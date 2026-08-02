"""CT-010a numerical replay, identity, type, and graph controls."""

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
def _no_autosave(monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct010-no-autosave")


def _table(description="Published service bin"):
    return fatigue_inputs.normalise_spectrum_table([
        {
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
        },
        {
            "spectrum": "Traffic",
            "name": "BIN-B",
            "description": "Published frequent bin",
            "cycles": 1.0e6,
            "n_long_ed_kn": -180.0,
            "mx_long_ed_knm": 15.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 8.0,
            "mx_short_ed_knm": 7.0,
            "my_short_ed_knm": 0.0,
        },
    ])


def _input(*, concrete=True, catalog=True,
           edition=fatigue_inputs.EC2_2005,
           material_id="B500", concrete_id="C30",
           description="Published service bin"):
    entry = material_catalog.default_entry(
        "mild", material_id=material_id, preset=codes.EC2_2005.label)
    section = Section.from_polygon(
        corners=[(-0.20, -0.30), (0.20, -0.30),
                 (0.20, 0.30), (-0.20, 0.30)],
        bars_xy_area_mm2=[(0.0, -0.22, 314.0)],
    )
    inp = {
        "fatigue_on": True,
        "fatigue_edition": edition,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": False,
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
        fatigue_inputs.SPECTRUM_TABLE_KEY: _table(description),
        "section": section,
        "bar_elements": [{
            "id": "R1", "kind": "bar", "x_mm": 0.0, "y_mm": -220.0,
            "area_mm2": 314.0, "diameter_mm": 20.0,
            "material_id": material_id, "fatigue_detail_id": "F1",
        }],
        "tendon_elements": [],
        "bar_materials": [material_catalog.build_material(entry, "mild")],
        "tendon_materials": [],
        "nl": 6.0,
        "ns": 6.0,
        "geometry_error": None,
        "void_error": None,
        "steel_error": None,
        "material_error": None,
    }
    if concrete:
        inp.update({
            "concrete": codes.EC2_2005.concrete(30.0),
            "concrete_preset": codes.EC2_2005.label,
            "concrete_material_id": concrete_id,
        })
    if catalog:
        inp[material_catalog.MILD_CATALOG_KEY] = {
            "version": 1, "next_id": 2, "items": [entry]}
    return inp


def _mixed(*, catalog=True):
    inp = _input(catalog=catalog)
    details, detail_id = fatigue_inputs.add_entry(
        inp[fatigue_inputs.DETAIL_CATALOG_KEY],
        preset=fatigue_inputs.PRESET_2005_PRETENSION)
    detail = next(item for item in details["items"]
                  if item["id"] == detail_id)
    detail.update({
        "bond_ratio_xi": 0.7,
        "bond_equivalent_diameter_mm": 12.5,
    })
    inp[fatigue_inputs.DETAIL_CATALOG_KEY] = (
        fatigue_inputs.replace_entry(details, detail))
    tendon_entry = material_catalog.default_entry(
        "prestress", material_id="P1860", preset=codes.EC2_2005.label)
    inp["section"] = Section.from_polygon(
        corners=[(-0.20, -0.30), (0.20, -0.30),
                 (0.20, 0.30), (-0.20, 0.30)],
        bars_xy_area_mm2=[(0.0, -0.22, 314.0)],
        tendons_xy_area_mm2=[(0.04, 0.21, 150.0)],
    )
    inp["tendon_elements"] = [{
        "id": "P1", "kind": "tendon", "x_mm": 40.0, "y_mm": 210.0,
        "area_mm2": 150.0, "diameter_mm": 13.8,
        "material_id": "P1860", "fatigue_detail_id": detail_id,
    }]
    inp["tendon_materials"] = [
        material_catalog.build_material(tendon_entry, "prestress")]
    if catalog:
        inp[material_catalog.PRESTRESS_CATALOG_KEY] = {
            "version": 1, "next_id": 2, "items": [tendon_entry]}
    return inp


def _out(inp):
    errors = fatigue_analysis.validation_errors(inp)
    payload = (fatigue_analysis.invalid_result(inp, errors)
               if errors else fatigue_analysis.run_analysis(inp))
    return {"fatigue": payload}


def _bundle(inp, out=None, context=CONTEXT):
    candidate = _out(inp) if out is None else out
    bundle = build_fatigue_trace_family(
        inp, candidate, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=context)
    assert bundle is not None
    return bundle


def _elements(bundle):
    return [item for item in bundle.calculations
            if item.final_step_id == "ct-010-element-result"]


def _steps(calculation):
    return {item.step_id: item for item in calculation.steps}


def _reaches_every_step(calculation):
    steps = _steps(calculation)
    reached = set()
    pending = [calculation.final_step_id]
    while pending:
        step_id = pending.pop()
        if step_id in reached:
            continue
        reached.add(step_id)
        pending.extend(dep.step_id for dep in steps[step_id].dependencies)
    assert reached == set(steps)


def _reseal_step(bundle, calculation_index, step_index, **changes):
    calculations = list(bundle.calculations)
    steps = list(calculations[calculation_index].steps)
    steps[step_index] = dataclasses.replace(steps[step_index], **changes)
    calculations[calculation_index] = dataclasses.replace(
        calculations[calculation_index], steps=tuple(steps))
    return seal_bundle(dataclasses.replace(
        bundle, calculations=tuple(calculations), content_sha256=""))


def test_reinforcement_only_without_concrete_is_valid_and_explicit():
    headless = _input(concrete=False)
    assert fatigue_analysis.validation_errors(headless) == []
    headless_bundle = _bundle(headless)
    steps = _steps(_elements(headless_bundle)[0])
    assert steps["input-concrete-material-present"].result.value == 0.0
    assert not any("material-concrete-" in key for key in steps)
    assert "input-concrete-material-present" in {
        dep.step_id for dep in steps["material-vector"].dependencies}

    supplied = _input(concrete=True)
    supplied_bundle = _bundle(supplied)
    supplied_steps = _steps(_elements(supplied_bundle)[0])
    assert supplied_steps["input-concrete-material-present"].result.value == 1.0
    assert any("material-concrete-" in key for key in supplied_steps)
    assert supplied_bundle.content_sha256 != headless_bundle.content_sha256


def test_concrete_check_without_concrete_remains_retained_invalid_evidence():
    inp = _input(concrete=False)
    inp["fatigue_check_concrete"] = True
    out = _out(inp)
    assert out["fatigue"]["valid"] is False
    bundle = _bundle(inp, out)
    assert bundle.calculations[0].steps[-1].result.state == "failed"


def test_sn_miner_and_verdict_match_independent_closed_forms():
    inp = _input()
    out = _out(inp)
    bundle = _bundle(inp, out)
    steps = _steps(_elements(bundle)[0])
    result = out["fatigue"]["spectra"][0].reinforcement[0]
    for index, item in enumerate(result.bins):
        damage_id = next(
            key for key in steps
            if key.startswith(f"bin-{index:02d}-") and key.endswith("-damage"))
        assert steps[damage_id].result.value == pytest.approx(
            item.cycles / 10.0 ** item.log10_cycles_to_failure)
    assert steps["damage-total"].result.value == pytest.approx(
        sum(item.damage for item in result.bins))
    assert steps["ct-010-element-result"].result.value == (
        1.0 if result.passed else 0.0)


def test_authoritative_payload_contradiction_cannot_be_sealed(monkeypatch):
    inp = _input()
    out = _out(inp)
    contradictory = copy.deepcopy(out["fatigue"])
    spectra = list(contradictory["spectra"])
    reinforcement = list(spectra[0].reinforcement)
    reinforcement[0] = dataclasses.replace(
        reinforcement[0], passed=not reinforcement[0].passed)
    spectra[0] = dataclasses.replace(
        spectra[0], reinforcement=tuple(reinforcement))
    contradictory["spectra"] = type(contradictory["spectra"])(spectra)
    monkeypatch.setattr(
        fatigue_analysis, "run_analysis", lambda _inp: contradictory)
    with pytest.raises(TraceValidationError, match="declared operands"):
        _bundle(inp, {"fatigue": contradictory})


@pytest.mark.parametrize("change", [
    {"fatigue_on": False},
    {"section": None},
    {"material_error": "bad assignment"},
])
def test_inactive_states_require_total_candidate_absence(change):
    inp = _input()
    inp.update(change)
    assert build_fatigue_trace_family(
        inp, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is None
    with pytest.raises(TraceValidationError):
        build_fatigue_trace_family(
            inp, {"fatigue": {}}, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)


def test_invalid_inventory_and_error_text_are_exact():
    inp = _input()
    inp["bar_elements"][0]["fatigue_detail_id"] = ""
    out = _out(inp)
    assert out["fatigue"]["valid"] is False
    assert _bundle(inp, out).calculations[0].steps[-1].result.state == "failed"
    tampered = copy.deepcopy(out)
    tampered["fatigue"]["errors"] = list(tampered["fatigue"]["errors"])
    with pytest.raises(TraceValidationError):
        _bundle(inp, tampered)


@pytest.mark.parametrize("alias", [2023, "legacy 2023 edition"])
def test_application_edition_aliases_cannot_receive_trace_citations(alias):
    inp = _input(edition=alias)
    inp[fatigue_inputs.DETAIL_CATALOG_KEY]["items"][0] = (
        fatigue_inputs.apply_preset(
            inp[fatigue_inputs.DETAIL_CATALOG_KEY]["items"][0],
            fatigue_inputs.PRESET_2023_BARS))
    assert fatigue_analysis.validation_errors(inp) == []
    assert _out(inp)["fatigue"]["edition"] == fatigue_inputs.EC2_2023
    with pytest.raises(TraceValidationError, match="exact retained edition"):
        _bundle(inp)


@pytest.mark.parametrize(("key", "lookalike"), [
    ("fatigue_on", 1),
    ("fatigue_check_steel", 1),
    ("fatigue_check_concrete", 0),
    ("fatigue_gamma_s", True),
    ("fatigue_gamma_ff", float("inf")),
    ("nl", False),
])
def test_reader_does_not_launder_flags_or_finite_numbers(key, lookalike):
    inp = _input()
    inp[key] = lookalike
    with pytest.raises(TraceValidationError):
        build_fatigue_trace_family(
            inp, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
            context=CONTEXT)


@pytest.mark.parametrize("catalog", [True, False])
def test_mixed_bar_tendon_vectors_and_bond_inputs_are_complete(catalog):
    inp = _mixed(catalog=catalog)
    assert fatigue_analysis.validation_errors(inp) == []
    bundle = _bundle(inp)
    assert len(_elements(bundle)) == 2
    tendon = _steps(_elements(bundle)[1])
    assert {"detail-bond-xi", "detail-bond-eq-diameter"} <= set(tendon)
    assert any("geometry-tendon-" in key for key in tendon)
    assert any("material-tendon-" in key for key in tendon)
    if not catalog:
        sources = {step.source.kind for step in tendon.values()
                   if "material-tendon-" in step.step_id}
        assert sources == {SOURCE_PROJECT}


def test_catalog_free_laws_are_uncited_project_values():
    bundle = _bundle(_input(catalog=False))
    material = [step for step in _elements(bundle)[0].steps
                if "material-bar-" in step.step_id]
    assert material
    assert {step.source.kind for step in material} == {SOURCE_PROJECT}
    assert all(step.source.citation is None for step in material)


@pytest.mark.parametrize("bad", [[], {"items": []}, {"items": "bad"}])
def test_present_malformed_catalog_is_not_treated_as_catalog_free(bad):
    inp = _input()
    inp[material_catalog.MILD_CATALOG_KEY] = bad
    with pytest.raises(TraceValidationError):
        _bundle(inp)


def test_same_law_material_and_concrete_ids_reseal():
    first = _input(material_id="B500", concrete_id="C30")
    second = _input(material_id="B500-X", concrete_id="C30-X")
    first_bundle = _bundle(first)
    second_bundle = _bundle(second)
    assert first_bundle.content_sha256 != second_bundle.content_sha256
    assert _elements(first_bundle)[0].calculation_id != (
        _elements(second_bundle)[0].calculation_id)
    with pytest.raises(TraceValidationError):
        validate_fatigue_trace_family(
            first_bundle, second, _out(second), input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)


def test_bin_description_and_geometry_changes_reseal():
    first = _input(description="Published service bin")
    renamed = _input(description="Changed published description")
    widened = _input()
    widened["section"] = Section.from_polygon(
        corners=[(-0.21, -0.30), (0.21, -0.30),
                 (0.21, 0.30), (-0.21, 0.30)],
        bars_xy_area_mm2=[(0.0, -0.22, 314.0)])
    seals = {_bundle(item).content_sha256 for item in (first, renamed, widened)}
    assert len(seals) == 3


def test_normalised_node_owns_geometry_material_and_description_leaves():
    calculation = _elements(_bundle(_input()))[0]
    steps = _steps(calculation)
    dependencies = {
        item.step_id
        for item in steps["normalised-fatigue-inputs"].dependencies}
    assert {"geometry-vector", "material-vector"} <= dependencies
    assert any("-description-" in key for key in dependencies)
    assert any(key.startswith("geometry-ring-") for key in steps)
    assert any("material-concrete-" in key for key in steps)
    assert any("material-bar-" in key for key in steps)
    _reaches_every_step(calculation)


@pytest.mark.parametrize(("field", "bad"), [
    ("concrete_method", []),
    ("concrete_parameters", []),
])
def test_excluded_top_level_concrete_sibling_types_are_pinned(field, bad):
    inp = _input()
    out = _out(inp)
    altered = copy.deepcopy(out)
    altered["fatigue"][field] = bad
    with pytest.raises(TraceValidationError, match="retained type"):
        _bundle(inp, altered)


def test_joint_concrete_sibling_values_are_inert_but_types_remain_exact():
    inp = _input()
    inp["fatigue_check_concrete"] = True
    out = _out(inp)
    assert out["fatigue"]["checks"]["concrete"] is True
    changed = copy.deepcopy(out)
    changed["fatigue"]["concrete_method"] = "future CT-010b method"
    changed["fatigue"]["concrete_parameters"] = {"future": "values"}
    assert _bundle(inp, changed) == _bundle(inp, out)


def test_excluded_nested_concrete_fields_reject_type_replacements():
    inp = _input()
    out = _out(inp)
    changed = copy.deepcopy(out)
    spectra = list(changed["fatigue"]["spectra"])
    spectra[0] = dataclasses.replace(spectra[0], concrete=[])
    changed["fatigue"]["spectra"] = type(
        changed["fatigue"]["spectra"])(spectra)
    with pytest.raises(TraceValidationError, match="wrong retained type"):
        _bundle(inp, changed)

    changed = copy.deepcopy(out)
    spectra = list(changed["fatigue"]["spectra"])
    bins = list(spectra[0].bins)
    bins[0] = dataclasses.replace(
        bins[0], concrete_compression_long_mpa=[])
    spectra[0] = dataclasses.replace(
        spectra[0], bins=type(spectra[0].bins)(bins))
    changed["fatigue"]["spectra"] = type(
        changed["fatigue"]["spectra"])(spectra)
    with pytest.raises(TraceValidationError, match="wrong retained type"):
        _bundle(inp, changed)


@pytest.mark.parametrize("field", [
    "elements", "spectra", "governing_spectrum", "utilisation",
    "converged", "passed",
])
def test_owned_candidate_fields_are_exact(field):
    inp = _input()
    out = _out(inp)
    changed = copy.deepcopy(out)
    value = changed["fatigue"][field]
    if type(value) is bool:
        changed["fatigue"][field] = not value
    elif type(value) is float:
        changed["fatigue"][field] = value + 0.01
    elif type(value) is str:
        changed["fatigue"][field] = value + "-other"
    else:
        changed["fatigue"][field] = []
    with pytest.raises(TraceValidationError):
        _bundle(inp, changed)


def test_candidate_keys_order_and_finite_valid_sibling_are_closed():
    inp = _input()
    out = _out(inp)
    payload = out["fatigue"]
    reordered = {"fatigue": {key: payload[key] for key in reversed(payload)}}
    with pytest.raises(TraceValidationError, match="keys/order"):
        _bundle(inp, reordered)
    extra = copy.deepcopy(out)
    extra["fatigue"]["valid"] = True
    with pytest.raises(TraceValidationError):
        _bundle(inp, extra)


def test_2023_fatigue_detail_does_not_implement_2023_material_law():
    inp = _input(edition=fatigue_inputs.EC2_2023)
    inp[fatigue_inputs.DETAIL_CATALOG_KEY]["items"][0] = (
        fatigue_inputs.apply_preset(
            inp[fatigue_inputs.DETAIL_CATALOG_KEY]["items"][0],
            fatigue_inputs.PRESET_2023_BARS))
    assert _bundle(inp)
    entry = material_catalog.default_entry(
        "mild", material_id="B500", preset=codes.EC2_2023.label)
    inp["bar_materials"] = [material_catalog.build_material(entry, "mild")]
    inp[material_catalog.MILD_CATALOG_KEY] = {
        "version": 1, "next_id": 2, "items": [entry]}
    with pytest.raises(TraceValidationError, match="not implemented"):
        _bundle(inp)


def test_joint_and_concrete_only_output_ownership():
    joint = _input()
    joint["fatigue_check_concrete"] = True
    joint_steps = _steps(_bundle(joint).calculations[-1])
    assert "family-utilisation" not in joint_steps
    assert "governing-spectrum" not in joint_steps

    concrete_only = _input()
    concrete_only["fatigue_check_steel"] = False
    concrete_only["fatigue_check_concrete"] = True
    assert build_fatigue_trace_family(
        concrete_only, _out(concrete_only), input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) is None


def test_registry_ids_and_all_member_graphs_are_closed():
    bundle = _bundle(_input())
    assert REGISTRY_ID == "sector-ct-010-fatigue-v1"
    assert {item.coverage_id for item in bundle.calculations} == {COVERAGE_ID}
    assert {item.method_id for item in bundle.calculations} == {METHOD_ID}
    for calculation in bundle.calculations:
        _reaches_every_step(calculation)


def test_stale_hash_and_context_fail_exact_reconstruction():
    inp = _input()
    out = _out(inp)
    bundle = _bundle(inp, out)
    with pytest.raises(TraceValidationError):
        validate_fatigue_trace_family(
            bundle, inp, out, input_sha256="c" * 64,
            result_sha256=RESULT_SHA, context=CONTEXT)
    with pytest.raises(TraceValidationError):
        validate_fatigue_trace_family(
            bundle, inp, out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context={"case": "other"})


@pytest.mark.parametrize("kind", ["value", "source", "unit", "axis"])
def test_resealed_value_source_unit_and_axis_tampering_fails(kind):
    inp = _input()
    out = _out(inp)
    bundle = _bundle(inp, out)
    final_index = len(bundle.calculations[0].steps) - 1
    final = bundle.calculations[0].steps[final_index]
    if kind == "value":
        result = dataclasses.replace(
            final.result, value=final.result.value + 0.125)
        bad = _reseal_step(bundle, 0, final_index, result=result)
    elif kind == "source":
        bad = _reseal_step(
            bundle, 0, final_index,
            source=TraceSource(SOURCE_PROJECT, "changed-verdict"))
    elif kind == "unit":
        bad = _reseal_step(
            bundle, 0, final_index, unit=TraceUnit("x", "scalar"))
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
    inp = _input()
    out = _out(inp)
    bundle = _bundle(inp, out)
    calculation = bundle.calculations[0]
    index = next(
        i for i, step in enumerate(calculation.steps)
        if step.step_id.endswith("-stress-range")
        and not step.step_id.endswith("-design-stress-range"))
    step = calculation.steps[index]
    removed = _reseal_step(
        bundle, 0, index, dependencies=step.dependencies[1:])
    redirected = list(step.dependencies)
    redirected[0] = TraceDependency(
        "input-check-steel", _steps(calculation)["input-check-steel"].unit)
    redirected_bundle = _reseal_step(
        bundle, 0, index, dependencies=tuple(redirected))
    for bad in (removed, redirected_bundle):
        with pytest.raises(TraceValidationError):
            validate_fatigue_trace_family(
                bad, inp, out, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT)


def test_catalog_standard_and_project_sources_are_distinct():
    standard = _bundle(_input(catalog=True))
    project = _bundle(_input(catalog=False))
    standard_kinds = {
        step.source.kind for step in _elements(standard)[0].steps
        if "material-bar-" in step.step_id}
    project_kinds = {
        step.source.kind for step in _elements(project)[0].steps
        if "material-bar-" in step.step_id}
    assert standard_kinds == {SOURCE_STANDARD}
    assert project_kinds == {SOURCE_PROJECT}
