"""Independent numerical contracts for DK NA Formula 7.100 NA."""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from sector.design_standards import DesignBasisKey
from sector.heightened_crack_control import (
    CrackSystem,
    DualHeightenedCrackControlResult,
    HeightenedCrackControlResult,
    HeightenedCrackControlStatus,
    ReinforcementSurface,
    calculate_dual_heightened_crack_control,
    calculate_heightened_crack_control,
)

DK_BASIS = DesignBasisKey.FIRST_GEN_DK_NA_2024
BASE_INPUTS = {
    "basis": DK_BASIS,
    "crack_system": CrackSystem.FINE,
    "reinforcement_surface": ReinforcementSurface.RIBBED,
    "bar_diameter_mm": 16.0,
    "effective_tensile_strength_mpa": 2.9,
    "reinforcement_modulus_mpa": 200_000.0,
    "permitted_crack_width_mm": 0.2,
    "effective_tension_area_mm2": 120_000.0,
    "provided_reinforcement_area_mm2": 2_500.0,
}
NUMERIC_INPUTS = (
    "bar_diameter_mm",
    "effective_tensile_strength_mpa",
    "reinforcement_modulus_mpa",
    "permitted_crack_width_mm",
    "effective_tension_area_mm2",
    "provided_reinforcement_area_mm2",
)


def _calculate(**changes: object) -> HeightenedCrackControlResult:
    inputs = {**BASE_INPUTS, **changes}
    return calculate_heightened_crack_control(**inputs)


def test_fine_ribbed_benchmark_retains_every_operand_and_identity():
    result = _calculate()

    # Independent hand benchmark:
    # sqrt(16*2.9/(4*200000*1*0.2)) = 0.0170293863659264.
    assert result.base_reinforcement_ratio == pytest.approx(
        0.0170293863659264,
        rel=1e-14,
    )
    assert result.required_reinforcement_ratio == pytest.approx(
        0.0170293863659264,
        rel=1e-14,
    )
    assert result.required_reinforcement_area_mm2 == pytest.approx(
        2043.5263639111681,
        rel=1e-14,
    )
    assert result.comparison_ratio == pytest.approx(
        0.8174105455644672,
        rel=1e-14,
    )
    assert result.crack_system_factor == 1.0
    assert result.reinforcement_surface_multiplier == 1.0
    assert result.status is (
        HeightenedCrackControlStatus.PROVIDED_AREA_AT_LEAST_CALCULATED_REQUIREMENT
    )

    assert result.basis_key is DK_BASIS
    assert result.crack_system is CrackSystem.FINE
    assert result.reinforcement_surface is ReinforcementSurface.RIBBED
    assert result.bar_diameter_mm == 16.0
    assert result.effective_tensile_strength_mpa == 2.9
    assert result.reinforcement_modulus_mpa == 200_000.0
    assert result.permitted_crack_width_mm == 0.2
    assert result.effective_tension_area_mm2 == 120_000.0
    assert result.provided_reinforcement_area_mm2 == 2_500.0
    assert result.source == (
        "DS/EN 1992-1-1 DK NA:2024, supplementary provision to "
        "7.3.2(1)P, Formula 7.100 NA"
    )
    assert "user-selected" in result.disclosure
    assert "does not infer" in result.disclosure
    assert result.formula_identity == "Formula 7.100 NA"


def test_coarse_ribbed_benchmark_uses_k_two_inside_complete_radical():
    result = _calculate(
        crack_system="coarse",
        provided_reinforcement_area_mm2=1_500.0,
    )

    # Independent hand benchmark with k=2 under the radical.
    assert result.crack_system is CrackSystem.COARSE
    assert result.crack_system_factor == 2.0
    assert result.base_reinforcement_ratio == pytest.approx(
        0.012041594578792296,
        rel=1e-14,
    )
    assert result.required_reinforcement_ratio == pytest.approx(
        0.012041594578792296,
        rel=1e-14,
    )
    assert result.required_reinforcement_area_mm2 == pytest.approx(
        1444.9913494550756,
        rel=1e-14,
    )
    assert result.comparison_ratio == pytest.approx(
        0.9633275663033837,
        rel=1e-14,
    )


