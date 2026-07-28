"""Assign borders, fills and alignment to grid cells.

Grid mapping decides *where* a value belongs; this decides what it looks like.
Both read the same evidence — the rulings and filled rectangles the page already
carries — but they ask different questions of it: the mapper asks which lines
delimit a cell, and this asks which of a cell's four edges is actually drawn.

Cells that hold no text but do carry a border or a fill are materialised here,
because an empty cell in a bordered table is part of the table's appearance and
losing it leaves a hole in the grid.
"""

from __future__ import annotations

import logging

from app.models.content import PageContent, RectDrawing, Ruling
from app.models.geometry import BBox
from app.models.grid import (
    Border,
    BorderStyle,
    CellStyle,
    GridCell,
    HAlign,
    SheetGrid,
    VAlign,
)
from app.pipeline.colors import is_near_white

logger = logging.getLogger(__name__)

#: How far a ruling may sit from a cell edge and still be that edge.
EDGE_TOL = 2.5
#: A ruling must run along this much of the edge to count as bordering it.
MIN_EDGE_COVERAGE = 0.70
#: A filled rectangle must cover this much of a cell to be read as its fill.
MIN_FILL_COVERAGE = 0.80
#: Stroke widths, in points, at which a border changes weight.
MEDIUM_WIDTH = 1.2
THICK_WIDTH = 2.5
#: Alignment is called only when one side's slack exceeds the other by this much.
ALIGN_TOL = 3.0


def _border_style(stroke_width: float) -> BorderStyle:
    if stroke_width >= THICK_WIDTH:
        return BorderStyle.THICK
    if stroke_width >= MEDIUM_WIDTH:
        return BorderStyle.MEDIUM
    return BorderStyle.THIN


def _edge_ruling(
    rulings: list[Ruling],
    orientation: str,
    position: float,
    span_start: float,
    span_end: float,
) -> Ruling | None:
    """The ruling drawn along one edge of a cell, if there is one."""
    length = span_end - span_start
    if length <= 0:
        return None

    best: Ruling | None = None
    for ruling in rulings:
        if ruling.orientation != orientation:
            continue
        if abs(ruling.position - position) > EDGE_TOL:
            continue

        low, high = ruling.span
        covered = min(span_end, high) - max(span_start, low)
        if covered / length < MIN_EDGE_COVERAGE:
            continue

        # Prefer the heaviest stroke where several rules coincide.
        if best is None or ruling.stroke_width > best.stroke_width:
            best = ruling

    return best


def _cell_rect(
    cell: GridCell, col_bounds: list[float], row_bounds: list[float]
) -> BBox | None:
    """The cell's rectangle on the page, following its merged span."""
    last_col = min(cell.col + cell.col_span, len(col_bounds) - 1)
    last_row = min(cell.row + cell.row_span, len(row_bounds) - 1)
    if cell.col >= last_col or cell.row >= last_row:
        return None
    return BBox(
        x0=col_bounds[cell.col],
        top=row_bounds[cell.row],
        x1=col_bounds[last_col],
        bottom=row_bounds[last_row],
    )


def _borders_for(rect: BBox, rulings: list[Ruling]) -> tuple[Border, Border, Border, Border]:
    """``(left, right, top, bottom)`` borders for a cell rectangle."""

    def edge(orientation: str, position: float, start: float, end: float) -> Border:
        ruling = _edge_ruling(rulings, orientation, position, start, end)
        if ruling is None:
            return Border()
        return Border(style=_border_style(ruling.stroke_width), color=ruling.color)

    return (
        edge("v", rect.x0, rect.top, rect.bottom),
        edge("v", rect.x1, rect.top, rect.bottom),
        edge("h", rect.top, rect.x0, rect.x1),
        edge("h", rect.bottom, rect.x0, rect.x1),
    )


