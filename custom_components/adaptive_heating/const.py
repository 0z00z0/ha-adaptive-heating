"""Constants the rest of the integration points at."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from .core.card import (  # noqa: F401 - the names live with the card
    ATTR_BAND,
    ATTR_BORROWED_FROM,
    ATTR_DUTY,
    ATTR_DUTY_ASKED_FOR,
    ATTR_FAULT,
    ATTR_HAS_A_POWER_METER,
    ATTR_HOLD_ENDS_AT,
    ATTR_INTEGRATION_VERSION,
    ATTR_NO_READING_AT_ALL,
    ATTR_OUTDOOR,
    ATTR_POWER,
    ATTR_RELAY_GUARD_IS_HOLDING,
    ATTR_REPORTS_A_PROBLEM,
    ATTR_RESTING_ON,
    ATTR_ROOM_ID,
    ATTR_AREA_ID,
    ATTR_SENSORS_IN_THE_ROOM,
    ATTR_SENSORS_LEFT_OUT,
    ATTR_STAGE,
    ATTR_SWITCHED,
    ATTR_TARGET_SET_AT,
    ATTR_VOCABULARY_VERSION,
    ATTR_WARMING_RATE,
    ATTR_WARMING_RATE_MEASURED,
    ATTR_WARM_UP,
)

# Changing this orphans every instance already set up in a house.
DOMAIN: Final = "adaptive_heating"

# What this half names alike with the add-on: room identifiers, and the shape of a temperature,
# a duration and a time. Each half states its own version and neither refuses the other over a
# difference.
VOCABULARY_VERSION: Final = 2

# The same string as manifest.json's version, which a test holds the two to. The thermostat publishes it, so
# the add-on can tell this integration's thermostats from every other one in the house and the settings page
# can state what each half is running.
INTEGRATION_VERSION: Final = "0.1.0"

PLATFORMS: Final = ["climate", "sensor"]

# Both are matched against a label's id and never its name. Home Assistant slugifies the name a
# person types into the id, so a label named "Heating" arrives here as "heating".

# What puts a room on both halves until the add-on says otherwise: an Area holding a heater carrying
# this label. A room's temperature sensors carry the same one. The House tab's choice replaces both
# through the set_labels action.
HEATING_LABEL: Final = "heating"

# The label the lighting engine honours too, so a household running both meets one behaviour.
EXCLUDE_LABEL: Final = "adaptive_exclude"

STORAGE_VERSION: Final = 1

# Where the labels the add-on last sent are kept, house-wide and apart from every room's own store.
LABELS_STORAGE_KEY: Final = f"{DOMAIN}.labels"

# Which area each room is in, keyed by room id, and the highest room number ever issued. The hyphen keeps it
# apart from a room's own store, whose key ends in a room id and so never carries one.
ROOM_AREAS_STORAGE_KEY: Final = f"{DOMAIN}.room-areas"

# A coalesced write beats the fifteen minutes the platform's own restore store gives.
STORAGE_WRITE_DELAY: Final = 20

# The ordinary evaluation. Switching a thermostat back on costs at most this, and never a lost
# instruction.
EVALUATION_INTERVAL: Final = timedelta(seconds=30)
