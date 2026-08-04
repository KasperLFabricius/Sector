"""Independent F019 contract tests for report-table vertical pagination."""

from __future__ import annotations

import io
import pathlib
import sys

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Table

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import sector_report  # noqa: E402


def _builder():
    return sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, qa_appendix=False
    )


def _direct_tables(builder):
    tables = []
    for item in builder.flow:
        if isinstance(item, KeepTogether):
            tables.extend(child for child in item._content if isinstance(child, Table))
        elif isinstance(item, Table):
            tables.append(item)
    return tables


def _pdf(flow):
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
    return buffer.getvalue()


def _summary_rows(count=2):
    statuses = ("PASS", "FAIL")
    return [
        {
            "check": f"Check {index}",
            "case": f"CASE-{index}",
            "status": statuses[index % 2],
            "result": f"{index + 1}.0",
            "criterion": "<= 1.0",
        }
        for index in range(count)
    ]


def test_data_table_inventory_uses_one_pagination_boundary(monkeypatch):
    builder = _builder()
    builder._table([["Key", "Value"], ["A", "1"]], [30 * mm, 30 * mm])
    generic, = _direct_tables(builder)
    assert isinstance(generic, sector_report._PaginatedReportTable)
    assert generic.splitByRow == 1
    assert generic.splitInRow == 1

    builder = _builder()
    builder._status_block("PASS - retained banner", "PASS")
    banner, = _direct_tables(builder)
    assert type(banner) is Table
    assert banner._sector_status_banner is True

    monkeypatch.setattr(
        sector_report.presentation, "multi_case_summary_rows",
        lambda _inp, _out: _summary_rows(),
    )
    monkeypatch.setattr(
        sector_report.presentation, "summary_governing_case_flags",
        lambda rows: [False] * len(rows),
    )
    builder = _builder()
    builder._results_overview()
    overview = next(
        table for table in _direct_tables(builder)
        if getattr(table, "_sector_results_overview", False)
    )
    assert isinstance(overview, sector_report._PaginatedReportTable)
    assert overview.splitByRow == 1
    assert overview.splitInRow == 1


def test_ordinary_split_retains_three_data_rows_at_both_edges():
    data = [["Header"]] + [[f"row-{index}"] for index in range(10)]
    table = sector_report._PaginatedReportTable(
        data,
        colWidths=[80 * mm],
        rowHeights=[10] * len(data),
        repeatRows=1,
        splitByRow=1,
        splitInRow=1,
    )

    assert table.split(80 * mm, 35) == []
    assert table._sector_row_split_range == (4, -3)

    leading, trailing = table.split(80 * mm, 55)
    assert len(leading._cellvalues) - 1 >= 3
    assert len(trailing._cellvalues) - 1 >= 3
    assert table._sector_row_split_range == (4, -3)


@pytest.mark.parametrize("tall_index", [0, -1])
def test_structurally_tall_first_or_last_group_relaxes_fragment_range(tall_index):
    paragraph_style = ParagraphStyle("tall", fontSize=8, leading=10)
    ordinary = [Paragraph(f"ordinary-{index}", paragraph_style) for index in range(6)]
    tall = Paragraph("<br/>".join(f"tall-token-{index}" for index in range(130)),
                     paragraph_style)
    ordinary[tall_index] = tall
    data = [[Paragraph("Header", paragraph_style)]] + [[value] for value in ordinary]
    table = sector_report._PaginatedReportTable(
        data,
        colWidths=[80 * mm],
        repeatRows=1,
        splitByRow=1,
        splitInRow=1,
    )

    fragments = table.split(80 * mm, 120 * mm)
    assert table._sector_row_split_range is None
    assert fragments


@pytest.mark.parametrize("near_frame_edge", ["first", "last"])
def test_frame_padding_boundary_uses_the_fresh_usable_height(near_frame_edge):
    # The group fits inside the margin-derived document height but not the actual
    # fresh frame after ReportLab removes its 6 pt top and bottom padding.
    repeated_height = 10.0
    group_height = sector_report._A4_FRAME_USABLE_HEIGHT + 1.0
    tall_height = (group_height - repeated_height) / 3.0
    ordinary_heights = [10.0] * 6
    if near_frame_edge == "first":
        ordinary_heights[:3] = [tall_height] * 3
    else:
        ordinary_heights[-3:] = [tall_height] * 3
    data = [["Header"]] + [[f"row-{index}"] for index in range(6)]
    table = sector_report._PaginatedReportTable(
        data,
        colWidths=[80 * mm],
        rowHeights=[repeated_height] + ordinary_heights,
        repeatRows=1,
        splitByRow=1,
        splitInRow=1,
    )

    fragments = table.split(80 * mm, sector_report._A4_FRAME_USABLE_HEIGHT)
    assert table._sector_row_split_range is None
    assert fragments


