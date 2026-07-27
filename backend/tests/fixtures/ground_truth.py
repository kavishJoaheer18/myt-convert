"""Ground-truth model for generated fixtures.

Because the fixtures are rendered from these declarations, the true value,
position and span of every cell is known before the converter ever runs.  The
comparison in the test suite is therefore against an independent source of truth,
not against the converter's own opinion of what it produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ExpectedCell:
    """One cell the converter is required to produce."""

    row: int
    col: int
    #: Text exactly as it is drawn on the page; the workbook must *display* this.
    text: str
    row_span: int = 1
    col_span: int = 1
    bold: bool = False
    font_size: float = 0.0
    #: Spans are asserted only where the source makes them unambiguous — a ruled
    #: merge is a fact, whereas a heading's visual reach over empty space is not.
    assert_span: bool = True


@dataclass
class ExpectedSheet:
    page_number: int
    title: str
    n_rows: int
    n_cols: int
    cells: list[ExpectedCell] = field(default_factory=list)
    n_images: int = 0
    #: Column widths in points, for the Phase 3 proportion check.
    col_widths_pt: list[float] = field(default_factory=list)
    #: Row/column counts are only asserted for pages whose structure is exact.
    assert_shape: bool = True

    def cell_map(self) -> dict[tuple[int, int], ExpectedCell]:
        return {(c.row, c.col): c for c in self.cells}


@dataclass
class Fixture:
    """A generated PDF and everything that is known to be true about it."""

    name: str
    pdf_path: Path
    sheets: list[ExpectedSheet] = field(default_factory=list)
    description: str = ""

    @property
    def total_cells(self) -> int:
        return sum(len(sheet.cells) for sheet in self.sheets)
