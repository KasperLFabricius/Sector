"""Independent ownership and availability checks for combined chord figures."""
from __future__ import annotations

import copy
import io
from html import unescape
import pathlib
import pickle
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "app")]

import sector_report as report
from sector import codes
from tools import report_render_fixture


def _rows():
    return [dict(axis=axis, tension_low=low, valid=True, conditional=True,
                 m_total=demand, m_rd=capacity)
            for axis, low, demand, capacity in (
                ("x", True, 123.456789, 145.678912), ("x", False, 0., 73.25),
                ("y", True, 14.75, 0.), ("y", False, 56.125, 43.875))]


def _unit(monkeypatch, *, direction=None):
    builder = object.__new__(report.ReportBuilder)
    builder.figures = True
    builder.inp = {"plastic_case": {"id": "Combined <case>"}}
    c = {"component": direction or "vy", "longitudinal_candidates": _rows()}
    builder.out = {"combined": c if direction is None else {"directions": {direction: c}}}
    longitudinal = {"chord_status": "FAIL", "assessment": {"chord_coverage_complete": True}}
    figures, notes = [], []
    builder._fig = lambda figure, *a, **kw: figures.append((figure, kw["caption"]))
    builder._small = notes.append
    monkeypatch.setattr(report.presentation, "combined_publication_evidence_is_current", lambda *a: (True, None))
    monkeypatch.setattr(report.presentation, "combined_physical_components", lambda c: [
        {"key": "concrete", "angle_valid": True, "theta_deg": 31.25}])
    return builder, c, longitudinal, figures, notes


@pytest.mark.parametrize("direction", [None, "vx", "vy"])
def test_owned_combined_chart_retains_exact_candidates_and_context(monkeypatch, direction):
    builder, c, longitudinal, figures, notes = _unit(monkeypatch, direction=direction)
    original = pickle.dumps((builder.inp, builder.out, longitudinal))
    builder._combined_chord_diagram(c, longitudinal)
    assert len(figures) == 1
    figure, caption = figures[0]
    assert list(figure.data[0].x) == [row["m_total"] for row in c["longitudinal_candidates"]]
    assert list(figure.data[1].x) == [row["m_rd"] for row in c["longitudinal_candidates"]]
    assert "Case Combined <case>" in unescape(caption)
    assert "<case>" not in caption
    assert f"shear component {'Vx' if direction == 'vx' else 'Vy'}" in caption
    assert "31.25 degrees" in caption
    assert "zero demand" in " ".join(notes)
    assert pickle.dumps((builder.inp, builder.out, longitudinal)) == original


@pytest.mark.parametrize("attack", [
    "figures-off", "stale-case", "stale-evidence", "foreign-copy", "foreign-direction",
    "incomplete", "diagnostic", "not-requested", "missing-candidates", "substitute", "duplicate-face",
])
def test_combined_chart_withholds_unpublishable_evidence(monkeypatch, attack):
    builder, c, longitudinal, figures, notes = _unit(monkeypatch, direction="vy")
    if attack == "figures-off":
        builder.figures = False
    elif attack == "stale-case":
        builder.inp["_report_case_current"] = False
    elif attack == "stale-evidence":
        monkeypatch.setattr(report.presentation, "combined_publication_evidence_is_current", lambda *a: (False, "stale"))
    elif attack == "foreign-copy":
        c = copy.deepcopy(c)
    elif attack == "foreign-direction":
        c["component"] = "vx"
    elif attack == "incomplete":
        longitudinal["assessment"]["chord_coverage_complete"] = False
    elif attack in {"diagnostic", "not-requested"}:
        longitudinal["chord_status"] = "NOT ASSESSED" if attack == "diagnostic" else "NOT REQUESTED"
    elif attack == "missing-candidates":
        c.pop("longitudinal_candidates")
    elif attack == "substitute":
        c["longitudinal_candidates"][0]["conditional"] = False
    elif attack == "duplicate-face":
        c["longitudinal_candidates"].append(dict(c["longitudinal_candidates"][0]))
    builder._combined_chord_diagram(c, longitudinal)
    assert not figures
    if attack in {"missing-candidates", "substitute", "duplicate-face"}:
        assert any("unavailable" in note for note in notes)


@pytest.mark.parametrize("basis", [codes.EC2_2005_DKNA, codes.EC2_2005])
def test_native_combined_route_uses_its_case_when_shear_governs_elsewhere(basis):
    inp = report_render_fixture._inputs()
    inp["plastic_cases"][0].update(mx_ed_knm=80., vy_ed_kn=150., t_ed_knm=1.)
    inp["plastic_cases"][1].update(mx_ed_knm=30., vy_ed_kn=10., t_ed_knm=100.)
    inp.update(combined_method=basis.label, shear_method=basis.label, torsion_method=basis.label,
               elastic_on=False, fatigue_on=False)
    out = report_render_fixture._results(inp)
    out["worked_example_selection"] = report.presentation.worked_example_selection(inp, out)
    selected = out["worked_example_selection"]["families"]
    target_case = "PL-QA-2"
    assert selected["shear"]["case_id"] != target_case
    if basis == codes.EC2_2005_DKNA:
        assert selected["combined"]["case_id"] == target_case
    # Base EN publishes independent physical components for each case. It has
    # no aggregate verdict with which to rank the two combined cases.
    frozen = pickle.dumps((inp, out))
    builder = report.ReportBuilder(io.BytesIO(), {}, inp, out, profile="Standard", figures=True)
    captures = []
    builder._fig = lambda figure, *a, **kw: captures.append((figure, kw.get("caption", "")))
    expected = None
    for case_inp, case_out in builder._case_contexts("plastic"):
        if case_inp["plastic_case"]["id"] != target_case:
            continue
        builder.inp, builder.out = case_inp, case_out
        c = case_out["combined"]
        assert report.presentation.combined_publication_evidence_is_current(case_inp, case_out)[0]
        expected = c["longitudinal_candidates"]
        builder._combined()
    charts = [(figure, caption) for figure, caption in captures
              if figure.layout.title.text == "Longitudinal chords at the selected member angle"]
    assert len(charts) == 1
    chart, caption = charts[0]
    assert target_case in caption
    assert selected["shear"]["case_id"] not in caption
    assert "shear component Vy" in caption
    assert list(chart.data[0].x) == [row["m_total"] for row in expected]
    assert list(chart.data[1].x) == [row["m_rd"] for row in expected]
    assert pickle.dumps((inp, out)) == frozen

    # A complete result must not remain publishable after one retained chord
    # operand changes. Use a separate evidence copy, preserving the good case.
    builder.inp, builder.out = copy.deepcopy((builder.inp, builder.out))
    tampered = builder.out["combined"]
    tampered["longitudinal_candidates"][0]["m_total"] += .1
    assert not report.presentation.combined_publication_evidence_is_current(builder.inp, builder.out)[0]
    longitudinal = next(item for item in report.presentation.combined_physical_components(tampered)
                        if item["key"] == "longitudinal")
    before_count = len(captures)
    builder._combined_chord_diagram(tampered, longitudinal)
    assert len(captures) == before_count
    assert pickle.dumps((inp, out)) == frozen
