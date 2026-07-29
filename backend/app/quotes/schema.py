"""The shape of a supplier quote once it has been normalised.

Suppliers each have their own layout, column names and wording. What they have
in common is a header — who quoted, when, in what currency — and a table of line
items. This is that common shape, and the target every quote is mapped onto.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

#: Template columns, in the order the workbook expects them.
TEMPLATE_HEADERS: tuple[str, ...] = (
    "Date",
    "Supplier",
    "Ref / Code",
    "Description",
    "Currency",
    "Qty",
    "Unit Price",
    "Discount",
    "Discounted Price",
    "Total",
)


class ColumnMapping(BaseModel):
    """Which column of the extracted table holds each template field.

    Indices into the sheet's columns, not values. Whatever decides the mapping —
    a rule or a model — chooses *where to look*; the values themselves are always
    read from the extraction, so they cannot be invented.
    """

    ref: int | None = None
    description: int | None = None
    qty: int | None = None
    unit_price: int | None = None
    discount: int | None = None
    discounted_price: int | None = None
    total: int | None = None

    @property
    def is_usable(self) -> bool:
        """A quote is only worth emitting if it has something to identify a line
        and something to charge for it."""
        has_identity = self.ref is not None or self.description is not None
        has_money = self.unit_price is not None or self.total is not None
        return has_identity and has_money

    def assigned(self) -> dict[str, int]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class QuoteHeader(BaseModel):
    """The facts that apply to every line of a quote."""

    supplier: str = ""
    quote_date: date | None = None
    currency: str = ""
    #: Free-text reference for the quote as a whole, kept for traceability.
    reference: str = ""


class LineItem(BaseModel):
    """One row of the output template."""

    quote_date: date | None = None
    supplier: str = ""
    ref: str = ""
    description: str = ""
    currency: str = ""
    qty: Decimal | None = None
    unit_price: Decimal | None = None
    discount: Decimal | None = None
    discounted_price: Decimal | None = None
    total: Decimal | None = None

    #: Which file and page this came from, so a wrong number can be traced back.
    source_file: str = ""
    source_page: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.ref or self.description)


class TableLocation(BaseModel):
    """Where the line items sit on a page, and how its columns map."""

    page_number: int = Field(ge=1)
    header_row: int | None = None
    first_data_row: int = Field(ge=0)
    last_data_row: int | None = None
    columns: ColumnMapping = Field(default_factory=ColumnMapping)


class QuoteExtraction(BaseModel):
    """Everything recovered from one PDF."""

    source_file: str
    header: QuoteHeader = Field(default_factory=QuoteHeader)
    items: list[LineItem] = Field(default_factory=list)
    #: How the mapping was decided, recorded so a bad batch can be explained.
    strategy: str = "unknown"
    warnings: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.items)
