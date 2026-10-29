"""The thermostat a room appears as, and the six actions that drive it."""

from __future__ import annotations

import asyncio
import logging
import operator
from collections.abc import Callable
from datetime import datetime, time, timedelta
from functools import reduce
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF, STATE_ON, UnitOfTemperature
from homeassistant.core import CALLBACK_TYPE, CoreState, Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EVALUATION_INTERVAL,
    INTEGRATION_VERSION,
    STORAGE_VERSION,
    STORAGE_WRITE_DELAY,
    VOCABULARY_VERSION,
)
from .core import card
from .core.defaults import STANDARD
from .core.freshness import when_it_reported
from .core.identity import RoomIdentity
from .core.loop import RelayObservation
from .core.reasons import Fault, NotHeating, Refused, issue_key
from .core.rooms import Room, named_or_discovered
from .core.sensors import NO_READING, RoomReading, borrow, read
from .core.serialisation import OneAtATime
from .core.setpoint import HEAT, OFF, ThermostatObservation, is_a_thermostat, observe
from .core.setup import heater_already_claimed
from .core.thermostat import Command, RoomThermostat, WindowState

_LOGGER = logging.getLogger(__name__)

UNUSABLE = ("unknown", "unavailable", "", None)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    house = entry.runtime_data

    @callback
    def add_a_room(room: Room) -> None:
        async_add_entities([AdaptiveHeatingThermostat(hass, entry, room)])

    house.add_a_room = add_a_room
    async_add_entities(
        [AdaptiveHeatingThermostat(hass, entry, room) for room in house.rooms.values()]
    )


