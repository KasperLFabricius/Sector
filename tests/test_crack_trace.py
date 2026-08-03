"""CT-009 2004 base/building-DK oracles and adversarial closure tests."""

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
from sector import codes
from sector.calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_UNDEFINED,
    SOURCE_INPUT,
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    TraceResult,
    TraceSource,
    TraceUnit,
    TraceValidationError,
    bundle_from_json,
    bundle_to_json,
    seal_bundle,
)
from sector.crack_trace import (
    build_crack_trace_family,
    validate_crack_trace_family,
)
from sector.materials import Prestress
from sector.section import Section
from tests.test_section_trace_blocks import _catalog_item


INPUT_SHA = "3" * 64
RESULT_SHA = "4" * 64
CONTEXT = {"case": "ct009-base", "stage": 1}
DK_CODE = "DS/EN 1992-1-1 + DK NA"


@pytest.fixture(autouse=True)
def _isolate_autosave(monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct009-headless-no-autosave")


def _record(
    element_id: str,
    x: float,
    y: float,
    area: float,
    *,
    kind: str = "bar",
    material_id: str = "M1",
    size_mode: str = "Area",
) -> dict:
    diameter = math.sqrt(4.0 * area / math.pi)
    return {
        "id": element_id,
        "kind": kind,
        "x_mm": x * 1000.0,
        "y_mm": y * 1000.0,
        "area_mm2": area,
        "diameter_mm": diameter,
        "size_mode": size_mode,
        "material_id": material_id,
        "fatigue_detail_id": "FAT-160",
        "x": x,
        "y": y,
    }


def _input(
    *, empty: bool = False, independent: bool = False,
    with_tendon: bool = False, **changes,
) -> dict:
    outer = [(0.0, 0.0), (0.30, 0.0), (0.30, 0.60), (0.0, 0.60)]
    bars = [] if empty else [(0.06, 0.05, 500.0), (0.24, 0.05, 500.0)]
    tendons = [(0.15, 0.10, 780.0)] if with_tendon else []
    section = Section.from_polygon(outer, bars, tendons_xy_area_mm2=tendons)
    steel = codes.EC2_2005.steel(500.0)
    prestress = Prestress(curve=1, IS=0.004, Es=195_000.0)
    mild_item = _catalog_item("M1", codes.EC2_2005.label, steel)
    mild_item.update(name="B500B", description="Ribbed reinforcement")
    prestress_item = _catalog_item("P1", "Custom / imported", prestress)
    prestress_item.update(name="Y1860", description="Bonded tendon")
    records = [
        _record(
            f"B{position}",
            x,
            y,
            area,
            size_mode="Independent" if independent else "Area",
        )
        for position, (x, y, area) in enumerate(bars, start=1)
    ]
    ec_gpa = 34.0
    creep = 2.0
    inp = {
        "mode": "Elastic",
        "section": section,
        "outer": outer,
        "holes": [],
        "bars": bars,
        "tendons": tendons,
        "concrete": codes.EC2_2005.concrete(35.0),
        "steel": steel,
        "prestress": prestress,
        "bar_materials": [steel] * len(bars),
        "tendon_materials": [prestress] * len(tendons),
        "concrete_preset": codes.EC2_2005.label,
        "mild_preset": codes.EC2_2005.label,
        "prestress_preset": "Custom / imported",
        "concrete_material_id": "C35-main",
        "mild_material_catalog": {
            "version": 1,
            "next_id": 2,
            "items": [mild_item],
        },
        "prestress_material_catalog": {
            "version": 1,
            "next_id": 2,
            "items": [prestress_item] if with_tendon else [],
        },
        "bar_elements": records,
        "tendon_elements": [
            _record(
                f"T{position}", x, y, area,
                kind="tendon", material_id="P1",
            )
            for position, (x, y, area) in enumerate(tendons, start=1)
        ],
        "P_el_l": 0.0,
        "Mx_el_l": 260.0,
        "My_el_l": 0.0,
        "P_el_s": 0.0,
        "Mx_el_s": 90.0,
        "My_el_s": 0.0,
        "conc_Ec": ec_gpa,
        "el_phi": creep,
        "ns": 200_000.0 / (ec_gpa * 1000.0),
        "nl": 200_000.0 * (1.0 + creep) / (ec_gpa * 1000.0),
        "sls_fctm": 3.2,
        "sls_cw": True,
        "sls_phi": 0.0,
        "sls_k1": 0.8,
        "sls_tendon_xi": 0.0,
        "sls_code": "EN 1992-1-1:2005",
        "sls_edition": "2004",
        "sls_dk_na": False,
        "sls_member": "Beam",
    }
    inp.update(changes)
    return inp


def _output(inp: dict) -> dict:
    """Use the retained application adapter as the candidate-output oracle."""

    original = sector_app._run_capacity_checks
    sector_app._run_capacity_checks = lambda _inp, _out: None
    try:
        return sector_app._run_single_analysis(inp)
    finally:
        sector_app._run_capacity_checks = original


def _bundle(inp=None, out=None, context=None):
    inp = _input() if inp is None else inp
    out = _output(inp) if out is None else out
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT if context is None else context,
    )
    return inp, out, bundle


