"""Paths and non-secret configuration for the lights CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HOME = Path.home()
CONFIG_DIR = HOME / ".lights"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Which brand backend serves each room. Jake's home: living room = Cync (GE),
# bedrooms = AiDot. Kept in config so it can be refined to specific bulbs later.
DEFAULT_CONFIG: dict[str, Any] = {
    "aidot": {"country_code": "US"},
    "rooms": {
        "living": "cync",
        "bedroom": "aidot",
    },
}

# Keychain account (all secret items are stored under this account name).
KEYCHAIN_ACCOUNT = "jake"


def load_config() -> dict[str, Any]:
    """Load config.json, falling back to defaults for missing keys."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text())
        except (ValueError, OSError):
            stored = {}
        for key, value in stored.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    """Persist config.json (non-secret settings only)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")


def brands_for_room(room: str, cfg: dict[str, Any]) -> list[str]:
    """Return the ordered list of backend brands a room maps to.

    ``all`` expands to every distinct configured brand.
    """
    rooms = cfg.get("rooms", {})
    if room == "all":
        seen: list[str] = []
        for brand in rooms.values():
            if brand not in seen:
                seen.append(brand)
        return seen
    if room in rooms:
        return [rooms[room]]
    raise KeyError(room)
