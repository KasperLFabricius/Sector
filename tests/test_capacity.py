"""Headless orchestration tests for member shear, torsion and M-V-T checks."""

from __future__ import annotations

import ast
import copy
import dataclasses
import inspect
import math
import pathlib
from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import pytest

from sector import capacity, codes, shear, torsion
from sector import combined as combined_core
from sector import section as section_core
from sector.engineer_message import EngineerMessage
from sector.materials import Concrete, MildSteel


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
        "shear_gamma_v": 1.40,
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
        "torsion_design_basis": capacity.TORSION_DESIGN_EQUILIBRIUM,
        "torsion_member_scope": capacity.TORSION_MEMBER_CLOSED,
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


def _torsion_wall_bars(*, b=0.3, h=0.6, a=0.05, total_area=1473.0):
    area = total_area / 4.0
    return [
        (a, a, area),
        (b - a, a, area),
        (b - a, h - a, area),
        (a, h - a, area),
    ]


def _torsion_input(**overrides):
    values = {"bars": _torsion_wall_bars()}
    values.update(overrides)
    return _member_input(**values)


@pytest.mark.parametrize(
    ("design_basis", "member_scope", "expected_reason"),
    (
        (
            capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED,
            capacity.TORSION_MEMBER_CLOSED,
            "torsion design basis not established",
        ),
        (
            capacity.TORSION_DESIGN_COMPATIBILITY_MEMBER,
            capacity.TORSION_MEMBER_CLOSED,
            "compatibility torsion requires member or system assessment",
        ),
        (
            capacity.TORSION_DESIGN_EQUILIBRIUM,
            capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED,
            "torsion member scope not established",
        ),
        (
            capacity.TORSION_DESIGN_EQUILIBRIUM,
            capacity.TORSION_MEMBER_OPEN,
            "open or warping-sensitive torsion requires member analysis",
        ),
    ),
)
def test_torsion_applicability_blocks_before_sectional_kernels(
    monkeypatch,
    design_basis,
    member_scope,
    expected_reason,
):
    def forbidden(*_args, **_kwargs):
        pytest.fail("sectional torsion preparation must not run")

    monkeypatch.setattr(capacity, "_shared_links_present", forbidden)
    inp = _torsion_input(
        torsion_on=True,
        torsion_T=-40.0,
        torsion_design_basis=design_basis,
        torsion_member_scope=member_scope,
        section=None,
        outer=None,
    )

    context = capacity.build_torsion_context(inp, 0.0)
    result = capacity.unassessed_torsion_applicability(context)

    assert context["applicability_blocked"] is True
    assert context["t_ed_signed"] == pytest.approx(-40.0)
    assert context["t_ed"] == pytest.approx(40.0)
    assert context["applicability"]["reason"] == expected_reason
    assert context["applicability"]["full_resistance_route_entered"] is False
    assert result["assessment_status"] == "NOT ASSESSED"
    assert result["valid"] is False
    assert result["assessment_ok"] is None
    for key in ("trd", "util", "cot", "theta_deg", "asl_req", "interaction"):
        assert result[key] is None


@pytest.mark.parametrize(
    "key,bad_value",
    (
        ("torsion_design_basis", True),
        ("torsion_design_basis", np.bool_(False)),
        ("torsion_design_basis", 1),
        ("torsion_design_basis", "Equilibrium torsion"),
        ("torsion_member_scope", False),
        ("torsion_member_scope", np.bool_(True)),
        ("torsion_member_scope", 1.0),
        ("torsion_member_scope", "Closed section"),
    ),
)
def test_torsion_applicability_malformed_in_memory_choices_fail_closed(
    monkeypatch, key, bad_value
):
    monkeypatch.setattr(
        capacity,
        "_shared_links_present",
        lambda *_args, **_kwargs: pytest.fail("torsion kernel preparation entered"),
    )
    context = capacity.build_torsion_context(
        _torsion_input(torsion_on=True, **{key: bad_value}),
        0.0,
    )

    assert context["applicability_blocked"] is True
    assert context["applicability"]["status"] == "NOT ASSESSED"
    assert context["applicability"]["design_basis"] in (
        *capacity.TORSION_DESIGN_BASES,
    )
    assert context["applicability"]["member_scope"] in (
        *capacity.TORSION_MEMBER_SCOPES,
    )


def test_permitted_torsion_applicability_routes_retain_baseline_and_signed_action():
    results = []
    for design_basis in (
        capacity.TORSION_DESIGN_EQUILIBRIUM,
        capacity.TORSION_DESIGN_COMPATIBILITY_RESIDUAL,
    ):
        context = capacity.build_torsion_context(
            _torsion_input(
                torsion_on=True,
                torsion_T=-40.0,
                shear_links=True,
                torsion_design_basis=design_basis,
                torsion_member_scope=capacity.TORSION_MEMBER_CLOSED,
            ),
            0.0,
        )
        result = capacity.tube_torsion(
            context["tube"], context["t_ed"], **context["_tk"]
        )
        assert context["applicability_blocked"] is False
        assert context["applicability"]["status"] == "APPLICABLE"
        assert context["applicability"]["full_resistance_route_entered"] is True
        assert context["t_ed_signed"] == pytest.approx(-40.0)
        results.append(result)

    for result in results:
        assert result["valid"] is True
        assert result["trd"] == pytest.approx(78.81358728136769)
        assert result["util"] == pytest.approx(0.5075267016738927)
        assert result["cot"] == pytest.approx(1.6420676070939326)
        assert result["asl_req"] == pytest.approx(1003.154029061021)
    assert results[0]["trd"] == pytest.approx(results[1]["trd"])
    assert results[0]["util"] == pytest.approx(results[1]["util"])


@pytest.mark.parametrize(
    ("canonical_action", "signed_hint", "expected_signed"),
    (
        (80.0, 40.0, 80.0),
        (80.0, -40.0, -80.0),
        (-80.0, 40.0, 80.0),
    ),
)
def test_torsion_context_uses_canonical_demand_and_signed_hint_only_for_sense(
    canonical_action,
    signed_hint,
    expected_signed,
):
    context = capacity.build_torsion_context(
        _torsion_input(
            torsion_on=True,
            torsion_T=canonical_action,
            torsion_T_signed=signed_hint,
            shear_links=True,
        ),
        0.0,
    )
    result = capacity.tube_torsion(
        context["tube"], context["t_ed"], **context["_tk"]
    )

    assert context["t_ed"] == pytest.approx(80.0)
    assert context["t_ed_signed"] == pytest.approx(expected_signed)
    assert result["trd"] == pytest.approx(78.81358728136769)
    assert result["util"] == pytest.approx(80.0 / result["trd"])


def test_zero_torsion_action_does_not_require_member_scope_classification():
    zero = capacity.torsion_applicability({}, 0.0)
    smallest_nonzero = capacity.torsion_applicability(
        {}, math.nextafter(0.0, 1.0)
    )

    assert zero["status"] == "NOT APPLICABLE"
    assert zero["reason"] == "zero torsion action"
    assert zero["full_resistance_route_entered"] is False
    assert smallest_nonzero["status"] == "NOT ASSESSED"
    assert smallest_nonzero["reason"] == "torsion design basis not established"


def _shear_route_result(v_ed, *, vrd_c=103.417, vrd_links=None):
    result = {
        "v_ed": v_ed,
        "util": v_ed / vrd_c,
        "res": {"valid": True, "vrd_c": vrd_c},
    }
    if vrd_links is not None:
        result["links"] = {
            "res": {"valid": True, "vrd": vrd_links},
            "util": v_ed / vrd_links,
        }
    return result


def test_sparse_links_do_not_replace_applicable_concrete_resistance_or_verdict():
    selected = capacity.select_nominal_shear_resistance(
        _shear_route_result(80.0, vrd_links=29.452),
        links_selected=True,
    )

    assert selected.route == "concrete"
    assert selected.resistance == pytest.approx(103.417)
    assert selected.utilisation == pytest.approx(80.0 / 103.417)
    assert selected.status == "PASS"
    assert selected.ok is True
    assert selected.links_required is False
    assert 80.0 / 29.452 == pytest.approx(2.7162841233)


@pytest.mark.parametrize(
    (
        "demand",
        "link_resistance",
        "expected_route",
        "expected_status",
    ),
    (
        (math.nextafter(103.417, 0.0), None, "concrete", "PASS"),
        (math.nextafter(103.417, 0.0), 29.452, "concrete", "PASS"),
        (math.nextafter(103.417, 0.0), 200.0, "concrete", "PASS"),
        (103.417, None, "concrete", "PASS"),
        (103.417, 29.452, "concrete", "PASS"),
        (103.417, 200.0, "concrete", "PASS"),
        (math.nextafter(103.417, math.inf), None, "concrete", "FAIL"),
        (math.nextafter(103.417, math.inf), 29.452, "links", "FAIL"),
        (math.nextafter(103.417, math.inf), 200.0, "links", "PASS"),
    ),
)
def test_nominal_shear_route_uses_exact_vrdc_boundary(
    demand,
    link_resistance,
    expected_route,
    expected_status,
):
    selected = capacity.select_nominal_shear_resistance(
        _shear_route_result(demand, vrd_links=link_resistance),
        links_selected=link_resistance is not None,
    )

    assert selected.route == expected_route
    assert selected.status == expected_status
    assert selected.links_required is (demand > 103.417)


def test_missing_links_above_vrdc_retains_genuine_concrete_capacity_failure():
    selected = capacity.select_nominal_shear_resistance(
        _shear_route_result(math.nextafter(103.417, math.inf)),
        links_selected=False,
    )

    assert selected.route == "concrete"
    assert selected.status == "FAIL"
    assert selected.links_required is True


def test_unavailable_selected_links_cannot_bypass_fail_closed_geometry_gate():
    result = _shear_route_result(80.0)
    result["links"] = {
        "res": {
            "valid": False,
            "calculation_state": "NOT ASSESSED",
            "reason": "required shear geometry is unavailable",
        },
        "util": None,
    }
    selected = capacity.select_nominal_shear_resistance(
        result,
        links_selected=True,
    )

    assert selected.valid is False
    assert selected.status == "NOT ASSESSED"
    assert selected.route is None
    assert selected.resistance is None


@pytest.mark.parametrize("code", (codes.EC2_2005_DKNA, codes.EC2_2023))
def test_angle_gate_cannot_bypass_unavailable_link_arm(code):
    result = _shear_route_result(80.0)
    result["links"] = {
        "res": shear.vrd_links(
            35.0,
            code,
            300.0,
            550.0,
            1.0,
            500.0,
            0.0,
            0.18,
            1.0,
            3.0,
            fcd_mpa=20.0,
            gamma_s=1.15,
            v_ed_kn=80.0,
        ),
        "util": None,
    }

    selected = capacity.select_nominal_shear_resistance(
        result,
        links_selected=True,
    )

    assert selected.valid is False
    assert selected.status == "NOT ASSESSED"
    assert selected.route is None
    assert selected.resistance is None
    assert selected.utilisation is None
    assert "lever arm" in selected.reason


def _dkna_plastic_input(**overrides):
    bars = [
        (-0.10, -0.25, 500.0),
        (0.10, -0.25, 500.0),
        (-0.10, 0.25, 500.0),
        (0.10, 0.25, 500.0),
    ]
    concrete = Concrete(fck=35.0, gamma_c=1.5, curve=2)
    steel = MildSteel(
        fytk=500.0,
        fyck=500.0,
        futk=500.0,
        eut=0.05,
        gamma_y=1.15,
        gamma_u=1.15,
        gamma_E=1.0,
        curve=1,
    )
    values = _member_input(
        outer=[(-0.15, -0.30), (0.15, -0.30), (0.15, 0.30), (-0.15, 0.30)],
        bars=bars,
        section=section_core.Section.from_polygon(
            corners=[
                (-0.15, -0.30),
                (0.15, -0.30),
                (0.15, 0.30),
                (-0.15, 0.30),
            ],
            bars_xy_area_mm2=bars,
        ),
        concrete=concrete,
        steel=steel,
        v_min=0.0,
        v_max=360.0,
        v_inc=30.0,
    )
    values.update(overrides)
    return values


def _dkna_asymmetric_plastic_input(**overrides):
    """Irregular section used for independent zero-moment axial references."""

    outer = [
        (-0.50, -0.45), (0.55, -0.45), (0.55, -0.10), (0.18, -0.10),
        (0.18, 0.55), (-0.08, 0.55), (-0.08, 0.20), (-0.50, 0.20),
    ]
    hole = [(-0.02, -0.02), (0.10, -0.02), (0.10, 0.10), (-0.02, 0.10)]
    bars = [
        (-0.42, -0.38, 804.0), (0.45, -0.38, 804.0),
        (0.10, 0.47, 491.0), (-0.02, 0.47, 491.0),
        (-0.42, 0.13, 314.0), (0.48, -0.03, 314.0),
    ]
    values = _dkna_plastic_input(
        outer=outer,
        holes=[hole],
        bars=bars,
        section=section_core.Section.from_polygon(
            corners=outer,
            holes=[hole],
            bars_xy_area_mm2=bars,
        ),
    )
    values.update(overrides)
    return values


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


def _checked_plastic(util=0.20):
    return {
        "converged": True,
        "closed": True,
        "check_util": True,
        "util_valid": True,
        "util": util,
    }


@dataclasses.dataclass(frozen=True)
class _ValueErrorFloat:
    def __float__(self) -> float:
        raise ValueError("hostile conversion")


@dataclasses.dataclass(frozen=True)
class _FloatOnly:
    value: float

    def __float__(self) -> float:
        return self.value


def test_combined_angle_objective_r_m_accepts_valid_plastic_evidence():
    control = _checked_plastic(np.float64(0.20))
    before = copy.deepcopy(control)
    retained_util = control["util"]

    assert capacity.combined_angle_objective_r_m(control) == pytest.approx(0.20)
    assert control == before
    assert control["util"] is retained_util

    zero_control = _checked_plastic(np.float64(0.0))
    zero_util = zero_control["util"]
    assert capacity.combined_angle_objective_r_m(zero_control) == 0.0
    assert zero_control["util"] is zero_util

    above_one_control = _checked_plastic(np.float64(1.2345))
    above_one_util = above_one_control["util"]
    above_one = capacity.combined_angle_objective_r_m(above_one_control)
    assert type(above_one) is float
    assert above_one == pytest.approx(1.2345)
    assert above_one_control["util"] is above_one_util


def test_combined_angle_objective_r_m_rejects_invalid_plastic_evidence():
    for malformed in (None, object(), {}, {"plastic": _checked_plastic()}):
        assert capacity.combined_angle_objective_r_m(malformed) is None

    for flag in ("converged", "closed", "check_util", "util_valid"):
        missing = _checked_plastic()
        del missing[flag]
        missing_before = copy.deepcopy(missing)
        assert capacity.combined_angle_objective_r_m(missing) is None
        assert missing == missing_before
        for value in (False, None, 0, 1, "true", np.bool_(True)):
            mutated = _checked_plastic()
            mutated[flag] = value
            before = copy.deepcopy(mutated)
            retained_flag = mutated[flag]
            assert capacity.combined_angle_objective_r_m(mutated) is None
            assert mutated == before
            assert mutated[flag] is retained_flag

    missing_util = _checked_plastic()
    del missing_util["util"]
    missing_util_before = copy.deepcopy(missing_util)
    assert capacity.combined_angle_objective_r_m(missing_util) is None
    assert missing_util == missing_util_before
    for value in (
        None,
        False,
        True,
        np.bool_(False),
        "0.20",
        b"0.20",
        -0.01,
        math.nan,
        math.inf,
        -math.inf,
        10**4000,
        SimpleNamespace(),
        _ValueErrorFloat(),
    ):
        mutated = _checked_plastic(value)
        before = copy.deepcopy(mutated)
        retained_util = mutated["util"]
        assert capacity.combined_angle_objective_r_m(mutated) is None
        assert mutated == before
        assert mutated["util"] is retained_util


def test_combined_angle_objective_r_m_has_angle_independent_boundary():
    signature = inspect.signature(capacity.combined_angle_objective_r_m)
    assert tuple(signature.parameters) == ("plastic",)
    assert all(
        parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        for parameter in signature.parameters.values()
    )
    assert signature.parameters["plastic"].default is inspect.Parameter.empty


def test_combined_interaction_authority_uses_input_shared_stirrup_geometry():
    inp = _member_input(
        shear_links=True,
        shear_link_legs=4,
        shear_link_dia=10.0,
        shear_link_s=150.0,
    )
    expected = math.pi * 10.0**2 / 4.0 / 150.0
    retained = {"asw_over_s": expected}
    inp_before = dict(inp)
    retained_before = dict(retained)

    authority = capacity.combined_interaction_authority(inp, retained)

    assert authority == capacity.CombinedInteractionAuthority(
        links_required=True,
        expected_asw_over_s=expected,
        retained_asw_over_s=expected,
        retained_current=True,
        interaction_required=True,
    )
    assert inp == inp_before
    assert retained == retained_before

    # The torsion share is one closed-stirrup leg, not the shear leg count.
    multiplied = capacity.combined_interaction_authority(
        inp,
        {"asw_over_s": expected * inp["shear_link_legs"]},
    )
    assert multiplied.expected_asw_over_s == expected
    assert multiplied.retained_current is False
    assert multiplied.interaction_required is True

    equivalent_string = capacity.combined_interaction_authority(
        inp,
        {"asw_over_s": str(expected)},
    )
    assert equivalent_string.retained_asw_over_s is None
    assert equivalent_string.retained_current is False

    boolean_equivalent_input = _member_input(
        shear_links=True,
        shear_link_dia=1.0,
        shear_link_s=math.pi / 4.0,
    )
    boolean_equivalent = capacity.combined_interaction_authority(
        boolean_equivalent_input,
        {"asw_over_s": True},
    )
    assert boolean_equivalent.expected_asw_over_s == 1.0
    assert boolean_equivalent.retained_asw_over_s is None
    assert boolean_equivalent.retained_current is False


@pytest.mark.parametrize(
    "retained_ratio",
    [None, False, True, "0.5", math.nan, math.inf, -math.inf, -0.1, 0.0, 0.5, 0.6],
)
def test_combined_interaction_authority_rejects_stale_or_malformed_retained_ratio(
    retained_ratio,
):
    inp = _member_input(shear_links=True)
    retained = {"asw_over_s": retained_ratio}
    before = repr(retained)

    authority = capacity.combined_interaction_authority(inp, retained)

    assert authority.retained_current is False
    assert authority.interaction_required is True
    assert repr(retained) == before

    missing = capacity.combined_interaction_authority(inp, {})
    malformed = capacity.combined_interaction_authority(inp, object())
    assert missing.retained_current is False
    assert malformed.retained_current is False
    assert missing.interaction_required is True
    assert malformed.interaction_required is True


@pytest.mark.parametrize("field", ["shear_link_dia", "shear_link_s"])
@pytest.mark.parametrize(
    "value",
    [None, False, True, "10", math.nan, math.inf, -math.inf, -1.0, 0.0],
)
def test_combined_interaction_authority_rejects_invalid_active_input_geometry(
    field,
    value,
):
    inp = _member_input(shear_links=True)
    inp[field] = value
    with pytest.raises(capacity.CapacityInputError):
        capacity.combined_interaction_authority(inp, {"asw_over_s": 0.5})


@pytest.mark.parametrize(
    ("diameter", "spacing"),
    [(1.0e308, 1.0), (1.0e-200, 1.0e200)],
)
def test_combined_interaction_authority_rejects_nonfinite_derived_ratio(
    diameter,
    spacing,
):
    inp = _member_input(
        shear_links=True,
        shear_link_dia=diameter,
        shear_link_s=spacing,
    )
    with pytest.raises(capacity.CapacityInputError):
        capacity.combined_interaction_authority(inp, {"asw_over_s": 0.5})


@pytest.mark.parametrize("field", ["shear_link_dia", "shear_link_s"])
def test_combined_interaction_authority_requires_active_input_geometry(field):
    inp = _member_input(shear_links=True)
    del inp[field]
    with pytest.raises(capacity.CapacityInputError):
        capacity.combined_interaction_authority(inp, {"asw_over_s": 0.5})


@pytest.mark.parametrize("authority", [None, 0, 1, "", [], {}])
def test_combined_interaction_authority_requires_exact_link_authority(authority):
    inp = _member_input()
    inp["shear_links"] = authority
    with pytest.raises(capacity.CapacityInputError):
        capacity.combined_interaction_authority(inp, {"asw_over_s": 0.5})

    with pytest.raises(capacity.CapacityInputError):
        capacity.combined_interaction_authority(object(), {"asw_over_s": 0.5})

    missing = _member_input()
    del missing["shear_links"]
    with pytest.raises(capacity.CapacityInputError):
        capacity.combined_interaction_authority(missing, {"asw_over_s": 0.5})


