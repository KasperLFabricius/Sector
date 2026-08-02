"""Closed-family tests for CT-010a reinforcement fatigue."""

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
    RESULT_FAILED,
    RESULT_POSITIVE_INFINITY,
    TraceValidationError,
    seal_bundle,
)
from sector.fatigue_trace import (  # noqa: E402
    _damage_from_log,
    _trace_result,
    build_fatigue_trace_family,
    validate_fatigue_trace_family,
)


INPUT_HASH = "a" * 64
RESULT_HASH = "b" * 64
TRACE_CONTEXT = {"load_case": "fatigue-trace-test"}


def _steel_input(**overrides):
    value = _base(fatigue_check_concrete=False)
    value.update(overrides)
    return value


def _build(inp):
    out = fatigue_analysis.run_analysis(inp)
    bundle = build_fatigue_trace_family(
        inp,
        out,
        input_sha256=INPUT_HASH,
        result_sha256=RESULT_HASH,
        context=TRACE_CONTEXT,
    )
    return inp, out, bundle


@pytest.fixture
def example():
    return _build(_steel_input())


def _by_id(calculation):
    return {step.step_id: step for step in calculation.steps}


def _ancestor_ids(calculation, final_id):
    steps = _by_id(calculation)
    found = set()
    pending = [final_id]
    while pending:
        step_id = pending.pop()
        for dependency in steps[step_id].dependencies:
            if dependency.step_id not in found:
                found.add(dependency.step_id)
                pending.append(dependency.step_id)
    return found


def test_round_trip_uses_authoritative_replay(example):
    inp, out, bundle = example
    assert validate_fatigue_trace_family(
        bundle,
        inp,
        out,
        input_sha256=INPUT_HASH,
        result_sha256=RESULT_HASH,
        context=TRACE_CONTEXT,
    ) == bundle


def test_member_inventory_is_element_by_spectrum_plus_joint(example):
    _inp, _out, bundle = example
    assert len(bundle.calculations) == 5
    assert bundle.calculations[-1].calculation_id.endswith("reinforcement-output")


def test_every_final_reaches_input_and_all_partial_factors(example):
    _inp, _out, bundle = example
    required = {
        "fatigue-input-vector",
        "input-gamma-s",
        "input-gamma-ff",
        "input-gamma-c",
    }
    for calculation in bundle.calculations:
        assert required <= _ancestor_ids(calculation, calculation.final_step_id)


def test_reinforcement_only_input_accepts_missing_concrete_key():
    inp = _steel_input()
    inp.pop("concrete")
    _inp, _out, bundle = _build(inp)
    assert len(bundle.calculations) == 5


def test_reinforcement_only_input_accepts_present_null_concrete_law():
    inp = _steel_input(concrete=None)
    _inp, _out, bundle = _build(inp)
    assert len(bundle.calculations) == 5


def test_absent_null_and_live_concrete_states_have_distinct_seals():
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


def test_every_runtime_mild_material_field_is_identity():
    first = _steel_input()
    _inp, _out, left = _build(first)
    second = _steel_input()
    material = second["bar_materials"][0]
    second["bar_materials"][0] = dataclasses.replace(
        material,
        gamma_u=material.gamma_u + 0.01,
    )
    _inp, _out, right = _build(second)
    assert left.content_sha256 != right.content_sha256


def test_every_runtime_prestress_material_field_is_identity():
    first = _steel_input()
    _inp, _out, left = _build(first)
    second = _steel_input()
    material = second["tendon_materials"][0]
    second["tendon_materials"][0] = dataclasses.replace(
        material,
        gamma_u=material.gamma_u + 0.01,
    )
    _inp, _out, right = _build(second)
    assert left.content_sha256 != right.content_sha256


def test_disabled_concrete_law_fields_are_still_identity():
    first = _steel_input()
    _inp, _out, left = _build(first)
    second = _steel_input()
    second["concrete"] = dataclasses.replace(
        second["concrete"],
        alpha_cc=second["concrete"].alpha_cc + 0.01,
    )
    _inp, _out, right = _build(second)
    assert left.content_sha256 != right.content_sha256


