"""Tests for the shear resistance without shear reinforcement (VRd,c).

The engine reproduces EN 1992-1-1:2005 sec. 6.2.2(1) with the DK NA:2024 v_min.
The reference hand calculation is a 300 x 600 mm rectangle, C35, DK NA:2024,
with Asl = 1473 mm2 (d = 550 mm, bw = 300 mm, N = 0): VRd,c ~ 103.4 kN.
"""

from __future__ import annotations

import copy
import json
import math
import pathlib
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from sector import capacity, codes, detailing, shear

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))       # so `import sector_app` works standalone
APP = str(ROOT / "app" / "sector_app.py")

from app_case_inputs import (  # noqa: E402
    apply_widget_changes,
    discard_retired_qs_fragment,
    first_case_value,
    goto_input_stage,
)


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


def test_shear_ndps_accept_the_final_user_gamma_c():
    # The preset is only a starting value: the final effective user factor must
    # propagate into both CRd,c and the DK NA vmin expression.
    k, fck, gamma_c = 1.6, 35.0, 1.45 * 0.95 * 1.10
    code = codes.EC2_2005_DKNA
    assert code.shear_crd_c_over_gamma(gamma_c) == pytest.approx(0.18 / gamma_c)
    assert code.shear_vmin(k, fck, gamma_c) == pytest.approx(
        (0.051 / gamma_c) * k ** 1.5 * math.sqrt(fck))


# -- EN 1992-1-1:2023 strain-based tau_Rd,c (sec. 8.2.2) ---------------------

def test_shear_ddg_size_parameter():
    # ddg = 16 + Dlower <= 40 for fck <= 60; scaled by (60/fck)^2 above C60.
    assert codes.EC2_2023.shear_ddg(35.0, 16.0) == pytest.approx(32.0)
    assert codes.EC2_2023.shear_ddg(35.0, 32.0) == pytest.approx(40.0)   # capped
    assert codes.EC2_2023.shear_ddg(80.0, 32.0) == pytest.approx(16.0 + 32.0 * (60/80)**2)


def test_vrd_c_2023_hand_calc():
    # 300x600 (d=550, z=495), C35, ddg=32, fyd=500/1.15. gamma_v=1.40.
    code = codes.EC2_2023
    res = shear.vrd_c_2023(35.0, code, bw_mm=300.0, d_mm=550.0, asl_mm2=1473.0,
                           fyd_mpa=500.0 / 1.15, ddg_mm=32.0)
    assert res["valid"] and res["model"] == "2023"
    gv = 1.40
    rho = 1473.0 / (300.0 * 550.0)
    tau_basic = (0.66 / gv) * (100.0 * rho * 35.0 * 32.0 / 550.0) ** (1.0 / 3.0)
    tau_min = (11.0 / gv) * math.sqrt(35.0 / (500.0 / 1.15) * 32.0 / 550.0)
    assert res["tau_basic"] == pytest.approx(tau_basic)
    assert res["tau_min"] == pytest.approx(tau_min)
    assert res["tau_rdc"] == pytest.approx(max(tau_basic, tau_min))
    assert res["vrd_c"] == pytest.approx(max(tau_basic, tau_min) * 300.0 * 495.0 / 1000.0)
    assert res["vrd_c"] == pytest.approx(85.4, abs=0.3)


def test_vrd_c_2023_uses_the_selected_gamma_v_without_rounding():
    common = dict(
        fck=35.0,
        code=codes.EC2_2023,
        bw_mm=300.0,
        d_mm=550.0,
        asl_mm2=1473.0,
        fyd_mpa=500.0 / 1.15,
        ddg_mm=32.0,
    )

    default = shear.vrd_c_2023(**common, gamma_v=1.40)
    selected = shear.vrd_c_2023(**common, gamma_v=1.25)

    assert selected["gamma_v"] == pytest.approx(1.25)
    assert selected["tau_basic"] == pytest.approx(
        default["tau_basic"] * 1.40 / 1.25
    )
    assert selected["tau_min"] == pytest.approx(
        default["tau_min"] * 1.40 / 1.25
    )
    assert selected["vrd_c"] == pytest.approx(
        default["vrd_c"] * 1.40 / 1.25
    )


@pytest.mark.parametrize(
    "gamma_v",
    (
        True,
        False,
        np.bool_(True),
        0.0,
        1e-309,
        -1.0,
        float("nan"),
        float("inf"),
        "1.40",
    ),
)
def test_vrd_c_2023_rejects_malformed_gamma_v(gamma_v):
    with pytest.raises(
        ValueError,
        match="gamma_v must be a positive finite real number",
    ):
        shear.vrd_c_2023(
            35.0,
            codes.EC2_2023,
            bw_mm=300.0,
            d_mm=550.0,
            asl_mm2=1473.0,
            fyd_mpa=500.0 / 1.15,
            ddg_mm=32.0,
            gamma_v=gamma_v,
        )


def test_vrd_c_2023_invalid_keeps_all_keys():
    # Codex P2: an invalid 2023 result (zero depth) must still carry every reporting
    # key (incl. tau_basic) so the report does not KeyError.
    res = shear.vrd_c_2023(35.0, codes.EC2_2023, bw_mm=300.0, d_mm=0.0,
                           asl_mm2=1473.0, fyd_mpa=434.8, ddg_mm=32.0)
    assert not res["valid"]
    for k in ("vrd_c", "tau_rdc", "tau_basic", "tau_min", "rho_l", "z", "ddg",
              "fyd", "gamma_v", "model", "k_vp", "d_kvp", "a_cs",
              "n_ed_tension", "m_ed", "v_ed", "axial_applied"):
        assert k in res


def test_vrd_c_2023_axial_factor_formula_8_31():
    # Independent anchor for 8.30/8.31.  M/V = 1.10 m, which exceeds d = 0.55 m.
    common = dict(
        fck=35.0, code=codes.EC2_2023, bw_mm=300.0, d_mm=550.0,
        asl_mm2=1473.0, fyd_mpa=500.0 / 1.15, ddg_mm=32.0,
        m_ed_knm=110.0, v_ed_kn=100.0,
    )
    neutral = shear.vrd_c_2023(**common)
    tension = shear.vrd_c_2023(**common, n_ed_tension_kn=300.0)
    compression = shear.vrd_c_2023(**common, n_ed_tension_kn=-300.0)
    floor = shear.vrd_c_2023(**common, n_ed_tension_kn=-10_000.0)

    assert neutral["a_cs"] == pytest.approx(1100.0)
    assert neutral["k_vp"] == pytest.approx(1.0)
    assert tension["k_vp"] == pytest.approx(1.5)
    assert compression["k_vp"] == pytest.approx(0.5)
    assert floor["k_vp"] == pytest.approx(0.1)
    assert tension["d_kvp"] == pytest.approx(1.5 * 550.0)
    assert compression["d_kvp"] == pytest.approx(0.5 * 550.0)

    # Tension raises k_vp and lowers the basic resistance; compression does the
    # reverse.  Formula 8.20 and z = 0.9d retain the nominal depth.
    assert tension["tau_basic"] < neutral["tau_basic"] < compression["tau_basic"]
    assert tension["vrd_c"] < neutral["vrd_c"] < compression["vrd_c"]
    assert tension["tau_min"] == pytest.approx(neutral["tau_min"])
    assert compression["tau_min"] == pytest.approx(neutral["tau_min"])
    assert tension["z"] == pytest.approx(neutral["z"])
    assert compression["z"] == pytest.approx(neutral["z"])


def test_vrd_c_2023_dispatch_converts_compression_positive_sign():
    common = dict(
        fck=35.0, code=codes.EC2_2023, bw_mm=300.0, d_mm=550.0,
        asl_mm2=1473.0, ac_m2=0.18, fyd_mpa=500.0 / 1.15, ddg_mm=32.0,
        m_ed_knm=110.0, v_ed_kn=100.0,
    )
    tension = shear.vrd_c(**common, n_ed_comp_kn=-300.0)
    compression = shear.vrd_c(**common, n_ed_comp_kn=300.0)
    assert tension["n_ed_tension"] == pytest.approx(300.0)
    assert tension["k_vp"] == pytest.approx(1.5)
    assert compression["n_ed_tension"] == pytest.approx(-300.0)
    assert compression["k_vp"] == pytest.approx(0.5)


def test_vrd_c_dispatches_on_shear_model():
    # The generic vrd_c routes the 2023 edition to the strain-based branch.
    res = shear.vrd_c(35.0, codes.EC2_2023, 300.0, 550.0, 1473.0, 0.0, 0.18,
                      fyd_mpa=500.0 / 1.15, ddg_mm=32.0)
    assert res.get("model") == "2023"
    res5 = shear.vrd_c(35.0, codes.EC2_2005_DKNA, 300.0, 550.0, 1473.0, 0.0, 0.18)
    assert "model" not in res5 or res5.get("model") != "2023"
    assert res5["vrd_c"] != pytest.approx(res["vrd_c"])   # different models


def test_2005_dispatch_does_not_consume_the_2023_gamma_v_input():
    common = dict(
        fck=35.0,
        code=codes.EC2_2005_DKNA,
        bw_mm=300.0,
        d_mm=550.0,
        asl_mm2=1473.0,
        n_ed_comp_kn=0.0,
        ac_m2=0.18,
    )

    low = shear.vrd_c(**common, gamma_v=0.50)
    high = shear.vrd_c(**common, gamma_v=9.00)

    assert low == high


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


def test_physical_sparse_link_fixture_keeps_concrete_capacity_route():
    concrete = shear.vrd_c(
        fck=35.0,
        code=codes.EC2_2005_DKNA,
        bw_mm=300.0,
        d_mm=550.0,
        asl_mm2=1473.0,
        n_ed_comp_kn=0.0,
        ac_m2=0.18,
    )
    asw_over_s = (math.pi * 4.0**2 / 4.0) / 2000.0
    sparse = shear.vrd_links(
        35.0,
        codes.EC2_2005_DKNA,
        300.0,
        550.0,
        asw_over_s,
        500.0,
        0.0,
        0.18,
        1.0,
        2.5,
        z_mm=495.0,
        gamma_s=1.20,
        v_ed_kn=100.0,
    )
    result = {
        "v_ed": 100.0,
        "res": concrete,
        "util": 100.0 / concrete["vrd_c"],
        "links": {
            "res": sparse,
            "util": 100.0 / sparse["vrd"],
        },
    }

    selected = capacity.select_nominal_shear_resistance(
        result,
        links_selected=True,
    )

    assert concrete["vrd_c"] == pytest.approx(103.4166341272)
    assert sparse["vrd"] == pytest.approx(3.2397674240)
    assert 100.0 / sparse["vrd"] == pytest.approx(30.8664132057)
    assert selected.route == "concrete"
    assert selected.resistance == pytest.approx(concrete["vrd_c"])
    assert selected.utilisation == pytest.approx(100.0 / concrete["vrd_c"])
    assert selected.status == "PASS"


def test_vrd_c_uses_final_user_concrete_factor_and_fcd():
    # Deliberately differ from the DK preset (1.45): every shear quantity that
    # depends on concrete design strength must use the material-panel values.
    gamma_c = 1.45 * 0.95 * 1.10
    fcd = 0.90 * 35.0 / gamma_c
    res = shear.vrd_c(
        35.0, codes.EC2_2005_DKNA, 300.0, 550.0, 1473.0,
        n_ed_comp_kn=1e9, ac_m2=0.18, gamma_c=gamma_c, fcd_mpa=fcd,
    )
    assert res["gamma_c"] == pytest.approx(gamma_c)
    assert res["crd_c"] == pytest.approx(0.18 / gamma_c)
    assert res["vmin"] == pytest.approx(
        (0.051 / gamma_c) * res["k"] ** 1.5 * math.sqrt(35.0))
    assert res["fcd"] == pytest.approx(fcd)
    assert res["sigma_cp"] == pytest.approx(0.2 * fcd)


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


# -- shear WITH links (2005 sec. 6.2.3 / 2023 sec. 8.2.3) ------------------

def test_2023_compression_field_angle_limits():
    ordinary = shear.compression_field_limits_2023(0.0, 200.0, "B")
    tension = shear.compression_field_limits_2023(400.0, 200.0, "C")
    class_a = shear.compression_field_limits_2023(0.0, 200.0, "A")
    compression = shear.compression_field_limits_2023(-1000.0, 200.0, "B")
    assert ordinary["minimum"] == pytest.approx(1.0)
    assert ordinary["maximum"] == pytest.approx(2.5)
    assert tension["maximum"] == pytest.approx(2.3)
    assert tension["axial_tension_applied"]
    assert class_a["maximum"] == pytest.approx(2.0)
    assert compression["maximum"] == pytest.approx(2.5)
    assert not compression["compression_extension_credited"]


