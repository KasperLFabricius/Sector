from __future__ import annotations

import json
import pathlib
import sys

import pytest
from streamlit.testing.v1 import AppTest

from app import app_run_probe


ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = str(ROOT / "app" / "sector_app.py")
sys.path.insert(0, str(ROOT / "app"))


class FakeContext:
    def __init__(self, fragment_ids=()):
        self.fragment_ids_this_run = list(fragment_ids)
        self.parallel_coordinator = object()
        self.forwarded = []
        self._enqueue = self.forwarded.append

    def next_run(self, fragment_ids=None):
        if fragment_ids is not None:
            self.fragment_ids_this_run = list(fragment_ids)
        self.parallel_coordinator = object()


class FakeMessage:
    def __init__(self, size):
        self.size = size

    def ByteSize(self):
        return self.size


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " On "])
def test_explicit_true_tokens_enable_probe(value):
    assert app_run_probe.enabled({app_run_probe.ENABLE_ENV: value}) is True


@pytest.mark.parametrize("value", ["", "0", "false", "off", "no", "enabled"])
def test_all_other_tokens_leave_probe_disabled(value):
    assert app_run_probe.enabled({app_run_probe.ENABLE_ENV: value}) is False


def test_disabled_probe_is_exactly_inert(monkeypatch):
    monkeypatch.delenv(app_run_probe.ENABLE_ENV, raising=False)
    monkeypatch.delenv(app_run_probe.OUTPUT_ENV, raising=False)
    state = {}
    context = FakeContext()
    original = context._enqueue

    assert app_run_probe.open_run(state, context=context, now_ns=0) is None
    assert app_run_probe.close_run(state, context=context, now_ns=1) is None
    assert state == {}
    assert context._enqueue == original
    assert app_run_probe.snapshot(state) == {
        "schema_version": 2,
        "enabled": False,
        "history": [],
        "active": None,
        "error": None,
    }


def test_full_run_seals_all_messages_and_final_labels(monkeypatch):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")
    state = {
        "_main_page": "",
        "_input_tab": "",
        "_material_tab": "",
    }
    context = FakeContext()

    assert app_run_probe.open_run(
        state,
        context=context,
        now_ns=1_000_000_000,
        started_utc="2026-08-05T15:30:00+00:00",
    ) == 1
    context._enqueue(FakeMessage(125))
    context._enqueue(FakeMessage(375))
    state.update({
        "_main_page": "Inputs",
        "_input_tab": "2 - Section",
        "_material_tab": "Concrete",
    })
    record = app_run_probe.close_run(
        state, context=context, now_ns=1_750_000_000
    )

    assert [message.size for message in context.forwarded] == [125, 375]
    assert record == {
        "schema_version": 2,
        "run_number": 1,
        "kind": "app",
        "started_utc": "2026-08-05T15:30:00+00:00",
        "interrupted": False,
        "phases": {},
        "forward_message_count": 2,
        "forward_message_bytes": 500,
        "largest_forward_message_bytes": 375,
        "byte_accounting": True,
        "workspace": "Inputs",
        "input_stage": "2 - Section",
        "material_family": "Concrete",
        "duration_ms": pytest.approx(750.0),
    }


def test_fragment_context_never_opens_or_closes_full_run(monkeypatch):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")
    state = {}
    context = FakeContext(("fragment-id",))

    assert app_run_probe.open_run(state, context=context, now_ns=0) is None
    assert app_run_probe.close_run(state, context=context, now_ns=1) is None
    assert state == {}
    assert context.forwarded == []


def test_coalesced_parent_and_nested_queue_records_each_root_once(monkeypatch):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")
    state = {}
    context = FakeContext(("outer-id", "nested-id"))

    assert app_run_probe.open_fragment_run(
        state,
        "inputs",
        context=context,
        fragment_id="outer-id",
        now_ns=0,
    ) == 1
    context._enqueue(FakeMessage(100))
    assert app_run_probe.open_fragment_run(
        state,
        "save_load",
        context=context,
        fragment_id="nested-id",
        now_ns=1_000_000,
    ) is None
    assert app_run_probe.close_fragment_run(
        state,
        context=context,
        fragment_id="nested-id",
        now_ns=2_000_000,
    ) is None
    outer = app_run_probe.close_fragment_run(
        state,
        context=context,
        fragment_id="outer-id",
        now_ns=3_000_000,
    )

    assert outer["fragment_name"] == "inputs"
    assert outer["fragment_id"] == "outer-id"
    assert outer["interrupted"] is False
    assert outer["forward_message_bytes"] == 100

    assert app_run_probe.open_fragment_run(
        state,
        "save_load",
        context=context,
        fragment_id="nested-id",
        now_ns=4_000_000,
    ) == 2
    context._enqueue(FakeMessage(250))
    nested = app_run_probe.close_fragment_run(
        state,
        context=context,
        fragment_id="nested-id",
        now_ns=6_000_000,
    )

    assert nested["fragment_name"] == "save_load"
    assert nested["fragment_id"] == "nested-id"
    assert nested["interrupted"] is False
    assert nested["forward_message_bytes"] == 250
    assert [record["fragment_name"] for record in state[
        app_run_probe.state_keys()[2]
    ]] == ["inputs", "save_load"]


