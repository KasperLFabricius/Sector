"""Tests for the combined bending + shear + torsion (M-V-T) interaction checks."""

from __future__ import annotations

import copy
import inspect
import math
import pathlib
import sys

import numpy as np
import pytest

from sector import capacity, codes, combined, shear

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
APP = str(ROOT / "app" / "sector_app.py")

from app_case_inputs import (  # noqa: E402
    CALCULATION_RUN_TIMEOUT,
    REPORT_RUN_TIMEOUT,
    apply_widget_changes,
)
import result_presentation  # noqa: E402
from native_member_report_fixtures import native_member_report_cases  # noqa: E402,F401


# -- engine -----------------------------------------------------------------

def test_ratio_helper():
    assert combined.ratio(1.0, 2.0) == pytest.approx(0.5)
    assert combined.ratio(0.0, 0.0) == 0.0
    assert math.isinf(combined.ratio(1.0, 0.0))


def test_crushing_interaction():
    assert combined.crushing_interaction(40.0, 80.0, 150.0, 600.0) == pytest.approx(0.75)
    assert math.isinf(combined.crushing_interaction(1.0, 0.0, 0.0, 1.0))


def test_formula_631_screen_retains_operands_and_exact_existing_verdict():
    result = combined.minimum_reinforcement_screen_result(
        15.0,
        60.0,
        30.0,
        120.0,
        solid_rectangle=True,
        subdivided=False,
        model_2023=False,
        shear_available=True,
    )

    assert result.applicable is True
    assert result.status == "PASS"
    assert result.value == pytest.approx(0.5)
    assert result.torsion_ratio == pytest.approx(0.25)
    assert result.shear_ratio == pytest.approx(0.25)
    assert result.governs == "torsion"
    assert result.ok is True
    assert result.detailing_status == "NOT RUN"
    assert result.detailing_scope_key == "separate_detailing_not_run"


@pytest.mark.parametrize(
    ("kwargs", "status", "scope_key"),
    [
        (
            {"solid_rectangle": False},
            "NOT APPLICABLE",
            "section_geometry",
        ),
        (
            {"subdivided": True},
            "NOT APPLICABLE",
            "subdivided_section",
        ),
        (
            {
                "model_2023": True,
                "shear_available": False,
                "v_ed": None,
                "vrd_c": None,
            },
            "NOT APPLICABLE",
            "selected_2023_route",
        ),
        (
            {"shear_available": False, "v_ed": None, "vrd_c": None},
            "NOT ASSESSED",
            "shear_resistance_unavailable",
        ),
        (
            {"trd_c": 0.0},
            "NOT ASSESSED",
            "positive_resistance_unavailable",
        ),
    ],
    ids=(
        "unsupported-geometry",
        "subdivided",
        "2023-route",
        "missing-shear",
        "nonpositive-resistance",
    ),
)
def test_formula_631_scope_branches_never_publish_a_verdict(
    kwargs,
    status,
    scope_key,
):
    inputs = dict(
        t_ed=15.0,
        trd_c=60.0,
        v_ed=30.0,
        vrd_c=120.0,
        solid_rectangle=True,
        subdivided=False,
        model_2023=False,
        shear_available=True,
    )
    inputs.update(kwargs)

    result = combined.minimum_reinforcement_screen_result(**inputs)

    assert result.applicable is False
    assert result.status == status
    assert result.scope_key == scope_key
    assert result.value is None
    assert result.ok is None


@pytest.mark.parametrize(
    ("action", "value"),
    (
        ("n_ed", -20.0),
        ("n_ed", 20.0),
        ("mx_ed", -15.0),
        ("mx_ed", 15.0),
        ("my_ed", -10.0),
        ("my_ed", 10.0),
    ),
)
def test_dkna_formula_631_scope_rejects_signed_normal_or_moment_actions(
    action,
    value,
):
    kwargs = {action: value}
    result = combined.minimum_reinforcement_screen_result(
        15.0,
        60.0,
        30.0,
        120.0,
        solid_rectangle=True,
        subdivided=False,
        model_2023=False,
        shear_available=True,
        dk_na=True,
        shear_method="DS/EN 1992-1-1:2005 + DK NA:2024",
        torsion_method="DS/EN 1992-1-1:2005 + DK NA:2024",
        **kwargs,
    )

    assert result.applicable is False
    assert result.status == "NOT APPLICABLE"
    assert result.scope_key == "dkna_combined_normal_or_moment"
    assert result.normal_or_moment_active is True
    assert result.value is None and result.ok is None
    assert result.dk_na is True
    assert "DK NA:2024" in result.shear_method
    assert "DK NA:2024" in result.torsion_method


@pytest.mark.parametrize(
    ("scope_context", "scope_overrides"),
    (
        ("nonrectangular", {"solid_rectangle": False}),
        ("hollow", {"solid_rectangle": False}),
        (
            "subdivided",
            {"solid_rectangle": False, "subdivided": True},
        ),
        (
            "unavailable-shear",
            {"shear_available": False, "v_ed": None, "vrd_c": None},
        ),
        (
            "selected-2023",
            {
                "model_2023": True,
                "shear_method": codes.EC2_2023.label,
                "torsion_method": codes.EC2_2005_DKNA.label,
            },
        ),
    ),
    ids=lambda value: value if isinstance(value, str) else None,
)
@pytest.mark.parametrize(
    ("action", "value"),
    (
        ("n_ed", -20.0),
        ("n_ed", 20.0),
        ("mx_ed", -15.0),
        ("mx_ed", 15.0),
        ("my_ed", -10.0),
        ("my_ed", 10.0),
    ),
)
def test_dkna_formula_631_requirement_outranks_other_scope_limitations(
    scope_context,
    scope_overrides,
    action,
    value,
):
    inputs = dict(
        t_ed=15.0,
        trd_c=60.0,
        v_ed=30.0,
        vrd_c=120.0,
        solid_rectangle=True,
        subdivided=False,
        model_2023=False,
        shear_available=True,
        dk_na=True,
        shear_method=codes.EC2_2005_DKNA.label,
        torsion_method=codes.EC2_2005_DKNA.label,
        n_ed=0.0,
        mx_ed=0.0,
        my_ed=0.0,
    )
    inputs.update(scope_overrides)
    inputs[action] = value

    result = combined.minimum_reinforcement_screen_result(**inputs)

    assert scope_context in {
        "nonrectangular", "hollow", "subdivided", "unavailable-shear",
        "selected-2023",
    }
    assert result.applicable is False
    assert result.status == "NOT APPLICABLE"
    assert result.scope_key == "dkna_combined_normal_or_moment"
    assert result.normal_or_moment_active is True
    assert result.dk_na is True
    assert result.value is None and result.ok is None
    if scope_context == "selected-2023":
        assert result.model_2023 is True
        assert result.shear_method == codes.EC2_2023.label
        assert result.torsion_method == codes.EC2_2005_DKNA.label


def test_dkna_formula_631_scope_accepts_exact_zero_normal_and_moment_actions():
    result = combined.minimum_reinforcement_screen_result(
        15.0,
        60.0,
        30.0,
        120.0,
        solid_rectangle=True,
        subdivided=False,
        model_2023=False,
        shear_available=True,
        dk_na=True,
        n_ed=-0.0,
        mx_ed=0.0,
        my_ed=0.0,
    )

    assert result.applicable is True
    assert result.status == "PASS"
    assert result.normal_or_moment_active is False
    assert result.dk_na is True


def test_formula_631_over_limit_is_fail_and_not_a_sufficiency_result():
    result = combined.minimum_reinforcement_screen_result(
        45.0,
        60.0,
        60.0,
        120.0,
        solid_rectangle=True,
        subdivided=False,
        model_2023=False,
        shear_available=True,
    )

    assert result.value == pytest.approx(1.25)
    assert result.status == "FAIL"
    assert result.ok is False


def test_all_not_applicable_directional_screens_remain_not_applicable():
    assert capacity.aggregate_assessment_status(
        ["NOT APPLICABLE", "NOT APPLICABLE"]
    ) == "NOT APPLICABLE"
    assert capacity.aggregate_assessment_status(
        ["NOT APPLICABLE", "NOT ASSESSED"]
    ) == "NOT ASSESSED"


def test_dkna_sum_summed_vs_independent():
    assert combined.dkna_sum(
        0.3, 0.4, 0.2, r_n=0.1, m_v_independent=False
    ) == pytest.approx(1.0)
    # independent -> N + max(M+T, V+T) = 0.1 + max(0.5, 0.6) = 0.7
    assert combined.dkna_sum(
        0.3, 0.4, 0.2, r_n=0.1, m_v_independent=True
    ) == pytest.approx(0.7)


def test_dkna_axial_term_is_not_folded_into_bending():
    result = combined.dkna_interaction_result(
        950.0,
        1000.0,
        0.0,
        None,
        5.0,
        100.0,
        5.0,
        100.0,
        m_v_independent=False,
    )
    assert result.valid
    assert result.r_n == pytest.approx(0.95)
    assert result.r_m == pytest.approx(0.0)
    assert result.utilisation == pytest.approx(1.05)
    assert result.ok is False


@pytest.mark.parametrize("n_ed", [-950.0, 950.0])
def test_dkna_retains_axial_sign_and_uses_matching_magnitude(n_ed):
    result = combined.dkna_interaction_result(
        n_ed,
        1000.0,
        0.0,
        None,
        0.0,
        None,
        0.0,
        None,
        m_v_independent=False,
    )
    assert result.valid
    assert result.n.demand == pytest.approx(n_ed)
    assert result.n.demand_abs == pytest.approx(950.0)
    assert result.r_n == pytest.approx(0.95)


def test_dkna_active_action_without_resistance_fails_closed():
    result = combined.dkna_interaction_result(
        0.0,
        None,
        10.0,
        None,
        0.0,
        None,
        0.0,
        None,
        m_v_independent=False,
    )
    assert not result.valid
    assert result.utilisation is None
    assert result.ok is None
    assert result.m.active and not result.m.valid
    assert "acting alone" in result.reason


def test_dkna_independent_route_keeps_n_and_t_in_both_checks():
    result = combined.dkna_interaction_result(
        20.0,
        100.0,
        30.0,
        100.0,
        40.0,
        100.0,
        10.0,
        100.0,
        m_v_independent=True,
    )
    assert result.n_m_plus_t == pytest.approx(0.6)
    assert result.n_v_plus_t == pytest.approx(0.7)
    assert result.utilisation == pytest.approx(0.7)
    assert result.governing_chord == "N+V+T"
    assert result.conditional is True
    assert result.limit_satisfied is True
    assert result.status == "CONDITIONAL"
    assert result.ok is None


def test_dkna_independent_route_over_limit_fails_even_under_assumption():
    result = combined.dkna_interaction_result(
        0.0,
        None,
        80.0,
        100.0,
        10.0,
        100.0,
        30.0,
        100.0,
        m_v_independent=True,
    )

    assert result.valid is True
    assert result.utilisation == pytest.approx(1.10)
    assert result.limit_satisfied is False
    assert result.conditional is True
    assert result.status == "FAIL"
    assert result.ok is False


@pytest.mark.parametrize(
    ("utilisation", "expected_status", "expected_ok"),
    [
        (1.0, "CONDITIONAL", None),
        (math.nextafter(1.0, math.inf), "FAIL", False),
    ],
    ids=["at-limit", "first-representable-value-over-limit"],
)
def test_dkna_separate_route_limit_boundary_is_exact(
    utilisation,
    expected_status,
    expected_ok,
):
    result = combined.dkna_interaction_result(
        0.0,
        None,
        utilisation,
        1.0,
        0.0,
        None,
        0.0,
        None,
        m_v_independent=True,
    )

    assert result.utilisation == utilisation
    assert result.limit_satisfied is (utilisation <= 1.0)
    assert result.status == expected_status
    assert result.ok is expected_ok


def test_dkna_independent_route_with_incomplete_resistance_is_not_assessed():
    result = combined.dkna_interaction_result(
        0.0,
        None,
        10.0,
        None,
        0.0,
        None,
        0.0,
        None,
        m_v_independent=True,
    )

    assert result.valid is False
    assert result.conditional is True
    assert result.limit_satisfied is None
    assert result.status == "NOT ASSESSED"
    assert result.ok is None


def test_dkna_rejects_numpy_booleans_as_actions_or_route_selection():
    result = combined.dkna_interaction_result(
        np.bool_(True),
        100.0,
        0.0,
        None,
        0.0,
        None,
        0.0,
        None,
        m_v_independent=False,
    )
    assert not result.valid
    assert result.n.demand is None
    with pytest.raises(TypeError, match="must be a Boolean"):
        combined.dkna_sum(
            0.1, 0.2, 0.3, m_v_independent=np.bool_(True)
        )


def test_retained_combined_results_are_compact_and_reconstruct_scalars():
    crushing = combined.crushing_interaction_result(
        40.0, 80.0, 150.0, 600.0
    )
    assert crushing.torsion_ratio == pytest.approx(0.5)
    assert crushing.shear_ratio == pytest.approx(0.25)
    assert crushing.utilisation == pytest.approx(
        combined.crushing_interaction(40.0, 80.0, 150.0, 600.0)
    )
    dk = combined.dkna_interaction_result(
        0.1,
        1.0,
        0.3,
        1.0,
        0.4,
        1.0,
        0.2,
        1.0,
        m_v_independent=True,
    )
    assert dk.m_plus_t == pytest.approx(0.5)
    assert dk.v_plus_t == pytest.approx(0.6)
    assert dk.n_m_plus_t == pytest.approx(0.6)
    assert dk.n_v_plus_t == pytest.approx(0.7)
    assert dk.governing_chord == "N+V+T"
    assert dk.conditional is True
    assert dk.limit_satisfied is True
    assert dk.status == "CONDITIONAL"
    assert dk.ok is None
    assert dk.utilisation == pytest.approx(
        combined.dkna_sum(
            0.3, 0.4, 0.2, r_n=0.1, m_v_independent=True
        )
    )
    assert not hasattr(dk, "__dict__")
    with pytest.raises(AttributeError):
        dk.utilisation = 0.0


def test_retained_governing_strut_has_only_final_scan_certificate():
    functions = [lambda cot: 1.0 / cot, lambda cot: cot / 2.0]
    result = combined.governing_strut_result(functions, 1.0, 2.5, n=151)
    legacy_cot, legacy_util = combined.governing_strut_cot(
        functions, 1.0, 2.5, n=151
    )
    assert result.cot == pytest.approx(legacy_cot)
    assert result.utilisation == pytest.approx(legacy_util)
    assert result.samples == 151
    assert result.step == pytest.approx((2.5 - 1.0) / 150.0)
    assert result.selected_index == pytest.approx(
        (result.cot - 1.0) / result.step
    )
    assert result.objective_count == 2
    assert not hasattr(result, "candidates")
    assert not hasattr(result, "iterations")
    assert not hasattr(result, "history")


def test_empty_governing_strut_certificate_handles_zero_lower_bound():
    result = combined.governing_strut_result([], 0.0, 2.5, n=2)
    assert result.cot == 0.0
    assert result.theta_deg == pytest.approx(90.0)


def test_longitudinal_check_uncapped():
    # No cap needed (bending + shear stays well below MRd): a straight sum.
    #   mv = min(50*0.5, 400-100) = 25; mt = 30*0.5/2 = 7.5; total = 132.5
    r = combined.longitudinal_check(100.0, 400.0, 50.0, 30.0, 0.5)
    assert r["mv"] == pytest.approx(25.0)
    assert r["mt"] == pytest.approx(7.5)          # torsion distributed -> z/2
    assert r["m_total"] == pytest.approx(132.5)
    assert r["util"] == pytest.approx(132.5 / 400.0)
    assert not r["capped"]
    assert r["ok"]


def test_longitudinal_check_shear_shift_capped():
    # The shear shift wants 200*0.5 = 100 kNm but 6.2.3(7) caps it at MRd - MEd = 20.
    r = combined.longitudinal_check(100.0, 120.0, 200.0, 0.0, 0.5)
    assert r["mv"] == pytest.approx(20.0)
    assert r["capped"]
    assert r["m_total"] == pytest.approx(120.0)   # exactly MRd -> util 1.0
    assert r["util"] == pytest.approx(1.0)


def test_longitudinal_check_2023_shear_force_is_not_peak_moment_capped():
    # Sector does not establish the direct-support / concentrated-load condition
    # required for the favourable 2023 Formula (8.53) relief.
    r = combined.longitudinal_check(
        100.0,
        120.0,
        200.0,
        0.0,
        0.5,
        cap_shear_force=False,
    )
    assert r["mv"] == pytest.approx(100.0)
    assert not r["capped"]
    assert not r["cap_shear_force"]
    assert r["m_total"] == pytest.approx(200.0)
    assert r["util"] == pytest.approx(200.0 / 120.0)


def test_longitudinal_chord_2023_exact_two_face_review_fixture():
    tension = combined.longitudinal_chord_check_2023(
        90.0,
        100.0,
        250.0,
        0.0,
        0.5,
        tension_low=True,
        flexural_tension_low=True,
    )
    assert tension["chord_formula"] == "8.51"
    assert tension["chord_role"] == "flexural_tension"
    assert tension["face_m_ed_signed"] == pytest.approx(90.0)
    assert tension["mv"] == pytest.approx(125.0)
    assert tension["m_total"] == pytest.approx(215.0)
    assert tension["util"] == pytest.approx(2.15)
    assert tension["status"] == "FAIL"
    assert tension["chord_force_kn"] == pytest.approx(430.0)

    compression = combined.longitudinal_chord_check_2023(
        90.0,
        100.0,
        250.0,
        0.0,
        0.5,
        tension_low=False,
        flexural_tension_low=True,
    )
    assert compression["chord_formula"] == "8.52"
    assert compression["chord_role"] == "flexural_compression"
    assert compression["face_m_ed_signed"] == pytest.approx(-90.0)
    assert compression["mv"] == pytest.approx(125.0)
    assert compression["m_total"] == pytest.approx(35.0)
    assert compression["util"] == pytest.approx(0.35)
    assert compression["chord_force_kn"] == pytest.approx(-70.0)
    assert compression["chord_force_sign"] == "tension"


@pytest.mark.parametrize(
    ("moment", "flexural_tension_low"),
    ((90.0, True), (-90.0, False)),
)
def test_longitudinal_chord_2023_signed_moment_swaps_physical_faces(
    moment,
    flexural_tension_low,
):
    faces = {
        tension_low: combined.longitudinal_chord_check_2023(
            moment,
            100.0,
            250.0,
            0.0,
            0.5,
            tension_low=tension_low,
            flexural_tension_low=flexural_tension_low,
        )
        for tension_low in (True, False)
    }
    assert faces[flexural_tension_low]["m_total"] == pytest.approx(215.0)
    assert faces[flexural_tension_low]["chord_formula"] == "8.51"
    assert faces[not flexural_tension_low]["m_total"] == pytest.approx(35.0)
    assert faces[not flexural_tension_low]["chord_formula"] == "8.52"


def test_longitudinal_chord_2023_retains_axial_operand_without_double_counting():
    compression = combined.longitudinal_chord_check_2023(
        90.0,
        100.0,
        250.0,
        0.0,
        0.5,
        tension_low=False,
        flexural_tension_low=True,
        n_ed=-60.0,
    )
    tension = combined.longitudinal_chord_check_2023(
        90.0,
        100.0,
        250.0,
        0.0,
        0.5,
        tension_low=False,
        flexural_tension_low=True,
        n_ed=60.0,
    )
    assert compression["n_ed"] == pytest.approx(-60.0)
    assert tension["n_ed"] == pytest.approx(60.0)
    assert compression["chord_force_kn"] == pytest.approx(-100.0)
    assert tension["chord_force_kn"] == pytest.approx(-40.0)
    assert compression["m_total"] == pytest.approx(tension["m_total"])
    assert compression["util"] == pytest.approx(tension["util"])
    assert compression["axial_force_conditioned_in_m_rd"] is True
    reversed_tension_chord = combined.longitudinal_chord_check_2023(
        10.0,
        100.0,
        5.0,
        0.0,
        0.5,
        tension_low=True,
        flexural_tension_low=True,
        n_ed=-100.0,
    )
    assert reversed_tension_chord["chord_formula"] == "8.51"
    assert reversed_tension_chord["chord_force_kn"] == pytest.approx(-25.0)
    assert reversed_tension_chord["chord_force_sign"] == "compression"


@pytest.mark.parametrize(
    ("args", "kwargs"),
    (
        ((math.nan, 100.0, 250.0, 0.0, 0.5), {}),
        ((90.0, math.inf, 250.0, 0.0, 0.5), {}),
        ((90.0, 100.0, -1.0, 0.0, 0.5), {}),
        ((90.0, 100.0, 250.0, 0.0, 0.0), {}),
        ((90.0, 100.0, 250.0, 0.0, 0.5), {"n_ed": True}),
        (
            (90.0, 100.0, 250.0, 0.0, 0.5),
            {"flexural_tension_low": np.bool_(True)},
        ),
    ),
)
def test_longitudinal_chord_2023_rejects_invalid_operands(args, kwargs):
    options = {"tension_low": True, "flexural_tension_low": True}
    options.update(kwargs)
    with pytest.raises(ValueError, match="finite|positive|non-negative|Boolean"):
        combined.longitudinal_chord_check_2023(*args, **options)


def test_longitudinal_check_torsion_uses_half_lever_and_no_cap():
    # Torsion is not subject to the shear cap and acts on z/2 (distributed steel).
    r = combined.longitudinal_check(50.0, 300.0, 0.0, 80.0, 0.6)
    assert r["mv"] == 0.0
    assert r["mt"] == pytest.approx(80.0 * 0.6 / 2.0)
    assert not r["capped"]
    assert r["m_total"] == pytest.approx(74.0)


def test_chord_applied_moment_low_face_adds():
    # Common case: shear tension on the low face, a sagging moment tensions it too.
    assert combined.chord_applied_moment(100.0, True) == pytest.approx(100.0)


def test_chord_applied_moment_high_face_relief_floors_to_zero():
    # Codex's scenario: shear tension on the HIGH face but the applied moment is sagging
    # (tensions the LOW face), so it relieves the high chord -> contribution floors at 0
    # (the high chord must still carry the shear + torsion tension on its own).
    assert combined.chord_applied_moment(100.0, False) == 0.0


def test_chord_applied_moment_high_face_hogging_adds():
    # High face with a hogging moment that genuinely tensions it -> full contribution.
    assert combined.chord_applied_moment(-100.0, False) == pytest.approx(100.0)


def test_chord_applied_moment_low_face_hogging_relief():
    assert combined.chord_applied_moment(-80.0, True) == 0.0


def test_longitudinal_check_zero_capacity_is_inf():
    r = combined.longitudinal_check(10.0, 0.0, 5.0, 5.0, 0.5)
    assert math.isinf(r["util"])
    assert not r["ok"]


def test_longitudinal_check_zero_capacity_shear_only_is_inf_not_zero():
    # The subtle case: zero conditional capacity, no applied moment on the chord
    # (m_ed = 0, the moment compresses this face) and no torsion, but a real shear
    # shift. The 6.2.3(7) cap max(m_rd - m_ed, 0) = 0 would zero the shift and read
    # 0% OK; the guard makes the UNCAPPED shift fail the zero-capacity chord.
    r = combined.longitudinal_check(0.0, 0.0, ftd_v=200.0, ftd_t=0.0, z=0.5)
    assert math.isinf(r["util"]) and not r["ok"]
    assert r["mv"] == pytest.approx(100.0)          # the real shear shift is shown
    # Genuinely no demand at all -> still zero / OK (not a spurious fail).
    r0 = combined.longitudinal_check(0.0, 0.0, ftd_v=0.0, ftd_t=0.0, z=0.5)
    assert r0["util"] == 0.0 and r0["ok"]


def test_governing_strut_cot_balances_falling_and_rising_utils():
    # U_stirrup = 4/cot falls, U_chord = 1.0*cot rises: max is minimised at their
    # crossing cot = 2 (util 2.0); the scan must land there (within its resolution).
    cot, gov = combined.governing_strut_cot(
        [lambda c: 4.0 / c, lambda c: 1.0 * c], 1.0, 2.5)
    assert cot == pytest.approx(2.0, abs=2e-3)
    assert gov == pytest.approx(2.0, abs=2e-3)


def test_governing_strut_cot_clamps_to_band():
    # A falling util alone -> the flattest allowed strut (the old resistance-max).
    cot, _ = combined.governing_strut_cot([lambda c: 1.0 / c], 1.0, 2.5)
    assert cot == pytest.approx(2.5)
    # A rising util alone -> the steepest allowed strut.
    cot, _ = combined.governing_strut_cot([lambda c: c], 1.0, 2.5)
    assert cot == pytest.approx(1.0)
    # Crossing outside the band clamps to the edge: 9/cot vs cot cross at 3 > 2.5.
    cot, _ = combined.governing_strut_cot([lambda c: 9.0 / c, lambda c: c], 1.0, 2.5)
    assert cot == pytest.approx(2.5)


def test_governing_strut_cot_flat_objective_prefers_lower_cot():
    # All-constant utilisations (no load): ties break to the steeper strut (less
    # longitudinal steel demand); empty utils return the band's low edge.
    cot, _ = combined.governing_strut_cot([lambda c: 0.5], 1.0, 2.5)
    assert cot == pytest.approx(1.0)
    cot, gov = combined.governing_strut_cot([], 1.0, 2.5)
    assert cot == pytest.approx(1.0) and gov == 0.0


def test_governing_strut_cot_reversed_band():
    cot, _ = combined.governing_strut_cot([lambda c: 1.0 / c], 2.5, 1.0)
    assert cot == pytest.approx(2.5)


# -- app integration (AppTest) ----------------------------------------------

def _fresh():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state[capacity.TORSION_CASE_AUTHORITIES_KEY] = {
        "PL-01": {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                capacity.TORSION_DESIGN_EQUILIBRIUM
            ),
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: capacity.TORSION_MEMBER_CLOSED,
        }
    }
    at.session_state["torsion_design_basis"] = (
        capacity.TORSION_DESIGN_EQUILIBRIUM
    )
    at.session_state["torsion_member_scope"] = capacity.TORSION_MEMBER_CLOSED
    return at


