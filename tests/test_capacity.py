"""Headless orchestration tests for member shear, torsion and M-V-T checks."""

from __future__ import annotations

import ast
import dataclasses
import math
import pathlib
from types import SimpleNamespace

import numpy as np
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
        "combined_method": codes.EC2_2005_DKNA.label,
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


def _prestress_law(*, modulus_mpa=200_000.0, initial_strain=0.005):
    return SimpleNamespace(Es=modulus_mpa, IS=initial_strain)


def test_locked_in_prestress_result_retains_exact_tendon_terms_and_totals():
    first = _prestress_law()
    second = _prestress_law(modulus_mpa=180_000.0, initial_strain=0.003)
    inp = {
        "prestress": first,
        "tendons": [(0.0, -0.40, 1000.0), (0.10, -0.20, 500.0)],
        "tendon_materials": [first, second],
        "tendon_elements": [{"id": "PT-A"}, {"id": "PT-B"}],
    }

    result = capacity.locked_in_prestress_result(inp, cx=0.02, cy=-0.05)
    forces = (
        first.Es * first.IS * 1000.0 * 1000.0 / 1.0e6,
        second.Es * second.IS * 1000.0 * 500.0 / 1.0e6,
    )

    assert dataclasses.is_dataclass(result)
    assert not hasattr(result, "__dict__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.total_n_kn = 0.0
    assert result.origin_x_m == 0.02
    assert result.origin_y_m == -0.05
    assert [(row.tendon_index, row.element_id) for row in result.tendons] == [
        (0, "PT-A"),
        (1, "PT-B"),
    ]
    assert result.tendons[0].initial_strain == first.IS
    assert result.tendons[0].modulus_mpa == first.Es
    assert result.tendons[0].locked_in_stress_mpa == first.Es * first.IS
    assert result.tendons[0].area_mm2 == 1000.0
    assert result.tendons[0].x_m == 0.0
    assert result.tendons[0].y_m == -0.40
    assert [row.force_kn for row in result.tendons] == pytest.approx(forces)
    assert result.total_n_kn == sum(row.force_kn for row in result.tendons)
    assert result.total_mx_knm == sum(row.mx_knm for row in result.tendons)
    assert result.total_my_knm == sum(row.my_knm for row in result.tendons)
    assert capacity.prestress_resultants(inp, 0.02, -0.05) == result.resultants


@pytest.mark.parametrize(
    "inp",
    [
        {"prestress": _prestress_law(), "tendons": []},
        {
            "prestress": None,
            "tendons": [(0.0, -0.40, 1000.0)],
            "tendon_materials": [],
        },
    ],
)
def test_locked_in_prestress_result_preserves_empty_state(inp):
    result = capacity.locked_in_prestress_result(inp, cx=0.12, cy=-0.34)

    assert result.origin_x_m == 0.12
    assert result.origin_y_m == -0.34
    assert result.tendons == ()
    assert result.resultants == (0.0, 0.0, 0.0)
    assert capacity.prestress_resultants(inp, 0.12, -0.34) == result.resultants


def test_locked_in_prestress_result_translates_moments_with_origin():
    material = _prestress_law()
    inp = {
        "prestress": material,
        "tendons": [(-0.15, -0.30, 750.0), (0.20, 0.10, 500.0)],
    }
    at_zero = capacity.locked_in_prestress_result(inp)
    shifted = capacity.locked_in_prestress_result(inp, cx=0.04, cy=-0.07)

    assert [row.element_id for row in shifted.tendons] == [
        "tendon 1",
        "tendon 2",
    ]
    assert shifted.total_n_kn == at_zero.total_n_kn
    assert shifted.total_mx_knm == pytest.approx(
        at_zero.total_mx_knm - shifted.total_n_kn * shifted.origin_y_m
    )
    assert shifted.total_my_knm == pytest.approx(
        at_zero.total_my_knm - shifted.total_n_kn * shifted.origin_x_m
    )
    for original, translated in zip(at_zero.tendons, shifted.tendons):
        assert translated.mx_knm == pytest.approx(
            original.mx_knm - original.force_kn * shifted.origin_y_m
        )
        assert translated.my_knm == pytest.approx(
            original.my_knm - original.force_kn * shifted.origin_x_m
        )


def test_capacity_method_registries_preserve_exact_identity_and_order():
    assert tuple(capacity.SHEAR_METHODS) == (
        codes.EC2_2005_DKNA.label,
        codes.EC2_2005.label,
        codes.EC2_2023.label,
    )
    assert tuple(capacity.SHEAR_CODES) == (
        codes.EC2_2005_DKNA.label,
        codes.EC2_2005.label,
    )
    for label, code in capacity.SHEAR_METHODS.items():
        assert capacity.selected_shear_code(label) is code
    for label, code in capacity.SHEAR_CODES.items():
        assert capacity.selected_torsion_code(label) is code
        assert capacity.selected_combined_code(label) is code


@pytest.mark.parametrize(
    "resolver",
    [
        capacity.selected_shear_code,
        capacity.selected_torsion_code,
        capacity.selected_combined_code,
    ],
)
@pytest.mark.parametrize(
    "invalid",
    [
        None,
        "",
        "unsupported method",
        True,
        1,
        [],
        np.bool_(True),
        np.str_(codes.EC2_2005_DKNA.label),
    ],
)
def test_capacity_method_resolvers_reject_every_unretained_identity(
    resolver,
    invalid,
):
    with pytest.raises(capacity.CapacityMethodError, match="unsupported"):
        resolver(invalid)


@pytest.mark.parametrize("invalid", [None, "", "unsupported method", True, []])
def test_active_capacity_methods_fail_before_geometry_or_mechanics(
    monkeypatch,
    invalid,
):
    def geometry_was_reached(_inp):
        raise AssertionError("geometry must not run before method validation")

    monkeypatch.setattr(
        capacity,
        "_require_valid_input_geometry",
        geometry_was_reached,
    )
    with pytest.raises(capacity.CapacityMethodError, match="shear method"):
        capacity.build_shear_context(
            _member_input(shear_method=invalid), 0.0, 0.0
        )
    with pytest.raises(capacity.CapacityMethodError, match="shear method"):
        capacity.build_directional_shear_contexts(
            _member_input(
                shear_method=invalid,
                shear_Vx=10.0,
                shear_Vy=10.0,
            ),
            0.0,
            0.0,
        )
    with pytest.raises(capacity.CapacityMethodError, match="torsion method"):
        capacity.build_torsion_context(
            _member_input(torsion_on=True, torsion_method=invalid),
            0.0,
        )
    with pytest.raises(capacity.CapacityMethodError, match="combined method"):
        capacity.finalize_combined(
            _member_input(combined_on=True, combined_method=invalid),
            {},
        )


def test_inactive_capacity_families_leave_optional_method_identity_inert():
    inp = _member_input(
        shear_on=False,
        shear_method="unsupported method",
        torsion_on=False,
        torsion_method="unsupported method",
        combined_on=False,
        combined_method="unsupported method",
    )
    assert capacity.build_shear_context(inp, 0.0, 0.0) == (None, None)
    assert capacity.build_directional_shear_contexts(inp, 0.0, 0.0) == {}
    assert capacity.build_torsion_context(inp, 0.0) is None
    out = {}
    assert capacity.finalize_combined(inp, out) is None
    assert out == {}


def _plastic_point(**overrides):
    values = {
        "converged": True,
        "dx": 0.25,
        "dy": 0.20,
        "Mx": 120.0,
        "My": 80.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_shear_lever_arm_preserves_finite_and_expected_fallback_states(
    monkeypatch,
):
    inp = _member_input()
    monkeypatch.setattr(
        capacity,
        "plastic_capacity_at_angle",
        lambda *args, **kwargs: _plastic_point(dy=0.20),
    )
    assert capacity.shear_lever_arm(inp, "x", True, 550.0) == (
        200.0,
        "plastic internal lever arm",
    )

    monkeypatch.setattr(
        capacity,
        "plastic_capacity_at_angle",
        lambda *args, **kwargs: _plastic_point(
            converged=False,
            dy=math.nan,
        ),
    )
    assert capacity.shear_lever_arm(inp, "x", True, 550.0) == (
        pytest.approx(495.0),
        "0.9 d (fallback)",
    )


@pytest.mark.parametrize(
    "depth",
    [True, -1.0, math.nan, math.inf, -math.inf, "550", 10 ** 4000],
)
def test_shear_lever_arm_rejects_malformed_fallback_depth(depth):
    with pytest.raises(capacity.CapacityInputError, match="non-negative finite"):
        capacity.shear_lever_arm(
            _member_input(section=None),
            "x",
            True,
            depth,
        )


def test_shear_lever_arm_retains_zero_fallback_depth():
    assert capacity.shear_lever_arm(
        _member_input(section=None),
        "x",
        True,
        0.0,
    ) == (0.0, "0.9 d (fallback)")


def test_shear_lever_arm_propagates_unexpected_solver_fault(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("lever solve blew up")

    monkeypatch.setattr(capacity, "plastic_capacity_at_angle", boom)
    with pytest.raises(RuntimeError, match="lever solve blew up"):
        capacity.shear_lever_arm(_member_input(), "x", True, 550.0)


@pytest.mark.parametrize("converged", [None, 0, 1, np.bool_(True)])
def test_shear_lever_arm_rejects_malformed_convergence_state(
    monkeypatch,
    converged,
):
    monkeypatch.setattr(
        capacity,
        "plastic_capacity_at_angle",
        lambda *args, **kwargs: _plastic_point(converged=converged),
    )
    with pytest.raises(capacity.CapacityResultError, match="Boolean"):
        capacity.shear_lever_arm(_member_input(), "x", True, 550.0)


@pytest.mark.parametrize("lever", [math.nan, math.inf, -math.inf, "bad"])
def test_shear_lever_arm_rejects_nonfinite_converged_result(
    monkeypatch,
    lever,
):
    monkeypatch.setattr(
        capacity,
        "plastic_capacity_at_angle",
        lambda *args, **kwargs: _plastic_point(dy=lever),
    )
    with pytest.raises(capacity.CapacityResultError, match="finite real"):
        capacity.shear_lever_arm(_member_input(), "x", True, 550.0)


@pytest.mark.parametrize(
    "point",
    [
        None,
        SimpleNamespace(dy=0.20),
        SimpleNamespace(converged=True),
    ],
)
def test_shear_lever_arm_rejects_missing_solver_members(monkeypatch, point):
    monkeypatch.setattr(
        capacity,
        "plastic_capacity_at_angle",
        lambda *args, **kwargs: point,
    )
    with pytest.raises(capacity.CapacityResultError, match="missing returned"):
        capacity.shear_lever_arm(_member_input(), "x", True, 550.0)


@pytest.mark.parametrize(
    ("axis", "tension_low"),
    [("z", True), ([], True), ("x", 1), ("x", np.bool_(True))],
)
def test_capacity_face_identity_rejects_wrong_axis_or_retained_type(
    axis,
    tension_low,
):
    with pytest.raises(capacity.CapacityInputError, match="face identity"):
        capacity.shear_lever_arm(
            _member_input(), axis, tension_low, 550.0
        )


def test_shear_face_mrd_preserves_conditional_and_pure_axis_states(
    monkeypatch,
):
    inp = _member_input()
    monkeypatch.setattr(
        capacity,
        "conditional_capacity",
        lambda *args, **kwargs: (75.0, True),
    )
    assert capacity.shear_face_mrd(inp, "x", True, 25.0) == (75.0, True)

    monkeypatch.setattr(
        capacity,
        "conditional_capacity",
        lambda *args, **kwargs: (0.0, True),
    )
    assert capacity.shear_face_mrd(inp, "x", True, 25.0) == (0.0, True)

    monkeypatch.setattr(
        capacity,
        "conditional_capacity",
        lambda *args, **kwargs: (0.0, False),
    )
    monkeypatch.setattr(
        capacity,
        "plastic_capacity_at_angle",
        lambda *args, **kwargs: _plastic_point(Mx=-120.0),
    )
    assert capacity.shear_face_mrd(inp, "x", True, 25.0) == (
        120.0,
        False,
    )

    monkeypatch.setattr(
        capacity,
        "plastic_capacity_at_angle",
        lambda *args, **kwargs: _plastic_point(
            converged=False,
            Mx=math.nan,
        ),
    )
    assert capacity.shear_face_mrd(inp, "x", True, 25.0) == (0.0, False)


def test_shear_face_mrd_propagates_both_unexpected_solver_faults(monkeypatch):
    inp = _member_input()

    def conditional_boom(*args, **kwargs):
        raise RuntimeError("conditional solve blew up")

    monkeypatch.setattr(capacity, "conditional_capacity", conditional_boom)
    with pytest.raises(RuntimeError, match="conditional solve blew up"):
        capacity.shear_face_mrd(inp, "x", True, 25.0)

    monkeypatch.setattr(
        capacity,
        "conditional_capacity",
        lambda *args, **kwargs: (0.0, False),
    )

    def pure_axis_boom(*args, **kwargs):
        raise RuntimeError("pure-axis solve blew up")

    monkeypatch.setattr(
        capacity,
        "plastic_capacity_at_angle",
        pure_axis_boom,
    )
    with pytest.raises(RuntimeError, match="pure-axis solve blew up"):
        capacity.shear_face_mrd(inp, "x", True, 25.0)


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        [0.0, False],
        (0.0,),
        (0.0, False, "extra"),
        (-1.0, True),
        (math.nan, True),
        (math.inf, True),
        (1.0, False),
        (0.0, np.bool_(True)),
    ],
)
def test_shear_face_mrd_rejects_malformed_conditional_result(
    monkeypatch,
    candidate,
):
    monkeypatch.setattr(
        capacity,
        "conditional_capacity",
        lambda *args, **kwargs: candidate,
    )
    with pytest.raises(capacity.CapacityResultError):
        capacity.shear_face_mrd(_member_input(), "x", True, 25.0)


@pytest.mark.parametrize(
    ("point", "message"),
    [
        (_plastic_point(converged=1), "Boolean"),
        (_plastic_point(Mx=math.nan), "finite real"),
        (_plastic_point(Mx=math.inf), "finite real"),
    ],
)
def test_shear_face_mrd_rejects_malformed_pure_axis_result(
    monkeypatch,
    point,
    message,
):
    monkeypatch.setattr(
        capacity,
        "conditional_capacity",
        lambda *args, **kwargs: (0.0, False),
    )
    monkeypatch.setattr(
        capacity,
        "plastic_capacity_at_angle",
        lambda *args, **kwargs: point,
    )
    with pytest.raises(capacity.CapacityResultError, match=message):
        capacity.shear_face_mrd(_member_input(), "x", True, 25.0)


@pytest.mark.parametrize(
    "point",
    [
        None,
        SimpleNamespace(Mx=100.0),
        SimpleNamespace(converged=True),
    ],
)
def test_shear_face_mrd_rejects_missing_pure_axis_members(
    monkeypatch,
    point,
):
    monkeypatch.setattr(
        capacity,
        "conditional_capacity",
        lambda *args, **kwargs: (0.0, False),
    )
    monkeypatch.setattr(
        capacity,
        "plastic_capacity_at_angle",
        lambda *args, **kwargs: point,
    )
    with pytest.raises(capacity.CapacityResultError, match="missing returned"):
        capacity.shear_face_mrd(_member_input(), "x", True, 25.0)


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


@pytest.mark.parametrize("value", [np.bool_(True), np.bool_(False)])
def test_torsion_rejects_numpy_boolean_at_raw_solver_boundary(value):
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
        section=None,
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
