"""Data models for PANDA ESL advertisements."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from .const import (
    ALI_ESL_SERVICE_UUID,
    ETAG_525_SERVICE_UUID,
    ETAG_LOCAL_NAME_PREFIX,
    KNOWN_TEST_ADDRESS,
    KNOWN_TEST_NAME,
    LEGACY_FFE0_SERVICE_UUID,
    NORDIC_UART_SERVICE_UUID,
    PANDA_SERVICE_UUID,
)


def _normalize_address(address: str) -> str:
    """Normalize a BLE MAC address."""
    return address.upper()


def _address_bytes(address: str) -> bytes | None:
    """Return address bytes, or None if the address is not a public MAC."""
    parts = address.split(":")
    if len(parts) != 6:
        return None
    try:
        return bytes(int(part, 16) for part in parts)
    except ValueError:
        return None


def _service_info_name(service_info: BluetoothServiceInfoBleak) -> str:
    """Return the best available advertisement name."""
    return service_info.name or getattr(service_info, "local_name", None) or ""


def _service_uuid_set(service_info: BluetoothServiceInfoBleak) -> set[str]:
    """Return normalized service UUIDs from an advertisement."""
    return {uuid.lower() for uuid in service_info.service_uuids}


def _manufacturer_data_hex(manufacturer_data: dict[int, bytes]) -> dict[int, str]:
    """Return manufacturer data payloads as hex strings."""
    return {
        manufacturer_id: bytes(payload).hex()
        for manufacturer_id, payload in sorted(manufacturer_data.items())
    }


def _payload_string(payload: dict[str, Any], key: str) -> str | None:
    """Return a string payload value when present."""
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _payload_int(payload: dict[str, Any], key: str) -> int | None:
    """Return an integer payload value when present."""
    value = payload.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def manufacturer_data_echoes_address(
    address: str, manufacturer_data: dict[int, bytes]
) -> bool:
    """Return true if manufacturer data contains this device's public MAC bytes.

    The observed ETAG advertises the first two MAC bytes as the little-endian
    manufacturer ID and the remaining four bytes as manufacturer payload.
    """
    addr_bytes = _address_bytes(address)
    if addr_bytes is None:
        return False

    for manufacturer_id, payload in manufacturer_data.items():
        prefix = bytes((manufacturer_id & 0xFF, (manufacturer_id >> 8) & 0xFF))
        if prefix + bytes(payload) == addr_bytes:
            return True
    return False


def service_info_supported(service_info: BluetoothServiceInfoBleak) -> bool:
    """Return true if a Bluetooth advertisement looks like a PANDA ESL tag."""
    address = _normalize_address(service_info.address)
    name = _service_info_name(service_info)
    service_uuids = _service_uuid_set(service_info)

    if address == KNOWN_TEST_ADDRESS:
        return True
    if name == KNOWN_TEST_NAME:
        return True
    if name.startswith(ETAG_LOCAL_NAME_PREFIX) and PANDA_SERVICE_UUID in service_uuids:
        return True
    if name.startswith(ETAG_LOCAL_NAME_PREFIX) and ETAG_525_SERVICE_UUID in service_uuids:
        return True
    if PANDA_SERVICE_UUID in service_uuids and ALI_ESL_SERVICE_UUID in service_uuids:
        return True
    if name.startswith(ETAG_LOCAL_NAME_PREFIX) and manufacturer_data_echoes_address(
        address, service_info.manufacturer_data
    ):
        return True
    return False


def service_info_matches_target(
    service_info: BluetoothServiceInfoBleak, target_address: str
) -> bool:
    """Return true if an advertisement matches this configured tag."""
    if _normalize_address(service_info.address) == _normalize_address(target_address):
        return True
    return service_info_supported(service_info)


def service_info_interesting(
    service_info: BluetoothServiceInfoBleak, target_address: str
) -> bool:
    """Return true if an advertisement is useful scan context for this tag."""
    address = _normalize_address(service_info.address)
    name = _service_info_name(service_info)
    service_uuids = _service_uuid_set(service_info)
    interesting_names = ("ETAG-", "HOLY", "525", "530", "534")

    return (
        service_info_matches_target(service_info, target_address)
        or name.startswith(interesting_names)
        or PANDA_SERVICE_UUID in service_uuids
        or ALI_ESL_SERVICE_UUID in service_uuids
        or ETAG_525_SERVICE_UUID in service_uuids
        or LEGACY_FFE0_SERVICE_UUID in service_uuids
        or NORDIC_UART_SERVICE_UUID in service_uuids
        or manufacturer_data_echoes_address(
            _normalize_address(target_address), service_info.manufacturer_data
        )
    )


def summarize_scan(
    service_infos: Iterable[BluetoothServiceInfoBleak],
    target_address: str,
    limit: int = 12,
) -> tuple[int, list[dict[str, Any]]]:
    """Summarize visible BLE devices relevant to this tag."""
    service_info_list = list(service_infos)
    candidates_by_address: dict[str, dict[str, Any]] = {}
    for service_info in service_info_list:
        if not service_info_interesting(service_info, target_address):
            continue

        address = _normalize_address(service_info.address)
        candidates_by_address[address] = {
            "address": address,
            "name": _service_info_name(service_info) or None,
            "rssi": service_info.rssi,
            "source": getattr(service_info, "source", None),
            "address_type": getattr(service_info, "address_type", None),
            "service_uuids": sorted(_service_uuid_set(service_info)),
            "manufacturer_data": _manufacturer_data_hex(
                service_info.manufacturer_data
            ),
            "supported": service_info_supported(service_info),
        }

    target = _normalize_address(target_address)
    candidates = sorted(
        candidates_by_address.values(),
        key=lambda candidate: (
            candidate["address"] != target,
            candidate["name"] or "",
            candidate["address"],
        ),
    )
    return len(service_info_list), candidates[:limit]


def title_from_service_info(service_info: BluetoothServiceInfoBleak) -> str:
    """Build a human-readable title for a discovered tag."""
    name = _service_info_name(service_info)
    if name:
        return name
    return f"PANDA ESL {service_info.address[-8:].replace(':', '')}"


@dataclass
class PandaEslState:
    """Runtime state derived from BLE advertisements and optional GATT probes."""

    address: str
    name: str | None = None
    local_name: str | None = None
    rssi: int | None = None
    source: str | None = None
    service_uuids: list[str] = field(default_factory=list)
    manufacturer_data: dict[int, str] = field(default_factory=dict)
    last_seen: datetime | None = None
    detection_count: int = 0
    present: bool = False
    last_scan: datetime | None = None
    last_scan_error: str | None = None
    last_scan_result: str | None = None
    last_scan_discovered_devices: int | None = None
    last_scan_candidates: list[dict[str, Any]] = field(default_factory=list)
    last_probe: datetime | None = None
    last_probe_error: str | None = None
    gatt_services: list[dict[str, Any]] = field(default_factory=list)
    last_write: datetime | None = None
    last_write_error: str | None = None
    last_write_result: str | None = None
    last_write_details: list[dict[str, Any]] = field(default_factory=list)
    write_action_results: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Configurable protocol experiment settings. These are intentionally runtime-only;
    # once the correct values are found they can be promoted to stable options.
    experiment_plane_byte_count: int = 4000
    experiment_chunk_payload_size: int = 200
    experiment_write_delay_ms: int = 15
    experiment_fill_bit_pair: str = "00"
    experiment_plane_order: str = "2_then_1"
    experiment_preamble: str = "standard"
    experiment_single_plane_id: int = 1
    experiment_single_plane_bit: int = 0

    @classmethod
    def from_service_info(cls, service_info: BluetoothServiceInfoBleak) -> "PandaEslState":
        """Create state from a BluetoothServiceInfoBleak."""
        state = cls(address=_normalize_address(service_info.address))
        state.update_from_service_info(service_info)
        return state

    def update_from_service_info(self, service_info: BluetoothServiceInfoBleak) -> None:
        """Update advertisement-derived fields."""
        self.address = _normalize_address(service_info.address)
        self.name = service_info.name
        self.local_name = getattr(service_info, "local_name", None)
        self.rssi = service_info.rssi
        self.source = getattr(service_info, "source", None)
        self.service_uuids = sorted(uuid.lower() for uuid in service_info.service_uuids)
        self.manufacturer_data = _manufacturer_data_hex(service_info.manufacturer_data)
        self.last_seen = datetime.now(timezone.utc)
        self.detection_count += 1
        self.present = True

    def update_from_scanner_payload(
        self, payload: dict[str, Any], source: str
    ) -> None:
        """Update state from an ESPHome ble_scanner JSON payload."""
        address = _payload_string(payload, "address")
        if address:
            self.address = _normalize_address(address)

        name = _payload_string(payload, "name")
        if name:
            self.name = name
            self.local_name = name

        rssi = _payload_int(payload, "rssi")
        if rssi is not None:
            self.rssi = rssi

        service_uuids = payload.get("service_uuids")
        if isinstance(service_uuids, list):
            self.service_uuids = sorted(
                str(uuid).lower() for uuid in service_uuids if uuid
            )

        manufacturer_data = payload.get("manufacturer_data")
        if isinstance(manufacturer_data, dict):
            self.manufacturer_data = {
                str(key): str(value) for key, value in manufacturer_data.items()
            }

        self.source = source
        self.last_seen = datetime.now(timezone.utc)
        self.detection_count += 1
        self.present = True

    def mark_unavailable(self) -> None:
        """Mark the device unavailable in Bluetooth cache."""
        self.present = False

    def update_scan(
        self,
        result: str,
        error: str | None = None,
        *,
        discovered_devices: int | None = None,
        candidates: list[dict[str, Any]] | None = None,
    ) -> None:
        """Update active scan result data."""
        self.last_scan = datetime.now(timezone.utc)
        self.last_scan_result = result
        self.last_scan_error = error
        if discovered_devices is not None:
            self.last_scan_discovered_devices = discovered_devices
        if candidates is not None:
            self.last_scan_candidates = candidates

    def update_probe(
        self, services: list[dict[str, Any]], error: str | None = None
    ) -> None:
        """Update GATT probe data."""
        self.last_probe = datetime.now(timezone.utc)
        self.last_probe_error = error
        self.gatt_services = services

    def update_write(
        self,
        result: str,
        error: str | None = None,
        *,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        """Update write/action diagnostics without being overwritten by scans."""
        self.last_write = datetime.now(timezone.utc)
        self.last_write_result = result
        self.last_write_error = error
        if details is not None:
            self.last_write_details = details

    def update_write_action(
        self,
        action_key: str,
        result: str,
        error: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Update global and per-button write diagnostics."""
        detail_list = [details] if details is not None else []
        self.update_write(result, error, details=detail_list)
        timestamp = self.last_write.isoformat() if self.last_write else None
        attrs: dict[str, Any] = {
            "last_result": result,
            "last_error": error,
            "last_write": timestamp,
        }
        if details:
            compact_keys = (
                "color",
                "test_image",
                "plane_strategy",
                "canvas_width",
                "canvas_height",
                "plane_byte_count",
                "chunk_payload_size",
                "write_delay_ms",
                "preamble",
                "packet_count",
                "image_packets_written",
                "bytes_written",
                "notification_count",
                "protocol_variant",
                "trace_enabled",
                "trace_file",
                "trace_error",
                "trace_started_at",
                "trace_duration_ms",
                "trace_packet_count",
                "trace_notification_count",
                "trace_packets_with_notifications",
                "trace_packets_without_notifications",
                "threshold",
                "red_threshold",
                "pixel_counts",
                "notes",
            )
            for key in compact_keys:
                if key in details:
                    attrs[key] = details[key]
        self.write_action_results[action_key] = attrs

    def update_experiment_setting(self, key: str, value: Any) -> None:
        """Update a runtime experiment setting."""
        setattr(self, key, value)

    @property
    def display_name(self) -> str:
        """Return the best known display name."""
        return self.name or self.local_name or f"PANDA ESL {self.address[-8:]}"
