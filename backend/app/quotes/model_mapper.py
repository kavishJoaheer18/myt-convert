"""Asking a local language model which column means what.

Only consulted for pages the synonym rules could not place — a supplier who
labels a column "Vôtre prix" or "Netto" or nothing at all. The common case never
reaches a model, so a batch of familiar quotes costs nothing.

The model is shown the page as a grid of `r,c` addressed cells and asked for
*indices*. It never sees a request to transcribe anything, and its answer cannot
contain a price: whatever it returns, the values are read from the extraction.
That is the same rule the consensus stage follows, for the same reason — a model
that invents a number is far more dangerous than one that admits defeat.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import get_settings
from app.models.grid import SheetGrid
from app.quotes.schema import ColumnMapping, TableLocation

logger = logging.getLogger(__name__)

#: Cells beyond this are dropped from the prompt; a line-item table's header is
#: never hundreds of rows down, and a huge prompt is slow and no more accurate.
MAX_PROMPT_ROWS = 60
MAX_CELL_CHARS = 60

_SYSTEM = """\
You are reading a supplier quotation that has been extracted into a grid of
cells. Each cell is given as r<row>c<column>: <text>.

Identify the table of line items — the rows listing what is being quoted, each
with a price — and report which column holds each field.

Respond with JSON only, no prose:
{"header_row": <row index of the column headings, or null>,
 "first_data_row": <row index of the first line item>,
 "columns": {"ref": <col or null>, "description": <col or null>,
             "qty": <col or null>, "unit_price": <col or null>,
             "discount": <col or null>, "discounted_price": <col or null>,
             "total": <col or null>}}

Rules:
- Report column *numbers*, never the text in them.
- unit_price is the price before any discount; discounted_price is after it;
  total is the line total for the whole quantity.
- Use null for a field the table does not have. Do not guess.
- If there is no line-item table on this page, reply {"first_data_row": null}.
"""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def sheet_to_prompt(sheet: SheetGrid, max_rows: int = MAX_PROMPT_ROWS) -> str:
    """Render a sheet as addressed cells for the model to read."""
    lines: list[str] = []
    for row in range(min(sheet.n_rows, max_rows)):
        cells = sorted(
            (c for c in sheet.cells if c.row == row and c.text.strip()),
            key=lambda c: c.col,
        )
        if not cells:
            continue
        rendered = "  ".join(f"r{c.row}c{c.col}: {c.text[:MAX_CELL_CHARS]}" for c in cells)
        lines.append(rendered)
    return "\n".join(lines)


class OllamaQuoteMapper:
    """Locates a quote's line-item table using a model served by Ollama."""

    def __init__(
        self, base_url: str | None = None, model: str | None = None, timeout: float = 180.0
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.quote_model
        self.timeout = timeout

    def is_available(self) -> bool:
        """Whether Ollama is reachable and the model is pulled."""
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            response.raise_for_status()
            names = {m.get("name", "") for m in response.json().get("models", [])}
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("ollama unavailable", extra={"error": str(exc)})
            return False

        # Ollama reports "qwen2.5:32b"; accept a bare family name too.
        return any(name == self.model or name.startswith(f"{self.model}:") for name in names)

    def __call__(self, sheet: SheetGrid) -> TableLocation | None:
        """Map one sheet, or return None if the model finds no table."""
        prompt = sheet_to_prompt(sheet)
        if not prompt.strip():
            return None

        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    # Ollama constrains the reply to JSON, which small models
                    # need far more than a hosted one does.
                    "format": "json",
                    "options": {"temperature": 0},
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "")
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("quote model call failed", extra={"error": str(exc)})
            return None

        parsed = _parse(content)
        if parsed is None:
            return None

        location = _to_location(parsed, sheet)
        if location is not None:
            logger.info(
                "model located quote table",
                extra={
                    "page": sheet.page_number,
                    "model": self.model,
                    "columns": location.columns.assigned(),
                },
            )
        return location


def _parse(content: str) -> dict | None:
    match = _JSON_BLOCK.search(content or "")
    if match is None:
        logger.warning("quote model returned no JSON", extra={"reply": content[:200]})
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("quote model returned invalid JSON", extra={"reply": content[:200]})
        return None


def _as_index(value: object, limit: int) -> int | None:
    """Coerce a model-supplied index, discarding anything out of range.

    A hallucinated column number would otherwise read a neighbouring value and
    put it under the wrong heading, which is worse than leaving the field empty.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    return index if 0 <= index < limit else None


def _to_location(parsed: dict, sheet: SheetGrid) -> TableLocation | None:
    first_data_row = _as_index(parsed.get("first_data_row"), sheet.n_rows)
    if first_data_row is None:
        return None

    raw_columns = parsed.get("columns")
    if not isinstance(raw_columns, dict):
        return None

    mapping = ColumnMapping(
        **{
            field: _as_index(raw_columns.get(field), sheet.n_cols)
            for field in ColumnMapping.model_fields
        }
    )
    if not mapping.is_usable:
        logger.info("model mapping rejected as unusable", extra={"page": sheet.page_number})
        return None

    return TableLocation(
        page_number=sheet.page_number,
        header_row=_as_index(parsed.get("header_row"), sheet.n_rows),
        first_data_row=first_data_row,
        columns=mapping,
    )
