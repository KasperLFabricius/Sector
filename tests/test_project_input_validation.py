"""Project scalar, material-domain, nested-table and real upload validation."""

from __future__ import annotations

import json
import math
import os
import pathlib
import sys

import pytest
from streamlit.testing.v1 import AppTest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

APP = str(ROOT / "app" / "sector_app.py")

import fatigue_inputs  # noqa: E402
import load_cases  # noqa: E402
import material_catalog  # noqa: E402
import project_io  # noqa: E402
import reinforcement_table as rebar_table  # noqa: E402
import viz  # noqa: E402
from sector import capacity  # noqa: E402


_RESULT_KEYS = (
    "results",
    "result_sig",
    "result_plastic_sig",
    "result_elastic_sig",
    "result_fatigue_sig",
    "result_capacity_contract_sig",
    "result_plastic_case_context_sig",
    "result_elastic_case_context_sig",
    "result_plastic_bending_context_sig",
    "result_input_snapshot",
    "calculation_record",
    "_case_error",
    "pl_state",
    "report_buffer",
    "report_bytes",
    "report_signature",
    "report_filename",
    "report_generated_on",
    "report_generation_record",
    "_report_msg",
)


@pytest.fixture(scope="module", autouse=True)
def _isolated_autosave(tmp_path_factory):
    key = "SECTOR_AUTOSAVE_DIR"
    previous = os.environ.get(key)
    os.environ[key] = str(tmp_path_factory.mktemp("state-m01-autosave"))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def test_scalar_type_manifest_covers_every_current_schema_scalar_once() -> None:
    groups = (
        project_io._BOOLEAN_SCALAR_KEYS,
        project_io._INTEGER_SCALAR_KEYS,
        project_io._TEXT_SCALAR_KEYS,
        project_io._NESTED_SCALAR_KEYS,
        project_io._REAL_SCALAR_KEYS,
    )
    assert set().union(*groups) == set(project_io.SCALAR_KEYS)
    assert sum(map(len, groups)) == len(project_io.SCALAR_KEYS)


@pytest.mark.parametrize("key", project_io.PRESENTATION_SCALAR_KEYS)
def test_every_presentation_scalar_rejects_nontext_values(
    key: str,
) -> None:
    for invalid in (True, 1, 1.0, [], {}):
        with pytest.raises(ValueError):
            project_io.persistence_sha256({}, {key: invalid})


@pytest.mark.parametrize("key", sorted(project_io._BOOLEAN_SCALAR_KEYS))
def test_every_boolean_scalar_rejects_truthy_and_string_coercion(
    key: str,
) -> None:
    for invalid in (0, 1, "true", [], {}):
        with pytest.raises(ValueError):
            project_io._canonical_scalars({key: invalid}, {})


@pytest.mark.parametrize("key", sorted(project_io._TEXT_SCALAR_KEYS))
def test_every_text_scalar_rejects_nontext_values(key: str) -> None:
    for invalid in (True, 1, 1.0, [], {}):
        with pytest.raises(ValueError):
            project_io._canonical_scalars({key: invalid}, {})


@pytest.mark.parametrize(
    "key",
    (
        "shear_method",
        "torsion_method",
        "combined_method",
        "sls_code",
        "fatigue_edition",
    ),
)
def test_method_and_design_basis_types_use_the_authored_input_boundary(
    key: str,
) -> None:
    for invalid in (True, 1, 1.0, [], {}):
        with pytest.raises(project_io.ProjectInputError) as exc_info:
            project_io._canonical_scalars({key: invalid}, {})
        assert project_io.engineer_error_message(exc_info.value) == (
            "the project file contains an invalid input value"
        )


@pytest.mark.parametrize("key", sorted(project_io._EXACT_TEXT_OPTIONS))
def test_every_exact_text_selection_rejects_unknown_text(key: str) -> None:
    with pytest.raises(project_io.ProjectInputError):
        project_io._canonical_scalars({key: "unsupported selection"}, {})


@pytest.mark.parametrize(
    ("key", "value"),
    tuple(
        (key, sorted(options)[0])
        for key, options in sorted(project_io._EXACT_TEXT_OPTIONS.items())
    ),
)
def test_every_exact_text_selection_accepts_a_current_option(
    key: str,
    value: str,
) -> None:
    loaded = project_io._canonical_scalars({key: value}, {})
    assert loaded[key] == value


@pytest.mark.parametrize("key", sorted(project_io._INTEGER_SCALAR_KEYS))
def test_every_count_scalar_rejects_nonintegral_or_nonfinite_values(
    key: str,
) -> None:
    for invalid in (
        True,
        "2",
        2.5,
        float("nan"),
        float("inf"),
        [],
        {},
    ):
        with pytest.raises(project_io.ProjectInputError):
            project_io._canonical_scalars({key: invalid}, {})


@pytest.mark.parametrize("key", sorted(project_io._REAL_SCALAR_KEYS))
def test_every_real_scalar_rejects_boolean_string_nonfinite_and_container_values(
    key: str,
) -> None:
    for invalid in (
        True,
        "1.0",
        float("nan"),
        float("inf"),
        -float("inf"),
        [],
        {},
    ):
        with pytest.raises(project_io.ProjectInputError):
            project_io._canonical_scalars({key: invalid}, {})


@pytest.mark.parametrize("key", sorted(project_io._NESTED_SCALAR_KEYS))
def test_every_nested_scalar_rejects_the_wrong_container(key: str) -> None:
    for invalid in (True, "items", [], 1.0):
        with pytest.raises(project_io.ProjectInputError):
            project_io._canonical_scalars({key: invalid}, {})


