"""The PANDA ESL integration."""

from __future__ import annotations

import asyncio
from functools import partial
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_DEBOUNCE_MS,
    CONF_DISCOVERED_NAME,
    CONF_PREVENT_DUPLICATE_SEND,
    CONF_RETRY_COUNT,
    CONF_WRITE_DELAY_MS,
    DEFAULT_DEBOUNCE_MS,
    DEFAULT_PREVENT_DUPLICATE_SEND,
    DEFAULT_RETRY_COUNT,
    DEFAULT_WRITE_DELAY_MS,
    DOMAIN,
    ETAG_SERVICE_UUID,
    MANUFACTURER,
    MAX_RETRY_COUNT,
    PACKET_NOTIFICATION_CAPTURE,
    PANDA_SERVICE_UUID,
    WRITE_LOCK,
)
from .models import PandaEslState, service_info_matches_target, title_from_service_info
from .profiles import device_profile_from_names
from .renderer import blank_png, render_service_image
from .runtime import (
    PandaEslRuntimeData,
    async_write_rendered_packets,
    build_packets_from_rendered_image,
    update_from_service_info,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.IMAGE,
    Platform.SENSOR,
    Platform.SWITCH,
]
_SERVICE_LOCK = "__service_lock"
_SERVICES_REGISTERED = "__services_registered"

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Any(
            None,
            {
                vol.Required(CONF_ADDRESS): cv.string,
                vol.Optional(CONF_NAME): cv.string,
            },
        )
    },
    extra=vol.ALLOW_EXTRA,
)