def test_one_oversized_row_repeats_frozen_context_without_token_loss():
    builder = _builder()
    builder._h1("Pagination proof")
    builder._h2("Oversized row")
    builder._status_block("PASS - complete", "PASS")
    tokens = [f"ROWITEM{index:04d}" for index in range(190)]
    builder._table(
        [["Key", "Evidence"], ["ROW-1", "<br/>".join(tokens)]],
        [30 * mm, 125 * mm],
        keep=True,
    )

    wrapper = next(
        item for item in builder.flow
        if isinstance(item, KeepTogether)
        and any(isinstance(child, sector_report._PaginatedReportTable)
                for child in item._content)
    )
    assert wrapper is not None

    pdf = _pdf(builder.flow)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) >= 3
    pages = [page.extract_text() or "" for page in reader.pages]
    complete_text = "\n".join(pages)
    for token in tokens:
        assert complete_text.count(token) == 1
    table_pages = [page_text for page_text in pages if "ROWITEM" in page_text]
    assert len(table_pages) >= 2
    for page_text in table_pages:
        assert "Section 1: Pagination proof" in page_text
        assert "Subsection: Oversized row" in page_text
        assert "Assessment: PASS - complete" in page_text
        assert "Key" in page_text
        assert "Evidence" in page_text


def test_context_lifecycle_is_ordered_replaced_and_frozen():
    builder = _builder()
    builder._h1("First")
    builder._h2("Alpha")
    builder._status_block("PASS - initial", "PASS")
    builder._table([["Key"], ["one"]], [40 * mm])
    first = [
        table for table in _direct_tables(builder)
        if isinstance(table, sector_report._PaginatedReportTable)
    ][-1]

    builder._h2("Beta")
    builder._table([["Key"], ["two"]], [40 * mm])
    second = [
        table for table in _direct_tables(builder)
        if isinstance(table, sector_report._PaginatedReportTable)
    ][-1]

    builder._status_block("FAIL - replacement", "FAIL")
    builder._table([["Key"], ["three"]], [40 * mm])
    third = [
        table for table in _direct_tables(builder)
        if isinstance(table, sector_report._PaginatedReportTable)
    ][-1]

    builder._h1("Second")
    builder._table([["Key"], ["four"]], [40 * mm])
    fourth = [
        table for table in _direct_tables(builder)
        if isinstance(table, sector_report._PaginatedReportTable)
    ][-1]

    assert first._sector_context_labels == (
        "Section 1: First", "Subsection: Alpha", "Assessment: PASS - initial",
    )
    assert second._sector_context_labels == (
        "Section 1: First", "Subsection: Beta", "Assessment: PASS - initial",
    )
    assert third._sector_context_labels == (
        "Section 1: First", "Subsection: Beta", "Assessment: FAIL - replacement",
    )
    assert fourth._sector_context_labels == ("Section 2: Second",)
    assert first._sector_context_labels == (
        "Section 1: First", "Subsection: Alpha", "Assessment: PASS - initial",
    )


def test_results_overview_offsets_status_fills_after_context(monkeypatch):
    rows = _summary_rows()
    monkeypatch.setattr(
        sector_report.presentation, "multi_case_summary_rows",
        lambda _inp, _out: rows,
    )
    monkeypatch.setattr(
        sector_report.presentation, "summary_governing_case_flags",
        lambda values: [False] * len(values),
    )
    builder = _builder()
    builder._h1("Summary")
    builder._status_block("REVIEW - project", "REVIEW")
    builder._results_overview()

    overview = next(
        table for table in _direct_tables(builder)
        if getattr(table, "_sector_results_overview", False)
    )
    assert overview._sector_context_labels == (
        "Section 1: Summary",
        "Subsection: Results overview",
        "Assessment: REVIEW - project",
    )
    assert overview._sector_context_count == 3
    assert overview._sector_caption_row == 0
    assert overview._sector_header_row == 4
    assert overview._sector_data_start == 5
    status_fill_rows = {
        start[1]
        for command, start, end, _colour in overview._bkgrndcmds
        if command == "BACKGROUND" and start[0] == end[0] == 2
    }
    assert status_fill_rows == {5, 6}


def test_headerless_tables_repeat_context_without_promoting_first_data_row():
    builder = _builder()
    builder._h1("Headerless")
    builder._table([["identity", "value"]], [30 * mm, 30 * mm], header=False)
    table = next(
        value for value in _direct_tables(builder)
        if isinstance(value, sector_report._PaginatedReportTable)
    )

    assert table._sector_context_count == 1
    assert table._sector_caption_row == 0
    assert table.repeatRows == 2
    assert table._sector_header_row is None
    assert table._sector_data_start == 2
