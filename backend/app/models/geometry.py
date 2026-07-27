"""Geometric primitives shared by every pipeline stage.

All coordinates are PDF user-space points (1 pt = 1/72 inch) with the origin at
the **top-left** of the page and ``y`` increasing downwards.  pdfplumber already
reports ``top``/``bottom`` in this convention; PyMuPDF's ``Rect`` does too.  Any
stage that touches a library using bottom-left origin must convert at its own
boundary so that nothing downstream has to care.
"""

from __future__ import annotations

from typing import Iterable

from pydantic import BaseModel, Field, model_validator

# Rendering/measurement constants.
POINTS_PER_INCH: float = 72.0
PIXELS_PER_INCH: float = 96.0
#: Width in pixels of the "0" glyph in Excel's default font (Calibri 11), which
#: is the unit Excel uses for column widths.
EXCEL_CHAR_WIDTH_PX: float = 7.0


class BBox(BaseModel):
    """An axis-aligned rectangle in page points, top-left origin."""

    x0: float
    top: float
    x1: float
    bottom: float

    @model_validator(mode="after")
    def _normalise(self) -> "BBox":
        # Drawing operators happily emit inverted rectangles; normalise once here
        # so no downstream stage has to defend against x1 < x0.
        if self.x1 < self.x0:
            object.__setattr__(self, "x0", self.x1)
            object.__setattr__(self, "x1", self.x0)
        if self.bottom < self.top:
            object.__setattr__(self, "top", self.bottom)
            object.__setattr__(self, "bottom", self.top)
        return self

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def intersection(self, other: "BBox") -> "BBox | None":
        x0 = max(self.x0, other.x0)
        x1 = min(self.x1, other.x1)
        top = max(self.top, other.top)
        bottom = min(self.bottom, other.bottom)
        if x1 <= x0 or bottom <= top:
            return None
        return BBox(x0=x0, top=top, x1=x1, bottom=bottom)

    def overlap_ratio(self, other: "BBox") -> float:
        """Fraction of *self* that lies inside *other* (0.0 – 1.0)."""
        if self.area <= 0:
            return 0.0
        inter = self.intersection(other)
        return 0.0 if inter is None else inter.area / self.area

    def contains_point(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.top <= y <= self.bottom

    def merged(self, other: "BBox") -> "BBox":
        return BBox(
            x0=min(self.x0, other.x0),
            top=min(self.top, other.top),
            x1=max(self.x1, other.x1),
            bottom=max(self.bottom, other.bottom),
        )

    @classmethod
    def union(cls, boxes: Iterable["BBox"]) -> "BBox":
        it = iter(boxes)
        try:
            acc = next(it)
        except StopIteration as exc:  # pragma: no cover - guarded by callers
            raise ValueError("union() requires at least one box") from exc
        for box in it:
            acc = acc.merged(box)
        return acc


def points_to_excel_column_width(points: float) -> float:
    """Convert a column width in PDF points to Excel's character-width unit.

    Excel stores column width as a multiple of the default font's "0" glyph
    advance (7 px at 96 DPI for Calibri 11), so one unit is 7/96 inch = 5.25 pt.
    """
    pixels = points * (PIXELS_PER_INCH / POINTS_PER_INCH)
    return pixels / EXCEL_CHAR_WIDTH_PX


def excel_column_width_to_points(width: float) -> float:
    """Inverse of :func:`points_to_excel_column_width`."""
    pixels = width * EXCEL_CHAR_WIDTH_PX
    return pixels * (POINTS_PER_INCH / PIXELS_PER_INCH)


def points_to_excel_row_height(points: float) -> float:
    """Row heights are already expressed in points by the OOXML format."""
    return points


class Cluster(BaseModel):
    """A 1-D cluster of coordinates produced by the grid mapper."""

    start: float
    end: float
    members: list[float] = Field(default_factory=list)

    @property
    def centre(self) -> float:
        return (self.start + self.end) / 2.0

    @property
    def span(self) -> float:
        return self.end - self.start
