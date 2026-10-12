"""Independent checks of retained report action and neutral-axis annotations."""
from __future__ import annotations

import dataclasses
import math

import pytest
import report_diagrams as diagrams
from test_report_diagrams import _beam, _retained

from sector.elastic import solve_elastic_uncracked
from sector.section import Section
from sector.serviceability import analyse_cracking


def _plastic():
    return {"P_pl": -125., "Mx_pl": 150., "My_pl": -25., "shear_on": True,
                "shear_Vx": -30., "shear_Vy": 40., "shear_face_x": "negative",
                "shear_face_y": "auto", "torsion_on": True,
                "torsion_T": 20., "torsion_T_signed": -20.}


def test_signed_concurrent_actions_and_faces_are_preserved():
    text = diagrams.action_inset_text(_plastic(), "Plastic", "CASE<&>")
    for item in ("CASE&lt;&amp;&gt;", "N = -125 kN", "M<sub>x</sub> = 150 kN m",
                 "M<sub>y</sub> = -25 kN m", "V<sub>x</sub> = -30 kN",
                 "V<sub>y</sub> = 40 kN", "T = -20 kN m",
                 "automatic selection", "bottom-face tension", "left-face tension"):
        assert item in text
    assert "CASE<&>" not in text


@pytest.mark.parametrize("value", [None, True, "20", float("nan"), float("inf")])
def test_invalid_action_operands_fail_closed(value):
    inp = _plastic()
    inp["Mx_pl"] = value
    with pytest.raises(diagrams.DiagramUnavailable):
        diagrams.action_inset_text(inp, "Plastic", "CASE")


def test_torsion_rejects_hybrid_signed_magnitude():
    inp = _plastic()
    inp["torsion_T_signed"] = -30.
    with pytest.raises(diagrams.DiagramUnavailable, match="disagree"):
        diagrams.action_inset_text(inp, "Plastic", "CASE")
    inp.pop("torsion_T_signed")
    assert "T = 20 kN m" in diagrams.action_inset_text(inp, "Plastic", "CASE")


def test_capacity_only_slice_does_not_invent_moment_actions():
    text = diagrams.action_inset_text({"P_pl": -125.}, "Plastic", "CAP", capacity_only=True)
    assert "N = -125 kN" in text and "Capacity slice at this N" in text
    assert "M<sub>x</sub> =" not in text and "M<sub>y</sub> =" not in text
    with pytest.raises(diagrams.DiagramUnavailable):
        diagrams.action_inset_text({"P_pl": -125., "combined_on": True},
                                  "Plastic", "CAP", capacity_only=True)


def test_elastic_total_uses_signed_external_duration_sums():
    inp = dict(_plastic(), P_el_l=-100., P_el_s=25., Mx_el_l=-10.,
               Mx_el_s=15., My_el_l=30., My_el_s=-45.)
    text = diagrams.action_inset_text(inp, "Elastic", "EL")
    for item in ("TOTAL = long + short", "N = -75 kN", "M<sub>x</sub> = 5 kN m",
                 "M<sub>y</sub> = -15 kN m"):
        assert item in text
    assert "V<sub>" not in text and "T =" not in text


@pytest.mark.parametrize("actions,axis", [((100., 0., 0.), None),
                                        ((0., 10., 0.), 1), ((0., 0., 10.), 0)])
def test_action_sign_explanation_matches_native_ui_conversion(actions, axis):
    inp = _beam()
    section = Section.from_polygon(inp["outer"], inp["bars"])
    n, mx, my = actions
    result = solve_elastic_uncracked(section, -n, mx, my, 6.)
    sigma, gx, gy = result.raw_stress_plane
    values = [(point, sigma + gx * point[0] + gy * point[1]) for point in inp["outer"]]
    if axis is None:
        assert all(stress > 0 for _, stress in values)
    else:
        assert all(stress > 0 for point, stress in values if point[axis] < 0)
        assert all(stress < 0 for point, stress in values if point[axis] > 0)


def _plane(offset, gx, gy):
    return {"sigma0_kpa": offset, "gradient_x_kpa_per_m": gx, "gradient_y_kpa_per_m": gy}


@pytest.mark.parametrize("angle", [0, 13, 31, 45, 67, 89, 135, 179])
@pytest.mark.parametrize("reverse", [False, True])
def test_rotated_coincident_void_edge_keeps_complete_boundary(angle, reverse):
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    def rotate(point):
        x, y = point
        return c * x - s * y, s * x + c * y
    outer = list(map(rotate, [(-1., -1.), (1., -1.), (1., 1.), (-1., 1.)]))
    hole = list(map(rotate, [(-.5, -.5), (.5, -.5), (.5, .5), (-.5, .5)]))
    if reverse:
        outer.reverse()
        hole.reverse()
    segments, _ = diagrams._neutral_axis_segments(outer, [hole], _plane(-.5, c, s))
    assert sum(math.dist(*segment) for segment in segments) == pytest.approx(2., abs=2e-12, rel=0)
    for segment in segments:
        for x, y in segment:
            assert c * x + s * y - .5 == pytest.approx(0., abs=2e-12, rel=0)


