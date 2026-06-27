"""Tests for the stress-strain diagram figures (labels, symbols, merging).

Greek glyphs are referenced via chr() so this test file stays ASCII.
"""

from __future__ import annotations

import pathlib
import sys

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
    # fcd on the stress axis; eps_c2 and eps_cu2 on the strain axis.
    assert any("f<sub>cd</sub>" in t for t in texts)
    assert any(_EPS + "<sub>c2</sub>" in t for t in texts)
    assert any(_EPS + "<sub>cu2</sub>" in t for t in texts)


def test_merge_labels_joins_coincident_symbols():
    assert viz._merge_labels(["fyd", "fud"]) == "f<sub>yd</sub>/f<sub>ud</sub>"
    assert viz._merge_labels(["fyd", "fyd"]) == "f<sub>yd</sub>"  # de-duplicated


def test_steel_with_equal_yield_and_ultimate_merges_stress_label():
    # futk = fytk and gamma_u = gamma_y -> f_ud equals f_yd at one stress level.
    s = MildSteel(fytk=500.0, fyck=500.0, futk=500.0, eut=0.02, gamma_y=1.15,
                  gamma_u=1.15, gamma_E=1.0, curve=1)
    fig = viz.steel_curve_figure(s)
    assert any("/" in a.text for a in fig.layout.annotations)


def test_curve3_figure_builds_and_labels_all_points():
    s = MildSteel(fytk=550.0, fyck=550.0, futk=600.0, eut=0.05, gamma_y=1.0,
                  gamma_u=1.0, gamma_E=1.0, k=0.9, ey0t=0.002, ey0c=0.005, curve=3)
    fig = viz.steel_curve_figure(s)
    texts = " ".join(a.text for a in fig.layout.annotations)
    for sym in ("f<sub>1</sub>", "f<sub>2</sub>", "f<sub>ud</sub>"):
        assert sym in texts


def test_steel_figure_shows_modulus_slope_label():
    fig = viz.steel_curve_figure(
        MildSteel(fytk=500.0, fyck=500.0, gamma_y=1.15, curve=2))
    assert any("E<sub>d</sub>" in a.text for a in fig.layout.annotations)


def test_concrete_figure_has_no_modulus_label():
    fig = viz.concrete_curve_figure(Concrete(fck=35.0, gamma_c=1.5, curve=2))
    assert not any("E<sub>d</sub>" in a.text for a in fig.layout.annotations)


def test_prestress_figure_tension_only_with_proof_and_ultimate_labels():
    p = Prestress(curve=6, IS=0.0, fytk=1600.0, futk=1860.0, eut=0.035,
                  gamma_y=1.15, gamma_u=1.15, gamma_E=1.0)
    fig = viz.prestress_curve_figure(p)
    # Tension-only: the plotted strain never goes far into compression.
    xs = [x for tr in fig.data for x in (tr.x or [])]
    assert min(xs) >= -1.5  # per-mille; just below zero, no compression branch
    assert _has_marker_trace(fig)
    texts = " ".join(a.text for a in fig.layout.annotations)
    assert "f<sub>pd</sub>" in texts and "f<sub>pud</sub>" in texts
    assert _EPS + "<sub>pd</sub>" in texts
