"""Celery application and tasks."""

from __future__ import annotations

from celery import Celery

from app.config import get_settings
from app.logging_config import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

celery_app = Celery(
    "gridlock",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    # Conversions are CPU-bound and long; one at a time per worker process keeps
    # memory predictable when PaddleOCR loads its models in Phase 2.
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    # Inline mode runs the task in the calling process, so no broker is needed.
    task_always_eager=settings.run_conversions_inline,
    task_eager_propagates=False,
)


@celery_app.task(name="gridlock.convert")
def convert_job(job_id: str) -> str:
    """Run one conversion end to end and return the job id."""
    # Imported lazily so the API process can enqueue without loading the pipeline.
    from app.services import run_conversion

    run_conversion(job_id)
    return job_id


@celery_app.task(name="gridlock.extract_quotes")
def extract_quotes(batch_id: str) -> str:
    """Extract a batch of supplier quotes into one template workbook."""
    from app.quotes.runner import run_quote_batch

    run_quote_batch(batch_id)
    return batch_id
