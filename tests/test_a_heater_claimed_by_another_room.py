"""Two rooms naming one heater, which nothing refused.

Measured: two entries holding at different duties, each with its own loop over one relay, send 384
commands a day against the 192 a single loop sends, and 96 of 191 gaps between commands are shorter
than the five-minute guard, the shortest being nothing at all. Each loop counts only its own
changes, so the contact protection is defeated outright.
"""

from __future__ import annotations

import json
import unittest

from _core import COMPONENT
from core.setup import heater_already_claimed


class AHeaterBelongsToOneRoomTests(unittest.TestCase):
    def test_a_heater_another_room_already_drives_is_refused_and_names_that_room(self) -> None:
        taken = heater_already_claimed(
            ["switch.panel", "switch.oven"],
            {"toalett": ["switch.panel"], "stue": ["switch.stue"]},
        )

        self.assertEqual(taken, ("switch.panel", "toalett"))

    def test_a_heater_no_other_room_drives_is_accepted(self) -> None:
        self.assertIsNone(
            heater_already_claimed(
                ["switch.oven"], {"toalett": ["switch.panel"], "stue": ["switch.stue"]}
            )
        )

    def test_a_room_keeping_its_own_heaters_is_not_refused_against_itself(self) -> None:
        """Changing a room must not read the room's own heaters as somebody else's."""
        rooms = {"toalett": ["switch.panel"], "stue": ["switch.stue"]}
        without_itself = {room: heaters for room, heaters in rooms.items() if room != "toalett"}

        self.assertIsNone(heater_already_claimed(["switch.panel"], without_itself))

    def test_the_same_heater_twice_in_one_room_is_not_a_clash(self) -> None:
        self.assertIsNone(heater_already_claimed(["switch.panel", "switch.panel"], {}))


class TheWordsTheDialogUsesTests(unittest.TestCase):
    """The reason has to name the room that holds the heater, or nobody can act on it."""

    def test_both_dialogs_carry_the_refusal_and_it_names_the_room(self) -> None:
        for name in ("strings.json", "translations/en.json"):
            words = json.loads((COMPONENT / name).read_text(encoding="utf-8"))
            for flow in ("config", "options"):
                sentence = words[flow]["error"]["heater_taken"]
                self.assertIn("{room}", sentence, f"{name} {flow}")
                # Short by design: a label, not prose.
                self.assertLess(len(sentence), 70, f"{name} {flow}")


if __name__ == "__main__":
    unittest.main()
