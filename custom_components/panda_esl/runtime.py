"""Minimal runtime helpers for PANDA ESL writes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from bleak import BleakClient
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from PIL import Image

from .models import PandaEslState

PANDA_FFE1_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

# Empirically verified for the PANDA ESL-21R / ETAG stock firmware.
PANDA_PLANE_BYTE_COUNT = 4096  # 256 x 128 / 8
PANDA_CHUNK_PAYLOAD_SIZE = 50
PANDA_WRITE_DELAY_MS = 150
PANDA_CANVAS_WIDTH = 256
PANDA_CANVAS_HEIGHT = 128

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


def update_from_service_info(
    runtime: PandaEslRuntimeData, service_info: BluetoothServiceInfoBleak
) -> None:
    """Apply an advertisement update and notify entities."""
    runtime.state.update_from_service_info(service_info)
    runtime.coordinator.async_set_updated_data(runtime.state)


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


async def _async_send_packets(
    hass: HomeAssistant,
    runtime: PandaEslRuntimeData,
    *,
    packets: list[bytes],
    action_key: str,
    result_name: str,
    details: dict[str, Any],
    write_delay_ms: int = PANDA_WRITE_DELAY_MS,
) -> None:
    """Send packets using the stable slow transfer settings."""
    address = runtime.state.address
    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        message = "No connectable BLE device handle is available"
        runtime.state.update_write_action(action_key, result_name + "_error", message)
        runtime.coordinator.async_set_updated_data(runtime.state)
        raise HomeAssistantError(message)

    notifications: list[str] = []
    client: BleakClient | None = None
    try:
        client = await establish_connection(BleakClient, ble_device, address)

        def _notification_handler(_sender: Any, data: bytearray) -> None:
            notifications.append(bytes(data).hex())

        notify_started = False
        try:
            await client.start_notify(PANDA_FFE1_CHAR_UUID, _notification_handler)
            notify_started = True
            await asyncio.sleep(0.2)
        except Exception as err:  # noqa: BLE001
            notifications.append(f"notify_start_error:{type(err).__name__}:{err}")

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
        for packet_index, packet in enumerate(packets):
            await client.write_gatt_char(PANDA_FFE1_CHAR_UUID, packet, response=False)
            if preamble_len <= packet_index < len(packets) - 1:
                image_packets_written += 1
            await asyncio.sleep(write_delay_ms / 1000)

        await asyncio.sleep(2)
        if notify_started:
            try:
                await client.stop_notify(PANDA_FFE1_CHAR_UUID)
            except Exception as err:  # noqa: BLE001
                notifications.append(f"notify_stop_error:{type(err).__name__}:{err}")

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
            "characteristic": PANDA_FFE1_CHAR_UUID,
            "characteristic_info": characteristic_info,
            "protocol_variant": "v18_minimal",
        }
        runtime.state.update_write_action(action_key, result_name, details=write_details)
        runtime.coordinator.async_set_updated_data(runtime.state)
    except Exception as err:
        runtime.state.update_write_action(action_key, result_name + "_error", str(err))
        runtime.coordinator.async_set_updated_data(runtime.state)
        raise HomeAssistantError(f"Failed to write PANDA ESL image: {err}") from err
    finally:
        if client is not None and client.is_connected:
            await client.disconnect()


async def async_write_rendered_packets(
    hass: HomeAssistant,
    runtime: PandaEslRuntimeData,
    *,
    packets: list[bytes],
    action_key: str,
    result_name: str,
    details: dict[str, Any],
    write_delay_ms: int = PANDA_WRITE_DELAY_MS,
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
