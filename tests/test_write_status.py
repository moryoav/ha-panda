"""Write outcome visibility and diagnostics regressions."""

from types import SimpleNamespace

import pytest

from test_runtime_retries import FakeHass, _load_submodule, _runtime_data

panda_sensor = _load_submodule("sensor")
panda_diagnostics = _load_submodule("diagnostics")


def test_write_status_tracks_error_retry_and_protocol_completion():
    """Errors are visible, retries show writing, and success clears the error."""
    runtime, _ = _runtime_data()
    entry = SimpleNamespace(data={}, title="Label")
    status = panda_sensor.PandaEslWriteStatusSensor(entry, runtime)
    progress = panda_sensor.PandaEslWriteProgressSensor(entry, runtime)
    assert status.native_value == "idle"
    runtime.state.update_write_progress(20, active=True)
    assert status.native_value == "writing"
    runtime.state.update_write_progress(20, active=False)
    runtime.state.update_write_action("service_write", "write_service_ok_error", "ACK timeout")
    assert status.native_value == "error"
    assert progress.extra_state_attributes["last_error"] == "ACK timeout"
    runtime.state.update_write_progress(0, active=True, attempt=2)
    runtime.state.update_write_action("service_write", "write_in_progress")
    assert status.native_value == "writing"
    runtime.state.update_write_progress(100, active=False)
    assert status.native_value == "writing"
    runtime.state.update_write_action("service_write", "write_service_ok")
    assert status.native_value == "transfer_complete"
    assert status.extra_state_attributes["last_error"] is None
    assert status.extra_state_attributes["last_write"] is not None
    runtime.state.update_write_action("service_write", "write_service_dry_run")
    assert status.native_value == "idle"
    runtime.state.update_write_action("service_write", "write_cancelled")
    assert status.native_value == "idle"


@pytest.mark.asyncio
async def test_diagnostics_import_and_report_service_error():
    """Diagnostics must load and include errors not tied to a button."""
    runtime, _ = _runtime_data()
    runtime.state.update_write_action("service_write", "write_service_ok_error", "ACK timeout")
    entry = SimpleNamespace(
        data={"address": runtime.state.address}, options={}, title="Label",
        entry_id="label", runtime_data=runtime, version=1, minor_version=1,
    )
    hass = FakeHass()
    hass.data = {}
    result = await panda_diagnostics.async_get_config_entry_diagnostics(hass, entry)
    assert result["runtime"]["last_write_error"] == "ACK timeout"
    assert result["runtime"]["address"] != runtime.state.address
    assert result["entry"]["data"]["address"] != runtime.state.address
