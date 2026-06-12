"""Pillow renderer for PANDA ESL service payloads."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta
from io import BytesIO
import io
import json
import logging
import math
import os
from pathlib import Path
from typing import Any
import urllib.parse

import barcode
from barcode.writer import ImageWriter
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt
from PIL import Image, ImageDraw, ImageFont
import qrcode
import requests

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
RED = (255, 0, 0, 255)
YELLOW = (255, 255, 0, 255)

_SUPPORTED_COLORS = [WHITE, BLACK, RED, YELLOW]
_FONT_DIR = Path(__file__).with_name("fonts")
_DEFAULT_FONT = "fonts/NotoSansKR-Regular.ttf"
_MDI_META: list[dict[str, Any]] | None = None


def blank_png(width: int, height: int) -> bytes:
    """Return a white PNG for image entities before the first render."""
    image = Image.new("RGB", (width, height), "white")
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def _render_error(
    translation_key: str,
    message: str,
    **translation_placeholders: Any,
) -> HomeAssistantError:
    """Return a translated renderer error."""
    return HomeAssistantError(
        message,
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders={
            key: str(value) for key, value in translation_placeholders.items()
        },
    )


def _nearest_eink_color(red: int, green: int, blue: int) -> tuple[int, int, int, int]:
    best = WHITE
    best_dist = float("inf")
    for color in _SUPPORTED_COLORS:
        dist = (
            (red - color[0]) ** 2
            + (green - color[1]) ** 2
            + (blue - color[2]) ** 2
        )
        if dist < best_dist:
            best = color
            best_dist = dist
    return best


def get_index_color(color: Any) -> tuple[int, int, int, int] | None:
    """Convert a Gicisky color token or hex string to an e-ink RGBA color."""
    if color is None:
        return None

    color_str = str(color).strip().lower()
    if color_str in ("black", "b"):
        return BLACK
    if color_str in ("red", "r"):
        return RED
    if color_str in ("yellow", "y"):
        return YELLOW
    if color_str in ("white", "w"):
        return WHITE

    if color_str.startswith("#"):
        try:
            hex_value = color_str.lstrip("#")
            if len(hex_value) >= 6:
                return _nearest_eink_color(
                    int(hex_value[0:2], 16),
                    int(hex_value[2:4], 16),
                    int(hex_value[4:6], 16),
                )
        except ValueError:
            _LOGGER.debug("Could not parse hex color %s", color_str)
        return WHITE

    return WHITE


def _visible(element: dict[str, Any]) -> bool:
    visible = element.get("visible", True)
    if isinstance(visible, str):
        return visible.lower() not in {"0", "false", "off", "no"}
    return bool(visible)


def _number(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    return int(round(_number(value, default)))


def _check_required(
    element: dict[str, Any], required_keys: list[str], element_type: str
) -> None:
    missing = [key for key in required_keys if key not in element]
    if missing:
        missing_keys = ", ".join(missing)
        raise _render_error(
            "missing_required_element_arguments",
            f"Missing required argument(s) '{missing_keys}' in '{element_type}'",
            arguments=missing_keys,
            element_type=element_type,
        )


def _is_decimal(value: Any) -> bool:
    text = str(value)
    if not text:
        return False
    if text.startswith("-"):
        text = text[1:]
    return len(text.split(".")) <= 2 and text.replace(".", "").isdecimal()


def _min_max(data: list[float]) -> tuple[float, float]:
    if not data:
        raise _render_error(
            "recorder_data_out_of_range",
            "Data error, something is not in range of the recorder",
        )
    return min(data), max(data)


def _get_wrapped_text(text: str, font: ImageFont.ImageFont, line_length: int) -> str:
    lines = [""]
    for word in text.split():
        line = f"{lines[-1]} {word}".strip()
        if font.getlength(line) <= line_length:
            lines[-1] = line
        else:
            lines.append(word)
    return "\n".join(lines)


def _get_font_file(font_name: str, hass: HomeAssistant) -> str:
    if os.path.isabs(font_name) and os.path.exists(font_name):
        return font_name

    font_file = Path(__file__).parent / font_name
    if font_file.exists():
        return str(font_file)

    www_fonts = Path(hass.config.path("www/fonts"))
    custom_font = www_fonts / font_name
    if custom_font.exists():
        return str(custom_font)

    fallback = _FONT_DIR / "NotoSansKR-Regular.ttf"
    if fallback.exists():
        return str(fallback)

    return font_name


def _load_font(font_name: str, size: int, hass: HomeAssistant) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(_get_font_file(font_name, hass), size)
    except OSError:
        _LOGGER.warning("Falling back to default PIL font; missing font: %s", font_name)
        return ImageFont.load_default()


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    dash: list[int] | tuple[int, ...],
    fill: tuple[int, int, int, int],
    width: int,
) -> None:
    dash_on = dash[0]
    dash_off = dash[1] if len(dash) > 1 else dash[0]
    total_len = math.hypot(x1 - x0, y1 - y0)
    if total_len == 0:
        return

    dx = (x1 - x0) / total_len
    dy = (y1 - y0) / total_len
    pos = 0.0
    drawing = True
    while pos < total_len:
        seg_len = dash_on if drawing else dash_off
        seg_end = min(pos + seg_len, total_len)
        if drawing:
            draw.line(
                [
                    (x0 + dx * pos, y0 + dy * pos),
                    (x0 + dx * seg_end, y0 + dy * seg_end),
                ],
                fill=fill,
                width=width,
            )
        pos += seg_len
        drawing = not drawing


def _rounded_corners(corner_string: str) -> tuple[bool, bool, bool, bool]:
    if corner_string == "all":
        return True, True, True, True

    corner_map = {
        "top_left": 0,
        "top_right": 1,
        "bottom_right": 2,
        "bottom_left": 3,
    }
    result = [False] * 4
    for corner in corner_string.split(","):
        index = corner_map.get(corner.strip())
        if index is not None:
            result[index] = True
    return tuple(result)  # type: ignore[return-value]


def _rounded_rectangle(
    draw: ImageDraw.ImageDraw,
    box: list[tuple[float, float]] | tuple[tuple[float, float], tuple[float, float]],
    *,
    fill: tuple[int, int, int, int] | None,
    outline: tuple[int, int, int, int] | None,
    width: int,
    radius: int,
    corners: tuple[bool, bool, bool, bool] | None = None,
) -> None:
    kwargs = {
        "fill": fill,
        "outline": outline,
        "width": width,
        "radius": radius,
    }
    if corners is not None:
        kwargs["corners"] = corners
    try:
        draw.rounded_rectangle(box, **kwargs)
    except TypeError:
        kwargs.pop("corners", None)
        draw.rounded_rectangle(box, **kwargs)


def _resize_image(image: Image.Image, x_size: int, y_size: int, mode: str) -> Image.Image:
    target_ratio = x_size / y_size
    src_w, src_h = image.size
    src_ratio = src_w / src_h if src_h else 1

    if mode in ("fit", "contain"):
        if src_ratio > target_ratio:
            new_w = x_size
            new_h = round(x_size / src_ratio)
        else:
            new_h = y_size
            new_w = round(y_size * src_ratio)
        image = image.resize((new_w, new_h), Image.LANCZOS)
        canvas = Image.new("RGBA", (x_size, y_size), (255, 255, 255, 0))
        canvas.paste(image.convert("RGBA"), ((x_size - new_w) // 2, (y_size - new_h) // 2))
        return canvas

    if mode == "fill":
        if src_ratio > target_ratio:
            new_h = y_size
            new_w = round(y_size * src_ratio)
        else:
            new_w = x_size
            new_h = round(x_size / src_ratio)
        image = image.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - x_size) // 2
        top = (new_h - y_size) // 2
        return image.crop((left, top, left + x_size, top + y_size))

    return image.resize((x_size, y_size), Image.LANCZOS)


def _load_mdi_icon_data() -> list[dict[str, Any]]:
    global _MDI_META
    if _MDI_META is None:
        meta_file = _FONT_DIR / "materialdesignicons-webfont_meta.json"
        with meta_file.open(encoding="utf-8") as file:
            _MDI_META = json.load(file)
    return _MDI_META


def _map_weather_icon(icon: str) -> str:
    if not icon.startswith("weather-"):
        return icon

    weather_mapping = {
        "clear-night": "night",
        "partlycloudy": "partly-cloudy",
        "exceptional": "sunny-off",
    }
    clean_icon = icon.removeprefix("weather-")
    return f"weather-{weather_mapping.get(clean_icon, clean_icon)}"


def _load_dl_image(url: str) -> Image.Image:
    if url.startswith(("http://", "https://")):
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
        except requests.RequestException as err:
            raise _render_error(
                "download_image_failed",
                f"Failed to download image: {err}",
                error=err,
            ) from err
        return Image.open(io.BytesIO(response.content))

    if url.startswith("data:"):
        payload = url[5:]
        if not payload or "," not in payload:
            raise _render_error("invalid_data_url", "Invalid data URL")
        media_type, _, raw_data = payload.partition(",")
        if media_type.endswith(";base64"):
            raw_data += "=" * (-len(raw_data) % 4)
            try:
                data = base64.b64decode(raw_data)
            except ValueError as exc:
                raise _render_error(
                    "invalid_data_url_base64",
                    "Invalid base64 in data URL",
                ) from exc
        else:
            data = urllib.parse.unquote_to_bytes(raw_data)
        return Image.open(io.BytesIO(data))

    return Image.open(url)


def render_service_image(
    hass: HomeAssistant,
    service_data: dict[str, Any],
    width: int,
    height: int,
) -> Image.Image:
    """Render a Gicisky-compatible service payload to a PANDA-sized RGB image."""
    payload = service_data.get("payload", [])
    if not isinstance(payload, list):
        raise _render_error(
            "payload_must_be_list",
            "Payload must be a list of drawing elements",
        )

    rotate = _int(service_data.get("rotate", 0), 0)
    background = get_index_color(service_data.get("background", "white")) or WHITE

    if rotate in (90, 270):
        image = Image.new("RGBA", (height, width), color=background)
    else:
        image = Image.new("RGBA", (width, height), color=background)

    canvas_width, canvas_height = image.size
    pos_y = 0
    known_types = {
        "line",
        "rectangle",
        "rectangle_pattern",
        "circle",
        "ellipse",
        "text",
        "multiline",
        "icon",
        "dlimg",
        "qrcode",
        "barcode",
        "diagram",
        "plot",
        "progress_bar",
        "arc",
        "gauge",
        "polygon",
        "table",
        "text_box",
        "datamatrix",
    }

    for raw_element in payload:
        if not isinstance(raw_element, dict):
            raise _render_error(
                "payload_element_must_be_object",
                "Payload elements must be objects",
            )
        element = raw_element
        element_type = str(element.get("type", ""))
        if not _visible(element):
            continue
        if element_type not in known_types:
            _LOGGER.warning("Unknown element type '%s' - skipping", element_type)
            continue

        if element_type == "line":
            _check_required(element, ["x_start", "x_end"], "line")
            draw = ImageDraw.Draw(image)
            y_start = (
                pos_y + _int(element.get("y_padding", 0), 0)
                if "y_start" not in element
                else _number(element["y_start"])
            )
            y_end = y_start if "y_end" not in element else _number(element["y_end"])
            fill = get_index_color(element.get("fill", "black")) or BLACK
            line_width = _int(element.get("width", 1), 1)
            dash = element.get("dash")
            if dash:
                _draw_dashed_line(
                    draw,
                    _number(element["x_start"]),
                    y_start,
                    _number(element["x_end"]),
                    y_end,
                    dash,
                    fill,
                    line_width,
                )
            else:
                draw.line(
                    [
                        (_number(element["x_start"]), y_start),
                        (_number(element["x_end"]), y_end),
                    ],
                    fill=fill,
                    width=line_width,
                )
            pos_y = _int(y_start)

        if element_type == "rectangle":
            _check_required(element, ["x_start", "x_end", "y_start", "y_end"], "rectangle")
            draw = ImageDraw.Draw(image)
            radius = _int(
                element.get("radius", 10 if "corners" in element else 0),
                0,
            )
            corners = (
                _rounded_corners(str(element["corners"]))
                if "corners" in element
                else _rounded_corners("all")
                if "radius" in element
                else None
            )
            _rounded_rectangle(
                draw,
                [
                    (_number(element["x_start"]), _number(element["y_start"])),
                    (_number(element["x_end"]), _number(element["y_end"])),
                ],
                fill=get_index_color(element.get("fill")),
                outline=get_index_color(element.get("outline", "black")),
                width=_int(element.get("width", 1), 1),
                radius=radius,
                corners=corners,
            )

        if element_type == "rectangle_pattern":
            _check_required(
                element,
                [
                    "x_start",
                    "x_size",
                    "y_start",
                    "y_size",
                    "x_repeat",
                    "y_repeat",
                    "x_offset",
                    "y_offset",
                ],
                "rectangle_pattern",
            )
            draw = ImageDraw.Draw(image)
            fill = get_index_color(element.get("fill"))
            outline = get_index_color(element.get("outline", "black"))
            rect_width = _int(element.get("width", 1), 1)
            radius = _int(element.get("radius", 10 if "corners" in element else 0), 0)
            corners = (
                _rounded_corners(str(element["corners"]))
                if "corners" in element
                else _rounded_corners("all")
                if "radius" in element
                else None
            )
            for x_index in range(_int(element["x_repeat"])):
                for y_index in range(_int(element["y_repeat"])):
                    x0 = _number(element["x_start"]) + x_index * (
                        _number(element["x_offset"]) + _number(element["x_size"])
                    )
                    y0 = _number(element["y_start"]) + y_index * (
                        _number(element["y_offset"]) + _number(element["y_size"])
                    )
                    _rounded_rectangle(
                        draw,
                        [
                            (x0, y0),
                            (x0 + _number(element["x_size"]), y0 + _number(element["y_size"])),
                        ],
                        fill=fill,
                        outline=outline,
                        width=rect_width,
                        radius=radius,
                        corners=corners,
                    )

        if element_type == "circle":
            _check_required(element, ["x", "y", "radius"], "circle")
            draw = ImageDraw.Draw(image)
            x = _number(element["x"])
            y = _number(element["y"])
            radius = _number(element["radius"])
            draw.ellipse(
                [(x - radius, y - radius), (x + radius, y + radius)],
                fill=get_index_color(element.get("fill")),
                outline=get_index_color(element.get("outline", "black")),
                width=_int(element.get("width", 1), 1),
            )

        if element_type == "ellipse":
            _check_required(element, ["x_start", "x_end", "y_start", "y_end"], "ellipse")
            draw = ImageDraw.Draw(image)
            draw.ellipse(
                [
                    (_number(element["x_start"]), _number(element["y_start"])),
                    (_number(element["x_end"]), _number(element["y_end"])),
                ],
                fill=get_index_color(element.get("fill")),
                outline=get_index_color(element.get("outline", "black")),
                width=_int(element.get("width", 1), 1),
            )

        if element_type == "arc":
            _check_required(
                element,
                ["x_start", "y_start", "x_end", "y_end", "start_angle", "end_angle"],
                "arc",
            )
            draw = ImageDraw.Draw(image)
            box = [
                (_number(element["x_start"]), _number(element["y_start"])),
                (_number(element["x_end"]), _number(element["y_end"])),
            ]
            if element.get("pie", False):
                draw.pieslice(
                    box,
                    start=_number(element["start_angle"]),
                    end=_number(element["end_angle"]),
                    fill=get_index_color(element.get("fill")),
                    outline=get_index_color(element.get("outline", "black")),
                    width=_int(element.get("width", 1), 1),
                )
            else:
                draw.arc(
                    box,
                    start=_number(element["start_angle"]),
                    end=_number(element["end_angle"]),
                    fill=get_index_color(element.get("outline", "black")) or BLACK,
                    width=_int(element.get("width", 1), 1),
                )

        if element_type == "gauge":
            _check_required(element, ["x", "y", "radius", "progress"], "gauge")
            draw = ImageDraw.Draw(image)
            cx = _number(element["x"])
            cy = _number(element["y"])
            radius = _number(element["radius"])
            progress = _number(element["progress"])
            min_value = _number(element.get("min_value", 0))
            max_value = _number(element.get("max_value", 100))
            ratio = max(
                0.0,
                min(
                    1.0,
                    (progress - min_value) / (max_value - min_value)
                    if max_value != min_value
                    else 0,
                ),
            )
            start_angle = 135
            end_angle = 405
            box = [(cx - radius, cy - radius), (cx + radius, cy + radius)]
            bar_width = _int(element.get("width", 8), 8)
            draw.arc(
                box,
                start=start_angle,
                end=end_angle,
                fill=get_index_color(element.get("background", "white")) or WHITE,
                width=bar_width,
            )
            if ratio > 0:
                draw.arc(
                    box,
                    start=start_angle,
                    end=start_angle + ratio * 270,
                    fill=get_index_color(element.get("fill", "black")) or BLACK,
                    width=bar_width,
                )
            draw.arc(
                [(cx - radius - 1, cy - radius - 1), (cx + radius + 1, cy + radius + 1)],
                start=start_angle,
                end=end_angle,
                fill=get_index_color(element.get("outline", "black")) or BLACK,
                width=1,
            )
            if element.get("show_value", False):
                font = _load_font(
                    str(element.get("font", _DEFAULT_FONT)),
                    _int(element.get("size", 16), 16),
                    hass,
                )
                text = f"{int(progress)}" if progress == int(progress) else f"{progress:.1f}"
                draw.text(
                    (cx, cy),
                    text,
                    fill=get_index_color(element.get("color", "black")) or BLACK,
                    font=font,
                    anchor="mm",
                )

        if element_type == "polygon":
            _check_required(element, ["points"], "polygon")
            draw = ImageDraw.Draw(image)
            try:
                points = []
                for pair in str(element["points"]).split(";"):
                    x_raw, y_raw = pair.strip().split(",")
                    points.append((float(x_raw), float(y_raw)))
            except Exception as err:
                raise _render_error(
                    "invalid_polygon_points",
                    f"Polygon has invalid points format: {element['points']}",
                    points=element["points"],
                ) from err
            fill = get_index_color(element.get("fill"))
            outline = get_index_color(element.get("outline", "black"))
            line_width = _int(element.get("width", 1), 1)
            draw.polygon(points, fill=fill, outline=outline)
            if outline is not None and line_width > 1:
                draw.line(points + [points[0]], fill=outline, width=line_width, joint="curve")

        if element_type == "text":
            _check_required(element, ["x", "value"], "text")
            draw = ImageDraw.Draw(image)
            draw.fontmode = "1"
            font = _load_font(
                str(element.get("font", _DEFAULT_FONT)),
                _int(element.get("size", 20), 20),
                hass,
            )
            y_pos = (
                pos_y + _int(element.get("y_padding", 10), 10)
                if "y" not in element
                else _number(element["y"])
            )
            anchor = element.get("anchor", "lt")
            align = element.get("align", "left")
            spacing = _int(element.get("spacing", 5), 5)
            stroke_width = _int(element.get("stroke_width", 0), 0)
            stroke_fill = get_index_color(element.get("stroke_fill", "white")) or WHITE
            text_rotation = _number(element.get("rotation", 0))
            bg_color = get_index_color(element.get("background"))
            bg_padding = _int(element.get("background_padding", 2), 2)

            if "max_width" in element:
                text = _get_wrapped_text(
                    str(element["value"]), font, _int(element["max_width"])
                )
                anchor = None
            else:
                text = str(element["value"])

            x_pos = _number(element["x"])
            text_color = get_index_color(element.get("color", "black")) or BLACK

            if text_rotation != 0:
                dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
                box = dummy.textbbox(
                    (0, 0),
                    text,
                    font=font,
                    spacing=spacing,
                    stroke_width=stroke_width,
                )
                temp_w = box[2] - box[0] + stroke_width * 2 + 4
                temp_h = box[3] - box[1] + stroke_width * 2 + 4
                temp = Image.new("RGBA", (temp_w, temp_h), (255, 255, 255, 0))
                temp_draw = ImageDraw.Draw(temp)
                temp_draw.fontmode = "1"
                if bg_color is not None:
                    temp_draw.rectangle([(0, 0), (temp_w, temp_h)], fill=bg_color)
                temp_draw.text(
                    (2, 2),
                    text,
                    fill=text_color,
                    font=font,
                    spacing=spacing,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_fill,
                )
                temp = temp.rotate(text_rotation, expand=True)
                layer = Image.new("RGBA", image.size, (255, 255, 255, 0))
                layer.paste(temp, (_int(x_pos), _int(y_pos)), temp)
                image = Image.alpha_composite(image, layer)
            else:
                if bg_color is not None:
                    text_box = draw.textbbox(
                        (x_pos, y_pos),
                        text,
                        font=font,
                        anchor=anchor,
                        align=align,
                        spacing=spacing,
                        stroke_width=stroke_width,
                    )
                    draw.rectangle(
                        [
                            (text_box[0] - bg_padding, text_box[1] - bg_padding),
                            (text_box[2] + bg_padding, text_box[3] + bg_padding),
                        ],
                        fill=bg_color,
                    )
                draw.text(
                    (x_pos, y_pos),
                    text,
                    fill=text_color,
                    font=font,
                    anchor=anchor,
                    align=align,
                    spacing=spacing,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_fill,
                )

            text_box = ImageDraw.Draw(image).textbbox(
                (x_pos, y_pos),
                text,
                font=font,
                anchor=anchor,
                align=align,
                spacing=spacing,
                stroke_width=stroke_width,
            )
            pos_y = text_box[3]

        if element_type == "text_box":
            _check_required(element, ["x", "y", "value"], "text_box")
            draw = ImageDraw.Draw(image)
            draw.fontmode = "1"
            font = _load_font(
                str(element.get("font", _DEFAULT_FONT)),
                _int(element.get("size", 20), 20),
                hass,
            )
            text = str(element["value"])
            padding = _int(element.get("padding", 5), 5)
            x_pos = _number(element["x"])
            y_pos = _number(element["y"])
            text_box = draw.textbbox((x_pos + padding, y_pos + padding), text, font=font)
            _rounded_rectangle(
                draw,
                [
                    (x_pos, y_pos),
                    (text_box[2] + padding, text_box[3] + padding),
                ],
                fill=get_index_color(element.get("fill", "black")),
                outline=get_index_color(element.get("outline")),
                width=_int(element.get("width", 1), 1),
                radius=_int(element.get("radius", 5), 5),
            )
            draw.text(
                (x_pos + padding, y_pos + padding),
                text,
                fill=get_index_color(element.get("color", "white")) or WHITE,
                font=font,
                anchor="lt",
            )

        if element_type == "multiline":
            _check_required(element, ["x", "value", "delimiter"], "multiline")
            draw = ImageDraw.Draw(image)
            draw.fontmode = "1"
            font = _load_font(
                str(element.get("font", _DEFAULT_FONT)),
                _int(element.get("size", 20), 20),
                hass,
            )
            color = get_index_color(element.get("color", "black")) or BLACK
            anchor = element.get("anchor", "lm")
            stroke_width = _int(element.get("stroke_width", 0), 0)
            stroke_fill = get_index_color(element.get("stroke_fill", "white")) or WHITE
            pos = _number(
                element.get("start_y", pos_y + _int(element.get("y_padding", 10), 10))
            )
            for line in str(element["value"]).replace("\n", "").split(str(element["delimiter"])):
                draw.text(
                    (_number(element["x"]), pos),
                    line,
                    fill=color,
                    font=font,
                    anchor=anchor,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_fill,
                )
                pos += _number(element.get("offset_y", 0))
            pos_y = _int(pos)

        if element_type == "table":
            _check_required(element, ["x", "y", "columns", "rows"], "table")
            draw = ImageDraw.Draw(image)
            draw.fontmode = "1"
            font_size = _int(element.get("font_size", 14), 14)
            font = _load_font(str(element.get("font", _DEFAULT_FONT)), font_size, hass)
            table_x = _number(element["x"])
            current_y = _number(element["y"])
            col_widths = [_int(column) for column in element["columns"]]
            rows = element["rows"]
            row_height = _int(element.get("row_height", font_size + 8), font_size + 8)
            padding = _int(element.get("padding", 4), 4)
            header_fill = get_index_color(element.get("header_fill", "black")) or BLACK
            header_color = get_index_color(element.get("header_color", "white")) or WHITE
            cell_color = get_index_color(element.get("cell_color", "black")) or BLACK
            border_color = get_index_color(element.get("border_color", "black")) or BLACK
            border_width = _int(element.get("border_width", 1), 1)
            align = element.get("align", "left")

            for row_index, row in enumerate(rows):
                is_header = row_index == 0 and bool(element.get("header", True))
                fill_bg = header_fill if is_header else get_index_color(element.get("cell_fill"))
                text_color = header_color if is_header else cell_color
                current_x = table_x
                for cell, column_width in zip(row, col_widths, strict=False):
                    draw.rectangle(
                        [(current_x, current_y), (current_x + column_width, current_y + row_height)],
                        fill=fill_bg,
                        outline=border_color,
                        width=border_width,
                    )
                    if align == "center":
                        text_x = current_x + column_width // 2
                        anchor = "mm"
                    elif align == "right":
                        text_x = current_x + column_width - padding
                        anchor = "rm"
                    else:
                        text_x = current_x + padding
                        anchor = "lm"
                    draw.text(
                        (text_x, current_y + row_height // 2),
                        str(cell),
                        fill=text_color,
                        font=font,
                        anchor=anchor,
                    )
                    current_x += column_width
                current_y += row_height
            pos_y = _int(current_y)

        if element_type == "icon":
            _check_required(element, ["x", "y", "value", "size"], "icon")
            draw = ImageDraw.Draw(image)
            draw.fontmode = "1"
            icon_value = str(element["value"])
            if icon_value.startswith("mdi:"):
                icon_value = icon_value[4:]
            icon_value = _map_weather_icon(icon_value)
            codepoint = ""
            for icon in _load_mdi_icon_data():
                if icon.get("name") == icon_value or icon_value in icon.get("aliases", []):
                    codepoint = icon["codepoint"]
                    break
            if not codepoint:
                raise _render_error(
                    "invalid_icon",
                    f"Non valid icon used: {icon_value}",
                    icon=icon_value,
                )
            font = ImageFont.truetype(
                str(_FONT_DIR / "materialdesignicons-webfont.ttf"),
                _int(element["size"]),
            )
            draw.text(
                (_number(element["x"]), _number(element["y"])),
                chr(int(codepoint, 16)),
                fill=get_index_color(element.get("color", element.get("fill", "black"))) or BLACK,
                font=font,
                anchor=element.get("anchor", "la"),
                stroke_width=_int(element.get("stroke_width", 0), 0),
                stroke_fill=get_index_color(element.get("stroke_fill", "white")) or WHITE,
            )

        if element_type == "dlimg":
            _check_required(element, ["x", "y", "url", "xsize", "ysize"], "dlimg")
            downloaded = _load_dl_image(str(element["url"]))
            if _number(element.get("rotate", 0)) != 0:
                downloaded = downloaded.rotate(-_number(element.get("rotate", 0)), expand=True)
            downloaded = _resize_image(
                downloaded,
                _int(element["xsize"]),
                _int(element["ysize"]),
                str(element.get("mode", "stretch")),
            ).convert("RGBA")
            layer = Image.new("RGBA", image.size, (255, 255, 255, 0))
            layer.paste(downloaded, (_int(element["x"]), _int(element["y"])), downloaded)
            image = Image.alpha_composite(image, layer)

        if element_type == "qrcode":
            _check_required(element, ["x", "y", "data"], "qrcode")
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=_int(element.get("boxsize", 2), 2),
                border=_int(element.get("border", 1), 1),
            )
            qr.add_data(element["data"])
            qr.make(fit=True)
            qr_image = qr.make_image(
                fill_color=get_index_color(element.get("color", "black")) or BLACK,
                back_color=get_index_color(element.get("bgcolor", "white")) or WHITE,
            ).convert("RGBA")
            image.paste(qr_image, (_int(element["x"]), _int(element["y"])), qr_image)

        if element_type == "barcode":
            _check_required(element, ["x", "y", "data"], "barcode")
            options = {
                "module_width": float(element.get("module_width", 0.2)),
                "module_height": float(element.get("module_height", 7)),
                "quiet_zone": float(element.get("quiet_zone", 6.5)),
                "font_size": _int(element.get("font_size", 5), 5),
                "text_distance": float(element.get("text_distance", 5.0)),
                "background": str(element.get("bgcolor", "white")),
                "foreground": str(element.get("color", "black")),
                "write_text": bool(element.get("write_text", True)),
            }
            output = BytesIO()
            barcode_class = barcode.get_barcode_class(str(element.get("code", "code128")))
            barcode_class(str(element["data"]), writer=ImageWriter()).write(output, options=options)
            output.seek(0)
            barcode_image = Image.open(output).convert("RGBA")
            image.paste(barcode_image, (_int(element["x"]), _int(element["y"])), barcode_image)

        if element_type == "datamatrix":
            _check_required(element, ["x", "y", "data"], "datamatrix")
            try:
                from pystrich.datamatrix import DataMatrixEncoder
            except ImportError as err:
                raise _render_error(
                    "datamatrix_dependency_missing",
                    "datamatrix requires 'pyStrich'",
                ) from err
            encoder = DataMatrixEncoder(str(element["data"]))
            dm_image = Image.open(
                BytesIO(encoder.get_imagedata(cellsize=_int(element.get("boxsize", 2), 2)))
            ).convert("RGBA")
            if element.get("color", "black") != "black" or element.get("bgcolor", "white") != "white":
                target_color = get_index_color(element.get("color", "black")) or BLACK
                target_bg = get_index_color(element.get("bgcolor", "white")) or WHITE
                dm_image.putdata(
                    [
                        target_color if pixel[0] < 128 else target_bg
                        for pixel in dm_image.getdata()
                    ]
                )
            image.paste(dm_image, (_int(element["x"]), _int(element["y"])), dm_image)

        if element_type == "diagram":
            _check_required(element, ["x", "y", "height"], "diagram")
            draw = ImageDraw.Draw(image)
            draw.fontmode = "1"
            pos_x = _number(element["x"])
            pos_y = _number(element["y"])
            chart_width = _number(element.get("width", canvas_width))
            chart_height = _number(element["height"])
            margin = _number(element.get("margin", 20))
            draw.line(
                [(pos_x + margin, pos_y + chart_height - margin), (pos_x + chart_width, pos_y + chart_height - margin)],
                fill=BLACK,
                width=1,
            )
            draw.line(
                [(pos_x + margin, pos_y), (pos_x + margin, pos_y + chart_height - margin)],
                fill=BLACK,
                width=1,
            )
            if "bars" in element:
                bars_config = element["bars"]
                bars = str(bars_config["values"]).split(";")
                bar_margin = _number(bars_config.get("margin", 10))
                bar_count = len(bars)
                bar_width = math.floor(
                    (chart_width - margin - ((bar_count + 1) * bar_margin)) / bar_count
                )
                font = _load_font(
                    str(element.get("font", _DEFAULT_FONT)),
                    _int(bars_config.get("legend_size", 10), 10),
                    hass,
                )
                legend_color = get_index_color(bars_config.get("legend_color", "black")) or BLACK
                parsed_bars = []
                max_value = 0
                for bar in bars:
                    name, value_raw = bar.split(",", 1)
                    value = int(value_raw)
                    parsed_bars.append((name, value))
                    max_value = max(max_value, value)
                height_factor = (chart_height - margin) / max(max_value, 1)
                for bar_index, (name, value) in enumerate(parsed_bars):
                    x_pos = ((bar_margin + bar_width) * bar_index) + margin
                    draw.text(
                        (x_pos + (bar_width / 2), pos_y + chart_height - margin / 2),
                        str(name),
                        fill=legend_color,
                        font=font,
                        anchor="mm",
                    )
                    draw.rectangle(
                        [
                            (x_pos, pos_y + chart_height - margin - (height_factor * value)),
                            (x_pos + bar_width, pos_y + chart_height - margin),
                        ],
                        fill=get_index_color(bars_config["color"]) or BLACK,
                    )

        if element_type == "plot":
            _check_required(element, ["data"], "plot")
            draw = ImageDraw.Draw(image)
            draw.fontmode = "1"
            x_start = _int(element.get("x_start", 0), 0)
            y_start = _int(element.get("y_start", 0), 0)
            x_end = _int(element.get("x_end", canvas_width - 1 - x_start), canvas_width - 1)
            y_end = _int(element.get("y_end", canvas_height - 1 - x_start), canvas_height - 1)
            plot_width = x_end - x_start + 1
            plot_height = y_end - y_start + 1
            duration = timedelta(seconds=_number(element.get("duration", 60 * 60 * 24)))
            end_time = dt.utcnow()
            start_time = end_time - duration
            font_size = _int(element.get("size", 10), 10)
            font_name = str(element.get("font", _DEFAULT_FONT))
            font = _load_font(font_name, font_size, hass)

            ylegend = element.get("ylegend", {})
            if ylegend is None:
                ylegend_width = 0
                ylegend_pos = None
            else:
                ylegend_width = _int(ylegend.get("width", -1), -1)
                ylegend_color = get_index_color(ylegend.get("color", "black")) or BLACK
                ylegend_pos = ylegend.get("position", "left")
                if ylegend_pos not in ("left", "right", None):
                    ylegend_pos = "left"
                ylegend_font = _load_font(
                    str(ylegend.get("font", font_name)),
                    _int(ylegend.get("size", font_size), font_size),
                    hass,
                )

            yaxis = element.get("yaxis", {})
            if yaxis is None:
                yaxis_width = 0
                yaxis_tick_width = 0
            else:
                yaxis_width = _int(yaxis.get("width", 1), 1)
                yaxis_color = get_index_color(yaxis.get("color", "black")) or BLACK
                yaxis_tick_width = _int(yaxis.get("tick_width", 2), 2)
                yaxis_tick_every = float(yaxis.get("tick_every", 1))
                yaxis_grid = yaxis.get("grid", 5)
                yaxis_grid_color = get_index_color(yaxis.get("grid_color", "black")) or BLACK

            xlegend = element.get("xlegend")
            xlegend_height = 0
            if xlegend is not None:
                xlegend_color = get_index_color(xlegend.get("color", "black")) or BLACK
                xlegend_size = _int(xlegend.get("size", font_size), font_size)
                xlegend_font = _load_font(
                    str(xlegend.get("font", font_name)), xlegend_size, hass
                )
                xlegend_format = xlegend.get("format", "%H:%M")
                xlegend_ticks = _int(xlegend.get("ticks", 3), 3)
                xlegend_height = xlegend_size + 4

            min_value = element.get("low")
            max_value = element.get("high")
            min_value = float(min_value) if min_value is not None else None
            max_value = float(max_value) if max_value is not None else None
            series = element["data"]
            all_states = get_significant_states(
                hass,
                start_time=start_time,
                entity_ids=[item["entity"] for item in series],
                significant_changes_only=False,
                minimal_response=True,
                no_attributes=False,
            )

            raw_data: list[list[tuple[datetime, float]]] = []
            for plot in series:
                entity_id = plot["entity"]
                if entity_id not in all_states:
                    raise _render_error(
                        "no_recorded_data",
                        f"No recorded data found for {entity_id}",
                        entity_id=entity_id,
                    )
                states = all_states[entity_id]
                if states and not isinstance(states[0], dict):
                    states[0] = {
                        "state": states[0].state,
                        "last_changed": str(states[0].last_changed),
                    }
                values = [
                    (datetime.fromisoformat(str(state["last_changed"])), float(state["state"]))
                    for state in states
                    if _is_decimal(state["state"])
                ]
                local_min, local_max = _min_max([value for _when, value in values])
                min_value = min(min_value if min_value is not None else local_min, local_min)
                max_value = max(max_value if max_value is not None else local_max, local_max)
                raw_data.append(values)

            assert min_value is not None
            assert max_value is not None
            max_value = math.ceil(max_value)
            min_value = math.floor(min_value)
            if max_value == min_value:
                min_value -= 1
            spread = max_value - min_value

            if ylegend is not None and ylegend_width == -1:
                ylegend_width = math.ceil(
                    max(
                        draw.textlength(str(max_value), font=ylegend_font),
                        draw.textlength(str(min_value), font=ylegend_font),
                    )
                )

            diag_x = x_start + (ylegend_width if ylegend is not None and ylegend_pos == "left" else 0)
            diag_y = y_start
            diag_width = plot_width - (ylegend_width if ylegend is not None else 0)
            diag_height = plot_height - xlegend_height

            if element.get("debug", False):
                draw.rectangle([(x_start, y_start), (x_end, y_end)], outline=BLACK, width=1)
                draw.rectangle(
                    [(diag_x, diag_y), (diag_x + diag_width - 1, diag_y + diag_height - 1)],
                    outline=RED,
                    width=1,
                )

            if yaxis is not None and yaxis_grid is not None:
                grid_points = []
                current = min_value
                while current <= max_value:
                    current_y = round(
                        diag_y + (1 - ((current - min_value) / spread)) * (diag_height - 1)
                    )
                    grid_points.extend(
                        (x, current_y)
                        for x in range(diag_x, diag_x + diag_width, _int(yaxis_grid, 5))
                    )
                    current += yaxis_tick_every
                draw.point(grid_points, fill=yaxis_grid_color)

            for plot, values in zip(series, raw_data, strict=False):
                xy_raw = []
                for when, value in values:
                    rel_time = (when - start_time) / duration
                    rel_value = (value - min_value) / spread
                    xy_raw.append(
                        (
                            round(diag_x + rel_time * (diag_width - 1)),
                            round(diag_y + (1 - rel_value) * (diag_height - 1)),
                        )
                    )
                xy = []
                last_x = None
                ys = []
                for x_value, y_value in xy_raw:
                    if x_value != last_x:
                        if ys:
                            xy.append((last_x, round(sum(ys) / len(ys))))
                            ys = []
                        last_x = x_value
                    ys.append(y_value)
                if ys:
                    xy.append((last_x, round(sum(ys) / len(ys))))
                if len(xy) < 2:
                    continue
                area_fill = plot.get("area_fill")
                if area_fill:
                    baseline_y = diag_y + diag_height - 1
                    draw.polygon(
                        [(xy[0][0], baseline_y)] + xy + [(xy[-1][0], baseline_y)],
                        fill=get_index_color(area_fill),
                    )
                draw.line(
                    xy,
                    fill=get_index_color(plot.get("color", "black")) or BLACK,
                    width=_int(plot.get("width", 1), 1),
                    joint=plot.get("joint"),
                )

            if ylegend is not None:
                if ylegend_pos == "left":
                    draw.text((x_start, y_start), str(max_value), fill=ylegend_color, font=ylegend_font, anchor="lt")
                    draw.text((x_start, diag_y + diag_height - 1), str(min_value), fill=ylegend_color, font=ylegend_font, anchor="ls")
                elif ylegend_pos == "right":
                    draw.text((x_end, y_start), str(max_value), fill=ylegend_color, font=ylegend_font, anchor="rt")
                    draw.text((x_end, diag_y + diag_height - 1), str(min_value), fill=ylegend_color, font=ylegend_font, anchor="rs")

            if yaxis is not None:
                draw.rectangle(
                    [(diag_x, diag_y), (diag_x + yaxis_width - 1, diag_y + diag_height - 1)],
                    fill=yaxis_color,
                    width=0,
                )
                if yaxis_tick_width > 0:
                    current = min_value
                    while current <= max_value:
                        current_y = round(
                            diag_y + (1 - ((current - min_value) / spread)) * (diag_height - 1)
                        )
                        draw.rectangle(
                            [
                                (diag_x + yaxis_width, current_y),
                                (diag_x + yaxis_width + yaxis_tick_width - 1, current_y),
                            ],
                            fill=yaxis_color,
                            width=0,
                        )
                        current += yaxis_tick_every

            if xlegend is not None:
                label_y = diag_y + diag_height + 2
                for index in range(xlegend_ticks):
                    ratio = index / max(xlegend_ticks - 1, 1)
                    label_x = round(diag_x + ratio * (diag_width - 1))
                    time_label = (start_time + duration * ratio).strftime(xlegend_format)
                    anchor = "lt" if index == 0 else "rt" if index == xlegend_ticks - 1 else "mt"
                    draw.text((label_x, label_y), time_label, fill=xlegend_color, font=xlegend_font, anchor=anchor)

        if element_type == "progress_bar":
            _check_required(
                element,
                ["x_start", "x_end", "y_start", "y_end", "progress"],
                "progress_bar",
            )
            draw = ImageDraw.Draw(image)
            x_start = _number(element["x_start"])
            y_start = _number(element["y_start"])
            x_end = _number(element["x_end"])
            y_end = _number(element["y_end"])
            progress = max(0, min(100, _number(element["progress"])))
            direction = element.get("direction", "right")
            bg_color = get_index_color(element.get("background", "white")) or WHITE
            fill_color = get_index_color(element.get("fill", "red")) or RED
            outline = get_index_color(element.get("outline", "black")) or BLACK
            line_width = _int(element.get("width", 1), 1)
            radius = _int(element.get("radius", 0), 0)

            _rounded_rectangle(
                draw,
                [(x_start, y_start), (x_end, y_end)],
                fill=bg_color,
                outline=outline,
                width=line_width,
                radius=radius,
            )
            if direction in ("right", "left"):
                progress_width = (x_end - x_start) * (progress / 100)
                if direction == "right":
                    fill_box = [(x_start, y_start), (x_start + progress_width, y_end)]
                else:
                    fill_box = [(x_end - progress_width, y_start), (x_end, y_end)]
            else:
                progress_height = (y_end - y_start) * (progress / 100)
                if direction == "up":
                    fill_box = [(x_start, y_end - progress_height), (x_end, y_end)]
                else:
                    fill_box = [(x_start, y_start), (x_end, y_start + progress_height)]
            _rounded_rectangle(
                draw,
                fill_box,
                fill=fill_color,
                outline=None,
                width=1,
                radius=radius,
            )
            _rounded_rectangle(
                draw,
                [(x_start, y_start), (x_end, y_end)],
                fill=None,
                outline=outline,
                width=line_width,
                radius=radius,
            )
            if element.get("show_percentage", False):
                font_size = max(1, min(_int(y_end - y_start - 4), _int(x_end - x_start - 4), 20))
                font = _load_font(_DEFAULT_FONT, font_size, hass)
                text = f"{_int(progress)}%"
                text_box = draw.textbbox((0, 0), text, font=font)
                text_x = (x_start + x_end - (text_box[2] - text_box[0])) / 2
                text_y = (y_start + y_end - (text_box[3] - text_box[1])) / 2
                text_color = bg_color if progress > 50 else fill_color
                draw.text((text_x, text_y), text, font=font, fill=text_color, anchor="lt")

    if rotate in (90, 180, 270):
        image = image.rotate(-rotate, expand=True)

    if image.size != (width, height):
        image = image.resize((width, height), Image.LANCZOS)

    return image.convert("RGB")
