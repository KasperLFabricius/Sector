"""Unit test for the plastic utilisation helper.

``_radial_util`` rates an applied (Mx, My) point against the M-M capacity
envelope: the applied radius over the distance from the origin to where the load
ray crosses the envelope polygon. The envelope is the closed polygon through the
swept capacity points in sweep order -- the straight chords the M-M diagram
draws -- so the utilisation is measured against the chord, not a radial
interpolation of the vertex radii (which bulges outside the chords and would
understate utilisation).
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))


def _radial_util():
    from sector.combined import radial_util
    return radial_util


def _diamond(r=100.0):
    # Four-point envelope with vertices on the axes; the edges are the straight
    # chords between them (the largest chord-vs-radius gap, so the behaviour is
    # unambiguous).
    return [r, 0.0, -r, 0.0], [0.0, r, 0.0, -r]


def test_util_at_a_vertex_is_the_vertex_radius():
    # A load ray that passes through a sweep point sees that vertex radius exactly
    # (chord and radius coincide there). ``_radial_util`` returns (util, gov).
    f = _radial_util()
    mx, my = _diamond(100.0)
    assert f(mx, my, 50.0, 0.0)[0] == pytest.approx(0.5)  # along +Mx -> (100, 0) vertex
    assert f(mx, my, 0.0, 80.0)[0] == pytest.approx(0.8)  # along +My -> (0, 100) vertex
    assert f(mx, my, 0.0, 0.0) == (0.0, None)             # no applied moment -> 0
    assert f(mx, my, 150.0, 0.0)[0] == pytest.approx(1.5)  # outside the envelope


def test_util_follows_the_chord_not_the_radius():
    # Between sweep points the capacity is the chord, not the (larger) radial
    # interpolation of the vertex radii.
    f = _radial_util()
    mx, my = _diamond(100.0)
    # 45 deg: the chord from (100, 0) to (0, 100) is the line Mx + My = 100, which
    # the ray (t, t) crosses at (50, 50) -> capacity radius 50*sqrt(2) ~ 70.71
    # (a radial interpolation would wrongly give 100).
    cap = 50.0 * np.sqrt(2.0)
    assert f(mx, my, 35.0, 35.0)[0] == pytest.approx(35.0 * np.sqrt(2.0) / cap)
    assert f(mx, my, 50.0, 50.0)[0] == pytest.approx(1.0)  # exactly on the chord
    assert f(mx, my, 100.0, 100.0)[0] == pytest.approx(2.0)  # twice the chord distance


def test_util_uses_the_capacity_in_the_applied_direction():
    # A section stronger about x (axis intercepts 100 / 50): the same applied radius
    # gives a different utilisation depending on direction.
    f = _radial_util()
    mx, my = [100.0, 0.0, -100.0, 0.0], [0.0, 50.0, 0.0, -50.0]
    assert f(mx, my, 50.0, 0.0)[0] == pytest.approx(0.5)  # along Mx: 50 / 100
    assert f(mx, my, 0.0, 25.0)[0] == pytest.approx(0.5)  # along My: 25 / 50
    assert f(mx, my, 0.0, 50.0)[0] == pytest.approx(1.0)  # My capacity, on boundary


def test_util_matches_dense_circle_radius():
    # On a finely sampled circular envelope the chord ~ the radius, so a ray through
    # a vertex still reads the radius to good precision.
    f = _radial_util()
    th = np.linspace(0.0, 2.0 * np.pi, 72, endpoint=False)
    mx, my = (100.0 * np.cos(th)).tolist(), (100.0 * np.sin(th)).tolist()
    assert f(mx, my, 50.0, 0.0)[0] == pytest.approx(0.5)  # +Mx is a sample point
    assert f(mx, my, 0.0, 80.0)[0] == pytest.approx(0.8)  # +My is a sample point


def test_util_reports_the_governing_vertex():
    # The governing index is the swept point in the applied load's direction -- the
    # endpoint of the crossed chord nearest the crossing. This is what the report's
    # worked case and the Plastic view's default state use, so a pure-Mx load lands on
    # the Mx vertex rather than the strongest (about-y) point of the envelope.
    f = _radial_util()
    mx, my = _diamond(100.0)               # vertices 0:+Mx 1:+My 2:-Mx 3:-My
    assert f(mx, my, 50.0, 0.0)[1] == 0    # +Mx load -> the +Mx vertex
    assert f(mx, my, 0.0, 80.0)[1] == 1    # +My load -> the +My vertex
    assert f(mx, my, -30.0, 0.0)[1] == 2   # -Mx load -> the -Mx vertex
    assert f(mx, my, 90.0, 10.0)[1] == 0   # just off +Mx -> the nearer (+Mx) vertex
    assert f(mx, my, 0.0, 0.0)[1] is None  # no applied direction -> no governing index
