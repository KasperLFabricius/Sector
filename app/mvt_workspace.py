"""Presentation-only navigation for the existing shear and torsion inputs."""

from __future__ import annotations

from input_stage_host import input_stages, normalise_stage_selection

PAGE_KEY = "_mvt_page"
PAGES = (
    "Checks and methods",
    "Shared reinforcement",
    "Shear",
    "Torsion",
    "Combined M-V-T",
)
_CHECK_KEYS = frozenset({
    "shear_on", "torsion_on", "combined_on", "shear_method",
    "torsion_method", "combined_method",
})
_SHARED_KEYS = frozenset({
    "shear_links", "shear_link_dia", "shear_link_s", "shear_fywk",
    "shear_vx_link_legs", "shear_vy_link_legs",
    "shear_vx_transverse_leg_spacing", "shear_vy_transverse_leg_spacing",
    "strut_cot_min", "strut_cot_max", "capacity_steel_material_id",
})


def field_page(key):
    """Locate an existing input without changing its value or applicability."""
    key = str(key or "")
    if key in _CHECK_KEYS:
        return PAGES[0]
    if key in _SHARED_KEYS:
        return PAGES[1]
    if key.startswith("shear_"):
        return PAGES[2]
    if key.startswith(("torsion_", "_torsion_case_")):
        return PAGES[3]
    if key == "combined_mv_independent":
        return PAGES[4]
    return None


def select_page(state, page, *, on_change=None):
    """Store a navigation request after retaining the current input edits."""
    if page not in PAGES:
        raise ValueError(f"Unknown shear/torsion page: {page}")
    if on_change is not None:
        on_change()
    state[PAGE_KEY] = page
    for mirror in ("_pending_input_events", "_durable_input_scalars"):
        if mirror in state:
            state[mirror][PAGE_KEY] = page


def open_settings(state, group, page=None, *, on_change=None):
    """Open an input destination without enabling or declaring a prerequisite."""
    if group not in {"General", "Shear / torsion / M-V-T"}:
        raise ValueError("Unknown prerequisite settings group")
    if page is not None and page not in PAGES:
        raise ValueError("Unknown prerequisite settings page")
    if on_change is not None:
        on_change()
    state["_analysis_group"] = group
    for mirror in ("_pending_input_events", "_durable_input_scalars"):
        if mirror in state:
            state[mirror]["_analysis_group"] = group
    if page is not None:
        select_page(state, page)


def requirement_links(host, requirements, *, state, key_prefix, on_change=None,
                      show_status=False):
    """Link the existing requirement register to its current editing authority."""
    destinations = {
        "Plastic / Both bending analysis": ("General", None, "Open General settings"),
        "Check utilisation against applied moment": ("General", None, "Open General settings"),
        "Shear check enabled": ("Shear / torsion / M-V-T", PAGES[0], "Open Checks and methods"),
        "Torsion check enabled": ("Shear / torsion / M-V-T", PAGES[0], "Open Checks and methods"),
        "Shared links / closed torsion stirrups present": ("Shear / torsion / M-V-T", PAGES[1], "Open Shared reinforcement"),
    }
    links = []
    for met, label in requirements:
        if show_status:
            host.caption(("Ready: " if met else "Needs input: ") + label)
        target = destinations.get(label)
        if not met and target is not None and target not in links:
            links.append(target)
    for index, (group, page, label) in enumerate(links):
        host.button(label, key=f"{key_prefix}_{index}", on_click=open_settings,
                    args=(state, group, page), kwargs={"on_change": on_change},
                    help="Open the cited settings. Review and change the input explicitly.")


def stages(host, *, state, on_change=None):
    """Build one visible page; hidden inputs use the retained-state boundary."""
    normalise_stage_selection(state, PAGE_KEY, PAGES)
    selected = host.radio(
        "Shear, torsion and M-V-T settings", PAGES, key=PAGE_KEY,
        on_change=on_change,
        help=("Choose the settings page. Each page retains its entered values. "
              "Checks and methods controls which checks are enabled."),
    )
    if selected not in PAGES or selected != state.get(PAGE_KEY):
        selected = None
    pages = input_stages(host, PAGES, selected, state=state)
    pages[0].caption(
        "Select the checks and their methods. Combined M-V-T uses one shared "
        "edition for shear and torsion."
    )
    pages[4].markdown("**Combined M-V-T assumptions and requirements**")
    pages[4].caption(
        "Review the enabled checks and physical reinforcement before calculation. "
        "The requirement list shows which inputs need attention."
    )
    return pages
