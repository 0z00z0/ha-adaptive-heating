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


def read(
    sensors: list[SensorReading], as_at: datetime, defaults: Defaults = STANDARD
) -> RoomReading:
    """The room's temperature from the sensors that have reported recently."""
    excluded: dict[str, SensorExclusion] = {}
    live: list[SensorReading] = []

    for sensor in sensors:
        if sensor.temperature is None or as_at - sensor.reported_at > defaults.sensor_freshness:
            excluded[sensor.sensor_id] = SensorExclusion.QUIET
        elif as_at - sensor.last_moved_at >= defaults.stuck_reading:
            # A live sensor in a real room always wanders. A flat reading is a dying battery.
            excluded[sensor.sensor_id] = SensorExclusion.STUCK
        else:
            live.append(sensor)

    if len(live) == 2 and abs(live[0].temperature - live[1].temperature) > defaults.sensor_spread:
        # Two sensors cannot say which of them is lying, so the room loses its temperature with
        # both of them still reporting.
        for sensor in live:
            excluded[sensor.sensor_id] = SensorExclusion.BOTH_OF_A_DISAGREEING_PAIR
        live = []
    elif len(live) >= 3:
        middle = median(sensor.temperature for sensor in live)
        for sensor in list(live):
            if abs(sensor.temperature - middle) > defaults.sensor_spread:
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
