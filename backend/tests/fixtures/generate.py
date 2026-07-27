"""Render synthetic PDFs whose every cell is known in advance.

Each fixture is declared as a stack of blocks with explicit points-on-the-page
geometry, then rendered with reportlab.  The same declaration yields the expected
worksheet: rows follow the block stacking order, and columns are the union of
every table's edges — the superset grid any correct converter must produce, since
one worksheet can carry only one column structure.

The expected grid is derived from the *declaration*, never from the converter's
output, so agreement between the two is real evidence.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from tests.fixtures.ground_truth import ExpectedCell, ExpectedSheet, Fixture

PAGE_WIDTH, PAGE_HEIGHT = A4
CONTENT_LEFT = 56.0
CONTENT_TOP = 56.0
CELL_PADDING = 5.0
#: Blocks are separated by this much vertical whitespace.
BLOCK_GAP = 18.0

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

#: reportlab writes the base-14 fonts unsubsetted; the font parser maps the
#: PostScript name "Helvetica" onto the family Excel actually has.
EXPECTED_FAMILY = "Arial"


@dataclass(frozen=True)
class Merge:
    """A merged region in table-local coordinates."""

    row: int
    col: int
    row_span: int = 1
    col_span: int = 1

    def covers(self, row: int, col: int) -> bool:
        return (
            self.row <= row < self.row + self.row_span
            and self.col <= col < self.col + self.col_span
        )

    @property
    def is_anchor_only(self) -> bool:
        return self.row_span == 1 and self.col_span == 1


@dataclass
class TextBlock:
    """A single line of text starting at the content's left edge."""

    text: str
    font_size: float = 11.0
    bold: bool = False

    @property
    def height(self) -> float:
        return self.font_size * 1.35


@dataclass
class TableBlock:
    """A grid of text cells, optionally with drawn borders."""

    rows: list[list[str]]
    col_widths: list[float]
    row_height: float = 20.0
    font_size: float = 9.5
    ruled: bool = True
    merges: list[Merge] = field(default_factory=list)
    bold_rows: tuple[int, ...] = ()
    #: Columns whose values are right-aligned, as money and quantities are.
    right_aligned_cols: tuple[int, ...] = ()
    centered_cells: tuple[tuple[int, int], ...] = ()
    right_aligned_cells: tuple[tuple[int, int], ...] = ()

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return len(self.col_widths)

    @property
    def width(self) -> float:
        return sum(self.col_widths)

    @property
    def height(self) -> float:
        return self.n_rows * self.row_height

    def col_edges(self, left: float) -> list[float]:
        edges = [left]
        for width in self.col_widths:
            edges.append(edges[-1] + width)
        return edges

    def merge_at(self, row: int, col: int) -> Merge | None:
        for merge in self.merges:
            if merge.covers(row, col):
                return merge
        return None

    def is_covered(self, row: int, col: int) -> bool:
        """True for a slot swallowed by a merge anchored elsewhere."""
        merge = self.merge_at(row, col)
        return merge is not None and (merge.row, merge.col) != (row, col)


@dataclass
class ImageSwatch:
    """A generated raster placed at the content's left edge."""

    name: str
    width: float
    height: float
    color: tuple[int, int, int] = (30, 90, 160)


Block = TextBlock | TableBlock | ImageSwatch


@dataclass
class PageSpec:
    blocks: list[Block]


@dataclass
class FixtureSpec:
    name: str
    pages: list[PageSpec]
    description: str = ""


# --- Rendering --------------------------------------------------------------


def _flip(y_top: float) -> float:
    """Convert a top-down y coordinate to reportlab's bottom-up origin."""
    return PAGE_HEIGHT - y_top


def _string_width(text: str, size: float, bold: bool) -> float:
    return pdfmetrics.stringWidth(text, FONT_BOLD if bold else FONT_REGULAR, size)


def _draw_text_block(pdf: canvas.Canvas, block: TextBlock, top: float) -> None:
    pdf.setFont(FONT_BOLD if block.bold else FONT_REGULAR, block.font_size)
    # Place the baseline one em below the block top so the glyphs sit inside it.
    pdf.drawString(CONTENT_LEFT, _flip(top + block.font_size), block.text)


