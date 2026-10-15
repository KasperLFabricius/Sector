import copy

from app import result_workspace as workspace


def row(case, status="PASS"):
    return {"overview_key": "shear:x", "family": "plastic", "case": case,
            "view": "Shear", "check": "Shear x", "status": status,
            "result": "0.0", "criterion": "1.0"}


def test_selection_tracks_identity_through_reordering_and_changed_values():
    rows = [row("A"), row("B", "FAIL")]
    selected = workspace.identity(rows[1])
    updated = [dict(rows[1], result="0.75", status="PASS"), rows[0]]
    assert workspace.reconcile_selection(updated, selected) == 0
    assert workspace.table_key(rows, "All checks") != workspace.table_key(updated, "All checks")
    assert workspace.reconcile_selection([], selected) is None


def test_filters_preserve_exact_records_and_assessment_meaning():
    rows = [row("A"), row("B", "NOT ASSESSED"), row("C", "FAIL"),
            row("D", "CALCULATED - NO LIMIT COMPARISON"), row("E", "STALE")]
    before = copy.deepcopy(rows)
    assert [r["case"] for r in workspace.filter_rows(rows, "Needs attention")] == ["B", "C", "D", "E"]
    assert workspace.filter_rows(rows, "Calculated outputs") == [rows[3]]
    assert rows == before
    assert workspace.filter_rows(rows, "All checks")[0] is rows[0]


def test_ambiguous_selection_and_filter_table_keys_are_bounded():
    rows = [row("A"), row("A")]
    assert workspace.reconcile_selection(rows, workspace.identity(rows[0])) == 0
    assert workspace.table_key(rows, "All checks") != workspace.table_key(rows, "Needs attention")
    assert workspace.input_destination(rows[0]) == ("settings", "Shear / torsion / M-V-T", "Shear")
    assert workspace.input_destination(dict(rows[0], view="Fatigue Results")) == ("settings", "Fatigue", None)
