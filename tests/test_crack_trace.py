"""CT-009 2004/base-DK oracle, contract, and adversarial tests."""

from __future__ import annotations

import copy
import dataclasses
import math
from collections.abc import Mapping

import pytest

from app import material_catalog
from sector import codes, templates
from sector.calculation_trace import (
    SOURCE_PROJECT,
    TraceDependency,
    TraceSource,
    TraceUnit,
    TraceValidationError,
    seal_bundle,
)
from sector.crack_trace import (
    _authoritative_elastic,
    _geometry_and_elements,
    _material_state,
    _validate_candidate,
    build_crack_trace_family,
    crack_trace_applicability,
    validate_crack_trace_family,
)
from sector.crack_trace_contract import (
    BRANCH_CALCULATED,
    BRANCH_FAILED,
    CANDIDATE_KEYS,
    CRACK_KEYS,
    DK_COARSE_SOURCE,
    DOC_BASE,
    DOC_DK,
    ELASTIC_CORE_KEYS,
    ELASTIC_DK_KEYS,
    ELASTIC_META_KEYS,
    ELASTIC_SERVICE_KEYS,
    ELEMENT_KEYS,
    expected_registry,
)
from sector.section import MM2_TO_M2, Section
from sector.trace_registry import audit_trace_registry


INPUT_SHA, RESULT_SHA = "a" * 64, "b" * 64
CONTEXT = {"case": "CT-009 retained crack", "row": 2}


