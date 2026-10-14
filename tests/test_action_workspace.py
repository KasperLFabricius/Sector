"""Actions transactions preserve numbers, invalid cells and case authority."""

from __future__ import annotations

import copy
import pathlib
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))

from app import action_workspace as actions
from app import load_cases as cases
from app.table_field_definitions import decimal_issue_ledger

P, E = cases.CASE_TABLE_KEYS


def tables():
    return {
        P: cases.normalise_table([
            {"name": "ULS 1", "mx_ed_knm": 1.2345678901234567,
             "check_minimum_reinforcement": True},
            {"name": "ULS 2", "my_ed_knm": "bad number"},
        ], P),
        E: cases.normalise_table([{"name": "SLS 1", "n_long_ed_kn": -15.125,
                                   "n_short_ed_kn": 2.375}], E),
    }


def test_add_unique_across_both_families_and_clears_stale_declaration():
    data = tables()
    data[E].loc[0, "name"] = "Plastic case"
    updated, mapping, selected = actions.edit_cases(
        data, {"Plastic case 2": {"design_basis": "old"}}, table=P, operation="add")
    assert updated[P].iloc[selected]["name"] == "Plastic case 2"
    assert "Plastic case 2" not in mapping
    assert not updated[P].iloc[selected]["check_minimum_reinforcement"]
    pd.testing.assert_frame_equal(data[E], updated[E])


def test_duplicate_preserves_full_precision_and_resets_declarations():
    data = tables()
    authorities = {"ULS 1": {"basis": "equilibrium"}, "ULS 1 copy": {"basis": "old"}}
    updated, mapping, selected = actions.edit_cases(data, authorities,
                                                   table=P, operation="duplicate", row=0)
    assert updated[P].iloc[selected]["mx_ed_knm"] == data[P].iloc[0]["mx_ed_knm"]
    assert not updated[P].iloc[selected]["check_minimum_reinforcement"]
    assert mapping == {"ULS 1": {"basis": "equilibrium"}}
    assert authorities["ULS 1 copy"] == {"basis": "old"}
    assert len(data[P]) == 2


def test_duplicate_invalid_cell_keeps_original_text_at_both_positions():
    updated, _, selected = actions.edit_cases(tables(), {}, table=P, operation="duplicate", row=1)
    ledger = decimal_issue_ledger(updated[P].attrs)
    assert ledger[(1, "my_ed_knm")] == "bad number"
    assert ledger[(selected, "my_ed_knm")] == "bad number"


def test_delete_shifts_invalid_ledger_and_prunes_only_removed_authority():
    authorities = {"ULS 1": {"basis": "one"}, "ULS 2": {"basis": "two"}}
    updated, mapping, selected = actions.edit_cases(tables(), authorities,
                                                   table=P, operation="delete", row=0)
    assert selected == 0
    assert decimal_issue_ledger(updated[P].attrs) == {(0, "my_ed_knm"): "bad number"}
    assert mapping == {"ULS 2": {"basis": "two"}}


def test_delete_duplicate_name_does_not_drop_surviving_authority():
    data = tables()
    data[P].loc[1, "name"] = "ULS 1"
    _, mapping, _ = actions.edit_cases(data, {"ULS 1": {"basis": "one"}},
                                       table=P, operation="delete", row=0)
    assert "ULS 1" in mapping


@pytest.mark.parametrize("row", [-1, 100, None, True])
def test_invalid_selection_fails_without_mutation(row):
    data = tables()
    digest = actions.table_digest(data)
    with pytest.raises(ValueError):
        actions.edit_cases(data, {}, table=P, operation="delete", row=row)
    assert actions.table_digest(data) == digest


def test_stale_command_expires_after_any_input_change():
    data = tables()
    digest = actions.table_digest(data)
    data[E].loc[0, "n_short_ed_kn"] = 3.0
    with pytest.raises(ValueError, match="changed"):
        actions.edit_cases(data, {}, table=P, operation="delete", row=0, expected_digest=digest)


@pytest.mark.parametrize("text", [
    "name\tn_ed_kn\nPasted\t-1,23456789012345\n",
    "name;n_ed_kn\nPasted;-1,23456789012345\n",
    'name,n_ed_kn\nPasted,"-1,23456789012345"\n',
])
def test_spreadsheet_decimals_use_canonical_parser(text):
    result = actions.prepare_paste(text, P)
    assert result.iloc[0]["n_ed_kn"] == -1.23456789012345


@pytest.mark.parametrize("text", [
    "name\tn_ed_kn\n", "name\tn_ed_kn\nCase\t1\textra", "name\tunknown\nCase\t1",
    "name\tname\nCase\tOther", "description\tn_ed_kn\nCase\t1",
    "name\tcheck_minimum_reinforcement\nCase\tperhaps",
])
def test_malformed_paste_is_rejected(text):
    with pytest.raises(ValueError):
        actions.prepare_paste(text, P)