def test_explicit_numeric_coercions_are_finite_and_type_stable() -> None:
    loaded = project_io._canonical_scalars(
        {
            "conc_fck": 41,
            "qsv_ring_n": 8.0,
            "autosave_min": 5.0,
            "fatigue_on": False,
            "rep_proj_no": "STATE-M01",
        },
        {},
    )

    assert type(loaded["conc_fck"]) is float
    assert loaded["conc_fck"] == pytest.approx(41.0)
    assert type(loaded["qsv_ring_n"]) is int
    assert loaded["qsv_ring_n"] == 8
    assert type(loaded["autosave_min"]) is int
    assert loaded["autosave_min"] == 5
    assert type(loaded["fatigue_on"]) is bool
    assert type(loaded["rep_proj_no"]) is str


def test_all_current_nested_scalar_defaults_pass_the_type_boundary() -> None:
    loaded = project_io._canonical_scalars(
        {
            material_catalog.MILD_CATALOG_KEY: (
                material_catalog.default_catalog("mild")
            ),
            material_catalog.PRESTRESS_CATALOG_KEY: (
                material_catalog.default_catalog("prestress")
            ),
            fatigue_inputs.DETAIL_CATALOG_KEY: fatigue_inputs.default_catalog(),
            fatigue_inputs.BASIS_KEY: fatigue_inputs.default_basis(),
        },
        {},
    )

    assert loaded[material_catalog.MILD_CATALOG_KEY]["version"] == (
        material_catalog.VERSION
    )
    assert loaded[material_catalog.PRESTRESS_CATALOG_KEY]["version"] == (
        material_catalog.VERSION
    )
    assert loaded[fatigue_inputs.DETAIL_CATALOG_KEY]["version"] == (
        fatigue_inputs.VERSION
    )
    assert loaded[fatigue_inputs.BASIS_KEY] == fatigue_inputs.default_basis()


def test_custom_material_catalogues_and_live_aliases_round_trip() -> None:
    custom = material_catalog.CUSTOM_PRESET
    mild = material_catalog.default_catalog("mild")
    prestress = material_catalog.default_catalog("prestress")
    mild["items"][0]["preset"] = custom
    prestress["items"][0]["preset"] = custom
    source_scalars = {
        material_catalog.MILD_CATALOG_KEY: mild,
        material_catalog.PRESTRESS_CATALOG_KEY: prestress,
        "mild_preset": custom,
        "pre_preset": custom,
    }

    text = project_io.dump_project({}, source_scalars)
    _tables, loaded = project_io.parse_project(text)

    assert loaded["mild_preset"] == custom
    assert loaded["pre_preset"] == custom
    assert loaded[material_catalog.MILD_CATALOG_KEY]["items"][0]["preset"] == custom
    assert (
        loaded[material_catalog.PRESTRESS_CATALOG_KEY]["items"][0]["preset"]
        == custom
    )


@pytest.mark.parametrize(
    ("key", "value"),
    (
        (
            material_catalog.MILD_CATALOG_KEY,
            {"items": material_catalog.default_entry("mild")},
        ),
        (
            material_catalog.MILD_CATALOG_KEY,
            {"items": [{"id": "M1", "fytk": "550"}]},
        ),
        (
            material_catalog.MILD_CATALOG_KEY,
            {"items": [{"id": "M1", "fytk": float("nan")}]},
        ),
        (
            material_catalog.MILD_CATALOG_KEY,
            {"items": [{"id": "M1", "active_in_compression": 1}]},
        ),
        (
            material_catalog.PRESTRESS_CATALOG_KEY,
            {"items": [{"id": "P1", "curve": 3.5}]},
        ),
        (
            fatigue_inputs.DETAIL_CATALOG_KEY,
            {"items": [{"id": "F1", "n_star": "1000000"}]},
        ),
        (
            fatigue_inputs.DETAIL_CATALOG_KEY,
            {"items": [{"id": "F1", "bend_reduction": 1}]},
        ),
        (fatigue_inputs.BASIS_KEY, {"method": 1, "notes": ""}),
        (fatigue_inputs.BASIS_KEY, {"method": "Grouped", "private": True}),
    ),
)
def test_nested_catalogue_and_basis_fields_reject_hostile_types(
    key: str,
    value,
) -> None:
    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io._canonical_scalars({key: value}, {})

    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file contains an invalid input value"
    )


@pytest.mark.parametrize(
    ("kind", "field", "value"),
    (
        ("mild", "fytk", float("nan")),
        ("mild", "futk", -1.0),
        ("mild", "futk", 500.0),
        ("mild", "k", 1.1),
        ("mild", "eut", 1.0),
        ("prestress", "IS", float("inf")),
        ("prestress", "eut", -1.0),
        ("prestress", "futk", 1600.0),
        ("prestress", "ey0t", 40.0),
    ),
)
def test_project_material_catalogues_reject_invalid_active_domains(
    kind: str,
    field: str,
    value,
) -> None:
    key = material_catalog.catalog_key(kind)
    catalog = material_catalog.default_catalog(kind)
    catalog["items"][0][field] = value

    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io._canonical_scalars({key: catalog}, {})

    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file contains an invalid input value"
    )


def test_project_catalogue_rejects_ultimate_below_active_compression_yield() -> None:
    catalog = material_catalog.default_catalog("mild")
    catalog["items"][0].update(fytk=500.0, fyck=700.0, futk=600.0)

    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io._canonical_scalars(
            {material_catalog.MILD_CATALOG_KEY: catalog},
            {},
        )

    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file contains an invalid input value"
    )


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
def test_project_catalogue_rejects_descending_factored_ultimate_branch(
    kind: str,
    updates: dict,
) -> None:
    key = material_catalog.catalog_key(kind)
    catalog = material_catalog.default_catalog(kind)
    catalog["items"][0].update(updates)

    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io._canonical_scalars({key: catalog}, {})

    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file contains an invalid input value"
    )


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
def test_project_catalogue_accepts_mathematically_equal_factored_ultimate(
    kind: str,
    curve: int,
    updates: dict,
) -> None:
    key = material_catalog.catalog_key(kind)
    catalog = material_catalog.default_catalog(kind)
    catalog["items"][0].update(curve=curve, **updates)

    loaded = project_io._canonical_scalars({key: catalog}, {})
    material = material_catalog.build_material(
        loaded[key]["items"][0], kind
    )

    assert material.curve == curve


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
def test_project_catalogue_rejects_nonfinite_derived_design_ordinate(
    kind: str,
    curve: int,
    updates: dict,
) -> None:
    key = material_catalog.catalog_key(kind)
    catalog = material_catalog.default_catalog(kind)
    catalog["items"][0].update(curve=curve, **updates)

    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io._canonical_scalars({key: catalog}, {})

    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file contains an invalid input value"
    )


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
def test_project_catalogue_rejects_factored_yield_nan_escape(
    kind: str,
    curve: int,
    updates: dict,
) -> None:
    key = material_catalog.catalog_key(kind)
    catalog = material_catalog.default_catalog(kind)
    catalog["items"][0].update(curve=curve, **updates)

    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io._canonical_scalars({key: catalog}, {})

    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file contains an invalid input value"
    )


