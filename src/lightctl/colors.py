"""Color / color-temperature parsing shared by both backends.

``parse_color`` accepts a hex string (``#rrggbb``) or a friendly name and
returns either an RGB triple or a color-temperature in Kelvin (for the
"white" presets like ``warm`` / ``daylight``). Each backend then translates
into its own units.
"""

from __future__ import annotations

# Kelvin bounds we accept from the user for `temp`.
KELVIN_MIN = 2700
KELVIN_MAX = 6500

# Named RGB colors (0-255). Small, dependency-free table of common asks.
NAMED_RGB: dict[str, tuple[int, int, int]] = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "yellow": (255, 255, 0),
    "orange": (255, 90, 0),
    "purple": (140, 0, 255),
    "violet": (140, 0, 255),
    "pink": (255, 55, 120),
    "lime": (140, 255, 0),
    "teal": (0, 200, 160),
    "indigo": (60, 0, 200),
    "white": (255, 255, 255),
}

# "White" presets expressed as a color temperature in Kelvin.
CCT_PRESETS: dict[str, int] = {
    "candle": 2200,
    "warm": 2700,
    "warmwhite": 2700,
    "soft": 2900,
    "softwhite": 2900,
    "neutral": 4000,
    "cool": 4500,
    "coolwhite": 4500,
    "day": 6500,
    "daylight": 6500,
}


def clamp(value: int, low: int, high: int) -> int:
    """Clamp ``value`` into the inclusive range ``[low, high]``."""
    return max(low, min(high, value))


def parse_color(text: str) -> tuple[str, object]:
    """Parse a color argument.

    Returns ``("rgb", (r, g, b))`` or ``("cct", kelvin)``.
    Raises ``ValueError`` for anything unrecognized.
    """
    s = text.strip().lower().replace(" ", "").replace("_", "").replace("-", "")

    if s.startswith("#") or (len(s) == 6 and all(c in "0123456789abcdef" for c in s)):
        h = s.lstrip("#")
        if len(h) != 6:
            raise ValueError(f"'{text}' is not a valid #rrggbb hex color")
        return "rgb", (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    if s in CCT_PRESETS:
        return "cct", CCT_PRESETS[s]
    if s in NAMED_RGB:
        return "rgb", NAMED_RGB[s]

    raise ValueError(
        f"unknown color '{text}'. Try a #rrggbb hex, a name "
        f"({', '.join(sorted(NAMED_RGB))}), or a white preset "
        f"({', '.join(sorted(CCT_PRESETS))})."
    )


def kelvin_to_cync_percent(kelvin: int) -> int:
    """Map a Kelvin value to Cync's 1-100 color-temperature scale.

    Empirically (verified on real Cync bulbs) 1 = warmest and 100 = coolest,
    which is the opposite of pycync's docstring. So warm Kelvin -> low value,
    cool Kelvin -> high value. Clamp the input to our accepted band first.
    """
    k = clamp(kelvin, KELVIN_MIN, KELVIN_MAX)
    frac = (k - KELVIN_MIN) / (KELVIN_MAX - KELVIN_MIN)  # 0 at warmest, 1 at coolest
    return clamp(round(frac * 99) + 1, 1, 100)
