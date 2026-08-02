"""CT-010a fatigue trace replay and hostile boundary tests."""

from __future__ import annotations

import collections
import copy
import dataclasses
import pathlib
import sys
from contextlib import nullcontext
from unittest import mock

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tests")]

import fatigue_analysis  # noqa: E402
import fatigue_inputs  # noqa: E402
from test_fatigue_analysis import _base  # noqa: E402

from sector.calculation_trace import (  # noqa: E402
    TraceBundle,
    TraceValidationError,
    seal_bundle,
)
from sector.fatigue_trace import (  # noqa: E402
    build_fatigue_trace_family,
    validate_fatigue_trace_family,
)
from sector.fatigue_trace_contract import (  # noqa: E402
    INVALID_KEYS,
    SUCCESS_KEYS,
)
from sector.section import Section  # noqa: E402


INPUT_SHA = "a" * 64
RESULT_SHA = "b" * 64
CONTEXT = {"case": "fatigue", "stage": 8}
_REPLAYS = {}
_AUTO = object()


def _input(*, steel: bool = True, concrete: bool = False):
    inp = _base(
        fatigue_check_steel=steel,
        fatigue_check_concrete=concrete,
    )
    table = inp[fatigue_inputs.SPECTRUM_TABLE_KEY]
    inp[fatigue_inputs.SPECTRUM_TABLE_KEY] = table.iloc[:1].copy()
    return inp


def _output(inp):
    out = {"fatigue": fatigue_analysis.run_analysis(inp)}
    _REPLAYS[id(inp)] = out["fatigue"]
    return out


def _replay(inp, authoritative):
    if authoritative is _AUTO:
        authoritative = _REPLAYS.get(id(inp), _AUTO)
    if authoritative is _AUTO:
        return nullcontext()
    return mock.patch.object(
        fatigue_analysis,
        "run_analysis",
        return_value=authoritative,
    )


def _build(inp, out, *, context=CONTEXT, authoritative=_AUTO):
    with _replay(inp, authoritative):
        return build_fatigue_trace_family(
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context=context,
        )


def _validate(bundle, inp, out, *, input_sha=INPUT_SHA,
              result_sha=RESULT_SHA, context=CONTEXT,
              authoritative=_AUTO):
    with _replay(inp, authoritative):
        return validate_fatigue_trace_family(
            bundle,
            inp,
            out,
            input_sha256=input_sha,
            result_sha256=result_sha,
            context=context,
        )


def _reseal(bundle, mutate):
    payload = bundle.to_dict()
    mutate(payload)
    payload["content_sha256"] = ""
    return seal_bundle(TraceBundle.from_dict(payload))


@pytest.fixture(scope="module")
def fast_case():
    inp = _input()
    out = _output(inp)
    return inp, out, _build(inp, out)


@pytest.fixture(scope="module")
def concrete_case():
    inp = _input(concrete=True)
    out = _output(inp)
    return inp, out, _build(inp, out)


@pytest.fixture(scope="module")
def concrete_only_case():
    inp = _input(steel=False, concrete=True)
    out = _output(inp)
    return inp, out


def test_frozen_output_inventories_have_exact_order_and_count():
    assert len(SUCCESS_KEYS) == len(INVALID_KEYS) == 18
    assert SUCCESS_KEYS[0:3] == ("edition", "checks", "concrete_method")
    assert INVALID_KEYS[0:4] == ("valid", "converged", "passed", "errors")


def test_registry_has_one_member_contract_per_calculation(fast_case):
    _inp, _out, bundle = fast_case
    calculation_ids = tuple(
        calculation.calculation_id for calculation in bundle.calculations
    )
    assert len(calculation_ids) == 3
    assert len(set(calculation_ids)) == len(calculation_ids)
    assert {item.coverage_id for item in bundle.calculations} == {"ct-010"}


def test_exact_bundle_round_trip(fast_case):
    inp, out, bundle = fast_case
    assert _validate(bundle, inp, out) == bundle
    assert _validate(bundle.to_dict(), inp, out) == bundle


def test_stale_input_hash_is_rejected(fast_case):
    inp, out, bundle = fast_case
    with pytest.raises(TraceValidationError):
        _validate(bundle, inp, out, input_sha="c" * 64)


def test_stale_result_hash_is_rejected(fast_case):
    inp, out, bundle = fast_case
    with pytest.raises(TraceValidationError):
        _validate(bundle, inp, out, result_sha="d" * 64)


def test_coherently_resealed_trace_value_is_rejected(fast_case):
    inp, out, bundle = fast_case

    def mutate(payload):
        result = payload["calculations"][0]["steps"][-1]["result"]
        result["value"] += 0.125

    with pytest.raises(TraceValidationError):
        _validate(_reseal(bundle, mutate), inp, out)


@pytest.mark.parametrize("wrapper", [collections.OrderedDict,
                                      collections.UserDict])
