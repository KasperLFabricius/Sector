"""Contracts for deriving heightened operands from retained crack evidence."""

from __future__ import annotations

import pytest

from app.heightened_crack_adapter import (
    derive_heightened_reinforcement,
    resolve_reference_case_name,
)


def _case_entry(*, retained_as_eff_m2: float = 0.0015) -> dict:
    return {
        "name": "SLS-2",
        "results": {
            "elastic": {
                "crack_output": {"case": "Short-term (fine)"},
                "crack_short": {
                    "as_eff": retained_as_eff_m2,
                    "effective_reinforcement": [
                        {
                            "element_type": "Bar",
                            "element_id": "B1",
                            "reinforcement_type": "mild",
                            "in_effective_area": True,
                            "effective_area_contribution_mm2": 500.0,
                            "diameter_mm": 20.0,
                            "diameter_source": "provided",
                            "modulus_mpa": 200_000.0,
                        },
                        {
                            "element_type": "Bar",
                            "element_id": "B2",
                            "reinforcement_type": "mild",
                            "in_effective_area": True,
                            "effective_area_contribution_mm2": 1_000.0,
                            "diameter_mm": 25.0,
                            "diameter_source": "equivalent-area",
                            "modulus_mpa": 190_000.0,
                        },
                        {
                            "element_type": "Tendon",
                            "element_id": "P1",
                            "reinforcement_type": "prestress",
                            "in_effective_area": True,
                            "effective_area_contribution_mm2": 150.0,
                            "diameter_mm": 14.0,
                            "diameter_source": "provided",
                            "modulus_mpa": 195_000.0,
                        },
                    ],
                },
                "elements": [
                    {
                        "element_type": "Bar",
                        "element_id": "B1",
                        "material_id": "M1",
                        "material_name": "B500B",
                        "area_mm2": 500.0,
                        "modulus_mpa": 200_000.0,
                    },
                    {
                        "element_type": "Bar",
                        "element_id": "B2",
                        "material_id": "M2",
                        "material_name": "Custom mild",
                        "area_mm2": 1_000.0,
                        "modulus_mpa": 190_000.0,
                    },
                    {
                        "element_type": "Tendon",
                        "element_id": "P1",
                        "material_id": "P1",
                        "area_mm2": 150.0,
                        "modulus_mpa": 195_000.0,
                    },
                ],
            }
        },
    }


def test_reference_is_automatic_only_for_one_crack_enabled_case():
    one = [{"name": "SLS-1", "calculate_crack_width": True}]
    many = [
        *one,
        {"name": "SLS-2", "calculate_crack_width": True},
        {"name": "SLS-3", "calculate_crack_width": False},
    ]

    assert resolve_reference_case_name(one, None) == "SLS-1"
    assert resolve_reference_case_name(many, "SLS-2") == "SLS-2"
    with pytest.raises(ValueError, match="Select one crack-enabled"):
        resolve_reference_case_name(many, "")
    with pytest.raises(ValueError, match="at least one crack-enabled"):
        resolve_reference_case_name([], None)


def test_mixed_material_derivation_retains_element_and_material_provenance():
    derived = derive_heightened_reinforcement(
        _case_entry(),
        bar_diameter_override_mm=0.0,
    )

    assert derived.reference_case_id == "SLS-2"
    assert derived.ordinary_crack_branch == "Short-term (fine)"
    assert derived.bar_diameter_mm == 25.0
    assert derived.diameter_governing_element_ids == ("B2",)
    assert derived.reinforcement_modulus_mpa == 190_000.0
    assert derived.modulus_governing_material_ids == ("M2",)
    assert derived.provided_reinforcement_area_mm2 == 1_500.0
    assert [item.element_id for item in derived.contributions] == ["B1", "B2"]
    assert [item.material_id for item in derived.contributions] == ["M1", "M2"]


def test_ordinary_diameter_override_is_verified_against_retained_candidates():
    case = _case_entry()
    for retained in case["results"]["elastic"]["crack_short"][
        "effective_reinforcement"
    ]:
        retained["diameter_mm"] = 16.0
        retained["diameter_source"] = "provided"

    derived = derive_heightened_reinforcement(
        case,
        bar_diameter_override_mm=16.0,
    )

    assert derived.bar_diameter_mm == 16.0
    assert derived.diameter_source == "ordinary crack diameter override sls_phi"
    assert derived.diameter_governing_element_ids == ("B1", "B2")


def test_missing_or_inconsistent_retained_evidence_fails_closed():
    with pytest.raises(ValueError, match="do not close"):
        derive_heightened_reinforcement(
            _case_entry(retained_as_eff_m2=0.0016),
            bar_diameter_override_mm=0.0,
        )

    missing_modulus = _case_entry()
    del missing_modulus["results"]["elastic"]["elements"][1]["modulus_mpa"]
    with pytest.raises(ValueError, match="modulus"):
        derive_heightened_reinforcement(
            missing_modulus,
            bar_diameter_override_mm=0.0,
        )
