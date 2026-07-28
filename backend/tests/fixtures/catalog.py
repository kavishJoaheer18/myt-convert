"""The fixture set: five documents covering the layouts that break converters.

Values are chosen to exercise type inference as well as layout — thousands
separators, decimals, an identifier with a significant leading zero, and text
that merely looks numeric.
"""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path

from tests.fixtures.generate import (
    FixtureSpec,
    ImageSwatch,
    Merge,
    PageSpec,
    ProseBlock,
    TableBlock,
    TextBlock,
    render_fixture,
)
from tests.fixtures.ground_truth import Fixture

#: Where rendered fixtures land. Outside the repository by default: the tree may
#: sit in a synced folder (OneDrive, Dropbox), and a sync client holding a
#: generated PDF open makes the next run fail to overwrite it. They are
#: regenerated deterministically, so nothing is lost by keeping them in temp.
GENERATED_DIR = Path(
    os.environ.get("GRIDLOCK_FIXTURE_DIR")
    or Path(tempfile.gettempdir()) / "gridlock-fixtures"
)


def _simple_table_page() -> PageSpec:
    """A bare ruled table: the baseline case, nothing else on the page."""
    return PageSpec(
        blocks=[
            TableBlock(
                rows=[
                    ["Product", "Region", "Units", "Revenue"],
                    ["Widget A", "North", "1,250", "18,750.00"],
                    ["Widget B", "South", "980", "14,700.00"],
                    ["Gadget C", "East", "2,415", "36,225.00"],
                    ["Gadget D", "West", "760", "11,400.00"],
                    ["Assembly E", "Central", "1,032", "15,480.00"],
                ],
                col_widths=[150.0, 110.0, 90.0, 130.0],
                bold_rows=(0,),
                right_aligned_cols=(2, 3),
            )
        ]
    )


def _invoice_page() -> PageSpec:
    """Headings above a ruled table carrying both kinds of merge."""
    return PageSpec(
        blocks=[
            TextBlock("ACME CORPORATION", font_size=18.0, bold=True),
            TextBlock("123 Industrial Way, Port Louis, Mauritius", font_size=10.0),
            TextBlock("Invoice INV-1042 dated 27 July 2026", font_size=10.0),
            TableBlock(
                rows=[
                    ["ORDER DETAILS", "", "", ""],
                    ["Category", "Description", "Qty", "Amount"],
                    ["Fasteners", "Hex bolt M8", "1,000", "350.00"],
                    ["", "Washer set", "500", "90.00"],
                    ["Structural", "Steel bracket 40mm", "120", "1,500.00"],
                    ["Logistics", "Delivery", "1", "250.00"],
                    ["TOTAL DUE (MUR)", "", "", "2,190.00"],
                ],
                col_widths=[110.0, 190.0, 70.0, 110.0],
                row_height=22.0,
                merges=[
                    Merge(row=0, col=0, col_span=4),
                    Merge(row=2, col=0, row_span=2),
                    Merge(row=6, col=0, col_span=3),
                ],
                bold_rows=(0, 1, 6),
                right_aligned_cols=(2, 3),
                centered_cells=((0, 0),),
                right_aligned_cells=((6, 0),),
            ),
        ]
    )


def _multi_table_page() -> PageSpec:
    """Two tables with different column structures, plus an image.

    The worksheet must carry the union of both column grids, with each table
    spanning the sub-columns it covers.
    """
    return PageSpec(
        blocks=[
            TextBlock("QUARTERLY OPERATIONS", font_size=14.0, bold=True),
            ImageSwatch(name="ops_logo", width=96.0, height=42.0),
            TableBlock(
                rows=[
                    ["Metric", "Q1", "Q2"],
                    ["Orders shipped", "4,180", "5,067"],
                    ["Average lead time", "3.4", "2.9"],
                    ["Backorder rate", "0.07", "0.04"],
                ],
                col_widths=[160.0, 160.0, 160.0],
                bold_rows=(0,),
                right_aligned_cols=(1, 2),
            ),
            TextBlock("Regional breakdown", font_size=11.0, bold=True),
            TableBlock(
                rows=[
                    ["Depot", "Code", "Staff", "Capacity"],
                    ["Port Louis", "PL01", "34", "12,000"],
                    ["Curepipe", "CP02", "21", "8,400"],
                    ["Grand Baie", "GB03", "17", "6,150"],
                ],
                col_widths=[120.0, 120.0, 120.0, 120.0],
                bold_rows=(0,),
                right_aligned_cols=(2, 3),
            ),
        ]
    )


def _borderless_page() -> PageSpec:
    """No rulings at all: columns exist only as whitespace corridors."""
    return PageSpec(
        blocks=[
            TableBlock(
                rows=[
                    ["Account", "Type", "Opened", "Balance"],
                    ["Trading", "Current", "2019", "42,180.55"],
                    ["Reserve", "Savings", "2021", "8,904.10"],
                    ["Payroll", "Current", "2020", "15,326.00"],
                    ["Escrow", "Fixed", "2022", "60,000.00"],
                    ["Petty cash", "Current", "2023", "1,204.75"],
                    ["Bond fund", "Fixed", "2018", "97,455.20"],
                ],
                col_widths=[150.0, 120.0, 100.0, 110.0],
                row_height=19.0,
                ruled=False,
                bold_rows=(0,),
            )
        ]
    )


