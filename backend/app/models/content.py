"""Pydantic models describing what was found on a PDF page.

These sit at the boundary between the *extraction* stages (which know about
pdfplumber / PyMuPDF / PaddleOCR) and the *structuring* stages (which know only
about geometry and text).  Every extractor must return a :class:`PageContent`,
whatever library produced it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.geometry import BBox


class PageKind(StrEnum):
    """How a page must be routed through the pipeline."""

    #: A real text layer covers the page content; use the digital extractor.
    DIGITAL = "digital"
    #: No usable text layer; the page must be rasterised and OCR'd.
    SCANNED = "scanned"
    #: Some extractable text, but large image regions likely hide more.
    HYBRID = "hybrid"


class TextSource(StrEnum):
    """Where a piece of text came from, so confidence can be interpreted."""

    DIGITAL = "digital"
    OCR = "ocr"
    VLM = "vlm"
    HUMAN = "human"


class Word(BaseModel):
    """A single whitespace-delimited token with its typography."""

    text: str
    bbox: BBox
    font_name: str = ""
    font_size: float = 0.0
    bold: bool = False
    italic: bool = False
    #: sRGB hex without the leading '#', e.g. "1a1a1a".
    color: str = "000000"
    source: TextSource = TextSource.DIGITAL
    #: 0.0 – 1.0.  Digital extraction is exact, so it reports 1.0.
    confidence: float = 1.0

    @property
    def is_blank(self) -> bool:
        return not self.text.strip()


class Ruling(BaseModel):
    """A straight vector line segment: the backbone of table detection."""

    #: "h" or "v".  Segments that are neither are discarded by the extractor.
    orientation: str
    x0: float
    y0: float
    x1: float
    y1: float
    stroke_width: float = 0.0
    color: str = "000000"

    @property
    def length(self) -> float:
        return abs(self.x1 - self.x0) if self.orientation == "h" else abs(self.y1 - self.y0)

    @property
    def position(self) -> float:
        """The constant coordinate: ``y`` for horizontal, ``x`` for vertical."""
        return self.y0 if self.orientation == "h" else self.x0

    @property
    def span(self) -> tuple[float, float]:
        """The varying coordinate range, always ordered low → high."""
        if self.orientation == "h":
            return (min(self.x0, self.x1), max(self.x0, self.x1))
        return (min(self.y0, self.y1), max(self.y0, self.y1))


class RectDrawing(BaseModel):
    """A filled and/or stroked rectangle, used for cell fills and borders."""

    bbox: BBox
    fill_color: str | None = None
    stroke_color: str | None = None
    stroke_width: float = 0.0


class ImageBlock(BaseModel):
    """An embedded raster image and where it sits on the page."""

    bbox: BBox
    #: Path on disk of the extracted image, relative to the job directory.
    path: str
    width_px: int
    height_px: int
    #: PDF cross-reference number, kept for de-duplication of repeated logos.
    xref: int | None = None


class PageContent(BaseModel):
    """Everything one extractor found on one page."""

    page_number: int = Field(ge=1)
    width: float
    height: float
    kind: PageKind
    rotation: int = 0
    words: list[Word] = Field(default_factory=list)
    rulings: list[Ruling] = Field(default_factory=list)
    rects: list[RectDrawing] = Field(default_factory=list)
    images: list[ImageBlock] = Field(default_factory=list)

    @property
    def bbox(self) -> BBox:
        return BBox(x0=0.0, top=0.0, x1=self.width, bottom=self.height)

    def non_blank_words(self) -> list[Word]:
        return [w for w in self.words if not w.is_blank]