def test_bin_description_and_concrete_id_are_sealed():
    first = _steel_input(concrete_material_id="C-A")
    _inp, _out, left = _build(first)
    second = _steel_input(concrete_material_id="C-B")
    table = second[fatigue_inputs.SPECTRUM_TABLE_KEY].copy(deep=True)
    table.loc[0, fatigue_inputs.DESCRIPTION] = "Changed published description"
    second[fatigue_inputs.SPECTRUM_TABLE_KEY] = table
    _inp, _out, right = _build(second)
    assert left.content_sha256 != right.content_sha256


@pytest.mark.parametrize("field", ["concrete_method", "concrete_parameters"])
def test_excluded_concrete_top_level_type_is_pinned(field):
    inp = _steel_input()
    out = fatigue_analysis.run_analysis(inp)
    changed = dict(out)
    changed[field] = [out[field]]
    with pytest.raises(TraceValidationError, match="retained type"):
        build_fatigue_trace_family(
            inp,
            changed,
            input_sha256=INPUT_HASH,
            result_sha256=RESULT_HASH,
        )


def test_excluded_concrete_tuple_cardinality_is_pinned():
    inp = _steel_input()
    out = fatigue_analysis.run_analysis(inp)
    spectrum = out["spectra"][0]
    changed_spectrum = dataclasses.replace(
        spectrum,
        concrete=(1.0,),
    )
    changed = dict(out, spectra=(changed_spectrum, *out["spectra"][1:]))
    with pytest.raises(TraceValidationError, match="cardinality"):
        build_fatigue_trace_family(
            inp,
            changed,
            input_sha256=INPUT_HASH,
            result_sha256=RESULT_HASH,
        )


def test_excluded_concrete_member_type_is_pinned(monkeypatch):
    inp = _steel_input()
    replay = fatigue_analysis.run_analysis(inp)
    spectrum = replay["spectra"][0]
    replay_spectrum = dataclasses.replace(spectrum, concrete=(1.0,))
    expected = dict(
        replay,
        spectra=(replay_spectrum, *replay["spectra"][1:]),
    )
    candidate_spectrum = dataclasses.replace(
        spectrum,
        concrete=([1.0],),
    )
    candidate = dict(
        replay,
        spectra=(candidate_spectrum, *replay["spectra"][1:]),
    )
    monkeypatch.setattr(fatigue_analysis, "run_analysis", lambda _inp: expected)
    with pytest.raises(TraceValidationError, match="retained type"):
        build_fatigue_trace_family(
            inp,
            candidate,
            input_sha256=INPUT_HASH,
            result_sha256=RESULT_HASH,
        )


def test_invalid_payload_with_no_errors_stays_failed():
    inp = _steel_input()
    out = fatigue_analysis.invalid_result(inp, errors=())
    bundle = build_fatigue_trace_family(
        inp,
        out,
        input_sha256=INPUT_HASH,
        result_sha256=RESULT_HASH,
    )
    final = _by_id(bundle.calculations[0])[bundle.calculations[0].final_step_id]
    assert final.result.state == RESULT_FAILED


def test_invalid_payload_with_errors_stays_failed():
    inp = _steel_input(fatigue_gamma_s=None)
    out = fatigue_analysis.invalid_result(inp)
    bundle = build_fatigue_trace_family(
        inp,
        out,
        input_sha256=INPUT_HASH,
        result_sha256=RESULT_HASH,
    )
    final = _by_id(bundle.calculations[0])[bundle.calculations[0].final_step_id]
    assert final.result.state == RESULT_FAILED


def test_equivalent_area_only_nonconvergence_fails_assessments(monkeypatch):
    inp = _steel_input()
    replay = fatigue_analysis.run_analysis(inp)
    spectrum = replay["spectra"][0]
    failed_state = dataclasses.replace(spectrum.bins[0], converged=False)
    failed_reinforcement = []
    for result in spectrum.reinforcement:
        failed_bin = dataclasses.replace(result.bins[0], converged=False)
        failed_reinforcement.append(dataclasses.replace(
            result,
            bins=(failed_bin, *result.bins[1:]),
            converged=False,
            passed=False,
        ))
    failed_spectrum = dataclasses.replace(
        spectrum,
        bins=(failed_state, *spectrum.bins[1:]),
        reinforcement=tuple(failed_reinforcement),
        converged=False,
        passed=False,
    )
    retained = dict(
        replay,
        spectra=(failed_spectrum, *replay["spectra"][1:]),
        converged=False,
        passed=False,
    )
    monkeypatch.setattr(fatigue_analysis, "run_analysis", lambda _inp: retained)
    bundle = build_fatigue_trace_family(
        inp,
        retained,
        input_sha256=INPUT_HASH,
        result_sha256=RESULT_HASH,
    )
    failed = [
        _by_id(calculation)[calculation.final_step_id].result.state
        for calculation in bundle.calculations
        if "spectrum-000" in calculation.calculation_id
    ]
    assert failed and set(failed) == {RESULT_FAILED}


