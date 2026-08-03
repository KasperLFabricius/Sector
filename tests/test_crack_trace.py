from __future__ import annotations

import copy
import dataclasses
import math

import numpy as np
import pytest

from sector import codes
from sector.calculation_trace import (
    RESULT_FAILED, RESULT_FINITE, RESULT_UNDEFINED, SOURCE_STANDARD,
    TraceValidationError, seal_bundle,
)
from sector.crack_trace import build_crack_trace_family, validate_crack_trace_family
from sector.crack_trace_contract import DOCUMENT, RAW_GRADIENT, RAW_STRESS, SECOND_MOMENT
from sector.elastic import solve_elastic_combined, transformed_properties
from sector.materials import ES
from sector.section import Section
from sector.serviceability import analyse_cracking, combined_cracking, crack_width
from sector.sls import crack_outputs


INPUT_SHA, RESULT_SHA = "1" * 64, "2" * 64


def _catalog(law):
    item = {"id": "M1", "name": "B500", "description": "Published bin", "preset": codes.EC2_2005.label}
    for field in dataclasses.fields(law):
        value = getattr(law, field.name)
        if field.name in {"IS", "eut", "ey0t", "ey0c"}:
            value *= 1000.0
        elif field.name == "Es":
            value /= 1000.0
        item[field.name] = value
    return {"version": 1, "next_id": 2, "items": [item]}


def _record(identifier, x, y, diameter, *, mode="Diameter", area=None):
    area = math.pi * diameter**2 / 4.0 if area is None else area
    return {
        "id": identifier, "kind": "bar", "x_mm": x * 1000.0,
        "y_mm": y * 1000.0, "area_mm2": area, "diameter_mm": diameter,
        "size_mode": mode, "material_id": "M1", "fatigue_detail_id": "F160",
        "x": x, "y": y,
    }


def _input(*, empty=False, independent=False, **changes):
    outer = [(0.0, 0.0), (0.4, 0.0), (0.4, 0.6), (0.0, 0.6)]
    records = [] if empty else [
        _record("B1", 0.06, 0.05, 25.0 if independent else 32.0,
                mode="Independent" if independent else "Diameter",
                area=math.pi * 32.0**2 / 4.0),
        _record("B2", 0.34, 0.05, 32.0),
        _record("B3", 0.06, 0.55, 20.0),
        _record("B4", 0.34, 0.55, 20.0),
    ]
    bars = [(item["x"], item["y"], item["area_mm2"]) for item in records]
    section = Section.from_polygon(outer, bars)
    concrete, steel = codes.EC2_2005.concrete(35.0), codes.EC2_2005.steel(500.0)
    ec, creep = 34.0, 2.0
    inp = {
        "section": section, "outer": outer, "holes": [], "bars": bars,
        "tendons": [], "concrete": concrete, "steel": steel, "prestress": None,
        "bar_materials": [steel] * len(records), "tendon_materials": [],
        "concrete_material_id": "C35-A", "concrete_preset": codes.EC2_2005.label,
        "mild_preset": codes.EC2_2005.label,
        "prestress_preset": codes.EC2_2005.label,
        "mild_material_catalog": _catalog(steel),
        "prestress_material_catalog": {"version": 1, "next_id": 1, "items": []},
        "bar_elements": records, "tendon_elements": [], "mode": "Elastic",
        "P_el_l": 0.0, "Mx_el_l": 400.0, "My_el_l": 0.0,
        "P_el_s": 0.0, "Mx_el_s": 120.0, "My_el_s": 0.0,
        "conc_Ec": ec, "el_phi": creep,
        "nl": ES / (ec * 1000.0) * (1.0 + creep), "ns": ES / (ec * 1000.0),
        "sls_fctm": 3.2, "sls_cw": True, "sls_phi": 0.0, "sls_k1": 0.8,
        "sls_tendon_xi": 0.0, "sls_code": "EN 1992-1-1:2005",
        "sls_edition": "2004", "sls_dk_na": False, "sls_member": "Beam",
    }
    inp.update(changes)
    return inp


