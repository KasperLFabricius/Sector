"""Native PDF pagination contracts for headings and bounded report blocks."""

from __future__ import annotations

import io

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Flowable

from app import sector_report as report


class _LabeledBlock(Flowable):
    """An indivisible block with a known height and visible identity."""

    def __init__(self, height, label):
        super().__init__()
        self.width = 450
        self.height = height
        self.label = label

    def draw(self):
        self.canv.drawString(0, 5, self.label)


def _builder(profile):
    return report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, profile=profile
    )


def _pdf(builder):
    stream = io.BytesIO()
    document = report._ReportDocTemplate(
        stream, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=25 * mm, bottomMargin=20 * mm,
    )
    # Multi-pass construction also checks that heading layout survives the
    # production document's indexing lifecycle.
    document.multiBuild(builder.flow)
    reader = pypdf.PdfReader(io.BytesIO(stream.getvalue()))
    return reader, [page.extract_text() for page in reader.pages]


def _page(texts, token):
    matches = [index for index, text in enumerate(texts) if token in text]
    assert len(matches) == 1, (token, matches)
    return matches[0]


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_chapter_heading_stays_with_first_status_banner(profile):
    builder = _builder(profile)
    builder.flow.append(_LabeledBlock(640, "PRECEDING CONTENT"))
    builder._h1("Grouped fatigue")
    builder._status_block("FIRST STATUS DATA", "PASS")

    reader, texts = _pdf(builder)

    assert _page(texts, "Grouped fatigue") == _page(texts, "FIRST STATUS DATA")
    assert _page(texts, "PRECEDING CONTENT") < _page(texts, "FIRST STATUS DATA")
    assert reader.get_destination_page_number(reader.outline[0]) == _page(
        texts, "Grouped fatigue"
    )


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_subheading_stays_with_first_bounded_figure_group(profile):
    builder = _builder(profile)
    builder._h1("Crack calculations")
    builder.flow.append(_LabeledBlock(430, "PRECEDING CONTENT"))
    builder._h2("Coarse crack worked example")
    start = len(builder.flow)
    builder.flow.append(_LabeledBlock(250, "FIRST FIGURE DATA"))
    builder._small("Interpret the section and its effective concrete area.")
    builder._keep_from(start)

    reader, texts = _pdf(builder)

    page = _page(texts, "Coarse crack worked example")
    assert page == _page(texts, "FIRST FIGURE DATA")
    assert page == _page(texts, "Interpret the section")
    assert reader.get_destination_page_number(reader.outline[1][0]) == page


def test_explicit_heading_intro_and_map_group_stays_together():
    builder = _builder("Audit")
    builder.flow.append(_LabeledBlock(430, "PRECEDING CONTENT"))
    start = len(builder.flow)
    builder._h1("Current elastic case")
    builder._h2("Section stress and strain", reserve=0)
    builder._p("The maps use the same calculated section state.")
    builder.flow.append(_LabeledBlock(250, "MAP WITH EXTREMA"))
    builder._keep_from(start)

    reader, texts = _pdf(builder)

    map_page = _page(texts, "MAP WITH EXTREMA")
    for token in (
        "Current elastic case", "Section stress and strain",
        "The maps use the same calculated section state.",
    ):
        assert _page(texts, token) == map_page
    assert reader.get_destination_page_number(reader.outline[0]) == map_page
    assert reader.get_destination_page_number(reader.outline[1][0]) == map_page


def test_heading_protection_keeps_long_table_pageable_and_complete():
    builder = _builder("Audit")
    builder.flow.append(_LabeledBlock(600, "PRECEDING CONTENT"))
    builder._h1("Long result register")
    builder._table(
        [["Row identity", "Result"]]
        + [[f"UNIQUE-ROW-{index:03d}", str(index)] for index in range(80)],
        [100 * mm, 60 * mm], caption="Complete result register",
    )

    _, texts = _pdf(builder)

    assert _page(texts, "1. Long result register\n") == _page(texts, "UNIQUE-ROW-000")
    assert _page(texts, "UNIQUE-ROW-079") > _page(texts, "UNIQUE-ROW-000")
    combined = "\n".join(texts)
    for index in range(80):
        assert combined.count(f"UNIQUE-ROW-{index:03d}") == 1
    for text in texts:
        if "UNIQUE-ROW-" in text:
            assert "Row identity" in text
            assert "Complete result register" in text


