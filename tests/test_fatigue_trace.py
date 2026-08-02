"""Independent CT-010a replay, identity, type, and graph controls."""

from __future__ import annotations

import copy
import dataclasses
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_analysis  # noqa: E402
import fatigue_inputs  # noqa: E402
import material_catalog  # noqa: E402
from sector import codes  # noqa: E402
from sector.calculation_trace import (  # noqa: E402
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    TraceDependency,
    TraceSource,
    TraceUnit,
    TraceValidationError,
    seal_bundle,
)
from sector.fatigue_trace import (  # noqa: E402
    build_fatigue_trace_family,
    validate_fatigue_trace_family,
)
from sector.fatigue_trace_contract import (  # noqa: E402
    COVERAGE_ID,
    METHOD_ID,
    REGISTRY_ID,
)
from sector.section import Section  # noqa: E402


INPUT_SHA = "a" * 64
RESULT_SHA = "b" * 64
CONTEXT = {"case": "CT-010 fatigue"}


@pytest.fixture(autouse=True)
def _isolate_autosave(monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct010-fatigue-no-autosave")


def _spectrum(*, description="Service traffic", second=True):
    rows = [{
        "spectrum": "Traffic",
        "name": "BIN-A",
        "description": description,
        "cycles": 2.0e5,
        "n_long_ed_kn": -180.0,
        "mx_long_ed_knm": 15.0,
        "my_long_ed_knm": 0.0,
        "n_short_ed_kn": 25.0,
        "mx_short_ed_knm": 18.0,
        "my_short_ed_knm": 0.0,
    }]
    if second:
        rows.append({
            "spectrum": "Traffic",
            "name": "BIN-B",
            "description": "Frequent traffic",
            "cycles": 1.0e6,
            "n_long_ed_kn": -180.0,
            "mx_long_ed_knm": 15.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 8.0,
            "mx_short_ed_knm": 7.0,
            "my_short_ed_knm": 0.0,
        })
    return fatigue_inputs.normalise_spectrum_table(rows)


def _steel_input(*, catalog=True, concrete_check=False,
                 edition=fatigue_inputs.EC2_2005, description="Service traffic",
                 material_id="B500", concrete_id="C30"):
    material_entry = material_catalog.default_entry(
        "mild", material_id=material_id, preset=codes.EC2_2005.label)
    steel = material_catalog.build_material(material_entry, "mild")
    section = Section.from_polygon(
        corners=[(-0.20, -0.30), (0.20, -0.30),
                 (0.20, 0.30), (-0.20, 0.30)],
        bars_xy_area_mm2=[(0.0, -0.22, 314.0)],
    )
    inp = {
        "fatigue_on": True,
        "fatigue_edition": edition,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": concrete_check,
        "fatigue_concrete_method": fatigue_analysis.CONCRETE_MINER,
        "fatigue_gamma_c": 1.5,
        "fatigue_gamma_s": 1.15,
        "fatigue_gamma_ff": 1.0,
        "fatigue_beta_cc_t0": 1.0,
        "fatigue_t0_days": 28.0,
        "fatigue_concrete_k1": 0.85,
        "fatigue_concrete_c": 14.0,
        fatigue_inputs.DETAIL_CATALOG_KEY: fatigue_inputs.default_catalog(),
        fatigue_inputs.BASIS_KEY: {
            "method": fatigue_inputs.METHOD_GROUPED,
            "notes": "",
        },
        fatigue_inputs.SPECTRUM_TABLE_KEY: _spectrum(description=description),
        "section": section,
        "concrete": codes.EC2_2005.concrete(30.0),
        "concrete_preset": codes.EC2_2005.label,
        "concrete_material_id": concrete_id,
        "bar_elements": [{
            "id": "R1",
            "kind": "bar",
            "x_mm": 0.0,
            "y_mm": -220.0,
            "area_mm2": 314.0,
            "diameter_mm": 20.0,
            "material_id": material_id,
            "fatigue_detail_id": "F1",
        }],
        "tendon_elements": [],
        "bar_materials": [steel],
        "tendon_materials": [],
        "nl": 6.0,
        "ns": 6.0,
        "geometry_error": None,
        "void_error": None,
        "steel_error": None,
        "material_error": None,
    }
    if catalog:
        inp[material_catalog.MILD_CATALOG_KEY] = {
            "version": 1, "next_id": 2, "items": [material_entry]}
    return inp


def _mixed_input(*, catalog=True):
    inp = _steel_input(catalog=catalog)
    detail_catalog, detail_id = fatigue_inputs.add_entry(
        inp[fatigue_inputs.DETAIL_CATALOG_KEY],
        preset=fatigue_inputs.PRESET_2005_PRETENSION,
    )
    detail = next(item for item in detail_catalog["items"]
                  if item["id"] == detail_id)
    detail["bond_ratio_xi"] = 0.7
    detail["bond_equivalent_diameter_mm"] = 12.5
    inp[fatigue_inputs.DETAIL_CATALOG_KEY] = (
        fatigue_inputs.replace_entry(detail_catalog, detail))
    tendon_entry = material_catalog.default_entry(
        "prestress", material_id="P1860", preset=codes.EC2_2005.label)
    tendon = material_catalog.build_material(tendon_entry, "prestress")
    inp["section"] = Section.from_polygon(
        corners=[(-0.20, -0.30), (0.20, -0.30),
                 (0.20, 0.30), (-0.20, 0.30)],
        bars_xy_area_mm2=[(0.0, -0.22, 314.0)],
        tendons_xy_area_mm2=[(0.04, 0.21, 150.0)],
    )
    inp["tendon_elements"] = [{
        "id": "P1",
        "kind": "tendon",
        "x_mm": 40.0,
        "y_mm": 210.0,
        "area_mm2": 150.0,
        "diameter_mm": 13.8,
        "material_id": "P1860",
        "fatigue_detail_id": detail_id,
    }]
    inp["tendon_materials"] = [tendon]
    if catalog:
        inp[material_catalog.PRESTRESS_CATALOG_KEY] = {
            "version": 1, "next_id": 2, "items": [tendon_entry]}
    return inp


def _candidate(inp):
    errors = fatigue_analysis.validation_errors(inp)
    payload = (
        fatigue_analysis.invalid_result(inp, errors)
        if errors else fatigue_analysis.run_analysis(inp)
    )
    return {"fatigue": payload}


def _bundle(inp, out=None, *, context=CONTEXT):
    candidate = _candidate(inp) if out is None else out
    bundle = build_fatigue_trace_family(
        inp, candidate, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=context,
    )
    assert bundle is not None
    return bundle


def _element_calculation(bundle, index=0):
    calculations = [item for item in bundle.calculations
                    if item.final_step_id == "ct-010-element-result"]
    return calculations[index]


def _steps(calculation):
    return {step.step_id: step for step in calculation.steps}


def _replace_step(bundle, calculation_index, step_index, **changes):
    calculations = list(bundle.calculations)
    steps = list(calculations[calculation_index].steps)
    steps[step_index] = dataclasses.replace(steps[step_index], **changes)
    calculations[calculation_index] = dataclasses.replace(
        calculations[calculation_index], steps=tuple(steps))
    return seal_bundle(dataclasses.replace(
        bundle, calculations=tuple(calculations), content_sha256=""))


def _assert_reaches_final(calculation):
    by_id = _steps(calculation)
    reached = set()
    pending = [calculation.final_step_id]
    while pending:
        step_id = pending.pop()
        if step_id in reached:
            continue
        reached.add(step_id)
        pending.extend(item.step_id for item in by_id[step_id].dependencies)
    assert reached == set(by_id)


def test_closed_form_sn_miner_and_output_verdict_replay():
    inp = _steel_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    calculation = _element_calculation(bundle)
    steps = _steps(calculation)
    result = out["fatigue"]["spectra"][0].reinforcement[0]
    for index, bin_result in enumerate(result.bins):
        prefix = next(
            key[:-len("-damage")] for key in steps
            if key.startswith(f"bin-{index:02d}-") and key.endswith("-damage"))
        expected_damage = bin_result.cycles / (
            10.0 ** bin_result.log10_cycles_to_failure)
        assert steps[f"{prefix}-damage"].result.value == pytest.approx(
            expected_damage)
    assert steps["damage-total"].result.value == pytest.approx(
        sum(item.damage for item in result.bins))
    assert steps["ct-010-element-result"].result.value == (
        1.0 if result.passed else 0.0)
    output = _steps(bundle.calculations[-1])
    assert output["ct-010-reinforcement-output-result"].result.value == (
        1.0 if out["fatigue"]["passed"] else 0.0)


@pytest.mark.parametrize("changes", [
    {"fatigue_on": False},
    {"section": None},
    {"geometry_error": "invalid geometry"},
])
def test_inactive_branches_publish_no_family_and_reject_candidates(changes):
    inp = _steel_input()
    inp.update(changes)
    assert build_fatigue_trace_family(
        inp, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is None
    with pytest.raises(TraceValidationError):
        build_fatigue_trace_family(
            inp, {"fatigue": {}}, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)


def test_invalid_preflight_is_failed_evidence_before_candidate_numerics():
    inp = _steel_input()
    inp["bar_elements"][0]["fatigue_detail_id"] = ""
    out = _candidate(inp)
    assert out["fatigue"]["valid"] is False
    bundle = _bundle(inp, out)
    final = bundle.calculations[0].steps[-1]
    assert final.result.state == "failed"
    assert "preflight failed" in final.result.reason
    tampered = copy.deepcopy(out)
    tampered["fatigue"]["errors"] = list(tampered["fatigue"]["errors"])
    with pytest.raises(TraceValidationError):
        _bundle(inp, tampered)


@pytest.mark.parametrize("alias", [2023, "legacy 2023 alias"])
def test_finite_reader_rejects_adapter_edition_aliases(alias):
    inp = _steel_input(edition=alias)
    inp[fatigue_inputs.DETAIL_CATALOG_KEY]["items"][0] = (
        fatigue_inputs.apply_preset(
            inp[fatigue_inputs.DETAIL_CATALOG_KEY]["items"][0],
            fatigue_inputs.PRESET_2023_BARS))
    assert fatigue_analysis.validation_errors(inp) == []
    out = _candidate(inp)
    assert out["fatigue"]["edition"] == fatigue_inputs.EC2_2023
    with pytest.raises(TraceValidationError, match="exact retained edition"):
        _bundle(inp, out)


@pytest.mark.parametrize(("key", "value"), [
    ("fatigue_on", 1),
    ("fatigue_check_steel", 1),
    ("fatigue_check_concrete", 0),
    ("fatigue_gamma_s", True),
    ("fatigue_gamma_ff", float("inf")),
    ("nl", False),
])
def test_reader_rejects_boolean_and_numeric_lookalikes(key, value):
    inp = _steel_input()
    inp[key] = value
    with pytest.raises(TraceValidationError):
        build_fatigue_trace_family(
            inp, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
            context=CONTEXT)


def test_catalog_free_explicit_law_has_uncited_project_provenance():
    inp = _steel_input(catalog=False)
    assert fatigue_analysis.validation_errors(inp) == []
    bundle = _bundle(inp)
    material_steps = [
        step for step in _element_calculation(bundle).steps
        if "material-bar-" in step.step_id
    ]
    assert material_steps
    assert {step.source.kind for step in material_steps} == {
        SOURCE_PROJECT}
    assert all(step.source.citation is None for step in material_steps)


@pytest.mark.parametrize("catalog", [True, False])
def test_mixed_bar_tendon_replay_and_bond_identity(catalog):
    inp = _mixed_input(catalog=catalog)
    assert fatigue_analysis.validation_errors(inp) == []
    bundle = _bundle(inp)
    calculations = [item for item in bundle.calculations
                    if item.final_step_id == "ct-010-element-result"]
    assert len(calculations) == 2
    tendon_steps = _steps(calculations[1])
    assert "detail-bond-xi" in tendon_steps
    assert "detail-bond-eq-diameter" in tendon_steps
    assert any("material-tendon-" in key for key in tendon_steps)
    if not catalog:
        sources = {step.source.kind for step in calculations[1].steps
                   if "material-tendon-" in step.step_id}
        assert sources == {SOURCE_PROJECT}


@pytest.mark.parametrize("catalog", [[], {"items": []}, {"items": "bad"}])
def test_present_malformed_or_incomplete_material_catalog_fails_closed(catalog):
    inp = _steel_input()
    inp[material_catalog.MILD_CATALOG_KEY] = catalog
    with pytest.raises(TraceValidationError):
        _bundle(inp)


def test_material_and_concrete_identities_reseal_even_for_same_laws():
    first = _steel_input(material_id="B500", concrete_id="C30")
    second = _steel_input(material_id="B500-X", concrete_id="C30-X")
    first_bundle = _bundle(first)
    second_bundle = _bundle(second)
    assert first_bundle.content_sha256 != second_bundle.content_sha256
    assert _element_calculation(first_bundle).calculation_id != (
        _element_calculation(second_bundle).calculation_id)
    with pytest.raises(TraceValidationError):
        validate_fatigue_trace_family(
            first_bundle, second, _candidate(second), input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)


def test_published_bin_description_is_part_of_input_identity():
    first = _steel_input(description="Service traffic")
    second = _steel_input(description="Changed publication text")
    first_bundle = _bundle(first)
    second_bundle = _bundle(second)
    assert first_bundle.content_sha256 != second_bundle.content_sha256
    first_ids = set(_steps(_element_calculation(first_bundle)))
    second_ids = set(_steps(_element_calculation(second_bundle)))
    assert first_ids != second_ids


def test_complete_geometry_and_material_vectors_reach_member_final():
    bundle = _bundle(_steel_input())
    calculation = _element_calculation(bundle)
    steps = _steps(calculation)
    normalised = steps["normalised-fatigue-inputs"]
    dependencies = {item.step_id for item in normalised.dependencies}
    assert {"geometry-vector", "material-vector"} <= dependencies
    assert any(key.startswith("geometry-ring-") for key in steps)
    assert any("material-concrete-" in key for key in steps)
    assert any("material-bar-" in key for key in steps)
    _assert_reaches_final(calculation)


def test_geometry_change_reseals_the_complete_input_vector():
    first = _steel_input()
    second = _steel_input()
    second["section"] = Section.from_polygon(
        corners=[(-0.21, -0.30), (0.21, -0.30),
                 (0.21, 0.30), (-0.21, 0.30)],
        bars_xy_area_mm2=[(0.0, -0.22, 314.0)],
    )
    first_bundle = _bundle(first)
    second_bundle = _bundle(second)
    assert first_bundle.content_sha256 != second_bundle.content_sha256
    with pytest.raises(TraceValidationError):
        validate_fatigue_trace_family(
            first_bundle, second, _candidate(second), input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)


@pytest.mark.parametrize(("key", "replacement"), [
    ("concrete_method", []),
    ("concrete_parameters", []),
])
def test_excluded_concrete_sibling_types_are_fenced(key, replacement):
    inp = _steel_input()
    out = _candidate(inp)
    tampered = copy.deepcopy(out)
    tampered["fatigue"][key] = replacement
    with pytest.raises(TraceValidationError, match="retained type"):
        _bundle(inp, tampered)


def test_excluded_concrete_sibling_values_are_inert_with_same_type():
    inp = _steel_input(concrete_check=True)
    out = _candidate(inp)
    tampered = copy.deepcopy(out)
    tampered["fatigue"]["concrete_method"] = "future CT-010b method"
    tampered["fatigue"]["concrete_parameters"] = {
        "future": "future CT-010b values"}
    assert _bundle(inp, tampered) == _bundle(inp, out)


def test_excluded_concrete_dataclass_fields_keep_their_retained_types():
    inp = _steel_input()
    out = _candidate(inp)
    tampered = copy.deepcopy(out)
    spectra = list(tampered["fatigue"]["spectra"])
    spectra[0] = dataclasses.replace(spectra[0], concrete=[])
    tampered["fatigue"]["spectra"] = type(
        tampered["fatigue"]["spectra"])(spectra)
    with pytest.raises(TraceValidationError, match="wrong retained type"):
        _bundle(inp, tampered)

    tampered = copy.deepcopy(out)
    spectra = list(tampered["fatigue"]["spectra"])
    bins = list(spectra[0].bins)
    bins[0] = dataclasses.replace(
        bins[0], concrete_compression_long_mpa=[])
    spectra[0] = dataclasses.replace(
        spectra[0], bins=type(spectra[0].bins)(bins))
    tampered["fatigue"]["spectra"] = type(
        tampered["fatigue"]["spectra"])(spectra)
    with pytest.raises(TraceValidationError, match="wrong retained type"):
        _bundle(inp, tampered)


@pytest.mark.parametrize("field", [
    "elements", "spectra", "governing_spectrum", "utilisation",
    "converged", "passed",
])
def test_owned_candidate_fields_reject_tampering(field):
    inp = _steel_input()
    out = _candidate(inp)
    tampered = copy.deepcopy(out)
    value = tampered["fatigue"][field]
    if type(value) is bool:
        tampered["fatigue"][field] = not value
    elif type(value) is float:
        tampered["fatigue"][field] = value + 0.01
    elif type(value) is str:
        tampered["fatigue"][field] = value + "-changed"
    else:
        tampered["fatigue"][field] = []
    with pytest.raises(TraceValidationError):
        _bundle(inp, tampered)


def test_candidate_inventory_order_unknown_and_valid_key_fail_closed():
    inp = _steel_input()
    out = _candidate(inp)
    reordered = copy.deepcopy(out)
    payload = reordered["fatigue"]
    reordered["fatigue"] = {key: payload[key] for key in reversed(payload)}
    with pytest.raises(TraceValidationError, match="keys/order"):
        _bundle(inp, reordered)
    extra = copy.deepcopy(out)
    extra["fatigue"]["valid"] = True
    with pytest.raises(TraceValidationError):
        _bundle(inp, extra)


def test_2023_fatigue_detail_does_not_launder_2023_material_provenance():
    inp = _steel_input(edition=fatigue_inputs.EC2_2023)
    inp[fatigue_inputs.DETAIL_CATALOG_KEY]["items"][0] = (
        fatigue_inputs.apply_preset(
            inp[fatigue_inputs.DETAIL_CATALOG_KEY]["items"][0],
            fatigue_inputs.PRESET_2023_BARS))
    # A 2023 fatigue edition with the accepted 2005 material law is valid.
    assert _bundle(inp)

    entry = material_catalog.default_entry(
        "mild", material_id="B500", preset=codes.EC2_2023.label)
    inp["bar_materials"] = [material_catalog.build_material(entry, "mild")]
    inp[material_catalog.MILD_CATALOG_KEY] = {
        "version": 1, "next_id": 2, "items": [entry]}
    with pytest.raises(TraceValidationError, match="not implemented"):
        _bundle(inp)


def test_joint_output_omits_unowned_concrete_family_utilisation():
    inp = _steel_input(concrete_check=True)
    assert fatigue_analysis.validation_errors(inp) == []
    bundle = _bundle(inp)
    steps = _steps(bundle.calculations[-1])
    assert "family-utilisation" not in steps
    assert "governing-spectrum" not in steps
    assert steps["input-check-concrete"].result.value == 1.0


def test_concrete_only_valid_state_has_no_ct010a_family():
    inp = _steel_input()
    inp["fatigue_check_steel"] = False
    inp["fatigue_check_concrete"] = True
    out = _candidate(inp)
    assert build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is None


def test_registry_identity_and_every_calculation_graph_are_exact():
    bundle = _bundle(_steel_input())
    assert {calculation.coverage_id for calculation in bundle.calculations} == {
        COVERAGE_ID}
    assert {calculation.method_id for calculation in bundle.calculations} == {
        METHOD_ID}
    assert REGISTRY_ID == "sector-ct-010-fatigue-v1"
    for calculation in bundle.calculations:
        _assert_reaches_final(calculation)


def test_stale_hashes_and_context_identity_fail_validation():
    inp = _steel_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    with pytest.raises(TraceValidationError):
        validate_fatigue_trace_family(
            bundle, inp, out, input_sha256="c" * 64,
            result_sha256=RESULT_SHA, context=CONTEXT)
    with pytest.raises(TraceValidationError):
        validate_fatigue_trace_family(
            bundle, inp, out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context={"case": "other"})


@pytest.mark.parametrize("tamper", ["value", "source", "unit", "axis"])
def test_resealed_value_source_unit_and_axis_tampering_fails(tamper):
    inp = _steel_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    calculation = bundle.calculations[0]
    step_index = len(calculation.steps) - 1
    step = calculation.steps[step_index]
    if tamper == "value":
        changed = dataclasses.replace(
            step.result, value=step.result.value + 0.125)
        bad = _replace_step(bundle, 0, step_index, result=changed)
    elif tamper == "source":
        bad = _replace_step(
            bundle, 0, step_index,
            source=TraceSource(SOURCE_PROJECT, "tampered-source"))
    elif tamper == "unit":
        bad = _replace_step(
            bundle, 0, step_index, unit=TraceUnit("x", "scalar"))
    else:
        calculations = list(bundle.calculations)
        axes = list(calculations[0].axes)
        axes[0] = dataclasses.replace(axes[0], value=axes[0].value + "-x")
        calculations[0] = dataclasses.replace(
            calculations[0], axes=tuple(axes))
        bad = seal_bundle(dataclasses.replace(
            bundle, calculations=tuple(calculations), content_sha256=""))
    with pytest.raises(TraceValidationError):
        validate_fatigue_trace_family(
            bad, inp, out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)


def test_resealed_dependency_removal_and_redirection_fail():
    inp = _steel_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    calculation = bundle.calculations[0]
    step_index = next(
        index for index, step in enumerate(calculation.steps)
        if step.step_id.endswith("-stress-range")
        and not step.step_id.endswith("-design-stress-range"))
    step = calculation.steps[step_index]
    removed = _replace_step(
        bundle, 0, step_index, dependencies=step.dependencies[1:])
    redirected_dependencies = list(step.dependencies)
    redirected_dependencies[0] = TraceDependency(
        "input-check-steel",
        _steps(calculation)["input-check-steel"].unit,
    )
    redirected = _replace_step(
        bundle, 0, step_index, dependencies=tuple(redirected_dependencies))
    for bad in (removed, redirected):
        with pytest.raises(TraceValidationError):
            validate_fatigue_trace_family(
                bad, inp, out, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT)


def test_resealed_calculation_and_step_order_tampering_fails():
    inp = _steel_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    calculations = list(bundle.calculations)
    calculations.reverse()
    reordered_calculations = seal_bundle(dataclasses.replace(
        bundle, calculations=tuple(calculations), content_sha256=""))
    steps = list(bundle.calculations[0].steps)
    steps[0], steps[1] = steps[1], steps[0]
    bad_calculation = dataclasses.replace(
        bundle.calculations[0], steps=tuple(steps))
    reordered_steps = seal_bundle(dataclasses.replace(
        bundle,
        calculations=(bad_calculation, *bundle.calculations[1:]),
        content_sha256="",
    ))
    for bad in (reordered_calculations, reordered_steps):
        with pytest.raises(TraceValidationError):
            validate_fatigue_trace_family(
                bad, inp, out, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT)


def test_standard_and_project_sources_are_not_interchangeable():
    catalog_bundle = _bundle(_steel_input(catalog=True))
    project_bundle = _bundle(_steel_input(catalog=False))
    catalog_sources = {
        step.source.kind for step in _element_calculation(
            catalog_bundle).steps if "material-bar-" in step.step_id}
    project_sources = {
        step.source.kind for step in _element_calculation(
            project_bundle).steps if "material-bar-" in step.step_id}
    assert catalog_sources == {SOURCE_STANDARD}
    assert project_sources == {SOURCE_PROJECT}
