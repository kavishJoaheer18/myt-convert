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

from app.config import get_settings
from app.models.content import PageContent, PageKind
from app.models.grid import DocumentGrid, SheetGrid
from app.pipeline.classify import PageClassification, classify_page
from app.pipeline.extract_digital import extract_page
from app.pipeline.extract_ocr import OcrEngine, PaddleOcrEngine, extract_page_ocr
from app.pipeline.gridmap import build_sheet_grid
from app.pipeline.excel_writer import write_workbook
from app.pipeline.render import render_page

logger = logging.getLogger(__name__)


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


def extract_pages(
    pdf_path: Path,
    image_dir: Path,
    min_chars: int | None = None,
    ocr_engine: OcrEngine | None = None,
    dpi: int | None = None,
) -> list[PageContent]:
    """Classify every page and route it to the extractor it needs.

    The OCR engine is constructed only if a scanned page actually turns up, so a
    document of digital pages never pays for loading a recognition model.
    """
    # Resolved per call, not at import: the process may be reconfigured after
    # this module is loaded.
    settings = get_settings()
    contents: list[PageContent] = []
    threshold = min_chars if min_chars is not None else settings.min_chars_for_digital
    resolution = dpi or settings.render_dpi
    engine = ocr_engine

    with fitz.open(pdf_path) as doc, pdfplumber.open(pdf_path) as plumber_pdf:
        for index in range(len(doc)):
            classification: PageClassification = classify_page(
                doc[index], min_chars=threshold
            )

            if classification.kind is PageKind.SCANNED:
                if engine is None:
                    engine = PaddleOcrEngine()
                render = render_page(doc[index], dpi=resolution)
                contents.append(
                    extract_page_ocr(
                        render, engine, dpi=resolution, image_dir=image_dir
                    )
                )
            else:
                # A hybrid page keeps its text layer; Phase 4's consensus pass is
                # what catches anything hiding inside its images.
                contents.append(
                    extract_page(doc, plumber_pdf, index, classification.kind, image_dir)
                )

    return contents


def build_document_grid(job_id: str, pages: list[PageContent]) -> DocumentGrid:
    """Map extracted pages onto worksheets."""
    sheets: list[SheetGrid] = [
        build_sheet_grid(page, title=_sheet_title(page.page_number, len(pages)))
        for page in pages
    ]
    return DocumentGrid(job_id=job_id, sheets=sheets)


def convert_pdf(
    pdf_path: Path,
    job_dir: Path,
    job_id: str,
    ocr_engine: OcrEngine | None = None,
) -> ConversionResult:
    """Convert ``pdf_path`` into ``{job_dir}/output.xlsx``."""
    started = time.perf_counter()
    job_dir.mkdir(parents=True, exist_ok=True)
    image_dir = job_dir / "images"

    pages = extract_pages(pdf_path, image_dir, ocr_engine=ocr_engine)

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
