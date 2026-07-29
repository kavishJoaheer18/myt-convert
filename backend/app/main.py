"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.jobs import router as jobs_router
from app.config import get_settings
from app.logging_config import configure_logging
from app.models.db import init_db

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    logger.info("api ready", extra={"data_dir": str(settings.data_dir)})
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

# In production the browser never calls this directly — the frontend proxies
# /api on its own origin — so CORS is only for local development and for any
# extra origins a deployment chooses to allow.
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(jobs_router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
