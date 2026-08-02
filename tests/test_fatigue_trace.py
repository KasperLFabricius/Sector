"""Independent CT-010a success-contract and hostile-boundary tests."""

from __future__ import annotations

import copy
import dataclasses
import pathlib
import sys
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_analysis
import fatigue_inputs
from sector.calculation_trace import (
    RESULT_POSITIVE_INFINITY, SOURCE_PROJECT, SOURCE_STANDARD, TraceResult,
    TraceValidationError, bundle_from_json, bundle_to_json, create_bundle,
    seal_bundle,
)
from sector.fatigue_trace import (
    build_fatigue_trace_family, validate_fatigue_trace_family,
)
from sector.fatigue_trace_contract import (
    MemberShape, StepShape, registry_for,
)
from sector import fatigue_trace_replay
from sector.trace_registry import audit_trace_registry
from tests.test_fatigue_analysis import _base


INPUT_SHA = "1" * 64
RESULT_SHA = "2" * 64
CONTEXT = {"case": "ct010a-focus"}


@pytest.fixture(scope="module")
def case():
    inp = _base(fatigue_check_concrete=False)
    output = fatigue_analysis.run_analysis(inp)
    out = {"fatigue": output}
    bundle = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT)
    return inp, output, out, bundle


def _boundary(authoritative):
    return SimpleNamespace(
        run_analysis=lambda _inp: authoritative,
        prepare=fatigue_analysis.prepare,
        analysis_signature=fatigue_analysis.analysis_signature,
        invalid_result=fatigue_analysis.invalid_result,
        validation_errors=fatigue_analysis.validation_errors,
        fatigue_inputs=fatigue_inputs,
        calculation_references=fatigue_analysis.calculation_references,
        CONCRETE_MINER=fatigue_analysis.CONCRETE_MINER,
    )


def _build(inp, output, **kwargs):
    return build_fatigue_trace_family(
        inp, {"fatigue": output}, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT, **kwargs)


def test_success_round_trip_registry_shape_and_fresh_validation(case):
    inp, _output, out, bundle = case
    assert len(bundle.calculations) == 5
    assert bundle_from_json(bundle_to_json(bundle)) == bundle
    assert validate_fatigue_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) == bundle
    assert bundle.calculations[-1].final_step_id == (
        "reinforcement-fatigue-aggregate-result")


def test_positive_infinity_is_a_declared_successful_final_state(case):
    _inp, _output, _out, bundle = case
    calculation = bundle.calculations[0]
    final = dataclasses.replace(
        calculation.steps[-1],
        result=TraceResult(
            RESULT_POSITIVE_INFINITY, None,
            "replayed value is infinite"),
    )
    calculation = dataclasses.replace(
        calculation, steps=(*calculation.steps[:-1], final))
    overflow = create_bundle(
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        calculations=(calculation,))
    shape = MemberShape(
        "positive-infinity-probe", calculation.calculation_id,
        calculation.axes,
        tuple(StepShape(
            step.step_id, step.title, step.unit, step.quantity_role,
            step.source, tuple(dep.step_id for dep in step.dependencies))
              for step in calculation.steps),
    )
    contract = registry_for((shape,))
    assert RESULT_POSITIVE_INFINITY in (
        contract.families[0].members[0].result_states)
    assert audit_trace_registry(overflow, contract) == overflow


@pytest.mark.parametrize(
    "key,value",
    [
        ("fatigue_on", 1),
        ("fatigue_on", np.bool_(True)),
        ("fatigue_check_steel", "true"),
        ("fatigue_check_concrete", None),
    ],
)
def test_dispatch_controls_are_required_exact_booleans(case, key, value):
    inp, _output, out, _bundle = case
    changed = dict(inp)
    changed[key] = value
    with pytest.raises(TraceValidationError, match="exact built-in Boolean"):
        build_fatigue_trace_family(
            changed, out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA)


def test_missing_dispatch_control_is_rejected(case):
    inp, _output, out, _bundle = case
    changed = dict(inp)
    del changed["fatigue_check_steel"]
    with pytest.raises(TraceValidationError, match="required exact"):
        build_fatigue_trace_family(
            changed, out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA)


