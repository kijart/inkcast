"""Built-in page (``about:device``): the display's own data, drawn for e-ink.

Only values that change rarely are shown (no clock, no update counter, coarse
signal quality), so an unchanged display keeps producing the same image and is
not redrawn on every refresh.
"""

from html import escape
from typing import Any

UNKNOWN = "—"

STYLE = """
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: #fff; color: #000; }
body { font-family: "DejaVu Sans", "Helvetica Neue", Arial, sans-serif;
  padding: 5vmin; display: flex; flex-direction: column; gap: 3vmin; }
h1 { margin: 0; font-size: 7vmin; line-height: 1.1; overflow-wrap: anywhere; }
.uuid { font-size: 2.6vmin; font-family: "DejaVu Sans Mono", Menlo, monospace; }
hr { width: 100%; border: 0; border-top: 0.5vmin solid #000; margin: 0; }
dl { flex: 1; margin: 0; display: grid; grid-template-columns: max-content 1fr;
  align-content: space-evenly; gap: 1.5vmin 5vmin; font-size: 4.2vmin; }
dt { font-weight: normal; } dd { margin: 0; font-weight: bold; overflow-wrap: anywhere; }
"""


def render_device_page(info: dict[str, Any]) -> str:
    """HTML for one display from its status JSON plus ``refresh_seconds``,
    ``touch`` and ``resolution`` (viewport width, height)."""
    title = escape(info["name"] or info["uuid"])
    width, height = info["resolution"]
    rows = [
        ("Battery", _unit(info["battery_percent"], "%")),
        ("Signal", _signal(info["signal_dbm"])),
        ("Temperature", _unit(info["temperature_c"], " °C")),
        ("Humidity", _unit(info["humidity_percent"], "%")),
        ("Firmware", info["firmware"]),
        ("Wakes", f"every {info['sleep_minutes']} min" if info["sleep_minutes"] else "Always on"),
        ("Refresh", _every(info["refresh_seconds"])),
        ("Touch", "On" if info["touch"] else "Off"),
        ("Resolution", f"{width} × {height}"),
        ("Rotation", f"{info['rotate']}°"),
    ]
    items = "\n".join(
        f"<dt>{label}</dt><dd>{escape(str(value)) if value is not None else UNKNOWN}</dd>"
        for label, value in rows
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><style>{STYLE}</style></head>
<body>
<h1>{title}</h1>
<div class="uuid">{escape(info["uuid"])}</div>
<hr>
<dl>
{items}
</dl>
</body>
</html>
"""


def _unit(value: float | None, unit: str) -> str | None:
    return None if value is None else f"{round(value)}{unit}"


def _signal(dbm: int | None) -> str | None:
    """Coarse quality, so small RSSI swings do not redraw the display."""
    if dbm is None:
        return None
    if dbm >= -60:
        return "Excellent"
    if dbm >= -70:
        return "Good"
    if dbm >= -80:
        return "Fair"
    return "Weak"


def _every(seconds: int) -> str:
    return f"every {seconds // 60} min" if seconds % 60 == 0 else f"every {seconds} s"