def _fresh_unclassified():
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
    at.button(key="calculate").click().run(timeout=CALCULATION_RUN_TIMEOUT)
    return at


def _select_view(at, value):
    _goto_page(at, "Analysis")
    at.selectbox(key="view").set_value(value).run()
    return at


def _set(at, *changes):
    return apply_widget_changes(at, changes)


def _set_and_click(at, button_key, *changes, run_timeout=None):
    """Submit inputs, navigate if needed, then click the page-local action."""
    if button_key == "calculate" and changes:
        _set(at, *changes)
        changes = ()
    for widget_type, key, value in changes:
        getattr(at, widget_type)(key=key).set_value(value)
    if button_key == "calculate":
        _goto_page(at, "Analysis")
    at.button(key=button_key).click()
    if run_timeout is None and button_key == "calculate":
        run_timeout = CALCULATION_RUN_TIMEOUT
    return at.run(timeout=run_timeout)


def _translate_section_y(at, offset_mm):
    """Translate every section point while reseeding the rendered editors."""
    _goto_page(at, "Inputs")
    editors = {
        "corners_base": "ed_corners",
        "hole_base": "ed_hole",
        "bars_base": "ed_bars",
        "tendons_base": "ed_tendons",
    }
    for base_key, editor_key in editors.items():
        table = at.session_state[base_key].copy(deep=True)
        if "y (mm)" in table.columns:
            table["y (mm)"] = table["y (mm)"] + offset_mm
        try:
            version = at.session_state[editor_key + "_ver"]
        except KeyError:
            version = 0
        at.session_state[base_key] = table
        at.session_state[editor_key + "_ver"] = version + 1
        try:
            del at.session_state[editor_key]
        except KeyError:
            pass
    at.run()
    return at


def _enable_all(at, mv_independent=False):
    _set(
        at,
        ("number_input", "pl_Mx", 100.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    second = [
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "torsion_T", 40.0),
    ]
    if mv_independent:
        second.append(("checkbox", "combined_mv_independent", True))
    _set_and_click(at, "calculate", *second)
    return at


def test_biaxial_shear_with_torsion_keeps_two_screens_and_no_three_way_claim():
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 40.0),
        ("number_input", "pl_My", 30.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_Vx", 10.0),
        ("number_input", "shear_Vy", 12.0),
        ("number_input", "torsion_T", 5.0),
    )

    assert not at.exception
    results = at.session_state["results"]
    assert "generic_cross_direction_interaction_calculated" not in results["shear"]
    assert "status" not in results["shear"]
    assert "interaction_assessed" not in results["shear"]
    assert set(results["combined"]["directions"]) == {"vx", "vy"}
    assert "generic_cross_direction_interaction_calculated" not in results["combined"]
    assert "status" not in results["combined"]
    assert "interaction_status" not in results["combined"]
    assert set(results["torsion"]["directional_interactions"]) == {"vx", "vy"}
    for item in results["combined"]["directions"].values():
        assert item["governing_face"] in {"negative", "positive"}
        assert item["governing_cot"] is not None

    _select_view(at, "M-V-T Combined")
    assert not at.exception
    assert any(
        "generic simultaneous" in item.value.lower()
        and "not calculated" in item.value.lower()
        for item in at.info
    )
    table = next(
        frame.value for frame in at.dataframe
        if "Bending util." in frame.value.columns
    )
    assert "Governing face" in table.columns
    assert f"cot {chr(0x03B8)}" in table.columns


def test_biaxial_combined_reuses_one_lazy_normal_bending_action_solve(
    monkeypatch,
):
    original = capacity.dkna_normal_bending_action_alone
    production_calls = 0
    publication_calls = 0

    def counted(inp):
        nonlocal production_calls, publication_calls
        # Publication independently reconstructs authority after production.
        # The directional producer must still reuse one N/M solve.
        callers = {frame.function for frame in inspect.stack(context=0)}
        if "_single_combined_publication_evidence_is_current" in callers:
            publication_calls += 1
        elif "_run_uniaxial_capacity_checks" in callers:
            production_calls += 1
        else:
            pytest.fail("Unexpected normal-bending solve caller")
        return original(inp)

    monkeypatch.setattr(
        capacity, "dkna_normal_bending_action_alone", counted
    )
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 40.0),
        ("number_input", "pl_My", 30.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_Vx", 10.0),
        ("number_input", "shear_Vy", 12.0),
        ("number_input", "torsion_T", 5.0),
    )

    assert not at.exception
    assert production_calls == 1
    assert publication_calls > 0
    aggregate = at.session_state["results"]["combined"]
    assert set(aggregate["directions"]) == {"vx", "vy"}
    assert all(
        set(direction["action_alone"]) == {"n", "m", "v", "t"}
        for direction in aggregate["directions"].values()
    )


def test_biaxial_combined_keeps_directional_failure_without_aggregate_verdict():
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 1.0),
        ("number_input", "pl_My", 1.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_Vx", 1.0),
        ("number_input", "shear_Vy", 1.0),
        ("number_input", "torsion_T", 500.0),
    )

    assert not at.exception
    results = at.session_state["results"]
    assert all(
        direction["resistance_status"] == "PASS"
        and direction["status"] == "FAIL"
        and direction["links"]["longitudinal_assessment"]["status"] == "FAIL"
        for direction in results["shear"]["directions"].values()
    )
    combined = results["combined"]
    assert any(
        not direction["dkna_ok"]
        for direction in combined["directions"].values()
    )
    assert all(
        "status" not in direction and "governing_util" not in direction
        for direction in combined["directions"].values()
    )
    assert "generic_cross_direction_interaction_calculated" not in combined
    assert "status" not in combined
    assert "governing_component" not in combined


def test_biaxial_directional_vt_outside_permitted_range_withholds_verdicts():
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 20.0),
        ("number_input", "pl_My", 15.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "strut_cot_max", 3.0),
        ("number_input", "shear_Vx", 10.0),
        ("number_input", "shear_Vy", 12.0),
        ("number_input", "torsion_T", 5.0),
    )

    assert not at.exception
    interactions = at.session_state["results"]["torsion"][
        "directional_interactions"
    ]
    assert all(
        item["valid"] is False
        and item["reason"] == shear.STRUT_ANGLE_OUT_OF_RANGE_REASON
        and item["assessment_status"] == "NOT ASSESSED"
        and item["resistance_status"] == "NOT ASSESSED"
        and item["transverse_resistance_assessed"] is False
        and item["util"] is None
        and item.get("interaction") is None
        and item["angle_applicability"]["applicable"] is False
        for item in interactions.values()
    )
    combined_directions = at.session_state["results"]["combined"]["directions"]
    assert set(combined_directions) == {"vx", "vy"}
    assert all(
        item["valid"] is False
        and item["torsion_assessment_status"] == "NOT ASSESSED"
        and item["governing_cot"] is None
        and "dkna_sum" not in item
        and "action_alone" not in item
        for item in combined_directions.values()
    )
    _select_view(at, "Torsion")
    visible = " ".join(
        str(item.value)
        for collection in (at.warning, at.caption, at.markdown)
        for item in collection
    )
    assert "NOT ASSESSED" in visible
    assert "outside the permitted range" in visible
    screens = [frame.value for frame in at.dataframe
               if "Directional screen" in frame.value.columns]
    assert len(screens) == 1
    screen = screens[0]
    assert tuple(screen["Directional screen"]) == ("Vx,Ed + TEd", "Vy,Ed + TEd")
    assert set(screen["Status"]) == {"NOT ASSESSED"}
    assert set(screen["Governing face"]) == {"-"}
    assert screen[["TEd/TRd", "6.29 V+T", f"cot {chr(0x03B8)}"]].isna().all().all()
    minimum_screens = [frame.value for frame in at.dataframe
                       if "Directional 6.31 screen" in frame.value.columns]
    assert len(minimum_screens) == 1
    assert tuple(minimum_screens[0]["Directional 6.31 screen"]) == (
        "Vx,Ed + TEd", "Vy,Ed + TEd",
    )
    assert set(minimum_screens[0]["Status"]) == {"NOT ASSESSED"}
    assert minimum_screens[0]["6.31 sum"].isna().all()

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    rows = overview.loc[
        overview["Check"].str.contains("Combined M-V-T", regex=False)
    ]
    assert not rows.empty
    assert set(rows["Status"]) == {"NOT ASSESSED"}
    assert set(rows["Result"]) == {"-"}



def _run_member(
    at,
    *,
    mx=0.0,
    p=0.0,
    v=0.0,
    t=0.0,
    combined_on=True,
    strut_band=None,
):
    """Configure a complete M-V-T member with only the reruns needed for reveals."""
    _goto_page(at, "Inputs")
    # Once a shared AppTest has revealed every conditional member input, later load
    # cases can update all values and calculate in one rerun. This keeps repeated
    # engineering comparisons independent at result level without rebuilding the
    # same Streamlit controls two extra times per case.
    ready = (
        at.checkbox(key="shear_on").value
        and at.checkbox(key="torsion_on").value
        and at.checkbox(key="shear_links").value
    )
    if ready:
        changes = [
            ("number_input", "pl_Mx", mx),
            ("number_input", "pl_P", p),
            ("checkbox", "combined_on", combined_on),
            ("number_input", "shear_V", v),
            ("number_input", "torsion_T", t),
        ]
        if strut_band is not None:
            changes.extend([
                ("number_input", "strut_cot_min", strut_band[0]),
                ("number_input", "strut_cot_max", strut_band[1]),
            ])
        _set_and_click(at, "calculate", *changes)
        return at

    _set(
        at,
        ("number_input", "pl_Mx", mx),
        ("number_input", "pl_P", p),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", combined_on),
    )
    active = [
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", v),
        ("number_input", "torsion_T", t),
    ]
    if strut_band is None:
        _set_and_click(at, "calculate", *active)
        return at
    _set(at, *active)
    bands = [
        ("number_input", "strut_cot_min", strut_band[0]),
        ("number_input", "strut_cot_max", strut_band[1]),
    ]
    _set_and_click(at, "calculate", *bands)
    return at


def test_app_blocked_torsion_retains_shear_and_blocks_every_combined_verdict():
    at = _fresh_unclassified()
    at.run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "torsion_T", 40.0),
    )

    assert not at.exception
    results = at.session_state["results"]
    assert results["shear"]["assessment_status"] in {"PASS", "FAIL"}
    assert results["shear"]["nominal_resistance"]["resistance"] is not None
    assert results["torsion"]["assessment_status"] == "NOT ASSESSED"
    assert results["torsion"]["trd"] is None
    assert results["torsion"]["util"] is None
    assert results["combined"]["valid"] is False
    assert results["combined"]["torsion_assessment_status"] == "NOT ASSESSED"
    assert "dkna_sum" not in results["combined"]
    assert "action_alone" not in results["combined"]

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    torsion_rows = overview.loc[
        overview["Check"].str.contains("Torsion", case=False, regex=False)
    ]
    assert "NOT ASSESSED" in set(torsion_rows["Status"])
    assert not any(
        value not in {"-", "NOT ASSESSED"}
        for value in torsion_rows.loc[
            torsion_rows["Status"] == "NOT ASSESSED", "Result"
        ]
    )
    combined_rows = overview.loc[
        overview["Check"].str.contains("Combined M-V-T", regex=False)
    ]
    assert not combined_rows.empty
    assert set(combined_rows["Status"]) == {"NOT ASSESSED"}

    _select_view(at, "M-V-T Combined")
    visible = " ".join(
        str(item.value)
        for element_type in ("warning", "caption", "markdown", "info")
        for item in getattr(at, element_type)
    )
    assert "NOT ASSESSED" in visible
    assert "torsion" in visible.casefold()


def test_app_combined_assembles_all_three():
    at = _fresh()
    at.run()
    _enable_all(at)
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["valid"]
    assert c["dkna_valid"]
    assert c["dkna_sum"] == pytest.approx(
        c["r_n"] + c["r_m"] + c["r_v"] + c["r_t"]
    )
    assert c["dkna_selection"]["utilisation"] == pytest.approx(c["dkna_sum"])
    assert c["dkna_selection"]["all_sum"] == pytest.approx(
        c["r_n"] + c["r_m"] + c["r_v"] + c["r_t"]
    )
    assert c["dkna_selection"]["governing_chord"] == "N+M+V+T"
    assert set(c["action_alone"]) == {"n", "m", "v", "t"}
    for action in c["action_alone"].values():
        assert action["valid"]
        assert action["source_clause"].endswith("6.3.2(6)")
    v_evidence = c["action_alone"]["v"]["evidence"]
    assert v_evidence["both_faces_evaluated"] is True
    assert v_evidence["faces_evaluated"] == ["negative", "positive"]
    assert c["member_angle_selection"]["selected_index"] >= 0
    assert c["member_angle_selection"]["samples"] == 1501
    assert c["crushing"] is not None            # shear links present -> crushing check
    assert c["crushing"]["value"] == pytest.approx(
        c["crushing"]["torsion_ratio"] + c["crushing"]["shear_ratio"]
    )
    assert c["asl_torsion"] > 0.0


def test_app_dkna_publishes_signed_n_biaxial_m_and_action_alone_resistances():
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_P", 100.0),
        ("number_input", "pl_Mx", 80.0),
        ("number_input", "pl_My", -40.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 120.0),
        ("number_input", "torsion_T", 30.0),
    )
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["dkna_valid"]
    n = c["action_alone"]["n"]
    m = c["action_alone"]["m"]
    assert n["demand"] == pytest.approx(100.0)
    assert n["direction"] == "tension"
    assert n["evidence"]["zero_moment"] is True
    assert c["r_n"] == pytest.approx(abs(n["demand"]) / n["resistance"])
    assert m["demand"] == pytest.approx(math.hypot(80.0, -40.0))
    assert m["direction"] == pytest.approx(
        math.degrees(math.atan2(-40.0, 80.0)) % 360.0
    )
    assert m["evidence"]["axial_action_kn"] == pytest.approx(0.0)
    assert c["r_m"] == pytest.approx(m["demand"] / m["resistance"])

    _select_view(at, "M-V-T Combined")
    assert not at.exception
    labels = {metric.label for metric in at.metric}
    assert {r"Axial $N$", r"Bending $M$", r"Shear $V$", r"Torsion $T$"} <= labels
    visible = " ".join(
        str(item.value) for item in (*at.caption, *at.warning, *at.info)
    ).lower()
    assert "acting alone" in visible
    assert "biaxial moment direction" in visible
    assert "does not replace" in visible
    assert "annex f" in visible
    assert "folded" not in visible

    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_P", -100.0),
    )
    assert not at.exception
    compression = at.session_state["results"]["combined"]
    compression_n = compression["action_alone"]["n"]
    assert compression_n["demand"] == pytest.approx(-100.0)
    assert compression_n["direction"] == "compression"
    assert compression_n["evidence"]["zero_moment"] is True
    assert compression["r_n"] == pytest.approx(
        abs(compression_n["demand"]) / compression_n["resistance"]
    )


def test_app_dkna_unavailable_action_alone_resistance_is_not_assessed(
    monkeypatch,
):
    def unavailable(_inp):
        return {
            "n": capacity._dkna_action_record("N", 0.0, None, valid=True),
            "m": capacity._dkna_action_record(
                "M",
                100.0,
                None,
                valid=False,
                reason=(
                    "An action-alone resistance could not be determined. Check "
                    "the section, materials and complete Plastic bending sweep."
                ),
            ),
        }

    monkeypatch.setattr(
        capacity, "dkna_normal_bending_action_alone", unavailable
    )
    at = _fresh()
    at.run()
    _enable_all(at)
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["valid"]
    assert not c["dkna_valid"]
    assert c["dkna_sum"] is None
    assert c["dkna_ok"] is None

    _select_view(at, "M-V-T Combined")
    assert not at.exception
    combined_metric = next(
        metric for metric in at.metric
        if metric.label == r"$\sum(S_{Ed}/S_{Rd})$"
    )
    assert combined_metric.value == "-"
    assert combined_metric.delta in {None, ""}
    assert any("NOT ASSESSED" in warning.value for warning in at.warning)
    assert {
        "Concrete compression strut",
        "Closed stirrup",
        "Longitudinal reinforcement",
    } <= {metric.label for metric in at.metric}


def test_app_biaxial_unavailable_prerequisite_retains_selected_separate_route(
    monkeypatch,
):
    def unavailable(_inp):
        return {
            "n": capacity._dkna_action_record("N", 0.0, None, valid=True),
            "m": capacity._dkna_action_record(
                "M",
                50.0,
                None,
                valid=False,
                reason=(
                    "An action-alone resistance could not be determined. Check "
                    "the section, materials and complete Plastic bending sweep."
                ),
            ),
        }

    monkeypatch.setattr(
        capacity, "dkna_normal_bending_action_alone", unavailable
    )
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 40.0),
        ("number_input", "pl_My", 30.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("checkbox", "combined_mv_independent", True),
        ("number_input", "shear_Vx", 10.0),
        ("number_input", "shear_Vy", 12.0),
        ("number_input", "torsion_T", 5.0),
    )

    assert not at.exception
    aggregate = at.session_state["results"]["combined"]
    assert aggregate["biaxial"] is True
    assert aggregate["m_v_independent"] is True
    assert aggregate["m_v_separation_condition"]["declared"] is True
    assert set(aggregate["directions"]) == {"vx", "vy"}
    assert all(
        direction["m_v_independent"] is True
        and direction["dkna_valid"] is False
        for direction in aggregate["directions"].values()
    )
    assert result_presentation.combined_dkna_screen_label(aggregate) == (
        "max(N+M+T, N+V+T)"
    )

    _select_view(at, "M-V-T Combined")
    assert not at.exception
    visible = " ".join(
        str(item.value)
        for family in (at.caption, at.warning, at.info)
        for item in family
    )
    assert "NOT ASSESSED" in visible
    assert "action-alone" in visible


def test_app_combined_longitudinal_check():
    at = _fresh()
    at.run()
    _enable_all(at)
    c = at.session_state["results"]["combined"]
    lg = c["longitudinal"]                       # links are on, so the check is present
    assert lg["valid"]
    assert lg["axis"] in ("x", "y")
    # MEd,total is the applied moment plus the (non-negative) shear + torsion moments.
    assert lg["m_total"] == pytest.approx(lg["m_ed"] + lg["mv"] + lg["mt"])
    assert lg["mt"] > 0.0                         # torsion is acting
    assert lg["util"] == pytest.approx(lg["m_total"] / lg["m_rd"])
    assert math.isfinite(lg["util"])
    assert not lg["biaxial"]                       # default My_pl = 0 -> uniaxial
    assert lg["off_util"] == pytest.approx(0.0)
    # MRd is the pure-axis chord capacity (shear-face angle solve), never above the
    # biaxial M-M sweep extremum about that axis (which can sit at a point with a
    # companion off-axis moment and overstate the uniaxial chord capacity).
    assert 0.0 < lg["m_rd"] <= at.session_state["results"]["plastic"]["max_mx"] + 1e-6


def test_app_combined_longitudinal_biaxial_flagged():
    at = _fresh()
    at.run()
    _enable_all(at)                                # uniaxial first (My_pl = 0)
    _set_and_click(
        at, "calculate", ("number_input", "pl_My", 100.0)
    )  # add an off-axis moment
    lg = at.session_state["results"]["combined"]["longitudinal"]
    assert lg["biaxial"]                           # off-axis moment now non-negligible
    assert lg["off_util"] > 0.05


def test_app_combined_mv_independent_uses_max():
    at = _fresh()
    at.run()
    _enable_all(at, mv_independent=True)
    _goto_page(at, "Inputs")
    route = at.checkbox(key="combined_mv_independent")
    assert route.label == r"Apply separate $M$/$V$ route as a design assumption"
    assert "capacity, distribution and anchorage" in route.help
    assert "within the numerical limit is CONDITIONAL" in route.help
    assert "above the limit is FAIL even under" in route.help
    c = at.session_state["results"]["combined"]
    assert c["dkna_sum"] == pytest.approx(
        c["r_n"] + max(c["r_m"] + c["r_t"], c["r_v"] + c["r_t"])
    )
    assert c["dkna_selection"]["governing_chord"] in {"N+M+T", "N+V+T"}
    assert c["dkna_status"] == "CONDITIONAL"
    assert c["dkna_conditional"] is True
    assert c["dkna_ok"] is None
    assert c["dkna_limit_satisfied"] is (
        c["dkna_sum"] <= 1.0 + 1e-9
    )
    assert c["m_v_separation_condition"]["declared"] is True
    assert c["m_v_separation_condition"]["confirmed"] is False
    assert c["m_v_separation_condition"]["mechanically_verified"] is False
    assert "beyond" in c["m_v_separation_condition"]["condition"]
    _select_view(at, "M-V-T Combined")
    visible = " ".join(
        str(item.value) for item in (*at.caption, *at.warning, *at.info)
    )
    assert "CONDITIONAL" in visible
    assert "design assumption" in visible
    assert "area, distribution and anchorage" in visible
    assert "is confirmed" not in visible
    assert "N + M + T and N + V + T" in visible

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    row = overview.loc[
        overview["Check"] == "Combined M-V-T - DK NA sum"
    ].iloc[0]
    assert row["Status"] == "NOT ASSESSED"


@pytest.mark.parametrize("shear_force", (60.0, 100.0))
def test_app_separate_mv_toggle_cannot_turn_same_actions_into_pass(shear_force):
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 275.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", shear_force),
        ("number_input", "torsion_T", 40.0),
    )
    simultaneous = copy.deepcopy(at.session_state["results"]["combined"])

    _set_and_click(
        at,
        "calculate",
        ("checkbox", "combined_mv_independent", True),
    )
    separate = at.session_state["results"]["combined"]

    assert simultaneous["action_alone"] == separate["action_alone"]
    assert simultaneous["dkna_sum"] > 1.0
    assert simultaneous["dkna_status"] == "FAIL"
    assert simultaneous["dkna_ok"] is False
    expected_sum = (separate["r_n"] + separate["r_t"]
                    + max(separate["r_m"], separate["r_v"]))
    assert separate["dkna_sum"] == pytest.approx(expected_sum)
    if shear_force == 60.0:
        # Both possible shear faces use concrete at V=60; the lower action-alone
        # resistance is 94.306565842 kN. With M=275 and T=40, max(M,V)+T is
        # below one, while M+V+T exceeds it. The favourable assumption is still
        # CONDITIONAL and can never certify a PASS.
        assert separate["action_alone"]["v"]["resistance"] == pytest.approx(
            94.30656584213839
        )
        assert separate["dkna_sum"] < 1.0
        assert separate["dkna_limit_satisfied"] is True
        assert separate["dkna_status"] == "CONDITIONAL"
        assert separate["dkna_ok"] is None
    else:
        # Preserve the original 275/100/40 case: it exceeds one even under the
        # favourable assumption with the current action-alone denominators.
        assert separate["dkna_sum"] > 1.0
        assert separate["dkna_limit_satisfied"] is False
        assert separate["dkna_status"] == "FAIL"
        assert separate["dkna_ok"] is False

    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_Mx", 400.0),
    )
    over_limit = at.session_state["results"]["combined"]
    assert over_limit["m_v_independent"] is True
    assert over_limit["dkna_sum"] > 1.0
    assert over_limit["dkna_limit_satisfied"] is False
    assert over_limit["dkna_conditional"] is True
    assert over_limit["dkna_status"] == "FAIL"
    assert over_limit["dkna_ok"] is False

    _select_view(at, "M-V-T Combined")
    visible = " ".join(
        str(item.value)
        for family in (at.markdown, at.warning)
        for item in family
    )
    assert "FAIL" in visible
    assert "even under the favourable" in visible
    assert "failed numerical check governs" in visible

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    row = overview.loc[
        overview["Check"] == "Combined M-V-T - DK NA sum"
    ].iloc[0]
    assert row["Status"] == "FAIL"


def test_app_combined_edition_lock():
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("selectbox", "combined_method", codes.EC2_2005.label),
        ("number_input", "shear_V", 150.0),
        ("number_input", "torsion_T", 40.0),
    )
    assert not at.exception
    res = at.session_state["results"]
    # both checks follow the shared edition, and their own selectors are locked.
    assert res["shear"]["method"] == codes.EC2_2005.label
    assert res["torsion"]["method"] == codes.EC2_2005.label
    _goto_page(at, "Inputs")
    assert at.selectbox(key="shear_method").disabled
    assert at.selectbox(key="torsion_method").disabled


def test_app_base_en_keeps_physical_interactions_without_dkna_artifacts():
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 100.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
        ("selectbox", "combined_method", codes.EC2_2005.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "torsion_T", 40.0),
    )

    assert not at.exception
    results = at.session_state["results"]
    assert results["shear"]["method"] == codes.EC2_2005.label
    assert results["torsion"]["method"] == codes.EC2_2005.label
    combined_result = results["combined"]
    assert combined_result["method"] == codes.EC2_2005.label
    assert combined_result["crushing"]["valid"] is True
    assert combined_result["transverse"]["valid"] is True
    assert combined_result["longitudinal"]["valid"] is True
    for forbidden in (
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
        "dkna_status",
        "dkna_ok",
        "dkna_selection",
        "action_alone",
    ):
        assert forbidden not in combined_result

    _goto_page(at, "Inputs")
    assert "combined_mv_independent" not in {
        widget.key for widget in at.checkbox
    }
    _select_view(at, "M-V-T Combined")
    visible = " ".join(
        str(item.value)
        for family in (at.info, at.warning, at.caption, at.markdown)
        for item in family
    )
    assert "Base EN reports its supported V+T concrete" in visible
    assert "No additional aggregate interaction verdict" in visible
    assert "ONE member strut angle shared" in visible
    assert "selected to minimise the governing utilisation" in visible
    assert "DK NA" not in visible
    assert "action-alone" not in visible

    combined_result["longitudinal"]["theta_mode"] = "unknown"
    _select_view(at, "M-V-T Combined")
    visible = " ".join(
        str(item.value)
        for family in (at.info, at.warning, at.caption, at.markdown)
        for item in family
    )
    assert "does not identify how the member strut angle was selected" in visible
    assert "No shear or torsion is acting" not in visible

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    checks = tuple(str(value) for value in overview["Check"])
    assert any("concrete compression strut" in value.casefold() for value in checks)
    assert any("closed stirrup" in value.casefold() for value in checks)
    assert any("longitudinal reinforcement" in value.casefold() for value in checks)
    assert not any("DK NA" in value for value in checks)


