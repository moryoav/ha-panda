"""Quality metadata tests for the PANDA ESL custom integration."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "panda_esl"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _quality_scale_text() -> str:
    return (INTEGRATION / "quality_scale.yaml").read_text(encoding="utf-8")


def _quality_scale_rules() -> dict:
    data = yaml.safe_load(_quality_scale_text())
    return data["rules"]


def test_manifest_advertises_gold_quality_scale() -> None:
    """Manifest should expose the current release and gold quality scale."""
    manifest = _json(INTEGRATION / "manifest.json")

    assert manifest["domain"] == "panda_esl"
    assert manifest["integration_type"] == "device"
    assert manifest["iot_class"] == "local_push"
    assert manifest["quality_scale"] == "gold"
    assert manifest["version"] == "0.1.5"
    assert manifest["config_flow"] is True
    assert manifest["codeowners"] == ["@moryoav"]


def test_quality_scale_file_tracks_gold_rules() -> None:
    """The quality checklist should cover all implemented gold-era rules."""
    rules = _quality_scale_rules()
    required_rules = {
        "action_setup",
        "config_flow",
        "runtime_data",
        "action_exceptions",
        "config_entry_unloading",
        "entity_unavailable",
        "log_when_unavailable",
        "parallel_updates",
        "devices",
        "diagnostics",
        "discovery",
        "entity_category",
        "entity_disabled_by_default",
        "entity_translations",
        "exception_translations",
        "icon_translations",
        "reconfiguration_flow",
        "stale_devices",
    }

    for rule in required_rules:
        assert rules[rule] == "done"

    assert rules["test_coverage"]["status"] == "exempt"


def test_translations_cover_entities_services_and_exceptions() -> None:
    """English translations should mirror the base strings metadata."""
    strings = _json(INTEGRATION / "strings.json")
    translations = _json(INTEGRATION / "translations" / "en.json")

    assert translations == strings
    assert set(strings["services"]) == {"write", "write_guarded"}
    assert set(strings["entity"]) == {"button", "image", "switch"}
    assert set(strings["entity"]["button"]) == {
        "white_fill",
        "black_fill",
        "red_fill",
        "framed_image",
    }
    assert set(strings["entity"]["image"]) == {
        "last_updated_content",
        "preview_content",
    }
    assert set(strings["entity"]["switch"]) == {
        "write_lock",
        "packet_notification_capture",
    }
    assert {
        "target_device_required",
        "no_ble_device",
        "ack_timeout",
        "missing_required_element_arguments",
        "download_image_failed",
        "no_recorded_data",
    }.issubset(strings["exceptions"])


def test_icon_translations_cover_all_translated_entities() -> None:
    """Every translated entity key should have icon metadata."""
    strings = _json(INTEGRATION / "strings.json")
    icons = _json(INTEGRATION / "icons.json")

    for platform, entities in strings["entity"].items():
        assert set(icons["entity"][platform]) == set(entities)
        for icon_meta in icons["entity"][platform].values():
            assert icon_meta["default"].startswith("mdi:")


def test_documentation_and_changelog_reference_current_version() -> None:
    """Docs should include the newly documented quality-scale surfaces."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "## 0.1.5 - 2026-06-11" in changelog
    assert "Download diagnostics" in readme
    assert "Reconfigure" in readme
    assert "Supported Devices" in readme
    assert "Known Limitations" in readme