@pytest.fixture(autouse=True)
def _isolate_autosave(monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct009-headless-no-autosave")


def _element(kind, index, point, material_id, diameter, *, mode="Diameter"):
    x, y, area = point
    return {
        "id": f"R{index + 1}" if kind == "bar" else f"P{index + 1}",
        "kind": kind,
        "x_mm": x * 1000.0,
        "y_mm": y * 1000.0,
        "area_mm2": area,
        "diameter_mm": diameter,
        "size_mode": mode,
        "material_id": material_id,
        "fatigue_detail_id": "",
        "x": x,
        "y": y,
    }


def _input(*, dk=False, tendon=False, first_area=None, long_mx=110.0,
           short_mx=35.0, **changes):
    method = codes.EC2_2005_DKNA if dk else codes.EC2_2005
    outer = [(0.0, 0.0), (0.32, 0.0), (0.32, 0.62), (0.0, 0.62)]
    area = templates.bar_area(25.0)
    bars = [
        (0.05, 0.05, area if first_area is None else first_area),
        (0.27, 0.05, area),
        (0.05, 0.57, area),
        (0.27, 0.57, area),
    ]
    tendons = [(0.16, 0.09, 780.0)] if tendon else []
    mild_entry = material_catalog.default_entry(
        "mild", material_id="M1", preset=method.label
    )
    mild_entry.update(name="Crack-control bars", description="CT-009 selected mild law")
    prestress_entry = material_catalog.default_entry(
        "prestress", material_id="P1", preset=codes.EC2_2005.label
    )
    prestress_entry.update(
        name="Bonded tendon", description="CT-009 selected tendon law", IS=0.0042
    )
    steel = material_catalog.build_material(mild_entry, "mild")
    prestress = material_catalog.build_material(prestress_entry, "prestress")
    bar_elements = [
        _element(
            "bar", index, point, "M1",
            25.0 if index or first_area is None else math.sqrt(4.0 * point[2] / math.pi),
            mode="Diameter" if index or first_area is None else "Independent",
        )
        for index, point in enumerate(bars)
    ]
    tendon_elements = [
        _element("tendon", index, point, "P1", math.sqrt(4.0 * point[2] / math.pi))
        for index, point in enumerate(tendons)
    ]
    ec, creep = 34.0, 1.2
    inp = {
        "mode": "Elastic", "sls_cw": True, "sls_edition": "2004",
        "sls_dk_na": dk,
        "sls_code": "DS/EN 1992-1-1 + DK NA" if dk else "EN 1992-1-1:2005",
        "sls_member": "Beam",
        "outer": outer, "holes": [], "bars": bars, "tendons": tendons,
        "section": Section.from_polygon(outer, bars, tendons_xy_area_mm2=tendons),
        "bar_elements": bar_elements, "tendon_elements": tendon_elements,
        "mild_material_catalog": {"version": 1, "next_id": 2, "items": [mild_entry]},
        "prestress_material_catalog": {
            "version": 1, "next_id": 2, "items": [prestress_entry]
        },
        "bar_materials": [steel] * len(bars),
        "tendon_materials": [prestress] * len(tendons),
        "concrete": method.concrete(35.0), "steel": steel,
        "prestress": prestress if tendons else None,
        "concrete_preset": method.label, "mild_preset": method.label,
        "prestress_preset": codes.EC2_2005.label,
        "concrete_material_id": "C35-selected",
        "P_pl": 0.0, "Mx_pl": 0.0, "My_pl": 0.0,
        "P_el_l": 0.0, "Mx_el_l": long_mx, "My_el_l": 0.0,
        "P_el_s": 0.0, "Mx_el_s": short_mx, "My_el_s": 0.0,
        "conc_Ec": ec, "el_phi": creep,
        "ns": 200_000.0 / (ec * 1000.0),
        "nl": 200_000.0 * (1.0 + creep) / (ec * 1000.0),
        "sls_fctm": 3.2, "sls_phi": 0.0, "sls_k1": 0.8,
        "sls_tendon_xi": 0.7 if tendons else 0.0,
    }
    inp.update(changes)
    return inp


def _candidate(inp):
    folded, bars, tendons, geometry = _geometry_and_elements(inp)
    _blocks, bar_laws, tendon_laws, names, _identity = _material_state(inp, geometry)
    return {
        "elastic": _authoritative_elastic(
            inp, folded, bars, tendons, bar_laws, tendon_laws, names
        )
    }


def _bundle(inp, out=None):
    return build_crack_trace_family(
        inp, _candidate(inp) if out is None else out,
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA, context=CONTEXT,
    )


def _steps(bundle):
    return {step.step_id: step for step in bundle.calculations[0].steps}


@pytest.mark.parametrize("dk,expected_cases", [
    (False, "long,short"),
    (True, "long-fine,short-fine,long-coarse,short-coarse"),
])
def test_base_and_dk_roundtrip_have_exact_order_axes_and_registry(dk, expected_cases):
    inp = _input(dk=dk)
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    assert validate_crack_trace_family(
        bundle.to_dict(), inp, out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT,
    ) == bundle
    axes = {axis.name: axis.value for axis in bundle.calculations[0].axes}
    assert axes["case_order"] == expected_cases
    assert axes["dk_na"] == str(dk).lower()
    assert axes["branch"] == BRANCH_CALCULATED
    evidence_shape = __import__("sector.crack_trace", fromlist=["_replay"])._replay(
        inp, out, CONTEXT
    ).shape
    audit_trace_registry(bundle, expected_registry(evidence_shape))
    elastic = out["elastic"]
    expected = (*ELASTIC_CORE_KEYS, *ELASTIC_SERVICE_KEYS, *ELASTIC_META_KEYS)
    if dk:
        expected += ELASTIC_DK_KEYS
    assert tuple(elastic) == (*expected, "crack_output")


def test_independent_2004_formula_oracle_matches_every_base_candidate():
    inp = _input()
    elastic = _candidate(inp)["elastic"]
    es = inp["bar_materials"][0].Es
    for key, ratio, kt in (("crack", inp["nl"], 0.4),
                           ("crack_short", inp["ns"], 0.6)):
        for candidate in elastic[key]["candidates"]:
            sigma, rho = candidate["sigma_s"], candidate["rho_p_eff"]
            strain = max(
                (sigma - kt * inp["sls_fctm"] / rho * (1.0 + ratio * rho)) / es,
                0.6 * sigma / es,
            )
            assert candidate["esm_ecm"] == pytest.approx(strain, rel=1e-13)
            assert candidate["wk"] == pytest.approx(
                candidate["sr_max"] * strain, rel=1e-13
            )
    assert elastic["crack_output"]["value"] == max(
        elastic["crack"]["wk"], elastic["crack_short"]["wk"]
    )


@pytest.mark.parametrize("dk,tendon", [(False, False), (True, True)])
def test_retained_app_payload_matches_independent_trace_reconstruction(dk, tendon):
    from app.sector_app import _run_single_analysis

    inp = _input(dk=dk, tendon=tendon)
    inp.update(
        minimum_reinforcement_on=False,
        transverse_detailing_on=False,
        shear_on=False,
        torsion_on=False,
        combined_on=False,
    )
    retained = _run_single_analysis(inp)["elastic"]
    expected = _candidate(inp)["elastic"]
    _validate_candidate(retained, expected, BRANCH_CALCULATED)


def test_dk_coarse_source_and_width_scale_are_exact_and_not_cross_cited():
    inp = _input(dk=True)
    out = _candidate(inp)
    steps = _steps(_bundle(inp, out))
    assert steps["method-coarse-width-scale"].result.value == 0.5
    assert steps["case-long-coarse-governing-width"].source == DK_COARSE_SOURCE
    documents = {
        step.source.citation.document
        for step in steps.values() if step.source.citation is not None
    }
    assert documents == {DOC_BASE, DOC_DK}
    assert out["elastic"]["crack_coarse"]["coarse"] is True
    assert out["elastic"]["crack"]["coarse"] is False


def _nodes(value, path=()):
    if isinstance(value, Mapping):
        yield path, tuple(value)
        for key in value:
            yield from _nodes(value[key], (*path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _nodes(item, (*path, index))


def _leaves(value, path=()):
    if isinstance(value, Mapping):
        for key in value:
            yield from _leaves(value[key], (*path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _leaves(item, (*path, index))
    else:
        yield path, value


def _at(value, path):
    for key in path:
        value = value[key]
    return value


def _replace(value, path, replacement):
    if not path:
        return replacement
    key, *tail = path
    clone = dict(value) if isinstance(value, Mapping) else list(value)
    clone[key] = _replace(clone[key], tail, replacement)
    return tuple(clone) if isinstance(value, tuple) else clone


def _mutation(value):
    if type(value) is bool:
        return not value
    if type(value) is str:
        return value + "-tampered"
    if value is None:
        return 0.0
    if type(value) is int:
        return value + 1
    number = float(value)
    return math.nextafter(number, math.inf) if math.isfinite(number) else 0.0


def test_every_retained_payload_key_order_cardinality_type_and_leaf_is_pinned():
    expected = _candidate(_input(dk=True, tendon=True))["elastic"]
    for path, keys in list(_nodes(expected)):
        for key in keys:
            changed = copy.deepcopy(expected)
            del _at(changed, path)[key]
            with pytest.raises(TraceValidationError):
                _validate_candidate(changed, expected, BRANCH_CALCULATED)
        if len(keys) > 1:
            changed = copy.deepcopy(expected)
            target = _at(changed, path)
            reversed_items = [(key, target[key]) for key in reversed(keys)]
            target.clear(); target.update(reversed_items)
            with pytest.raises(TraceValidationError):
                _validate_candidate(changed, expected, BRANCH_CALCULATED)
    for path, value in list(_leaves(expected)):
        changed = _replace(copy.deepcopy(expected), path, _mutation(value))
        with pytest.raises(TraceValidationError):
            _validate_candidate(changed, expected, BRANCH_CALCULATED)


def test_crack_and_element_row_inventories_are_independently_frozen():
    elastic = _candidate(_input(tendon=True))["elastic"]
    assert all(tuple(row) == ELEMENT_KEYS for row in elastic["elements"])
    for crack_key in ("crack", "crack_short"):
        assert tuple(elastic[crack_key]) == CRACK_KEYS
        assert all(tuple(row) == CANDIDATE_KEYS
                   for row in elastic[crack_key]["candidates"])
    assert [row["element_type"] for row in elastic["elements"]][-1] == "Tendon"
    assert elastic["elements"][-1]["element_id"] == "P1"


@pytest.mark.parametrize("area", [templates.bar_area(25.0), 0.1])
def test_original_mm2_area_uses_exact_section_multiplication_and_reaches_output(area):
    inp = _input(first_area=area)
    out = _candidate(inp)
    retained = out["elastic"]["elements"][0]["area_mm2"]
    assert retained == area
    assert math.copysign(1.0, retained) == math.copysign(1.0, area)
    assert inp["section"].bars[0].area == area * MM2_TO_M2
    bundle = _bundle(inp, out)
    area_steps = [
        step for step in bundle.calculations[0].steps
        if "u617265615f6d6d32-number" in step.step_id
    ]
    assert any(step.result.value == area for step in area_steps)


def test_complete_material_id_name_description_and_concrete_identity_are_sealed():
    inp = _input()
    out = _candidate(inp)
    baseline = _bundle(inp, out)
    variants = []
    changed = copy.deepcopy(inp)
    changed["concrete_material_id"] = "C35-same-law-other-id"
    variants.append((changed, out))
    changed = copy.deepcopy(inp)
    changed["mild_material_catalog"]["items"][0]["description"] = "changed description"
    variants.append((changed, out))
    changed = copy.deepcopy(inp)
    changed["bar_elements"][0]["id"] = "RX"
    variants.append((changed, None))
    for changed, retained in variants:
        changed_out = _candidate(changed) if retained is None else retained
        rebuilt = _bundle(changed, changed_out)
        assert rebuilt.to_dict() != baseline.to_dict()
        with pytest.raises(TraceValidationError):
            validate_crack_trace_family(
                baseline, changed, changed_out, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT,
            )


def test_geometry_hole_actions_diameters_and_member_all_reach_final():
    inp = _input(dk=True)
    baseline = _bundle(inp)
    variants = []
    for key, value in (("Mx_el_l", 111.0), ("sls_phi", 18.0), ("sls_member", "Slab")):
        changed = copy.deepcopy(inp); changed[key] = value; variants.append(changed)
    holed = copy.deepcopy(inp)
    holed["holes"] = [[(0.13, 0.25), (0.19, 0.25), (0.19, 0.37), (0.13, 0.37)]]
    holed["section"] = Section.from_polygon(
        holed["outer"], holed["bars"], holed["holes"]
    )
    variants.append(holed)
    assert all(_bundle(item).to_dict() != baseline.to_dict() for item in variants)


def test_uncracked_branch_publishes_only_undefined_final():
    uncracked = _input(long_mx=0.1, short_mx=0.0)
    out = _candidate(uncracked)
    bundle = _bundle(uncracked, out)
    assert out["elastic"]["cracked"] is False
    assert bundle.calculations[0].steps[-1].result.state == "undefined"
    assert out["elastic"]["crack_output"]["calculation_state"] == "NOT APPLICABLE"


def test_nonconverged_branch_is_failure_first_and_failure_numerics_are_inert(monkeypatch):
    import sector.crack_trace as module

    original = module.solve_elastic_combined

    def nonconverged(*args, **kwargs):
        return dataclasses.replace(original(*args, **kwargs), converged=False)

    monkeypatch.setattr(module, "solve_elastic_combined", nonconverged)
    inp = _input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    assert bundle.calculations[0].steps[-1].result.state == "failed"
    assert {axis.name: axis.value for axis in bundle.calculations[0].axes}["branch"] == BRANCH_FAILED
    changed = copy.deepcopy(out)
    changed["elastic"]["max_conc"] = math.nan
    changed["elastic"]["total"][0] = math.inf
    assert _bundle(inp, changed).to_dict() == bundle.to_dict()
    promoted = copy.deepcopy(out)
    promoted["elastic"]["converged"] = True
    with pytest.raises(TraceValidationError):
        _bundle(inp, promoted)


def test_unrelated_result_families_and_excluded_fatigue_assignment_are_inert():
    inp = _input()
    out = _candidate(inp)
    baseline = _bundle(inp, out).to_dict()
    unrelated = copy.deepcopy(out)
    unrelated.update(plastic={"util": math.nan}, shear=[1, 2, 3], fatigue=object())
    assert _bundle(inp, unrelated).to_dict() == baseline
    excluded = copy.deepcopy(inp)
    excluded["bar_elements"][0]["fatigue_detail_id"] = "F-unrelated"
    assert _bundle(excluded, out).to_dict() == baseline


@pytest.mark.parametrize("key,value,match", [
    ("mode", 1, "mode"),
    ("sls_cw", 1, "Boolean"),
    ("sls_dk_na", [], "Boolean"),
    ("sls_edition", 2004, "text"),
])
def test_applicability_types_fail_closed_before_family_filtering(key, value, match):
    inp = _input(); inp[key] = value
    with pytest.raises(TraceValidationError, match=match):
        crack_trace_applicability(inp)


def test_inactive_and_2023_sibling_boundaries_are_explicitly_absent():
    for changes in (
        {"mode": "Plastic"}, {"sls_cw": False},
        {"sls_edition": "2023", "sls_code": "EN 1992-1-1:2023"},
    ):
        inp = _input(**changes)
        assert build_crack_trace_family(
            inp, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        ) is None
        assert validate_crack_trace_family(
            None, inp, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        ) is None


def test_every_graph_leaf_reaches_final_and_resealed_graph_source_unit_tamper_fails():
    inp, out = _input(dk=True), None
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    calculation = bundle.calculations[0]
    by_id = {step.step_id: step for step in calculation.steps}
    reached, pending = set(), [calculation.final_step_id]
    while pending:
        step_id = pending.pop(); reached.add(step_id)
        pending.extend(
            dependency.step_id for dependency in by_id[step_id].dependencies
            if dependency.step_id not in reached
        )
    assert reached == set(by_id)

    target_index = next(
        index for index, step in enumerate(calculation.steps)
        if step.step_id == "case-long-fine-governing-width"
    )
    target = calculation.steps[target_index]
    candidates = []
    changed_steps = list(calculation.steps)
    changed_steps[target_index] = dataclasses.replace(
        target, source=TraceSource(SOURCE_PROJECT, "alternate-project-method")
    )
    candidates.append(dataclasses.replace(calculation, steps=tuple(changed_steps)))
    unit = TraceUnit("MPa", "stress")
    unit_steps = tuple(
        dataclasses.replace(
            step,
            unit=unit if step.step_id == target.step_id else step.unit,
            dependencies=tuple(
                TraceDependency(
                    dependency.step_id,
                    unit if dependency.step_id == target.step_id else dependency.unit,
                )
                for dependency in step.dependencies
            ),
        )
        for step in calculation.steps
    )
    candidates.append(dataclasses.replace(calculation, steps=unit_steps))
    changed_steps = list(calculation.steps)
    changed_steps[target_index] = dataclasses.replace(
        target, dependencies=target.dependencies[:-1]
    )
    candidates.append(dataclasses.replace(calculation, steps=tuple(changed_steps)))
    for candidate in candidates:
        with pytest.raises(TraceValidationError):
            tampered = seal_bundle(dataclasses.replace(bundle, calculations=(candidate,)))
            validate_crack_trace_family(
                tampered, inp, out, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT,
            )


def test_stale_hashes_and_coherently_resealed_final_value_are_rejected():
    inp, out = _input(), None
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    final = bundle.calculations[0].steps[-1]
    changed = dataclasses.replace(
        final,
        result=dataclasses.replace(final.result, value=final.result.value + 0.001),
    )
    calculation = dataclasses.replace(
        bundle.calculations[0],
        steps=(*bundle.calculations[0].steps[:-1], changed),
    )
    tampered = seal_bundle(dataclasses.replace(bundle, calculations=(calculation,)))
    for candidate, input_sha, result_sha in (
        (tampered, INPUT_SHA, RESULT_SHA),
        (bundle, "c" * 64, RESULT_SHA),
        (bundle, INPUT_SHA, "d" * 64),
    ):
        with pytest.raises(TraceValidationError):
            validate_crack_trace_family(
                candidate, inp, out, input_sha256=input_sha,
                result_sha256=result_sha, context=CONTEXT,
            )


def test_no_compliance_verdict_limit_or_allowable_width_is_published():
    inp, out = _input(dk=True), None
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    assert not {"limit", "util", "status", "verdict"} & set(out["elastic"]["crack_output"])
    serialized = str(bundle.to_dict()).lower()
    assert "compliance verdict" in serialized  # explicit exclusion assumption only