@pytest.mark.parametrize("value", [True, None, 0, "false"])
def test_malformed_valid_discriminators_cannot_bypass_success(value, case):
    inp, _output, _out, _bundle = case
    with pytest.raises(TraceValidationError, match="valid discriminator|inventory"):
        _build(inp, {"valid": value})


def test_truncated_invalid_payload_and_forged_invalid_are_rejected(case):
    inp, _output, _out, _bundle = case
    with pytest.raises(TraceValidationError, match="valid discriminator|inventory"):
        _build(inp, {"valid": False})
    forged = fatigue_analysis.invalid_result(inp, ("forged",))
    with pytest.raises(TraceValidationError, match="valid fatigue input"):
        _build(inp, forged)


def test_genuine_invalid_payload_is_exactly_fenced_and_deferred(case):
    inp, _output, _out, _bundle = case
    invalid = dict(inp)
    invalid["ns"] = -1.0
    payload = fatigue_analysis.invalid_result(invalid)
    assert _build(invalid, payload) is None
    tampered = copy.deepcopy(payload)
    tampered["warnings"] = (*tampered["warnings"], "fabricated")
    with pytest.raises(TraceValidationError, match="fatigue.invalid"):
        _build(invalid, tampered)


def test_disabled_missing_and_concrete_only_states_publish_no_ct010a(case):
    inp, _output, _out, _bundle = case
    disabled = dict(inp)
    disabled["fatigue_on"] = False
    assert build_fatigue_trace_family(
        disabled, {"fatigue": None}, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA) is None
    with pytest.raises(TraceValidationError, match="disabled fatigue"):
        build_fatigue_trace_family(
            disabled, {"fatigue": {}}, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA)
    assert build_fatigue_trace_family(
        inp, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA) is None
    concrete = _base(
        fatigue_check_steel=False, fatigue_check_concrete=True)
    concrete_output = fatigue_analysis.run_analysis(concrete)
    assert _build(concrete, concrete_output) is None


def test_output_inventory_order_mapping_type_and_excluded_sibling_types(case):
    inp, output, _out, _bundle = case
    reordered = {key: output[key] for key in reversed(tuple(output))}
    with pytest.raises(TraceValidationError, match="inventory/order"):
        _build(inp, reordered)

    class DictSubclass(dict):
        pass

    with pytest.raises(TraceValidationError, match="exact built-in dict"):
        _build(inp, DictSubclass(output))
    for key, replacement in (
        ("concrete_method", []),
        ("concrete_parameters", []),
    ):
        changed = dict(output)
        changed[key] = replacement
        with pytest.raises(TraceValidationError, match="excluded type"):
            _build(inp, changed)


def test_concrete_output_values_are_explicitly_inert(monkeypatch):
    inp = _base(fatigue_check_concrete=True)
    output = fatigue_analysis.run_analysis(inp)
    baseline = _build(inp, output)
    first = output["spectra"][0]
    changed_first = dataclasses.replace(
        first,
        fcd_fat_mpa=first.fcd_fat_mpa * 1.1,
        concrete=tuple(
            dataclasses.replace(item, damage=item.damage * 1.1)
            for item in first.concrete),
    )
    changed = dict(output)
    changed["spectra"] = (changed_first, *output["spectra"][1:])
    monkeypatch.setattr(
        fatigue_trace_replay, "application_boundary",
        lambda: _boundary(changed))
    assert _build(inp, changed) == baseline


def test_complete_input_geometry_material_and_description_identity(case):
    inp, output, _out, bundle = case
    changed_id = dict(inp)
    changed_id["concrete_material_id"] = "C40-same-law-A"
    first = _build(changed_id, fatigue_analysis.run_analysis(changed_id))
    changed_id["concrete_material_id"] = "C40-same-law-B"
    second = _build(changed_id, fatigue_analysis.run_analysis(changed_id))
    assert first.content_sha256 != second.content_sha256

    dtype_changed = copy.deepcopy(inp)
    dtype_changed["section"].concrete[0] = (
        dtype_changed["section"].concrete[0].astype(np.float32))
    changed_output = fatigue_analysis.run_analysis(dtype_changed)
    dtype_bundle = _build(dtype_changed, changed_output)
    assert dtype_bundle.content_sha256 != bundle.content_sha256

    described = copy.deepcopy(inp)
    frame = described[fatigue_inputs.SPECTRUM_TABLE_KEY]
    frame.loc[0, "description"] = "Published changed description"
    described_output = fatigue_analysis.run_analysis(described)
    assert _build(described, described_output).content_sha256 != (
        bundle.content_sha256)


