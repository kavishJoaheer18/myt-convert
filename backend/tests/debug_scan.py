"""Developer aid: convert a rasterised fixture and print what did not match.

Run with ``python -m tests.debug_scan <fixture-name>`` from ``backend/``.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from app.pipeline.convert import convert_pdf  # noqa: E402
from app.pipeline.extract_ocr import PaddleOcrEngine  # noqa: E402
from tests.accuracy import compare_workbook  # noqa: E402
from tests.fixtures.catalog import GENERATED_DIR, SPECS, get_fixture  # noqa: E402
from tests.fixtures.rasterize import rasterize_fixture  # noqa: E402


def dump(name: str, engine: PaddleOcrEngine) -> None:
    scanned = rasterize_fixture(get_fixture(name), GENERATED_DIR, dpi=300)
    work_dir = Path(tempfile.mkdtemp(prefix=f"scan_{name}_"))
    try:
        result = convert_pdf(
            scanned.pdf_path, work_dir, job_id=f"debug-{name}", ocr_engine=engine
        )
        report = compare_workbook(scanned, result.output_path)

        print(f"\n=== {scanned.name}: {report.accuracy * 100:.2f}% ===")
        for problem in report.problems():
            print(f"  {problem}")

        for sheet, expected in zip(result.document.sheets, scanned.sheets):
            print(
                f"  page {sheet.page_number}: actual {sheet.n_rows}x{sheet.n_cols}, "
                f"expected {expected.n_rows}x{expected.n_cols}"
            )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    shared_engine = PaddleOcrEngine()
    for target in sys.argv[1:] or list(SPECS):
        dump(target, shared_engine)
