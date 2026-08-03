"""Independent CT-010a success-contract and hostile-boundary tests."""

from __future__ import annotations

import copy
import dataclasses
import math
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
    RESULT_FAILED, RESULT_POSITIVE_INFINITY, SOURCE_INPUT, SOURCE_PROJECT,
    SOURCE_STANDARD, TraceResult, TraceValidationError, bundle_from_json,
    bundle_to_json, create_bundle, seal_bundle,
)
from sector.fatigue_trace import (
    build_fatigue_trace_family, validate_fatigue_trace_family,
)
from sector.fatigue_trace_contract import (
    CONCRETE_VERDICT, MemberShape, StepShape, registry_for,
)
from sector import fatigue
from sector import fatigue_trace_replay
from sector.section import Section
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


def _concrete_input(*, edition=None, method=None):
    inp = _base(
        fatigue_check_steel=False,
        fatigue_check_concrete=True,
    )
    inp["section"] = Section.from_polygon([
        (-0.20, -0.30),
        (0.20, -0.30),
        (0.20, 0.30),
        (-0.20, 0.30),
    ])
    inp["bar_elements"] = []
    inp["tendon_elements"] = []
    inp["bar_materials"] = []
    inp["tendon_materials"] = []
    inp[fatigue_inputs.SPECTRUM_TABLE_KEY] = (
        fatigue_inputs.normalise_spectrum_table([{
            "spectrum": "Uniform concrete",
            "name": "CONC-1",
            "description": "Uniform compression range",
            "cycles": 2.0e5,
            "n_long_ed_kn": -100.0,
            "n_short_ed_kn": -20.0,
        }])
    )
    if edition is not None:
        inp["fatigue_edition"] = edition
    if method is not None:
        inp["fatigue_concrete_method"] = method
    return inp


@pytest.fixture(scope="module")
def concrete_case():
    inp = _concrete_input()
    output = fatigue_analysis.run_analysis(inp)
    out = {"fatigue": output}
    bundle = _build(inp, output)
    return inp, output, out, bundle


def _reachable(calculation):
    by_id = {step.step_id: step for step in calculation.steps}
    reached = set()
    pending = [calculation.final_step_id]
    while pending:
        step_id = pending.pop()
        if step_id in reached:
            continue
        reached.add(step_id)
        pending.extend(
            dependency.step_id for dependency in by_id[step_id].dependencies
        )
    return reached


def _changed(value):
    if type(value) is bool:
        return not value
    if value is None:
        return 0.0
    if type(value) is str:
        return value + "-tampered"
    if isinstance(value, int):
        return value + 1
    number = float(value)
    if math.isinf(number):
        return 0.0
    if abs(number) > 1.0e6:
        return number * 0.5
    return number + 1.0


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


def test_genuine_invalid_payload_builds_one_minimal_failed_member(case):
    inp, _output, _out, _bundle = case
    invalid = dict(inp)
    invalid["ns"] = -1.0
    payload = fatigue_analysis.invalid_result(invalid)
    bundle = _build(invalid, payload)
    assert len(bundle.calculations) == 1
    calculation = bundle.calculations[0]
    assert calculation.final_step_id == "reinforcement-fatigue-invalid-result"
    assert calculation.steps[-1].result.state == RESULT_FAILED
    assert calculation.steps[-1].result.value is None
    assert "Long-term modular ratio" not in calculation.steps[-1].result.reason
    assert "Short-term modular ratio" in calculation.steps[-1].result.reason
    assert all(
        item.source.kind in {SOURCE_INPUT, SOURCE_PROJECT}
        for item in calculation.steps)
    assert {item.step_id for item in calculation.steps[:-1]} == {
        item.step_id for item in calculation.steps[-1].dependencies}
    assert validate_fatigue_trace_family(
        bundle, invalid, {"fatigue": payload}, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) == bundle
    tampered = copy.deepcopy(payload)
    tampered["warnings"] = (*tampered["warnings"], "fabricated")
    with pytest.raises(TraceValidationError, match="fatigue.invalid"):
        _build(invalid, tampered)


def test_invalid_branch_does_not_traverse_failure_only_geometry(case):
    inp, _output, _out, _bundle = case
    left = dict(inp)
    right = dict(inp)
    left["section"] = None
    right["section"] = object()
    left_payload = fatigue_analysis.invalid_result(left)
    right_payload = fatigue_analysis.invalid_result(right)
    assert left_payload == right_payload
    left_bundle = _build(left, left_payload)
    right_bundle = _build(right, right_payload)
    assert left_bundle == right_bundle


