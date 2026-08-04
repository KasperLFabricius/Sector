"""Focused geometry and pagination contract for PR-10B publication tables."""

from __future__ import annotations

import io
import pathlib
import sys

import pytest
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import sector_report  # noqa: E402


def _builder():
    return sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, qa_appendix=False
    )


def _plain(cell):
    return cell.getPlainText() if hasattr(cell, "getPlainText") else str(cell)


def test_numeric_atoms_drive_real_widths_at_the_readable_font_floor():
    builder = _builder()
    builder._h1("Fatigue evidence")
    builder._h2("Entered spectrum actions")
    data = [["Spectrum", "Bin", "Description", "Cycles"] + [f"N{i}" for i in range(6)]]
    data.append(["S1", "B1", "Published bin", "1000.000"] + ["-1000.000"] * 6)
    start = len(builder.flow)

    builder._table(
        data,
        [18 * mm, 18 * mm, 24 * mm, 15 * mm] + [15 * mm] * 6,
        font=5.1,
        keep=False,
        repeat_cols=3,
    )

    tables = [item for item in builder.flow[start:]
              if isinstance(item, sector_report._BalancedTable)]
    assert len(tables) == 1
    table = tables[0]
    assert table._sector_font_size == sector_report._MIN_TABLE_FONT
    assert sum(table._colWidths) <= sector_report._A4_CONTENT_WIDTH + 1e-7
    for row in table._cellvalues[1:]:
        for cell, width in zip(row, table._colWidths):
            assert cell.minWidth() + 2 * sector_report._TABLE_HORIZONTAL_PADDING \
                <= width + 1e-7
            assert cell.style.fontSize >= sector_report._MIN_TABLE_FONT


def test_dense_tables_split_into_complete_sequential_column_panels():
    builder = _builder()
    builder._h1("Dense calculation")
    builder._h2("Candidate outputs")
    builder._status_block("FAIL - retained engineering verdict", "FAIL")
    headers = ["Member"] + [f"Output {index}" for index in range(1, 9)]
    data = [headers]
    data.extend([
        [f"M{row}"] + [f"-{column}{row}000000.000" for column in range(1, 9)]
        for row in range(1, 5)
    ])
    start = len(builder.flow)

    builder._table(
        data,
        [25 * mm] + [24 * mm] * 8,
        font=6.0,
        keep=False,
        repeat_cols=1,
    )

    flow = builder.flow[start:]
    tables = [item for item in flow
              if isinstance(item, sector_report._BalancedTable)]
    assert len(tables) > 1
    assert {table._sector_panel_count for table in tables} == {len(tables)}
    assert all(table._sector_source_columns[0] == 0 for table in tables)
    non_identity = [column for table in tables
                    for column in table._sector_source_columns[1:]]
    assert non_identity == list(range(1, len(headers)))
    assert all(table._nrows == len(data) + 1 for table in tables)
    assert all(sum(table._colWidths) <= sector_report._A4_CONTENT_WIDTH + 1e-7
               for table in tables)
    for source_row in data[1:]:
        for column in range(1, len(headers)):
            table = next(item for item in tables
                         if column in item._sector_source_columns)
            panel_column = table._sector_source_columns.index(column)
            assert _plain(table._cellvalues[data.index(source_row) + 1][panel_column]) \
                == source_row[column]
    continuation_text = " ".join(
        table._sector_context_text for table in tables
    )
    assert "Dense calculation" in continuation_text
    assert "Candidate outputs" in continuation_text
    assert "retained engineering verdict" in continuation_text
    assert "column panel" in continuation_text


