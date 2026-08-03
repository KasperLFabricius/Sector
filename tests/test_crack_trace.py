"""Independent CT-009 oracle, exact-contract, and hostile-boundary tests."""

from __future__ import annotations

import copy
import dataclasses
import math
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import sector_app
from sector import codes, templates
from sector.calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_UNDEFINED,
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    TraceDependency,
    TraceValidationError,
    bundle_to_json,
    seal_bundle,
)
import sector.crack_trace as crack_trace
from sector.crack_trace import (
    build_crack_trace_family,
    validate_crack_trace_family,
)
from sector.crack_trace_contract import (
    CASE_LONG_COARSE,
    CASE_LONG_FINE,
    CASE_SHORT_COARSE,
    CASE_SHORT_FINE,
    CT005,
    DOC_BASE,
    DOC_DK,
    registry_for,
    MemberShape,
)
from sector.section import Section
from sector.trace_registry import audit_trace_registry


INPUT_SHA = "8" * 64
RESULT_SHA = "9" * 64
CONTEXT = {"case": "ct009-focus", "stage": 3}


@pytest.fixture(autouse=True)
def _isolate_autosave(monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct009-headless-no-autosave")


def _catalog_item(material_id, name, preset, law):
    item = {"id": material_id, "name": name, "preset": preset}
    for field in dataclasses.fields(law):
        value = getattr(law, field.name)
        if field.name in {"IS", "eut", "ey0t", "ey0c"}:
            value *= 1000.0
        elif field.name == "Es":
            value /= 1000.0
        item[field.name] = value
    return item


def _input(*, dk=False, holed=False, moment=150.0):
    if holed:
        outer = [(0.0, 0.0), (0.35, 0.0), (0.32, 0.60), (0.0, 0.60)]
        holes = [[(0.13, 0.25), (0.13, 0.35), (0.19, 0.35), (0.19, 0.25)]]
        bars = [(0.075, 0.05, 491.0), (0.16, 0.05, 491.0), (0.245, 0.05, 491.0)]
    else:
        outer = [(0.0, 0.0), (0.30, 0.0), (0.30, 0.60), (0.0, 0.60)]
        holes = []
        bars = [(0.075, 0.05, 491.0), (0.15, 0.05, 491.0), (0.225, 0.05, 491.0)]
    section = Section.from_polygon(outer, bars, holes=holes)
    concrete = codes.EC2_2005.concrete(30.0)
    steel = codes.EC2_2005.steel(500.0)
    ec_gpa = 33.0
    creep = 1.0
    bar_elements = [
        {
            "id": f"B{index + 1}",
            "material_id": "M-B500",
            "diameter_mm": 25.0,
            "description": f"bottom bar {index + 1}",
        }
        for index in range(len(bars))
    ]
    return {
        "mode": "Elastic",
        "section": section,
        "outer": outer,
        "holes": holes,
        "bars": bars,
        "tendons": [],
        "geometry_error": None,
        "void_error": None,
        "steel_error": None,
        "material_error": None,
        "concrete": concrete,
        "steel": steel,
        "prestress": None,
        "bar_materials": None,
        "tendon_materials": [],
        "concrete_preset": codes.EC2_2005.label,
        "mild_preset": codes.EC2_2005.label,
        "prestress_preset": "Custom / imported",
        "concrete_material_id": "C30-primary",
        "bar_elements": bar_elements,
        "tendon_elements": [],
        "mild_material_catalog": {
            "version": 1,
            "next_id": 2,
            "items": [
                _catalog_item(
                    "M-B500", "B500 reinforcement", codes.EC2_2005.label, steel)
            ],
        },
        "prestress_material_catalog": {
            "version": 1, "next_id": 1, "items": [],
        },
        "P_pl": 0.0,
        "Mx_pl": 0.0,
        "My_pl": 0.0,
        "P_el_l": 0.0,
        "Mx_el_l": moment,
        "My_el_l": 0.0,
        "P_el_s": 0.0,
        "Mx_el_s": 20.0 if moment > 20.0 else 0.0,
        "My_el_s": 0.0,
        "conc_Ec": ec_gpa,
        "el_phi": creep,
        "ns": 200_000.0 / (ec_gpa * 1000.0),
        "nl": 200_000.0 * (1.0 + creep) / (ec_gpa * 1000.0),
        "sls_fctm": 2.9,
        "sls_phi": 25.0,
        "sls_k1": 0.8,
        "sls_dk_na": dk,
        "sls_member": "Beam",
        "sls_edition": "2004",
        "sls_code": "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010",
        "sls_cw": True,
        "sls_tendon_xi": 0.0,
        "minimum_reinforcement_on": False,
        "fatigue_on": False,
    }


def _candidate(inp):
    result = sector_app._run_single_analysis(inp)
    assert "elastic" in result
    return result


def _build(inp, out):
    return build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    )