def test_invalid_error_order_and_coherent_reseal_are_fenced(case):
    inp, _output, _out, _bundle = case
    invalid = dict(inp)
    invalid["section"] = None
    invalid["ns"] = -1.0
    payload = fatigue_analysis.invalid_result(invalid)
    assert len(payload["errors"]) >= 2
    reordered = dict(payload)
    reordered["errors"] = tuple(reversed(payload["errors"]))
    with pytest.raises(TraceValidationError, match="fatigue.invalid"):
        _build(invalid, reordered)

    bundle = _build(invalid, payload)
    first = bundle.calculations[0]
    step = first.steps[0]
    changed_step = dataclasses.replace(
        step, result=TraceResult(step.result.state, step.result.value + 1.0))
    changed_calculation = dataclasses.replace(
        first, steps=(changed_step, *first.steps[1:]))
    changed = seal_bundle(dataclasses.replace(
        bundle, calculations=(changed_calculation,), content_sha256=""))
    with pytest.raises(TraceValidationError, match="authoritative input replay"):
        validate_fatigue_trace_family(
            changed, invalid, {"fatigue": payload}, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)


def test_invalid_branch_ignores_unrelated_output_families(case):
    inp, _output, _out, _bundle = case
    invalid = dict(inp)
    invalid["ns"] = -1.0
    payload = fatigue_analysis.invalid_result(invalid)
    out = {"fatigue": payload, "unrelated": object()}
    assert build_fatigue_trace_family(
        invalid, out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) is not None


@pytest.mark.parametrize(
    "raw",
    [None, float("nan"), False, ["malformed"], 1 + 2j, object()],
)
def test_invalid_branch_accepts_retained_non_numeric_failure_fields(case, raw):
    inp, _output, _out, _bundle = case
    invalid = dict(inp)
    invalid["fatigue_gamma_s"] = raw
    payload = fatigue_analysis.invalid_result(invalid)
    bundle = _build(invalid, payload)
    assert bundle.calculations[0].steps[-1].result.state == RESULT_FAILED


def test_disabled_missing_and_concrete_only_dispatch(case):
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
    concrete = _concrete_input()
    concrete_output = fatigue_analysis.run_analysis(concrete)
    assert _build(concrete, concrete_output) is not None
    concrete["ns"] = -1.0
    concrete_invalid = fatigue_analysis.invalid_result(concrete)
    invalid_bundle = _build(concrete, concrete_invalid)
    assert invalid_bundle.calculations[0].final_step_id == (
        "concrete-fatigue-invalid-result")
    assert invalid_bundle.calculations[0].steps[-1].result.state == RESULT_FAILED
    assert invalid_bundle.calculations[0].steps[-1].source == CONCRETE_VERDICT


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


def test_concrete_output_values_are_value_bearing(monkeypatch):
    inp = _concrete_input()
    output = fatigue_analysis.run_analysis(inp)
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
    with pytest.raises(TraceValidationError, match="concrete"):
        _build(inp, changed)


@pytest.mark.parametrize(
    "field",
    [
        "concrete_method",
        "concrete_parameters",
        "t0_days",
        "partial_factors",
        "calculation_references",
        "governing_spectrum",
        "utilisation",
        "converged",
        "passed",
    ],
)
def test_every_concrete_top_level_output_is_value_bearing(
    concrete_case, monkeypatch, field,
):
    inp, output, _out, _bundle = concrete_case
    changed = dict(output)
    if field in {"concrete_parameters", "partial_factors"}:
        nested = dict(output[field])
        key = "fck_mpa" if field == "concrete_parameters" else "gamma_c"
        nested[key] = _changed(nested[key])
        changed[field] = nested
    elif field == "calculation_references":
        nested = dict(output[field])
        nested["concrete"] = _changed(nested["concrete"])
        changed[field] = nested
    else:
        changed[field] = _changed(output[field])
    monkeypatch.setattr(
        fatigue_trace_replay,
        "application_boundary",
        lambda: _boundary(changed),
    )
    with pytest.raises(TraceValidationError):
        _build(inp, changed)


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


def test_concrete_round_trip_registry_shape_and_complete_reachability(
    concrete_case,
):
    inp, _output, out, bundle = concrete_case
    assert len(bundle.calculations) == 6
    assert [item.method_id for item in bundle.calculations].count(
        "sector-retained-concrete-fatigue-replay") == 5
    assert bundle.calculations[-1].final_step_id == "fatigue-aggregate-result"
    for calculation in bundle.calculations:
        assert _reachable(calculation) == {
            step.step_id for step in calculation.steps
        }
    assert validate_fatigue_trace_family(
        bundle,
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    ) == bundle


