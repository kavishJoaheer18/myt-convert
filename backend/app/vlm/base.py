"""The one interface every vision model goes through.

A VLM is never the sole source of a cell's value.  It does three things and no
more: propose structure, vote when the deterministic pipeline is unsure, and
verify a finished page.  Everything a cell contains still has to originate in
text the extractor actually found, which is why the provider's page method
*reviews* an existing grid rather than producing one of its own.

Keeping this to a single small interface is what makes the local and hosted
providers interchangeable, and what lets the tests substitute a deterministic
double for the consensus gate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class CellQuery(BaseModel):
    """One cell put to the model for review."""

    row: int = Field(ge=0)
    col: int = Field(ge=0)
    #: What the deterministic pipeline read.
    value: str
    #: Where the cell sits on the page, in points, so the model can look there.
    x0: float
    top: float
    x1: float
    bottom: float


class CellReading(BaseModel):
    """What the model says a cell actually contains."""

    row: int = Field(ge=0)
    col: int = Field(ge=0)
    text: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PageVerdict(BaseModel):
    """The model's review of one page."""

    #: Cells whose value the model disputes, with what it reads instead.
    disagreements: list[CellReading] = Field(default_factory=list)
    #: Values the model can see that were not in the grid at all.
    missing: list[CellReading] = Field(default_factory=list)

    @property
    def disputed_positions(self) -> set[tuple[int, int]]:
        return {(d.row, d.col) for d in self.disagreements}


class VLMUnavailable(RuntimeError):
    """The configured provider cannot be reached or is not configured."""


class VLMProvider(ABC):
    """A vision model that can review a page and read a cropped cell."""

    #: Short identifier recorded against every verdict, for auditability.
    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider is configured and usable right now."""

    @abstractmethod
    def verify_page(self, page_png: bytes, cells: list[CellQuery]) -> PageVerdict:
        """Review an extracted grid against the rendered page.

        Implementations must return only genuine disagreements.  A provider that
        echoes back every cell would drown the review queue and defeat the point.
        """

    @abstractmethod
    def read_crop(self, crop_png: bytes) -> CellReading:
        """Read a single magnified cell crop.

        Used by the zoom-and-re-ask step, where the disputed region is enlarged
        so both the OCR engine and the model get a second, better look.  The
        returned row and column are ignored; only the text and confidence matter.
        """


def get_provider(name: str | None = None) -> VLMProvider:
    """Construct the configured provider.

    Imported lazily so that neither SDK is a hard dependency of the pipeline.
    """
    from app.config import get_settings

    settings = get_settings()
    chosen = (name or settings.vlm_provider).lower()

    if chosen == "anthropic":
        from app.vlm.anthropic import AnthropicProvider

        return AnthropicProvider()
    if chosen == "ollama":
        from app.vlm.ollama import OllamaProvider

        return OllamaProvider()

    raise VLMUnavailable(f"unknown VLM provider {chosen!r}; expected 'anthropic' or 'ollama'")
