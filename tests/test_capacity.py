"""Headless orchestration tests for member shear, torsion and M-V-T checks."""

from __future__ import annotations

import ast
import copy
import dataclasses
import json
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


def _checked_plastic(util=0.20, **overrides):
    result = {
        "util": util,
        "converged": True,
        "closed": True,
        "check_util": True,
        "util_valid": True,
    }
    result.update(overrides)
    return result


def _member_angle_selection(cot=1.5, *, include_dkna=True):
    cot_min = 1.0
    cot_max = 2.5
    samples = 1501
    step = (cot_max - cot_min) / (samples - 1)
    selected_index = round((cot - cot_min) / step)
    labels = ["shear link yielding", "torsion sub-tube 1"]
    if include_dkna:
        labels.append("DK NA governing interaction")
    labels = tuple(labels)
    governing_index = len(labels) - 1 if include_dkna else 0
    return {
        "cot": cot,
        "theta_deg": math.degrees(math.atan2(1.0, cot)),
        "utilisation": 0.95,
        "cot_min": cot_min,
        "cot_max": cot_max,
        "samples": samples,
        "step": step,
        "selected_index": selected_index,
        "objective_count": len(labels),
        "governing_component_indices": (governing_index,),
        "runner_up_utilisation": 0.40,
        "objective_labels": labels,
        "governing_objectives": (labels[governing_index],),
    }


def _torsion_only_member_angle_selection(cot=1.5, *, utilisation=0.40):
    selection = _member_angle_selection(cot, include_dkna=False)
    selection.update(
        utilisation=utilisation,
        objective_count=1,
        governing_component_indices=(0,),
        runner_up_utilisation=None,
        objective_labels=("torsion sub-tube 1",),
        governing_objectives=("torsion sub-tube 1",),
    )
    return selection


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


def test_torsion_subdivision_requires_zero_global_tef_and_keeps_subtubes_automatic():
    automatic = _member_input(
        torsion_on=True,
        torsion_subdivide=True,
        torsion_tef=0.0,
        torsion_subrects=[(150.0, 300.0, 300.0, 600.0)],
    )

    ctx = capacity.build_torsion_context(automatic, 0.0)

    assert ctx["subdivide"] is True
    assert len(ctx["subtubes"]) == 1
    assert ctx["subtubes"][0]["tef_user"] is False
    assert ctx["subtubes"][0]["tef_selection"] == "A/u"

    two_holes = [
        [(0.05, 0.10), (0.10, 0.10), (0.10, 0.15), (0.05, 0.15)],
        [(0.20, 0.40), (0.25, 0.40), (0.25, 0.45), (0.20, 0.45)],
    ]
    for rectangles, holes in (
        (automatic["torsion_subrects"], []),
        ([(150.0, 300.0, 290.0, 600.0)], []),  # requested, but leaves a gap
        (automatic["torsion_subrects"], two_holes),  # multi-cell placeholder
    ):
        overridden = dict(
            automatic,
            torsion_tef=25.0,
            torsion_subrects=rectangles,
            holes=holes,
        )
        with pytest.raises(
            capacity.CapacityInputError,
            match=(
                r"torsion wall-thickness override must be 0 "
                r"\(automatic per sub-tube\) when torsion subdivision is enabled"
            ),
        ):
            capacity.build_torsion_context(overridden, 0.0)


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


def _combined_components(*, links=False):
    method = codes.EC2_2005_DKNA.label
    selection = _member_angle_selection() if links else None
    shear_result = {
        "res": {"valid": True},
        "util": 0.30,
        "method": method,
    }
    if links:
        shear_result.update(v_ed=30.0)
        shear_result["links"] = {
            "res": {"valid": True, "cot": 1.5},
            "util": 0.35,
            "delta_ftd": 22.5,
            "member_angle_selection": selection,
        }
    return {
        "plastic": _checked_plastic(),
        "shear": shear_result,
        "torsion": {
            "valid": True,
            "util": 0.40,
            "interaction": None,
            "asl_req": 125.0,
            "asw_over_s": 0.0,
            "t_ed": 0.0,
            "primary": {"t_ed": 0.0, "cot": 1.5, "asl_req": 125.0},
            "subdivided": False,
            "member_angle_selection": selection,
            "method": method,
        },
    }


