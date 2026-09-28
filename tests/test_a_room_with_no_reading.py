"""The third kind of room: a heater on a switch, nothing to measure it, and its own dial.

Measured at the cabin on 2026-09-24 on a room set up that way: it paced the ordinary cycle at a duty
worked out from a target it cannot perceive and an outdoor temperature it has never seen, reported a
problem for ever, and accepted all three actions that need a number. These tests are what that run
would have failed.
"""

from __future__ import annotations

import unittest
from datetime import timedelta

from _core import at
from core.defaults import STANDARD
from core.loop import Stage
from core.reasons import NotHeating, Refused
from core.sensors import NO_READING, SensorReading, read
from core.thermostat import RoomThermostat


def a_room_with_no_reading() -> RoomThermostat:
    return RoomThermostat("soverom_2", ["switch.bedroom_heat"], no_reading_at_all=True)


class ARoomWithNoReading(unittest.TestCase):
    def test_it_is_switched_on_and_off_rather_than_pacing_a_cycle(self) -> None:
        thermostat = a_room_with_no_reading()
        thermostat.set_regulation(switched="on")

        on = thermostat.evaluate(at(), NO_READING)
        self.assertTrue(on.heating)
        self.assertEqual(on.stage, Stage.SWITCHED_ON)
        self.assertEqual(on.duty, 1.0)

        # Past the shortest time between relay changes, or the guard answers instead of the mode.
        thermostat.set_regulation(switched="off")
        off = thermostat.evaluate(at(minutes=6), NO_READING)

        self.assertFalse(off.heating)
        self.assertEqual(off.stage, Stage.SWITCHED_OFF)
        self.assertEqual(off.duty, 0.0)
        self.assertEqual(off.reason, NotHeating.THE_MODE_SAYS_OFF)

    def test_a_room_that_has_lost_its_sensors_still_repeats_its_holding_duty(self) -> None:
        """The other direction, and the one the cabin ran into: these are different situations."""
        thermostat = RoomThermostat("stue", ["switch.stue"])
        thermostat.set_target(20.0, at())
        thermostat.evaluate(
            at(), read([SensorReading("sensor.stue", 19.0, at(), at())], at()), outdoor=0.0
        )

        quiet = thermostat.evaluate(at(hours=3), NO_READING, outdoor=0.0)

        self.assertEqual(quiet.stage, Stage.REPEATING_THE_HOLDING_DUTY)
        self.assertGreater(quiet.duty, 0.0)

    def test_nothing_is_commanded_before_the_planner_has_said_which(self) -> None:
        """There is no duty to repeat, so the fallback leaves the relay exactly as it was."""
        thermostat = a_room_with_no_reading()

        first = thermostat.evaluate(at(), NO_READING)

        self.assertFalse(first.heating)
        self.assertEqual(first.commands, ())

    def test_the_three_actions_that_need_a_number_are_refused(self) -> None:
        thermostat = a_room_with_no_reading()

        for call in (
            lambda: thermostat.warm_room_by(18.0, at(hours=6), at()),
            lambda: thermostat.hold_temperature(18.0, timedelta(minutes=5), at()),
            lambda: thermostat.set_warming_rate(1.0, None),
        ):
            with self.assertRaises(Refused) as refused:
                call()
            self.assertEqual(refused.exception.reason, NotHeating.THE_ROOM_HAS_NO_READING)

        self.assertIsNone(thermostat.warm_up)
        self.assertIsNone(thermostat.hold)
        self.assertFalse(thermostat.warming_rate.measured)

        # The two that only write numbers are accepted, because neither promises anything.
        thermostat.set_regulation(switched="on")
        thermostat.return_to_target(at())

    def test_it_does_not_report_a_problem_for_having_no_reading(self) -> None:
        thermostat = a_room_with_no_reading()
        thermostat.set_regulation(switched="on")

        self.assertFalse(thermostat.evaluate(at(), NO_READING).reports_a_problem)

    def test_a_mode_that_has_spoken_cannot_be_put_back_to_having_said_nothing(self) -> None:
        """Decided rather than missing: the state before the first instruction does not come back.

        Every mode cell holds on or off, so the planner always has one of the two to send. Leaving
        the relay exactly as it was is what a room does before anything has told it, and nothing
        needs to return it there. A call that names no value leaves the last instruction standing.
        """
        thermostat = a_room_with_no_reading()
        thermostat.set_regulation(switched="on")

        thermostat.set_regulation(band=0.6)

        self.assertEqual(str(thermostat.regulation.switched), "on")
        self.assertTrue(thermostat.evaluate(at(minutes=6), NO_READING).heating)

    def test_a_rate_it_could_never_have_measured_is_cleared_on_the_next_evaluation(self) -> None:
        """Reaches a room already carrying one, which is the state the cabin's room is in."""
        thermostat = a_room_with_no_reading()

        # Set before the refusal existed, which is the only way such a room can carry one.
        thermostat.no_reading_at_all = False
        thermostat.set_warming_rate(1.0, None)
        thermostat.no_reading_at_all = True
        self.assertTrue(thermostat.warming_rate.measured)

        thermostat.evaluate(at(), NO_READING)

        self.assertFalse(thermostat.warming_rate.measured)
        self.assertEqual(thermostat.warming_rate.degrees_per_hour, STANDARD.warming_rate_by_hand)

    def test_a_sliver_of_a_cycle_delivers_nothing_rather_than_the_guards_five_minutes(self) -> None:
        """Measured at the cabin: a duty asking for fifty-four seconds held the relay for five
        minutes, because a transition inside the guard was stretched rather than skipped."""
        thermostat = RoomThermostat("stue", ["switch.stue"])
        thermostat.set_target(20.0, at())

        # A room just above its target with the outdoor term alone asking for a sliver of the cycle.
        warm = read([SensorReading("sensor.stue", 20.0, at(), at())], at())
        first = thermostat.evaluate(at(), warm, outdoor=-8.0)

        # Fourteen per cent of a fifteen-minute cycle is two minutes, and the relay may not change
        # for
        # five, so the cycle delivers nothing at all and the relay never moves.
        later = thermostat.evaluate(at(minutes=3), warm, outdoor=-8.0)

        for decision in (first, later):
            self.assertLess(decision.duty, 0.2)
            self.assertGreater(decision.duty, 0.0)
            self.assertEqual(decision.delivered, 0.0)
            self.assertFalse(decision.heating)
            self.assertFalse(decision.held_by_the_relay_guard)


if __name__ == "__main__":
    unittest.main()
