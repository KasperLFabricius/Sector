"""AppTest adapters for load inputs that moved from scalars to case tables."""

from __future__ import annotations

import load_cases


_FIELDS = {
    "pl_case_id": (load_cases.PLASTIC_TABLE_KEY, "name"),
    "pl_P": (load_cases.PLASTIC_TABLE_KEY, "n_ed_kn"),
    "pl_Mx": (load_cases.PLASTIC_TABLE_KEY, "mx_ed_knm"),
    "pl_My": (load_cases.PLASTIC_TABLE_KEY, "my_ed_knm"),
    "shear_V": (load_cases.PLASTIC_TABLE_KEY, "vy_ed_kn"),
    "shear_Vx": (load_cases.PLASTIC_TABLE_KEY, "vx_ed_kn"),
    "shear_Vy": (load_cases.PLASTIC_TABLE_KEY, "vy_ed_kn"),
    "shear_face_x": (load_cases.PLASTIC_TABLE_KEY, "vx_face"),
    "shear_face_y": (load_cases.PLASTIC_TABLE_KEY, "vy_face"),
    "torsion_T": (load_cases.PLASTIC_TABLE_KEY, "t_ed_knm"),
    "el_case_id": (load_cases.ELASTIC_TABLE_KEY, "name"),
    "el_long_P": (load_cases.ELASTIC_TABLE_KEY, "n_long_ed_kn"),
    "el_long_Mx": (load_cases.ELASTIC_TABLE_KEY, "mx_long_ed_knm"),
    "el_long_My": (load_cases.ELASTIC_TABLE_KEY, "my_long_ed_knm"),
    "el_short_P": (load_cases.ELASTIC_TABLE_KEY, "n_short_ed_kn"),
    "el_short_Mx": (load_cases.ELASTIC_TABLE_KEY, "mx_short_ed_knm"),
    "el_short_My": (load_cases.ELASTIC_TABLE_KEY, "my_short_ed_knm"),
    "sls_cw": (load_cases.ELASTIC_TABLE_KEY, "check_crack_width"),
}
_DESCRIPTION_KEYS = {
    "pl_case_type", "pl_case_source", "el_case_type", "el_case_source",
}
_EDITOR_KEYS = {
    load_cases.PLASTIC_TABLE_KEY: "plastic_cases_editor",
    load_cases.ELASTIC_TABLE_KEY: "elastic_cases_editor",
}
_WIDGET_ALIASES = {
    "shear_bw": "shear_vy_bw",
    "shear_link_legs": "shear_vy_link_legs",
}


def _delete(state, key):
    try:
        del state[key]
    except KeyError:
        pass


def _description_parts(value):
    value = str(value or "").strip()
    if " | Source: " in value:
        return tuple(value.split(" | Source: ", 1))
    if value.startswith("Source: "):
        return "", value[8:]
    return value, ""


def apply_case_changes(at, changes):
    """Apply former scalar-widget edits to row 1 of the canonical tables.

    Returns ``(ordinary_widget_changes, changed)``. This keeps the established
    solver tests concise while the UI-facing tests exercise the native editors.
    """
    changes = list(changes)
    case_updates = {
        key: value
        for _widget_type, key, value in changes
        if key in _FIELDS or key in _DESCRIPTION_KEYS
    }
    ordinary = [
        (widget_type, _WIDGET_ALIASES.get(key, key), value)
        for widget_type, key, value in changes
        if key not in _FIELDS and key not in _DESCRIPTION_KEYS
    ]
    if not case_updates:
        return ordinary, False

    defaults = load_cases.tables_from_legacy_scalars({})
    frames = {}
    for base_key in load_cases.CASE_TABLE_KEYS:
        value = (
            at.session_state[base_key]
            if base_key in at.session_state
            else defaults[base_key]
        )
        frame = load_cases.normalise_table(value, base_key)
        if frame.empty:
            frame = defaults[base_key].copy(deep=True)
        frames[base_key] = frame

    for key, value in case_updates.items():
        if key in _FIELDS:
            base_key, column = _FIELDS[key]
            frames[base_key].at[0, column] = value

    for prefix, base_key in (
        ("pl", load_cases.PLASTIC_TABLE_KEY),
        ("el", load_cases.ELASTIC_TABLE_KEY),
    ):
        type_key, source_key = f"{prefix}_case_type", f"{prefix}_case_source"
        if type_key not in case_updates and source_key not in case_updates:
            continue
        classification, source = _description_parts(
            frames[base_key].at[0, load_cases.DESCRIPTION]
        )
        classification = str(case_updates.get(type_key, classification)).strip()
        source = str(case_updates.get(source_key, source)).strip()
        description = classification
        if source:
            description += (" | " if description else "") + f"Source: {source}"
        frames[base_key].at[0, load_cases.DESCRIPTION] = description

    for base_key, frame in frames.items():
        at.session_state[base_key] = load_cases.normalise_table(frame, base_key)
        _delete(at.session_state, _EDITOR_KEYS[base_key])
        _delete(at.session_state, f"_{base_key}_editor_seed")
    return ordinary, True


def first_case_value(at, legacy_key):
    """Read one former scalar value from canonical row 1 for assertions."""
    base_key, column = _FIELDS[legacy_key]
    return at.session_state[base_key].iloc[0][column]
