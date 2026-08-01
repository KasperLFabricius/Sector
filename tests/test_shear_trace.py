"""Independent CT-006 directional-shear trace acceptance and hostile controls."""

from __future__ import annotations

import copy
import dataclasses
import functools
import math
import pathlib
import sys

import pytest

from sector import capacity, combined
from sector.calculation_trace import (
    RESULT_FAILED,
    TraceAxis,
    TraceDependency,
    TraceResult,
    TraceUnit,
    TraceValidationError,
    bundle_to_json,
    seal_bundle,
)
from sector.shear_trace import build_shear_trace_family, validate_shear_trace_family


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import test_shear as retained_app  # noqa: E402


INPUT_SHA = "1" * 64
RESULT_SHA = "2" * 64
CONTEXT = {"case": "ct006"}


@functools.lru_cache(maxsize=4)
def _cached_case(method=None, links=True):
    at = retained_app._fresh()
    at.run()
    retained_app._set(
        at,
        ("checkbox", "shear_on", True),
        ("checkbox", "shear_links", links),
    )
    if method is not None:
        retained_app._set(at, ("selectbox", "shear_method", method))
    retained_app._set_and_click(
        at,
        "calculate",
        ("number_input", "pl_Mx", 0.0),
        ("number_input", "pl_My", 0.0),
        ("number_input", "shear_Vx", 100.0),
        ("number_input", "shear_Vy", 150.0),
    )
    assert not at.exception
    return (
        copy.deepcopy(at.session_state["result_input_snapshot"]),
        copy.deepcopy(at.session_state["results"]["plastic_cases"][0]["results"]["shear"]),
    )


def _case(method=None, links=True):
    return copy.deepcopy(_cached_case(method, links))


def _bundle(inp, out):
    return build_shear_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA, context=CONTEXT
    )


def _validate(bundle, inp, out, **hashes):
    return validate_shear_trace_family(
        bundle, inp, out,
        input_sha256=hashes.get("input_sha256", INPUT_SHA),
        result_sha256=hashes.get("result_sha256", RESULT_SHA), context=CONTEXT,
    )


def _drop(value, path):
    target = value
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]


def _contexts(inp):
    n_prestress = capacity.prestress_axial(inp)
    return capacity.build_directional_shear_contexts(
        inp, n_prestress, -float(inp["P_pl"]) + n_prestress
    )


def test_01_direction_insertion_order_identity_and_cardinality_are_mandatory():
    inp, out = _case()
    hostiles = []
    reversed_order = copy.deepcopy(out)
    reversed_order["directions"] = dict(reversed(list(reversed_order["directions"].items())))
    hostiles.append(reversed_order)
    missing = copy.deepcopy(out)
    del missing["directions"]["vx"]
    hostiles.append(missing)
    active = copy.deepcopy(out)
    active["active_directions"] = ["vy", "vx"]
    hostiles.append(active)
    faces = copy.deepcopy(out)
    faces["directions"]["vx"]["face_candidates"].reverse()
    hostiles.append(faces)
    for hostile in hostiles:
        with pytest.raises(TraceValidationError):
            _bundle(inp, hostile)


def test_single_vx_and_vy_members_remain_independently_complete():
    inp, out = _case()
    for component, inactive, expected_axis in (("vx", "vy", "y"), ("vy", "vx", "x")):
        one = copy.deepcopy(inp)
        one[f"shear_V{inactive[1]}"] = 0.0
        if one.get("shear_components"):
            one["shear_components"][inactive]["signed_v_ed"] = 0.0
        calculation = _bundle(one, copy.deepcopy(out["directions"][component])).calculations[0]
        axes = dict((axis.name, axis.value) for axis in calculation.axes)
        assert axes["direction_order"] == component
        assert axes["direction_cardinality"] == "1"
        assert axes["direction_axes"] == f"{component}:{expected_axis}"
        assert all(
            not step.step_id.startswith(f"{inactive}-face-")
            for step in calculation.steps
        )
        assert next(step for step in calculation.steps if step.step_id.startswith(f"{component}-face-")).title.startswith(component)


