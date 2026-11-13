"""Sector 0.97.1 I2: CSV action schema v1, case attributes in the editors,
moment reference texts, the sign-convention figure and the case-table memo."""

from __future__ import annotations

import math
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "app"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import project_io  # noqa: E402

from app import action_csv, load_cases, reproducible_example  # noqa: E402
from app import action_workspace as actions  # noqa: E402
from app import table_field_definitions as fields  # noqa: E402
from sector import capacity  # noqa: E402

PLASTIC = load_cases.PLASTIC_TABLE_KEY
ELASTIC = load_cases.ELASTIC_TABLE_KEY


def _reference():
    return project_io.parse_project(reproducible_example.project_json())


def _cases():
    plastic = load_cases.normalise_table([
        {"name": "ULS-1", "description": "Span; max, \"quoted\"", "n_ed_kn": -1250.5,
         "mx_ed_knm": 310.125, "my_ed_knm": -0.1, "vx_ed_kn": 12.0, "vy_ed_kn": 1e-05,
         "vx_face": "negative", "vy_face": "auto", "t_ed_knm": -4.5,
         "check_minimum_reinforcement": True, "location_tag": "Span 2, midspan",
         "design_situation": "accidental", "stage": "final"},
        {"name": "ULS-2", "n_ed_kn": 0.30000000000000004, "location_tag": "Support B"},
    ], PLASTIC)
    elastic = load_cases.normalise_table([
        {"name": "SLS-1", "description": "Quasi-permanent", "n_long_ed_kn": -350.0,
         "mx_long_ed_knm": 120.0, "my_long_ed_knm": 0.0, "n_short_ed_kn": -120.0,
         "mx_short_ed_knm": 45.25, "my_short_ed_knm": -3.0,
         "calculate_crack_width": True, "design_situation": "transient"},
    ], ELASTIC)
    return {PLASTIC: plastic, ELASTIC: elastic}


def _csv(*lines, delimiter=","):
    return "\r\n".join(lines) + "\r\n"


_HEAD = "limit_state,name,n_ed_kn,mx_ed_knm,n_long_ed_kn"
_UNITS = "-,-,kN,kNm,kN"


# --- File form ----------------------------------------------------------

def test_columns_and_units_follow_the_column_names():
    # Source: the unit suffix of each column key (kn = kN, knm = kNm).
    assert action_csv.VERSION_LINE == "# sector-actions-csv v1"
    assert action_csv.COLUMNS[:6] == (
        "limit_state", "name", "description", "location_tag", "design_situation", "stage")
    for column in action_csv.COLUMNS:
        expected = "kNm" if column.endswith("_knm") else "kN" if column.endswith("_kn") else "-"
        assert action_csv.UNITS[column] == expected, column
    plastic_only = set(load_cases.TABLE_COLUMNS[PLASTIC]) - {"name", "description"}
    elastic_only = set(load_cases.TABLE_COLUMNS[ELASTIC]) - {"name", "description"}
    assert set(action_csv.COLUMNS) == {
        "limit_state", "name", "description", *load_cases.ATTRIBUTE_COLUMNS,
        *plastic_only, *elastic_only}


def test_template_has_version_heading_and_units_rows_only():
    lines = action_csv.template().splitlines()
    assert lines[0] == "# sector-actions-csv v1"
    assert lines[1].split(",") == list(action_csv.COLUMNS)
    assert lines[2].split(",")[action_csv.COLUMNS.index("mx_long_ed_knm")] == "kNm"
    assert len(lines) == 3
    with pytest.raises(ValueError, match="at least one case row"):
        action_csv.parse(action_csv.template())


@pytest.mark.parametrize("delimiter", [",", ";"])
def test_export_and_import_give_the_same_canonical_tables(delimiter):
    tables = _cases()
    text = action_csv.export_csv(tables, delimiter=delimiter)
    if delimiter == ";":
        assert "-1250,5" in text and "1e-05" in text
    parsed = action_csv.parse(text)
    for key in load_cases.CASE_TABLE_KEYS:
        pd.testing.assert_frame_equal(
            parsed[key], load_cases.active_table(tables[key], key), check_exact=True)
    assert parsed[PLASTIC].loc[1, "n_ed_kn"] == 0.30000000000000004


