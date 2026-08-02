"""CT-010a reinforcement-fatigue trace closure tests."""

from __future__ import annotations

import collections
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
    RAW_CONTROLS,
    SUCCESS_KEYS,
)
from test_fatigue_analysis import _base  # noqa: E402


INPUT_SHA = "1" * 64
RESULT_SHA = "2" * 64


def _fast(**overrides):
    inp = _base(fatigue_check_concrete=False)
    inp[fatigue_inputs.SPECTRUM_TABLE_KEY] = (
        inp[fatigue_inputs.SPECTRUM_TABLE_KEY].iloc[:1].copy()
    )
    inp.update(overrides)
    return inp


def _build(inp, candidate, *, context=None):
    return build_fatigue_trace_family(
        inp,
        {"fatigue": candidate},
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=context,
    )


@pytest.fixture(scope="module")
def fast_case():
    inp = _fast()
    return inp, fatigue_analysis.run_analysis(inp)


@pytest.fixture(scope="module")
def concrete_case():
    inp = _base()
    return inp, fatigue_analysis.run_analysis(inp)


@pytest.fixture(scope="module")
def concrete_only_case():
    inp = _fast(fatigue_check_steel=False, fatigue_check_concrete=True)
    return inp, fatigue_analysis.run_analysis(inp)


def test_frozen_inventories():
    assert SUCCESS_KEYS[0:3] == ("edition", "checks", "concrete_method")
    assert SUCCESS_KEYS[-3:] == ("utilisation", "converged", "passed")
    assert INVALID_KEYS[:4] == ("valid", "converged", "passed", "errors")
    assert "fatigue_gamma_c" in RAW_CONTROLS
    assert "concrete_material_id" in RAW_CONTROLS


def test_member_per_spectrum_element_and_aggregate(fast_case):
    inp, candidate = fast_case
    bundle = _build(inp, candidate, context={"case": "FAT"})

    assert len(bundle.calculations) == 3
    assert bundle.calculations[-1].final_step_id == (
        "ct-010-reinforcement-output-result"
    )
    assert all(item.coverage_id == "ct-010" for item in bundle.calculations)


def test_exact_round_trip(fast_case):
    inp, candidate = fast_case
    bundle = _build(inp, candidate)

    checked = validate_fatigue_trace_family(
        bundle.to_dict(), inp, {"fatigue": candidate},
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
    )
    assert checked.to_dict() == bundle.to_dict()


def test_stale_input_hash_fails(fast_case):
    inp, candidate = fast_case
    bundle = _build(inp, candidate)

    with pytest.raises(TraceValidationError, match="input fingerprint"):
        validate_fatigue_trace_family(
            bundle, inp, {"fatigue": candidate},
            input_sha256="3" * 64, result_sha256=RESULT_SHA,
        )


def test_stale_result_hash_fails(fast_case):
    inp, candidate = fast_case
    bundle = _build(inp, candidate)

    with pytest.raises(TraceValidationError, match="result fingerprint"):
        validate_fatigue_trace_family(
            bundle, inp, {"fatigue": candidate},
            input_sha256=INPUT_SHA, result_sha256="3" * 64,
        )


def test_tampered_trace_fails(fast_case):
    inp, candidate = fast_case
    data = _build(inp, candidate).to_dict()
    data["calculations"][0]["steps"][-1]["result"]["value"] += 0.01

    with pytest.raises(TraceValidationError):
        validate_fatigue_trace_family(
            data, inp, {"fatigue": candidate},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )


@pytest.mark.parametrize("factory", [collections.OrderedDict, collections.UserDict])
def test_successful_top_mapping_type_is_exact(fast_case, factory):
    inp, candidate = fast_case

    with pytest.raises(TraceValidationError, match="type must be dict"):
        _build(inp, factory(candidate))


def test_successful_top_key_order_is_exact(fast_case):
    inp, candidate = fast_case
    changed = {key: candidate[key] for key in reversed(tuple(candidate))}

    with pytest.raises(TraceValidationError, match="keys/order"):
        _build(inp, changed)


def test_reinforcement_value_tampering_fails(fast_case):
    inp, candidate = fast_case
    spectrum = candidate["spectra"][0]
    items = list(spectrum.reinforcement)
    items[0] = dataclasses.replace(
        items[0], utilisation=items[0].utilisation + 0.01
    )
    changed = dict(candidate)
    changed["spectra"] = (
        dataclasses.replace(spectrum, reinforcement=tuple(items)),
    )

    with pytest.raises(TraceValidationError, match="reinforcement"):
        _build(inp, changed)


