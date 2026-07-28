import math

import numpy as np
import pandas as pd
import pytest

from app import fatigue_inputs as fi
from sector import conformance


@pytest.mark.parametrize(
    ("edition", "gamma_s", "gamma_c"),
    [
        (fi.EC2_2005, 1.15, 1.50),
        (fi.EC2_2005_DKNA, 1.32, 1.595),
        (fi.EC2_2_2005_AC, 1.15, 1.50),
        (fi.EC2_2023, 1.15, 1.50),
    ],
)
def test_edition_factor_presets_resolve_expected_unity_category_values(
    edition, gamma_s, gamma_c
):
    basis = fi.fatigue_factor_preset(edition)

    assert basis["gamma_s"] == pytest.approx(gamma_s)
    assert basis["gamma_c"] == pytest.approx(gamma_c)
    assert basis["reference"]


def test_dk_fatigue_factor_derivation_exposes_every_multiplier():
    basis = fi.fatigue_factor_preset(
        fi.EC2_2005_DKNA,
        gamma0=0.95,
        gamma3=1.10,
    )

    expected_s = 1.20 * 1.10 * 0.95 * 1.10
    expected_c = 1.45 * 1.10 * 0.95 * 1.10
    assert basis["gamma_s"] == pytest.approx(expected_s)
    assert basis["gamma_c"] == pytest.approx(expected_c)
    assert basis["gamma_s_derivation"] == (
        f"1.20 x 1.10 x 0.950 x 1.100 = {expected_s:.3f}"
    )
    assert basis["gamma_c_derivation"] == (
        f"1.45 x 1.10 x 0.950 x 1.100 = {expected_c:.3f}"
    )


def test_approved_fatigue_override_survives_edition_switches_unchanged():
    finals = []
    for edition in fi.EDITIONS:
        gamma_s, gamma_c, basis = fi.resolve_fatigue_factors(
            edition,
            mode=fi.FACTOR_MODE_OVERRIDE,
            gamma_s=1.27,
            gamma_c=1.61,
            gamma0=0.95,
            gamma3=1.10,
            approval_reference="DB-FACT-01 / checker A",
        )
        finals.append((gamma_s, gamma_c))
        assert basis["gamma_s_derivation"] == (
            "approved custom final override = 1.270"
        )
        assert basis["gamma_c_derivation"] == (
            "approved custom final override = 1.610"
        )

    assert all(
        gamma_s == pytest.approx(1.27)
        and gamma_c == pytest.approx(1.61)
        for gamma_s, gamma_c in finals
    )


@pytest.mark.parametrize("value", [0.5, 2.0])
def test_positive_custom_material_factors_are_preserved_without_clamping(value):
    gamma_s, gamma_c, review_basis = fi.resolve_fatigue_factors(
        fi.EC2_2_2005_AC,
        mode=fi.FACTOR_MODE_PRESET,
        gamma_s=value,
        gamma_c=value,
    )
    approved_s, approved_c, approved_basis = fi.resolve_fatigue_factors(
        fi.EC2_2_2005_AC,
        mode=fi.FACTOR_MODE_OVERRIDE,
        gamma_s=value,
        gamma_c=value,
        approval_reference="DB-FACT-02 / checker B",
    )

    assert (gamma_s, gamma_c) == pytest.approx((value, value))
    assert (
        review_basis["conformance"]["state"]
        == conformance.STATE_REVIEW
    )
    assert (approved_s, approved_c) == pytest.approx((value, value))
    assert (
        approved_basis["conformance"]["state"]
        == conformance.STATE_APPROVED_CUSTOM
    )
    assert (
        approved_basis["parameter_conformance"]["gamma_s"]["actual_value"]
        == value
    )


def test_custom_factor_without_approval_calculates_but_requires_review():
    gamma_s, gamma_c, basis = fi.resolve_fatigue_factors(
        fi.EC2_2_2005_AC,
        mode=fi.FACTOR_MODE_OVERRIDE,
        gamma_s=0.5,
        gamma_c=2.0,
        approval_reference="",
    )

    assert (gamma_s, gamma_c) == pytest.approx((0.5, 2.0))
    assert basis["conformance"]["state"] == conformance.STATE_REVIEW
    assert all(
        record["state"] == conformance.STATE_REVIEW
        for record in basis["parameter_conformance"].values()
    )


def test_factor_approval_metadata_must_be_typed_text():
    with pytest.raises(ValueError, match="must be typed text"):
        fi.resolve_fatigue_factors(
            fi.EC2_2_2005_AC,
            mode=fi.FACTOR_MODE_OVERRIDE,
            gamma_s=0.5,
            gamma_c=2.0,
            approval_reference=True,
        )


