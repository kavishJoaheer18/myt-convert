"""Turn a generated fixture into its "scanned" counterpart.

Each page is rendered to a raster and re-wrapped as an image-only PDF, which is
exactly what a scanner produces: no text layer, no vector rulings, nothing but
pixels.  The ground truth is unchanged — the same values are on the page — so the
digital and scanned runs are scored against one identical source of truth.

Optional degradations model a real scan: a fraction of a degree of skew from a
sheet fed slightly crooked, and Gaussian sensor noise.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import fitz
import numpy as np
from PIL import Image

from tests.fixtures.ground_truth import ExpectedSheet, Fixture


def _degrade(image: np.ndarray, skew_degrees: float, noise_sigma: float) -> np.ndarray:
    """Apply scanner-like skew and sensor noise."""
    result = Image.fromarray(image)

    if skew_degrees:
        result = result.rotate(
            skew_degrees, resample=Image.BICUBIC, expand=False, fillcolor=(255, 255, 255)
        )

    array = np.asarray(result).astype(np.float32)
    if noise_sigma > 0:
        rng = np.random.default_rng(seed=20260727)
        array = array + rng.normal(0.0, noise_sigma, array.shape)

    return np.clip(array, 0, 255).astype(np.uint8)


def rasterize_fixture(
    fixture: Fixture,
    out_dir: Path,
    dpi: int = 300,
    skew_degrees: float = 0.0,
    noise_sigma: float = 0.0,
    suffix: str = "_scan",
) -> Fixture:
    """Render ``fixture`` to an image-only PDF and return it with the same truth."""
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"{fixture.name}{suffix}.pdf"

    scanned = fitz.open()
    with fitz.open(fixture.pdf_path) as source:
        for page in source:
            pixmap = page.get_pixmap(dpi=dpi, alpha=False, colorspace=fitz.csRGB)
            image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height, pixmap.width, 3
            )

            if skew_degrees or noise_sigma:
                image = _degrade(image, skew_degrees, noise_sigma)

            png_path = out_dir / f"{fixture.name}{suffix}_p{page.number + 1}.png"
            Image.fromarray(image).save(png_path, format="PNG")

            # Keep the original page size so ground-truth geometry still applies.
            new_page = scanned.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, filename=str(png_path))

    scanned.save(output_path)
    scanned.close()

    return replace(
        fixture,
        name=f"{fixture.name}{suffix}",
        pdf_path=output_path,
        sheets=[_without_font_style(sheet) for sheet in fixture.sheets],
        description=f"{fixture.description} (rasterised at {dpi} DPI)",
    )


def _without_font_style(sheet: ExpectedSheet) -> ExpectedSheet:
    """Drop the style expectations a raster genuinely cannot answer.

    A scan carries no font metadata — nothing in the pixels says which typeface
    was used or whether it was bold — so asserting typography against a scanned
    fixture would be testing for something the format does not contain.  Values,
    positions, spans and fills are all still asserted.
    """
    # Picture count is deliberately left alone: figure detection is expected to
    # recover the same images from the raster that the digital path extracted.
    return replace(
        sheet, cells=[replace(cell, assert_style=False) for cell in sheet.cells]
    )
