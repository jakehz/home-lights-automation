"""Local web server for the lights UI (aiohttp).

Binds to 127.0.0.1 only. Reuses :mod:`lightctl.engine` so the UI has identical
behavior to the CLI.
"""

from __future__ import annotations

import importlib.resources

from aiohttp import web

from .base import Action, DeviceResult
from .colors import CCT, KELVIN_MAX, KELVIN_MIN, NAMED_RGB
from .config import load_config
from .engine import ACTIONS, BrandOutcome, build_action, run_action

HOST = "127.0.0.1"


def _rgb_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _outcomes_json(outcomes: list[BrandOutcome]) -> dict:
    return {
        "ok": any(o.ok for o in outcomes),
        "rooms": [
            {
                "brand": o.brand,
                "label": o.label,
                "devices": [
                    {"name": r.name, "ok": r.ok, "detail": r.detail}
                    for r in o.results
                ],
            }
            for o in outcomes
        ],
    }


async def handle_index(request: web.Request) -> web.Response:
    html = importlib.resources.files("lightctl.web").joinpath("index.html").read_text()
    return web.Response(text=html, content_type="text/html")


async def handle_config(request: web.Request) -> web.Response:
    cfg = load_config()
    rooms_cfg = cfg.get("rooms", {})
    pretty = {"cync": "Cync", "aidot": "AiDot"}
    labels = {"living": "Living room", "bedroom": "Bedrooms"}
    rooms = [{"key": "all", "label": "All lights", "brand": None}]
    for key, brand in rooms_cfg.items():
        rooms.append({
            "key": key,
            "label": labels.get(key, key.title()),
            "brand": pretty.get(brand, brand),
        })
    return web.json_response({
        "rooms": rooms,
        "actions": list(ACTIONS),
        "kelvin": {"min": KELVIN_MIN, "max": KELVIN_MAX},
        "presets": [
            {"name": n, "kelvin": k}
            for n, k in [("Warm", CCT["WARM"]),
                         ("Neutral", CCT["NEUTRAL"]),
                         ("Daylight", CCT["DAYLIGHT"])]
        ],
        "swatches": [
            {"name": n, "hex": _rgb_hex(rgb)}
            for n, rgb in NAMED_RGB.items()
        ],
    })


async def handle_status(request: web.Request) -> web.Response:
    room = request.query.get("room", "all")
    cfg = load_config()
    try:
        outcomes = await run_action(room, Action(kind="status"), cfg)
    except KeyError:
        return web.json_response({"error": f"unknown room '{room}'"}, status=400)
    return web.json_response(_outcomes_json(outcomes))


async def handle_command(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    room = body.get("room", "all")
    action_name = body.get("action")
    value = body.get("value")
    if value is not None:
        value = str(value)

    try:
        action = build_action(action_name, value)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    cfg = load_config()
    try:
        outcomes = await run_action(room, action, cfg)
    except KeyError:
        return web.json_response({"error": f"unknown room '{room}'"}, status=400)
    return web.json_response(_outcomes_json(outcomes))


def build_app() -> web.Application:
    app = web.Application()
    app.add_routes([
        web.get("/", handle_index),
        web.get("/api/config", handle_config),
        web.get("/api/status", handle_status),
        web.post("/api/command", handle_command),
    ])
    return app


def run_server(port: int = 8765) -> None:
    """Start the web UI (blocks until Ctrl-C)."""
    url = f"http://{HOST}:{port}"
    print(f"lights web UI running at {url}", flush=True)
    print("Open it in your browser. Press Ctrl-C to stop.", flush=True)
    web.run_app(build_app(), host=HOST, port=port, print=None)