class AdaptiveHeatingThermostat(ClimateEntity):
    """An ordinary climate entity, so every standard control works without this project."""

    _attr_has_entity_name = True
    _attr_name = None
    # Carries the custom preset names' translations in the strings files.
    _attr_translation_key = "room"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_should_poll = False
    # A class variable: the platform combines it once per subclass and reads nothing per instance.
    _unrecorded_attributes = card.EVERY_ATTRIBUTE

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, room: Room) -> None:
        self.hass = hass
        self._entry = entry
        # The room's own identity never changes; the area is where it is now.
        self._identity = RoomIdentity(room.room_id)
        self._room_id = self._identity.room_id
        self._area_id = room.area_id
        self._discovered_heaters: list[str] = list(room.heaters)
        self._discovered_sensors: list[str] = list(room.temperature_sensors)
        self._heaters: list[str] = list(room.heaters)
        self._sensors: list[str] = list(room.temperature_sensors)
        self._window_sensor: str | None = None
        self._outdoor_sensor: str | None = None
        self._neighbour: str | None = None
        self._power_sensor: str | None = None

        self._attr_unique_id = self._identity.unique_id
        area = ar.async_get(hass).async_get_area(room.area_id)
        self._attr_device_info = DeviceInfo(
            identifiers={self._identity.device_identifier},
            # A display name and nothing more. The device is placed in its Area by id once it
            # exists, because `suggested_area` takes a name and can create a second area where that
            # name does not match an existing one.
            name=room.area_id if area is None else area.name,
            manufacturer="Adaptive Heating",
        )
        self._thermostat = RoomThermostat(
            self._room_id, self._heaters, no_reading_at_all=not self._sensors
        )
        self._take_the_offer()
        self._store: Store = Store(hass, STORAGE_VERSION, self._identity.store_key)
        self._decision = None
        self._reading: RoomReading = NO_READING
        self._restarted_at: datetime | None = None
        self._outdoor_now: float | None = None
        self._one_at_a_time = OneAtATime(lambda: self._evaluate(dt_util.utcnow()))
        self._passes: set[asyncio.Task[None]] = set()
        self._watching_states: CALLBACK_TYPE | None = None
        self._fault_raised: Fault | None = None

    @callback
    def _take_the_offer(self) -> None:
        # The same for every room, whatever heats it: nothing of a thermostat underneath is copied.
        offered = card.offered(self._thermostat)
        self._attr_hvac_modes = [HVACMode(mode) for mode in offered.modes]
        self._attr_supported_features = reduce(
            operator.or_,
            (ClimateEntityFeature[name] for name in offered.features),
            ClimateEntityFeature(0),
        )
        self._attr_preset_modes = list(offered.presets)
        self._attr_min_temp = offered.minimum
        self._attr_max_temp = offered.maximum
        self._attr_target_temperature_step = offered.step

    # ----- the platform's own surface -----------------------------------------------------------

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if self._thermostat.switched_on else HVACMode.OFF

    @property
    def preset_mode(self) -> str | None:
        return self._thermostat.preset

    @property
    def hvac_action(self) -> HVACAction:
        if not self._thermostat.switched_on:
            return HVACAction.OFF
        if self._decision is not None and self._decision.heating:
            warm_up = self._thermostat.warm_up
            if warm_up is not None and warm_up.running(dt_util.utcnow()):
                return HVACAction.PREHEATING
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def not_heating_because(self) -> NotHeating | None:
        """What the room's own enum sensor publishes. Nothing of it reaches the card."""
        return None if self._decision is None else self._decision.reason

    @property
    def current_temperature(self) -> float | None:
        return self._reading.temperature

    @property
    def target_temperature(self) -> float | None:
        # A room with no reading has no target: its heater's own dial decides, and a number here would
        # be one nothing in the room can perceive.
        if self._thermostat.no_reading_at_all:
            return None

        # A switched-off thermostat shows the temperature it would hold.
        return self._thermostat.temperature_it_would_hold(dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return card.attributes(
            self._room_id,
            self._area_id,
            INTEGRATION_VERSION,
            VOCABULARY_VERSION,
            self._thermostat,
            self._decision,
            self._reading,
            self._outdoor_now,
            self._power_sensor is not None,
        )

    async def async_added_to_hass(self) -> None:
        # Set up while the core is still coming up means every state in the machine carries the
        # restart moment, whatever the sensor behind it is doing. Set up on a core already running
        # means the times are the sensors' own. Nothing else can tell the two apart.
        if self.hass.state is not CoreState.running:
            self._restarted_at = dt_util.utcnow()

        # Keyed by the room id, which a move leaves alone.
        self.hass.data.setdefault(DOMAIN, {})[self._room_id] = self
        self._place_the_device_in_its_area()

        stored = await self._store.async_load()
        self._thermostat.restore(stored, dt_util.utcnow())

        self._watch_what_the_room_reads()
        self.async_on_remove(
            async_track_time_interval(self.hass, self._on_the_clock, EVALUATION_INTERVAL)
        )
        self.async_on_remove(self._stop_evaluating)
        await self._one_at_a_time.after_a_change()

    async def async_will_remove_from_hass(self) -> None:
        if self.hass.data.get(DOMAIN, {}).get(self._room_id) is self:
            self.hass.data[DOMAIN].pop(self._room_id)

    @callback
    def _place_the_device_in_its_area(self) -> None:
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={self._identity.device_identifier})
        if device is not None and device.area_id != self._area_id:
            registry.async_update_device(device.id, area_id=self._area_id)

    @callback
    def follow_the_area(self, room: Room) -> None:
        """The room is in another area now: its card says so and it drives what that area holds."""
        self._area_id = room.area_id
        self._discovered_heaters = list(room.heaters)
        self._discovered_sensors = list(room.temperature_sensors)
        self._follow_the_named_slots()
        # The issue named the old area; the next pass raises it again under the new name.
        if self._fault_raised is not None:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(self._fault_raised))
            self._fault_raised = None
        self.async_write_ha_state()
        self._start_a_pass()

    @callback
    def _watch_what_the_room_reads(self) -> None:
        """Every entity this room reads, re-subscribed whenever the add-on names a slot."""
        if self._watching_states is not None:
            self._watching_states()
            self._watching_states = None
        watched = [*self._sensors, *self._heaters]
        for optional in (self._window_sensor, self._outdoor_sensor, self._power_sensor):
            if optional:
                watched.append(optional)
        if watched:
            self._watching_states = async_track_state_change_event(
                self.hass, watched, self._state_changed
            )

    @callback
    def _stop_evaluating(self) -> None:
        """A room going away takes its passes with it.

        An abandoned pass writes the state of an entity that has gone and saves to a store entry
        that has gone with it.
        """
        self._one_at_a_time.close()
        # A room that has gone leaves no issue behind for a fault nothing is watching any more.
        if self._fault_raised is not None:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(self._fault_raised))
            self._fault_raised = None
        if self._watching_states is not None:
            self._watching_states()
            self._watching_states = None
        for pass_in_flight in list(self._passes):
            pass_in_flight.cancel()

    @callback
    def _state_changed(self, event: Event) -> None:
        self._start_a_pass()

    @callback
    def _on_the_clock(self, now: datetime) -> None:
        self._start_a_pass()

    def _start_a_pass(self) -> None:
        # The handle is kept so removal can cancel it; nothing else owns an evaluation's lifetime.
        task = self.hass.async_create_task(self._one_at_a_time.after_a_change())
        self._passes.add(task)
        task.add_done_callback(self._passes.discard)

    # ----- the standard climate actions ---------------------------------------------------------

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        # Nothing clamps this. The away mode's temperature is frost protection, not a floor.
        await self._act(lambda now: self._thermostat.set_target(float(temperature), now))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode is HVACMode.OFF:
            await self._act(self._thermostat.switch_off)
        else:
            await self._act(self._thermostat.switch_on)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        # Stored and reported as given. The house's status selector is never written from here.
        await self._act(lambda now: self._thermostat.set_preset(preset_mode, now))

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    # ----- the six actions ------------------------------------------------------------------------

    # A refusal leaves `_act` as the platform's own `ServiceValidationError`, so the websocket
    # answers `service_validation_error` and the add-on reads it as the room's answer. A field out
    # of bounds never reaches here: the schema raises a `vol.Invalid` and that answers
    # `invalid_format`.
    async def async_warm_room_by(self, temperature: float, by_time: datetime | time) -> None:
        # The core helper, not an hour written onto today's date: on the two nights the clock moves
        # the arithmetic lands an hour out.
        wanted = (
            by_time
            if isinstance(by_time, datetime)
            else dt_util.find_next_time_expression_time(
                dt_util.now(), [by_time.second], [by_time.minute], [by_time.hour]
            )
        )

        await self._act(
            lambda now: self._thermostat.warm_room_by(temperature, dt_util.as_utc(wanted), now)
        )

    async def async_hold_temperature(self, temperature: float, duration: timedelta) -> None:
        await self._act(
            lambda now: self._thermostat.hold_temperature(temperature, duration, now)
        )

    async def async_set_warming_rate(
        self, degrees_per_hour: float, measured_at_outdoor: float | None = None
    ) -> None:
        await self._act(
            lambda _now: self._thermostat.set_warming_rate(degrees_per_hour, measured_at_outdoor)
        )

    async def async_set_regulation(self, **fields: Any) -> None:
        await self._act(lambda _now: self._set_regulation(**fields))

    def _set_regulation(self, **fields: Any) -> None:
        named = fields.get("heaters")
        if named and heater_already_claimed(named, self._what_the_other_rooms_drive()) is not None:
            # Two loops over one relay each count only their own changes, so the shortest time
            # between relay changes stops protecting anything.
            raise Refused(NotHeating.THE_HEATER_BELONGS_TO_ANOTHER_ROOM)
        self._thermostat.set_regulation(**fields)
        self._follow_the_named_slots()

    def _what_the_other_rooms_drive(self) -> dict[str, list[str]]:
        """Every other room's heaters, keyed by room id."""
        return {
            room_id: list(other._heaters)
            for room_id, other in self.hass.data.get(DOMAIN, {}).items()
            if isinstance(other, AdaptiveHeatingThermostat) and other is not self
        }

    @callback
    def _follow_the_named_slots(self) -> None:
        """A slot the add-on named is that slot's whole set; the registry read stands elsewhere."""
        regulation = self._thermostat.regulation
        self._heaters = named_or_discovered(regulation.heaters, self._discovered_heaters)
        self._sensors = named_or_discovered(
            regulation.temperature_sensors, self._discovered_sensors
        )
        self._window_sensor = regulation.window_sensor
        self._power_sensor = regulation.power_sensor
        self._outdoor_sensor = regulation.outdoor_sensor
        self._neighbour = regulation.neighbour
        self._thermostat.drive(self._heaters)
        # Follows from what the room reads and never from a sensor going quiet.
        self._thermostat.no_reading_at_all = not self._sensors and not self._neighbour
        self._take_the_offer()
        self._watch_what_the_room_reads()

    async def async_return_to_target(self) -> None:
        await self._act(self._thermostat.return_to_target)

    async def async_move_to_area(self, area: str) -> None:
        # Imported here: the package imports this platform, not the other way round.
        from . import move_room

        await move_room(self.hass, self._entry, self._room_id, area)

    # ----- the evaluation -------------------------------------------------------------------------

    async def _act(self, change: Callable[[datetime], object]) -> None:
        """A person's change and the evaluation it causes, as one turn nothing interleaves with.

        The change writes the same fields an evaluation writes, so it belongs inside the same gate
        rather than in front of it.

        A refusal is turned into `ServiceValidationError` here and nowhere else. A second catch
        elsewhere would let one route answer under a different code than the rest.
        """

        async def change_it_and_evaluate() -> None:
            now = dt_util.utcnow()
            change(now)
            await self._evaluate(now, write_it_down_now=True)

        try:
            await self._one_at_a_time.at_once(change_it_and_evaluate)
        except Refused as refusal:
            raise ServiceValidationError(str(refusal)) from refusal

    async def _evaluate(self, now: datetime, write_it_down_now: bool = False) -> None:
        self._note_what_the_sensors_say(now)
        self._reading = self._room_reading(now)
        outdoor = self._outdoor(now)
        self._outdoor_now = outdoor
        decision = self._thermostat.evaluate(
            now, self._reading, outdoor, self._window(now), self._power(now), self._relays()
        )
        self._decision = decision

        for command in decision.commands:
            await self._command(command)

        # A coalesced write beats the platform's own fifteen minutes, but a value whose loss
        # matters goes down before the call returns.
        if write_it_down_now:
            await self._store.async_save(self._thermostat.as_dict())
        else:
            self._store.async_delay_save(self._thermostat.as_dict, STORAGE_WRITE_DELAY)
        self.async_write_ha_state()
        self._tell_about_the_fault()
        reason = self._entry.runtime_data.reason_sensors.get(self._room_id)
        if reason is not None:
            reason.async_write_ha_state()

    @callback
    def _tell_about_the_fault(self) -> None:
        """One repairs issue per fault, keyed on the fault and the room id, deleted when it clears."""
        fault = self._thermostat.power.fault
        if fault is self._fault_raised:
            return
        if self._fault_raised is not None:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(self._fault_raised))
        self._fault_raised = fault
        if fault is None:
            return
        area = ar.async_get(self.hass).async_get_area(self._area_id)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._issue_id(fault),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            # A room over a thermostat has no relay, so the words differ by what heats the room.
            translation_key=issue_key(fault, self._over_a_thermostat()),
            translation_placeholders={"room": self._area_id if area is None else area.name},
        )

    def _issue_id(self, fault: Fault) -> str:
        return self._identity.issue_id(str(fault))

    def _over_a_thermostat(self) -> bool:
        return bool(self._heaters) and all(is_a_thermostat(one) for one in self._heaters)

    def _note_what_the_sensors_say(self, now: datetime) -> None:
        for sensor_id in self._sensors:
            state = self.hass.states.get(sensor_id)
            if state is None or state.state in UNUSABLE:
                continue
            reported_at = when_it_reported(
                # `last_reported` is carried since 2024.4. An older core has no such field, and
                # the updated time stands in there.
                getattr(state, "last_reported", None),
                state.last_updated,
                self._restarted_at,
            )
            if reported_at is None:
                continue
            try:
                self._thermostat.freshness.note(
                    sensor_id, float(state.state), reported_at, state.last_changed
                )
            except ValueError:
                continue
        self._thermostat.freshness.prune(
            now, self._thermostat.regulation.freshness_record_retention
        )

    def _room_reading(self, now: datetime) -> RoomReading:
        regulation = self._thermostat.regulation
        if self._sensors:
            return read(
                self._thermostat.freshness.readings(
                    self._sensors, now, regulation.sensor_freshness
                ),
                now,
                regulation,
            )
        lender = self._lender()
        if lender is None:
            return NO_READING
        return borrow(lender._reading, lender.entity_id or lender._area_id)

    def _lender(self) -> AdaptiveHeatingThermostat | None:
        if not self._neighbour:
            return None
        for other in self.hass.data.get(DOMAIN, {}).values():
            if not isinstance(other, AdaptiveHeatingThermostat) or other is self:
                continue
            if other.entity_id != self._neighbour and other._area_id != self._neighbour:
                continue
            return other
        return None

    def _outdoor(self, now: datetime) -> float | None:
        if not self._outdoor_sensor:
            return None
        state = self.hass.states.get(self._outdoor_sensor)
        if state is None or state.state in UNUSABLE:
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        self._thermostat.note_outdoor(value, now)
        return value

    def _power(self, now: datetime) -> float | None:
        """What the heater is drawing, or nothing where no meter is named or the meter has gone quiet."""
        if not self._power_sensor:
            return None
        state = self.hass.states.get(self._power_sensor)
        if state is None or state.state in UNUSABLE:
            return None
        reported_at = when_it_reported(
            getattr(state, "last_reported", None), state.last_updated, self._restarted_at
        )
        # A meter that has not reported inside its window is out, exactly as any other sensor is. An
        # unreadable meter is never evidence that a heater is off.
        if reported_at is None or now - reported_at > STANDARD.sensor_freshness:
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def _relays(self) -> dict[str, RelayObservation | ThermostatObservation]:
        """What each switch says about itself, and when it last moved.

        A switch that is unknown or unavailable reports nothing rather than reporting open, so a
        relay
        off the mesh is left alone. The stamp is Home Assistant's own, so a wall switch a person
        flipped holds the guard and nothing has to be stored to survive a restart.
        """
        seen: dict[str, RelayObservation | ThermostatObservation] = {}
        for heater_id in self._heaters:
            state = self.hass.states.get(heater_id)
            if is_a_thermostat(heater_id):
                seen[heater_id] = observe(
                    None if state is None else state.state,
                    None if state is None else state.attributes,
                )
                continue
            if state is None or state.state in UNUSABLE:
                seen[heater_id] = RelayObservation(None, None)
                continue
            seen[heater_id] = RelayObservation(state.state == STATE_ON, state.last_changed)
        return seen

    def _window(self, now: datetime) -> WindowState:
        if not self._window_sensor:
            return WindowState.CLOSED
        state = self.hass.states.get(self._window_sensor)
        if state is None or state.state in UNUSABLE:
            return WindowState.QUIET
        if state.state == STATE_ON:
            return WindowState.OPEN
        if state.state == STATE_OFF:
            return WindowState.CLOSED
        return WindowState.QUIET

    async def _command(self, command: Command) -> None:
        heater_id = command.heater_id
        domain = heater_id.split(".")[0]
        calls: list[tuple[str, dict[str, Any]]]
        if is_a_thermostat(heater_id):
            calls = [("set_hvac_mode", {"hvac_mode": HEAT if command.closed else OFF})]
            if command.closed and command.setpoint is not None:
                calls.append(("set_temperature", {ATTR_TEMPERATURE: command.setpoint}))
        else:
            calls = [("turn_on" if command.closed else "turn_off", {})]
        for service, data in calls:
            try:
                await self.hass.services.async_call(
                    domain, service, {"entity_id": heater_id, **data}, blocking=True
                )
            except Exception:  # noqa: BLE001 - a command that does not land is reported, not fatal
                _LOGGER.warning("%s: the command to %s was refused", self._area_id, heater_id)
