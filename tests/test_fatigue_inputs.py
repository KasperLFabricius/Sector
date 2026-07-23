import math

import pandas as pd
import pytest

from app import fatigue_inputs as fi


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
