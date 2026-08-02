"""CT-010a closed-boundary tests."""

from __future__ import annotations

import dataclasses
import pathlib
import sys
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_analysis  # noqa: E402
import fatigue_inputs  # noqa: E402
from test_fatigue_analysis import _base  # noqa: E402
from sector.calculation_trace import (  # noqa: E402
    RESULT_FAILED, RESULT_POSITIVE_INFINITY, TraceValidationError,
    bundle_from_json, bundle_to_json, seal_bundle,
)
from sector.fatigue_trace import (  # noqa: E402
    _compare_shape, _damage_from_log, build_fatigue_trace_family,
    validate_fatigue_trace_family,
)


INPUT_HASH = "d" * 64
RESULT_HASH = "e" * 64
TRACE_CONTEXT = {"case": "fatigue", "index": 5}


def _steel_input(**overrides):
    return _base(fatigue_check_concrete=False, **overrides)


def _build(inp=None, out=None, context=TRACE_CONTEXT):
    inp = _steel_input() if inp is None else inp
    out = fatigue_analysis.run_analysis(inp) if out is None else out
    bundle = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH,
        context=context,
    )
    return inp, out, bundle


@pytest.fixture(scope="module")
def example():
    return _build()


def _by_id(calculation):
    return {step.step_id: step for step in calculation.steps}


def _reachable(calculation):
    steps = _by_id(calculation)
    result = {calculation.final_step_id}
    pending = [calculation.final_step_id]
    while pending:
        for dependency in steps[pending.pop()].dependencies:
            if dependency.step_id not in result:
                result.add(dependency.step_id)
                pending.append(dependency.step_id)
    return result


def test_bundle_round_trip_and_reconstruction(example):
    inp, out, bundle = example
    loaded = bundle_from_json(bundle_to_json(bundle))
    assert validate_fatigue_trace_family(
        loaded, inp, out, input_sha256=INPUT_HASH,
        result_sha256=RESULT_HASH, context=TRACE_CONTEXT,
    ) == bundle


def test_member_inventory_is_element_times_spectrum_plus_joint(example):
    _inp, out, bundle = example
    assessment_count = sum(len(spectrum.reinforcement)
                           for spectrum in out["spectra"])
    assert len(bundle.calculations) == assessment_count + 1


def test_full_identity_and_all_partial_factors_reach_finals(example):
    _inp, _out, bundle = example
    required = {
        "fatigue-input-vector", "input-gamma-s", "input-gamma-ff",
        "input-gamma-c", "normalised-fatigue-inputs",
    }
    for calculation in bundle.calculations:
        assert required <= _reachable(calculation)


def test_reinforcement_only_input_can_omit_concrete_law():
    inp = _steel_input()
    inp.pop("concrete")
    out = fatigue_analysis.run_analysis(inp)
    bundle = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
    )
    assert bundle.calculations
    assert any("text-u616273656e74" in step.step_id
               for step in bundle.calculations[0].steps)


def test_concrete_presence_and_absence_have_different_seals():
    present = _steel_input()
    _inp, _out, present_bundle = _build(present)
    absent = _steel_input()
    absent.pop("concrete")
    _inp, _out, absent_bundle = _build(absent)
    assert present_bundle.content_sha256 != absent_bundle.content_sha256


def test_every_runtime_reinforcement_law_field_is_sealed_without_catalogs():
    first = _steel_input()
    first.pop("mild_material_catalog")
    first.pop("prestress_material_catalog")
    _inp, _out, left = _build(first)
    second = _steel_input()
    second.pop("mild_material_catalog")
    second.pop("prestress_material_catalog")
    second["bar_materials"][0] = dataclasses.replace(
        second["bar_materials"][0], active_in_compression=False
    )
    second["tendon_materials"][0] = dataclasses.replace(
        second["tendon_materials"][0], gamma_E=1.01
    )
    _inp, _out, right = _build(second)
    assert left.content_sha256 != right.content_sha256


def test_bin_description_and_concrete_id_both_change_seal():
    first = _steel_input(concrete_material_id="C-A")
    _inp, _out, left = _build(first)
    second = _steel_input(concrete_material_id="C-B")
    table = second[fatigue_inputs.SPECTRUM_TABLE_KEY].copy()
    table.loc[0, fatigue_inputs.DESCRIPTION] = "Different retained description"
    second[fatigue_inputs.SPECTRUM_TABLE_KEY] = table
    _inp, _out, right = _build(second)
    assert left.content_sha256 != right.content_sha256


