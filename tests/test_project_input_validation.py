"""STATE-M01 project scalar, nested-table and real upload validation."""

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


_RESULT_KEYS = (
    "results",
    "result_sig",
    "result_plastic_sig",
    "result_elastic_sig",
    "result_fatigue_sig",
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

    hostile = (
        _mutated_project(valid_a, scalar("conc_fck", True)),
        _mutated_project(valid_a, scalar("qsv_b_mm", "400")),
        _mutated_project(valid_a, scalar("mode", {"value": "Both"})),
        _mutated_project(valid_a, wrong_rows),
        _mutated_project(
            valid_a,
            scalar("conc_fck", float("nan")),
            rehash=False,
        ),
    )

    forbidden = (
        "conc_fck",
        "qsv_b_mm",
        "plastic_cases_base",
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


def test_nonfinite_json_tokens_are_rejected_before_any_numeric_fallback() -> None:
    text = project_io.dump_project({}, {"conc_fck": 41.0})
    for token in (float("nan"), float("inf"), -float("inf")):
        data = json.loads(text)
        data["scalars"]["conc_fck"] = token
        hostile = json.dumps(data, allow_nan=True)
        with pytest.raises(project_io.ProjectInputError) as exc_info:
            project_io.parse_project(hostile)
        public = project_io.engineer_error_message(exc_info.value)
        assert public == "the project file is incomplete or damaged"
        assert not math.isfinite(token)
