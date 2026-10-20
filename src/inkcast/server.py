"""Glue: accept displays, render their URL, push the image, report status."""

import asyncio
import hashlib
import logging
import time

from aiohttp import web
from pyvisionect.devices.enums import ParamControl
from pyvisionect.io import VisionectServer
from pyvisionect.session import (
    SLOT_FLASH_SAVE,
    SLOT_IMAGE,
    SLOT_PARAM_WRITES,
    SLOT_SLEEP,
    Acked,
    DeviceConnected,
    DeviceConnection,
    Event,
    Nacked,
    ParamsReceived,
    StatusReceived,
    TouchReceived,
)

from .config import Config, DeviceConfig
from .display import encode, preview_png, resolve_panel, viewport
from .render import Renderer
from .status import DeviceStatus, render_page

log = logging.getLogger(__name__)

TCLV_TOUCH_MODE = 50  # 0=off, 1=on, 3=on+beep
REFRESH_TICK_SECONDS = 1.0  # how often the refresh loop checks which displays are due


class InkcastServer:
    def __init__(self, config: Config, renderer: Renderer) -> None:
        self.config = config
        self.renderer = renderer
        self.server = VisionectServer(
            on_events=self.on_events, host=config.host, port=config.port
        )
        self.devices: dict[str, DeviceStatus] = {}
        self._last_digest: dict[bytes, str] = {}
        self._last_refresh: dict[bytes, float] = {}  # time.monotonic() of the last refresh
        self._tasks: set[asyncio.Task[None]] = set()

    async def run(self) -> None:
        runner = None
        if self.config.status_port:
            runner = web.AppRunner(self.status_app(), access_log=None)
            await runner.setup()
            await web.TCPSite(runner, self.config.host, self.config.status_port).start()
            log.info("status page on http://%s:%d/", self.config.host, self.config.status_port)
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self.server.serve_forever())
                tasks.create_task(self._refresh_loop())
        finally:
            if runner:
                await runner.cleanup()

    async def on_events(self, conn: DeviceConnection, events: list[Event]) -> None:
        pending = conn.state.pending
        for event in events:
            match event:
                case DeviceConnected():
                    log.info("%s connected (%s)", event.uuid, resolve_panel(conn.state).describe())
                    self._status(event.uuid).seen(event.status.fields())
                    conn.read_params([TCLV_TOUCH_MODE])
                    self._spawn(self.refresh(conn.state.device_id, force=True))
                case ParamsReceived():
                    for item in event.params.items:
                        log.info("%s param %d = %d", event.uuid, item.id, item.as_int())
                        if item.id == TCLV_TOUCH_MODE and item.control == ParamControl.READ:
                            self._status(event.uuid).touch_mode = item.as_int()
                            self._sync_touch_mode(conn, event.uuid, item.as_int())
                case TouchReceived(touch=touch) if touch:
                    log.info(
                        "%s touch finger %d at (%d, %d)",
                        event.uuid, touch.finger_num, touch.x, touch.y,
                    )
                case StatusReceived():
                    log.debug("%s status %s", event.uuid, event.status.fields())
                    self._status(event.uuid).seen(event.status.fields())
                case Acked():
                    pending.on_acked(event.packet_id)
                case Nacked():
                    log.warning("%s refused packet %d", event.uuid, event.packet_id)
                    pending.on_nacked(event.packet_id, charging=event.charging)

    def _sync_touch_mode(self, conn: DeviceConnection, uuid: str, current: int) -> None:
        """Write the configured touch mode, and persist it, only if the device differs."""
        wanted = 1 if self.config.device(uuid).touch else 0
        if current == wanted:
            return
        log.info("%s setting touch mode %d -> %d", uuid, current, wanted)
        conn.state.pending.write_param(TCLV_TOUCH_MODE, wanted)
        conn.apply_pending(phases=[SLOT_PARAM_WRITES, SLOT_FLASH_SAVE])

    async def refresh(self, device_id: bytes, *, force: bool = False) -> None:
        """Push the display's URL if it changed, then send it to sleep if configured.

        *force* skips the in-memory "page unchanged" shortcut (used on connect),
        but an image the display already shows is never sent again. Sleep is sent
        even when rendering fails, so a broken page cannot keep the display awake.
        """
        conn = self.server.connection_for(device_id)
        if conn is None:
            return  # asleep; we render again when it reconnects
        self._last_refresh[device_id] = time.monotonic()
        uuid = _format_uuid(device_id)
        device = self.config.device(uuid)
        try:
            await self._queue_image(conn, uuid, device, force=force)
        except Exception as exc:
            log.exception("%s failed to update", uuid)
            self._status(uuid).updated("error", f"{type(exc).__name__}: {exc}")
        if device.sleep_minutes:
            conn.state.pending.sleep(device.sleep_minutes)
        conn.apply_pending(phases=[SLOT_IMAGE, SLOT_SLEEP])  # image first, then sleep
        try:
            await self.server.flush(device_id)
        except KeyError:
            log.info("%s disconnected before the update was sent", uuid)

    async def _queue_image(
        self, conn: DeviceConnection, uuid: str, device: DeviceConfig, *, force: bool
    ) -> None:
        device_id = conn.state.device_id
        panel = resolve_panel(conn.state)
        image = await self.renderer.fetch(device.url, viewport(panel, device.rotate))

        digest = hashlib.sha256(image.tobytes()).hexdigest()
        if not force and self._last_digest.get(device_id) == digest:
            return
        frame = await asyncio.to_thread(encode, image, panel, device.rotate, device.fit)
        self._last_digest[device_id] = digest
        status = self._status(uuid)
        status.preview_png = await asyncio.to_thread(
            preview_png, image, viewport(panel, device.rotate), device.fit
        )

        if frame.state_checksum == _display_crc(conn):
            log.info("%s already showing %s", uuid, device.url)
            status.updated("unchanged")
            return
        conn.state.pending.set_image(frame)
        status.updated("sent")
        log.info("%s showing %s", uuid, device.url)

    async def _refresh_loop(self) -> None:
        """Re-render each connected display once its own refresh_seconds has passed."""
        while True:
            await asyncio.sleep(REFRESH_TICK_SECONDS)
            for device_id in list(self.server.connections):
                interval = self.config.refresh_seconds_for(_format_uuid(device_id))
                last = self._last_refresh.setdefault(device_id, time.monotonic())
                if time.monotonic() - last >= interval:
                    await self.refresh(device_id)

    # -- status page ---------------------------------------------------------

    def status_app(self) -> web.Application:
        app = web.Application()
        app.add_routes([
            web.get("/", self._page),
            web.get("/api/devices", self._api),
            web.get("/devices/{uuid}/preview.png", self._preview),
        ])
        return app

    def _status(self, uuid: str) -> DeviceStatus:
        return self.devices.setdefault(uuid, DeviceStatus(uuid))

    def _device_list(self) -> list[dict]:
        """Configured displays first, then any other display that has connected."""
        connected = {_format_uuid(device_id) for device_id in self.server.connections}
        uuids = [*self.config.devices, *(u for u in self.devices if u not in self.config.devices)]
        return [self._status(u).to_json(self.config.device(u), u in connected) for u in uuids]

    async def _page(self, request: web.Request) -> web.Response:
        return web.Response(text=render_page(self._device_list()), content_type="text/html")

    async def _api(self, request: web.Request) -> web.Response:
        return web.json_response(self._device_list())

    async def _preview(self, request: web.Request) -> web.Response:
        status = self.devices.get(request.match_info["uuid"].lower())
        if status is None or status.preview_png is None:
            raise web.HTTPNotFound()
        return web.Response(body=status.preview_png, content_type="image/png")

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


def _display_crc(conn: DeviceConnection) -> int | None:
    """Checksum of what the display reports it is showing (status field 9)."""
    status = conn.state.last_status
    return status.fields().get("DisplayStateCRC") if status else None


def _format_uuid(device_id: bytes) -> str:
    h = device_id.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