def test_repeated_context_row_freezes_context_before_later_sections():
    builder = _builder()
    builder._h1("Original section")
    builder._h2("Original subsection")
    builder._status_block("FAIL - original verdict", "FAIL")
    builder._h2("Child output table")
    builder._table(
        [["Member", "Value"]] + [[f"M{index}", str(index)] for index in range(10)],
        [50 * mm, 50 * mm],
        keep=False,
    )
    table = next(
        item for item in reversed(builder.flow)
        if isinstance(item, sector_report._BalancedTable)
    )
    builder._h1("Later section")

    text = table._sector_context_text
    assert "Original section" in text
    assert "Child output table" in text
    assert "original verdict" in text
    assert "Later section" not in text

    builder._h2("Later table")
    builder._table(
        [["Name", "Value"], ["A", "1"]],
        [50 * mm, 50 * mm],
        keep=False,
    )
    later_table = next(
        item for item in reversed(builder.flow)
        if isinstance(item, sector_report._BalancedTable)
    )
    assert "original verdict" not in later_table._sector_context_text


def test_balanced_table_leaves_three_data_rows_in_the_tail():
    style = getSampleStyleSheet()["BodyText"]
    data = [[Paragraph("Header", style)]]
    data.extend([[Paragraph(f"Row {index}", style)]] for index in range(1, 11))
    table = sector_report._BalancedTable(
        data,
        colWidths=[50 * mm],
        rowHeights=[10] * len(data),
        repeatRows=1,
    )

    fragments = table.split(50 * mm, 90)

    tables = [item for item in fragments
              if isinstance(item, sector_report._BalancedTable)]
    assert len(tables) == 2
    tail_data_rows = tables[1]._nrows - tables[1].repeatRows
    assert tail_data_rows == sector_report._MIN_SPLIT_DATA_ROWS
    assert tables[0]._nrows - tables[0].repeatRows >= \
        sector_report._MIN_SPLIT_DATA_ROWS


def test_balanced_range_is_rebased_for_every_recursive_split():
    style = getSampleStyleSheet()["BodyText"]
    data = [[Paragraph("Header", style)]]
    data.extend([[Paragraph(f"Row {index}", style)]] for index in range(1, 31))
    table = sector_report._BalancedTable(
        data,
        colWidths=[50 * mm],
        rowHeights=[10] * len(data),
        repeatRows=1,
    )

    first_split = table.split(50 * mm, 90)
    remainder = next(
        item for item in reversed(first_split)
        if isinstance(item, sector_report._BalancedTable)
    )
    assert remainder._rowSplitRange == (
        1 + sector_report._MIN_SPLIT_DATA_ROWS,
        -sector_report._MIN_SPLIT_DATA_ROWS,
    )

    second_split = remainder.split(50 * mm, 90)
    assert len([
        item for item in second_split
        if isinstance(item, sector_report._BalancedTable)
    ]) == 2


def test_width_allocator_prefers_reallocation_before_panelisation():
    desired = [80 * mm, 45 * mm, 45 * mm]
    minima = [30 * mm, 25 * mm, 25 * mm]

    fitted = sector_report.ReportBuilder._fit_column_widths(desired, minima)

    assert fitted is not None
    assert sum(fitted) == pytest.approx(sector_report._A4_CONTENT_WIDTH)
    assert all(width >= minimum for width, minimum in zip(fitted, minima))
    assert sector_report.ReportBuilder._column_panels(minima, 1) == [(0, 1, 2)]


def test_long_trace_identity_wraps_losslessly_instead_of_aborting_layout():
    builder = _builder()
    identity = "trace.identity." + "0123456789abcdef" * 24
    data = [["Step", "Derivation", "Result"]]
    data.append(["1. Inputs", identity, "PASS"])
    start = len(builder.flow)

    builder._table(
        data,
        [25 * mm, 110 * mm, 35 * mm],
        font=7.2,
        keep=False,
        repeat_cols=1,
    )

    tables = [item for item in builder.flow[start:]
              if isinstance(item, sector_report._BalancedTable)]
    assert len(tables) == 1
    assert all(sum(table._colWidths) <= sector_report._A4_CONTENT_WIDTH + 1e-7
               for table in tables)
    identity_table = tables[0]
    identity_column = identity_table._sector_source_columns.index(1)
    assert _plain(identity_table._cellvalues[2][identity_column]) == identity
