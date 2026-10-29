"""Which rooms the house has, and every gate that keeps one out.

A room nobody declared is the whole point of reading the registries, so each gate is proved on its
own: a hidden heater, an excluded Area, a sole heater that is unavailable, and a thermostat of this
integration's own.
"""

from __future__ import annotations

import unittest

import _core  # noqa: F401 - puts the component's folder on the path
from core.rooms import Candidate, Room, changed, named_or_discovered, rooms

HEATING = "heating"
EXCLUDED = "adaptive_exclude"
OURS = "adaptive_heating"


def heater(entity_id: str, area_id: str, **rest: object) -> Candidate:
    return Candidate(entity_id, area_id, frozenset({HEATING}), "shelly", **rest)  # type: ignore[arg-type]


def sensor(entity_id: str, area_id: str, **rest: object) -> Candidate:
    return Candidate(
        entity_id, area_id, frozenset({HEATING}), "shelly", device_class="temperature", **rest  # type: ignore[arg-type]
    )


def house(areas: dict[str, set[str]], entities: list[Candidate]) -> dict[str, Room]:
    return rooms(areas, entities, OURS, HEATING, EXCLUDED)


class TheHouseTabsLabelsTests(unittest.TestCase):
    """The add-on's House tab chooses the labels, and the integration finds its rooms by them."""

    def test_a_heater_carrying_the_chosen_label_makes_a_room_and_the_old_label_does_not(self) -> None:
        chosen = Candidate("switch.stue", "stue", frozenset({"varme"}), "shelly")
        old = heater("switch.bad", "bad")

        found = rooms({"stue": set(), "bad": set()}, [chosen, old], OURS, "varme", EXCLUDED)

        self.assertEqual(set(found), {"stue"})

    def test_no_include_label_finds_every_heater_and_the_exclude_label_still_wins(self) -> None:
        loose = Candidate("switch.stue", "stue", frozenset(), "shelly")
        kept_out = Candidate("switch.bad", "bad", frozenset({EXCLUDED}), "shelly")

        found = rooms({"stue": set(), "bad": set()}, [loose, kept_out], OURS, "", EXCLUDED)

        self.assertEqual(set(found), {"stue"})


class AGroupOfHeatersTests(unittest.TestCase):
    def test_a_group_stands_for_its_members_and_never_for_another_room_s(self) -> None:
        group = heater("switch.stue_panels", "stue", members=("switch.stue_a", "switch.loft_b"))
        own = Candidate("switch.stue_a", "stue", frozenset(), "shelly")
        elsewhere = Candidate("switch.loft_b", "loft", frozenset(), "shelly")

        found = house({"stue": set(), "loft": set()}, [group, own, elsewhere])

        self.assertEqual(found["stue"].heaters, ("switch.stue_a",))


class WhichAreasBecomeRoomsTests(unittest.TestCase):
    def test_two_areas_with_a_labelled_heater_make_two_rooms(self) -> None:
        found = house(
            {"stue": set(), "bad": set()},
            [heater("switch.stue", "stue"), heater("climate.bad", "bad")],
        )

        self.assertEqual(set(found), {"stue", "bad"})
        self.assertEqual(found["stue"].heaters, ("switch.stue",))
        self.assertEqual(found["bad"].heaters, ("climate.bad",))

    def test_an_area_with_no_labelled_heater_makes_no_room(self) -> None:
        unlabelled = Candidate("switch.loft", "loft", frozenset(), "shelly")

        self.assertEqual(house({"loft": set()}, [unlabelled]), {})

    def test_a_hidden_labelled_heater_makes_no_room(self) -> None:
        found = house({"stue": set()}, [heater("switch.stue", "stue", hidden=True)])

        self.assertEqual(found, {})

    def test_an_area_carrying_the_exclude_label_makes_no_room(self) -> None:
        found = house({"stue": {EXCLUDED}}, [heater("switch.stue", "stue")])

        self.assertEqual(found, {})

    def test_an_area_whose_only_labelled_heater_is_unavailable_makes_no_room(self) -> None:
        found = house({"stue": set()}, [heater("switch.stue", "stue", available=False)])

        self.assertEqual(found, {})

    def test_a_room_keeps_its_available_heater_when_a_second_one_is_unavailable(self) -> None:
        """The gate is on the Area having none left, never on each heater being reachable."""
        found = house(
            {"stue": set()},
            [heater("switch.stue", "stue"), heater("switch.panel", "stue", available=False)],
        )

        self.assertEqual(found["stue"].heaters, ("switch.stue",))

    def test_a_thermostat_of_this_integrations_own_is_never_a_heater(self) -> None:
        """Every room publishes a climate entity carrying the label would make it heat itself."""
        ours = Candidate("climate.stue", "stue", frozenset({HEATING}), OURS)

        self.assertEqual(house({"stue": set()}, [ours]), {})

    def test_an_entity_carrying_both_labels_stays_out(self) -> None:
        both = Candidate("switch.stue", "stue", frozenset({HEATING, EXCLUDED}), "shelly")

        self.assertEqual(house({"stue": set()}, [both]), {})