@pytest.fixture(scope="module")
def base_case():
    inp = _input()
    out = _candidate(inp)
    bundle = _build(inp, out)
    return inp, out, bundle


@pytest.fixture(scope="module")
def dk_case():
    inp = _input(dk=True)
    out = _candidate(inp)
    bundle = _build(inp, out)
    return inp, out, bundle


def _member_id(calculation):
    if calculation.calculation_id.endswith("-aggregate"):
        return "aggregate"
    return next(
        case_id for case_id in (
            CASE_LONG_FINE, CASE_SHORT_FINE,
            CASE_LONG_COARSE, CASE_SHORT_COARSE,
        )
        if calculation.calculation_id.endswith(f"-{case_id}")
    )


def test_base_round_trip_exact_registry_and_case_order(base_case):
    inp, out, bundle = base_case
    assert bundle is not None
    assert [_member_id(item) for item in bundle.calculations] == [
        CASE_LONG_FINE, CASE_SHORT_FINE, "aggregate"]
    assert [item.steps[-1].result.state for item in bundle.calculations] == [
        RESULT_FINITE, RESULT_FINITE, RESULT_FINITE]
    assert validate_crack_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) == bundle
    assert "sector.calculation-trace.v1" in bundle_to_json(bundle)
    shapes = tuple(
        MemberShape(_member_id(item), item, item.steps[-1].result.state)
        for item in bundle.calculations)
    assert audit_trace_registry(bundle, registry_for(shapes)) == bundle


def test_dk_round_trip_requires_four_ordered_cases(dk_case):
    inp, out, bundle = dk_case
    assert [_member_id(item) for item in bundle.calculations] == [
        CASE_LONG_FINE, CASE_SHORT_FINE,
        CASE_LONG_COARSE, CASE_SHORT_COARSE, "aggregate",
    ]
    assert validate_crack_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) == bundle
    source_editions = {
        step.source.edition
        for calculation in bundle.calculations
        for step in calculation.steps
        if step.source.kind == SOURCE_STANDARD
    }
    assert DOC_BASE in source_editions
    assert DOC_DK in source_editions


