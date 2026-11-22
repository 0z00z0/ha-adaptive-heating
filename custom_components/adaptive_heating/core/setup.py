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


def labels_after_the_call(
    stored: Mapping[str, str], sent: Mapping[str, str], default_include: str, default_exclude: str
) -> dict[str, str]:
    """Both label ids after a set_labels call.

    An add-on with no label picked sends no include label, and the one the first setup chose stays.
    """
    if "include_label" in sent:
        include = sent["include_label"]
    else:
        include = stored.get("include_label", default_include)
    exclude = sent.get("exclude_label") or default_exclude
    return {"include_label": include, "exclude_label": exclude}


def label_the_setup_offers(
    stored: Mapping[str, str], existing: Iterable[str], default: str
) -> tuple[str | None, bool]:
    """The label id the first setup starts from, and whether it may be changed there.

    A label the add-on already sent is its to change, so the setup shows it and offers no choice.
    """
    if stored.get("include_label"):
        return stored["include_label"], False
    return (default if default in set(existing) else None), True


def every_heater(
    candidates: Iterable[tuple[str, str, str | None, str | None]],
    heater_domains: Iterable[str],
    own_platform: str,
) -> list[str]:
    """Every heater the "start from every heater" choice ticks.

    Each candidate is (entity id, domain, platform, area id).

    An entity with no area makes no room, and this integration's own thermostats are never heaters.
    """
    domains = set(heater_domains)
    return sorted(
        entity_id
        for entity_id, domain, platform, area in candidates
        if domain in domains and platform != own_platform and area
    )
