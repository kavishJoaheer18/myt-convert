"""Extraction for pages with no usable text layer.

The design goal is that nothing downstream can tell how a page arrived.  OCR
produces :class:`Word` objects in page points and morphology recovers
:class:`Ruling` objects from the same raster, so the grid mapper, the type
inference and the Excel writer are shared verbatim with the digital path.

What differs is certainty: every word carries the recogniser's confidence, and
that confidence propagates to the cell so Phase 4 knows where to look.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
from PIL import Image

from app.models.content import ImageBlock, PageContent, PageKind, Ruling, TextSource, Word
from app.models.geometry import BBox
from app.pipeline.preprocess import PreprocessResult, preprocess_page
from app.pipeline.raster_lines import detect_figures, detect_rulings, sample_cell_fills
from app.pipeline.render import PageRender

logger = logging.getLogger(__name__)

#: A text-line box is taller than its font: cap height plus descender plus
#: padding. Empirically the glyphs occupy about this share of the box.
FONT_SIZE_FROM_BOX_HEIGHT = 0.78
#: Detections below this confidence are kept but flagged; below this the value
#: is more likely noise than text.
MIN_KEEP_CONFIDENCE = 0.30


@dataclass(frozen=True)
class OcrDetection:
    """One recognised text line, in pixels of the preprocessed page."""

    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    confidence: float


@runtime_checkable
class OcrEngine(Protocol):
    """Anything that can turn a page image into text lines with boxes."""

    def recognize(self, image: np.ndarray) -> list[OcrDetection]:
        """Return every text line found in ``image``, in pixel coordinates."""
        ...


class PaddleOcrEngine:
    """PaddleOCR (PP-OCRv5) text detection and recognition.

    The model is loaded on first use and reused, because construction costs
    several seconds and a document has many pages.
    """

    def __init__(self, lang: str = "en", use_gpu: bool = False) -> None:
        self._lang = lang
        self._use_gpu = use_gpu
        self._ocr: object | None = None

    def _engine(self) -> object:
        if self._ocr is None:
            # Imported lazily: the API image does not install PaddleOCR.
            from paddleocr import PaddleOCR

            logger.info("loading PaddleOCR", extra={"lang": self._lang})
            self._ocr = PaddleOCR(
                lang=self._lang,
                # Orientation and unwarping are handled by our own preprocessing,
                # and running them twice costs time and can fight each other.
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                device="gpu" if self._use_gpu else "cpu",
            )
        return self._ocr

    def recognize(self, image: np.ndarray) -> list[OcrDetection]:
        engine = self._engine()
        # PaddleOCR expects three-channel input; the preprocessed page is grey.
        if image.ndim == 2:
            image = np.stack([image] * 3, axis=-1)

        raw = engine.predict(input=image)  # type: ignore[attr-defined]
        detections: list[OcrDetection] = []

        for page_result in raw:
            texts = page_result.get("rec_texts", [])
            scores = page_result.get("rec_scores", [])
            polys = page_result.get("rec_polys", page_result.get("dt_polys", []))

            for text, score, poly in zip(texts, scores, polys):
                if not str(text).strip():
                    continue
                points = np.asarray(poly, dtype=float).reshape(-1, 2)
                detections.append(
                    OcrDetection(
                        text=str(text),
                        x0=float(points[:, 0].min()),
                        top=float(points[:, 1].min()),
                        x1=float(points[:, 0].max()),
                        bottom=float(points[:, 1].max()),
                        confidence=float(score),
                    )
                )

        logger.info("ocr recognised page", extra={"detections": len(detections)})
        return detections


def _split_detection_at_rulings(
    detection: OcrDetection, verticals_px: list[tuple[float, float, float]]
) -> list[OcrDetection]:
    """Split a detection that straddles a table border.

    OCR occasionally merges two cells across a thin rule.  The rule is hard
    evidence of a boundary, so the box is cut at it and the text is divided in
    proportion to where the cut falls — the same assumption a monospaced estimate
    would make, and close enough for the grid mapper to place each part in the
    right column.

    A ruling only counts if it spans the detection *vertically* as well.  Without
    that check, the column borders of a table lower down the page would slice a
    heading above it into fragments.
    """
    crossings = sorted(
        x
        for x, y_top, y_bottom in verticals_px
        if detection.x0 + 2.0 < x < detection.x1 - 2.0
        and y_top <= detection.top + 2.0
        and y_bottom >= detection.bottom - 2.0
    )
    if not crossings or not detection.text:
        return [detection]

    width = detection.x1 - detection.x0
    pieces: list[OcrDetection] = []
    edges = [detection.x0, *crossings, detection.x1]

    for index in range(len(edges) - 1):
        start, end = edges[index], edges[index + 1]
        char_start = int(round(len(detection.text) * (start - detection.x0) / width))
        char_end = int(round(len(detection.text) * (end - detection.x0) / width))
        text = detection.text[char_start:char_end].strip()
        if not text:
            continue
        pieces.append(
            OcrDetection(
                text=text,
                x0=start,
                top=detection.top,
                x1=end,
                bottom=detection.bottom,
                confidence=detection.confidence,
            )
        )

    return pieces or [detection]


def _detection_to_word(detection: OcrDetection, processed: PreprocessResult) -> Word:
    box = BBox(
        x0=processed.px_to_pt(detection.x0),
        top=processed.px_to_pt(detection.top),
        x1=processed.px_to_pt(detection.x1),
        bottom=processed.px_to_pt(detection.bottom),
    )
    return Word(
        text=detection.text.strip(),
        bbox=box,
        # A scan carries no font metadata; size is inferred from the box and the
        # family is left to the workbook default rather than being invented.
        font_name="Calibri",
        font_size=round(box.height * FONT_SIZE_FROM_BOX_HEIGHT, 1),
        source=TextSource.OCR,
        confidence=detection.confidence,
    )


def _extract_figures(
    processed: PreprocessResult,
    render: PageRender,
    detections: list[OcrDetection],
    rulings: list[Ruling],
    image_dir: Path,
) -> list[ImageBlock]:
    """Crop picture regions out of the page raster and save them."""
    boxes = detect_figures(
        processed.binary,
        processed.dpi,
        [(d.x0, d.top, d.x1, d.bottom) for d in detections],
        rulings=rulings,
    )
    if not boxes:
        return []

    image_dir.mkdir(parents=True, exist_ok=True)
    source = processed.gray if render.image.ndim == 2 else render.image
    blocks: list[ImageBlock] = []

    for index, (x, y, w, h) in enumerate(boxes):
        # Crop from the deskewed page so the saved figure is upright, but fall
        # back to the original raster if shapes diverge.
        crop_source = source if source.shape[:2] == processed.gray.shape[:2] else processed.gray
        crop = crop_source[y : y + h, x : x + w]
        if crop.size == 0:
            continue

        path = image_dir / f"p{render.page_number}_fig{index}.png"
        Image.fromarray(crop).save(path, format="PNG")

        blocks.append(
            ImageBlock(
                bbox=BBox(
                    x0=processed.px_to_pt(x),
                    top=processed.px_to_pt(y),
                    x1=processed.px_to_pt(x + w),
                    bottom=processed.px_to_pt(y + h),
                ),
                path=str(path),
                width_px=int(w),
                height_px=int(h),
            )
        )

    return blocks


def extract_page_ocr(
    render: PageRender,
    engine: OcrEngine,
    dpi: int | None = None,
    image_dir: Path | None = None,
) -> PageContent:
    """Preprocess, OCR and structure one rasterised page."""
    resolution = dpi or render.dpi
    processed = preprocess_page(render.image, resolution)

    rulings: list[Ruling] = detect_rulings(processed.binary, resolution)
    verticals_px = [
        (
            processed.pt_to_px(r.position),
            processed.pt_to_px(r.span[0]),
            processed.pt_to_px(r.span[1]),
        )
        for r in rulings
        if r.orientation == "v"
    ]

    detections = engine.recognize(processed.gray)
    kept = [d for d in detections if d.confidence >= MIN_KEEP_CONFIDENCE]
    for discarded in (d for d in detections if d.confidence < MIN_KEEP_CONFIDENCE):
        logger.debug(
            "discarding low-confidence detection",
            extra={"text": discarded.text, "confidence": discarded.confidence},
        )

    words: list[Word] = []
    for detection in kept:
        for piece in _split_detection_at_rulings(detection, verticals_px):
            word = _detection_to_word(piece, processed)
            if word.text:
                words.append(word)

    images = (
        _extract_figures(processed, render, kept, rulings, image_dir)
        if image_dir is not None
        else []
    )

    logger.info(
        "extracted scanned page",
        extra={
            "page": render.page_number,
            "words": len(words),
            "rulings": len(rulings),
            "figures": len(images),
            "mean_confidence": round(
                float(np.mean([w.confidence for w in words])) if words else 0.0, 4
            ),
        },
    )

    rects = (
        sample_cell_fills(
            processed.color,
            rulings,
            resolution,
            # Regions already recovered as pictures must not also become a
            # background colour behind the cell they sit in.
            exclude_px=[
                (
                    int(processed.pt_to_px(image.bbox.x0)),
                    int(processed.pt_to_px(image.bbox.top)),
                    int(processed.pt_to_px(image.bbox.width)),
                    int(processed.pt_to_px(image.bbox.height)),
                )
                for image in images
            ],
        )
        if processed.color is not None
        else []
    )

    return PageContent(
        page_number=render.page_number,
        width=render.width_pt,
        height=render.height_pt,
        kind=PageKind.SCANNED,
        words=words,
        rulings=rulings,
        rects=rects,
        images=images,
    )


_WHITESPACE = re.compile(r"\s+")


def normalize_ocr_text(text: str) -> str:
    """Collapse the whitespace OCR sprinkles into single spaces."""
    return _WHITESPACE.sub(" ", text).strip()
