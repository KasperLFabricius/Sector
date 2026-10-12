"""Independent geometry and retained-state checks for report diagrams."""
from __future__ import annotations

import dataclasses
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import report_diagrams as diagrams
from sector.geometry import area_moments, clip_halfplane
from sector.section import Section
from sector.serviceability import analyse_cracking


def _retained(inp, *, edition="2005", coarse=False, actions=(0.0, 150.0, 0.0)):
    elements = inp["bars"] + inp.get("tendons", [])
    section = Section.from_polygon(inp["outer"], elements, holes=inp.get("holes", []))
    options = {}
    if inp.get("tendons"):
        import numpy as np
        types = ["mild"] * len(inp["bars"]) + ["prestress"] * len(inp["tendons"])
        options = dict(
            Es=[200_000. if kind == "mild" else 195_000. for kind in types],
            n_mult=np.array([1. if kind == "mild" else .975 for kind in types]),
            prestress_stress=np.array([0. if kind == "mild" else 100_000. for kind in types]),
            reinforcement_types=types,
            k1=[.8 if kind == "mild" else 1.6 for kind in types], bond_ratio_xi=.5)
    result = analyse_cracking(section, *actions, 6.0, fctm=3.0,
                              bar_diameter=20.0, edition=edition, coarse=coarse, **options)
    crack = result.crack
    assert crack is not None
    area = dataclasses.asdict(crack.effective_area_operands)
    area["record_kind"] = type(crack.effective_area_operands).__name__
    if crack.effective_reinforcement:
        eligible = [dataclasses.asdict(item) for item in crack.effective_reinforcement]
    else:
        eligible = [dataclasses.asdict(item) for item in crack.effective_reinforcement_2023.elements]
    for item in eligible:
        item["element_id"] = f"R{item['element_index'] + 1}"
    sigma, gx, gy = result.cracked_state.raw_stress_plane
    return {
        "ac_eff": crack.ac_eff, "effective_area_operands": area,
        "effective_reinforcement": eligible,
    }, {"converged": result.cracked_state.converged,
        "raw_stress_plane": {"sigma0_kpa": sigma, "gradient_x_kpa_per_m": gx,
                             "gradient_y_kpa_per_m": gy}}


def _beam():
    return {"outer": [(-.15, -.3), (.15, -.3), (.15, .3), (-.15, .3)],
            "holes": [], "bars": [(-.1, -.25, 400.), (.1, -.25, 400.),
                                    (-.1, .25, 400.), (.1, .25, 400.)],
            "tendons": []}


@pytest.mark.parametrize("edition,coarse", [("2005", False), ("2005", True), ("2023", False)])
@pytest.mark.parametrize("sign", [1., -1.])
def test_native_bending_diagram_retains_signed_face_and_area(edition, coarse, sign):
    inp = _beam()
    crack, state = _retained(inp, edition=edition, coarse=coarse, actions=(0., sign * 150., 0.))
    fig = diagrams.crack_effective_area_figure(inp, crack, state, title="Native bending")
    zones = [t for t in fig.data if t.name == "Effective concrete area"]
    assert len(zones) == 1
    ring = [(float(x) / 1000, float(y) / 1000) for x, y in zip(zones[0].x, zones[0].y)]
    assert abs(area_moments(ring).area) == pytest.approx(crack["ac_eff"], abs=1e-12)
    assert all(sign * y <= 1e-10 for _, y in ring)
    included = next(t for t in fig.data if t.name == "Included reinforcement")
    expected = [i for i, row in enumerate(crack["effective_reinforcement"]) if row["in_effective_area"]]
    assert list(included.customdata) == [f"R{i + 1}" for i in expected]