def test_positive_infinity_is_an_explicit_final_state():
    assert _trace_result(float("inf")).state == RESULT_POSITIVE_INFINITY


def test_damage_reconstruction_is_logarithmic():
    assert _damage_from_log(1.0e300, -300.0) == float("inf")
    assert _damage_from_log(1.0e-300, 300.0) == 0.0


def test_nested_reinforcement_sequence_type_is_exact(example):
    inp, out, _bundle = example
    spectrum = out["spectra"][0]
    first = dataclasses.replace(
        spectrum.bins[0],
        bar_stress_long_mpa=list(spectrum.bins[0].bar_stress_long_mpa),
    )
    changed_spectrum = dataclasses.replace(
        spectrum,
        bins=(first, *spectrum.bins[1:]),
    )
    changed = dict(out, spectra=(changed_spectrum, *out["spectra"][1:]))
    with pytest.raises(TraceValidationError, match="retained type"):
        build_fatigue_trace_family(
            inp,
            changed,
            input_sha256=INPUT_HASH,
            result_sha256=RESULT_HASH,
        )


def test_numeric_boolean_input_is_rejected():
    inp = _steel_input(fatigue_gamma_s=True)
    out = fatigue_analysis.run_analysis(inp)
    with pytest.raises(TraceValidationError, match="non-Boolean"):
        build_fatigue_trace_family(
            inp,
            out,
            input_sha256=INPUT_HASH,
            result_sha256=RESULT_HASH,
        )


def test_unused_catalog_entry_remains_identity():
    first = _steel_input()
    _inp, _out, left = _build(first)
    second = _steel_input()
    catalog, detail_id = fatigue_inputs.add_entry(
        second[fatigue_inputs.DETAIL_CATALOG_KEY],
        preset=fatigue_inputs.PRESET_2023_BARS,
    )
    next(item for item in catalog["items"] if item["id"] == detail_id)[
        "description"
    ] = "Unassigned identity"
    second[fatigue_inputs.DETAIL_CATALOG_KEY] = catalog
    _inp, _out, right = _build(second)
    assert left.content_sha256 != right.content_sha256


def test_coherently_resealed_expression_tamper_is_rejected(example):
    inp, out, bundle = example
    calculation = bundle.calculations[0]
    final = _by_id(calculation)[calculation.final_step_id]
    changed_final = dataclasses.replace(final, actual_expression="tampered")
    changed_steps = tuple(
        changed_final if step is final else step
        for step in calculation.steps
    )
    candidate = seal_bundle(
        dataclasses.replace(
            bundle,
            calculations=(
                dataclasses.replace(calculation, steps=changed_steps),
                *bundle.calculations[1:],
            ),
            content_sha256="",
        )
    )
    with pytest.raises(TraceValidationError, match="independent replay"):
        validate_fatigue_trace_family(
            candidate,
            inp,
            out,
            input_sha256=INPUT_HASH,
            result_sha256=RESULT_HASH,
            context=TRACE_CONTEXT,
        )


def test_stale_result_hash_is_rejected(example):
    inp, out, bundle = example
    with pytest.raises(TraceValidationError, match="result fingerprint"):
        validate_fatigue_trace_family(
            bundle,
            inp,
            out,
            input_sha256=INPUT_HASH,
            result_sha256="f" * 64,
            context=TRACE_CONTEXT,
        )


def test_no_crack_trace_dependency_is_imported():
    assert "sector.crack_trace" not in sys.modules
    assert "sector.crack_trace_contract" not in sys.modules
