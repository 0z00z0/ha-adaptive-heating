"""Warming a room to a temperature by a time, and holding one until it expires."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum

from .defaults import STANDARD, Defaults


def next_occurrence(wanted: time, now: datetime) -> datetime:
    """The next moment the clock reads `wanted`: today where it is still ahead, tomorrow otherwise.

    A deadline written as a time alone is how a person writes one, and the day it means is the next
    day it comes round on. A profile entry's boundary is resolved the same way on the other side.
    """
    today = now.replace(hour=wanted.hour, minute=wanted.minute, second=wanted.second, microsecond=0)

    return today if today > now else today + timedelta(days=1)


class WarmUpOutcome(StrEnum):
    RUNNING = "running"
    MET = "met"
    MISSED = "missed"


@dataclass(frozen=True, slots=True)
class WarmingRate:
    degrees_per_hour: float
    measured_at_outdoor: float | None = None
    measured: bool = False


@dataclass(slots=True)
class WarmUp:
    temperature: float
    deadline: datetime
    starts_at: datetime
    reaches: float | None = None
    short_by: float | None = None
    outcome: WarmUpOutcome = WarmUpOutcome.RUNNING
    missed_by: float | None = None

    def running(self, now: datetime) -> bool:
        return self.starts_at <= now < self.deadline

    def finished(self, now: datetime) -> bool:
        return now >= self.deadline

    def as_dict(self) -> dict[str, object]:
        return {
            "temperature": self.temperature,
            "deadline": self.deadline.isoformat(),
            "starts_at": self.starts_at.isoformat(),
            "reaches": self.reaches,
            "short_by": self.short_by,
        }

    @classmethod
    def from_dict(cls, stored: dict[str, object] | None) -> WarmUp | None:
        if not stored:
            return None
        try:
            return cls(
                temperature=float(stored["temperature"]),  # type: ignore[arg-type]
                deadline=datetime.fromisoformat(str(stored["deadline"])),
                starts_at=datetime.fromisoformat(str(stored["starts_at"])),
                reaches=None if stored.get("reaches") is None else float(stored["reaches"]),  # type: ignore[arg-type]
                short_by=None if stored.get("short_by") is None else float(stored["short_by"]),  # type: ignore[arg-type]
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(slots=True)
class TimedHold:
    temperature: float
    ends_at: datetime

    def unexpired(self, now: datetime) -> bool:
        return now < self.ends_at

    def as_dict(self) -> dict[str, object]:
        return {"temperature": self.temperature, "ends_at": self.ends_at.isoformat()}

    @classmethod
    def from_dict(cls, stored: dict[str, object] | None) -> TimedHold | None:
        if not stored:
            return None
        try:
            return cls(
                temperature=float(stored["temperature"]),  # type: ignore[arg-type]
                ends_at=datetime.fromisoformat(str(stored["ends_at"])),
            )
        except (KeyError, TypeError, ValueError):
            return None


def plan(
    temperature: float,
    deadline: datetime,
    now: datetime,
    room: float | None,
    rate: WarmingRate,
    defaults: Defaults = STANDARD,
) -> WarmUp:
    """Work backwards from the deadline to a start time, on four fifths of the rate measured.

    A room behaving as measured therefore arrives with a fifth of the planned time to spare. A room
    that cannot make it starts at once and heats anyway, and the plan carries what it will reach.
    """
    rise = 0.0 if room is None else max(0.0, temperature - room)
    planned_rate = max(rate.degrees_per_hour * defaults.warm_up_planning_fraction, 1e-6)
    planned = timedelta(hours=rise / planned_rate)
    starts_at = deadline - planned

    if starts_at <= now:
        starts_at = now
        available = (deadline - now).total_seconds() / 3600.0
        reaches = None if room is None else room + max(0.0, available) * planned_rate
        short_by = (
            None if reaches is None or reaches >= temperature else round(temperature - reaches, 3)
        )
        return WarmUp(temperature, deadline, starts_at, reaches, short_by)

    return WarmUp(temperature, deadline, starts_at, temperature, None)
