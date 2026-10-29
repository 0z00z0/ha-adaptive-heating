"""The six room actions and the one house action, declared once.

The table below is what the registered schema, `services.yaml` and the English strings are all
built from or checked against, so a field cannot appear in the picker without a label or reach a
handler without a bound.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

import voluptuous as vol

WARM_ROOM_BY = "warm_room_by"
HOLD_TEMPERATURE = "hold_temperature"
SET_WARMING_RATE = "set_warming_rate"
SET_REGULATION = "set_regulation"
RETURN_TO_TARGET = "return_to_target"

# The room, its thermostat and everything it has learnt, placed in another area.
MOVE_TO_AREA = "move_to_area"

# The one action with no room for a target: which labels find the rooms, as the add-on's House tab chose them.
SET_LABELS = "set_labels"

HOLDING_BEHAVIOURS = ("paced", "band")

# What a mode is worth in a room with no reading at all, where another room takes a temperature.
SWITCHED = ("on", "off")

# Whether the room's frost temperature holds. Off leaves only the device's own minimum.
FROST_LIMIT = ("on", "off")


def as_datetime(value: object) -> datetime | time:
    """A full date and time, or a clock time alone, which the handler reads as the next occurrence.

    A time alone is how a person writes a deadline by hand, and refusing it named neither the field
    nor the reason. The picker still supplies a full date and time, and that is unchanged.
    """
    if isinstance(value, (datetime, time)):
        return value

    if isinstance(value, str):
        for reader in (datetime.fromisoformat, time.fromisoformat):
            try:
                return reader(value)
            except ValueError:
                continue

    raise vol.Invalid("wanted a time like 06:00, or a full date and time")


def as_duration(value: object) -> timedelta:
    if isinstance(value, timedelta):
        return value
    if isinstance(value, (int, float)):
        return timedelta(seconds=float(value))
    if isinstance(value, str):
        hours, minutes, seconds = (value.split(":") + ["0", "0"])[:3]
        return timedelta(hours=float(hours), minutes=float(minutes), seconds=float(seconds))
    if isinstance(value, dict):
        return timedelta(
            days=float(value.get("days", 0)),
            hours=float(value.get("hours", 0)),
            minutes=float(value.get("minutes", 0)),
            seconds=float(value.get("seconds", 0)),
        )
    raise vol.Invalid("not a duration")


def as_entity_id(value: object) -> str:
    """One entity id. Checked here, because this table imports nothing from Home Assistant."""
    if isinstance(value, str) and value.count(".") == 1 and all(value.split(".")):
        return value
    raise vol.Invalid("wanted one entity id, like switch.panel")


def as_label_id(value: object) -> str:
    """A label id, or nothing at all, which is how no include label is said."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    raise vol.Invalid("wanted a label id, like heating")


def as_area_id(value: object) -> str:
    """One area id, never empty: a room always has an area."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise vol.Invalid("wanted an area id, like living_room")


def as_entity_ids(value: object) -> list[str]:
    """A list of entity ids, or one on its own, which is how a person writes a single slot."""
    if isinstance(value, str):
        return [as_entity_id(value)]
    if isinstance(value, (list, tuple)):
        return [as_entity_id(one) for one in value]
    raise vol.Invalid("wanted entity ids, like switch.panel")


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    kind: str
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    options: tuple[str, ...] = ()

    def validator(self) -> object:
        if self.kind == "time":
            return as_datetime
        if self.kind == "duration":
            return as_duration
        if self.kind == "select":
            return vol.In(self.options)
        if self.kind == "entity":
            return as_entity_id
        if self.kind == "entities":
            return as_entity_ids
        if self.kind == "label":
            return as_label_id
        if self.kind == "area":
            return as_area_id
        return vol.All(vol.Coerce(float), vol.Range(min=self.minimum, max=self.maximum))


@dataclass(frozen=True, slots=True)
class Action:
    name: str
    fields: tuple[Field, ...] = field(default_factory=tuple)

    def fields_for_the_schema(self) -> dict[object, object]:
        """This action's own fields, for the platform's own entity-service helper to build from.

        Nothing here names a target. The helper adds `entity_id`, `device_id`, `area_id`,
        `floor_id` and `label_id` itself, and it refuses a schema it did not make.
        """
        shape: dict[object, object] = {}
        for one in self.fields:
            marker = vol.Required(one.name) if one.required else vol.Optional(one.name)
            shape[marker] = one.validator()
        return shape


ACTIONS: tuple[Action, ...] = (
    Action(
        WARM_ROOM_BY,
        (
            Field("temperature", "number", True, 2.0, 30.0, 0.5),
            Field("by_time", "time", True),
        ),
    ),
    Action(
        HOLD_TEMPERATURE,
        (
            Field("temperature", "number", True, 2.0, 30.0, 0.5),
            Field("duration", "duration", True),
        ),
    ),
    Action(
        SET_WARMING_RATE,
        (
            Field("degrees_per_hour", "number", True, 0.05, 20.0, 0.05),
            Field("measured_at_outdoor", "number", False, -50.0, 50.0, 0.5),
        ),
    ),
    Action(
        SET_REGULATION,
        (
            Field("behaviour", "select", False, options=HOLDING_BEHAVIOURS),
            Field("band", "number", False, 0.1, 1.0, 0.1),
            Field("outdoor_shift_per_degree", "number", False, 0.0, 0.1, 0.001),
            Field("cycle_length", "duration"),
            Field("full_output_below", "number", False, 0.1, 10.0, 0.1),
            Field("shortest_time_between_relay_changes", "duration"),
            Field("switched", "select", False, options=SWITCHED),
            Field("sensor_freshness", "duration"),
            Field("stuck_reading", "duration"),
            Field("sensor_spread", "number", False, 0.1, 10.0, 0.1),
            Field("freshness_record_retention", "duration"),
            # A named slot is that slot's whole set, and the registry read is not consulted for it.
            Field("heaters", "entities"),
            Field("temperature_sensors", "entities"),
            Field("window_sensor", "entity"),
            Field("power_sensor", "entity"),
            Field("neighbour", "entity"),
            Field("outdoor_sensor", "entity"),
            # What a blind thermostat room's off-phase writes, the device's own minimum where it is higher.
            Field("frost_temperature", "number", False, -20.0, 30.0, 0.5),
            Field("frost_limit", "select", False, options=FROST_LIMIT),
        ),
    ),
    Action(RETURN_TO_TARGET),
    Action(MOVE_TO_AREA, (Field("area", "area", True),)),
)

# Called with no target. Both fields are label ids; an empty include label lets every candidate through.
HOUSE_ACTIONS: tuple[Action, ...] = (
    Action(
        SET_LABELS,
        (
            Field("include_label", "label"),
            Field("exclude_label", "label"),
        ),
    ),
)

BY_NAME: dict[str, Action] = {action.name: action for action in ACTIONS}
