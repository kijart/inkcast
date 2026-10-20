"""End to end: a fake display dials in over TCP and receives an image."""

import asyncio
import socket

from PIL import Image
from pyvisionect.devices.enums import PacketType
from pyvisionect.devices import Panel
from pyvisionect.devices.enums import ParamControl
from pyvisionect.packets import ParamItem, ParamPacket, StatusPacket
from pyvisionect.wire import Compression, DataHeader, Direction, FrameDecoder, encode_frame

from inkcast.config import Config, DeviceConfig
from inkcast.display import encode
from inkcast.server import InkcastServer

UUID = bytes.fromhex("00112233445566778899aabb00000000")
UUID_STR = "00112233-4455-6677-8899-aabb00000000"
JOAN6 = Panel(1024, 758, 1, "eink-generic")
# Status fields as a real Joan 6 (firmware 7.3.4358) reports them: a DisplayType (8)
# pyvisionect does not know, plus 1 display (7) of 1024x758 (38/39).
STATUS_TAGS = [
    (0, 3), (1, 0), (7, 1), (8, 0x501100EB), (9, 0xDB963A1A), (10, 100),
    (16, 7), (17, 4), (18, 4407), (22, 8), (27, 1), (40, 3), (43, 585), (54, 1),
    (38, 1024), (39, 758),
]


class FakeRenderer:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, tuple[int, int]]] = []
        self.fail = fail

    async def fetch(self, url: str, size: tuple[int, int]) -> Image.Image:
        self.calls.append((url, size))
        if self.fail:
            raise ConnectionError("page unreachable")
        return Image.new("RGB", size, "white")


def touch_mode_reply(value: int) -> bytes:
    """The device's answer to a TCLV 50 (touch mode) read."""
    payload = ParamPacket(items=[ParamItem(50, ParamControl.READ, bytes([value]))]).encode()
    header = DataHeader(device_id=UUID, type=PacketType.PARAM, id=2, length=len(payload))
    return encode_frame(
        header, payload, direction=Direction.DEVICE_TO_SERVER, compression=Compression.NONE
    )


async def param_writes(reader: asyncio.StreamReader, seconds: float) -> dict[int, int]:
    """TCLV writes the server sends within *seconds*, as {id: value}."""
    decoder = FrameDecoder(Direction.SERVER_TO_DEVICE)
    writes: dict[int, int] = {}
    try:
        async with asyncio.timeout(seconds):
            while data := await reader.read(65536):
                for frame in decoder.feed(data):
                    if frame.data.type == PacketType.PARAM:
                        for item in ParamPacket.decode(frame.payload).items:
                            if item.control == ParamControl.WRITE:
                                writes[item.id] = item.as_int()
    except TimeoutError:
        pass
    return writes


def status_frame(display_crc: int = 0xDB963A1A) -> bytes:
    records = [(tag, display_crc if tag == 9 else value) for tag, value in STATUS_TAGS]
    payload = StatusPacket(records=records, sentinel=0xDEADBEEF).encode()
    header = DataHeader(device_id=UUID, type=PacketType.STATUS, id=1, length=len(payload))
    return encode_frame(
        header, payload, direction=Direction.DEVICE_TO_SERVER, compression=Compression.NONE
    )


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def receive_packet_types(reader: asyncio.StreamReader, wanted: int) -> list[int]:
    decoder = FrameDecoder(Direction.SERVER_TO_DEVICE)
    types: list[int] = []
    while wanted not in types:
        data = await reader.read(65536)
        if not data:
            raise AssertionError(f"server closed the connection; got packet types {types}")
        types += [frame.data.type for frame in decoder.feed(data)]
    return types


async def test_connected_display_receives_its_configured_url() -> None:
    port = free_port()
    config = Config(
        default_url="http://default/",
        host="127.0.0.1",
        port=port,
        devices={UUID_STR: DeviceConfig(url="http://mine/", rotate=90)},
    )
    renderer = FakeRenderer()
    app = InkcastServer(config, renderer)
    await app.server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(status_frame())
        await writer.drain()

        types = await asyncio.wait_for(receive_packet_types(reader, PacketType.IMAGE), 10)

        assert PacketType.IMAGE in types
        assert renderer.calls == [("http://mine/", (758, 1024))]
        writer.close()
    finally:
        await app.server.close(abort=True)


async def test_connected_display_is_asked_for_its_touch_mode() -> None:
    port = free_port()
    app = InkcastServer(Config(default_url="http://default/", host="127.0.0.1", port=port), FakeRenderer())
    await app.server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(status_frame())
        await writer.drain()

        types = await asyncio.wait_for(receive_packet_types(reader, PacketType.PARAM), 10)

        assert PacketType.PARAM in types
        writer.close()
    finally:
        await app.server.close(abort=True)


