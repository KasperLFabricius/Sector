"""Verification of the plastic solver with prestressing tendons.

The case is the manual's prestressed T-beam example (concrete type 1, mild steel
type 1, prestress type 1 with a 0.40 % initial strain). The ultimate capacity
(Mx, My), the concrete/steel/cable strains, the curvature and the neutral-axis
intercepts reproduce the printout. (The diagnostic compression-force and
internal-lever-arm outputs use a different internal decomposition with prestress
and are not asserted here.)
"""

from __future__ import annotations

import math

import pytest

from sector.materials import Concrete, MildSteel, Prestress
from sector.plastic import plastic_capacity_at_angle, solve_plastic
from sector.section import Section


def t_beam():
    mild_xy = [
        (-.55, .30), (-.50, .30), (-.30, .30), (-.10, .30), (.10, .30),
        (.30, .30), (.50, .30), (.55, .30),
        (-.55, .25), (.55, .25),
        (-.55, .20), (-.50, .20), (-.30, .20), (-.10, .20), (.10, .20),
        (.30, .20), (.50, .20), (.55, .20),
        (-.10, -.07), (.10, -.07), (-.10, -.35), (.10, -.35),
        (-.10, -.55), (.10, -.55),
        (-.10, -.60), (-.03, -.60), (.03, -.60), (.10, -.60),
    ]
    section = Section.from_polygon(
        corners=[(-.6, .35), (.6, .35), (.6, .15), (.15, .15),
                 (.15, -.65), (-.15, -.65), (-.15, .15), (-.6, .15)],
        bars_xy_area_mm2=[(x, y, 491.0) for x, y in mild_xy],
        tendons_xy_area_mm2=[(0.0, -.38, 1016.0), (0.0, -.54, 1016.0)],
    )
    concrete = Concrete(fck=18.0, gamma_c=1.9, curve=1)
    steel = MildSteel(fytk=225.0, fyck=225.0, eut=0.20, futk=225.0,
                      gamma_y=1.5, gamma_u=1.5, gamma_E=1.5, curve=1)
    prestress = Prestress(curve=1, IS=0.004, gamma_y=1.5)
    return section, concrete, steel, prestress


# V, Mx, My, eps_steel, eps_cable, curvature, na_y (or None for inf)
TBEAM_CASES = [
    (0.0, 302.1, 914.8, -0.22, -0.35, 0.004959, None),
    (90.0, 2027.5, 0.0, -0.34, -0.70, 0.007273, -0.131),
    (270.0, -863.3, 0.0, -0.06, -0.17, 0.004286, 0.167),
]


@pytest.mark.parametrize("case", TBEAM_CASES, ids=[f"V{int(c[0])}" for c in TBEAM_CASES])
def test_prestressed_tbeam_matches_handcalc(case):
    V, Mx, My, eps_s, eps_c, curv, na_y = case
    section, concrete, steel, prestress = t_beam()
    r = plastic_capacity_at_angle(section, concrete, steel, 1976.0, V, prestress=prestress)

    assert r.converged
    assert r.Mx == pytest.approx(Mx, abs=1.5)
    assert r.My == pytest.approx(My, abs=1.5)
    assert r.eps_concrete == pytest.approx(0.35)
    assert r.eps_steel == pytest.approx(eps_s, abs=0.02)
    assert r.eps_cable == pytest.approx(eps_c, abs=0.02)
    assert r.curvature == pytest.approx(curv, abs=5e-5)
    if na_y is None:
        assert math.isinf(r.na_y_intercept)
    else:
        assert r.na_y_intercept == pytest.approx(na_y, abs=0.002)


def test_cable_strain_includes_initial_prestrain():
    # At V=90 the lower cable's reported strain is the total tendon strain
    # (compression positive): -(IS + section tension) = -(0.40 + ~0.30) ~ -0.70 %.
    section, concrete, steel, prestress = t_beam()
    r = plastic_capacity_at_angle(section, concrete, steel, 1976.0, 90.0, prestress=prestress)
    assert r.eps_cable == pytest.approx(-0.70, abs=0.02)
    # Without the prestrain the reported strain would be the section strain only
    # (smaller magnitude); the IS offset is what brings it to ~0.70 %.
    assert abs(r.eps_cable) > 0.40


