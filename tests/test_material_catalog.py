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


@pytest.mark.parametrize(
    ("kind", "curve", "missing"),
    (
        ("mild", 3, "futk"),
        ("mild", 2, "gamma_y"),
        ("prestress", 7, "ey0t"),
        ("prestress", 1, "IS"),
    ),
)
def test_catalogue_build_rejects_curve_specific_omissions(kind, curve, missing):
    entry = mc.default_entry(kind)
    entry["curve"] = curve
    entry.pop(missing)

    with pytest.raises(ValueError, match=missing):
        mc.build_material(entry, kind)


@pytest.mark.parametrize(
    ("kind", "field", "value", "match"),
    (
        ("mild", "fytk", float("nan"), "fytk"),
        ("mild", "futk", -1.0, "futk"),
        ("mild", "futk", 500.0, "futk"),
        ("mild", "k", 1.1, "k"),
        ("mild", "eut", 1.0, "yield strain"),
        ("prestress", "IS", float("inf"), "IS"),
        ("prestress", "eut", -1.0, "eut"),
        ("prestress", "futk", 1600.0, "fpk"),
        ("prestress", "ey0t", 40.0, "proof strain"),
    ),
)
def test_catalogue_build_rejects_invalid_active_material_domains(
    kind,
    field,
    value,
    match,
):
    entry = mc.default_entry(kind)
    entry[field] = value

    with pytest.raises(ValueError, match=match):
        mc.build_material(entry, kind)


def test_catalogue_build_accepts_inapplicable_tension_only_compression_relations():
    entry = mc.default_entry("mild")
    entry.update(
        active_in_compression=False,
        fytk=500.0,
        fyck=700.0,
        futk=600.0,
        ey0c=-1.0,
    )

    steel = mc.build_material(entry, "mild")

    assert steel.active_in_compression is False
    assert steel.stress(-0.02) == 0.0


@pytest.mark.parametrize(
    "ey0c",
    (float("nan"), float("inf"), -float("inf"), "not-a-number"),
)
def test_catalogue_rejects_nonfinite_inactive_compression_offset(ey0c):
    entry = mc.default_entry("mild")
    entry.update(active_in_compression=False, ey0c=ey0c)

    with pytest.raises(ValueError, match="ey0c"):
        mc.build_material(entry, "mild")


def test_catalogue_build_rejects_ultimate_below_active_compression_yield():
    entry = mc.default_entry("mild")
    entry.update(fytk=500.0, fyck=700.0, futk=600.0)

    with pytest.raises(ValueError, match="active fyck"):
        mc.build_material(entry, "mild")


@pytest.mark.parametrize(
    ("kind", "updates"),
    (
        (
            "mild",
            {
                "fytk": 500.0,
                "fyck": 500.0,
                "futk": 550.0,
                "gamma_y": 1.0,
                "gamma_u": 2.0,
            },
        ),
        (
            "prestress",
            {
                "fytk": 1600.0,
                "futk": 1800.0,
                "gamma_y": 1.0,
                "gamma_u": 2.0,
            },
        ),
    ),
)
def test_catalogue_build_rejects_descending_factored_ultimate_branch(
    kind,
    updates,
):
    entry = mc.default_entry(kind)
    entry.update(updates)

    with pytest.raises(ValueError, match="gamma_u"):
        mc.build_material(entry, kind)


@pytest.mark.parametrize(
    ("kind", "curve", "updates"),
    (
        (
            "mild",
            1,
            {
                "fytk": 500.0,
                "fyck": 500.0,
                "futk": 550.0,
                "gamma_y": 1.0,
                "gamma_u": 1.1,
            },
        ),
        (
            "mild",
            3,
            {
                "fytk": 500.0,
                "fyck": 500.0,
                "futk": 550.0,
                "gamma_y": 1.0,
                "gamma_u": 1.1,
            },
        ),
        (
            "prestress",
            6,
            {
                "fytk": 1600.0,
                "futk": 1760.0,
                "gamma_y": 1.0,
                "gamma_u": 1.1,
            },
        ),
        (
            "prestress",
            7,
            {
                "fytk": 1600.0,
                "futk": 1760.0,
                "gamma_y": 1.0,
                "gamma_u": 1.1,
            },
        ),
    ),
)
def test_catalogue_build_accepts_mathematically_equal_factored_ultimate(
    kind,
    curve,
    updates,
):
    entry = mc.default_entry(kind)
    entry.update(curve=curve, **updates)

    material = mc.build_material(entry, kind)

    assert material.curve == curve


