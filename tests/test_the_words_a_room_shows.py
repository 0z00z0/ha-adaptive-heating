"""The words a person meets for a room's verdict and a meter's fault.

Both live in the integration's strings files, so a key with no text reaches a household as the key
itself. The guard is the enum, not a count: a reason added to the loop fails this file until its
words are written.
"""

from __future__ import annotations

import ast
import json
import unittest

from _core import COMPONENT
from core import card
from core.reasons import REFUSAL_WORDS, Fault, NotHeating, issue_key

STRINGS = ("strings.json", "translations/en.json")


def words(name: str) -> dict:
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def states(name: str) -> dict[str, str]:
    return words(name)["entity"]["sensor"]["not_heating_because"]["state"]


class TheReasonAsASensorsStateTests(unittest.TestCase):
    def test_every_reason_has_words_in_both_strings_files(self) -> None:
        for name in STRINGS:
            written = states(name)
            for reason in NotHeating:
                self.assertIn(str(reason), written, f"{name}: {reason}")
                self.assertTrue(written[str(reason)].strip(), f"{name}: {reason}")

    def test_the_states_name_nothing_the_loop_cannot_reach(self) -> None:
        every = {str(reason) for reason in NotHeating}
        for name in STRINGS:
            self.assertEqual(set(states(name)) - every, set(), name)

    def test_the_sensor_itself_carries_a_name_and_the_enum_class(self) -> None:
        for name in STRINGS:
            self.assertEqual(
                words(name)["entity"]["sensor"]["not_heating_because"]["name"], "Reason", name
            )

    def test_every_word_on_a_card_is_a_few_words_and_not_a_sentence(self) -> None:
        for name in STRINGS:
            for reason, text in states(name).items():
                self.assertLess(len(text), 30, f"{name}: {reason}")
                self.assertNotIn(".", text, f"{name}: {reason}")
                self.assertLessEqual(len(text.split()), 4, f"{name}: {reason}")

    def test_the_card_no_longer_publishes_the_reason(self) -> None:
        """Dropped deliberately: the sensor is where a person and an automation read it."""
        self.assertNotIn("not_heating_because", card.EVERY_ATTRIBUTE)


class TheMeterFaultAsARepairsIssueTests(unittest.TestCase):
    def test_each_fault_has_an_issue_entry_naming_the_room(self) -> None:
        for name in STRINGS:
            raised = words(name)["issues"]
            for key in ("heater_drew_nothing", "relay_stuck_closed", "thermostat_drew_power"):
                self.assertIn(key, raised, f"{name}: {key}")
                self.assertTrue(raised[key]["title"].strip(), f"{name}: {key}")
                self.assertIn("{room}", raised[key]["description"], f"{name}: {key}")

    def test_the_issue_a_thermostat_room_raises_names_no_relay(self) -> None:
        """The defect this step closes: a room over a thermostat has no relay to be stuck."""
        key = issue_key(Fault.RELAY_STUCK_CLOSED, over_a_thermostat=True)

        self.assertEqual(key, "thermostat_drew_power")
        for name in STRINGS:
            raised = words(name)["issues"][key]
            self.assertNotIn("relay", (raised["title"] + raised["description"]).lower(), name)

    def test_a_room_over_a_relay_still_names_the_relay(self) -> None:
        key = issue_key(Fault.RELAY_STUCK_CLOSED, over_a_thermostat=False)

        self.assertEqual(key, "relay_stuck_closed")
        for name in STRINGS:
            raised = words(name)["issues"][key]
            self.assertIn("relay", (raised["title"] + raised["description"]).lower(), name)

    def test_a_heater_drawing_nothing_reads_the_same_either_way(self) -> None:
        for over_a_thermostat in (True, False):
            self.assertEqual(
                issue_key(Fault.HEATER_DREW_NOTHING, over_a_thermostat), "heater_drew_nothing"
            )

    def test_the_issue_titles_are_short(self) -> None:
        for name in STRINGS:
            for key, raised in words(name)["issues"].items():
                self.assertLess(len(raised["title"]), 30, f"{name}: {key}")


class TheSentenceARefusedActionAnswersWithTests(unittest.TestCase):
    """An action's answer is not translated, so those sentences stay in the Python."""

    @staticmethod
    def raised() -> set[str]:
        """Every reason a `raise Refused(NotHeating.X)` names, anywhere in the integration."""
        named: set[str] = set()
        for source in COMPONENT.rglob("*.py"):
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                    continue
                called = node.exc.func
                if not isinstance(called, ast.Name) or called.id != "Refused":
                    continue
                for argument in node.exc.args:
                    if isinstance(argument, ast.Attribute):
                        named.add(argument.attr)
        return named

    def test_every_reason_an_action_is_refused_with_has_a_sentence(self) -> None:
        held = {reason.name for reason in REFUSAL_WORDS}

        self.assertEqual(self.raised() - held, set())

    def test_the_table_carries_nothing_no_action_is_refused_with(self) -> None:
        """A sentence nobody can reach is a word to keep translated for nothing."""
        held = {reason.name for reason in REFUSAL_WORDS}

        self.assertEqual(held - self.raised(), set())

    def test_each_sentence_is_short_enough_to_read_on_a_card(self) -> None:
        for reason, sentence in REFUSAL_WORDS.items():
            self.assertLess(len(sentence), 70, reason)


if __name__ == "__main__":
    unittest.main()
