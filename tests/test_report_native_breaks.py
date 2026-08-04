"""Independent PR11C1A native report-break contracts."""

from __future__ import annotations

import ast
import io
import inspect
import pathlib
import sys

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    NotAtTopPageBreak,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import sector_report  # noqa: E402


def _builder():
    return sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, qa_appendix=False
    )


def _page_count(flow):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=20 * mm,
    )
    doc.build(flow)
    return len(pypdf.PdfReader(io.BytesIO(buffer.getvalue())).pages)


def test_native_break_is_inert_on_a_fresh_page_and_active_after_content():
    style = sector_report._styles()["body"]
    first = Paragraph("first", style)
    second = Paragraph("second", style)
    assert _page_count([
        first, PageBreak(), NotAtTopPageBreak(), second,
    ]) == 2
    assert _page_count([
        Paragraph("first", style), NotAtTopPageBreak(),
        Paragraph("second", style),
    ]) == 2


def test_builder_uses_the_native_frame_action_break():
    builder = _builder()
    builder._page_break()
    page_break, = builder.flow
    assert type(page_break) is NotAtTopPageBreak
    tree = ast.parse(inspect.getsource(sector_report.ReportBuilder))
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "PageBreak" not in called_names


def test_results_overview_retains_type_and_dense_padding(monkeypatch):
    row = {
        "check": "Plastic bending",
        "case": "LC-1",
        "status": "PASS",
        "result": "80.0 %",
        "criterion": "<= 100 %",
    }
    monkeypatch.setattr(
        sector_report.presentation,
        "multi_case_summary_rows",
        lambda _inp, _out: [row],
    )
    monkeypatch.setattr(
        sector_report.presentation,
        "summary_governing_case_flags",
        lambda _rows: [True],
    )
    builder = _builder()
    builder._results_overview()
    table = next(
        item for item in builder.flow
        if getattr(item, "_sector_results_overview", False)
    )
    header = table._cellvalues[table._sector_header_row][0]
    assert header.style.fontSize == pytest.approx(7.2)
    for cell_style in table._cellStyles[0]:
        assert cell_style.topPadding == pytest.approx(1.2)
        assert cell_style.bottomPadding == pytest.approx(1.2)