class WhatARoomReadsTests(unittest.TestCase):
    def test_a_rooms_sensors_are_the_labelled_temperature_sensors_in_its_area(self) -> None:
        found = house(
            {"stue": set()},
            [
                heater("switch.stue", "stue"),
                sensor("sensor.stue_temperatur", "stue"),
                Candidate("sensor.stue_fukt", "stue", frozenset({HEATING}), "shelly",
                          device_class="humidity"),
                Candidate("sensor.bad_temperatur", "stue", frozenset(), "shelly",
                          device_class="temperature"),
            ],
        )

        self.assertEqual(found["stue"].temperature_sensors, ("sensor.stue_temperatur",))

    def test_one_entity_per_device_so_a_two_relay_heater_is_driven_once(self) -> None:
        found = house(
            {"stue": set()},
            [
                heater("switch.stue_b", "stue", device_id="panel"),
                heater("switch.stue_a", "stue", device_id="panel"),
                heater("switch.oven", "stue", device_id="oven"),
                heater("input_boolean.prove", "stue"),
            ],
        )

        # Sorted, so which of a device's entities wins does not follow registry order.
        self.assertEqual(
            found["stue"].heaters, ("input_boolean.prove", "switch.oven", "switch.stue_a")
        )


class WhenARoomComesAndGoesTests(unittest.TestCase):
    def test_removing_the_label_from_one_heater_removes_that_room_and_leaves_the_other(
        self,
    ) -> None:
        """A room's stored state is keyed by its area id, so the room that stays is never touched."""
        labelled = [heater("switch.stue", "stue"), heater("switch.bad", "bad")]
        before = house({"stue": set(), "bad": set()}, labelled)

        after = house(
            {"stue": set(), "bad": set()},
            [Candidate("switch.stue", "stue", frozenset(), "shelly"), labelled[1]],
        )
        new, gone = changed(before, after)

        self.assertEqual((new, gone), ((), ("stue",)))
        self.assertEqual(after["bad"], before["bad"])

    def test_a_restart_with_no_add_on_connected_restores_both_rooms(self) -> None:
        """Nothing is waited for: the registries alone answer, and no room is declared anywhere."""
        registries = (
            {"stue": set(), "bad": set()},
            [heater("switch.stue", "stue"), heater("switch.bad", "bad")],
        )

        self.assertEqual(set(house(*registries)), {"stue", "bad"})
        self.assertEqual(changed(house(*registries), house(*registries)), ((), ()))


class WhatANamedSlotReplacesTests(unittest.TestCase):
    def test_a_room_sent_no_list_keeps_what_it_discovered(self) -> None:
        self.assertEqual(
            named_or_discovered(None, ["switch.stue", "switch.oven"]),
            ["switch.stue", "switch.oven"],
        )

    def test_a_named_list_is_the_whole_set_and_the_discovered_one_is_not_consulted(self) -> None:
        self.assertEqual(
            named_or_discovered(("switch.loft",), ["switch.stue", "switch.oven"]),
            ["switch.loft"],
        )

    def test_a_named_empty_list_means_no_heaters_rather_than_falling_back(self) -> None:
        self.assertEqual(named_or_discovered((), ["switch.stue"]), [])


if __name__ == "__main__":
    unittest.main()
