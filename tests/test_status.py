"""Status page and JSON API, with a fake display connected over TCP."""

import asyncio
import io
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from pyvisionect.devices.enums import PacketType

from inkcast.config import Config, DeviceConfig
from inkcast.server import InkcastServer
from inkcast.status import DeviceStatus, render_page
from test_server import UUID_STR, FakeRenderer, free_port, packet_types_within, status_frame

OTHER_UUID = "ffffffff-0000-0000-0000-000000000000"


@asynccontextmanager
async def running(
    devices: dict[str, DeviceConfig], renderer: FakeRenderer | None = None
) -> AsyncIterator[TestClient]:
    """A InkcastServer with one fake display connected, and an HTTP client for its status app."""
    port = free_port()
    config = Config(default_url="http://default/", host="127.0.0.1", port=port, devices=devices)
    app = InkcastServer(config, renderer or FakeRenderer())
    await app.server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(status_frame())
        await writer.drain()
        await packet_types_within(reader, seconds=1.5)  # let connect + render finish
        async with TestClient(TestServer(app.status_app())) as client:
            yield client
        writer.close()
    finally:
        await app.server.close(abort=True)


async def device_json(client: TestClient, uuid: str) -> dict:
    response = await client.get("/api/devices")
    assert response.status == 200
    return next(d for d in await response.json() if d["uuid"] == uuid)


async def test_api_reports_a_connected_display() -> None:
    devices = {UUID_STR: DeviceConfig(url="http://mine/", name="Kitchen", sleep_minutes=60)}
    async with running(devices) as client:
        device = await device_json(client, UUID_STR)

    assert device["name"] == "Kitchen"
    assert device["connected"] is True
    assert device["state"] == "connected"
    assert device["last_seen"].endswith("Z")  # UTC
    assert device["battery_percent"] == 100
    assert device["firmware"] == "7.4.4407"
    assert device["source"] == "http://mine/"
    assert device["sleep_minutes"] == 60
    assert device["last_update"]["result"] == "sent"
    assert device["preview_url"] == f"/devices/{UUID_STR}/preview.png"


async def test_api_lists_configured_displays_never_seen() -> None:
    devices = {
        UUID_STR: DeviceConfig(url="http://mine/"),
        OTHER_UUID: DeviceConfig(url="http://other/"),
    }
    async with running(devices) as client:
        device = await device_json(client, OTHER_UUID)

    assert device["connected"] is False
    assert device["state"] == "never_seen"
    assert device["last_seen"] is None
    assert device["source"] == "http://other/"
    assert device["preview_url"] is None


async def test_api_reports_render_errors() -> None:
    devices = {UUID_STR: DeviceConfig(url="http://mine/")}
    async with running(devices, FakeRenderer(fail=True)) as client:
        device = await device_json(client, UUID_STR)

    assert device["last_update"]["result"] == "error"
    assert "page unreachable" in device["last_update"]["error"]


async def test_preview_is_what_the_display_shows() -> None:
    devices = {UUID_STR: DeviceConfig(url="http://mine/", rotate=90)}
    async with running(devices) as client:
        response = await client.get(f"/devices/{UUID_STR}/preview.png")
        body = await response.read()

    assert response.status == 200
    assert response.content_type == "image/png"
    assert Image.open(io.BytesIO(body)).size == (758, 1024)  # portrait, as mounted


async def test_preview_of_unknown_display_is_404() -> None:
    async with running({UUID_STR: DeviceConfig(url="http://mine/")}) as client:
        response = await client.get(f"/devices/{OTHER_UUID}/preview.png")

    assert response.status == 404


async def test_page_is_self_contained_and_themeable() -> None:
    devices = {UUID_STR: DeviceConfig(url="http://mine/", name="Kitchen <e-ink>")}
    async with running(devices) as client:
        response = await client.get("/")
        html = await response.text()

    assert response.status == 200
    assert response.content_type == "text/html"
    assert "Kitchen &lt;e-ink&gt;" in html  # escaped
    assert UUID_STR in html
    assert "prefers-color-scheme: dark" in html
    assert 'data-theme="dark"' in html or "data-theme" in html
    for external in ("<script src", "@import", "https://"):
        assert external not in html
    assert all('href="data:' in tag for tag in re.findall(r"<link[^>]*>", html))


async def test_status_page_is_off_by_default() -> None:
    assert Config(default_url="http://x/").status_port is None


async def test_display_is_still_sent_an_image_with_status_page() -> None:
    port = free_port()
    config = Config(default_url="http://default/", host="127.0.0.1", port=port)
    app = InkcastServer(config, FakeRenderer())
    await app.server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(status_frame())
        await writer.drain()

        assert PacketType.IMAGE in await packet_types_within(reader, seconds=1.5)
        writer.close()
    finally:
        await app.server.close(abort=True)


def seen_minutes_ago(minutes: int) -> DeviceStatus:
    status = DeviceStatus("x")
    status.last_seen = datetime.now(UTC) - timedelta(minutes=minutes)
    return status


def test_sleeping_display_is_asleep_until_overdue() -> None:
    device = DeviceConfig(url="u", sleep_minutes=60)

    assert seen_minutes_ago(30).to_json(device, connected=False)["state"] == "asleep"
    assert seen_minutes_ago(65).to_json(device, connected=False)["state"] == "asleep"  # grace
    assert seen_minutes_ago(75).to_json(device, connected=False)["state"] == "disconnected"


def test_display_without_sleep_is_disconnected_when_not_connected() -> None:
    device = DeviceConfig(url="u")

    assert seen_minutes_ago(1).to_json(device, connected=False)["state"] == "disconnected"


def test_next_wake_is_utc() -> None:
    device = DeviceConfig(url="u", sleep_minutes=60)

    assert seen_minutes_ago(1).to_json(device, connected=False)["next_wake"].endswith("Z")


async def test_page_shows_the_state() -> None:
    async with running({UUID_STR: DeviceConfig(url="http://mine/")}) as client:
        html = await (await client.get("/")).text()

    assert ">Connected<" in html


def test_page_declares_an_inline_favicon() -> None:
    page = render_page([])
    assert '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,' in page
    assert '<h1><img src="data:image/svg+xml,' in page
