"""Telling the user what a 503 from Resideo actually means.

Resideo's edge answers a refused request with ``503 {"statusCode":503,"message":"..."}`` before
authentication, as a blanket path policy. That looks identical whether Resideo is genuinely down
or has simply stopped serving the address we use — and in September 2026 it was the latter: the
consumer API moved to ``api.ha.resideo.com`` and the old host kept answering "The API is
temporarily down for planned maintenance" indefinitely, while the phone app, already pointed at
the new host, carried on working.

Nothing in the response distinguishes the two cases. Two things do, and both are in the message
we show: **how long it has lasted**, and **whether the First Alert app still works**. So this
module deliberately never promises that waiting will fix it.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .aioresideo.exceptions import ResideoUnavailableError
from .const import CLOUD_UNAVAILABLE_ISSUE, DOMAIN

# Shown as "Learn more" on the repair card. The description can't carry links: hassfest rejects
# any URL in a translated string (script/hassfest/translations.py, RE_URL).
LEARN_MORE_URL = "https://github.com/sfcodes/ha-resideo/issues"


def unavailable_reason(err: ResideoUnavailableError) -> str:
    """The one-line failure reason for the integration card and the log.

    Deliberately states only what happened. Earlier wording here promised Home Assistant would
    "keep retrying automatically" and that the problem would clear itself — both were false for
    the case that actually occurred, and the reassurance is what stopped anyone looking further.
    """
    if err.service_message:
        return f'Resideo answered HTTP 503 for every request. Resideo says: "{err.service_message}"'
    return "Resideo answered HTTP 503 (service unavailable) for every request."


def _issue_id(entry: ConfigEntry) -> str:
    """Per-entry, so two Resideo accounts don't fight over one card."""
    return f"{CLOUD_UNAVAILABLE_ISSUE}_{entry.entry_id}"


@callback
def async_report_unavailable(
    hass: HomeAssistant, entry: ConfigEntry, err: ResideoUnavailableError
) -> None:
    """Raise (or leave standing) the Repairs card for a cloud that is refusing us.

    Safe to call on every failure. ``async_get_or_create`` only writes and fires an event when
    something actually changed, and it preserves both ``created`` and the user's ``dismissed_version``
    — so a re-report during a long outage is free, and dismissing the card makes it stay dismissed.

    That preserved ``created`` is also where the start time comes from: it survives coordinator
    rebuilds *and* a Home Assistant restart (the registry writes it for non-persistent issues too),
    which is why there is no timestamp of our own anywhere. It is read back here so ``since`` stays
    byte-identical across re-reports, keeping them genuine no-ops.
    """
    existing = ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(entry))
    since = existing.created if existing is not None else dt_util.utcnow()
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(entry),
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=CLOUD_UNAVAILABLE_ISSUE,
        translation_placeholders={
            "since": dt_util.as_local(since).strftime("%Y-%m-%d %H:%M"),
            "message": err.service_message or "(no message)",
        },
        learn_more_url=LEARN_MORE_URL,
    )


@callback
def async_clear_unavailable(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the card once anything gets through. No-ops when there is no card.

    Only ever called on a real success — never on unload. Deleting the issue also destroys its
    ``created``, and a config-entry *reload* (which reauth triggers) goes through unload, so
    clearing there would silently reset the outage clock the message depends on.
    """
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))