def test_app_base_en_biaxial_view_keeps_only_directional_physical_checks():
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 40.0),
        ("number_input", "pl_My", 30.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
        ("selectbox", "combined_method", codes.EC2_2005.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_Vx", 10.0),
        ("number_input", "shear_Vy", 12.0),
        ("number_input", "torsion_T", 5.0),
    )

    assert not at.exception
    aggregate = at.session_state["results"]["combined"]
    assert aggregate["method"] == codes.EC2_2005.label
    assert set(aggregate["directions"]) == {"vx", "vy"}
    for direction in aggregate["directions"].values():
        assert direction["method"] == codes.EC2_2005.label
        assert "action_alone" not in direction
        assert not any(key.startswith("dkna_") for key in direction)

    _select_view(at, "M-V-T Combined")
    direction_table = next(
        frame.value
        for frame in at.dataframe
        if "Directional screen" in frame.value.columns
    )
    assert tuple(direction_table["Directional screen"]) == (
        "Vx,Ed + TEd",
        "Vy,Ed + TEd",
    )
    assert {"Concrete strut", "Closed stirrup", "Longitudinal"}.issubset(
        direction_table.columns
    )
    assert not any("DK NA" in str(column) for column in direction_table.columns)
    assert not any("action-alone" in str(column).casefold() for column in direction_table.columns)

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    checks = tuple(str(value) for value in overview["Check"])
    assert "Combined Vx+T concrete compression strut" in checks
    assert "Combined Vx+T closed stirrup" in checks
    assert not any("DK NA" in value or "action-alone" in value.casefold() for value in checks)


def _assert_current_native_mvt_views(at, *, longitudinal=False):
    """Prove a real producer positive before an adversarial saved-result edit."""
    inp = at.session_state["result_input_snapshot"]
    results = at.session_state["results"]
    assert results["plastic"]["util_valid"] is True
    assert result_presentation.combined_publication_evidence_is_current(inp, results)[0] is True
    assert result_presentation.combined_bending_assessment_blocker(results, inp) is None
    pristine = copy.deepcopy(results)
    component = next(item for item in
                     result_presentation.combined_physical_components(results["combined"])
                     if item["key"] == "longitudinal") if longitudinal else None
    _select_view(at, "M-V-T Combined")
    assert not at.exception
    assert not any("Combined M-V-T is NOT ASSESSED" in item.value for item in at.warning)
    assert at.metric or at.dataframe
    if longitudinal:
        physical = next(metric for metric in at.metric
                        if metric.label == "Longitudinal reinforcement")
        physical_value = str(physical.value)
        expected_value = "-" if component["util"] is None else f"{component['util'] * 100:.1f} %"
        assert physical_value == expected_value
        if component["status"] in {"PASS", "FAIL"}:
            assert physical.delta == component["status"]
        else:
            assert component["status"] == "NOT ASSESSED"
            assert physical.delta in {None, ""}
        # Chord and overall Formula6.28/longitudinal assessment remain distinct.
        assert component["chord_status"] in {"PASS", "FAIL"}
        chord = next(metric for metric in at.metric if metric.label == "Chord utilisation")
        assert chord.delta == component["chord_status"]
        assert str(chord.value) == f"{component['chord_util'] * 100:.1f} %"
    _select_view(at, "Results Overview")
    overview = next(table.value for table in at.table if "Check" in table.value)
    rows = overview[overview["Check"].str.startswith("Combined ")]
    assert not rows.empty
    assessed = rows[rows["Status"].isin(["PASS", "FAIL"])]
    assert not assessed.empty
    assert all(value != "-" for value in assessed["Result"])
    if longitudinal:
        target = rows[rows["Check"] == "Combined longitudinal reinforcement"]
        assert len(target) == 1
        assert (target.iloc[0]["Status"], target.iloc[0]["Result"]) == (
            component["status"], physical_value,
        )
    return pristine


def _assert_rejected_native_mvt_views(at):
    """An actual guard rejection must produce explicit unavailable Overview rows."""
    inp = at.session_state["result_input_snapshot"]
    results = at.session_state["results"]
    assert result_presentation.combined_publication_evidence_is_current(inp, results)[0] is False
    blocker = result_presentation.combined_bending_assessment_blocker(results, inp)
    assert isinstance(blocker, str) and blocker
    _select_view(at, "M-V-T Combined")
    assert not at.exception
    assert any("Combined M-V-T is NOT ASSESSED" in item.value and blocker in item.value
               for item in at.warning)
    values = {str(metric.value) for metric in at.metric}
    assert not values.difference({"-", "NOT ASSESSED"})
    assert not any("Directional screen" in frame.value.columns for frame in at.dataframe)
    captions = " ".join(str(item.value) for item in at.caption)
    _select_view(at, "Results Overview")
    assert not at.exception
    overview = next(table.value for table in at.table if "Check" in table.value)
    rows = overview[overview["Check"].str.startswith("Combined ")]
    assert not rows.empty
    assert set(rows["Status"]) == {"NOT ASSESSED"}
    assert set(rows["Result"]) == {"-"}
    return {"rows": rows, "values": values, "captions": captions}


def _restore_current_native_mvt_views(at, pristine, *, longitudinal=False):
    at.session_state["results"] = copy.deepcopy(pristine)
    _assert_current_native_mvt_views(at, longitudinal=longitudinal)


def _base_en_component_view(combined_result):
    """Render the declared component unit, outside ordinary native publication."""
    from streamlit.testing.v1 import AppTest

    leaf = AppTest.from_string(
        "import streamlit as st\nimport sector_app\n"
        "sector_app._render_base_en_combined(st.session_state['component'])\n",
        default_timeout=60,
    )
    leaf.session_state["component"] = copy.deepcopy(combined_result)
    leaf.run()
    assert not leaf.exception
    return leaf


@pytest.mark.parametrize("malformed_vy", ("missing", "empty"))
def test_app_base_en_missing_biaxial_direction_fails_closed(malformed_vy):
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 40.0),
        ("number_input", "pl_My", 30.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
        ("selectbox", "combined_method", codes.EC2_2005.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_Vx", 10.0),
        ("number_input", "shear_Vy", 12.0),
        ("number_input", "torsion_T", 5.0),
    )
    pristine = _assert_current_native_mvt_views(at)
    aggregate = at.session_state["results"]["combined"]
    assert set(aggregate["directions"]) == {"vx", "vy"}
    assert all(aggregate["directions"].values())
    assert result_presentation.base_en_combined_direction_items(aggregate) is not None
    if malformed_vy == "missing":
        aggregate["directions"].pop("vy")
    else:
        aggregate["directions"]["vy"] = {}

    assert result_presentation.base_en_combined_direction_items(aggregate) is None
    proof = _assert_rejected_native_mvt_views(at)
    combined_rows = proof["rows"]
    assert tuple(combined_rows["Check"]) == ("Combined M-V-T supported components",)
    assert tuple(combined_rows["Status"]) == ("NOT ASSESSED",)
    assert tuple(combined_rows["Result"]) == ("-",)
    _restore_current_native_mvt_views(at, pristine)


@pytest.mark.parametrize(
    ("retained", "transverse_retained"),
    (
        (True, True),
        ("0.5", "0.5"),
        (-0.25, -0.25),
        (math.inf, True),
    ),
)
def test_app_base_en_invalid_utilisations_are_not_published(
    retained,
    transverse_retained,
):
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 100.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
        ("selectbox", "combined_method", codes.EC2_2005.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "torsion_T", 40.0),
    )
    pristine = _assert_current_native_mvt_views(at)
    combined = at.session_state["results"]["combined"]
    combined["transverse"].update(
        u_crush=transverse_retained,
        u_stirrup=transverse_retained,
        shear_fraction=transverse_retained,
        torsion_fraction=transverse_retained,
    )
    combined["crushing"]["value"] = transverse_retained
    combined["longitudinal"]["util"] = retained
    combined["governing_longitudinal"] = combined["longitudinal"]
    combined["longitudinal_assessment"].update(status="PASS", util=retained)
    combined["torsion_longitudinal_assessment"] = {
        "status": "FAIL",
        "demand_ratio": retained,
        "reason": "longitudinal_torsion_reinforcement_not_verified",
    }

    leaf = _base_en_component_view(combined)
    assert not leaf.exception
    component_metrics = {
        metric.label: str(metric.value)
        for metric in leaf.metric
        if metric.label in {
            "Concrete compression strut",
            "Closed stirrup",
            "Longitudinal reinforcement",
        }
    }
    assert component_metrics["Concrete compression strut"] == "-"
    assert component_metrics["Closed stirrup"] == "-"
    assert component_metrics["Longitudinal reinforcement"] != "100.0 %"
    assert "100.0 %" not in {str(metric.value) for metric in leaf.metric}
    assert "50.0 %" not in {str(metric.value) for metric in leaf.metric}
    assert "-25.0 %" not in {str(metric.value) for metric in leaf.metric}
    assert "inf" not in {str(metric.value).casefold() for metric in leaf.metric}
    assert sum(caption.value == "NOT ASSESSED" for caption in leaf.caption) >= 3

    _assert_rejected_native_mvt_views(at)
    assert not at.exception
    overview = at.table[0].value
    combined_rows = overview[
        overview["Check"].str.startswith("Combined ")
    ]
    assert not combined_rows.empty
    assert set(combined_rows["Status"]) == {"NOT ASSESSED"}
    assert "100.0 %" not in set(combined_rows["Result"])
    assert "50.0 %" not in set(combined_rows["Result"])
    assert "-25.0 %" not in set(combined_rows["Result"])
    assert "inf" not in {str(value).casefold() for value in combined_rows["Result"]}
    _restore_current_native_mvt_views(at, pristine)


@pytest.mark.parametrize(
    ("retained", "transverse_retained"),
    (
        (True, True),
        ("0.5", "0.5"),
        (-0.25, -0.25),
        (math.inf, True),
    ),
)
def test_app_dkna_worked_details_share_invalid_utilisation_boundary(
    retained,
    transverse_retained,
):
    at = _fresh()
    at.run()
    _enable_all(at)
    pristine = _assert_current_native_mvt_views(at)
    combined = at.session_state["results"]["combined"]
    combined["transverse"].update(
        u_crush=transverse_retained,
        u_stirrup=transverse_retained,
        shear_fraction=transverse_retained,
        torsion_fraction=transverse_retained,
    )
    combined["crushing"]["value"] = transverse_retained
    combined["longitudinal"]["util"] = retained
    combined["governing_longitudinal"] = combined["longitudinal"]
    combined["longitudinal_assessment"].update(
        status="PASS", util=retained
    )
    combined["torsion_longitudinal_assessment"] = {
        "status": "FAIL",
        "demand_ratio": retained,
        "reason": "longitudinal_torsion_reinforcement_not_verified",
    }

    # The old Sum/stirrup widgets represented these canonical components.
    # Ordinary native publication now rejects the complete poisoned family first.
    physical = {item["key"]: item for item in
                result_presentation.combined_physical_components(combined)}
    for key in ("concrete", "stirrup"):
        assert physical[key]["status"] == "NOT ASSESSED"
        assert physical[key]["util"] is None
    longitudinal = capacity.combined_longitudinal_assessment(combined)
    assert longitudinal["chord_status"] == "NOT ASSESSED"
    assert longitudinal["chord_util"] is None
    # Independently valid orthogonal children are not rewritten or invalidated.
    proof = _assert_rejected_native_mvt_views(at)
    visible_metrics = proof["values"]
    assert "100.0 %" not in visible_metrics
    assert "50.0 %" not in visible_metrics
    assert "-25.0 %" not in visible_metrics
    assert "inf" not in {value.casefold() for value in visible_metrics}
    _restore_current_native_mvt_views(at, pristine)


def test_app_direct_shear_and_formula_629_invalid_utilisations_are_not_assessed():
    at = _fresh()
    at.run()
    _enable_all(at)
    pristine = _assert_current_native_mvt_views(at)

    _select_view(at, "Shear")
    valid_shear_metric = next(
        metric
        for metric in at.metric
        if metric.label == r"Utilisation $V_{Ed}/V_{Rd}$"
    )
    assert valid_shear_metric.delta in {"PASS", "FAIL"}

    _select_view(at, "Torsion")
    valid_formula_metric = next(
        metric
        for metric in at.metric
        if metric.label == r"Sum ($\leq100\%$)"
    )
    assert valid_formula_metric.delta in {"PASS", "FAIL"}

    for rejected_utilisation in (True, math.inf):
        at.session_state["results"] = copy.deepcopy(pristine)
        results = at.session_state["results"]
        results["shear"]["links"]["util"] = rejected_utilisation
        results["torsion"]["interaction"]["value"] = rejected_utilisation
        inp = at.session_state["result_input_snapshot"]
        provided = result_presentation.provided_link_publication_assessment(
            inp, results["shear"], torsion_result=results["torsion"],
        )
        assert provided.valid is False
        assert provided.utilisation is None
        assert result_presentation.torsion_publication_component_is_current(
            inp, results["shear"], results["torsion"],
        )[0] is False
        for view, affected_label in (
            ("Shear", r"Utilisation $V_{Ed}/V_{Rd}$"),
            ("Torsion", r"Sum ($\leq100\%$)"),
        ):
            _select_view(at, view)
            assert not at.exception
            assert any("NOT ASSESSED" in item.value for item in at.warning)
            affected = [metric for metric in at.metric if metric.label == affected_label]
            assert all(str(metric.value) == "-" and metric.delta in {None, ""}
                       for metric in affected)
        _assert_rejected_native_mvt_views(at)
    _restore_current_native_mvt_views(at, pristine)


@pytest.mark.parametrize(
    "method",
    [codes.EC2_2005.label, codes.EC2_2005_DKNA.label],
)
@pytest.mark.parametrize("conflict", ["utilisation", "angle", "theta"])
def test_app_conflicting_formula_629_evidence_fails_closed_everywhere(
    method,
    conflict,
):
    at = _fresh()
    at.run()
    if method == codes.EC2_2005.label:
        _set(
            at,
            ("number_input", "pl_Mx", 100.0),
            ("checkbox", "shear_on", True),
            ("checkbox", "torsion_on", True),
            ("checkbox", "combined_on", True),
            ("selectbox", "combined_method", method),
        )
        _set_and_click(
            at,
            "calculate",
            ("checkbox", "shear_links", True),
            ("number_input", "shear_V", 150.0),
            ("number_input", "torsion_T", 40.0),
        )
    else:
        _enable_all(at)
    pristine = _assert_current_native_mvt_views(at)
    combined = at.session_state["results"]["combined"]
    if conflict == "utilisation":
        combined["transverse"]["u_crush"] = True
        combined["crushing"]["value"] = 0.50
    elif conflict == "angle":
        combined["transverse"]["u_crush"] = combined["crushing"]["value"]
        combined["transverse"]["cot"] = 1.50
        combined["crushing"]["cot"] = 1.40
    else:
        combined["transverse"]["u_crush"] = combined["crushing"]["value"]
        combined["crushing"]["theta_deg"] = 60.0

    physical = {item["key"]: item for item in
                result_presentation.combined_physical_components(combined)}
    assert physical["concrete"]["status"] == "NOT ASSESSED"
    assert physical["concrete"]["util"] is None
    if conflict in {"angle", "theta"}:
        assert physical["stirrup"]["status"] == "NOT ASSESSED"
        assert physical["stirrup"]["util"] is None
    # Keep the Base-EN Formula6.29 formatting obligation at its real leaf.
    if method == codes.EC2_2005.label:
        leaf = _base_en_component_view(combined)
        assert any("Formula (6.29) is NOT ASSESSED" in item.value for item in leaf.warning)
        concrete_metrics = [metric for metric in leaf.metric
                            if metric.label == "Concrete compression strut"]
        assert {str(metric.value) for metric in concrete_metrics} == {"-"}
        assert all(metric.delta in {None, ""} for metric in concrete_metrics)
    proof = _assert_rejected_native_mvt_views(at)
    assert "50.0 %" not in proof["values"]
    assert "1.40" not in proof["captions"]
    assert r"\theta=60.0" not in proof["captions"]
    _restore_current_native_mvt_views(at, pristine)


def test_app_combined_basis_switch_invalidates_results_and_reports():
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 100.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
        ("selectbox", "combined_method", codes.EC2_2005.label),
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "torsion_T", 40.0),
    )
    _calculate(at)
    base_before = at.session_state["results"]["combined"]
    base_signature = at.session_state["result_sig"]
    assert "action_alone" not in base_before

    _goto_page(at, "Report")
    at.session_state["_report_no_figures"] = True
    at.button(key="gen_report").click().run(timeout=REPORT_RUN_TIMEOUT)
    assert at.session_state["report_generation_record"]["result_source"] == (
        "reused-current-analysis-results"
    )
    base_report_signature = at.session_state["report_signature"]
    assert not any("Report out of date" in item.value for item in at.warning)

    _set(
        at,
        ("selectbox", "combined_method", codes.EC2_2005_DKNA.label),
        ("checkbox", "combined_mv_independent", True),
    )
    _select_view(at, "M-V-T Combined")
    assert any("press Calculate" in item.value for item in at.warning)
    _goto_page(at, "Report")
    assert any("Report out of date" in item.value for item in at.warning)
    _calculate(at)
    dk_result = at.session_state["results"]["combined"]
    dk_signature = at.session_state["result_sig"]
    assert dk_result is not base_before
    assert dk_signature != base_signature
    assert dk_result["method"] == codes.EC2_2005_DKNA.label
    assert dk_result["m_v_independent"] is True
    assert "action_alone" in dk_result
    assert "dkna_sum" in dk_result

    _goto_page(at, "Report")
    at.button(key="gen_report").click().run(timeout=REPORT_RUN_TIMEOUT)
    assert at.session_state["report_generation_record"]["result_source"] == (
        "reused-current-analysis-results"
    )
    dk_report_signature = at.session_state["report_signature"]
    assert dk_report_signature != base_report_signature

    _set(at, ("selectbox", "combined_method", codes.EC2_2005.label))
    _select_view(at, "M-V-T Combined")
    assert any("press Calculate" in item.value for item in at.warning)
    _goto_page(at, "Report")
    assert any("Report out of date" in item.value for item in at.warning)
    _calculate(at)
    base_after = at.session_state["results"]["combined"]
    assert base_after is not dk_result
    assert base_after["method"] == codes.EC2_2005.label
    assert "action_alone" not in base_after
    assert "dkna_sum" not in base_after
    assert at.session_state["combined_mv_independent"] is True
    _goto_page(at, "Inputs")
    assert "combined_mv_independent" not in {
        widget.key for widget in at.checkbox
    }


def test_mvt_m03_contract_recomputes_pre_scope_capacity_results():
    import sector_app

    at = _fresh()
    at.run()
    _set(at, ("radio", "mode", "Both"))
    _enable_all(at, mv_independent=True)

    latest = at.session_state["_latest_inputs"]
    token = sector_app._CAPACITY_RESULT_CONTRACT_TOKEN
    scope_marker = "combined-edition-scope-v1"
    assert scope_marker in token
    pre_scope_token = tuple(item for item in token if item != scope_marker)
    for key in ("plastic_case_context_sig", "plastic_sig", "signature"):
        assert tuple(latest[key]).count(token) == 1

    before = at.session_state["results"]
    plastic_before = before["plastic"]
    elastic_before = before["elastic"]
    shear_before = before["shear"]
    torsion_before = before["torsion"]
    combined_before = before["combined"]
    cached_case = before["plastic_cases"][0]
    assert cached_case["results"]["combined"] is combined_before
    combined_before["pre_mvt_m03_marker"] = True
    combined_before["dkna_sum"] = 0.01
    for key in (
        "result_sig",
        "result_plastic_sig",
        "result_plastic_case_context_sig",
    ):
        at.session_state[key] = tuple(
            pre_scope_token if item == token else item
            for item in at.session_state[key]
        )
    assert at.session_state["result_sig"] != latest["signature"]

    _calculate(at)
    refreshed = at.session_state["results"]
    assert refreshed["plastic"] is plastic_before
    assert refreshed["elastic"] is elastic_before
    assert refreshed["shear"] is not shear_before
    assert refreshed["torsion"] is not torsion_before
    assert refreshed["combined"] is not combined_before
    assert "pre_mvt_m03_marker" not in refreshed["combined"]
    assert refreshed["combined"]["dkna_sum"] != pytest.approx(0.01)
    assert refreshed["plastic_cases"][0]["reused"] is False
    assert refreshed["elastic_cases"][0]["reused"] is True
    for key in (
        "result_sig",
        "result_plastic_sig",
        "result_plastic_case_context_sig",
    ):
        assert tuple(at.session_state[key]).count(token) == 1


def test_mvt_m04_contract_recomputes_pre_range_capacity_results():
    import sector_app

    at = _fresh()
    at.run()
    _set(
        at,
        ("radio", "mode", "Both"),
        ("number_input", "strut_cot_max", 3.0),
    )
    _enable_all(at)

    latest = at.session_state["_latest_inputs"]
    token = sector_app._CAPACITY_RESULT_CONTRACT_TOKEN
    scope_marker = "compression-strut-applicability-v1"
    assert scope_marker in token
    pre_scope_token = tuple(item for item in token if item != scope_marker)
    for key in ("plastic_case_context_sig", "plastic_sig", "signature"):
        assert tuple(latest[key]).count(token) == 1

    before = at.session_state["results"]
    plastic_before = before["plastic"]
    elastic_before = before["elastic"]
    shear_before = before["shear"]
    torsion_before = before["torsion"]
    combined_before = before["combined"]
    for family in (shear_before, torsion_before, combined_before):
        family["pre_mvt_m04_marker"] = True
    shear_before["links"]["res"].update(
        valid=True,
        vrd_s=999_000.0,
        vrd_max=999_000.0,
        vrd=999_000.0,
        cot=3.0,
    )
    shear_before["links"]["util"] = 0.001
    torsion_before.update(
        valid=True,
        transverse_resistance_assessed=True,
        trd_s=999_000.0,
        trd_max=999_000.0,
        trd=999_000.0,
        cot=3.0,
        util=0.001,
        resistance_status="PASS",
    )
    combined_before.update(valid=True, dkna_sum=0.001, dkna_ok=True)
    for key in (
        "result_sig",
        "result_plastic_sig",
        "result_plastic_case_context_sig",
    ):
        at.session_state[key] = tuple(
            pre_scope_token if item == token else item
            for item in at.session_state[key]
        )
    assert at.session_state["result_sig"] != latest["signature"]

    _calculate(at)
    refreshed = at.session_state["results"]
    assert refreshed["plastic"] is plastic_before
    assert refreshed["elastic"] is elastic_before
    assert refreshed["shear"] is not shear_before
    assert refreshed["torsion"] is not torsion_before
    assert refreshed["combined"] is not combined_before
    for family_name in ("shear", "torsion", "combined"):
        assert "pre_mvt_m04_marker" not in refreshed[family_name]
    assert refreshed["shear"]["links"]["res"]["vrd"] is None
    assert refreshed["torsion"]["trd"] is None
    assert refreshed["combined"]["valid"] is False
    assert "dkna_sum" not in refreshed["combined"]
    assert refreshed["plastic_cases"][0]["reused"] is False
    assert refreshed["elastic_cases"][0]["reused"] is True
    for key in (
        "result_sig",
        "result_plastic_sig",
        "result_plastic_case_context_sig",
    ):
        assert tuple(at.session_state[key]).count(token) == 1
    assert at.session_state[
        sector_app._RESULT_CAPACITY_CONTRACT_KEY
    ] == token


def test_mvt_m04_contract_recomputes_when_stored_input_and_result_are_both_old():
    import sector_app

    at = _fresh()
    at.run()
    _set(
        at,
        ("radio", "mode", "Both"),
        ("number_input", "strut_cot_max", 3.0),
    )
    _enable_all(at)

    latest = copy.deepcopy(at.session_state["_latest_inputs"])
    token = sector_app._CAPACITY_RESULT_CONTRACT_TOKEN
    scope_marker = "compression-strut-applicability-v1"
    pre_scope_token = tuple(item for item in token if item != scope_marker)
    before = at.session_state["results"]
    plastic_before = before["plastic"]
    elastic_before = before["elastic"]
    shear_before = before["shear"]
    torsion_before = before["torsion"]
    combined_before = before["combined"]
    for family in (shear_before, torsion_before, combined_before):
        family["pre_mvt_m04_equal_signature_marker"] = True

    pre_scope_inputs = copy.deepcopy(latest)
    for key in ("plastic_case_context_sig", "plastic_sig", "signature"):
        pre_scope_inputs[key] = tuple(
            pre_scope_token if item == token else item
            for item in latest[key]
        )
    at.session_state["_latest_inputs"] = pre_scope_inputs
    at.session_state["result_input_snapshot"] = copy.deepcopy(pre_scope_inputs)
    at.session_state["result_sig"] = pre_scope_inputs["signature"]
    at.session_state["result_plastic_sig"] = pre_scope_inputs["plastic_sig"]
    at.session_state["result_plastic_case_context_sig"] = pre_scope_inputs[
        "plastic_case_context_sig"
    ]
    del at.session_state[sector_app._RESULT_CAPACITY_CONTRACT_KEY]
    assert at.session_state["result_sig"] == at.session_state[
        "_latest_inputs"
    ]["signature"]
    assert at.session_state["result_plastic_case_context_sig"] == (
        at.session_state["_latest_inputs"]["plastic_case_context_sig"]
    )

    _goto_page(at, "Report")
    _goto_page(at, "Analysis")
    assert any("Capacity results require recalculation" in item.value
               for item in at.caption)
    _calculate(at)

    refreshed = at.session_state["results"]
    assert refreshed["plastic"] is plastic_before
    assert refreshed["elastic"] is elastic_before
    assert refreshed["shear"] is not shear_before
    assert refreshed["torsion"] is not torsion_before
    assert refreshed["combined"] is not combined_before
    for family_name in ("shear", "torsion", "combined"):
        assert "pre_mvt_m04_equal_signature_marker" not in refreshed[family_name]
    assert refreshed["plastic_cases"][0]["reused"] is False
    assert refreshed["elastic_cases"][0]["reused"] is True
    assert at.session_state[
        sector_app._RESULT_CAPACITY_CONTRACT_KEY
    ] == token


