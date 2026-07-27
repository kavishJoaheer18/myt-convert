"""Font-name parsing.

Embedded PDF fonts arrive as subset-tagged PostScript names such as
``ABCDEF+Helvetica-BoldOblique``.  Excel wants a plain family name plus boolean
bold/italic flags, so the two representations are reconciled here.
"""

from __future__ import annotations

import re

#: Six uppercase letters and a '+' prefixed to subsetted embedded fonts.
_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")

_BOLD_TOKENS = ("bold", "black", "heavy", "semibold", "demibold", "extrabold")
_ITALIC_TOKENS = ("italic", "oblique")

#: Map the core PDF families onto fonts Excel can actually render.
_FAMILY_ALIASES = {
    "helvetica": "Arial",
    "arial": "Arial",
    "times": "Times New Roman",
    "timesnewroman": "Times New Roman",
    "timesroman": "Times New Roman",
    "courier": "Courier New",
    "couriernew": "Courier New",
    "symbol": "Symbol",
    "zapfdingbats": "Wingdings",
}


def strip_subset_prefix(font_name: str) -> str:
    return _SUBSET_PREFIX.sub("", font_name or "")


def is_bold(font_name: str) -> bool:
    name = strip_subset_prefix(font_name).lower()
    return any(token in name for token in _BOLD_TOKENS)


def is_italic(font_name: str) -> bool:
    name = strip_subset_prefix(font_name).lower()
    return any(token in name for token in _ITALIC_TOKENS)


def family_name(font_name: str) -> str:
    """Reduce a PostScript font name to an Excel-friendly family name."""
    name = strip_subset_prefix(font_name)
    if not name:
        return "Calibri"

    # Drop the style suffix: "Helvetica-BoldOblique" → "Helvetica".
    base = re.split(r"[-,]", name)[0]

    # Some names concatenate style without a separator: "ArialBold".
    lowered = base.lower()
    for token in (*_BOLD_TOKENS, *_ITALIC_TOKENS):
        if lowered.endswith(token) and len(lowered) > len(token):
            base = base[: -len(token)]
            lowered = base.lower()

    key = re.sub(r"[^a-z]", "", lowered)
    if key in _FAMILY_ALIASES:
        return _FAMILY_ALIASES[key]

    # Re-space CamelCase names so "OpenSans" reads as "Open Sans".
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base).strip()
    return spaced or "Calibri"


def parse_font(font_name: str) -> tuple[str, bool, bool]:
    """Return ``(family, bold, italic)`` for a raw PDF font name."""
    return family_name(font_name), is_bold(font_name), is_italic(font_name)