def test_neutral_axis_removes_void_and_concave_recess_intervals():
    outer = [(-1., -1.), (1., -1.), (1., 1.), (-1., 1.)]
    hole = [(-.5, -.5), (.5, -.5), (.5, .5), (-.5, .5)]
    segments, _ = diagrams._neutral_axis_segments(outer, [hole], _plane(0., 0., 1.))
    assert len(segments) == 2
    assert sum(math.dist(*segment) for segment in segments) == pytest.approx(1., abs=1e-12, rel=0)
    assert all(abs((a[0] + b[0]) / 2) >= .5 for a, b in segments)
    outer = [(0., 0.), (4., 0.), (4., 4.), (3., 4.), (3., 1.), (1., 1.), (1., 4.), (0., 4.)]
    segments, _ = diagrams._neutral_axis_segments(outer, [], _plane(-2., 0., 1.))
    assert len(segments) == 2
    assert sum(math.dist(*segment) for segment in segments) == pytest.approx(2., abs=1e-12, rel=0)


@pytest.mark.parametrize("plane,note", [(_plane(1., 0., 0.), "No neutral axis"),
                                       (_plane(-1., 0., 0.), "No neutral axis"),
                                       (_plane(0., 0., 0.), "Zero reference-stress plane"),
                                       (_plane(-2., 1., 1.), "No neutral axis")])
def test_uniform_planes_and_tangent_do_not_invent_a_segment(plane, note):
    segments, actual = diagrams._neutral_axis_segments(
        [(-1., -1.), (1., -1.), (1., 1.), (-1., 1.)], [], plane)
    assert segments == [] and note in actual


@pytest.mark.parametrize("source,label", [("geometry", "geometry-derived"), ("override", "entered override")])
def test_cover_annotation_preserves_retained_source_and_rejects_disagreement(source, label):
    inp = _beam()
    crack, state = _retained(inp)
    crack.update(cover=40., governing_candidate={"cover": 40., "cover_source": source})
    fig = diagrams.crack_effective_area_figure(inp, crack, state, title="Cover")
    assert any(f"40 mm ({label})" in annotation.text for annotation in fig.layout.annotations)
    assert any(trace.name == "Neutral axis" for trace in fig.data)
    crack["cover"] = 35.
    with pytest.raises(diagrams.DiagramUnavailable):
        diagrams.crack_effective_area_figure(inp, crack, state, title="Mismatch")


@pytest.mark.parametrize("mode", ["off", "stale", "invalid", "current", "long"])
def test_input_figure_uses_current_selected_context_and_figures_off_is_inert(monkeypatch, mode):
    import sector_report
    builder = object.__new__(sector_report.ReportBuilder)
    builder.inp = {"bars": [], "tendons": []}
    builder.figures = mode != "off"
    captions = []
    for name in ("_h1", "_h2", "_geometry_tables", "_slab_density_input_tables",
                 "_concrete_section_properties_block", "_concrete_block", "_page_break",
                 "_loads_block", "_project_source_register", "_settings_block", "_fig"):
        setattr(builder, name, lambda *args, **kwargs: None)
    builder._fig = lambda *a, **kw: captions.append(kw["caption"])
    calls = []
    plastic = dict(_plastic(), _report_case_current=mode != "stale")
    if mode == "invalid":
        plastic["P_pl"] = float("nan")
    elastic = {"P_el_l": 100., "P_el_s": -25., "Mx_el_l": 5., "Mx_el_s": 10.,
                   "My_el_l": 0., "My_el_s": 0., "_report_case_current": True}
    def selected(key, family):
        calls.append(family)
        return (plastic if family == "plastic" else elastic), {"check_util": True}
    builder._selected_brief_result_context = selected
    identity = "Long<&>sigma 1e-9 m2 " * 24 if mode == "long" else "ID"
    monkeypatch.setattr(sector_report.presentation, "action_set", lambda inp, family: {"id": identity})
    figures = []
    monkeypatch.setattr(diagrams, "section_axes_figure", lambda inp, **kw: figures.append(kw["action_inset"]))
    builder._inputs()
    if mode == "off":
        assert calls == figures == []
    else:
        expected = "Plastic" if mode in {"current", "long"} else "Elastic"
        assert len(figures) == 1 and expected + " action set" in figures[0]
        assert calls == (["plastic"] if mode in {"current", "long"} else ["plastic", "elastic"])
        assert identity in captions[0]
        if mode == "long":
            assert "Case identity: see caption" in figures[0]
            assert "Long" not in figures[0]
            assert figures[0].count("<br>") <= 17
            import io

            from PIL import Image
            from reportlab.platypus import Paragraph, Table
            stream = io.BytesIO()
            Image.new("RGB", (4, 4), "white").save(stream, format="PNG")
            monkeypatch.setattr(sector_report, "_fig_png", lambda *a: (stream.getvalue(), False))
            real = sector_report.ReportBuilder(io.BytesIO(), {}, {}, {}, figures=True, profile="Standard")
            real._fig(object(), caption=captions[0])
            def paragraphs(value):
                if isinstance(value, Paragraph):
                    yield value.getPlainText()
                elif isinstance(value, Table):
                    yield from paragraphs(value._cellvalues)
                elif isinstance(value, (list, tuple)):
                    for child in value:
                        yield from paragraphs(child)
                elif hasattr(value, "_content"):
                    yield from paragraphs(value._content)
            assert any(identity in text for text in paragraphs(real.flow))


