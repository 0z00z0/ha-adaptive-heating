"""Constants the rest of the integration points at."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

# Changing this orphans every instance already set up in a house.
DOMAIN: Final = "adaptive_heating"

# What this half names alike with the add-on: room identifiers, and the shape of a temperature,
# a duration and a time. Each half states its own version and neither refuses the other over a
# difference.
VOCABULARY_VERSION: Final = 1

# The same string as manifest.json's version, which a test holds the two to. The thermostat publishes it, so
# the add-on can tell this integration's thermostats from every other one in the house and the settings page
# can state what each half is running.
INTEGRATION_VERSION: Final = "0.1.0"

PLATFORMS: Final = ["climate"]

CONF_ROOM: Final = "room"
CONF_HEATERS: Final = "heaters"
CONF_TEMPERATURE_SENSORS: Final = "temperature_sensors"
CONF_WINDOW_SENSOR: Final = "window_sensor"
CONF_OUTDOOR_SENSOR: Final = "outdoor_sensor"
CONF_NEIGHBOUR: Final = "neighbour"

# What the heater draws. A room with one gets the two faults a closed relay cannot confirm on its own,
# and a room without one is ordinary rather than misconfigured.
CONF_POWER_SENSOR: Final = "power_sensor"

STORAGE_VERSION: Final = 1

# A coalesced write beats the fifteen minutes the platform's own restore store gives.
STORAGE_WRITE_DELAY: Final = 20

# The ordinary evaluation. Switching a thermostat back on costs at most this, and never a lost
# instruction.
EVALUATION_INTERVAL: Final = timedelta(seconds=30)

ATTR_REASON: Final = "not_heating_because"
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

# What the add-on reads to find the rooms: which room this thermostat is, and which half it belongs to.
ATTR_ROOM: Final = "room"
ATTR_INTEGRATION_VERSION: Final = "integration_version"
ATTR_VOCABULARY_VERSION: Final = "vocabulary_version"

# What the add-on drives a room from: whether a mode is worth a temperature here or on and off, what the
# loop read outside, and when this room's temperature was last set.
ATTR_NO_READING_AT_ALL: Final = "no_reading_at_all"
ATTR_OUTDOOR: Final = "outdoor"
ATTR_TARGET_SET_AT: Final = "target_set_at"

# What the meter says, and what the relay is doing where the guard and the duty disagree.
ATTR_POWER: Final = "power"
ATTR_HAS_A_POWER_METER: Final = "has_a_power_meter"
ATTR_FAULT: Final = "fault"
ATTR_RELAY_GUARD_IS_HOLDING: Final = "relay_guard_is_holding"
ATTR_SWITCHED: Final = "switched"