async def connect_and_reply_touch_mode(touch: bool, current: int) -> dict[int, int]:
    port = free_port()
    config = Config(
        default_url="http://default/",
        host="127.0.0.1",
        port=port,
        devices={UUID_STR: DeviceConfig(url="http://mine/", touch=touch)},
    )
    app = InkcastServer(config, FakeRenderer())
    await app.server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(status_frame())
        await writer.drain()
        await asyncio.wait_for(receive_packet_types(reader, PacketType.PARAM), 10)
        writer.write(touch_mode_reply(current))
        await writer.drain()
        writes = await param_writes(reader, seconds=1)
        writer.close()
        return writes
    finally:
        await app.server.close(abort=True)


async def test_touch_is_enabled_and_saved_when_config_wants_it() -> None:
    writes = await connect_and_reply_touch_mode(touch=True, current=0)

    assert writes == {50: 1, 53: 1}  # touch mode on, then flash_save


async def test_touch_is_disabled_when_config_does_not_want_it() -> None:
    writes = await connect_and_reply_touch_mode(touch=False, current=1)

    assert writes == {50: 0, 53: 1}


async def test_nothing_is_written_when_touch_mode_already_matches() -> None:
    writes = await connect_and_reply_touch_mode(touch=True, current=1)

    assert writes == {}


async def packet_types_within(reader: asyncio.StreamReader, seconds: float) -> list[int]:
    decoder = FrameDecoder(Direction.SERVER_TO_DEVICE)
    types: list[int] = []
    try:
        async with asyncio.timeout(seconds):
            while data := await reader.read(65536):
                types += [frame.data.type for frame in decoder.feed(data)]
    except TimeoutError:
        pass
    return types


async def connect_and_collect(
    device: DeviceConfig, renderer: FakeRenderer, display_crc: int = 0xDB963A1A
) -> list[int]:
    port = free_port()
    config = Config(
        default_url="http://default/", host="127.0.0.1", port=port, devices={UUID_STR: device}
    )
    app = InkcastServer(config, renderer)
    await app.server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(status_frame(display_crc))
        await writer.drain()
        types = await packet_types_within(reader, seconds=1.5)
        writer.close()
        return types
    finally:
        await app.server.close(abort=True)


async def test_image_already_on_the_display_is_not_sent_again() -> None:
    shown = encode(Image.new("RGB", (1024, 758), "white"), JOAN6, rotate=0).state_checksum

    types = await connect_and_collect(
        DeviceConfig(url="http://mine/"), FakeRenderer(), display_crc=shown
    )

    assert PacketType.IMAGE not in types


async def test_sleep_is_sent_after_the_image() -> None:
    types = await connect_and_collect(DeviceConfig(url="http://mine/", sleep_minutes=60), FakeRenderer())

    assert PacketType.IMAGE in types
    assert PacketType.COMMAND in types
    assert types.index(PacketType.IMAGE) < types.index(PacketType.COMMAND)


async def test_sleep_is_sent_even_when_rendering_fails() -> None:
    types = await connect_and_collect(
        DeviceConfig(url="http://mine/", sleep_minutes=60), FakeRenderer(fail=True)
    )

    assert PacketType.IMAGE not in types
    assert PacketType.COMMAND in types


async def test_no_sleep_is_sent_without_sleep_minutes() -> None:
    types = await connect_and_collect(DeviceConfig(url="http://mine/"), FakeRenderer())

    assert PacketType.COMMAND not in types


async def renders_while_connected(
    config_refresh: int, device: DeviceConfig, seconds: float, monkeypatch
) -> int:
    """How many times a connected display's page is rendered within *seconds*."""
    monkeypatch.setattr("inkcast.server.REFRESH_TICK_SECONDS", 0.1)
    port = free_port()
    config = Config(
        default_url="http://default/",
        host="127.0.0.1",
        port=port,
        refresh_seconds=config_refresh,
        devices={UUID_STR: device},
    )
    renderer = FakeRenderer()
    app = InkcastServer(config, renderer)
    await app.server.start()
    loop = asyncio.create_task(app._refresh_loop())
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(status_frame())
        await writer.drain()
        await packet_types_within(reader, seconds=seconds)
        writer.close()
        return len(renderer.calls)
    finally:
        loop.cancel()
        await app.server.close(abort=True)


async def test_device_refresh_seconds_re_renders_a_connected_display(monkeypatch) -> None:
    device = DeviceConfig(url="http://mine/", refresh_seconds=1)

    renders = await renders_while_connected(300, device, seconds=2.5, monkeypatch=monkeypatch)

    assert renders >= 2  # once on connect, then every second


async def test_global_refresh_seconds_applies_without_a_device_override(monkeypatch) -> None:
    renders = await renders_while_connected(
        1, DeviceConfig(url="http://mine/"), seconds=2.5, monkeypatch=monkeypatch
    )

    assert renders >= 2


async def test_device_refresh_seconds_wins_over_a_shorter_global_one(monkeypatch) -> None:
    device = DeviceConfig(url="http://mine/", refresh_seconds=300)

    renders = await renders_while_connected(1, device, seconds=2.5, monkeypatch=monkeypatch)

    assert renders == 1  # only the render on connect
