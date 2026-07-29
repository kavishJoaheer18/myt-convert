"""Pydantic schemas for the HTTP boundary.

Kept separate from the SQLAlchemy models so the wire format can stay stable while
the storage layer changes underneath it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.db import DiscrepancyStatus, JobStatus


class JobSummary(BaseModel):
    """What the job list shows for each conversion."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    status: JobStatus
    page_count: int
    cell_count: int
    created_at: datetime
    updated_at: datetime


class PageSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_number: int
    kind: str
    n_rows: int
    n_cols: int
    width_pt: float
    height_pt: float


class DiscrepancyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    page_number: int
    row: int
    col: int
    deterministic_value: str
    vlm_value: str
    resolved_value: str | None
    status: DiscrepancyStatus
    confidence: float


class JobDetail(JobSummary):
    """Everything the job page needs, including why it failed if it did."""

    error: str | None = None
    duration_ms: float = 0.0
    has_output: bool = False
    has_verified_output: bool = False
    pages: list[PageSummary] = Field(default_factory=list)
    discrepancies: list[DiscrepancyOut] = Field(default_factory=list)


class CellOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row: int
    col: int
    row_span: int
    col_span: int
    text: str
    number_format: str
    source: str
    confidence: float


class SheetOut(BaseModel):
    """One page's cells, for the side-by-side review view."""

    page_number: int
    n_rows: int
    n_cols: int
    cells: list[CellOut] = Field(default_factory=list)


class CellCorrection(BaseModel):
    """A single human fix submitted from the review UI."""

    page_number: int = Field(ge=1)
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    value: str


class ReviewRequest(BaseModel):
    corrections: list[CellCorrection] = Field(default_factory=list)
    #: Mark the job DONE even if open discrepancies remain.
    accept_remaining: bool = False


class ReviewResponse(BaseModel):
    job_id: str
    status: JobStatus
    applied: int
    remaining_discrepancies: int


class JobCreated(BaseModel):
    id: str
    status: JobStatus


class QuoteBatchCreated(BaseModel):
    id: str
    status: JobStatus


class QuoteBatchSummary(BaseModel):
    """What the quote batch list and detail views show."""

    id: str
    status: JobStatus
    filenames: list[str] = Field(default_factory=list)
    file_count: int = 0
    files_read: int = 0
    row_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    duration_ms: float = 0.0
    has_output: bool = False
    created_at: datetime
