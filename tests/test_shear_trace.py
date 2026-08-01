"""CT-006 original-input replay, exact inventories and hostile closure."""

from __future__ import annotations

import copy
import dataclasses
import math

import pytest

from app import sector_app
from sector import codes, combined
from sector.calculation_trace import (
    TraceUnit, TraceValidationError, bundle_to_json, seal_bundle,
)
from sector.section import Section
from sector.shear_trace import build_shear_trace_families, validate_shear_trace_families
import sector.shear_trace_replay as replay
from sector.shear_trace_contract import (
    BASE_ANGLE_SOURCE, BASE_LINK_SOURCE, BASE_LONGITUDINAL_SOURCE,
    BASE_SHEAR_SOURCE, CORE_INPUT_KEYS, DK_NU_SOURCE, DK_VMIN_SOURCE,
    DIRECTION_ORDER, LINK_INPUT_KEYS, PUBLISHED_2023_INPUT_KEYS,
    expected_registry,
)
from sector.trace_registry import audit_trace_registry


INPUT_SHA, RESULT_SHA = "a" * 64, "b" * 64
CONTEXT = {"case": "ct006-final", "stage": 1}


def _input(*, method=codes.EC2_2005_DKNA, links=True, bars=True):
    outer = [(0.0, 0.0), (0.4, 0.0), (0.4, 0.6), (0.0, 0.6)]
    reinforcement = [
        (0.05, 0.05, 800.0), (0.35, 0.05, 700.0),
        (0.35, 0.55, 650.0), (0.05, 0.55, 750.0),
    ] if bars else []
    section = Section.from_polygon(outer, reinforcement)
    concrete, steel = method.concrete(35.0), method.steel(550.0)
    faces = {"vx": "negative", "vy": "negative"}
    signed = {"vx": 75.0, "vy": 85.0}
    return {
        "section": section, "outer": outer, "holes": [], "bars": reinforcement,
        "tendons": [], "concrete": concrete, "steel": steel, "prestress": None,
        "concrete_preset": method.label, "mild_preset": method.label,
        "prestress_preset": "Curve 1 (built-in)",
        "P_pl": 0.0, "Mx_pl": 40.0, "My_pl": 30.0,
        "shear_on": True, "shear_method": method.label,
        "shear_Vx": signed["vx"], "shear_Vy": signed["vy"],
        "shear_face_x": faces["vx"], "shear_face_y": faces["vy"],
        "shear_components": {
            key: {"signed_v_ed": signed[key], "v_ed": abs(signed[key]),
                  "axis": {"vx": "y", "vy": "x"}[key], "face": faces[key],
                  "active": True}
            for key in DIRECTION_ORDER
        },
        "shear_vx_bw": 0.0, "shear_vy_bw": 0.0,
        "shear_vx_link_legs": 2.0, "shear_vy_link_legs": 3.0,
        "shear_links": links, "strut_cot_min": 1.0, "strut_cot_max": 2.5,
        "shear_link_dia": 10.0, "shear_link_s": 150.0, "shear_fywk": 550.0,
        "shear_dlower": 16.0, "transverse_ductility_class": "B",
    }


def _output(inp):
    extrema = replay._canonical_extrema(inp)
    out = {"plastic": dict(extrema, util=0.0)}
    sector_app._run_capacity_checks(inp, out)
    return out


def _build(inp, out):
    return build_shear_trace_families(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA, context=CONTEXT
    )


def _validate(bundle, inp, out):
    return validate_shear_trace_families(
        bundle, inp, out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT,
    )


@pytest.fixture(scope="module")
def case():
    inp = _input()
    out = _output(inp)
    return inp, out, _build(inp, out)


def _steps(calculation):
    return {step.step_id: step for step in calculation.steps}


