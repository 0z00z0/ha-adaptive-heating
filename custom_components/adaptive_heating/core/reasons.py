"""Why a room is not heating, and what a meter says is wrong.

The words a person reads live in the integration's strings file: each reason is a state of the
room's own enum sensor, and each meter fault is a repairs issue. Only the sentences a refused
action answers with are written here, because an action's answer is not translated.
"""

from __future__ import annotations

from enum import StrEnum


class NotHeating(StrEnum):
    ROOM_IS_SWITCHED_OFF = "room_is_switched_off"
    WINDOW_IS_OPEN = "window_is_open"
    NO_TEMPERATURE_READING = "no_temperature_reading"
    AT_TEMPERATURE = "at_temperature"
    PACING_THE_CYCLE = "pacing_the_cycle"
    RELAY_GUARD_IS_HOLDING = "relay_guard_is_holding"

    # A room with no reading at all. The mode says off, or its heater's own dial holds whatever the
    # room is worth while the mode says on.
    THE_MODE_SAYS_OFF = "the_mode_says_off"

    # What the three actions that need a number are refused with in such a room.
    THE_ROOM_HAS_NO_READING = "the_room_has_no_reading"

    # A thermostat underneath that is unknown or unavailable. A switch has no such state of its own.
    THE_HEATER_IS_NOT_ANSWERING = "the_heater_is_not_answering"

    # What a named heater set is refused with where another room already drives one of its heaters.
    THE_HEATER_BELONGS_TO_ANOTHER_ROOM = "the_heater_belongs_to_another_room"


# Only the reasons an action is refused with. A `Refused` raised with any other reason has no
# sentence to answer under, and a test holds this table to the raise sites.
REFUSAL_WORDS: dict[NotHeating, str] = {
    NotHeating.ROOM_IS_SWITCHED_OFF: "The room is switched off.",
    NotHeating.THE_ROOM_HAS_NO_READING: "The room has no temperature reading.",
    NotHeating.THE_HEATER_BELONGS_TO_ANOTHER_ROOM: "Another room already drives that heater.",
}


class Fault(StrEnum):
    """What a power meter says is wrong. A room without one raises neither."""

    HEATER_DREW_NOTHING = "heater_drew_nothing"
    RELAY_STUCK_CLOSED = "relay_stuck_closed"


# A room over a thermostat has no relay to name, so the stuck-relay fault reads differently there.
THERMOSTAT_DREW_POWER: str = "thermostat_drew_power"


def issue_key(fault: Fault, over_a_thermostat: bool) -> str:
    """Which words the repairs issue carries, by what heats the room."""
    if fault is Fault.RELAY_STUCK_CLOSED and over_a_thermostat:
        return THERMOSTAT_DREW_POWER
    return str(fault)


class Refused(Exception):
    """An action the thermostat will not take, carrying the one reason.

    A plain exception, so it stays clear of the `vol.Invalid` a field out of bounds raises. That one
    answers `invalid_format`, and a room's own answer has to be separable from it by the code alone,
    which is how the add-on tells an answer from a failure. The entity turns this into the platform's
    `ServiceValidationError` at the one point every action passes through, which is what makes it
    answer `service_validation_error`. The sentence is the same either way.
    """

    def __init__(self, reason: NotHeating) -> None:
        super().__init__(REFUSAL_WORDS[reason])
        self.reason = reason
