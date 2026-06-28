"""Tests for the design-code material presets.

The expected values are taken from the codes themselves: EN 1992-1-1:2005
(Table 2.1N, 3.1.6, 3.1.7), the DK NA:2024 (Table 2.1Na, 3.2.7(2)) and
EN 1992-1-1:2023 (Table 4.3, 5.1.6, 8.1.2).
"""

from __future__ import annotations

import pytest

from sector import codes
from sector.materials import Concrete, EPS_C_PEAK, ES, MildSteel


def test_registry_and_tables():
    assert list(codes.CODES) == [
        "EN 1992-1-1:2005",
        "DS/EN 1992-1-1:2005 + DK NA:2024",
        "DS/EN 1992-1-1:2023",
    ]
    assert codes.CONCRETE_CLASSES["C30/37"] == pytest.approx(30.0)
    assert codes.CONCRETE_CLASSES["C50/60"] == pytest.approx(50.0)
    assert codes.STEEL_GRADES["B500"] == pytest.approx(500.0)
    # Only normal-strength classes are offered for now.
    assert max(codes.CONCRETE_CLASSES.values()) == pytest.approx(50.0)


def test_ec2_2005_factors_and_fcd():
    code = codes.CODES["EN 1992-1-1:2005"]
    assert (code.gamma_c, code.gamma_s, code.alpha_cc) == (1.5, 1.15, 1.0)
    # fcd = alpha_cc * fck / gamma_c.
    assert code.concrete(35.0).fcd == pytest.approx(35.0 / 1.5)
    # The preset reproduces the verified concrete law exactly (alpha_cc = 1).
    ref = Concrete(fck=30.0, gamma_c=1.5, curve=2)
    c = code.concrete(30.0)
    for e in (-EPS_C_PEAK, -0.001, -0.003):
        assert c.stress(e, design=True) == pytest.approx(ref.stress(e, design=True))


def test_table_3_1_strain_limits():
    # Up to C50/60 the strain limits and exponent are constant.
    assert codes.eps_c2(30.0) == pytest.approx(0.002)
    assert codes.eps_cu2(30.0) == pytest.approx(0.0035)
    assert codes.n_exponent(30.0) == pytest.approx(2.0)
    assert codes.eps_c2(50.0) == pytest.approx(0.002)
    assert codes.eps_cu2(50.0) == pytest.approx(0.0035)
    assert codes.n_exponent(50.0) == pytest.approx(2.0)
    # Above C50/60 they are strength-dependent (EC2 Table 3.1; C70 ~ 2.4/2.7/1.45).
    assert codes.eps_c2(70.0) == pytest.approx(0.0024158, abs=1e-6)
    assert codes.eps_cu2(70.0) == pytest.approx(0.002656, abs=1e-6)
    assert codes.n_exponent(70.0) == pytest.approx(1.43744, abs=1e-5)


def test_code_concrete_above_c50_is_strength_dependent():
    code = codes.CODES["EN 1992-1-1:2005"]
    c = code.concrete(70.0)
    assert c.eps_c2 == pytest.approx(codes.eps_c2(70.0))
    assert c.eps_cu2 == pytest.approx(codes.eps_cu2(70.0))
    assert c.n == pytest.approx(codes.n_exponent(70.0))
    # A normal-strength class still gets the verified default law.
    assert code.concrete(30.0).eps_cu2 == pytest.approx(0.0035)


def test_ec2_2023_keeps_constant_concrete_strains():
    # The 2023 edition keeps the ultimate parabola strains constant for all classes
    # (only eta_cc changes); a high grade must not get the Table 3.1 values.
    c = codes.CODES["DS/EN 1992-1-1:2023"].concrete(70.0)
    assert c.eps_c2 == pytest.approx(0.002)
    assert c.eps_cu2 == pytest.approx(0.0035)
    assert c.n == pytest.approx(2.0)


def test_dk_na_2024_partial_factors():
    code = codes.CODES["DS/EN 1992-1-1:2005 + DK NA:2024"]
    # In-situ reinforced concrete, normal control class.
    assert (code.gamma_c, code.gamma_s, code.alpha_cc) == (1.45, 1.20, 1.0)
    assert code.concrete(35.0).fcd == pytest.approx(35.0 / 1.45)
    assert code.steel(500.0).stress(0.02, design=True) == pytest.approx(500.0 / 1.20)


def test_ec2_2023_eta_cc_is_strength_dependent():
    code = codes.CODES["DS/EN 1992-1-1:2023"]
    assert (code.gamma_c, code.gamma_s) == (1.5, 1.15)
    # eta_cc = (40/fck)^(1/3), capped at 1.0; k_tc = 1.0.
    assert code.concrete_factor(40.0) == pytest.approx(1.0)        # fck = ref
    assert code.concrete_factor(20.0) == pytest.approx(1.0)        # capped at 1.0
    assert code.concrete_factor(50.0) == pytest.approx((40.0 / 50.0) ** (1.0 / 3.0))
    # The reduction flows through to fcd.
    c = code.concrete(50.0)
    assert c.fcd == pytest.approx((40.0 / 50.0) ** (1.0 / 3.0) * 50.0 / 1.5)


def test_all_codes_use_perfectly_plastic_steel_without_strain_limit():
    # Option (b): horizontal branch, no strain limit (DK NA mandates this).
    for code in codes.CODES.values():
        s = code.steel(500.0)
        assert isinstance(s, MildSteel)
        assert s.eut >= 1.0  # effectively unlimited
        fyd = 500.0 / code.gamma_s
        assert s.stress(0.02, design=True) == pytest.approx(fyd)
        assert s.stress(-0.02, design=True) == pytest.approx(-fyd)


def test_ec2_steel_keeps_the_modulus_unfactored():
    # EC2 reduces the yield stress to fyd but keeps Es on the elastic branch;
    # the preset must not factor the modulus by gamma_s (Codex review).
    code = codes.CODES["EN 1992-1-1:2005"]
    s = code.steel(500.0)
    fyd = 500.0 / 1.15
    eps = 0.0005  # below the design yield strain fyd/Es, so still elastic
    assert eps < fyd / ES
    # Elastic stress uses the full modulus Es, not the factored Es/gamma_s.
    assert s.stress(eps, design=True) == pytest.approx(ES * eps)
    assert s.stress(eps, design=True) != pytest.approx(ES / 1.15 * eps)
    # Tension and compression both still yield at fyd.
    assert s.stress(0.02, design=True) == pytest.approx(fyd)
    assert s.stress(-0.02, design=True) == pytest.approx(-fyd)
