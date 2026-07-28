"""Anthropic implementation of :class:`VLMProvider`."""

from __future__ import annotations

import base64
import json
import logging
import re

from app.config import get_settings
from app.vlm.base import CellQuery, CellReading, PageVerdict, VLMProvider, VLMUnavailable

logger = logging.getLogger(__name__)

#: Cap the review payload; a page with more cells than this is split.
MAX_CELLS_PER_CALL = 300
_MAX_TOKENS = 4096

_PAGE_SYSTEM = """\
You are verifying a table extracted from a scanned or digital page.

You will receive an image of the page and a JSON list of cells that were
extracted from it. Each cell has a row, a col, the value that was extracted, and
the bounding box (x0, top, x1, bottom) in PDF points measuring from the page's
top-left corner.

Your job is to report ONLY the cells where the extracted value does not match
what the image actually shows at that bounding box.

Rules:
- Report a disagreement only when you are confident the extracted value is
  wrong. Do not report differences in surrounding whitespace.
- Compare the visible characters exactly, including thousands separators,
  currency symbols, percent signs and leading zeros.
- If a value is correct, say nothing about it.
- Also list any clearly visible value that is missing from the list entirely.

Respond with JSON only, no prose, in exactly this shape:
{"disagreements": [{"row": 0, "col": 0, "text": "what you actually read",
                    "confidence": 0.0-1.0}],
 "missing": [{"row": 0, "col": 0, "text": "value", "confidence": 0.0-1.0}]}
"""

_CROP_SYSTEM = """\
You are reading one magnified cell cropped from a table.

Report exactly the characters visible in the image, preserving thousands
separators, currency symbols, percent signs, leading zeros and letter case. Do
not interpret, reformat, round or explain the value.

Respond with JSON only, no prose:
{"text": "the characters you read", "confidence": 0.0-1.0}
"""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict:
    """Pull the JSON object out of a reply, tolerating a code fence around it."""
    match = _JSON_BLOCK.search(text)
    if match is None:
        raise ValueError(f"no JSON object in model reply: {text[:200]!r}")
    return json.loads(match.group(0))


class AnthropicProvider(VLMProvider):
    """Reads pages and crops with a Claude vision model."""

    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.anthropic_api_key
        self._model = model or settings.vlm_model
        self._client: object | None = None

    def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_client(self) -> object:
        if self._client is None:
            if not self._api_key:
                raise VLMUnavailable("ANTHROPIC_API_KEY is not set")
            try:
                from anthropic import Anthropic
            except ImportError as exc:  # pragma: no cover - dependency is pinned
                raise VLMUnavailable("the anthropic package is not installed") from exc
            self._client = Anthropic(api_key=self._api_key)
        return self._client

    def _ask(self, system: str, image_png: bytes, prompt: str) -> dict:
        client = self._get_client()
        encoded = base64.standard_b64encode(image_png).decode("ascii")

        response = client.messages.create(  # type: ignore[attr-defined]
            model=self._model,
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )

        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        return _extract_json(text)

    def verify_page(self, page_png: bytes, cells: list[CellQuery]) -> PageVerdict:
        if not cells:
            return PageVerdict()

        disagreements: list[CellReading] = []
        missing: list[CellReading] = []

        # A very dense page is split so the payload stays within a sane size and
        # the model's attention is not spread over hundreds of boxes at once.
        for start in range(0, len(cells), MAX_CELLS_PER_CALL):
            batch = cells[start : start + MAX_CELLS_PER_CALL]
            payload = json.dumps([c.model_dump() for c in batch], separators=(",", ":"))

            try:
                parsed = self._ask(
                    _PAGE_SYSTEM, page_png, f"Cells extracted from this page:\n{payload}"
                )
            except (ValueError, json.JSONDecodeError) as exc:
                # A malformed reply must not fail the conversion; it just means
                # this page gets no second opinion.
                logger.warning("unusable VLM page reply", extra={"error": str(exc)})
                continue

            for item in parsed.get("disagreements", []):
                reading = _as_reading(item)
                if reading is not None:
                    disagreements.append(reading)
            for item in parsed.get("missing", []):
                reading = _as_reading(item)
                if reading is not None:
                    missing.append(reading)

        logger.info(
            "vlm page verdict",
            extra={
                "provider": self.name,
                "cells": len(cells),
                "disagreements": len(disagreements),
                "missing": len(missing),
            },
        )
        return PageVerdict(disagreements=disagreements, missing=missing)

    def read_crop(self, crop_png: bytes) -> CellReading:
        try:
            parsed = self._ask(_CROP_SYSTEM, crop_png, "Read this cell.")
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("unusable VLM crop reply", extra={"error": str(exc)})
            return CellReading(row=0, col=0, text="", confidence=0.0)

        return CellReading(
            row=0,
            col=0,
            text=str(parsed.get("text", "")),
            confidence=_clamp(parsed.get("confidence", 0.0)),
        )


def _clamp(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _as_reading(item: object) -> CellReading | None:
    """Build a reading from one model-supplied entry, ignoring malformed ones."""
    if not isinstance(item, dict):
        return None
    try:
        return CellReading(
            row=int(item["row"]),
            col=int(item["col"]),
            text=str(item.get("text", "")),
            confidence=_clamp(item.get("confidence", 0.0)),
        )
    except (KeyError, TypeError, ValueError):
        return None
