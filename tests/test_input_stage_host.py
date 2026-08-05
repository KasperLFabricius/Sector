"""Independent contracts for the responsive outer input-stage boundary."""

from __future__ import annotations

import pathlib
import sys

import pandas as pd


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from input_stage_host import (  # noqa: E402
    InputStage,
    input_stages,
    live_fragment_value,
)


class _Host:
    def __init__(self, calls=None, name="root"):
        self.calls = calls if calls is not None else []
        self.name = name

    def number_input(self, label, *args, **kwargs):
        self.calls.append((self.name, "number_input", label))
        return 99.0

    def button(self, label, *args, **kwargs):
        self.calls.append((self.name, "button", label))
        return True

    def markdown(self, body, *args, **kwargs):
        self.calls.append((self.name, "markdown", body))

    def columns(self, spec, *args, **kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        self.calls.append((self.name, "columns", count))
        return tuple(_Host(self.calls, f"col-{index}") for index in range(count))

    def container(self, *args, **kwargs):
        self.calls.append((self.name, "container", None))
        return _Host(self.calls, "container")


def test_only_selected_outer_stage_delegates() -> None:
    host = _Host()
    first, second, third = input_stages(
        host, ("first", "second", "third"), "second", state={}
    )

    assert [stage.open for stage in (first, second, third)] == [False, True, False]
    assert first.button("No", key="no") is False
    first.markdown("hidden")
    assert second.number_input("Visible", key="value") == 99.0
    assert all(not child.open for child in third.columns(2))
    assert host.calls == [("root", "number_input", "Visible")]


def test_inactive_values_prefer_event_then_durable_then_live_then_default() -> None:
    state = {
        "event": 1.0,
        "durable": 2.0,
        "live": 3.0,
        "_pending_input_events": {"event": 11.0},
        "_durable_input_scalars": {"event": 10.0, "durable": 22.0},
    }
    stage = InputStage(None, active=False, state=state)

    assert stage.number_input("Event", key="event") == 11.0
    assert stage.number_input("Durable", key="durable") == 22.0
    assert stage.number_input("Live", key="live") == 3.0
    assert stage.selectbox("Choice", ["A", "B"], key="choice") == "A"
    assert stage.toggle("Enabled", value=True, key="enabled") is True
    assert stage.button("Never", key="never", on_click=lambda: 1 / 0) is False


def test_inactive_editor_and_children_are_detached_and_closed() -> None:
    source = pd.DataFrame({"value": [1.0]})
    stage = InputStage(None, active=False, state={})

    result = stage.data_editor(source, key="editor")
    result.loc[0, "value"] = 9.0
    nested = stage.container().tabs(["A", "B"])

    assert source.loc[0, "value"] == 1.0
    assert all(not child.open for child in nested)


def test_live_fragment_edit_controls_project_serialization() -> None:
    state = {"autosave_min": 17}
    durable = {"autosave_min": 5, "fallback": "retained"}

    assert live_fragment_value(state, durable, "autosave_min") == 17
    assert live_fragment_value(state, durable, "fallback") == "retained"
