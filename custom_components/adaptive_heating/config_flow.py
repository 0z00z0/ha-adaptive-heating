"""Setting the house up: one entry, and the heaters and sensors that make its rooms."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.helpers import selector
from homeassistant.helpers.storage import Store

from .const import DOMAIN, HEATING_LABEL, LABELS_STORAGE_KEY, STORAGE_VERSION
from .core.rooms import HEATER_DOMAINS, SENSOR_DOMAIN, TEMPERATURE
from .core.setup import every_heater, label_the_setup_offers, labels_to_write, without_an_area

LABEL = "label"
HEATERS = "heaters"
TEMPERATURE_SENSORS = "temperature_sensors"


class AdaptiveHeatingConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    # Set by "start from every heater": the heaters form opens with every candidate ticked.
    _every = False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return self.async_show_menu(step_id="user", menu_options=["rooms", "every_heater"])

    async def async_step_every_heater(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._every = True
        return await self.async_step_rooms()

    async def async_step_rooms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # Rooms are never stored in the entry. The label written here is what finds them.
        store: Store = Store(self.hass, STORAGE_VERSION, LABELS_STORAGE_KEY)
        stored = await store.async_load() or {}
        existing = [one.label_id for one in lr.async_get(self.hass).async_list_labels()]
        label, choosable = label_the_setup_offers(stored, existing, HEATING_LABEL)
        if not choosable:
            # The add-on already sent a label, and the House tab is where it changes.
            return await self.async_step_rooms_labelled(user_input)
        if user_input is not None:
            label = user_input.get(LABEL)

        async def finish(written: str) -> ConfigFlowResult:
            await store.async_save({**stored, "include_label": written})
            return self.async_create_entry(title="Adaptive Heating", data={})

        return await self._pick("rooms", label, user_input, finish, untick=False, choosable=True)

    async def async_step_rooms_labelled(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        stored = await Store(self.hass, STORAGE_VERSION, LABELS_STORAGE_KEY).async_load() or {}

        async def finish(_written: str) -> ConfigFlowResult:
            return self.async_create_entry(title="Adaptive Heating", data={})

        return await self._pick(
            "rooms_labelled", stored["include_label"], user_input, finish, untick=False
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        house = getattr(self._get_reconfigure_entry(), "runtime_data", None)
        include = getattr(house, "include_label", None)
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["reconfigure_rooms", "reconfigure_every_heater"],
            description_placeholders={LABEL: self._label_name(include or HEATING_LABEL)},
        )

    async def async_step_reconfigure_every_heater(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._every = True
        return await self.async_step_reconfigure_rooms()

    async def async_step_reconfigure_rooms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        # The add-on's House tab owns the label; the picker writes the one rooms are found by.
        include = getattr(getattr(entry, "runtime_data", None), "include_label", None)

        async def finish(_written: str) -> ConfigFlowResult:
            # No reload: the registry listener adds and removes rooms without one.
            return self.async_abort(reason="reconfigure_successful")

        return await self._pick(
            "reconfigure_rooms", include or HEATING_LABEL, user_input, finish, untick=True
        )

    async def _pick(
        self,
        step_id: str,
        label: str | None,
        user_input: dict[str, Any] | None,
        finish: Any,
        untick: bool,
        choosable: bool = False,
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
        if self._every and user_input is None:
            # Ticked on the form only: nothing is written until the person submits.
            ticked[HEATERS] = every_heater(
                (
                    (one.entity_id, one.domain, one.platform, area)
                    for one, area in self._with_areas(entities)
                ),
                HEATER_DOMAINS,
                DOMAIN,
            )
        errors: dict[str, str] = {}
        placeholders = {"entities": "", LABEL: self._label_name(label)}
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
                # Made only once the rest is accepted, so a refused form creates nothing.
                written = label or self._the_heating_label()
                self._write(entities, written, picked, ticked, untick)
                return await finish(written)
            ticked = {HEATERS: heaters, TEMPERATURE_SENSORS: sensors}

        suggested: dict[str, Any] = dict(ticked)
        fields: dict[object, object] = {}
        if choosable:
            fields[vol.Optional(LABEL)] = selector.LabelSelector(selector.LabelSelectorConfig())
            if label is not None:
                suggested[LABEL] = label
        schema = vol.Schema(
            {
                **fields,
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
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
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

    def _with_areas(
        self, entities: er.EntityRegistry
    ) -> list[tuple[er.RegistryEntry, str | None]]:
        devices = dr.async_get(self.hass)
        found: list[tuple[er.RegistryEntry, str | None]] = []
        for one in entities.entities.values():
            if one.disabled_by is not None:
                continue
            device = None if one.device_id is None else devices.async_get(one.device_id)
            found.append((one, one.area_id or (None if device is None else device.area_id)))
        return found

    def _the_heating_label(self) -> str:
        """The label id of "Heating", made when the house has none."""
        labels = lr.async_get(self.hass)
        known = labels.async_get_label_by_name("Heating")
        return (known or labels.async_create("Heating")).label_id

    def _label_name(self, label: str | None) -> str:
        known = None if label is None else lr.async_get(self.hass).async_get_label(label)
        return label or "" if known is None else known.name

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
        shown = ticked[HEATERS] + ticked[TEMPERATURE_SENSORS]
        unticked = [one for one in shown if one not in picked] if untick else []
        current = {
            one: known.labels
            for one in picked + unticked
            if (known := entities.async_get(one)) is not None
        }
        for entity_id, written in labels_to_write(current, label, picked, unticked).items():
            entities.async_update_entity(entity_id, labels=written)