@pytest.mark.parametrize(
    ("kind", "curve"),
    (("mild", 1), ("mild", 3), ("prestress", 6), ("prestress", 7)),
)
def test_catalogue_factored_strength_order_is_scale_independent(kind, curve):
    entry = mc.default_entry(kind)
    entry.update(
        curve=curve,
        fytk=1.0e-308,
        futk=2.0e-308,
        eut=50.0,
        gamma_y=1.0,
        gamma_u=2.0,
        gamma_E=1.0,
        Es=1.0e-309,
    )
    if kind == "mild":
        entry.update(fyck=0.0, active_in_compression=False)
    if curve in (3, 7):
        entry.update(k=1.0, ey0t=0.0)
    if curve == 3:
        entry["ey0c"] = -10.0

    equal = mc.build_material(entry, kind)
    assert equal.stress(equal.eut) == equal.futk / equal.gamma_u

    entry["futk"] = 1.0e-308
    with pytest.raises(ValueError, match="gamma_u"):
        mc.build_material(entry, kind)


@pytest.mark.parametrize(
    ("kind", "curve"),
    (("mild", 1), ("mild", 3), ("prestress", 6), ("prestress", 7)),
)
def test_catalogue_extreme_finite_hardening_law_stays_finite(kind, curve):
    entry = mc.default_entry(kind)
    entry.update(
        curve=curve,
        fytk=1.0,
        futk=1.0e308,
        eut=1.0e308,
        gamma_y=1.0,
        gamma_u=1.0,
        gamma_E=1.0,
        Es=200.0,
    )
    if kind == "mild":
        entry.update(fyck=0.0, active_in_compression=False)
    if curve in (3, 7):
        entry.update(k=0.9, ey0t=0.0)
    if curve == 3:
        entry["ey0c"] = -10.0

    material = mc.build_material(entry, kind)

    assert material.eut == pytest.approx(1.0e305)
    assert material.stress(material.eut) == 1.0e308
    assert all(
        math.isfinite(material.stress(strain))
        for strain in (0.0035, material.eut / 2.0, material.eut)
    )


@pytest.mark.parametrize("curve", (1, 2, 3, 4, 5))
def test_catalogue_builtin_prestress_rejects_nonfinite_design_stress(curve):
    entry = mc.default_entry("prestress")
    entry.update(curve=curve, gamma_y=1.0e-308)

    with pytest.raises(ValueError, match="design stress"):
        mc.build_material(entry, "prestress")


@pytest.mark.parametrize(
    ("kind", "curve", "updates"),
    (
        (
            "mild",
            1,
            {
                "fytk": 500.0,
                "fyck": 500.0,
                "futk": 1.0e308,
                "gamma_y": 1.0,
                "gamma_u": 1.0e-308,
            },
        ),
        (
            "mild",
            3,
            {
                "fytk": 1.0e-308,
                "fyck": 1.0e-308,
                "futk": 1.0e-308,
                "gamma_y": 1.0e308,
                "gamma_u": 1.0e308,
            },
        ),
        (
            "prestress",
            6,
            {
                "fytk": 1600.0,
                "futk": 1.0e308,
                "gamma_y": 1.0,
                "gamma_u": 1.0e-308,
            },
        ),
        (
            "prestress",
            7,
            {
                "fytk": 1.0e-308,
                "futk": 1.0e-308,
                "gamma_y": 1.0e308,
                "gamma_u": 1.0e308,
            },
        ),
    ),
)
def test_catalogue_build_rejects_nonfinite_derived_design_ordinate(
    kind,
    curve,
    updates,
):
    entry = mc.default_entry(kind)
    entry.update(curve=curve, **updates)

    with pytest.raises(ValueError, match="positive finite|gamma_u"):
        mc.build_material(entry, kind)


