"""Generate the font preview gallery in ``images/font-previews``.

Every preview is rendered through ``render_service_image`` from the
integration, which is the same code path ``panda_esl.write`` uses for
``dry_run: true``. Text is drawn with Pillow's 1-bit font mode, so the images
show exactly the pixels that reach the label: there is no anti-aliasing.

Run from the repository root::

    python tools/generate_font_previews.py

Pixel fonts only look right when the requested size is a whole multiple of the
grid they were drawn on. Fonts with a ``grid`` value are therefore rendered at
the largest multiple that fits the canvas target instead of the target itself.
The chosen sizes are written to ``images/font-previews/sizes.json`` so the doc
can quote them.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent))
import font_preview_lib as lib  # noqa: E402

REPO_ROOT = lib.REPO_ROOT
OUTPUT_DIR = REPO_ROOT / "images" / "font-previews"
OPTIONAL_FONTS = REPO_ROOT / "optional_fonts"
BUNDLED_FONTS = REPO_ROOT / "custom_components" / "panda_esl" / "fonts"


@dataclass(frozen=True)
class Canvas:
    key: str
    width: int
    height: int
    title_size: int
    body_size: int
    title_y: int
    body_y: int
    suffix: str


CANVASES = (
    Canvas("2.13", 256, 128, 48, 32, 33, 78, ""),
    Canvas("2.66", 296, 152, 56, 40, 39, 92, "-266"),
)


@dataclass(frozen=True)
class FontSpec:
    name: str
    file: str  # payload ``font`` value (relative to config/panda_esl/fonts or bundled)
    slug: str
    group: str
    grid: int = 0  # native pixel grid of a pixel font; 0 = free outline font

    @property
    def path(self) -> Path:
        if self.file.startswith("fonts/"):
            return BUNDLED_FONTS / self.file.removeprefix("fonts/")
        return OPTIONAL_FONTS / self.file


FONTS: list[FontSpec] = [
    # Korean fonts that shipped with the original gallery.
    FontSpec("Noto Sans KR Thin", "NotoSansKR-Thin.ttf", "noto-sans-kr-thin", "korean"),
    FontSpec("Noto Sans KR ExtraLight", "NotoSansKR-ExtraLight.ttf", "noto-sans-kr-extralight", "korean"),
    FontSpec("Noto Sans KR Light", "NotoSansKR-Light.ttf", "noto-sans-kr-light", "korean"),
    FontSpec("Noto Sans KR Regular", "fonts/NotoSansKR-Regular.ttf", "noto-sans-kr-regular", "korean"),
    FontSpec("Noto Sans KR Medium", "NotoSansKR-Medium.ttf", "noto-sans-kr-medium", "korean"),
    FontSpec("Noto Sans KR SemiBold", "NotoSansKR-SemiBold.ttf", "noto-sans-kr-semibold", "korean"),
    FontSpec("Noto Sans KR Bold", "fonts/NotoSansKR-Bold.ttf", "noto-sans-kr-bold", "korean"),
    FontSpec("Noto Sans KR ExtraBold", "NotoSansKR-ExtraBold.ttf", "noto-sans-kr-extrabold", "korean"),
    FontSpec("Noto Sans KR Black", "NotoSansKR-Black.ttf", "noto-sans-kr-black", "korean"),
    FontSpec("Gmarket Sans Light", "GmarketSansTTFLight.ttf", "gmarket-sans-light", "korean"),
    FontSpec("Gmarket Sans Medium", "GmarketSansTTFMedium.ttf", "gmarket-sans-medium", "korean"),
    FontSpec("Gmarket Sans Bold", "GmarketSansTTFBold.ttf", "gmarket-sans-bold", "korean"),
    FontSpec("CookieRun Regular", "CookieRunRegular.ttf", "cookierun-regular", "korean"),
    FontSpec("CookieRun Bold", "CookieRunBold.ttf", "cookierun-bold", "korean"),
    FontSpec("CookieRun Black", "CookieRunBlack.ttf", "cookierun-black", "korean"),
    FontSpec("Ownglyph Park DaHyun", "OwnglyphParkDaHyun.ttf", "ownglyph-park-dahyun", "korean"),
    # Outline fonts designed and hinted for screens.
    FontSpec("Atkinson Hyperlegible Regular", "AtkinsonHyperlegible-Regular.ttf", "atkinson-hyperlegible-regular", "screen"),
    FontSpec("Atkinson Hyperlegible Bold", "AtkinsonHyperlegible-Bold.ttf", "atkinson-hyperlegible-bold", "screen"),
    FontSpec("B612 Regular", "B612-Regular.ttf", "b612-regular", "screen"),
    FontSpec("B612 Bold", "B612-Bold.ttf", "b612-bold", "screen"),
    FontSpec("DejaVu Sans", "DejaVuSans.ttf", "dejavu-sans", "screen"),
    FontSpec("DejaVu Sans Bold", "DejaVuSans-Bold.ttf", "dejavu-sans-bold", "screen"),
    FontSpec("Liberation Sans Regular", "LiberationSans-Regular.ttf", "liberation-sans-regular", "screen"),
    FontSpec("Liberation Sans Bold", "LiberationSans-Bold.ttf", "liberation-sans-bold", "screen"),
    # Pixel and bitmap-derived fonts.
    FontSpec("Silkscreen Regular", "Silkscreen-Regular.ttf", "silkscreen-regular", "pixel", grid=8),
    FontSpec("Silkscreen Bold", "Silkscreen-Bold.ttf", "silkscreen-bold", "pixel", grid=8),
    FontSpec("Press Start 2P", "PressStart2P-Regular.ttf", "press-start-2p", "pixel", grid=8),
    FontSpec("VT323", "VT323-Regular.ttf", "vt323", "pixel"),
    FontSpec("Pixelify Sans", "PixelifySans.ttf", "pixelify-sans", "pixel"),
    FontSpec("Tiny5", "Tiny5-Regular.ttf", "tiny5", "pixel", grid=8),
    FontSpec("Jersey 10", "Jersey10-Regular.ttf", "jersey-10", "pixel"),
    FontSpec("DotGothic16", "DotGothic16-Regular.ttf", "dotgothic16", "pixel", grid=16),
    FontSpec("Terminus TTF", "TerminusTTF.ttf", "terminus", "pixel"),
    FontSpec("Terminus TTF Bold", "TerminusTTF-Bold.ttf", "terminus-bold", "pixel"),
    FontSpec("Galmuri11", "Galmuri11.ttf", "galmuri11", "pixel", grid=12),
    FontSpec("Galmuri11 Bold", "Galmuri11-Bold.ttf", "galmuri11-bold", "pixel", grid=12),
    FontSpec("Galmuri14", "Galmuri14.ttf", "galmuri14", "pixel", grid=15),
]

SAMPLE_TITLE = "PANDA"
SAMPLE_BODY = "ABC 123"


def _payload(canvas: Canvas, font: str, title_size: int, body_size: int) -> list[dict[str, Any]]:
    return [
        {
            "type": "rectangle",
            "x_start": 0,
            "y_start": 0,
            "x_end": canvas.width - 1,
            "y_end": canvas.height - 1,
            "width": 2,
        },
        {
            "type": "text",
            "value": SAMPLE_TITLE,
            "x": canvas.width // 2,
            "y": canvas.title_y,
            "size": title_size,
            "font": font,
            "anchor": "mt",
        },
        {
            "type": "text",
            "value": SAMPLE_BODY,
            "x": canvas.width // 2,
            "y": canvas.body_y,
            "size": body_size,
            "font": font,
            "anchor": "mt",
        },
    ]


def grid_sizes(grid: int, canvas: Canvas) -> tuple[int, int]:
    """Pick title/body sizes that are whole multiples of a pixel font's grid."""
    title = max(grid, canvas.title_size // grid * grid)
    candidates = [size for size in range(grid, title, grid)] or [grid]
    body = min(candidates, key=lambda size: (abs(size - canvas.body_size), -size))
    return title, body


def main() -> None:
    renderer = lib.load_renderer()
    hass = lib.fake_hass(OPTIONAL_FONTS)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, dict[str, Any]] = {}

    for spec in FONTS:
        if not spec.path.exists():
            raise SystemExit(f"Missing font file: {spec.path}")
        record: dict[str, Any] = {"name": spec.name, "file": spec.file, "group": spec.group}
        if spec.grid:
            record["grid"] = spec.grid
        for canvas in CANVASES:
            title_size, body_size = canvas.title_size, canvas.body_size
            if spec.grid:
                title_size, body_size = grid_sizes(spec.grid, canvas)
            image = lib.render(
                renderer,
                hass,
                _payload(canvas, spec.file, title_size, body_size),
                canvas.width,
                canvas.height,
            )
            out = OUTPUT_DIR / f"{spec.slug}{canvas.suffix}.png"
            image.save(out, optimize=True)
            record[canvas.key] = {"title": title_size, "body": body_size}
        sizes[spec.slug] = record
        print(f"{spec.name:32s} 2.13: {record['2.13']}  2.66: {record['2.66']}  grid: {spec.grid or '-'}")

    with (OUTPUT_DIR / "sizes.json").open("w", encoding="utf-8") as handle:
        json.dump(sizes, handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