def _payload(result, identifiers):
    if result is None:
        return None
    def element(index):
        return "Bar", index + 1, identifiers[index]
    def row(item):
        kind, number, identity = element(item.bar_index)
        return {
            "element_type": kind, "element_no": number, "element_id": identity,
            "x_mm": item.x * 1000.0, "y_mm": item.y * 1000.0,
            "area_mm2": item.area, "wk": item.wk, "sr_max": item.sr_max,
            "esm_ecm": item.esm_ecm, "sigma_s": item.sigma_s,
            "rho_p_eff": item.rho_p_eff, "ac_eff": item.ac_eff,
            "hc_ef": item.hc_ef, "phi": item.phi, "cover": item.cover,
            "coarse": item.coarse, "edition": item.edition, "kw": item.kw,
            "k1_r": item.k1_r, "kfl": item.kfl,
            "sr_max_geometric": item.sr_max_geometric,
        }
    kind, number, identity = element(result.gov_bar)
    return {
        "wk": result.wk, "sr_max": result.sr_max, "esm_ecm": result.esm_ecm,
        "sigma_s": result.sigma_s, "rho_p_eff": result.rho_p_eff,
        "ac_eff": result.ac_eff, "hc_ef": result.hc_ef, "phi": result.phi,
        "cover": result.cover, "gov_bar": result.gov_bar + 1,
        "element_type": kind, "element_no": number, "element_id": identity,
        "coarse": result.coarse, "edition": result.edition, "kw": result.kw,
        "k1_r": result.k1_r, "kfl": result.kfl,
        "sr_max_geometric": result.sr_max_geometric,
        "candidates": [row(item) for item in result.candidates],
    }


def _candidate(inp):
    section = inp["section"]
    moduli = np.asarray([law.Es for law in inp["bar_materials"]], dtype=float)
    multipliers = moduli / ES
    p_long, p_short = -inp["P_el_l"], -inp["P_el_s"]
    combined = solve_elastic_combined(
        section, p_long, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
        p_short, inp["Mx_el_s"], inp["My_el_s"], inp["ns"], n_mult=multipliers,
    )
    diameter = [item["diameter_mm"] for item in inp["bar_elements"]]
    k1 = [inp["sls_k1"]] * len(diameter)
    long = analyse_cracking(
        section, p_long, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
        fctm=inp["sls_fctm"], Es=moduli, beta=0.5, kt=0.4,
        bar_diameter=diameter, k1=k1, edition="2004", n_mult=multipliers,
    )
    peak_cracked, peak_factor, peak_sigma = combined_cracking(
        section, p_long, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
        p_short, inp["Mx_el_s"], inp["My_el_s"], inp["ns"],
        fctm=inp["sls_fctm"], n_mult=multipliers,
    )
    if peak_factor < long.lambda_cr:
        cracked, factor, sigma, governing = peak_cracked, peak_factor, peak_sigma, combined.short_term
    else:
        cracked, factor, sigma, governing = long.cracked, long.lambda_cr, long.sigma_ct, long.cracked_state
    props_un = transformed_properties(section, inp["nl"], cracked=False, n_mult=multipliers)
    props_cr = transformed_properties(
        section, inp["nl"], eps0=governing.eps0, kx=governing.kx, ky=governing.ky,
        cracked=True, n_mult=multipliers,
    ) if cracked else None
    if cracked:
        states = (long.cracked_state,
                  dataclasses.replace(combined.short_term,
                                      bar_stress=np.asarray(combined.bar_stress_total)))
        results = [crack_width(
            section, state, ratio, fctm=inp["sls_fctm"], Es=moduli, kt=kt,
            bar_diameter=diameter, k1=k1, edition="2004", n_mult=multipliers,
            reinforcement_types=["mild"] * len(diameter),
        ) for state, ratio, kt in zip(states, (inp["nl"], inp["ns"]), (0.4, 0.6))]
    else:
        results = [None, None]
    ids = [item["id"] for item in inp["bar_elements"]]
    payloads = [_payload(item, ids) for item in results]
    elastic = {
        "converged": True, "cracked": bool(cracked), "lambda_cr": float(factor),
        "sigma_ct": float(sigma), "fctm": inp["sls_fctm"], "show_cw": True,
        "props_un": {key: float(getattr(props_un, key)) for key in ("area", "cx", "cy", "Ix", "Iy", "Ixy")},
        "props_cr": None if props_cr is None else
            {key: float(getattr(props_cr, key)) for key in ("area", "cx", "cy", "Ix", "Iy", "Ixy")},
        "crack": payloads[0], "crack_short": payloads[1],
    }
    if cracked:
        elastic.update(crack_code=inp["sls_code"], crack_edition="2004", crack_member=None)
    elastic["crack_output"] = crack_outputs(
        {"Long-term": payloads[0], "Short-term": payloads[1]}, valid=True)
    return {"elastic": elastic}, combined


def _bundle(inp=None, out=None, context=None):
    inp = _input() if inp is None else inp
    out = _candidate(inp)[0] if out is None else out
    context = {"case": "SLS-01"} if context is None else context
    bundle = build_crack_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA, context=context)
    assert bundle is not None
    return bundle, inp, out