def test_authoritative_output_spectra_are_joined_to_prepared_order(
    monkeypatch, case,
):
    inp, output, _out, _bundle = case
    changed = dict(output)
    changed["spectra"] = tuple(reversed(output["spectra"]))
    monkeypatch.setattr(
        fatigue_trace_replay, "application_boundary",
        lambda: _boundary(changed))
    with pytest.raises(TraceValidationError, match="output/prepared spectrum name"):
        _build(inp, changed)


@pytest.mark.parametrize("field", ["name", "description", "cycles"])
def test_solver_state_bins_are_joined_to_input_bins(
    monkeypatch, case, field,
):
    inp, output, _out, _bundle = case
    first_spectrum = output["spectra"][0]
    state = first_spectrum.bins[0]
    replacement = {
        "name": state.name + "-wrong",
        "description": state.description + " wrong",
        "cycles": state.cycles + 1.0,
    }[field]
    bins = (dataclasses.replace(state, **{field: replacement}),
            *first_spectrum.bins[1:])
    changed_spectrum = dataclasses.replace(first_spectrum, bins=bins)
    changed = dict(output)
    changed["spectra"] = (changed_spectrum, *output["spectra"][1:])
    monkeypatch.setattr(
        fatigue_trace_replay, "application_boundary",
        lambda: _boundary(changed))
    with pytest.raises(TraceValidationError, match="state/prepared bin"):
        _build(inp, changed)


def test_reported_bin_convergence_must_equal_matched_state(
    monkeypatch, case,
):
    inp, output, _out, _bundle = case
    spectrum = output["spectra"][0]
    assessment = spectrum.reinforcement[0]
    reported_bin = assessment.bins[0]
    changed_bin = dataclasses.replace(
        reported_bin, converged=not reported_bin.converged)
    changed_assessment = dataclasses.replace(
        assessment, bins=(changed_bin, *assessment.bins[1:]))
    changed_spectrum = dataclasses.replace(
        spectrum,
        reinforcement=(changed_assessment, *spectrum.reinforcement[1:]))
    changed = dict(output)
    changed["spectra"] = (changed_spectrum, *output["spectra"][1:])
    monkeypatch.setattr(
        fatigue_trace_replay, "application_boundary",
        lambda: _boundary(changed))
    with pytest.raises(TraceValidationError, match="reported bin convergence"):
        _build(inp, changed)


def test_retained_design_stress_and_assessment_identity_are_reconstructed(case):
    inp, output, _out, _bundle = case
    spectrum = output["spectra"][0]
    assessment = spectrum.reinforcement[0]
    first_bin = assessment.bins[0]
    changed_bin = dataclasses.replace(
        first_bin,
        stress_total_design_mpa=first_bin.stress_total_design_mpa + 1.0)
    changed_assessment = dataclasses.replace(
        assessment, bins=(changed_bin, *assessment.bins[1:]))
    changed_spectrum = dataclasses.replace(
        spectrum,
        reinforcement=(changed_assessment, *spectrum.reinforcement[1:]))
    changed = dict(output)
    changed["spectra"] = (changed_spectrum, *output["spectra"][1:])
    with pytest.raises(TraceValidationError, match="design total|value differs"):
        _build(inp, changed)

    changed_assessment = dataclasses.replace(assessment, element_id="R-wrong")
    changed_spectrum = dataclasses.replace(
        spectrum,
        reinforcement=(changed_assessment, *spectrum.reinforcement[1:]))
    changed["spectra"] = (changed_spectrum, *output["spectra"][1:])
    with pytest.raises(TraceValidationError, match="value differs|element ID"):
        _build(inp, changed)


