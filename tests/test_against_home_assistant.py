"""The two things only a running Home Assistant can settle.

Both were found by a live trial at the cabin on 2026-09-24, and both were invisible from the
interface: the entry reported itself loaded and the thermostat worked.

- Not one of the five actions was registered. Home Assistant refused the first schema and the
  raise took every later registration with it, leaving a line in the log and nothing else. Asking
  the registry is the only way to catch that.
- A sensor dead for a year was believed, because the integration timed the reading by when it
  first noticed it. Only a real state carries the times that settle it.
- A heater a second room names is refused by the setup dialog. The rule itself is settled without
  Home Assistant; what only a running one settles is that the dialog answers with the refusal, keeps
  the form open and creates no second room.

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

import voluptuous  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.exceptions import ServiceValidationError  # noqa: E402
from homeassistant.setup import async_setup_component  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.adaptive_heating.const import (  # noqa: E402
    ATTR_BAND,
    ATTR_RESTING_ON,
    CONF_HEATERS,
    CONF_ROOM,
    CONF_TEMPERATURE_SENSORS,
    DOMAIN,
)
from custom_components.adaptive_heating.core import actions as table  # noqa: E402

ROOM = "climate.toalett"


async def a_room(hass: HomeAssistant, sensors: list[str] | None = None) -> MockConfigEntry:
    hass.states.async_set("switch.panel", "off")
    if sensors is None:
        hass.states.async_set("sensor.room", "18.6")
        sensors = ["sensor.room"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Toalett",
        data={
            CONF_ROOM: "Toalett",
            CONF_HEATERS: ["switch.panel"],
            CONF_TEMPERATURE_SENSORS: sensors,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_every_one_of_the_five_actions_reaches_the_registry(hass: HomeAssistant) -> None:
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
    assert hass.states.get(ROOM) is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_an_action_called_against_a_room_reaches_the_thermostat(
    hass: HomeAssistant,
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await a_room(hass)

    await hass.services.async_call(
        DOMAIN,
        table.HOLD_TEMPERATURE,
        {"entity_id": ROOM, "temperature": 22.0, "duration": {"hours": 1}},
        blocking=True,
    )
    assert hass.states.get(ROOM).attributes["temperature"] == 22.0

    await hass.services.async_call(
        DOMAIN, table.RETURN_TO_TARGET, {"entity_id": ROOM}, blocking=True
    )
    assert hass.states.get(ROOM).attributes["temperature"] != 22.0


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_field_this_half_does_not_know_is_dropped_rather_than_refusing_the_call(
    hass: HomeAssistant,
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await a_room(hass)

    # What a newer add-on sends an older integration. The fields it does know still take effect.
    await hass.services.async_call(
        DOMAIN,
        table.SET_REGULATION,
        {"entity_id": ROOM, "band": 0.4, "something_later_added": 99},
        blocking=True,
    )
    assert hass.states.get(ROOM).attributes[ATTR_BAND] == 0.4


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_field_outside_its_bound_never_reaches_the_thermostat(
    hass: HomeAssistant,
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await a_room(hass)
    before = hass.states.get(ROOM).attributes[ATTR_BAND]

    # A `vol.Invalid` is what answers `invalid_format` over the websocket, and it is the shape a
    # room's own refusal has to stay clear of.
    with pytest.raises(voluptuous.Invalid):
        await hass.services.async_call(
            DOMAIN, table.SET_REGULATION, {"entity_id": ROOM, "band": 9.0}, blocking=True
        )
    assert hass.states.get(ROOM).attributes[ATTR_BAND] == before


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_room_s_own_refusal_leaves_the_handler_as_a_service_validation_error(
    hass: HomeAssistant,
) -> None:
    """The one shape that answers `service_validation_error`, which is the add-on's marker for an
    answer the room itself gave."""
    assert await async_setup_component(hass, DOMAIN, {})
    await a_room(hass)

    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": ROOM, "hvac_mode": "off"}, blocking=True
    )

    with pytest.raises(ServiceValidationError) as refused:
        await hass.services.async_call(
            DOMAIN,
            table.HOLD_TEMPERATURE,
            {"entity_id": ROOM, "temperature": 22.0, "duration": {"hours": 1}},
            blocking=True,
        )

    assert not isinstance(refused.value, voluptuous.Invalid)
    assert str(refused.value) == "The room is switched off."


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_call_naming_no_room_is_refused(hass: HomeAssistant) -> None:
    # The target fields belong to Home Assistant's own builder, and it is that builder which
    # insists on at least one of them.
    assert await async_setup_component(hass, DOMAIN, {})
    await a_room(hass)

    with pytest.raises(Exception):  # noqa: B017 - the platform's own refusal
        await hass.services.async_call(DOMAIN, table.RETURN_TO_TARGET, {}, blocking=True)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_sensor_dead_for_a_year_does_not_take_the_healthy_one_down_with_it(
    hass: HomeAssistant, freezer
) -> None:
    """The cabin's own case: 10.7 from 2024 beside 18.6 from today, 7.9 degrees apart."""
    assert await async_setup_component(hass, DOMAIN, {})

    freezer.move_to("2025-09-24 12:00:00+00:00")
    hass.states.async_set("sensor.oomi", "10.7")

    freezer.move_to("2026-09-24 12:00:00+00:00")
    hass.states.async_set("sensor.shelly", "18.6")
    await a_room(hass, ["sensor.oomi", "sensor.shelly"])

    state = hass.states.get(ROOM)
    assert state.attributes["current_temperature"] == 18.6
    assert state.attributes[ATTR_RESTING_ON] == 1


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_a_second_room_naming_the_same_heater_is_refused_by_the_dialog(
    hass: HomeAssistant,
) -> None:
    """Two loops over one relay defeat the guard outright: 384 commands a day against 192."""
    assert await async_setup_component(hass, DOMAIN, {})
    await a_room(hass)

    started = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    answered = await hass.config_entries.flow.async_configure(
        started["flow_id"],
        {CONF_ROOM: "Stue", CONF_HEATERS: ["switch.panel"]},
    )

    assert answered["type"] == "form"
    assert answered["errors"] == {CONF_HEATERS: "heater_taken"}
    # The refusal names the room holding the heater, or nobody can act on it.
    assert answered["description_placeholders"]["room"] == "Toalett"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
