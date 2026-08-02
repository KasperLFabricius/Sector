"""Focused oracle and hostile-boundary tests for successful CT-010a."""

from __future__ import annotations

import copy
import dataclasses
from types import SimpleNamespace

import numpy as np
import pytest

from test_fatigue_analysis import _base

import fatigue_analysis

from sector import fatigue_trace
from sector.calculation_trace import (
    TraceAxis, TraceValidationError, bundle_from_json, bundle_to_json,
    seal_bundle,
)
from sector.fatigue_trace import (
    build_fatigue_trace_family, validate_fatigue_trace_family,
)
from sector.fatigue_trace_contract import (
    INVALID_KEYS, SUCCESS_KEYS, fatigue_sources,
)


INPUT_HASH = "a" * 64
RESULT_HASH = "b" * 64


@pytest.fixture(scope="module")
def retained_success():
    inp = _base()
    return inp, fatigue_analysis.run_analysis(inp)


def _adapter_with(replay):
    return SimpleNamespace(
        run_analysis=lambda _inp: replay,
        prepare=fatigue_analysis.prepare,
        analysis_signature=fatigue_analysis.analysis_signature,
        invalid_result=fatigue_analysis.invalid_result,
        validation_errors=fatigue_analysis.validation_errors,
    )


def _pin(monkeypatch, replay):
    monkeypatch.setattr(fatigue_trace, "_adapter", lambda: _adapter_with(replay))


def _build(monkeypatch, inp, replay, candidate=None):
    _pin(monkeypatch, replay)
    return build_fatigue_trace_family(
        inp, {"fatigue": replay if candidate is None else candidate},
        input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)


def _replace_spectrum(payload, position, **changes):
    spectra = list(payload["spectra"])
    spectra[position] = dataclasses.replace(spectra[position], **changes)
    payload["spectra"] = tuple(spectra)


def test_success_round_trip_registry_and_exact_hashes(
    retained_success, monkeypatch,
):
    inp, replay = retained_success
    bundle = _build(monkeypatch, inp, replay)

    assert tuple(replay) == SUCCESS_KEYS
    assert len(bundle.calculations) == 5
    assert bundle.input_sha256 == INPUT_HASH
    assert bundle.result_sha256 == RESULT_HASH
    restored = bundle_from_json(bundle_to_json(bundle))
    assert validate_fatigue_trace_family(
        restored, inp, {"fatigue": replay},
        input_sha256=INPUT_HASH, result_sha256=RESULT_HASH) == bundle


@pytest.mark.parametrize(
    "key,value",
    [
        ("fatigue_on", 1),
        ("fatigue_check_steel", np.bool_(True)),
        ("fatigue_check_concrete", "true"),
    ],
)
def test_dispatch_booleans_are_exact_before_output_selection(
    retained_success, monkeypatch, key, value,
):
    inp, replay = retained_success
    changed = dict(inp)
    changed[key] = value
    _pin(monkeypatch, replay)
    with pytest.raises(TraceValidationError, match="exact built-in Boolean"):
        build_fatigue_trace_family(
            changed, {"fatigue": None},
            input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)


def test_missing_dispatch_boolean_fails_closed(retained_success, monkeypatch):
    inp, replay = retained_success
    changed = dict(inp)
    changed.pop("fatigue_on")
    _pin(monkeypatch, replay)
    with pytest.raises(TraceValidationError, match="required exact"):
        build_fatigue_trace_family(
            changed, {"fatigue": None},
            input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)


@pytest.mark.parametrize("discriminator", [True, None, 0, "false"])
def test_any_nonfalse_or_truncated_valid_payload_is_corrupt(
    retained_success, monkeypatch, discriminator,
):
    inp, replay = retained_success
    _pin(monkeypatch, replay)
    with pytest.raises(TraceValidationError, match="valid discriminator"):
        build_fatigue_trace_family(
            inp, {"fatigue": {"valid": discriminator}},
            input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)


