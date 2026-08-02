"""Config flow for PANDA ESL Bluetooth tags."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth, onboarding
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_DEBOUNCE_MS,
    CONF_DISCOVERED_NAME,
    CONF_PREVENT_DUPLICATE_SEND,
    CONF_RETRY_COUNT,
    CONF_SERVICE_UUIDS,
    CONF_WRITE_DELAY_MS,
    DEFAULT_DEBOUNCE_MS,
    DEFAULT_PREVENT_DUPLICATE_SEND,
    DEFAULT_RETRY_COUNT,
    DEFAULT_WRITE_DELAY_MS,
    DOMAIN,
    MAX_RETRY_COUNT,
)
from .models import service_info_supported, title_from_service_info
from .profiles import device_profile_from_names

OPTIONS_SCHEMA = {
    vol.Required(CONF_RETRY_COUNT, default=DEFAULT_RETRY_COUNT): NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=MAX_RETRY_COUNT,
            step=1,
            mode=NumberSelectorMode.BOX,
        )
    ),
    vol.Required(CONF_WRITE_DELAY_MS, default=DEFAULT_WRITE_DELAY_MS): NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=1000,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="ms",
        )
    ),
    vol.Required(
        CONF_PREVENT_DUPLICATE_SEND,
        default=DEFAULT_PREVENT_DUPLICATE_SEND,
    ): bool,
    vol.Required(CONF_DEBOUNCE_MS, default=DEFAULT_DEBOUNCE_MS): NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=120000,
            step=1000,
            mode=NumberSelectorMode.SLIDER,
            unit_of_measurement="ms",
        )
    ),
}


@dataclass
class Discovery:
    """A discovered PANDA ESL device."""

    title: str
    service_info: BluetoothServiceInfoBleak


class PandaEslConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PANDA ESL."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._title: str | None = None
        self._discovered_devices: dict[str, Discovery] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle Bluetooth discovery."""
        if not service_info_supported(discovery_info):
            return self.async_abort(reason="not_supported")

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self._title = title_from_service_info(discovery_info)
        self.context["title_placeholders"] = {"name": self._title}

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a Bluetooth-discovered tag."""
        if user_input is not None or not onboarding.async_is_onboarded(self.hass):
            return self._async_create_entry()

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders=self.context["title_placeholders"],
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose from currently discovered tags."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            discovery = self._discovered_devices[address]
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            self._discovery_info = discovery.service_info
            self._title = discovery.title
            self.context["title_placeholders"] = {"name": discovery.title}
            return self._async_create_entry()

        await bluetooth.async_request_active_scan(self.hass, duration=5)
        current_ids = self._async_current_ids(include_ignore=False)
        for service_info in bluetooth.async_discovered_service_info(self.hass, False):
            address = service_info.address
            if address in current_ids or address in self._discovered_devices:
                continue
            if service_info_supported(service_info):
                self._discovered_devices[address] = Discovery(
                    title=title_from_service_info(service_info),
                    service_info=service_info,
                )

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        titles = {
            address: discovery.title
            for address, discovery in self._discovered_devices.items()
        }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(titles)}),
        )

    async def async_step_import(
        self, import_config: dict[str, Any]
    ) -> ConfigFlowResult:
        """Import a PANDA ESL tag from YAML."""
        address = import_config[CONF_ADDRESS].upper()
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()

        service_info = bluetooth.async_last_service_info(
            self.hass, address, connectable=False
        )
        if service_info is not None:
            if not service_info_supported(service_info):
                return self.async_abort(reason="not_supported")
            self._discovery_info = service_info
            self._title = title_from_service_info(service_info)
            self.context["title_placeholders"] = {"name": self._title}
            return self._async_create_entry()

        imported_name = import_config.get(CONF_NAME)
        if device_profile_from_names(imported_name) is None:
            return self.async_abort(reason="not_supported")

        title = str(imported_name)
        return self.async_create_entry(
            title=title,
            data={
                CONF_ADDRESS: address,
                CONF_NAME: title,
                CONF_DISCOVERED_NAME: title,
                CONF_SERVICE_UUIDS: [],
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of a configured tag."""
        entry = self._get_reconfigure_entry()
        address = entry.data[CONF_ADDRESS]

        if user_input is not None:
            name = str(user_input[CONF_NAME]).strip()
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_mismatch()

            data_updates: dict[str, Any] = {CONF_NAME: name}
            service_info = bluetooth.async_last_service_info(
                self.hass, address, connectable=False
            )
            if service_info is not None and service_info_supported(service_info):
                data_updates[CONF_DISCOVERED_NAME] = title_from_service_info(
                    service_info
                )
                data_updates[CONF_SERVICE_UUIDS] = sorted(
                    uuid.lower() for uuid in service_info.service_uuids
                )

            return self.async_update_reload_and_abort(
                entry,
                data_updates=data_updates,
            )

        current_name = entry.data.get(CONF_NAME) or entry.title
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=current_name): vol.All(
                        str, str.strip, vol.Length(min=1)
                    )
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow."""
        return OptionsFlowHandler()

    def _async_create_entry(self) -> ConfigFlowResult:
        """Create a config entry from selected discovery info."""
        assert self._discovery_info is not None
        title = self._title or title_from_service_info(self._discovery_info)
        return self.async_create_entry(
            title=title,
            data={
                CONF_ADDRESS: self._discovery_info.address,
                CONF_NAME: title,
                CONF_DISCOVERED_NAME: title_from_service_info(
                    self._discovery_info
                ),
                CONF_SERVICE_UUIDS: sorted(
                    uuid.lower() for uuid in self._discovery_info.service_uuids
                ),
            },
        )


class OptionsFlowHandler(OptionsFlowWithReload):
    """Handle PANDA ESL options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        suggested_values = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(OPTIONS_SCHEMA), suggested_values
            ),
        )
