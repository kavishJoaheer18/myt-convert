"""Developer aid: print the grid a fixture converts to, next to what is expected.

Run with ``python -m tests.debug_dump <fixture-name>`` from ``backend/``.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from app.pipeline.convert import convert_pdf
from tests.fixtures.catalog import SPECS, get_fixture


def dump(name: str) -> None:
    fixture = get_fixture(name)
    work_dir = Path(tempfile.mkdtemp(prefix=f"gridlock_{name}_"))
    try:
        result = convert_pdf(fixture.pdf_path, work_dir, job_id=f"debug-{name}")

        for sheet, expected in zip(result.document.sheets, fixture.sheets):
            print(f"\n=== {name} page {sheet.page_number} ===")
            print(f"actual   rows={sheet.n_rows} cols={sheet.n_cols} cells={len(sheet.cells)}")
            print(f"expected rows={expected.n_rows} cols={expected.n_cols} cells={len(expected.cells)}")

            print("\n-- actual cells --")
            for cell in sorted(sheet.cells, key=lambda c: (c.row, c.col)):
                span = f" [{cell.row_span}x{cell.col_span}]" if cell.is_merged else ""
                print(f"  ({cell.row:>2},{cell.col:>2}){span:>10}  {cell.text!r}")

            print("\n-- expected cells --")
            for cell in sorted(expected.cells, key=lambda c: (c.row, c.col)):
                span = (
                    f" [{cell.row_span}x{cell.col_span}]"
                    if (cell.row_span > 1 or cell.col_span > 1)
                    else ""
                )
                print(f"  ({cell.row:>2},{cell.col:>2}){span:>10}  {cell.text!r}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    targets = sys.argv[1:] or list(SPECS)
    for target in targets:
        dump(target)
