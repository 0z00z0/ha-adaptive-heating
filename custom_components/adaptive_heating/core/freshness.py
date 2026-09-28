"""When each sensor last reported, and when its reading last moved.

Home Assistant records when a value last arrived and when it last moved, and re-stamps every
sensor in the house as it comes up. So its times are read where they can be believed, the record
kept here is what survives a restart, and the record outranks a stamp that jumped forward without
the value moving.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .defaults import STANDARD, Defaults
from .sensors import SensorReading


def when_it_reported(
    last_reported: datetime | None,
    last_updated: datetime | None,
    restarted_at: datetime | None,
) -> datetime | None:
    """When a sensor last actually reported, or nothing where the platform cannot say.

    The report time is the one that moves on every report, including one repeating the value
    already held; the updated time is the fallback where a platform does not carry it. A restart
    stamps every sensor in the house at once, so a stamp at or before the restart is no evidence
    that the sensor behind it is alive: a value dead for a year comes back carrying it too.
    """
    reported = last_reported if last_reported is not None else last_updated
    if reported is None:
        return None
    if restarted_at is not None and reported <= restarted_at:
        return None
    return reported


@dataclass(slots=True)
class SensorMemory:
    temperature: float
    reported_at: datetime
    last_moved_at: datetime


class FreshnessRecord:
    """What is known about each sensor, kept across a restart."""

    def __init__(self, defaults: Defaults = STANDARD) -> None:
        self._defaults = defaults
        self._sensors: dict[str, SensorMemory] = {}

    def note(
        self,
        sensor_id: str,
        temperature: float,
        reported_at: datetime,
        moved_at: datetime | None = None,
    ) -> None:
        """One genuine report, timed by the platform rather than by whenever it was noticed."""
        moved = moved_at if moved_at is not None else reported_at
        known = self._sensors.get(sensor_id)
        if known is None or known.temperature != temperature:
            self._sensors[sensor_id] = SensorMemory(temperature, reported_at, moved)
            return
        # The value has not moved, so what is written down wins wherever it is the older evidence.
        # A restart hands every sensor a fresh changed-at, and the stuck rule must survive that.
        known.reported_at = max(known.reported_at, reported_at)
        known.last_moved_at = min(known.last_moved_at, moved)

    def forget(self, sensor_id: str) -> None:
        self._sensors.pop(sensor_id, None)

    def readings(self, sensor_ids: list[str], as_at: datetime) -> list[SensorReading]:
        """One reading per sensor the room names. A sensor with no record counts as stale."""
        stale = as_at - self._defaults.sensor_freshness - timedelta(seconds=1)
        out: list[SensorReading] = []
        for sensor_id in sensor_ids:
            known = self._sensors.get(sensor_id)
            if known is None:
                out.append(SensorReading(sensor_id, None, stale, stale))
            else:
                out.append(
                    SensorReading(
                        sensor_id, known.temperature, known.reported_at, known.last_moved_at
                    )
                )
        return out

    def prune(self, as_at: datetime) -> None:
        cutoff = as_at - self._defaults.freshness_record_retention
        for sensor_id in [k for k, v in self._sensors.items() if v.reported_at < cutoff]:
            del self._sensors[sensor_id]

    def as_dict(self) -> dict[str, dict[str, object]]:
        return {
            sensor_id: {
                "temperature": memory.temperature,
                "reported_at": memory.reported_at.isoformat(),
                "last_moved_at": memory.last_moved_at.isoformat(),
            }
            for sensor_id, memory in self._sensors.items()
        }

    @classmethod
    def from_dict(
        cls, stored: dict[str, dict[str, object]] | None, defaults: Defaults = STANDARD
    ) -> FreshnessRecord:
        record = cls(defaults)
        for sensor_id, memory in (stored or {}).items():
            try:
                record._sensors[sensor_id] = SensorMemory(
                    float(memory["temperature"]),  # type: ignore[arg-type]
                    datetime.fromisoformat(str(memory["reported_at"])),
                    datetime.fromisoformat(str(memory["last_moved_at"])),
                )
            except (KeyError, TypeError, ValueError):
                continue
        return record
