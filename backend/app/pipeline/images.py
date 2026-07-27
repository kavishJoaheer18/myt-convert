"""Anchor extracted page images to grid cells.

An image must land in the cell its top-left corner occupies and keep the size it
had on the page — not its native raster size.  A 2000 px logo drawn into a 50 pt
box has to come out 50 pt wide, or the workbook looks nothing like the PDF.
"""

from __future__ import annotations

import logging

from app.models.content import ImageBlock
from app.models.geometry import PIXELS_PER_INCH, POINTS_PER_INCH
from app.models.grid import AnchoredImage

logger = logging.getLogger(__name__)

#: Images smaller than this on the page are separators or spacer GIFs.
_MIN_DISPLAY_PT = 2.0


def points_to_display_pixels(points: float) -> int:
    """Convert an on-page size in points to the 96 DPI pixels Excel draws with."""
    return max(1, int(round(points * (PIXELS_PER_INCH / POINTS_PER_INCH))))


def _band_index(value: float, boundaries: list[float]) -> int:
    for i in range(len(boundaries) - 1):
        if boundaries[i] <= value < boundaries[i + 1]:
            return i
    return max(0, len(boundaries) - 2)


def anchor_images(
    images: list[ImageBlock],
    col_bounds: list[float],
    row_bounds: list[float],
) -> list[AnchoredImage]:
    """Place each image in the cell containing its top-left corner."""
    if len(col_bounds) < 2 or len(row_bounds) < 2:
        return []

    anchored: list[AnchoredImage] = []
    for image in images:
        box = image.bbox
        if box.width < _MIN_DISPLAY_PT or box.height < _MIN_DISPLAY_PT:
            logger.debug("skipping sub-visible image", extra={"path": image.path})
            continue

        col = _band_index(box.x0, col_bounds)
        row = _band_index(box.top, row_bounds)

        anchored.append(
            AnchoredImage(
                path=image.path,
                row=row,
                col=col,
                width_px=points_to_display_pixels(box.width),
                height_px=points_to_display_pixels(box.height),
                offset_x_pt=max(0.0, box.x0 - col_bounds[col]),
                offset_y_pt=max(0.0, box.top - row_bounds[row]),
            )
        )

    logger.info("anchored images", extra={"count": len(anchored)})
    return anchored
