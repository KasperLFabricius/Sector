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
    FOURTH_METRE,
    KILONEWTON_PER_CUBIC_METRE,
    KILONEWTON_PER_SQUARE_METRE,
)
from sector.elastic import solve_elastic_combined, transformed_properties
from sector.materials import ES
from sector.section import Section
from sector.serviceability import analyse_cracking, combined_cracking, crack_width
from sector.sls import crack_outputs


INPUT_SHA = "1" * 64
RESULT_SHA = "2" * 64
CONTEXT = {"case": "SLS-01"}


def _catalog(material):
    entry = {
        "id": "M1",
        "name": "B500",
        "description": "Published bin identity",
        "preset": codes.EC2_2005.label,
    }
    for field in dataclasses.fields(material):
        value = getattr(material, field.name)
        if field.name in {"IS", "eut", "ey0t", "ey0c"}:
            value *= 1000.0
        elif field.name == "Es":
            value /= 1000.0
        entry[field.name] = value
    return {"version": 1, "next_id": 2, "items": [entry]}


def _bar_record(
    identifier: str,
    x: float,
    y: float,
    diameter: float,
    *,
    size_mode: str = "Diameter",
    area: float | None = None,
):
    actual_area = math.pi * diameter**2 / 4.0 if area is None else area
    return {
        "id": identifier,
        "kind": "bar",
        "x_mm": x * 1000.0,
        "y_mm": y * 1000.0,
        "area_mm2": actual_area,
        "diameter_mm": diameter,
        "size_mode": size_mode,
        "material_id": "M1",
        "fatigue_detail_id": "F160",
        "x": x,
        "y": y,
    }


def _input(*, empty: bool = False, independent: bool = False, **changes):
    outer = [(0.0, 0.0), (0.4, 0.0), (0.4, 0.6), (0.0, 0.6)]
    records = [] if empty else [
        _bar_record(
            "B1",
            0.06,
            0.05,
            25.0 if independent else 32.0,
            size_mode="Independent" if independent else "Diameter",
            area=math.pi * 32.0**2 / 4.0,
        ),
        _bar_record("B2", 0.34, 0.05, 32.0),
        _bar_record("B3", 0.06, 0.55, 20.0),
        _bar_record("B4", 0.34, 0.55, 20.0),
    ]
    bars = [
        (record["x"], record["y"], record["area_mm2"])
        for record in records
    ]
    section = Section.from_polygon(outer, bars)
    concrete = codes.EC2_2005.concrete(35.0)
    steel = codes.EC2_2005.steel(500.0)
    concrete_modulus = 34.0
    creep = 2.0
    snapshot = {
        "section": section,
        "outer": outer,
        "holes": [],
        "bars": bars,
        "tendons": [],
        "concrete": concrete,
        "steel": steel,
        "prestress": None,
        "bar_materials": [steel] * len(records),
        "tendon_materials": [],
        "concrete_material_id": "C35-A",
        "concrete_preset": codes.EC2_2005.label,
        "mild_preset": codes.EC2_2005.label,
        "prestress_preset": codes.EC2_2005.label,
        "mild_material_catalog": _catalog(steel),
        "prestress_material_catalog": {
            "version": 1,
            "next_id": 1,
            "items": [],
        },
        "bar_elements": records,
        "tendon_elements": [],
        "mode": "Elastic",
        "P_el_l": 0.0,
        "Mx_el_l": 400.0,
        "My_el_l": 0.0,
        "P_el_s": 0.0,
        "Mx_el_s": 120.0,
        "My_el_s": 0.0,
        "conc_Ec": concrete_modulus,
        "el_phi": creep,
        "nl": ES / (concrete_modulus * 1000.0) * (1.0 + creep),
        "ns": ES / (concrete_modulus * 1000.0),
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
    snapshot.update(changes)
    return snapshot


def _crack_payload(result, element_ids):
    if result is None:
        return None

    def identity(index):
        return "Bar", index + 1, element_ids[index]

    def row(candidate):
        kind, number, element_id = identity(candidate.bar_index)
        return {
            "element_type": kind,
            "element_no": number,
            "element_id": element_id,
            "x_mm": candidate.x * 1000.0,
            "y_mm": candidate.y * 1000.0,
            "area_mm2": candidate.area,
            "wk": candidate.wk,
            "sr_max": candidate.sr_max,
            "esm_ecm": candidate.esm_ecm,
            "sigma_s": candidate.sigma_s,
            "rho_p_eff": candidate.rho_p_eff,
            "ac_eff": candidate.ac_eff,
            "hc_ef": candidate.hc_ef,
            "phi": candidate.phi,
            "cover": candidate.cover,
            "coarse": candidate.coarse,
            "edition": candidate.edition,
            "kw": candidate.kw,
            "k1_r": candidate.k1_r,
            "kfl": candidate.kfl,
            "sr_max_geometric": candidate.sr_max_geometric,
        }

    kind, number, element_id = identity(result.gov_bar)
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
        "element_id": element_id,
        "coarse": result.coarse,
        "edition": result.edition,
        "kw": result.kw,
        "k1_r": result.k1_r,
        "kfl": result.kfl,
        "sr_max_geometric": result.sr_max_geometric,
        "candidates": [row(candidate) for candidate in result.candidates],
    }