def test_reference_project_round_trip_keeps_the_project_hashes():
    tables, scalars = _reference()
    text = action_csv.export_csv(tables)
    result, mapping, counts, _imported = action_csv.import_cases(
        tables, scalars.get(capacity.TORSION_CASE_AUTHORITIES_KEY), text=text, mode="replace")
    assert counts == {PLASTIC: len(load_cases.active_table(tables[PLASTIC], PLASTIC)),
                      ELASTIC: len(load_cases.active_table(tables[ELASTIC], ELASTIC))}
    new_tables = {**tables, **result}
    new_scalars = dict(scalars)
    if capacity.TORSION_CASE_AUTHORITIES_KEY in scalars:
        new_scalars[capacity.TORSION_CASE_AUTHORITIES_KEY] = mapping
    assert project_io.input_sha256(new_tables, new_scalars) == project_io.input_sha256(tables, scalars)
    assert (project_io.persistence_sha256(new_tables, new_scalars)
            == project_io.persistence_sha256(tables, scalars))
    assert (project_io.dump_project(new_tables, new_scalars)
            == project_io.dump_project(tables, scalars))


def test_reference_project_round_trip_keeps_the_result_sha256():
    from app import calculation_service

    tables, scalars = _reference()
    result, mapping, _counts, _imported = action_csv.import_cases(
        tables, scalars.get(capacity.TORSION_CASE_AUTHORITIES_KEY),
        text=action_csv.export_csv(tables, delimiter=";"), mode="replace")
    new_scalars = dict(scalars)
    if capacity.TORSION_CASE_AUTHORITIES_KEY in scalars:
        new_scalars[capacity.TORSION_CASE_AUTHORITIES_KEY] = mapping
    before = calculation_service.calculate_project(reproducible_example.project_json())
    after = calculation_service.calculate_project(
        project_io.dump_project({**tables, **result}, new_scalars))
    assert after["result_sha256"] == before["result_sha256"]


def test_spreadsheet_forms_import():
    # Excel pads the version line with delimiters, adds a BOM and CRLF ends.
    text = (chr(0xFEFF) + "# sector-actions-csv v1;;;;\r\n" + _HEAD.replace(",", ";")
            + "\r\n" + _UNITS.replace(",", ";").replace("kNm", "kN m") + "\r\n"
            + "uls;P1;-1,5;2;\r\nSLS;E1;;;3,25\r\n")
    parsed = action_csv.parse(text)
    assert parsed[PLASTIC].loc[0, "n_ed_kn"] == -1.5
    assert parsed[ELASTIC].loc[0, "n_long_ed_kn"] == 3.25
    assert parsed[PLASTIC].loc[0, "design_situation"] == "persistent"
    quoted = _csv(action_csv.VERSION_LINE, _HEAD, _UNITS, 'ULS,P1,"-1,5",2,')
    assert action_csv.parse(quoted)[PLASTIC].loc[0, "n_ed_kn"] == -1.5
    tabbed = _csv(action_csv.VERSION_LINE, _HEAD.replace(",", "\t"),
                  _UNITS.replace(",", "\t"), "ULS\tP1\t1\t2\t")
    assert action_csv.parse(tabbed)[PLASTIC].loc[0, "mx_ed_knm"] == 2.0