def test_success_candidate_requires_exact_builtin_dict(fast_case, wrapper):
    inp, out, _bundle = fast_case
    hostile = {"fatigue": wrapper(out["fatigue"])}
    with pytest.raises(TraceValidationError):
        _build(inp, hostile)


def test_success_key_reordering_is_rejected(fast_case):
    inp, out, _bundle = fast_case
    value = out["fatigue"]
    reordered = {key: value[key] for key in reversed(value)}
    with pytest.raises(TraceValidationError):
        _build(inp, {"fatigue": reordered})


def test_resolved_reinforcement_property_tamper_is_rejected(fast_case):
    inp, out, _bundle = fast_case
    candidate = copy.deepcopy(out["fatigue"])
    first = candidate["reinforcement_properties"][0]
    candidate["reinforcement_properties"] = (
        dataclasses.replace(first, delta_sigma_rsk_mpa=first.delta_sigma_rsk_mpa + 1.0),
        *candidate["reinforcement_properties"][1:],
    )
    with pytest.raises(TraceValidationError):
        _build(inp, {"fatigue": candidate})


def test_coherent_assessment_stress_cannot_bypass_matched_elastic_state(
    fast_case,
):
    inp, out, _bundle = fast_case
    candidate = copy.deepcopy(out["fatigue"])
    spectrum = candidate["spectra"][0]
    assessment = spectrum.reinforcement[0]
    row = assessment.bins[0]
    shifted = dataclasses.replace(
        row,
        stress_long_mpa=row.stress_long_mpa + 1.0,
        stress_total_mpa=row.stress_total_mpa + 1.0,
        stress_total_design_mpa=row.stress_total_design_mpa + 1.0,
    )
    assessment = dataclasses.replace(assessment, bins=(shifted,))
    spectrum = dataclasses.replace(
        spectrum,
        reinforcement=(assessment, *spectrum.reinforcement[1:]),
    )
    candidate["spectra"] = (spectrum,)
    with pytest.raises(TraceValidationError, match="independent proof"):
        _build(inp, {"fatigue": candidate}, authoritative=candidate)


def test_assessment_bin_identity_is_joined_to_state(fast_case):
    inp, out, _bundle = fast_case
    candidate = copy.deepcopy(out["fatigue"])
    spectrum = candidate["spectra"][0]
    assessment = spectrum.reinforcement[0]
    row = dataclasses.replace(assessment.bins[0], bin_name="wrong-bin")
    assessment = dataclasses.replace(assessment, bins=(row,))
    spectrum = dataclasses.replace(
        spectrum,
        reinforcement=(assessment, *spectrum.reinforcement[1:]),
    )
    candidate["spectra"] = (spectrum,)
    with pytest.raises(TraceValidationError, match="bin identity"):
        _build(inp, {"fatigue": candidate}, authoritative=candidate)


def test_disabled_fatigue_is_inapplicable():
    inp = _input()
    inp["fatigue_on"] = False
    assert _build(inp, {"fatigue": None}) is None


def test_concrete_only_valid_output_is_replayed_before_inapplicability(
    concrete_only_case,
):
    inp, out = concrete_only_case
    assert _build(inp, out) is None


def test_concrete_only_empty_spectra_is_rejected(concrete_only_case):
    inp, out = concrete_only_case
    candidate = copy.deepcopy(out["fatigue"])
    candidate["spectra"] = ()
    with pytest.raises(TraceValidationError):
        _build(inp, {"fatigue": candidate})


def test_concrete_only_truncated_spectrum_is_rejected(concrete_only_case):
    inp, out = concrete_only_case
    candidate = copy.deepcopy(out["fatigue"])
    spectrum = candidate["spectra"][0]
    candidate["spectra"] = (
        dataclasses.replace(spectrum, bins=()),
    )
    with pytest.raises(TraceValidationError):
        _build(inp, {"fatigue": candidate})


def test_inapplicable_input_rejects_unrelated_bundle(fast_case):
    _inp, _out, bundle = fast_case
    disabled = _input()
    disabled["fatigue_on"] = False
    with pytest.raises(TraceValidationError):
        _validate(bundle, disabled, {"fatigue": None})


def test_invalid_empty_errors_are_preserved_exactly():
    inp = _input()
    invalid = fatigue_analysis.invalid_result(inp, errors=())
    bundle = _build(inp, {"fatigue": invalid})
    axes = {axis.name: axis.value for axis in bundle.calculations[0].axes}
    assert axes["error_count"] == "0"
    assert _validate(bundle, inp, {"fatigue": invalid}) == bundle


def test_invalid_external_errors_are_preserved_exactly():
    inp = _input()
    errors = ("external preflight A", "external preflight B")
    invalid = fatigue_analysis.invalid_result(inp, errors=errors)
    bundle = _build(inp, {"fatigue": invalid})
    assert all(error in bundle.calculations[0].steps[-1].result.reason
               for error in errors)


