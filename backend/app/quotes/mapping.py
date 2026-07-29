"""Deciding which column of a quote's table means what.

Two strategies, tried in order. Header names are matched against a synonym list
first, because when a supplier writes "Unit Price" there is nothing to reason
about and a rule is instant, free and deterministic. Anything the rules cannot
place goes to a language model.

Both return *indices*, never values. Whatever decides the mapping chooses where
to look; the numbers are then read from the extraction, so a model cannot invent
a price.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.models.grid import SheetGrid
from app.quotes.schema import ColumnMapping, TableLocation

logger = logging.getLogger(__name__)

#: Header wordings seen in the wild, per template field. Order matters within a
#: field: the earlier patterns are the more specific ones.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "ref": (
        "ref / code", "ref/code", "part number", "part no", "item code",
        "product code", "sku", "article", "reference", "ref", "code", "item no",
        "material", "mpn",
    ),
    "description": (
        "description", "product description", "item description", "details",
        "product", "item", "designation", "particulars",
    ),
    "qty": ("quantity", "qty", "units", "no. of units", "nos", "pcs"),
    "unit_price": (
        "list price", "unit price", "rate", "price each", "unit cost",
        "gross price", "u/price", "price",
    ),
    "discount": ("disc %", "discount %", "discount", "disc", "rebate", "less"),
    "discounted_price": (
        "discounted price", "net price", "net unit price", "net rate",
        "price after discount", "net",
    ),
    "total": (
        "total price", "line total", "extended price", "amount", "total",
        "sub total", "subtotal", "value",
    ),
}

#: A header row must place at least this many fields to be believed.
_MIN_MATCHED_FIELDS = 3


@dataclass(frozen=True)
class HeaderCandidate:
    """A row that might be the table's header, and what it matched."""

    row: int
    mapping: ColumnMapping
    matched: int
    #: How many rows the heading occupies, so data starts after all of them.
    depth: int = 1

    @property
    def is_credible(self) -> bool:
        return self.matched >= _MIN_MATCHED_FIELDS and self.mapping.is_usable


def _normalise(text: str) -> str:
    """Lower-case, collapse whitespace, drop currency and unit noise.

    Headers are routinely written over several lines — "LIST / PRICE / USD" —
    and the grid rejoins them with spaces, so the currency has to come off before
    matching or "list price usd" never equals "list price".
    """
    cleaned = re.sub(r"\s+", " ", text or "").strip().lower()
    cleaned = re.sub(r"[（(]\s*(usd|eur|gbp|mur|incl|excl)[^)）]*[)）]", " ", cleaned)
    cleaned = re.sub(r"\b(usd|eur|gbp|mur|zar|inr|aed|vat|excl|incl)\b", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" .:-")


def _score_header_row(texts: dict[int, str]) -> tuple[ColumnMapping, int]:
    """Match one row's cells against the synonym lists."""
    mapping = ColumnMapping()
    taken: set[int] = set()
    matched = 0

    # Longest synonyms first so "net price" wins over "price" for the same cell.
    ordered_fields = sorted(
        _SYNONYMS.items(),
        key=lambda kv: max(len(s) for s in kv[1]),
        reverse=True,
    )

    for field, synonyms in ordered_fields:
        if getattr(mapping, field) is not None:
            continue
        best: tuple[int, int] | None = None  # (specificity, column)

        for column, raw in texts.items():
            if column in taken:
                continue
            label = _normalise(raw)
            if not label:
                continue
            for synonym in synonyms:
                # Exact match, or the header contains the synonym as words.
                if label == synonym or re.search(rf"\b{re.escape(synonym)}\b", label):
                    specificity = len(synonym)
                    if best is None or specificity > best[0]:
                        best = (specificity, column)
                    break

        if best is not None:
            setattr(mapping, field, best[1])
            taken.add(best[1])
            matched += 1

    return mapping, matched


def _row_texts(sheet: SheetGrid, row: int) -> dict[int, str]:
    return {
        cell.col: cell.text
        for cell in sheet.cells
        if cell.row == row and cell.text.strip()
    }


def _composite_texts(sheet: SheetGrid, rows: range) -> dict[int, str]:
    """Join several rows into one header, column by column.

    Column headings are frequently stacked to keep a table narrow — `LIST` over
    `PRICE` over `USD`. Read one row at a time, three separate columns all say
    just "PRICE" and only one of them can win the match. Read together they say
    "LIST PRICE USD", "NET PRICE (USD)" and "TOTAL PRICE USD", which are
    distinguishable.
    """
    merged: dict[int, list[str]] = {}
    for row in rows:
        for column, text in _row_texts(sheet, row).items():
            merged.setdefault(column, []).append(text)
    return {column: " ".join(parts) for column, parts in merged.items()}


def find_header_row(sheet: SheetGrid) -> HeaderCandidate | None:
    """The most credible header on a sheet, if there is one.

    Every row is scored rather than assuming the table starts near the top:
    quotes carry a letterhead, an address block and terms before the items. Each
    position is tried as a one, two and three row header, and the reading that
    places the most fields wins.
    """
    best: HeaderCandidate | None = None

    for row in range(sheet.n_rows):
        for depth in (1, 2, 3):
            if row + depth > sheet.n_rows:
                break
            window = range(row, row + depth)
            texts = _composite_texts(sheet, window)
            if len(texts) < _MIN_MATCHED_FIELDS:
                continue

            mapping, matched = _score_header_row(texts)
            candidate = HeaderCandidate(
                row=row, mapping=mapping, matched=matched, depth=depth
            )
            if not candidate.is_credible:
                continue
            # More fields placed wins; a shallower header breaks the tie, so a
            # single-row header is not padded with the data row beneath it.
            if best is None or (matched, -depth) > (best.matched, -best.depth):
                best = candidate

    if best is not None:
        logger.info(
            "matched quote header by rule",
            extra={
                "page": sheet.page_number,
                "row": best.row,
                "rows_used": best.depth,
                "fields": best.mapping.assigned(),
            },
        )
    return best


def locate_table(sheet: SheetGrid) -> TableLocation | None:
    """Find the line-item table on a sheet using header synonyms alone."""
    candidate = find_header_row(sheet)
    if candidate is None:
        return None

    # A multi-line header ("LIST / PRICE / USD") occupies several rows; data
    # starts at the first row below that carries something in a mapped column.
    mapped_columns = set(candidate.mapping.assigned().values())
    heading_end = candidate.row + candidate.depth
    first_data_row = heading_end

    for row in range(heading_end, sheet.n_rows):
        texts = _row_texts(sheet, row)
        if not texts:
            continue
        # Still header if every populated cell reads like a header word.
        if all(_normalise(t) and _looks_like_header(t) for t in texts.values()):
            continue
        if mapped_columns & set(texts):
            first_data_row = row
            break

    return TableLocation(
        page_number=sheet.page_number,
        header_row=candidate.row,
        first_data_row=first_data_row,
        columns=candidate.mapping,
    )


def _looks_like_header(text: str) -> bool:
    label = _normalise(text)
    if not label:
        return False
    return any(label == synonym for synonyms in _SYNONYMS.values() for synonym in synonyms)
