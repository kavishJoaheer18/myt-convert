"""Quote batch routes: upload several PDFs, download one spreadsheet."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.config import get_settings
from app.models.db import JobStatus, QuoteBatch
from app.models.schemas import QuoteBatchCreated, QuoteBatchSummary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/quotes", tags=["quotes"])

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
_MAX_FILES = 50


def _load_batch(session: Session, batch_id: str) -> QuoteBatch:
    batch = session.get(QuoteBatch, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"batch {batch_id} not found")
    return batch


def _to_summary(batch: QuoteBatch) -> QuoteBatchSummary:
    return QuoteBatchSummary(
        id=batch.id,
        status=JobStatus(batch.status),
        filenames=[name for name in (batch.filenames or "").split("\n") if name],
        file_count=batch.file_count,
        files_read=batch.files_read,
        row_count=batch.row_count,
        warnings=[w for w in (batch.warnings or "").split("\n") if w],
        error=batch.error,
        duration_ms=batch.duration_ms,
        has_output=bool(batch.output_path and Path(batch.output_path).exists()),
        created_at=batch.created_at,
    )


@router.post("", response_model=QuoteBatchCreated, status_code=status.HTTP_202_ACCEPTED)
async def submit_batch(
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
) -> QuoteBatchCreated:
    """Accept one or more quote PDFs and queue them for extraction."""
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no files were uploaded")
    if len(files) > _MAX_FILES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"at most {_MAX_FILES} files per batch"
        )

    for upload in files:
        if not (upload.filename or "").lower().endswith(".pdf"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{upload.filename or 'file'} is not a PDF",
            )

    batch = QuoteBatch(status=JobStatus.QUEUED, file_count=len(files))
    session.add(batch)
    session.flush()

    settings = get_settings()
    source_dir = settings.job_dir(batch.id) / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)

    names: list[str] = []
    for index, upload in enumerate(files):
        name = Path(upload.filename or f"quote{index}.pdf").name
        # Numbered so two suppliers sending "Quote.pdf" do not collide.
        destination = source_dir / f"{index:03d}_{name}"
        written = 0
        with destination.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > _MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        f"{name} exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
                    )
                handle.write(chunk)
        names.append(name)

    batch.filenames = "\n".join(names)
    session.commit()

    from app.worker import extract_quotes

    extract_quotes.delay(batch.id)
    return QuoteBatchCreated(id=batch.id, status=JobStatus(batch.status))


@router.get("", response_model=list[QuoteBatchSummary])
def list_batches(session: Session = Depends(get_session)) -> list[QuoteBatchSummary]:
    statement = select(QuoteBatch).order_by(QuoteBatch.created_at.desc()).limit(100)
    return [_to_summary(b) for b in session.execute(statement).scalars()]


@router.get("/{batch_id}", response_model=QuoteBatchSummary)
def get_batch(batch_id: str, session: Session = Depends(get_session)) -> QuoteBatchSummary:
    return _to_summary(_load_batch(session, batch_id))


@router.get("/{batch_id}/download")
def download_batch(
    batch_id: str, session: Session = Depends(get_session)
) -> FileResponse:
    """The filled-in supplier quote template."""
    batch = _load_batch(session, batch_id)

    if batch.status == JobStatus.FAILED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"batch failed: {batch.error or 'unknown error'}"
        )
    if not batch.output_path:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"batch is {batch.status}; no spreadsheet yet"
        )

    path = Path(batch.output_path)
    if not path.exists():
        raise HTTPException(status.HTTP_410_GONE, "spreadsheet is no longer on disk")

    return FileResponse(
        path, media_type=_XLSX_MEDIA_TYPE, filename="supplier-quotes.xlsx"
    )


@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_batch(batch_id: str, session: Session = Depends(get_session)) -> Response:
    batch = _load_batch(session, batch_id)
    session.delete(batch)
    session.commit()
    shutil.rmtree(get_settings().job_dir(batch_id), ignore_errors=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
