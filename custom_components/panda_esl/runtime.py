"""Minimal runtime helpers for PANDA ESL writes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import json
import logging
from pathlib import Path
import time
from typing import Any

from bleak import BleakClient
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from PIL import Image

from .const import DOMAIN, TRACE_DIRECTORY
from .models import PandaEslState

_LOGGER = logging.getLogger(__name__)

PANDA_FFE1_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

# Empirically verified for the PANDA ESL-21R / ETAG stock firmware.
PANDA_PLANE_BYTE_COUNT = 4096  # 256 x 128 / 8
PANDA_CHUNK_PAYLOAD_SIZE = 50
PANDA_WRITE_DELAY_MS = 150
PANDA_CANVAS_WIDTH = 256
PANDA_CANVAS_HEIGHT = 128
PANDA_ACK_MAX_ATTEMPTS = 2
PANDA_ACK_CHUNK_TIMEOUT_S = 5.0
PANDA_ACK_FINAL_TIMEOUT_S = 10.0
PANDA_ACK_INTER_PACKET_DELAY_MS = 10
PANDA_FINAL_ACK = bytes.fromhex("91040019")

_STANDARD_PREAMBLE: list[bytes] = [
    bytes.fromhex("ac05ca"),
    bytes.fromhex("ac1100112233445566778899112233445566ca"),
    bytes.fromhex("ac07ca"),
]


@dataclass
class PandaEslRuntimeData:
    """Runtime data stored on the config entry."""

    state: PandaEslState
    coordinator: DataUpdateCoordinator[PandaEslState]
    image_coordinator: DataUpdateCoordinator[bytes]
    preview_coordinator: DataUpdateCoordinator[bytes]
    packet_notification_capture: bool = False
    availability_logged: bool = False


def _safe_filename_part(value: str) -> str:
    """Return a conservative filename segment."""
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_")


def _decode_packet(packet: bytes) -> dict[str, Any]:
    """Decode the PANDA packet envelope enough for trace inspection."""
    decoded: dict[str, Any] = {"enveloped": False}
    if len(packet) < 3 or packet[0] != 0xAC or packet[-1] != 0xCA:
        return decoded

    command = packet[1]
    decoded = {
        "enveloped": True,
        "command": f"0x{command:02x}",
    }
    if command == 0x01 and len(packet) >= 10:
        decoded.update(
            {
                "kind": "image_chunk",
                "plane": packet[2],
                "chunk_index": (packet[3] << 8) | packet[4],
                "chunk_total": (packet[5] << 8) | packet[6],
                "flags": packet[7],
                "declared_payload_len": packet[8],
                "actual_payload_len": max(0, len(packet) - 10),
            }
        )
    elif command == 0x03:
        decoded["kind"] = "commit"
    elif command in (0x05, 0x07, 0x11):
        decoded["kind"] = "preamble"
    else:
        decoded["kind"] = "unknown"
    return decoded


def _progress_ack_value(data: bytes) -> int | None:
    """Return the PANDA chunk progress value from a notification."""
    if len(data) != 6 or data[0] != 0x91 or data[1] != 0x02 or data[-1] != 0x19:
        return None
    return int.from_bytes(data[2:5], "little")


def _write_packet_trace_file(
    config_path: str,
    metadata: dict[str, Any],
    packet_events: list[dict[str, Any]],
    notifications: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    """Write a packet notification trace file and return its path."""
    trace_dir = Path(config_path) / TRACE_DIRECTORY
    trace_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _safe_filename_part(str(metadata["started_at"]).replace("+00:00", "Z"))
    address = _safe_filename_part(str(metadata.get("address", "unknown")))
    action = _safe_filename_part(str(metadata.get("action_key", "write")))
    path = trace_dir / f"{timestamp}_{address}_{action}.jsonl"

    with path.open("w", encoding="utf-8", newline="\n") as trace_file:
        trace_file.write(
            json.dumps({"type": "metadata", **metadata}, sort_keys=True) + "\n"
        )
        for event in packet_events:
            trace_file.write(
                json.dumps({"type": "packet", **event}, sort_keys=True) + "\n"
            )
        assigned_notification_ids = {
            notification["id"]
            for event in packet_events
            for notification in event.get("notifications", [])
        }
        for notification in notifications:
            if notification["id"] in assigned_notification_ids:
                continue
            trace_file.write(
                json.dumps(
                    {"type": "unassigned_notification", **notification},
                    sort_keys=True,
                )
                + "\n"
            )
        trace_file.write(
            json.dumps({"type": "summary", **summary}, sort_keys=True) + "\n"
        )

    return str(path)


def update_from_service_info(
    runtime: PandaEslRuntimeData, service_info: BluetoothServiceInfoBleak
) -> None:
    """Apply an advertisement update and notify entities."""
    if runtime.availability_logged:
        _LOGGER.info("PANDA ESL %s is available again", service_info.address)
        runtime.availability_logged = False
    runtime.state.update_from_service_info(service_info)
    runtime.coordinator.async_set_updated_data(runtime.state)


def _translated_error(
    translation_key: str,
    message: str,
    **translation_placeholders: Any,
) -> HomeAssistantError:
    """Return a translated Home Assistant error."""
    return HomeAssistantError(
        message,
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders={
            key: str(value) for key, value in translation_placeholders.items()
        },
    )


def _frame_image_chunks(plane: int, payload: bytes) -> list[bytes]:
    """Frame one image plane into vendor AC 01 packets."""
    total = max(1, (len(payload) + PANDA_CHUNK_PAYLOAD_SIZE - 1) // PANDA_CHUNK_PAYLOAD_SIZE)
    packets: list[bytes] = []
    for index in range(total):
        chunk = payload[index * PANDA_CHUNK_PAYLOAD_SIZE : (index + 1) * PANDA_CHUNK_PAYLOAD_SIZE]
        packets.append(
            bytes(
                [
                    0xAC,
                    0x01,
                    plane & 0xFF,
                    (index >> 8) & 0xFF,
                    index & 0xFF,
                    (total >> 8) & 0xFF,
                    total & 0xFF,
                    0x00,
                    len(chunk) & 0xFF,
                ]
            )
            + chunk
            + b"\xCA"
        )
    return packets


def _build_fill_packets(color: str) -> list[bytes]:
    """Build reliable full-screen fill packets.

    Discovered color model:
      white -> plane 0 = 1, plane 1 = 0
      black -> plane 0 = 0
      red   -> plane 1 = 1
    """
    packets: list[bytes] = list(_STANDARD_PREAMBLE)
    if color == "white":
        packets += _frame_image_chunks(0, bytes([0xFF]) * PANDA_PLANE_BYTE_COUNT)
        packets += _frame_image_chunks(1, bytes([0x00]) * PANDA_PLANE_BYTE_COUNT)
    elif color == "black":
        packets += _frame_image_chunks(0, bytes([0x00]) * PANDA_PLANE_BYTE_COUNT)
    elif color == "red":
        packets += _frame_image_chunks(1, bytes([0xFF]) * PANDA_PLANE_BYTE_COUNT)
    else:
        raise ValueError(f"Unknown fill color: {color}")
    packets.append(bytes.fromhex("ac03ca"))
    return packets


_FONT_5X7: dict[str, tuple[str, ...]] = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
}


def _draw_text_5x7(
    pixels: list[list[int]], text: str, left: int, top: int, scale: int, color: int
) -> None:
    """Draw blocky 5x7 text into the test image."""
    x = left
    height = len(pixels)
    width = len(pixels[0]) if pixels else 0
    for ch in text.upper():
        glyph = _FONT_5X7.get(ch, _FONT_5X7[" "])
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit != "1":
                    continue
                for dy in range(scale):
                    py = top + gy * scale + dy
                    if not 0 <= py < height:
                        continue
                    for dx in range(scale):
                        px = x + gx * scale + dx
                        if 0 <= px < width:
                            pixels[py][px] = color
        x += 6 * scale


def _encode_pixels_plane01(pixels: list[list[int]]) -> tuple[bytes, bytes]:
    """Encode pixels for plane 0 black active-low and plane 1 red active-high.

    Pixel values: 0=white, 1=black, 2=red.
    Packing order: columns left-to-right, rows bottom-to-top, MSB first.
    """
    height = len(pixels)
    width = len(pixels[0]) if pixels else 0
    plane0 = bytearray()
    plane1 = bytearray()

    for x in range(width):
        bit_index = 0
        b0 = 0xFF
        b1 = 0x00
        for y in range(height - 1, -1, -1):
            color = pixels[y][x]
            mask = 1 << (7 - bit_index)
            if color == 1:  # black
                b0 &= (~mask) & 0xFF
                b1 &= (~mask) & 0xFF
            elif color == 2:  # red
                b0 |= mask
                b1 |= mask
            else:  # white
                b0 |= mask
                b1 &= (~mask) & 0xFF

            bit_index += 1
            if bit_index == 8:
                plane0.append(b0 & 0xFF)
                plane1.append(b1 & 0xFF)
                bit_index = 0
                b0 = 0xFF
                b1 = 0x00

        if bit_index:
            plane0.append(b0 & 0xFF)
            plane1.append(b1 & 0xFF)

    return bytes(plane0), bytes(plane1)


def _build_framed_pixels() -> list[list[int]]:
    """Build the current diagnostic framed image in displayed coordinates.

    Top/right borders are inset to avoid the bezel. The final image is flipped
    vertically before encoding because the panel displays the memory top-bottom.
    """
    width = PANDA_CANVAS_WIDTH
    height = PANDA_CANVAS_HEIGHT
    display_pixels = [[0 for _x in range(width)] for _y in range(height)]

    def draw_rect_frame(left: int, top: int, right: int, bottom: int, color: int, thickness: int = 1) -> None:
        for t in range(thickness):
            l = left + t
            r = right - t
            u = top + t
            b = bottom - t
            if l > r or u > b:
                break
            for x in range(l, r + 1):
                display_pixels[u][x] = color
                display_pixels[b][x] = color
            for y in range(u, b + 1):
                display_pixels[y][l] = color
                display_pixels[y][r] = color

    top_inset = 5
    right_inset = 5
    outer_left, outer_top = 0, top_inset
    outer_right, outer_bottom = width - 1 - right_inset, height - 1
    draw_rect_frame(outer_left, outer_top, outer_right, outer_bottom, color=1, thickness=2)
    draw_rect_frame(outer_left + 5, outer_top + 5, outer_right - 5, outer_bottom - 5, color=2, thickness=2)

    # Corner/orientation blocks in displayed coordinates.
    for yy in range(12, 18):
        for xx in range(10, 16):
            display_pixels[yy][xx] = 1
    for yy in range(12, 18):
        for xx in range(width - 22, width - 16):
            display_pixels[yy][xx] = 2
    for yy in range(height - 18, height - 12):
        for xx in range(10, 16):
            display_pixels[yy][xx] = 2
    for yy in range(height - 18, height - 12):
        for xx in range(width - 22, width - 16):
            display_pixels[yy][xx] = 1

    _draw_text_5x7(display_pixels, "FRAME", left=54, top=50, scale=4, color=1)

    return [display_pixels[height - 1 - y][:] for y in range(height)]


def _build_framed_packets() -> list[bytes]:
    plane0, plane1 = _encode_pixels_plane01(_build_framed_pixels())
    if len(plane0) != PANDA_PLANE_BYTE_COUNT or len(plane1) != PANDA_PLANE_BYTE_COUNT:
        raise ValueError(f"Unexpected plane sizes: {len(plane0)}, {len(plane1)}")
    packets: list[bytes] = list(_STANDARD_PREAMBLE)
    packets += _frame_image_chunks(0, plane0)
    packets += _frame_image_chunks(1, plane1)
    packets.append(bytes.fromhex("ac03ca"))
    return packets


def _image_color_to_pixel(
    red: int, green: int, blue: int, threshold: int, red_threshold: int
) -> int:
    """Map rendered RGB to PANDA's 0=white, 1=black, 2=red palette."""
    is_red_or_yellow = red > red_threshold and blue < red_threshold
    if is_red_or_yellow:
        return 2

    luminance = ((red * 38) + (green * 75) + (blue * 15)) >> 7
    if luminance < threshold:
        return 1
    return 0


