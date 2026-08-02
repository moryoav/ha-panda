"""Image entities for PANDA ESL rendered content."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from homeassistant.components.image import Image, ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MANUFACTURER
from .runtime import PandaEslRuntimeData

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0
RESTORE_DATA_VERSION = 1
RESTORE_CONTENT_TYPE = "image/png"


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


@dataclass(frozen=True)
class PandaEslImageExtraStoredData(ExtraStoredData):
    """Extra restore data for PANDA ESL image bytes."""

    content: bytes
    content_type: str = RESTORE_CONTENT_TYPE
    version: int = RESTORE_DATA_VERSION

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the image data."""
        return {
            "version": self.version,
            "content_type": self.content_type,
            "content": base64.b64encode(self.content).decode("ascii"),
        }

    @classmethod
    def from_dict(
        cls, restored: dict[str, Any]
    ) -> "PandaEslImageExtraStoredData | None":
        """Return restored image data, or None when the payload is unusable."""
        if restored.get("version") != RESTORE_DATA_VERSION:
            return None
        if restored.get("content_type") != RESTORE_CONTENT_TYPE:
            return None
        encoded_content = restored.get("content")
        if not isinstance(encoded_content, str):
            return None
        try:
            content = base64.b64decode(encoded_content.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError):
            return None
        if not content:
            return None
        return cls(content=content)


def _restored_image_timestamp(last_state: State | None) -> datetime | None:
    """Return the restored image timestamp from an image entity state."""
    if last_state is None or last_state.state in (None, "unknown", "unavailable"):
        return None
    return dt_util.parse_datetime(last_state.state)


class PandaEslImageEntity(
    CoordinatorEntity[DataUpdateCoordinator[bytes]], RestoreEntity, ImageEntity
):
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

    async def async_added_to_hass(self) -> None:
        """Restore the last image bytes after Home Assistant restarts."""
        await super().async_added_to_hass()
        restored_extra = await self.async_get_last_extra_data()
        if restored_extra is None:
            return
        restored_image = PandaEslImageExtraStoredData.from_dict(
            restored_extra.as_dict()
        )
        if restored_image is None:
            return

        self.coordinator.data = restored_image.content
        self._cached_image = Image(
            content_type=restored_image.content_type,
            content=restored_image.content,
        )
        self._attr_image_last_updated = _restored_image_timestamp(
            await self.async_get_last_state()
        )

    @property
    def extra_restore_state_data(self) -> PandaEslImageExtraStoredData | None:
        """Return image bytes to restore after Home Assistant restarts."""
        if self._cached_image is None or self._cached_image.content is None:
            return None
        return PandaEslImageExtraStoredData(
            content=self._cached_image.content,
            content_type=self._cached_image.content_type,
        )

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
            model=self._runtime.profile.model,
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
        self._cached_image = Image(content_type=RESTORE_CONTENT_TYPE, content=self.data)
        self._attr_image_last_updated = dt_util.now()
        super()._handle_coordinator_update()
