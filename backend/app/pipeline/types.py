"""Type inference: recover a typed value whose *display* still matches the page.

The governing rule is that conversion must never change what the reader sees.  A
cell reading ``1,234.50`` becomes the number ``1234.5`` only because the number
format ``#,##0.00`` renders it back to ``1,234.50`` character for character.
Anything that cannot be round-tripped that faithfully stays text.

That rule is enforced, not merely intended: :func:`infer_value` renders its own
result through :func:`display_string` and falls back to text if the two differ.
A cell that is wrong is worse than a cell that is merely untyped.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.models.grid import CellValue

# --- Number shapes ----------------------------------------------------------

_GROUPED = r"\d{1,3}(?:,\d{3})+"
_PLAIN = r"\d+"
_NUMBER = rf"(?:{_GROUPED}|{_PLAIN})(?:\.\d+)?"

_NUMERIC_RE = re.compile(rf"^(?P<sign>-)?(?P<num>{_NUMBER})$")
_PERCENT_RE = re.compile(rf"^(?P<sign>-)?(?P<num>{_NUMBER})\s*%$")
#: A leading symbol ($1,200.00) or a currency code (MUR 1,200.00).
_CURRENCY_PREFIX_RE = re.compile(
    rf"^(?P<sign>-)?(?P<sym>[$£€¥₹]|[A-Z]{{3}}\s)\s?(?P<num>{_NUMBER})$"
)
#: A trailing symbol or code (1 200,00 EUR is not supported; see ASSUMPTIONS).
_CURRENCY_SUFFIX_RE = re.compile(
    rf"^(?P<sign>-)?(?P<num>{_NUMBER})\s?(?P<sym>[$£€¥₹]|\s[A-Z]{{3}})$"
)
#: Accounting notation: a negative shown in parentheses.
_PAREN_RE = re.compile(rf"^\((?P<sym>[$£€¥₹])?(?P<num>{_NUMBER})\)$")

_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_MONTH_INDEX = {name.lower(): i + 1 for i, name in enumerate(_MONTHS)}
_MONTH_INDEX.update({name[:3].lower(): i + 1 for i, name in enumerate(_MONTHS)})
_MONTH_PATTERN = "|".join(
    sorted({*(m.lower() for m in _MONTHS), *(m[:3].lower() for m in _MONTHS)}, key=len, reverse=True)
)

_ISO_DATE_RE = re.compile(r"^(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})$")
_SLASH_DATE_RE = re.compile(r"^(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<y>\d{4})$")
_DMY_TEXT_RE = re.compile(
    rf"^(?P<d>\d{{1,2}})\s+(?P<m>{_MONTH_PATTERN})\s+(?P<y>\d{{4}})$", re.IGNORECASE
)
_MDY_TEXT_RE = re.compile(
    rf"^(?P<m>{_MONTH_PATTERN})\s+(?P<d>\d{{1,2}}),\s*(?P<y>\d{{4}})$", re.IGNORECASE
)

GENERAL = "General"


def _has_significant_leading_zero(digits: str) -> bool:
    """True for values like ``007`` whose zeros would be lost by numeric typing."""
    integer_part = digits.split(".", 1)[0]
    return len(integer_part) > 1 and integer_part.startswith("0")


def _decimals_of(number: str) -> int:
    return len(number.split(".", 1)[1]) if "." in number else 0


def _numeric_pattern(number: str) -> str:
    """``#,##0.00`` or ``0.00`` depending on whether the source grouped digits."""
    base = "#,##0" if "," in number else "0"
    decimals = _decimals_of(number)
    return f"{base}.{'0' * decimals}" if decimals else base


def _to_decimal(number: str, negative: bool) -> Decimal | None:
    try:
        value = Decimal(number.replace(",", ""))
    except InvalidOperation:
        return None
    return -value if negative else value


def _as_number(value: Decimal, decimals: int) -> CellValue:
    return int(value) if decimals == 0 else float(value)


# --- Inference --------------------------------------------------------------


def _infer_percent(text: str) -> tuple[CellValue, str] | None:
    match = _PERCENT_RE.match(text)
    if match is None:
        return None
    number = match.group("num")
    value = _to_decimal(number, bool(match.group("sign")))
    if value is None:
        return None
    decimals = _decimals_of(number)
    # Excel's percent format multiplies by 100 on display, so the stored value
    # must be the fraction.
    return float(value) / 100.0, f"{_numeric_pattern(number)}%"


def _infer_currency(text: str) -> tuple[CellValue, str] | None:
    for pattern, symbol_leads in ((_CURRENCY_PREFIX_RE, True), (_CURRENCY_SUFFIX_RE, False)):
        match = pattern.match(text)
        if match is None:
            continue
        number = match.group("num")
        if _has_significant_leading_zero(number):
            return None
        value = _to_decimal(number, bool(match.group("sign")))
        if value is None:
            return None

        symbol = match.group("sym")
        quoted = f'"{symbol}"'
        pattern_body = _numeric_pattern(number)
        number_format = (
            f"{quoted}{pattern_body}" if symbol_leads else f"{pattern_body}{quoted}"
        )
        return _as_number(value, _decimals_of(number)), number_format
    return None


def _infer_accounting(text: str) -> tuple[CellValue, str] | None:
    match = _PAREN_RE.match(text)
    if match is None:
        return None
    number = match.group("num")
    value = _to_decimal(number, negative=True)
    if value is None:
        return None

    symbol = match.group("sym") or ""
    quoted = f'"{symbol}"' if symbol else ""
    body = _numeric_pattern(number)
    # The positive branch is never displayed here, but Excel requires both.
    number_format = f"{quoted}{body}_);({quoted}{body})"
    return _as_number(value, _decimals_of(number)), number_format