def test_project_catalogue_accepts_tension_only_compression_relations() -> None:
    catalog = material_catalog.default_catalog("mild")
    catalog["items"][0].update(
        active_in_compression=False,
        fytk=500.0,
        fyck=700.0,
        futk=600.0,
        ey0c=-10.0,
    )

    loaded = project_io._canonical_scalars(
        {material_catalog.MILD_CATALOG_KEY: catalog},
        {},
    )
    item = loaded[material_catalog.MILD_CATALOG_KEY]["items"][0]
    steel = material_catalog.build_material(item, "mild")

    assert steel.active_in_compression is False
    assert steel.ey0c == pytest.approx(-0.01)
    assert steel.stress(-0.02) == 0.0
    assert not any(
        stress < 0.0 or strain < 0.0
        for strain, stress, *_ in steel.diagram_markers(design=False)
    )
    figure = viz.steel_curve_figure(steel)
    annotations = " ".join(
        str(item.text) for item in figure.layout.annotations
    )
    assert "f<sub>yck</sub>" not in annotations
    assert chr(0x03B5) + "<sub>0c</sub>" not in annotations
    marker = next(trace for trace in figure.data if trace.mode == "markers")
    assert all(value >= 0.0 for value in marker.x)
    assert all(value >= 0.0 for value in marker.y)


def test_sparse_project_aliases_accept_tension_only_compression_relations() -> None:
    loaded = project_io._canonical_scalars(
        {
            "mild_active_comp": False,
            "mild_fytk": 500.0,
            "mild_fyck": 700.0,
            "mild_futk": 600.0,
            "mild_ey0c": -1.0,
        },
        {},
    )

    assert loaded["mild_active_comp"] is False
    assert loaded["mild_fyck"] == pytest.approx(700.0)
    assert loaded["mild_ey0c"] == pytest.approx(-1.0)


@pytest.mark.parametrize(
    ("kind", "curve", "missing"),
    (
        ("mild", 3, "futk"),
        ("mild", 2, "gamma_y"),
        ("prestress", 7, "ey0t"),
        ("prestress", 1, "IS"),
    ),
)
def test_project_material_catalogues_reject_curve_specific_omissions(
    kind: str,
    curve: int,
    missing: str,
) -> None:
    key = material_catalog.catalog_key(kind)
    catalog = material_catalog.default_catalog(kind)
    catalog["items"][0]["curve"] = curve
    catalog["items"][0].pop(missing)

    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io._canonical_scalars({key: catalog}, {})

    assert missing in str(exc_info.value)
    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file contains an invalid input value"
    )


@pytest.mark.parametrize(
    "scalars",
    (
        {"mild_futk": 500.0},
        {"mild_eut": 1.0},
        {"pre_futk": 1600.0},
        {"pre_ey0t": 40.0},
    ),
)
def test_sparse_project_material_aliases_reject_invalid_active_domains(
    scalars: dict,
) -> None:
    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io._canonical_scalars(scalars, {})

    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file contains an invalid input value"
    )


def test_project_alias_validation_preserves_curve_applicability() -> None:
    mild = material_catalog.default_catalog("mild")
    mild["items"][0]["curve"] = 2
    prestress = material_catalog.default_catalog("prestress")
    prestress["items"][0]["curve"] = 1

    loaded = project_io._canonical_scalars(
        {
            material_catalog.MILD_CATALOG_KEY: mild,
            material_catalog.PRESTRESS_CATALOG_KEY: prestress,
            "mild_futk": -1.0,
            "mild_k": 1.1,
            "pre_fytk": -1.0,
            "pre_futk": -1.0,
            "pre_ey0t": -1.0,
        },
        {},
    )

    assert loaded["mild_futk"] == pytest.approx(-1.0)
    assert loaded["pre_fytk"] == pytest.approx(-1.0)


def test_present_catalogues_ignore_orphaned_m1_p1_aliases() -> None:
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

    loaded = project_io._canonical_scalars(
        {
            material_catalog.MILD_CATALOG_KEY: mild,
            material_catalog.PRESTRESS_CATALOG_KEY: prestress,
            "mild_fytk": 500.0,
            "mild_fyck": 700.0,
            "mild_futk": 600.0,
            "pre_fytk": 1600.0,
            "pre_futk": 1500.0,
        },
        {},
    )

    assert [
        item["id"]
        for item in loaded[material_catalog.MILD_CATALOG_KEY]["items"]
    ] == ["M2"]
    assert [
        item["id"]
        for item in loaded[material_catalog.PRESTRESS_CATALOG_KEY]["items"]
    ] == ["P2"]
    assert loaded["mild_fyck"] == pytest.approx(700.0)
    assert loaded["pre_futk"] == pytest.approx(1500.0)