@pytest.mark.parametrize("field", ["concrete_method", "concrete_parameters"])
def test_excluded_concrete_key_keeps_concrete_type(field, example):
    inp, out, _bundle = example
    changed = dict(out)
    changed[field] = []
    with pytest.raises(TraceValidationError, match="retained type"):
        build_fatigue_trace_family(
            inp, changed, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_concrete_tuple_shape_keeps_cardinality_and_member_types():
    expected = (
        SimpleNamespace(bins=(SimpleNamespace(damage=0.1),), passed=True),
        SimpleNamespace(bins=(SimpleNamespace(damage=0.2),), passed=False),
    )
    _compare_shape(expected, expected, "concrete")
    with pytest.raises(TraceValidationError, match="cardinality"):
        _compare_shape((), expected, "concrete")
    with pytest.raises(TraceValidationError, match="retained type"):
        _compare_shape(({}, expected[1]), expected, "concrete")


def test_populated_concrete_tuple_cannot_be_removed(monkeypatch):
    inp = _steel_input()
    replay = fatigue_analysis.run_analysis(inp)
    spectrum = replay["spectra"][0]
    marker = SimpleNamespace(bins=(SimpleNamespace(damage=0.1),), passed=True)
    with_concrete = dataclasses.replace(spectrum, concrete=(marker,))
    replay = dict(replay, spectra=(with_concrete, *replay["spectra"][1:]))
    monkeypatch.setattr(fatigue_analysis, "run_analysis", lambda _inp: replay)
    build_fatigue_trace_family(
        inp, replay, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
    )
    without_concrete = dataclasses.replace(with_concrete, concrete=())
    changed = dict(replay, spectra=(without_concrete, *replay["spectra"][1:]))
    with pytest.raises(TraceValidationError, match="cardinality"):
        build_fatigue_trace_family(
            inp, changed, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_empty_error_invalid_payload_is_still_invalid():
    inp = _steel_input()
    out = fatigue_analysis.invalid_result(inp, errors=())
    bundle = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
    )
    final = _by_id(bundle.calculations[0])[bundle.calculations[0].final_step_id]
    assert final.result.state == RESULT_FAILED
    assert final.result.value is None


def test_invalid_payload_with_errors_is_failure_only():
    inp = _steel_input()
    inp["fatigue_gamma_s"] = "bad"
    out = fatigue_analysis.invalid_result(inp)
    bundle = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
    )
    final = _by_id(bundle.calculations[0])[bundle.calculations[0].final_step_id]
    assert final.result.state == RESULT_FAILED
    assert "finite number" in final.result.reason


def test_equivalent_area_failure_is_not_reconstructed_from_original_only(monkeypatch):
    inp = _steel_input()
    import sector.fatigue as fatigue

    solve_original = fatigue.solve_fatigue_bin
    tendon_area = sum(tendon.area for tendon in inp["section"].tendons)

    def solve(section, *args, **kwargs):
        state = solve_original(section, *args, **kwargs)
        if sum(tendon.area for tendon in section.tendons) != pytest.approx(tendon_area):
            return dataclasses.replace(state, converged=False)
        return state

    monkeypatch.setattr(fatigue, "solve_fatigue_bin", solve)
    out = fatigue_analysis.run_analysis(inp)
    assert out["spectra"][0].bins[0].elastic_result.converged
    assert not out["spectra"][0].bins[0].converged
    bundle = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
    )
    assert all(
        _by_id(calculation)[calculation.final_step_id].result.state
        == RESULT_FAILED
        for calculation in bundle.calculations
    )


def test_overflow_final_is_explicit_positive_infinity():
    inp = _steel_input()
    detail = inp[fatigue_inputs.DETAIL_CATALOG_KEY]["items"][0]
    detail.update({
        "preset": fatigue_inputs.CUSTOM_PRESET,
        "stress_model": fatigue_inputs.FIXED_STRESS,
        "delta_sigma_rsk_mpa": 1.0e-100,
        "source": "Project test",
    })
    out = fatigue_analysis.run_analysis(inp)
    bundle = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
    )
    states = {
        _by_id(calculation)[calculation.final_step_id].result.state
        for calculation in bundle.calculations
    }
    assert RESULT_POSITIVE_INFINITY in states


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


def test_numeric_boolean_input_is_rejected_before_coercion():
    inp = _steel_input(fatigue_gamma_s=True)
    out = fatigue_analysis.run_analysis(inp)
    with pytest.raises(TraceValidationError, match="non-Boolean"):
        build_fatigue_trace_family(
            inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_unassigned_catalog_item_remains_part_of_identity():
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


def test_resealed_trace_expression_tamper_is_rejected(example):
    inp, out, bundle = example
    calculation = bundle.calculations[0]
    final = _by_id(calculation)[calculation.final_step_id]
    changed_final = dataclasses.replace(final, actual_expression="tampered")
    steps = tuple(changed_final if step is final else step
                  for step in calculation.steps)
    candidate = seal_bundle(dataclasses.replace(
        bundle,
        calculations=(dataclasses.replace(calculation, steps=steps),
                      *bundle.calculations[1:]),
        content_sha256="",
    ))
    with pytest.raises(TraceValidationError, match="independent replay"):
        validate_fatigue_trace_family(
            candidate, inp, out, input_sha256=INPUT_HASH,
            result_sha256=RESULT_HASH, context=TRACE_CONTEXT,
        )


def test_stale_result_hash_is_rejected(example):
    inp, out, bundle = example
    with pytest.raises(TraceValidationError, match="result fingerprint"):
        validate_fatigue_trace_family(
            bundle, inp, out, input_sha256=INPUT_HASH,
            result_sha256="f" * 64, context=TRACE_CONTEXT,
        )


def test_no_crack_trace_dependency_is_imported():
    assert "sector.crack_trace" not in sys.modules
    assert "sector.crack_trace_contract" not in sys.modules
