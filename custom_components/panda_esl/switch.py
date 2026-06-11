"""Switch entities for PANDA ESL."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, MANUFACTURER, MODEL, WRITE_LOCK
from .runtime import PandaEslRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the PANDA ESL write-lock switch."""
    async_add_entities([PandaEslWriteLockSwitch(hass, entry)])


class PandaEslWriteLockSwitch(RestoreEntity, SwitchEntity):
    """Switch that guards physical service writes."""

    _attr_has_entity_name = True
    _attr_translation_key = "write_lock"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:lock"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the write-lock switch."""
        runtime: PandaEslRuntimeData = entry.runtime_data
        self._hass = hass
        self._entry = entry
        self._runtime = runtime
        self._is_on = False
        safe_address = runtime.state.address.replace(":", "").lower()
        self._attr_unique_id = f"{DOMAIN}_{safe_address}_write_lock"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self._runtime.state.address)},
            identifiers={(DOMAIN, self._runtime.state.address)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=self._entry.title,
        )

    @property
    def available(self) -> bool:
        """Return true."""
        return True

    @property
    def is_on(self) -> bool:
        """Return whether physical guarded writes are locked."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the write lock."""
        self._is_on = True
        self._hass.data[DOMAIN][self._entry.entry_id][WRITE_LOCK] = True
        self._persist_state(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the write lock."""
        self._is_on = False
        self._hass.data[DOMAIN][self._entry.entry_id][WRITE_LOCK] = False
        self._persist_state(False)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore the write-lock state."""
        await super().async_added_to_hass()
        if WRITE_LOCK in self._entry.data:
            self._is_on = bool(self._entry.data[WRITE_LOCK])
        else:
            last_state = await self.async_get_last_state()
            self._is_on = last_state is not None and last_state.state == "on"
        self._hass.data[DOMAIN][self._entry.entry_id][WRITE_LOCK] = self._is_on

    def _persist_state(self, value: bool) -> None:
        data = {**self._entry.data, WRITE_LOCK: value}
        self._hass.config_entries.async_update_entry(self._entry, data=data)
