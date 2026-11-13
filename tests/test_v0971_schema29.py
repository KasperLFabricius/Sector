"""Schema 29: section-model provisions with no engineering effect.

The expected values come from the schema-29 rules of the 0.97.1 PR plan
(decisions 5, 6, 7 and 12): outer corners C<n>, void corners V<n> unique over
all voids, an edge is the ordered pair of its corner IDs, one region A1, bar
groups G<n> with a group ID column on the elements, the case attributes
(location tag, design situation default persistent, stage blank or "final")
and the automatic-recalculation preference (off by default). Schemas 25 to 28
load with the present behaviour.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "app"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import case_analysis  # noqa: E402
import load_cases  # noqa: E402
import project_io  # noqa: E402

from app import reinforcement_table as rebar  # noqa: E402
from app import reproducible_example, section_ids  # noqa: E402
from sector import capacity  # noqa: E402

PLASTIC = load_cases.PLASTIC_TABLE_KEY
ELASTIC = load_cases.ELASTIC_TABLE_KEY
SCHEMA29_SCALARS = (
    section_ids.REGIONS_KEY,
    rebar.GROUPS_KEY,
    project_io.AUTO_RECALCULATE_KEY,
)
SCHEMA28_SCALARS = (
    "conc_pivot_c",
    capacity.MED_MAX_ON_KEY,
    *capacity.MED_MAX_KEYS.values(),
    capacity.SHEAR_TENDONS_KEY,
)
WIDTH_KEYS = (
    "sls_long_term_permitted_crack_width_mm",
    "sls_short_term_permitted_crack_width_mm",
    "sls_heightened_permitted_crack_width_mm",
)


def _reference():
    return reproducible_example.project_tables(), reproducible_example.project_scalars()


def _payload(tables=None, scalars=None) -> dict:
    if tables is None or scalars is None:
        tables, scalars = _reference()
    return json.loads(project_io.dump_project(tables, scalars))


def _rehash(payload: dict) -> str:
    payload["provenance"]["input_sha256"] = (
        project_io.recorded_input_sha256(payload)
    )
    return json.dumps(payload)


def _drop_columns(table: dict, names) -> None:
    keep = [i for i, column in enumerate(table["columns"]) if column not in names]
    table["columns"] = [table["columns"][i] for i in keep]
    table["rows"] = [[row[i] for i in keep] for row in table["rows"]]


def _older_text(version: int, *, legacy_columns: bool = True) -> str:
    """Return the reference project in the form that ``version`` wrote."""

    payload = _payload()
    payload["version"] = version
    scalars = payload["scalars"]
    for key in SCHEMA29_SCALARS:
        scalars.pop(key)
    if legacy_columns:
        tables = payload["tables"]
        for key in section_ids.GEOMETRY_TABLE_KEYS:
            _drop_columns(tables[key], {section_ids.ID})
        for key in project_io.REINFORCEMENT_TABLE_KEYS:
            _drop_columns(tables[key], {rebar.GROUP_ID})
        for key in load_cases.CASE_TABLE_KEYS:
            _drop_columns(tables[key], set(load_cases.ATTRIBUTE_COLUMNS))
    if version <= project_io.PREVIOUS_VERSION:
        for key in SCHEMA28_SCALARS:
            scalars.pop(key, None)
    if version <= project_io.MIGRATABLE_VERSION:
        scalars.pop("shear_gamma_v")
        scalars.pop(capacity.TORSION_CASE_AUTHORITIES_KEY)
    if version == project_io.LEGACY_MIGRATABLE_VERSION:
        shared = scalars["sls_long_term_permitted_crack_width_mm"]
        for key in WIDTH_KEYS:
            scalars.pop(key)
        scalars[project_io.LEGACY_SHARED_CRACK_WIDTH_KEY] = shared
    return _rehash(payload)


def _comparable(tables, scalars):
    """Canonical content of one parsed project, for exact comparison."""

    content = project_io._canonical_inputs(tables, scalars)
    return json.loads(json.dumps(content))


# --- Defaults of a new project -------------------------------------------


def test_schema_29_is_current_and_28_migrates():
    assert project_io.VERSION == 29
    assert project_io.SCHEMA28_VERSION == 28
    assert project_io.MIGRATABLE_VERSIONS == (25, 26, 27, 28)
    assert set(SCHEMA29_SCALARS) <= set(project_io.SCALAR_KEYS)
    assert project_io.AUTO_RECALCULATE_KEY in project_io._BOOLEAN_SCALAR_KEYS
    assert {section_ids.REGIONS_KEY, rebar.GROUPS_KEY} <= (
        project_io._NESTED_SCALAR_KEYS
    )


def test_new_project_saves_every_schema29_field_at_its_default():
    payload = _payload()
    tables = payload["tables"]
    corners = tables["corners_base"]
    assert corners["columns"] == ["ID", "x (mm)", "y (mm)"]
    # The reference outer ring has four corners, numbered in row order.
    assert [row[0] for row in corners["rows"]] == ["C1", "C2", "C3", "C4"]
    for key in project_io.REINFORCEMENT_TABLE_KEYS:
        assert tables[key]["columns"] == rebar.PROJECT_COLUMNS
        assert all(row[-1] == "" for row in tables[key]["rows"])
    for key in load_cases.CASE_TABLE_KEYS:
        columns = tables[key]["columns"]
        assert columns[-3:] == ["location_tag", "design_situation", "stage"]
        for row in tables[key]["rows"]:
            assert row[-3:] == ["", "persistent", ""]
    scalars = payload["scalars"]
    assert scalars[section_ids.REGIONS_KEY] == {
        "version": 1,
        "items": [{"id": "A1", "template": None, "next_corner": 5,
                   "next_void_corner": 1}],
    }
    assert scalars[rebar.GROUPS_KEY] == {"version": 1, "next_id": 1, "items": []}
    assert scalars[project_io.AUTO_RECALCULATE_KEY] is False


def test_empty_project_has_the_defaults_and_empty_id_tables():
    payload = json.loads(project_io.dump_project({}, {}))
    assert payload["tables"]["corners_base"] == {
        "columns": ["ID", "x (mm)", "y (mm)"],
        "rows": [],
    }
    assert payload["scalars"][project_io.AUTO_RECALCULATE_KEY] is False


# --- Stable IDs and the edge identity rule --------------------------------


def test_void_corner_ids_are_unique_over_all_voids_and_separators_have_none():
    holes = pd.DataFrame({
        "x (mm)": [0.0, 10.0, 0.0, None, 50.0, 60.0, 50.0],
        "y (mm)": [0.0, 0.0, 10.0, None, 0.0, 0.0, 10.0],
    })
    frame = section_ids.normalise_geometry_table(holes, "hole_base")
    assert frame["ID"].tolist() == ["V1", "V2", "V3", "", "V4", "V5", "V6"]


def test_a_deletion_keeps_the_other_ids_and_a_new_row_gets_the_next_number():
    corners = section_ids.normalise_geometry_table(
        pd.DataFrame({"x (mm)": [0, 1, 1, 0], "y (mm)": [0, 0, 1, 1]}),
        "corners_base",
    )
    after_delete = corners.drop(index=1).reset_index(drop=True)
    after_delete.loc[len(after_delete)] = ["", 0.5, 2.0]
    frame = section_ids.normalise_geometry_table(after_delete, "corners_base")
    # C2 was deleted: C1, C3 and C4 keep their IDs, the new row is C5.
    assert frame["ID"].tolist() == ["C1", "C3", "C4", "C5"]


def test_invalid_and_duplicate_ids_get_the_next_free_number():
    frame = section_ids.normalise_geometry_table(
        pd.DataFrame({
            "ID": ["C7", "C7", "V1", "x", "C2"],
            "x (mm)": [0.0, 1.0, 1.0, 0.0, 2.0],
            "y (mm)": [0.0, 0.0, 1.0, 1.0, 2.0],
        }),
        "corners_base",
    )
    assert frame["ID"].tolist() == ["C7", "C8", "C9", "C10", "C2"]


def test_edge_identity_is_the_ordered_pair_of_corner_ids():
    assert section_ids.edge_id("C3", "C4") == "C3-C4"
    assert section_ids.ring_edge_ids(["C1", "C3", "C4"]) == [
        "C1-C3", "C3-C4", "C4-C1",
    ]
    assert section_ids.ring_edge_ids(["V1", "V2"]) == []
    assert section_ids.parse_edge_id("V2-V5") == ("V2", "V5")
    for invalid in ("C1-V2", "C1-C1", "C1", "C1-C2-C3", "R1-C2", 3):
        with pytest.raises(ValueError):
            section_ids.parse_edge_id(invalid)


# --- Save and load round trip ---------------------------------------------


def _schema29_project():
    """A project with non-default values in every schema-29 field."""

    tables, scalars = _reference()
    corners = section_ids.normalise_geometry_table(
        tables["corners_base"], "corners_base"
    )
    corners["ID"] = ["C1", "C3", "C4", "C9"]
    tables["corners_base"] = corners
    bars = rebar.normalise_table(tables["bars_base"], "bar", with_group=True)
    bars.loc[bars.index[:2], rebar.GROUP_ID] = "G2"
    tables["bars_base"] = bars
    plastic = load_cases.normalise_table(tables[PLASTIC], PLASTIC)
    plastic[load_cases.LOCATION_TAG] = "Support A"
    plastic[load_cases.DESIGN_SITUATION] = "accidental"
    plastic[load_cases.STAGE] = "final"
    tables[PLASTIC] = plastic
    elastic = load_cases.normalise_table(tables[ELASTIC], ELASTIC)
    elastic[load_cases.DESIGN_SITUATION] = "transient"
    tables[ELASTIC] = elastic
    scalars = dict(scalars)
    scalars[section_ids.REGIONS_KEY] = {
        "version": 1,
        "items": [{
            "id": "A1",
            "next_corner": 12,
            "template": {
                "kind": "Rectangle",
                "parameters": {"b_mm": 200.0, "h_mm": 300, "flag": True},
            },
        }],
    }
    scalars[rebar.GROUPS_KEY] = {
        "version": 1,
        "next_id": 4,
        "items": [{
            "id": "G2",
            "element": "bar",
            "generator": "line",
            "parameters": {"n": 2, "diameter_mm": 16.0, "edge": "C1-C3"},
            "material_id": "M1",
        }],
    }
    scalars[project_io.AUTO_RECALCULATE_KEY] = True
    return tables, scalars


def test_schema29_fields_round_trip_exactly():
    tables, scalars = _schema29_project()
    text = project_io.dump_project(tables, scalars)
    loaded_tables, loaded_scalars, info = project_io.parse_project_with_info(text)
    assert info["source_schema_version"] == 29
    assert info["migrated"] is False
    assert info["migration_warnings"] == ()
    assert info["method_changes"] == ()
    assert loaded_tables["corners_base"]["ID"].tolist() == ["C1", "C3", "C4", "C9"]
    assert loaded_tables["bars_base"][rebar.GROUP_ID].tolist()[:3] == [
        "G2", "G2", "",
    ]
    assert set(loaded_tables[PLASTIC][load_cases.LOCATION_TAG]) == {"Support A"}
    assert set(loaded_tables[PLASTIC][load_cases.DESIGN_SITUATION]) == {"accidental"}
    assert set(loaded_tables[PLASTIC][load_cases.STAGE]) == {"final"}
    assert set(loaded_tables[ELASTIC][load_cases.DESIGN_SITUATION]) == {"transient"}
    assert loaded_scalars[section_ids.REGIONS_KEY]["items"][0]["template"] == {
        "kind": "Rectangle",
        "parameters": {"b_mm": 200.0, "flag": True, "h_mm": 300},
    }
    assert type(
        loaded_scalars[section_ids.REGIONS_KEY]["items"][0]["template"][
            "parameters"]["h_mm"]
    ) is int
    assert loaded_scalars[rebar.GROUPS_KEY]["items"][0]["id"] == "G2"
    assert loaded_scalars[rebar.GROUPS_KEY]["next_id"] == 4
    assert loaded_scalars[project_io.AUTO_RECALCULATE_KEY] is True
    resaved = project_io.dump_project(loaded_tables, loaded_scalars)
    assert json.loads(resaved)["provenance"]["input_sha256"] == (
        json.loads(text)["provenance"]["input_sha256"]
    )
    assert json.loads(resaved)["tables"] == json.loads(text)["tables"]
    assert json.loads(resaved)["scalars"] == json.loads(text)["scalars"]


def test_group_next_id_is_above_every_group_number():
    groups = project_io._validate_reinforcement_groups(
        {
            "version": 1,
            "next_id": 1,
            "items": [{
                "id": "G5", "element": "tendon", "generator": "ring",
                "parameters": {}, "material_id": "P1",
            }],
        },
        rebar.GROUPS_KEY,
    )
    assert groups["next_id"] == 6


# --- Load matrix of the older schemas ------------------------------------


@pytest.mark.parametrize("legacy_columns", (True, False))
@pytest.mark.parametrize("version", (25, 26, 27, 28))
def test_older_schema_loads_with_the_schema29_defaults(version, legacy_columns):
    text = _older_text(version, legacy_columns=legacy_columns)
    tables, scalars, info = project_io.parse_project_with_info(text)
    assert info["source_schema_version"] == version
    assert info["target_schema_version"] == 29
    # A 0.97.0 schema-28 file gets only defaults with no engineering effect.
    assert info["migrated"] is (version < 28)
    assert list(tables["corners_base"].columns) == list(section_ids.COLUMNS)
    assert tables["corners_base"]["ID"].tolist() == ["C1", "C2", "C3", "C4"]
    for key in project_io.REINFORCEMENT_TABLE_KEYS:
        assert set(tables[key][rebar.GROUP_ID]) <= {""}
    for key in load_cases.CASE_TABLE_KEYS:
        frame = tables[key]
        assert list(frame.columns) == list(load_cases.PERSISTED_COLUMNS[key])
        assert set(frame[load_cases.LOCATION_TAG]) <= {""}
        assert set(frame[load_cases.DESIGN_SITUATION]) <= {"persistent"}
        assert set(frame[load_cases.STAGE]) <= {""}
    assert scalars[section_ids.REGIONS_KEY]["items"] == [{
        "id": "A1", "template": None, "next_corner": 5, "next_void_corner": 1,
    }]
    assert scalars[rebar.GROUPS_KEY] == project_io.default_reinforcement_groups()
    assert scalars[project_io.AUTO_RECALCULATE_KEY] is False
    message = " ".join(info["method_changes"])
    if version == 28:
        # Schema 28 has the current methods: no method-change message.
        assert info["method_changes"] == ()
        assert info["migration_warnings"] == ()
    else:
        assert "corrected methods" in message
    if version == 25:
        assert any(
            "one permitted crack width" in warning
            for warning in info["migration_warnings"]
        )
    else:
        assert not any(
            "one permitted crack width" in warning
            for warning in info["migration_warnings"]
        )


def test_schema28_file_gives_the_same_inputs_as_its_schema29_save():
    """The 28-to-29 migration adds only fields with no engineering effect."""

    old_tables, old_scalars = project_io.parse_project(_older_text(28))
    new_tables, new_scalars = project_io.parse_project(
        project_io.dump_project(*_reference())
    )
    assert _comparable(old_tables, old_scalars) == _comparable(
        new_tables, new_scalars
    )


def test_development_schema28_file_keeps_its_method_message():
    payload = json.loads(_older_text(28))
    payload["provenance"]["sector_version"] = "0.96.9"
    _tables, _scalars, info = project_io.parse_project_with_info(_rehash(payload))
    assert "corrected methods" in " ".join(info["method_changes"])


def test_schema29_file_with_the_older_columns_is_rejected():
    payload = _payload()
    _drop_columns(payload["tables"]["corners_base"], {section_ids.ID})
    with pytest.raises(project_io.ProjectInputError, match="current format"):
        project_io.parse_project(_rehash(payload))


def test_schema28_file_with_a_group_reference_needs_the_group():
    payload = json.loads(_older_text(28, legacy_columns=False))
    bars = payload["tables"]["bars_base"]
    bars["rows"][0][bars["columns"].index(rebar.GROUP_ID)] = "G1"
    with pytest.raises(project_io.ProjectInputError, match="not a bar group"):
        project_io.parse_project(_rehash(payload))


# --- Validation of the schema-29 fields ----------------------------------


def _regions(items):
    return {"version": 1, "items": items}


@pytest.mark.parametrize(
    "value",
    (
        _regions([]),
        _regions([{"id": "A1"}, {"id": "A1"}]),
        _regions([{"id": "S1"}]),
        _regions([{"id": "R1"}]),
        _regions([{"id": "A2"}]),
        _regions([{"id": "A1", "next_corner": 0}]),
        _regions([{"id": "A1", "next_void_corner": 2.0}]),
        _regions([{"id": "A1", "name": "deck"}]),
        _regions([{"id": "A1", "template": {"kind": "Hexagon", "parameters": {}}}]),
        _regions([{"id": "A1", "template": {"kind": "Rectangle"}}]),
        _regions([{"id": "A1", "template": {
            "kind": "Rectangle", "parameters": {"b_mm": float("nan")}}}]),
        _regions([{"id": "A1", "template": {
            "kind": "Rectangle", "parameters": {"B": 1.0}}}]),
        _regions([{"id": "A1", "template": {
            "kind": "Rectangle", "parameters": {"b": [1.0]}}}]),
        _regions([{"id": "A1", "template": {
            "kind": "Rectangle", "parameters": {"note": "a\nb"}}}]),
        {"version": 2, "items": [{"id": "A1"}]},
        {"items": [{"id": "A1"}], "next_id": 2},
        [{"id": "A1"}],
    ),
)
def test_invalid_region_lists_are_rejected(value):
    with pytest.raises(project_io.ProjectInputError):
        project_io._canonical_scalars({section_ids.REGIONS_KEY: value}, {})


def test_a_region_without_optional_fields_gets_the_defaults():
    scalars = project_io._canonical_scalars(
        {section_ids.REGIONS_KEY: _regions([{"id": "A1"}])}, {}
    )
    assert scalars[section_ids.REGIONS_KEY]["items"] == [{
        "id": "A1", "template": None, "next_corner": 1, "next_void_corner": 1,
    }]


def test_a_deleted_highest_id_is_not_issued_again():
    """D1-R1-02: the region counter keeps a deleted ID from being reused."""

    tables, scalars = _reference()
    corners = section_ids.normalise_geometry_table(
        tables["corners_base"], "corners_base"
    )
    tables["corners_base"] = corners
    tables, scalars = project_io.parse_project(project_io.dump_project(tables, scalars))
    assert scalars[section_ids.REGIONS_KEY]["items"][0]["next_corner"] == 5
    corners = tables["corners_base"].copy()
    corners.loc[3, "ID"] = ""          # C4 deleted, a new row in its place
    tables["corners_base"] = corners
    saved = json.loads(project_io.dump_project(tables, scalars))
    assert [row[0] for row in saved["tables"]["corners_base"]["rows"]] == [
        "C1", "C2", "C3", "C5",
    ]
    assert saved["scalars"][section_ids.REGIONS_KEY]["items"][0]["next_corner"] == 6


def _group(**changes):
    group = {
        "id": "G1", "element": "bar", "generator": "face",
        "parameters": {"spacing_mm": 150.0}, "material_id": "M1",
    }
    group.update(changes)
    return {"version": 1, "items": [group]}


@pytest.mark.parametrize(
    "value",
    (
        _group(id="B1"),
        _group(id=1),
        _group(element="link"),
        _group(generator="spiral"),
        _group(material_id=""),
        _group(material_id=" M1"),
        _group(parameters=[]),
        _group(parameters={"n": float("inf")}),
        {"version": 1, "items": [
            {"id": "G1", "element": "bar", "generator": "line",
             "parameters": {}}]},
        {"version": 1, "items": [_group()["items"][0], _group()["items"][0]]},
        [],
    ),
)
def test_invalid_bar_groups_are_rejected(value):
    with pytest.raises(project_io.ProjectInputError):
        project_io._canonical_scalars({rebar.GROUPS_KEY: value}, {})


def test_a_group_material_must_be_defined():
    tables, scalars = _reference()
    scalars[rebar.GROUPS_KEY] = _group(material_id="M9")
    with pytest.raises(ValueError, match="M9"):
        project_io.dump_project(tables, scalars)


def test_an_element_group_must_exist_with_the_same_element_kind():
    tables, scalars = _reference()
    tendons = rebar.normalise_table(
        rebar.table_from_points([(0.0, -100.0, 150.0)], "tendon"),
        "tendon",
        with_group=True,
    )
    tendons.loc[tendons.index[0], rebar.GROUP_ID] = "G1"
    tables["tendons_base"] = tendons
    scalars[rebar.GROUPS_KEY] = _group()
    with pytest.raises(project_io.ProjectInputError, match="not a tendon group"):
        project_io.dump_project(tables, scalars)


@pytest.mark.parametrize(
    ("column", "value"),
    (
        (load_cases.DESIGN_SITUATION, "fire"),
        (load_cases.DESIGN_SITUATION, ""),
        (load_cases.DESIGN_SITUATION, "Persistent"),
        (load_cases.STAGE, "initial"),
        (load_cases.LOCATION_TAG, "line 1\nline 2"),
        (load_cases.LOCATION_TAG, "x" * 61),
        (load_cases.LOCATION_TAG, 3),
    ),
)
def test_invalid_case_attributes_in_a_file_are_rejected(column, value):
    payload = _payload()
    table = payload["tables"][PLASTIC]
    table["rows"][0][table["columns"].index(column)] = value
    with pytest.raises(project_io.ProjectInputError):
        project_io.parse_project(_rehash(payload))


def test_invalid_case_attributes_cannot_be_saved():
    tables, scalars = _reference()
    plastic = load_cases.normalise_table(tables[PLASTIC], PLASTIC)
    plastic[load_cases.STAGE] = "initial"
    tables[PLASTIC] = plastic
    assert load_cases.attribute_errors(plastic, PLASTIC)
    with pytest.raises(project_io.ProjectInputError):
        project_io.dump_project(tables, scalars)


def test_case_attributes_normalise_case_and_blank_values():
    frame = load_cases.normalise_table(
        [{"name": "PL-1", "design_situation": " Transient ", "stage": "FINAL"},
         {"name": "PL-2", "design_situation": None, "location_tag": " Pier 2 "}],
        PLASTIC,
    )
    assert frame[load_cases.DESIGN_SITUATION].tolist() == ["transient", "persistent"]
    assert frame[load_cases.STAGE].tolist() == ["final", ""]
    assert frame[load_cases.LOCATION_TAG].tolist() == ["", "Pier 2"]
    assert load_cases.attribute_errors(frame, PLASTIC) == []
    assert load_cases.case_attributes(frame, PLASTIC) == {
        "PL-1": {"location_tag": "", "design_situation": "transient",
                 "stage": "final"},
        "PL-2": {"location_tag": "Pier 2", "design_situation": "persistent",
                 "stage": ""},
    }


def test_void_separator_row_with_an_id_is_rejected():
    payload = _payload()
    holes = payload["tables"]["hole_base"]
    holes["rows"] = [
        ["V1", 0.0, 0.0], ["V2", 10.0, 0.0], ["V3", 0.0, 10.0],
        ["V4", None, None],
        ["V5", 50.0, 0.0], ["V6", 60.0, 0.0], ["V7", 50.0, 10.0],
    ]
    with pytest.raises(project_io.ProjectInputError, match="must have a blank ID"):
        project_io.parse_project(_rehash(payload))


# --- Hash and staleness rules (decision 7) -------------------------------


def test_case_attributes_stay_out_of_records_and_row_signatures():
    tables, _scalars = _reference()
    plastic = load_cases.normalise_table(tables[PLASTIC], PLASTIC)
    edited = plastic.copy(deep=True)
    edited[load_cases.LOCATION_TAG] = "Midspan"
    edited[load_cases.DESIGN_SITUATION] = "seismic"
    edited[load_cases.STAGE] = "final"
    inp = {"plastic_cases": plastic}
    inp_edited = {"plastic_cases": edited}
    records = case_analysis.case_records(inp, "plastic")
    records_edited = case_analysis.case_records(inp_edited, "plastic")
    assert records == records_edited
    assert not set(load_cases.ATTRIBUTE_COLUMNS) & set(records[0])
    assert [
        case_analysis.case_signature(record, PLASTIC) for record in records
    ] == [
        case_analysis.case_signature(record, PLASTIC) for record in records_edited
    ]
    # A blank row stays blank when only an attribute is set.
    blank = load_cases.normalise_table([{"location_tag": "Pier 1"}], PLASTIC)
    assert load_cases.active_table(blank, PLASTIC).empty


def test_schema29_fields_change_the_persistence_hash_only():
    tables, scalars = _reference()
    edited_tables, edited_scalars = _schema29_project()
    # The geometry, reinforcement and actions are the same.
    for key in ("corners_base", "bars_base", PLASTIC, ELASTIC):
        left = project_io._normalise_table(tables[key], key)
        right = project_io._normalise_table(edited_tables[key], key)
        engineering = [
            column for column in left.columns
            if column not in {
                section_ids.ID, rebar.GROUP_ID, *load_cases.ATTRIBUTE_COLUMNS,
            }
        ]
        pd.testing.assert_frame_equal(left[engineering], right[engineering])
    # Decision 7: the schema-29 fields are outside input_sha256.
    assert project_io.input_sha256(tables, scalars) == project_io.input_sha256(
        edited_tables, edited_scalars
    )
    assert project_io.persistence_sha256(
        tables, scalars
    ) != project_io.persistence_sha256(edited_tables, edited_scalars)


def test_no_schema29_key_is_a_staleness_signature_key():
    text = (ROOT / "app" / "sector_app.py").read_text(encoding="utf-8")
    start = text.index("_SHARED_SIG_KEYS = (")
    end = text.index("\n)\n", text.index("_ELASTIC_CONTEXT_SIG_KEYS = ("))
    signature_block = text[start:end]
    for key in (*SCHEMA29_SCALARS, *load_cases.ATTRIBUTE_COLUMNS):
        assert f'"{key}"' not in signature_block


# --- The application wiring ----------------------------------------------


@pytest.fixture(scope="module")
def _isolated_autosave(tmp_path_factory):
    key = "SECTOR_AUTOSAVE_DIR"
    previous = os.environ.get(key)
    os.environ[key] = str(tmp_path_factory.mktemp("v0971-schema29-autosave"))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _upload(at, text: str):
    from app_workflow_navigation import goto_input_stage

    goto_input_stage(at, "Project")
    at.file_uploader[0].set_value(
        ("schema29.json", text.encode("utf-8"), "application/json")
    ).run()
    assert not at.exception
    assert any("Project loaded" in str(item.value) for item in at.success)
    return at


def _app_save(at) -> dict:
    """Serialise the session as the project download does."""

    input_durable = dict(at.session_state["_durable_input_scalars"])
    report_durable = dict(at.session_state["_durable_report_scalars"])
    tables = {
        key: at.session_state[key]
        for key in project_io.PROJECT_TABLE_KEYS
        if key in at.session_state
    }
    scalars = {}
    for key in (*project_io.SCALAR_KEYS, *project_io.PRESENTATION_SCALAR_KEYS):
        if key in at.session_state:
            scalars[key] = at.session_state[key]
        elif key in input_durable:
            scalars[key] = input_durable[key]
        elif key in report_durable:
            scalars[key] = report_durable[key]
    return json.loads(project_io.dump_project(tables, scalars))


def test_app_loads_schema29_fields_and_keeps_the_engineering_inputs(
    _isolated_autosave,
):
    from streamlit.testing.v1 import AppTest

    app = str(ROOT / "app" / "sector_app.py")
    at = AppTest.from_file(app, default_timeout=180).run()
    _upload(at, project_io.dump_project(*_reference()))
    reference_signature = project_io.result_sha256(
        at.session_state["_latest_inputs"]["signature"]
    )
    _upload(at, project_io.dump_project(*_schema29_project()))
    # Decision 7: the schema-29 fields do not change the engineering inputs.
    assert project_io.result_sha256(
        at.session_state["_latest_inputs"]["signature"]
    ) == reference_signature
    # The live corner table shows the stored IDs (PR I1, decision 28). The
    # reinforcement tables keep their columns until PR I3.
    assert list(at.session_state["corners_base"].columns) == [
        "ID", "x (mm)", "y (mm)",
    ]
    assert list(at.session_state["bars_base"].columns) == rebar.COLUMNS
    assert at.session_state[project_io.AUTO_RECALCULATE_KEY] is True
    saved = _app_save(at)
    # The case attributes, the region list, the groups and the preference
    # survive the application save. The corners keep their stored IDs.
    plastic = saved["tables"][PLASTIC]
    index = plastic["columns"].index(load_cases.DESIGN_SITUATION)
    assert {row[index] for row in plastic["rows"]} == {"accidental"}
    assert saved["scalars"][section_ids.REGIONS_KEY]["items"][0]["template"][
        "kind"] == "Rectangle"
    assert saved["scalars"][rebar.GROUPS_KEY]["items"][0]["id"] == "G2"
    assert saved["scalars"][project_io.AUTO_RECALCULATE_KEY] is True
    assert [row[0] for row in saved["tables"]["corners_base"]["rows"]] == [
        "C1", "C3", "C4", "C9",
    ]
    assert project_io.parse_project(json.dumps(saved)) is not None


# --- Edge cases of the pure helpers --------------------------------------


def test_geometry_normaliser_reads_records_and_rejects_unknown_tables():
    frame = section_ids.normalise_geometry_table(
        [
            {"ID": ["C1"], "x (mm)": True, "y (mm)": "a"},
            {"x (mm)": "1.5", "y (mm)": float("inf")},
        ],
        "corners_base",
    )
    assert frame["ID"].tolist() == ["C1", "C2"]
    assert frame["x (mm)"].isna().tolist() == [True, False]
    assert frame["x (mm)"].iloc[1] == 1.5
    assert frame["y (mm)"].isna().all()
    assert section_ids.corner_ids(
        pd.DataFrame({"x (mm)": [0.0, None, 5.0], "y (mm)": [0.0, None, 5.0]}),
        "hole_base",
    ) == ["V1", "V2"]
    with pytest.raises(ValueError, match="unknown geometry table"):
        section_ids.normalise_geometry_table(None, "bars_base")
    assert list(
        section_ids.normalise_geometry_table(None, "corners_base").columns
    ) == list(section_ids.COLUMNS)


@pytest.mark.parametrize(
    "value",
    (
        {"version": 1, "items": "R1"},
        {"version": 1, "items": ["R1"]},
        {"version": 1, "items": [{"id": 1}]},
        {"version": 1, "items": [{"id": "A1", "template": "Rectangle"}]},
        {"version": 1, "items": [{"id": "A1", "template": {
            "kind": "Rectangle",
            "parameters": {f"p{i}": 1.0 for i in range(65)},
        }}]},
    ),
)
def test_region_list_shape_errors(value):
    with pytest.raises(ValueError):
        section_ids.validate_regions(value)


def test_attribute_and_table_helpers_fail_closed_for_unknown_input():
    assert load_cases.attribute_error(load_cases.LOCATION_TAG, 3) == "must be text"
    assert load_cases.attribute_error(load_cases.STAGE, "final") is None
    with pytest.raises(ValueError, match="unknown case attribute"):
        load_cases.attribute_error("phase", "final")
    with pytest.raises(RuntimeError, match="unhandled project table"):
        project_io._normalise_table(None, "links_base")


def test_app_load_of_a_0970_file_and_an_attribute_edit_keep_results_current(
    _isolated_autosave,
):
    """D1-R1-03 and D1-R1-14: a 0.97.0 file asks for no review of converted
    inputs, and an attribute edit does not change the engineering signature
    that the staleness check compares."""

    from streamlit.testing.v1 import AppTest

    app = str(ROOT / "app" / "sector_app.py")
    at = AppTest.from_file(app, default_timeout=180).run()
    _upload(at, _older_text(28))
    texts = " ".join(str(item.value) for item in (*at.success, *at.caption))
    assert "Review the converted inputs" not in texts
    assert "Project file updated" not in texts
    signature = project_io.result_sha256(
        at.session_state["_latest_inputs"]["signature"]
    )
    plastic = at.session_state[PLASTIC].copy(deep=True)
    plastic[load_cases.LOCATION_TAG] = "Pier 3"
    plastic[load_cases.DESIGN_SITUATION] = "transient"
    at.session_state[PLASTIC] = plastic
    at.session_state[f"_{PLASTIC}_editor_seed"] = plastic.copy(deep=True)
    at.run()
    assert not at.exception
    assert set(at.session_state[PLASTIC][load_cases.LOCATION_TAG]) == {"Pier 3"}
    assert project_io.result_sha256(
        at.session_state["_latest_inputs"]["signature"]
    ) == signature


def test_load_numbers_a_row_without_id_from_the_region_counters():
    """D1-R2-01: a load issues the same IDs as a save and no deleted number."""

    payload = _payload()
    region = payload["scalars"][section_ids.REGIONS_KEY]["items"][0]
    # C4 and V6 were issued and deleted before this save.
    region["next_corner"] = 5
    region["next_void_corner"] = 7
    corners = payload["tables"]["corners_base"]
    corners["rows"][3][0] = ""
    corners["rows"][2][0] = "C1"          # duplicate of the first row
    holes = payload["tables"]["hole_base"]
    holes["rows"] = [
        ["V1", -50.0, -50.0], ["V2", 50.0, -50.0], ["V3", 50.0, 50.0],
        ["", 0.0, 60.0], ["V5", -50.0, 50.0],
    ]
    tables, scalars = project_io.parse_project(_rehash(payload))
    assert tables["corners_base"]["ID"].tolist() == ["C1", "C2", "C5", "C6"]
    assert tables["hole_base"]["ID"].tolist() == ["V1", "V2", "V3", "V7", "V5"]
    saved = json.loads(project_io.dump_project(tables, scalars))
    assert [row[0] for row in saved["tables"]["corners_base"]["rows"]] == [
        "C1", "C2", "C5", "C6",
    ]
    region = saved["scalars"][section_ids.REGIONS_KEY]["items"][0]
    assert (region["next_corner"], region["next_void_corner"]) == (7, 8)


def test_app_protects_a_material_that_only_a_bar_group_uses(_isolated_autosave):
    """D1-R1-05 and D1-R2-03: Delete is off, with a true help text."""

    from app_workflow_navigation import goto_material
    from streamlit.testing.v1 import AppTest

    import material_catalog

    tables, scalars = _reference()
    catalogue = material_catalog.default_catalog("mild")
    second = dict(catalogue["items"][0], id="M2", name="Group steel")
    catalogue = {**catalogue, "next_id": 3, "items": [*catalogue["items"], second]}
    scalars[material_catalog.MILD_CATALOG_KEY] = catalogue
    scalars[rebar.GROUPS_KEY] = _group(material_id="M2")
    app = str(ROOT / "app" / "sector_app.py")
    at = AppTest.from_file(app, default_timeout=180).run()
    _upload(at, project_io.dump_project(tables, scalars))
    goto_material(at, "Mild steel")
    at.session_state["_mild_catalog_selected"] = "M2"
    at.run()
    assert not at.exception
    delete = at.button(key="mild_catalog_delete")
    assert delete.disabled is True
    assert delete.help == "A bar group in the project uses this material."