@pytest.mark.parametrize("angle,shift,reverse", [(0., 0, False), (30., 0, False), (90., 0, False), (0., 1, False), (0., 0, True)])
def test_native_direct_tension_uses_retained_local_rectangle_frame(angle, shift, reverse):
    inp = _beam()
    a = math.radians(angle)
    def rotate(point):
        x, y, *tail = point
        return (x * math.cos(a) - y * math.sin(a) + .7,
                x * math.sin(a) + y * math.cos(a) - .4, *tail)
    inp["outer"] = [rotate(p) for p in inp["outer"]]
    inp["outer"] = inp["outer"][shift:] + inp["outer"][:shift]
    if reverse:
        inp["outer"].reverse()
    inp["bars"] = [rotate(p) for p in inp["bars"]]
    # Pure direct tension about the input origin includes the translated force arm.
    crack, state = _retained(inp, edition="2023", actions=(-800., 320., -560.))
    assert crack["effective_area_operands"]["record_kind"] == "CrackEffectiveArea2023Direct"
    fig = diagrams.crack_effective_area_figure(inp, crack, state, title="Native direct tension")
    area = sum(abs(area_moments([(x / 1000, y / 1000) for x, y in zip(t.x, t.y)]).area)
               for t in fig.data if t.name == "Effective concrete area")
    assert area == pytest.approx(crack["ac_eff"], abs=1e-12)


@pytest.mark.parametrize("edition,coarse", [("2005", False), ("2005", True), ("2023", False)])
@pytest.mark.parametrize("reverse", [False, True])
def test_bending_hole_is_removed_from_visible_effective_area(edition, coarse, reverse):
    inp = _beam()
    inp["holes"] = [[(-.025, -.24), (.025, -.24), (.025, -.12), (-.025, -.12)]]
    if reverse:
        inp["outer"].reverse()
        inp["holes"][0].reverse()
    crack, state = _retained(inp, edition=edition, coarse=coarse)
    fig = diagrams.crack_effective_area_figure(inp, crack, state, title="Void")
    zone_index = next(i for i, t in enumerate(fig.data) if t.name == "Effective concrete area")
    masks = [t for t in fig.data[zone_index + 1:] if t.fill == "toself" and t.fillcolor == "white"]
    assert len(masks) == 1
    assert set(zip(masks[0].x, masks[0].y)) == {(x * 1000, y * 1000) for x, y in inp["holes"][0]}


def test_direct_tension_rejects_an_unaccepted_elastic_state():
    inp = _beam()
    crack, state = _retained(inp, edition="2023", actions=(-800., 0., 0.))
    state["converged"] = False
    with pytest.raises(diagrams.DiagramUnavailable):
        diagrams.crack_effective_area_figure(inp, crack, state, title="Unaccepted")


def test_concave_effective_band_does_not_draw_a_bridge_across_open_recess():
    inp = {"outer": [(0., 0.), (4., 0.), (4., 4.), (3., 4.), (3., 1.), (1., 1.), (1., 4.), (0., 4.)],
           "holes": [], "bars": [(.5, 3., 100.), (3.5, 3., 100.)], "tendons": []}
    crack = {"ac_eff": 4., "effective_area_operands": {"record_kind": "CrackEffectiveArea2005Fine", "band_limit": 2., "selected_hc_eff": 2., "ac_eff": 4.},
             "effective_reinforcement": [{"element_index": i, "element_id": f"R{i + 1}", "in_effective_area": True} for i in range(2)]}
    state = {"converged": True, "raw_stress_plane": {"sigma0_kpa": 0., "gradient_x_kpa_per_m": 0., "gradient_y_kpa_per_m": 1.}}
    fig = diagrams.crack_effective_area_figure(inp, crack, state, title="Open recess")
    for trace in fig.data:
        if trace.name != "Effective concrete area" or not trace.line.width:
            continue
        points = list(zip(trace.x, trace.y))
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            x, y = (x0 + x1) / 2, (y0 + y1) / 2
            assert not (1000 < x < 3000 and y > 1000), (x, y)


@pytest.mark.parametrize("field,value", [("ac_eff", -1.), ("ac_eff", float("nan"))])
def test_invalid_retained_area_is_rejected(field, value):
    inp = _beam(); crack, state = _retained(inp)
    crack[field] = value
    with pytest.raises(diagrams.DiagramUnavailable):
        diagrams.crack_effective_area_figure(inp, crack, state, title="Invalid")


def test_inconsistent_element_membership_is_rejected():
    inp = _beam(); crack, state = _retained(inp)
    crack["effective_reinforcement"][0]["in_effective_area"] = False
    with pytest.raises(diagrams.DiagramUnavailable):
        diagrams.crack_effective_area_figure(inp, crack, state, title="Inconsistent")


