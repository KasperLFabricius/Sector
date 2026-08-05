from __future__ import annotations

import json
import math
import pathlib
import sys

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from app import performance_diagnostics as diagnostics


ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = str(ROOT / "app" / "sector_app.py")
sys.path.insert(0, str(ROOT / "app"))


class FakeContext:
    def __init__(self, fragment_ids=()):
        self.fragment_ids_this_run = list(fragment_ids)
        self.forwarded = []
        self._enqueue = self.forwarded.append


class FakeMessage:
    def __init__(self, size):
        self.size = size

    def ByteSize(self):
        return self.size


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " On "])
def test_explicit_true_tokens_enable_local_diagnostics(value):
    assert diagnostics.enabled({diagnostics.ENABLED_ENV: value}) is True


@pytest.mark.parametrize("value", ["", "0", "false", "off", "no", "enabled"])
def test_every_other_token_leaves_diagnostics_disabled(value):
    assert diagnostics.enabled({diagnostics.ENABLED_ENV: value}) is False


def test_disabled_collector_is_inert_and_creates_no_state(monkeypatch):
    monkeypatch.delenv(diagnostics.ENABLED_ENV, raising=False)
    state = {}
    context = FakeContext()
    original_enqueue = context._enqueue

    assert diagnostics.begin_run(state, context=context, now_ns=10) is None
    assert diagnostics.begin_phase(state, "startup", now_ns=20) is None
    assert diagnostics.finish_run(state, now_ns=30) is None
    assert state == {}
    assert context._enqueue == original_enqueue
    assert diagnostics.snapshot(state) == {
        "schema_version": diagnostics.SCHEMA_VERSION,
        "enabled": False,
        "runs": [],
        "current": None,
        "error": None,
    }


def test_run_phase_and_forward_message_identity(monkeypatch):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "1")
    state = {
        "_main_page": "Inputs",
        "_input_tab": "2 - Section",
        "_material_tab": "Concrete",
    }
    context = FakeContext()

    assert diagnostics.begin_run(
        state, context=context, now_ns=1_000_000_000,
        started_utc="2026-08-05T10:00:00+00:00",
    ) == 1
    token = diagnostics.begin_phase(
        state, "normalization", now_ns=1_100_000_000
    )
    context._enqueue(FakeMessage(125))
    context._enqueue(FakeMessage(375))
    assert diagnostics.end_phase(
        state, token, now_ns=1_250_000_000
    ) == pytest.approx(150.0)
    record = diagnostics.finish_run(state, now_ns=1_500_000_000)

    assert context.forwarded[0].size == 125
    assert context.forwarded[1].size == 375
    assert record == {
        "schema_version": 1,
        "run_number": 1,
        "kind": "app",
        "fragment_ids": [],
        "started_utc": "2026-08-05T10:00:00+00:00",
        "interrupted": False,
        "phases": {
            "normalization": {
                "count": 1,
                "total_ms": pytest.approx(150.0),
                "max_ms": pytest.approx(150.0),
                "last_ms": pytest.approx(150.0),
            }
        },
        "forward_message_count": 2,
        "forward_message_bytes": 500,
        "largest_forward_message_bytes": 375,
        "byte_accounting": True,
        "workspace": "Inputs",
        "input_stage": "2 - Section",
        "material_family": "Concrete",
        "duration_ms": pytest.approx(500.0),
    }


def test_completed_run_labels_are_sealed_from_final_state(monkeypatch):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "1")
    state = {
        "_main_page": "",
        "_input_tab": "",
        "_material_tab": "",
    }
    diagnostics.begin_run(state, context=FakeContext(), now_ns=0)
    state.update({
        "_main_page": "Inputs",
        "_input_tab": "2 - Section",
        "_material_tab": "Concrete",
    })

    record = diagnostics.finish_run(state, now_ns=1)

    assert record["workspace"] == "Inputs"
    assert record["input_stage"] == "2 - Section"
    assert record["material_family"] == "Concrete"


