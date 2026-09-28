"""Setting a room up: what it heats, what it reads, and whose reading it may borrow."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_HEATERS,
    CONF_NEIGHBOUR,
    CONF_OUTDOOR_SENSOR,
    CONF_POWER_SENSOR,
    CONF_ROOM,
    CONF_TEMPERATURE_SENSORS,
    CONF_WINDOW_SENSOR,
    DOMAIN,
)
from .core.setup import heater_already_claimed

_SWITCHES = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["switch", "input_boolean"], multiple=True)
)
_TEMPERATURES = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="temperature", multiple=True)
)
_ONE_TEMPERATURE = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
)
_WINDOW = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])
)
_NEIGHBOUR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="climate", integration=DOMAIN)
)
_POWER = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="power")
)


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ROOM, default=defaults.get(CONF_ROOM, "")): str,
            vol.Required(CONF_HEATERS, default=defaults.get(CONF_HEATERS, [])): _SWITCHES,
            vol.Optional(
                CONF_TEMPERATURE_SENSORS, default=defaults.get(CONF_TEMPERATURE_SENSORS, [])
            ): _TEMPERATURES,
            vol.Optional(CONF_NEIGHBOUR, description={"suggested_value": defaults.get(
                CONF_NEIGHBOUR)}): _NEIGHBOUR,
            vol.Optional(CONF_WINDOW_SENSOR, description={"suggested_value": defaults.get(
                CONF_WINDOW_SENSOR)}): _WINDOW,
            vol.Optional(CONF_OUTDOOR_SENSOR, description={"suggested_value": defaults.get(
                CONF_OUTDOOR_SENSOR)}): _ONE_TEMPERATURE,
            vol.Optional(CONF_POWER_SENSOR, description={"suggested_value": defaults.get(
                CONF_POWER_SENSOR)}): _POWER,
        }
    )


def _heaters_of_the_other_rooms(
    hass: HomeAssistant, this_entry_id: str | None
) -> dict[str, list[str]]:
    """Which heaters every other room drives, keyed by the room each belongs to."""
    elsewhere: dict[str, list[str]] = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == this_entry_id:
            continue
        options: dict[str, Any] = {**entry.data, **entry.options}
        elsewhere[options.get(CONF_ROOM, entry.title)] = list(options.get(CONF_HEATERS, []))
    return elsewhere


class AdaptiveHeatingConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            claimed = heater_already_claimed(
                user_input.get(CONF_HEATERS) or [],
                _heaters_of_the_other_rooms(self.hass, None),
            )
            if not user_input.get(CONF_HEATERS):
                # A room with nothing to switch is not set up, because nothing can be held.
                errors[CONF_HEATERS] = "no_heater"
            elif claimed is not None:
                # Two loops over one relay defeat the shortest time between relay changes outright.
                errors[CONF_HEATERS] = "heater_taken"
                placeholders["room"] = claimed[1]
            else:
                return self.async_create_entry(title=user_input[CONF_ROOM], data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return AdaptiveHeatingOptionsFlow()


class AdaptiveHeatingOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            # This room's own heaters are not somebody else's, so its entry is left out of the
            # check.
            claimed = heater_already_claimed(
                user_input.get(CONF_HEATERS) or [],
                _heaters_of_the_other_rooms(self.hass, self.config_entry.entry_id),
            )
            if not user_input.get(CONF_HEATERS):
                errors[CONF_HEATERS] = "no_heater"
            elif claimed is not None:
                errors[CONF_HEATERS] = "heater_taken"
                placeholders["room"] = claimed[1]
            else:
                return self.async_create_entry(title="", data=user_input)
        standing = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(standing),
            errors=errors,
            description_placeholders=placeholders,
        )
