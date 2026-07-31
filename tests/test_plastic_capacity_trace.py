from __future__ import annotations

import copy
import dataclasses
import math

import pytest

from sector import (
    codes,
    combined,
    material_presets,
    plastic_capacity_trace,
)
from sector.calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    TraceResult,
    TraceValidationError,
    create_bundle,
    validate_bundle,
)
from sector.plastic import solve_plastic
from sector.plastic_capacity_trace import build_plastic_capacity_trace_family
from sector.section import Section
from sector.trace_registry import audit_trace_registry


def _oracle(mx, my, ax, ay):
    """Independent ray/polygon reconstruction; no trace-builder calls."""

    demand = math.hypot(ax, ay)
    ux, uy = ax / demand, ay / demand
    hits = []
    for index, (px, py) in enumerate(zip(mx, my)):
        nxt = (index + 1) % len(mx)
        ex, ey = mx[nxt] - px, my[nxt] - py
        determinant = ux * ey - uy * ex
        if abs(determinant) <= 1.0e-12:
            continue
        ray = (ey * px - ex * py) / determinant
        edge = (uy * px - ux * py) / determinant
        if -1.0e-9 <= edge <= 1.0 + 1.0e-9 and ray > 1.0e-9:
            hits.append((ray, index))
    resistance, edge = min(hits)
    nxt = (edge + 1) % len(mx)
    crossing = (ux * resistance, uy * resistance)
    distances = (
        math.hypot(mx[edge] - crossing[0], my[edge] - crossing[1]),
        math.hypot(mx[nxt] - crossing[0], my[nxt] - crossing[1]),
    )
    selected = edge if distances[0] <= distances[1] else nxt
    return demand / resistance, selected, resistance


def _point(point):
    return {
        "V": point.V,
        "Mx": point.Mx,
        "My": point.My,
        "na_x": point.na_x_intercept,
        "na_y": point.na_y_intercept,
        "eps_c": -point.eps_concrete,
        "eps_s": -point.eps_steel,
        "eps_s_comp": -point.eps_steel_comp,
        "eps_cable": -point.eps_cable,
        "kappa": point.curvature,
        "axial": point.axial,
        "axial_action": -point.axial,
        "compression_depth": point.compression_depth,
        "neutral_axis_depth": point.neutral_axis_depth,
        "axial_residual": point.axial_residual,
        "axial_tolerance": point.axial_tolerance,
        "concrete_force": point.concrete_force,
        "concrete_mx": point.concrete_mx,
        "concrete_my": point.concrete_my,
        "steel_force": point.steel_force,
        "steel_mx": point.steel_mx,
        "steel_my": point.steel_my,
        "tendon_force": point.tendon_force,
        "tendon_mx": point.tendon_mx,
        "tendon_my": point.tendon_my,
        "comp_force": point.compression_force,
        "comp_mx": point.compression_mx,
        "comp_my": point.compression_my,
        "tension_force": point.tension_force,
        "tension_mx": point.tension_mx,
        "tension_my": point.tension_my,
        "lever": point.lever_arm,
        "dx": point.dx,
        "dy": point.dy,
        "converged": point.converged,
    }


@pytest.fixture(scope="module")
def representative_case():
    tendon_values = material_presets.PRESTRESS_PRESETS[codes.EC2_2005.label]
    tendon = material_presets.build_prestress(
        tendon_values["curve"],
        **{key: value for key, value in tendon_values.items() if key != "curve"},
    )
    section = Section.from_polygon(
        [(0.0, 0.0), (0.4, 0.0), (0.4, 0.7), (0.0, 0.7)],
        [
            (0.06, 0.06, 700.0),
            (0.34, 0.06, 700.0),
            (0.34, 0.64, 700.0),
            (0.06, 0.64, 700.0),
        ],
        tendons_xy_area_mm2=[(0.2, 0.1, 500.0)],
    )
    concrete = codes.EC2_2005.concrete(35.0)
    steel = codes.EC2_2005.steel(500.0)
    inp = {
        "section": section,
        "concrete": concrete,
        "steel": steel,
        "prestress": tendon,
        "concrete_preset": codes.EC2_2005.label,
        "mild_preset": codes.EC2_2005.label,
        "prestress_preset": codes.EC2_2005.label,
        "P_pl": 40.0,
        "Mx_pl": 115.0,
        "My_pl": 65.0,
    }
    points = solve_plastic(
        section,
        concrete,
        steel,
        -inp["P_pl"],
        0.0,
        315.0,
        45.0,
        prestress=tendon,
    )
    mx, my = [item.Mx for item in points], [item.My for item in points]
    oracle = _oracle(
        mx,
        my,
        inp["Mx_pl"],
        inp["My_pl"],
    )
    radial = combined.radial_util_result(
        mx,
        my,
        inp["Mx_pl"],
        inp["My_pl"],
    )
    out = {
        "plastic": {
            "mx": mx,
            "my": my,
            "util": radial.utilisation,
            "util_gov": radial.governing_index,
            "closed": True,
            "check_util": True,
            "applied": (inp["Mx_pl"], inp["My_pl"]),
            "demand": radial.demand,
            "resistance": radial.resistance,
            "converged": all(item.converged for item in points),
            "points": [_point(item) for item in points],
        }
    }
    return inp, out, oracle