def test_invalid_boolean_type_is_checked_before_payload_replay():
    inp = _input()
    invalid = fatigue_analysis.invalid_result(inp, errors=())
    invalid["valid"] = 0
    with pytest.raises(TraceValidationError, match="valid=False"):
        _build(inp, {"fatigue": invalid})


def test_invalid_key_order_is_rejected():
    inp = _input()
    invalid = fatigue_analysis.invalid_result(inp, errors=())
    reordered = {key: invalid[key] for key in reversed(invalid)}
    with pytest.raises(TraceValidationError, match="keys/order"):
        _build(inp, {"fatigue": reordered})


def test_invalid_errors_retain_order_and_type():
    inp = _input()
    invalid = fatigue_analysis.invalid_result(inp, errors=("A", "B"))
    invalid["errors"] = ["A", "B"]
    with pytest.raises(TraceValidationError, match="retained type"):
        _build(inp, {"fatigue": invalid})


def test_bin_description_changes_sealed_input_identity(fast_case):
    inp, _out, bundle = fast_case
    changed = copy.deepcopy(inp)
    table = changed[fatigue_inputs.SPECTRUM_TABLE_KEY]
    table.loc[table.index[0], "description"] = "Changed published description"
    changed_bundle = _build(changed, _output(changed))
    assert changed_bundle.to_dict() != bundle.to_dict()


def test_concrete_material_identity_changes_sealed_input_identity(fast_case):
    inp, _out, bundle = fast_case
    changed = copy.deepcopy(inp)
    changed["concrete_preset"] = "same law, different concrete identity"
    changed_bundle = _build(changed, _output(changed))
    assert changed_bundle.to_dict() != bundle.to_dict()


def test_geometry_vector_changes_sealed_input_identity(fast_case):
    inp, _out, bundle = fast_case
    changed = copy.deepcopy(inp)
    section = changed["section"]
    moved = dataclasses.replace(section.bars[0], x=section.bars[0].x + 0.001)
    changed["section"] = Section(
        section.concrete,
        [moved, *section.bars[1:]],
        section.tendons,
    )
    changed["bar_elements"][0]["x_mm"] += 1.0
    changed_bundle = _build(changed, _output(changed))
    assert changed_bundle.to_dict() != bundle.to_dict()


def test_context_is_part_of_member_identity(fast_case):
    inp, out, bundle = fast_case
    changed = _build(inp, out, context={"case": "fatigue", "stage": 9})
    assert changed.to_dict() != bundle.to_dict()


def test_excluded_concrete_method_value_does_not_enter_ct010a(concrete_case):
    inp, out, bundle = concrete_case
    candidate = copy.deepcopy(out["fatigue"])
    candidate["concrete_method"] += " (excluded value)"
    changed = _build(inp, {"fatigue": candidate})
    assert changed.to_dict() == bundle.to_dict()


@pytest.mark.parametrize("key", ["concrete_method", "concrete_parameters"])
def test_excluded_concrete_sibling_top_type_is_pinned(concrete_case, key):
    inp, out, _bundle = concrete_case
    candidate = copy.deepcopy(out["fatigue"])
    candidate[key] = [candidate[key]]
    with pytest.raises(TraceValidationError, match="retained type"):
        _build(inp, {"fatigue": candidate})


def test_excluded_concrete_result_values_do_not_enter_ct010a(concrete_case):
    inp, out, bundle = concrete_case
    candidate = copy.deepcopy(out["fatigue"])
    spectrum = candidate["spectra"][0]
    result = spectrum.concrete[0]
    numeric = next(
        field.name for field in dataclasses.fields(result)
        if type(getattr(result, field.name)) is float
    )
    result = dataclasses.replace(
        result,
        **{numeric: getattr(result, numeric) + 0.25},
    )
    candidate["spectra"] = (
        dataclasses.replace(
            spectrum,
            concrete=(result, *spectrum.concrete[1:]),
        ),
    )
    changed = _build(inp, {"fatigue": candidate})
    assert changed.to_dict() == bundle.to_dict()


def test_excluded_concrete_result_container_type_is_pinned(concrete_case):
    inp, out, _bundle = concrete_case
    candidate = copy.deepcopy(out["fatigue"])
    spectrum = candidate["spectra"][0]
    candidate["spectra"] = (
        dataclasses.replace(spectrum, concrete=list(spectrum.concrete)),
    )
    with pytest.raises(TraceValidationError, match="retained type"):
        _build(inp, {"fatigue": candidate})


def test_active_input_requires_candidate():
    with pytest.raises(TraceValidationError, match="needs a candidate"):
        _build(_input(), {"fatigue": None})


@pytest.mark.parametrize("inp,out", [([], {}), ({}, [])])
def test_entry_points_reject_non_mapping_boundaries(inp, out):
    with pytest.raises(TraceValidationError, match="mapping"):
        _build(inp, out)
