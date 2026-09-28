"""How a room is regulated: what the regulation action writes, and the band."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum

from .defaults import STANDARD, Defaults


class HoldingBehaviour(StrEnum):
    PACED = "paced"
    BAND = "band"


class Switched(StrEnum):
    ON = "on"
    OFF = "off"


@dataclass(frozen=True, slots=True)
class Regulation:
    behaviour: HoldingBehaviour = HoldingBehaviour.PACED
    band: float = STANDARD.band_starting_value
    outdoor_shift_per_degree: float = STANDARD.outdoor_term_per_degree
    cycle_length: timedelta = STANDARD.cycle_length
    full_output_below: float = STANDARD.full_output_below
    shortest_time_between_relay_changes: timedelta = STANDARD.shortest_time_between_relay_changes

    # What a mode is worth in a room with no reading at all. Only the planner sets it, and only for such
    # a room, so a room whose sensors have merely gone quiet still repeats its holding duty.
    switched: Switched | None = None

    @property
    def deliverable_floor(self) -> float:
        """The shortest on-phase a cycle can hold: the guard as a fraction of the cycle."""
        cycle = self.cycle_length.total_seconds()
        if cycle <= 0.0:
            return 0.0
        return min(1.0, self.shortest_time_between_relay_changes.total_seconds() / cycle)

    @property
    def deliverable_ceiling(self) -> float:
        return 1.0 - self.deliverable_floor

    def deliverable(self, duty: float) -> float:
        """What the relay can actually hold of one cycle.

        A transition the guard would not let finish is skipped rather than stretched, so a duty too
        small to deliver rounds to nothing and one too large rounds to full output. The room reaches
        its target across cycles instead of over-delivering in each one.
        """
        floor = self.deliverable_floor
        if floor <= 0.0:
            return duty
        # The tolerance keeps a duty sitting exactly on an edge, which two thirds of a
        # fifteen-minute
        # cycle does, on the paced side of it.
        if duty < floor - 1e-9:
            return 0.0
        if duty > self.deliverable_ceiling + 1e-9:
            return 1.0
        return duty

    def deliverable_blind(self, duty: float) -> float:
        """The same band, entered from above and from below.

        A missing reading may not switch a heater off, so a fraction too small to deliver rounds up
        to
        the shortest on-phase rather than down to nothing.
        """
        floor = self.deliverable_floor
        if floor <= 0.0:
            return min(max(duty, 0.0), 1.0)
        return min(max(duty, floor), max(floor, self.deliverable_ceiling))

    def as_dict(self) -> dict[str, object]:
        return {
            "switched": None if self.switched is None else str(self.switched),
            "behaviour": str(self.behaviour),
            "band": self.band,
            "outdoor_shift_per_degree": self.outdoor_shift_per_degree,
            "cycle_length": self.cycle_length.total_seconds(),
            "full_output_below": self.full_output_below,
            "shortest_time_between_relay_changes": (
                self.shortest_time_between_relay_changes.total_seconds()
            ),
        }

    @classmethod
    def from_dict(cls, stored: dict[str, object] | None) -> Regulation:
        if not stored:
            return cls()
        standing = cls()
        switched = stored.get("switched")
        try:
            return cls(
                switched=None if switched is None else Switched(str(switched)),
                behaviour=HoldingBehaviour(str(stored.get("behaviour", standing.behaviour))),
                band=float(stored.get("band", standing.band)),  # type: ignore[arg-type]
                outdoor_shift_per_degree=float(
                    stored.get("outdoor_shift_per_degree", standing.outdoor_shift_per_degree)  # type: ignore[arg-type]
                ),
                cycle_length=timedelta(
                    seconds=float(stored.get("cycle_length", standing.cycle_length.total_seconds()))  # type: ignore[arg-type]
                ),
                full_output_below=float(
                    stored.get("full_output_below", standing.full_output_below)  # type: ignore[arg-type]
                ),
                shortest_time_between_relay_changes=timedelta(
                    seconds=float(
                        stored.get(
                            "shortest_time_between_relay_changes",
                            standing.shortest_time_between_relay_changes.total_seconds(),
                        )  # type: ignore[arg-type]
                    )
                ),
            )
        except (TypeError, ValueError):
            return standing


class BandLearning:
    """The band around the target, measured either side of a switch.

    The band decides how far a room may drift before the heat returns, so it errs narrow. A
    measurement narrowing it is taken on the spot; one widening it is taken only after five in a
    row agree, and the band never passes the ceiling.
    """

    def __init__(self, defaults: Defaults = STANDARD) -> None:
        self._defaults = defaults
        self.band = defaults.band_starting_value
        self.measurements = 0
        self.set_by_hand: float | None = None
        self._agreeing_wider = 0

    @property
    def in_force(self) -> float:
        return self.set_by_hand if self.set_by_hand is not None else self.band

    @property
    def locked(self) -> bool:
        return self.set_by_hand is not None

    @property
    def measured(self) -> bool:
        return self.measurements > 0

    def observe(self, drift: float) -> None:
        """One measurement: how far the room ran past the switch, either side."""
        wanted = min(max(abs(drift) * 2.0, 0.1), self._defaults.band_ceiling)
        self.measurements += 1
        if wanted < self.band:
            self.band = wanted
            self._agreeing_wider = 0
            return
        if wanted == self.band:
            self._agreeing_wider = 0
            return
        self._agreeing_wider += 1
        if self._agreeing_wider >= self._defaults.agreements_before_relaxing:
            self.band = wanted
            self._agreeing_wider = 0

    def set(self, band: float) -> None:
        self.set_by_hand = min(band, self._defaults.band_ceiling)

    def clear(self) -> None:
        # The system's own number kept following the measurements underneath, so it comes back
        # informed rather than at its starting value.
        self.set_by_hand = None

    def reset(self) -> None:
        self.band = self._defaults.band_starting_value
        self.measurements = 0
        self._agreeing_wider = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "band": self.band,
            "measurements": self.measurements,
            "set_by_hand": self.set_by_hand,
            "agreeing_wider": self._agreeing_wider,
        }

    @classmethod
    def from_dict(
        cls, stored: dict[str, object] | None, defaults: Defaults = STANDARD
    ) -> BandLearning:
        learning = cls(defaults)
        if not stored:
            return learning
        try:
            learning.band = float(stored.get("band", learning.band))  # type: ignore[arg-type]
            learning.measurements = int(stored.get("measurements", 0))  # type: ignore[arg-type]
            by_hand = stored.get("set_by_hand")
            learning.set_by_hand = None if by_hand is None else float(by_hand)  # type: ignore[arg-type]
            learning._agreeing_wider = int(stored.get("agreeing_wider", 0))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return cls(defaults)
        return learning


def with_band(regulation: Regulation, band: float) -> Regulation:
    return replace(regulation, band=band)
