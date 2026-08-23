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
    CondPageBreak,
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


def test_subsection_heading_reserves_space_for_first_calculation_block():
    builder = _builder()

    builder._h2("Worked calculation")

    guard, heading = builder.flow
    assert isinstance(guard, CondPageBreak)
    assert guard.height == pytest.approx(170)
    assert heading.getPlainText() == "Worked calculation"


def test_selected_chapter_heading_can_reserve_its_first_subsection():
    builder = _builder()

    builder._h1("Section and materials", reserve=240)

    guard, heading = builder.flow
    assert isinstance(guard, CondPageBreak)
    assert guard.height == pytest.approx(240)
    assert heading.getPlainText() == "1. Section and materials"


def test_paginated_table_moves_instead_of_leaving_caption_and_header_only():
    styles = sector_report._styles()
    width = 80 * mm
    table = sector_report._PaginatedReportTable(
        [
            [Paragraph("Table 1.1. Caption", styles["small"]), ""],
            [Paragraph("A", styles["small"]), Paragraph("B", styles["small"])],
            [Paragraph("first", styles["small"]), Paragraph("row", styles["small"])],
            [Paragraph("second", styles["small"]), Paragraph("row", styles["small"])],
        ],
        colWidths=[width / 2, width / 2],
        repeatRows=2,
        splitByRow=1,
        splitInRow=0,
    )
    table._calc(width, 500)
    minimum = sum(table._rowHeights[:3])

    assert table.split(width, minimum - 0.1) == []
    assert table.split(width, minimum + 0.1)


def test_paginated_table_falls_back_to_two_trailing_rows_when_three_are_tall():
    width = 80 * mm
    data = [["caption", ""], ["A", "B"]]
    data.extend([[str(index), str(index)] for index in range(7)])
    table = sector_report._PaginatedReportTable(
        data,
        colWidths=[width / 2, width / 2],
        rowHeights=[20, 20, 20, 20, 20, 260, 260, 260, 260],
        repeatRows=2,
        splitByRow=1,
        splitInRow=0,
    )

    table.split(width, 400)

    assert table._sector_row_split_range == (4, -2)


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
    assert header.style.fontSize == pytest.approx(8.5)
    assert header.style.leading == pytest.approx(10.1)
    assert table._sector_overview_groups == ("Checks and comparisons",)
    assert sum(table._colWidths) == pytest.approx(170 * mm)
    for cell_style in table._cellStyles[0]:
        assert cell_style.leftPadding == pytest.approx(2)
        assert cell_style.rightPadding == pytest.approx(2)
        assert cell_style.topPadding == pytest.approx(0.7)
        assert cell_style.bottomPadding == pytest.approx(0.7)
    heading, introduction = builder.flow[1:3]
    assert heading.getKeepWithNext()
    assert introduction.getKeepWithNext()


def test_results_overview_separates_scope_state_from_result_groups(monkeypatch):
    rows = [
        {
            "check": "Plastic bending",
            "case": "LC-1",
            "status": "PASS",
            "result": "80.0 %",
            "criterion": "<= 100 %",
        },
        {
            "check": "Centroid",
            "case": "-",
            "status": "CALCULATED",
            "result": "1.0 mm",
            "criterion": "Output only",
        },
        {
            "check": "Fatigue",
            "case": "-",
            "status": "NOT RUN",
            "result": "-",
            "criterion": "-",
        },
        {
            "check": "Shear",
            "case": "LC-2",
            "status": "FAIL",
            "result": "120.0 %",
            "criterion": "<= 100 %",
        },
    ]
    monkeypatch.setattr(
        sector_report.presentation,
        "multi_case_summary_rows",
        lambda _inp, _out: rows,
    )
    monkeypatch.setattr(
        sector_report.presentation,
        "summary_governing_case_flags",
        lambda _rows: [False, False, False, True],
    )
    builder = _builder()
    builder._results_overview()
    table = next(
        item for item in builder.flow
        if getattr(item, "_sector_results_overview", False)
    )
    assert table._sector_overview_groups == (
        "Checks and comparisons",
        "Calculated outputs",
        "Checks and comparisons",
    )
    values = [
        row[0].getPlainText()
        for row in table._cellvalues[table._sector_data_start:]
    ]
    assert values == [
        "Checks and comparisons",
        "Plastic bending",
        "Calculated outputs",
        "Centroid",
        "Checks and comparisons",
        "Shear",
    ]
    plain_text = " | ".join(
        item.getPlainText()
        for item in builder.flow
        if hasattr(item, "getPlainText")
    )
    assert "Scope and calculation state" in plain_text
    assert "Fatigue | - | NOT RUN | -" in plain_text
