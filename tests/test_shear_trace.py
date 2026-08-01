"""CT-006 directional shear oracle, contract, and hostile evidence."""

from __future__ import annotations

import copy
import dataclasses
import math
import pathlib
import sys

import pytest

from sector import capacity, codes, combined, shear
from sector.calculation_trace import (
    RESULT_FAILED, SOURCE_PROJECT, TraceDependency, TraceSource,
    TraceUnit, TraceValidationError, seal_bundle,
)
from sector.plastic import solve_plastic
from sector.section import Section
from sector.shear_trace import build_shear_trace_family, validate_shear_trace_family
from sector.shear_trace_contract import (
    BASE_CONCRETE_SOURCE, BASE_LINK_SOURCE, BASE_NU_SOURCE, BASE_VMIN_SOURCE,
    DK_NU_SOURCE, DK_VMIN_SOURCE,
    PUBLISHED_2023_SOURCE, expected_registry, expected_step_contract,
)
from sector.shear_trace_replay import replay_shear_evidence
from sector.trace_registry import audit_trace_registry


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

INPUT_SHA = "a" * 64
RESULT_SHA = "b" * 64
CONTEXT = {"case": "ct006", "stage": 1}


def _input(method=codes.EC2_2005_DKNA.label, **overrides):
    code = capacity.SHEAR_METHODS[method]
    outer = [(-0.20, -0.30), (0.20, -0.30), (0.20, 0.30), (-0.20, 0.30)]
    bars = [
        (-0.15, -0.24, 650.0), (0.15, -0.24, 550.0),
        (0.15, 0.24, 500.0), (-0.15, 0.24, 600.0),
    ]
    section = Section.from_polygon(outer, bars)
    inp = {
        "section": section, "outer": outer, "holes": [], "bars": bars,
        "tendons": [], "prestress": None,
        "concrete": code.concrete(35.0), "steel": code.steel(500.0),
        "concrete_preset": method, "mild_preset": method,
        "P_pl": 0.0, "Mx_pl": 45.0, "My_pl": -30.0,
        "mode": "Plastic", "check_util": True,
        "v_min": 0.0, "v_max": 360.0, "v_inc": 15.0,
        "shear_on": True, "shear_method": method,
        "shear_Vx": 90.0, "shear_Vy": -110.0,
        "shear_face_x": "auto", "shear_face_y": "auto",
        "shear_vx_bw": 0.0, "shear_vy_bw": 0.0,
        "shear_vx_link_legs": 2.0, "shear_vy_link_legs": 2.0,
        "shear_axis": "x", "shear_tension": True, "shear_V": 0.0,
        "shear_bw": 0.0, "shear_link_legs": 2.0,
        "shear_links": True, "shear_link_dia": 10.0,
        "shear_link_s": 150.0, "shear_fywk": 500.0,
        "strut_cot_min": 1.0, "strut_cot_max": 2.5,
        "shear_dlower": 16.0, "transverse_ductility_class": "B",
        "torsion_on": False, "combined_on": False,
    }
    inp.update(overrides)
    return inp


def _plastic(inp):
    points = solve_plastic(
        inp["section"], inp["concrete"], inp["steel"], -inp["P_pl"],
        0.0, 345.0, 15.0,
        prestress=inp.get("prestress") if inp["section"].tendons else None,
        bar_materials=inp.get("bar_materials"),
        tendon_materials=inp.get("tendon_materials"),
    )
    mx, my = [point.Mx for point in points], [point.My for point in points]
    radial = combined.radial_util_result(mx, my, inp["Mx_pl"], inp["My_pl"])
    return {
        "max_mx": max(mx), "min_mx": min(mx),
        "max_my": max(my), "min_my": min(my),
        "util": radial.utilisation, "converged": all(point.converged for point in points),
    }


def _candidate(inp):
    import sector_app
    out = {"plastic": _plastic(inp)}
    sector_app._run_capacity_checks(inp, out)
    return out


