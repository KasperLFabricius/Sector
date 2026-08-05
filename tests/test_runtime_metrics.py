from __future__ import annotations

import json
import math
import pathlib
import sys

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from app import runtime_metrics


ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = str(ROOT / "app" / "sector_app.py")
sys.path.insert(0, str(ROOT / "app"))


class FakeContext:
    def __init__(self, target_ids=()):
        self.fragment_ids_this_run = list(target_ids)
        self.forwarded = []
        self._enqueue = self.forwarded.append


class FakeMessage:
    def __init__(self, size):
        self.size = size

    def ByteSize(self):
        return self.size


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " On "])
def test_only_explicit_true_values_enable_measurements(value):
    assert runtime_metrics.is_enabled({runtime_metrics.ENABLE_ENV: value}) is True


@pytest.mark.parametrize("value", ["", "0", "false", "off", "no", "enabled"])
def test_other_values_leave_measurements_disabled(value):
    assert runtime_metrics.is_enabled({runtime_metrics.ENABLE_ENV: value}) is False


def test_disabled_api_is_inert(monkeypatch):
    monkeypatch.delenv(runtime_metrics.ENABLE_ENV, raising=False)
    monkeypatch.delenv(runtime_metrics.OUTPUT_ENV, raising=False)
    state = {}
    context = FakeContext()
    original_enqueue = context._enqueue

    assert runtime_metrics.open_app_run(
        state, context=context, now_ns=0
    ) is None
    assert runtime_metrics.open_fragment_run(
        state, "inputs", context=context, fragment_id="inputs", now_ns=1
    ) is None
    assert runtime_metrics.start_phase(state, "startup", now_ns=2) is None
    assert runtime_metrics.stop_phase(state, None, now_ns=3) is None
    assert runtime_metrics.close_app_run(
        state, context=context, now_ns=4
    ) is None
    assert state == {}
    assert context._enqueue == original_enqueue
    assert runtime_metrics.snapshot(state) == {
        "schema_version": runtime_metrics.SCHEMA_VERSION,
        "enabled": False,
        "history": [],
        "active": None,
        "error": None,
    }


def test_app_record_seals_phases_bytes_and_final_labels(monkeypatch):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    state = {"_main_page": "", "_input_tab": "", "_material_tab": ""}
    context = FakeContext()

    assert runtime_metrics.open_app_run(
        state,
        context=context,
        now_ns=1_000_000_000,
        started_utc="2026-08-05T12:00:00+00:00",
    ) == 1
    token = runtime_metrics.start_phase(state, "startup", now_ns=1_100_000_000)
    context._enqueue(FakeMessage(150))
    context._enqueue(FakeMessage(350))
    runtime_metrics.stop_phase(state, token, now_ns=1_250_000_000)
    state.update({
        "_main_page": "Inputs",
        "_input_tab": "2 - Section",
        "_material_tab": "Concrete",
    })
    record = runtime_metrics.close_app_run(
        state, context=context, now_ns=1_500_000_000
    )

    assert [message.size for message in context.forwarded] == [150, 350]
    assert record == {
        "schema_version": 1,
        "run_number": 1,
        "kind": "app",
        "fragment_name": "",
        "fragment_id": "",
        "started_utc": "2026-08-05T12:00:00+00:00",
        "interrupted": False,
        "phases": {
            "startup": {
                "count": 1,
                "total_ms": pytest.approx(150.0),
                "max_ms": pytest.approx(150.0),
                "last_ms": pytest.approx(150.0),
            }
        },
        "forward_message_count": 2,
        "forward_message_bytes": 500,
        "largest_forward_message_bytes": 350,
        "byte_accounting": True,
        "workspace": "Inputs",
        "input_stage": "2 - Section",
        "material_family": "Concrete",
        "duration_ms": pytest.approx(500.0),
    }


def test_fragment_owner_excludes_nested_fragment_bodies(monkeypatch):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    state = {}
    context = FakeContext(("outer-id",))

    assert runtime_metrics.open_fragment_run(
        state,
        "inputs",
        context=context,
        fragment_id="outer-id",
        now_ns=10,
    ) == 1
    assert runtime_metrics.open_fragment_run(
        state,
        "report",
        context=context,
        fragment_id="nested-id",
        now_ns=20,
    ) is None
    assert runtime_metrics.close_fragment_run(
        state, context=context, fragment_id="nested-id", now_ns=30
    ) is None
    assert runtime_metrics.snapshot(state)["active"]["fragment_name"] == "inputs"

    record = runtime_metrics.close_fragment_run(
        state, context=context, fragment_id="outer-id", now_ns=40
    )
    assert record["kind"] == "fragment"
    assert record["fragment_name"] == "inputs"
    assert record["fragment_id"] == "outer-id"