def _complete_active_transverse_components():
    out = _combined_components(links=True)
    out["shear"].update(v_ed=30.0)
    out["shear"]["res"]["vrd_c"] = 100.0
    out["shear"]["links"]["res"].update(
        cot=1.5, vrd_s=100.0, vrd_max=200.0
    )
    out["torsion"].update(
        asw_over_s=0.5,
        t_ed=10.0,
        primary={
            "t_ed": 10.0,
            "trd_s": 100.0,
            "trd_max": 80.0,
            "cot": 1.5,
            "asl_req": 125.0,
        },
        interaction={
            "valid": True,
            "cot": 1.5,
            "theta_deg": math.degrees(math.atan2(1.0, 1.5)),
            "trd_max": 80.0,
            "vrd_max": 200.0,
            "t_ed": 10.0,
            "v_ed": 30.0,
            "value": 0.275,
        },
    )
    return out


def test_combined_prerequisites_bind_active_interaction_and_shear_shift_to_sources():
    inp = _member_input(combined_on=True, shear_links=True)
    control = _complete_active_transverse_components()
    control_before = copy.deepcopy(control)

    assert capacity.evaluate_combined_prerequisites(inp, control).valid
    assert control == control_before

    dead_torsion = _complete_active_transverse_components()
    dead_torsion["torsion"].update(util=0.0, t_ed=0.0)
    dead_torsion["torsion"]["primary"].update(
        t_ed=0.0,
        trd_max=90.0,
        cot=2.0,
    )
    dead_torsion["torsion"]["interaction"].update(t_ed=0.0, value=0.15)
    dead_torsion_selection = _member_angle_selection()
    dead_torsion_selection["utilisation"] = 0.20 + 0.35
    dead_torsion["shear"]["links"]["member_angle_selection"] = (
        dead_torsion_selection
    )
    dead_torsion["torsion"]["member_angle_selection"] = copy.deepcopy(
        dead_torsion_selection
    )
    assert capacity.evaluate_combined_prerequisites(inp, dead_torsion).valid

    dead_shear = _complete_active_transverse_components()
    dead_shear["shear"].update(v_ed=0.0)
    dead_shear["shear"]["links"].update(util=0.0, delta_ftd=0.0)
    dead_shear["shear"]["links"]["res"].update(cot=2.0, vrd_max=250.0)
    dead_shear["torsion"]["interaction"].update(v_ed=0.0, value=0.125)
    dead_shear_selection = _member_angle_selection()
    dead_shear_selection["utilisation"] = 0.20 + 0.40
    dead_shear["shear"]["links"]["member_angle_selection"] = dead_shear_selection
    dead_shear["torsion"]["member_angle_selection"] = copy.deepcopy(
        dead_shear_selection
    )
    assert capacity.evaluate_combined_prerequisites(inp, dead_shear).valid

    mutations = []
    missing_value = object()
    for valid in (missing_value, False, 1):
        mutated = _complete_active_transverse_components()
        if valid is missing_value:
            del mutated["shear"]["links"]["res"]["valid"]
        else:
            mutated["shear"]["links"]["res"]["valid"] = valid
        mutations.append(mutated)
    for utilisation in (missing_value, math.nan, math.inf, -0.01, True):
        mutated = _complete_active_transverse_components()
        if utilisation is missing_value:
            del mutated["shear"]["links"]["util"]
        else:
            mutated["shear"]["links"]["util"] = utilisation
        mutations.append(mutated)

    missing_delta = _complete_active_transverse_components()
    del missing_delta["shear"]["links"]["delta_ftd"]
    mutations.append(missing_delta)
    wrong_delta = _complete_active_transverse_components()
    wrong_delta["shear"]["links"]["delta_ftd"] = 23.0
    mutations.append(wrong_delta)

    missing_interaction = _complete_active_transverse_components()
    del missing_interaction["torsion"]["interaction"]
    mutations.append(missing_interaction)
    null_interaction = _complete_active_transverse_components()
    null_interaction["torsion"]["interaction"] = None
    mutations.append(null_interaction)
    invalid_interaction = _complete_active_transverse_components()
    invalid_interaction["torsion"]["interaction"]["valid"] = False
    mutations.append(invalid_interaction)
    incomplete_interaction = _complete_active_transverse_components()
    del incomplete_interaction["torsion"]["interaction"]["theta_deg"]
    mutations.append(incomplete_interaction)

    for key, value in (
        ("cot", 1.6),
        ("theta_deg", 30.0),
        ("trd_max", 81.0),
        ("vrd_max", 201.0),
        ("t_ed", 11.0),
        ("v_ed", 31.0),
        ("value", 0.30),
        ("trd_max", 0.0),
        ("vrd_max", 0.0),
    ):
        mutated = _complete_active_transverse_components()
        mutated["torsion"]["interaction"][key] = value
        mutations.append(mutated)

    wrong_primary_resistance = _complete_active_transverse_components()
    wrong_primary_resistance["torsion"]["primary"]["trd_max"] = 81.0
    mutations.append(wrong_primary_resistance)
    wrong_link_resistance = _complete_active_transverse_components()
    wrong_link_resistance["shear"]["links"]["res"]["vrd_max"] = 201.0
    mutations.append(wrong_link_resistance)

    for out in mutations:
        sources_before = copy.deepcopy(out)
        assert capacity.evaluate_combined_prerequisites(inp, out).valid is False
        assert out == sources_before


