"""Hostile closure tests for CT-010a reinforcement fatigue."""

from __future__ import annotations

import dataclasses
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_analysis  # noqa: E402
import fatigue_inputs  # noqa: E402
from test_fatigue_analysis import _base  # noqa: E402
from sector.calculation_trace import (  # noqa: E402
    RESULT_FAILED, RESULT_FINITE, RESULT_POSITIVE_INFINITY,
    TraceValidationError, seal_bundle,
)
from sector.fatigue_trace import (  # noqa: E402
    _damage_from_log, _trace_result, build_fatigue_trace_family,
    validate_fatigue_trace_family,
)


INPUT_HASH = "a" * 64
RESULT_HASH = "b" * 64
CONTEXT = {"load_case": "fatigue-trace-test"}


def _steel_input(**overrides):
    value = _base(fatigue_check_concrete=False)
    value.update(overrides)
    return value


def _build(inp):
    out = fatigue_analysis.run_analysis(inp)
    bundle = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH,
        context=CONTEXT,
    )
    return inp, out, bundle


@pytest.fixture
def example():
    return _build(_steel_input())


def _steps(calculation):
    return {step.step_id: step for step in calculation.steps}


def _ancestors(calculation):
    by_id = _steps(calculation)
    result, pending = set(), [calculation.final_step_id]
    while pending:
        for dependency in by_id[pending.pop()].dependencies:
            if dependency.step_id not in result:
                result.add(dependency.step_id)
                pending.append(dependency.step_id)
    return result


def test_round_trip_reconstructs_exact_bundle(example):
    inp, out, bundle = example
    assert validate_fatigue_trace_family(
        bundle, inp, out, input_sha256=INPUT_HASH,
        result_sha256=RESULT_HASH, context=CONTEXT,
    ) == bundle


def test_inventory_is_element_times_spectrum_plus_aggregate(example):
    _inp, _out, bundle = example
    assert len(bundle.calculations) == 5
    assert bundle.calculations[-1].calculation_id.endswith("reinforcement-output")


def test_all_finals_reach_complete_input_and_three_factors(example):
    _inp, _out, bundle = example
    required = {
        "fatigue-input-vector", "input-gamma-s", "input-gamma-ff",
        "input-gamma-c",
    }
    for calculation in bundle.calculations:
        assert required <= _ancestors(calculation)


def test_entered_gamma_c_is_numeric_when_concrete_check_is_off(example):
    inp, _out, bundle = example
    for calculation in bundle.calculations:
        result = _steps(calculation)["input-gamma-c"].result
        assert result.state == RESULT_FINITE
        assert result.value == inp["fatigue_gamma_c"]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("fatigue_gamma_c", 1.61),
        ("fatigue_beta_cc_t0", 0.91),
        ("fatigue_t0_days", 29.0),
        ("fatigue_concrete_k1", 0.86),
        ("fatigue_concrete_c", 14.1),
        ("fatigue_concrete_method", "unused concrete method identity"),
    ],
)
def test_disabled_concrete_scalar_controls_remain_identity(key, value):
    _inp, _out, left = _build(_steel_input())
    _inp, _out, right = _build(_steel_input(**{key: value}))
    assert left.content_sha256 != right.content_sha256


def test_missing_concrete_key_is_valid_when_concrete_check_is_off():
    inp = _steel_input()
    inp.pop("concrete")
    _inp, _out, bundle = _build(inp)
    assert len(bundle.calculations) == 5


def test_null_concrete_law_is_valid_when_concrete_check_is_off():
    _inp, _out, bundle = _build(_steel_input(concrete=None))
    assert len(bundle.calculations) == 5


def test_absent_null_and_live_concrete_inputs_seal_differently():
    absent = _steel_input()
    absent.pop("concrete")
    _inp, _out, absent_bundle = _build(absent)
    _inp, _out, null_bundle = _build(_steel_input(concrete=None))
    _inp, _out, live_bundle = _build(_steel_input())
    assert len({
        absent_bundle.content_sha256,
        null_bundle.content_sha256,
        live_bundle.content_sha256,
    }) == 3


