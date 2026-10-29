"""Every attribute the card publishes is declared unrecorded.

A key added to the card and left out of the set is recorded for ever, in a database a household
never looks at, and nothing about the running system shows it.
"""

from __future__ import annotations

import unittest

from _core import at
from core import card
from core.sensors import SensorReading, read
from core.thermostat import RoomThermostat


class WhatTheCardPublishesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.room = RoomThermostat("stue", ["switch.stue"])
        self.reading = read([SensorReading("sensor.stue", 19.0, at(), at())], at())
        self.decision = self.room.evaluate(at(), self.reading)

    def published(self) -> set[str]:
        return set(
            card.attributes("room_001", "stue", "0.1.0", 1, self.room, self.decision, self.reading, -4.0, True)
        )

    def test_every_key_the_card_publishes_is_declared_unrecorded(self) -> None:
        self.assertEqual(self.published() - card.EVERY_ATTRIBUTE, set())

    def test_the_set_names_nothing_the_card_does_not_publish(self) -> None:
        self.assertEqual(card.EVERY_ATTRIBUTE - self.published(), set())

    def test_the_card_names_the_room_by_its_id_and_the_area_apart(self) -> None:
        """Both halves key a room by its room id, so a moved or renamed Area is the same room."""
        published = card.attributes(
            "room_001", "stue", "0.1.0", 2, self.room, self.decision, self.reading, -4.0, True
        )
        self.assertEqual(
            (published[card.ATTR_ROOM_ID], published[card.ATTR_AREA_ID]), ("room_001", "stue")
        )


if __name__ == "__main__":
    unittest.main()
