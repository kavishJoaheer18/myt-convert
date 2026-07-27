"""Colour normalisation.

PDF producers describe colour in whatever space they please — DeviceGray,
DeviceRGB, DeviceCMYK, or a packed integer from PyMuPDF.  Every extractor funnels
its raw values through here so the rest of the pipeline only ever sees a 6-digit
uppercase sRGB hex string.
"""

from __future__ import annotations

from typing import Any, Sequence

BLACK = "000000"
WHITE = "FFFFFF"


def _clamp_byte(value: float) -> int:
    return max(0, min(255, int(round(value))))


def _from_unit(value: float) -> int:
    """Map a 0.0–1.0 component to 0–255, tolerating values already in 0–255."""
    # Some producers emit 0–255 integers even in DeviceRGB arrays.
    if value > 1.0:
        return _clamp_byte(value)
    return _clamp_byte(value * 255.0)


def rgb_to_hex(r: float, g: float, b: float) -> str:
    return f"{_from_unit(r):02X}{_from_unit(g):02X}{_from_unit(b):02X}"


def cmyk_to_hex(c: float, m: float, y: float, k: float) -> str:
    r = 255.0 * (1.0 - min(1.0, c + k))
    g = 255.0 * (1.0 - min(1.0, m + k))
    b = 255.0 * (1.0 - min(1.0, y + k))
    return f"{_clamp_byte(r):02X}{_clamp_byte(g):02X}{_clamp_byte(b):02X}"


def normalize_color(raw: Any, default: str | None = BLACK) -> str | None:
    """Coerce any PDF colour representation to ``RRGGBB``.

    Returns ``default`` when the value is missing or uninterpretable, so callers
    can distinguish "no fill" (``default=None``) from "unspecified, assume black".
    """
    if raw is None:
        return default

    # PyMuPDF hands back a packed 0xRRGGBB integer for drawing colours.
    if isinstance(raw, int) and not isinstance(raw, bool):
        return f"{raw & 0xFFFFFF:06X}"

    if isinstance(raw, float):
        return rgb_to_hex(raw, raw, raw)

    if isinstance(raw, str):
        text = raw.lstrip("#").strip()
        if len(text) == 6:
            try:
                int(text, 16)
            except ValueError:
                return default
            return text.upper()
        return default

    if isinstance(raw, Sequence):
        parts = [float(v) for v in raw if isinstance(v, (int, float))]
        if len(parts) == 1:
            grey = parts[0]
            return rgb_to_hex(grey, grey, grey)
        if len(parts) == 3:
            return rgb_to_hex(*parts)
        if len(parts) == 4:
            return cmyk_to_hex(*parts)

    return default


def is_near_white(hex_color: str | None, threshold: int = 248) -> bool:
    """True for colours close enough to white to be a no-op cell fill.

    Excel treats an explicit white fill as meaningful, but PDFs routinely paint a
    white background rectangle behind the whole page; reproducing those as fills
    would bury the borders underneath them.
    """
    if not hex_color or len(hex_color) != 6:
        return False
    try:
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return False
    return r >= threshold and g >= threshold and b >= threshold
