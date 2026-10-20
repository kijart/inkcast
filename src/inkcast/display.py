"""Turn a screenshot into a frame the e-ink panel understands."""

import io
from dataclasses import replace

from PIL import Image, ImageOps
from pyvisionect.devices import Panel
from pyvisionect.imaging import EncodedFrame, encode_frame
from pyvisionect.session import DeviceState

GRAY_4BPP = 4
FLOYD_STEINBERG = 3


def resolve_panel(state: DeviceState) -> Panel:
    """The device's panel geometry.

    pyvisionect maps unknown ``DisplayType`` values (e.g. the Joan 6's
    ``0x501100EB``) to a 32" multi-panel default. A single-display device
    also reports its own size, so trust that instead.
    """
    panel = state.panel
    fields = state.last_status.fields() if state.last_status else {}
    width, height = fields.get("DisplayWidth"), fields.get("DisplayHeight")
    if panel.is_default and fields.get("NumberOfSupportedDisplays") == 1 and width and height:
        return replace(
            panel, width=width, height=height, displays=1, driver="eink-generic", is_default=False
        )
    return panel


def viewport(panel: Panel, rotate: int) -> tuple[int, int]:
    """Browser viewport size: the panel size, swapped when mounted in portrait."""
    if rotate in (90, 270):
        return panel.height, panel.width
    return panel.width, panel.height


def fit_image(image: Image.Image, size: tuple[int, int], fit: str) -> Image.Image:
    """Grayscale *image* fitted to *size*; transparency becomes white.

    ``contain`` keeps it whole with white bands, ``cover`` fills by cropping,
    ``stretch`` ignores the aspect ratio.
    """
    if image.has_transparency_data:
        rgba = image.convert("RGBA")
        image = Image.new("RGBA", rgba.size, "white")
        image.alpha_composite(rgba)
    image = image.convert("L")
    if image.size == size:
        return image
    match fit:
        case "cover":
            return ImageOps.fit(image, size)
        case "stretch":
            return image.resize(size)
        case _:
            return ImageOps.pad(image, size, color=255)


def encode(image: Image.Image, panel: Panel, rotate: int, fit: str = "contain") -> EncodedFrame:
    """Fit to the viewport, rotate back to the panel's orientation, encode as 16 greys.

    CPU-bound: run it in an executor, never on the event loop.
    """
    image = fit_image(image, viewport(panel, rotate), fit).rotate(-rotate, expand=True)
    return encode_frame(image, panel=panel, encoding=GRAY_4BPP, dithering=FLOYD_STEINBERG)


def preview_png(image: Image.Image, size: tuple[int, int], fit: str) -> bytes:
    """PNG of *image* as it appears on the display (grayscale, fitted, as mounted)."""
    buffer = io.BytesIO()
    fit_image(image, size, fit).save(buffer, format="PNG")
    return buffer.getvalue()
