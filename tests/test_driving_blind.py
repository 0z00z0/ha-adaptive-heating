"""A room whose sensors have gone quiet, and how much heat it may repeat.

Measured on this loop: a room 3 °C below its target computes a duty of 1.0 and remembers it for
that target. One minute later every sensor goes quiet, and over six hours blind the relay is closed
all of the time. The duty was remembered with no test on which stage produced it, so the law's own
full-output stage entered the memory, and nothing capped or bounded what the fallback repeated.
"""

from __future__ import annotations

import unittest

from _core import at
from core.defaults import STANDARD
from core.loop import HeaterLoop, Stage
from core.regulation import Regulation
from core.sensors import NO_READING, SensorReading, read
from core.thermostat import RoomThermostat


def a_reading(temperature: float, minutes: float = 0.0):
    return read(
        [SensorReading("sensor.room", temperature, at(minutes=minutes), at(minutes=minutes))],
        at(minutes=minutes),
    )


class FullOutputNeverEntersTheMemoryTests(unittest.TestCase):
    def test_a_room_far_below_its_target_remembers_nothing_from_its_full_output_stage(self) -> None:
        loop = HeaterLoop("switch.panel")
        regulation = Regulation()

        # Three degrees below target, which is twice the handover distance: the law's own full
        # output stage, and the state the cabin was in when the measurement was taken.
        flat_out = loop.evaluate(at(), 18.0, 21.0, -10.0, regulation)
        self.assertIs(flat_out.stage, Stage.FULL_OUTPUT)
        self.assertEqual(flat_out.duty, 1.0)

        self.assertIsNone(loop.remembered_for(21.0))

    def test_the_relay_is_not_closed_all_of_the_time_over_six_hours_blind(self) -> None:
        """The measurement this file exists for: 100 % of six hours, on a remembered 1.0."""
        loop = HeaterLoop("switch.panel")
        regulation = Regulation()

        loop.evaluate(at(), 18.0, 21.0, -10.0, regulation)

        closed = 0
        ticks = 0
        for tick in range(1, 6 * 60):
            blind = loop.evaluate(at(minutes=tick), None, 21.0, -10.0, regulation)
            self.assertIs(blind.stage, Stage.REPEATING_THE_HOLDING_DUTY)
            ticks += 1
            closed += 1 if blind.relay_closed else 0

        self.assertLess(closed / ticks, 0.7)
        # And heat continues rather than stopping: an unheated cabin in January costs more.
        self.assertGreater(closed / ticks, 0.0)


class TheFractionIsCappedTests(unittest.TestCase):
    def test_the_blind_fraction_never_passes_the_top_of_the_deliverable_band(self) -> None:
        loop = HeaterLoop("switch.panel")
        regulation = Regulation()

        # A file written before the cap existed, or by a room that held at nearly full output.
        loop.restore({"remembered": {"21.0": 1.0}})

        blind = loop.evaluate(at(), None, 21.0, -10.0, regulation)

        # Both figures: what the room says it is repeating, and what the relay is held for.
        self.assertLessEqual(blind.duty, regulation.deliverable_ceiling)
        self.assertLessEqual(blind.delivered, regulation.deliverable_ceiling)
        self.assertGreater(blind.delivered, 0.0)

    def test_a_room_with_nothing_remembered_runs_the_fixed_last_resort_fraction(self) -> None:
        loop = HeaterLoop("switch.panel")
        regulation = Regulation()

        blind = loop.evaluate(at(), None, 21.0, -10.0, regulation)

        self.assertIs(blind.stage, Stage.REPEATING_THE_HOLDING_DUTY)
        self.assertAlmostEqual(blind.duty, STANDARD.blind_last_resort_fraction)
        # Fifteen per cent of a fifteen-minute cycle is shorter than the guard, and a missing
        # reading may not switch a heater off, so blind driving rounds up rather than to nothing.
        self.assertAlmostEqual(blind.delivered, regulation.deliverable_floor)


class HowLongBlindDrivingLastsTests(unittest.TestCase):
    def test_a_remembered_fraction_is_not_repeated_past_the_window_it_was_measured_over(
        self,
    ) -> None:
        loop = HeaterLoop("switch.panel")
        regulation = Regulation()

        # A holding duty in the middle of the deliverable band, so the fall to the last resort
        # shows as a different figure rather than as the same one twice.
        loop.evaluate(at(), 20.25, 21.0, 21.0, regulation)
        held = loop.remembered_for(21.0)
        self.assertIsNotNone(held)

        # The spell starts here, so the window runs from this evaluation and not from the reading.
        loop.evaluate(at(hours=1), None, 21.0, 21.0, regulation)
        inside = loop.evaluate(at(hours=23), None, 21.0, 21.0, regulation)
        self.assertAlmostEqual(inside.duty, held)

        past = loop.evaluate(at(hours=26), None, 21.0, 21.0, regulation)
        self.assertAlmostEqual(past.duty, STANDARD.blind_last_resort_fraction)
        self.assertNotAlmostEqual(past.duty, held)

    def test_the_blind_spell_starts_again_once_a_reading_returns(self) -> None:
        loop = HeaterLoop("switch.panel")
        regulation = Regulation()

        loop.evaluate(at(), 20.25, 21.0, 21.0, regulation)
        loop.evaluate(at(hours=1), None, 21.0, 21.0, regulation)
        loop.evaluate(at(hours=23), 20.25, 21.0, 21.0, regulation)

        # Twenty-six hours after the sensors first went, and nothing into this spell.
        again = loop.evaluate(at(hours=26), None, 21.0, 21.0, regulation)
        self.assertAlmostEqual(again.duty, loop.remembered_for(21.0))


class TheFallbackReachesAWholeRoomTests(unittest.TestCase):
    def test_a_room_that_loses_its_sensors_at_full_output_does_not_stay_closed(self) -> None:
        """The whole room, not one loop: the case the existing fallback test could not reach."""
        thermostat = RoomThermostat("stue", ["switch.stue"])
        thermostat.set_target(21.0, at())

        thermostat.evaluate(at(), a_reading(18.0), outdoor=-10.0)

        closed = 0
        ticks = 0
        for tick in range(1, 6 * 60):
            blind = thermostat.evaluate(at(minutes=tick), NO_READING, outdoor=-10.0)
            self.assertIs(blind.stage, Stage.REPEATING_THE_HOLDING_DUTY)
            ticks += 1
            closed += 1 if blind.heating else 0

        self.assertLess(closed / ticks, 0.7)
        self.assertGreater(closed / ticks, 0.0)


if __name__ == "__main__":
    unittest.main()
