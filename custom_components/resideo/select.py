"""Select platform for the Resideo integration.

Controls include a thermostat's **Room priority** and a remote room-sensor's **Occupancy
sensitivity** (``accessoryValue`` ``sensitivity`` → read ``OccupancySensitivity``;
``resideo-api-spec.md`` §10).

The remote-sensor setting is **eventually-consistent**: the API accepts the write (``202``) but the
battery-powered wireless sensor only applies it on its next check-in, so there is no immediate
read-back (§10.4). Its entity holds the chosen value optimistically and clears it only once a later
refresh actually reports it — there is **no reconcile timer** (a fixed delay would wrongly snap the
UI back before the sensor has checked in).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .aioresideo.const import (
    OCCUPANCY_SENSITIVITY_OPTIONS,
    PRIORITY_FOLLOW_ME,
    PRIORITY_PICK_A_ROOM,
    SETPOINT_PERMANENT_HOLD,
)
from .aioresideo.exceptions import ResideoError
from .coordinator import ResideoConfigEntry, ResideoDataUpdateCoordinator
from .entity import OptimisticWriteMixin, ResideoAccessoryEntity, ResideoEntity

# Writes are commands; serialize service calls per platform (reads are pure push).
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ResideoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Resideo selects."""
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = []
    for mac, data in coordinator.data.items():
        if data.priority.priority_type in ROOM_PRIORITY_OPTIONS:
            entities.append(ResideoRoomPrioritySelect(coordinator, mac))
            if any(room.id is not None for room in data.rooms.rooms):
                entities.append(ResideoPriorityRoomSelect(coordinator, mac))
        for room, accessory in data.rooms.air_sensor_accessories():
            if accessory.occupancy_sensitivity is not None:
                entities.append(
                    ResideoOccupancySensitivitySelect(coordinator, mac, room, accessory)
                )
    async_add_entities(entities)


ROOM_PRIORITY_OPTIONS = (PRIORITY_PICK_A_ROOM, PRIORITY_FOLLOW_ME)


class ResideoRoomPrioritySelect(OptimisticWriteMixin, ResideoEntity, SelectEntity):
    """Choose the thermostat's room-priority mode.

    The API also carries ``SelectedRooms``. This mode control keeps that selection unchanged;
    :class:`ResideoPriorityRoomSelect` changes it.
    """

    _attr_translation_key = "room_priority"
    _attr_options = list(ROOM_PRIORITY_OPTIONS)

    def __init__(self, coordinator: ResideoDataUpdateCoordinator, mac: str) -> None:
        super().__init__(coordinator, mac)
        self._attr_unique_id = f"{mac}_room_priority"

    def _confirmed_values(self) -> dict[str, Any] | None:
        priority = self.priority
        if priority is None:
            return None
        return {"current_option": priority.priority_type}

    @property
    def current_option(self) -> str | None:
        if "current_option" in self._optimistic:
            return self._optimistic["current_option"]
        priority = self.priority
        return priority.priority_type if priority else None

    async def async_select_option(self, option: str) -> None:
        priority = self.priority
        if priority is None or priority.priority_type not in ROOM_PRIORITY_OPTIONS:
            raise HomeAssistantError("Room priority is unavailable")
        try:
            await self.coordinator.api.async_set_priority(
                self._mac,
                option,
                priority.selected_rooms,
                status=priority.priority_status or SETPOINT_PERMANENT_HOLD,
            )
        except ResideoError as err:
            raise HomeAssistantError(f"Failed to set room priority: {err}") from err
        await self._async_post_write({"current_option": option})


