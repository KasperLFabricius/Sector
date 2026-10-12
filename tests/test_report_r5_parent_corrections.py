"""Keep physical values and evidence together after report-only corrections."""
from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import sector_report as report
import viz
from test_report import _inp
from test_report_heading_layout import _LabeledBlock, _pdf


@pytest.mark.parametrize("profile", ["Standard", "Audit"])
@pytest.mark.parametrize("preceding_height", [240, 340, 460])
def test_concrete_table_and_first_strength_equation_share_page(profile, preceding_height):
    builder = report.ReportBuilder(io.BytesIO(), {}, _inp(),
        {"material_properties": {"concrete": {"design_strength_mpa": 20.0}}},
        figures=False, profile=profile)
    builder._h1("Materials")
    builder.flow.append(_LabeledBlock(preceding_height, "PRECEDING EVIDENCE"))
    builder._h2("Concrete")
    builder._concrete_block()
    _, pages = _pdf(builder)
    table = [i for i, text in enumerate(pages) if "Characteristic strength" in text]
    result_label = "Equation (1.1)" if profile == "Audit" else "Final results and used design parameters"
    equation = [i for i, text in enumerate(pages) if result_label in text]
    assert len(table) == len(equation) == 1
    assert table == equation
    text = " ".join(pages[table[0]].split())
    assert "20.000 MPa" in text and "= 20 MPa" in text
    assert "Concrete" in text


@pytest.mark.parametrize("source,markup", [
    ("stirrups (VRd,s)", "stirrups (V<sub>Rd,s</sub>)"),
    ("crushing (VRd,max)", "crushing (V<sub>Rd,max</sub>)"),
    ("links (tau_Rd,sy)", "links (&#964;<sub>Rd,sy</sub>)"),
    ("compression field (sigma_cd)", "compression field (&#963;<sub>cd</sub>)"),
    ("stirrups (TRd,s)", "stirrups (T<sub>Rd,s</sub>)"),
    ("crushing (TRd,max)", "crushing (T<sub>Rd,max</sub>)"),
])
def test_only_exact_known_resistance_labels_get_math_markup(source, markup):
    assert report._report_resistance_governing_label(source) == markup
    for literal in (source + " USER sigma", "<sub>user</sub> & " + source):
        assert report._report_resistance_governing_label(literal) == report._html_escape(literal)


def test_report_torsion_labels_preserve_native_geometry_and_default_labels():
    outer = [(-.15, -.3), (.15, -.3), (.15, .3), (-.15, .3)]
    args = (outer, [], 40.)
    native = viz.tube_figure(*args, ak_m2=.14, title="Literal & <sub>ID</sub>")
    before = native.to_plotly_json()
    updated = viz.tube_figure(*args, ak_m2=.14, title="Literal & <sub>ID</sub>", report_labels=True)
    expected = copy.deepcopy(before)
    expected["data"][1]["name"] = "inner wall face (t<sub>ef</sub> = 40 mm)"
    expected["data"][2]["name"] = "wall center-line (A<sub>k</sub> = 140,000 mm<sup>2</sup>)"
    assert updated.to_plotly_json() == expected
    assert native.to_plotly_json() == before
    assert before["data"][1]["name"] == "inner wall face (t<sub>ef</sub> = 40 mm)"


def test_crack_area_annotation_has_clearance_above_native_geometry():
    from test_report_diagrams import _beam, _retained
    import report_diagrams

    inp = _beam()
    crack, state = _retained(inp)
    before = copy.deepcopy((inp, crack, state))
    figure = report_diagrams.crack_effective_area_figure(inp, crack, state, title="Crack area")
    note = next(item for item in figure.layout.annotations if "Effective area:" in item.text)
    assert note.yref == "paper" and note.yanchor == "bottom" and note.y >= 1.04
    assert figure.layout.margin.t >= 145
    assert (inp, crack, state) == before
