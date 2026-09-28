"""Why a room is not heating, written once.

The card, the thermostat's own attributes and the answer an action call gets all read this table,
so a person who asks two surfaces the same question gets one answer.
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


# Short by design. Anything needing explanation sits behind an icon, never in the sentence.
WORDS: dict[NotHeating, str] = {
    NotHeating.ROOM_IS_SWITCHED_OFF: "The room is switched off.",
    NotHeating.WINDOW_IS_OPEN: "A window is open.",
    NotHeating.NO_TEMPERATURE_READING: "No temperature reading.",
    NotHeating.AT_TEMPERATURE: "At temperature.",
    NotHeating.PACING_THE_CYCLE: "Pacing, heat due shortly.",
    NotHeating.RELAY_GUARD_IS_HOLDING: "Relay held, switched recently.",
    NotHeating.THE_MODE_SAYS_OFF: "Off, the mode says so.",
    NotHeating.THE_ROOM_HAS_NO_READING: "The room has no temperature reading.",
}


class Fault(StrEnum):
    """What a power meter says is wrong. A room without one raises neither."""

    HEATER_DREW_NOTHING = "heater_drew_nothing"
    RELAY_STUCK_CLOSED = "relay_stuck_closed"


# Worded as what was seen, never as a certain fault: a heater with a dial of its own draws nothing
# once that dial is satisfied, and nothing the system reads tells that from a switch turned off.
FAULT_WORDS: dict[Fault, str] = {
    Fault.HEATER_DREW_NOTHING: "Switched on, drawing nothing.",
    Fault.RELAY_STUCK_CLOSED: "Drawing power with the relay open.",
}


class Refused(Exception):
    """An action the thermostat will not take, carrying the one reason.

    A plain exception, so it stays clear of the `vol.Invalid` a field out of bounds raises. That one
    answers `invalid_format`, and a room's own answer has to be separable from it by the code alone,
    which is how the add-on tells an answer from a failure. The entity turns this into the platform's
    `ServiceValidationError` at the one point every action passes through, which is what makes it
    answer `service_validation_error`. The sentence is the same either way.
    """

    def __init__(self, reason: NotHeating) -> None:
        super().__init__(WORDS[reason])
        self.reason = reason
