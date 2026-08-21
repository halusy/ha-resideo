"""Stream-side tests: event parsing + location grouping (no live socket)."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.resideo.aioresideo import (
    ResideoChangeConfirm,
    ResideoLiveFeed,
    ResideoStream,
    parse_event,
)
from custom_components.resideo.aioresideo.client import ResideoClient
from custom_components.resideo.aioresideo.const import SIGNALR_FEED_RECONNECT_MARGIN


def test_parse_live_feed_setpoint(fixture_loader) -> None:
    ev = parse_event(fixture_loader("live_setpoint.json"))
    assert isinstance(ev, ResideoLiveFeed)
    assert ev.device_id == "AABBCCDDEEFF"
    assert ev.property_name == "Setpoint"
    assert ev.value["CoolSetpoint"] == 77
    assert ev.subscription_expiration == "2026-06-19T18:38:10+00:00"


def test_parse_from_raw_string(fixture_loader) -> None:
    # the hub delivers each ``events`` argument as a JSON STRING, not a dict
    ev = parse_event(json.dumps(fixture_loader("live_operation_status.json")))
    assert isinstance(ev, ResideoLiveFeed)
    assert ev.property_name == "OperationStatus"
    assert ev.value["Mode"] == "Heat"


def test_parse_change_request(fixture_loader) -> None:
    ev = parse_event(fixture_loader("change_request_success.json"))
    assert isinstance(ev, ResideoChangeConfirm)
    assert ev.success is True
    assert ev.transaction_id == "RHIE-qLo2sThYMXL"
    assert ev.change_name == "changeSetpoint"
    assert ev.change_direction == "AppInitiated"


def test_parse_garbage_returns_none() -> None:
    assert parse_event("not json") is None
    assert parse_event({"NotificationType": "SomethingElse", "Body": {}}) is None
    assert parse_event(123) is None  # type: ignore[arg-type]


def test_iter_locations(accounts) -> None:
    targets = ResideoClient.iter_locations(accounts)
    assert len(targets) == 1
    target = targets[0]
    assert target.node_id == (
        "Q29uc3VtZXJEZXZpY2VMb2NhdGlvbjowMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDA="
    )
    assert target.name == "Home"
    # all devices in the location (thermostat + smoke); the caller intersects with thermostats
    assert target.device_ids == ("AABBCCDDEEFF", "DDEEFFAABBCC")


def _stream() -> ResideoStream:
    return ResideoStream(None, "node", ["AABBCCDDEEFF"], lambda _ev: None)


def test_feed_expiry_accepts_a_future_stamp() -> None:
    """A believable SubscriptionExpiration shortens/sets the pre-expiry reconnect deadline."""
    stream = _stream()
    soon = datetime.now(UTC) + timedelta(seconds=SIGNALR_FEED_RECONNECT_MARGIN + 300)
    stream._note_expiry(soon.isoformat())
    assert stream._feed_expiry == pytest.approx(soon.timestamp())


def test_feed_expiry_ignores_a_stale_stamp() -> None:
    """The cloud stamps pushes with an already-expired SubscriptionExpiration (observed ~800s
    stale). Adopting it would trip the pre-expiry reconnect on the next keepalive tick, and since
    every push carries one the client would reconnect every ~16s forever."""
    stream = _stream()
    stream._feed_expiry = time.time() + 600  # the TTL fallback set at connect
    for stale in (
        datetime.now(UTC) - timedelta(seconds=812),  # observed live, 2026-08-21
        datetime.now(UTC) + timedelta(seconds=SIGNALR_FEED_RECONNECT_MARGIN - 1),  # inside margin
    ):
        stream._note_expiry(stale.isoformat())
        assert stream._feed_expiry == pytest.approx(time.time() + 600, abs=5)  # unchanged
    stream._note_expiry("not-a-timestamp")
    assert stream._feed_expiry == pytest.approx(time.time() + 600, abs=5)
