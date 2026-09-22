"""Helpers for generating font preview images through the PANDA ESL renderer.

This loads ``custom_components/panda_esl/renderer.py`` without a running Home
Assistant instance so the previews use exactly the same drawing path as
``panda_esl.write`` with ``dry_run: true``.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "custom_components" / "panda_esl"
PACKAGE_NAME = "panda_esl_font_previews"


def _stub(name: str, **attrs: Any) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _install_stubs() -> None:
    _stub("barcode", get_barcode_class=lambda *_a, **_k: None)
    _stub("barcode.writer", ImageWriter=object)
    _stub("qrcode", constants=SimpleNamespace(ERROR_CORRECT_H=1), QRCode=object)
    _stub("requests", RequestException=Exception, get=lambda *_a, **_k: None)
    ha = _stub("homeassistant")
    ha.__path__ = []  # type: ignore[attr-defined]
    _stub("homeassistant.components")
    _stub("homeassistant.components.recorder")
    _stub(
        "homeassistant.components.recorder.history",
        get_significant_states=lambda *_a, **_k: {},
    )
    _stub("homeassistant.core", HomeAssistant=object)
    _stub("homeassistant.exceptions", HomeAssistantError=Exception)
    _stub("homeassistant.util", dt=SimpleNamespace(now=lambda: None))


def load_renderer() -> Any:
    """Import the renderer module with Home Assistant stubbed out."""
    _install_stubs()
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(PACKAGE_DIR)]  # type: ignore[attr-defined]
    sys.modules.setdefault(PACKAGE_NAME, package)
    for name in ("const", "renderer"):
        module_name = f"{PACKAGE_NAME}.{name}"
        if module_name in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(
            module_name, PACKAGE_DIR / f"{name}.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{PACKAGE_NAME}.renderer"]


def fake_hass(font_root: Path) -> SimpleNamespace:
    """Return a minimal ``hass`` whose ``panda_esl/fonts`` dir is ``font_root``."""

    def _path(path: str = "") -> str:
        if path.startswith("panda_esl/fonts"):
            return str(font_root / path.removeprefix("panda_esl/fonts").lstrip("/"))
        return str(font_root.parent / path)

    return SimpleNamespace(config=SimpleNamespace(path=_path))


def render(renderer: Any, hass: Any, payload: list[dict[str, Any]], width: int, height: int) -> Image.Image:
    """Render a payload to an RGB image, like the dry-run preview entity."""
    image = renderer.render_service_image(hass, {"payload": payload}, width, height)
    return image.convert("RGB")