def test_phase_accumulation_and_unknown_phase_guard(monkeypatch):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "true")
    state = {}
    diagnostics.begin_run(state, context=FakeContext(), now_ns=0)
    first = diagnostics.begin_phase(state, "preview", now_ns=1_000_000)
    diagnostics.end_phase(state, first, now_ns=6_000_000)
    second = diagnostics.begin_phase(state, "preview", now_ns=10_000_000)
    diagnostics.end_phase(state, second, now_ns=22_000_000)
    record = diagnostics.finish_run(state, now_ns=30_000_000)

    assert record["phases"]["preview"] == {
        "count": 2,
        "total_ms": pytest.approx(17.0),
        "max_ms": pytest.approx(12.0),
        "last_ms": pytest.approx(12.0),
    }
    with pytest.raises(ValueError, match="Unknown performance phase"):
        diagnostics.begin_phase(state, "solver")


def test_superseded_run_is_closed_as_interrupted(monkeypatch):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "yes")
    state = {}
    context = FakeContext(("input-fragment",))
    diagnostics.begin_run(state, context=context, now_ns=100)
    context._enqueue(FakeMessage(20))
    diagnostics.begin_run(state, context=context, now_ns=300)

    first = state[diagnostics.state_keys()[2]][0]
    assert first["run_number"] == 1
    assert first["kind"] == "fragment"
    assert first["fragment_ids"] == ["input-fragment"]
    assert first["interrupted"] is True
    assert first["duration_ms"] == pytest.approx(0.0002)
    assert first["forward_message_bytes"] == 20
    assert state[diagnostics.state_keys()[1]]["run_number"] == 2


def test_completed_run_storage_is_bounded(monkeypatch):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "on")
    state = {}
    context = FakeContext()
    for number in range(1, diagnostics.RUN_LIMIT + 4):
        diagnostics.begin_run(state, context=context, now_ns=number * 10)
        diagnostics.finish_run(state, now_ns=number * 10 + 1)

    runs = diagnostics.snapshot(state)["runs"]
    assert len(runs) == diagnostics.RUN_LIMIT
    assert runs[0]["run_number"] == 4
    assert runs[-1]["run_number"] == diagnostics.RUN_LIMIT + 3


def test_app_and_fragment_finalizers_do_not_cross_boundaries(monkeypatch):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "1")
    state = {}
    app_context = FakeContext()
    fragment_context = FakeContext(("fragment-a",))

    diagnostics.begin_run(state, context=app_context, now_ns=0)
    assert diagnostics.begin_fragment_run(
        state, context=app_context, now_ns=1
    ) == 1
    assert diagnostics.finish_fragment_run(
        state, context=app_context, now_ns=2
    ) is None
    assert diagnostics.finish_app_run(
        state, context=app_context, now_ns=3
    )["kind"] == "app"

    diagnostics.begin_fragment_run(state, context=fragment_context, now_ns=10)
    assert diagnostics.finish_app_run(
        state, context=fragment_context, now_ns=11
    ) is None
    assert diagnostics.finish_fragment_run(
        state, context=fragment_context, now_ns=12
    )["kind"] == "fragment"


def test_missing_streamlit_queue_disables_bytes_without_breaking_run(monkeypatch):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "1")
    state = {}

    class ContextWithoutQueue:
        fragment_ids_this_run = []

    diagnostics.begin_run(state, context=ContextWithoutQueue(), now_ns=10)
    record = diagnostics.finish_run(state, now_ns=20)
    assert record["byte_accounting"] is False
    assert record["forward_message_count"] == 0
    assert record["forward_message_bytes"] == 0


def test_bad_message_size_never_suppresses_the_original_enqueue(monkeypatch):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "1")
    state = {}
    context = FakeContext()
    diagnostics.begin_run(state, context=context, now_ns=0)

    class BadMessage:
        def ByteSize(self):
            raise ValueError("not serializable")

    message = BadMessage()
    context._enqueue(message)
    record = diagnostics.finish_run(state, now_ns=1)
    assert context.forwarded == [message]
    assert record["byte_accounting"] is False
    assert record["forward_message_count"] == 0


