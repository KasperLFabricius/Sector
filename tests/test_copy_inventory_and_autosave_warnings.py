"""Preserve independent labels and recovery warning destinations."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import manual_information_architecture as ia
from tools import audit_user_copy


ROOT = Path(__file__).resolve().parent.parent


def _inventory(tmp_path, monkeypatch, source):
    path = tmp_path / "copy_example.py"
    path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(audit_user_copy, "ROOT", tmp_path)
    return audit_user_copy.inventory_file(path)


def test_literal_labels_are_individual_surfaces(tmp_path, monkeypatch):
    rows = _inventory(tmp_path, monkeypatch, '''
def example():
    labels = {"force": "Applied axial force", "moment": "Applied moment"}
    return labels
''')
    assert [(row["surface"], row["text"]) for row in rows] == [
        ("assigned_labels[force]", "Applied axial force"),
        ("assigned_labels[moment]", "Applied moment"),
    ]


def test_long_individual_label_remains_visible_to_word_limit(tmp_path, monkeypatch):
    text = " ".join(["quantity"] * 51)
    rows = _inventory(tmp_path, monkeypatch, f"def example():\n    labels = {{'force': {text!r}}}\n")
    assert len(rows) == 1
    assert rows[0]["words"] == 51
    assert rows[0]["text"] == text


def test_dynamic_label_map_keeps_existing_aggregate_control(tmp_path, monkeypatch):
    text = " ".join(["quantity"] * 51)
    rows = _inventory(tmp_path, monkeypatch, f"def example():\n    labels = {{'Force (N)': {text!r}, 'Other': supplied_label}}\n")
    assert len(rows) == 1
    assert rows[0]["surface"] == "assigned_labels"
    assert rows[0]["words"] > 50


def test_all_overview_label_values_remain_in_inventory():
    path = ROOT / "app" / "sector_app.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_ui_summary_quantity")
    mapping = next(node.value for node in ast.walk(function)
                   if isinstance(node, ast.Assign) and any(
                       isinstance(target, ast.Name) and target.id == "labels"
                       for target in node.targets))
    values = ast.literal_eval(mapping)
    rows = [row for row in audit_user_copy.inventory_file(path)
            if function.lineno <= row["line"] <= function.end_lineno]
    actual = {row["surface"]: row["text"] for row in rows}
    assert len(values) == 46
    assert actual == {f"assigned_labels[{key}]": value for key, value in values.items()}


@pytest.mark.parametrize("state,expected", [
    ({"_autosave_recovery_blocked": "Protected recovery file."}, "Protected recovery file."),
    ({"_autosave_write_notice": "Write failed."}, "Write failed."),
    ({"_autosave_recovery_blocked": "Protected.", "_autosave_write_notice": "Write failed."}, "Protected."),
    ({}, None),
])
def test_autosave_panel_preserves_notice_and_registered_route(state, expected):
    before = dict(state)
    tree = ast.parse((ROOT / "app" / "sector_app.py").read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"_manual_warning", "_autosave_panel"}]
    warnings = []
    routes = []
    def reference(key):
        routes.append(key)
        return ia.warning_reference(key)
    namespace = {
        "st": SimpleNamespace(session_state=state),
        "manual_ia": SimpleNamespace(warning_reference=reference),
        "_seeded_checkbox": lambda *args, **kwargs: True,
        "_seeded_number": lambda *args, **kwargs: None,
        "_reset_autosave_clock": lambda: None,
        "_AUTOSAVE_DEFAULT_MIN": 2,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "autosave-panel", "exec"), namespace)
    namespace["_autosave_panel"](SimpleNamespace(warning=warnings.append, caption=lambda value: None))
    assert warnings == ([] if expected is None else [expected])
    assert routes == ([] if expected is None else ["autosave-recovery"])
    assert state == before


def test_recovery_guidance_preserves_distinct_conditions():
    reference = ia.warning_reference("autosave-recovery")
    assert "another" in reference.cause.lower()
    assert "cannot be read" in reference.cause
    assert "cannot be written" in reference.cause
    assert "check folder access" in reference.correction
    assert "Download project" in reference.correction
    assert "close other sessions and restart Sector" in reference.correction
    assert "Keep an unreadable recovery file" in reference.correction
    assert all(len(text.split()) <= 50 for text in (
        reference.symptom, reference.cause, reference.correction))
    with pytest.raises(ValueError, match="unknown manual warning reference"):
        ia.warning_reference("autosave-recovery<script>")