def test_base_method_without_links_closes_concrete_resistance_and_verdict_only():
    inp, out = _case("EN 1992-1-1:2005", links=False)
    calculation = _bundle(inp, out).calculations[0]
    axes = dict((axis.name, axis.value) for axis in calculation.axes)
    assert calculation.method_id == "ec2-2005-directional-shear"
    assert axes["links"] == "disabled"
    assert not any("-link-" in step.step_id for step in calculation.steps)
    vmin = next(step for step in calculation.steps if step.step_id == "method-vmin-rule")
    assert vmin.source.edition == "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010"
    assert vmin.source.citation.clause == "6.2.2(1)"


def test_02_authoritative_failure_precedes_candidate_numeric_parsing(monkeypatch):
    inp, _out = _case()
    failed_inp = copy.deepcopy(inp)
    failed_inp["bars"] = []
    variants = ({}, {"directions": math.nan}, {"shear": {"res": {"vrd_c": math.inf}}})
    bundles = [_bundle(failed_inp, candidate) for candidate in variants]
    assert {bundle_to_json(item) for item in bundles} == {bundle_to_json(bundles[0])}
    assert len(bundles[0].calculations[0].steps) == 2
    assert bundles[0].calculations[0].steps[-1].result.state == RESULT_FAILED

    valid_inp, valid_out = _case()
    with pytest.raises(TraceValidationError):
        _bundle(valid_inp, {"failed": True})

    original = capacity.build_directional_shear_contexts

    def nonfinite(*args, **kwargs):
        contexts = original(*args, **kwargs)
        payload, link = contexts["vx"]["candidates"][0]
        payload = dict(payload, res=dict(payload["res"], vrd_c=math.nan))
        contexts["vx"]["candidates"][0] = (payload, link)
        return contexts

    monkeypatch.setattr("sector.shear_trace_replay.capacity.build_directional_shear_contexts", nonfinite)
    failed = _bundle(valid_inp, valid_out)
    assert failed.calculations[0].steps[-1].result.state == RESULT_FAILED


@pytest.mark.parametrize("path", [
    ("directions", "vx", "face_candidates", 0, "shear", "v_ed"),
    ("directions", "vx", "face_candidates", 0, "shear", "res", "vrd_c"),
    ("directions", "vx", "face_candidates", 0, "shear", "util"),
    ("directions", "vx", "face_candidates", 0, "shear", "links", "res", "vrd"),
    ("directions", "vx", "face_candidates", 0, "shear", "links", "util"),
    ("directions", "vx", "face_candidates", 0, "shear", "links", "delta_ftd"),
    ("directions", "vx", "face_candidates", 0, "shear", "links", "chord", "m_rd"),
    ("directions", "vx", "face_candidates", 0, "shear", "links", "chord", "ok"),
    ("directions", "vx", "face_candidates", 0, "shear_metric"),
    ("directions", "vx", "face_candidates", 0, "shear_status"),
    ("directions", "vx", "governing_face"),
    ("directions", "vx", "status"),
    ("directions", "vx", "governing_domains", "shear"),
])
def test_03_every_advertised_finite_metric_resistance_and_verdict_is_required(path):
    inp, out = _case()
    _drop(out, path)
    with pytest.raises((KeyError, TraceValidationError)):
        _bundle(inp, out)


def _ancestors(calculation, step_id):
    dependencies = {
        step.step_id: {item.step_id for item in step.dependencies}
        for step in calculation.steps
    }
    found, pending = set(), list(dependencies[step_id])
    while pending:
        current = pending.pop()
        if current not in found:
            found.add(current)
            pending.extend(dependencies[current])
    return found