def test_solve_plastic_passes_prestress_through_sweep():
    section, concrete, steel, prestress = t_beam()
    pts = solve_plastic(section, concrete, steel, 1976.0, 0.0, 270.0, 90.0,
                        prestress=prestress)
    assert len(pts) == 4
    assert pts[1].V == 90.0
    assert pts[1].Mx == pytest.approx(2027.5, abs=1.5)


def _axial_endpoints(section, concrete, steel, prestress, angle=90.0):
    """Read the finite endpoint equilibria returned by deliberate range probes."""
    tension = plastic_capacity_at_angle(
        section, concrete, steel, -1.0e12, angle, prestress=prestress
    ).axial
    compression = plastic_capacity_at_angle(
        section, concrete, steel, 1.0e12, angle, prestress=prestress
    ).axial
    return tension, compression


@pytest.mark.parametrize("endpoint_index,direction", [(0, -1.0), (1, 1.0)],
                         ids=["below-tension", "above-compression"])
def test_just_outside_axial_range_is_not_converged_within_residual_tolerance(
        endpoint_index, direction):
    section, concrete, steel, prestress = t_beam()
    endpoints = _axial_endpoints(section, concrete, steel, prestress)
    endpoint = endpoints[endpoint_index]
    residual_tolerance = 1.0e-6 * max(1.0, abs(endpoint))
    requested = endpoint + direction * 0.25 * residual_tolerance

    point = plastic_capacity_at_angle(
        section, concrete, steel, requested, 90.0, prestress=prestress
    )

    # This is the dangerous case: the finite clamped response passes the historical
    # residual-only criterion, but the requested axial action is not reachable.
    assert math.isfinite(point.axial)
    assert abs(point.axial - requested) < 1.0e-6 * max(1.0, abs(requested))
    assert point.converged is False


def test_exact_axial_endpoints_and_interior_remain_converged():
    section, concrete, steel, prestress = t_beam()
    tension, compression = _axial_endpoints(section, concrete, steel, prestress)

    for requested in (tension, 1976.0, compression):
        point = plastic_capacity_at_angle(
            section, concrete, steel, requested, 90.0, prestress=prestress
        )
        assert point.converged is True
        assert point.axial == pytest.approx(
            requested, abs=1.0e-6 * max(1.0, abs(requested))
        )


@pytest.mark.parametrize("endpoint_index,direction", [(0, -1.0), (1, 1.0)],
                         ids=["tension-sweep", "compression-sweep"])
def test_unreachable_axial_sweep_has_no_false_finite_convergence(
        endpoint_index, direction):
    section, concrete, steel, prestress = t_beam()
    endpoint = _axial_endpoints(
        section, concrete, steel, prestress
    )[endpoint_index]
    residual_tolerance = 1.0e-6 * max(1.0, abs(endpoint))
    requested = endpoint + direction * 0.25 * residual_tolerance

    points = solve_plastic(
        section, concrete, steel, requested, 0.0, 270.0, 90.0,
        prestress=prestress,
    )

    assert all(
        math.isfinite(value)
        for point in points
        for value in (point.axial, point.Mx, point.My)
    )
    historical_tolerance = 1.0e-6 * max(1.0, abs(requested))
    assert any(
        abs(point.axial - requested) < historical_tolerance
        for point in points
    )
    assert all(point.converged is False for point in points)


def test_tendons_omitted_when_no_prestress_material():
    # Without a prestress material the tendons are simply not counted.
    section, concrete, steel, _ = t_beam()
    with_pre = plastic_capacity_at_angle(section, concrete, steel, 1976.0, 90.0,
                                         prestress=Prestress(curve=1, IS=0.004, gamma_y=1.5))
    without = plastic_capacity_at_angle(section, concrete, steel, 1976.0, 90.0)
    assert with_pre.Mx != pytest.approx(without.Mx, abs=1.0)
    assert without.eps_cable == 0.0
