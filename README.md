# GridLock

Self-hosted PDF → Excel conversion that keeps the layout. Upload a PDF, get back
an `.xlsx` whose values sit in the right cells with the fonts, borders, fills,
merged ranges and images of the source — plus per-cell confidence tracking.

## Status

| Phase | Scope | Gate | State |
| ----- | ----- | ---- | ----- |
| 1 | Digital PDFs: classification, word + vector extraction, grid mapping, Excel output, upload UI | `pytest tests/test_phase1.py` at 100% cell accuracy | ✅ passing |
| 2 | Scanned PDFs: OpenCV preprocessing, PaddleOCR, raster rule + figure detection, per-cell confidence | ≥98% on 300 DPI rasters | ✅ passing (100%) |
| 3 | Formatting fidelity: borders, fills, colour, alignment, dates/currency/percentages | formatting assertions + LibreOffice render | ✅ passing |
| 4 | Consensus & verification: dual extraction, zoom-and-re-ask, SSIM diff, review UI | ≥19 of 20 injected corruptions flagged | not started |

## Running the stack

```bash
docker compose up --build
```

The UI is on http://localhost:3000 and the API on http://localhost:8000
(interactive docs at `/docs`).

## Running the tests

The suite generates its own fixtures, so there is nothing to download.

```bash
cd backend && python -m pytest tests/
```

Every run ends with a cell-accuracy table scored against the fixtures' ground
truth.

Two checks need more than the core dependencies:

```bash
docker build --target verify -t gridlock-verify backend && docker run --rm gridlock-verify
```

That runs the Phase 3 suite against LibreOffice, which renders each produced
workbook back to PDF — the only way to know a real spreadsheet application
accepts it. The image carries no OCR stack, so it also proves the digital path
runs without OpenCV or PaddlePaddle. The Phase 2 OCR gate needs
`requirements-ocr.txt` installed and takes about ten minutes on CPU.

## How it works

A PDF has no cells — only glyphs at coordinates and lines drawn between them, so
the grid has to be recovered. GridLock does that in order of trustworthiness:

1. **Ruling lines.** If the producer drew a table border, its segments *are* the
   grid. Collinear fragments are reassembled first, since tables are usually
   stroked cell by cell.
2. **Whitespace columns.** For borderless tables, a vertical corridor that stays
   empty across most rows is a column separator. Only rows that already look like
   table rows get a vote, so a full-width heading cannot veto every separator
   beneath it.
3. **Text lines.** Rows otherwise follow the visual lines of text.

Merged cells come from the borders around them rather than from how wide their
text is, which is what lets a heading merged across four columns survive as one
value. Values are typed only when a number format exists that displays them
back character for character.

## Layout

```
backend/
  app/api/        FastAPI routes
  app/pipeline/   classify, extract, gridmap, excel_writer, images, types
  app/models/     SQLAlchemy tables, pydantic schemas, geometry, grid model
  app/vlm/        pluggable VLM providers (Phase 4)
  app/worker.py   Celery tasks
  tests/          per-phase gates and the fixture generator
frontend/         Next.js 14 upload, job list and review views
```

## Configuration

Copy `.env.example` to `.env`. Everything has a working default except
`ANTHROPIC_API_KEY`, which Phase 4's consensus stage needs.

Design decisions that were not fully specified are recorded in
[ASSUMPTIONS.md](ASSUMPTIONS.md).