def test_unexpected_message_size_failure_never_suppresses_enqueue(monkeypatch):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "1")
    state = {}
    context = FakeContext()
    diagnostics.begin_run(state, context=context, now_ns=0)

    class UnexpectedMessage:
        def ByteSize(self):
            raise RuntimeError("changed Streamlit protobuf internals")

    message = UnexpectedMessage()
    context._enqueue(message)
    record = diagnostics.finish_run(state, now_ns=1)
    assert context.forwarded == [message]
    assert record["byte_accounting"] is False
    assert record["forward_message_count"] == 0


def test_accounting_state_failure_never_suppresses_enqueue(monkeypatch):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "1")
    context = FakeContext()

    class BrokenState:
        def get(self, _key):
            raise RuntimeError("changed state proxy internals")

    assert diagnostics._install_forward_counter(context, BrokenState()) is True
    message = FakeMessage(125)
    context._enqueue(message)
    assert context.forwarded == [message]


def test_json_lines_output_requires_an_explicit_path(monkeypatch, tmp_path):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "1")
    output = tmp_path / "performance.jsonl"
    monkeypatch.setenv(diagnostics.OUTPUT_ENV, str(output))
    state = {"engineering_secret": "must-not-be-recorded"}

    diagnostics.begin_run(
        state, context=FakeContext(), now_ns=0,
        started_utc="2026-08-05T10:00:00+00:00",
    )
    diagnostics.finish_run(state, now_ns=5_000_000)

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["duration_ms"] == pytest.approx(5.0)
    assert "engineering_secret" not in rows[0]
    assert "must-not-be-recorded" not in output.read_text(encoding="utf-8")


def test_unwritable_output_is_a_diagnostic_not_an_app_failure(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "1")
    monkeypatch.setenv(
        diagnostics.OUTPUT_ENV, str(tmp_path / "missing" / "performance.jsonl")
    )
    state = {}
    diagnostics.begin_run(state, context=FakeContext(), now_ns=0)
    record = diagnostics.finish_run(state, now_ns=1)

    assert record["run_number"] == 1
    assert diagnostics.snapshot(state)["error"].startswith("FileNotFoundError:")


def test_snapshot_detaches_current_internal_clock(monkeypatch):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "1")
    state = {}
    diagnostics.begin_run(state, context=FakeContext(), now_ns=123)
    snap = diagnostics.snapshot(state)
    assert "_started_ns" not in snap["current"]
    snap["current"]["workspace"] = "changed"
    assert state[diagnostics.state_keys()[1]]["workspace"] == ""


def test_app_wires_every_frozen_phase_and_run_boundary():
    source = (ROOT / "app" / "sector_app.py").read_text(encoding="utf-8")
    startup_call = "_autosave_startup()        # restore"
    for phase in diagnostics.PHASES:
        assert f'"{phase}"' in source
    assert source.index("performance_diagnostics.begin_run(st.session_state)") < (
        source.index(startup_call)
    )
    assert source.index(startup_call) < source.index(
        "performance_diagnostics.end_phase(st.session_state, startup_token)"
    )
    assert source.rindex("performance_diagnostics.finish_app_run") > source.rindex(
        "manual.render_manual_dialog()"
    )
    assert source.count("performance_diagnostics.begin_fragment_run") == 3
    assert source.count("performance_diagnostics.finish_fragment_run") == 4
    assert source.count("_timed_autosave()") == 3  # definition plus two call sites
    quick_section = source[
        source.index("def _quick_section_viewport"):
        source.index("def _modular_ratio_readout")
    ]
    assert quick_section.count("finish_fragment_run(st.session_state)") == 3
    apply_start = quick_section.index("if apply:")
    apply_finish = quick_section.index(
        "finish_fragment_run(st.session_state)", apply_start
    )
    assert quick_section.index(
        '_reseed_table("tendons_base"', apply_start
    ) < apply_finish
    assert apply_finish < quick_section.index("st.rerun()", apply_start)
    analysis = source[
        source.index("def _analysis_workspace"):
        source.index("# Layout", source.index("def _analysis_workspace"))
    ]
    stale_snapshot_error = analysis.index(
        '"The stale calculation has no matching input snapshot.'
    )
    stale_snapshot_return = analysis.index("        return", stale_snapshot_error)
    assert analysis.index(
        "performance_diagnostics.finish_fragment_run(st.session_state)",
        stale_snapshot_error,
    ) < stale_snapshot_return
    assert analysis.count("\n        return") == 1
    assert analysis.count("performance_diagnostics.finish_fragment_run") == 2


