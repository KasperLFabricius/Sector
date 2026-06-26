"""Tests for the plastic-analysis material laws, against the published curves."""

from __future__ import annotations

import pytest

from sector.materials import (
    ES,
    EPS_CU,
    EPS_C_PEAK,
    EPS_P_RES,
    Concrete,
    MildSteel,
    Prestress,
)


# ---------------------------------------------------------------------------
# Concrete
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("curve", [1, 2])
def test_concrete_zero_in_tension_and_at_origin(curve):
    c = Concrete(fck=30.0, curve=curve)
    assert c.stress(0.0) == 0.0
    assert c.stress(0.001) == 0.0  # tension -> no stress


@pytest.mark.parametrize("curve", [1, 2])
def test_concrete_plateau_equals_fck_between_peak_and_ultimate(curve):
    c = Concrete(fck=30.0, curve=curve)
    # Characteristic compressive stress is fck across [0.2 %, 0.35 %].
    for e in (EPS_C_PEAK, 0.0025, EPS_CU):
        assert c.stress(-e, design=False) == pytest.approx(-30.0)


@pytest.mark.parametrize("curve", [1, 2])
def test_concrete_continuous_at_peak(curve):
    c = Concrete(fck=35.0, curve=curve)
    just_below = c.stress(-(EPS_C_PEAK - 1e-7), design=False)
    assert just_below == pytest.approx(-35.0, abs=0.05)


def test_concrete_type2_parabola_value():
    # Type 2: f = 10 e (1 - 2.5 e) fck, e in %. At e = 0.1 %: 0.75 fck.
    c = Concrete(fck=40.0, curve=2)
    assert c.stress(-0.001, design=False) == pytest.approx(-0.75 * 40.0)


def test_concrete_type1_uses_E0_formula():
    # Type 1 at e = 0.1 %, fck = 30 -> E0 = 51*30/43.
    fck = 30.0
    e0 = 51.0 * fck / (13.0 + fck)
    e = 0.1
    expected = (10 * e0 * e + 100 * (0.75 * fck - e0) * e ** 2
                + 250 * (e0 - fck) * e ** 3)
    c = Concrete(fck=fck, curve=1)
    assert c.stress(-0.001, design=False) == pytest.approx(-expected)


def test_concrete_design_scales_by_gamma_c():
    c = Concrete(fck=30.0, gamma_c=1.5, curve=2)
    assert c.fcd == pytest.approx(20.0)
    assert c.stress(-EPS_C_PEAK, design=True) == pytest.approx(-20.0)


def test_concrete_crushed_beyond_ultimate():
    c = Concrete(fck=30.0, curve=2)
    assert c.stress(-(EPS_CU + 0.001), design=False) == 0.0


# ---------------------------------------------------------------------------
# Mild steel type 2 (elastic-perfectly-plastic)
# ---------------------------------------------------------------------------


def test_mild_type2_elastic_then_yield():
    s = MildSteel(fytk=550.0, fyck=550.0, gamma_y=1.2, curve=2)
    fyd = 550.0 / 1.2
    slope = ES / 1.2
    # Elastic below yield.
    assert s.stress(0.001) == pytest.approx(slope * 0.001)
    # Yield plateau in tension and compression.
    assert s.stress(0.02) == pytest.approx(fyd)
    assert s.stress(-0.02) == pytest.approx(-fyd)


def test_mild_type2_characteristic_vs_design():
    s = MildSteel(fytk=500.0, fyck=500.0, gamma_y=1.15, curve=2)
    assert s.stress(0.02, design=False) == pytest.approx(500.0)
    assert s.stress(0.02, design=True) == pytest.approx(500.0 / 1.15)


def test_mild_type2_asymmetric_compression_yield():
    s = MildSteel(fytk=500.0, fyck=300.0, gamma_y=1.0, curve=2)
    assert s.stress(0.02) == pytest.approx(500.0)
    assert s.stress(-0.02) == pytest.approx(-300.0)


def test_mild_type2_ruptures_beyond_eut():
    s = MildSteel(fytk=500.0, fyck=500.0, eut=0.05, gamma_y=1.0, curve=2)
    assert s.stress(0.05) == pytest.approx(500.0)  # still intact at eut
    assert s.stress(0.0500001) == 0.0              # fractured just beyond
    assert s.stress(0.1) == 0.0
    # Compression has no rupture limit (it is bounded by concrete crushing).
    assert s.stress(-0.1) == pytest.approx(-500.0)


# ---------------------------------------------------------------------------
# Mild steel type 1 (bilinear with hardening)
# ---------------------------------------------------------------------------


def test_mild_type1_elastic_branch():
    s = MildSteel(fytk=500.0, fyck=500.0, eut=0.05, futk=540.0,
                  gamma_y=1.0, gamma_u=1.0, gamma_E=1.0, curve=1)
    assert s.stress(0.001) == pytest.approx(ES * 0.001)


