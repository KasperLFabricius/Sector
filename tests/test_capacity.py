"""Headless orchestration tests for member shear, torsion and M-V-T checks."""

from __future__ import annotations

import ast
import math
import pathlib
from types import SimpleNamespace

import pytest

from sector import capacity, codes, torsion


def _rect(b=0.3, h=0.6):
    return [(0.0, 0.0), (b, 0.0), (b, h), (0.0, h)]


def _materials():
    concrete = SimpleNamespace(fck=35.0, fcd=35.0 / 1.45, gamma_c=1.45)
    steel = SimpleNamespace(fytk=550.0, gamma_y=1.20)
    return concrete, steel


def _member_input(**overrides):
    concrete, steel = _materials()
    inp = {
        "outer": _rect(),
        "holes": [],
        "bars": [(0.05, 0.05, 1473.0)],
        "section": object(),
        "concrete": concrete,
        "steel": steel,
        "prestress": None,
        "tendons": [],
        "P_pl": 0.0,
        "Mx_pl": 100.0,
        "My_pl": 0.0,
        "shear_on": True,
        "shear_method": codes.EC2_2005_DKNA.label,
        "shear_axis": "x",
        "shear_tension": True,
        "shear_bw": 0.0,
        "shear_dlower": 16.0,
        "shear_V": 75.0,
        "shear_links": False,
        "strut_cot_min": 1.0,
        "strut_cot_max": 2.5,
        "shear_link_legs": 2,
        "shear_link_dia": 10.0,
        "shear_link_s": 150.0,
        "shear_fywk": 550.0,
        "torsion_on": False,
        "torsion_method": codes.EC2_2005_DKNA.label,
        "torsion_tef": 0.0,
        "torsion_nu_v": False,
        "torsion_gamma_ct": codes.EC2_2005_DKNA.gamma_ct,
        "torsion_T": 40.0,
        "torsion_subdivide": False,
        "torsion_subrects": [],
        "combined_on": False,
        "combined_method": "DS/EN 1992-1-1 + DK NA",
        "combined_mv_independent": False,
    }
    inp.update(overrides)
    return inp