def test_disabled_live_app_creates_no_diagnostic_state(monkeypatch):
    monkeypatch.delenv(diagnostics.ENABLED_ENV, raising=False)
    monkeypatch.delenv(diagnostics.OUTPUT_ENV, raising=False)
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()

    assert not at.exception
    assert all(key not in at.session_state for key in diagnostics.state_keys())


def test_enabled_live_app_records_active_phases_and_real_forward_bytes(
    monkeypatch
):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "1")
    monkeypatch.delenv(diagnostics.OUTPUT_ENV, raising=False)
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()

    assert not at.exception
    first = at.session_state[diagnostics.state_keys()[2]][-1]
    assert first["kind"] == "app"
    assert first["workspace"] == "Inputs"
    assert first["byte_accounting"] is True
    assert first["forward_message_count"] > 0
    assert first["forward_message_bytes"] > 0
    assert {
        "startup", "pane_construction", "normalization",
        "input_assembly", "autosave",
    }.issubset(first["phases"])
    assert "preview" not in first["phases"]

    stage = at.selectbox(key="_input_tab")
    section_label = next(value for value in stage.options if "Section" in value)
    stage.set_value(section_label).run()
    assert not at.exception
    second = at.session_state[diagnostics.state_keys()[2]][-1]
    assert second["run_number"] == first["run_number"] + 1
    assert second["input_stage"] == section_label
    assert "preview" in second["phases"]
    assert second["phases"]["preview"]["count"] == 1


def test_diagnostics_are_excluded_from_current_project_persistence(monkeypatch):
    monkeypatch.setenv(diagnostics.ENABLED_ENV, "true")
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    assert not at.exception

    import project_io

    assert not set(diagnostics.state_keys()).intersection(project_io.SCALAR_KEYS)
    assert not set(diagnostics.state_keys()).intersection(project_io.PROJECT_TABLE_KEYS)
    project = project_io.dump_project(
        {
            key: at.session_state[key]
            for key in project_io.PROJECT_TABLE_KEYS
            if key in at.session_state
        },
        {
            key: at.session_state[key]
            for key in project_io.SCALAR_KEYS
            if key in at.session_state
        },
    )
    assert "performance_diagnostic" not in project
    assert diagnostics.ENABLED_ENV not in project


def _dense_browser_project_text():
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
                "x (mm)": -700.0 + 1400.0 * (index % 16) / 15.0,
                "y (mm)": -700.0 + 1400.0 * (index // 16) / 15.0,
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
                "description": "Dense browser performance action",
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
                "description": "Dense browser performance action",
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
                "description": "Dense browser performance bin",
                "cycles": 10000.0 + 100.0 * index,
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
        "rep_proj_no": "PR12C-DENSE-BROWSER",
    }
    return project_io.dump_project(
        tables, scalars, app_version="0.91", revision="pr12c-browser"
    )


def test_dense_browser_project_fixture_is_current_and_valid(tmp_path):
    import fatigue_inputs
    import load_cases
    import project_io

    project = _dense_browser_project_text()
    destination = tmp_path / "autosave.json"
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
