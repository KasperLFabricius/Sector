"""Independent PR11C1 report page-start and object-start contracts."""

from __future__ import annotations

import io
import pathlib
import sys

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    CondPageBreak,
    NotAtTopPageBreak,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
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


def _page_texts(flow):
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
    return [
        page.extract_text() or ""
        for page in pypdf.PdfReader(io.BytesIO(buffer.getvalue())).pages
    ]


def test_native_not_at_top_break_never_duplicates_a_fresh_page():
    style = sector_report._styles()["body"]
    assert _page_count([
        Paragraph("first page", style),
        PageBreak(),
        NotAtTopPageBreak(),
        Paragraph("second page", style),
    ]) == 2

    assert _page_count([
        Paragraph("first page", style),
        NotAtTopPageBreak(),
        Paragraph("second page", style),
    ]) == 2


def test_builder_page_break_uses_reportlabs_frame_action_boundary():
    builder = _builder()
    builder._page_break()
    page_break, = builder.flow
    assert type(page_break) is NotAtTopPageBreak


def test_table_reference_reserves_a_readable_object_start():
    builder = _builder()
    builder._table(
        [["Key", "Value"], ["Demand", "125.0 %"]],
        [50 * mm, 50 * mm],
    )
    assert isinstance(builder.flow[0], CondPageBreak)
    assert builder.flow[0].height == pytest.approx(
        sector_report._PUBLICATION_START_HEIGHT
    )
    assert builder.flow[1].getPlainText() == "See Table 0.1."
    assert any(isinstance(item, Table) for item in builder.flow[2]._content)


def test_near_edge_subsection_moves_with_its_reserved_table_start():
    builder = _builder()
    builder._h2("Concrete corners")
    builder._table(
        [["Corner", "Value"], ["C1", "125.0 %"]],
        [50 * mm, 50 * mm],
    )
    assert isinstance(builder.flow[0], CondPageBreak)
    assert builder.flow[0].height == pytest.approx(
        sector_report._PUBLICATION_HEADING_START_HEIGHT
    )
    assert builder.flow[1].getPlainText() == "Concrete corners"
    pages = _page_texts([Spacer(1, 195 * mm), *builder.flow])
    heading_page = next(
        index for index, text in enumerate(pages)
        if "Concrete corners" in text
    )
    table_page = next(
        index for index, text in enumerate(pages)
        if "Table 0.1." in text
    )
    assert heading_page == table_page


def test_results_overview_uses_the_dense_owned_padding(monkeypatch):
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
    for cell_style in table._cellStyles[0]:
        assert cell_style.topPadding == pytest.approx(1.2)
        assert cell_style.bottomPadding == pytest.approx(1.2)
