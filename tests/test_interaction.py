"""Tests for the N-M interaction sweep (sector.plastic.solve_interaction).

The interaction diagram traces the ultimate moment against axial force at a fixed
neutral-axis angle. It reuses the plastic capacity solver, so the tests check the
structural invariants of the curve (range, monotone axial, interior peak, squash
apex) and that each point agrees with a direct capacity solve at the same N.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402  (real app preset materials + example sections)
from sector.plastic import (  # noqa: E402
    plastic_capacity_at_angle,
    solve_interaction,
)


def _beam():
    ex = manual.example_beam()
    return manual._section_of(ex), ex["concrete"], ex["steel"], None


def _circular():
    ex = manual.example_circular()
    return manual._section_of(ex), ex["concrete"], ex["steel"], ex["prestress"]


def test_plastic_point_reports_the_achieved_axial():
    sec, c, s, _ = _beam()
    r = plastic_capacity_at_angle(sec, c, s, 200.0, 90.0)
    assert r.axial == pytest.approx(200.0, abs=1e-3)   # equilibrium met at the target


def test_interaction_spans_tension_to_squash_with_interior_peak():
    sec, c, s, _ = _beam()
    pts = solve_interaction(sec, c, s, 90.0, n_points=24)
    N = [p.axial for p in pts]
    Mx = [p.Mx for p in pts]
    assert N[0] < 0.0 < N[-1]                          # tension end .. squash end
    assert all(N[i] <= N[i + 1] + 1e-6 for i in range(len(N) - 1))   # monotone axial
    # The peak moment (balanced point) is in the interior and exceeds both ends; the
    # ends carry a moment for this singly-reinforced beam (asymmetric steel), so they
    # are not zero -- only the peak-is-interior structure is asserted.
    i_peak = max(range(len(Mx)), key=lambda i: Mx[i])
    assert 0 < i_peak < len(Mx) - 1
    assert max(Mx) > Mx[0] and max(Mx) > Mx[-1]


def test_symmetric_section_has_zero_moment_at_the_axial_extremes():
    # A doubly-symmetric section carries no moment under uniform strain, so both the
    # tension and the squash apex sit on the N axis (Mx = 0).
    import numpy as np
    from sector.section import Section
    ex = manual.example_beam()
    c, s = ex["concrete"], ex["steel"]
    a = np.pi / 4 * 0.02 ** 2
    bars = ([(x, -0.25, a) for x in (-0.15, 0.0, 0.15)]
            + [(x, 0.25, a) for x in (-0.15, 0.0, 0.15)])   # symmetric top and bottom
    sec = Section.from_polygon(
        corners=[(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)],
        bars_xy_area_mm2=bars)
    pts = solve_interaction(sec, c, s, 90.0, n_points=24)
    assert pts[0].Mx == pytest.approx(0.0, abs=2.0)    # tension apex on the axis
    assert pts[-1].Mx == pytest.approx(0.0, abs=2.0)   # squash apex on the axis


def test_interaction_points_match_a_direct_capacity_solve():
    sec, c, s, _ = _beam()
    pts = solve_interaction(sec, c, s, 90.0, n_points=16)
    # Every interior point must reproduce a direct plastic solve at the same axial.
    for p in pts[3:-3]:
        direct = plastic_capacity_at_angle(sec, c, s, p.axial, 90.0)
        assert p.Mx == pytest.approx(direct.Mx, rel=1e-6, abs=1e-6)


def test_interaction_moment_capacity_matches_the_zero_axial_capacity():
    # At N = 0 the interaction moment equals the plastic capacity for P = 0.
    sec, c, s, _ = _beam()
    pts = solve_interaction(sec, c, s, 90.0, n_points=40)
    i0 = min(range(len(pts)), key=lambda i: abs(pts[i].axial))
    m0 = plastic_capacity_at_angle(sec, c, s, 0.0, 90.0).Mx
    assert pts[i0].Mx == pytest.approx(m0, rel=0.02)


def test_interaction_handles_a_prestressed_section():
    sec, c, s, pre = _circular()
    pts = solve_interaction(sec, c, s, 90.0, prestress=pre, n_points=20)
    N = [p.axial for p in pts]
    assert N[0] < N[-1]                                 # spans a real axial range
    assert all(p.converged for p in pts[2:-2])          # interior points converge


def test_interaction_reaches_the_true_axial_limits_with_prestress():
    # Tendons yield far above the mild bars, so the tension probe must use the
    # prestress design stress -- otherwise the diagram stops short of the true
    # tension capacity. Both ends must reach the clamped extremes of a direct solve.
    sec, c, s, pre = _circular()
    true_Nt = plastic_capacity_at_angle(sec, c, s, -1.0e7, 90.0, prestress=pre).axial
    true_Nc = plastic_capacity_at_angle(sec, c, s, +1.0e7, 90.0, prestress=pre).axial
    pts = solve_interaction(sec, c, s, 90.0, prestress=pre, n_points=8)
    assert pts[0].axial == pytest.approx(true_Nt, abs=1.0)    # tension limit reached
    assert pts[-1].axial == pytest.approx(true_Nc, abs=1.0)   # squash reached
