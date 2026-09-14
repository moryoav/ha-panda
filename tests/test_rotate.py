"""Mounting orientation, refresh, and queued-write regression tests."""

from __future__ import annotations

import asyncio
from functools import partial
from io import BytesIO
import logging
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from PIL import Image
import pytest

from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from test_renderer_fonts import renderer as panda_renderer
from test_runtime_retries import (
    ETAG_525_PROFILE,
    ETAG_526_PROFILE,
    ETAG_530_PROFILE,
    ETAG_534_PROFILE,
    FakeHass,
    _load_submodule,
    _runtime_data,
    panda_runtime,
)

# Reuse the renderer test harness for optional barcode/QR dependencies.
sys.modules.setdefault("panda_esl_runtime_tests.renderer", panda_renderer)
panda_init = _load_submodule("__init__")
panda_switch = _load_submodule("switch")
panda_image = _load_submodule("image")


def _setup(profile=ETAG_525_PROFILE):
    runtime, _ = _runtime_data(profile)
    entry = SimpleNamespace(
        entry_id="label",
        runtime_data=runtime,
        data={"name": "Label"},
        options={"retry_count": 2, "write_delay_ms": 25},
        title="Label",
    )
    hass = FakeHass()
    hass.data = {"panda_esl": {"label": {"last_image_data": None}}}

    def update(entry, *, data):
        entry.data = data

    hass.config_entries = SimpleNamespace(
        async_update_entry=update, async_get_entry=lambda _id: entry
    )
    image = Image.new("RGB", (profile.width, profile.height), "white")
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((1, 0), (0, 0, 0))
    packets, png, details = panda_runtime.build_packets_from_rendered_image(
        image, profile=profile
    )
    return hass, entry, image, packets, png, details


@pytest.mark.parametrize(
    "profile",
    [
        ETAG_525_PROFILE,
        ETAG_526_PROFILE,
        ETAG_530_PROFILE,
        ETAG_534_PROFILE,
    ],
)
async def test_rotate_refresh_round_trip(monkeypatch, profile):
    """Both orientations preserve colors and protocol geometry on every model."""
    hass, entry, image, packets, png, _ = _setup(profile)
    runtime = entry.runtime_data
    runtime.image_coordinator.data = png
    # An unsent preview/duplicate cache must never become the rotation source.
    runtime.preview_coordinator.data = b"unsent preview"
    hass.data["panda_esl"]["label"]["last_image_data"] = b"dry run"
    send = AsyncMock()
    monkeypatch.setattr(panda_runtime, "async_write_rendered_packets", send)

    await panda_runtime.async_set_rotation(hass, entry, True)

    expected_packets, expected_png, _ = panda_runtime.build_packets_from_rendered_image(
        image.transpose(Image.Transpose.ROTATE_180), profile=profile
    )
    assert send.call_args.kwargs["packets"] == expected_packets
    assert send.call_args.kwargs["retry_count"] == 2
    assert send.call_args.kwargs["write_delay_ms"] == 25
    assert runtime.image_coordinator.data == expected_png
    assert runtime.preview_coordinator.data == expected_png
    assert hass.data["panda_esl"]["label"]["last_image_data"] == expected_png
    assert entry.data["rotate"] is runtime.rotate is True
    assert entry.data["name"] == "Label"
    await panda_runtime.async_set_rotation(hass, entry, True)
    assert send.await_count == 1
    with Image.open(BytesIO(expected_png)) as rotated:
        assert rotated.getpixel((profile.width - 1, profile.height - 1)) == (255, 0, 0)
        assert rotated.getpixel((profile.width - 2, profile.height - 1)) == (0, 0, 0)

    await panda_runtime.async_set_rotation(hass, entry, False)

    assert send.call_args.kwargs["packets"] == packets
    assert runtime.image_coordinator.data == png
    assert entry.data["rotate"] is runtime.rotate is False


async def test_failed_refresh_keeps_orientation_and_successful_content(monkeypatch):
    hass, entry, _, _, png, _ = _setup()
    runtime = entry.runtime_data
    runtime.image_coordinator.data = png
    send = AsyncMock(side_effect=HomeAssistantError("offline"))
    monkeypatch.setattr(panda_runtime, "async_write_rendered_packets", send)
    entity = panda_switch.PandaEslRotateSwitch(hass, entry)
    monkeypatch.setattr(entity, "async_write_ha_state", lambda: None)

    with pytest.raises(HomeAssistantError, match="offline"):
        await entity.async_turn_on()

    assert entity.is_on is False
    assert entry.data == {"name": "Label"}
    assert runtime.image_coordinator.data == png
    assert runtime.preview_coordinator.data != png
    send.side_effect = None
    await entity.async_turn_on()
    assert entity.is_on is True
    assert send.await_count == 2