def test_combined_interaction_authority_ignores_inactive_and_not_applied_loads():
    inactive = _member_input(
        shear_links=False,
        shear_link_dia=0.0,
        shear_link_s=0.0,
    )
    assert capacity.combined_interaction_authority(inactive, object()) == (
        capacity.CombinedInteractionAuthority(
            links_required=False,
            expected_asw_over_s=None,
            retained_asw_over_s=None,
            retained_current=True,
            interaction_required=False,
        )
    )

    active = _member_input(
        shear_links=True,
        shear_V=0.0,
        torsion_T=0.0,
    )
    expected = math.pi * active["shear_link_dia"] ** 2 / 4.0 / active["shear_link_s"]
    authority = capacity.combined_interaction_authority(
        active,
        {"asw_over_s": expected},
    )
    assert authority.retained_current is True
    assert authority.interaction_required is True

    stale_input = dict(active, shear_link_dia=12.0)
    stale = capacity.combined_interaction_authority(
        stale_input,
        {"asw_over_s": expected},
    )
    assert stale.retained_current is False
    assert stale.interaction_required is True

    tiny = _member_input(
        shear_links=True,
        shear_link_dia=1.0e-6,
        shear_link_s=1.0e6,
    )
    tiny_expected = math.pi * tiny["shear_link_dia"] ** 2 / 4.0 / tiny["shear_link_s"]
    assert tiny_expected > 0.0
    assert capacity.combined_interaction_authority(
        tiny,
        {"asw_over_s": 0.0},
    ).retained_current is False
    assert capacity.combined_interaction_authority(
        tiny,
        {"asw_over_s": tiny_expected},
    ).retained_current is True


def _chord_candidate(
    role,
    axis,
    tension_low,
    *,
    gets_shift=False,
    torsion_live=True,
    util=0.5,
):
    candidate = {
        "valid": True,
        "conditional": True,
        "role": role,
        "axis": axis,
        "tension_low": tension_low,
        "util": util,
    }
    if role == "shear_axis":
        candidate.update(
            off_not_evaluated=None,
            has_torsion=torsion_live,
            gets_shift=gets_shift,
        )
    return candidate


def _complete_torsion_chord_links(*, shear_axis="x", shear_tension_low=True):
    off_axis = "y" if shear_axis == "x" else "x"
    return {
        "chord_candidates": [
            _chord_candidate(
                "shear_axis",
                shear_axis,
                True,
                gets_shift=shear_tension_low is True,
            ),
            _chord_candidate(
                "shear_axis",
                shear_axis,
                False,
                gets_shift=shear_tension_low is False,
            ),
            _chord_candidate("off_axis", off_axis, True),
            _chord_candidate("off_axis", off_axis, False),
        ]
    }


def _complete_2023_chord_links(*, shear_axis="x", torsion_live=False):
    off_axis = "y" if shear_axis == "x" else "x"
    tension = _chord_candidate(
        "shear_axis",
        shear_axis,
        True,
        gets_shift=True,
        torsion_live=torsion_live,
    )
    tension.update(chord_role="flexural_tension", chord_formula="8.51")
    tension["flexural_tension_low"] = True
    compression = _chord_candidate(
        "shear_axis",
        shear_axis,
        False,
        gets_shift=True,
        torsion_live=torsion_live,
    )
    compression.update(chord_role="flexural_compression", chord_formula="8.52")
    compression["flexural_tension_low"] = True
    candidates = [tension, compression]
    if torsion_live:
        candidates.extend((
            _chord_candidate("off_axis", off_axis, True),
            _chord_candidate("off_axis", off_axis, False),
        ))
    return {"model_2023": True, "chord_candidates": candidates}


def _chord_evidence_is_valid(
    links,
    *,
    shear_live,
    torsion_live,
    torsion_subdivided,
    shear_axis="x",
    shear_tension_low=True,
):
    return capacity.combined_longitudinal_chord_evidence_is_valid(
        links,
        shear_axis=shear_axis,
        shear_tension_low=shear_tension_low,
        shear_live=shear_live,
        torsion_live=torsion_live,
        torsion_subdivided=torsion_subdivided,
    )


def test_combined_longitudinal_chord_evidence_accepts_complete_required_faces():
    assert _chord_evidence_is_valid(
        object(),
        shear_live=False,
        torsion_live=False,
        torsion_subdivided=False,
    )
    assert _chord_evidence_is_valid(
        object(),
        shear_live=False,
        torsion_live=False,
        torsion_subdivided=True,
    )

    shear_only = {
        "chord_candidates": [
            _chord_candidate(
                "shear_axis",
                "x",
                True,
                gets_shift=True,
                torsion_live=False,
            )
        ]
    }
    assert _chord_evidence_is_valid(
        shear_only,
        shear_live=True,
        torsion_live=False,
        torsion_subdivided=False,
    )
    alternate_shear_only = {
        "chord_candidates": [
            _chord_candidate(
                "shear_axis",
                "y",
                False,
                gets_shift=True,
                torsion_live=False,
            )
        ]
    }
    assert _chord_evidence_is_valid(
        alternate_shear_only,
        shear_axis="y",
        shear_tension_low=False,
        shear_live=True,
        torsion_live=False,
        torsion_subdivided=False,
    )

    torsion = _complete_torsion_chord_links()
    before = copy.deepcopy(torsion)
    for shear_live in (False, True):
        assert _chord_evidence_is_valid(
            torsion,
            shear_live=shear_live,
            torsion_live=True,
            torsion_subdivided=False,
        )
    assert torsion == before
    alternate_torsion = _complete_torsion_chord_links(
        shear_axis="y",
        shear_tension_low=False,
    )
    assert _chord_evidence_is_valid(
        alternate_torsion,
        shear_axis="y",
        shear_tension_low=False,
        shear_live=True,
        torsion_live=True,
        torsion_subdivided=False,
    )

    tuple_candidates = {
        "chord_candidates": tuple(copy.deepcopy(torsion["chord_candidates"]))
    }
    assert _chord_evidence_is_valid(
        tuple_candidates,
        shear_live=True,
        torsion_live=True,
        torsion_subdivided=False,
    )

    shear_2023 = _complete_2023_chord_links()
    assert _chord_evidence_is_valid(
        shear_2023,
        shear_live=True,
        torsion_live=False,
        torsion_subdivided=False,
    )
    torsion_2023 = _complete_2023_chord_links(torsion_live=True)
    assert _chord_evidence_is_valid(
        torsion_2023,
        shear_live=True,
        torsion_live=True,
        torsion_subdivided=False,
    )

    infinite_failure = copy.deepcopy(torsion)
    infinite_failure["chord_candidates"][0]["util"] = math.inf
    assert _chord_evidence_is_valid(
        infinite_failure,
        shear_live=True,
        torsion_live=True,
        torsion_subdivided=False,
    )
    zero_utilisation = copy.deepcopy(torsion)
    zero_utilisation["chord_candidates"][0]["util"] = 0.0
    assert _chord_evidence_is_valid(
        zero_utilisation,
        shear_live=True,
        torsion_live=True,
        torsion_subdivided=False,
    )


def test_2023_longitudinal_chord_assessment_fails_closed_for_every_required_face():
    def assess(links):
        return capacity.longitudinal_chord_assessment(
            links,
            shear_axis="x",
            shear_tension_low=True,
            shear_live=True,
            torsion_live=False,
            torsion_subdivided=False,
        )

    complete = _complete_2023_chord_links()
    passed = assess(complete)
    assert passed["status"] == "PASS"
    assert passed["ok"] is True
    assert passed["coverage_complete"] is True
    assert passed["util"] == pytest.approx(0.5)

    failed = copy.deepcopy(complete)
    failed["chord_candidates"][1]["util"] = 2.15
    definite_failure = assess(failed)
    assert definite_failure["status"] == "FAIL"
    assert definite_failure["ok"] is False
    assert definite_failure["coverage_complete"] is True
    assert definite_failure["util"] == pytest.approx(2.15)
    assert definite_failure["governing"]["chord_formula"] == "8.52"

    incomplete = copy.deepcopy(complete)
    del incomplete["chord_candidates"][1]
    unavailable = assess(incomplete)
    assert unavailable["status"] == "NOT ASSESSED"
    assert unavailable["ok"] is None
    assert unavailable["coverage_complete"] is False

    failed_and_incomplete = copy.deepcopy(incomplete)
    failed_and_incomplete["chord_candidates"][0]["util"] = 2.15
    retained_failure = assess(failed_and_incomplete)
    assert retained_failure["status"] == "FAIL"
    assert retained_failure["ok"] is False
    assert retained_failure["coverage_complete"] is False


def _pub_h01_longitudinal_fixture(utilisation=1.2392531643):
    m_total = 123.925316
    m_rd = (
        m_total / utilisation
        if math.isfinite(utilisation) and utilisation > 0.0
        else 0.0
        if utilisation == math.inf
        else 100.0
    )
    return {
        "valid": True,
        "status": "PASS" if utilisation <= 1.0 + 1.0e-9 else "FAIL",
        "ok": utilisation <= 1.0 + 1.0e-9,
        "axis": "x",
        "tension_low": True,
        "conditional": True,
        "biaxial": False,
        "off_util": 0.0,
        "off_not_evaluated": None,
        "m_ed": 80.0,
        "mv": 4.213620,
        "mt": 39.711696,
        "m_total": m_total,
        "m_rd": m_rd,
        "ftd_v": 17.34,
        "ftd_t": 326.8452380952381,
        "z": 0.243,
        "util": utilisation,
        "capped": False,
        "cap_shear_force": True,
        "mv_uncapped": 4.213620,
        "shear_headroom": max(m_rd - 80.0, 0.0),
        "shear_term_selection": (
            "zero-capacity uncapped demand" if m_rd <= 0.0 else "uncapped"
        ),
    }


def _pub_h01_2023_shear_only_candidates():
    common = {
        "valid": True,
        "status": "PASS",
        "ok": True,
        "role": "shear_axis",
        "axis": "x",
        "conditional": True,
        "biaxial": False,
        "off_util": 0.0,
        "off_not_evaluated": None,
        "mv": 10.0,
        "mt": 0.0,
        "m_rd": 100.0,
        "ftd_v": 40.0,
        "ftd_t": 0.0,
        "z": 0.25,
        "capped": False,
        "cap_shear_force": False,
        "has_torsion": False,
        "gets_shift": True,
        "flexural_tension_low": True,
    }
    tension = {
        **common,
        "tension_low": True,
        "chord_role": "flexural_tension",
        "chord_formula": "8.51",
        "m_ed": 40.0,
        "face_m_ed_signed": 40.0,
        "m_total": 50.0,
        "util": 0.50,
    }
    compression = {
        **common,
        "tension_low": False,
        "chord_role": "flexural_compression",
        "chord_formula": "8.52",
        "m_ed": 20.0,
        "face_m_ed_signed": -20.0,
        "m_total": 0.0,
        "util": 0.0,
    }
    return tension, compression


def _pub_h01_2005_torsion_candidates():
    direct = {
        **_pub_h01_longitudinal_fixture(0.50),
        "role": "shear_axis",
        "has_torsion": True,
        "gets_shift": True,
    }

    def torsion_only(role, axis, tension_low):
        mt = 39.711696
        m_ed = 10.0
        m_rd = 100.0
        candidate = {
            "valid": True,
            "status": "PASS",
            "ok": True,
            "role": role,
            "axis": axis,
            "tension_low": tension_low,
            "conditional": True,
            "biaxial": False,
            "off_util": 0.0,
            "m_ed": m_ed,
            "mv": 0.0,
            "mt": mt,
            "m_total": m_ed + mt,
            "m_rd": m_rd,
            "ftd_v": 0.0,
            "ftd_t": 326.8452380952381,
            "z": 0.243,
            "util": (m_ed + mt) / m_rd,
            "capped": False,
            "cap_shear_force": True,
            "mv_uncapped": 0.0,
            "shear_headroom": m_rd - m_ed,
            "shear_term_selection": "uncapped",
        }
        if role == "shear_axis":
            candidate.update(
                has_torsion=True,
                gets_shift=False,
                off_not_evaluated=None,
            )
        return candidate

    return [
        direct,
        torsion_only("shear_axis", "x", False),
        torsion_only("off_axis", "y", True),
        torsion_only("off_axis", "y", False),
    ]


def _unverified_formula_628(ratio=0.50):
    reference_fyd = 400.0
    provided_force = 400.0
    required_force = ratio * provided_force
    sufficient = bool(
        provided_force >= required_force
        or math.isclose(
            provided_force,
            required_force,
            rel_tol=1.0e-12,
            abs_tol=0.0,
        )
    )
    if required_force == 0.0:
        status = "PASS"
        ok = True
        reason = "no_longitudinal_torsion_demand"
    elif not sufficient:
        status = "FAIL"
        ok = False
        reason = "longitudinal_torsion_reinforcement_insufficient"
    else:
        status = "NOT ASSESSED"
        ok = None
        reason = "longitudinal_torsion_reinforcement_not_verified"
    return {
        "status": status,
        "ok": ok,
        "reason": reason,
        "required_asl_mm2": required_force * 1000.0 / reference_fyd,
        "required_design_force_kn": required_force,
        "provided_design_force_kn": provided_force,
        "reference_fyd_mpa": reference_fyd,
        "demand_ratio": ratio,
        "area_sufficient": sufficient,
    }


