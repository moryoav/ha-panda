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
    assert manifest["version"] == "0.1.16"
    assert manifest["config_flow"] is True
    assert manifest["codeowners"] == ["@moryoav"]
    assert {
        matcher["local_name"]
        for matcher in manifest["bluetooth"]
        if "local_name" in matcher
    } == {"ETAG-525*", "ETAG-526*"}
    assert all("manufacturer_id" not in matcher for matcher in manifest["bluetooth"])


def test_hacs_uses_zip_release_asset() -> None:
    """HACS should install the small release artifact, not optional repo assets."""
    hacs = _json(ROOT / "hacs.json")

    assert hacs["zip_release"] is True
    assert hacs["filename"] == "panda_esl.zip"
    assert hacs["hide_default_branch"] is True


def test_font_package_keeps_only_runtime_fonts() -> None:
    """Optional fonts should stay outside the HACS-installed integration."""
    integration_fonts = {
        path.name for path in (INTEGRATION / "fonts").iterdir() if path.is_file()
    }
    optional_fonts = {
        path.name for path in (ROOT / "optional_fonts").iterdir() if path.is_file()
    }

    assert integration_fonts == {
        "NotoSansKR-Regular.ttf",
        "NotoSansKR-Bold.ttf",
        "materialdesignicons-webfont.ttf",
        "materialdesignicons-webfont_meta.json",
    }
    assert {
        "GmarketSansTTFBold.ttf",
        "GmarketSansTTFMedium.ttf",
        "CookieRunRegular.ttf",
        "OwnglyphParkDaHyun.ttf",
    }.issubset(optional_fonts)


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
    assert set(strings["entity"]) == {"button", "image", "sensor", "switch"}
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
    assert set(strings["entity"]["sensor"]) == {
        "write_progress",
        "bluetooth_rssi",
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


def test_services_target_panda_esl_devices() -> None:
    """Services should select PANDA ESL devices using Home Assistant metadata."""
    services = yaml.safe_load((INTEGRATION / "services.yaml").read_text(encoding="utf-8"))

    for service_name in ("write", "write_guarded"):
        assert "target" not in services[service_name]
        device_selector = services[service_name]["fields"]["device_id"]["selector"][
            "device"
        ]
        assert device_selector == {
            "filter": [{"integration": "panda_esl"}],
            "multiple": True,
        }


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

    assert "## 0.1.16 - 2026-08-04" in changelog
    assert "@chrisrock1984" in changelog
    assert "## 0.1.14 - 2026-08-02" in changelog
    assert "@ruffoa" in changelog
    assert "optional_fonts" in changelog
    assert "panda_esl.zip" in changelog
    assert "Bluetooth RSSI" in readme
    assert "Write progress" in readme
    assert "Write retries" in readme
    assert "Download diagnostics" in readme
    assert "Reconfigure" in readme
    assert "Supported Devices" in readme
    assert "ETAG-525" in readme
    assert "ETAG-526" in readme
    assert "296x152" in readme
    assert "Known Limitations" in readme
    assert "config/panda_esl/fonts/" in readme
    assert "optional_fonts" in readme
