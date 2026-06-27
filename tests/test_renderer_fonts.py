"""Font lookup tests for the PANDA ESL renderer."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from types import SimpleNamespace
from typing import Any

PACKAGE_NAME = "panda_esl_renderer_tests"
PACKAGE_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "panda_esl"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(PACKAGE_DIR)]
sys.modules.setdefault(PACKAGE_NAME, package)

barcode_stub = types.ModuleType("barcode")
barcode_stub.get_barcode_class = lambda *_args, **_kwargs: None
barcode_writer_stub = types.ModuleType("barcode.writer")
barcode_writer_stub.ImageWriter = object
sys.modules.setdefault("barcode", barcode_stub)
sys.modules.setdefault("barcode.writer", barcode_writer_stub)

qrcode_stub = types.ModuleType("qrcode")
qrcode_stub.constants = SimpleNamespace(ERROR_CORRECT_H=1)
qrcode_stub.QRCode = object
sys.modules.setdefault("qrcode", qrcode_stub)

requests_stub = types.ModuleType("requests")
requests_stub.RequestException = Exception
requests_stub.get = lambda *_args, **_kwargs: None
sys.modules.setdefault("requests", requests_stub)


def _load_submodule(name: str) -> Any:
    module_name = f"{PACKAGE_NAME}.{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(
        module_name, PACKAGE_DIR / f"{name}.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_load_submodule("const")
renderer = _load_submodule("renderer")


def _fake_hass(config_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(path=lambda path="": str(config_root / path))
    )


def test_font_lookup_supports_private_config_font_dir(tmp_path: Path) -> None:
    """Old bundled font paths should resolve to copied user fonts."""
    font_file = tmp_path / "panda_esl" / "fonts" / "GmarketSansTTFBold.ttf"
    font_file.parent.mkdir(parents=True)
    font_file.write_bytes(b"font")

    resolved = renderer._get_font_file(
        "fonts/GmarketSansTTFBold.ttf",
        _fake_hass(tmp_path),
    )

    assert Path(resolved) == font_file


def test_font_lookup_keeps_www_font_dir_compatibility(tmp_path: Path) -> None:
    """The legacy www/fonts directory should still work."""
    font_file = tmp_path / "www" / "fonts" / "Custom.ttf"
    font_file.parent.mkdir(parents=True)
    font_file.write_bytes(b"font")

    resolved = renderer._get_font_file("Custom.ttf", _fake_hass(tmp_path))

    assert Path(resolved) == font_file


def test_mdi_icon_metadata_loads_compact_map() -> None:
    """Compacted MDI metadata should still resolve icon names."""
    renderer._MDI_MAP = None

    icon_map = renderer._load_mdi_icon_map()

    assert icon_map["sail-boat"]
    assert icon_map["format-color-fill"]
