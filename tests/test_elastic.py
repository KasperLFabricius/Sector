"""Verification of the elastic cracked-section solver.

The headline cases are the rectangular cross-section worked example, whose
published results are reproduced here as parametrised cases. Stresses are
compared in kN/m^2 (the units the worked example reports) within a tolerance
that absorbs the rounding of the original printout; the modern production
fixtures verified later are higher precision.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sector.elastic import solve_elastic
from sector.section import Section


def rectangular_section() -> Section:
    """1 m square, four 491 mm^2 bars 50 mm in from each corner."""
    return Section.from_polygon(
        corners=[(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)],
        bars_xy_area_mm2=[
            (0.05, 0.05, 491.0),
            (0.05, 0.95, 491.0),
            (0.95, 0.95, 491.0),
            (0.95, 0.05, 491.0),
        ],
    )


def centered_section() -> Section:
    """1 m square centred on the origin (centroid at the origin).

    Used for symmetry checks: because the moments are taken about the origin,
    putting the centroid there makes an axial load with zero moments truly
    concentric and makes a sign flip of My a clean reflection across x = 0.
    """
    return Section.from_polygon(
        corners=[(-0.5, -0.5), (-0.5, 0.5), (0.5, 0.5), (0.5, -0.5)],
        bars_xy_area_mm2=[
            (-0.45, -0.45, 491.0),
            (-0.45, 0.45, 491.0),
            (0.45, 0.45, 491.0),
            (0.45, -0.45, 491.0),
        ],
    )


# (name, P, Mx, My, n, max_comp, comp_point, bar_stresses, x_int, y_int)
WORKED_CASES = [
    ("LC1", 1000.0, 200.0, 200.0, 25.0, 5744.0, 0,
     [-129430.0, -2689.0, 124051.0, -2689.0], 1.0191, 1.0191),
    ("LC3", 900.0, 300.0, -100.0, 25.0, 7647.0, 0,
     [-165689.0, -78600.0, 293135.0, 206046.0], 0.462861, 1.975691),
    ("LC4", 0.0, 90.0, 0.0, 25.0, 949.0, 1,
     [102717.0, -17009.0, -17009.0, 102717.0], math.inf, 0.8221397),
    ("LC5", 0.0, 90.0, 0.0, 8.0, 1656.0, 1,
     [100473.0, -7256.0, -7256.0, 100473.0], math.inf, 0.8893836),
]


@pytest.mark.parametrize("case", WORKED_CASES, ids=[c[0] for c in WORKED_CASES])
def test_worked_rectangular_example(case):
    name, P, Mx, My, n, max_comp, comp_pt, bars, x_int, y_int = case
    res = solve_elastic(rectangular_section(), P, Mx, My, n)

    assert res.converged
    # Stresses to ~0.5% (worst published case LC1 differs by ~0.1%).
    assert res.max_concrete_compression == pytest.approx(max_comp, rel=0.005, abs=20)
    assert res.max_concrete_point == comp_pt
    for got, exp in zip(res.bar_stress, bars):
        assert got == pytest.approx(exp, rel=0.005, abs=20)

    if math.isinf(x_int):
        assert math.isinf(res.na_x_intercept)
    else:
        assert res.na_x_intercept == pytest.approx(x_int, rel=0.002)
    if math.isinf(y_int):
        assert math.isinf(res.na_y_intercept)
    else:
        assert res.na_y_intercept == pytest.approx(y_int, rel=0.002)


def test_pure_axial_compression_is_uniform():
    # Concentric axial load (centroid at the origin, no moments): the section is
    # uniformly compressed (no neutral axis), so the stress follows the closed
    # form sigma = P / (A_concrete + n * A_steel).
    sec = centered_section()
    n = 25.0
    P = 1000.0
    res = solve_elastic(sec, P, 0.0, 0.0, n)

    a_concrete = 1.0
    a_steel = 4 * 491.0e-6
    eps0 = -P / (a_concrete + n * a_steel)
    assert res.converged
    assert res.eps0 == pytest.approx(eps0)
    assert res.kx == pytest.approx(0.0, abs=1e-9)
    assert res.ky == pytest.approx(0.0, abs=1e-9)
    # Concrete compression magnitude = |eps0| (Ec = 1); all bars equal n*eps0.
    assert res.max_concrete_compression == pytest.approx(-eps0)
    assert np.allclose(res.bar_stress, n * eps0)
    # No tension anywhere -> neutral axis at infinity on both axes.
    assert math.isinf(res.na_x_intercept) and math.isinf(res.na_y_intercept)


def test_symmetry_uniaxial_bending_keeps_axis_straight():
    # Bending about X only (My = 0) on an x-symmetric section: the strain plane
    # must not tilt in x.
    res = solve_elastic(rectangular_section(), 0.0, 90.0, 0.0, 25.0)
    assert res.kx == pytest.approx(0.0, abs=1e-6 * abs(res.ky))


def test_sign_flip_of_moment_mirrors_result():
    # On an origin-symmetric section, flipping My reflects the problem across
    # x = 0, so the bar stresses mirror left<->right (bar0<->bar3, bar1<->bar2).
    sec = centered_section()
    a = solve_elastic(sec, 900.0, 300.0, 100.0, 25.0)
    b = solve_elastic(sec, 900.0, 300.0, -100.0, 25.0)
    assert a.bar_stress[0] == pytest.approx(b.bar_stress[3], rel=1e-9, abs=1e-6)
    assert a.bar_stress[1] == pytest.approx(b.bar_stress[2], rel=1e-9, abs=1e-6)


def test_solver_converges_quickly():
    res = solve_elastic(rectangular_section(), 1000.0, 200.0, 200.0, 25.0)
    assert res.converged
    assert res.iterations <= 12