def test_04_dk_vmin_and_nu_sources_are_exact_and_causally_reach_verdicts():
    inp, out = _case()
    calculation = _bundle(inp, out).calculations[0]
    steps = {step.step_id: step for step in calculation.steps}
    vmin, nu = steps["method-vmin-rule"], steps["method-nu-rule"]
    assert (vmin.source.method_id, vmin.source.citation.document, vmin.source.citation.locator) == (
        "dk-na-2024-shear-vmin", "DS/EN 1992-1-1 DK NA:2024", "v_min"
    )
    assert (nu.source.method_id, nu.source.citation.document, nu.source.citation.locator) == (
        "dk-na-2024-shear-nu-v", "DS/EN 1992-1-1 DK NA:2024", "nu_v"
    )
    prefix = "vx-face-00"
    assert "method-vmin-rule" in _ancestors(calculation, f"{prefix}-concrete-v-floor")
    assert f"{prefix}-concrete-v-floor" in _ancestors(calculation, f"{prefix}-concrete-vrd-c")
    assert "method-nu-rule" in _ancestors(calculation, f"{prefix}-link-result-vrd-max")
    assert f"{prefix}-link-result-vrd-max" in _ancestors(calculation, f"{prefix}-link-result-vrd")
    assert f"{prefix}-link-result-vrd" in _ancestors(calculation, f"{prefix}-shear-status")
    assert steps[f"{prefix}-concrete-v-basic"].source.method_id == "ec2-2005-shear-without-links"
    assert steps[f"{prefix}-link-result-cot"].source.citation is None
    assert steps[f"{prefix}-link-longitudinal-force"].source.method_id == "ec2-2005-variable-strut-shear"


def _independent_selector(inp, context, tension_low):
    low, high = context["cot_min"], context["cot_max"]
    axis = context["axis"]
    m_signed = float(inp["Mx_pl" if axis == "x" else "My_pl"])
    m_off = float(inp["My_pl" if axis == "x" else "Mx_pl"])
    m_ed = combined.chord_applied_moment(m_signed, tension_low)
    m_rd, _ = capacity.shear_face_mrd(inp, axis, tension_low, m_off=m_off)
    z = context["z_mm"] / 1000.0
    factor = 1.0 if context.get("model_2023") else 0.5
    best = None
    for index in range(1501):
        cot = low + (high - low) * index / 1500
        result = context["build"](cot, cot)
        values = [context["v_ed"] / result["vrd_s"], context["v_ed"] / result["vrd_max"]]
        if m_rd > 0.0:
            values.append(combined.longitudinal_check(
                m_ed, m_rd, factor * context["v_ed"] * cot, 0.0, z,
                cap_shear_force=not context.get("model_2023"),
            )["util"])
        key = (max(values), sum(values), cot)
        if best is None or key < best[0]:
            best = key, cot
    return best[1]


def _coherent_alternate_cot(inp, out):
    contexts = _contexts(inp)
    for component in ("vx", "vy"):
        root = out["directions"][component]
        for entry, (payload, context) in zip(
            root["face_candidates"], contexts[component]["candidates"], strict=True
        ):
            links = entry["shear"]["links"]
            old = links["res"]["cot"]
            alternate = context["cot_max"] if not math.isclose(old, context["cot_max"]) else context["cot_min"]
            result = context["build"](alternate, alternate)
            links["res"] = result
            links["util"] = context["v_ed"] / result["vrd"]
            factor = 1.0 if context.get("model_2023") else 0.5
            force = factor * context["v_ed"] * result["cot"]
            links["longitudinal_shear_force"] = force
            links["delta_ftd"] = None if context.get("model_2023") else force
            for chord in [links["chord"], *links["chord_candidates"]]:
                chord.update(combined.longitudinal_check(
                    chord["m_ed"], chord["m_rd"], force, 0.0, chord["z"],
                    cap_shear_force=not context.get("model_2023"),
                ))
                chord["valid"] = True
            entry["shear_metric"] = links["util"]
            entry["shear_status"] = "PASS" if links["util"] <= 1.0 + 1e-9 else "FAIL"
        selected = max(range(len(root["face_candidates"])), key=lambda index: capacity.assessment_key(
            root["face_candidates"][index]["shear_status"],
            root["face_candidates"][index]["shear_metric"],
        ))
        chosen = root["face_candidates"][selected]
        face_mode = root["face_mode"]
        root.update(copy.deepcopy(chosen["shear"]))
        root["face_mode"] = face_mode
        root["governing_face"] = "negative" if chosen["tension_low"] else "positive"
        root["status"] = capacity.aggregate_assessment_status(
            item["shear_status"] for item in root["face_candidates"]
        )
        root["governing_domains"]["shear"].update(
            face=root["governing_face"], status=root["status"],
            util=chosen["shear_metric"], cot=chosen["shear"]["links"]["res"]["cot"],
        )
    return out


