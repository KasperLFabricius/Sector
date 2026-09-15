"""Analytical checks of the default net-concrete elastic area model."""

import numpy as np
import pytest

from sector.elastic import (
    solve_elastic,
    solve_elastic_combined,
    solve_elastic_uncracked,
    transformed_properties,
)
from sector.serviceability import analyse_cracking
from sector.section import Section


def section():
    return Section.from_polygon(
        [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)],
        [(-0.25, -0.25, 2000), (0.25, -0.25, 2000),
         (-0.25, 0.25, 2000), (0.25, 0.25, 2000)],
    )


def test_default_matches_review_rc_stress_methodology_example():
    # Independent two-layer equilibrium solution retained in the user's
    # "Review RC stress methodology" comparison (98 kN, 461 kNm).
    sec = Section.from_polygon(
        [(-0.5, -0.3), (0.5, -0.3), (0.5, 0.3), (-0.5, 0.3)],
        [(x, 0.3-depth/1000, area/2)
         for depth, area in [(63.5, 2454.369260617026), (539, 3141.5926535897934)]
         for x in [-0.25, 0.25]],
    )
    result = solve_elastic(sec, 98, 461, 0, 5.543784140944425)
    assert result.converged
    assert (0.3-result.na_y_intercept)*1000 == pytest.approx(121.86355484824293)
    assert result.max_concrete_compression/1000 == pytest.approx(14.721043925963777)
    assert max(result.bar_stress)/1000 == pytest.approx(279.35034588702626)


@pytest.mark.parametrize("P", [-1000.0, 1000.0])
@pytest.mark.parametrize("displace", [True, False])
def test_uncracked_axial_stiffness_and_physical_steel_stress(P, displace):
    sec = section()
    result = solve_elastic_uncracked(sec, P, 0, 0, 10,
                                     displace_concrete=displace)
    expected = -P / (1 + (10 - int(displace)) * 0.008)
    assert result.converged
    assert result.strain_plane == pytest.approx((expected, 0, 0), abs=1e-10)
    assert result.bar_stress == pytest.approx(np.full(4, 10 * expected))


@pytest.mark.parametrize("cracked", [True, False])
def test_prescribed_plane_recovers_load_and_transformed_properties(cracked):
    # Prescribe eps=y. Integrate the unit rectangle analytically, then add
    # physical bar forces and subtract the concrete forces at occupied points.
    sec = section()
    x, y, a = sec.bar_arrays()
    ratios = np.array([10, 12, 14, 16])
    concrete_at_bars = np.minimum(y, 0) if cracked else y
    force = (ratios * y - concrete_at_bars) * a
    concrete_N = -1 / 8 if cracked else 0
    concrete_Mx = 1 / 24 if cracked else 1 / 12
    N = concrete_N + force.sum()
    Mx = concrete_Mx + (force * y).sum()
    My = (force * x).sum()
    solve = solve_elastic if cracked else solve_elastic_uncracked
    result = solve(sec, -N, -Mx, -My, 10, n_mult=ratios / 10)
    assert result.converged
    assert result.strain_plane == pytest.approx((0, 0, 1), abs=5e-9)
    assert result.bar_stress == pytest.approx(ratios * y)
    props = transformed_properties(sec, 10, cracked=cracked,
                                   eps0=0, kx=0, ky=1, n_mult=ratios / 10)
    weights = (ratios - ((y < 0) if cracked else 1)) * a
    A = (0.5 if cracked else 1) + weights.sum()
    Sx = (weights * x).sum()
    Sy = (-1 / 8 if cracked else 0) + (weights * y).sum()
    assert props.area == pytest.approx(A)
    assert props.cx == pytest.approx(Sx / A)
    assert props.cy == pytest.approx(Sy / A)
    assert props.Ix == pytest.approx(concrete_Mx + (weights*y*y).sum() - Sy*Sy/A)
    # The published properties reproduce the stiffness used by the solver.
    matrix = np.asarray(result.equilibrium.equilibrium_matrix)
    assert matrix[0] == pytest.approx((A, Sx, Sy))
    assert matrix[1, 2] == pytest.approx(props.Ix + A * props.cy**2)


def test_cracking_factor_uses_net_uncracked_inertia():
    sec = section()
    # Symmetric pure bending: I = bh^3/12 + (n-1)*sum(As*y^2).
    I = 1 / 12 + 9 * 0.008 * 0.25**2
    M = 1000.0
    fctm = 3.0
    result = analyse_cracking(sec, 0, M, 0, 10, fctm=fctm)
    assert result.lambda_cr == pytest.approx(fctm * 1000 * I / (M * 0.5))


@pytest.mark.parametrize("prestress", [0.0, 10000.0])
def test_combined_uniform_compression_recovers_total_force(prestress):
    sec = section()
    # Alternating materials, symmetric about the centroid. Locked-in stresses
    # exercise the retained prestress and creep-neutralisation terms together.
    mult = np.array([1, 1.2, 1.2, 1])
    ps = np.full(4, prestress)
    result = solve_elastic_combined(sec, 1000, 0, 0, 20, 300, 0, 0, 8,
                                    n_mult=mult, prestress_stress=ps)
    assert result.converged
    expected_long = -(1000 + prestress * 0.008) / (1 + ((20*mult-1)*0.002).sum())
    assert result.long.eps0 == pytest.approx(expected_long)
    assert result.long.bar_stress == pytest.approx(20 * mult * expected_long)
    # Physical concrete occupies 1-As; physical steel includes full stresses.
    concrete_force = result.short_term.eps0 * (1 - 0.008)
    steel_force = result.bar_stress_total.sum() * 0.002
    assert concrete_force + steel_force == pytest.approx(-1300, abs=1e-8)

