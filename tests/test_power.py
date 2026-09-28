"""What a heater's meter confirms, and the one room where it is the only evidence there is.

Measured at the cabin on 2026-09-24: a close drew 615 W for four minutes and then about 1 W with the
relay still shut, and the next close drew 1.2 W for its whole five minutes. A closed relay is not
evidence of heat.
"""

from __future__ import annotations

import unittest

from _core import at
from core.power import PowerWatch
from core.reasons import Fault


class WhatTheMeterSays(unittest.TestCase):
    def setUp(self) -> None:
        self.watch = PowerWatch()

    def test_a_closed_relay_drawing_nothing_below_target_names_the_heater(self) -> None:
        self.assertIsNone(self.watch.observe(at(), relay_closed=True, below_target=True, watts=0.5))
        self.assertIsNone(
            self.watch.observe(at(minutes=14), relay_closed=True, below_target=True, watts=0.5)
        )
        self.assertEqual(
            self.watch.observe(at(minutes=15), relay_closed=True, below_target=True, watts=0.5),
            Fault.HEATER_DREW_NOTHING,
        )

    def test_a_room_at_its_temperature_drawing_nothing_is_no_fault(self) -> None:
        """A heater with a thermostat of its own draws nothing once that thermostat is satisfied."""
        self.watch.observe(at(), relay_closed=True, below_target=False, watts=0.5)

        self.assertIsNone(
            self.watch.observe(at(hours=8), relay_closed=True, below_target=False, watts=0.5)
        )

    def test_a_room_with_no_reading_waits_six_hours_and_then_says_so(self) -> None:
        """The clause that carries the weight cannot be asked here, so the answer waits instead."""
        self.watch.observe(at(), relay_closed=True, below_target=None, watts=1.2)

        self.assertIsNone(
            self.watch.observe(at(minutes=15), relay_closed=True, below_target=None, watts=1.2)
        )
        self.assertEqual(
            self.watch.observe(at(hours=6), relay_closed=True, below_target=None, watts=1.2),
            Fault.HEATER_DREW_NOTHING,
        )

    def test_power_drawn_with_the_relay_open_names_a_stuck_relay(self) -> None:
        self.watch.observe(at(), relay_closed=False, below_target=True, watts=615.0)

        self.assertEqual(
            self.watch.observe(at(minutes=15), relay_closed=False, below_target=True, watts=615.0),
            Fault.RELAY_STUCK_CLOSED,
        )

    def test_a_quiet_meter_raises_neither_fault(self) -> None:
        """An unreadable meter is never evidence that a heater is off."""
        self.watch.observe(at(), relay_closed=True, below_target=True, watts=0.0)

        self.assertIsNone(
            self.watch.observe(at(hours=12), relay_closed=True, below_target=True, watts=None)
        )
        self.assertIsNone(self.watch.fault)

    def test_the_heater_running_clears_what_was_building(self) -> None:
        self.watch.observe(at(), relay_closed=True, below_target=True, watts=0.5)
        self.watch.observe(at(minutes=10), relay_closed=True, below_target=True, watts=615.0)

        self.assertIsNone(
            self.watch.observe(at(minutes=20), relay_closed=True, below_target=True, watts=615.0)
        )


if __name__ == "__main__":
    unittest.main()
