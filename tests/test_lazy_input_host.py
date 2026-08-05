"""Independent unit contracts for active-only input containers."""

from __future__ import annotations

import pathlib
import sys

import pandas as pd


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from lazy_input_host import LazyContainer, active_panes  # noqa: E402


class _Delegate:
    def __init__(self, calls=None, name="root"):
        self.calls = calls if calls is not None else []
        self.name = name

    def _record(self, method, *args):
        self.calls.append((self.name, method, args))

    def number_input(self, label, *args, **kwargs):
        self._record("number_input", label)
        return 99.0

    def button(self, label, *args, **kwargs):
        self._record("button", label)
        return True

    def markdown(self, body, *args, **kwargs):
        self._record("markdown", body)

    def columns(self, spec, *args, **kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        self._record("columns", count)
        return tuple(
            _Delegate(self.calls, f"column-{index}") for index in range(count)
        )

    def container(self, *args, **kwargs):
        self._record("container")
        return _Delegate(self.calls, "container")


def test_exactly_one_selected_pane_delegates_output_and_children() -> None:
    delegate = _Delegate()
    state = {"retained": 42.0}
    first, second, third = active_panes(
        delegate, ("first", "second", "third"), "second", state=state
    )

    assert not first.open and second.open and not third.open
    assert first.number_input("Inactive", key="retained") == 42.0
    assert second.number_input("Active", key="active") == 99.0
    assert third.button("Ignored", key="ignored") is False
    first.markdown("not emitted")
    inactive_columns = first.columns([1, 1])
    active_columns = second.columns(2)

    assert all(not column.open for column in inactive_columns)
    assert all(column.open for column in active_columns)
    assert delegate.calls == [
        ("root", "number_input", ("Active",)),
        ("root", "columns", (2,)),
    ]


def test_inactive_widgets_seed_declared_defaults_without_callbacks() -> None:
    state = {
        "retained": 1.0,
        "_durable_input_scalars": {"retained": 7.0, "pending": 3.0},
        "_pending_input_events": {"pending": 8.0},
    }
    pane = LazyContainer(None, open_=False, state=state)

    assert pane.number_input("Retained", key="retained") == 7.0
    assert pane.number_input("Pending", key="pending") == 8.0
    assert pane.selectbox("Choice", ["A", "B"], key="choice") == "A"
    assert pane.number_input("Number", 1.0, 9.0, 3.5, key="number") == 3.5
    assert pane.toggle("Enabled", value=True, key="enabled") is True
    assert pane.text_area("Notes", "draft", key="notes") == "draft"
    assert pane.button("Apply", key="apply", on_click=lambda: 1 / 0) is False
    assert {key: state[key] for key in (
        "retained", "pending", "choice", "number", "enabled", "notes"
    )} == {
        "retained": 7.0,
        "pending": 8.0,
        "choice": "A",
        "number": 3.5,
        "enabled": True,
        "notes": "draft",
    }


def test_inactive_editor_value_is_a_detached_copy_and_parent_closes_children() -> None:
    state = {}
    source = pd.DataFrame({"value": [1.0]})
    parent = LazyContainer(None, open_=False, state=state)

    edited = parent.data_editor(source, key="editor")
    edited.loc[0, "value"] = 9.0
    nested = active_panes(parent.container(), ("A", "B"), "A", state=state)

    assert source.loc[0, "value"] == 1.0
    assert all(not pane.open for pane in nested)