def _build(inp=None, out=None):
    inp = _input() if inp is None else inp
    out = _candidate(inp) if out is None else out
    return build_shear_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT,
    )


def _step(calculation, suffix):
    return next(item for item in calculation.steps if item.step_id.endswith(suffix))


def _axes(calculation):
    return {item.name: item.value for item in calculation.axes}


def _manual_2005_concrete(inp, component):
    spec = capacity.shear_direction_specs(inp)[component]
    tension_low = capacity.shear_face_candidates(spec["face"], spec["moment"])[0]
    area, cx, cy = capacity.gross_area_centroid(inp["outer"], inp["holes"])
    centroid = cy if spec["axis"] == "x" else cx
    asl, cg = shear.tension_reinforcement(inp["bars"], spec["axis"], tension_low, centroid)
    depth = shear.effective_depth(inp["outer"], spec["axis"], tension_low, cg)
    bw = shear.min_web_width(inp["outer"], inp["holes"], spec["axis"])
    code = capacity.SHEAR_METHODS[inp["shear_method"]]
    k = min(1.0 + math.sqrt(200.0 / depth), 2.0)
    rho = min(asl / (bw * depth), 0.02)
    sigma = min((-inp["P_pl"]) / area / 1000.0, 0.2 * inp["concrete"].fcd)
    crd = 0.18 / inp["concrete"].gamma_c
    vmin = code.shear_vmin(k, inp["concrete"].fck, inp["concrete"].gamma_c)
    basic = crd * k * (100.0 * rho * inp["concrete"].fck) ** (1.0 / 3.0) + 0.15 * sigma
    floor = vmin + 0.15 * sigma
    return max(basic, floor, 0.0) * bw * depth / 1000.0


def test_dk_two_direction_oracle_sources_and_causal_chains():
    inp = _input()
    bundle = _build(inp)
    assert [_axes(item)["component"] for item in bundle.calculations] == ["vx", "vy"]
    for calculation, component in zip(bundle.calculations, ("vx", "vy")):
        assert _step(calculation, "-vrd-c").result.value == pytest.approx(
            _manual_2005_concrete(inp, component), rel=2.0e-10
        )
        assert _step(calculation, "-vmin").source == DK_VMIN_SOURCE
        assert _step(calculation, "-nu1").source == DK_NU_SOURCE
        assert _step(calculation, "-concrete-verdict").result.value in {0.0, 1.0}
        assert _step(calculation, "-linked-verdict").result.value in {0.0, 1.0}
        validate_shear_trace_family(
            bundle, inp, _candidate(inp), input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT,
        )


@pytest.mark.parametrize("method", [codes.EC2_2005.label, codes.EC2_2023.label])
def test_base_and_published_not_implemented_variants(method):
    inp = _input(method, shear_Vx=0.0, shear_Vy=90.0)
    calculation = _build(inp).calculations[0]
    # Test-owned resistance oracle from original inputs and the independently
    # retained face/geometry operands (not candidate governing selection).
    asws = _step(calculation, "-asw-over-s").result.value
    z = _step(calculation, "-z").result.value
    fywd = _step(calculation, "-fywd").result.value
    cot = _step(calculation, "-cot").result.value
    bw = _step(calculation, "-bw").result.value
    fcd = _step(calculation, "-fcd").result.value
    assert _step(calculation, "-vrd-s").result.value == pytest.approx(
        asws * z * fywd * cot / 1000.0
    )
    if method == codes.EC2_2005.label:
        assert _step(calculation, "-vmin").source == BASE_VMIN_SOURCE
        assert _step(calculation, "-nu1").source == BASE_NU_SOURCE
        alpha = _step(calculation, "-alpha-cw").result.value
        nu = _step(calculation, "-nu1").result.value
        assert _step(calculation, "-vrd-max").result.value == pytest.approx(
            alpha * bw * z * nu * fcd / (cot + 1.0 / cot) / 1000.0
        )
    else:
        assert _step(calculation, "-tau-rdc").source == PUBLISHED_2023_SOURCE
        assert _step(calculation, "-nu1").source == PUBLISHED_2023_SOURCE
        assert all(step.source.kind == SOURCE_PROJECT or step.source != PUBLISHED_2023_SOURCE
                   for step in calculation.steps)
        assert "published-not-implemented" in " ".join(calculation.warnings)
        rho = _step(calculation, "-rho-l").result.value
        fck = inp["concrete"].fck
        ddg = _step(calculation, "-ddg").result.value
        dkvp = _step(calculation, "-d-kvp").result.value
        gamma_v = _step(calculation, "-gamma-v").result.value
        depth = _step(calculation, "-d").result.value
        fyd = _step(calculation, "-fyd-flex").result.value
        tau_basic = (0.66 / gamma_v) * (100.0 * rho * fck * ddg / dkvp) ** (1.0 / 3.0)
        tau_min = (11.0 / gamma_v) * math.sqrt(fck / fyd * ddg / depth)
        assert _step(calculation, "-tau-rdc").result.value == pytest.approx(max(tau_basic, tau_min))
        assert _step(calculation, "-vrd-max").result.value == pytest.approx(
            bw * 0.5 * fcd * z / (cot + 1.0 / cot) / 1000.0
        )


