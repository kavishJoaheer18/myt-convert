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

from app.models.content import Ruling
from app.models.geometry import POINTS_PER_INCH

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

    for x, y, w, h, area in _components(mask):
        if w < min_px or h < min_px:
            continue
        if area < w * h * min_fill_ratio:
            continue
        figures.append((x, y, w, h))

    logger.info("detected figures in raster", extra={"count": len(figures)})
    return figures


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