def test_vrd_links_2023_hand_calc_and_derived_stresses():
    # 300 x 600 mm, d=550 mm, z=495 mm, two 10 mm legs at 150 mm,
    # fywk=500 MPa, gamma_s=1.15, fcd=20 MPa and VEd=300 kN.
    asw = 2.0 * math.pi * 10.0**2 / 4.0
    asw_over_s = asw / 150.0
    result = shear.vrd_links(
        35.0,
        codes.EC2_2023,
        300.0,
        550.0,
        asw_over_s,
        500.0,
        0.0,
        0.18,
        1.0,
        2.5,
        z_mm=495.0,
        fcd_mpa=20.0,
        gamma_s=1.15,
        v_ed_kn=300.0,
    )
    assert result["valid"] and result["model"] == "2023"
    rho_w = asw_over_s / 300.0
    assert result["rho_w"] == pytest.approx(rho_w)
    assert result["nu"] == pytest.approx(0.5)
    assert result["tau_rd_sy"] == pytest.approx(
        rho_w * (500.0 / 1.15) * result["cot"]
    )
    assert result["tau_ed"] == pytest.approx(300.0 * 1000.0 / (300.0 * 495.0))
    assert result["sigma_cd"] == pytest.approx(
        result["tau_ed"] * (result["cot"] + 1.0 / result["cot"])
    )
    assert result["nu_fcd"] == pytest.approx(10.0)
    assert result["vrd"] == pytest.approx(
        min(result["vrd_s"], result["vrd_max"])
    )


@pytest.mark.parametrize(
    "n_ed_comp_kn",
    (math.nextafter(0.0, math.inf), 750.0, 2000.0),
    ids=(
        "smallest-positive",
        "total-equals-v-times-configured-cot-upper-bound",
        "high-compression",
    ),
)
def test_vrd_links_2023_axial_compression_fails_before_angle_selection(
    monkeypatch,
    n_ed_comp_kn,
):
    def forbidden_angle_selection(*args, **kwargs):
        del args, kwargs
        pytest.fail("the simplified compression-field method was entered")

    monkeypatch.setattr(shear, "optimum_strut_angle", forbidden_angle_selection)
    result = shear.vrd_links(
        35.0,
        codes.EC2_2023,
        300.0,
        550.0,
        1.0,
        500.0,
        n_ed_comp_kn,
        0.18,
        1.0,
        2.5,
        z_mm=495.0,
        fcd_mpa=20.0,
        gamma_s=1.15,
        v_ed_kn=300.0,
    )

    assert result["valid"] is False
    assert result["calculation_state"] == "NOT ASSESSED"
    assert result["reason"] == (
        "2023 axial-compression applicability conditions were not demonstrated"
    )
    assert result["vrd_s"] is None
    assert result["vrd_max"] is None
    assert result["vrd"] is None
    assert result["z"] is None
    assert result["cot"] is None
    assert result["angle_selection"] == "none"
    applicability = result["axial_applicability"]
    assert applicability["net_axial_compression_kn"] == n_ed_comp_kn
    assert applicability["mean_compression_mpa"] == pytest.approx(
        n_ed_comp_kn / 0.18 / 1000.0
    )
    assert applicability["web_force_condition_demonstrated"] is False
    assert applicability["selected_web_force_kn"] is None
    assert applicability["web_force_limit_kn"] is None
    assert applicability["chord_depth_condition_demonstrated"] is False
    assert applicability["action_compression_chord_depth_mm"] is None
    assert applicability["compression_chord_depth_limit_mm"] == pytest.approx(
        0.25 * 550.0
    )
    assert applicability["simplified_method_applicable"] is False
    assert applicability["separate_member_assessment_required"] is True
    assert applicability["annex_g_requirement_determined"] is False
    if n_ed_comp_kn == 750.0:
        # This is exact equality to VEd times the configured cotangent upper bound.
        # No angle or NEdw allocation has been selected, so the total net compression
        # cannot demonstrate the web-force condition in 8.2.3(11).
        assert result["cot_max"] == pytest.approx(2.5)
        assert n_ed_comp_kn == 300.0 * result["cot_max"]
        assert applicability["selected_web_force_kn"] is None


@pytest.mark.parametrize("n_ed_comp_kn", (-300.0, -0.0, 0.0))
def test_vrd_links_2023_zero_or_tension_retains_existing_method(n_ed_comp_kn):
    result = shear.vrd_links(
        35.0,
        codes.EC2_2023,
        300.0,
        550.0,
        1.0,
        500.0,
        n_ed_comp_kn,
        0.18,
        1.0,
        2.5,
        z_mm=495.0,
        fcd_mpa=20.0,
        gamma_s=1.15,
        v_ed_kn=300.0,
    )

    assert result["valid"] is True
    assert result["vrd"] > 0.0
    applicability = result["axial_applicability"]
    assert applicability["compression_present"] is False
    assert applicability["simplified_method_applicable"] is True
    assert applicability["web_force_condition_required"] is False
    assert applicability["chord_depth_condition_required"] is False


def test_vrd_links_2023_requires_final_fcd():
    result = shear.vrd_links(
        35.0,
        codes.EC2_2023,
        300.0,
        550.0,
        1.0,
        500.0,
        0.0,
        0.18,
        1.0,
        2.5,
        z_mm=495.0,
    )
    assert not result["valid"]
    assert result["fcd"] == 0.0

def test_shear_nu1_edition_dependent():
    # Recommended nu = 0.6(1 - fck/250); DK NA:2024 nu_v = 0.7 - fck/200 >= 0.45.
    assert codes.EC2_2005.shear_nu1(35.0) == pytest.approx(0.6 * (1 - 35.0 / 250.0))
    assert codes.EC2_2005_DKNA.shear_nu1(35.0) == pytest.approx(0.525)
    assert codes.EC2_2005_DKNA.shear_nu1(60.0) == pytest.approx(0.45)   # floor


def test_shear_alpha_cw_ranges():
    code, fcd = codes.EC2_2005, 20.0
    assert code.shear_alpha_cw(0.0, fcd) == 1.0
    assert code.shear_alpha_cw(-5.0, fcd) == 1.0                 # tension -> 1
    assert code.shear_alpha_cw(0.1 * fcd, fcd) == pytest.approx(1.1)
    assert code.shear_alpha_cw(0.4 * fcd, fcd) == pytest.approx(1.25)
    assert code.shear_alpha_cw(0.75 * fcd, fcd) == pytest.approx(2.5 * 0.25)
    assert code.shear_alpha_cw(1.2 * fcd, fcd) == 0.0           # beyond fcd -> crushed


def test_vrd_links_hand_calc_dk_na_stirrups_govern():
    # 300 x 600 (d=550, explicit calculated z=495), C35, DK NA,
    # 2-leg 10 mm links at 150 mm,
    # fywk=500. The crossover cot is above 2.5, so cot clamps to 2.5 and the stirrups
    # govern: VRd,s ~ 540 kN < VRd,max ~ 649 kN.
    code = codes.EC2_2005_DKNA
    asw = 2 * math.pi / 4 * 10.0 ** 2                            # 2 legs, 10 mm
    res = shear.vrd_links(35.0, code, bw_mm=300.0, d_mm=550.0, asw_over_s=asw / 150.0,
                          fywk=500.0, n_ed_comp_kn=0.0, ac_m2=0.18,
                          cot_min=1.0, cot_max=2.5, z_mm=495.0)
    assert res["valid"]
    assert res["z"] == pytest.approx(495.0)
    assert res["nu1"] == pytest.approx(0.525)
    assert res["fywd"] == pytest.approx(500.0 / 1.20)
    assert res["alpha_cw"] == pytest.approx(1.0)
    assert res["cot"] == pytest.approx(2.5)                     # crossover above max
    assert res["vrd_s"] == pytest.approx(540.0, abs=1.0)
    assert res["vrd_max"] == pytest.approx(648.9, abs=1.5)
    assert res["vrd"] == pytest.approx(res["vrd_s"])
    assert "stirrups" in res["governs"]


def test_vrd_links_uses_final_material_factors_not_method_preset():
    gamma_s = 1.20 * 0.95 * 1.10
    fcd = 19.75
    res = shear.vrd_links(
        35.0, codes.EC2_2005_DKNA, 300.0, 550.0, asw_over_s=3.0,
        fywk=500.0, n_ed_comp_kn=0.0, ac_m2=0.18, cot_min=1.0,
        cot_max=2.5, z_mm=495.0, fcd_mpa=fcd, gamma_s=gamma_s,
    )
    assert res["gamma_s"] == pytest.approx(gamma_s)
    assert res["fywd"] == pytest.approx(500.0 / gamma_s)
    assert res["fcd"] == pytest.approx(fcd)


def test_vrd_links_interior_optimum_balances_stirrups_and_crushing():
    # Heavy links push the crossover inside the band, where VRd,s = VRd,max and VRd
    # is maximised at that intermediate angle.
    code = codes.EC2_2005_DKNA
    res = shear.vrd_links(35.0, code, 300.0, 550.0, asw_over_s=3.0, fywk=500.0,
                          n_ed_comp_kn=0.0, ac_m2=0.18, cot_min=1.0, cot_max=2.5,
                          z_mm=495.0)
    assert 1.0 < res["cot"] < 2.5
    assert res["vrd_s"] == pytest.approx(res["vrd_max"], rel=1e-3)
    assert res["vrd"] == pytest.approx(res["vrd_s"], rel=1e-3)
    assert res["theta_deg"] == pytest.approx(math.degrees(math.atan(1.0 / res["cot"])))


def test_vrd_links_axial_compression_raises_vrd_max():
    # A compression axial force raises alpha_cw (6.11N) and hence VRd,max.
    code = codes.EC2_2005
    base = shear.vrd_links(
        35.0, code, 300.0, 550.0, 3.0, 500.0, 0.0, 0.18, 1.0, 2.5,
        z_mm=495.0,
    )
    comp = shear.vrd_links(
        35.0, code, 300.0, 550.0, 3.0, 500.0, 800.0, 0.18, 1.0, 2.5,
        z_mm=495.0,
    )
    assert comp["alpha_cw"] > 1.0
    assert comp["vrd_max"] > base["vrd_max"]


def test_vrd_links_invalid_without_stirrups():
    res = shear.vrd_links(35.0, codes.EC2_2005_DKNA, 300.0, 550.0, asw_over_s=0.0,
                          fywk=500.0, n_ed_comp_kn=0.0, ac_m2=0.18,
                          cot_min=1.0, cot_max=2.5, z_mm=495.0)
    assert not res["valid"] and res["vrd"] == 0.0


@pytest.mark.parametrize("code", (codes.EC2_2005_DKNA, codes.EC2_2023))
@pytest.mark.parametrize("cot_max", (2.5, 3.0), ids=("in-range", "out-of-range"))
def test_vrd_links_without_an_explicit_calculated_arm_fails_closed(code, cot_max):
    result = shear.vrd_links(
        35.0,
        code,
        300.0,
        550.0,
        1.0,
        500.0,
        0.0,
        0.18,
        1.0,
        cot_max,
        fcd_mpa=20.0,
        gamma_s=1.15,
        v_ed_kn=100.0,
    )

    assert result["valid"] is False
    assert result["calculation_state"] == "NOT ASSESSED"
    assert "lever arm" in result["reason"]
    assert result["z"] is None
    assert result["vrd_s"] is None
    assert result["vrd_max"] is None
    assert result["vrd"] is None


def test_direct_2023_links_kernel_without_an_arm_fails_closed():
    result = shear.vrd_links_2023(
        35.0,
        codes.EC2_2023,
        300.0,
        550.0,
        1.0,
        500.0,
        1.0,
        2.5,
        fcd_mpa=20.0,
        gamma_s=1.15,
        v_ed_kn=100.0,
    )

    assert result["valid"] is False
    assert result["calculation_state"] == "NOT ASSESSED"
    assert result["vrd"] is None


def test_optimum_cot_theta_clamps_to_bounds():
    # a >= b -> crossover below 1, floor at 1; tiny a -> above max, clamp to max.
    assert shear.optimum_cot_theta(a=100.0, b=50.0, cot_min=1.0, cot_max=2.5) == 1.0
    assert shear.optimum_cot_theta(a=1.0, b=1e6, cot_min=1.0, cot_max=2.5) == 2.5
    # Widened UPPER bound is honoured (the UI warns but does not block).
    assert shear.optimum_cot_theta(1.0, 1e6, 1.0, 3.0) == 3.0


def test_optimum_cot_theta_never_below_one_even_with_wide_lower_bound():
    # Codex P2: below cot(theta) = 1 BOTH VRd,s and VRd,max fall, so the optimum is
    # never there even when the user widens cot_min below 1. The crossover is floored
    # at 1 before clamping, so a heavy-link section optimises at 1.0, not the 0.5 floor.
    assert shear.optimum_cot_theta(a=100.0, b=50.0, cot_min=0.5, cot_max=2.5) == 1.0
    assert shear.optimum_cot_theta(a=1.0, b=5.0, cot_min=0.5, cot_max=2.5) == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("requested_min", "requested_max", "permitted_max", "applicable"),
    (
        (1.0, 2.5, 2.5, True),
        (math.nextafter(1.0, math.inf), math.nextafter(2.5, 0.0), 2.5, True),
        (math.nextafter(1.0, 0.0), 2.5, 2.5, False),
        (1.0, math.nextafter(2.5, math.inf), 2.5, False),
        (1.0, 2.0, 2.0, True),
        (1.0, math.nextafter(2.0, math.inf), 2.0, False),
        (1.0, 1.6, 1.6, True),
        (1.0, math.nextafter(1.6, math.inf), 1.6, False),
    ),
)
def test_strut_angle_applicability_uses_exact_requested_interval(
    requested_min,
    requested_max,
    permitted_max,
    applicable,
):
    result = shear.strut_angle_applicability(
        requested_min,
        requested_max,
        permitted_min=1.0,
        permitted_max=permitted_max,
        method="implementation fixture",
        basis="fixture permitted range",
        clause="fixture clause",
    )

    assert result["applicable"] is applicable
    assert result["status"] == ("ASSESSED" if applicable else "NOT ASSESSED")
    assert result["requested_min"] == min(requested_min, requested_max)
    assert result["requested_max"] == max(requested_min, requested_max)
    assert result["permitted_max"] == permitted_max
    assert result["reason"] == (
        None if applicable else shear.STRUT_ANGLE_OUT_OF_RANGE_REASON
    )


