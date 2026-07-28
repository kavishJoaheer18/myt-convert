"""Recover table rulings from a scanned page.

A digital PDF hands over its table borders as vector operators.  A scan has only
pixels, so the equivalent evidence must be rebuilt: morphological opening with a
long, one-pixel-thin kernel keeps runs of ink that continue for far longer than
any glyph stroke, which is exactly what a rule is and what a letter is not.

The output is the same :class:`Ruling` type the digital extractor produces, in
page points — so the grid mapper cannot tell which path a page arrived by.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from app.models.content import RectDrawing, Ruling
from app.models.geometry import BBox, POINTS_PER_INCH
from app.pipeline.colors import is_near_white

logger = logging.getLogger(__name__)

#: A rule must run at least this fraction of the page to count.
MIN_LENGTH_PAGE_FRACTION = 0.06
#: ...and must be no thicker than this, in points, or it is a filled block.
MAX_THICKNESS_PT = 4.0
#: Long, thin and mostly-solid: a dashed border still passes, a word does not.
MIN_FILL_RATIO = 0.55


def _open_with_kernel(binary: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    eroded = cv2.erode(binary, kernel, iterations=1)
    return cv2.dilate(eroded, kernel, iterations=1)


def _components(image: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    """``(x, y, w, h, area)`` for every connected component except the background."""
    count, _, stats, _ = cv2.connectedComponentsWithStats(image, connectivity=8)
    return [
        (
            int(stats[i, cv2.CC_STAT_LEFT]),
            int(stats[i, cv2.CC_STAT_TOP]),
            int(stats[i, cv2.CC_STAT_WIDTH]),
            int(stats[i, cv2.CC_STAT_HEIGHT]),
            int(stats[i, cv2.CC_STAT_AREA]),
        )
        for i in range(1, count)
    ]


def detect_rulings(binary: np.ndarray, dpi: int) -> list[Ruling]:
    """Find horizontal and vertical rules in a white-on-black binary page."""
    height, width = binary.shape[:2]
    px_to_pt = POINTS_PER_INCH / dpi

    min_h_px = max(20, int(width * MIN_LENGTH_PAGE_FRACTION))
    min_v_px = max(20, int(height * MIN_LENGTH_PAGE_FRACTION))
    max_thickness_px = max(2, int(MAX_THICKNESS_PT / px_to_pt))

    rulings: list[Ruling] = []

    # --- horizontal ---
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (min_h_px, 1))
    horizontal = _open_with_kernel(binary, kernel)
    for x, y, w, h, area in _components(horizontal):
        if w < min_h_px or h > max_thickness_px:
            continue
        if area < w * h * MIN_FILL_RATIO:
            continue
        centre = (y + h / 2.0) * px_to_pt
        rulings.append(
            Ruling(
                orientation="h",
                x0=x * px_to_pt,
                y0=centre,
                x1=(x + w) * px_to_pt,
                y1=centre,
                stroke_width=max(h * px_to_pt, 0.5),
            )
        )

    # --- vertical ---
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_v_px))
    vertical = _open_with_kernel(binary, kernel)
    for x, y, w, h, area in _components(vertical):
        if h < min_v_px or w > max_thickness_px:
            continue
        if area < w * h * MIN_FILL_RATIO:
            continue
        centre = (x + w / 2.0) * px_to_pt
        rulings.append(
            Ruling(
                orientation="v",
                x0=centre,
                y0=y * px_to_pt,
                x1=centre,
                y1=(y + h) * px_to_pt,
                stroke_width=max(w * px_to_pt, 0.5),
            )
        )

    logger.info(
        "detected rulings in raster",
        extra={
            "horizontal": sum(1 for r in rulings if r.orientation == "h"),
            "vertical": sum(1 for r in rulings if r.orientation == "v"),
        },
    )
    return rulings


def erase_rulings(binary: np.ndarray, rulings: list[Ruling], dpi: int) -> np.ndarray:
    """Blank out the detected rules, leaving glyphs and pictures behind.

    Erasing by *detected ruling* rather than by morphological opening matters:
    an opening with a long kernel also swallows any solid block wider than the
    kernel, so a logo would be erased along with the borders.
    """
    px_per_pt = dpi / POINTS_PER_INCH
    result = binary.copy()
    height, width = result.shape[:2]

    for ruling in rulings:
        thickness_px = max(2, int(round(ruling.stroke_width * px_per_pt)))
        pad = thickness_px // 2 + 2
        low, high = ruling.span
        centre_px = int(round(ruling.position * px_per_pt))

        if ruling.orientation == "h":
            y0 = max(0, centre_px - pad)
            y1 = min(height, centre_px + pad + 1)
            x0 = max(0, int(low * px_per_pt))
            x1 = min(width, int(high * px_per_pt) + 1)
        else:
            x0 = max(0, centre_px - pad)
            x1 = min(width, centre_px + pad + 1)
            y0 = max(0, int(low * px_per_pt))
            y1 = min(height, int(high * px_per_pt) + 1)

        result[y0:y1, x0:x1] = 0

    return result


def detect_figures(
    binary: np.ndarray,
    dpi: int,
    text_boxes_px: list[tuple[float, float, float, float]],
    rulings: list[Ruling] | None = None,
    min_size_pt: float = 18.0,
    min_fill_ratio: float = 0.25,
) -> list[tuple[int, int, int, int]]:
    """Find picture regions: ink that is neither a rule nor recognised text.

    A scanned page carries its logos and charts as ink like everything else.  If
    they are ignored, the workbook loses them *and* loses the vertical space they
    occupied, which shifts every row beneath them.  What remains after erasing
    the rules and everything OCR could read is, by elimination, a picture.

    Returns bounding boxes in pixels.
    """
    mask = erase_rulings(binary, rulings or [], dpi)

    for x0, top, x1, bottom in text_boxes_px:
        # Pad generously: a detection box hugs the glyphs, and their antialiased
        # fringes would otherwise survive as speckle.
        pad = 4
        y_start = max(0, int(top) - pad)
        y_end = min(mask.shape[0], int(bottom) + pad)
        x_start = max(0, int(x0) - pad)
        x_end = min(mask.shape[1], int(x1) + pad)
        mask[y_start:y_end, x_start:x_end] = 0

    # Close small gaps so a dithered or hatched figure reads as one region.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    min_px = max(8, int(min_size_pt * dpi / POINTS_PER_INCH))
    figures: list[tuple[int, int, int, int]] = []

    def holds_text(x: int, y: int, w: int, h: int) -> bool:
        """True when recognised text sits within this region."""
        return any(
            x <= (bx0 + bx1) / 2.0 <= x + w and y <= (btop + bbottom) / 2.0 <= y + h
            for bx0, btop, bx1, bbottom in text_boxes_px
        )

    for x, y, w, h, area in _components(mask):
        if w < min_px or h < min_px:
            continue
        if area < w * h * min_fill_ratio:
            continue
        # Ink with words on top of it is a shaded region, not a picture — a
        # filled header row would otherwise be cropped out as an image.
        if holds_text(x, y, w, h):
            continue
        figures.append((x, y, w, h))

    logger.info("detected figures in raster", extra={"count": len(figures)})
    return figures


def detect_filled_blocks(
    binary: np.ndarray,
    dpi: int,
    min_width_pt: float = 30.0,
    min_height_pt: float = 8.0,
    max_height_pt: float = 60.0,
    min_fill_ratio: float = 0.55,
) -> list[tuple[int, int, int, int]]:
    """Find solid shaded bands — a filled header row and the like.

    These matter because a dark fill hides the very rules that would otherwise
    bound the cell: a black line on a navy background has no contrast, and
    morphology sees one thick block rather than a rule. Without detecting the
    block itself, a shaded header's colour is unrecoverable.
    """
    px_per_pt = dpi / POINTS_PER_INCH
    min_w = int(min_width_pt * px_per_pt)
    min_h = int(min_height_pt * px_per_pt)
    max_h = int(max_height_pt * px_per_pt)

    blocks: list[tuple[int, int, int, int]] = []
    for x, y, w, h, area in _components(binary):
        if w < min_w or not (min_h <= h <= max_h):
            continue
        # Solid, allowing for the holes that reversed-out glyphs punch in it.
        if area < w * h * min_fill_ratio:
            continue
        blocks.append((x, y, w, h))

    return blocks


def _sample_median_hex(color: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> str | None:
    """Per-channel median colour of a region, or ``None`` if it is degenerate.

    A median reports the background even with glyphs sitting on top of it, since
    the text is a minority of the pixels.
    """
    if y1 - y0 < 2 or x1 - x0 < 2:
        return None
    patch = color[y0:y1, x0:x1].reshape(-1, color.shape[2])
    median = np.median(patch, axis=0)
    return f"{int(median[0]):02X}{int(median[1]):02X}{int(median[2]):02X}"


def sample_cell_fills(
    color: np.ndarray,
    rulings: list[Ruling],
    dpi: int,
    exclude_px: list[tuple[int, int, int, int]] | None = None,
    inset_pt: float = 1.5,
) -> list[RectDrawing]:
    """Recover cell background colours from a scanned page.

    A digital PDF states its fills as drawing operators; a scan only shows them.
    Two sources are combined: every rectangle of the ruling grid, and any solid
    shaded band whose own borders the shading has hidden. Near-white results are
    discarded, because an unshaded cell has no fill to reproduce.

    ``exclude_px`` lists regions already claimed as pictures, which must not be
    turned into a background colour as well.
    """
    px_per_pt = dpi / POINTS_PER_INCH
    height, width = color.shape[:2]
    inset_px = max(1, int(round(inset_pt * px_per_pt)))
    excluded = exclude_px or []
    fills: list[RectDrawing] = []

    def overlaps_excluded(x0: int, y0: int, x1: int, y1: int) -> bool:
        for ex, ey, ew, eh in excluded:
            if x0 < ex + ew and x1 > ex and y0 < ey + eh and y1 > ey:
                return True
        return False

    # --- rectangles of the ruling grid ---
    horizontals = sorted({r.position for r in rulings if r.orientation == "h"})
    verticals = sorted({r.position for r in rulings if r.orientation == "v"})

    if len(horizontals) >= 2 and len(verticals) >= 2:
        for row in range(len(horizontals) - 1):
            for col in range(len(verticals) - 1):
                top_pt, bottom_pt = horizontals[row], horizontals[row + 1]
                left_pt, right_pt = verticals[col], verticals[col + 1]

                y0 = max(0, int(top_pt * px_per_pt) + inset_px)
                y1 = min(height, int(bottom_pt * px_per_pt) - inset_px)
                x0 = max(0, int(left_pt * px_per_pt) + inset_px)
                x1 = min(width, int(right_pt * px_per_pt) - inset_px)
                if overlaps_excluded(x0, y0, x1, y1):
                    continue

                hex_color = _sample_median_hex(color, x0, y0, x1, y1)
                if hex_color is None or is_near_white(hex_color):
                    continue
                fills.append(
                    RectDrawing(
                        bbox=BBox(x0=left_pt, top=top_pt, x1=right_pt, bottom=bottom_pt),
                        fill_color=hex_color,
                    )
                )

    # --- solid shaded bands ---
    # The rules must go first: they connect a shaded row to the rest of the
    # table grid, so the component would otherwise be the whole table.
    block_mask = erase_rulings(_ink_mask(color), rulings, dpi)
    for x, y, w, h in detect_filled_blocks(block_mask, dpi):
        if overlaps_excluded(x, y, x + w, y + h):
            continue
        hex_color = _sample_median_hex(
            color, x + inset_px, y + inset_px, x + w - inset_px, y + h - inset_px
        )
        if hex_color is None or is_near_white(hex_color):
            continue
        fills.append(
            RectDrawing(
                bbox=BBox(
                    x0=x / px_per_pt,
                    top=y / px_per_pt,
                    x1=(x + w) / px_per_pt,
                    bottom=(y + h) / px_per_pt,
                ),
                fill_color=hex_color,
            )
        )

    logger.info("sampled cell fills", extra={"count": len(fills)})
    return fills


def _ink_mask(color: np.ndarray) -> np.ndarray:
    """Everything that is not paper, as a binary mask.

    Deliberately not the preprocessed binary: that one is tuned to isolate
    glyph strokes, whereas a shaded band has to be seen as the one solid region
    it is.
    """
    gray = cv2.cvtColor(color, cv2.COLOR_RGB2GRAY) if color.ndim == 3 else color
    return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]


def text_mask(binary: np.ndarray, rulings_removed: bool = True) -> np.ndarray:
    """The binary page with long rules erased, leaving glyphs behind.

    Useful for skew estimation and for OCR engines that stumble on ruled cells.
    """
    if not rulings_removed:
        return binary

    height, width = binary.shape[:2]
    result = binary.copy()

    for kernel_size in (
        (max(20, width // 16), 1),
        (1, max(20, height // 16)),
    ):
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_size)
        lines = _open_with_kernel(binary, kernel)
        result = cv2.subtract(result, lines)

    return result
