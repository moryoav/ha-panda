"""Sensor entities for PANDA ESL."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .models import PandaEslState
from .runtime import PandaEslRuntimeData

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PANDA ESL sensors."""
    runtime: PandaEslRuntimeData = entry.runtime_data
    async_add_entities(
        [
            PandaEslWriteProgressSensor(entry, runtime),
            PandaEslBluetoothRssiSensor(entry, runtime),
        ]
    )


class PandaEslWriteProgressSensor(CoordinatorEntity, SensorEntity):
    """Sensor that reports BLE image write progress."""

    _attr_has_entity_name = True
    _attr_translation_key = "write_progress"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 1

    def __init__(self, entry: ConfigEntry, runtime: PandaEslRuntimeData) -> None:
        """Initialize the write progress sensor."""
        super().__init__(runtime.coordinator)
        self._entry = entry
        self._runtime = runtime
        safe_address = runtime.state.address.replace(":", "").lower()
        self._attr_unique_id = f"{DOMAIN}_{safe_address}_write_progress"

    @property
    def available(self) -> bool:
        """Return true because progress is local runtime state."""
        return True

    @property
    def native_value(self) -> float:
        """Return the current write progress percentage."""
        return self._panda_state.write_progress_percent

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return chunk-level write progress details."""
        return {
            "active": self._panda_state.write_progress_active,
            "chunks_written": self._panda_state.write_progress_chunks_written,
            "chunks_total": self._panda_state.write_progress_chunks_total,
            "attempt": self._panda_state.write_progress_attempt,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self._runtime.state.address)},
            identifiers={(DOMAIN, self._runtime.state.address)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=self._entry.data.get(CONF_NAME) or self._entry.title,
        )

    @property
    def _panda_state(self) -> PandaEslState:
        """Return the current shared state."""
        return self._runtime.state


class PandaEslBluetoothRssiSensor(CoordinatorEntity, SensorEntity):
    """Sensor that reports the latest advertised Bluetooth RSSI."""

    _attr_has_entity_name = True
    _attr_translation_key = "bluetooth_rssi"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_suggested_display_precision = 0

    def __init__(self, entry: ConfigEntry, runtime: PandaEslRuntimeData) -> None:
        """Initialize the Bluetooth RSSI sensor."""
        super().__init__(runtime.coordinator)
        self._entry = entry
        self._runtime = runtime
        safe_address = runtime.state.address.replace(":", "").lower()
        self._attr_unique_id = f"{DOMAIN}_{safe_address}_bluetooth_rssi"

    @property
    def available(self) -> bool:
        """Return true when the tag is visible and RSSI is known."""
        return self._panda_state.present and self._panda_state.rssi is not None

    @property
    def native_value(self) -> int | None:
        """Return the latest advertised Bluetooth RSSI in dBm."""
        return self._panda_state.rssi

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self._runtime.state.address)},
            identifiers={(DOMAIN, self._runtime.state.address)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=self._entry.data.get(CONF_NAME) or self._entry.title,
        )

    @property
    def _panda_state(self) -> PandaEslState:
        """Return the current shared state."""
        return self._runtime.state