def test_deferred_invalid_requires_exact_inventory_and_replay_before_geometry(
    retained_success, monkeypatch,
):
    inp, _replay = retained_success
    malformed = copy.deepcopy(inp)
    malformed["section"] = {}
    invalid = fatigue_analysis.invalid_result(
        malformed, fatigue_analysis.validation_errors(malformed))
    assert tuple(invalid) == INVALID_KEYS
    _pin(monkeypatch, None)

    assert build_fatigue_trace_family(
        malformed, {"fatigue": invalid},
        input_sha256=INPUT_HASH, result_sha256=RESULT_HASH) is None
    corrupted = dict(invalid)
    corrupted["errors"] = ()
    with pytest.raises(TraceValidationError, match="differs"):
        build_fatigue_trace_family(
            malformed, {"fatigue": corrupted},
            input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)
    truncated = dict(invalid)
    truncated.pop("utilisation")
    with pytest.raises(TraceValidationError, match="valid discriminator"):
        build_fatigue_trace_family(
            malformed, {"fatigue": truncated},
            input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)

    valid_input, _ = retained_success
    forged = fatigue_analysis.invalid_result(valid_input, ())
    with pytest.raises(TraceValidationError, match="valid fatigue input"):
        build_fatigue_trace_family(
            valid_input, {"fatigue": forged},
            input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)


def test_disabled_missing_and_inapplicable_outputs_are_fenced(
    retained_success, monkeypatch,
):
    inp, replay = retained_success
    _pin(monkeypatch, replay)
    assert build_fatigue_trace_family(
        inp, {"fatigue": None},
        input_sha256=INPUT_HASH, result_sha256=RESULT_HASH) is None
    disabled = dict(inp)
    disabled["fatigue_on"] = False
    assert build_fatigue_trace_family(
        disabled, {"fatigue": None},
        input_sha256=INPUT_HASH, result_sha256=RESULT_HASH) is None
    with pytest.raises(TraceValidationError, match="disabled"):
        build_fatigue_trace_family(
            disabled, {"fatigue": replay},
            input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)
    with pytest.raises(TraceValidationError, match="cannot carry evidence"):
        validate_fatigue_trace_family(
            {"not": "a bundle"}, inp, {"fatigue": None},
            input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)


def test_output_order_mapping_types_and_concrete_sibling_types_are_exact(
    retained_success, monkeypatch,
):
    class DictSubclass(dict):
        pass

    inp, replay = retained_success
    _pin(monkeypatch, replay)
    candidates = []
    candidates.append({key: replay[key] for key in reversed(replay)})
    candidates.append(DictSubclass(replay))
    concrete_method = copy.deepcopy(replay)
    concrete_method["concrete_method"] = [replay["concrete_method"]]
    candidates.append(concrete_method)
    concrete_parameters = copy.deepcopy(replay)
    concrete_parameters["concrete_parameters"] = [
        replay["concrete_parameters"]]
    candidates.append(concrete_parameters)
    partial = copy.deepcopy(replay)
    partial["partial_factors"] = DictSubclass(partial["partial_factors"])
    candidates.append(partial)

    for candidate in candidates:
        with pytest.raises(TraceValidationError):
            build_fatigue_trace_family(
                inp, {"fatigue": candidate},
                input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)


def test_concrete_values_are_excluded_but_not_their_shape(
    retained_success, monkeypatch,
):
    inp, replay = retained_success
    changed = copy.deepcopy(replay)
    changed["concrete_method"] = "Excluded concrete method"
    changed["concrete_parameters"]["fck_mpa"] += 77.0
    assert _build(monkeypatch, inp, replay, changed) is not None


def test_reinforcement_only_shared_outputs_are_exact_and_reconstructed(
    retained_success, monkeypatch,
):
    inp, replay = retained_success
    changed_input = copy.deepcopy(inp)
    changed_input["fatigue_check_concrete"] = False
    steel = copy.deepcopy(replay)
    steel["checks"]["concrete"] = False
    steel["concrete_method"] = None
    steel["calculation_references"].pop("concrete")
    steel["partial_factors"]["gamma_c"] = None
    steel["concrete_parameters"] = None
    steel["t0_days"] = None
    for position, spectrum in enumerate(steel["spectra"]):
        governing = max(
            spectrum.reinforcement, key=lambda item: item.utilisation)
        _replace_spectrum(
            steel, position,
            concrete=(), concrete_search=None, fcd_fat_mpa=None,
            governing_concrete_fibre=None, concrete_method=None,
            utilisation=governing.utilisation,
            converged=all(item.converged for item in spectrum.reinforcement),
            passed=all(item.passed for item in spectrum.reinforcement),
        )
    governing = max(steel["spectra"], key=lambda item: item.utilisation)
    steel["governing_spectrum"] = governing.spectrum_name
    steel["utilisation"] = governing.utilisation
    steel["converged"] = all(item.converged for item in steel["spectra"])
    steel["passed"] = all(item.passed for item in steel["spectra"])

    assert _build(monkeypatch, changed_input, steel) is not None
    tampered = copy.deepcopy(steel)
    tampered["utilisation"] += 0.25
    _pin(monkeypatch, steel)
    with pytest.raises(TraceValidationError, match="value differs"):
        build_fatigue_trace_family(
            changed_input, {"fatigue": tampered},
            input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)