def test_each_requested_nested_fragment_can_own_its_direct_rerun(monkeypatch):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    state = {}
    context = FakeContext(("report-id",))
    runtime_metrics.open_fragment_run(
        state,
        "report",
        context=context,
        fragment_id="report-id",
        now_ns=0,
    )
    record = runtime_metrics.close_fragment_run(
        state, context=context, fragment_id="report-id", now_ns=10
    )
    assert record["fragment_name"] == "report"
    assert record["interrupted"] is False


def test_repeated_open_for_same_owner_does_not_split_the_run(monkeypatch):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    state = {}
    context = FakeContext(("input-id",))
    assert runtime_metrics.open_fragment_run(
        state, "inputs", context=context, fragment_id="input-id", now_ns=0
    ) == 1
    assert runtime_metrics.open_fragment_run(
        state, "inputs", context=context, fragment_id="input-id", now_ns=5
    ) == 1
    record = runtime_metrics.close_fragment_run(
        state, context=context, fragment_id="input-id", now_ns=10
    )
    assert record["run_number"] == 1
    assert len(runtime_metrics.snapshot(state)["history"]) == 1


def test_superseded_owner_is_retained_as_interrupted(monkeypatch):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    state = {}
    first_context = FakeContext(("input-id",))
    second_context = FakeContext(("analysis-id",))
    runtime_metrics.open_fragment_run(
        state, "inputs", context=first_context, fragment_id="input-id", now_ns=0
    )
    runtime_metrics.open_fragment_run(
        state,
        "analysis",
        context=second_context,
        fragment_id="analysis-id",
        now_ns=100,
    )

    history = runtime_metrics.snapshot(state)["history"]
    assert len(history) == 1
    assert history[0]["fragment_name"] == "inputs"
    assert history[0]["interrupted"] is True
    assert runtime_metrics.snapshot(state)["active"]["fragment_name"] == "analysis"


def test_phase_accumulates_and_unknown_phase_is_rejected(monkeypatch):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    state = {}
    context = FakeContext()
    runtime_metrics.open_app_run(state, context=context, now_ns=0)
    first = runtime_metrics.start_phase(state, "preview", now_ns=1_000_000)
    runtime_metrics.stop_phase(state, first, now_ns=6_000_000)
    second = runtime_metrics.start_phase(state, "preview", now_ns=10_000_000)
    runtime_metrics.stop_phase(state, second, now_ns=22_000_000)
    record = runtime_metrics.close_app_run(
        state, context=context, now_ns=30_000_000
    )

    assert record["phases"]["preview"] == {
        "count": 2,
        "total_ms": pytest.approx(17.0),
        "max_ms": pytest.approx(12.0),
        "last_ms": pytest.approx(12.0),
    }
    with pytest.raises(ValueError, match="Unknown runtime phase"):
        runtime_metrics.start_phase(state, "solver")


def test_history_is_bounded(monkeypatch):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    state = {}
    context = FakeContext()
    for number in range(1, runtime_metrics.RUN_LIMIT + 4):
        runtime_metrics.open_app_run(state, context=context, now_ns=number * 10)
        runtime_metrics.close_app_run(
            state, context=context, now_ns=number * 10 + 1
        )
    history = runtime_metrics.snapshot(state)["history"]
    assert len(history) == runtime_metrics.RUN_LIMIT
    assert history[0]["run_number"] == 4
    assert history[-1]["run_number"] == runtime_metrics.RUN_LIMIT + 3


def test_app_and_fragment_finalizers_are_fenced(monkeypatch):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    state = {}
    app_context = FakeContext()
    fragment_context = FakeContext(("analysis-id",))

    runtime_metrics.open_app_run(state, context=app_context, now_ns=0)
    assert runtime_metrics.close_fragment_run(
        state,
        context=fragment_context,
        fragment_id="analysis-id",
        now_ns=1,
    ) is None
    assert runtime_metrics.close_app_run(
        state, context=app_context, now_ns=2
    )["kind"] == "app"

    runtime_metrics.open_fragment_run(
        state,
        "analysis",
        context=fragment_context,
        fragment_id="analysis-id",
        now_ns=3,
    )
    assert runtime_metrics.close_app_run(
        state, context=fragment_context, now_ns=4
    ) is None
    assert runtime_metrics.close_fragment_run(
        state,
        context=fragment_context,
        fragment_id="analysis-id",
        now_ns=5,
    )["kind"] == "fragment"


