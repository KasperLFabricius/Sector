"""Verification of the plastic capacity solver.

The headline case is the "Fundamentsbjaelke" production handcalc run (a rectangular
mild-steel section, P = 0, swept through four neutral-axis angles), reproduced
here to the printout precision. A second check confirms the engine agrees with a
Eurocode rectangular-stress-block hand calculation for a slab (the two methods
differ only in the concrete stress shape, so they should be within a couple of
percent).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sector.materials import Concrete, MildSteel
from sector.plastic import _band_stresses, plastic_capacity_at_angle, solve_plastic
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
def test_fundamentsbjaelke_matches_handcalc(case):
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
    # Lever-arm component magnitudes match (the handcalc component sign convention
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


def test_eps_steel_comp_is_the_most_compressed_bar_strain():
    # The solver reports both mild-steel strain extremes (compression-positive): the
    # most tensile (eps_steel) and the most compressed (eps_steel_comp). At V = 90 the
    # top and bottom bars strain differently, so the two extremes differ.
    section, concrete, steel = fundamentsbjaelke()
    r = plastic_capacity_at_angle(section, concrete, steel, 0.0, 90.0)
    assert r.eps_steel_comp >= r.eps_steel          # max >= min, by definition
    assert r.eps_steel_comp != r.eps_steel          # a distinct extreme, not a copy


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


def test_governing_curvature_caps_compression_steel_rupture():
    # The symmetric rupture must also cap the curvature for a compression bar: with
    # eut below the concrete crushing strain, a compression bar reaches eut first.
    import numpy as np
    from sector.plastic import _governing_curvature
    # s_na = s_max - c = 0.1. A bar 0.08 past the NA on the compression side (s = 0.18)
    # reaches eut = 2 permille before the concrete crushes. s_bars are the projections.
    s_bars = np.array([0.18, 0.099])
    empty = np.empty(0)
    low = MildSteel(fytk=500.0, fyck=500.0, eut=0.002, gamma_y=1.0, curve=2)
    phi = _governing_curvature(low, None, 0.2, 0.1, s_bars, empty, 0.0035)
    assert phi == pytest.approx(0.002 / 0.08, rel=1e-6)    # compression bar governs
    # With a large eut the concrete crushing limit governs instead (no cap effect).
    high = MildSteel(fytk=500.0, fyck=500.0, eut=0.05, gamma_y=1.0, curve=2)
    phi2 = _governing_curvature(high, None, 0.2, 0.1, s_bars, empty, 0.0035)
    assert phi2 == pytest.approx(0.0035 / 0.1, rel=1e-6)   # concrete governs


def test_plastic_capacity_responds_to_ultimate_strain():
    # The solver must use the concrete's own eps_cu2/eps_c2: with the steel forced
    # to govern by yield (no rupture), changing the crushing strain reshapes the
    # compression stress block, so the ultimate moment changes.
    b, h, cover, As_mm2 = 1.0, 0.30, 0.04, 2000.0
    slab = Section.from_polygon(
        corners=[(-b / 2, 0.0), (-b / 2, h), (b / 2, h), (b / 2, 0.0)],
        bars_xy_area_mm2=[(0.0, cover, As_mm2)],
    )
    steel = MildSteel(fytk=500.0, fyck=500.0, eut=1.0, gamma_y=1.15, curve=2)
    full = Concrete(fck=30.0, gamma_c=1.5, curve=2)                  # eps_cu2 = 3.5 permille
    short = Concrete(fck=30.0, gamma_c=1.5, curve=2, eps_cu2=0.0022)  # almost no plateau
    m_full = plastic_capacity_at_angle(slab, full, steel, 0.0, 90.0).Mx
    m_short = plastic_capacity_at_angle(slab, short, steel, 0.0, 90.0).Mx
    assert abs(m_full - m_short) / m_full > 0.003   # eps_cu2 visibly changes Mrd


def _rect_with_top_and_bottom_bars():
    return Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        bars_xy_area_mm2=[(0.15, 0.05, 500.0), (0.15, 0.55, 500.0)],
    )


_C30 = Concrete(fck=30.0, gamma_c=1.5, curve=2)
_B500 = MildSteel(fytk=500.0, fyck=500.0, futk=500.0, eut=0.05,
                  gamma_y=1.15, gamma_u=1.15, gamma_E=1.0, curve=1)


def test_all_compressed_section_reports_the_bar_strain():
    # Under high axial compression every bar is compressed; the reported most-tensile
    # steel strain is the least-compressed bar's actual (positive) strain, not a
    # floor of zero.
    r = plastic_capacity_at_angle(_rect_with_top_and_bottom_bars(), _C30, _B500,
                                  3500.0, 90.0)
    assert r.converged
    assert r.eps_steel > 0.0


def test_unreachable_axial_is_flagged_not_converged():
    # An axial force above the squash load cannot be balanced: the point is flagged
    # not-converged (non-zero equilibrium residual), while a reachable one converges.
    sec = _rect_with_top_and_bottom_bars()
    assert not plastic_capacity_at_angle(sec, _C30, _B500, 1.0e6, 90.0).converged
    assert plastic_capacity_at_angle(sec, _C30, _B500, 0.0, 90.0).converged


def test_shared_prep_matches_standalone_solve():
    # solve_plastic builds the angle-independent prep once and reuses it across the
    # sweep (and shares the kernel scratch buffers). Each swept point must be bit-for-
    # bit identical to a standalone plastic_capacity_at_angle (prep=None) at the same
    # angle -- the hoist is a pure speed-up, not a change of result.
    section, concrete, steel = fundamentsbjaelke()
    swept = solve_plastic(section, concrete, steel, 150.0, 0.0, 360.0, 12.0)
    for p in swept:
        d = plastic_capacity_at_angle(section, concrete, steel, 150.0, p.V)
        assert p.Mx == d.Mx and p.My == d.My and p.axial == d.axial
        assert p.compression_force == d.compression_force
        assert p.curvature == d.curvature and p.lever_arm == d.lever_arm


def test_band_stress_memo_collapses_equal_kappa_h_and_preserves_values():
    # The band-midpoint strain is kappa*(i+0.5)*h -- the neutral-axis depth cancels --
    # so the band stresses are a function of the product kappa*h alone. The per-sweep
    # memo (v0.71) exploits that: two calls with the same kappa*h but different splits
    # collapse to one cached array, and memoization does not change the values a
    # no-memo call produces.
    conc = Concrete(fck=35.0, gamma_c=1.5, curve=2)
    memo: dict = {}
    a = _band_stresses(conc, 0.020, 0.0010, 40, memo=memo)   # kappa*h = 2.0e-5
    b = _band_stresses(conc, 0.040, 0.0005, 40, memo=memo)   # kappa*h = 2.0e-5
    assert a is b and len(memo) == 1                          # one cached array, reused
    assert np.allclose(a, _band_stresses(conc, 0.020, 0.0010, 40),
                       rtol=0.0, atol=1e-12)                  # memo preserves the values
