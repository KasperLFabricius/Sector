"""Hostile acceptance tests for the CT-010a trace boundary."""

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
    _damage, _same_shape, build_fatigue_trace_family,
    validate_fatigue_trace_family,
)


IH = "a" * 64
RH = "b" * 64
CTX = {"case": "fatigue", "row": 2}


def _case(**overrides):
    return _base(fatigue_check_concrete=False, **overrides)


def _bundle(inp=None, out=None, context=CTX):
    inp = _case() if inp is None else inp
    out = fatigue_analysis.run_analysis(inp) if out is None else out
    return inp, out, build_fatigue_trace_family(
        inp, out, input_sha256=IH, result_sha256=RH, context=context
    )


@pytest.fixture(scope="module")
def retained():
    return _bundle()


def _step_map(calculation):
    return {step.step_id: step for step in calculation.steps}


def _ancestor_ids(calculation):
    steps = _step_map(calculation)
    found = {calculation.final_step_id}
    pending = [calculation.final_step_id]
    while pending:
        for dependency in steps[pending.pop()].dependencies:
            if dependency.step_id not in found:
                found.add(dependency.step_id)
                pending.append(dependency.step_id)
    return found


def test_round_trip_and_exact_validation(retained):
    inp, out, bundle = retained
    candidate = bundle_from_json(bundle_to_json(bundle))
    assert validate_fatigue_trace_family(
        candidate, inp, out, input_sha256=IH, result_sha256=RH, context=CTX
    ) == bundle


def test_one_member_exists_for_each_element_and_independent_spectrum(retained):
    _inp, out, bundle = retained
    count = sum(len(item.reinforcement) for item in out["spectra"])
    assert len(bundle.calculations) == count + 1
    spectrum_axes = [
        next(axis.value for axis in calculation.axes if axis.name == "spectrum")
        for calculation in bundle.calculations[:-1]
    ]
    assert spectrum_axes.count("Traffic A") == 2
    assert spectrum_axes.count("Traffic B") == 2


def test_complete_input_vector_and_all_factors_reach_every_final(retained):
    _inp, _out, bundle = retained
    for calculation in bundle.calculations:
        ancestors = _ancestor_ids(calculation)
        assert {
            "fatigue-input-vector", "input-gamma-s", "input-gamma-ff",
            "input-gamma-c", "normalised-fatigue-inputs",
        } <= ancestors


def test_published_bin_description_changes_content_seal():
    first = _case()
    _inp, _out, left = _bundle(first)
    second = _case()
    table = second[fatigue_inputs.SPECTRUM_TABLE_KEY].copy()
    table.loc[0, fatigue_inputs.DESCRIPTION] = "A distinct retained description"
    second[fatigue_inputs.SPECTRUM_TABLE_KEY] = table
    _inp, _out, right = _bundle(second)
    assert left.content_sha256 != right.content_sha256


def test_concrete_and_reinforcement_material_ids_are_identity_not_law():
    first = _case(concrete_material_id="C1")
    _inp, _out, left = _bundle(first)
    second = _case(concrete_material_id="C2")
    second["mild_material_catalog"]["items"][0]["id"] = "M2"
    second["mild_material_catalog"]["next_id"] = 3
    second["bar_elements"][0]["material_id"] = "M2"
    _inp, _out, right = _bundle(second)
    assert left.content_sha256 != right.content_sha256


@pytest.mark.parametrize("field", ["concrete_method", "concrete_parameters"])
def test_concrete_sibling_rejects_list_replacement(retained, field):
    inp, out, _trace = retained
    damaged = dict(out)
    damaged[field] = []
    with pytest.raises(TraceValidationError, match="retained type"):
        build_fatigue_trace_family(
            inp, damaged, input_sha256=IH, result_sha256=RH
        )