def _dk_input(**changes):
    values = dict(sls_code=DK_CODE, sls_dk_na=True)
    values.update(changes)
    return _input(**values)


def _reachable(calculation):
    by_id = {step.step_id: step for step in calculation.steps}
    seen = set()
    pending = [calculation.final_step_id]
    while pending:
        step_id = pending.pop()
        if step_id in seen:
            continue
        seen.add(step_id)
        pending.extend(
            dependency.step_id for dependency in by_id[step_id].dependencies
        )
    return seen


def _leaf_paths(value, prefix=()):
    if type(value) is dict:
        for key, item in value.items():
            yield from _leaf_paths(item, (*prefix, key))
    elif type(value) in {list, tuple}:
        for index, item in enumerate(value):
            yield from _leaf_paths(item, (*prefix, index))
    else:
        yield prefix


def _change_leaf(value):
    if value is None:
        return "tampered-none"
    if type(value) is bool:
        return not value
    if type(value) is int:
        return value + 1
    if type(value) is float:
        return float(np.nextafter(value, math.inf))
    if type(value) is str:
        return value + "-tampered"
    raise AssertionError(f"unhandled hostile leaf type {type(value)!r}")


def _mutate_path(value, path):
    target = value
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = _change_leaf(target[path[-1]])


def test_application_oracle_round_trip_graph_sources_units_and_formula():
    inp, out, bundle = _bundle()
    assert out["elastic"]["crack"]["wk"] > 0.0
    assert len(bundle.calculations) == 3
    assert bundle_from_json(bundle_to_json(bundle)) == bundle
    assert validate_crack_trace_family(
        bundle,
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    ) == bundle

    assert [item.axes[-1].value for item in bundle.calculations[:2]] == [
        "fine",
        "fine",
    ]
    for calculation in bundle.calculations:
        assert _reachable(calculation) == {step.step_id for step in calculation.steps}
        assert calculation.steps[-1].quantity_role == "final_result"
    first = bundle.calculations[0]
    candidates = [
        item
        for item in first.steps
        if item.step_id.startswith("candidate-") and item.step_id.endswith("-wk")
    ]
    assert first.steps[-1].result.value == max(item.result.value for item in candidates)
    payload = out["elastic"]["crack"]
    assert payload["wk"] == pytest.approx(payload["sr_max"] * payload["esm_ecm"])

    sources = {step.source.kind for calculation in bundle.calculations for step in calculation.steps}
    assert sources == {SOURCE_INPUT, SOURCE_PROJECT, SOURCE_STANDARD}
    plane_units = {
        step.step_id: step.unit.symbol
        for step in first.steps
        if step.step_id.startswith("cracked-state-")
    }
    assert plane_units == {
        "cracked-state-q0": "kN/m2",
        "cracked-state-qx": "kN/m3",
        "cracked-state-qy": "kN/m3",
    }
    standard_methods = {
        step.source.method_id
        for calculation in bundle.calculations
        for step in calculation.steps
        if step.source.kind == SOURCE_STANDARD
    }
    assert {
        "en-1992-1-1-2004-effective-tension-area",
        "en-1992-1-1-2004-mean-strain-difference",
        "en-1992-1-1-2004-close-centre-crack-spacing",
        "en-1992-1-1-2004-crack-width",
    }.issubset(standard_methods)
    assert all(
        step.source.edition == "2004"
        and step.source.citation is not None
        and step.source.citation.document
        == "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010"
        for calculation in bundle.calculations
        for step in calculation.steps
        if step.source.kind == SOURCE_STANDARD
    )


