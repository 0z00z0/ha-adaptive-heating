"""Which rooms the house has, from what Home Assistant's registries say.

The entry reads the registries and hands the answer over as plain records, so every gate is
exercised on a bare interpreter and the rules here import nothing from the platform.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

# A thermostat is driven by its setpoint and a switch by its relay; nothing else can be held.
HEATER_DOMAINS: Final = ("switch", "input_boolean", "climate")

SENSOR_DOMAIN: Final = "sensor"
TEMPERATURE: Final = "temperature"


@dataclass(frozen=True, slots=True)
class Candidate:
    """One entity as the registries and the state machine describe it."""

    entity_id: str
    area_id: str | None
    labels: frozenset[str]
    platform: str
    hidden: bool = False
    available: bool = True
    device_id: str | None = None
    device_class: str | None = None
    # A group helper's own entity ids, read off its state. Empty for anything that is not a group.
    members: tuple[str, ...] = ()

    @property
    def domain(self) -> str:
        return self.entity_id.split(".")[0]


@dataclass(frozen=True, slots=True)
class Room:
    """A room in an area. The Area's name belongs to the Area and is free to change."""

    area_id: str
    heaters: tuple[str, ...]
    temperature_sensors: tuple[str, ...]
    # The room's own identity, which `identity.identify` fills. Empty until then.
    room_id: str = ""


def rooms(
    areas: Mapping[str, Iterable[str]],
    entities: Iterable[Candidate],
    own_platform: str,
    include_label: str | None,
    exclude_label: str,
) -> dict[str, Room]:
    """Every Area holding at least one labelled, available heater, keyed by area id.

    Both labels are ids, as the add-on's label rule resolved them. No include label lets every
    candidate through; the exclude label still wins over it.
    """
    everything = list(entities)
    by_id = {candidate.entity_id: candidate for candidate in everything}
    labelled: list[Candidate] = [
        candidate
        for candidate in everything
        if candidate.area_id is not None
        and not candidate.hidden
        # A thermostat of this integration's own is a room, never a room's heater.
        and candidate.platform != own_platform
        and (not include_label or include_label in candidate.labels)
        and exclude_label not in candidate.labels
    ]
    found: dict[str, Room] = {}
    for area_id, area_labels in areas.items():
        if exclude_label in set(area_labels):
            continue
        here = [candidate for candidate in labelled if candidate.area_id == area_id]
        heaters = _one_per_device(
            _opened(
                (
                    candidate
                    for candidate in here
                    if candidate.domain in HEATER_DOMAINS and candidate.available
                ),
                by_id,
                area_id,
                own_platform,
                exclude_label,
            )
        )
        if not heaters:
            continue
        found[area_id] = Room(
            area_id,
            heaters,
            _one_per_device(
                candidate
                for candidate in here
                if candidate.domain == SENSOR_DOMAIN
                and candidate.device_class == TEMPERATURE
            ),
        )
    return found


def _opened(
    candidates: Iterable[Candidate],
    by_id: Mapping[str, Candidate],
    area_id: str,
    own_platform: str,
    exclude_label: str,
) -> list[Candidate]:
    """A group of heaters stands for its members, each driven as a relay of its own.

    Followed through nested groups. A member must be a live heater outside this integration, carry no
    exclude label and sit in no other Area; the include label is not asked of it. The same rule as the
    add-on's resolver.
    """
    taken: dict[str, Candidate] = {}
    seen: set[str] = set()

    def open_one(candidate: Candidate) -> None:
        if candidate.entity_id in seen:
            return
        seen.add(candidate.entity_id)
        if not candidate.members:
            taken.setdefault(candidate.entity_id, candidate)
            return
        for member_id in candidate.members:
            member = by_id.get(member_id)
            if (
                member is None
                or member.domain not in HEATER_DOMAINS
                or not member.available
                or member.platform == own_platform
                or exclude_label in member.labels
                or member.area_id not in (None, area_id)
            ):
                continue
            open_one(member)

    for candidate in candidates:
        open_one(candidate)
    return list(taken.values())


def _one_per_device(candidates: Iterable[Candidate]) -> tuple[str, ...]:
    """One entity per device, the lowest entity id of each. An entity with no device stands alone."""
    # Sorted, so which of a device's entities wins does not follow registry order.
    devices: set[str] = set()
    taken: list[str] = []
    for candidate in sorted(candidates, key=lambda one: one.entity_id):
        if candidate.device_id is not None:
            if candidate.device_id in devices:
                continue
            devices.add(candidate.device_id)
        taken.append(candidate.entity_id)
    return tuple(taken)


def named_or_discovered(named: tuple[str, ...] | None, discovered: Iterable[str]) -> list[str]:
    """A slot the add-on named is that slot's whole set; the registry read stands where it named none."""
    return list(discovered) if named is None else list(named)


def changed(known: Iterable[str], now: Iterable[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Which room ids are new and which have gone, so neither reloads the entry."""
    before = set(known)
    after = set(now)
    return tuple(sorted(after - before)), tuple(sorted(before - after))
