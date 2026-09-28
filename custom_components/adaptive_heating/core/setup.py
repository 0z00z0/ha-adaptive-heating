"""What the setup dialog refuses, decided without Home Assistant in the way."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def heater_already_claimed(
    heaters: Iterable[str], elsewhere: Mapping[str, Iterable[str]]
) -> tuple[str, str] | None:
    """The first heater another room already drives, and which room that is.

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
