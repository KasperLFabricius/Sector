"""Independent contract/adversarial tests for successful CT-010a evidence."""

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
from sector.fatigue_trace_contract import SUCCESS_KEYS, code_sources


INPUT_SHA = "1" * 64
RESULT_SHA = "2" * 64


@pytest.fixture(scope="module")
def authoritative():
    inp = _base()
    candidate = fatigue_analysis.run_analysis(inp)
    return inp, candidate


def _facade(candidate):
    return SimpleNamespace(
        run_analysis=lambda _inp: candidate,
        prepare=fatigue_analysis.prepare,
        analysis_signature=fatigue_analysis.analysis_signature,
    )


def _install(monkeypatch, candidate):
    monkeypatch.setattr(fatigue_trace, "_analysis", lambda: _facade(candidate))


def _bundle(monkeypatch, inp, candidate):
    _install(monkeypatch, candidate)
    return build_fatigue_trace_family(
        inp, {"fatigue": candidate},
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
    )


def _replace_spectrum(candidate, position, **changes):
    spectra = list(candidate["spectra"])
    spectra[position] = dataclasses.replace(spectra[position], **changes)
    candidate["spectra"] = tuple(spectra)


def _replace_assessment(candidate, spectrum_position, element_position, **changes):
    spectrum = candidate["spectra"][spectrum_position]
    assessments = list(spectrum.reinforcement)
    assessments[element_position] = dataclasses.replace(
        assessments[element_position], **changes)
    _replace_spectrum(candidate, spectrum_position,
                      reinforcement=tuple(assessments))


def test_success_inventory_round_trip_and_exact_registry(
    authoritative, monkeypatch,
):
    inp, candidate = authoritative
    bundle = _bundle(monkeypatch, inp, candidate)

    assert tuple(candidate) == SUCCESS_KEYS
    assert len(bundle.calculations) == 5
    assert [axis.value for axis in bundle.calculations[-1].axes] == [
        "reinforcement-fatigue", "aggregate",
    ]
    restored = bundle_from_json(bundle_to_json(bundle))
    assert restored == bundle
    assert validate_fatigue_trace_family(
        restored, inp, {"fatigue": candidate},
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
    ) == bundle


@pytest.mark.parametrize(
    "key,bad",
    [
        ("fatigue_on", 1),
        ("fatigue_on", np.bool_(True)),
        ("fatigue_check_steel", "true"),
        ("fatigue_check_concrete", None),
    ],
)
def test_raw_dispatch_controls_are_required_exact_booleans(
    authoritative, monkeypatch, key, bad,
):
    inp, candidate = authoritative
    changed = dict(inp)
    changed[key] = bad
    _install(monkeypatch, candidate)
    with pytest.raises(TraceValidationError, match="exact built-in Boolean"):
        build_fatigue_trace_family(
            changed, {"fatigue": candidate},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )


def test_missing_raw_dispatch_control_fails_before_candidate_dispatch(
    authoritative, monkeypatch,
):
    inp, candidate = authoritative
    changed = dict(inp)
    changed.pop("fatigue_check_concrete")
    _install(monkeypatch, candidate)
    with pytest.raises(TraceValidationError, match="required exact"):
        build_fatigue_trace_family(
            changed, {"fatigue": None},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )


def test_invalid_branch_is_selected_before_malformed_section_traversal(
    authoritative, monkeypatch,
):
    inp, _candidate = authoritative
    changed = dict(inp)
    changed["section"] = {}
    invalid = {"valid": False, "errors": ["retained invalid"]}
    _install(monkeypatch, None)

    assert build_fatigue_trace_family(
        changed, {"fatigue": invalid},
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
    ) is None
    with pytest.raises(TraceValidationError, match="inapplicable"):
        validate_fatigue_trace_family(
            {"unrelated": "bundle"}, changed, {"fatigue": invalid},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )


def test_disabled_and_missing_candidates_are_inapplicable(
    authoritative, monkeypatch,
):
    inp, candidate = authoritative
    _install(monkeypatch, candidate)
    missing = {"fatigue": None}
    assert build_fatigue_trace_family(
        inp, missing, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
    ) is None
    disabled = dict(inp)
    disabled["fatigue_on"] = False
    assert build_fatigue_trace_family(
        disabled, missing, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
    ) is None
    with pytest.raises(TraceValidationError, match="disabled"):
        build_fatigue_trace_family(
            disabled, {"fatigue": candidate},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )


def test_concrete_only_success_is_fully_fenced_then_inapplicable(
    authoritative, monkeypatch,
):
    inp, candidate = authoritative
    changed = copy.deepcopy(inp)
    changed["fatigue_check_steel"] = False
    concrete_only = copy.deepcopy(candidate)
    concrete_only["checks"]["reinforcement"] = False
    concrete_only["calculation_references"].pop("reinforcement")
    concrete_only["partial_factors"]["gamma_s"] = None
    concrete_only["reinforcement_properties"] = ()
    for position, spectrum in enumerate(concrete_only["spectra"]):
        _replace_spectrum(
            concrete_only, position, reinforcement=(),
            governing_reinforcement_id=None,
        )
    _install(monkeypatch, concrete_only)

    assert build_fatigue_trace_family(
        changed, {"fatigue": concrete_only},
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
    ) is None
    truncated = dict(concrete_only)
    truncated.pop("warnings")
    with pytest.raises(TraceValidationError, match="inventory"):
        build_fatigue_trace_family(
            changed, {"fatigue": truncated},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )


def test_reinforcement_only_shared_aggregates_are_not_excluded(
    authoritative, monkeypatch,
):
    inp, candidate = authoritative
    changed = copy.deepcopy(inp)
    changed["fatigue_check_concrete"] = False
    steel_only = copy.deepcopy(candidate)
    steel_only["checks"]["concrete"] = False
    steel_only["concrete_method"] = None
    steel_only["calculation_references"].pop("concrete")
    steel_only["partial_factors"]["gamma_c"] = None
    steel_only["concrete_parameters"] = None
    steel_only["t0_days"] = None
    for position, spectrum in enumerate(steel_only["spectra"]):
        governing = max(
            spectrum.reinforcement, key=lambda item: item.utilisation)
        _replace_spectrum(
            steel_only, position,
            concrete=(), concrete_search=None, fcd_fat_mpa=None,
            governing_concrete_fibre=None, concrete_method=None,
            utilisation=governing.utilisation,
            converged=all(item.converged for item in spectrum.reinforcement),
            passed=all(item.passed for item in spectrum.reinforcement),
        )
    governing_spectrum = max(
        steel_only["spectra"], key=lambda item: item.utilisation)
    steel_only["governing_spectrum"] = governing_spectrum.spectrum_name
    steel_only["utilisation"] = governing_spectrum.utilisation
    steel_only["converged"] = all(
        item.converged for item in steel_only["spectra"])
    steel_only["passed"] = all(item.passed for item in steel_only["spectra"])
    _install(monkeypatch, steel_only)

    assert build_fatigue_trace_family(
        changed, {"fatigue": steel_only},
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
    ) is not None
    tampered = copy.deepcopy(steel_only)
    tampered["utilisation"] += 0.1
    with pytest.raises(TraceValidationError, match="value differs"):
        build_fatigue_trace_family(
            changed, {"fatigue": tampered},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("warnings"),
        lambda value: value.__setitem__("unknown", 1),
        lambda value: value.__setitem__(
            "concrete_method", [value["concrete_method"]]),
        lambda value: value.__setitem__(
            "concrete_parameters", [value["concrete_parameters"]]),
    ],
)
def test_inventory_and_concrete_sibling_types_fail_closed(
    authoritative, monkeypatch, mutation,
):
    inp, candidate = authoritative
    changed = copy.deepcopy(candidate)
    mutation(changed)
    _install(monkeypatch, candidate)
    with pytest.raises(TraceValidationError):
        build_fatigue_trace_family(
            inp, {"fatigue": changed},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )


def test_outer_and_nested_mapping_subclasses_fail_closed(
    authoritative, monkeypatch,
):
    class MappingSubclass(dict):
        pass

    inp, candidate = authoritative
    _install(monkeypatch, candidate)
    with pytest.raises(TraceValidationError, match="built-in dict"):
        build_fatigue_trace_family(
            inp, {"fatigue": MappingSubclass(candidate)},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )
    changed = copy.deepcopy(candidate)
    changed["partial_factors"] = MappingSubclass(changed["partial_factors"])
    with pytest.raises(TraceValidationError, match="inventory"):
        build_fatigue_trace_family(
            inp, {"fatigue": changed},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )


def test_concrete_values_are_inert_while_shape_and_type_remain_pinned(
    authoritative, monkeypatch,
):
    inp, candidate = authoritative
    changed = copy.deepcopy(candidate)
    changed["concrete_method"] = "Excluded concrete method value"
    changed["concrete_parameters"]["fck_mpa"] += 123.0
    _install(monkeypatch, candidate)

    assert build_fatigue_trace_family(
        inp, {"fatigue": changed},
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
    ) is not None


