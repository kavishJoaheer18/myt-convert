"""Turn free-floating page content into a row/column grid.

This is the stage that decides accuracy.  A PDF has no notion of cells — only
glyphs at coordinates and lines drawn between them — so the grid has to be
recovered.  The strategy, in order of trustworthiness:

1. **Ruling lines.**  If the producer drew a table border, its vertical and
   horizontal segments *are* the grid.  Nothing inferred beats a line that is
   actually there.
2. **Whitespace columns.**  For borderless tables, a vertical strip that stays
   empty across most text lines is a column separator.
3. **Text lines.**  Rows fall back to the visual lines of text, which is how a
   person transcribing the page would read it.

Columns are global to the sheet (Excel allows only one column grid per
worksheet), so separators found anywhere on the page are unioned; a table that
does not use a given separator simply spans across it as a merged cell.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field

from app.models.content import PageContent, Ruling, Word
from app.models.geometry import BBox
from app.models.grid import GridCell, SheetGrid
from app.pipeline.colors import is_near_white
from app.pipeline.images import anchor_images
from app.pipeline.styles import apply_styles

logger = logging.getLogger(__name__)

# --- Tuning constants -------------------------------------------------------
#: Coordinates closer than this collapse into one boundary.
BOUNDARY_TOL = 2.0
#: Two words belong to the same visual line if their vertical spans overlap this
#: much, relative to the shorter word.
LINE_OVERLAP_RATIO = 0.45
#: First-pass gap (pt) used only to find candidate table rows.
COARSE_GAP = 4.0
#: A whitespace corridor must be at least this wide to separate columns.
MIN_GAP_WIDTH = 5.0
#: ...and must stay empty across at least this fraction of candidate rows.
MIN_GAP_SUPPORT = 0.85
#: Columns and rows thinner than this are artefacts of double-drawn borders.
MIN_BAND_SIZE = 3.0
#: A run must cover this much of a column (relative to the smaller of the two)
#: before it is considered to occupy it.
CELL_OVERLAP_RATIO = 0.30
#: A ruling must be at least this fraction of the page to define table geometry.
MIN_RULING_PAGE_FRACTION = 0.04
#: How far a column's text edges may scatter (pt) before it stops looking like a
#: column. Cell padding is constant, so a real column's edges align to well under
#: a couple of points; justified prose measured three to four times this.
MAX_COLUMN_EDGE_SPREAD = 4.0
#: Rows needed before a column's alignment is worth judging.
MIN_ALIGNMENT_SAMPLES = 3


@dataclass
class TextRun:
    """Consecutive words on one visual line with no column separator between."""

    words: list[Word] = field(default_factory=list)

    @property
    def bbox(self) -> BBox:
        return BBox.union(w.bbox for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words).strip()


@dataclass
class TextLine:
    """One visual line of text on the page."""

    words: list[Word] = field(default_factory=list)

    @property
    def bbox(self) -> BBox:
        return BBox.union(w.bbox for w in self.words)


@dataclass
class _Band:
    """A candidate row, and whether the page actually drew its edges."""

    top: float
    bottom: float
    top_ruled: bool = False
    bottom_ruled: bool = False


def _cluster_positions(values: list[float], tol: float = BOUNDARY_TOL) -> list[float]:
    """Collapse near-duplicate coordinates into their cluster means."""
    if not values:
        return []
    ordered = sorted(values)
    clusters: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        if value - clusters[-1][-1] <= tol:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [statistics.fmean(c) for c in clusters]


def _prune_boundaries(boundaries: list[float], min_size: float = MIN_BAND_SIZE) -> list[float]:
    """Drop boundaries that would create a degenerately thin band."""
    if len(boundaries) <= 2:
        return boundaries
    kept = [boundaries[0]]
    for value in boundaries[1:-1]:
        if value - kept[-1] >= min_size:
            kept.append(value)
    # The final boundary is the content edge and is never negotiable; if the
    # last interior boundary crowds it, the interior one loses.
    while len(kept) > 1 and boundaries[-1] - kept[-1] < min_size:
        kept.pop()
    kept.append(boundaries[-1])
    return kept


# --- Text lines and runs ----------------------------------------------------


def group_words_into_lines(words: list[Word]) -> list[TextLine]:
    """Cluster words into visual lines by vertical overlap."""
    usable = [w for w in words if not w.is_blank]
    if not usable:
        return []

    ordered = sorted(usable, key=lambda w: (w.bbox.top, w.bbox.x0))
    lines: list[list[Word]] = [[ordered[0]]]
    current_top, current_bottom = ordered[0].bbox.top, ordered[0].bbox.bottom

    for word in ordered[1:]:
        box = word.bbox
        overlap = min(current_bottom, box.bottom) - max(current_top, box.top)
        shorter = min(current_bottom - current_top, box.height) or 1.0
        if overlap / shorter >= LINE_OVERLAP_RATIO:
            lines[-1].append(word)
            current_top = min(current_top, box.top)
            current_bottom = max(current_bottom, box.bottom)
        else:
            lines.append([word])
            current_top, current_bottom = box.top, box.bottom

    result = [TextLine(words=sorted(ws, key=lambda w: w.bbox.x0)) for ws in lines]
    return sorted(result, key=lambda line: line.bbox.top)


def _split_line_by_gaps(line: TextLine, gap: float) -> list[TextRun]:
    """Split a line wherever the horizontal gap between words exceeds ``gap``."""
    runs: list[TextRun] = []
    current: list[Word] = []
    previous_x1: float | None = None

    for word in line.words:
        if previous_x1 is not None and word.bbox.x0 - previous_x1 > gap:
            runs.append(TextRun(words=current))
            current = []
        current.append(word)
        previous_x1 = word.bbox.x1

    if current:
        runs.append(TextRun(words=current))
    return runs


def _crossing_verticals(
    band_top: float, band_bottom: float, verticals: list[Ruling]
) -> list[float]:
    """X positions of vertical rulings that actually cross this row band."""
    band_mid = (band_top + band_bottom) / 2.0
    return sorted(
        {
            ruling.position
            for ruling in verticals
            if ruling.span[0] <= band_mid + BOUNDARY_TOL
            and ruling.span[1] >= band_mid - BOUNDARY_TOL
        }
    )


def _split_line_for_row(
    line: TextLine,
    band_top: float,
    band_bottom: float,
    corridors: list[float],
    verticals: list[Ruling],
) -> list[TextRun]:
    """Split one line into cell-sized runs, using whatever evidence this row has.

    Where the producer drew borders across this band, *those* borders delimit the
    cells and nothing else does — which is the only way a cell merged across four
    columns survives as one value instead of being torn along the column grid it
    deliberately ignores.

    Rows outside any ruled table are split only at whitespace corridors that were
    confirmed to run down the page — never at the sheet's global column
    boundaries, and never at a bare gap.  Those boundaries may come from a table
    elsewhere on the page, and applying them to a paragraph shreds its sentences
    into columns that have nothing to do with it.  A wide gap alone is no better
    evidence: justification stretches word spaces, and OCR reports a line in
    fragments with gaps of its own making.

    The rule is therefore that a line is only cut where something on the page
    positively says a column boundary is there.
    """
    if not line.words:
        return []

    crossing = _crossing_verticals(band_top, band_bottom, verticals)
    separators = crossing if len(crossing) >= 2 else corridors

    runs: list[TextRun] = []
    current: list[Word] = []
    previous: Word | None = None

    for word in line.words:
        if previous is not None:
            gap_start, gap_end = previous.bbox.x1, word.bbox.x0
            if any(gap_start < s < gap_end for s in separators):
                runs.append(TextRun(words=current))
                current = []
        current.append(word)
        previous = word

    if current:
        runs.append(TextRun(words=current))
    return runs


def _coarse_gap_for_line(line: TextLine) -> float:
    """Gap that separates columns rather than words, scaled to the line's font.

    A space advance is roughly 0.28 em, so a gap of more than about one and a
    half spaces is structural rather than typographic.  Without this scaling a
    fixed threshold splits large headings at every space.
    """
    sizes = [w.font_size for w in line.words if w.font_size > 0]
    size = statistics.median(sizes) if sizes else 10.0
    return max(COARSE_GAP, 1.6 * 0.28 * size)


def _column_index_for(x: float, boundaries: list[float]) -> int:
    """Index of the column band containing ``x`` (clamped to the grid)."""
    for i in range(len(boundaries) - 1):
        if boundaries[i] <= x < boundaries[i + 1]:
            return i
    return max(0, len(boundaries) - 2)


# --- Column discovery -------------------------------------------------------


def _significant_rulings(rulings: list[Ruling], orientation: str, page_extent: float) -> list[Ruling]:
    minimum = page_extent * MIN_RULING_PAGE_FRACTION
    return [r for r in rulings if r.orientation == orientation and r.length >= minimum]


def _column_edges_from_rulings(page: PageContent) -> list[float]:
    verticals = _significant_rulings(page.rulings, "v", page.height)
    return _cluster_positions([r.position for r in verticals])


def _column_edges_from_whitespace(
    lines: list[TextLine], content: BBox
) -> list[float]:
    """Find vertical corridors that stay empty across most candidate table rows.

    Only lines that already look like table rows (two or more coarse runs) get a
    vote, so a full-width heading cannot veto every column separator underneath
    it.
    """
    candidates: list[list[TextRun]] = []
    for line in lines:
        runs = _split_line_by_gaps(line, _coarse_gap_for_line(line))
        if len(runs) >= 2:
            candidates.append(runs)

    if len(candidates) < 2:
        return []

    # Sample occupancy on a fine lattice across the content width.
    step = 0.5
    n_bins = max(1, int(content.width / step) + 1)
    free_counts = [0] * n_bins

    for runs in candidates:
        occupied = [False] * n_bins
        for run in runs:
            box = run.bbox
            start = max(0, int((box.x0 - content.x0) / step))
            end = min(n_bins - 1, int((box.x1 - content.x0) / step))
            for b in range(start, end + 1):
                occupied[b] = True
        for b in range(n_bins):
            if not occupied[b]:
                free_counts[b] += 1

    required = len(candidates) * MIN_GAP_SUPPORT
    separators: list[float] = []
    run_start: int | None = None

    for b in range(n_bins):
        is_free = free_counts[b] >= required
        if is_free and run_start is None:
            run_start = b
        elif not is_free and run_start is not None:
            separators.extend(_corridor_to_separator(run_start, b - 1, step, content))
            run_start = None
    if run_start is not None:
        separators.extend(_corridor_to_separator(run_start, n_bins - 1, step, content))

    if separators and not _columns_are_aligned(candidates, separators, content):
        return []
    return separators


def _columns_are_aligned(
    candidates: list[list[TextRun]], separators: list[float], content: BBox
) -> bool:
    """Do the proposed columns look like a table, or like justified prose?

    In a table the values of a column start (or, for numbers, end) at very nearly
    the same x on every row. In justified text the inter-word gaps drift from
    line to line, and enough of them can coincide to punch a corridor clean
    through a paragraph — which is how a page of prose ends up split into ten
    "columns".

    Requiring the edges to line up separates the two cases without needing to
    know anything about the words themselves.
    """
    bounds = [content.x0, *separators, content.x1]
    spreads: list[float] = []

    for index in range(len(bounds) - 1):
        low, high = bounds[index], bounds[index + 1]
        lefts: list[float] = []
        rights: list[float] = []

        for runs in candidates:
            inside = [r for r in runs if low <= r.bbox.cx < high]
            if not inside:
                continue
            lefts.append(min(r.bbox.x0 for r in inside))
            rights.append(max(r.bbox.x1 for r in inside))

        if len(lefts) < MIN_ALIGNMENT_SAMPLES:
            continue
        # Either edge lining up is enough: columns of numbers are right-aligned.
        spreads.append(min(statistics.pstdev(lefts), statistics.pstdev(rights)))

    if not spreads:
        return True
    # Every column must line up, not merely the average of them: in justified
    # prose the first "column" is the left margin and aligns perfectly, which
    # would drag a mean down far enough to accept the whole spurious grid.
    return max(spreads) <= MAX_COLUMN_EDGE_SPREAD


def _corridor_to_separator(
    start_bin: int, end_bin: int, step: float, content: BBox
) -> list[float]:
    """Convert an empty bin range into a separator, ignoring page margins."""
    x_start = content.x0 + start_bin * step
    x_end = content.x0 + (end_bin + 1) * step
    if x_end - x_start < MIN_GAP_WIDTH:
        return []
    # Corridors touching the content edges are margins, not separators.
    if x_start <= content.x0 + 0.5 or x_end >= content.x1 - 0.5:
        return []
    return [(x_start + x_end) / 2.0]


def whitespace_corridors(lines: list[TextLine], content: BBox) -> list[float]:
    """Confirmed vertical corridors, the only column evidence an unruled row has."""
    return [
        x
        for x in _column_edges_from_whitespace(lines, content)
        if content.x0 + MIN_BAND_SIZE < x < content.x1 - MIN_BAND_SIZE
    ]


def build_column_boundaries(
    page: PageContent,
    lines: list[TextLine],
    content: BBox,
    corridors: list[float] | None = None,
) -> list[float]:
    """The sheet's global column boundaries, left edge to right edge."""
    edges = _column_edges_from_rulings(page)
    interior = [x for x in edges if content.x0 + MIN_BAND_SIZE < x < content.x1 - MIN_BAND_SIZE]

    if not interior:
        interior = list(
            corridors if corridors is not None else whitespace_corridors(lines, content)
        )

    boundaries = _cluster_positions([content.x0, *interior, content.x1])
    return _prune_boundaries(boundaries)