def test_resolved_property_tampering_fails(fast_case):
    inp, candidate = fast_case
    props = list(candidate["reinforcement_properties"])
    props[0] = dataclasses.replace(props[0], delta_sigma_rsk_mpa=999.0)
    changed = dict(candidate, reinforcement_properties=tuple(props))

    with pytest.raises(TraceValidationError, match="reinforcement_properties"):
        _build(inp, changed)


def test_assessment_stress_is_joined_to_elastic_vector(
    fast_case, monkeypatch
):
    inp, candidate = fast_case
    spectrum = candidate["spectra"][0]
    assessments = list(spectrum.reinforcement)
    first_bin = assessments[0].bins[0]
    wrong = dataclasses.replace(
        first_bin,
        stress_long_mpa=first_bin.stress_long_mpa + 0.5,
    )
    assessments[0] = dataclasses.replace(
        assessments[0], bins=(wrong,)
    )
    coherent_wrong = dict(candidate)
    coherent_wrong["spectra"] = (
        dataclasses.replace(
            spectrum, reinforcement=tuple(assessments)
        ),
    )
    monkeypatch.setattr(
        fatigue_analysis, "run_analysis", lambda _inp: coherent_wrong
    )

    with pytest.raises(TraceValidationError, match="long stress"):
        _build(inp, coherent_wrong)


def test_assessment_bin_identity_is_joined_to_elastic_state(
    fast_case, monkeypatch
):
    inp, candidate = fast_case
    spectrum = candidate["spectra"][0]
    assessments = list(spectrum.reinforcement)
    wrong = dataclasses.replace(
        assessments[0].bins[0], bin_name="wrong-bin"
    )
    assessments[0] = dataclasses.replace(assessments[0], bins=(wrong,))
    coherent_wrong = dict(candidate)
    coherent_wrong["spectra"] = (
        dataclasses.replace(spectrum, reinforcement=tuple(assessments)),
    )
    monkeypatch.setattr(
        fatigue_analysis, "run_analysis", lambda _inp: coherent_wrong
    )

    with pytest.raises(TraceValidationError, match="bin identity"):
        _build(inp, coherent_wrong)


def test_disabled_input_has_no_trace():
    inp = _fast(fatigue_on=False)
    assert build_fatigue_trace_family(
        inp, {"fatigue": None}, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    ) is None


def test_disabled_input_rejects_candidate(fast_case):
    inp, candidate = fast_case
    with pytest.raises(TraceValidationError, match="disabled"):
        _build(dict(inp, fatigue_on=False), candidate)


def test_concrete_only_success_is_validated_before_inapplicability(
    concrete_only_case, monkeypatch
):
    inp, candidate = concrete_only_case
    monkeypatch.setattr(
        fatigue_analysis, "run_analysis", lambda _inp: candidate
    )
    assert _build(inp, candidate) is None

    with pytest.raises(TraceValidationError, match="keys/order"):
        _build(inp, {})


def test_concrete_only_truncated_candidate_fails(
    concrete_only_case, monkeypatch
):
    inp, retained = concrete_only_case
    monkeypatch.setattr(
        fatigue_analysis, "run_analysis", lambda _inp: retained
    )
    candidate = dict(retained)
    candidate.pop("spectra")

    with pytest.raises(TraceValidationError, match="keys/order"):
        _build(inp, candidate)


def test_inapplicable_concrete_only_rejects_bundle(
    concrete_only_case, monkeypatch
):
    inp, candidate = concrete_only_case
    monkeypatch.setattr(
        fatigue_analysis, "run_analysis", lambda _inp: candidate
    )
    unrelated = _build(*_make_invalid())

    with pytest.raises(TraceValidationError, match="inapplicable"):
        validate_fatigue_trace_family(
            unrelated, inp, {"fatigue": candidate},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )


def _make_invalid(errors=("external failure",)):
    inp = _fast(fatigue_gamma_s="bad")
    return inp, fatigue_analysis.invalid_result(inp, errors=errors)


def test_invalid_preserves_explicit_empty_errors():
    inp, candidate = _make_invalid(())
    bundle = _build(inp, candidate)

    assert candidate["errors"] == ()
    assert bundle.calculations[0].steps[-1].result.state == "failed"


def test_invalid_preserves_external_error_order_and_text():
    errors = ("first external error", "second external error")
    inp, candidate = _make_invalid(errors)
    bundle = _build(inp, candidate)
    step_ids = tuple(step.step_id for step in bundle.calculations[0].steps)

    assert candidate["errors"] == errors
    assert any("error-00-" in step_id for step_id in step_ids)
    assert any("error-01-" in step_id for step_id in step_ids)


