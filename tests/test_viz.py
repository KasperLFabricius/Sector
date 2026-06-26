"""Tests for the stress-strain diagram figures (labels and symbols).

Greek glyphs are referenced via chr() so this test file stays ASCII.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import viz  # noqa: E402
from sector.materials import Concrete, MildSteel  # noqa: E402

_EPS = chr(0x3B5)       # epsilon
_SIGMA = chr(0x3C3)     # sigma
_PERMILLE = chr(0x2030)  # per-mille sign


def test_concrete_figure_uses_greek_axes_and_marks_points():
    fig = viz.concrete_curve_figure(Concrete(fck=35.0, gamma_c=1.5, curve=2))
    xtitle = fig.layout.xaxis.title.text
    assert _EPS in xtitle and _PERMILLE in xtitle
    assert _SIGMA in fig.layout.yaxis.title.text
    # A guide line + label for each point of interest (fcd, eps_c2, eps_cu2).
    assert len(fig.layout.annotations) >= 3
    texts = " ".join(a.text for a in fig.layout.annotations)
    assert _EPS in texts  # at least one strain symbol shown


def test_steel_figure_marks_yield():
    fig = viz.steel_curve_figure(
        MildSteel(fytk=500.0, fyck=500.0, gamma_y=1.15, curve=2))
    assert len(fig.layout.annotations) >= 2
    assert _SIGMA in fig.layout.yaxis.title.text


def test_curve3_figure_builds_without_error():
    s = MildSteel(fytk=550.0, fyck=550.0, futk=600.0, eut=0.05, gamma_y=1.0,
                  gamma_u=1.0, gamma_E=1.0, k=0.9, ey0t=0.002, ey0c=0.005, curve=3)
    fig = viz.steel_curve_figure(s)
    assert len(fig.layout.annotations) >= 3  # eps_y1, f1, f2
