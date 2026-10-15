"""AppTest navigation adapters for the public workflow pages."""

from __future__ import annotations

from collections.abc import MutableMapping

_STAGE_ROUTES = {
    "Analysis settings": "settings",
    "Section": "section",
    "Material parameters": "materials",
    "Loads": "actions",
    "Project": "project",
}
_STAGE_LABELS = {
    f"{index} {chr(0x00B7)} {label}": route
    for index, (label, route) in enumerate(tuple(_STAGE_ROUTES.items())[:4], 1)
}
_STAGE_LABELS["Project"] = "project"
_PAGE_ROUTES = {
    "Analysis": "results", "Results": "results", "Report": "report",
    "Section": "section", "Materials": "materials", "Actions": "actions",
    "Analysis settings": "settings", "Project and recovery": "project",
    "Help and manual": "help",
}
_PUBLIC_ROUTES = frozenset(_PAGE_ROUTES.values())


def goto_page(at, page):
    """Request one registered native page while retaining the input stage."""
    state = at.session_state
    if page == "Inputs":
        target = _STAGE_LABELS.get(state.filtered_state.get("_input_tab"), "section")
    else:
        target = page if page in _PUBLIC_ROUTES else _PAGE_ROUTES[page]
    if state.filtered_state.get("_workflow_page") != target:
        state["_next_workflow_page"] = target
        at.run()
    return at


def goto_input_stage(at, short_name):
    return goto_page(at, _STAGE_ROUTES[short_name])


def _navigation_values(at, values):
    """Mirror navigation preferences only; leave all engineering inputs intact."""
    state = at.session_state
    changed = any(state.filtered_state.get(key) != value for key, value in values.items())
    for key, value in values.items():
        state[key] = value
        for mirror in ("_pending_input_events", "_durable_input_scalars"):
            saved = state.filtered_state.get(mirror)
            if isinstance(saved, MutableMapping):
                saved[key] = value
    return changed


def goto_widget_owner(at, key):
    """Mount each existing field's public page and selected settings group."""
    import mvt_workspace

    values = {}
    route = "settings"
    if key.startswith("conc_") or key == "sls_fctm":
        route, family = "materials", "Concrete"
    elif key.startswith(("mild_", "mildcat_")):
        route, family = "materials", "Reinforcing steel"
    elif key.startswith(("pre_", "precat_")):
        route, family = "materials", "Prestressing steel"
    elif key.startswith("fatiguecat_"):
        route, family = "materials", "Fatigue details"
    elif key == "fatigue_spectrum_editor":
        route = "actions"
        values["_actions_family"] = "Fatigue"
    elif key == "el_phi":
        route = "actions"
        values["_actions_family"] = "Elastic"
    elif key.startswith("rep_"):
        route = "report"
    elif key.startswith(("autosave_", "project_")):
        route = "project"
    elif key.startswith(("section_", "label_")):
        route = "section"
    if route == "materials":
        values.update(_material_tab=family, _material_tab_preference=family)
    elif route == "settings":
        page = mvt_workspace.field_page(key)
        if page is not None:
            group = "Shear / torsion / M-V-T"
            values["_mvt_page"] = page
        elif key.startswith("sls_"):
            group = "Crack width"
        elif key.startswith("fatigue_"):
            group = "Fatigue"
        elif key.startswith(("detailing_", "minimum_reinforcement_", "transverse_", "clear_spacing_")) or key == "modelled_direction_alias":
            group = "Detailing"
        else:
            group = "General"
        values["_analysis_group"] = group
    changed = _navigation_values(at, values)
    current = at.session_state.filtered_state.get("_workflow_page")
    goto_page(at, route)
    if changed and current == route:
        at.run()
    return at


def goto_material(at, family):
    """Select the exact material family, accepting the historical test alias."""
    family = "Reinforcing steel" if family == "Mild steel" else family
    keys = {"Concrete": "conc_fck", "Reinforcing steel": "mild_fytk",
            "Prestressing steel": "pre_fytk", "Fatigue details": "fatiguecat_id"}
    return goto_widget_owner(at, keys[family])


def goto_action_family(at, family):
    """Select one Actions tab without changing its canonical tables."""
    if family not in {"Plastic", "Elastic", "Fatigue"}:
        raise ValueError("Unknown Actions tab")
    changed = _navigation_values(at, {"_actions_family": family})
    current = at.session_state.filtered_state.get("_workflow_page")
    goto_page(at, "actions")
    if changed and current == "actions":
        at.run()
    return at


def mounted_widget(at, widget_type, *, key):
    """Read an actual visible input after selecting its existing owner."""
    goto_widget_owner(at, key)
    return getattr(at, widget_type)(key=key)
