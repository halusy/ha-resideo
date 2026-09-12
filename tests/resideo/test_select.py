"""Select entities: room priority and remote-sensor occupancy sensitivity."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .conftest import MAC, eid


async def test_room_priority_select_writes_current_rooms_and_status(
    hass: HomeAssistant, init_integration, mock_api
) -> None:
    """Changing mode must not discard the room selection returned by ``/priority``."""
    entity_id = eid(hass, "select", f"{MAC}_room_priority")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "PickARoom"
    assert state.attributes["options"] == ["PickARoom", "FollowMe"]

    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity_id, "option": "FollowMe"}, blocking=True
    )

    mock_api.async_set_priority.assert_awaited_once_with(MAC, "FollowMe", [1], status="NoHold")
    assert hass.states.get(entity_id).state == "FollowMe"


async def test_priority_room_select_uses_the_room_id_and_enables_pick_a_room(
    hass: HomeAssistant, init_integration, mock_api
) -> None:
    """The room select maps the sensor's room name to ``SelectedRooms``' group-room ID."""
    entity_id = eid(hass, "select", f"{MAC}_priority_room")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "Guest Room"
    assert state.attributes["options"] == ["Master Bedroom", "Guest Room"]

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id, "option": "Master Bedroom"},
        blocking=True,
    )

    mock_api.async_set_priority.assert_awaited_once_with(MAC, "PickARoom", [0], status="NoHold")
    assert hass.states.get(entity_id).state == "Master Bedroom"
