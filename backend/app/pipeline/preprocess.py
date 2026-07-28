"""Raster preprocessing for scanned pages.

A scan arrives skewed, speckled and unevenly lit.  Each step here exists to make
the *next* stage's job tractable: deskewing so that text lines and table rules
are axis-aligned (every downstream stage assumes that), denoising so speckle is
not mistaken for glyphs, and binarising so morphology can isolate the rules.

Everything operates on numpy arrays and nothing here imports OCR, so it can be
tested without loading a recognition model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from app.models.geometry import POINTS_PER_INCH

logger = logging.getLogger(__name__)

#: Rotations beyond this are page orientation problems, not scanner skew, and
#: correcting them by shear would do more harm than leaving them alone.
MAX_DESKEW_DEGREES = 15.0
#: Below this the correction is within measurement noise.
MIN_DESKEW_DEGREES = 0.08


@dataclass(frozen=True)
class PreprocessResult:
    """The processed page plus what had to be done to it."""

    #: Deskewed greyscale image, the reference for OCR and for cropping.
    gray: np.ndarray
    #: Binary image (text is white on black) used for morphology.
    binary: np.ndarray
    skew_degrees: float
    dpi: int

    @property
    def height(self) -> int:
        return int(self.gray.shape[0])

    @property
    def width(self) -> int:
        return int(self.gray.shape[1])

    def px_to_pt(self, pixels: float) -> float:
        return pixels * POINTS_PER_INCH / self.dpi

    def pt_to_px(self, points: float) -> float:
        return points * self.dpi / POINTS_PER_INCH


def to_grayscale(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)


def _weighted_median(values: list[float], weights: list[float]) -> float:
    order = np.argsort(np.asarray(values))
    sorted_values = np.asarray(values, dtype=float)[order]
    cumulative = np.cumsum(np.asarray(weights, dtype=float)[order])
    if cumulative[-1] <= 0:
        return 0.0
    index = int(np.searchsorted(cumulative, cumulative[-1] / 2.0))
    return float(sorted_values[min(index, len(sorted_values) - 1)])


def estimate_skew(binary: np.ndarray) -> float:
    """Estimate page skew in degrees, positive meaning counter-clockwise.

    Hough is run over Canny *edges* rather than the filled binary.  A solid
    region — a logo, a chart, a dark photo — contains an unlimited supply of
    near-horizontal chords, and feeding those to Hough buries the handful of real
    lines under hundreds of spurious ones; a single image block was enough to
    swing the estimate by more than two degrees.  Edge detection reduces that
    block to its outline, which contributes the two horizontal edges it actually
    has.

    Angles are combined by a length-weighted median, so a table rule spanning the
    page outvotes a short fragment, and a few bad detections cannot drag the
    result the way a mean would.
    """
    height, width = binary.shape[:2]
    min_length = max(60, width // 8)

    edges = cv2.Canny(binary, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 720.0,
        threshold=120,
        minLineLength=min_length,
        maxLineGap=12,
    )
    if lines is None:
        return 0.0

    angles: list[float] = []
    weights: list[float] = []
    for x0, y0, x1, y1 in lines[:, 0]:
        dx, dy = float(x1 - x0), float(y1 - y0)
        if abs(dx) < 1.0:
            continue
        angle = float(np.degrees(np.arctan2(dy, dx)))
        if abs(angle) <= MAX_DESKEW_DEGREES:
            angles.append(angle)
            weights.append(float(np.hypot(dx, dy)))

    # Too little evidence to justify rotating the page at all.
    if len(angles) < 3:
        return 0.0
    return _weighted_median(angles, weights)


def rotate(image: np.ndarray, degrees: float, border: int) -> np.ndarray:
    """Rotate about the image centre, padding with ``border``."""
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), degrees, 1.0)
    return cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border,
    )


def binarize(gray: np.ndarray) -> np.ndarray:
    """Produce a white-on-black binary image.

    Otsu handles the evenly-lit case well and is stable; adaptive thresholding
    rescues pages with a lighting gradient.  The two are combined so that a
    stroke either method is confident about survives.
    """
    otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 41, 12
    )
    return cv2.bitwise_or(otsu, adaptive)


def denoise(gray: np.ndarray) -> np.ndarray:
    """Remove scanner speckle without softening glyph edges.

    A median blur is used rather than a Gaussian because salt-and-pepper speckle
    is what scans actually produce, and the median leaves stroke edges intact.
    """
    return cv2.medianBlur(gray, 3)


def remove_speck_components(binary: np.ndarray, min_area: int = 6) -> np.ndarray:
    """Drop connected components too small to be part of any glyph."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if count <= 1:
        return binary

    keep = np.zeros(count, dtype=bool)
    keep[0] = False
    for index in range(1, count):
        keep[index] = stats[index, cv2.CC_STAT_AREA] >= min_area
    return np.where(keep[labels], 255, 0).astype(np.uint8)


def preprocess_page(image: np.ndarray, dpi: int) -> PreprocessResult:
    """Deskew, denoise and binarise one rendered page."""
    gray = to_grayscale(image)
    cleaned = denoise(gray)

    skew = estimate_skew(binarize(cleaned))
    if abs(skew) >= MIN_DESKEW_DEGREES:
        # Rotating the greyscale (not the binary) keeps antialiasing for OCR.
        cleaned = rotate(cleaned, skew, border=255)
    else:
        skew = 0.0

    binary = remove_speck_components(binarize(cleaned))

    logger.info(
        "preprocessed page",
        extra={"skew_degrees": round(skew, 3), "dpi": dpi, "shape": list(cleaned.shape)},
    )
    return PreprocessResult(gray=cleaned, binary=binary, skew_degrees=skew, dpi=dpi)
