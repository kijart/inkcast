"""Live status of the displays: in-memory records, a JSON API and a small HTML page."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

from .config import DeviceConfig

WAKE_GRACE = timedelta(minutes=10)
"""How late a sleeping display may be before it counts as disconnected."""


@dataclass
class DeviceStatus:
    """What we last heard from one display and what we last did to it."""

    uuid: str
    last_seen: datetime | None = None
    fields: dict[str, Any] = field(default_factory=dict)  # last status packet
    touch_mode: int | None = None
    last_update_at: datetime | None = None
    last_result: str | None = None  # "sent", "unchanged" or "error"
    last_error: str | None = None
    preview_png: bytes | None = None

    def seen(self, fields: dict[str, Any]) -> None:
        self.fields = fields
        self.last_seen = _now()

    def updated(self, result: str, error: str | None = None) -> None:
        self.last_update_at = _now()
        self.last_result = result
        self.last_error = error

    def to_json(self, device: DeviceConfig, connected: bool) -> dict[str, Any]:
        f = self.fields
        firmware = f.get("Firmware")
        next_wake = None
        if not connected and self.last_seen and device.sleep_minutes:
            next_wake = self.last_seen + timedelta(minutes=device.sleep_minutes)
        return {
            "uuid": self.uuid,
            "name": device.name,
            "state": self._state(connected, next_wake),
            "connected": connected,
            "last_seen": _iso(self.last_seen),
            "next_wake": _iso(next_wake),
            "battery_percent": f.get("BatteryLevel"),
            "battery_voltage_mv": f.get("BatteryVoltage"),
            "charging": (f.get("ChargingStatus") or {}).get("name"),
            "signal_dbm": f.get("SignalStrength"),
            "temperature_c": f.get("AverageTemperature"),
            "humidity_percent": f.get("HumiditySensor"),
            "firmware": "{major}.{minor}.{revision}".format(**firmware) if firmware else None,
            "display_updates": f.get("DisplayUpdateCount"),
            "touch_mode": self.touch_mode,
            "source": device.url,
            "rotate": device.rotate,
            "sleep_minutes": device.sleep_minutes,
            "last_update": {
                "at": _iso(self.last_update_at),
                "result": self.last_result,
                "error": self.last_error,
            },
            "preview_url": f"/devices/{self.uuid}/preview.png" if self.preview_png else None,
        }


    def _state(self, connected: bool, next_wake: datetime | None) -> str:
        """``connected``, ``asleep`` (expected to wake), ``disconnected`` or ``never_seen``."""
        if connected:
            return "connected"
        if self.last_seen is None:
            return "never_seen"
        if next_wake and _now() <= next_wake + WAKE_GRACE:
            return "asleep"
        return "disconnected"


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime | None) -> str | None:
    """RFC 3339 in UTC, e.g. ``2026-10-18T22:30:00Z``."""
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------
# HTML page: self-contained, no external resources, auto/light/dark theme
# --------------------------------------------------------------------------

STYLE = """
:root {
  --bg: #f6f7f9; --card: #ffffff; --text: #1d2125; --muted: #626b75;
  --border: #dde1e6; --ok: #1f8a4c; --warn: #b26b00; --bad: #c62828; --img-bg: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #121417; --card: #1b1e22; --text: #e6e8eb; --muted: #9aa3ad;
    --border: #2c3137; --ok: #4cc27a; --warn: #e0a23a; --bad: #ef5d5d; --img-bg: #e9e9e9;
  }
}
:root[data-theme="dark"] {
  --bg: #121417; --card: #1b1e22; --text: #e6e8eb; --muted: #9aa3ad;
  --border: #2c3137; --ok: #4cc27a; --warn: #e0a23a; --bad: #ef5d5d; --img-bg: #e9e9e9;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px 16px; background: var(--bg); color: var(--text);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
main { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 1.4rem; margin: 0 0 20px; display: flex; align-items: center; gap: 8px; }
h1 img { width: 1.2em; height: 1.2em; }
.theme { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.theme button { background: var(--card); color: var(--muted); border: 0; padding: 3px 10px;
  font: inherit; cursor: pointer; }
.theme button[aria-pressed="true"] { color: var(--text); font-weight: 600; background: var(--border); }
.grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
.card h2 { font-size: 1.05rem; margin: 0 0 2px; }
.uuid { color: var(--muted); font: 12px ui-monospace, SFMono-Regular, Menlo, monospace;
  overflow-wrap: anywhere; }
.badge { display: inline-block; margin: 10px 0; padding: 2px 10px; border-radius: 999px;
  font-size: 0.85rem; font-weight: 600; border: 1px solid currentColor; }
.ok { color: var(--ok); } .warn { color: var(--warn); } .bad { color: var(--bad); }
.muted { color: var(--muted); }
.preview { display: block; width: 100%; height: auto; border: 1px solid var(--border);
  border-radius: 6px; background: var(--img-bg); margin: 4px 0 12px; }
.empty-preview { padding: 40px 0; text-align: center; border: 1px dashed var(--border);
  border-radius: 6px; margin: 4px 0 12px; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; margin: 0; }
dt { color: var(--muted); } dd { margin: 0; overflow-wrap: anywhere; }
footer { margin-top: 24px; color: var(--muted); font-size: 0.85rem;
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
"""

SCRIPT = """
(function () {
  var root = document.documentElement;
  function apply(theme) {
    if (theme === "light" || theme === "dark") root.setAttribute("data-theme", theme);
    else root.removeAttribute("data-theme");
    document.querySelectorAll(".theme button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.value === (theme || "auto")));
    });
  }
  var saved = null;
  try { saved = localStorage.getItem("theme"); } catch (e) {}
  apply(saved);
  document.querySelectorAll(".theme button").forEach(function (b) {
    b.addEventListener("click", function () {
      try { localStorage.setItem("theme", b.dataset.value); } catch (e) {}
      apply(b.dataset.value);
    });
  });
})();
"""


FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect x='3' y='2' width='26' height='28' rx='4' fill='%23222'/%3E"
    "%3Crect x='6' y='5' width='20' height='22' rx='1' fill='%23eee'/%3E"
    "%3Cpath d='M9 10h14M9 15h14M9 20h9' stroke='%23222' stroke-width='2' stroke-linecap='round'/%3E"
    "%3C/svg%3E"
)


def render_page(devices: list[dict[str, Any]]) -> str:
    cards = "\n".join(_card(d) for d in devices) or '<p class="muted">No displays yet.</p>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>inkcast status</title>
<link rel="icon" type="image/svg+xml" href="{FAVICON}">
<style>{STYLE}</style>
</head>
<body>
<main>
<h1><img src="{FAVICON}" alt="">inkcast</h1>
<div class="grid">
{cards}
</div>
<footer>
  <span>Refreshes every 30 s</span> · <a class="muted" href="/api/devices">JSON</a> ·
  <a class="muted" href="https://github.com/kijart/inkcast" target="_blank" rel="noopener">GitHub</a> ·
  <div class="theme" role="group" aria-label="Theme">
    <button type="button" data-value="auto">Auto</button>
    <button type="button" data-value="light">Light</button>
    <button type="button" data-value="dark">Dark</button>
  </div>
</footer>
</main>
<script>{SCRIPT}</script>
</body>
</html>
"""


STATES = {
    "connected": ("ok", "Connected"),
    "asleep": ("muted", "Asleep"),
    "disconnected": ("bad", "Disconnected"),
    "never_seen": ("warn", "Never seen"),
}


def _card(d: dict[str, Any]) -> str:
    css, label = STATES[d["state"]]
    badge = f'<span class="badge {css}">{label}</span>'

    if d["preview_url"]:
        preview = f'<img class="preview" src="{escape(d["preview_url"])}" alt="Current image">'
    else:
        preview = '<div class="empty-preview muted">No image sent yet</div>'

    update = d["last_update"]
    if update["result"] == "error":
        result = f'<span class="bad">error</span> {escape(update["error"] or "")}'
    else:
        result = escape(update["result"] or "—")

    rows = [
        ("Battery", _battery(d)),
        ("Signal", _unit(d["signal_dbm"], " dBm")),
        ("Temperature", _unit(d["temperature_c"], " °C")),
        ("Humidity", _unit(d["humidity_percent"], " %")),
        ("Last seen", _when(d["last_seen"])),
        ("Next wake", _when(d["next_wake"])),
        ("Showing", f'<span class="uuid">{escape(d["source"])}</span>'),
        ("Last update", f"{result} <span class=\"muted\">{_when(update['at'])}</span>"),
        ("Sleep", f'{d["sleep_minutes"]} min' if d["sleep_minutes"] else "off"),
        ("Rotation", f'{d["rotate"]}°'),
        ("Touch", {None: "—", 0: "off"}.get(d["touch_mode"], "on")),
        ("Firmware", escape(d["firmware"] or "—")),
        ("Screen updates", _unit(d["display_updates"], "")),
    ]
    details = "\n".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows)
    return f"""<section class="card">
  <h2>{escape(d["name"] or "Unnamed display")}</h2>
  <div class="uuid">{escape(d["uuid"])}</div>
  {badge}
  {preview}
  <dl>
{details}
  </dl>
</section>"""


def _battery(d: dict[str, Any]) -> str:
    percent = d["battery_percent"]
    if percent is None:
        return "—"
    css = "ok" if percent > 40 else "warn" if percent > 15 else "bad"
    volts = f' <span class="muted">{d["battery_voltage_mv"] / 1000:.2f} V</span>' \
        if d["battery_voltage_mv"] else ""
    charging = f' <span class="muted">({escape(d["charging"])})</span>' \
        if d["charging"] and d["charging"] != "disabled" else ""
    return f'<span class="{css}">{percent} %</span>{volts}{charging}'


def _unit(value: Any, unit: str) -> str:
    return "—" if value is None else f"{escape(str(value))}{unit}"


def _when(iso: str | None) -> str:
    if not iso:
        return "—"
    moment = datetime.fromisoformat(iso)
    seconds = (moment - _now()).total_seconds()
    minutes = round(abs(seconds) / 60)
    relative = (
        "just now" if minutes == 0
        else f"in {minutes} min" if seconds > 0
        else f"{minutes} min ago"
    )
    return f'<time datetime="{iso}" title="{iso}">{relative}</time>'
