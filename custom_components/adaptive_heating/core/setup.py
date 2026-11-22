"""What a named heater set is refused for, decided without Home Assistant in the way."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def heater_already_claimed(
    heaters: Iterable[str], elsewhere: Mapping[str, Iterable[str]]
) -> tuple[str, str] | None:
    """The first heater another room already drives, and which room that is.

    The rooms it is run over are the discovered ones, keyed by area id, each with the heaters it
    actually drives.

    Two rooms over one relay run two loops, each counting only its own changes, so the shortest
    time between relay changes stops protecting anything. Measured at 384 commands a day against
    192, with 96 of 191 gaps inside the guard and the shortest at nothing at all.
    """
    taken = {
        heater: room for room, its_heaters in elsewhere.items() for heater in its_heaters
    }
    for heater in heaters:
        room = taken.get(heater)
        if room is not None:
            return heater, room
    return None


def without_an_area(
    picked: Iterable[str], area_of: Mapping[str, str | None]
) -> list[str]:
    """The picked entities that sit in no area, their own or their device's, so make no room."""
    return [entity_id for entity_id in picked if not area_of.get(entity_id)]


def labels_to_write(
    current: Mapping[str, Iterable[str]],
    label: str,
    picked: Iterable[str],
    unticked: Iterable[str] = (),
) -> dict[str, set[str]]:
    """Each entity's whole label set after the picker, for the entities whose set changes.

    Every other label an entity carries stays. Only an entity the picker showed ticked and is now
    unticked loses the label.
    """
    written: dict[str, set[str]] = {}
    for entity_id in picked:
        before = set(current.get(entity_id, ()))
        if label not in before:
            written[entity_id] = before | {label}
    for entity_id in unticked:
        before = set(current.get(entity_id, ()))
        if label in before and entity_id not in written:
            written[entity_id] = before - {label}
    return written