@pytest.mark.parametrize(
    ("kind", "curve"),
    (("mild", 1), ("mild", 3), ("prestress", 6), ("prestress", 7)),
)
def test_project_catalogue_strength_order_is_scale_independent(kind, curve):
    catalog = material_catalog.default_catalog(kind)
    entry = catalog["items"][0]
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

    loaded = project_io._canonical_scalars(
        {material_catalog.catalog_key(kind): catalog},
        {},
    )
    assert loaded[material_catalog.catalog_key(kind)]["items"][0][
        "futk"
    ] == pytest.approx(2.0e-308, rel=1.0e-12, abs=0.0)

    entry["futk"] = 1.0e-308
    with pytest.raises(project_io.ProjectInputError):
        project_io._canonical_scalars(
            {material_catalog.catalog_key(kind): catalog},
            {},
        )


@pytest.mark.parametrize(
    ("kind", "curve"),
    (("mild", 1), ("mild", 3), ("prestress", 6), ("prestress", 7)),
)
def test_project_catalogue_extreme_hardening_law_has_finite_stress(kind, curve):
    catalog = material_catalog.default_catalog(kind)
    entry = catalog["items"][0]
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

    loaded = project_io._canonical_scalars(
        {material_catalog.catalog_key(kind): catalog},
        {},
    )
    material = material_catalog.build_material(
        loaded[material_catalog.catalog_key(kind)]["items"][0],
        kind,
    )

    assert material.stress(material.eut) == 1.0e308
    assert all(
        math.isfinite(material.stress(strain))
        for strain in (0.0035, material.eut / 2.0, material.eut)
    )


@pytest.mark.parametrize("curve", (1, 2, 3, 4, 5))
def test_project_catalogue_builtin_prestress_rejects_nonfinite_design_stress(
    curve,
):
    catalog = material_catalog.default_catalog("prestress")
    catalog["items"][0].update(curve=curve, gamma_y=1.0e-308)

    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io._canonical_scalars(
            {material_catalog.PRESTRESS_CATALOG_KEY: catalog},
            {},
        )

    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file contains an invalid input value"
    )


def _table_object_with_row(key: str) -> dict:
    columns = list(project_io._expected_table_columns(key))
    numeric, nullable, text, boolean = project_io._table_cell_kinds(key)
    row = []
    for column in columns:
        if column in numeric:
            row.append(0.0)
        elif column in boolean:
            row.append(False)
        elif column == rebar_table.SIZE_MODE:
            row.append(rebar_table.AREA_MODE)
        elif column in load_cases.PLASTIC_FACE_COLUMNS:
            row.append(load_cases.FACE_AUTO)
        elif column in text:
            row.append("")
        else:  # pragma: no cover - the production manifest owns every column
            raise AssertionError((key, column, nullable))
    if key in project_io.REINFORCEMENT_TABLE_KEYS:
        row[columns.index(rebar_table.AREA)] = 100.0
    return {"columns": columns, "rows": [row]}


@pytest.mark.parametrize("key", project_io.PROJECT_TABLE_KEYS)
def test_every_current_nested_table_has_one_exact_column_contract(key: str) -> None:
    frame = project_io._obj_to_table(_table_object_with_row(key), key)
    assert list(frame.columns) == list(project_io._expected_table_columns(key))


@pytest.mark.parametrize(
    ("key", "column", "invalid"),
    (
        ("corners_base", "x (mm)", True),
        ("corners_base", "y (mm)", "0.0"),
        ("corners_base", "x (mm)", float("nan")),
        ("bars_base", rebar_table.X, "0"),
        ("bars_base", rebar_table.ELEMENT_ID, 1),
        ("bars_base", rebar_table.SIZE_MODE, "automatic"),
        (load_cases.PLASTIC_TABLE_KEY, "n_ed_kn", "12"),
        (load_cases.PLASTIC_TABLE_KEY, "name", True),
        (
            load_cases.PLASTIC_TABLE_KEY,
            "check_minimum_reinforcement",
            1,
        ),
        (load_cases.PLASTIC_TABLE_KEY, "vx_face", "left"),
        (fatigue_inputs.SPECTRUM_TABLE_KEY, "cycles", True),
        (fatigue_inputs.SPECTRUM_TABLE_KEY, "name", {}),
    ),
)
def test_nested_table_cells_reject_hostile_types_before_dataframe_coercion(
    key: str,
    column: str,
    invalid,
) -> None:
    value = _table_object_with_row(key)
    position = value["columns"].index(column)
    value["rows"][0][position] = invalid

    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io._obj_to_table(value, key)

    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file contains an invalid input value"
    )


@pytest.mark.parametrize("key", ("bars_base", "tendons_base"))
@pytest.mark.parametrize(
    ("column", "invalid"),
    (
        (rebar_table.X, float("nan")),
        (rebar_table.Y, float("inf")),
        (rebar_table.AREA, 0.0),
        (rebar_table.AREA, -100.0),
        (rebar_table.AREA, float("nan")),
    ),
)
def test_project_reinforcement_rows_require_finite_coordinates_and_positive_area(
    key: str,
    column: str,
    invalid,
) -> None:
    value = _table_object_with_row(key)
    value["rows"][0][value["columns"].index(column)] = invalid

    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io._obj_to_table(value, key)

    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file contains an invalid input value"
    )


def test_project_dump_rejects_a_negative_reinforcement_area() -> None:
    bars = rebar_table.normalise_table(
        [{rebar_table.X: 0.0, rebar_table.Y: 0.0, rebar_table.AREA: -100.0}],
        "bar",
    )

    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io.dump_project({"bars_base": bars}, {})

    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file contains an invalid input value"
    )