def test_combined_longitudinal_assessment_retains_alias_free_exact_failure():
    direct = _pub_h01_longitudinal_fixture()
    combined = {
        "longitudinal": direct,
        "torsion_longitudinal_assessment": _unverified_formula_628(),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "FAIL"
    assert assessment["ok"] is False
    assert assessment["util"] == pytest.approx(1.2392531643)
    assert assessment["governing_source"] == "combined_chord"
    assert assessment["governing"] is direct
    assert assessment["chord_governing"] is direct
    assert assessment["torsion_status"] == "NOT ASSESSED"

    combined["overall_longitudinal_assessment"] = assessment
    assert capacity.combined_longitudinal_assessment(combined) is assessment


def test_combined_longitudinal_stale_governing_alias_cannot_replace_direct_failure():
    direct = _pub_h01_longitudinal_fixture()
    stale_alias = {
        **direct,
        "status": "PASS",
        "ok": True,
        "m_ed": 0.0,
        "mv": 10.0,
        "mt": 40.0,
        "m_total": 50.0,
        "util": 0.50,
    }
    combined = {
        "longitudinal": direct,
        "governing_longitudinal": stale_alias,
        "longitudinal_all_conditional": True,
        "torsion_longitudinal_assessment": _unverified_formula_628(0.0),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["reason"] == "combined_longitudinal_evidence_inconsistent"


def test_combined_longitudinal_stale_retained_assessment_cannot_replace_child_failure():
    direct = _pub_h01_longitudinal_fixture()
    stale = {
        **direct,
        "status": "PASS",
        "ok": True,
        "m_ed": 0.0,
        "mv": 10.0,
        "mt": 40.0,
        "m_total": 50.0,
        "ftd_v": 10.0 / direct["z"],
        "ftd_t": 80.0 / direct["z"],
        "util": 0.50,
    }
    combined = {
        "longitudinal": direct,
        "longitudinal_assessment": {
            "status": "PASS",
            "ok": True,
            "util": 0.50,
            "reason": "required_longitudinal_chords_satisfied",
            "coverage_complete": True,
            "governing": stale,
        },
        "torsion_longitudinal_assessment": _unverified_formula_628(0.0),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["reason"] == "combined_longitudinal_evidence_inconsistent"


def test_combined_longitudinal_2023_coverage_is_rebuilt_from_retained_faces():
    tension, compression = _pub_h01_2023_shear_only_candidates()
    combined = {
        "longitudinal_model_2023": True,
        "longitudinal": tension,
        "longitudinal_candidates": [tension, compression],
        "governing_longitudinal": tension,
        "longitudinal_assessment": {
            "status": "PASS",
            "ok": True,
            "util": 0.50,
            "reason": "required_longitudinal_chords_satisfied",
            "coverage_complete": True,
            "governing": tension,
        },
        "t_ed": 0.0,
        "asl_torsion": 0.0,
        "torsion_subdivided": False,
        "torsion_subtubes": None,
        "torsion_longitudinal_assessment": _unverified_formula_628(0.0),
    }

    complete = capacity.combined_longitudinal_assessment(combined)
    assert complete["status"] == "PASS"
    assert complete["util"] == pytest.approx(0.50)

    stale_complete = copy.deepcopy(combined)
    del stale_complete["longitudinal_candidates"][1]
    rejected = capacity.combined_longitudinal_assessment(stale_complete)
    assert rejected["status"] == "NOT ASSESSED"
    assert rejected["ok"] is None
    assert rejected["util"] is None
    assert rejected["reason"] == "combined_longitudinal_evidence_inconsistent"

    missing_list = copy.deepcopy(combined)
    missing_list.pop("longitudinal_candidates")
    rejected_missing_list = capacity.combined_longitudinal_assessment(missing_list)
    assert rejected_missing_list["status"] == "NOT ASSESSED"
    assert rejected_missing_list["ok"] is None
    assert rejected_missing_list["util"] is None
    assert (
        rejected_missing_list["reason"]
        == "combined_longitudinal_evidence_inconsistent"
    )

    honest_incomplete = copy.deepcopy(stale_complete)
    honest_incomplete["longitudinal_assessment"].update(
        status="NOT ASSESSED",
        ok=None,
        reason="required_longitudinal_chord_coverage_incomplete",
        coverage_complete=False,
    )
    unavailable = capacity.combined_longitudinal_assessment(honest_incomplete)
    assert unavailable["status"] == "NOT ASSESSED"
    assert unavailable["ok"] is None
    assert unavailable["util"] is None
    assert unavailable["reason"] == "required_longitudinal_chord_coverage_incomplete"


def test_combined_longitudinal_2023_rejects_torsion_operands_with_stale_flag():
    tension, compression = _pub_h01_2023_shear_only_candidates()
    for candidate in (tension, compression):
        candidate.update(
            ftd_t=40.0,
            mt=5.0,
            m_total=candidate["m_total"] + 5.0,
            util=(candidate["m_total"] + 5.0) / candidate["m_rd"],
        )
    governing = max((tension, compression), key=lambda item: item["util"])
    combined = {
        "longitudinal_model_2023": True,
        "longitudinal": tension,
        "longitudinal_candidates": [tension, compression],
        "governing_longitudinal": governing,
        "longitudinal_assessment": {
            "status": "PASS",
            "ok": True,
            "util": governing["util"],
            "reason": "required_longitudinal_chords_satisfied",
            "coverage_complete": True,
            "governing": governing,
        },
        "torsion_longitudinal_assessment": _unverified_formula_628(0.0),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["reason"] == "combined_longitudinal_evidence_inconsistent"


def test_combined_longitudinal_2005_rebuilds_all_torsion_chord_faces():
    candidates = _pub_h01_2005_torsion_candidates()
    governing = max(candidates, key=lambda item: item["util"])
    combined = {
        "longitudinal": candidates[0],
        "longitudinal_candidates": candidates,
        "governing_longitudinal": governing,
        "longitudinal_assessment": {
            "status": "PASS",
            "ok": True,
            "util": governing["util"],
            "reason": "required_longitudinal_chords_satisfied",
            "coverage_complete": True,
            "governing": governing,
        },
        "t_ed": 40.0,
        "asl_torsion": 500.0,
        "torsion_longitudinal_assessment": _unverified_formula_628(0.50),
    }

    complete = capacity.combined_longitudinal_assessment(combined)
    assert complete["chord_status"] == "PASS"
    assert complete["chord_coverage_complete"] is True

    stale = copy.deepcopy(combined)
    stale["longitudinal_candidates"] = [stale["longitudinal"]]
    stale["governing_longitudinal"] = stale["longitudinal"]
    stale["longitudinal_assessment"]["governing"] = stale["longitudinal"]
    rejected = capacity.combined_longitudinal_assessment(stale)

    assert rejected["status"] == "NOT ASSESSED"
    assert rejected["ok"] is None
    assert rejected["util"] is None
    assert rejected["reason"] == "combined_longitudinal_evidence_inconsistent"


def test_combined_longitudinal_2005_requires_torsion_on_every_required_face():
    candidates = _pub_h01_2005_torsion_candidates()
    governing = max(candidates, key=lambda item: item["util"])
    combined = {
        "longitudinal": candidates[0],
        "longitudinal_candidates": candidates,
        "governing_longitudinal": governing,
        "longitudinal_assessment": {
            "status": "PASS",
            "ok": True,
            "util": governing["util"],
            "reason": "required_longitudinal_chords_satisfied",
            "coverage_complete": True,
            "governing": governing,
        },
        "t_ed": 40.0,
        "asl_torsion": 500.0,
        "torsion_longitudinal_assessment": _unverified_formula_628(0.50),
    }
    for candidate in combined["longitudinal_candidates"]:
        if candidate["role"] != "off_axis":
            continue
        candidate["ftd_t"] = 0.0
        candidate["mt"] = 0.0
        candidate["m_total"] = candidate["m_ed"]
        candidate["util"] = candidate["m_total"] / candidate["m_rd"]
        candidate["status"] = "PASS"
        candidate["ok"] = True

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["reason"] == "combined_longitudinal_evidence_inconsistent"


def test_combined_longitudinal_current_candidates_require_role_identity():
    candidates = _pub_h01_2005_torsion_candidates()
    governing = max(candidates, key=lambda item: item["util"])
    combined = {
        "longitudinal": candidates[0],
        "longitudinal_candidates": candidates,
        "governing_longitudinal": governing,
        "longitudinal_assessment": {
            "status": "PASS",
            "ok": True,
            "util": governing["util"],
            "reason": "required_longitudinal_chords_satisfied",
            "coverage_complete": True,
            "governing": governing,
        },
        "t_ed": 40.0,
        "asl_torsion": 500.0,
        "torsion_longitudinal_assessment": _unverified_formula_628(0.50),
    }
    for candidate in combined["longitudinal_candidates"]:
        candidate.pop("role")

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["reason"] == "combined_longitudinal_evidence_inconsistent"


def test_combined_longitudinal_role_bearing_direct_requires_candidate_list():
    candidates = _pub_h01_2005_torsion_candidates()
    direct = candidates[0]
    combined = {
        "longitudinal": direct,
        "governing_longitudinal": direct,
        "longitudinal_assessment": {
            "status": "PASS",
            "ok": True,
            "util": direct["util"],
            "reason": "required_longitudinal_chords_satisfied",
            "coverage_complete": True,
            "governing": direct,
        },
        "t_ed": 40.0,
        "asl_torsion": 500.0,
        "torsion_longitudinal_assessment": _unverified_formula_628(0.50),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["reason"] == "combined_longitudinal_evidence_inconsistent"


def test_combined_longitudinal_legacy_roleless_torsion_reconciles_owner_liveness():
    direct = _pub_h01_longitudinal_fixture(0.80)
    forged_zero_owner = {
        "longitudinal": direct,
        "longitudinal_candidates": [direct],
        "t_ed": 0.0,
        "asl_torsion": 0.0,
        "torsion_subdivided": False,
        "torsion_subtubes": None,
        "torsion_longitudinal_assessment": _unverified_formula_628(0.0),
    }

    rejected = capacity.combined_longitudinal_assessment(forged_zero_owner)

    assert rejected["status"] == "NOT ASSESSED"
    assert rejected["chord_status"] == "NOT ASSESSED"
    assert rejected["torsion_status"] == "PASS"
    assert rejected["util"] is None

    valid_live = copy.deepcopy(forged_zero_owner)
    valid_live.update(
        t_ed=40.0,
        asl_torsion=500.0,
        torsion_longitudinal_assessment=_unverified_formula_628(0.50),
    )
    accepted_live = capacity.combined_longitudinal_assessment(valid_live)

    assert accepted_live["chord_status"] == "PASS"
    assert accepted_live["chord_util"] == pytest.approx(0.80)
    assert accepted_live["torsion_status"] == "NOT ASSESSED"


def test_combined_longitudinal_legacy_zero_demand_control_remains_complete():
    direct = _pub_h01_longitudinal_fixture(0.80)
    direct.update(
        ftd_t=0.0,
        mt=0.0,
        m_total=direct["m_ed"] + direct["mv"],
    )
    direct["m_rd"] = direct["m_total"] / 0.80
    direct["shear_headroom"] = direct["m_rd"] - direct["m_ed"]
    direct["util"] = 0.80
    combined = {
        "longitudinal": direct,
        "t_ed": 0.0,
        "asl_torsion": 0.0,
        "torsion_subdivided": False,
        "torsion_subtubes": None,
        "torsion_longitudinal_assessment": _unverified_formula_628(0.0),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "PASS"
    assert assessment["chord_status"] == "PASS"
    assert assessment["torsion_status"] == "PASS"


@pytest.mark.parametrize(
    ("face_m_ed_signed", "m_total", "util"),
    ((-40.0, 0.0, 0.0), (5.0, 15.0, 0.15)),
)
def test_combined_longitudinal_2023_rejects_stale_face_moment_identity(
    face_m_ed_signed,
    m_total,
    util,
):
    tension, compression = _pub_h01_2023_shear_only_candidates()
    tension.update(
        face_m_ed_signed=face_m_ed_signed,
        m_total=m_total,
        util=util,
        status="PASS",
        ok=True,
    )
    governing = max((tension, compression), key=lambda item: item["util"])
    combined = {
        "longitudinal_model_2023": True,
        "longitudinal": tension,
        "longitudinal_candidates": [tension, compression],
        "governing_longitudinal": governing,
        "longitudinal_assessment": {
            "status": "PASS",
            "ok": True,
            "util": governing["util"],
            "reason": "required_longitudinal_chords_satisfied",
            "coverage_complete": True,
            "governing": governing,
        },
        "torsion_longitudinal_assessment": _unverified_formula_628(0.0),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["reason"] == "combined_longitudinal_evidence_inconsistent"


def test_combined_longitudinal_2023_rejects_first_generation_headroom_cap():
    tension, compression = _pub_h01_2023_shear_only_candidates()
    tension.update(
        ftd_v=300.0,
        mv=60.0,
        m_total=100.0,
        util=1.0,
        capped=True,
        cap_shear_force=False,
        status="PASS",
        ok=True,
    )
    combined = {
        "longitudinal_model_2023": True,
        "longitudinal": tension,
        "longitudinal_candidates": [tension, compression],
        "governing_longitudinal": tension,
        "longitudinal_assessment": {
            "status": "PASS",
            "ok": True,
            "util": 1.0,
            "reason": "required_longitudinal_chords_satisfied",
            "coverage_complete": True,
            "governing": tension,
        },
        "torsion_longitudinal_assessment": _unverified_formula_628(0.0),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["reason"] == "combined_longitudinal_evidence_inconsistent"


def test_combined_longitudinal_first_generation_reconciles_headroom_cap_state():
    direct = {
        **_pub_h01_longitudinal_fixture(),
        "ftd_v": 200.0,
        "mv": 20.0,
        "m_total": 139.711696,
        "util": 1.39711696,
        "status": "FAIL",
        "ok": False,
        "capped": False,
        "cap_shear_force": True,
        "mv_uncapped": 48.6,
        "shear_headroom": 20.0,
        "shear_term_selection": "uncapped",
    }

    assessment = capacity.combined_longitudinal_assessment({
        "longitudinal": direct,
        "torsion_longitudinal_assessment": _unverified_formula_628(),
    })

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None


def test_combined_longitudinal_formula_628_recomputes_retained_force_ratio():
    direct = _pub_h01_longitudinal_fixture(0.80)
    stale = _unverified_formula_628(0.0)
    stale.update(
        required_asl_mm2=500.0,
        required_design_force_kn=200.0,
        provided_design_force_kn=100.0,
        area_sufficient=False,
    )

    assessment = capacity.combined_longitudinal_assessment({
        "longitudinal": direct,
        "torsion_longitudinal_assessment": stale,
    })

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["torsion_status"] == "NOT ASSESSED"
    assert assessment["reason"] == "combined_longitudinal_evidence_inconsistent"


def test_torsion_longitudinal_publication_authority_hides_stale_operands():
    stale = _unverified_formula_628(0.0)
    stale.update(
        required_asl_mm2=500.0,
        required_design_force_kn=200.0,
        provided_design_force_kn=100.0,
        provided_gross_area_mm2=250.0,
        provided_equivalent_area_mm2=250.0,
        area_sufficient=False,
    )

    sanitized = capacity.validated_torsion_longitudinal_assessment(
        stale,
        owner={
            "asl_req": 500.0,
            "t_ed": 40.0,
            "subdivided": False,
            "subtubes": None,
        },
    )

    assert sanitized["evidence_consistent"] is False
    assert sanitized["status"] == "NOT ASSESSED"
    assert sanitized["ok"] is None
    assert sanitized["reason"] == "combined_longitudinal_evidence_inconsistent"
    assert sanitized["required_asl_mm2"] is None
    assert sanitized["required_design_force_kn"] is None
    assert sanitized["provided_design_force_kn"] is None
    assert sanitized["provided_gross_area_mm2"] is None
    assert sanitized["provided_equivalent_area_mm2"] is None
    assert sanitized["demand_ratio"] is None


def test_torsion_longitudinal_publication_authority_binds_owning_demand():
    forged_zero = _unverified_formula_628(0.0)

    rejected = capacity.validated_torsion_longitudinal_assessment(
        forged_zero,
        owner={
            "valid": True,
            "t_ed": 40.0,
            "asl_req": 500.0,
            "subdivided": False,
            "subtubes": None,
        },
    )
    accepted_zero = capacity.validated_torsion_longitudinal_assessment(
        forged_zero,
        owner={
            "valid": True,
            "t_ed": 0.0,
            "asl_req": 0.0,
            "subdivided": False,
            "subtubes": None,
        },
    )
    live = _unverified_formula_628(0.50)
    accepted_live = capacity.validated_torsion_longitudinal_assessment(
        live,
        owner={
            "valid": True,
            "t_ed": 40.0,
            "asl_req": 500.0,
            "subdivided": False,
            "subtubes": None,
        },
    )

    assert rejected["evidence_consistent"] is False
    assert rejected["status"] == "NOT ASSESSED"
    assert rejected["required_asl_mm2"] is None
    assert accepted_zero["evidence_consistent"] is True
    assert accepted_zero["status"] == "PASS"
    assert accepted_zero["required_asl_mm2"] == pytest.approx(0.0)
    assert accepted_live["evidence_consistent"] is True
    assert accepted_live["status"] == "NOT ASSESSED"
    assert accepted_live["required_asl_mm2"] == pytest.approx(500.0)


def test_torsion_longitudinal_publication_authority_rejects_boolean_tube_area():
    retained = _unverified_formula_628(0.50)
    retained["required_by_tube_mm2"] = (True, 499.0)

    sanitized = capacity.validated_torsion_longitudinal_assessment(
        retained,
        owner={
            "valid": True,
            "t_ed": 40.0,
            "asl_req": 500.0,
            "subdivided": True,
            "subtubes": (
                {"asl_req": 1.0, "t_ed": 10.0},
                {"asl_req": 499.0, "t_ed": 30.0},
            ),
        },
    )

    assert sanitized["evidence_consistent"] is False
    assert sanitized["status"] == "NOT ASSESSED"
    assert sanitized["required_asl_mm2"] is None


def test_torsion_longitudinal_publication_authority_rejects_subtube_total_conflict():
    retained = _unverified_formula_628(0.0)
    retained["required_by_tube_mm2"] = (10.0, 20.0)

    sanitized = capacity.validated_torsion_longitudinal_assessment(
        retained,
        owner={
            "valid": True,
            "t_ed": 0.0,
            "asl_req": 0.0,
            "subdivided": True,
            "subtubes": (
                {"asl_req": 10.0, "t_ed": 0.0},
                {"asl_req": 20.0, "t_ed": 0.0},
            ),
        },
    )

    assert sanitized["evidence_consistent"] is False
    assert sanitized["status"] == "NOT ASSESSED"
    assert sanitized["required_asl_mm2"] is None
    assert sanitized["required_by_tube_mm2"] is None


@pytest.mark.parametrize(
    ("owner_torque", "torque_parts"),
    [
        (0.0, (10.0, 30.0)),
        (40.0, (10.0, 20.0)),
    ],
    ids=["positive-children-under-zero-owner", "unequal-live-sum"],
)
def test_torsion_longitudinal_publication_authority_rejects_subtube_torque_conflict(
    owner_torque,
    torque_parts,
):
    live = owner_torque > 0.0
    retained = _unverified_formula_628(0.50 if live else 0.0)
    area_parts = (200.0, 300.0) if live else (0.0, 0.0)
    retained["required_by_tube_mm2"] = area_parts

    sanitized = capacity.validated_torsion_longitudinal_assessment(
        retained,
        owner={
            "valid": True,
            "t_ed": owner_torque,
            "asl_req": 500.0 if live else 0.0,
            "subdivided": True,
            "subtubes": tuple(
                {"asl_req": area, "t_ed": torque}
                for area, torque in zip(area_parts, torque_parts, strict=True)
            ),
        },
    )

    assert sanitized["evidence_consistent"] is False
    assert sanitized["status"] == "NOT ASSESSED"
    assert sanitized["required_asl_mm2"] is None
    assert sanitized["required_by_tube_mm2"] is None


@pytest.mark.parametrize("invalid_torque", [True, math.nan, math.inf, "10"])
def test_torsion_longitudinal_publication_authority_rejects_malformed_subtube_torque(
    invalid_torque,
):
    retained = _unverified_formula_628(0.50)
    retained["required_by_tube_mm2"] = (200.0, 300.0)

    sanitized = capacity.validated_torsion_longitudinal_assessment(
        retained,
        owner={
            "valid": True,
            "t_ed": 40.0,
            "asl_req": 500.0,
            "subdivided": True,
            "subtubes": (
                {"asl_req": 200.0, "t_ed": invalid_torque},
                {"asl_req": 300.0, "t_ed": 40.0},
            ),
        },
    )

    assert sanitized["evidence_consistent"] is False
    assert sanitized["status"] == "NOT ASSESSED"
    assert sanitized["required_asl_mm2"] is None


def test_torsion_longitudinal_publication_authority_rejects_array_status():
    retained = _unverified_formula_628(0.0)
    retained["status"] = np.array(["PASS"])

    sanitized = capacity.validated_torsion_longitudinal_assessment(
        retained,
        owner={
            "t_ed": 0.0,
            "asl_req": 0.0,
            "subdivided": False,
            "subtubes": None,
        },
    )

    assert sanitized["evidence_consistent"] is False
    assert sanitized["status"] == "NOT ASSESSED"
    assert sanitized["demand_ratio"] is None


@pytest.mark.parametrize("hostile", [np.array([True]), 0.50 + 0.0j])
def test_combined_longitudinal_candidate_rejects_non_real_scalar_utilisation(
    hostile,
):
    direct = _pub_h01_longitudinal_fixture(0.50)
    direct["util"] = hostile
    combined = {
        "longitudinal": direct,
        "t_ed": 40.0,
        "asl_torsion": 500.0,
        "torsion_longitudinal_assessment": _unverified_formula_628(0.50),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None


def test_torsion_longitudinal_publication_authority_requires_per_tube_liveness():
    retained = _unverified_formula_628(0.50)
    retained["required_by_tube_mm2"] = (200.0, 300.0)

    sanitized = capacity.validated_torsion_longitudinal_assessment(
        retained,
        owner={
            "t_ed": 40.0,
            "asl_req": 500.0,
            "subdivided": True,
            "subtubes": (
                {"asl_req": 200.0, "t_ed": 40.0},
                {"asl_req": 300.0, "t_ed": 0.0},
            ),
        },
    )

    assert sanitized["evidence_consistent"] is False
    assert sanitized["status"] == "NOT ASSESSED"
    assert sanitized["required_by_tube_mm2"] is None


def test_torsion_longitudinal_publication_authority_rejects_force_underflow():
    retained = {
        "status": "PASS",
        "ok": True,
        "reason": "no_longitudinal_torsion_demand",
        "required_asl_mm2": 1.0e-200,
        "required_design_force_kn": 0.0,
        "provided_design_force_kn": 1.0,
        "reference_fyd_mpa": 1.0e-200,
        "demand_ratio": 0.0,
        "area_sufficient": True,
    }

    sanitized = capacity.validated_torsion_longitudinal_assessment(
        retained,
        owner={
            "t_ed": 1.0,
            "asl_req": 1.0e-200,
            "subdivided": False,
            "subtubes": None,
        },
    )

    assert sanitized["evidence_consistent"] is False
    assert sanitized["status"] == "NOT ASSESSED"
    assert sanitized["demand_ratio"] is None


def test_torsion_longitudinal_publication_authority_rejects_overflowing_tube_sum():
    retained = _unverified_formula_628(0.50)
    retained["required_by_tube_mm2"] = (1.0e308, 1.0e308)

    sanitized = capacity.validated_torsion_longitudinal_assessment(
        retained,
        owner={
            "t_ed": 40.0,
            "asl_req": 500.0,
            "subdivided": True,
            "subtubes": (
                {"asl_req": 1.0e308, "t_ed": 20.0},
                {"asl_req": 1.0e308, "t_ed": 20.0},
            ),
        },
    )

    assert sanitized["evidence_consistent"] is False
    assert sanitized["status"] == "NOT ASSESSED"
    assert sanitized["required_by_tube_mm2"] is None


def test_combined_longitudinal_publication_rejects_subtube_torque_conflict():
    direct = _pub_h01_longitudinal_fixture(0.80)
    retained = _unverified_formula_628(0.0)
    retained["required_by_tube_mm2"] = (0.0, 0.0)
    combined = {
        "longitudinal": direct,
        "t_ed": 0.0,
        "asl_torsion": 0.0,
        "torsion_subdivided": True,
        "torsion_subtubes": (
            {"asl_req": 0.0, "t_ed": 10.0},
            {"asl_req": 0.0, "t_ed": 30.0},
        ),
        "torsion_longitudinal_assessment": retained,
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["torsion_status"] == "NOT ASSESSED"
    assert assessment["reason"] == "combined_longitudinal_evidence_inconsistent"


@pytest.mark.parametrize(
    "owner",
    [
        {"t_ed": 0.0, "asl_req": 0.0},
        {
            "t_ed": 0.0,
            "asl_req": 0.0,
            "subdivided": False,
            "subtubes": ({"asl_req": 0.0},),
        },
        {
            "t_ed": 0.0,
            "asl_req": 0.0,
            "subdivided": True,
            "subtubes": (),
        },
    ],
)
def test_torsion_longitudinal_publication_authority_rejects_malformed_subdivision(
    owner,
):
    retained = _unverified_formula_628(0.0)
    retained["required_by_tube_mm2"] = (0.0,)

    sanitized = capacity.validated_torsion_longitudinal_assessment(
        retained,
        owner=owner,
    )

    assert sanitized["evidence_consistent"] is False
    assert sanitized["status"] == "NOT ASSESSED"


@pytest.mark.parametrize(
    ("ratio", "t_ed", "total", "parts", "torque_parts", "expected_status"),
    [
        (0.0, 0.0, 0.0, (0.0, 0.0), (0.0, 0.0), "PASS"),
        (
            0.50,
            40.0,
            500.0,
            (200.0, 300.0),
            (16.0, 24.0),
            "NOT ASSESSED",
        ),
    ],
)
def test_torsion_longitudinal_publication_authority_accepts_reconciled_subtubes(
    ratio,
    t_ed,
    total,
    parts,
    torque_parts,
    expected_status,
):
    retained = _unverified_formula_628(ratio)
    retained["required_by_tube_mm2"] = parts

    sanitized = capacity.validated_torsion_longitudinal_assessment(
        retained,
        owner={
            "valid": True,
            "t_ed": t_ed,
            "asl_req": total,
            "subdivided": True,
            "subtubes": tuple(
                {"asl_req": area, "t_ed": torque}
                for area, torque in zip(parts, torque_parts, strict=True)
            ),
        },
    )

    assert sanitized["evidence_consistent"] is True
    assert sanitized["status"] == expected_status
    assert sanitized["required_asl_mm2"] == pytest.approx(total)
    assert sanitized["required_by_tube_mm2"] == pytest.approx(parts)


def test_combined_longitudinal_candidate_recomputes_total_from_operands():
    direct = {
        **_pub_h01_longitudinal_fixture(),
        "status": "PASS",
        "ok": True,
        "m_total": 50.0,
        "util": 0.50,
    }
    assessment = capacity.combined_longitudinal_assessment({
        "longitudinal": direct,
        "torsion_longitudinal_assessment": _unverified_formula_628(),
    })

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["reason"] == "required_longitudinal_chord_coverage_incomplete"


def test_combined_longitudinal_definite_failure_governs_incomplete_child():
    direct = _pub_h01_longitudinal_fixture()
    combined = {
        "longitudinal": direct,
        "longitudinal_assessment": {
            "status": "FAIL",
            "ok": False,
            "util": direct["util"],
            "reason": "required_longitudinal_chord_failed",
            "coverage_complete": False,
            "governing": direct,
        },
        "t_ed": 40.0,
        "asl_torsion": 500.0,
        "torsion_longitudinal_assessment": _unverified_formula_628(),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "FAIL"
    assert assessment["util"] == pytest.approx(1.2392531643)
    assert assessment["coverage_complete"] is False


def test_combined_longitudinal_retained_not_assessed_cannot_mask_child_failure():
    direct = _pub_h01_longitudinal_fixture()
    combined = {
        "longitudinal": direct,
        "longitudinal_assessment": {
            "status": "NOT ASSESSED",
            "ok": None,
            "util": direct["util"],
            "reason": "required_longitudinal_chord_coverage_incomplete",
            "coverage_complete": True,
            "governing": direct,
        },
        "torsion_longitudinal_assessment": _unverified_formula_628(0.50),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "FAIL"
    assert assessment["ok"] is False
    assert assessment["util"] == pytest.approx(1.2392531643)
    assert assessment["chord_status"] == "FAIL"
    assert assessment["chord_reason"] == "required_longitudinal_chord_failed"


@pytest.mark.parametrize(
    "coverage_marker",
    ("not_solved", "subdivided", "circular_geometry"),
)
def test_combined_longitudinal_definite_failure_survives_documented_missing_face(
    coverage_marker,
):
    direct = {
        **_pub_h01_longitudinal_fixture(),
        "role": "shear_axis",
        "has_torsion": True,
        "gets_shift": True,
        "off_not_evaluated": coverage_marker,
    }
    combined = {
        "longitudinal": direct,
        "longitudinal_candidates": [direct],
        "governing_longitudinal": direct,
        "longitudinal_assessment": {
            "status": "FAIL",
            "ok": False,
            "util": direct["util"],
            "reason": "required_longitudinal_chord_failed",
            "coverage_complete": False,
            "governing": direct,
        },
        "t_ed": 40.0,
        "asl_torsion": 500.0,
        "torsion_longitudinal_assessment": _unverified_formula_628(),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "FAIL"
    assert assessment["ok"] is False
    assert assessment["util"] == pytest.approx(1.2392531643)
    assert assessment["coverage_complete"] is False
    assert assessment["governing"] is direct


@pytest.mark.parametrize("hostile", (None, 1, "missing"))
def test_combined_longitudinal_documented_missing_face_requires_shift_identity(
    hostile,
):
    direct = {
        **_pub_h01_longitudinal_fixture(),
        "role": "shear_axis",
        "has_torsion": True,
        "gets_shift": hostile,
        "off_not_evaluated": "not_solved",
    }
    if hostile == "missing":
        direct.pop("gets_shift")
    combined = {
        "longitudinal": direct,
        "longitudinal_candidates": [direct],
        "governing_longitudinal": direct,
        "longitudinal_assessment": {
            "status": "FAIL",
            "ok": False,
            "util": direct["util"],
            "reason": "required_longitudinal_chord_failed",
            "coverage_complete": False,
            "governing": direct,
        },
        "torsion_longitudinal_assessment": _unverified_formula_628(),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["reason"] == "combined_longitudinal_evidence_inconsistent"


def test_combined_longitudinal_unshifted_face_rejects_retained_shear_term():
    direct = {
        **_pub_h01_longitudinal_fixture(),
        "role": "shear_axis",
        "has_torsion": True,
        "gets_shift": False,
        "off_not_evaluated": "not_solved",
    }
    combined = {
        "longitudinal": direct,
        "longitudinal_candidates": [direct],
        "governing_longitudinal": direct,
        "longitudinal_assessment": {
            "status": "FAIL",
            "ok": False,
            "util": direct["util"],
            "reason": "required_longitudinal_chord_failed",
            "coverage_complete": False,
            "governing": direct,
        },
        "torsion_longitudinal_assessment": _unverified_formula_628(),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["reason"] == "combined_longitudinal_evidence_inconsistent"


def test_combined_longitudinal_unknown_missing_face_marker_remains_invalid():
    direct = {
        **_pub_h01_longitudinal_fixture(),
        "role": "shear_axis",
        "has_torsion": True,
        "gets_shift": True,
        "off_not_evaluated": "unknown",
    }
    combined = {
        "longitudinal": direct,
        "longitudinal_candidates": [direct],
        "governing_longitudinal": direct,
        "longitudinal_assessment": {
            "status": "FAIL",
            "ok": False,
            "util": direct["util"],
            "reason": "required_longitudinal_chord_failed",
            "coverage_complete": False,
            "governing": direct,
        },
        "torsion_longitudinal_assessment": _unverified_formula_628(),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["reason"] == "combined_longitudinal_evidence_inconsistent"


@pytest.mark.parametrize(
    "mutation",
    (
        {"biaxial": True},
        {"conditional": False},
        {"off_not_evaluated": "not_solved"},
        {"util": True},
        {"util": "1.2392531643"},
        {"util": math.nan},
        {"util": -math.inf},
        {"util": -0.1},
        {"status": "PASS"},
        {"ok": True},
        {"axis": ["x"]},
        {"role": ["shear_axis"]},
        {"status": ["FAIL"]},
        {"chord_formula": ["8.51"]},
        {"m_ed": True},
        {"m_total": math.nan},
        {"m_rd": math.inf},
        {"z": -0.243},
    ),
)
def test_combined_longitudinal_legacy_fallback_fails_closed(mutation):
    direct = _pub_h01_longitudinal_fixture()
    direct.update(mutation)
    combined = {
        "longitudinal": direct,
        "torsion_longitudinal_assessment": _unverified_formula_628(),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None


def test_combined_longitudinal_does_not_promote_apparent_formula_628_pass():
    direct = _pub_h01_longitudinal_fixture(0.80)
    combined = {
        "longitudinal": direct,
        "torsion_longitudinal_assessment": {
            "status": "PASS",
            "ok": True,
            "reason": "longitudinal_torsion_reinforcement_not_verified",
            "demand_ratio": 0.50,
        },
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["util"] is None
    assert assessment["torsion_status"] == "NOT ASSESSED"


def test_combined_longitudinal_positive_infinity_is_explicit_failure():
    direct = _pub_h01_longitudinal_fixture(math.inf)
    direct["m_rd"] = 0.0
    assessment = capacity.combined_longitudinal_assessment({
        "longitudinal": direct,
        "torsion_longitudinal_assessment": _unverified_formula_628(),
    })

    assert assessment["status"] == "FAIL"
    assert assessment["ok"] is False
    assert assessment["util"] == math.inf


def test_combined_longitudinal_retained_canonical_requires_exact_scalar_types():
    direct = _pub_h01_longitudinal_fixture(1.0)
    combined = {
        "longitudinal": direct,
        "torsion_longitudinal_assessment": {
            "status": "PASS",
            "ok": True,
            "reason": "no_longitudinal_torsion_demand",
            "demand_ratio": 0.0,
        },
    }
    retained = dict(capacity.combined_longitudinal_assessment(combined))
    retained["util"] = True
    combined["overall_longitudinal_assessment"] = retained

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["util"] is None
    assert assessment["reason"] == "combined_longitudinal_evidence_inconsistent"


def test_combined_longitudinal_stale_overall_reason_cannot_hide_derived_failure():
    direct = _pub_h01_longitudinal_fixture()
    combined = {
        "longitudinal": direct,
        "torsion_longitudinal_assessment": _unverified_formula_628(0.50),
    }
    derived = dict(capacity.combined_longitudinal_assessment(combined))
    assert derived["status"] == "FAIL"
    stale = copy.deepcopy(derived)
    stale["reason"] = "stale retained summary"
    combined["overall_longitudinal_assessment"] = stale

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "FAIL"
    assert assessment["ok"] is False
    assert assessment["util"] == pytest.approx(1.2392531643)
    assert assessment["reason"] == "required_longitudinal_chord_failed"


def test_combined_longitudinal_unassessed_chord_retains_valid_partial_evidence():
    direct = {
        **_pub_h01_longitudinal_fixture(),
        "status": "PASS",
        "ok": True,
        "m_ed": 0.0,
        "mv": 10.0,
        "mt": 40.0,
        "m_total": 50.0,
        "ftd_v": 10.0 / 0.243,
        "ftd_t": 80.0 / 0.243,
        "util": 0.50,
        "mv_uncapped": 10.0,
        "shear_headroom": 100.0,
    }
    retained = {
        "status": "NOT ASSESSED",
        "ok": None,
        "util": 0.50,
        "reason": "required_longitudinal_chord_coverage_incomplete",
        "coverage_complete": False,
        "governing": direct,
    }
    assessment = capacity.combined_longitudinal_assessment({
        "longitudinal": direct,
        "longitudinal_assessment": retained,
        "torsion_longitudinal_assessment": _unverified_formula_628(),
    })

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["util"] is None
    assert assessment["reason"] == "required_longitudinal_chord_coverage_incomplete"
    assert assessment["chord_governing"] is direct
    assert assessment["chord_assessment"] is retained


def test_combined_longitudinal_unassessed_chord_drops_malformed_governing():
    direct = _pub_h01_longitudinal_fixture()
    direct["m_total"] = math.nan
    assessment = capacity.combined_longitudinal_assessment({
        "longitudinal": direct,
        "longitudinal_assessment": {
            "status": "NOT ASSESSED",
            "ok": None,
            "util": None,
            "reason": "required_longitudinal_chord_coverage_incomplete",
            "coverage_complete": False,
            "governing": direct,
        },
        "torsion_longitudinal_assessment": _unverified_formula_628(),
    })

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["util"] is None
    assert assessment["chord_governing"] is None


def test_combined_longitudinal_retained_array_cannot_crash_reconciliation():
    direct = _pub_h01_longitudinal_fixture()
    combined = {
        "longitudinal": direct,
        "torsion_longitudinal_assessment": _unverified_formula_628(),
    }
    retained = dict(capacity.combined_longitudinal_assessment(combined))
    retained["governing"] = {**direct, "axis": np.array(["x"])}
    combined["overall_longitudinal_assessment"] = retained

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["util"] is None


def test_combined_longitudinal_retained_status_array_cannot_crash_reconciliation():
    direct = _pub_h01_longitudinal_fixture()
    combined = {
        "longitudinal": direct,
        "longitudinal_assessment": {
            "status": np.array(["FAIL"]),
            "ok": False,
            "util": direct["util"],
            "coverage_complete": True,
            "governing": direct,
        },
        "torsion_longitudinal_assessment": _unverified_formula_628(),
    }

    assessment = capacity.combined_longitudinal_assessment(combined)

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["util"] is None


@pytest.mark.parametrize(
    ("index", "field", "value"),
    (
        (0, "chord_formula", "8.52"),
        (1, "chord_formula", "8.51"),
        (0, "chord_role", "flexural_compression"),
        (1, "chord_role", "flexural_tension"),
        (0, "flexural_tension_low", False),
        (1, "flexural_tension_low", False),
        (0, "flexural_tension_low", 1),
    ),
)
def test_2023_longitudinal_chord_evidence_rejects_mismatched_face_identity(
    index,
    field,
    value,
):
    links = _complete_2023_chord_links()
    links["chord_candidates"][index][field] = value
    assert not _chord_evidence_is_valid(
        links,
        shear_live=True,
        torsion_live=False,
        torsion_subdivided=False,
    )


def test_combined_longitudinal_chord_evidence_rejects_incomplete_coverage():
    control = _complete_torsion_chord_links()
    for index in range(4):
        missing = copy.deepcopy(control)
        del missing["chord_candidates"][index]
        assert not _chord_evidence_is_valid(
            missing,
            shear_live=True,
            torsion_live=True,
            torsion_subdivided=False,
        )

    malformed_sets = []
    duplicate = copy.deepcopy(control)
    duplicate["chord_candidates"][-1] = copy.deepcopy(
        duplicate["chord_candidates"][-2]
    )
    malformed_sets.append(duplicate)
    extra = copy.deepcopy(control)
    extra["chord_candidates"].append(
        _chord_candidate("shear_axis", "y", True)
    )
    malformed_sets.append(extra)
    same_axis = copy.deepcopy(control)
    same_axis["chord_candidates"][2]["axis"] = "x"
    same_axis["chord_candidates"][3]["axis"] = "x"
    malformed_sets.append(same_axis)
    split_shear_axis = copy.deepcopy(control)
    split_shear_axis["chord_candidates"][1]["axis"] = "y"
    malformed_sets.append(split_shear_axis)
    split_off_axis = copy.deepcopy(control)
    split_off_axis["chord_candidates"][2]["axis"] = "x"
    malformed_sets.append(split_off_axis)
    no_shift = copy.deepcopy(control)
    no_shift["chord_candidates"][0]["gets_shift"] = False
    malformed_sets.append(no_shift)
    two_shifts = copy.deepcopy(control)
    two_shifts["chord_candidates"][1]["gets_shift"] = True
    malformed_sets.append(two_shifts)
    swapped_shift = copy.deepcopy(control)
    swapped_shift["chord_candidates"][0]["gets_shift"] = False
    swapped_shift["chord_candidates"][1]["gets_shift"] = True
    malformed_sets.append(swapped_shift)
    shear_only_extra = {
        "chord_candidates": [
            _chord_candidate(
                "shear_axis",
                "x",
                True,
                gets_shift=True,
                torsion_live=False,
            ),
            _chord_candidate(
                "off_axis",
                "y",
                True,
                torsion_live=False,
            ),
        ]
    }
    assert not _chord_evidence_is_valid(
        shear_only_extra,
        shear_live=True,
        torsion_live=False,
        torsion_subdivided=False,
    )
    for shear_only_candidate in (
        _chord_candidate(
            "shear_axis",
            "x",
            True,
            gets_shift=False,
            torsion_live=False,
        ),
        _chord_candidate(
            "shear_axis",
            "x",
            True,
            gets_shift=True,
            torsion_live=True,
        ),
        _chord_candidate(
            "off_axis",
            "y",
            True,
            torsion_live=False,
        ),
    ):
        assert not _chord_evidence_is_valid(
            {"chord_candidates": [shear_only_candidate]},
            shear_live=True,
            torsion_live=False,
            torsion_subdivided=False,
        )
    for malformed in malformed_sets:
        before = copy.deepcopy(malformed)
        assert not _chord_evidence_is_valid(
            malformed,
            shear_live=True,
            torsion_live=True,
            torsion_subdivided=False,
        )
        assert malformed == before

    thread_repro = {
        "chord": _chord_candidate("shear_axis", "x", True, gets_shift=True)
    }
    assert not _chord_evidence_is_valid(
        thread_repro,
        shear_live=True,
        torsion_live=True,
        torsion_subdivided=False,
    )
    for legacy_key in (
        "chord",
        "chord_off",
        "governing_longitudinal",
        "longitudinal_fallback",
    ):
        assert not _chord_evidence_is_valid(
            {
                legacy_key: _chord_candidate(
                    "shear_axis",
                    "x",
                    True,
                    gets_shift=True,
                    torsion_live=False,
                )
            },
            shear_live=True,
            torsion_live=False,
            torsion_subdivided=False,
        )

    assert not _chord_evidence_is_valid(
        {
            "chord_candidates": [
                _chord_candidate(
                    "shear_axis",
                    "x",
                    True,
                    gets_shift=True,
                    torsion_live=False,
                )
            ]
        },
        shear_axis="y",
        shear_live=True,
        torsion_live=False,
        torsion_subdivided=False,
    )
    assert not _chord_evidence_is_valid(
        {
            "chord_candidates": [
                _chord_candidate(
                    "shear_axis",
                    "x",
                    True,
                    gets_shift=True,
                    torsion_live=False,
                )
            ]
        },
        shear_tension_low=False,
        shear_live=True,
        torsion_live=False,
        torsion_subdivided=False,
    )
    assert not _chord_evidence_is_valid(
        control,
        shear_axis="y",
        shear_live=True,
        torsion_live=True,
        torsion_subdivided=False,
    )
    assert not _chord_evidence_is_valid(
        control,
        shear_tension_low=False,
        shear_live=True,
        torsion_live=True,
        torsion_subdivided=False,
    )


def test_combined_longitudinal_chord_evidence_rejects_bad_candidate_claims():
    mutations = [
        ("valid", None),
        ("valid", False),
        ("valid", 1),
        ("conditional", None),
        ("conditional", False),
        ("conditional", 1),
        ("role", None),
        ("role", "other"),
        ("axis", None),
        ("axis", "z"),
        ("tension_low", None),
        ("tension_low", 1),
        ("util", None),
        ("util", True),
        ("util", "0.5"),
        ("util", math.nan),
        ("util", -math.inf),
        ("util", -0.1),
        ("off_not_evaluated", "not_solved"),
        ("off_not_evaluated", "subdivided"),
        ("off_not_evaluated", "unknown"),
        ("has_torsion", False),
        ("has_torsion", 1),
        ("gets_shift", None),
        ("gets_shift", 1),
    ]
    for field, value in mutations:
        links = _complete_torsion_chord_links()
        links["chord_candidates"][0][field] = value
        assert not _chord_evidence_is_valid(
            links,
            shear_live=True,
            torsion_live=True,
            torsion_subdivided=False,
        )

    for field in (
        "valid",
        "conditional",
        "role",
        "axis",
        "tension_low",
        "util",
        "off_not_evaluated",
        "has_torsion",
        "gets_shift",
    ):
        links = _complete_torsion_chord_links()
        del links["chord_candidates"][0][field]
        assert not _chord_evidence_is_valid(
            links,
            shear_live=True,
            torsion_live=True,
            torsion_subdivided=False,
        )

    off_axis_mutations = [
        ("valid", False),
        ("conditional", False),
        ("role", "other"),
        ("axis", "z"),
        ("tension_low", 1),
        ("util", math.nan),
        ("off_not_evaluated", "not_solved"),
        ("off_not_evaluated", "subdivided"),
        ("off_not_evaluated", "unknown"),
    ]
    for field, value in off_axis_mutations:
        links = _complete_torsion_chord_links()
        links["chord_candidates"][2][field] = value
        assert not _chord_evidence_is_valid(
            links,
            shear_live=True,
            torsion_live=True,
            torsion_subdivided=False,
        )
    for field in ("valid", "conditional", "role", "axis", "tension_low", "util"):
        links = _complete_torsion_chord_links()
        del links["chord_candidates"][2][field]
        assert not _chord_evidence_is_valid(
            links,
            shear_live=True,
            torsion_live=True,
            torsion_subdivided=False,
        )


def test_combined_longitudinal_chord_evidence_rejects_unsupported_shapes():
    control = _complete_torsion_chord_links()
    for malformed in (None, object(), {}, {"chord_candidates": {}}, {"chord_candidates": []}):
        assert not _chord_evidence_is_valid(
            malformed,
            shear_live=True,
            torsion_live=True,
            torsion_subdivided=False,
        )

    non_mapping = copy.deepcopy(control)
    non_mapping["chord_candidates"][0] = None
    assert not _chord_evidence_is_valid(
        non_mapping,
        shear_live=True,
        torsion_live=True,
        torsion_subdivided=False,
    )

    not_solved = copy.deepcopy(control)
    for candidate in not_solved["chord_candidates"][:2]:
        candidate["off_not_evaluated"] = "not_solved"
    assert not _chord_evidence_is_valid(
        not_solved,
        shear_live=True,
        torsion_live=True,
        torsion_subdivided=False,
    )

    for links in (control, not_solved):
        assert not _chord_evidence_is_valid(
            links,
            shear_live=True,
            torsion_live=True,
            torsion_subdivided=True,
        )
        assert not _chord_evidence_is_valid(
            links,
            shear_live=False,
            torsion_live=True,
            torsion_subdivided=True,
        )

    for mode_name in ("shear_live", "torsion_live", "torsion_subdivided"):
        for bad_mode in (None, 0, 1, "false", []):
            modes = {
                "shear_live": True,
                "torsion_live": True,
                "torsion_subdivided": False,
            }
            modes[mode_name] = bad_mode
            assert not _chord_evidence_is_valid(
                control,
                **modes,
            )

    for bad_axis in (None, 0, 1, "", "z", []):
        assert not _chord_evidence_is_valid(
            control,
            shear_axis=bad_axis,
            shear_live=True,
            torsion_live=True,
            torsion_subdivided=False,
        )
    for bad_face in (None, 0, 1, "true", []):
        assert not _chord_evidence_is_valid(
            control,
            shear_tension_low=bad_face,
            shear_live=True,
            torsion_live=True,
            torsion_subdivided=False,
        )


@dataclasses.dataclass(frozen=True)
class _TopologySection:
    error: type[Exception] | None = None
    concrete: object = (
        ((0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)),
    )

    def require_valid_geometry(self):
        if self.error is not None:
            raise self.error("invalid section geometry")


def _torsion_subdivision_geometry_input(*, section=..., outer=..., holes=...):
    inp = {
        "outer": _rect() if outer is ... else outer,
        "holes": [] if holes is ... else holes,
    }
    if section is not ...:
        inp["section"] = section
    return inp


@pytest.mark.parametrize(
    "inp",
    [
        _torsion_subdivision_geometry_input(),
        _torsion_subdivision_geometry_input(section=_TopologySection()),
        _torsion_subdivision_geometry_input(
            section=SimpleNamespace(require_valid_geometry=None)
        ),
        _torsion_subdivision_geometry_input(holes=None),
        _torsion_subdivision_geometry_input(
            holes=[
                [(0.1, 0.2), (0.2, 0.2), (0.2, 0.4), (0.1, 0.4)]
            ]
        ),
    ],
)
def test_torsion_subdivision_geometry_accepts_both_current_representations(
    inp,
):
    before = copy.deepcopy(inp)

    result = capacity.combined_torsion_subdivision_geometry_is_valid(inp)

    assert result is True
    assert inp == before


@pytest.mark.parametrize(
    ("section_outer", "section_holes", "raw_outer", "raw_holes"),
    [
        (
            [(0.3, 0.0), (0.3, 0.6), (0.0, 0.6), (0.0, 0.0)],
            [],
            _rect(),
            [],
        ),
        (
            list(reversed(_rect())),
            [],
            [*_rect(), _rect()[0]],
            [],
        ),
        (
            [*_rect(), _rect()[0]],
            [],
            [(0.3, 0.6), (0.0, 0.6), (0.0, 0.0), (0.3, 0.0)],
            [],
        ),
        (
            _rect(),
            [
                [(0.03, 0.08), (0.10, 0.08), (0.10, 0.20), (0.03, 0.20)],
                [(0.18, 0.35), (0.25, 0.35), (0.25, 0.50), (0.18, 0.50)],
            ],
            _rect(),
            (
                [(0.25, 0.50), (0.25, 0.35), (0.18, 0.35), (0.18, 0.50)],
                [(0.10, 0.20), (0.03, 0.20), (0.03, 0.08), (0.10, 0.08)],
            ),
        ),
    ],
)
def test_torsion_subdivision_geometry_accepts_equivalent_ring_encodings(
    section_outer,
    section_holes,
    raw_outer,
    raw_holes,
):
    section = section_core.Section.from_polygon(section_outer, holes=section_holes)
    inp = _torsion_subdivision_geometry_input(
        section=section,
        outer=raw_outer,
        holes=raw_holes,
    )
    before_outer = copy.deepcopy(inp["outer"])
    before_holes = copy.deepcopy(inp["holes"])
    before_rings = [ring.copy() for ring in section.concrete]

    assert capacity.combined_torsion_subdivision_geometry_is_valid(inp)
    assert inp["section"] is section
    assert inp["outer"] == before_outer
    assert inp["holes"] == before_holes
    assert all(
        np.array_equal(actual, retained)
        for actual, retained in zip(section.concrete, before_rings, strict=True)
    )


@pytest.mark.parametrize(
    ("section_outer", "section_holes", "raw_outer", "raw_holes"),
    [
        (_rect(), [], _rect(b=0.4), []),
        (
            _rect(),
            [],
            [(0.0, 0.0), (0.3 + 1.0e-13, 0.0), (0.3, 0.6), (0.0, 0.6)],
            [],
        ),
        (
            _rect(),
            [],
            _rect(),
            [[(0.08, 0.20), (0.18, 0.20), (0.18, 0.38), (0.08, 0.38)]],
        ),
        (
            _rect(),
            [[(0.08, 0.20), (0.18, 0.20), (0.18, 0.38), (0.08, 0.38)]],
            _rect(),
            [],
        ),
        (
            _rect(),
            [[(0.04, 0.10), (0.12, 0.10), (0.12, 0.24), (0.04, 0.24)]],
            _rect(),
            [[(0.16, 0.32), (0.24, 0.32), (0.24, 0.48), (0.16, 0.48)]],
        ),
    ],
)
def test_torsion_subdivision_geometry_rejects_mismatched_valid_representations(
    section_outer,
    section_holes,
    raw_outer,
    raw_holes,
):
    section = section_core.Section.from_polygon(section_outer, holes=section_holes)
    inp = _torsion_subdivision_geometry_input(
        section=section,
        outer=raw_outer,
        holes=raw_holes,
    )
    before_outer = copy.deepcopy(inp["outer"])
    before_holes = copy.deepcopy(inp["holes"])
    before_rings = [ring.copy() for ring in section.concrete]

    assert not capacity.combined_torsion_subdivision_geometry_is_valid(inp)
    assert inp["section"] is section
    assert inp["outer"] == before_outer
    assert inp["holes"] == before_holes
    assert all(
        np.array_equal(actual, retained)
        for actual, retained in zip(section.concrete, before_rings, strict=True)
    )


@pytest.mark.parametrize(
    "section",
    [
        SimpleNamespace(require_valid_geometry=lambda: None),
        _TopologySection(concrete=()),
        _TopologySection(concrete="rings"),
        _TopologySection(concrete=(((0.0, 0.0), (0.3, 0.0)),)),
    ],
)
def test_torsion_subdivision_geometry_rejects_missing_or_malformed_section_rings(
    section,
):
    inp = _torsion_subdivision_geometry_input(section=section)

    assert not capacity.combined_torsion_subdivision_geometry_is_valid(inp)


@pytest.mark.parametrize(
    ("concrete_factory", "expected_first"),
    [
        pytest.param(
            lambda: {tuple(_rect()): None},
            None,
            id="mapping",
        ),
        pytest.param(
            lambda: iter((tuple(_rect()),)),
            tuple(_rect()),
            id="one-shot-iterator",
        ),
    ],
)
def test_torsion_subdivision_geometry_rejects_nonrepeatable_section_collections(
    concrete_factory,
    expected_first,
):
    section = _TopologySection(concrete=concrete_factory())
    inp = _torsion_subdivision_geometry_input(section=section)

    assert not capacity.combined_torsion_subdivision_geometry_is_valid(inp)
    if expected_first is not None:
        assert next(section.concrete) == expected_first


def test_torsion_subdivision_geometry_preflights_real_section_before_validation():
    section = section_core.Section.from_polygon(_rect())
    retained_ring = tuple(_rect())
    concrete = iter((retained_ring,))
    section.concrete = concrete
    inp = _torsion_subdivision_geometry_input(section=section)

    assert not capacity.combined_torsion_subdivision_geometry_is_valid(inp)
    assert next(concrete) == retained_ring


@pytest.mark.parametrize(
    "holes_factory",
    [
        pytest.param(dict, id="empty-mapping"),
        pytest.param(
            lambda: {
                ((0.08, 0.20), (0.18, 0.20), (0.18, 0.38), (0.08, 0.38)): None
            },
            id="ring-keyed-mapping",
        ),
    ],
)
def test_torsion_subdivision_geometry_rejects_mapping_raw_holes(holes_factory):
    holes = holes_factory()
    inp = _torsion_subdivision_geometry_input(holes=holes)
    before = copy.deepcopy(inp)

    assert not capacity.combined_torsion_subdivision_geometry_is_valid(inp)
    assert inp == before


def test_torsion_subdivision_geometry_rejects_raw_hole_iterator_without_consuming():
    hole = ((0.08, 0.20), (0.18, 0.20), (0.18, 0.38), (0.08, 0.38))
    holes = iter((hole,))
    inp = _torsion_subdivision_geometry_input(holes=holes)

    assert not capacity.combined_torsion_subdivision_geometry_is_valid(inp)
    assert next(holes) == hole


@pytest.mark.parametrize(
    "bad_input",
    [None, False, 0, 1, "mapping", b"mapping", [], (), object()],
)
def test_torsion_subdivision_geometry_rejects_malformed_top_level(bad_input):
    assert not capacity.combined_torsion_subdivision_geometry_is_valid(
        bad_input
    )


@pytest.mark.parametrize("missing_key", ["outer", "holes"])
def test_torsion_subdivision_geometry_requires_both_raw_geometry_keys(
    missing_key,
):
    inp = _torsion_subdivision_geometry_input()
    del inp[missing_key]
    before = copy.deepcopy(inp)

    assert not capacity.combined_torsion_subdivision_geometry_is_valid(inp)
    assert inp == before


@pytest.mark.parametrize(
    "section_error",
    [ValueError, TypeError, ArithmeticError, OverflowError],
)
def test_torsion_subdivision_geometry_rejects_invalid_section_with_valid_raw(
    section_error,
):
    inp = _torsion_subdivision_geometry_input(
        section=_TopologySection(section_error)
    )
    before = copy.deepcopy(inp)

    assert not capacity.combined_torsion_subdivision_geometry_is_valid(inp)
    assert inp == before


@pytest.mark.parametrize(
    ("outer", "holes"),
    [
        (None, []),
        ([], []),
        ([(0.0, 0.0), (0.3, 0.0)], []),
        (
            [(0.0, 0.0), (0.3, 0.6), (0.0, 0.6), (0.3, 0.0)],
            [],
        ),
        (
            [
                (0.0, 0.0),
                (0.3, 0.0),
                (0.3, 0.6),
                (0.3, 0.0),
                (0.0, 0.6),
            ],
            [],
        ),
        (_rect(), "holes"),
        (_rect(), [None]),
        (_rect(), [[(0.0, 0.0), (0.1, 0.0)]]),
        (
            _rect(),
            [[(0.1, 0.2), (0.2, 0.4), (0.1, 0.4), (0.2, 0.2)]],
        ),
    ],
)
def test_torsion_subdivision_geometry_rejects_stale_raw_with_valid_section(
    outer,
    holes,
):
    inp = _torsion_subdivision_geometry_input(
        section=_TopologySection(),
        outer=outer,
        holes=holes,
    )
    before = copy.deepcopy(inp)

    assert not capacity.combined_torsion_subdivision_geometry_is_valid(inp)
    assert inp == before


def test_torsion_subdivision_geometry_has_dormant_one_object_boundary():
    signature = inspect.signature(
        capacity.combined_torsion_subdivision_geometry_is_valid
    )
    parameters = tuple(signature.parameters.values())
    assert tuple(parameter.name for parameter in parameters) == ("inp",)
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters[0].default is inspect.Parameter.empty


def _torsion_subdivision_input(
    *,
    section=...,
    outer=None,
    holes=...,
    rectangles=...,
    wall_override=0.0,
):
    inp = {
        "outer": _rect() if outer is None else outer,
        "holes": [] if holes is ... else holes,
        "torsion_subdivide": True,
        "torsion_tef": wall_override,
        "torsion_subrects": (
            [(150.0, 300.0, 300.0, 600.0)]
            if rectangles is ...
            else rectangles
        ),
    }
    if section is not ...:
        inp["section"] = section
    return inp


@pytest.mark.parametrize(
    "inp",
    [
        _torsion_subdivision_input(),
        _torsion_subdivision_input(
            outer=[
                (-0.15, -0.30),
                (0.15, -0.30),
                (0.15, 0.30),
                (-0.15, 0.30),
            ],
            rectangles=(
                (-75.0, 0.0, 150.0, 600.0),
                (75.0, 0.0, 150.0, 600.0),
            ),
            wall_override=-0.0,
        ),
        _torsion_subdivision_input(
            rectangles=[
                (50.0, 300.0, 100.0, 600.0),
                (150.0, 300.0, 100.0, 600.0),
                (250.0, 300.0, 100.0, 600.0),
            ],
            wall_override=np.float64(0.0),
        ),
        _torsion_subdivision_input(
            holes=[
                [(0.1, 0.2), (0.2, 0.2), (0.2, 0.4), (0.1, 0.4)]
            ],
            rectangles=[
                (150.0, 100.0, 300.0, 200.0),
                (150.0, 500.0, 300.0, 200.0),
                (50.0, 300.0, 100.0, 200.0),
                (250.0, 300.0, 100.0, 200.0),
            ],
        ),
        _torsion_subdivision_input(
            section=section_core.Section.from_polygon(_rect()),
        ),
        _torsion_subdivision_input(
            holes=None,
            rectangles=[[150.0, 300.0, 300.0, 600.0]],
        ),
    ],
)
def test_torsion_subdivision_input_accepts_exact_producer_partition(inp):
    retained_section = inp.get("section")
    retained_wall_override = inp["torsion_tef"]
    before_outer = copy.deepcopy(inp["outer"])
    before_holes = copy.deepcopy(inp["holes"])
    before_rectangles = copy.deepcopy(inp["torsion_subrects"])

    result = capacity.combined_torsion_subdivision_input_is_valid(inp)

    assert result is True
    assert inp.get("section") is retained_section
    assert inp["outer"] == before_outer
    assert inp["holes"] == before_holes
    assert inp["torsion_subrects"] == before_rectangles
    assert inp["torsion_tef"] is retained_wall_override


@pytest.mark.parametrize(
    "bad_input",
    [None, False, 0, 1, "mapping", b"mapping", [], (), object()],
)
def test_torsion_subdivision_input_rejects_malformed_top_level(bad_input):
    assert not capacity.combined_torsion_subdivision_input_is_valid(bad_input)


@pytest.mark.parametrize("authority", [None, False, 0, 1, "true", [], ()])
def test_torsion_subdivision_input_requires_exact_active_authority(authority):
    inp = _torsion_subdivision_input()
    inp["torsion_subdivide"] = authority
    before = copy.deepcopy(inp)

    assert not capacity.combined_torsion_subdivision_input_is_valid(inp)
    assert inp == before

    missing = _torsion_subdivision_input()
    del missing["torsion_subdivide"]
    missing_before = copy.deepcopy(missing)
    assert not capacity.combined_torsion_subdivision_input_is_valid(missing)
    assert missing == missing_before


@pytest.mark.parametrize(
    "wall_override",
    [
        None,
        False,
        True,
        np.bool_(False),
        "0",
        b"0",
        -1.0,
        -1.0e-300,
        1.0e-300,
        math.nan,
        math.inf,
        -math.inf,
        10**400,
        SimpleNamespace(),
        _ValueErrorFloat(),
    ],
)
def test_torsion_subdivision_input_requires_exact_zero_wall_override(
    wall_override,
):
    inp = _torsion_subdivision_input(wall_override=wall_override)
    before = copy.deepcopy(inp)

    assert not capacity.combined_torsion_subdivision_input_is_valid(inp)
    assert inp == before

    missing = _torsion_subdivision_input()
    del missing["torsion_tef"]
    missing_before = copy.deepcopy(missing)
    assert not capacity.combined_torsion_subdivision_input_is_valid(missing)
    assert missing == missing_before


@pytest.mark.parametrize(
    "rectangles",
    [
        None,
        [],
        "rectangles",
        b"rectangles",
        {},
        [None],
        [{0: 150.0, 1: 300.0, 2: 300.0, 3: 600.0}],
        [(150.0, 300.0, 300.0)],
        [(150.0, 300.0, 300.0, 600.0, 1.0)],
        [(True, 300.0, 300.0, 600.0)],
        [(150.0, "300", 300.0, 600.0)],
        [(Decimal("150"), 300.0, 300.0, 600.0)],
        [(150.0, Decimal("300"), 300.0, 600.0)],
        [(150.0, 300.0, Decimal("300"), 600.0)],
        [(150.0, 300.0, 300.0, Decimal("600"))],
        [(_FloatOnly(150.0), 300.0, 300.0, 600.0)],
        [(150.0, _FloatOnly(300.0), 300.0, 600.0)],
        [(150.0, 300.0, _FloatOnly(300.0), 600.0)],
        [(150.0, 300.0, 300.0, _FloatOnly(600.0))],
        [(150.0, _ValueErrorFloat(), 300.0, 600.0)],
        [(150.0, SimpleNamespace(), 300.0, 600.0)],
        [(150.0, 300.0, 0.0, 600.0)],
        [(150.0, 300.0, -1.0, 600.0)],
        [(150.0, 300.0, math.nan, 600.0)],
        [(150.0, 300.0, math.inf, 600.0)],
        [(150.0, 300.0, 10**400, 600.0)],
        [(0.0, 0.0, 1.0e308, 1.0e308)],
        [
            (0.0, 0.0, 1.0e157, 1.0e157),
            (0.0, 0.0, 1.0e157, 1.0e157),
        ],
        [(145.0, 300.0, 290.0, 600.0)],
        [
            (100.0, 300.0, 200.0, 600.0),
            (200.0, 300.0, 200.0, 600.0),
        ],
        [(350.0, 300.0, 300.0, 600.0)],
    ],
)
def test_torsion_subdivision_input_rejects_malformed_or_invalid_partition(
    rectangles,
):
    inp = _torsion_subdivision_input(rectangles=rectangles)
    before = copy.deepcopy(inp)

    assert not capacity.combined_torsion_subdivision_input_is_valid(inp)
    assert inp == before

    missing = _torsion_subdivision_input()
    del missing["torsion_subrects"]
    missing_before = copy.deepcopy(missing)
    assert not capacity.combined_torsion_subdivision_input_is_valid(missing)
    assert missing == missing_before


def test_torsion_subdivision_input_rejects_partition_iterator_without_consuming():
    rectangle = (150.0, 300.0, 300.0, 600.0)
    rectangles = iter((rectangle,))
    inp = _torsion_subdivision_input(rectangles=rectangles)

    assert not capacity.combined_torsion_subdivision_input_is_valid(inp)
    assert next(rectangles) == rectangle

    rectangle_values = iter(rectangle)
    item_iterator = _torsion_subdivision_input(rectangles=[rectangle_values])
    assert not capacity.combined_torsion_subdivision_input_is_valid(
        item_iterator
    )
    assert next(rectangle_values) == rectangle[0]


def test_torsion_subdivision_input_delegates_exact_geometry_authority():
    malformed_hole = _torsion_subdivision_input(
        holes=[[(0.0, 0.0), (0.1, 0.0)]],
    )
    assert not capacity.combined_torsion_subdivision_input_is_valid(
        malformed_hole
    )

    section = section_core.Section.from_polygon(_rect(b=0.4))
    mismatched_section = _torsion_subdivision_input(section=section)
    before_rings = [ring.copy() for ring in section.concrete]

    assert not capacity.combined_torsion_subdivision_input_is_valid(
        mismatched_section
    )
    assert all(
        np.array_equal(actual, retained)
        for actual, retained in zip(section.concrete, before_rings, strict=True)
    )


def test_torsion_subdivision_input_has_dormant_one_object_boundary():
    signature = inspect.signature(
        capacity.combined_torsion_subdivision_input_is_valid
    )
    parameters = tuple(signature.parameters.values())
    assert tuple(parameter.name for parameter in parameters) == ("inp",)
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters[0].default is inspect.Parameter.empty


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


def test_shear_lever_arm_preserves_finite_and_fails_closed_on_nonconvergence(
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
    lever, reason = capacity.shear_lever_arm(inp, "x", True, 550.0)
    assert lever is None
    assert "did not converge" in reason


@pytest.mark.parametrize(("axis", "expected_mm"), (("x", 420.0), ("y", 310.0)))
@pytest.mark.parametrize("tension_low", (True, False))
@pytest.mark.parametrize("axial_kn", (-600.0, 250.0))
def test_shear_lever_arm_uses_the_exact_face_state_independent_of_sweep(
    monkeypatch,
    axis,
    expected_mm,
    tension_low,
    axial_kn,
):
    called_angles = []

    def exact_face(*args, **kwargs):
        called_angles.append(args[4])
        return _plastic_point(dx=-0.310, dy=0.420)

    monkeypatch.setattr(capacity, "plastic_capacity_at_angle", exact_face)
    inp = _member_input(P_pl=axial_kn)
    inp.update(pl_angle_start=15.0, pl_angle_end=75.0, pl_angle_step=30.0)

    lever, source = capacity.shear_lever_arm(
        inp, axis, tension_low, 550.0
    )

    assert lever == pytest.approx(expected_mm)
    assert source == "plastic internal lever arm"
    expected_angle = (
        90.0 if axis == "x" and tension_low
        else 270.0 if axis == "x"
        else 0.0 if tension_low
        else 180.0
    )
    assert called_angles == [expected_angle]


@pytest.mark.parametrize(
    "depth",
    [True, -1.0, math.nan, math.inf, -math.inf, "550", 10 ** 4000],
)
def test_shear_lever_arm_rejects_malformed_effective_depth(depth):
    with pytest.raises(capacity.CapacityInputError, match="non-negative finite"):
        capacity.shear_lever_arm(
            _member_input(section=None),
            "x",
            True,
            depth,
        )


def test_shear_lever_arm_with_no_section_never_invents_an_arm():
    lever, reason = capacity.shear_lever_arm(
        _member_input(section=None),
        "x",
        True,
        0.0,
    )
    assert lever is None
    assert "section model" in reason


@pytest.mark.parametrize(("axis", "component"), (("x", "dy"), ("y", "dx")))
@pytest.mark.parametrize("tension_low", (True, False))
def test_shear_lever_arm_fails_closed_on_a_degenerate_face_component(
    monkeypatch,
    axis,
    component,
    tension_low,
):
    point = _plastic_point()
    setattr(point, component, 0.0)
    monkeypatch.setattr(
        capacity,
        "plastic_capacity_at_angle",
        lambda *args, **kwargs: point,
    )

    lever, reason = capacity.shear_lever_arm(
        _member_input(), axis, tension_low, 550.0
    )

    assert lever is None
    assert "zero or degenerate" in reason


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


def test_shear_face_mrd_translates_conditional_and_fallback_resistance(
    monkeypatch,
):
    inp = _member_input()
    received = {}

    def conditional(*args, **kwargs):
        received.update(kwargs)
        return 85.0, True

    monkeypatch.setattr(capacity, "conditional_capacity", conditional)
    assert capacity.shear_face_mrd(
        inp,
        "x",
        True,
        25.0,
        moment_reference_shift=30.0,
    ) == (85.0, True)
    assert received["own_moment_offset"] == pytest.approx(30.0)

    monkeypatch.setattr(
        capacity,
        "conditional_capacity",
        lambda *args, **kwargs: (0.0, False),
    )
    monkeypatch.setattr(
        capacity,
        "plastic_capacity_at_angle",
        lambda *args, **kwargs: _plastic_point(Mx=120.0),
    )
    assert capacity.shear_face_mrd(
        inp,
        "x",
        True,
        25.0,
        moment_reference_shift=-20.0,
    ) == (100.0, False)
    assert capacity.shear_face_mrd(
        inp,
        "x",
        True,
        25.0,
        moment_reference_shift=-200.0,
    ) == (0.0, False)


@pytest.mark.parametrize("shift", (True, math.nan, math.inf, "reference"))
def test_shear_face_mrd_rejects_invalid_reference_shift(shift):
    with pytest.raises(capacity.CapacityResultError, match="reference shift"):
        capacity.shear_face_mrd(
            _member_input(),
            "x",
            True,
            25.0,
            moment_reference_shift=shift,
        )


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


def test_torsion_longitudinal_shortfall_is_a_definite_failure():
    inp = _member_input(
        bars=[(0.0, 0.0, 1000.0)],
        bar_materials=[SimpleNamespace(fytk=500.0, gamma_y=1.0)],
        steel=SimpleNamespace(fytk=500.0, gamma_y=1.0),
    )

    result = capacity.torsion_longitudinal_assessment(
        inp,
        (1176.68,),
        resistance_assessed=True,
    )

    assert result["status"] == "FAIL"
    assert result["ok"] is False
    assert result["required_asl_mm2"] == pytest.approx(1176.68)
    assert result["provided_gross_area_mm2"] == pytest.approx(1000.0)
    assert result["provided_equivalent_area_mm2"] == pytest.approx(1000.0)
    assert result["demand_ratio"] == pytest.approx(1.17668)
    assert result["area_sufficient"] is False
    assert result["reason"] == (
        "longitudinal_torsion_reinforcement_insufficient"
    )


def test_torsion_longitudinal_apparent_area_remains_not_assessed():
    inp = _member_input(
        bars=[(-0.1, -0.2, 900.0), (0.1, 0.2, 900.0)],
        bar_materials=[
            SimpleNamespace(fytk=500.0, gamma_y=1.0),
            SimpleNamespace(fytk=600.0, gamma_y=1.2),
        ],
        steel=SimpleNamespace(fytk=500.0, gamma_y=1.0),
    )

    result = capacity.torsion_longitudinal_assessment(
        inp,
        (400.0, 800.0),
        resistance_assessed=True,
    )

    assert result["required_by_tube_mm2"] == pytest.approx((400.0, 800.0))
    assert result["required_asl_mm2"] == pytest.approx(1200.0)
    assert result["provided_gross_area_mm2"] == pytest.approx(1800.0)
    assert result["provided_design_force_kn"] == pytest.approx(900.0)
    assert result["provided_equivalent_area_mm2"] == pytest.approx(1800.0)
    assert result["area_sufficient"] is True
    assert result["status"] == "NOT ASSESSED"
    assert result["ok"] is None
    assert result["distribution_verified"] is False
    assert result["all_perimeter_sides_verified"] is False
    assert result["bending_reserve_verified"] is False
    assert result["anchorage_verified"] is False
    assert result["tube_allocation_verified"] is False


def test_torsion_longitudinal_uses_each_modelled_bar_design_strength():
    inp = _member_input(
        bars=[(-0.1, 0.0, 500.0), (0.1, 0.0, 500.0)],
        bar_materials=[
            SimpleNamespace(fytk=500.0, gamma_y=1.0),
            SimpleNamespace(fytk=600.0, gamma_y=1.0),
        ],
        steel=SimpleNamespace(fytk=500.0, gamma_y=1.0),
    )

    result = capacity.torsion_longitudinal_assessment(
        inp,
        (1050.0,),
        resistance_assessed=True,
    )

    assert result["provided_gross_area_mm2"] == pytest.approx(1000.0)
    assert result["provided_design_force_kn"] == pytest.approx(550.0)
    assert result["provided_equivalent_area_mm2"] == pytest.approx(1100.0)
    assert result["area_sufficient"] is True
    assert result["status"] == "NOT ASSESSED"


def test_torsion_longitudinal_zero_demand_passes_without_inventing_detailing():
    result = capacity.torsion_longitudinal_assessment(
        _member_input(bars=[], bar_materials=[]),
        (0.0,),
        resistance_assessed=True,
    )

    assert result["status"] == "PASS"
    assert result["ok"] is True
    assert result["demand_ratio"] == 0.0
    assert result["distribution_verified"] is False
    assert result["anchorage_verified"] is False


def test_torsion_longitudinal_missing_component_or_material_evidence_fails_closed():
    missing_component = capacity.torsion_longitudinal_assessment(
        _member_input(),
        (100.0,),
        resistance_assessed=False,
    )
    mismatched_materials = capacity.torsion_longitudinal_assessment(
        _member_input(bar_materials=[]),
        (100.0,),
        resistance_assessed=True,
    )

    for result in (missing_component, mismatched_materials):
        assert result["status"] == "NOT ASSESSED"
        assert result["ok"] is None
        assert result["area_sufficient"] is None
        assert result["reason"] == (
            "longitudinal_torsion_reinforcement_evidence_unavailable"
        )


def _torsion_cracking_result(method, gamma_ct, demand=28.0):
    ctx = capacity.build_torsion_context(
        _torsion_input(
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


@pytest.mark.parametrize(
    "method",
    [codes.EC2_2005.label, codes.EC2_2005_DKNA.label],
)
def test_tube_torsion_angle_gate_precedes_angle_resistance_and_demand_kernels(
    monkeypatch,
    method,
):
    inp = _torsion_input(
        torsion_on=True,
        torsion_method=method,
        torsion_gamma_ct=(
            codes.EC2_2005.gamma_ct
            if method == codes.EC2_2005.label
            else codes.EC2_2005_DKNA.gamma_ct
        ),
        shear_links=True,
        strut_cot_min=1.0,
        strut_cot_max=3.0,
        torsion_T=100.0,
    )
    context = capacity.build_torsion_context(inp, 0.0)

    def forbidden(*args, **kwargs):
        del args, kwargs
        pytest.fail("angle-dependent torsion kernel entered outside its range")

    monkeypatch.setattr(shear, "optimum_strut_angle", forbidden)
    monkeypatch.setattr(torsion, "trd_s_result", forbidden)
    monkeypatch.setattr(torsion, "trd_max_result", forbidden)
    monkeypatch.setattr(torsion, "asl_required_result", forbidden)

    result = capacity.tube_torsion(
        context["tube"], context["t_ed"], **context["_tk"]
    )

    assert result["tube_valid"] is True
    assert result["valid"] is False
    assert result["transverse_resistance_assessed"] is False
    assert result["assessment_reason"] == shear.STRUT_ANGLE_OUT_OF_RANGE_REASON
    assert result["trd_s"] is None
    assert result["trd_max"] is None
    assert result["trd"] is None
    assert result["util"] is None
    assert result["asl_req"] is None
    assert result["trd_c"] > 0.0


def test_zero_torsion_does_not_activate_an_out_of_range_interval():
    inp = _torsion_input(
        torsion_on=True,
        shear_links=True,
        strut_cot_min=1.0,
        strut_cot_max=3.0,
        torsion_T=0.0,
    )
    context = capacity.build_torsion_context(inp, 0.0)
    result = capacity.tube_torsion(
        context["tube"], context["t_ed"], **context["_tk"]
    )

    assert context["angle_applicability"]["active"] is False
    assert context["angle_applicability"]["status"] == "NOT APPLICABLE"
    assert result["valid"] is True
    assert result["trd"] > 0.0
    assert result["util"] == 0.0


@pytest.mark.parametrize(
    "method",
    [codes.EC2_2005.label, codes.EC2_2005_DKNA.label],
)
def test_tube_torsion_requires_current_closed_link_authority(method):
    absent_input = _torsion_input(
        torsion_on=True,
        torsion_method=method,
        torsion_gamma_ct=(
            codes.EC2_2005.gamma_ct
            if method == codes.EC2_2005.label
            else codes.EC2_2005_DKNA.gamma_ct
        ),
        shear_links=False,
        shear_link_dia=16.0,
        shear_link_s=100.0,
    )
    absent_section = absent_input["section"]
    absent_before = copy.deepcopy(
        {key: value for key, value in absent_input.items() if key != "section"}
    )
    absent_context = capacity.build_torsion_context(absent_input, 0.0)
    absent = capacity.tube_torsion(
        absent_context["tube"],
        absent_context["t_ed"],
        **absent_context["_tk"],
    )

    assert absent_input["section"] is absent_section
    assert {
        key: value for key, value in absent_input.items() if key != "section"
    } == absent_before
    assert absent_context["closed_links_present"] is False
    assert absent_context["asw_t"] == 0.0
    assert absent_context["asw_over_s_t"] == 0.0
    assert absent["tube_valid"] is True
    assert absent["closed_links_present"] is False
    assert absent["full_resistance_assessed"] is False
    assert absent["assessment_reason"] == "closed_links_not_present"
    assert absent["valid"] is False
    assert absent["trd_s"] == 0.0
    assert absent["trd"] is None
    assert absent["util"] is None
    assert absent["governs"] is None
    assert absent["trd_max"] > 0.0
    assert absent["trd_c"] > 0.0

    below_unity_band_context = capacity.build_torsion_context(
        dict(
            absent_input,
            strut_cot_min=0.5,
            strut_cot_max=0.8,
        ),
        0.0,
    )
    below_unity_band = capacity.tube_torsion(
        below_unity_band_context["tube"],
        below_unity_band_context["t_ed"],
        **below_unity_band_context["_tk"],
    )
    assert below_unity_band["valid"] is False
    assert below_unity_band["tube_valid"] is True
    assert below_unity_band["transverse_resistance_assessed"] is False
    assert below_unity_band["assessment_reason"] == (
        shear.STRUT_ANGLE_OUT_OF_RANGE_REASON
    )
    assert below_unity_band["cot"] is None
    assert below_unity_band["theta_deg"] is None
    assert below_unity_band["trd_s"] is None
    assert below_unity_band["trd_max"] is None
    assert below_unity_band["trd"] is None
    assert below_unity_band["util"] is None
    assert below_unity_band["asl_req"] is None
    assert below_unity_band["trd_c"] > 0.0
    assert below_unity_band["angle_applicability"]["requested_min"] == 0.5
    assert below_unity_band["angle_applicability"]["requested_max"] == 0.8

    stale_detail_kwargs = dict(absent_context["_tk"])
    stale_detail_kwargs["nu_detail"] = True
    stale_detail = capacity.tube_torsion(
        absent_context["tube"],
        absent_context["t_ed"],
        **stale_detail_kwargs,
    )
    assert stale_detail["nu"] == pytest.approx(absent["nu"])
    assert stale_detail["trd_max"] == pytest.approx(absent["trd_max"])

    absent_missing_link_inputs = dict(absent_input)
    for key in ("shear_link_dia", "shear_link_s", "shear_fywk"):
        absent_missing_link_inputs.pop(key)
    absent_missing_context = capacity.build_torsion_context(
        absent_missing_link_inputs,
        0.0,
    )
    assert absent_missing_context["asw_t"] == 0.0
    assert absent_missing_context["asw_over_s_t"] == 0.0
    assert absent_missing_context["_tk"]["fywd"] == 0.0

    absent_zero_geometry_context = capacity.build_torsion_context(
        dict(
            absent_input,
            shear_link_dia=0.0,
            shear_link_s=0.0,
        ),
        0.0,
    )
    absent_zero_geometry = capacity.tube_torsion(
        absent_zero_geometry_context["tube"],
        absent_zero_geometry_context["t_ed"],
        **absent_zero_geometry_context["_tk"],
    )
    assert absent_zero_geometry["assessment_reason"] == (
        "closed_links_not_present"
    )
    assert absent_zero_geometry["trd"] is None
    assert absent_zero_geometry["trd_max"] > 0.0

    current_input = dict(absent_input, shear_links=True)
    current_context = capacity.build_torsion_context(current_input, 0.0)
    current = capacity.tube_torsion(
        current_context["tube"],
        current_context["t_ed"],
        **current_context["_tk"],
    )

    assert current_context["closed_links_present"] is True
    assert current_context["asw_over_s_t"] > 0.0
    assert current["closed_links_present"] is True
    assert current["full_resistance_assessed"] is True
    assert current["valid"] is True
    assert current["trd"] == pytest.approx(
        min(current["trd_s"], current["trd_max"])
    )
    assert current["util"] == pytest.approx(
        current["t_ed"] / current["trd"]
    )

    steel_governing_context = capacity.build_torsion_context(
        dict(
            absent_input,
            shear_links=True,
            shear_link_dia=2.0,
            shear_link_s=500.0,
        ),
        0.0,
    )
    steel_governing = capacity.tube_torsion(
        steel_governing_context["tube"],
        steel_governing_context["t_ed"],
        **steel_governing_context["_tk"],
    )
    assert steel_governing["full_resistance_assessed"] is True
    assert steel_governing["governs"] == "stirrups (TRd,s)"

    concrete_governing_context = capacity.build_torsion_context(
        dict(
            absent_input,
            shear_links=True,
            shear_link_dia=32.0,
            shear_link_s=50.0,
        ),
        0.0,
    )
    concrete_governing = capacity.tube_torsion(
        concrete_governing_context["tube"],
        concrete_governing_context["t_ed"],
        **concrete_governing_context["_tk"],
    )
    assert concrete_governing["full_resistance_assessed"] is True
    assert concrete_governing["governs"] == "crushing (TRd,max)"

    zero_resistance_kwargs = dict(current_context["_tk"])
    zero_resistance_kwargs["fcd"] = 0.0
    assessed_zero = capacity.tube_torsion(
        current_context["tube"],
        current_context["t_ed"],
        **zero_resistance_kwargs,
    )
    assert assessed_zero["full_resistance_assessed"] is True
    assert assessed_zero["valid"] is True
    assert assessed_zero["trd"] == 0.0
    assert math.isinf(assessed_zero["util"])
    assert assessed_zero["governs"] == "crushing (TRd,max)"

    zero_input = dict(current_input, shear_link_dia=0.0)
    zero_context = capacity.build_torsion_context(zero_input, 0.0)
    zero = capacity.tube_torsion(
        zero_context["tube"],
        zero_context["t_ed"],
        **zero_context["_tk"],
    )
    assert zero["closed_links_present"] is True
    assert zero["full_resistance_assessed"] is False
    assert (
        zero["assessment_reason"]
        == "closed_link_reinforcement_not_positive"
    )


def test_torsion_uses_one_closed_loop_leg_independent_of_shear_leg_count():
    one_leg = capacity.build_torsion_context(
        _torsion_input(
            torsion_on=True,
            shear_links=True,
            shear_link_legs=1.0,
        ),
        0.0,
    )
    many_legs = capacity.build_torsion_context(
        _torsion_input(
            torsion_on=True,
            shear_links=True,
            shear_link_legs=8.0,
        ),
        0.0,
    )

    assert many_legs["asw_t"] == pytest.approx(one_leg["asw_t"])
    assert many_legs["asw_over_s_t"] == pytest.approx(
        one_leg["asw_over_s_t"]
    )
    one_result = capacity.tube_torsion(
        one_leg["tube"], one_leg["t_ed"], **one_leg["_tk"]
    )
    many_result = capacity.tube_torsion(
        many_legs["tube"], many_legs["t_ed"], **many_legs["_tk"]
    )
    assert many_result["trd_s"] == pytest.approx(one_result["trd_s"])


@pytest.mark.parametrize(
    "authority",
    [None, 0, 1, "false", np.bool_(False), [], ()],
)
def test_build_torsion_context_rejects_non_boolean_link_authority(authority):
    inp = _member_input(
        section=None,
        torsion_on=True,
        shear_links=authority,
    )
    before = copy.deepcopy(inp)

    with pytest.raises(
        capacity.CapacityInputError,
        match="shared links / closed torsion stirrups must be a Boolean",
    ):
        capacity.build_torsion_context(inp, 0.0)

    if isinstance(authority, np.bool_):
        assert isinstance(inp["shear_links"], np.bool_)
        assert bool(inp["shear_links"]) is bool(before["shear_links"])
    else:
        assert inp == before


@pytest.mark.parametrize(
    "authority",
    [None, 0, 1, "false", np.bool_(False), [], ()],
)
def test_build_shear_context_rejects_non_boolean_link_authority(authority):
    inp = _member_input(shear_on=True, shear_links=authority)

    with pytest.raises(
        capacity.CapacityInputError,
        match="shared links / closed torsion stirrups must be a Boolean",
    ):
        capacity.build_shear_context(inp, 0.0, 0.0)


def test_directional_shear_rejects_malformed_authority_without_live_action():
    inp = _member_input(
        shear_links="false",
        shear_Vx=0.0,
        shear_Vy=0.0,
    )
    section = inp.get("section")
    before = copy.deepcopy({
        key: value for key, value in inp.items() if key != "section"
    })

    with pytest.raises(
        capacity.CapacityInputError,
        match="shared links / closed torsion stirrups must be a Boolean",
    ):
        capacity.build_directional_shear_contexts(inp, 0.0, 0.0)

    assert inp.get("section") is section
    assert {
        key: value for key, value in inp.items() if key != "section"
    } == before


def test_build_torsion_context_requires_link_authority_and_gates_nu_v():
    missing = _member_input(torsion_on=True)
    del missing["shear_links"]
    with pytest.raises(
        capacity.CapacityInputError,
        match="shared links / closed torsion stirrups must be a Boolean",
    ):
        capacity.build_torsion_context(missing, 0.0)

    no_links = capacity.build_torsion_context(
        _torsion_input(
            torsion_on=True,
            shear_links=False,
            torsion_nu_v=True,
        ),
        0.0,
    )
    assert no_links["nu_detail_requested"] is True
    assert no_links["nu_detail"] is False
    assert no_links["nu_detail_applied"] is False

    malformed = _member_input(
        torsion_on=True,
        shear_links=True,
        torsion_nu_v=1,
    )
    with pytest.raises(
        capacity.CapacityInputError,
        match="torsion closed-detailing allowance must be a Boolean",
    ):
        capacity.build_torsion_context(malformed, 0.0)


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


def test_plastic_effective_depths_publish_all_axes_faces_and_bar_populations():
    inp = _member_input(
        bars=[
            (0.15, 0.04, 100.0),
            (0.15, 0.53, 200.0),
            (0.03, 0.30, 300.0),
            (0.26, 0.30, 400.0),
        ]
    )

    rows = capacity.plastic_effective_depths(inp)

    assert [
        (row["axis"], row["tension_low"], row["arm_component"])
        for row in rows
    ] == [
        ("x", True, "z_y"),
        ("x", False, "z_y"),
        ("y", True, "z_x"),
        ("y", False, "z_x"),
    ]
    assert [row["d_mm"] for row in rows] == pytest.approx(
        [560.0, 530.0, 270.0, 260.0]
    )
    assert [row["asl_bar_ids"] for row in rows] == [
        (1,), (2,), (3,), (4,),
    ]
    assert [row["asl_mm2"] for row in rows] == pytest.approx(
        [100.0, 200.0, 300.0, 400.0]
    )
    assert [row["asl_cg_m"] for row in rows] == pytest.approx(
        [0.04, 0.53, 0.03, 0.26]
    )


def test_2023_shear_context_propagates_axial_tension_angle_limit_and_final_fcd(
    monkeypatch,
):
    monkeypatch.setattr(
        capacity,
        "plastic_capacity_at_angle",
        lambda *args, **kwargs: _plastic_point(dy=0.495),
    )
    inp = _member_input(
        shear_method=codes.EC2_2023.label,
        shear_links=True,
        transverse_ductility_class="B",
        P_pl=-400.0,
        plastic_case={"id": "PL-01"},
    )
    _payload, links = capacity.build_shear_context(
        inp,
        n_prestress=0.0,
        n_ed_comp=-400.0,
    )

    assert links is not None and links["model_2023"]
    assert links["z_component"] == "z_y"
    assert links["z_source_angle_deg"] == pytest.approx(90.0)
    assert links["z_source_case"] == "PL-01"
    assert links["z_source_axial_kn"] == pytest.approx(-400.0)
    assert links["angle_limits"]["axial_tension_applied"]
    assert links["angle_limits"]["maximum"] == pytest.approx(
        max(2.5 - 0.1 * 400.0 / inp["shear_V"], 1.0)
    )
    result = links["build"](1.0, links["angle_limits"]["maximum"])
    assert result["valid"]
    assert result["fcd"] == pytest.approx(inp["concrete"].fcd)


@pytest.mark.parametrize(
    ("lever_arm", "prerequisites_available"),
    ((None, False), (495.0, True)),
    ids=("missing-arm", "complete"),
)
def test_shear_angle_prerequisites_are_independent_of_range_applicability(
    monkeypatch,
    lever_arm,
    prerequisites_available,
):
    monkeypatch.setattr(
        capacity,
        "shear_lever_arm",
        lambda *_args, **_kwargs: (
            lever_arm,
            (
                "calculated plastic lever arm unavailable"
                if lever_arm is None
                else "plastic internal lever arm"
            ),
        ),
    )
    inp = _member_input(
        shear_method=codes.EC2_2023.label,
        shear_links=True,
        transverse_ductility_class="A",
        strut_cot_max=2.5,
    )

    _payload, links = capacity.build_shear_context(inp, 0.0, 0.0)

    assert links is not None
    assert links["angle_applicability"]["applicable"] is False
    assert links["angle_applicability"]["permitted_max"] == pytest.approx(2.0)
    assert links["angle_prerequisites_available"] is prerequisites_available


@pytest.mark.parametrize(
    "invalid_legs",
    (True, np.bool_(True), float("nan"), float("inf"), -float("inf")),
    ids=(
        "boolean",
        "numpy-boolean",
        "nan",
        "positive-infinity",
        "negative-infinity",
    ),
)
@pytest.mark.parametrize("entry", ("direct", "directional"))
def test_invalid_shear_link_legs_cannot_satisfy_angle_prerequisites(
    invalid_legs,
    entry,
):
    inp = _member_input(
        section=None,
        shear_links=True,
        shear_link_legs=invalid_legs,
        shear_components={"vx": {"signed_v_ed": 75.0}},
        shear_vx_link_legs=invalid_legs,
        shear_vy_link_legs=2.0,
    )

    if entry == "direct":
        _payload, links = capacity.build_shear_context(inp, 0.0, 0.0)
    else:
        directional = capacity.build_directional_shear_contexts(
            inp, 0.0, 0.0
        )
        _payload, links = directional["vx"]["candidates"][0]

    assert links is not None
    assert links["link_legs"] is None
    assert links["asw"] == 0.0
    assert links["effective_asw_over_s"] == 0.0
    assert links["angle_prerequisites_available"] is False
    result = links["build"](1.0, 2.0)
    assert result["valid"] is False
    assert result["calculation_state"] == "NOT ASSESSED"
    assert result["vrd"] is None
    assert result["reason"] == (
        "Enter a positive finite number of effective link legs for each active "
        "shear direction"
    )


def test_2023_shear_context_uses_the_exact_selected_gamma_v():
    default, _ = capacity.build_shear_context(
        _member_input(
            shear_method=codes.EC2_2023.label,
            shear_gamma_v=1.40,
        ),
        0.0,
        0.0,
    )
    selected, _ = capacity.build_shear_context(
        _member_input(
            shear_method=codes.EC2_2023.label,
            shear_gamma_v=1.25,
        ),
        0.0,
        0.0,
    )

    assert selected["res"]["gamma_v"] == pytest.approx(1.25)
    assert selected["res"]["vrd_c"] == pytest.approx(
        default["res"]["vrd_c"] * 1.40 / 1.25
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
@pytest.mark.parametrize("links_selected", (False, True))
def test_2023_shear_context_rejects_malformed_gamma_v(
    gamma_v,
    links_selected,
):
    inp = _member_input(
        shear_method=codes.EC2_2023.label,
        shear_gamma_v=gamma_v,
        shear_links=links_selected,
    )
    if links_selected:
        inp["section"] = None
    with pytest.raises(
        capacity.CapacityInputError,
        match="gamma_V must be a positive finite real number",
    ) as caught:
        capacity.build_shear_context(inp, 0.0, 0.0)
    assert isinstance(caught.value.engineer_message, EngineerMessage)
    assert caught.value.engineer_message.text == (
        "gamma_V must be a positive finite real number"
    )


@pytest.mark.parametrize("links_selected", (False, True))
def test_2023_shear_context_rejects_a_missing_gamma_v(links_selected):
    inp = _member_input(
        shear_method=codes.EC2_2023.label,
        shear_links=links_selected,
    )
    if links_selected:
        inp["section"] = None
    del inp["shear_gamma_v"]

    with pytest.raises(
        capacity.CapacityInputError,
        match="gamma_V must be a positive finite real number",
    ) as caught:
        capacity.build_shear_context(inp, 0.0, 0.0)
    assert isinstance(caught.value.engineer_message, EngineerMessage)


def test_2023_shear_links_apply_the_exact_selected_gamma_v():
    low_input = _member_input(
        shear_method=codes.EC2_2023.label,
        shear_links=True,
        shear_gamma_v=1.20,
        section=None,
    )
    high_input = dict(low_input, shear_gamma_v=1.80)

    low_payload, low_links = capacity.build_shear_context(low_input, 0.0, 0.0)
    high_payload, high_links = capacity.build_shear_context(high_input, 0.0, 0.0)

    assert low_links is not None and high_links is not None
    assert low_payload["res"]["gamma_v"] == pytest.approx(1.20)
    assert high_payload["res"]["gamma_v"] == pytest.approx(1.80)
    assert low_payload["res"]["vrd_c"] == pytest.approx(
        high_payload["res"]["vrd_c"] * 1.80 / 1.20
    )
    assert low_links["build"](1.0, 2.0) == high_links["build"](1.0, 2.0)


def test_gamma_v_is_isolated_from_2005_links_torsion_and_combined_routes(
    monkeypatch,
):
    low_2005, _ = capacity.build_shear_context(
        _member_input(shear_gamma_v=0.50), 0.0, 0.0
    )
    high_2005, _ = capacity.build_shear_context(
        _member_input(shear_gamma_v=9.00), 0.0, 0.0
    )
    assert low_2005["res"] == high_2005["res"]

    low_input = _member_input(
        shear_method=codes.EC2_2023.label,
        shear_links=True,
        shear_gamma_v=1.20,
        section=None,
    )
    high_input = dict(low_input, shear_gamma_v=1.80)
    _low_payload, low_links = capacity.build_shear_context(
        low_input, 0.0, 0.0
    )
    _high_payload, high_links = capacity.build_shear_context(
        high_input, 0.0, 0.0
    )
    assert low_links is not None and high_links is not None
    assert low_links["build"](1.0, 2.0) == high_links["build"](1.0, 2.0)

    torsion_low = capacity.build_torsion_context(
        _torsion_input(torsion_on=True, shear_gamma_v=0.50), 0.0
    )
    torsion_high = capacity.build_torsion_context(
        _torsion_input(torsion_on=True, shear_gamma_v=9.00), 0.0
    )
    assert torsion_low == torsion_high

    out_low = {
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
    out_high = copy.deepcopy(out_low)
    n = capacity._dkna_action_record("N", 0.0, None, valid=True)
    m = capacity._dkna_action_record("M", 0.2, 1.0, valid=True)
    v = capacity._dkna_action_record("V", 0.3, 1.0, valid=True)
    t = capacity._dkna_action_record("T", 0.4, 1.0, valid=True)
    monkeypatch.setattr(capacity, "_dkna_shear_action_alone", lambda _inp: v)
    monkeypatch.setattr(capacity, "_dkna_torsion_action_alone", lambda _inp: t)
    capacity.finalize_combined(
        _member_input(
            combined_on=True,
            shear_gamma_v=0.50,
            _dkna_nm_action_alone={"n": n, "m": m},
        ),
        out_low,
    )
    capacity.finalize_combined(
        _member_input(
            combined_on=True,
            shear_gamma_v=9.00,
            _dkna_nm_action_alone={"n": n, "m": m},
        ),
        out_high,
    )
    assert out_low["combined"] == out_high["combined"]


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
    assert payload["moment_reference_shift"] == pytest.approx(30.0)


def test_2023_chord_reference_includes_eccentric_locked_in_prestress():
    prestress = _prestress_law()
    inp = _member_input(
        P_pl=100.0,
        Mx_pl=10.0,
        My_pl=0.0,
        shear_method=codes.EC2_2023.label,
        shear_Vy=25.0,
        shear_components={"vy": {"signed_v_ed": 25.0}},
        shear_face_y="auto",
        prestress=prestress,
        tendons=[(0.15, 0.0, 10.0)],
        tendon_materials=[prestress],
    )
    prestress_force = prestress.Es * prestress.IS * 10.0 / 1000.0
    prestress_mx_at_centroid = prestress_force * (0.0 - 0.30)
    expected_shift = 100.0 * 0.30 - prestress_mx_at_centroid

    contexts = capacity.build_directional_shear_contexts(
        inp,
        n_prestress=prestress_force,
        n_ed_comp=-100.0 + prestress_force,
    )
    payload, _links = contexts["vy"]["candidates"][0]

    assert payload["m_prestress"] == pytest.approx(
        prestress_mx_at_centroid
    )
    assert payload["moment_reference_shift"] == pytest.approx(expected_shift)
    assert payload["m_ed_2023"] == pytest.approx(10.0 + expected_shift)
    assert payload["tension_low"] is True


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


@pytest.mark.parametrize(
    ("statuses", "expected_status", "governing_status"),
    [
        (("NOT ASSESSED", "CONDITIONAL"), "NOT ASSESSED", "NOT ASSESSED"),
        (("CONDITIONAL", "CONDITIONAL"), "CONDITIONAL", "CONDITIONAL"),
        (("FAIL", "CONDITIONAL"), "FAIL", "FAIL"),
        (("CONDITIONAL", "PASS"), "CONDITIONAL", "CONDITIONAL"),
    ],
)
def test_mandatory_face_status_order_retains_conditional_authority(
    statuses,
    expected_status,
    governing_status,
):
    candidates = [
        {"status": statuses[0], "util": 0.20},
        {"status": statuses[1], "util": 0.90},
    ]

    governing = max(
        candidates,
        key=lambda item: capacity.assessment_key(
            item["status"], item["util"]
        ),
    )

    assert governing["status"] == governing_status
    assert capacity.aggregate_assessment_status(statuses) == expected_status


def test_mandatory_all_conditional_faces_use_utilisation_as_tie_breaker():
    candidates = [
        {"status": "CONDITIONAL", "util": 0.72},
        {"status": "CONDITIONAL", "util": 0.91},
    ]

    governing = max(
        candidates,
        key=lambda item: capacity.assessment_key(
            item["status"], item["util"]
        ),
    )

    assert governing is candidates[1]
    assert capacity.aggregate_assessment_status(
        item["status"] for item in candidates
    ) == "CONDITIONAL"


def test_build_torsion_context_accepts_exact_partition_and_rejects_gap():
    valid = _torsion_input(
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
    automatic = _torsion_input(
        torsion_on=True,
        torsion_subdivide=True,
        torsion_tef=0.0,
        torsion_subrects=[(150.0, 300.0, 300.0, 600.0)],
    )

    ctx = capacity.build_torsion_context(automatic, 0.0)

    assert ctx["subdivide"] is True
    assert len(ctx["subtubes"]) == 1
    assert ctx["subtubes"][0]["tef_user"] is False
    assert ctx["subtubes"][0]["tef_selection"] == (
        "A/u and reinforcement lower bound"
    )
    assert ctx["subtubes"][0]["wall_evidence"]["complete"] is True

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


def test_torsion_context_recomputes_false_pass_oracle_from_required_160mm_wall():
    inp = _torsion_input(
        outer=_rect(0.4, 0.6),
        bars=_torsion_wall_bars(b=0.4, h=0.6, a=0.08),
        torsion_on=True,
        torsion_T=100.0,
        shear_links=True,
        shear_link_dia=10.0,
        shear_link_s=150.0,
        shear_fywk=500.0,
        strut_cot_min=2.0,
        strut_cot_max=2.0,
    )
    context = capacity.build_torsion_context(inp, 0.0)
    selected = capacity.tube_torsion(
        context["tube"], context["t_ed"], **context["_tk"]
    )
    legacy_tube = torsion.tube_properties(inp["outer"], None)
    unchecked = capacity.tube_torsion(
        legacy_tube, context["t_ed"], **context["_tk"]
    )
    tk = context["_tk"]
    legacy_steel = torsion.trd_s_result(
        legacy_tube["Ak"], tk["fywd"], tk["asw_over_s"], 2.0
    )
    legacy_strut = torsion.trd_max_result(
        tk["fck"],
        tk["tcode"],
        legacy_tube["Ak"],
        legacy_tube["tef"],
        tk["alpha_cw"],
        2.0,
        closed_detailing=(
            tk["closed_links_present"] is True and tk["nu_detail"] is True
        ),
        fcd_mpa=tk["fcd"],
    )
    legacy_selection = torsion.select_full_torsion_resistance(
        legacy_steel.trd_s,
        legacy_strut.trd_max,
        closed_links_present=tk["closed_links_present"],
        asw_over_s=tk["asw_over_s"],
    )

    assert legacy_tube["tef"] == pytest.approx(120.0)
    assert legacy_tube["Ak"] == pytest.approx(0.1344)
    assert legacy_steel.trd_s == pytest.approx(117.2861257340)
    assert legacy_strut.trd_max == pytest.approx(114.4531862069)
    assert legacy_selection.resistance == pytest.approx(114.4531862069)
    assert 100.0 / legacy_selection.resistance == pytest.approx(0.8737200704)
    assert unchecked["valid"] is False
    assert unchecked["tube_valid"] is False
    assert unchecked["assessment_reason"] == (
        "torsion wall reinforcement locations are missing"
    )
    for key in (
        "trd_s",
        "trd_max",
        "trd",
        "trd_c",
        "cot",
        "theta_deg",
        "util",
        "asl_req",
        "nu",
        "governs",
        "angle_selection",
        "steel_resistance",
        "strut_resistance",
        "resistance_selection",
        "cracking_resistance",
        "longitudinal_reinforcement",
    ):
        assert unchecked[key] is None

    assert context["tube"]["tef"] == pytest.approx(160.0)
    assert context["tube"]["Ak"] == pytest.approx(0.1056)
    assert context["tube"]["uk"] == pytest.approx(1.36)
    assert selected["trd_s"] == pytest.approx(92.1533845053)
    assert selected["trd_max"] == pytest.approx(119.9033379310)
    assert selected["trd"] == pytest.approx(92.1533845053)
    assert selected["util"] == pytest.approx(1.0851473450)


def test_tube_torsion_rejects_unchecked_wall_geometry_before_kernels(
    monkeypatch,
):
    context = capacity.build_torsion_context(
        _torsion_input(
            outer=_rect(0.4, 0.6),
            bars=_torsion_wall_bars(b=0.4, h=0.6, a=0.08),
            torsion_on=True,
            torsion_T=100.0,
            shear_links=True,
            shear_link_dia=10.0,
            shear_link_s=150.0,
            strut_cot_min=2.0,
            strut_cot_max=2.0,
        ),
        0.0,
    )
    unchecked = torsion.tube_properties(_rect(0.4, 0.6), None)

    def forbidden(*_args, **_kwargs):
        pytest.fail("unchecked wall geometry entered the torsion kernel")

    monkeypatch.setattr(torsion, "trd_s_result", forbidden)
    result = capacity.tube_torsion(
        unchecked, context["t_ed"], **context["_tk"]
    )

    assert result["valid"] is False
    assert result["transverse_resistance_assessed"] is False
    assert result["assessment_reason"] == (
        "torsion wall reinforcement locations are missing"
    )
    assert result["trd"] is None
    assert result["util"] is None


def test_tube_torsion_rejects_assessed_looking_compound_geometry_before_kernels(
    monkeypatch,
):
    outer = [
        (0.0, 0.0),
        (0.3, 0.0),
        (0.3, 0.1),
        (0.1, 0.1),
        (0.1, 0.3),
        (0.0, 0.3),
    ]
    bars = [
        (0.15, 0.02, 100.0),
        (0.28, 0.05, 100.0),
        (0.20, 0.08, 100.0),
        (0.08, 0.20, 100.0),
        (0.05, 0.28, 100.0),
        (0.02, 0.15, 100.0),
    ]
    tube = torsion.tube_properties_with_reinforcement(outer, None, bars)
    reference = capacity.build_torsion_context(
        _torsion_input(torsion_on=True),
        0.0,
    )

    def forbidden(*_args, **_kwargs):
        pytest.fail("compound geometry entered the torsion resistance kernel")

    monkeypatch.setattr(torsion, "trd_s_result", forbidden)
    result = capacity.tube_torsion(tube, 20.0, **reference["_tk"])

    assert tube["valid"] is False
    assert tube["reason"] == "compound outline requires subdivision"
    assert result["valid"] is False
    assert result["assessment_reason"] == "compound outline requires subdivision"
    assert result["trd"] is None
    assert result["util"] is None
    assert result["asl_req"] is None


def test_mixed_corner_and_mid_face_wall_evidence_fails_before_solver_until_override(
    monkeypatch,
):
    bars = [
        (0.04, 0.08, 100.0),
        (0.36, 0.08, 100.0),
        (0.36, 0.52, 100.0),
        (0.04, 0.52, 100.0),
        (0.20, 0.05, 100.0),
        (0.20, 0.55, 100.0),
    ]
    inp = _torsion_input(
        outer=_rect(0.4, 0.6),
        bars=bars,
        torsion_on=True,
        torsion_T=100.0,
        shear_links=True,
        shear_link_dia=10.0,
        shear_link_s=150.0,
        shear_fywk=500.0,
        strut_cot_min=2.0,
        strut_cot_max=2.0,
    )
    context = capacity.build_torsion_context(inp, 0.0)

    assert context["tube"]["valid"] is False
    assert context["tube"]["reason"] == (
        "torsion wall automatic thickness varies by wall"
    )
    assert [
        wall["a_mm"] for wall in context["tube"]["wall_evidence"]["walls"]
    ] == pytest.approx([80.0, 40.0, 80.0, 40.0])

    def forbidden(*_args, **_kwargs):
        pytest.fail("conflicting wall thickness entered the torsion kernel")

    with monkeypatch.context() as isolated:
        isolated.setattr(torsion, "trd_s_result", forbidden)
        rejected = capacity.tube_torsion(
            context["tube"], context["t_ed"], **context["_tk"]
        )
    assert rejected["valid"] is False
    assert rejected["trd"] is None
    assert rejected["util"] is None

    corrected = capacity.build_torsion_context(
        dict(inp, torsion_tef=160.0),
        0.0,
    )
    accepted = capacity.tube_torsion(
        corrected["tube"], corrected["t_ed"], **corrected["_tk"]
    )
    assert accepted["tube_valid"] is True
    assert accepted["tube"]["tef"] == pytest.approx(160.0)
    assert accepted["trd_s"] == pytest.approx(92.1533845053)
    assert accepted["trd_max"] == pytest.approx(119.9033379310)
    assert accepted["trd"] == pytest.approx(92.1533845053)
    assert accepted["util"] == pytest.approx(1.0851473450)


def test_subdivided_tubes_require_complete_unambiguous_wall_mapping():
    rectangles = [
        (150.0, 300.0, 300.0, 600.0),
        (450.0, 300.0, 300.0, 600.0),
    ]
    complete_bars = [
        *_torsion_wall_bars(b=0.3, h=0.6, a=0.05, total_area=736.5),
        *[
            (x + 0.3, y, area)
            for x, y, area in _torsion_wall_bars(
                b=0.3,
                h=0.6,
                a=0.05,
                total_area=736.5,
            )
        ],
    ]
    complete = capacity.build_torsion_context(
        _torsion_input(
            outer=_rect(0.6, 0.6),
            bars=complete_bars,
            torsion_on=True,
            torsion_subdivide=True,
            torsion_subrects=rectangles,
        ),
        0.0,
    )

    assert complete["subdivide"] is True
    assert all(tube["valid"] for tube in complete["subtubes"])
    assert [tube["tef"] for tube in complete["subtubes"]] == pytest.approx(
        [100.0, 100.0]
    )
    assert all(
        tube["wall_evidence"]["complete"] for tube in complete["subtubes"]
    )
    assert {
        position
        for wall in complete["subtubes"][0]["wall_evidence"]["walls"]
        for position in wall["bar_indices"]
    } == {1, 2, 3, 4}
    assert {
        position
        for wall in complete["subtubes"][1]["wall_evidence"]["walls"]
        for position in wall["bar_indices"]
    } == {5, 6, 7, 8}

    incomplete = capacity.build_torsion_context(
        _torsion_input(
            outer=_rect(0.6, 0.6),
            bars=[bar for bar in complete_bars if bar[0] < 0.55 - 1.0e-12],
            torsion_on=True,
            torsion_subdivide=True,
            torsion_subrects=rectangles,
        ),
        0.0,
    )
    assert incomplete["subdivide"] is True
    assert not all(tube["valid"] for tube in incomplete["subtubes"])
    assert any(
        tube["reason"]
        in {
            "torsion wall reinforcement mapping is incomplete",
            "torsion sub-tube reinforcement mapping is incomplete",
        }
        for tube in incomplete["subtubes"]
    )

    shared_boundary = [*complete_bars, (0.3, 0.05, 10.0)]
    ambiguous = capacity.build_torsion_context(
        _torsion_input(
            outer=_rect(0.6, 0.6),
            bars=shared_boundary,
            torsion_on=True,
            torsion_subdivide=True,
            torsion_subrects=rectangles,
        ),
        0.0,
    )
    assert all(not tube["valid"] for tube in ambiguous["subtubes"])
    assert all(
        tube["reason"] == "torsion sub-tube reinforcement assignment is ambiguous"
        for tube in ambiguous["subtubes"]
    )


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


def test_finalize_combined_builds_valid_payload(monkeypatch):
    n = capacity._dkna_action_record("N", 0.0, None, valid=True)
    m = capacity._dkna_action_record("M", 0.2, 1.0, valid=True)
    v = capacity._dkna_action_record("V", 0.3, 1.0, valid=True)
    t = capacity._dkna_action_record("T", 0.4, 1.0, valid=True)
    inp = _member_input(
        combined_on=True,
        _dkna_nm_action_alone={"n": n, "m": m},
    )
    monkeypatch.setattr(capacity, "_dkna_shear_action_alone", lambda _inp: v)
    monkeypatch.setattr(capacity, "_dkna_torsion_action_alone", lambda _inp: t)
    out = {
        "plastic": {"util": 0.20},
        "shear": {"res": {"valid": True}, "util": 0.30},
        "torsion": {
            "valid": True,
            "util": 0.40,
            "interaction": None,
            "t_ed": 40.0,
            "asl_req": 125.0,
            "subdivided": True,
            "subtubes": (
                {"asl_req": 50.0, "t_ed": 15.0},
                {"asl_req": 75.0, "t_ed": 25.0},
            ),
            "asw_over_s": 0.0,
        },
    }
    capacity.finalize_combined(inp, out)
    result = out["combined"]
    assert result["valid"]
    assert result["dkna_sum"] == pytest.approx(0.90)
    assert result["dkna_valid"]
    assert result["dkna_ok"]
    assert result["dkna_status"] == "PASS"
    assert result["dkna_conditional"] is False
    assert result["dkna_limit_satisfied"] is True
    assert result["r_n"] == pytest.approx(0.0)
    assert result["r_m"] == pytest.approx(0.20)
    assert result["r_v"] == pytest.approx(0.30)
    assert result["r_t"] == pytest.approx(0.40)
    assert result["torsion_subdivided"] is True
    assert result["torsion_subtubes"] == (
        {"asl_req": 50.0, "t_ed": 15.0},
        {"asl_req": 75.0, "t_ed": 25.0},
    )
    assert result["m_v_separation_condition"]["confirmed"] is False
    assert result["m_v_separation_condition"]["declared"] is False
    assert result["m_v_separation_condition"]["mechanically_verified"] is False
    assert result["m_v_separation_condition"]["source_clause"].endswith(
        "6.3.2(6)"
    )


@pytest.mark.parametrize(
    "inactive_mv_option",
    [True, "stale", "missing"],
    ids=["persisted-true", "hostile-text", "omitted"],
)
def test_finalize_combined_base_en_retains_physical_checks_without_dkna(
    monkeypatch, inactive_mv_option,
):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Base EN entered the DK NA action-alone interaction")

    monkeypatch.setattr(
        capacity, "dkna_normal_bending_action_alone", forbidden
    )
    monkeypatch.setattr(capacity, "_dkna_shear_action_alone", forbidden)
    monkeypatch.setattr(capacity, "_dkna_torsion_action_alone", forbidden)
    monkeypatch.setattr(combined_core, "dkna_interaction_result", forbidden)
    chord = {
        "valid": True,
        "util": 0.55,
        "axis": "x",
        "tension_low": True,
        "conditional": True,
    }
    chord_assessment = {
        "status": "PASS",
        "reason": "required_longitudinal_chord_coverage_complete",
        "util": 0.55,
        "coverage_complete": True,
    }
    inp = _member_input(
        combined_on=True,
        combined_method=codes.EC2_2005.label,
        shear_method=codes.EC2_2005.label,
        torsion_method=codes.EC2_2005.label,
    )
    if inactive_mv_option == "missing":
        inp.pop("combined_mv_independent")
    else:
        inp["combined_mv_independent"] = inactive_mv_option
    out = {
        "plastic": {"util": 0.20},
        "shear": {
            "res": {"valid": True, "vrd_c": 100.0},
            "util": 0.30,
            "v_ed": 30.0,
            "links": {
                "res": {
                    "valid": True,
                    "vrd_s": 100.0,
                    "vrd_max": 200.0,
                    "cot": 1.5,
                },
                "util": 0.30,
                "delta_ftd": 15.0,
                "chord": chord,
                "longitudinal_assessment": chord_assessment,
            },
        },
        "torsion": {
            "valid": True,
            "assessment_status": "PASS",
            "overall_reason": None,
            "longitudinal_assessment": {
                "status": "PASS",
                "demand_ratio": 0.50,
            },
            "interaction": {
                "valid": True,
                "cot": 1.5,
                "value": 0.40,
            },
            "primary": {"t_ed": 20.0, "trd_s": 100.0},
            "asl_req": 125.0,
            "asw_over_s": 0.1,
        },
    }

    capacity.finalize_combined(inp, out)

    result = out["combined"]
    assert result["valid"] is True
    assert result["method"] == codes.EC2_2005.label
    assert result["crushing"] == out["torsion"]["interaction"]
    assert result["transverse"]["valid"] is True
    assert result["longitudinal"] is chord
    assert result["longitudinal_assessment"] is chord_assessment
    forbidden_keys = {
        "source_clause",
        "r_n",
        "r_m",
        "r_v",
        "r_t",
        "m_v_independent",
        "m_v_separation_condition",
        "dkna_sum",
        "dkna_valid",
        "dkna_reason",
        "dkna_conditional",
        "dkna_limit_satisfied",
        "dkna_status",
        "dkna_ok",
        "dkna_selection",
        "action_alone",
    }
    assert forbidden_keys.isdisjoint(result)


def test_finalize_combined_editions_share_physical_results_but_only_dk_runs_sum(
    monkeypatch,
):
    chord = {
        "valid": True,
        "util": 0.55,
        "axis": "x",
        "tension_low": True,
        "conditional": True,
    }
    chord_assessment = {
        "status": "PASS",
        "reason": "required_longitudinal_chord_coverage_complete",
        "util": 0.55,
        "coverage_complete": True,
    }
    component_out = {
        "plastic": {"util": 0.20},
        "shear": {
            "res": {"valid": True, "vrd_c": 100.0},
            "util": 0.30,
            "v_ed": 30.0,
            "links": {
                "res": {
                    "valid": True,
                    "vrd_s": 100.0,
                    "vrd_max": 200.0,
                    "cot": 1.5,
                },
                "util": 0.30,
                "delta_ftd": 15.0,
                "chord": chord,
                "longitudinal_assessment": chord_assessment,
            },
        },
        "torsion": {
            "valid": True,
            "assessment_status": "PASS",
            "overall_reason": None,
            "longitudinal_assessment": {
                "status": "PASS",
                "demand_ratio": 0.50,
            },
            "interaction": {
                "valid": True,
                "cot": 1.5,
                "value": 0.40,
            },
            "primary": {"t_ed": 20.0, "trd_s": 100.0},
            "asl_req": 125.0,
            "asw_over_s": 0.1,
        },
    }
    n = capacity._dkna_action_record("N", 0.0, None, valid=True)
    m = capacity._dkna_action_record("M", 0.2, 1.0, valid=True)
    v = capacity._dkna_action_record("V", 0.3, 1.0, valid=True)
    t = capacity._dkna_action_record("T", 0.4, 1.0, valid=True)
    action_calls = []

    def v_action(_inp):
        action_calls.append("V")
        return v

    def t_action(_inp):
        action_calls.append("T")
        return t

    monkeypatch.setattr(capacity, "_dkna_shear_action_alone", v_action)
    monkeypatch.setattr(capacity, "_dkna_torsion_action_alone", t_action)
    base_inp = _member_input(
        combined_on=True,
        combined_method=codes.EC2_2005.label,
        shear_method=codes.EC2_2005.label,
        torsion_method=codes.EC2_2005.label,
        combined_mv_independent=True,
    )
    dk_inp = dict(
        base_inp,
        combined_method=codes.EC2_2005_DKNA.label,
        shear_method=codes.EC2_2005_DKNA.label,
        torsion_method=codes.EC2_2005_DKNA.label,
        _dkna_nm_action_alone={"n": n, "m": m},
    )
    base_out = copy.deepcopy(component_out)
    dk_out = copy.deepcopy(component_out)

    capacity.finalize_combined(base_inp, base_out)
    assert action_calls == []
    capacity.finalize_combined(dk_inp, dk_out)
    assert action_calls == ["V", "T"]

    base_result = base_out["combined"]
    dk_result = dk_out["combined"]
    for key in (
        "valid",
        "crushing",
        "asl_torsion",
        "delta_ftd",
        "links",
        "longitudinal",
        "longitudinal_assessment",
        "transverse",
    ):
        assert base_result[key] == dk_result[key]
    assert "dkna_sum" not in base_result
    assert "action_alone" not in base_result
    assert dk_result["dkna_sum"] == pytest.approx(0.70)
    assert tuple(dk_result["action_alone"]) == ("n", "m", "v", "t")


@pytest.mark.parametrize(
    ("m_demand", "expected_sum", "expected_status", "expected_ok"),
    [
        (0.6, 0.90, "CONDITIONAL", None),
        (0.8, 1.10, "FAIL", False),
    ],
    ids=["within-limit", "over-limit"],
)
def test_finalize_combined_separate_route_is_assumption_only(
    monkeypatch,
    m_demand,
    expected_sum,
    expected_status,
    expected_ok,
):
    n = capacity._dkna_action_record("N", 0.0, None, valid=True)
    m = capacity._dkna_action_record("M", m_demand, 1.0, valid=True)
    v = capacity._dkna_action_record("V", 0.4, 1.0, valid=True)
    t = capacity._dkna_action_record("T", 0.3, 1.0, valid=True)
    inp = _member_input(
        combined_on=True,
        combined_mv_independent=True,
        _dkna_nm_action_alone={"n": n, "m": m},
    )
    monkeypatch.setattr(capacity, "_dkna_shear_action_alone", lambda _inp: v)
    monkeypatch.setattr(capacity, "_dkna_torsion_action_alone", lambda _inp: t)
    out = {
        "plastic": {"util": 0.60},
        "shear": {"res": {"valid": True}, "util": 0.40},
        "torsion": {
            "valid": True,
            "util": 0.30,
            "interaction": None,
            "asl_req": 125.0,
            "asw_over_s": 0.0,
        },
    }

    capacity.finalize_combined(inp, out)
    result = out["combined"]

    assert result["dkna_sum"] == pytest.approx(expected_sum)
    assert result["dkna_valid"] is True
    assert result["dkna_limit_satisfied"] is (expected_sum <= 1.0)
    assert result["dkna_conditional"] is True
    assert result["dkna_status"] == expected_status
    assert result["dkna_ok"] is expected_ok
    condition = result["m_v_separation_condition"]
    assert condition["declared"] is True
    assert condition["confirmed"] is False
    assert condition["mechanically_verified"] is False
    assert "capacity, distribution or anchorage" in condition["limitation"]


@pytest.mark.parametrize(
    "torsion_status",
    ["NOT ASSESSED", "FAIL"],
)
def test_finalize_combined_retains_governing_longitudinal_torsion_state(
    monkeypatch,
    torsion_status,
):
    n = capacity._dkna_action_record("N", 0.0, None, valid=True)
    m = capacity._dkna_action_record("M", 0.2, 1.0, valid=True)
    v = capacity._dkna_action_record("V", 0.3, 1.0, valid=True)
    t = capacity._dkna_action_record("T", 0.4, 1.0, valid=True)
    inp = _member_input(
        combined_on=True,
        _dkna_nm_action_alone={"n": n, "m": m},
    )
    monkeypatch.setattr(capacity, "_dkna_shear_action_alone", lambda _inp: v)
    monkeypatch.setattr(capacity, "_dkna_torsion_action_alone", lambda _inp: t)
    reason = (
        "longitudinal_torsion_reinforcement_insufficient"
        if torsion_status == "FAIL"
        else "longitudinal_torsion_reinforcement_not_verified"
    )
    longitudinal = {
        "status": torsion_status,
        "reason": reason,
        "required_asl_mm2": 1176.672,
        "provided_equivalent_area_mm2": 1000.0,
        "demand_ratio": 1.176672,
    }
    out = {
        "plastic": {"util": 0.20},
        "shear": {"res": {"valid": True}, "util": 0.30},
        "torsion": {
            "valid": True,
            "util": 0.40,
            "interaction": None,
            "asl_req": 1176.672,
            "asw_over_s": 0.0,
            "assessment_status": torsion_status,
            "overall_reason": reason,
            "longitudinal_assessment": longitudinal,
        },
    }

    capacity.finalize_combined(inp, out)
    result = out["combined"]

    assert result["valid"] is True
    assert result["dkna_sum"] == pytest.approx(0.90)
    assert result["dkna_status"] == "PASS"
    assert result["torsion_assessment_status"] == torsion_status
    assert result["torsion_assessment_reason"] == reason
    assert result["torsion_longitudinal_assessment"] == longitudinal
    assert result["assessment_status"] == torsion_status


@pytest.mark.parametrize(
    ("n_ed", "direction"),
    [(100.0, "tension"), (-100.0, "compression")],
)
def test_dkna_axial_action_alone_uses_matching_tension_or_compression_branch(
    n_ed,
    direction,
):
    action = capacity._dkna_axial_action_alone(
        _dkna_plastic_input(P_pl=n_ed)
    )
    assert action["valid"]
    assert action["demand"] == pytest.approx(n_ed)
    assert action["direction"] == direction
    assert action["resistance"] > abs(n_ed)
    assert action["evidence"]["zero_moment"] is True
    assert action["source_clause"].endswith("6.3.2(6)")


@pytest.mark.parametrize(
    ("n_ed", "expected_resistance", "expected_endpoint"),
    [
        (100.0, 600.0, -1000.0),
        (-100.0, 700.0, 1200.0),
    ],
)
def test_dkna_axial_action_alone_enforces_zero_moment_before_accepting_nrd(
    monkeypatch,
    n_ed,
    expected_resistance,
    expected_endpoint,
):
    solver_axial = -expected_resistance if n_ed > 0.0 else expected_resistance
    monkeypatch.setattr(
        capacity,
        "solve_zero_moment_axial_capacity",
        lambda *_args, **_kwargs: SimpleNamespace(
            axial=solver_axial,
            converged=True,
            endpoint_axial=expected_endpoint,
            neutral_axis_angle_deg=47.0,
            moment_residual_knm=1.0e-8,
            moment_tolerance_knm=1.0e-6,
            point_evaluations=17,
            iterations=5,
        ),
    )

    action = capacity._dkna_axial_action_alone(
        _dkna_plastic_input(P_pl=n_ed)
    )

    assert action["valid"]
    assert action["resistance"] == pytest.approx(
        expected_resistance, abs=1.0e-5
    )
    assert action["resistance"] < abs(expected_endpoint)
    assert action["evidence"]["endpoint_axial_kn"] == expected_endpoint
    assert action["evidence"]["zero_moment"] is True
    assert action["evidence"]["iterations"] == 5
    assert action["evidence"]["point_evaluations"] == 17


@pytest.mark.parametrize(
    ("n_ed", "reference_resistance"),
    [
        # Independent former 1-degree complete-sweep/bisection references.
        (100.0, 1283.186788295355),
        (-100.0, 12003.2902276955),
    ],
    ids=("asymmetric-tension", "asymmetric-compression"),
)
def test_dkna_zero_moment_axial_boundary_matches_independent_fine_sweep(
    monkeypatch,
    n_ed,
    reference_resistance,
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("complete sweep or interaction trace entered")

    monkeypatch.setattr(capacity, "solve_plastic", forbidden)
    monkeypatch.setattr(capacity, "solve_interaction", forbidden)

    action = capacity._dkna_axial_action_alone(
        _dkna_asymmetric_plastic_input(P_pl=n_ed)
    )

    assert action["valid"] is True
    assert action["resistance"] == pytest.approx(
        reference_resistance, rel=5.0e-4
    )
    assert 1 <= action["evidence"]["point_evaluations"] <= 80
    assert action["evidence"]["moment_residual_knm"] <= (
        action["evidence"]["moment_tolerance_knm"]
    )


def test_dkna_zero_moment_axial_boundary_reuses_one_prep_and_has_hard_ceiling(
    monkeypatch,
):
    plastic = capacity._module("plastic")
    original_prep = plastic._prep_section
    original_point = plastic.plastic_capacity_at_angle
    calls = {"prep": 0, "point": 0}

    def counted_prep(*args, **kwargs):
        calls["prep"] += 1
        return original_prep(*args, **kwargs)

    def counted_point(*args, **kwargs):
        calls["point"] += 1
        return original_point(*args, **kwargs)

    monkeypatch.setattr(plastic, "_prep_section", counted_prep)
    monkeypatch.setattr(plastic, "plastic_capacity_at_angle", counted_point)
    inp = _dkna_asymmetric_plastic_input(P_pl=100.0)

    result = plastic.solve_zero_moment_axial_capacity(
        inp["section"],
        inp["concrete"],
        inp["steel"],
        tension=True,
    )

    assert result.converged is True
    assert calls == {"prep": 1, "point": result.point_evaluations}
    assert result.point_evaluations <= 80
    assert result.point_evaluations < 361


def test_dkna_axial_action_alone_fails_closed_on_boundary_nonconvergence(
    monkeypatch,
):
    monkeypatch.setattr(
        capacity,
        "solve_zero_moment_axial_capacity",
        lambda *_args, **_kwargs: SimpleNamespace(
            axial=None,
            converged=False,
            endpoint_axial=-1000.0,
            neutral_axis_angle_deg=None,
            moment_residual_knm=5.0,
            moment_tolerance_knm=1.0e-6,
            point_evaluations=192,
            iterations=18,
        ),
    )

    action = capacity._dkna_axial_action_alone(
        _dkna_plastic_input(P_pl=100.0)
    )

    assert action["valid"] is False
    assert action["resistance"] is None
    assert "could not be determined" in action["reason"]


def test_dkna_bending_action_alone_follows_biaxial_direction_not_applied_n():
    tension = capacity._dkna_bending_action_alone(
        _dkna_plastic_input(P_pl=400.0, Mx_pl=60.0, My_pl=-30.0)
    )
    compression = capacity._dkna_bending_action_alone(
        _dkna_plastic_input(P_pl=-400.0, Mx_pl=60.0, My_pl=-30.0)
    )
    assert tension["valid"] and compression["valid"]
    assert tension["demand"] == pytest.approx(math.hypot(60.0, -30.0))
    assert tension["direction"] == pytest.approx(
        math.degrees(math.atan2(-30.0, 60.0)) % 360.0
    )
    assert tension["resistance"] == pytest.approx(compression["resistance"])
    assert tension["evidence"]["mx_ed"] == pytest.approx(60.0)
    assert tension["evidence"]["my_ed"] == pytest.approx(-30.0)
    assert tension["evidence"]["axial_action_kn"] == pytest.approx(0.0)


def test_dkna_shear_action_alone_auto_checks_both_faces_and_uses_lower_resistance(
    monkeypatch,
):
    seen = []

    def face_context(face_input, _n_prestress, _n_ed_comp):
        tension_low = face_input["shear_tension"]
        seen.append(tension_low)
        resistance = 80.0 if tension_low else 60.0
        return {"res": {"valid": True, "vrd_c": resistance}}, None

    monkeypatch.setattr(capacity, "build_shear_context", face_context)
    action = capacity._dkna_shear_action_alone(
        _member_input(shear_axis="x", shear_face_y="auto", shear_V=30.0)
    )

    assert seen == [True, False]
    assert action["valid"]
    assert action["resistance"] == pytest.approx(60.0)
    assert action["evidence"]["both_faces_evaluated"] is True
    assert action["evidence"]["faces_evaluated"] == ["negative", "positive"]
    assert action["evidence"]["governing_face"] == "positive"


def test_dkna_shear_action_alone_explicit_face_checks_only_that_face(monkeypatch):
    seen = []

    def face_context(face_input, _n_prestress, _n_ed_comp):
        seen.append(face_input["shear_tension"])
        return {"res": {"valid": True, "vrd_c": 75.0}}, None

    monkeypatch.setattr(capacity, "build_shear_context", face_context)
    action = capacity._dkna_shear_action_alone(
        _member_input(shear_axis="x", shear_face_y="negative", shear_V=30.0)
    )

    assert seen == [True]
    assert action["valid"]
    assert action["resistance"] == pytest.approx(75.0)
    assert action["evidence"]["both_faces_evaluated"] is False
    assert action["evidence"]["faces_evaluated"] == ["negative"]


@pytest.mark.parametrize(
    ("demand", "expected_resistance", "expected_route"),
    (
        (80.0, 103.417, "concrete"),
        (math.nextafter(103.417, math.inf), 29.452, "links"),
    ),
    ids=("concrete-route", "designed-links-route"),
)
def test_dkna_action_alone_uses_the_selected_nominal_shear_denominator(
    monkeypatch,
    demand,
    expected_resistance,
    expected_route,
):
    def face_context(_face_input, _n_prestress, _n_ed_comp):
        return (
            {"res": {"valid": True, "vrd_c": 103.417}},
            {
                "build": lambda _cot_min, _cot_max: {
                    "valid": True,
                    "vrd": 29.452,
                    "cot": 2.0,
                },
                "cot_min": 1.0,
                "cot_max": 2.5,
            },
        )

    monkeypatch.setattr(capacity, "build_shear_context", face_context)
    action = capacity._dkna_shear_action_alone(
        _member_input(
            shear_axis="x",
            shear_face_y="negative",
            shear_V=demand,
            shear_links=True,
        )
    )

    assert action["valid"] is True
    assert action["resistance"] == pytest.approx(expected_resistance)
    assert action["demand"] / action["resistance"] == pytest.approx(
        demand / expected_resistance
    )
    assert action["evidence"]["nominal_route"] == expected_route


def test_dkna_shear_action_alone_auto_fails_closed_if_either_face_is_unavailable(
    monkeypatch,
):
    seen = []

    def face_context(face_input, _n_prestress, _n_ed_comp):
        tension_low = face_input["shear_tension"]
        seen.append(tension_low)
        if tension_low:
            return {"res": {"valid": True, "vrd_c": 80.0}}, None
        return {"res": {"valid": False, "vrd_c": None}}, None

    monkeypatch.setattr(capacity, "build_shear_context", face_context)
    action = capacity._dkna_shear_action_alone(
        _member_input(shear_axis="x", shear_face_y="auto", shear_V=30.0)
    )

    assert seen == [True, False]
    assert not action["valid"]
    assert action["resistance"] is None
    assert "action-alone resistance" in action["reason"]


def test_dkna_zero_n_and_m_do_not_enter_action_alone_plastic_solver(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("zero action must not enter the Plastic solver")

    monkeypatch.setattr(capacity, "solve_plastic", unexpected)
    monkeypatch.setattr(capacity, "solve_interaction", unexpected)
    actions = capacity.dkna_normal_bending_action_alone(
        _dkna_plastic_input(P_pl=0.0, Mx_pl=0.0, My_pl=0.0)
    )
    assert actions["n"]["valid"] and actions["m"]["valid"]
    assert actions["n"]["resistance"] is None
    assert actions["m"]["resistance"] is None


@pytest.mark.parametrize("independent_mv", [False, True], ids=["simultaneous", "separate"])
def test_finalize_combined_discloses_missing_component(independent_mv):
    inp = _member_input(
        combined_on=True,
        combined_mv_independent=independent_mv,
    )
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
        "m_v_independent": independent_mv,
        "m_v_separation_condition": {
            "confirmed": False,
            "declared": independent_mv,
            "mechanically_verified": False,
            "verification_state": (
                "design assumption" if independent_mv else "not selected"
            ),
            "condition": (
                "Additional longitudinal reinforcement required for shear "
                "beyond that required for bending is provided"
            ),
            "limitation": (
                "This section calculation does not verify the additional "
                "reinforcement capacity, distribution or anchorage"
            ),
            "source_clause": "DS/EN 1992-1-1 DK NA:2024, 6.3.2(6)",
        },
    }


def test_finalize_combined_fails_closed_when_selected_links_are_not_assessed():
    inp = _member_input(combined_on=True, shear_links=True)
    out = {
        "plastic": {"util": 0.20},
        "shear": {
            "res": {"valid": True},
            "util": 0.30,
            "links": {
                "res": {
                    "valid": False,
                    "calculation_state": "NOT ASSESSED",
                    "reason": "exact calculated plastic lever arm z is unavailable",
                },
                "util": None,
                "assessment_reason": (
                    "calculated plastic lever arm unavailable: the exact "
                    "face-aligned Plastic solve did not converge"
                ),
            },
        },
        "torsion": {"valid": True, "util": 0.40},
    }

    capacity.finalize_combined(inp, out)

    assert out["combined"]["valid"] is False
    assert out["combined"]["have_v"] is False
    assert "did not converge" in out["combined"]["reason"]
    assert "dkna_sum" not in out["combined"]


def test_finalize_combined_preserves_every_longitudinal_candidate(monkeypatch):
    n = capacity._dkna_action_record("N", 0.0, None, valid=True)
    m = capacity._dkna_action_record("M", 0.2, 1.0, valid=True)
    v = capacity._dkna_action_record("V", 0.3, 1.0, valid=True)
    t = capacity._dkna_action_record("T", 0.4, 1.0, valid=True)
    inp = _member_input(
        combined_on=True,
        _dkna_nm_action_alone={"n": n, "m": m},
    )
    monkeypatch.setattr(capacity, "_dkna_shear_action_alone", lambda _inp: v)
    monkeypatch.setattr(capacity, "_dkna_torsion_action_alone", lambda _inp: t)
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
                "model_2023": True,
                "chord": exact,
                "chord_candidates": [fallback, exact],
                "longitudinal_assessment": {
                    "status": "NOT ASSESSED",
                    "reason": "required_longitudinal_chord_coverage_incomplete",
                },
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
    assert out["combined"]["longitudinal_model_2023"] is True
    assert out["combined"]["longitudinal_candidates"] == [fallback, exact]