def test_recursive_shape_fence_pins_tuple_cardinality_and_member_types():
    expected = (
        SimpleNamespace(value=1.0, flags=(True, False)),
        SimpleNamespace(value=2.0, flags=(False, True)),
    )
    _same_shape(expected, expected, "concrete")
    with pytest.raises(TraceValidationError, match="cardinality"):
        _same_shape((), expected, "concrete")
    with pytest.raises(TraceValidationError, match="retained type"):
        _same_shape(({"value": 1.0}, expected[1]), expected, "concrete")


def test_populated_concrete_tuple_replacement_is_rejected(monkeypatch):
    inp = _case()
    replay = fatigue_analysis.run_analysis(inp)
    spectrum = replay["spectra"][0]
    concrete_marker = SimpleNamespace(
        bins=(SimpleNamespace(damage=0.1),), passed=True
    )
    populated = dataclasses.replace(spectrum, concrete=(concrete_marker,))
    replay = dict(replay, spectra=(populated, *replay["spectra"][1:]))
    monkeypatch.setattr(fatigue_analysis, "run_analysis", lambda _inp: replay)
    build_fatigue_trace_family(inp, replay, input_sha256=IH, result_sha256=RH)
    empty = dataclasses.replace(populated, concrete=())
    damaged = dict(replay, spectra=(empty, *replay["spectra"][1:]))
    with pytest.raises(TraceValidationError, match="cardinality"):
        build_fatigue_trace_family(
            inp, damaged, input_sha256=IH, result_sha256=RH
        )


def test_equivalent_area_only_failure_remains_an_explicit_failure(monkeypatch):
    inp = _case()
    import sector.fatigue as fatigue

    original = fatigue.solve_fatigue_bin
    original_area = sum(item.area for item in inp["section"].tendons)

    def solve(section, *args, **kwargs):
        state = original(section, *args, **kwargs)
        if sum(item.area for item in section.tendons) != pytest.approx(original_area):
            return dataclasses.replace(state, converged=False)
        return state

    monkeypatch.setattr(fatigue, "solve_fatigue_bin", solve)
    out = fatigue_analysis.run_analysis(inp)
    assert out["spectra"][0].bins[0].elastic_result.converged
    assert not out["spectra"][0].bins[0].converged
    trace = build_fatigue_trace_family(
        inp, out, input_sha256=IH, result_sha256=RH
    )
    assert all(
        _step_map(calculation)[calculation.final_step_id].result.state
        == RESULT_FAILED
        for calculation in trace.calculations
    )


def test_registry_admits_explicit_positive_infinity():
    inp = _case()
    catalog = inp[fatigue_inputs.DETAIL_CATALOG_KEY]
    detail = catalog["items"][0]
    detail["preset"] = fatigue_inputs.CUSTOM_PRESET
    detail["delta_sigma_rsk_mpa"] = 1.0e-100
    detail["stress_model"] = fatigue_inputs.FIXED_STRESS
    detail["source"] = "Project fatigue test"
    out = fatigue_analysis.run_analysis(inp)
    assert out["spectra"][0].reinforcement[0].damage == float("inf")
    trace = build_fatigue_trace_family(
        inp, out, input_sha256=IH, result_sha256=RH
    )
    states = [
        _step_map(calculation)[calculation.final_step_id].result.state
        for calculation in trace.calculations
    ]
    assert RESULT_POSITIVE_INFINITY in states


def test_log_damage_never_divides_by_underflowed_life():
    assert _damage(1.0e300, -300.0) == float("inf")
    assert _damage(1.0e-300, 300.0) == 0.0


def test_exact_tuple_type_on_reinforcement_state(retained):
    inp, out, _trace = retained
    first_spectrum = out["spectra"][0]
    first_bin = dataclasses.replace(
        first_spectrum.bins[0],
        bar_stress_long_mpa=list(first_spectrum.bins[0].bar_stress_long_mpa),
    )
    changed_spectrum = dataclasses.replace(
        first_spectrum, bins=(first_bin, *first_spectrum.bins[1:])
    )
    damaged = dict(out, spectra=(changed_spectrum, *out["spectra"][1:]))
    with pytest.raises(TraceValidationError, match="retained type"):
        build_fatigue_trace_family(
            inp, damaged, input_sha256=IH, result_sha256=RH
        )