def test_nonstandard_json_nan_action_uses_authored_project_guidance() -> None:
    data = json.loads(project_io.dump_project(load_cases.default_tables(), {}))
    table = data["tables"][load_cases.PLASTIC_TABLE_KEY]
    action = table["columns"].index("n_ed_kn")
    table["rows"][0][action] = float("nan")

    with pytest.raises(project_io.ProjectInputError) as exc_info:
        project_io.parse_project(json.dumps(data, allow_nan=True))

    assert project_io.engineer_error_message(exc_info.value) == (
        "the project file contains an invalid input value"
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "table-list",
        "unknown-field",
        "columns-container",
        "columns-mismatch",
        "rows-container",
        "row-container",
        "row-width",
    ),
)
def test_nested_table_structure_rejects_wrong_containers(mutation: str) -> None:
    key = load_cases.PLASTIC_TABLE_KEY
    value = _table_object_with_row(key)
    if mutation == "table-list":
        value = []
    elif mutation == "unknown-field":
        value["private"] = True
    elif mutation == "columns-container":
        value["columns"] = {"name": 1}
    elif mutation == "columns-mismatch":
        value["columns"] = value["columns"][:-1]
    elif mutation == "rows-container":
        value["rows"] = {"0": value["rows"][0]}
    elif mutation == "row-container":
        value["rows"][0] = {"name": "case"}
    elif mutation == "row-width":
        value["rows"][0] = value["rows"][0][:-1]

    with pytest.raises(project_io.ProjectInputError):
        project_io._obj_to_table(value, key)


def _fresh() -> AppTest:
    return AppTest.from_file(APP, default_timeout=90).run()


def _goto_page(at: AppTest, page: str) -> AppTest:
    current = (
        at.session_state["_main_page"]
        if "_main_page" in at.session_state
        else None
    )
    if current != page:
        at.segmented_control(key="_main_page").set_value(page).run()
    return at


def _goto_project(at: AppTest) -> AppTest:
    _goto_page(at, "Inputs")
    if at.session_state["_input_tab"] != "Project":
        at.session_state["_input_tab"] = "Project"
        at.run()
    return at


def _goto_concrete(at: AppTest) -> AppTest:
    _goto_page(at, "Inputs")
    material_stage = f"3 {chr(0x00B7)} Material parameters"
    at.session_state["_input_tab"] = material_stage
    at.session_state["_material_tab"] = "Concrete"
    at.session_state["_material_tab_preference"] = "Concrete"
    at.run()
    return at


def _upload(at: AppTest, content: bytes) -> AppTest:
    assert len(at.file_uploader) == 1
    at.file_uploader[0].set_value(
        ("sector_section.json", content, "application/json")
    ).run()
    return at


def _replacement_bytes(at: AppTest, fck: float) -> bytes:
    tables = {
        key: at.session_state[key]
        for key in project_io.PROJECT_TABLE_KEYS
        if key in at.session_state
    }
    scalars = {
        key: at.session_state[key]
        for key in project_io.SCALAR_KEYS
        if key in at.session_state
    }
    scalars["conc_fck"] = fck
    return project_io.dump_project(tables, scalars).encode("utf-8")


def _mutated_project(
    source: bytes,
    mutation,
    *,
    rehash: bool = True,
) -> bytes:
    data = json.loads(source.decode("utf-8"))
    mutation(data)
    if rehash:
        data["provenance"]["input_sha256"] = project_io._input_digest({
            "tables": data["tables"],
            "scalars": data["scalars"],
        })
    return json.dumps(data, allow_nan=True).encode("utf-8")


def _calculate(at: AppTest) -> AppTest:
    _goto_page(at, "Analysis")
    if not any(button.key == "calculate" for button in at.button):
        _goto_page(at, "Inputs")
        _goto_page(at, "Analysis")
    at.button(key="calculate").click().run()
    assert "results" in at.session_state, [item.value for item in at.error]
    return at


def _project_signature(at: AppTest) -> str:
    tables = {
        key: at.session_state[key]
        for key in project_io.PROJECT_TABLE_KEYS
        if key in at.session_state
    }
    scalars = {
        key: at.session_state[key]
        for key in project_io.SCALAR_KEYS
        if key in at.session_state
    }
    return project_io.persistence_sha256(tables, scalars)


def _completed_result_evidence(at: AppTest) -> tuple[tuple[str, ...], str]:
    _calculate(at)
    _goto_project(at)
    supplemental = {
        "report_buffer": b"STATE-M01 last-valid report",
        "report_bytes": b"STATE-M01 last-valid report",
        "report_signature": ("STATE-M01", "report"),
        "report_filename": "state-m01.pdf",
        "report_generation_record": {"source": "last-valid"},
    }
    for key, value in supplemental.items():
        at.session_state[key] = value
    present = tuple(key for key in _RESULT_KEYS if key in at.session_state)
    return present, project_io.result_sha256(
        {key: at.session_state[key] for key in present}
    )


def _assert_result_evidence(
    at: AppTest,
    expected: tuple[tuple[str, ...], str],
) -> None:
    present, digest = expected
    assert tuple(key for key in _RESULT_KEYS if key in at.session_state) == present
    assert project_io.result_sha256(
        {key: at.session_state[key] for key in present}
    ) == digest