def _quantized_preview_png(display_pixels: list[list[int]]) -> bytes:
    """Return a PNG preview of the actual PANDA three-color output."""
    height = len(display_pixels)
    width = len(display_pixels[0]) if display_pixels else 0
    image = Image.new("RGB", (width, height), "white")
    palette = {
        0: (255, 255, 255),
        1: (0, 0, 0),
        2: (255, 0, 0),
    }
    image.putdata(
        [palette.get(display_pixels[y][x], palette[0]) for y in range(height) for x in range(width)]
    )
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def build_packets_from_rendered_image(
    image: Image.Image,
    *,
    threshold: int = 128,
    red_threshold: int = 128,
) -> tuple[list[bytes], bytes, dict[str, Any]]:
    """Build PANDA packets from a rendered RGB image.

    Service payloads are drawn in displayed coordinates. Like the proven framed
    diagnostic image, the rendered pixels are vertically pre-flipped before the
    existing PANDA plane encoder sees them.
    """
    if image.size != (PANDA_CANVAS_WIDTH, PANDA_CANVAS_HEIGHT):
        image = image.resize((PANDA_CANVAS_WIDTH, PANDA_CANVAS_HEIGHT), Image.LANCZOS)

    rgb_image = image.convert("RGB")
    display_pixels: list[list[int]] = []
    counts = {"white": 0, "black": 0, "red": 0}
    for y in range(PANDA_CANVAS_HEIGHT):
        row: list[int] = []
        for x in range(PANDA_CANVAS_WIDTH):
            red, green, blue = rgb_image.getpixel((x, y))
            color = _image_color_to_pixel(red, green, blue, threshold, red_threshold)
            row.append(color)
            if color == 2:
                counts["red"] += 1
            elif color == 1:
                counts["black"] += 1
            else:
                counts["white"] += 1
        display_pixels.append(row)

    memory_pixels = [
        display_pixels[PANDA_CANVAS_HEIGHT - 1 - y][:] for y in range(PANDA_CANVAS_HEIGHT)
    ]
    plane0, plane1 = _encode_pixels_plane01(memory_pixels)
    if len(plane0) != PANDA_PLANE_BYTE_COUNT or len(plane1) != PANDA_PLANE_BYTE_COUNT:
        raise ValueError(f"Unexpected plane sizes: {len(plane0)}, {len(plane1)}")

    packets: list[bytes] = list(_STANDARD_PREAMBLE)
    packets += _frame_image_chunks(0, plane0)
    packets += _frame_image_chunks(1, plane1)
    packets.append(bytes.fromhex("ac03ca"))

    details: dict[str, Any] = {
        "canvas_width": PANDA_CANVAS_WIDTH,
        "canvas_height": PANDA_CANVAS_HEIGHT,
        "plane_strategy": "0_then_1",
        "threshold": threshold,
        "red_threshold": red_threshold,
        "pixel_counts": counts,
        "notes": "rendered service payload, yellow mapped to red, vertically pre-flipped",
    }
    return packets, _quantized_preview_png(display_pixels), details