def test_finite_family_order_axes_inventory_and_oracle(case):
    inp, out, bundle = case
    assert [dict((a.name, a.value) for a in c.axes)["direction"] for c in bundle.calculations] == ["vx", "vy"]
    axes = dict((a.name, a.value) for a in bundle.calculations[0].axes)
    assert axes["physical-axis"] == "y" and axes["face-selector"] == "negative"
    assert axes["face-order"] == "negative"
    steps = _steps(bundle.calculations[0])
    d, bw, asl, fck, gc = (steps[f"face-negative-{k}"].result.value for k in
                           ("d", "bw", "asl", "fck", "gamma-c"))
    k = 1.0 + math.sqrt(200.0 / d)
    rho = min(asl / (bw * d), 0.02)
    basic = (0.18 / gc) * k * (100.0 * rho * fck) ** (1 / 3)
    vmin = (0.051 / gc) * k ** 1.5 * math.sqrt(fck)
    assert steps["face-negative-v-basic"].result.value == pytest.approx(basic)
    assert steps["face-negative-vmin"].result.value == pytest.approx(vmin)
    assert steps["face-negative-vrd-c"].result.value == pytest.approx(max(basic, vmin) * bw * d / 1000)
    assert steps["face-negative-v-basic"].source == BASE_SHEAR_SOURCE
    assert steps["face-negative-vmin"].source == DK_VMIN_SOURCE
    assert steps["face-negative-nu1"].source == DK_NU_SOURCE
    assert steps["face-negative-vrd-s"].source == BASE_LINK_SOURCE
    assert steps["face-negative-cot-limit-hi"].source == BASE_ANGLE_SOURCE
    assert steps["face-negative-longitudinal-shear-force"].source == BASE_LONGITUDINAL_SOURCE
    _validate(bundle, inp, out)


def test_original_face_selector_is_identity_distinct_from_face_order():
    auto = _input(links=False)
    auto["shear_face_x"] = auto["shear_components"]["vx"]["face"] = "auto"
    explicit = copy.deepcopy(auto)
    explicit["shear_face_x"] = explicit["shear_components"]["vx"]["face"] = "negative"
    bundles = [_build(i, _output(i)) for i in (auto, explicit)]
    a0, a1 = (dict((a.name, a.value) for a in b.calculations[0].axes) for b in bundles)
    assert a0["face-order"] == a1["face-order"] == "negative"
    assert (a0["face-selector"], a1["face-selector"]) == ("auto", "negative")


def test_declared_branch_input_inventory_and_ranges_are_closed():
    baseline = _input()
    for key in (*CORE_INPUT_KEYS, *LINK_INPUT_KEYS):
        attack = copy.deepcopy(baseline); attack.pop(key)
        with pytest.raises(TraceValidationError): replay._validated_input(attack)
    p23 = _input(method=codes.EC2_2023)
    for key in PUBLISHED_2023_INPUT_KEYS:
        attack = copy.deepcopy(p23); attack.pop(key)
        with pytest.raises(TraceValidationError): replay._validated_input(attack)
    for key, value in (("P_pl", math.nan), ("shear_vx_bw", -1.0),
                       ("shear_vx_link_legs", 0.0), ("strut_cot_min", 3.0),
                       ("transverse_ductility_class", "D")):
        attack = copy.deepcopy(baseline); attack[key] = value
        if key == "strut_cot_min": attack["strut_cot_max"] = 2.5
        with pytest.raises(TraceValidationError): replay._validated_input(attack)


@pytest.mark.parametrize("field,value", [
    ("scalar", math.nan), ("signed", math.inf), ("absolute", math.nan),
])
def test_nonfinite_demand_is_caught_before_active_filter(field, value):
    baseline = _input(links=False); retained = _output(baseline)
    inp = copy.deepcopy(baseline)
    if field == "scalar": inp["shear_Vx"] = value
    else: inp["shear_components"]["vx"][{"signed": "signed_v_ed", "absolute": "v_ed"}[field]] = value
    states = replay._demand_states(inp)
    assert states[0].invalid
    out = {"shear": retained["shear"]["directions"]["vy"]}
    bundle = _build(inp, out)
    assert bundle.calculations[0].steps[-1].result.state == "failed"
    assert dict((a.name, a.value) for a in bundle.calculations[1].axes)["direction"] == "vy"


def test_active_direction_list_and_actual_mapping_order_are_both_mandatory(case):
    inp, out, _bundle = case
    attacks = []
    missing = copy.deepcopy(out); missing["shear"].pop("active_directions"); attacks.append(missing)
    reversed_list = copy.deepcopy(out); reversed_list["shear"]["active_directions"].reverse(); attacks.append(reversed_list)
    reversed_map = copy.deepcopy(out); d = reversed_map["shear"]["directions"]
    reversed_map["shear"]["directions"] = {"vy": d["vy"], "vx": d["vx"]}; attacks.append(reversed_map)
    nonfinite = copy.deepcopy(out); nonfinite["shear"]["directions"]["vx"]["res"]["vrd_c"] = math.nan; attacks.append(nonfinite)
    for attack in attacks:
        with pytest.raises(TraceValidationError):
            _build(inp, attack)


