"""Exact UI destinations preserve existing validation and input tables."""

from __future__ import annotations

import copy

import pandas as pd
import pytest

from app import input_issues, load_cases
from sector.engineer_message import EngineerMessage


def _issues(plastic=None, elastic=None):
    errors = load_cases.validation_errors(plastic, elastic)
    return input_issues.case_issues(errors, plastic=plastic, elastic=elastic)


@pytest.mark.parametrize("key", load_cases.CASE_TABLE_KEYS)
def test_each_numeric_field_routes_to_exact_case_and_column(key):
    for field in load_cases.NUMERIC_COLUMNS[key]:
        rows = [{"name": "Valid"}, {"name": "Case 2", field: "bad"}]
        plastic, elastic = (rows, None) if key == load_cases.PLASTIC_TABLE_KEY else (None, rows)
        issue, = _issues(plastic, elastic)
        location = issue.target.case_location
        assert location.table_key == key
        assert location.field_key == field
        assert location.case_name == "Case 2"
        assert location.row_position == 1
        assert input_issues.resolve_case_location(location, plastic, elastic) == 1


def test_blank_spacer_rows_do_not_shift_physical_editor_destination():
    rows = [{}, {"name": "A"}, {}, {"name": "B", "n_ed_kn": "bad"}]
    issue, = _issues(rows)
    assert issue.target.case_location.row_position == 3
    assert input_issues.resolve_case_location(issue.target.case_location, rows, None) == 3


def test_unique_case_survives_reordering_without_reusing_an_old_row_number():
    rows = [{"name": "A"}, {"name": "B", "n_ed_kn": "bad"}]
    issue, = _issues(rows)
    assert input_issues.resolve_case_location(issue.target.case_location, rows[::-1], None) == 0


@pytest.mark.parametrize("change", ["rename", "delete", "correct", "duplicate", "family"])
def test_changed_case_expires_focus_and_preserves_existing_selection(change):
    rows = [{"name": "A"}, {"name": "B", "n_ed_kn": "bad"}]
    issue, = _issues(rows)
    current = copy.deepcopy(rows)
    elastic = None
    if change == "rename":
        current[1]["name"] = "C"
    elif change == "delete":
        current.pop()
    elif change == "correct":
        current[1]["n_ed_kn"] = 0.0
    elif change == "duplicate":
        current.append({"name": "b"})
    else:
        current.pop()
        elastic = [{"name": "B", "n_long_ed_kn": "bad"}]
    selection = {"selected_case": "A", "filter": "attention", "scroll": 420}
    retained = dict(selection)
    assert input_issues.resolve_case_location(issue.target.case_location, current, elastic) is None
    assert selection == retained


def test_duplicate_names_bind_later_occurrence_across_families():
    plastic = [{"name": "Case A"}]
    elastic = [{"name": "case a", "n_short_ed_kn": "bad"}]
    duplicate, numeric = _issues(plastic, elastic)
    assert duplicate.message.code == "CASE-NAME-UNIQUE"
    assert duplicate.target.case_location.field_key == "name"
    assert duplicate.target.case_location.case_name is None
    assert numeric.target.case_location.case_name is None
    assert input_issues.resolve_case_location(duplicate.target.case_location, plastic, elastic) == 0
    plastic.append({"name": "New"})
    assert input_issues.resolve_case_location(duplicate.target.case_location, plastic, elastic) is None


def test_multiple_duplicate_rows_have_separate_snapshot_bound_locations():
    rows = [{"name": "A"}, {"name": "a"}, {"name": " A "}]
    issues = _issues(rows)
    assert [issue.target.case_location.row_position for issue in issues] == [1, 2]
    assert all(issue.target.case_location.case_name is None for issue in issues)


def test_unnamed_active_row_is_exact_while_snapshot_is_unchanged():
    rows = [{}, {"n_ed_kn": 17}]
    issue, = _issues(rows)
    assert issue.target.case_location.field_key == "name"
    assert issue.target.case_location.row_position == 1
    assert issue.target.case_location.case_name is None
    assert input_issues.resolve_case_location(issue.target.case_location, rows, None) == 1
    assert input_issues.resolve_case_location(issue.target.case_location, rows[::-1], None) is None


def test_both_invalid_face_fields_route_in_existing_validator_order():
    rows = [{"name": "A", "vx_face": "bad x", "vy_face": "bad y"}]
    issues = _issues(rows)
    assert [issue.target.case_location.field_key for issue in issues] == ["vx_face", "vy_face"]
    assert [issue.message for issue in issues] == load_cases.validation_errors(rows, None)


def test_required_table_and_sweep_keep_their_existing_destinations():
    rows = [{"name": "E", "my_short_ed_knm": "bad"}]
    sweep = EngineerMessage("PLASTIC-SWEEP-BOUNDS", "Correct the sweep")
    errors = [sweep, *load_cases.validation_errors(None, rows, require_plastic=True)]
    issues = input_issues.case_issues(errors, elastic=rows)
    assert issues[0].target.widget_key == "v_max"
    assert issues[1].target.widget_key == "plastic_cases_editor"
    assert issues[1].target.case_location is None
    assert issues[2].target.case_location.field_key == "my_short_ed_knm"