def test_reinforcement_only_bundle_remains_byte_identical(case):
    assert case[3].content_sha256 == (
        "47de2205aea9befd4d9a617f4b5310c4cf4fc192d86a75b8a3f239608f028a20"
    )


def test_2023_concrete_strength_life_damage_and_verdict_oracle(concrete_case):
    _inp, output, _out, bundle = concrete_case
    spectrum = output["spectra"][0]
    reported = spectrum.concrete[0]
    reported_bin = reported.bins[0]
    calculation = bundle.calculations[0]
    steps = {step.step_id: step for step in calculation.steps}
    fck = output["concrete_parameters"]["fck_mpa"]
    beta = output["concrete_parameters"]["beta_cc_t0"]
    gamma_c = output["partial_factors"]["gamma_c"]
    eta = min((40.0 / fck) ** (1.0 / 3.0), 1.0)
    strength = beta * fck / gamma_c * min(0.85 * eta, 0.8)
    sigma_min = reported_bin.compression_min_design_mpa
    sigma_max = reported_bin.compression_max_design_mpa
    ratio = sigma_min / sigma_max
    log_life = 14.0 * (1.0 - sigma_max / strength) / math.sqrt(
        1.0 - ratio
    )
    damage = reported_bin.cycles / (10.0 ** log_life)
    assert steps["fcd-fat"].result.value == pytest.approx(strength)
    assert steps["fcd-fat"].source.citation.clause == "10.5"
    assert steps["bin-1-log-life"].result.value == pytest.approx(log_life)
    assert steps["bin-1-damage"].result.value == pytest.approx(damage)
    assert steps["assessment-utilisation"].result.value == pytest.approx(
        max(reported.damage, reported.stress_utilisation)
    )
    assert steps["assessment-passed"].result.value == float(reported.passed)


@pytest.mark.parametrize(
    "edition,expected",
    [
        (
            fatigue_inputs.EC2_2005,
            lambda output: (
                output["concrete_parameters"]["k1"]
                * output["concrete_parameters"]["beta_cc_t0"]
                * output["concrete_parameters"]["alpha_cc"]
                * output["concrete_parameters"]["fck_mpa"]
                / output["partial_factors"]["gamma_c"]
                * (1.0 - output["concrete_parameters"]["fck_mpa"] / 250.0)
            ),
        ),
        (
            fatigue_inputs.EC2_2023,
            lambda output: (
                output["concrete_parameters"]["beta_cc_t0"]
                * output["concrete_parameters"]["fck_mpa"]
                / output["partial_factors"]["gamma_c"]
                * min(
                    0.85 * min(
                        (40.0 / output["concrete_parameters"]["fck_mpa"])
                        ** (1.0 / 3.0),
                        1.0,
                    ),
                    0.8,
                )
            ),
        ),
    ],
)
def test_edition_strength_variants_use_one_frozen_oracle(edition, expected):
    inp = _concrete_input(edition=edition)
    output = fatigue_analysis.run_analysis(inp)
    bundle = _build(inp, output)
    fcd = next(
        step for step in bundle.calculations[0].steps
        if step.step_id == "fcd-fat"
    )
    assert fcd.result.value == pytest.approx(expected(output))


@pytest.mark.parametrize(
    "method,source_kind,source_id",
    [
        (
            fatigue.CONCRETE_MINER,
            SOURCE_STANDARD,
            "en-1992-concrete-fatigue-miner",
        ),
        (
            fatigue.CONCRETE_PROJECT_MINER,
            SOURCE_PROJECT,
            "sector-project-concrete-fatigue-sn",
        ),
        (
            fatigue.CONCRETE_EQUIVALENT,
            SOURCE_STANDARD,
            "en-1992-concrete-fatigue-equivalent",
        ),
    ],
)
def test_concrete_methods_have_exact_branch_and_provenance(
    method, source_kind, source_id,
):
    inp = _concrete_input(method=method)
    output = fatigue_analysis.run_analysis(inp)
    bundle = _build(inp, output)
    calculation = bundle.calculations[0]
    sources = {step.source.method_id: step.source for step in calculation.steps}
    assert sources[source_id].kind == source_kind
    if source_kind == SOURCE_PROJECT:
        assert sources[source_id].citation is None
        assert output["calculation_references"]["concrete"] == (
            "Project-defined concrete Miner S-N relation (uncited)"
        )
        assert any("uncited" in warning for warning in output["warnings"])
    if method == fatigue.CONCRETE_EQUIVALENT:
        by_id = {step.step_id: step for step in calculation.steps}
        reported = output["spectra"][0].concrete[0].bins[0]
        ratio = reported.compression_min_design_mpa / (
            reported.compression_max_design_mpa)
        expected = (
            reported.compression_max_design_mpa
            / output["spectra"][0].fcd_fat_mpa
            + 0.43 * math.sqrt(1.0 - ratio)
        )
        assert by_id["bin-1-equivalent-utilisation"].result.value == (
            pytest.approx(expected))
        assert by_id["bin-1-life"].result.state == RESULT_POSITIVE_INFINITY
        assert by_id["bin-1-damage"].result.value == 0.0