def _attacks(value):
    if type(value) is dict:
        for key in tuple(value):
            changed = copy.deepcopy(value); changed.pop(key); yield changed
        if len(value) > 1:
            keys = list(value); keys[0], keys[1] = keys[1], keys[0]
            yield {key: copy.deepcopy(value[key]) for key in keys}
        for key, child in value.items():
            for mutation in _attacks(child):
                changed = copy.deepcopy(value); changed[key] = mutation; yield changed
    elif type(value) is list:
        if value: yield copy.deepcopy(value[:-1])
        if len(value) > 1: yield list(reversed(copy.deepcopy(value)))
        for index, child in enumerate(value):
            for mutation in _attacks(child):
                changed = copy.deepcopy(value); changed[index] = mutation; yield changed
    elif value is None: yield 0.0
    elif type(value) is bool: yield not value
    elif type(value) is str: yield value + "-tampered"
    elif type(value) in {int, float}: yield float(value) + 0.125


def test_exhaustive_candidate_inventory_rejects_every_mutation_and_reorder(case):
    expected = case[1]["shear"]
    count = 0
    for attack in _attacks(expected):
        count += 1
        with pytest.raises(TraceValidationError):
            replay.validate_candidate_inventory(attack, expected)
    assert count > 250


def test_coherent_alternate_cot_and_paired_chord_tamper_reject(case):
    inp, out, _bundle = case
    attack = copy.deepcopy(out)
    direction = attack["shear"]["directions"]["vx"]
    for linked in (direction["links"], direction["face_candidates"][0]["shear"]["links"]):
        r = linked["res"]; cot = min(r["cot"] + 0.15, linked["cot_max"])
        r["cot"], r["theta_deg"] = cot, math.degrees(math.atan(1 / cot))
        r["vrd_s"] = r["asw_over_s"] * r["z"] * r["fywd"] * cot / 1000
        r["vrd_max"] = r["alpha_cw"] * direction["bw"] * r["z"] * r["nu1"] * r["fcd"] / (cot + 1 / cot) / 1000
        r["vrd"] = min(r["vrd_s"], r["vrd_max"]); linked["util"] = direction["v_ed"] / r["vrd"]
        linked["longitudinal_shear_force"] = linked["delta_ftd"] = 0.5 * direction["v_ed"] * cot
        c = combined.longitudinal_check(linked["chord"]["m_ed"], linked["chord"]["m_rd"],
                                        linked["delta_ftd"], 0.0, linked["chord"]["z"])
        linked["chord"].update(c); linked["chord_candidates"][0].update(c)
        linked["chord"]["off_util"] += 0.2; linked["chord"]["biaxial"] = True
        linked["chord_candidates"][0]["off_util"] += 0.2; linked["chord_candidates"][0]["biaxial"] = True
    direction["governing_domains"]["shear"]["cot"] = direction["links"]["res"]["cot"]
    direction["governing_domains"]["shear"]["util"] = direction["links"]["util"]
    with pytest.raises(TraceValidationError):
        _build(inp, attack)


def test_concrete_fail_remains_auditable_when_links_pass():
    inp = _input(); inp["shear_Vy"] = inp["shear_components"]["vy"]["signed_v_ed"] = 140.0
    inp["shear_components"]["vy"]["v_ed"] = 140.0
    steps = _steps(_build(inp, _output(inp)).calculations[1])
    concrete = steps["face-negative-concrete-util"].result.value
    linked = steps["face-negative-links-util"].result.value
    assert concrete > 1.0 and linked < 1.0
    assert steps["face-negative-concrete-verdict"].result.value == 0.0
    assert steps["face-negative-links-verdict"].result.value == 1.0
    assert "face-negative-concrete-verdict" in {
        dep.step_id for dep in steps["face-negative-complete-evidence"].dependencies
    }


def test_failed_mechanics_is_minimal_inert_and_cannot_promote():
    inp = _input(links=False, bars=False)
    first = _build(inp, {"shear": {"garbage": math.nan}})
    second = _build(inp, {"shear": {"other": 1e99}})
    assert bundle_to_json(first) == bundle_to_json(second)
    assert all(len(calc.steps) == 2 and calc.steps[-1].result.state == "failed"
               for calc in first.calculations)
    finite = _input(links=False)
    with pytest.raises(TraceValidationError):
        _validate(first, finite, _output(finite))