async def test_no_image_and_repeated_setting_do_not_send(monkeypatch):
    hass, entry, *_ = _setup()
    send = AsyncMock()
    monkeypatch.setattr(panda_runtime, "async_write_rendered_packets", send)
    other_runtime, _ = _runtime_data()

    await panda_runtime.async_set_rotation(hass, entry, True)
    await panda_runtime.async_set_rotation(hass, entry, True)

    assert entry.data["rotate"] is True
    assert other_runtime.rotate is False
    assert entry.runtime_data.image_coordinator.data is None
    send.assert_not_awaited()


async def test_write_lock_rejects_refresh(monkeypatch):
    hass, entry, _, _, png, _ = _setup()
    entry.runtime_data.image_coordinator.data = png
    hass.data["panda_esl"]["label"]["write_lock"] = True
    send = AsyncMock()
    monkeypatch.setattr(panda_runtime, "async_write_rendered_packets", send)

    with pytest.raises(HomeAssistantError) as error:
        await panda_runtime.async_set_rotation(hass, entry, True)

    assert error.value.translation_key == "rotation_write_locked"
    assert entry.runtime_data.rotate is False
    send.assert_not_awaited()


async def test_queued_service_uses_latest_orientation(monkeypatch):
    """A payload prepared before the switch changes must follow the new setting."""
    hass, entry, _, packets, png, details = _setup()
    runtime = entry.runtime_data
    context = {
        "runtime": runtime,
        "store": hass.data["panda_esl"]["label"],
        "options": entry.options,
        "packets": packets,
        "current_image_data": png,
        "details": details,
        "action_key": "service_write_guarded",
        "rotate": False,
    }
    await panda_runtime.async_set_rotation(hass, entry, True)
    send = AsyncMock()
    monkeypatch.setattr(panda_init, "async_write_rendered_packets", send)

    await panda_init._async_execute_service_write(hass, context)

    expected_packets, expected_png, _ = panda_runtime.rotate_image_packets(
        png, runtime.profile
    )
    assert send.call_args.kwargs["packets"] == expected_packets
    assert runtime.image_coordinator.data == expected_png
    assert context["rotate"] is True


async def test_rotation_waits_for_active_write(monkeypatch):
    """A concurrent toggle uses the image completed by the active transfer."""
    hass, entry, _, packets, png, details = _setup()
    runtime = entry.runtime_data
    started, finish = asyncio.Event(), asyncio.Event()

    async def active_send(*args, **kwargs):
        started.set()
        await finish.wait()

    monkeypatch.setattr(panda_init, "async_write_rendered_packets", active_send)
    rotation_send = AsyncMock()
    monkeypatch.setattr(panda_runtime, "async_write_rendered_packets", rotation_send)
    context = {
        "runtime": runtime,
        "store": hass.data["panda_esl"]["label"],
        "options": entry.options,
        "packets": packets,
        "current_image_data": png,
        "details": details,
        "action_key": "service_write",
        "rotate": False,
    }
    write = asyncio.create_task(panda_init._async_execute_service_write(hass, context))
    await started.wait()
    toggle = asyncio.create_task(panda_runtime.async_set_rotation(hass, entry, True))
    await asyncio.sleep(0)
    assert not toggle.done()
    rotation_send.assert_not_awaited()
    finish.set()
    await asyncio.gather(write, toggle)

    _, expected, _ = panda_runtime.rotate_image_packets(png, runtime.profile)
    assert runtime.image_coordinator.data == expected
    rotation_send.assert_awaited_once()


@pytest.mark.parametrize("service_rotation", [0, 90, 180, 270])
async def test_service_rotation_is_additive_and_preview_matches(
    monkeypatch, service_rotation
):
    hass, entry, *_ = _setup()
    service = SimpleNamespace(
        data={
            "rotate": service_rotation,
            "payload": [
                {
                    "type": "rectangle",
                    "x_start": 0,
                    "y_start": 0,
                    "x_end": 10,
                    "y_end": 15,
                    "fill": "red",
                }
            ],
        }
    )
    normal = await panda_init._async_build_service_context(
        hass, service, "label", guarded=False
    )
    entry.runtime_data.rotate = True
    rotated = await panda_init._async_build_service_context(
        hass, service, "label", guarded=False
    )
    expected_packets, expected_png, _ = panda_runtime.rotate_image_packets(
        normal["current_image_data"], entry.runtime_data.profile
    )
    assert rotated["packets"] == expected_packets
    assert rotated["current_image_data"] == expected_png
    assert entry.runtime_data.preview_coordinator.data == expected_png
    assert entry.runtime_data.image_coordinator.data is None


