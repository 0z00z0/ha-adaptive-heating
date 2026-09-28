"""One loop per heater: the two-stage law, the relay guard and the duty fallback."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from .defaults import STANDARD, Defaults
from .reasons import NotHeating
from .regulation import HoldingBehaviour, Regulation, Switched


class Stage(StrEnum):
    FULL_OUTPUT = "full_output"
    PACING = "pacing"
    BAND = "band"
    REPEATING_THE_HOLDING_DUTY = "repeating_the_holding_duty"
    NOT_HEATING = "not_heating"

    # A room with no reading at all is switched on and off and nothing more.
    SWITCHED_ON = "switched_on"
    SWITCHED_OFF = "switched_off"


@dataclass(frozen=True, slots=True)
class RelayObservation:
    """What the switch says about itself. `closed` is None where it is unknown or unavailable."""

    closed: bool | None
    since: datetime | None


@dataclass(frozen=True, slots=True)
class LoopDecision:
    relay_closed: bool
    duty: float
    # What the relay is held for, after the rounding and the guard. Anything learning from a cycle
    # reads this and never `duty`, which is the request.
    delivered: float
    stage: Stage
    reason: NotHeating | None
    held_by_the_relay_guard: bool
    changed: bool


def duty_for(
    room: float,
    target: float,
    outdoor: float | None,
    regulation: Regulation,
    defaults: Defaults = STANDARD,
) -> tuple[float, Stage]:
    """How much of a cycle the heater runs for, and which stage of the law that is."""
    error = target - room
    if error >= regulation.full_output_below:
        return 1.0, Stage.FULL_OUTPUT

    # The outdoor term is what stops a room settling below its target in a cold snap. It is never
    # dropped for want of a reading; the caller supplies the coldest figure it knows instead.
    outdoor_term = regulation.outdoor_shift_per_degree * max(
        0.0, target - (outdoor if outdoor is not None else defaults.outdoor_never_seen)
    )
    proportional = error / regulation.full_output_below if regulation.full_output_below > 0 else 0.0
    return min(max(outdoor_term + proportional, 0.0), 1.0), Stage.PACING


class HeaterLoop:
    """The loop for one heater. Heaters in the same room are staggered by their offset."""

    def __init__(
        self,
        heater_id: str,
        stagger: timedelta = timedelta(0),
        defaults: Defaults = STANDARD,
    ) -> None:
        self.heater_id = heater_id
        self.stagger = stagger
        self._defaults = defaults
        self.relay_closed = False
        self.last_change_at: datetime | None = None
        self.cycle_started_at: datetime | None = None
        self.blind_since: datetime | None = None
        self._remembered: OrderedDict[float, float] = OrderedDict()

    def remember(self, target: float, duty: float) -> None:
        key = round(target, 1)
        self._remembered[key] = duty
        self._remembered.move_to_end(key)
        while len(self._remembered) > self._defaults.remembered_holding_duties:
            self._remembered.popitem(last=False)

    def remembered_for(self, target: float) -> float | None:
        return self._remembered.get(round(target, 1))

    def see(self, observed: RelayObservation | None) -> None:
        """Take the relay's own state, and the relay's own clock, where the switch has both.

        A state that is unknown or unavailable is never acted on, so a switch off the mesh is left
        alone rather than fought. The switch's last-changed stamp is what the guard is read against,
        so the guard is right when a person flips a wall switch and needs nothing stored.
        """
        if observed is None or observed.closed is None:
            return
        self.relay_closed = observed.closed
        if observed.since is not None:
            self.last_change_at = observed.since

    def open_once(self, now: datetime) -> LoopDecision:
        """The single command on the way into a state that heats nothing."""
        changed = self.relay_closed
        self.relay_closed = False
        self.cycle_started_at = None
        self.blind_since = None
        if changed:
            self.last_change_at = now
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
        observed: RelayObservation | None = None,
    ) -> LoopDecision:
        self.see(observed)

        if no_reading_at_all:
            return self._switch(now, regulation)

        self._note_the_blind_spell(now, room)
        duty, stage = self._duty(now, room, target, outdoor, regulation, at_full_output)

        on_the_band = regulation.behaviour is HoldingBehaviour.BAND
        if on_the_band and room is not None and not at_full_output:
            wanted = self._band_wants(room, target, regulation)
            stage = Stage.BAND if stage is not Stage.FULL_OUTPUT else stage
            paced = False
            delivered: float | None = None
        else:
            delivered = (
                regulation.deliverable_blind(duty)
                if stage is Stage.REPEATING_THE_HOLDING_DUTY
                else regulation.deliverable(duty)
            )
            wanted = self._cycle_wants(now, delivered, regulation)
            paced = True

        # A paced room below its target and waiting its turn is the one state with no word of its
        # own. Below the target is the test, not the duty: an outdoor term keeps the duty above
        # nothing in a settled room, and that room really is at its temperature.
        resting = paced and room is not None and room < target
        decision = self._apply(now, wanted, duty, delivered, stage, regulation, resting)
        self._remember_what_was_held(room, target, regulation, decision)
        return decision

    def _switch(self, now: datetime, regulation: Regulation) -> LoopDecision:
        """A room with no reading at all: no band, no duty and no cycle, because each needs a reading.

        The relay is closed or open, the dial on the heater holds whatever the room is worth, and until
        the planner has said which, the relay is left exactly as it was. That is the fallback such a room
        has: there is no duty to repeat.
        """
        if regulation.switched is None:
            wanted = self.relay_closed
        else:
            wanted = regulation.switched is Switched.ON

        stage = Stage.SWITCHED_ON if wanted else Stage.SWITCHED_OFF
        decision = self._apply(
            now, wanted, 1.0 if wanted else 0.0, None, stage, regulation, resting=False
        )

        return decision if decision.relay_closed or decision.held_by_the_relay_guard else replace(
            decision, reason=NotHeating.THE_MODE_SAYS_OFF
        )

    def _note_the_blind_spell(self, now: datetime, room: float | None) -> None:
        if room is not None:
            self.blind_since = None
        elif self.blind_since is None:
            self.blind_since = now

    def _blind_too_long(self, now: datetime) -> bool:
        return (
            self.blind_since is not None
            and now - self.blind_since >= self._defaults.longest_blind_spell
        )

    def _duty(
        self,
        now: datetime,
        room: float | None,
        target: float,
        outdoor: float | None,
        regulation: Regulation,
        at_full_output: bool,
    ) -> tuple[float, Stage]:
        if at_full_output:
            return 1.0, Stage.FULL_OUTPUT
        if room is None:
            # The fallback never stops heating: it repeats the fraction this room was holding at
            # this
            # temperature, capped below full output, and falls to the fixed fraction once that
            # figure
            # has been repeated for longer than the stretch it was measured over.
            remembered = None if self._blind_too_long(now) else self.remembered_for(target)
            if remembered is None:
                remembered = self._defaults.blind_last_resort_fraction
            capped = min(max(remembered, 0.0), regulation.deliverable_ceiling)
            return capped, Stage.REPEATING_THE_HOLDING_DUTY
        return duty_for(room, target, outdoor, regulation, self._defaults)

    def _remember_what_was_held(
        self,
        room: float | None,
        target: float,
        regulation: Regulation,
        decision: LoopDecision,
    ) -> None:
        """Only a paced cycle enters the memory, and only what it delivered.

        Full output is not holding time. A room 1.5 degrees or more below target, and a paced
        cycle rounded up to the whole of it, both heat flat out, and repeating either blind leaves
        the relay closed for as long as the room stays quiet. A band room keeps no fraction.
        """
        if room is None or decision.stage is not Stage.PACING:
            return
        if regulation.behaviour is not HoldingBehaviour.PACED or decision.delivered >= 1.0:
            return
        self.remember(target, decision.delivered)

    def _band_wants(self, room: float, target: float, regulation: Regulation) -> bool:
        half = regulation.band / 2.0
        if room <= target - half:
            return True
        if room >= target + half:
            return False
        return self.relay_closed

    def _cycle_wants(self, now: datetime, duty: float, regulation: Regulation) -> bool:
        """The cycle is the rhythm. The duty it is read against is the one computed just now.

        Latching the duty at the start of a cycle delays a temperature a person has just set by
        the remainder of that cycle, in both directions. The relay is protected by the shortest
        time between changes, never by the duty standing still.
        """
        started = self.cycle_started_at
        # Only the clock rolls a cycle over. A fraction that came out at nothing is a cycle running
        # at
        # nothing, and reading that as no cycle at all is what opened a relay mid-cycle upstream.
        if started is None or now - started >= regulation.cycle_length:
            self.cycle_started_at = now - (self.stagger % regulation.cycle_length)
            started = self.cycle_started_at
        elapsed = now - started
        return elapsed < regulation.cycle_length * duty

    def _apply(
        self,
        now: datetime,
        wanted: bool,
        duty: float,
        delivered: float | None,
        stage: Stage,
        regulation: Regulation,
        resting: bool,
    ) -> LoopDecision:
        open_because = NotHeating.PACING_THE_CYCLE if resting else NotHeating.AT_TEMPERATURE
        held = 1.0 if self.relay_closed else 0.0
        if wanted == self.relay_closed:
            reason = None if self.relay_closed else open_because
            return LoopDecision(
                self.relay_closed,
                duty,
                held if delivered is None else delivered,
                stage,
                reason,
                False,
                False,
            )

        # The shortest time between changes protects the relay's contacts and overrides the band.
        if (
            self.last_change_at is not None
            and now - self.last_change_at < regulation.shortest_time_between_relay_changes
        ):
            # The guard decides what the room delivers here, so the relay's own state is the figure.
            return LoopDecision(
                self.relay_closed,
                duty,
                held,
                stage,
                NotHeating.RELAY_GUARD_IS_HOLDING if not self.relay_closed else None,
                True,
                False,
            )

        self.relay_closed = wanted
        self.last_change_at = now
        return LoopDecision(
            wanted,
            duty,
            (1.0 if wanted else 0.0) if delivered is None else delivered,
            stage,
            None if wanted else open_because,
            False,
            True,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "relay_closed": self.relay_closed,
            "last_change_at": None if self.last_change_at is None
            else self.last_change_at.isoformat(),
            "cycle_started_at": None if self.cycle_started_at is None
            else self.cycle_started_at.isoformat(),
            "blind_since": None if self.blind_since is None else self.blind_since.isoformat(),
            "remembered": {str(k): v for k, v in self._remembered.items()},
        }

    def restore(self, stored: dict[str, object] | None) -> None:
        if not stored:
            return
        try:
            # The relay guard's own state has to come back too, or the first change after a
            # restart is blocked for the whole minimum.
            self.relay_closed = bool(stored.get("relay_closed", False))
            last = stored.get("last_change_at")
            self.last_change_at = None if last is None else datetime.fromisoformat(str(last))
            started = stored.get("cycle_started_at")
            self.cycle_started_at = (
                None if started is None else datetime.fromisoformat(str(started))
            )
            # A spell that began before a restart is still that spell, so a box restarting every
            # hour
            # cannot repeat one fraction for a week.
            blind = stored.get("blind_since")
            self.blind_since = None if blind is None else datetime.fromisoformat(str(blind))
            remembered = stored.get("remembered") or {}
            if isinstance(remembered, dict):
                for key, value in remembered.items():
                    self.remember(float(key), float(value))
        except (TypeError, ValueError):
            return
