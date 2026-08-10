import math

import pytest

from app import material_catalog as mc
from sector import material_presets as mp


def test_default_catalogue_builds_one_stable_material():
    mild = mc.default_catalog("mild")
    prestress = mc.default_catalog("prestress")

    assert mc.material_ids(mild, "mild") == ["M1"]
    assert mc.material_ids(prestress, "prestress") == ["P1"]
    assert mc.build_material(mild["items"][0], "mild").fytk == 550.0
    assert mc.build_material(prestress["items"][0], "prestress").Es == 195000.0


def test_mild_delete_then_add_reuses_lowest_available_suffix():
    catalogue, second = mc.add_entry(mc.default_catalog("mild"), "mild")
    catalogue, third = mc.duplicate_entry(catalogue, "mild", "M1")
    catalogue = mc.delete_entry(catalogue, "mild", second)
    assert catalogue["next_id"] == 2
    catalogue, fourth = mc.add_entry(catalogue, "mild")

    assert (second, third, fourth) == ("M2", "M3", "M2")
    assert mc.material_ids(catalogue, "mild") == ["M1", "M3", "M2"]
    assert catalogue["next_id"] == 4


def test_prestress_delete_then_duplicate_reuses_lowest_available_suffix():
    catalogue, second = mc.add_entry(
        mc.default_catalog("prestress"), "prestress"
    )
    catalogue, third = mc.add_entry(catalogue, "prestress")
    catalogue = mc.delete_entry(catalogue, "prestress", second)
    catalogue, duplicate = mc.duplicate_entry(catalogue, "prestress", "P1")

    assert (second, third, duplicate) == ("P2", "P3", "P2")
    assert mc.material_ids(catalogue, "prestress") == ["P1", "P3", "P2"]
    assert catalogue["next_id"] == 4


def test_delete_rejects_last_or_assigned_material():
    with pytest.raises(ValueError, match="at least one"):
        mc.delete_entry(mc.default_catalog("mild"), "mild", "M1")

    catalogue, _ = mc.add_entry(mc.default_catalog("mild"), "mild")
    with pytest.raises(ValueError, match="assigned"):
        mc.delete_entry(catalogue, "mild", "M1", assigned_ids=["M1"])


def test_normalise_repairs_invalid_and_duplicate_ids_deterministically():
    raw = {
        "next_id": 2,
        "items": [
            {**mc.default_entry("mild"), "id": "M4", "name": "A"},
            {**mc.default_entry("mild"), "id": "M4", "name": "B"},
            {**mc.default_entry("mild"), "id": "bad", "name": "C"},
        ],
    }
    out = mc.normalise_catalog(raw, "mild")

    assert mc.material_ids(out, "mild") == ["M4", "M1", "M2"]
    assert out["next_id"] == 3


def test_stale_persisted_next_id_does_not_skip_a_mild_gap():
    raw = {
        "next_id": 99,
        "items": [
            {**mc.default_entry("mild"), "id": "M1"},
            {**mc.default_entry("mild"), "id": "M3"},
        ],
    }

    canonical = mc.normalise_catalog(raw, "mild")
    updated, material_id = mc.add_entry(canonical, "mild")

    assert canonical["next_id"] == 2
    assert material_id == "M2"
    assert updated["next_id"] == 4


def test_stale_persisted_next_id_does_not_skip_a_prestress_gap():
    raw = {
        "next_id": 500,
        "items": [
            {**mc.default_entry("prestress"), "id": "P1"},
            {**mc.default_entry("prestress"), "id": "P4"},
        ],
    }

    canonical = mc.normalise_catalog(raw, "prestress")
    updated, material_id = mc.add_entry(canonical, "prestress")

    assert canonical["next_id"] == 2
    assert material_id == "P2"
    assert updated["next_id"] == 3


def test_assignment_reservations_protect_orphan_ids_during_repair_and_add():
    raw = {
        "next_id": 200,
        "items": [
            {**mc.default_entry("mild"), "id": "M1"},
            {**mc.default_entry("mild"), "id": "damaged"},
        ],
    }

    canonical = mc.normalise_catalog(raw, "mild", reserved_ids=[" M2 "])
    updated, material_id = mc.add_entry(
        canonical, "mild", reserved_ids=["M2", "bad", "P4"]
    )

    assert mc.material_ids(canonical, "mild") == ["M1", "M3"]
    assert material_id == "M4"
    assert mc.material_ids(updated, "mild") == ["M1", "M3", "M4"]


def test_assignment_reservation_protects_id_when_catalogue_is_missing():
    canonical = mc.normalise_catalog(None, "prestress", reserved_ids=["P1"])

    assert mc.material_ids(canonical, "prestress") == ["P2"]
    assert canonical["next_id"] == 1


