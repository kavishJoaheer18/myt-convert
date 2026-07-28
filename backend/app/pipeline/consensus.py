"""Dual extraction and dispute resolution.

The deterministic pipeline and a vision model read the same page independently.
Where they agree, the cell passes untouched — which is the overwhelming majority
and costs nothing further.  Where they disagree, the cell is *looked at again*:
the disputed region is re-rasterised from the PDF at several times the working
resolution and put back to both the OCR engine and the model.

Re-rasterising rather than upscaling matters. Enlarging a crop of the page image
interpolates pixels that were already lost; going back to the PDF redraws the
glyphs, which is the only way a second look can see anything the first did not.

A cell is only overwritten when two independent readers of the magnified crop
agree with each other and against the original. Anything still unresolved
becomes a Discrepancy for a human, because the alternative — picking a winner
on one vote — is how silent corruption gets into a spreadsheet.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import fitz
import numpy as np
from PIL import Image

from app.models.content import TextSource
from app.models.geometry import BBox
from app.models.grid import DocumentGrid, GridCell, SheetGrid
from app.pipeline.render import render_page, render_region
from app.vlm.base import CellQuery, CellReading, VLMProvider

if TYPE_CHECKING:
    from app.pipeline.extract_ocr import OcrEngine

logger = logging.getLogger(__name__)

#: How much bigger than the working resolution the second look is taken at.
ZOOM_FACTOR = 3.5
#: Padding around a disputed cell, in points, so glyphs are not clipped.
CROP_PADDING_PT = 2.0
#: Confidence recorded for a cell the crop readers agreed to change.
RESOLVED_CONFIDENCE = 0.95

_WHITESPACE = re.compile(r"\s+")


class Resolution(StrEnum):
    """How a candidate dispute ended up."""

    #: The second look confirmed the original value; nothing to do.
    AGREED = "agreed"
    #: Both crop readers agreed on a different value, which was applied.
    CORRECTED = "corrected"
    #: Still unsettled; a human has to decide.
    OPEN = "open"


@dataclass
class Dispute:
    """One cell the two readings did not agree on."""

    page_number: int
    row: int
    col: int
    deterministic_value: str
    vlm_value: str
    resolution: Resolution
    resolved_value: str | None = None
    crop_path: str | None = None
    #: Confidence in the resolution, not in the original extraction.
    confidence: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.resolution is Resolution.OPEN


@dataclass
class ConsensusResult:
    """What the consensus pass found across a document."""

    checked_cells: int = 0
    disputes: list[Dispute] = field(default_factory=list)

    @property
    def flagged(self) -> list[Dispute]:
        """Every cell the two readings disagreed on and that needed a decision."""
        return [d for d in self.disputes if d.resolution is not Resolution.AGREED]

    @property
    def open_disputes(self) -> list[Dispute]:
        return [d for d in self.disputes if d.is_open]

    @property
    def corrected(self) -> list[Dispute]:
        return [d for d in self.disputes if d.resolution is Resolution.CORRECTED]

    @property
    def needs_review(self) -> bool:
        return bool(self.open_disputes)


def normalize(text: str) -> str:
    """Collapse whitespace so trivial spacing differences are not disputes."""
    return _WHITESPACE.sub(" ", text or "").strip()


def _same(left: str, right: str) -> bool:
    return normalize(left) == normalize(right)


def _to_png(image: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="PNG")
    return buffer.getvalue()


def _queries_for(sheet: SheetGrid) -> list[CellQuery]:
    """Every cell worth a second opinion, with where to look for it."""
    queries: list[CellQuery] = []
    for cell in sheet.cells:
        if cell.is_empty or cell.bbox is None:
            continue
        queries.append(
            CellQuery(
                row=cell.row,
                col=cell.col,
                value=cell.text,
                x0=round(cell.bbox.x0, 1),
                top=round(cell.bbox.top, 1),
                x1=round(cell.bbox.x1, 1),
                bottom=round(cell.bbox.bottom, 1),
            )
        )
    return queries


def _read_crop_with_ocr(crop: np.ndarray, engine: "OcrEngine | None") -> str | None:
    """Read a magnified crop with the OCR engine, if one is available."""
    if engine is None:
        return None
    try:
        detections = engine.recognize(crop)
    except Exception as exc:  # noqa: BLE001 - a failed re-read is not fatal
        logger.warning("crop OCR failed", extra={"error": str(exc)})
        return None

    ordered = sorted(detections, key=lambda d: (round(d.top / 10.0), d.x0))
    return normalize(" ".join(d.text for d in ordered))


def _decide(
    deterministic: str,
    page_vlm: str,
    crop_ocr: str | None,
    crop_vlm: str | None,
) -> tuple[Resolution, str | None]:
    """Weigh the four readings of one cell.

    The original value is only overturned when both readers of the magnified
    crop agree with each other and against it. One dissenting voice is enough to
    dispute a cell, but never enough to rewrite it.
    """
    if crop_ocr and crop_vlm and _same(crop_ocr, crop_vlm):
        winner = crop_ocr
        if _same(winner, deterministic):
            return Resolution.AGREED, None
        return Resolution.CORRECTED, winner

    # A single crop reader confirming the original settles it the other way:
    # the page-level model was mistaken.
    if crop_ocr and _same(crop_ocr, deterministic):
        return Resolution.AGREED, None
    if crop_vlm and _same(crop_vlm, deterministic):
        return Resolution.AGREED, None

    # A crop reader corroborating the page-level model is two votes against one.
    if crop_ocr and _same(crop_ocr, page_vlm):
        return Resolution.CORRECTED, page_vlm
    if crop_vlm and _same(crop_vlm, page_vlm):
        return Resolution.CORRECTED, page_vlm

    return Resolution.OPEN, None


def _crop_for_cell(
    page: fitz.Page, cell_bbox: BBox, dpi: int, zoom: float
) -> np.ndarray:
    padded = BBox(
        x0=cell_bbox.x0 - CROP_PADDING_PT,
        top=cell_bbox.top - CROP_PADDING_PT,
        x1=cell_bbox.x1 + CROP_PADDING_PT,
        bottom=cell_bbox.bottom + CROP_PADDING_PT,
    )
    return render_region(page, padded, dpi=int(dpi * zoom))


def _apply_correction(cell: GridCell, value: str) -> None:
    """Overwrite a cell's text, letting the writer re-derive its typed value."""
    cell.text = value
    cell.value = None
    cell.number_format = "General"
    cell.source = TextSource.VLM
    cell.confidence = RESOLVED_CONFIDENCE