async def _async_send_packets_attempt(
    hass: HomeAssistant,
    runtime: PandaEslRuntimeData,
    *,
    packets: list[bytes],
    action_key: str,
    result_name: str,
    details: dict[str, Any],
    write_delay_ms: int = PANDA_WRITE_DELAY_MS,
    attempt: int = 1,
    max_attempts: int = PANDA_ACK_MAX_ATTEMPTS,
) -> None:
    """Send packets using PANDA notification ACK-gated flow control."""
    address = runtime.state.address
    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        message = "No connectable BLE device handle is available"
        runtime.state.update_write_action(action_key, result_name + "_error", message)
        runtime.coordinator.async_set_updated_data(runtime.state)
        raise _translated_error("no_ble_device", message, address=address)

    capture_trace = runtime.packet_notification_capture
    trace_started_at = datetime.now(timezone.utc)
    trace_started_monotonic = time.monotonic()
    trace_packet_events: list[dict[str, Any]] = []
    trace_notifications: list[dict[str, Any]] = []
    current_packet_event: dict[str, Any] | None = None
    progress_cycles: list[set[int]] = [set()]
    last_progress_value: int | None = None
    final_ack_seen = False
    ack_event = asyncio.Event()
    notifications: list[str] = []
    client: BleakClient | None = None
    try:
        client = await establish_connection(BleakClient, ble_device, address)
        loop = asyncio.get_running_loop()

        def _record_notification(sender: str, data: bytes) -> None:
            nonlocal final_ack_seen, last_progress_value
            notification = {
                "id": len(trace_notifications),
                "relative_ms": round(
                    (time.monotonic() - trace_started_monotonic) * 1000, 3
                ),
                "sender": sender,
                "data_hex": data.hex(),
                "length": len(data),
            }
            trace_notifications.append(notification)
            notifications.append(notification["data_hex"])
            if current_packet_event is not None:
                current_packet_event["notifications"].append(notification)

            progress_value = _progress_ack_value(data)
            if progress_value is not None:
                if (
                    last_progress_value is not None
                    and progress_value < last_progress_value
                ):
                    progress_cycles.append(set())
                progress_cycles[-1].add(progress_value)
                last_progress_value = progress_value
                notification["ack_kind"] = "chunk_progress"
                notification["ack_value"] = progress_value
            elif data == PANDA_FINAL_ACK:
                final_ack_seen = True
                notification["ack_kind"] = "final"
            ack_event.set()

        def _notification_handler(_sender: Any, data: bytearray) -> None:
            loop.call_soon_threadsafe(
                _record_notification,
                str(_sender),
                bytes(data),
            )

        async def _wait_for_ack(
            predicate: Any,
            timeout: float,
            label: str,
        ) -> None:
            deadline = time.monotonic() + timeout
            while True:
                if predicate():
                    return
                ack_event.clear()
                if predicate():
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _translated_error(
                        "ack_timeout",
                        f"Timed out waiting for PANDA ACK: {label}",
                        label=label,
                    )
                try:
                    await asyncio.wait_for(ack_event.wait(), remaining)
                except TimeoutError as err:
                    raise _translated_error(
                        "ack_timeout",
                        f"Timed out waiting for PANDA ACK: {label}",
                        label=label,
                    ) from err

        async def _wait_for_chunk_progress(cycle: int, chunk_index: int) -> None:
            await _wait_for_ack(
                lambda: (
                    len(progress_cycles) > cycle
                    and chunk_index in progress_cycles[cycle]
                ),
                PANDA_ACK_CHUNK_TIMEOUT_S,
                f"cycle {cycle} chunk {chunk_index}",
            )

        async def _wait_for_final_ack() -> None:
            await _wait_for_ack(
                lambda: final_ack_seen,
                PANDA_ACK_FINAL_TIMEOUT_S,
                "final commit",
            )

        notify_started = False
        try:
            await client.start_notify(PANDA_FFE1_CHAR_UUID, _notification_handler)
            notify_started = True
            await asyncio.sleep(0.2)
        except Exception as err:  # noqa: BLE001
            notifications.append(f"notify_start_error:{type(err).__name__}:{err}")
            raise _translated_error(
                "notify_start_failed",
                f"Failed to start PANDA notifications for ACK flow: {err}",
                error=err,
            ) from err

        characteristic_info: dict[str, Any] = {}
        try:
            char = client.services.get_characteristic(PANDA_FFE1_CHAR_UUID)
        except Exception:
            char = None
        if char is not None:
            characteristic_info = {
                "properties": sorted(getattr(char, "properties", []) or []),
                "max_write_without_response_size": getattr(char, "max_write_without_response_size", None),
            }

        preamble_len = len(_STANDARD_PREAMBLE)
        image_packets_written = 0
        image_ack_cycle = -1
        for packet_index, packet in enumerate(packets):
            decoded_packet = _decode_packet(packet)
            expected_ack_cycle: int | None = None
            if decoded_packet.get("kind") == "image_chunk":
                if decoded_packet["chunk_index"] == 0:
                    image_ack_cycle += 1
                expected_ack_cycle = image_ack_cycle
            elif decoded_packet.get("kind") == "commit":
                final_ack_seen = False

            if capture_trace:
                if packet_index < preamble_len:
                    stage = "preamble"
                elif packet_index == len(packets) - 1:
                    stage = "final"
                else:
                    stage = "image"
                current_packet_event = {
                    "packet_index": packet_index,
                    "stage": stage,
                    "relative_start_ms": round(
                        (time.monotonic() - trace_started_monotonic) * 1000, 3
                    ),
                    "packet_len": len(packet),
                    "packet_hex": packet.hex(),
                    "decoded": decoded_packet,
                    "ack_cycle": expected_ack_cycle,
                    "notifications": [],
                }
            await client.write_gatt_char(PANDA_FFE1_CHAR_UUID, packet, response=False)
            if capture_trace and current_packet_event is not None:
                current_packet_event["relative_write_return_ms"] = round(
                    (time.monotonic() - trace_started_monotonic) * 1000, 3
                )
            if preamble_len <= packet_index < len(packets) - 1:
                image_packets_written += 1

            if decoded_packet.get("kind") == "image_chunk":
                assert expected_ack_cycle is not None
                await _wait_for_chunk_progress(
                    expected_ack_cycle,
                    int(decoded_packet["chunk_index"]),
                )
                if capture_trace and current_packet_event is not None:
                    current_packet_event["ack_received_ms"] = round(
                        (time.monotonic() - trace_started_monotonic) * 1000, 3
                    )
                if PANDA_ACK_INTER_PACKET_DELAY_MS:
                    await asyncio.sleep(PANDA_ACK_INTER_PACKET_DELAY_MS / 1000)
            elif decoded_packet.get("kind") == "commit":
                await _wait_for_final_ack()
                if capture_trace and current_packet_event is not None:
                    current_packet_event["ack_received_ms"] = round(
                        (time.monotonic() - trace_started_monotonic) * 1000, 3
                    )
            else:
                await asyncio.sleep(write_delay_ms / 1000)

            if capture_trace and current_packet_event is not None:
                current_packet_event["relative_end_ms"] = round(
                    (time.monotonic() - trace_started_monotonic) * 1000, 3
                )
                current_packet_event["notification_count"] = len(
                    current_packet_event["notifications"]
                )
                trace_packet_events.append(current_packet_event)
                current_packet_event = None

        await asyncio.sleep(0.2)
        if notify_started:
            try:
                await client.stop_notify(PANDA_FFE1_CHAR_UUID)
            except Exception as err:  # noqa: BLE001
                notifications.append(f"notify_stop_error:{type(err).__name__}:{err}")

        trace_summary: dict[str, Any] = {}
        if capture_trace:
            packets_with_notifications = sum(
                1
                for event in trace_packet_events
                if event.get("notification_count", 0) > 0
            )
            trace_summary = {
                "trace_enabled": True,
                "trace_started_at": trace_started_at.isoformat(),
                "trace_duration_ms": round(
                    (time.monotonic() - trace_started_monotonic) * 1000, 3
                ),
                "trace_packet_count": len(trace_packet_events),
                "trace_notification_count": len(trace_notifications),
                "trace_packets_with_notifications": packets_with_notifications,
                "trace_packets_without_notifications": (
                    len(trace_packet_events) - packets_with_notifications
                ),
            }

        ack_progress_count = sum(len(cycle) for cycle in progress_cycles)
        ack_cycle_count = sum(1 for cycle in progress_cycles if cycle)
        write_details = {
            **details,
            "address": address,
            "plane_byte_count": PANDA_PLANE_BYTE_COUNT,
            "chunk_payload_size": PANDA_CHUNK_PAYLOAD_SIZE,
            "write_delay_ms": write_delay_ms,
            "preamble": "standard",
            "packet_count": len(packets),
            "image_packets_written": image_packets_written,
            "bytes_written": sum(len(packet) for packet in packets),
            "notification_count": len(notifications),
            "notifications": notifications[:40],
            "attempt": attempt,
            "max_attempts": max_attempts,
            "ack_progress_count": ack_progress_count,
            "ack_cycle_count": ack_cycle_count,
            "ack_final_seen": final_ack_seen,
            "ack_chunk_timeout_s": PANDA_ACK_CHUNK_TIMEOUT_S,
            "ack_final_timeout_s": PANDA_ACK_FINAL_TIMEOUT_S,
            "characteristic": PANDA_FFE1_CHAR_UUID,
            "characteristic_info": characteristic_info,
            "protocol_variant": "v19_ack_gated",
            **trace_summary,
        }
        if capture_trace:
            metadata = {
                "trace_version": 1,
                "started_at": trace_started_at.isoformat(),
                "address": address,
                "action_key": action_key,
                "result_name": result_name,
                "characteristic": PANDA_FFE1_CHAR_UUID,
                "characteristic_info": characteristic_info,
                "write_delay_ms": write_delay_ms,
                "packet_count": len(packets),
                "image_packets_written": image_packets_written,
                "bytes_written": sum(len(packet) for packet in packets),
                "attempt": attempt,
                "max_attempts": max_attempts,
                "ack_chunk_timeout_s": PANDA_ACK_CHUNK_TIMEOUT_S,
                "ack_final_timeout_s": PANDA_ACK_FINAL_TIMEOUT_S,
                "protocol_variant": "v19_ack_gated",
            }
            try:
                trace_file = await hass.async_add_executor_job(
                    _write_packet_trace_file,
                    hass.config.path(),
                    metadata,
                    trace_packet_events,
                    trace_notifications,
                    {
                        **trace_summary,
                        "result": result_name,
                        "ack_progress_count": ack_progress_count,
                        "ack_cycle_count": ack_cycle_count,
                        "ack_final_seen": final_ack_seen,
                    },
                )
                write_details["trace_file"] = trace_file
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Failed to write PANDA packet trace: %s", err)
                write_details["trace_error"] = str(err)

        runtime.state.update_write_action(action_key, result_name, details=write_details)
        runtime.coordinator.async_set_updated_data(runtime.state)
    except Exception as err:
        error_details: dict[str, Any] | None = None
        if capture_trace:
            if current_packet_event is not None:
                current_packet_event["relative_error_ms"] = round(
                    (time.monotonic() - trace_started_monotonic) * 1000, 3
                )
                current_packet_event["error"] = str(err)
                current_packet_event["notification_count"] = len(
                    current_packet_event["notifications"]
                )
                trace_packet_events.append(current_packet_event)
            packets_with_notifications = sum(
                1
                for event in trace_packet_events
                if event.get("notification_count", 0) > 0
            )
            trace_summary = {
                "trace_enabled": True,
                "trace_started_at": trace_started_at.isoformat(),
                "trace_duration_ms": round(
                    (time.monotonic() - trace_started_monotonic) * 1000, 3
                ),
                "trace_packet_count": len(trace_packet_events),
                "trace_notification_count": len(trace_notifications),
                "trace_packets_with_notifications": packets_with_notifications,
                "trace_packets_without_notifications": (
                    len(trace_packet_events) - packets_with_notifications
                ),
                "trace_error": str(err),
            }
            ack_progress_count = sum(len(cycle) for cycle in progress_cycles)
            ack_cycle_count = sum(1 for cycle in progress_cycles if cycle)
            metadata = {
                "trace_version": 1,
                "started_at": trace_started_at.isoformat(),
                "address": address,
                "action_key": action_key,
                "result_name": result_name + "_error",
                "characteristic": PANDA_FFE1_CHAR_UUID,
                "write_delay_ms": write_delay_ms,
                "packet_count": len(packets),
                "attempt": attempt,
                "max_attempts": max_attempts,
                "ack_chunk_timeout_s": PANDA_ACK_CHUNK_TIMEOUT_S,
                "ack_final_timeout_s": PANDA_ACK_FINAL_TIMEOUT_S,
                "protocol_variant": "v19_ack_gated",
            }
            error_details = {
                **details,
                **trace_summary,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "ack_progress_count": ack_progress_count,
                "ack_cycle_count": ack_cycle_count,
                "ack_final_seen": final_ack_seen,
                "ack_chunk_timeout_s": PANDA_ACK_CHUNK_TIMEOUT_S,
                "ack_final_timeout_s": PANDA_ACK_FINAL_TIMEOUT_S,
                "protocol_variant": "v19_ack_gated",
            }
            try:
                trace_file = await hass.async_add_executor_job(
                    _write_packet_trace_file,
                    hass.config.path(),
                    metadata,
                    trace_packet_events,
                    trace_notifications,
                    {
                        **trace_summary,
                        "result": result_name + "_error",
                        "ack_progress_count": ack_progress_count,
                        "ack_cycle_count": ack_cycle_count,
                        "ack_final_seen": final_ack_seen,
                    },
                )
                error_details["trace_file"] = trace_file
            except Exception as trace_err:  # noqa: BLE001
                _LOGGER.warning("Failed to write PANDA packet trace: %s", trace_err)
                error_details["trace_error"] = (
                    f"{err}; trace_write_error={trace_err}"
                )
        runtime.state.update_write_action(
            action_key,
            result_name + "_error",
            str(err),
            details=error_details,
        )
        runtime.coordinator.async_set_updated_data(runtime.state)
        if isinstance(err, HomeAssistantError):
            raise
        raise _translated_error(
            "write_failed",
            f"Failed to write PANDA ESL image: {err}",
            error=err,
        ) from err
    finally:
        if client is not None and client.is_connected:
            await client.disconnect()


