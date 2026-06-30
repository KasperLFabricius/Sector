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


def test_mild_curve2_labels_inputs():
    s = MildSteel(fytk=500.0, fyck=500.0, eut=0.05, gamma_y=1.15, curve=2)
    pts = s.diagram_markers(design=True)
    fyd = 500.0 / 1.15
    assert pts[0] == (pytest.approx(500.0 / ES), pytest.approx(fyd), None, "fytk")
    assert pts[1] == (pytest.approx(0.05), pytest.approx(fyd), "eut", "fytk")
    assert pts[2] == (pytest.approx(-500.0 / ES), pytest.approx(-fyd), None, "fyck")


def test_mild_curve1_labels_inputs():
    s = MildSteel(fytk=500.0, fyck=500.0, futk=500.0, eut=1.0, gamma_y=1.15,
                  gamma_u=1.15, gamma_E=1.0, curve=1)
    # The last marker is the symmetric compression rupture at -eut (appended by
    # diagram_markers); the first three are the yield, tension rupture and comp yield.
    yld, ult, comp, comp_ult = s.diagram_markers(design=True)
    fyd = 500.0 / 1.15
    assert yld == (pytest.approx(fyd / ES), pytest.approx(fyd), None, "fytk")
    assert ult[2:] == ("eut", "futk") and ult[1] == pytest.approx(fyd)
    assert comp[2:] == (None, "fyck") and comp[1] == pytest.approx(-fyd)
    # Compression rupture at -eut (futk = fytk here, so the stress is -fyd).
    assert comp_ult[0] == pytest.approx(-1.0) and comp_ult[2] == "eut"
    assert comp_ult[1] == pytest.approx(-fyd)


def test_mild_curve3_labels_inputs_and_independent_fyck():
    s = MildSteel(fytk=550.0, fyck=400.0, futk=600.0, eut=0.05, gamma_y=1.0,
                  gamma_u=1.0, gamma_E=1.0, k=0.9, ey0t=0.002, ey0c=0.005, curve=3)
    pts = s.diagram_markers(design=True)
    skeys = {sk for *_, sk in pts}
    ekeys = {ek for _, _, ek, _ in pts}
    assert {"fytk", "futk", "fyck", "k_fytk", "k_fyck"} <= skeys
    assert {"ey0t", "eut", "ey0c"} <= ekeys
    # The compression yield uses fyck (= -400), independent of fytk.
    comp = [sig for _, sig, _, sk in pts if sk == "fyck"]
    assert any(sig == pytest.approx(-400.0) for sig in comp)
    # No derived/design labels.
    assert not ({"f1", "f2", "fud", "fyd"} & skeys)


def test_prestress_proof_point_lies_on_the_curve():
    # Curve 6 (bilinear) reaches fp0.1k at the end of the elastic branch...
    p6 = Prestress(curve=6, IS=0.0, fytk=1600.0, futk=1860.0, eut=0.035,
                   gamma_y=1.15, gamma_u=1.15, gamma_E=1.0)
    proof = [(s, sig) for s, sig, ek, sk in p6.diagram_markers(design=True)
             if sk == "fp01k"][0]
    assert proof[0] == pytest.approx(proof[1] / ES)
    assert p6.stress(proof[0], design=True) == pytest.approx(proof[1])

    # ...curve 7 reaches fp0.1k only after the plastic strain ey0t.
    p7 = Prestress(curve=7, IS=0.0, fytk=1600.0, futk=1860.0, eut=0.035,
                   k=0.9, ey0t=0.002, gamma_y=1.15, gamma_u=1.15, gamma_E=1.0)
    proof7 = [(s, sig) for s, sig, ek, sk in p7.diagram_markers(design=True)
              if sk == "fp01k"][0]
    assert proof7[0] == pytest.approx(0.002 + proof7[1] / ES)
    assert p7.stress(proof7[0], design=True) == pytest.approx(proof7[1])


def test_elastic_slope_reflects_partial_factor():
    # Curves 1/3 factor the modulus with gamma_E; curve 2 ties it to gamma_y.
    s1 = MildSteel(fytk=500.0, fyck=500.0, futk=550.0, eut=0.05, gamma_y=1.15,
                   gamma_u=1.15, gamma_E=1.05, curve=1)
    assert s1.elastic_slope(design=True) == pytest.approx(ES / 1.05)
    assert s1.elastic_slope(design=False) == pytest.approx(ES)
    s2 = MildSteel(fytk=500.0, fyck=500.0, gamma_y=1.2, curve=2)
    assert s2.elastic_slope(design=True) == pytest.approx(ES / 1.2)
