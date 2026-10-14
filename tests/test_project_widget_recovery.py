"""Project replacement keeps durable values and recovers native edit transactions."""
import copy

import pandas as pd
import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import project_widget_state as recovery
import load_cases
import fatigue_inputs


@pytest.mark.parametrize("key", sorted(recovery.BUTTON_KEYS) + [
    "mild_catalog_add", "prestress_catalog_delete", "_ed_bars_bulk_apply",
    "_ed_tendons_bulk_apply", "analysis-input-issue-2-case_missing",
    "mvt_checks_prerequisite_0", "mvt_combined_prerequisite_3",
    "_actions_add::plastic_cases_base", "_actions_duplicate::elastic_cases_base",
    "_actions_delete::plastic_cases_base", "_actions_template::elastic_cases_base",
    "_actions_paste_apply::elastic_cases_base",
    "_actions_cell_edit::plastic_cases_base::2::n_ed_kn::abc123::apply",
    "project_upload", "project_upload_15",
])
@pytest.mark.parametrize("pulse", [False, True])
def test_all_event_widget_families_are_not_reassigned(key, pulse):
    assert recovery.is_event_widget(key)
    restored = recovery.recovery_values({key: pulse, "conc_fck": 41.0})
    assert restored == {"conc_fck": 41.0}


def test_durable_values_retain_identity_and_exact_types():
    snapshot = {
        "fatigue_on": False, "_manual_open": True,
        "_workflow_calculate_request": {"generation": 4},
        "_workflow_page": "section", "_next_main_page": "Inputs",
        "_actions_selected::plastic_cases_base": 0,
        "_actions_cell_edit::plastic_cases_base::2::n_ed_kn::abc123": "0.10000000000000003",
        "_actions_paste::elastic_cases_base": "A\t0.1",
        "_project_upload_content_identity": "old-content",
        "_project_upload_widget_generation": 3,
        "ed_bars": {"rows": [{"area_mm2": 100.00000000000003}], "version": 4},
        "ed_bars_ver": 4,
        "bars_base": pd.DataFrame({"id": pd.Series(["B1"], dtype="object")}),
        "report_buffer": b"%PDF-old", "results": {"n": 0.12345678901234567},
    }
    restored = recovery.recovery_values(snapshot)
    assert set(restored) == set(snapshot)
    assert all(restored[key] is value for key, value in snapshot.items())


@pytest.mark.parametrize("table", load_cases.CASE_TABLE_KEYS)
def test_native_case_patch_is_folded_once_with_precision_invalid_cells_and_row_order(table):
    seed = load_cases.normalise_table([
        {"name": "first", "n_ed_kn": 0.12345678901234567},
        {"name": "deleted", "n_ed_kn": 9.0},
    ], table)
    numeric = load_cases.NUMERIC_COLUMNS[table][0]
    seed.loc[0, numeric] = 0.12345678901234567
    editor = table.replace("_base", "_editor")
    patch = {"edited_rows": {"0": {numeric: "invalid", "description": "retain me"}},
             "deleted_rows": [1], "added_rows": [{"name": "added", numeric: "0.10000000000000003"}]}
    seed_key = f"_{table}_editor_seed"
    snapshot = {table: seed.copy(deep=True), seed_key: seed, editor: patch,
                "_torsion_case_authorities": {"first": {"scope": True}}}
    before = copy.deepcopy(snapshot)
    recovered = recovery.recovery_values(snapshot)
    assert editor not in recovered
    assert recovered[table]["name"].tolist() == ["first", "added"]
    display = load_cases.editor_table(recovered[table], table)
    assert display.loc[0, numeric] == "invalid"
    assert display.loc[1, numeric] == "0.10000000000000003"
    assert display.loc[0, "description"] == "retain me"
    pd.testing.assert_frame_equal(recovered[table], recovered[seed_key])
    pd.testing.assert_frame_equal(snapshot[seed_key], before[seed_key])
    assert snapshot[editor] == before[editor]
    # A rerender starts from the folded seed with a fresh, empty widget patch.
    again = recovery.recovery_values({**recovered, editor: {"edited_rows": {}, "deleted_rows": [], "added_rows": []}})
    pd.testing.assert_frame_equal(again[table], recovered[table])
    assert recovered["_torsion_case_authorities"] is snapshot["_torsion_case_authorities"]


def test_fatigue_native_patch_preserves_invalid_ledger():
    table = fatigue_inputs.SPECTRUM_TABLE_KEY
    seed = fatigue_inputs.normalise_spectrum_table([{"spectrum": "Traffic", "name": "F1", "cycles": 100.0}])
    recovered = recovery.recovery_values({table: seed, f"_{table}_editor_seed": seed,
        "fatigue_spectrum_editor": {"edited_rows": {"0": {"cycles": "1,2,3"}}, "added_rows": [], "deleted_rows": []}})
    assert fatigue_inputs.editor_spectrum_table(recovered[table]).loc[0, "cycles"] == "1,2,3"
    assert "fatigue_spectrum_editor" not in recovered


@pytest.mark.parametrize("patch", [
    {"edited_rows": {"8": {"name": "wrong"}}},
    {"edited_rows": {"0": {"unknown": "wrong"}}},
    {"deleted_rows": [-1]}, {"added_rows": [{"unknown": "wrong"}]},
    {"edited_rows": {True: {"name": "wrong"}}},
])
def test_invalid_native_transaction_fails_before_mutating_durable_values(patch):
    frame = pd.DataFrame({"name": ["original"]})
    before = frame.copy(deep=True)
    with pytest.raises(ValueError):
        recovery.fold_editor_patch(frame, patch)
    pd.testing.assert_frame_equal(frame, before)
