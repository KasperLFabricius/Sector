"""Tests for the torsional resistance (EN 1992-1-1:2005 section 6.3).

Reference hand calculation: a 300 x 600 mm solid rectangle, C35, DK NA:2024, with a
closed phi10 stirrup at s = 150 mm (fywk = 500). The tube idealisation gives
A = 0.18 m2, u = 1.8 m, tef = 100 mm, Ak = 0.1 m2, uk = 1.4 m; at the optimum strut
cot(theta) = 1.751 the stirrups and the struts meet at TRd ~ 76.4 kN.m.
"""

from __future__ import annotations

import math

import pytest

from sector import codes, shear, torsion


def _rect(b, h):
    """Corner-origin rectangle b x h (metres)."""
    return [(0.0, 0.0), (b, 0.0), (b, h), (0.0, h)]


# -- tube idealisation ------------------------------------------------------

def test_tube_properties_solid_rectangle():
    t = torsion.tube_properties(_rect(0.3, 0.6), None)
    assert t["valid"]
    assert t["A"] == pytest.approx(0.18)
    assert t["u"] == pytest.approx(1.8)
    assert t["tef"] == pytest.approx(100.0)           # A/u = 0.1 m -> 100 mm
    assert t["Ak"] == pytest.approx(0.1)              # (0.3-0.1)(0.6-0.1)
    assert t["uk"] == pytest.approx(1.4)              # 2(0.2 + 0.5)
    assert not t["tef_capped"] and not t["tef_user"]


def test_tube_tef_override():
    t = torsion.tube_properties(_rect(0.3, 0.6), None, tef_override=80.0)
    assert t["tef"] == pytest.approx(80.0)
    assert t["tef_user"]
    # Centre-line offset by 40 mm -> (0.3-0.08)(0.6-0.08).
    assert t["Ak"] == pytest.approx((0.3 - 0.08) * (0.6 - 0.08))


def test_tube_hollow_caps_tef_at_the_wall():
    # A thin box: outer 0.6 x 0.6, a 0.4 x 0.4 void -> ~0.1 m walls. A/u = 0.36/2.4 =
    # 0.15 m, but the real wall is ~0.1 m, so tef is capped below the solid A/u value.
    outer = _rect(0.6, 0.6)
    hole = [(0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5)]
    t = torsion.tube_properties(outer, [hole])
    assert t["hollow"] and t["tef_capped"]
    assert t["tef"] < t["tef_auto"]
    assert t["tef"] == pytest.approx(100.0, abs=15.0)   # ~ the 100 mm wall


def test_offset_polygon_inward_square():
    ring = torsion.offset_polygon_inward([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0),
                                          (0.0, 1.0)], 0.1)
    from sector import geometry
    assert abs(geometry.signed_area(ring)) == pytest.approx(0.64)   # 0.8 x 0.8


# -- resistances (hand-calc anchor) -----------------------------------------

def _tube():
    return torsion.tube_properties(_rect(0.3, 0.6), None)


def test_torsion_nu_edition_dependent():
    assert codes.EC2_2005.torsion_nu(35.0) == pytest.approx(0.6 * (1 - 35.0 / 250.0))
    assert codes.EC2_2005_DKNA.torsion_nu(35.0) == pytest.approx(0.7 * (0.7 - 35.0 / 200.0))


def test_trd_s_and_trd_max_meet_at_the_optimum():
    code = codes.EC2_2005_DKNA
    t = _tube()
    fcd = code.concrete_factor(35.0) * 35.0 / code.gamma_c
    fywd = 500.0 / code.gamma_s
    nu = code.torsion_nu(35.0)
    asw_over_s = math.pi / 4 * 10.0 ** 2 / 150.0        # 1 closed phi10 leg / 150 mm
    # The torsion optimum reuses the shear crossover with a = (Asw/s)*fywd,
    # b = nu*alpha_cw*fcd*tef (tef in mm).
    a = asw_over_s * fywd
    b = nu * 1.0 * fcd * t["tef"]
    cot = shear.optimum_cot_theta(a, b, 1.0, 2.5)
    assert cot == pytest.approx(1.751, abs=1e-3)
    vs = torsion.trd_s(t["Ak"], fywd, asw_over_s, cot)
    vmax = torsion.trd_max(35.0, code, t["Ak"], t["tef"], 1.0, cot)
    assert vs == pytest.approx(76.4, abs=0.3)
    assert vmax == pytest.approx(76.4, abs=0.3)
    assert vs == pytest.approx(vmax, rel=1e-3)          # crossover


def test_trd_max_peaks_at_cot_one():
    code = codes.EC2_2005_DKNA
    t = _tube()
    peak = torsion.trd_max(35.0, code, t["Ak"], t["tef"], 1.0, 1.0)
    flatter = torsion.trd_max(35.0, code, t["Ak"], t["tef"], 1.0, 2.0)
    assert peak > flatter
    assert peak == pytest.approx(88.7, abs=0.5)


def test_trd_c_cracking_moment():
    code = codes.EC2_2005_DKNA
    t = _tube()
    fctm = codes.fctm(35.0)
    fctd = 0.7 * fctm / code.gamma_c                   # fctk,0.05 / gamma_c
    tc = torsion.trd_c(fctd, t["Ak"], t["tef"])
    assert tc == pytest.approx(2.0 * t["Ak"] * (t["tef"] / 1000.0) * fctd * 1000.0)
    assert tc == pytest.approx(31.0, abs=1.5)


def test_asl_required_longitudinal_steel():
    code = codes.EC2_2005_DKNA
    t = _tube()
    fyd = 500.0 / code.gamma_s
    asl = torsion.asl_required(50.0, t["uk"], t["Ak"], fyd, 1.751)
    assert asl == pytest.approx(1471.0, abs=5.0)


# -- app integration (AppTest) ----------------------------------------------

import pathlib  # noqa: E402
import sys  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
APP = str(ROOT / "app" / "sector_app.py")


def _fresh():
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(APP, default_timeout=90)


def test_app_torsion_produces_a_resistance():
    at = _fresh()
    at.run()
    at.checkbox(key="torsion_on").set_value(True).run()
    at.number_input(key="torsion_T").set_value(40.0).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    t = at.session_state["results"]["torsion"]
    assert t["valid"] and t["trd"] > 0.0
    assert t["trd"] == pytest.approx(min(t["trd_s"], t["trd_max"]))
    assert 1.0 <= t["cot"] <= 2.5
    assert t["util"] == pytest.approx(40.0 / t["trd"])
    assert t["asl_req"] > 0.0                       # torsion needs longitudinal steel


def test_app_torsion_view_renders():
    at = _fresh()
    at.run()
    at.checkbox(key="torsion_on").set_value(True).run()
    at.number_input(key="torsion_T").set_value(30.0).run()
    at.button(key="calculate").click().run()
    at.selectbox(key="view").set_value("Torsion").run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert any("Utilisation" in lbl for lbl in labels)
    assert any("TRd" in lbl for lbl in labels)


def test_app_combined_shear_torsion_interaction():
    # With both shear links and torsion on, the 6.29 crushing interaction appears.
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    at.number_input(key="shear_V").set_value(150.0).run()
    at.checkbox(key="torsion_on").set_value(True).run()
    at.number_input(key="torsion_T").set_value(40.0).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    inter = at.session_state["results"]["torsion"]["interaction"]
    assert inter["value"] == pytest.approx(
        inter["t_ed"] / inter["trd_max"] + inter["v_ed"] / inter["vrd_max"])
    assert inter["cot"] == pytest.approx(1.0)       # common crushing angle at 45 deg


def test_app_torsion_is_saved_and_restored():
    import project_io
    at = _fresh()
    at.run()
    at.checkbox(key="torsion_on").set_value(True).run()
    at.number_input(key="torsion_T").set_value(55.0).run()
    scalars = {k: at.session_state[k] for k in project_io.SCALAR_KEYS
               if k in at.session_state}
    assert scalars["torsion_on"] is True and scalars["torsion_T"] == 55.0
    at2 = _fresh()
    at2.run()
    at2.session_state["_pending_project"] = project_io.dump_project({}, scalars)
    at2.run()
    assert not at2.exception
    assert at2.session_state["torsion_on"] is True
    assert at2.session_state["torsion_T"] == 55.0
