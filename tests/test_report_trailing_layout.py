"""Keep report qualifications with the evidence they explain."""
from __future__ import annotations

import io

import pytest
from reportlab.platypus import Paragraph
from test_report import _fatigue_report_fixture
from test_report_heading_layout import _LabeledBlock, _pdf

from app import sector_report as report


def test_standard_initial_prestress_schedules_stay_with_resultant_summary():
    elements = [
        {"element_id": f"P{index + 1}", "material_id": "P1",
         "modulus_mpa": 195000., "initial_strain": .005,
         "locked_in_stress_mpa": 975., "area_mm2": 150.,
         "force_kn": 146.25, "x_m": x, "y_m": y,
         "mx_knm": 146.25 * y, "my_knm": 146.25 * x}
        for index, (x, y) in enumerate(((-.1, -.2), (.1, -.2),
                                      (-.1, .2), (.1, .2)))
    ]
    payload = {"elements": elements, "internal_resultant_origin": {
        "n_kn": 585., "mx_knm": 0., "my_knm": 0.}}
    builder = report.ReportBuilder(io.BytesIO(), {}, {},
        {"prestress_initial": payload}, figures=False, profile="Standard")
    builder._h1("Retained material values")
    builder.flow.append(_LabeledBlock(300, "Earlier material definition"))
    builder._prestress_initial_block()
    _, pages = _pdf(builder)
    matches = [text for text in pages if "Initial prestress action" in text]
    assert len(matches) == 1
    text = matches[0]
    for token in ("195000.0", "0.005000", "975.000", "146.250",
                  "-29.250", "14.625", "= 585", "= 0",
                  "Tendon internal tensile-force resultant",
                  "Tendon internal moment resultant about the section x-axis",
                  "Tendon internal moment resultant about the section y-axis"):
        assert token in " ".join(text.split())


def test_standard_large_prestress_schedule_splits_and_retains_every_tendon():
    elements = [
        {"element_id": f"TENDON-{index:03d}", "material_id": "P1",
         "modulus_mpa": 195000., "initial_strain": .005,
         "locked_in_stress_mpa": 975., "area_mm2": 150.,
         "force_kn": 146.25, "x_m": 0., "y_m": 0.,
         "mx_knm": 0., "my_knm": 0.}
        for index in range(60)
    ]
    payload = {"elements": elements, "internal_resultant_origin": {
        "n_kn": 8775., "mx_knm": 0., "my_knm": 0.}}
    builder = report.ReportBuilder(io.BytesIO(), {}, {},
        {"prestress_initial": payload}, figures=False, profile="Standard")
    builder._h1("Retained material values")
    builder._prestress_initial_block()
    _, pages = _pdf(builder)
    assert len(pages) > 1
    text = " ".join(" ".join(pages).split())
    for element in elements:
        # Each tendon occurs once in each of the two retained schedules.
        assert text.count(element["element_id"]) == 2
    assert "= 8775" in text
    assert "Tendon internal tensile-force resultant" in text
    assert "Tendon internal moment resultant about the section x-axis" in text
    assert "Tendon internal moment resultant about the section y-axis" in text


@pytest.mark.parametrize("role", ["body", "small"])
def test_body_paragraph_split_leaves_at_least_two_lines_on_each_page(role):
    style = report._styles()[role]
    paragraph = Paragraph(" ".join(f"word{i}" for i in range(30)), style)
    paragraph.wrap(100, 1000)
    original_lines = len(paragraph.blPara.lines)
    assert original_lines > 3
    parts = paragraph.split(100, style.leading * (original_lines - 1) + .1)
    assert len(parts) == 2
    for part in parts:
        part.wrap(100, 1000)
    assert [len(part.blPara.lines) for part in parts] == [original_lines - 2, 2]


def test_method_qualification_precedes_its_schedule():
    builder = report.ReportBuilder(io.BytesIO(), {}, {"shear_on": True,
        "shear_method": "EC2_2005_DK_2024"}, {}, figures=False, profile="Standard")
    builder._h1("Conventions")
    builder._method_register()
    _, pages = _pdf(builder)
    text = " ".join(" ".join(pages).split())
    assert text.index("Check project adoption") < text.index("Check family")
    assert text.count("Each result chapter gives") == 1
    assert "Concrete, link and longitudinal chord resistance" in text


