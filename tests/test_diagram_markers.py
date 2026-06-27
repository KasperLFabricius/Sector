"""Tests for the stress-strain diagram markers (points of interest).

Each marker is a point ``(strain, stress, eps_key, sigma_key)``.
"""

from __future__ import annotations

import pytest

from sector.materials import EPS_CU, EPS_C_PEAK, ES, Concrete, MildSteel, Prestress


def test_concrete_markers_are_points():
    c = Concrete(fck=35.0, gamma_c=1.5, curve=2)
    pts = c.diagram_markers(design=True)
    fcd = -35.0 / 1.5
    s, sig, ek, sk = pts[0]
    assert (s, ek, sk) == (-EPS_C_PEAK, "eps_c2", "fcd")
    assert sig == pytest.approx(fcd)
    s, sig, ek, sk = pts[1]
    assert (s, ek, sk) == (-EPS_CU, "eps_cu2", None)
    assert c.diagram_markers(design=False)[0][3] == "fck"


def test_mild_curve2_has_yield_ultimate_and_compression():
    s = MildSteel(fytk=500.0, fyck=500.0, eut=0.05, gamma_y=1.15, curve=2)
    pts = s.diagram_markers(design=True)
    fyd = 500.0 / 1.15
    assert pts[0] == (pytest.approx(500.0 / ES), pytest.approx(fyd), "eps_yd", "fyd")
    assert pts[1] == (pytest.approx(0.05), pytest.approx(fyd), "eps_ud", "fud")
    # Compression yield mirrors the tension yield (symmetric fyck = fytk).
    assert pts[2] == (pytest.approx(-500.0 / ES), pytest.approx(-fyd),
                      "eps_yd", "fyd")


def test_mild_curve1_ec_yield_and_compression():
    s = MildSteel(fytk=500.0, fyck=500.0, futk=500.0, eut=1.0, gamma_y=1.15,
                  gamma_u=1.15, gamma_E=1.0, curve=1)
    yld, ult, comp = s.diagram_markers(design=True)
    fyd = 500.0 / 1.15
    assert yld == (pytest.approx(fyd / ES), pytest.approx(fyd), "eps_yd", "fyd")
    assert ult[1] == pytest.approx(fyd)            # futk = fytk -> f_ud == f_yd
    assert comp[1] == pytest.approx(-fyd)          # compression yield


def test_mild_curve3_tension_and_compression_yields():
    s = MildSteel(fytk=550.0, fyck=550.0, futk=600.0, eut=0.05, gamma_y=1.0,
                  gamma_u=1.0, gamma_E=1.0, k=0.9, ey0t=0.002, ey0c=0.005, curve=3)
    pts = s.diagram_markers(design=True)
    keys = [(ek, sk) for _, _, ek, sk in pts]
    assert keys == [("eps_y1", "f1"), ("eps_y2", "f2"), ("eps_ud", "fud"),
                    ("eps_y1", "f1"), ("eps_y2", "f2")]
    # The two compression yields are at negative strain and stress.
    assert pts[3][0] < 0 and pts[3][1] == pytest.approx(-0.9 * 550.0)
    assert pts[4] == (pytest.approx(-0.005), pytest.approx(-550.0), "eps_y2", "f2")


def test_prestress_proof_point_lies_on_the_curve():
    # The fpd marker must sit on the actual law for both user-defined curves.
    # Curve 6 (bilinear) reaches fpd at the end of the elastic branch...
    p6 = Prestress(curve=6, IS=0.0, fytk=1600.0, futk=1860.0, eut=0.035,
                   gamma_y=1.15, gamma_u=1.15, gamma_E=1.0)
    eps_pd, fpd, ek, sk = p6.diagram_markers(design=True)[0]
    assert (ek, sk) == ("eps_pd", "fpd")
    assert eps_pd == pytest.approx(fpd / ES)
    assert p6.stress(eps_pd, design=True) == pytest.approx(fpd)

    # ...curve 7 (two yield) only reaches fpd after the plastic strain ey0t.
    p7 = Prestress(curve=7, IS=0.0, fytk=1600.0, futk=1860.0, eut=0.035,
                   k=0.9, ey0t=0.002, gamma_y=1.15, gamma_u=1.15, gamma_E=1.0)
    eps_pd, fpd, _, _ = p7.diagram_markers(design=True)[0]
    assert eps_pd == pytest.approx(0.002 + fpd / ES)
    assert p7.stress(eps_pd, design=True) == pytest.approx(fpd)


def test_elastic_slope_reflects_partial_factor():
    # Curves 1/3 factor the modulus with gamma_E; curve 2 ties it to gamma_y.
    s1 = MildSteel(fytk=500.0, fyck=500.0, futk=550.0, eut=0.05, gamma_y=1.15,
                   gamma_u=1.15, gamma_E=1.05, curve=1)
    assert s1.elastic_slope(design=True) == pytest.approx(ES / 1.05)
    assert s1.elastic_slope(design=False) == pytest.approx(ES)
    s2 = MildSteel(fytk=500.0, fyck=500.0, gamma_y=1.2, curve=2)
    assert s2.elastic_slope(design=True) == pytest.approx(ES / 1.2)
