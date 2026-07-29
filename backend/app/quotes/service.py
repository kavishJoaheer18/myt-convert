"""Running a batch of quotes end to end.

Takes the PDFs of a batch, extracts each one, and writes them all into a single
template workbook. One quote failing does not lose the rest — the batch reports
what it could not read and produces the rows it could.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings
from app.pipeline.convert import build_document_grid, extract_pages
from app.quotes.extract import extract_quote
from app.quotes.schema import QuoteExtraction
from app.quotes.workbook import write_quote_workbook

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    output_path: Path
    extractions: list[QuoteExtraction] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    rows: int = 0
    duration_ms: float = 0.0

    @property
    def files_read(self) -> int:
        return len(self.extractions)

    @property
    def warnings(self) -> list[str]:
        return [
            f"{extraction.source_file}: {warning}"
            for extraction in self.extractions
            for warning in extraction.warnings
        ]


def _build_mapper():
    """The model fallback, if one is configured and actually reachable.

    Returns None when unavailable, which simply means unfamiliar layouts are
    reported rather than mapped — the batch still runs.
    """
    settings = get_settings()
    if not settings.enable_quote_model:
        return None

    from app.quotes.model_mapper import OllamaQuoteMapper

    mapper = OllamaQuoteMapper()
    if not mapper.is_available():
        logger.info(
            "quote model not available; using rules only",
            extra={"model": mapper.model, "url": mapper.base_url},
        )
        return None
    return mapper


def run_batch(pdf_paths: list[Path], output_path: Path, work_dir: Path) -> BatchResult:
    """Extract every quote in ``pdf_paths`` into one template workbook."""
    started = time.perf_counter()
    mapper = _build_mapper()
    result = BatchResult(output_path=output_path)

    for index, pdf_path in enumerate(pdf_paths):
        name = pdf_path.name
        try:
            pages = extract_pages(pdf_path, work_dir / "images" / str(index))
            document = build_document_grid(f"quote-{index}", pages)
            extraction = extract_quote(document, name, mapper=mapper)
            result.extractions.append(extraction)
        except Exception as exc:  # noqa: BLE001 - one bad file must not lose the batch
            logger.exception("quote extraction failed", extra={"file": name})
            result.failures.append((name, f"{type(exc).__name__}: {exc}"))

    _, rows = write_quote_workbook(result.extractions, output_path)
    result.rows = rows
    result.duration_ms = (time.perf_counter() - started) * 1000.0

    logger.info(
        "quote batch complete",
        extra={
            "files": len(pdf_paths),
            "read": result.files_read,
            "rows": rows,
            "failed": len(result.failures),
            "duration_ms": round(result.duration_ms, 1),
        },
    )
    return result