def test_description_material_identity_and_geometry_scalar_type_are_sealed(
    retained_success, monkeypatch,
):
    inp, replay = retained_success
    baseline = _build(monkeypatch, inp, replay)

    described_input = copy.deepcopy(inp)
    described_input["fatigue_spectrum_base"].loc[0, "description"] = "Revised"
    described_replay = copy.deepcopy(replay)
    states = list(described_replay["spectra"][0].bins)
    states[0] = dataclasses.replace(states[0], description="Revised")
    _replace_spectrum(described_replay, 0, bins=tuple(states))
    described = _build(monkeypatch, described_input, described_replay)

    concrete_input = copy.deepcopy(inp)
    concrete_input["concrete_material_id"] = "C-identical-law-new-id"
    concrete_input["concrete_preset"] = "Same law, separate identity"
    concrete = _build(monkeypatch, concrete_input, replay)

    typed_input = copy.deepcopy(inp)
    typed_input["section"].concrete[0] = (
        typed_input["section"].concrete[0].astype(np.float32))
    typed = _build(monkeypatch, typed_input, replay)

    assert len({
        baseline.content_sha256, described.content_sha256,
        concrete.content_sha256, typed.content_sha256,
    }) == 4
    for bundle in (baseline, described, concrete, typed):
        for calculation in bundle.calculations:
            final = calculation.steps[-1]
            assert any(
                dependency.step_id.startswith("identity-complete-original-input")
                for dependency in final.dependencies)


def test_matched_state_controls_design_stress_and_damage(
    retained_success, monkeypatch,
):
    inp, replay = retained_success
    changed = copy.deepcopy(replay)
    states = list(changed["spectra"][0].bins)
    values = list(states[0].bar_stress_fatigue_design_total_mpa)
    values[0] += 9.0
    states[0] = dataclasses.replace(
        states[0], bar_stress_fatigue_design_total_mpa=tuple(values))
    _replace_spectrum(changed, 0, bins=tuple(states))
    _pin(monkeypatch, changed)

    with pytest.raises(TraceValidationError, match="design total"):
        build_fatigue_trace_family(
            inp, {"fatigue": changed},
            input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)


def test_standard_and_custom_sources_are_kind_correct_and_uncited_as_required(
    retained_success, monkeypatch,
):
    inp, replay = retained_success
    standard = _build(monkeypatch, inp, replay)
    mild_proof = fatigue_sources(
        replay["edition"], "mild", custom_detail=False)[1]
    tendon_proof = fatigue_sources(
        replay["edition"], "prestress", custom_detail=False)[1]
    assert "5.2.4" in mild_proof.citation.clause
    assert "5.3.3" in tendon_proof.citation.clause
    source_sets = {
        calculation.axes[-1].value:
        {step.source.method_id for step in calculation.steps}
        for calculation in standard.calculations[:-1]
    }
    assert mild_proof.method_id in source_sets["mild"]
    assert tendon_proof.method_id in source_sets["prestress"]

    custom_input = copy.deepcopy(inp)
    item = custom_input["fatigue_detail_catalog"]["items"][0]
    item["preset"] = "Custom / imported"
    item["source"] = "Project tests PFT-02"
    custom_replay = copy.deepcopy(replay)
    details = list(custom_replay["fatigue_detail_basis"])
    details[0] = {
        **details[0], "preset": "Custom / imported",
        "source": "Project tests PFT-02", "edition": None, "custom": True,
    }
    custom_replay["fatigue_detail_basis"] = tuple(details)
    custom_replay["warnings"] = tuple(
        fatigue_analysis.validation_warnings(custom_input))
    custom_replay["calculation_references"]["reinforcement"] += (
        "; assigned custom/imported S-N resistance sources are listed separately")
    custom = _build(monkeypatch, custom_input, custom_replay)
    expected_source = fatigue_sources(
        custom_replay["edition"], "mild", custom_detail=True)[0]
    assert expected_source.kind == "project"
    assert expected_source.edition is None and expected_source.citation is None
    mild = next(
        calculation for calculation in custom.calculations
        if calculation.axes[-1] == TraceAxis("kind", "mild"))
    assert {
        step.source for step in mild.steps
        if step.source.method_id.endswith("fatigue-sn")
    } == {expected_source}
    assert "Project tests PFT-02" in bundle_to_json(custom)


