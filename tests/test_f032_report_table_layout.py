"""Independent F032 contract tests for report-table width publication."""

from __future__ import annotations

import io
import pathlib
import sys

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import KeepTogether, SimpleDocTemplate, Table

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import sector_report  # noqa: E402
import case_analysis  # noqa: E402
import fatigue_inputs  # noqa: E402
import load_cases  # noqa: E402


def _builder():
    return sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, qa_appendix=False
    )


def _tables(builder):
    values = []
    for item in builder.flow:
        if isinstance(item, KeepTogether):
            values.extend(child for child in item._content if isinstance(child, Table))
        elif isinstance(item, Table):
            values.append(item)
    return values


def _pdf(builder):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=20 * mm,
    )
    doc.build(builder.flow)
    return buffer.getvalue()


def test_table_contract_rejects_incomplete_column_inventories():
    builder = _builder()

    with pytest.raises(ValueError, match="at least one cell"):
        builder._table([], [])
    with pytest.raises(ValueError, match="same columns"):
        builder._table([["A", "B"], ["only A"]], [30 * mm, 30 * mm])
    with pytest.raises(ValueError, match="widths must match"):
        builder._table([["A", "B"], ["1", "2"]], [30 * mm])


def test_small_tables_retain_the_minimum_type_and_authored_order():
    builder = _builder()
    builder._table(
        [["Identity", "Value"], [sector_report._html_escape("BIN-01"), "12.3"]],
        [35 * mm, 35 * mm],
        font=4.8,
    )

    table, = _tables(builder)
    assert table._sector_font_size == pytest.approx(7.2)
    assert table._sector_source_columns == (0, 1)
    assert table._sector_panel_number == 1
    assert table._sector_panel_count == 1


@pytest.mark.parametrize("separator", ["-", "/", ":", " "])
def test_digit_only_identifier_segments_remain_wrappable(separator):
    builder = _builder()
    identifier = sector_report._html_escape("BIN" + separator + "7" * 320)
    builder._table(
        [["Published bin", "Value"], [identifier, "1.000"]],
        [32 * mm, 28 * mm],
        keep=False,
    )

    table, = _tables(builder)
    identity_floor, value_floor = table._sector_width_floors
    assert identity_floor <= 32 * mm + 1e-7
    assert value_floor <= 28 * mm + 1e-7
    assert _pdf(builder).startswith(b"%PDF")


@pytest.mark.parametrize(
    "cell",
    [
        "{atom}",
        "{atom} MPa",
        "{atom} (governing)",
        "{atom}<br/>Method 2023",
    ],
)
def test_numeric_atoms_are_measured_inside_mixed_markup(cell):
    builder = _builder()
    atom = "123456789012345678901234567890"
    rendered = cell.format(atom=atom)
    builder._table(
        [["Identity", "Evidence"], [sector_report._html_escape("BIN-A"), rendered]],
        [30 * mm, 140 * mm],
        keep=False,
    )

    table, = _tables(builder)
    measured = pdfmetrics.stringWidth(
        atom, sector_report._FONT, sector_report._MIN_REPORT_TABLE_FONT
    )
    assert table._sector_width_floors[1] >= (
        measured + 2 * sector_report._REPORT_TABLE_HORIZONTAL_PADDING
    )


def test_escaped_equation_text_retains_its_explicit_numeric_evidence():
    builder = _builder()
    atom = "123456789012345678901234567890"
    markup = sector_report._html_escape(f"CALCULATED: {atom} MPa")
    evidence = sector_report._numerical_table_text(markup, atom)
    builder._table(
        [["Equation", "Result"],
         [sector_report._html_escape("equation-01"), evidence]],
        [30 * mm, 140 * mm],
        keep=False,
    )

    table, = _tables(builder)
    measured = pdfmetrics.stringWidth(
        atom, sector_report._FONT, sector_report._MIN_REPORT_TABLE_FONT
    )
    assert table._sector_width_floors[1] >= (
        measured + 2 * sector_report._REPORT_TABLE_HORIZONTAL_PADDING
    )


