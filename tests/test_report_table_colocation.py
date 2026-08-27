"""Independent PR11C1B report-table colocation contracts."""

from __future__ import annotations

import io
import pathlib
import sys

import pytest
from reportlab.lib.units import mm
from reportlab.platypus import (
    CondPageBreak,
    KeepTogether,
    NotAtTopPageBreak,
    Paragraph,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import sector_report  # noqa: E402
from sector import __version__  # noqa: E402
from tools.report_render_fixture import (  # noqa: E402
    validate_report_page_semantics,
    validate_report_table_colocation,
)


def _builder(inp=None):
    return sector_report.ReportBuilder(
        io.BytesIO(), {}, inp or {}, {}, figures=False, qa_appendix=False
    )


def _all_flowables(items):
    for item in items:
        yield item
        if isinstance(item, KeepTogether):
            yield from _all_flowables(item._content)


def test_generic_table_owns_destination_and_first_caption_without_self_reference():
    builder = _builder()
    builder._h1("Actions")
    builder._h2("Design values")
    builder._table(
        [["Force (kN)", "Moment (kNm)"]]
        + [[str(index), str(index * 2)] for index in range(18)],
        [40 * mm, 40 * mm],
        keep=False,
    )

    table = next(
        item for item in builder.flow
        if isinstance(item, sector_report._PaginatedReportTable)
    )
    assert "See Table" not in " ".join(
        item.getPlainText()
        for item in _all_flowables(builder.flow)
        if hasattr(item, "getPlainText")
    )
    first, continuation = table.split(80 * mm, 70 * mm)
    first_caption = first._cellvalues[0][0].getPlainText()
    continued_caption = continuation._cellvalues[0][0].getPlainText()
    assert first_caption.startswith("Table 1.1.")
    assert "See Table" not in first_caption + continued_caption
    assert continued_caption.startswith("Table 1.1 (continued).")


def test_results_overview_owns_its_caption_without_self_reference(monkeypatch):
    row = {
        "check": "Plastic bending",
        "case": "PL-1",
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
    assert table._cellvalues[0][0].getPlainText().startswith(
        "Table 0.1."
    )
    assert isinstance(table, sector_report._ResultsOverviewTable)
    assert table.keepWithNext == 0
    assert (
        "one governing row"
        in table._sector_trailing_note.getPlainText()
    )
    assert "See Table" not in table._cellvalues[0][0].getPlainText()


def test_multi_panel_table_publishes_one_destination_and_compact_captions():
    builder = _builder()
    headers = ["Spectrum", "Bin"] + [f"Result {index}" for index in range(7)]
    row = ["SPECTRUM-A", "BIN-123456789"] + ["1234567890.12345"] * 7
    builder._table(
        [headers, row],
        [25 * mm, 25 * mm] + [30 * mm] * 7,
        font=5.0,
        keep=False,
        repeat_cols=2,
    )

    tables = [
        item for item in builder.flow
        if isinstance(item, sector_report._PaginatedReportTable)
    ]
    assert len(tables) > 1
    assert tables[0]._cellvalues[0][0].getPlainText().startswith(
        "Table 0.1."
    )
    assert all(
        "See Table" not in table._cellvalues[0][0].getPlainText()
        and "Table 0.1 (continued)." in table._cellvalues[0][0].getPlainText()
        for table in tables[1:]
    )


def test_case_action_table_reserves_space_for_heading_and_input_table():
    inp = {
        "plastic_case": {"id": "PL-EDGE", "type": "ULS"},
        "_report_case_actions": {
            "n_ed_kn": 1.0,
            "mx_ed_knm": 2.0,
            "my_ed_knm": 3.0,
            "vx_ed_kn": 4.0,
            "vy_ed_kn": 5.0,
            "t_ed_knm": 6.0,
        },
    }
    builder = _builder(inp)
    builder._case_heading("Plastic section capacity", "plastic")

    nested = list(_all_flowables(builder.flow))
    assert any(isinstance(item, CondPageBreak) for item in nested)
    assert not any(isinstance(item, NotAtTopPageBreak) for item in nested)
    table = next(
        item for item in nested
        if isinstance(item, sector_report._PaginatedReportTable)
    )
    assert table._cellvalues[0][0].getPlainText().startswith(
        "Table 1.1."
    )


def test_exact_label_boundary_rejects_1_10_as_caption_for_1_1():
    with pytest.raises(AssertionError, match="strands the reference to Table 1.1"):
        validate_report_table_colocation([
            "See Table 1.1.\nTable 1.10. A different table",
        ])

    validate_report_table_colocation([
        "See Table 1.1.\nTable 1.1. The referenced table\n"
        "See Table 1.10.\nTable 1.10. A different table",
    ])


def test_report_page_with_only_dynamic_furniture_is_rejected():
    furniture = (
        "Project: QA-REFERENCE | Section: Reference section\n"
        "Rev: -\n"
        f"Sector {__version__}  -  fixture00000  -  Sweco Danmark A/S\n"
        "Page 3 of 59"
    )
    with pytest.raises(AssertionError, match="no report body"):
        validate_report_page_semantics([furniture])

    validate_report_page_semantics([
        furniture + "\nTable 1.1. Reported information",
    ])
