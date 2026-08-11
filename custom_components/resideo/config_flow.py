"""Config flow for the Resideo integration.

Three auth paths against the consumer API (no developer account):
  - ``login``   — email/password via ``aioresideo.ResideoAuth`` (Auth0), headless.
  - ``browser`` — open Auth0's own sign-in page, paste the redirect back. The only path
    that survives a bot-detection CAPTCHA, since a human drives the page.
  - ``manual``  — paste a refresh token grabbed by proxying ``login.resideo.com``.

Entries are deduped by the Auth0 ``sub`` claim of the access token (the account identity),
which also guards re-auth against silently rewiring an entry to a different account.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .aioresideo import (
    AuthorizeRequest,
    Resideo,
    ResideoAuth,
    build_authorize_url,
    decode_jwt_claims,
    parse_authorize_redirect,
)
from .aioresideo.exceptions import (
    ResideoAuthError,
    ResideoConnectionError,
    ResideoError,
)
from .const import CONF_REDIRECT_URL, CONF_REFRESH_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_LOGIN_SCHEMA = vol.Schema(
    {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
)
STEP_MANUAL_SCHEMA = vol.Schema({vol.Required(CONF_REFRESH_TOKEN): str})
STEP_BROWSER_SCHEMA = vol.Schema({vol.Required(CONF_REDIRECT_URL): str})

AUTH_MENU = ["login", "browser", "manual"]

# Auth0 error code -> form-error key. Anything unrecognised (including a failure in the
# login flow's own mechanics) falls to ``login_failed`` rather than blaming the credentials.
_AUTH_ERROR_KEYS = {
    "invalid_credentials": "invalid_auth",
    "invalid_captcha": "captcha_required",
    "too_many_attempts": "too_many_attempts",
    "blocked_user": "too_many_attempts",
    # Browser path: the paste itself was wrong, not the account.
    "invalid_code": "invalid_code",
    "state_mismatch": "state_mismatch",
}


def _auth_error(err: ResideoAuthError, *, token_path: bool = False) -> tuple[str, str]:
    """Map an auth failure to a ``(form-error key, detail)`` pair.

    ``detail`` is interpolated into the message so a screenshot of the form is enough to
    diagnose the failure — the whole point being that "Invalid authentication" alone is not.
    """
    key = _AUTH_ERROR_KEYS.get(err.code or "", "login_failed")
    if token_path and key in ("invalid_auth", "login_failed"):
        # A pasted refresh token was rejected; nothing to say about an email/password.
        key = "invalid_token"
    detail = ": ".join(part for part in (err.step, err.code) if part) or str(err)
    return key, detail


class ResideoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Resideo."""

    VERSION = 1

    def __init__(self) -> None:
        # Held between the two halves of the browser step: the user leaves to sign in,
        # and the PKCE verifier + state must still be here when they paste the redirect.
        self._authorize: AuthorizeRequest | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step: pick how to authenticate."""
        return self.async_show_menu(step_id="user", menu_options=AUTH_MENU)

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Email/password login via aioresideo (Auth0)."""
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                tokens = await ResideoAuth(session).login(
                    user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
            except ResideoAuthError as err:
                errors["base"], detail = _auth_error(err)
                _LOGGER.debug("Resideo login failed (%s): %s", errors["base"], err)
            except (ResideoConnectionError, ResideoError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Resideo login")
                errors["base"] = "unknown"
            else:
                return await self._finish(
                    tokens.get("refresh_token"),
                    access_token=tokens.get("access_token"),
                    email=user_input[CONF_EMAIL],
                )
        return self.async_show_form(
            step_id="login",
            data_schema=STEP_LOGIN_SCHEMA,
            errors=errors,
            description_placeholders={"detail": detail},
        )

    async def async_step_browser(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in via Auth0's own page in the user's browser, then paste the redirect back.

        Auth0's bot detection can demand a CAPTCHA that a headless client cannot solve; here
        the human drives the page, so the CAPTCHA is simply part of signing in. The redirect
        lands on the mobile app's custom scheme, which the browser cannot open — the URL is
        still in the address bar, and that is what gets pasted.
        """
        errors: dict[str, str] = {}
        detail = ""
        if self._authorize is None:
            self._authorize = build_authorize_url()
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                code = parse_authorize_redirect(
                    user_input[CONF_REDIRECT_URL], self._authorize.state
                )
                tokens = await ResideoAuth(session).exchange_code(
                    code, self._authorize.code_verifier
                )
            except ResideoAuthError as err:
                errors["base"], detail = _auth_error(err)
                _LOGGER.debug("Resideo browser sign-in failed (%s): %s", errors["base"], err)
                # A spent or mismatched code can't be retried — start a fresh authorization.
                self._authorize = build_authorize_url()
            except (ResideoConnectionError, ResideoError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Resideo browser sign-in")
                errors["base"] = "unknown"
            else:
                return await self._finish(
                    tokens.get("refresh_token"), access_token=tokens.get("access_token")
                )
        return self.async_show_form(
            step_id="browser",
            data_schema=STEP_BROWSER_SCHEMA,
            errors=errors,
            description_placeholders={"url": self._authorize.url, "detail": detail},
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual refresh-token entry."""
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            refresh_token = user_input[CONF_REFRESH_TOKEN]
            api = Resideo(session, refresh_token=refresh_token)
            try:
                await api.client.async_ensure_token()  # validate the token works
            except ResideoAuthError as err:
                errors["base"], detail = _auth_error(err, token_path=True)
                _LOGGER.debug("Resideo token validation failed: %s", err)
            except (ResideoConnectionError, ResideoError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating a Resideo refresh token")
                errors["base"] = "unknown"
            else:
                # The refresh may have rotated the token; persist the latest one.
                return await self._finish(
                    api.refresh_token or refresh_token,
                    access_token=api.tokens.get("access_token"),
                )
        return self.async_show_form(
            step_id="manual",
            data_schema=STEP_MANUAL_SCHEMA,
            errors=errors,
            description_placeholders={"detail": detail},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Re-authenticate an existing entry (token expired/revoked)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick how to re-authenticate (same paths as setup)."""
        return self.async_show_menu(step_id="reauth_confirm", menu_options=AUTH_MENU)

    async def _finish(
        self,
        refresh_token: str | None,
        *,
        access_token: str | None = None,
        email: str | None = None,
    ) -> ConfigFlowResult:
        """Create the entry, or update it in place when re-authenticating."""
        if not refresh_token:
            return self.async_abort(reason="no_token")
        # The Auth0 ``sub`` claim identifies the account (no extra API call needed).
        sub = (decode_jwt_claims(access_token) or {}).get("sub")
        if sub:
            await self.async_set_unique_id(sub)
        else:
            _LOGGER.debug("Access token carried no decodable `sub`; skipping unique_id")
        if self.source == SOURCE_REAUTH:
            reauth_entry = self._get_reauth_entry()
            if sub and reauth_entry.unique_id:
                self._abort_if_unique_id_mismatch(reason="reauth_account_mismatch")
            if sub:
                # Adopt the unique_id on entries created before it was recorded.
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    unique_id=sub,
                    data_updates={CONF_REFRESH_TOKEN: refresh_token},
                )
            return self.async_update_reload_and_abort(
                reauth_entry,
                data_updates={CONF_REFRESH_TOKEN: refresh_token},
            )
        if sub:
            self._abort_if_unique_id_configured()
        title = f"Resideo ({email})" if email else "Resideo"
        return self.async_create_entry(title=title, data={CONF_REFRESH_TOKEN: refresh_token})
