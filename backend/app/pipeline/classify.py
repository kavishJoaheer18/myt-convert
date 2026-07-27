"""Page classification: does this page carry a usable text layer?

The answer decides which extractor runs, so it is deliberately conservative — a
page misrouted to the digital extractor silently loses whatever is locked inside
its raster, whereas a page needlessly sent to OCR merely costs time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import fitz

from app.models.content import PageKind

logger = logging.getLogger(__name__)

#: A page whose images blanket this fraction of it is probably a scan.
_IMAGE_COVERAGE_SCANNED = 0.80
#: Characters per page below which a text layer is not worth trusting alone.
_DEFAULT_MIN_CHARS = 20


@dataclass(frozen=True)
class PageClassification:
    """Why a page was routed the way it was — surfaced in logs and the API."""

    page_number: int
    kind: PageKind
    char_count: int
    image_coverage: float
    width: float
    height: float
    rotation: int


def _image_coverage(page: fitz.Page) -> float:
    """Fraction of the page covered by raster images (union approximated)."""
    page_area = abs(page.rect.get_area())
    if page_area <= 0:
        return 0.0

    covered = 0.0
    for info in page.get_image_info():
        bbox = fitz.Rect(info["bbox"])
        clipped = bbox & page.rect
        if not clipped.is_empty:
            covered += abs(clipped.get_area())

    # Overlapping images can push the naive sum past the page area.
    return min(1.0, covered / page_area)


def classify_page(page: fitz.Page, min_chars: int = _DEFAULT_MIN_CHARS) -> PageClassification:
    """Classify a single already-open page."""
    text = page.get_text("text") or ""
    char_count = len(text.strip())
    coverage = _image_coverage(page)

    if char_count < min_chars:
        kind = PageKind.SCANNED
    elif coverage >= _IMAGE_COVERAGE_SCANNED:
        # Text is present but a full-page image may hide much more of it.
        kind = PageKind.HYBRID
    else:
        kind = PageKind.DIGITAL

    return PageClassification(
        page_number=page.number + 1,
        kind=kind,
        char_count=char_count,
        image_coverage=coverage,
        width=page.rect.width,
        height=page.rect.height,
        rotation=page.rotation,
    )


def classify_document(
    pdf_path: Path, min_chars: int = _DEFAULT_MIN_CHARS
) -> list[PageClassification]:
    """Classify every page of a PDF."""
    results: list[PageClassification] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            results.append(classify_page(page, min_chars=min_chars))

    logger.info(
        "classified document",
        extra={
            "pdf": str(pdf_path),
            "pages": len(results),
            "kinds": {k.value: sum(1 for r in results if r.kind is k) for k in PageKind},
        },
    )
    return results
