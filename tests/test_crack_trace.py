from __future__ import annotations

import copy
import dataclasses
import math

import numpy as np
import pytest

from sector import codes
from sector.calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_UNDEFINED,
    SOURCE_STANDARD,
    TraceValidationError,
    seal_bundle,
)
from sector.crack_trace import (
    build_crack_trace_family,
    validate_crack_trace_family,
)
from sector.crack_trace_contract import (
    DOCUMENT,
    RAW_GRADIENT,
    RAW_STRESS,
    SECOND_MOMENT,
)
from sector.elastic import solve_elastic_combined, transformed_properties
from sector.materials import ES
from sector.section import Section
from sector.serviceability import analyse_cracking, combined_cracking, crack_width
from sector.sls import crack_outputs


INPUT_SHA = "1" * 64
RESULT_SHA = "2" * 64


def _catalog_item(material_id, preset, law):
    item = {
        "id": material_id,
        "name": "B500 catalogue identity",
        "description": "Published bin description retained by CT-009",
        "preset": preset,
    }
    for field in dataclasses.fields(law):
        value = getattr(law, field.name)
        if field.name in {"IS", "eut", "ey0t", "ey0c"}:
            value *= 1000.0
        elif field.name == "Es":
            value /= 1000.0
        item[field.name] = value
    return item


def _element(identifier, x, y, diameter, material_id="M1"):
    area = math.pi * diameter * diameter / 4.0
    return {
        "id": identifier,
        "kind": "bar",
        "x_mm": x * 1000.0,
        "y_mm": y * 1000.0,
        "area_mm2": area,
        "diameter_mm": diameter,
        "size_mode": "Diameter",
        "material_id": material_id,
        "fatigue_detail_id": "FAT-160",
        "x": x,
        "y": y,
    }


