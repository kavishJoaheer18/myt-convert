"""Job routes: upload, poll, download."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi import Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.config import get_settings
from app.models.db import Job, JobStatus
from app.models.schemas import (
    CellOut,
    DiscrepancyOut,
    JobCreated,
    JobDetail,
    JobSummary,
    PageSummary,
    ReviewRequest,
    ReviewResponse,
    SheetOut,
)
from app.review import apply_corrections
from app.services import create_job, list_jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#: Uploads above this size are rejected before anything touches the disk.
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
#: Screen resolution for the review view; the OCR path renders at a higher DPI.
_REVIEW_DPI = 144


def _load_job(session: Session, job_id: str) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"job {job_id} not found")
    return job


def _to_detail(job: Job) -> JobDetail:
    return JobDetail(
        id=job.id,
        filename=job.filename,
        status=JobStatus(job.status),
        page_count=job.page_count,
        cell_count=job.cell_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
        error=job.error,
        duration_ms=job.duration_ms,
        has_output=bool(job.output_path and Path(job.output_path).exists()),
        has_verified_output=bool(job.verified_path and Path(job.verified_path).exists()),
        pages=[PageSummary.model_validate(p) for p in job.pages],
        discrepancies=[DiscrepancyOut.model_validate(d) for d in job.discrepancies],
    )


@router.post("", response_model=JobCreated, status_code=status.HTTP_202_ACCEPTED)
async def submit_job(
    file: UploadFile = File(...), session: Session = Depends(get_session)
) -> JobCreated:
    """Accept a PDF and queue it for conversion."""
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "only PDF uploads are accepted")

    # Stream to a temporary file so an oversized upload never lands in a job dir.
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as staging:
        staged = Path(staging.name)
        written = 0
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > _MAX_UPLOAD_BYTES:
                staging.close()
                staged.unlink(missing_ok=True)
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"upload exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
                )
            staging.write(chunk)

    if written == 0:
        staged.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "uploaded file is empty")

    job = create_job(session, filename, staged)

    # Imported here so the module stays importable without a broker configured.
    from app.worker import convert_job

    convert_job.delay(job.id)
    return JobCreated(id=job.id, status=JobStatus(job.status))


@router.get("", response_model=list[JobSummary])
def get_jobs(session: Session = Depends(get_session)) -> list[JobSummary]:
    return [JobSummary.model_validate(job) for job in list_jobs(session)]


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: str, session: Session = Depends(get_session)) -> JobDetail:
    return _to_detail(_load_job(session, job_id))


@router.get("/{job_id}/sheets/{page_number}", response_model=SheetOut)
def get_sheet(
    job_id: str, page_number: int, session: Session = Depends(get_session)
) -> SheetOut:
    """One page's cells, for the side-by-side review view."""
    job = _load_job(session, job_id)
    page = next((p for p in job.pages if p.page_number == page_number), None)
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"page {page_number} not found")

    return SheetOut(
        page_number=page.page_number,
        n_rows=page.n_rows,
        n_cols=page.n_cols,
        cells=[CellOut.model_validate(c) for c in page.cells],
    )


@router.get("/{job_id}/download")
def download(
    job_id: str, verified: bool = False, session: Session = Depends(get_session)
) -> FileResponse:
    """Download the produced workbook, or the corrected one once it exists."""
    job = _load_job(session, job_id)

    if job.status == JobStatus.FAILED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"job failed: {job.error or 'unknown error'}"
        )

    chosen = job.verified_path if verified else job.output_path
    if verified and not chosen:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no verified workbook for this job")
    if not chosen:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"job is {job.status}; no workbook yet"
        )

    path = Path(chosen)
    if not path.exists():
        raise HTTPException(status.HTTP_410_GONE, "workbook is no longer on disk")

    stem = Path(job.filename).stem or "converted"
    suffix = "-verified" if verified else ""
    return FileResponse(
        path, media_type=_XLSX_MEDIA_TYPE, filename=f"{stem}{suffix}.xlsx"
    )


@router.get("/{job_id}/pages/{page_number}/image")
def page_image(
    job_id: str, page_number: int, session: Session = Depends(get_session)
) -> FileResponse:
    """The source page as a PNG, for the side-by-side review view.

    Rendered on first request and cached in the job directory, so opening the
    review page does not re-rasterise a document every time.
    """
    job = _load_job(session, job_id)
    if not any(p.page_number == page_number for p in job.pages):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"page {page_number} not found")

    cached = get_settings().job_dir(job_id) / "renders" / f"page{page_number}.png"
    if not cached.exists():
        source = Path(job.source_path or "")
        if not source.exists():
            raise HTTPException(status.HTTP_410_GONE, "source PDF is no longer on disk")

        import fitz

        from app.pipeline.render import render_page, save_render

        with fitz.open(source) as document:
            if page_number > len(document):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "page out of range")
            save_render(render_page(document[page_number - 1], dpi=_REVIEW_DPI), cached)

    return FileResponse(cached, media_type="image/png")


@router.get("/{job_id}/discrepancies/{discrepancy_id}/crop")
def discrepancy_crop(
    job_id: str, discrepancy_id: str, session: Session = Depends(get_session)
) -> FileResponse:
    """The magnified crop of a disputed cell."""
    job = _load_job(session, job_id)
    discrepancy = next((d for d in job.discrepancies if d.id == discrepancy_id), None)
    if discrepancy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "discrepancy not found")
    if not discrepancy.crop_path or not Path(discrepancy.crop_path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no crop for this discrepancy")

    return FileResponse(discrepancy.crop_path, media_type="image/png")


@router.post("/{job_id}/review", response_model=ReviewResponse)
def submit_review(
    job_id: str, request: ReviewRequest, session: Session = Depends(get_session)
) -> ReviewResponse:
    """Apply human corrections and rebuild the verified workbook."""
    job = _load_job(session, job_id)

    if job.status == JobStatus.FAILED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"job failed: {job.error or 'unknown error'}"
        )

    try:
        applied, remaining = apply_corrections(
            session,
            job,
            get_settings().job_dir(job_id),
            request.corrections,
            accept_remaining=request.accept_remaining,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    return ReviewResponse(
        job_id=job.id,
        status=JobStatus(job.status),
        applied=applied,
        remaining_discrepancies=remaining,
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: str, session: Session = Depends(get_session)) -> Response:
    """Delete a job and everything it produced."""
    job = _load_job(session, job_id)
    session.delete(job)
    session.commit()
    shutil.rmtree(get_settings().job_dir(job_id), ignore_errors=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