def test_reserved_normalisation_round_trip_is_stable():
    raw = {
        "version": 999,
        "next_id": 88,
        "items": [
            {**mc.default_entry("prestress"), "id": "P3", "name": "A"},
            {**mc.default_entry("prestress"), "id": "P3", "name": "B"},
            {**mc.default_entry("prestress"), "id": "broken", "name": "C"},
        ],
    }

    first = mc.normalise_catalog(raw, "prestress", reserved_ids=["P1"])
    second = mc.normalise_catalog(first, "prestress", reserved_ids=["P1"])

    assert mc.material_ids(first, "prestress") == ["P3", "P2", "P4"]
    assert first["next_id"] == 1
    assert second == first


def test_add_result_has_a_stable_normalisation_round_trip():
    raw = {
        "next_id": 900,
        "items": [
            {**mc.default_entry("mild"), "id": "M1"},
            {**mc.default_entry("mild"), "id": "M3"},
        ],
    }

    updated, material_id = mc.add_entry(raw, "mild")

    assert material_id == "M2"
    assert mc.normalise_catalog(updated, "mild") == updated


def test_invalid_imported_curve_is_repaired_before_ui_use():
    mild = mc.normalise_catalog({
        "items": [{"id": "M1", "preset": "Unknown source", "curve": 99}]
    }, "mild")
    prestress = mc.normalise_catalog({
        "items": [{"id": "P1", "preset": "Unknown source", "curve": -2}]
    }, "prestress")

    assert mild["items"][0]["curve"] in mc.curves("mild")
    assert prestress["items"][0]["curve"] in mc.curves("prestress")
    mc.build_material(mild["items"][0], "mild")
    mc.build_material(prestress["items"][0], "prestress")


def test_invalid_curve_keeps_a_recognised_preset_internally_consistent():
    preset = "Curve 4 (built-in)"
    out = mc.normalise_catalog({
        "items": [{"id": "P1", "preset": preset, "curve": 99}]
    }, "prestress")

    assert out["items"][0]["preset"] == preset
    assert out["items"][0]["curve"] == 4


def test_missing_current_catalogue_initialises_current_default():
    out = mc.ensure_catalog({"mild_fytk": 412.0}, "mild")
    assert mc.material_ids(out, "mild") == ["M1"]
    assert out["items"][0]["fytk"] == 550.0


def test_ensure_catalog_reserves_assignments_before_default_or_repair():
    assert mc.material_ids(
        mc.ensure_catalog({}, "mild", reserved_ids=["M1"]), "mild"
    ) == ["M2"]

    damaged = {
        mc.MILD_CATALOG_KEY: {
            "version": mc.VERSION,
            "items": [{**mc.default_entry("mild"), "id": "bad"}],
        }
    }
    assert mc.material_ids(
        mc.ensure_catalog(damaged, "mild", reserved_ids=["M1"]), "mild"
    ) == ["M2"]


def test_apply_preset_keeps_identity_and_description():
    entry = mc.default_entry("prestress")
    entry.update(name="Cable A", description="Measured workline")
    out = mc.apply_preset(entry, "prestress", "Curve 7 (two yield)")

    assert out["id"] == "P1"
    assert out["name"] == "Cable A"
    assert out["description"] == "Measured workline"
    assert out["curve"] == 7
    assert math.isclose(out["k"], 0.9)


def test_mild_preset_identity_is_concrete_and_not_numerically_promoted():
    generic_name = "Curve 2 (elastic-perfectly-plastic)"
    edition_name = "DS/EN 1992-1-1:2005 + DK NA:2024"
    generic = mc.default_entry("mild", preset=generic_name)
    edition = mc.default_entry("mild", preset=edition_name)

    # Make the two laws numerically identical while retaining their selected IDs.
    edition["curve"] = generic["curve"]
    for field in mc.MILD_FIELDS:
        edition[field] = generic[field]
    generic_law = mc.build_material(generic, "mild")
    edition_law = mc.build_material(edition, "mild")
    for strain in (-0.01, -0.001, 0.001, 0.01):
        assert edition_law.stress(strain) == pytest.approx(
            generic_law.stress(strain)
        )

    assert mc.mild_preset_classification(generic_name) == (
        "User-defined / project-defined Curve 2 preset; uncited"
    )
    assert mc.mild_preset_classification(edition_name) == (
        "Curve 3 Eurocode design preset"
    )
    assert "Curve 2 preset; uncited" in mc.mild_preset_display_label(generic_name)
    assert "Curve 3 Eurocode design preset" in mc.mild_preset_display_label(
        edition_name
    )
    assert mp.MILD_PRESETS[generic_name]["gamma_E"] == pytest.approx(1.0)


def test_invalid_assignment_list_is_unique_and_sorted():
    out = mc.invalid_assignments(
        ["M9", "M2", "M9", "M1"], mc.default_catalog("mild"), "mild"
    )
    assert out == ["M2", "M9"]