# --- Row discovery ----------------------------------------------------------


def _band_is_real(
    top: float, bottom: float, verticals: list[Ruling], lines: list[TextLine]
) -> bool:
    """Does a gap between two horizontal rulings represent an actual table row?

    Two stacked tables produce a spurious band between them — bounded above by
    the first table's last line and below by the second's first.  A genuine row
    either holds text or is crossed by the table's vertical borders; the dead
    space between tables is neither.
    """
    if any(top <= line.bbox.cy < bottom for line in lines):
        return True
    return any(
        ruling.span[0] <= top + BOUNDARY_TOL and ruling.span[1] >= bottom - BOUNDARY_TOL
        for ruling in verticals
    )


def build_row_boundaries(page: PageContent, lines: list[TextLine], content: BBox) -> list[float]:
    """Rows from ruled bands, backfilled with visual text lines.

    Ruled bands win where they exist — they preserve empty rows that carry no
    text but do carry structure.  Text lines outside every band contribute a row
    of their own so nothing on the page is dropped.

    Vertical whitespace between bands is *absorbed* into the neighbouring rows
    rather than becoming an empty spacer row: the boundary sits at the midpoint
    of the gap.  That keeps the vertical proportions of the page without
    inventing rows that were never there, and for adjacent ruled bands (whose
    gap is zero) the midpoint is exactly the shared border.
    """
    horizontals = _significant_rulings(page.rulings, "h", page.width)
    verticals = _significant_rulings(page.rulings, "v", page.height)

    # A shaded rectangle's edges bound a row just as a drawn rule does, and on a
    # scan they may be the only evidence left: a dark fill hides the very line
    # that would otherwise delimit the row it shades.
    fill_edges: list[float] = []
    for rect in page.rects:
        if rect.fill_color and not is_near_white(rect.fill_color):
            fill_edges.extend((rect.bbox.top, rect.bbox.bottom))

    ruled_edges = _cluster_positions([r.position for r in horizontals] + fill_edges)
    ruled_edges = [
        y for y in ruled_edges if content.top - BOUNDARY_TOL <= y <= content.bottom + BOUNDARY_TOL
    ]

    # Each band records whether its edges came from a ruling, because a ruled
    # edge is a fact about the page and must survive as the row boundary.
    bands: list[_Band] = []
    for i in range(len(ruled_edges) - 1):
        top, bottom = ruled_edges[i], ruled_edges[i + 1]
        if bottom - top >= MIN_BAND_SIZE and _band_is_real(top, bottom, verticals, lines):
            bands.append(_Band(top=top, bottom=bottom, top_ruled=True, bottom_ruled=True))

    def covered(centre: float) -> bool:
        return any(band.top <= centre < band.bottom for band in bands)

    for line in lines:
        if not covered(line.bbox.cy):
            bands.append(_Band(top=line.bbox.top, bottom=line.bbox.bottom))

    # An image occupies vertical space just as text does; without a row of its
    # own it would be anchored into whichever neighbouring row it happened to
    # touch and the page would lose a band of its layout.
    for image in page.images:
        box = image.bbox
        if not covered(box.cy):
            bands.append(_Band(top=box.top, bottom=box.bottom))

    if not bands:
        return [content.top, content.bottom]

    bands.sort(key=lambda b: (b.top, b.bottom))
    merged: list[_Band] = [bands[0]]
    for band in bands[1:]:
        previous = merged[-1]
        if band.top < previous.bottom - BOUNDARY_TOL:
            # Overlapping bands (a text line straddling a ruling) become one row.
            merged[-1] = _Band(
                top=previous.top,
                bottom=max(previous.bottom, band.bottom),
                top_ruled=previous.top_ruled,
                bottom_ruled=band.bottom_ruled
                if band.bottom >= previous.bottom
                else previous.bottom_ruled,
            )
        else:
            merged.append(band)

    boundaries = [min(content.top, merged[0].top)]
    for index in range(len(merged) - 1):
        boundaries.append(_boundary_between(merged[index], merged[index + 1]))
    boundaries.append(max(content.bottom, merged[-1].bottom))

    return _prune_boundaries(boundaries)


