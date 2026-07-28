"""Visual verification: does the workbook actually look like the page?

The workbook is rendered back to PDF with LibreOffice and compared to the source
page with SSIM.  This is a structural smoke check, not a pixel match — a
spreadsheet lays out its own margins, substitutes fonts and paginates on its own
terms, so even a perfect conversion scores well short of 1.0.

What it catches is the class of failure no cell-level check can see: a blank
sheet, a collapsed column grid, content driven off the page.  The score is
recorded per page so a regression shows up as a drop rather than as an absolute
number anyone has to interpret.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.pipeline.render import render_document
from app.pipeline.render_xlsx import render_to_pdf

logger = logging.getLogger(__name__)

#: Comparison resolution. Low on purpose: the check is about layout, and fine
#: detail only adds noise from font substitution.
COMPARE_DPI = 100
#: Below this, the render and the source have structurally diverged.
DEFAULT_THRESHOLD = 0.50


@dataclass
class PageSimilarity:
    page_number: int
    ssim: float
    threshold: float

    @property
    def passed(self) -> bool:
        return self.ssim >= self.threshold


@dataclass
class VerificationResult:
    pages: list[PageSimilarity] = field(default_factory=list)
    rendered_pdf: Path | None = None
    #: Set when LibreOffice is unavailable, so callers can tell "not run" from
    #: "ran and failed".
    skipped_reason: str | None = None

    @property
    def ran(self) -> bool:
        return self.skipped_reason is None

    @property
    def mean_ssim(self) -> float:
        return float(np.mean([p.ssim for p in self.pages])) if self.pages else 0.0

    @property
    def passed(self) -> bool:
        return self.ran and bool(self.pages) and all(p.passed for p in self.pages)

    @property
    def failures(self) -> list[PageSimilarity]:
        return [p for p in self.pages if not p.passed]


def _to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    # Rec. 601 luma, matching what OpenCV's RGB2GRAY produces.
    return (
        0.299 * image[:, :, 0] + 0.587 * image[:, :, 1] + 0.114 * image[:, :, 2]
    ).astype(np.uint8)


def _match_shape(image: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Resize to ``shape`` (height, width) using Pillow, which needs no OpenCV."""
    from PIL import Image

    if image.shape[:2] == shape:
        return image
    resized = Image.fromarray(image).resize((shape[1], shape[0]), Image.BILINEAR)
    return np.asarray(resized)


def compare_images(source: np.ndarray, rendered: np.ndarray) -> float:
    """SSIM between two page images, after matching their sizes."""
    from skimage.metrics import structural_similarity

    source_gray = _to_gray(source)
    rendered_gray = _match_shape(_to_gray(rendered), source_gray.shape[:2])

    # SSIM's window must fit inside the image.
    smallest = min(source_gray.shape[:2])
    window = min(7, smallest if smallest % 2 == 1 else smallest - 1)
    if window < 3:
        return 0.0

    score = structural_similarity(source_gray, rendered_gray, win_size=window)
    return float(score)


def verify_visual(
    source_pdf: Path,
    xlsx_path: Path,
    work_dir: Path,
    dpi: int = COMPARE_DPI,
    threshold: float = DEFAULT_THRESHOLD,
) -> VerificationResult:
    """Render the workbook back to PDF and compare it to the source pages."""
    from app.pipeline.render_xlsx import LibreOfficeNotFound, LibreOfficeRenderError

    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        rendered_pdf = render_to_pdf(xlsx_path, work_dir)
    except LibreOfficeNotFound as exc:
        logger.info("visual verification skipped", extra={"reason": str(exc)})
        return VerificationResult(skipped_reason=str(exc))
    except LibreOfficeRenderError as exc:
        # The workbook not rendering at all is itself a verification failure.
        logger.warning("workbook failed to render", extra={"error": str(exc)})
        return VerificationResult(
            pages=[PageSimilarity(page_number=1, ssim=0.0, threshold=threshold)]
        )

    source_pages = render_document(source_pdf, dpi=dpi)
    rendered_pages = render_document(rendered_pdf, dpi=dpi)

    result = VerificationResult(rendered_pdf=rendered_pdf)
    for index, source_page in enumerate(source_pages):
        if index >= len(rendered_pages):
            # A missing page is a total mismatch, not an absent measurement.
            result.pages.append(
                PageSimilarity(page_number=index + 1, ssim=0.0, threshold=threshold)
            )
            continue
        score = compare_images(source_page.image, rendered_pages[index].image)
        result.pages.append(
            PageSimilarity(page_number=index + 1, ssim=score, threshold=threshold)
        )

    logger.info(
        "visual verification complete",
        extra={
            "pages": len(result.pages),
            "mean_ssim": round(result.mean_ssim, 4),
            "failures": len(result.failures),
        },
    )
    return result
