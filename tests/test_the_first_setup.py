"""The setup dialog's two guards: an entity outside any area makes no room, and writing the label
leaves every other label an entity carries."""

from __future__ import annotations

import unittest

import _core  # noqa: F401
from core.setup import (
    every_heater,
    label_the_setup_offers,
    labels_after_the_call,
    labels_to_write,
    without_an_area,
)


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


class TheLabelRoomsAreFoundByTests(unittest.TestCase):
    """The first setup picks the label, and an add-on with none picked never takes it away."""

    def test_an_add_on_with_no_label_picked_leaves_the_setups_label_in_place(self) -> None:
        stored = {"include_label": "heat", "exclude_label": "adaptive_exclude"}
        sent_nothing = {"exclude_label": "adaptive_exclude"}

        unpicked = labels_after_the_call(stored, sent_nothing, "heating", "adaptive_exclude")
        picked = labels_after_the_call(stored, {"include_label": "varme"}, "heating", "adaptive_exclude")

        self.assertEqual(unpicked["include_label"], "heat")
        self.assertEqual(picked["include_label"], "varme")

    def test_a_label_the_add_on_already_sent_is_shown_and_not_offered(self) -> None:
        existing = ["heat", "heating"]

        self.assertEqual(label_the_setup_offers({"include_label": "heat"}, existing, "heating"), ("heat", False))
        self.assertEqual(label_the_setup_offers({}, existing, "heating"), ("heating", True))
        self.assertEqual(label_the_setup_offers({}, ["heat"], "heating"), (None, True))


class EveryHeaterTests(unittest.TestCase):
    def test_every_heater_with_an_area_is_ticked_and_our_own_and_homeless_ones_are_not(self) -> None:
        ticked = every_heater(
            [
                ("switch.socket", "switch", "shelly", "stue"),
                ("input_boolean.panel", "input_boolean", None, "bad"),
                ("climate.floor", "climate", "zha", "bad"),
                ("climate.stue", "climate", "adaptive_heating", "stue"),
                ("switch.loose", "switch", "shelly", None),
                ("light.lamp", "light", "hue", "stue"),
            ],
            ("switch", "input_boolean", "climate"),
            "adaptive_heating",
        )

        self.assertEqual(ticked, ["climate.floor", "input_boolean.panel", "switch.socket"])

if __name__ == "__main__":
    unittest.main()