def _input(**changes):
    outer = [(0.0, 0.0), (0.4, 0.0), (0.4, 0.6), (0.0, 0.6)]
    bar_data = [
        (0.06, 0.05, math.pi * 32.0**2 / 4.0),
        (0.34, 0.05, math.pi * 32.0**2 / 4.0),
        (0.06, 0.55, math.pi * 20.0**2 / 4.0),
        (0.34, 0.55, math.pi * 20.0**2 / 4.0),
    ]
    section = Section.from_polygon(outer, bar_data)
    concrete = codes.EC2_2005.concrete(35.0)
    steel = codes.EC2_2005.steel(500.0)
    ec = 34.0
    creep = 2.0
    values = {
        "section": section,
        "outer": outer,
        "holes": [],
        "bars": bar_data,
        "tendons": [],
        "concrete": concrete,
        "steel": steel,
        "prestress": None,
        "bar_materials": [steel] * len(bar_data),
        "tendon_materials": [],
        "concrete_material_id": "C35-A",
        "concrete_preset": codes.EC2_2005.label,
        "mild_preset": codes.EC2_2005.label,
        "prestress_preset": codes.EC2_2005.label,
        "mild_material_catalog": {
            "version": 1,
            "next_id": 2,
            "items": [_catalog_item("M1", codes.EC2_2005.label, steel)],
        },
        "prestress_material_catalog": {
            "version": 1,
            "next_id": 1,
            "items": [],
        },
        "bar_elements": [
            _element("B1", 0.06, 0.05, 32.0),
            _element("B2", 0.34, 0.05, 32.0),
            _element("B3", 0.06, 0.55, 20.0),
            _element("B4", 0.34, 0.55, 20.0),
        ],
        "tendon_elements": [],
        "mode": "Elastic",
        "P_el_l": 0.0,
        "Mx_el_l": 400.0,
        "My_el_l": 0.0,
        "P_el_s": 0.0,
        "Mx_el_s": 120.0,
        "My_el_s": 0.0,
        "conc_Ec": ec,
        "el_phi": creep,
        "nl": ES / (ec * 1000.0) * (1.0 + creep),
        "ns": ES / (ec * 1000.0),
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
    values.update(changes)
    return values


def _payload(result, bar_ids):
    if result is None:
        return None

    def identity(index):
        return "Bar", index + 1, bar_ids[index]

    def candidate(item):
        kind, number, identifier = identity(item.bar_index)
        return {
            "element_type": kind,
            "element_no": number,
            "element_id": identifier,
            "x_mm": item.x * 1000.0,
            "y_mm": item.y * 1000.0,
            "area_mm2": item.area,
            "wk": item.wk,
            "sr_max": item.sr_max,
            "esm_ecm": item.esm_ecm,
            "sigma_s": item.sigma_s,
            "rho_p_eff": item.rho_p_eff,
            "ac_eff": item.ac_eff,
            "hc_ef": item.hc_ef,
            "phi": item.phi,
            "cover": item.cover,
            "coarse": item.coarse,
            "edition": item.edition,
            "kw": item.kw,
            "k1_r": item.k1_r,
            "kfl": item.kfl,
            "sr_max_geometric": item.sr_max_geometric,
        }

    kind, number, identifier = identity(result.gov_bar)
    return {
        "wk": result.wk,
        "sr_max": result.sr_max,
        "esm_ecm": result.esm_ecm,
        "sigma_s": result.sigma_s,
        "rho_p_eff": result.rho_p_eff,
        "ac_eff": result.ac_eff,
        "hc_ef": result.hc_ef,
        "phi": result.phi,
        "cover": result.cover,
        "gov_bar": result.gov_bar + 1,
        "element_type": kind,
        "element_no": number,
        "element_id": identifier,
        "coarse": result.coarse,
        "edition": result.edition,
        "kw": result.kw,
        "k1_r": result.k1_r,
        "kfl": result.kfl,
        "sr_max_geometric": result.sr_max_geometric,
        "candidates": [candidate(item) for item in result.candidates],
    }


def _candidate(inp):
    section = inp["section"]
    moduli = np.asarray([item.Es for item in inp["bar_materials"]], dtype=float)
    n_mult = moduli / ES
    p_long = -inp["P_el_l"]
    p_short = -inp["P_el_s"]
    combined = solve_elastic_combined(
        section,
        p_long,
        inp["Mx_el_l"],
        inp["My_el_l"],
        inp["nl"],
        p_short,
        inp["Mx_el_s"],
        inp["My_el_s"],
        inp["ns"],
        n_mult=n_mult,
    )
    diameter = [item["diameter_mm"] for item in inp["bar_elements"]]
    k1 = [inp["sls_k1"]] * len(diameter)
    long = analyse_cracking(
        section,
        p_long,
        inp["Mx_el_l"],
        inp["My_el_l"],
        inp["nl"],
        fctm=inp["sls_fctm"],
        Es=moduli,
        beta=0.5,
        kt=0.4,
        bar_diameter=diameter,
        k1=k1,
        edition="2004",
        n_mult=n_mult,
    )
    peak_cracked, peak_factor, peak_sigma = combined_cracking(
        section,
        p_long,
        inp["Mx_el_l"],
        inp["My_el_l"],
        inp["nl"],
        p_short,
        inp["Mx_el_s"],
        inp["My_el_s"],
        inp["ns"],
        fctm=inp["sls_fctm"],
        n_mult=n_mult,
    )
    if peak_factor < long.lambda_cr:
        cracked, factor, sigma, state = (
            peak_cracked,
            peak_factor,
            peak_sigma,
            combined.short_term,
        )
    else:
        cracked, factor, sigma, state = (
            long.cracked,
            long.lambda_cr,
            long.sigma_ct,
            long.cracked_state,
        )
    props_un = transformed_properties(section, inp["nl"], cracked=False,
                                      n_mult=n_mult)
    props_cr = (
        transformed_properties(
            section,
            inp["nl"],
            eps0=state.eps0,
            kx=state.kx,
            ky=state.ky,
            cracked=True,
            n_mult=n_mult,
        )
        if cracked
        else None
    )
    ids = [item["id"] for item in inp["bar_elements"]]
    if cracked:
        short_state = dataclasses.replace(
            combined.short_term,
            bar_stress=np.asarray(combined.bar_stress_total, dtype=float),
        )
        long_result = crack_width(
            section,
            long.cracked_state,
            inp["nl"],
            fctm=inp["sls_fctm"],
            Es=moduli,
            kt=0.4,
            bar_diameter=diameter,
            k1=k1,
            edition="2004",
            n_mult=n_mult,
            reinforcement_types=["mild"] * len(diameter),
        )
        short_result = crack_width(
            section,
            short_state,
            inp["ns"],
            fctm=inp["sls_fctm"],
            Es=moduli,
            kt=0.6,
            bar_diameter=diameter,
            k1=k1,
            edition="2004",
            n_mult=n_mult,
            reinforcement_types=["mild"] * len(diameter),
        )
        long_payload = _payload(long_result, ids)
        short_payload = _payload(short_result, ids)
    else:
        long_payload = short_payload = None
    elastic = {
        "converged": True,
        "cracked": bool(cracked),
        "lambda_cr": float(factor),
        "sigma_ct": float(sigma),
        "fctm": inp["sls_fctm"],
        "show_cw": True,
        "props_un": {
            name: float(getattr(props_un, name))
            for name in ("area", "cx", "cy", "Ix", "Iy", "Ixy")
        },
        "props_cr": (
            None
            if props_cr is None
            else {
                name: float(getattr(props_cr, name))
                for name in ("area", "cx", "cy", "Ix", "Iy", "Ixy")
            }
        ),
        "crack": long_payload,
        "crack_short": short_payload,
    }
    if cracked:
        elastic.update(
            crack_code=inp["sls_code"],
            crack_edition=inp["sls_edition"],
            crack_member=None,
        )
    elastic["crack_output"] = crack_outputs(
        {"Long-term": long_payload, "Short-term": short_payload}, valid=True
    )
    return {"elastic": elastic}, combined


def _bundle(inp=None, out=None):
    inp = _input() if inp is None else inp
    if out is None:
        out, _combined = _candidate(inp)
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"case": "SLS-01"},
    )
    assert bundle is not None
    return bundle, inp, out