@pytest.mark.parametrize(
    "value",
    (True, np.bool_(False), "2.5", math.nan, math.inf, -math.inf),
)
def test_strut_angle_applicability_rejects_non_real_or_non_finite_limits(value):
    with pytest.raises(ValueError, match="finite real numbers"):
        shear.strut_angle_applicability(
            1.0,
            value,
            permitted_min=1.0,
            permitted_max=2.5,
            method="implementation fixture",
            basis="fixture permitted range",
            clause="fixture clause",
        )


def test_inactive_strut_angle_retains_limits_without_a_domain_verdict():
    result = shear.strut_angle_applicability(
        1.0,
        3.0,
        permitted_min=1.0,
        permitted_max=2.5,
        method="implementation fixture",
        basis="fixture permitted range",
        clause="fixture clause",
        active=False,
    )

    assert result["active"] is False
    assert result["applicable"] is False
    assert result["status"] == "NOT APPLICABLE"
    assert result["reason"] is None
    assert result["requested_max"] == 3.0
    assert result["permitted_max"] == 2.5


def test_first_generation_false_pass_oracle_is_not_assessed_outside_band():
    asw_over_s = 2.0 * math.pi * 10.0**2 / 4.0 / 150.0
    common = dict(
        fck=35.0,
        code=codes.EC2_2005,
        bw_mm=300.0,
        d_mm=550.0,
        asw_over_s=asw_over_s,
        fywk=550.0,
        n_ed_comp_kn=0.0,
        ac_m2=0.18,
        cot_min=1.0,
        z_mm=500.0,
        fcd_mpa=35.0 / 1.45,
        gamma_s=1.20,
        v_ed_kn=620.0,
    )

    permitted = shear.vrd_links(cot_max=2.5, **common)
    assert permitted["valid"] is True
    assert permitted["vrd"] == pytest.approx(599.956930373051)
    assert 620.0 / permitted["vrd"] == pytest.approx(1.0334075141268662)

    outside = shear.vrd_links(cot_max=3.0, **common)
    assert outside["valid"] is False
    assert outside["calculation_state"] == "NOT ASSESSED"
    assert outside["vrd_s"] is None
    assert outside["vrd_max"] is None
    assert outside["vrd"] is None
    assert outside["cot"] is None
    assert outside["angle_applicability"]["requested_max"] == 3.0
    assert outside["angle_applicability"]["permitted_max"] == 2.5

    inactive = shear.vrd_links(cot_max=3.0, **dict(common, v_ed_kn=0.0))
    assert inactive["valid"] is True
    assert math.isfinite(inactive["vrd"]) and inactive["vrd"] > 0.0
    assert inactive["angle_applicability"]["active"] is False
    assert inactive["angle_applicability"]["status"] == "NOT APPLICABLE"


def test_2023_class_a_false_pass_oracle_is_not_assessed_outside_band():
    asw_over_s = 2.0 * math.pi * 10.0**2 / 4.0 / 150.0
    common = dict(
        fck=35.0,
        code=codes.EC2_2023,
        bw_mm=300.0,
        d_mm=550.0,
        asw_over_s=asw_over_s,
        fywk=550.0,
        n_ed_comp_kn=0.0,
        ac_m2=0.165,
        cot_min=1.0,
        z_mm=500.0,
        fcd_mpa=35.0 / 1.5,
        gamma_s=1.15,
        v_ed_kn=556.81558,
        ductility_class="A",
    )

    permitted = shear.vrd_links(cot_max=2.0, **common)
    assert permitted["valid"] is True
    assert permitted["vrd"] == pytest.approx(500.8336114418512)
    assert 556.81558 / permitted["vrd"] == pytest.approx(1.1117775789787394)

    outside = shear.vrd_links(cot_max=2.5, **common)
    assert outside["valid"] is False
    assert outside["calculation_state"] == "NOT ASSESSED"
    assert outside["vrd"] is None
    assert outside["angle_applicability"]["permitted_max"] == 2.0


def test_retained_strut_angle_is_compact_frozen_and_reconstructs_selection():
    result = shear.optimum_strut_angle(3.0, 21.0, 1.0, 2.5)
    assert result.cot == pytest.approx(
        shear.optimum_cot_theta(3.0, 21.0, 1.0, 2.5)
    )
    assert result.tan == pytest.approx(1.0 / result.cot)
    assert result.sin_cos == pytest.approx(result.cot / (1.0 + result.cot**2))
    assert result.cot_unconstrained == pytest.approx(math.sqrt(6.0))
    assert result.selection == "stirrup/crushing crossover"
    assert not hasattr(result, "__dict__")
    with pytest.raises(AttributeError):
        result.cot = 2.0


def test_shear_results_retain_caps_and_final_angle_operands():
    concrete = shear.vrd_c(
        35.0,
        codes.EC2_2005_DKNA,
        bw_mm=300.0,
        d_mm=550.0,
        asl_mm2=20_000.0,
        n_ed_comp_kn=10_000.0,
        ac_m2=0.18,
    )
    assert concrete["rho_l"] == pytest.approx(min(concrete["rho_l_raw"], 0.02))
    assert concrete["sigma_cp"] == pytest.approx(
        min(concrete["sigma_cp_raw"], concrete["sigma_cp_cap"])
    )
    assert concrete["stress"] == pytest.approx(
        max(concrete["v_basic"], concrete["v_floor"], 0.0)
    )

    links = shear.vrd_links(
        35.0,
        codes.EC2_2005_DKNA,
        300.0,
        550.0,
        asw_over_s=3.0,
        fywk=500.0,
        n_ed_comp_kn=0.0,
        ac_m2=0.18,
        cot_min=1.0,
        cot_max=2.5,
        z_mm=495.0,
    )
    assert links["tan"] == pytest.approx(1.0 / links["cot"])
    assert links["sin_cos"] == pytest.approx(
        links["cot"] / (1.0 + links["cot"] ** 2)
    )
    assert links["angle_a"] == pytest.approx(
        links["asw_over_s"] * links["fywd"]
    )
    assert links["angle_b"] == pytest.approx(
        links["alpha_cw"] * links["bw"] * links["nu1"] * links["fcd"]
    )


def test_vrd_links_widened_lower_bound_does_not_reduce_vrd():
    # Heavy links whose crossover is well below 1: the optimiser picks cot = 1 (not
    # the widened 0.5 floor), and forcing cot = 0.5 gives a strictly smaller VRd.
    code = codes.EC2_2005_DKNA
    wide = shear.vrd_links(35.0, code, 300.0, 550.0, asw_over_s=8.0, fywk=500.0,
                           n_ed_comp_kn=0.0, ac_m2=0.18, cot_min=0.5, cot_max=2.5,
                           z_mm=495.0)
    assert wide["cot"] == pytest.approx(1.0)
    forced = shear.vrd_links(
        35.0, code, 300.0, 550.0, 8.0, 500.0, 0.0, 0.18, 0.5, 0.5,
        z_mm=495.0,
    )
    assert forced["cot"] == pytest.approx(0.5)
    assert forced["vrd"] < wide["vrd"]


# -- section-form and duct operands (MVT-H06) ------------------------------

def _shear_geometry(**overrides):
    values = dict(
        model_2023=True,
        solid_rectangle=True,
        section_form=shear.SHEAR_SECTION_AUTO,
        bw_mm=400.0,
        bw_user=False,
        links_present=True,
        web_inclination_deg=0.0,
        hoop_diameter_mm=0.0,
        fitted_z_mm=0.0,
        duct_case=shear.SHEAR_DUCT_NONE,
        duct_sum_mm=0.0,
        duct_largest_mm=0.0,
    )
    values.update(overrides)
    return shear.resolve_shear_geometry(**values)


@pytest.mark.parametrize("model_2023", (False, True))
def test_rectangular_no_duct_geometry_retains_the_existing_operands(model_2023):
    result = _shear_geometry(model_2023=model_2023)

    assert result["valid"] is True
    assert result["resolved_form"] == shear.SHEAR_SECTION_CONSTANT
    assert result["concrete_bw_mm"] == pytest.approx(400.0)
    assert result["links_bw_mm"] == pytest.approx(400.0)
    assert result["asw_factor"] == pytest.approx(1.0)
    assert result["duct_factor_concrete"] == pytest.approx(0.0)
    assert result["duct_factor_links"] == pytest.approx(0.0)


def test_2023_variable_width_applies_the_inclination_to_link_area_only():
    result = _shear_geometry(
        solid_rectangle=False,
        section_form=shear.SHEAR_SECTION_VARIABLE,
        bw_user=True,
        web_inclination_deg=60.0,
    )

    assert result["valid"] is True
    assert result["asw_factor"] == pytest.approx(0.5)
    assert result["concrete_bw_mm"] == pytest.approx(400.0)
    assert result["links_bw_mm"] == pytest.approx(400.0)

    no_links = _shear_geometry(
        solid_rectangle=False,
        section_form=shear.SHEAR_SECTION_VARIABLE,
        bw_user=True,
        links_present=False,
        web_inclination_deg="not required",
    )
    assert no_links["concrete_valid"] is True
    assert no_links["asw_factor"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    "section_form",
    (shear.SHEAR_SECTION_VARIABLE, shear.SHEAR_SECTION_CIRCULAR),
)
def test_first_generation_variable_and_circular_forms_fail_closed(section_form):
    result = _shear_geometry(
        model_2023=False,
        solid_rectangle=False,
        section_form=section_form,
        bw_user=True,
        hoop_diameter_mm=600.0,
        fitted_z_mm=500.0,
    )

    assert result["valid"] is False
    assert result["concrete_valid"] is False
    assert result["links_valid"] is False
    assert result["reason"] == shear.SHEAR_SECTION_METHOD_REASON


def test_2023_circular_factor_400_over_600_removes_the_1_5_overstatement():
    geometry_result = _shear_geometry(
        solid_rectangle=False,
        section_form=shear.SHEAR_SECTION_CIRCULAR,
        bw_user=True,
        hoop_diameter_mm=600.0,
        fitted_z_mm=500.0,
    )
    assert geometry_result["valid"] is True
    assert geometry_result["asw_factor"] == pytest.approx(2.0 / 3.0)
    assert geometry_result["fitted_z_mm"] == pytest.approx(500.0)

    gross_asw_over_s = 2.0
    common = dict(
        fck=35.0,
        code=codes.EC2_2023,
        bw_mm=400.0,
        d_mm=550.0,
        fywk=500.0,
        n_ed_comp_kn=0.0,
        ac_m2=0.24,
        cot_min=2.0,
        cot_max=2.0,
        z_mm=500.0,
        fcd_mpa=20.0,
        gamma_s=1.15,
        v_ed_kn=100.0,
    )
    unadjusted = shear.vrd_links(
        asw_over_s=gross_asw_over_s,
        **common,
    )
    corrected = shear.vrd_links(
        asw_over_s=gross_asw_over_s * geometry_result["asw_factor"],
        **common,
    )

    assert corrected["vrd_s"] == pytest.approx(
        unadjusted["vrd_s"] * 2.0 / 3.0
    )
    assert unadjusted["vrd_s"] / corrected["vrd_s"] == pytest.approx(1.5)


@pytest.mark.parametrize(
    ("duct_case", "factor"),
    (
        (shear.SHEAR_DUCT_GROUTED_STEEL, 0.5),
        (shear.SHEAR_DUCT_GROUTED_PLASTIC_THIN, 0.8),
        (shear.SHEAR_DUCT_GROUTED_PLASTIC_THICK, 1.2),
        (shear.SHEAR_DUCT_UNGROUTED_OR_SOFT, 1.2),
    ),
)
def test_2023_supported_duct_cases_use_formula_8_54(duct_case, factor):
    result = _shear_geometry(
        duct_case=duct_case,
        duct_sum_mm=80.0,
        duct_largest_mm=40.0,
    )

    assert result["links_valid"] is True
    assert result["duct_factor_links"] == pytest.approx(factor)
    assert result["links_bw_mm"] == pytest.approx(400.0 - factor * 80.0)
    expected_concrete_factor = (
        1.2 if duct_case == shear.SHEAR_DUCT_UNGROUTED_OR_SOFT else 0.0
    )
    assert result["duct_factor_concrete"] == pytest.approx(
        expected_concrete_factor
    )
    assert result["concrete_bw_mm"] == pytest.approx(
        400.0 - expected_concrete_factor * 80.0
    )


def test_2023_duct_threshold_is_strict_and_no_links_ignores_known_grouted_ducts():
    at_threshold = _shear_geometry(
        duct_case=shear.SHEAR_DUCT_GROUTED_PLASTIC_THIN,
        duct_sum_mm=50.0,
        duct_largest_mm=25.0,
    )
    assert at_threshold["links_bw_mm"] == pytest.approx(400.0)

    known_grouted_no_links = _shear_geometry(
        links_present=False,
        duct_case=shear.SHEAR_DUCT_GROUTED_PLASTIC_THIN,
        duct_sum_mm=0.0,
        duct_largest_mm=0.0,
    )
    assert known_grouted_no_links["concrete_valid"] is True
    assert known_grouted_no_links["concrete_bw_mm"] == pytest.approx(400.0)

    ungrouted_no_links = _shear_geometry(
        links_present=False,
        duct_case=shear.SHEAR_DUCT_UNGROUTED_OR_SOFT,
        duct_sum_mm=80.0,
        duct_largest_mm=40.0,
    )
    assert ungrouted_no_links["concrete_bw_mm"] == pytest.approx(304.0)


