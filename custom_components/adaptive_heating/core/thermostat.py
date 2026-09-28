"""One room's thermostat: what it holds, what it commands, and what it stops commanding."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from .defaults import STANDARD, Defaults
from .freshness import FreshnessRecord
from .loop import HeaterLoop, LoopDecision, RelayObservation, Stage
from .power import PowerWatch
from .reasons import Fault, NotHeating, Refused
from .regulation import BandLearning, HoldingBehaviour, Regulation, Switched
from .sensors import NO_READING, RoomReading
from .warmup import TimedHold, WarmingRate, WarmUp, WarmUpOutcome, plan


class WindowState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    QUIET = "quiet"


@dataclass(frozen=True, slots=True)
class Command:
    heater_id: str
    closed: bool


@dataclass(frozen=True, slots=True)
class Decision:
    """What the room is holding, what it is doing about it, and what has to be sent."""

    target: float
    heating: bool
    duty: float
    # What the relay was actually held for, against the duty the law asked for.
    delivered: float
    stage: Stage
    reason: NotHeating | None
    commands: tuple[Command, ...]
    resting_on: int
    sensors_in_the_room: int
    reports_a_problem: bool

    # What the relay is actually doing where the guard and the duty disagree, and what the meter says.
    held_by_the_relay_guard: bool = False
    fault: Fault | None = None


class RoomThermostat:
    def __init__(
        self,
        room_id: str,
        heater_ids: list[str],
        frost_temperature: float | None = None,
        defaults: Defaults = STANDARD,
        no_reading_at_all: bool = False,
    ) -> None:
        self.room_id = room_id
        self._defaults = defaults
        # A room set up with no sensor of its own and no neighbour to borrow from. It follows from the
        # setup and never from a sensor going quiet, which is a fault and this is not.
        self.no_reading_at_all = no_reading_at_all
        self.switched_on = True
        # Every starting value is the cold one, and no restart lands on a warmer setting.
        self.target = frost_temperature if frost_temperature is not None else (
            defaults.minimum_temperature
        )
        self.target_set_at: datetime | None = None
        self.regulation = Regulation()
        self.band_learning = BandLearning(defaults)
        self.warming_rate = WarmingRate(defaults.warming_rate_by_hand, None, False)
        self.warm_up: WarmUp | None = None
        self.hold: TimedHold | None = None
        self.freshness = FreshnessRecord(defaults)
        self.power = PowerWatch(defaults)
        self.reading: RoomReading = NO_READING
        self.window = WindowState.CLOSED
        cycle = defaults.cycle_length.total_seconds()
        self.loops = [
            HeaterLoop(
                heater_id,
                timedelta(seconds=(cycle * index) / max(1, len(heater_ids))),
                defaults,
            )
            for index, heater_id in enumerate(heater_ids)
        ]
        self._window_changed_at: datetime | None = None
        self._window_stops_heating = False
        self._outdoor_seen: list[tuple[datetime, float]] = []
        self._watching: float | None = None
        self._watching_closed = False
        self.last_warm_up: WarmUp | None = None

    # ----- what a person or the planner does to it -------------------------------------------

    def switch_off(self, now: datetime) -> None:
        """Nothing is queued while a thermostat is off, so anything with a time in it ends here."""
        self.switched_on = False
        self.warm_up = None
        self.hold = None

    def switch_on(self, now: datetime) -> None:
        self.switched_on = True

    def set_target(self, temperature: float, at: datetime) -> None:
        self.target = temperature
        self.target_set_at = at

    def warm_room_by(
        self, temperature: float, deadline: datetime, now: datetime
    ) -> WarmUp:
        self._refuse_while_off()
        self._refuse_without_a_reading()
        self.warm_up = plan(
            temperature, deadline, now, self.reading.temperature, self.warming_rate, self._defaults
        )
        return self.warm_up

    def hold_temperature(self, temperature: float, duration: timedelta, now: datetime) -> TimedHold:
        self._refuse_while_off()
        self._refuse_without_a_reading()
        self.hold = TimedHold(temperature, now + duration)
        return self.hold

    def set_warming_rate(self, degrees_per_hour: float, measured_at_outdoor: float | None) -> None:
        self._refuse_without_a_reading()
        self.warming_rate = WarmingRate(degrees_per_hour, measured_at_outdoor, True)

    def set_regulation(self, **fields: object) -> Regulation:
        # A field this half does not know is ignored rather than refused.
        known = {
            name: value
            for name, value in fields.items()
            if name in Regulation.__dataclass_fields__ and value is not None
        }
        if "behaviour" in known:
            known["behaviour"] = HoldingBehaviour(str(known["behaviour"]))
        if "switched" in known:
            known["switched"] = Switched(str(known["switched"]))
        if "band" in known:
            self.band_learning.set(float(known["band"]))  # type: ignore[arg-type]
            known["band"] = self.band_learning.in_force
        self.regulation = replace(self.regulation, **known)  # type: ignore[arg-type]
        return self.regulation

    def return_to_target(self, now: datetime) -> None:
        self.warm_up = None
        self.hold = None

    def _refuse_while_off(self) -> None:
        if not self.switched_on:
            raise Refused(NotHeating.ROOM_IS_SWITCHED_OFF)

    def _refuse_without_a_reading(self) -> None:
        # Solving backwards from a deadline, holding a temperature and measuring a rise all need a
        # number this room can never produce. Accepting one promises what nothing behind it can keep.
        if self.no_reading_at_all:
            raise Refused(NotHeating.THE_ROOM_HAS_NO_READING)

    # ----- what it holds ----------------------------------------------------------------------

    def temperature_it_would_hold(self, now: datetime) -> float:
        """A running warm-up wins outright, an unexpired hold comes next, then the target."""
        if self.warm_up is not None and self.warm_up.running(now):
            return self.warm_up.temperature
        if self.hold is not None and self.hold.unexpired(now):
            return self.hold.temperature
        return self.target

    def note_outdoor(self, temperature: float, at: datetime) -> None:
        self._outdoor_seen.append((at, temperature))
        cutoff = at - self._defaults.coldest_outdoor_window
        self._outdoor_seen = [seen for seen in self._outdoor_seen if seen[0] >= cutoff]

    @property
    def coldest_outdoor_recently(self) -> float | None:
        return min((t for _, t in self._outdoor_seen), default=None)

    # ----- the evaluation ----------------------------------------------------------------------

    def evaluate(
        self,
        now: datetime,
        reading: RoomReading,
        outdoor: float | None = None,
        window: WindowState = WindowState.CLOSED,
        power: float | None = None,
        relays: dict[str, RelayObservation] | None = None,
    ) -> Decision:
        self.reading = reading
        # What each switch says about itself, before anything is decided from it. A room that heats
        # nothing this pass still has to reconcile, or a heater found on stays on.
        for loop in self.loops:
            loop.see((relays or {}).get(loop.heater_id))
        self._forget_a_rate_this_room_cannot_have()
        self._settle_window(now, window)
        self._retire_finished_work(now)

        target = self.temperature_it_would_hold(now)
        self._note_power(now, target, power)
        # Dropping the outdoor term leaves the room below its target, so the coldest figure the
        # room knows stands in for a reading it has not got.
        effective_outdoor = outdoor if outdoor is not None else self.coldest_outdoor_recently

        if not self.switched_on:
            return self._stop(now, target, NotHeating.ROOM_IS_SWITCHED_OFF)
        if self._window_stops_heating:
            return self._stop(now, target, NotHeating.WINDOW_IS_OPEN)

        at_full_output = (
            self.warm_up is not None
            and self.warm_up.running(now)
            and (reading.temperature is None or reading.temperature < self.warm_up.temperature)
        )
        regulation = replace(self.regulation, band=self.band_learning.in_force)

        decisions: list[LoopDecision] = []
        commands: list[Command] = []
        for loop in self.loops:
            decision = loop.evaluate(
                now,
                reading.temperature,
                target,
                effective_outdoor,
                regulation,
                at_full_output,
                self.no_reading_at_all,
            )
            decisions.append(decision)
            if decision.changed:
                commands.append(Command(loop.heater_id, decision.relay_closed))

        self._watch_the_drift(reading.temperature, target, decisions)

        heating = any(decision.relay_closed for decision in decisions)
        duty = max((decision.duty for decision in decisions), default=0.0)
        delivered = max((decision.delivered for decision in decisions), default=0.0)
        stage = decisions[0].stage if decisions else Stage.NOT_HEATING
        reason = None if heating else self._why_not(reading, decisions)
        return Decision(
            target,
            heating,
            duty,
            delivered,
            stage,
            reason,
            tuple(commands),
            reading.resting_on,
            reading.sensors_in_the_room,
            self._reports_a_problem(reading),
            any(decision.held_by_the_relay_guard for decision in decisions),
            self.power.fault,
        )

    def _forget_a_rate_this_room_cannot_have(self) -> None:
        """A room that can never measure a rise must not report one.

        The refusal stops a new one arriving, and a room told a rate before that refusal existed
        cannot be corrected by the same action. This clears it on the next ordinary evaluation, so a
        room already in that state is reached without waiting for anything.
        """
        if self.no_reading_at_all and self.warming_rate.measured:
            self.warming_rate = WarmingRate(self._defaults.warming_rate_by_hand, None, False)

    def _note_power(self, now: datetime, target: float, power: float | None) -> None:
        """The meter is read against what the relay has been doing since the last evaluation."""
        room = self.reading.temperature
        below = None if self.no_reading_at_all or room is None else room < target

        self.power.observe(now, any(loop.relay_closed for loop in self.loops), below, power)

    def _stop(self, now: datetime, target: float, reason: NotHeating) -> Decision:
        commands = [
            Command(loop.heater_id, False)
            for loop in self.loops
            if loop.open_once(now).changed
        ]
        return Decision(
            target,
            False,
            0.0,
            0.0,
            Stage.NOT_HEATING,
            reason,
            tuple(commands),
            self.reading.resting_on,
            self.reading.sensors_in_the_room,
            self._reports_a_problem(self.reading),
            False,
            self.power.fault,
        )

    def _why_not(self, reading: RoomReading, decisions: list[LoopDecision]) -> NotHeating:
        if any(decision.held_by_the_relay_guard for decision in decisions):
            return NotHeating.RELAY_GUARD_IS_HOLDING
        # A room with no reading at all is not missing one: the mode simply says off.
        if self.no_reading_at_all:
            return NotHeating.THE_MODE_SAYS_OFF
        if not reading.has_a_temperature:
            return NotHeating.NO_TEMPERATURE_READING
        # A room waiting out the off-phase of its cycle is normal, and the loop is the only thing
        # that knows it. Re-deriving the word here is what published "At temperature" at the cabin.
        if any(decision.reason is NotHeating.PACING_THE_CYCLE for decision in decisions):
            return NotHeating.PACING_THE_CYCLE
        return NotHeating.AT_TEMPERATURE

    def _reports_a_problem(self, reading: RoomReading) -> bool:
        # A switched-off room is the owner's act, so it is left out of every report that names a
        # room as having a problem. This is the only place that decides it.
        if not self.switched_on:
            return False
        # A room that never had a reading is not a room that lost one. Reporting the absence would
        # name that room for ever, and there is nothing to go and look at.
        if self.no_reading_at_all:
            return self.power.fault is not None
        return bool(reading.left_out) or not reading.has_a_temperature or self.power.fault is not None

    def _settle_window(self, now: datetime, window: WindowState) -> None:
        # A sensor that went quiet while it last said open would otherwise hold the room cold for
        # as long as it stayed silent.
        if window is WindowState.QUIET:
            self.window = window
            self._window_stops_heating = False
            self._window_changed_at = None
            return
        if window is not self.window:
            self.window = window
            self._window_changed_at = now
        if self._window_changed_at is None:
            return
        since = now - self._window_changed_at
        if window is WindowState.OPEN and since >= self._defaults.window_delay_to_stop:
            self._window_stops_heating = True
        elif window is WindowState.CLOSED and since >= self._defaults.window_delay_to_resume:
            self._window_stops_heating = False

    def _retire_finished_work(self, now: datetime) -> None:
        if self.hold is not None and not self.hold.unexpired(now):
            self.hold = None
        warm_up = self.warm_up
        if warm_up is not None and warm_up.finished(now):
            room = self.reading.temperature
            if room is not None and room + 1e-9 >= warm_up.temperature:
                warm_up.outcome = WarmUpOutcome.MET
                warm_up.missed_by = 0.0
            else:
                warm_up.outcome = WarmUpOutcome.MISSED
                warm_up.missed_by = (
                    None if room is None else round(warm_up.temperature - room, 3)
                )
            self.warm_up = None
            self.last_warm_up = warm_up

    def _watch_the_drift(
        self, room: float | None, target: float, decisions: list[LoopDecision]
    ) -> None:
        if room is None or not decisions or self.band_learning.locked:
            return
        changed = decisions[0].changed
        if not changed:
            if self._watching is not None:
                self._watching = (
                    min(self._watching, room) if self._watching_closed
                    else max(self._watching, room)
                )
            return
        if self._watching is not None:
            self.band_learning.observe(self._watching - target)
        self._watching = room
        self._watching_closed = decisions[0].relay_closed

    # ----- what survives a restart ---------------------------------------------------------------

    def as_dict(self) -> dict[str, object]:
        return {
            "switched_on": self.switched_on,
            "target": self.target,
            "target_set_at": None if self.target_set_at is None else self.target_set_at.isoformat(),
            "regulation": self.regulation.as_dict(),
            "band_learning": self.band_learning.as_dict(),
            "warming_rate": {
                "degrees_per_hour": self.warming_rate.degrees_per_hour,
                "measured_at_outdoor": self.warming_rate.measured_at_outdoor,
                "measured": self.warming_rate.measured,
            },
            "warm_up": None if self.warm_up is None else self.warm_up.as_dict(),
            "hold": None if self.hold is None else self.hold.as_dict(),
            "freshness": self.freshness.as_dict(),
            "loops": {loop.heater_id: loop.as_dict() for loop in self.loops},
            "outdoor_seen": [[at.isoformat(), value] for at, value in self._outdoor_seen],
        }

    def restore(self, stored: dict[str, object] | None, now: datetime) -> None:
        """Come back on what was written down, and never on something warmer."""
        if not stored:
            return
        self.switched_on = bool(stored.get("switched_on", True))
        written = stored.get("target")
        if written is not None:
            with suppress(TypeError, ValueError):
                self.target = float(written)  # type: ignore[arg-type]
        set_at = stored.get("target_set_at")
        if set_at is not None:
            try:
                self.target_set_at = datetime.fromisoformat(str(set_at))
            except ValueError:
                self.target_set_at = None
        self.regulation = Regulation.from_dict(stored.get("regulation"))  # type: ignore[arg-type]
        self.band_learning = BandLearning.from_dict(
            stored.get("band_learning"), self._defaults  # type: ignore[arg-type]
        )
        rate = stored.get("warming_rate")
        if isinstance(rate, dict):
            with suppress(KeyError, TypeError, ValueError):
                self.warming_rate = WarmingRate(
                    float(rate["degrees_per_hour"]),
                    None if rate.get("measured_at_outdoor") is None
                    else float(rate["measured_at_outdoor"]),
                    bool(rate.get("measured", False)),
                )
        self.freshness = FreshnessRecord.from_dict(
            stored.get("freshness"), self._defaults  # type: ignore[arg-type]
        )
        self.freshness.prune(now)
        loops = stored.get("loops")
        if isinstance(loops, dict):
            for loop in self.loops:
                loop.restore(loops.get(loop.heater_id))
        seen = stored.get("outdoor_seen")
        if isinstance(seen, list):
            for entry in seen:
                try:
                    self.note_outdoor(float(entry[1]), datetime.fromisoformat(str(entry[0])))
                except (IndexError, TypeError, ValueError):
                    continue

        # A hold that ran out while the system was down reads as expired, and a warm-up whose
        # deadline passed while it was down is over rather than resumed late.
        hold = TimedHold.from_dict(stored.get("hold"))  # type: ignore[arg-type]
        self.hold = hold if hold is not None and hold.unexpired(now) else None
        warm_up = WarmUp.from_dict(stored.get("warm_up"))  # type: ignore[arg-type]
        self.warm_up = warm_up if warm_up is not None and not warm_up.finished(now) else None