def _reachable(calculation):
    steps = {item.step_id: item for item in calculation.steps}
    found, pending = set(), [calculation.final_step_id]
    while pending:
        key = pending.pop()
        if key not in found:
            found.add(key)
            pending.extend(item.step_id for item in steps[key].dependencies)
    return found


def test_round_trip_exact_order_graph_units_sources_and_formula():
    bundle, inp, out = _bundle()
    assert [next(axis.value for axis in calc.axes if axis.name == "crack_case")
            for calc in bundle.calculations] == ["long-term", "short-term", "aggregate"]
    for calculation in bundle.calculations:
        assert _reachable(calculation) == {item.step_id for item in calculation.steps}
    units = {item.step_id: item.unit for item in bundle.calculations[0].steps}
    assert units["cracked-state-q0"] == RAW_STRESS
    assert units["cracked-state-qx"] == units["cracked-state-qy"] == RAW_GRADIENT
    assert all(item.unit == SECOND_MOMENT for item in bundle.calculations[-1].steps
               if item.step_id.endswith(("-ix", "-iy", "-ixy")))
    candidate = out["elastic"]["crack"]["candidates"][0]
    assert candidate["wk"] == pytest.approx(candidate["sr_max"] * candidate["esm_ecm"], rel=1e-12)
    assert validate_crack_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context={"case": "SLS-01"}) == bundle
    sources = [item.source for calc in bundle.calculations for item in calc.steps
               if item.source.kind == SOURCE_STANDARD]
    assert sources and {item.citation.document for item in sources} == {DOCUMENT}


def test_independent_area_and_diameter_are_separate_positive_inputs():
    inp = _input(independent=True)
    out = _candidate(inp)[0]
    bundle, _inp, _out = _bundle(inp, out, {})
    assert bundle.calculations[-1].steps[-1].result.state == RESULT_FINITE
    assert inp["bar_elements"][0]["area_mm2"] != pytest.approx(math.pi * 25.0**2 / 4.0)
    for mode in ("Area", "Diameter"):
        invalid = copy.deepcopy(inp)
        invalid["bar_elements"][0]["size_mode"] = mode
        with pytest.raises(TraceValidationError, match="area/diameter"):
            build_crack_trace_family(invalid, out, input_sha256=INPUT_SHA,
                                     result_sha256=RESULT_SHA)


def test_empty_reinforcement_produces_undefined_not_applicable_trace():
    inp = _input(empty=True, Mx_el_l=0.0, Mx_el_s=0.0)
    out = _candidate(inp)[0]
    bundle, _inp, _out = _bundle(inp, out, {})
    assert out["elastic"]["crack_output"]["calculation_state"] == "NOT APPLICABLE"
    assert out["elastic"]["crack_output"]["value"] is None
    assert all(calc.steps[-1].result.state == RESULT_UNDEFINED
               for calc in bundle.calculations)


@pytest.mark.parametrize("mutation", [
    lambda value: value["mild_material_catalog"]["items"][0].__setitem__("description", "changed"),
    lambda value: value.__setitem__("concrete_material_id", "same-law-other-id"),
    lambda value: value["bar_elements"][0].__setitem__("x_mm", 61.0),
    lambda value: value["bar_elements"][0].__setitem__("future", "unknown"),
    lambda value: value.__setitem__("bar_elements", tuple(value["bar_elements"])),
])
def test_complete_identity_and_duplicate_representations_are_sealed(mutation):
    bundle, inp, out = _bundle()
    changed = copy.deepcopy(inp)
    mutation(changed)
    with pytest.raises(TraceValidationError):
        validate_crack_trace_family(
            bundle, changed, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
            context={"case": "SLS-01"})


def test_excluded_sibling_values_are_inert_but_type_and_presence_are_pinned():
    bundle, inp, out = _bundle()
    changed = copy.deepcopy(inp)
    changed["bar_elements"][0]["fatigue_detail_id"] = "F90"
    changed["sls_member"] = "Slab"
    changed["sls_tendon_xi"] = float("nan")
    assert validate_crack_trace_family(
        bundle, changed, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context={"case": "SLS-01"}) == bundle
    for key, value in (("sls_member", []), ("sls_tendon_xi", [])):
        invalid = {**inp, key: value}
        with pytest.raises(TraceValidationError):
            build_crack_trace_family(invalid, out, input_sha256=INPUT_SHA,
                                     result_sha256=RESULT_SHA)