def _retained_output(inp):
    section = inp["section"]
    moduli = np.asarray([material.Es for material in inp["bar_materials"]])
    multipliers = moduli / ES
    long_force = -inp["P_el_l"]
    short_force = -inp["P_el_s"]
    combined = solve_elastic_combined(
        section,
        long_force,
        inp["Mx_el_l"],
        inp["My_el_l"],
        inp["nl"],
        short_force,
        inp["Mx_el_s"],
        inp["My_el_s"],
        inp["ns"],
        n_mult=multipliers,
    )
    diameters = [record["diameter_mm"] for record in inp["bar_elements"]]
    k1 = [inp["sls_k1"]] * len(diameters)
    sustained = analyse_cracking(
        section,
        long_force,
        inp["Mx_el_l"],
        inp["My_el_l"],
        inp["nl"],
        fctm=inp["sls_fctm"],
        Es=moduli,
        beta=0.5,
        kt=0.4,
        bar_diameter=diameters,
        k1=k1,
        edition="2004",
        n_mult=multipliers,
    )
    peak_cracked, peak_factor, peak_tension = combined_cracking(
        section,
        long_force,
        inp["Mx_el_l"],
        inp["My_el_l"],
        inp["nl"],
        short_force,
        inp["Mx_el_s"],
        inp["My_el_s"],
        inp["ns"],
        fctm=inp["sls_fctm"],
        n_mult=multipliers,
    )
    if peak_factor < sustained.lambda_cr:
        cracked = peak_cracked
        factor = peak_factor
        tension = peak_tension
        governing = combined.short_term
    else:
        cracked = sustained.cracked
        factor = sustained.lambda_cr
        tension = sustained.sigma_ct
        governing = sustained.cracked_state
    uncracked_properties = transformed_properties(
        section, inp["nl"], cracked=False, n_mult=multipliers,
    )
    cracked_properties = (
        transformed_properties(
            section,
            inp["nl"],
            eps0=governing.eps0,
            kx=governing.kx,
            ky=governing.ky,
            cracked=True,
            n_mult=multipliers,
        )
        if cracked
        else None
    )
    if cracked:
        states = (
            sustained.cracked_state,
            dataclasses.replace(
                combined.short_term,
                bar_stress=np.asarray(combined.bar_stress_total),
            ),
        )
        crack_results = [
            crack_width(
                section,
                state,
                ratio,
                fctm=inp["sls_fctm"],
                Es=moduli,
                kt=kt,
                bar_diameter=diameters,
                k1=k1,
                edition="2004",
                n_mult=multipliers,
                reinforcement_types=["mild"] * len(diameters),
            )
            for state, ratio, kt in zip(
                states, (inp["nl"], inp["ns"]), (0.4, 0.6)
            )
        ]
    else:
        crack_results = [None, None]
    element_ids = [record["id"] for record in inp["bar_elements"]]
    payloads = [
        _crack_payload(result, element_ids)
        for result in crack_results
    ]

    def properties(value):
        return {
            name: float(getattr(value, name))
            for name in ("area", "cx", "cy", "Ix", "Iy", "Ixy")
        }

    elastic = {
        "converged": True,
        "cracked": bool(cracked),
        "lambda_cr": float(factor),
        "sigma_ct": float(tension),
        "fctm": inp["sls_fctm"],
        "show_cw": True,
        "props_un": properties(uncracked_properties),
        "props_cr": (
            None if cracked_properties is None else properties(cracked_properties)
        ),
        "crack": payloads[0],
        "crack_short": payloads[1],
    }
    if cracked:
        elastic.update(
            crack_code=inp["sls_code"],
            crack_edition="2004",
            crack_member=None,
        )
    elastic["crack_output"] = crack_outputs(
        {"Long-term": payloads[0], "Short-term": payloads[1]},
        valid=True,
    )
    return {"elastic": elastic}, combined


