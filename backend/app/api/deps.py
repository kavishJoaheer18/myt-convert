"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Iterator

from sqlalchemy.orm import Session

from app.models.db import SessionLocal


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