@pytest.mark.parametrize("material_key", ["bar_materials", "tendon_materials"])
def test_every_live_steel_law_field_remains_identity(material_key):
    _inp, _out, left = _build(_steel_input())
    changed = _steel_input()
    law = changed[material_key][0]
    changed[material_key][0] = dataclasses.replace(
        law, gamma_u=law.gamma_u + 0.01
    )
    _inp, _out, right = _build(changed)
    assert left.content_sha256 != right.content_sha256


def test_disabled_concrete_law_fields_remain_identity():
    _inp, _out, left = _build(_steel_input())
    changed = _steel_input()
    changed["concrete"] = dataclasses.replace(
        changed["concrete"], alpha_cc=changed["concrete"].alpha_cc + 0.01
    )
    _inp, _out, right = _build(changed)
    assert left.content_sha256 != right.content_sha256


def test_bin_description_and_concrete_material_id_are_sealed():
    _inp, _out, left = _build(_steel_input(concrete_material_id="C-A"))
    changed = _steel_input(concrete_material_id="C-B")
    table = changed[fatigue_inputs.SPECTRUM_TABLE_KEY].copy(deep=True)
    table.loc[0, fatigue_inputs.DESCRIPTION] = "Changed published description"
    changed[fatigue_inputs.SPECTRUM_TABLE_KEY] = table
    _inp, _out, right = _build(changed)
    assert left.content_sha256 != right.content_sha256


@pytest.mark.parametrize("field", ["concrete_method", "concrete_parameters"])
def test_excluded_top_level_concrete_types_are_pinned(field):
    inp = _steel_input()
    out = fatigue_analysis.run_analysis(inp)
    changed = dict(out)
    changed[field] = [out[field]]
    with pytest.raises(TraceValidationError, match="retained type"):
        build_fatigue_trace_family(
            inp, changed, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_excluded_concrete_tuple_cardinality_is_pinned():
    inp = _steel_input()
    out = fatigue_analysis.run_analysis(inp)
    spectrum = out["spectra"][0]
    changed_spectrum = dataclasses.replace(spectrum, concrete=(1.0,))
    changed = dict(out, spectra=(changed_spectrum, *out["spectra"][1:]))
    with pytest.raises(TraceValidationError, match="cardinality"):
        build_fatigue_trace_family(
            inp, changed, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_excluded_concrete_nested_member_type_is_pinned(monkeypatch):
    inp = _steel_input()
    replay = fatigue_analysis.run_analysis(inp)
    spectrum = replay["spectra"][0]
    expected_spectrum = dataclasses.replace(spectrum, concrete=(1.0,))
    expected = dict(
        replay, spectra=(expected_spectrum, *replay["spectra"][1:])
    )
    candidate_spectrum = dataclasses.replace(spectrum, concrete=([1.0],))
    candidate = dict(
        replay, spectra=(candidate_spectrum, *replay["spectra"][1:])
    )
    monkeypatch.setattr(fatigue_analysis, "run_analysis", lambda _inp: expected)
    with pytest.raises(TraceValidationError, match="retained type"):
        build_fatigue_trace_family(
            inp, candidate, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_empty_error_invalid_payload_stays_failed():
    inp = _steel_input()
    out = fatigue_analysis.invalid_result(inp, errors=())
    bundle = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
    )
    calculation = bundle.calculations[0]
    assert _steps(calculation)[calculation.final_step_id].result.state == RESULT_FAILED


@pytest.mark.parametrize(
    "mutate",
    [
        lambda inp: inp.pop("fatigue_check_steel"),
        lambda inp: inp.update(fatigue_check_concrete="not-a-boolean"),
    ],
)
def test_incomplete_flag_invalid_payload_is_traceable(mutate):
    inp = _steel_input()
    mutate(inp)
    out = fatigue_analysis.invalid_result(inp)
    bundle = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
    )
    calculation = bundle.calculations[0]
    assert _steps(calculation)[calculation.final_step_id].result.state == RESULT_FAILED


def test_invalid_payload_with_errors_stays_failed():
    inp = _steel_input(fatigue_gamma_s=None)
    out = fatigue_analysis.invalid_result(inp)
    bundle = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
    )
    calculation = bundle.calculations[0]
    assert _steps(calculation)[calculation.final_step_id].result.state == RESULT_FAILED


