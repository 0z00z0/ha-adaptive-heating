"""Why a room is not heating, as an entity of its own.

An enum sensor rather than an attribute, so the words are the household's and a dashboard or an
automation can read the verdict without parsing a sentence.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .core.identity import RoomIdentity
from .core.reasons import NotHeating
from .core.rooms import Room


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    house = entry.runtime_data

    @callback
    def add_a_reason(room: Room) -> None:
        async_add_entities([WhyItIsNotHeating(hass, entry, room)])

    house.add_a_reason = add_a_reason
    async_add_entities([WhyItIsNotHeating(hass, entry, room) for room in house.rooms.values()])


class WhyItIsNotHeating(SensorEntity):
    """One room's verdict. Unknown while the room is heating, because there is nothing to say."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    # Carries the states' words in the strings files, and the entity's own name with them.
    _attr_translation_key = "not_heating_because"
    # Every member, so a reason newly reachable from the loop is a state the platform accepts.
    _attr_options = [str(reason) for reason in NotHeating]

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, room: Room) -> None:
        self.hass = hass
        self._house = entry.runtime_data
        identity = RoomIdentity(room.room_id)
        self._room_id = identity.room_id
        self._attr_unique_id = identity.reason_unique_id
        area = ar.async_get(hass).async_get_area(room.area_id)
        self._attr_device_info = DeviceInfo(
            identifiers={identity.device_identifier},
            name=room.area_id if area is None else area.name,
            manufacturer="Adaptive Heating",
        )

    @property
    def native_value(self) -> str | None:
        room = self.hass.data.get(DOMAIN, {}).get(self._room_id)
        reason = None if room is None else room.not_heating_because
        return None if reason is None else str(reason)

    async def async_added_to_hass(self) -> None:
        # The room's own loop decides; this follows what it wrote rather than evaluating again.
        self._house.reason_sensors[self._room_id] = self

    async def async_will_remove_from_hass(self) -> None:
        if self._house.reason_sensors.get(self._room_id) is self:
            self._house.reason_sensors.pop(self._room_id)