@pytest.mark.parametrize("offset", [0., 10.])
def test_coordinate_diagram_preserves_origin_and_equal_length_scale(offset):
    inp = _beam(); inp["outer"] = [(x + offset, y + offset) for x, y in inp["outer"]]
    inp["bars"] = [(x + offset, y + offset, a) for x, y, a in inp["bars"]]
    inp["bar_elements"] = [{"id": f"R{i + 1}"} for i in range(4)]
    fig = diagrams.section_axes_figure(inp)
    assert fig.layout.yaxis.scaleanchor == "x"
    assert fig.layout.yaxis.scaleratio == 1
    assert list(fig.data[0].x)[:-1] == [x * 1000 for x, _ in inp["outer"]]
    if offset:
        assert any("outside" in a.text for a in fig.layout.annotations)
    else:
        origin = next(t for t in fig.data if list(t.text or []) == ["O (0, 0)"])
        assert list(origin.x) == list(origin.y) == [0]


@pytest.mark.parametrize("shift", [0, 2])
def test_asymmetric_direct_bands_keep_their_physical_faces(shift):
    inp = _beam()
    inp["bars"] = [(x, y, 400.) for x in (-.12, .08) for y in (-.26, .24)]
    inp["outer"] = inp["outer"][shift:] + inp["outer"][:shift]
    crack, state = _retained(inp, edition="2023", actions=(-800., 8., 16.))
    fig = diagrams.crack_effective_area_figure(inp, crack, state, title="Asymmetric perimeter")
    area = crack["effective_area_operands"]
    assert area["record_kind"] == "CrackEffectiveArea2023Direct"
    p0, p1, p2 = inp["outer"][:3]
    width, height = area["width"], area["height"]
    ux = ((p1[0] - p0[0]) / width, (p1[1] - p0[1]) / width)
    uy = ((p2[0] - p1[0]) / height, (p2[1] - p1[1]) / height)
    inner_u = (area["left_band"] + width - area["right_band"]) / 2
    inner_v = (area["bottom_band"] + height - area["top_band"]) / 2
    inner_center = (p0[0] + ux[0] * inner_u + uy[0] * inner_v,
                    p0[1] + ux[1] * inner_u + uy[1] * inner_v)
    inner_area = area["inner_width"] * area["inner_height"]
    expected_centroid = tuple(-inner_area * value / crack["ac_eff"] for value in inner_center)
    assert inner_area > 0
    moments = [area_moments([(x / 1000, y / 1000) for x, y in zip(t.x, t.y)])
               for t in fig.data if t.name == "Effective concrete area"]
    actual_centroid = (sum(m.sx for m in moments) / sum(m.area for m in moments),
                       sum(m.sy for m in moments) / sum(m.area for m in moments))
    assert actual_centroid == pytest.approx(expected_centroid, abs=1e-12)


@pytest.mark.parametrize("which,key", [("Long-term fine", "long_term"),
                                       ("Short-term coarse", "instantaneous_combined")])
def test_report_diagram_uses_the_matching_accepted_duration(which, key, monkeypatch):
    import section_fields
    import sector_report

    builder = object.__new__(sector_report.ReportBuilder)
    builder.inp = _beam()
    states = {"long_term": object(), "instantaneous_combined": object()}
    builder.out = {"elastic": {"field_context": section_fields.context_signature(builder.inp, "Elastic"),
                               "accepted_states": states}}
    builder.figures = True
    builder.flow = []
    seen = []
    monkeypatch.setattr(diagrams, "crack_effective_area_figure",
                        lambda inp, cw, state, **kwargs: seen.append(state) or "figure")
    builder._fig = lambda *args, **kwargs: None
    builder._small = lambda *args: None
    builder._keep_from = lambda *args: None
    builder._crack_area_diagram({}, which)
    assert seen == [states[key]]
    builder.out["elastic"]["field_context"] = "stale"
    builder._crack_area_diagram({}, which)
    assert seen == [states[key]]
    builder.figures = False
    builder._crack_area_diagram({}, which)
    assert seen == [states[key]]


