"""Adversarial CT-010a trace acceptance tests."""

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
    _log_damage, _shape, build_fatigue_trace_family,
    validate_fatigue_trace_family,
)


INPUT_SHA = "1" * 64
RESULT_SHA = "2" * 64
CONTEXT = {"case": "FAT", "position": 4}


def _input(**changes):
    return _base(fatigue_check_concrete=False, **changes)


def _make(inp=None, out=None, context=CONTEXT):
    inp = _input() if inp is None else inp
    out = fatigue_analysis.run_analysis(inp) if out is None else out
    trace = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=context,
    )
    return inp, out, trace


@pytest.fixture(scope="module")
def sample():
    return _make()


def _steps(calculation):
    return {row.step_id: row for row in calculation.steps}


def _closure(calculation):
    steps = _steps(calculation)
    visited = {calculation.final_step_id}
    pending = [calculation.final_step_id]
    while pending:
        row = steps[pending.pop()]
        for dependency in row.dependencies:
            if dependency.step_id not in visited:
                visited.add(dependency.step_id)
                pending.append(dependency.step_id)
    return visited


def test_build_serialise_and_validate(sample):
    inp, out, trace = sample
    candidate = bundle_from_json(bundle_to_json(trace))
    assert validate_fatigue_trace_family(
        candidate, inp, out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT,
    ) == trace


def test_dynamic_members_are_element_by_independent_spectrum(sample):
    _inp, out, trace = sample
    expected = sum(len(spectrum.reinforcement) for spectrum in out["spectra"])
    assert len(trace.calculations) == expected + 1
    assert sum(
        next(axis.value for axis in calculation.axes if axis.name == "spectrum")
        == "Traffic A"
        for calculation in trace.calculations[:-1]
    ) == 2


def test_every_final_reaches_input_vector_and_three_factors(sample):
    _inp, _out, trace = sample
    for calculation in trace.calculations:
        assert {
            "retained-fatigue-input-vector", "input-gamma-s",
            "input-gamma-ff", "input-gamma-c",
            "normalised-fatigue-inputs",
        } <= _closure(calculation)


def test_runtime_mild_law_field_changes_seal_without_catalog_dependence():
    first = _input()
    first.pop("mild_material_catalog")
    first.pop("prestress_material_catalog")
    _inp, _out, left = _make(first)
    second = _input()
    second.pop("mild_material_catalog")
    second.pop("prestress_material_catalog")
    second["bar_materials"][0] = dataclasses.replace(
        second["bar_materials"][0], active_in_compression=False
    )
    _inp, _out, right = _make(second)
    assert left.content_sha256 != right.content_sha256


def test_runtime_prestress_law_inert_field_changes_seal():
    first = _input()
    _inp, _out, left = _make(first)
    second = _input()
    second["tendon_materials"][0] = dataclasses.replace(
        second["tendon_materials"][0], gamma_E=1.01
    )
    _inp, _out, right = _make(second)
    assert left.content_sha256 != right.content_sha256


def test_bin_description_and_concrete_material_id_are_retained():
    first = _input(concrete_material_id="C1")
    _inp, _out, left = _make(first)
    second = _input(concrete_material_id="C2")
    table = second[fatigue_inputs.SPECTRUM_TABLE_KEY].copy()
    table.loc[0, fatigue_inputs.DESCRIPTION] = "Changed description identity"
    second[fatigue_inputs.SPECTRUM_TABLE_KEY] = table
    _inp, _out, right = _make(second)
    assert left.content_sha256 != right.content_sha256


@pytest.mark.parametrize("name", ["concrete_method", "concrete_parameters"])
def test_concrete_sibling_key_rejects_list(name, sample):
    inp, out, _trace = sample
    damaged = dict(out)
    damaged[name] = []
    with pytest.raises(TraceValidationError, match="retained type"):
        build_fatigue_trace_family(
            inp, damaged, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


def test_complete_concrete_tuple_shape_pins_cardinality_and_member_type():
    expected = (
        SimpleNamespace(bins=(SimpleNamespace(damage=0.1),), passed=True),
        SimpleNamespace(bins=(SimpleNamespace(damage=0.2),), passed=False),
    )
    _shape(expected, expected, "concrete")
    with pytest.raises(TraceValidationError, match="cardinality"):
        _shape((), expected, "concrete")
    with pytest.raises(TraceValidationError, match="retained type"):
        _shape(({"bins": ()}, expected[1]), expected, "concrete")


def test_reader_rejects_removal_of_populated_concrete_tuple(monkeypatch):
    inp = _input()
    replay = fatigue_analysis.run_analysis(inp)
    spectrum = replay["spectra"][0]
    marker = SimpleNamespace(bins=(SimpleNamespace(damage=0.1),), passed=True)
    populated = dataclasses.replace(spectrum, concrete=(marker,))
    replay = dict(replay, spectra=(populated, *replay["spectra"][1:]))
    monkeypatch.setattr(fatigue_analysis, "run_analysis", lambda _inp: replay)
    build_fatigue_trace_family(
        inp, replay, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
    )
    missing = dataclasses.replace(populated, concrete=())
    damaged = dict(replay, spectra=(missing, *replay["spectra"][1:]))
    with pytest.raises(TraceValidationError, match="cardinality"):
        build_fatigue_trace_family(
            inp, damaged, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


def test_empty_error_invalid_payload_stays_invalid():
    inp = _input()
    out = fatigue_analysis.invalid_result(inp, errors=())
    assert out["errors"] == ()
    trace = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
    )
    assert len(trace.calculations) == 1
    final = _steps(trace.calculations[0])[trace.calculations[0].final_step_id]
    assert final.result.state == RESULT_FAILED
    assert final.result.value is None


def test_nonempty_invalid_payload_is_failure_only():
    inp = _input()
    inp["fatigue_gamma_s"] = "not-a-number"
    out = fatigue_analysis.invalid_result(inp)
    trace = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
    )
    final = _steps(trace.calculations[0])[trace.calculations[0].final_step_id]
    assert final.result.state == RESULT_FAILED
    assert "finite number" in final.result.reason