def test_bounded_search_certificate_reaches_concrete_spectrum_final(
    concrete_case,
):
    _inp, output, _out, bundle = concrete_case
    reported = output["spectra"][0].concrete_search
    calculation = bundle.calculations[-2]
    by_id = {step.step_id: step for step in calculation.steps}
    assert by_id["search-initial-divisions"].result.value == 4.0
    assert by_id["search-max-depth"].result.value == 26.0
    assert by_id["search-max-boxes"].result.value == 200_000.0
    assert by_id["search-best"].result.value == pytest.approx(reported.damage)
    assert by_id["search-upper"].result.value == pytest.approx(
        reported.upper_damage)
    assert by_id["search-absolute-gap"].result.value == pytest.approx(
        max(reported.upper_damage - reported.damage, 0.0)
    )
    assert by_id["search-relative-gap"].result.value == pytest.approx(
        reported.absolute_gap / max(abs(reported.upper_damage), 1.0e-12)
    )
    assert by_id["concrete-spectrum-utilisation"].result.value == pytest.approx(
        max(
            reported.upper_damage,
            *(item.utilisation for item in output["spectra"][0].concrete),
        )
    )


CONCRETE_BIN_FIELDS = tuple(
    field.name for field in dataclasses.fields(fatigue.ConcreteBinResult)
)
CONCRETE_FIBRE_FIELDS = tuple(
    field.name for field in dataclasses.fields(
        fatigue.ConcreteFibreFatigueResult)
    if field.name != "bins"
)
CONCRETE_SEARCH_FIELDS = tuple(
    field.name for field in dataclasses.fields(fatigue.ConcreteFibreSearch)
)


@pytest.mark.parametrize("field", CONCRETE_BIN_FIELDS)
def test_every_concrete_bin_output_leaf_is_independently_checked(
    concrete_case, monkeypatch, field,
):
    inp, output, _out, _bundle = concrete_case
    spectrum = output["spectra"][0]
    fibre = spectrum.concrete[0]
    reported = fibre.bins[0]
    changed_bin = dataclasses.replace(
        reported, **{field: _changed(getattr(reported, field))})
    changed_fibre = dataclasses.replace(fibre, bins=(changed_bin,))
    changed_spectrum = dataclasses.replace(
        spectrum,
        concrete=(changed_fibre, *spectrum.concrete[1:]),
    )
    changed = dict(output)
    changed["spectra"] = (changed_spectrum,)
    monkeypatch.setattr(
        fatigue_trace_replay,
        "application_boundary",
        lambda: _boundary(changed),
    )
    with pytest.raises(TraceValidationError):
        _build(inp, changed)


@pytest.mark.parametrize("field", CONCRETE_FIBRE_FIELDS)
def test_every_concrete_fibre_output_leaf_is_independently_checked(
    concrete_case, monkeypatch, field,
):
    inp, output, _out, _bundle = concrete_case
    spectrum = output["spectra"][0]
    reported = spectrum.concrete[0]
    changed_fibre = dataclasses.replace(
        reported, **{field: _changed(getattr(reported, field))})
    changed_spectrum = dataclasses.replace(
        spectrum,
        concrete=(changed_fibre, *spectrum.concrete[1:]),
    )
    changed = dict(output)
    changed["spectra"] = (changed_spectrum,)
    monkeypatch.setattr(
        fatigue_trace_replay,
        "application_boundary",
        lambda: _boundary(changed),
    )
    with pytest.raises(TraceValidationError):
        _build(inp, changed)


@pytest.mark.parametrize("field", CONCRETE_SEARCH_FIELDS)
def test_every_concrete_search_output_leaf_is_independently_checked(
    concrete_case, monkeypatch, field,
):
    inp, output, _out, _bundle = concrete_case
    spectrum = output["spectra"][0]
    search = spectrum.concrete_search
    changed_search = dataclasses.replace(
        search, **{field: _changed(getattr(search, field))})
    changed_spectrum = dataclasses.replace(
        spectrum, concrete_search=changed_search)
    changed = dict(output)
    changed["spectra"] = (changed_spectrum,)
    monkeypatch.setattr(
        fatigue_trace_replay,
        "application_boundary",
        lambda: _boundary(changed),
    )
    with pytest.raises(TraceValidationError):
        _build(inp, changed)


