"""A room's reading carries everything below it, so each way it can go wrong is proved."""

from __future__ import annotations

import unittest

from _core import at
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

    def test_both_of_a_disagreeing_pair_are_dropped_and_the_room_loses_its_reading(self) -> None:
        reading = read(
            [sensor("a", 18.0, moved=-10), sensor("b", 22.5, moved=-10)],
            at(),
        )
        self.assertIsNone(reading.temperature)
        self.assertEqual(reading.resting_on, 0)
        self.assertEqual(len(reading.disagreeing_pair), 2)
        self.assertEqual(
            {v.temperature for v in reading.disagreeing_pair}, {18.0, 22.5}
        )

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
