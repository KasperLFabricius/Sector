"""Contents: closed row gaps remove an almost empty last contents page.

Reference: independent review finding P1-17 of release 0.97.0. A spill of a few
rows must fold back. A large spill keeps the normal row gaps and its own page.
"""

from __future__ import annotations

import io
import pathlib
import sys

import pypdf
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate
from reportlab.platypus.tableofcontents import TableOfContents

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))

import sector_report  # noqa: E402

_STYLES = [
    ParagraphStyle("h1", fontSize=9, leading=12, spaceBefore=6),
    ParagraphStyle("h2", fontSize=9, leading=12, leftIndent=8),
]


def _pages(contents_class, rows):
    contents = contents_class(levelStyles=_STYLES, dotsMinLevel=0)
    contents._lastEntries = [
        (0 if number % 5 == 0 else 1, f"Row {number}", 1, None)
        for number in range(rows)
    ]
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4).build([contents])
    return len(pypdf.PdfReader(io.BytesIO(buffer.getvalue())).pages)


def test_small_spill_folds_back_and_large_spill_keeps_its_page():
    first_spill = next(
        rows for rows in range(10, 120) if _pages(TableOfContents, rows) == 2
    )
    assert _pages(sector_report._ReportContents, first_spill - 1) == 1
    assert _pages(sector_report._ReportContents, first_spill) == 1
    assert _pages(sector_report._ReportContents, first_spill + 20) == 2