def _fill_for(rect: BBox, rects: list[RectDrawing]) -> str | None:
    """The fill colour painted behind a cell, if any.

    The smallest qualifying rectangle wins: a page-wide background must not
    override the shading drawn specifically behind a header row.
    """
    best: RectDrawing | None = None
    for drawing in rects:
        if not drawing.fill_color or is_near_white(drawing.fill_color):
            continue
        if rect.overlap_ratio(drawing.bbox) < MIN_FILL_COVERAGE:
            continue
        if best is None or drawing.bbox.area < best.bbox.area:
            best = drawing
    return best.fill_color if best is not None else None


def _alignment_for(content: BBox | None, rect: BBox) -> tuple[HAlign, VAlign]:
    """Infer alignment from where the text sits inside its cell."""
    if content is None:
        return HAlign.LEFT, VAlign.BOTTOM

    left_slack = content.x0 - rect.x0
    right_slack = rect.x1 - content.x1
    if abs(left_slack - right_slack) <= ALIGN_TOL:
        horizontal = HAlign.CENTER
    elif left_slack < right_slack:
        horizontal = HAlign.LEFT
    else:
        horizontal = HAlign.RIGHT

    top_slack = content.top - rect.top
    bottom_slack = rect.bottom - content.bottom
    if abs(top_slack - bottom_slack) <= ALIGN_TOL:
        vertical = VAlign.CENTER
    elif top_slack < bottom_slack:
        vertical = VAlign.TOP
    else:
        vertical = VAlign.BOTTOM

    return horizontal, vertical


def _style_cell(
    cell: GridCell,
    col_bounds: list[float],
    row_bounds: list[float],
    rulings: list[Ruling],
    rects: list[RectDrawing],
) -> None:
    rect = _cell_rect(cell, col_bounds, row_bounds)
    if rect is None:
        return

    left, right, top, bottom = _borders_for(rect, rulings)
    cell.style.borders.left = left
    cell.style.borders.right = right
    cell.style.borders.top = top
    cell.style.borders.bottom = bottom

    fill = _fill_for(rect, rects)
    if fill is not None:
        cell.style.fill_color = fill

    cell.style.h_align, cell.style.v_align = _alignment_for(cell.bbox, rect)


def _materialise_decorated_blanks(
    grid: SheetGrid,
    col_bounds: list[float],
    row_bounds: list[float],
    rulings: list[Ruling],
    rects: list[RectDrawing],
) -> list[GridCell]:
    """Create empty cells for positions that are bordered or filled.

    An empty cell inside a bordered table still shows its borders; without this
    the table comes out with gaps where nothing happened to be written.
    """
    occupied = {
        (row, col)
        for cell in grid.cells
        for row in range(cell.row, cell.row + cell.row_span)
        for col in range(cell.col, cell.col + cell.col_span)
    }

    created: list[GridCell] = []
    for row in range(grid.n_rows):
        for col in range(grid.n_cols):
            if (row, col) in occupied:
                continue
            rect = BBox(
                x0=col_bounds[col],
                top=row_bounds[row],
                x1=col_bounds[col + 1],
                bottom=row_bounds[row + 1],
            )
            left, right, top, bottom = _borders_for(rect, rulings)
            fill = _fill_for(rect, rects)
            style = CellStyle()
            style.borders.left = left
            style.borders.right = right
            style.borders.top = top
            style.borders.bottom = bottom
            style.fill_color = fill

            if not style.borders.any_visible and fill is None:
                continue

            created.append(GridCell(row=row, col=col, text="", style=style, bbox=rect))

    return created


def apply_styles(
    grid: SheetGrid,
    page: PageContent,
    col_bounds: list[float],
    row_bounds: list[float],
) -> None:
    """Decorate every cell of ``grid`` from the page's rulings and fills."""
    if grid.n_rows == 0 or grid.n_cols == 0:
        return

    for cell in grid.cells:
        _style_cell(cell, col_bounds, row_bounds, page.rulings, page.rects)

    blanks = _materialise_decorated_blanks(
        grid, col_bounds, row_bounds, page.rulings, page.rects
    )
    grid.cells.extend(blanks)

    logger.info(
        "applied cell styles",
        extra={
            "page": grid.page_number,
            "styled": len(grid.cells),
            "decorated_blanks": len(blanks),
        },
    )