def _bundle(family, input_hash="a" * 64, result_hash="b" * 64):
    return create_bundle(
        input_sha256=input_hash,
        result_sha256=result_hash,
        calculations=(family.calculation,),
    )


def _steps(family):
    return {item.step_id: item for item in family.calculation.steps}


def _dependency_closure(steps, root):
    reached = set()
    pending = [root]
    while pending:
        step_id = pending.pop()
        if step_id in reached:
            continue
        reached.add(step_id)
        pending.extend(item.step_id for item in steps[step_id].dependencies)
    return reached


def test_independent_oracle_and_exact_registry_close_ct002(representative_case):
    inp, out, oracle = representative_case
    util, selected, resistance = oracle
    assert util == pytest.approx(0.3231334179)
    assert selected == 1
    assert resistance == pytest.approx(408.8046633)
    assert out["plastic"]["util"] == pytest.approx(util)
    assert out["plastic"]["util_gov"] == selected
    assert out["plastic"]["demand"] == pytest.approx(
        math.hypot(inp["Mx_pl"], inp["My_pl"])
    )
    assert out["plastic"]["resistance"] == pytest.approx(resistance)

    family = build_plastic_capacity_trace_family(
        inp,
        out,
        context={"case": "representative", "stage": 2},
    )
    bundle = _bundle(family)
    assert audit_trace_registry(bundle, family.registry) == bundle
    assert family.calculation.coverage_id == "ct-002"
    assert family.calculation.method_id == "ec2-2005"
    member = family.registry.families[0].members[0]
    assert member.result_states == frozenset({RESULT_FINITE, RESULT_FAILED})
    axes = {axis.name: axis.value for axis in family.calculation.axes}
    assert axes["selected_member"] == str(selected)
    assert axes["retained_cardinality"] == str(len(out["plastic"]["points"]))

    steps = _steps(family)
    assert steps["geometry-bar-001-area"].unit.symbol == "m2"
    assert steps["governing-ray-resistance"].result.value == pytest.approx(
        resistance
    )
    assert steps[family.calculation.final_step_id].result.value == pytest.approx(
        util
    )
    assert steps["selected-solver-axial"].result.value == pytest.approx(
        sum(
            steps[f"{kind}-force-resultant"].result.value
            for kind in (
                "concrete",
                "steel",
                "tendon",
            )
        )
    )
    required = {
        "action-p-ed",
        "action-mx-ed",
        "action-my-ed",
        "section-geometry-vector",
        "geometry-bar-001-area",
        "geometry-tendon-001-area",
        "concrete-law-vector",
        "bar-001-law-vector",
        "tendon-001-law-vector",
        "retained-capacity-arrays",
        "selected-axial-residual",
    }
    assert required <= set(steps)
    assert all(
        item.source.edition == codes.EC2_2005.label
        for item in steps.values()
        if item.source.kind == "standard"
    )


def test_every_input_and_material_leaf_reaches_the_final_result(
    representative_case,
):
    inp, out, _ = representative_case
    family = build_plastic_capacity_trace_family(inp, out, context={})
    steps = _steps(family)
    closure = _dependency_closure(steps, family.calculation.final_step_id)
    expected_leaves = {
        step.step_id
        for step in steps.values()
        if step.quantity_role == "user-input"
        or (
            step.quantity_role == "method-value"
            and "-law-" in step.step_id
        )
    }
    assert expected_leaves <= closure

    expected_material_dependencies = {
        "concrete": {"concrete-law-vector"},
        "steel": {
            step_id
            for step_id in steps
            if step_id.startswith("bar-") and step_id.endswith("-law-vector")
        },
        "tendon": {
            step_id
            for step_id in steps
            if step_id.startswith("tendon-")
            and step_id.endswith("-law-vector")
        },
    }
    for kind, expected in expected_material_dependencies.items():
        for component in ("force", "mx", "my"):
            dependencies = {
                item.step_id
                for item in steps[
                    f"{kind}-{component}-resultant"
                ].dependencies
            }
            assert "section-geometry-vector" in dependencies
            assert "action-p-ed" in dependencies
            assert expected <= dependencies


