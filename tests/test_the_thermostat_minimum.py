"""The card names the lowest a thermostat underneath accepts, which the add-on's night setback stays above."""

from __future__ import annotations

import unittest

from _core import at
from core import card
from core.loop import RelayObservation
from core.sensors import SensorReading, read
from core.setpoint import observe
from core.thermostat import RoomThermostat


def the_card_with(heaters: list[str], relays: dict[str, object]) -> dict[str, object]:
    room = RoomThermostat("stue", heaters)
    room.set_target(20.0, at())
    reading = read([SensorReading("sensor.room", 19.0, at(), at())], at())
    decision = room.evaluate(at(), reading, 5.0, relays=relays)  # type: ignore[arg-type]
    return card.attributes("room_001", "stue", "0.1.0", 1, room, decision, reading, 5.0, False)


class TheThermostatMinimumTests(unittest.TestCase):
    def test_the_highest_minimum_of_the_thermostats_underneath_is_published(self) -> None:
        attributes = the_card_with(
            ["climate.panel_1", "climate.panel_2"],
            {
                "climate.panel_1": observe("heat", {"temperature": 20.0, "min_temp": 5.0}),
                "climate.panel_2": observe("heat", {"temperature": 20.0, "min_temp": 7.0}),
            },
        )

        self.assertEqual(attributes[card.ATTR_THERMOSTAT_MINIMUM], 7.0)

    def test_a_room_driven_through_a_switch_publishes_no_minimum(self) -> None:
        attributes = the_card_with(
            ["switch.panel_1"], {"switch.panel_1": RelayObservation(False, at())}
        )

        self.assertIsNone(attributes[card.ATTR_THERMOSTAT_MINIMUM])

    def test_a_thermostat_that_names_no_minimum_publishes_none(self) -> None:
        attributes = the_card_with(
            ["climate.panel_1"], {"climate.panel_1": observe("heat", {"temperature": 20.0})}
        )

        self.assertIsNone(attributes[card.ATTR_THERMOSTAT_MINIMUM])


if __name__ == "__main__":
    unittest.main()
