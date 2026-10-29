"""A heating mode is a climate preset, chosen on a room's card and held there.

The add-on writes a preset only at a period boundary or a change for the house, and reads the held
one on every other pass, weighed by the moment it was chosen. Anything in the control loop that cleared or replaced it would undo a
person's choice within half a minute and show nowhere.
"""

from __future__ import annotations

import json
import unittest
from datetime import timedelta

from _core import COMPONENT, at
from core import card
from core.sensors import SensorReading, read
from core.thermostat import RoomThermostat

EVALUATION_INTERVAL = timedelta(seconds=30)
STRING_FILES = ("strings.json", "translations/en.json")


def room(temperature: float, minutes: float):
    return read(
        [SensorReading("sensor.stue", temperature, at(minutes=minutes), at(minutes=minutes))],
        at(minutes=minutes),
    )


class ThePresetListTests(unittest.TestCase):
    def test_the_card_offers_seven_presets_and_both_kinds_of_room_can_choose_one(self) -> None:
        for no_reading_at_all in (False, True):
            offered = card.offered(
                RoomThermostat("stue", ["switch.stue"], no_reading_at_all=no_reading_at_all)
            )
            self.assertEqual(
                offered.presets,
                (
                    "away",
                    "sleep",
                    "home",
                    "boost",
                    "planned_to_arrive",
                    "on_the_way",
                    "temporarily_away",
                ),
            )
            self.assertIn("PRESET_MODE", offered.features)


class AChosenPresetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.thermostat = RoomThermostat("stue", ["switch.stue"])

    def test_a_room_starts_with_no_preset(self) -> None:
        self.assertIsNone(self.thermostat.preset)

    def test_a_custom_name_is_accepted_and_reported(self) -> None:
        self.thermostat.set_preset("on_the_way", at())
        self.assertEqual(self.thermostat.preset, "on_the_way")

    def test_a_preset_set_on_the_card_is_still_reported_after_three_evaluation_intervals(
        self,
    ) -> None:
        self.thermostat.set_target(20.0, at())
        self.thermostat.set_preset("temporarily_away", at())

        # Readings either side of the target, so the loop switches the relay in both directions.
        for step, temperature in enumerate((17.0, 21.5, 17.0, 21.5)):
            minutes = (EVALUATION_INTERVAL * step).total_seconds() / 60
            self.thermostat.evaluate(at(minutes=minutes), room(temperature, minutes))

        self.assertEqual(self.thermostat.preset, "temporarily_away")

    def test_it_comes_back_after_a_cut_and_a_name_the_list_no_longer_holds_does_not(self) -> None:
        self.thermostat.set_preset("sleep", at(minutes=5))
        written = json.loads(json.dumps(self.thermostat.as_dict()))

        after = RoomThermostat("stue", ["switch.stue"])
        after.restore(written, at(minutes=60))
        self.assertEqual(after.preset, "sleep")
        # The moment it was chosen, not the restart: the add-on weighs the preset against hand changes by it.
        self.assertEqual(after.preset_set_at, at(minutes=5))

        written["preset"] = "a_name_since_removed"
        again = RoomThermostat("stue", ["switch.stue"])
        again.restore(written, at())
        self.assertIsNone(again.preset)

    def test_a_preset_changes_no_verdict_and_sends_no_command_of_its_own(self) -> None:
        plain = RoomThermostat("stue", ["switch.stue"])
        chosen = RoomThermostat("stue", ["switch.stue"])
        chosen.set_preset("boost", at())
        for thermostat in (plain, chosen):
            thermostat.set_target(20.0, at())

        for step, temperature in enumerate((17.0, 21.5, 17.0)):
            minutes = step * 0.5
            self.assertEqual(
                chosen.evaluate(at(minutes=minutes), room(temperature, minutes)),
                plain.evaluate(at(minutes=minutes), room(temperature, minutes)),
            )


class TheCardCarriesWhenThePresetWasChosenTests(unittest.TestCase):
    def test_the_card_publishes_the_moment_and_keeps_it_from_the_recorder(self) -> None:
        thermostat = RoomThermostat("stue", ["switch.stue"])
        thermostat.set_preset("away", at(minutes=7))
        published = card.attributes("room_001", "stue", "1", 1, thermostat, None, room(19.0, 7), None, False)
        self.assertEqual(published[card.ATTR_PRESET_SET_AT], at(minutes=7).isoformat())
        self.assertIn(card.ATTR_PRESET_SET_AT, card.EVERY_ATTRIBUTE)


class TheCustomNamesAreTranslatedTests(unittest.TestCase):
    def test_the_strings_carry_every_custom_name(self) -> None:
        self.assertEqual(len(card.CUSTOM_PRESETS), 3)
        for file_name in STRING_FILES:
            written = json.loads((COMPONENT / file_name).read_text(encoding="utf-8"))
            names = written["entity"]["climate"]["room"]["state_attributes"]["preset_mode"]["state"]
            for key in card.CUSTOM_PRESETS:
                with self.subTest(file=file_name, key=key):
                    self.assertTrue(names.get(key), f"{file_name} carries no text for {key}")


if __name__ == "__main__":
    unittest.main()