def test_rectangular_fine_case_matches_independent_hand_oracle(base_case):
    inp, out, bundle = base_case
    crack = out["elastic"]["crack"]
    candidate = crack["candidates"][0]
    h = 0.60
    d = 0.55
    hc_eff = min(2.5 * (h - d), h / 2.0)
    assert hc_eff == pytest.approx(0.125)
    ac_eff = 0.30 * hc_eff
    rho = 3.0 * 491.0e-6 / ac_eff
    sigma = out["elastic"]["long"][candidate["element_no"] - 1]
    es = inp["steel"].Es
    esm = max(
        (
            sigma
            - 0.4 * inp["sls_fctm"] / rho
            * (1.0 + inp["nl"] * rho)
        ) / es,
        0.6 * sigma / es,
    )
    cover = 50.0 - 25.0 / 2.0
    sr_max = (
        3.4 * cover
        + inp["sls_k1"] * 0.5 * 0.425 * 25.0 / rho
    )
    assert candidate["hc_ef"] == pytest.approx(hc_eff, abs=1e-12)
    assert candidate["ac_eff"] == pytest.approx(ac_eff, abs=1e-12)
    assert candidate["rho_p_eff"] == pytest.approx(rho, rel=1e-12)
    assert candidate["cover"] == pytest.approx(cover, abs=1e-9)
    assert candidate["esm_ecm"] == pytest.approx(esm, rel=1e-12)
    assert candidate["sr_max"] == pytest.approx(sr_max, rel=1e-12)
    assert candidate["wk"] == pytest.approx(sr_max * esm, rel=1e-12)
    assert bundle.calculations[0].steps[-1].result.value == crack["wk"]


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("missing", "ordered inventory"),
        ("reordered", "ordered inventory"),
        ("mapping-type", "different inventory|exact object|ordered inventory"),
        ("candidate-list-type", "candidates must be a list"),
        ("nextafter", "exact authoritative replay"),
        ("aggregate", "exact authoritative replay"),
    ],
)
def test_exact_payload_inventory_types_and_adjacent_float_are_fenced(
    base_case, mutation, match,
):
    inp, out, _bundle = base_case
    changed = copy.deepcopy(out)
    elastic = changed["elastic"]
    if mutation == "missing":
        del elastic["max_conc"]
    elif mutation == "reordered":
        elastic["total"] = elastic.pop("total")
    elif mutation == "mapping-type":
        elastic["crack"] = list(elastic["crack"].items())
    elif mutation == "candidate-list-type":
        elastic["crack"]["candidates"] = tuple(
            elastic["crack"]["candidates"])
    elif mutation == "nextafter":
        elastic["crack"]["wk"] = math.nextafter(
            elastic["crack"]["wk"], math.inf)
    else:
        elastic["crack_output"]["value"] = math.nextafter(
            elastic["crack_output"]["value"], math.inf)
    with pytest.raises(TraceValidationError, match=match):
        _build(inp, changed)


def test_candidate_order_governor_and_branch_tampering_are_fenced(base_case):
    inp, out, _bundle = base_case
    for mutate in ("order", "governor", "branch"):
        changed = copy.deepcopy(out)
        crack = changed["elastic"]["crack"]
        if mutate == "order":
            crack["candidates"].reverse()
        elif mutate == "governor":
            crack["gov_bar"] = 2 if crack["gov_bar"] != 2 else 1
        else:
            crack["candidates"][0]["sr_max_geometric"] = not (
                crack["candidates"][0]["sr_max_geometric"])
        with pytest.raises(TraceValidationError, match="authoritative replay"):
            _build(inp, changed)


def test_every_advertised_output_key_is_required_and_unknown_keys_fail(base_case):
    inp, out, _bundle = base_case
    paths = (
        ("elastic",),
        ("elastic", "crack"),
        ("elastic", "crack", "candidates", 0),
        ("elastic", "crack_output"),
        ("elastic", "elements", 0),
    )
    for path in paths:
        target = out
        for item in path:
            target = target[item]
        for key in tuple(target):
            changed = copy.deepcopy(out)
            probe = changed
            for item in path:
                probe = probe[item]
            del probe[key]
            with pytest.raises(TraceValidationError):
                _build(inp, changed)
        changed = copy.deepcopy(out)
        probe = changed
        for item in path:
            probe = probe[item]
        probe["unknown_ct009_sibling"] = None
        with pytest.raises(TraceValidationError):
            _build(inp, changed)


