"""Retry behavior tests for PANDA ESL packet writes."""

from __future__ import annotations

import asyncio
import importlib.util
from io import BytesIO
from pathlib import Path
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

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
panda_models = _load_submodule("models")
panda_profiles = _load_submodule("profiles")
PandaEslState = panda_models.PandaEslState
ETAG_525_PROFILE = panda_profiles.ETAG_525_PROFILE
ETAG_526_PROFILE = panda_profiles.ETAG_526_PROFILE
ETAG_530_PROFILE = panda_profiles.ETAG_530_PROFILE
ETAG_534_PROFILE = panda_profiles.ETAG_534_PROFILE


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


class FakeImageCoordinator:
    """Capture image coordinator updates."""

    def __init__(self) -> None:
        self.data: bytes | None = None
        self.updates: list[bytes] = []

    def async_set_updated_data(self, data: bytes) -> None:
        """Record an image update."""
        self.data = data
        self.updates.append(data)


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
        battery_percentage: int | None = None,
        legacy_battery_response: bool = False,
        status_battery_response: bool = False,
    ) -> None:
        self.drop_once = drop_once or set()
        self.always_drop = always_drop or set()
        self.start_notify_error = start_notify_error
        self.battery_percentage = battery_percentage
        self.legacy_battery_response = legacy_battery_response
        self.status_battery_response = status_battery_response
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
        if (
            packet == panda_runtime.PANDA_DEVICE_INFO_REQUEST
            and self.battery_percentage is not None
            and not self.status_battery_response
        ):
            if self.legacy_battery_response:
                self._emit(
                    bytes(
                        (0x91, 0x05, 0x03, 0x02, self.battery_percentage, 0x19)
                    )
                )
            else:
                self._emit(
                    bytes(
                        (
                            0x91,
                            0x00,
                            0x03,
                            0x02,
                            0x00,
                            0x00,
                            0x00,
                            0x00,
                            0x00,
                            0x00,
                            self.battery_percentage,
                            0x19,
                        )
                    )
                )
        elif (
            packet == bytes.fromhex("ac07ca")
            and self.battery_percentage is not None
            and self.status_battery_response
        ):
            self._emit(bytes((0x91, 0x08, self.battery_percentage, 0x19)))
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


def _runtime_data(
    profile: Any = ETAG_525_PROFILE,
) -> tuple[panda_runtime.PandaEslRuntimeData, FakeCoordinator]:
    coordinator = FakeCoordinator()
    runtime = panda_runtime.PandaEslRuntimeData(
        state=PandaEslState(address=ADDRESS),
        coordinator=coordinator,
        image_coordinator=FakeImageCoordinator(),
        preview_coordinator=FakeImageCoordinator(),
        profile=profile,
    )
    return runtime, coordinator


def _packets() -> list[bytes]:
    return [
        *panda_runtime._STANDARD_PREAMBLE,
        *panda_runtime._frame_image_chunks(0, b"x" * 60),
        bytes.fromhex("ac03ca"),
    ]


def _service_info(
    name: str,
    *,
    address: str = ADDRESS,
    local_name: str | None = None,
) -> SimpleNamespace:
    """Return a minimal Bluetooth advertisement for profile tests."""
    return SimpleNamespace(
        address=address,
        name=name,
        local_name=local_name,
        rssi=-50,
        source="test",
        service_uuids=[panda_runtime.PANDA_FFE1_CHAR_UUID],
        manufacturer_data={},
    )


