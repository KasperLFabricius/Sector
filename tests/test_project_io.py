from __future__ import annotations

import copy
import inspect
import json
import math
import pathlib
import re
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_inputs
import load_cases
import material_catalog
import project_io
import reinforcement_table

from app import modelled_direction
from sector import capacity, codes, design_standards


class _FloatTypeError:
    def __float__(self):
        raise TypeError("hostile conversion")


class _FloatValueError:
    def __float__(self):
        raise ValueError("hostile conversion")


class _FloatOverflowError:
    def __float__(self):
        raise OverflowError("hostile conversion")


@pytest.mark.parametrize(
    ("sweep", "expected_message"),
    (
        (
            {"v_min": 0.0, "v_max": 1.0, "v_inc": 1e-20},
            "increase the neutral-axis sweep maximum increment; the requested "
            "sweep is too fine to calculate reliably",
        ),
        (
            {"v_min": 1e16, "v_max": 1e16 + 2.0, "v_inc": 1.0},
            "increase the neutral-axis sweep maximum increment; the requested "
            "sweep is too fine to calculate reliably",
        ),
        (
            {"v_min": -1e308, "v_max": 1e308, "v_inc": 1.0},
            "correct the neutral-axis sweep start and end angles; their separation "
            "is too large to calculate reliably",
        ),
    ),
)
def test_current_project_rejects_unsafe_plastic_sweep_with_authored_copy(
    sweep,
    expected_message,
):
    payload = json.loads(project_io.dump_project({}, {
        "v_min": 0.0,
        "v_max": 360.0,
        "v_inc": 15.0,
    }))
    payload["scalars"].update(sweep)
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })

    with pytest.raises(project_io.ProjectInputError) as caught:
        project_io.parse_project(json.dumps(payload))

    assert project_io.engineer_error_message(caught.value) == expected_message


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 0.0),
        (-0.0, 0.0),
        (0.25, 0.25),
        (1.75, 1.75),
        (np.int64(2), 2.0),
        (np.float32(0.375), 0.375),
    ],
)
def test_nonnegative_project_scalar_normalizes_finite_reals(value, expected):
    before_type = type(value)
    result = project_io._nonnegative_real(value, "criterion")
    assert type(result) is float
    assert result == pytest.approx(expected)
    if expected == 0.0:
        assert not np.signbit(result)
    assert type(value) is before_type


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        np.bool_(True),
        np.bool_(False),
        "0.25",
        b"0.25",
        -0.001,
        float("nan"),
        float("inf"),
        -float("inf"),
        _FloatTypeError(),
        _FloatValueError(),
        _FloatOverflowError(),
    ],
)
def test_nonnegative_project_scalar_rejects_non_numeric_or_invalid_values(value):
    with pytest.raises(
        ValueError, match="criterion must be a non-negative finite real number"
    ):
        project_io._nonnegative_real(value, "criterion")


def test_nonnegative_project_scalar_has_exact_required_boundary():
    parameters = list(
        inspect.signature(project_io._nonnegative_real).parameters.values()
    )
    assert [parameter.name for parameter in parameters] == ["value", "label"]
    assert all(parameter.default is inspect.Parameter.empty for parameter in parameters)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (True, 1),
        (1, 1.0),
        ([1.0], (1.0,)),
        (np.float32(1.0), np.float64(1.0)),
        (np.array([1.0], dtype="float32"), np.array([1.0], dtype="float64")),
    ],
)
def test_result_fingerprint_retains_concrete_type(first, second):
    assert project_io.result_sha256(first) != project_io.result_sha256(second)


def test_result_fingerprint_is_order_independent_and_seals_every_mapping_field():
    first = {
        "b": pd.DataFrame({"x": [1.0], "label": ["one"]}),
        "a": {"value": -0.0},
    }
    reordered = {
        "a": {"value": -0.0},
        "b": pd.DataFrame({"x": [1.0], "label": ["one"]}),
    }
    assert project_io.result_sha256(first) == project_io.result_sha256(reordered)

    changed = copy.deepcopy(reordered)
    changed["a"]["retired_metadata"] = {"value": 1}
    assert project_io.result_sha256(changed) != project_io.result_sha256(first)
    assert project_io.result_sha256({"a": [1, True, -0.0]}) == (
        "39b6f6999c42d6fe396078a0a062e91fc58193bd96159099d9a88e96e41ab9f0"
    )


def _current_project():
    tables = {
        "corners_base": pd.DataFrame(
            {
                "x (mm)": [0.0, 500.0, 500.0, 0.0],
                "y (mm)": [0.0, 0.0, 800.0, 800.0],
            }
        ),
        "hole_base": pd.DataFrame(
            columns=["x (mm)", "y (mm)"], dtype="float64"
        ),
        "bars_base": reinforcement_table.empty_table(),
        "tendons_base": reinforcement_table.empty_table(),
        load_cases.PLASTIC_TABLE_KEY: load_cases.normalise_table(
            [{
                "name": "Only characteristic action",
                "description": "User label retained",
                "n_ed_kn": 123.5,
                "mx_ed_knm": -44.0,
                "my_ed_knm": 8.0,
                "vx_ed_kn": 9.0,
                "vy_ed_kn": -11.0,
                "vx_face": "negative",
                "vy_face": "positive",
                "t_ed_knm": 2.0,
                "check_minimum_reinforcement": False,
            }],
            load_cases.PLASTIC_TABLE_KEY,
        ),
        load_cases.ELASTIC_TABLE_KEY: load_cases.normalise_table(
            [{
                "name": "One Elastic action",
                "description": "No completeness inference",
                "n_long_ed_kn": 20.0,
                "mx_long_ed_knm": 30.0,
                "my_long_ed_knm": -12.0,
                "n_short_ed_kn": 3.0,
                "mx_short_ed_knm": 4.0,
                "my_short_ed_knm": 5.0,
                "calculate_crack_width": True,
            }],
            load_cases.ELASTIC_TABLE_KEY,
        ),
        fatigue_inputs.SPECTRUM_TABLE_KEY: (
            fatigue_inputs.empty_spectrum_table()
        ),
    }
    scalars = {
        "mode": "Both",
        "conc_gamma_c": 0.5,
        "mild_gamma_y": 2.0,
        "torsion_gamma_ct": 2.0,
        "sls_code": (
            design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024.value
        ),
        "fatigue_edition": (
            design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024.value
        ),
        "sls_long_term_permitted_crack_width_mm": 0.0,
        "sls_short_term_permitted_crack_width_mm": 0.0,
        "sls_heightened_permitted_crack_width_mm": 0.0,
        "rep_proj_no": "P-001",
    }
    return tables, scalars


def _heightened_inputs() -> dict[str, object]:
    return {
        "sls_heightened_on": True,
        "sls_heightened_reference_case": "One Elastic action",
        "sls_heightened_reinforcement_surface": "ribbed",
        "sls_heightened_effective_tensile_strength_mpa": 2.9,
        "sls_heightened_permitted_crack_width_mm": 0.2,
        "sls_heightened_fine_effective_tension_area_mm2": 120_000.0,
        "sls_heightened_coarse_effective_tension_area_mm2": 180_000.0,
    }


_MISSING = object()


def _schema25_payload(
    tables=None,
    scalars=None,
    *,
    shared_width=_MISSING,
):
    """Build an integrity-valid schema-25 shared-width payload."""

    if tables is None or scalars is None:
        tables, scalars = _current_project()
    current_scalars = dict(scalars)
    current_scalars.setdefault("shear_gamma_v", 1.40)
    payload = json.loads(project_io.dump_project(tables, current_scalars))
    payload["version"] = project_io.LEGACY_MIGRATABLE_VERSION
    payload["scalars"].pop("shear_gamma_v", None)
    payload["scalars"].pop(capacity.TORSION_CASE_AUTHORITIES_KEY, None)
    for key in (
        "sls_long_term_permitted_crack_width_mm",
        "sls_short_term_permitted_crack_width_mm",
        "sls_heightened_permitted_crack_width_mm",
    ):
        payload["scalars"].pop(key, None)
    if shared_width is not _MISSING:
        payload["scalars"][project_io.LEGACY_SHARED_CRACK_WIDTH_KEY] = (
            shared_width
        )
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    return payload


def _legacy_heightened_schema25_payload(tables=None) -> dict:
    """Build one integrity-valid pre-PR06 schema-25 heightened payload."""

    if tables is None:
        tables, scalars = _current_project()
    else:
        _, scalars = _current_project()
    scalars.update(_heightened_inputs())
    payload = json.loads(project_io.dump_project(tables, scalars))
    payload["version"] = project_io.LEGACY_MIGRATABLE_VERSION
    persisted = payload["scalars"]
    persisted.pop("shear_gamma_v", None)
    persisted.pop(capacity.TORSION_CASE_AUTHORITIES_KEY, None)
    heightened_width = persisted.pop(
        "sls_heightened_permitted_crack_width_mm"
    )
    persisted.pop("sls_long_term_permitted_crack_width_mm")
    persisted.pop("sls_short_term_permitted_crack_width_mm")
    persisted[project_io.LEGACY_SHARED_CRACK_WIDTH_KEY] = heightened_width
    persisted.pop("sls_heightened_reference_case", None)
    persisted.pop("sls_heightened_fine_effective_tension_area_mm2", None)
    persisted.pop("sls_heightened_coarse_effective_tension_area_mm2", None)
    persisted.update({
        "sls_heightened_crack_system": "fine",
        "sls_heightened_bar_diameter_mm": 16.0,
        "sls_heightened_reinforcement_modulus_mpa": 200_000.0,
        "sls_heightened_effective_tension_area_mm2": 120_000.0,
        "sls_heightened_provided_reinforcement_area_mm2": 2_500.0,
    })
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": persisted,
    })
    return payload