def _bundle(inp=None, out=None, context=None):
    snapshot = _input() if inp is None else inp
    retained = _retained_output(snapshot)[0] if out is None else out
    trace_context = CONTEXT if context is None else context
    bundle = build_crack_trace_family(
        snapshot,
        retained,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=trace_context,
    )
    assert bundle is not None
    return bundle, snapshot, retained


def _reachable(calculation):
    by_id = {step.step_id: step for step in calculation.steps}
    found = set()
    pending = [calculation.final_step_id]
    while pending:
        step_id = pending.pop()
        if step_id in found:
            continue
        found.add(step_id)
        pending.extend(
            dependency.step_id for dependency in by_id[step_id].dependencies
        )
    return found


def test_independent_oracle_round_trip_graph_units_sources_and_formula():
    bundle, inp, out = _bundle()
    assert [
        next(axis.value for axis in calculation.axes if axis.name == "crack_case")
        for calculation in bundle.calculations
    ] == ["long-term", "short-term", "aggregate"]
    for calculation in bundle.calculations:
        assert _reachable(calculation) == {
            step.step_id for step in calculation.steps
        }
    units = {step.step_id: step.unit for step in bundle.calculations[0].steps}
    assert units["cracked-state-q0"] == KILONEWTON_PER_SQUARE_METRE
    assert units["cracked-state-qx"] == KILONEWTON_PER_CUBIC_METRE
    assert units["cracked-state-qy"] == KILONEWTON_PER_CUBIC_METRE
    assert all(
        step.unit == FOURTH_METRE
        for step in bundle.calculations[-1].steps
        if step.step_id.endswith(("-ix", "-iy", "-ixy"))
    )
    candidate = out["elastic"]["crack"]["candidates"][0]
    assert candidate["wk"] == pytest.approx(
        candidate["sr_max"] * candidate["esm_ecm"], rel=1e-12
    )
    standard_sources = [
        step.source
        for calculation in bundle.calculations
        for step in calculation.steps
        if step.source.kind == SOURCE_STANDARD
    ]
    assert standard_sources
    assert {source.citation.document for source in standard_sources} == {DOCUMENT}
    assert validate_crack_trace_family(
        bundle,
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    ) == bundle


@pytest.mark.parametrize("edition,dk_na", [("2023", False), ("2004", True)])
def test_mismatched_base_selector_flags_are_inactive(edition, dk_na):
    inp = _input(sls_edition=edition, sls_dk_na=dk_na)
    assert build_crack_trace_family(
        inp, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
    ) is None


@pytest.mark.parametrize(
    "code,edition,dk_na",
    [
        ("DS/EN 1992-1-1 + DK NA", "2004", True),
        ("EN 1992-1-1:2023", "2023", False),
        ("DS/EN 1992-2:2005 + AC:2008", "2004", False),
    ],
)
def test_other_code_selectors_are_inactive(code, edition, dk_na):
    inp = _input(sls_code=code, sls_edition=edition, sls_dk_na=dk_na)
    assert build_crack_trace_family(
        inp, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
    ) is None


