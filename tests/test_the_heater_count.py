"""The card says how many heaters the room drives and how many do not answer, as lighting counts lamps."""

from __future__ import annotations

import unittest

from _core import at
from core import card
from core.loop import RelayObservation
from core.sensors import SensorReading, read
from core.setpoint import observe
from core.thermostat import RoomThermostat

HEATERS = ["switch.panel_1", "switch.panel_2", "climate.panel_3"]


def the_card_with(relays: dict[str, object]) -> dict[str, object]:
    room = RoomThermostat("stue", HEATERS)
    room.set_target(20.0, at())
    reading = read([SensorReading("sensor.room", 19.0, at(), at())], at())
    decision = room.evaluate(at(), reading, 5.0, relays=relays)  # type: ignore[arg-type]
    return card.attributes("room_001", "stue", "0.1.0", 1, room, decision, reading, 5.0, False)


def answering() -> dict[str, object]:
    return {
        "switch.panel_1": RelayObservation(False, at()),
        "switch.panel_2": RelayObservation(True, at()),
        "climate.panel_3": observe("heat", {"temperature": 20.0}),
    }


class TheHeaterCountTests(unittest.TestCase):
    def test_one_silent_heater_of_three_is_one_of_three(self) -> None:
        relays = answering()
        relays["switch.panel_2"] = RelayObservation(None, None)

        attributes = the_card_with(relays)

        self.assertEqual((attributes["heaters_not_responding"], attributes["heater_count"]), (1, 3))

    def test_every_heater_answering_is_none_of_three(self) -> None:
        attributes = the_card_with(answering())

        self.assertEqual((attributes["heaters_not_responding"], attributes["heater_count"]), (0, 3))

    def test_a_thermostat_underneath_that_has_gone_counts_as_well(self) -> None:
        relays = answering()
        relays["climate.panel_3"] = observe("unavailable", {})

        self.assertEqual(the_card_with(relays)["heaters_not_responding"], 1)


if __name__ == "__main__":
    unittest.main()