def test_05_independent_selector_and_coherent_alternate_cot_tamper():
    inp, out = _case()
    contexts = _contexts(inp)
    for component in ("vx", "vy"):
        for entry, tension_low, (_payload, context) in zip(
            out["directions"][component]["face_candidates"],
            capacity.shear_face_candidates("auto", 0.0),
            contexts[component]["candidates"], strict=True,
        ):
            assert entry["shear"]["links"]["res"]["cot"] == pytest.approx(
                _independent_selector(inp, context, tension_low), abs=1.0e-14
            )
    hostile = _coherent_alternate_cot(inp, copy.deepcopy(out))
    with pytest.raises(TraceValidationError):
        _bundle(inp, hostile)


@pytest.mark.parametrize("field", [
    "component", "axis", "method", "tension_low", "asl_bar_ids",
    "associated_moment", "signed_v_ed",
])
def test_candidate_identity_axis_sign_action_and_material_selection_tamper(field):
    inp, out = _case()
    face = out["directions"]["vx"]["face_candidates"][0]
    target = out["directions"]["vx"] if field in {"associated_moment", "signed_v_ed"} else face["shear"]
    value = target[field]
    target[field] = (not value) if type(value) is bool else ([999] if isinstance(value, list) else value + 1 if type(value) in {int, float} else "wrong")
    with pytest.raises(TraceValidationError):
        _bundle(inp, out)


def _reseal(bundle, calculation):
    return seal_bundle(dataclasses.replace(bundle, calculations=(calculation,)))


@pytest.mark.parametrize("kind", [
    "method", "axis", "order", "dependency", "unit", "value", "state", "role",
    "source", "edition", "citation", "duplicate",
])
def test_resealed_method_axis_order_graph_dimension_source_and_value_tamper(kind):
    inp, out = _case()
    bundle = _bundle(inp, out)
    calculation = bundle.calculations[0]
    steps = list(calculation.steps)
    if kind == "method":
        calculation = dataclasses.replace(calculation, method_id="wrong-method")
    elif kind == "axis":
        axes = list(calculation.axes)
        axes[0] = TraceAxis(axes[0].name, "wrong-axis")
        calculation = dataclasses.replace(calculation, axes=tuple(axes))
    elif kind == "order":
        steps[0], steps[1] = steps[1], steps[0]
        calculation = dataclasses.replace(calculation, steps=tuple(steps))
    elif kind == "duplicate":
        calculation = dataclasses.replace(calculation, steps=(*steps, steps[-1]))
    else:
        index = next(i for i, step in enumerate(steps) if step.step_id == "vx-face-00-concrete-vrd-c")
        old = steps[index]
        if kind == "dependency":
            steps[index] = dataclasses.replace(old, dependencies=old.dependencies[:-1])
        elif kind == "unit":
            replacement = TraceUnit("kPa", "stress")
            steps[index] = dataclasses.replace(old, unit=replacement)
            for j, step in enumerate(steps):
                deps = tuple(TraceDependency(dep.step_id, replacement if dep.step_id == old.step_id else dep.unit) for dep in step.dependencies)
                steps[j] = dataclasses.replace(step, dependencies=deps)
        elif kind == "value":
            steps[index] = dataclasses.replace(old, result=TraceResult("finite", old.result.value + 1.0), substituted_expression=old.substituted_expression + " tamper")
        elif kind == "state":
            steps[index] = dataclasses.replace(old, result=TraceResult("failed", None, "promoted"), substituted_expression=old.substituted_expression + " promoted")
        elif kind == "role":
            steps[index] = dataclasses.replace(old, quantity_role="method_value")
        elif kind == "source":
            steps[index] = dataclasses.replace(old, source=steps[index + 1].source)
        elif kind == "edition":
            steps[index] = dataclasses.replace(old, source=dataclasses.replace(old.source, edition="wrong edition"))
        else:
            citation = dataclasses.replace(old.source.citation, locator="wrong locator")
            steps[index] = dataclasses.replace(old, source=dataclasses.replace(old.source, citation=citation))
        calculation = dataclasses.replace(calculation, steps=tuple(steps))
    with pytest.raises(TraceValidationError):
        _validate(_reseal(bundle, calculation), inp, out)


