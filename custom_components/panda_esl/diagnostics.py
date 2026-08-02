"""Diagnostics support for PANDA ESL."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ADDRESS, DOMAIN
from .runtime import PandaEslRuntimeData

TO_REDACT = [CONF_ADDRESS, "address"]


def _serialize(value: Any) -> Any:
    """Return JSON-serializable diagnostics data."""
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(item) for item in value]
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime: PandaEslRuntimeData | None = getattr(entry, "runtime_data", None)
    store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    if isinstance(store, dict):
        store = {
            key: value
            for key, value in store.items()
            if key not in {"last_image_data", "write_debouncer"}
        }

    runtime_diagnostics: dict[str, Any] = {}
    if runtime is not None:
        runtime_diagnostics = _serialize(runtime.state)
        runtime_diagnostics["device_profile"] = _serialize(runtime.profile)

    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
            "version": entry.version,
            "minor_version": entry.minor_version,
        },
        "runtime": async_redact_data(
            runtime_diagnostics,
            TO_REDACT,
        ),
        "store": async_redact_data(_serialize(store), TO_REDACT),
    }
