"""Tests for the Material Parameters presets and builders."""

from __future__ import annotations

import pytest

from sector import codes, material_presets as mp
from sector.materials import Concrete, MildSteel


def test_concrete_presets_cover_legacy_and_eurocodes():
    labels = list(mp.CONCRETE_PRESETS)
    assert "Curve 1 (cubic)" in labels
    assert "Curve 2 (parabola-rectangle)" in labels
    for code_label in codes.CODES:
        assert code_label in labels


def test_mild_presets_cover_legacy_and_eurocodes():
    labels = list(mp.MILD_PRESETS)
    assert "Curve 2 (elastic-perfectly-plastic)" in labels
    for code_label in codes.CODES:
        assert code_label in labels


def test_concrete_eurocode_presets_match_codes():
    for label, code in codes.CODES.items():
        p = mp.CONCRETE_PRESETS[label]
        c = mp.build_concrete(**p)
        assert isinstance(c, Concrete)
        assert c.gamma_c == pytest.approx(code.gamma_c)
        # The preset reproduces the code's design strength for the default class.
        assert c.fcd == pytest.approx(code.concrete(p["fck"]).fcd)


def test_mild_eurocode_presets_have_unfactored_modulus():
    # EC2 presets use curve 1 with gamma_E = 1 (un-factored Es) and gamma_s yield.
    for label, code in codes.CODES.items():
        p = mp.MILD_PRESETS[label]
        assert p["curve"] == 1
        assert p["gamma_E"] == pytest.approx(1.0)
        assert p["gamma_y"] == pytest.approx(code.gamma_s)
        s = mp.build_mild(**p)
        assert isinstance(s, MildSteel)
        assert s.stress(0.02, design=True) == pytest.approx(p["fytk"] / code.gamma_s)


def test_build_mild_uses_only_fields_for_the_curve():
    # Curve 2 ignores the hardening/second-yield fields even if supplied.
    s = mp.build_mild(curve=2, fytk=500.0, fyck=500.0, eut=0.05, gamma_y=1.15,
                      futk=999.0, k=0.5, ey0t=0.01)
    assert s.curve == 2
    assert s.futk == 0.0  # not passed through for curve 2


def test_every_preset_builds_a_valid_material():
    for p in mp.CONCRETE_PRESETS.values():
        assert mp.build_concrete(**p).fcd > 0
    for p in mp.MILD_PRESETS.values():
        s = mp.build_mild(**p)
        assert s.stress(0.02, design=True) > 0


def test_field_metadata_matches_fields():
    for f in mp.CONCRETE_FIELDS:
        assert f in mp.CONCRETE_FIELD_META
    for fields in mp.MILD_FIELDS_BY_CURVE.values():
        for f in fields:
            assert f in mp.MILD_FIELD_META