def _schema26_payload(tables=None, scalars=None) -> dict:
    """Build one integrity-valid schema-26 payload without gamma_V."""

    if tables is None or scalars is None:
        tables, scalars = _current_project()
    current_scalars = dict(scalars)
    current_scalars.setdefault("shear_gamma_v", 1.40)
    payload = json.loads(project_io.dump_project(tables, current_scalars))
    payload["version"] = project_io.MIGRATABLE_VERSION
    payload["scalars"].pop("shear_gamma_v", None)
    payload["scalars"].pop(capacity.TORSION_CASE_AUTHORITIES_KEY, None)
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    return payload


def test_current_schema_save_load_resave_retains_exact_inputs():
    tables, scalars = _current_project()
    first = project_io.dump_project(
        tables,
        scalars,
        app_version="0.91",
        revision="abc123",
    )
    loaded_tables, loaded_scalars = project_io.parse_project(first)
    second = project_io.dump_project(
        loaded_tables,
        loaded_scalars,
        app_version="0.91",
        revision="abc123",
    )

    assert loaded_scalars["conc_gamma_c"] == pytest.approx(0.5)
    assert loaded_scalars["mild_gamma_y"] == pytest.approx(2.0)
    assert loaded_scalars["torsion_gamma_ct"] == pytest.approx(2.0)
    assert loaded_scalars["shear_gamma_v"] == pytest.approx(1.40)
    assert loaded_scalars["fatigue_edition"] == (
        design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024.value
    )
    assert (
        loaded_tables[load_cases.PLASTIC_TABLE_KEY].loc[0, "name"]
        == "Only characteristic action"
    )
    assert loaded_tables[load_cases.PLASTIC_TABLE_KEY].loc[
        0, "n_ed_kn"
    ] == pytest.approx(123.5)
    assert project_io.project_provenance(first)["input_hash_valid"] is True
    assert project_io.project_provenance(second)["input_hash_valid"] is True
    assert json.loads(first)["version"] == project_io.VERSION
    assert json.loads(second)["version"] == project_io.VERSION


def test_current_schema_round_trip_ignores_orphaned_material_aliases():
    mild = {
        "version": material_catalog.VERSION,
        "next_id": 3,
        "items": [
            material_catalog.default_entry("mild", material_id="M2")
        ],
    }
    prestress = {
        "version": material_catalog.VERSION,
        "next_id": 3,
        "items": [
            material_catalog.default_entry("prestress", material_id="P2")
        ],
    }
    scalars = {
        material_catalog.MILD_CATALOG_KEY: mild,
        material_catalog.PRESTRESS_CATALOG_KEY: prestress,
        "mild_fytk": 500.0,
        "mild_fyck": 700.0,
        "mild_futk": 600.0,
        "pre_fytk": 1600.0,
        "pre_futk": 1500.0,
    }

    first = project_io.dump_project({}, scalars)
    tables, loaded = project_io.parse_project(first)
    second = project_io.dump_project(tables, loaded)
    _, reloaded = project_io.parse_project(second)

    for project_text in (first, second):
        assert project_io.project_provenance(project_text)["input_hash_valid"] is True
    assert [
        item["id"]
        for item in reloaded[material_catalog.MILD_CATALOG_KEY]["items"]
    ] == ["M2"]
    assert [
        item["id"]
        for item in reloaded[material_catalog.PRESTRESS_CATALOG_KEY]["items"]
    ] == ["P2"]
    assert reloaded["mild_fyck"] == pytest.approx(700.0)
    assert reloaded["pre_futk"] == pytest.approx(1500.0)


def test_current_schema_extreme_finite_material_laws_round_trip_safely():
    mild = material_catalog.default_catalog("mild")
    mild["items"][0].update(
        preset=material_catalog.CUSTOM_PRESET,
        curve=1,
        active_in_compression=False,
        fytk=1.0,
        fyck=0.0,
        futk=1.0e308,
        eut=1.0e308,
        gamma_y=1.0,
        gamma_u=1.0,
        gamma_E=1.0,
        Es=200.0,
    )
    prestress = material_catalog.default_catalog("prestress")
    prestress["items"][0].update(
        preset=material_catalog.CUSTOM_PRESET,
        curve=6,
        IS=0.0,
        fytk=1.0,
        futk=1.0e308,
        eut=1.0e308,
        gamma_y=1.0,
        gamma_u=1.0,
        gamma_E=1.0,
        Es=200.0,
    )

    first = project_io.dump_project(
        {},
        {
            material_catalog.MILD_CATALOG_KEY: mild,
            material_catalog.PRESTRESS_CATALOG_KEY: prestress,
        },
    )
    tables, loaded = project_io.parse_project(first)
    second = project_io.dump_project(tables, loaded)
    _, reloaded = project_io.parse_project(second)

    for kind in material_catalog.KINDS:
        item = reloaded[material_catalog.catalog_key(kind)]["items"][0]
        material = material_catalog.build_material(item, kind)
        assert material.stress(material.eut) == 1.0e308
        assert math.isfinite(material.stress(0.0035))
    assert project_io.project_provenance(second)["input_hash_valid"] is True


def test_current_schema_round_trip_retains_selected_gamma_v_exactly():
    tables, scalars = _current_project()
    scalars.update({
        "shear_on": True,
        "shear_method": codes.EC2_2023.label,
        "shear_gamma_v": 1.25,
    })

    text = project_io.dump_project(tables, scalars)
    _loaded_tables, loaded = project_io.parse_project(text)
    payload = json.loads(text)

    assert payload["version"] == 27
    assert payload["scalars"]["shear_gamma_v"] == pytest.approx(1.25)
    assert loaded["shear_gamma_v"] == pytest.approx(1.25)


def test_schema_26_active_2023_shear_migrates_to_explicit_default_gamma_v():
    tables, scalars = _current_project()
    scalars.update({
        "shear_on": True,
        "shear_method": codes.EC2_2023.label,
    })
    source = json.dumps(_schema26_payload(tables, scalars))

    _loaded_tables, loaded, info = project_io.parse_project_with_info(source)

    assert loaded["shear_gamma_v"] == pytest.approx(1.40)
    assert info["source_schema_version"] == 26
    assert info["target_schema_version"] == 27
    assert info["migrated"] is True
    assert len(info["migration_warnings"]) == 1
    assert "explicit gamma_V input at 1.40" in info["migration_warnings"][0]
    assert info["migration_provenance"]["shear_gamma_v"] == {
        "defaulted": True,
        "value": 1.40,
        "active_2023_shear": True,
    }


def test_schema_26_inactive_gamma_v_default_is_silent_and_deterministic():
    source = json.dumps(_schema26_payload())

    _loaded_tables, loaded, info = project_io.parse_project_with_info(source)

    assert loaded["shear_gamma_v"] == pytest.approx(1.40)
    assert info["migration_warnings"] == ()
    assert info["migration_provenance"]["shear_gamma_v"] == {
        "defaulted": True,
        "value": 1.40,
        "active_2023_shear": False,
    }


def test_schema_26_2023_shear_links_migrate_gamma_v_with_review_warning():
    tables, scalars = _current_project()
    scalars.update({
        "shear_on": True,
        "shear_method": codes.EC2_2023.label,
        "shear_links": True,
    })
    source = json.dumps(_schema26_payload(tables, scalars))

    _loaded_tables, loaded, info = project_io.parse_project_with_info(source)

    assert loaded["shear_gamma_v"] == pytest.approx(1.40)
    assert len(info["migration_warnings"]) == 1
    assert "explicit gamma_V input at 1.40" in info["migration_warnings"][0]
    assert info["migration_provenance"]["shear_gamma_v"] == {
        "defaulted": True,
        "value": 1.40,
        "active_2023_shear": True,
    }


def test_schema_25_active_2023_shear_migrates_both_bounded_contracts():
    tables, scalars = _current_project()
    scalars.update({
        "shear_on": True,
        "shear_method": codes.EC2_2023.label,
    })
    payload = _schema25_payload(tables, scalars, shared_width=0.0)

    _loaded_tables, loaded, info = project_io.parse_project_with_info(
        json.dumps(payload)
    )

    assert loaded["shear_gamma_v"] == pytest.approx(1.40)
    assert len(info["migration_warnings"]) == 1
    assert "project file used the fixed" in info["migration_warnings"][0]
    assert info["migration_provenance"]["shear_gamma_v"][
        "active_2023_shear"
    ] is True


def test_schema_25_2023_shear_links_migrate_gamma_v_with_review_warning():
    tables, scalars = _current_project()
    scalars.update({
        "shear_on": True,
        "shear_method": codes.EC2_2023.label,
        "shear_links": True,
    })
    payload = _schema25_payload(tables, scalars, shared_width=0.0)

    _loaded_tables, loaded, info = project_io.parse_project_with_info(
        json.dumps(payload)
    )

    assert loaded["shear_gamma_v"] == pytest.approx(1.40)
    assert any(
        "explicit gamma_V input at 1.40" in warning
        for warning in info["migration_warnings"]
    )
    assert info["migration_provenance"]["shear_gamma_v"] == {
        "defaulted": True,
        "value": 1.40,
        "active_2023_shear": True,
    }


@pytest.mark.parametrize(
    "value",
    (
        True,
        False,
        np.bool_(True),
        0.0,
        -1.0,
        float("nan"),
        float("inf"),
        "1.40",
    ),
)
def test_current_schema_rejects_malformed_gamma_v(value):
    tables, scalars = _current_project()
    scalars["shear_gamma_v"] = value

    with pytest.raises(
        ValueError,
        match="shear_gamma_v must be a positive finite real number",
    ):
        project_io.dump_project(tables, scalars)


def test_current_schema_active_2023_shear_requires_gamma_v():
    tables, scalars = _current_project()
    scalars.update({
        "shear_on": True,
        "shear_method": codes.EC2_2023.label,
    })

    with pytest.raises(
        ValueError,
        match="shear_gamma_v is required when the DS/EN",
    ):
        project_io.dump_project(tables, scalars)


