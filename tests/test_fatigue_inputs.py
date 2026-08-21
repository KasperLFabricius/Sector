import math

import pandas as pd
import pytest

from app import fatigue_inputs as fi
from sector.design_standards import DesignBasisKey


_FIRST_GEN_SOURCE = (
    "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 6.8.6(1)-(2), "
    "recommended values"
)
_FIRST_GEN_DK_SOURCE = (
    "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 6.8.6(1)-(2), "
    "with DS/EN 1992-1-1 DK NA:2024, 6.8.6(1) unchanged"
)
_PUBLISHED_2023_SOURCE = "DS/EN 1992-1-1:2023, 10.4(1)"


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


@pytest.mark.parametrize(
    (
        "preset", "basis", "diameter", "detail_class", "threshold",
        "range_basis", "source", "cycles",
    ),
    [
        (fi.PRESET_2005_BARS, DesignBasisKey.FIRST_GEN_BASE, 16.0,
         "unwelded straight reinforcing bar", 70.0, "characteristic",
         _FIRST_GEN_SOURCE, None),
        (fi.PRESET_2005_BENT_BARS, DesignBasisKey.FIRST_GEN_DK_NA_2024,
         16.0, "unwelded bent reinforcing bar", 70.0, "characteristic",
         _FIRST_GEN_DK_SOURCE, None),
        (fi.PRESET_2005_WELDED, DesignBasisKey.FIRST_GEN_BASE, 16.0,
         "welded reinforcing bar or fabric", 35.0, "characteristic",
         _FIRST_GEN_SOURCE, None),
        (fi.PRESET_2023_BARS, DesignBasisKey.PUBLISHED_2023, 12.0,
         "unwelded straight reinforcing bar", 90.0, "design",
         _PUBLISHED_2023_SOURCE, 1.0e8),
        (fi.PRESET_2023_BARS, DesignBasisKey.PUBLISHED_2023, 12.000001,
         "unwelded straight reinforcing bar", 73.0, "design",
         _PUBLISHED_2023_SOURCE, 1.0e8),
        (fi.PRESET_2023_WELDED, DesignBasisKey.PUBLISHED_2023, 12.0,
         "butt or tack welded reinforcing bar or fabric", 40.0, "design",
         _PUBLISHED_2023_SOURCE, 1.0e8),
        (fi.PRESET_2023_WELDED, DesignBasisKey.PUBLISHED_2023, 12.000001,
         "butt or tack welded reinforcing bar or fabric", 30.0, "design",
         _PUBLISHED_2023_SOURCE, 1.0e8),
        (fi.PRESET_2023_COUPLERS, DesignBasisKey.PUBLISHED_2023, 20.0,
         "reinforcing-steel coupler", 19.0, "design",
         _PUBLISHED_2023_SOURCE, 1.0e8),
        (fi.PRESET_2023_PRETENSION, DesignBasisKey.PUBLISHED_2023, 15.7,
         "pretensioning steel", 95.0, "design",
         _PUBLISHED_2023_SOURCE, 1.0e8),
        (fi.PRESET_2023_PLASTIC_STRAND, DesignBasisKey.PUBLISHED_2023, 15.7,
         "single strand in plastic duct", 95.0, "design",
         _PUBLISHED_2023_SOURCE, 1.0e8),
        (fi.PRESET_2023_PLASTIC_TENDON, DesignBasisKey.PUBLISHED_2023, 15.7,
         "tendon in plastic duct", 80.0, "design",
         _PUBLISHED_2023_SOURCE, 1.0e8),
        (fi.PRESET_2023_STEEL_CURVED, DesignBasisKey.PUBLISHED_2023, 15.7,
         "curved tendon in steel duct", 55.0, "design",
         _PUBLISHED_2023_SOURCE, 1.0e8),
    ],
)
def test_simplified_reinforcement_screen_named_mapping(
    preset, basis, diameter, detail_class, threshold, range_basis, source,
    cycles,
):
    entry = fi.default_entry(preset=preset)

    rule = fi.simplified_reinforcement_screen_rule(entry, diameter, basis)

    assert rule["detail_class"] == detail_class
    assert rule["threshold_mpa"] == pytest.approx(threshold)
    assert rule["range_basis"] == range_basis
    assert rule["max_cycles"] == cycles
    assert rule["reason"] == ""
    assert rule["source"] == source


@pytest.mark.parametrize("diameter", [12.0, 12.000001])
def test_2023_bent_screen_applies_the_existing_bend_factor_once(diameter):
    entry = fi.default_entry(preset=fi.PRESET_2023_BENT_BARS)
    entry["mandrel_diameter_mm"] = 80.0
    base = 90.0 if diameter <= 12.0 else 73.0

    rule = fi.simplified_reinforcement_screen_rule(
        entry,
        diameter,
        DesignBasisKey.PUBLISHED_2023,
    )

    assert rule["threshold_mpa"] == pytest.approx(
        base * fi.bend_reduction_factor(entry, diameter)
    )
    assert rule["detail_class"] == "unwelded bent reinforcing bar"
    assert rule["range_basis"] == "design"
    assert rule["max_cycles"] == 1.0e8
    assert rule["reason"] == ""
    assert rule["source"] == _PUBLISHED_2023_SOURCE


