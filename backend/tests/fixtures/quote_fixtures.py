"""Generated supplier quotes, each with its line items known in advance.

Modelled on quotes that actually arrive: a letterhead, a block of reference
fields, and a table whose column headings differ from supplier to supplier. One
fixture per awkward habit — headings stacked over three rows, a totals row at the
bottom, a page with no table at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from tests.fixtures.catalog import GENERATED_DIR

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT = 40.0
FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


@dataclass(frozen=True)
class ExpectedItem:
    ref: str
    description: str
    qty: Decimal
    unit_price: Decimal
    discount: Decimal | None
    total: Decimal


@dataclass
class QuoteSpec:
    """A quote to render, and what must come back out of it."""

    name: str
    supplier: str
    quote_date: str
    currency: str
    #: Column headings, one entry per column; a tuple stacks over several rows.
    headings: list[str | tuple[str, ...]]
    #: Cell text per row, aligned with the headings.
    rows: list[list[str]]
    expected_items: list[ExpectedItem]
    #: Appended after the items, e.g. a grand total.
    trailer: list[list[str]] = field(default_factory=list)
    include_table: bool = True


@dataclass
class QuoteFixture:
    pdf_path: Path
    expected_items: list[ExpectedItem]
    expected_supplier: str
    expected_date: date
    expected_currency: str


_COLUMN_X = (LEFT, 150.0, 300.0, 360.0, 430.0, 500.0)


def _draw(spec: QuoteSpec, path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4)
    y = PAGE_HEIGHT - 50

    pdf.setFont(FONT_BOLD, 13)
    pdf.drawString(LEFT, y, spec.supplier)
    y -= 18
    pdf.setFont(FONT, 9)
    pdf.drawString(LEFT, y, "12 Industrial Road, Port Louis")
    y -= 12
    pdf.drawString(LEFT, y, f"Date: {spec.quote_date}")
    y -= 12
    pdf.drawString(LEFT, y, f"Quotation No: Q-{abs(hash(spec.name)) % 10000:04d}")
    y -= 12
    pdf.drawString(LEFT, y, f"All prices in {spec.currency}")
    y -= 28

    if not spec.include_table:
        pdf.setFont(FONT, 9)
        for line in (
            "Thank you for your enquiry. We regret that we are unable to quote",
            "for the items requested at this time. Please contact our office to",
            "discuss alternatives or revised delivery schedules.",
        ):
            pdf.drawString(LEFT, y, line)
            y -= 13
        pdf.save()
        return

    # Headings, stacked upwards so a tuple's last element sits on the base line.
    depth = max(len(h) if isinstance(h, tuple) else 1 for h in spec.headings)
    pdf.setFont(FONT_BOLD, 8.5)
    for level in range(depth):
        for index, heading in enumerate(spec.headings):
            parts = heading if isinstance(heading, tuple) else (heading,)
            offset = level - (depth - len(parts))
            if 0 <= offset < len(parts):
                pdf.drawString(_COLUMN_X[index], y, parts[offset])
        y -= 11
    y -= 6

    pdf.setFont(FONT, 8.5)
    for row in [*spec.rows, *spec.trailer]:
        for index, text in enumerate(row):
            if text:
                pdf.drawString(_COLUMN_X[index], y, text)
        y -= 14

    pdf.save()


QUOTE_SPECS: dict[str, QuoteSpec] = {
    # Headings on one row, the plainest case.
    "simple_quote": QuoteSpec(
        name="simple_quote",
        supplier="Indian Ocean Technologies",
        quote_date="2026-03-14",
        currency="EUR",
        headings=["Code", "Description", "Qty", "Unit Price", "Discount", "Amount"],
        rows=[
            ["SW-1001", "Managed switch 24-port", "2", "410.00", "10", "738.00"],
            ["SW-1002", "SFP module 10G", "8", "58.50", "10", "421.20"],
            ["CBL-330", "Patch cable 3m", "40", "3.20", "0", "128.00"],
        ],
        expected_items=[
            ExpectedItem("SW-1001", "Managed switch 24-port", Decimal("2"), Decimal("410.00"), Decimal("10"), Decimal("738.00")),
            ExpectedItem("SW-1002", "SFP module 10G", Decimal("8"), Decimal("58.50"), Decimal("10"), Decimal("421.20")),
            ExpectedItem("CBL-330", "Patch cable 3m", Decimal("40"), Decimal("3.20"), Decimal("0"), Decimal("128.00")),
        ],
    ),
    # Money columns whose headings stack over three rows, as on a real quote.
    "stacked_headings": QuoteSpec(
        name="stacked_headings",
        supplier="Exclusive Networks Mauritius",
        quote_date="2026-05-06",
        currency="USD",
        headings=[
            "SKU",
            "DESCRIPTION",
            "QTY",
            ("LIST", "PRICE", "USD"),
            ("DISC", "%"),
            ("NET", "PRICE", "USD"),
        ],
        rows=[
            ["FCZ-15-F100F", "FortiGate-100F Unified Threat", "1.00", "3,740.00", "32.00", "2,543.20"],
            ["FCZ-15-00207", "FortiGate-200E Unified Threat", "1.00", "3,145.90", "32.00", "2,139.21"],
        ],
        expected_items=[
            ExpectedItem("FCZ-15-F100F", "FortiGate-100F Unified Threat", Decimal("1.00"), Decimal("3740.00"), Decimal("32.00"), Decimal("2543.20")),
            ExpectedItem("FCZ-15-00207", "FortiGate-200E Unified Threat", Decimal("1.00"), Decimal("3145.90"), Decimal("32.00"), Decimal("2139.21")),
        ],
    ),
    # A grand total under the items, which must not become one.
    "with_totals_row": QuoteSpec(
        name="with_totals_row",
        supplier="Cape Supply Company",
        quote_date="2026-01-22",
        currency="ZAR",
        headings=["Part No", "Item Description", "Quantity", "Rate", "Disc", "Line Total"],
        rows=[
            ["PN-77", "Steel bracket 40mm", "120", "12.50", "0", "1500.00"],
            ["PN-78", "Hex bolt M8", "1000", "0.35", "0", "350.00"],
        ],
        trailer=[
            ["", "Subtotal", "", "", "", "1850.00"],
            ["", "VAT 15%", "", "", "", "277.50"],
            ["", "Total Due", "", "", "", "2127.50"],
        ],
        expected_items=[
            ExpectedItem("PN-77", "Steel bracket 40mm", Decimal("120"), Decimal("12.50"), Decimal("0"), Decimal("1500.00")),
            ExpectedItem("PN-78", "Hex bolt M8", Decimal("1000"), Decimal("0.35"), Decimal("0"), Decimal("350.00")),
        ],
    ),
    # A letter with no table at all.
    "no_table": QuoteSpec(
        name="no_table",
        supplier="Northern Trading Ltd",
        quote_date="2026-02-02",
        currency="GBP",
        headings=[],
        rows=[],
        expected_items=[],
        include_table=False,
    ),
}


@lru_cache(maxsize=None)
def get_quote_fixture(name: str) -> QuoteFixture:
    """Render (once per session) and return the named quote fixture."""
    if name not in QUOTE_SPECS:
        raise KeyError(f"unknown quote fixture {name!r}; available: {sorted(QUOTE_SPECS)}")

    spec = QUOTE_SPECS[name]
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / f"quote_{spec.name}.pdf"
    _draw(spec, path)

    return QuoteFixture(
        pdf_path=path,
        expected_items=spec.expected_items,
        expected_supplier=spec.supplier,
        expected_date=date.fromisoformat(spec.quote_date),
        expected_currency=spec.currency,
    )
