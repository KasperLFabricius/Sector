"""CT-010a closure tests for replay, identity, catalogues, and trace graphs."""

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
from sector.fatigue import FatigueLife  # noqa: E402
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


INPUT_SHA = "1" * 64
RESULT_SHA = "2" * 64
TRACE_CONTEXT = {"case": "fresh CT-010a"}


@pytest.fixture(autouse=True)
def _disable_autosave(monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct010-test-no-autosave")


def _spectrum(description: str = "Published governing bin"):
    rows = [
        {
            "spectrum": "Service traffic",
            "name": "HIGH",
            "description": description,
            "cycles": 150_000.0,
            "n_long_ed_kn": -160.0,
            "mx_long_ed_knm": 12.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 20.0,
            "mx_short_ed_knm": 16.0,
            "my_short_ed_knm": 0.0,
        },
        {
            "spectrum": "Service traffic",
            "name": "FREQUENT",
            "description": "Published frequent bin",
            "cycles": 800_000.0,
            "n_long_ed_kn": -160.0,
            "mx_long_ed_knm": 12.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 6.0,
            "mx_short_ed_knm": 5.0,
            "my_short_ed_knm": 0.0,
        },
    ]
    return fatigue_inputs.normalise_spectrum_table(rows)


def _input(
    *,
    with_concrete: bool = True,
    with_catalog: bool = True,
    material_id: str = "M1",
    concrete_id: str = "C1",
    description: str = "Published governing bin",
):
    entry = material_catalog.default_entry(
        "mild", material_id=material_id, preset=codes.EC2_2005.label
    )
    section = Section.from_polygon(
        corners=[
            (-0.19, -0.29),
            (0.19, -0.29),
            (0.19, 0.29),
            (-0.19, 0.29),
        ],
        bars_xy_area_mm2=[(0.0, -0.215, 314.0)],
    )
    inp = {
        "fatigue_on": True,
        "fatigue_edition": fatigue_inputs.EC2_2005,
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
        fatigue_inputs.SPECTRUM_TABLE_KEY: _spectrum(description),
        "section": section,
        "bar_elements": [
            {
                "id": "R1",
                "kind": "bar",
                "x_mm": 0.0,
                "y_mm": -215.0,
                "area_mm2": 314.0,
                "diameter_mm": 20.0,
                "material_id": material_id,
                "fatigue_detail_id": "F1",
            }
        ],
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
    if with_concrete:
        inp.update(
            {
                "concrete": codes.EC2_2005.concrete(30.0),
                "concrete_preset": codes.EC2_2005.label,
                "concrete_material_id": concrete_id,
            }
        )
    if with_catalog:
        next_id = int(material_id[1:]) + 1
        inp[material_catalog.MILD_CATALOG_KEY] = {
            "version": material_catalog.VERSION,
            "next_id": next_id,
            "items": [entry],
        }
    return inp


def _result(inp):
    errors = fatigue_analysis.validation_errors(inp)
    fatigue = (
        fatigue_analysis.invalid_result(inp, errors)
        if errors
        else fatigue_analysis.run_analysis(inp)
    )
    return {"fatigue": fatigue}


def _build(inp, out=None):
    retained = _result(inp) if out is None else out
    bundle = build_fatigue_trace_family(
        inp,
        retained,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=TRACE_CONTEXT,
    )
    assert bundle is not None
    return bundle


def _element(bundle):
    return next(
        calculation
        for calculation in bundle.calculations
        if calculation.final_step_id == "ct-010-element-result"
    )


def _steps(calculation):
    return {step.step_id: step for step in calculation.steps}


def _assert_final_reaches_every_step(calculation):
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


def _reseal(bundle, *, step_id: str, **changes):
    calculations = list(bundle.calculations)
    calculation_index = next(
        index
        for index, calculation in enumerate(calculations)
        if step_id in _steps(calculation)
    )
    calculation = calculations[calculation_index]
    steps = list(calculation.steps)
    step_index = next(
        index for index, step in enumerate(steps) if step.step_id == step_id
    )
    steps[step_index] = dataclasses.replace(steps[step_index], **changes)
    calculations[calculation_index] = dataclasses.replace(
        calculation, steps=tuple(steps)
    )
    return seal_bundle(
        dataclasses.replace(
            bundle, calculations=tuple(calculations), content_sha256=""
        )
    )


def test_headless_reinforcement_and_concrete_identity_are_explicit():
    headless = _input(with_concrete=False)
    assert fatigue_analysis.validation_errors(headless) == []
    headless_steps = _steps(_element(_build(headless)))
    assert headless_steps["input-concrete-material-present"].result.value == 0.0
    assert not any(key.startswith("material-concrete-") for key in headless_steps)

    supplied = _input(concrete_id="C30-published")
    supplied_steps = _steps(_element(_build(supplied)))
    assert supplied_steps["input-concrete-material-present"].result.value == 1.0
    assert any(key.startswith("material-concrete-") for key in supplied_steps)


def test_missing_concrete_for_concrete_check_is_a_retained_failure():
    inp = _input(with_concrete=False)
    inp["fatigue_check_concrete"] = True
    out = _result(inp)
    assert out["fatigue"]["valid"] is False
    bundle = _build(inp, out)
    assert bundle.calculations[0].steps[-1].result.state == "failed"


def test_description_concrete_id_geometry_and_material_id_reseal_identity():
    baseline = _build(_input())
    changed_description = _build(_input(description="Different published text"))
    changed_concrete = _build(_input(concrete_id="C2"))
    changed_material = _build(_input(material_id="M2"))
    hashes = {
        baseline.content_sha256,
        changed_description.content_sha256,
        changed_concrete.content_sha256,
        changed_material.content_sha256,
    }
    assert len(hashes) == 4


def test_complete_geometry_and_material_vectors_reach_the_member_final():
    calculation = _element(_build(_input()))
    steps = _steps(calculation)
    normalised = {
        dep.step_id for dep in steps["normalised-fatigue-inputs"].dependencies
    }
    assert {"geometry-vector", "material-vector"} <= normalised
    final_dependencies = {
        dep.step_id for dep in steps[calculation.final_step_id].dependencies
    }
    assert "normalised-fatigue-inputs" in final_dependencies
    _assert_final_reaches_every_step(calculation)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state: setattr(
            state.elastic_result.long,
            "eps0",
            state.elastic_result.long.eps0 + 1.0e-9,
        ),
        lambda state: state.elastic_result.long.bar_stress.__setitem__(
            0, state.elastic_result.long.bar_stress[0] + 0.125
        ),
        lambda state: setattr(
            state.elastic_result.short_term,
            "converged",
            not state.elastic_result.short_term.converged,
        ),
        lambda state: setattr(
            state.design_elastic_result.short_term,
            "iterations",
            state.design_elastic_result.short_term.iterations + 1,
        ),
    ],
)
def test_every_retained_elastic_solve_value_is_exact(mutate):
    inp = _input()
    out = _result(inp)
    candidate = copy.deepcopy(out)
    state = candidate["fatigue"]["spectra"][0].bins[0]
    mutate(state)
    with pytest.raises(TraceValidationError, match="authoritative replay"):
        _build(inp, candidate)


