"""The three answers a call can get, and the code each one arrives under.

Only a running Home Assistant settles what goes on the wire, and it is not installable on every
machine, so two things stand in for it here.

The shapes are proved against the rules themselves: a room's own refusal and a field out of bounds
are separate types, which is what lets the codes differ at all. The codes are proved against a
replica of Home Assistant's ordered handler, read from `websocket_api/commands.py` at 2026.9.1 and
written out below: `ServiceNotFound` first, then `vol.Invalid`, then `ServiceValidationError`. A
replica settles the classification and never the platform, so the wire itself is settled at the
cabin.
"""

from __future__ import annotations

import ast
import json
import unittest

import voluptuous

from _core import COMPONENT, at
from core import actions as table
from core.reasons import WORDS, NotHeating, Refused
from core.sensors import SensorReading, read
from core.thermostat import RoomThermostat

try:
    from homeassistant.exceptions import (
        HomeAssistantError,
        ServiceNotFound,
        ServiceValidationError,
    )
except ImportError:
    # Home Assistant's own three, with the relationships its source gives them. `ServiceNotFound`
    # sits under `ServiceValidationError`, which is why the order below is load-bearing.
    class HomeAssistantError(Exception):  # type: ignore[no-redef]
        pass

    class ServiceValidationError(HomeAssistantError):  # type: ignore[no-redef]
        pass

    class ServiceNotFound(ServiceValidationError):  # type: ignore[no-redef]
        def __init__(self, domain: str, service: str) -> None:
            super().__init__(f"Action {domain}.{service} not found.")
            self.domain = domain
            self.service = service


NOT_FOUND = "not_found"
INVALID_FORMAT = "invalid_format"
SERVICE_VALIDATION_ERROR = "service_validation_error"
HOME_ASSISTANT_ERROR = "home_assistant_error"
A_SERVER_FAULT = "a_server_fault"


def the_code_it_answers_under(raised: Exception) -> str:
    """Home Assistant's own order, read from `websocket_api/commands.py` at 2026.9.1."""
    if isinstance(raised, ServiceNotFound):
        return NOT_FOUND
    if isinstance(raised, voluptuous.Invalid):
        return INVALID_FORMAT
    if isinstance(raised, ServiceValidationError):
        return SERVICE_VALIDATION_ERROR
    if isinstance(raised, HomeAssistantError):
        return HOME_ASSISTANT_ERROR
    return A_SERVER_FAULT


def as_the_entity_hands_it_on(refusal: Refused) -> Exception:
    """The one line `climate.py` runs on the way out, held to that file by the test below."""
    return ServiceValidationError(str(refusal))


def a_switched_off_room() -> RoomThermostat:
    thermostat = RoomThermostat("stue", ["switch.panel"])
    thermostat.set_target(18.0, at())
    thermostat.evaluate(
        at(), read([SensorReading("sensor.room", 17.0, at(), at())], at())
    )
    thermostat.switch_off(at())
    return thermostat


class WhatEachAnswerIsToldApartBy(unittest.TestCase):
    def test_a_room_s_own_refusal_answers_under_service_validation_error(self) -> None:
        with self.assertRaises(Refused) as refused:
            a_switched_off_room().warm_room_by(21.0, at(hours=4), at())

        refusal = refused.exception
        self.assertNotIsInstance(refusal, voluptuous.Invalid)
        self.assertEqual(refusal.reason, NotHeating.ROOM_IS_SWITCHED_OFF)
        self.assertEqual(
            the_code_it_answers_under(as_the_entity_hands_it_on(refusal)),
            SERVICE_VALIDATION_ERROR,
        )

    def test_a_field_outside_its_bound_answers_under_invalid_format(self) -> None:
        band = next(
            one
            for one in table.BY_NAME[table.SET_REGULATION].fields
            if one.name == "band"
        )
        with self.assertRaises(Exception) as refused:  # noqa: B017 - the shape is under test
            band.validator()(9.0)

        raised = refused.exception
        self.assertNotIsInstance(raised, Refused)
        self.assertEqual(the_code_it_answers_under(raised), INVALID_FORMAT)

    def test_an_action_nobody_registered_answers_under_not_found(self) -> None:
        domain = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))["domain"]
        absent = "an_action_this_half_never_declared"
        self.assertNotIn(absent, table.BY_NAME)
        self.assertEqual(
            the_code_it_answers_under(ServiceNotFound(domain, absent)), NOT_FOUND
        )

    def test_the_three_codes_are_three(self) -> None:
        """Separable by the code alone, with nothing reading the sentence."""
        refusal = as_the_entity_hands_it_on(Refused(NotHeating.THE_ROOM_HAS_NO_READING))
        bad_field = voluptuous.Invalid("value must be at most 1.0")
        absent = ServiceNotFound("adaptive_heating", "never_declared")

        answered = [the_code_it_answers_under(one) for one in (refusal, bad_field, absent)]
        self.assertEqual(
            answered, [SERVICE_VALIDATION_ERROR, INVALID_FORMAT, NOT_FOUND]
        )
        self.assertEqual(len(set(answered)), 3)

    def test_the_sentence_a_room_gives_reaches_the_answer_word_for_word(self) -> None:
        for reason in (NotHeating.ROOM_IS_SWITCHED_OFF, NotHeating.THE_ROOM_HAS_NO_READING):
            self.assertEqual(str(as_the_entity_hands_it_on(Refused(reason))), WORDS[reason])

        self.assertEqual(WORDS[NotHeating.ROOM_IS_SWITCHED_OFF], "The room is switched off.")
        self.assertEqual(
            WORDS[NotHeating.THE_ROOM_HAS_NO_READING],
            "The room has no temperature reading.",
        )

    def test_the_entity_turns_a_refusal_into_that_error_at_the_one_choke_point(self) -> None:
        """Every action reaches the thermostat through `_act`, and a refusal raised past it is a
        server fault with a traceback."""
        tree = ast.parse((COMPONENT / "climate.py").read_text(encoding="utf-8"))
        choke_points = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_act"
        ]
        self.assertEqual(len(choke_points), 1)

        caught = [
            handler
            for node in ast.walk(tree)
            if isinstance(node, ast.Try)
            for handler in node.handlers
            if isinstance(handler.type, ast.Name) and handler.type.id == Refused.__name__
        ]
        self.assertEqual(len(caught), 1, "a refusal is caught once, and in `_act`")
        self.assertIn(caught[0], list(ast.walk(choke_points[0])))

        thrown = [
            node.exc.func.id
            for node in ast.walk(caught[0])
            if isinstance(node, ast.Raise)
            and isinstance(node.exc, ast.Call)
            and isinstance(node.exc.func, ast.Name)
        ]
        self.assertEqual(thrown, [ServiceValidationError.__name__])


if __name__ == "__main__":
    unittest.main()
