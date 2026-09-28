"""The five actions: what each one does to the room, and what the picker is given to show."""

from __future__ import annotations

import json
import unittest
from datetime import time, timedelta

import voluptuous
import yaml

from _core import COMPONENT, at
from core import actions as table
from core.reasons import NotHeating, Refused
from core.regulation import HoldingBehaviour
from core.sensors import SensorReading, read
from core.thermostat import RoomThermostat
from core.warmup import WarmUpOutcome, next_occurrence


def room(temperature: float, minutes: float = 0.0):
    return read(
        [SensorReading("sensor.room", temperature, at(minutes=minutes), at(minutes=minutes))],
        at(minutes=minutes),
    )


class ActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.thermostat = RoomThermostat("stue", ["switch.panel"])
        self.thermostat.set_target(18.0, at())
        self.thermostat.evaluate(at(), room(17.0))

    def test_warming_the_room_by_a_time_starts_early_and_marks_the_deadline_met(self) -> None:
        self.thermostat.set_warming_rate(2.0, 0.0)
        plan = self.thermostat.warm_room_by(21.0, at(hours=6), at())

        # Four fifths of two degrees an hour is 1.6, so four degrees is planned as two and a half
        # hours rather than two: the room arrives with time to spare, never late.
        self.assertEqual(plan.starts_at, at(hours=6) - timedelta(hours=2.5))
        self.assertIsNone(plan.short_by)

        before = self.thermostat.evaluate(at(hours=1), room(17.0, 60))
        self.assertEqual(before.target, 18.0)

        during = self.thermostat.evaluate(at(hours=4), room(17.0, 240))
        self.assertEqual(during.target, 21.0)
        self.assertEqual(during.duty, 1.0)

        self.thermostat.evaluate(at(hours=6), room(21.2, 360))
        self.assertEqual(self.thermostat.last_warm_up.outcome, WarmUpOutcome.MET)
        self.assertIsNone(self.thermostat.warm_up)

    def test_a_room_that_cannot_make_its_deadline_starts_at_once_and_says_how_short(self) -> None:
        self.thermostat.set_warming_rate(1.0, 0.0)
        plan = self.thermostat.warm_room_by(25.0, at(hours=1), at())

        self.assertEqual(plan.starts_at, at())
        self.assertAlmostEqual(plan.reaches, 17.8)
        self.assertAlmostEqual(plan.short_by, 7.2)

    def test_holding_a_temperature_falls_back_to_the_target_when_it_expires(self) -> None:
        self.thermostat.hold_temperature(22.0, timedelta(hours=2), at())

        during = self.thermostat.evaluate(at(hours=1), room(19.0, 60))
        self.assertEqual(during.target, 22.0)

        after = self.thermostat.evaluate(at(hours=3), room(19.0, 180))
        self.assertEqual(after.target, 18.0)
        self.assertIsNone(self.thermostat.hold)

    def test_setting_how_fast_the_room_warms_replaces_the_hand_set_figure(self) -> None:
        self.assertFalse(self.thermostat.warming_rate.measured)
        self.thermostat.set_warming_rate(3.5, -4.0)
        self.assertEqual(self.thermostat.warming_rate.degrees_per_hour, 3.5)
        self.assertEqual(self.thermostat.warming_rate.measured_at_outdoor, -4.0)
        self.assertTrue(self.thermostat.warming_rate.measured)

    def test_setting_how_the_room_is_regulated_changes_the_loop_and_locks_a_set_band(self) -> None:
        self.thermostat.set_regulation(
            behaviour="band",
            band=0.8,
            outdoor_shift_per_degree=0.01,
            cycle_length=timedelta(minutes=10),
            full_output_below=2.0,
            shortest_time_between_relay_changes=timedelta(minutes=3),
        )
        regulation = self.thermostat.regulation
        self.assertIs(regulation.behaviour, HoldingBehaviour.BAND)
        self.assertEqual(regulation.full_output_below, 2.0)
        self.assertEqual(regulation.cycle_length, timedelta(minutes=10))
        self.assertTrue(self.thermostat.band_learning.locked)
        self.assertEqual(self.thermostat.band_learning.in_force, 0.8)

    def test_an_unknown_field_is_ignored_rather_than_refusing_the_call(self) -> None:
        self.thermostat.set_regulation(band=0.4, something_later_added=99)
        self.assertEqual(self.thermostat.band_learning.in_force, 0.4)

    def test_an_action_declares_its_own_fields_and_names_no_target(self) -> None:
        """The target fields belong to the platform's helper, and a schema carrying them is
        refused outright."""
        action = table.BY_NAME[table.SET_REGULATION]
        declared = action.fields_for_the_schema()
        named = {str(marker) for marker in declared}
        self.assertEqual(named, {one.name for one in action.fields})
        for target in ("entity_id", "device_id", "area_id", "floor_id", "label_id"):
            self.assertNotIn(target, named)

        # Each field still carries its bound, so a call out of range is refused before any handler
        # sees it.
        band = next(v for k, v in declared.items() if str(k) == "band")
        self.assertEqual(band(0.4), 0.4)
        with self.assertRaises(voluptuous.Invalid):
            band(9.0)

    def test_a_refusal_carries_the_room_s_one_reason(self) -> None:
        """Which code it then answers under is in `test_what_each_answer_is_told_apart_by`."""
        self.thermostat.switch_off(at())

        with self.assertRaises(Refused) as refused:
            self.thermostat.warm_room_by(21.0, at(hours=4), at())

        self.assertIn("switched off", str(refused.exception).lower())
        self.assertEqual(refused.exception.reason, NotHeating.ROOM_IS_SWITCHED_OFF)

    def test_a_deadline_written_as_a_time_alone_means_the_next_time_it_comes_round(self) -> None:
        """How every trial has called it by hand, and it was thrown out naming neither field nor reason."""
        self.assertEqual(self._read("06:00"), time(6, 0))
        self.assertEqual(self._read(at(hours=22).isoformat()), at(hours=22))

        # Still ahead today, and already gone today. The run starts at 08:00.
        self.assertEqual(next_occurrence(time(9, 30), at()), at(hours=1, minutes=30))
        self.assertEqual(next_occurrence(time(6, 0), at()), at(hours=22))

        # What a value nobody can read answers: the field and what was wanted, never silence.
        self.assertIn("06:00", str(self._read("half past six")))

    @staticmethod
    def _read(value: str) -> object:
        """What the field made of it, or the refusal, so a mutant reads as an assertion and not a crash."""
        try:
            return table.as_datetime(value)
        except voluptuous.Invalid as refused:
            return refused

    def test_returning_the_room_to_its_target_ends_a_warm_up_and_a_hold(self) -> None:
        self.thermostat.warm_room_by(24.0, at(hours=4), at())
        self.thermostat.hold_temperature(23.0, timedelta(hours=4), at())
        self.assertIsNotNone(self.thermostat.warm_up)

        self.thermostat.return_to_target(at(minutes=30))
        decision = self.thermostat.evaluate(at(minutes=30), room(19.0, 30))
        self.assertEqual(decision.target, 18.0)
        self.assertIsNone(self.thermostat.warm_up)
        self.assertIsNone(self.thermostat.hold)