def test_equivalent_area_nonconvergence_fails_assessment(monkeypatch):
    inp = _steel_input()
    replay = fatigue_analysis.run_analysis(inp)
    spectrum = replay["spectra"][0]
    failed_state = dataclasses.replace(spectrum.bins[0], converged=False)
    reinforcement = []
    for result in spectrum.reinforcement:
        failed_bin = dataclasses.replace(result.bins[0], converged=False)
        reinforcement.append(dataclasses.replace(
            result, bins=(failed_bin, *result.bins[1:]),
            converged=False, passed=False,
        ))
    failed_spectrum = dataclasses.replace(
        spectrum, bins=(failed_state, *spectrum.bins[1:]),
        reinforcement=tuple(reinforcement), converged=False, passed=False,
    )
    retained = dict(
        replay, spectra=(failed_spectrum, *replay["spectra"][1:]),
        converged=False, passed=False,
    )
    monkeypatch.setattr(fatigue_analysis, "run_analysis", lambda _inp: retained)
    bundle = build_fatigue_trace_family(
        inp, retained, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
    )
    states = [
        _steps(calculation)[calculation.final_step_id].result.state
        for calculation in bundle.calculations
        if "spectrum-000" in calculation.calculation_id
    ]
    assert states and set(states) == {RESULT_FAILED}


def test_positive_infinity_has_an_explicit_result_state():
    assert _trace_result(float("inf")).state == RESULT_POSITIVE_INFINITY


def test_damage_reconstruction_uses_log_domain():
    assert _damage_from_log(1.0e300, -300.0) == float("inf")
    assert _damage_from_log(1.0e-300, 300.0) == 0.0


def test_nested_reinforcement_sequence_type_is_exact(example):
    inp, out, _bundle = example
    spectrum = out["spectra"][0]
    first = dataclasses.replace(
        spectrum.bins[0],
        bar_stress_long_mpa=list(spectrum.bins[0].bar_stress_long_mpa),
    )
    altered = dataclasses.replace(spectrum, bins=(first, *spectrum.bins[1:]))
    changed = dict(out, spectra=(altered, *out["spectra"][1:]))
    with pytest.raises(TraceValidationError, match="retained type"):
        build_fatigue_trace_family(
            inp, changed, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_numeric_boolean_input_is_rejected_on_success_branch():
    inp = _steel_input(fatigue_gamma_s=True)
    out = fatigue_analysis.run_analysis(inp)
    with pytest.raises(TraceValidationError, match="non-Boolean"):
        build_fatigue_trace_family(
            inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_unassigned_catalog_entry_is_still_identity():
    _inp, _out, left = _build(_steel_input())
    changed = _steel_input()
    catalog, detail_id = fatigue_inputs.add_entry(
        changed[fatigue_inputs.DETAIL_CATALOG_KEY],
        preset=fatigue_inputs.PRESET_2023_BARS,
    )
    next(item for item in catalog["items"] if item["id"] == detail_id)[
        "description"
    ] = "Unassigned identity"
    changed[fatigue_inputs.DETAIL_CATALOG_KEY] = catalog
    _inp, _out, right = _build(changed)
    assert left.content_sha256 != right.content_sha256


def test_resealed_expression_tamper_is_rejected(example):
    inp, out, bundle = example
    calculation = bundle.calculations[0]
    final = _steps(calculation)[calculation.final_step_id]
    changed_final = dataclasses.replace(final, actual_expression="tampered")
    changed_steps = tuple(
        changed_final if step is final else step for step in calculation.steps
    )
    candidate = seal_bundle(dataclasses.replace(
        bundle,
        calculations=(
            dataclasses.replace(calculation, steps=changed_steps),
            *bundle.calculations[1:],
        ),
        content_sha256="",
    ))
    with pytest.raises(TraceValidationError, match="independent replay"):
        validate_fatigue_trace_family(
            candidate, inp, out, input_sha256=INPUT_HASH,
            result_sha256=RESULT_HASH, context=CONTEXT,
        )


def test_stale_result_hash_is_rejected(example):
    inp, out, bundle = example
    with pytest.raises(TraceValidationError, match="result fingerprint"):
        validate_fatigue_trace_family(
            bundle, inp, out, input_sha256=INPUT_HASH,
            result_sha256="f" * 64, context=CONTEXT,
        )


def test_no_crack_trace_dependency_is_imported():
    assert "sector.crack_trace" not in sys.modules
    assert "sector.crack_trace_contract" not in sys.modules