@pytest.mark.parametrize(
    "duct_case",
    (
        shear.SHEAR_DUCT_GROUTED_PLASTIC_THIN,
        shear.SHEAR_DUCT_GROUTED_PLASTIC_THICK,
        shear.SHEAR_DUCT_UNGROUTED_OR_SOFT,
    ),
)
def test_2005_plastic_and_ungrouted_duct_cases_use_the_1_2_sum(duct_case):
    result = _shear_geometry(
        model_2023=False,
        duct_case=duct_case,
        duct_sum_mm=80.0,
        duct_largest_mm=40.0,
    )

    assert result["concrete_bw_mm"] == pytest.approx(400.0)
    assert result["links_bw_mm"] == pytest.approx(304.0)
    assert result["duct_factor_links"] == pytest.approx(1.2)


def test_2005_grouted_steel_uses_largest_diameter_threshold_then_sum():
    below = _shear_geometry(
        model_2023=False,
        duct_case=shear.SHEAR_DUCT_GROUTED_STEEL,
        duct_sum_mm=0.0,
        duct_largest_mm=50.0,
    )
    above = _shear_geometry(
        model_2023=False,
        duct_case=shear.SHEAR_DUCT_GROUTED_STEEL,
        duct_sum_mm=100.0,
        duct_largest_mm=60.0,
    )

    assert below["links_valid"] is True
    assert below["links_bw_mm"] == pytest.approx(400.0)
    assert above["links_bw_mm"] == pytest.approx(350.0)
    assert above["duct_factor_links"] == pytest.approx(0.5)


def test_duct_nominal_width_reduces_compression_field_not_link_yield():
    common = dict(
        fck=35.0,
        d_mm=550.0,
        asw_over_s=1.5,
        fywk=500.0,
        n_ed_comp_kn=0.0,
        ac_m2=0.22,
        cot_min=2.0,
        cot_max=2.0,
        z_mm=495.0,
        fcd_mpa=20.0,
        gamma_s=1.15,
        v_ed_kn=100.0,
    )
    for code, nominal_width in (
        (codes.EC2_2005_DKNA, 350.0),
        (codes.EC2_2023, 336.0),
    ):
        physical = shear.vrd_links(code=code, bw_mm=400.0, **common)
        nominal = shear.vrd_links(code=code, bw_mm=nominal_width, **common)

        assert nominal["vrd_s"] == pytest.approx(physical["vrd_s"])
        assert nominal["vrd_max"] == pytest.approx(
            physical["vrd_max"] * nominal_width / 400.0
        )
        assert nominal["vrd_max"] < physical["vrd_max"]


def test_missing_or_impossible_required_shear_geometry_fails_closed():
    circular = _shear_geometry(
        solid_rectangle=False,
        section_form=shear.SHEAR_SECTION_CIRCULAR,
        bw_user=True,
        hoop_diameter_mm=0.0,
        fitted_z_mm=0.0,
    )
    assert circular["concrete_valid"] is True
    assert circular["links_valid"] is False
    assert circular["links_reason"] == shear.SHEAR_CIRCULAR_REASON

    unknown_duct = _shear_geometry(
        links_present=False,
        duct_case=shear.SHEAR_DUCT_DETAILS_INCOMPLETE,
    )
    assert unknown_duct["concrete_valid"] is False
    assert unknown_duct["concrete_reason"] == shear.SHEAR_DUCT_INPUT_REASON

    no_web = _shear_geometry(
        duct_case=shear.SHEAR_DUCT_UNGROUTED_OR_SOFT,
        duct_sum_mm=400.0,
        duct_largest_mm=200.0,
    )
    assert no_web["concrete_valid"] is False
    assert no_web["links_valid"] is False
    assert no_web["concrete_reason"] == shear.SHEAR_NOMINAL_WIDTH_REASON
    assert no_web["links_reason"] == shear.SHEAR_NOMINAL_WIDTH_REASON


@pytest.mark.parametrize(
    ("hoop_diameter_mm", "fitted_z_mm"),
    (
        (True, 500.0),
        ("600", 500.0),
        (float("nan"), 500.0),
        (float("inf"), 500.0),
        (600.0, True),
        (600.0, "500"),
        (600.0, float("nan")),
        (600.0, float("inf")),
        (600.0, 601.0),
        (399.0, 399.0),
    ),
)
def test_invalid_circular_hoop_or_fitted_arm_withholds_the_links_branch(
    hoop_diameter_mm,
    fitted_z_mm,
):
    result = _shear_geometry(
        solid_rectangle=False,
        section_form=shear.SHEAR_SECTION_CIRCULAR,
        bw_user=True,
        hoop_diameter_mm=hoop_diameter_mm,
        fitted_z_mm=fitted_z_mm,
    )

    assert result["concrete_valid"] is True
    assert result["links_valid"] is False
    assert result["links_reason"] == shear.SHEAR_CIRCULAR_REASON
    assert result["links_bw_mm"] is None


@pytest.mark.parametrize(
    "bad_width",
    (True, "400", float("nan"), float("inf"), 0.0, -1.0),
)
def test_invalid_web_width_never_reaches_a_shear_branch(bad_width):
    result = _shear_geometry(bw_mm=bad_width)

    assert result["concrete_valid"] is False
    assert result["links_valid"] is False
    assert result["reason"] == shear.SHEAR_SECTION_GEOMETRY_REASON
    assert result["concrete_bw_mm"] is None
    assert result["links_bw_mm"] is None


@pytest.mark.parametrize(
    "bad_inclination",
    (True, "60", float("nan"), float("inf"), -0.1, 90.0),
)
def test_invalid_variable_width_inclination_withholds_the_links_branch(
    bad_inclination,
):
    result = _shear_geometry(
        solid_rectangle=False,
        section_form=shear.SHEAR_SECTION_VARIABLE,
        bw_user=True,
        web_inclination_deg=bad_inclination,
    )

    assert result["concrete_valid"] is True
    assert result["links_valid"] is False
    assert result["links_reason"] == shear.SHEAR_VARIABLE_WIDTH_REASON
    assert result["asw_factor"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    "bad_duct_sum",
    (True, "80", float("nan"), float("inf"), 0.0, -1.0),
)
def test_invalid_required_duct_sum_withholds_both_2023_branches(bad_duct_sum):
    result = _shear_geometry(
        duct_case=shear.SHEAR_DUCT_UNGROUTED_OR_SOFT,
        duct_sum_mm=bad_duct_sum,
        duct_largest_mm=0.0,
    )

    assert result["concrete_valid"] is False
    assert result["links_valid"] is False
    assert result["concrete_reason"] == shear.SHEAR_DUCT_INPUT_REASON
    assert result["links_reason"] == shear.SHEAR_DUCT_INPUT_REASON


def test_non_rectangular_constant_width_requires_an_entered_web_width():
    result = _shear_geometry(
        solid_rectangle=False,
        section_form=shear.SHEAR_SECTION_CONSTANT,
        bw_user=False,
    )

    assert result["concrete_valid"] is False
    assert result["links_valid"] is False
    assert result["reason"] == shear.SHEAR_SECTION_GEOMETRY_REASON


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


def test_tension_reinforcement_selection_retains_public_bar_ids():
    bars = [(0.05, -0.25, 300.0), (0.15, -0.20, 500.0),
            (0.10, 0.22, 400.0)]
    area, cg, bar_ids = shear.tension_reinforcement_selection(
        bars, "x", tension_low=True, centroid_coord=0.0
    )
    assert area == pytest.approx(800.0)
    assert cg == pytest.approx((-0.25 * 300.0 - 0.20 * 500.0) / 800.0)
    assert bar_ids == [1, 2]


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
    from sector.capacity import gross_area_centroid
    rect = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    a, cx, cy = gross_area_centroid(rect, [])
    assert a == pytest.approx(0.24)                   # 0.4 x 0.6 m
    assert (cx, cy) == pytest.approx((0.0, 0.0))
    hole = [(-0.05, -0.05), (0.05, -0.05), (0.05, 0.05), (-0.05, 0.05)]
    a2, cx2, cy2 = gross_area_centroid(rect, [hole])
    assert a2 == pytest.approx(0.24 - 0.01)           # void removed
    assert (cx2, cy2) == pytest.approx((0.0, 0.0))    # centred void keeps the centroid


# -- app integration (AppTest) ----------------------------------------------

def _fresh():
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(APP, default_timeout=90)


def _goto_page(at, page):
    try:
        current = at.session_state["_main_page"]
    except KeyError:
        current = None
    if current != page:
        at.segmented_control(key="_main_page").set_value(page).run()
    return at


def _calculate(at):
    _goto_page(at, "Analysis")
    at.button(key="calculate").click().run()
    return at


def _select_view(at, value):
    _goto_page(at, "Analysis")
    at.selectbox(key="view").set_value(value).run()
    return at


def _set(at, *changes):
    return apply_widget_changes(at, changes)


def _replace_base_table(at, base_key, value):
    """Reseed one rendered point table through the application's live boundary."""

    goto_input_stage(at, "Section")
    editor = {
        "corners_base": "ed_corners",
        "bars_base": "ed_bars",
    }[base_key]
    try:
        version = at.session_state[editor + "_ver"]
    except KeyError:
        version = 0
    at.session_state[base_key] = value
    at.session_state[editor + "_ver"] = version + 1
    try:
        del at.session_state[editor]
    except KeyError:
        pass
    at.run()
    return at


def _set_and_click(at, button_key, *changes):
    """Submit a group of existing inputs with one button-triggered rerun."""
    if button_key in {"qs_apply", "qs_back"} and changes:
        _set(at, *changes)
        changes = ()
    elif button_key == "calculate" and changes:
        _set(at, *changes)
        changes = ()
    for widget_type, key, value in changes:
        getattr(at, widget_type)(key=key).set_value(value)
    if button_key == "calculate":
        _goto_page(at, "Analysis")
    at.button(key=button_key).click()
    at.run()
    if button_key in {"qs_apply", "qs_back"}:
        discard_retired_qs_fragment(at)
    return at


def test_app_sparse_links_keep_concrete_capacity_and_fail_detailing_separately():
    import reinforcement_table

    at = _fresh()
    at.run()
    corners = at.session_state["corners_base"].copy(deep=True)
    corners.loc[:, "x (mm)"] = [-150.0, -150.0, 150.0, 150.0]
    corners.loc[:, "y (mm)"] = [-300.0, 300.0, 300.0, -300.0]
    _replace_base_table(at, "corners_base", corners)
    bars = reinforcement_table.table_from_points(
        [(0.0, -250.0, 1473.0), (0.0, 250.0, 1473.0)],
        "bar",
    )
    _replace_base_table(at, "bars_base", bars)
    _set(
        at,
        ("number_input", "mild_gamma_y", 1.20),
        ("checkbox", "transverse_detailing_on", True),
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2005_DKNA.label),
        ("checkbox", "shear_links", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("number_input", "shear_V", 100.0),
        ("number_input", "shear_bw", 300.0),
        ("number_input", "shear_link_legs", 1),
        ("number_input", "shear_link_dia", 4.0),
        ("number_input", "shear_link_s", 2000.0),
        ("number_input", "shear_fywk", 500.0),
    )

    assert not at.exception
    sh = at.session_state["results"]["shear"]
    selected = sh["nominal_resistance"]
    assert sh["res"]["vrd_c"] == pytest.approx(103.4166341272)
    assert sh["links"]["res"]["vrd"] < 5.0
    assert sh["links"]["util"] > 20.0
    assert selected["route"] == "concrete"
    assert selected["resistance"] == pytest.approx(sh["res"]["vrd_c"])
    assert selected["utilisation"] == pytest.approx(
        100.0 / sh["res"]["vrd_c"]
    )
    assert sh["resistance_status"] == "PASS"
    assert sh["assessment_status"] == "PASS"
    assert sh["links"]["longitudinal_shear_force"] == pytest.approx(0.0)
    assert sh["links"]["longitudinal_assessment"]["status"] == "NOT APPLICABLE"
    assert at.session_state["results"]["transverse_reinforcement"]["status"] == "FAIL"

    _select_view(at, "Shear")
    visible = " ".join(
        str(item.value)
        for collection in (at.caption, at.warning, at.error, at.markdown)
        for item in collection
    )
    assert "Separate link detailing assessment: FAIL" in visible
    assert "not a shear-capacity verdict" in visible
    assert "Overall reinforced shear assessment: FAIL" not in visible
    assert "Longitudinal chord: bending + shear tension" not in visible
    assert "no shear-induced longitudinal chord force is applied" in visible
    assert (
        "extra longitudinal tension the tension chord must also carry" not in visible
    )
    assert not any(
        "M_{Ed,\\mathrm{total}}" in metric.label
        or "M_{Ed,total}" in metric.label
        for metric in at.metric
    )
    nominal_metric = next(
        metric for metric in at.metric if "Nominal utilisation" in metric.label
    )
    assert nominal_metric.value == "96.7 %"
    assert nominal_metric.delta == "OK"
    comparison_metric = next(
        metric for metric in at.metric if "Provided-link comparison" in metric.label
    )
    assert comparison_metric.delta == ""

    _select_view(at, "Results Overview")
    overview = next(table.value for table in at.table if "Check" in table.value)
    concrete_row = overview.loc[
        overview["Check"] == "Shear without links"
    ].iloc[0]
    detail_row = overview.loc[
        overview["Check"].str.contains("minimum ratio", case=False)
    ].iloc[0]
    assert concrete_row["Status"] == "PASS"
    assert concrete_row["Result"] == "96.7 % (VEd / VRd,c)"
    assert detail_row["Status"] == "FAIL"
    assert not any(
        row["Status"] == "FAIL"
        for _index, row in overview.iterrows()
        if row["Check"] in {"Shear without links", "Shear with links"}
    )