def test_every_owned_output_and_nested_leaf_is_required():
    bundle, inp, out = _bundle()
    mutations = []
    for key in out["elastic"]:
        changed = copy.deepcopy(out); del changed["elastic"][key]; mutations.append(changed)
    for parent in ("crack", "crack_short"):
        for key in out["elastic"][parent]:
            changed = copy.deepcopy(out); del changed["elastic"][parent][key]; mutations.append(changed)
        for key in out["elastic"][parent]["candidates"][0]:
            changed = copy.deepcopy(out); del changed["elastic"][parent]["candidates"][0][key]; mutations.append(changed)
    for parent in ("props_un", "props_cr", "crack_output"):
        for key in out["elastic"][parent]:
            changed = copy.deepcopy(out); del changed["elastic"][parent][key]; mutations.append(changed)
    extra = copy.deepcopy(out); extra["elastic"]["crack_coarse"] = None; mutations.append(extra)
    stale = copy.deepcopy(out); stale["elastic"]["lambda_cr_legacy"] = 1.0; mutations.append(stale)
    for changed in mutations:
        with pytest.raises(TraceValidationError):
            validate_crack_trace_family(
                bundle, inp, changed, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
                context={"case": "SLS-01"})


def test_resealed_trace_tamper_is_rejected():
    bundle, inp, out = _bundle()
    calculations = list(bundle.calculations)
    first = calculations[0]
    steps = list(first.steps)
    index = next(i for i, item in enumerate(steps) if item.step_id == first.final_step_id)
    steps[index] = dataclasses.replace(steps[index], result=dataclasses.replace(steps[index].result, value=0.123))
    calculations[0] = dataclasses.replace(first, steps=tuple(steps))
    candidate = seal_bundle(dataclasses.replace(bundle, calculations=tuple(calculations), content_sha256=""))
    with pytest.raises(TraceValidationError, match="independent"):
        validate_crack_trace_family(
            candidate, inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
            context={"case": "SLS-01"})


@pytest.mark.parametrize("code,edition,dk", [
    ("DS/EN 1992-1-1 + DK NA", "2004", True),
    ("EN 1992-1-1:2023", "2023", False),
    ("DS/EN 1992-2:2005 + AC:2008", "2004", False),
])
def test_other_selectors_are_inactive(code, edition, dk):
    inp = _input(sls_code=code, sls_edition=edition, sls_dk_na=dk)
    assert build_crack_trace_family(inp, {}, input_sha256=INPUT_SHA,
                                    result_sha256=RESULT_SHA) is None


def test_active_output_cannot_be_deleted():
    with pytest.raises(TraceValidationError, match="elastic output"):
        build_crack_trace_family(_input(), {}, input_sha256=INPUT_SHA,
                                 result_sha256=RESULT_SHA)


def test_failure_requires_exact_invalid_aggregate_and_ignores_failure_values(monkeypatch):
    inp = _input()
    _out, combined = _candidate(inp)
    monkeypatch.setattr(
        "sector.crack_trace.solve_elastic_combined",
        lambda *args, **kwargs: dataclasses.replace(combined, converged=False))
    aggregate = {"value": None, "case": None, "governing": None, "unit": "mm",
                 "calculation_state": "INVALID"}
    out = {"elastic": {"converged": False, "unused": float("nan"),
                        "crack_output": aggregate}}
    bundle, _inp, _out = _bundle(inp, out, {})
    assert bundle.calculations[0].steps[-1].result.state == RESULT_FAILED
    changed = copy.deepcopy(out); changed["elastic"]["unused"] = 12.0
    assert validate_crack_trace_family(bundle, inp, changed, input_sha256=INPUT_SHA,
                                       result_sha256=RESULT_SHA) == bundle
    for key in aggregate:
        invalid = copy.deepcopy(out); del invalid["elastic"]["crack_output"][key]
        with pytest.raises(TraceValidationError):
            build_crack_trace_family(inp, invalid, input_sha256=INPUT_SHA,
                                     result_sha256=RESULT_SHA)


def test_actual_app_payload_runs_for_base_and_tendons():
    import test_app_smoke as smoke
    scenarios = ((smoke._fresh(), False), (smoke._fresh_qs(mode="Elastic"), True))
    for at, tendons in scenarios:
        if not tendons:
            at.run()
        else:
            smoke._set_and_click(at, "qs_apply", ("number_input", "tnd_n", 4))
        changes = [
            ("number_input", "el_long_Mx", 400.0),
            ("number_input", "el_short_Mx", 120.0),
            ("checkbox", "sls_cw", True),
            ("selectbox", "sls_code", "EN 1992-1-1:2005"),
        ]
        if not tendons:
            changes.insert(0, ("radio", "mode", "Elastic"))
        smoke._set_and_click(at, "calculate", *changes)
        assert not at.exception
        assert build_crack_trace_family(
            at.session_state["result_input_snapshot"], at.session_state["results"],
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
            context={"case": "tendon" if tendons else "base"}) is not None
