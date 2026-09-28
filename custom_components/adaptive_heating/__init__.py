"""Adaptive Heating: a thermostat per room, between the room's sensors and its heaters."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_platform_entity_service
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS, VOCABULARY_VERSION
from .core import actions as action_table

__all__ = ["DOMAIN", "VOCABULARY_VERSION"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """The five actions, declared before any room is set up.

    Registering them here rather than from the climate platform is what makes them exist even
    where no room loads, which is what an automation naming one is validated against.
    """
    for action in action_table.ACTIONS:
        async_register_platform_entity_service(
            hass,
            DOMAIN,
            action.name,
            entity_domain=CLIMATE_DOMAIN,
            func=f"async_{action.name}",
            # Only the helper's own builder produces a schema the platform accepts, and its
            # default refuses a field it does not know. Removing one instead is what lets a newer
            # add-on talk to an older integration without either half gating on a version.
            schema=cv.make_entity_service_schema(
                action.fields_for_the_schema(), extra=vol.REMOVE_EXTRA
            ),
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # One room per entry. The shared table is what lets a borrowing room find its neighbour's
    # reading without either of them owning the other.
    hass.data.setdefault(DOMAIN, {})
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
