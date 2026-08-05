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
    normalise_stage_selection,
    reset_input_stage_mounts,
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


class _SeedHost:
    def __init__(self):
        self.calls = []

    def number_input(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return kwargs.get("value", 40.0)

    def segmented_control(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return kwargs.get("default")

    def selectbox(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        index = kwargs.get("index", args[2] if len(args) > 2 else 0)
        return args[1][index]


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


def test_nested_stages_cannot_open_when_their_parent_is_closed() -> None:
    host = _Host()
    inactive_parent = InputStage(None, active=False, state={})

    first, second = input_stages(
        inactive_parent.container(), ("first", "second"), "second", state={}
    )

    assert [first.open, second.open] == [False, False]
    second.markdown("hidden")
    assert host.calls == []


def test_unavailable_stage_is_removed_from_every_retained_source() -> None:
    state = {
        "_material_tab": "Fatigue details",
        "_pending_input_events": {"_material_tab": "Fatigue details"},
        "_durable_input_scalars": {"_material_tab": "Fatigue details"},
    }

    selected = normalise_stage_selection(
        state, "_material_tab", ("Concrete", "Mild steel")
    )

    assert selected == "Concrete"
    assert state["_material_tab"] == "Concrete"
    assert "_material_tab" not in state["_pending_input_events"]
    assert state["_durable_input_scalars"]["_material_tab"] == "Concrete"


def test_first_active_mount_seeds_retained_value_then_uses_live_widget() -> None:
    host = _SeedHost()
    state = {"value": 35.0}
    stage = InputStage(host, active=True, state=state)

    assert stage.number_input("Value", 1.0, 200.0, key="value") == 35.0
    assert host.calls[0][1]["value"] == 35.0
    assert state["value"] == 35.0

    state["value"] = 40.0
    assert stage.number_input("Value", 1.0, 200.0, key="value") == 40.0
    assert "value" not in host.calls[1][1]

    reset_input_stage_mounts(state)
    state["value"] = 45.0
    assert stage.number_input("Value", 1.0, 200.0, key="value") == 45.0
    assert host.calls[2][1]["value"] == 45.0


def test_segmented_control_remount_uses_default_not_index() -> None:
    host = _SeedHost()
    state = {"scope": "Selected"}
    stage = InputStage(host, active=True, state=state)

    assert stage.segmented_control(
        "Apply to", ["All", "Selected"], key="scope", required=True
    ) == "Selected"
    assert host.calls[0][1]["default"] == "Selected"
    assert "index" not in host.calls[0][1]


def test_positional_selectbox_index_is_replaced_without_duplication() -> None:
    host = _SeedHost()
    state = {"choice": "B"}
    stage = InputStage(host, active=True, state=state)

    assert stage.selectbox("Choice", ["A", "B"], 0, key="choice") == "B"
    assert host.calls[0][0][2] == 1
    assert "index" not in host.calls[0][1]


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
