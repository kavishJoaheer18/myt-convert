"""The review flow: apply human corrections and rebuild a verified workbook.

The grid is persisted as JSON next to the workbook so a correction can be
applied to the *structure* — keeping every merge, border and fill — rather than
patching cells in a saved file. Rewriting from the grid means the verified
workbook is produced by exactly the same writer as the original, so a corrected
download cannot differ from an uncorrected one in any way except the values a
human changed.

Every correction is kept as ``(crop, wrong value, corrected value)``. That triple
is the only record of what the pipeline gets wrong in the field, and it is what
any future retraining would be built from.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db import Cell, Correction, Discrepancy, DiscrepancyStatus, Job, JobStatus, Page
from app.models.content import TextSource
from app.models.grid import DocumentGrid
from app.models.schemas import CellCorrection
from app.pipeline.excel_writer import write_workbook

logger = logging.getLogger(__name__)

GRID_FILENAME = "grid.json"
VERIFIED_FILENAME = "verified.xlsx"


def save_grid(document: DocumentGrid, job_dir: Path) -> Path:
    """Persist the structured grid so review can rebuild from it."""
    path = job_dir / GRID_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document.model_dump_json(), encoding="utf-8")
    return path


def load_grid(job_dir: Path) -> DocumentGrid:
    path = job_dir / GRID_FILENAME
    if not path.exists():
        raise FileNotFoundError(f"no saved grid for this job at {path}")
    return DocumentGrid.model_validate_json(path.read_text(encoding="utf-8"))


def _find_discrepancy(
    session: Session, job_id: str, correction: CellCorrection
) -> Discrepancy | None:
    statement = select(Discrepancy).where(
        Discrepancy.job_id == job_id,
        Discrepancy.page_number == correction.page_number,
        Discrepancy.row == correction.row,
        Discrepancy.col == correction.col,
    )
    return session.execute(statement).scalars().first()


def _update_stored_cell(
    session: Session, job_id: str, correction: CellCorrection
) -> str:
    """Write the corrected text onto the persisted cell; return the old value."""
    page = session.execute(
        select(Page).where(
            Page.job_id == job_id, Page.page_number == correction.page_number
        )
    ).scalars().first()
    if page is None:
        return ""

    cell = session.execute(
        select(Cell).where(
            Cell.page_id == page.id,
            Cell.row == correction.row,
            Cell.col == correction.col,
        )
    ).scalars().first()

    if cell is None:
        # A value the extractor missed entirely still belongs in the sheet.
        session.add(
            Cell(
                page_id=page.id,
                row=correction.row,
                col=correction.col,
                text=correction.value,
                source="human",
                confidence=1.0,
            )
        )
        return ""

    previous = cell.text
    cell.text = correction.value
    cell.source = "human"
    cell.confidence = 1.0
    return previous


def apply_corrections(
    session: Session,
    job: Job,
    job_dir: Path,
    corrections: list[CellCorrection],
    accept_remaining: bool = False,
) -> tuple[int, int]:
    """Apply corrections and rebuild the verified workbook.

    Returns ``(applied, remaining_open_discrepancies)``.
    """
    document = load_grid(job_dir)
    applied = 0

    for correction in corrections:
        sheet = next(
            (s for s in document.sheets if s.page_number == correction.page_number), None
        )
        if sheet is None:
            logger.warning(
                "correction for unknown page",
                extra={"job_id": job.id, "page": correction.page_number},
            )
            continue

        cell = sheet.cell_at(correction.row, correction.col)
        previous = _update_stored_cell(session, job.id, correction)

        if cell is None:
            # Materialise a cell the extractor never produced.
            from app.models.grid import GridCell

            cell = GridCell(row=correction.row, col=correction.col)
            sheet.cells.append(cell)
            sheet.n_rows = max(sheet.n_rows, correction.row + 1)
            sheet.n_cols = max(sheet.n_cols, correction.col + 1)
        else:
            previous = previous or cell.text

        cell.text = correction.value
        # Clear the typed value so the writer re-infers it from the new text.
        cell.value = None
        cell.number_format = "General"
        cell.source = TextSource.HUMAN
        cell.confidence = 1.0

        discrepancy = _find_discrepancy(session, job.id, correction)
        if discrepancy is not None:
            discrepancy.resolved_value = correction.value
            discrepancy.status = DiscrepancyStatus.RESOLVED

        session.add(
            Correction(
                job_id=job.id,
                page_number=correction.page_number,
                row=correction.row,
                col=correction.col,
                crop_path=discrepancy.crop_path if discrepancy is not None else None,
                wrong_value=previous,
                corrected_value=correction.value,
            )
        )
        applied += 1

    save_grid(document, job_dir)
    verified_path = write_workbook(document, job_dir / VERIFIED_FILENAME)
    job.verified_path = str(verified_path)

    if accept_remaining:
        for discrepancy in session.execute(
            select(Discrepancy).where(
                Discrepancy.job_id == job.id,
                Discrepancy.status == DiscrepancyStatus.OPEN,
            )
        ).scalars():
            discrepancy.status = DiscrepancyStatus.DISMISSED

    # Sessions are created with autoflush off, so the status changes above are
    # still pending; without this the count would report what was true before
    # the review and leave a finished job sitting in NEEDS_REVIEW.
    session.flush()

    remaining = len(
        list(
            session.execute(
                select(Discrepancy).where(
                    Discrepancy.job_id == job.id,
                    Discrepancy.status == DiscrepancyStatus.OPEN,
                )
            ).scalars()
        )
    )

    job.status = JobStatus.NEEDS_REVIEW if remaining else JobStatus.DONE
    session.commit()

    logger.info(
        "review applied",
        extra={"job_id": job.id, "applied": applied, "remaining": remaining},
    )
    return applied, remaining
