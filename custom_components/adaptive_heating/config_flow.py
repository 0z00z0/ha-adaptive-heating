"""Setting the house up: one entry, and the heaters and sensors that make its rooms."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.helpers import selector

from .const import DOMAIN, HEATING_LABEL
from .core.rooms import HEATER_DOMAINS, SENSOR_DOMAIN, TEMPERATURE
from .core.setup import labels_to_write, without_an_area

HEATERS = "heaters"
TEMPERATURE_SENSORS = "temperature_sensors"


class AdaptiveHeatingConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return await self.async_step_rooms()

    async def async_step_rooms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # Rooms are never stored in the entry. The label written here is what finds them.
        return await self._pick(
            "rooms",
            HEATING_LABEL,
            user_input,
            lambda: self.async_create_entry(title="Adaptive Heating", data={}),
            untick=False,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        # The add-on's House tab can replace the label; the picker writes the one rooms are found by.
        include = getattr(getattr(entry, "runtime_data", None), "include_label", None)
        # No reload: the registry listener adds and removes rooms without one.
        return await self._pick(
            "reconfigure",
            include or HEATING_LABEL,
            user_input,
            lambda: self.async_abort(reason="reconfigure_successful"),
            untick=True,
        )

    async def _pick(
        self,
        step_id: str,
        label: str,
        user_input: dict[str, Any] | None,
        finish: Any,
        untick: bool,
    ) -> ConfigFlowResult:
        entities = er.async_get(self.hass)
        own = [one.entity_id for one in entities.entities.values() if one.platform == DOMAIN]
        ticked = {
            HEATERS: sorted(
                one.entity_id
                for one in entities.entities.values()
                if label in one.labels
                and one.domain in HEATER_DOMAINS
                and one.platform != DOMAIN
            ),
            TEMPERATURE_SENSORS: sorted(
                one.entity_id
                for one in entities.entities.values()
                if label in one.labels
                and one.domain == SENSOR_DOMAIN
                and (one.device_class or one.original_device_class) == TEMPERATURE
            ),
        }
        errors: dict[str, str] = {}
        placeholders = {"entities": ""}
        if user_input is not None:
            heaters = list(user_input.get(HEATERS, []))
            sensors = list(user_input.get(TEMPERATURE_SENSORS, []))
            picked = heaters + sensors
            homeless = without_an_area(picked, self._areas(entities, picked))
            if not heaters:
                errors[HEATERS] = "no_heater"
            elif homeless:
                errors["base"] = "no_area"
                placeholders["entities"] = ", ".join(self._name(one) for one in homeless)
            else:
                self._write(entities, label, picked, ticked, untick)
                return finish()
            ticked = {HEATERS: heaters, TEMPERATURE_SENSORS: sensors}

        schema = vol.Schema(
            {
                vol.Required(HEATERS): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=list(HEATER_DOMAINS), exclude_entities=own, multiple=True
                    )
                ),
                vol.Optional(TEMPERATURE_SENSORS): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=SENSOR_DOMAIN, device_class=TEMPERATURE, multiple=True
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, ticked),
            errors=errors,
            description_placeholders=placeholders,
        )

    def _areas(self, entities: er.EntityRegistry, picked: list[str]) -> dict[str, str | None]:
        devices = dr.async_get(self.hass)
        areas: dict[str, str | None] = {}
        for entity_id in picked:
            known = entities.async_get(entity_id)
            if known is None:
                # Not in the registry, so it can carry neither an area nor a label.
                areas[entity_id] = None
                continue
            device = None if known.device_id is None else devices.async_get(known.device_id)
            areas[entity_id] = known.area_id or (None if device is None else device.area_id)
        return areas

    def _name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return entity_id if state is None else state.name

    def _write(
        self,
        entities: er.EntityRegistry,
        label: str,
        picked: list[str],
        ticked: dict[str, list[str]],
        untick: bool,
    ) -> None:
        labels = lr.async_get(self.hass)
        if label == HEATING_LABEL and labels.async_get_label(label) is None:
            labels.async_create("Heating")
        shown = ticked[HEATERS] + ticked[TEMPERATURE_SENSORS]
        unticked = [one for one in shown if one not in picked] if untick else []
        current = {
            one: known.labels
            for one in picked + unticked
            if (known := entities.async_get(one)) is not None
        }
        for entity_id, written in labels_to_write(current, label, picked, unticked).items():
            entities.async_update_entity(entity_id, labels=written)
