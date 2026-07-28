"""The structured representation handed to the Excel writer.

A :class:`SheetGrid` is the pipeline's single source of truth for one worksheet:
it fixes the row/column geometry, the value and typography of every cell, and
where images are anchored.  Nothing downstream of grid mapping looks at the PDF
again, so anything the workbook must reproduce has to be represented here.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Union

from pydantic import BaseModel, Field, field_validator

from app.models.content import TextSource
from app.models.geometry import BBox

#: The Python types a cell value may take once type inference has run.
CellValue = Union[str, int, float, bool, date, datetime, None]


class HAlign(StrEnum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class VAlign(StrEnum):
    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"


class BorderStyle(StrEnum):
    NONE = "none"
    THIN = "thin"
    MEDIUM = "medium"
    THICK = "thick"


class Border(BaseModel):
    style: BorderStyle = BorderStyle.NONE
    color: str = "000000"

    @property
    def visible(self) -> bool:
        return self.style is not BorderStyle.NONE


class CellBorders(BaseModel):
    left: Border = Field(default_factory=Border)
    right: Border = Field(default_factory=Border)
    top: Border = Field(default_factory=Border)
    bottom: Border = Field(default_factory=Border)

    @property
    def any_visible(self) -> bool:
        return any(b.visible for b in (self.left, self.right, self.top, self.bottom))


class CellStyle(BaseModel):
    """Typography and decoration for one cell."""

    font_name: str = "Calibri"
    font_size: float = 11.0
    bold: bool = False
    italic: bool = False
    font_color: str = "000000"
    fill_color: str | None = None
    h_align: HAlign = HAlign.LEFT
    v_align: VAlign = VAlign.BOTTOM
    borders: CellBorders = Field(default_factory=CellBorders)
    wrap_text: bool = False


class GridCell(BaseModel):
    """One logical cell of the output worksheet.

    ``row``/``col`` are 0-based; the Excel writer converts to openpyxl's 1-based
    indexing at the last moment.  A cell with ``row_span``/``col_span`` greater
    than one is the anchor of a merged range and owns the whole region.
    """

    row: int = Field(ge=0)
    col: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)

    #: Text exactly as it reads on the page, before type inference.
    text: str = ""
    #: Typed value written to the workbook; ``None`` until type inference runs.
    value: CellValue = None
    #: Excel number format that makes ``value`` display as ``text``.
    number_format: str = "General"

    style: CellStyle = Field(default_factory=CellStyle)
    #: Region of the source page this cell was derived from.
    bbox: BBox | None = None

    source: TextSource = TextSource.DIGITAL
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip() and self.value is None

    @property
    def is_merged(self) -> bool:
        return self.row_span > 1 or self.col_span > 1

    def covers(self, row: int, col: int) -> bool:
        return (
            self.row <= row < self.row + self.row_span
            and self.col <= col < self.col + self.col_span
        )


class AnchoredImage(BaseModel):
    """An extracted image pinned to a cell, with an explicit pixel size."""

    path: str
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    #: Sub-cell offset in points, so a logo does not jump to the cell corner.
    offset_x_pt: float = 0.0
    offset_y_pt: float = 0.0


class SheetGrid(BaseModel):
    """A complete worksheet: geometry, cells, and images."""

    page_number: int = Field(ge=1)
    title: str
    #: How the source page was read: digital, scanned or hybrid.
    kind: str = "digital"
    n_rows: int = Field(ge=0)
    n_cols: int = Field(ge=0)
    cells: list[GridCell] = Field(default_factory=list)
    images: list[AnchoredImage] = Field(default_factory=list)

    #: Column widths and row heights in *points*, converted by the writer.
    col_widths_pt: list[float] = Field(default_factory=list)
    row_heights_pt: list[float] = Field(default_factory=list)

    #: Source page size, retained for verification renders in Phase 4.
    page_width_pt: float = 0.0
    page_height_pt: float = 0.0

    @field_validator("title")
    @classmethod
    def _sanitise_title(cls, value: str) -> str:
        """Excel rejects []:*?/\\ in sheet names and caps them at 31 chars."""
        cleaned = value
        for bad in "[]:*?/\\":
            cleaned = cleaned.replace(bad, "-")
        cleaned = cleaned.strip("'") or "Sheet"
        return cleaned[:31]

    def cell_at(self, row: int, col: int) -> GridCell | None:
        """Return the cell anchored exactly at ``(row, col)``."""
        for cell in self.cells:
            if cell.row == row and cell.col == col:
                return cell
        return None

    def cell_covering(self, row: int, col: int) -> GridCell | None:
        """Return the cell occupying ``(row, col)``, following merged ranges."""
        for cell in self.cells:
            if cell.covers(row, col):
                return cell
        return None

    def non_empty_cells(self) -> list[GridCell]:
        return [c for c in self.cells if not c.is_empty]


class DocumentGrid(BaseModel):
    """Every sheet produced from one PDF, in page order."""

    job_id: str
    sheets: list[SheetGrid] = Field(default_factory=list)

    @property
    def total_cells(self) -> int:
        return sum(len(sheet.non_empty_cells()) for sheet in self.sheets)