def _boundary_between(upper: _Band, lower: _Band) -> float:
    """Where the row boundary falls between two consecutive bands.

    A ruled edge wins outright: the boundary must coincide with the line the
    producer drew, or the row's rectangle stops matching the cell's borders and
    its background fill, and both are then lost.  Only when neither side is ruled
    is the whitespace split down the middle, which keeps the page's vertical
    proportions without inventing a spacer row.
    """
    if lower.top_ruled:
        return lower.top
    if upper.bottom_ruled:
        return upper.bottom
    return (upper.bottom + lower.top) / 2.0


# --- Cell assembly ----------------------------------------------------------


def _band_indices(low: float, high: float, boundaries: list[float]) -> list[int]:
    """Indices of the bands a ``[low, high]`` interval meaningfully occupies."""
    hits: list[int] = []
    for i in range(len(boundaries) - 1):
        b_low, b_high = boundaries[i], boundaries[i + 1]
        overlap = min(high, b_high) - max(low, b_low)
        if overlap <= 0:
            continue
        reference = min(b_high - b_low, high - low) or 1.0
        if overlap >= max(0.75, CELL_OVERLAP_RATIO * reference):
            hits.append(i)

    if not hits:
        # Degenerate interval (zero-width run): fall back to its midpoint.
        hits = [_column_index_for((low + high) / 2.0, boundaries)]
    return hits


def _boundary_index(value: float, boundaries: list[float], tol: float = BOUNDARY_TOL * 1.5) -> int | None:
    """Index of the boundary coinciding with ``value``, if any."""
    best: int | None = None
    best_delta = tol
    for index, boundary in enumerate(boundaries):
        delta = abs(boundary - value)
        if delta <= best_delta:
            best, best_delta = index, delta
    return best


def _ruled_col_extent(
    box: BBox,
    band_top: float,
    band_bottom: float,
    col_bounds: list[float],
    verticals: list[Ruling],
) -> tuple[int, int] | None:
    """Columns enclosed by the vertical borders around ``box``.

    This is what makes merged cells work.  A header merged across four columns
    has no internal vertical rulings on its row, so the nearest borders on either
    side of its text are the outer edges of the whole span — regardless of how
    short the text is or whether it is centred.
    """
    band_mid = (band_top + band_bottom) / 2.0
    crossing = sorted(
        {
            ruling.position
            for ruling in verticals
            if ruling.span[0] <= band_mid + BOUNDARY_TOL
            and ruling.span[1] >= band_mid - BOUNDARY_TOL
        }
    )
    if len(crossing) < 2:
        return None

    left_candidates = [x for x in crossing if x <= box.x0 + BOUNDARY_TOL]
    right_candidates = [x for x in crossing if x >= box.x1 - BOUNDARY_TOL]
    if not left_candidates or not right_candidates:
        return None

    first = _boundary_index(max(left_candidates), col_bounds)
    last_edge = _boundary_index(min(right_candidates), col_bounds)
    if first is None or last_edge is None or last_edge <= first:
        return None

    # Boundary indices bracket the columns; the last column is one short.
    return first, min(last_edge - 1, len(col_bounds) - 2)


def _ruled_row_extent(
    box: BBox,
    col_left: float,
    col_right: float,
    row_bounds: list[float],
    horizontals: list[Ruling],
) -> tuple[int, int] | None:
    """Rows enclosed by the horizontal borders above and below ``box``."""
    col_mid = (col_left + col_right) / 2.0
    crossing = sorted(
        {
            ruling.position
            for ruling in horizontals
            if ruling.span[0] <= col_mid + BOUNDARY_TOL
            and ruling.span[1] >= col_mid - BOUNDARY_TOL
        }
    )
    if len(crossing) < 2:
        return None

    above = [y for y in crossing if y <= box.top + BOUNDARY_TOL]
    below = [y for y in crossing if y >= box.bottom - BOUNDARY_TOL]
    if not above or not below:
        return None

    first = _boundary_index(max(above), row_bounds)
    last_edge = _boundary_index(min(below), row_bounds)
    if first is None or last_edge is None or last_edge <= first:
        return None

    return first, min(last_edge - 1, len(row_bounds) - 2)


def _dominant_style_words(run: TextRun) -> Word:
    """The word whose typography represents the run.

    The longest word wins, so a stray superscript cannot dictate the cell's font.
    """
    return max(run.words, key=lambda w: (len(w.text), w.bbox.width))


