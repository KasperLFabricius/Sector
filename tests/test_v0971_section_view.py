"""Sector 0.97.1 PR I1: section view, stable corner IDs and live properties.

The expected section properties come from an independent hand calculation
(rectangle formulas and the parallel-axis theorem), never from Sector output.
The ID tests follow plan decisions 6, 28 and 29: the corner and void grids keep
each ID through an edit, an insertion, a deletion and a reorder, a deleted
number is not issued again, and a reference stores its ID family.
"""

from __future__ import annotations

import copy
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys

import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "app"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import point_grid as point_grid_module  # noqa: E402
import project_io  # noqa: E402

from app import reproducible_example, section_drawing, section_ids  # noqa: E402
from app import reinforcement_table as rebar  # noqa: E402
from sector import geometry  # noqa: E402

GEOMETRY_COLUMNS = ["ID", "x (mm)", "y (mm)"]


# --- UI-18: live section properties from a list of parts -------------------


def _rectangle(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def test_section_properties_of_a_rectangle_with_an_offset_void_match_the_hand_calculation():
    # Hand calculation, mm. Outer 400 x 600 centred at O: A1 = 240 000,
    # I_x1 = 400 * 600^3 / 12 = 7.2e9, I_y1 = 600 * 400^3 / 12 = 3.2e9.
    # Void 100 x 200 centred at (50, 100): A2 = 20 000,
    # I_x2 = 100 * 200^3 / 12, I_y2 = 200 * 100^3 / 12.
    # Net A = 220 000. x_c = -50 * 20 000 / 220 000, y_c = -100 * 20 000 / 220 000.
    # Parallel axes for a solid less a void: I = I1 - I2 - (A1 A2 / A) d^2,
    # and I_xy = -(A1 A2 / A) dx dy, with dx = 50 and dy = 100.
    a1, a2 = 240_000.0, 20_000.0
    area = a1 - a2
    k = a1 * a2 / area
    expected_ix = 400.0 * 600.0**3 / 12.0 - 100.0 * 200.0**3 / 12.0 - k * 100.0**2
    expected_iy = 600.0 * 400.0**3 / 12.0 - 200.0 * 100.0**3 / 12.0 - k * 50.0**2
    expected_ixy = -k * 50.0 * 100.0
    assert expected_ix == pytest.approx(6_915_151_515.15, rel=1e-11)
    assert expected_iy == pytest.approx(3_128_787_878.79, rel=1e-11)

    properties = geometry.section_properties([
        geometry.SectionPart(
            _rectangle(-200.0, -300.0, 200.0, 300.0),
            (_rectangle(0.0, 0.0, 100.0, 200.0),),
        )
    ])
    assert properties.area == pytest.approx(area, rel=1e-12)
    assert properties.centroid[0] == pytest.approx(-50.0 * a2 / area, rel=1e-12)
    assert properties.centroid[1] == pytest.approx(-100.0 * a2 / area, rel=1e-12)
    assert properties.i_x == pytest.approx(expected_ix, rel=1e-12)
    assert properties.i_y == pytest.approx(expected_iy, rel=1e-12)
    assert properties.i_xy == pytest.approx(expected_ixy, rel=1e-12)
    assert properties.part_areas == pytest.approx((area,))


def test_section_properties_orient_the_rings_and_weight_each_part():
    # The same section with a clockwise outer ring and a counter-clockwise void.
    outer = list(reversed(_rectangle(-200.0, -300.0, 200.0, 300.0)))
    void = _rectangle(0.0, 0.0, 100.0, 200.0)
    reference = geometry.section_properties(
        [geometry.SectionPart(_rectangle(-200.0, -300.0, 200.0, 300.0), (void,))]
    )
    reversed_rings = geometry.section_properties(
        [geometry.SectionPart(outer, (list(reversed(void)),))]
    )
    assert reversed_rings == reference
    # Two parts: 100 x 100 at (0..100, 0..100) with ratio 1 and the same square at
    # (100..200, 0..100) with ratio 3. Hand calculation: A = 1e4 + 3e4 = 4e4,
    # x_c = (1e4 * 50 + 3e4 * 150) / 4e4 = 125, y_c = 50,
    # I_y = 4 * 100^4 / 12 + 1e4 * 75^2 + 3e4 * 25^2.
    parts = [
        geometry.SectionPart(_rectangle(0.0, 0.0, 100.0, 100.0)),
        geometry.SectionPart(_rectangle(100.0, 0.0, 200.0, 100.0), (), 3.0),
    ]
    properties = geometry.section_properties(parts)
    assert properties.area == pytest.approx(40_000.0)
    assert properties.centroid == pytest.approx((125.0, 50.0))
    assert properties.i_x == pytest.approx(4.0 * 100.0**4 / 12.0)
    assert properties.i_y == pytest.approx(
        4.0 * 100.0**4 / 12.0 + 1e4 * 75.0**2 + 3e4 * 25.0**2
    )
    assert properties.i_xy == pytest.approx(0.0, abs=1e-3)
    assert properties.part_areas == pytest.approx((10_000.0, 10_000.0))


@pytest.mark.parametrize(
    "parts",
    [
        [],
        [geometry.SectionPart(_rectangle(0, 0, 1, 1), (), 0.0)],
        [geometry.SectionPart(_rectangle(0, 0, 1, 1), (), math.nan)],
        [geometry.SectionPart([(0, 0), (1, 1), (2, 2)])],
        [geometry.SectionPart(_rectangle(0, 0, 1, 1), (_rectangle(0, 0, 1, 1),))],
    ],
)
def test_section_properties_reject_parts_without_a_positive_area(parts):
    with pytest.raises(ValueError):
        geometry.section_properties(parts)


# --- Decision 29: ring split and ID families ------------------------------


def _void_table(rows):
    return pd.DataFrame(rows, columns=GEOMETRY_COLUMNS)


def test_void_table_splits_into_rings_at_the_separator_rows_only():
    table = _void_table([
        ["V1", -30.0, -80.0],
        ["V2", 30.0, -80.0],
        ["V3", 30.0, math.nan],      # incomplete: not a corner, not a separator
        ["V4", -30.0, -20.0],
        ["", math.nan, math.nan],    # separator
        ["V5", -30.0, 20.0],
        ["V6", 30.0, 20.0],
        ["V7", 30.0, 80.0],
        ["", math.nan, math.nan],    # trailing separator: an empty void slot
    ])
    rings = section_ids.ring_corner_ids(table, section_ids.VOIDS_TABLE_KEY)
    assert rings == [["V1", "V2", "V4"], ["V5", "V6", "V7"]]
    assert section_ids.incomplete_row_ids(table, section_ids.VOIDS_TABLE_KEY) == [
        "V3"
    ]
    # The edges come from each ring, never from one false ring over all voids.
    assert [section_ids.ring_edge_ids(ring) for ring in rings] == [
        ["V1-V2", "V2-V4", "V4-V1"],
        ["V5-V6", "V6-V7", "V7-V5"],
    ]
    rows = section_ids.ring_rows(table, section_ids.VOIDS_TABLE_KEY)
    assert rows[1][0] == {"id": "V5", "x": -30.0, "y": 20.0}
    # In the corner table a blank row is an incomplete row, not a separator.
    corners = _void_table([
        ["C1", 0.0, 0.0], ["C2", math.nan, math.nan], ["C3", 1.0, 0.0],
        ["C4", 1.0, 1.0],
    ])
    assert section_ids.ring_corner_ids(corners, "corners_base") == [
        ["C1", "C3", "C4"]
    ]
    assert section_ids.incomplete_row_ids(corners, "corners_base") == ["C2"]


def test_a_reference_stores_its_id_family():
    # The region A1 and the bar R1 differ, and each family checks its ID form.
    assert section_ids.element_reference("region", "A1") == {
        "family": "region", "id": "A1",
    }
    assert section_ids.element_reference("bar", "R1") == {"family": "bar", "id": "R1"}
    assert section_ids.element_reference("edge", "C3-C4")["family"] == "edge"
    assert section_ids.element_reference("void edge", "V2-V3")["id"] == "V2-V3"
    for family, element_id in (
        ("bar", "A1"),
        ("corner", "V1"),
        ("void corner", "C1"),
        ("tendon", "R1"),
        ("group", "R1"),
        ("edge", "V1-V2"),
        ("void edge", "C1-C2"),
        ("edge", "C1"),
        ("unknown", "C1"),
        ("corner", 3),
    ):
        with pytest.raises(ValueError):
            section_ids.element_reference(family, element_id)
    # The bar, tendon and group prefixes agree with the reinforcement table.
    assert section_ids.element_reference("tendon", rebar.id_prefix("tendon") + "2")
    assert section_ids.element_reference("group", rebar.GROUP_ID_PREFIX + "2")


# --- Section view figure ----------------------------------------------------


def _meta_references(figure):
    out = []
    for trace in figure.data:
        meta = trace.meta if isinstance(trace.meta, dict) else {}
        out.extend(
            tuple(item) for item in meta.get(section_drawing.SELECT_META, [])
        )
    return out


def test_section_view_marks_ids_edges_selection_origin_and_centroid():
    outer = _rectangle(-0.1, -0.15, 0.1, 0.15)
    holes = [_rectangle(-0.03, -0.08, 0.03, -0.02)]
    figure = section_drawing.section_figure(
        outer,
        holes,
        [(-0.06, -0.12, 314.0)],
        tendons=[(0.0, 0.1, 150.0)],
        show_labels=True,
        scale=1000.0,
        unit="mm",
        bar_ids=["R1"],
        tendon_ids=["P1"],
        outer_ids=["C1", "C3", "C4", "C9"],
        hole_ids=[["V1", "V2", "V3", "V4"]],
        selectable=True,
        selection={"family": "edge", "id": "C9-C1"},
        show_origin=True,
        centroid=(0.0, 0.01),
    )
    references = _meta_references(figure)
    assert ("corner", "C9") in references
    assert ("void corner", "V4") in references
    assert ("edge", "C4-C9") in references and ("edge", "C9-C1") in references
    assert ("void edge", "V4-V1") in references
    assert ("bar", "R1") in references and ("tendon", "P1") in references
    names = [trace.name for trace in figure.data]
    assert "selected edge C9-C1" in names
    assert "origin O (moment reference)" in names
    assert "gross centroid" in names
    labels = [
        text for trace in figure.data if trace.mode == "text"
        for text in (trace.text or ())
    ]
    assert {"C1", "C9", "V1"} <= set(labels)
    # Each element family draws its selection mark.
    for selection, name in (
        ({"family": "corner", "id": "C4"}, "selected corner C4"),
        ({"family": "void corner", "id": "V2"}, "selected void corner V2"),
        ({"family": "void edge", "id": "V2-V3"}, "selected edge V2-V3"),
        ({"family": "bar", "id": "R1"}, "selected bar R1"),
        ({"family": "tendon", "id": "P1"}, "selected tendon P1"),
    ):
        marked = section_drawing.section_figure(
            outer, holes, [(-0.06, -0.12, 314.0)], tendons=[(0.0, 0.1, 150.0)],
            bar_ids=["R1"], tendon_ids=["P1"], outer_ids=["C1", "C3", "C4", "C9"],
            hole_ids=[["V1", "V2", "V3", "V4"]], selection=selection,
        )
        assert name in [trace.name for trace in marked.data]
    # A click maps to its reference through the trace metadata; a label or the
    # origin mark selects nothing.
    curves = {
        trace.name: number for number, trace in enumerate(figure.data)
        if trace.name
    }
    edge_curve = next(
        number for number, trace in enumerate(figure.data)
        if isinstance(trace.meta, dict)
        and ["edge", "C1-C3"] in trace.meta.get(section_drawing.SELECT_META, [])
    )
    assert section_drawing.selected_reference(
        figure, [{"curve_number": edge_curve, "point_index": 0}]
    ) == ("edge", "C1-C3")
    assert section_drawing.selected_reference(
        figure, [{"curve_number": curves["reinforcing bar"], "point_index": 0}]
    ) == ("bar", "R1")
    assert section_drawing.selected_reference(
        figure,
        [{"curve_number": curves["origin O (moment reference)"],
          "point_index": 0}],
    ) is None
    assert section_drawing.selected_reference(figure, [{"x": 1}]) is None
    # O far outside the section is named in the legend only (I1-R1-N05).
    far = section_drawing.section_figure(
        _rectangle(10.0, 10.0, 10.2, 10.3), show_origin=True,
    )
    names = [trace.name for trace in far.data]
    assert "origin O (moment reference) outside the view" in names
    # A result figure without IDs keeps the ring-order numbers and no targets.
    plain = section_drawing.section_figure(outer, holes, show_labels=True)
    assert _meta_references(plain) == []
    assert "1" in [t for tr in plain.data if tr.mode == "text" for t in tr.text]


# --- Grid payload contract ---------------------------------------------------


def test_grid_reports_its_counter_and_id_clicks_for_the_current_seed_only():
    payload = {"payload": {"data_version": "4", "rows": [], "next_id": 14}}
    assert point_grid_module.reported_next_id(payload, 4) == 14
    assert point_grid_module.reported_next_id(payload, 5) is None
    assert point_grid_module.reported_next_id({"payload": {"data_version": "4",
                                                           "next_id": 0}}, 4) is None
    event = {"selection": {"data_version": "4", "id": "C3", "token": "7"}}
    assert point_grid_module.selection_event(event, 4) == ("C3", "7")
    assert point_grid_module.selection_event(event, 3) is None
    assert point_grid_module.selection_event({"selection": None}, 4) is None


def test_grid_frontend_decimal_comma_error_cells_and_id_counter(tmp_path):
    """Run the pure grid rules of point_grid.js in Node.js (UI-02, decision 28)."""

    node = shutil.which("node")
    assert node, "Node.js is required for the point grid frontend test"
    source = (
        pathlib.Path(point_grid_module.__file__).resolve().parent
        / "point_grid_frontend" / "point_grid.js"
    ).read_text(encoding="utf-8")
    (tmp_path / "grid.mjs").write_text(
        source + "\nexport { createPointGridInstance }\n", encoding="utf-8"
    )
    (tmp_path / "driver.mjs").write_text(
        """
import { createPointGridInstance } from "./grid.mjs"
const element = () => ({
  addEventListener() {}, removeEventListener() {}, setAttribute() {},
  hidden: true, textContent: "",
})
const parts = {
  ".pg-wrap": element(), ".pg-grid": element(),
  ".pg-add-row": element(), ".pg-warning": element(),
}
const parent = { querySelector: s => parts[s], getRootNode: () => ({}) }
const state = createPointGridInstance(parent)
state.configure({
  columns: ["ID", "x (mm)", "y (mm)"],
  column_specs: [
    { field: "ID", type: "id" },
    { field: "x (mm)", type: "number" },
    { field: "y (mm)", type: "number" },
  ],
  id_column: "ID", id_prefix: "V", id_next: 9, separator_rows: true,
  data_version: "1",
})
const number = { type: "number" }
const paste = [
  "12,5", "-3,25", "1.5", "0,125", "1,200", "-12,000", "1,2000",
  "1,234,5", "1,5.0", "abc", "",
].map(value => state.pasteValue(value, number))
const rows = [
  { ID: "V1", "x (mm)": 1, "y (mm)": 1 },
  { ID: "", "x (mm)": 2, "y (mm)": 2 },
  { ID: "V3", "x (mm)": null, "y (mm)": null },
  { ID: "V1", "x (mm)": 3, "y (mm)": 3 },
  { ID: "", "x (mm)": 4, "y (mm)": null },
  { ID: "V5", "x (mm)": "x (mm)", "y (mm)": "y (mm)" },
  { ID: "", "x (mm)": "abc", "y (mm)": 0 },
]
state.applyIds(rows)
const blank = state.blankRow()
globalThis.document = { createElement: tag => ({ tag, textContent: "" }) }
const cellElement = {
  classList: { toggle() {} }, setAttribute() {}, removeAttribute() {},
}
const markup = "<img src=x onerror=alert(1)>"
const formatted = state.formatNumber({
  getValue: () => markup, getElement: () => cellElement,
})
console.log(JSON.stringify({
  paste, ids: rows.map(row => row.ID), next: state.nextId,
  coerced: state.coerceValue("abc", number), blank: blank.ID,
  text: rows.map(row => state.hasTextCell(row)),
  formatted: { type: typeof formatted, tag: formatted.tag, text: formatted.textContent },
}))
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(tmp_path / "driver.mjs")],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    out = json.loads(completed.stdout)
    # One comma and no dot is a decimal comma. A comma that can be a thousands
    # separator (1,200 and -12,000) is not read; other text stays as an error
    # cell (I1-R1-03).
    assert out["paste"] == [
        12.5, -3.25, 1.5, 0.125, "1,200", "-12,000", 1.2,
        "1,234,5", "1,5.0", "abc", None,
    ]
    # The emitted value of an error cell is blank, so the row is incomplete.
    assert out["coerced"] is None
    # Valid IDs stay, a duplicate or a missing ID gets the next counter number
    # (9 from the region, not 4 above the largest ID), a separator has no ID.
    # A row with text but no number is a separator in the browser and in Python
    # (I1-R1-04); the payload names it in text_rows.
    assert out["ids"] == ["V1", "V9", "", "V10", "V11", "", "V12"]
    assert out["text"] == [False, False, False, False, False, True, True]
    assert out["next"] == 13
    # A new void row starts blank, so it is a separator until it has a value.
    assert out["blank"] == ""
    # An error cell is a text node, never HTML from the clipboard (Codex P2).
    assert out["formatted"] == {
        "type": "object", "tag": "span", "text": "<img src=x onerror=alert(1)>",
    }


# --- Decision 28 and the section view in the application ------------------


@pytest.fixture(scope="module")
def _isolated_autosave(tmp_path_factory):
    key = "SECTOR_AUTOSAVE_DIR"
    previous = os.environ.get(key)
    os.environ[key] = str(tmp_path_factory.mktemp("v0971-section-view-autosave"))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _geometry(rows):
    return pd.DataFrame(rows, columns=GEOMETRY_COLUMNS)


def _project(corners, voids, *, next_corner, next_void_corner, shift=(0.0, 0.0),
             axial=None):
    tables = reproducible_example.project_tables()
    scalars = copy.deepcopy(reproducible_example.project_scalars())
    if axial is not None:
        cases = tables["plastic_cases_base"].copy()
        cases["n_ed_kn"] = axial
        tables["plastic_cases_base"] = cases
    tables["corners_base"] = _geometry(corners)
    tables["hole_base"] = _geometry(voids)
    if shift != (0.0, 0.0):
        bars = tables["bars_base"].copy()
        bars["x (mm)"] = bars["x (mm)"] + shift[0]
        bars["y (mm)"] = bars["y (mm)"] + shift[1]
        tables["bars_base"] = bars
    region = scalars[section_ids.REGIONS_KEY]["items"][0]
    region["next_corner"] = next_corner
    region["next_void_corner"] = next_void_corner
    return project_io.dump_project(tables, scalars)


def _app():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(
        str(ROOT / "app" / "sector_app.py"), default_timeout=180
    ).run()


def _upload(at, text: str):
    from app_workflow_navigation import goto_input_stage

    goto_input_stage(at, "Project")
    at.file_uploader[0].set_value(
        ("i1.json", text.encode("utf-8"), "application/json")
    ).run()
    assert not at.exception
    assert any("Project loaded" in str(item.value) for item in at.success)
    return at


def _submit(at, editor, rows, *, next_id=None, text_rows=None):
    """Submit one grid report as the browser sends it.

    The report carries the seed version that the grid last rendered with, as
    in the browser, not the version that Python stores.
    """

    from app_workflow_navigation import goto_input_stage

    goto_input_stage(at, "Section")
    try:
        version = at.session_state[editor]["payload"]["data_version"]
    except (KeyError, TypeError):
        version = str(at.session_state[editor + "_ver"])
    payload = {"data_version": str(version), "rows": copy.deepcopy(rows)}
    if next_id is not None:
        payload["next_id"] = next_id
    if text_rows is not None:
        payload["text_rows"] = text_rows
    at.session_state[editor] = {"payload": payload, "selection": None}
    at.run()
    assert not at.exception
    return at


def _app_save(at) -> dict:
    """Serialise the session as the project download does (`_project_state`)."""

    input_durable = dict(at.session_state["_durable_input_scalars"])
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
    return json.loads(project_io.dump_project(tables, scalars))


def _ids(saved, key):
    return [row[0] for row in saved["tables"][key]["rows"]]


def _row(element_id, x, y):
    return {"ID": element_id, "x (mm)": x, "y (mm)": y}


_CORNERS = [
    ["C1", -100.0, -150.0], ["C3", 100.0, -150.0],
    ["C4", 100.0, 150.0], ["C9", -100.0, 150.0],
]
_VOIDS = [
    ["V1", -30.0, -80.0], ["V2", 30.0, -80.0], ["V3", 30.0, -20.0],
    ["V4", -30.0, -20.0], ["", math.nan, math.nan],
    ["V5", -30.0, 20.0], ["V6", 30.0, 20.0], ["V7", 30.0, 80.0],
    ["V8", -30.0, 80.0],
]


def test_app_load_edit_save_keeps_each_corner_and_void_id(_isolated_autosave):
    at = _upload(_app(), _project(
        _CORNERS, _VOIDS, next_corner=12, next_void_corner=9,
    ))
    # The live grids show the stored IDs (no renumbering at load).
    assert list(at.session_state["corners_base"].columns) == GEOMETRY_COLUMNS
    # The centroid is at O, so the moment reference line does not show.
    assert not any("from O" in str(item.value) for item in at.info)
    assert at.session_state["corners_base"]["ID"].tolist() == [
        "C1", "C3", "C4", "C9",
    ]
    # Browser edit of the corners: C3 deleted in the middle, a new row (the
    # browser issues C12 from the region counter) inserted after C1, and C9
    # moved to the top.
    _submit(at, "ed_corners", [
        _row("C9", -100.0, 150.0), _row("C1", -100.0, -150.0),
        _row("C12", 100.0, -150.0), _row("C4", 100.0, 150.0),
    ], next_id=13)
    # Browser edit of the voids: V2 deleted and V9 inserted in void 1, void 2
    # reordered.
    _submit(at, "ed_hole", [
        _row("V1", -30.0, -80.0), _row("V9", 30.0, -80.0),
        _row("V3", 30.0, -20.0), _row("V4", -30.0, -20.0),
        _row("", None, None),
        _row("V8", -30.0, 80.0), _row("V5", -30.0, 20.0),
        _row("V6", 30.0, 20.0), _row("V7", 30.0, 80.0),
    ], next_id=10)
    # C13 was added and deleted in the browser between two reports.
    _submit(at, "ed_corners", [
        _row("C9", -100.0, 150.0), _row("C1", -100.0, -150.0),
        _row("C12", 100.0, -150.0), _row("C4", 100.0, 150.0),
    ], next_id=14)
    saved = _app_save(at)
    assert _ids(saved, "corners_base") == ["C9", "C1", "C12", "C4"]
    assert _ids(saved, "hole_base") == [
        "V1", "V9", "V3", "V4", "", "V8", "V5", "V6", "V7",
    ]
    region = saved["scalars"][section_ids.REGIONS_KEY]["items"][0]
    assert region["next_corner"] == 14
    assert region["next_void_corner"] == 10
    # The edge selection splits the voids at the separator row (decision 29).
    tables, _scalars = project_io.parse_project(json.dumps(saved))
    assert section_ids.ring_corner_ids(tables["hole_base"], "hole_base") == [
        ["V1", "V9", "V3", "V4"], ["V8", "V5", "V6", "V7"],
    ]
    # A second load and save keeps every ID and both counters.
    _upload(at, json.dumps(saved))
    again = _app_save(at)
    assert _ids(again, "corners_base") == ["C9", "C1", "C12", "C4"]
    assert _ids(again, "hole_base") == _ids(saved, "hole_base")
    assert again["scalars"][section_ids.REGIONS_KEY] == saved["scalars"][
        section_ids.REGIONS_KEY
    ]
    # C12, the highest number, is deleted and a row without an ID is added: it
    # gets C14, so neither C12 nor the browser-only C13 is issued again.
    _submit(at, "ed_corners", [
        _row("C9", -100.0, 150.0), _row("C1", -100.0, -150.0),
        _row("", 100.0, -150.0), _row("C4", 100.0, 150.0),
    ])
    assert _ids(_app_save(at), "corners_base") == ["C9", "C1", "C14", "C4"]
    # The Remove void and Add void commands keep the IDs of the other rows.
    at.button(key="rem_void").click().run()
    assert at.session_state["hole_base"]["ID"].tolist() == ["V1", "V9", "V3", "V4"]
    at.button(key="add_void").click().run()
    assert at.session_state["hole_base"]["ID"].tolist() == [
        "V1", "V9", "V3", "V4", "",
    ]
    void_rows = [
        _row("V1", -30.0, -80.0), _row("V9", 30.0, -80.0),
        _row("V3", 30.0, -20.0), _row("V4", -30.0, -20.0),
    ]
    # I1-R1-01 probe: a report where Python clears an ID (a row with the ID
    # V20 and no number, as an older grid sent a pasted text-only row). The grid
    # re-seeds before it renders, so the next browser report, with the version
    # that the grid rendered with, keeps its edit of V1.
    _submit(at, "ed_hole", void_rows + [_row("V20", None, None)])
    assert at.session_state["hole_base"]["ID"].tolist() == [
        "V1", "V9", "V3", "V4", "",
    ]
    edited = copy.deepcopy(void_rows)
    edited[0]["x (mm)"] = -40.0
    _submit(at, "ed_hole", edited)
    assert at.session_state["hole_base"]["x (mm)"].iloc[0] == -40.0
    # I1-R1-04 and -05: a text-only row (reported in text_rows) and a row with
    # one blank coordinate are named under the grid and block the calculation;
    # neither joins two voids.
    _submit(at, "ed_hole", [
        void_rows[0], void_rows[1], _row("", None, None),
        void_rows[2], _row("V4", None, -20.0),
    ], text_rows=[2])
    warnings = [str(item.value) for item in at.warning]
    assert any(
        "Incomplete rows: V4, void table row 3." in text for text in warnings
    ), warnings
    error = at.session_state["_latest_inputs"]["geometry_error"]
    assert error is not None and "V4, void table row 3" in error.text
    # The corrected rows calculate again.
    _submit(at, "ed_hole", void_rows)
    assert at.session_state["_latest_inputs"]["geometry_error"] is None


def test_section_view_properties_selection_and_origin_move(_isolated_autosave):
    # Reference section moved by (+100, +150) mm with an offset void.
    # Hand calculation: A1 = 200 * 300 = 60 000 at (100, 150), void
    # 40 x 100 = 4 000 at (40, 150). A = 56 000 mm2,
    # x_c = (60 000 * 100 - 4 000 * 40) / 56 000 = 104.2857 mm, y_c = 150 mm,
    # I_x = 200 * 300^3 / 12 - 40 * 100^3 / 12 = 4.467e8 mm4,
    # I_y = 300 * 200^3 / 12 - 100 * 40^3 / 12 - (60 000 * 4 000 / 56 000) * 60^2
    #     = 1.840e8 mm4.
    corners = [["C1", 0.0, 0.0], ["C2", 200.0, 0.0], ["C3", 200.0, 300.0],
               ["C4", 0.0, 300.0]]
    voids = [["V1", 20.0, 100.0], ["V2", 60.0, 100.0], ["V3", 60.0, 200.0],
             ["V4", 20.0, 200.0]]
    at = _upload(_app(), _project(
        corners, voids, next_corner=5, next_void_corner=5, shift=(100.0, 150.0),
        axial=-500.0,
    ))
    from app_workflow_navigation import goto_input_stage

    goto_input_stage(at, "Section")
    table = next(
        str(item.value) for item in at.markdown
        if "Area $A_c$" in str(item.value)
    )
    assert "| Area $A_c$ | 56 000 mm$^2$ |" in table
    assert "Reinforcement ratio $A_s / A_c$ (all bars)" in table
    assert "rho" not in table
    assert "(104.3, 150.0) mm" in table
    assert "$4.467 \\times 10^{8}$ mm$^4$" in table
    assert "$1.840 \\times 10^{8}$ mm$^4$" in table
    # A case has N not 0, and the centroid is far from O, so the moment
    # reference line shows.
    assert any("from O" in str(item.value) for item in at.info)
    # A selection with its family marks the element in the view.
    at.session_state["_section_selection"] = {"family": "void edge", "id": "V2-V3"}
    at.run()
    assert any(
        "Selected: void edge V2-V3" in str(item.value) for item in at.caption
    )
    figure = at.session_state["_fig_cache"]["section"][1]
    assert "selected edge V2-V3" in [trace.name for trace in figure.data]
    # The view stays beside the Materials and Actions inputs.
    for stage in ("Material parameters", "Loads"):
        goto_input_stage(at, stage)
        assert not at.exception
        assert "section_compact" in at.session_state["_fig_cache"]
    goto_input_stage(at, "Section")
    cases_before = at.session_state["plastic_cases_base"].copy(deep=True)
    # Two torsion sub-rectangles (centre x, centre y, b, h) that partition the
    # outer 200 x 300 rectangle (EN 1992-1-1 6.3.1(3) input), stored as the
    # torsion inputs of the project.
    subrects = [(100.0, 75.0, 200.0, 150.0), (100.0, 225.0, 200.0, 150.0)]
    for index, (x0, y0, _b, _h) in enumerate(subrects):
        at.session_state[f"torsion_sub_x{index}"] = x0
        at.session_state[f"torsion_sub_y{index}"] = y0
    outer_before = [(0.0, 0.0), (200.0, 0.0), (200.0, 300.0), (0.0, 300.0)]
    assert geometry.rectangles_partition_concrete(
        outer_before, [], subrects
    ) == (True, "")
    at.button(key="move_origin_to_centroid").click().run()
    assert any(
        "keep their values and then act about the new origin, so the results "
        "of a case with N not 0 change" in str(item.value)
        for item in at.warning
    )
    at.button(key="confirm_move_origin").click().run()
    assert not at.exception
    xc = (60_000.0 * 100.0 - 4_000.0 * 40.0) / 56_000.0
    # I1-R1-02: the torsion sub-rectangles move with the section, so the
    # partition of the moved outline stays valid.
    moved_rects = [
        (
            at.session_state[f"torsion_sub_x{index}"],
            at.session_state[f"torsion_sub_y{index}"],
            b, h,
        )
        for index, (_x, _y, b, h) in enumerate(subrects)
    ]
    assert [value for rect in moved_rects for value in rect[:2]] == pytest.approx(
        [100.0 - xc, -75.0, 100.0 - xc, 75.0], abs=1e-6
    )
    outer_after = [(x - xc, y - 150.0) for x, y in outer_before]
    assert geometry.rectangles_partition_concrete(
        outer_after, [], moved_rects
    ) == (True, "")
    moved = at.session_state["corners_base"]
    assert moved["ID"].tolist() == ["C1", "C2", "C3", "C4"]
    assert moved["x (mm)"].tolist() == pytest.approx(
        [-xc, 200.0 - xc, 200.0 - xc, -xc], abs=1e-6
    )
    assert moved["y (mm)"].tolist() == pytest.approx(
        [-150.0, -150.0, 150.0, 150.0], abs=1e-6
    )
    assert at.session_state["hole_base"]["ID"].tolist() == ["V1", "V2", "V3", "V4"]
    assert at.session_state["hole_base"]["x (mm)"].iloc[0] == pytest.approx(
        20.0 - xc, abs=1e-6
    )
    bars = at.session_state["bars_base"]
    assert bars["ID"].tolist() == ["R1", "R2", "R3", "R4"]
    assert bars["x (mm)"].tolist() == pytest.approx(
        [40.0 - xc, 160.0 - xc, 40.0 - xc, 160.0 - xc], abs=1e-6
    )
    # Decision 10: the entered moments do not change.
    pd.testing.assert_frame_equal(at.session_state["plastic_cases_base"], cases_before)
    # An incomplete corner row is reported under its grid and blocks the
    # calculation (UI-02, I1-R1-05).
    rows = at.session_state["corners_base"].to_dict("records")
    rows.append(_row("", 10.0, None))
    _submit(at, "ed_corners", rows)
    assert any(
        "Incomplete rows: C5." in str(item.value) for item in at.warning
    )
    assert at.session_state["_latest_inputs"]["geometry_error"] is not None
