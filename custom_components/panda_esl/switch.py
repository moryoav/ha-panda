"""Switch entities for PANDA ESL."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    PACKET_NOTIFICATION_CAPTURE,
    ROTATE,
    WRITE_LOCK,
)
from .runtime import PandaEslRuntimeData, async_set_rotation

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PANDA ESL switches."""
    async_add_entities(
        [
            PandaEslWriteLockSwitch(hass, entry),
            PandaEslRotateSwitch(hass, entry),
            PandaEslPacketNotificationCaptureSwitch(hass, entry),
        ]
    )


class PandaEslRotateSwitch(SwitchEntity):
    """Persistent mounting orientation with an immediate display refresh."""

    _attr_has_entity_name = True
    _attr_translation_key = ROTATE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the per-device rotation switch."""
        self._hass = hass
        self._entry = entry
        self._runtime: PandaEslRuntimeData = entry.runtime_data
        safe_address = self._runtime.state.address.replace(":", "").lower()
        self._attr_unique_id = f"{DOMAIN}_{safe_address}_{ROTATE}"

    @property
    def device_info(self) -> DeviceInfo:
        """Attach the setting to its label."""
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self._runtime.state.address)},
            identifiers={(DOMAIN, self._runtime.state.address)},
            manufacturer=MANUFACTURER,
            model=self._runtime.profile.model,
            name=self._entry.data.get(CONF_NAME) or self._entry.title,
        )

    @property
    def is_on(self) -> bool:
        """Return whether outgoing content is rotated by 180 degrees."""
        return self._runtime.rotate

    async def async_turn_on(self, **kwargs) -> None:
        """Rotate the current content and subsequent writes."""
        await async_set_rotation(self._hass, self._entry, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Restore the normal mounting orientation."""
        await async_set_rotation(self._hass, self._entry, False)
        self.async_write_ha_state()


class PandaEslWriteLockSwitch(RestoreEntity, SwitchEntity):
    """Switch that guards physical service writes."""

    _attr_has_entity_name = True
    _attr_translation_key = "write_lock"
    _attr_entity_category = EntityCategory.CONFIG

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
            model=self._runtime.profile.model,
            name=self._entry.data.get(CONF_NAME) or self._entry.title,
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


class PandaEslPacketNotificationCaptureSwitch(RestoreEntity, SwitchEntity):
    """Switch that enables packet-level notification trace files."""

    _attr_has_entity_name = True
    _attr_translation_key = "packet_notification_capture"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the packet notification capture switch."""
        runtime: PandaEslRuntimeData = entry.runtime_data
        self._hass = hass
        self._entry = entry
        self._runtime = runtime
        self._is_on = bool(entry.data.get(PACKET_NOTIFICATION_CAPTURE, False))
        safe_address = runtime.state.address.replace(":", "").lower()
        self._attr_unique_id = (
            f"{DOMAIN}_{safe_address}_packet_notification_capture"
        )

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

    @property
    def available(self) -> bool:
        """Return true."""
        return True

    @property
    def is_on(self) -> bool:
        """Return whether packet notification capture is enabled."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Enable packet notification trace files."""
        self._set_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable packet notification trace files."""
        self._set_enabled(False)

    async def async_added_to_hass(self) -> None:
        """Restore the packet notification capture state."""
        await super().async_added_to_hass()
        if PACKET_NOTIFICATION_CAPTURE in self._entry.data:
            self._is_on = bool(self._entry.data[PACKET_NOTIFICATION_CAPTURE])
        else:
            last_state = await self.async_get_last_state()
            self._is_on = last_state is not None and last_state.state == "on"
        self._apply_state()

    def _set_enabled(self, value: bool) -> None:
        """Update and persist the capture switch state."""
        self._is_on = value
        self._apply_state()
        self._persist_state(value)
        self.async_write_ha_state()

    def _apply_state(self) -> None:
        """Apply the switch state to runtime and domain storage."""
        self._runtime.packet_notification_capture = self._is_on
        self._hass.data[DOMAIN][self._entry.entry_id][
            PACKET_NOTIFICATION_CAPTURE
        ] = self._is_on

    def _persist_state(self, value: bool) -> None:
        data = {**self._entry.data, PACKET_NOTIFICATION_CAPTURE: value}
        self._hass.config_entries.async_update_entry(self._entry, data=data)