def test_bin_description_concrete_id_and_geometry_type_change_trace_identity(
    authoritative, monkeypatch,
):
    inp, candidate = authoritative
    baseline = _bundle(monkeypatch, inp, candidate)

    described_input = copy.deepcopy(inp)
    described_input["fatigue_spectrum_base"].loc[0, "description"] = "Changed"
    described_candidate = copy.deepcopy(candidate)
    first = described_candidate["spectra"][0]
    states = list(first.bins)
    states[0] = dataclasses.replace(states[0], description="Changed")
    _replace_spectrum(described_candidate, 0, bins=tuple(states))
    described = _bundle(monkeypatch, described_input, described_candidate)

    concrete_input = copy.deepcopy(inp)
    concrete_input["concrete_material_id"] = "C-same-law-different-id"
    concrete_input["concrete_preset"] = "Same law, different catalogue row"
    concrete = _bundle(monkeypatch, concrete_input, candidate)

    geometry_input = copy.deepcopy(inp)
    geometry_input["section"].concrete[0] = (
        geometry_input["section"].concrete[0].astype(np.float32))
    geometry = _bundle(monkeypatch, geometry_input, candidate)

    assert len({
        baseline.content_sha256, described.content_sha256,
        concrete.content_sha256, geometry.content_sha256,
    }) == 4
    for bundle in (baseline, described, concrete, geometry):
        for calculation in bundle.calculations:
            final = next(
                step for step in calculation.steps
                if step.step_id == calculation.final_step_id)
            assert "input-normalised" in {
                dependency.step_id for dependency in final.dependencies}


def test_matched_state_is_the_source_of_each_reinforcement_stress(
    authoritative, monkeypatch,
):
    inp, candidate = authoritative
    changed = copy.deepcopy(candidate)
    spectrum = changed["spectra"][0]
    states = list(spectrum.bins)
    design = list(states[0].bar_stress_fatigue_design_total_mpa)
    design[0] += 5.0
    states[0] = dataclasses.replace(
        states[0], bar_stress_fatigue_design_total_mpa=tuple(design))
    _replace_spectrum(changed, 0, bins=tuple(states))
    # Make the altered state the retained replay so output inventory comparison
    # passes; the unchanged assessment must still fail independent reconstruction.
    _install(monkeypatch, changed)
    with pytest.raises(TraceValidationError, match="design total stress"):
        build_fatigue_trace_family(
            inp, {"fatigue": changed},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )


def test_kind_correct_proof_sources_and_distinct_member_axes(
    authoritative, monkeypatch,
):
    inp, candidate = authoritative
    bundle = _bundle(monkeypatch, inp, candidate)
    mild_sn, mild_proof = code_sources(candidate["edition"], "mild")
    tendon_sn, tendon_proof = code_sources(candidate["edition"], "prestress")

    assert mild_sn == tendon_sn
    assert mild_proof.method_id == "en-1992-reinforcement-fatigue-yield"
    assert "5.2.4" in mild_proof.citation.clause
    assert tendon_proof.method_id == "en-1992-prestress-fatigue-yield"
    assert "5.3.3" in tendon_proof.citation.clause
    kinds = {
        next(axis.value for axis in calculation.axes if axis.name == "kind"):
        {step.source.method_id for step in calculation.steps}
        for calculation in bundle.calculations[:-1]
    }
    assert mild_proof.method_id in kinds["mild"]
    assert tendon_proof.method_id in kinds["prestress"]


def test_custom_imported_sn_source_is_project_defined_and_uncited(
    authoritative, monkeypatch,
):
    inp, candidate = authoritative
    changed_input = copy.deepcopy(inp)
    detail = changed_input["fatigue_detail_catalog"]["items"][0]
    detail["preset"] = "Custom / imported"
    detail["source"] = "Project fatigue test series PFT-01"
    changed_candidate = copy.deepcopy(candidate)
    details = list(changed_candidate["fatigue_detail_basis"])
    details[0] = {
        **details[0],
        "preset": "Custom / imported",
        "source": "Project fatigue test series PFT-01",
        "edition": None,
        "custom": True,
    }
    changed_candidate["fatigue_detail_basis"] = tuple(details)
    changed_candidate["warnings"] = tuple(
        fatigue_analysis.validation_warnings(changed_input))
    changed_candidate["calculation_references"]["reinforcement"] += (
        "; assigned custom/imported S-N resistance sources are listed separately"
    )
    bundle = _bundle(monkeypatch, changed_input, changed_candidate)

    custom = code_sources(
        changed_candidate["edition"], "mild", custom_detail=True)[0]
    assert custom.kind == "project"
    assert custom.edition is None
    assert custom.citation is None
    mild = next(
        calculation for calculation in bundle.calculations[:-1]
        if calculation.axes[-1] == TraceAxis("kind", "mild"))
    sn_sources = {
        step.source for step in mild.steps
        if step.source.method_id.endswith("fatigue-sn")
    }
    assert sn_sources == {custom}
    assert "Project fatigue test series PFT-01" in bundle_to_json(bundle)