def test_each_face_keeps_concrete_fail_when_links_pass():
    inp = _input(shear_Vx=0.0, shear_Vy=180.0, Mx_pl=20.0, My_pl=0.0)
    calculation = _build(inp).calculations[0]
    assert _step(calculation, "-concrete-utilisation").result.value > 1.0
    assert _step(calculation, "-concrete-verdict").result.value == 0.0
    assert _step(calculation, "-linked-utilisation").result.value < 1.0
    assert _step(calculation, "-linked-verdict").result.value == 1.0
    assert calculation.steps[-1].result.value == 1.0


def test_direction_and_face_order_cardinality_are_exact():
    inp = _input(Mx_pl=0.0, My_pl=0.0)
    out = _candidate(inp)
    assert tuple(out["shear"]["directions"]) == ("vx", "vy")
    assert [item["tension_low"] for item in out["shear"]["directions"]["vx"]["face_candidates"]] == [True, False]

    reversed_directions = copy.deepcopy(out)
    original = reversed_directions["shear"]["directions"]
    reversed_directions["shear"]["directions"] = {"vy": original["vy"], "vx": original["vx"]}
    with pytest.raises(TraceValidationError):
        _build(inp, reversed_directions)

    reversed_faces = copy.deepcopy(out)
    reversed_faces["shear"]["directions"]["vx"]["face_candidates"].reverse()
    with pytest.raises(TraceValidationError):
        _build(inp, reversed_faces)


def test_failure_is_minimal_inert_and_cannot_be_promoted():
    inp = _input(
        shear_Vx=0.0, shear_Vy=80.0, Mx_pl=30.0, My_pl=0.0,
        bars=[(-0.15, 0.24, 600.0), (0.15, 0.24, 600.0)],
    )
    inp["section"] = Section.from_polygon(inp["outer"], inp["bars"])
    out = _candidate(inp)
    first = _build(inp, out)
    assert first.calculations[0].steps[-1].result.state == RESULT_FAILED

    noisy = copy.deepcopy(out)
    face = noisy["shear"]["face_candidates"][0]
    face["shear"] = {"res": {"vrd_c": math.nan}, "links": {"util": math.inf}}
    noisy["shear"].pop("res", None)
    second = _build(inp, noisy)
    assert first.to_dict() == second.to_dict()

    promoted = copy.deepcopy(noisy)
    promoted["shear"]["status"] = "PASS"
    promoted["shear"]["face_candidates"][0]["shear_status"] = "PASS"
    with pytest.raises(TraceValidationError):
        _build(inp, promoted)


