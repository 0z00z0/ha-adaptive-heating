"""The things only a running Home Assistant can settle.

- Not one of the five actions was registered. Home Assistant refused the first schema and the
  raise took every later registration with it, leaving a line in the log and nothing else. Asking
  the registry is the only way to catch that.
- A sensor dead for a year was believed, because the integration timed the reading by when it
  first noticed it. Only a real state carries the times that settle it.
- Which rooms the house has comes from the area, entity and label registries. The rules behind each
  gate are settled in `test_rooms_from_the_registries`; what only a running one settles is that the
  registries answer the way the rules are fed, that a room appears and leaves without the entry
  reloading, and that the room which stays keeps its stored state.
- A named slot replaces what was discovered, and a heater another room drives is refused.
- A mode is a preset on the room's card: the platform lists and reports it, a card choice survives
  three evaluation intervals, nothing writes the house's status selector, and the custom names
  translate.
- Why a room is not heating is the state of its own enum sensor, and its words come out of the
  strings file. Only a running core resolves a translation key.
- A meter fault is a repairs issue. Only the issue registry says whether one was raised, which
  words it carries and whether it went when the fault cleared.
- A deadline written as a time alone lands on the right hour on the night the clock moves. The
  core helper that settles it is not importable without Home Assistant.

This file skips itself where Home Assistant is not installed, which is the ordinary case.
"""

from __future__ import annotations

import unittest

try:
    # Running the rules needs none of these. `unittest.SkipTest` is what both runners honour at
    # module level; `pytest.importorskip` reads as an error under plain unittest.
    import pytest
    import pytest_homeassistant_custom_component  # noqa: F401
except ImportError as missing:
    raise unittest.SkipTest(str(missing)) from missing

from datetime import datetime  # noqa: E402

import voluptuous  # noqa: E402
from homeassistant.components.climate import ClimateEntityFeature  # noqa: E402
from homeassistant.components.climate.const import (  # noqa: E402
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_HOME,
    PRESET_SLEEP,
)
from homeassistant.const import ATTR_TEMPERATURE  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.exceptions import ServiceValidationError  # noqa: E402
from homeassistant.helpers import area_registry as ar  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from homeassistant.helpers import issue_registry as ir  # noqa: E402
from homeassistant.helpers import label_registry as lr  # noqa: E402
from homeassistant.helpers.translation import async_get_translations  # noqa: E402
from homeassistant.setup import async_setup_component  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.adaptive_heating.const import (  # noqa: E402
    ATTR_BAND,
    ATTR_RESTING_ON,
    ATTR_AREA_ID,
    DOMAIN,
    EVALUATION_INTERVAL,
    EXCLUDE_LABEL,
    HEATING_LABEL,
)
from custom_components.adaptive_heating.core import actions as table  # noqa: E402
from custom_components.adaptive_heating.core.reasons import NotHeating  # noqa: E402


def an_area(hass: HomeAssistant, name: str, labels: set[str] | None = None) -> str:
    """One Area, and its id, which is the only thing a room is ever keyed on."""
    area = ar.async_get(hass).async_create(name)
    if labels:
        ar.async_get(hass).async_update(area.id, labels=labels)
    return area.id


def a_heater(
    hass: HomeAssistant,
    area_id: str,
    object_id: str,
    state: str = "off",
    labels: set[str] | None = None,
    hidden: bool = False,
) -> str:
    registry = er.async_get(hass)
    known = registry.async_get_or_create(
        "switch",
        "shelly",
        object_id,
        suggested_object_id=object_id,
        labels={HEATING_LABEL} if labels is None else labels,
    )
    registry.async_update_entity(
        known.entity_id,
        area_id=area_id,
        hidden_by=er.RegistryEntryHider.USER if hidden else None,
    )
    hass.states.async_set(known.entity_id, state)
    return known.entity_id


def a_temperature_sensor(hass: HomeAssistant, area_id: str, object_id: str, value: str) -> str:
    registry = er.async_get(hass)
    known = registry.async_get_or_create(
        "sensor",
        "shelly",
        object_id,
        suggested_object_id=object_id,
        labels={HEATING_LABEL},
        original_device_class="temperature",
    )
    registry.async_update_entity(known.entity_id, area_id=area_id)
    hass.states.async_set(known.entity_id, value, {"device_class": "temperature"})
    return known.entity_id