def test_aggregate_graph_has_separate_utilisation_convergence_and_status_closure(
    retained_success, monkeypatch,
):
    inp, replay = retained_success
    aggregate = _build(monkeypatch, inp, replay).calculations[-1]
    steps = {step.step_id: step for step in aggregate.steps}
    utilisations = tuple(
        name for name in steps
        if name.startswith("assessment-") and name.endswith("-utilisation"))
    convergence = tuple(
        name for name in steps
        if name.startswith("assessment-") and name.endswith("-convergence"))
    statuses = tuple(
        name for name in steps
        if name.startswith("assessment-") and name.endswith("-status"))
    assert len(utilisations) == len(convergence) == len(statuses) == 4
    assert tuple(
        edge.step_id for edge in steps["global-convergence"].dependencies
    ) == convergence
    global_status = {
        edge.step_id for edge in steps["global-status"].dependencies}
    assert set(statuses) < global_status
    assert "global-convergence" in global_status
    final = {edge.step_id for edge in aggregate.steps[-1].dependencies}
    assert set(utilisations + convergence + statuses) < final


def test_stale_and_resealed_dependency_tampering_fail(
    retained_success, monkeypatch,
):
    inp, replay = retained_success
    bundle = _build(monkeypatch, inp, replay)
    aggregate = bundle.calculations[-1]
    steps = list(aggregate.steps)
    position = next(
        index for index, step in enumerate(steps)
        if step.step_id == "global-convergence")
    steps[position] = dataclasses.replace(
        steps[position], dependencies=steps[position].dependencies[1:])
    calculations = list(bundle.calculations)
    calculations[-1] = dataclasses.replace(aggregate, steps=tuple(steps))
    stale = dataclasses.replace(bundle, calculations=tuple(calculations))
    _pin(monkeypatch, replay)
    with pytest.raises(TraceValidationError, match="seal"):
        validate_fatigue_trace_family(
            stale, inp, {"fatigue": replay},
            input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)
    resealed = seal_bundle(dataclasses.replace(stale, content_sha256=""))
    with pytest.raises(TraceValidationError, match="dependency graph"):
        validate_fatigue_trace_family(
            resealed, inp, {"fatigue": replay},
            input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)


def test_reinforcement_output_value_and_fingerprint_tamper_fail(
    retained_success, monkeypatch,
):
    inp, replay = retained_success
    changed = copy.deepcopy(replay)
    spectrum = changed["spectra"][0]
    assessments = list(spectrum.reinforcement)
    bins = list(assessments[0].bins)
    bins[0] = dataclasses.replace(
        bins[0], stress_range_mpa=bins[0].stress_range_mpa + 1.0)
    assessments[0] = dataclasses.replace(assessments[0], bins=tuple(bins))
    _replace_spectrum(changed, 0, reinforcement=tuple(assessments))
    _pin(monkeypatch, replay)
    with pytest.raises(TraceValidationError, match="value differs"):
        build_fatigue_trace_family(
            inp, {"fatigue": changed},
            input_sha256=INPUT_HASH, result_sha256=RESULT_HASH)
    bundle = _build(monkeypatch, inp, replay)
    with pytest.raises(TraceValidationError, match="current input fingerprint"):
        validate_fatigue_trace_family(
            bundle, inp, {"fatigue": replay},
            input_sha256="c" * 64, result_sha256=RESULT_HASH)