def test_fresh_unknown_or_reordered_element_schema_is_rejected():
    inp = _input()
    out = _retained_output(inp)[0]
    extra = copy.deepcopy(inp)
    extra["bar_elements"][0]["future"] = "unknown"
    with pytest.raises(TraceValidationError, match="exact current schema"):
        build_crack_trace_family(
            extra, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )
    reordered = copy.deepcopy(inp)
    record = reordered["bar_elements"][0]
    reordered["bar_elements"][0] = {
        "kind": record["kind"],
        **{key: value for key, value in record.items() if key != "kind"},
    }
    with pytest.raises(TraceValidationError, match="exact current schema"):
        build_crack_trace_family(
            reordered, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


def test_failed_replay_rejects_every_extra_crack_owned_surface(monkeypatch):
    inp = _input()
    successful_out, combined = _retained_output(inp)
    monkeypatch.setattr(
        "sector.crack_trace.solve_elastic_combined",
        lambda *args, **kwargs: dataclasses.replace(combined, converged=False),
    )
    invalid_aggregate = {
        "value": None,
        "case": None,
        "governing": None,
        "unit": "mm",
        "calculation_state": "INVALID",
    }
    base = copy.deepcopy(successful_out)
    base["elastic"]["converged"] = False
    base["elastic"]["lambda_cr"] = float("nan")
    base["elastic"]["crack_output"] = invalid_aggregate
    base["elastic"]["stress_outputs"] = {"arbitrary": float("nan")}
    bundle, _inp, _retained = _bundle(inp, base, {})
    assert bundle.calculations[0].steps[-1].result.state == RESULT_FAILED
    changed = copy.deepcopy(base)
    changed["elastic"]["stress_outputs"]["arbitrary"] = 123.0
    changed["elastic"]["lambda_cr"] = 999.0
    assert validate_crack_trace_family(
        bundle,
        inp,
        changed,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context={},
    ) == bundle
    for key, value in (
        ("crack_utilisation", 0.25),
        ("crack_verdict", "PASS"),
        ("crack_future", {"value": 1.0}),
        ("props_future", {"area": 1.0}),
        ("sls_limit_source", "legacy"),
    ):
        hostile = copy.deepcopy(base)
        hostile["elastic"][key] = value
        with pytest.raises(TraceValidationError, match="inventory/order"):
            build_crack_trace_family(
                inp,
                hostile,
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )
    missing = copy.deepcopy(base)
    del missing["elastic"]["props_cr"]
    with pytest.raises(TraceValidationError, match="inventory/order"):
        build_crack_trace_family(
            inp, missing, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


def test_empty_reinforcement_is_explicitly_not_applicable():
    inp = _input(empty=True, Mx_el_l=0.0, Mx_el_s=0.0)
    out = _retained_output(inp)[0]
    bundle, _inp, _out = _bundle(inp, out, {})
    assert out["elastic"]["crack_output"]["calculation_state"] == "NOT APPLICABLE"
    assert out["elastic"]["crack_output"]["value"] is None
    assert all(
        calculation.steps[-1].result.state == RESULT_UNDEFINED
        for calculation in bundle.calculations
    )


def test_independent_area_and_diameter_are_distinct_positive_identities():
    inp = _input(independent=True)
    out = _retained_output(inp)[0]
    bundle, _inp, _out = _bundle(inp, out, {})
    assert bundle.calculations[-1].steps[-1].result.state == RESULT_FINITE
    assert inp["bar_elements"][0]["area_mm2"] != pytest.approx(
        math.pi * inp["bar_elements"][0]["diameter_mm"] ** 2 / 4.0
    )
    for mode in ("Area", "Diameter"):
        hostile = copy.deepcopy(inp)
        hostile["bar_elements"][0]["size_mode"] = mode
        with pytest.raises(
            TraceValidationError, match="area/diameter|area-derived diameter"
        ):
            build_crack_trace_family(
                hostile, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
            )


@pytest.mark.parametrize("area", [0.0, -1.0])
def test_independent_area_must_be_strictly_positive_in_all_representations(area):
    inp = _input(independent=True)
    inp["bar_elements"][0]["area_mm2"] = area
    inp["bars"][0] = (
        inp["bar_elements"][0]["x"],
        inp["bar_elements"][0]["y"],
        area,
    )
    inp["section"] = Section.from_polygon(inp["outer"], inp["bars"])
    with pytest.raises(TraceValidationError, match="positive finite"):
        build_crack_trace_family(
            inp, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


def test_near_equal_duplicate_geometry_is_rejected_exactly():
    inp = _input()
    inp["bar_elements"][0]["x_mm"] = math.nextafter(
        inp["bar_elements"][0]["x_mm"], math.inf
    )
    with pytest.raises(TraceValidationError, match="stale relative"):
        build_crack_trace_family(
            inp, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["mild_material_catalog"]["items"][0].__setitem__(
            "description", "changed"
        ),
        lambda value: value.__setitem__("concrete_material_id", "same-law-other-id"),
        lambda value: value["bar_elements"][0].__setitem__("x_mm", 61.0),
        lambda value: value.__setitem__("bar_elements", tuple(value["bar_elements"])),
        lambda value: value["outer"].reverse(),
    ],
)
def test_complete_typed_geometry_and_material_identity_is_sealed(mutation):
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
            context=CONTEXT,
        )


def test_excluded_sibling_values_are_inert_but_presence_and_type_are_pinned():
    bundle, inp, out = _bundle()
    changed = copy.deepcopy(inp)
    changed["bar_elements"][0]["fatigue_detail_id"] = "F90"
    changed["sls_member"] = "Slab"
    changed["sls_tendon_xi"] = float("nan")
    assert validate_crack_trace_family(
        bundle,
        changed,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    ) == bundle
    for key, value in (("sls_member", []), ("sls_tendon_xi", [])):
        hostile = {**inp, key: value}
        with pytest.raises(TraceValidationError):
            build_crack_trace_family(
                hostile, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
            )
    missing = dict(inp)
    del missing["sls_member"]
    with pytest.raises(TraceValidationError, match="requires sls_member"):
        build_crack_trace_family(
            missing, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


def test_every_owned_output_and_nested_candidate_leaf_is_required():
    bundle, inp, out = _bundle()
    mutations = []
    for key in out["elastic"]:
        changed = copy.deepcopy(out)
        del changed["elastic"][key]
        mutations.append(changed)
    for parent in ("crack", "crack_short"):
        for key in out["elastic"][parent]:
            changed = copy.deepcopy(out)
            del changed["elastic"][parent][key]
            mutations.append(changed)
        for row in out["elastic"][parent]["candidates"]:
            for key in row:
                changed = copy.deepcopy(out)
                del changed["elastic"][parent]["candidates"][0][key]
                mutations.append(changed)
    for parent in ("props_un", "props_cr", "crack_output"):
        for key in out["elastic"][parent]:
            changed = copy.deepcopy(out)
            del changed["elastic"][parent][key]
            mutations.append(changed)
    unknown = copy.deepcopy(out)
    unknown["elastic"]["crack_future"] = None
    mutations.append(unknown)
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


def test_coherently_resealed_trace_tamper_is_rejected():
    bundle, inp, out = _bundle()
    calculations = list(bundle.calculations)
    first = calculations[0]
    steps = list(first.steps)
    final_position = next(
        index for index, step in enumerate(steps)
        if step.step_id == first.final_step_id
    )
    steps[final_position] = dataclasses.replace(
        steps[final_position],
        result=dataclasses.replace(steps[final_position].result, value=0.123),
    )
    calculations[0] = dataclasses.replace(first, steps=tuple(steps))
    hostile = seal_bundle(dataclasses.replace(
        bundle,
        calculations=tuple(calculations),
        content_sha256="",
    ))
    with pytest.raises(TraceValidationError, match="independent"):
        validate_crack_trace_family(
            hostile,
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context=CONTEXT,
        )


def test_active_output_cannot_be_omitted():
    with pytest.raises(TraceValidationError, match="elastic output"):
        build_crack_trace_family(
            _input(), {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


def test_removed_crack_limit_input_cannot_reenter_current_schema():
    inp = _input(sls_crack_limit=0.3)
    with pytest.raises(TraceValidationError, match="removed sls_crack_limit"):
        build_crack_trace_family(
            inp, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


def test_actual_application_payload_runs_for_base_and_tendons():
    import test_app_smoke as smoke

    scenarios = ((smoke._fresh(), False), (smoke._fresh_qs(mode="Elastic"), True))
    for app_test, with_tendons in scenarios:
        if with_tendons:
            smoke._set_and_click(
                app_test, "qs_apply", ("number_input", "tnd_n", 4)
            )
        else:
            app_test.run()
        changes = [
            ("number_input", "el_long_Mx", 400.0),
            ("number_input", "el_short_Mx", 120.0),
            ("checkbox", "sls_cw", True),
            ("selectbox", "sls_code", "EN 1992-1-1:2005"),
        ]
        if not with_tendons:
            changes.insert(0, ("radio", "mode", "Elastic"))
        smoke._set_and_click(app_test, "calculate", *changes)
        assert not app_test.exception
        assert build_crack_trace_family(
            app_test.session_state["result_input_snapshot"],
            app_test.session_state["results"],
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context={"case": "tendon" if with_tendons else "base"},
        ) is not None
