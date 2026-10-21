from inkcast.device_page import render_device_page

INFO = {
    "uuid": "00112233-4455-6677-8899-aabb00000000",
    "name": "Kitchen",
    "battery_percent": 87,
    "charging": "charging",
    "signal_dbm": -63,
    "temperature_c": 21.6,
    "humidity_percent": 44.4,
    "firmware": "7.4.4407",
    "sleep_minutes": 60,
    "refresh_seconds": 300,
    "touch": True,
    "rotate": 90,
    "resolution": (758, 1024),
}


def test_page_shows_the_display_data() -> None:
    html = render_device_page(INFO)

    for text in (
        "Kitchen", INFO["uuid"], "87%", "charging", "Good", "22 °C", "44%",
        "7.4.4407", "every 60 min", "every 5 min", "On", "758 × 1024", "90°",
    ):
        assert text in html


def test_page_escapes_the_name() -> None:
    html = render_device_page({**INFO, "name": "Kitchen <e-ink>"})

    assert "Kitchen &lt;e-ink&gt;" in html
    assert "<e-ink>" not in html


def test_unknown_values_show_a_dash() -> None:
    html = render_device_page(
        {**INFO, "battery_percent": None, "charging": None, "signal_dbm": None,
         "temperature_c": None, "humidity_percent": None, "firmware": None}
    )

    assert html.count("<dd>—</dd>") == 6


def test_display_without_sleep_is_always_awake() -> None:
    assert "Always on" in render_device_page({**INFO, "sleep_minutes": 0})


def test_unnamed_display_is_titled_by_its_uuid() -> None:
    html = render_device_page({**INFO, "name": ""})

    assert f"<h1>{INFO['uuid']}</h1>" in html


def test_signal_is_shown_as_a_coarse_quality() -> None:
    assert [
        _signal(dbm) for dbm in (-50, -60, -61, -70, -71, -80, -81)
    ] == ["Excellent", "Excellent", "Good", "Good", "Fair", "Fair", "Weak"]


def test_same_data_renders_the_same_page() -> None:
    assert render_device_page(INFO) == render_device_page(dict(INFO))


def _signal(dbm: int) -> str:
    html = render_device_page({**INFO, "signal_dbm": dbm})
    return html.split("<dt>Signal</dt><dd>")[1].split("</dd>")[0]
