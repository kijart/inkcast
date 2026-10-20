"""Renderer against real headless Chromium (needs `playwright install chromium`)."""

import functools
import http.server
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from PIL import Image

from inkcast.render import Renderer

VIEWPORT = (1024, 758)


@pytest.fixture
def site(tmp_path: Path) -> Iterator[str]:
    Image.new("RGB", (40, 30), "red").save(tmp_path / "photo.png")
    (tmp_path / "page.html").write_text("<body style='background:#fff'>hello</body>")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=tmp_path)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
async def renderer() -> AsyncIterator[Renderer]:
    async with Renderer(settle_seconds=0) as renderer:
        yield renderer


async def test_web_page_is_screenshotted_at_viewport_size(renderer: Renderer, site: str) -> None:
    image = await renderer.fetch(f"{site}/page.html", VIEWPORT)

    assert image.size == VIEWPORT


async def test_image_url_is_loaded_as_is(renderer: Renderer, site: str) -> None:
    image = await renderer.fetch(f"{site}/photo.png", VIEWPORT)

    assert image.size == (40, 30)
    assert image.convert("RGB").getpixel((0, 0)) == (255, 0, 0)


async def test_local_image_file_is_loaded_as_is(renderer: Renderer, tmp_path: Path) -> None:
    Image.new("RGB", (40, 30), "blue").save(tmp_path / "local.png")

    image = await renderer.fetch((tmp_path / "local.png").as_uri(), VIEWPORT)

    assert image.size == (40, 30)
