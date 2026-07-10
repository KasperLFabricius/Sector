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


def test_tendons_drawn_as_diamonds_with_given_colors():
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    fig = viz.section_figure(outer, bars=[(0.0, -0.2)], bar_colors=[viz.BAR_TENSION],
                             tendons=[(0.0, 0.2)], tendon_colors=[viz.BAR_COMPRESSION])
    tendon = next(t for t in fig.data if getattr(t, "name", None) == "tendon")
    assert tendon.marker.symbol == "diamond"
    assert list(tendon.marker.color) == [viz.BAR_COMPRESSION]
    bar = next(t for t in fig.data if getattr(t, "name", None) == "reinforcing bar")
    assert bar.marker.symbol == "circle"


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
