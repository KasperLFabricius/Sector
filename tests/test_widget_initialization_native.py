"""Exact default and loaded input identity across native owner-page mounts."""

import base64
import dataclasses
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import project_io

APP = str(ROOT / "app" / "sector_app.py")
PAGES = (
    "section",
    "materials",
    "actions",
    "settings",
    "results",
    "report",
    "project",
    "help",
    "section",
)


def encode(value):
    """Retain types, exact IEEE bytes, shape, masks and all object fields."""
    if (
        value is None
        or isinstance(value, (str, bool, int))
        and not isinstance(value, np.generic)
    ):
        return value
    if isinstance(value, float):
        return {
            "type": "float",
            "ieee754_le": struct.pack("<d", value).hex(),
            "display": repr(value),
            "finite": math.isfinite(value),
        }
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            raw = None
        else:
            raw = base64.b64encode(np.ascontiguousarray(value).tobytes()).decode(
                "ascii"
            )
        masks = {}
        if value.dtype.kind in "fc":
            masks = {
                k: fn(value).tolist()
                for k, fn in [
                    ("nan", np.isnan),
                    ("positive_infinity", np.isposinf),
                    ("negative_infinity", np.isneginf),
                ]
            }
        return {
            "type": "ndarray",
            "dtype": value.dtype.str,
            "shape": list(value.shape),
            "bytes_base64": raw,
            "values": encode(value.tolist()),
            "nonfinite_masks": masks,
        }
    if isinstance(value, np.generic):
        return {
            "type": "numpy_scalar",
            "dtype": value.dtype.str,
            "bytes_base64": base64.b64encode(value.tobytes()).decode("ascii"),
            "value": encode(value.item()),
        }
    if isinstance(value, pd.DataFrame):
        return {
            "type": "DataFrame",
            "columns": encode(list(value.columns)),
            "index": encode(list(value.index)),
            "dtypes": list(map(str, value.dtypes)),
            "records": encode(value.to_dict("records")),
            "attrs": encode(value.attrs),
        }
    if dataclasses.is_dataclass(value):
        return {
            "type": type(value).__module__ + "." + type(value).__qualname__,
            "fields": {
                f.name: encode(getattr(value, f.name))
                for f in dataclasses.fields(value)
            },
        }
    if isinstance(value, dict):
        items = [[encode(k), encode(v)] for k, v in value.items()]
        items.sort(key=lambda p: json.dumps(p[0], sort_keys=True))
        return {"type": "dict", "items": items}
    if isinstance(value, (list, tuple)):
        return {"type": type(value).__name__, "items": [encode(x) for x in value]}
    if isinstance(value, (set, frozenset)):
        items = [encode(x) for x in value]
        items.sort(key=lambda x: json.dumps(x, sort_keys=True))
        return {"type": type(value).__name__, "items": items}
    if isinstance(value, bytes):
        return {"type": "bytes", "base64": base64.b64encode(value).decode("ascii")}
    raise TypeError(f"Unsupported retained type: {type(value)!r}")


def _route(app, page):
    app.session_state["_next_workflow_page"] = page
    app.run()
    assert not app.exception
    assert app.session_state["_workflow_page"] == page


def _assert_inputs(app, expected):
    assert encode(app.session_state["_latest_inputs"]) == expected
    assert not app.session_state.filtered_state.get("results")


def _assert_preferences(app, enabled, minutes):
    state = app.session_state.filtered_state
    assert state["autosave_on"] is enabled
    assert state["autosave_min"] == minutes
    assert state["_durable_input_scalars"]["autosave_on"] is enabled
    assert state["_durable_input_scalars"]["autosave_min"] == minutes
    checkbox = app.checkbox(key="autosave_on")
    number = app.number_input(key="autosave_min")
    assert checkbox.value is enabled
    assert number.value == minutes
    # Verify the actual frontend initialization, rather than only server state.
    assert (
        checkbox.proto.value if checkbox.proto.set_value else checkbox.proto.default
    ) is enabled
    assert (
        number.proto.value if number.proto.set_value else number.proto.default
    ) == minutes


@pytest.mark.parametrize("loaded_custom", [False, True])
def test_complete_inputs_and_preferences_survive_all_native_owner_pages(
    loaded_custom, monkeypatch, tmp_path
):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path / "isolated-recovery"))
    app = AppTest.from_file(APP, default_timeout=180)
    if loaded_custom:
        app.session_state["_pending_project"] = project_io.dump_project(
            {}, {"autosave_on": False, "autosave_min": 7}
        )
    app.run()
    assert not app.exception
    # Capture every canonical field immediately after first render, before any
    # owner navigation can repair a hidden initial-load error.
    expected = encode(app.session_state["_latest_inputs"])
    assert expected is not None
    enabled, minutes = (False, 7) if loaded_custom else (True, 2)
    state = app.session_state.filtered_state
    assert state["autosave_on"] is enabled
    assert state["autosave_min"] == minutes
    for page in PAGES:
        _route(app, page)
        _assert_inputs(app, expected)
        if page == "project":
            _assert_preferences(app, enabled, minutes)
    _route(app, "project")
    _assert_preferences(app, enabled, minutes)
    _assert_inputs(app, expected)
    # Deliberate native widget events must remain authoritative on the same page.
    if not enabled:
        app.checkbox(key="autosave_on").set_value(True).run()
        assert not app.exception
    app.number_input(key="autosave_min").set_value(9).run()
    assert not app.exception
    app.checkbox(key="autosave_on").set_value(False).run()
    assert not app.exception
    _assert_preferences(app, False, 9)
    _assert_inputs(app, expected)
    _route(app, "materials")
    _assert_inputs(app, expected)
    _route(app, "project")
    _assert_preferences(app, False, 9)
    _assert_inputs(app, expected)