@pytest.mark.parametrize(
    "profile",
    [
        ETAG_525_PROFILE,
        ETAG_526_PROFILE,
        ETAG_530_PROFILE,
        ETAG_534_PROFILE,
    ],
)
@pytest.mark.parametrize("content", ["frame", "white", "black", "red"])
async def test_diagnostic_images_follow_rotation(monkeypatch, profile, content):
    hass, entry, *_ = _setup(profile)
    runtime = entry.runtime_data
    runtime.rotate = True
    send = AsyncMock()
    monkeypatch.setattr(panda_runtime, "_async_send_packets", send)

    if content == "frame":
        await panda_runtime.async_write_nearfinal_framed_image(hass, runtime)
        normal_png = panda_runtime._framed_preview_png(profile)
    else:
        await getattr(panda_runtime, f"async_write_{content}_fill")(hass, runtime)
        normal_png = panda_runtime._fill_preview_png(content, profile)

    expected_packets, expected_png, _ = panda_runtime.rotate_image_packets(
        normal_png, profile
    )
    assert send.call_args.kwargs["packets"] == expected_packets
    assert runtime.image_coordinator.data == expected_png
    assert runtime.preview_coordinator.data == expected_png


async def test_restored_image_can_be_rotated_back_after_restart(hass, monkeypatch):
    """Restore the transmitted PNG and use the persisted mounting orientation."""
    fake_hass, entry, _, _, png, _ = _setup()
    runtime = entry.runtime_data
    entry.data["rotate"] = runtime.rotate = True
    _, rotated_png, _ = panda_runtime.rotate_image_packets(png, runtime.profile)
    runtime.image_coordinator = DataUpdateCoordinator(
        hass, logging.getLogger(__name__), name="image", config_entry=None
    )
    entity = panda_image.PandaEslImageEntity(
        hass, entry, runtime.image_coordinator, "last_updated_content"
    )
    monkeypatch.setattr(panda_image.RestoreEntity, "async_added_to_hass", AsyncMock())
    monkeypatch.setattr(
        entity,
        "async_get_last_extra_data",
        AsyncMock(
            return_value=panda_image.PandaEslImageExtraStoredData(content=rotated_png)
        ),
    )
    monkeypatch.setattr(
        entity,
        "async_get_last_state",
        AsyncMock(return_value=State("image.label", "2026-09-14T12:00:00+00:00")),
    )

    await entity.async_added_to_hass()

    assert runtime.image_coordinator.data == rotated_png
    send = AsyncMock()
    monkeypatch.setattr(panda_runtime, "async_write_rendered_packets", send)
    await panda_runtime.async_set_rotation(fake_hass, entry, False)
    assert runtime.image_coordinator.data == png
    assert entry.data["rotate"] is False
    send.assert_awaited_once()


async def test_setup_restores_rotation_without_sending_blank_content(hass, monkeypatch):
    """Entry setup loads the setting before services or entities can write."""
    entry = SimpleNamespace(
        entry_id="label",
        data={
            "address": "48:87:2D:C4:90:EA",
            "discovered_name": "ETAG-5250000001",
            "rotate": True,
        },
        options={},
        title="Label",
        async_on_unload=Mock(),
    )
    monkeypatch.setattr(
        panda_init.bluetooth, "async_last_service_info", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        panda_init.bluetooth, "async_register_callback", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        panda_init.bluetooth, "async_track_unavailable", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        panda_init.dr,
        "async_get",
        lambda _: SimpleNamespace(
            async_get_or_create=lambda **kw: SimpleNamespace(id="device")
        ),
    )
    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", AsyncMock())
    monkeypatch.setattr(
        panda_init,
        "DataUpdateCoordinator",
        partial(DataUpdateCoordinator, config_entry=None),
    )

    assert await panda_init.async_setup_entry(hass, entry)

    assert entry.runtime_data.rotate is True
    assert entry.runtime_data.image_coordinator.data is None
    switch = panda_switch.PandaEslRotateSwitch(hass, entry)
    assert switch.is_on is True
    assert switch.translation_key == "rotate"
    assert switch.entity_category == "config"
