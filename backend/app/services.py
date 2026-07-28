"""Job orchestration: the layer between HTTP/Celery and the pipeline.

Kept free of both FastAPI and Celery imports so a conversion can be driven from a
test or a shell without a broker running.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging_config import job_logger
from app.models.db import Cell, Discrepancy, Job, JobStatus, Page, new_session
from app.models.grid import DocumentGrid
from app.pipeline.consensus import run_consensus
from app.pipeline.convert import ConversionResult, convert_pdf
from app.pipeline.excel_writer import write_workbook
from app.pipeline.types import infer_value
from app.review import save_grid
from app.vlm.base import VLMUnavailable, get_provider

logger = logging.getLogger(__name__)


def create_job(session: Session, filename: str, upload: Path) -> Job:
    """Register a job and move the upload into its own directory."""
    settings = get_settings()
    job = Job(filename=filename, status=JobStatus.QUEUED)
    session.add(job)
    session.flush()

    job_dir = settings.job_dir(job.id)
    job_dir.mkdir(parents=True, exist_ok=True)
    destination = job_dir / "source.pdf"
    shutil.move(str(upload), destination)

    job.source_path = str(destination)
    session.commit()
    return job


def _persist_document(session: Session, job: Job, document: DocumentGrid) -> None:
    """Store every page and cell so later phases can reason about them."""
    for sheet in document.sheets:
        page = Page(
            job_id=job.id,
            page_number=sheet.page_number,
            kind=sheet.kind,
            n_rows=sheet.n_rows,
            n_cols=sheet.n_cols,
            width_pt=sheet.page_width_pt,
            height_pt=sheet.page_height_pt,
        )
        session.add(page)
        session.flush()

        for cell in sheet.cells:
            # The page text is what is stored; the typed value is re-derived on
            # export, so only the format it will be rendered with is kept here.
            number_format = (
                cell.number_format if cell.value is not None else infer_value(cell.text)[1]
            )
            session.add(
                Cell(
                    page_id=page.id,
                    row=cell.row,
                    col=cell.col,
                    row_span=cell.row_span,
                    col_span=cell.col_span,
                    text=cell.text,
                    number_format=number_format,
                    source=cell.source.value,
                    confidence=cell.confidence,
                )
            )


def _cross_check(
    session: Session,
    job: Job,
    source: Path,
    result: ConversionResult,
    job_dir: Path,
) -> int:
    """Run the consensus pass, if a provider is configured.

    A missing or unreachable provider degrades to a plain conversion rather than
    a failed job: a second opinion is valuable, not mandatory. Returns the number
    of disputes left for a human.
    """
    settings = get_settings()
    if not settings.enable_consensus:
        return 0

    try:
        provider = get_provider()
    except VLMUnavailable as exc:
        logger.info("consensus skipped", extra={"job_id": job.id, "reason": str(exc)})
        return 0

    if not provider.is_available():
        logger.info(
            "consensus skipped",
            extra={"job_id": job.id, "reason": f"{provider.name} provider not configured"},
        )
        return 0

    consensus = run_consensus(
        source,
        result.document,
        provider,
        crop_dir=job_dir / "crops",
        dpi=settings.render_dpi,
    )

    if consensus.corrected:
        # Cells the second look settled have changed, so the workbook the user
        # downloads must be rewritten from the corrected grid.
        write_workbook(result.document, result.output_path)

    for dispute in consensus.open_disputes:
        session.add(
            Discrepancy(
                job_id=job.id,
                page_number=dispute.page_number,
                row=dispute.row,
                col=dispute.col,
                deterministic_value=dispute.deterministic_value,
                vlm_value=dispute.vlm_value,
                crop_path=dispute.crop_path,
                confidence=dispute.confidence,
            )
        )

    return len(consensus.open_disputes)


def run_conversion(job_id: str) -> ConversionResult | None:
    """Convert one job's PDF and record the outcome.

    Returns ``None`` if the job vanished; raises nothing on conversion failure —
    the failure is recorded on the job so the API can report it.
    """
    settings = get_settings()
    session: Session = new_session()
    log = job_logger(__name__, job_id)

    try:
        job = session.get(Job, job_id)
        if job is None:
            log.warning("job not found")
            return None

        job.status = JobStatus.PROCESSING
        session.commit()

        source = Path(job.source_path or "")
        if not source.exists():
            raise FileNotFoundError(f"source PDF missing at {source}")

        log.info("conversion started", extra={"source": str(source)})
        job_dir = settings.job_dir(job_id)
        result = convert_pdf(source, job_dir, job_id)

        open_disputes = _cross_check(session, job, source, result, job_dir)

        _persist_document(session, job, result.document)
        save_grid(result.document, job_dir)

        job.output_path = str(result.output_path)
        job.page_count = len(result.document.sheets)
        job.cell_count = result.total_cells
        job.duration_ms = result.duration_ms
        job.status = JobStatus.NEEDS_REVIEW if open_disputes else JobStatus.DONE
        job.error = None
        session.commit()

        log.info(
            "conversion succeeded",
            extra={"cells": job.cell_count, "open_disputes": open_disputes},
        )
        return result

    except Exception as exc:  # noqa: BLE001 - the failure must reach the user
        session.rollback()
        job = session.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error = f"{type(exc).__name__}: {exc}"
            session.commit()
        log.exception("conversion failed")
        return None

    finally:
        session.close()


def list_jobs(session: Session, limit: int = 100) -> list[Job]:
    statement = select(Job).order_by(Job.created_at.desc()).limit(limit)
    return list(session.execute(statement).scalars())
