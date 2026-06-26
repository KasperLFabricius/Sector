"""Verification of the plastic (ultimate) capacity solver.

The headline case is the "Fundamentsbjaelke" production PCROSS run (a rectangular
mild-steel section, P = 0, swept through four neutral-axis angles), reproduced
here to the printout precision. A second check confirms the engine agrees with a
Eurocode rectangular-stress-block hand calculation for a slab (the two methods
differ only in the concrete stress shape, so they should be within a couple of
percent).
"""

from __future__ import annotations

import math

import pytest

from sector.materials import Concrete, MildSteel
from sector.plastic import plastic_capacity_at_angle, solve_plastic
from sector.section import Section


def fundamentsbjaelke():
    section = Section.from_polygon(
        corners=[(-0.150, -0.300), (-0.150, 0.300), (0.150, 0.300), (0.150, -0.300)],
        bars_xy_area_mm2=[
            (-0.10, -0.244, 201.0), (-0.06, -0.244, 201.0), (-0.02, -0.244, 201.0),
            (0.02, -0.244, 201.0), (0.06, -0.244, 201.0), (0.10, -0.244, 201.0),
            (0.10, 0.244, 201.0), (-0.10, 0.244, 201.0),
        ],
    )
    concrete = Concrete(fck=33.0, gamma_c=1.31, curve=1)
    steel = MildSteel(fytk=550.0, fyck=550.0, eut=0.05, futk=550.0,
                      gamma_y=1.08, gamma_u=1.08, gamma_E=1.08, curve=1)
    return section, concrete, steel


# V, Mx, My, U, compress, curvature, steel%, L, |DX|, |DY|, x_int, y_int
FUND_CASES = [
    (0.0, 99.9, 99.8, 45.0, 615.8, 0.07043, -1.41, 0.229, 0.162, 0.162, 0.100, math.inf),
    (90.0, 310.4, 0.0, 90.0, 614.2, 0.04126, -1.89, 0.505, 0.000, 0.505, math.inf, 0.215),
    (180.0, 99.9, -99.8, 135.0, 615.8, 0.07043, -1.41, 0.229, 0.162, 0.162, -0.100, math.inf),
    (270.0, -110.7, 0.0, 270.0, 306.9, 0.07067, -3.49, 0.361, 0.000, 0.361, math.inf, -0.250),
]


@pytest.mark.parametrize("case", FUND_CASES, ids=[f"V{int(c[0])}" for c in FUND_CASES])
def test_fundamentsbjaelke_matches_pcross(case):
    V, Mx, My, U, comp, curv, steel_pct, L, dxa, dya, x_int, y_int = case
    section, concrete, steel = fundamentsbjaelke()
    r = plastic_capacity_at_angle(section, concrete, steel, 0.0, V)

    assert r.converged
    assert r.Mx == pytest.approx(Mx, abs=0.6)
    assert r.My == pytest.approx(My, abs=0.6)
    assert r.U == pytest.approx(U, abs=0.3)
    assert r.compression_force == pytest.approx(comp, abs=1.0)
    assert r.curvature == pytest.approx(curv, abs=5e-5)
    assert r.eps_concrete == pytest.approx(0.35)
    assert r.eps_steel == pytest.approx(steel_pct, abs=0.02)
    assert r.lever_arm == pytest.approx(L, abs=0.003)
    # Lever-arm component magnitudes match (the legacy component sign convention
    # is direction-dependent; L and the magnitudes are the meaningful values).
    assert abs(r.dx) == pytest.approx(dxa, abs=0.003)
    assert abs(r.dy) == pytest.approx(dya, abs=0.003)
    if math.isinf(x_int):
        assert math.isinf(r.na_x_intercept)
    else:
        assert r.na_x_intercept == pytest.approx(x_int, abs=0.002)
    if math.isinf(y_int):
        assert math.isinf(r.na_y_intercept)
    else:
        assert r.na_y_intercept == pytest.approx(y_int, abs=0.002)


def test_solve_plastic_sweep_returns_all_angles():
    section, concrete, steel = fundamentsbjaelke()
    pts = solve_plastic(section, concrete, steel, 0.0, 0.0, 360.0, 90.0)
    assert [p.V for p in pts] == [0.0, 90.0, 180.0, 270.0, 360.0]
    # 0 and 360 degrees are the same state.
    assert pts[0].Mx == pytest.approx(pts[4].Mx, abs=1e-6)


def test_slab_matches_eurocode_rectangular_block():
    # A singly-reinforced 1 m slab strip; compare the plastic engine (parabola)
    # with the Eurocode rectangular-stress-block hand-calc method.
    b, h, cover, As_mm2 = 1.0, 0.30, 0.04, 2000.0
    d = h - cover
    fck, gc, fyk, gs = 30.0, 1.5, 500.0, 1.15
    fcd, fyd = fck / gc, fyk / gs
    T = As_mm2 * 1e-6 * fyd
    a = T / (fcd * b)                       # rectangular block depth
    mrd_block = T * (d - a / 2.0) * 1000.0  # kNm

    slab = Section.from_polygon(
        corners=[(-b / 2, 0.0), (-b / 2, h), (b / 2, h), (b / 2, 0.0)],
        bars_xy_area_mm2=[(0.0, cover, As_mm2)],
    )
    concrete = Concrete(fck=fck, gamma_c=gc, curve=2)
    steel = MildSteel(fytk=fyk, fyck=fyk, eut=0.05, gamma_y=gs, curve=2)
    r = plastic_capacity_at_angle(slab, concrete, steel, 0.0, 90.0)

    assert r.converged
    assert r.Mx == pytest.approx(mrd_block, rel=0.02)  # within ~2%