def test_invalid_shear_leg_evidence_does_not_narrow_valid_torsion():
    import case_analysis
    import sector_app

    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 100.0),
        ("selectbox", "transverse_ductility_class", "A"),
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "strut_cot_max", 2.0),
        ("number_input", "shear_V", 500.0),
        ("number_input", "torsion_T", 40.0),
    )
    assert not at.exception

    baseline = at.session_state["results"]
    latest = at.session_state["_latest_inputs"]
    record = latest["plastic_cases"].iloc[0].to_dict()
    direct_input = case_analysis.plastic_case_input(latest, record)
    for key in ("plastic_cases", "elastic_cases"):
        direct_input.pop(key, None)

    for invalid_legs in (True, float("inf")):
        hostile_input = dict(
            direct_input,
            shear_link_legs=invalid_legs,
            shear_vx_link_legs=invalid_legs,
            shear_vy_link_legs=invalid_legs,
            strut_cot_max=2.5,
        )
        result = sector_app.run_analysis(
            hostile_input,
            reuse_plastic=baseline["plastic"],
        )

        links = result["shear"]["links"]
        assert links["legs"] is None
        assert links["res"]["valid"] is False
        assert links["res"]["calculation_state"] == "NOT ASSESSED"
        assert links["res"]["vrd"] is None
        assert "positive finite number" in links["res"]["reason"]

        torsion_result = result["torsion"]
        torsion_angle = torsion_result["angle_applicability"]
        assert torsion_angle["applicable"] is True
        assert torsion_angle["permitted_max"] == pytest.approx(2.5)
        assert "shared shear and torsion" not in torsion_angle["basis"]
        assert torsion_result["trd"] > 0.0
        assert torsion_result["util"] is not None

        combined_result = result["combined"]
        assert combined_result["valid"] is False
        assert "positive finite number" in combined_result["reason"]
        assert "dkna_sum" not in combined_result

    hostile_latest = copy.deepcopy(latest)
    hostile_latest["shear_vx_link_legs"] = True
    hostile_latest["shear_vy_link_legs"] = True
    for key in ("plastic_case_context_sig", "plastic_sig", "signature"):
        hostile_latest[key] = (
            *hostile_latest[key],
            ("hostile-shear-link-legs", key),
        )
    at.session_state["_latest_inputs"] = hostile_latest
    _goto_page(at, "Report")
    _goto_page(at, "Analysis")
    _calculate(at)

    assert not at.exception
    native = at.session_state["results"]
    native_links = native["shear"]["links"]
    assert native_links["legs"] is None
    assert native_links["res"]["calculation_state"] == "NOT ASSESSED"
    assert native_links["res"]["vrd"] is None
    assert native["torsion"]["trd"] > 0.0
    assert native["torsion"]["angle_applicability"][
        "permitted_max"
    ] == pytest.approx(2.5)
    assert "shared shear and torsion" not in native["torsion"][
        "angle_applicability"
    ]["basis"]

    _select_view(at, "Shear")
    visible = " ".join(
        item.value
        for collection in (at.warning, at.caption, at.markdown)
        for item in collection
    )
    assert "positive finite number of effective link legs" in visible
    assert not any(
        token in visible.lower()
        for token in ("boolean", "infinity", "payload", "schema", "contract")
    )


def test_app_combined_incomplete_flags_missing(monkeypatch):
    monkeypatch.setattr(
        capacity,
        "dkna_normal_bending_action_alone",
        lambda _inp: pytest.fail(
            "action-alone resistance entered for an incomplete combined check"
        ),
    )
    at = _fresh()
    at.run()
    _set_and_click(
        at, "calculate", ("checkbox", "combined_on", True)
    )  # no shear / torsion
    assert not at.exception
    assert "combined" not in at.session_state["results"]
    _select_view(at, "M-V-T Combined")
    assert any("Vx,Ed = Vy,Ed = TEd = 0" in item.value for item in at.info)

    _set(at, ("checkbox", "shear_on", True))
    _set_and_click(
        at,
        "calculate",
        ("number_input", "shear_V", 50.0),
    )
    assert not at.exception
    assert "shear" in at.session_state["results"]
    assert "torsion" not in at.session_state["results"]
    assert "combined" not in at.session_state["results"]


def test_app_combined_view_renders():
    at = _fresh()
    at.run()
    _enable_all(at)
    links = at.session_state["results"]["shear"]["links"]
    assert len(links["chord_candidates"]) == 4
    assert {item["role"] for item in links["chord_candidates"]} == {
        "shear_axis", "off_axis",
    }
    assert links["governing_longitudinal"]["util"] == pytest.approx(
        max(item["util"] for item in links["chord_candidates"])
    )
    assert links["longitudinal_all_conditional"] is (
        links["longitudinal_fallback"] is None
    )
    combined = at.session_state["results"]["combined"]
    assert combined["governing_longitudinal"] == links["governing_longitudinal"]
    assert combined["longitudinal_fallback"] == links["longitudinal_fallback"]
    assert (
        combined["longitudinal_all_conditional"]
        is links["longitudinal_all_conditional"]
    )
    _select_view(at, "M-V-T Combined")
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert any("Bending" in lbl for lbl in labels)
    assert any("S_{Ed}/S_{Rd}" in lbl for lbl in labels)
    # The summary exposes physical mechanisms, not an artificial maximum labelled
    # as transverse-reinforcement utilisation.
    for expected in (
        "Concrete compression strut",
        "Closed stirrup",
        "Longitudinal reinforcement",
    ):
        assert expected in labels
    assert "Closed-stirrup utilisation" in labels
    assert not any("Crushing utilisation" in lbl for lbl in labels)
    assert not any(lbl.startswith("Governing (") for lbl in labels)


def test_app_combined_outside_permitted_range_withholds_all_verdicts():
    at = _fresh()
    at.run()
    at.number_input(key="strut_cot_max").set_value(3.0).run()
    _enable_all(at)
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["valid"] is False
    assert c["reason"] == shear.STRUT_ANGLE_OUT_OF_RANGE_REASON
    assert c["outside_default_range"] is True
    assert c["angle_applicability"]["applicable"] is False
    assert c["angle_applicability"]["requested_max"] == 3.0
    assert c["angle_applicability"]["permitted_max"] == 2.5
    assert "dkna_sum" not in c
    assert "dkna_status" not in c
    assert "action_alone" not in c
    assert "transverse" not in c
    assert "crushing" not in c
    assert "longitudinal" not in c
    _select_view(at, "M-V-T Combined")
    assert not at.exception
    visible = " ".join(
        item.value
        for collection in (at.warning, at.caption, at.markdown)
        for item in collection
    )
    assert "Combined M-V-T is NOT ASSESSED" in visible
    assert "Torsion prerequisite is not assessed" in visible
    assert "outside the permitted range" in visible
    assert not at.metric

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    combined_rows = overview.loc[
        overview["Check"].str.contains("Combined M-V-T", regex=False)
    ]
    assert not combined_rows.empty
    assert set(combined_rows["Status"]) == {"NOT ASSESSED"}
    assert set(combined_rows["Result"]) == {"-"}


@pytest.mark.parametrize("torsion_action", (40.0, -40.0))
def test_app_shared_2023_class_a_and_torsion_range_uses_the_intersection(
    torsion_action,
):
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 100.0),
        ("selectbox", "transverse_ductility_class", "A"),
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("checkbox", "torsion_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "strut_cot_max", 2.5),
        ("number_input", "shear_V", 500.0),
        ("number_input", "torsion_T", torsion_action),
    )

    assert not at.exception
    blocked = at.session_state["results"]
    link_angle = blocked["shear"]["links"]["angle_applicability"]
    torsion_angle = blocked["torsion"]["angle_applicability"]
    assert link_angle == torsion_angle
    assert link_angle["applicable"] is False
    assert link_angle["requested_max"] == 2.5
    assert link_angle["permitted_max"] == 2.0
    assert "shared shear and torsion" in link_angle["basis"]
    assert blocked["shear"]["method"] == codes.EC2_2023.label
    assert blocked["torsion"]["method"] == codes.EC2_2005_DKNA.label
    assert blocked["shear"]["links"]["res"]["vrd"] is None
    assert blocked["torsion"]["trd"] is None
    assert blocked["torsion"].get("interaction") is None

    _set_and_click(
        at,
        "calculate",
        ("number_input", "strut_cot_max", 2.0),
    )
    recovered = at.session_state["results"]
    assert recovered["shear"]["links"]["angle_applicability"][
        "applicable"
    ] is True
    assert recovered["torsion"]["angle_applicability"]["applicable"] is True
    assert recovered["shear"]["links"]["res"]["vrd"] > 0.0
    assert recovered["torsion"]["trd"] > 0.0


def test_unavailable_shear_arm_does_not_narrow_valid_torsion(monkeypatch):
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
    _set(
        at,
        ("selectbox", "transverse_ductility_class", "A"),
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "strut_cot_max", 2.5),
        ("number_input", "shear_V", 500.0),
        ("number_input", "torsion_T", 40.0),
    )

    assert not at.exception
    results = at.session_state["results"]
    links = results["shear"]["links"]
    assert links["res"]["valid"] is False
    assert links["res"]["calculation_state"] == "NOT ASSESSED"
    assert links["res"]["z"] is None
    assert "lever arm" in links["res"]["reason"]

    torsion_result = results["torsion"]
    torsion_angle = torsion_result["angle_applicability"]
    assert torsion_angle["applicable"] is True
    assert torsion_angle["permitted_max"] == pytest.approx(2.5)
    assert "shared shear and torsion" not in torsion_angle["basis"]
    assert torsion_result["trd"] > 0.0
    assert torsion_result["util"] is not None

    combined_result = results["combined"]
    assert combined_result["valid"] is False
    assert "lever arm" in combined_result["reason"]
    assert "dkna_sum" not in combined_result


def test_signed_torsion_has_identical_direct_and_case_table_results():
    import case_analysis
    import sector_app

    def evidence(result):
        torsion_result = result["torsion"]
        combined_result = result["combined"]
        return {
            "torsion_demand": torsion_result["t_ed"],
            "torsion_resistance": torsion_result["trd"],
            "torsion_utilisation": torsion_result["util"],
            "longitudinal_demand": torsion_result["asl_req"],
            "selected_angle": torsion_result["cot"],
            "formula_629": torsion_result["interaction"]["value"],
            "combined_transverse": combined_result["transverse"]["governing"],
            "combined_longitudinal": combined_result["longitudinal"]["util"],
        }, {
            "torsion_resistance": torsion_result["resistance_status"],
            "torsion_overall": torsion_result["assessment_status"],
            "combined_transverse": combined_result["transverse"]["ok"],
            "combined_longitudinal": combined_result["longitudinal"]["ok"],
        }

    def assert_parity(reference, candidate):
        reference_values, reference_statuses = evidence(reference)
        candidate_values, candidate_statuses = evidence(candidate)
        assert candidate_values == pytest.approx(reference_values)
        assert candidate_statuses == reference_statuses

    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 100.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
        ("selectbox", "combined_method", codes.EC2_2005.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "torsion_T", 40.0),
    )
    assert not at.exception
    positive_native = copy.deepcopy(at.session_state["results"])
    positive_entry = positive_native["plastic_cases"][0]
    assert positive_entry["actions"]["t_ed_knm"] == pytest.approx(40.0)

    latest = at.session_state["_latest_inputs"]
    record = latest["plastic_cases"].iloc[0].to_dict()
    direct_input = case_analysis.plastic_case_input(latest, record)
    for key in ("plastic_cases", "elastic_cases"):
        direct_input.pop(key, None)
    direct_input["torsion_T"] = 40.0
    positive_direct = sector_app.run_analysis(
        direct_input,
        reuse_plastic=positive_native["plastic"],
    )
    negative_direct = sector_app.run_analysis(
        dict(direct_input, torsion_T=-40.0),
        reuse_plastic=positive_native["plastic"],
    )
    assert_parity(positive_direct, negative_direct)
    assert_parity(positive_native, positive_direct)

    _set_and_click(
        at,
        "calculate",
        ("number_input", "torsion_T", -40.0),
    )
    assert not at.exception
    negative_native = at.session_state["results"]
    negative_entry = negative_native["plastic_cases"][0]
    assert negative_entry["actions"]["t_ed_knm"] == pytest.approx(-40.0)
    assert negative_native["torsion"]["t_ed"] == pytest.approx(40.0)
    assert_parity(positive_native, negative_native)


def test_app_strut_angle_responds_to_loads():
    # The user-reported defect: the auto strut angle sat at cot = 2.5 regardless of
    # VEd/MEd/NEd because it maximised the shear RESISTANCE alone. The member angle
    # now minimises the governing utilisation, so it must respond to the loads.
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()

    def run(v, mx, p):
        _set_and_click(
            at,
            "calculate",
            ("number_input", "shear_V", v),
            ("number_input", "pl_Mx", mx),
            ("number_input", "pl_P", p),
        )
        assert not at.exception
        return at.session_state["results"]["shear"]["links"]

    # Pure shear: nothing trades against the stirrups -> flattest strut (as before).
    lk = run(500.0, 0.0, 0.0)
    assert lk["res"]["cot"] == pytest.approx(2.5)
    # Bending near MRd: the chord governs, the strut steepens to relieve delta_Ftd.
    lk = run(150.0, 400.0, 0.0)
    assert lk["res"]["cot"] < 1.2
    assert lk["chord"]["util"] > 0.9
    # Moderate bending: an interior optimum where stirrup and chord utils BALANCE.
    lk = run(150.0, 100.0, 0.0)
    assert 1.2 < lk["res"]["cot"] < 2.4
    assert lk["util"] == pytest.approx(lk["chord"]["util"], rel=0.02)
    # Axial compression raises MRd -> the chord relaxes and the angle flattens again.
    cot_n0 = lk["res"]["cot"]
    lk = run(150.0, 100.0, -800.0)
    assert lk["res"]["cot"] > cot_n0


def test_app_chord_check_in_shear_payload_without_torsion():
    # The longitudinal chord check (B1) is now available for V + M without torsion
    # (torsion term = 0) and shown from the shear links payload.
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "pl_Mx", 100.0),
    )
    ch = at.session_state["results"]["shear"]["links"]["chord"]
    assert ch is not None and ch["valid"]
    assert ch["mt"] == pytest.approx(0.0)            # no torsion contribution
    assert ch["m_total"] == pytest.approx(ch["m_ed"] + ch["mv"])
    assert not ch["has_torsion"]
    # Capacity-only run (utilisation check off): no chord; the scan over the shear
    # utils alone reproduces the resistance-maximising angle (2.5 here).
    _set_and_click(
        at, "calculate", ("checkbox", "pl_check_util", False)
    )
    lk = at.session_state["results"]["shear"]["links"]
    assert lk["chord"] is None
    assert lk["res"]["cot"] == pytest.approx(2.5)
    # A zero action is not evaluated for that load case.
    _set_and_click(at, "calculate", ("number_input", "shear_V", 0.0))
    assert "shear" not in at.session_state["results"]
    _select_view(at, "Shear")
    assert any("Vx,Ed = Vy,Ed = 0" in item.value for item in at.info)


@pytest.mark.parametrize(
    ("moment", "flexural_tension_low"),
    ((100.0, True), (-100.0, False)),
)
def test_app_2023_shear_retains_both_signed_longitudinal_chords(
    moment,
    flexural_tension_low,
):
    at = _fresh().run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "pl_Mx", moment),
    )

    assert not at.exception
    links = at.session_state["results"]["shear"]["links"]
    assert links["model_2023"] is True
    candidates = [
        candidate
        for candidate in links["chord_candidates"]
        if candidate["role"] == "shear_axis"
    ]
    assert len(candidates) == 2
    assert {candidate["tension_low"] for candidate in candidates} == {True, False}
    assert {candidate["chord_formula"] for candidate in candidates} == {
        "8.51",
        "8.52",
    }
    assert all(candidate["gets_shift"] is True for candidate in candidates)
    assert all(candidate["conditional"] is True for candidate in candidates)
    by_role = {candidate["chord_role"]: candidate for candidate in candidates}
    assert by_role["flexural_tension"]["tension_low"] is flexural_tension_low
    assert by_role["flexural_tension"]["face_m_ed_signed"] > 0.0
    assert by_role["flexural_compression"]["tension_low"] is not flexural_tension_low
    assert by_role["flexural_compression"]["face_m_ed_signed"] < 0.0
    assert links["longitudinal_assessment"]["coverage_complete"] is True
    assert links["longitudinal_assessment"]["status"] in {"PASS", "FAIL"}


@pytest.mark.parametrize("requested_max", (2.4, 2.5))
def test_app_2023_chords_are_invariant_to_section_reference_translation(
    requested_max,
):
    at = _fresh().run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "pl_P", 100.0),
        ("number_input", "pl_Mx", 20.0),
        ("number_input", "shear_V", 150.0),
        ("number_input", "strut_cot_max", requested_max),
    )
    assert not at.exception
    centred_links = at.session_state["results"]["shear"]["links"]
    centred = {
        candidate["tension_low"]: candidate
        for candidate in centred_links["chord_candidates"]
        if candidate["role"] == "shear_axis"
    }

    _translate_section_y(at, 300.0)
    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_Mx", -10.0),
    )

    assert not at.exception
    shifted_links = at.session_state["results"]["shear"]["links"]
    shifted = {
        candidate["tension_low"]: candidate
        for candidate in shifted_links["chord_candidates"]
        if candidate["role"] == "shear_axis"
    }
    assert shifted_links["m_ed_2023"] == pytest.approx(20.0)
    assert shifted_links["moment_reference_shift"] == pytest.approx(30.0)
    permitted_max = 2.5 - 0.1 * 100.0 / 150.0
    for links in (centred_links, shifted_links):
        assert links["angle_applicability"]["permitted_max"] == (
            pytest.approx(permitted_max)
        )
        assert links["angle_applicability"]["requested_max"] == requested_max
    if requested_max > permitted_max:
        for links in (centred_links, shifted_links):
            assert links["res"]["valid"] is False
            assert links["angle_applicability"]["status"] == "NOT ASSESSED"
        assert centred == shifted == {}
        return
    assert centred_links["res"]["valid"] is True
    assert shifted_links["res"]["valid"] is True
    assert set(centred) == {True, False}
    assert set(shifted) == {True, False}
    assert shifted[True]["chord_role"] == "flexural_tension"
    assert shifted[False]["chord_role"] == "flexural_compression"
    for tension_low in (True, False):
        assert shifted[tension_low]["m_ed_origin_signed"] == pytest.approx(
            -10.0
        )
        assert shifted[tension_low]["moment_reference_shift"] == pytest.approx(
            30.0
        )
        assert shifted[tension_low]["face_m_ed_signed"] == pytest.approx(
            centred[tension_low]["face_m_ed_signed"]
        )
        assert shifted[tension_low]["m_rd"] == pytest.approx(
            centred[tension_low]["m_rd"],
            rel=2.0e-6,
        )
        assert shifted[tension_low]["util"] == pytest.approx(
            centred[tension_low]["util"],
            rel=2.0e-6,
        )


def test_app_2023_shear_with_torsion_retains_complete_shifted_chords():
    at = _fresh().run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("checkbox", "torsion_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "pl_Mx", 90.0),
        ("number_input", "torsion_T", 40.0),
    )

    assert not at.exception
    links = at.session_state["results"]["shear"]["links"]
    shear_faces = [
        candidate
        for candidate in links["chord_candidates"]
        if candidate["role"] == "shear_axis"
    ]
    off_axis_faces = [
        candidate
        for candidate in links["chord_candidates"]
        if candidate["role"] == "off_axis"
    ]
    assert len(shear_faces) == 2
    assert len(off_axis_faces) == 2
    assert {candidate["chord_formula"] for candidate in shear_faces} == {
        "8.51",
        "8.52",
    }
    assert all(candidate["gets_shift"] is True for candidate in shear_faces)
    assert all(candidate["ftd_t"] > 0.0 for candidate in shear_faces)
    assert links["longitudinal_assessment"]["coverage_complete"] is True
    assert links["longitudinal_assessment"]["status"] in {"PASS", "FAIL"}


@pytest.fixture(scope="module")
def native_2023_shear_contract_cases(tmp_path_factory):
    """Whole native bundles at the real C5 actions and a measured T=0 failure."""
    cases = {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path_factory.mktemp("native-c3-c5")))
        for name, moment, torque in (("failed", -200.0, 0.0), ("complete", 90.0, 40.0)):
            at = _fresh().run()
            _set(at, ("checkbox", "shear_on", True),
                 ("checkbox", "torsion_on", torque != 0.0),
                 ("selectbox", "shear_method", codes.EC2_2023.label))
            changes = [("checkbox", "shear_links", True),
                       ("number_input", "shear_V", 150.0),
                       ("number_input", "pl_Mx", moment)]
            if torque:
                changes.append(("number_input", "torsion_T", torque))
            _set_and_click(at, "calculate", *changes)
            cases[name] = _current_2023_shear_views(at)
    return cases


def _current_2023_shear_views(at):
    """Bind actual selected Shear and Overview views to a complete producer pair."""
    assert not at.exception
    inp = copy.deepcopy(at.session_state["result_input_snapshot"])
    out = copy.deepcopy(at.session_state["results"])
    assert out["plastic"]["util_valid"] is True
    assert out["plastic_cases"][0]["name"] == "PL-01"
    provided = result_presentation.provided_link_publication_assessment(
        inp, out["shear"], torsion_result=out.get("torsion"),
    )
    chord = result_presentation.provided_link_longitudinal_publication_assessment(
        inp, out["shear"], torsion_result=out.get("torsion"),
    )
    assert provided.valid is True and chord["valid"] is True
    assert chord["assessment"]["coverage_complete"] is True
    faces = [item for item in chord["candidates"] if item["role"] == "shear_axis"]
    assert len(faces) == 2
    assert {item["chord_formula"] for item in faces} == {"8.51", "8.52"}
    for face in faces:
        assert face["mv"] == pytest.approx(face["ftd_v"] * face["z"])
        assert face["m_total"] == pytest.approx(
            max(face["face_m_ed_signed"] + face["mv"], 0.0) + face["ftd_t"] * face["z"] / 2,
        )
        assert face["util"] == pytest.approx(face["m_total"] / face["m_rd"])
    _select_view(at, "Shear")
    assert not at.exception
    table = next(item.value.copy(deep=True) for item in at.dataframe
                 if "Formula" in item.value and "Signed Mface" in item.value)
    assert set(table["Formula"]) == {"(8.51)", "(8.52)"}
    visible = " ".join(str(item.value) for item in
                       (*at.warning, *at.info, *at.caption, *at.markdown))
    _select_view(at, "Results Overview")
    assert not at.exception
    overview = next(item.value.copy(deep=True) for item in at.table if "Check" in item.value)
    chord_row = overview[overview["Check"] == "Shear longitudinal chords"].iloc[0]
    assert (chord_row["Status"], chord_row["Result"]) == (
        chord["assessment"]["status"], f"{chord['assessment']['util'] * 100:.1f} %",
    )
    link_row = overview[overview["Check"] == "Shear with links"].iloc[0]
    assert link_row["Status"] == provided.status
    assert link_row["Result"].startswith(f"{provided.utilisation * 100:.1f} %")
    return {"input": inp, "results": out, "provided": provided, "chord": chord,
            "table": table, "visible": visible, "overview": overview}


def _assert_rejected_native_2023_shear(at):
    """The real family/link guard rejects a complete but noncurrent saved pair."""
    inp = at.session_state["result_input_snapshot"]
    out = at.session_state["results"]
    provided = result_presentation.provided_link_publication_assessment(
        inp, out["shear"], torsion_result=out.get("torsion"),
    )
    current, reason = result_presentation.shear_publication_input_is_current(
        inp, out["shear"], plastic_result=out.get("plastic"),
        validate_directions=False, torsion_result=out.get("torsion"),
    )
    assert current is False or provided.valid is False
    if provided.valid:
        # A family rejection can coexist with a valid resistance subcheck.
        assert current is False
        assert provided.status == "PASS" and provided.ok is True
        assert provided.utilisation == pytest.approx(
            abs(out["shear"]["v_ed"]) / provided.resistance,
        )
    _select_view(at, "Shear")
    assert not at.exception
    prefix = ("The shear check is NOT ASSESSED:" if not current
              else "The provided-link resistance is NOT ASSESSED:")
    assert any(prefix in item.value for item in at.warning)
    assert not any("Overall reinforced shear assessment: FAIL" in item.value for item in at.warning)
    assert not any("Formula" in item.value for item in at.dataframe)
    assert not any(item.label in {r"$V_{Rd,s}$", r"$V_{Rd,max}$", r"$V_{Rd}=\min$"}
                   for item in at.metric)
    _select_view(at, "Results Overview")
    assert not at.exception
    overview = next(item.value for item in at.table if "Check" in item.value)
    links = overview[overview["Check"].str.startswith("Shear")
                     & overview["Check"].str.endswith("with links")]
    assert not links.empty
    assert set(links["Status"]) == {"NOT ASSESSED"}
    assert set(links["Result"]) == {"-"}
    return current, reason


def _recalculate_after_2023_solver_fault(at, monkeypatch):
    """Discard only the AppTest cache made by the deliberately replaced solver."""
    import pickle

    failed = at.session_state["results"]
    frozen = pickle.dumps(failed)
    signature = at.session_state["result_input_snapshot"]["signature"]
    monkeypatch.undo()
    # An input signature cannot detect a test-only replacement of its solver.
    # Clear the cached result, not its saved evidence or publication predicates.
    at.session_state["results"] = {}
    _set_and_click(at, "calculate")
    assert not at.exception
    assert at.session_state["result_input_snapshot"]["signature"] == signature
    assert at.session_state["results"]["plastic_cases"][0]["reused"] is False
    assert pickle.dumps(failed) == frozen


