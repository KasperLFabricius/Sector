"""Tests for the stress-strain diagram figures (labels, symbols, merging).

Greek glyphs are referenced via chr() so this test file stays ASCII.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import viz  # noqa: E402
from sector.materials import Concrete, MildSteel, Prestress  # noqa: E402

_EPS = chr(0x3B5)       # epsilon
_SIGMA = chr(0x3C3)     # sigma
_PERMILLE = chr(0x2030)  # per-mille sign


def _has_marker_trace(fig):
    return any(getattr(t, "mode", None) == "markers" for t in fig.data)


def test_concrete_figure_greek_axes_dots_and_axis_labels():
    fig = viz.concrete_curve_figure(Concrete(fck=35.0, gamma_c=1.5, curve=2))
    xtitle = fig.layout.xaxis.title.text
    assert _EPS in xtitle and _PERMILLE in xtitle
    assert _SIGMA in fig.layout.yaxis.title.text
    assert _has_marker_trace(fig)  # dots on the curve
    texts = [a.text for a in fig.layout.annotations]
    # fck (the input) on the stress axis; eps_c2 and eps_cu2 on the strain axis.
    assert any("f<sub>ck</sub>" in t for t in texts)
    assert any(_EPS + "<sub>c2</sub>" in t for t in texts)
    assert any(_EPS + "<sub>cu2</sub>" in t for t in texts)


def test_section_figure_draws_in_mm_with_scale():
    # The section figure scales metre geometry for display: a 0.4 m corner is
    # drawn at 400 mm and the axes are labelled mm.
    fig = viz.section_figure([(0.0, 0.0), (0.4, 0.0), (0.4, 0.6), (0.0, 0.6)],
                             scale=1000.0, unit="mm")
    assert "mm" in fig.layout.xaxis.title.text
    assert "mm" in fig.layout.yaxis.title.text
    assert max(fig.data[0].x) == pytest.approx(400.0)
    assert max(fig.data[0].y) == pytest.approx(600.0)


def test_section_figure_accepts_numpy_array_rings():
    # Sections store rings as NumPy arrays; section_figure must not truth-test them
    # (an array's truth value is ambiguous) when scaling for display.
    import numpy as np
    outer = np.array([[0.0, 0.0], [0.4, 0.0], [0.4, 0.6], [0.0, 0.6]])
    holes = [np.array([[0.1, 0.1], [0.3, 0.1], [0.3, 0.5], [0.1, 0.5]])]
    bars = np.array([[0.2, 0.05, 2.0e-4]])
    fig = viz.section_figure(outer, holes=holes, bars=bars, scale=1000.0, unit="mm")
    assert max(fig.data[0].x) == pytest.approx(400.0)


def test_elastic_strain_profile_distinguishes_bars_and_tendons():
    corners = [
        {"point_no": 1, "ring": "Outer", "x_mm": -100.0, "y_mm": -200.0,
         "strain_permille": -0.5},
        {"point_no": 2, "ring": "Outer", "x_mm": 100.0, "y_mm": 200.0,
         "strain_permille": 1.0},
    ]
    elements = [
        {"element_type": "Bar", "element_id": "bar 1", "x_mm": 0.0,
         "y_mm": -150.0, "strain_permille": 0.8, "total_mpa": 160.0},
        {"element_type": "Tendon", "element_id": "tendon 1", "x_mm": 0.0,
         "y_mm": 150.0, "strain_permille": 4.0, "total_mpa": 780.0},
    ]
    fig = viz.elastic_strain_figure(
        corners, elements, (-10_000.0, 0.0, 50_000.0),
        ec_mpa=30_000.0,
    )
    names = [trace.name for trace in fig.data]
    assert "Concrete strain plane" in names
    assert "Bars" in names and "Tendons" in names
    assert fig.layout.yaxis.autorange == "reversed"
    assert "permille" in fig.layout.xaxis.title.text


def test_tension_only_curve_has_no_spurious_vertical_at_origin():
    # A tension-only law (zero in compression, elastic in tension) is continuous
    # at the origin: the 0 -> elastic-branch transition must NOT be drawn as a
    # rupture vertical (regression: a jump near 0,0 when compression is off).
    fn = lambda e: 0.0 if e < 0.0 else 200000.0 * e
    grid = [-0.025 + i * 0.05 / 239 for i in range(240)]
    xs, ys = viz._trace_xy(fn, grid, peak=550.0)
    spurious = [(x, y) for x, y in zip(xs, ys) if abs(x) < 0.05 and abs(y) > 1.0]
    assert not spurious
    # the diagram for a tension-only reinforcement still builds.
    s = MildSteel(fytk=550.0, fyck=550.0, futk=550.0, eut=1.0, curve=3,
                  active_in_compression=False)
    assert viz.steel_curve_figure(s) is not None


def test_merge_labels_joins_coincident_symbols():
    assert viz._merge_labels(["fytk", "futk"]) == "f<sub>ytk</sub>/f<sub>utk</sub>"
    assert viz._merge_labels(["fytk", "fytk"]) == "f<sub>ytk</sub>"  # de-duplicated


def test_steel_with_equal_yield_and_ultimate_merges_stress_label():
    # futk = fytk and gamma_u = gamma_y -> f_ud equals f_yd at one stress level.
    s = MildSteel(fytk=500.0, fyck=500.0, futk=500.0, eut=0.02, gamma_y=1.15,
                  gamma_u=1.15, gamma_E=1.0, curve=1)
    fig = viz.steel_curve_figure(s)
    assert any("/" in a.text for a in fig.layout.annotations)


def test_curve3_figure_labels_input_parameters_not_derived():
    s = MildSteel(fytk=550.0, fyck=400.0, futk=600.0, eut=0.05, gamma_y=1.0,
                  gamma_u=1.0, gamma_E=1.0, k=0.9, ey0t=0.002, ey0c=0.005, curve=3)
    fig = viz.steel_curve_figure(s)
    texts = " ".join(a.text for a in fig.layout.annotations)
    # Inputs are labelled: yield, ultimate, compression yield, k*fytk, strains.
    for sym in ("f<sub>ytk</sub>", "f<sub>utk</sub>", "f<sub>yck</sub>",
                "k" + viz._MID + "f<sub>ytk</sub>", _EPS + "<sub>ut</sub>",
                _EPS + "<sub>0t</sub>", _EPS + "<sub>0c</sub>"):
        assert sym in texts, sym
    # Derived/design quantities are not shown.
    for sym in ("f<sub>1</sub>", "f<sub>2</sub>", "f<sub>ud</sub>", "f<sub>yd</sub>"):
        assert sym not in texts, sym


def _named_trace(fig, name):
    return next(t for t in fig.data if getattr(t, "name", None) == name)


def test_yield_corner_is_an_exact_vertex_with_full_elastic_slope():
    # Perfectly plastic steel: characteristic yield strain = fytk/Es = 2.75 per-mille.
    # The grid must carry an exact vertex there so the elastic branch keeps its full
    # slope (Es) up to the corner, instead of a segment spanning the corner averaging
    # the elastic slope and the plateau (the spurious "second slope").
    s = MildSteel(fytk=550.0, fyck=550.0, futk=550.0, eut=1.0, curve=2,
                  Es=200000.0, gamma_y=1.0, gamma_E=1.0, gamma_u=1.0)
    char = _named_trace(viz.steel_curve_figure(s), "characteristic")
    xs, ys = list(char.x), list(char.y)
    i = min(range(len(xs)), key=lambda j: abs(xs[j] - 2.75))
    assert xs[i] == pytest.approx(2.75, abs=1e-6)     # exact vertex at the corner
    assert ys[i] == pytest.approx(550.0, abs=1e-6)
    slope_below = (ys[i] - ys[i - 1]) / (xs[i] - xs[i - 1])
    slope_above = (ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i])
    assert slope_below == pytest.approx(200.0, abs=1e-3)  # Es: 200 MPa per per-mille
    assert slope_above == pytest.approx(0.0, abs=1e-6)    # flat plateau above yield


def test_steel_figure_shows_input_modulus_slope_label():
    fig = viz.steel_curve_figure(
        MildSteel(fytk=500.0, fyck=500.0, gamma_y=1.15, curve=2, Es=205000.0))
    texts = " ".join(a.text for a in fig.layout.annotations)
    assert "E<sub>s</sub>" in texts and "205 GPa" in texts


def test_na_line_at_spans_the_extent():
    # Horizontal line y = 0 (a=0, b=1, c=0): endpoints span +/- extent in x.
    x0, y0, x1, y1 = viz.na_line_at(0.0, 1.0, 0.0, 0.5)
    assert y0 == pytest.approx(0.0) and y1 == pytest.approx(0.0)
    assert {round(x0, 3), round(x1, 3)} == {-0.5, 0.5}


def test_section_figure_numbers_rebar_and_corners():
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    bars = [(-0.1, -0.25), (0.1, -0.25)]
    tendons = [(0.0, 0.27)]
    fig = viz.section_figure(outer, bars=bars, tendons=tendons, show_labels=True)
    texts = [t for t in fig.data if getattr(t, "mode", None) == "text"]
    # Reinforcement: bars then tendons, numbered continuously 1, 2, 3.
    rebar = next(t for t in texts if list(t.text) == ["1", "2", "3"])
    assert list(rebar.x)[:2] == [-0.1, 0.1]      # bars precede the tendon
    # Concrete corners: the four outer vertices numbered 1..4.
    assert any(list(t.text) == ["1", "2", "3", "4"] for t in texts)


def test_section_figure_uses_stable_element_ids_when_supplied():
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    fig = viz.section_figure(
        outer,
        bars=[(-0.1, -0.25, 314.0), (0.1, -0.25, 314.0)],
        tendons=[(0.0, 0.27, 150.0)],
        bar_ids=["R1", "R3"], tendon_ids=["P2"], show_labels=True,
    )

    labels = [trace for trace in fig.data if getattr(trace, "mode", None) == "text"]
    assert any(list(trace.text) == ["R1", "R3", "P2"] for trace in labels)
    bar = next(t for t in fig.data if getattr(t, "name", None) == "reinforcing bar")
    tendon = next(t for t in fig.data if getattr(t, "name", None) == "tendon")
    assert "Bar R3" in str(bar.customdata[1])
    assert "Tendon P2" in str(tendon.customdata[0])


def _corner_hover(fig):
    # The invisible corner hover trace: a markers trace whose fill is transparent.
    return next(t for t in fig.data
                if getattr(t, "mode", None) == "markers"
                and getattr(t.marker, "color", None) == "rgba(0,0,0,0)")


def test_section_hover_reports_corner_coordinates():
    # Concrete corners get invisible hover targets (transparent markers) that report
    # the corner number and its coordinates in the display unit, without drawing
    # anything over the outline; corners carry no area.
    outer = [(0.0, 0.0), (0.4, 0.0), (0.4, 0.6), (0.0, 0.6)]
    corner = _corner_hover(viz.section_figure(outer, scale=1000.0, unit="mm"))
    assert list(corner.x) == [0.0, 400.0, 400.0, 0.0]        # drawn in mm
    texts = [str(c) for c in corner.customdata]
    assert any("Corner 1" in t and "x = 0 mm" in t and "y = 0 mm" in t for t in texts)
    assert any("Corner 2" in t for t in texts)
    assert all("area" not in t for t in texts)


def test_section_hover_reports_bar_and_tendon_coords_area_and_number():
    # Bars and tendons report their coordinates, area (mm2) and continuous number
    # (bars first, tendons after) so hover matches the labels and the result tables.
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    bars = [(-0.1, -0.25, 314.0), (0.1, -0.25, 314.0)]       # x, y in m; area in mm2
    tendons = [(0.0, 0.27, 150.0)]
    fig = viz.section_figure(outer, bars=bars, tendons=tendons, scale=1000.0, unit="mm")
    bar = next(t for t in fig.data if getattr(t, "name", None) == "reinforcing bar")
    tendon = next(t for t in fig.data if getattr(t, "name", None) == "tendon")
    b0 = str(bar.customdata[0])
    assert "Bar 1" in b0 and "x = -100 mm" in b0 and "y = -250 mm" in b0
    assert "area = 314 mm" in b0
    # Tendon numbering continues after the two bars.
    t0 = str(tendon.customdata[0])
    assert "Tendon 3" in t0 and "area = 150 mm" in t0


def test_section_hover_bars_without_area_omit_it():
    # A bar given as a plain (x, y) point (no area column) still hovers, just without
    # the area line -- the callers in the manual pass 2-tuples.
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    fig = viz.section_figure(outer, bars=[(0.0, 0.0)])
    bar = next(t for t in fig.data if getattr(t, "name", None) == "reinforcing bar")
    assert "area" not in str(bar.customdata[0])


def test_section_figure_appends_per_bar_and_tendon_hover():
    # The plastic view passes per-bar/tendon stress-strain read-outs; section_figure
    # appends each to that point's hover (on its own line after the coordinates/area).
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    fig = viz.section_figure(
        outer, bars=[(-0.1, -0.25, 314.0), (0.1, -0.25, 314.0)],
        tendons=[(0.0, 0.26, 150.0)], scale=1000.0, unit="mm",
        bar_hover=["sig = 300 MPa, eps = 0.10 %", "sig = 310 MPa, eps = 0.20 %"],
        tendon_hover=["sig = 1200 MPa, eps = 5.90 %"])
    bar = next(t for t in fig.data if getattr(t, "name", None) == "reinforcing bar")
    tendon = next(t for t in fig.data if getattr(t, "name", None) == "tendon")
    assert "sig = 300 MPa" in str(bar.customdata[0])
    assert "eps = 0.20 %" in str(bar.customdata[1])
    assert "area = 314 mm" in str(bar.customdata[0])       # coords/area still present
    assert "sig = 1200 MPa" in str(tendon.customdata[0])


def _corner_count(fig):
    texts = [t for t in fig.data if getattr(t, "mode", None) == "text"]
    return len(max(texts, key=lambda t: len(t.text)).text) if texts else 0


def test_label_min_gap_thins_crowded_corners():
    from sector import templates
    outer = [tuple(v) for v in templates.circular(0.6)]   # 48-vertex polygon
    # gap 0 keeps every corner; a larger gap thins the crowded ones.
    assert _corner_count(viz.section_figure(outer, show_labels=True,
                                            label_min_gap=0.0)) == 48
    thinned = _corner_count(viz.section_figure(outer, show_labels=True,
                                               label_min_gap=0.15))
    assert 0 < thinned < 48


def test_label_min_gap_is_independent_of_size():
    # The hide threshold (which labels show) does not depend on the font size.
    from sector import templates
    outer = [tuple(v) for v in templates.circular(0.6)]
    small = viz.section_figure(outer, show_labels=True, label_min_gap=0.15,
                               label_scale=1.0)
    big = viz.section_figure(outer, show_labels=True, label_min_gap=0.15,
                             label_scale=2.5)
    assert _corner_count(small) == _corner_count(big)


def test_sparse_corners_all_labelled():
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    fig = viz.section_figure(outer, show_labels=True)   # default gap keeps all 4
    assert any(list(t.text) == ["1", "2", "3", "4"]
               for t in fig.data if getattr(t, "mode", None) == "text")


def test_label_scale_sets_font_size():
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    fig = viz.section_figure(outer, bars=[(0.0, 0.0)], show_labels=True, label_scale=2.0)
    sizes = [t.textfont.size for t in fig.data if getattr(t, "mode", None) == "text"]
    assert sizes and all(sz == pytest.approx(22.0) for sz in sizes)   # 11 * 2.0


def test_section_state_uses_element_shapes_and_non_colour_sign_patterns():
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    fig = viz.section_figure(outer, bars=[(0.0, -0.2)], bar_colors=[viz.BAR_TENSION],
                             tendons=[(0.0, 0.2)], tendon_colors=[viz.BAR_COMPRESSION])
    tendon = next(t for t in fig.data if getattr(t, "name", None) == "tendon")
    assert list(tendon.marker.symbol) == ["diamond-x"]
    assert list(tendon.marker.color) == [viz.BAR_COMPRESSION]
    bar = next(t for t in fig.data if getattr(t, "name", None) == "reinforcing bar")
    assert list(bar.marker.symbol) == ["circle"]
    names = [getattr(trace, "name", "") or "" for trace in fig.data]
    assert "tension (+): plain marker" in names
    assert "compression (-): x marker" in names
    assert viz.BAR_TENSION == "#0072B2"
    assert viz.BAR_COMPRESSION == "#D55E00"


def test_section_figure_no_labels_by_default():
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    fig = viz.section_figure(outer, bars=[(0.0, 0.0)])
    assert not any(getattr(t, "mode", None) == "text" for t in fig.data)


def test_section_figure_shades_zones():
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    comp = [(-0.2, 0.0), (0.2, 0.0), (0.2, 0.3), (-0.2, 0.3)]
    fig = viz.section_figure(outer, zones=[(comp, viz.COMP_ZONE_FILL, "compression zone")])
    fills = [t for t in fig.data if getattr(t, "fill", None) == "toself"]
    assert any(t.name == "compression zone" for t in fills)


def test_halfplane_bar_colors_mild_follows_the_neutral_axis_side():
    # NA at y = 0 with the compression side y > 0 (a*x + b*y + c = y). Mild bars
    # have no prestrain, so their colour is just which side of the NA they sit on;
    # a bar on the axis reads as tension (matching the elastic view's >= 0 rule).
    hp = (0.0, 1.0, 0.0)
    colors = viz.halfplane_bar_colors([(0.0, 0.1), (0.0, -0.1), (0.0, 0.0)], hp, kappa=1.0)
    assert colors == [viz.BAR_COMPRESSION, viz.BAR_TENSION, viz.BAR_TENSION]


def test_halfplane_bar_colors_tendon_prestrain_keeps_tension_on_compression_side():
    # A tendon just inside the compression side (d = 0.004) whose locked-in prestrain
    # (IS = 0.006) exceeds the section compression strain is still in net tension; a
    # mild bar at the same point, with no prestrain, reads as compression.
    hp = (0.0, 1.0, 0.0)
    pt = [(0.0, 0.004)]
    assert viz.halfplane_bar_colors(pt, hp, kappa=1.0, prestrain=0.006) == [viz.BAR_TENSION]
    assert viz.halfplane_bar_colors(pt, hp, kappa=1.0) == [viz.BAR_COMPRESSION]


def test_halfplane_bar_colors_no_halfplane_returns_none():
    assert viz.halfplane_bar_colors([(0.0, 0.0)], None) is None


def test_hard_cutoff_renders_as_a_true_vertical():
    # Concrete crushes at eps_cu2 = 3.5 permille: the drop to zero must be drawn
    # vertical (two trace points at the same strain), not sloped across samples.
    fig = viz.concrete_curve_figure(Concrete(fck=35.0, gamma_c=1.5, curve=2))
    char = fig.data[1]  # the characteristic (solid) curve
    verticals = [
        (char.x[i], char.y[i], char.y[i + 1])
        for i in range(len(char.x) - 1)
        if abs(char.x[i] - char.x[i + 1]) < 1e-9            # same strain
        and abs(char.y[i] - char.y[i + 1]) > 1.0            # non-trivial jump
    ]
    assert verticals, "expected a vertical drop at the crushing strain"
    x_cut, y_a, y_b = verticals[0]
    assert x_cut == pytest.approx(-3.5, abs=0.05)           # at -eps_cu2 (per-mille)
    assert min(abs(y_a), abs(y_b)) < 1e-6                   # one end is zero stress


def test_concrete_figure_has_no_modulus_label():
    fig = viz.concrete_curve_figure(Concrete(fck=35.0, gamma_c=1.5, curve=2))
    assert not any("E<sub>s</sub>" in a.text or "E<sub>p</sub>" in a.text
                   for a in fig.layout.annotations)


def test_interaction_figure_snaps_apex_noise_to_zero():
    # A pure-Mx apex leaves a tiny floating-point residual in My; it must snap to 0
    # so the hover does not read e.g. "(388.5, 0.0007)". A genuine value is kept.
    mx = [388.5, 0.0, -388.5, 0.0]
    my = [0.0007, 30.0, -0.0007, -30.0]
    fig = viz.interaction_figure(mx, my, applied=(200.0, 0.0009))
    cap = fig.data[0]
    assert cap.x[0] == 0.0 and cap.x[2] == 0.0   # apex residuals snapped
    assert cap.x[1] == 30.0                       # genuine My preserved
    assert fig.data[1].x[0] == 0.0                # applied My noise snapped too
    assert "kNm" in cap.hovertemplate


def test_interaction_figure_plots_mx_vertical_my_horizontal():
    # Mx is bending *about* the x-axis, so it is the vertical plot axis and My the
    # horizontal one.
    mx = [100.0, 0.0, -100.0, 0.0]
    my = [0.0, 30.0, 0.0, -30.0]
    fig = viz.interaction_figure(mx, my, applied=(80.0, 20.0))
    cap = fig.data[0]
    assert list(cap.x) == my + my[:1]      # My on the horizontal axis
    assert list(cap.y) == mx + mx[:1]      # Mx on the vertical axis
    applied = fig.data[1]
    assert list(applied.x) == [20.0]       # applied My
    assert list(applied.y) == [80.0]       # applied Mx
    assert "about the x-axis" in fig.layout.yaxis.title.text
    assert "about the y-axis" in fig.layout.xaxis.title.text


def test_interaction_figure_uses_equal_aspect_axes():
    # The M-M envelope is drawn on a common scale (equal aspect), so it keeps its
    # true shape instead of being stretched to fill the plot (user preference,
    # v0.54 -- reverts the independent-autoscale of #108).
    fig = viz.interaction_figure([560.0, 0.0, -560.0, 0.0], [0.0, 90.0, 0.0, -90.0])
    assert fig.layout.yaxis.scaleanchor == "x"       # Mx tied to the My scale
    assert fig.layout.yaxis.scaleratio == 1


def test_prestress_figure_tension_only_labels_inputs():
    p = Prestress(curve=7, IS=0.006, fytk=1600.0, futk=1860.0, eut=0.035,
                  k=0.9, ey0t=0.002, gamma_y=1.15, gamma_u=1.15, gamma_E=1.0)
    fig = viz.prestress_curve_figure(p)
    xs = [x for tr in fig.data for x in (tr.x or [])]
    assert min(xs) >= -1.5  # per-mille; tension only
    assert _has_marker_trace(fig)
    texts = " ".join(a.text for a in fig.layout.annotations)
    for sym in ("f<sub>p0.1k</sub>", "f<sub>pk</sub>", "E<sub>p</sub>",
                "I<sub>S</sub>", _EPS + "<sub>ut</sub>"):
        assert sym in texts, sym


def test_legends_sit_below_the_axis_titles():
    # The horizontal legend must sit clear below the x-axis title (which has a
    # small standoff) and stay inside the bottom margin -- at every plot height, so
    # the taller Section (640) and Quick Section (560) views do not clip it. y is a
    # fraction of the plot area, so the pixel offset (not y) must be the constant.
    corners = [(0.0, 0.0), (0.4, 0.0), (0.4, 0.6), (0.0, 0.6)]
    cases = [(viz.interaction_figure([100.0, 0.0, -100.0], [0.0, 100.0, 0.0]), 440)]
    for h in (440, 560, 640):
        cases.append((viz.section_figure(corners, bars=[(0.2, 0.05)], scale=1000.0,
                                         unit="mm", height=h), h))
    for fig, h in cases:
        m = fig.layout.margin
        offset_px = -fig.layout.legend.y * (h - m.t - m.b)   # px below the plot
        assert 55 <= offset_px <= m.b                 # below the title, within margin
        assert fig.layout.xaxis.title.standoff == 10  # title kept near the axis


# -- v0.52 (F4): torsion tube overlay + shear-links truss schematic ----------

def test_tube_figure_draws_outline_centre_line_and_inner_face():
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    fig = viz.tube_figure(outer, holes=None, tef_mm=90.0, ak_m2=0.09)
    names = [getattr(t, "name", "") or "" for t in fig.data]
    assert any("outline" in n for n in names)
    assert any("centre-line" in n for n in names)      # tef/2 inward offset
    assert any("inner wall face" in n for n in names)  # tef inward offset
    # Drawn in mm (scale 1000): the outline spans -200..200 in x.
    outline = next(t for t in fig.data if (t.name or "") == "outline")
    assert max(outline.x) == pytest.approx(200.0)
    # The centre-line sits inside the outline (offset inward by tef/2 = 45 mm).
    centre = next(t for t in fig.data if "centre-line" in (t.name or ""))
    assert max(centre.x) < 200.0
    assert max(centre.x) == pytest.approx(155.0, abs=1.0)


def test_tube_figure_accepts_numpy_array_rings():
    # Codex: the section model stores rings as NumPy arrays; tube_figure must not
    # truth-test them (`outer or []` raises ValueError on an array).
    import numpy as np
    outer = np.array([[-0.2, -0.3], [0.2, -0.3], [0.2, 0.3], [-0.2, 0.3]])
    holes = [np.array([[-0.05, -0.1], [0.05, -0.1], [0.05, 0.1], [-0.05, 0.1]])]
    fig = viz.tube_figure(outer, holes=holes, tef_mm=60.0, ak_m2=0.05)
    outline = next(t for t in fig.data if (t.name or "") == "outline")
    assert max(outline.x) == pytest.approx(200.0)


def test_tube_figure_degrades_without_a_wall():
    # No tef -> just the outline, no offset rings (and no crash).
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    fig = viz.tube_figure(outer, tef_mm=0.0)
    names = [getattr(t, "name", "") or "" for t in fig.data]
    assert any("outline" in n for n in names)
    assert not any("centre-line" in n for n in names)


def test_marker_sizes_scale_with_relative_diameter():
    # O25 (491) next to O16 (201): the marker diameter ratio must follow the true
    # bar-diameter ratio sqrt(491/201) ~ 1.56, clamped to the [lo, hi] band.
    pts = [(0, 0, 491.0), (1, 0, 491.0), (0, 1, 201.0)]
    sizes = viz._marker_sizes(pts, 9.0, 6.5, 14.0)
    assert sizes[0] == sizes[1] > sizes[2]
    # The smaller bar's raw scaled size (9 * sqrt(201/491) ~ 5.8) hits the lo clamp.
    assert sizes[2] == pytest.approx(6.5)
    # Within the clamp band the ratio follows the true diameter ratio.
    in_band = viz._marker_sizes([(0, 0, 400.0), (0, 1, 300.0)], 9.0, 6.5, 14.0)
    assert in_band[0] / in_band[1] == pytest.approx((400.0 / 300.0) ** 0.5, rel=1e-6)
    # Equal areas -> everyone at base; missing areas (2-tuples) -> base scalar.
    assert viz._marker_sizes([(0, 0, 300.0)] * 3, 9.0, 6.5, 14.0) == [9.0] * 3
    assert viz._marker_sizes([(0, 0), (1, 1)], 9.0, 6.5, 14.0) == 9.0


def test_na_line_clipped_to_section_bbox():
    # A corner-origin section: unclipped, the +/- extent segment (anchored at the
    # line's closest point to the ORIGIN) overshoots far outside the section.
    import math as m
    a, b = m.cos(m.radians(35.0)), m.sin(m.radians(35.0))
    c = -0.35                                       # NA crosses the upper section
    x0, y0, x1, y1 = viz.na_line_at(a, b, c, 0.45, bbox=(0.0, 0.0, 0.3, 0.6))
    for x, y in ((x0, y0), (x1, y1)):               # endpoints inside bbox + 8% margin
        assert -0.06 <= x <= 0.36 and -0.06 <= y <= 0.66
    # Without a bbox the old +/- extent behaviour is preserved.
    ux0, uy0, ux1, uy1 = viz.na_line_at(a, b, c, 0.45)
    assert m.hypot(ux1 - ux0, uy1 - uy0) == pytest.approx(0.9)
    # A line that misses the box falls back to the extent span (no empty segment).
    fx0, fy0, fx1, fy1 = viz.na_line_at(a, b, -5.0, 0.45, bbox=(0.0, 0.0, 0.3, 0.6))
    assert m.hypot(fx1 - fx0, fy1 - fy0) == pytest.approx(0.9)


def test_interaction_figure_legend_always_shown():
    # A single-trace figure (capacity-only, or a partial arc) must still show the
    # legend -- it carries the "capacity (partial arc)" cue.
    fig = viz.interaction_figure([100.0, 0.0], [0.0, 90.0], closed=False)
    assert fig.layout.showlegend is True
    assert "partial arc" in fig.data[0].name


def test_vt_figure_subscripts_and_capacity_marker():
    fig = viz.vt_interaction_figure(1319.0, 148.0, 150.0, 40.0)
    assert "<sub>Ed</sub>" in fig.layout.xaxis.title.text
    assert "<sub>Ed</sub>" in fig.layout.yaxis.title.text
    names = [t.name or "" for t in fig.data]
    assert any("capacity (this direction)" in n for n in names)


def test_subtube_labels_follow_validated_global_centres():
    subs = [_sub(300, 600, 100.0, 0.10, 24.6, 90.0, 0.27, 0.0, -100.0),
            _sub(1000, 200, 91.0, 0.15, 15.4, 58.5, 0.26, 0.0, 300.0)]
    fig = viz.subtube_figure(subs)
    anns = fig.layout.annotations
    assert len(anns) == 2
    assert anns[0].y == pytest.approx(-100.0)
    assert anns[1].y == pytest.approx(300.0)


def test_concrete_curve_labels_design_plateau():
    from sector.materials import Concrete
    fig = viz.concrete_curve_figure(Concrete(fck=35.0, gamma_c=1.5, curve=2))
    texts = [a.text or "" for a in fig.layout.annotations]
    assert any("f<sub>cd</sub>" in t for t in texts)
    # gamma_c = 1: the curves coincide, so no separate (colliding) f_cd label.
    fig1 = viz.concrete_curve_figure(Concrete(fck=35.0, gamma_c=1.0, curve=2))
    texts1 = [a.text or "" for a in fig1.layout.annotations]
    assert not any("f<sub>cd</sub>" in t for t in texts1)


def test_interaction_figures_state_positive_bending_direction():
    # Both interaction diagrams carry a corner note (with arrow glyphs) stating what
    # PHYSICAL bending a positive value means: +Mx tensions the bottom face, +My the
    # left face (the solver's V = 90 / V = 0 convention), +N is axial tension.
    up, right = chr(0x2191), chr(0x2192)
    mm = viz.interaction_figure([100.0, 0.0, -80.0], [0.0, 90.0, 0.0])
    txt = " ".join(a.text or "" for a in mm.layout.annotations)
    assert up + " +Mx: tension at the bottom face" in txt
    assert right + " +My: tension at the left face" in txt
    nmx = viz.interaction_nm_figure([0.0, -500.0, 500.0], [200.0, 0.0, 0.0], axis="x")
    tx = " ".join(a.text or "" for a in nmx.layout.annotations)
    assert "+Mx: tension at the bottom face" in tx and "+N: axial tension" in tx
    nmy = viz.interaction_nm_figure([0.0, -500.0, 500.0], [200.0, 0.0, 0.0], axis="y")
    ty = " ".join(a.text or "" for a in nmy.layout.annotations)
    assert "+My: tension at the left face" in ty


def test_interaction_figure_partial_arc_is_not_filled():
    # A partial sweep is an OPEN arc: draw it as a bare line (no toself fill / no closing
    # vertex), else it shades a capacity region across an artificial closing chord.
    mx = [100.0, 80.0, 0.0]
    my = [0.0, 40.0, 90.0]
    op = viz.interaction_figure(mx, my, closed=False)
    assert op.data[0].fill in (None, "none")           # not filled
    assert len(op.data[0].x) == len(my)                # no repeated closing vertex
    cl = viz.interaction_figure(mx, my, closed=True)
    assert cl.data[0].fill == "toself"
    assert len(cl.data[0].x) == len(my) + 1            # closed (first vertex repeated)


def test_interaction_nm_landmark_uses_signed_max():
    # Asymmetric N-M: the negative-moment branch has the larger |M|, but the "max M"
    # landmark must sit on the positive branch to match the signed "Max M" metric.
    N = [0.0, -500.0, 500.0, 0.0]
    M = [200.0, 0.0, 0.0, -350.0]      # positive max = 200; larger |M| (350) is negative
    fig = viz.interaction_nm_figure(N, M, axis="x")
    ann = [a for a in fig.layout.annotations if "max" in (a.text or "").lower()]
    assert ann and ann[0].x == pytest.approx(200.0)    # positive max, not the -350 apex


def _sub(b, h, tef, ak, ted, trd, util, cx=0.0, cy=0.0):
    return dict(tube={"tef": tef, "Ak": ak}, b_mm=b, h_mm=h,
                x_mm=cx, y_mm=cy, stiffness=0.003,
                t_ed=ted, trd=trd, util=util, governs="stirrups")


def test_subtube_figure_draws_each_rectangle_with_walls():
    subs = [_sub(300, 600, 100.0, 0.10, 24.6, 90.0, 0.27, 0.0, -100.0),
            _sub(1000, 200, 91.0, 0.15, 15.4, 58.5, 0.26, 0.0, 300.0)]
    fig = viz.subtube_figure(subs)
    # Two rectangle outlines + two wall centre-lines = 4 traces; equal aspect.
    assert len(fig.data) == 4
    assert fig.layout.yaxis.scaleanchor == "x"
    # One annotation per sub-tube, drawn at the validated global centres.
    assert len(fig.layout.annotations) == 2
    assert fig.layout.annotations[0].y == pytest.approx(-100.0)
    assert fig.layout.annotations[1].y == pytest.approx(300.0)


def test_subtube_figure_empty_is_safe():
    fig = viz.subtube_figure([])
    assert fig is not None and len(fig.data) == 0


def test_truss_figure_strut_angle_and_link_spacing():
    import math
    fig = viz.truss_figure(21.8, 495.0, legs=2.0, dia_mm=10.0, s_mm=150.0)
    names = [getattr(t, "name", "") or "" for t in fig.data]
    assert any("compression chord" in n for n in names)
    assert any("tension chord" in n for n in names)
    assert any("strut" in n for n in names)
    assert any("links" in n for n in names)
    # The strut spans one panel (horizontal run z*cot theta, rise z), so its slope
    # equals tan(theta) -- equal aspect makes the drawn angle read true.
    strut = next(t for t in fig.data if "strut" in (t.name or ""))
    dx, dy = strut.x[1] - strut.x[0], strut.y[1] - strut.y[0]
    assert dy / dx == pytest.approx(math.tan(math.radians(21.8)), rel=1e-3)


def test_truss_figure_caps_the_number_of_ties():
    # A very small spacing must not spray hundreds of traces (drawing cap).
    fig = viz.truss_figure(21.8, 495.0, s_mm=5.0)
    ties = [t for t in fig.data if "links" in (getattr(t, "name", "") or "")]
    assert len(ties) <= 30


# -- v0.57 (A2): house palette + shared layout template ----------------------

def test_material_curve_names_match_their_colours():
    # The characteristic curve is CURVE_CHAR (purple) and the design curve is
    # CURVE_DESIGN (grey); the constants used to be swapped, so the names lied.
    from sector import material_presets as mp
    st = mp.build_mild(**mp.MILD_PRESETS[list(mp.MILD_PRESETS)[0]])
    fig = viz.steel_curve_figure(st)
    char = next(t for t in fig.data if getattr(t, "name", None) == "characteristic")
    design = next(t for t in fig.data if getattr(t, "name", None) == "design")
    assert char.line.color == viz.CURVE_CHAR
    assert design.line.color == viz.CURVE_DESIGN


def test_interaction_fills_use_the_house_envelope_fill():
    # The interaction fills route through ENVELOPE_FILL (purple-tinted to match the
    # envelope line), not the old off-palette default-plotly blue.
    nm = viz.interaction_nm_figure([100.0, 0.0, -50.0], [0.0, 80.0, 0.0])
    assert nm.data[0].fillcolor == viz.ENVELOPE_FILL
    vt = viz.vt_interaction_figure(600.0, 80.0, 100.0, 30.0)
    assert any(getattr(t, "fillcolor", None) == viz.ENVELOPE_FILL for t in vt.data)


def test_shared_sector_template_is_registered():
    import plotly.io as pio
    assert "sector" in pio.templates
    assert pio.templates["sector"].layout.font.family == viz._FONT_FAMILY


def test_truss_links_use_a_link_colour_not_the_neutral_axis():
    # The stirrup ties get their own LINK_LINE constant instead of reusing NA_LINE.
    fig = viz.truss_figure(21.8, 495.0, s_mm=150.0)
    ties = [t for t in fig.data if "links" in (getattr(t, "name", "") or "")]
    assert ties and all(t.line.color == viz.LINK_LINE for t in ties)


# -- v0.58 (A4): interaction-diagram information upgrade ----------------------

def test_mm_interaction_shows_fill_util_ray_and_angle_hover():
    mx = [300.0, 0.0, -300.0, 0.0]
    my = [0.0, 80.0, 0.0, -80.0]
    angles = [0.0, 90.0, 180.0, 270.0]
    fig = viz.interaction_figure(mx, my, applied=(150.0, 20.0), angles=angles, util=0.5)
    names = [getattr(t, "name", "") or "" for t in fig.data]
    assert "load direction" in names                       # the utilisation ray
    assert any("capacity (this direction)" in n for n in names)  # the crossing marker
    cap = next(t for t in fig.data if getattr(t, "name", None) == "capacity")
    assert cap.fill == "toself"                            # filled envelope
    assert cap.customdata is not None                      # per-vertex angle hover
    assert any("util = 0.50" in (a.text or "") for a in fig.layout.annotations)


def test_mm_interaction_without_util_has_no_ray():
    fig = viz.interaction_figure([100.0, 0.0, -100.0], [0.0, 30.0, 0.0],
                                 applied=(50.0, 10.0))
    names = [getattr(t, "name", "") or "" for t in fig.data]
    assert "load direction" not in names


def test_nm_interaction_marks_landmarks():
    N = [400.0, 0.0, -2500.0, 0.0]
    M = [0.0, 300.0, 0.0, -300.0]
    fig = viz.interaction_nm_figure(N, M, axis="x")
    assert any(getattr(t, "name", None) == "landmarks" for t in fig.data)
    anns = " ".join(a.text for a in fig.layout.annotations)
    assert "squash" in anns and "tension" in anns and "max Mx" in anns


def test_vt_interaction_shows_ray_and_interaction_sum():
    fig = viz.vt_interaction_figure(650.0, 88.0, 150.0, 40.0)
    names = [getattr(t, "name", "") or "" for t in fig.data]
    assert "load direction" in names
    anns = " ".join(a.text for a in fig.layout.annotations)
    assert "sum =" in anns and "OK" in anns


def test_truss_figure_labels_theta_and_z_dimension():
    # v0.61: the truss shows a theta arc at the strut base and a z dimension arrow.
    fig = viz.truss_figure(30.0, 495.0, s_mm=150.0)
    texts = [a.text for a in fig.layout.annotations]
    assert chr(0x3B8) in texts                                 # theta label at the arc
    assert any("z =" in (t or "") for t in texts)              # z dimension label


def test_shear_geometry_figure_exposes_derived_geometry_and_selected_bars():
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    bars = [(-0.1, -0.25, 300.0), (0.1, -0.25, 300.0),
            (-0.1, 0.25, 200.0), (0.1, 0.25, 200.0)]
    fig = viz.shear_geometry_figure(
        outer, [], bars, axis="x", tension_low=True,
        centroid=(0.0, 0.0), asl_bar_ids=[1, 2], asl_cg_m=-0.25,
        asl_mm2=600.0, d_mm=550.0, z_mm=495.0, bw_mm=400.0,
        bw_source="auto minimum solid width",
    )
    selected = next(t for t in fig.data if t.name == "included in Asl")
    assert list(selected.text) == ["1", "2"]
    text = " ".join((a.text or "") for a in fig.layout.annotations)
    assert "d = 550 mm" in text and "z = 495 mm" in text
    assert "400 mm" in text and "auto minimum solid width" in text
    assert "bars 1, 2" in text and "V<sub>y,Ed</sub>" in text


def test_horizontal_shear_geometry_uses_left_tension_face():
    fig = viz.shear_geometry_figure(
        [(0.0, 0.0), (0.6, 0.0), (0.6, 0.3), (0.0, 0.3)], [],
        [(0.05, 0.15, 500.0), (0.55, 0.15, 500.0)],
        axis="y", tension_low=True, centroid=(0.3, 0.15),
        asl_bar_ids=[1], asl_cg_m=0.05, asl_mm2=500.0,
        d_mm=550.0, z_mm=495.0, bw_mm=300.0, bw_source="user input",
    )
    text = " ".join((a.text or "") for a in fig.layout.annotations)
    assert "tension face" in text and "bending about y" in text
    assert "user input" in text


def test_uniaxial_shear_geometry_preserves_negative_action_direction():
    fig = viz.shear_geometry_figure(
        [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)], [],
        [(-0.1, -0.25, 300.0), (0.1, -0.25, 300.0)],
        axis="x", tension_low=True, centroid=(0.0, 0.0),
        asl_bar_ids=[1, 2], asl_cg_m=-0.25, asl_mm2=600.0,
        d_mm=550.0, z_mm=495.0, bw_mm=400.0, bw_source="auto",
        signed_v_ed=-25.0,
    )
    load_arrow = next(
        annotation for annotation in fig.layout.annotations
        if annotation.showarrow and annotation.arrowcolor == viz.LOAD_POINT
    )
    text = " ".join((annotation.text or "") for annotation in fig.layout.annotations)

    assert load_arrow.y < load_arrow.ay
    assert "V<sub>y,Ed</sub> = -25 kN" in text


def test_biaxial_shear_overview_has_signed_coordinate_arrows_without_resultant():
    fig = viz.biaxial_shear_overview_figure(
        [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)],
        [], [], vx_ed=-40.0, vy_ed=25.0,
    )
    text = " ".join((annotation.text or "") for annotation in fig.layout.annotations)
    arrows = [annotation for annotation in fig.layout.annotations if annotation.showarrow]

    assert "V<sub>x,Ed</sub> = -40" in text
    assert "V<sub>y,Ed</sub> = 25" in text
    assert len(arrows) == 2
    assert "resultant" not in text.casefold()