def test_new_streamlit_run_interrupts_unsealed_fragment(monkeypatch):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")
    state = {}
    context = FakeContext(("inputs-id",))

    app_run_probe.open_fragment_run(
        state,
        "inputs",
        context=context,
        fragment_id="inputs-id",
        now_ns=0,
    )
    context.next_run(("analysis-id",))
    assert app_run_probe.open_fragment_run(
        state,
        "analysis",
        context=context,
        fragment_id="analysis-id",
        now_ns=5_000_000,
    ) == 2
    current = app_run_probe.close_fragment_run(
        state,
        context=context,
        fragment_id="analysis-id",
        now_ns=8_000_000,
    )

    history = app_run_probe.snapshot(state)["history"]
    assert [record["fragment_name"] for record in history] == [
        "inputs",
        "analysis",
    ]
    assert [record["interrupted"] for record in history] == [True, False]
    assert current["duration_ms"] == pytest.approx(3.0)


def test_fragment_owner_is_fenced_to_current_queue(monkeypatch):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")
    state = {}
    context = FakeContext(("analysis-id",))

    assert app_run_probe.open_fragment_run(
        state,
        "inputs",
        context=context,
        fragment_id="inputs-id",
        now_ns=0,
    ) is None
    assert app_run_probe.close_fragment_run(
        state,
        context=context,
        fragment_id="inputs-id",
        now_ns=1,
    ) is None
    assert state == {}


def test_fragment_owner_names_are_frozen_even_when_probe_is_disabled(monkeypatch):
    monkeypatch.delenv(app_run_probe.ENABLE_ENV, raising=False)

    with pytest.raises(ValueError, match="Unknown fragment owner"):
        app_run_probe.open_fragment_run({}, "solver")


def test_phases_accumulate_and_cannot_cross_run_boundaries(monkeypatch):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")
    state = {}
    context = FakeContext()

    app_run_probe.open_run(state, context=context, now_ns=0)
    first = app_run_probe.start_phase(state, "preview", now_ns=1_000_000)
    assert app_run_probe.stop_phase(
        state, first, now_ns=4_000_000
    ) == pytest.approx(3.0)
    second = app_run_probe.start_phase(state, "preview", now_ns=5_000_000)
    app_run_probe.stop_phase(state, second, now_ns=10_000_000)
    stale = app_run_probe.start_phase(state, "autosave", now_ns=11_000_000)
    app_run_probe.close_run(state, context=context, now_ns=12_000_000)

    context.next_run()
    app_run_probe.open_run(state, context=context, now_ns=20_000_000)
    assert app_run_probe.stop_phase(
        state, stale, now_ns=25_000_000
    ) is None
    record = app_run_probe.close_run(
        state, context=context, now_ns=30_000_000
    )

    first_record = app_run_probe.snapshot(state)["history"][0]
    assert first_record["phases"]["preview"] == {
        "count": 2,
        "total_ms": pytest.approx(8.0),
        "max_ms": pytest.approx(5.0),
        "last_ms": pytest.approx(5.0),
    }
    assert "autosave" not in record["phases"]


def test_phase_names_are_frozen_even_when_probe_is_disabled(monkeypatch):
    monkeypatch.delenv(app_run_probe.ENABLE_ENV, raising=False)

    with pytest.raises(ValueError, match="Unknown run phase"):
        app_run_probe.start_phase({}, "solver")


def test_forged_phase_token_cannot_publish_an_unknown_phase(monkeypatch):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")
    state = {}
    context = FakeContext()
    app_run_probe.open_run(state, context=context, now_ns=0)

    assert app_run_probe.stop_phase(
        state,
        {"run_number": 1, "name": "solver", "started_ns": 0},
        now_ns=1_000_000,
    ) is None
    record = app_run_probe.close_run(
        state, context=context, now_ns=2_000_000
    )
    assert record["phases"] == {}