def test_real_inputs_upload_rejects_hostile_types_transactionally() -> None:
    at = _fresh()
    valid_a = _replacement_bytes(at, 41.0)
    _goto_project(at)
    _upload(at, valid_a)
    assert at.session_state["conc_fck"] == pytest.approx(41.0)

    before_results = _completed_result_evidence(at)
    before_project = _project_signature(at)
    before_identity = at.session_state["_project_upload_content_identity"]

    def scalar(key: str, value):
        return lambda data: data["scalars"].__setitem__(key, value)

    def wrong_rows(data: dict) -> None:
        data["tables"][load_cases.PLASTIC_TABLE_KEY]["rows"] = [
            {"name": "wrong container"}
        ]

    def negative_bar_area(data: dict) -> None:
        table = data["tables"]["bars_base"]
        assert table["rows"]
        mode = table["columns"].index(rebar_table.SIZE_MODE)
        area = table["columns"].index(rebar_table.AREA)
        table["rows"][0][mode] = rebar_table.AREA_MODE
        table["rows"][0][area] = -100.0

    def nan_plastic_action(data: dict) -> None:
        table = data["tables"][load_cases.PLASTIC_TABLE_KEY]
        assert table["rows"]
        action = table["columns"].index("n_ed_kn")
        table["rows"][0][action] = float("nan")

    def unrepresentable_sweep_span(data: dict) -> None:
        data["scalars"].update(
            v_min=-1e308,
            v_max=1e308,
            v_inc=1.0,
        )

    too_fine = _mutated_project(valid_a, scalar("v_inc", 1e-20))
    _upload(at, too_fine)
    assert not at.exception
    assert _project_signature(at) == before_project
    assert at.session_state["_project_upload_content_identity"] == before_identity
    assert at.session_state["conc_fck"] == pytest.approx(41.0)
    assert at.session_state["v_inc"] == pytest.approx(15.0)
    _assert_result_evidence(at, before_results)
    sweep_visible = "\n".join(str(item.value) for item in at.error)
    assert "New file was not applied" in sweep_visible
    assert "increase the neutral-axis sweep maximum increment" in sweep_visible
    assert "too fine to calculate reliably" in sweep_visible
    assert not any(
        token in sweep_visible
        for token in (
            "4097",
            "tuple",
            "allocation",
            "payload",
            "schema",
            "hash",
            "traceback",
        )
    )

    too_wide = _mutated_project(valid_a, unrepresentable_sweep_span)
    _upload(at, too_wide)
    assert not at.exception
    assert _project_signature(at) == before_project
    assert at.session_state["_project_upload_content_identity"] == before_identity
    assert at.session_state["v_min"] == pytest.approx(0.0)
    assert at.session_state["v_max"] == pytest.approx(360.0)
    _assert_result_evidence(at, before_results)
    span_visible = "\n".join(str(item.value) for item in at.error)
    assert "New file was not applied" in span_visible
    assert "correct the neutral-axis sweep start and end angles" in span_visible
    assert "separation is too large to calculate reliably" in span_visible
    assert "increase the neutral-axis sweep maximum increment" not in span_visible

    hostile = (
        _mutated_project(valid_a, scalar("conc_fck", True)),
        _mutated_project(valid_a, scalar("qsv_b_mm", "400")),
        _mutated_project(valid_a, scalar("mode", {"value": "Both"})),
        _mutated_project(valid_a, scalar("shear_method", True)),
        _mutated_project(valid_a, scalar("torsion_design_basis", True)),
        _mutated_project(
            valid_a,
            scalar("torsion_member_scope", "Closed section"),
        ),
        _mutated_project(
            valid_a,
            scalar(
                capacity.TORSION_CASE_AUTHORITIES_KEY,
                {
                    "PL-01": {
                        capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                            capacity.TORSION_DESIGN_EQUILIBRIUM
                        ),
                        capacity.TORSION_CASE_MEMBER_SCOPE_KEY: True,
                    }
                },
            ),
        ),
        _mutated_project(valid_a, scalar("sls_code", {})),
        _mutated_project(valid_a, wrong_rows),
        _mutated_project(valid_a, negative_bar_area),
        _mutated_project(valid_a, nan_plastic_action, rehash=False),
        _mutated_project(
            valid_a,
            scalar("conc_fck", float("nan")),
            rehash=False,
        ),
    )

    forbidden = (
        "conc_fck",
        "qsv_b_mm",
        "shear_method",
        "torsion_design_basis",
        "torsion_member_scope",
        "sls_code",
        "plastic_cases_base",
        "bars_base",
        "area (mm2)",
        "Boolean",
        "finite number",
        "NaN",
        "payload",
        "schema",
        "hash",
        "traceback",
    )
    for content in hostile:
        _upload(at, content)

        assert not at.exception
        assert _project_signature(at) == before_project
        assert at.session_state["_project_upload_content_identity"] == (
            before_identity
        )
        assert at.session_state["conc_fck"] == pytest.approx(41.0)
        _assert_result_evidence(at, before_results)
        visible = "\n".join(str(item.value) for item in at.error)
        assert "New file was not applied" in visible
        assert "Select an intact, compatible Sector project file" in visible
        assert not any(token in visible for token in forbidden)

    # The retained project still mounts its real Material widget after every
    # rejection; no hostile value reached Streamlit's widget construction.
    _goto_concrete(at)
    assert at.number_input(key="conc_fck").value == pytest.approx(41.0)
    assert not at.exception

    # A corrected valid selection remains usable and invalidates every old result
    # and report artefact only after complete successful application.
    _goto_project(at)
    valid_b = _mutated_project(valid_a, scalar("conc_fck", 42.0))
    _upload(at, valid_b)
    assert at.session_state["conc_fck"] == pytest.approx(42.0)
    assert at.session_state["_latest_inputs"]["concrete"].fck == pytest.approx(
        42.0
    )
    assert any("Project loaded" in str(item.value) for item in at.success)
    assert not at.exception
    for key in _RESULT_KEYS:
        assert key not in at.session_state


def test_real_upload_without_case_authority_ignores_permissive_global_aliases():
    at = _fresh()
    source = _replacement_bytes(at, 41.0)

    def remove_mapping_but_keep_old_aliases(data: dict) -> None:
        data["scalars"].pop(capacity.TORSION_CASE_AUTHORITIES_KEY, None)
        data["scalars"]["torsion_design_basis"] = (
            capacity.TORSION_DESIGN_EQUILIBRIUM
        )
        data["scalars"]["torsion_member_scope"] = (
            capacity.TORSION_MEMBER_CLOSED
        )

    candidate_era = _mutated_project(source, remove_mapping_but_keep_old_aliases)
    _goto_project(at)
    _upload(at, candidate_era)

    mapping = at.session_state[capacity.TORSION_CASE_AUTHORITIES_KEY]
    assert mapping == {
        "PL-01": {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
            ),
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: (
                capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
            ),
        }
    }
    _goto_page(at, "Inputs")
    at.session_state["_input_tab"] = f"1 {chr(0x00B7)} Analysis settings"
    at.run()
    assert at.selectbox(key="_torsion_case_design_basis::PL-01").value == (
        capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
    )
    assert at.selectbox(key="_torsion_case_member_scope::PL-01").value == (
        capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
    )

    cases = at.session_state[load_cases.PLASTIC_TABLE_KEY].copy(deep=True)
    cases.at[0, "t_ed_knm"] = 40.0
    at.session_state[load_cases.PLASTIC_TABLE_KEY] = load_cases.normalise_table(
        cases,
        load_cases.PLASTIC_TABLE_KEY,
    )
    for key in (
        "plastic_cases_editor",
        f"_{load_cases.PLASTIC_TABLE_KEY}_editor_seed",
    ):
        try:
            del at.session_state[key]
        except KeyError:
            pass
    at.checkbox(key="torsion_on").set_value(True).run()
    _calculate(at)
    result = at.session_state["results"]["plastic_cases"][0]["results"][
        "torsion"
    ]
    assert result["assessment_status"] == "NOT ASSESSED"
    assert result["trd"] is None
    assert result["util"] is None
    assert not at.exception


