"""Adaptive Heating: a thermostat per room, between the room's sensors and its heaters."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import voluptuous as vol
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.helpers.service import async_register_platform_entity_service
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    EXCLUDE_LABEL,
    HEATING_LABEL,
    LABELS_STORAGE_KEY,
    PLATFORMS,
    ROOM_AREAS_STORAGE_KEY,
    STORAGE_VERSION,
    VOCABULARY_VERSION,
)
from .core import actions as action_table
from .core.identity import (
    DeviceMove,
    RoomIdentity,
    follow_the_device,
    identify,
    moved,
    refuse_move,
)
from .core.rooms import Candidate, Room, changed, rooms

__all__ = ["DOMAIN", "VOCABULARY_VERSION"]

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

UNUSABLE = ("unknown", "unavailable", "")


@dataclass(slots=True)
class House:
    """The rooms the registries describe, and each platform's way of adding one room more."""

    # Keyed by room id. Each room carries the area it is in now.
    rooms: dict[str, Room] = field(default_factory=dict)
    # Room id to area id, kept across a restart, including for a room that is not present now.
    links: dict[str, str] = field(default_factory=dict)
    # The highest room number ever issued, kept beside the links. It never goes down.
    highest_room: int = 0
    links_store: Store | None = None
    # Label ids as the add-on's House tab chose them, kept so a core restart finds the same rooms before
    # the add-on has spoken. An empty include label lets every candidate through.
    include_label: str = HEATING_LABEL
    exclude_label: str = EXCLUDE_LABEL
    add_a_room: Callable[[Room], None] | None = None
    add_a_reason: Callable[[Room], None] | None = None
    # The room's reason sensor, keyed by room id: the loop tells it, and a room going away removes it.
    reason_sensors: dict[str, Any] = field(default_factory=dict)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """The six room actions and the house's labels action, declared before any room is set up.

    Registering them here rather than from the climate platform is what makes them exist even
    where no room loads, which is what an automation naming one is validated against.
    """
    for action in action_table.ACTIONS:
        async_register_platform_entity_service(
            hass,
            DOMAIN,
            action.name,
            entity_domain=CLIMATE_DOMAIN,
            func=f"async_{action.name}",
            # Only the helper's own builder produces a schema the platform accepts, and its
            # default refuses a field it does not know. Removing one instead is what lets a newer
            # add-on talk to an older integration without either half gating on a version.
            schema=cv.make_entity_service_schema(
                action.fields_for_the_schema(), extra=vol.REMOVE_EXTRA
            ),
        )

    labels: Store = Store(hass, STORAGE_VERSION, LABELS_STORAGE_KEY)

    async def set_labels(call: ServiceCall) -> None:
        include = call.data.get("include_label", HEATING_LABEL)
        exclude = call.data.get("exclude_label") or EXCLUDE_LABEL
        await labels.async_save({"include_label": include, "exclude_label": exclude})
        for entry in hass.config_entries.async_entries(DOMAIN):
            # An entry not yet set up has no house; it reads the store above when it is.
            house = getattr(entry, "runtime_data", None)
            if not isinstance(house, House):
                continue
            if (house.include_label, house.exclude_label) == (include, exclude):
                continue
            house.include_label, house.exclude_label = include, exclude
            await _follow_the_registries(hass, entry)

    for action in action_table.HOUSE_ACTIONS:
        hass.services.async_register(
            DOMAIN,
            action.name,
            set_labels,
            schema=vol.Schema(action.fields_for_the_schema(), extra=vol.REMOVE_EXTRA),
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # One entry for the house. The shared table is keyed by the room id.
    hass.data.setdefault(DOMAIN, {})
    stored = await Store(hass, STORAGE_VERSION, LABELS_STORAGE_KEY).async_load() or {}
    links_store: Store = Store(hass, STORAGE_VERSION, ROOM_AREAS_STORAGE_KEY)
    linked = await links_store.async_load() or {}
    house = House(
        links={str(room): str(area) for room, area in linked.get("links", {}).items()},
        highest_room=int(linked.get("highest_room", 0)),
        links_store=links_store,
        include_label=stored.get("include_label", HEATING_LABEL),
        exclude_label=stored.get("exclude_label") or EXCLUDE_LABEL,
    )
    house.rooms = await _resolve_and_keep(hass, house)
    entry.runtime_data = house
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def the_registries_changed(_event: Event) -> None:
        await _follow_the_registries(hass, entry)

    for registry_event in (
        ar.EVENT_AREA_REGISTRY_UPDATED,
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        lr.EVENT_LABEL_REGISTRY_UPDATED,
    ):
        entry.async_on_unload(hass.bus.async_listen(registry_event, the_registries_changed))

    async def a_device_moved(event: Event) -> None:
        if event.data.get("action") == "update" and "area_id" in event.data.get("changes", {}):
            await _follow_the_device(hass, entry, event.data["device_id"])

    entry.async_on_unload(hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, a_device_moved))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.pop(DOMAIN, None)
    return unloaded


@callback
def resolve(hass: HomeAssistant, house: House) -> tuple[dict[str, Room], dict[str, str], int]:
    """The rooms the registries describe right now, keyed by room id, the links with any new room, and the highest number."""
    areas = ar.async_get(hass)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    by_area = rooms(
        {area.id: area.labels for area in areas.async_list_areas()},
        [_candidate(hass, devices, known) for known in entities.entities.values()],
        DOMAIN,
        house.include_label,
        house.exclude_label,
    )
    found, links, highest = identify(by_area, house.links, house.highest_room)
    return {
        room_id: replace(by_area[area_id], room_id=room_id) for room_id, area_id in found.items()
    }, links, highest