def test_current_schema_2023_shear_links_require_gamma_v_on_dump_and_parse():
    tables, scalars = _current_project()
    scalars.update({
        "shear_on": True,
        "shear_method": codes.EC2_2023.label,
        "shear_links": True,
    })
    scalars.pop("shear_gamma_v", None)

    with pytest.raises(
        ValueError,
        match="shear_gamma_v is required when the DS/EN",
    ):
        project_io.dump_project(tables, scalars)

    scalars["shear_gamma_v"] = 1.40
    payload = json.loads(project_io.dump_project(tables, scalars))
    payload["scalars"].pop("shear_gamma_v")
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    with pytest.raises(
        ValueError,
        match="shear_gamma_v is required when the DS/EN",
    ):
        project_io.parse_project(json.dumps(payload))


def test_shared_link_authority_round_trips_and_missing_defaults_false():
    tables, scalars = _current_project()
    scalars.update(
        torsion_on=True,
        shear_links=True,
        torsion_nu_v=True,
    )

    text = project_io.dump_project(tables, scalars)
    _, loaded = project_io.parse_project(text)
    payload = json.loads(text)

    assert payload["version"] == project_io.VERSION
    assert payload["scalars"]["shear_links"] is True
    assert payload["scalars"]["torsion_nu_v"] is True
    assert loaded["shear_links"] is True
    assert loaded["torsion_nu_v"] is True

    missing_payload = json.loads(text)
    missing_payload["scalars"].pop("shear_links")
    missing_payload["scalars"].pop("torsion_nu_v")
    missing_payload["provenance"]["input_sha256"] = (
        project_io._input_digest({
            "tables": missing_payload["tables"],
            "scalars": missing_payload["scalars"],
        })
    )
    missing_text = json.dumps(missing_payload)
    missing_tables, missing_loaded = project_io.parse_project(missing_text)

    assert missing_payload["version"] == project_io.VERSION
    assert "shear_links" not in missing_payload["scalars"]
    assert "torsion_nu_v" not in missing_payload["scalars"]
    assert missing_loaded["shear_links"] is False
    assert missing_loaded["torsion_nu_v"] is False

    resaved = json.loads(
        project_io.dump_project(missing_tables, missing_loaded)
    )
    assert resaved["version"] == project_io.VERSION
    assert resaved["scalars"]["shear_links"] is False
    assert resaved["scalars"]["torsion_nu_v"] is False


def test_torsion_applicability_choices_round_trip_and_missing_defaults_safe():
    tables, scalars = _current_project()
    scalars.update(
        torsion_design_basis=capacity.TORSION_DESIGN_COMPATIBILITY_RESIDUAL,
        torsion_member_scope=capacity.TORSION_MEMBER_CLOSED,
    )

    text = project_io.dump_project(tables, scalars)
    loaded_tables, loaded = project_io.parse_project(text)

    assert loaded["torsion_design_basis"] == (
        capacity.TORSION_DESIGN_COMPATIBILITY_RESIDUAL
    )
    assert loaded["torsion_member_scope"] == capacity.TORSION_MEMBER_CLOSED
    assert json.loads(
        project_io.dump_project(loaded_tables, loaded)
    )["scalars"]["torsion_design_basis"] == (
        capacity.TORSION_DESIGN_COMPATIBILITY_RESIDUAL
    )

    payload = json.loads(text)
    payload["scalars"].pop("torsion_design_basis")
    payload["scalars"].pop("torsion_member_scope")
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    _, missing = project_io.parse_project(json.dumps(payload))

    assert missing["torsion_design_basis"] == (
        capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
    )
    assert missing["torsion_member_scope"] == (
        capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
    )


def test_torsion_case_authorities_round_trip_and_follow_case_identity():
    tables, scalars = _current_project()
    first_name = "Only characteristic action"
    second_name = "Compatibility action"
    second = tables[load_cases.PLASTIC_TABLE_KEY].iloc[0].copy()
    second["name"] = second_name
    second["t_ed_knm"] = -7.0
    tables[load_cases.PLASTIC_TABLE_KEY] = load_cases.normalise_table(
        pd.concat(
            [
                tables[load_cases.PLASTIC_TABLE_KEY],
                pd.DataFrame([second]),
            ],
            ignore_index=True,
        ),
        load_cases.PLASTIC_TABLE_KEY,
    )
    scalars[capacity.TORSION_CASE_AUTHORITIES_KEY] = {
        first_name: {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                capacity.TORSION_DESIGN_EQUILIBRIUM
            ),
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: capacity.TORSION_MEMBER_CLOSED,
        },
        second_name: {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                capacity.TORSION_DESIGN_COMPATIBILITY_MEMBER
            ),
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: capacity.TORSION_MEMBER_OPEN,
        },
        "Deleted action": {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                capacity.TORSION_DESIGN_EQUILIBRIUM
            ),
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: capacity.TORSION_MEMBER_CLOSED,
        },
    }

    text = project_io.dump_project(tables, scalars)
    loaded_tables, loaded = project_io.parse_project(text)
    assert list(loaded[capacity.TORSION_CASE_AUTHORITIES_KEY]) == [
        first_name,
        second_name,
    ]
    assert loaded[capacity.TORSION_CASE_AUTHORITIES_KEY][first_name] == {
        capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
            capacity.TORSION_DESIGN_EQUILIBRIUM
        ),
        capacity.TORSION_CASE_MEMBER_SCOPE_KEY: capacity.TORSION_MEMBER_CLOSED,
    }
    assert loaded[capacity.TORSION_CASE_AUTHORITIES_KEY][second_name][
        capacity.TORSION_CASE_DESIGN_BASIS_KEY
    ] == capacity.TORSION_DESIGN_COMPATIBILITY_MEMBER

    changed = dict(loaded)
    changed[capacity.TORSION_CASE_AUTHORITIES_KEY] = {
        **loaded[capacity.TORSION_CASE_AUTHORITIES_KEY],
        second_name: {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                capacity.TORSION_DESIGN_COMPATIBILITY_RESIDUAL
            ),
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: capacity.TORSION_MEMBER_CLOSED,
        },
    }
    changed_payload = json.loads(project_io.dump_project(loaded_tables, changed))
    original_payload = json.loads(text)
    assert changed_payload["provenance"]["input_sha256"] != (
        original_payload["provenance"]["input_sha256"]
    )

    reordered = dict(loaded_tables)
    reordered[load_cases.PLASTIC_TABLE_KEY] = (
        loaded_tables[load_cases.PLASTIC_TABLE_KEY].iloc[::-1].reset_index(drop=True)
    )
    _, reordered_scalars = project_io.parse_project(
        project_io.dump_project(reordered, loaded)
    )
    assert list(reordered_scalars[capacity.TORSION_CASE_AUTHORITIES_KEY]) == [
        second_name,
        first_name,
    ]
    assert reordered_scalars[capacity.TORSION_CASE_AUTHORITIES_KEY][second_name][
        capacity.TORSION_CASE_DESIGN_BASIS_KEY
    ] == capacity.TORSION_DESIGN_COMPATIBILITY_MEMBER

    renamed = dict(loaded_tables)
    renamed_frame = loaded_tables[load_cases.PLASTIC_TABLE_KEY].copy(deep=True)
    renamed_frame.at[0, "name"] = "Renamed action"
    renamed[load_cases.PLASTIC_TABLE_KEY] = renamed_frame
    _, renamed_scalars = project_io.parse_project(
        project_io.dump_project(renamed, loaded)
    )
    assert "Only characteristic action" not in renamed_scalars[
        capacity.TORSION_CASE_AUTHORITIES_KEY
    ]
    assert renamed_scalars[capacity.TORSION_CASE_AUTHORITIES_KEY][
        "Renamed action"
    ] == {
        capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
            capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
        ),
        capacity.TORSION_CASE_MEMBER_SCOPE_KEY: (
            capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
        ),
    }


def test_missing_current_torsion_case_mapping_fails_closed_for_every_case():
    tables, scalars = _current_project()
    text = project_io.dump_project(tables, scalars)
    payload = json.loads(text)
    payload["scalars"].pop(capacity.TORSION_CASE_AUTHORITIES_KEY)
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })

    _, loaded = project_io.parse_project(json.dumps(payload))

    assert loaded[capacity.TORSION_CASE_AUTHORITIES_KEY] == {
        "Only characteristic action": {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
            ),
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: (
                capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
            ),
        }
    }


@pytest.mark.parametrize("identity", ("duplicate", "casefold", "cross-table", "blank"))
def test_hash_valid_project_rejects_ambiguous_case_identities_before_authority(
    identity,
):
    tables, scalars = _current_project()
    payload = json.loads(project_io.dump_project(tables, scalars))
    plastic = payload["tables"][load_cases.PLASTIC_TABLE_KEY]
    elastic = payload["tables"][load_cases.ELASTIC_TABLE_KEY]
    name_index = plastic["columns"].index(load_cases.NAME)

    if identity in {"duplicate", "casefold"}:
        duplicate = copy.deepcopy(plastic["rows"][0])
        duplicate[name_index] = (
            "ONLY CHARACTERISTIC ACTION"
            if identity == "casefold"
            else "Only characteristic action"
        )
        plastic["rows"].append(duplicate)
    elif identity == "cross-table":
        elastic_name_index = elastic["columns"].index(load_cases.NAME)
        elastic["rows"][0][elastic_name_index] = "Only characteristic action"
    else:
        plastic["rows"][0][name_index] = ""

    payload["scalars"][capacity.TORSION_CASE_AUTHORITIES_KEY] = {
        "Only characteristic action": {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                capacity.TORSION_DESIGN_EQUILIBRIUM
            ),
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: (
                capacity.TORSION_MEMBER_CLOSED
            ),
        }
    }
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })

    with pytest.raises(project_io.ProjectInputError) as caught:
        project_io.parse_project(json.dumps(payload))

    assert project_io.engineer_error_message(caught.value) == (
        "the project file contains an invalid input value"
    )