def test_coherent_alternate_cot_and_downstream_payload_is_rejected():
    inp = _input(shear_Vx=0.0, shear_Vy=110.0)
    out = _candidate(inp)
    tampered = copy.deepcopy(out)
    face = tampered["shear"]["face_candidates"][0]
    original_cot = face["shear"]["links"]["res"]["cot"]
    alternate = 1.0 if original_cot > 1.1 else 2.5
    npre = capacity.prestress_axial(inp)
    ncomp = -inp["P_pl"] + npre
    context = capacity.build_directional_shear_contexts(inp, npre, ncomp)["vy"]["candidates"][0][1]
    replacement = context["build"](alternate, alternate)
    demand = face["shear"]["v_ed"]
    util = demand / replacement["vrd"]
    status = "PASS" if util <= 1.0 + 1.0e-9 else "FAIL"
    for target in (face["shear"]["links"], tampered["shear"]["links"]):
        target["res"] = replacement
        target["util"] = util
        target["longitudinal_shear_force"] = 0.5 * demand * alternate
        target["delta_ftd"] = target["longitudinal_shear_force"]
    face["shear_metric"] = util
    face["shear_status"] = status
    tampered["shear"]["status"] = status
    tampered["shear"]["governing_domains"]["shear"].update(cot=alternate, util=util, status=status)
    with pytest.raises(TraceValidationError):
        _build(inp, tampered)


def test_paired_chord_off_util_and_biaxial_tamper_is_rejected():
    inp = _input(shear_Vx=0.0, shear_Vy=100.0)
    out = _candidate(inp)
    tampered = copy.deepcopy(out)
    top = tampered["shear"]["links"]["chord"]
    candidate = tampered["shear"]["face_candidates"][0]["shear"]["links"]["chord"]
    for chord in (top, candidate):
        chord["off_util"] += 0.25
        chord["biaxial"] = chord["off_util"] > 0.05
    with pytest.raises(TraceValidationError):
        _build(inp, tampered)


@pytest.mark.parametrize("field", ["v_ed", "vrd_c", "util", "shear_metric", "shear_status"])
def test_coherent_or_omitted_finite_field_tamper_is_rejected(field):
    inp = _input(shear_Vx=0.0)
    out = _candidate(inp)
    tampered = copy.deepcopy(out)
    face = tampered["shear"]["face_candidates"][0]
    if field == "v_ed":
        face["shear"]["v_ed"] *= 0.8
        tampered["shear"]["v_ed"] *= 0.8
    elif field == "vrd_c":
        face["shear"]["res"]["vrd_c"] *= 1.2
        tampered["shear"]["res"]["vrd_c"] *= 1.2
    elif field == "util":
        face["shear"]["links"]["util"] *= 0.8
        tampered["shear"]["links"]["util"] *= 0.8
    else:
        face.pop(field)
    with pytest.raises(TraceValidationError):
        _build(inp, tampered)


def _reachable(calculation):
    dependencies = {step.step_id: tuple(item.step_id for item in step.dependencies) for step in calculation.steps}
    reached = set()
    stack = [calculation.final_step_id]
    while stack:
        item = stack.pop()
        if item not in reached:
            reached.add(item)
            stack.extend(dependencies[item])
    return reached


