"""Phase 1 gate: digital PDFs must round-trip at 100% cell-value accuracy.

Every fixture is rendered from a known declaration, converted, and scored against
that declaration cell by cell.  The workbook is read back from disk so the score
describes the artefact a user would download.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.content import PageKind
from app.pipeline.classify import classify_document
from app.pipeline.convert import convert_pdf
from app.pipeline.types import display_string, infer_value
from tests.accuracy import compare_workbook
from tests.conftest import record_report
from tests.fixtures.catalog import SPECS, get_fixture

PHASE = "phase 1 (digital)"
FIXTURE_NAMES = sorted(SPECS)


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_fixture_converts_at_full_accuracy(fixture_name: str, job_dir: Path) -> None:
    fixture = get_fixture(fixture_name)

    result = convert_pdf(fixture.pdf_path, job_dir, job_id=f"test-{fixture_name}")
    report = compare_workbook(fixture, result.output_path)
    record_report(PHASE, report)

    assert report.accuracy == 1.0 and report.passed, (
        f"{fixture_name}: {report.accuracy * 100:.2f}% accuracy over "
        f"{report.scored_cells} cells\n  " + "\n  ".join(report.problems()[:25])
    )


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_all_fixture_pages_classify_as_digital(fixture_name: str) -> None:
    fixture = get_fixture(fixture_name)
    classifications = classify_document(fixture.pdf_path)

    assert len(classifications) == len(fixture.sheets)
    assert all(c.kind is PageKind.DIGITAL for c in classifications), [
        (c.page_number, c.kind, c.char_count) for c in classifications
    ]


def test_multi_page_document_produces_one_sheet_per_page(job_dir: Path) -> None:
    fixture = get_fixture("mixed_5page")
    result = convert_pdf(fixture.pdf_path, job_dir, job_id="test-multipage")

    assert len(result.document.sheets) == 5
    assert [s.title for s in result.document.sheets] == [f"Page {n}" for n in range(1, 6)]


def test_images_are_extracted_and_anchored(job_dir: Path) -> None:
    fixture = get_fixture("multi_table_images")
    result = convert_pdf(fixture.pdf_path, job_dir, job_id="test-images")

    sheet = result.document.sheets[0]
    assert len(sheet.images) == 1

    image = sheet.images[0]
    assert Path(image.path).exists()
    # The swatch is declared 96 x 42 pt, which is 128 x 56 px at 96 DPI.
    assert image.width_px == pytest.approx(128, abs=2)
    assert image.height_px == pytest.approx(56, abs=2)


def test_column_widths_track_the_source_proportions(job_dir: Path) -> None:
    """The four declared columns are 150, 110, 90 and 130 pt wide."""
    fixture = get_fixture("simple_table")
    result = convert_pdf(fixture.pdf_path, job_dir, job_id="test-widths")

    widths = result.document.sheets[0].col_widths_pt
    assert len(widths) == 4
    for actual, declared in zip(widths, (150.0, 110.0, 90.0, 130.0)):
        assert actual == pytest.approx(declared, abs=1.5)


@pytest.mark.parametrize(
    ("text", "expected_value", "expected_format"),
    [
        ("1,250", 1250, "#,##0"),
        ("18,750.00", 18750.0, "#,##0.00"),
        ("3.14159", 3.14159, "0.00000"),
        ("-250", -250, "0"),
        ("2019", 2019, "0"),
        ("0.07", 0.07, "0.00"),
        # A leading zero is an identifier, not a quantity, and must survive.
        ("007", "007", "General"),
        ("PL01", "PL01", "General"),
        ("Invoice INV-1042", "Invoice INV-1042", "General"),
    ],
)
def test_type_inference_preserves_display(
    text: str, expected_value: object, expected_format: str
) -> None:
    value, number_format = infer_value(text)

    assert value == expected_value
    assert number_format == expected_format
    # The governing rule: typing a value must never change what the reader sees.
    assert display_string(value, number_format) == text