def test_retained_application_tendon_payload_replays_with_exact_catalogue_id():
    inp = _input(with_tendon=True)
    out = _output(inp)
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"case": "tendon"},
    )
    assert bundle is not None
    assert out["elastic"]["prestress"] is not None
    assert any(
        candidate["element_type"] == "Tendon"
        for case in (out["elastic"]["crack"], out["elastic"]["crack_short"])
        for candidate in case["candidates"]
    )


def test_wide_spacing_branch_cites_expression_7_14():
    inp = _input()
    inp["outer"] = [(0.0, 0.0), (1.0, 0.0), (1.0, 0.60), (0.0, 0.60)]
    inp["bars"] = [(0.05, 0.05, 500.0), (0.95, 0.05, 500.0)]
    for record, (x, y, area) in zip(inp["bar_elements"], inp["bars"]):
        record.update(x=x, y=y, x_mm=x * 1000.0, y_mm=y * 1000.0,
                      area_mm2=area)
    inp["section"] = Section.from_polygon(inp["outer"], inp["bars"])
    _inp, _out, bundle = _bundle(inp=inp)
    assert any(
        step.source.method_id == "en-1992-1-1-2004-wide-spacing-crack-spacing"
        and step.source.citation.clause == "7.3.4(4)"
        for calculation in bundle.calculations
        for step in calculation.steps
    )


@pytest.mark.parametrize(
    "edition,dk_na",
    [("2023", False), ("2004", True)],
)
def test_type_valid_mismatched_base_selectors_are_inactive(edition, dk_na):
    inp = _input(sls_edition=edition, sls_dk_na=dk_na)
    assert build_crack_trace_family(
        inp,
        {},
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    ) is None


@pytest.mark.parametrize(
    "code,edition,dk_na",
    [
        ("EN 1992-1-1:2023", "2023", False),
        ("DS/EN 1992-2:2005 + AC:2008", "2004", False),
        ("DS/EN 1992-1-1 + DK NA", "2004", False),
    ],
)
def test_other_current_code_branches_are_inactive(code, edition, dk_na):
    inp = _input(sls_code=code, sls_edition=edition, sls_dk_na=dk_na)
    assert build_crack_trace_family(
        inp,
        {},
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    ) is None


def test_building_dk_round_trip_order_registry_and_exact_output():
    inp = _dk_input()
    out = _output(inp)
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"route": "building-dk"},
    )
    assert bundle is not None
    assert len(bundle.calculations) == 5
    assert [
        dict((axis.name, axis.value) for axis in item.axes)["crack_case"]
        for item in bundle.calculations
    ] == [
        "long-term-fine",
        "short-term-fine",
        "long-term-coarse",
        "short-term-coarse",
        "aggregate",
    ]
    assert tuple(
        key for key in out["elastic"] if key.startswith("crack")
    ) == (
        "cracked",
        "crack",
        "crack_short",
        "crack_code",
        "crack_edition",
        "crack_member",
        "crack_coarse",
        "crack_short_coarse",
        "crack_output",
    )
    assert validate_crack_trace_family(
        bundle,
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"route": "building-dk"},
    ) == bundle


