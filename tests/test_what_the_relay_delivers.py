"""What a cycle actually delivers, against what the law asked for.

Measured on this loop at the shipped fifteen-minute cycle and five-minute guard, twelve hours of
ten-second ticks: a duty of 0.05 held the relay closed for a third of every cycle and a duty of 0.95
held it closed for two thirds, while the card reported the figure asked for in both cases. A
too-short on-time was stretched to the guard rather than dropped, so a room barely needing heat took
up to seven times what it asked for, and a room needing more than two thirds could not hold its
target at all.
"""

from __future__ import annotations

import unittest

from _core import at
from core.loop import HeaterLoop, Stage
from core.regulation import Regulation


def a_cycle(duty_wanted: float) -> tuple[HeaterLoop, Regulation, float]:
    """A room whose distance from its target asks for that duty, and nothing else."""
    regulation = Regulation()
    target = 21.0
    # The distance term alone: the outdoor reading is set to the target so the outdoor term is nil.
    room = target - duty_wanted * regulation.full_output_below
    return HeaterLoop("switch.panel"), regulation, room


class WhatOneCycleDeliversTests(unittest.TestCase):
    def test_a_duty_too_small_to_deliver_is_skipped_rather_than_stretched(self) -> None:
        loop, regulation, room = a_cycle(0.05)

        first = loop.evaluate(at(), room, 21.0, 21.0, regulation)

        self.assertAlmostEqual(first.duty, 0.05, places=3)
        self.assertEqual(first.delivered, 0.0)
        self.assertFalse(first.relay_closed)

        # The measured fault: the relay closed at the start of the cycle and the guard then held it
        # closed for the whole five minutes, a third of the cycle, for a duty asking forty-five
        # seconds.
        for minute in (1, 2, 4, 6, 8, 14):
            later = loop.evaluate(at(minutes=minute), room, 21.0, 21.0, regulation)
            self.assertFalse(later.relay_closed, minute)
            self.assertEqual(later.delivered, 0.0, minute)

    def test_a_duty_too_large_to_deliver_becomes_full_output(self) -> None:
        loop, regulation, room = a_cycle(0.95)

        first = loop.evaluate(at(), room, 21.0, 21.0, regulation)

        self.assertAlmostEqual(first.duty, 0.95, places=3)
        self.assertEqual(first.delivered, 1.0)
        self.assertTrue(first.relay_closed)

        # Two thirds was the measured delivery. The relay now stays closed across the roll-over.
        for minute in (6, 12, 14, 16, 20):
            later = loop.evaluate(at(minutes=minute), room, 21.0, 21.0, regulation)
            self.assertTrue(later.relay_closed, minute)
            self.assertEqual(later.delivered, 1.0, minute)

    def test_a_duty_inside_the_deliverable_band_is_paced_as_asked(self) -> None:
        loop, regulation, room = a_cycle(0.5)

        closed = loop.evaluate(at(), room, 21.0, 21.0, regulation)
        self.assertAlmostEqual(closed.delivered, 0.5, places=3)
        self.assertTrue(closed.relay_closed)

        # Half of fifteen minutes is seven and a half, and both phases clear the five-minute guard.
        self.assertTrue(loop.evaluate(at(minutes=7), room, 21.0, 21.0, regulation).relay_closed)
        self.assertFalse(loop.evaluate(at(minutes=8), room, 21.0, 21.0, regulation).relay_closed)

    def test_the_deliverable_band_is_the_guard_over_the_cycle(self) -> None:
        regulation = Regulation()

        self.assertAlmostEqual(regulation.deliverable_floor, 1.0 / 3.0)
        self.assertAlmostEqual(regulation.deliverable_ceiling, 2.0 / 3.0)

        # Confirmed by re-running with the guard at one minute of fifteen, where delivered tracks
        # asked-for to within a fifteenth and the distorted band all but disappears.
        wide = Regulation(shortest_time_between_relay_changes=regulation.cycle_length / 15)
        self.assertAlmostEqual(wide.deliverable_floor, 1.0 / 15.0)
        self.assertAlmostEqual(wide.deliverable(0.1), 0.1)
        self.assertAlmostEqual(wide.deliverable(0.9), 0.9)


class WhatTheLearningReadsTests(unittest.TestCase):
    def test_the_fraction_remembered_is_the_one_delivered_and_not_the_one_asked_for(self) -> None:
        """Anything learning from a duty the relay did not run is fitted against a fiction."""
        loop, regulation, room = a_cycle(0.05)

        delivered = loop.evaluate(at(), room, 21.0, 21.0, regulation)

        self.assertEqual(delivered.delivered, 0.0)
        self.assertEqual(loop.remembered_for(21.0), 0.0)

    def test_a_cycle_delivered_as_full_output_is_not_remembered_as_a_holding_duty(self) -> None:
        loop, regulation, room = a_cycle(0.95)

        loop.evaluate(at(), room, 21.0, 21.0, regulation)

        self.assertIsNone(loop.remembered_for(21.0))


class WhatTheDeliveredFigureMustNotDecideTests(unittest.TestCase):
    """Upstream's most expensive fault: the realised figure read as whether a cycle was running.

    One set of fields held both the running cycle's parameters and the next cycle's, so a
    recalculation clamped to nothing wrote "nothing next time", a later one read that as "no cycle
    is running", cancelled the running cycle and opened the relay mid-cycle. Fixed in its release
    9.3.3, 2026-04-12.
    """

    def test_a_cycle_delivering_nothing_is_still_a_running_cycle(self) -> None:
        loop, regulation, room = a_cycle(0.05)

        loop.evaluate(at(), room, 21.0, 21.0, regulation)
        started = loop.cycle_started_at
        self.assertIsNotNone(started)

        loop.evaluate(at(minutes=7), room, 21.0, 21.0, regulation)
        self.assertEqual(loop.cycle_started_at, started)

        # The roll-over is the clock's business, and nothing else moves it.
        loop.evaluate(at(minutes=16), room, 21.0, 21.0, regulation)
        self.assertNotEqual(loop.cycle_started_at, started)

    def test_a_room_delivering_nothing_still_says_which_stage_produced_the_duty(self) -> None:
        loop, regulation, room = a_cycle(0.05)

        nothing = loop.evaluate(at(), room, 21.0, 21.0, regulation)

        self.assertIs(nothing.stage, Stage.PACING)


if __name__ == "__main__":
    unittest.main()