@pytest.mark.parametrize(
    "invalid",
    (
        True,
        [],
        {"Only characteristic action": True},
        {
            " Only characteristic action": {
                "design_basis": capacity.TORSION_DESIGN_EQUILIBRIUM,
                "member_scope": capacity.TORSION_MEMBER_CLOSED,
            }
        },
        {
            "Only characteristic action": {
                "design_basis": capacity.TORSION_DESIGN_EQUILIBRIUM,
            }
        },
        {
            "Only characteristic action": {
                "design_basis": capacity.TORSION_DESIGN_EQUILIBRIUM,
                "member_scope": True,
            }
        },
        {
            "Only characteristic action": {
                "design_basis": "Equilibrium torsion",
                "member_scope": capacity.TORSION_MEMBER_CLOSED,
            }
        },
    ),
)
def test_torsion_case_authority_mapping_rejects_malformed_values(invalid):
    tables, scalars = _current_project()
    valid_text = project_io.dump_project(tables, scalars)
    scalars[capacity.TORSION_CASE_AUTHORITIES_KEY] = invalid
    with pytest.raises(project_io.ProjectInputError):
        project_io.dump_project(tables, scalars)

    payload = json.loads(valid_text)
    payload["scalars"][capacity.TORSION_CASE_AUTHORITIES_KEY] = invalid
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io.parse_project(json.dumps(payload))
    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file contains an invalid input value"
    )


@pytest.mark.parametrize("source_version", (25, 26, 27))
def test_omitted_torsion_applicability_defaults_safe_in_supported_schemas(
    source_version,
):
    tables, scalars = _current_project()
    if source_version == 25:
        payload = _schema25_payload(tables, scalars)
    elif source_version == 26:
        payload = _schema26_payload(tables, scalars)
    else:
        payload = json.loads(project_io.dump_project(tables, scalars))
    payload["scalars"].pop("torsion_design_basis", None)
    payload["scalars"].pop("torsion_member_scope", None)
    payload["scalars"].pop(capacity.TORSION_CASE_AUTHORITIES_KEY, None)
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })

    _, loaded = project_io.parse_project(json.dumps(payload))

    assert loaded["torsion_design_basis"] == (
        capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
    )
    assert loaded["torsion_member_scope"] == (
        capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
    )
    assert loaded[capacity.TORSION_CASE_AUTHORITIES_KEY] == {
        "Only characteristic action": {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
            ),
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: (
                capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
            ),
        }
    }


@pytest.mark.parametrize(
    "key,invalid",
    (
        ("torsion_design_basis", True),
        ("torsion_design_basis", 1),
        ("torsion_design_basis", 1.0),
        ("torsion_design_basis", "Equilibrium torsion"),
        ("torsion_design_basis", "equilibrium torsion"),
        ("torsion_member_scope", False),
        ("torsion_member_scope", 0),
        ("torsion_member_scope", 0.0),
        ("torsion_member_scope", "Closed section"),
        ("torsion_member_scope", "Not established "),
    ),
)
def test_torsion_applicability_choices_are_strict_exact_text(key, invalid):
    tables, scalars = _current_project()
    valid_text = project_io.dump_project(tables, scalars)
    scalars[key] = invalid

    with pytest.raises(ValueError, match=rf"^{key} "):
        project_io.dump_project(tables, scalars)

    payload = json.loads(valid_text)
    payload["scalars"][key] = invalid
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    with pytest.raises(project_io.ProjectInputError):
        project_io.parse_project(json.dumps(payload))


@pytest.mark.parametrize("key", ("shear_links", "torsion_nu_v"))
@pytest.mark.parametrize("invalid", (None, 0, 1, "true", [], {}))
def test_shared_link_authorities_must_be_serialized_booleans(key, invalid):
    tables, scalars = _current_project()
    valid_text = project_io.dump_project(tables, scalars)
    scalars[key] = invalid

    with pytest.raises(ValueError, match=rf"^{key} must be a Boolean$"):
        project_io.dump_project(tables, scalars)

    payload = json.loads(valid_text)
    payload["scalars"][key] = invalid
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    with pytest.raises(ValueError, match=rf"^{key} must be a Boolean$"):
        project_io.parse_project(json.dumps(payload))


@pytest.mark.parametrize(
    ("shape", "settings"),
    [
        (
            "Trapezoid",
            {"qsv_trap_bottom_mm": 900.0, "qsv_trap_top_mm": 550.0,
             "qsv_trap_h_mm": 750.0},
        ),
        (
            "L-section",
            {"qsv_l_b_mm": 950.0, "qsv_l_h_mm": 850.0,
             "qsv_l_web_mm": 180.0, "qsv_l_flange_mm": 220.0},
        ),
        (
            "I-section",
            {"qsv_i_bf_mm": 850.0, "qsv_i_tf_mm": 180.0,
             "qsv_i_bw_mm": 240.0, "qsv_i_hw_mm": 650.0},
        ),
        (
            "U-section",
            {"qsv_u_b_mm": 900.0, "qsv_u_h_mm": 850.0,
             "qsv_u_web_mm": 160.0, "qsv_u_base_mm": 210.0},
        ),
        (
            "Annulus",
            {"qsv_annulus_outer_mm": 900.0, "qsv_annulus_inner_mm": 450.0},
        ),
        (
            "T-section",
            {"qsv_t_orientation": "Flange at bottom"},
        ),
        (
            "Slab strip",
            {"qsv_qs_rebar_mode": "By spacing", "qsv_bot_s": 200.0,
             "qsv_top_s": 250.0, "qsv_bot_c_mm": 45.0,
             "qsv_top_c_mm": 55.0},
        ),
    ],
)
def test_expanded_quick_section_settings_round_trip(shape, settings):
    tables, scalars = _current_project()
    expected = {"qsv_shape": shape, **settings}
    scalars.update(expected)

    text = project_io.dump_project(tables, scalars)
    _loaded_tables, loaded_scalars = project_io.parse_project(text)

    assert {key: loaded_scalars[key] for key in expected} == expected
    assert project_io.project_provenance(text)["input_hash_valid"] is True


def test_schema_27_serializes_exact_three_crack_width_inputs():
    tables, scalars = _current_project()
    scalars.update(
        sls_long_term_permitted_crack_width_mm=0.25,
        sls_short_term_permitted_crack_width_mm=0.30,
        sls_heightened_permitted_crack_width_mm=0.20,
    )

    payload = json.loads(project_io.dump_project(tables, scalars))
    elastic = payload["tables"][load_cases.ELASTIC_TABLE_KEY]

    assert payload["version"] == 27
    assert tuple(elastic["columns"]) == load_cases.ELASTIC_COLUMNS
    assert project_io.LEGACY_SHARED_CRACK_WIDTH_KEY not in payload["scalars"]
    assert payload["scalars"][
        "sls_long_term_permitted_crack_width_mm"
    ] == pytest.approx(0.25)
    assert payload["scalars"][
        "sls_short_term_permitted_crack_width_mm"
    ] == pytest.approx(0.30)
    assert payload["scalars"][
        "sls_heightened_permitted_crack_width_mm"
    ] == pytest.approx(0.20)


def test_schema_27_signed_zero_crack_limits_use_the_canonical_zero_hash():
    tables, zero_scalars = _current_project()
    signed_scalars = copy.deepcopy(zero_scalars)
    for key in (
        "sls_long_term_permitted_crack_width_mm",
        "sls_short_term_permitted_crack_width_mm",
        "sls_heightened_permitted_crack_width_mm",
    ):
        zero_scalars[key] = 0.0
        signed_scalars[key] = -0.0

    zero_payload = json.loads(project_io.dump_project(tables, zero_scalars))
    signed_payload = json.loads(project_io.dump_project(tables, signed_scalars))

    for key in (
        "sls_long_term_permitted_crack_width_mm",
        "sls_short_term_permitted_crack_width_mm",
        "sls_heightened_permitted_crack_width_mm",
    ):
        assert signed_payload["scalars"][key] == 0.0
        assert not np.signbit(signed_payload["scalars"][key])
    assert signed_payload["provenance"]["input_sha256"] == (
        zero_payload["provenance"]["input_sha256"]
    )


@pytest.mark.parametrize("shared", (_MISSING, None, "", "   ", 0.0))
def test_schema_25_blank_or_zero_shared_width_migrates_to_three_zeroes(shared):
    payload = _schema25_payload(shared_width=shared)
    source = json.dumps(payload)

    _tables, scalars, info = project_io.parse_project_with_info(source)

    assert info["migrated"] is True
    assert info["source_schema_version"] == 25
    assert info["target_schema_version"] == 27
    assert info["migration_warnings"] == ()
    assert scalars["sls_long_term_permitted_crack_width_mm"] == 0.0
    assert scalars["sls_short_term_permitted_crack_width_mm"] == 0.0
    assert scalars["sls_heightened_permitted_crack_width_mm"] == 0.0


def test_schema_25_positive_shared_width_splits_only_into_ordinary_when_disabled():
    tables, scalars = _current_project()
    scalars["sls_heightened_on"] = False
    payload = _schema25_payload(tables, scalars, shared_width=0.30)

    _tables, migrated, info = project_io.parse_project_with_info(
        json.dumps(payload)
    )

    assert migrated["sls_long_term_permitted_crack_width_mm"] == pytest.approx(
        0.30
    )
    assert migrated["sls_short_term_permitted_crack_width_mm"] == pytest.approx(
        0.30
    )
    assert migrated["sls_heightened_permitted_crack_width_mm"] == 0.0
    assert len(info["migration_warnings"]) == 1
    assert "copied" in info["migration_warnings"][0]
    assert info["migration_provenance"] == {
        "source_key": project_io.LEGACY_SHARED_CRACK_WIDTH_KEY,
        "shared_value_mm": 0.30,
        "long_term_value_mm": 0.30,
        "short_term_value_mm": 0.30,
        "heightened_value_mm": 0.0,
        "heightened_preserved": False,
        "shear_gamma_v": {
            "defaulted": True,
            "value": 1.40,
            "active_2023_shear": False,
        },
    }


def test_schema_25_enabled_heightened_preserves_shared_formula_operand():
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    payload = _schema25_payload(
        tables, scalars, shared_width=0.20
    )

    _tables, migrated, info = project_io.parse_project_with_info(
        json.dumps(payload)
    )

    assert migrated["sls_long_term_permitted_crack_width_mm"] == pytest.approx(
        0.20
    )
    assert migrated["sls_short_term_permitted_crack_width_mm"] == pytest.approx(
        0.20
    )
    assert migrated["sls_heightened_permitted_crack_width_mm"] == pytest.approx(
        0.20
    )
    assert info["migration_provenance"]["heightened_preserved"] is True