def _native_ratio_case(edition, mixed=False):
    import numpy as np
    inp = _beam()
    section = Section.from_polygon(inp["outer"], inp["bars"])
    options = {}
    if mixed:
        options = {"Es": [200_000., 195_000., 200_000., 195_000.],
                       "n_mult": np.array([1., .975, 1., .975]),
                       "prestress_stress": np.array([0., 100_000., 0., 100_000.]),
                       "reinforcement_types": ["mild", "prestress", "mild", "prestress"],
                       "k1": [.8, 1.6, .8, 1.6], "bond_ratio_xi": .5}
    result = analyse_cracking(section, 0., 150., 0., 6., fctm=3.,
                              bar_diameter=20., edition=edition, **options)
    crack = result.crack
    assert crack is not None
    cw = dataclasses.asdict(crack)
    cw["effective_area_operands"]["record_kind"] = type(crack.effective_area_operands).__name__
    cw["governing_candidate"] = next(dataclasses.asdict(item) for item in crack.candidates
                                      if item.bar_index == crack.gov_bar)
    return cw


def _capture_ratio(cw):
    import sector_report
    builder = object.__new__(sector_report.ReportBuilder)
    tables, notes = [], []
    builder._h2 = lambda *a, **k: None
    builder._table = lambda rows, *a, **k: tables.append(rows)
    builder._small = notes.append
    builder._crack_ratio_basis(cw)
    return tables, notes


@pytest.mark.parametrize("edition", ["2005", "2023"])
@pytest.mark.parametrize("mixed", [False, True])
def test_standard_ratio_basis_matches_native_edition_and_bond_weighting(edition, mixed):
    import sector_report
    cw = _native_ratio_case(edition, mixed)
    basis = cw["effective_reinforcement_2023"] if edition == "2023" else cw["governing_candidate"]
    tendon = basis["ap_eff_weighted" if edition == "2023" else "ap_eff"]
    assert (basis["as_eff"] + tendon) / basis["ac_eff"] == pytest.approx(cw["rho_p_eff"], rel=1e-12)
    tables, notes = _capture_ratio(cw)
    assert len(tables) == 1 and len(tables[0]) == 5
    expected = [sector_report._fmt(basis["as_eff"] * 1e6, 3) + " mm<super>2</super>",
                sector_report._fmt(tendon * 1e6, 3) + " mm<super>2</super>",
                sector_report._fmt(cw["ac_eff"] * 1e6, 3) + " mm<super>2</super>",
                f"{cw['rho_p_eff']:.8f}"]
    assert [row[1] for row in tables[0][1:]] == expected
    assert abs(float(tables[0][-1][1]) - cw["rho_p_eff"]) <= 0.5e-8
    assert any("bond weighting" in note for note in notes) == (edition == "2023")
    if edition == "2023" and mixed:
        assert basis["ap_eff_weighted"] != basis["ap_eff"]


@pytest.mark.parametrize("edition", ["2005", "2023"])
@pytest.mark.parametrize("fault", ["missing", "nonfinite", "negative", "zero-area", "ratio", "outer-area", "outer-ratio"])
def test_standard_ratio_basis_rejects_incomplete_or_contradictory_evidence(edition, fault):
    cw = _native_ratio_case(edition)
    basis = cw["effective_reinforcement_2023"] if edition == "2023" else cw["governing_candidate"]
    if fault == "missing":
        basis.pop("as_eff")
    elif fault == "nonfinite":
        basis["as_eff"] = float("nan")
    elif fault == "negative":
        basis["as_eff"] = -1.
    elif fault == "zero-area":
        basis["ac_eff"] = 0.
    elif fault == "ratio":
        basis["rho_p_eff"] *= 2.
    elif fault == "outer-area":
        cw["ac_eff"] *= 2.
    else:
        cw["rho_p_eff"] *= 2.
    tables, notes = _capture_ratio(cw)
    assert tables == []
    assert len(notes) == 1 and "unavailable" in notes[0]


@pytest.mark.parametrize("edition", ["2005", "2023"])
def test_standard_retains_ratio_basis_with_figures_disabled(edition):
    import sector_report
    from report_profiles import resolve_profile
    builder = object.__new__(sector_report.ReportBuilder)
    builder.profile = resolve_profile("Standard")
    builder.figures = False
    builder.out = {"elastic": {"crack_code": edition}}
    tables, notes = [], []
    builder._h2 = lambda *a, **k: None
    builder._table = lambda rows, *a, **k: tables.append(rows)
    builder._small = notes.append
    cw = _native_ratio_case(edition)
    assert builder._crack_worked_missing_operands(cw) == ()
    builder._crack_worked(cw)
    assert len(tables) == 1 and len(tables[0]) == 5
    assert not any("unavailable" in note for note in notes)
