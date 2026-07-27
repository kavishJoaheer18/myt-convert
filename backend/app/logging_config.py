"""Structured JSON logging.

Every pipeline log line carries the ``job_id`` so a single conversion can be
followed end to end across the API process and the Celery workers.  Bind it once
with :func:`job_logger` and it rides along on every record.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Render records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Anything passed via `extra=` becomes a top-level field.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger, replacing any handlers."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # uvicorn installs its own handlers; make them defer to ours.
    for noisy in ("uvicorn", "uvicorn.access", "uvicorn.error", "celery"):
        logger = logging.getLogger(noisy)
        logger.handlers = []
        logger.propagate = True


def job_logger(name: str, job_id: str, **context: Any) -> logging.LoggerAdapter:
    """A logger whose every record carries ``job_id`` and any extra context."""
    return logging.LoggerAdapter(logging.getLogger(name), {"job_id": job_id, **context})