def test_reinforcement_result_tamper_is_rejected(retained):
    inp, out, _trace = retained
    spectrum = out["spectra"][0]
    result = dataclasses.replace(
        spectrum.reinforcement[0],
        governing_damage_bin=spectrum.reinforcement[0].bins[-1].bin_name,
    )
    damaged_spectrum = dataclasses.replace(
        spectrum, reinforcement=(result, *spectrum.reinforcement[1:])
    )
    damaged = dict(out, spectra=(damaged_spectrum, *out["spectra"][1:]))
    with pytest.raises(TraceValidationError):
        build_fatigue_trace_family(
            inp, damaged, input_sha256=IH, result_sha256=RH
        )


def test_wrong_numeric_input_type_is_not_coerced():
    inp = _case(fatigue_gamma_s=True)
    out = fatigue_analysis.run_analysis(inp)
    with pytest.raises(TraceValidationError, match="non-Boolean"):
        build_fatigue_trace_family(
            inp, out, input_sha256=IH, result_sha256=RH
        )


def test_unused_detail_catalog_entry_changes_seal():
    first = _case()
    _inp, _out, left = _bundle(first)
    second = _case()
    catalog, detail_id = fatigue_inputs.add_entry(
        second[fatigue_inputs.DETAIL_CATALOG_KEY],
        preset=fatigue_inputs.PRESET_2023_BARS,
    )
    next(item for item in catalog["items"] if item["id"] == detail_id)[
        "description"
    ] = "Retained even though unassigned"
    second[fatigue_inputs.DETAIL_CATALOG_KEY] = catalog
    _inp, _out, right = _bundle(second)
    assert left.content_sha256 != right.content_sha256


def test_invalid_boundary_has_failure_only_final():
    inp = _case()
    inp["fatigue_gamma_s"] = "bad"
    out = fatigue_analysis.invalid_result(inp)
    trace = build_fatigue_trace_family(
        inp, out, input_sha256=IH, result_sha256=RH
    )
    final = _step_map(trace.calculations[0])[trace.calculations[0].final_step_id]
    assert final.result.state == RESULT_FAILED
    assert final.result.value is None


def test_resealed_candidate_expression_tamper_is_rejected(retained):
    inp, out, bundle = retained
    calculation = bundle.calculations[0]
    final = _step_map(calculation)[calculation.final_step_id]
    changed = dataclasses.replace(final, actual_expression="tampered")
    steps = tuple(changed if item is final else item for item in calculation.steps)
    candidate = seal_bundle(dataclasses.replace(
        bundle,
        calculations=(dataclasses.replace(calculation, steps=steps),
                      *bundle.calculations[1:]),
        content_sha256="",
    ))
    with pytest.raises(TraceValidationError, match="independent replay"):
        validate_fatigue_trace_family(
            candidate, inp, out, input_sha256=IH, result_sha256=RH,
            context=CTX,
        )


def test_stale_result_fingerprint_is_rejected(retained):
    inp, out, bundle = retained
    with pytest.raises(TraceValidationError, match="result fingerprint"):
        validate_fatigue_trace_family(
            bundle, inp, out, input_sha256=IH, result_sha256="c" * 64,
            context=CTX,
        )


def test_reordered_spectra_are_rejected(retained):
    inp, out, _trace = retained
    damaged = dict(out, spectra=tuple(reversed(out["spectra"])))
    with pytest.raises(TraceValidationError):
        build_fatigue_trace_family(
            inp, damaged, input_sha256=IH, result_sha256=RH
        )


def test_import_does_not_pull_crack_family():
    assert "sector.crack_trace" not in sys.modules
    assert "sector.crack_trace_contract" not in sys.modules
