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

## Phase 2 — scanned PDFs

### A12. OCR feeds the same grid mapper as the digital path
Recognised text becomes `Word` objects in page points and morphology turns the
raster's rules into `Ruling` objects, so grid mapping, type inference and the
Excel writer are shared verbatim between the two paths. Nothing downstream knows
which way a page arrived. What differs is certainty: every OCR word carries the
recogniser's confidence, and that propagates to the cell.

### A13. Table structure comes from detected rules, not PP-StructureV3's HTML
The brief named PP-StructureV3 for "text + table structure". Text recognition
uses PaddleOCR (PP-OCRv5). For *structure*, morphological rule detection is used
instead of PP-StructureV3's table branch, because the latter emits HTML whose
cells must then be re-associated with page coordinates, while the writer needs
coordinate-anchored cells. Detecting the rules directly gives that without a
lossy round trip, and it reuses the Phase 1 grid mapper unchanged — including
merged-cell detection, which the HTML path would have to reimplement. If a
borderless scanned table ever fails the gate, PP-StructureV3 is the right thing
to add as a structure provider for that case specifically.

### A14. A detection is only split at a rule that crosses it vertically
OCR sometimes merges two cells across a thin border, so a detection straddling a
rule is cut at it. The rule must overlap the detection vertically as well:
without that check, a table's column borders sliced up headings sitting above
the table, turning `ACME CORPORATION` into `ACME CORP ORATION`.

### A15. Ink that is neither rule nor text is a picture
A scanned logo arrives as ink like everything else. After erasing detected rules
and everything OCR could read, sufficiently large remaining regions are cropped
out and anchored as images. Ignoring them would lose the picture *and* the
vertical space it occupied, shifting every row beneath it.

### A16. Skew is estimated from edges, not from filled regions
A solid block contains an unlimited supply of near-horizontal chords, and
feeding them to Hough buries the real lines: one 96 × 42 pt swatch swung the
estimate to −2.3°, which tilted the page and destroyed every table rule on it.
Hough therefore runs over Canny edges, and angles are combined with a
length-weighted median so a page-wide rule outvotes a short fragment.

### A17. Scanned pages carry no font metadata
A raster cannot say which typeface it was set in. Font size is inferred from the
text-line box height; the family falls back to the workbook default rather than
being guessed, and bold/italic are not asserted. Phase 3 revisits what can be
recovered from stroke weight.

## Cross-cutting

### A10. Accuracy counts spurious cells as errors
The reported figure is `matched / (expected + extra)`. Scoring only the expected
cells would let a converter that scattered extra values across the sheet still
report a perfect result.

### A11. The score is measured on the saved workbook
Fixtures are scored by reading the `.xlsx` back from disk and rendering each cell
the way Excel would, so what is measured is the file a user downloads rather than
an in-memory structure that might not survive serialisation.