def test_invalid_branch_precedes_malformed_booleans():
    inp = _fast(fatigue_check_steel=[])
    candidate = fatigue_analysis.invalid_result(inp, errors=("bad switch",))

    assert _build(inp, candidate).calculations[0].final_step_id == (
        "ct-010-invalid-result"
    )


def test_invalid_key_order_fails_as_invalid_not_success():
    inp, candidate = _make_invalid()
    changed = {key: candidate[key] for key in reversed(tuple(candidate))}

    with pytest.raises(TraceValidationError, match="invalid fatigue keys/order"):
        _build(inp, changed)


def test_changed_invalid_errors_reject_old_bundle():
    inp, first = _make_invalid(("first",))
    second = fatigue_analysis.invalid_result(inp, errors=("second",))
    bundle = _build(inp, first)

    with pytest.raises(TraceValidationError):
        validate_fatigue_trace_family(
            bundle, inp, {"fatigue": second}, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_bin_description_changes_internal_identity_with_fixed_outer_hash():
    first_inp = _fast()
    second_inp = _fast()
    table = second_inp[fatigue_inputs.SPECTRUM_TABLE_KEY].copy()
    table.loc[table.index[0], fatigue_inputs.DESCRIPTION] = "changed text"
    second_inp[fatigue_inputs.SPECTRUM_TABLE_KEY] = table

    first = _build(first_inp, fatigue_analysis.run_analysis(first_inp))
    second = _build(second_inp, fatigue_analysis.run_analysis(second_inp))
    assert first.content_sha256 != second.content_sha256


def test_same_law_concrete_id_changes_internal_identity(fast_case):
    inp, candidate = fast_case
    first = _build(dict(inp, concrete_material_id="C-1"), candidate)
    second = _build(dict(inp, concrete_material_id="C-2"), candidate)

    assert first.content_sha256 != second.content_sha256


def test_context_changes_axes_and_seal(fast_case):
    inp, candidate = fast_case
    first = _build(inp, candidate, context={"case": "A"})
    second = _build(inp, candidate, context={"case": "B"})

    assert first.content_sha256 != second.content_sha256


def test_concrete_method_value_excluded_but_type_pinned(
    concrete_case, monkeypatch
):
    inp, candidate = concrete_case
    monkeypatch.setattr(
        fatigue_analysis, "run_analysis", lambda _inp: candidate
    )
    assert _build(inp, dict(candidate, concrete_method="other")) is not None

    with pytest.raises(TraceValidationError, match="type"):
        _build(inp, dict(candidate, concrete_method=["other"]))


def test_concrete_parameters_values_excluded_but_shape_pinned(
    concrete_case, monkeypatch
):
    inp, candidate = concrete_case
    monkeypatch.setattr(
        fatigue_analysis, "run_analysis", lambda _inp: candidate
    )
    parameters = dict(candidate["concrete_parameters"])
    parameters["fck_mpa"] += 1.0
    assert _build(
        inp, dict(candidate, concrete_parameters=parameters)
    ) is not None

    with pytest.raises(TraceValidationError, match="type"):
        _build(inp, dict(candidate, concrete_parameters=[]))


def test_concrete_result_values_excluded_but_container_pinned(
    concrete_case, monkeypatch
):
    inp, candidate = concrete_case
    monkeypatch.setattr(
        fatigue_analysis, "run_analysis", lambda _inp: candidate
    )
    first = candidate["spectra"][0]
    fibres = list(first.concrete)
    fibres[0] = dataclasses.replace(
        fibres[0], damage=fibres[0].damage + 0.01
    )
    changed = dict(candidate)
    changed["spectra"] = (
        dataclasses.replace(first, concrete=tuple(fibres)),
        *candidate["spectra"][1:],
    )
    assert _build(inp, changed) is not None

    incompatible = dict(candidate)
    incompatible["spectra"] = (
        dataclasses.replace(first, concrete=list(first.concrete)),
        *candidate["spectra"][1:],
    )
    with pytest.raises(TraceValidationError, match="type"):
        _build(inp, incompatible)


def test_active_missing_candidate_fails():
    inp = _fast()
    with pytest.raises(TraceValidationError, match="needs a candidate"):
        build_fatigue_trace_family(
            inp, {"fatigue": None}, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_non_mapping_boundaries_fail():
    with pytest.raises(TraceValidationError, match="input mapping"):
        build_fatigue_trace_family(
            [], {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )
    with pytest.raises(TraceValidationError, match="result mapping"):
        build_fatigue_trace_family(
            {}, [], input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )
