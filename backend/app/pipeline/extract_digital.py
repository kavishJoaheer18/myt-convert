"""Extraction for pages that carry a real text layer.

Two libraries are used because each is best at one job: pdfplumber gives clean
word segmentation with per-word font attributes, while PyMuPDF exposes the vector
drawing operators that reveal a table's ruling lines.  Both report coordinates
with a top-left origin, so their output composes without conversion.
"""

from __future__ import annotations

import logging
from pathlib import Path

import fitz
import pdfplumber

from app.models.content import ImageBlock, PageContent, PageKind, RectDrawing, Ruling, Word
from app.models.geometry import BBox
from app.pipeline.colors import normalize_color
from app.pipeline.fonts import parse_font

logger = logging.getLogger(__name__)

#: Maximum deviation (pt) for a segment to count as axis-aligned.
_STRAIGHTNESS_TOL = 0.6
#: A rectangle thinner than this in either axis is really a drawn line.
_LINE_THICKNESS_MAX = 2.5
#: Segments shorter than this are decoration (bullet ticks, underscores).
_MIN_RULING_LENGTH = 3.0

_WORD_ATTRS = ["fontname", "size", "non_stroking_color"]


def _make_ruling(
    x0: float, y0: float, x1: float, y1: float, width: float, color: str
) -> Ruling | None:
    """Build a Ruling if the segment is axis-aligned and long enough."""
    dx, dy = abs(x1 - x0), abs(y1 - y0)

    if dy <= _STRAIGHTNESS_TOL and dx >= _MIN_RULING_LENGTH:
        y = (y0 + y1) / 2.0
        return Ruling(
            orientation="h", x0=min(x0, x1), y0=y, x1=max(x0, x1), y1=y,
            stroke_width=width, color=color,
        )
    if dx <= _STRAIGHTNESS_TOL and dy >= _MIN_RULING_LENGTH:
        x = (x0 + x1) / 2.0
        return Ruling(
            orientation="v", x0=x, y0=min(y0, y1), x1=x, y1=max(y0, y1),
            stroke_width=width, color=color,
        )
    return None


def _rect_edges(rect: fitz.Rect, width: float, color: str) -> list[Ruling]:
    """The four edges of a stroked rectangle, as ruling segments."""
    x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
    candidates = [
        _make_ruling(x0, y0, x1, y0, width, color),  # top
        _make_ruling(x0, y1, x1, y1, width, color),  # bottom
        _make_ruling(x0, y0, x0, y1, width, color),  # left
        _make_ruling(x1, y0, x1, y1, width, color),  # right
    ]
    return [r for r in candidates if r is not None]


def _extract_drawings(page: fitz.Page) -> tuple[list[Ruling], list[RectDrawing]]:
    """Split vector drawings into ruling lines and filled/stroked rectangles."""
    rulings: list[Ruling] = []
    rects: list[RectDrawing] = []

    for drawing in page.get_drawings():
        dtype = drawing.get("type", "s")
        stroke_hex = normalize_color(drawing.get("color"), default=None)
        fill_hex = normalize_color(drawing.get("fill"), default=None)
        stroke_w = float(drawing.get("width") or 0.0)
        # A hairline still paints one device pixel; treat 0 as the thinnest line.
        effective_w = stroke_w if stroke_w > 0 else 0.5

        for item in drawing.get("items", []):
            op = item[0]

            if op == "l":
                p0, p1 = item[1], item[2]
                ruling = _make_ruling(
                    p0.x, p0.y, p1.x, p1.y, effective_w, stroke_hex or "000000"
                )
                if ruling is not None:
                    rulings.append(ruling)

            elif op == "re":
                rect = fitz.Rect(item[1])
                if rect.is_empty:
                    continue
                thin = rect.width <= _LINE_THICKNESS_MAX or rect.height <= _LINE_THICKNESS_MAX
                if thin:
                    # A filled sliver is how many producers draw a rule.
                    line_color = fill_hex or stroke_hex or "000000"
                    thickness = min(rect.width, rect.height) or effective_w
                    if rect.width >= rect.height:
                        ruling = _make_ruling(
                            rect.x0, rect.y0 + rect.height / 2.0,
                            rect.x1, rect.y0 + rect.height / 2.0,
                            thickness, line_color,
                        )
                    else:
                        ruling = _make_ruling(
                            rect.x0 + rect.width / 2.0, rect.y0,
                            rect.x0 + rect.width / 2.0, rect.y1,
                            thickness, line_color,
                        )
                    if ruling is not None:
                        rulings.append(ruling)
                    continue

                rects.append(
                    RectDrawing(
                        bbox=BBox(x0=rect.x0, top=rect.y0, x1=rect.x1, bottom=rect.y1),
                        fill_color=fill_hex if dtype in ("f", "fs") else None,
                        stroke_color=stroke_hex if dtype in ("s", "fs") else None,
                        stroke_width=stroke_w,
                    )
                )
                if dtype in ("s", "fs"):
                    # Border rectangles double as the table's ruling grid.
                    rulings.extend(_rect_edges(rect, effective_w, stroke_hex or "000000"))

            # Bezier ("c") and quad ("qu") items carry no grid information.

    return rulings, rects


def merge_collinear_rulings(rulings: list[Ruling], tol: float = 1.0) -> list[Ruling]:
    """Join collinear segments that touch into single rulings.

    Table grids are usually stroked cell by cell, so a table's left border
    arrives as one short segment per row.  Downstream stages judge a ruling by
    its length — to tell a table border from a bullet tick, or to find which
    columns a merged cell spans — so those fragments have to be reassembled
    before anything reasons about them.
    """
    if not rulings:
        return []

    merged: list[Ruling] = []
    for orientation in ("h", "v"):
        group = [r for r in rulings if r.orientation == orientation]
        if not group:
            continue

        by_position: dict[int, list[Ruling]] = {}
        for ruling in group:
            # Bucket by quantised position so near-identical lines meet.
            by_position.setdefault(int(round(ruling.position / max(tol, 0.01))), []).append(ruling)

        for bucket in by_position.values():
            bucket.sort(key=lambda r: r.span[0])
            position = sum(r.position for r in bucket) / len(bucket)
            start, end = bucket[0].span
            width = bucket[0].stroke_width
            color = bucket[0].color

            for ruling in bucket[1:]:
                low, high = ruling.span
                if low <= end + tol:
                    end = max(end, high)
                    width = max(width, ruling.stroke_width)
                else:
                    merged.append(_ruling_from_span(orientation, position, start, end, width, color))
                    start, end = low, high
                    width, color = ruling.stroke_width, ruling.color

            merged.append(_ruling_from_span(orientation, position, start, end, width, color))

    return merged


def _ruling_from_span(
    orientation: str, position: float, start: float, end: float, width: float, color: str
) -> Ruling:
    if orientation == "h":
        return Ruling(
            orientation="h", x0=start, y0=position, x1=end, y1=position,
            stroke_width=width, color=color,
        )
    return Ruling(
        orientation="v", x0=position, y0=start, x1=position, y1=end,
        stroke_width=width, color=color,
    )


def _extract_images(
    doc: fitz.Document, page: fitz.Page, out_dir: Path, page_number: int
) -> list[ImageBlock]:
    """Save every embedded raster to ``out_dir`` and record its placement."""
    blocks: list[ImageBlock] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[int, tuple[int, int, int, int]]] = set()

    for index, info in enumerate(page.get_image_info(xrefs=True)):
        xref = int(info.get("xref", 0) or 0)
        rect = fitz.Rect(info["bbox"]) & page.rect
        if rect.is_empty or rect.width < 1 or rect.height < 1:
            continue

        # The same logo placed twice reports twice; key on position as well.
        key = (xref, tuple(int(v) for v in (rect.x0, rect.y0, rect.x1, rect.y1)))
        if key in seen:
            continue
        seen.add(key)

        if xref <= 0:
            continue
        try:
            raw = doc.extract_image(xref)
        except (ValueError, RuntimeError) as exc:
            logger.warning(
                "image extraction failed", extra={"xref": xref, "page": page_number, "error": str(exc)}
            )
            continue

        ext = raw.get("ext", "png")
        filename = f"p{page_number}_img{index}_{xref}.{ext}"
        path = out_dir / filename
        path.write_bytes(raw["image"])

        blocks.append(
            ImageBlock(
                bbox=BBox(x0=rect.x0, top=rect.y0, x1=rect.x1, bottom=rect.y1),
                path=str(path),
                width_px=int(raw.get("width", 0) or rect.width),
                height_px=int(raw.get("height", 0) or rect.height),
                xref=xref,
            )
        )

    return blocks


def _extract_words(plumber_page: pdfplumber.page.Page) -> list[Word]:
    """Word tokens with the typography pdfplumber recovered for each."""
    words: list[Word] = []

    # extra_attrs makes pdfplumber split a run wherever font, size or colour
    # changes, so each emitted word has exactly one consistent style.
    for raw in plumber_page.extract_words(
        keep_blank_chars=False,
        use_text_flow=False,
        extra_attrs=_WORD_ATTRS,
    ):
        text = raw.get("text", "")
        if not text.strip():
            continue

        font_raw = str(raw.get("fontname") or "")
        family, bold, italic = parse_font(font_raw)
        color = normalize_color(raw.get("non_stroking_color"), default="000000") or "000000"

        words.append(
            Word(
                text=text,
                bbox=BBox(
                    x0=float(raw["x0"]),
                    top=float(raw["top"]),
                    x1=float(raw["x1"]),
                    bottom=float(raw["bottom"]),
                ),
                font_name=family,
                font_size=round(float(raw.get("size") or 0.0), 2),
                bold=bold,
                italic=italic,
                color=color,
            )
        )

    return words


def extract_page(
    doc: fitz.Document,
    plumber_pdf: pdfplumber.PDF,
    page_index: int,
    kind: PageKind,
    image_dir: Path,
) -> PageContent:
    """Extract one page's text, vectors and images into a :class:`PageContent`."""
    fitz_page = doc[page_index]
    plumber_page = plumber_pdf.pages[page_index]
    page_number = page_index + 1

    words = _extract_words(plumber_page)
    raw_rulings, rects = _extract_drawings(fitz_page)
    rulings = merge_collinear_rulings(raw_rulings)
    images = _extract_images(doc, fitz_page, image_dir, page_number)

    logger.info(
        "extracted digital page",
        extra={
            "page": page_number,
            "words": len(words),
            "rulings": len(rulings),
            "rects": len(rects),
            "images": len(images),
        },
    )

    return PageContent(
        page_number=page_number,
        width=float(fitz_page.rect.width),
        height=float(fitz_page.rect.height),
        kind=kind,
        rotation=int(fitz_page.rotation),
        words=words,
        rulings=rulings,
        rects=rects,
        images=images,
    )


def extract_document(
    pdf_path: Path, image_dir: Path, kinds: list[PageKind] | None = None
) -> list[PageContent]:
    """Extract every page of a digital PDF."""
    pages: list[PageContent] = []
    with fitz.open(pdf_path) as doc, pdfplumber.open(pdf_path) as plumber_pdf:
        for index in range(len(doc)):
            kind = kinds[index] if kinds and index < len(kinds) else PageKind.DIGITAL
            pages.append(extract_page(doc, plumber_pdf, index, kind, image_dir))
    return pages
