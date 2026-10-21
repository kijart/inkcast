"""Turn a URL into an image: raster images as-is, everything else via headless Chromium."""

import asyncio
import io
import mimetypes
from contextlib import AsyncExitStack
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from PIL import Image
from playwright.async_api import Browser, async_playwright


class Renderer:
    """One shared headless browser; each render opens a fresh page."""

    def __init__(self, settle_seconds: float = 2.0) -> None:
        self._settle_seconds = settle_seconds
        self._stack = AsyncExitStack()
        self._browser: Browser | None = None

    async def __aenter__(self) -> "Renderer":
        playwright = await self._stack.enter_async_context(async_playwright())
        self._browser = await playwright.chromium.launch()
        self._stack.push_async_callback(self._browser.close)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._stack.aclose()

    async def fetch(self, url: str, size: tuple[int, int]) -> Image.Image:
        """The image at *url*, or a *size* screenshot if it is a web page.

        Raster images come back at their own size; the caller fits them.
        """
        if url.startswith("file://"):
            path = Path(url2pathname(urlparse(url).path))
            if _is_raster(mimetypes.guess_type(path)[0]):
                return await asyncio.to_thread(_open, path.read_bytes())

        assert self._browser is not None, "use Renderer as an async context manager"
        width, height = size
        page = await self._browser.new_page(viewport={"width": width, "height": height})
        try:
            response = await page.goto(url, wait_until="networkidle")
            if response and _is_raster(response.headers.get("content-type")):
                return _open(await response.body())
            await asyncio.sleep(self._settle_seconds)  # let client-side widgets draw
            return _open(await page.screenshot())
        finally:
            await page.close()

    async def fetch_html(self, html: str, size: tuple[int, int]) -> Image.Image:
        """A *size* screenshot of a self-contained *html* document."""
        assert self._browser is not None, "use Renderer as an async context manager"
        width, height = size
        page = await self._browser.new_page(viewport={"width": width, "height": height})
        try:
            await page.set_content(html)
            return _open(await page.screenshot())
        finally:
            await page.close()


def _is_raster(content_type: str | None) -> bool:
    """Images Pillow can decode; SVG is left to the browser."""
    return bool(content_type) and content_type.startswith("image/") and "svg" not in content_type


def _open(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image