def test_every_step_reaches_final_and_every_operand_edge_is_exact():
    inp = _input(shear_Vx=0.0)
    out = _candidate(inp)
    bundle = _build(inp, out)
    replay = replay_shear_evidence(inp, out, CONTEXT)
    registry = expected_registry(tuple(item.shape for item in replay.directions))
    calculation = bundle.calculations[0]
    assert _reachable(calculation) == {step.step_id for step in calculation.steps}

    # Includes the previously orphan-prone chord verdict and links-required edges.
    resealed = 0
    for step_index, step in enumerate(calculation.steps):
        for dependency_index in range(len(step.dependencies)):
            steps = list(calculation.steps)
            dependencies = list(step.dependencies)
            alternatives = [
                prior for prior in calculation.steps[:step_index]
                if prior.unit == dependencies[dependency_index].unit
                and prior.step_id not in {item.step_id for item in dependencies}
            ]
            if len(dependencies) == 1 and alternatives:
                replacement = alternatives[0]
                dependencies[dependency_index] = TraceDependency(
                    replacement.step_id, replacement.unit
                )
            else:
                dependencies.pop(dependency_index)
            steps[step_index] = dataclasses.replace(step, dependencies=tuple(dependencies))
            try:
                tampered = seal_bundle(dataclasses.replace(bundle, calculations=(
                    dataclasses.replace(calculation, steps=tuple(steps)),
                )))
            except TraceValidationError:
                # The core closure guard can reject an orphan before a new seal is
                # issued; otherwise the exact registry must reject the resealed edge.
                continue
            resealed += 1
            with pytest.raises(TraceValidationError):
                audit_trace_registry(tampered, registry)
    assert resealed > 20


def test_dk_source_swaps_and_final_chain_disconnection_are_rejected():
    inp = _input(shear_Vx=0.0)
    out = _candidate(inp)
    bundle = _build(inp, out)
    replay = replay_shear_evidence(inp, out, CONTEXT)
    registry = expected_registry(tuple(item.shape for item in replay.directions))
    calculation = bundle.calculations[0]
    steps = list(calculation.steps)
    vmin_index = next(i for i, step in enumerate(steps) if step.step_id.endswith("-vmin"))
    nu_index = next(i for i, step in enumerate(steps) if step.step_id.endswith("-nu1"))
    for index, source in ((vmin_index, BASE_CONCRETE_SOURCE), (nu_index, BASE_LINK_SOURCE)):
        changed = list(steps)
        changed[index] = dataclasses.replace(changed[index], source=source)
        tampered = seal_bundle(dataclasses.replace(bundle, calculations=(
            dataclasses.replace(calculation, steps=tuple(changed)),
        )))
        with pytest.raises(TraceValidationError):
            audit_trace_registry(tampered, registry)

    # A same-kind standard source with a changed locator is also not interchangeable.
    source = steps[vmin_index].source
    swapped = dataclasses.replace(source, citation=dataclasses.replace(source.citation, locator="wrong same-kind locator"))
    changed = list(steps)
    changed[vmin_index] = dataclasses.replace(changed[vmin_index], source=swapped)
    with pytest.raises(TraceValidationError):
        audit_trace_registry(seal_bundle(dataclasses.replace(bundle, calculations=(
            dataclasses.replace(calculation, steps=tuple(changed)),
        ))), registry)


def test_missing_direction_order_unit_dependency_and_value_tamper_fail():
    inp = _input()
    out = _candidate(inp)
    bundle = _build(inp, out)
    with pytest.raises(TraceValidationError):
        validate_shear_trace_family(
            seal_bundle(dataclasses.replace(bundle, calculations=bundle.calculations[:1])),
            inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA, context=CONTEXT,
        )
    calculation = bundle.calculations[0]
    steps = list(calculation.steps)
    index = next(i for i, step in enumerate(steps) if step.step_id.endswith("-vrd-max"))
    wrong_unit = TraceUnit("kNm", "moment")
    steps[index] = dataclasses.replace(steps[index], unit=wrong_unit)
    for i, step in enumerate(steps):
        steps[i] = dataclasses.replace(step, dependencies=tuple(
            TraceDependency(dep.step_id, wrong_unit if dep.step_id == calculation.steps[index].step_id else dep.unit)
            for dep in step.dependencies
        ))
    tampered_calculation = dataclasses.replace(calculation, steps=tuple(steps))
    tampered = seal_bundle(dataclasses.replace(bundle, calculations=(tampered_calculation, bundle.calculations[1])))
    with pytest.raises(TraceValidationError):
        validate_shear_trace_family(
            tampered, inp, out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT,
        )


