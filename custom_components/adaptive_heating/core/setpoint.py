"""One loop per thermostat underneath a room: the setpoint and the mode it is given every pass."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import floor

from .defaults import STANDARD, Defaults
from .loop import LoopDecision, RemembersHoldingDuties, Stage
from .reasons import NotHeating
from .regulation import Regulation, Switched

HEAT = "heat"
OFF = "off"

_NOT_ANSWERING = ("unknown", "unavailable", "", None)


def is_a_thermostat(heater_id: str) -> bool:
    return heater_id.startswith("climate.")


@dataclass(frozen=True, slots=True)
class ThermostatObservation:
    """What the thermostat underneath publishes. Nothing else of it is read."""

    answering: bool
    mode: str | None = None
    setpoint: float | None = None
    reading: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    # From the device's `hvac_action`; None where it publishes none.
    heating: bool | None = None


NOT_ANSWERING = ThermostatObservation(False)
_HEATING = ("heating", "preheating")


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def observe(state: str | None, attributes: Mapping[str, object] | None) -> ThermostatObservation:
    """Home Assistant's state and attributes for one climate entity, as the loop reads them."""
    if state in _NOT_ANSWERING:
        return NOT_ANSWERING
    attributes = attributes or {}
    action = attributes.get("hvac_action")
    return ThermostatObservation(
        True,
        state,
        _number(attributes.get("temperature")),
        _number(attributes.get("current_temperature")),
        _number(attributes.get("min_temp")),
        _number(attributes.get("max_temp")),
        _number(attributes.get("target_temp_step")),
        None if action is None else action in _HEATING,
    )


def setpoint_for(
    room: float,
    target: float,
    device_reading: float | None,
    outdoor: float | None,
    regulation: Regulation,
    defaults: Defaults = STANDARD,
) -> float:
    """The room's target, moved by how much warmer the thermostat's own sensor reads than the room.

    A sensor at the heater reading 4 degrees warm holds the room 4 degrees cold, so the number
    written goes up by 4. The outdoor term is the switch loop's own figure taken through the same
    handover distance, so one stored number means the same shortfall in either kind of room.
    """
    shift = 0.0 if device_reading is None else device_reading - room
    outdoor_term = regulation.full_output_below * regulation.outdoor_shift_per_degree * max(
        0.0, target - (outdoor if outdoor is not None else defaults.outdoor_never_seen)
    )
    return target + shift + outdoor_term


def fit(value: float, observed: ThermostatObservation, defaults: Defaults = STANDARD) -> float:
    """Rounded to the device's own step, then held inside its own range."""
    step = observed.step if observed.step is not None and observed.step > 0 else (
        defaults.temperature_step
    )
    rounded = floor(value / step + 0.5) * step
    if observed.maximum is not None:
        rounded = min(rounded, observed.maximum)
    if observed.minimum is not None:
        rounded = max(rounded, observed.minimum)
    return round(rounded, 3)