def _draw_swatch(pdf: canvas.Canvas, swatch: ImageSwatch, top: float, out_dir: Path) -> Path:
    """Write a deterministic PNG and place it on the page."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{swatch.name}.png"

    if not path.exists():
        image = PILImage.new("RGB", (int(swatch.width * 4), int(swatch.height * 4)), swatch.color)
        # A contrasting bar makes the image visually identifiable in the output.
        for x in range(image.width // 4, image.width // 2):
            for y in range(image.height // 3, 2 * image.height // 3):
                image.putpixel((x, y), (245, 245, 245))
        image.save(path, format="PNG")

    pdf.drawImage(
        str(path),
        CONTENT_LEFT,
        _flip(top + swatch.height),
        width=swatch.width,
        height=swatch.height,
    )
    return path


def _draw_table_borders(pdf: canvas.Canvas, table: TableBlock, left: float, top: float) -> None:
    """Stroke the grid cell by cell, omitting the interiors of merged regions.

    Drawing per cell rather than as full-length rules mirrors how real producers
    emit tables, and exercises the extractor's collinear-segment merging.
    """
    edges = table.col_edges(left)
    pdf.setLineWidth(0.75)
    pdf.setStrokeColorRGB(0.15, 0.15, 0.15)

    for row in range(table.n_rows + 1):
        y = _flip(top + row * table.row_height)
        for col in range(table.n_cols):
            merge = None
            for candidate in table.merges:
                interior = (
                    candidate.row < row < candidate.row + candidate.row_span
                    and candidate.col <= col < candidate.col + candidate.col_span
                )
                if interior:
                    merge = candidate
                    break
            if merge is None:
                pdf.line(edges[col], y, edges[col + 1], y)

    for col in range(table.n_cols + 1):
        x = edges[col]
        for row in range(table.n_rows):
            merge = None
            for candidate in table.merges:
                interior = (
                    candidate.col < col < candidate.col + candidate.col_span
                    and candidate.row <= row < candidate.row + candidate.row_span
                )
                if interior:
                    merge = candidate
                    break
            if merge is None:
                pdf.line(x, _flip(top + row * table.row_height),
                         x, _flip(top + (row + 1) * table.row_height))


def _draw_table(pdf: canvas.Canvas, table: TableBlock, left: float, top: float) -> None:
    if table.ruled:
        _draw_table_borders(pdf, table, left, top)

    edges = table.col_edges(left)
    pdf.setFillColorRGB(0, 0, 0)

    for row_index, row in enumerate(table.rows):
        for col_index, text in enumerate(row):
            if not text or table.is_covered(row_index, col_index):
                continue

            merge = table.merge_at(row_index, col_index)
            span_cols = merge.col_span if merge else 1
            span_rows = merge.row_span if merge else 1

            cell_left = edges[col_index]
            cell_right = edges[min(col_index + span_cols, table.n_cols)]
            cell_top = top + row_index * table.row_height
            cell_height = span_rows * table.row_height

            bold = row_index in table.bold_rows
            pdf.setFont(FONT_BOLD if bold else FONT_REGULAR, table.font_size)
            width = _string_width(text, table.font_size, bold)

            if (row_index, col_index) in table.centered_cells:
                x = cell_left + (cell_right - cell_left - width) / 2.0
            elif (row_index, col_index) in table.right_aligned_cells or (
                col_index in table.right_aligned_cols
            ):
                x = cell_right - CELL_PADDING - width
            else:
                x = cell_left + CELL_PADDING

            # Vertically centre the text within its (possibly merged) region.
            baseline_top = cell_top + cell_height / 2.0 + table.font_size * 0.35
            pdf.drawString(x, _flip(baseline_top), text)


# --- Ground-truth derivation ------------------------------------------------


def _cluster(values: list[float], tol: float = 1.0) -> list[float]:
    if not values:
        return []
    ordered = sorted(values)
    groups: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        if value - groups[-1][-1] <= tol:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [statistics.fmean(g) for g in groups]


def _global_col_bounds(page: PageSpec) -> list[float]:
    """Union of every table's column edges — the sheet's column grid.

    A worksheet has one column structure, so two tables with different widths on
    the same page must share the superset of their edges, each spanning the
    sub-columns it covers.
    """
    edges: list[float] = [CONTENT_LEFT]
    right = CONTENT_LEFT

    for block in page.blocks:
        if isinstance(block, TableBlock):
            edges.extend(block.col_edges(CONTENT_LEFT))
            right = max(right, CONTENT_LEFT + block.width)
        elif isinstance(block, TextBlock):
            right = max(right, CONTENT_LEFT + _string_width(block.text, block.font_size, block.bold))
        elif isinstance(block, ImageSwatch):
            right = max(right, CONTENT_LEFT + block.width)

    edges.append(right)
    return _cluster(edges)


def _boundary_index(value: float, bounds: list[float], tol: float = 1.5) -> int:
    for index, bound in enumerate(bounds):
        if abs(bound - value) <= tol:
            return index
    raise AssertionError(f"edge {value} is not on the fixture's column grid {bounds}")


def _expected_sheet(page: PageSpec, page_number: int, title: str) -> ExpectedSheet:
    """Derive the worksheet the converter must produce for this page."""
    col_bounds = _global_col_bounds(page)
    n_cols = max(1, len(col_bounds) - 1)

    cells: list[ExpectedCell] = []
    row_cursor = 0
    n_images = 0

    for block in page.blocks:
        if isinstance(block, TextBlock):
            cells.append(
                ExpectedCell(
                    row=row_cursor,
                    col=0,
                    text=block.text,
                    bold=block.bold,
                    font_size=block.font_size,
                    # How far a heading visually reaches across empty space is
                    # not a fact about the source, so its span is not asserted.
                    assert_span=False,
                )
            )
            row_cursor += 1

        elif isinstance(block, ImageSwatch):
            n_images += 1
            row_cursor += 1

        elif isinstance(block, TableBlock):
            edges = block.col_edges(CONTENT_LEFT)
            for row_index, row in enumerate(block.rows):
                for col_index, text in enumerate(row):
                    if not text or block.is_covered(row_index, col_index):
                        continue
                    merge = block.merge_at(row_index, col_index)
                    span_cols = merge.col_span if merge else 1
                    span_rows = merge.row_span if merge else 1

                    first = _boundary_index(edges[col_index], col_bounds)
                    last = _boundary_index(
                        edges[min(col_index + span_cols, block.n_cols)], col_bounds
                    )
                    cells.append(
                        ExpectedCell(
                            row=row_cursor + row_index,
                            col=first,
                            text=text,
                            row_span=span_rows,
                            col_span=last - first,
                            bold=row_index in block.bold_rows,
                            font_size=block.font_size,
                            # Borders make a span a fact; whitespace does not.
                            assert_span=block.ruled,
                        )
                    )
            row_cursor += block.n_rows

    return ExpectedSheet(
        page_number=page_number,
        title=title,
        n_rows=row_cursor,
        n_cols=n_cols,
        cells=cells,
        n_images=n_images,
        col_widths_pt=[col_bounds[i + 1] - col_bounds[i] for i in range(n_cols)],
    )


def _sheet_title(page_number: int, total_pages: int) -> str:
    """Mirror the naming the converter applies, so sheets can be matched up."""
    return f"Page {page_number}" if total_pages > 1 else "Sheet1"


def render_fixture(spec: FixtureSpec, out_dir: Path) -> Fixture:
    """Render ``spec`` to a PDF and return it alongside its expected worksheets."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{spec.name}.pdf"
    asset_dir = out_dir / "assets"

    pdf = canvas.Canvas(str(pdf_path), pagesize=A4)
    pdf.setTitle(spec.name)

    sheets: list[ExpectedSheet] = []
    for index, page in enumerate(spec.pages):
        top = CONTENT_TOP
        for block in page.blocks:
            if isinstance(block, TextBlock):
                _draw_text_block(pdf, block, top)
                top += block.height + BLOCK_GAP
            elif isinstance(block, ImageSwatch):
                _draw_swatch(pdf, block, top, asset_dir)
                top += block.height + BLOCK_GAP
            elif isinstance(block, TableBlock):
                _draw_table(pdf, block, CONTENT_LEFT, top)
                top += block.height + BLOCK_GAP

        sheets.append(
            _expected_sheet(page, index + 1, _sheet_title(index + 1, len(spec.pages)))
        )
        pdf.showPage()

    pdf.save()
    return Fixture(
        name=spec.name, pdf_path=pdf_path, sheets=sheets, description=spec.description
    )
