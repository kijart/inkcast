from PIL import Image
from pyvisionect.devices import Panel
from pyvisionect.packets import StatusPacket
from pyvisionect.session import DeviceState

from inkcast.display import encode, fit_image, resolve_panel, viewport

JOAN6 = Panel(1024, 758, 1, "eink-generic")


def test_viewport_matches_panel_and_swaps_for_portrait() -> None:
    assert viewport(JOAN6, rotate=0) == (1024, 758)
    assert viewport(JOAN6, rotate=180) == (1024, 758)
    assert viewport(JOAN6, rotate=90) == (758, 1024)


def test_encode_produces_frame_for_portrait_screenshot() -> None:
    screenshot = Image.new("RGB", (758, 1024), "white")

    frame = encode(screenshot, JOAN6, rotate=90)

    assert frame.rectangles
    assert frame.state_checksum is not None


def status(*records: tuple[int, int]) -> DeviceState:
    return DeviceState(device_id=bytes(16), last_status=StatusPacket(records=list(records)))


def test_unknown_display_type_uses_reported_geometry() -> None:
    joan6 = status((7, 1), (8, 0x501100EB), (38, 1024), (39, 758))

    panel = resolve_panel(joan6)

    assert (panel.width, panel.height, panel.displays) == (1024, 758, 1)


def test_known_display_type_keeps_pyvisionect_panel() -> None:
    known = status((7, 1), (8, 6), (38, 999), (39, 999))

    assert resolve_panel(known) == known.panel


def test_contain_letterboxes_on_white() -> None:
    wide = Image.new("L", (2000, 500), 0)

    fitted = fit_image(wide, (1024, 758), "contain")

    assert fitted.size == (1024, 758)
    assert fitted.getpixel((512, 0)) == 255  # white band above
    assert fitted.getpixel((512, 379)) == 0  # image in the middle


def test_cover_fills_by_cropping() -> None:
    wide = Image.new("L", (2000, 500), 0)

    fitted = fit_image(wide, (1024, 758), "cover")

    assert fitted.size == (1024, 758)
    assert fitted.getpixel((512, 0)) == 0


def test_stretch_resizes_to_exact_size() -> None:
    assert fit_image(Image.new("L", (10, 10)), (1024, 758), "stretch").size == (1024, 758)


def test_transparency_becomes_white() -> None:
    transparent = Image.new("RGBA", (1024, 758), (0, 0, 0, 0))

    assert fit_image(transparent, (1024, 758), "contain").getpixel((0, 0)) == 255


def test_encode_accepts_images_of_any_size() -> None:
    frame = encode(Image.new("RGB", (300, 200), "white"), JOAN6, rotate=0, fit="contain")

    assert frame.rectangles