def test_upstream_short_plane_and_long_element_stresses_are_exact(base_case):
    inp, out, _bundle = base_case
    probes = []
    changed = copy.deepcopy(out)
    plane = list(changed["elastic"]["stress_plane"])
    plane[0] = math.nextafter(plane[0], math.inf)
    changed["elastic"]["stress_plane"] = tuple(plane)
    probes.append(changed)
    changed = copy.deepcopy(out)
    changed["elastic"]["long"][0] = math.nextafter(
        changed["elastic"]["long"][0], math.inf)
    probes.append(changed)
    changed = copy.deepcopy(out)
    changed["elastic"]["elements"][0]["total_mpa"] = math.nextafter(
        changed["elastic"]["elements"][0]["total_mpa"], math.inf)
    probes.append(changed)
    for probe in probes:
        with pytest.raises(TraceValidationError, match="authoritative replay"):
            _build(inp, probe)


def test_same_law_material_ids_concrete_id_and_descriptions_change_identity(base_case):
    inp, _out, bundle = base_case
    variants = []
    changed = copy.deepcopy(inp)
    changed["concrete_material_id"] = "C30-same-law-other-id"
    variants.append(changed)
    changed = copy.deepcopy(inp)
    changed["bar_elements"][0]["description"] = "published alternate description"
    variants.append(changed)
    changed = copy.deepcopy(inp)
    item = changed["mild_material_catalog"]["items"][0]
    item["id"] = "M-SAME-LAW"
    for record in changed["bar_elements"]:
        record["material_id"] = "M-SAME-LAW"
    variants.append(changed)
    for variant in variants:
        variant_out = _candidate(variant)
        candidate = _build(variant, variant_out)
        assert candidate.to_dict() != bundle.to_dict()


def test_original_mm2_area_survives_exact_element_row_replay():
    inp = _input()
    area_mm2 = templates.bar_area(25.0)
    assert area_mm2 != (area_mm2 / 1.0e6) * 1.0e6
    bars = [(x, y, area_mm2) for x, y, _area in inp["bars"]]
    inp["bars"] = bars
    inp["section"] = Section.from_polygon(
        inp["outer"], bars, holes=inp["holes"])
    out = _candidate(inp)
    assert out["elastic"]["elements"][0]["area_mm2"] == area_mm2
    bundle = _build(inp, out)
    assert validate_crack_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) == bundle


def test_nonrectangular_holed_geometry_is_explicit_and_changes_trace(base_case):
    _inp, _out, base_bundle = base_case
    inp = _input(holed=True)
    out = _candidate(inp)
    bundle = _build(inp, out)
    assert bundle.to_dict() != base_bundle.to_dict()
    step_ids = {
        step.step_id for calculation in bundle.calculations
        for step in calculation.steps
    }
    assert any(step_id.startswith("geometry-ring-001-") for step_id in step_ids)
    assert validate_crack_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) == bundle


def test_every_published_leaf_reaches_its_member_final(base_case, dk_case):
    for bundle in (base_case[2], dk_case[2]):
        for calculation in bundle.calculations:
            by_id = {step.step_id: step for step in calculation.steps}
            pending = [calculation.final_step_id]
            reached = set()
            while pending:
                current = pending.pop()
                for dependency in by_id[current].dependencies:
                    if dependency.step_id not in reached:
                        reached.add(dependency.step_id)
                        pending.append(dependency.step_id)
            assert reached == set(by_id) - {calculation.final_step_id}


def test_short_and_long_sources_are_split_without_compliance_verdict(base_case):
    _inp, _out, bundle = base_case
    short = bundle.calculations[1]
    assert any(step.source == CT005 for step in short.steps)
    assert any(
        step.source.kind == SOURCE_PROJECT
        and step.source.method_id == "sector-long-term-cracked-state-replay"
        for step in bundle.calculations[0].steps)
    assert all(
        "pass" not in step.step_id and "utilisation" not in step.step_id
        for calculation in bundle.calculations for step in calculation.steps)


def test_inactive_and_2023_boundaries_are_deferred(base_case):
    inp, out, _bundle = base_case
    disabled = dict(inp, sls_cw=False)
    assert _build(disabled, out) is None
    plastic = dict(inp, mode="Plastic")
    assert _build(plastic, out) is None
    future = dict(inp, sls_edition="2023")
    assert _build(future, out) is None
    for key, value in (("sls_cw", 1), ("sls_dk_na", np.bool_(False))):
        malformed = dict(inp)
        malformed[key] = value
        with pytest.raises(TraceValidationError, match="exact built-in Boolean"):
            _build(malformed, out)


