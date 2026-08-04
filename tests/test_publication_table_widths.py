"""PR-10B1a F032 report-table width and token contracts."""

from __future__ import annotations

import io
import pathlib
import sys

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, SimpleDocTemplate, Table

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import sector_report  # noqa: E402


def _builder():
    return sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, version="0.91", figures=False
    )


def _tables(builder):
    values = []
    for item in builder.flow:
        if isinstance(item, KeepTogether):
            values.extend(child for child in item._content if isinstance(child, Table))
        elif isinstance(item, Table):
            values.append(item)
    return values


def _plain(cell):
    return cell.getPlainText() if hasattr(cell, "getPlainText") else str(cell)


def _pixels(image):
    getter = getattr(image, "get_flattened_data", image.getdata)
    return getter()


def test_table_font_floor_and_rectangular_inventory_are_enforced():
    builder = _builder()
    builder._table(
        [["Point", "sigma (MPa)"], ["C1", "-12.5"]],
        [45 * mm, 45 * mm],
        font=5.0,
    )
    table = _tables(builder)[0]
    assert table._sector_font_size == sector_report._MIN_REPORT_TABLE_FONT == 7.2

    with pytest.raises(ValueError, match="same columns"):
        _builder()._table(
            [["ID", "A", "B"], ["row", "1"]],
            [30 * mm] * 3,
        )
    with pytest.raises(ValueError, match="widths must match"):
        _builder()._table([["ID", "A"], ["row", "1"]], [30 * mm])


@pytest.mark.parametrize("suffix", ["", " MPa", " (governing)"])
def test_long_identity_wraps_losslessly_while_numeric_tokens_remain_atoms(suffix):
    identity = "trace-sha256-" + "abcdef0123456789" * 14
    numeric = "1234567890.123456789"
    builder = _builder()
    builder._table(
        [["Identity", "Value"], [identity, numeric + suffix]],
        [40 * mm, 40 * mm],
        keep=False,
    )
    table = _tables(builder)[0]
    assert _plain(table._cellvalues[1][0]) == identity
    assert _plain(table._cellvalues[1][1]) == numeric + suffix
    assert sum(table._colWidths) <= sector_report._A4_CONTENT_WIDTH + 1e-7
    assert table._sector_width_floors[0] == pytest.approx(40 * mm)
    assert table._sector_width_floors[1] == pytest.approx(
        sector_report.pdfmetrics.stringWidth(
            numeric,
            table._cellvalues[1][1].style.fontName,
            table._cellvalues[1][1].style.fontSize,
        )
        + 2 * sector_report._REPORT_TABLE_HORIZONTAL_PADDING
    )


@pytest.mark.parametrize("suffix", ["", " MPa", " (governing)"])
def test_oversize_numeric_word_is_rejected_inside_any_cell_text(suffix):
    with pytest.raises(ValueError, match="indivisible numeric token"):
        _builder()._table(
            [["Identity", "Value"], ["row", "9" * 500 + suffix]],
            [30 * mm, 30 * mm],
        )


def test_wide_evidence_is_ordered_into_panels_with_repeated_identity_columns():
    number = "12345678901234567890.123456789"
    authored = [
        ["Step", "A", "B", "C", "D"],
        ["immutable-step-01", number + "1", number + "2", number + "3", number + "4"],
    ]
    builder = _builder()
    builder._table(
        authored,
        [28 * mm] * 5,
        keep=False,
        repeat_cols=1,
    )
    tables = _tables(builder)

    assert len(tables) > 1
    assert [table._sector_panel_number for table in tables] == list(
        range(1, len(tables) + 1)
    )
    assert all(table._sector_panel_count == len(tables) for table in tables)
    assert all(table._sector_source_columns[0] == 0 for table in tables)
    observed_nonidentity = []
    for table in tables:
        assert sum(table._colWidths) <= sector_report._A4_CONTENT_WIDTH + 1e-7
        for local, source in enumerate(table._sector_source_columns):
            assert _plain(table._cellvalues[1][local]) == authored[1][source]
        observed_nonidentity.extend(table._sector_source_columns[1:])
    assert observed_nonidentity == [1, 2, 3, 4]


def test_dense_panels_build_and_rasterise_inside_a4_without_token_loss():
    pdf = io.BytesIO()
    builder = _builder()
    number = "98765432109876543210.123456789"
    builder._table(
        [["ID", "A", "B", "C", "D"]]
        + [[f"ROW-{row}"] + [number + str(column) for column in range(4)]
           for row in range(18)],
        [28 * mm] * 5,
        keep=False,
        repeat_cols=1,
    )
    expected_panels = len(_tables(builder))
    doc = SimpleDocTemplate(
        pdf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=20 * mm,
    )
    doc.build(builder.flow)
    payload = pdf.getvalue()

    reader = pypdf.PdfReader(io.BytesIO(payload))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    extracted_lines = [line.strip() for line in text.splitlines()]
    for row in range(18):
        assert extracted_lines.count(f"ROW-{row}") == expected_panels
    for column in range(4):
        assert extracted_lines.count(number + str(column)) == 18

    pdfium = pytest.importorskip("pypdfium2")
    document = pdfium.PdfDocument(payload)
    try:
        for index in range(len(document)):
            page = document[index]
            try:
                bitmap = page.render(scale=1.0)
                try:
                    image = bitmap.to_pil().convert("L")
                    assert image.width / image.height == pytest.approx(
                        A4[0] / A4[1], rel=0.01
                    )
                    edge = max(2, int(image.width * 0.01))
                    assert min(_pixels(
                        image.crop((0, 0, edge, image.height))
                    )) > 245
                    assert min(_pixels(
                        image.crop((image.width - edge, 0, image.width, image.height))
                    )) > 245
                finally:
                    bitmap.close()
            finally:
                page.close()
    finally:
        document.close()