def test_app_shear_check_produces_a_resistance():
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(at, "calculate", ("number_input", "shear_V", 100.0))
    assert not at.exception
    sh = at.session_state["results"]["shear"]
    assert sh["res"]["vrd_c"] > 0.0
    # Default 400 x 600 mm section, bottom bars at y = -250 mm -> d = 550, bw = 400.
    assert sh["d"] == pytest.approx(550.0, abs=1.0)
    assert sh["bw"] == pytest.approx(400.0, abs=1.0)
    assert not sh["bw_user"]                           # auto width
    assert sh["asl_bar_ids"] and sh["asl_cg"] is not None
    assert sh["util"] == pytest.approx(100.0 / sh["res"]["vrd_c"])


def test_app_circular_2023_fails_closed_then_applies_factor_and_fitted_arm(
    monkeypatch,
):
    original_vrd_links = shear.vrd_links
    calls = []

    def tracked_vrd_links(*args, **kwargs):
        calls.append((args, kwargs))
        return original_vrd_links(*args, **kwargs)

    monkeypatch.setattr(shear, "vrd_links", tracked_vrd_links)
    at = _fresh()
    at.run()
    at.session_state["_qs_open"] = True
    at.run()
    _set(at, ("selectbox", "shape", "Circular"))
    _set_and_click(at, "qs_apply")
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("checkbox", "shear_links", True),
        ("selectbox", "shear_section_form", shear.SHEAR_SECTION_CIRCULAR),
        ("number_input", "shear_vx_bw", 400.0),
        ("number_input", "shear_vy_bw", 400.0),
    )
    _set_and_click(at, "calculate", ("number_input", "shear_V", 50.0))

    assert not at.exception
    assert calls == []
    missing = at.session_state["results"]["shear"]
    assert missing["res"]["valid"] is True
    assert missing["links"]["res"]["calculation_state"] == "NOT ASSESSED"
    assert missing["links"]["res"]["vrd"] is None
    assert missing["links"]["util"] is None
    assert missing["links"]["shear_geometry"]["links_reason"] == (
        shear.SHEAR_CIRCULAR_REASON
    )

    _select_view(at, "Shear")
    visible = " ".join(
        item.value
        for collection in (at.warning, at.caption, at.markdown)
        for item in collection
    )
    assert "Enter the governing web width, hoop diameter" in visible
    assert "non-governing concrete-only context" in visible
    relevant_metrics = [
        metric
        for metric in at.metric
        if "V_{Rd" in metric.label or "Utilisation" in metric.label
    ]
    assert relevant_metrics
    assert all(metric.delta not in {"OK", "Over limit", "PASS", "FAIL"}
               for metric in relevant_metrics)
    assert shear.SHEAR_CIRCULAR_REASON not in visible

    _select_view(at, "Results Overview")
    overview = next(table.value for table in at.table if "Check" in table.value)
    links_row = overview.loc[overview["Check"] == "Shear with links"].iloc[0]
    assert links_row["Status"] == "NOT ASSESSED"
    assert links_row["Result"] == "-"

    _set_and_click(
        at,
        "calculate",
        ("number_input", "shear_hoop_diameter", 600.0),
        ("number_input", "shear_vx_fitted_z", 500.0),
        ("number_input", "shear_vy_fitted_z", 500.0),
    )
    assert not at.exception
    assert calls
    applied = at.session_state["results"]["shear"]
    assert applied["links"]["res"]["valid"] is True
    assert applied["links"]["asw_factor"] == pytest.approx(2.0 / 3.0)
    assert applied["links"]["effective_asw_over_s"] == pytest.approx(
        applied["links"]["asw_over_s"] * 2.0 / 3.0
    )
    assert applied["links"]["res"]["z"] == pytest.approx(500.0)
    assert applied["links"]["z_source"] == "circular_fitted_section"

    _select_view(at, "Shear")
    visible = " ".join(item.value for item in at.caption)
    assert "Fitted-section arm" in visible
    assert "section-form factor is applied" in visible
    rendered = " ".join(
        str(item.value)
        for collection in (at.caption, at.markdown, at.table, at.dataframe)
        for item in collection
    )
    assert "fitted circular section" in rendered
    assert "circular_fitted_section" not in rendered

    _select_view(at, "Results Overview")
    overview = next(table.value for table in at.table if "Check" in table.value)
    concrete_row = overview.loc[
        overview["Check"] == "Shear without links"
    ].iloc[0]
    assert concrete_row["Status"] == "PASS"
    assert "Shear with links" not in set(overview["Check"])
    import result_presentation as _presentation

    assert _presentation.result_reason(
        "compression field (sigma_cd)",
        "shear",
        context="H06 compression-field governing branch",
    ) == "concrete compression-field resistance governs"

    retained_rows = _presentation.multi_case_summary_rows(
        at.session_state["_latest_inputs"],
        at.session_state["results"],
    )
    retained_row = next(
        item for item in retained_rows if item["check"] == "Shear with links"
    )
    assert "effective Asw factor 0.66667" in retained_row["note"]
    assert "link-yield resistance governs" in retained_row["note"]
    assert "Review the shear inputs" not in retained_row["note"]


def test_app_circular_vx_torsion_rejects_invalid_off_axis_arm_then_recovers():
    at = _fresh()
    at.run()
    at.session_state["_qs_open"] = True
    at.run()
    _set(at, ("selectbox", "shape", "Circular"))
    _set_and_click(at, "qs_apply")
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("checkbox", "shear_links", True),
        ("selectbox", "shear_section_form", shear.SHEAR_SECTION_CIRCULAR),
        ("number_input", "shear_vx_bw", 400.0),
        ("number_input", "shear_vy_bw", 400.0),
        ("checkbox", "torsion_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("number_input", "shear_Vx", 50.0),
        ("number_input", "shear_Vy", 0.0),
        ("number_input", "torsion_T", 40.0),
        ("number_input", "shear_hoop_diameter", 600.0),
        ("number_input", "shear_vx_fitted_z", 500.0),
        ("number_input", "shear_vy_fitted_z", 700.0),
    )

    assert not at.exception
    blocked = at.session_state["results"]["shear"]
    assert blocked["component"] == "vx"
    assert blocked["links"]["res"]["valid"] is True
    assert blocked["links"]["chord_off"] is None
    assert blocked["links"]["chord"]["off_not_evaluated"] == (
        "circular_geometry"
    )
    assessment = blocked["links"]["longitudinal_assessment"]
    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["coverage_complete"] is False
    assert assessment["reason"] == shear.SHEAR_CIRCULAR_REASON
    assert blocked["assessment_status"] == "NOT ASSESSED"
    assert blocked["assessment_ok"] is None

    _select_view(at, "Shear")
    blocked_visible = " ".join(
        str(item.value)
        for collection in (at.warning, at.caption, at.markdown)
        for item in collection
    )
    assert "fitted-section lever arm" in blocked_visible
    assert "for both directions" in blocked_visible
    assert "Overall reinforced shear assessment: NOT ASSESSED" in blocked_visible
    assert "Required 2023 longitudinal chord faces" in blocked_visible
    assert "Overall reinforced shear assessment: PASS" not in blocked_visible
    assert shear.SHEAR_CIRCULAR_REASON not in blocked_visible

    _select_view(at, "Results Overview")
    overview = next(table.value for table in at.table if "Check" in table.value)
    chord_row = overview.loc[
        overview["Check"] == "Shear longitudinal chords"
    ].iloc[0]
    links_row = overview.loc[overview["Check"] == "Shear with links"].iloc[0]
    assert chord_row["Status"] == "NOT ASSESSED"
    assert chord_row["Result"].endswith(" %")
    assert links_row["Status"] == "NOT ASSESSED"
    assert "PASS" not in {chord_row["Status"], links_row["Status"]}

    _set_and_click(
        at,
        "calculate",
        ("number_input", "shear_vy_fitted_z", 500.0),
    )

    assert not at.exception
    recovered = at.session_state["results"]["shear"]
    assert recovered["component"] == "vx"
    assert recovered["links"]["chord_off"] is not None
    assert recovered["links"]["chord_off"]["z"] == pytest.approx(0.5)
    assert len(recovered["links"]["chord_candidates"]) == 4
    recovered_assessment = recovered["links"]["longitudinal_assessment"]
    assert recovered_assessment["coverage_complete"] is True
    assert recovered_assessment["status"] in {"PASS", "FAIL"}
    assert recovered["assessment_status"] in {"PASS", "FAIL"}


def test_app_unknown_2023_duct_geometry_blocks_no_links_kernel_and_recovers(
    monkeypatch,
):
    original_vrd_c = shear.vrd_c
    calls = []

    def tracked_vrd_c(*args, **kwargs):
        calls.append((args, kwargs))
        return original_vrd_c(*args, **kwargs)

    monkeypatch.setattr(shear, "vrd_c", tracked_vrd_c)
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("selectbox", "shear_duct_case", shear.SHEAR_DUCT_DETAILS_INCOMPLETE),
    )
    _set_and_click(at, "calculate", ("number_input", "shear_V", 50.0))

    assert not at.exception
    assert calls == []
    blocked = at.session_state["results"]["shear"]
    assert blocked["res"]["calculation_state"] == "NOT ASSESSED"
    assert blocked["res"]["vrd_c"] is None
    assert blocked["util"] is None

    _select_view(at, "Shear")
    visible = " ".join(
        item.value
        for collection in (at.warning, at.caption, at.markdown)
        for item in collection
    )
    assert "Enter the duct type and outer diameters" in visible
    assert "No resistance, utilisation or PASS/FAIL verdict" in visible
    assert shear.SHEAR_DUCT_INPUT_REASON not in visible

    _select_view(at, "Results Overview")
    overview = next(table.value for table in at.table if "Check" in table.value)
    row = overview.loc[overview["Check"] == "Shear without links"].iloc[0]
    assert row["Status"] == "NOT ASSESSED"
    assert row["Result"] == "-"

    _set_and_click(
        at,
        "calculate",
        ("selectbox", "shear_duct_case", shear.SHEAR_DUCT_NONE),
    )
    assert not at.exception
    assert calls
    corrected = at.session_state["results"]["shear"]
    assert corrected["res"]["valid"] is True
    assert corrected["res"]["vrd_c"] > 0.0
    assert corrected["util"] is not None


def test_app_variable_width_2023_applies_cosine_and_2005_fails_closed():
    at = _fresh()
    at.run()
    at.session_state["_qs_open"] = True
    at.run()
    _set(at, ("selectbox", "shape", "T-section"))
    _set_and_click(at, "qs_apply")
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("checkbox", "shear_links", True),
        ("selectbox", "shear_section_form", shear.SHEAR_SECTION_VARIABLE),
        ("number_input", "shear_vx_bw", 300.0),
        ("number_input", "shear_vy_bw", 300.0),
        ("number_input", "shear_vx_web_inclination_deg", 60.0),
        ("number_input", "shear_vy_web_inclination_deg", 60.0),
    )
    _set_and_click(at, "calculate", ("number_input", "shear_V", 50.0))

    assert not at.exception
    supported = at.session_state["results"]["shear"]
    assert supported["links"]["res"]["valid"] is True
    assert supported["links"]["asw_factor"] == pytest.approx(0.5)
    assert supported["links"]["effective_asw_over_s"] == pytest.approx(
        supported["links"]["asw_over_s"] * 0.5
    )

    _set_and_click(
        at,
        "calculate",
        ("selectbox", "shear_method", codes.EC2_2005_DKNA.label),
    )
    assert not at.exception
    unsupported = at.session_state["results"]["shear"]
    assert unsupported["res"]["calculation_state"] == "NOT ASSESSED"
    assert unsupported["res"]["vrd_c"] is None
    assert unsupported["links"]["res"]["calculation_state"] == "NOT ASSESSED"
    assert unsupported["links"]["res"]["vrd"] is None

    _select_view(at, "Shear")
    visible = " ".join(
        item.value
        for collection in (at.warning, at.caption, at.markdown)
        for item in collection
    )
    assert "separately applicable member calculation" in visible
    assert shear.SHEAR_SECTION_METHOD_REASON not in visible


def test_app_transverse_detailing_uses_active_direction_and_renders_view():
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "transverse_detailing_on", True),
        ("checkbox", "shear_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 100.0),
    )
    assert not at.exception
    case_result = at.session_state["results"]["plastic_cases"][0]["results"]
    transverse = case_result["transverse_reinforcement"]
    assert transverse["status"] == "PASS"
    assert [check["kind"] for check in transverse["checks"]] == [
        "minimum_ratio",
        "longitudinal_spacing",
        "transverse_leg_spacing",
    ]
    assert (
        transverse["checks"][2]["spacing_source"]
        == "gross-web upper-bound screen"
    )

    _select_view(at, "Detailing")
    assert not at.exception
    assert any(
        "Shear/torsion link detailing" in item.value
        for item in at.markdown
    )