def _reachable(calculation):
    by_id = {step.step_id: step for step in calculation.steps}
    reached = set()
    pending = [calculation.final_step_id]
    while pending:
        step_id = pending.pop()
        if step_id in reached:
            continue
        reached.add(step_id)
        pending.extend(dep.step_id for dep in by_id[step_id].dependencies)
    return reached


def test_round_trip_order_graph_sources_units_and_formula_oracle():
    bundle, inp, out = _bundle()
    assert [
        next(axis.value for axis in item.axes if axis.name == "crack_case")
        for item in bundle.calculations[:2]
    ] == [
        "long-term",
        "short-term",
    ]
    assert len(bundle.calculations) == 3
    for calculation in bundle.calculations:
        assert _reachable(calculation) == {
            step.step_id for step in calculation.steps
        }
    long = bundle.calculations[0]
    units = {step.step_id: step.unit for step in long.steps}
    assert units["cracked-state-q0"] == RAW_STRESS
    assert units["cracked-state-qx"] == RAW_GRADIENT
    assert units["cracked-state-qy"] == RAW_GRADIENT
    aggregate = bundle.calculations[-1]
    for step in aggregate.steps:
        if step.step_id.endswith(("-ix", "-iy", "-ixy")):
            assert step.unit == SECOND_MOMENT
    candidate = out["elastic"]["crack"]["candidates"][0]
    assert candidate["wk"] == pytest.approx(
        candidate["sr_max"] * candidate["esm_ecm"], rel=1e-12
    )
    assert validate_crack_trace_family(
        bundle,
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"case": "SLS-01"},
    ) == bundle