def _exact_2023_shear_chord_component():
    """Coherent declared 215/100 and 35/100 arithmetic, without native authority."""
    faces = []
    for low in (True, False):
        face = combined.longitudinal_chord_check_2023(
            90.0, 100.0, 250.0, 0.0, 0.5,
            tension_low=low, flexural_tension_low=True,
        )
        face.update(valid=True, conditional=True, axis="x", role="shear_axis",
                    biaxial=False, off_not_evaluated=None, has_torsion=False,
                    gets_shift=True)
        faces.append(face)
    links = {"model_2023": True, "chord_candidates": faces,
             "longitudinal_shear_force": 250.0, "chord": faces[0],
             "governing_longitudinal": faces[0], "longitudinal_all_conditional": True,
             "chord_off": None, "longitudinal_fallback": None}
    links["longitudinal_assessment"] = capacity.longitudinal_chord_assessment(
        links, shear_axis="x", shear_tension_low=True, shear_live=True,
        torsion_live=False, torsion_subdivided=False,
    )
    publication = capacity.provided_link_longitudinal_publication_assessment(
        {"axis": "x", "tension_low": True, "links": links},
    )
    assert publication["valid"] is True
    assert publication["assessment"]["coverage_complete"] is True
    assert publication["assessment"]["status"] == "FAIL"
    assert [(face["m_total"], face["util"], face["status"]) for face in faces] == [
        (215.0, 2.15, "FAIL"), (35.0, 0.35, "PASS"),
    ]
    return publication


def _retained_2023_chord_row(inp, assessment):
    row = result_presentation._summary_row(
        "Shear longitudinal chords", "plastic", assessment["status"],
        "-" if assessment["util"] is None else f"{assessment['util'] * 100:.1f} %",
        "<= 100 %", assessment["util"], "Shear",
        result_presentation.result_reason(assessment["reason"], "shear"),
        inp, overview_key="shear:longitudinal_chords", overview_parent="shear",
    )
    # This row belongs to the declared formatting unit, not a native case source.
    row["source"] = "Retained shear chord calculation"
    return row


def _retained_2023_chord_view(inp, out, assessment, publication=None):
    """Actual formatting leaves and declared Overview rows; no native claim."""
    from streamlit.testing.v1 import AppTest

    leaf = AppTest.from_string(
        "import copy\nimport streamlit as st\nimport sector_app\nimport result_presentation\n"
        "from unittest.mock import patch\n"
        "inp, out, assessment, publication, row = st.session_state['declared_unit']\n"
        "surface = st.radio('Unit surface', ['Chord', 'Overview'], key='unit_surface')\n"
        "if surface == 'Chord':\n"
        "    sector_app._render_shear_longitudinal_assessment(assessment)\n"
        "    if publication is not None:\n"
        "        sector_app._render_shear_2023_chord_faces(publication)\n"
        "else:\n"
        "    original = result_presentation.multi_case_summary_rows\n"
        "    with patch.object(result_presentation, 'multi_case_summary_rows', "
        "side_effect=lambda *args, **kwargs: [copy.deepcopy(row)]):\n"
        "        sector_app.results_overview_view(inp, out)\n"
        "    assert result_presentation.multi_case_summary_rows is original\n",
        default_timeout=120,
    )
    leaf.session_state["declared_unit"] = copy.deepcopy((
        inp, out, assessment, publication, _retained_2023_chord_row(inp, assessment),
    ))
    leaf.run()
    assert not leaf.exception
    return leaf


def _retained_2023_chord_pdf(inp, out, assessment, publication, profile, path):
    import pickle
    from test_report import _declared_member_overview_unit, _finish_retained_unit_pdf

    before = pickle.dumps((inp, out, assessment, publication))
    row = _retained_2023_chord_row(inp, assessment)
    buffer, builder = _declared_member_overview_unit(
        inp, out, [row], profile, "Retained separate shear chord formatting",
    )
    if publication is None:
        builder._shear_2023_missing_chords(assessment)
    elif profile in {"Standard", "Audit"}:
        builder._shear_2023_chord_faces(publication, assessment, assessment["status"])
    pdf = _finish_retained_unit_pdf(buffer, builder)
    assert pickle.dumps((inp, out, assessment, publication)) == before
    path.write_bytes(pdf)
    return _native_2023_pdf_text(pdf)


def _native_2023_pdf_text(pdf):
    import io
    import pypdf

    return " ".join(" ".join((page.extract_text() or "").split())
                    for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def _native_2023_shear_pdf(inp, out, profile, path, *, current):
    import pickle
    import re
    import sector_report

    inp, out = copy.deepcopy((inp, out))
    out["worked_example_selection"] = result_presentation.worked_example_selection(inp, out)
    before = pickle.dumps((inp, out))
    provided = result_presentation.provided_link_publication_assessment(
        inp, out["shear"], torsion_result=out.get("torsion"),
    )
    family_current, _family_reason = result_presentation.shear_publication_input_is_current(
        inp, out["shear"], plastic_result=out.get("plastic"),
        validate_directions=False, torsion_result=out.get("torsion"),
    )
    if current:
        assert family_current is True and provided.valid is True
    else:
        assert family_current is False or provided.valid is False
        if provided.valid:
            assert provided.status == "PASS" and provided.ok is True
            assert provided.utilisation == pytest.approx(
                abs(out["shear"]["v_ed"]) / provided.resistance,
            )
    rows = [row for row in result_presentation.multi_case_summary_rows(inp, out)
            if row["check"].startswith("Shear")]
    assert rows
    pdf = sector_report.build_report({}, inp, out, figures=False, profile=profile)
    path.write_bytes(pdf)
    text = _native_2023_pdf_text(pdf)
    assert pickle.dumps((inp, out)) == before
    selected = result_presentation.governing_summary_rows(rows)
    compared = result_presentation.governing_result_rows(selected)
    information = result_presentation.governing_information_rows(selected)
    for row in (*compared, *information):
        def token(value):
            return re.escape(str(value)).replace(r"\ ", r"\s+").replace(r"\-", r"-\s*")
        separator = r"\s+\|\s+" if row in information else r"\s+"
        pattern = separator.join(token(row[key]) for key in ("check", "case", "status", "result"))
        matched = re.search(pattern, text)
        assert matched is not None, (row["check"], row["case"], row["status"])
    link_rows = [row for row in rows if row["check"].endswith("with links")]
    assert link_rows
    if not current:
        assert all(row["status"] == "NOT ASSESSED" and row["result"] == "-"
                   and row["util"] is None for row in link_rows)
        assert "215.0 %" not in text
    else:
        chords = [row for row in rows if row["check"] == "Shear longitudinal chords"]
        assert len(chords) == 1
        chord = result_presentation.provided_link_longitudinal_publication_assessment(
            inp, out["shear"], torsion_result=out.get("torsion"),
        )
        assert chord["valid"] is True
        assert chords[0]["status"] == chord["assessment"]["status"]
        if profile in {"Standard", "Audit"}:
            assert "Required 2023 longitudinal chord faces" in text
            assert "(8.51)" in text and "(8.52)" in text
    return text


def _install_exact_2023_chord_review_fixture(monkeypatch):
    original = combined.longitudinal_chord_check_2023

    def controlled_review_fixture(
        _m_ed_signed,
        _m_rd,
        _n_vd,
        _ftd_t,
        _z,
        *,
        tension_low,
        flexural_tension_low,
        n_ed=0.0,
    ):
        return original(
            90.0,
            100.0,
            250.0,
            0.0,
            0.5,
            tension_low=tension_low,
            flexural_tension_low=flexural_tension_low,
            n_ed=n_ed,
        )

    monkeypatch.setattr(
        combined,
        "longitudinal_chord_check_2023",
        controlled_review_fixture,
    )


def _app_with_failed_2023_chord(monkeypatch):
    _install_exact_2023_chord_review_fixture(monkeypatch)
    at = _fresh().run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "pl_Mx", 90.0),
    )
    return at


def test_app_2023_failed_required_chord_propagates_to_shear_and_overview(
    monkeypatch, native_2023_shear_contract_cases,
):
    at = _app_with_failed_2023_chord(monkeypatch)
    assert not at.exception
    links = at.session_state["results"]["shear"]["links"]
    assessment = links["longitudinal_assessment"]
    assert at.session_state["results"]["shear"]["assessment_status"] == "FAIL"
    assert at.session_state["results"]["shear"]["assessment_ok"] is False
    assert assessment["status"] == "FAIL"
    assert assessment["ok"] is False
    assert assessment["coverage_complete"] is True
    assert assessment["util"] == pytest.approx(2.15)
    assert assessment["governing"]["m_total"] == pytest.approx(215.0)
    inp = copy.deepcopy(at.session_state["result_input_snapshot"])
    out = copy.deepcopy(at.session_state["results"])
    _assert_rejected_native_2023_shear(at)

    # The exact overridden numbers remain a separate coherent formatting unit.
    publication = _exact_2023_shear_chord_component()
    leaf = _retained_2023_chord_view(inp, out, publication["assessment"], publication)
    visible = " ".join(str(item.value) for item in
                       (*leaf.warning, *leaf.caption, *leaf.markdown))
    assert "Overall reinforced shear assessment: FAIL" in visible
    assert "required longitudinal chords exceed" in visible
    face_table = next(frame.value for frame in leaf.dataframe
                      if "Formula" in frame.value and "Signed Mface" in frame.value)
    assert set(face_table["Formula"]) == {"(8.51)", "(8.52)"}
    assert set(face_table["Status"]) == {"FAIL", "PASS"}
    leaf.radio(key="unit_surface").set_value("Overview").run()
    assert not leaf.exception
    overview = leaf.table[0].value
    row = overview.loc[overview["Check"] == "Shear longitudinal chords"].iloc[0]
    assert row["Status"] == "FAIL"
    assert row["Result"] == "215.0 %"

    native = native_2023_shear_contract_cases["failed"]
    assert native["chord"]["assessment"]["util"] == pytest.approx(1.695976504439608)
    assert native["chord"]["assessment"]["status"] == "FAIL"
    assert "Overall reinforced shear assessment: FAIL" in native["visible"]
    assert "required longitudinal chords exceed" in native["visible"]
    assert set(native["table"]["Status"]) == {"FAIL", "PASS"}
    native_row = native["overview"].loc[
        native["overview"]["Check"] == "Shear longitudinal chords"
    ].iloc[0]
    assert (native_row["Status"], native_row["Result"]) == ("FAIL", "169.6 %")
    # The old aggregate 215% shear-resistance claim is replaced by its own
    # independent current |V|/VRd comparison, while the chord remains failed.
    overall_row = native["overview"].loc[
        native["overview"]["Check"] == "Shear with links"
    ].iloc[0]
    assert native["provided"].utilisation == pytest.approx(0.8160181797595336)
    assert (overall_row["Status"], overall_row["Result"]) == ("PASS", "81.6 %")
    _recalculate_after_2023_solver_fault(at, monkeypatch)
    _current_2023_shear_views(at)


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_failed_2023_chord_reaches_every_report_profile(
    monkeypatch, profile, native_2023_shear_contract_cases, tmp_path,
):
    at = _app_with_failed_2023_chord(monkeypatch)
    assert not at.exception
    inputs = copy.deepcopy(at.session_state["result_input_snapshot"])
    results = copy.deepcopy(at.session_state["results"])
    _native_2023_shear_pdf(
        inputs, results, profile, tmp_path / "rejected-overridden-shear.pdf", current=False,
    )
    publication = _exact_2023_shear_chord_component()
    text = _retained_2023_chord_pdf(
        inputs, results, publication["assessment"], publication, profile,
        tmp_path / "retained-exact-shear-chords.pdf",
    )
    assert "Shear longitudinal chords" in text
    assert "215.0 %" in text
    assert "FAIL" in text
    assert "required longitudinal chords exceed" in text
    assert "SHEAR-LONGITUDINAL" not in text
    if profile in {"Standard", "Audit"}:
        assert "Required 2023 longitudinal chord faces" in text
        assert "(8.51)" in text and "(8.52)" in text
        assert "215.0 kNm" in text

    # Native reconstruction must use the real kernel, not the retained override.
    monkeypatch.undo()
    native = native_2023_shear_contract_cases["failed"]
    native_text = _native_2023_shear_pdf(
        native["input"], native["results"], profile,
        tmp_path / "native-failed-shear.pdf", current=True,
    )
    assert "169.6 %" in native_text and "required longitudinal chords exceed" in native_text
    assert "SHEAR-LONGITUDINAL" not in native_text
    if profile in {"Standard", "Audit"}:
        assert "263.2 kNm" in native_text
    _recalculate_after_2023_solver_fault(at, monkeypatch)
    _current_2023_shear_views(at)


def _app_with_incomplete_2023_chord(monkeypatch):
    original = capacity.shear_face_mrd

    def one_face_unavailable(
        inp,
        axis,
        tension_low,
        m_off=0.0,
        **kwargs,
    ):
        if tension_low is False:
            return 0.0, False
        return original(inp, axis, tension_low, m_off=m_off, **kwargs)

    monkeypatch.setattr(capacity, "shear_face_mrd", one_face_unavailable)
    at = _fresh().run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "pl_Mx", 90.0),
    )
    return at


def test_app_2023_incomplete_chord_coverage_is_not_assessed(monkeypatch):
    at = _app_with_incomplete_2023_chord(monkeypatch)
    assert not at.exception
    shear = at.session_state["results"]["shear"]
    assessment = shear["links"]["longitudinal_assessment"]
    assert len(shear["links"]["chord_candidates"]) == 1
    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["coverage_complete"] is False
    assert shear["assessment_status"] == "NOT ASSESSED"
    assert shear["assessment_ok"] is None

    _select_view(at, "Shear")
    visible = " ".join(
        str(item.value) for item in (*at.warning, *at.caption, *at.markdown)
    )
    assert "Overall reinforced shear assessment: NOT ASSESSED" in visible
    assert "Complete both required longitudinal chord checks" in visible

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    # Transverse link resistance and required longitudinal coverage are
    # separate checks; an unavailable chord must not erase a valid link result.
    inp = at.session_state["result_input_snapshot"]
    provided = result_presentation.provided_link_publication_assessment(inp, shear)
    assert provided.valid is True and provided.status == "PASS"
    assert provided.utilisation == pytest.approx(shear["v_ed"] / shear["links"]["res"]["vrd"])
    link_row = overview.loc[overview["Check"] == "Shear with links"].iloc[0]
    assert link_row["Status"] == "PASS"
    assert link_row["Result"].startswith(f"{provided.utilisation * 100:.1f} %")
    chord_row = overview.loc[overview["Check"] == "Shear longitudinal chords"].iloc[0]
    assert chord_row["Status"] == "NOT ASSESSED"
    # The one known face remains a diagnostic value; it is not a coverage PASS.
    assert assessment["coverage_complete"] is False and assessment["ok"] is None
    assert assessment["util"] == pytest.approx(
        shear["links"]["chord_candidates"][0]["m_total"]
        / shear["links"]["chord_candidates"][0]["m_rd"],
    )
    assert chord_row["Result"] == f"{assessment['util'] * 100:.1f} %"


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_incomplete_2023_chord_is_not_assessed_in_every_report_profile(
    monkeypatch,
    profile,
):
    import io

    import pypdf

    import sector_report

    at = _app_with_incomplete_2023_chord(monkeypatch)
    assert not at.exception
    inputs = at.session_state["_latest_inputs"]
    results = at.session_state["results"]
    results["worked_example_selection"] = (
        result_presentation.worked_example_selection(inputs, results)
    )
    pdf = sector_report.build_report(
        {}, inputs, results, figures=False, profile=profile
    )
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = " ".join(
        " ".join((page.extract_text() or "").split())
        for page in reader.pages
    )

    assert "Shear longitudinal chords" in text
    assert "NOT ASSESSED" in text
    assert "Complete both required longitudinal chord checks" in text
    assert "SHEAR-LONGITUDINAL" not in text
    if profile in {"Standard", "Audit"}:
        assert "Required 2023 longitudinal chord faces" in text
        assert "(8.51)" in text
        assert "Flexural tension" in text


def _app_with_no_2023_chord_candidate(monkeypatch):
    monkeypatch.setattr(
        capacity,
        "shear_face_mrd",
        lambda *args, **kwargs: (0.0, False),
    )
    at = _fresh().run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
    )
    _set(
        at,
        ("selectbox", "shear_method", codes.EC2_2023.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "pl_Mx", 90.0),
        ("number_input", "torsion_T", 40.0),
    )
    return at


def test_app_2023_zero_chord_candidates_remain_visibly_not_assessed(
    monkeypatch, native_2023_shear_contract_cases,
):
    positive = native_2023_shear_contract_cases["complete"]
    assert positive["chord"]["assessment"]["coverage_complete"] is True
    assert len(positive["chord"]["candidates"]) == 4
    assert all(item["ftd_t"] > 0 for item in positive["chord"]["candidates"])

    at = _app_with_no_2023_chord_candidate(monkeypatch)
    assert not at.exception
    results = at.session_state["results"]
    links = results["shear"]["links"]
    assert links["model_2023"] is True
    assert links["chord"] is None
    assert links["chord_candidates"] == []
    assert links["longitudinal_assessment"]["status"] == "NOT ASSESSED"
    canonical = capacity.longitudinal_chord_assessment(
        links, shear_axis=results["shear"]["axis"],
        shear_tension_low=results["shear"]["tension_low"], shear_live=True,
        torsion_live=True, torsion_subdivided=False,
    )
    assert canonical == links["longitudinal_assessment"]
    assert canonical["util"] is None and canonical["coverage_complete"] is False
    inputs = copy.deepcopy(at.session_state["result_input_snapshot"])
    failed = copy.deepcopy(results)
    current, _reason = _assert_rejected_native_2023_shear(at)
    assert current is False

    leaf = _retained_2023_chord_view(inputs, failed, canonical)
    visible = " ".join(str(item.value) for item in
                       (*leaf.warning, *leaf.info, *leaf.caption, *leaf.markdown))
    assert "Complete both required longitudinal chord checks" in visible
    leaf.radio(key="unit_surface").set_value("Overview").run()
    assert not leaf.exception
    overview = leaf.table[0].value
    row = overview.loc[overview["Check"] == "Shear longitudinal chords"].iloc[0]
    assert row["Status"] == "NOT ASSESSED"
    assert row["Result"] == "-"

    _recalculate_after_2023_solver_fault(at, monkeypatch)
    recovered = _current_2023_shear_views(at)
    assert recovered["chord"]["assessment"]["coverage_complete"] is True
    assert len(recovered["chord"]["candidates"]) == 4
    assert failed["shear"]["links"]["chord_candidates"] == []


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_zero_2023_chord_candidates_publish_assessment_without_legacy_copy(
    monkeypatch, profile, native_2023_shear_contract_cases, tmp_path,
):
    positive = native_2023_shear_contract_cases["complete"]
    assert positive["chord"]["assessment"]["coverage_complete"] is True
    assert len(positive["chord"]["candidates"]) == 4
    at = _app_with_no_2023_chord_candidate(monkeypatch)
    assert not at.exception
    inputs = copy.deepcopy(at.session_state["result_input_snapshot"])
    results = copy.deepcopy(at.session_state["results"])
    links = results["shear"]["links"]
    assert links["model_2023"] is True and links["chord"] is None
    assert links["chord_candidates"] == []
    canonical = capacity.longitudinal_chord_assessment(
        links, shear_axis=results["shear"]["axis"],
        shear_tension_low=results["shear"]["tension_low"], shear_live=True,
        torsion_live=True, torsion_subdivided=False,
    )
    assert canonical == links["longitudinal_assessment"]
    assert canonical["status"] == "NOT ASSESSED" and canonical["util"] is None
    native_text = _native_2023_shear_pdf(
        inputs, results, profile, tmp_path / "rejected-zero-face-shear.pdf", current=False,
    )
    text = _retained_2023_chord_pdf(
        inputs, results, canonical, None, profile, tmp_path / "retained-missing-shear-chords.pdf",
    )
    assert "Shear longitudinal chords" in text
    assert "NOT ASSESSED" in text
    assert "Complete both required longitudinal chord checks" in text
    assert "SHEAR-LONGITUDINAL" not in text
    if profile in {"Standard", "Audit"}:
        assert "Required 2023 longitudinal chord faces" in text
        assert "Enable shear links for the full utilisation check" not in text
        assert "both beyond the bending steel" not in text
    for forbidden in ("SHEAR-LONGITUDINAL", "Enable shear links for the full utilisation check",
                      "both beyond the bending steel"):
        assert forbidden not in native_text

    _recalculate_after_2023_solver_fault(at, monkeypatch)
    recovered = _current_2023_shear_views(at)
    _native_2023_shear_pdf(
        recovered["input"], recovered["results"], profile,
        tmp_path / "recovered-native-shear.pdf", current=True,
    )
    assert results["shear"]["links"]["chord_candidates"] == []


def test_mvt_view_zero_2023_chord_candidates_uses_retained_assessment():
    at = _fresh().run()
    _enable_all(at)
    assert not at.exception
    pristine = _assert_current_native_mvt_views(at, longitudinal=True)

    retained = copy.deepcopy(at.session_state["results"])
    combined_result = retained["combined"]
    combined_result.pop("longitudinal", None)
    combined_result.pop("longitudinal_candidates", None)
    combined_result.pop("governing_longitudinal", None)
    combined_result["longitudinal_model_2023"] = True
    combined_result["longitudinal_assessment"] = {
        "status": "NOT ASSESSED",
        "ok": None,
        "util": None,
        "reason": "required_longitudinal_chord_coverage_incomplete",
        "coverage_complete": False,
        "governing": None,
    }
    at.session_state["results"] = retained

    _select_view(at, "M-V-T Combined")

    assert not at.exception
    visible = " ".join(
        str(item.value)
        for family in (at.markdown, at.warning, at.info, at.caption)
        for item in family
    )
    scope_note = result_presentation.combined_publication_scope_note(combined_result)
    assert "2023 Combined bending, shear and torsion is outside" in scope_note
    assert scope_note in visible
    assert "NOT ASSESSED" in visible
    # Preserve the retained missing-face diagnostic separately from the
    # unsupported Combined publication route.
    assert "Complete both required longitudinal chord checks" in (
        result_presentation.combined_longitudinal_chord_assessment_note(combined_result)
    )
    assessment = capacity.combined_longitudinal_assessment(combined_result)
    assert assessment["chord_status"] == "NOT ASSESSED"
    assert assessment["chord_util"] is None
    assert combined_result["longitudinal_assessment"]["coverage_complete"] is False
    assert not combined_result.get("longitudinal_candidates")
    assert "Enable links for the full utilisation check" not in visible
    assert "(6.18)" not in visible
    assert r"\Delta Ftd" not in visible
    assert "\u0394Ftd" not in visible
    _assert_rejected_native_mvt_views(at)
    _restore_current_native_mvt_views(at, pristine, longitudinal=True)


def test_failed_2023_chord_propagates_to_retained_mvt_component_and_overview():
    assessment = {
        "status": "FAIL",
        "ok": False,
        "util": 2.15,
        "reason": "required_longitudinal_chord_failed",
        "coverage_complete": True,
        "governing": {"valid": True, "util": 2.15},
    }
    combined_result = {
        "valid": True,
        "method": codes.EC2_2005_DKNA.label,
        "dkna_valid": True,
        "dkna_sum": 0.60,
        "dkna_limit_satisfied": True,
        "dkna_status": "PASS",
        "dkna_ok": True,
        "torsion_assessment_status": "PASS",
        "torsion_longitudinal_assessment": {
            "status": "NOT ASSESSED",
            "demand_ratio": 0.40,
            "reason": "longitudinal_torsion_reinforcement_not_verified",
        },
        "longitudinal_assessment": assessment,
        "transverse": {
            "valid": True,
            "u_crush": 0.40,
            "u_stirrup": 0.50,
            "cot": 1.5,
            "shear_fraction": 0.25,
            "torsion_fraction": 0.25,
        },
    }

    assert result_presentation.combined_dkna_status(combined_result) == "FAIL"
    note = result_presentation.combined_governing_assessment_note(
        combined_result
    )
    assert "required longitudinal chords exceed" in note
    assert "not an overall M-V-T verdict" in note
    components = {
        item["key"]: item
        for item in result_presentation.combined_physical_components(
            combined_result
        )
    }
    # A bare retained FAIL/2.15 claim has no candidate operands or owners.
    # Preserve its legacy arithmetic/diagnostic contract without admitting it
    # as canonical physical-component or native Overview authority.
    assert assessment["util"] == pytest.approx(215.0 / 100.0)
    assert "required longitudinal chords exceed" in (
        result_presentation.combined_longitudinal_chord_assessment_note(combined_result)
    )
    assert "distributed around every torsion-tube side" in result_presentation.result_reason(
        combined_result["torsion_longitudinal_assessment"]["reason"], "torsion",
    )
    canonical = capacity.combined_longitudinal_assessment(combined_result)
    assert canonical["status"] == canonical["chord_status"] == "NOT ASSESSED"
    assert canonical["util"] is None and canonical["chord_util"] is None
    assert components["longitudinal"]["status"] == "NOT ASSESSED"
    assert components["longitudinal"]["util"] is None
    assert "Recalculate the combined longitudinal reinforcement assessment" in (
        components["longitudinal"]["note"]
    )

    rows = result_presentation.result_summary_rows(
        {"combined_on": True},
        {"combined": combined_result},
    )
    combined_rows = [row for row in rows if row["check"].startswith("Combined ")]
    assert combined_rows
    assert {row["status"] for row in combined_rows} == {"NOT ASSESSED"}
    assert {row["result"] for row in combined_rows} == {"-"}
    assert all(row["util"] is None for row in combined_rows)


def _retained_longitudinal_component_row(leaf, combined_result):
    """Bind retained row assertions to the canonical assessment and real formatter.

    A manufactured component never qualifies a native Overview row. The same
    test separately requires explicit unavailable rows from the ordinary view.
    """
    component = next(item for item in result_presentation.combined_physical_components(
        combined_result,
    ) if item["key"] == "longitudinal")
    metric = next(item for item in leaf.metric if item.label == "Longitudinal reinforcement")
    status = component["status"]
    if status in {"PASS", "FAIL"}:
        assert metric.delta == status
    else:
        assert status == "NOT ASSESSED"
        assert metric.delta in {None, ""}
        assert any(item.value == "NOT ASSESSED" for item in leaf.caption)
    return {"Status": status, "Result": str(metric.value)}


