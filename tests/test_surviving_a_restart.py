"""What a room comes back holding, because a cut is the one thing a cabin's heating must survive."""

from __future__ import annotations

import json
import unittest
from datetime import timedelta

from _core import at
from core.regulation import HoldingBehaviour
from core.sensors import SensorReading, read
from core.thermostat import RoomThermostat


def room(temperature: float, minutes: float = 0.0):
    return read(
        [SensorReading("sensor.room", temperature, at(minutes=minutes), at(minutes=minutes))],
        at(minutes=minutes),
    )


def after_a_cut(before: RoomThermostat, now) -> RoomThermostat:
    """What the file holds is the whole of what crosses the cut, so it goes through JSON."""
    written = json.loads(json.dumps(before.as_dict()))
    after = RoomThermostat(before.room_id, [loop.heater_id for loop in before.loops])
    after.restore(written, now)
    return after


class RestartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.thermostat = RoomThermostat("stue", ["switch.panel"])
        self.thermostat.set_target(19.5, at())
        self.thermostat.set_regulation(
            behaviour="band", full_output_below=2.5, cycle_length=timedelta(minutes=20)
        )
        self.thermostat.set_warming_rate(1.75, -3.0)
        self.thermostat.evaluate(at(), room(18.0))

    def test_the_room_comes_back_on_the_temperature_it_wrote_down(self) -> None:
        after = after_a_cut(self.thermostat, at(minutes=5))
        self.assertEqual(after.target, 19.5)
        self.assertEqual(after.evaluate(at(minutes=5), room(18.0, 5)).target, 19.5)

    def test_the_regulation_numbers_and_the_measured_rate_come_back(self) -> None:
        after = after_a_cut(self.thermostat, at(minutes=5))
        self.assertIs(after.regulation.behaviour, HoldingBehaviour.BAND)
        self.assertEqual(after.regulation.full_output_below, 2.5)
        self.assertEqual(after.regulation.cycle_length, timedelta(minutes=20))
        self.assertEqual(after.warming_rate.degrees_per_hour, 1.75)
        self.assertTrue(after.warming_rate.measured)

    def test_the_relay_guard_comes_back_so_the_first_change_is_not_blocked_for_the_minimum(
        self,
    ) -> None:
        after = after_a_cut(self.thermostat, at(minutes=8))
        self.assertTrue(after.loops[0].relay_closed)
        self.assertEqual(after.loops[0].last_change_at, at())

        # Eight minutes have passed, which is past the shortest time between changes, so the room
        # reaching its temperature opens the relay at once rather than waiting the whole minimum.
        decision = after.evaluate(at(minutes=8), room(21.0, 8))
        self.assertFalse(decision.heating)
        self.assertEqual(len(decision.commands), 1)

    def test_a_hold_that_ran_out_while_the_system_was_down_reads_as_expired(self) -> None:
        self.thermostat.hold_temperature(23.0, timedelta(hours=1), at())
        after = after_a_cut(self.thermostat, at(hours=4))
        self.assertIsNone(after.hold)
        self.assertEqual(after.evaluate(at(hours=4), room(18.0, 240)).target, 19.5)

    def test_a_hold_still_running_is_resumed(self) -> None:
        self.thermostat.hold_temperature(23.0, timedelta(hours=4), at())
        after = after_a_cut(self.thermostat, at(hours=1))
        self.assertIsNotNone(after.hold)
        self.assertEqual(after.evaluate(at(hours=1), room(18.0, 60)).target, 23.0)

    def test_the_freshness_record_crosses_the_cut_and_drops_what_is_a_week_old(self) -> None:
        self.thermostat.freshness.note("sensor.room", 18.0, at())
        self.thermostat.freshness.note("sensor.loft", 12.0, at(days=-8))

        after = after_a_cut(self.thermostat, at(minutes=5))
        readings = {
            reading.sensor_id: reading
            for reading in after.freshness.readings(["sensor.room", "sensor.loft"], at(minutes=5))
        }
        self.assertEqual(readings["sensor.room"].temperature, 18.0)
        self.assertEqual(readings["sensor.room"].reported_at, at())
        # An unknown time counts as stale, so the dropped record cannot be read as fresh.
        self.assertIsNone(readings["sensor.loft"].temperature)
        self.assertTrue(
            at(minutes=5) - readings["sensor.loft"].reported_at > timedelta(hours=1)
        )


if __name__ == "__main__":
    unittest.main()