def test_missing_queue_disables_only_byte_accounting(monkeypatch):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    state = {}

    class ContextWithoutQueue:
        fragment_ids_this_run = []

    context = ContextWithoutQueue()
    runtime_metrics.open_app_run(state, context=context, now_ns=0)
    record = runtime_metrics.close_app_run(state, context=context, now_ns=1)
    assert record["byte_accounting"] is False
    assert record["forward_message_count"] == 0
    assert record["forward_message_bytes"] == 0


def test_message_accounting_failure_never_suppresses_forwarding(monkeypatch):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    state = {}
    context = FakeContext()
    runtime_metrics.open_app_run(state, context=context, now_ns=0)

    class BrokenMessage:
        def ByteSize(self):
            raise RuntimeError("protobuf API changed")

    message = BrokenMessage()
    context._enqueue(message)
    record = runtime_metrics.close_app_run(state, context=context, now_ns=1)
    assert context.forwarded == [message]
    assert record["byte_accounting"] is False
    assert record["forward_message_count"] == 0


def test_state_accounting_failure_never_suppresses_forwarding(monkeypatch):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    context = FakeContext()

    class BrokenState:
        def get(self, _key):
            raise RuntimeError("state proxy changed")

    assert runtime_metrics._install_message_counter(context, BrokenState()) is True
    message = FakeMessage(100)
    context._enqueue(message)
    assert context.forwarded == [message]