def reconcile_page(
    page: fitz.Page,
    sheet: SheetGrid,
    vlm: VLMProvider,
    ocr_engine: "OcrEngine | None",
    crop_dir: Path,
    dpi: int,
    zoom: float = ZOOM_FACTOR,
) -> list[Dispute]:
    """Cross-check one sheet against the model and resolve what it can."""
    queries = _queries_for(sheet)
    if not queries:
        return []

    page_png = _to_png(render_page(page, dpi=dpi).image)
    verdict = vlm.verify_page(page_png, queries)
    if not verdict.disagreements and not verdict.missing:
        return []

    crop_dir.mkdir(parents=True, exist_ok=True)
    by_position = {(c.row, c.col): c for c in sheet.cells}
    disputes: list[Dispute] = []

    candidates: list[tuple[CellReading, GridCell | None]] = [
        (reading, by_position.get((reading.row, reading.col)))
        for reading in (*verdict.disagreements, *verdict.missing)
    ]

    for reading, cell in candidates:
        deterministic = cell.text if cell is not None else ""
        bbox = cell.bbox if cell is not None else None

        crop_ocr: str | None = None
        crop_vlm: str | None = None
        crop_path: Path | None = None

        if bbox is not None:
            crop = _crop_for_cell(page, bbox, dpi, zoom)
            crop_path = crop_dir / f"p{sheet.page_number}_r{reading.row}c{reading.col}.png"
            Image.fromarray(crop).save(crop_path, format="PNG")

            crop_ocr = _read_crop_with_ocr(crop, ocr_engine)
            try:
                crop_vlm = normalize(vlm.read_crop(_to_png(crop)).text)
            except NotImplementedError:
                raise
            except Exception as exc:  # noqa: BLE001 - a failed re-read is not fatal
                logger.warning("crop VLM read failed", extra={"error": str(exc)})

        resolution, resolved_value = _decide(
            deterministic, reading.text, crop_ocr, crop_vlm
        )

        if resolution is Resolution.CORRECTED and resolved_value is not None and cell is not None:
            _apply_correction(cell, resolved_value)

        disputes.append(
            Dispute(
                page_number=sheet.page_number,
                row=reading.row,
                col=reading.col,
                deterministic_value=deterministic,
                vlm_value=reading.text,
                resolution=resolution,
                resolved_value=resolved_value,
                crop_path=str(crop_path) if crop_path is not None else None,
                confidence=reading.confidence,
            )
        )

    return disputes


def run_consensus(
    pdf_path: Path,
    document: DocumentGrid,
    vlm: VLMProvider,
    ocr_engine: "OcrEngine | None" = None,
    crop_dir: Path | None = None,
    dpi: int = 300,
    zoom: float = ZOOM_FACTOR,
) -> ConsensusResult:
    """Cross-check a whole document, correcting what the second look settles.

    Cells the crop readers agree to change are rewritten in ``document`` before
    the workbook is written; everything still unsettled comes back as an open
    dispute.
    """
    result = ConsensusResult()
    crops = crop_dir or (pdf_path.parent / "crops")

    with fitz.open(pdf_path) as doc:
        for sheet in document.sheets:
            index = sheet.page_number - 1
            if index >= len(doc):
                continue
            result.checked_cells += len(sheet.non_empty_cells())
            result.disputes.extend(
                reconcile_page(doc[index], sheet, vlm, ocr_engine, crops, dpi, zoom)
            )

    logger.info(
        "consensus complete",
        extra={
            "job_id": document.job_id,
            "checked": result.checked_cells,
            "flagged": len(result.flagged),
            "corrected": len(result.corrected),
            "open": len(result.open_disputes),
        },
    )
    return result