@pytest.mark.parametrize(
    ("kind", "curve", "updates"),
    (
        (
            "mild",
            1,
            {
                "fytk": 1.0e308,
                "fyck": 0.0,
                "futk": 1.0e308,
                "eut": 2000.0,
                "gamma_y": 1.0e307,
                "gamma_u": 1.0e307,
                "gamma_E": 1.0e308,
                "Es": 1.0e305,
                "active_in_compression": False,
            },
        ),
        (
            "mild",
            3,
            {
                "fytk": 1.0e-308,
                "fyck": 0.0,
                "futk": 1.0e-308,
                "eut": 2000.0,
                "gamma_y": 1.0e-308,
                "gamma_u": 1.0e-308,
                "gamma_E": 1.0e-306,
                "Es": 1.0e-310,
                "active_in_compression": False,
                "k": 1.0,
                "ey0t": 0.0,
                "ey0c": 0.0,
            },
        ),
        (
            "prestress",
            6,
            {
                "IS": 0.0,
                "fytk": 1.0e308,
                "futk": 1.0e308,
                "eut": 2000.0,
                "gamma_y": 1.0e307,
                "gamma_u": 1.0e307,
                "gamma_E": 1.0e308,
                "Es": 1.0e305,
            },
        ),
        (
            "prestress",
            7,
            {
                "IS": 0.0,
                "fytk": 1.0e-308,
                "futk": 1.0e-308,
                "eut": 2000.0,
                "gamma_y": 1.0e-308,
                "gamma_u": 1.0e-308,
                "gamma_E": 1.0e-306,
                "Es": 1.0e-310,
                "k": 1.0,
                "ey0t": 0.0,
            },
        ),
    ),
)
def test_catalogue_build_rejects_factored_yield_nan_escape(
    kind,
    curve,
    updates,
):
    entry = mc.default_entry(kind)
    entry.update(curve=curve, **updates)

    with pytest.raises(ValueError, match="yield strain|proof strain"):
        mc.build_material(entry, kind)


@pytest.mark.parametrize(
    ("kind", "curve", "updates"),
    (
        (
            "mild",
            1,
            {
                "fytk": 1.0e307,
                "fyck": 0.0,
                "futk": 1.0e307,
                "eut": 2000.0,
                "gamma_y": 1.0e307,
                "gamma_u": 1.0e307,
                "gamma_E": 1.0e307,
                "Es": 1.0e305,
                "active_in_compression": False,
            },
        ),
        (
            "prestress",
            7,
            {
                "IS": 0.0,
                "fytk": 1.0e-308,
                "futk": 1.0e-308,
                "eut": 2000.0,
                "gamma_y": 1.0e-308,
                "gamma_u": 1.0e-308,
                "gamma_E": 1.0e-308,
                "Es": 1.0e-310,
                "k": 1.0,
                "ey0t": 0.0,
            },
        ),
    ),
)
def test_catalogue_build_accepts_finite_factored_yield_after_cancellation(
    kind,
    curve,
    updates,
):
    entry = mc.default_entry(kind)
    entry.update(curve=curve, **updates)

    material = mc.build_material(entry, kind)

    assert math.isfinite(material.stress(0.05))
    assert math.isfinite(material.stress(material.eut))


def test_catalogue_build_ignores_fields_outside_the_selected_curve():
    mild = mc.default_entry("mild")
    mild.update(
        curve=2,
        futk=float("nan"),
        gamma_u=float("nan"),
        gamma_E=float("nan"),
        k=1.1,
        ey0t=float("inf"),
        ey0c=-1.0,
    )
    assert mc.build_material(mild, "mild").curve == 2

    prestress = mc.default_entry("prestress")
    prestress.update(
        curve=1,
        fytk=float("nan"),
        futk=-1.0,
        eut=-1.0,
        gamma_u=float("nan"),
        gamma_E=float("nan"),
        k=1.1,
        ey0t=-1.0,
    )
    assert mc.build_material(prestress, "prestress").curve == 1


def test_catalogue_normalisation_never_repairs_engineering_values():
    entry = mc.default_entry("mild")
    entry["fytk"] = float("nan")
    normalised = mc.normalise_catalog({"items": [entry]}, "mild")

    assert math.isnan(normalised["items"][0]["fytk"])
    with pytest.raises(ValueError, match="fytk"):
        mc.build_material(normalised["items"][0], "mild")

    entry = mc.default_entry("prestress")
    entry["futk"] = 1600.0
    normalised = mc.normalise_catalog({"items": [entry]}, "prestress")

    assert normalised["items"][0]["futk"] == pytest.approx(1600.0)
    with pytest.raises(ValueError, match="fpk"):
        mc.build_material(normalised["items"][0], "prestress")


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