def test_smooth_multiplier_applies_outside_the_complete_base_ratio():
    result = _calculate(
        reinforcement_surface="smooth",
        provided_reinforcement_area_mm2=2_800.0,
    )

    # Independent hand benchmark: sqrt(2)*0.0170293863659264.
    assert result.reinforcement_surface is ReinforcementSurface.SMOOTH
    assert result.reinforcement_surface_multiplier == pytest.approx(
        1.4142135623730951,
        rel=1e-14,
    )
    assert result.base_reinforcement_ratio == pytest.approx(
        0.0170293863659264,
        rel=1e-14,
    )
    assert result.required_reinforcement_ratio == pytest.approx(
        0.024083189157584593,
        rel=1e-14,
    )
    assert result.required_reinforcement_area_mm2 == pytest.approx(
        2889.982698910151,
        rel=1e-14,
    )
    assert result.comparison_ratio == pytest.approx(
        1.0321366781821968,
        rel=1e-14,
    )
    assert result.status is (
        HeightenedCrackControlStatus.PROVIDED_AREA_BELOW_CALCULATED_REQUIREMENT
    )


def test_dual_visual_source_benchmark_closes_fine_coarse_and_smooth_routes():
    common = {
        "permitted_crack_width_mm": 0.30,
        "effective_tension_area_mm2": 60_000.0,
        "provided_reinforcement_area_mm2": 1_600.0,
    }
    fine = _calculate(**common)
    coarse = _calculate(crack_system="coarse", **common)
    smooth = _calculate(reinforcement_surface="smooth", **common)
    smooth_coarse = _calculate(
        crack_system="coarse",
        reinforcement_surface="smooth",
        **common,
    )

    assert fine.base_reinforcement_ratio == pytest.approx(
        0.01390443574307614,
        rel=0.0,
        abs=1e-12,
    )
    assert fine.required_reinforcement_ratio == pytest.approx(
        0.01390443574307614,
        rel=0.0,
        abs=1e-12,
    )
    assert fine.required_reinforcement_area_mm2 == pytest.approx(
        834.26614458456845,
        rel=0.0,
        abs=1e-9,
    )
    assert fine.comparison_ratio == pytest.approx(
        0.52141634036535534,
        rel=0.0,
        abs=1e-12,
    )

    assert coarse.base_reinforcement_ratio == pytest.approx(
        0.00983192080250175,
        rel=0.0,
        abs=1e-12,
    )
    assert coarse.required_reinforcement_ratio == pytest.approx(
        0.00983192080250175,
        rel=0.0,
        abs=1e-12,
    )
    assert coarse.required_reinforcement_area_mm2 == pytest.approx(
        589.91524815010496,
        rel=0.0,
        abs=1e-9,
    )
    assert coarse.comparison_ratio == pytest.approx(
        0.3686970300938156,
        rel=0.0,
        abs=1e-12,
    )

    assert smooth.base_reinforcement_ratio == pytest.approx(
        fine.base_reinforcement_ratio,
        rel=0.0,
        abs=1e-15,
    )
    assert smooth.required_reinforcement_ratio == pytest.approx(
        0.019663841605003504,
        rel=0.0,
        abs=1e-12,
    )
    assert smooth.required_reinforcement_area_mm2 == pytest.approx(
        1179.8304963002101,
        rel=0.0,
        abs=1e-9,
    )
    assert smooth.comparison_ratio == pytest.approx(
        0.73739406018763132,
        rel=0.0,
        abs=1e-12,
    )

    assert smooth.required_reinforcement_ratio / (
        fine.required_reinforcement_ratio
    ) == pytest.approx(math.sqrt(2.0), rel=0.0, abs=1e-15)
    assert fine.required_reinforcement_ratio / (
        coarse.required_reinforcement_ratio
    ) == pytest.approx(math.sqrt(2.0), rel=0.0, abs=1e-15)
    assert smooth_coarse.base_reinforcement_ratio == pytest.approx(
        coarse.base_reinforcement_ratio,
        rel=0.0,
        abs=1e-15,
    )
    assert smooth_coarse.required_reinforcement_ratio == pytest.approx(
        fine.required_reinforcement_ratio,
        rel=0.0,
        abs=1e-15,
    )
    assert smooth_coarse.required_reinforcement_area_mm2 == pytest.approx(
        834.26614458456845,
        rel=0.0,
        abs=1e-9,
    )
    assert smooth_coarse.comparison_ratio == pytest.approx(
        0.52141634036535534,
        rel=0.0,
        abs=1e-12,
    )


