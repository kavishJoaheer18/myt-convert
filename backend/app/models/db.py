"""SQLAlchemy models and the session factory.

Every extracted cell is persisted, not just the ones that end up in dispute.
Phase 2 attaches OCR confidence per cell, and Phase 4's review flow needs the
original value alongside whatever a human corrects it to, so the row has to exist
before anyone asks a question about it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    DONE = "DONE"
    FAILED = "FAILED"


class DiscrepancyStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    page_count: Mapped[int] = mapped_column(Integer, default=0)
    cell_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)

    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    #: Written by the Phase 4 review flow once corrections are applied.
    verified_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    pages: Mapped[list["Page"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="Page.page_number"
    )
    discrepancies: Mapped[list["Discrepancy"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (Index("ix_pages_job_page", "job_id", "page_number", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)

    page_number: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    n_rows: Mapped[int] = mapped_column(Integer, default=0)
    n_cols: Mapped[int] = mapped_column(Integer, default=0)
    width_pt: Mapped[float] = mapped_column(Float, default=0.0)
    height_pt: Mapped[float] = mapped_column(Float, default=0.0)
    #: Raster of the source page, rendered for review and verification.
    render_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    job: Mapped[Job] = relationship(back_populates="pages")
    cells: Mapped[list["Cell"]] = relationship(
        back_populates="page", cascade="all, delete-orphan"
    )


class Cell(Base):
    __tablename__ = "cells"
    __table_args__ = (Index("ix_cells_page_pos", "page_id", "row", "col"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)

    row: Mapped[int] = mapped_column(Integer)
    col: Mapped[int] = mapped_column(Integer)
    row_span: Mapped[int] = mapped_column(Integer, default=1)
    col_span: Mapped[int] = mapped_column(Integer, default=1)

    text: Mapped[str] = mapped_column(Text, default="")
    number_format: Mapped[str] = mapped_column(String(64), default="General")
    #: Where the text came from: digital, ocr, vlm or human.
    source: Mapped[str] = mapped_column(String(16), default="digital")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)

    page: Mapped[Page] = relationship(back_populates="cells")


class Discrepancy(Base):
    """A cell whose value the consensus stage could not settle (Phase 4)."""

    __tablename__ = "discrepancies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    row: Mapped[int] = mapped_column(Integer)
    col: Mapped[int] = mapped_column(Integer)

    deterministic_value: Mapped[str] = mapped_column(Text, default="")
    vlm_value: Mapped[str] = mapped_column(Text, default="")
    resolved_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=DiscrepancyStatus.OPEN, index=True)

    #: Crop of the disputed region, shown in the review UI and kept as training
    #: evidence once a human decides.
    crop_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    job: Mapped[Job] = relationship(back_populates="discrepancies")


class QuoteBatch(Base):
    """A set of supplier quotes extracted into one template workbook.

    Deliberately its own table rather than a flag on Job: create_all can add a
    table to a live database but cannot alter one, so a new table deploys onto
    an existing installation without a migration.
    """

    __tablename__ = "quote_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Newline-separated source filenames, in upload order.
    filenames: Mapped[str] = mapped_column(Text, default="")
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    #: Files whose line items could be read.
    files_read: Mapped[int] = mapped_column(Integer, default=0)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    #: Anything the operator should check, one per line.
    warnings: Mapped[str] = mapped_column(Text, default="")

    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Correction(Base):
    """A persisted human correction: ``(crop, wrong value, corrected value)``."""

    __tablename__ = "corrections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    row: Mapped[int] = mapped_column(Integer)
    col: Mapped[int] = mapped_column(Integer)

    crop_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    wrong_value: Mapped[str] = mapped_column(Text, default="")
    corrected_value: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """The process-wide engine, built on first use.

    Deliberately not created at import time: importing a model should not open a
    connection pool, and the URL has to be readable from the environment after
    the module graph is already loaded.
    """
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True, future=True)
    return _engine


def new_session() -> Session:
    """A fresh session bound to the shared engine."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _session_factory()


def reset_engine() -> None:
    """Drop the cached engine so a new database URL takes effect (tests only)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def init_db() -> None:
    """Create any missing tables.

    Alembic owns migrations for a real deployment; this keeps a fresh
    docker-compose stack usable without a separate migration step.
    """
    Base.metadata.create_all(bind=get_engine())
