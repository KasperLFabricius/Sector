"""Hostile CT-010a replay, numerical, identity, and graph tests."""

from __future__ import annotations

import copy
import dataclasses
import math
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
    _damage_from_log,
    build_fatigue_trace_family,
    validate_fatigue_trace_family,
)
from sector.fatigue_trace_contract import (  # noqa: E402
    COVERAGE_ID,
    METHOD_ID,
    REGISTRY_ID,
)
from sector.section import Section  # noqa: E402


INPUT_SHA = "3" * 64
RESULT_SHA = "4" * 64
CONTEXT = {"case": "CT-010a r5"}


@pytest.fixture(autouse=True)
def _no_autosave(monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct010-r5-no-autosave")


def _spectrum(description="Published primary bin", *, one_bin=False):
    records = [
        {
            "spectrum": "Rail fatigue",
            "name": "PRIMARY",
            "description": description,
            "cycles": 120_000.0,
            "n_long_ed_kn": -150.0,
            "mx_long_ed_knm": 11.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 18.0,
            "mx_short_ed_knm": 14.0,
            "my_short_ed_knm": 0.0,
        },
        {
            "spectrum": "Rail fatigue",
            "name": "SECONDARY",
            "description": "Published secondary bin",
            "cycles": 650_000.0,
            "n_long_ed_kn": -150.0,
            "mx_long_ed_knm": 11.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 5.0,
            "mx_short_ed_knm": 4.0,
            "my_short_ed_knm": 0.0,
        },
    ]
    return fatigue_inputs.normalise_spectrum_table(
        records[:1] if one_bin else records)


def _input(
    *,
    concrete=True,
    material_catalogue=True,
    material_id="M1",
    concrete_id="C1",
    description="Published primary bin",
    joint=False,
):
    material = material_catalog.default_entry(
        "mild", material_id=material_id, preset=codes.EC2_2005.label)
    section = Section.from_polygon(
        corners=[
            (-0.18, -0.28), (0.18, -0.28),
            (0.18, 0.28), (-0.18, 0.28),
        ],
        bars_xy_area_mm2=[(0.0, -0.205, 314.0)],
    )
    inp = {
        "fatigue_on": True,
        "fatigue_edition": fatigue_inputs.EC2_2005,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": joint,
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
        fatigue_inputs.SPECTRUM_TABLE_KEY: _spectrum(
            description, one_bin=joint),
        "section": section,
        "bar_elements": [{
            "id": "R1",
            "kind": "bar",
            "x_mm": 0.0,
            "y_mm": -205.0,
            "area_mm2": 314.0,
            "diameter_mm": 20.0,
            "material_id": material_id,
            "fatigue_detail_id": "F1",
        }],
        "tendon_elements": [],
        "bar_materials": [
            material_catalog.build_material(material, "mild")],
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
    if material_catalogue:
        next_id = int(material_id[1:]) + 1
        inp[material_catalog.MILD_CATALOG_KEY] = {
            "version": material_catalog.VERSION,
            "next_id": next_id,
            "items": [material],
        }
    return inp


def _out(inp):
    errors = fatigue_analysis.validation_errors(inp)
    payload = (
        fatigue_analysis.invalid_result(inp, errors)
        if errors else fatigue_analysis.run_analysis(inp))
    return {"fatigue": payload}


def _bundle(inp, out=None):
    candidate = _out(inp) if out is None else out
    bundle = build_fatigue_trace_family(
        inp,
        candidate,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    )
    assert bundle is not None
    return bundle


def _elements(bundle):
    return tuple(
        calc for calc in bundle.calculations
        if calc.final_step_id == "ct-010-element-result")


def _steps(calc):
    return {step.step_id: step for step in calc.steps}


def _reaches_all(calc):
    steps = _steps(calc)
    reached = set()
    pending = [calc.final_step_id]
    while pending:
        step_id = pending.pop()
        if step_id in reached:
            continue
        reached.add(step_id)
        pending.extend(dep.step_id for dep in steps[step_id].dependencies)
    assert reached == set(steps)


def _reseal(bundle, step_id, **changes):
    calculations = list(bundle.calculations)
    ci = next(i for i, calc in enumerate(calculations) if step_id in _steps(calc))
    calc = calculations[ci]
    steps = list(calc.steps)
    si = next(i for i, step in enumerate(steps) if step.step_id == step_id)
    steps[si] = dataclasses.replace(steps[si], **changes)
    calculations[ci] = dataclasses.replace(calc, steps=tuple(steps))
    return seal_bundle(dataclasses.replace(
        bundle, calculations=tuple(calculations), content_sha256=""))


def test_reinforcement_only_accepts_absent_concrete_and_binds_presence():
    inp = _input(concrete=False)
    assert fatigue_analysis.validation_errors(inp) == []
    steps = _steps(_elements(_bundle(inp))[0])
    assert steps["input-concrete-material-present"].result.value == 0.0
    assert not any(key.startswith("material-concrete-") for key in steps)


def test_joint_gamma_c_reaches_every_element_and_output_final():
    inp = _input(joint=True)
    bundle = _bundle(inp)
    owned = tuple(
        calc for calc in bundle.calculations
        if calc.final_step_id in {
            "ct-010-element-result",
            "ct-010-reinforcement-output-result",
        })
    assert owned
    for calc in owned:
        steps = _steps(calc)
        assert steps["input-gamma-c"].result.value == 1.5
        _reaches_all(calc)


def test_log_domain_damage_survives_underflowed_life():
    damage = _damage_from_log(1.0e-320, -330.0)
    assert math.isfinite(damage)
    assert 9.9e9 < damage < 1.01e10
    assert _damage_from_log(1.0, math.inf) == 0.0


def test_missing_concrete_joint_input_is_retained_invalid_evidence():
    inp = _input(concrete=False, joint=True)
    out = _out(inp)
    assert out["fatigue"]["valid"] is False
    bundle = _bundle(inp, out)
    assert bundle.calculations[0].steps[-1].result.state == "failed"


def test_description_geometry_and_same_law_material_id_change_trace_identity():
    original = _bundle(_input())
    description = _bundle(_input(description="Changed publication text"))
    concrete_id = _bundle(_input(concrete_id="C2"))
    material_id = _bundle(_input(material_id="M2"))
    assert len({
        original.content_sha256,
        description.content_sha256,
        concrete_id.content_sha256,
        material_id.content_sha256,
    }) == 4


def test_geometry_and_material_vectors_are_in_final_dependency_closure():
    calc = _elements(_bundle(_input()))[0]
    steps = _steps(calc)
    normalised = {
        dep.step_id for dep in steps["normalised-fatigue-inputs"].dependencies}
    assert {"geometry-vector", "material-vector"} <= normalised
    assert "normalised-fatigue-inputs" in {
        dep.step_id for dep in steps[calc.final_step_id].dependencies}
    _reaches_all(calc)


@pytest.mark.parametrize("mutation", [
    lambda state: setattr(
        state.elastic_result.long, "eps0",
        state.elastic_result.long.eps0 + 1.0e-9),
    lambda state: state.elastic_result.long.bar_stress.__setitem__(
        0, state.elastic_result.long.bar_stress[0] + 0.25),
    lambda state: setattr(
        state.elastic_result.short_term, "converged",
        not state.elastic_result.short_term.converged),
    lambda state: setattr(
        state.design_elastic_result.short_term, "iterations",
        state.design_elastic_result.short_term.iterations + 1),
])
def test_complete_retained_elastic_graph_is_exact(mutation):
    inp = _input()
    candidate = copy.deepcopy(_out(inp))
    mutation(candidate["fatigue"]["spectra"][0].bins[0])
    with pytest.raises(TraceValidationError, match="authoritative replay"):
        _bundle(inp, candidate)


@pytest.mark.parametrize("field", ["concrete_method", "concrete_parameters"])
def test_excluded_top_level_concrete_siblings_are_type_fenced(field):
    inp = _input()
    candidate = copy.deepcopy(_out(inp))
    candidate["fatigue"][field] = []
    with pytest.raises(TraceValidationError, match="retained type"):
        _bundle(inp, candidate)


def test_excluded_nested_concrete_sibling_replacement_is_rejected():
    inp = _input()
    candidate = copy.deepcopy(_out(inp))
    spectrum = candidate["fatigue"]["spectra"][0]
    candidate["fatigue"]["spectra"] = (
        dataclasses.replace(spectrum, concrete=[]),)
    with pytest.raises(TraceValidationError, match="wrong retained type"):
        _bundle(inp, candidate)


def test_finite_edition_alias_is_not_citable():
    inp = _input()
    inp["fatigue_edition"] = "2005"
    assert fatigue_analysis.validation_errors(inp) == []
    with pytest.raises(TraceValidationError, match="exact retained edition"):
        _bundle(inp)


@pytest.mark.parametrize(("key", "lookalike"), [
    ("fatigue_on", 1),
    ("fatigue_check_steel", 1),
    ("fatigue_check_concrete", 0),
    ("nl", True),
    ("fatigue_gamma_ff", "1.0"),
])
def test_boolean_and_numeric_lookalikes_are_not_coerced(key, lookalike):
    inp = _input()
    inp[key] = lookalike
    with pytest.raises(TraceValidationError):
        _bundle(inp)


def test_catalog_free_explicit_law_is_project_provenance():
    inp = _input(material_catalogue=False, material_id="owner-B500")
    steps = _steps(_elements(_bundle(inp))[0])
    sources = {
        step.source.kind for key, step in steps.items()
        if key.startswith("material-bar-")}
    assert sources == {SOURCE_PROJECT}


def test_present_material_catalogue_is_fully_canonical():
    key = material_catalog.MILD_CATALOG_KEY
    cases = []
    for mutate in (
        lambda cat: cat.__setitem__("version", 99),
        lambda cat: cat.__setitem__("next_id", True),
        lambda cat: cat.__setitem__("extra", "ignored"),
        lambda cat: cat["items"].append({}),
        lambda cat: cat["items"].append(copy.deepcopy(cat["items"][0])),
        lambda cat: cat["items"][0].__setitem__("extra", 1.0),
    ):
        inp = _input()
        mutate(inp[key])
        cases.append(inp)
    noncanonical = _input()
    noncanonical[key]["items"][0]["id"] = "B500"
    noncanonical["bar_elements"][0]["material_id"] = "B500"
    cases.append(noncanonical)
    for inp in cases:
        with pytest.raises(TraceValidationError):
            _bundle(inp)


def test_fatigue_detail_catalogue_metadata_and_siblings_are_canonical():
    key = fatigue_inputs.DETAIL_CATALOG_KEY
    cases = []
    for mutate in (
        lambda cat: cat.__setitem__("version", 1),
        lambda cat: cat.__setitem__("next_id", False),
        lambda cat: cat.__setitem__("extra", "ignored"),
        lambda cat: cat["items"].append({}),
        lambda cat: cat["items"][0].__setitem__("source", " altered "),
    ):
        inp = _input()
        mutate(inp[key])
        cases.append(inp)
    for inp in cases:
        with pytest.raises(TraceValidationError):
            _bundle(inp)


def test_unassigned_canonical_material_and_detail_entries_are_allowed():
    inp = _input()
    materials, material_id = material_catalog.add_entry(
        inp[material_catalog.MILD_CATALOG_KEY], "mild")
    details, detail_id = fatigue_inputs.add_entry(
        inp[fatigue_inputs.DETAIL_CATALOG_KEY])
    assert material_id == "M2"
    assert detail_id == "F2"
    inp[material_catalog.MILD_CATALOG_KEY] = materials
    inp[fatigue_inputs.DETAIL_CATALOG_KEY] = details
    assert _bundle(inp).calculations


def test_raw_state_to_result_contradiction_cannot_be_sealed(monkeypatch):
    inp = _input()
    authoritative = _out(inp)["fatigue"]
    spectrum = authoritative["spectra"][0]
    result = spectrum.reinforcement[0]
    first = dataclasses.replace(
        result.bins[0], stress_long_mpa=result.bins[0].stress_long_mpa + 0.5)
    changed_result = dataclasses.replace(
        result, bins=(first, *result.bins[1:]))
    changed_spectrum = dataclasses.replace(
        spectrum, reinforcement=(changed_result,))
    contradictory = dict(authoritative)
    contradictory["spectra"] = (changed_spectrum,)
    monkeypatch.setattr(
        fatigue_analysis, "run_analysis", lambda _inp: contradictory)
    with pytest.raises(TraceValidationError, match="declared operands"):
        _bundle(inp, {"fatigue": contradictory})


def test_log_damage_contradiction_cannot_be_sealed(monkeypatch):
    inp = _input()
    out = _out(inp)
    monkeypatch.setattr(
        "sector.fatigue_trace._damage_from_log",
        lambda _cycles, _log_life: 123.0,
    )
    with pytest.raises(TraceValidationError, match="declared operands"):
        _bundle(inp, out)


def test_trace_values_match_independent_bin_and_element_replay():
    inp = _input()
    out = _out(inp)
    steps = _steps(_elements(_bundle(inp, out))[0])
    retained = out["fatigue"]["spectra"][0].reinforcement[0]
    assert steps["damage-total"].result.value == pytest.approx(
        sum(item.damage for item in retained.bins))
    assert steps["yield-utilisation"].result.value == pytest.approx(
        retained.yield_utilisation)
    assert steps["utilisation"].result.value == pytest.approx(
        retained.utilisation)
    assert steps["ct-010-element-result"].result.value == float(
        retained.passed)


def test_registry_identity_and_all_final_graphs_are_closed():
    bundle = _bundle(_input())
    assert REGISTRY_ID == "sector-ct-010-fatigue-v1"
    for calc in bundle.calculations:
        assert calc.coverage_id == COVERAGE_ID
        assert calc.method_id == METHOD_ID
        _reaches_all(calc)


def test_resealed_value_source_and_dependency_tampering_fails():
    inp = _input()
    out = _out(inp)
    bundle = _bundle(inp, out)
    step = _steps(_elements(bundle)[0])["damage-total"]
    attacks = (
        _reseal(
            bundle,
            "damage-total",
            result=dataclasses.replace(
                step.result, value=step.result.value + 0.01),
        ),
        _reseal(
            bundle,
            "damage-total",
            source=TraceSource(SOURCE_PROJECT, "invented-project-method"),
        ),
        _reseal(
            bundle,
            "damage-total",
            dependencies=(TraceDependency("input-nl", step.unit),),
        ),
    )
    for attack in attacks:
        with pytest.raises(TraceValidationError):
            validate_fatigue_trace_family(
                attack,
                inp,
                out,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
                context=CONTEXT,
            )
    with pytest.raises(TraceValidationError):
        _reseal(bundle, "damage-total", unit=TraceUnit("%", "ratio"))


@pytest.mark.parametrize("change", [
    lambda inp: inp.pop("fatigue_on"),
    lambda inp: inp.__setitem__("fatigue_on", False),
    lambda inp: inp.__setitem__("section", None),
])
def test_inactive_state_requires_total_fatigue_surface_absence(change):
    inp = _input()
    out = _out(inp)
    change(inp)
    with pytest.raises(TraceValidationError, match="cannot carry"):
        _bundle(inp, out)
    assert build_fatigue_trace_family(
        inp,
        {},
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    ) is None


def test_material_law_and_fatigue_equation_sources_are_distinct():
    steps = _steps(_elements(_bundle(_input()))[0])
    material_methods = {
        step.source.method_id for key, step in steps.items()
        if key.startswith("material-") and key != "material-vector"}
    fatigue_methods = {
        step.source.method_id for key, step in steps.items()
        if key.endswith("-sn-exponent")}
    assert material_methods
    assert fatigue_methods
    assert material_methods.isdisjoint(fatigue_methods)
    assert {
        step.source.kind for key, step in steps.items()
        if key.endswith("-sn-exponent")} == {SOURCE_STANDARD}