def test_mild_type1_hardens_to_rupture_stress():
    s = MildSteel(fytk=500.0, fyck=500.0, eut=0.05, futk=540.0,
                  gamma_y=1.0, gamma_u=1.0, gamma_E=1.0, curve=1)
    eps_y = 500.0 / ES
    # Yield point and rupture point.
    assert s.stress(eps_y) == pytest.approx(500.0)
    assert s.stress(0.05) == pytest.approx(540.0)
    # Linear hardening in between.
    mid = 0.5 * (eps_y + 0.05)
    assert s.stress(mid) == pytest.approx(0.5 * (500.0 + 540.0), rel=1e-6)


def test_mild_type1_design_factors_applied():
    s = MildSteel(fytk=500.0, fyck=500.0, eut=0.05, futk=540.0,
                  gamma_y=1.15, gamma_u=1.25, gamma_E=1.0, curve=1)
    fyd = 500.0 / 1.15
    fud = 540.0 / 1.25
    # Each ordinate is divided by its own partial factor.
    eps_y = fyd / ES
    assert s.stress(eps_y) == pytest.approx(fyd)
    assert s.stress(0.05) == pytest.approx(fud)
    # Between yield and rupture the stress interpolates linearly between the two
    # design ordinates (here fud < fyd, so the branch decreases).
    mid = 0.5 * (eps_y + 0.05)
    assert s.stress(mid) == pytest.approx(0.5 * (fyd + fud), rel=1e-6)


def test_mild_type1_compression_plateau_no_hardening():
    s = MildSteel(fytk=500.0, fyck=500.0, eut=0.05, futk=540.0,
                  gamma_y=1.0, gamma_u=1.0, gamma_E=1.0, curve=1)
    # Deep compression stays at the (negative) yield, no hardening.
    assert s.stress(-0.04) == pytest.approx(-500.0)


def test_mild_type1_ruptures_beyond_eut():
    s = MildSteel(fytk=500.0, fyck=500.0, eut=0.05, futk=540.0,
                  gamma_y=1.0, gamma_u=1.0, gamma_E=1.0, curve=1)
    assert s.stress(0.05) == pytest.approx(540.0)  # rupture stress at eut
    assert s.stress(0.0500001) == 0.0              # fractured just beyond eut
    assert s.stress(0.2) == 0.0
    # Compression is unaffected by the tensile rupture limit.
    assert s.stress(-0.2) == pytest.approx(-500.0)


# ---------------------------------------------------------------------------
# Prestressing steel
# ---------------------------------------------------------------------------


def test_prestress_zero_in_compression_and_beyond_rupture():
    p = Prestress(curve=1, IS=0.006, gamma_y=1.0)
    assert p.stress(0.0) == 0.0
    assert p.stress(-0.005) == 0.0          # tendon takes no compression
    assert p.stress(EPS_P_RES + 1e-6) == 0.0  # fractured beyond 3.5 %


def test_prestress_builtin_rupture_strain_ignores_eut_field():
    # Built-in curves always rupture at EPS_P_RES regardless of any eut field,
    # so the effective rupture strain (used by the solver bracket) matches.
    p = Prestress(curve=1, IS=0.0, eut=0.10, gamma_y=1.0)
    assert p.rupture_strain == EPS_P_RES
    assert p.stress(EPS_P_RES + 1e-6) == 0.0   # ruptured despite eut=0.10
    # A custom curve does use its eut.
    q = Prestress(curve=6, IS=0.0, fytk=1550.0, futk=1770.0, eut=0.04, gamma_y=1.0)
    assert q.rupture_strain == 0.04


@pytest.mark.parametrize(
    "curve, e_pct, expected",
    [
        # Breakpoints read from the published built-in curves.
        (1, 0.6, 1200.0), (1, 1.0, 1600.0), (1, 1.75, 1645.0), (1, 3.5, 1645.0),
        # At e = 1.0 % the curve is on the plateau branch (the published labels);
        # types 2 and 4 have a small step from the cubic branch there.
        (2, 1.0, 1548.0), (2, 3.5, 1763.0),
        (3, 1.0, 1558.0), (3, 3.5, 1770.5),
        (4, 1.0, 1508.0), (4, 3.5, 1770.5),
        (5, 1.0, 1505.0), (5, 3.5, 1770.0),
    ],
)
def test_prestress_builtin_curve_breakpoints(curve, e_pct, expected):
    p = Prestress(curve=curve, IS=0.0, gamma_y=1.0)
    assert p.stress(e_pct / 100.0, design=False) == pytest.approx(expected, abs=1.0)


def test_prestress_builtin_continuity_at_segment_joins():
    # The polynomial segments must meet (curve 1 at 0.6 % and 1.0 %).
    p = Prestress(curve=1, IS=0.0, gamma_y=1.0)
    for e in (0.006, 0.010, 0.0175):
        below = p.stress(e - 1e-7, design=False)
        above = p.stress(e + 1e-7, design=False)
        assert below == pytest.approx(above, abs=0.5)


