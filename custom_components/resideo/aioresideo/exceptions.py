"""Exceptions raised by aioresideo."""

from __future__ import annotations

from typing import Any


class ResideoError(Exception):
    """Base error for all aioresideo failures."""


class ResideoAuthError(ResideoError):
    """Authentication / token failure (HTTP 401, invalid credentials, expired refresh token).

    Carries the failing ``step`` of the Auth0 flow, the HTTP ``status``, and the normalized
    Auth0 error ``code`` (e.g. ``invalid_captcha``) when the response supplied one, so callers
    can tell "wrong password" apart from "the flow itself broke".
    """

    def __init__(
        self,
        message: str,
        *,
        step: str | None = None,
        status: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.step = step
        self.status = status
        self.code = code


class ResideoConnectionError(ResideoError):
    """Network/transport error talking to api.ha.resideo.com (timeouts, DNS, TLS, ...)."""


class ResideoApiError(ResideoError):
    """A non-2xx API response that is not an authentication failure.

    Carries the HTTP ``status`` and parsed ``body`` (when available) for diagnostics.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class ResideoUnavailableError(ResideoApiError):
    """HTTP 503 — Resideo's edge is refusing the request outright.

    Raised for *any* 503, not just the "planned maintenance" wording: that body is hand-written
    on Resideo's side and may be reworded, and the edge returns it before authentication, so
    there is nothing else to key on. ``service_message`` is Resideo's own text when the body
    carried one, meant to be shown to the user verbatim.

    Worth knowing when this fires: a 503 that *persists* is how Resideo retires a host. In
    September 2026 it moved the consumer API to ``api.ha.resideo.com`` and left the old host
    answering "The API is temporarily down for planned maintenance" indefinitely, while the
    First Alert app — already pointed at the new host — kept working. So this error means
    "Resideo is refusing us", never "Resideo is down"; see ``availability.py`` for how that
    distinction reaches the user.
    """

    def __init__(self, message: str, *, service_message: str | None, body: Any = None) -> None:
        super().__init__(message, status=503, body=body)
        self.service_message = service_message


def edge_message(body: Any) -> str | None:
    """Resideo's own explanation out of an edge error body, if it carried one.

    Both ``api.resideo.com`` and ``api.ha.resideo.com`` sit behind the same Azure Front Door and
    render gateway-level errors as ``{"statusCode": N, "message": "..."}``, so this shape is
    portable across the hosts. Backend errors come from Envoy and usually have no body at all.
    """
    if not isinstance(body, dict):
        return None
    message = body.get("message")
    return message if isinstance(message, str) and message else None
