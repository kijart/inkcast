# inkcast

**Show web pages and images on Visionect e-ink displays, such as the Joan 6,
without the Visionect Software Suite.**

inkcast is a small self-hosted server. Your displays connect to it; it renders the
page you choose (a [MagicMirror²](https://magicmirror.builders) dashboard, a Home
Assistant view, any URL) with headless Chromium, or takes an image, and pushes it to
the screen. One process, one TOML file: no database, no Redis, no vendor account.

The display protocol is implemented by [pyvisionect](https://github.com/schlarpc/pyvisionect),
a reverse-engineered implementation of Visionect "protocol v3".

## Features

- **Web pages or images per display**: a URL is rendered in Chromium at the panel's
  size; a PNG/JPEG (by URL or `file://`) is fitted to it.
- **Built for e-ink**: 16 grey levels with Floyd–Steinberg dithering, rotation for
  portrait or upside-down mounting, and no screen refresh when nothing changed.
- **Battery friendly**: sends the display to sleep after each update, and never
  keeps it awake because a page failed to load.
- **Touch panel** on/off per display.
- **Status page and JSON API**: battery, signal, temperature, last and next
  contact, and a preview of what each display shows. Light and dark themes, no
  external resources.
- **Home Assistant** sensors through the built-in RESTful integration (examples below).

## Compatible displays

Displays built on Visionect's platform that speak protocol v3 and have a single
panel. Tested with:

| Display           | Firmware | Status                                       |
| ----------------- | -------- | -------------------------------------------- |
| Joan 6 (1024×758) | 7.3.4358 | Works: image push, sleep, status, touch mode |

Other single-panel Visionect displays are likely to work: inkcast takes the panel
size from what the display reports. Reports for other models are welcome.

## Requirements

- Python 3.13+ and [uv](https://docs.astral.sh/uv/), or Docker/Podman.
- The display on the same local network, set up once as described below.

## Quick start

```sh
git clone <this repository> inkcast && cd inkcast
cp config.example.toml config.toml # set default_url
uv sync
uv run playwright install chromium
uv run inkcast config.toml # add -v for debug logs
```

Or in a container:

```sh
cp config.example.toml config.toml
docker compose up -d --build # or: podman compose up -d --build
```

When a display connects, its UUID appears in the log:

```txt
2026-10-18T22:30:00.123Z INFO inkcast.server: 00112233-4455-6677-8899-aabbccddeeff connected (...)
```

Use it in `config.toml` to give that display its own settings.

## Preparing the display (once)

Each display has to point to the machine running inkcast, on port 11113, with
**outbound encryption disabled**. Visionect's link encryption relies on keys held by
a Visionect service, so a self-hosted server cannot use it.

- With the **Joan app or the Visionect Configurator**, set the server address to the
  IP of the machine running inkcast and turn encryption off.
- Or over the **USB serial console**:

  ```txt
  server_tcp_set <inkcast-ip> 11113
  encryption_mode_set 0
  flash_save
  ```

## Configuration

`config.toml` (see [`config.example.toml`](config.example.toml)):

```toml
default_url = "http://example.com" # for displays not listed below
refresh_seconds = 300
status_port = 8000

[devices."00112233-4455-6677-8899-aabbccddeeff"]
name = "Kitchen"
url = "http://example.com/kitchen"
refresh_seconds = 3600
rotate = 180
sleep_minutes = 60
```

| Option            | Default     | Description                                                                                                       |
| ----------------- | ----------- | ----------------------------------------------------------------------------------------------------------------- |
| `default_url`     | (required)  | What displays without their own `url` show.                                                                       |
| `host`            | `"0.0.0.0"` | Address to listen on.                                                                                             |
| `port`            | `11113`     | Port displays connect to (the Visionect default).                                                                 |
| `refresh_seconds` | `300`       | How often connected displays are re-rendered. The image is only sent if it changed. Each display can override it. |
| `settle_seconds`  | `2.0`       | Wait after a page loads, so client-side widgets can draw.                                                         |
| `status_port`     | off         | Port of the status page and JSON API.                                                                             |

Per display, under `[devices."<uuid>"]`:

| Option            | Default                  | Description                                                                                                          |
| ----------------- | ------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| `name`            | `""`                     | Shown on the status page and in the API.                                                                             |
| `url`             | `default_url`            | Web page, image URL, or `file:///path/to/image.png`.                                                                 |
| `fit`             | `"contain"`              | Images only: `contain` (white bands), `cover` (crop) or `stretch`.                                                   |
| `refresh_seconds` | global `refresh_seconds` | How often this display is re-rendered while connected. With `sleep_minutes`, it is updated when it wakes up instead. |
| `rotate`          | `0`                      | `0`, `90`, `180` or `270`. `90`/`270` render the page in portrait.                                                   |
| `sleep_minutes`   | `0`                      | Minutes the display sleeps after each update. `0` lets it follow its own schedule.                                   |
| `touch`           | `false`                  | Turns the touch panel on. Saved on the display.                                                                      |

### Battery life

The display can only be updated while it is awake, and nothing can wake it over
the network. For a battery display, `sleep_minutes` is what matters most:

| Use                       | `sleep_minutes` | `refresh_seconds` |
| ------------------------- | --------------- | ----------------- |
| Plugged in, quick updates | `0`             | `30`–`60`         |
| On battery, lasting weeks | `30`–`120`      | high, e.g. `3600` |

Keep `touch = false` on battery, and avoid content that changes every minute (such
as a clock with seconds): every change is a screen refresh.

## How it works

1. The display is a **TCP client**: it connects to inkcast on port 11113 and
   reports its status (panel size, battery, what it is showing...).
2. inkcast loads the display's `url`:
   - a **web page** is screenshotted with headless Chromium at the panel size;
   - an **image** (`Content-Type: image/*`, or `file://`) is used as is, fitted with
     `fit`. Transparent areas become white; SVG is rendered by the browser.
3. The result is rotated, converted to 16 greys and dithered.
4. If the display already shows that exact image (it reports a checksum of its
   screen), nothing is sent. Otherwise the image is sent, followed by the sleep
   command if `sleep_minutes` is set.
5. While a display stays connected, the page is re-rendered every
   `refresh_seconds` (its own, or the global one) and sent only if it changed.

With `touch`, inkcast reads the display's touch mode on every connection and writes
it, and saves it to the display's flash, only when it differs. Touches are logged as
`touch finger N at (x, y)`; they are not passed to the page.

Logs use UTC timestamps.

## Status page and API

With `status_port = 8000`:

| URL                                                     |                                                                                                                                                                                          |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `http://<inkcast-host>:8000/`                           | One card per display: current image, state, battery, signal, temperature, humidity, last and next contact, last update result and settings. Auto/light/dark theme; refreshes every 30 s. |
| `http://<inkcast-host>:8000/api/devices`                | The same data as JSON.                                                                                                                                                                   |
| `http://<inkcast-host>:8000/devices/<uuid>/preview.png` | What the display shows.                                                                                                                                                                  |

`GET /api/devices` returns one object per display (configured displays first,
then any other display that has connected):

```json
[
  {
    "uuid": "00112233-4455-6677-8899-aabbccddeeff",
    "name": "Kitchen",
    "state": "asleep",
    "connected": false,
    "last_seen": "2026-10-18T22:30:00Z",
    "next_wake": "2026-10-18T23:30:00Z",
    "battery_percent": 97,
    "battery_voltage_mv": 4138,
    "charging": "disabled",
    "signal_dbm": -66,
    "temperature_c": 26,
    "humidity_percent": 54,
    "firmware": "7.3.4358",
    "display_updates": 15,
    "touch_mode": 0,
    "source": "http://example.com/kitchen",
    "rotate": 180,
    "sleep_minutes": 60,
    "last_update": {
      "at": "2026-10-18T22:30:03Z",
      "result": "sent",
      "error": null
    },
    "preview_url": "/devices/00112233-4455-6677-8899-aabbccddeeff/preview.png"
  }
]
```

- Times are UTC in RFC 3339 format (`Z` suffix).
- `state` is the badge on the status page:
  - `connected`: connected right now;
  - `asleep`: sent to sleep and not overdue (`next_wake` plus 10 minutes);
  - `disconnected`: not connected and not expected to be asleep (no
    `sleep_minutes`, or it missed its wake-up);
  - `never_seen`: configured but not connected since inkcast started.
- Values come from the display's last status, so they change when it wakes up.
  Data is kept in memory: after a restart, fields are `null` until each display
  connects again.
- `last_update.result` is `sent`, `unchanged` (it already showed that image) or `error`.

## Home Assistant

The built-in [RESTful integration](https://www.home-assistant.io/integrations/rest/)
can turn `/api/devices` into sensors with a single request. Replace
`<inkcast-host>` and the UUID, add this to `configuration.yaml` and restart Home
Assistant:

```yaml
rest:
  - resource: http://<inkcast-host>:8000/api/devices
    scan_interval: 300
    sensor:
      - name: "Kitchen display state"
        unique_id: kitchen_display_state
        value_template: >-
          {% set d = value_json | selectattr('uuid', 'equalto', '00112233-4455-6677-8899-aabbccddeeff') | first %}
          {{ d.state }}
      - name: "Kitchen display battery"
        unique_id: kitchen_display_battery
        device_class: battery
        state_class: measurement
        unit_of_measurement: "%"
        value_template: >-
          {% set d = value_json | selectattr('uuid', 'equalto', '00112233-4455-6677-8899-aabbccddeeff') | first %}
          {{ d.battery_percent }}
      - name: "Kitchen display signal"
        unique_id: kitchen_display_signal
        device_class: signal_strength
        state_class: measurement
        unit_of_measurement: "dBm"
        value_template: >-
          {% set d = value_json | selectattr('uuid', 'equalto', '00112233-4455-6677-8899-aabbccddeeff') | first %}
          {{ d.signal_dbm }}
      - name: "Kitchen display temperature"
        unique_id: kitchen_display_temperature
        device_class: temperature
        state_class: measurement
        unit_of_measurement: "°C"
        value_template: >-
          {% set d = value_json | selectattr('uuid', 'equalto', '00112233-4455-6677-8899-aabbccddeeff') | first %}
          {{ d.temperature_c }}
      - name: "Kitchen display humidity"
        unique_id: kitchen_display_humidity
        device_class: humidity
        state_class: measurement
        unit_of_measurement: "%"
        value_template: >-
          {% set d = value_json | selectattr('uuid', 'equalto', '00112233-4455-6677-8899-aabbccddeeff') | first %}
          {{ d.humidity_percent }}
      - name: "Kitchen display last seen"
        unique_id: kitchen_display_last_seen
        device_class: timestamp
        value_template: >-
          {% set d = value_json | selectattr('uuid', 'equalto', '00112233-4455-6677-8899-aabbccddeeff') | first %}
          {{ as_datetime(d.last_seen) if d.last_seen else none }}
      - name: "Kitchen display next wake"
        unique_id: kitchen_display_next_wake
        device_class: timestamp
        value_template: >-
          {% set d = value_json | selectattr('uuid', 'equalto', '00112233-4455-6677-8899-aabbccddeeff') | first %}
          {{ as_datetime(d.next_wake) if d.next_wake else none }}
      - name: "Kitchen display last update"
        unique_id: kitchen_display_last_update
        value_template: >-
          {% set d = value_json | selectattr('uuid', 'equalto', '00112233-4455-6677-8899-aabbccddeeff') | first %}
          {{ d.last_update.result or 'unknown' }}
    binary_sensor:
      - name: "Kitchen display connected"
        unique_id: kitchen_display_connected
        device_class: connectivity
        value_template: >-
          {% set d = value_json | selectattr('uuid', 'equalto', '00112233-4455-6677-8899-aabbccddeeff') | first %}
          {{ d.connected }}
```

- Repeat the sensors for each display.
- `scan_interval` is how often Home Assistant asks inkcast, not the display; polling
  faster than `sleep_minutes` adds little.
- On battery, "state" is more useful than "connected", which is `off` while the
  display sleeps.

**Current image.** Add a [Generic Camera](https://www.home-assistant.io/integrations/generic/)
with this _Still image URL_ (leave the stream URL empty) and show it with a
_Picture Entity_ card:

```txt
http://<inkcast-host>:8000/devices/00112233-4455-6677-8899-aabbccddeeff/preview.png
```

**Alerts**, for example:

```yaml
automation:
  - alias: "Kitchen display low battery"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.kitchen_display_battery
        below: 20
    actions:
      - action: notify.notify
        data:
          message: "Kitchen display battery at {{ states('sensor.kitchen_display_battery') }} %"
  - alias: "Kitchen display disconnected"
    triggers:
      - trigger: state
        entity_id: sensor.kitchen_display_state
        to: "disconnected"
    actions:
      - action: notify.notify
        data:
          message: "Kitchen display is disconnected"
```

## Security

- The display protocol has **no authentication**: anything that can reach port
  11113 can claim to be any display. The status page and API are read-only but
  unauthenticated too.
- The link is unencrypted (see [Preparing the display](#preparing-the-display-once)).

Run inkcast on a trusted local network and do not expose its ports to the internet.

## Limitations

- Single-panel displays only; multi-panel signs are not supported.
- Every update redraws the full screen (no partial updates).
- No firmware updates: Visionect firmware images are encrypted with keys only
  Visionect holds.
- Touches are logged but not forwarded to the page.
- Some displays report a panel type pyvisionect does not list yet (the Joan 6
  reports `0x501100EB`); inkcast then uses the size the display reports.

## Development

```sh
uv sync
uv run playwright install chromium # the renderer tests use a real browser
uv run pytest
```

## Credits

- [pyvisionect](https://github.com/schlarpc/pyvisionect) by schlarpc: the display
  protocol, imaging and work queue.
- [Playwright](https://playwright.dev/python/) and Chromium for rendering.

## License

[MIT](LICENSE).

## Disclaimer

inkcast is an independent project, not affiliated with or endorsed by Visionect.
Visionect and Joan are trademarks of their respective owners and are used here only
to describe compatibility.