@pytest.mark.parametrize(
    ("preset", "basis", "detail_class", "source"),
    [
        (fi.PRESET_2005_COUPLERS, DesignBasisKey.FIRST_GEN_BASE,
         "unsupported first-generation detail", _FIRST_GEN_SOURCE),
        (fi.PRESET_2005_PRETENSION, DesignBasisKey.FIRST_GEN_DK_NA_2024,
         "unsupported first-generation detail", _FIRST_GEN_DK_SOURCE),
        (fi.PRESET_2005_BARS, DesignBasisKey.PUBLISHED_2023,
         "edition-mismatched named detail", ""),
        (fi.PRESET_2023_BARS, DesignBasisKey.FIRST_GEN_BASE,
         "edition-mismatched named detail", ""),
        (fi.PRESET_2023_PRESTRESS_COUPLER,
         DesignBasisKey.PUBLISHED_2023,
         "unsupported published-2023 detail", _PUBLISHED_2023_SOURCE),
    ],
)
def test_simplified_reinforcement_screen_unsupported_mapping_falls_back(
    preset, basis, detail_class, source
):
    rule = fi.simplified_reinforcement_screen_rule(
        fi.default_entry(preset=preset),
        16.0,
        basis,
    )

    assert rule["detail_class"] == detail_class
    assert rule["threshold_mpa"] is None
    assert rule["range_basis"] == ""
    assert rule["source"] == source
    assert rule["max_cycles"] is None
    assert rule["reason"]


def test_custom_values_cannot_recreate_named_screen_provenance():
    entry = fi.default_entry(preset=fi.PRESET_2023_BARS)
    entry["n_star"] += 1.0
    custom = fi.normalise_catalog({"items": [entry]})["items"][0]

    rule = fi.simplified_reinforcement_screen_rule(
        custom,
        12.0,
        DesignBasisKey.PUBLISHED_2023,
    )

    assert custom["preset"] == fi.CUSTOM_PRESET
    assert rule["threshold_mpa"] is None
    assert rule["detail_class"] == "custom/imported detail"


@pytest.mark.parametrize("diameter", [None, True, 0.0, -1.0, math.inf])
def test_simplified_reinforcement_screen_rejects_malformed_diameter(diameter):
    with pytest.raises(ValueError, match="diameter_mm"):
        fi.simplified_reinforcement_screen_rule(
            fi.default_entry(preset=fi.PRESET_2023_BARS),
            diameter,
            DesignBasisKey.PUBLISHED_2023,
        )


def test_catalogue_ids_are_stable_and_lowest_unused_id_is_reused():
    catalogue, second = fi.add_entry(fi.default_catalog())
    catalogue, third = fi.duplicate_entry(catalogue, "F1")
    catalogue = fi.delete_entry(catalogue, second)
    catalogue, reused = fi.add_entry(catalogue)

    assert (second, third, reused) == ("F2", "F3", "F2")
    assert fi.detail_ids(catalogue) == ["F1", "F3", "F2"]


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

    assert fi.detail_ids(catalogue) == ["F4", "F1", "F2"]
    assert fi.invalid_assignments(["", "F4"], catalogue, fi.MILD) == []
    assert fi.invalid_assignments(["F1"], catalogue, fi.MILD) == ["F1"]
    assert fi.invalid_assignments(["F1"], catalogue, fi.PRESTRESS) == []


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


def test_grouped_spectrum_basis_is_direct_and_has_no_policy_warnings():
    basis = fi.normalise_basis({
        "method": fi.METHOD_GROUPED,
        "notes": "Engineer-defined bins",
    })

    assert basis == {
        "method": fi.METHOD_GROUPED,
        "notes": "Engineer-defined bins",
    }
    assert fi.basis_warnings(basis) == []
    assert fi.method_requires_single_bin(fi.METHOD_GROUPED) is False


def test_grouped_spectrum_basis_rejects_unknown_method():
    with pytest.raises(ValueError, match="unknown fatigue calculation method"):
        fi.normalise_basis({"method": "Authority route"})


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
        "Fatigue row 1: cycles must be a finite number"
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
        "Fatigue row 1: cycles must be a finite number",
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
        (
            "Fatigue row 2: Spectrum 'traffic' differs only by case from "
            "'Traffic'; use one spelling"
        )
    ]
    assert list(groups) == ["Traffic"]
    assert [row["name"] for row in groups["Traffic"]] == ["FAT-01", "FAT-02"]
