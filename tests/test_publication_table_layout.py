"""PR-10B1 report-table readability and pagination contracts."""

from __future__ import annotations

import io
import pathlib
import sys

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, SimpleDocTemplate

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import sector_report


def _builder():
    return sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, version="0.91", figures=False
    )


def _tables(builder):
    values = []
    for item in builder.flow:
        if isinstance(item, KeepTogether):
            values.extend(
                child
                for child in item._content
                if isinstance(child, sector_report._ReadableSplitTable)
            )
        elif isinstance(item, sector_report._ReadableSplitTable):
            values.append(item)
    return values


def _plain(cell):
    return cell.getPlainText() if hasattr(cell, "getPlainText") else str(cell)


def _data_rows(table):
    repeated = table.repeatRows
    header_rows = repeated if isinstance(repeated, int) else max(repeated) + 1
    return table._nrows - header_rows


def test_table_floor_context_and_verdict_lifecycle_are_frozen():
    builder = _builder()
    builder._h1("Elastic stresses - CASE-A")
    builder._status_block("INVALID - singular transformed section", "INVALID")
    builder._h2("Elastic stress outputs")
    builder._table(
        [["Point", "sigma (MPa)"], ["C1", "-12.5"]],
        [45 * mm, 45 * mm],
        font=5.0,
    )

    first = _tables(builder)[0]
    assert first._sector_font_size == sector_report._MIN_TABLE_FONT == 7.2
    assert "Section 1 - Elastic stresses - CASE-A" in first._sector_context_text
    assert "Elastic stress outputs" in first._sector_context_text
    assert "Status: INVALID - singular transformed section" in first._sector_context_text
    assert first.repeatRows == 2

    builder._h1("Cracking - CASE-A")
    builder._table([["Item", "Value"], ["state", "not requested"]], [45 * mm] * 2)
    second = _tables(builder)[1]
    assert "Section 2 - Cracking - CASE-A" in second._sector_context_text
    assert "Status:" not in second._sector_context_text


def test_wide_numeric_evidence_uses_panels_and_repeats_identity_losslessly():
    builder = _builder()
    builder._h1("Calculation trace")
    numeric = "12345678901234567890.123456789"
    rows = [
        ["Step", "A", "B", "C", "D"],
        ["immutable-step-01", numeric + "1", numeric + "2", numeric + "3", numeric + "4"],
    ]
    builder._table(rows, [28 * mm] * 5, keep=False, repeat_cols=1)
    tables = _tables(builder)

    assert len(tables) > 1
    assert all(table._sector_source_columns[0] == 0 for table in tables)
    assert [table._sector_panel_index for table in tables] == list(range(len(tables)))
    assert all(table._sector_panel_count == len(tables) for table in tables)
    for table in tables:
        assert sum(table._colWidths) <= sector_report._A4_CONTENT_WIDTH + 1e-7
        assert _plain(table._cellvalues[2][0]) == "immutable-step-01"
        for local, source in enumerate(table._sector_source_columns):
            assert _plain(table._cellvalues[2][local]) == rows[1][source]


def test_long_machine_identity_wraps_but_oversize_numeric_atom_is_rejected():
    builder = _builder()
    identity = "sha256:" + "abcdef0123456789" * 12
    builder._table(
        [["Trace identity", "Value"], [identity, "1.25"]],
        [35 * mm, 35 * mm],
        keep=False,
    )
    table = _tables(builder)[0]
    assert _plain(table._cellvalues[2][0]) == identity
    assert sum(table._colWidths) <= sector_report._A4_CONTENT_WIDTH + 1e-7

    with pytest.raises(ValueError, match="unbreakable cell"):
        _builder()._table(
            [["Identity", "Value"], ["row", "9" * 500]],
            [30 * mm, 30 * mm],
        )


def test_readable_split_keeps_three_rows_when_they_fit():
    builder = _builder()
    builder._h1("Rows")
    builder._table(
        [["ID", "Value"]] + [[f"R{i}", str(i)] for i in range(12)],
        [50 * mm, 50 * mm],
        keep=False,
    )
    table = _tables(builder)[0]
    table.wrap(sector_report._A4_CONTENT_WIDTH, sector_report._A4_CONTENT_HEIGHT)
    header_height = sum(table._rowHeights[:2])
    available = header_height + sum(table._rowHeights[2:6]) + 0.1
    fragments = table.split(sector_report._A4_CONTENT_WIDTH, available)

    assert len(fragments) == 2
    assert _data_rows(fragments[0]) >= 3
    assert _data_rows(fragments[1]) >= 3


def test_tall_rows_relax_the_three_row_bound_and_remain_recursively_pageable():
    builder = _builder()
    builder._h1("Tall descriptions")
    tall = " ".join(["validated-user-description"] * 45)
    builder._table(
        [["ID", "Description"]]
        + [[f"ROW-{index}", f"{tall} {index}"] for index in range(8)],
        [25 * mm, 45 * mm],
        keep=False,
    )
    table = _tables(builder)[0]
    table.wrap(sector_report._A4_CONTENT_WIDTH, sector_report._A4_CONTENT_HEIGHT)
    header_height = sum(table._rowHeights[:2])
    available = header_height + table._rowHeights[2] + 0.1
    fragments = table.split(sector_report._A4_CONTENT_WIDTH, available)

    assert len(fragments) == 2
    assert _data_rows(fragments[0]) == 1
    tail = fragments[1]
    tail.wrap(sector_report._A4_CONTENT_WIDTH, sector_report._A4_CONTENT_HEIGHT)
    next_available = sum(tail._rowHeights[:2]) + tail._rowHeights[2] + 0.1
    assert len(tail.split(sector_report._A4_CONTENT_WIDTH, next_available)) == 2


def test_tall_user_rows_build_a_complete_a4_pdf_without_loss():
    buffer = io.BytesIO()
    builder = _builder()
    builder._h1("Pasted descriptions")
    description = " ".join(["auditable-description"] * 65)
    builder._table(
        [["ID", "Description"]]
        + [[f"TALL-{index}", f"{description} token-{index}"] for index in range(9)],
        [25 * mm, 135 * mm],
        keep=False,
    )
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=20 * mm,
    )
    doc.build(builder.flow)

    reader = pypdf.PdfReader(io.BytesIO(buffer.getvalue()))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert len(reader.pages) > 1
    for index in range(9):
        assert f"TALL-{index}" in text
        assert f"token-{index}" in text