def test_f095_004_fixture_and_link_controls_follow_one_prerequisite_contract():
    fixture = json.loads(
        (pathlib.Path(__file__).parent / "fixtures" / "v095_review_cases.json")
        .read_text(encoding="utf-8")
    )
    case = next(item for item in fixture["findings"] if item["id"] == "F095-004")
    reproduction = case["reproduction"]
    inp = _member_input(**reproduction["input"])
    out = copy.deepcopy(reproduction["out"])
    before = copy.deepcopy(out)

    assessment = capacity.evaluate_combined_prerequisites(inp, out)

    assert out == before
    assert assessment.valid is False
    assert (assessment.r_m, assessment.r_v, assessment.r_t) == (0.2, 0.3, 0.4)
    assert (assessment.have_m, assessment.have_v, assessment.have_t) == (
        False, False, False,
    )
    assert assessment.reasons == (
        "plastic result is not converged",
        "plastic utilisation is not valid",
        "shear method is missing or inconsistent",
        "torsion design action is missing or malformed",
        "torsion subdivision state is missing or malformed",
        "torsion method is missing or inconsistent",
    )

    current = copy.deepcopy(out)
    current["plastic"].update(
        converged=True,
        closed=True,
        check_util=True,
        util_valid=True,
    )
    current["shear"]["method"] = inp["combined_method"]
    current["torsion"].update(
        method=inp["combined_method"],
        t_ed=0.0,
        primary={"t_ed": 0.0, "cot": 1.5, "asl_req": 125.0},
        subdivided=False,
    )
    inactive = capacity.evaluate_combined_prerequisites(
        _member_input(**dict(reproduction["input"], shear_links=False)),
        current,
    )
    assert inactive.valid is True
    assert inactive.links_required is False
    assert inactive.links_valid is True
    assert inactive.r_v == pytest.approx(0.30)

    active = copy.deepcopy(current)
    active["shear"] = copy.deepcopy(
        reproduction["controls"]["invalid_active_links"]["shear"]
    )
    active["shear"]["method"] = inp["combined_method"]
    invalid_links = capacity.evaluate_combined_prerequisites(
        _member_input(**dict(reproduction["input"], shear_links=True)),
        active,
    )
    assert invalid_links.valid is False
    assert invalid_links.links_required is True
    assert invalid_links.links_valid is False
    assert invalid_links.have_v is False