def test_legacy_fatigue_values_are_retained_but_identified_for_review():
    gamma_s, gamma_c, basis = fi.resolve_fatigue_factors(
        fi.EC2_2005_DKNA,
        mode=fi.FACTOR_MODE_LEGACY,
        gamma_s=1.15,
        gamma_c=1.50,
    )

    assert (gamma_s, gamma_c) == pytest.approx((1.15, 1.50))
    assert basis["legacy_review_required"] is True
    assert "review required" in basis["gamma_s_derivation"]


@pytest.mark.parametrize("boolean_value", [True, np.bool_(True)])
def test_fatigue_factor_resolvers_reject_boolean_numbers(boolean_value):
    with pytest.raises(ValueError, match="Boolean values are not accepted"):
        fi.fatigue_factor_preset(
            fi.EC2_2005_DKNA,
            gamma0=boolean_value,
        )
    with pytest.raises(ValueError, match="Boolean values are not accepted"):
        fi.fatigue_factor_preset(
            fi.EC2_2005_DKNA,
            gamma3=boolean_value,
        )
    with pytest.raises(ValueError, match="Boolean values are not accepted"):
        fi.resolve_fatigue_factors(
            fi.EC2_2005_DKNA,
            mode=fi.FACTOR_MODE_OVERRIDE,
            gamma_s=boolean_value,
            gamma_c=1.595,
        )
    with pytest.raises(ValueError, match="Boolean values are not accepted"):
        fi.resolve_fatigue_factors(
            fi.EC2_2005_DKNA,
            mode=fi.FACTOR_MODE_OVERRIDE,
            gamma_s=1.32,
            gamma_c=boolean_value,
        )


def test_builtin_detail_presets_match_the_two_eurocode_editions():
    old_bar = fi.default_entry(preset=fi.PRESET_2005_BARS)
    new_bar = fi.default_entry(preset=fi.PRESET_2023_BARS)
    old_plastic_tendon = fi.default_entry(
        preset=fi.PRESET_2005_PLASTIC_TENDON
    )
    new_plastic_tendon = fi.default_entry(
        preset=fi.PRESET_2023_PLASTIC_TENDON
    )
    new_curved_steel_duct = fi.default_entry(
        preset=fi.PRESET_2023_STEEL_CURVED
    )

    assert (
        old_bar["n_star"],
        old_bar["k1"],
        old_bar["k2"],
        old_bar["delta_sigma_rsk_mpa"],
    ) == (1e6, 5.0, 9.0, 162.5)
    assert new_bar["n_star"] == 2e6
    assert new_bar["stress_model"] == fi.EC2_2023_BAR_STRESS
    assert old_plastic_tendon["k2"] == 10.0
    assert new_plastic_tendon["k2"] == 9.0
    assert new_curved_steel_duct["k1"] == 3.0


def test_named_detail_preset_retains_edition_only_while_values_match():
    entry = fi.default_entry(preset=fi.PRESET_2023_BARS)
    entry["mandrel_diameter_mm"] = 80.0
    entry["bond_ratio_xi"] = 0.7
    unchanged = fi.normalise_catalog({"items": [entry]})["items"][0]

    assert unchanged["preset"] == fi.PRESET_2023_BARS
    assert fi.preset_edition(unchanged["preset"]) == fi.EC2_2023

    entry["n_star"] = 3.0e6
    custom = fi.normalise_catalog({"items": [entry]})["items"][0]

    assert custom["preset"] == fi.CUSTOM_PRESET
    assert fi.preset_edition(custom["preset"]) is None
    assert custom["n_star"] == 3.0e6


@pytest.mark.parametrize(
    ("diameter", "expected"),
    [(10.0, 160.0), (12.0, 160.0), (14.0, 140.0),
     (16.0, 140.0), (20.0, 130.0), (32.0, 130.0)],
)
def test_2023_bar_reference_range_is_diameter_dependent(diameter, expected):
    entry = fi.default_entry(preset=fi.PRESET_2023_BARS)
    assert fi.characteristic_stress_range(entry, diameter) == expected


def test_bent_bar_factor_uses_mandrel_ratio_and_cannot_exceed_straight_bar():
    entry = fi.default_entry(preset=fi.PRESET_2005_BENT_BARS)
    entry["mandrel_diameter_mm"] = 80.0

    assert fi.bend_reduction_factor(entry, 16.0) == pytest.approx(0.48)

    entry["mandrel_diameter_mm"] = 1000.0
    assert fi.bend_reduction_factor(entry, 16.0) == 1.0


def test_catalogue_ids_are_stable_and_never_reused():
    catalogue, second = fi.add_entry(fi.default_catalog())
    catalogue, third = fi.duplicate_entry(catalogue, "F1")
    catalogue = fi.delete_entry(catalogue, second)
    catalogue, fourth = fi.add_entry(catalogue)

    assert (second, third, fourth) == ("F2", "F3", "F4")
    assert fi.detail_ids(catalogue) == ["F1", "F3", "F4"]


