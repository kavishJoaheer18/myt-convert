"""Driving a quote batch from its database record.

Kept apart from the extraction itself so the pipeline can be exercised without a
database, and so the worker task stays a single call.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import get_settings
from app.logging_config import job_logger
from app.models.db import JobStatus, QuoteBatch, new_session
from app.quotes.service import run_batch

logger = logging.getLogger(__name__)

OUTPUT_FILENAME = "supplier-quotes.xlsx"


def run_quote_batch(batch_id: str) -> None:
    """Extract every quote in a batch and record the outcome."""
    session = new_session()
    log = job_logger(__name__, batch_id)

    try:
        batch = session.get(QuoteBatch, batch_id)
        if batch is None:
            log.warning("quote batch not found")
            return

        batch.status = JobStatus.PROCESSING
        session.commit()

        settings = get_settings()
        batch_dir = settings.job_dir(batch_id)
        source_dir = batch_dir / "sources"
        pdfs = sorted(source_dir.glob("*.pdf"))
        if not pdfs:
            raise FileNotFoundError(f"no source PDFs under {source_dir}")

        log.info("quote batch started", extra={"files": len(pdfs)})
        result = run_batch(pdfs, batch_dir / OUTPUT_FILENAME, batch_dir)

        # A file that could not be opened at all is a warning too — otherwise it
        # would vanish silently from a batch that otherwise looks fine.
        warnings = list(result.warnings)
        warnings.extend(f"{name}: {reason}" for name, reason in result.failures)

        batch.files_read = result.files_read
        batch.row_count = result.rows
        batch.warnings = "\n".join(warnings)
        batch.output_path = str(result.output_path)
        batch.duration_ms = result.duration_ms
        batch.status = JobStatus.DONE
        batch.error = None
        session.commit()

        log.info("quote batch finished", extra={"rows": result.rows})

    except Exception as exc:  # noqa: BLE001 - the failure must reach the user
        session.rollback()
        batch = session.get(QuoteBatch, batch_id)
        if batch is not None:
            batch.status = JobStatus.FAILED
            batch.error = f"{type(exc).__name__}: {exc}"
            session.commit()
        log.exception("quote batch failed")

    finally:
        session.close()