def test_every_step_reaches_final_and_every_dependency_edge_is_exact(case):
    bundle = case[2]
    shapes = tuple(item.shape for item in replay.replay_shear_evidence(case[0], case[1], CONTEXT).directions)
    registry = expected_registry(shapes); attacked = 0
    for ci, calc in enumerate(bundle.calculations):
        by_id = {step.step_id: step for step in calc.steps}; reached = {calc.final_step_id}; pending = [by_id[calc.final_step_id]]
        while pending:
            pending += [by_id[d.step_id] for d in pending.pop().dependencies if d.step_id not in reached and not reached.add(d.step_id)]
        assert reached == set(by_id)
        for si, step in enumerate(calc.steps):
            for di in range(len(step.dependencies)):
                attacked += 1; steps = list(calc.steps)
                deps = list(step.dependencies); deps.pop(di)
                steps[si] = dataclasses.replace(step, dependencies=tuple(deps))
                calcs = list(bundle.calculations); calcs[ci] = dataclasses.replace(calc, steps=tuple(steps))
                try: mutant = seal_bundle(dataclasses.replace(bundle, calculations=tuple(calcs), content_sha256=""))
                except TraceValidationError: continue
                with pytest.raises(TraceValidationError): audit_trace_registry(mutant, registry)
    assert attacked > 80
    inp, out, bundle = case
    original = bundle.calculations
    attacks = (original[:1], tuple(reversed(original)), (original[0], *original),
               (dataclasses.replace(original[0], method_id="wrong-method"), original[1]),
               (dataclasses.replace(original[0], axes=tuple(reversed(original[0].axes))), original[1]))
    for calculations in attacks:
        with pytest.raises(TraceValidationError):
            _validate(seal_bundle(dataclasses.replace(bundle, calculations=calculations,
                                                       content_sha256="")), inp, out)


def test_sources_units_seals_hashes_unrelated_inputs_and_2023_boundary(case):
    inp, out, bundle = case
    calc, by_id = bundle.calculations[0], _steps(bundle.calculations[0])
    for step_id, wrong_source in (("face-negative-vmin", DK_NU_SOURCE),
                                  ("face-negative-nu1", DK_VMIN_SOURCE)):
        swapped = dataclasses.replace(by_id[step_id], source=wrong_source)
        steps = tuple(swapped if item.step_id == step_id else item for item in calc.steps)
        mutant = seal_bundle(dataclasses.replace(bundle, calculations=(dataclasses.replace(calc, steps=steps), *bundle.calculations[1:]), content_sha256=""))
        with pytest.raises(TraceValidationError): _validate(mutant, inp, out)
    step = by_id["face-negative-vmin"]
    material = next(item for item in calc.steps if item.step_id.startswith("material-bar"))
    concrete = next(item for item in calc.steps if item.step_id.startswith("material-concrete"))
    swapped_material = dataclasses.replace(material, source=concrete.source)
    material_steps = tuple(swapped_material if item.step_id == material.step_id else item for item in calc.steps)
    material_mutant = seal_bundle(dataclasses.replace(bundle, calculations=(dataclasses.replace(calc, steps=material_steps), *bundle.calculations[1:]), content_sha256=""))
    with pytest.raises(TraceValidationError): _validate(material_mutant, inp, out)
    bad_unit = dataclasses.replace(step, unit=TraceUnit("kN", "force"))
    with pytest.raises(TraceValidationError): seal_bundle(dataclasses.replace(bundle, calculations=(dataclasses.replace(calc, steps=tuple(bad_unit if x.step_id == step.step_id else x for x in calc.steps)), *bundle.calculations[1:]), content_sha256=""))
    with pytest.raises(TraceValidationError): validate_shear_trace_families(bundle, inp, out, input_sha256="c" * 64, result_sha256=RESULT_SHA, context=CONTEXT)
    with pytest.raises(TraceValidationError): validate_shear_trace_families(bundle, inp, out, input_sha256=INPUT_SHA, result_sha256="d" * 64, context=CONTEXT)
    unrelated = copy.deepcopy(inp); unrelated.update(v_min=math.nan, v_max=math.inf, torsion_T=math.nan)
    assert _build(unrelated, out).to_dict() == bundle.to_dict()
    plain = _input(links=False); plain_out = _output(plain)
    plain_bundle = _build(plain, plain_out)
    ignored = copy.deepcopy(plain); ignored.update(shear_vx_link_legs=math.nan,
                                                   shear_link_dia=math.inf,
                                                   transverse_ductility_class="invalid")
    assert _build(ignored, plain_out).to_dict() == plain_bundle.to_dict()
    for links in (False, True):
        p23 = _input(method=codes.EC2_2023, links=links); b23 = _build(p23, _output(p23))
        assert "published but not implemented" in " ".join(b23.warnings)
        assert all(step.source.citation is None for calc in b23.calculations for step in calc.steps if step.source.method_id.startswith("published-not-implemented"))