def test_catalogue_delete_rejects_last_or_assigned_detail():
    with pytest.raises(ValueError, match="at least one"):
        fi.delete_entry(fi.default_catalog(), "F1")

    catalogue, _ = fi.add_entry(fi.default_catalog())
    with pytest.raises(ValueError, match="assigned"):
        fi.delete_entry(catalogue, "F1", assigned_ids=["F1"])


def test_catalogue_repairs_duplicate_ids_and_checks_assignment_kind():
    raw = {
        "items": [
            {**fi.default_entry(), "id": "F4"},
            {**fi.default_entry(preset=fi.PRESET_2023_PRETENSION), "id": "F4"},
            {**fi.default_entry(), "id": "bad"},
        ]
    }
    catalogue = fi.normalise_catalog(raw)

    assert fi.detail_ids(catalogue) == ["F4", "F5", "F6"]
    assert fi.invalid_assignments(["", "F4"], catalogue, fi.MILD) == []
    assert fi.invalid_assignments(["F5"], catalogue, fi.MILD) == ["F5"]
    assert fi.invalid_assignments(["F5"], catalogue, fi.PRESTRESS) == []


def test_catalogue_validation_requires_positive_curve_data_and_mandrel():
    entry = fi.default_entry(preset=fi.PRESET_2023_BENT_BARS)
    entry["n_star"] = 0.0
    catalogue = {"items": [entry]}

    errors = fi.catalog_errors(catalogue)

    assert "F1: n_star must be greater than zero" in errors
    assert any("mandrel_diameter_mm" in error for error in errors)


def test_tendon_bond_inputs_are_explicit_optional_catalogue_properties():
    entry = fi.default_entry(preset=fi.PRESET_2023_PRETENSION)
    assert entry["bond_ratio_xi"] == 0.0
    assert entry["bond_equivalent_diameter_mm"] == 0.0

    entry["bond_ratio_xi"] = 0.7
    entry["bond_equivalent_diameter_mm"] = 12.5
    restored = fi.normalise_catalog({"items": [entry]})["items"][0]

    assert restored["bond_ratio_xi"] == 0.7
    assert restored["bond_equivalent_diameter_mm"] == 12.5


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("n_star", "bad", "n_star must be a finite number"),
        ("k1", math.inf, "k1 must be a finite number"),
        ("kind", "cable", "kind must be mild or prestress"),
        ("stress_model", "other", "unknown stress_model"),
        ("bend_reduction", "false", "bend_reduction must be true or false"),
    ],
)
def test_catalogue_rejects_explicit_malformed_engineering_fields(
    field, value, message
):
    entry = fi.default_entry(preset=fi.PRESET_2023_BENT_BARS)
    entry[field] = value

    with pytest.raises(ValueError, match=message):
        fi.normalise_catalog({"items": [entry]})


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"items": "bad"}, "items must be a non-empty list"),
        ({"items": 42}, "items must be a non-empty list"),
        ({"items": None}, "items must be a non-empty list"),
        ({"items": {}}, "items must be a non-empty list"),
        ({"items": []}, "items must be a non-empty list"),
        ({}, "items must be a non-empty list"),
        ({"items": ["bad"]}, "items must contain only objects"),
    ],
)
def test_catalogue_rejects_malformed_item_containers(value, message):
    with pytest.raises(ValueError, match=message):
        fi.normalise_catalog(value)


def test_replace_entry_applies_the_same_strict_field_validation():
    entry = fi.default_entry()
    entry["n_star"] = "bad"

    with pytest.raises(ValueError, match="n_star must be a finite number"):
        fi.replace_entry(fi.default_catalog(), entry)


def test_authority_basis_is_metadata_with_method_specific_qa_warnings():
    basis = fi.normalise_basis({
        "authority": fi.AUTHORITY_BN_NEW,
        "method": fi.METHOD_BN_NEW_2,
        "spectrum_source": "Prescribed traffic set",
        "cycle_count_source": "BN traffic composition",
        "dynamic_effects": fi.DYNAMIC_INCLUDED,
        "cycle_counting": fi.COUNTING_OTHER,
        "concurrence_basis": "",
        "atypical_traffic": fi.ATYPICAL_NOT_APPLICABLE,
        "authority_adjustments": "",
    })

    warnings = fi.basis_warnings(basis)

    assert "Selected BN1-59-5 method requires rainflow counting" in warnings
    assert "Lane/track concurrence basis is not stated" in warnings
    assert (
        "BN prescribed-traffic source/approval reference is not stated"
        in warnings
    )
    assert "Authority load/cycle adjustments are not stated" in warnings
    assert fi.method_requires_single_bin(fi.METHOD_BN_NEW_1) is True
    assert fi.method_requires_single_bin(fi.METHOD_BN_NEW_2) is False


