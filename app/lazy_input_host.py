"""Active-only Streamlit containers backed by a complete session draft."""

from __future__ import annotations

import copy
from collections.abc import Sequence


_FALSE_ACTIONS = frozenset(
    {
        "button",
        "download_button",
        "form_submit_button",
        "link_button",
    }
)


def _copy_value(value):
    if hasattr(value, "copy"):
        try:
            return value.copy(deep=True)
        except TypeError:
            try:
                return value.copy()
            except TypeError:
                pass
    return copy.deepcopy(value)


def _option_default(args, kwargs):
    options = kwargs.get("options")
    if options is None and len(args) > 1:
        options = args[1]
    options = list(options or [])
    index = kwargs.get("index", 0)
    if index is None or not options:
        return None
    return options[index]


def _inactive_widget_value(method, args, kwargs, state):
    """Return one widget's retained value without constructing the widget."""

    if method in _FALSE_ACTIONS:
        return False
    if method == "data_editor":
        return _copy_value(args[0] if args else kwargs.get("data"))

    key = kwargs.get("key")
    if key is not None:
        pending = state.get("_pending_input_events", {})
        durable = state.get("_durable_input_scalars", {})
        if key in pending:
            value = _copy_value(pending[key])
            state[key] = _copy_value(value)
            return value
        if key in durable:
            value = _copy_value(durable[key])
            state[key] = _copy_value(value)
            return value
    if key is not None and key in state:
        return state[key]

    if method in {"radio", "selectbox", "segmented_control", "pills"}:
        value = _option_default(args, kwargs)
    elif method == "multiselect":
        value = kwargs.get("default", args[2] if len(args) > 2 else [])
    elif method == "select_slider":
        value = kwargs.get("value")
        if value is None:
            value = _option_default(args, kwargs)
    elif method in {"checkbox", "toggle"}:
        value = kwargs.get("value", args[1] if len(args) > 1 else False)
    elif method in {"text_input", "text_area"}:
        value = kwargs.get("value", args[1] if len(args) > 1 else "")
    elif method in {"number_input", "slider"}:
        value = kwargs.get("value", args[3] if len(args) > 3 else None)
        if value is None:
            value = kwargs.get("min_value", args[1] if len(args) > 1 else 0)
    elif method in {"date_input", "time_input", "color_picker"}:
        value = kwargs.get("value", args[1] if len(args) > 1 else None)
    elif method in {"file_uploader", "camera_input", "audio_input"}:
        value = None
    else:
        return None

    value = _copy_value(value)
    if key is not None and value is not None:
        state[key] = _copy_value(value)
    return value


class LazyContainer:
    """Delegate only while open; otherwise expose inert Streamlit-like methods."""

    def __init__(self, delegate, *, open_, state):
        self._delegate = delegate
        self._state = state
        self.open = bool(open_)

    def __enter__(self):
        if self.open:
            self._delegate.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.open:
            return self._delegate.__exit__(exc_type, exc_value, traceback)
        return False

    def columns(self, spec, *args, **kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        if not self.open:
            return tuple(
                LazyContainer(None, open_=False, state=self._state)
                for _ in range(count)
            )
        return tuple(
            LazyContainer(item, open_=True, state=self._state)
            for item in self._delegate.columns(spec, *args, **kwargs)
        )

    def container(self, *args, **kwargs):
        if not self.open:
            return LazyContainer(None, open_=False, state=self._state)
        return LazyContainer(
            self._delegate.container(*args, **kwargs),
            open_=True,
            state=self._state,
        )

    def expander(self, *args, **kwargs):
        if not self.open:
            return LazyContainer(None, open_=False, state=self._state)
        return LazyContainer(
            self._delegate.expander(*args, **kwargs),
            open_=True,
            state=self._state,
        )

    def empty(self):
        if not self.open:
            return LazyContainer(None, open_=False, state=self._state)
        return LazyContainer(
            self._delegate.empty(), open_=True, state=self._state
        )

    def tabs(self, labels, *args, **kwargs):
        if not self.open:
            return tuple(
                LazyContainer(None, open_=False, state=self._state)
                for _ in labels
            )
        return tuple(
            LazyContainer(
                item,
                open_=bool(getattr(item, "open", True)),
                state=self._state,
            )
            for item in self._delegate.tabs(labels, *args, **kwargs)
        )

    def __getattr__(self, name):
        if self.open:
            return getattr(self._delegate, name)

        def inert(*args, **kwargs):
            return _inactive_widget_value(name, args, kwargs, self._state)

        return inert


def active_panes(host, labels: Sequence[str], selected: str, *, state):
    """Return ordered wrappers with exactly the selected pane open."""

    labels = tuple(labels)
    if not labels:
        return ()
    parent_open = bool(getattr(host, "open", True))
    delegate = host._delegate if isinstance(host, LazyContainer) else host
    return tuple(
        LazyContainer(
            delegate if parent_open and label == selected else None,
            open_=parent_open and label == selected,
            state=state,
        )
        for label in labels
    )
