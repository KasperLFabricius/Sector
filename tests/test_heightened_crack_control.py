"""Independent numerical contracts for DK NA Formula 7.100 NA."""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from sector.design_standards import DesignBasisKey
from sector.heightened_crack_control import (
    CrackSystem,
    HeightenedCrackControlResult,
    HeightenedCrackControlStatus,
    ReinforcementSurface,
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