def test_combined_prerequisites_reject_every_flag_and_nonfinite_utilisation():
    base_inp = _member_input(combined_on=True)

    for flag in ("converged", "closed", "check_util", "util_valid"):
        for value in (False, None, 1, "true"):
            out = _combined_components()
            out["plastic"][flag] = value
            assert capacity.evaluate_combined_prerequisites(
                base_inp, out
            ).valid is False
        missing = _combined_components()
        del missing["plastic"][flag]
        assert capacity.evaluate_combined_prerequisites(
            base_inp, missing
        ).valid is False

    for value in (math.nan, math.inf, -math.inf, -1.0e-12, -0.4, True, False):
        for family, key in (
            ("plastic", "util"),
            ("shear", "util"),
            ("torsion", "util"),
        ):
            out = _combined_components()
            out[family][key] = value
            assert capacity.evaluate_combined_prerequisites(base_inp, out).valid is False

    invalid_shear = _combined_components()
    invalid_shear["shear"]["res"]["valid"] = 1
    assert capacity.evaluate_combined_prerequisites(
        base_inp, invalid_shear
    ).shear_valid is False

    for value in (False, None, 1, "true"):
        invalid_torsion = _combined_components()
        invalid_torsion["torsion"]["valid"] = value
        assert capacity.evaluate_combined_prerequisites(
            base_inp, invalid_torsion
        ).torsion_valid is False
    missing_torsion_flag = _combined_components()
    del missing_torsion_flag["torsion"]["valid"]
    assert capacity.evaluate_combined_prerequisites(
        base_inp, missing_torsion_flag
    ).torsion_valid is False

    for links in (
        None,
        {"res": {"valid": False}, "util": 0.35},
        {"res": {"valid": True}, "util": math.inf},
        {"res": {"valid": True}, "util": -1.0e-12},
        {"res": {"valid": True}, "util": True},
    ):
        active = _combined_components(links=True)
        active["shear"]["links"] = links
        assessment = capacity.evaluate_combined_prerequisites(
            _member_input(combined_on=True, shear_links=True), active
        )
        assert assessment.valid is False
        assert assessment.links_valid is False


def test_combined_prerequisites_bind_each_raw_method_to_combined_authority():
    inp = _member_input(combined_on=True)
    assert capacity.evaluate_combined_prerequisites(
        inp, _combined_components()
    ).valid
    assert capacity.evaluate_combined_prerequisites(
        _member_input(combined_on=True, shear_links=True),
        _combined_components(links=True),
    ).valid

    for method in capacity.SHEAR_CODES:
        method_input = _member_input(
            combined_on=True,
            combined_method=method,
            shear_method=method,
            torsion_method=method,
        )
        method_components = _combined_components()
        method_components["shear"]["method"] = method
        method_components["torsion"]["method"] = method
        assessment = capacity.evaluate_combined_prerequisites(
            method_input, method_components
        )
        assert assessment.valid
        assert assessment.method == method

    for family in ("shear", "torsion"):
        missing = _combined_components()
        del missing[family]["method"]
        assessment = capacity.evaluate_combined_prerequisites(inp, missing)
        assert assessment.valid is False
        assert getattr(assessment, f"{family}_valid") is False

        mismatched = _combined_components()
        mismatched[family]["method"] = codes.EC2_2005.label
        assessment = capacity.evaluate_combined_prerequisites(inp, mismatched)
        assert assessment.valid is False
        assert getattr(assessment, f"{family}_valid") is False

    for key, family in (
        ("shear_method", "shear"),
        ("torsion_method", "torsion"),
    ):
        missing_input = _member_input(combined_on=True)
        del missing_input[key]
        with pytest.raises(
            capacity.CapacityInputError,
            match=rf"combined {family} method must equal the combined method",
        ):
            capacity.evaluate_combined_prerequisites(
                missing_input, _combined_components()
            )

        mismatched_input = _member_input(
            combined_on=True,
            **{key: codes.EC2_2005.label},
        )
        with pytest.raises(
            capacity.CapacityInputError,
            match=rf"combined {family} method must equal the combined method",
        ):
            capacity.evaluate_combined_prerequisites(
                mismatched_input, _combined_components()
            )

    with pytest.raises(
        capacity.CapacityInputError,
        match="combined M-V independence must be a concrete Boolean",
    ):
        capacity.evaluate_combined_prerequisites(
            _member_input(combined_on=True, combined_mv_independent=1),
            _combined_components(),
        )

    for malformed in (None, "", 0, [], ()):
        with pytest.raises(
            capacity.CapacityInputError,
            match="combined shear-links authority must be a concrete Boolean",
        ):
            capacity.evaluate_combined_prerequisites(
                _member_input(combined_on=True, shear_links=malformed),
                _combined_components(links=True),
            )