def test_preview_retains_invalid_text_and_blank_zero():
    frame = actions.prepare_paste("name\tn_ed_kn\tmx_ed_knm\nCase\twrong\t\n", P)
    assert decimal_issue_ledger(frame.attrs) == {(0, "n_ed_kn"): "wrong"}
    assert frame.iloc[0]["mx_ed_knm"] == 0.0


def test_invalid_preview_cannot_be_committed():
    data = {P: cases.empty_table(P), E: cases.empty_table(E)}
    with pytest.raises(ValueError):
        actions.edit_cases(data, {}, table=P, operation="paste", text="name\tn_ed_kn\nCase\twrong")
    assert data[P].empty


def test_duplicate_name_across_families_blocks_paste():
    data = {P: cases.empty_table(P), E: cases.normalise_table([{"name": "Case"}], E)}
    with pytest.raises(ValueError):
        actions.edit_cases(data, {}, table=P, operation="paste", text="name\tn_ed_kn\ncase\t1")


def test_elastic_duplicate_retains_increment_and_crack_width_request():
    data = tables()
    data[E].loc[0, "calculate_crack_width"] = True
    result, _, selected = actions.edit_cases(data, {}, table=E, operation="duplicate", row=0)
    row = result[E].iloc[selected]
    assert row["n_long_ed_kn"] == -15.125
    assert row["n_short_ed_kn"] == 2.375
    assert row["calculate_crack_width"]


def test_paste_appends_and_resets_stale_authority_without_changing_existing():
    data = {P: cases.normalise_table([{"name": "Original", "n_ed_kn": -16.25}], P), E: cases.empty_table(E)}
    result, mapping, selected = actions.edit_cases(
        data, {"Pasted": {"basis": "stale"}, "Original": {"basis": "valid"}},
        table=P, operation="paste", text="name\tn_ed_kn\nPasted\t1.000000000000001")
    assert result[P].iloc[0]["n_ed_kn"] == -16.25
    assert result[P].iloc[selected]["n_ed_kn"] == 1.000000000000001
    assert mapping == {"Original": {"basis": "valid"}}


def test_queue_then_consume_resets_editor_before_render_and_updates_selection():
    state = tables()
    state[actions.AUTHORITY_KEY] = {"ULS 1": {"basis": "valid"}}
    digest = actions.table_digest(state)
    calls = []
    actions.queue_command(state, {"table": P, "operation": "duplicate", "row": 0,
                                  "expected_digest": digest}, lambda: calls.append("snapshot"))
    def reseed(key, frame):
        calls.append("reseed")
        state[key] = frame
    actions.consume_command(state, reseed)
    assert calls == ["snapshot", "reseed"]
    assert state[actions.selection_key(P)] == 2
    assert state[actions.NOTICE_KEY][0]
    assert actions.COMMAND_KEY not in state


def test_failed_transaction_leaves_tables_and_authority_unchanged():
    state = tables()
    before = actions.table_digest(state)
    state[actions.AUTHORITY_KEY] = {"ULS 1": {"basis": "valid"}}
    authorities = copy.deepcopy(state[actions.AUTHORITY_KEY])
    state[actions.COMMAND_KEY] = {"table": P, "operation": "delete", "row": 0,
                                  "expected_digest": "stale"}
    actions.consume_command(state, lambda *_: pytest.fail("must not reseed"))
    assert actions.table_digest(state) == before
    assert state[actions.AUTHORITY_KEY] == authorities
    assert not state[actions.NOTICE_KEY][0]


def exact_focus(data):
    errors = cases.validation_errors(data[P], data[E])
    issues = actions.input_issues.case_issues(errors, plastic=data[P], elastic=data[E])
    return next(issue.target.case_location for issue in issues if issue.target.case_location)


def test_exact_focus_selects_family_and_physical_row_without_input_changes():
    state = tables()
    digest = actions.table_digest(state)
    location = exact_focus(state)
    state.update({"_input_issue_focus": {"case_location": location},
                  actions.FAMILY_KEY: "Elastic", "_result_filter": "attention"})
    assert actions.resolve_focus(state) == (location, 1)
    assert state[actions.FAMILY_KEY] == "Plastic"
    assert state[actions.selection_key(P)] == 1
    assert actions.table_digest(state) == digest
    assert state["_result_filter"] == "attention"


def test_stale_focus_preserves_existing_selection_and_family():
    state = tables()
    location = exact_focus(state)
    state[P] = cases.normalise_table([{"name": "Replacement"}], P)
    state.update({"_input_issue_focus": {"case_location": location},
                  actions.FAMILY_KEY: "Elastic", actions.selection_key(E): 0})
    assert actions.resolve_focus(state) is None
    assert state[actions.FAMILY_KEY] == "Elastic"
    assert state[actions.selection_key(E)] == 0
    assert actions.FOCUS_KEY not in state


