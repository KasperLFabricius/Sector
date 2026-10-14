"""Generated reinforcement starts with the canonical table dtype contract."""
import ast
from pathlib import Path
from types import CodeType, FunctionType
import pandas as pd
import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import reinforcement_table as rebar_table


def build_frame(*args, **kwargs):
    source = Path(__file__).resolve().parents[1] / "app" / "sector_app.py"
    node = next(node for node in ast.parse(source.read_text(encoding="utf-8")).body
                if isinstance(node, ast.FunctionDef) and node.name == "_rebar_df")
    scope = {"pd": pd, "rebar_table": rebar_table}
    compiled = compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec")
    code = next(value for value in compiled.co_consts if isinstance(value, CodeType))
    function = FunctionType(code, scope, argdefs=("bar",))
    function.__kwdefaults__ = {"size_mode": rebar_table.AREA_MODE,
                              "material_id": None, "diameters_mm": None}
    return function(*args, **kwargs)


@pytest.mark.parametrize("kind", ["bar", "tendon"])
@pytest.mark.parametrize("material_id", [None, "M1", "001", 7])
@pytest.mark.parametrize("independent", [False, True])
def test_material_ids_are_canonical_before_first_section_mount(kind, material_id, independent):
    points = [(0.1, 0.2, 123.45678901234567), (0.2, 0.3, 200.1)]
    kwargs = {"kind": kind, "material_id": material_id}
    if independent:
        kwargs["diameters_mm"] = [16.0, 20.0]
    frame = build_frame(points, **kwargs)
    pd.testing.assert_frame_equal(frame, rebar_table.normalise_table(frame, kind))
    if material_id is not None:
        assert frame[rebar_table.MATERIAL_ID].tolist() == [str(material_id)] * 2
        assert str(frame[rebar_table.MATERIAL_ID].dtype) == "object"
    assert frame[rebar_table.AREA].tolist() == [point[2] for point in points]


def test_empty_generated_table_remains_canonical():
    frame = build_frame([], kind="bar", material_id="M1")
    pd.testing.assert_frame_equal(frame, rebar_table.normalise_table(frame, "bar"))