@pytest.mark.parametrize(
    "cell",
    [
        "{atom} MPa",
        "{atom}<br/>Method 2023",
        "Result = {atom} (governing)",
    ],
)
def test_indivisible_numeric_evidence_wider_than_a4_fails_explicitly(cell):
    builder = _builder()
    rendered = cell.format(atom="9" * 240)

    with pytest.raises(ValueError, match="numeric evidence wider"):
        builder._table(
            [["Identity", "Evidence"],
             [sector_report._html_escape("BIN-A"), rendered]],
            [30 * mm, 140 * mm],
        )


def test_dense_tables_form_ordered_panels_with_repeated_identity_columns():
    builder = _builder()
    headers = ["Spectrum", "Bin"] + [f"Result {index}" for index in range(1, 8)]
    row = [
        sector_report._html_escape("SPECTRUM-A"),
        sector_report._html_escape("BIN-123456789"),
    ] + [f"{index}234567890.12345" for index in range(1, 8)]
    builder._table(
        [headers, row],
        [25 * mm, 25 * mm] + [30 * mm] * 7,
        font=5.0,
        keep=False,
        repeat_cols=2,
    )

    tables = _tables(builder)
    assert len(tables) > 1
    assert all(table._sector_font_size == pytest.approx(7.2) for table in tables)
    assert all(table._sector_source_columns[:2] == (0, 1) for table in tables)
    emitted = [
        column
        for table in tables
        for column in table._sector_source_columns[2:]
    ]
    assert emitted == list(range(2, 9))
    assert all(sum(table._colWidths) <= sector_report._A4_CONTENT_WIDTH + 1e-7
               for table in tables)

    pdf = _pdf(builder)
    import pypdf
    import pypdfium2

    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = " ".join(page.extract_text() or "" for page in reader.pages)
    for value in row[2:]:
        assert text.count(value) == 1

    raster = pypdfium2.PdfDocument(pdf)
    for page in raster:
        image = page.render(scale=1).to_pil().convert("RGB")
        assert all(image.getpixel((0, y)) == (255, 255, 255)
                   for y in range(image.height))
        assert all(image.getpixel((image.width - 1, y)) == (255, 255, 255)
                   for y in range(image.height))


def test_load_tables_declare_their_complete_composite_row_identities():
    defaults = load_cases.default_tables()
    fatigue_record = {
        fatigue_inputs.SPECTRUM: "SP-1",
        fatigue_inputs.NAME: "BIN-1",
        fatigue_inputs.DESCRIPTION: "Description",
        fatigue_inputs.CYCLES: 1.0,
        **{column: 0.0 for column in fatigue_inputs.ACTION_COLUMNS},
    }
    inp = {
        "mode": "Both",
        "plastic_cases": defaults[load_cases.PLASTIC_TABLE_KEY],
        "elastic_cases": defaults[load_cases.ELASTIC_TABLE_KEY],
        "fatigue_on": True,
        fatigue_inputs.SPECTRUM_TABLE_KEY: fatigue_inputs.spectrum_from_records(
            [fatigue_record]
        ),
    }
    plastic = case_analysis.case_records(inp, "plastic")
    elastic = case_analysis.case_records(inp, "elastic")
    out = {
        "plastic_cases": [{"actions": plastic[0], "results": {}}],
        "elastic_cases": [{"actions": elastic[0], "results": {}}],
    }
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, inp, out, figures=False, qa_appendix=False
    )
    captured = {}

    def capture(data, widths, **kwargs):
        captured[tuple(data[0])] = kwargs.get("repeat_cols", 1)

    builder._table = capture
    builder._loads_block()

    assert captured[next(header for header in captured
                         if header[:3] == ("Case", "Description", "N<sub>Ed</sub>"))] == 2
    assert captured[next(header for header in captured
                         if header[:3] == ("Case", "Description", "Part"))] == 3
    assert captured[next(header for header in captured
                         if header[:3] == ("Spectrum", "Bin", "Description"))] == 3
