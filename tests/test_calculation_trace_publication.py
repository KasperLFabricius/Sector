"""PR-08E publication, fingerprint, context and renderer contracts."""

from __future__ import annotations

import copy
import dataclasses
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import bridge_analysis  # noqa: E402
import bridge_inputs  # noqa: E402
import fatigue_analysis  # noqa: E402
import calculation_trace_publication as publication  # noqa: E402
import case_analysis  # noqa: E402
import project_io  # noqa: E402
from sector import bridge  # noqa: E402
from sector.calculation_trace import (  # noqa: E402
    TraceBundle,
    TraceValidationError,
    seal_bundle,
)
from tests.test_fatigue_analysis import _base as _fatigue_input  # noqa: E402


INPUT_SHA = "a" * 64


def _bridge_input():
    return {
        "section": None,
        "bridge_standard": bridge.EN1992_2_BASE,
        bridge_inputs.BRITTLE_TABLE_KEY: [{
            "region_id": "bottom",
            "m_rep_knm": 1000.0,
            "z_s_m": 0.8,
            "f_yk_mpa": 500.0,
            "as_provided_mm2": 2600.0,
        }],
        bridge_inputs.BOX_WALL_TABLE_KEY: None,
        bridge_inputs.MINIMUM_CRACK_TABLE_KEY: None,
    }


def _published_bridge():
    inp = _bridge_input()
    result = {"bridge": bridge_analysis.run(inp)}
    publication.attach_calculation_traces(
        inp, result, input_sha256=INPUT_SHA,
    )
    return inp, result


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


def test_bridge_publication_is_exact_complete_and_renderer_neutral():
    inp, result = _published_bridge()
    records = publication.published_calculations(result, inp)
    assert len(records) == 1
    record = records[0]
    assert record.input_sha256 == INPUT_SHA
    assert record.calculation.coverage_id == "ct-011"
    rows = publication.format_trace_rows(record.calculation)
    assert len(rows) == 12
    assert tuple(row["sequence"] for row in rows) == tuple(range(1, 13))
    assert rows[-1]["role"] == "final_result"
    assert rows[-1]["state"] == "finite"
    assert any(
        "DS/EN 1992-2:2005 + AC:2008" in row["source"]
        and "clause 6.1(109)-(110)" in row["source"]
        for row in rows
    )
    label = publication.calculation_label(record)
    assert "single" in label
    assert "u616e616c79736973" not in label
    assert publication.published_errors(result) == ()


def test_fatigue_publication_uses_the_retained_wrapper_and_is_not_masked():
    inp = _fatigue_input(fatigue_check_concrete=False)
    result = {"fatigue": fatigue_analysis.run_analysis(inp)}
    publication.attach_calculation_traces(
        inp, result, input_sha256=INPUT_SHA,
    )
    records = publication.published_calculations(result, inp)
    assert records
    assert {item.calculation.coverage_id for item in records} == {"ct-010"}
    assert publication.published_errors(result) == ()


def test_result_and_bundle_tampering_fail_before_rendering():
    inp, result = _published_bridge()
    changed_result = copy.deepcopy(result)
    changed_result["bridge"]["calculations"]["brittle_method_b"]["rows"][0][
        "as_required_mm2"
    ] += 1.0
    with pytest.raises(TraceValidationError, match="retained result"):
        publication.published_calculations(changed_result, inp)

    changed_trace = copy.deepcopy(result)
    changed_trace["calculation_traces"]["bundles"][0]["calculations"][0][
        "title"
    ] = "Coherently unsealed title mutation"
    with pytest.raises(TraceValidationError, match="content seal"):
        publication.published_calculations(changed_trace, inp)

    resealed = copy.deepcopy(result)
    publication_value = resealed[publication.PUBLICATION_KEY]
    candidate = TraceBundle.from_dict(publication_value["bundles"][0])
    changed_calculation = dataclasses.replace(
        candidate.calculations[0], title="Coherently resealed title mutation"
    )
    publication_value["bundles"][0] = seal_bundle(dataclasses.replace(
        candidate,
        calculations=(changed_calculation, *candidate.calculations[1:]),
        content_sha256="",
    )).to_dict()
    publication_value["content_sha256"] = publication._publication_content_sha256(
        publication_value
    )
    with pytest.raises(TraceValidationError, match="authoritative input replay"):
        publication.published_calculations(resealed, inp)


def test_one_family_publication_failure_is_transparent_and_local(monkeypatch):
    inp = _bridge_input()
    result = {"bridge": bridge_analysis.run(inp)}

    def reject(*args, **kwargs):
        raise TraceValidationError("focused CT-011 rejection")

    monkeypatch.setattr(publication, "build_bridge_trace_family", reject)
    publication.attach_calculation_traces(
        inp, result, input_sha256=INPUT_SHA,
    )
    assert publication.published_calculations(result, inp) == ()
    errors = publication.published_errors(result)
    assert [(item.coverage_id, item.message) for item in errors] == [
        ("ct-011", "focused CT-011 rejection")
    ]
    assert result["bridge"]["calculations"]


def test_all_family_adapters_use_the_frozen_order_and_exact_wrapper_shapes(
    monkeypatch,
):
    calls = []
    functions = (
        ("build_plastic_capacity_trace_family", "ct-002"),
        ("build_shear_trace_family", "ct-006"),
        ("build_torsion_trace_family", "ct-007"),
        ("build_detailing_trace_family", "ct-008"),
        ("build_crack_trace_family", "ct-009"),
        ("build_fatigue_trace_family", "ct-010"),
        ("build_bridge_trace_family", "ct-011"),
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
    assert [item[0] for item in calls] == [
        "ct-002", "ct-006", "ct-007", "ct-008", "ct-009", "ct-010",
        "ct-011",
    ]
    by_coverage = {coverage: args for coverage, args, _kwargs in calls}
    assert by_coverage["ct-006"][1] is result["shear"]
    assert by_coverage["ct-010"][1] == {"fatigue": result["fatigue"]}
    assert by_coverage["ct-011"][1] == {"bridge": result["bridge"]}


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
