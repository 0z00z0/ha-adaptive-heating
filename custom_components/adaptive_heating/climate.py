"""The thermostat a room appears as, and the five actions that drive it."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF, STATE_ON, UnitOfTemperature
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_BAND,
    ATTR_BORROWED_FROM,
    ATTR_DUTY,
    ATTR_DUTY_ASKED_FOR,
    ATTR_FAULT,
    ATTR_HAS_A_POWER_METER,
    ATTR_HOLD_ENDS_AT,
    ATTR_INTEGRATION_VERSION,
    ATTR_NO_READING_AT_ALL,
    ATTR_OUTDOOR,
    ATTR_POWER,
    ATTR_REASON,
    ATTR_RELAY_GUARD_IS_HOLDING,
    ATTR_REPORTS_A_PROBLEM,
    ATTR_RESTING_ON,
    ATTR_ROOM,
    ATTR_SENSORS_IN_THE_ROOM,
    ATTR_SENSORS_LEFT_OUT,
    ATTR_STAGE,
    ATTR_SWITCHED,
    ATTR_TARGET_SET_AT,
    ATTR_VOCABULARY_VERSION,
    ATTR_WARM_UP,
    ATTR_WARMING_RATE,
    ATTR_WARMING_RATE_MEASURED,
    CONF_HEATERS,
    CONF_NEIGHBOUR,
    CONF_OUTDOOR_SENSOR,
    CONF_POWER_SENSOR,
    CONF_ROOM,
    CONF_TEMPERATURE_SENSORS,
    CONF_WINDOW_SENSOR,
    DOMAIN,
    EVALUATION_INTERVAL,
    INTEGRATION_VERSION,
    STORAGE_VERSION,
    STORAGE_WRITE_DELAY,
    VOCABULARY_VERSION,
)
from .core.defaults import STANDARD
from .core.freshness import when_it_reported
from .core.loop import RelayObservation
from .core.reasons import FAULT_WORDS, WORDS, Refused
from .core.sensors import NO_READING, RoomReading, read
from .core.serialisation import OneAtATime
from .core.thermostat import RoomThermostat, WindowState
from .core.warmup import next_occurrence

_LOGGER = logging.getLogger(__name__)

UNUSABLE = ("unknown", "unavailable", "", None)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    thermostat = AdaptiveHeatingThermostat(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = thermostat
    async_add_entities([thermostat])


class AdaptiveHeatingThermostat(ClimateEntity):
    """An ordinary climate entity, so every standard control works without this project."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = STANDARD.minimum_temperature
    _attr_max_temp = STANDARD.maximum_temperature
    _attr_target_temperature_step = STANDARD.temperature_step
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        options: dict[str, Any] = {**entry.data, **entry.options}
        self._room: str = options.get(CONF_ROOM, entry.title)
        self._heaters: list[str] = list(options.get(CONF_HEATERS, []))
        self._sensors: list[str] = list(options.get(CONF_TEMPERATURE_SENSORS, []))
        self._window_sensor: str | None = options.get(CONF_WINDOW_SENSOR)
        self._outdoor_sensor: str | None = options.get(CONF_OUTDOOR_SENSOR)
        self._neighbour: str | None = options.get(CONF_NEIGHBOUR)
        self._power_sensor: str | None = options.get(CONF_POWER_SENSOR)
        no_reading_at_all = not self._sensors and not self._neighbour

        # A room with no reading has no temperature to set, so the card offers none. Home Assistant
        # itself then refuses the standard action that would set one.
        if no_reading_at_all:
            self._attr_supported_features = (
                ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
            )

        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=self._room,
            manufacturer="Adaptive Heating",
        )
        self._thermostat = RoomThermostat(
            self._room, self._heaters, no_reading_at_all=no_reading_at_all
        )
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._decision = None
        self._reading: RoomReading = NO_READING
        self._restarted_at: datetime | None = None
        self._outdoor_now: float | None = None
        self._one_at_a_time = OneAtATime(lambda: self._evaluate(dt_util.utcnow()))
        self._passes: set[asyncio.Task[None]] = set()

    # ----- the platform's own surface -----------------------------------------------------------

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if self._thermostat.switched_on else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        if not self._thermostat.switched_on:
            return HVACAction.OFF
        if self._decision is not None and self._decision.heating:
            return HVACAction.HEATING
        return HVACAction.IDLE

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
        thermostat = self._thermostat
        decision = self._decision
        warm_up = thermostat.warm_up
        return {
            # The add-on finds its rooms by these three. Nothing else in a house publishes them, so a
            # thermostat carrying them is one of this integration's and one carrying none is not.
            ATTR_ROOM: self._room,
            ATTR_INTEGRATION_VERSION: INTEGRATION_VERSION,
            ATTR_VOCABULARY_VERSION: VOCABULARY_VERSION,
            ATTR_REASON: None if decision is None or decision.reason is None
            else WORDS[decision.reason],
            ATTR_STAGE: None if decision is None else str(decision.stage),
            # What the relay was held for, which is the figure anything learning from a cycle reads.
            # The request stands beside it so the law can still be followed.
            ATTR_DUTY: None if decision is None else round(decision.delivered, 3),
            ATTR_DUTY_ASKED_FOR: None if decision is None else round(decision.duty, 3),
            ATTR_RESTING_ON: self._reading.resting_on,
            ATTR_SENSORS_IN_THE_ROOM: self._reading.sensors_in_the_room,
            ATTR_SENSORS_LEFT_OUT: {
                verdict.sensor_id: str(verdict.excluded) for verdict in self._reading.left_out
            },
            ATTR_BORROWED_FROM: self._reading.borrowed_from,
            ATTR_WARM_UP: None if warm_up is None else warm_up.as_dict(),
            ATTR_HOLD_ENDS_AT: None if thermostat.hold is None
            else thermostat.hold.ends_at.isoformat(),
            ATTR_BAND: thermostat.band_learning.in_force,
            ATTR_WARMING_RATE: thermostat.warming_rate.degrees_per_hour,
            ATTR_WARMING_RATE_MEASURED: thermostat.warming_rate.measured,
            ATTR_REPORTS_A_PROBLEM: False if decision is None else decision.reports_a_problem,
            # Follows from how the room was set up, never from a sensor that has gone quiet: a room with
            # no sensor of its own and no neighbour to borrow from can only be switched on and off.
            ATTR_NO_READING_AT_ALL: thermostat.no_reading_at_all,
            ATTR_SWITCHED: None if thermostat.regulation.switched is None
            else str(thermostat.regulation.switched),
            ATTR_OUTDOOR: self._outdoor_now,
            ATTR_TARGET_SET_AT: None if thermostat.target_set_at is None
            else thermostat.target_set_at.isoformat(),
            # The duty above is what the loop asked for. Where the guard overrides it, this is what
            # the relay is actually doing.
            ATTR_RELAY_GUARD_IS_HOLDING: False if decision is None
            else decision.held_by_the_relay_guard,
            ATTR_HAS_A_POWER_METER: self._power_sensor is not None,
            ATTR_POWER: thermostat.power.watts,
            ATTR_FAULT: None if thermostat.power.fault is None
            else FAULT_WORDS[thermostat.power.fault],
        }

    async def async_added_to_hass(self) -> None:
        # Set up while the core is still coming up means every state in the machine carries the
        # restart moment, whatever the sensor behind it is doing. Set up on a core already running
        # means the times are the sensors' own. Nothing else can tell the two apart.
        if self.hass.state is not CoreState.running:
            self._restarted_at = dt_util.utcnow()

        stored = await self._store.async_load()
        self._thermostat.restore(stored, dt_util.utcnow())

        watched = [*self._sensors, *self._heaters]
        for optional in (self._window_sensor, self._outdoor_sensor, self._power_sensor):
            if optional:
                watched.append(optional)
        if watched:
            self.async_on_remove(
                async_track_state_change_event(self.hass, watched, self._state_changed)
            )
        self.async_on_remove(
            async_track_time_interval(self.hass, self._on_the_clock, EVALUATION_INTERVAL)
        )
        self.async_on_remove(self._stop_evaluating)
        await self._one_at_a_time.after_a_change()

    @callback
    def _stop_evaluating(self) -> None:
        """A room going away takes its passes with it.

        An abandoned pass writes the state of an entity that has gone and saves to a store entry
        that has gone with it.
        """
        self._one_at_a_time.close()
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

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    # ----- the five actions -----------------------------------------------------------------------

    # A refusal leaves `_act` as the platform's own `ServiceValidationError`, so the websocket
    # answers `service_validation_error` and the add-on reads it as the room's answer. A field out
    # of bounds never reaches here: the schema raises a `vol.Invalid` and that answers
    # `invalid_format`.
    async def async_warm_room_by(self, temperature: float, by_time: datetime | time) -> None:
        wanted = by_time if isinstance(by_time, datetime) else next_occurrence(by_time, dt_util.now())

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
        await self._act(lambda _now: self._thermostat.set_regulation(**fields))

    async def async_return_to_target(self) -> None:
        await self._act(self._thermostat.return_to_target)

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
            await self._command(command.heater_id, command.closed)

        # A coalesced write beats the platform's own fifteen minutes, but a value whose loss
        # matters goes down before the call returns.
        if write_it_down_now:
            await self._store.async_save(self._thermostat.as_dict())
        else:
            self._store.async_delay_save(self._thermostat.as_dict, STORAGE_WRITE_DELAY)
        self.async_write_ha_state()

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
        self._thermostat.freshness.prune(now)

    def _room_reading(self, now: datetime) -> RoomReading:
        if self._sensors:
            return read(self._thermostat.freshness.readings(self._sensors, now), now)
        lender = self._lender()
        if lender is None:
            return NO_READING
        return lender._reading.borrowed(lender.entity_id or lender._room)

    def _lender(self) -> AdaptiveHeatingThermostat | None:
        if not self._neighbour:
            return None
        for other in self.hass.data.get(DOMAIN, {}).values():
            if not isinstance(other, AdaptiveHeatingThermostat) or other is self:
                continue
            if other.entity_id != self._neighbour and other._room != self._neighbour:
                continue
            # A borrowed reading is never borrowed onward, so a borrowing room cannot lend.
            if other._reading.borrowed_from is not None or not other._reading.has_a_temperature:
                return None
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

    def _relays(self) -> dict[str, RelayObservation]:
        """What each switch says about itself, and when it last moved.

        A switch that is unknown or unavailable reports nothing rather than reporting open, so a
        relay
        off the mesh is left alone. The stamp is Home Assistant's own, so a wall switch a person
        flipped holds the guard and nothing has to be stored to survive a restart.
        """
        seen: dict[str, RelayObservation] = {}
        for heater_id in self._heaters:
            state = self.hass.states.get(heater_id)
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

    async def _command(self, heater_id: str, closed: bool) -> None:
        domain = heater_id.split(".")[0]
        service = "turn_on" if closed else "turn_off"
        try:
            await self.hass.services.async_call(
                domain, service, {"entity_id": heater_id}, blocking=True
            )
        except Exception:  # noqa: BLE001 - a command that does not land is reported, never fatal
            _LOGGER.warning("%s: the command to %s was refused", self._room, heater_id)