@pytest.mark.parametrize("shared", (_MISSING, None, "", 0.0))
def test_schema_25_enabled_heightened_requires_positive_shared_operand(shared):
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    payload = _schema25_payload(tables, scalars, shared_width=shared)

    with pytest.raises(ValueError, match="permitted crack width must be positive"):
        project_io.parse_project(json.dumps(payload))


def test_schema_25_migration_does_not_mutate_source_and_resaves_current_keys():
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    payload = _schema25_payload(
        tables, scalars, shared_width=0.20
    )
    source = json.dumps(payload)
    original = source[:]

    migrated_tables, migrated_scalars, info = (
        project_io.parse_project_with_info(source)
    )

    assert source == original
    assert project_io.project_provenance(source)["input_hash_valid"] is True
    assert info["source_schema_version"] == 25

    resaved = json.loads(
        project_io.dump_project(migrated_tables, migrated_scalars)
    )
    assert resaved["version"] == 27
    assert project_io.LEGACY_SHARED_CRACK_WIDTH_KEY not in resaved["scalars"]
    assert {
        "sls_long_term_permitted_crack_width_mm",
        "sls_short_term_permitted_crack_width_mm",
        "sls_heightened_permitted_crack_width_mm",
    }.issubset(resaved["scalars"])


@pytest.mark.parametrize(
    "invalid",
    (True, False, -0.1, "0.30", "NaN"),
)
def test_schema_25_rejects_malformed_shared_width(invalid):
    payload = _schema25_payload(shared_width=invalid)

    with pytest.raises(ValueError, match="non-negative finite real number"):
        project_io.parse_project(json.dumps(payload))


@pytest.mark.parametrize(
    "key",
    (
        "sls_long_term_permitted_crack_width_mm",
        "sls_short_term_permitted_crack_width_mm",
        "sls_heightened_permitted_crack_width_mm",
    ),
)
@pytest.mark.parametrize(
    "invalid",
    (
        True,
        np.bool_(True),
        np.bool_(False),
        -0.1,
        "0.30",
        float("nan"),
        float("inf"),
    ),
)
def test_schema_27_rejects_malformed_width_inputs(key, invalid):
    tables, scalars = _current_project()
    scalars[key] = invalid

    with pytest.raises(ValueError, match="non-negative finite real number"):
        project_io.dump_project(tables, scalars)


def test_direction_alias_round_trips_outside_calculation_inputs():
    tables, scalars = _current_project()
    without_alias_hash = project_io.input_sha256(tables, scalars)
    without_alias_persistence = project_io.persistence_sha256(tables, scalars)
    scalars[modelled_direction.ALIAS_KEY] = "  span   direction  "

    text = project_io.dump_project(tables, scalars)
    loaded_tables, loaded_scalars = project_io.parse_project(text)
    payload = json.loads(text)

    assert payload["presentation"] == {
        modelled_direction.ALIAS_KEY: "span direction",
        project_io.REPORT_PROFILE_KEY: "Standard",
    }
    assert modelled_direction.ALIAS_KEY not in payload["scalars"]
    assert loaded_scalars[modelled_direction.ALIAS_KEY] == "span direction"
    assert project_io.input_sha256(loaded_tables, loaded_scalars) == (
        without_alias_hash
    )
    assert project_io.persistence_sha256(
        loaded_tables, loaded_scalars
    ) != without_alias_persistence


def test_report_profile_is_presentation_only_but_changes_persistence_identity():
    tables, scalars = _current_project()
    standard = {**scalars, project_io.REPORT_PROFILE_KEY: "Standard"}
    audit = {**scalars, project_io.REPORT_PROFILE_KEY: "Audit"}

    assert project_io.input_sha256(tables, standard) == (
        project_io.input_sha256(tables, audit)
    )
    assert project_io.persistence_sha256(tables, standard) != (
        project_io.persistence_sha256(tables, audit)
    )

    payload = json.loads(project_io.dump_project(tables, audit))
    _, loaded = project_io.parse_project(json.dumps(payload))
    assert project_io.REPORT_PROFILE_KEY not in payload["scalars"]
    assert payload["presentation"][project_io.REPORT_PROFILE_KEY] == "Audit"
    assert loaded[project_io.REPORT_PROFILE_KEY] == "Audit"


@pytest.mark.parametrize(
    ("legacy_label", "expected"),
    (
        ("Default report", "Standard"),
        ("Default report + QA appendix", "Audit"),
        ("Brief", "Brief"),
        ("Standard", "Standard"),
        ("Audit", "Audit"),
    ),
)
def test_current_schema_migrates_exact_legacy_report_labels_and_scalar_placement(
    legacy_label,
    expected,
):
    tables, scalars = _current_project()
    payload = json.loads(project_io.dump_project(tables, scalars))
    payload["presentation"].pop(project_io.REPORT_PROFILE_KEY)
    payload["scalars"][project_io.REPORT_PROFILE_KEY] = legacy_label
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })

    text = json.dumps(payload)
    assert project_io.project_provenance(text)["input_hash_valid"] is True
    _, loaded = project_io.parse_project(text)
    assert loaded[project_io.REPORT_PROFILE_KEY] == expected


@pytest.mark.parametrize(
    "value",
    ("default report", "Default report ", "Unknown", 1, ["Audit"]),
)
def test_unknown_or_inexact_persisted_report_profile_fails_closed(value):
    tables, scalars = _current_project()
    payload = json.loads(project_io.dump_project(tables, scalars))
    payload["presentation"][project_io.REPORT_PROFILE_KEY] = value
    text = json.dumps(payload)

    assert project_io.project_provenance(text)["input_hash_valid"] is True
    with pytest.raises(ValueError, match="unknown persisted report profile"):
        project_io.parse_project(text)


@pytest.mark.parametrize(
    ("operation", "expected"),
    (
        (
            lambda: project_io._decode("not JSON"),
            "the selected file is not a readable Sector project",
        ),
        (
            lambda: project_io._decode(json.dumps({
                "format": project_io.FORMAT,
                "version": 99,
            })),
            "the project file contains information that this version of Sector "
            "cannot read",
        ),
        (
            lambda: project_io.normalise_report_profile("Retired report"),
            "the saved report type is not available in this version of Sector",
        ),
    ),
)
def test_authored_project_validation_paths_retain_engineering_guidance(
    operation,
    expected,
):
    with pytest.raises(ValueError) as caught:
        operation()

    message = project_io.engineer_error_message(caught.value)

    assert message == expected
    assert not re.search(
        r"\b(?:sha(?:-?256)?|schema|payload|hash|contract|json|provenance)\b",
        message,
        flags=re.IGNORECASE,
    )


def test_plain_project_exception_is_never_promoted_from_its_text(caplog):
    hostile = "modelled direction alias is valid in GitHub PR #77 payload"

    message = project_io.engineer_error_message(ValueError(hostile))

    assert message == "the project file could not be read"
    assert hostile not in message
    assert "Suppressed untrusted diagnostic" in caplog.text


def test_direction_alias_validation_is_separate_from_input_integrity():
    tables, scalars = _current_project()
    payload = json.loads(project_io.dump_project(tables, scalars))
    payload["presentation"][modelled_direction.ALIAS_KEY] = "span\ndirection"

    assert project_io.project_provenance(
        json.dumps(payload)
    )["input_hash_valid"] is True
    with pytest.raises(
        project_io.ProjectInputError,
        match="invalid modelled-direction description",
    ) as caught:
        project_io.parse_project(json.dumps(payload))
    assert project_io.engineer_error_message(caught.value) == (
        "the modelled-direction description must be a single line of at most "
        "60 characters"
    )


def test_direction_alias_length_limit_is_symmetric_and_presentation_only():
    tables, scalars = _current_project()
    too_long = "x" * (modelled_direction.MAX_ALIAS_CHARS + 1)
    message = "^modelled direction alias must be at most 60 characters$"

    with pytest.raises(ValueError, match=message):
        project_io.dump_project(
            tables,
            {**scalars, modelled_direction.ALIAS_KEY: too_long},
        )

    payload = json.loads(project_io.dump_project(tables, scalars))
    payload["presentation"][modelled_direction.ALIAS_KEY] = too_long
    text = json.dumps(payload)

    assert project_io.project_provenance(text)["input_hash_valid"] is True
    with pytest.raises(
        project_io.ProjectInputError,
        match="invalid modelled-direction description",
    ) as caught:
        project_io.parse_project(text)
    assert project_io.engineer_error_message(caught.value) == (
        "the modelled-direction description must be a single line of at most "
        "60 characters"
    )


def test_project_round_trip_preserves_decimal_precision_and_blank_action_zero():
    tables, scalars = _current_project()
    tables[load_cases.PLASTIC_TABLE_KEY] = load_cases.normalise_table(
        [{
            "name": "Decimal input",
            "n_ed_kn": "1,23456789012345",
            "mx_ed_knm": "",
        }],
        load_cases.PLASTIC_TABLE_KEY,
    )

    text = project_io.dump_project(tables, scalars)
    loaded, _loaded_scalars = project_io.parse_project(text)
    row = loaded[load_cases.PLASTIC_TABLE_KEY].iloc[0]

    assert row["n_ed_kn"] == pytest.approx(1.23456789012345)
    assert row["mx_ed_knm"] == 0.0
    assert project_io.project_provenance(text)["input_hash_valid"] is True


