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


def test_add_duplicate_delete_never_reuses_an_id():
    catalogue, second = mc.add_entry(mc.default_catalog("mild"), "mild")
    catalogue, third = mc.duplicate_entry(catalogue, "mild", "M1")
    catalogue = mc.delete_entry(catalogue, "mild", second)
    catalogue, fourth = mc.add_entry(catalogue, "mild")

    assert (second, third, fourth) == ("M2", "M3", "M4")
    assert mc.material_ids(catalogue, "mild") == ["M1", "M3", "M4"]


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

    assert mc.material_ids(out, "mild") == ["M4", "M5", "M6"]
    assert out["next_id"] == 7


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
