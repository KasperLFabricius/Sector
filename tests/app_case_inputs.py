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
    "sls_cw": (load_cases.ELASTIC_TABLE_KEY, "calculate_crack_width"),
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
_INPUT_STAGE_LABELS = (
    f"1 {chr(0x00B7)} Analysis settings",
    f"2 {chr(0x00B7)} Section",
    f"3 {chr(0x00B7)} Material parameters",
    f"4 {chr(0x00B7)} Loads",
    "Project",
)


def _tree_contains_key(node, keys):
    if getattr(node, "key", None) in keys:
        return True
    children = getattr(node, "children", {})
    values = children.values() if isinstance(children, dict) else children
    return any(_tree_contains_key(child, keys) for child in values)


def _direct_tab_labels(node):
    children = getattr(node, "children", {})
    values = list(children.values() if isinstance(children, dict) else children)
    return [
        getattr(child, "label", None)
        for child in values
        if getattr(child, "type", None) == "tab"
    ]


def _tree_parent_of_tab_group(node, labels):
    children = getattr(node, "children", {})
    values = list(children.values() if isinstance(children, dict) else children)
    for child in values:
        if _direct_tab_labels(child) == list(labels):
            return node
    for child in values:
        parent = _tree_parent_of_tab_group(child, labels)
        if parent is not None:
            return parent
    return None


def discard_retired_qs_fragment(at):
    """Mirror the browser removal of Quick Section after its full rerun."""

    main = next(
        child
        for child in at._tree.children.values()
        if getattr(child, "type", None) == "main"
    )
    input_host = _tree_parent_of_tab_group(main, _INPUT_STAGE_LABELS)
    if input_host is None:
        return at
    retired_markers = {"qs_apply", "qs_back", "shape"}
    for index, child in list(input_host.children.items()):
        if (
            _direct_tab_labels(child) != list(_INPUT_STAGE_LABELS)
            and _tree_contains_key(child, retired_markers)
        ):
            del input_host.children[index]
    return at


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

    defaults = load_cases.default_tables()
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


def _goto_page(at, page):
    try:
        current = at.session_state["_main_page"]
    except KeyError:
        current = None
    if current != page:
        at.segmented_control(key="_main_page").set_value(page).run()


def _goto_inputs(at):
    _goto_page(at, "Inputs")


def goto_input_stage(at, short_name):
    _goto_inputs(at)
    labels = {
        label.split(" ", 2)[-1] if label[0].isdigit() else label: label
        for label in _INPUT_STAGE_LABELS
    }
    target = labels[short_name]
    try:
        current = at.session_state["_input_tab"]
    except KeyError:
        current = None
    if current != target:
        at.session_state["_input_tab"] = target
        at.run()


def _goto_material(at, family):
    goto_input_stage(at, "Material parameters")
    try:
        current = at.session_state["_material_tab"]
    except KeyError:
        current = None
    if current != family:
        at.session_state["_material_tab"] = family
        at.session_state["_material_tab_preference"] = family
        at.run()


def _goto_widget_owner(at, key):
    if key.startswith("conc_") or key == "sls_fctm":
        return _goto_material(at, "Concrete")
    if key.startswith(("mild_", "mildcat_")):
        return _goto_material(at, "Mild steel")
    if key.startswith(("pre_", "precat_")):
        return _goto_material(at, "Prestressing steel")
    if key.startswith("fatiguecat_"):
        return _goto_material(at, "Fatigue details")
    if key == "el_phi":
        return goto_input_stage(at, "Loads")
    if key.startswith("rep_"):
        return _goto_page(at, "Report")
    if key.startswith(("autosave_", "project_")):
        return goto_input_stage(at, "Project")
    if key.startswith(("section_", "label_")):
        return goto_input_stage(at, "Section")
    return goto_input_stage(at, "Analysis settings")


def apply_widget_changes(at, changes):
    """Apply legacy case aliases and mount each ordinary widget's owner."""

    ordinary, case_changed = apply_case_changes(at, changes)
    if case_changed:
        _goto_inputs(at)
        if not ordinary:
            at.run()
    for widget_type, key, value in ordinary:
        try:
            widget = getattr(at, widget_type)(key=key)
        except KeyError:
            if key == "view":
                at.segmented_control(key="_main_page").set_value("Analysis").run()
            else:
                _goto_widget_owner(at, key)
            widget = getattr(at, widget_type)(key=key)
        widget.set_value(value).run()
    return at
