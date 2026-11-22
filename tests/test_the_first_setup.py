"""The setup dialog's two guards: an entity outside any area makes no room, and writing the label
leaves every other label an entity carries."""

from __future__ import annotations

import unittest

import _core  # noqa: F401
from core.setup import labels_to_write, without_an_area


class TheFirstSetupTests(unittest.TestCase):
    def test_an_entity_in_no_area_is_named_and_one_in_an_area_is_not(self) -> None:
        homeless = without_an_area(
            ["switch.panel", "sensor.loose", "switch.nowhere"],
            {"switch.panel": "stue", "sensor.loose": None},
        )

        self.assertEqual(homeless, ["sensor.loose", "switch.nowhere"])

    def test_the_label_joins_the_ones_already_carried_and_an_unticked_entity_keeps_the_rest(
        self,
    ) -> None:
        written = labels_to_write(
            {
                "switch.panel": {"kitchen", "energy"},
                "switch.done": {"heating", "energy"},
                "switch.dropped": {"heating", "energy"},
            },
            "heating",
            ["switch.panel", "switch.done"],
            ["switch.dropped"],
        )

        self.assertEqual(
            written,
            {"switch.panel": {"kitchen", "energy", "heating"}, "switch.dropped": {"energy"}},
        )

    def test_nothing_loses_the_label_unless_it_was_shown_ticked(self) -> None:
        self.assertEqual(
            labels_to_write(
                {"switch.panel": set(), "switch.other": {"heating"}}, "heating", ["switch.panel"]
            ),
            {"switch.panel": {"heating"}},
        )


if __name__ == "__main__":
    unittest.main()