_COMMON_WRITE_SERVICE_SCHEMA = {
    vol.Required("payload"): cv.ensure_list,
    vol.Optional("rotate", default=0): vol.All(
        vol.Coerce(int), vol.In([0, 90, 180, 270])
    ),
    vol.Optional("background", default="white"): vol.All(
        cv.string, vol.Lower, vol.In(["white", "black", "red", "yellow"])
    ),
    vol.Optional("threshold", default=128): vol.All(
        vol.Coerce(int), vol.Range(min=0, max=255)
    ),
    vol.Optional("red_threshold", default=128): vol.All(
        vol.Coerce(int), vol.Range(min=0, max=255)
    ),
    vol.Optional("dry_run", default=False): cv.boolean,
}
WRITE_SERVICE_SCHEMA = vol.Schema(
    _COMMON_WRITE_SERVICE_SCHEMA,
    extra=vol.ALLOW_EXTRA,
)
WRITE_GUARDED_SERVICE_SCHEMA = vol.Schema(
    {
        **_COMMON_WRITE_SERVICE_SCHEMA,
        vol.Optional("debounce_override_ms"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=120000)
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up PANDA ESL YAML imports."""
    hass.data.setdefault(DOMAIN, {})
    _async_register_services_once(hass)

    if DOMAIN not in config or config[DOMAIN] is None:
        return True

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "import"},
            data=config[DOMAIN],
        )
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PANDA ESL from a config entry."""
    address = entry.data[CONF_ADDRESS]
    configured_name = entry.data.get(CONF_NAME) or entry.title
    last_service_info = bluetooth.async_last_service_info(
        hass, address, connectable=False
    )

    if last_service_info is not None:
        state = PandaEslState.from_service_info(last_service_info)
        name = configured_name or title_from_service_info(last_service_info)
    else:
        state = PandaEslState(address=address, name=configured_name)
        name = configured_name

    profile = device_profile_from_names(
        last_service_info.name if last_service_info is not None else None,
        (
            getattr(last_service_info, "local_name", None)
            if last_service_info is not None
            else None
        ),
        entry.data.get(CONF_DISCOVERED_NAME),
    )
    if profile is None:
        _LOGGER.error(
            "PANDA ESL %s does not advertise a supported ETAG-525 or ETAG-526 identifier",
            address,
        )
        return False

    coordinator: DataUpdateCoordinator[PandaEslState] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{address}",
    )
    blank_image = blank_png(profile.width, profile.height)
    image_coordinator: DataUpdateCoordinator[bytes] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{address}_image",
    )
    preview_coordinator: DataUpdateCoordinator[bytes] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{address}_preview",
    )
    runtime = PandaEslRuntimeData(
        state=state,
        coordinator=coordinator,
        image_coordinator=image_coordinator,
        preview_coordinator=preview_coordinator,
        profile=profile,
        packet_notification_capture=bool(
            entry.data.get(PACKET_NOTIFICATION_CAPTURE, False)
        ),
    )
    entry.runtime_data = runtime
    coordinator.async_set_updated_data(state)
    image_coordinator.async_set_updated_data(blank_image)
    preview_coordinator.async_set_updated_data(blank_image)

    device_entry = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(CONNECTION_BLUETOOTH, address)},
        identifiers={(DOMAIN, address)},
        manufacturer=MANUFACTURER,
        model=profile.model,
        name=name,
    )

    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data.setdefault(_SERVICE_LOCK, asyncio.Lock())
    options = {**entry.data, **entry.options}
    domain_data[entry.entry_id] = {
        "address": address,
        "device_id": device_entry.id,
        "device_profile": profile.key,
        "last_image_data": None,
        "write_pending": False,
        WRITE_LOCK: bool(entry.data.get(WRITE_LOCK, False)),
        PACKET_NOTIFICATION_CAPTURE: bool(
            entry.data.get(PACKET_NOTIFICATION_CAPTURE, False)
        ),
        "write_debouncer": Debouncer(
            hass,
            _LOGGER,
            cooldown=int(options.get(CONF_DEBOUNCE_MS, DEFAULT_DEBOUNCE_MS)) / 1000,
            immediate=False,
        ),
    }
    _async_register_services_once(hass)

    @callback
    def _async_discovered_device(
        service_info: BluetoothServiceInfoBleak, change: BluetoothChange
    ) -> None:
        """Subscribe to Bluetooth updates for this tag."""
        if not service_info_matches_target(service_info, address):
            return
        update_from_service_info(runtime, service_info)

    @callback
    def _async_unavailable() -> None:
        """Handle the tag leaving the Bluetooth cache."""
        if not runtime.availability_logged:
            _LOGGER.info("PANDA ESL %s is unavailable", address)
            runtime.availability_logged = True
        runtime.state.mark_unavailable()
        runtime.coordinator.async_set_updated_data(runtime.state)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_discovered_device,
            {"address": address, "connectable": False},
            BluetoothScanningMode.ACTIVE,
            scan_interval=300,
            scan_duration=10,
        )
    )
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_discovered_device,
            {"service_uuid": PANDA_SERVICE_UUID, "connectable": False},
            BluetoothScanningMode.ACTIVE,
        )
    )
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_discovered_device,
            {"service_uuid": ETAG_SERVICE_UUID, "connectable": False},
            BluetoothScanningMode.ACTIVE,
        )
    )
    entry.async_on_unload(
        bluetooth.async_track_unavailable(
            hass, _async_unavailable, address, connectable=False
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _async_register_services_once(hass: HomeAssistant) -> None:
    """Register PANDA ESL write services once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_SERVICES_REGISTERED):
        return

    async def write_service(service: ServiceCall) -> None:
        await _async_handle_write_service(hass, service, guarded=False)

    async def write_guarded_service(service: ServiceCall) -> None:
        await _async_handle_write_service(hass, service, guarded=True)

    hass.services.async_register(
        DOMAIN,
        "write",
        write_service,
        schema=WRITE_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "write_guarded",
        write_guarded_service,
        schema=WRITE_GUARDED_SERVICE_SCHEMA,
    )
    domain_data[_SERVICES_REGISTERED] = True


def _service_validation_error(
    translation_key: str,
    message: str,
    **translation_placeholders: str,
) -> ServiceValidationError:
    """Return a translated service validation error."""
    return ServiceValidationError(
        message,
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders=translation_placeholders,
    )


def _service_error(
    translation_key: str,
    message: str,
    **translation_placeholders: str,
) -> HomeAssistantError:
    """Return a translated service error."""
    return HomeAssistantError(
        message,
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders=translation_placeholders,
    )


def _normalize_device_ids(hass: HomeAssistant, service: ServiceCall) -> list[str]:
    """Normalize device_id from service data/target."""
    device_ids = service.data.get("device_id")
    if device_ids is None:
        target = getattr(service, "target", None) or {}
        device_ids = target.get("device_id") if isinstance(target, dict) else None

    if isinstance(device_ids, str):
        return [device_ids]
    if isinstance(device_ids, list):
        return [str(device_id) for device_id in device_ids]

    loaded_device_ids = [
        store["device_id"]
        for entry_id, store in hass.data.get(DOMAIN, {}).items()
        if isinstance(store, dict)
        and not str(entry_id).startswith("__")
        and "device_id" in store
    ]
    if len(loaded_device_ids) == 1:
        return loaded_device_ids

    raise _service_validation_error(
        "target_device_required",
        "Target device_id is required for panda_esl.write",
    )


async def _entry_id_from_device_id(hass: HomeAssistant, device_id: str) -> str:
    """Resolve a Home Assistant device id to a loaded PANDA ESL entry id."""
    for entry_id, store in hass.data.get(DOMAIN, {}).items():
        if (
            isinstance(store, dict)
            and not str(entry_id).startswith("__")
            and store.get("device_id") == device_id
        ):
            return str(entry_id)

    device_entry = dr.async_get(hass).async_get(device_id)
    if device_entry is not None:
        for config_entry_id in device_entry.config_entries:
            config_entry = hass.config_entries.async_get_entry(config_entry_id)
            if config_entry is not None and config_entry.domain == DOMAIN:
                return config_entry_id

    raise _service_validation_error(
        "device_not_loaded",
        f"No loaded PANDA ESL config entry has device_id {device_id!r}",
        device_id=device_id,
    )


def _entry_store(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    """Return stored runtime data for an entry id."""
    store = hass.data.get(DOMAIN, {}).get(entry_id)
    if not isinstance(store, dict):
        raise _service_error(
            "entry_not_loaded",
            f"PANDA ESL entry {entry_id!r} is not loaded",
            entry_id=entry_id,
        )
    return store


def _write_operation_lock(hass: HomeAssistant) -> asyncio.Lock:
    """Return the global PANDA write operation lock."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    lock = domain_data.get(_SERVICE_LOCK)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        domain_data[_SERVICE_LOCK] = lock
    return lock


async def _async_build_service_context(
    hass: HomeAssistant,
    service: ServiceCall,
    entry_id: str,
    *,
    guarded: bool,
) -> dict[str, Any]:
    """Render a service payload and build PANDA packets."""
    store = _entry_store(hass, entry_id)
    config_entry = hass.config_entries.async_get_entry(entry_id)
    if config_entry is None:
        raise _service_error(
            "entry_missing",
            f"PANDA ESL entry {entry_id!r} no longer exists",
            entry_id=entry_id,
        )
    runtime: PandaEslRuntimeData = config_entry.runtime_data

    threshold = int(service.data.get("threshold", 128))
    red_threshold = int(service.data.get("red_threshold", 128))
    render_job = partial(
        render_service_image,
        hass,
        dict(service.data),
        runtime.profile.width,
        runtime.profile.height,
    )
    rendered_image = await hass.async_add_executor_job(render_job)
    packet_job = partial(
        build_packets_from_rendered_image,
        rendered_image,
        threshold=threshold,
        red_threshold=red_threshold,
        profile=runtime.profile,
    )
    packets, current_image_data, render_details = await hass.async_add_executor_job(
        packet_job
    )
    runtime.preview_coordinator.async_set_updated_data(current_image_data)

    options = {**config_entry.data, **config_entry.options}
    action_key = "service_write_guarded" if guarded else "service_write"
    details = {
        **render_details,
        "service": "write_guarded" if guarded else "write",
        "dry_run": bool(service.data.get("dry_run", False)),
        "payload_elements": len(service.data.get("payload", [])),
    }
    return {
        "entry_id": entry_id,
        "store": store,
        "runtime": runtime,
        "options": options,
        "packets": packets,
        "current_image_data": current_image_data,
        "action_key": action_key,
        "details": details,
        "address": runtime.state.address,
    }


def _update_service_write_action(
    runtime: PandaEslRuntimeData,
    action_key: str,
    result: str,
    *,
    details: dict[str, Any] | None = None,
) -> None:
    """Record a service write result."""
    runtime.state.update_write_action(action_key, result, details=details)
    runtime.coordinator.async_set_updated_data(runtime.state)


async def _async_execute_service_write(
    hass: HomeAssistant,
    context: dict[str, Any],
) -> None:
    """Execute a rendered PANDA service write with retries."""
    runtime: PandaEslRuntimeData = context["runtime"]
    store = context["store"]
    options = context["options"]
    retry_count = max(
        0,
        min(int(options.get(CONF_RETRY_COUNT, DEFAULT_RETRY_COUNT)), MAX_RETRY_COUNT),
    )
    write_delay_ms = int(options.get(CONF_WRITE_DELAY_MS, DEFAULT_WRITE_DELAY_MS))

    await async_write_rendered_packets(
        hass,
        runtime,
        packets=context["packets"],
        action_key=context["action_key"],
        result_name="write_service_ok",
        details=context["details"],
        write_delay_ms=write_delay_ms,
        retry_count=retry_count,
    )
    runtime.image_coordinator.async_set_updated_data(context["current_image_data"])
    store["last_image_data"] = context["current_image_data"]


async def _async_run_guarded_write(
    hass: HomeAssistant,
    context: dict[str, Any],
) -> None:
    """Run a physical write under the global write lock."""
    store = context["store"]
    runtime: PandaEslRuntimeData = context["runtime"]
    async with _write_operation_lock(hass):
        store["write_pending"] = False
        if store.get(WRITE_LOCK, False):
            _LOGGER.info("Write lock active for %s; skipping BLE write", context["address"])
            _update_service_write_action(
                runtime,
                context["action_key"],
                "write_service_skipped_locked",
                details=context["details"],
            )
            return
        await _async_execute_service_write(hass, context)


def _cancel_pending_write(store: dict[str, Any]) -> None:
    """Cancel a pending debounced write for an entry."""
    if not store.get("write_pending"):
        return
    debouncer = store.get("write_debouncer")
    if debouncer is not None:
        debouncer.async_cancel()
    store["write_pending"] = False


async def _async_handle_write_service(
    hass: HomeAssistant,
    service: ServiceCall,
    *,
    guarded: bool,
) -> None:
    """Handle panda_esl.write and panda_esl.write_guarded."""
    device_ids = _normalize_device_ids(hass, service)
    dry_run = bool(service.data.get("dry_run", False))

    for device_id in device_ids:
        entry_id = await _entry_id_from_device_id(hass, device_id)
        context = await _async_build_service_context(
            hass, service, entry_id, guarded=guarded
        )
        store = context["store"]
        runtime: PandaEslRuntimeData = context["runtime"]

        if guarded:
            prevent_duplicate = bool(
                context["options"].get(
                    CONF_PREVENT_DUPLICATE_SEND,
                    DEFAULT_PREVENT_DUPLICATE_SEND,
                )
            )
            if prevent_duplicate and context["current_image_data"] == store.get(
                "last_image_data"
            ):
                _LOGGER.info(
                    "Skipping duplicate PANDA ESL image for %s", context["address"]
                )
                _update_service_write_action(
                    runtime,
                    context["action_key"],
                    "write_service_skipped_duplicate",
                    details=context["details"],
                )
                continue

        store["last_image_data"] = context["current_image_data"]

        if dry_run:
            _update_service_write_action(
                runtime,
                context["action_key"],
                "write_service_dry_run",
                details=context["details"],
            )
            continue

        if guarded and store.get(WRITE_LOCK, False):
            _LOGGER.info("Write lock active for %s; skipping BLE write", context["address"])
            _update_service_write_action(
                runtime,
                context["action_key"],
                "write_service_skipped_locked",
                details=context["details"],
            )
            continue

        if not guarded:
            _cancel_pending_write(store)
            await _async_run_guarded_write(hass, context)
            continue

        debounce_ms = int(
            service.data.get(
                "debounce_override_ms",
                context["options"].get(CONF_DEBOUNCE_MS, DEFAULT_DEBOUNCE_MS),
            )
        )
        debouncer: Debouncer = store["write_debouncer"]
        if debounce_ms > 0:
            new_cooldown = debounce_ms / 1000
            if debouncer.cooldown != new_cooldown:
                debouncer.cooldown = new_cooldown
            if store.get("write_pending"):
                _LOGGER.info(
                    "Cancelled pending write for %s; rescheduled with %sms delay",
                    context["address"],
                    debounce_ms,
                )
            store["write_pending"] = True
            debouncer.function = partial(_async_run_guarded_write, hass, context)
            debouncer.async_schedule_call()
            _update_service_write_action(
                runtime,
                context["action_key"],
                "write_service_debounced",
                details={**context["details"], "debounce_ms": debounce_ms},
            )
        else:
            _cancel_pending_write(store)
            await _async_run_guarded_write(hass, context)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    store = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if isinstance(store, dict):
        debouncer = store.get("write_debouncer")
        if debouncer is not None:
            debouncer.async_shutdown()

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate PANDA ESL config entries."""
    if entry.version == 1 and entry.minor_version < 2:
        data = {**entry.data}
        data.setdefault(CONF_NAME, entry.title)
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            version=1,
            minor_version=2,
        )
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow removing the device associated with this config entry."""
    return (DOMAIN, entry.data[CONF_ADDRESS]) in device_entry.identifiers