@pytest.mark.parametrize(
    ("table_key", "row", "match"),
    [
        (
            load_cases.ELASTIC_TABLE_KEY,
            {"name": "Bad", "mx_short_ed_knm": "12abc"},
            "elastic_cases_base row 1: mx_short_ed_knm",
        ),
        (
            fatigue_inputs.SPECTRUM_TABLE_KEY,
            {
                "spectrum": "Traffic",
                "name": "Bad bin",
                "cycles": "10",
                "n_short_ed_kn": "12abc",
            },
            "fatigue_spectrum_base row 1: n_short_ed_kn",
        ),
    ],
)
def test_project_dump_rejects_malformed_nonblank_decimal_without_json_null(
    table_key, row, match
):
    tables, scalars = _current_project()
    tables[table_key] = (
        load_cases.normalise_table([row], table_key)
        if table_key in load_cases.CASE_TABLE_KEYS
        else fatigue_inputs.normalise_spectrum_table([row])
    )

    with pytest.raises(ValueError, match=match):
        project_io.dump_project(tables, scalars)


@pytest.mark.parametrize(
    ("table_key", "column", "entered"),
    [
        (load_cases.PLASTIC_TABLE_KEY, "n_ed_kn", "12abc"),
        (load_cases.ELASTIC_TABLE_KEY, "mx_short_ed_knm", True),
        (fatigue_inputs.SPECTRUM_TABLE_KEY, "cycles", "10 cycles"),
    ],
)
def test_project_parse_rejects_hash_valid_malformed_nonblank_decimal(
    table_key,
    column,
    entered,
):
    tables, scalars = _current_project()
    if table_key == fatigue_inputs.SPECTRUM_TABLE_KEY:
        tables[table_key] = fatigue_inputs.normalise_spectrum_table(
            [{"spectrum": "Traffic", "name": "Bin 1", "cycles": 10.0}]
        )
    data = json.loads(project_io.dump_project(tables, scalars))
    encoded = data["tables"][table_key]
    encoded["rows"][0][encoded["columns"].index(column)] = entered
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(
        ValueError,
        match=rf"{re.escape(table_key)} row 1: {re.escape(column)} contains "
        r"malformed decimal input",
    ):
        project_io.parse_project(json.dumps(data))


def test_project_dump_allows_a_wholly_blank_fatigue_editor_row():
    tables, scalars = _current_project()
    tables[fatigue_inputs.SPECTRUM_TABLE_KEY] = (
        fatigue_inputs.normalise_spectrum_table([{}])
    )

    text = project_io.dump_project(tables, scalars)
    loaded, _loaded_scalars = project_io.parse_project(text)

    assert len(loaded[fatigue_inputs.SPECTRUM_TABLE_KEY]) == 1
    assert pd.isna(
        loaded[fatigue_inputs.SPECTRUM_TABLE_KEY].loc[0, "cycles"]
    )


@pytest.mark.parametrize(
    ("table_key", "kind", "assigned_id", "catalog_key", "catalog"),
    [
        (
            "bars_base",
            "bar",
            "M2",
            material_catalog.MILD_CATALOG_KEY,
            {
                "items": [
                    material_catalog.default_entry("mild", material_id="M1"),
                    material_catalog.default_entry("mild", material_id="bad"),
                ]
            },
        ),
        (
            "tendons_base",
            "tendon",
            "P2",
            material_catalog.PRESTRESS_CATALOG_KEY,
            {
                "items": [
                    material_catalog.default_entry(
                        "prestress", material_id="P1"
                    ),
                    material_catalog.default_entry(
                        "prestress", material_id="bad"
                    ),
                ]
            },
        ),
    ],
)
def test_project_catalog_repair_never_rebinds_assigned_material_gap(
    table_key, kind, assigned_id, catalog_key, catalog
):
    tables, scalars = _current_project()
    tables[table_key] = reinforcement_table.normalise_table(
        [{
            reinforcement_table.X: 0.0,
            reinforcement_table.Y: 0.0,
            reinforcement_table.SIZE_MODE: reinforcement_table.AREA_MODE,
            reinforcement_table.AREA: 100.0,
            reinforcement_table.MATERIAL_ID: assigned_id,
        }],
        kind,
    )
    scalars[catalog_key] = catalog

    with pytest.raises(ValueError, match=assigned_id):
        project_io.dump_project(tables, scalars)


def test_project_catalog_repair_never_rebinds_active_capacity_material_gap():
    tables, scalars = _current_project()
    scalars.update(
        shear_on=True,
        capacity_steel_material_id="M2",
        mild_material_catalog={
            "items": [
                material_catalog.default_entry("mild", material_id="M1"),
                material_catalog.default_entry("mild", material_id="bad"),
            ]
        },
    )

    with pytest.raises(ValueError, match="M2"):
        project_io.dump_project(tables, scalars)


def test_project_catalog_repair_never_rebinds_assigned_fatigue_gap():
    tables, scalars = _current_project()
    tables["bars_base"] = reinforcement_table.normalise_table(
        [{
            reinforcement_table.X: 0.0,
            reinforcement_table.Y: 0.0,
            reinforcement_table.SIZE_MODE: reinforcement_table.AREA_MODE,
            reinforcement_table.AREA: 100.0,
            reinforcement_table.MATERIAL_ID: "M1",
            reinforcement_table.FATIGUE_DETAIL_ID: "F2",
        }],
        "bar",
    )
    scalars[material_catalog.MILD_CATALOG_KEY] = (
        material_catalog.default_catalog("mild")
    )
    scalars[fatigue_inputs.DETAIL_CATALOG_KEY] = {
        "items": [
            fatigue_inputs.default_entry(detail_id="F1"),
            fatigue_inputs.default_entry(detail_id="bad"),
        ]
    }

    with pytest.raises(ValueError, match="F2"):
        project_io.dump_project(tables, scalars)


def test_parse_rejects_hash_valid_project_with_missing_assigned_material():
    tables, scalars = _current_project()
    tables["bars_base"] = reinforcement_table.normalise_table(
        [{
            reinforcement_table.X: 0.0,
            reinforcement_table.Y: 0.0,
            reinforcement_table.SIZE_MODE: reinforcement_table.AREA_MODE,
            reinforcement_table.AREA: 100.0,
            reinforcement_table.MATERIAL_ID: "M1",
        }],
        "bar",
    )
    scalars[material_catalog.MILD_CATALOG_KEY] = (
        material_catalog.default_catalog("mild")
    )
    data = json.loads(project_io.dump_project(tables, scalars))
    bar_table = data["tables"]["bars_base"]
    material_column = bar_table["columns"].index(
        reinforcement_table.MATERIAL_ID
    )
    bar_table["rows"][0][material_column] = "M2"
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(ValueError, match="M2"):
        project_io.parse_project(json.dumps(data))


def test_parse_rejects_hash_valid_project_with_missing_capacity_material():
    tables, scalars = _current_project()
    scalars.update(shear_on=True, capacity_steel_material_id="M1")
    scalars[material_catalog.MILD_CATALOG_KEY] = (
        material_catalog.default_catalog("mild")
    )
    data = json.loads(project_io.dump_project(tables, scalars))
    data["scalars"]["capacity_steel_material_id"] = "M2"
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(ValueError, match="M2"):
        project_io.parse_project(json.dumps(data))


@pytest.mark.parametrize(
    ("key", "label"),
    [
        *(
            ("shear_method", label)
            for label in capacity.SHEAR_METHODS
        ),
        *(
            ("torsion_method", label)
            for label in capacity.SHEAR_CODES
        ),
        *(
            ("combined_method", label)
            for label in capacity.SHEAR_CODES
        ),
    ],
)
def test_current_schema_retains_every_capacity_method_identity(key, label):
    tables, scalars = _current_project()
    scalars[key] = label

    first = project_io.dump_project(tables, scalars)
    loaded_tables, loaded_scalars = project_io.parse_project(first)
    second = project_io.dump_project(loaded_tables, loaded_scalars)
    _, reloaded_scalars = project_io.parse_project(second)

    assert loaded_scalars[key] == label
    assert reloaded_scalars[key] == label
    assert project_io.project_provenance(first)["input_hash_valid"] is True
    assert project_io.project_provenance(second)["input_hash_valid"] is True


def test_current_schema_keeps_dk_only_route_setting_dormant_under_base_en():
    tables, scalars = _current_project()
    scalars.update(
        combined_on=True,
        combined_method=codes.EC2_2005.label,
        combined_mv_independent=True,
    )

    first = project_io.dump_project(tables, scalars)
    loaded_tables, loaded_scalars = project_io.parse_project(first)
    second = project_io.dump_project(loaded_tables, loaded_scalars)
    _, reloaded_scalars = project_io.parse_project(second)

    assert loaded_scalars["combined_method"] == codes.EC2_2005.label
    assert loaded_scalars["combined_mv_independent"] is True
    assert reloaded_scalars["combined_method"] == codes.EC2_2005.label
    assert reloaded_scalars["combined_mv_independent"] is True
    assert project_io.project_provenance(first)["input_hash_valid"] is True
    assert project_io.project_provenance(second)["input_hash_valid"] is True


@pytest.mark.parametrize(
    "key",
    ["shear_method", "torsion_method", "combined_method"],
)
@pytest.mark.parametrize(
    "invalid",
    ["", "unsupported method"],
)
def test_current_schema_rejects_present_unsupported_capacity_method(
    key,
    invalid,
):
    tables, scalars = _current_project()
    scalars[key] = invalid

    with pytest.raises(capacity.CapacityMethodError, match="unsupported"):
        project_io.dump_project(tables, scalars)


@pytest.mark.parametrize(
    ("key", "label"),
    [
        ("shear_method", codes.EC2_2005_DKNA.label),
        ("torsion_method", codes.EC2_2005.label),
        ("combined_method", codes.EC2_2005_DKNA.label),
    ],
)
def test_current_loader_rejects_coherently_rehashed_unsupported_method(
    key,
    label,
):
    tables, scalars = _current_project()
    scalars[key] = label
    data = json.loads(project_io.dump_project(tables, scalars))
    data["scalars"][key] = "unsupported method"
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(capacity.CapacityMethodError, match="unsupported"):
        project_io.parse_project(json.dumps(data))


def test_corrupt_current_input_is_rejected_by_hash():
    tables, scalars = _current_project()
    data = json.loads(project_io.dump_project(tables, scalars))
    data["scalars"]["conc_gamma_c"] = 2.0

    with pytest.raises(ValueError, match="hash mismatch"):
        project_io.parse_project(json.dumps(data))


