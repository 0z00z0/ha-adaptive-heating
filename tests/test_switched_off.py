"""A thermostat switched off is an owner's act, and this is what it was decided to do."""

from __future__ import annotations

import unittest
from datetime import timedelta

from _core import at
from core.reasons import NotHeating, Refused
from core.sensors import SensorReading, read
from core.thermostat import RoomThermostat


def warm_room(temperature: float, minutes: float) -> object:
    return read([SensorReading("sensor.room", temperature, at(minutes=minutes),
                               at(minutes=minutes))], at(minutes=minutes))


class SwitchedOffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.thermostat = RoomThermostat("stue", ["switch.panel"])
        self.thermostat.set_target(21.0, at())
        # A cold room, so a thermostat that heats at all would be heating.
        self.thermostat.evaluate(at(), warm_room(17.0, 0))

    def test_the_relay_opens_once_and_nothing_is_commanded_after_that(self) -> None:
        self.assertTrue(self.thermostat.loops[0].relay_closed)

        self.thermostat.switch_off(at(minutes=1))
        first = self.thermostat.evaluate(at(minutes=1), warm_room(17.0, 1))
        self.assertEqual(len(first.commands), 1)
        self.assertFalse(first.commands[0].closed)

        for minute in range(2, 40):
            later = self.thermostat.evaluate(at(minutes=minute), warm_room(10.0, minute))
            self.assertEqual(later.commands, ())
            self.assertFalse(later.heating)

    def test_it_keeps_its_reading_and_shows_the_temperature_it_would_hold(self) -> None:
        self.thermostat.switch_off(at(minutes=1))
        decision = self.thermostat.evaluate(at(minutes=2), warm_room(18.5, 2))
        self.assertEqual(decision.target, 21.0)
        self.assertEqual(self.thermostat.reading.temperature, 18.5)
        self.assertEqual(decision.resting_on, 1)
        self.assertEqual(decision.reason, NotHeating.ROOM_IS_SWITCHED_OFF)

    def test_a_switched_off_room_is_left_out_of_the_problem_report(self) -> None:
        quiet = read(
            [SensorReading("sensor.room", 18.0, at(hours=-5), at(hours=-5))], at(minutes=2)
        )
        while_on = self.thermostat.evaluate(at(minutes=2), quiet)
        self.assertTrue(while_on.reports_a_problem)

        self.thermostat.switch_off(at(minutes=3))
        while_off = self.thermostat.evaluate(at(minutes=4), quiet)
        self.assertFalse(while_off.reports_a_problem)

    def test_nothing_with_a_time_in_it_is_queued_while_it_is_off(self) -> None:
        self.thermostat.switch_off(at(minutes=1))

        with self.assertRaises(Refused) as warm:
            self.thermostat.warm_room_by(22.0, at(hours=3), at(minutes=1))
        self.assertEqual(warm.exception.reason, NotHeating.ROOM_IS_SWITCHED_OFF)

        with self.assertRaises(Refused) as hold:
            self.thermostat.hold_temperature(23.0, timedelta(hours=1), at(minutes=1))
        self.assertEqual(hold.exception.reason, NotHeating.ROOM_IS_SWITCHED_OFF)

        self.assertIsNone(self.thermostat.warm_up)
        self.assertIsNone(self.thermostat.hold)

        self.thermostat.switch_on(at(minutes=2))
        decision = self.thermostat.evaluate(at(minutes=20), warm_room(17.0, 20))
        self.assertEqual(decision.target, 21.0)
        self.assertIsNone(self.thermostat.warm_up)
        self.assertIsNone(self.thermostat.hold)

    def test_a_warm_up_running_when_it_is_switched_off_does_not_arrive_late(self) -> None:
        self.thermostat.warm_room_by(22.0, at(hours=2), at())
        self.assertIsNotNone(self.thermostat.warm_up)

        self.thermostat.switch_off(at(minutes=1))
        self.assertIsNone(self.thermostat.warm_up)

        self.thermostat.switch_on(at(minutes=2))
        decision = self.thermostat.evaluate(at(minutes=20), warm_room(17.0, 20))
        self.assertEqual(decision.target, 21.0)

    def test_a_person_switching_it_on_resumes_heating_at_the_next_evaluation(self) -> None:
        self.thermostat.switch_off(at(minutes=1))
        self.thermostat.evaluate(at(minutes=1), warm_room(17.0, 1))

        self.thermostat.switch_on(at(minutes=10))
        resumed = self.thermostat.evaluate(at(minutes=10), warm_room(17.0, 10))
        self.assertTrue(resumed.heating)
        self.assertEqual(len(resumed.commands), 1)
        self.assertTrue(resumed.commands[0].closed)

    def test_the_off_state_comes_back_switched_off_after_a_restart(self) -> None:
        self.thermostat.switch_off(at(minutes=1))
        self.thermostat.evaluate(at(minutes=1), warm_room(17.0, 1))
        written = self.thermostat.as_dict()

        after = RoomThermostat("stue", ["switch.panel"])
        after.restore(written, at(minutes=30))
        self.assertFalse(after.switched_on)

        decision = after.evaluate(at(minutes=30), warm_room(12.0, 30))
        self.assertFalse(decision.heating)
        self.assertEqual(decision.commands, ())
        self.assertEqual(decision.reason, NotHeating.ROOM_IS_SWITCHED_OFF)

    def test_an_ordinary_evaluation_never_switches_it_back_on(self) -> None:
        self.thermostat.switch_off(at(minutes=1))
        for minute in range(1, 200, 5):
            self.thermostat.evaluate(at(minutes=minute), warm_room(5.0, minute))
        self.assertFalse(self.thermostat.switched_on)


if __name__ == "__main__":
    unittest.main()
