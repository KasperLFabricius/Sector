"""PR-08E publication, fingerprint, context and renderer contracts."""

from __future__ import annotations

import copy
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import calculation_trace_publication as publication  # noqa: E402
import case_analysis  # noqa: E402
import project_io  # noqa: E402


INPUT_SHA = "a" * 64

@pytest.mark.parametrize(
    ("first", "second"),
    [
        (True, 1),
        (1, 1.0),
        ([1.0], (1.0,)),
        (np.float32(1.0), np.float64(1.0)),
        (np.array([1.0], dtype="float32"), np.array([1.0], dtype="float64")),
    ],
)
def test_result_fingerprint_retains_concrete_type(first, second):
    assert project_io.result_sha256(first) != project_io.result_sha256(second)


def test_result_fingerprint_is_order_independent_and_excludes_trace_recursively():
    first = {
        "b": pd.DataFrame({"x": [1.0], "label": ["one"]}),
        "a": {"value": -0.0},
    }
    second = {
        "a": {"calculation_traces": {"untrusted": object()}, "value": -0.0},
        "b": pd.DataFrame({"x": [1.0], "label": ["one"]}),
        "calculation_traces": {"different": object()},
    }
    assert project_io.result_sha256(first) == project_io.result_sha256(second)
    changed = copy.deepcopy(second)
    changed["a"]["value"] = 0.0
    assert project_io.result_sha256(changed) != project_io.result_sha256(first)


def test_remaining_family_adapters_use_the_frozen_order_and_exact_wrapper_shapes(
    monkeypatch,
):
    calls = []
    functions = (
        ("build_plastic_capacity_trace_family", "ct-002"),
    )

    for function_name, coverage_id in functions:
        def record(*args, _coverage_id=coverage_id, **kwargs):
            calls.append((_coverage_id, args, kwargs))
            return None

        monkeypatch.setattr(publication, function_name, record)

    result = {
        "plastic": {"interaction": {"x": {}, "y": {}}},
        "elastic": {"retained": True},
        "shear": {"retained": True},
        "torsion": {"retained": True},
        "clear_spacing": {"retained": True},
        "fatigue": {"retained": True},
        "bridge": {"retained": True},
    }
    publication.attach_calculation_traces(
        {"interaction": True}, result, input_sha256=INPUT_SHA,
    )
    assert [item[0] for item in calls] == ["ct-002"]
    assert publication.PUBLICATION_KEY not in result


def test_case_context_pins_family_position_name_and_signature():
    entry = {
        "name": "ULS-07",
        "signature": ("ULS-07", "bridge", -25.0, True),
    }
    first = case_analysis.trace_context("plastic", 2, entry)
    second = case_analysis.trace_context("plastic", 2, copy.deepcopy(entry))
    assert first == second
    assert first == {
        "analysis": "case-table",
        "family": "plastic",
        "case_index": 3,
        "case_name": "ULS-07",
        "case_signature_sha256": first["case_signature_sha256"],
    }
    moved = case_analysis.trace_context("plastic", 3, entry)
    renamed = case_analysis.trace_context(
        "plastic", 2, dict(entry, name="ULS-08")
    )
    assert moved != first
    assert renamed != first
    with pytest.raises(ValueError, match="tuple signature"):
        case_analysis.trace_context("plastic", 0, dict(entry, signature=list(
            entry["signature"]
        )))
