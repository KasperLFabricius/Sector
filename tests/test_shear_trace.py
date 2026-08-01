"""CT-006 core oracle, branch, inventory, and hostile trace contracts."""

from __future__ import annotations

import copy
import dataclasses
import math
from collections.abc import Mapping

import pytest

from app import material_catalog
from app.sector_app import _run_capacity_checks
from sector import capacity, codes
from sector.calculation_trace import (
    SOURCE_PROJECT, SOURCE_STANDARD, SourceCitation, TraceDependency, TraceSource,
    TraceUnit, TraceValidationError, seal_bundle,
)
from sector.section import Section
from sector.shear_trace import (
    _replay, _validate_candidate, build_shear_trace_family,
    shear_core_applicability, validate_shear_trace_family,
)
from sector.shear_trace_contract import (
    AGGREGATE_EXCLUDED, BASE_NU_SOURCE, BASE_VMIN_SOURCE, CORE_INPUT_KEYS,
    DK_NU_SOURCE, DK_VMIN_SOURCE, DIRECTIONS, DOC_BASE, FACE_WRAPPER_EXCLUDED,
    GOVERNING_DOMAIN_EXCLUDED, LINK_EXCLUDED, LINK_INPUT_KEYS, SHEAR_EXCLUDED,
    expected_registry,
)
from sector.trace_registry import audit_trace_registry


INPUT_SHA, RESULT_SHA = "a" * 64, "b" * 64
CONTEXT = {"case": "CT-006 core"}

