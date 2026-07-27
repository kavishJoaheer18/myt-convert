"""End-to-end conversion: PDF in, .xlsx out.

This module owns the ordering of the pipeline and nothing else.  It is importable
without Postgres, Redis or Celery so the conversion can be exercised directly by
tests and by the CLI.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import fitz
import pdfplumber

from app.models.content import PageContent, PageKind
from app.models.grid import DocumentGrid, SheetGrid
from app.pipeline.classify import PageClassification, classify_page
from app.pipeline.extract_digital import extract_page
from app.pipeline.gridmap import build_sheet_grid
from app.pipeline.excel_writer import write_workbook

logger = logging.getLogger(__name__)


class ScannedPageNotSupportedError(RuntimeError):
    """Raised when a page needs OCR, which arrives in Phase 2.

    Failing loudly is deliberate: silently emitting an empty sheet for a scanned
    page would look like a successful conversion that had simply lost the data.
    """

    def __init__(self, page_numbers: list[int]) -> None:
        self.page_numbers = page_numbers
        joined = ", ".join(str(n) for n in page_numbers)
        super().__init__(
            f"pages {joined} have no usable text layer and require OCR "
            f"(available from Phase 2)"
        )


@dataclass
class PageReport:
    """Per-page telemetry, surfaced through the API and the accuracy summary."""

    page_number: int
    kind: PageKind
    rows: int
    cols: int
    cells: int
    images: int
    duration_ms: float


@dataclass
class ConversionResult:
    job_id: str
    pdf_path: Path
    output_path: Path
    document: DocumentGrid
    pages: list[PageReport] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def total_cells(self) -> int:
        return self.document.total_cells


def _sheet_title(page_number: int, total_pages: int) -> str:
    return f"Page {page_number}" if total_pages > 1 else "Sheet1"


def extract_pages(pdf_path: Path, image_dir: Path, min_chars: int = 20) -> list[PageContent]:
    """Classify and extract every page of a PDF."""
    contents: list[PageContent] = []
    scanned: list[int] = []

    with fitz.open(pdf_path) as doc, pdfplumber.open(pdf_path) as plumber_pdf:
        for index in range(len(doc)):
            classification: PageClassification = classify_page(doc[index], min_chars=min_chars)
            if classification.kind is PageKind.SCANNED:
                scanned.append(classification.page_number)
                continue
            contents.append(
                extract_page(doc, plumber_pdf, index, classification.kind, image_dir)
            )

    if scanned:
        raise ScannedPageNotSupportedError(scanned)
    return contents


def build_document_grid(job_id: str, pages: list[PageContent]) -> DocumentGrid:
    """Map extracted pages onto worksheets."""
    sheets: list[SheetGrid] = [
        build_sheet_grid(page, title=_sheet_title(page.page_number, len(pages)))
        for page in pages
    ]
    return DocumentGrid(job_id=job_id, sheets=sheets)


def convert_pdf(pdf_path: Path, job_dir: Path, job_id: str) -> ConversionResult:
    """Convert ``pdf_path`` into ``{job_dir}/output.xlsx``."""
    started = time.perf_counter()
    job_dir.mkdir(parents=True, exist_ok=True)
    image_dir = job_dir / "images"

    pages = extract_pages(pdf_path, image_dir)

    sheets: list[SheetGrid] = []
    reports: list[PageReport] = []
    for page in pages:
        page_started = time.perf_counter()
        sheet = build_sheet_grid(page, title=_sheet_title(page.page_number, len(pages)))
        sheets.append(sheet)
        reports.append(
            PageReport(
                page_number=page.page_number,
                kind=page.kind,
                rows=sheet.n_rows,
                cols=sheet.n_cols,
                cells=len(sheet.non_empty_cells()),
                images=len(sheet.images),
                duration_ms=(time.perf_counter() - page_started) * 1000.0,
            )
        )

    document = DocumentGrid(job_id=job_id, sheets=sheets)
    output_path = write_workbook(document, job_dir / "output.xlsx")
    duration_ms = (time.perf_counter() - started) * 1000.0

    logger.info(
        "conversion complete",
        extra={
            "job_id": job_id,
            "pages": len(pages),
            "cells": document.total_cells,
            "duration_ms": round(duration_ms, 1),
        },
    )

    return ConversionResult(
        job_id=job_id,
        pdf_path=pdf_path,
        output_path=output_path,
        document=document,
        pages=reports,
        duration_ms=duration_ms,
    )