def test_uncracked_state_publishes_only_undefined_aggregate():
    inp = _input(moment=0.5)
    out = _candidate(inp)
    assert out["elastic"]["cracked"] is False
    bundle = _build(inp, out)
    assert len(bundle.calculations) == 1
    assert _member_id(bundle.calculations[0]) == "aggregate"
    final = bundle.calculations[0].steps[-1].result
    assert final.state == RESULT_UNDEFINED
    assert final.value is None
    assert "applicable" in final.reason.lower()


def test_nonconverged_failure_is_minimal_and_does_not_parse_failure_numerics(
    base_case, monkeypatch,
):
    inp, out, _bundle = base_case
    authoritative = crack_trace.solve_elastic_combined

    def failed_combined(*args, **kwargs):
        return dataclasses.replace(
            authoritative(*args, **kwargs), converged=False)

    monkeypatch.setattr(crack_trace, "solve_elastic_combined", failed_combined)
    changed = copy.deepcopy(out)
    elastic = changed["elastic"]
    elastic["converged"] = False
    for output in elastic["stress_outputs"].values():
        output.update(value=None, calculation_state="INVALID")
    elastic["crack_output"] = {
        "value": None,
        "case": None,
        "governing": None,
        "unit": "mm",
        "calculation_state": "INVALID",
    }
    elastic["crack"]["wk"] = math.nan
    elastic["crack_short"]["candidates"][0]["sigma_s"] = math.inf
    bundle = _build(inp, changed)
    assert len(bundle.calculations) == 1
    final = bundle.calculations[0].steps[-1].result
    assert final.state == RESULT_FAILED
    assert final.value is None
    assert "non-converged" in final.reason


def test_unrelated_top_level_families_are_inert(base_case):
    inp, out, bundle = base_case
    changed = {"plastic": {"corrupt": [object()]}, **out, "fatigue": []}
    assert _build(inp, changed) == bundle


def test_base_rejects_coarse_siblings_and_dk_requires_them(base_case, dk_case):
    inp, out, _bundle = base_case
    changed = copy.deepcopy(out)
    changed["elastic"]["crack_coarse"] = None
    with pytest.raises(TraceValidationError, match="ordered inventory"):
        _build(inp, changed)
    dk_inp, dk_out, _dk_bundle = dk_case
    changed = copy.deepcopy(dk_out)
    del changed["elastic"]["crack_coarse"]
    with pytest.raises(TraceValidationError, match="ordered inventory"):
        _build(dk_inp, changed)


def test_stale_seal_source_role_unit_and_dependency_tampering_fail(base_case):
    inp, out, bundle = base_case
    calculation = bundle.calculations[0]
    target_index = len(calculation.steps) - 1
    target = calculation.steps[target_index]
    mutations = (
        dataclasses.replace(target, quantity_role="computed_intermediate"),
        dataclasses.replace(target, source=CT005),
        dataclasses.replace(target, unit=calculation.steps[0].unit),
        dataclasses.replace(
            target,
            dependencies=target.dependencies[:-1] + (
                TraceDependency(
                    target.dependencies[-2].step_id,
                    target.dependencies[-2].unit,
                ),
            ),
        ),
    )
    for replacement in mutations:
        steps = list(calculation.steps)
        steps[target_index] = replacement
        changed_calculation = dataclasses.replace(calculation, steps=tuple(steps))
        changed_bundle = dataclasses.replace(
            bundle,
            calculations=(changed_calculation, *bundle.calculations[1:]),
            content_sha256="",
        )
        with pytest.raises(TraceValidationError):
            resealed = seal_bundle(changed_bundle)
            validate_crack_trace_family(
                resealed, inp, out, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT)
