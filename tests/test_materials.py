"""Tests for the plastic-analysis material laws, against the published curves."""

from __future__ import annotations

import pytest

from sector.materials import ES, EPS_CU, EPS_C_PEAK, Concrete, MildSteel


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
