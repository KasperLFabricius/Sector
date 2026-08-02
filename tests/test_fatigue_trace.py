"""Closed-boundary tests for CT-010a reinforcement-fatigue traces."""

from __future__ import annotations

import dataclasses
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_analysis  # noqa: E402
import fatigue_inputs  # noqa: E402
from sector.calculation_trace import TraceValidationError  # noqa: E402
from sector.fatigue_trace import (  # noqa: E402
    build_fatigue_trace_family,
    validate_fatigue_trace_family,
)
from sector.fatigue_trace_contract import (  # noqa: E402
    INVALID_KEYS,
    NORMAL_SUCCESS_KEYS,
    RAW_INPUT_KEYS,
)
from test_fatigue_analysis import _base  # noqa: E402


INPUT_SHA = "1" * 64
RESULT_SHA = "2" * 64


def _fast_input(**overrides):
    inp = _base(fatigue_check_concrete=False)
    inp[fatigue_inputs.SPECTRUM_TABLE_KEY] = (
        inp[fatigue_inputs.SPECTRUM_TABLE_KEY].iloc[:1].copy()
    )
    inp.update(overrides)
    return inp


def _build(inp, payload, *, context=None):
    return build_fatigue_trace_family(
        inp,
        {"fatigue": payload},
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=context,
    )


@pytest.fixture(scope="module")
def fast_case():
    inp = _fast_input()
    return inp, fatigue_analysis.run_analysis(inp)


@pytest.fixture(scope="module")
def concrete_case():
    inp = _base()
    return inp, fatigue_analysis.run_analysis(inp)


def test_contract_inventories_are_frozen():
    assert RAW_INPUT_KEYS[0:4] == (
        "fatigue_on",
        "fatigue_check_steel",
        "fatigue_check_concrete",
        "fatigue_edition",
    )
    assert NORMAL_SUCCESS_KEYS[-4:] == (
        "governing_spectrum",
        "utilisation",
        "converged",
        "passed",
    )
    assert INVALID_KEYS[0:4] == (
        "valid",
        "converged",
        "passed",
        "errors",
    )


def test_builds_one_member_per_spectrum_element_plus_output(fast_case):
    inp, payload = fast_case
    bundle = _build(inp, payload, context={"case": "FAT"})

    assert len(bundle.calculations) == 3
    assert bundle.calculations[-1].final_step_id == (
        "ct-010-reinforcement-output-result"
    )
    assert all(item.coverage_id == "ct-010" for item in bundle.calculations)


def test_round_trip_validation_is_exact(fast_case):
    inp, payload = fast_case
    bundle = _build(inp, payload)

    assert validate_fatigue_trace_family(
        bundle.to_dict(),
        inp,
        {"fatigue": payload},
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    ).to_dict() == bundle.to_dict()


def test_stale_input_digest_is_rejected(fast_case):
    inp, payload = fast_case
    bundle = _build(inp, payload)

    with pytest.raises(TraceValidationError, match="input fingerprint"):
        validate_fatigue_trace_family(
            bundle,
            inp,
            {"fatigue": payload},
            input_sha256="3" * 64,
            result_sha256=RESULT_SHA,
        )


def test_stale_result_digest_is_rejected(fast_case):
    inp, payload = fast_case
    bundle = _build(inp, payload)

    with pytest.raises(TraceValidationError, match="result fingerprint"):
        validate_fatigue_trace_family(
            bundle,
            inp,
            {"fatigue": payload},
            input_sha256=INPUT_SHA,
            result_sha256="3" * 64,
        )