def test_app_vx_gross_depth_screen_does_not_create_a_false_failure():
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "transverse_detailing_on", True),
        ("checkbox", "shear_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_Vx", 100.0),
        ("number_input", "shear_Vy", 0.0),
    )
    assert not at.exception
    case_result = at.session_state["results"]["plastic_cases"][0]["results"]
    transverse = case_result["transverse_reinforcement"]
    spacing = next(
        check for check in transverse["checks"]
        if check["kind"] == "transverse_leg_spacing"
    )
    # Default section: the gross vertical breadth is 600 mm, but no actual
    # Vx-parallel leg spacing was entered. That upper bound cannot prove failure.
    assert spacing["component"] == "vx"
    assert spacing["measurement_axis"] == "y"
    assert spacing["spacing_source"] == "gross-web upper-bound screen"
    assert spacing["provided"] == pytest.approx(600.0, abs=1.0)
    assert spacing["status"] == "NOT ASSESSED"
    assert spacing["utilisation"] is None


def test_app_beam_link_detailing_requires_minimum_links_at_low_shear():
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "transverse_detailing_on", True),
        ("checkbox", "shear_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", False),
        ("number_input", "shear_V", 50.0),
    )
    assert not at.exception
    case_result = at.session_state["results"]["plastic_cases"][0]["results"]
    transverse = case_result["transverse_reinforcement"]
    assert transverse["status"] == "FAIL"
    assert [check["kind"] for check in transverse["checks"]] == [
        "required_links"
    ]
    assert transverse["checks"][0]["clause"] == "9.2.2(2), (5)"
    assert "minimum shear reinforcement" in transverse["checks"][0]["reason"]
    assert at.session_state["shear_links"] is False


def test_app_slab_detailing_exposes_the_modelled_section_cut_direction():
    at = _fresh()
    at.run()
    _set(
        at,
        ("selectbox", "detailing_member_type", detailing.MEMBER_SLAB),
    )
    assert not at.exception
    assert at.selectbox(key="detailing_cut_direction").value == (
        detailing.CUT_TRANSVERSE
    )
    _set(
        at,
        ("selectbox", "detailing_cut_direction", detailing.CUT_LONGITUDINAL),
    )
    assert not at.exception
    assert at.session_state["detailing_member_type"] == detailing.MEMBER_SLAB
    assert at.session_state["detailing_cut_direction"] == (
        detailing.CUT_LONGITUDINAL
    )


def test_app_biaxial_shear_reports_two_directions_without_interaction_claim():
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_Mx", 50.0),
        ("number_input", "pl_My", 50.0),
        ("number_input", "shear_Vx", 1.0),
        ("number_input", "shear_Vy", 1.0),
        ("checkbox", "shear_links", True),
    )

    assert not at.exception
    sh = at.session_state["results"]["shear"]
    assert set(sh["directions"]) == {"vx", "vy"}
    assert "generic_cross_direction_interaction_calculated" not in sh
    assert "status" not in sh
    assert "interaction_assessed" not in sh
    assert "interaction_status" not in sh
    assert sh["directions"]["vx"]["axis"] == "y"
    assert sh["directions"]["vy"]["axis"] == "x"
    assert sh["directions"]["vx"]["links"]["z_component"] == "z_x"
    assert sh["directions"]["vy"]["links"]["z_component"] == "z_y"
    assert {
        sh["directions"][component]["links"]["z_source_case"]
        for component in ("vx", "vy")
    } == {"PL-01"}

    _select_view(at, "Shear")
    summary = next(
        frame.value
        for frame in at.dataframe
        if {"Component", "VEd [kN]", "VRd [kN]", "Utilisation", "Status"}
        .issubset(frame.value.columns)
    ).set_index("Component")
    for component, label in (("vx", "Vx,Ed"), ("vy", "Vy,Ed")):
        direction = sh["directions"][component]
        nominal = direction["nominal_resistance"]
        assert nominal["route"] == "concrete"
        assert summary.loc[label, "VRd [kN]"] == pytest.approx(
            nominal["resistance"]
        )
        assert summary.loc[label, "Utilisation"] == pytest.approx(
            nominal["utilisation"]
        )
        assert summary.loc[label, "Status"] == direction["status"]
        assert summary.loc[label, "VRd [kN]"] != pytest.approx(
            direction["links"]["res"]["vrd"]
        )


def test_app_auto_face_checks_both_sides_when_associated_moment_is_zero():
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_Mx", 0.0),
        ("number_input", "shear_Vy", 1.0),
    )

    assert not at.exception
    vy = at.session_state["results"]["shear"]
    assert vy["component"] == "vy"
    assert "directions" not in vy
    assert vy["both_faces_evaluated"] is True
    assert len(vy["face_candidates"]) == 2
    assert vy["governing_face"] in {"negative", "positive"}
    candidates = vy["face_candidates"]
    governing = max(
        candidates,
        key=lambda item: capacity.assessment_key(
            item["shear_status"], item["shear_metric"]
        ),
    )
    assert vy["status"] == capacity.aggregate_assessment_status(
        item["shear_status"] for item in candidates
    )
    assert vy["governing_face"] == (
        "negative" if governing["tension_low"] else "positive"
    )


def test_legacy_bending_blocks_combined_evidence_in_both_face_shear_view():
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("checkbox", "combined_on", True),
        ("number_input", "pl_Mx", 0.0),
        ("number_input", "shear_Vy", 150.0),
        ("number_input", "torsion_T", 40.0),
    )

    assert not at.exception
    results = at.session_state["results"]
    selected = results["plastic_cases"][0]["results"]
    shear = selected["shear"]
    assert shear["both_faces_evaluated"] is True
    assert shear["governing_domains"].get("combined") is not None

    _select_view(at, "Shear")
    current_candidates = next(
        frame.value
        for frame in at.dataframe
        if {"Face", "Combined status", "Governing domains"}.issubset(
            frame.value.columns
        )
    )
    current_governing = next(
        frame.value
        for frame in at.dataframe
        if {"Check", "Governing face", "Value / utilisation",
            "Status / outcome"}.issubset(frame.value.columns)
    )
    assert current_candidates["Combined status"].tolist() == [
        candidate["combined_status"] for candidate in shear["face_candidates"]
    ]
    assert set(current_candidates["Combined status"]) == {"NOT ASSESSED"}
    assert selected["combined"]["torsion_assessment_status"] == "NOT ASSESSED"
    current_component_rows = current_governing.loc[
        current_governing["Check"].isin(["Shear", "V+T (6.29)"])
    ].reset_index(drop=True)
    current_combined = current_governing.loc[
        current_governing["Check"] == "Combined"
    ]
    assert len(current_combined) == 1
    current_domain = shear["governing_domains"]["combined"]
    current_combined_row = current_combined.iloc[0]
    cot_column = next(
        column for column in current_governing.columns
        if str(column).startswith("cot ")
    )
    expected_face_suffix = (
        "(-y)" if current_domain["face"] == "negative" else "(+y)"
    )
    assert str(current_combined_row["Governing face"]).endswith(
        expected_face_suffix
    )
    assert current_combined_row[cot_column] == pytest.approx(current_domain["cot"])
    assert current_combined_row["Value / utilisation"] == pytest.approx(
        current_domain["util"]
    )
    assert current_combined_row["Status / outcome"] == current_domain["status"]

    root_plastic_before = copy.deepcopy(results["plastic"])
    legacy_selected = copy.deepcopy(selected)
    legacy_selected["plastic"].pop("util_valid")
    face_candidates_before = copy.deepcopy(legacy_selected["shear"]["face_candidates"])
    governing_domains_before = copy.deepcopy(
        legacy_selected["shear"]["governing_domains"]
    )
    results["plastic_cases"][0]["results"] = legacy_selected
    _select_view(at, "Shear")

    legacy_candidates = next(
        frame.value
        for frame in at.dataframe
        if {"Face", "Combined status", "Governing domains"}.issubset(
            frame.value.columns
        )
    )
    legacy_governing = next(
        frame.value
        for frame in at.dataframe
        if {"Check", "Governing face", "Value / utilisation",
            "Status / outcome"}.issubset(frame.value.columns)
    )
    assert set(legacy_candidates["Combined status"]) == {"NOT ASSESSED"}
    assert all(
        "Combined" not in str(value)
        for value in legacy_candidates["Governing domains"]
    )
    legacy_component_rows = legacy_governing.loc[
        legacy_governing["Check"].isin(["Shear", "V+T (6.29)"])
    ].reset_index(drop=True)
    assert legacy_component_rows.to_dict("records") == (
        current_component_rows.to_dict("records")
    )
    legacy_combined = legacy_governing.loc[
        legacy_governing["Check"] == "Combined"
    ]
    assert len(legacy_combined) == 1
    assert legacy_combined.iloc[0]["Governing face"] == "-"
    assert legacy_combined.iloc[0]["Status / outcome"] == "NOT ASSESSED"
    assert math.isnan(float(legacy_combined.iloc[0]["Value / utilisation"]))
    assert any(
        "saved bending result cannot confirm" in item.value.casefold()
        and "contains the origin" in item.value.casefold()
        and "recalculate" in item.value.casefold()
        for item in at.warning
    )
    assert results["plastic"] == root_plastic_before
    assert legacy_selected["shear"]["face_candidates"] == face_candidates_before
    assert legacy_selected["shear"]["governing_domains"] == governing_domains_before


def test_app_linked_shear_governing_uses_the_selected_link_utilisation():
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "pl_Mx", 0.0),
        ("number_input", "shear_Vy", 150.0),
    )

    assert not at.exception
    vy = at.session_state["results"]["shear"]
    assert vy["component"] == "vy"
    assert "directions" not in vy
    candidates = vy["face_candidates"]
    assert len(candidates) == 2
    for candidate in candidates:
        assert candidate["shear_metric"] == pytest.approx(
            candidate["shear"]["links"]["util"]
        )
    governing = max(
        candidates,
        key=lambda item: capacity.assessment_key(
            item["shear_status"], item["shear"]["links"]["util"]
        ),
    )
    assert vy["governing_face"] == (
        "negative" if governing["tension_low"] else "positive"
    )
    assert vy["governing_domains"]["shear"]["util"] == pytest.approx(
        governing["shear"]["links"]["util"]
    )


def test_app_shear_bw_override_is_used():
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("number_input", "shear_bw", 250.0),
        ("number_input", "shear_V", 100.0),
    )
    assert not at.exception
    sh = at.session_state["results"]["shear"]
    assert sh["bw"] == pytest.approx(250.0)
    assert sh["bw_user"]


def test_app_shear_view_renders_and_shows_utilisation():
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(at, "calculate", ("number_input", "shear_V", 80.0))
    _select_view(at, "Shear")
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert any("Utilisation" in lbl for lbl in labels)
    assert any("VRd,c" in lbl or "Resistance" in lbl for lbl in labels)
    captions = " ".join(item.value for item in at.caption)
    assert "2005 no-links resistance has no z operand" in captions
    shear_figure = next(
        json.loads(chart.proto.spec)
        for chart in at.get("plotly_chart")
        if any(
            annotation.get("name") == "shear-d-label"
            for annotation in json.loads(chart.proto.spec)
            .get("layout", {}).get("annotations", [])
        )
    )
    annotation_names = {
        annotation.get("name")
        for annotation in shear_figure["layout"]["annotations"]
    }
    assert "shear-d-label" in annotation_names
    assert "shear-z-label" not in annotation_names


def test_app_shear_axial_input_enabled_in_elastic_mode():
    # In Elastic-only mode the Plastic case table remains editable because its axial
    # force drives shear sigma_cp. Compression (negative N, tension-positive) must
    # raise VRd,c through sigma_cp.
    at = _fresh()
    at.run()
    _set(
        at,
        ("radio", "mode", "Elastic"),
        ("checkbox", "shear_on", True),
    )
    goto_input_stage(at, "Loads")
    assert any(frame.key == "plastic_cases_editor" for frame in at.dataframe)
    _set_and_click(at, "calculate", ("number_input", "shear_V", 50.0))
    assert not at.exception
    base = at.session_state["results"]["shear"]["res"]["vrd_c"]
    _set_and_click(
        at, "calculate", ("number_input", "pl_P", -400.0)
    )  # compression (N tension +)
    assert not at.exception
    comp = at.session_state["results"]["shear"]["res"]
    assert comp["sigma_cp"] > 0.0                          # compression -> positive sigma_cp
    assert comp["vrd_c"] > base                            # ...raises VRd,c


def test_app_shear_links_produce_a_resistance():
    # Enabling links computes the variable-strut VRd = min(VRd,s, VRd,max) alongside
    # VRd,c; the default section (bottom bars at d~550, bw~400) gives a positive VRd.
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set(
        at,
        ("number_input", "shear_V", 200.0),
        ("checkbox", "shear_links", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("number_input", "shear_link_dia", 10.0),
        ("number_input", "shear_link_s", 150.0),
    )
    assert not at.exception
    lk = at.session_state["results"]["shear"]["links"]
    assert lk["res"]["valid"]
    assert lk["res"]["vrd"] > 0.0
    assert lk["res"]["vrd"] == pytest.approx(min(lk["res"]["vrd_s"], lk["res"]["vrd_max"]))
    assert 1.0 <= lk["res"]["cot"] <= 2.5
    assert lk["util"] == pytest.approx(200.0 / lk["res"]["vrd"])


def test_app_shear_links_use_the_plastic_lever_arm():
    # z is the internal lever arm the plastic engine computes (compression-tension
    # resultant separation for bending about the shear axis), not the 0.9d default.
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 100.0),
    )
    assert not at.exception
    sh = at.session_state["results"]["shear"]
    lk = sh["links"]
    assert lk["z_source"] == "plastic internal lever arm"
    assert lk["z_component"] == "z_y"
    assert lk["z_source_angle_deg"] == pytest.approx(270.0)
    assert lk["z_source_case"] == "PL-01"
    z, d = lk["res"]["z"], sh["d"]
    assert 0.6 * d < z < d                    # a real flexural lever arm below d
    _select_view(at, "Shear")
    captions = " ".join(item.value for item in at.caption)
    assert "= |z_y| from PL-01, top (+y) 270" in captions
    assert "used in V_Rd,s and V_Rd,max" in captions