async def _async_send_packets(
    hass: HomeAssistant,
    runtime: PandaEslRuntimeData,
    *,
    packets: list[bytes],
    action_key: str,
    result_name: str,
    details: dict[str, Any],
    write_delay_ms: int = PANDA_WRITE_DELAY_MS,
    max_attempts: int = PANDA_ACK_MAX_ATTEMPTS,
) -> None:
    """Send packets with at most one whole-write retry."""
    bounded_attempts = max(1, min(int(max_attempts), PANDA_ACK_MAX_ATTEMPTS))
    last_error: HomeAssistantError | None = None
    for attempt in range(1, bounded_attempts + 1):
        try:
            await _async_send_packets_attempt(
                hass,
                runtime,
                packets=packets,
                action_key=action_key,
                result_name=result_name,
                details=details,
                write_delay_ms=write_delay_ms,
                attempt=attempt,
                max_attempts=bounded_attempts,
            )
            return
        except HomeAssistantError as err:
            last_error = err
            if attempt < bounded_attempts:
                _LOGGER.warning(
                    "Retrying PANDA ESL write to %s after ACK failure: %s",
                    runtime.state.address,
                    err,
                )
                await asyncio.sleep(1)

    assert last_error is not None
    raise last_error


async def async_write_rendered_packets(
    hass: HomeAssistant,
    runtime: PandaEslRuntimeData,
    *,
    packets: list[bytes],
    action_key: str,
    result_name: str,
    details: dict[str, Any],
    write_delay_ms: int = PANDA_WRITE_DELAY_MS,
    max_attempts: int = PANDA_ACK_MAX_ATTEMPTS,
) -> None:
    """Send rendered-image packets through the proven PANDA packet path."""
    await _async_send_packets(
        hass,
        runtime,
        packets=packets,
        action_key=action_key,
        result_name=result_name,
        details=details,
        write_delay_ms=write_delay_ms,
        max_attempts=max_attempts,
    )