def test_same_kind_and_material_provenance_swaps_stale_seals_and_family_masking():
    inp, out = _case()
    bundle = _bundle(inp, out)
    calculation = bundle.calculations[0]
    steps = list(calculation.steps)
    pairs = [
        ("method-vmin-rule", "method-nu-rule"),
        (next(step.step_id for step in steps if step.step_id.startswith("material-concrete-")),
         next(step.step_id for step in steps if step.step_id.startswith("material-bar-"))),
    ]
    for left_id, right_id in pairs:
        changed = list(steps)
        left = next(i for i, step in enumerate(changed) if step.step_id == left_id)
        right = next(i for i, step in enumerate(changed) if step.step_id == right_id)
        changed[left] = dataclasses.replace(changed[left], source=steps[right].source)
        changed[right] = dataclasses.replace(changed[right], source=steps[left].source)
        with pytest.raises(TraceValidationError):
            _validate(_reseal(bundle, dataclasses.replace(calculation, steps=tuple(changed))), inp, out)
    with pytest.raises(TraceValidationError):
        _validate(bundle, inp, out, input_sha256="3" * 64)
    with pytest.raises(TraceValidationError):
        _validate(bundle, inp, out, result_sha256="4" * 64)
    stale = bundle.to_dict()
    stale["calculations"][0]["steps"][-1]["result"]["value"] = 0.0
    with pytest.raises(TraceValidationError):
        _validate(stale, inp, out)
    unrelated = dataclasses.replace(calculation, calculation_id="other.family", coverage_id="other")
    with pytest.raises(TraceValidationError):
        _validate(_reseal(bundle, unrelated), inp, out)
    with pytest.raises(TraceValidationError):
        _validate(seal_bundle(dataclasses.replace(bundle, calculations=(calculation, unrelated))), inp, out)
    with pytest.raises(TraceValidationError):
        seal_bundle(dataclasses.replace(bundle, calculations=(calculation, calculation)))


def test_unrelated_input_cannot_mask_ct006_and_every_leaf_reaches_its_final():
    inp, out = _case()
    original = _bundle(inp, out)
    unrelated = copy.deepcopy(inp)
    unrelated.update(P_el_s=math.nan, crack_width_on="hostile", fatigue_spectrum=object())
    assert bundle_to_json(_bundle(unrelated, out)) == bundle_to_json(original)
    calculation = original.calculations[0]
    reached = _ancestors(calculation, calculation.final_step_id) | {calculation.final_step_id}
    assert reached == {step.step_id for step in calculation.steps}


def test_nonfinite_finite_candidate_and_2023_lifecycle_source_identity_are_rejected_or_exact():
    inp, out = _case()
    out["directions"]["vx"]["face_candidates"][0]["shear"]["links"]["util"] = math.inf
    with pytest.raises(TraceValidationError):
        _bundle(inp, out)
    inp, out = _case("DS/EN 1992-1-1:2023")
    calculation = _bundle(inp, out).calculations[0]
    assert calculation.method_id == "ec2-2023-published-not-implemented-directional-shear"
    assert dict((axis.name, axis.value) for axis in calculation.axes)["local_lifecycle"] == "published-not-implemented"
    assert any("published-not-implemented" in warning for warning in calculation.warnings)
    method_steps = [step for step in calculation.steps if step.step_id.startswith("method-")]
    assert all(
        "published-not-implemented" in step.source.method_id
        for step in method_steps if step.step_id != "method-selector-cardinality"
    )
    assert any(step.step_id.endswith("-chord-m-rd") for step in calculation.steps)
    _drop(out, ("directions", "vx", "face_candidates", 0, "shear", "links", "chord", "m_rd"))
    with pytest.raises(TraceValidationError):
        _bundle(inp, out)