@pytest.mark.parametrize("kind", ["method", "axis", "sign", "edition", "duplicate"])
def test_resealed_method_axis_sign_edition_and_duplicate_member_fail(kind):
    inp = _input(shear_Vx=0.0)
    out = _candidate(inp)
    bundle = _build(inp, out)
    calculation = bundle.calculations[0]
    if kind == "duplicate":
        with pytest.raises(TraceValidationError):
            seal_bundle(dataclasses.replace(bundle, calculations=(calculation, calculation)))
        return
    if kind == "method":
        changed = dataclasses.replace(calculation, method_id="wrong-shear-method")
    elif kind in {"axis", "sign"}:
        axes = list(calculation.axes)
        axis_name = "physical_axis" if kind == "axis" else "sign"
        index = next(i for i, axis in enumerate(axes) if axis.name == axis_name)
        axes[index] = dataclasses.replace(
            axes[index], value="wrong-axis" if kind == "axis" else "compression-positive-v"
        )
        changed = dataclasses.replace(calculation, axes=tuple(axes))
    else:
        steps = list(calculation.steps)
        index = next(i for i, step in enumerate(steps) if step.step_id.endswith("-vmin"))
        steps[index] = dataclasses.replace(
            steps[index], source=dataclasses.replace(steps[index].source, edition="wrong edition")
        )
        changed = dataclasses.replace(calculation, steps=tuple(steps))
    tampered = seal_bundle(dataclasses.replace(bundle, calculations=(changed,)))
    with pytest.raises(TraceValidationError):
        validate_shear_trace_family(
            tampered, inp, out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT,
        )


def test_nonfinite_authoritative_intermediate_selects_failure_before_candidate_numbers(monkeypatch):
    inp = _input(shear_Vx=0.0)
    out = _candidate(inp)
    original = capacity.build_directional_shear_contexts

    def broken(*args, **kwargs):
        contexts = original(*args, **kwargs)
        payload, link = contexts["vy"]["candidates"][0]
        payload = dict(payload, res=dict(payload["res"], vrd_c=math.nan))
        contexts["vy"] = dict(contexts["vy"], candidates=[(payload, link)])
        return contexts

    monkeypatch.setattr("sector.shear_trace_replay.capacity.build_directional_shear_contexts", broken)
    out["shear"]["status"] = "INVALID"
    out["shear"]["face_candidates"][0]["shear_status"] = "INVALID"
    out["shear"]["face_candidates"][0]["shear"] = {"res": {"vrd_c": math.inf}}
    assert _build(inp, out).calculations[0].steps[-1].result.state == RESULT_FAILED


def test_unrelated_inputs_material_provenance_and_stale_seals():
    inp = _input(shear_Vx=0.0)
    out = _candidate(inp)
    baseline = _build(inp, out)
    unrelated = dict(inp, P_el_l=math.nan, crack_width=math.inf,
                     v_min=math.nan, v_max=math.inf, v_inc=-math.inf)
    assert _build(unrelated, out).calculations == baseline.calculations

    changed_provenance = dict(inp, concrete_preset=codes.EC2_2005.label)
    with pytest.raises(TraceValidationError):
        validate_shear_trace_family(
            baseline, changed_provenance, out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT,
        )
    with pytest.raises(TraceValidationError):
        validate_shear_trace_family(
            baseline, inp, out, input_sha256="c" * 64,
            result_sha256=RESULT_SHA, context=CONTEXT,
        )
    with pytest.raises(TraceValidationError):
        validate_shear_trace_family(
            baseline, inp, out, input_sha256=INPUT_SHA,
            result_sha256="d" * 64, context=CONTEXT,
        )
    changed_action = dict(inp, Mx_pl=inp["Mx_pl"] + 5.0)
    with pytest.raises(TraceValidationError):
        validate_shear_trace_family(
            baseline, changed_action, out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT,
        )
    raw = baseline.to_dict()
    raw["calculations"][0]["steps"][-1]["result"]["value"] = 0.25
    with pytest.raises(TraceValidationError):
        validate_shear_trace_family(
            raw, inp, out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT,
        )
