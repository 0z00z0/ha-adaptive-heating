"""Which room is in which area, kept apart from the area itself.

A room's identity is `room_001`, `room_002` and on, minted once when the room is first created and
never changed or issued again. The area is an attribute of the room, as it is of any device in Home
Assistant, so a room moved to another area keeps its entity, its device, its stored state and its
history.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

# What a move is refused with. An action's answer is not translated, as for the room's own refusals.
ANOTHER_ROOM_IS_THERE = "Another room is already in that area."
NO_SUCH_AREA = "Home Assistant has no area with that id."
A_ROOM_HAS_AN_AREA = "A room always has an area."


class DeviceMove(StrEnum):
    """What a room does once its device has been placed in an area by hand."""

    NOTHING = "nothing"
    FOLLOW = "follow"
    PUT_BACK = "put_back"


@dataclass(frozen=True, slots=True)
class RoomIdentity:
    """Everything keyed on the room rather than the area, so none of it moves with the area."""

    room_id: str

    @property
    def unique_id(self) -> str:
        return self.room_id

    @property
    def device_identifier(self) -> tuple[str, str]:
        return ("adaptive_heating", self.room_id)

    @property
    def store_key(self) -> str:
        return f"adaptive_heating.{self.room_id}"

    @property
    def reason_unique_id(self) -> str:
        return f"{self.room_id}_not_heating_because"

    def issue_id(self, fault: str) -> str:
        return f"{fault}_{self.room_id}"


def room_id(number: int) -> str:
    """Three digits at least; past 999 the number simply grows, so no earlier id is renamed."""
    return f"room_{number:03d}"


def identify(
    areas: Iterable[str],
    links: Mapping[str, str],
    highest: int,
) -> tuple[dict[str, str], dict[str, str], int]:
    """Each area holding a room, as room id to area id, the links with any new room, and the highest number issued.

    An area a room is linked to gets that room. Any other area gets a new room numbered one past
    `highest`, which only ever grows, so a removed room's id is never issued again.
    """
    linked = {area_id: room for room, area_id in links.items()}
    kept = dict(links)
    found: dict[str, str] = {}
    for area_id in sorted(areas):
        room = linked.get(area_id)
        if room is None:
            highest += 1
            room = room_id(highest)
            kept[room] = area_id
        found[room] = area_id
    return found, kept, highest


def refuse_move(
    room_id: str,
    to_area: str,
    present: Mapping[str, str],
    known_areas: Iterable[str],
) -> str | None:
    """Why a room may not move to `to_area`, or nothing. `present` is room id to area id."""
    if to_area not in set(known_areas):
        return NO_SUCH_AREA
    for other, area_id in present.items():
        if other != room_id and area_id == to_area:
            return ANOTHER_ROOM_IS_THERE
    return None


def follow_the_device(
    room_id: str,
    device_area: str | None,
    links: Mapping[str, str],
    present: Mapping[str, str],
    known_areas: Iterable[str],
) -> tuple[DeviceMove, str | None]:
    """Whether a room follows its device into `device_area`, and why not where it is put back."""
    # The link already says so: `move_to_area`, a put-back or the room placing its own device.
    if device_area == links.get(room_id):
        return DeviceMove.NOTHING, None
    refusal = (
        A_ROOM_HAS_AN_AREA
        if device_area is None
        else refuse_move(room_id, device_area, present, known_areas)
    )
    return (DeviceMove.FOLLOW, None) if refusal is None else (DeviceMove.PUT_BACK, refusal)


def moved(links: Mapping[str, str], room_id: str, to_area: str) -> dict[str, str]:
    """The links once `room_id` is in `to_area`.

    A link of a room that is not present any more, to the same area, is dropped: the area has one
    room, and the room that moved in is it.
    """
    kept = {other: area_id for other, area_id in links.items() if area_id != to_area}
    kept[room_id] = to_area
    return kept