def test_building_dk_routes_and_member_rule_bind_selecting_identities():
    inp = _dk_input()
    bundle = build_crack_trace_family(
        inp,
        _output(inp),
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    )
    for calculation in bundle.calculations:
        reachable = _reachable(calculation)
        input_ids = {
            step.step_id
            for step in calculation.steps
            if step.step_id.startswith("input-") and "-sha256-" in step.step_id
        }
        route_steps = tuple(
            step
            for step in calculation.steps
            if step.step_id.startswith("route-building-dk-")
        )
        assert input_ids and len(route_steps) == 2
        assert all(
            step.step_id in reachable
            and step.quantity_role == "computed_intermediate"
            and {dependency.step_id for dependency in step.dependencies}
            == input_ids
            for step in route_steps
        )
        assert {step.source.method_id for step in route_steps} == {
            "en-1992-1-1-2004-crack-width-route",
            "dk-na-2024-crack-width-route",
        }
        rules = tuple(
            step
            for step in calculation.steps
            if step.step_id == "case-fine-effective-height-rule"
        )
        if rules:
            assert len(rules) == 1
            assert rules[0].quantity_role == "computed_intermediate"
            assert {
                dependency.step_id for dependency in rules[0].dependencies
            } == input_ids


def test_building_dk_fine_coarse_formulas_and_sources_are_exact():
    inp = _dk_input()
    out = _output(inp)
    bundle = build_crack_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
    )
    for fine_key, coarse_key in (
        ("crack", "crack_coarse"),
        ("crack_short", "crack_short_coarse"),
    ):
        fine = out["elastic"][fine_key]
        coarse = out["elastic"][coarse_key]
        assert fine["wk"] == pytest.approx(fine["sr_max"] * fine["esm_ecm"])
        assert coarse["wk"] == pytest.approx(
            0.5 * coarse["sr_max"] * coarse["esm_ecm"]
        )
        assert fine["coarse"] is False
        assert coarse["coarse"] is True
    assert any(
        step.source.method_id == "dk-na-2024-effective-tension-area-fine"
        for step in bundle.calculations[0].steps
    )
    assert any(
        step.source.method_id == "dk-na-2024-effective-tension-area-coarse"
        for step in bundle.calculations[2].steps
    )
    assert any(
        step.source.method_id == "dk-na-2024-coarse-crack-width"
        for step in bundle.calculations[2].steps
    )
    coefficient = next(
        step
        for step in bundle.calculations[0].steps
        if step.step_id.endswith("cover-coefficient")
    )
    cover = out["elastic"]["crack"]["candidates"][0]["cover"]
    assert coefficient.result.value == pytest.approx(
        3.4 * (25.0 / cover) ** (2.0 / 3.0)
    )
    assert len(coefficient.dependencies) == 1
    assert coefficient.dependencies[0].step_id.endswith("-cover")
    spacing = next(
        step
        for step in bundle.calculations[0].steps
        if step.step_id.endswith("-sr-max")
    )
    assert coefficient.step_id in {
        dependency.step_id for dependency in spacing.dependencies
    }