@pytest.fixture(autouse=True)
def _isolate_autosave(monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct006-core-no-autosave")

def _input(*, method=codes.EC2_2005_DKNA, links=True, vx=130.0,
           vy=-150.0, bars=None, **changes):
    outer = [(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)]
    bars = ([(0.05, 0.05, 700.0), (0.25, 0.05, 900.0),
             (0.05, 0.55, 700.0), (0.25, 0.55, 700.0)]
            if bars is None else bars)
    entries = [material_catalog.default_entry(
        "mild", material_id=material_id, preset=method.label
    ) for material_id in ("M1", "M2")]
    steel = material_catalog.build_material(entries[0], "mild")
    components = {
        "vx": {"signed_v_ed": vx, "v_ed": abs(vx), "axis": "y",
               "face": "auto", "active": bool(vx)},
        "vy": {"signed_v_ed": vy, "v_ed": abs(vy), "axis": "x",
               "face": "auto", "active": bool(vy)},
    }
    inp = dict(
        outer=outer, holes=[], bars=bars, tendons=[],
        section=Section.from_polygon(outer, bars),
        concrete=method.concrete(35.0), steel=steel, prestress=None,
        bar_elements=[{"id": f"B{i + 1}", "material_id": "M1"}
                      for i in range(len(bars))], bar_materials=[steel] * len(bars),
        mild_material_catalog={"version": 1, "next_id": 3, "items": entries},
        capacity_steel_material_id="M2",
        concrete_preset=method.label, mild_preset=method.label,
        P_pl=0.0, Mx_pl=0.0, My_pl=0.0, shear_on=True,
        shear_method=method.label, shear_Vx=vx, shear_Vy=vy,
        shear_components=components, shear_face_x="auto", shear_face_y="auto",
        shear_vx_bw=0.0, shear_vy_bw=240.0,
        shear_vx_link_legs=2.0, shear_vy_link_legs=3.0,
        shear_links=links, strut_cot_min=1.0, strut_cot_max=2.5,
        shear_link_dia=10.0, shear_link_s=150.0, shear_fywk=500.0,
        shear_dlower=16.0, torsion_on=False, combined_on=False,
    )
    inp.update(changes)
    return inp

def _candidate(inp):
    out = {}
    _run_capacity_checks(inp, out)
    return out.get("shear", {})

def _bundle(inp, out=None):
    result = build_shear_trace_family(
        inp, _candidate(inp) if out is None else out,
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA, context=CONTEXT,
    )
    assert result is not None
    return result

def _steps(bundle, member="vx"):
    calculation = next(item for item in bundle.calculations
                       if dict((axis.name, axis.value) for axis in item.axes)["direction"] == member)
    return {step.step_id: step for step in calculation.steps}

def test_two_active_is_the_only_family_and_all_demands_precede_filtering():
    assert shear_core_applicability(_input()) == "directional"
    assert len(_bundle(_input(links=False)).calculations) == 2
    for vx, vy, branch in ((0.0, 0.0, "not-applicable-0-active"),
                           (25.0, 0.0, "not-applicable-1-active")):
        inp = _input(vx=vx, vy=vy)
        out = _candidate(inp)
        assert shear_core_applicability(inp) == branch
        assert ("directions" in out) is False
        assert build_shear_trace_family(inp, out, input_sha256=INPUT_SHA,
                                        result_sha256=RESULT_SHA) is None
        assert validate_shear_trace_family(None, inp, out, input_sha256=INPUT_SHA,
                                           result_sha256=RESULT_SHA) is None
    for bad in (math.nan, math.inf, -math.inf):
        inp = _input(vx=0.0, vy=0.0)
        inp["shear_Vy"] = bad
        inp["shear_components"]["vy"].update(signed_v_ed=bad, v_ed=bad)
        with pytest.raises(TraceValidationError, match="finite"):
            shear_core_applicability(inp)
    inp = _input()
    inp["shear_components"]["vx"]["signed_v_ed"] *= -1.0
    with pytest.raises(TraceValidationError, match="signed demands differ"):
        _bundle(inp, {})
    reversed_band = _bundle(_input(strut_cot_min=2.5, strut_cot_max=1.0))
    assert _steps(reversed_band)["input-cot-min"].result.value == 2.5
    for key in (*CORE_INPUT_KEYS, *LINK_INPUT_KEYS):
        inp = _input(); del inp[key]
        with pytest.raises(TraceValidationError):
            _bundle(inp, {})
    with pytest.raises(TraceValidationError, match="implemented 2004"):
        _bundle(_input(method=codes.EC2_2023), {})
    for mode, face in (("auto", "negative"), ("negative", "negative"),
                       ("positive", "positive")):
        inp = _input(My_pl=20.0, shear_face_x=mode)
        inp["shear_components"]["vx"]["face"] = mode
        axes = dict((axis.name, axis.value) for axis in _bundle(inp).calculations[0].axes)
        assert (axes["face_selector"], axes["face_order"]) == (mode, face)

@pytest.mark.parametrize(
    "method,vmin,nu",
    [(codes.EC2_2005, lambda k, f, g: .035*k**1.5*math.sqrt(f),
      lambda f: .6*(1-f/250)),
     (codes.EC2_2005_DKNA, lambda k, f, g: .051/g*k**1.5*math.sqrt(f),
      lambda f: max(.7-f/200, .45))],
)
def test_original_input_oracle_closes_base_and_dk_concrete_links(method, vmin, nu):
    inp = _input(method=method)
    bundle = _bundle(inp)
    steps = _steps(bundle)
    fck, gamma, bw, depth, asl, demand = 35.0, inp["concrete"].gamma_c, 600.0, 250.0, 1400.0, 130.0
    k = min(1 + math.sqrt(200/depth), 2)
    rho = min(asl/(bw*depth), .02)
    basic = .18/gamma*k*(100*rho*fck)**(1/3)
    floor = vmin(k, fck, gamma)
    vrdc = max(basic, floor, 0)*bw*depth/1000
    for name, value in (("k", k), ("rho-l", rho), ("v-basic", basic),
                        ("vmin", floor), ("vrd-c", vrdc),
                        ("concrete-utilisation", demand/vrdc)):
        assert steps[f"face-00-{name}"].result.value == pytest.approx(value)

    z, _ = capacity.shear_lever_arm(inp, "y", True, depth)
    asw_s = 2*math.pi*10**2/4/150
    fywd, nu1, fcd = 500/inp["steel"].gamma_y, nu(fck), inp["concrete"].fcd
    scan = []
    for index in range(1501):
        cot = 1 + 1.5*index/1500
        vs = asw_s*z*fywd*cot/1000
        vmax = bw*z*nu1*fcd/(cot + 1/cot)/1000
        values = (demand/vs, demand/vmax)
        scan.append(((max(values), sum(values), cot), cot, vs, vmax))
    _, cot, vs, vmax = min(scan)
    assert steps["face-00-cot"].result.value == pytest.approx(cot)
    assert steps["face-00-vrd-s"].result.value == pytest.approx(vs)
    assert steps["face-00-vrd-max"].result.value == pytest.approx(vmax)
    assert steps["face-00-links-utilisation"].result.value == pytest.approx(demand/min(vs, vmax))
    assert steps["input-width-override"].result.value == 0.0
    assert steps["face-00-bw-effective"].result.value == pytest.approx(600.0)
    vy_steps = _steps(bundle, "vy")
    assert vy_steps["input-width-override"].result.value == vy_steps["face-00-bw-effective"].result.value == 240.0
    assert steps["face-00-concrete-verdict"].result.value == 0.0
    assert steps["face-00-links-verdict"].result.value == 1.0
    expected_sources = ((DK_VMIN_SOURCE, DK_NU_SOURCE)
                        if method is codes.EC2_2005_DKNA
                        else (BASE_VMIN_SOURCE, BASE_NU_SOURCE))
    assert (steps["face-00-vmin"].source, steps["face-00-nu1"].source) == expected_sources

def test_selected_capacity_steel_identity_controls_exact_source_and_2023_boundary():
    inp = _input(method=codes.EC2_2005)
    bar_entry = inp["mild_material_catalog"]["items"][0]
    bar_entry["preset"] = "Custom / imported"
    steps = _steps(_bundle(inp))
    expected = TraceSource(
        SOURCE_STANDARD, "ec2-2005-bar-law", codes.EC2_2005.label,
        SourceCitation(DOC_BASE, "3.2.7", "design stress-strain law"),
    )
    assert steps["face-00-fywd"].source == expected
    axes = dict((axis.name, axis.value) for axis in _bundle(inp).calculations[0].axes)
    assert axes["capacity_steel_material_id"] == "M2"

    custom = copy.deepcopy(inp)
    custom["mild_material_catalog"]["items"][0]["preset"] = codes.EC2_2005.label
    custom["mild_material_catalog"]["items"][1]["preset"] = "Custom / imported"
    assert _steps(_bundle(custom))["face-00-fywd"].source == TraceSource(
        SOURCE_PROJECT, "project-bar-law"
    )
    future = copy.deepcopy(inp)
    future["mild_material_catalog"]["items"][1]["preset"] = codes.EC2_2023.label
    with pytest.raises(TraceValidationError, match="2023"):
        _bundle(future, {})
    no_links = copy.deepcopy(future)
    no_links["shear_links"] = False
    no_links.pop("capacity_steel_material_id")
    assert _bundle(no_links, _candidate(no_links)) is not None

    for failure in ("duplicate", "missing", "mismatch"):
        broken = _input(method=codes.EC2_2005)
        items = broken["mild_material_catalog"]["items"]
        if failure == "duplicate":
            items.append(copy.deepcopy(items[1]))
        elif failure == "missing":
            items.pop()
        else:
            items[1]["gamma_y"] += 0.01
        with pytest.raises(TraceValidationError):
            _bundle(broken, {})

def _walk(value, excluded, path=()):
    if isinstance(value, Mapping):
        keys = [key for key in value if key not in excluded]
        yield "mapping", path, tuple(keys)
        for key in keys:
            yield from _walk(value[key], excluded, (*path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk(item, excluded, (*path, index))
    else:
        yield "leaf", path, value

def _at(value, path):
    for key in path:
        value = value[key]
    return value

def _replaced(value, path, replacement):
    if not path:
        return replacement
    key, *tail = path
    clone = dict(value) if isinstance(value, Mapping) else list(value)
    clone[key] = _replaced(clone[key], tail, replacement)
    return tuple(clone) if isinstance(value, tuple) else clone

def _mutate_leaf(value):
    if type(value) is bool:
        return not value
    if isinstance(value, (int, float)):
        return value + .271828
    if isinstance(value, str):
        return value + "-tampered"
    return 0.0

def _layer_exclusions(value):
    if "directions" in value and "active_directions" in value:
        return AGGREGATE_EXCLUDED
    if "shear_status" in value and "shear" in value:
        return FACE_WRAPPER_EXCLUDED
    if "angle_limits" in value and "asw_over_s" in value:
        return LINK_EXCLUDED
    domain = value.get("shear")
    if isinstance(domain, Mapping) and {"face", "cot", "status", "util"} <= set(domain):
        return GOVERNING_DOMAIN_EXCLUDED
    if "res" in value and "component" in value and "v_ed" in value:
        return SHEAR_EXCLUDED
    return ()

def _rewrite_excluded(value, operation):
    if isinstance(value, list):
        for item in value:
            _rewrite_excluded(item, operation)
    if not isinstance(value, dict):
        return
    excluded = _layer_exclusions(value)
    for key in tuple(value):
        if key not in excluded:
            _rewrite_excluded(value[key], operation)
    if operation == "remove":
        for key in excluded:
            value.pop(key, None)
    elif operation == "mutate":
        value.update((key, math.nan) for key in excluded)
    else:
        for key in excluded:
            value.setdefault(key, math.nan)
        retained = [(key, item) for key, item in value.items() if key not in excluded]
        omitted = [(key, value[key]) for key in reversed(tuple(excluded))]
        value.clear(); value.update((*omitted, *retained))

def test_every_retained_candidate_field_missing_reordered_or_mutated_fails():
    inp, out = _input(), None; out = _candidate(inp)
    evidence = _replay(inp, out, CONTEXT)
    excluded = set().union(AGGREGATE_EXCLUDED, SHEAR_EXCLUDED, LINK_EXCLUDED,
                           FACE_WRAPPER_EXCLUDED, GOVERNING_DOMAIN_EXCLUDED)
    for kind, path, detail in list(_walk(out, excluded)):
        if kind == "leaf":
            changed = _replaced(copy.deepcopy(out), path, _mutate_leaf(detail))
            with pytest.raises(TraceValidationError):
                _validate_candidate(changed, evidence)
        else:
            changed = copy.deepcopy(out)
            _at(changed, path)["unexpected-ct006-field"] = 0.0
            with pytest.raises(TraceValidationError):
                _validate_candidate(changed, evidence)
            for key in detail:
                changed = copy.deepcopy(out)
                del _at(changed, path)[key]
                with pytest.raises(TraceValidationError):
                    _validate_candidate(changed, evidence)
            if len(detail) > 1:
                changed = copy.deepcopy(out)
                node = _at(changed, path)
                reordered = [(key, node[key]) for key in reversed(detail)]
                node.clear(); node.update(reordered)
                with pytest.raises(TraceValidationError):
                    _validate_candidate(changed, evidence)

def test_every_explicitly_excluded_sibling_is_inert_and_byte_identical():
    inp, out = _input(), None; out = _candidate(inp)
    baseline = _bundle(inp, out).to_dict()
    removed = copy.deepcopy(out)
    _rewrite_excluded(removed, "mutate"); _rewrite_excluded(removed, "remove")
    variants = (removed, copy.deepcopy(out), copy.deepcopy(out))
    _rewrite_excluded(variants[1], "mutate")
    _rewrite_excluded(variants[2], "reorder")
    assert all(_bundle(inp, item).to_dict() == baseline for item in variants)

def test_coherent_alternate_cot_and_recomputed_link_verdict_is_rejected():
    inp, out = _input(), None; out = _candidate(inp)
    evidence = _replay(inp, out, CONTEXT)
    changed = copy.deepcopy(out)
    for direction in DIRECTIONS:
        item = changed["directions"][direction]
        shears = [item, *(face["shear"] for face in item["face_candidates"])]
        for shear in shears:
            link, cot = shear["links"], 1.125
            old = link["res"]
            vs = old["asw_over_s"]*old["z"]*old["fywd"]*cot/1000
            vmax = old["alpha_cw"]*shear["bw"]*old["z"]*old["nu1"]*old["fcd"]/(cot+1/cot)/1000
            old.update(vrd_s=vs, vrd_max=vmax, vrd=min(vs, vmax), cot=cot,
                       theta_deg=math.degrees(math.atan(1/cot)),
                       governs="stirrups (VRd,s)" if vs <= vmax else "crushing (VRd,max)")
            link["util"] = shear["v_ed"]/old["vrd"]
        for face in item["face_candidates"]:
            face["shear_metric"] = face["shear"]["links"]["util"]
            face["shear_status"] = "PASS" if face["shear_metric"] <= 1 + 1e-9 else "FAIL"
        item["status"] = "FAIL" if any(face["shear_status"] == "FAIL" for face in item["face_candidates"]) else "PASS"
        item["governing_domains"]["shear"].update(cot=1.125, status=item["status"],
                                                   util=item["links"]["util"])
    with pytest.raises(TraceValidationError):
        _validate_candidate(changed, evidence)

def test_failure_fields_are_inert_and_unrelated_inputs_cannot_mask_core():
    failed_inp = _input(links=False, bars=[])
    out = _candidate(failed_inp)
    first = _bundle(failed_inp, out)
    changed = copy.deepcopy(out)
    changed["directions"]["vx"], changed["directions"]["vy"] = {}, {"res": {"vrd_c": math.nan}}
    assert _bundle(failed_inp, changed).to_dict() == first.to_dict()
    assert _bundle(failed_inp, _candidate(_input())).to_dict() == first.to_dict()
    assert all(calc.steps[-1].result.state == "failed" for calc in first.calculations)
    inp = _input()
    baseline = _bundle(inp)
    masked = dict(inp, v_min=math.nan, v_max=math.inf, v_inc=-math.inf,
                  torsion_T=math.nan, shear_dlower=math.nan)
    assert _bundle(masked, _candidate(inp)).to_dict() == baseline.to_dict()

def test_registry_edges_reach_final_and_resealed_graph_source_unit_seals_fail():
    inp, out = _input(), None; out = _candidate(inp)
    bundle = _bundle(inp, out)
    evidence = _replay(inp, out, CONTEXT)
    registry = expected_registry(tuple(item.shape for item in evidence))
    for calculation in bundle.calculations:
        by_id = {step.step_id: step for step in calculation.steps}
        reached, pending = set(), [calculation.final_step_id]
        while pending:
            step_id = pending.pop(); reached.add(step_id)
            pending.extend(dep.step_id for dep in by_id[step_id].dependencies if dep.step_id not in reached)
        assert reached == set(by_id)
    for ci, calculation in enumerate(bundle.calculations):
        for si, step in enumerate(calculation.steps):
            for di in range(len(step.dependencies)):
                calculations, steps = list(bundle.calculations), list(calculation.steps)
                steps[si] = dataclasses.replace(step, dependencies=step.dependencies[:di] + step.dependencies[di+1:])
                calculations[ci] = dataclasses.replace(calculation, steps=tuple(steps))
                with pytest.raises(TraceValidationError):
                    audit_trace_registry(seal_bundle(dataclasses.replace(
                        bundle, calculations=tuple(calculations))), registry)
    steps = list(bundle.calculations[0].steps)
    index = next(i for i, step in enumerate(steps) if step.step_id == "face-00-vmin")
    steps[index] = dataclasses.replace(steps[index], source=DK_NU_SOURCE)
    source_calc = dataclasses.replace(bundle.calculations[0], steps=tuple(steps))
    unit, target = TraceUnit("MPa", "stress"), "face-00-vrd-c"
    unit_steps = tuple(dataclasses.replace(step, unit=unit if step.step_id == target else step.unit,
        dependencies=tuple(TraceDependency(dep.step_id, unit if dep.step_id == target else dep.unit)
                           for dep in step.dependencies)) for step in bundle.calculations[0].steps)
    for calculation in (source_calc, dataclasses.replace(bundle.calculations[0], steps=unit_steps)):
        tampered = seal_bundle(dataclasses.replace(bundle, calculations=(calculation, bundle.calculations[1])))
        with pytest.raises(TraceValidationError):
            validate_shear_trace_family(tampered, inp, out, input_sha256=INPUT_SHA,
                                        result_sha256=RESULT_SHA, context=CONTEXT)
    raw = dataclasses.replace(bundle, input_sha256="c"*64)
    for candidate, input_sha, result_sha in ((raw, INPUT_SHA, RESULT_SHA),
        (bundle, "c"*64, RESULT_SHA), (bundle, INPUT_SHA, "c"*64)):
        with pytest.raises(TraceValidationError):
            validate_shear_trace_family(candidate, inp, out, input_sha256=input_sha,
                                        result_sha256=result_sha, context=CONTEXT)