def test_standard_custom_mild_and_prestress_provenance(case):
    _inp, _output, _out, bundle = case
    bar, tendon = bundle.calculations[0], bundle.calculations[1]
    bar_sources = {item.source.method_id: item.source for item in bar.steps}
    tendon_sources = {item.source.method_id: item.source for item in tendon.steps}
    assert bar_sources["en-1992-reinforcement-fatigue-sn"].kind == SOURCE_STANDARD
    assert bar_sources["en-1992-reinforcement-fatigue-proof"].citation.clause == (
        "5.2.4 and Annex E.5")
    assert tendon_sources["en-1992-prestress-fatigue-proof"].citation.clause == (
        "5.3.3 and Annex E.5")

    custom = _base(fatigue_check_concrete=False)
    catalogue = custom[fatigue_inputs.DETAIL_CATALOG_KEY]
    catalogue["items"][0]["n_star"] = 3.0e6
    catalogue["items"][0]["source"] = "Project S-N test series SN-04"
    custom[fatigue_inputs.DETAIL_CATALOG_KEY] = (
        fatigue_inputs.normalise_catalog(catalogue))
    custom_bundle = _build(custom, fatigue_analysis.run_analysis(custom))
    custom_source = next(
        item.source for item in custom_bundle.calculations[0].steps
        if item.source.method_id == "sector-custom-reinforcement-fatigue-sn")
    assert custom_source.kind == SOURCE_PROJECT
    assert custom_source.citation is None
    assert any(
        "Project-defined S-N source: Project S-N test series SN-04" in warning
        for item in custom_bundle.calculations[0].steps
        for warning in item.warnings)


def test_aggregate_has_independent_utilisation_convergence_and_verdict(case):
    _inp, output, _out, bundle = case
    aggregate = bundle.calculations[-1]
    ids = {item.step_id for item in aggregate.steps}
    for spectrum_position, spectrum in enumerate(output["spectra"], 1):
        for element_position, _assessment in enumerate(
                spectrum.reinforcement, 1):
            prefix = (
                f"spectrum-{spectrum_position}-element-{element_position}")
            assert {
                f"{prefix}-utilisation", f"{prefix}-converged",
                f"{prefix}-passed",
            } <= ids
    assert {
        "global-governing-spectrum", "global-governing-element",
        "global-utilisation", "global-converged", "global-passed",
    } <= ids
    final = aggregate.steps[-1]
    assert {item.step_id for item in aggregate.steps[:-1]} == {
        item.step_id for item in final.dependencies}


def test_stale_and_coherently_resealed_graph_tampering_is_rejected(case):
    inp, _output, out, bundle = case
    calculation = bundle.calculations[0]
    step = calculation.steps[-2]
    tampered_step = dataclasses.replace(
        step, result=TraceResult(step.result.state, step.result.value + 0.01))
    tampered_calculation = dataclasses.replace(
        calculation,
        steps=(*calculation.steps[:-2], tampered_step,
               calculation.steps[-1]))
    tampered = seal_bundle(dataclasses.replace(
        bundle,
        calculations=(tampered_calculation, *bundle.calculations[1:]),
        content_sha256=""))
    with pytest.raises(TraceValidationError, match="authoritative input replay"):
        validate_fatigue_trace_family(
            tampered, inp, out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)

    with pytest.raises(TraceValidationError, match="current input fingerprint"):
        validate_fatigue_trace_family(
            bundle, inp, out, input_sha256="3" * 64,
            result_sha256=RESULT_SHA, context=CONTEXT)


def test_reinforcement_output_and_fingerprint_tampering_fail(case):
    inp, output, out, bundle = case
    changed = dict(output)
    changed["utilisation"] = output["utilisation"] + 0.1
    with pytest.raises(TraceValidationError, match="value differs|utilisation"):
        _build(inp, changed)
    with pytest.raises(TraceValidationError, match="current result fingerprint"):
        validate_fatigue_trace_family(
            bundle, inp, out, input_sha256=INPUT_SHA,
            result_sha256="4" * 64, context=CONTEXT)