def test_json_lines_requires_an_explicit_destination(monkeypatch, tmp_path):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    destination = tmp_path / "runtime.jsonl"
    monkeypatch.setenv(runtime_metrics.OUTPUT_ENV, str(destination))
    state = {"engineering_secret": "not-recorded"}
    context = FakeContext()
    runtime_metrics.open_app_run(
        state,
        context=context,
        now_ns=0,
        started_utc="2026-08-05T12:00:00+00:00",
    )
    runtime_metrics.close_app_run(state, context=context, now_ns=5_000_000)

    rows = [
        json.loads(line)
        for line in destination.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["duration_ms"] == pytest.approx(5.0)
    assert "engineering_secret" not in rows[0]
    assert "not-recorded" not in destination.read_text(encoding="utf-8")


def test_unwritable_destination_is_diagnostic_only(monkeypatch, tmp_path):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    monkeypatch.setenv(
        runtime_metrics.OUTPUT_ENV,
        str(tmp_path / "missing" / "runtime.jsonl"),
    )
    state = {}
    context = FakeContext()
    runtime_metrics.open_app_run(state, context=context, now_ns=0)
    record = runtime_metrics.close_app_run(state, context=context, now_ns=1)
    assert record["run_number"] == 1
    assert runtime_metrics.snapshot(state)["error"].startswith(
        "FileNotFoundError:"
    )


def test_snapshot_is_detached_and_hides_internal_clock(monkeypatch):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    state = {}
    runtime_metrics.open_app_run(state, context=FakeContext(), now_ns=123)
    snapshot = runtime_metrics.snapshot(state)
    assert "_started_ns" not in snapshot["active"]
    snapshot["active"]["workspace"] = "changed"
    assert state[runtime_metrics.state_keys()[1]]["workspace"] == ""


def _function_slice(source: str, name: str, next_name: str) -> str:
    return source[source.index(f"def {name}"):source.index(f"def {next_name}")]


def test_app_wires_all_five_fragment_owners_and_every_normal_exit():
    source = (ROOT / "app" / "sector_app.py").read_text(encoding="utf-8")
    assert source.count("runtime_metrics.open_fragment_run") == 5
    for fragment_name in ("save_load", "report", "quick_section", "inputs", "analysis"):
        assert f'"{fragment_name}"' in source

    save_load = _function_slice(source, "_save_load_panel", "_report_meta")
    upload = save_load.index('st.session_state["_pending_project"]')
    assert upload < save_load.index("runtime_metrics.close_fragment_run", upload)
    assert save_load.index("runtime_metrics.close_fragment_run", upload) < (
        save_load.index("st.rerun()", upload)
    )
    assert save_load.count("runtime_metrics.close_fragment_run") == 2

    report = _function_slice(source, "_report_panel", "_generate_report")
    request = report.index('st.session_state["_generating_report"]')
    assert request < report.index("runtime_metrics.close_fragment_run", request)
    assert report.index("runtime_metrics.close_fragment_run", request) < (
        report.index("st.rerun()", request)
    )
    assert report.count("runtime_metrics.close_fragment_run") == 2

    quick = _function_slice(source, "_quick_section_viewport", "_modular_ratio_readout")
    assert quick.count("runtime_metrics.close_fragment_run") == 3
    assert quick.count("st.rerun()") == 2
    first_close = quick.index("runtime_metrics.close_fragment_run")
    first_rerun = quick.index("st.rerun()")
    second_close = quick.index("runtime_metrics.close_fragment_run", first_close + 1)
    second_rerun = quick.index("st.rerun()", first_rerun + 1)
    assert first_close < first_rerun < second_close < second_rerun

    inputs = _function_slice(source, "_input_workspace", "_sweep")
    assert inputs.count("runtime_metrics.close_fragment_run") == 1
    assert "st.rerun()" not in inputs

    analysis_start = source.index("def _analysis_workspace")
    analysis = source[
        analysis_start:source.index("# Layout", analysis_start)
    ]
    stale_error = analysis.index('"The stale calculation has no matching input snapshot.')
    early_return = analysis.index("        return", stale_error)
    assert analysis.index(
        "runtime_metrics.close_fragment_run", stale_error
    ) < early_return
    assert analysis.count("\n        return") == 1
    assert analysis.count("runtime_metrics.close_fragment_run") == 2


def test_app_wires_frozen_phases_and_full_run_boundaries():
    source = (ROOT / "app" / "sector_app.py").read_text(encoding="utf-8")
    for name in runtime_metrics.PHASE_NAMES:
        assert f'"{name}"' in source
    startup = source.index("_autosave_startup()        # restore")
    assert source.index("runtime_metrics.open_app_run") < startup
    assert startup < source.index("runtime_metrics.stop_phase", startup)
    assert source.rindex("runtime_metrics.close_app_run") > source.rindex(
        "manual.render_manual_dialog()"
    )
    assert source.count("_measured_autosave()") == 3


def test_disabled_live_app_creates_no_runtime_state(monkeypatch):
    monkeypatch.delenv(runtime_metrics.ENABLE_ENV, raising=False)
    monkeypatch.delenv(runtime_metrics.OUTPUT_ENV, raising=False)
    app = AppTest.from_file(APP, default_timeout=90)
    app.run()
    assert not app.exception
    assert all(key not in app.session_state for key in runtime_metrics.state_keys())


def test_enabled_live_app_records_final_labels_phases_and_real_bytes(monkeypatch):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    monkeypatch.delenv(runtime_metrics.OUTPUT_ENV, raising=False)
    app = AppTest.from_file(APP, default_timeout=90)
    app.run()
    assert not app.exception

    first = app.session_state[runtime_metrics.state_keys()[2]][-1]
    assert first["kind"] == "app"
    assert first["workspace"] == "Inputs"
    assert first["input_stage"]
    assert first["byte_accounting"] is True
    assert first["forward_message_count"] > 0
    assert first["forward_message_bytes"] > 0
    assert {
        "startup",
        "pane_construction",
        "normalization",
        "input_assembly",
        "autosave",
    }.issubset(first["phases"])


def test_runtime_state_is_excluded_from_project_persistence(monkeypatch):
    monkeypatch.setenv(runtime_metrics.ENABLE_ENV, "1")
    app = AppTest.from_file(APP, default_timeout=90)
    app.run()
    assert not app.exception

    import project_io

    assert not set(runtime_metrics.state_keys()).intersection(project_io.SCALAR_KEYS)
    assert not set(runtime_metrics.state_keys()).intersection(
        project_io.PROJECT_TABLE_KEYS
    )
    project = project_io.dump_project(
        {
            key: app.session_state[key]
            for key in project_io.PROJECT_TABLE_KEYS
            if key in app.session_state
        },
        {
            key: app.session_state[key]
            for key in project_io.SCALAR_KEYS
            if key in app.session_state
        },
    )
    assert "runtime_metrics" not in project
    assert runtime_metrics.ENABLE_ENV not in project


def dense_current_project_text() -> str:
    """Build the deterministic dense current-schema browser fixture."""

    import bridge_inputs
    import fatigue_inputs
    import load_cases
    import project_io
    import reinforcement_table

    radius = 1000.0
    corners = pd.DataFrame({
        "x (mm)": [
            radius * math.cos(-2.0 * math.pi * index / 64)
            for index in range(64)
        ],
        "y (mm)": [
            radius * math.sin(-2.0 * math.pi * index / 64)
            for index in range(64)
        ],
    })
    bars = reinforcement_table.normalise_table(
        [
            {
                "ID": f"R{index + 1}",
                "x (mm)": -750.0 + 1500.0 * (index % 16) / 15.0,
                "y (mm)": -750.0 + 1500.0 * (index // 16) / 15.0,
                "size mode": "Diameter",
                "area (mm2)": None,
                "diameter (mm)": 20.0,
                "material ID": "M1",
                "fatigue detail ID": "F1",
            }
            for index in range(256)
        ],
        "bar",
    )
    tendons = reinforcement_table.normalise_table(
        [
            {
                "ID": f"T{index + 1}",
                "x (mm)": 800.0 * math.cos(2.0 * math.pi * index / 64),
                "y (mm)": 800.0 * math.sin(2.0 * math.pi * index / 64),
                "size mode": "Area",
                "area (mm2)": 150.0,
                "diameter (mm)": None,
                "material ID": "P1",
                "fatigue detail ID": "F2",
            }
            for index in range(64)
        ],
        "tendon",
    )
    plastic = load_cases.normalise_table(
        [
            {
                "name": f"P-{index + 1:03d}",
                "description": "Dense runtime action",
                "n_ed_kn": -1000.0 + 10.0 * index,
                "mx_ed_knm": 25.0 + index,
                "my_ed_knm": -15.0 - 0.5 * index,
                "vx_ed_kn": 2.0 * index,
                "vy_ed_kn": -1.5 * index,
                "vx_face": "auto",
                "vy_face": "auto",
                "t_ed_knm": 0.25 * index,
                "check_minimum_reinforcement": False,
            }
            for index in range(200)
        ],
        load_cases.PLASTIC_TABLE_KEY,
    )
    elastic = load_cases.normalise_table(
        [
            {
                "name": f"E-{index + 1:03d}",
                "description": "Dense runtime action",
                "n_long_ed_kn": -500.0 + 5.0 * index,
                "mx_long_ed_knm": 12.0 + index,
                "my_long_ed_knm": -8.0 - index,
                "n_short_ed_kn": 2.0 * index,
                "mx_short_ed_knm": 4.0 + index,
                "my_short_ed_knm": -3.0 - 0.5 * index,
                "calculate_crack_width": index == 0,
            }
            for index in range(200)
        ],
        load_cases.ELASTIC_TABLE_KEY,
    )
    spectra = fatigue_inputs.normalise_spectrum_table(
        [
            {
                "spectrum": "Dense grouped spectrum",
                "name": f"F-{index + 1:03d}",
                "description": "Dense runtime fatigue bin",
                "cycles": 10_000.0 + 100.0 * index,
                "n_long_ed_kn": -200.0,
                "mx_long_ed_knm": 10.0,
                "my_long_ed_knm": -5.0,
                "n_short_ed_kn": 0.0,
                "mx_short_ed_knm": 1.0 + index,
                "my_short_ed_knm": 0.0,
            }
            for index in range(50)
        ]
    )
    fatigue_catalog, tendon_detail_id = fatigue_inputs.add_entry(
        fatigue_inputs.default_catalog(),
        preset=fatigue_inputs.PRESET_2005_PRETENSION,
    )
    assert tendon_detail_id == "F2"
    tables = {
        "corners_base": corners,
        "hole_base": pd.DataFrame(
            columns=["x (mm)", "y (mm)"], dtype="float64"
        ),
        "bars_base": bars,
        "tendons_base": tendons,
        load_cases.PLASTIC_TABLE_KEY: plastic,
        load_cases.ELASTIC_TABLE_KEY: elastic,
        fatigue_inputs.SPECTRUM_TABLE_KEY: spectra,
    }
    for key in bridge_inputs.TABLE_KEYS:
        tables[key] = bridge_inputs.empty_table(key)
    scalars = {
        "mode": "Both",
        "fatigue_on": True,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": False,
        fatigue_inputs.DETAIL_CATALOG_KEY: fatigue_catalog,
        fatigue_inputs.BASIS_KEY: fatigue_inputs.default_basis(),
        "rep_proj_no": "PR12C-RUNTIME-DENSE",
    }
    return project_io.dump_project(
        tables, scalars, app_version="0.91", revision="pr12c-runtime"
    )


def test_dense_browser_fixture_is_current_and_valid(tmp_path):
    import fatigue_inputs
    import load_cases
    import project_io

    project = dense_current_project_text()
    destination = tmp_path / "dense-project.json"
    destination.write_text(project, encoding="utf-8")
    tables, scalars = project_io.parse_project(project)
    assert len(tables["corners_base"]) == 64
    assert len(tables["bars_base"]) == 256
    assert len(tables["tendons_base"]) == 64
    assert len(tables[load_cases.PLASTIC_TABLE_KEY]) == 200
    assert len(tables[load_cases.ELASTIC_TABLE_KEY]) == 200
    assert len(tables[fatigue_inputs.SPECTRUM_TABLE_KEY]) == 50
    assert scalars["fatigue_on"] is True
    assert destination.stat().st_size > 100_000
