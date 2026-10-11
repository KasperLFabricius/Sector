"""Independent report body-word, numeric-evidence and residual display checks."""
from __future__ import annotations

import copy
import io
import re

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table

from app import sector_report as report


def _builder(profile):
    return report.ReportBuilder(io.BytesIO(), {}, {}, {}, figures=False, profile=profile)


def _tables(flow):
    for item in flow:
        if isinstance(item, Table):
            yield item
        elif hasattr(item, "_content"):
            yield from _tables(item._content)


def _pdf_text(builder):
    stream = io.BytesIO()
    SimpleDocTemplate(stream, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                      topMargin=25*mm, bottomMargin=20*mm).build(builder.flow)
    reader = pypdf.PdfReader(stream)
    return "\n".join(page.extract_text() for page in reader.pages)


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
@pytest.mark.parametrize("token", ["Minimum-reinforcement", "characteristic", "APPLICABLE"])
def test_narrow_body_columns_keep_complete_words_at_reviewed_font(profile, token):
    builder = _builder(profile)
    builder._h1("Readable body words")
    builder._table([["ID", "Basis", "Status", "Result"],
                    ["R1", token, "NOT APPLICABLE", "1234567890.12345"]],
                   [20*mm, 16*mm, 18*mm, 40*mm], keep=False)
    tables = list(_tables(builder.flow))
    assert tables
    assert all(t._sector_font_size == 9.5 for t in tables)
    assert all(sum(t._colWidths) <= 170*mm + 1e-7 for t in tables)
    text = _pdf_text(builder)
    assert token in text
    assert "APPLICABLE" in text
    assert "1234567890.12345" in text


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_long_literal_id_wraps_without_widening_page_or_losing_digits(profile):
    builder = _builder(profile)
    identifier = "BIN-" + "1234567890" * 32
    builder._table([["ID", "Basis", "Result"],
                    [report._html_escape(identifier), "characteristic", "1.23456789"]],
                   [32*mm, 16*mm, 40*mm], keep=False)
    tables = list(_tables(builder.flow))
    for table in tables:
        assert sum(table._colWidths) <= 170*mm + 1e-7
        if 0 in table._sector_source_columns:
            i = table._sector_source_columns.index(0)
            assert table._sector_width_floors[i] <= 170*mm/3 + 6 + 1e-7
        assert table._sector_font_size == 9.5
    text = _pdf_text(builder)
    assert identifier in re.sub(r"\s+", "", text)
    assert "characteristic" in text
    assert "1.23456789" in text


def test_retained_small_signed_residuals_and_tolerance_survive_publication(monkeypatch):
    builder = _builder("Audit")
    builder._h1("Elastic equilibrium")
    state = {
        "raw_stress_plane": {"sigma0_kpa": 1.0, "gradient_x_kpa_per_m": 2.0,
                             "gradient_y_kpa_per_m": 3.0},
        "iterations": 6,
        "equilibrium": {
            "matrix": [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]],
            "target": {"n": 1., "mx": 2., "my": 3.},
            "internal": {"n": 1., "mx": 2., "my": 3.},
            "residual": {"n": -1.249418346e-10, "mx": 1.925570814e-11, "my": 0.},
            "normalised_residual": 4.16472782e-11,
            "relative_tolerance": 1e-12,
        },
    }
    before = copy.deepcopy(state)
    captured, notes = [], []
    original_table, original_small = builder._table, builder._small
    def table(rows, *args, **kwargs):
        captured.append(copy.deepcopy(rows))
        return original_table(rows, *args, **kwargs)
    def small(text, *args, **kwargs):
        notes.append(text)
        return original_small(text, *args, **kwargs)
    monkeypatch.setattr(builder, "_table", table)
    monkeypatch.setattr(builder, "_small", small)
    plane, equilibrium, matrix = builder._elastic_state_tables("Retained state", state)
    assert state == before
    assert plane is state["raw_stress_plane"]
    assert equilibrium is state["equilibrium"]
    assert matrix is equilibrium["matrix"]
    residual_table, = [rows for rows in captured if rows[0] == [
        "Resultant", "Target", "Internal", "Residual", "Unit"
    ]]
    for row, key in zip(residual_table[1:], ("n", "mx", "my"), strict=True):
        actual = float(row[3])
        assert actual == pytest.approx(equilibrium["residual"][key], rel=5e-9, abs=0)
    note, = [n for n in notes if n.startswith("Normalized residual =")]
    assert "Normalized residual = 4.16472782e-11. Tolerance = 1e-12." == note
    text = _pdf_text(builder)
    assert "Normalized residual" in text and "Tolerance" in text
    assert "4.16472782" in text and "1.24941835" in text