def test_superseded_full_run_is_retained_as_interrupted(monkeypatch):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")
    state = {}
    context = FakeContext()

    app_run_probe.open_run(state, context=context, now_ns=0)
    context._enqueue(FakeMessage(10))
    app_run_probe.open_run(state, context=context, now_ns=5_000_000)
    context._enqueue(FakeMessage(20))
    app_run_probe.close_run(state, context=context, now_ns=12_000_000)

    history = app_run_probe.snapshot(state)["history"]
    assert [record["run_number"] for record in history] == [1, 2]
    assert [record["interrupted"] for record in history] == [True, False]
    assert [record["forward_message_bytes"] for record in history] == [10, 20]


def test_history_is_bounded(monkeypatch):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")
    state = {}
    context = FakeContext()

    for number in range(1, app_run_probe.HISTORY_LIMIT + 4):
        app_run_probe.open_run(state, context=context, now_ns=number * 10)
        app_run_probe.close_run(state, context=context, now_ns=number * 10 + 1)

    history = app_run_probe.snapshot(state)["history"]
    assert len(history) == app_run_probe.HISTORY_LIMIT
    assert history[0]["run_number"] == 4
    assert history[-1]["run_number"] == app_run_probe.HISTORY_LIMIT + 3


def test_message_accounting_failure_still_forwards_original(monkeypatch):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")
    state = {}
    context = FakeContext()

    class BrokenMessage:
        def ByteSize(self):
            raise RuntimeError("size unavailable")

    message = BrokenMessage()
    app_run_probe.open_run(state, context=context, now_ns=0)
    context._enqueue(message)
    record = app_run_probe.close_run(state, context=context, now_ns=1)

    assert context.forwarded == [message]
    assert record["byte_accounting"] is False
    assert record["forward_message_count"] == 0


def test_interrupted_enqueue_is_not_counted_as_browser_output(monkeypatch):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")

    class RerunInterrupt(BaseException):
        pass

    context = FakeContext()

    def interrupt(_message):
        raise RerunInterrupt

    context._enqueue = interrupt
    state = {}
    app_run_probe.open_run(state, context=context, now_ns=0)

    with pytest.raises(RerunInterrupt):
        context._enqueue(FakeMessage(500))

    record = app_run_probe.close_run(state, context=context, now_ns=1)
    assert record["forward_message_count"] == 0
    assert record["forward_message_bytes"] == 0
    assert record["largest_forward_message_bytes"] == 0
    assert record["byte_accounting"] is True


def test_broken_state_proxy_cannot_break_public_probe(monkeypatch):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")
    context = FakeContext()

    class BrokenState:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("state unavailable")

        def pop(self, *_args, **_kwargs):
            raise RuntimeError("state unavailable")

        def __setitem__(self, _key, _value):
            raise RuntimeError("state unavailable")

    state = BrokenState()
    assert app_run_probe.open_run(state, context=context, now_ns=0) is None
    assert app_run_probe.close_run(state, context=context, now_ns=1) is None
    assert app_run_probe.snapshot(state)["error"] == "state unavailable"


def test_optional_jsonl_is_local_and_exact(monkeypatch, tmp_path):
    destination = tmp_path / "app-runs.jsonl"
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "true")
    monkeypatch.setenv(app_run_probe.OUTPUT_ENV, str(destination))
    state = {}
    context = FakeContext()

    app_run_probe.open_run(
        state,
        context=context,
        now_ns=0,
        started_utc="2026-08-05T15:30:00+00:00",
    )
    context._enqueue(FakeMessage(42))
    record = app_run_probe.close_run(
        state, context=context, now_ns=2_000_000
    )

    assert json.loads(destination.read_text(encoding="utf-8")) == record
    assert app_run_probe.snapshot(state)["error"] is None


def test_unwritable_jsonl_path_is_diagnostic_only(monkeypatch, tmp_path):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")
    monkeypatch.setenv(
        app_run_probe.OUTPUT_ENV, str(tmp_path / "missing" / "runs.jsonl")
    )
    state = {}
    context = FakeContext()

    app_run_probe.open_run(state, context=context, now_ns=0)
    record = app_run_probe.close_run(state, context=context, now_ns=1)

    assert record["duration_ms"] == pytest.approx(0.000001)
    assert app_run_probe.snapshot(state)["error"].startswith("FileNotFoundError:")