def _text_and_small_table_page() -> PageSpec:
    """Prose-like lines above a narrow table, with awkward-to-type values."""
    return PageSpec(
        blocks=[
            TextBlock("Appendix B - Reference codes", font_size=13.0, bold=True),
            TextBlock("Codes are assigned sequentially and never reused.", font_size=10.0),
            TableBlock(
                rows=[
                    ["Code", "Meaning", "Active"],
                    ["007", "Legacy import", "no"],
                    ["1042", "Standard order", "yes"],
                    ["3.14159", "Calibration constant", "yes"],
                    ["-250", "Reversal adjustment", "yes"],
                ],
                col_widths=[110.0, 240.0, 90.0],
                bold_rows=(0,),
            ),
        ]
    )


def _formatted_report_page() -> PageSpec:
    """Everything Phase 3 has to reproduce, on one page.

    A shaded header in reversed-out white, an italic note row, per-column
    alignment, and values in every type the inference layer claims to handle:
    currency, percentages, dates, accounting negatives and plain numbers.
    """
    return PageSpec(
        blocks=[
            TextBlock("FINANCIAL SUMMARY", font_size=16.0, bold=True),
            TableBlock(
                rows=[
                    ["Account", "Posted", "Amount", "Change"],
                    ["Trading income", "2026-01-15", "$42,180.55", "12.5%"],
                    ["Service revenue", "27 July 2026", "$8,904.10", "-4.2%"],
                    ["Refunds issued", "Mar 3, 2026", "($1,204.75)", "0.8%"],
                    ["Equipment lease", "2026-02-28", "MUR 60,000.00", "100%"],
                    ["Provisional figures pending audit", "", "", ""],
                ],
                col_widths=[170.0, 120.0, 120.0, 70.0],
                row_height=22.0,
                bold_rows=(0,),
                italic_rows=(5,),
                row_fills={0: "1F3864"},
                row_font_colors={0: "FFFFFF", 5: "808080"},
                right_aligned_cols=(2, 3),
                centered_cells=((0, 1),),
                merges=[Merge(row=5, col=0, col_span=4)],
                assert_style=True,
            ),
        ]
    )


def _prose_page() -> PageSpec:
    """Justified body text above a small table.

    A real 33-page research paper exposed this: justified spacing lined up
    across enough lines to punch whitespace corridors through a paragraph, and
    the page came out as a ten-column "table" of shredded sentences. The prose
    must stay one cell per line while the actual table below it is still found.
    """
    return PageSpec(
        blocks=[
            TextBlock("Box A: Quantum readiness", font_size=13.0, bold=True),
            ProseBlock(
                # Lines nearly fill the measure, so justification stretches the
                # spaces only slightly — as a real typesetter would leave them.
                lines=[
                    "The project explored how central banks might migrate their core payment",
                    "systems to post-quantum cryptography without interrupting settlement at",
                    "any point. It emphasised the need for a broad readiness roadmap, taking",
                    "in the upskilling of staff and a full inventory of the legacy systems that",
                    "cannot be upgraded in place, and recommended a carefully staged plan.",
                    "A staged transition was recommended by the working group.",
                ],
                width=396.0,
            ),
            TableBlock(
                rows=[
                    ["Phase", "Focus", "Status"],
                    ["One", "Inventory", "complete"],
                    ["Two", "Pilot migration", "ongoing"],
                    ["Three", "Full rollout", "planned"],
                ],
                col_widths=[130.0, 200.0, 130.0],
                bold_rows=(0,),
            ),
        ]
    )


SPECS: dict[str, FixtureSpec] = {
    "simple_table": FixtureSpec(
        name="simple_table",
        pages=[_simple_table_page()],
        description="Single ruled table, six rows by four columns.",
    ),
    "merged_invoice": FixtureSpec(
        name="merged_invoice",
        pages=[_invoice_page()],
        description="Headings plus a ruled table with horizontal and vertical merges.",
    ),
    "multi_table_images": FixtureSpec(
        name="multi_table_images",
        pages=[_multi_table_page()],
        description="Two tables of differing widths and an embedded image.",
    ),
    "borderless_table": FixtureSpec(
        name="borderless_table",
        pages=[_borderless_page()],
        description="Borderless table; columns inferred from whitespace alone.",
    ),
    "formatted_report": FixtureSpec(
        name="formatted_report",
        pages=[_formatted_report_page()],
        description="Shaded header, italics, colour, alignment and every value type.",
    ),
    "justified_prose": FixtureSpec(
        name="justified_prose",
        pages=[_prose_page()],
        description="Justified paragraphs that must not be read as columns.",
    ),
    "mixed_5page": FixtureSpec(
        name="mixed_5page",
        pages=[
            _simple_table_page(),
            _invoice_page(),
            _multi_table_page(),
            _borderless_page(),
            _text_and_small_table_page(),
        ],
        description="Five pages combining every layout above.",
    ),
}


@lru_cache(maxsize=None)
def get_fixture(name: str) -> Fixture:
    """Render (once per session) and return the named fixture."""
    if name not in SPECS:
        raise KeyError(f"unknown fixture {name!r}; available: {sorted(SPECS)}")
    return render_fixture(SPECS[name], GENERATED_DIR)


def all_fixtures() -> list[Fixture]:
    return [get_fixture(name) for name in SPECS]
