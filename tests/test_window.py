"""An open window stops the room, and a window sensor that fell silent must not hold it cold."""

from __future__ import annotations

import unittest

from _core import at
from core.reasons import NotHeating
from core.sensors import SensorReading, read
from core.thermostat import RoomThermostat, WindowState


def room(temperature: float, minutes: float = 0.0):
    return read(
        [SensorReading("sensor.room", temperature, at(minutes=minutes), at(minutes=minutes))],
        at(minutes=minutes),
    )


class WindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.thermostat = RoomThermostat("stue", ["switch.panel"])
        self.thermostat.set_target(21.0, at())
        self.thermostat.evaluate(at(), room(17.0))

    def test_an_open_window_stops_the_room_after_the_delay_and_closing_it_resumes(self) -> None:
        straight_away = self.thermostat.evaluate(
            at(minutes=1), room(17.0, 1), None, WindowState.OPEN
        )
        self.assertTrue(straight_away.heating)

        stopped = self.thermostat.evaluate(at(minutes=6), room(17.0, 6), None, WindowState.OPEN)
        self.assertFalse(stopped.heating)
        self.assertEqual(stopped.reason, NotHeating.WINDOW_IS_OPEN)
        # The target is left where it was, so the card still says what the room is for.
        self.assertEqual(stopped.target, 21.0)

        self.thermostat.evaluate(at(minutes=7), room(17.0, 7), None, WindowState.CLOSED)
        resumed = self.thermostat.evaluate(
            at(minutes=12), room(17.0, 12), None, WindowState.CLOSED
        )
        self.assertTrue(resumed.heating)

    def test_a_window_sensor_that_goes_quiet_stops_counting_as_open(self) -> None:
        self.thermostat.evaluate(at(minutes=1), room(17.0, 1), None, WindowState.OPEN)
        stopped = self.thermostat.evaluate(at(minutes=6), room(17.0, 6), None, WindowState.OPEN)
        self.assertFalse(stopped.heating)

        gone_quiet = self.thermostat.evaluate(
            at(minutes=12), room(17.0, 12), None, WindowState.QUIET
        )
        self.assertTrue(gone_quiet.heating)


if __name__ == "__main__":
    unittest.main()