@pytest.mark.parametrize("shape", ["u", "c"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("oblique", [False, True])
def test_concave_band_masks_its_open_recess_and_preserves_material(shape, reverse, oblique):
    outer = [(0., 0.), (4., 0.), (4., 4.), (3., 4.), (3., 1.), (1., 1.), (1., 4.), (0., 4.)]
    bars = [(.5, 3., 100.), (3.5, 3., 100.)]
    if shape == "c":
        outer = [(y, x) for x, y in outer]
        bars = [(y, x, a) for x, y, a in bars]
    if reverse:
        outer.reverse()
    gx, gy = ((.25 if oblique else 0.), 1.)
    if shape == "c":
        gx, gy = gy, gx
    magnitude = math.hypot(gx, gy)
    gx, gy = gx / magnitude, gy / magnitude
    area = abs(area_moments(clip_halfplane(outer, gx, gy, -2.)).area)
    inp = {"outer": outer, "holes": [], "bars": bars, "tendons": []}
    crack = {"ac_eff": area, "effective_area_operands": {
        "record_kind": "CrackEffectiveArea2005Fine", "band_limit": 2.,
        "selected_hc_eff": max(gx * x + gy * y for x, y in outer) - 2., "ac_eff": area},
        "effective_reinforcement": [{"element_index": i, "in_effective_area": gx * x + gy * y >= 2.}
                                    for i, (x, y, _) in enumerate(bars)]}
    state = {"converged": True, "raw_stress_plane": {
        "sigma0_kpa": 0., "gradient_x_kpa_per_m": gx, "gradient_y_kpa_per_m": gy}}
    fig = diagrams.crack_effective_area_figure(inp, crack, state, title="Concave material")
    zone = next(trace for trace in fig.data if trace.name == "Effective concrete area")
    assert zone.line.width == 0
    assert abs(area_moments([(x / 1000, y / 1000) for x, y in zip(zone.x, zone.y)]).area) == pytest.approx(area, abs=1e-12)
    # The exterior mask must retain the complete original ring. A convex hull
    # would fill the recess; a bounding box alone would hide the material.
    mask = next(shape for shape in fig.layout.shapes if shape.fillrule == "evenodd")
    assert mask.layer == "above" and mask.fillcolor == "white" and mask.line.width == 0
    assert (mask.xref, mask.yref) == ("x", "y")
    original_path = "M " + " L ".join(f"{x * 1000},{y * 1000}" for x, y in outer) + " Z"
    assert mask.path.endswith(original_path)


@pytest.mark.parametrize("edition,coarse", [("2005", False), ("2005", True), ("2023", False)])
@pytest.mark.parametrize("sign", [-1., 1.])
def test_native_biaxial_band_matches_clipped_net_area(edition, coarse, sign):
    inp = _beam()
    crack, state = _retained(inp, edition=edition, coarse=coarse, actions=(0., sign * 120., sign * 30.))
    fig = diagrams.crack_effective_area_figure(inp, crack, state, title="Biaxial bending")
    zone = next(trace for trace in fig.data if trace.name == "Effective concrete area")
    assert abs(area_moments([(x / 1000, y / 1000) for x, y in zip(zone.x, zone.y)]).area) == pytest.approx(crack["ac_eff"], abs=1e-12)
    assert fig.layout.yaxis.scaleanchor == "x" and fig.layout.yaxis.scaleratio == 1


def test_2023_native_nested_element_schedule_remains_available():
    inp = _beam()
    crack, state = _retained(inp, edition="2023", actions=(-800., 0., 0.))
    crack["effective_reinforcement_2023"] = {"elements": crack.pop("effective_reinforcement")}
    fig = diagrams.crack_effective_area_figure(inp, crack, state, title="2023 schedule")
    included = next(trace for trace in fig.data if trace.name == "Included reinforcement")
    assert list(included.customdata) == ["R1", "R2", "R3", "R4"]


def _chords():
    return [dict(axis=axis, tension_low=low, valid=True, conditional=True,
                 m_total=demand, m_rd=capacity)
            for axis, low, demand, capacity in [
                ("x", True, 123.456789, 145.678912),
                ("x", False, 0., 73.25),
                ("y", True, 14.75, 0.),
                ("y", False, 56.125, 43.875)]]


def test_chord_chart_preserves_all_four_physical_faces_and_exact_moment_values():
    rows = _chords()
    fig = diagrams.chord_comparison_figure(rows)
    demand, capacity = fig.data
    assert list(demand.x) == [row["m_total"] for row in rows]
    assert list(capacity.x) == [row["m_rd"] for row in rows]
    expected = ["x-axis: bottom (-y) face", "x-axis: top (+y) face",
                "y-axis: left (-x) face", "y-axis: right (+x) face"]
    assert list(demand.y) == list(capacity.y) == expected
    assert fig.layout.xaxis.range[0] == 0
    assert fig.layout.xaxis.range[1] > max(demand.x + capacity.x)
    assert "kN m" in fig.layout.xaxis.title.text
    assert demand.marker.symbol != capacity.marker.symbol


@pytest.mark.parametrize("key,value", [
    ("valid", False), ("conditional", False), ("axis", "z"), ("tension_low", 1),
    ("m_total", -1.), ("m_rd", -1.), ("m_rd", float("nan")),
    ("m_total", float("inf")), ("m_total", True), ("m_rd", None)])
def test_chord_chart_rejects_unaccepted_or_invalid_evidence(key, value):
    rows = _chords()
    rows[0][key] = value
    with pytest.raises(diagrams.DiagramUnavailable):
        diagrams.chord_comparison_figure(rows)


def test_chord_chart_rejects_duplicate_physical_faces():
    rows = _chords()
    rows.append(dict(rows[0]))
    with pytest.raises(diagrams.DiagramUnavailable):
        diagrams.chord_comparison_figure(rows)


def test_chord_chart_rejects_missing_candidates():
    with pytest.raises(diagrams.DiagramUnavailable):
        diagrams.chord_comparison_figure([])


@pytest.mark.parametrize("complete,valid,figures,expected", [
    (True, True, True, 1), (False, True, True, 0),
    (True, False, True, 0), (True, True, False, 0)])
def test_report_chord_chart_requires_complete_authoritative_coverage(
        complete, valid, figures, expected, monkeypatch):
    from types import SimpleNamespace
    import sector_report

    builder = object.__new__(sector_report.ReportBuilder)
    builder.inp = {"shear_links": True}
    builder.out = {}
    builder.figures = figures
    for name in ("_h2", "_small", "_p", "_table", "_formula", "_fig"):
        setattr(builder, name, lambda *a, **kw: None)
    builder._shear_link_terms_available = lambda lk: True
    lk = {key: 1. for key in (
        "fywd", "z", "theta_deg", "cot", "nu1", "alpha_cw", "cot_unconstrained",
        "cot_min", "cot_max", "vrd_s", "vrd_max", "fcd", "tan", "vrd")}
    lk.update(valid=True, angle_selection="within limits", governs="links")
    sh = {"v_ed": 1., "bw": 1., "links": {
        "res": lk, "legs": 2, "dia": 10., "s": 100., "asw_over_s": 1.,
        "longitudinal_shear_force": 1.}}
    presentation = sector_report.presentation
    monkeypatch.setattr(presentation, "nominal_shear_resistance",
                        lambda *a, **kw: {"valid": True, "route": "links"})
    monkeypatch.setattr(presentation, "provided_link_publication_assessment",
                        lambda *a, **kw: SimpleNamespace(valid=True, utilisation=.5, status="PASS"))
    candidates = _chords()
    publication = {"valid": valid, "assessment": {
        "status": "PASS" if complete else "NOT ASSESSED", "coverage_complete": complete},
        "governing": dict(candidates[0], ok=True), "candidates": candidates}
    monkeypatch.setattr(presentation, "provided_link_longitudinal_publication_assessment",
                        lambda *a, **kw: publication)
    monkeypatch.setattr(sector_report.viz, "truss_figure", lambda *a, **kw: object())
    calls = []
    monkeypatch.setattr(diagrams, "chord_comparison_figure",
                        lambda rows: calls.append(rows) or object())
    class AfterChart(Exception):
        pass
    def stop_at_next_chord_operation(value):
        raise AfterChart
    monkeypatch.setattr(sector_report, "_demand_resistance_verdict", stop_at_next_chord_operation)
    with pytest.raises(AfterChart):
        builder._shear_links(sh)
    assert len(calls) == expected
    if expected:
        assert calls[0] is candidates


@pytest.mark.parametrize("edition,coarse", [("2005", False), ("2005", True), ("2023", False)])
@pytest.mark.parametrize("reverse_schedule", [False, True])
def test_native_mixed_material_markers_keep_type_inclusion_and_id(edition, coarse, reverse_schedule):
    inp = _beam()
    inp["bars"] = [(-.1, -.25, 400.), (-.1, .25, 400.)]
    inp["tendons"] = [(.1, -.25, 400.), (.1, .25, 400.)]
    crack, state = _retained(inp, edition=edition, coarse=coarse)
    schedule = crack["effective_reinforcement"]
    for row in schedule:
        index = row["element_index"]
        row["element_id"] = (f"B{index + 1}" if index < 2 else f"T{index - 1}")
    if reverse_schedule:
        schedule.reverse()
    fig = diagrams.crack_effective_area_figure(inp, crack, state, title="Mixed reinforcement")
    observed = {}
    for trace in fig.data:
        if trace.name in {"Included reinforcement", "Other reinforcement"}:
            for identifier, symbol, x, y in zip(trace.customdata, trace.marker.symbol, trace.x, trace.y):
                observed[identifier] = (symbol, x, y)
    assert observed == {
        "B1": ("circle", -100., -250.), "B2": ("circle-open", -100., 250.),
        "T1": ("diamond", 100., -250.), "T2": ("diamond-open", 100., 250.)}


@pytest.mark.parametrize("chapter", [False, True])
def test_map_groups_keep_each_figure_with_extrema_and_local_signs(chapter, monkeypatch):
    from types import SimpleNamespace
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import KeepTogether, Paragraph, Spacer
    from reportlab.lib.units import mm
    import sector_report

    style = getSampleStyleSheet()["BodyText"]
    builder = object.__new__(sector_report.ReportBuilder)
    builder.figures = True
    builder.inp = {"elastic_case": {"id": "SLS1"}}
    builder.flow = []
    if chapter:
        heading = Paragraph("Elastic section maps - SLS1", style)
        heading._sector_outline_level = 0
        builder.flow.append(heading)
    def paragraph(text, **kwargs):
        builder.flow.append(Paragraph(text, style))
    builder._h2 = builder._p = builder._small = paragraph
    sizes = []
    def figure(value, width, height, **kwargs):
        sizes.append((width, height))
        builder.flow.append(Spacer(width * mm, height * mm))
    builder._fig = figure
    builder._table = lambda rows, widths, **kwargs: paragraph("Extrema " + rows[1][0])
    field = SimpleNamespace(state="TOTAL", caption="Accepted state", density=True)
    native_figure = SimpleNamespace(layout=SimpleNamespace(width=760, height=665))
    monkeypatch.setattr(sector_report.section_fields, "field_pair",
                        lambda *a, **kw: (field, [("stress", native_figure), ("strain", native_figure)]))
    monkeypatch.setattr(sector_report.section_fields, "extrema",
                        lambda value, quantity: [(quantity + " minimum", -1., 0., 0.)])
    builder._section_field_maps({}, family="Elastic")
    assert sizes == [(170, 148.75), (170, 148.75)]
    # Definitions precede the complete map groups; the chapter heading stays first.
    common, (first, second) = builder.flow[:-2], builder.flow[-2:]
    assert isinstance(first, KeepTogether) and isinstance(second, KeepTogether)
    text1 = [item.getPlainText() for item in first._content if isinstance(item, Paragraph)]
    text2 = [item.getPlainText() for item in second._content if isinstance(item, Paragraph)]
    assert text1[-2] == "Extrema stress minimum"
    assert "Tension is positive" in text1[-1] and "separate stress scales" in text1[-1]
    assert text2[0] == "Extrema strain minimum"
    assert "Tension is positive" in text2[-1] and "Strain values" in text2[-1]
    assert "Section stress and strain maps" in text1
    assert "TOTAL. Accepted state" in text1
    if chapter:
        assert common[0] is heading
        assert common.count(heading) == 1
    assert all(isinstance(item, Paragraph) for item in common)
    assert any("color limits stay fixed" in item.getPlainText() for item in common)
    assert any("Display bands" in item.getPlainText() for item in common)
    assert any("Slab-density" in item.getPlainText() for item in common)