def test_equivalent_area_only_nonconvergence_is_preserved(monkeypatch):
    inp = _input()
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
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
    )
    assert all(
        _steps(calculation)[calculation.final_step_id].result.state
        == RESULT_FAILED
        for calculation in trace.calculations
    )


def test_positive_infinity_is_an_admitted_final_state():
    inp = _input()
    detail = inp[fatigue_inputs.DETAIL_CATALOG_KEY]["items"][0]
    detail.update({
        "preset": fatigue_inputs.CUSTOM_PRESET,
        "stress_model": fatigue_inputs.FIXED_STRESS,
        "delta_sigma_rsk_mpa": 1.0e-100,
        "source": "Project fatigue evidence",
    })
    out = fatigue_analysis.run_analysis(inp)
    assert out["spectra"][0].reinforcement[0].damage == float("inf")
    trace = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
    )
    assert RESULT_POSITIVE_INFINITY in {
        _steps(calculation)[calculation.final_step_id].result.state
        for calculation in trace.calculations
    }


def test_log_domain_damage_handles_both_extremes():
    assert _log_damage(1.0e300, -300.0) == float("inf")
    assert _log_damage(1.0e-300, 300.0) == 0.0


def test_nested_reinforcement_type_tamper_is_rejected(sample):
    inp, out, _trace = sample
    spectrum = out["spectra"][0]
    state = dataclasses.replace(
        spectrum.bins[0],
        bar_stress_total_mpa=list(spectrum.bins[0].bar_stress_total_mpa),
    )
    altered = dataclasses.replace(spectrum, bins=(state, *spectrum.bins[1:]))
    damaged = dict(out, spectra=(altered, *out["spectra"][1:]))
    with pytest.raises(TraceValidationError, match="retained type"):
        build_fatigue_trace_family(
            inp, damaged, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


def test_numeric_boolean_is_not_laundered():
    inp = _input(fatigue_gamma_s=True)
    out = fatigue_analysis.run_analysis(inp)
    with pytest.raises(TraceValidationError, match="non-Boolean"):
        build_fatigue_trace_family(
            inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


def test_unused_catalog_record_remains_in_identity():
    first = _input()
    _inp, _out, left = _make(first)
    second = _input()
    catalog, new_id = fatigue_inputs.add_entry(
        second[fatigue_inputs.DETAIL_CATALOG_KEY],
        preset=fatigue_inputs.PRESET_2023_BARS,
    )
    next(row for row in catalog["items"] if row["id"] == new_id)[
        "description"
    ] = "Unassigned retained record"
    second[fatigue_inputs.DETAIL_CATALOG_KEY] = catalog
    _inp, _out, right = _make(second)
    assert left.content_sha256 != right.content_sha256


def test_resealed_expression_change_is_rejected(sample):
    inp, out, trace = sample
    calculation = trace.calculations[0]
    final = _steps(calculation)[calculation.final_step_id]
    changed = dataclasses.replace(final, actual_expression="coherent reseal")
    rows = tuple(changed if row is final else row for row in calculation.steps)
    candidate = seal_bundle(dataclasses.replace(
        trace,
        calculations=(dataclasses.replace(calculation, steps=rows),
                      *trace.calculations[1:]),
        content_sha256="",
    ))
    with pytest.raises(TraceValidationError, match="independent replay"):
        validate_fatigue_trace_family(
            candidate, inp, out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT,
        )


def test_stale_input_fingerprint_is_rejected(sample):
    inp, out, trace = sample
    with pytest.raises(TraceValidationError, match="input fingerprint"):
        validate_fatigue_trace_family(
            trace, inp, out, input_sha256="3" * 64,
            result_sha256=RESULT_SHA, context=CONTEXT,
        )


def test_crack_trace_is_not_imported():
    assert "sector.crack_trace" not in sys.modules
    assert "sector.crack_trace_contract" not in sys.modules
