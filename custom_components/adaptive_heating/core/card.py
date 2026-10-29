"""What a person meets on a room's card, whatever heats the room underneath.

Built here and nowhere else, so a room over a switch and a room over a thermostat cannot publish
different names, modes or controls without a test seeing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from .defaults import STANDARD

if TYPE_CHECKING:
    from .sensors import RoomReading
    from .thermostat import Decision, RoomThermostat

ATTR_STAGE: Final = "stage"
# The duty is what the relay was held for. The request stands beside it, because a figure the relay
# did not run cannot be fed to anything that learns.
ATTR_DUTY: Final = "duty"
ATTR_DUTY_ASKED_FOR: Final = "duty_asked_for"
ATTR_RESTING_ON: Final = "reading_rests_on"
ATTR_SENSORS_IN_THE_ROOM: Final = "sensors_in_the_room"
ATTR_SENSORS_LEFT_OUT: Final = "sensors_left_out"
ATTR_BORROWED_FROM: Final = "reading_borrowed_from"
ATTR_WARM_UP: Final = "warm_up"
ATTR_HOLD_ENDS_AT: Final = "hold_ends_at"
ATTR_BAND: Final = "band"
ATTR_WARMING_RATE: Final = "warming_rate"
ATTR_WARMING_RATE_MEASURED: Final = "warming_rate_measured"
ATTR_REPORTS_A_PROBLEM: Final = "reports_a_problem"

# What the add-on reads to find the rooms: which room this thermostat is, the area it is in now, and
# which half it belongs to.
ATTR_ROOM_ID: Final = "room_id"
ATTR_AREA_ID: Final = "area_id"
ATTR_INTEGRATION_VERSION: Final = "integration_version"
ATTR_VOCABULARY_VERSION: Final = "vocabulary_version"

# What the add-on drives a room from: whether a mode is worth a temperature here or on and off, what the
# loop read outside, and when this room's temperature was last set.
ATTR_NO_READING_AT_ALL: Final = "no_reading_at_all"
ATTR_OUTDOOR: Final = "outdoor"
ATTR_TARGET_SET_AT: Final = "target_set_at"
ATTR_PRESET_SET_AT: Final = "preset_set_at"

# What the meter says, and what the relay is doing where the guard and the duty disagree.
ATTR_POWER: Final = "power"
ATTR_HAS_A_POWER_METER: Final = "has_a_power_meter"
ATTR_FAULT: Final = "fault"
ATTR_RELAY_GUARD_IS_HOLDING: Final = "relay_guard_is_holding"
ATTR_SWITCHED: Final = "switched"

# Lighting's lamp count and lamps not responding, under heating's names, which the room event carries.
ATTR_HEATER_COUNT: Final = "heater_count"
ATTR_HEATERS_NOT_RESPONDING: Final = "heaters_not_responding"

# The lowest a thermostat underneath accepts, which a night setback is never planned below.
ATTR_THERMOSTAT_MINIMUM: Final = "thermostat_minimum"


# The platform translates the first four. Each custom name needs a text in both strings files.
PLATFORM_PRESETS: Final = ("away", "sleep", "home", "boost")
CUSTOM_PRESETS: Final = ("planned_to_arrive", "on_the_way", "temporarily_away")
PRESETS: Final = PLATFORM_PRESETS + CUSTOM_PRESETS


# Every attribute `attributes` publishes, so none of them reaches the recorder. A key added below
# and left out here is recorded for ever, and a test holds the two together.
EVERY_ATTRIBUTE: Final = frozenset(
    {
        ATTR_ROOM_ID,
        ATTR_AREA_ID,
        ATTR_INTEGRATION_VERSION,
        ATTR_VOCABULARY_VERSION,
        ATTR_STAGE,
        ATTR_DUTY,
        ATTR_DUTY_ASKED_FOR,
        ATTR_RESTING_ON,
        ATTR_SENSORS_IN_THE_ROOM,
        ATTR_SENSORS_LEFT_OUT,
        ATTR_BORROWED_FROM,
        ATTR_WARM_UP,
        ATTR_HOLD_ENDS_AT,
        ATTR_BAND,
        ATTR_WARMING_RATE,
        ATTR_WARMING_RATE_MEASURED,
        ATTR_REPORTS_A_PROBLEM,
        ATTR_NO_READING_AT_ALL,
        ATTR_SWITCHED,
        ATTR_OUTDOOR,
        ATTR_TARGET_SET_AT,
        ATTR_PRESET_SET_AT,
        ATTR_RELAY_GUARD_IS_HOLDING,
        ATTR_HAS_A_POWER_METER,
        ATTR_POWER,
        ATTR_FAULT,
        ATTR_HEATER_COUNT,
        ATTR_HEATERS_NOT_RESPONDING,
        ATTR_THERMOSTAT_MINIMUM,
    }
)


@dataclass(frozen=True, slots=True)
class Offered:
    """The modes and controls on the card. Nothing of a thermostat underneath reaches it."""

    modes: tuple[str, ...]
    # Names of Home Assistant's own climate feature flags.
    features: tuple[str, ...]
    minimum: float
    maximum: float
    step: float
    presets: tuple[str, ...] = PRESETS


def offered(thermostat: RoomThermostat) -> Offered:
    # A room with no reading has no temperature to set, so the card offers none. Home Assistant
    # itself then refuses the standard action that would set one.
    features = ("PRESET_MODE", "TURN_ON", "TURN_OFF") if thermostat.no_reading_at_all else (
        "TARGET_TEMPERATURE", "PRESET_MODE", "TURN_ON", "TURN_OFF"
    )
    return Offered(
        ("heat", "off"),
        features,
        STANDARD.minimum_temperature,
        STANDARD.maximum_temperature,
        STANDARD.temperature_step,
    )


def attributes(
    room_id: str,
    area_id: str,
    integration_version: str,
    vocabulary_version: int,
    thermostat: RoomThermostat,
    decision: Decision | None,
    reading: RoomReading,
    outdoor: float | None,
    has_a_power_meter: bool,
) -> dict[str, Any]:
    warm_up = thermostat.warm_up
    has_a_duty = decision is not None and decision.has_a_duty
    return {
        # The add-on finds its rooms by these. Nothing else in a house publishes them, so a thermostat
        # carrying them is one of this integration's and one carrying none is not. Both halves key a
        # room by its room id; the area id only says where it is now.
        ATTR_ROOM_ID: room_id,
        ATTR_AREA_ID: area_id,
        ATTR_INTEGRATION_VERSION: integration_version,
        ATTR_VOCABULARY_VERSION: vocabulary_version,
        ATTR_STAGE: None if decision is None else str(decision.stage),
        # What the relay was held for, which is the figure anything learning from a cycle reads.
        # The request stands beside it so the law can still be followed. A room over a thermostat
        # has neither and publishes none, except while blind on the relay's fallback.
        ATTR_DUTY: round(decision.delivered, 3) if has_a_duty else None,
        ATTR_DUTY_ASKED_FOR: round(decision.duty, 3) if has_a_duty else None,
        ATTR_RESTING_ON: reading.resting_on,
        ATTR_SENSORS_IN_THE_ROOM: reading.sensors_in_the_room,
        ATTR_SENSORS_LEFT_OUT: {
            verdict.sensor_id: str(verdict.excluded) for verdict in reading.left_out
        },
        ATTR_BORROWED_FROM: reading.borrowed_from,
        ATTR_WARM_UP: None if warm_up is None else warm_up.as_dict(),
        ATTR_HOLD_ENDS_AT: None if thermostat.hold is None
        else thermostat.hold.ends_at.isoformat(),
        ATTR_BAND: thermostat.band_learning.in_force,
        ATTR_WARMING_RATE: thermostat.warming_rate.degrees_per_hour,
        ATTR_WARMING_RATE_MEASURED: thermostat.warming_rate.measured,
        ATTR_REPORTS_A_PROBLEM: False if decision is None else decision.reports_a_problem,
        # Follows from how the room was set up, never from a sensor that has gone quiet: a room with
        # no sensor of its own and no neighbour to borrow from can only be switched on and off.
        ATTR_NO_READING_AT_ALL: thermostat.no_reading_at_all,
        ATTR_SWITCHED: None if thermostat.regulation.switched is None
        else str(thermostat.regulation.switched),
        ATTR_OUTDOOR: outdoor,
        ATTR_TARGET_SET_AT: None if thermostat.target_set_at is None
        else thermostat.target_set_at.isoformat(),
        ATTR_PRESET_SET_AT: None if thermostat.preset_set_at is None
        else thermostat.preset_set_at.isoformat(),
        # The duty above is what the loop asked for. Where the guard overrides it, this is what
        # the relay is actually doing.
        ATTR_RELAY_GUARD_IS_HOLDING: False if decision is None
        else decision.held_by_the_relay_guard,
        ATTR_HAS_A_POWER_METER: has_a_power_meter,
        ATTR_POWER: thermostat.power.watts,
        ATTR_FAULT: None if thermostat.power.fault is None
        else str(thermostat.power.fault),
        ATTR_HEATER_COUNT: len(thermostat.loops),
        ATTR_HEATERS_NOT_RESPONDING: None if decision is None
        else thermostat.heaters_not_answering,
        ATTR_THERMOSTAT_MINIMUM: thermostat.thermostat_minimum,
    }
