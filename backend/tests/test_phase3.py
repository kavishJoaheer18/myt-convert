"""Phase 3 gate: formatting fidelity.

Values in the right cells is not the whole job — the workbook has to *look* like
the page.  These tests assert the typography and decoration the converter claims
to reproduce, and then hand the result to LibreOffice, because a workbook
openpyxl writes happily can still be rejected by a real spreadsheet application.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import fitz
import pytest

from app.models.grid import BorderStyle, HAlign
from app.pipeline.convert import convert_pdf
from app.pipeline.render_xlsx import is_available, render_to_pdf
from app.pipeline.types import display_string, infer_value
from tests.accuracy import compare_workbook
from tests.conftest import record_report, requires_ocr
from tests.fixtures.catalog import GENERATED_DIR, SPECS, get_fixture
from tests.fixtures.rasterize import rasterize_fixture

PHASE = "phase 3 (formatting)"
FIXTURE_NAMES = sorted(SPECS)

requires_libreoffice = pytest.mark.skipif(
    not is_available(),
    reason="LibreOffice not installed; set LIBREOFFICE_BIN or use the worker image",
)


# --- Type inference ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected_value", "expected_format"),
    [
        # Currency, symbol leading and code trailing.
        ("$1,234.50", 1234.5, '"$"#,##0.00'),
        ("MUR 1,200.00", 1200.0, '"MUR "#,##0.00'),
        ("1,234.50 USD", 1234.5, '#,##0.00" USD"'),
        # Percentages are stored as fractions, as Excel expects.
        ("12.5%", 0.125, "0.0%"),
        ("-4.2%", -0.042, "0.0%"),
        ("100%", 1.0, "0%"),
        # Accounting negatives.
        ("(1,234.50)", -1234.5, "#,##0.00_);(#,##0.00)"),
        ("($980.00)", -980.0, '"$"0.00_);("$"0.00)'),
        # Dates in every unambiguous shape.
        ("2026-07-27", date(2026, 7, 27), "yyyy-mm-dd"),
        ("27 July 2026", date(2026, 7, 27), "d mmmm yyyy"),
        ("Jul 27, 2026", date(2026, 7, 27), "mmm d, yyyy"),
        ("27/07/2026", date(2026, 7, 27), "dd/mm/yyyy"),
    ],
)
def test_rich_type_inference_preserves_display(
    text: str, expected_value: object, expected_format: str
) -> None:
    value, number_format = infer_value(text)

    assert value == expected_value
    assert number_format == expected_format
    assert display_string(value, number_format) == text


@pytest.mark.parametrize(
    "text",
    [
        # Day/month order cannot be recovered, so typing it would be a guess.
        "01/02/2026",
        "11/12/2025",
        # Identifiers that merely look numeric.
        "007",
        "PL01",
        "2026-13-45",
    ],
)
def test_ambiguous_values_stay_text(text: str) -> None:
    value, number_format = infer_value(text)

    assert value == text
    assert number_format == "General"


def test_inference_never_changes_what_the_reader_sees() -> None:
    """The invariant behind every typing decision, over the whole fixture set."""
    for name in FIXTURE_NAMES:
        for sheet in get_fixture(name).sheets:
            for cell in sheet.cells:
                value, number_format = infer_value(cell.text)
                assert display_string(value, number_format) == cell.text, (
                    f"{name}: {cell.text!r} would display as "
                    f"{display_string(value, number_format)!r}"
                )


# --- Formatting fidelity ----------------------------------------------------


def test_formatting_is_reproduced(job_dir: Path) -> None:
    """Fills, borders, colour, italics and alignment all survive conversion."""
    fixture = get_fixture("formatted_report")

    result = convert_pdf(fixture.pdf_path, job_dir, job_id="fmt")
    report = compare_workbook(fixture, result.output_path)
    record_report(PHASE, report)

    assert report.passed, "\n  ".join(report.problems()[:25])


def test_header_row_carries_its_fill_and_reversed_text(job_dir: Path) -> None:
    fixture = get_fixture("formatted_report")
    result = convert_pdf(fixture.pdf_path, job_dir, job_id="fmt-header")

    sheet = result.document.sheets[0]
    header = [c for c in sheet.cells if c.row == 1 and c.text]
    assert len(header) == 4

    for cell in header:
        assert cell.style.fill_color == "1F3864"
        assert cell.style.font_color == "FFFFFF"
        assert cell.style.bold
        assert cell.style.borders.left.style is not BorderStyle.NONE
        assert cell.style.borders.top.style is not BorderStyle.NONE


def test_alignment_is_inferred_from_position(job_dir: Path) -> None:
    fixture = get_fixture("formatted_report")
    result = convert_pdf(fixture.pdf_path, job_dir, job_id="fmt-align")
    sheet = result.document.sheets[0]

    def align_at(row: int, col: int) -> HAlign:
        cell = sheet.cell_at(row, col)
        assert cell is not None, f"no cell at r{row}c{col}"
        return cell.style.h_align

    assert align_at(2, 0) is HAlign.LEFT  # "Trading income"
    assert align_at(2, 2) is HAlign.RIGHT  # "$42,180.55"
    assert align_at(1, 1) is HAlign.CENTER  # centred header


def test_empty_bordered_cells_are_materialised(job_dir: Path) -> None:
    """A blank cell inside a bordered table still shows its borders."""
    fixture = get_fixture("simple_table")
    result = convert_pdf(fixture.pdf_path, job_dir, job_id="fmt-blanks")
    sheet = result.document.sheets[0]

    for row in range(sheet.n_rows):
        for col in range(sheet.n_cols):
            cell = sheet.cell_covering(row, col)
            assert cell is not None, f"r{row}c{col} has no cell at all"
            assert cell.style.borders.any_visible, f"r{row}c{col} lost its borders"


@requires_ocr
def test_scanned_shaded_header_recovers_its_fill(job_dir: Path, ocr_engine) -> None:
    """A scan states no fills; the colour has to be read back off the pixels.

    The shading also hides the rule that would bound the row, so the fill's own
    edges are what re-establish the row boundary.
    """
    scanned = rasterize_fixture(get_fixture("formatted_report"), GENERATED_DIR, dpi=300)

    result = convert_pdf(
        scanned.pdf_path, job_dir, job_id="scan-fill", ocr_engine=ocr_engine
    )
    sheet = result.document.sheets[0]

    header = [c for c in sheet.cells if c.row == 1 and c.text]
    assert len(header) == 4
    for cell in header:
        assert cell.style.fill_color is not None, f"r1c{cell.col} lost its shading"
        channels = [int(cell.style.fill_color[i : i + 2], 16) for i in (0, 2, 4)]
        # Sampled from the raster, so allow a little tolerance around #1F3864.
        for actual, expected in zip(channels, (0x1F, 0x38, 0x64)):
            assert abs(actual - expected) <= 12


def test_column_widths_hold_the_source_proportions(job_dir: Path) -> None:
    """Relative widths must match, so the sheet reads like the page."""
    fixture = get_fixture("simple_table")
    result = convert_pdf(fixture.pdf_path, job_dir, job_id="fmt-widths")

    widths = result.document.sheets[0].col_widths_pt
    declared = (150.0, 110.0, 90.0, 130.0)

    total, declared_total = sum(widths), sum(declared)
    for actual, expected in zip(widths, declared):
        assert actual / total == pytest.approx(expected / declared_total, abs=0.005)


def test_row_heights_follow_the_source(job_dir: Path) -> None:
    fixture = get_fixture("formatted_report")
    result = convert_pdf(fixture.pdf_path, job_dir, job_id="fmt-heights")

    # The table's rows are declared 22 pt tall; row 0 is the heading above it.
    table_heights = result.document.sheets[0].row_heights_pt[1:]
    for height in table_heights:
        assert height == pytest.approx(22.0, abs=1.0)


# --- The LibreOffice gate ---------------------------------------------------


@requires_libreoffice
@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_workbook_renders_in_libreoffice(fixture_name: str, job_dir: Path) -> None:
    """Every produced workbook must open and print in a real spreadsheet app."""
    fixture = get_fixture(fixture_name)
    result = convert_pdf(fixture.pdf_path, job_dir, job_id=f"render-{fixture_name}")

    pdf_path = render_to_pdf(result.output_path, job_dir / "render")

    assert pdf_path.exists() and pdf_path.stat().st_size > 0
    with fitz.open(pdf_path) as rendered:
        # One source page becomes one worksheet, which prints as at least one page.
        assert len(rendered) >= len(fixture.sheets)
        assert rendered[0].get_text("text").strip()