def test_aggregate_binds_every_assessment_utilisation_convergence_and_status(
    authoritative, monkeypatch,
):
    inp, candidate = authoritative
    aggregate = _bundle(monkeypatch, inp, candidate).calculations[-1]
    steps = {step.step_id: step for step in aggregate.steps}
    convergence_ids = tuple(
        step_id for step_id in steps
        if step_id.startswith("assessment-") and step_id.endswith("-converged"))
    status_ids = tuple(
        step_id for step_id in steps
        if step_id.startswith("assessment-") and step_id.endswith("-status"))
    utilisation_ids = tuple(
        step_id for step_id in steps
        if step_id.startswith("assessment-") and step_id.endswith("-utilisation"))

    assert len(convergence_ids) == len(status_ids) == len(utilisation_ids) == 4
    assert tuple(
        dependency.step_id for dependency in steps["global-converged"].dependencies
    ) == convergence_ids
    global_status_dependencies = {
        item.step_id for item in steps["global-status"].dependencies}
    assert set(status_ids) < global_status_dependencies
    assert "global-converged" in global_status_dependencies
    final_dependencies = {
        item.step_id for item in steps[aggregate.final_step_id].dependencies}
    assert set(convergence_ids + status_ids + utilisation_ids) < final_dependencies


def test_stale_and_coherently_resealed_graph_tampering_are_rejected(
    authoritative, monkeypatch,
):
    inp, candidate = authoritative
    bundle = _bundle(monkeypatch, inp, candidate)
    aggregate = bundle.calculations[-1]
    steps = list(aggregate.steps)
    position = next(
        index for index, step in enumerate(steps)
        if step.step_id == "global-converged")
    steps[position] = dataclasses.replace(
        steps[position], dependencies=steps[position].dependencies[1:])
    calculations = list(bundle.calculations)
    calculations[-1] = dataclasses.replace(aggregate, steps=tuple(steps))
    stale = dataclasses.replace(bundle, calculations=tuple(calculations))
    _install(monkeypatch, candidate)

    with pytest.raises(TraceValidationError, match="seal"):
        validate_fatigue_trace_family(
            stale, inp, {"fatigue": candidate},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )
    resealed = seal_bundle(dataclasses.replace(stale, content_sha256=""))
    with pytest.raises(TraceValidationError, match="dependency graph"):
        validate_fatigue_trace_family(
            resealed, inp, {"fatigue": candidate},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )


def test_candidate_order_and_reinforcement_values_are_exact(
    authoritative, monkeypatch,
):
    inp, candidate = authoritative
    reordered = {key: candidate[key] for key in reversed(candidate)}
    _install(monkeypatch, candidate)
    with pytest.raises(TraceValidationError, match="inventory/order"):
        build_fatigue_trace_family(
            inp, {"fatigue": reordered},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )

    changed = copy.deepcopy(candidate)
    assessment = changed["spectra"][0].reinforcement[0]
    first_bin = dataclasses.replace(
        assessment.bins[0], stress_range_mpa=assessment.bins[0].stress_range_mpa + 1.0)
    _replace_assessment(
        changed, 0, 0, bins=(first_bin, *assessment.bins[1:]))
    with pytest.raises(TraceValidationError, match="value differs"):
        build_fatigue_trace_family(
            inp, {"fatigue": changed},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        )


def test_bundle_hashes_and_axes_are_fresh_and_exact(
    authoritative, monkeypatch,
):
    inp, candidate = authoritative
    bundle = _bundle(monkeypatch, inp, candidate)
    assert bundle.input_sha256 == INPUT_SHA
    assert bundle.result_sha256 == RESULT_SHA
    with pytest.raises(TraceValidationError, match="current input fingerprint"):
        validate_fatigue_trace_family(
            bundle, inp, {"fatigue": candidate},
            input_sha256="3" * 64, result_sha256=RESULT_SHA,
        )
    assessment_axes = bundle.calculations[0].axes
    assert assessment_axes == (
        TraceAxis("family", "reinforcement-fatigue"),
        TraceAxis("spectrum", "Traffic A"),
        TraceAxis("member", "R1"),
        TraceAxis("kind", "mild"),
    )
