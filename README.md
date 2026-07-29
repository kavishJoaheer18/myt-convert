# myt convert

Self-hosted PDF → Excel conversion that keeps the layout. A Mauritius Telecom
service, presented under the myt brand. Upload a PDF, get back
an `.xlsx` whose values sit in the right cells with the fonts, borders, fills,
merged ranges and images of the source — plus per-cell confidence tracking.

## Status

| Phase | Scope | Gate | State |
| ----- | ----- | ---- | ----- |
| 1 | Digital PDFs: classification, word + vector extraction, grid mapping, Excel output, upload UI | `pytest tests/test_phase1.py` at 100% cell accuracy | ✅ passing |
| 2 | Scanned PDFs: OpenCV preprocessing, PaddleOCR, raster rule + figure detection, per-cell confidence | ≥98% on 300 DPI rasters | ✅ passing (100%) |
| 3 | Formatting fidelity: borders, fills, colour, alignment, dates/currency/percentages | formatting assertions + LibreOffice render | ✅ passing |
| 4 | Consensus & verification: dual extraction, zoom-and-re-ask, SSIM diff, review UI | ≥19 of 20 injected corruptions flagged | ✅ passing (20/20) |

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
the grid has to be recovered, in order of trustworthiness:

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

Scanned pages take the same route. OCR produces words in page points and
morphology recovers the rules from the raster, so grid mapping, type inference
and the writer are shared with the digital path — only the certainty differs,
and that rides along as a per-cell confidence score.

Finally, a vision model reviews the finished grid against the page. Where it
disagrees, the cell is re-rasterised from the PDF at 3.5× and put back to both
the OCR engine and the model. A value is overwritten only when both agree
against the original; anything still unsettled goes to the review screen rather
than being guessed at.

## Trying it on a real document

The quickest path — no database, no broker, no containers:

```bash
cd backend && python -m app.cli /path/to/your.pdf
```

It writes `your.xlsx` next to the PDF and prints what it found per page. Add
`--inspect` to see only how each page is classified without converting.

Scanned documents additionally need `pip install -r requirements-ocr.txt`; the
models download themselves on first use.

For the review workflow — the side-by-side view with click-to-fix cells — run
the full stack with `docker compose up --build`.

## Known limitations

- **Scanned justified prose.** OCR reports a justified line in fragments whose
  edges can align across rows well enough to look like columns, so a paragraph
  may come out split. The digital path handles this correctly. Fixing the
  scanned case needs page-region segmentation; the fixture is in the suite,
  marked expected-to-fail with that reason, and still scored.
- **Typography from scans.** A raster says nothing about typeface or weight, so
  bold, italic and font colour are not recovered from scanned pages. Values,
  positions, merges, borders and fills are.
- **Ambiguous dates.** `01/02/2026` is left as text, since the page does not say
  whether the day or the month comes first.

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