def build_sheet_grid(page: PageContent, title: str | None = None) -> SheetGrid:
    """Map one extracted page onto a worksheet grid."""
    lines = group_words_into_lines(page.words)
    sheet_title = title or f"Page {page.page_number}"

    if not lines and not page.images:
        return SheetGrid(
            page_number=page.page_number,
            title=sheet_title,
            kind=page.kind.value,
            n_rows=0,
            n_cols=0,
            page_width_pt=page.width,
            page_height_pt=page.height,
        )

    content = _content_bbox(page, lines)
    corridors = whitespace_corridors(lines, content)
    col_bounds = build_column_boundaries(page, lines, content, corridors)
    row_bounds = build_row_boundaries(page, lines, content)

    n_cols = max(0, len(col_bounds) - 1)
    n_rows = max(0, len(row_bounds) - 1)

    verticals = _significant_rulings(page.rulings, "v", page.height)
    horizontals = _significant_rulings(page.rulings, "h", page.width)

    cells: list[GridCell] = []
    occupied: dict[tuple[int, int], GridCell] = {}

    for line in lines:
        row_hits = _band_indices(line.bbox.top, line.bbox.bottom, row_bounds)
        text_row = row_hits[0]
        text_row_span = len(row_hits)

        band_top = row_bounds[text_row]
        band_bottom = row_bounds[min(text_row + text_row_span, len(row_bounds) - 1)]

        runs = _split_line_for_row(line, band_top, band_bottom, corridors, verticals)

        for run in runs:
            if not run.text:
                continue
            box = run.bbox

            ruled_cols = _ruled_col_extent(box, band_top, band_bottom, col_bounds, verticals)
            if ruled_cols is not None:
                col, last_col = ruled_cols
            else:
                col_hits = _band_indices(box.x0, box.x1, col_bounds)
                col, last_col = col_hits[0], col_hits[-1]
            col_span = last_col - col + 1

            row, row_span = text_row, text_row_span
            ruled_rows = _ruled_row_extent(
                box, col_bounds[col], col_bounds[last_col + 1], row_bounds, horizontals
            )
            if ruled_rows is not None:
                row, last_row = ruled_rows
                row_span = last_row - row + 1

            key = (row, col)
            if key in occupied:
                # Two runs landed in one cell (e.g. a wrapped label); join them
                # in reading order rather than dropping either.
                existing = occupied[key]
                existing.text = f"{existing.text} {run.text}".strip()
                existing.bbox = existing.bbox.merged(box) if existing.bbox else box
                existing.col_span = max(existing.col_span, col_span)
                continue

            style_word = _dominant_style_words(run)
            cell = GridCell(
                row=row,
                col=col,
                row_span=row_span,
                col_span=col_span,
                text=run.text,
                bbox=box,
                source=style_word.source,
                confidence=min(w.confidence for w in run.words),
            )
            cell.style.font_name = style_word.font_name or "Calibri"
            cell.style.font_size = style_word.font_size or 11.0
            cell.style.bold = style_word.bold
            cell.style.italic = style_word.italic
            cell.style.font_color = style_word.color

            occupied[key] = cell
            cells.append(cell)

    _resolve_span_collisions(cells)

    grid = SheetGrid(
        page_number=page.page_number,
        title=sheet_title,
        kind=page.kind.value,
        n_rows=n_rows,
        n_cols=n_cols,
        cells=cells,
        images=anchor_images(page.images, col_bounds, row_bounds),
        col_widths_pt=[col_bounds[i + 1] - col_bounds[i] for i in range(n_cols)],
        row_heights_pt=[row_bounds[i + 1] - row_bounds[i] for i in range(n_rows)],
        page_width_pt=page.width,
        page_height_pt=page.height,
    )

    apply_styles(grid, page, col_bounds, row_bounds)

    logger.info(
        "built sheet grid",
        extra={
            "page": page.page_number,
            "rows": n_rows,
            "cols": n_cols,
            "cells": len(grid.cells),
            "ruled": bool(_column_edges_from_rulings(page)),
        },
    )
    return grid