class ResideoPriorityRoomSelect(OptimisticWriteMixin, ResideoEntity, SelectEntity):
    """Choose one room whose sensors drive the thermostat in ``PickARoom`` mode.

    Resideo's ``SelectedRooms`` API field contains group-room IDs, rather than accessory IDs.
    A room may have more than one sensor; the T9/T10 manual-priority UI chooses one room, so this
    entity sends exactly one room ID.
    """

    _attr_translation_key = "priority_room"

    def __init__(self, coordinator: ResideoDataUpdateCoordinator, mac: str) -> None:
        super().__init__(coordinator, mac)
        self._attr_unique_id = f"{mac}_priority_room"

    @property
    def _room_options(self) -> dict[str, int]:
        """Map unique, user-visible room names to the API's room IDs."""
        rooms = [room for room in (self.rooms.rooms if self.rooms else []) if room.id is not None]
        names = [room.name or f"Room {room.id}" for room in rooms]
        return {
            name if names.count(name) == 1 else f"{name} ({room.id})": room.id
            for room, name in zip(rooms, names, strict=True)
        }

    @property
    def options(self) -> list[str]:
        return list(self._room_options)

    def _confirmed_values(self) -> dict[str, Any] | None:
        priority = self.priority
        if priority is None:
            return None
        selected = priority.selected_rooms
        if len(selected) != 1:
            return {"current_option": None}
        room_id = selected[0]
        return {
            "current_option": next(
                (name for name, option_id in self._room_options.items() if option_id == room_id),
                None,
            )
        }

    @property
    def current_option(self) -> str | None:
        if "current_option" in self._optimistic:
            return self._optimistic["current_option"]
        return self._confirmed_values()["current_option"] if self.priority else None

    async def async_select_option(self, option: str) -> None:
        priority = self.priority
        room_id = self._room_options.get(option)
        if priority is None or room_id is None:
            raise HomeAssistantError("Priority room is unavailable")
        try:
            await self.coordinator.api.async_set_priority(
                self._mac,
                PRIORITY_PICK_A_ROOM,
                [room_id],
                status=priority.priority_status or SETPOINT_PERMANENT_HOLD,
            )
        except ResideoError as err:
            raise HomeAssistantError(f"Failed to set priority room: {err}") from err
        await self._async_post_write({"current_option": option})


class ResideoOccupancySensitivitySelect(
    OptimisticWriteMixin, ResideoAccessoryEntity, SelectEntity
):
    """A remote sensor's occupancy-sensitivity select (optimistic, reconcile-on-report)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "occupancy_sensitivity"
    _attr_options = list(OCCUPANCY_SENSITIVITY_OPTIONS)
    # Sensitivity is eventually-consistent (applied at the battery sensor's next check-in), so
    # there is NO reconcile timer — a fixed delay would wrongly snap the UI back before the
    # sensor has checked in. The optimistic value is held until a refresh reports it (e.g. the
    # periodic reconnect resync, or a Sensor push that carries it).
    _reconcile_delay = None

    def __init__(
        self,
        coordinator: ResideoDataUpdateCoordinator,
        mac: str,
        room,
        accessory,
    ) -> None:
        super().__init__(
            coordinator, mac, room.id, accessory.accessory_id, room.name, accessory.model
        )
        self._attr_unique_id = (
            f"{mac}_room{room.id}_acc{accessory.accessory_id}_occupancy_sensitivity"
        )

    def _confirmed_values(self) -> dict[str, Any] | None:
        accessory = self.accessory
        if accessory is None:
            return None
        return {"current_option": accessory.occupancy_sensitivity}

    @callback
    def _on_optimistic_cleared(self, key: str) -> None:
        self.coordinator.accessory_override(self._mac, self._accessory_id).pop(
            "sensitivity", None
        )

    @property
    def current_option(self) -> str | None:
        if "current_option" in self._optimistic:
            return self._optimistic["current_option"]
        accessory = self.accessory
        return accessory.occupancy_sensitivity if accessory else None

    async def async_select_option(self, option: str) -> None:
        accessory = self.accessory
        if accessory is None:
            raise HomeAssistantError("Accessory is unavailable")
        # Full-body write composed from the accessory's shared overrides (carries the current
        # excludes; see ResideoDataUpdateCoordinator.async_write_accessory_value).
        try:
            await self.coordinator.async_write_accessory_value(
                self._mac, self._accessory_id, accessory, field="sensitivity", value=option
            )
        except ResideoError as err:
            raise HomeAssistantError(f"Failed to set occupancy sensitivity: {err}") from err
        await self._async_post_write({"current_option": option})