def _infer_number(text: str) -> tuple[CellValue, str] | None:
    match = _NUMERIC_RE.match(text)
    if match is None:
        return None
    number = match.group("num")
    if _has_significant_leading_zero(number):
        # "007" is an identifier, not a quantity.
        return None
    value = _to_decimal(number, bool(match.group("sign")))
    if value is None:
        return None
    return _as_number(value, _decimals_of(number)), _numeric_pattern(number)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _infer_date(text: str) -> tuple[CellValue, str] | None:
    iso = _ISO_DATE_RE.match(text)
    if iso is not None:
        value = _safe_date(int(iso["y"]), int(iso["m"]), int(iso["d"]))
        return (value, "yyyy-mm-dd") if value else None

    dmy = _DMY_TEXT_RE.match(text)
    if dmy is not None:
        month = _MONTH_INDEX.get(dmy["m"].lower())
        value = _safe_date(int(dmy["y"]), month or 0, int(dmy["d"]))
        if value is None:
            return None
        spelled = len(dmy["m"]) > 3
        return value, "d mmmm yyyy" if spelled else "d mmm yyyy"

    mdy = _MDY_TEXT_RE.match(text)
    if mdy is not None:
        month = _MONTH_INDEX.get(mdy["m"].lower())
        value = _safe_date(int(mdy["y"]), month or 0, int(mdy["d"]))
        if value is None:
            return None
        spelled = len(mdy["m"]) > 3
        return value, "mmmm d, yyyy" if spelled else "mmm d, yyyy"

    slash = _SLASH_DATE_RE.match(text)
    if slash is not None:
        a, b = int(slash["a"]), int(slash["b"])
        # 01/02/2026 is genuinely ambiguous; only type it when the order is
        # forced. Guessing here would silently corrupt the value.
        if a > 12 and b <= 12:
            value = _safe_date(int(slash["y"]), b, a)
            return (value, "dd/mm/yyyy") if value else None
        if b > 12 and a <= 12:
            value = _safe_date(int(slash["y"]), a, b)
            return (value, "mm/dd/yyyy") if value else None
        return None

    return None


#: Order matters: percent and currency must be tried before the bare number,
#: which would otherwise match their digits and drop the symbol.
_INFERENCE_CHAIN = (
    _infer_percent,
    _infer_currency,
    _infer_accounting,
    _infer_date,
    _infer_number,
)


def infer_value(text: str) -> tuple[CellValue, str]:
    """Return ``(value, number_format)`` for a cell's literal page text.

    Text that cannot be typed and rendered back identically is returned
    unchanged with the ``General`` format, which is always display-safe.
    """
    stripped = text.strip()
    if not stripped:
        return "", GENERAL

    for infer in _INFERENCE_CHAIN:
        result = infer(stripped)
        if result is None:
            continue
        value, number_format = result
        # The safety net: if the round trip does not reproduce the page exactly,
        # the value is not worth the risk.
        if display_string(value, number_format) == stripped:
            return value, number_format

    return stripped, GENERAL


# --- Display ----------------------------------------------------------------

_QUOTED_RE = re.compile(r'"([^"]*)"')


def _format_number(value: float, pattern: str) -> str:
    grouped = "#,##" in pattern
    decimals = len(pattern.split(".", 1)[1]) if "." in pattern else 0
    spec = f",.{decimals}f" if grouped else f".{decimals}f"
    return format(value, spec)


def _render_numeric_format(value: float, number_format: str) -> str:
    """Render the numeric formats :func:`infer_value` is able to emit."""
    # Accounting: positives use the first section, negatives the parenthesised one.
    if "_)" in number_format:
        positive, _, negative = number_format.partition(";")
        section = negative if value < 0 else positive.replace("_)", "")
        literal = "".join(_QUOTED_RE.findall(section))
        body = _QUOTED_RE.sub("", section).strip("()")
        rendered = f"{literal}{_format_number(abs(value), body)}"
        return f"({rendered})" if value < 0 else rendered

    if number_format.endswith("%"):
        body = number_format[:-1]
        return f"{_format_number(value * 100.0, body)}%"

    literal = "".join(_QUOTED_RE.findall(number_format))
    body = _QUOTED_RE.sub("", number_format)
    sign = "-" if value < 0 else ""
    rendered = _format_number(abs(value), body)

    if number_format.startswith('"'):
        return f"{sign}{literal}{rendered}"
    if literal:
        return f"{sign}{rendered}{literal}"
    return f"{sign}{rendered}"


def _render_date_format(value: date, number_format: str) -> str:
    """Render the date formats :func:`infer_value` is able to emit."""
    replacements = (
        ("yyyy", f"{value.year:04d}"),
        ("mmmm", _MONTHS[value.month - 1]),
        ("mmm", _MONTHS[value.month - 1][:3]),
        ("mm", f"{value.month:02d}"),
        ("dd", f"{value.day:02d}"),
        ("d", str(value.day)),
    )
    result = number_format
    for token, replacement in replacements:
        result = result.replace(token, f"\0{replacement}\0")
    return result.replace("\0", "")


def display_string(value: CellValue, number_format: str) -> str:
    """Render a typed value the way Excel would, for verification and tests.

    Only the formats :func:`infer_value` can emit are supported; anything else
    falls back to ``str`` so callers still get a comparable string.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        return value

    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return _render_date_format(value, number_format)

    if isinstance(value, (int, float, Decimal)):
        if number_format == GENERAL:
            return f"{value:g}" if isinstance(value, float) else str(value)
        return _render_numeric_format(float(value), number_format)

    return str(value)