def _content_bbox(page: PageContent, lines: list[TextLine]) -> BBox:
    """Bounding box of everything that must appear in the sheet.

    The grid is anchored to the content, not the paper, so a 72 pt page margin
    does not become an empty column A.
    """
    boxes: list[BBox] = [line.bbox for line in lines]
    boxes.extend(image.bbox for image in page.images)

    # Ruled table borders often sit slightly outside the text they enclose.
    page_area = page.bbox
    for ruling in page.rulings:
        if ruling.length < min(page.width, page.height) * MIN_RULING_PAGE_FRACTION:
            continue
        low, high = ruling.span
        if ruling.orientation == "h":
            boxes.append(BBox(x0=low, top=ruling.position, x1=high, bottom=ruling.position))
        else:
            boxes.append(BBox(x0=ruling.position, top=low, x1=ruling.position, bottom=high))

    if not boxes:
        return page_area

    union = BBox.union(boxes)
    return BBox(
        x0=max(page_area.x0, union.x0),
        top=max(page_area.top, union.top),
        x1=min(page_area.x1, union.x1),
        bottom=min(page_area.bottom, union.bottom),
    )


def _resolve_span_collisions(cells: list[GridCell]) -> None:
    """Shrink spans that would overlap another cell's anchor.

    openpyxl raises if two merged ranges intersect, and a span that swallows a
    neighbouring value would lose data outright, so the span always yields.
    """
    anchors = {(c.row, c.col) for c in cells}

    for cell in cells:
        max_col_span = cell.col_span
        for offset in range(1, cell.col_span):
            if (cell.row, cell.col + offset) in anchors:
                max_col_span = offset
                break
        cell.col_span = max(1, max_col_span)

        max_row_span = cell.row_span
        for offset in range(1, cell.row_span):
            if any((cell.row + offset, cell.col + c) in anchors for c in range(cell.col_span)):
                max_row_span = offset
                break
        cell.row_span = max(1, max_row_span)
