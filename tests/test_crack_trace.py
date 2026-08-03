"""CT-009 2004 base/building-DK oracles and adversarial closure tests."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
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
    trace_identity_token,
)
from sector.crack_trace import (
    build_crack_trace_family,
    validate_crack_trace_family,
)
from sector.crack_trace_contract import MemberShape, registry_for
from sector.materials import Prestress
from sector.section import Section
from sector.sls import crack_outputs
from tests.test_section_trace_blocks import _catalog_item


INPUT_SHA = "3" * 64
RESULT_SHA = "4" * 64
CONTEXT = {"case": "ct009-base", "stage": 1}
DK_CODE = "DS/EN 1992-1-1 + DK NA"
BRIDGE_BASE_CODE = "DS/EN 1992-2:2005 + AC:2008"
BRIDGE_DK_CODE = "DS/EN 1992-2 DK NA:2015"
CODE_2023 = "EN 1992-1-1:2023"


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


def _bridge_input(*, dk_na: bool = False, **changes):
    values = dict(
        sls_code=BRIDGE_DK_CODE if dk_na else BRIDGE_BASE_CODE,
        sls_dk_na=dk_na,
    )
    values.update(changes)
    return _input(**values)


def _2023_input(**changes):
    values = dict(sls_code=CODE_2023, sls_edition="2023", sls_dk_na=False)
    values.update(changes)
    return _input(**values)


def _2023_direct_input(**changes):
    outer = [(-0.15, -0.30), (0.15, -0.30), (0.15, 0.30), (-0.15, 0.30)]
    bars = [
        (-0.10, -0.25, 500.0),
        (0.10, -0.25, 500.0),
        (-0.10, 0.25, 500.0),
        (0.10, 0.25, 500.0),
    ]
    steel = _input()["steel"]
    values = dict(
        outer=outer,
        bars=bars,
        section=Section.from_polygon(outer, bars),
        bar_materials=[steel] * len(bars),
        bar_elements=[
            _record(f"B{position}", x, y, area)
            for position, (x, y, area) in enumerate(bars, start=1)
        ],
        P_el_l=5000.0,
        Mx_el_l=0.0,
        My_el_l=0.0,
        P_el_s=0.0,
        Mx_el_s=0.0,
        My_el_s=0.0,
    )
    values.update(changes)
    return _2023_input(**values)


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
        ("EN 1992-1-1:2023", "2004", False),
        ("DS/EN 1992-1-1 + DK NA", "2004", False),
        (BRIDGE_BASE_CODE, "2004", True),
        (BRIDGE_DK_CODE, "2004", False),
        (BRIDGE_DK_CODE, "2023", True),
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


@pytest.mark.parametrize(
    "dk_na,code,cases,route,method_id",
    [
        (
            False,
            BRIDGE_BASE_CODE,
            ("long-term", "short-term", "aggregate"),
            "bridge-base",
            "sector-en-1992-2-2005-crack-width-route-replay",
        ),
        (
            True,
            BRIDGE_DK_CODE,
            (
                "long-term-fine",
                "short-term-fine",
                "long-term-coarse",
                "short-term-coarse",
                "aggregate",
            ),
            "bridge-dk",
            "sector-dk-na-2015-bridge-crack-width-route-replay",
        ),
    ],
)
def test_bridge_routes_round_trip_order_axes_and_retained_mechanics(
    dk_na, code, cases, route, method_id,
):
    inp = _bridge_input(dk_na=dk_na)
    out = _output(inp)
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"route": route},
    )
    assert bundle is not None
    assert bundle_from_json(bundle_to_json(bundle)) == bundle
    assert [
        dict((axis.name, axis.value) for axis in item.axes)["crack_case"]
        for item in bundle.calculations
    ] == list(cases)
    for calculation in bundle.calculations:
        axes = {axis.name: axis.value for axis in calculation.axes}
        assert axes["crack_route"] == route
        assert axes["crack_code"] == trace_identity_token(code)
        assert calculation.method_id == method_id
        assert _reachable(calculation) == {
            step.step_id for step in calculation.steps
        }
    assert out["elastic"]["crack_code"] == code
    assert out["elastic"]["crack_edition"] == "2004"
    assert out["elastic"]["crack_member"] == ("Beam" if dk_na else None)
    assert validate_crack_trace_family(
        bundle,
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"route": route},
    ) == bundle

    reference_input = _dk_input() if dk_na else _input()
    reference = _output(reference_input)["elastic"]
    keys = (
        "crack",
        "crack_short",
        *(("crack_coarse", "crack_short_coarse") if dk_na else ()),
        "crack_output",
    )
    assert all(out["elastic"][key] == reference[key] for key in keys)


@pytest.mark.parametrize(
    "dk_na,prefix,methods,editions,documents,clauses,locators",
    [
        (
            False,
            "route-bridge-base-",
            ("en-1992-2-2005-crack-width-route",),
            (BRIDGE_BASE_CODE,),
            (BRIDGE_BASE_CODE,),
            ("7.3.4(101)",),
            ("recommended method: EN 1992-1-1 7.3.4",),
        ),
        (
            True,
            "route-bridge-dk-",
            (
                "en-1992-2-2005-crack-width-route",
                "dk-na-2015-bridge-crack-width-route",
                "dk-na-2024-crack-width-route",
            ),
            (
                BRIDGE_BASE_CODE,
                BRIDGE_DK_CODE,
                "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 with "
                "DS/EN 1992-1-1 DK NA:2024 rev. 2024-02-01",
            ),
            (
                BRIDGE_BASE_CODE,
                BRIDGE_DK_CODE,
                "DS/EN 1992-1-1 DK NA:2024 rev. 2024-02-01",
            ),
            ("7.3.4(101)", "7.3.4(101)", "7.3.2(3), 7.3.4(1), 7.3.4(3)"),
            (
                "recommended method: EN 1992-1-1 7.3.4",
                "no national choice",
                "fine/coarse systems, member rule and cover-dependent k3",
            ),
        ),
    ],
)
def test_bridge_route_sources_and_selector_dependencies_are_exact(
    dk_na, prefix, methods, editions, documents, clauses, locators,
):
    inp = _bridge_input(dk_na=dk_na)
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
        assert len(input_ids) == 32
        routes = tuple(
            step for step in calculation.steps if step.step_id.startswith(prefix)
        )
        assert input_ids and len(routes) == len(methods)
        assert tuple(step.source.method_id for step in routes) == methods
        assert tuple(step.source.edition for step in routes) == editions
        assert tuple(step.source.citation.document for step in routes) == documents
        assert tuple(step.source.citation.clause for step in routes) == clauses
        assert tuple(step.source.citation.locator for step in routes) == locators
        assert all(
            step.step_id in reachable
            and step.quantity_role == "computed_intermediate"
            and {dependency.step_id for dependency in step.dependencies} == input_ids
            for step in routes
        )
        rules = tuple(
            step
            for step in calculation.steps
            if step.step_id == "case-fine-effective-height-rule"
        )
        if rules:
            assert dk_na and len(rules) == 1
            assert {
                dependency.step_id for dependency in rules[0].dependencies
            } == input_ids


@pytest.mark.parametrize(
    "dk_na,route,registry_id,family_id,method_id",
    [
        (
            False,
            "bridge-base",
            "sector-ct-009-crack-width-2004-bridge-base-v1",
            "ct-009-crack-width-2004-bridge-base",
            "sector-en-1992-2-2005-crack-width-route-replay",
        ),
        (
            True,
            "bridge-dk",
            "sector-ct-009-crack-width-2004-bridge-dk-v1",
            "ct-009-crack-width-2004-bridge-dk",
            "sector-dk-na-2015-bridge-crack-width-route-replay",
        ),
    ],
)
def test_bridge_registry_family_and_method_identities_are_distinct(
    dk_na, route, registry_id, family_id, method_id,
):
    inp = _bridge_input(dk_na=dk_na)
    calculation = build_crack_trace_family(
        inp,
        _output(inp),
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    ).calculations[0]
    final = next(
        step for step in calculation.steps
        if step.step_id == calculation.final_step_id
    )
    shape = MemberShape(
        member_id="registry-probe",
        calculation_id=calculation.calculation_id,
        axes=calculation.axes,
        steps=tuple(
            (
                step.step_id,
                step.quantity_role,
                step.source,
                tuple(item.step_id for item in step.dependencies),
            )
            for step in calculation.steps
        ),
        states=frozenset({final.result.state}),
    )
    registry = registry_for((shape,), dk_na=dk_na, route=route)
    assert registry.registry_id == registry_id
    assert registry.families[0].family_id == family_id
    assert registry.families[0].members[0].method_id == method_id


@pytest.mark.parametrize("dk_na", [False, True])
def test_bridge_geometry_material_catalogue_and_selector_identity_is_sealed(dk_na):
    inp = _bridge_input(dk_na=dk_na)
    out = _output(inp)
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    )
    mutations = []
    catalogue = copy.deepcopy(inp)
    catalogue["mild_material_catalog"]["items"][0]["description"] += " changed"
    mutations.append(catalogue)
    concrete = copy.deepcopy(inp)
    concrete["concrete_material_id"] += "-same-law"
    mutations.append(concrete)
    selector = copy.deepcopy(inp)
    opposite_code = (
        BRIDGE_BASE_CODE if dk_na else BRIDGE_DK_CODE
    )
    selector["sls_code"] = opposite_code
    selector["sls_dk_na"] = not dk_na
    assert opposite_code != inp["sls_code"]
    mutations.append(selector)
    for changed in mutations:
        with pytest.raises(TraceValidationError):
            validate_crack_trace_family(
                bundle,
                changed,
                out,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )


@pytest.mark.parametrize("dk_na", [False, True])
def test_every_bridge_owned_leaf_and_inventory_are_reconstructed(dk_na):
    inp = _bridge_input(dk_na=dk_na)
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
    for path in tuple(_leaf_paths(owned)):
        changed = copy.deepcopy(out)
        _mutate_path(changed["elastic"], path)
        with pytest.raises(TraceValidationError):
            build_crack_trace_family(
                inp,
                changed,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )

    mutations = []
    missing = copy.deepcopy(out)
    del missing["elastic"]["crack"]
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


@pytest.mark.parametrize(
    "dk_na,prefix,code,member",
    [
        (False, "route-bridge-base-", BRIDGE_BASE_CODE, None),
        (True, "route-bridge-dk-", BRIDGE_DK_CODE, "Beam"),
    ],
)
def test_bridge_failure_seals_exact_route_metadata_and_ignores_only_numerics(
    monkeypatch, dk_na, prefix, code, member,
):
    inp = _bridge_input(dk_na=dk_na)
    out = _output(inp)
    original = sector_app.solve_elastic_combined

    def failed(*args, **kwargs):
        return dataclasses.replace(original(*args, **kwargs), converged=False)

    import sector.crack_trace as crack_trace

    monkeypatch.setattr(crack_trace, "solve_elastic_combined", failed)
    out["elastic"]["converged"] = False
    out["elastic"]["props_un"]["Ix"] = float("nan")
    out["elastic"]["crack"]["wk"] = object()
    if dk_na:
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
        context={"route": "failed-bridge"},
    )
    calculation = bundle.calculations[0]
    assert calculation.steps[-1].result.state == RESULT_FAILED
    assert calculation.steps[-1].result.value is None
    input_ids = {
        step.step_id
        for step in calculation.steps
        if step.step_id.startswith("input-") and "-sha256-" in step.step_id
    }
    route_steps = tuple(
        step for step in calculation.steps if step.step_id.startswith(prefix)
    )
    assert len(route_steps) == (3 if dk_na else 1)
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

    stale_values = {
        "crack_code": "wrong-route",
        "crack_edition": "stale-edition",
        "crack_member": "Slab" if member == "Beam" else "Beam",
    }
    assert out["elastic"]["crack_code"] == code
    assert out["elastic"]["crack_member"] == member
    for key, stale in stale_values.items():
        changed = copy.deepcopy(out)
        changed["elastic"][key] = stale
        with pytest.raises(TraceValidationError, match=f"failed elastic.{key}"):
            build_crack_trace_family(
                inp,
                changed,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )


def test_accepted_base_and_building_dk_bundle_bytes_remain_exact(monkeypatch):
    success_cases = (
        (
            _input(),
            CONTEXT,
            "d9b9d1fb20038b64f8446d148e9038095b95df13114814abc8b66f514e9c39d9",
        ),
        (
            _dk_input(),
            {"route": "building-dk"},
            "8ec5e3a96b1dbc82e15299966a5181f123ce6077eece3803fdea77fa692ff0bc",
        ),
    )
    outputs = []
    for inp, context, expected in success_cases:
        out = _output(inp)
        outputs.append(out)
        bundle = build_crack_trace_family(
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context=context,
        )
        assert hashlib.sha256(bundle_to_json(bundle).encode("ascii")).hexdigest() == expected

    original = sector_app.solve_elastic_combined

    def failed(*args, **kwargs):
        return dataclasses.replace(original(*args, **kwargs), converged=False)

    import sector.crack_trace as crack_trace

    monkeypatch.setattr(crack_trace, "solve_elastic_combined", failed)
    dk_failed_input = _dk_input(sls_member="Slab")
    dk_failed_output = _output(dk_failed_input)
    failure_cases = (
        (
            success_cases[0][0],
            outputs[0],
            CONTEXT,
            "b143f168ec448579cd3e31d9a3dec4a381e42618899d558be7c84af02e38890a",
        ),
        (
            dk_failed_input,
            dk_failed_output,
            {"route": "building-dk-failed"},
            "84ab06ca477fc9d283114b1bc992f01474e3ccf39176af7ebb18f166a4044492",
        ),
    )
    for inp, out, context, expected in failure_cases:
        out["elastic"]["converged"] = False
        out["elastic"]["props_un"]["Ix"] = float("nan")
        out["elastic"]["crack"]["wk"] = object()
        if inp["sls_dk_na"]:
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
            context=context,
        )
        assert hashlib.sha256(bundle_to_json(bundle).encode("ascii")).hexdigest() == expected


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


def test_2023_calculated_bending_round_trip_values_order_and_methods():
    inp = _2023_input()
    out = _output(inp)
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"route": "2023-calculated-bending"},
    )
    assert bundle_from_json(bundle_to_json(bundle)) == bundle
    assert validate_crack_trace_family(
        bundle,
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"route": "2023-calculated-bending"},
    ) == bundle
    assert [
        {axis.name: axis.value for axis in calculation.axes}["crack_case"]
        for calculation in bundle.calculations
    ] == ["long-term", "short-term", "aggregate"]
    assert [calculation.method_id for calculation in bundle.calculations] == [
        "sector-en-1992-1-1-2023-refined-bending-replay",
        "sector-en-1992-1-1-2023-refined-bending-replay",
        "sector-en-1992-1-1-2023-crack-width-aggregate",
    ]
    long_term = out["elastic"]["crack"]
    short_term = out["elastic"]["crack_short"]
    assert long_term["wk"] == pytest.approx(0.7398000579056716)
    assert long_term["sr_max"] == pytest.approx(169.48056326929603)
    assert long_term["esm_ecm"] == pytest.approx(0.0022449179685008554)
    assert long_term["rho_p_eff"] == pytest.approx(0.01904761904761901)
    assert long_term["ac_eff"] == pytest.approx(0.0525000000000001)
    assert long_term["hc_ef"] == pytest.approx(0.1750000000000005)
    assert (long_term["kw"], long_term["k1_r"], long_term["kfl"]) == pytest.approx(
        (1.7, 1.143786759399941, 0.6848874598070733)
    )
    assert short_term["wk"] == pytest.approx(0.9917623023584697)
    assert out["elastic"]["crack_output"] == {
        "value": 0.9917623023584697,
        "case": "Short-term",
        "governing": "B1",
        "unit": "mm",
        "calculation_state": "CALCULATED",
    }
    for calculation in bundle.calculations:
        axes = {axis.name: axis.value for axis in calculation.axes}
        assert axes["crack_code"] == trace_identity_token(CODE_2023)
        assert axes["crack_edition"] == "2023"
        assert axes["crack_route"] == "building-2023"
        assert _reachable(calculation) == {
            step.step_id for step in calculation.steps
        }


def test_2023_standard_provenance_is_exclusively_2023_including_case_kt():
    inp = _2023_input()
    calculation = build_crack_trace_family(
        inp,
        _output(inp),
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    ).calculations[0]
    expected = {
        "en-1992-1-1-2023-crack-width-route": "refined calculation of crack width",
        "en-1992-1-1-2023-effective-tension-area": "Figure 9.3",
        "en-1992-1-1-2023-effective-reinforcement-ratio": "Formula (9.12)",
        "en-1992-1-1-2023-mean-strain-difference": "Formula (9.11)",
        "en-1992-1-1-2023-mean-crack-spacing": "Formula (9.15)",
        "en-1992-1-1-2023-curvature-factor": "Formula (9.9)",
        "en-1992-1-1-2023-flexural-coefficient": "Formula (9.17)",
        "en-1992-1-1-2023-bond-factor": "Formula (9.18)",
        "en-1992-1-1-2023-calculated-crack-width": "Formula (9.8)",
    }
    standard_steps = [
        step for step in calculation.steps if step.source.kind == SOURCE_STANDARD
    ]
    assert all(
        step.source.edition == "DS/EN 1992-1-1:2023"
        and step.source.citation is not None
        and step.source.citation.document == "DS/EN 1992-1-1:2023"
        and step.source.citation.clause == "9.2.3"
        for step in standard_steps
    )
    assert {
        step.source.method_id: step.source.citation.locator
        for step in standard_steps
        if step.source.method_id in expected
    } == expected
    case_kt = next(step for step in calculation.steps if step.step_id == "case-kt")
    assert case_kt.source.method_id == "en-1992-1-1-2023-mean-strain-difference"


@pytest.mark.parametrize(
    "changes,cap_governs",
    [({}, False), ({"P_el_l": -1000.0, "Mx_el_l": 300.0, "P_el_s": 0.0, "Mx_el_s": 0.0}, True)],
)
def test_2023_formula_9_15_reconstructs_uncapped_cap_and_selection(
    changes, cap_governs,
):
    inp = _2023_input(**changes)
    out = _output(inp)
    calculation = build_crack_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
    ).calculations[0]
    by_id = {step.step_id: step for step in calculation.steps}
    prefix = "candidate-0001"
    depth = by_id[f"{prefix}-h-minus-x"]
    uncapped = by_id[f"{prefix}-spacing-uncapped"]
    cap = by_id[f"{prefix}-spacing-cap"]
    selected = by_id[f"{prefix}-sr-max"]
    width = by_id[f"{prefix}-wk"]
    assert depth.result.value > 0.0
    assert selected.result.value == pytest.approx(
        min(uncapped.result.value, cap.result.value)
    )
    assert selected.result.value == pytest.approx(out["elastic"]["crack"]["sr_max"])
    assert (cap.result.value < uncapped.result.value) is cap_governs
    assert {item.step_id for item in cap.dependencies} == {
        f"{prefix}-h-minus-x",
        f"{prefix}-kw",
    }
    assert {item.step_id for item in selected.dependencies} == {
        f"{prefix}-spacing-uncapped",
        f"{prefix}-spacing-cap",
    }
    assert selected.source.citation.locator == "Formula (9.15)"
    assert width.result.value == pytest.approx(
        by_id[f"{prefix}-kw"].result.value
        * by_id[f"{prefix}-k1-r"].result.value
        * selected.result.value
        * by_id[f"{prefix}-esm-ecm"].result.value
    )
    assert width.source.citation.locator == "Formula (9.8)"
    assert _reachable(calculation) == set(by_id)


def test_2023_direct_and_tendon_subfamilies_fail_closed():
    direct = _2023_direct_input()
    with pytest.raises(TraceValidationError, match="direct-tension trace is deferred"):
        build_crack_trace_family(
            direct,
            _output(direct),
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )
    tendon = _2023_input(with_tendon=True, sls_tendon_xi=0.7)
    with pytest.raises(TraceValidationError, match="tendon bond trace is deferred"):
        build_crack_trace_family(
            tendon,
            _output(tendon),
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def _2023_mixed_not_assessed_bundle(monkeypatch):
    from sector.serviceability import CrackWidthEvaluation
    import sector.crack_trace as crack_trace

    inp = _2023_input()
    out = _output(inp)
    original_evaluate = crack_trace.evaluate_crack_width

    def mixed_evaluation(*args, **kwargs):
        if kwargs["kt"] == 0.6:
            return CrackWidthEvaluation(
                "NOT ASSESSED",
                "The short-term strain gradient is outside the validated scope.",
            )
        return original_evaluate(*args, **kwargs)

    monkeypatch.setattr(crack_trace, "evaluate_crack_width", mixed_evaluation)
    out["elastic"]["crack_short"] = None
    out["elastic"]["crack_output"] = crack_outputs(
        {"Long-term": out["elastic"]["crack"], "Short-term": None},
        valid=True,
    )
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"route": "2023-mixed-applicability"},
    )
    return inp, out, bundle


def test_2023_not_assessed_case_blocks_finite_sibling_and_preserves_reason(monkeypatch):
    inp, out, bundle = _2023_mixed_not_assessed_bundle(monkeypatch)
    assert validate_crack_trace_family(
        bundle,
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"route": "2023-mixed-applicability"},
    ) == bundle

    axes = [
        {axis.name: axis.value for axis in calculation.axes}
        for calculation in bundle.calculations
    ]
    assert [item["crack_branch"] for item in axes] == [
        "calculated",
        "not-assessed",
        "not-assessed",
    ]
    assert [item["crack_scope"] for item in axes] == [
        "refined-bending",
        "not-assessed",
        "not-assessed",
    ]
    assert [calculation.method_id for calculation in bundle.calculations] == [
        "sector-en-1992-1-1-2023-refined-bending-replay",
        "sector-en-1992-1-1-2023-crack-width-not-assessed",
        "sector-en-1992-1-1-2023-crack-width-aggregate",
    ]
    case_final = bundle.calculations[1].steps[-1].result
    aggregate_final = bundle.calculations[2].steps[-1].result
    reason = "The short-term strain gradient is outside the validated scope."
    assert case_final == TraceResult(RESULT_UNDEFINED, None, reason)
    assert aggregate_final == TraceResult(
        RESULT_UNDEFINED,
        None,
        "The retained 2023 crack-width aggregate is not assessed: " + reason,
    )
    assert all(
        _reachable(calculation) == {step.step_id for step in calculation.steps}
        for calculation in bundle.calculations
    )


def test_2023_actual_combined_tension_and_bending_is_not_assessed():
    inp = _2023_direct_input(Mx_el_l=10.0)
    out = _output(inp)
    assert out["elastic"]["crack"] is None
    assert out["elastic"]["crack_short"] is None
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"route": "2023-combined-tension-bending"},
    )
    reason = (
        "The entire section is in tension but the strain gradient is not uniform. "
        "The validated direct-tension branch does not cover this combined "
        "tension-and-bending state."
    )
    assert [
        {axis.name: axis.value for axis in calculation.axes}["crack_branch"]
        for calculation in bundle.calculations
    ] == ["not-assessed", "not-assessed", "not-assessed"]
    assert [
        calculation.steps[-1].result.reason
        for calculation in bundle.calculations
    ] == [
        reason,
        reason,
        "The retained 2023 crack-width aggregate is not assessed: " + reason,
    ]


@pytest.mark.parametrize("mutation", ["method", "scope", "case-reason", "aggregate-reason"])
def test_2023_not_assessed_metadata_and_reasons_reject_resealed_tampering(
    monkeypatch, mutation,
):
    inp, out, bundle = _2023_mixed_not_assessed_bundle(monkeypatch)
    calculations = list(bundle.calculations)
    position = 2 if mutation == "aggregate-reason" else 1
    calculation = calculations[position]
    if mutation == "method":
        calculation = dataclasses.replace(calculation, method_id="forged-method")
    elif mutation == "scope":
        changed_axes = tuple(
            dataclasses.replace(axis, value="not-applicable")
            if axis.name == "crack_scope" else axis
            for axis in calculation.axes
        )
        calculation = dataclasses.replace(calculation, axes=changed_axes)
    else:
        final = dataclasses.replace(
            calculation.steps[-1],
            result=dataclasses.replace(
                calculation.steps[-1].result,
                reason="Forged applicability reason.",
            ),
        )
        calculation = dataclasses.replace(
            calculation, steps=(*calculation.steps[:-1], final)
        )
    calculations[position] = calculation
    changed = seal_bundle(dataclasses.replace(
        bundle,
        calculations=tuple(calculations),
        content_sha256="",
    ))
    with pytest.raises(TraceValidationError):
        validate_crack_trace_family(
            changed,
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context={"route": "2023-mixed-applicability"},
        )


def test_2023_direct_tension_fence_does_not_depend_on_candidate_presence():
    inp = _2023_direct_input()
    outer = [
        (-0.30, 0.0),
        (-0.15, -0.26),
        (0.15, -0.26),
        (0.30, 0.0),
        (0.15, 0.26),
        (-0.15, 0.26),
    ]
    bars = [
        (-0.15, 0.0, 500.0),
        (0.15, 0.0, 500.0),
        (0.0, -0.15, 500.0),
        (0.0, 0.15, 500.0),
    ]
    inp.update(
        outer=outer,
        bars=bars,
        section=Section.from_polygon(outer, bars),
        bar_materials=[inp["steel"]] * len(bars),
        bar_elements=[
            _record(f"B{position}", x, y, area)
            for position, (x, y, area) in enumerate(bars, start=1)
        ],
    )
    out = _output(inp)
    assert out["elastic"]["crack"] is None
    assert out["elastic"]["crack_short"] is None
    with pytest.raises(TraceValidationError, match="direct-tension trace is deferred"):
        build_crack_trace_family(
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_2023_pr08d2a1_calculated_and_uncracked_bundle_bytes_remain_frozen():
    calculated = _2023_input()
    uncracked = _2023_input(
        P_el_l=0.0,
        Mx_el_l=0.0,
        My_el_l=0.0,
        P_el_s=0.0,
        Mx_el_s=0.0,
        My_el_s=0.0,
    )
    fixtures = (
        (
            calculated,
            {"route": "2023-calculated-bending"},
            "e40416438c1894795e040c820e16d2b04904d196f86fceccba13785278085390",
        ),
        (
            uncracked,
            {"route": "2023-uncracked"},
            "65d17e6ae2eb6a8a9e0a054d7b229c43e15495e2c407568e3a8b46c3e3b4acfb",
        ),
    )
    for inp, context, expected in fixtures:
        bundle = build_crack_trace_family(
            inp,
            _output(inp),
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context=context,
        )
        assert hashlib.sha256(bundle_to_json(bundle).encode("ascii")).hexdigest() == expected


def test_2023_uncracked_family_is_explicitly_not_applicable():
    inp = _2023_input(
        P_el_l=0.0,
        Mx_el_l=0.0,
        My_el_l=0.0,
        P_el_s=0.0,
        Mx_el_s=0.0,
        My_el_s=0.0,
    )
    bundle = build_crack_trace_family(
        inp,
        _output(inp),
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    )
    for calculation in bundle.calculations:
        axes = {axis.name: axis.value for axis in calculation.axes}
        assert axes["crack_branch"] == "not-applicable"
        assert axes["crack_scope"] == "not-applicable"
        assert calculation.steps[-1].result.state == RESULT_UNDEFINED
        assert calculation.steps[-1].result.value is None


@pytest.mark.parametrize("kind", ["concrete", "bar"])
def test_2023_selected_published_material_provenance_fails_closed(kind):
    inp = _2023_input()
    if kind == "concrete":
        inp["concrete_preset"] = codes.EC2_2023.label
        inp["concrete"] = codes.EC2_2023.concrete(35.0)
    else:
        law = codes.EC2_2023.steel(500.0)
        inp["mild_preset"] = codes.EC2_2023.label
        inp["steel"] = law
        inp["bar_materials"] = [law] * len(inp["bars"])
        item = _catalog_item("M1", codes.EC2_2023.label, law)
        item.update(name="B500B", description="Ribbed reinforcement")
        inp["mild_material_catalog"]["items"] = [item]
    with pytest.raises(
        TraceValidationError,
        match="2023 material provenance is published but not implemented",
    ):
        build_crack_trace_family(
            inp, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


def test_2023_failure_retains_route_metadata_without_candidate_numerics(monkeypatch):
    inp = _2023_input()
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
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
    )
    calculation = bundle.calculations[0]
    axes = {axis.name: axis.value for axis in calculation.axes}
    assert calculation.method_id == "sector-en-1992-1-1-2023-crack-width-failure"
    assert axes["crack_branch"] == "failed"
    assert axes["crack_edition"] == "2023"
    assert axes["crack_scope"] == "failed"
    assert calculation.steps[-1].result.state == RESULT_FAILED
    assert calculation.steps[-1].result.value is None
    assert _reachable(calculation) == {
        step.step_id for step in calculation.steps
    }


def test_2023_owned_output_leaves_and_inventory_are_reconstructed():
    inp = _2023_input()
    out = _output(inp)
    owned = {
        key: value
        for key, value in out["elastic"].items()
        if key == "converged"
        or key.startswith("crack")
        or key.startswith(("lambda_cr", "sigma_ct", "fctm", "show_cw", "props_"))
    }
    for path in tuple(_leaf_paths(owned)):
        changed = copy.deepcopy(out)
        _mutate_path(changed["elastic"], path)
        with pytest.raises(TraceValidationError):
            build_crack_trace_family(
                inp, changed, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
            )
    for mutation in ("missing", "unknown", "reordered"):
        changed = copy.deepcopy(out)
        if mutation == "missing":
            del changed["elastic"]["crack"]
        elif mutation == "unknown":
            changed["elastic"]["crack_future"] = None
        else:
            elastic = changed["elastic"]
            changed["elastic"] = {
                key: elastic[key] for key in reversed(tuple(elastic))
            }
        with pytest.raises(TraceValidationError, match="inventory|sibling"):
            build_crack_trace_family(
                inp, changed, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
            )


def test_accepted_2004_bridge_bundles_remain_byte_exact():
    cases = (
        (_bridge_input(), {"route": "bridge-base"}, "e84b27051d5237f609b6daf4da1542642b50a41116a49acd09fe689177b9e55c"),
        (_bridge_input(dk_na=True), {"route": "bridge-dk"}, "c1d521adf0e26bc6e865800b297a49bc35e5fa10590bf95923ec76964b1b1705"),
    )
    for inp, context, expected in cases:
        bundle = build_crack_trace_family(
            inp,
            _output(inp),
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context=context,
        )
        assert hashlib.sha256(bundle_to_json(bundle).encode("ascii")).hexdigest() == expected