def test_final_prerequisites_require_current_common_angle_only_for_live_actions():
    inp = _member_input(combined_on=True, shear_links=True)
    control = _combined_components(links=True)
    assert capacity.evaluate_combined_prerequisites(inp, control).valid

    independent_input = _member_input(
        combined_on=True,
        shear_links=True,
        combined_mv_independent=True,
    )
    independent_control = _combined_components(links=True)
    independent_selection = _member_angle_selection()
    independent_selection["utilisation"] = max(0.20 + 0.40, 0.35 + 0.40)
    independent_control["shear"]["links"][
        "member_angle_selection"
    ] = independent_selection
    independent_control["torsion"]["member_angle_selection"] = copy.deepcopy(
        independent_selection
    )
    independent_assessment = capacity.evaluate_combined_prerequisites(
        independent_input, independent_control
    )
    assert independent_assessment.valid
    assert independent_assessment.m_v_independent is True

    wrong_independent_selection = _combined_components(links=True)
    assert capacity.evaluate_combined_prerequisites(
        independent_input, wrong_independent_selection
    ).valid is False

    preliminary = copy.deepcopy(control)
    preliminary["shear"]["links"]["member_angle_selection"] = None
    preliminary["torsion"]["member_angle_selection"] = None
    assert capacity.combined_angle_objective_r_m(inp, preliminary) == pytest.approx(
        0.20
    )
    assert capacity.evaluate_combined_prerequisites(inp, preliminary).valid is False
    assert capacity.combined_plastic_prerequisite_is_valid(control["plastic"])

    invalid_plastic_preliminary = copy.deepcopy(preliminary)
    invalid_plastic_preliminary["plastic"]["converged"] = False
    assert capacity.combined_angle_objective_r_m(
        inp, invalid_plastic_preliminary
    ) is None
    assert not capacity.combined_plastic_prerequisite_is_valid(
        invalid_plastic_preliminary["plastic"]
    )

    invalid_link_preliminary = copy.deepcopy(preliminary)
    invalid_link_preliminary["shear"]["links"]["res"]["valid"] = False
    assert capacity.combined_angle_objective_r_m(
        inp, invalid_link_preliminary
    ) is None

    invalid_torsion_preliminary = copy.deepcopy(preliminary)
    invalid_torsion_preliminary["torsion"]["valid"] = False
    assert capacity.combined_angle_objective_r_m(
        inp, invalid_torsion_preliminary
    ) is None

    mutations = []
    missing_links_copy = copy.deepcopy(control)
    del missing_links_copy["shear"]["links"]["member_angle_selection"]
    mutations.append(missing_links_copy)
    missing_torsion_copy = copy.deepcopy(control)
    del missing_torsion_copy["torsion"]["member_angle_selection"]
    mutations.append(missing_torsion_copy)
    cot_only = copy.deepcopy(control)
    cot_only["shear"]["links"]["member_angle_selection"] = {"cot": 1.5}
    cot_only["torsion"]["member_angle_selection"] = {"cot": 1.5}
    mutations.append(cot_only)
    for label_key in ("objective_labels", "governing_objectives"):
        for malformed_labels in (1, True, None):
            malformed_label_metadata = copy.deepcopy(control)
            malformed_selection = _member_angle_selection()
            malformed_selection[label_key] = malformed_labels
            malformed_label_metadata["shear"]["links"][
                "member_angle_selection"
            ] = malformed_selection
            malformed_label_metadata["torsion"][
                "member_angle_selection"
            ] = copy.deepcopy(malformed_selection)
            mutations.append(malformed_label_metadata)
    impossible_grid = copy.deepcopy(control)
    bad_selection = _member_angle_selection()
    bad_selection["step"] = 0.2
    impossible_grid["shear"]["links"]["member_angle_selection"] = bad_selection
    impossible_grid["torsion"]["member_angle_selection"] = copy.deepcopy(
        bad_selection
    )
    mutations.append(impossible_grid)
    runner_above_governing = copy.deepcopy(control)
    bad_runner = _member_angle_selection()
    bad_runner["runner_up_utilisation"] = 1.0
    runner_above_governing["shear"]["links"][
        "member_angle_selection"
    ] = bad_runner
    runner_above_governing["torsion"]["member_angle_selection"] = copy.deepcopy(
        bad_runner
    )
    mutations.append(runner_above_governing)
    missing_runner = copy.deepcopy(control)
    no_runner = _member_angle_selection()
    no_runner["runner_up_utilisation"] = None
    missing_runner["shear"]["links"]["member_angle_selection"] = no_runner
    missing_runner["torsion"]["member_angle_selection"] = copy.deepcopy(no_runner)
    mutations.append(missing_runner)
    impossible_runner = copy.deepcopy(control)
    all_govern = _member_angle_selection()
    all_govern["governing_component_indices"] = (0, 1, 2)
    all_govern["governing_objectives"] = all_govern["objective_labels"]
    impossible_runner["shear"]["links"]["member_angle_selection"] = all_govern
    impossible_runner["torsion"]["member_angle_selection"] = copy.deepcopy(
        all_govern
    )
    mutations.append(impossible_runner)
    understated_dkna = copy.deepcopy(control)
    low_selection = _member_angle_selection()
    low_selection["utilisation"] = 0.90
    understated_dkna["shear"]["links"][
        "member_angle_selection"
    ] = low_selection
    understated_dkna["torsion"]["member_angle_selection"] = copy.deepcopy(
        low_selection
    )
    mutations.append(understated_dkna)
    tied_but_not_governing = copy.deepcopy(control)
    non_dkna_governing = _member_angle_selection()
    non_dkna_governing["governing_component_indices"] = (0,)
    non_dkna_governing["governing_objectives"] = (
        non_dkna_governing["objective_labels"][0],
    )
    tied_but_not_governing["shear"]["links"][
        "member_angle_selection"
    ] = non_dkna_governing
    tied_but_not_governing["torsion"][
        "member_angle_selection"
    ] = copy.deepcopy(non_dkna_governing)
    mutations.append(tied_but_not_governing)
    governing_but_not_tied = copy.deepcopy(control)
    overstated_dkna = _member_angle_selection()
    overstated_dkna["utilisation"] = 1.0
    governing_but_not_tied["shear"]["links"][
        "member_angle_selection"
    ] = overstated_dkna
    governing_but_not_tied["torsion"][
        "member_angle_selection"
    ] = copy.deepcopy(overstated_dkna)
    mutations.append(governing_but_not_tied)
    no_dkna = copy.deepcopy(control)
    incomplete_selection = _member_angle_selection(include_dkna=False)
    no_dkna["shear"]["links"]["member_angle_selection"] = incomplete_selection
    no_dkna["torsion"]["member_angle_selection"] = copy.deepcopy(
        incomplete_selection
    )
    mutations.append(no_dkna)
    lower_runner_than_dkna = copy.deepcopy(control)
    low_runner_selection = _member_angle_selection()
    low_runner_selection["utilisation"] = 0.9500000000001
    low_runner_selection["governing_component_indices"] = (0,)
    low_runner_selection["governing_objectives"] = (
        low_runner_selection["objective_labels"][0],
    )
    low_runner_selection["runner_up_utilisation"] = 0.90
    lower_runner_than_dkna["shear"]["links"][
        "member_angle_selection"
    ] = low_runner_selection
    lower_runner_than_dkna["torsion"][
        "member_angle_selection"
    ] = copy.deepcopy(low_runner_selection)
    mutations.append(lower_runner_than_dkna)

    for out in mutations:
        assessment = capacity.evaluate_combined_prerequisites(inp, out)
        assert assessment.valid is False
        assert "live common member-angle selection" in assessment.reasons[-1]

    legitimate_non_dkna_governing = copy.deepcopy(control)
    slightly_higher_selection = _member_angle_selection()
    slightly_higher_selection["utilisation"] = 0.9500000000001
    slightly_higher_selection["governing_component_indices"] = (0,)
    slightly_higher_selection["governing_objectives"] = (
        slightly_higher_selection["objective_labels"][0],
    )
    slightly_higher_selection["runner_up_utilisation"] = 0.20 + 0.35 + 0.40
    legitimate_non_dkna_governing["shear"]["links"][
        "member_angle_selection"
    ] = slightly_higher_selection
    legitimate_non_dkna_governing["torsion"][
        "member_angle_selection"
    ] = copy.deepcopy(slightly_higher_selection)
    assert capacity.evaluate_combined_prerequisites(
        inp, legitimate_non_dkna_governing
    ).valid

    inactive_links = _combined_components()
    inactive_links["shear"]["v_ed"] = 30.0
    assert capacity.evaluate_combined_prerequisites(
        _member_input(combined_on=True, shear_links=False), inactive_links
    ).valid

    legacy_dead = _combined_components()
    del legacy_dead["torsion"]["primary"]
    legacy_dead["torsion"]["member_angle_selection"] = None
    assert capacity.evaluate_combined_prerequisites(
        _member_input(combined_on=True, shear_links=False), legacy_dead
    ).valid

    all_dead = _combined_components(links=True)
    all_dead["shear"]["v_ed"] = 0.0
    all_dead["shear"]["links"]["delta_ftd"] = 0.0
    all_dead["shear"]["links"]["member_angle_selection"] = None
    all_dead["torsion"]["member_angle_selection"] = None
    assert capacity.evaluate_combined_prerequisites(inp, all_dead).valid