def _pub_h01_formula_628_assessment(ratio):
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
    elif sufficient:
        status, ok, reason = (
            "NOT ASSESSED",
            None,
            "longitudinal_torsion_reinforcement_not_verified",
        )
    else:
        status, ok, reason = (
            "FAIL",
            False,
            "longitudinal_torsion_reinforcement_insufficient",
        )
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


@pytest.mark.parametrize("parent_state", ("stale_mapping", "non_mapping"))
def test_pub_h01_exact_failure_is_identical_in_mvt_view_and_overview(
    parent_state,
):
    at = _fresh()
    at.run()
    _enable_all(at)
    native_pristine = _assert_current_native_mvt_views(at, longitudinal=True)
    assert not at.exception

    retained = copy.deepcopy(at.session_state["results"])
    combined_result = retained["combined"]
    direct = {
        **combined_result["longitudinal"],
        "valid": True,
        "status": "FAIL",
        "ok": False,
        "axis": "x",
        "tension_low": True,
        "conditional": True,
        "biaxial": False,
        "off_util": 0.0,
        "off_not_evaluated": None,
        "m_ed": 80.0,
        "mv": 4.213620,
        "mt": 39.711696,
        "m_total": 123.925316,
        "m_rd": 100.0,
        "ftd_v": 17.34,
        "ftd_t": 326.8452380952381,
        "z": 0.243,
        "util": 1.2392531643,
        "capped": False,
        "cap_shear_force": True,
        "mv_uncapped": 4.213620,
        "shear_headroom": 20.0,
        "shear_term_selection": "uncapped",
    }
    for legacy_only_key in (
        "role",
        "has_torsion",
        "gets_shift",
        "chord_formula",
        "chord_role",
        "flexural_tension_low",
        "face_m_ed_signed",
    ):
        direct.pop(legacy_only_key, None)
    combined_result["longitudinal"] = direct
    for key in (
        "governing_longitudinal",
        "longitudinal_assessment",
        "longitudinal_candidates",
        "longitudinal_fallback",
        "overall_longitudinal_assessment",
    ):
        combined_result.pop(key, None)
    combined_result["longitudinal_all_conditional"] = True
    stale_governing = {
        **direct,
        "status": "PASS",
        "ok": True,
        "m_rd": direct["m_total"] / 0.80,
        "util": 0.80,
    }
    combined_result["longitudinal_assessment"] = (
        {
            "status": "NOT ASSESSED",
            "ok": None,
            "util": 0.80,
            "reason": "required_longitudinal_chord_coverage_incomplete",
            "coverage_complete": False,
            "governing": stale_governing,
        }
        if parent_state == "stale_mapping"
        else []
    )
    combined_result["torsion_longitudinal_assessment"] = (
        _pub_h01_formula_628_assessment(0.50)
    )
    stale_overall = dict(
        capacity.combined_longitudinal_assessment(combined_result)
    )
    assert stale_overall["status"] == "FAIL"
    stale_overall.update(
        status="NOT ASSESSED",
        ok=None,
        util=None,
        reason="required_longitudinal_chord_coverage_incomplete",
        coverage_complete=False,
        governing_source=None,
        governing_mechanism=None,
        governing=None,
    )
    combined_result["overall_longitudinal_assessment"] = stale_overall
    at.session_state["results"] = retained

    leaf = _base_en_component_view(combined_result)
    assert not leaf.exception
    physical = next(
        metric for metric in leaf.metric
        if metric.label == "Longitudinal reinforcement"
    )
    detailed = next(
        metric for metric in leaf.metric
        if metric.label == "Chord utilisation"
    )
    assert str(physical.value) == "123.9 %"
    assert str(physical.delta) == "FAIL"
    assert str(detailed.value) == "123.9 %"
    assert str(detailed.delta) == "FAIL"

    row = _retained_longitudinal_component_row(leaf, combined_result)
    _assert_rejected_native_mvt_views(at)
    assert row["Status"] == "FAIL"
    assert row["Result"] == "123.9 %"
    assert str(row["Result"]).casefold() not in {"inf", "infinite", "-"}
    _restore_current_native_mvt_views(at, native_pristine, longitudinal=True)


def test_pub_h01_chord_and_formula_628_overall_are_published_separately():
    at = _fresh()
    at.run()
    _enable_all(at)
    native_pristine = _assert_current_native_mvt_views(at, longitudinal=True)
    assert not at.exception

    retained = copy.deepcopy(at.session_state["results"])
    combined_result = retained["combined"]
    combined_result["method"] = codes.EC2_2005.label
    chord = combined_result["longitudinal"]
    chord.update(
        status="PASS",
        ok=True,
        m_rd=float(chord["m_total"]) / 0.50,
        util=0.50,
    )
    chord.update(
        cap_shear_force=True,
        mv_uncapped=float(chord["ftd_v"]) * float(chord["z"]),
        shear_headroom=max(float(chord["m_rd"]) - float(chord["m_ed"]), 0.0),
        shear_term_selection="uncapped",
        capped=False,
    )
    for legacy_only_key in (
        "role",
        "has_torsion",
        "gets_shift",
        "chord_formula",
        "chord_role",
        "flexural_tension_low",
        "face_m_ed_signed",
    ):
        chord.pop(legacy_only_key, None)
    for key in (
        "governing_longitudinal",
        "longitudinal_assessment",
        "longitudinal_candidates",
        "longitudinal_fallback",
        "overall_longitudinal_assessment",
    ):
        combined_result.pop(key, None)
    combined_result.pop("longitudinal_model_2023", None)
    combined_result["longitudinal_all_conditional"] = True
    formula_628 = _pub_h01_formula_628_assessment(2.0)
    combined_result["asl_torsion"] = formula_628["required_asl_mm2"]
    combined_result["torsion_longitudinal_assessment"] = formula_628
    combined_result["overall_longitudinal_assessment"] = (
        capacity.combined_longitudinal_assessment(combined_result)
    )
    at.session_state["results"] = retained

    leaf = _base_en_component_view(combined_result)
    assert not leaf.exception
    chord_metric = next(
        metric for metric in leaf.metric if metric.label == "Chord utilisation"
    )
    overall_metric = next(
        metric
        for metric in leaf.metric
        if metric.label == "Longitudinal reinforcement"
    )
    assert str(chord_metric.value) == "50.0 %"
    assert str(chord_metric.delta) == "PASS"
    assert str(overall_metric.value) == "200.0 %"
    assert str(overall_metric.delta) == "FAIL"
    visible = " ".join(str(item.value) for item in leaf.caption)
    assert (
        "Overall longitudinal reinforcement assessment: 200.0 % (FAIL)" in visible
    )
    assert "governing check: Formula (6.28) longitudinal torsion reinforcement" in visible
    _assert_rejected_native_mvt_views(at)
    _restore_current_native_mvt_views(at, native_pristine, longitudinal=True)


def test_pub_h01_stale_2023_single_face_pass_fails_closed_in_native_views():
    at = _fresh()
    at.run()
    _enable_all(at)
    native_pristine = _assert_current_native_mvt_views(at, longitudinal=True)
    assert not at.exception

    retained = copy.deepcopy(at.session_state["results"])
    combined_result = retained["combined"]
    combined_result["method"] = codes.EC2_2005.label
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
    combined_result.update(
        longitudinal_model_2023=True,
        longitudinal=tension,
        longitudinal_candidates=[tension, compression],
        governing_longitudinal=tension,
        longitudinal_assessment={
            "status": "PASS",
            "ok": True,
            "util": 0.50,
            "reason": "required_longitudinal_chords_satisfied",
            "coverage_complete": True,
            "governing": tension,
        },
        torsion_longitudinal_assessment={
            "status": "PASS",
            "ok": True,
            "reason": "no_longitudinal_torsion_demand",
            "demand_ratio": 0.0,
        },
    )
    combined_result["overall_longitudinal_assessment"] = (
        capacity.combined_longitudinal_assessment(combined_result)
    )
    del combined_result["longitudinal_candidates"][1]
    at.session_state["results"] = retained

    leaf = _base_en_component_view(combined_result)
    assert not leaf.exception
    overall_metric = next(
        metric
        for metric in leaf.metric
        if metric.label == "Longitudinal reinforcement"
    )
    assert str(overall_metric.value) == "-"
    assert str(overall_metric.delta) == ""
    assert any(str(caption.value) == "NOT ASSESSED" for caption in leaf.caption)
    assert all(
        not (
            metric.label == "Chord utilisation"
            and str(metric.delta) == "PASS"
        )
        for metric in leaf.metric
    )

    row = _retained_longitudinal_component_row(leaf, combined_result)
    _assert_rejected_native_mvt_views(at)
    assert row["Status"] == "NOT ASSESSED"
    assert row["Result"] == "-"
    _restore_current_native_mvt_views(at, native_pristine, longitudinal=True)


def test_pub_h01_stale_operands_never_publish_native_longitudinal_pass():
    at = _fresh()
    at.run()
    _enable_all(at)
    native_pristine = _assert_current_native_mvt_views(at, longitudinal=True)
    assert not at.exception
    base_results = copy.deepcopy(at.session_state["results"])

    for attack in (
        "face_moment",
        "headroom_cap",
        "formula_628",
        "owner_liveness",
        "subtube_liveness",
        "array_status",
        "tube_overflow",
        "face_overflow",
    ):
        retained = copy.deepcopy(base_results)
        combined_result = retained["combined"]
        for key in (
            "governing_longitudinal",
            "longitudinal_assessment",
            "longitudinal_candidates",
            "longitudinal_fallback",
            "overall_longitudinal_assessment",
        ):
            combined_result.pop(key, None)

        if attack in {
            "formula_628",
            "owner_liveness",
            "subtube_liveness",
            "array_status",
            "tube_overflow",
        }:
            direct = {
                "valid": True,
                "status": "PASS",
                "ok": True,
                "axis": "x",
                "tension_low": True,
                "conditional": True,
                "biaxial": False,
                "off_util": 0.0,
                "off_not_evaluated": None,
                "m_ed": 40.0,
                "mv": 10.0,
                "mt": 0.0,
                "m_total": 50.0,
                "m_rd": 100.0,
                "ftd_v": 40.0,
                "ftd_t": 0.0,
                "z": 0.25,
                "util": 0.50,
                "capped": False,
                "cap_shear_force": True,
                "mv_uncapped": 10.0,
                "shear_headroom": 60.0,
                "shear_term_selection": "uncapped",
            }
            formula_628 = _pub_h01_formula_628_assessment(0.0)
            if attack in {"owner_liveness", "subtube_liveness"}:
                direct.update(
                    ftd_t=317.693568,
                    mt=39.711696,
                    m_total=89.711696,
                    util=0.89711696,
                )
                combined_result.update(
                    t_ed=0.0 if attack == "owner_liveness" else 40.0,
                    asl_torsion=0.0 if attack == "owner_liveness" else 500.0,
                    torsion_subdivided=attack == "subtube_liveness",
                    torsion_subtubes=(
                        (
                            {"asl_req": 200.0, "t_ed": 40.0},
                            {"asl_req": 300.0, "t_ed": 0.0},
                        )
                        if attack == "subtube_liveness"
                        else None
                    ),
                )
                if attack == "subtube_liveness":
                    formula_628 = _pub_h01_formula_628_assessment(0.50)
                    formula_628["required_by_tube_mm2"] = (200.0, 300.0)
            elif attack == "array_status":
                formula_628["status"] = np.array(["PASS"])
                combined_result.update(
                    t_ed=0.0,
                    asl_torsion=0.0,
                    torsion_subdivided=False,
                    torsion_subtubes=None,
                )
            elif attack == "tube_overflow":
                formula_628["required_by_tube_mm2"] = (10**1000,)
                combined_result.update(
                    t_ed=0.0,
                    asl_torsion=0.0,
                    torsion_subdivided=True,
                    torsion_subtubes=({"asl_req": 0.0, "t_ed": 0.0},),
                )
            else:
                assert combined_result["t_ed"] > 0.0
                assert combined_result["asl_torsion"] > 0.0
            combined_result.update(
                longitudinal_model_2023=False,
                longitudinal=direct,
                longitudinal_all_conditional=True,
                torsion_longitudinal_assessment=formula_628,
            )
        else:
            ftd_v = 300.0 if attack == "headroom_cap" else 40.0
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
                "m_rd": 100.0,
                "ftd_v": ftd_v,
                "ftd_t": 0.0,
                "z": 0.25,
                "mt": 0.0,
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
                "face_m_ed_signed": (
                    10**1000
                    if attack == "face_overflow"
                    else -40.0
                    if attack == "face_moment"
                    else 40.0
                ),
                "mv": (
                    10.0
                    if attack in {"face_moment", "face_overflow"}
                    else 60.0
                ),
                "m_total": (
                    0.0
                    if attack == "face_moment"
                    else 50.0
                    if attack == "face_overflow"
                    else 100.0
                ),
                "util": (
                    0.0
                    if attack == "face_moment"
                    else 0.50
                    if attack == "face_overflow"
                    else 1.0
                ),
                "capped": attack == "headroom_cap",
            }
            compression_mv = ftd_v * 0.25
            compression_total = max(-20.0 + compression_mv, 0.0)
            compression = {
                **common,
                "tension_low": False,
                "chord_role": "flexural_compression",
                "chord_formula": "8.52",
                "m_ed": 20.0,
                "face_m_ed_signed": -20.0,
                "mv": compression_mv,
                "m_total": compression_total,
                "util": compression_total / 100.0,
                "capped": False,
            }
            governing = max(
                (tension, compression), key=lambda item: item["util"]
            )
            combined_result.update(
                longitudinal_model_2023=True,
                longitudinal=tension,
                longitudinal_candidates=[tension, compression],
                governing_longitudinal=governing,
                longitudinal_assessment={
                    "status": "PASS",
                    "ok": True,
                    "util": governing["util"],
                    "reason": "required_longitudinal_chords_satisfied",
                    "coverage_complete": True,
                    "governing": governing,
                },
                torsion_longitudinal_assessment=(
                    _pub_h01_formula_628_assessment(0.0)
                ),
            )

        combined_result["overall_longitudinal_assessment"] = (
            capacity.combined_longitudinal_assessment(combined_result)
        )
        assert combined_result["overall_longitudinal_assessment"]["status"] == (
            "NOT ASSESSED"
        )
        at.session_state["results"] = retained

        leaf = _base_en_component_view(combined_result)
        assert not leaf.exception
        overall_metric = next(
            metric
            for metric in leaf.metric
            if metric.label == "Longitudinal reinforcement"
        )
        assert str(overall_metric.value) == "-"
        assert str(overall_metric.delta) == ""
        if attack not in {
            "formula_628",
            "subtube_liveness",
            "array_status",
            "tube_overflow",
        }:
            assert all(
                not (
                    metric.label == "Chord utilisation"
                    and str(metric.delta) == "PASS"
                )
                for metric in leaf.metric
            )

        row = _retained_longitudinal_component_row(leaf, combined_result)
        _assert_rejected_native_mvt_views(at)
        assert row["Status"] == "NOT ASSESSED"
        assert row["Result"] == "-"
    _restore_current_native_mvt_views(at, native_pristine, longitudinal=True)


def test_pub_h01_missing_off_axis_torsion_fails_closed_in_native_views():
    at = _fresh()
    at.run()
    _enable_all(at)
    native_pristine = _assert_current_native_mvt_views(at, longitudinal=True)
    assert not at.exception

    retained = copy.deepcopy(at.session_state["results"])
    combined_result = retained["combined"]
    candidates = combined_result["longitudinal_candidates"]
    assert len(candidates) == 4
    assert {item["role"] for item in candidates} == {
        "shear_axis",
        "off_axis",
    }
    assert combined_result["t_ed"] > 0.0
    common_torsion_force = {item["ftd_t"] for item in candidates}
    assert len(common_torsion_force) == 1
    assert next(iter(common_torsion_force)) > 0.0
    pristine = capacity.combined_longitudinal_assessment(combined_result)
    assert pristine["chord_status"] == "PASS"
    assert pristine["chord_coverage_complete"] is True

    for candidate in candidates:
        if candidate["role"] != "off_axis":
            continue
        candidate["ftd_t"] = 0.0
        candidate["mt"] = 0.0
        candidate["m_total"] = candidate["m_ed"]
        candidate["util"] = candidate["m_total"] / candidate["m_rd"]
        candidate["status"] = "PASS"
        candidate["ok"] = True
    governing = max(candidates, key=lambda item: item["util"])
    combined_result["governing_longitudinal"] = governing
    combined_result["longitudinal_assessment"].update(
        status="PASS",
        ok=True,
        util=governing["util"],
        reason="required_longitudinal_chords_satisfied",
        coverage_complete=True,
        governing=governing,
    )
    combined_result["overall_longitudinal_assessment"] = (
        capacity.combined_longitudinal_assessment(combined_result)
    )
    assert combined_result["overall_longitudinal_assessment"]["status"] == (
        "NOT ASSESSED"
    )
    at.session_state["results"] = retained

    leaf = _base_en_component_view(combined_result)
    assert not leaf.exception
    physical = next(
        metric
        for metric in leaf.metric
        if metric.label == "Longitudinal reinforcement"
    )
    assert str(physical.value) == "-"
    assert str(physical.delta) == ""
    assert all(
        not (
            metric.label == "Chord utilisation"
            and str(metric.delta) == "PASS"
        )
        for metric in leaf.metric
    )

    row = _retained_longitudinal_component_row(leaf, combined_result)
    _assert_rejected_native_mvt_views(at)
    assert row["Status"] == "NOT ASSESSED"
    assert row["Result"] == "-"
    _restore_current_native_mvt_views(at, native_pristine, longitudinal=True)


def test_pub_h01_subtube_total_forgery_fails_closed_in_torsion_and_overview():
    at = _fresh()
    at.run()
    _enable_all(at)
    native_pristine = _assert_current_native_mvt_views(at, longitudinal=True)
    assert not at.exception

    retained = copy.deepcopy(at.session_state["results"])
    torsion = retained["torsion"]
    first = copy.deepcopy(torsion["primary"])
    second = copy.deepcopy(torsion["primary"])
    for index, (subtube, torque) in enumerate(
        ((first, 10.0), (second, 20.0))
    ):
        subtube.update(
            asl_req=0.0,
            stiffness=1.0,
            x_mm=float(index * 250),
            y_mm=0.0,
            b_mm=200.0,
            h_mm=300.0,
            t_ed=torque,
            util=0.0,
        )
    torsion.update(
        t_ed=0.0,
        t_ed_signed=0.0,
        asl_req=0.0,
        applicability=capacity.torsion_applicability(
            {
                "torsion_design_basis": capacity.TORSION_DESIGN_EQUILIBRIUM,
                "torsion_member_scope": capacity.TORSION_MEMBER_CLOSED,
            },
            0.0,
        ),
        subdivided=True,
        subtubes=[first, second],
        primary=first,
        trd=first["trd"] + second["trd"],
        util=0.0,
        governing_sub=0,
        torque_distribution={
            "applied_torque": 0.0,
            "positive_stiffness_sum": 2.0,
            "shares": (
                {"index": 0, "stiffness": 1.0, "fraction": 0.5, "torque": 0.0},
                {"index": 1, "stiffness": 1.0, "fraction": 0.5, "torque": 0.0},
            ),
        },
        assessment_status="PASS",
        assessment_ok=True,
        overall_reason="no_longitudinal_torsion_demand",
    )
    torsion["longitudinal_assessment"].update(
        status="PASS",
        ok=True,
        reason="no_longitudinal_torsion_demand",
        required_asl_mm2=0.0,
        required_by_tube_mm2=(0.0, 0.0),
        required_design_force_kn=0.0,
        provided_gross_area_mm2=250.0,
        provided_design_force_kn=100.0,
        provided_equivalent_area_mm2=250.0,
        reference_fyd_mpa=400.0,
        demand_ratio=0.0,
        area_sufficient=True,
    )
    at.session_state["results"] = retained
    sanitized = result_presentation.torsion_longitudinal_assessment(torsion)
    assert sanitized["evidence_consistent"] is False
    assert sanitized["status"] == "NOT ASSESSED"

    _select_view(at, "Torsion")
    assert not at.exception
    assert not any(
        "Longitudinal assessment" in set(frame.value.get("Quantity", ()))
        for frame in at.dataframe
    )
    assert all(
        str(metric.delta) != "PASS" for metric in at.metric
    )

    _select_view(at, "Results Overview")
    assert not at.exception
    overview = at.table[0].value
    torsion_rows = overview.loc[
        overview["Check"].astype(str).str.startswith("Torsion")
    ]
    assert not torsion_rows.empty
    assert set(torsion_rows["Status"]) == {"NOT ASSESSED"}
    assert set(torsion_rows["Result"]) == {"-"}
    assert result_presentation.torsion_publication_component_is_current(
        at.session_state["result_input_snapshot"], retained["shear"], torsion,
    )[0] is False
    _assert_rejected_native_mvt_views(at)
    _restore_current_native_mvt_views(at, native_pristine, longitudinal=True)


@pytest.mark.parametrize(
    "child_state",
    (
        "documented_incomplete",
        "missing_list",
        "none_sibling",
        "malformed_status",
    ),
)
def test_pub_h01_known_failed_chord_survives_incomplete_face_in_native_views(
    child_state,
):
    at = _fresh()
    at.run()
    _enable_all(at)
    native_pristine = _assert_current_native_mvt_views(at, longitudinal=True)
    assert not at.exception

    retained = copy.deepcopy(at.session_state["results"])
    combined_result = retained["combined"]
    direct = {
        **combined_result["longitudinal"],
        "valid": True,
        "status": "FAIL",
        "ok": False,
        "role": "shear_axis",
        "axis": "x",
        "tension_low": True,
        "conditional": True,
        "biaxial": False,
        "off_util": 0.0,
        "off_not_evaluated": "not_solved",
        "has_torsion": True,
        "gets_shift": True,
        "m_ed": 80.0,
        "mv": 4.213620,
        "mt": 39.711696,
        "m_total": 123.925316,
        "m_rd": 100.0,
        "ftd_v": 17.34,
        "ftd_t": 326.8452380952381,
        "z": 0.243,
        "util": 1.2392531643,
        "capped": False,
        "cap_shear_force": True,
        "mv_uncapped": 4.213620,
        "shear_headroom": 20.0,
        "shear_term_selection": "uncapped",
    }
    combined_result.update(
        longitudinal_model_2023=False,
        longitudinal=direct,
        longitudinal_candidates=[direct],
        governing_longitudinal=direct,
        longitudinal_fallback=None,
        longitudinal_all_conditional=True,
        longitudinal_assessment={
            "status": "FAIL",
            "ok": False,
            "util": direct["util"],
            "reason": "required_longitudinal_chord_failed",
            "coverage_complete": False,
            "governing": direct,
        },
        torsion_longitudinal_assessment=(
            _pub_h01_formula_628_assessment(0.50)
        ),
    )
    if child_state == "missing_list":
        combined_result.pop("longitudinal_candidates", None)
    elif child_state == "none_sibling":
        combined_result["longitudinal_candidates"] = [direct, None]
    elif child_state == "malformed_status":
        malformed = {**direct, "status": ["PASS"]}
        combined_result["longitudinal_candidates"] = [direct, malformed]
    combined_result.pop("overall_longitudinal_assessment", None)
    combined_result["overall_longitudinal_assessment"] = (
        capacity.combined_longitudinal_assessment(combined_result)
    )
    assert combined_result["overall_longitudinal_assessment"]["status"] == "FAIL"
    assert combined_result["overall_longitudinal_assessment"]["util"] == (
        pytest.approx(1.2392531643)
    )
    at.session_state["results"] = retained

    leaf = _base_en_component_view(combined_result)
    assert not leaf.exception
    overall_metric = next(
        metric
        for metric in leaf.metric
        if metric.label == "Longitudinal reinforcement"
    )
    assert str(overall_metric.value) == "123.9 %"
    assert str(overall_metric.delta) == "FAIL"

    row = _retained_longitudinal_component_row(leaf, combined_result)
    _assert_rejected_native_mvt_views(at)
    assert row["Status"] == "FAIL"
    assert row["Result"] == "123.9 %"
    _restore_current_native_mvt_views(at, native_pristine, longitudinal=True)


@pytest.mark.parametrize("model_2023", (False, True), ids=("2005", "2023"))
def test_pub_h01_malformed_candidate_containers_keep_failure_in_native_views(
    model_2023,
):
    at = _fresh()
    at.run()
    _enable_all(at)
    native_pristine = _assert_current_native_mvt_views(at, longitudinal=True)
    assert not at.exception
    baseline = copy.deepcopy(at.session_state["results"])

    for candidate_container in (None, "bad", 7, True, {}, [], ()):
        retained = copy.deepcopy(baseline)
        combined_result = retained["combined"]
        if model_2023:
            direct = {
                "valid": True,
                "status": "FAIL",
                "ok": False,
                "role": "shear_axis",
                "axis": "x",
                "tension_low": True,
                "conditional": True,
                "biaxial": False,
                "off_util": 0.0,
                "off_not_evaluated": None,
                "m_ed": 40.0,
                "mv": 10.0,
                "mt": 0.0,
                "m_total": 50.0,
                "m_rd": 50.0 / 1.2392531643,
                "ftd_v": 40.0,
                "ftd_t": 0.0,
                "z": 0.25,
                "util": 1.2392531643,
                "capped": False,
                "cap_shear_force": False,
                "has_torsion": False,
                "gets_shift": True,
                "flexural_tension_low": True,
                "chord_role": "flexural_tension",
                "chord_formula": "8.51",
                "face_m_ed_signed": 40.0,
            }
            owner_torsion = 0.0
            owner_area = 0.0
            formula_628 = _pub_h01_formula_628_assessment(0.0)
        else:
            direct = {
                **combined_result["longitudinal"],
                "valid": True,
                "status": "FAIL",
                "ok": False,
                "role": "shear_axis",
                "axis": "x",
                "tension_low": True,
                "conditional": True,
                "biaxial": False,
                "off_util": 0.0,
                "off_not_evaluated": "not_solved",
                "has_torsion": True,
                "gets_shift": True,
                "m_ed": 80.0,
                "mv": 4.213620,
                "mt": 39.711696,
                "m_total": 123.925316,
                "m_rd": 100.0,
                "ftd_v": 17.34,
                "ftd_t": 326.8452380952381,
                "z": 0.243,
                "util": 1.2392531643,
                "capped": False,
                "cap_shear_force": True,
                "mv_uncapped": 4.213620,
                "shear_headroom": 20.0,
                "shear_term_selection": "uncapped",
            }
            for key in (
                "chord_formula",
                "chord_role",
                "flexural_tension_low",
                "face_m_ed_signed",
            ):
                direct.pop(key, None)
            owner_torsion = 40.0
            owner_area = 500.0
            formula_628 = _pub_h01_formula_628_assessment(0.50)
        combined_result.update(
            longitudinal_model_2023=model_2023,
            longitudinal=direct,
            longitudinal_candidates=candidate_container,
            governing_longitudinal=direct,
            longitudinal_fallback=None,
            longitudinal_all_conditional=True,
            longitudinal_assessment={
                "status": "NOT ASSESSED",
                "ok": None,
                "util": direct["util"],
                "reason": "required_longitudinal_chord_coverage_incomplete",
                "coverage_complete": False,
                "governing": direct,
            },
            t_ed=owner_torsion,
            asl_torsion=owner_area,
            torsion_subdivided=False,
            torsion_subtubes=None,
            torsion_longitudinal_assessment=formula_628,
            overall_longitudinal_assessment={
                "status": "NOT ASSESSED",
                "ok": None,
                "util": None,
            },
        )
        at.session_state["results"] = retained

        leaf = _base_en_component_view(combined_result)
        assert not leaf.exception
        overall_metric = next(
            metric
            for metric in leaf.metric
            if metric.label == "Longitudinal reinforcement"
        )
        assert str(overall_metric.value) == "123.9 %"
        assert str(overall_metric.delta) == "FAIL"

        row = _retained_longitudinal_component_row(leaf, combined_result)
        _assert_rejected_native_mvt_views(at)
        assert row["Status"] == "FAIL"
        assert row["Result"] == "123.9 %"
    _restore_current_native_mvt_views(at, native_pristine, longitudinal=True)


