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
    # Mx is bending *about* the x-axis, so it is the vertical plot axis and My
    # the horizontal one -- a tall (strong-about-x) section gives a tall envelope.
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
    # small standoff), so the two do not overlap. Regression for the legend text
    # colliding with the axis label.
    inter = viz.interaction_figure([100.0, 0.0, -100.0], [0.0, 100.0, 0.0])
    sect = viz.section_figure([(0.0, 0.0), (0.4, 0.0), (0.4, 0.6), (0.0, 0.6)],
                              bars=[(0.2, 0.05)], scale=1000.0, unit="mm")
    for fig in (inter, sect):
        assert fig.layout.legend.y <= -0.2            # pushed below the axis title
        assert fig.layout.margin.b >= 90              # room for title + legend
        assert fig.layout.xaxis.title.standoff == 10  # title kept near the axis