async def the_house(hass: HomeAssistant) -> MockConfigEntry:
    """One entry for the house. Nothing in it names a room."""
    entry = MockConfigEntry(domain=DOMAIN, title="Adaptive Heating", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def the_reason(hass: HomeAssistant, area_id: str) -> str | None:
    """One room's reason sensor, found by its unique id and never by a name."""
    found = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{the_room_id(hass, area_id)}_not_heating_because"
    )
    return None if found is None else hass.states.get(found).state


def the_room(hass: HomeAssistant, area_id: str) -> str | None:
    """The entity id of the thermostat standing for one Area, or nothing where it has no room."""
    for state in hass.states.async_all("climate"):
        if state.attributes.get(ATTR_AREA_ID) == area_id:
            return state.entity_id
    return None


def the_room_id(hass: HomeAssistant, area_id: str) -> str:
    """The room id the card in one Area publishes."""
    return hass.states.get(the_room(hass, area_id)).attributes["room_id"]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_every_one_of_the_six_room_actions_reaches_the_registry(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    for action in table.ACTIONS:
        assert hass.services.has_service(DOMAIN, action.name), action.name


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_the_actions_exist_before_any_room_does(hass: HomeAssistant) -> None:
    # Declared from the integration's own setup, so an automation naming one is validated even
    # where no room loads at all.
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, table.HOLD_TEMPERATURE)
    assert hass.states.async_all("climate") == []


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_two_areas_with_a_labelled_heater_create_two_rooms(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    bad = an_area(hass, "Bad")
    a_heater(hass, stue, "stue_panel")
    a_heater(hass, bad, "bad_panel")
    await the_house(hass)

    assert the_room(hass, stue) is not None
    assert the_room(hass, bad) is not None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_hidden_labelled_heater_creates_no_room(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    loft = an_area(hass, "Loft")
    a_heater(hass, loft, "loft_panel", hidden=True)
    await the_house(hass)

    assert the_room(hass, loft) is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_an_area_carrying_the_exclude_label_creates_no_room(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    lr.async_get(hass).async_create(EXCLUDE_LABEL)
    garasje = an_area(hass, "Garasje", {EXCLUDE_LABEL})
    a_heater(hass, garasje, "garasje_panel")
    await the_house(hass)

    assert the_room(hass, garasje) is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_an_area_whose_only_heater_is_unavailable_creates_no_room(
    hass: HomeAssistant,
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    bod = an_area(hass, "Bod")
    a_heater(hass, bod, "bod_panel", state="unavailable")
    await the_house(hass)

    assert the_room(hass, bod) is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_removing_the_label_removes_that_room_and_keeps_the_others_stored_state(
    hass: HomeAssistant,
) -> None:
    """The entry is never reloaded, so the room that stays keeps everything it was holding."""
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    bad = an_area(hass, "Bad")
    heater = a_heater(hass, stue, "stue_panel")
    a_heater(hass, bad, "bad_panel")
    a_temperature_sensor(hass, bad, "bad_temperatur", "19.0")
    await the_house(hass)

    staying = the_room(hass, bad)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": staying, ATTR_TEMPERATURE: 22.5}, blocking=True
    )

    er.async_get(hass).async_update_entity(heater, labels=set())
    await hass.async_block_till_done()

    assert the_room(hass, stue) is None
    assert hass.states.get(staying).attributes["temperature"] == 22.5


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_restart_with_no_add_on_connected_restores_both_rooms(
    hass: HomeAssistant,
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    bad = an_area(hass, "Bad")
    a_heater(hass, stue, "stue_panel")
    a_heater(hass, bad, "bad_panel")
    a_temperature_sensor(hass, stue, "stue_temperatur", "19.0")
    a_temperature_sensor(hass, bad, "bad_temperatur", "19.0")
    entry = await the_house(hass)

    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": the_room(hass, stue), ATTR_TEMPERATURE: 21.5},
        blocking=True,
    )

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert the_room(hass, bad) is not None
    assert hass.states.get(the_room(hass, stue)).attributes["temperature"] == 21.5


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_named_heater_is_driven_alone_and_a_room_sent_none_keeps_what_it_found(
    hass: HomeAssistant,
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    bad = an_area(hass, "Bad")
    discovered = a_heater(hass, stue, "stue_panel")
    a_heater(hass, bad, "bad_panel")
    unlabelled = a_heater(hass, stue, "stue_loft", labels=set())
    a_temperature_sensor(hass, stue, "stue_temperatur", "15.0")
    await the_house(hass)

    room = the_room(hass, stue)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": room, ATTR_TEMPERATURE: 22.0}, blocking=True
    )
    assert hass.states.get(discovered).state == "on"

    await hass.services.async_call(
        DOMAIN, table.SET_REGULATION, {"entity_id": room, "heaters": [unlabelled]}, blocking=True
    )

    assert hass.states.get(unlabelled).state == "on"
    # The room sent no list keeps what it discovered, and the one that was named drops it.
    assert hass.states.get(the_room(hass, bad)) is not None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_named_window_sensor_makes_the_room_read_it(
    hass: HomeAssistant, freezer
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    a_heater(hass, stue, "stue_panel")
    a_temperature_sensor(hass, stue, "stue_temperatur", "15.0")
    await the_house(hass)
    room = the_room(hass, stue)

    hass.states.async_set("binary_sensor.stue_vindu", "on")
    await hass.services.async_call(
        DOMAIN,
        table.SET_REGULATION,
        {"entity_id": room, "window_sensor": "binary_sensor.stue_vindu"},
        blocking=True,
    )

    # The window has to stay open for the settling delay before it stops the room.
    freezer.tick(300)
    await hass.services.async_call(
        DOMAIN, table.RETURN_TO_TARGET, {"entity_id": room}, blocking=True
    )

    assert the_reason(hass, stue) == "window_is_open"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_heater_another_room_drives_is_refused(hass: HomeAssistant) -> None:
    """Two loops over one relay send 384 commands a day against 192, defeating the guard."""
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    bad = an_area(hass, "Bad")
    a_heater(hass, stue, "stue_panel")
    theirs = a_heater(hass, bad, "bad_panel")
    await the_house(hass)

    with pytest.raises(ServiceValidationError) as refused:
        await hass.services.async_call(
            DOMAIN,
            table.SET_REGULATION,
            {"entity_id": the_room(hass, stue), "heaters": [theirs]},
            blocking=True,
        )

    assert "another room" in str(refused.value).lower()


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_field_this_half_does_not_know_is_dropped_rather_than_refusing_the_call(
    hass: HomeAssistant,
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    a_heater(hass, stue, "stue_panel")
    await the_house(hass)

    # What a newer add-on sends an older integration. The fields it does know still take effect.
    await hass.services.async_call(
        DOMAIN,
        table.SET_REGULATION,
        {"entity_id": the_room(hass, stue), "band": 0.4, "something_later_added": 99},
        blocking=True,
    )
    assert hass.states.get(the_room(hass, stue)).attributes[ATTR_BAND] == 0.4


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_field_outside_its_bound_never_reaches_the_thermostat(
    hass: HomeAssistant,
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    a_heater(hass, stue, "stue_panel")
    await the_house(hass)
    room = the_room(hass, stue)
    before = hass.states.get(room).attributes[ATTR_BAND]

    # A `vol.Invalid` is what answers `invalid_format` over the websocket, and it is the shape a
    # room's own refusal has to stay clear of.
    with pytest.raises(voluptuous.Invalid):
        await hass.services.async_call(
            DOMAIN, table.SET_REGULATION, {"entity_id": room, "band": 9.0}, blocking=True
        )
    assert hass.states.get(room).attributes[ATTR_BAND] == before


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_room_s_own_refusal_leaves_the_handler_as_a_service_validation_error(
    hass: HomeAssistant,
) -> None:
    """The one shape that answers `service_validation_error`, which is the add-on's marker for an
    answer the room itself gave."""
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    a_heater(hass, stue, "stue_panel")
    a_temperature_sensor(hass, stue, "stue_temperatur", "19.0")
    await the_house(hass)
    room = the_room(hass, stue)

    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": room, "hvac_mode": "off"}, blocking=True
    )

    with pytest.raises(ServiceValidationError) as refused:
        await hass.services.async_call(
            DOMAIN,
            table.HOLD_TEMPERATURE,
            {"entity_id": room, "temperature": 22.0, "duration": {"hours": 1}},
            blocking=True,
        )

    assert not isinstance(refused.value, voluptuous.Invalid)
    assert str(refused.value) == "The room is switched off."


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_call_naming_no_room_is_refused(hass: HomeAssistant) -> None:
    # The target fields belong to Home Assistant's own builder, and it is that builder which
    # insists on at least one of them.
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    a_heater(hass, stue, "stue_panel")
    await the_house(hass)

    with pytest.raises(Exception):  # noqa: B017 - the platform's own refusal
        await hass.services.async_call(DOMAIN, table.RETURN_TO_TARGET, {}, blocking=True)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_sensor_dead_for_a_year_does_not_take_the_healthy_one_down_with_it(
    hass: HomeAssistant, freezer
) -> None:
    """The cabin's own case: 10.7 from 2024 beside 18.6 from today, 7.9 degrees apart."""
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    a_heater(hass, stue, "stue_panel")

    freezer.move_to("2025-09-24 12:00:00+00:00")
    a_temperature_sensor(hass, stue, "oomi", "10.7")

    freezer.move_to("2026-09-24 12:00:00+00:00")
    a_temperature_sensor(hass, stue, "shelly", "18.6")
    await the_house(hass)

    state = hass.states.get(the_room(hass, stue))
    assert state.attributes["current_temperature"] == 18.6
    assert state.attributes[ATTR_RESTING_ON] == 1


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_second_entry_for_the_house_is_refused(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await the_house(hass)

    started = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    assert started["type"] == "abort"
    assert started["reason"] == "single_instance_allowed"


async def a_room_with_a_card(hass: HomeAssistant) -> str:
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    a_heater(hass, stue, "stue_panel")
    a_temperature_sensor(hass, stue, "stue_temperatur", "19.0")
    await the_house(hass)
    return the_room(hass, stue)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_the_card_lists_seven_presets_and_reports_a_custom_one_set_on_it(
    hass: HomeAssistant,
) -> None:
    room = await a_room_with_a_card(hass)

    state = hass.states.get(room)
    assert state.attributes["preset_modes"][:4] == [
        PRESET_AWAY,
        PRESET_SLEEP,
        PRESET_HOME,
        PRESET_BOOST,
    ]
    assert len(state.attributes["preset_modes"]) == 7
    assert state.attributes["supported_features"] & ClimateEntityFeature.PRESET_MODE
    assert state.attributes["preset_mode"] is None

    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": room, "preset_mode": "on_the_way"},
        blocking=True,
    )

    assert hass.states.get(room).attributes["preset_mode"] == "on_the_way"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_preset_set_on_the_card_is_still_reported_after_three_evaluation_intervals(
    hass: HomeAssistant,
) -> None:
    room = await a_room_with_a_card(hass)
    await hass.services.async_call(
        "climate", "set_preset_mode", {"entity_id": room, "preset_mode": "boost"}, blocking=True
    )

    for passed in range(1, 4):
        async_fire_time_changed(hass, dt_util.utcnow() + passed * EVALUATION_INTERVAL)
        await hass.async_block_till_done()

    assert hass.states.get(room).attributes["preset_mode"] == "boost"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_setting_a_preset_leaves_the_houses_status_selector_untouched(
    hass: HomeAssistant,
) -> None:
    hass.states.async_set("input_select.house_status", "home")
    hass.states.async_set("select.house_status", "home")
    input_select_calls = async_mock_service(hass, "input_select", "select_option")
    select_calls = async_mock_service(hass, "select", "select_option")
    room = await a_room_with_a_card(hass)

    await hass.services.async_call(
        "climate", "set_preset_mode", {"entity_id": room, "preset_mode": "sleep"}, blocking=True
    )
    async_fire_time_changed(hass, dt_util.utcnow() + EVALUATION_INTERVAL)
    await hass.async_block_till_done()

    assert input_select_calls == []
    assert select_calls == []
    assert hass.states.get("input_select.house_status").state == "home"
    assert hass.states.get("select.house_status").state == "home"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_name_outside_the_list_is_refused_by_the_platform(hass: HomeAssistant) -> None:
    room = await a_room_with_a_card(hass)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "climate", "set_preset_mode", {"entity_id": room, "preset_mode": "eco"}, blocking=True
        )


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_the_core_loads_the_three_custom_names_from_the_strings(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    found = await async_get_translations(hass, "en", "entity", [DOMAIN])

    for key in ("planned_to_arrive", "on_the_way", "temporarily_away"):
        written = (
            f"component.{DOMAIN}.entity.climate.room.state_attributes.preset_mode.state.{key}"
        )
        assert found.get(written), written


async def a_room_with_a_meter(hass: HomeAssistant) -> tuple[str, str, str]:
    """One room over a relay, its meter named, and the area id it is keyed on."""
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    a_heater(hass, stue, "stue_panel")
    a_temperature_sensor(hass, stue, "stue_temperatur", "19.0")
    await the_house(hass)
    room = the_room(hass, stue)
    hass.states.async_set("sensor.stue_effekt", "0.0", {"device_class": "power"})
    await hass.services.async_call(
        DOMAIN,
        table.SET_REGULATION,
        {"entity_id": room, "power_sensor": "sensor.stue_effekt"},
        blocking=True,
    )
    return stue, room, "sensor.stue_effekt"


async def pass_the_window(hass: HomeAssistant, freezer, minutes: int) -> None:
    freezer.tick(minutes * 60)
    async_fire_time_changed(hass, dt_util.utcnow() + EVALUATION_INTERVAL)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_the_reason_a_room_is_not_heating_is_its_own_sensors_state(
    hass: HomeAssistant,
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    a_heater(hass, stue, "stue_panel")
    a_temperature_sensor(hass, stue, "stue_temperatur", "19.0")
    await the_house(hass)

    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": the_room(hass, stue), "hvac_mode": "off"},
        blocking=True,
    )

    assert the_reason(hass, stue) == "room_is_switched_off"
    # The card carries none of it; the add-on's Rooms tab reads the sensor instead.
    assert "not_heating_because" not in hass.states.get(the_room(hass, stue)).attributes


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_the_core_loads_every_reason_s_words_from_the_strings(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    found = await async_get_translations(hass, "en", "entity", [DOMAIN])

    for reason in NotHeating:
        written = f"component.{DOMAIN}.entity.sensor.not_heating_because.state.{reason}"
        assert found.get(written), written


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_stuck_relay_raises_an_issue_and_clearing_it_takes_the_issue_away(
    hass: HomeAssistant, freezer
) -> None:
    stue, room, meter = await a_room_with_a_meter(hass)
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": room, "hvac_mode": "off"}, blocking=True
    )

    hass.states.async_set(meter, "615.0", {"device_class": "power"})
    await hass.async_block_till_done()
    await pass_the_window(hass, freezer, 16)

    issue = f"relay_stuck_closed_{the_room_id(hass, stue)}"
    raised = ir.async_get(hass).async_get_issue(DOMAIN, issue)
    assert raised is not None
    assert raised.severity is ir.IssueSeverity.WARNING
    assert raised.is_fixable is False
    assert raised.translation_key == "relay_stuck_closed"

    hass.states.async_set(meter, "0.0", {"device_class": "power"})
    await hass.async_block_till_done()
    await pass_the_window(hass, freezer, 1)

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue) is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_the_issue_a_thermostat_room_raises_carries_the_words_that_name_no_relay(
    hass: HomeAssistant, freezer
) -> None:
    """The defect this closes: a room driven through a thermostat has no relay to be stuck."""
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    a_heater(hass, stue, "stue_panel")
    a_temperature_sensor(hass, stue, "stue_temperatur", "19.0")
    await the_house(hass)
    room = the_room(hass, stue)
    hass.states.async_set("climate.stue_ovn", "off", {"temperature": 18.0})
    hass.states.async_set("sensor.stue_effekt", "0.0", {"device_class": "power"})
    await hass.services.async_call(
        DOMAIN,
        table.SET_REGULATION,
        {
            "entity_id": room,
            "heaters": ["climate.stue_ovn"],
            "power_sensor": "sensor.stue_effekt",
        },
        blocking=True,
    )
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": room, "hvac_mode": "off"}, blocking=True
    )

    hass.states.async_set("sensor.stue_effekt", "615.0", {"device_class": "power"})
    await hass.async_block_till_done()
    await pass_the_window(hass, freezer, 16)

    issue = f"relay_stuck_closed_{the_room_id(hass, stue)}"
    raised = ir.async_get(hass).async_get_issue(DOMAIN, issue)
    assert raised is not None
    assert raised.translation_key == "thermostat_drew_power"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_deadline_written_as_a_time_lands_on_the_right_hour_when_the_clock_moves(
    hass: HomeAssistant, freezer
) -> None:
    """Europe/Oslo goes back an hour at 03:00 on 2026-10-25.

    Writing the wanted hour onto today's date keeps the offset the day started on, so 06:00 comes
    out an hour early. The control below is that arithmetic, and it has to disagree with the answer
    or this test proves nothing.
    """
    await hass.config.async_set_time_zone("Europe/Oslo")
    freezer.move_to("2026-10-25 00:30:00+02:00")
    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    a_heater(hass, stue, "stue_panel")
    a_temperature_sensor(hass, stue, "stue_temperatur", "19.0")
    await the_house(hass)

    await hass.services.async_call(
        DOMAIN,
        table.WARM_ROOM_BY,
        {"entity_id": the_room(hass, stue), "temperature": 21.0, "by_time": "06:00:00"},
        blocking=True,
    )

    now = dt_util.now()
    by_hand = now.replace(hour=6, minute=0, second=0, microsecond=0)
    warm_up = hass.states.get(the_room(hass, stue)).attributes["warm_up"]
    deadline = dt_util.parse_datetime(warm_up["deadline"])

    wanted = datetime(2026, 10, 25, 6, 0, tzinfo=dt_util.get_time_zone("Europe/Oslo"))

    assert deadline == dt_util.as_utc(wanted)
    assert dt_util.as_utc(by_hand) != deadline


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_room_moved_to_another_area_keeps_its_entity_device_and_target(
    hass: HomeAssistant,
) -> None:
    """The device registry call and the action reaching the entity, which nothing else settles.

    The room moves first and its heater after: an area holding a labelled heater already has a room.
    """
    from homeassistant.helpers import device_registry as dr

    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    bad = an_area(hass, "Bad")
    garasje = an_area(hass, "Garasje")
    heater = a_heater(hass, stue, "stue_panel")
    a_heater(hass, bad, "bad_panel")
    a_temperature_sensor(hass, stue, "stue_temperatur", "19.0")
    await the_house(hass)
    room = the_room(hass, stue)
    room_id = the_room_id(hass, stue)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": room, ATTR_TEMPERATURE: 21.5}, blocking=True
    )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, table.MOVE_TO_AREA, {"entity_id": room, "area": bad}, blocking=True
        )

    await hass.services.async_call(
        DOMAIN, table.MOVE_TO_AREA, {"entity_id": room, "area": garasje}, blocking=True
    )
    er.async_get(hass).async_update_entity(heater, area_id=garasje)
    await hass.async_block_till_done()

    assert the_room(hass, garasje) == room
    assert the_room(hass, stue) is None
    assert er.async_get(hass).async_get(room).unique_id == room_id
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, room_id)})
    assert device is not None and device.area_id == garasje
    assert hass.states.get(room).attributes["temperature"] == 21.5


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_room_follows_its_device_moved_by_hand_and_a_taken_area_puts_it_back(
    hass: HomeAssistant,
) -> None:
    """The device registry's own event, which only a running core raises."""
    from homeassistant.helpers import device_registry as dr

    assert await async_setup_component(hass, DOMAIN, {})
    stue = an_area(hass, "Stue")
    bad = an_area(hass, "Bad")
    garasje = an_area(hass, "Garasje")
    heater = a_heater(hass, stue, "stue_panel")
    a_heater(hass, bad, "bad_panel")
    a_temperature_sensor(hass, stue, "stue_temperatur", "19.0")
    await the_house(hass)
    room = the_room(hass, stue)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": room, ATTR_TEMPERATURE: 21.5}, blocking=True
    )
    room_id = the_room_id(hass, stue)
    devices = dr.async_get(hass)
    device = devices.async_get_device(identifiers={(DOMAIN, room_id)})
    assert device is not None

    devices.async_update_device(device.id, area_id=bad)
    await hass.async_block_till_done()
    assert devices.async_get(device.id).area_id == stue
    assert the_room(hass, stue) == room

    devices.async_update_device(device.id, area_id=garasje)
    await hass.async_block_till_done()
    er.async_get(hass).async_update_entity(heater, area_id=garasje)
    await hass.async_block_till_done()

    assert the_room(hass, garasje) == room
    assert er.async_get(hass).async_get(room).unique_id == room_id
    assert devices.async_get(device.id).area_id == garasje
    assert hass.states.get(room).attributes["temperature"] == 21.5