@pytest.mark.parametrize("model_2023", (False, True), ids=("2005", "2023"))
def test_pub_h01_malformed_candidate_container_never_promotes_native_pass(
    model_2023,
):
    at = _fresh()
    at.run()
    _enable_all(at)
    native_pristine = _assert_current_native_mvt_views(at, longitudinal=True)
    assert capacity.combined_longitudinal_assessment(
        native_pristine["combined"],
    )["chord_status"] == "PASS"
    assert not at.exception
    if not model_2023:
        # Isolate the missing inventory on a genuinely current chord-PASS bundle.
        # The unchanged compound manufactured vectors below remain separate.
        import pickle

        damaged = copy.deepcopy(native_pristine)
        damaged["combined"]["longitudinal_candidates"] = None
        for family in ("shear", "torsion"):
            assert pickle.dumps(damaged[family]) == pickle.dumps(native_pristine[family])
        for key in native_pristine["combined"]:
            if key != "longitudinal_candidates":
                assert pickle.dumps(damaged["combined"][key]) == pickle.dumps(
                    native_pristine["combined"][key],
                )
        assessment = capacity.combined_longitudinal_assessment(damaged["combined"])
        assert assessment["chord_status"] == "NOT ASSESSED"
        assert assessment["chord_util"] is None
        at.session_state["results"] = damaged
        _assert_rejected_native_mvt_views(at)
        _restore_current_native_mvt_views(at, native_pristine, longitudinal=True)
        assert capacity.combined_longitudinal_assessment(
            at.session_state["results"]["combined"],
        )["chord_status"] == "PASS"

    retained = copy.deepcopy(at.session_state["results"])
    combined_result = retained["combined"]
    if model_2023:
        direct = {
            "valid": True,
            "status": "PASS",
            "ok": True,
            "role": "shear_axis",
            "axis": "x",
            "tension_low": True,
            "conditional": True,
            "biaxial": False,
            "off_util": 0.0,
            "off_not_evaluated": None,
            "m_ed": 40.0,
            "mv": 10.0,
            "mt": 0.0,
            "m_total": 50.0,
            "m_rd": 62.5,
            "ftd_v": 40.0,
            "ftd_t": 0.0,
            "z": 0.25,
            "util": 0.80,
            "capped": False,
            "cap_shear_force": False,
            "has_torsion": False,
            "gets_shift": True,
            "flexural_tension_low": True,
            "chord_role": "flexural_tension",
            "chord_formula": "8.51",
            "face_m_ed_signed": 40.0,
        }
        owner_torsion = 0.0
        owner_area = 0.0
        formula_628 = _pub_h01_formula_628_assessment(0.0)
    else:
        direct = {
            **combined_result["longitudinal"],
            "valid": True,
            "status": "PASS",
            "ok": True,
            "role": "shear_axis",
            "axis": "x",
            "tension_low": True,
            "conditional": True,
            "biaxial": False,
            "off_util": 0.0,
            "off_not_evaluated": "not_solved",
            "has_torsion": True,
            "gets_shift": True,
            "m_ed": 80.0,
            "mv": 4.213620,
            "mt": 39.711696,
            "m_total": 123.925316,
            "m_rd": 123.925316 / 0.80,
            "ftd_v": 17.34,
            "ftd_t": 326.8452380952381,
            "z": 0.243,
            "util": 0.80,
            "capped": False,
            "cap_shear_force": True,
            "mv_uncapped": 4.213620,
            "shear_headroom": 123.925316 / 0.80 - 80.0,
            "shear_term_selection": "uncapped",
        }
        for key in (
            "chord_formula",
            "chord_role",
            "flexural_tension_low",
            "face_m_ed_signed",
        ):
            direct.pop(key, None)
        owner_torsion = 40.0
        owner_area = 500.0
        formula_628 = _pub_h01_formula_628_assessment(0.50)
    combined_result.update(
        longitudinal_model_2023=model_2023,
        longitudinal=direct,
        longitudinal_candidates=None,
        governing_longitudinal=direct,
        longitudinal_fallback=None,
        longitudinal_all_conditional=True,
        longitudinal_assessment={
            "status": "NOT ASSESSED",
            "ok": None,
            "util": direct["util"],
            "reason": "required_longitudinal_chord_coverage_incomplete",
            "coverage_complete": False,
            "governing": direct,
        },
        t_ed=owner_torsion,
        asl_torsion=owner_area,
        torsion_subdivided=False,
        torsion_subtubes=None,
        torsion_longitudinal_assessment=formula_628,
        overall_longitudinal_assessment={
            "status": "NOT ASSESSED",
            "ok": None,
            "util": None,
        },
    )
    at.session_state["results"] = retained

    leaf = _base_en_component_view(combined_result)
    assert not leaf.exception
    overall_metric = next(
        metric
        for metric in leaf.metric
        if metric.label == "Longitudinal reinforcement"
    )
    assert str(overall_metric.value) == "-"
    assert str(overall_metric.delta) == ""
    assert all(
        not (
            metric.label == "Chord utilisation"
            and str(metric.delta) == "PASS"
        )
        for metric in leaf.metric
    )

    row = _retained_longitudinal_component_row(leaf, combined_result)
    _assert_rejected_native_mvt_views(at)
    assert row["Status"] == "NOT ASSESSED"
    assert row["Result"] == "-"
    _restore_current_native_mvt_views(at, native_pristine, longitudinal=True)


def test_pub_h01_roleless_torsion_failure_with_zero_owner_is_not_published():
    at = _fresh()
    at.run()
    _enable_all(at)
    native_pristine = _assert_current_native_mvt_views(at, longitudinal=True)
    assert not at.exception

    retained = copy.deepcopy(at.session_state["results"])
    combined_result = retained["combined"]
    direct = {
        **combined_result["longitudinal"],
        "valid": True,
        "status": "FAIL",
        "ok": False,
        "axis": "x",
        "tension_low": True,
        "conditional": True,
        "biaxial": False,
        "off_util": 0.0,
        "off_not_evaluated": "not_solved",
        "m_ed": 80.0,
        "mv": 4.213620,
        "mt": 39.711696,
        "m_total": 123.925316,
        "m_rd": 100.0,
        "ftd_v": 17.34,
        "ftd_t": 326.8452380952381,
        "z": 0.243,
        "util": 1.2392531643,
        "capped": False,
        "cap_shear_force": True,
        "mv_uncapped": 4.213620,
        "shear_headroom": 20.0,
        "shear_term_selection": "uncapped",
    }
    for role_key in (
        "role",
        "has_torsion",
        "gets_shift",
        "chord_formula",
        "chord_role",
        "flexural_tension_low",
        "face_m_ed_signed",
    ):
        direct.pop(role_key, None)
    combined_result.update(
        longitudinal_model_2023=False,
        longitudinal=direct,
        longitudinal_candidates=None,
        governing_longitudinal=direct,
        longitudinal_fallback=None,
        longitudinal_all_conditional=True,
        longitudinal_assessment={
            "status": "NOT ASSESSED",
            "ok": None,
            "util": direct["util"],
            "reason": "required_longitudinal_chord_coverage_incomplete",
            "coverage_complete": False,
            "governing": direct,
        },
        t_ed=0.0,
        asl_torsion=0.0,
        torsion_subdivided=False,
        torsion_subtubes=None,
        torsion_longitudinal_assessment=(
            _pub_h01_formula_628_assessment(0.0)
        ),
    )
    combined_result["overall_longitudinal_assessment"] = (
        capacity.combined_longitudinal_assessment(combined_result)
    )
    assert combined_result["overall_longitudinal_assessment"]["status"] == (
        "NOT ASSESSED"
    )
    at.session_state["results"] = retained

    leaf = _base_en_component_view(combined_result)
    assert not leaf.exception
    overall_metric = next(
        metric
        for metric in leaf.metric
        if metric.label == "Longitudinal reinforcement"
    )
    assert str(overall_metric.value) == "-"
    assert str(overall_metric.delta) == ""
    visible = " ".join(
        str(item.value)
        for collection in (
            leaf.metric,
            leaf.warning,
            leaf.info,
            leaf.caption,
            leaf.markdown,
        )
        for item in collection
    )
    assert "123.9 %" not in visible

    row = _retained_longitudinal_component_row(leaf, combined_result)
    _assert_rejected_native_mvt_views(at)
    assert row["Status"] == "NOT ASSESSED"
    assert row["Result"] == "-"
    _restore_current_native_mvt_views(at, native_pristine, longitudinal=True)


@pytest.mark.parametrize(
    "hostile", ("malformed", "stale_alias", "overflowing_real")
)
def test_pub_h01_inconsistent_longitudinal_evidence_fails_closed_in_native_views(
    hostile,
):
    at = _fresh()
    at.run()
    _enable_all(at)
    native_pristine = _assert_current_native_mvt_views(at, longitudinal=True)
    assert not at.exception

    retained = copy.deepcopy(at.session_state["results"])
    combined_result = retained["combined"]
    direct = {
        **combined_result["longitudinal"],
        "valid": True,
        "status": "FAIL",
        "ok": False,
        "axis": "x",
        "tension_low": True,
        "conditional": True,
        "biaxial": False,
        "off_util": 0.0,
        "off_not_evaluated": None,
        "m_ed": 80.0,
        "mv": 4.213620,
        "mt": 39.711696,
        "m_total": 123.925316,
        "m_rd": 100.0,
        "ftd_v": 17.34,
        "ftd_t": 326.8452380952381,
        "z": 0.243,
        "util": 1.2392531643,
        "capped": False,
    }
    combined_result["longitudinal"] = direct
    for key in (
        "governing_longitudinal",
        "longitudinal_assessment",
        "longitudinal_candidates",
        "longitudinal_fallback",
        "overall_longitudinal_assessment",
    ):
        combined_result.pop(key, None)
    combined_result["longitudinal_all_conditional"] = True
    if hostile == "malformed":
        direct["m_ed"] = "not-a-number"
    elif hostile == "overflowing_real":
        for role_key in (
            "role",
            "has_torsion",
            "gets_shift",
            "chord_formula",
            "chord_role",
            "flexural_tension_low",
            "face_m_ed_signed",
        ):
            direct.pop(role_key, None)
        direct["m_ed"] = 10**1000
    else:
        combined_result["governing_longitudinal"] = {
            **direct,
            "status": "PASS",
            "ok": True,
            "m_ed": 0.0,
            "mv": 10.0,
            "mt": 40.0,
            "m_total": 50.0,
            "util": 0.50,
        }
    combined_result["torsion_longitudinal_assessment"] = {
        "status": "NOT ASSESSED",
        "ok": None,
        "reason": "longitudinal_torsion_reinforcement_not_verified",
        "demand_ratio": 0.50,
    }
    combined_result["overall_longitudinal_assessment"] = (
        capacity.combined_longitudinal_assessment(combined_result)
    )
    assert combined_result["overall_longitudinal_assessment"]["status"] == (
        "NOT ASSESSED"
    )
    at.session_state["results"] = retained

    leaf = _base_en_component_view(combined_result)
    assert not leaf.exception
    physical = next(
        metric for metric in leaf.metric
        if metric.label == "Longitudinal reinforcement"
    )
    assert str(physical.value) == "-"
    visible = " ".join(
        str(item.value)
        for collection in (
            leaf.metric,
            leaf.warning,
            leaf.info,
            leaf.caption,
            leaf.markdown,
        )
        for item in collection
    )
    assert "NOT ASSESSED" in visible
    if hostile == "malformed":
        assert "not-a-number" not in visible
    assert "123.9 %" not in visible
    assert not any(
        str(metric.value).casefold() in {"nan", "inf", "-inf"}
        for metric in leaf.metric
    )

    row = _retained_longitudinal_component_row(leaf, combined_result)
    _assert_rejected_native_mvt_views(at)
    assert row["Status"] == "NOT ASSESSED"
    assert row["Result"] == "-"
    _restore_current_native_mvt_views(at, native_pristine, longitudinal=True)


def test_pub_h01_contract_recomputes_capacity_and_clears_buffered_report():
    import sector_app

    at = _fresh()
    at.run()
    _set(
        at,
        ("radio", "mode", "Both"),
        ("number_input", "pl_Mx", 100.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "torsion_T", 40.0),
    )
    assert not at.exception

    latest = at.session_state["_latest_inputs"]
    token = sector_app._CAPACITY_RESULT_CONTRACT_TOKEN
    marker = "canonical-combined-longitudinal-assessment-v1"
    assert marker in token
    pre_pub_h01_token = tuple(item for item in token if item != marker)
    plastic_before = at.session_state["results"]["plastic"]
    elastic_before = at.session_state["results"]["elastic"]
    cached = at.session_state["results"]["plastic_cases"][0]
    cached["results"]["combined"]["pre_pub_h01_marker"] = True
    cached["results"]["combined"]["longitudinal"]["util"] = 0.50
    at.session_state["report_buffer"] = b"pre-PUB-H01 report"
    at.session_state["report_signature"] = ("pre-PUB-H01",)
    for key in (
        "result_sig",
        "result_plastic_sig",
        "result_plastic_case_context_sig",
    ):
        at.session_state[key] = tuple(
            pre_pub_h01_token if item == token else item
            for item in at.session_state[key]
        )
    assert at.session_state["result_sig"] != latest["signature"]

    _calculate(at)

    results = at.session_state["results"]
    assert results["plastic"] is plastic_before
    assert results["elastic"] is elastic_before
    assert results["plastic_cases"][0]["reused"] is False
    assert "pre_pub_h01_marker" not in results["combined"]
    assert "overall_longitudinal_assessment" in results["combined"]
    assert results["elastic_cases"][0]["reused"] is True

    _goto_page(at, "Report")
    assert any(
        "Report out of date" in warning.value for warning in at.warning
    )
    assert not any(
        button.label == "Download report (PDF)"
        for button in at.download_button
    )


def test_incomplete_2023_chord_keeps_retained_mvt_not_assessed():
    combined_result = {
        "valid": True,
        "dkna_valid": True,
        "dkna_sum": 0.60,
        "dkna_limit_satisfied": True,
        "dkna_status": "PASS",
        "dkna_ok": True,
        "torsion_assessment_status": "PASS",
        "torsion_longitudinal_assessment": {
            "status": "NOT ASSESSED",
            "demand_ratio": 0.40,
            "reason": "longitudinal_torsion_reinforcement_not_verified",
        },
        "longitudinal_assessment": {
            "status": "NOT ASSESSED",
            "ok": None,
            "util": 0.50,
            "reason": "required_longitudinal_chord_coverage_incomplete",
            "coverage_complete": False,
            "governing": {"valid": True, "util": 0.50},
        },
    }

    assert (
        result_presentation.combined_dkna_status(combined_result)
        == "NOT ASSESSED"
    )
    components = {
        item["key"]: item
        for item in result_presentation.combined_physical_components(
            combined_result
        )
    }
    assert components["longitudinal"]["status"] == "NOT ASSESSED"
    assert components["longitudinal"]["coverage"] == "incomplete"
    assert components["longitudinal"]["util"] is None
    assert components["longitudinal"]["chord_status"] == "NOT ASSESSED"
    assert components["longitudinal"]["chord_util"] is None
    assert "Recalculate the combined longitudinal reinforcement assessment" in (
        components["longitudinal"]["note"]
    )
    # Original retained missing-face and distribution guidance remain distinct
    # from the current canonical reconstruction's recalculation instruction.
    assert "Complete both required longitudinal chord checks" in (
        result_presentation.combined_longitudinal_chord_assessment_note(combined_result)
    )
    assert "distributed around every torsion-tube side" in result_presentation.result_reason(
        combined_result["torsion_longitudinal_assessment"]["reason"], "torsion",
    )
    assert combined_result["longitudinal_assessment"]["util"] == 0.50
    assert combined_result["longitudinal_assessment"]["coverage_complete"] is False


def test_incomplete_torsion_wall_evidence_blocks_stale_mvt_verdicts():
    raw_reason = "torsion wall reinforcement mapping is incomplete"
    torsion_result = {
        "valid": False,
        "tube_valid": False,
        "closed_links_present": True,
        "transverse_resistance_assessed": False,
        "full_resistance_assessed": False,
        "reason": raw_reason,
        "trd": 999.123,
        "util": 0.42,
    }
    stale_combined = {
        "valid": True,
        "dkna_valid": True,
        "dkna_sum": 0.72,
        "dkna_limit_satisfied": True,
        "dkna_status": "PASS",
        "dkna_ok": True,
    }
    results = {"torsion": torsion_result, "combined": stale_combined}

    # Missing applicability is an earlier, independent blocker.
    assert "design basis and member scope have not been established" in (
        result_presentation.combined_bending_assessment_blocker(results)
    )
    torsion_result["t_ed"] = 1.0
    torsion_result["applicability"] = capacity.torsion_applicability({
        "torsion_design_basis": capacity.TORSION_DESIGN_EQUILIBRIUM,
        "torsion_member_scope": capacity.TORSION_MEMBER_CLOSED,
    }, 1.0)
    assert result_presentation.torsion_applicability_publication_status(
        torsion_result,
    ) == "APPLICABLE"
    blocker = result_presentation.combined_bending_assessment_blocker(results)
    assert blocker == (
        "Torsion prerequisite is not assessed: Torsion is not assessed because "
        "longitudinal reinforcement has not been established for every "
        "equivalent-tube wall"
    )
    assert raw_reason not in blocker
    rows = result_presentation.result_summary_rows(
        {"torsion_on": True, "combined_on": True, "shear_links": True},
        results,
    )
    combined_row = next(
        row for row in rows if row["check"] == "Combined M-V-T - DK NA sum"
    )
    assert combined_row["status"] == "NOT ASSESSED"
    assert combined_row["result"] == "-"
    assert combined_row["util"] is None
    assert (
        result_presentation.worked_example_selection({}, results)["families"].get(
            "combined"
        )
        is None
    )


def test_app_invalid_tube_does_not_poison_the_member_angle():
    # Workflow finding: an INVALID torsion tube (util = inf at every angle) must not
    # constrain the member angle -- previously it tied the scan and pinned the links
    # at band-low, changing the shear result.
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 500.0),
    )
    base = at.session_state["results"]["shear"]["links"]
    assert base["res"]["cot"] == pytest.approx(2.5)
    assert math.isfinite(base["util"])
    _set(at, ("checkbox", "torsion_on", True))
    _set_and_click(
        at,
        "calculate",
        ("number_input", "torsion_T", 40.0),
        ("number_input", "torsion_tef", 400.0),
    )  # tef > section: invalid
    r = at.session_state["results"]
    assert not r["torsion"]["valid"]                             # tube rejected
    lk = r["shear"]["links"]
    assert lk["res"]["cot"] == pytest.approx(2.5)                # angle unaffected
    assert lk["util"] == pytest.approx(base["util"])             # verdict unchanged


def test_app_objective_matches_reported_chord_cap():
    # Workflow finding: the objective must scan the SAME capped chord utilisation the
    # app reports. Here the cap saturates (MEd ~ MRd), so steepening cannot improve
    # the reported chord -- the angle must NOT sacrifice the stirrups (the old
    # uncapped objective dragged cot to 1.0 and failed them).
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 500.0),
        ("number_input", "pl_Mx", 430.0),
    )  # ~0.97 MRd
    lk = at.session_state["results"]["shear"]["links"]
    assert lk["res"]["cot"] == pytest.approx(2.5, abs=0.05)
    assert lk["util"] < 1.0                                      # stirrups still pass
    assert lk["chord"]["capped"]                                 # cap is active


def test_app_zero_torsion_is_skipped_with_the_shared_strut_band():
    # A zero torsion action is skipped; the live shear check uses the shared band.
    at = _fresh()
    at.run()
    _run_member(
        at,
        v=500.0,
        t=0.0,
        combined_on=False,
        strut_band=(1.0, 2.5),
    )
    r = at.session_state["results"]
    lk = r["shear"]["links"]
    assert lk["res"]["cot"] == pytest.approx(2.5)                # shear band governs
    assert "torsion" not in r


def test_app_dead_shear_companion_uses_the_shared_strut_band():
    # Mirror of the T=0 case: zero shear is skipped while torsion remains live.
    at = _fresh()
    at.run()
    _run_member(
        at,
        mx=80.0,
        v=0.0,
        t=40.0,
        combined_on=False,
        strut_band=(1.0, 1.2),
    )
    r = at.session_state["results"]
    assert "shear" not in r
    assert 1.0 - 1e-9 <= r["torsion"]["cot"] <= 1.2 + 1e-9


def test_app_invalid_bending_evidence_does_not_poison_the_member_angle():
    # An unreachable N/M request produces invalid plastic evidence, not an invented
    # infinite utilisation. The combined check must fail closed while the independent
    # V/T member-angle selection remains the same as when combined interaction is off.
    def run(combined):
        at = _fresh()
        at.run()
        _run_member(
            at,
            mx=120.0,
            p=8000.0,
            v=300.0,
            t=60.0,
            combined_on=combined,
        )
        return at.session_state["results"]
    r_on = run(True)
    r_off = run(False)
    assert r_on["plastic"]["util"] is None
    assert r_on["plastic"]["util_valid"] is False
    assert r_on["combined"]["valid"] is False
    assert r_on["combined"]["have_m"] is False
    cot_on = r_on["shear"]["links"]["res"]["cot"]
    cot_off = r_off["shear"]["links"]["res"]["cot"]
    assert cot_on == pytest.approx(cot_off)


def test_app_dkna_action_alone_resistances_are_not_evaluated_at_common_angle():
    # DK NA 6.3.2(6) uses each resistance for its action acting ALONE. The selected
    # common angle remains authoritative for the physical shared-strut/stirrup/chord
    # checks, but it must not condition the action-alone V or T denominator.
    at = _fresh()
    at.run()

    _run_member(at, mx=150.0, v=280.0, t=100.0)
    result = at.session_state["results"]
    c = result["combined"]
    cot_star = result["shear"]["links"]["res"]["cot"]
    labels = c["member_angle_selection"]["objective_labels"]
    assert "DK NA governing interaction" not in labels
    v_action = c["action_alone"]["v"]
    t_action = c["action_alone"]["t"]
    assert c["r_v"] == pytest.approx(
        v_action["demand"] / v_action["resistance"]
    )
    assert c["r_t"] == pytest.approx(
        t_action["demand"] / t_action["resistance"]
    )
    # The action-alone capacities optimise their own resistance within the same
    # declared admissible band; the common physical angle remains separate.
    assert v_action["evidence"]["cot"] != pytest.approx(cot_star)
    assert t_action["evidence"]["cot"] != pytest.approx(cot_star)


