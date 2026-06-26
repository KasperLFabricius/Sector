"""Tests for the stress-strain diagram markers (points of interest)."""

from __future__ import annotations

import pytest

from sector.materials import EPS_CU, EPS_C_PEAK, Concrete, MildSteel


def test_concrete_markers():
    c = Concrete(fck=35.0, gamma_c=1.5, curve=2)
    by_key = {k: (kind, v) for kind, v, k in c.diagram_markers(design=True)}
    assert set(by_key) == {"fcd", "eps_c2", "eps_cu2"}
    assert by_key["eps_c2"] == ("strain", -EPS_C_PEAK)
    assert by_key["eps_cu2"] == ("strain", -EPS_CU)
    assert by_key["fcd"][0] == "stress"
    assert by_key["fcd"][1] == pytest.approx(-35.0 / 1.5)
    # Characteristic markers report fck rather than fcd.
    assert {k for _, _, k in c.diagram_markers(design=False)} == {
        "fck", "eps_c2", "eps_cu2"}


def test_mild_curve2_markers():
    s = MildSteel(fytk=500.0, fyck=500.0, gamma_y=1.15, curve=2)
    by_key = {k: (kind, v) for kind, v, k in s.diagram_markers(design=True)}
    assert set(by_key) == {"eps_yd", "fyd"}
    assert by_key["fyd"][1] == pytest.approx(500.0 / 1.15)
    # Yield strain = fyd / (ES / gamma_y) = fytk / ES.
    assert by_key["eps_yd"][1] == pytest.approx(500.0 / 2.0e5)


def test_mild_curve1_omits_rupture_when_out_of_view():
    # No strain limit (large eut): the rupture marker is not shown.
    s = MildSteel(fytk=500.0, fyck=500.0, futk=500.0, eut=1.0, gamma_y=1.15,
                  gamma_u=1.15, gamma_E=1.0, curve=1)
    assert {k for _, _, k in s.diagram_markers()} == {"eps_yd", "fyd"}
    # A physical rupture strain is annotated.
    s2 = MildSteel(fytk=500.0, fyck=500.0, futk=550.0, eut=0.05, gamma_y=1.15,
                   gamma_u=1.15, gamma_E=1.0, curve=1)
    assert "eps_ud" in {k for _, _, k in s2.diagram_markers()}


def test_mild_curve3_marks_both_yields():
    s = MildSteel(fytk=550.0, fyck=550.0, futk=600.0, eut=0.05, gamma_y=1.0,
                  gamma_u=1.0, gamma_E=1.0, k=0.9, ey0t=0.002, ey0c=0.005, curve=3)
    by_key = {k: v for _, v, k in s.diagram_markers(design=True)}
    assert set(by_key) == {"eps_y1", "f1", "f2"}
    assert by_key["f1"] == pytest.approx(0.9 * 550.0)
    assert by_key["f2"] == pytest.approx(550.0)