def test_real_upload_rejects_invalid_material_domain_transactionally() -> None:
    at = _fresh().run()
    valid_a = _replacement_bytes(at, 41.0)
    _goto_project(at)
    _upload(at, valid_a)
    assert at.session_state["conc_fck"] == pytest.approx(41.0)

    before_results = _completed_result_evidence(at)
    before_project = _project_signature(at)
    before_identity = at.session_state["_project_upload_content_identity"]

    def reverse_mild_strengths(data: dict) -> None:
        item = data["scalars"][material_catalog.MILD_CATALOG_KEY]["items"][0]
        item.update(fytk=500.0, fyck=700.0, futk=600.0)

    def overflow_mild_design_ultimate(data: dict) -> None:
        item = data["scalars"][material_catalog.MILD_CATALOG_KEY]["items"][0]
        item.update(
            curve=1,
            fytk=500.0,
            fyck=500.0,
            futk=1.0e308,
            gamma_y=1.0,
            gamma_u=1.0e-308,
        )

    def underflow_prestress_design_ordinates(data: dict) -> None:
        item = data["scalars"][
            material_catalog.PRESTRESS_CATALOG_KEY
        ]["items"][0]
        item.update(
            curve=7,
            fytk=1.0e-308,
            futk=1.0e-308,
            gamma_y=1.0e308,
            gamma_u=1.0e308,
        )

    def overflow_mild_factored_yield_strain(data: dict) -> None:
        item = data["scalars"][material_catalog.MILD_CATALOG_KEY]["items"][0]
        item.update(
            curve=1,
            active_in_compression=False,
            fytk=1.0e308,
            fyck=0.0,
            futk=1.0e308,
            eut=2000.0,
            gamma_y=1.0e307,
            gamma_u=1.0e307,
            gamma_E=1.0e308,
            Es=1.0e305,
        )

    def underflow_prestress_factored_yield_strain(data: dict) -> None:
        item = data["scalars"][
            material_catalog.PRESTRESS_CATALOG_KEY
        ]["items"][0]
        item.update(
            curve=7,
            IS=0.0,
            fytk=1.0e-308,
            futk=1.0e-308,
            eut=2000.0,
            gamma_y=1.0e-308,
            gamma_u=1.0e-308,
            gamma_E=1.0e-306,
            Es=1.0e-310,
            k=1.0,
            ey0t=0.0,
        )

    def overflow_builtin_prestress_design_stress(data: dict) -> None:
        item = data["scalars"][
            material_catalog.PRESTRESS_CATALOG_KEY
        ]["items"][0]
        item.update(curve=1, IS=0.0, gamma_y=1.0e-308)

    def tiny_descending_mild_design_branch(data: dict) -> None:
        item = data["scalars"][material_catalog.MILD_CATALOG_KEY]["items"][0]
        item.update(
            curve=1,
            active_in_compression=False,
            fytk=1.0e-308,
            fyck=0.0,
            futk=1.0e-308,
            eut=50.0,
            gamma_y=1.0,
            gamma_u=2.0,
            gamma_E=1.0,
            Es=1.0e-309,
        )

    for mutation in (
        reverse_mild_strengths,
        overflow_mild_design_ultimate,
        underflow_prestress_design_ordinates,
        overflow_mild_factored_yield_strain,
        underflow_prestress_factored_yield_strain,
        overflow_builtin_prestress_design_stress,
        tiny_descending_mild_design_branch,
    ):
        invalid = _mutated_project(valid_a, mutation)
        _upload(at, invalid)

        assert not at.exception
        assert _project_signature(at) == before_project
        assert at.session_state["_project_upload_content_identity"] == (
            before_identity
        )
        assert at.session_state["conc_fck"] == pytest.approx(41.0)
        _assert_result_evidence(at, before_results)
        visible = "\n".join(str(item.value) for item in at.error)
        assert "New file was not applied" in visible
        assert "Select an intact, compatible Sector project file" in visible
        assert not any(
            token in visible
            for token in (
                "futk",
                "gamma_u",
                "gamma_E",
                "infinity",
                "nan",
                "payload",
                "schema",
                "contract",
                "hash",
                "traceback",
            )
        )

    def corrected_project(data: dict) -> None:
        scalars = data["scalars"]
        scalars.update(
            conc_fck=42.0,
            mild_fytk=500.0,
            mild_fyck=500.0,
            mild_futk=550.0,
            mild_gamma_y=1.0,
            mild_gamma_u=1.1,
            mild_gamma_E=1.0,
            pre_fytk=1600.0,
            pre_futk=1760.0,
            pre_gamma_y=1.0,
            pre_gamma_u=1.1,
            pre_gamma_E=1.0,
        )
        mild = scalars[material_catalog.MILD_CATALOG_KEY]["items"][0]
        mild.update(
            curve=3,
            fytk=500.0,
            fyck=500.0,
            futk=550.0,
            gamma_y=1.0,
            gamma_u=1.1,
            gamma_E=1.0,
        )
        prestress = scalars[material_catalog.PRESTRESS_CATALOG_KEY]["items"][0]
        prestress.update(
            curve=7,
            fytk=1600.0,
            futk=1760.0,
            gamma_y=1.0,
            gamma_u=1.1,
            gamma_E=1.0,
        )

    valid_b = _mutated_project(valid_a, corrected_project)
    _upload(at, valid_b)

    assert not at.exception
    assert at.session_state["conc_fck"] == pytest.approx(42.0)
    assert any("Project loaded" in str(item.value) for item in at.success)
    for key in _RESULT_KEYS:
        assert key not in at.session_state

    _calculate(at)
    snapshot = at.session_state["result_input_snapshot"]
    assert snapshot["steel"].futk / snapshot["steel"].gamma_u == (
        pytest.approx(snapshot["steel"].fytk / snapshot["steel"].gamma_y)
    )
    assert snapshot["prestress"].futk / snapshot["prestress"].gamma_u == (
        pytest.approx(
            snapshot["prestress"].fytk / snapshot["prestress"].gamma_y
        )
    )