def test_app_links_with_a_degenerate_plastic_arm_are_not_assessed(monkeypatch):
    monkeypatch.setattr(
        capacity,
        "plastic_capacity_at_angle",
        lambda *args, **kwargs: SimpleNamespace(
            converged=True,
            dx=0.0,
            dy=0.0,
        ),
    )
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 100.0),
    )

    assert not at.exception
    links = at.session_state["results"]["shear"]["links"]
    result = links["res"]
    assert result["valid"] is False
    assert result["calculation_state"] == "NOT ASSESSED"
    assert result["z"] is None
    assert result["vrd_s"] is None
    assert result["vrd_max"] is None
    assert result["vrd"] is None
    assert links["util"] is None
    assert links["longitudinal_shear_force"] is None
    assert links["chord"] is None

    _select_view(at, "Shear")
    assert not at.exception
    warnings = " ".join(item.value for item in at.warning)
    assert "NOT ASSESSED" in warnings
    assert "zero or degenerate" in warnings


def test_shear_lever_arm_fails_closed_without_a_section():
    from sector.capacity import shear_lever_arm
    z, src = shear_lever_arm({"section": None}, "x", True, 550.0)
    assert z is None
    assert "section model" in src


def test_app_shear_links_outside_permitted_bounds_are_not_assessed():
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("number_input", "strut_cot_max", 3.0),
        ("number_input", "shear_V", 80.0),
    )
    assert not at.exception
    lk = at.session_state["results"]["shear"]["links"]
    assert lk["out_of_limits"] is True
    assert lk["res"]["valid"] is False
    assert lk["res"]["calculation_state"] == "NOT ASSESSED"
    assert lk["res"]["vrd"] is None
    assert lk["util"] is None
    assert lk["longitudinal_shear_force"] is None
    assert lk["chord"] is None
    assert lk["angle_applicability"]["requested_max"] == 3.0
    assert lk["angle_applicability"]["permitted_max"] == 2.5
    nominal = at.session_state["results"]["shear"]["nominal_resistance"]
    assert nominal["route"] == "concrete"
    assert nominal["status"] == "PASS"
    _select_view(at, "Shear")
    assert not at.exception
    visible = " ".join(
        item.value
        for collection in (at.warning, at.caption, at.markdown)
        for item in collection
    )
    assert "reinforced-shear check is NOT ASSESSED" in visible
    assert "outside the permitted range" in visible
    assert "Requested cot" in visible
    assert "1.000 to 3.000" in visible
    assert not any(
        metric.label == r"Utilisation $V_{Ed}/V_{Rd}$"
        for metric in at.metric
    )

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    concrete_row = overview.loc[
        overview["Check"] == "Shear without links"
    ].iloc[0]
    link_row = overview.loc[overview["Check"] == "Shear with links"].iloc[0]
    assert concrete_row["Status"] == "PASS"
    assert link_row["Status"] == "NOT ASSESSED"
    assert link_row["Result"] == "-"


@pytest.mark.parametrize(
    "method",
    (codes.EC2_2005_DKNA.label, codes.EC2_2023.label),
)
def test_app_angle_gate_cannot_bypass_unavailable_link_arm(monkeypatch, method):
    from sector import capacity

    monkeypatch.setattr(
        capacity,
        "shear_lever_arm",
        lambda *_args, **_kwargs: (
            None,
            "calculated plastic lever arm unavailable: the exact "
            "face-aligned Plastic solve did not converge",
        ),
    )
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("selectbox", "shear_method", method),
        ("number_input", "strut_cot_max", 3.0),
        ("number_input", "shear_V", 80.0),
    )

    assert not at.exception
    shear_result = at.session_state["results"]["shear"]
    links = shear_result["links"]
    assert links["res"]["valid"] is False
    assert links["res"]["calculation_state"] == "NOT ASSESSED"
    assert links["res"]["z"] is None
    assert links["res"]["vrd"] is None
    assert "lever arm" in links["res"]["reason"]
    assert links["util"] is None
    nominal = shear_result["nominal_resistance"]
    assert nominal["valid"] is False
    assert nominal["status"] == "NOT ASSESSED"
    assert nominal["route"] is None
    assert nominal["resistance"] is None
    assert nominal["utilisation"] is None

    _select_view(at, "Shear")
    visible = " ".join(
        item.value
        for collection in (at.warning, at.caption, at.markdown)
        for item in collection
    )
    assert "reinforced-shear check is NOT ASSESSED" in visible
    assert "face-aligned Plastic calculation did not converge" in visible


def test_app_shear_uses_final_material_factors():
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "conc_gamma_c", 1.80),
        ("number_input", "mild_gamma_y", 1.35),
        ("checkbox", "shear_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 100.0),
    )
    assert not at.exception
    sh = at.session_state["results"]["shear"]
    assert sh["res"]["gamma_c"] == pytest.approx(1.80)
    assert sh["res"]["fcd"] == pytest.approx(
        at.session_state["conc_alpha_cc"]
        * at.session_state["conc_fck"] / 1.80
    )
    assert sh["links"]["res"]["gamma_s"] == pytest.approx(1.35)
    assert sh["links"]["res"]["fywd"] == pytest.approx(
        at.session_state["shear_fywk"] / 1.35
    )


def test_app_shear_2023_method_uses_tau_rdc():
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("number_input", "shear_V", 50.0),
    )
    assert not at.exception
    sh = at.session_state["results"]["shear"]
    assert sh["model_2023"]
    assert sh["ddg"] == pytest.approx(32.0)             # default Dlower = 16
    assert sh["res"]["tau_rdc"] > 0.0 and sh["res"]["vrd_c"] > 0.0
    _select_view(at, "Shear")
    assert not at.exception
    captions = " ".join(item.value for item in at.caption)
    assert "Standard-defined arm z" in captions
    assert "0.9d per DS/EN 1992-1-1:2023 8.2.1(3)" in captions


def test_app_shear_2023_fyd_from_yield_parameters():
    # Codex P2: fyd is fytk/gamma_y of the mild steel, not stress() sampled at a
    # fixed strain (which a hardening / low-rupture law would misread).
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("number_input", "shear_V", 50.0),
    )
    sh = at.session_state["results"]["shear"]
    fytk = at.session_state["mild_fytk"]
    gy = at.session_state["mild_gamma_y"]
    assert sh["fyd_flex"] == pytest.approx(fytk / gy)
    assert sh["res"]["fyd"] == pytest.approx(fytk / gy)


def test_app_shear_2023_links_produce_compression_field_result():
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 50.0),
    )
    assert not at.exception
    links = at.session_state["results"]["shear"]["links"]
    assert links["res"]["valid"]
    assert links["model_2023"]
    assert links["res"]["nu"] == pytest.approx(0.5)
    assert links["longitudinal_shear_force"] == pytest.approx(
        50.0 * links["res"]["cot"]
    )
    assert links["delta_ftd"] is None
    _select_view(at, "Shear")
    assert not any("not yet implemented" in m.value for m in at.info)


def test_app_shear_2023_links_with_axial_compression_fail_closed(monkeypatch):
    from sector import capacity
    from sector import combined as combined_core

    def forbidden_lever_arm(*args, **kwargs):
        del args, kwargs
        pytest.fail("the face-aligned Plastic lever-arm solve was entered")

    monkeypatch.setattr(capacity, "shear_lever_arm", forbidden_lever_arm)
    monkeypatch.setattr(
        combined_core,
        "crushing_interaction_result",
        forbidden_lever_arm,
    )
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 50.0),
        ("checkbox", "torsion_on", True),
        ("number_input", "torsion_T", 40.0),
        ("number_input", "pl_P", -200.0),
    )

    assert not at.exception
    links = at.session_state["results"]["shear"]["links"]
    shear_result = at.session_state["results"]["shear"]
    assert shear_result["n_ed"] == pytest.approx(-200.0)
    assert shear_result["n_prestress"] == pytest.approx(0.0)
    assert shear_result["n_ed_comp"] == pytest.approx(200.0)
    assert links["res"]["calculation_state"] == "NOT ASSESSED"
    assert links["res"]["vrd"] is None
    assert links["util"] is None
    assert at.session_state["results"]["shear"]["assessment_status"] == (
        "NOT ASSESSED"
    )
    torsion = at.session_state["results"]["torsion"]
    assert "interaction" not in torsion
    assert torsion["min_reinf"]["status"] == "NOT APPLICABLE"

    _select_view(at, "Shear")
    visible = " ".join(
        item.value
        for collection in (at.warning, at.caption, at.markdown)
        for item in collection
    )
    assert "Net axial compression is present" in visible
    assert "force assigned to the web" in visible
    assert "action-state compression-chord depth" in visible
    assert "Annex G" in visible
    assert "applicability conditions were not demonstrated" not in visible
    assert "V_{Rd,s}" not in visible
    assert "PASS" not in visible
    screening_metric = next(
        metric
        for metric in at.metric
        if "Utilisation" in metric.label and "V_{Rd,c}" in metric.label
    )
    assert screening_metric.value == "20.7 %"
    assert screening_metric.delta == ""
    assert all(metric.delta not in {"OK", "Over limit"} for metric in at.metric)
    assert "non-governing concrete-only context" in visible

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    row = overview.loc[overview["Check"] == "Shear with links"].iloc[0]
    assert row["Status"] == "NOT ASSESSED"
    assert row["Result"] == "-"
    import result_presentation as _presentation

    retained_rows = _presentation.governing_result_rows(
        _presentation.governing_summary_rows(
            _presentation.multi_case_summary_rows(
                at.session_state["_latest_inputs"],
                at.session_state["results"],
            )
        )
    )
    retained_row = next(
        item for item in retained_rows if item["check"] == "Shear with links"
    )
    assert retained_row["view"] == "Shear"
    assert "Net axial compression is present" in retained_row["note"]
    overview_copy = " ".join(item.value for item in at.caption)
    assert "Net axial compression is present" in overview_copy
    assert "Annex G" in overview_copy
    assert "No longitudinal chord action" not in overview_copy


def test_app_prestress_triggers_2023_links_guard_until_exactly_cancelled():
    at = _fresh()
    at.session_state["_qs_open"] = True
    at.run()
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "tnd_n", 4),
        ("number_input", "tnd_a", 1000.0),
    )
    _set_and_click(
        at,
        "calculate",
        ("number_input", "pre_IS", 0.1),
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 50.0),
    )

    assert not at.exception
    first = at.session_state["results"]["shear"]
    assert first["n_prestress"] > 0.0
    assert first["n_ed"] == pytest.approx(0.0)
    assert first["n_ed_comp"] == pytest.approx(first["n_prestress"])
    assert first["links"]["res"]["calculation_state"] == "NOT ASSESSED"

    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_P", first["n_prestress"]),
    )
    cancelled = at.session_state["results"]["shear"]
    assert cancelled["n_ed"] == pytest.approx(first["n_prestress"])
    assert cancelled["n_prestress"] == pytest.approx(first["n_prestress"])
    assert cancelled["n_ed_comp"] == pytest.approx(0.0, abs=1.0e-12)
    assert cancelled["links"]["res"]["valid"] is True
    assert cancelled["links"]["res"]["vrd"] > 0.0