def test_building_dk_member_and_tendon_rules_are_active_but_xi_is_inert():
    beam = _dk_input(sls_member="Beam")
    slab = _dk_input(sls_member="Slab")
    beam_bundle = build_crack_trace_family(
        beam, _output(beam), input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
    )
    slab_bundle = build_crack_trace_family(
        slab, _output(slab), input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
    )
    assert beam_bundle != slab_bundle
    beam_rule = next(
        step for step in beam_bundle.calculations[0].steps
        if step.step_id == "case-fine-effective-height-rule"
    )
    slab_rule = next(
        step for step in slab_bundle.calculations[0].steps
        if step.step_id == "case-fine-effective-height-rule"
    )
    assert beam_rule.result.value == 0.0
    assert slab_rule.result.value == 1.0

    tendon = _dk_input(with_tendon=True, sls_member="Beam")
    tendon_changed = copy.deepcopy(tendon)
    tendon_changed["sls_tendon_xi"] = 0.75
    first_out = _output(tendon)
    second_out = _output(tendon_changed)
    first = build_crack_trace_family(
        tendon, first_out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
    )
    second = build_crack_trace_family(
        tendon_changed,
        second_out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    )
    tendon_rule = next(
        step for step in first.calculations[0].steps
        if step.step_id == "case-fine-effective-height-rule"
    )
    assert tendon_rule.result.value == 1.0
    assert first == second

    invalid = _dk_input(sls_member="Column")
    with pytest.raises(TraceValidationError, match="Beam or Slab"):
        build_crack_trace_family(
            invalid,
            {},
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )

    wrong_xi = _dk_input(sls_tendon_xi=[])
    with pytest.raises(TraceValidationError, match="retain built-in numeric"):
        build_crack_trace_family(
            wrong_xi,
            {},
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )
    missing_xi = _dk_input()
    del missing_xi["sls_tendon_xi"]
    with pytest.raises(TraceValidationError, match="requires sls_tendon_xi"):
        build_crack_trace_family(
            missing_xi,
            {},
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_unreinforced_building_dk_has_four_undefined_cases_and_aggregate():
    inp = _dk_input(empty=True, Mx_el_l=0.0, Mx_el_s=0.0)
    out = _output(inp)
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    )
    assert [item.steps[-1].result.state for item in bundle.calculations] == [
        RESULT_UNDEFINED,
        RESULT_UNDEFINED,
        RESULT_UNDEFINED,
        RESULT_UNDEFINED,
        RESULT_UNDEFINED,
    ]


def test_every_building_dk_owned_leaf_is_independently_reconstructed():
    inp = _dk_input()
    out = _output(inp)
    owned = {
        key: value
        for key, value in out["elastic"].items()
        if key == "converged"
        or key.startswith("crack")
        or key.startswith(
            ("lambda_cr", "sigma_ct", "fctm", "show_cw", "props_")
        )
    }
    paths = tuple(_leaf_paths(owned))
    assert paths
    for path in paths:
        changed = copy.deepcopy(out)
        _mutate_path(changed["elastic"], path)
        with pytest.raises(TraceValidationError):
            build_crack_trace_family(
                inp,
                changed,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )


def test_building_dk_output_inventory_missing_unknown_and_reordered_is_rejected():
    inp = _dk_input()
    out = _output(inp)
    mutations = []
    missing = copy.deepcopy(out)
    del missing["elastic"]["crack_coarse"]
    mutations.append(missing)
    unknown = copy.deepcopy(out)
    unknown["elastic"]["crack_future"] = None
    mutations.append(unknown)
    reordered = copy.deepcopy(out)
    elastic = reordered["elastic"]
    reordered["elastic"] = {
        key: elastic[key] for key in reversed(tuple(elastic))
    }
    mutations.append(reordered)
    for changed in mutations:
        with pytest.raises(TraceValidationError, match="inventory|sibling"):
            build_crack_trace_family(
                inp,
                changed,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )


def test_fresh_unknown_reordered_and_missing_element_schema_is_rejected():
    inp = _input()
    out = _output(inp)
    for mutation in ("unknown", "reordered", "missing"):
        changed = copy.deepcopy(inp)
        record = changed["bar_elements"][0]
        if mutation == "unknown":
            record["future"] = 1
        elif mutation == "reordered":
            changed["bar_elements"][0] = {
                key: record[key] for key in reversed(tuple(record))
            }
        else:
            del record["fatigue_detail_id"]
        with pytest.raises(TraceValidationError, match="exact current schema|current schema"):
            build_crack_trace_family(
                changed,
                out,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )


@pytest.mark.parametrize("area", [0.0, -500.0])
def test_independent_area_and_diameter_are_separately_positive(area):
    inp = _input(independent=True)
    inp["bars"][0] = (*inp["bars"][0][:2], area)
    inp["bar_elements"][0]["area_mm2"] = area
    inp["section"] = Section.from_polygon(inp["outer"], inp["bars"])
    with pytest.raises(TraceValidationError, match="positive finite"):
        build_crack_trace_family(
            inp,
            {},
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_near_equal_duplicate_geometry_is_rejected_exactly():
    inp = _input()
    inp["bar_elements"][0]["x"] = float(np.nextafter(
        inp["bar_elements"][0]["x"], math.inf
    ))
    with pytest.raises(TraceValidationError, match="stale"):
        build_crack_trace_family(
            inp,
            {},
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_success_sibling_inventory_order_and_recursive_type_reach_bundle():
    inp, out, bundle = _bundle()
    mutations = []

    missing = copy.deepcopy(out)
    del missing["elastic"]["total"]
    mutations.append(missing)

    extra = copy.deepcopy(out)
    extra["elastic"]["future_sibling"] = 1
    mutations.append(extra)

    reordered = copy.deepcopy(out)
    elastic = reordered["elastic"]
    reordered["elastic"] = {
        key: elastic[key] for key in reversed(tuple(elastic))
    }
    mutations.append(reordered)

    changed_type = copy.deepcopy(out)
    changed_type["elastic"]["elements"] = tuple(changed_type["elastic"]["elements"])
    mutations.append(changed_type)

    nested_type = copy.deepcopy(out)
    nested_type["elastic"]["stress_outputs"]["reinforcement"]["value"] = "same-value"
    mutations.append(nested_type)

    for changed in mutations:
        with pytest.raises(TraceValidationError):
            validate_crack_trace_family(
                bundle,
                inp,
                changed,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
                context=CONTEXT,
            )


def test_success_sibling_values_are_inert_when_recursive_type_is_retained():
    inp, out, first = _bundle()
    changed = copy.deepcopy(out)
    changed["elastic"]["total"] = [value + 123.0 for value in changed["elastic"]["total"]]
    changed["elastic"]["max_conc"] += 99.0
    changed["elastic"]["stress_outputs"]["reinforcement"]["value"] += 1.0
    second = build_crack_trace_family(
        inp,
        changed,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    )
    assert second == first


def test_both_mode_unrelated_family_values_do_not_mask_valid_crack_family():
    elastic_input = _input()
    elastic = _output(elastic_input)["elastic"]
    inp = _input(mode="Both")
    first = build_crack_trace_family(
        inp,
        {"plastic": {"opaque": object()}, "elastic": elastic},
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    )
    second = build_crack_trace_family(
        inp,
        {"plastic": {"opaque": object()}, "elastic": elastic},
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    )
    assert first == second


@pytest.mark.parametrize(
    "mutation",
    [
        "catalog-description",
        "concrete-id",
        "element-id",
        "material-id",
        "outer",
        "material-law",
    ],
)
def test_complete_geometry_material_and_catalogue_identity_is_sealed(mutation):
    inp, out, bundle = _bundle()
    changed = copy.deepcopy(inp)
    if mutation == "catalog-description":
        changed["mild_material_catalog"]["items"][0]["description"] += " changed"
    elif mutation == "concrete-id":
        changed["concrete_material_id"] += "-changed"
    elif mutation == "element-id":
        changed["bar_elements"][0]["id"] = "B-new"
    elif mutation == "material-id":
        changed["bar_elements"][0]["material_id"] = "M-new"
    elif mutation == "outer":
        changed["outer"][0] = (np.nextafter(0.0, -1.0), 0.0)
    else:
        changed["bar_materials"][0] = dataclasses.replace(
            changed["bar_materials"][0], Es=199_000.0
        )
    with pytest.raises(TraceValidationError):
        validate_crack_trace_family(
            bundle,
            changed,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context=CONTEXT,
        )


def test_concrete_identity_is_required_not_inferred_from_equal_material_law():
    inp = _input()
    out = _output(inp)
    del inp["concrete_material_id"]
    with pytest.raises(TraceValidationError, match="requires concrete_material_id"):
        build_crack_trace_family(
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_branch_only_sibling_values_are_inert_but_presence_and_type_are_pinned():
    inp, out, first = _bundle()
    changed = copy.deepcopy(inp)
    changed["sls_member"] = "Slab"
    changed["sls_tendon_xi"] = 7.5
    second = build_crack_trace_family(
        changed,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    )
    assert second == first

    for key, value in (("sls_member", []), ("sls_tendon_xi", [])):
        wrong = copy.deepcopy(inp)
        wrong[key] = value
        with pytest.raises(TraceValidationError, match="retain"):
            build_crack_trace_family(
                wrong,
                out,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )
    missing = copy.deepcopy(inp)
    del missing["sls_member"]
    with pytest.raises(TraceValidationError, match="requires sls_member"):
        build_crack_trace_family(
            missing,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


@pytest.mark.parametrize(
    "path",
    [
        ("lambda_cr",),
        ("props_un", "Ix"),
        ("crack", "wk"),
        ("crack", "candidates", 0, "cover"),
        ("crack_short", "element_id"),
        ("crack_output", "case"),
    ],
)
def test_every_owned_output_and_nested_candidate_leaf_is_required(path):
    inp = _input()
    out = _output(inp)
    target = out["elastic"]
    for part in path[:-1]:
        target = target[part]
    leaf = path[-1]
    if isinstance(leaf, int):
        target[leaf] = None
    elif isinstance(target, dict):
        value = target[leaf]
        target[leaf] = (
            value + 1.0
            if type(value) in {int, float} and type(value) is not bool
            else "tampered"
        )
    with pytest.raises(TraceValidationError):
        build_crack_trace_family(
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_empty_reinforcement_is_explicitly_undefined():
    inp = _input(empty=True, Mx_el_l=0.0, Mx_el_s=0.0)
    out = _output(inp)
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    )
    assert [item.steps[-1].result.state for item in bundle.calculations] == [
        RESULT_UNDEFINED,
        RESULT_UNDEFINED,
        RESULT_UNDEFINED,
    ]
    aggregate = bundle.calculations[-1]
    factor = next(
        step for step in aggregate.steps
        if step.step_id == "governing-cracking-factor"
    )
    assert factor.result.state == "positive_infinity"


def test_nonconvergence_builds_minimal_failure_without_failure_numerics(monkeypatch):
    inp = _input()
    out = _output(inp)
    original = sector_app.solve_elastic_combined

    def failed(*args, **kwargs):
        return dataclasses.replace(original(*args, **kwargs), converged=False)

    import sector.crack_trace as crack_trace

    monkeypatch.setattr(crack_trace, "solve_elastic_combined", failed)
    out["elastic"]["converged"] = False
    out["elastic"]["props_un"]["Ix"] = float("nan")
    out["elastic"]["crack"]["wk"] = object()
    out["elastic"]["crack_output"] = {
        "value": None,
        "case": None,
        "governing": None,
        "unit": "mm",
        "calculation_state": "INVALID",
    }
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    )
    assert len(bundle.calculations) == 1
    final = bundle.calculations[0].steps[-1]
    assert final.result.state == RESULT_FAILED
    assert final.result.value is None
    assert final.source.kind == SOURCE_PROJECT

    out["elastic"]["crack_verdict"] = "PASS"
    with pytest.raises(TraceValidationError, match="inventory"):
        build_crack_trace_family(
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_building_dk_failure_reconstructs_metadata_and_ignores_only_numerics(
    monkeypatch,
):
    inp = _dk_input(sls_member="Slab")
    out = _output(inp)
    original = sector_app.solve_elastic_combined

    def failed(*args, **kwargs):
        return dataclasses.replace(original(*args, **kwargs), converged=False)

    import sector.crack_trace as crack_trace

    monkeypatch.setattr(crack_trace, "solve_elastic_combined", failed)
    out["elastic"]["converged"] = False
    out["elastic"]["props_un"]["Ix"] = float("nan")
    out["elastic"]["crack"]["wk"] = object()
    out["elastic"]["crack_coarse"]["wk"] = object()
    out["elastic"]["crack_output"] = {
        "value": None,
        "case": None,
        "governing": None,
        "unit": "mm",
        "calculation_state": "INVALID",
    }
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    )
    assert len(bundle.calculations) == 1
    calculation = bundle.calculations[0]
    assert calculation.steps[-1].result.state == RESULT_FAILED
    input_ids = {
        step.step_id
        for step in calculation.steps
        if step.step_id.startswith("input-") and "-sha256-" in step.step_id
    }
    route_steps = tuple(
        step for step in calculation.steps
        if step.step_id.startswith("route-building-dk-")
    )
    assert len(route_steps) == 2
    assert all(
        {dependency.step_id for dependency in step.dependencies} == input_ids
        for step in route_steps
    )
    metadata_steps = tuple(
        step
        for step in calculation.steps
        if step.title.startswith("Sealed crack_")
    )
    assert len(metadata_steps) == 24
    reachable = _reachable(calculation)
    assert all(step.step_id in reachable for step in metadata_steps)

    for key, stale in (
        ("crack_code", "EN 1992-1-1:2005"),
        ("crack_edition", "stale-edition"),
        ("crack_member", "Beam"),
    ):
        changed = copy.deepcopy(out)
        changed["elastic"][key] = stale
        with pytest.raises(TraceValidationError, match=f"failed elastic.{key}"):
            build_crack_trace_family(
                inp,
                changed,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )


def test_removed_limit_and_new_limit_utilisation_verdict_surfaces_are_rejected():
    inp = _input()
    out = _output(inp)
    removed = copy.deepcopy(inp)
    removed["sls_crack_limit"] = 0.3
    with pytest.raises(TraceValidationError, match="removed"):
        build_crack_trace_family(
            removed,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )
    for key in ("wk_limit", "crack_utilisation", "crack_verdict", "sls_limit_source"):
        changed = copy.deepcopy(out)
        changed["elastic"][key] = 1.0
        with pytest.raises(TraceValidationError, match="inventory"):
            build_crack_trace_family(
                inp,
                changed,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )


def test_coherently_resealed_trace_tamper_is_rejected():
    inp, out, bundle = _bundle()
    calculation = bundle.calculations[0]
    first = calculation.steps[0]
    changed_step = dataclasses.replace(
        first,
        result=TraceResult(RESULT_FINITE, first.result.value + 1.0),
    )
    changed_calculation = dataclasses.replace(
        calculation,
        steps=(changed_step, *calculation.steps[1:]),
    )
    changed = seal_bundle(dataclasses.replace(
        bundle,
        calculations=(changed_calculation, *bundle.calculations[1:]),
        content_sha256="",
    ))
    with pytest.raises(TraceValidationError, match="independent reconstruction"):
        validate_crack_trace_family(
            changed,
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context=CONTEXT,
        )


@pytest.mark.parametrize("kind", ["source", "unit", "axis", "final"])
def test_resealed_metadata_dependency_surface_is_rejected(kind):
    inp, out, bundle = _bundle()
    calculation = bundle.calculations[0]
    if kind == "source":
        step = dataclasses.replace(
            calculation.steps[0],
            source=TraceSource(SOURCE_PROJECT, "forged-source"),
        )
        calculation = dataclasses.replace(
            calculation, steps=(step, *calculation.steps[1:])
        )
    elif kind == "unit":
        step = dataclasses.replace(
            calculation.steps[0], unit=TraceUnit("forged", "scalar")
        )
        calculation = dataclasses.replace(
            calculation, steps=(step, *calculation.steps[1:])
        )
    elif kind == "axis":
        calculation = dataclasses.replace(
            calculation, axes=calculation.axes[:-1]
        )
    else:
        calculation = dataclasses.replace(
            calculation, final_step_id=calculation.steps[-2].step_id
        )
    with pytest.raises(TraceValidationError):
        changed = seal_bundle(dataclasses.replace(
            bundle,
            calculations=(calculation, *bundle.calculations[1:]),
            content_sha256="",
        ))
        validate_crack_trace_family(
            changed,
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context=CONTEXT,
        )


def test_context_axis_collision_and_missing_active_output_are_rejected():
    inp = _input()
    out = _output(inp)
    with pytest.raises(ValueError, match="replace"):
        build_crack_trace_family(
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context={"crack_case": "forged"},
        )
    with pytest.raises(TraceValidationError, match="elastic output"):
        build_crack_trace_family(
            inp,
            {},
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )
