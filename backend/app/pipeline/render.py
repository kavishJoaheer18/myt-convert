"""Rasterise PDF pages.

Used by the OCR path to get pixels to read, by the review UI to show the source
page, and by Phase 4's visual diff.  All of them want the same thing: an RGB
numpy array at a known DPI, with a recorded scale so coordinates can be mapped
back to page points.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import fitz
import numpy as np

from app.models.geometry import POINTS_PER_INCH

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageRender:
    """A rasterised page and the scale that produced it."""

    image: np.ndarray
    dpi: int
    page_number: int
    #: Page dimensions in points, for mapping pixels back to PDF space.
    width_pt: float
    height_pt: float

    @property
    def scale(self) -> float:
        return self.dpi / POINTS_PER_INCH

    def px_to_pt(self, pixels: float) -> float:
        return pixels / self.scale

    def pt_to_px(self, points: float) -> float:
        return points * self.scale


def render_page(page: fitz.Page, dpi: int = 300) -> PageRender:
    """Rasterise one open page to an RGB array."""
    pixmap = page.get_pixmap(dpi=dpi, alpha=False, colorspace=fitz.csRGB)
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, 3
    )
    # frombuffer gives a read-only view onto PyMuPDF's buffer; callers filter and
    # rotate in place, so hand them their own array.
    return PageRender(
        image=np.array(image),
        dpi=dpi,
        page_number=page.number + 1,
        width_pt=float(page.rect.width),
        height_pt=float(page.rect.height),
    )


def render_document(pdf_path: Path, dpi: int = 300) -> list[PageRender]:
    with fitz.open(pdf_path) as doc:
        return [render_page(page, dpi=dpi) for page in doc]


def save_render(render: PageRender, path: Path) -> Path:
    """Write a render to disk as PNG, for the review UI and verification."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(render.image).save(path, format="PNG")
    logger.info("saved page render", extra={"page": render.page_number, "path": str(path)})
    return path
