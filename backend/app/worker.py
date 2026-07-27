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
)


@celery_app.task(name="gridlock.convert")
def convert_job(job_id: str) -> str:
    """Run one conversion end to end and return the job id."""
    # Imported lazily so the API process can enqueue without loading the pipeline.
    from app.services import run_conversion

    run_conversion(job_id)
    return job_id
