# Assumptions

Decisions taken where the brief was genuinely ambiguous. Each records what was
unclear, what was chosen, and why — so a later reader can overturn one without
re-deriving the reasoning.

## Phase 1 — digital PDFs

### A1. The grid is anchored to page content, not to the paper
A PDF page has margins; a worksheet does not. Anchoring column A to the left
edge of the paper would put a 56 pt empty column in front of every document.
The grid is therefore anchored to the bounding box of the page's content (text,
images and table rulings), so content starts at A1 — which is also what a person
transcribing the page would do.

### A2. Vertical whitespace stretches rows rather than creating empty ones
The gap between two blocks is absorbed by putting the row boundary at the
midpoint of the gap, instead of emitting a spacer row. This keeps vertical
proportions without inventing rows the source never had. Empty rows that are
genuinely part of a ruled table are still preserved, because they come from the
ruling structure rather than from whitespace.

### A3. Columns are global to the sheet; tables span the sub-columns they cover
Excel allows one column structure per worksheet. When a page holds two tables
with different column widths, the sheet uses the union of both edge sets and each
table's cells span the sub-columns they cover. Splitting the page across two
worksheets would break the "one worksheet per page" rule in the brief.

### A4. A merged cell is defined by its borders, not by how wide its text is
Where a row is crossed by vertical rulings, those rulings delimit its cells and
nothing else does. This is what lets a heading merged across four columns survive
as one value rather than being torn along a column grid it deliberately ignores.
Outside ruled regions, a cell's span falls back to which columns its text
overlaps.

### A5. Type inference must never change what the reader sees
A value is typed only when a number format exists that renders it back to the
original characters. `1,234.50` becomes `1234.5` with format `#,##0.00`; `007`
stays text, because typing it would silently drop a leading zero that is probably
part of an identifier. Phase 1 covers plain and thousands-separated numbers;
dates, currency and percentages arrive in Phase 3.

### A6. Scanned pages fail loudly in Phase 1
Until the OCR path exists, a page with no text layer raises
`ScannedPageNotSupportedError` rather than producing an empty sheet. A silent
empty sheet looks like a successful conversion that merely lost the data.

### A7. Sheet naming
One worksheet per page, named `Sheet1` for a single-page document and `Page N`
otherwise. Excel's 31-character limit and its ban on `[]:*?/\` are enforced in
the model, and duplicate names get a numeric suffix.

### A8. Coordinates are top-left origin throughout
pdfplumber and PyMuPDF both report top-left-origin coordinates, so no conversion
is needed between them. Any future extractor using a bottom-left origin must
convert at its own boundary. reportlab (fixtures only) is bottom-left and does
convert at its boundary.

### A9. Page-level coordinate offsets are not handled
A PDF whose CropBox is offset from its MediaBox could make pdfplumber and
PyMuPDF disagree about absolute positions. No fixture exercises this and no
real-world case has been observed; it is left until one appears.

## Cross-cutting

### A10. Accuracy counts spurious cells as errors
The reported figure is `matched / (expected + extra)`. Scoring only the expected
cells would let a converter that scattered extra values across the sheet still
report a perfect result.

### A11. The score is measured on the saved workbook
Fixtures are scored by reading the `.xlsx` back from disk and rendering each cell
the way Excel would, so what is measured is the file a user downloads rather than
an in-memory structure that might not survive serialisation.