@pytest.mark.parametrize(
    "field",
    [
        "concrete_compression_long_mpa",
        "concrete_compression_total_mpa",
        "concrete_compression_design_total_mpa",
    ],
)
def test_concrete_solver_stress_vectors_are_reconstructed_from_planes(
    concrete_case, monkeypatch, field,
):
    inp, output, _out, _bundle = concrete_case
    spectrum = output["spectra"][0]
    state = spectrum.bins[0]
    vector = getattr(state, field)
    changed_state = dataclasses.replace(
        state, **{field: (vector[0] + 1.0, *vector[1:])})
    changed_spectrum = dataclasses.replace(spectrum, bins=(changed_state,))
    changed = dict(output)
    changed["spectra"] = (changed_spectrum,)
    monkeypatch.setattr(
        fatigue_trace_replay,
        "application_boundary",
        lambda: _boundary(changed),
    )
    with pytest.raises(TraceValidationError, match="state .* compression"):
        _build(inp, changed)


@pytest.mark.parametrize(
    "field",
    [
        "fcd_fat_mpa",
        "governing_concrete_fibre",
        "concrete_method",
        "utilisation",
        "converged",
        "passed",
    ],
)
def test_concrete_spectrum_and_mixed_fields_are_reconstructed(
    concrete_case, monkeypatch, field,
):
    inp, output, _out, _bundle = concrete_case
    spectrum = output["spectra"][0]
    changed_spectrum = dataclasses.replace(
        spectrum, **{field: _changed(getattr(spectrum, field))})
    changed = dict(output)
    changed["spectra"] = (changed_spectrum,)
    monkeypatch.setattr(
        fatigue_trace_replay,
        "application_boundary",
        lambda: _boundary(changed),
    )
    with pytest.raises(TraceValidationError):
        _build(inp, changed)


def test_concrete_cardinality_and_order_are_fenced(
    concrete_case, monkeypatch,
):
    inp, output, _out, _bundle = concrete_case
    spectrum = output["spectra"][0]
    for concrete in (
        spectrum.concrete[:-1],
        tuple(reversed(spectrum.concrete)),
        list(spectrum.concrete),
    ):
        changed_spectrum = dataclasses.replace(spectrum, concrete=concrete)
        changed = dict(output)
        changed["spectra"] = (changed_spectrum,)
        monkeypatch.setattr(
            fatigue_trace_replay,
            "application_boundary",
            lambda changed=changed: _boundary(changed),
        )
        with pytest.raises(TraceValidationError):
            _build(inp, changed)


def test_concrete_only_invalid_is_failure_first_and_geometry_inert():
    left = _concrete_input()
    right = _concrete_input()
    left["ns"] = -1.0
    right["ns"] = -1.0
    left["section"] = None
    right["section"] = object()
    left_payload = fatigue_analysis.invalid_result(left)
    right_payload = fatigue_analysis.invalid_result(right)
    assert left_payload == right_payload
    assert _build(left, left_payload) == _build(right, right_payload)


def test_compact_mixed_case_closes_complete_global_aggregate():
    inp = _base(fatigue_check_steel=True, fatigue_check_concrete=True)
    inp["section"] = Section.from_polygon(
        [(-0.20, -0.30), (0.20, -0.30), (0.20, 0.30), (-0.20, 0.30)],
        [(0.0, -0.22, 314.0)],
    )
    inp["tendon_elements"] = []
    inp["tendon_materials"] = []
    inp[fatigue_inputs.SPECTRUM_TABLE_KEY] = (
        fatigue_inputs.normalise_spectrum_table([{
            "spectrum": "Mixed compact",
            "name": "MIX-1",
            "description": "Uniform compression plus mild reinforcement",
            "cycles": 2.0e5,
            "n_long_ed_kn": -100.0,
            "n_short_ed_kn": -20.0,
        }])
    )
    output = fatigue_analysis.run_analysis(inp)
    bundle = _build(inp, output)
    assert bundle.calculations[0].final_step_id == (
        "reinforcement-fatigue-result")
    assert any(
        item.final_step_id == "concrete-fatigue-spectrum-result"
        for item in bundle.calculations
    )
    assert bundle.calculations[-1].steps[-1].result.value == pytest.approx(
        output["utilisation"])