def test_every_standard_leaf_cites_only_the_selected_building_document():
    bundle, _inp, _out = _bundle()
    standard = [
        step.source
        for calculation in bundle.calculations
        for step in calculation.steps
        if step.source.kind == SOURCE_STANDARD
    ]
    assert standard
    assert {item.citation.document for item in standard} == {DOCUMENT}
    assert all(item.edition == "2004" for item in standard)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda inp: inp["mild_material_catalog"]["items"][0].__setitem__(
            "description", "Changed published bin description"
        ),
        lambda inp: inp.__setitem__("concrete_material_id", "C35-same-law-B"),
        lambda inp: inp["outer"].__setitem__(1, (0.401, 0.0)),
        lambda inp: inp["bar_elements"][0].__setitem__("material_id", "M-X"),
    ],
)
def test_complete_geometry_material_catalogue_and_concrete_identity_is_sealed(mutation):
    bundle, inp, out = _bundle()
    changed = copy.deepcopy(inp)
    mutation(changed)
    with pytest.raises(TraceValidationError):
        validate_crack_trace_family(
            bundle,
            changed,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context={"case": "SLS-01"},
        )


def test_excluded_values_are_inert_but_presence_position_and_type_are_pinned():
    bundle, inp, out = _bundle()
    inert = copy.deepcopy(inp)
    inert["bar_elements"][0]["fatigue_detail_id"] = "FAT-90"
    inert["sls_member"] = "Slab"
    inert["sls_tendon_xi"] = float("nan")
    assert validate_crack_trace_family(
        bundle,
        inert,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"case": "SLS-01"},
    ) == bundle

    for changed in (
        {**inp, "sls_member": []},
        {**inp, "sls_tendon_xi": []},
    ):
        with pytest.raises(TraceValidationError):
            build_crack_trace_family(
                changed,
                out,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )
    missing = copy.deepcopy(inp)
    del missing["bar_elements"][0]["fatigue_detail_id"]
    with pytest.raises(TraceValidationError, match="fatigue_detail_id"):
        build_crack_trace_family(
            missing,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_success_output_inventory_nested_values_order_and_unknown_siblings_are_fenced():
    bundle, inp, out = _bundle()
    owned = list(out["elastic"])
    for key in owned:
        changed = copy.deepcopy(out)
        del changed["elastic"][key]
        with pytest.raises(TraceValidationError):
            validate_crack_trace_family(
                bundle,
                inp,
                changed,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )

    nested = copy.deepcopy(out)
    nested["elastic"]["crack"]["candidates"][0]["cover"] += 0.25
    reordered = copy.deepcopy(out)
    reordered["elastic"] = dict(reversed(list(reordered["elastic"].items())))
    extra = copy.deepcopy(out)
    extra["elastic"]["crack_coarse"] = None
    stale_scalar = copy.deepcopy(out)
    stale_scalar["elastic"]["lambda_cr_legacy"] = 1.0
    for changed in (nested, reordered, extra, stale_scalar):
        with pytest.raises(TraceValidationError):
            validate_crack_trace_family(
                bundle,
                inp,
                changed,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )


def test_every_published_crack_property_candidate_and_aggregate_field_is_required():
    bundle, inp, out = _bundle()
    paths = []
    for case_key in ("crack", "crack_short"):
        for key in out["elastic"][case_key]:
            paths.append((case_key, None, key))
        for key in out["elastic"][case_key]["candidates"][0]:
            paths.append((case_key, 0, key))
    for property_key in ("props_un", "props_cr"):
        for key in out["elastic"][property_key]:
            paths.append((property_key, None, key))
    for key in out["elastic"]["crack_output"]:
        paths.append(("crack_output", None, key))

    for parent, candidate_index, key in paths:
        changed = copy.deepcopy(out)
        target = changed["elastic"][parent]
        if candidate_index is not None:
            target = target["candidates"][candidate_index]
        del target[key]
        with pytest.raises(TraceValidationError):
            validate_crack_trace_family(
                bundle,
                inp,
                changed,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
                context={"case": "SLS-01"},
            )


def test_branch_input_container_key_order_unknown_sibling_and_duplicates_are_sealed():
    bundle, inp, out = _bundle()
    changed_inputs = []

    container = copy.deepcopy(inp)
    container["bar_elements"] = tuple(container["bar_elements"])
    changed_inputs.append(container)

    record_order = copy.deepcopy(inp)
    record_order["bar_elements"][0] = dict(
        reversed(list(record_order["bar_elements"][0].items()))
    )
    changed_inputs.append(record_order)

    catalogue_order = copy.deepcopy(inp)
    catalogue_order["mild_material_catalog"] = dict(
        reversed(list(catalogue_order["mild_material_catalog"].items()))
    )
    changed_inputs.append(catalogue_order)

    unknown = copy.deepcopy(inp)
    unknown["bar_elements"][0]["future_field"] = "not silently ignored"
    changed_inputs.append(unknown)

    stale_duplicate = copy.deepcopy(inp)
    stale_duplicate["bar_elements"][0]["x_mm"] += 1.0
    changed_inputs.append(stale_duplicate)

    for changed in changed_inputs:
        with pytest.raises(TraceValidationError):
            validate_crack_trace_family(
                bundle,
                changed,
                out,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
                context={"case": "SLS-01"},
            )


def test_positive_finite_independent_area_and_diameter_are_both_preserved():
    inp = _input()
    inp["bar_elements"][0]["size_mode"] = "Independent"
    inp["bar_elements"][0]["diameter_mm"] = 25.0
    out, _combined = _candidate(inp)
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    )
    assert bundle is not None
    assert out["elastic"]["crack"]["candidates"][0]["area_mm2"] != pytest.approx(
        math.pi * 25.0**2 / 4.0
    )
    changed = copy.deepcopy(inp)
    changed["bar_elements"][0]["diameter_mm"] = 26.0
    changed_out, _combined = _candidate(changed)
    assert changed_out["elastic"]["crack"] != out["elastic"]["crack"]


