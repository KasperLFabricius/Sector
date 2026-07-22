from __future__ import annotations

import math
import pathlib
import sys

import pandas as pd
import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import reinforcement_table as rt  # noqa: E402


def test_legacy_rows_get_deterministic_stable_ids_and_defaults():
    frame = rt.normalise_table(pd.DataFrame({
        "x (mm)": [0.0, 50.0],
        "y (mm)": [-100.0, -100.0],
        "area (mm2)": [math.pi * 100.0, math.pi * 64.0],
    }), "bar")

    assert frame[rt.ELEMENT_ID].tolist() == ["R1", "R2"]
    assert frame[rt.SIZE_MODE].tolist() == [rt.AREA_MODE, rt.AREA_MODE]
    assert frame[rt.MATERIAL_ID].tolist() == ["M1", "M1"]
    assert frame[rt.DIAMETER].tolist() == pytest.approx([20.0, 16.0])


def test_ids_do_not_renumber_after_delete_and_new_row_uses_next_suffix():
    original = rt.normalise_table([
        {rt.ELEMENT_ID: "R1", rt.X: 0.0, rt.Y: 0.0, rt.AREA: 100.0},
        {rt.ELEMENT_ID: "R2", rt.X: 1.0, rt.Y: 0.0, rt.AREA: 100.0},
        {rt.ELEMENT_ID: "R3", rt.X: 2.0, rt.Y: 0.0, rt.AREA: 100.0},
    ], "bar")

    deleted = original.iloc[[0, 2]].reset_index(drop=True)
    retained = rt.normalise_table(deleted, "bar")
    added = pd.concat([
        retained,
        pd.DataFrame([{rt.X: 3.0, rt.Y: 0.0, rt.AREA: 100.0}]),
    ], ignore_index=True)
    final = rt.normalise_table(added, "bar")

    assert retained[rt.ELEMENT_ID].tolist() == ["R1", "R3"]
    assert final[rt.ELEMENT_ID].tolist() == ["R1", "R3", "R4"]


def test_area_diameter_and_independent_modes_resolve_as_declared():
    frame = rt.normalise_table([
        {rt.SIZE_MODE: rt.AREA_MODE, rt.AREA: math.pi * 100.0},
        {rt.SIZE_MODE: rt.DIAMETER_MODE, rt.DIAMETER: 16.0},
        {rt.SIZE_MODE: rt.INDEPENDENT_MODE, rt.AREA: 500.0, rt.DIAMETER: 25.0},
    ], "bar")

    assert frame.iloc[0][rt.DIAMETER] == pytest.approx(20.0)
    assert frame.iloc[1][rt.AREA] == pytest.approx(math.pi * 16.0**2 / 4.0)
    assert frame.iloc[2][rt.AREA] == 500.0
    assert frame.iloc[2][rt.DIAMETER] == 25.0


def test_table_from_points_can_make_diameter_authoritative_rows():
    frame = rt.table_from_points(
        [(0.0, -100.0, math.pi * 100.0)],
        "bar",
        size_mode=rt.DIAMETER_MODE,
    )

    assert frame.iloc[0][rt.SIZE_MODE] == rt.DIAMETER_MODE
    assert frame.iloc[0][rt.DIAMETER] == pytest.approx(20.0)
    assert frame.iloc[0][rt.AREA] == pytest.approx(math.pi * 100.0)


def test_tendon_defaults_and_valid_elements_keep_assignment_metadata():
    frame = rt.normalise_table([{
        rt.X: 10.0, rt.Y: -20.0, rt.AREA: 150.0,
        rt.FATIGUE_DETAIL_ID: "PF1", rt.GROUP_ID: "CABLE-A",
    }], "tendon")

    elements = rt.valid_elements(frame, "tendon")

    assert frame.iloc[0][rt.ELEMENT_ID] == "P1"
    assert frame.iloc[0][rt.MATERIAL_ID] == "P1"
    assert elements[0]["fatigue_detail_id"] == "PF1"
    assert elements[0]["group_id"] == "CABLE-A"


def test_incomplete_or_nonpositive_size_rows_are_not_solver_elements():
    frame = rt.normalise_table([
        {rt.X: 0.0, rt.Y: 0.0, rt.AREA: 100.0},
        {rt.X: 10.0, rt.Y: None, rt.AREA: 100.0},
        {rt.X: 20.0, rt.Y: 0.0, rt.AREA: -1.0},
    ], "bar")

    assert [item["id"] for item in rt.valid_elements(frame, "bar")] == ["R1"]
    assert [element_id for element_id, _ in rt.row_issues(frame, "bar")] == [
        "R2", "R3"
    ]


def test_grid_metadata_marks_id_immutable_and_size_fields_as_derived_pair():
    specs = {spec["field"]: spec for spec in rt.point_grid_specs("bar")}
    options = rt.point_grid_options("bar")

    assert specs[rt.ELEMENT_ID]["editable"] is False
    assert specs[rt.ELEMENT_ID]["paste"] is False
    assert specs[rt.AREA]["derived_role"] == "area"
    assert specs[rt.DIAMETER]["derived_role"] == "diameter"
    assert options["id_column"] == rt.ELEMENT_ID
    assert options["id_prefix"] == "R"
    assert options["compact_paste_fields"] == [rt.X, rt.Y, rt.AREA]
    assert options["default_values"][rt.MATERIAL_ID] == "M1"


def test_grid_material_assignment_is_limited_to_catalogue_ids():
    specs = {
        spec["field"]: spec
        for spec in rt.point_grid_specs("bar", ["M1", "M4"])
    }
    options = rt.point_grid_options("bar", ["M1", "M4"])

    assert specs[rt.MATERIAL_ID]["type"] == "select"
    assert specs[rt.MATERIAL_ID]["options"] == ["M1", "M4"]
    assert options["default_values"][rt.MATERIAL_ID] == "M1"
