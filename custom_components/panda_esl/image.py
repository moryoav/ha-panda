"""Image entities for PANDA ESL rendered content."""

from __future__ import annotations

import logging

from homeassistant.components.image import Image, ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MANUFACTURER, MODEL
from .runtime import PandaEslRuntimeData

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PANDA ESL image entities."""
    runtime: PandaEslRuntimeData = entry.runtime_data
    async_add_entities(
        [
            PandaEslImageEntity(hass, entry, runtime.image_coordinator, "last_updated_content"),
            PandaEslImageEntity(
                hass,
                entry,
                runtime.preview_coordinator,
                "preview_content",
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        ]
    )


class PandaEslImageEntity(CoordinatorEntity[DataUpdateCoordinator[bytes]], ImageEntity):
    """Image entity backed by a PNG bytes coordinator."""

    _attr_has_entity_name = True
    _attr_content_type = "image/png"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: DataUpdateCoordinator[bytes],
        key: str,
        *,
        entity_category: EntityCategory | None = None,
    ) -> None:
        """Initialize the image entity."""
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        runtime: PandaEslRuntimeData = entry.runtime_data
        self._entry = entry
        self._runtime = runtime
        self._attr_translation_key = key
        self._attr_entity_category = entity_category
        safe_address = runtime.state.address.replace(":", "").lower()
        self._attr_unique_id = f"{DOMAIN}_{safe_address}_{key}"
        self._cached_image = Image(content_type="image/png", content=coordinator.data)

    @property
    def available(self) -> bool:
        """Return true when coordinator data exists."""
        return self.coordinator.data is not None

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
    def data(self) -> bytes:
        """Return raw PNG bytes."""
        return self.coordinator.data

    def image(self) -> bytes | None:
        """Return image bytes."""
        return self._cached_image.content

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle image data updates."""
        _LOGGER.debug("Updated PANDA ESL image data")
        self._cached_image = Image(content_type="image/png", content=self.data)
        self._attr_image_last_updated = dt_util.now()
        super()._handle_coordinator_update()
