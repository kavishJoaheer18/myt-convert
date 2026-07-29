"""Turning an extracted page into normalised quote line items.

The grid comes from the ordinary conversion pipeline, so this works on scanned
and digital quotes alike. What is added here is meaning: which rows are items,
which column is the discount, and who sent the quote.

Values are only ever *read* from the grid. The mapping decides where to look.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal

from app.models.grid import DocumentGrid, SheetGrid
from app.quotes.mapping import locate_table
from app.quotes.schema import (
    ColumnMapping,
    LineItem,
    QuoteExtraction,
    QuoteHeader,
    TableLocation,
)
from app.quotes.values import (
    detect_currency,
    find_date_in,
    find_labelled_value,
    infer_day_first,
    parse_decimal,
    parse_percent,
)

logger = logging.getLogger(__name__)

#: Rows whose first cell reads like one of these end the line items.
_TOTAL_MARKERS = (
    "total", "subtotal", "sub total", "grand total", "vat", "tax", "shipping",
    "delivery charge", "amount due", "balance", "net total", "total due",
)
#: A description longer than this is prose, not a line item.
_MAX_DESCRIPTION = 400


def _cell_text(sheet: SheetGrid, row: int, col: int | None) -> str:
    if col is None:
        return ""
    cell = sheet.cell_at(row, col)
    return cell.text.strip() if cell else ""


def _page_lines(sheet: SheetGrid) -> list[str]:
    """The page as text lines, in reading order, for header-field matching."""
    by_row: dict[int, list[tuple[int, str]]] = {}
    for cell in sheet.cells:
        if cell.text.strip():
            by_row.setdefault(cell.row, []).append((cell.col, cell.text.strip()))
    return [
        " ".join(text for _, text in sorted(cells))
        for _, cells in sorted(by_row.items())
    ]


def _is_terminator(first_text: str) -> bool:
    """Has the table reached its totals?"""
    label = re.sub(r"[^a-z ]", " ", first_text.lower()).strip()
    label = re.sub(r"\s+", " ", label)
    return any(label.startswith(marker) for marker in _TOTAL_MARKERS)


#: Page numbering that letterheads share a line with the company name.
_PAGE_FURNITURE = re.compile(r"\s*page\s+\d+\s*(of|/)\s*\d+\s*", re.IGNORECASE)


def _strip_page_furniture(line: str) -> str:
    """Remove "Page 1 of 2" and the like, which sits beside the company name."""
    return _PAGE_FURNITURE.sub(" ", line).strip()


def resolve_day_first(lines: list[str], mapper=None) -> bool | None:
    """Decide whether this quote writes dates day-first.

    The document is asked first: any date on it with a field above twelve settles
    the matter as fact. Only when every date is ambiguous is the model consulted,
    and only if it is confident. Failing both, dates stay blank — visibly missing
    rather than quietly wrong.
    """
    from_document = infer_day_first(lines)
    if from_document is not None:
        return from_document

    resolver = getattr(mapper, "resolve_date_convention", None)
    if resolver is None:
        return None

    try:
        return resolver("\n".join(lines[:40]))
    except Exception as exc:  # noqa: BLE001 - a missing date is not a failed batch
        logger.warning("date convention resolution failed", extra={"error": str(exc)})
        return None


def extract_header(
    sheet: SheetGrid, source_file: str, day_first: bool | None = None
) -> QuoteHeader:
    """Recover supplier, date and currency from the top of the page.

    The supplier is taken as the first substantial line, which is where a
    letterhead puts the company name on essentially every quote.
    """
    lines = _page_lines(sheet)

    supplier = ""
    for line in lines[:6]:
        # "Page 1 of 2" shares the line with the company name on most letterheads.
        candidate = _strip_page_furniture(line)
        if len(candidate) < 3 or re.match(r"^(page|quotation|quote|date)\b", candidate, re.I):
            continue
        supplier = candidate.split("  ")[0][:120]
        break

    date_text = find_labelled_value(lines, "date", "quote date", "quotation date")
    reference = find_labelled_value(
        lines, "ref", "reference", "quote no", "quotation no", "quote number"
    )

    return QuoteHeader(
        supplier=supplier,
        quote_date=(
            find_date_in(date_text, day_first=day_first)
            or find_date_in(" ".join(lines[:25]), day_first=day_first)
        ),
        currency=detect_currency(*lines[:40]),
        reference=reference[:80],
    )


def extract_items(
    sheet: SheetGrid,
    location: TableLocation,
    header: QuoteHeader,
    source_file: str,
) -> list[LineItem]:
    """Read the line items a located table contains."""
    columns: ColumnMapping = location.columns
    items: list[LineItem] = []
    last_row = location.last_data_row if location.last_data_row is not None else sheet.n_rows - 1

    for row in range(location.first_data_row, min(last_row, sheet.n_rows - 1) + 1):
        ref = _cell_text(sheet, row, columns.ref)
        description = _cell_text(sheet, row, columns.description)
        first_text = ref or description

        if first_text and _is_terminator(first_text):
            break

        qty = parse_decimal(_cell_text(sheet, row, columns.qty))
        unit_price = parse_decimal(_cell_text(sheet, row, columns.unit_price))
        discount = parse_percent(_cell_text(sheet, row, columns.discount))
        discounted = parse_decimal(_cell_text(sheet, row, columns.discounted_price))
        total = parse_decimal(_cell_text(sheet, row, columns.total))

        # A row with nothing to identify it and no money on it is a spacer, a
        # continuation of the description above, or a note.
        if not (ref or description):
            continue
        if unit_price is None and total is None and discounted is None:
            continue

        items.append(
            LineItem(
                quote_date=header.quote_date,
                supplier=header.supplier,
                ref=ref[:120],
                description=description[:_MAX_DESCRIPTION],
                currency=header.currency,
                qty=qty,
                unit_price=unit_price,
                discount=discount,
                discounted_price=discounted,
                total=total or _derive_total(qty, discounted or unit_price),
                source_file=source_file,
                source_page=sheet.page_number,
            )
        )

    return items


def _derive_total(qty: Decimal | None, price: Decimal | None) -> Decimal | None:
    """Fill in a line total only when both halves of it are known.

    Arithmetic the supplier did not print is still arithmetic they implied, but
    a guess at either factor would make the sum meaningless.
    """
    if qty is None or price is None:
        return None
    return qty * price


def extract_quote(
    document: DocumentGrid,
    source_file: str,
    mapper=None,
) -> QuoteExtraction:
    """Read every line item from one quote document.

    ``mapper`` is an optional callable taking a sheet and returning a
    :class:`TableLocation`; it is consulted only for pages the synonym rules
    cannot place, which keeps a model out of the common case entirely.
    """
    result = QuoteExtraction(source_file=source_file, strategy="rules")
    if not document.sheets:
        result.warnings.append("no pages could be read")
        return result

    first_sheet = document.sheets[0]
    day_first = resolve_day_first(_page_lines(first_sheet), mapper)
    header = extract_header(first_sheet, source_file, day_first=day_first)
    result.header = header

    for sheet in document.sheets:
        location = locate_table(sheet)

        if location is None and mapper is not None:
            location = mapper(sheet)
            if location is not None:
                result.strategy = "model"

        if location is None:
            continue

        # Continuation pages repeat the header but not the letterhead.
        page_header = header
        if sheet.page_number == document.sheets[0].page_number:
            page_header = header
        items = extract_items(sheet, location, page_header, source_file)
        result.items.extend(items)

        logger.info(
            "extracted quote page",
            extra={
                "file": source_file,
                "page": sheet.page_number,
                "items": len(items),
                "columns": location.columns.assigned(),
            },
        )

    if not result.items:
        result.warnings.append(
            "no line items found — the table's columns could not be identified"
        )
    if not header.supplier:
        result.warnings.append("supplier name not found")
    if header.quote_date is None:
        result.warnings.append(
            "quote date not found, or its day/month order could not be established"
        )

    return result