async def _resolve_and_keep(hass: HomeAssistant, house: House) -> dict[str, Room]:
    """Resolves, and writes a new room's link down before its thermostat exists."""
    now, links, highest = resolve(hass, house)
    if links != house.links or highest != house.highest_room:
        house.links, house.highest_room = links, highest
        await _save_the_links(house)
    return now


async def _save_the_links(house: House) -> None:
    if house.links_store is not None:
        await house.links_store.async_save({"links": house.links, "highest_room": house.highest_room})


async def move_room(hass: HomeAssistant, entry: ConfigEntry, room_id: str, to_area: str) -> None:
    """Places a room in another area. Its unique id, device, store and history stay as they are."""
    house: House = entry.runtime_data
    present = {one: room.area_id for one, room in house.rooms.items()}
    if present.get(room_id) == to_area:
        return
    areas = ar.async_get(hass)
    refusal = refuse_move(room_id, to_area, present, (one.id for one in areas.async_list_areas()))
    if refusal is not None:
        raise ServiceValidationError(refusal)
    await _link(hass, entry, room_id, to_area)


async def _link(hass: HomeAssistant, entry: ConfigEntry, room_id: str, to_area: str) -> None:
    """The link, the device and the room's card all in `to_area`, the room's id untouched."""
    house: House = entry.runtime_data
    # Written first, so the device's own registry event finds the link already there.
    house.links = moved(house.links, room_id, to_area)
    await _save_the_links(house)
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={RoomIdentity(room_id).device_identifier})
    area = ar.async_get(hass).async_get_area(to_area)
    if device is not None:
        # The integration's own device name was the area's when the room was created, so it follows the area.
        # A name a person gave the device is kept apart by Home Assistant and stays.
        registry.async_update_device(
            device.id, area_id=to_area, name=to_area if area is None else area.name
        )
    await _follow_the_registries(hass, entry)


async def _follow_the_device(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> None:
    """A room's device placed in another area by hand takes the room there, unless one is there."""
    house: House = entry.runtime_data
    registry = dr.async_get(hass)
    device = registry.async_get(device_id)
    if device is None:
        return
    room_id = next((key for domain, key in device.identifiers if domain == DOMAIN), None)
    if room_id is None or room_id not in house.links:
        return
    move, refusal = follow_the_device(
        room_id,
        device.area_id,
        house.links,
        {one: room.area_id for one, room in house.rooms.items()},
        (one.id for one in ar.async_get(hass).async_list_areas()),
    )
    if move is DeviceMove.NOTHING:
        return
    if move is DeviceMove.PUT_BACK:
        _LOGGER.warning(
            "Room %s stays in area %s, not %s: %s",
            room_id, house.links[room_id], device.area_id, refusal,
        )
        registry.async_update_device(device.id, area_id=house.links[room_id])
        return
    await _link(hass, entry, room_id, device.area_id)  # type: ignore[arg-type]


@callback
def _candidate(
    hass: HomeAssistant, devices: dr.DeviceRegistry, known: er.RegistryEntry
) -> Candidate:
    device = None if known.device_id is None else devices.async_get(known.device_id)
    state = hass.states.get(known.entity_id)
    return Candidate(
        known.entity_id,
        # An entity's own area wins; most heaters take theirs from the device instead.
        known.area_id if known.area_id else (None if device is None else device.area_id),
        frozenset(known.labels),
        known.platform,
        known.hidden_by is not None,
        state is not None and state.state not in UNUSABLE,
        known.device_id,
        known.device_class or known.original_device_class,
        _members(state),
    )


def _members(state: Any) -> tuple[str, ...]:
    """A group helper's own entities, which it lists under `entity_id`. Nothing else carries that."""
    listed = None if state is None else state.attributes.get("entity_id")
    if isinstance(listed, (list, tuple)):
        return tuple(one for one in listed if isinstance(one, str))
    return ()


async def _follow_the_registries(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """A room appears, leaves or changes area without the entry reloading, so no other room loses its state."""
    house: House = entry.runtime_data
    now = await _resolve_and_keep(hass, house)
    new, gone = changed(house.rooms, now)
    elsewhere = [
        room_id
        for room_id, room in now.items()
        if room_id in house.rooms and house.rooms[room_id].area_id != room.area_id
    ]
    if not new and not gone and not elsewhere:
        return
    house.rooms = now
    for room_id in gone:
        reason = house.reason_sensors.get(room_id)
        if reason is not None:
            await reason.async_remove()
        thermostat = hass.data.get(DOMAIN, {}).get(room_id)
        if thermostat is not None:
            # Its registry entry stays, so a room coming back keeps its entity id and its store.
            await thermostat.async_remove()
    for room_id in elsewhere:
        thermostat = hass.data.get(DOMAIN, {}).get(room_id)
        if thermostat is not None:
            thermostat.follow_the_area(now[room_id])
    for room_id in new:
        if house.add_a_room is not None:
            house.add_a_room(now[room_id])
        if house.add_a_reason is not None:
            house.add_a_reason(now[room_id])
