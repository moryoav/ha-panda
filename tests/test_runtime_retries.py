"""Retry behavior tests for PANDA ESL packet writes."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

from homeassistant.exceptions import HomeAssistantError

bluetooth_stub = types.ModuleType("homeassistant.components.bluetooth")


class BluetoothChange:
    """Minimal Bluetooth change enum stub."""

    ADVERTISEMENT = "advertisement"


class BluetoothScanningMode:
    """Minimal Bluetooth scanning mode enum stub."""

    ACTIVE = "active"


class BluetoothServiceInfoBleak:
    """Minimal Bluetooth service-info stub for imports."""


bluetooth_stub.BluetoothChange = BluetoothChange
bluetooth_stub.BluetoothScanningMode = BluetoothScanningMode
bluetooth_stub.BluetoothServiceInfoBleak = BluetoothServiceInfoBleak
bluetooth_stub.async_ble_device_from_address = lambda *_args, **_kwargs: None
bluetooth_stub.async_last_service_info = lambda *_args, **_kwargs: None
bluetooth_stub.async_register_callback = lambda *_args, **_kwargs: None
bluetooth_stub.async_track_unavailable = lambda *_args, **_kwargs: None
sys.modules.setdefault("homeassistant.components.bluetooth", bluetooth_stub)

PACKAGE_NAME = "panda_esl_runtime_tests"
PACKAGE_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "panda_esl"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(PACKAGE_DIR)]
sys.modules.setdefault(PACKAGE_NAME, package)


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


panda_runtime = _load_submodule("runtime")
PandaEslState = _load_submodule("models").PandaEslState


ADDRESS = "48:87:2D:C4:90:EA"
ORIGINAL_ASYNCIO_SLEEP = asyncio.sleep


class FakeCoordinator:
    """Capture coordinator updates."""

    def __init__(self) -> None:
        self.snapshots: list[dict[str, Any]] = []

    def async_set_updated_data(self, state: PandaEslState) -> None:
        """Record progress snapshots without copying the whole state object."""
        self.snapshots.append(
            {
                "chunks_written": state.write_progress_chunks_written,
                "percent": state.write_progress_percent,
                "active": state.write_progress_active,
            }
        )


class FakeHass:
    """Minimal Home Assistant object used by the packet writer."""

    config = SimpleNamespace(path=lambda: ".")

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        """Run executor jobs synchronously for tests."""
        return func(*args)


class FakeBleClient:
    """BleakClient replacement that emits deterministic PANDA ACKs."""

    def __init__(
        self,
        *,
        drop_once: set[tuple[int, int]] | None = None,
        always_drop: set[tuple[int, int]] | None = None,
        start_notify_error: Exception | None = None,
    ) -> None:
        self.drop_once = drop_once or set()
        self.always_drop = always_drop or set()
        self.start_notify_error = start_notify_error
        self.notify_callback: Any | None = None
        self.writes: list[bytes] = []
        self.write_counts: dict[tuple[int, int], int] = {}
        self.is_connected = True
        self.services = SimpleNamespace(
            get_characteristic=lambda _uuid: SimpleNamespace(
                properties=["notify", "write", "write-without-response"],
                max_write_without_response_size=241,
            )
        )

    async def start_notify(self, _uuid: str, callback: Any) -> None:
        """Start notifications or raise a configured setup error."""
        if self.start_notify_error is not None:
            raise self.start_notify_error
        self.notify_callback = callback

    async def stop_notify(self, _uuid: str) -> None:
        """Stop notifications."""

    async def disconnect(self) -> None:
        """Mark the fake client disconnected."""
        self.is_connected = False

    async def write_gatt_char(
        self, _uuid: str, packet: bytes, *, response: bool = False
    ) -> None:
        """Record writes and emit matching ACK notifications."""
        self.writes.append(packet)
        decoded = panda_runtime._decode_packet(packet)
        kind = decoded.get("kind")
        if kind == "image_chunk":
            key = (int(decoded["plane"]), int(decoded["chunk_index"]))
            count = self.write_counts.get(key, 0)
            self.write_counts[key] = count + 1
            if key in self.always_drop or (key in self.drop_once and count == 0):
                return
            self._emit_chunk_ack(key[1])
        elif kind == "commit":
            self._emit(panda_runtime.PANDA_FINAL_ACK)
        if self.notify_callback is not None:
            await ORIGINAL_ASYNCIO_SLEEP(0)

    def _emit_chunk_ack(self, chunk_index: int) -> None:
        ack = b"\x91\x02" + int(chunk_index).to_bytes(3, "little") + b"\x19"
        self._emit(ack)

    def _emit(self, data: bytes) -> None:
        assert self.notify_callback is not None
        self.notify_callback("sender", bytearray(data))


@pytest.fixture
def retry_test_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Speed up retry tests and stub the BLE device lookup."""

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(panda_runtime.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(panda_runtime, "PANDA_ACK_CHUNK_TIMEOUT_S", 0.05)
    monkeypatch.setattr(panda_runtime, "PANDA_ACK_FINAL_TIMEOUT_S", 0.05)
    monkeypatch.setattr(panda_runtime, "PANDA_ACK_INTER_PACKET_DELAY_MS", 0)
    monkeypatch.setattr(
        panda_runtime.bluetooth,
        "async_ble_device_from_address",
        lambda *_args, **_kwargs: object(),
    )


def _runtime_data() -> tuple[panda_runtime.PandaEslRuntimeData, FakeCoordinator]:
    coordinator = FakeCoordinator()
    runtime = panda_runtime.PandaEslRuntimeData(
        state=PandaEslState(address=ADDRESS),
        coordinator=coordinator,
        image_coordinator=FakeCoordinator(),
        preview_coordinator=FakeCoordinator(),
    )
    return runtime, coordinator


def _packets() -> list[bytes]:
    return [
        *panda_runtime._STANDARD_PREAMBLE,
        *panda_runtime._frame_image_chunks(0, b"x" * 60),
        bytes.fromhex("ac03ca"),
    ]


def _image_write_keys(client: FakeBleClient) -> list[tuple[int, int]]:
    keys: list[tuple[int, int]] = []
    for packet in client.writes:
        decoded = panda_runtime._decode_packet(packet)
        if decoded.get("kind") == "image_chunk":
            keys.append((int(decoded["plane"]), int(decoded["chunk_index"])))
    return keys


def _install_clients(
    monkeypatch: pytest.MonkeyPatch, clients: list[FakeBleClient]
) -> list[FakeBleClient]:
    used_clients: list[FakeBleClient] = []

    async def fake_establish_connection(
        _client_cls: Any, _ble_device: Any, _address: str
    ) -> FakeBleClient:
        client = clients.pop(0)
        used_clients.append(client)
        return client

    monkeypatch.setattr(
        panda_runtime, "establish_connection", fake_establish_connection
    )
    return used_clients


@pytest.mark.usefixtures("retry_test_setup")
async def test_retry_count_zero_does_not_resend_failed_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry count of zero fails after the first missing chunk ACK."""
    client = FakeBleClient(always_drop={(0, 1)})
    _install_clients(monkeypatch, [client])
    runtime, _coordinator = _runtime_data()

    with pytest.raises(HomeAssistantError):
        await panda_runtime._async_send_packets(
            FakeHass(),
            runtime,
            packets=_packets(),
            action_key="test",
            result_name="write_test_ok",
            details={},
            write_delay_ms=0,
            retry_count=0,
        )

    assert _image_write_keys(client) == [(0, 0), (0, 1)]


@pytest.mark.usefixtures("retry_test_setup")
async def test_chunk_ack_timeout_uses_whole_write_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missed chunk ACK retries the whole write instead of duplicating a chunk."""
    failing_client = FakeBleClient(always_drop={(0, 1)})
    successful_client = FakeBleClient()
    used_clients = _install_clients(monkeypatch, [failing_client, successful_client])
    runtime, _coordinator = _runtime_data()

    await panda_runtime._async_send_packets(
        FakeHass(),
        runtime,
        packets=_packets(),
        action_key="test",
        result_name="write_test_ok",
        details={},
        write_delay_ms=0,
        retry_count=1,
    )

    assert used_clients == [failing_client, successful_client]
    assert _image_write_keys(failing_client) == [(0, 0), (0, 1)]
    assert _image_write_keys(successful_client) == [(0, 0), (0, 1)]
    attrs = runtime.state.write_action_results["test"]
    assert attrs["retry_count"] == 1
    assert attrs["chunk_retry_count"] == 0
    assert attrs["image_packets_confirmed"] == 2
    assert runtime.state.write_progress_chunks_written == 2


@pytest.mark.usefixtures("retry_test_setup")
async def test_failed_chunk_uses_configured_whole_write_retry_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persistent chunk timeout creates retry_count extra write attempts."""
    clients = [FakeBleClient(always_drop={(0, 1)}) for _ in range(4)]
    used_clients = _install_clients(monkeypatch, clients[:])
    runtime, _coordinator = _runtime_data()

    with pytest.raises(HomeAssistantError):
        await panda_runtime._async_send_packets(
            FakeHass(),
            runtime,
            packets=_packets(),
            action_key="test",
            result_name="write_test_ok",
            details={},
            write_delay_ms=0,
            retry_count=3,
        )

    assert used_clients == clients
    for client in used_clients:
        assert _image_write_keys(client) == [(0, 0), (0, 1)]


@pytest.mark.usefixtures("retry_test_setup")
async def test_non_chunk_failure_uses_whole_write_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Notification setup failures reconnect and retry the whole write."""
    failing_client = FakeBleClient(start_notify_error=RuntimeError("notify failed"))
    successful_client = FakeBleClient()
    used_clients = _install_clients(monkeypatch, [failing_client, successful_client])
    runtime, _coordinator = _runtime_data()

    await panda_runtime._async_send_packets(
        FakeHass(),
        runtime,
        packets=_packets(),
        action_key="test",
        result_name="write_test_ok",
        details={},
        write_delay_ms=0,
        retry_count=1,
    )

    assert used_clients == [failing_client, successful_client]
    assert failing_client.writes == []
    assert _image_write_keys(successful_client) == [(0, 0), (0, 1)]
