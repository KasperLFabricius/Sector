"""Figures-off retains report evidence without constructing graphical objects."""
from __future__ import annotations

import copy
import io
import pathlib
import pickle
import sys
from unittest.mock import MagicMock

import pytest
from pypdf import PdfReader

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

from tools import report_render_fixture
import sector_report
import test_report as report_data


@pytest.fixture
def forbid_graphics(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Figures-off constructed a figure or started image export")

    for module in (sector_report.viz, sector_report.report_diagrams):
        for name in dir(module):
            if name.endswith("_figure") and callable(getattr(module, name)):
                monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(sector_report.section_fields, "field_pair", forbidden)
    monkeypatch.setattr(sector_report, "ensure_image_server", forbidden)
    monkeypatch.setattr(sector_report, "_fig_png", forbidden)


def test_native_all_profiles_keep_evidence_without_any_figure_factory(forbid_graphics):
    inp = report_render_fixture._inputs()
    out = report_render_fixture._results(inp)
    frozen = pickle.dumps((inp, out))
    for profile in ("Brief", "Standard", "Audit"):
        report_inp, report_out = copy.deepcopy((inp, out))
        report_evidence = pickle.dumps((report_inp, report_out))
        pdf = sector_report.build_report(
            {}, report_inp, report_out, figures=False, profile=profile,
        )
        assert pickle.dumps((report_inp, report_out)) == report_evidence
        reader = PdfReader(io.BytesIO(pdf))
        text = " ".join(" ".join((page.extract_text() or "").split()) for page in reader.pages)
        assert reader.pages
        assert f"Report profile {profile}" in text
        for retained_identity in ("PL-QA-1", "PL-QA-2", "EL-QA-1", "EL-QA-2", "Road traffic"):
            assert retained_identity in text
        assert "Plastic bending" in text and "Fatigue" in text
        assert "PASS" in text and "FAIL" in text
    assert pickle.dumps((inp, out)) == frozen


def test_optional_nm_route_keeps_diagnostic_text_without_figure_factory(forbid_graphics):
    # Exercise the optional route with bounded retained adapter data. Its invalid
    # boundary warning must survive figures-off independently of the chart.
    plastic = copy.deepcopy(report_data._out()["plastic"])
    plastic["interaction"] = {
        axis: {"N": [-100., 0., 100.], "M": [0., 50., 0.],
               "converged": False, "applied": (0., 20.)}
        for axis in ("x", "y")
    }
    builder = MagicMock()
    builder.figures = False
    builder.profile.key = "Standard"
    builder.inp = report_data._inp()
    builder.out = {"plastic": plastic}
    builder._selected_family.return_value = None
    sector_report.ReportBuilder._plastic(builder)
    headings = [call.args[0] for call in builder._h2.call_args_list]
    assert "Axial-moment (N-M<sub>x</sub>) interaction" in headings
    assert "Axial-moment (N-M<sub>y</sub>) interaction" in headings
    assert any("One or more points did not converge" in call.args[0]
               for call in builder._status_block.call_args_list)
    builder._fig.assert_not_called()


def test_optional_subtube_route_keeps_all_tables_and_equations_without_factory(forbid_graphics):
    # Reuse the established retained component operands, not a second solver.
    subs = [report_data._subtube(300, 600, 100., .1, .0037, 24.6, 90.,
                                 24.6 / 90., "stirrups (TRd,s)", 0., -100.),
            report_data._subtube(1000, 200, 91., .15, .0023, 15.4, 20.,
                                 15.4 / 20., "crushing (TRd,max)", 0., 300.,
                                 bar_position_start=5)]
    for sub, area in zip(subs, (850., 550.)):
        sub["asl_req"] = area
    stiffness = sum(sub["stiffness"] for sub in subs)
    result = {"subtubes": subs, "util": max(sub["util"] for sub in subs),
              "trd": sum(sub["trd"] for sub in subs),
              "governing_sub": max(range(2), key=lambda index: subs[index]["util"]),
              "asl_req": 1400., "torque_distribution": {
                  "applied_torque": 40., "positive_stiffness_sum": stiffness,
                  "shares": tuple({"stiffness": sub["stiffness"],
                                   "fraction": sub["stiffness"] / stiffness,
                                   "torque": sub["t_ed"]} for sub in subs)}}
    builder = MagicMock()
    builder.figures = False
    sector_report.ReportBuilder._subtube_section(builder, result)
    assert builder._table.call_count >= 3
    keys = {call.kwargs.get("equation_key") for call in builder._formula.call_args_list}
    assert {"torsion.subtube.stiffness-share", "torsion.subtube.torque-share"} <= keys
    assert any("Total required longitudinal steel" in call.args[0]
               and "1400" in call.args[0] for call in builder._small.call_args_list)
    builder._fig.assert_not_called()
