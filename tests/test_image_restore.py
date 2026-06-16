"""Restore data tests for PANDA ESL image entities."""

from __future__ import annotations

from datetime import timezone
import importlib.util
from pathlib import Path
import sys
import types
from typing import Any

from homeassistant.core import State

PACKAGE_NAME = "panda_esl_image_tests"
PACKAGE_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "panda_esl"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(PACKAGE_DIR)]
sys.modules.setdefault(PACKAGE_NAME, package)

runtime_stub = types.ModuleType(f"{PACKAGE_NAME}.runtime")
runtime_stub.PandaEslRuntimeData = object
sys.modules.setdefault(f"{PACKAGE_NAME}.runtime", runtime_stub)


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
panda_image = _load_submodule("image")

RESTORE_CONTENT_TYPE = panda_image.RESTORE_CONTENT_TYPE
RESTORE_DATA_VERSION = panda_image.RESTORE_DATA_VERSION
PandaEslImageExtraStoredData = panda_image.PandaEslImageExtraStoredData
_restored_image_timestamp = panda_image._restored_image_timestamp


def test_image_restore_data_round_trip() -> None:
    """Image restore data should serialize PNG bytes into JSON-safe data."""
    content = b"\x89PNG\r\n\x1a\npanda"
    restore_data = PandaEslImageExtraStoredData(content=content)

    restored = PandaEslImageExtraStoredData.from_dict(restore_data.as_dict())

    assert restored is not None
    assert restored.content == content
    assert restored.content_type == RESTORE_CONTENT_TYPE
    assert restored.version == RESTORE_DATA_VERSION


def test_invalid_image_restore_data_returns_none() -> None:
    """Malformed restore data should be ignored."""
    valid_content = PandaEslImageExtraStoredData(content=b"png").as_dict()["content"]

    assert PandaEslImageExtraStoredData.from_dict({}) is None
    assert (
        PandaEslImageExtraStoredData.from_dict(
            {
                "version": RESTORE_DATA_VERSION + 1,
                "content_type": RESTORE_CONTENT_TYPE,
                "content": valid_content,
            }
        )
        is None
    )
    assert (
        PandaEslImageExtraStoredData.from_dict(
            {
                "version": RESTORE_DATA_VERSION,
                "content_type": "image/jpeg",
                "content": valid_content,
            }
        )
        is None
    )
    assert (
        PandaEslImageExtraStoredData.from_dict(
            {
                "version": RESTORE_DATA_VERSION,
                "content_type": RESTORE_CONTENT_TYPE,
                "content": "not base64",
            }
        )
        is None
    )
    assert (
        PandaEslImageExtraStoredData.from_dict(
            {
                "version": RESTORE_DATA_VERSION,
                "content_type": RESTORE_CONTENT_TYPE,
                "content": "",
            }
        )
        is None
    )


def test_restored_image_timestamp_parses_valid_state() -> None:
    """Image restore should recover the previous image timestamp."""
    restored = _restored_image_timestamp(
        State("image.panda_esl_preview_content", "2026-06-16T06:14:22+00:00")
    )

    assert restored is not None
    assert restored.year == 2026
    assert restored.month == 6
    assert restored.day == 16
    assert restored.hour == 6
    assert restored.minute == 14
    assert restored.second == 22
    assert restored.tzinfo == timezone.utc


def test_restored_image_timestamp_ignores_empty_states() -> None:
    """Unavailable or missing image states should not restore a timestamp."""
    assert _restored_image_timestamp(None) is None
    assert (
        _restored_image_timestamp(
            State("image.panda_esl_preview_content", "unknown")
        )
        is None
    )
    assert (
        _restored_image_timestamp(
            State("image.panda_esl_preview_content", "unavailable")
        )
        is None
    )