def test_capacity_module_has_no_ui_dependency():
    """Engineering orchestration must remain importable without Streamlit."""
    source = pathlib.Path(capacity.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert not any(name == "streamlit" or name.startswith("streamlit.") for name in imports)


def _torsion_cracking_result(method, gamma_ct, demand=28.0):
    ctx = capacity.build_torsion_context(
        _member_input(
            torsion_on=True,
            torsion_method=method,
            torsion_gamma_ct=gamma_ct,
            torsion_T=demand,
        ),
        0.0,
    )
    result = capacity.tube_torsion(
        ctx["tube"], ctx["t_ed"], **ctx["_tk"]
    )
    return ctx, result


def test_torsion_method_defaults_keep_distinct_tensile_factors():
    assert codes.EC2_2005.gamma_ct == pytest.approx(1.50)
    assert codes.EC2_2005_DKNA.gamma_ct == pytest.approx(1.70)

    en_ctx, en = _torsion_cracking_result(
        codes.EC2_2005.label, codes.EC2_2005.gamma_ct
    )
    dk_ctx, dk = _torsion_cracking_result(
        codes.EC2_2005_DKNA.label, codes.EC2_2005_DKNA.gamma_ct
    )

    assert en_ctx["gamma_ct"] == pytest.approx(1.50)
    assert dk_ctx["gamma_ct"] == pytest.approx(1.70)
    assert en["trd_c"] == pytest.approx(29.959649455822216)
    assert dk["trd_c"] == pytest.approx(26.434984813960778)


@pytest.mark.parametrize("gamma_ct", [0.5, 2.0])
def test_torsion_uses_positive_custom_tensile_factor_unchanged(gamma_ct):
    ctx, result = _torsion_cracking_result(
        codes.EC2_2005_DKNA.label, gamma_ct
    )
    expected_fctk = 0.7 * codes.fctm(35.0)

    assert ctx["gamma_ct"] == pytest.approx(gamma_ct)
    assert ctx["fctk_005"] == pytest.approx(expected_fctk)
    assert ctx["fctd"] == pytest.approx(expected_fctk / gamma_ct)
    assert result["trd_c"] == pytest.approx(
        torsion.trd_c(expected_fctk / gamma_ct, 0.1, 100.0)
    )


@pytest.mark.parametrize(
    "value", [True, False, 0.0, -1.0, math.inf, -math.inf, math.nan, "1.70"]
)
def test_torsion_rejects_only_malformed_or_nonpositive_tensile_factors(value):
    with pytest.raises(ValueError, match="positive finite real"):
        _torsion_cracking_result(codes.EC2_2005_DKNA.label, value)


def test_dk_tensile_factor_prevents_between_threshold_false_pass():
    demand = 28.0
    ctx, result = _torsion_cracking_result(
        codes.EC2_2005_DKNA.label,
        codes.EC2_2005_DKNA.gamma_ct,
        demand=demand,
    )
    legacy_gamma_c_result = torsion.trd_c(
        ctx["fctk_005"] / 1.45,
        ctx["tube"]["Ak"],
        ctx["tube"]["tef"],
    )

    assert result["trd_c"] == pytest.approx(26.434984813960778)
    assert legacy_gamma_c_result == pytest.approx(30.992740816367807)
    assert demand > result["trd_c"]
    assert demand < legacy_gamma_c_result


def test_build_shear_context_returns_payload_without_ui():
    inp = _member_input()
    payload, links = capacity.build_shear_context(inp, 0.0, 0.0)
    assert links is None
    assert payload["res"]["valid"]
    assert payload["axis"] == "x"
    assert payload["bw"] == pytest.approx(300.0)
    assert payload["d"] == pytest.approx(550.0)
    assert payload["asl"] == pytest.approx(1473.0)
    assert payload["centroid"] == pytest.approx((0.15, 0.30))


def test_2023_shear_context_propagates_axial_tension_angle_limit_and_final_fcd():
    inp = _member_input(
        shear_method=codes.EC2_2023.label,
        shear_links=True,
        transverse_ductility_class="B",
    )
    _payload, links = capacity.build_shear_context(
        inp,
        n_prestress=0.0,
        n_ed_comp=-400.0,
    )

    assert links is not None and links["model_2023"]
    assert links["angle_limits"]["axial_tension_applied"]
    assert links["angle_limits"]["maximum"] == pytest.approx(
        max(2.5 - 0.1 * 400.0 / inp["shear_V"], 1.0)
    )
    result = links["build"](1.0, links["angle_limits"]["maximum"])
    assert result["valid"]
    assert result["fcd"] == pytest.approx(inp["concrete"].fcd)


def test_directional_shear_contexts_map_components_moments_faces_and_settings():
    inp = _member_input(
        bars=[
            (0.05, 0.30, 500.0),   # left
            (0.25, 0.30, 800.0),   # right
            (0.15, 0.05, 1400.0),  # bottom
            (0.15, 0.55, 300.0),   # top
        ],
        Mx_pl=100.0,
        My_pl=-80.0,
        shear_Vx=40.0,
        shear_Vy=50.0,
        shear_face_x="auto",
        shear_face_y="auto",
        shear_vx_bw=210.0,
        shear_vy_bw=260.0,
        shear_vx_link_legs=3.0,
        shear_vy_link_legs=4.0,
    )

    contexts = capacity.build_directional_shear_contexts(inp, 0.0, 0.0)
    vx_payload, _ = contexts["vx"]["candidates"][0]
    vy_payload, _ = contexts["vy"]["candidates"][0]

    assert vx_payload["axis"] == "y"          # depth along x; paired with My
    assert vx_payload["tension_low"] is False  # negative My -> right (+x)
    assert vx_payload["asl"] == pytest.approx(800.0)
    assert vx_payload["bw"] == pytest.approx(210.0)
    assert vy_payload["axis"] == "x"          # depth along y; paired with Mx
    assert vy_payload["tension_low"] is True   # positive Mx -> bottom (-y)
    assert vy_payload["asl"] == pytest.approx(1400.0)
    assert vy_payload["bw"] == pytest.approx(260.0)
    assert vx_payload["res"]["vrd_c"] != pytest.approx(
        vy_payload["res"]["vrd_c"]
    )


def test_auto_face_checks_both_faces_at_zero_moment_and_override_is_explicit():
    assert capacity.shear_face_candidates("auto", 10.0) == (True,)
    assert capacity.shear_face_candidates("auto", -10.0) == (False,)
    assert capacity.shear_face_candidates("auto", 0.0) == (True, False)
    assert capacity.shear_face_candidates("negative", -10.0) == (True,)
    assert capacity.shear_face_candidates("positive", 10.0) == (False,)
    with pytest.raises(ValueError, match="shear face"):
        capacity.shear_face_candidates("sideways", 0.0)


def test_auto_face_uses_centroid_adjusted_moment_not_origin_moment():
    inp = _member_input(
        # The concrete centroid is y = 0.30 m. The positive 10 kNm origin
        # moment becomes +40 kNm at the centroid under 100 kN tension.
        P_pl=100.0,
        Mx_pl=10.0,
        My_pl=0.0,
        # The normal table path also carries an explicit signed component; it is
        # authoritative even if a compatibility scalar contains only magnitude.
        shear_Vy=25.0,
        shear_components={"vy": {"signed_v_ed": -25.0}},
        shear_face_y="auto",
    )
    spec = capacity.shear_direction_specs(inp)["vy"]

    assert spec["moment_origin"] == pytest.approx(10.0)
    assert spec["moment"] == pytest.approx(40.0)
    assert spec["signed_v_ed"] == pytest.approx(-25.0)
    assert spec["v_ed"] == pytest.approx(25.0)
    assert capacity.shear_face_candidates(spec["face"], spec["moment"]) == (True,)

    contexts = capacity.build_directional_shear_contexts(
        inp, n_prestress=0.0, n_ed_comp=-100.0
    )
    payload, _links = contexts["vy"]["candidates"][0]
    assert payload["m_ed_2023"] == pytest.approx(40.0)


def test_mandatory_faces_are_governed_independently_for_shear_and_combined():
    candidates = [
        {
            "shear_status": "FAIL", "shear_metric": 1.05,
            "combined_status": "PASS", "combined_metric": 0.80,
        },
        {
            "shear_status": "PASS", "shear_metric": 0.70,
            "combined_status": "FAIL", "combined_metric": 1.20,
        },
    ]
    shear_governing = max(
        candidates,
        key=lambda item: capacity.assessment_key(
            item["shear_status"], item["shear_metric"]
        ),
    )
    combined_governing = max(
        candidates,
        key=lambda item: capacity.assessment_key(
            item["combined_status"], item["combined_metric"]
        ),
    )

    assert shear_governing is candidates[0]
    assert combined_governing is candidates[1]
    assert capacity.aggregate_assessment_status(
        item["shear_status"] for item in candidates
    ) == "FAIL"
    assert capacity.aggregate_assessment_status(
        item["combined_status"] for item in candidates
    ) == "FAIL"


def test_build_torsion_context_accepts_exact_partition_and_rejects_gap():
    valid = _member_input(
        torsion_on=True,
        torsion_subdivide=True,
        torsion_subrects=[(150.0, 300.0, 300.0, 600.0)],
    )
    ctx = capacity.build_torsion_context(valid, 0.0)
    assert ctx["subdivision_requested"]
    assert ctx["subdivision_valid"]
    assert ctx["subdivide"]
    assert ctx["sub_dims"] == [(150.0, 300.0, 300.0, 600.0)]

    invalid = dict(valid)
    invalid["torsion_subrects"] = [(150.0, 300.0, 290.0, 600.0)]
    bad = capacity.build_torsion_context(invalid, 0.0)
    assert not bad["subdivision_valid"]
    assert not bad["subdivide"]
    assert not bad["tube"]["valid"]
    assert "invalid sub-tube partition" in bad["tube"]["reason"]


def test_build_torsion_context_rejects_closed_concave_ring_started_at_reentrant_corner():
    concave = [
        (0.1, 0.1),
        (0.1, 0.2),
        (0.0, 0.2),
        (0.0, 0.0),
        (0.2, 0.0),
        (0.2, 0.1),
    ]
    closed = [*concave, concave[0]]

    ctx = capacity.build_torsion_context(
        _member_input(torsion_on=True, outer=closed),
        0.0,
    )

    assert ctx["compound_detected"] is True
    assert ctx["tube"]["valid"] is False
    assert ctx["tube"]["reason"] == "compound outline requires subdivision"


def test_finalize_combined_builds_valid_payload():
    inp = _member_input(combined_on=True)
    out = {
        "plastic": {"util": 0.20},
        "shear": {"res": {"valid": True}, "util": 0.30},
        "torsion": {
            "valid": True,
            "util": 0.40,
            "interaction": None,
            "asl_req": 125.0,
            "asw_over_s": 0.0,
        },
    }
    capacity.finalize_combined(inp, out)
    result = out["combined"]
    assert result["valid"]
    assert result["dkna_sum"] == pytest.approx(0.90)
    assert result["dkna_ok"]
    assert result["r_m"] == pytest.approx(0.20)
    assert result["r_v"] == pytest.approx(0.30)
    assert result["r_t"] == pytest.approx(0.40)


def test_finalize_combined_discloses_missing_component():
    inp = _member_input(combined_on=True)
    out = {
        "plastic": {"util": 0.20},
        "shear": {"res": {"valid": True}, "util": 0.30},
    }
    capacity.finalize_combined(inp, out)
    assert out["combined"] == {
        "valid": False,
        "have_m": True,
        "have_v": True,
        "have_t": False,
        "method": inp["combined_method"],
    }


def test_finalize_combined_preserves_every_longitudinal_candidate():
    inp = _member_input(combined_on=True)
    fallback = {
        "valid": True, "util": 0.40, "axis": "x",
        "tension_low": True, "conditional": False,
    }
    exact = {
        "valid": True, "util": 0.60, "axis": "x",
        "tension_low": False, "conditional": True,
    }
    out = {
        "plastic": {"util": 0.20},
        "shear": {
            "res": {"valid": True, "vrd_c": 100.0},
            "links": {
                "res": {"valid": True, "vrd_s": 100.0, "vrd_max": 200.0,
                        "cot": 1.5},
                "util": 0.30,
                "delta_ftd": 15.0,
                "chord": exact,
                "chord_candidates": [fallback, exact],
            },
            "v_ed": 30.0,
        },
        "torsion": {
            "valid": True,
            "util": 0.40,
            "interaction": None,
            "asl_req": 125.0,
            "asw_over_s": 0.0,
        },
    }

    capacity.finalize_combined(inp, out)

    assert out["combined"]["longitudinal"] is exact
    assert out["combined"]["longitudinal_candidates"] == [fallback, exact]