async def async_write_white_fill(hass: HomeAssistant, runtime: PandaEslRuntimeData) -> None:
    """Send a solid white fill."""
    await _async_send_packets(
        hass,
        runtime,
        packets=_build_fill_packets("white"),
        action_key="white_fill",
        result_name="write_white_fill_ok",
        details={"test_image": "Solid white fill", "color": "white", "plane_strategy": "0_then_1"},
    )


async def async_write_black_fill(hass: HomeAssistant, runtime: PandaEslRuntimeData) -> None:
    """Send a solid black fill."""
    await _async_send_packets(
        hass,
        runtime,
        packets=_build_fill_packets("black"),
        action_key="black_fill",
        result_name="write_black_fill_ok",
        details={"test_image": "Solid black fill", "color": "black", "plane_strategy": "0_only"},
    )


async def async_write_red_fill(hass: HomeAssistant, runtime: PandaEslRuntimeData) -> None:
    """Send a solid red fill."""
    await _async_send_packets(
        hass,
        runtime,
        packets=_build_fill_packets("red"),
        action_key="red_fill",
        result_name="write_red_fill_ok",
        details={"test_image": "Solid red fill", "color": "red", "plane_strategy": "1_only"},
    )


async def async_write_nearfinal_framed_image(hass: HomeAssistant, runtime: PandaEslRuntimeData) -> None:
    """Send the diagnostic framed image."""
    await _async_send_packets(
        hass,
        runtime,
        packets=_build_framed_packets(),
        action_key="framed_image",
        result_name="write_framed_image_ok",
        details={
            "test_image": "Framed image",
            "canvas_width": PANDA_CANVAS_WIDTH,
            "canvas_height": PANDA_CANVAS_HEIGHT,
            "plane_strategy": "0_then_1",
            "notes": "top/right inset, vertically pre-flipped",
        },
    )