@pytest.mark.parametrize("profile", ["Standard", "Audit"])
def test_percentage_qualifications_precede_the_reference_table(profile, monkeypatch):
    element = {"element_id": "ROW-ID", "material_id": "M1", "x_mm": 0., "y_mm": 0.,
               "area_mm2": 100., "strain_permille": 1., "total_mpa": 20.,
               "long_mpa": 10., "dif_mpa": 10., "rst1_mpa": 5.}
    inp = {"bars": [], "tendons": []}
    out = {"elastic": {"na_x": 0., "na_y": 0., "elements": [element]}}
    builder = report.ReportBuilder(io.BytesIO(), {}, inp, out, figures=False, profile=profile)
    builder._case_heading = lambda *a, **k: builder._h1("Elastic section")
    builder._selected_family = lambda *a: None
    builder._section_field_maps = lambda *a, **k: None
    monkeypatch.setattr(report.elastic_display, "element_comparison_rows", lambda *a: [
        {"Element": "PERCENTAGE-ID", "Material": "M1", "Reference": "f_yk",
         **{label: 10. for _, label in report.elastic_display.COMPONENTS}}])
    builder._elastic()
    _, pages = _pdf(builder)
    text = " ".join(" ".join(pages).split())
    for qualification in ("The percentage is the absolute stress", "These percentages do not assess compliance"):
        assert text.count(qualification) == 1
        assert text.index(qualification) < text.index("PERCENTAGE-ID")


def test_standard_concrete_fatigue_outcome_precedes_supporting_search_and_bins():
    inp, out = _fatigue_report_fixture()
    completed = dict(out)
    completed["worked_example_selection"] = report.presentation.worked_example_selection(inp, completed)
    builder = report.ReportBuilder(io.BytesIO(), {}, inp, completed, figures=False, profile="Standard")
    builder._fatigue()
    _, pages = _pdf(builder)
    text = "\n".join(pages)
    start = text.index("Governing concrete fatigue result")
    assert start < text.index("Governing concrete fiber", start)
    assert start < text.index("Bounded governing-fiber search", start)
    assert "Final results and used design parameters" in text[start:]


@pytest.mark.parametrize("family", ["minimum_reinforcement", "transverse_reinforcement"])
def test_detailing_scope_precedes_calculation_evidence(family):
    if family == "minimum_reinforcement":
        result = {"status": "PASS", "edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
                  "checks": [{"type": "minimum area", "status": "PASS", "axis": "xy",
                    "face": "resultant tension zone", "as_provided_mm2": 628.,
                    "as_min_mm2": 81.432, "utilisation": 81.432 / 628., "bt_mm": 200.,
                    "d_mm": 270., "fctm_mpa": 2.9, "fyk_mpa": 500.,
                    "strength_coefficient": .001508, "floor_coefficient": .0013,
                    "selected_coefficient": .001508, "governing_coefficient": "0.26 fctm / fyk",
                    "bar_ids": ["R1", "R2"]}]}
    else:
        result = {"status": "PASS", "checks": [{"kind": "minimum_ratio", "scope": "Shear VY",
                  "status": "PASS", "provided": .0012, "limit": .00069,
                  "utilisation": .575, "clause": "9.2.2(5)"}]}
    result["limitations"] = ["SCOPE-FIRST: retained check boundary.", "SCOPE-LAST: retained project boundary."]
    builder = report.ReportBuilder(io.BytesIO(), {}, {}, {family: result}, figures=False, profile="Standard")
    builder._case_heading = lambda *a, **k: builder._h1("Detailing")
    builder._selected_family = lambda *a: None
    getattr(builder, "_" + family)()
    _, pages = _pdf(builder)
    text = " ".join(" ".join(pages).split())
    assert text.count("SCOPE-FIRST") == text.count("SCOPE-LAST") == 1
    assert text.index("SCOPE-FIRST") < text.index("SCOPE-LAST") < text.index("Table 1.1")
