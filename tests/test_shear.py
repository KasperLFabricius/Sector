"""Tests for the shear resistance without shear reinforcement (VRd,c).

The engine reproduces EN 1992-1-1:2005 sec. 6.2.2(1) with the DK NA:2024 v_min.
The reference hand calculation is a 300 x 600 mm rectangle, C35, DK NA:2024,
with Asl = 1473 mm2 (d = 550 mm, bw = 300 mm, N = 0): VRd,c ~ 103.4 kN.
"""

from __future__ import annotations

import math
import pathlib
import sys

import pytest

from sector import codes, shear

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))       # so `import sector_app` works standalone
APP = str(ROOT / "app" / "sector_app.py")


# -- design-code shear NDPs -------------------------------------------------

def test_shear_crd_c_over_gamma_and_k1():
    # CRd,c = 0.18/gamma_c; k1 = 0.15 in both 2005 editions (recommended, DK NA keeps).
    assert codes.EC2_2005.shear_crd_c_over_gamma() == pytest.approx(0.18 / 1.5)
    assert codes.EC2_2005_DKNA.shear_crd_c_over_gamma() == pytest.approx(0.18 / 1.45)
    assert codes.EC2_2005.shear_k1 == pytest.approx(0.15)
    assert codes.EC2_2005_DKNA.shear_k1 == pytest.approx(0.15)


def test_shear_vmin_recommended_vs_dk_na():
    # Recommended v_min = 0.035*k^1.5*sqrt(fck); the DK NA:2024 raises it to
    # (0.051/gamma_c)*k^1.5*sqrt(fck).
    k, fck = 1.6, 35.0
    assert codes.EC2_2005.shear_vmin(k, fck) == pytest.approx(
        0.035 * k ** 1.5 * math.sqrt(fck))
    assert codes.EC2_2005_DKNA.shear_vmin(k, fck) == pytest.approx(
        (0.051 / 1.45) * k ** 1.5 * math.sqrt(fck))
    # The DK NA value is higher than the recommended one for a normal grade.
    assert codes.EC2_2005_DKNA.shear_vmin(k, fck) > codes.EC2_2005.shear_vmin(k, fck)


# -- the resistance formula (hand-calc anchor) ------------------------------

def test_vrd_c_hand_calc_dk_na():
    code = codes.EC2_2005_DKNA
    res = shear.vrd_c(fck=35.0, code=code, bw_mm=300.0, d_mm=550.0,
                      asl_mm2=1473.0, n_ed_comp_kn=0.0, ac_m2=0.18)
    assert res["valid"]
    k = 1.0 + math.sqrt(200.0 / 550.0)
    rho = 1473.0 / (300.0 * 550.0)
    crd = 0.18 / 1.45
    assert res["k"] == pytest.approx(k)
    assert res["rho_l"] == pytest.approx(rho)
    assert res["crd_c"] == pytest.approx(crd)
    # Independent closed-form value (sigma_cp = 0), then the documented ~103.4 kN.
    basic = crd * k * (100.0 * rho * 35.0) ** (1.0 / 3.0)
    vmin = (0.051 / 1.45) * k ** 1.5 * math.sqrt(35.0)
    expect = max(basic, vmin) * 300.0 * 550.0 / 1000.0
    assert res["vrd_c"] == pytest.approx(expect)
    assert res["vrd_c"] == pytest.approx(103.4, abs=0.1)
    assert res["k1"] == pytest.approx(0.15)


def test_vrd_c_caps_rho_l_and_k():
    # rho_l is capped at 0.02 and k at 2.0.
    res = shear.vrd_c(35.0, codes.EC2_2005_DKNA, bw_mm=300.0, d_mm=120.0,
                      asl_mm2=1e6, n_ed_comp_kn=0.0, ac_m2=0.18)
    assert res["rho_l"] == pytest.approx(0.02)
    assert res["k"] == pytest.approx(2.0)             # 1 + sqrt(200/120) > 2 -> capped


def test_vrd_c_axial_compression_raises_and_is_capped():
    code = codes.EC2_2005_DKNA
    base = shear.vrd_c(35.0, code, 300.0, 550.0, 1473.0, 0.0, 0.18)
    comp = shear.vrd_c(35.0, code, 300.0, 550.0, 1473.0, 500.0, 0.18)
    assert comp["sigma_cp"] > 0.0                     # compression -> positive sigma_cp
    assert comp["vrd_c"] > base["vrd_c"]              # ...which raises VRd,c
    # sigma_cp is capped at 0.2*fcd for a very large axial force.
    huge = shear.vrd_c(35.0, code, 300.0, 550.0, 1473.0, 1e9, 0.18)
    assert huge["sigma_cp"] == pytest.approx(0.2 * huge["fcd"])


def test_vrd_c_floor_governs_at_low_reinforcement():
    code = codes.EC2_2005_DKNA
    res = shear.vrd_c(35.0, code, 300.0, 550.0, asl_mm2=50.0,
                      n_ed_comp_kn=0.0, ac_m2=0.18)
    assert res["v_floor"] >= res["v_basic"]           # the lower bound governs
    assert res["vrd_c"] == pytest.approx(res["v_floor"] * 300.0 * 550.0 / 1000.0)


def test_vrd_c_zero_depth_is_invalid():
    res = shear.vrd_c(35.0, codes.EC2_2005_DKNA, bw_mm=300.0, d_mm=0.0,
                      asl_mm2=1473.0, n_ed_comp_kn=0.0, ac_m2=0.18)
    assert not res["valid"]
    assert res["vrd_c"] == 0.0


# -- geometry derivation helpers --------------------------------------------

def test_min_web_width_rect_t_box():
    # Rectangle: constant width -> the section width.
    rect = [(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)]
    assert shear.min_web_width(rect, None, "x") == pytest.approx(300.0)
    # T-section: 0.3 m web below a 0.6 m flange; the minimum solid width is the web.
    tee = [(0.15, 0.0), (0.45, 0.0), (0.45, 0.45), (0.6, 0.45), (0.6, 0.6),
           (0.0, 0.6), (0.0, 0.45), (0.15, 0.45)]
    assert shear.min_web_width(tee, None, "x") == pytest.approx(300.0)
    # Box: 0.6 m square with a 0.2 m central void -> 0.4 m solid across the void band.
    box = [(0.0, 0.0), (0.6, 0.0), (0.6, 0.6), (0.0, 0.6)]
    hole = [(0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4)]
    assert shear.min_web_width(box, [hole], "x") == pytest.approx(400.0)


def test_min_web_width_catches_a_thin_void_between_grid_levels():
    # A 2 mm horizontal duct that falls between the old fixed sample levels must still
    # reduce the derived web width: the vertex-based sampling evaluates at the void's
    # own levels (Codex P1). 0.4 m wide section, a 0.2 m-wide duct -> 0.2 m web.
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    duct = [(-0.1, 0.105), (0.1, 0.105), (0.1, 0.107), (-0.1, 0.107)]
    assert shear.min_web_width(outer, [duct], "x") == pytest.approx(200.0)


def test_tension_reinforcement_and_effective_depth():
    outer = [(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)]
    bars = [(0.15, 0.05, 1473.0),     # bottom, tension side
            (0.15, 0.55, 600.0)]      # top, compression side
    centroid = 0.3
    asl, cg = shear.tension_reinforcement(bars, "x", tension_low=True,
                                          centroid_coord=centroid)
    assert asl == pytest.approx(1473.0)               # only the bottom bar counts
    assert cg == pytest.approx(0.05)
    d = shear.effective_depth(outer, "x", tension_low=True, tension_cg_coord=cg)
    assert d == pytest.approx(550.0)                  # (0.6 - 0.05) m -> 550 mm
    # No tension reinforcement on the chosen face -> zero area and no depth.
    asl0, cg0 = shear.tension_reinforcement(bars, "x", tension_low=False,
                                            centroid_coord=0.6)
    # (both bars below 0.6, tension_low=False keeps those above 0.6 -> none)
    assert asl0 == 0.0 and cg0 is None
    assert shear.effective_depth(outer, "x", False, None) == 0.0


def test_horizontal_shear_uses_the_x_coordinate():
    # Axis 'y' (horizontal shear) measures depth in x; the tension bar is on the left.
    outer = [(0.0, 0.0), (0.6, 0.0), (0.6, 0.3), (0.0, 0.3)]
    bars = [(0.05, 0.15, 1000.0), (0.55, 0.15, 1000.0)]
    asl, cg = shear.tension_reinforcement(bars, "y", tension_low=True,
                                          centroid_coord=0.3)
    assert asl == pytest.approx(1000.0) and cg == pytest.approx(0.05)
    d = shear.effective_depth(outer, "y", tension_low=True, tension_cg_coord=cg)
    assert d == pytest.approx(550.0)                  # (0.6 - 0.05) m -> 550 mm


# -- app helper: gross area / centroid --------------------------------------

def test_gross_area_centroid_rect_and_hole():
    from sector_app import _gross_area_centroid
    rect = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    a, cx, cy = _gross_area_centroid(rect, [])
    assert a == pytest.approx(0.24)                   # 0.4 x 0.6 m
    assert (cx, cy) == pytest.approx((0.0, 0.0))
    hole = [(-0.05, -0.05), (0.05, -0.05), (0.05, 0.05), (-0.05, 0.05)]
    a2, cx2, cy2 = _gross_area_centroid(rect, [hole])
    assert a2 == pytest.approx(0.24 - 0.01)           # void removed
    assert (cx2, cy2) == pytest.approx((0.0, 0.0))    # centred void keeps the centroid


# -- app integration (AppTest) ----------------------------------------------

def _fresh():
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(APP, default_timeout=90)


def test_app_shear_check_produces_a_resistance():
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.number_input(key="shear_V").set_value(100.0).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    sh = at.session_state["results"]["shear"]
    assert sh["res"]["vrd_c"] > 0.0
    # Default 400 x 600 mm section, bottom bars at y = -250 mm -> d = 550, bw = 400.
    assert sh["d"] == pytest.approx(550.0, abs=1.0)
    assert sh["bw"] == pytest.approx(400.0, abs=1.0)
    assert not sh["bw_user"]                           # auto width
    assert sh["util"] == pytest.approx(100.0 / sh["res"]["vrd_c"])


def test_app_shear_bw_override_is_used():
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.number_input(key="shear_bw").set_value(250.0).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    sh = at.session_state["results"]["shear"]
    assert sh["bw"] == pytest.approx(250.0)
    assert sh["bw_user"]


def test_app_shear_view_renders_and_shows_utilisation():
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.number_input(key="shear_V").set_value(80.0).run()
    at.button(key="calculate").click().run()
    at.selectbox(key="view").set_value("Shear").run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert any("Utilisation" in lbl for lbl in labels)
    assert any("VRd,c" in lbl or "Resistance" in lbl for lbl in labels)


def test_app_shear_axial_input_enabled_in_elastic_mode():
    # Codex P2: in Elastic-only mode the shear sigma_cp still uses the plastic axial
    # force, so that input must stay enabled when the shear check is on (else the user
    # cannot enter the ULS axial the result depends on). A compression axial (negative
    # N, tension-positive) must raise VRd,c through sigma_cp.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.checkbox(key="shear_on").set_value(True).run()
    assert not at.number_input(key="pl_P").disabled        # axial input available
    at.number_input(key="shear_V").set_value(50.0).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    base = at.session_state["results"]["shear"]["res"]["vrd_c"]
    at.number_input(key="pl_P").set_value(-400.0).run()    # compression (N tension +)
    at.button(key="calculate").click().run()
    assert not at.exception
    comp = at.session_state["results"]["shear"]["res"]
    assert comp["sigma_cp"] > 0.0                          # compression -> positive sigma_cp
    assert comp["vrd_c"] > base                            # ...raises VRd,c


def test_app_shear_is_saved_and_restored():
    # The shear inputs are persisted (SCALAR_KEYS); a project round trip keeps them.
    import project_io
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.number_input(key="shear_V").set_value(123.0).run()
    at.selectbox(key="shear_axis").set_value("Horizontal shear (bending about y)").run()
    scalars = {k: at.session_state[k] for k in project_io.SCALAR_KEYS
               if k in at.session_state}
    assert scalars["shear_on"] is True and scalars["shear_V"] == 123.0

    at2 = _fresh()
    at2.run()
    at2.session_state["_pending_project"] = project_io.dump_project({}, scalars)
    at2.run()
    assert not at2.exception
    assert at2.session_state["shear_on"] is True
    assert at2.session_state["shear_V"] == 123.0
    assert at2.session_state["shear_axis"] == "Horizontal shear (bending about y)"