def test_focus_does_not_force_family_again_after_deliberate_navigation():
    state = tables()
    state["_input_issue_focus"] = {"case_location": exact_focus(state)}
    assert actions.resolve_focus(state)
    state[actions.FAMILY_KEY] = "Elastic"
    assert actions.resolve_focus(state)
    assert state[actions.FAMILY_KEY] == "Elastic"


def test_focus_is_retained_for_field_edit_rerun_and_expires_after_correction():
    state = tables()
    state["_input_issue_focus"] = {"case_location": exact_focus(state)}
    actions.resolve_focus(state)
    state.pop("_input_issue_focus")
    assert actions.resolve_focus(state)
    result, _, _ = actions.edit_cases(state, {}, table=P, operation="correct", row=1,
                                      column="my_ed_knm", value="12,375")
    state[P] = result[P]
    assert actions.resolve_focus(state) is None
    assert result[P].iloc[1]["my_ed_knm"] == 12.375


def test_cell_correction_changes_exact_cell_and_retains_other_invalid_values():
    data = tables()
    result, _, _ = actions.edit_cases(data, {}, table=E, operation="correct", row=0,
                                      column="n_short_ed_kn", value="-1.2345678901234567")
    assert result[E].iloc[0]["n_short_ed_kn"] == -1.2345678901234567
    assert result[E].iloc[0]["n_long_ed_kn"] == -15.125
    assert decimal_issue_ledger(result[P].attrs) == decimal_issue_ledger(data[P].attrs)


def test_duplicate_name_correction_preserves_existing_engineering_declaration():
    data = tables()
    mapping = {"ULS 1": {"basis": "existing"}, "ULS 2": {"basis": "existing two"}}
    result, after, _ = actions.edit_cases(data, mapping, table=P, operation="correct", row=1,
                                         column="name", value="ULS 1")
    assert after == mapping
    assert cases.validation_errors(result[P], result[E])


def test_field_apply_reads_latest_widget_event():
    state = tables()
    state["cell_widget"] = "9,25"
    command = {"table": E, "operation": "correct", "row": 0,
               "column": "n_short_ed_kn", "value": "old"}
    actions.queue_cell_correction(state, command, "cell_widget")
    assert state[actions.COMMAND_KEY]["value"] == "9,25"


def test_paste_edit_before_apply_requires_updated_preview():
    state = tables()
    state[f"_actions_paste::{P}"] = "new text"
    actions.queue_command(state, {"table": P, "operation": "paste", "text": "old text"})
    assert actions.COMMAND_KEY not in state
    assert not state[actions.NOTICE_KEY][0]


def test_consumed_transaction_is_journalled_until_complete_render():
    state = tables()
    original = copy.deepcopy(state)
    state[actions.AUTHORITY_KEY] = {"ULS 1": {"basis": "old"}}
    state[actions.COMMAND_KEY] = {"table": P, "operation": "delete", "row": 0}
    actions.consume_command(state, lambda key, frame: state.update({key: frame}))
    journal = copy.deepcopy(state["_pending_input_events"])
    # Simulate restoring the old completed input snapshot after interruption.
    state[P] = original[P]
    state[actions.AUTHORITY_KEY] = {"ULS 1": {"basis": "old"}}
    state.update(journal)
    assert len(state[P]) == 1
    assert state[P].iloc[0]["name"] == "ULS 2"
    assert "ULS 1" not in state[actions.AUTHORITY_KEY]
    assert decimal_issue_ledger(state[P].attrs) == {(0, "my_ed_knm"): "bad number"}


def test_selected_unique_case_survives_reorder_and_widget_cleanup():
    state = tables()
    state[actions.selection_key(P)] = 0
    actions.retain_selection(state, P)
    state[P] = cases.normalise_table(cases.editor_table(state[P], P).iloc[::-1].reset_index(drop=True), P)
    state.pop(actions.selection_key(P))
    actions.restore_selection(state, P)
    assert state[actions.selection_key(P)] == 1
    assert state[P].iloc[1]["name"] == "ULS 1"


def test_selected_case_identity_expires_after_duplicate_name_or_delete():
    state = tables()
    state[actions.selection_key(P)] = 0
    actions.retain_selection(state, P)
    state[P].loc[1, "name"] = "uls 1"
    actions.restore_selection(state, P)
    assert state[actions.selection_key(P)] is None


def test_new_issue_request_refocuses_same_case_after_user_navigation():
    state = tables()
    location = exact_focus(state)
    state["_input_issue_focus"] = {"case_location": location, "request_id": 1}
    actions.resolve_focus(state)
    state[actions.FAMILY_KEY] = "Elastic"
    state["_input_issue_focus"] = {"case_location": location, "request_id": 2}
    actions.resolve_focus(state)
    assert state[actions.FAMILY_KEY] == "Plastic"
    assert state[actions.selection_key(P)] == 1
