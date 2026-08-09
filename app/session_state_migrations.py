"""Pure, once-only cleanup of retired Sector session-state surfaces.

The v0.92 component-mapped bridge workflow could survive a Streamlit hot
reload because widget, durable-input and calculated-output state live for the
browser session. Project files are handled separately by the current-schema
loader: ``_pending_project`` is intentionally left untouched so a schema-23
file reaches the explicit schema rejection instead of being silently changed.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping

MIGRATION_MARKER = "_sector_v093_bridge_state_purged_v1"

RETIRED_BRIDGE_TABLE_KEYS = (
    "bridge_brittle_base",
    "bridge_box_walls_base",
    "bridge_minimum_crack_base",
)
RETIRED_BRIDGE_SCALAR_KEYS = ("bridge_standard",)
RETIRED_BRIDGE_EDITOR_KEYS = tuple(
    f"{key}_editor" for key in RETIRED_BRIDGE_TABLE_KEYS
)
RETIRED_BRIDGE_SEED_KEYS = tuple(
    f"_{key}_editor_seed" for key in RETIRED_BRIDGE_TABLE_KEYS
)
RETIRED_BRIDGE_STATE_KEYS = (
    *RETIRED_BRIDGE_SCALAR_KEYS,
    *RETIRED_BRIDGE_TABLE_KEYS,
    *RETIRED_BRIDGE_EDITOR_KEYS,
    *RETIRED_BRIDGE_SEED_KEYS,
)

_INPUT_MIRROR_KEYS = (
    "_durable_input_scalars",
    "_pending_input_events",
)
_SCHEMA23_ARTIFACT_KEYS = (
    "_latest_inputs",
    "results",
    "result_input_snapshot",
    "calculation_record",
    "_loaded_project_provenance",
    "_autosave_hash",
    "_fig_cache",
    "report_buffer",
    "report_bytes",
    "report_signature",
    "report_filename",
    "report_generated_on",
    "_generating_report",
    "_report_msg",
    "manual_pdf",
)
_RETIRED_VIEW = "Bridge Calculations"
_DEFAULT_VIEW = "Results Overview"


def _without_retired_bridge_entries(value: object) -> object:
    """Copy a mapping without exact retired keys; preserve other values."""

    if not isinstance(value, Mapping):
        return value
    return {
        key: item
        for key, item in value.items()
        if key not in RETIRED_BRIDGE_STATE_KEYS
    }


def purge_retired_bridge_session_state(
    state: MutableMapping[str, object],
) -> bool:
    """Remove schema-23 bridge state once and return whether cleanup ran.

    Calculation, snapshot, report, manual-PDF and cache artifacts are removed
    as whole units because their schema-23 identities included the retired
    bridge signature even when every bridge table was empty. Unrelated entries
    inside the durable-input mirror and pending widget-event journal survive.
    The marker is deliberately the final write so an interrupted cleanup is
    retried on the next Streamlit rerun.
    """

    if state.get(MIGRATION_MARKER) is True:
        return False
    state.pop(MIGRATION_MARKER, None)

    for key in RETIRED_BRIDGE_STATE_KEYS:
        state.pop(key, None)

    for key in _INPUT_MIRROR_KEYS:
        if key not in state:
            continue
        current = state[key]
        cleaned = _without_retired_bridge_entries(current)
        if cleaned is not current:
            state[key] = cleaned

    for key in _SCHEMA23_ARTIFACT_KEYS:
        state.pop(key, None)

    for key in tuple(state):
        if key == "result_sig" or (
            key.startswith("result_") and key.endswith("_sig")
        ):
            state.pop(key, None)

    for key in ("view", "_workspace_view"):
        if state.get(key) == _RETIRED_VIEW:
            state[key] = _DEFAULT_VIEW
    if state.get("_main_page") == "Analysis":
        state["_main_page"] = "Inputs"
    if state.get("_next_main_page") == "Analysis":
        state["_next_main_page"] = "Inputs"

    state[MIGRATION_MARKER] = True
    return True