@pytest.mark.parametrize("mode", ["Area", "Diameter"])
def test_derived_size_modes_reject_stale_area_diameter_duplicates(mode):
    inp = _input()
    inp["bar_elements"][0]["size_mode"] = mode
    inp["bar_elements"][0]["diameter_mm"] = 25.0
    out, _combined = _candidate(inp)
    with pytest.raises(TraceValidationError, match="area/diameter"):
        build_crack_trace_family(
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


@pytest.mark.parametrize(
    "key,value",
    [
        ("P_el_l", float("nan")),
        ("Mx_el_s", float("inf")),
        ("conc_Ec", 0.0),
        ("sls_fctm", -1.0),
        ("sls_phi", -0.1),
        ("sls_cw", 1),
        ("sls_dk_na", 0),
    ],
)
def test_original_input_type_finiteness_sign_and_boolean_boundaries(key, value):
    inp = _input(**{key: value})
    out, _combined = _candidate(_input())
    with pytest.raises(TraceValidationError):
        build_crack_trace_family(
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_coherently_resealed_trace_tamper_is_rejected():
    bundle, inp, out = _bundle()
    calculations = list(bundle.calculations)
    first = calculations[0]
    steps = list(first.steps)
    final_index = next(
        index for index, step in enumerate(steps)
        if step.step_id == first.final_step_id
    )
    steps[final_index] = dataclasses.replace(
        steps[final_index],
        result=dataclasses.replace(steps[final_index].result, value=0.123),
    )
    calculations[0] = dataclasses.replace(first, steps=tuple(steps))
    resealed = seal_bundle(dataclasses.replace(
        bundle,
        calculations=tuple(calculations),
        content_sha256="",
    ))
    with pytest.raises(TraceValidationError, match="independent"):
        validate_crack_trace_family(
            resealed,
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context={"case": "SLS-01"},
        )


@pytest.mark.parametrize(
    "code,edition,dk",
    [
        ("DS/EN 1992-1-1 + DK NA", "2004", True),
        ("EN 1992-1-1:2023", "2023", False),
        ("DS/EN 1992-2:2005 + AC:2008", "2004", False),
    ],
)
def test_dk_2023_and_bridge_selectors_are_explicitly_outside_base_slice(
    code, edition, dk
):
    inp = _input(sls_code=code, sls_edition=edition, sls_dk_na=dk)
    assert build_crack_trace_family(
        inp,
        {},
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    ) is None


def test_active_result_cannot_be_deleted_and_uncracked_has_no_fabricated_width():
    inp = _input()
    with pytest.raises(TraceValidationError, match="elastic output"):
        build_crack_trace_family(
            inp,
            {},
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )
    uncracked = _input(Mx_el_l=0.0, Mx_el_s=0.0)
    out, _combined = _candidate(uncracked)
    bundle, _inp, _out = _bundle(uncracked, out)
    assert out["elastic"]["crack_output"]["value"] is None
    assert out["elastic"]["crack_output"]["calculation_state"] == "NOT APPLICABLE"
    assert all(
        calculation.steps[-1].result.state == RESULT_UNDEFINED
        for calculation in bundle.calculations
    )


def test_failure_is_minimal_and_requires_exact_invalid_aggregate(monkeypatch):
    inp = _input()
    _out, combined = _candidate(inp)
    monkeypatch.setattr(
        "sector.crack_trace.solve_elastic_combined",
        lambda *args, **kwargs: dataclasses.replace(combined, converged=False),
    )
    aggregate = {
        "value": None,
        "case": None,
        "governing": None,
        "unit": "mm",
        "calculation_state": "INVALID",
    }
    out = {
        "elastic": {
            "converged": False,
            "unused_failure_number": float("nan"),
            "crack_output": aggregate,
        }
    }
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    )
    assert bundle.calculations[0].steps[-1].result.state == RESULT_FAILED
    changed_value = copy.deepcopy(out)
    changed_value["elastic"]["unused_failure_number"] = 123.0
    assert validate_crack_trace_family(
        bundle,
        inp,
        changed_value,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    ) == bundle
    for changed in (
        {"elastic": {"converged": False}},
        {"elastic": {"converged": False, "crack_output": dict(aggregate, unit="m")}},
        {"elastic": {"converged": False, "crack_output": list(aggregate)}},
    ):
        with pytest.raises(TraceValidationError):
            build_crack_trace_family(
                inp,
                changed,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )

    for key in aggregate:
        changed = copy.deepcopy(out)
        del changed["elastic"]["crack_output"][key]
        with pytest.raises(TraceValidationError):
            build_crack_trace_family(
                inp,
                changed,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )
    reordered = copy.deepcopy(out)
    reordered["elastic"]["crack_output"] = dict(
        reversed(list(aggregate.items()))
    )
    extra = copy.deepcopy(out)
    extra["elastic"]["crack_output"]["future"] = None
    for changed in (reordered, extra):
        with pytest.raises(TraceValidationError):
            build_crack_trace_family(
                inp,
                changed,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )


def test_actual_app_base_payload_matches_independent_replay():
    import test_app_smoke as smoke

    at = smoke._fresh()
    at.run()
    smoke._set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("number_input", "el_short_Mx", 120.0),
        ("checkbox", "sls_cw", True),
        ("selectbox", "sls_code", "EN 1992-1-1:2005"),
    )
    assert not at.exception
    inp = at.session_state["result_input_snapshot"]
    out = at.session_state["results"]
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"case": "app-base"},
    )
    assert bundle is not None
    assert bundle.calculations[-1].steps[-1].result.state == RESULT_FINITE


def test_actual_app_base_payload_with_tendons_keeps_concrete_material_and_element_identity():
    import test_app_smoke as smoke

    at = smoke._fresh_qs(mode="Elastic")
    smoke._set_and_click(at, "qs_apply", ("number_input", "tnd_n", 4))
    smoke._set_and_click(
        at,
        "calculate",
        ("number_input", "el_long_Mx", 400.0),
        ("number_input", "el_short_Mx", 120.0),
        ("checkbox", "sls_cw", True),
        ("selectbox", "sls_code", "EN 1992-1-1:2005"),
    )
    assert not at.exception
    inp = at.session_state["result_input_snapshot"]
    out = at.session_state["results"]
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={"case": "app-tendon"},
    )
    assert bundle is not None
    candidate_ids = {
        item["element_id"]
        for item in out["elastic"]["crack"]["candidates"]
    }
    assert candidate_ids
    assert candidate_ids <= {
        item["id"] for item in inp["bar_elements"] + inp["tendon_elements"]
    }
