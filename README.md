# lights

One terminal command to control both brands of smart lights in the house:

- **Living room** → GE / **Cync** (cloud API via `pycync`)
- **Bedrooms** → **AiDot** (local LAN control via `python-aidot`, after one cloud login)

## First-time setup

```
lights setup
```

You'll log in once per brand. Credentials and auth tokens are stored in the
**macOS Keychain** (nothing sensitive is written to disk). Cync will email you a
one-time 6-digit code the first time — enter it when prompted.

## Usage

```
lights <room> <action> [value]
lights <action> [value]          # applies to all rooms
```

| Command | What it does |
|---|---|
| `lights all off` | turn every light off |
| `lights all on` | turn every light on |
| `lights bedroom dim 40` | bedrooms to 40% brightness |
| `lights living temp 3000` | living room to 3000 K white |
| `lights bedroom color warm` | bedrooms to warm white |
| `lights living color #0044ff` | living room to blue |
| `lights status` | show on/off + level per light |

- `room`: `living` | `bedroom` | `all`
- `color`: a name (`red`, `warm`, `daylight`, …) or `#rrggbb` hex

## Web UI

```
lights serve            # then open http://127.0.0.1:8765
lights serve --port 9000
```

Starts a local dashboard with the same functionality as the CLI: per-room
on/off, brightness, color-temperature, colors, and live status. It binds to
`127.0.0.1` only (this Mac; not exposed to the network) and runs until you press
Ctrl-C. Auto-refresh is off by default — a Cync status poll is a full cloud
round-trip, so refresh after actions or with the Refresh button.

## How it works / good to know

- **AiDot is local.** After the initial login for keys, bedroom commands go
  straight to the bulbs over Wi-Fi — fast, no cloud round-trip.
- **Cync is cloud-only** (reverse-engineered). Two inherent quirks:
  1. Only one connection per Cync account at a time — **opening the Cync phone
     app briefly disconnects this CLI**, and vice-versa.
  2. Needs internet + at least one Wi-Fi Cync device acting as the bridge.
- If one brand is unreachable, the other room still runs; the exit code is
  non-zero only when a targeted room fully fails.

## Project layout

- `src/lightctl/` — CLI (`cli.py`), backends (`aidot_backend.py`,
  `cync_backend.py`), Keychain wrapper (`secrets.py`), color helpers
- Managed with **uv**; run directly via `~/.local/bin/lights` (execs the
  project venv). Update deps deliberately with `uv lock --upgrade`.