def test_dual_api_retains_both_systems_and_publishes_governing_comparison():
    result = calculate_dual_heightened_crack_control(
        basis=DK_BASIS,
        reinforcement_surface="ribbed",
        bar_diameter_mm=16.0,
        effective_tensile_strength_mpa=2.9,
        reinforcement_modulus_mpa=200_000.0,
        permitted_crack_width_mm=0.2,
        fine_effective_tension_area_mm2=60_000.0,
        coarse_effective_tension_area_mm2=100_000.0,
        provided_reinforcement_area_mm2=1_600.0,
    )

    assert isinstance(result, DualHeightenedCrackControlResult)
    assert result.fine.crack_system is CrackSystem.FINE
    assert result.coarse.crack_system is CrackSystem.COARSE
    assert result.fine.effective_tension_area_mm2 == 60_000.0
    assert result.coarse.effective_tension_area_mm2 == 100_000.0
    assert result.governing_crack_system is CrackSystem.COARSE
    assert result.governing_required_reinforcement_area_mm2 == (
        result.coarse.required_reinforcement_area_mm2
    )
    assert result.governing_comparison_ratio == result.coarse.comparison_ratio
    assert result.governing_status is result.coarse.status


def test_dual_api_near_threshold_uses_true_larger_ratio_not_tolerance_tie():
    epsilon = 5.0e-13
    result = calculate_dual_heightened_crack_control(
        basis=DK_BASIS,
        reinforcement_surface="ribbed",
        bar_diameter_mm=4.0,
        effective_tensile_strength_mpa=1.0,
        reinforcement_modulus_mpa=1.0,
        permitted_crack_width_mm=1.0,
        fine_effective_tension_area_mm2=1_000.0 * (1.0 - epsilon),
        coarse_effective_tension_area_mm2=(
            1_000.0 * (1.0 + epsilon) / math.sqrt(0.5)
        ),
        provided_reinforcement_area_mm2=1_000.0,
    )

    assert result.fine.comparison_ratio < 1.0
    assert result.coarse.comparison_ratio > 1.0
    assert result.governing_crack_system is CrackSystem.COARSE
    assert result.governing_status is (
        HeightenedCrackControlStatus.PROVIDED_AREA_BELOW_CALCULATED_REQUIREMENT
    )


def test_exact_area_tie_is_at_least_the_calculated_requirement():
    result = _calculate(
        bar_diameter_mm=4.0,
        effective_tensile_strength_mpa=1.0,
        reinforcement_modulus_mpa=1.0,
        permitted_crack_width_mm=1.0,
        effective_tension_area_mm2=10.0,
        provided_reinforcement_area_mm2=10.0,
    )

    assert result.base_reinforcement_ratio == 1.0
    assert result.required_reinforcement_ratio == 1.0
    assert result.required_reinforcement_area_mm2 == 10.0
    assert result.comparison_ratio == 1.0
    assert result.status.value == ("PROVIDED AREA AT LEAST CALCULATED REQUIREMENT")


@pytest.mark.parametrize("field", NUMERIC_INPUTS)
@pytest.mark.parametrize(
    "invalid",
    (0.0, -1.0, math.nan, math.inf, -math.inf, True, False, "1.0", None),
)
def test_every_numeric_operand_must_be_positive_finite_and_not_boolean(
    field: str,
    invalid: object,
):
    with pytest.raises(ValueError, match="positive finite real number"):
        _calculate(**{field: invalid})


@pytest.mark.parametrize(
    ("field", "invalid", "message"),
    (
        ("crack_system", "Fine", "exactly 'fine' or 'coarse'"),
        ("crack_system", "fine ", "exactly 'fine' or 'coarse'"),
        ("crack_system", True, "exactly 'fine' or 'coarse'"),
        (
            "reinforcement_surface",
            "Ribbed",
            "exactly 'ribbed' or 'smooth'",
        ),
        (
            "reinforcement_surface",
            "smooth ",
            "exactly 'ribbed' or 'smooth'",
        ),
        (
            "reinforcement_surface",
            False,
            "exactly 'ribbed' or 'smooth'",
        ),
    ),
)
def test_crack_and_surface_enums_are_exact(
    field: str,
    invalid: object,
    message: str,
):
    with pytest.raises(ValueError, match=message):
        _calculate(**{field: invalid})


@pytest.mark.parametrize(
    "basis",
    (
        DesignBasisKey.FIRST_GEN_BASE,
        DesignBasisKey.PUBLISHED_2023,
    ),
)
def test_formula_is_unavailable_outside_first_generation_dk_na_2024(
    basis: DesignBasisKey,
):
    with pytest.raises(ValueError, match="implemented only"):
        _calculate(basis=basis)


def test_result_family_is_frozen_and_slotted():
    result = _calculate()

    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.comparison_ratio = 0.0