class SetpointLoop(RemembersHoldingDuties):
    """The loop for one thermostat. Only the blind fallback is shared with the relay loop."""

    def __init__(self, heater_id: str, defaults: Defaults = STANDARD) -> None:
        self.heater_id = heater_id
        self._defaults = defaults
        self.observed: ThermostatObservation = NOT_ANSWERING
        # What the room last asked of the device: heat or off, and the number.
        self.asking_for_heat = False
        self.written: float | None = None
        self.written_for: tuple[float, bool] | None = None
        self.reconsidered_at: datetime | None = None
        self.last_change_at: datetime | None = None
        self.last_write_at: datetime | None = None
        self.blind_since: datetime | None = None
        self.cycle_started_at: datetime | None = None
        self.stagger = timedelta(0)
        self._to_write: tuple[bool, float | None] | None = None
        self._start_remembering()
        # The target, when the stretch began, and the seconds the device said it was heating.
        self._window: tuple[float, datetime, float] | None = None
        self._last_seen: tuple[datetime, bool] | None = None

    @property
    def relay_closed(self) -> bool:
        """What the meter is read against: whether the room asked the device for heat."""
        return self.asking_for_heat

    def see(self, observed: object) -> None:
        self.observed = observed if isinstance(observed, ThermostatObservation) else NOT_ANSWERING

    def command(self) -> tuple[bool, float | None]:
        """Heat or off, and the setpoint to go with heat, from the last evaluation that wrote."""
        return self._to_write or (False, None)

    def open_once(self, now: datetime) -> LoopDecision:
        """Off, written every pass the room heats nothing, so a hand turning it on is undone."""
        self.asking_for_heat = False
        self.blind_since = None
        self.cycle_started_at = None
        self._window = None
        self._last_seen = None
        changed = self._write(now, False, None)
        return LoopDecision(False, 0.0, 0.0, Stage.NOT_HEATING, None, False, changed)

    def evaluate(
        self,
        now: datetime,
        room: float | None,
        target: float,
        outdoor: float | None,
        regulation: Regulation,
        at_full_output: bool = False,
        no_reading_at_all: bool = False,
        observed: object | None = None,
    ) -> LoopDecision:
        if observed is not None:
            self.see(observed)

        if no_reading_at_all:
            return self._switch(now, regulation)

        if room is None:
            self.blind_since = self.blind_since or now
        else:
            self.blind_since = None
            self.cycle_started_at = None
        self._measure(now, room, target, regulation, at_full_output)

        if not self.observed.answering:
            # Nothing is written and nothing is concluded. The next pass that sees it answer writes.
            return LoopDecision(
                False, 0.0, 0.0, Stage.NOT_HEATING, NotHeating.THE_HEATER_IS_NOT_ANSWERING, False,
                False,
            )

        if room is None and not at_full_output:
            return self._blind(now, target, regulation)

        wanted, stage = self._setpoint(now, room, target, outdoor, regulation, at_full_output)
        self.asking_for_heat = True
        changed = self._write(now, True, wanted)

        heating = at_full_output or (room is not None and room < target)
        reason = None if heating or room is None else NotHeating.AT_TEMPERATURE
        return LoopDecision(heating, 0.0, 0.0, stage, reason, False, changed)

    def _measure(
        self,
        now: datetime,
        room: float | None,
        target: float,
        regulation: Regulation,
        at_full_output: bool,
    ) -> None:
        """The share of the stretch the device said it was heating, entered as a relay's paced duty is.

        Only a pass inside the handover distance and short of full output counts, as for a relay;
        anything else, or a gap longer than a cycle, starts the stretch again.
        """
        heating = self.observed.heating
        if (
            room is None
            or at_full_output
            or heating is None
            or target - room >= regulation.full_output_below
        ):
            self._window = None
            self._last_seen = None
            return
        key = round(target, 1)
        last, self._last_seen = self._last_seen, (now, heating)
        window = self._window
        if (
            window is None
            or window[0] != key
            or last is None
            or now - last[0] > regulation.cycle_length
        ):
            self._window = (key, now, 0.0)
            return
        _, started, heated = window
        if last[1]:
            heated += (now - last[0]).total_seconds()
        span = (now - started).total_seconds()
        if span < self._defaults.thermostat_holding_window.total_seconds():
            self._window = (key, started, heated)
            return
        share = heated / span
        if share < 1.0:
            self.remember(target, share)
        self._window = (key, now, 0.0)

    def _blind(self, now: datetime, target: float, regulation: Regulation) -> LoopDecision:
        """The relay's own fallback, with the device's top and the room's frost temperature as closed and open."""
        duty = self._blind_duty(now, target, regulation)
        delivered = regulation.deliverable_blind(duty)
        on = self._cycle_wants(now, delivered, regulation)
        top = self.observed.maximum
        wanted = (top if top is not None else self._defaults.maximum_temperature) if on else (
            self._off_phase(regulation)
        )
        written = self._adopt(now, fit(wanted, self.observed, self._defaults), None)
        self.asking_for_heat = True
        changed = self._write(now, True, written)
        return LoopDecision(
            on, duty, delivered, Stage.REPEATING_THE_HOLDING_DUTY, None, False, changed
        )

    def _off_phase(self, regulation: Regulation) -> float:
        # `fit` raises a frost temperature below the device's minimum to that minimum.
        if regulation.frost_limit:
            return regulation.frost_temperature
        bottom = self.observed.minimum
        return bottom if bottom is not None else self._defaults.minimum_temperature

    def _setpoint(
        self,
        now: datetime,
        room: float | None,
        target: float,
        outdoor: float | None,
        regulation: Regulation,
        at_full_output: bool,
    ) -> tuple[float, Stage]:
        held = (round(target, 3), at_full_output)
        if at_full_output:
            maximum = self.observed.maximum
            wanted = maximum if maximum is not None else self._defaults.maximum_temperature
            return self._adopt(now, fit(wanted, self.observed, self._defaults), held), (
                Stage.FULL_OUTPUT
            )

        changed_instruction = self.written is None or self.written_for != held
        due = self.reconsidered_at is None or now - self.reconsidered_at >= regulation.cycle_length
        guarded = (
            self.last_change_at is not None
            and now - self.last_change_at < regulation.shortest_time_between_relay_changes
        )
        if room is not None and (changed_instruction or (due and not guarded)):
            computed = setpoint_for(
                room, target, self.observed.reading, outdoor, regulation, self._defaults
            )
            self._adopt(now, fit(computed, self.observed, self._defaults), held)
        return self.written, Stage.HOLDING_A_SETPOINT  # type: ignore[return-value]

    def _adopt(self, now: datetime, wanted: float, held: tuple[float, bool] | None) -> float:
        # Held for nothing while blind, so the first pass with a reading again works the number out.
        if self.written is None or abs(wanted - self.written) > 1e-9:
            self.last_change_at = now
        self.written = wanted
        self.written_for = held
        self.reconsidered_at = now
        return wanted

    def _switch(self, now: datetime, regulation: Regulation) -> LoopDecision:
        """A room with no reading at all: the mode alone. The device's own setpoint is its dial."""
        if not self.observed.answering:
            return LoopDecision(
                False, 0.0, 0.0, Stage.SWITCHED_OFF, NotHeating.THE_HEATER_IS_NOT_ANSWERING, False,
                False,
            )
        if regulation.switched is None:
            on = self.observed.mode == HEAT
            self.asking_for_heat = on
            changed = False
        else:
            on = regulation.switched is Switched.ON
            self.asking_for_heat = on
            changed = self._write(now, on, None)
        stage = Stage.SWITCHED_ON if on else Stage.SWITCHED_OFF
        reason = None if on else NotHeating.THE_MODE_SAYS_OFF
        return LoopDecision(on, 0.0, 0.0, stage, reason, False, changed)

    def _write(self, now: datetime, heat: bool, setpoint: float | None) -> bool:
        """Whether this pass sends anything: all do, bar a repeat of one that just landed."""
        if not self.observed.answering:
            self._to_write = None
            return False
        shown = self.observed.setpoint
        agrees = self.observed.mode == (HEAT if heat else OFF) and (
            setpoint is None or (shown is not None and abs(shown - setpoint) < 1e-9)
        )
        recently = (
            self.last_write_at is not None
            and now - self.last_write_at < self._defaults.setpoint_rewrite_interval
        )
        if agrees and recently and self._to_write == (heat, setpoint):
            return False
        self._to_write = (heat, setpoint)
        self.last_write_at = now
        return True

    def as_dict(self) -> dict[str, object]:
        def moment(value: datetime | None) -> str | None:
            return None if value is None else value.isoformat()

        return {
            "written": self.written,
            "written_for": None if self.written_for is None else list(self.written_for),
            "reconsidered_at": moment(self.reconsidered_at),
            "last_change_at": moment(self.last_change_at),
            "blind_since": moment(self.blind_since),
            "cycle_started_at": moment(self.cycle_started_at),
            "remembered": self._remembered_as_dict(),
        }

    def restore(self, stored: dict[str, object] | None) -> None:
        if not stored:
            return

        def moment(name: str) -> datetime | None:
            value = stored.get(name)
            return None if value is None else datetime.fromisoformat(str(value))

        try:
            written = stored.get("written")
            self.written = None if written is None else float(written)  # type: ignore[arg-type]
            held = stored.get("written_for")
            self.written_for = (
                None if not isinstance(held, list) else (float(held[0]), bool(held[1]))
            )
            self.reconsidered_at = moment("reconsidered_at")
            self.last_change_at = moment("last_change_at")
            # A spell that began before a restart is still that spell.
            self.blind_since = moment("blind_since")
            self.cycle_started_at = moment("cycle_started_at")
            self._restore_remembered(stored.get("remembered"))
        except (IndexError, TypeError, ValueError):
            return