@pytest.mark.parametrize("version", (23, 24))
def test_retired_schemas_name_the_current_and_migratable_versions(version):
    text = json.dumps({
        "format": project_io.FORMAT,
        "version": version,
        "tables": "deliberately malformed",
        "scalars": None,
    })

    for reader in (project_io.project_provenance, project_io.parse_project):
        with pytest.raises(
            ValueError,
            match=(
                rf"unsupported Sector project schema {version}; only current "
                r"schema 27 and migrations from schemas 25 and 26"
            ),
        ):
            reader(text)


def test_noncurrent_non_v23_schema_names_current_and_migratable_versions():
    text = json.dumps({"format": project_io.FORMAT, "version": 22})

    with pytest.raises(
        ValueError,
        match=(
            r"unsupported Sector project schema 22; only current schema 27 "
            r"and migrations from schemas 25 and 26"
        ),
    ):
        project_io.parse_project(text)


def test_schema_27_serialization_contains_no_retired_bridge_inputs():
    tables, scalars = _current_project()
    tables.update({
        "bridge_brittle_base": {"retired": True},
        "bridge_box_walls_base": {"retired": True},
        "bridge_minimum_crack_base": {"retired": True},
    })
    scalars["bridge_standard"] = "retired"

    data = json.loads(project_io.dump_project(tables, scalars))

    assert data["version"] == 27
    assert set(data["tables"]) == set(project_io.PROJECT_TABLE_KEYS)
    assert not {
        "bridge_brittle_base",
        "bridge_box_walls_base",
        "bridge_minimum_crack_base",
    }.intersection(data["tables"])
    assert "bridge_standard" not in data["scalars"]
    assert not hasattr(project_io, "BRIDGE_TABLE_KEYS")


@pytest.mark.parametrize(
    "retired_table",
    (
        "bridge_brittle_base",
        "bridge_box_walls_base",
        "bridge_minimum_crack_base",
    ),
)
def test_rehashed_current_schema_rejects_each_retired_table_as_unknown(
    retired_table,
):
    tables, scalars = _current_project()
    data = json.loads(project_io.dump_project(tables, scalars))
    data["tables"][retired_table] = {"columns": [], "rows": []}
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(
        ValueError,
        match=rf"^unknown current-schema tables: {re.escape(retired_table)}$",
    ):
        project_io.parse_project(json.dumps(data))


def test_rehashed_current_schema_rejects_retired_bridge_scalar_as_unknown():
    tables, scalars = _current_project()
    data = json.loads(project_io.dump_project(tables, scalars))
    data["scalars"]["bridge_standard"] = "retired"
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(
        ValueError,
        match=r"^unknown current-schema inputs: bridge_standard$",
    ):
        project_io.parse_project(json.dumps(data))


@pytest.mark.parametrize("basis_key", tuple(design_standards.DesignBasisKey))
def test_fatigue_edition_round_trips_only_as_a_registered_basis_key(basis_key):
    tables, scalars = _current_project()
    scalars["fatigue_edition"] = basis_key.value

    text = project_io.dump_project(tables, scalars)
    _, loaded = project_io.parse_project(text)

    assert loaded["fatigue_edition"] == basis_key.value
    assert json.loads(text)["scalars"]["fatigue_edition"] == basis_key.value


@pytest.mark.parametrize(
    "invalid",
    (
        "DS/EN 1992-1-1:2005",
        "DS/EN 1992-1-1:2005 + DK NA:2024",
        "DS/EN 1992-1-1:2023",
        "ec2_1_1_2023_published ",
        "",
    ),
)
def test_fatigue_edition_rejects_labels_legacy_tokens_and_near_matches(
    invalid,
):
    tables, scalars = _current_project()
    scalars["fatigue_edition"] = invalid

    with pytest.raises(ValueError, match="registered basis keys"):
        project_io.dump_project(tables, scalars)


def test_rehashed_current_schema_rejects_an_unregistered_fatigue_edition():
    tables, scalars = _current_project()
    data = json.loads(project_io.dump_project(tables, scalars))
    data["scalars"]["fatigue_edition"] = "DS/EN 1992-1-1:2023"
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(ValueError, match="registered basis keys"):
        project_io.parse_project(json.dumps(data))


@pytest.mark.parametrize("basis_key", tuple(design_standards.DesignBasisKey))
def test_sls_code_round_trips_only_as_a_registered_basis_key(basis_key):
    tables, scalars = _current_project()
    scalars["sls_code"] = basis_key.value

    text = project_io.dump_project(tables, scalars)
    _, loaded = project_io.parse_project(text)

    assert loaded["sls_code"] == basis_key.value
    assert json.loads(text)["scalars"]["sls_code"] == basis_key.value


@pytest.mark.parametrize(
    "invalid",
    (
        "EN 1992-1-1:2005",
        "DS/EN 1992-1-1 + DK NA",
        "DS/EN 1992-1-1 + DK NA (fine crack system)",
        "EN 1992-1-1:2023",
        "ec2_1_1_first_gen_dk_na_2024 ",
        "unknown",
        "",
    ),
)
def test_sls_code_rejects_labels_aliases_whitespace_and_unknown_values(invalid):
    tables, scalars = _current_project()
    scalars["sls_code"] = invalid

    with pytest.raises(ValueError, match="registered basis keys"):
        project_io.dump_project(tables, scalars)


def test_ordinary_crack_request_requires_a_persisted_sls_basis_key():
    tables, scalars = _current_project()
    scalars.pop("sls_code")

    with pytest.raises(
        ValueError,
        match="sls_code is required when an Elastic case requests crack width",
    ):
        project_io.dump_project(tables, scalars)


def test_active_heightened_inputs_round_trip_with_direct_fct_eff():
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    scalars["sls_fctm"] = 9.9

    text = project_io.dump_project(tables, scalars)
    _, loaded = project_io.parse_project(text)
    persisted = json.loads(text)["scalars"]

    for key, value in _heightened_inputs().items():
        assert loaded[key] == value
        assert persisted[key] == value
    assert loaded["sls_heightened_effective_tensile_strength_mpa"] == 2.9
    assert loaded["sls_fctm"] == 9.9


def test_legacy_schema25_heightened_operands_migrate_to_dual_contract():
    payload = _legacy_heightened_schema25_payload()

    _, loaded, info = project_io.parse_project_with_info(json.dumps(payload))

    assert info["migrated"] is True
    assert len(info["migration_warnings"]) == 2
    assert "copied to the independent long-term and short-term inputs" in info["migration_warnings"][0]
    assert "copied to both the fine and coarse systems" in info["migration_warnings"][1]
    assert loaded["sls_heightened_reference_case"] == "One Elastic action"
    assert loaded[
        "sls_heightened_fine_effective_tension_area_mm2"
    ] == pytest.approx(120_000.0)
    assert loaded[
        "sls_heightened_coarse_effective_tension_area_mm2"
    ] == pytest.approx(120_000.0)
    assert not project_io.LEGACY_HEIGHTENED_OPERAND_KEYS.intersection(loaded)


def test_legacy_heightened_migration_refuses_ambiguous_reference_case():
    tables, _ = _current_project()
    elastic = tables[load_cases.ELASTIC_TABLE_KEY].to_dict("records")
    tables[load_cases.ELASTIC_TABLE_KEY] = load_cases.normalise_table(
        [
            *elastic,
            {
                "name": "Second Elastic action",
                "calculate_crack_width": True,
            },
        ],
        load_cases.ELASTIC_TABLE_KEY,
    )
    payload = _legacy_heightened_schema25_payload(tables)

    with pytest.raises(ValueError, match="do not identify one reference case"):
        project_io.parse_project_with_info(json.dumps(payload))


def test_legacy_heightened_migration_rejects_mixed_old_and_new_contract():
    payload = _legacy_heightened_schema25_payload()
    payload["scalars"][
        "sls_heightened_fine_effective_tension_area_mm2"
    ] = 120_000.0
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })

    with pytest.raises(ValueError, match="mixes retired and current"):
        project_io.parse_project_with_info(json.dumps(payload))


@pytest.mark.parametrize(
    "basis_key",
    (
        design_standards.DesignBasisKey.FIRST_GEN_BASE,
        design_standards.DesignBasisKey.PUBLISHED_2023,
    ),
)
def test_active_heightened_check_is_strictly_dk_na_2024_only(basis_key):
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    scalars["sls_code"] = basis_key.value

    with pytest.raises(
        ValueError,
        match="heightened crack control requires "
        "ec2_1_1_first_gen_dk_na_2024",
    ):
        project_io.dump_project(tables, scalars)


@pytest.mark.parametrize(
    "missing",
    project_io.HEIGHTENED_CRACK_SCALAR_KEYS[2:],
)
def test_active_heightened_check_requires_every_selector_and_operand(missing):
    tables, scalars = _current_project()
    heightened = _heightened_inputs()
    heightened.pop(missing)
    scalars.update(heightened)
    scalars.pop(missing, None)

    with pytest.raises(ValueError, match=rf"^{re.escape(missing)} is required"):
        project_io.dump_project(tables, scalars)


def test_active_heightened_reference_is_auto_selected_for_one_crack_case():
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    scalars.pop("sls_heightened_reference_case")

    text = project_io.dump_project(tables, scalars)
    _, loaded = project_io.parse_project(text)

    assert loaded["sls_heightened_reference_case"] == "One Elastic action"


@pytest.mark.parametrize(
    ("key", "invalid", "message"),
    (
        (
            "sls_heightened_reinforcement_surface",
            "Ribbed",
            "ribbed.*smooth",
        ),
        (
            "sls_heightened_reinforcement_surface",
            "smooth ",
            "ribbed.*smooth",
        ),
        (
            "sls_heightened_reinforcement_surface",
            False,
            "ribbed.*smooth",
        ),
    ),
)
def test_active_heightened_selectors_are_exact(key, invalid, message):
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    scalars[key] = invalid

    with pytest.raises(ValueError, match=message):
        project_io.dump_project(tables, scalars)