def test_live_torsion_uses_top_level_action_and_requires_primary_angle_evidence():
    inp = _member_input(combined_on=True, shear_links=False)
    control = _combined_components()
    control["torsion"].update(
        t_ed=10.0,
        primary={"t_ed": 10.0, "cot": 1.5, "asl_req": 125.0},
        member_angle_selection=_torsion_only_member_angle_selection(),
    )
    assert capacity.evaluate_combined_prerequisites(inp, control).valid
    assert capacity.evaluate_combined_prerequisites(
        _member_input(
            combined_on=True,
            shear_links=False,
            strut_cot_min=2.5,
            strut_cot_max=1.0,
        ),
        control,
    ).valid

    mutations = []
    missing_selection = copy.deepcopy(control)
    del missing_selection["torsion"]["member_angle_selection"]
    mutations.append(missing_selection)
    missing_primary = copy.deepcopy(control)
    del missing_primary["torsion"]["primary"]
    mutations.append(missing_primary)
    wrong_primary_action = copy.deepcopy(control)
    wrong_primary_action["torsion"]["primary"]["t_ed"] = 9.0
    mutations.append(wrong_primary_action)
    wrong_top_level_asl = copy.deepcopy(control)
    wrong_top_level_asl["torsion"]["asl_req"] = 1.0
    mutations.append(wrong_top_level_asl)
    impossible_grid = copy.deepcopy(control)
    impossible_grid["torsion"]["member_angle_selection"]["selected_index"] = 0
    mutations.append(impossible_grid)
    understated_torsion = copy.deepcopy(control)
    understated_torsion["torsion"]["member_angle_selection"][
        "utilisation"
    ] = 0.30
    understated_torsion["torsion"]["member_angle_selection"][
        "runner_up_utilisation"
    ] = None
    mutations.append(understated_torsion)
    overstated_torsion = copy.deepcopy(control)
    overstated_torsion["torsion"]["member_angle_selection"][
        "utilisation"
    ] = 0.50
    overstated_torsion["torsion"]["member_angle_selection"][
        "runner_up_utilisation"
    ] = None
    mutations.append(overstated_torsion)
    forged_band = copy.deepcopy(control)
    forged_selection = _torsion_only_member_angle_selection()
    forged_selection.update(
        cot=10.0,
        theta_deg=math.degrees(math.atan2(1.0, 10.0)),
        cot_min=10.0,
        cot_max=11.0,
        step=1.0 / 1500.0,
        selected_index=0,
    )
    forged_band["torsion"]["primary"]["cot"] = 10.0
    forged_band["torsion"]["member_angle_selection"] = forged_selection
    mutations.append(forged_band)
    missing_top_action = copy.deepcopy(control)
    del missing_top_action["torsion"]["t_ed"]
    mutations.append(missing_top_action)
    negative_top_action = copy.deepcopy(control)
    negative_top_action["torsion"]["t_ed"] = -1.0
    mutations.append(negative_top_action)
    hidden_primary_action = _combined_components()
    hidden_primary_action["torsion"]["primary"]["t_ed"] = 10.0
    hidden_primary_action["torsion"]["member_angle_selection"] = None
    mutations.append(hidden_primary_action)

    for out in mutations:
        assessment = capacity.evaluate_combined_prerequisites(inp, out)
        assert assessment.valid is False
        assert assessment.torsion_valid is False


