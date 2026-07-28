"""Phase 2 gate: rasterised fixtures convert at >=98% cell accuracy.

The same PDFs from Phase 1 are re-rendered at 300 DPI as image-only documents,
so the ground truth is identical and the only variable is that the text now has
to be read off pixels.  Every produced cell must also carry a real confidence
score, which is what Phase 4's consensus stage triages on.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.models.content import PageKind, TextSource
from app.pipeline.classify import classify_document
from app.pipeline.convert import convert_pdf, extract_pages
from app.pipeline.preprocess import binarize, estimate_skew, preprocess_page
from app.pipeline.raster_lines import detect_rulings
from app.pipeline.render import render_document
from tests.accuracy import compare_workbook
from tests.conftest import record_report
from tests.fixtures.catalog import GENERATED_DIR, SPECS, get_fixture
from tests.fixtures.rasterize import rasterize_fixture

PHASE = "phase 2 (scanned)"
#: The gate for OCR: near-perfect, but not the exact match digital text allows.
MIN_ACCURACY = 0.98
SCAN_DPI = 300

FIXTURE_NAMES = sorted(SPECS)


def _paddle_available() -> bool:
    try:
        import paddleocr  # noqa: F401
    except ImportError:
        return False
    return True


requires_ocr = pytest.mark.skipif(
    not _paddle_available(),
    reason="PaddleOCR is not installed; install requirements-ocr.txt to run the OCR gate",
)


@pytest.fixture(scope="module")
def ocr_engine():
    """One recognition model shared by the whole module; loading it is slow."""
    from app.pipeline.extract_ocr import PaddleOcrEngine

    return PaddleOcrEngine()


def _scanned(name: str, **kwargs: object):
    return rasterize_fixture(get_fixture(name), GENERATED_DIR, dpi=SCAN_DPI, **kwargs)


# --- Preprocessing (no OCR model needed) ------------------------------------


def test_rasterised_pages_classify_as_scanned() -> None:
    scanned = _scanned("simple_table")
    classifications = classify_document(scanned.pdf_path)

    assert all(c.kind is PageKind.SCANNED for c in classifications)
    # An image-only page has no text layer at all.
    assert all(c.char_count == 0 for c in classifications)


def test_deskew_removes_a_known_rotation() -> None:
    skewed = _scanned("simple_table", skew_degrees=0.8, suffix="_skewed")
    render = render_document(skewed.pdf_path, dpi=SCAN_DPI)[0]

    processed = preprocess_page(render.image, SCAN_DPI)

    # The skew was detected...
    assert abs(processed.skew_degrees) > 0.3
    # ...and what remains after correcting it is negligible.
    assert abs(estimate_skew(processed.binary)) < 0.2


def test_denoising_survives_sensor_noise() -> None:
    noisy = _scanned("simple_table", noise_sigma=12.0, suffix="_noisy")
    render = render_document(noisy.pdf_path, dpi=SCAN_DPI)[0]

    processed = preprocess_page(render.image, SCAN_DPI)
    rulings = detect_rulings(processed.binary, SCAN_DPI)

    # A six-row, four-column table has seven horizontal and five vertical rules.
    assert sum(1 for r in rulings if r.orientation == "h") >= 7
    assert sum(1 for r in rulings if r.orientation == "v") >= 5


def test_ruling_detection_recovers_the_table_grid() -> None:
    scanned = _scanned("simple_table")
    render = render_document(scanned.pdf_path, dpi=SCAN_DPI)[0]
    processed = preprocess_page(render.image, SCAN_DPI)

    rulings = detect_rulings(processed.binary, SCAN_DPI)
    horizontal = sorted({round(r.position, 0) for r in rulings if r.orientation == "h"})
    vertical = sorted({round(r.position, 0) for r in rulings if r.orientation == "v"})

    assert len(horizontal) == 7
    assert len(vertical) == 5
    # The declared column edges are at 56, 206, 316, 406 and 536 points.
    for actual, declared in zip(vertical, (56.0, 206.0, 316.0, 406.0, 536.0)):
        assert actual == pytest.approx(declared, abs=2.0)


def test_borderless_page_yields_no_spurious_rulings() -> None:
    scanned = _scanned("borderless_table")
    render = render_document(scanned.pdf_path, dpi=SCAN_DPI)[0]
    processed = preprocess_page(render.image, SCAN_DPI)

    rulings = detect_rulings(processed.binary, SCAN_DPI)

    # Rows of text must not be mistaken for rules.
    assert len(rulings) == 0


def test_skew_estimate_ignores_solid_image_blocks() -> None:
    """A logo must not be read as skew.

    Hough over a filled block finds unlimited near-horizontal chords through it.
    One 96x42 pt swatch was enough to swing the estimate to -2.3 degrees, which
    tilted the page and destroyed every table rule on it.
    """
    scanned = _scanned("multi_table_images")
    render = render_document(scanned.pdf_path, dpi=SCAN_DPI)[0]

    processed = preprocess_page(render.image, SCAN_DPI)

    assert abs(processed.skew_degrees) < 0.15
    # With the page left flat, the two tables' rules survive detection.
    rulings = detect_rulings(processed.binary, SCAN_DPI)
    assert sum(1 for r in rulings if r.orientation == "h") >= 10


def test_binarize_separates_ink_from_paper() -> None:
    render = render_document(_scanned("simple_table").pdf_path, dpi=150)[0]
    gray = render.image[:, :, 0]

    binary = binarize(gray)

    assert set(np.unique(binary)).issubset({0, 255})
    # A page of text is mostly paper.
    assert 0.001 < float(np.count_nonzero(binary)) / binary.size < 0.30


# --- The OCR gate -----------------------------------------------------------


@requires_ocr
@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_scanned_fixture_meets_accuracy_gate(
    fixture_name: str, job_dir: Path, ocr_engine
) -> None:
    scanned = _scanned(fixture_name)

    result = convert_pdf(
        scanned.pdf_path, job_dir, job_id=f"scan-{fixture_name}", ocr_engine=ocr_engine
    )
    report = compare_workbook(scanned, result.output_path)
    record_report(PHASE, report)

    assert report.accuracy >= MIN_ACCURACY, (
        f"{scanned.name}: {report.accuracy * 100:.2f}% accuracy over "
        f"{report.scored_cells} cells\n  " + "\n  ".join(report.problems()[:25])
    )


@requires_ocr
def test_pictures_are_recovered_from_a_scan(job_dir: Path, ocr_engine) -> None:
    """A scanned logo is just ink; it must still come back as an image.

    Dropping it would also drop the vertical space it occupied, shifting every
    row beneath it.
    """
    scanned = _scanned("multi_table_images")

    result = convert_pdf(
        scanned.pdf_path, job_dir, job_id="scan-figures", ocr_engine=ocr_engine
    )

    sheet = result.document.sheets[0]
    assert len(sheet.images) == 1
    assert Path(sheet.images[0].path).exists()
    # The row the swatch occupies survives, so the tables below it stay aligned.
    assert sheet.n_rows == 11


@requires_ocr
def test_every_scanned_cell_carries_a_confidence(job_dir: Path, ocr_engine) -> None:
    scanned = _scanned("simple_table")

    pages = extract_pages(
        scanned.pdf_path, job_dir / "images", ocr_engine=ocr_engine, dpi=SCAN_DPI
    )
    result = convert_pdf(
        scanned.pdf_path, job_dir, job_id="scan-confidence", ocr_engine=ocr_engine
    )

    assert all(page.kind is PageKind.SCANNED for page in pages)
    assert all(word.source is TextSource.OCR for page in pages for word in page.words)

    cells = [c for sheet in result.document.sheets for c in sheet.non_empty_cells()]
    assert cells, "conversion produced no cells"
    for cell in cells:
        assert cell.source is TextSource.OCR
        # A real score, not the digital path's placeholder 1.0.
        assert 0.0 < cell.confidence <= 1.0
