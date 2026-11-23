"""A room's reading carries everything below it, so each way it can go wrong is proved."""

from __future__ import annotations

import unittest

from _core import at
from core.freshness import FreshnessRecord
from core.sensors import SensorExclusion, SensorReading, read


def sensor(name: str, temperature: float, reported: float = 0.0, moved: float = 0.0):
    return SensorReading(name, temperature, at(minutes=reported), at(minutes=moved))


def excluded_as(reading, sensor_id: str) -> SensorExclusion:
    return next(v.excluded for v in reading.verdicts if v.sensor_id == sensor_id)


class RoomSensorTests(unittest.TestCase):
    def test_a_quiet_sensor_leaves_the_average_and_the_other_carries_the_room(self) -> None:
        reading = read(
            [sensor("a", 20.0, reported=-90), sensor("b", 21.0, reported=-5, moved=-5)],
            at(),
        )
        self.assertEqual(reading.temperature, 21.0)
        self.assertEqual(reading.resting_on, 1)
        self.assertEqual(reading.sensors_in_the_room, 2)
        self.assertEqual(excluded_as(reading, "a"), SensorExclusion.QUIET)

    def test_a_reading_held_at_one_value_for_six_hours_leaves_the_average(self) -> None:
        reading = read(
            [
                sensor("stuck", 19.0, reported=-1, moved=-6 * 60),
                sensor("live", 20.0, reported=-1, moved=-30),
            ],
            at(),
        )
        self.assertEqual(reading.temperature, 20.0)
        self.assertEqual(excluded_as(reading, "stuck"), SensorExclusion.STUCK)

    def test_two_live_sensors_that_disagree_give_their_average_and_are_named_apart(self) -> None:
        reading = read(
            [sensor("a", 18.0, moved=-10), sensor("b", 22.5, moved=-10)],
            at(),
        )
        self.assertEqual(reading.temperature, 20.25)
        self.assertEqual(reading.resting_on, 2)
        self.assertEqual(reading.left_out, ())
        self.assertEqual({v.temperature for v in reading.apart}, {18.0, 22.5})

    def test_a_sensor_going_quiet_drops_out_and_returns_when_it_reports_again(self) -> None:
        record = FreshnessRecord()
        record.note("dying", 23.0, at(minutes=0))
        record.note("healthy", 20.0, at(minutes=0))
        ids = ["dying", "healthy"]
        self.assertEqual(read(record.readings(ids, at(minutes=30)), at(minutes=30)).temperature, 21.5)

        record.note("healthy", 20.2, at(minutes=61))
        quiet = read(record.readings(ids, at(minutes=61)), at(minutes=61))
        self.assertEqual(quiet.temperature, 20.2)
        self.assertEqual(excluded_as(quiet, "dying"), SensorExclusion.QUIET)

        record.note("dying", 22.8, at(minutes=70))
        back = read(record.readings(ids, at(minutes=70)), at(minutes=70))
        self.assertEqual(back.temperature, 21.5)
        self.assertEqual(back.left_out, ())

    def test_a_sensor_home_assistant_calls_unavailable_is_quiet_at_once(self) -> None:
        record = FreshnessRecord()
        record.note("gone", 30.0, at(minutes=0))
        record.note("live", 20.0, at(minutes=0))
        readings = record.readings(["gone", "live"], at(minutes=5), unavailable=frozenset({"gone"}))
        reading = read(readings, at(minutes=5))
        self.assertEqual(reading.temperature, 20.0)
        self.assertEqual(excluded_as(reading, "gone"), SensorExclusion.QUIET)

    def test_three_sensors_settle_a_disagreement_by_majority(self) -> None:
        reading = read(
            [
                sensor("a", 20.0, moved=-10),
                sensor("b", 20.4, moved=-10),
                sensor("far", 25.0, moved=-10),
            ],
            at(),
        )
        self.assertAlmostEqual(reading.temperature, 20.2)
        self.assertEqual(reading.resting_on, 2)
        self.assertEqual(excluded_as(reading, "far"), SensorExclusion.FAR_FROM_THE_OTHERS)

    def test_a_pair_inside_the_difference_is_averaged_rather_than_dropped(self) -> None:
        reading = read(
            [sensor("a", 20.0, moved=-10), sensor("b", 21.0, moved=-10)],
            at(),
        )
        self.assertEqual(reading.temperature, 20.5)
        self.assertEqual(reading.resting_on, 2)

    def test_a_room_whose_sensors_have_all_gone_quiet_has_no_reading(self) -> None:
        reading = read(
            [sensor("a", 20.0, reported=-120), sensor("b", 21.0, reported=-300)],
            at(),
        )
        self.assertFalse(reading.has_a_temperature)
        self.assertEqual(len(reading.left_out), 2)


if __name__ == "__main__":
    unittest.main()