@pytest.fixture(scope="module")
def pub_m01_native_environment(tmp_path_factory):
    """Isolate module-scoped native producers before function fixtures run."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(
            "SECTOR_AUTOSAVE_DIR",
            str(tmp_path_factory.mktemp("pub-m01-module") / "autosave"),
        )
        yield


@pytest.fixture(scope="module")
def pub_m01_exact_minimax_case(pub_m01_native_environment):
    """One exact producer for the shared-angle minimax and endpoint control."""

    at = _fresh()
    at.run()
    _run_member(
        at,
        mx=150.0,
        v=550.0,
        t=100.0,
        strut_band=(1.0, 2.5),
    )
    assert not at.exception
    wide_input = copy.deepcopy(at.session_state["result_input_snapshot"])
    wide_results = copy.deepcopy(at.session_state["results"])

    _select_view(at, "Shear")
    assert not at.exception
    shear_metrics = tuple(
        (metric.label, str(metric.value), str(metric.delta))
        for metric in at.metric
    )
    shear_visible = " ".join(
        str(item.value)
        for collection in (at.warning, at.info, at.caption, at.markdown)
        for item in collection
    )
    shear_tables = " ".join(
        frame.value.to_string(index=False) for frame in at.dataframe
    )

    _select_view(at, "M-V-T Combined")
    assert not at.exception
    combined_metrics = tuple(
        (metric.label, str(metric.value), str(metric.delta))
        for metric in at.metric
    )
    combined_visible = " ".join(
        str(item.value)
        for collection in (at.warning, at.info, at.caption, at.markdown)
        for item in collection
    )

    _select_view(at, "Results Overview")
    assert not at.exception
    overview = at.table[0].value.copy(deep=True)

    _run_member(
        at,
        mx=150.0,
        v=550.0,
        t=100.0,
        strut_band=(2.5, 2.5),
    )
    assert not at.exception
    fixed_input = copy.deepcopy(at.session_state["result_input_snapshot"])
    fixed_results = copy.deepcopy(at.session_state["results"])

    poisoned_results = copy.deepcopy(wide_results)
    for family in ("shear", "torsion", "combined"):
        poisoned_results[family] = copy.deepcopy(fixed_results[family])
    for target, source in zip(
        poisoned_results.get("plastic_cases") or (),
        fixed_results.get("plastic_cases") or (),
        strict=True,
    ):
        target_results = target.get("results") or {}
        source_results = source.get("results") or {}
        for family in ("shear", "torsion", "combined"):
            target_results[family] = copy.deepcopy(source_results[family])

    _set(
        at,
        ("number_input", "strut_cot_min", 1.0),
        ("number_input", "strut_cot_max", 2.5),
    )
    at.session_state["results"] = copy.deepcopy(poisoned_results)
    at.session_state["result_input_snapshot"] = copy.deepcopy(wide_input)
    at.session_state["result_sig"] = wide_input["signature"]
    at.session_state["result_plastic_sig"] = wide_input["plastic_sig"]
    at.session_state["result_plastic_case_context_sig"] = wide_input[
        "plastic_case_context_sig"
    ]
    at.session_state["result_plastic_bending_context_sig"] = wide_input[
        "plastic_bending_context_sig"
    ]
    _select_view(at, "Torsion")
    assert not at.exception
    poisoned_torsion_metrics = tuple(
        (metric.label, str(metric.value), str(metric.delta))
        for metric in at.metric
    )
    poisoned_torsion_visible = " ".join(
        str(item.value)
        for collection in (at.warning, at.info, at.caption, at.markdown)
        for item in collection
    )
    _select_view(at, "Results Overview")
    assert not at.exception
    poisoned_overview = at.table[0].value.copy(deep=True)
    return {
        "wide_input": wide_input,
        "wide_results": wide_results,
        "fixed_input": fixed_input,
        "fixed_results": fixed_results,
        "poisoned_results": poisoned_results,
        "poisoned_torsion_metrics": poisoned_torsion_metrics,
        "poisoned_torsion_visible": poisoned_torsion_visible,
        "poisoned_overview": poisoned_overview,
        "shear_metrics": shear_metrics,
        "shear_visible": shear_visible,
        "shear_tables": shear_tables,
        "combined_metrics": combined_metrics,
        "combined_visible": combined_visible,
        "overview": overview,
    }


def test_pub_m01_exact_minimax_rejects_coherent_fixed_endpoint_result(
    pub_m01_exact_minimax_case,
):
    case = pub_m01_exact_minimax_case
    wide_input = case["wide_input"]
    wide = case["wide_results"]
    fixed_input = case["fixed_input"]
    fixed = case["fixed_results"]

    selection = wide["combined"]["member_angle_selection"]
    assert selection["cot"] == pytest.approx(2.332)
    assert selection["theta_deg"] == pytest.approx(23.210450538217586)
    assert selection["utilisation"] == pytest.approx(1.7899186763923811)
    assert selection["samples"] == 1501
    assert selection["step"] == pytest.approx(0.001)
    assert selection["selected_index"] == 1332
    assert selection["objective_count"] == 9
    assert selection["governing_component_indices"] == (6,)
    assert selection["governing_objectives"] == (
        "x-axis positive longitudinal chord",
    )
    assert selection["runner_up_utilisation"] == pytest.approx(
        1.7891604810044097
    )
    assert wide["shear"]["links"]["util"] == pytest.approx(
        1.0579291203151089
    )
    assert wide["combined"]["dkna_sum"] == pytest.approx(
        2.402432432531132
    )
    assert result_presentation.combined_publication_evidence_is_current(
        wide_input,
        wide,
    ) == (True, None)

    fixed_selection = fixed["combined"]["member_angle_selection"]
    assert fixed_selection["cot"] == pytest.approx(2.5)
    assert fixed_selection["utilisation"] == pytest.approx(1.9188665055664464)
    assert fixed["shear"]["links"]["util"] == pytest.approx(
        0.9868362834299335
    )
    assert result_presentation.combined_publication_evidence_is_current(
        fixed_input,
        fixed,
    ) == (True, None)
    assert result_presentation.combined_publication_evidence_is_current(
        wide_input,
        fixed,
    ) == (False, "combined component evidence is unavailable")
    assert result_presentation.torsion_publication_evidence_is_current(
        wide_input,
        wide["shear"],
        wide["torsion"],
    ) == (True, None)
    assert result_presentation.torsion_publication_evidence_is_current(
        fixed_input,
        fixed["shear"],
        fixed["torsion"],
    ) == (True, None)
    assert result_presentation.torsion_publication_evidence_is_current(
        wide_input,
        wide["shear"],
        fixed["torsion"],
    ) == (False, "torsion result evidence is unavailable")
    for missing in ("absent", "none"):
        shear = copy.deepcopy(wide["shear"])
        torsion = copy.deepcopy(fixed["torsion"])
        if missing == "absent":
            (shear.get("links") or {}).pop("member_angle_selection", None)
            torsion.pop("member_angle_selection", None)
        else:
            (shear.get("links") or {})["member_angle_selection"] = None
            torsion["member_angle_selection"] = None
        assert result_presentation.torsion_publication_evidence_is_current(
            wide_input,
            shear,
            torsion,
        ) == (False, "torsion result evidence is unavailable")
        for theta_mode in (None, "resistance", "unavailable"):
            altered_shear = copy.deepcopy(shear)
            links = altered_shear.get("links") or {}
            if theta_mode is None:
                links.pop("theta_mode", None)
            else:
                links["theta_mode"] = theta_mode
            assert result_presentation.torsion_publication_evidence_is_current(
                wide_input,
                altered_shear,
                torsion,
            ) == (False, "torsion result evidence is unavailable")
    independent_torsion = copy.deepcopy(fixed["torsion"])
    independent_torsion.pop("member_angle_selection", None)
    independent_input = copy.deepcopy(fixed_input)
    independent_input["shear_on"] = False
    independent_input["shear_V"] = 0.0
    independent_input["shear_Vx"] = 0.0
    independent_input["shear_Vy"] = 0.0
    assert result_presentation.torsion_publication_evidence_is_current(
        independent_input,
        None,
        independent_torsion,
    ) == (False, "torsion result evidence is unavailable")

    # A positive independent control is calculated with its actual participants;
    # removing evidence from a shared-angle result cannot create that control.
    import sector_app

    independent = {"plastic": copy.deepcopy(wide["plastic"])}
    sector_app._run_capacity_checks(independent_input, independent)
    assert independent["torsion"]["member_angle_selection"] is not None
    assert result_presentation.torsion_publication_evidence_is_current(
        independent_input,
        None,
        independent["torsion"],
    ) == (True, None)


def test_pub_m01_exact_minimax_reaches_native_views(
    pub_m01_exact_minimax_case,
):
    case = pub_m01_exact_minimax_case
    assert any(
        value == "105.8 %" and delta in {"FAIL", "Over limit"}
        for _label, value, delta in case["shear_metrics"]
    )
    assert "2.332" in case["shear_visible"] + case["shear_tables"]
    assert "NOT ASSESSED" not in case["shear_visible"]
    assert any(
        value == "240.2 %" and delta == "FAIL"
        for _label, value, delta in case["combined_metrics"]
    )
    assert ("Shear share", "105.8 %", "") in case["combined_metrics"]
    assert any(
        label == "Closed-stirrup utilisation"
        and value == "178.9 %" and delta == "FAIL"
        for label, value, delta in case["combined_metrics"]
    )
    assert "cot\\theta=2.33" in case["combined_visible"].replace(" ", "")

    by_check = {
        row["Check"]: row
        for _, row in case["overview"].iterrows()
    }
    assert by_check["Shear with links"]["Status"] == "FAIL"
    assert by_check["Shear with links"]["Result"] == "105.8 %"
    assert by_check["Combined M-V-T - DK NA sum"]["Status"] == "FAIL"
    assert by_check["Combined M-V-T - DK NA sum"]["Result"] == "240.2 %"


def test_pub_m01_fixed_angle_torsion_transplant_is_withheld_from_native_views(
    pub_m01_exact_minimax_case,
):
    case = pub_m01_exact_minimax_case
    assert any(
        value == "NOT ASSESSED"
        for _label, value, _delta in case["poisoned_torsion_metrics"]
    )
    visible = case["poisoned_torsion_visible"]
    assert "NOT ASSESSED" in visible
    assert "101.4 %" not in visible
    assert "3084" not in visible.replace(",", "")

    rows = case["poisoned_overview"]
    torsion = rows.loc[rows["Check"] == "Torsion"].iloc[0]
    assert torsion["Status"] == "NOT ASSESSED"
    assert torsion["Result"] == "-"
    assert not rows["Result"].astype(str).str.contains("101.4", regex=False).any()
    assert not rows["Result"].astype(str).str.contains("3084", regex=False).any()


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_pub_m01_exact_minimax_reaches_every_report_profile(
    pub_m01_exact_minimax_case,
    profile,
):
    import io

    from pypdf import PdfReader

    import sector_report

    inp = pub_m01_exact_minimax_case["wide_input"]
    results = copy.deepcopy(pub_m01_exact_minimax_case["wide_results"])
    results["worked_example_selection"] = (
        result_presentation.worked_example_selection(inp, results)
    )
    pdf = sector_report.build_report(
        {},
        inp,
        results,
        figures=False,
        profile=profile,
    )
    text = " ".join(
        " ".join((page.extract_text() or "").split())
        for page in PdfReader(io.BytesIO(pdf)).pages
    )

    assert "Shear with links PL-01 FAIL 105.8 %" in text
    assert "Combined M-V-T - DK NA sum PL-01 FAIL 240.2 %" in text
    if profile != "Brief":
        assert "Selected common member angle: cot theta = 2.332" in text.replace(
            chr(0x03B8), "theta"
        )
        assert "105.8 %" in text
        assert "240.2 %" in text


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_pub_m01_fixed_angle_torsion_transplant_is_withheld_from_reports(
    pub_m01_exact_minimax_case,
    profile,
):
    import io

    from pypdf import PdfReader

    import sector_report

    case = pub_m01_exact_minimax_case
    pdf = sector_report.build_report(
        {},
        case["wide_input"],
        copy.deepcopy(case["poisoned_results"]),
        figures=False,
        profile=profile,
    )
    text = " ".join(
        " ".join((page.extract_text() or "").split())
        for page in PdfReader(io.BytesIO(pdf)).pages
    )
    assert "Torsion PL-01 NOT ASSESSED -" in text
    assert "101.4 %" not in text
    assert "3,084" not in text
    assert "3084" not in text


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_pub_m01_genuine_fixed_angle_keeps_its_own_report_values(
    pub_m01_exact_minimax_case, profile,
):
    import io

    from pypdf import PdfReader

    import sector_report

    case = pub_m01_exact_minimax_case
    inp = case["fixed_input"]
    out = copy.deepcopy(case["fixed_results"])
    out["worked_example_selection"] = result_presentation.worked_example_selection(inp, out)
    assert result_presentation.torsion_publication_evidence_is_current(
        inp, out["shear"], out["torsion"],
    ) == (True, None)
    pdf = sector_report.build_report({}, inp, out, figures=False, profile=profile)
    text = " ".join(
        " ".join((page.extract_text() or "").split())
        for page in PdfReader(io.BytesIO(pdf)).pages
    )
    assert "Shear with links PL-01 PASS 98.7 %" in text
    assert "Torsion transverse/strut resistance PL-01 FAIL 101.4 %" in text
    if profile != "Brief":
        assert "Selected common member angle: cot theta = 2.500" in text.replace(
            chr(0x03B8), "theta",
        )


def test_app_combined_is_skipped_when_shear_is_zero(monkeypatch):
    # VEd = 0 disables the shear and dependent combined checks for this case.
    monkeypatch.setattr(
        capacity,
        "dkna_normal_bending_action_alone",
        lambda _inp: pytest.fail(
            "action-alone resistance entered for a zero-shear combined check"
        ),
    )
    at = _fresh()
    at.run()
    _run_member(
        at,
        mx=90.0,
        v=0.0,
        t=60.0,
        strut_band=(1.0, 1.4),
    )
    r = at.session_state["results"]
    assert "shear" not in r
    assert "combined" not in r
    assert "torsion" in r


def test_app_no_transverse_load_skips_capacity_and_combined_checks():
    # VEd = TEd = 0 means neither transverse check is evaluated for this case.
    at = _fresh()
    at.run()
    _run_member(at, mx=100.0, v=0.0, t=0.0)
    r = at.session_state["results"]
    assert "shear" not in r
    assert "torsion" not in r
    assert "combined" not in r
    _select_view(at, "M-V-T Combined")
    assert any("Vx,Ed = Vy,Ed = TEd = 0" in item.value for item in at.info)


def test_app_combined_longitudinal_matches_shear_chord():
    # The combined view's longitudinal check and the shear view's chord check are the
    # SAME computation (one member angle) -- the payloads must agree.
    at = _fresh()
    at.run()
    _enable_all(at)
    r = at.session_state["results"]
    lg = r["combined"]["longitudinal"]
    ch = r["shear"]["links"]["chord"]
    assert lg["util"] == pytest.approx(ch["util"])
    assert lg["m_total"] == pytest.approx(ch["m_total"])


def test_app_combined_transverse_shear_credit():
    # VEd <= VRd,c: the concrete carries the shear, so the shared stirrup's shear
    # share is 0 and the whole stirrup serves torsion (Q2).
    at = _fresh()
    at.run()
    _run_member(at, mx=100.0, v=10.0, t=40.0)  # V well below VRd,c
    assert not at.exception
    tr = at.session_state["results"]["combined"]["transverse"]
    assert tr["shear_credited"] is True
    assert tr["shear_fraction"] == pytest.approx(0.0)
    assert tr["torsion_fraction"] > 0.0
    # With the shear credited the stirrup serves torsion alone; the governing value
    # is still max(stirrup, crushing) AT THE MEMBER ANGLE, where the crushing sum
    # (6.29, no VRd,c credit) may control.
    assert tr["u_stirrup"] == pytest.approx(tr["torsion_fraction"], rel=1e-6)
    assert tr["governing"] == pytest.approx(max(tr["u_stirrup"], tr["u_crush"]))
    assert tr["governs"] == ("crushing" if tr["u_crush"] > tr["u_stirrup"]
                             else "stirrups")
    # Concrete remains the nominal shear route, while provided links participate
    # in the common member angle because torsion is live.
    r = at.session_state["results"]
    assert r["shear"]["nominal_resistance"]["route"] == "concrete"
    assert r["shear"]["links"]["longitudinal_shear_force"] == pytest.approx(0.0)
    assert r["combined"]["action_alone"]["v"]["evidence"][
        "nominal_route"
    ] == "concrete"
    assert r["combined"]["r_v"] == pytest.approx(
        r["combined"]["action_alone"]["v"]["demand"]
        / r["combined"]["action_alone"]["v"]["resistance"]
    )
    assert r["shear"]["links"]["theta_mode"] == "utilisation"
    assert tr["cot"] == pytest.approx(r["torsion"]["cot"])


@pytest.mark.parametrize("shear_force", (60.0, 300.0))
def test_member_angle_chord_objectives_match_retained_forces(monkeypatch, shear_force):
    # Capture the genuine minimax objectives at the chosen and adjacent angles.
    # This catches a force mismatch even when a transverse objective governs.
    original = combined.governing_strut_result
    scans = []

    def capture(evaluators, low, high, **kwargs):
        result = original(evaluators, low, high, **kwargs)
        caller = inspect.currentframe().f_back.f_code.co_name
        probes = sorted({max(low, result.cot - 0.001), result.cot,
                         min(high, result.cot + 0.001)})
        scans.append((caller, result.cot, [
            (cot, tuple(evaluator(cot) for evaluator in evaluators))
            for cot in probes
        ]))
        return result

    monkeypatch.setattr(combined, "governing_strut_result", capture)
    at = _fresh().run()
    _run_member(at, mx=275.0, v=shear_force, t=40.0)
    assert not at.exception
    inp = at.session_state["result_input_snapshot"]
    out = at.session_state["results"]
    sh, tor = out["shear"], out["torsion"]
    links = sh["links"]
    selection = links["member_angle_selection"]
    labels = selection["objective_labels"]
    candidates = links["chord_candidates"]
    assert len(candidates) == 4
    assert {(item["axis"], item["tension_low"]) for item in candidates} == {
        ("x", True), ("x", False), ("y", True), ("y", False),
    }
    assert all(item["role"] == (
        "shear_axis" if item["axis"] == "x" else "off_axis"
    ) for item in candidates)
    assert inp["plastic_case"]["id"] == links["z_source_case"] == "PL-01"
    assert out["plastic_cases"][0]["results"]["shear"] is sh
    assert len(labels) == len(set(labels))
    assert all(item["valid"] and item["conditional"] for item in candidates)
    credited = shear_force <= sh["res"]["vrd_c"]
    assert credited is (shear_force == 60.0)
    cot_star = links["res"]["cot"]

    expected_selection = result_presentation._current_member_angle_selection(
        inp, sh, tor,
    )
    assert expected_selection == selection
    assert result_presentation.provided_link_publication_assessment(
        inp, sh, torsion_result=tor,
    ).valid

    for caller in ("_run_uniaxial_capacity_checks", "_current_member_angle_selection"):
        matching = [probes for source, cot, probes in scans
                    if source == caller and abs(cot - cot_star) < 1e-12
                    and len(probes[0][1]) == len(labels)]
        assert matching, caller
        for probes in matching:
            for cot, values in probes:
                for candidate in candidates:
                    face = "negative" if candidate["tension_low"] else "positive"
                    role = ("longitudinal" if candidate["role"] == "shear_axis"
                            else "off-axis")
                    label = f"{candidate['axis']}-axis {face} {role} chord"
                    gets_shift = (candidate["role"] == "shear_axis"
                                  and candidate.get("gets_shift") is True)
                    shear_force_at = (0.0 if credited or not gets_shift
                                      else 0.5 * shear_force * cot)
                    torsion_force_at = candidate["ftd_t"] * cot / cot_star
                    mv = min(shear_force_at * candidate["z"],
                             max(candidate["m_rd"] - candidate["m_ed"], 0.0))
                    mt = torsion_force_at * candidate["z"] / 2.0
                    expected = (candidate["m_ed"] + mv + mt) / candidate["m_rd"]
                    assert values[labels.index(label)] == pytest.approx(expected)
                    if cot == cot_star:
                        assert candidate["ftd_v"] == pytest.approx(shear_force_at)
                        assert candidate["util"] == pytest.approx(expected)
    transverse = out["combined"]["transverse"]
    assert transverse["shear_credited"] is credited
    assert transverse["u_crush"] > tor["t_ed"] / tor["trd_max"]


def test_app_combined_transverse_no_credit_when_shear_high():
    # VEd > VRd,c: the stirrup carries both, so the shear share is > 0 and adds.
    at = _fresh()
    at.run()
    _run_member(at, mx=100.0, v=300.0, t=40.0)  # V above VRd,c
    assert not at.exception
    tr = at.session_state["results"]["combined"]["transverse"]
    assert tr["shear_credited"] is False
    assert tr["shear_fraction"] > 0.0


def test_app_combined_uses_one_shared_strut_band():
    # Shear and torsion use one physical compression-strut range and therefore
    # report the same member angle for every live combined check.
    at = _fresh()
    at.run()
    _run_member(
        at,
        mx=100.0,
        v=100.0,
        t=40.0,
        strut_band=(1.4, 1.8),
    )
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["transverse"]["valid"] is True
    assert c["crushing"]["valid"] is True
    shared_cot = c["transverse"]["cot"]
    assert 1.4 <= shared_cot <= 1.8
    assert at.session_state["results"]["shear"]["links"]["res"]["cot"] == pytest.approx(
        shared_cot
    )
    assert at.session_state["results"]["torsion"]["cot"] == pytest.approx(shared_cot)


def test_app_combined_is_saved_and_restored():
    import project_io
    at = _fresh()
    at.run()
    at.checkbox(key="combined_on").set_value(True).run()
    at.selectbox(key="combined_method").set_value(codes.EC2_2005.label).run()
    at.session_state["combined_mv_independent"] = True
    at.run()
    scalars = {k: at.session_state[k] for k in project_io.SCALAR_KEYS
               if k in at.session_state}
    assert scalars["combined_on"] is True
    assert scalars["combined_mv_independent"] is True
    at2 = _fresh()
    at2.run()
    at2.session_state["_pending_project"] = project_io.dump_project({}, scalars)
    at2.run()
    assert not at2.exception
    assert at2.session_state["combined_on"] is True
    assert at2.session_state["combined_method"] == codes.EC2_2005.label
    assert at2.session_state["combined_mv_independent"] is True
    assert "combined_mv_independent" not in {
        widget.key for widget in at2.checkbox
    }


def test_pub_h01_current_native_failure_rejects_isolated_candidate_inventory(
    native_member_report_cases, tmp_path,
):
    """Complete native bundles exercise both real views; this is not app navigation."""
    import hashlib
    import json
    import pickle
    from streamlit.testing.v1 import AppTest

    inp, out = copy.deepcopy(native_member_report_cases["two-face"])
    original = pickle.dumps((inp, out))
    assert result_presentation.combined_publication_evidence_is_current(inp, out) == (True, None)
    candidates = out["combined"]["longitudinal_candidates"]
    assert {(item["axis"], item["tension_low"]) for item in candidates} == {
        ("x", True), ("x", False), ("y", True), ("y", False),
    }
    failed = next(item for item in candidates if item["status"] == "FAIL")
    assert abs(failed["m_total"] / failed["m_rd"] - 2.059941571055692) < 1e-10
    runner = AppTest.from_string(
        "import streamlit as st\nimport sector_app\n"
        "inp, out = st.session_state['native_bundle']\n"
        "surface = st.radio('Result surface', ['M-V-T Combined', 'Results Overview'], key='surface')\n"
        "if surface == 'M-V-T Combined':\n    sector_app.combined_view(inp, out)\n"
        "else:\n    sector_app.results_overview_view(inp, out)\n",
        default_timeout=120,
    )
    records = []

    def inspect(label, bundle, current):
        root_input, root_output = bundle
        actual, reason = result_presentation.combined_publication_evidence_is_current(
            root_input, root_output,
        )
        assert actual is current, (label, reason)
        runner.session_state["native_bundle"] = copy.deepcopy(bundle)
        runner.session_state["surface"] = "M-V-T Combined"
        runner.run()
        assert not runner.exception
        view_metrics = [{"label": metric.label, "value": str(metric.value),
                         "delta": metric.delta} for metric in runner.metric]
        warnings = [item.value for item in runner.warning]
        if current:
            assert not any("Combined M-V-T is NOT ASSESSED" in text for text in warnings)
            for metric_label in ("Longitudinal reinforcement", "Chord utilisation"):
                metric = next(item for item in view_metrics if item["label"] == metric_label)
                assert (metric["value"], metric["delta"]) == ("206.0 %", "FAIL")
        else:
            assert any("Combined M-V-T is NOT ASSESSED" in text for text in warnings)
            assert not view_metrics
        runner.radio(key="surface").set_value("Results Overview").run()
        assert not runner.exception
        table = next(item.value for item in runner.table if "Check" in item.value)
        combined_rows = table[table["Check"].str.startswith("Combined ")]
        assert not combined_rows.empty
        if current:
            row = combined_rows[combined_rows["Check"] == "Combined longitudinal reinforcement"].iloc[0]
            assert (row["Status"], row["Result"]) == ("FAIL", "206.0 %")
        else:
            assert set(combined_rows["Status"]) == {"NOT ASSESSED"}
            assert set(combined_rows["Result"]) == {"-"}
        assessment = capacity.combined_longitudinal_assessment(root_output["combined"])
        assert assessment["status"] == assessment["chord_status"] == "FAIL"
        expected_util = failed["m_total"] / failed["m_rd"]
        assert assessment["util"] == pytest.approx(expected_util)
        assert assessment["chord_util"] == pytest.approx(expected_util)
        assert pickle.dumps(root_output["shear"]) == pickle.dumps(out["shear"])
        assert pickle.dumps(root_output["torsion"]) == pickle.dumps(out["torsion"])
        records.append({"label": label, "current": actual, "reason": reason,
                        "metrics": view_metrics,
                        "rows": combined_rows.to_dict(orient="records"),
                        "canonical": {key: assessment.get(key) for key in (
                            "status", "util", "chord_status", "chord_util", "chord_reason")},
                        "same_shear_companion": pickle.dumps(root_output["shear"]) == pickle.dumps(out["shear"]),
                        "same_torsion_companion": pickle.dumps(root_output["torsion"]) == pickle.dumps(out["torsion"])})

    inspect("current-native-206-percent", (inp, out), True)
    for label, container in (
        ("none", None), ("text", "bad"), ("integer", 7), ("boolean", True),
        ("mapping", {}), ("empty-list", []), ("empty-tuple", ()),
    ):
        altered = copy.deepcopy(out)
        altered["combined"]["longitudinal_candidates"] = container
        inspect("container-" + label, (inp, altered), False)
    for label in ("missing-list", "documented-incomplete", "none-sibling", "malformed-status"):
        altered = copy.deepcopy(out)
        combined = altered["combined"]
        if label == "missing-list":
            combined.pop("longitudinal_candidates")
        else:
            candidates = list(combined["longitudinal_candidates"])
            if label == "documented-incomplete":
                candidates = [item for item in candidates if item["status"] == "FAIL"]
                combined["longitudinal_assessment"] = dict(
                    combined["longitudinal_assessment"], coverage_complete=False,
                )
            elif label == "none-sibling":
                candidates.append(None)
            else:
                index = next(i for i, item in enumerate(candidates) if item["status"] == "PASS")
                candidates[index] = dict(candidates[index], status=["PASS"])
            combined["longitudinal_candidates"] = candidates
        inspect(label, (inp, altered), False)
    inspect("restored-native-206-percent", (inp, out), True)
    assert pickle.dumps((inp, out)) == original
    destination = tmp_path / "native-mvt-inventory.json"
    assert not destination.exists()
    destination.write_text(json.dumps({"producer_bundle_sha256": hashlib.sha256(original).hexdigest(),
                                      "records": records}, indent=2) + "\n", encoding="utf-8")
