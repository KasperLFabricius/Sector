"""Tests for the stress-strain diagram markers (points of interest).

Each marker is a point ``(strain, stress, eps_key, sigma_key)``.
"""

from __future__ import annotations

import pytest

from sector.materials import EPS_CU, EPS_C_PEAK, ES, Concrete, MildSteel


def test_concrete_markers_are_points():
    c = Concrete(fck=35.0, gamma_c=1.5, curve=2)
    pts = c.diagram_markers(design=True)
    fcd = -35.0 / 1.5
    assert (-EPS_C_PEAK, pytest.approx(fcd), "eps_c2", "fcd") in [
        (s, pytest.approx(sig), ek, sk) for s, sig, ek, sk in [pts[0]]]
    # eps_cu2 sits at the same stress level, so it carries no separate stress key.
    s, sig, ek, sk = pts[1]
    assert (s, ek, sk) == (-EPS_CU, "eps_cu2", None)
    assert sig == pytest.approx(fcd)
    # Characteristic markers report fck.
    assert c.diagram_markers(design=False)[0][3] == "fck"


def test_mild_curve2_yield_and_ultimate_share_stress():
    s = MildSteel(fytk=500.0, fyck=500.0, eut=0.05, gamma_y=1.15, curve=2)
    pts = s.diagram_markers(design=True)
    fyd = 500.0 / 1.15
    assert pts[0] == (pytest.approx(500.0 / ES), pytest.approx(fyd), "eps_yd", "fyd")
    # Perfectly plastic: ultimate stress equals yield -> both labels at one level.
    assert pts[1] == (pytest.approx(0.05), pytest.approx(fyd), "eps_ud", "fud")


def test_mild_curve1_ec_has_unfactored_yield_strain():
    s = MildSteel(fytk=500.0, fyck=500.0, futk=500.0, eut=1.0, gamma_y=1.15,
                  gamma_u=1.15, gamma_E=1.0, curve=1)
    yld, ult = s.diagram_markers(design=True)
    fyd = 500.0 / 1.15
    assert yld == (pytest.approx(fyd / ES), pytest.approx(fyd), "eps_yd", "fyd")
    # futk = fytk and gamma_u = gamma_s, so f_ud coincides with f_yd.
    assert ult[1] == pytest.approx(fyd)


def test_mild_curve3_has_two_yields_and_ultimate():
    s = MildSteel(fytk=550.0, fyck=550.0, futk=600.0, eut=0.05, gamma_y=1.0,
                  gamma_u=1.0, gamma_E=1.0, k=0.9, ey0t=0.002, ey0c=0.005, curve=3)
    keys = [(ek, sk) for _, _, ek, sk in s.diagram_markers(design=True)]
    assert keys == [("eps_y1", "f1"), ("eps_y2", "f2"), ("eps_ud", "fud")]
    stresses = [sig for _, sig, _, _ in s.diagram_markers(design=True)]
    assert stresses == [pytest.approx(0.9 * 550.0), pytest.approx(550.0),
                        pytest.approx(600.0)]
