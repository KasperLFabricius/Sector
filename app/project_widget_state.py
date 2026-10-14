"""Restore project data while Streamlit retains ownership of event widgets."""
from __future__ import annotations

import re

BUTTON_KEYS = frozenset({
    "calculate", "_context_full_manual", "open_manual", "open_qs",
    "_actions_fatigue_settings",
    "fatigue_catalog_add_mild", "fatigue_catalog_add_tendon",
    "fatigue_catalog_duplicate", "fatigue_catalog_delete", "gen_report",
    "qs_back", "qs_apply", "clear_pts", "add_void", "rem_void", "auto_all_btn",
    "conc_strain_auto", "sls_fctm_auto", "conc_Ec_auto",
    "_apply_report_presentation_preset", "undo_clear_pts", "_preview_generated_report",
    "confirm_clear_pts", "cancel_clear_pts", "slab_density_use_explicit",
    "overview_open_result", "overview_related_inputs", "overview_status_help",
    "_close_report_preview", "initialise_inputs", "manual_gen_pdf",
    "manual_dl_pdf", "manual_dl_html", "manual_close",
})
_BUTTON_PATTERNS = (
    r"(?:mild|prestress)_catalog_(?:add|duplicate|delete)",
    r"_ed_(?:bars|tendons)_bulk_apply",
    r"analysis-input-issue-[0-9]+-[a-zA-Z0-9_-]+",
    r"mvt_(?:checks|combined)_prerequisite_[0-9]+",
    r"_actions_(?:add|duplicate|delete|template|paste_apply)::(?:plastic|elastic)_cases_base",
    r"_actions_cell_edit::(?:plastic|elastic)_cases_base::[0-9]+::[^:]+::[a-f0-9]+::apply",
)
EDITOR_TABLES = {
    "plastic_cases_editor": "plastic_cases_base",
    "elastic_cases_editor": "elastic_cases_base",
    "fatigue_spectrum_editor": "fatigue_spectrum_base",
}


def is_event_widget(key):
    """Match event widgets exactly, including only the Apply suffix of cell edits."""
    return isinstance(key, str) and (
        key in BUTTON_KEYS
        or any(re.fullmatch(pattern, key) for pattern in _BUTTON_PATTERNS)
        or re.fullmatch(r"project_upload(?:_[0-9]+)?", key) is not None
    )


def fold_editor_patch(frame, patch):
    """Fold a native editor transaction into a new row seed without rounding.

    Native action and spectrum editors use text and Boolean columns with a hidden
    RangeIndex. Edits precede deletions and additions, as in the native editor.
    """
    if not isinstance(patch, dict):
        raise ValueError("The recovery editor transaction must be a dictionary.")
    records = frame.to_dict("records")
    columns = tuple(frame.columns)
    edits = patch.get("edited_rows", {})
    deleted = patch.get("deleted_rows", [])
    added = patch.get("added_rows", [])
    if not isinstance(edits, dict) or not isinstance(deleted, list) or not isinstance(added, list):
        raise ValueError("The recovery editor transaction has invalid row operations.")
    for raw_position, cells in edits.items():
        if isinstance(raw_position, bool) or not str(raw_position).isdecimal():
            raise ValueError("The recovery editor row position is invalid.")
        position = int(raw_position)
        if position >= len(records) or not isinstance(cells, dict) or not set(cells) <= set(columns):
            raise ValueError("The recovery editor cell position is invalid.")
        records[position].update(cells)
    if any(type(position) is not int or not 0 <= position < len(records) for position in deleted):
        raise ValueError("The recovery editor deleted row is invalid.")
    records = [row for position, row in enumerate(records) if position not in deleted]
    for cells in added:
        if not isinstance(cells, dict) or not set(cells) <= set(columns):
            raise ValueError("The recovery editor added row is invalid.")
        records.append({column: cells.get(column) for column in columns})
    # The existing canonical parser owns numeric parsing and invalid-cell ledgers.
    return records


def recovery_values(snapshot):
    """Keep durable state and fold native patches before remounting their widgets."""
    restored = {key: value for key, value in snapshot.items()
                if not is_event_widget(key) and key not in EDITOR_TABLES}
    for editor, table in EDITOR_TABLES.items():
        patch = snapshot.get(editor)
        seed_key = f"_{table}_editor_seed"
        if editor not in snapshot:
            continue
        if not isinstance(patch, dict):
            raise ValueError("The recovery editor transaction must be a dictionary.")
        if set(patch) - {"edited_rows", "deleted_rows", "added_rows"}:
            raise ValueError("The recovery editor transaction has unknown operations.")
        if (not isinstance(patch.get("edited_rows", {}), dict)
                or not isinstance(patch.get("deleted_rows", []), list)
                or not isinstance(patch.get("added_rows", []), list)):
            raise ValueError("The recovery editor transaction has invalid row operations.")
        has_operations = any(patch.get(key) for key in ("edited_rows", "deleted_rows", "added_rows"))
        if seed_key not in snapshot and not has_operations:
            continue
        import pandas as pd
        if not isinstance(snapshot.get(seed_key), pd.DataFrame):
            raise ValueError("The recovery editor row seed is unavailable.")
        if table == "fatigue_spectrum_base":
            import fatigue_inputs
            if tuple(snapshot[seed_key].columns) != tuple(fatigue_inputs.SPECTRUM_COLUMNS):
                raise ValueError("The recovery spectrum row seed is incomplete.")
            frame = fatigue_inputs.editor_spectrum_table(snapshot[seed_key])
            canonical = fatigue_inputs.normalise_spectrum_table(fold_editor_patch(frame, patch))
        else:
            import load_cases
            if tuple(snapshot[seed_key].columns) != tuple(load_cases.TABLE_COLUMNS[table]):
                raise ValueError("The recovery action row seed is incomplete.")
            frame = load_cases.editor_table(snapshot[seed_key], table)
            canonical = load_cases.normalise_table(fold_editor_patch(frame, patch), table)
        restored[table] = canonical
        restored[seed_key] = canonical.copy(deep=True)
    return restored


def commit_editor_values(state, editors=None):
    """Commit native action edits while retaining their mounted widget seeds.

    Streamlit installs all incoming widget values before callbacks. A tab or
    page callback can therefore commit the same transaction as its editor
    callback. Each replay uses the immutable seed, so additions and deletions
    remain idempotent. Validate every selected transaction before any write.
    """
    selected = tuple(EDITOR_TABLES if editors is None else editors)
    snapshot = {}
    for editor in selected:
        if editor not in EDITOR_TABLES:
            raise ValueError("The action editor is unknown.")
        if editor not in state:
            continue
        table = EDITOR_TABLES[editor]
        snapshot[editor] = state[editor]
        seed_key = f"_{table}_editor_seed"
        if seed_key in state:
            snapshot[seed_key] = state[seed_key]
    prepared = recovery_values(snapshot)
    for editor in selected:
        table = EDITOR_TABLES[editor]
        if table in prepared:
            state[table] = prepared[table]

