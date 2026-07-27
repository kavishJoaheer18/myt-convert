"""Type inference: recover a typed value whose *display* still matches the page.

The governing rule is that conversion must never change what the reader sees.  A
cell reading ``1,234.50`` becomes the number ``1234.5`` only because the number
format ``#,##0.00`` renders it back to ``1,234.50`` character for character.
Anything that cannot be round-tripped that faithfully stays text.

Phase 1 handles plain and thousands-separated numbers; dates, currency and
percentages arrive in Phase 3.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.models.grid import CellValue

#: 1,234.50 / -1,234 / 1,234
_GROUPED = re.compile(r"^-?\d{1,3}(?:,\d{3})+(?:\.(\d+))?$")
#: 42 / -3.14159 / 0.5
_PLAIN = re.compile(r"^-?\d+(?:\.(\d+))?$")


def _has_significant_leading_zero(text: str) -> bool:
    """True for values like ``007`` whose zeros would be lost by numeric typing."""
    digits = text.lstrip("-")
    integer_part = digits.split(".", 1)[0]
    return len(integer_part) > 1 and integer_part.startswith("0")


def _decimal_format(decimals: int, grouped: bool) -> str:
    base = "#,##0" if grouped else "0"
    return f"{base}.{'0' * decimals}" if decimals else base


def infer_value(text: str) -> tuple[CellValue, str]:
    """Return ``(value, number_format)`` for a cell's literal page text.

    Text that is not confidently numeric is returned unchanged with the
    ``General`` format, which is always display-safe.
    """
    stripped = text.strip()
    if not stripped:
        return "", "General"

    grouped_match = _GROUPED.match(stripped)
    plain_match = _PLAIN.match(stripped)
    match = grouped_match or plain_match
    if match is None:
        return stripped, "General"

    if plain_match is not None and _has_significant_leading_zero(stripped):
        # "007" is an identifier, not a quantity.
        return stripped, "General"

    decimals = len(match.group(1) or "")
    number_format = _decimal_format(decimals, grouped=grouped_match is not None)

    try:
        value = Decimal(stripped.replace(",", ""))
    except InvalidOperation:
        return stripped, "General"

    numeric: CellValue = int(value) if decimals == 0 else float(value)
    return numeric, number_format


def display_string(value: CellValue, number_format: str) -> str:
    """Render a typed value the way Excel would, for verification and tests.

    Only the formats :func:`infer_value` can emit are supported; anything else
    falls back to ``str`` so callers still get a comparable string.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"

    if isinstance(value, (int, float, Decimal)):
        if number_format == "General":
            return f"{value:g}" if isinstance(value, float) else str(value)

        grouped = "#,##" in number_format
        decimals = len(number_format.split(".", 1)[1]) if "." in number_format else 0
        spec = f",.{decimals}f" if grouped else f".{decimals}f"
        return format(float(value), spec)

    return str(value)