def test_prestress_builtin_design_scales_by_gamma_y():
    p = Prestress(curve=1, IS=0.0, gamma_y=1.12)
    assert p.stress(0.01, design=True) == pytest.approx(1600.0 / 1.12, abs=1.0)


def test_prestress_type6_bilinear_with_hardening():
    p = Prestress(curve=6, IS=0.0059, fytk=1550.0, eut=0.035, futk=1770.0,
                  gamma_y=1.0, gamma_u=1.0, gamma_E=1.0)
    eps_y = 1550.0 / ES
    assert p.stress(0.5 * eps_y) == pytest.approx(ES * 0.5 * eps_y)  # elastic
    assert p.stress(eps_y) == pytest.approx(1550.0)                  # yield
    assert p.stress(0.035) == pytest.approx(1770.0)                  # rupture stress
    assert p.stress(0.036) == 0.0                                    # fractured
    assert p.stress(-0.01) == 0.0                                    # no compression


def test_prestress_type6_design_factors():
    p = Prestress(curve=6, IS=0.0, fytk=1550.0, eut=0.035, futk=1770.0,
                  gamma_y=1.12, gamma_u=1.12, gamma_E=0.97)
    assert p.stress(0.035, design=True) == pytest.approx(1770.0 / 1.12, abs=1.0)


def test_prestress_invalid_curve_rejected():
    with pytest.raises(ValueError):
        Prestress(curve=8)
    with pytest.raises(ValueError):
        Prestress(curve=6, fytk=0.0, futk=0.0)


# ---------------------------------------------------------------------------
# Two-yield-point laws: mild steel type 3 and prestress type 7
# ---------------------------------------------------------------------------


def mild3():
    return MildSteel(fytk=550.0, fyck=550.0, eut=0.05, futk=620.0, curve=3,
                     k=0.9, ey0t=0.02, ey0c=0.025,
                     gamma_y=1.0, gamma_u=1.0, gamma_E=1.0)


def test_mild_type3_tension_breakpoints():
    s = mild3()
    e1 = 0.9 * 550.0 / ES          # first yield strain
    e2 = 0.02 + 550.0 / ES         # second yield strain (plastic ey0t + elastic)
    assert s.stress(0.5 * e1) == pytest.approx(ES * 0.5 * e1)   # elastic
    assert s.stress(e1) == pytest.approx(0.9 * 550.0)           # 1st yield
    assert s.stress(e2) == pytest.approx(550.0)                 # 2nd yield
    assert s.stress(0.05) == pytest.approx(620.0)               # rupture stress
    assert s.stress(0.051) == 0.0                               # fractured


def test_mild_type3_tension_segments_continuous():
    s = mild3()
    for e in (0.9 * 550.0 / ES, 0.02 + 550.0 / ES):
        assert s.stress(e - 1e-7) == pytest.approx(s.stress(e + 1e-7), abs=0.1)


def test_mild_type3_compression_mirror():
    s = mild3()
    assert s.stress(-0.001) == pytest.approx(-ES * 0.001)  # elastic
    assert s.stress(-0.025) == pytest.approx(-550.0)       # 2nd yield at ey0c


def test_mild_type3_design_scaling():
    s = MildSteel(fytk=550.0, fyck=550.0, eut=0.05, futk=620.0, curve=3,
                  k=0.9, ey0t=0.02, ey0c=0.025,
                  gamma_y=1.15, gamma_u=1.25, gamma_E=1.0)
    e2 = 0.02 + (550.0 / 1.15) / ES
    assert s.stress(e2) == pytest.approx(550.0 / 1.15)
    assert s.stress(0.05) == pytest.approx(620.0 / 1.25)


def test_mild_type3_requires_futk():
    with pytest.raises(ValueError):
        MildSteel(fytk=550.0, fyck=550.0, curve=3)


def test_prestress_type7_trilinear_tension_only():
    p = Prestress(curve=7, IS=0.006, fytk=1600.0, eut=0.035, futk=1860.0,
                  k=0.9, ey0t=0.01, gamma_y=1.0, gamma_u=1.0, gamma_E=1.0)
    e1 = 0.9 * 1600.0 / ES
    e2 = 0.01 + 1600.0 / ES
    assert p.stress(e1, design=False) == pytest.approx(0.9 * 1600.0)
    assert p.stress(e2, design=False) == pytest.approx(1600.0)
    assert p.stress(0.035, design=False) == pytest.approx(1860.0)
    assert p.stress(0.04) == 0.0       # fractured
    assert p.stress(-0.01) == 0.0      # no compression


def test_prestress_type7_design_and_validation():
    p = Prestress(curve=7, IS=0.0, fytk=1600.0, eut=0.035, futk=1860.0,
                  k=0.9, ey0t=0.01, gamma_y=1.12, gamma_u=1.12)
    assert p.stress(0.035, design=True) == pytest.approx(1860.0 / 1.12, abs=1.0)
    with pytest.raises(ValueError):
        Prestress(curve=7, fytk=0.0, futk=0.0)