class ActionPickerTests(unittest.TestCase):
    """A field with no label, or a label with no field, is what a stranger meets in the picker."""

    def setUp(self) -> None:
        self.declared = yaml.safe_load(
            (COMPONENT / "services.yaml").read_text(encoding="utf-8")
        )
        self.words = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))

    def test_every_action_is_declared_and_named_with_the_same_fields(self) -> None:
        self.assertEqual(set(self.declared), {action.name for action in table.ACTIONS})
        self.assertEqual(set(self.words["services"]), {action.name for action in table.ACTIONS})

        for action in table.ACTIONS:
            wanted = {one.name for one in action.fields}
            self.assertEqual(set(self.declared[action.name].get("fields", {})), wanted)
            said = self.words["services"][action.name]
            self.assertEqual(set(said.get("fields", {})), wanted)
            self.assertTrue(said["name"])
            self.assertTrue(said["description"])
            for one in wanted:
                self.assertTrue(said["fields"][one]["name"])
                self.assertTrue(said["fields"][one]["description"])

    def test_the_english_translations_are_the_words_home_assistant_loads(self) -> None:
        loaded = json.loads(
            (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
        )
        self.assertEqual(loaded, self.words)

    def test_nothing_a_person_reads_is_spelt_the_american_way(self) -> None:
        american = ("color", "behavior", "initialize", "analyze", "customize")
        for name in ("strings.json", "services.yaml"):
            text = (COMPONENT / name).read_text(encoding="utf-8").lower()
            for word in american:
                self.assertNotIn(word, text, f"{name} carries {word!r}")


if __name__ == "__main__":
    unittest.main()
