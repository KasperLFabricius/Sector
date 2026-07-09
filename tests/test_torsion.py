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
    # A thin box: outer 0.6 x 0.6, a 0.4 x 0.4 void -> 0.1 m walls. A/u = 0.36/2.4 =
    # 0.15 m, but the real wall is 0.1 m, so tef is capped to the actual wall.
    outer = _rect(0.6, 0.6)
    hole = [(0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5)]
    t = torsion.tube_properties(outer, [hole])
    assert t["hollow"] and t["tef_capped"]
    assert t["tef_auto"] == pytest.approx(150.0)
    assert t["tef"] == pytest.approx(100.0)             # the actual 100 mm wall


def test_tube_thin_box_wall_is_not_overestimated():
    # Codex P1: a 1.0 x 1.0 box with a centered 0.9 x 0.9 void has 50 mm walls; the
    # cap must be the real wall, not the ~63 mm the concrete-area/perimeter estimate
    # gave (which inflated TRd,max / TRd,c by ~20%).
    outer = _rect(1.0, 1.0)
    hole = [(0.05, 0.05), (0.95, 0.05), (0.95, 0.95), (0.05, 0.95)]
    t = torsion.tube_properties(outer, [hole])
    assert t["tef_auto"] == pytest.approx(250.0)        # A/u = 1.0/4.0
    assert t["tef"] == pytest.approx(50.0)              # the actual 50 mm wall


def test_tube_rejects_too_large_tef_override():
    # A tef larger than the section can support inverts the inward offset; it must be
    # rejected (not accepted via abs() as a spurious Ak), leaving an invalid tube.
    t = torsion.tube_properties(_rect(0.3, 0.6), None, tef_override=400.0)
    assert not t["valid"]
    assert t["Ak"] == 0.0


def test_tube_multi_cell_is_invalid():
    # Codex P2: two or more voids -> the single-tube idealisation does not model the
    # internal webs, so it is rejected rather than reporting an unconservative TRd.
    outer = _rect(1.0, 1.0)
    h1 = [(0.1, 0.1), (0.4, 0.1), (0.4, 0.9), (0.1, 0.9)]
    h2 = [(0.6, 0.1), (0.9, 0.1), (0.9, 0.9), (0.6, 0.9)]
    t = torsion.tube_properties(outer, [h1, h2])
    assert not t["valid"]
    assert "multi-cell" in (t.get("reason") or "")


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


def test_combined_vrdmax_uses_shear_method_not_torsion():
    # The combined VRd,max must follow the SHEAR method and lever arm, not the torsion
    # code / 0.9d. Changing only the torsion method moves TRd,max but leaves VRd,max.
    def inter(torsion_method):
        at = _fresh()
        at.run()
        at.checkbox(key="shear_on").set_value(True).run()
        at.checkbox(key="shear_links").set_value(True).run()
        at.number_input(key="shear_V").set_value(150.0).run()
        at.checkbox(key="torsion_on").set_value(True).run()
        at.number_input(key="torsion_T").set_value(40.0).run()
        at.selectbox(key="torsion_method").set_value(torsion_method).run()
        at.button(key="calculate").click().run()
        assert not at.exception
        return at.session_state["results"]["torsion"]["interaction"]

    a = inter(codes.EC2_2005_DKNA.label)
    b = inter(codes.EC2_2005.label)
    assert a["vrd_max"] == pytest.approx(b["vrd_max"])   # shear-driven, unchanged
    assert a["trd_max"] != pytest.approx(b["trd_max"])   # torsion-driven, changed


def test_app_torsion_only_axial_input_enabled():
    # Codex P2: in an Elastic-only torsion check the plastic axial input still drives
    # alpha_cw, so it must be enabled (not disabled) when only torsion is on, and a
    # compression axial force must raise TRd,max.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.checkbox(key="torsion_on").set_value(True).run()
    at.number_input(key="torsion_T").set_value(30.0).run()
    assert not at.number_input(key="pl_P").disabled
    at.button(key="calculate").click().run()
    base = at.session_state["results"]["torsion"]["trd_max"]
    at.number_input(key="pl_P").set_value(-1500.0).run()   # compression (N tension +)
    at.button(key="calculate").click().run()
    assert not at.exception
    t = at.session_state["results"]["torsion"]
    assert t["alpha_cw"] > 1.0                              # compression -> alpha_cw up
    assert t["trd_max"] > base


def test_app_torsion_multi_void_rejected():
    import pandas as pd
    at = _fresh()
    at.run()
    # two separate triangular voids in the default rectangle (blank-row separated)
    at.session_state["hole_base"] = pd.DataFrame({
        "x (mm)": [-100.0, -40.0, -70.0, None, 40.0, 100.0, 70.0],
        "y (mm)": [-50.0, -50.0, 50.0, None, -50.0, -50.0, 50.0]})
    at.checkbox(key="torsion_on").set_value(True).run()
    at.number_input(key="torsion_T").set_value(20.0).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    assert not at.session_state["results"]["torsion"]["valid"]
    at.selectbox(key="view").set_value("Torsion").run()
    assert any("multi-cell" in w.value for w in at.warning)


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