@pytest.mark.parametrize(
    "key",
    (
        "sls_heightened_effective_tensile_strength_mpa",
        "sls_heightened_permitted_crack_width_mm",
        "sls_heightened_fine_effective_tension_area_mm2",
        "sls_heightened_coarse_effective_tension_area_mm2",
    ),
)
@pytest.mark.parametrize(
    "invalid",
    (
        True,
        np.bool_(True),
        np.bool_(False),
        "1.0",
        0.0,
        -1.0,
        float("nan"),
        float("inf"),
    ),
)
def test_active_heightened_operands_must_be_positive_finite_reals(key, invalid):
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    scalars[key] = invalid

    with pytest.raises(
        ValueError,
        match=rf"^{re.escape(key)} must be a positive",
    ):
        project_io.dump_project(tables, scalars)


def test_active_heightened_fct_eff_never_falls_back_to_sls_fctm():
    tables, scalars = _current_project()
    heightened = _heightened_inputs()
    heightened.pop("sls_heightened_effective_tensile_strength_mpa")
    scalars.update(heightened)
    scalars["sls_fctm"] = 2.9

    with pytest.raises(
        ValueError,
        match="sls_heightened_effective_tensile_strength_mpa is required",
    ):
        project_io.dump_project(tables, scalars)


@pytest.mark.parametrize("invalid", (0, 1, "true", None))
def test_heightened_enable_flag_must_be_an_exact_boolean(invalid):
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    scalars["sls_heightened_on"] = invalid

    with pytest.raises(ValueError, match="sls_heightened_on must be a Boolean"):
        project_io.dump_project(tables, scalars)


def test_dormant_heightened_values_round_trip_under_a_non_dk_basis():
    tables, scalars = _current_project()
    dormant = _heightened_inputs()
    dormant["sls_heightened_on"] = False
    scalars.update(dormant)
    scalars["sls_code"] = (
        design_standards.DesignBasisKey.PUBLISHED_2023.value
    )

    text = project_io.dump_project(tables, scalars)
    _, loaded = project_io.parse_project(text)

    for key, value in dormant.items():
        assert loaded[key] == value
    assert loaded["sls_code"] == (
        design_standards.DesignBasisKey.PUBLISHED_2023.value
    )


def test_obsolete_compliance_and_approval_inputs_are_not_in_schema():
    forbidden = {
        "checker",
        "approver",
        "infrastructure_manager",
        "asset_class",
        "project_basis",
        "cover_calculator",
        "approval_reference",
        "sls_crack_limit",
        "check_stress",
        "multidirectional_interaction",
        "bridge_standard",
        "design_basis",
    }
    assert not forbidden.intersection(project_io.SCALAR_KEYS)


def test_calculation_record_is_correlated_but_results_are_not_persisted():
    tables, scalars = _current_project()
    digest = project_io.input_sha256(tables, scalars)
    engineering_digest = "e" * 64
    text = project_io.dump_project(
        tables,
        scalars,
        calculation={
            "performed_at_utc": "2026-07-29T12:00:00+00:00",
            "sector_version": "0.91",
            "source_revision": "abc123",
            "input_sha256": digest,
            "engineering_input_sha256": engineering_digest,
            "result_sha256": "f" * 64,
        },
    )
    provenance = project_io.project_provenance(text)

    assert provenance["results_included"] is False
    assert provenance["calculation"]["matches_saved_inputs"] is True
    assert provenance["calculation"]["engineering_input_sha256"] == (
        engineering_digest
    )
    assert provenance["calculation"]["result_sha256"] == "f" * 64

    with pytest.raises(ValueError, match="result_sha256"):
        project_io.dump_project(
            tables,
            scalars,
            calculation={"input_sha256": digest, "result_sha256": "not-a-hash"},
        )
    with pytest.raises(ValueError, match="engineering_input_sha256"):
        project_io.dump_project(
            tables,
            scalars,
            calculation={"engineering_input_sha256": "not-a-hash"},
        )


def test_provenance_and_calculation_input_checks_are_independent():
    tables, scalars = _current_project()
    digest = project_io.input_sha256(tables, scalars)
    text = project_io.dump_project(
        tables,
        scalars,
        calculation={
            "performed_at_utc": "2026-07-29T12:00:00+00:00",
            "sector_version": "0.96.1",
            "source_revision": "a" * 40,
            "input_sha256": digest,
            "engineering_input_sha256": "e" * 64,
            "result_sha256": "f" * 64,
        },
        app_version="0.96.1",
        revision="a" * 40,
    )
    original = json.loads(text)

    changed_provenance = copy.deepcopy(original)
    changed_provenance["provenance"]["input_sha256"] = "0" * 64
    provenance_changed = project_io.project_provenance(
        json.dumps(changed_provenance)
    )
    assert provenance_changed["input_hash_valid"] is False
    assert provenance_changed["calculation"]["matches_saved_inputs"] is True
    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io.parse_project(json.dumps(changed_provenance))
    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file is damaged or was changed outside Sector"
    )

    changed_calculation = copy.deepcopy(original)
    changed_calculation["calculation"]["input_sha256"] = "1" * 64
    calculation_changed = project_io.project_provenance(
        json.dumps(changed_calculation)
    )
    assert calculation_changed["input_hash_valid"] is True
    assert calculation_changed["calculation"]["matches_saved_inputs"] is False
    project_io.parse_project(json.dumps(changed_calculation))


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("sector_version", True),
        ("sector_version", "RAW payload schema contract"),
        ("sector_version", "0.96.1-payload-schema-contract"),
        ("source_revision", []),
        ("source_revision", "source control history"),
        ("saved_at_utc", 1),
        ("saved_at_utc", "2026-08-25T12:00:00"),
        ("input_sha256", "g" * 64),
        ("results_included", "false"),
        ("results_included", True),
        ("private_payload", "RAW internal value"),
    ),
)
def test_project_provenance_rejects_unpublishable_fields(field, invalid):
    tables, scalars = _current_project()
    data = json.loads(project_io.dump_project(tables, scalars))
    data["provenance"][field] = invalid

    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io.project_provenance(json.dumps(data))

    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file is incomplete or damaged"
    )


@pytest.mark.parametrize("invalid", (None, True, "RAW payload", []))
def test_project_calculation_record_requires_an_object(invalid):
    tables, scalars = _current_project()
    data = json.loads(project_io.dump_project(tables, scalars))
    data["calculation"] = invalid

    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io.project_provenance(json.dumps(data))

    assert project_io.engineer_error_message(exc_info.value) == (
        "the recorded calculation is damaged; recalculate before saving the project"
    )


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("performed_at_utc", True),
        ("performed_at_utc", "RAW traceback payload"),
        ("performed_at_utc", "2026-08-25T12:00:00"),
        ("sector_version", {}),
        ("sector_version", "RAW source-control process"),
        ("sector_version", "0.96.1-payload-schema-contract"),
        ("source_revision", 1),
        ("source_revision", "source control history"),
        ("input_sha256", "not-a-check"),
        ("engineering_input_sha256", False),
        ("result_sha256", "f" * 63),
        ("matches_saved_inputs", "true"),
        ("private_payload", "RAW internal value"),
    ),
)
def test_project_calculation_record_rejects_unpublishable_fields(field, invalid):
    tables, scalars = _current_project()
    digest = project_io.input_sha256(tables, scalars)
    data = json.loads(project_io.dump_project(
        tables,
        scalars,
        calculation={
            "performed_at_utc": "2026-08-25T12:00:00+00:00",
            "sector_version": "0.96.1",
            "source_revision": "a" * 40,
            "input_sha256": digest,
            "engineering_input_sha256": "e" * 64,
            "result_sha256": "f" * 64,
        },
    ))
    data["calculation"][field] = invalid

    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io.project_provenance(json.dumps(data))

    assert project_io.engineer_error_message(exc_info.value) == (
        "the recorded calculation is damaged; recalculate before saving the project"
    )


def test_recorded_labels_never_echo_unvalidated_values():
    hostile = "RAW GitHub SHA-256 payload schema contract internal_private_ID"

    assert project_io.recorded_sector_version_label(hostile) is None
    assert project_io.recorded_sector_version_label(
        "0.96.1-payload-schema-contract"
    ) is None
    assert project_io.recorded_sector_version_label("0.96.1") == "0.96.1"
    assert project_io.recorded_utc_label(hostile) is None
    assert project_io.recorded_utc_label("2026-08-25T14:30:00+02:00") == (
        "2026-08-25 12:30 UTC"
    )


def test_nonpositive_factor_is_rejected_but_positive_custom_values_are_not():
    tables, scalars = _current_project()
    for value in (0.5, 2.0):
        custom = dict(scalars, conc_gamma_c=value)
        _, loaded = project_io.parse_project(
            project_io.dump_project(tables, custom)
        )
        assert loaded["conc_gamma_c"] == pytest.approx(value)
    with pytest.raises(ValueError, match="positive finite"):
        project_io.dump_project(tables, dict(scalars, conc_gamma_c=0.0))


@pytest.mark.parametrize("value", [0.5, 2.0])
def test_current_schema_retains_direct_torsion_tensile_factor(value):
    tables, scalars = _current_project()
    scalars.update(torsion_on=True, torsion_gamma_ct=value)

    text = project_io.dump_project(tables, scalars)
    _, loaded = project_io.parse_project(text)

    assert loaded["torsion_gamma_ct"] == pytest.approx(value)


@pytest.mark.parametrize(
    "value", [True, False, 0.0, -1.0, float("inf"), float("-inf"), float("nan")]
)
def test_current_schema_rejects_invalid_torsion_tensile_factor(value):
    tables, scalars = _current_project()
    scalars.update(torsion_on=True, torsion_gamma_ct=value)

    with pytest.raises(ValueError, match="positive finite real"):
        project_io.dump_project(tables, scalars)


def test_current_schema_requires_torsion_tensile_factor_when_active():
    tables, scalars = _current_project()
    scalars["torsion_on"] = True
    scalars.pop("torsion_gamma_ct")

    with pytest.raises(ValueError, match="torsion_gamma_ct is required"):
        project_io.dump_project(tables, scalars)
