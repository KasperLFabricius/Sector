from dataclasses import FrozenInstanceError

import pytest

from sector.elastic import (
    ModularRatioMaterial,
    ModularRatioResult,
    calculate_modular_ratios,
)


def test_modular_ratios_retain_mixed_material_order_and_exact_values() -> None:
    result = calculate_modular_ratios(
        30_000.0,
        2.0,
        (
            ("M2", "mild", 200_000.0),
            ("P1", "prestress", 195_000.0),
        ),
    )

    assert result.concrete_modulus_mpa == 30_000.0
    assert result.creep_coefficient == 2.0
    assert result.effective_concrete_modulus_mpa == 10_000.0
    assert [material.material_id for material in result.materials] == ["M2", "P1"]
    assert [material.material_family for material in result.materials] == [
        "mild",
        "prestress",
    ]
    assert result.materials[0].modulus_mpa == 200_000.0
    assert result.materials[0].short_term == pytest.approx(20.0 / 3.0)
    assert result.materials[0].long_term == pytest.approx(20.0)
    assert result.materials[1].modulus_mpa == 195_000.0
    assert result.materials[1].short_term == pytest.approx(6.5)
    assert result.materials[1].long_term == pytest.approx(19.5)


def test_modular_ratio_records_are_frozen_and_slotted() -> None:
    material = ModularRatioMaterial("M1", "mild", 200_000.0, 6.25, 12.5)
    result = ModularRatioResult(32_000.0, 1.0, 16_000.0, (material,))

    assert not hasattr(material, "__dict__")
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        material.short_term = 1.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.creep_coefficient = 2.0  # type: ignore[misc]


@pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan")])
def test_modular_ratios_reject_invalid_concrete_modulus(value: float) -> None:
    with pytest.raises(ValueError, match="concrete modulus"):
        calculate_modular_ratios(value, 1.0, ())


@pytest.mark.parametrize("value", [-0.1, float("inf"), float("nan")])
def test_modular_ratios_reject_invalid_creep_coefficient(value: float) -> None:
    with pytest.raises(ValueError, match="creep coefficient"):
        calculate_modular_ratios(30_000.0, value, ())


@pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan")])
def test_modular_ratios_reject_invalid_material_modulus(value: float) -> None:
    with pytest.raises(ValueError, match="material modulus"):
        calculate_modular_ratios(30_000.0, 1.0, (("M1", "mild", value),))
