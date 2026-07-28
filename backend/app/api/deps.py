"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Iterator

from sqlalchemy.orm import Session

from app.models.db import new_session


def get_session() -> Iterator[Session]:
    session = new_session()
    try:
        yield session
    finally:
        session.close()