def test_trace_value_tampering_is_rejected(fast_case):
    inp, payload = fast_case
    data = _build(inp, payload).to_dict()
    step = data["calculations"][0]["steps"][-1]
    step["result"]["value"] += 0.01

    with pytest.raises(TraceValidationError):
        validate_fatigue_trace_family(
            data,
            inp,
            {"fatigue": payload},
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_reinforcement_result_tampering_is_rejected(fast_case):
    inp, payload = fast_case
    changed = dict(payload)
    spectrum = payload["spectra"][0]
    reinforcement = list(spectrum.reinforcement)
    reinforcement[0] = dataclasses.replace(
        reinforcement[0], utilisation=reinforcement[0].utilisation + 0.01
    )
    changed["spectra"] = (
        dataclasses.replace(spectrum, reinforcement=tuple(reinforcement)),
    )

    with pytest.raises(TraceValidationError, match="reinforcement"):
        _build(inp, changed)


def test_reinforcement_property_tampering_is_rejected(fast_case):
    inp, payload = fast_case
    changed = dict(payload)
    properties = list(payload["reinforcement_properties"])
    properties[0] = dataclasses.replace(
        properties[0], delta_sigma_rsk_mpa=999.0
    )
    changed["reinforcement_properties"] = tuple(properties)

    with pytest.raises(TraceValidationError, match="reinforcement_properties"):
        _build(inp, changed)


def test_spectrum_container_type_is_pinned(fast_case):
    inp, payload = fast_case
    changed = dict(payload)
    changed["spectra"] = list(payload["spectra"])

    with pytest.raises(TraceValidationError, match="type"):
        _build(inp, changed)


def test_top_level_key_order_is_pinned(fast_case):
    inp, payload = fast_case
    changed = {key: payload[key] for key in reversed(tuple(payload))}

    with pytest.raises(TraceValidationError, match="keys/order"):
        _build(inp, changed)


def test_disabled_input_has_no_trace():
    inp = _fast_input(fatigue_on=False)

    assert build_fatigue_trace_family(
        inp,
        {"fatigue": None},
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    ) is None


def test_disabled_input_rejects_candidate(fast_case):
    inp, payload = fast_case
    changed = dict(inp, fatigue_on=False)

    with pytest.raises(TraceValidationError, match="disabled"):
        _build(changed, payload)


def test_valid_concrete_only_result_is_outside_ct010a():
    inp = _fast_input(
        fatigue_check_steel=False,
        fatigue_check_concrete=True,
    )
    payload = fatigue_analysis.run_analysis(inp)

    assert _build(inp, payload) is None


def test_invalid_payload_preserves_explicit_empty_error_sequence():
    inp = _fast_input(fatigue_gamma_s="bad")
    payload = fatigue_analysis.invalid_result(inp, errors=())

    bundle = _build(inp, payload)

    assert payload["errors"] == ()
    assert bundle.calculations[0].steps[-1].result.state == "failed"


def test_invalid_payload_preserves_external_error_order_and_text():
    inp = _fast_input(fatigue_gamma_s="bad")
    errors = ("external solver failure", "second retained failure")
    payload = fatigue_analysis.invalid_result(inp, errors=errors)

    bundle = _build(inp, payload)
    ids = tuple(step.step_id for step in bundle.calculations[0].steps)

    assert payload["errors"] == errors
    assert any("error-00-" in step_id for step_id in ids)
    assert any("error-01-" in step_id for step_id in ids)


def test_invalid_payload_accepts_malformed_boolean_controls():
    inp = _fast_input(fatigue_check_steel=[])
    payload = fatigue_analysis.invalid_result(inp, errors=("bad switch",))

    assert _build(inp, payload).calculations[0].final_step_id == (
        "ct-010-invalid-result"
    )


def test_changed_invalid_candidate_rejects_existing_bundle():
    inp = _fast_input(fatigue_gamma_s="bad")
    first = fatigue_analysis.invalid_result(inp, errors=("first",))
    second = fatigue_analysis.invalid_result(inp, errors=("second",))
    bundle = _build(inp, first)

    with pytest.raises(TraceValidationError):
        validate_fatigue_trace_family(
            bundle,
            inp,
            {"fatigue": second},
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_invalid_payload_key_order_is_pinned():
    inp = _fast_input(fatigue_gamma_s="bad")
    payload = fatigue_analysis.invalid_result(inp, errors=("bad",))
    changed = {key: payload[key] for key in reversed(tuple(payload))}

    with pytest.raises(TraceValidationError, match="keys/order"):
        _build(inp, changed)


def test_bin_description_changes_trace_identity_with_fixed_outer_hashes():
    first_inp = _fast_input()
    second_inp = _fast_input()
    table = second_inp[fatigue_inputs.SPECTRUM_TABLE_KEY].copy()
    table.loc[table.index[0], fatigue_inputs.DESCRIPTION] = "Changed text"
    second_inp[fatigue_inputs.SPECTRUM_TABLE_KEY] = table
    first = _build(first_inp, fatigue_analysis.run_analysis(first_inp))
    second = _build(second_inp, fatigue_analysis.run_analysis(second_inp))

    assert first.content_sha256 != second.content_sha256


def test_same_law_concrete_ids_change_trace_identity(fast_case):
    inp, payload = fast_case
    first_inp = dict(inp, concrete_material_id="C-A")
    second_inp = dict(inp, concrete_material_id="C-B")

    first = _build(first_inp, payload)
    second = _build(second_inp, payload)

    assert first.content_sha256 != second.content_sha256


def test_raw_scalar_type_changes_trace_identity(fast_case):
    inp, payload = fast_case
    changed = dict(inp, fatigue_gamma_c=type("FloatLike", (float,), {})(1.595))

    first = _build(inp, payload)
    second = _build(changed, payload)

    assert first.content_sha256 != second.content_sha256


def test_context_changes_exact_axes(fast_case):
    inp, payload = fast_case
    first = _build(inp, payload, context={"case": "A"})
    second = _build(inp, payload, context={"case": "B"})

    assert first.content_sha256 != second.content_sha256


def test_concrete_method_value_is_excluded_but_type_is_pinned(
    concrete_case, monkeypatch
):
    inp, payload = concrete_case
    monkeypatch.setattr(fatigue_analysis, "run_analysis", lambda _inp: payload)
    changed = dict(payload, concrete_method="excluded alternative")

    assert _build(inp, changed) is not None

    incompatible = dict(payload, concrete_method=[payload["concrete_method"]])
    with pytest.raises(TraceValidationError, match="type"):
        _build(inp, incompatible)


def test_concrete_parameter_values_are_excluded_but_shape_is_pinned(
    concrete_case, monkeypatch
):
    inp, payload = concrete_case
    monkeypatch.setattr(fatigue_analysis, "run_analysis", lambda _inp: payload)
    changed = dict(payload)
    changed["concrete_parameters"] = dict(payload["concrete_parameters"])
    changed["concrete_parameters"]["fck_mpa"] += 1.0

    assert _build(inp, changed) is not None

    incompatible = dict(payload, concrete_parameters=[])
    with pytest.raises(TraceValidationError, match="type"):
        _build(inp, incompatible)


def test_concrete_result_values_are_excluded_but_container_type_is_pinned(
    concrete_case, monkeypatch
):
    inp, payload = concrete_case
    monkeypatch.setattr(fatigue_analysis, "run_analysis", lambda _inp: payload)
    spectrum = payload["spectra"][0]
    fibres = list(spectrum.concrete)
    fibres[0] = dataclasses.replace(
        fibres[0], damage=fibres[0].damage + 0.01
    )
    changed = dict(payload)
    changed["spectra"] = (
        dataclasses.replace(spectrum, concrete=tuple(fibres)),
        *payload["spectra"][1:],
    )

    assert _build(inp, changed) is not None

    incompatible = dict(payload)
    incompatible["spectra"] = (
        dataclasses.replace(spectrum, concrete=list(spectrum.concrete)),
        *payload["spectra"][1:],
    )
    with pytest.raises(TraceValidationError, match="type"):
        _build(inp, incompatible)


def test_missing_active_candidate_is_rejected():
    inp = _fast_input()

    with pytest.raises(TraceValidationError, match="needs a candidate"):
        build_fatigue_trace_family(
            inp,
            {"fatigue": None},
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_non_mapping_boundaries_are_rejected():
    with pytest.raises(TraceValidationError, match="input mapping"):
        build_fatigue_trace_family(
            [],
            {},
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )
    with pytest.raises(TraceValidationError, match="result mapping"):
        build_fatigue_trace_family(
            {},
            [],
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )
