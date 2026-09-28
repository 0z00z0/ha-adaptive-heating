"""When a sensor last actually reported, which is not the same question as when it was noticed.

A sensor dead for a year still has its last value served by Home Assistant. Counting that value as
having just arrived is what cost the cabin its room temperature on 2026-09-24: the dead sensor and
the healthy one were both believed, they disagreed by 7.9 degrees, and the room dropped both.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime

from _core import at
from core.freshness import FreshnessRecord, when_it_reported
from core.sensors import SensorExclusion, read


@dataclass(frozen=True)
class Served:
    """What Home Assistant hands over for one sensor, with the platform out of the way."""

    sensor_id: str
    temperature: float
    last_reported: datetime
    last_changed: datetime


def note_what_is_served(
    record: FreshnessRecord, served: tuple[Served, ...], restarted_at: datetime | None = None
) -> None:
    for one in served:
        reported_at = when_it_reported(one.last_reported, one.last_changed, restarted_at)
        if reported_at is None:
            continue
        record.note(one.sensor_id, one.temperature, reported_at, one.last_changed)


def excluded_as(reading, sensor_id: str) -> SensorExclusion:
    return next(v.excluded for v in reading.verdicts if v.sensor_id == sensor_id)


DEAD = Served("sensor.oomi", 10.7, at(days=-365), at(days=-365))
LIVE = Served("sensor.shelly", 18.6, at(minutes=-4), at(minutes=-4))
NAMED = [DEAD.sensor_id, LIVE.sensor_id]


class FreshnessComesFromThePlatformTests(unittest.TestCase):
    def test_a_year_old_value_still_being_served_is_not_taken_as_a_fresh_report(self) -> None:
        record = FreshnessRecord()
        note_what_is_served(record, (DEAD, LIVE))

        reading = read(record.readings(NAMED, at()), at())
        self.assertEqual(reading.temperature, 18.6)
        self.assertEqual(reading.resting_on, 1)
        self.assertEqual(excluded_as(reading, DEAD.sensor_id), SensorExclusion.QUIET)

        # The room must not lose its temperature to a disagreement with a corpse.
        self.assertEqual(reading.disagreeing_pair, ())

    def test_a_platform_that_states_no_report_time_falls_back_to_when_it_was_updated(self) -> None:
        self.assertEqual(when_it_reported(None, at(minutes=-5), None), at(minutes=-5))
        self.assertIsNone(when_it_reported(None, None, None))

    def test_two_sensors_that_really_are_both_reporting_still_settle_as_a_disagreeing_pair(
        self,
    ) -> None:
        record = FreshnessRecord()
        note_what_is_served(
            record,
            (Served("sensor.one", 10.7, at(minutes=-4), at(minutes=-4)), LIVE),
        )

        reading = read(record.readings(["sensor.one", LIVE.sensor_id], at()), at())
        self.assertIsNone(reading.temperature)
        self.assertEqual(len(reading.disagreeing_pair), 2)


class ARestartStampsEverySensorAtOnceTests(unittest.TestCase):
    def test_a_stamp_from_the_restart_is_not_evidence_that_a_sensor_is_alive(self) -> None:
        restarted_at = at()
        # Home Assistant re-creates every state as it comes up, so a dead sensor's value carries
        # the restart moment exactly as a healthy one's does.
        self.assertIsNone(when_it_reported(at(seconds=-2), at(seconds=-2), restarted_at))
        self.assertEqual(
            when_it_reported(at(minutes=1), at(minutes=1), restarted_at), at(minutes=1)
        )

    def test_the_record_written_down_before_the_cut_outranks_the_restart_stamp(self) -> None:
        record = FreshnessRecord()
        note_what_is_served(record, (DEAD, LIVE))

        # The restart re-serves both values unchanged. Neither is evidence, so what survived the
        # cut is what the room reads.
        restarted_at = at()
        note_what_is_served(
            record,
            (
                Served(DEAD.sensor_id, 10.7, at(seconds=-1), at(seconds=-1)),
                Served(LIVE.sensor_id, 18.6, at(seconds=-1), at(seconds=-1)),
            ),
            restarted_at,
        )

        reading = read(record.readings(NAMED, at(seconds=30)), at(seconds=30))
        self.assertEqual(reading.temperature, 18.6)
        self.assertEqual(excluded_as(reading, DEAD.sensor_id), SensorExclusion.QUIET)

    def test_a_restart_does_not_hand_a_stuck_reading_a_fresh_start(self) -> None:
        record = FreshnessRecord()
        flat = Served("sensor.flat", 19.0, at(hours=-1), at(hours=-9))
        note_what_is_served(record, (flat,))

        # The value last moved nine hours ago, which is past the stuck window. A restart moving
        # the platform's own changed-at forward must not hide that.
        note_what_is_served(
            record, (Served("sensor.flat", 19.0, at(minutes=1), at(minutes=1)),)
        )

        reading = read(record.readings(["sensor.flat"], at(minutes=2)), at(minutes=2))
        self.assertEqual(excluded_as(reading, "sensor.flat"), SensorExclusion.STUCK)


if __name__ == "__main__":
    unittest.main()
