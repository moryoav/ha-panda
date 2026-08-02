"""Button entities for PANDA ESL writes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .runtime import (
    PandaEslRuntimeData,
    async_write_black_fill,
    async_write_nearfinal_framed_image,
    async_write_red_fill,
    async_write_white_fill,
)

PARALLEL_UPDATES = 0

WriteFn = Callable[[HomeAssistant, PandaEslRuntimeData], Awaitable[None]]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PANDA ESL write buttons."""
    runtime: PandaEslRuntimeData = entry.runtime_data
    async_add_entities(
        [
            PandaEslWriteButton(
                hass,
                entry,
                runtime,
                key="white_fill",
                write_fn=async_write_white_fill,
            ),
            PandaEslWriteButton(
                hass,
                entry,
                runtime,
                key="black_fill",
                write_fn=async_write_black_fill,
            ),
            PandaEslWriteButton(
                hass,
                entry,
                runtime,
                key="red_fill",
                write_fn=async_write_red_fill,
            ),
            PandaEslWriteButton(
                hass,
                entry,
                runtime,
                key="framed_image",
                write_fn=async_write_nearfinal_framed_image,
            ),
        ]
    )


class PandaEslWriteButton(CoordinatorEntity, ButtonEntity):
    """Button that sends one PANDA ESL diagnostic write."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        runtime: PandaEslRuntimeData,
        *,
        key: str,
        write_fn: WriteFn,
    ) -> None:
        """Initialize the button."""
        super().__init__(runtime.coordinator)
        self._hass = hass
        self._entry = entry
        self._runtime = runtime
        self._key = key
        self._write_fn = write_fn
        self._attr_translation_key = key
        safe_address = runtime.state.address.replace(":", "").lower()
        self._attr_unique_id = f"{DOMAIN}_{safe_address}_{key}"

    @property
    def available(self) -> bool:
        """Return true when the tag is visible to Home Assistant Bluetooth."""
        return self._runtime.state.present

    async def async_press(self) -> None:
        """Send the selected image/fill."""
        await self._write_fn(self._hass, self._runtime)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the most recent write result for this button."""
        return self._runtime.state.write_action_results.get(self._key, {})

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self._runtime.state.address)},
            identifiers={(DOMAIN, self._runtime.state.address)},
            manufacturer=MANUFACTURER,
            model=self._runtime.profile.model,
            name=self._entry.data.get(CONF_NAME) or self._entry.title,
        )
