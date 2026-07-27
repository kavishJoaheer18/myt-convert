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

    app_name: str = "GridLock"
    log_level: str = "INFO"

    #: Root of the per-job artefact tree: ``{data_dir}/{job_id}/``.
    data_dir: Path = Field(default=Path("./data"))

    database_url: str = "postgresql+psycopg://gridlock:gridlock@postgres:5432/gridlock"
    redis_url: str = "redis://redis:6379/0"

    # --- Extraction tuning -------------------------------------------------
    #: Below this many extractable characters per page, treat it as scanned.
    min_chars_for_digital: int = 20
    #: Raster resolution for OCR and for verification renders.
    render_dpi: int = 300

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
