"""Recognize repeated canonical scalars during an explicit calculation request."""

from __future__ import annotations

import math

import project_io


def repeats_requested_input(state, key, *, callback=None):
    """Keep a transport repeat from creating a new uncommitted input draft.

    The comparison uses the completed model attached to the still-pending
    explicit request. Live defaults and navigation mirrors are not baselines.
    Existing journal entries and all uncertain values retain normal handling.
    """
    if callback is not None or type(key) is not str or key.startswith("_"):
        return False
    if state.get("_inputs_build_in_progress", False):
        return False
    pending = state.get("_pending_input_events", {})
    if type(pending) is not dict or key in pending:
        return False
    inputs = state.get("_latest_inputs")
    request = state.get("_workflow_calculate_request")
    if type(inputs) is not dict or type(request) is not dict:
        return False
    signature = inputs.get("signature")
    requested_signature = request.get("signature")
    if type(signature) is not tuple or not signature:
        return False
    if type(requested_signature) is not tuple or not requested_signature:
        return False
    generation = state.get("_project_upload_widget_generation", 0)
    requested_generation = request.get("generation")
    if type(generation) is not int or type(requested_generation) is not int:
        return False
    if generation != requested_generation or key not in inputs or key not in state:
        return False
    current = state[key]
    committed = inputs[key]
    if type(current) not in (bool, int, float, str) or type(current) is not type(committed):
        return False
    if type(current) is float and not (math.isfinite(current) and math.isfinite(committed)):
        return False
    try:
        return (
            project_io.result_sha256(signature)
            == project_io.result_sha256(requested_signature)
            and project_io.result_sha256(current)
            == project_io.result_sha256(committed)
        )
    except (TypeError, ValueError):
        return False
