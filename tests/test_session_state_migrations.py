"""Pure-state tests for the once-only v0.93 bridge retirement cleanup."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import session_state_migrations as migrations


def test_bridge_retirement_purges_every_schema23_artifact_and_marks_last():
    pending_project = object()
    unrelated = object()
    durable = {
        "mode": "Both",
        **{key: f"old-{key}" for key in migrations.RETIRED_BRIDGE_STATE_KEYS},
    }
    pending_events = {
        "sls_cw": True,
        **{key: f"event-{key}" for key in migrations.RETIRED_BRIDGE_STATE_KEYS},
    }
    state = {
        migrations.MIGRATION_MARKER: False,
        "unrelated": unrelated,
        "_pending_project": pending_project,
        **{key: f"live-{key}" for key in migrations.RETIRED_BRIDGE_STATE_KEYS},
        "_durable_input_scalars": durable,
        "_pending_input_events": pending_events,
        "_latest_inputs": {"mode": "Both", "bridge_standard": "retired"},
        "results": {"plastic": object(), "bridge": object()},
        "result_input_snapshot": {
            "mode": "Both",
            "bridge_brittle_base": object(),
        },
        "calculation_record": {"input_sha256": "a" * 64},
        "_loaded_project_provenance": {"input_sha256": "b" * 64},
        "_loaded_project_migration": {"source_schema_version": 24},
        "_project_migration_warnings": ("legacy migration warning",),
        "_autosave_hash": "c" * 64,
        "_fig_cache": {"section": object()},
        "result_sig": ("schema-23",),
        "result_plastic_sig": ("plastic",),
        "result_elastic_sig": ("elastic",),
        "result_fatigue_sig": ("fatigue",),
        "result_capacity_contract_sig": ("capacity",),
        "result_future_sig": ("future",),
        "report_buffer": b"%PDF-old",
        "report_bytes": b"%PDF-legacy",
        "report_signature": ("schema-23",),
        "report_filename": "old.pdf",
        "report_generated_on": "2026-08-09",
        "_generating_report": True,
        "_report_msg": ("success", "old report"),
        "manual_pdf": b"%PDF-old-manual",
        "view": "Bridge Calculations",
        "_workspace_view": "Bridge Calculations",
        "_main_page": "Analysis",
        "_next_main_page": "Analysis",
        "result_summary_preference": "expanded",
    }

    assert migrations.purge_retired_bridge_session_state(state) is True

    for key in migrations.RETIRED_BRIDGE_STATE_KEYS:
        assert key not in state
    assert state["_durable_input_scalars"] == {"mode": "Both"}
    assert state["_pending_input_events"] == {"sls_cw": True}
    assert state["_pending_project"] is pending_project
    assert state["unrelated"] is unrelated
    assert state["result_summary_preference"] == "expanded"

    for key in (
        "_latest_inputs",
        "results",
        "result_input_snapshot",
        "calculation_record",
        "_loaded_project_provenance",
        "_loaded_project_migration",
        "_project_migration_warnings",
        "_autosave_hash",
        "_fig_cache",
        "result_sig",
        "result_plastic_sig",
        "result_elastic_sig",
        "result_fatigue_sig",
        "result_capacity_contract_sig",
        "result_future_sig",
        "report_buffer",
        "report_bytes",
        "report_signature",
        "report_filename",
        "report_generated_on",
        "_generating_report",
        "_report_msg",
        "manual_pdf",
    ):
        assert key not in state

    assert state["view"] == "Results Overview"
    assert state["_workspace_view"] == "Results Overview"
    assert state["_main_page"] == "Inputs"
    assert state["_next_main_page"] == "Inputs"
    assert state[migrations.MIGRATION_MARKER] is True
    assert next(reversed(state)) == migrations.MIGRATION_MARKER

    # Nested dictionaries are copied rather than mutating aliases held elsewhere.
    assert durable["bridge_standard"] == "old-bridge_standard"
    assert pending_events["bridge_standard"] == "event-bridge_standard"


def test_bridge_retirement_is_once_only_and_preserves_nonretired_navigation():
    state = {
        "view": "Fatigue Results",
        "_workspace_view": "Fatigue Results",
        "_main_page": "Inputs",
        "_next_main_page": "Inputs",
        "_durable_input_scalars": "unexpected but unrelated opaque state",
        "_pending_input_events": None,
    }

    assert migrations.purge_retired_bridge_session_state(state) is True
    state["bridge_standard"] = "cannot be recreated by the retired UI"
    snapshot = dict(state)

    assert migrations.purge_retired_bridge_session_state(state) is False
    assert state == snapshot
    assert state["view"] == "Fatigue Results"
    assert state["_workspace_view"] == "Fatigue Results"
    assert state["_main_page"] == "Inputs"
    assert state["_durable_input_scalars"] == (
        "unexpected but unrelated opaque state"
    )
    assert state["_pending_input_events"] is None