def test_app_shear_2023_class_a_range_is_enforced_and_recovers_at_equality():
    at = _fresh()
    at.run()
    _set(
        at,
        ("selectbox", "transverse_ductility_class", "A"),
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("checkbox", "shear_links", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("number_input", "strut_cot_max", 2.5),
        ("number_input", "shear_V", 100.0),
    )
    links = at.session_state["results"]["shear"]["links"]
    assert links["cot_limit_hi"] == pytest.approx(2.0)
    assert links["out_of_limits"]
    assert links["res"]["valid"] is False
    assert links["res"]["vrd"] is None
    assert links["util"] is None
    assert links["res"]["calculation_state"] == "NOT ASSESSED"
    assert links["angle_applicability"]["permitted_max"] == 2.0

    _set_and_click(
        at,
        "calculate",
        ("number_input", "strut_cot_max", 2.0),
    )
    recovered = at.session_state["results"]["shear"]["links"]
    assert recovered["angle_applicability"]["applicable"] is True
    assert recovered["res"]["valid"] is True
    assert recovered["res"]["vrd"] > 0.0


def test_app_shear_2023_axial_tension_range_uses_net_action_and_exact_boundary():
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("checkbox", "shear_links", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_P", 500.0),
        ("number_input", "shear_V", 100.0),
        ("number_input", "strut_cot_max", 2.5),
    )

    links = at.session_state["results"]["shear"]["links"]
    limits = links["angle_limits"]
    assert limits["axial_tension_applied"] is True
    assert limits["maximum"] == pytest.approx(2.0)
    assert links["angle_applicability"]["requested_max"] == 2.5
    assert links["angle_applicability"]["applicable"] is False
    assert links["res"]["vrd"] is None
    assert links["util"] is None

    _set_and_click(
        at,
        "calculate",
        ("number_input", "strut_cot_max", 2.0),
    )
    recovered = at.session_state["results"]["shear"]["links"]
    assert recovered["angle_applicability"]["applicable"] is True
    assert recovered["res"]["valid"] is True
    assert recovered["res"]["vrd"] > 0.0


def test_app_shear_is_saved_and_restored():
    # The check settings remain scalars; the row-specific action is canonical table
    # data. A project round trip must preserve both without compatibility scalars.
    import project_io
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set(
        at,
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("number_input", "shear_gamma_v", 1.25),
        ("number_input", "strut_cot_max", 3.0),
        ("number_input", "shear_Vx", 123.0),
        ("number_input", "shear_vx_bw", 240.0),
        ("selectbox", "shear_section_form", shear.SHEAR_SECTION_VARIABLE),
        ("number_input", "shear_vx_web_inclination_deg", 12.5),
        ("number_input", "shear_vy_web_inclination_deg", 17.5),
        ("selectbox", "shear_duct_case", shear.SHEAR_DUCT_GROUTED_PLASTIC_THIN),
        ("number_input", "shear_vx_duct_sum", 80.0),
        ("number_input", "shear_vy_duct_sum", 60.0),
        ("number_input", "shear_vx_duct_largest", 40.0),
        ("number_input", "shear_vy_duct_largest", 30.0),
    )
    scalars = {k: at.session_state[k] for k in project_io.SCALAR_KEYS
               if k in at.session_state}
    tables = {k: at.session_state[k] for k in project_io.PROJECT_TABLE_KEYS
              if k in at.session_state}
    assert scalars["shear_on"] is True and "shear_V" not in scalars
    assert first_case_value(at, "shear_Vx") == pytest.approx(123.0)

    at2 = _fresh()
    at2.run()
    at2.session_state["_pending_project"] = project_io.dump_project(tables, scalars)
    at2.run()
    assert not at2.exception
    assert at2.session_state["shear_on"] is True
    assert at2.session_state["shear_method"] == codes.EC2_2023.label
    assert at2.session_state["shear_gamma_v"] == pytest.approx(1.25)
    assert at2.session_state["strut_cot_max"] == pytest.approx(3.0)
    assert first_case_value(at2, "shear_Vx") == pytest.approx(123.0)
    assert at2.session_state["shear_vx_bw"] == pytest.approx(240.0)
    assert at2.session_state["shear_section_form"] == (
        shear.SHEAR_SECTION_VARIABLE
    )
    assert at2.session_state["shear_vx_web_inclination_deg"] == pytest.approx(
        12.5
    )
    assert at2.session_state["shear_vy_web_inclination_deg"] == pytest.approx(
        17.5
    )
    assert at2.session_state["shear_duct_case"] == (
        shear.SHEAR_DUCT_GROUTED_PLASTIC_THIN
    )
    assert at2.session_state["shear_vx_duct_sum"] == pytest.approx(80.0)
    assert at2.session_state["shear_vy_duct_sum"] == pytest.approx(60.0)
    assert at2.session_state["shear_vx_duct_largest"] == pytest.approx(40.0)
    assert at2.session_state["shear_vy_duct_largest"] == pytest.approx(30.0)


# -- Prestress resultants and axial-force effects in shear -------------------

def test_prestress_resultants_helper():
    # The helper reproduces the locked-in tendon force sum(Ep*IS*Ap) and its
    # eccentric moments about the concrete centroid.
    from sector import capacity
    from sector import material_presets as mp
    kw = dict(mp.PRESTRESS_PRESETS["EN 1992-1-1:2005"])
    kw["IS"] = 5.0                                       # permille -> a real prestrain
    pre = mp.build_prestress(**kw)
    assert pre.IS > 0.0
    tendons = [(0.0, -0.40, 1000.0), (0.10, -0.40, 500.0)]   # 1500 mm2 total
    expected = pre.Es * pre.IS * 1000.0 * (1500.0 / 1.0e6)   # kN
    assert expected > 0.0
    p_res, mx_res, my_res = capacity.prestress_resultants(
        {"prestress": pre, "tendons": tendons}, cx=0.0, cy=0.0)
    assert p_res == pytest.approx(expected)
    # Mx = sum(P_i*(y_i-cy)); My = sum(P_i*(x_i-cx)).
    assert mx_res == pytest.approx(-0.40 * expected)
    assert my_res == pytest.approx(expected / 3.0 * 0.10)
    assert capacity.prestress_axial(
        {"prestress": pre, "tendons": tendons}) == pytest.approx(expected)
    # No tendons or no prestress material -> no precompression.
    assert capacity.prestress_resultants(
        {"prestress": pre, "tendons": []}, 0.0, 0.0
    ) == (0.0, 0.0, 0.0)
    assert capacity.prestress_resultants(
        {"prestress": None, "tendons": tendons}, 0.0, 0.0
    ) == (0.0, 0.0, 0.0)

    # Element-specific materials use each tendon's own modulus and initial strain.
    import dataclasses
    pre_2 = dataclasses.replace(pre, Es=180_000.0, IS=0.003)
    expected_forces = [
        pre.Es * pre.IS * 1000.0 * 1000.0 / 1.0e6,
        pre_2.Es * pre_2.IS * 1000.0 * 500.0 / 1.0e6,
    ]
    mixed = capacity.prestress_resultants({
        "prestress": pre,
        "tendons": tendons,
        "tendon_materials": [pre, pre_2],
    })
    assert mixed[0] == pytest.approx(sum(expected_forces))
    assert mixed[1] == pytest.approx(-0.40 * sum(expected_forces))
    assert mixed[2] == pytest.approx(0.10 * expected_forces[1])


def _qs_prestressed_shear(pre_is, *, method=None):
    """A Quick Section rectangle with four tendons and the given prestrain, with
    the shear check enabled. ``pre_is`` in permille (0 = no precompression)."""
    at = _fresh()
    at.session_state["_qs_open"] = True
    at.run()
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "tnd_n", 4),
        ("number_input", "tnd_a", 1000.0),
    )
    _set(
        at,
        ("number_input", "pre_IS", pre_is),
        ("checkbox", "shear_on", True),
    )
    changes = [("number_input", "shear_V", 50.0)]
    if method is not None:
        changes.append(("selectbox", "shear_method", method))
    _set_and_click(at, "calculate", *changes)
    return at


def test_app_shear_prestress_raises_vrd_c():
    # F1: the tendon precompression enters sigma_cp, so VRd,c (and its k1*sigma_cp
    # term) rises versus the same section with no prestrain.
    at = _qs_prestressed_shear(5.0)
    assert not at.exception
    sh = at.session_state["results"]["shear"]
    assert sh["n_prestress"] > 0.0
    assert sh["res"]["sigma_cp"] > 0.0
    vrd_pre = sh["res"]["vrd_c"]

    _set_and_click(at, "calculate", ("number_input", "pre_IS", 0.0))
    sh0 = at.session_state["results"]["shear"]
    assert sh0["n_prestress"] == pytest.approx(0.0)
    assert sh0["res"]["sigma_cp"] == pytest.approx(0.0)
    # Same geometry / reinforcement, only the prestress differs -> higher VRd,c.
    assert vrd_pre > sh0["res"]["vrd_c"] + 1.0
    # The applied axial N is still the external force only (unchanged by prestress).
    assert sh["n_ed"] == pytest.approx(sh0["n_ed"])


def test_app_shear_2023_applies_axial_factor():
    # Formula 8.31 is applied in the app: net tension reduces the basic resistance
    # and net compression increases it.  The former "ignored" warning is obsolete.
    m2023 = codes.EC2_2023.label
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("selectbox", "shear_method", m2023),
        ("number_input", "shear_V", 100.0),
        ("number_input", "pl_Mx", 110.0),
        ("number_input", "pl_P", 0.0),
    )
    neutral = at.session_state["results"]["shear"]["res"]

    _set_and_click(at, "calculate", ("number_input", "pl_P", 200.0))  # tension +
    assert not at.exception
    tension = at.session_state["results"]["shear"]["res"]
    assert tension["k_vp"] > 1.0
    assert tension["tau_basic"] < neutral["tau_basic"]
    _select_view(at, "Shear")
    assert not any("UNCONSERVATIVE" in w.value for w in at.warning)

    # Net compression reverses the effect.
    _set_and_click(at, "calculate", ("number_input", "pl_P", -200.0))
    compression = at.session_state["results"]["shear"]["res"]
    assert compression["k_vp"] < 1.0
    assert compression["tau_basic"] > neutral["tau_basic"]


def test_app_gamma_v_control_has_the_exact_2023_scope_and_references():
    at = _fresh()
    at.run()

    gamma = at.number_input(key="shear_gamma_v")
    assert gamma.value == pytest.approx(1.40)
    assert gamma.disabled is True
    for reference in (
        "DS/EN 1992-1-1:2023",
        "4.3.3",
        "Table 4.3 (NDP)",
        "8.2.2",
    ):
        assert reference in gamma.help

    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
    )
    assert at.number_input(key="shear_gamma_v").disabled is False

    _set(at, ("checkbox", "shear_links", True))
    assert at.number_input(key="shear_gamma_v").disabled is False
    _set(at, ("checkbox", "shear_links", False))
    assert at.number_input(key="shear_gamma_v").disabled is False

    _set_and_click(
        at,
        "calculate",
        ("number_input", "shear_gamma_v", 1.25),
        ("number_input", "shear_V", 100.0),
    )
    result = at.session_state["results"]["shear"]["res"]
    assert result["gamma_v"] == pytest.approx(1.25)

    _goto_page(at, "Inputs")
    _set(
        at,
        ("selectbox", "shear_method", codes.EC2_2005_DKNA.label),
    )
    assert at.number_input(key="shear_gamma_v").disabled is True


def test_app_gamma_v_change_marks_results_stale_and_recalculates():
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("number_input", "shear_V", 100.0),
    )
    _calculate(at)
    old_signature = at.session_state["result_sig"]
    default = at.session_state["results"]["shear"]["res"]["vrd_c"]

    _goto_page(at, "Inputs")
    _set(at, ("number_input", "shear_gamma_v", 1.25))
    assert at.session_state["_latest_inputs"]["signature"] != old_signature
    assert at.session_state["result_sig"] == old_signature

    _calculate(at)
    selected = at.session_state["results"]["shear"]["res"]
    assert selected["gamma_v"] == pytest.approx(1.25)
    assert selected["vrd_c"] == pytest.approx(default * 1.40 / 1.25)


def test_app_gamma_v_is_absent_from_the_2005_result_signature():
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("number_input", "shear_V", 100.0),
    )
    _calculate(at)
    old_signature = at.session_state["result_sig"]
    old_resistance = at.session_state["results"]["shear"]["res"]["vrd_c"]

    at.session_state["shear_gamma_v"] = 9.00
    at.run()

    assert at.session_state["_latest_inputs"]["signature"] == old_signature
    assert at.session_state["result_sig"] == old_signature
    assert at.session_state["results"]["shear"]["res"]["vrd_c"] == pytest.approx(
        old_resistance
    )


def test_app_gamma_v_remains_active_for_2023_sparse_links():
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("number_input", "shear_gamma_v", 1.80),
        ("number_input", "shear_V", 10.0),
        ("checkbox", "shear_links", True),
    )

    assert at.number_input(key="shear_gamma_v").disabled is False
    _calculate(at)

    assert not at.exception
    result = at.session_state["results"]["shear"]
    assert result["res"]["gamma_v"] == pytest.approx(1.80)
    assert result["links"] is not None
    assert result["nominal_resistance"]["route"] == "concrete"
    high_gamma_resistance = result["res"]["vrd_c"]
    old_signature = at.session_state["result_sig"]

    _goto_page(at, "Inputs")
    _set(at, ("number_input", "shear_gamma_v", 1.25))

    assert at.session_state["_latest_inputs"]["signature"] != old_signature
    assert at.session_state["result_sig"] == old_signature

    _calculate(at)
    recalculated = at.session_state["results"]["shear"]
    assert recalculated["res"]["gamma_v"] == pytest.approx(1.25)
    assert recalculated["res"]["vrd_c"] == pytest.approx(
        high_gamma_resistance * 1.80 / 1.25
    )
    assert recalculated["nominal_resistance"]["route"] == "concrete"

    _select_view(at, "Shear")
    visible = " ".join(
        str(item.value)
        for collection in (at.caption, at.warning, at.error, at.markdown)
        for item in collection
    )
    assert "no shear-induced longitudinal chord force is applied" in visible
    assert "is applied to both flexural chords" not in visible


@pytest.mark.parametrize("unsafe_gamma_v", (0.0, 1e-309))
@pytest.mark.parametrize("links_selected", (False, True))
def test_app_rejects_unsafe_active_gamma_v_before_a_shear_result(
    unsafe_gamma_v,
    links_selected,
):
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("number_input", "shear_gamma_v", unsafe_gamma_v),
        ("number_input", "shear_V", 100.0),
        ("checkbox", "shear_links", links_selected),
    )

    _calculate(at)

    assert not at.exception
    assert any(
        "gamma_V must be a positive finite real number" in item.value
        for item in at.error
    )
    assert "shear" not in at.session_state.filtered_state.get("results", {})
