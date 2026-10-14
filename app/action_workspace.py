"""Lossless action-table management and presentation-only family navigation."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
from collections.abc import Mapping

import pandas as pd
from input_stage_host import stateful_input_tabs

from app import input_issues, load_cases
from app.table_field_definitions import field_definition

FAMILY_KEY = "_actions_family"
FAMILIES = ("Plastic", "Elastic")
ACTION_TABS = (*FAMILIES, "Fatigue")
TABLES = dict(zip(FAMILIES, load_cases.CASE_TABLE_KEYS))
COMMAND_KEY = "_actions_pending_command"
NOTICE_KEY = "_actions_notice"
AUTHORITY_KEY = "torsion_case_authorities"
FOCUS_KEY = "_actions_cell_focus"


def selection_key(table):
    return f"_actions_selected::{table}"


def retain_selection(state, table, on_change=None):
    """Remember a unique case identity separately from its display row."""
    row = state.get(selection_key(table))
    frame = load_cases.normalise_table(state.get(table), table)
    name = str(frame.iloc[row][load_cases.NAME]) if type(row) is int and 0 <= row < len(frame) else None
    all_names = [str(value).casefold() for key in load_cases.CASE_TABLE_KEYS
                 for value in load_cases.normalise_table(state.get(key), key)[load_cases.NAME]]
    unique = bool(name) and all_names.count(name.casefold()) == 1
    state[f"_actions_selection_identity::{table}"] = {
        "name": name if unique else None, "digest": table_digest(state),
    }
    if on_change is not None:
        on_change()


def restore_selection(state, table):
    """Keep the selected unique case across reordered table rows."""
    saved = state.get(f"_actions_selection_identity::{table}")
    if not isinstance(saved, Mapping):
        return
    name = saved.get("name")
    if name:
        matches = [(key, row) for key in load_cases.CASE_TABLE_KEYS
                   for row, current in enumerate(load_cases.normalise_table(state.get(key), key)[load_cases.NAME])
                   if str(current).casefold() == name.casefold()]
        state[selection_key(table)] = matches[0][1] if len(matches) == 1 and matches[0][0] == table else None
    elif saved.get("digest") != table_digest(state):
        state[selection_key(table)] = None


def table_digest(tables):
    """Bind an operation to the exact visible values, including invalid text."""
    payload = {key: load_cases.editor_table(tables.get(key), key).to_dict("records")
               for key in load_cases.CASE_TABLE_KEYS}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def unique_name(tables, stem):
    names = {str(name).strip().casefold()
             for key in load_cases.CASE_TABLE_KEYS
             for name in load_cases.normalise_table(tables.get(key), key)[load_cases.NAME]}
    candidate, counter = stem, 2
    while candidate.casefold() in names:
        candidate = f"{stem} {counter}"
        counter += 1
    return candidate


def prepare_paste(text, table):
    """Read a headered spreadsheet block through the canonical decimal parser."""
    if table not in load_cases.CASE_TABLE_KEYS:
        raise ValueError("Select a supported action family.")
    text = str(text).lstrip("\ufeff")
    delimiter = "\t" if "\t" in text else ";" if ";" in text else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter, strict=True))
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise ValueError("Paste a header row and at least one case.")
    header = [cell.strip() for cell in rows[0]]
    if len(header) != len(set(header)):
        raise ValueError("Use each column heading once.")
    unknown = set(header) - set(load_cases.TABLE_COLUMNS[table])
    if unknown or load_cases.NAME not in header:
        raise ValueError("Use the template column headings, including name.")
    if any(len(row) != len(header) for row in rows[1:]):
        raise ValueError("Each pasted row must have the same number of cells as the header.")
    frame = pd.DataFrame(rows[1:], columns=header)
    for flag in load_cases.FLAG_COLUMNS[table]:
        if flag in frame and any(str(value).strip().casefold() not in
                                 {"", "0", "1", "true", "false", "yes", "no", "on", "off"}
                                 for value in frame[flag]):
            raise ValueError(f"Use true or false in {flag}.")
    return load_cases.normalise_table(frame, table)


def paste_template(table):
    return "\t".join(load_cases.TABLE_COLUMNS[table]) + "\n"


def _join_frames(first, second, table):
    # Convert tagged invalid cells back to their retained text before reindexing.
    left = load_cases.editor_table(first, table)
    right = load_cases.editor_table(second, table)
    return load_cases.normalise_table(pd.concat([left, right], ignore_index=True), table)


def edit_cases(tables, authorities, *, table, operation, row=None,
               text=None, expected_digest=None, column=None, value=None):
    """Return detached tables, declarations and selection for one explicit action."""
    if table not in load_cases.CASE_TABLE_KEYS:
        raise ValueError("Select a supported action family.")
    if expected_digest is not None and table_digest(tables) != expected_digest:
        raise ValueError("The action tables changed. Review them and repeat the command.")
    result = {key: load_cases.normalise_table(tables.get(key), key)
              for key in load_cases.CASE_TABLE_KEYS}
    mapping = copy.deepcopy(authorities) if isinstance(authorities, Mapping) else {}
    frame = load_cases.editor_table(result[table], table)
    if operation in {"duplicate", "delete", "correct"} and (type(row) is not int or not 0 <= row < len(frame)):
        raise ValueError("Select an existing case row.")
    if operation == "add":
        name = unique_name(result, f"{next(f for f, t in TABLES.items() if t == table)} case")
        added = load_cases.normalise_table([{load_cases.NAME: name}], table)
        result[table] = _join_frames(result[table], added, table)
        selected = len(frame)
        mapping.pop(name, None)
    elif operation == "duplicate":
        name = unique_name(result, f"{str(frame.iloc[row][load_cases.NAME]).strip() or 'Case'} copy")
        added = frame.iloc[[row]].copy(deep=True)
        added[load_cases.NAME] = name
        if table == load_cases.PLASTIC_TABLE_KEY:
            added["check_minimum_reinforcement"] = False
        result[table] = _join_frames(result[table], added, table)
        selected = len(frame)
        mapping.pop(name, None)
    elif operation == "delete":
        name = str(frame.iloc[row][load_cases.NAME])
        result[table] = load_cases.normalise_table(frame.drop(index=row).reset_index(drop=True), table)
        selected = min(row, len(result[table]) - 1) if len(result[table]) else None
        if table == load_cases.PLASTIC_TABLE_KEY and name not in set(result[table][load_cases.NAME]):
            mapping.pop(name, None)
    elif operation == "correct":
        if column not in load_cases.TABLE_COLUMNS[table]:
            raise ValueError("Select an existing action field.")
        old_name = str(frame.iloc[row][load_cases.NAME])
        frame.at[row, column] = value
        result[table] = load_cases.normalise_table(frame, table)
        selected = row
        if column == load_cases.NAME:
            new_name = str(result[table].iloc[row][load_cases.NAME])
            names = [str(name).strip().casefold() for key in load_cases.CASE_TABLE_KEYS
                     for name in load_cases.active_table(result[key], key)[load_cases.NAME]]
            identity_valid = all(names) and len(set(names)) == len(names)
            if new_name != old_name and identity_valid:
                # A renamed case is a new identity until its declarations are reviewed.
                mapping.pop(new_name, None)
                if old_name not in set(result[table][load_cases.NAME]):
                    mapping.pop(old_name, None)
    elif operation == "paste":
        added = prepare_paste(text, table)
        result[table] = _join_frames(result[table], added, table)
        errors = load_cases.validation_errors(result[load_cases.PLASTIC_TABLE_KEY],
                                             result[load_cases.ELASTIC_TABLE_KEY])
        if errors:
            raise ValueError("; ".join(str(error) for error in errors))
        selected = len(frame)
        for name in added[load_cases.NAME]:
            mapping.pop(str(name), None)
    else:
        raise ValueError("Select a supported case command.")
    return result, mapping, selected


def queue_command(state, command, on_change=None):
    if on_change is not None:
        on_change()
    if command.get("operation") == "paste" and state.get(
        f"_actions_paste::{command['table']}", command.get("text")
    ) != command.get("text"):
        state[NOTICE_KEY] = (False, "The pasted text changed. Review the updated preview before appending.")
        return
    state[COMMAND_KEY] = copy.deepcopy(command)


def queue_cell_correction(state, command, widget_key, on_change=None):
    """Read the current widget event, including an edit immediately before Apply."""
    command = dict(command)
    command["value"] = state[widget_key]
    queue_command(state, command, on_change)


def consume_command(state, reseed):
    """Apply a queued transaction before either data-editor widget mounts."""
    command = state.pop(COMMAND_KEY, None)
    if command is None:
        return
    try:
        result, mapping, selected = edit_cases(
            {key: state.get(key) for key in load_cases.CASE_TABLE_KEYS},
            state.get(AUTHORITY_KEY), **command,
        )
    except (ValueError, csv.Error) as exc:
        state[NOTICE_KEY] = (False, str(exc))
        return
    table = command["table"]
    reseed(table, result[table])
    state[AUTHORITY_KEY] = mapping
    state[selection_key(table)] = selected
    retain_selection(state, table)
    pending = dict(state.get("_pending_input_events", {}))
    pending[table] = result[table].copy(deep=True)
    pending[AUTHORITY_KEY] = copy.deepcopy(mapping)
    pending[selection_key(table)] = selected
    state["_pending_input_events"] = pending
    state.pop(FOCUS_KEY, None)
    state[NOTICE_KEY] = (True, "Action table updated. Review the selected case before calculation.")


def resolve_focus(state):
    """Accept typed current cell targets and leave unrelated navigation intact."""
    request = state.get("_input_issue_focus", {})
    incoming = request.get("case_location")
    token = (request.get("request_id"), incoming)
    if incoming is None:
        state.pop("_actions_focus_received", None)
    if incoming is not None and token != state.get("_actions_focus_received"):
        state["_actions_focus_received"] = token
        row = input_issues.resolve_case_location(
            incoming, state.get(load_cases.PLASTIC_TABLE_KEY), state.get(load_cases.ELASTIC_TABLE_KEY))
        if row is None:
            state.pop(FOCUS_KEY, None)
            state["_actions_focus_notice"] = "The issue location changed. Review the current action table."
        else:
            state[FOCUS_KEY] = incoming
            state[FAMILY_KEY] = next(family for family, table in TABLES.items() if table == incoming.table_key)
            state[selection_key(incoming.table_key)] = row
            retain_selection(state, incoming.table_key)
            for mirror in ("_durable_input_scalars", "_pending_input_events"):
                if mirror in state:
                    state[mirror][FAMILY_KEY] = state[FAMILY_KEY]
                    state[mirror][selection_key(incoming.table_key)] = row
    location = state.get(FOCUS_KEY)
    if location is None:
        return None
    row = input_issues.resolve_case_location(
        location, state.get(load_cases.PLASTIC_TABLE_KEY), state.get(load_cases.ELASTIC_TABLE_KEY))
    if row is None:
        state.pop(FOCUS_KEY, None)
        state["_actions_focus_notice"] = "The issue location changed. Review the current action table."
        return None
    return location, row


def focused_editor(host, *, state, resolved, on_change=None):
    """Expose the actual requested cell with its registry definition and unit."""
    if resolved is None or not bool(getattr(host, "open", True)):
        return
    location, row = resolved
    table, column = location.table_key, location.field_key
    frame = load_cases.editor_table(state.get(table), table)
    definition = field_definition(table, column)
    panel = host.container(border=True)
    panel.markdown("**Input issue**")
    panel.text(f"Row {row + 1}: {frame.iloc[row][load_cases.NAME] or '(unnamed case)'}")
    panel.caption(f"Field: {definition.label}. {definition.definition}")
    widget_key = f"_actions_cell_edit::{table}::{row}::{column}::{location.row_digest}"
    current = frame.iloc[row][column]
    if column in load_cases.FLAG_COLUMNS[table]:
        value = panel.checkbox(definition.label, value=bool(current), key=widget_key, help=definition.help)
    elif column in load_cases.PLASTIC_FACE_COLUMNS:
        options = list(load_cases.FACE_OPTIONS)
        if current not in options:
            options.insert(0, str(current))
        value = panel.selectbox(definition.label, options, index=options.index(current),
                                key=widget_key, help=definition.help)
    else:
        value = panel.text_input(definition.label, value=str(current), key=widget_key, help=definition.help)
    panel.button("Apply correction to this field", key=f"{widget_key}::apply",
                 help="Update only this case field. The existing parser and validation rules apply.",
                 on_click=queue_cell_correction, args=(state, {
                     "table": table, "operation": "correct", "row": row, "column": column,
                     "value": value, "expected_digest": table_digest(state),
                 }, widget_key, on_change))


def family_stages(host, *, state, on_change=None):
    resolved = resolve_focus(state) if bool(getattr(host, "open", True)) else None
    pages = stateful_input_tabs(
        host, ACTION_TABS, key=FAMILY_KEY, state=state,
        on_change=on_change or "rerun",
    )
    notice = state.pop("_actions_focus_notice", None) if bool(getattr(host, "open", True)) else None
    if notice:
        host.info(notice)
    if resolved:
        focused_editor(pages[load_cases.CASE_TABLE_KEYS.index(resolved[0].table_key)],
                       state=state, resolved=resolved, on_change=on_change)
    return pages


def conventions(host):
    guide = host.expander("Axes, signs and paste rules", expanded=False)
    rules = (
        "**Axes:** +x points right; +y points up in the section view.",
        "**Axial force:** positive N is tension; negative N is compression.",
        "**Bending:** positive Mx compresses the top face and positive My compresses the right face for centered pure bending.",
        "**Shear:** Vx pairs with My; Vy pairs with Mx. Negative-coordinate faces are left for Vx and bottom for Vy. "
        "Positive-coordinate faces are right for Vx and top for Vy. Automatic uses the adjusted moment and checks both faces when it is effectively zero.",
        "**Torsion:** retain the source model's documented signed torsion action. The current resistance check uses its magnitude.",
        "**Elastic actions:** instantaneous actions are additional increments. The total includes the sustained component.",
        "**Fatigue:** each spectrum bin combines sustained/basic actions with a cyclic increment and its cycle count. "
        "Sector solves the basic and combined states elastically and uses their stress range.",
        "**Paste:** ordinary blank action cells use zero. Invalid numeric entries remain visible and require correction. "
        "Use dot or comma decimals. Case names must be unique across Plastic/capacity, Elastic and fatigue-bin tables.",
    )
    for rule in rules:
        guide.markdown("- " + rule)



def toolbar(host, table, *, state, on_change=None):
    """Offer explicit row commands and a bounded paste preview."""
    if not bool(getattr(host, "open", True)):
        return
    tables = {key: state.get(key) for key in load_cases.CASE_TABLE_KEYS}
    frame = load_cases.normalise_table(tables[table], table)
    key = selection_key(table)
    options = list(range(len(frame)))
    restore_selection(state, table)
    if key not in state or (state[key] is not None and state[key] not in options):
        state[key] = options[0] if options else None
    selected = host.selectbox(
        "Selected case", options, key=key, index=0 if options else None,
        format_func=lambda index: f"{index + 1}: {frame.iloc[index][load_cases.NAME] or '(unnamed case)'}",
        help="Select the physical table row for duplication or deletion. The case name identifies its results and report records.",
        on_change=retain_selection, args=(state, table, on_change),
    )
    retain_selection(state, table)
    digest = table_digest(tables)
    cols = host.columns(3)
    for col, operation, label in zip(cols, ("add", "duplicate", "delete"),
                                     ("Add case", "Duplicate selected", "Delete selected")):
        col.button(label, key=f"_actions_{operation}::{table}",
                   disabled=operation != "add" and selected is None,
                   on_click=queue_command,
                   args=(state, {"table": table, "operation": operation, "row": selected,
                                 "expected_digest": digest}, on_change),
                   help={
                       "add": "Append a uniquely named case with the existing defaults for this action family.",
                       "duplicate": "Copy the selected case's action values. Review the new case's torsion declarations and minimum-reinforcement selection.",
                       "delete": "Remove the selected case row. Review the case list before calculation.",
                   }[operation])
    host.caption("Duplication retains action values. New Plastic copies require fresh torsion declarations and minimum-reinforcement selection.")
    panel = host.expander("Paste cases with preview", expanded=False)
    panel.caption("Paste a headered block from the template. Accepted cases are appended; existing rows stay in place.")
    panel.download_button("Download paste headings", paste_template(table),
                          file_name=f"{table}-headings.tsv", mime="text/tab-separated-values",
                          key=f"_actions_template::{table}",
                          help="Download the supported column names for this action family.")
    text = panel.text_area("Spreadsheet rows", key=f"_actions_paste::{table}",
                           help="Use template headings and tab, semicolon or comma-separated cells. Quote comma decimals in comma-separated files.")
    if text.strip():
        try:
            preview = prepare_paste(text, table)
            panel.dataframe(load_cases.editor_table(preview, table), hide_index=True, width="stretch")
            edit_cases(tables, state.get(AUTHORITY_KEY),
                       table=table, operation="paste", text=text, expected_digest=digest)
        except (ValueError, csv.Error) as exc:
            panel.error(str(exc))
        else:
            panel.button(f"Append {len(preview)} previewed cases", key=f"_actions_paste_apply::{table}",
                         help="Append this validated preview to the selected family. Existing rows retain their values.",
                         on_click=queue_command, args=(state, {
                             "table": table, "operation": "paste", "text": text,
                             "expected_digest": digest,
                         }, on_change))
