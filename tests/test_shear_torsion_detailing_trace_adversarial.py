"""Hostile PR-08C trace evidence and failure-closure controls."""

from __future__ import annotations

import copy
import dataclasses
import math

import pytest

from sector import capacity, codes, combined, detailing
from sector.calculation_trace import (
    RESULT_FINITE,
    SourceCitation,
    TraceAxis,
    TraceResult,
    TraceUnit,
    TraceValidationError,
    bundle_to_json,
    create_bundle,
    validate_bundle,
)
from sector.shear_torsion_detailing_trace import (
    _detailing_evidence,
    _shear_evidence,
    build_detailing_trace_family,
    build_shear_trace_family,
    build_torsion_trace_family,
)
from sector.shear_torsion_detailing_trace_contract import expected_registry
from sector.trace_registry import audit_trace_registry
from tests.test_shear_torsion_detailing_trace import (
    CONTEXT,
    INPUT_SHA,
    RESULT_SHA,
    _detail_output,
    _input,
    _shear_output,
    _torsion_output,
)


def _shear_bundle(inp=None, out=None):
    inp = _input(torsion_on=False) if inp is None else inp
    out = _shear_output(inp) if out is None else out
    return build_shear_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT,
    )


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("missing-direction", "order/cardinality"),
        ("extra-direction", "order/cardinality"),
        ("missing-face", "cardinality"),
        ("wrong-axis", "axis"),
        ("wrong-sign", "signed_v_ed"),
        ("wrong-method", "method"),
    ],
)
def test_direction_member_method_axis_sign_and_cardinality_fail_closed(
    mutation, match
):
    inp = _input(torsion_on=False, Mx_pl=0.0, My_pl=0.0)
    out = _shear_output(inp)
    directions = out["shear"]["directions"]
    if mutation == "missing-direction":
        directions.pop("vx")
    elif mutation == "extra-direction":
        directions["vz"] = copy.deepcopy(directions["vy"])
    elif mutation == "missing-face":
        directions["vx"]["face_candidates"].pop()
    elif mutation == "wrong-axis":
        directions["vx"]["face_candidates"][0]["shear"]["axis"] = "x"
    elif mutation == "wrong-sign":
        directions["vx"]["signed_v_ed"] *= -1.0
    elif mutation == "wrong-method":
        directions["vx"]["face_candidates"][0]["shear"]["method"] = (
            codes.EC2_2005.label
        )
    with pytest.raises(TraceValidationError, match=match):
        _shear_bundle(inp, out)


def test_face_order_and_governing_face_cannot_be_candidate_selected():
    inp = _input(
        torsion_on=False, shear_Vx=0.0, shear_Vy=70.0,
        Mx_pl=0.0, My_pl=0.0,
    )
    out = _shear_output(inp)
    direction = out["shear"]
    direction["face_candidates"].reverse()
    with pytest.raises(TraceValidationError, match="face"):
        _shear_bundle(inp, out)

    out = _shear_output(inp)
    direction = out["shear"]
    direction["governing_face"] = (
        "positive" if direction["governing_face"] == "negative" else "negative"
    )
    with pytest.raises(TraceValidationError, match="governing face"):
        _shear_bundle(inp, out)


def test_coherent_demand_resistance_utilisation_and_verdict_tamper_is_rejected():
    inp = _input(torsion_on=False)
    out = _shear_output(inp)
    candidate = out["shear"]["directions"]["vx"]["face_candidates"][0]
    shear = candidate["shear"]
    shear["v_ed"] *= 1.10
    shear["links"]["res"]["vrd"] *= 1.10
    shear["links"]["util"] = shear["v_ed"] / shear["links"]["res"]["vrd"]
    candidate["shear_metric"] = shear["links"]["util"]
    candidate["shear_status"] = (
        "PASS" if candidate["shear_metric"] <= 1.0 else "FAIL"
    )
    with pytest.raises(TraceValidationError, match="v_ed"):
        _shear_bundle(inp, out)


def test_link_input_and_nonfinite_intermediate_tamper_is_rejected():
    inp = _input(torsion_on=False)
    out = _shear_output(inp)
    links = out["shear"]["directions"]["vy"]["face_candidates"][0][
        "shear"
    ]["links"]
    links["fywk"] = 600.0
    with pytest.raises(TraceValidationError, match="fywk"):
        _shear_bundle(inp, out)

    out = _shear_output(inp)
    out["shear"]["directions"]["vy"]["face_candidates"][0]["shear"][
        "links"
    ]["res"]["vrd_max"] = math.nan
    with pytest.raises(TraceValidationError, match="vrd_max"):
        _shear_bundle(inp, out)