def test_authority_basis_rejects_cross_authority_method_and_unknown_status():
    with pytest.raises(ValueError, match="is not available"):
        fi.normalise_basis({
            "authority": fi.AUTHORITY_VD,
            "method": fi.METHOD_BN_EXISTING_4,
        })
    with pytest.raises(ValueError, match="unknown dynamic-effects status"):
        fi.normalise_basis({"dynamic_effects": "Maybe"})


def _spectrum_rows():
    return [
        {
            "spectrum": "Traffic A",
            "name": "A-01",
            "description": "High range",
            "cycles": 2.5e5,
            "n_long_ed_kn": -1000.0,
            "mx_long_ed_knm": 250.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 200.0,
            "mx_short_ed_knm": 100.0,
            "my_short_ed_knm": 20.0,
        },
        {
            "spectrum": "Traffic A",
            "name": "A-02",
            "description": "Low range",
            "cycles": 1.5e6,
            "n_long_ed_kn": -1000.0,
            "mx_long_ed_knm": 250.0,
            "n_short_ed_kn": 50.0,
            "mx_short_ed_knm": 25.0,
        },
        {
            "spectrum": "Traffic B",
            "name": "B-01",
            "cycles": 4e5,
            "n_short_ed_kn": -75.0,
        },
    ]


def test_spectrum_normalisation_records_and_groups_are_lossless():
    table = fi.normalise_spectrum_table(_spectrum_rows())
    records = fi.spectrum_records(table)
    restored = fi.spectrum_from_records(records)

    assert list(restored.columns) == list(fi.SPECTRUM_COLUMNS)
    assert all(
        pd.api.types.is_float_dtype(restored[column])
        for column in fi.SPECTRUM_NUMERIC
    )
    assert records == fi.spectrum_records(restored)
    assert list(fi.spectrum_groups(restored)) == ["Traffic A", "Traffic B"]
    assert len(fi.spectrum_groups(restored)["Traffic A"]) == 2


def test_blank_spectrum_rows_are_ignored_but_invalid_active_values_are_retained():
    table = fi.normalise_spectrum_table([
        {},
        {"spectrum": "S1", "name": "B1", "cycles": "bad"},
    ])

    active = fi.active_spectrum_table(table)

    assert len(active) == 1
    assert math.isnan(active.loc[0, "cycles"])
    assert fi.spectrum_errors(active) == [
        "Fatigue row 1: cycles must be greater than zero"
    ]
    with pytest.raises(ValueError, match="cycles must be finite"):
        fi.spectrum_records(active)


def test_invalid_numeric_only_row_is_not_silently_discarded():
    table = fi.normalise_spectrum_table([{"cycles": "bad"}])

    active = fi.active_spectrum_table(table)

    assert len(active) == 1
    assert fi.spectrum_errors(active) == [
        "Fatigue row 1: Spectrum is required",
        "Fatigue row 1: Name is required",
        "Fatigue row 1: cycles must be greater than zero",
    ]


def test_spectrum_validation_requires_group_unique_name_and_positive_cycles():
    rows = [
        {"spectrum": "", "name": "EL-01", "cycles": 0.0},
        {"spectrum": "S1", "name": "bin", "cycles": -2.0},
        {"spectrum": "S1", "name": "BIN", "cycles": 10.0},
    ]

    errors = fi.spectrum_errors(rows, existing_case_names=["EL-01"])

    assert "Fatigue row 1: Spectrum is required" in errors
    assert "Case name 'EL-01' is duplicated; names must be unique" in errors
    assert "Fatigue row 1: cycles must be greater than zero" in errors
    assert "Fatigue row 2: cycles must be greater than zero" in errors
    assert "Case name 'BIN' is duplicated; names must be unique" in errors


def test_spectrum_requires_a_row_only_when_fatigue_is_enabled():
    assert fi.spectrum_errors(None) == []
    assert fi.spectrum_errors(None, require_rows=True) == [
        "At least one fatigue spectrum bin is required"
    ]


def test_spectrum_case_collisions_are_reported_and_never_split_damage_groups():
    rows = [
        {"spectrum": "Traffic", "name": "FAT-01", "cycles": 1e5},
        {"spectrum": "traffic", "name": "FAT-02", "cycles": 2e5},
    ]

    errors = fi.spectrum_errors(rows)
    groups = fi.spectrum_groups(rows)

    assert errors == [
        "Fatigue row 2: Spectrum 'traffic' differs only by case from "
        "'Traffic'; use one spelling"
    ]
    assert list(groups) == ["Traffic"]
    assert [row["name"] for row in groups["Traffic"]] == ["FAT-01", "FAT-02"]
