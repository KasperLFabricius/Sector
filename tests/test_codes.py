"""Tests for the design-code material presets."""

from __future__ import annotations

import pytest

from sector import codes
from sector.materials import Concrete, EPS_C_PEAK, MildSteel


def test_registry_and_tables_are_sane():
    assert "EN 1992-1-1:2005" in codes.CODES
    # Classes map to their cylinder strength; grades to their yield strength.
    assert codes.CONCRETE_CLASSES["C30/37"] == pytest.approx(30.0)
    assert codes.CONCRETE_CLASSES["C50/60"] == pytest.approx(50.0)
    assert codes.STEEL_GRADES["B500"] == pytest.approx(500.0)
    # Only normal-strength classes are offered for now.
    assert max(codes.CONCRETE_CLASSES.values()) == pytest.approx(50.0)


def test_ec2_2005_factors():
    code = codes.CODES["EN 1992-1-1:2005"]
    assert (code.gamma_c, code.gamma_s, code.alpha_cc) == (1.5, 1.15, 1.0)


def test_ec2_2005_concrete_matches_the_verified_law():
    code = codes.CODES["EN 1992-1-1:2005"]
    c = code.concrete(30.0)
    # alpha_cc = 1.0, so the preset reproduces the manual concrete exactly.
    assert isinstance(c, Concrete)
    assert c.curve == 2
    assert c.fcd == pytest.approx(30.0 / 1.5)
    ref = Concrete(fck=30.0, gamma_c=1.5, curve=2)
    for e in (-EPS_C_PEAK, -0.001, -0.003):
        assert c.stress(e, design=True) == pytest.approx(ref.stress(e, design=True))


def test_ec2_2005_steel_is_perfectly_plastic_with_strain_limit():
    code = codes.CODES["EN 1992-1-1:2005"]
    s = code.steel(500.0)
    assert isinstance(s, MildSteel)
    assert s.curve == 2
    assert s.eut == pytest.approx(0.045)
    # Design yield at fyk / gamma_s, both senses.
    assert s.stress(0.02, design=True) == pytest.approx(500.0 / 1.15)
    assert s.stress(-0.02, design=True) == pytest.approx(-500.0 / 1.15)
