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


def test_steel_figure_shows_input_modulus_slope_label():
    fig = viz.steel_curve_figure(
        MildSteel(fytk=500.0, fyck=500.0, gamma_y=1.15, curve=2, Es=205000.0))
    texts = " ".join(a.text for a in fig.layout.annotations)
    assert "E<sub>s</sub>" in texts and "205 GPa" in texts


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
