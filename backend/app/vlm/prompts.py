"""Prompts and reply parsing shared by every VLM provider.

Both providers ask the same two questions and accept the same answers, so the
wording lives here rather than in each one. A page reviewed by Claude and the
same page reviewed by a local model differ in accuracy, never in what was asked.
"""

from __future__ import annotations

import json
import logging
import re

from app.vlm.base import CellReading, PageVerdict

logger = logging.getLogger(__name__)

PAGE_SYSTEM = """\
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

CROP_SYSTEM = """\
You are reading one magnified cell cropped from a table.

Report exactly the characters visible in the image, preserving thousands
separators, currency symbols, percent signs, leading zeros and letter case. Do
not interpret, reformat, round or explain the value.

Respond with JSON only, no prose:
{"text": "the characters you read", "confidence": 0.0-1.0}
"""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a reply, tolerating a code fence around it.

    Smaller local models are markedly less obedient about "JSON only" than a
    hosted one, so the object is located rather than assumed.
    """
    match = _JSON_BLOCK.search(text)
    if match is None:
        raise ValueError(f"no JSON object in model reply: {text[:200]!r}")
    return json.loads(match.group(0))


def clamp_confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def as_reading(item: object) -> CellReading | None:
    """Build a reading from one model-supplied entry, ignoring malformed ones."""
    if not isinstance(item, dict):
        return None
    try:
        return CellReading(
            row=int(item["row"]),
            col=int(item["col"]),
            text=str(item.get("text", "")),
            confidence=clamp_confidence(item.get("confidence", 0.0)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def verdict_from_payload(parsed: dict) -> PageVerdict:
    """Coerce a parsed reply into a verdict, discarding anything malformed."""
    disagreements = [r for r in map(as_reading, parsed.get("disagreements", [])) if r]
    missing = [r for r in map(as_reading, parsed.get("missing", [])) if r]
    return PageVerdict(disagreements=disagreements, missing=missing)