@pytest.mark.parametrize("selection", [None, True, 1.0, -1, 8])
def test_util_gov_is_exact_and_never_substituted(representative_case, selection):
    inp, out, _ = representative_case
    hostile = copy.deepcopy(out)
    hostile["plastic"]["util_gov"] = selection
    with pytest.raises(TraceValidationError, match="util_gov"):
        build_plastic_capacity_trace_family(inp, hostile, context={})


def test_valid_alternate_member_fails_authoritative_selection(
    representative_case,
):
    inp, out, _ = representative_case
    hostile = copy.deepcopy(out)
    hostile["plastic"]["util_gov"] = (out["plastic"]["util_gov"] + 1) % 8
    with pytest.raises(TraceValidationError, match="authoritative envelope"):
        build_plastic_capacity_trace_family(
            inp,
            hostile,
            context={"case": "A"},
        )


def test_coherently_tampered_radial_result_fails_authoritative_selection(
    representative_case,
):
    inp, out, _ = representative_case
    hostile = copy.deepcopy(out)
    hostile["plastic"]["resistance"] *= 2.0
    hostile["plastic"]["util"] = (
        hostile["plastic"]["demand"] / hostile["plastic"]["resistance"]
    )
    hostile["plastic"]["util_gov"] = (
        hostile["plastic"]["util_gov"] + 1
    ) % len(hostile["plastic"]["points"])
    with pytest.raises(TraceValidationError, match="authoritative envelope"):
        build_plastic_capacity_trace_family(inp, hostile, context={})


def test_coherently_tampered_resistance_fails_authoritative_value(
    representative_case,
):
    inp, out, _ = representative_case
    hostile = copy.deepcopy(out)
    hostile["plastic"]["resistance"] *= 2.0
    hostile["plastic"]["util"] = (
        hostile["plastic"]["demand"] / hostile["plastic"]["resistance"]
    )
    with pytest.raises(
        TraceValidationError,
        match="authoritative governing resistance",
    ):
        build_plastic_capacity_trace_family(inp, hostile, context={})


def test_duplicate_member_identity_fails_closed(representative_case):
    inp, out, _ = representative_case
    hostile = copy.deepcopy(out)
    hostile["plastic"]["points"][1] = copy.deepcopy(
        hostile["plastic"]["points"][0]
    )
    hostile["plastic"]["mx"][1] = hostile["plastic"]["mx"][0]
    hostile["plastic"]["my"][1] = hostile["plastic"]["my"][0]
    with pytest.raises(TraceValidationError, match="duplicate member angles"):
        build_plastic_capacity_trace_family(inp, hostile, context={})


def test_missing_solver_intermediate_fails_closed(representative_case):
    inp, out, _ = representative_case
    hostile = copy.deepcopy(out)
    selected = hostile["plastic"]["util_gov"]
    del hostile["plastic"]["points"][selected]["tendon_my"]
    with pytest.raises(TraceValidationError, match="missing tendon_my"):
        build_plastic_capacity_trace_family(inp, hostile, context={})


@pytest.mark.parametrize(
    ("field", "change", "message"),
    [
        ("axial_residual", 1.0, "axial residual"),
        ("Mx", 1.0, "Mx array member"),
        ("lever", 0.01, "lever-arm components"),
    ],
)
def test_inconsistent_selected_solver_evidence_fails_closed(
    representative_case,
    field,
    change,
    message,
):
    inp, out, _ = representative_case
    hostile = copy.deepcopy(out)
    selected = hostile["plastic"]["util_gov"]
    hostile["plastic"]["points"][selected][field] += change
    with pytest.raises(TraceValidationError, match=message):
        build_plastic_capacity_trace_family(inp, hostile, context={})


def test_convergence_flag_cannot_contradict_retained_residual(
    representative_case,
):
    inp, out, _ = representative_case
    hostile = copy.deepcopy(out)
    selected = hostile["plastic"]["util_gov"]
    hostile["plastic"]["points"][selected]["converged"] = False
    with pytest.raises(TraceValidationError, match="convergence contradicts"):
        build_plastic_capacity_trace_family(inp, hostile, context={})


@pytest.mark.parametrize(
    ("field", "change", "message"),
    [
        ("demand", 1.0, "retained moment demand"),
        ("resistance", 1.0, "demand/resistance utilisation"),
    ],
)
def test_retained_ray_results_are_checked_without_regeneration(
    representative_case,
    field,
    change,
    message,
):
    inp, out, _ = representative_case
    hostile = copy.deepcopy(out)
    hostile["plastic"][field] += change
    with pytest.raises(TraceValidationError, match=message):
        build_plastic_capacity_trace_family(inp, hostile, context={})


