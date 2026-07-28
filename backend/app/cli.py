"""Convert a PDF from the command line.

The quickest way to try a real document: no database, no broker, no containers.

    python -m app.cli invoice.pdf

The full stack is what you want for the review workflow, since that needs the
job records and the web UI. This is for seeing what the converter makes of a
particular file.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from app.config import get_settings
from app.pipeline.classify import classify_document
from app.pipeline.convert import convert_pdf


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Convert a PDF to a layout-faithful .xlsx.",
    )
    parser.add_argument("pdf", type=Path, help="the PDF to convert")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="where to write the .xlsx (default: alongside the PDF)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=None,
        help="raster resolution for scanned pages (default: 300)",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="only report how each page would be classified, and stop",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show pipeline logging"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not args.pdf.exists():
        print(f"error: no such file: {args.pdf}", file=sys.stderr)
        return 2

    settings = get_settings()
    if args.dpi:
        settings.render_dpi = args.dpi

    classifications = classify_document(args.pdf, min_chars=settings.min_chars_for_digital)
    print(f"{args.pdf.name}: {len(classifications)} page(s)")
    for page in classifications:
        print(
            f"  page {page.page_number}: {page.kind.value} "
            f"({page.char_count} chars, {page.image_coverage:.0%} image cover)"
        )

    if args.inspect:
        return 0

    if any(p.kind.value == "scanned" for p in classifications):
        # Plain ASCII: the Windows console defaults to cp1252 and mangles the rest.
        print("\nScanned pages found; loading the OCR models (first run downloads them)...")

    output = args.output or args.pdf.with_suffix(".xlsx")
    started = time.perf_counter()
    try:
        result = convert_pdf(args.pdf, output.parent, job_id=args.pdf.stem)
    except ImportError as exc:
        print(
            f"\nerror: this document needs the OCR extras: {exc}\n"
            f"       pip install -r requirements-ocr.txt",
            file=sys.stderr,
        )
        return 3

    # convert_pdf writes output.xlsx into the directory it is given.
    produced = result.output_path
    if produced != output:
        produced.replace(output)

    elapsed = time.perf_counter() - started
    print(f"\nwrote {output}  ({elapsed:.1f}s)")
    print(f"{'page':>5}  {'source':>8}  {'rows':>5}  {'cols':>5}  {'cells':>6}  images")
    for page in result.pages:
        print(
            f"{page.page_number:>5}  {page.kind.value:>8}  {page.rows:>5}  "
            f"{page.cols:>5}  {page.cells:>6}  {page.images}"
        )
    print(f"{'':>5}  {'total':>8}  {'':>5}  {'':>5}  {result.total_cells:>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
