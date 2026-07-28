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

## Phase 3 — formatting fidelity

### A18. A value is typed only if it round-trips character for character
`infer_value` renders its own result back through `display_string` and falls
back to plain text whenever the two differ. The rule is enforced rather than
merely intended, because a cell that is silently wrong is worse than a cell that
is merely untyped.

### A19. Ambiguous dates stay text
`01/02/2026` could be 1 February or 2 January and the page does not say which.
A slash-separated date is typed only when the order is forced — one component
above 12 — or when the format is unambiguous (ISO, or a spelled month). Guessing
would corrupt the value in a way no later stage could detect.

### A20. Percentages are stored as fractions
Excel's percent format multiplies by 100 on display, so `12.5%` is stored as
`0.125` with format `0.0%`. Storing 12.5 would display as `1250.0%`.

### A21. A ruled row boundary is never moved
Where a band's edge came from a ruling, that ruling *is* the row boundary; only
the whitespace between two unruled bands is split down the middle. If the
boundary drifts, the row's rectangle stops matching the cell's borders and its
background fill, and both are then lost.

### A22. A painted rectangle's edges bound a row
Fill rectangles contribute row boundaries alongside rulings. On a scan this is
sometimes the only evidence available: a dark fill hides the very rule that
would delimit the row it shades.

### A23. Scanned pages recover fills but not typography
Cell background colour is sampled from the raster with a per-channel median,
which reports the background even with glyphs on top of it. Bold, italic and
font colour are *not* inferred from a scan — nothing in the pixels reliably says
which typeface was used — so scanned fixtures assert values, positions, spans and
fills, but not typography. Borders on a solidly shaded row are also not
recoverable, since the rule beneath the shading has no contrast.

### A24. OCR is imported lazily
`convert.py` imports the OCR stack only when a scanned page actually appears, so
the API image runs without OpenCV or PaddlePaddle. The Phase 3 container run —
core requirements plus LibreOffice, no OCR — is what keeps this honest.

## Phase 4 — consensus and verification

### A25. The model reviews the grid; it does not produce one
`verify_page` is given the page image *and* the extracted cells with their
bounding boxes, and returns only the cells it disputes. The alternative — asking
the model to read the page into its own table and aligning that to ours — makes
alignment the dominant source of error, and an alignment failure looks exactly
like a disagreement. Reviewing keeps the VLM to the role the brief sets out:
propose, vote, verify, never originate.

### A26. A cell is only overwritten when two independent readers agree
One dissenting voice is enough to *dispute* a cell and never enough to *rewrite*
it. A value changes only when the OCR engine and the model, reading the
magnified crop, agree with each other and against the original. Anything else
becomes a Discrepancy for a human, because picking a winner on a single vote is
how silent corruption gets into a spreadsheet.

### A27. Zoom means re-rasterising, not upscaling
The disputed region is redrawn from the PDF at 3.5× the working resolution
rather than enlarged from the page image. Upscaling interpolates detail that was
already lost, so a second look at the same pixels cannot see anything new.

### A28. A missing VLM degrades, it does not fail
When no provider is configured the conversion completes without a second
opinion. A second opinion is valuable, not mandatory, and failing the job would
make an unconfigured deployment useless.

### A29. Corrections are rebuilt from the saved grid
The structured grid is persisted as JSON beside the workbook, so a correction is
applied to the structure and the verified workbook is produced by the same
writer as the original. It therefore cannot differ except in the values a human
changed — patching a saved .xlsx in place could not offer that guarantee.

### A30. Consensus is tested with a deterministic double
The gate asks whether consensus *detects disagreement*, which is a property of
the mechanism rather than of any model's eyesight. A ground-truth stand-in
isolates exactly that and keeps the suite reproducible and free. The Anthropic
provider is implemented in full but is only exercised when an API key is
present.

### A31. CPU-first OCR models
PaddleOCR defaults to its server models. They are roughly an order of magnitude
slower on CPU for a small accuracy gain, which turned the zoom-and-re-ask step —
one recognition call per disputed cell — into minutes of work per page. The
mobile models are the default; `OCR_MODEL_VARIANT=server` opts back in.

## Cross-cutting

### A10. Accuracy counts spurious cells as errors
The reported figure is `matched / (expected + extra)`. Scoring only the expected
cells would let a converter that scattered extra values across the sheet still
report a perfect result.

### A11. The score is measured on the saved workbook
Fixtures are scored by reading the `.xlsx` back from disk and rendering each cell
the way Excel would, so what is measured is the file a user downloads rather than
an in-memory structure that might not survive serialisation.