def test_consistent_nonconvergence_is_an_explicit_failure(representative_case):
    inp, out, _ = representative_case
    hostile_input = {**inp, "P_pl": inp["P_pl"] + 1.0}
    hostile = copy.deepcopy(out)
    for point in hostile["plastic"]["points"]:
        point["axial_residual"] += 1.0
        point["axial_tolerance"] = 41.0e-6
        point["converged"] = False
    hostile["plastic"]["converged"] = False
    family = build_plastic_capacity_trace_family(
        hostile_input,
        hostile,
        context={},
    )
    final = _steps(family)[family.calculation.final_step_id]
    assert final.result.state == RESULT_FAILED
    assert family.registry.families[0].members[0].result_states == frozenset(
        {RESULT_FINITE, RESULT_FAILED}
    )
    assert audit_trace_registry(_bundle(family), family.registry)


@pytest.mark.parametrize(
    ("drift", "message"),
    [
        ("method", "identity mismatch"),
        ("axes", "identity mismatch"),
        ("source-edition", "identity mismatch"),
        ("step-order", "step IDs"),
        ("dependency", "dependency graph"),
    ],
)
def test_builder_self_audits_against_independent_registry(
    representative_case,
    monkeypatch,
    drift,
    message,
):
    inp, out, _ = representative_case
    original = plastic_capacity_trace._calculation

    def drifting_calculation(evidence, *, context):
        calculation = original(evidence, context=context)
        if drift == "method":
            return dataclasses.replace(
                calculation,
                method_id="project-drift",
            )
        if drift == "axes":
            return dataclasses.replace(
                calculation,
                axes=calculation.axes[:-1],
            )

        changed = list(calculation.steps)
        if drift == "source-edition":
            standard_index = next(
                index
                for index, step in enumerate(changed)
                if step.source.kind == "standard"
            )
            step = changed[standard_index]
            changed[standard_index] = dataclasses.replace(
                step,
                source=dataclasses.replace(
                    step.source,
                    edition="wrong-edition",
                ),
            )
        elif drift == "step-order":
            changed[0], changed[1] = changed[1], changed[0]
        else:
            changed = [
                dataclasses.replace(
                    step,
                    dependencies=tuple(
                        item
                        for item in step.dependencies
                        if item.step_id != "section-geometry-vector"
                    ),
                )
                if step.step_id == "retained-member-000-mx"
                else step
                for step in changed
            ]
        return dataclasses.replace(calculation, steps=tuple(changed))

    monkeypatch.setattr(
        plastic_capacity_trace,
        "_calculation",
        drifting_calculation,
    )
    with pytest.raises(TraceValidationError, match=message):
        build_plastic_capacity_trace_family(inp, out, context={})


@pytest.mark.parametrize(
    ("step_id", "dependency_id"),
    [
        ("retained-member-000-mx", "section-geometry-vector"),
        ("retained-member-000-mx", "bar-001-law-vector"),
    ],
)
def test_geometry_and_material_dependency_omissions_are_audited(
    representative_case,
    step_id,
    dependency_id,
):
    inp, out, _ = representative_case
    family = build_plastic_capacity_trace_family(inp, out, context={})
    changed = []
    for step in family.calculation.steps:
        if step.step_id == step_id:
            step = dataclasses.replace(
                step,
                dependencies=tuple(
                    item for item in step.dependencies
                    if item.step_id != dependency_id
                ),
            )
        changed.append(step)
    calculation = dataclasses.replace(family.calculation, steps=tuple(changed))
    candidate = create_bundle(
        input_sha256="a" * 64,
        result_sha256="b" * 64,
        calculations=(calculation,),
    )
    with pytest.raises(TraceValidationError, match="dependency graph"):
        audit_trace_registry(candidate, family.registry)


def test_content_edition_and_freshness_tamper_fail_closed(representative_case):
    inp, out, _ = representative_case
    family = build_plastic_capacity_trace_family(inp, out, context={"case": "A"})
    bundle = _bundle(family)
    final_id = family.calculation.final_step_id
    changed = tuple(
        dataclasses.replace(
            step,
            result=TraceResult(
                state=RESULT_FINITE,
                value=step.result.value + 0.01,
            ),
        )
        if step.step_id == final_id else step
        for step in family.calculation.steps
    )
    tampered = dataclasses.replace(
        bundle,
        calculations=(dataclasses.replace(family.calculation, steps=changed),),
    )
    with pytest.raises(TraceValidationError, match="content seal"):
        validate_bundle(tampered)
    with pytest.raises(TraceValidationError, match="current input"):
        validate_bundle(bundle, expected_input_sha256="c" * 64)

    wrong_edition = {
        **inp,
        "concrete_preset": codes.EC2_2023.label,
    }
    candidate = build_plastic_capacity_trace_family(
        wrong_edition,
        out,
        context={"case": "A"},
    )
    with pytest.raises(TraceValidationError, match="identity mismatch"):
        audit_trace_registry(_bundle(candidate), family.registry)