def test_coherent_alternate_cot_is_rejected_for_shear_and_torsion():
    shear_inp = _input(torsion_on=False)
    shear_out = _shear_output(shear_inp)
    n_prestress = capacity.prestress_axial(shear_inp)
    n_comp = -shear_inp["P_pl"] + n_prestress
    shear_context = capacity.build_directional_shear_contexts(
        shear_inp, n_prestress, n_comp
    )["vx"]
    payload, link_context = shear_context["candidates"][0]
    alternate = 1.25
    def shear_at(cot):
        return link_context["build"](cot, cot)

    selected, _ = combined.governing_strut_cot(
        (
            lambda cot: combined.ratio(payload["v_ed"], shear_at(cot)["vrd_s"]),
            lambda cot: combined.ratio(payload["v_ed"], shear_at(cot)["vrd_max"]),
        ),
        link_context["cot_min"],
        link_context["cot_max"],
    )
    assert alternate != pytest.approx(
        selected
    )
    alternate_result = link_context["build"](alternate, alternate)
    wrapper = shear_out["shear"]["directions"]["vx"]["face_candidates"][0]
    wrapper["shear"]["links"]["res"] = alternate_result
    alternate_util = payload["v_ed"] / alternate_result["vrd"]
    wrapper["shear"]["links"]["util"] = alternate_util
    wrapper["shear_metric"] = alternate_util
    wrapper["shear_status"] = (
        "PASS" if alternate_util <= 1.0 + 1.0e-9 else "FAIL"
    )
    with pytest.raises(TraceValidationError, match="links.res"):
        build_shear_trace_family(
            shear_inp,
            shear_out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )

    torsion_inp = _input(shear_on=False)
    torsion_out = _torsion_output(torsion_inp)
    torsion_context = capacity.build_torsion_context(torsion_inp, 0.0)
    alternate = 1.10
    def torsion_at(cot):
        kwargs = dict(
            torsion_context["_tk"], cot_min=cot, cot_max=cot
        )
        return capacity.tube_torsion(
            torsion_context["subtubes"][0],
            torsion_context["ted_parts"][0],
            **kwargs,
        )

    selected, _ = combined.governing_strut_cot(
        (lambda cot: torsion_at(cot)["util"],),
        torsion_context["tcot_min"],
        torsion_context["tcot_max"],
    )
    assert alternate != pytest.approx(selected)
    kwargs = dict(
        torsion_context["_tk"], cot_min=alternate, cot_max=alternate
    )
    alternate_result = capacity.tube_torsion(
        torsion_context["subtubes"][0],
        torsion_context["ted_parts"][0],
        **kwargs,
    )
    actual = torsion_out["torsion"]
    actual["primary"] = alternate_result
    for key in (
        "tube", "trd_s", "trd_max", "trd_c", "cot", "theta_deg",
        "nu", "governs",
    ):
        actual[key] = alternate_result[key]
    actual["trd"] = alternate_result["trd"]
    actual["asl_req"] = alternate_result["asl_req"]
    actual["util"] = alternate_result["util"]
    with pytest.raises(TraceValidationError, match="torsion tube"):
        build_torsion_trace_family(
            torsion_inp,
            torsion_out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_torsion_coherent_tube_and_aggregate_tamper_is_rejected():
    inp = _input(shear_on=False)
    out = _torsion_output(inp)
    primary = out["torsion"]["primary"]
    primary["trd"] *= 1.20
    primary["util"] = primary["t_ed"] / primary["trd"]
    out["torsion"]["trd"] = primary["trd"]
    out["torsion"]["util"] = primary["util"]
    with pytest.raises(TraceValidationError, match="torsion tube"):
        build_torsion_trace_family(
            inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


def test_custom_positive_gamma_ct_is_preserved_and_wrong_method_is_rejected():
    inp = _input(shear_on=False, torsion_gamma_ct=2.05)
    bundle = build_torsion_trace_family(
        inp, _torsion_output(inp), input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    )
    assert bundle.calculations[0].steps[-1].result.state == RESULT_FINITE
    out = _torsion_output(inp)
    out["torsion"]["method"] = codes.EC2_2005.label
    with pytest.raises(TraceValidationError, match="method"):
        build_torsion_trace_family(
            inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


def test_invalid_torsion_input_yields_minimal_failure_before_candidate_numbers():
    inp = _input(shear_on=False, torsion_gamma_ct=math.nan)
    hostile = {
        "torsion": {
            "valid": False,
            "trd": 9.9e99,
            "util": -1.0,
            "primary": {"cot": math.nan, "trd": 9.9e99},
        }
    }
    bundle = build_torsion_trace_family(
        inp, hostile, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
    )
    calculation = bundle.calculations[0]
    assert calculation.steps[-1].result.state != RESULT_FINITE
    assert not any(
        token in step.step_id
        for step in calculation.steps
        for token in ("resistance", "utilisation", "verdict", "cot")
    )


def test_detailing_pair_order_missing_subfamily_and_coherent_tamper_fail():
    inp = _input(My_pl=0.0)
    out = _detail_output(inp)
    out["clear_spacing"]["pairs"][:2] = reversed(
        out["clear_spacing"]["pairs"][:2]
    )
    with pytest.raises(TraceValidationError, match=r"clear[ -]spacing"):
        build_detailing_trace_family(
            inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )

    out = _detail_output(inp)
    out.pop("transverse_reinforcement")
    with pytest.raises(TraceValidationError, match="transverse reinforcement"):
        build_detailing_trace_family(
            inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )

    out = _detail_output(inp)
    pair = out["clear_spacing"]["pairs"][0]
    pair["clear_mm"] += 20.0
    pair["margin_mm"] = pair["clear_mm"] - pair["required_mm"]
    pair["status"] = "PASS" if pair["margin_mm"] >= 0.0 else "FAIL"
    with pytest.raises(TraceValidationError, match=r"clear[ -]spacing"):
        build_detailing_trace_family(
            inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
        )


def test_failure_only_detailing_numbers_are_inert_and_finite_promotion_fails():
    inp = _input(
        shear_on=False,
        torsion_on=False,
        minimum_reinforcement_on=False,
        transverse_detailing_on=False,
        bar_elements=[{
            "id": "R1", "kind": "bar", "x_mm": 0.0, "y_mm": 0.0,
            "diameter_mm": 20.0, "material_id": "B500",
        }],
    )
    result = detailing.clear_spacing(
        inp["bar_elements"], d_upper_mm=inp["detailing_d_upper"],
        edition=inp["detailing_edition"],
    )
    original = build_detailing_trace_family(
        inp, {"clear_spacing": result}, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    )
    hostile = copy.deepcopy(result)
    hostile["pairs"] = [{
        "status": "PASS", "clear_mm": 1.0e30,
        "required_mm": -1.0e30, "margin_mm": 2.0e30,
    }]
    rebuilt = build_detailing_trace_family(
        inp, {"clear_spacing": hostile}, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    )
    assert bundle_to_json(rebuilt) == bundle_to_json(original)

    evidence = _detailing_evidence(inp, {"clear_spacing": result}, {})
    calculation = original.calculations[0]
    steps = list(calculation.steps)
    steps[-1] = dataclasses.replace(
        steps[-1], result=TraceResult(RESULT_FINITE, 1.0)
    )
    promoted = create_bundle(
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        calculations=(dataclasses.replace(calculation, steps=tuple(steps)),),
    )
    with pytest.raises(TraceValidationError, match="result state"):
        audit_trace_registry(
            promoted, expected_registry(tuple(item.plan for item in evidence))
        )


def test_registry_rejects_missing_duplicate_masking_axis_method_and_graph_drift():
    inp = _input(torsion_on=False)
    out = _shear_output(inp)
    bundle = _shear_bundle(inp, out)
    evidence = _shear_evidence(inp, out, CONTEXT)
    registry = expected_registry(tuple(item.plan for item in evidence))
    calculations = bundle.calculations

    missing = create_bundle(
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        calculations=calculations[1:],
    )
    with pytest.raises(TraceValidationError, match="missing"):
        audit_trace_registry(missing, registry)

    unrelated = dataclasses.replace(
        calculations[0], calculation_id="shear.unrelated.member"
    )
    masked = create_bundle(
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        calculations=(unrelated, *calculations[1:]),
    )
    with pytest.raises(TraceValidationError, match="missing.*unexpected"):
        audit_trace_registry(masked, registry)

    with pytest.raises(TraceValidationError, match="duplicate calculation"):
        create_bundle(
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            calculations=(calculations[0], calculations[0]),
        )

    wrong_axis = dataclasses.replace(
        calculations[0], axes=(TraceAxis("component", "vy"),)
    )
    altered = create_bundle(
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        calculations=(wrong_axis, *calculations[1:]),
    )
    with pytest.raises(TraceValidationError, match="axes"):
        audit_trace_registry(altered, registry)

    wrong_method = dataclasses.replace(calculations[0], method_id="wrong-method")
    altered = create_bundle(
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        calculations=(wrong_method, *calculations[1:]),
    )
    with pytest.raises(TraceValidationError, match="method"):
        audit_trace_registry(altered, registry)

    steps = list(calculations[0].steps)
    steps[-1] = dataclasses.replace(
        steps[-1], dependencies=tuple(reversed(steps[-1].dependencies))
    )
    altered = create_bundle(
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        calculations=(dataclasses.replace(calculations[0], steps=tuple(steps)),
                      *calculations[1:]),
    )
    with pytest.raises(TraceValidationError, match="dependency graph"):
        audit_trace_registry(altered, registry)


def test_registry_rejects_same_kind_source_citation_and_unit_swaps():
    inp = _input(torsion_on=False)
    out = _shear_output(inp)
    bundle = _shear_bundle(inp, out)
    evidence = _shear_evidence(inp, out, CONTEXT)
    registry = expected_registry(tuple(item.plan for item in evidence))
    calculation = bundle.calculations[0]

    standard_positions = []
    standard_sources = []
    for index, step in enumerate(calculation.steps):
        if step.source.kind == "standard" and step.source not in standard_sources:
            standard_positions.append(index)
            standard_sources.append(step.source)
    first, second = standard_positions[:2]
    steps = list(calculation.steps)
    steps[first] = dataclasses.replace(steps[first], source=steps[second].source)
    steps[second] = dataclasses.replace(steps[second], source=steps[first].source)
    swapped = create_bundle(
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        calculations=(dataclasses.replace(calculation, steps=tuple(steps)),
                      *bundle.calculations[1:]),
    )
    with pytest.raises(TraceValidationError, match="source"):
        audit_trace_registry(swapped, registry)

    steps = list(calculation.steps)
    target = standard_positions[0]
    source = steps[target].source
    citation = source.citation
    changed_source = dataclasses.replace(
        source,
        citation=SourceCitation(
            citation.document, citation.clause, citation.locator + " tamper"
        ),
    )
    steps[target] = dataclasses.replace(steps[target], source=changed_source)
    changed = create_bundle(
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        calculations=(dataclasses.replace(calculation, steps=tuple(steps)),
                      *bundle.calculations[1:]),
    )
    with pytest.raises(TraceValidationError, match="source"):
        audit_trace_registry(changed, registry)

    steps = list(calculation.steps)
    steps[0] = dataclasses.replace(
        steps[0], unit=TraceUnit("kN", "force")
    )
    with pytest.raises(TraceValidationError, match="unit mismatch"):
        create_bundle(
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
            calculations=(dataclasses.replace(calculation, steps=tuple(steps)),
                          *bundle.calculations[1:]),
        )


def test_seal_stale_hash_unrelated_inputs_and_leaf_reachability():
    inp = _input(torsion_on=False)
    inp.update(
        conc_Ec=math.nan,
        v_min=math.nan,
        crack_limit=math.nan,
        fatigue_on=True,
        fatigue_invalid=object(),
    )
    bundle = _shear_bundle(inp, _shear_output(inp))
    with pytest.raises(TraceValidationError, match="seal"):
        validate_bundle(dataclasses.replace(bundle, warnings=("tamper",)))
    with pytest.raises(TraceValidationError, match="current input"):
        validate_bundle(bundle, expected_input_sha256="f" * 64)
    with pytest.raises(TraceValidationError, match="current result"):
        validate_bundle(bundle, expected_result_sha256="e" * 64)

    for calculation in bundle.calculations:
        by_id = {step.step_id: step for step in calculation.steps}
        reachable = {calculation.final_step_id}
        pending = [by_id[calculation.final_step_id]]
        while pending:
            step = pending.pop()
            for dependency in step.dependencies:
                if dependency.step_id not in reachable:
                    reachable.add(dependency.step_id)
                    pending.append(by_id[dependency.step_id])
        assert reachable == set(by_id)


def test_torsion_ignores_unrelated_nonfinite_moments_and_custom_law_is_project():
    inp = _input(shear_on=False, Mx_pl=math.nan, My_pl=math.nan)
    bundle = build_torsion_trace_family(
        inp, _torsion_output(inp), input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    )
    assert bundle.calculations

    custom = _input(torsion_on=False)
    custom["concrete"] = dataclasses.replace(custom["concrete"], alpha_cc=0.93)
    bundle = _shear_bundle(custom, _shear_output(custom))
    concrete_steps = [
        step for calculation in bundle.calculations for step in calculation.steps
        if step.step_id.startswith("material-concrete-")
    ]
    assert concrete_steps
    assert all(step.source.kind == "project" for step in concrete_steps)
