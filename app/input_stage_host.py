"""Active-only Streamlit stage containers backed by retained input state."""

from __future__ import annotations

import copy
from collections.abc import Sequence


_INERT_ACTIONS = frozenset(
    {"button", "download_button", "form_submit_button", "link_button"}
)
_VALUE_WIDGETS = frozenset(
    {
        "checkbox",
        "color_picker",
        "date_input",
        "multiselect",
        "number_input",
        "pills",
        "radio",
        "segmented_control",
        "select_slider",
        "selectbox",
        "slider",
        "text_area",
        "text_input",
        "time_input",
        "toggle",
    }
)
_MOUNTED_WIDGET_KEYS = "_mounted_input_stage_widget_keys"


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
    index = kwargs.get("index", args[2] if len(args) > 2 else 0)
    if index is None or not options:
        return None
    return options[index]


def _declared_default(method, args, kwargs):
    if method in {"radio", "selectbox"}:
        return _selected_option(args, kwargs)
    if method in {"segmented_control", "pills"}:
        default = kwargs.get("default")
        if default is None and kwargs.get("required", False):
            return _selected_option(args, kwargs)
        return default
    if method == "multiselect":
        return kwargs.get("default", args[2] if len(args) > 2 else [])
    if method == "select_slider":
        return kwargs.get(
            "value", args[2] if len(args) > 2 else _selected_option(args, kwargs)
        )
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
        mounted = set(state.get(_MOUNTED_WIDGET_KEYS, ()))
        mounted.discard(key)
        state[_MOUNTED_WIDGET_KEYS] = mounted
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


def _seed_arguments(method, args, kwargs, value):
    """Give a remounted Streamlit widget one explicit retained initial value."""

    args = list(args)
    kwargs = dict(kwargs)
    if method in {"radio", "selectbox"}:
        options = list(kwargs.get("options", args[1] if len(args) > 1 else ()))
        if value in options:
            index = options.index(value)
            if len(args) > 2:
                args[2] = index
                kwargs.pop("index", None)
            else:
                kwargs["index"] = index
    elif method in {"segmented_control", "pills"}:
        kwargs["default"] = value
    elif method == "multiselect":
        if len(args) > 2:
            args[2] = value
            kwargs.pop("default", None)
        else:
            kwargs["default"] = value
    elif method == "select_slider":
        if len(args) > 2:
            args[2] = value
            kwargs.pop("value", None)
        else:
            kwargs["value"] = value
    elif method in {"checkbox", "toggle", "text_input", "text_area",
                    "date_input", "time_input", "color_picker"}:
        if len(args) > 1:
            args[1] = value
        else:
            kwargs["value"] = value
    elif method in {"number_input", "slider"}:
        if len(args) > 3:
            args[3] = value
        else:
            kwargs["value"] = value
    return tuple(args), kwargs


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
            delegate = getattr(self._delegate, method)

            def active(*args, **kwargs):
                key = kwargs.get("key")
                mounted = set(self._state.get(_MOUNTED_WIDGET_KEYS, ()))
                if (
                    method in _VALUE_WIDGETS
                    and key is not None
                    and key in self._state
                    and key not in mounted
                ):
                    value = _detached(self._state[key])
                    seeded_args, seeded_kwargs = _seed_arguments(
                        method, args, kwargs, value
                    )
                    self._state.pop(key, None)
                    try:
                        result = delegate(*seeded_args, **seeded_kwargs)
                    except Exception:
                        self._state[key] = value
                        raise
                    self._state.setdefault(key, _detached(result))
                    mounted.add(key)
                    self._state[_MOUNTED_WIDGET_KEYS] = mounted
                    return result
                return delegate(*args, **kwargs)

            return active

        def inactive(*args, **kwargs):
            return _retained_widget_value(method, args, kwargs, self._state)

        return inactive


def input_stages(host, labels: Sequence[str], selected: str, *, state):
    """Return ordered containers with only ``selected`` allowed to delegate."""

    labels = tuple(labels)
    parent_open = bool(getattr(host, "open", True))
    delegate = host._delegate if isinstance(host, InputStage) else host
    return tuple(
        InputStage(
            delegate if parent_open and label == selected else None,
            active=parent_open and label == selected,
            state=state,
        )
        for label in labels
    )


def stateful_input_tabs(
    host,
    labels: Sequence[str],
    *,
    key,
    state,
    on_change="rerun",
    width="stretch",
):
    """Return active-only wrappers around Streamlit's stateful native tabs.

    A stateful ``st.tabs`` call is authoritative only when its keyed selection
    and ``.open`` flags identify the same single tab. Any incomplete or
    contradictory host response closes every stage so hidden input bodies
    cannot execute during a navigation transition.
    """

    labels = tuple(labels)
    if not labels:
        raise ValueError("Stateful input tabs require at least one label")
    if len(set(labels)) != len(labels):
        raise ValueError("Stateful input tab labels must be unique")

    normalise_stage_selection(state, key, labels)
    tabs = tuple(
        host.tabs(
            labels,
            key=key,
            on_change=on_change,
            width=width,
        )
    )
    open_indices = tuple(
        index
        for index, tab in enumerate(tabs)
        if getattr(tab, "open", None) is True
    )
    selected = state.get(key)
    valid_active = (
        len(tabs) == len(labels)
        and len(open_indices) == 1
        and labels[open_indices[0]] == selected
    )
    if not valid_active:
        return tuple(
            InputStage(None, active=False, state=state) for _ in labels
        )

    active_index = open_indices[0]
    return tuple(
        InputStage(
            tab._delegate if isinstance(tab, InputStage) else tab,
            active=index == active_index,
            state=state,
        )
        if index == active_index
        else InputStage(None, active=False, state=state)
        for index, tab in enumerate(tabs)
    )


def normalise_stage_selection(state, key, labels: Sequence[str]):
    """Remove unavailable navigation values from live and retained mirrors."""

    labels = tuple(labels)
    if not labels:
        raise ValueError("A stage selector requires at least one label")
    allowed = set(labels)
    pending = state.get("_pending_input_events", {})
    if pending.get(key) not in allowed:
        pending.pop(key, None)
    durable = state.get("_durable_input_scalars", {})
    if key in durable and durable[key] not in allowed:
        durable[key] = labels[0]
    if state.get(key) not in allowed:
        state.pop(key, None)
    state.setdefault(key, labels[0])
    return state[key]


def reset_input_stage_mounts(state):
    """Mark every input widget unmounted after leaving the Inputs workspace."""

    state.pop(_MOUNTED_WIDGET_KEYS, None)


def live_fragment_value(state, durable, key):
    """Prefer a mounted fragment edit; use the completed draft as fallback."""

    return state[key] if key in state else durable[key]
