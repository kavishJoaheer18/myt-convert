"""Test doubles for the consensus gate.

The gate asks whether consensus *detects disagreement*, which is a property of
the mechanism rather than of any particular model's eyesight.  Substituting a
deterministic reader for the VLM isolates exactly that, and keeps the suite
reproducible and free.

The corrupting OCR engine models the failure that actually happens in the field:
a misread at page resolution that a magnified second look gets right.  It
therefore corrupts only the full-page pass and reads crops faithfully — which is
precisely the situation zoom-and-re-ask exists to resolve.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.pipeline.consensus import normalize
from app.vlm.base import CellQuery, CellReading, PageVerdict, VLMProvider


@dataclass
class GroundTruthVLM(VLMProvider):
    """A model that always reads the page correctly.

    Stands in for a vision model that is right about the cells it disputes, so
    the test measures the consensus machinery rather than model accuracy.
    """

    #: (page_number, row, col) -> the value truly on the page.
    truth: dict[tuple[int, int, int], str]
    page_number: int = 1
    name: str = "ground-truth-double"
    #: Every query the provider was asked to verify, for assertions.
    seen: list[CellQuery] = field(default_factory=list)
    crop_reads: int = 0

    def is_available(self) -> bool:
        return True

    def verify_page(self, page_png: bytes, cells: list[CellQuery]) -> PageVerdict:
        self.seen.extend(cells)
        disagreements: list[CellReading] = []

        for cell in cells:
            expected = self.truth.get((self.page_number, cell.row, cell.col))
            if expected is None or normalize(expected) == normalize(cell.value):
                continue
            disagreements.append(
                CellReading(row=cell.row, col=cell.col, text=expected, confidence=0.95)
            )

        return PageVerdict(disagreements=disagreements)

    def read_crop(self, crop_png: bytes) -> CellReading:
        # The crop reader is exercised through the OCR engine in these tests;
        # abstaining here keeps the two votes genuinely independent.
        self.crop_reads += 1
        return CellReading(row=0, col=0, text="", confidence=0.0)


@dataclass
class SilentVLM(VLMProvider):
    """A model that disputes nothing, for the no-disagreement path."""

    name: str = "silent-double"

    def is_available(self) -> bool:
        return True

    def verify_page(self, page_png: bytes, cells: list[CellQuery]) -> PageVerdict:
        return PageVerdict()

    def read_crop(self, crop_png: bytes) -> CellReading:
        return CellReading(row=0, col=0, text="", confidence=0.0)


class CorruptingOcrEngine:
    """Wraps a real OCR engine and misreads chosen values at page resolution.

    Only full-page recognition is corrupted. Crops come back faithfully, which
    is the realistic case: a character misread in a dense page is usually read
    correctly once the region is magnified.
    """

    #: Above this area (in pixels) an image is a page rather than a cell crop.
    PAGE_AREA_PX = 2_000_000

    def __init__(self, inner: object, corruptions: dict[str, str]) -> None:
        self._inner = inner
        self._corruptions = corruptions
        self.applied: list[str] = []

    def recognize(self, image: np.ndarray) -> list:
        detections = self._inner.recognize(image)  # type: ignore[attr-defined]
        if image.size < self.PAGE_AREA_PX:
            return detections

        from dataclasses import replace

        corrupted = []
        for detection in detections:
            replacement = self._corruptions.get(detection.text.strip())
            if replacement is None:
                corrupted.append(detection)
                continue
            self.applied.append(detection.text.strip())
            corrupted.append(replace(detection, text=replacement))
        return corrupted
