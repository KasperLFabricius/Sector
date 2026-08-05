"""Active-only Streamlit stage containers backed by retained input state."""

from __future__ import annotations

import copy
from collections.abc import Sequence


_INERT_ACTIONS = frozenset(
    {"button", "download_button", "form_submit_button", "link_button"}
)


def _detached(value):
    if hasattr(value, "copy"):
        try:
            return value.copy(deep=True)
        except TypeError:
            try:
                return value.copy()
            except TypeError:
                pass
    return copy.deepcopy(value)


def _selected_option(args, kwargs):
    options = kwargs.get("options", args[1] if len(args) > 1 else ())
    options = list(options or ())
    index = kwargs.get("index", 0)
    if index is None or not options:
        return None
    return options[index]


def _declared_default(method, args, kwargs):
    if method in {"radio", "selectbox", "segmented_control", "pills"}:
        return _selected_option(args, kwargs)
    if method == "multiselect":
        return kwargs.get("default", args[2] if len(args) > 2 else [])
    if method == "select_slider":
        return kwargs.get("value", _selected_option(args, kwargs))
    if method in {"checkbox", "toggle"}:
        return kwargs.get("value", args[1] if len(args) > 1 else False)
    if method in {"text_input", "text_area"}:
        return kwargs.get("value", args[1] if len(args) > 1 else "")
    if method in {"number_input", "slider"}:
        value = kwargs.get("value", args[3] if len(args) > 3 else None)
        if value is None:
            value = kwargs.get("min_value", args[1] if len(args) > 1 else 0)
        return value
    if method in {"date_input", "time_input", "color_picker"}:
        return kwargs.get("value", args[1] if len(args) > 1 else None)
    return None


def _retained_widget_value(method, args, kwargs, state):
    """Reconstruct an inactive widget value without mounting the widget."""

    if method in _INERT_ACTIONS:
        return False
    if method == "data_editor":
        return _detached(args[0] if args else kwargs.get("data"))
    if method in {"file_uploader", "camera_input", "audio_input"}:
        return None

    key = kwargs.get("key")
    if key is not None:
        pending = state.get("_pending_input_events", {})
        durable = state.get("_durable_input_scalars", {})
        for source in (pending, durable, state):
            if key in source:
                value = _detached(source[key])
                state[key] = _detached(value)
                return value

    value = _detached(_declared_default(method, args, kwargs))
    if key is not None and value is not None:
        state[key] = _detached(value)
    return value


class InputStage:
    """A Streamlit-like container that delegates only for the selected stage."""

    def __init__(self, delegate, *, active, state):
        self._delegate = delegate
        self._state = state
        self.open = bool(active)

    def __enter__(self):
        if self.open:
            self._delegate.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.open:
            return self._delegate.__exit__(exc_type, exc_value, traceback)
        return False

    def _child(self, delegate=None):
        return InputStage(delegate, active=self.open, state=self._state)

    def columns(self, spec, *args, **kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        if not self.open:
            return tuple(
                InputStage(None, active=False, state=self._state)
                for _ in range(count)
            )
        return tuple(
            InputStage(item, active=True, state=self._state)
            for item in self._delegate.columns(spec, *args, **kwargs)
        )

    def container(self, *args, **kwargs):
        if not self.open:
            return self._child()
        return self._child(self._delegate.container(*args, **kwargs))

    def expander(self, *args, **kwargs):
        if not self.open:
            return self._child()
        return self._child(self._delegate.expander(*args, **kwargs))

    def empty(self):
        if not self.open:
            return self._child()
        return self._child(self._delegate.empty())

    def tabs(self, labels, *args, **kwargs):
        if not self.open:
            return tuple(
                InputStage(None, active=False, state=self._state)
                for _ in labels
            )
        return tuple(
            InputStage(
                item,
                active=bool(getattr(item, "open", True)),
                state=self._state,
            )
            for item in self._delegate.tabs(labels, *args, **kwargs)
        )

    def __getattr__(self, method):
        if self.open:
            return getattr(self._delegate, method)

        def inactive(*args, **kwargs):
            return _retained_widget_value(method, args, kwargs, self._state)

        return inactive


def input_stages(host, labels: Sequence[str], selected: str, *, state):
    """Return ordered containers with only ``selected`` allowed to delegate."""

    labels = tuple(labels)
    return tuple(
        InputStage(host if label == selected else None,
                   active=label == selected, state=state)
        for label in labels
    )


def live_fragment_value(state, durable, key):
    """Prefer a mounted fragment edit; use the completed draft as fallback."""

    return state[key] if key in state else durable[key]