def test_snapshot_is_detached(monkeypatch):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")
    state = {}
    context = FakeContext()
    app_run_probe.open_run(state, context=context, now_ns=0)

    first = app_run_probe.snapshot(state)
    first["active"]["workspace"] = "mutated"
    assert app_run_probe.snapshot(state)["active"]["workspace"] == ""


def test_probe_encloses_every_top_level_streamlit_message():
    source = pathlib.Path(APP).read_text(encoding="utf-8")
    opened = source.index("app_run_probe.open_run(st.session_state)")
    page_config = source.index("st.set_page_config(")
    logo = source.index("st.sidebar.image(")
    title = source.index("st.title(")
    caption = source.index("st.caption(")
    closed = source.rindex("app_run_probe.close_run(st.session_state)")

    assert source.count("app_run_probe.open_run") == 1
    assert source.count("app_run_probe.close_run") == 1
    assert opened < page_config < logo < title < caption < closed
    assert not source[closed:].strip().removeprefix(
        "app_run_probe.close_run(st.session_state)"
    ).strip()


def test_all_fragment_owners_are_explicit_and_bounded():
    source = pathlib.Path(APP).read_text(encoding="utf-8")
    expected = {"inputs", "save_load", "report", "quick_section", "analysis"}

    assert set(app_run_probe.FRAGMENT_NAMES) == expected
    assert {
        name
        for name in expected
        if f'open_fragment_run(st.session_state, "{name}")' in source
    } == expected
    assert source.count("app_run_probe.open_fragment_run") == len(expected)
    assert source.count("app_run_probe.close_fragment_run") == 10

    for marker in (
        'def _save_load_panel()',
        'def _report_panel(input_signature)',
        'def _quick_section_viewport()',
        'def _input_workspace()',
        'def _analysis_workspace(inp)',
    ):
        body = source[source.index(marker):]
        next_definition = body.find("\ndef ", 1)
        if next_definition >= 0:
            body = body[:next_definition]
        assert "app_run_probe.open_fragment_run" in body
        assert "app_run_probe.close_fragment_run" in body


def test_phase_labels_and_structural_placement_are_frozen():
    source = pathlib.Path(APP).read_text(encoding="utf-8")

    assert app_run_probe.PHASE_NAMES == (
        "startup",
        "pane_construction",
        "normalization",
        "input_assembly",
        "preview",
        "autosave",
    )
    assert source.index('start_phase(st.session_state, "startup")') < source.index(
        "st.set_page_config("
    )
    assert source.index(
        "app_run_probe.stop_phase(st.session_state, _startup_probe)"
    ) < source.index("main_page = st.segmented_control(")
    assert "_measured_autosave()" in source


def test_disabled_live_app_creates_no_probe_state(monkeypatch):
    monkeypatch.delenv(app_run_probe.ENABLE_ENV, raising=False)
    monkeypatch.delenv(app_run_probe.OUTPUT_ENV, raising=False)

    app = AppTest.from_file(APP).run(timeout=30)

    assert not app.exception
    assert all(key not in app.session_state for key in app_run_probe.state_keys())


def test_enabled_live_app_seals_complete_record(monkeypatch):
    monkeypatch.setenv(app_run_probe.ENABLE_ENV, "1")
    monkeypatch.delenv(app_run_probe.OUTPUT_ENV, raising=False)

    app = AppTest.from_file(APP).run(timeout=30)

    assert not app.exception
    history = app.session_state[app_run_probe.state_keys()[2]]
    assert len(history) == 1
    record = history[0]
    assert record["kind"] == "app"
    assert record["workspace"] == "Inputs"
    assert record["input_stage"] == "1 " + chr(0x00B7) + " Analysis settings"
    assert record["material_family"] == "Concrete"
    assert record["forward_message_count"] > 0
    assert record["forward_message_bytes"] > 0
    assert record["largest_forward_message_bytes"] > 0
    assert record["byte_accounting"] is True
    assert record["interrupted"] is False
    assert {
        "startup",
        "pane_construction",
        "normalization",
        "input_assembly",
        "autosave",
    }.issubset(record["phases"])


def test_probe_state_is_excluded_from_current_project_schema():
    import project_io

    assert not set(app_run_probe.state_keys()).intersection(project_io.SCALAR_KEYS)
    assert not set(app_run_probe.state_keys()).intersection(project_io.TABLE_KEYS)
