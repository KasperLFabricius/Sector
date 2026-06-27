"""Tests for the Material Parameters presets and builders."""

from __future__ import annotations

import pytest

from sector import codes, material_presets as mp
from sector.materials import Concrete, ES, MildSteel


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
    # EC2 presets build the general law (curve 3) reduced to a flat design
    # diagram: gamma_E = 1 (un-factored Es) and the yield held flat to fyd.
    for label, code in codes.CODES.items():
        p = mp.MILD_PRESETS[label]
        assert p["curve"] == 3
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


def test_strength_dependent_alpha_cc_tracks_fck_for_2023():
    label = "DS/EN 1992-1-1:2023"
    assert mp.strength_dependent_alpha_cc(label, 40.0) == pytest.approx(1.0)
    # C50/60: eta_cc = (40/50)^(1/3) ~ 0.928 (Codex review).
    assert mp.strength_dependent_alpha_cc(label, 50.0) == pytest.approx(
        round((40.0 / 50.0) ** (1.0 / 3.0), 4))
    # Constant-alpha_cc editions and legacy curves are not strength-dependent.
    assert mp.strength_dependent_alpha_cc("EN 1992-1-1:2005", 50.0) is None
    assert mp.strength_dependent_alpha_cc("Curve 2 (parabola-rectangle)", 50.0) is None


def test_curve3_preset_second_yield_is_continuous():
    # The default Curve 3 preset must place the second yield beyond first yield,
    # so compression follows the second-yield branch rather than jumping into
    # hardening (Codex review).
    p = mp.MILD_PRESETS["Curve 3 (two yield points)"]
    s = mp.build_mild(**p)
    f1 = p["k"] * p["fytk"]          # first yield stress (gamma = 1)
    f2 = p["fytk"]                   # second yield stress
    e1 = f1 / s.Es                   # first compression yield strain (fraction)
    assert s.ey0c > e1               # built material's ey0c (converted to fraction)
    sig = -s.stress(-(e1 + 1.0e-4), design=False)  # compression magnitude
    assert f1 <= sig < f1 + 0.2 * (f2 - f1)


def test_all_mild_presets_use_the_general_law():
    # Every mild preset builds curve 3 so every field is live on the diagram.
    for p in mp.MILD_PRESETS.values():
        assert p["curve"] == 3
        assert "Es" in p


def test_parametric_prestress_presets_use_the_general_law():
    # The user-defined and Eurocode prestress presets build curve 7; the built-in
    # characteristic curves stay fixed.
    assert mp.PRESTRESS_PRESETS["Curve 6 (bilinear)"]["curve"] == 7
    assert mp.PRESTRESS_PRESETS["Curve 7 (two yield)"]["curve"] == 7
    for label in codes.CODES:
        assert mp.PRESTRESS_PRESETS[label]["curve"] == 7
    assert mp.PRESTRESS_PRESETS["Curve 1 (built-in)"]["curve"] == 1


def test_eurocode_prestress_presets_set_Ep_directly():
    # Ep is now the direct input (gamma_E = 1), 195/200 GPa by edition.
    for label, code in codes.CODES.items():
        p = mp.PRESTRESS_PRESETS[label]
        assert p["gamma_E"] == pytest.approx(1.0)
        expected = 200000.0 if code.key == "EC2-2023" else 195000.0
        assert p["Es"] == pytest.approx(expected)


def test_field_metadata_matches_fields():
    for f in mp.CONCRETE_FIELDS:
        assert f in mp.CONCRETE_FIELD_META
    for fields in mp.MILD_FIELDS_BY_CURVE.values():
        for f in fields:
            assert f in mp.MILD_FIELD_META