def test_real_upload_accepts_extreme_finite_hardening_laws_and_calculates() -> None:
    at = _fresh().run()
    source = _replacement_bytes(at, 41.0)

    def extreme_finite_laws(data: dict) -> None:
        scalars = data["scalars"]
        mild = scalars[material_catalog.MILD_CATALOG_KEY]["items"][0]
        mild.update(
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
        prestress = scalars[
            material_catalog.PRESTRESS_CATALOG_KEY
        ]["items"][0]
        prestress.update(
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
        scalars.update(
            mild_preset=material_catalog.CUSTOM_PRESET,
            mild_active_comp=False,
            mild_fytk=1.0,
            mild_fyck=0.0,
            mild_futk=1.0e308,
            mild_eut=1.0e308,
            mild_gamma_y=1.0,
            mild_gamma_u=1.0,
            mild_gamma_E=1.0,
            mild_Es=200.0,
            pre_preset=material_catalog.CUSTOM_PRESET,
            pre_IS=0.0,
            pre_fytk=1.0,
            pre_futk=1.0e308,
            pre_eut=1.0e308,
            pre_gamma_y=1.0,
            pre_gamma_u=1.0,
            pre_gamma_E=1.0,
            pre_Es=200.0,
        )

    _goto_project(at)
    _upload(at, _mutated_project(source, extreme_finite_laws))

    assert not at.exception
    assert any("Project loaded" in str(item.value) for item in at.success)
    _calculate(at)
    snapshot = at.session_state["result_input_snapshot"]
    for material, representative_strain in (
        (snapshot["steel"], 0.0035),
        (snapshot["prestress"], 0.0059),
    ):
        assert math.isfinite(material.stress(representative_strain))
        assert math.isfinite(material.stress(material.eut))
    assert not at.exception


def test_real_upload_uses_catalogues_without_recreating_orphaned_aliases() -> None:
    at = _fresh().run()
    source = _replacement_bytes(at, 41.0)

    def catalogues_without_alias_ids(data: dict) -> None:
        scalars = data["scalars"]
        scalars[material_catalog.MILD_CATALOG_KEY] = {
            "version": material_catalog.VERSION,
            "next_id": 3,
            "items": [
                material_catalog.default_entry("mild", material_id="M2")
            ],
        }
        scalars[material_catalog.PRESTRESS_CATALOG_KEY] = {
            "version": material_catalog.VERSION,
            "next_id": 3,
            "items": [
                material_catalog.default_entry(
                    "prestress", material_id="P2"
                )
            ],
        }
        scalars.update(
            mild_fytk=500.0,
            mild_fyck=700.0,
            mild_futk=600.0,
            pre_fytk=1600.0,
            pre_futk=1500.0,
            capacity_steel_material_id="M2",
        )
        for table_key, old_id, new_id in (
            ("bars_base", "M1", "M2"),
            ("tendons_base", "P1", "P2"),
        ):
            table = data["tables"][table_key]
            material_column = table["columns"].index(rebar_table.MATERIAL_ID)
            for row in table["rows"]:
                if row[material_column] == old_id:
                    row[material_column] = new_id

    _goto_project(at)
    _upload(at, _mutated_project(source, catalogues_without_alias_ids))

    assert not at.exception
    assert any("Project loaded" in str(item.value) for item in at.success)
    assert [
        item["id"]
        for item in at.session_state[
            material_catalog.MILD_CATALOG_KEY
        ]["items"]
    ] == ["M2"]
    assert [
        item["id"]
        for item in at.session_state[
            material_catalog.PRESTRESS_CATALOG_KEY
        ]["items"]
    ] == ["P2"]

    tables = {
        key: at.session_state[key]
        for key in project_io.PROJECT_TABLE_KEYS
        if key in at.session_state
    }
    scalars = {
        key: at.session_state[key]
        for key in project_io.SCALAR_KEYS
        if key in at.session_state
    }
    saved = project_io.dump_project(tables, scalars)
    _, reloaded = project_io.parse_project(saved)
    assert [
        item["id"]
        for item in reloaded[material_catalog.MILD_CATALOG_KEY]["items"]
    ] == ["M2"]
    assert [
        item["id"]
        for item in reloaded[material_catalog.PRESTRESS_CATALOG_KEY]["items"]
    ] == ["P2"]

    _calculate(at)
    snapshot = at.session_state["result_input_snapshot"]
    assert set(snapshot["mild_materials"]) == {"M2"}
    assert set(snapshot["prestress_materials"]) == {"P2"}
    assert not at.exception


def test_nonfinite_json_tokens_are_rejected_before_any_numeric_fallback() -> None:
    text = project_io.dump_project({}, {"conc_fck": 41.0})
    for token in (float("nan"), float("inf"), -float("inf")):
        data = json.loads(text)
        data["scalars"]["conc_fck"] = token
        hostile = json.dumps(data, allow_nan=True)
        with pytest.raises(project_io.ProjectInputError) as exc_info:
            project_io.parse_project(hostile)
        public = project_io.engineer_error_message(exc_info.value)
        assert public == "the project file contains an invalid input value"
        assert not math.isfinite(token)
