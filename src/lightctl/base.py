"""Shared types for the light backends."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Action:
    """A resolved command to apply to lights.

    ``kind`` is one of: on, off, dim, temp, color, status.
    Only the field(s) relevant to ``kind`` are populated.
    """

    kind: str
    dim: int | None = None          # brightness percent 0-100
    kelvin: int | None = None       # white color temperature in Kelvin
    rgb: tuple[int, int, int] | None = None


@dataclass
class DeviceResult:
    """Outcome of applying an action to a single device."""

    name: str
    ok: bool
    detail: str = ""
