"""Reading typed values out of quote text.

Suppliers write the same number a dozen ways: `1,234.50`, `1 234,50`, `(980.00)`
for a credit, `32%`, `USD 40.00`, `40.00 USD`. These helpers reduce all of that
to a Decimal, and refuse rather than guess when the text is genuinely ambiguous.

Decimal, not float, because these are prices that get summed and compared.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

#: Currency codes and symbols seen on quotes, mapped to the ISO code.
_CURRENCY_SYMBOLS = {
    "$": "USD",
    "US$": "USD",
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "¥": "JPY",
    "Rs": "MUR",
    "R$": "BRL",
}
_CURRENCY_CODES = {
    "USD", "EUR", "GBP", "MUR", "ZAR", "INR", "AED", "CHF", "JPY", "CNY",
    "AUD", "CAD", "SGD", "KES", "NGN", "BRL",
}

_TRAILING_PERCENT = re.compile(r"%\s*$")
_NOT_NUMERIC = re.compile(r"[^\d.,\-()]")
#: 1.234,56 — a comma decimal separator with dots grouping.
_EURO_STYLE = re.compile(r"^-?\d{1,3}(?:\.\d{3})+,\d+$")
#: 1 234,56 — space grouping, comma decimal.
_SPACED_EURO = re.compile(r"^-?\d{1,3}(?: \d{3})+,\d+$")

#: Formats that state the order unambiguously — ISO, or a spelled month.
_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
    "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%d-%b-%Y", "%d %b, %Y",
    "%d %B, %Y", "%b %d %Y", "%B %d %Y",
)
#: Three numbers separated by / - or . — the order is not stated by the text.
_NUMERIC_DATE = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})$")


def parse_decimal(text: str | None) -> Decimal | None:
    """Read a number from quote text, or return None if it is not one.

    Handles both `1,234.50` and the European `1.234,50`, brackets for negatives,
    and a trailing percent sign.
    """
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None

    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()").strip()
    raw = _TRAILING_PERCENT.sub("", raw).strip()

    # Strip currency words and symbols, keeping only what could be a number.
    cleaned = _NOT_NUMERIC.sub("", raw).strip()
    if not cleaned or cleaned in {"-", ".", ","}:
        return None

    if _EURO_STYLE.match(cleaned) or _SPACED_EURO.match(cleaned):
        cleaned = cleaned.replace(".", "").replace(" ", "").replace(",", ".")
    elif "," in cleaned and "." in cleaned:
        # Whichever separator comes last is the decimal point.
        cleaned = (
            cleaned.replace(",", "")
            if cleaned.rfind(".") > cleaned.rfind(",")
            else cleaned.replace(".", "").replace(",", ".")
        )
    elif "," in cleaned:
        # A lone comma: decimal if it leaves one or two digits, else grouping.
        tail = cleaned.rsplit(",", 1)[1]
        cleaned = cleaned.replace(",", "." if len(tail) in (1, 2) else "")

    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -value if negative else value


def parse_percent(text: str | None) -> Decimal | None:
    """A discount, as a percentage number — `32`, `32%` and `32.00` all give 32."""
    return parse_decimal(text)


def detect_currency(*texts: str | None) -> str:
    """Find a currency code in any of the given strings.

    Codes are checked before symbols: `USD 40.00` should not be read as a dollar
    sign that happens to sit next to letters.
    """
    for text in texts:
        if not text:
            continue
        upper = str(text).upper()
        for code in _CURRENCY_CODES:
            if re.search(rf"\b{code}\b", upper):
                return code

    for text in texts:
        if not text:
            continue
        for symbol, code in _CURRENCY_SYMBOLS.items():
            if symbol in str(text):
                return code
    return ""


def parse_date(text: str | None, day_first: bool | None = None) -> date | None:
    """Read a date, refusing ambiguous day/month orders by default.

    `05/06/2026` is 5 June to most of the world and 6 May in the United States,
    and the page does not say which. Left unread, the Date column is visibly
    blank and someone fixes it; guessed wrong, it is plausible and nobody
    notices — so the same rule the converter applies to cells applies here.

    ``day_first`` overrides that for a deployment whose suppliers all follow one
    convention: True reads 05/06 as 5 June, False as 6 May.
    """
    if not text:
        return None
    raw = str(text).strip()

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    match = _NUMERIC_DATE.match(raw)
    if match is None:
        return None

    first, second, year = (int(g) for g in match.groups())

    # One field above twelve can only be the day, whatever the convention.
    if first > 12 >= second:
        return _safe_date(year, second, first)
    if second > 12 >= first:
        return _safe_date(year, first, second)

    if day_first is None:
        return None
    return _safe_date(year, second, first) if day_first else _safe_date(year, first, second)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


#: A date anywhere inside a longer string.
_DATE_LIKE = re.compile(
    r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}"
    r"|\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4}"
    r"|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})"
)


def find_date_in(text: str | None) -> date | None:
    """Pull a date out of a longer string.

    A label's value often runs into whatever follows it on the same line —
    "Date: 2026/05/06 Partner Email:" — because the page put them side by side
    and reading order joins them. Searching for the date shape avoids having to
    guess where the value ends.
    """
    if not text:
        return None
    for match in _DATE_LIKE.finditer(str(text)):
        parsed = parse_date(match.group(1))
        if parsed is not None:
            return parsed
    return None


def find_labelled_value(lines: list[str], *labels: str) -> str:
    """Find the text following a label such as `Date:` or `Quotation No`.

    Quotes put the value on the same line as its label far more often than not,
    so that is what this looks for.
    """
    for line in lines:
        for label in labels:
            pattern = rf"{re.escape(label)}\s*[:\-]?\s*(.+)"
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                # Stop at the next label on the same line: "Date: x  Ref: y".
                value = re.split(r"\s{2,}[A-Z][A-Za-z /]{2,}\s*:", value)[0]
                if value:
                    return value.strip()
    return ""