def _image_chunks(packets: list[bytes], plane: int) -> list[bytes]:
    """Return image packets for one color plane."""
    return [
        packet
        for packet in packets
        if (decoded := panda_runtime._decode_packet(packet)).get("kind")
        == "image_chunk"
        and decoded.get("plane") == plane
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


@pytest.mark.parametrize(
    ("tag_id", "expected_profile"),
    [
        ("ETAG-52500033D0", ETAG_525_PROFILE),
        ("etag-52600013a5", ETAG_526_PROFILE),
        ("ETAG-53000033D0", ETAG_530_PROFILE),
        ("etag-53400013a5", ETAG_534_PROFILE),
    ],
)
def test_device_profile_is_encoded_in_tag_id(
    tag_id: str,
    expected_profile: Any,
) -> None:
    """Supported display geometry should be selected from the advertised ID."""
    assert panda_profiles.device_profile_from_tag_id(tag_id) == expected_profile


@pytest.mark.parametrize(
    "tag_id",
    [
        "ETAG-52400033D0",
        "ETAG-52700033D0",
        "ETAG-53100033D0",
        "ETAG-53300033D0",
        "ETAG-53500033D0",
        "ETAG-525",
        "ETAG-52600013A5-extra",
        "HOLY-IOT",
        "",
    ],
)
def test_unsupported_tag_ids_have_no_profile(tag_id: str) -> None:
    """Unknown device families must not inherit the 2.13-inch geometry."""
    assert panda_profiles.device_profile_from_tag_id(tag_id) is None


def test_supported_device_filter_uses_name_and_local_name() -> None:
    """Discovery should accept only recognized IDs from either name field."""
    assert panda_models.service_info_supported(_service_info("ETAG-52500033D0"))
    assert panda_models.service_info_supported(
        _service_info("Generic BLE", local_name="ETAG-52600013A5")
    )
    assert panda_models.service_info_supported(_service_info("ETAG-53000033D0"))
    assert panda_models.service_info_supported(
        _service_info("Generic BLE", local_name="ETAG-53400013A5")
    )
    assert not panda_models.service_info_supported(_service_info("ETAG-52700033D0"))


def test_target_match_does_not_cross_update_supported_tags() -> None:
    """A callback for one configured tag must ignore another supported tag."""
    other = _service_info(
        "ETAG-52600013A5",
        address="48:87:2D:C5:AA:7B",
    )

    assert not panda_models.service_info_matches_target(other, ADDRESS)
    assert panda_models.service_info_matches_target(other, other.address)


@pytest.mark.parametrize(
    ("notification", "expected"),
    [
        (bytes.fromhex("910003020000000000006419"), 100),
        (bytes.fromhex("910503026419"), 100),
        (bytes.fromhex("91086419"), 100),
        (bytes.fromhex("910003020000000000006519"), None),
        (bytes.fromhex("91086519"), None),
        (bytes.fromhex("91060019"), None),
        (bytes.fromhex("9100030200000000000064"), None),
    ],
)
def test_battery_percentage_notification_parser(
    notification: bytes,
    expected: int | None,
) -> None:
    """Device-info responses should expose only valid battery percentages."""
    assert panda_runtime._battery_percentage_from_notification(notification) == expected


def test_only_etag_530_uses_active_high_black_plane() -> None:
    """The ETAG-530 hardware inverts the black plane relative to other tags."""
    assert ETAG_530_PROFILE.black_plane_active_high is True
    assert all(
        profile.black_plane_active_high is False
        for profile in (ETAG_525_PROFILE, ETAG_526_PROFILE, ETAG_534_PROFILE)
    )


def test_only_etag_534_uses_row_major_framebuffer() -> None:
    """The ETAG-534 controller consumes complete rows instead of columns."""
    assert ETAG_534_PROFILE.row_major is True
    assert all(
        profile.row_major is False
        for profile in (ETAG_525_PROFILE, ETAG_526_PROFILE, ETAG_530_PROFILE)
    )


@pytest.mark.parametrize(
    ("profile", "plane_bytes", "chunks_per_plane", "packet_count", "tail_bytes"),
    [
        (ETAG_525_PROFILE, 4096, 82, 168, 46),
        (ETAG_526_PROFILE, 5624, 113, 230, 24),
        (ETAG_530_PROFILE, 10800, 216, 436, 50),
        (ETAG_534_PROFILE, 15000, 300, 604, 50),
    ],
)
@pytest.mark.parametrize(
    ("color", "expected_plane_bytes"),
    [
        ("white", (b"\xff", b"\x00")),
        ("black", (b"\x00", b"\x00")),
        ("red", (b"\xff", b"\xff")),
    ],
)
def test_fill_packet_geometry(
    profile: Any,
    plane_bytes: int,
    chunks_per_plane: int,
    packet_count: int,
    tail_bytes: int,
    color: str,
    expected_plane_bytes: tuple[bytes, bytes],
) -> None:
    """Every fill should replace both color planes for every supported profile."""
    packets = panda_runtime._build_fill_packets(color, profile)

    assert profile.plane_byte_count == plane_bytes
    assert len(packets) == packet_count
    assert packets[: len(panda_runtime._STANDARD_PREAMBLE)] == list(
        panda_runtime._STANDARD_PREAMBLE
    )
    assert packets[-1] == bytes.fromhex("ac03ca")
    image_planes = [
        int(decoded["plane"])
        for packet in packets
        if (decoded := panda_runtime._decode_packet(packet)).get("kind")
        == "image_chunk"
    ]
    assert image_planes == [0] * chunks_per_plane + [1] * chunks_per_plane
    for plane, expected_byte in enumerate(expected_plane_bytes):
        if plane == 0 and profile.black_plane_active_high:
            expected_byte = bytes([expected_byte[0] ^ 0xFF])
        chunks = _image_chunks(packets, plane)
        decoded = [panda_runtime._decode_packet(packet) for packet in chunks]
        payload = b"".join(packet[9:-1] for packet in chunks)

        assert len(chunks) == chunks_per_plane
        assert [item["chunk_index"] for item in decoded] == list(
            range(chunks_per_plane)
        )
        assert {item["chunk_total"] for item in decoded} == {chunks_per_plane}
        assert decoded[-1]["actual_payload_len"] == tail_bytes
        assert payload == expected_byte * plane_bytes


def test_fill_packet_builder_rejects_unknown_color() -> None:
    """Unknown fill names should fail instead of sending an ambiguous image."""
    with pytest.raises(ValueError, match="Unknown fill color"):
        panda_runtime._build_fill_packets("blue", ETAG_525_PROFILE)


@pytest.mark.parametrize(
    ("color", "expected_plane_bytes"),
    [
        ("white", (b"\x00", b"\x00")),
        ("black", (b"\xff", b"\x00")),
        ("red", (b"\x00", b"\xff")),
    ],
)
def test_etag_530_fill_corrects_black_plane_polarity(
    color: str,
    expected_plane_bytes: tuple[bytes, bytes],
) -> None:
    """ETAG-530 fills should use active-high black-plane payloads."""
    packets = panda_runtime._build_fill_packets(color, ETAG_530_PROFILE)

    for plane, expected_byte in enumerate(expected_plane_bytes):
        payload = b"".join(
            packet[9:-1] for packet in _image_chunks(packets, plane)
        )
        assert payload == expected_byte * ETAG_530_PROFILE.plane_byte_count


@pytest.mark.parametrize(
    ("profile", "width", "height", "chunks_per_plane", "plane_bytes"),
    [
        (ETAG_526_PROFILE, 296, 152, 113, 5624),
        (ETAG_530_PROFILE, 360, 240, 216, 10800),
        (ETAG_534_PROFILE, 400, 300, 300, 15000),
    ],
)
def test_rendered_image_uses_profile_canvas_and_planes(
    profile: Any,
    width: int,
    height: int,
    chunks_per_plane: int,
    plane_bytes: int,
) -> None:
    """Rendered writes should preserve each supported non-default canvas."""
    source = Image.new(
        "RGB",
        (profile.width, profile.height),
        "white",
    )

    packets, preview_png, details = panda_runtime.build_packets_from_rendered_image(
        source,
        profile=profile,
    )

    with Image.open(BytesIO(preview_png)) as preview:
        assert preview.size == (width, height)
    assert len(_image_chunks(packets, 0)) == chunks_per_plane
    assert len(_image_chunks(packets, 1)) == chunks_per_plane
    assert details["device_profile"] == profile.key
    assert details["canvas_width"] == width
    assert details["canvas_height"] == height
    assert details["plane_byte_count"] == plane_bytes
    assert details["black_plane_active_high"] is profile.black_plane_active_high
    assert details["framebuffer_layout"] == (
        "row_major" if profile.row_major else "column_major"
    )
    assert details["pixel_counts"] == {
        "white": width * height,
        "black": 0,
        "red": 0,
    }


@pytest.mark.parametrize(
    ("color", "expected_rgb", "expected_plane_bytes"),
    [
        ("white", (255, 255, 255), (b"\x00", b"\x00")),
        ("black", (0, 0, 0), (b"\xff", b"\x00")),
        ("red", (255, 0, 0), (b"\x00", b"\xff")),
    ],
)
def test_etag_530_rendered_images_correct_black_plane_polarity(
    color: str,
    expected_rgb: tuple[int, int, int],
    expected_plane_bytes: tuple[bytes, bytes],
) -> None:
    """Rendered ETAG-530 colors should be encoded with corrected polarity."""
    source = Image.new("RGB", (1, 1), color)

    packets, preview_png, _details = panda_runtime.build_packets_from_rendered_image(
        source,
        profile=ETAG_530_PROFILE,
    )

    with Image.open(BytesIO(preview_png)) as preview:
        assert preview.getpixel((0, 0)) == expected_rgb
    for plane, expected_byte in enumerate(expected_plane_bytes):
        payload = b"".join(
            packet[9:-1] for packet in _image_chunks(packets, plane)
        )
        assert payload == expected_byte * ETAG_530_PROFILE.plane_byte_count


def test_etag_530_framed_image_corrects_black_plane_polarity() -> None:
    """The diagnostic frame should apply ETAG-530 black-plane polarity."""
    canonical_plane0, canonical_plane1 = panda_runtime._encode_pixels_plane01(
        panda_runtime._build_framed_pixels(ETAG_530_PROFILE)
    )
    packets = panda_runtime._build_framed_packets(ETAG_530_PROFILE)

    encoded_plane0 = b"".join(
        packet[9:-1] for packet in _image_chunks(packets, 0)
    )
    encoded_plane1 = b"".join(
        packet[9:-1] for packet in _image_chunks(packets, 1)
    )
    assert encoded_plane0 == bytes(value ^ 0xFF for value in canonical_plane0)
    assert encoded_plane1 == canonical_plane1


def test_etag_534_packs_rows_left_to_right() -> None:
    """The ETAG-534 framebuffer consists of 300 rows of 50 bytes each."""
    pixels = [
        [0, 1, 2, 0, 1, 2, 0, 1],
        [1, 0, 2, 1, 0, 2, 1, 0],
    ]

    column_plane0, column_plane1 = panda_runtime._encode_pixels_plane01(pixels)
    row_plane0, row_plane1 = panda_runtime._encode_pixels_plane01(
        pixels,
        row_major=ETAG_534_PROFILE.row_major,
    )

    assert len(column_plane0) == len(column_plane1) == 8
    assert (row_plane0, row_plane1) == (b"\x6d\xb6", b"\x24\x24")
    assert ETAG_534_PROFILE.plane_byte_count == 15000
    assert ETAG_534_PROFILE.row_major is True


@pytest.mark.usefixtures("retry_test_setup")
@pytest.mark.parametrize(
    ("profile", "packet_count", "image_packet_count"),
    [
        (ETAG_526_PROFILE, 231, 226),
        (ETAG_530_PROFILE, 437, 432),
        (ETAG_534_PROFILE, 605, 600),
    ],
)
async def test_non_default_profile_full_write_completes_two_ack_cycles(
    monkeypatch: pytest.MonkeyPatch,
    profile: Any,
    packet_count: int,
    image_packet_count: int,
) -> None:
    """Larger profiles should confirm every chunk and the final commit."""
    client = FakeBleClient()
    _install_clients(monkeypatch, [client])
    runtime, _coordinator = _runtime_data(profile)

    await panda_runtime._async_send_packets(
        FakeHass(),
        runtime,
        packets=panda_runtime._build_fill_packets("white", profile),
        action_key="white_fill",
        result_name="write_white_fill_ok",
        details={},
        write_delay_ms=0,
        retry_count=0,
    )

    attrs = runtime.state.write_action_results["white_fill"]
    assert len(client.writes) == packet_count
    assert attrs["device_profile"] == profile.key
    assert attrs["framebuffer_layout"] == (
        "row_major" if profile.row_major else "column_major"
    )
    assert attrs["image_packets_written"] == image_packet_count
    assert attrs["image_packets_confirmed"] == image_packet_count
    assert attrs["ack_progress_count"] == image_packet_count
    assert attrs["ack_cycle_count"] == 2
    assert attrs["ack_final_seen"] is True
    assert runtime.state.write_progress_chunks_total == image_packet_count
    assert runtime.state.write_progress_percent == 100.0
    assert client.writes[0] == panda_runtime.PANDA_DEVICE_INFO_REQUEST


@pytest.mark.usefixtures("retry_test_setup")
@pytest.mark.parametrize("legacy_response", [False, True])
async def test_display_write_updates_battery_from_device_info_notification(
    monkeypatch: pytest.MonkeyPatch,
    legacy_response: bool,
) -> None:
    """A display write should query and publish the reported battery percentage."""
    client = FakeBleClient(
        battery_percentage=87,
        legacy_battery_response=legacy_response,
    )
    _install_clients(monkeypatch, [client])
    runtime, _coordinator = _runtime_data()

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

    attrs = runtime.state.write_action_results["test"]
    assert client.writes[0] == panda_runtime.PANDA_DEVICE_INFO_REQUEST
    assert client.writes.count(panda_runtime.PANDA_DEVICE_INFO_REQUEST) == 1
    assert runtime.state.battery_percentage == 87
    assert runtime.state.battery_last_updated is not None
    assert attrs["battery_query_sent"] is True
    assert attrs["battery_percentage"] == 87


@pytest.mark.usefixtures("retry_test_setup")
@pytest.mark.parametrize(
    ("write_fn", "action_key", "expected_rgb"),
    [
        (panda_runtime.async_write_white_fill, "white_fill", (255, 255, 255)),
        (panda_runtime.async_write_black_fill, "black_fill", (0, 0, 0)),
        (panda_runtime.async_write_red_fill, "red_fill", (255, 0, 0)),
        (
            panda_runtime.async_write_nearfinal_framed_image,
            "framed_image",
            None,
        ),
    ],
)
async def test_diagnostic_write_updates_battery_preview_and_last_content(
    monkeypatch: pytest.MonkeyPatch,
    write_fn: Any,
    action_key: str,
    expected_rgb: tuple[int, int, int] | None,
) -> None:
    """Diagnostic writes should publish their image and observed status battery."""
    client = FakeBleClient(
        battery_percentage=100,
        status_battery_response=True,
    )
    _install_clients(monkeypatch, [client])
    runtime, _coordinator = _runtime_data()

    await write_fn(FakeHass(), runtime)

    preview = runtime.preview_coordinator
    last_updated = runtime.image_coordinator
    assert preview.data is not None
    assert preview.updates == [preview.data]
    assert last_updated.data == preview.data
    assert last_updated.updates == [preview.data]
    with Image.open(BytesIO(preview.data)) as image:
        assert image.size == (runtime.profile.width, runtime.profile.height)
        if expected_rgb is not None:
            center = (runtime.profile.width // 2, runtime.profile.height // 2)
            assert image.getpixel(center) == expected_rgb
        else:
            assert image.getpixel((12, 14)) == (0, 0, 0)
            assert image.getpixel((12, runtime.profile.height - 15)) == (255, 0, 0)

    attrs = runtime.state.write_action_results[action_key]
    assert runtime.state.battery_percentage == 100
    assert attrs["battery_percentage"] == 100
    assert runtime.state.last_write_details[0]["battery_response"] == "91086419"


@pytest.mark.usefixtures("retry_test_setup")
async def test_failed_diagnostic_write_does_not_update_last_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview should render before a write, while last content requires success."""
    monkeypatch.setattr(
        panda_runtime.bluetooth,
        "async_ble_device_from_address",
        lambda *_args, **_kwargs: None,
    )
    runtime, _coordinator = _runtime_data()

    with pytest.raises(HomeAssistantError):
        await panda_runtime.async_write_white_fill(FakeHass(), runtime)

    assert runtime.preview_coordinator.data is not None
    assert runtime.preview_coordinator.updates == [
        runtime.preview_coordinator.data
    ]
    assert runtime.image_coordinator.data is None
    assert runtime.image_coordinator.updates == []


@pytest.mark.usefixtures("retry_test_setup")
async def test_missing_battery_response_does_not_block_display_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tags that do not answer the optional query should still update normally."""
    client = FakeBleClient()
    _install_clients(monkeypatch, [client])
    runtime, _coordinator = _runtime_data()

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

    attrs = runtime.state.write_action_results["test"]
    assert runtime.state.battery_percentage is None
    assert attrs["battery_query_sent"] is True
    assert attrs["battery_percentage"] is None
    assert runtime.state.write_progress_percent == 100.0


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
