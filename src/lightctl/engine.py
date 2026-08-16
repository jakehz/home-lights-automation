"""Shared command engine used by both the CLI and the web server.

Turns a room + :class:`Action` into per-backend results. Kept separate from any
front-end so the CLI and the web UI behave identically.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from aiohttp import ClientSession

from . import aidot_backend, cync_backend
from .base import Action, DeviceResult
from .colors import KELVIN_MAX, KELVIN_MIN, clamp, parse_color
from .config import brands_for_room

ACTIONS = ("on", "off", "dim", "temp", "color", "status")

# Cync allows only one cloud connection per account at a time, so overlapping
# requests (e.g. a status poll landing during a command) must not run at once.
_RUN_LOCK = asyncio.Lock()


@dataclass
class BrandOutcome:
    """Results for one backend/room from applying an action."""

    brand: str
    label: str
    results: list[DeviceResult]

    @property
    def ok(self) -> bool:
        return any(r.ok for r in self.results)


def build_action(action_name: str, value: str | None) -> Action:
    """Resolve an action name + raw value into an :class:`Action`.

    Raises ``ValueError`` with a friendly message on bad input. Shared by the
    CLI arg parser and the web ``/api/command`` endpoint.
    """
    if action_name not in ACTIONS:
        raise ValueError(f"unknown action '{action_name}'")

    if action_name in ("on", "off", "status"):
        return Action(kind=action_name)

    if value is None or value == "":
        raise ValueError(f"'{action_name}' needs a value")

    if action_name == "dim":
        try:
            level = int(value)
        except ValueError:
            raise ValueError(f"dim needs a number 0-100, got '{value}'")
        return Action(kind="dim", dim=clamp(level, 0, 100))

    if action_name == "temp":
        try:
            kelvin = int(value)
        except ValueError:
            raise ValueError(f"temp needs Kelvin {KELVIN_MIN}-{KELVIN_MAX}, got '{value}'")
        return Action(kind="temp", kelvin=clamp(kelvin, KELVIN_MIN, KELVIN_MAX))

    # color: may resolve to an RGB color or a white color-temperature preset.
    kind, payload = parse_color(value)
    if kind == "cct":
        return Action(kind="temp", kelvin=int(payload))
    return Action(kind="color", rgb=tuple(payload))  # type: ignore[arg-type]


def brand_room_label(cfg: dict, brand: str) -> str:
    """Human label like 'living room (Cync)' for a backend brand."""
    pretty = {"cync": "Cync", "aidot": "AiDot"}
    rooms = [r for r, b in cfg.get("rooms", {}).items() if b == brand]
    room = rooms[0] if rooms else brand
    labels = {"living": "living room", "bedroom": "bedrooms"}
    room_label = labels.get(room, room)
    return f"{room_label} ({pretty.get(brand, brand)})"


async def _run_brand(brand: str, action: Action, session: ClientSession,
                     cfg: dict) -> list[DeviceResult]:
    """Dispatch to a single backend, returning results or a room-level error."""
    try:
        if brand == "aidot":
            country = cfg.get("aidot", {}).get("country_code", "US")
            return await aidot_backend.apply(action, session, country)
        if brand == "cync":
            return await cync_backend.apply(action, session)
        return [DeviceResult(brand, False, "no backend")]
    except cync_backend.CyncNeedsSetup as exc:
        return [DeviceResult("(living)", False, str(exc))]
    except aidot_backend.AidotError as exc:
        return [DeviceResult("(bedroom)", False, str(exc))]
    except Exception as exc:  # noqa: BLE001
        hint = ""
        if brand == "cync":
            hint = " (is the Cync phone app open? only one connection is allowed at a time)"
        return [DeviceResult("(" + brand + ")", False,
                             (str(exc) or exc.__class__.__name__) + hint)]


async def run_action(room: str, action: Action, cfg: dict) -> list[BrandOutcome]:
    """Apply ``action`` to every backend serving ``room``.

    Serializes with a lock so requests never overlap (Cync single-connection).
    Raises ``KeyError`` if ``room`` is unknown.
    """
    brands = brands_for_room(room, cfg)  # raises KeyError on unknown room
    async with _RUN_LOCK:
        async with ClientSession() as session:
            results = await asyncio.gather(
                *[_run_brand(b, action, session, cfg) for b in brands]
            )
    return [
        BrandOutcome(brand=b, label=brand_room_label(cfg, b), results=r)
        for b, r in zip(brands, results)
    ]