def test_excluded_concrete_siblings_keep_presence_position_and_type():
    inp = _input()
    out = _result(inp)
    for key in ("concrete_method", "concrete_parameters"):
        candidate = copy.deepcopy(out)
        candidate["fatigue"][key] = []
        with pytest.raises(TraceValidationError, match="retained type"):
            _build(inp, candidate)

    candidate = copy.deepcopy(out)
    spectrum = candidate["fatigue"]["spectra"][0]
    candidate["fatigue"]["spectra"] = (
        dataclasses.replace(spectrum, concrete=[]),
    )
    with pytest.raises(TraceValidationError, match="wrong retained type"):
        _build(inp, candidate)


def test_application_edition_alias_is_not_allowed_at_trace_boundary():
    inp = _input()
    inp["fatigue_edition"] = "2005"
    assert fatigue_analysis.validation_errors(inp) == []
    with pytest.raises(TraceValidationError, match="exact retained edition"):
        _build(inp)


@pytest.mark.parametrize(
    ("key", "lookalike"),
    [
        ("fatigue_on", 1),
        ("fatigue_check_steel", 1),
        ("fatigue_check_concrete", 0),
        ("nl", True),
        ("fatigue_gamma_ff", "1.0"),
    ],
)
def test_flags_and_finite_inputs_are_not_coerced(key, lookalike):
    inp = _input()
    inp[key] = lookalike
    with pytest.raises(TraceValidationError):
        _build(inp)


def test_catalog_free_laws_are_accepted_as_uncited_project_values():
    inp = _input(with_catalog=False, material_id="owner-B500")
    bundle = _build(inp)
    sources = {
        step.source.kind
        for step in _element(bundle).steps
        if step.step_id.startswith("material-bar-")
    }
    assert sources == {SOURCE_PROJECT}


def test_present_catalog_must_be_complete_and_canonical():
    base = _input()
    key = material_catalog.MILD_CATALOG_KEY
    damaged = []

    wrong_version = copy.deepcopy(base)
    wrong_version[key]["version"] = 99
    damaged.append(wrong_version)

    bool_next = copy.deepcopy(base)
    bool_next[key]["next_id"] = True
    damaged.append(bool_next)

    extra_top = copy.deepcopy(base)
    extra_top[key]["ignored"] = "not retained"
    damaged.append(extra_top)

    malformed_sibling = copy.deepcopy(base)
    malformed_sibling[key]["items"].append({})
    damaged.append(malformed_sibling)

    duplicate = copy.deepcopy(base)
    duplicate[key]["items"].append(copy.deepcopy(duplicate[key]["items"][0]))
    damaged.append(duplicate)

    noncanonical_id = copy.deepcopy(base)
    noncanonical_id[key]["items"][0]["id"] = "B500"
    noncanonical_id["bar_elements"][0]["material_id"] = "B500"
    damaged.append(noncanonical_id)

    unknown_item_key = copy.deepcopy(base)
    unknown_item_key[key]["items"][0]["ignored"] = 1.0
    damaged.append(unknown_item_key)

    for inp in damaged:
        with pytest.raises(TraceValidationError):
            _build(inp)