def test_torsion_chord_asl_binding_allows_only_subdivided_top_level_sum():
    inp = _member_input(combined_on=True, shear_links=True)
    control = _combined_components(links=True)
    control["shear"]["links"]["chord"] = {"valid": True}
    assert capacity.evaluate_combined_prerequisites(inp, control).valid

    mismatched = copy.deepcopy(control)
    mismatched["torsion"]["asl_req"] = 250.0
    assessment = capacity.evaluate_combined_prerequisites(inp, mismatched)
    assert assessment.valid is False
    assert assessment.torsion_valid is False
    assert (
        "non-subdivided torsion longitudinal force is inconsistent"
        in assessment.reasons
    )

    missing_identity = copy.deepcopy(control)
    del missing_identity["torsion"]["subdivided"]
    assert capacity.evaluate_combined_prerequisites(
        inp, missing_identity
    ).torsion_valid is False

    subdivided = copy.deepcopy(control)
    subdivided["torsion"].update(subdivided=True, asl_req=250.0)
    assert capacity.evaluate_combined_prerequisites(inp, subdivided).valid

    live_subdivided = _combined_components()
    live_subdivided["torsion"].update(
        subdivided=True,
        t_ed=20.0,
        asl_req=250.0,
        primary={"t_ed": 10.0, "cot": 1.5, "asl_req": 125.0},
        member_angle_selection=_torsion_only_member_angle_selection(),
    )
    no_links_input = _member_input(combined_on=True, shear_links=False)
    assert capacity.evaluate_combined_prerequisites(
        no_links_input, live_subdivided
    ).valid

    primary_exceeds_total = copy.deepcopy(live_subdivided)
    primary_exceeds_total["torsion"]["primary"]["t_ed"] = 21.0
    assert capacity.evaluate_combined_prerequisites(
        no_links_input, primary_exceeds_total
    ).torsion_valid is False