def test_decode_reads_utf8_and_windows_1252():
    text = "description " + "".join(map(chr, (0xE6, 0xF8, 0xE5)))
    assert action_csv.decode(text.encode("utf-8-sig")) == text
    assert action_csv.decode(text.encode("cp1252")) == text
    with pytest.raises(ValueError, match="at most 2 MB"):
        action_csv.decode(b" " * (action_csv.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="CSV UTF-8"):
        action_csv.decode(b"\x81\x8d")


@pytest.mark.parametrize(("text", "message"), [
    ("", "Line 1 must be the version line"),
    (_csv(_HEAD, _UNITS, "ULS,P1,1,2,"), "Line 1 must be the version line"),
    (_csv("# sector-actions-csv v2", _HEAD, _UNITS, "ULS,P1,1,2,"), 'schema "v2"'),
    (_csv(action_csv.VERSION_LINE), "heading row and the units row"),
    (_csv(action_csv.VERSION_LINE, _HEAD + ",n_ed", _UNITS + ",kN", "ULS,P1,1,2,,1"),
     'the column headings "n_ed" are not known'),
    (_csv(action_csv.VERSION_LINE, "name,n_ed_kn", "-,kN", "P1,1"), "add the limit_state column"),
    (_csv(action_csv.VERSION_LINE, _HEAD, "-,-,kN,MNm,kN", "ULS,P1,1,2,"),
     'the unit of mx_ed_knm must be "kNm". The file has "MNm".'),
    (_csv(action_csv.VERSION_LINE, _HEAD, _UNITS, "ULS,P1,1,2,5"),
     "Line 4: leave n_long_ed_kn blank in a ULS row"),
    (_csv(action_csv.VERSION_LINE, _HEAD, _UNITS, "QLS,P1,1,2,"),
     "Line 4: limit_state must be ULS or SLS"),
    (_csv(action_csv.VERSION_LINE, _HEAD, _UNITS, "ULS,,1,2,"), "Line 4: enter a case name"),
    (_csv(action_csv.VERSION_LINE, _HEAD, _UNITS, "ULS,P1,1,2"), "Line 4 has 4 cells"),
    (_csv(action_csv.VERSION_LINE, _HEAD, _UNITS, "ULS,P1,1;5,2,"),
     'Line 4: n_ed_kn must be one decimal number. The file has "1;5".'),
    (_csv(action_csv.VERSION_LINE, "limit_state,name,design_situation", "-,-,-",
          "ULS,P1,frequent"), "Line 4: design_situation must be persistent"),
    (_csv(action_csv.VERSION_LINE, "limit_state,name,stage", "-,-,-", "SLS,E1,erection"),
     'Line 4: stage must be blank or "final"'),
    (_csv(action_csv.VERSION_LINE, "limit_state,name,location_tag", "-,-,-",
          "ULS,P1," + "x" * 61), "Line 4: location_tag must be one line of at most 60"),
    (_csv(action_csv.VERSION_LINE, "limit_state,name,vx_face", "-,-,-", "ULS,P1,middle"),
     "Line 4: vx_face must be auto, negative or positive"),
    (_csv(action_csv.VERSION_LINE, "limit_state,name,calculate_crack_width", "-,-,-",
          "SLS,E1,maybe"), "Line 4: use true or false in calculate_crack_width"),
])
def test_invalid_files_fail_closed_with_the_line(text, message):
    with pytest.raises(ValueError) as error:
        action_csv.parse(text)
    assert message in str(error.value)


def test_form_edges_trailing_cells_headings_and_message_limit():
    with pytest.raises(ValueError, match="comma or a semicolon"):
        action_csv.export_csv(_cases(), delimiter="\t")
    assert action_csv.is_versioned("\n  \n") is False
    # Trailing empty heading and data cells (spreadsheet padding) are ignored.
    padded = _csv(action_csv.VERSION_LINE, _HEAD + ",,", _UNITS + ",,", "ULS,P1,1,2,,,")
    assert action_csv.parse(padded)[PLASTIC].loc[0, "mx_ed_knm"] == 2.0
    with pytest.raises(ValueError, match="Line 2: give each column a heading"):
        action_csv.parse(_csv(action_csv.VERSION_LINE, "limit_state,,name", "-,-,-", "ULS,,P1"))
    with pytest.raises(ValueError, match="Line 2: use each column heading once"):
        action_csv.parse(_csv(action_csv.VERSION_LINE, "limit_state,name,NAME", "-,-,-", "ULS,P,Q"))
    # A one-column file has no delimiter: the version check still applies.
    with pytest.raises(ValueError, match="add the name column"):
        action_csv.parse(_csv(action_csv.VERSION_LINE, "limit_state", "-", "ULS"))
    many = _csv(action_csv.VERSION_LINE, _HEAD, _UNITS, *[f"XLS,P{i},1,2," for i in range(7)])
    with pytest.raises(ValueError) as error:
        action_csv.parse(many)
    assert str(error.value).endswith(". The file has 2 more issues.")


def test_older_form_paste_still_imports_and_older_file_gives_one_message():
    # The 0.97.0 per-table paste form: a heading row and case rows, no version
    # line and no units row.
    old = "name\tn_ed_kn\tmx_ed_knm\nP-OLD\t-10,5\t3\n"
    frame = actions.prepare_paste(old, PLASTIC)
    assert frame.loc[0, "n_ed_kn"] == -10.5
    assert frame.loc[0, "design_situation"] == "persistent"
    with pytest.raises(ValueError) as error:
        action_csv.parse(old)
    assert str(error.value) == action_csv.NO_VERSION_MESSAGE
    with pytest.raises(ValueError, match="starts with a version line"):
        actions.prepare_paste(_csv(action_csv.VERSION_LINE, _HEAD, _UNITS), PLASTIC)
    with_attributes = "name\tstage\tdesign_situation\nP2\tfinal\tSeismic\n"
    frame = actions.prepare_paste(with_attributes, PLASTIC)
    assert (frame.loc[0, "stage"], frame.loc[0, "design_situation"]) == ("final", "seismic")
    with pytest.raises(ValueError, match="Pasted row 1: stage"):
        actions.prepare_paste("name\tstage\nP3\tstage 1\n", PLASTIC)
    assert actions.paste_template(ELASTIC).rstrip("\n").split("\t") == list(
        load_cases.PERSISTED_COLUMNS[ELASTIC])


def _authority():
    return {capacity.TORSION_CASE_DESIGN_BASIS_KEY: capacity.TORSION_DESIGN_EQUILIBRIUM,
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: capacity.TORSION_MEMBER_CLOSED}


def test_replace_keeps_a_declaration_only_for_an_unchanged_case():
    tables = _cases()
    authorities = {"ULS-1": _authority(), "ULS-2": _authority(), "GONE": _authority()}
    changed = {key: table.copy(deep=True) for key, table in tables.items()}
    changed[PLASTIC].loc[1, "n_ed_kn"] = 0.5
    text = action_csv.export_csv(changed)
    result, mapping, counts, _imported = action_csv.import_cases(
        tables, authorities, text=text, mode="replace")
    assert set(mapping) == {"ULS-1"}
    assert counts == {PLASTIC: 2, ELASTIC: 1}
    assert result[PLASTIC].loc[1, "n_ed_kn"] == 0.5


def test_append_adds_cases_and_rejects_a_repeated_name():
    tables = _cases()
    text = _csv(action_csv.VERSION_LINE, _HEAD, _UNITS, "ULS,NEW-1,1,2,", "SLS,NEW-2,,,7")
    result, mapping, counts, _imported = action_csv.import_cases(
        tables, {"NEW-1": _authority(), "ULS-1": _authority()}, text=text, mode="append")
    assert list(result[PLASTIC]["name"]) == ["ULS-1", "ULS-2", "NEW-1"]
    assert list(result[ELASTIC]["name"]) == ["SLS-1", "NEW-2"]
    assert set(mapping) == {"ULS-1"} and counts == {PLASTIC: 1, ELASTIC: 1}
    repeated = _csv(action_csv.VERSION_LINE, _HEAD, _UNITS, "SLS,uls-1,,,7")
    with pytest.raises(ValueError, match="unique name"):
        action_csv.import_cases(tables, {}, text=repeated, mode="append")
    with pytest.raises(ValueError, match="append or replace"):
        action_csv.import_cases(tables, {}, text=text, mode="merge")


def test_queued_import_replaces_both_tables_and_clears_the_upload():
    state = {key: table for key, table in _cases().items()}
    state[actions.AUTHORITY_KEY] = {"ULS-1": _authority()}
    text = _csv(action_csv.VERSION_LINE, _HEAD, _UNITS, "ULS,A,1,2,", "SLS,B,,,3")
    reseeded = {}

    def reseed(key, value):
        reseeded[key] = value
        state[key] = value

    actions.queue_command(state, {"operation": "import", "text": text, "mode": "replace",
                                  "expected_digest": actions.table_digest(state)})
    actions.consume_command(state, reseed)
    assert set(reseeded) == set(load_cases.CASE_TABLE_KEYS)
    assert state[actions.NOTICE_KEY] == (
        True, "Sector imported 1 ULS case and 1 SLS case. Review the cases and the "
              "torsion declarations before calculation.")
    assert state[actions.AUTHORITY_KEY] == {}
    assert state[actions.CSV_FILE_VERSION_KEY] == 1
    assert state[actions.selection_key(PLASTIC)] == 0
    stale = {"operation": "import", "text": text, "mode": "append", "expected_digest": "0"}
    actions.queue_command(state, stale)
    actions.consume_command(state, reseed)
    assert state[actions.NOTICE_KEY][0] is False
    assert "changed" in state[actions.NOTICE_KEY][1]


class _Host:
    """Record the calls of the CSV panel, with one uploaded file."""

    def __init__(self, data=None, mode="Replace the Plastic and Elastic cases", open=True):
        self.data, self.mode, self.open, self.calls = data, mode, open, []

    def expander(self, *args, **kwargs):
        return self

    def columns(self, count):
        return [self] * count

    def radio(self, label, options, **kwargs):
        return self.mode if label == "Import mode" else options[0]

    def file_uploader(self, *args, **kwargs):
        if self.data is None:
            return None
        return type("Upload", (), {"getvalue": lambda _self: self.data})()

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return record


def test_csv_panel_previews_a_valid_file_and_reports_an_invalid_file():
    state = dict(_cases())
    assert actions.csv_panel(_Host(open=False), state=state) is None
    empty = _Host()
    actions.csv_panel(empty, state=state)
    downloads = [call for call in empty.calls if call[0] == "download_button"]
    assert [call[1][0] for call in downloads] == ["Download actions CSV", "Download CSV template"]
    assert downloads[0][1][1] == action_csv.export_csv(state)
    assert not any(call[0] == "button" for call in empty.calls)
    text = _csv(action_csv.VERSION_LINE, _HEAD, _UNITS, "ULS,A,1,2,")
    valid = _Host(text.encode("utf-8"))
    actions.csv_panel(valid, state=state)
    button = next(call for call in valid.calls if call[0] == "button")
    assert button[1][0] == "Import 1 ULS case and 0 SLS cases"
    command = button[2]["args"][1]
    assert (command["operation"], command["mode"], command["text"]) == ("import", "replace", text)
    assert ("markdown", ("**Plastic cases (ULS)**",), {}) in valid.calls
    invalid = _Host(_csv(_HEAD, _UNITS, "ULS,A,1,2,").encode("utf-8"), mode="Append to the current cases")
    actions.csv_panel(invalid, state=state)
    assert ("error", (action_csv.NO_VERSION_MESSAGE,), {}) in invalid.calls
    assert not any(call[0] == "button" for call in invalid.calls)


def test_actions_page_shows_attributes_figure_and_csv_panel(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    app = AppTest.from_file(str(ROOT / "app" / "sector_app.py"), default_timeout=120)
    app.session_state["_next_workflow_page"] = "actions"
    app.run()
    assert not app.exception
    labels = [item.label for item in app.expander]
    assert "Axes, signs and paste rules" in labels
    assert "Import and export actions (CSV v1)" in labels
    assert len(app.get("plotly_chart")) >= 1
    editor = next(item for item in app.dataframe if item.key == "plastic_cases_editor")
    assert list(editor.proto.column_order) == list(load_cases.PERSISTED_COLUMNS[PLASTIC])
    text = _csv(action_csv.VERSION_LINE, _HEAD, _UNITS, "ULS,IMP-1,-5,7,", "SLS,IMP-2,,,-9")
    tables = {key: app.session_state[key] for key in load_cases.CASE_TABLE_KEYS}
    app.session_state[actions.COMMAND_KEY] = {
        "operation": "import", "text": text, "mode": "replace",
        "expected_digest": actions.table_digest(tables)}
    app.run()
    assert not app.exception
    assert list(app.session_state[PLASTIC]["name"]) == ["IMP-1"]
    assert list(app.session_state[ELASTIC]["n_long_ed_kn"]) == [-9.0]
    assert any("Sector imported 1 ULS case and 1 SLS case" in item.value for item in app.success)


# --- Field registry, help texts and conventions ------------------------------

def test_case_attributes_are_registered_without_a_calculation_effect():
    assert fields.CASE_ATTRIBUTE_KEYS == load_cases.ATTRIBUTE_COLUMNS
    for key in load_cases.CASE_TABLE_KEYS:
        assert tuple(item.key for item in fields.table_fields(key)) == load_cases.PERSISTED_COLUMNS[key]
        for column in load_cases.ATTRIBUTE_COLUMNS:
            definition = fields.field_definition(key, column)
            assert fields.method_dependency(key, definition) == fields.CASE_ATTRIBUTE_DEPENDENCY
            assert "No calculation uses this value." in definition.help
    assert fields.field_definition(PLASTIC, "design_situation").default == "persistent"


def test_moment_help_and_conventions_state_the_origin_reference():
    for key in (PLASTIC, ELASTIC, fields.FATIGUE_SPECTRUM_TABLE_KEY):
        for definition in fields.table_fields(key):
            if definition.key.startswith(("mx_", "my_")):
                assert "origin O" in definition.help, (key, definition.key)

    class Guide:
        def __init__(self):
            self.paragraphs = []

        def expander(self, *args, **kwargs):
            return self

        def markdown(self, text):
            self.paragraphs.append(text)

    guide = Guide()
    assert actions.conventions(guide) is guide
    text = " ".join(guide.paragraphs)
    assert "through the section origin O (0, 0)" in text
    assert "Mx = Mx,C - N yc and My = My,C - N xc" in text
    assert "xc and yc in m, that is the section coordinates in mm divided by 1000" in text
    assert all(len(paragraph.split()) <= 50 for paragraph in guide.paragraphs)


def test_moment_reference_formula_agrees_with_the_elastic_solver():
    # Hand calculation: a 300 x 400 mm plain rectangle with O at its lower-left
    # corner, so the centroid C is at (150, 200) mm. N = -1000 kN (compression)
    # through C gives a uniform stress. About O, the conventions text gives
    # Mx = 0 - (-1000)(0.2) = 200 kNm and My = 0 - (-1000)(0.15) = 150 kNm.
    from sector import elastic
    from sector.section import Section

    section = Section([np.array([[0.0, 0.0], [0.3, 0.0], [0.3, 0.4], [0.0, 0.4]])])
    n_tension = -1000.0
    result = elastic.solve_elastic_uncracked(
        section, -n_tension, 0.0 - n_tension * 0.2, 0.0 - n_tension * 0.15, 6.0)
    # Uniform compression 1000 / (0.3 * 0.4) = 8333.3 kN/m2, no gradient.
    assert math.isclose(result.max_concrete_compression, 1000.0 / 0.12, rel_tol=1e-9)
    assert abs(result.kx) < 1e-9 and abs(result.ky) < 1e-9


def test_manual_publishes_the_csv_field_reference():
    from app import manual

    blocks = manual.manual_blocks()
    tables = [block for block in blocks
              if block[0] == "table" and block[1] == ["Column", "Unit", "Rows", "Content"]]
    assert len(tables) == 1
    rows = {row[0]: row for row in tables[0][2]}
    assert rows["`limit_state`"][2] == "All"
    assert rows["`mx_ed_knm`"][1:3] == ["kNm", "ULS"]
    assert rows["`n_long_ed_kn`"][1:3] == ["kN", "SLS"]
    text = " ".join(block[1] for block in blocks if block[0] == "md")
    assert "`# sector-actions-csv v1`" in text


# --- Sign-convention figure ---------------------------------------------------

def test_sign_convention_figure_labels_every_positive_action():
    import report_diagrams

    figure = report_diagrams.action_sign_convention_figure()
    labels = [item.text for item in figure.layout.annotations if item.text]
    for label in ("+x", "+y", "+Vx", "+Vy", "T", "O", "+N = tension",
                  "<b>+Mx, centred bending</b>", "<b>+My, centred bending</b>"):
        assert label in labels
    # +Mx compresses the top face and +My the right face (Sector convention).
    compression = [trace for trace in figure.data
                   if getattr(trace, "fillpattern", None) is not None
                   and trace.fillpattern.shape == "x"]
    assert len(compression) == 2
    assert min(compression[0].y) > 0.0 and min(compression[1].x) > 0.0
    texts = {(item.text, item.xref) for item in figure.layout.annotations}
    assert ("Compression", "x2") in texts and ("Tension", "x3") in texts


# --- UI-31 memo ------------------------------------------------------------

def test_memo_gives_the_uncached_result_and_detached_copies():
    sources = [
        _cases()[PLASTIC],
        load_cases.editor_table(_cases()[PLASTIC], PLASTIC),
        pd.DataFrame([{"name": "A", "n_ed_kn": "1,5", "mx_ed_knm": "x1"}]),
    ]
    for source in sources:
        expected = load_cases._normalise_table(source, PLASTIC)
        for _ in range(2):
            actual = load_cases.normalise_table(source, PLASTIC)
            pd.testing.assert_frame_equal(actual, expected, check_exact=True)
            assert actual.attrs == expected.attrs
    first = load_cases.normalise_table(sources[2], PLASTIC)
    assert fields.is_invalid_decimal_sentinel(first.loc[0, "mx_ed_knm"])
    first.loc[0, "name"] = "CHANGED"
    first.attrs.clear()
    again = load_cases.normalise_table(sources[2], PLASTIC)
    assert again.loc[0, "name"] == "A"
    assert fields.decimal_issue_ledger(again.attrs) == {(0, "mx_ed_knm"): "x1"}


def test_memo_is_used_for_a_repeated_table(monkeypatch):
    calls = []
    original = load_cases._normalise_table

    def counted(value, key):
        calls.append(key)
        return original(value, key)

    monkeypatch.setattr(load_cases, "_normalise_table", counted)
    source = pd.DataFrame([{"name": "MEMO-COUNT", "n_ed_kn": "-7,25"}])
    first = load_cases.normalise_table(source, PLASTIC)
    second = load_cases.normalise_table(source.copy(deep=True), PLASTIC)
    assert len(calls) == 1
    pd.testing.assert_frame_equal(first, second, check_exact=True)
    large = pd.DataFrame({"name": [f"L{i}" for i in range(load_cases._MEMO_MAX_CELLS + 1)]})
    load_cases.normalise_table(large, PLASTIC)
    load_cases.normalise_table(large, PLASTIC)
    assert len(calls) == 3


def test_memo_keeps_the_ledger_of_each_canonical_frame():
    one = load_cases.normalise_table(pd.DataFrame([{"name": "A", "n_ed_kn": "1.2.3"}]), PLASTIC)
    two = load_cases.normalise_table(pd.DataFrame([{"name": "A", "n_ed_kn": "4..5"}]), PLASTIC)
    # The same sentinel cells, different issue texts.
    assert fields.is_invalid_decimal_sentinel(one.loc[0, "n_ed_kn"])
    assert fields.is_invalid_decimal_sentinel(two.loc[0, "n_ed_kn"])
    for frame, entered in ((one, "1.2.3"), (two, "4..5"), (one, "1.2.3")):
        again = load_cases.normalise_table(frame, PLASTIC)
        assert fields.decimal_issue_ledger(again.attrs) == {(0, "n_ed_kn"): entered}


def _template_row(**values):
    cells = dict.fromkeys(action_csv.COLUMNS, "")
    cells.update(values)
    return [cells[column] for column in action_csv.COLUMNS]


def test_an_extra_cell_never_moves_a_value_to_the_next_column():
    # I2-R1-01: the template row "ULS,P1,,,,,-1250,5,310,0,..." with an
    # unquoted comma decimal has one cell more than the heading row.
    row = _template_row(limit_state="ULS", name="P1", n_ed_kn="-1250,5",
                        mx_ed_knm="310", my_ed_knm="0")
    lines = action_csv.template().splitlines()
    shifted = _csv(*lines, ",".join(row))
    width = len(action_csv.COLUMNS)
    with pytest.raises(ValueError) as error:
        action_csv.parse(shifted)
    assert str(error.value) == (
        f"Line 4 has {width + 1} cells. The heading row has {width}. "
        "Put each comma decimal in quotes.")
    quoted = _csv(*lines, ",".join(cell if "," not in cell else f'"{cell}"' for cell in row))
    parsed = action_csv.parse(quoted)[PLASTIC]
    assert (parsed.loc[0, "n_ed_kn"], parsed.loc[0, "mx_ed_knm"]) == (-1250.5, 310.0)


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_each_delimiter_rejects_a_row_wider_than_the_heading_row(delimiter):
    head = delimiter.join(("limit_state", "name", "n_ed_kn", "mx_ed_knm"))
    units = delimiter.join(("-", "-", "kN", "kNm"))
    pad = delimiter * 2
    padded = _csv(action_csv.VERSION_LINE, head + pad, units + pad,
                  delimiter.join(("ULS", "P1", "1", "2", "", "")))
    assert action_csv.parse(padded)[PLASTIC].loc[0, "mx_ed_knm"] == 2.0
    trailing = _csv(action_csv.VERSION_LINE, head, units, delimiter.join(("ULS", "P1", "1", "2", "")))
    with pytest.raises(ValueError, match="Line 4 has 5 cells. The heading row has 4."):
        action_csv.parse(trailing)
    wide = _csv(action_csv.VERSION_LINE, head, units, delimiter.join(("ULS", "P1", "1", "5", "2")))
    with pytest.raises(ValueError, match="Line 4 has 5 cells. The heading row has 4."):
        action_csv.parse(wide)
    # A padded heading row: a value under a blank heading is rejected.
    under_blank = _csv(action_csv.VERSION_LINE, head + delimiter, units + delimiter,
                       delimiter.join(("ULS", "P1", "1", "2", "9")))
    with pytest.raises(ValueError, match="Line 4 has a value in a column without a heading."):
        action_csv.parse(under_blank)


def test_repeated_names_and_fatigue_bins_give_the_line_and_the_name():
    tables = _cases()
    again = _csv(action_csv.VERSION_LINE, _HEAD, _UNITS, "ULS,X1,1,2,", "SLS,uls-1,,,7")
    with pytest.raises(ValueError) as error:
        action_csv.import_cases(tables, {}, text=again, mode="append")
    assert str(error.value) == ('Line 5: the case name "uls-1" is already used by a current '
                                "case. Use a unique name for each case.")
    inside = _csv(action_csv.VERSION_LINE, _HEAD, _UNITS, "ULS,D1,1,2,", "SLS,d1,,,7")
    with pytest.raises(ValueError, match='Line 5: the case name "d1" is already used by an '
                                         "earlier line of the file."):
        action_csv.import_cases(tables, {}, text=inside, mode="replace")
    with pytest.raises(ValueError, match='Line 4: the case name "D1" is already used by a fatigue bin.'):
        action_csv.import_cases(tables, {}, text=inside, mode="replace", reserved_names=("d1",))
    assert "EngineerMessage" not in str(error.value)


def test_paste_errors_use_the_message_text():
    state = dict(_cases())
    with pytest.raises(ValueError) as error:
        actions.edit_cases(state, {}, table=PLASTIC, operation="paste", text="name\tn_ed_kn\nULS-1\t1\n")
    assert str(error.value) == "Use a unique name for every Plastic and Elastic case."


@pytest.mark.parametrize(("text", "message"), [
    (_csv(action_csv.VERSION_LINE, _HEAD, _UNITS, 'ULS,"P1"x,1,2,'),
     "Line 4: Sector cannot read this line. A quoted cell is not closed correctly."),
    (_csv(action_csv.VERSION_LINE, _HEAD, _UNITS, 'ULS,"P1,1,2,'),
     "Line 4: Sector cannot read this line. A quoted cell is not closed correctly."),
    (_csv(action_csv.VERSION_LINE, _HEAD, _UNITS, 'ULS,"' + "x" * 131073 + '",1,2,'),
     "A cell has more than 131072 characters."),
    (_csv(action_csv.VERSION_LINE, _HEAD, _UNITS, 'ULS,P1,1,2,', 'ULS,"two\nlines",1,2,', "XLS,P3,1,2,"),
     "Line 7: limit_state must be ULS or SLS."),
], ids=["text-after-quote", "open-quote", "long-cell", "multi-line-record"])
def test_csv_reader_errors_and_line_numbers(text, message):
    with pytest.raises(ValueError) as error:
        action_csv.parse(text)
    assert message in str(error.value)


def test_utf16_files_and_other_hash_lines_give_one_message():
    data = (chr(0xFEFF) + action_csv.VERSION_LINE).encode("utf-16-le")
    with pytest.raises(ValueError, match="CSV UTF-8"):
        action_csv.decode(bytes((0xFF, 0xFE)) + data[2:])
    with pytest.raises(ValueError, match="CSV UTF-8"):
        action_csv.decode(action_csv.VERSION_LINE.encode("utf-16-be"))
    comment = "# my comment\nname\tn_ed_kn\nP1\t1\n"
    assert action_csv.is_versioned(comment) is False
    assert action_csv.is_versioned('"# Sector-actions-csv v1",,') is True
    with pytest.raises(ValueError, match="Use the template column headings"):
        actions.prepare_paste(comment, PLASTIC)


def test_file_with_only_the_two_necessary_columns_imports():
    # Both columns are unitless, so the units row is all blank (",").
    text = _csv(action_csv.VERSION_LINE, "limit_state,name", ",", "ULS,P-ONLY", ",", "SLS,E-ONLY")
    parsed = action_csv.parse(text)
    assert list(parsed[PLASTIC]["name"]) == ["P-ONLY"]
    assert list(parsed[ELASTIC]["name"]) == ["E-ONLY"]
    assert parsed[PLASTIC].loc[0, "n_ed_kn"] == 0.0
    with pytest.raises(ValueError, match="Add at least one case row after the units row."):
        action_csv.parse(_csv(action_csv.VERSION_LINE, "limit_state,name", ",", ","))


def test_case_row_limit(monkeypatch):
    monkeypatch.setattr(action_csv, "MAX_CASE_ROWS", 2)
    text = _csv(action_csv.VERSION_LINE, _HEAD, _UNITS, "ULS,R1,1,2,", "ULS,R2,1,2,", "ULS,R3,1,2,")
    with pytest.raises(ValueError, match="more than 2 case rows"):
        action_csv.parse(text)


def test_memo_separates_a_cleared_cell_from_a_malformed_cell():
    malformed = load_cases.normalise_table(
        pd.DataFrame([{"name": "A", "n_ed_kn": "1.2.3"}]), PLASTIC)
    repeated = load_cases.normalise_table(malformed, PLASTIC)
    assert fields.is_invalid_decimal_sentinel(repeated.loc[0, "n_ed_kn"])
    cleared = malformed.copy(deep=True)
    cleared.loc[0, "n_ed_kn"] = math.nan
    result = load_cases.normalise_table(cleared, PLASTIC)
    assert result.loc[0, "n_ed_kn"] == 0.0
    assert fields.decimal_issue_ledger(result.attrs) == {}
