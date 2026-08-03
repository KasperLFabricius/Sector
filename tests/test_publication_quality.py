"""PR-10 publication typography, continuation and provenance contracts."""

from __future__ import annotations

import io
import pathlib
import re
import sys

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table


ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import manual  # noqa: E402
import publication_notation as notation  # noqa: E402
import sector_report  # noqa: E402
from sector import torsion  # noqa: E402
from sector import torsion_trace_contract  # noqa: E402


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.234e-12, "<nobr>1.234 &#215; 10<super>-12</super></nobr>"),
        (-9.876e18, "<nobr>-9.876 &#215; 10<super>18</super></nobr>"),
        (12.5, "12.5"),
        (None, "-"),
    ],
)
def test_scientific_values_use_one_typographic_notation(value, expected):
    assert notation.scientific_markup(value, 4) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("25 mm2", "<nobr>25 mm<super>2</super></nobr>"),
        ("1.047 mm2/mm", "<nobr>1.047 mm<super>2</super>/mm</nobr>"),
        ("Area m2 and inertia m4", "Area <nobr>m<super>2</super></nobr> and inertia <nobr>m<super>4</super></nobr>"),
    ],
)
def test_plain_unit_powers_become_atomic_superscripts(source, expected):
    assert notation.normalise_unit_exponents(source) == expected
    assert notation.protect_numeric_tokens(expected) == expected


def _dense_table_pdf(
    row_count: int = 180,
) -> tuple[bytes, int, str, float, float, float, float]:
    builder = sector_report.ReportBuilder(io.BytesIO(), {}, {}, {}, figures=False)
    builder._chapter = 8
    builder._h1("Dense family")
    builder._h2("Candidate table")
    builder._status_block("Candidate independently reconstructed", "PASS")
    status_space_before = builder.flow[-2]._content[0].getSpaceBefore()
    data = [["Candidate", "Stress", "Area"]]
    data.extend([
        [
            f"C-{index:03d}",
            notation.scientific_markup((index + 1) * 1.234e-12, 5) + " MPa",
            f"{1000 + index}.25 mm2",
        ]
        for index in range(row_count)
    ])
    builder._table(data, [35 * mm, 60 * mm, 55 * mm], font=5.1, keep=False)
    table = next(item for item in builder.flow if isinstance(item, Table))
    repeat_rows = table.repeatRows
    context = table._cellvalues[0][0].getPlainText()
    minimum_font = min(
        cell.style.fontSize
        for row in table._cellvalues[2:]
        for cell in row
        if hasattr(cell, "style")
    )
    space_before = table.getSpaceBefore()
    gap_after = builder.flow[-1].height
    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    ).build(builder.flow)
    return (
        buffer.getvalue(), repeat_rows, context, minimum_font,
        space_before, gap_after, status_space_before,
    )


@pytest.mark.parametrize("row_count", [1, 12])
def test_small_and_default_tables_keep_identity_and_cardinality(row_count):
    fitz = pytest.importorskip("fitz")
    pdf, *_ = _dense_table_pdf(row_count)
    document = fitz.open(stream=pdf, filetype="pdf")
    assert document.page_count == 1
    text = document[0].get_text()
    assert "9. Dense family | Candidate table | Status: PASS" in " ".join(
        text.split()
    )
    assert len(re.findall(r"C-\d{3}", text)) == row_count


def test_dense_table_clamps_font_and_repeats_complete_context():
    fitz = pytest.importorskip("fitz")
    (
        pdf, repeat_rows, context_value, minimum_font, space_before, gap_after,
        status_space_before,
    ) = _dense_table_pdf()
    assert repeat_rows == 2
    assert context_value == (
        "9. Dense family | Candidate table | Status: PASS"
    )
    assert minimum_font == pytest.approx(notation.MIN_TABLE_FONT_SIZE)
    assert space_before >= 4.0
    assert gap_after >= 4.0
    assert status_space_before >= 4.0

    document = fitz.open(stream=pdf, filetype="pdf")
    assert document.page_count >= 3
    context = "9. Dense family | Candidate table | Status: PASS"
    for page in document:
        text = page.get_text()
        if "Candidate" in text:
            assert context in " ".join(text.split())
            assert len(re.findall(r"C-\d{3}", text)) >= 3
        lines = [
            line
            for block in page.get_text("dict")["blocks"]
            if "lines" in block
            for line in block["lines"]
            if any(span["text"].strip() for span in line["spans"])
        ]
        # ReportLab intentionally scales a superscript to 80% of its base font.
        # Every ordinary line must still contain a base span at the publication
        # minimum; checking every individual span would reject the exponent itself.
        assert min(max(span["size"] for span in line["spans"]) for line in lines) >= 7.15


def test_manual_and_report_share_the_unit_notation_layer():
    assert manual._inline_md_to_rl("$A_s = 25$ mm2") == (
        "A<sub>s</sub> = <nobr>25 mm<super>2</super></nobr>"
    )
    assert sector_report._fmt_sig(1.234e-12, 4) == notation.scientific_markup(
        1.234e-12, 4
    )
    assert notation.protect_numeric_tokens("finite: 196398721.0 1") == (
        "finite: <nobr>196398721.0 1</nobr>"
    )


def test_transverse_and_longitudinal_torsion_sources_are_not_conflated():
    transverse = torsion_trace_contract.TRANSVERSE_SOURCE.citation
    longitudinal = torsion_trace_contract.LONGITUDINAL_SOURCE.citation
    assert transverse.clause == "6.3.2(1) and 6.2.3(3)"
    assert transverse.locator == "Formulae (6.27) and (6.8)"
    assert longitudinal.locator == "Formula (6.28)"
    assert "6.27 + 6.8" in (torsion.__doc__ or "")

    report_source = (APP / "sector_report.py").read_text(encoding="utf-8")
    app_source = (APP / "sector_app.py").read_text(encoding="utf-8")
    manual_text = "\n".join(
        str(part) for block in manual.manual_blocks() for part in block[1:]
    )
    assert "Formula (6.27)" in report_source and "Formula (6.8)" in report_source
    assert "derived from 6.27 with transverse equilibrium in 6.8" in app_source
    assert "torsional wall force" in manual_text and "(6.27)" in manual_text
    assert "longitudinal steel" in manual_text and "(6.28)" in manual_text
