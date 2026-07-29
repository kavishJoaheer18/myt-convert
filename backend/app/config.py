"""Runtime configuration, read once from the environment."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "myt convert"
    log_level: str = "INFO"
    #: Browser origins allowed to call the API directly. Empty in production,
    #: where the frontend proxies /api on its own origin.
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    #: Root of the per-job artefact tree: ``{data_dir}/{job_id}/``.
    data_dir: Path = Field(default=Path("./data"))

    database_url: str = "postgresql+psycopg://gridlock:gridlock@postgres:5432/gridlock"
    redis_url: str = "redis://redis:6379/0"
    #: Run conversions inside the request instead of handing them to a worker.
    #: For trying the app on one machine without standing up Redis; a real
    #: deployment leaves this off so uploads return immediately.
    run_conversions_inline: bool = False

    # --- Extraction tuning -------------------------------------------------
    #: Below this many extractable characters per page, treat it as scanned.
    min_chars_for_digital: int = 20
    #: Raster resolution for OCR and for verification renders.
    render_dpi: int = 300
    #: "mobile" or "server". PaddleOCR defaults to the server models, which are
    #: an order of magnitude slower on CPU for a small accuracy gain; the
    #: deployment target here is CPU-only, so mobile is the sane default.
    ocr_model_variant: str = "mobile"

    # --- Consensus (Phase 4) -----------------------------------------------
    #: Cross-check every conversion against the VLM. Turned off automatically
    #: when no provider is configured, so a missing key degrades to a plain
    #: conversion rather than a failed job.
    enable_consensus: bool = True
    #: SSIM below which a rendered sheet counts as structurally diverged.
    visual_similarity_threshold: float = 0.50

    # --- VLM ---------------------------------------------------------------
    vlm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    vlm_model: str = "claude-opus-5"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2-vision"

    def job_dir(self, job_id: str) -> Path:
        return self.data_dir / job_id


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