def test_fully_canonical_unassigned_material_is_allowed():
    inp = _input()
    key = material_catalog.MILD_CATALOG_KEY
    expanded, new_id = material_catalog.add_entry(inp[key], "mild")
    assert new_id == "M2"
    inp[key] = expanded
    assert _build(inp).calculations


def test_independent_numerical_replay_rejects_engine_contradiction(monkeypatch):
    inp = _input()
    out = _result(inp)

    def false_life(*_args, **_kwargs):
        return FatigueLife(cycles=1.0, log10_cycles=0.0, exponent=1.0)

    monkeypatch.setattr("sector.fatigue_trace.steel_fatigue_life", false_life)
    with pytest.raises(TraceValidationError, match="declared operands"):
        _build(inp, out)


def test_sn_miner_and_verdict_steps_are_operand_derived():
    inp = _input()
    out = _result(inp)
    steps = _steps(_element(_build(inp, out)))
    retained = out["fatigue"]["spectra"][0].reinforcement[0]
    damage_steps = sorted((
        step
        for step in steps.values()
        if step.step_id.endswith("-damage") and step.step_id.startswith("bin-")
    ), key=lambda step: step.step_id)
    for step, bin_result in zip(damage_steps, retained.bins):
        assert step.result.value == pytest.approx(
            bin_result.cycles / 10.0 ** bin_result.log10_cycles_to_failure
        )
    assert steps["damage-total"].result.value == pytest.approx(
        sum(item.damage for item in retained.bins)
    )
    assert steps["ct-010-element-result"].result.value == float(retained.passed)


def test_registry_and_every_calculation_graph_are_closed():
    bundle = _build(_input())
    assert bundle.calculations
    for calculation in bundle.calculations:
        assert calculation.coverage_id == COVERAGE_ID
        assert calculation.method_id == METHOD_ID
        _assert_final_reaches_every_step(calculation)
    payload = bundle.to_dict()
    assert payload["schema"] == "sector.calculation-trace.v1"
    assert REGISTRY_ID == "sector-ct-010-fatigue-v1"


def test_resealed_value_source_unit_and_dependency_tampering_is_rejected():
    inp = _input()
    out = _result(inp)
    bundle = _build(inp, out)
    step = _steps(_element(bundle))["damage-total"]
    attacks = (
        _reseal(
            bundle,
            step_id="damage-total",
            result=dataclasses.replace(step.result, value=step.result.value + 0.1),
        ),
        _reseal(
            bundle,
            step_id="damage-total",
            source=TraceSource(SOURCE_PROJECT, "invented-project-method"),
        ),
        _reseal(
            bundle,
            step_id="damage-total",
            dependencies=(TraceDependency("input-nl", step.unit),),
        ),
    )
    for candidate in attacks:
        with pytest.raises(TraceValidationError):
            validate_fatigue_trace_family(
                candidate,
                inp,
                out,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
                context=TRACE_CONTEXT,
            )

    with pytest.raises(TraceValidationError):
        _reseal(
            bundle,
            step_id="damage-total",
            unit=TraceUnit("%", "ratio"),
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda inp, out: inp.pop("fatigue_on"),
        lambda inp, out: inp.__setitem__("fatigue_on", False),
        lambda inp, out: inp.__setitem__("section", None),
    ],
)
def test_inactive_input_requires_complete_candidate_absence(change):
    inp = _input()
    out = _result(inp)
    change(inp, out)
    with pytest.raises(TraceValidationError, match="cannot carry"):
        _build(inp, out)
    assert (
        build_fatigue_trace_family(
            inp,
            {},
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context=TRACE_CONTEXT,
        )
        is None
    )


def test_material_and_fatigue_sources_remain_distinct():
    bundle = _build(_input())
    steps = _steps(_element(bundle))
    material_sources = {
        step.source.kind
        for step in steps.values()
        if step.step_id.startswith("material-")
        and not step.step_id.endswith("vector")
    }
    sn_sources = {
        step.source.kind
        for step in steps.values()
        if step.step_id.endswith("-sn-exponent")
    }
    assert material_sources == {SOURCE_STANDARD}
    assert sn_sources == {SOURCE_STANDARD}
    assert {
        step.source.method_id
        for step in steps.values()
        if step.step_id.startswith("material-")
    }.isdisjoint(
        {
            step.source.method_id
            for step in steps.values()
            if step.step_id.endswith("-sn-exponent")
        }
    )