def test_chapter_and_subheading_chain_survives_conditional_page_break():
    builder = _builder("Audit")
    builder.flow.append(_LabeledBlock(430, "PRECEDING CONTENT"))
    builder._h1("New calculation family", reserve=170)
    builder._h2("First bounded calculation")
    start = len(builder.flow)
    builder.flow.append(_LabeledBlock(250, "FIRST CALCULATION DATA"))
    builder._keep_from(start)

    reader, texts = _pdf(builder)

    page = _page(texts, "FIRST CALCULATION DATA")
    assert _page(texts, "New calculation family") == page
    assert _page(texts, "First bounded calculation") == page
    assert page == 1
    assert reader.get_destination_page_number(reader.outline[0]) == page
    assert reader.get_destination_page_number(reader.outline[1][0]) == page


def test_first_equation_keeps_heading_source_and_equation_contract():
    builder = _builder("Audit")
    builder.flow.append(_LabeledBlock(600, "PRECEDING CONTENT"))
    builder._h1("Plastic equilibrium")
    builder._formula(
        "F<sub>c</sub> + F<sub>s</sub> + F<sub>p</sub> - N = 0",
        ref="LAYOUT SOURCE ID",
        equation_key="basis.plastic.equilibrium",
    )
    equations = []
    for item in builder.flow:
        if isinstance(item, report._EquationFlowable):
            equations.append(item)
        equations.extend(getattr(item, "_sector_equations", ()))
    assert len(equations) == 1
    equation = equations[0]
    assert equation._sector_equation_key == "basis.plastic.equilibrium"
    assert equation._sector_equation_number == "1.1"
    assert len(equation._sector_equation_symbols) == 7
    assert equation._sector_equation_roles.count("source") == 1
    assert equation._sector_equation_roles.count("symbol") == 7

    reader, texts = _pdf(builder)

    page = _page(texts, "Plastic equilibrium")
    assert page == _page(texts, "Equation (1.1)")
    assert page == _page(texts, "Symbols:")
    assert page == _page(texts, "LAYOUT SOURCE ID")
    assert reader.get_destination_page_number(reader.outline[0]) == page


def test_heading_absorption_preserves_adjacent_standard_result_identity():
    builder = _builder("Standard")
    builder._h1("Adjacent final results")
    builder._standard_result_projection(
        "result-a", "a", "UNIQUE RESULT A", "SOURCE A", "", "a = 1"
    )
    builder._standard_result_projection(
        "result-b", "b", "UNIQUE RESULT B", "SOURCE B", "", "b = 2"
    )

    _, texts = _pdf(builder)

    combined = "\n".join(texts)
    for token in ("UNIQUE RESULT A", "UNIQUE RESULT B", "SOURCE A", "SOURCE B"):
        assert combined.count(token) == 1
    assert _page(texts, "UNIQUE RESULT A") == _page(texts, "UNIQUE RESULT B")


@pytest.mark.parametrize("helper", ["_keep_from", "_keep_measured_calculation_from"])
def test_regrouping_preserves_original_equation_audit_metadata(helper):
    builder = _builder("Audit")
    builder._h1("Retained equation identity")
    builder._formula(
        "F<sub>c</sub> + F<sub>s</sub> + F<sub>p</sub> - N = 0",
        ref="RETAINED SOURCE ID",
        equation_key="basis.plastic.equilibrium",
    )
    original = tuple(getattr(builder.flow[0], "_sector_equations", ()))
    assert len(original) == 1
    builder._small("The source and symbol inventory stay with this calculation.")

    getattr(builder, helper)(0)

    retained = tuple(getattr(builder.flow[0], "_sector_equations", ()))
    assert retained == original
    assert retained[0] is original[0]
    _, texts = _pdf(builder)
    assert _page(texts, "RETAINED SOURCE ID") == _page(texts, "Symbols:")
