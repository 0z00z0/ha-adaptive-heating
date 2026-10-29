"""A room's temperature from its own sensors, with a verdict on every one of them.

The same rules run in the planner, over the outdoor sensors it owns. The two copies are deliberate:
a room keeps its reading while the add-on is away, so the check that produces it cannot live there.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from statistics import median

from .defaults import STANDARD, Defaults
from .regulation import Regulation


class SensorExclusion(StrEnum):
    NONE = "none"
    QUIET = "quiet"
    STUCK = "stuck"
    FAR_FROM_THE_OTHERS = "far_from_the_others"
    BOTH_OF_A_DISAGREEING_PAIR = "both_of_a_disagreeing_pair"


@dataclass(frozen=True, slots=True)
class SensorReading:
    sensor_id: str
    temperature: float | None
    reported_at: datetime
    last_moved_at: datetime


@dataclass(frozen=True, slots=True)
class SensorVerdict:
    sensor_id: str
    temperature: float | None
    excluded: SensorExclusion


@dataclass(frozen=True, slots=True)
class RoomReading:
    temperature: float | None
    resting_on: int
    sensors_in_the_room: int
    verdicts: tuple[SensorVerdict, ...]
    borrowed_from: str | None = None

    @property
    def has_a_temperature(self) -> bool:
        return self.temperature is not None

    @property
    def left_out(self) -> tuple[SensorVerdict, ...]:
        return tuple(v for v in self.verdicts if v.excluded is not SensorExclusion.NONE)

    @property
    def disagreeing_pair(self) -> tuple[SensorVerdict, ...]:
        return tuple(
            v for v in self.verdicts if v.excluded is SensorExclusion.BOTH_OF_A_DISAGREEING_PAIR
        )

    def borrowed(self, lending_room: str) -> RoomReading:
        return RoomReading(
            self.temperature, self.resting_on, self.sensors_in_the_room, self.verdicts, lending_room
        )


NO_READING = RoomReading(None, 0, 0, ())


def borrow(lender: RoomReading | None, lending_room: str) -> RoomReading:
    """A neighbour's reading for a room with no sensor of its own, or no reading at all.

    The safe state: a neighbour with no temperature lends nothing, and a borrowed reading is never
    lent onward, so the room stops rather than heating on a figure nobody measured.
    """
    if lender is None or lender.borrowed_from is not None or not lender.has_a_temperature:
        return NO_READING
    return lender.borrowed(lending_room)


def read(
    sensors: list[SensorReading],
    as_at: datetime,
    settings: Defaults | Regulation = STANDARD,
) -> RoomReading:
    """The room's temperature from the sensors that have reported recently.

    The three figures are read off whatever is passed: the standing defaults, or the room's own
    regulation once the add-on has sent them.
    """
    excluded: dict[str, SensorExclusion] = {}
    live: list[SensorReading] = []

    for sensor in sensors:
        if sensor.temperature is None or as_at - sensor.reported_at > settings.sensor_freshness:
            excluded[sensor.sensor_id] = SensorExclusion.QUIET
        elif as_at - sensor.last_moved_at >= settings.stuck_reading:
            # A live sensor in a real room always wanders. A flat reading is a dying battery.
            excluded[sensor.sensor_id] = SensorExclusion.STUCK
        else:
            live.append(sensor)

    if len(live) == 2 and abs(live[0].temperature - live[1].temperature) > settings.sensor_spread:
        # Two sensors cannot say which of them is lying, so the room loses its temperature with
        # both of them still reporting.
        for sensor in live:
            excluded[sensor.sensor_id] = SensorExclusion.BOTH_OF_A_DISAGREEING_PAIR
        live = []
    elif len(live) >= 3:
        middle = median(sensor.temperature for sensor in live)
        for sensor in list(live):
            if abs(sensor.temperature - middle) > settings.sensor_spread:
                excluded[sensor.sensor_id] = SensorExclusion.FAR_FROM_THE_OTHERS
                live.remove(sensor)

    verdicts = tuple(
        SensorVerdict(
            sensor.sensor_id,
            sensor.temperature,
            excluded.get(sensor.sensor_id, SensorExclusion.NONE),
        )
        for sensor in sensors
    )

    temperature = (
        None if not live else sum(sensor.temperature for sensor in live) / len(live)
    )
    return RoomReading(temperature, len(live), len(sensors), verdicts)