@pytest.mark.parametrize("value", [
    "PLASTIC-N-ED: row 1 n_ed_kn",
    EngineerMessage("PLASTIC-UNKNOWN", "Open row 1"),
    EngineerMessage("UNKNOWN-CODE", "Open Elastic case A"),
])
def test_unknown_or_untyped_diagnostics_never_grant_navigation(value):
    issue, = input_issues.case_issues([value], plastic=[{"name": "A", "n_ed_kn": "bad"}])
    assert issue.target is None


def test_known_code_with_different_authored_text_cannot_borrow_row_context():
    value = EngineerMessage("PLASTIC-N-ED", "A different diagnostic")
    issue, = input_issues.case_issues([value], plastic=[{"name": "A", "n_ed_kn": "bad"}])
    assert issue.target.case_location is None


def test_reordered_or_partial_diagnostic_sequence_gets_no_exact_destinations():
    rows = [{"name": "A", "n_ed_kn": "bad", "t_ed_knm": "bad"}]
    errors = load_cases.validation_errors(rows, None)
    for values in (errors[::-1], errors[:1], errors + [EngineerMessage("UNKNOWN", "Unknown")]):
        issues = input_issues.case_issues(values, plastic=rows)
        assert all(issue.target is None or issue.target.case_location is None for issue in issues)


def test_snapshot_inputs_attrs_and_validator_messages_remain_identical():
    plastic = load_cases.normalise_table(
        [{"name": "A", "n_ed_kn": "bad"}, {}, {"name": "A", "t_ed_knm": "invalid"}],
        load_cases.PLASTIC_TABLE_KEY,
    )
    elastic = load_cases.normalise_table([{ "name": "E", "n_long_ed_kn": 42}], load_cases.ELASTIC_TABLE_KEY)
    before = (plastic.copy(deep=True), elastic.copy(deep=True))
    attrs = copy.deepcopy([plastic.attrs, elastic.attrs])
    errors = load_cases.validation_errors(plastic, elastic)
    issues = input_issues.case_issues(errors, plastic=plastic, elastic=elastic)
    assert [issue.message for issue in issues] == errors
    assert all(issue.target.case_location is not None for issue in issues)
    for current, original in zip((plastic, elastic), before):
        pd.testing.assert_frame_equal(current, original)
    assert [plastic.attrs, elastic.attrs] == attrs
    assert load_cases.validation_errors(plastic, elastic) == errors


def test_case_name_content_is_data_and_cannot_select_a_different_field():
    rows = [{"name": "elastic_cases_editor <script>row 4</script>", "n_ed_kn": "bad"}]
    issue, = _issues(rows)
    assert issue.target.widget_key == "plastic_cases_editor"
    assert issue.target.case_location.field_key == "n_ed_kn"
    assert input_issues.resolve_case_location(issue.target.case_location, rows, None) == 0


def test_impossible_case_destination_is_rejected():
    issue, = _issues([{"name": "A", "n_ed_kn": "bad"}])
    with pytest.raises(ValueError, match="Actions editor"):
        input_issues.InputTarget(input_issues.SECTION, "ed_bars", case_location=issue.target.case_location)
    assert input_issues.resolve_case_location({"row_position": 0}, None, None) is None


@pytest.mark.parametrize("errors", [[], [EngineerMessage("PLASTIC-SWEEP-BOUNDS", "Correct the sweep")]])
def test_valid_tables_and_global_issues_do_not_replay_row_validation(monkeypatch, errors):
    def unexpected(*args, **kwargs):
        pytest.fail("row validation must run only for existing row diagnostics")

    monkeypatch.setattr(input_issues, "_exact_case_targets", unexpected)
    input_issues.case_issues(errors, plastic=[{"name": "A"}])


@pytest.mark.parametrize("name_kind", ["unique", "ambiguous", "unnamed"])
@pytest.mark.parametrize("canonical", [False, True])
def test_invalid_text_change_expires_exact_focus_even_when_numeric_value_stays_nan(name_kind, canonical):
    rows = [{"name": "A", "n_ed_kn": "bad"}]
    if name_kind == "ambiguous":
        rows.append({"name": "a"})
    elif name_kind == "unnamed":
        rows[0]["name"] = ""
    key = load_cases.PLASTIC_TABLE_KEY
    original = load_cases.normalise_table(rows, key) if canonical else rows
    issue = next(issue for issue in _issues(original) if issue.message.code == "PLASTIC-N-ED")
    location = issue.target.case_location
    assert input_issues.resolve_case_location(location, original, None) == 0
    revised = copy.deepcopy(rows)
    revised[0]["n_ed_kn"] = "worse"
    current = load_cases.normalise_table(revised, key) if canonical else revised
    assert input_issues.resolve_case_location(location, current, None) is None
    new_issue = next(issue for issue in _issues(current) if issue.message.code == "PLASTIC-N-ED")
    assert new_issue.target.case_location.row_digest != location.row_digest
    assert new_issue.target.case_location.tables_digest != location.tables_digest
    assert input_issues.resolve_case_location(new_issue.target.case_location, current, None) == 0
