"""Solver-owned unpublished PR-08C calculation traces.

The builders consume original solver input and retained result dictionaries. They
replay the authoritative low-level mechanics before any finite trace is issued;
candidate dictionaries are evidence to be checked, never calculation authority.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import capacity, codes, combined, detailing
from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    ROLE_COMPUTED,
    ROLE_FINAL,
    ROLE_METHOD_VALUE,
    ROLE_USER_INPUT,
    SOURCE_PROJECT,
    TraceBundle,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceSource,
    TraceStep,
    TraceValidationError,
    create_bundle,
    trace_identity_token,
    validate_bundle,
)
from .section_trace_blocks import (
    GeometryBlock,
    _catalog_matches,
    _concrete_block,
    _provenance,
    _standard_law_matches,
    _law_values,
    _materials,
    section_trace_blocks,
)
from .shear_torsion_detailing_trace_contract import (
    ANGLE,
    AREA_M2,
    AREA_MM2,
    BASE_TORSION,
    DETAILING_COVERAGE,
    DETAILING_FAMILY,
    DK_SHEAR,
    DK_TORSION,
    DK_TRANSVERSE,
    FORCE,
    INPUT_SOURCE,
    LENGTH_M,
    LENGTH_MM,
    MOMENT,
    MemberPlan,
    ONE,
    PROJECT_DETAILING,
    PROJECT_SHARED_ANGLE,
    PROJECT_SHEAR,
    PROJECT_TORSION,
    RATIO,
    SHEAR_COVERAGE,
    SHEAR_FAMILY,
    STRESS,
    StepSpec,
    TORSION_COVERAGE,
    TORSION_FAMILY,
    calculation_id,
    detailing_rule_source,
    expected_registry,
    member_axes,
    method_id,
    shear_rule_source,
)
from .trace_registry import audit_trace_registry


_TOL = 1.0e-9
_FAILURE_TEXT = "authoritative PR-08C mechanics did not yield a finite assessment"


@dataclass(frozen=True, slots=True)
class _Evidence:
    plan: MemberPlan
    values: tuple[tuple[str, float | None], ...]
    failure_reason: str | None = None
    warnings: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()


class _Rows:
    def __init__(self) -> None:
        self.specs: list[StepSpec] = []
        self.values: list[tuple[str, float | None]] = []
        self.ids: set[str] = set()

    def add(
        self,
        step_id: str,
        title: str,
        unit,
        role: str,
        source: TraceSource,
        value: float | int | bool | None,
        *dependencies: str,
        expression: str = "retained value",
    ) -> str:
        if step_id in self.ids:
            raise ValueError(f"duplicate PR-08C step {step_id}")
        self.ids.add(step_id)
        if type(value) is bool:
            value = 1.0 if value else 0.0
        elif value is not None:
            value = float(value)
        self.specs.append(
            StepSpec(
                step_id,
                title,
                unit,
                role,
                source,
                tuple(dependencies),
                expression,
            )
        )
        self.values.append((step_id, value))
        return step_id

    def input(self, step_id, title, unit, value) -> str:
        return self.add(
            step_id, title, unit, ROLE_USER_INPUT, INPUT_SOURCE, value
        )

    def method(self, step_id, title, unit, source, value) -> str:
        return self.add(
            step_id, title, unit, ROLE_METHOD_VALUE, source, value
        )

    def computed(
        self, step_id, title, unit, source, value, *dependencies,
        expression="retained mechanics",
    ) -> str:
        return self.add(
            step_id,
            title,
            unit,
            ROLE_COMPUTED,
            source,
            value,
            *dependencies,
            expression=expression,
        )

    def final(self, value: float | None, *, failed: bool) -> None:
        dependencies = tuple(spec.step_id for spec in self.specs)
        self.add(
            "assessment-result",
            "PR-08C member assessment",
            ONE,
            ROLE_FINAL,
            PROJECT_DETAILING if not self.specs else self.specs[-1].source,
            value,
            *dependencies,
            expression=(
                "explicit failed state"
                if failed
                else "1 when the reconstructed assessment passes, otherwise 0"
            ),
        )


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be an ordered sequence")
    return tuple(value)


def _finite(value: Any, label: str, *, positive: bool = False) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise ValueError(f"{label} must be a finite non-Boolean number")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0.0):
        qualifier = "positive finite" if positive else "finite"
        raise ValueError(f"{label} must be {qualifier}")
    return number


def _same(actual: Any, expected: Any, label: str) -> None:
    """Strict structural comparison with engineering tolerance for finite numbers."""

    if type(expected) is bool or expected is None or isinstance(expected, str):
        if actual != expected or type(actual) is not type(expected):
            raise ValueError(f"{label} contradicts authoritative reconstruction")
        return
    if type(expected) in {int, float}:
        if type(actual) not in {int, float} or type(actual) is bool:
            raise ValueError(f"{label} must be numeric")
        a, e = float(actual), float(expected)
        if math.isinf(e):
            if a != e:
                raise ValueError(f"{label} contradicts authoritative reconstruction")
        elif not math.isfinite(a) or not math.isclose(
            a, e, rel_tol=2.0e-9, abs_tol=2.0e-9
        ):
            raise ValueError(f"{label} contradicts authoritative reconstruction")
        return
    if isinstance(expected, Mapping):
        actual = _mapping(actual, label)
        for key, item in expected.items():
            if key not in actual:
                raise ValueError(f"{label} is missing {key}")
            _same(actual[key], item, f"{label}.{key}")
        return
    if isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)):
        actual = _sequence(actual, label)
        if len(actual) != len(expected):
            raise ValueError(f"{label} has wrong cardinality")
        for index, (a_item, e_item) in enumerate(zip(actual, expected)):
            _same(a_item, e_item, f"{label}[{index}]")
        return
    if actual != expected:
        raise ValueError(f"{label} contradicts authoritative reconstruction")


def _material_source(inp: Mapping[str, Any], kind: str, law: Any) -> TraceSource:
    preset_key = {
        "concrete": "concrete_preset",
        "bar": "mild_preset",
        "tendon": "prestress_preset",
    }[kind]
    preset = inp.get(preset_key)
    if kind == "bar" and inp.get("capacity_steel_material_id"):
        selected_id = inp["capacity_steel_material_id"]
        items = (
            (inp.get("mild_material_catalog") or {}).get("items") or ()
        )
        matches = [
            item for item in items
            if isinstance(item, Mapping) and item.get("id") == selected_id
        ]
        if len(matches) == 1 and _catalog_matches("bar", law, matches[0]):
            preset = matches[0].get("preset")
    try:
        if kind == "concrete":
            code = next(
                (
                    item for item in codes.CODES.values()
                    if preset in {item.key, item.label}
                ),
                None,
            )
            if code is None or _law_values(law) != _law_values(
                code.concrete(law.fck)
            ):
                raise ValueError
        elif not _standard_law_matches(kind, preset, law):
            raise ValueError
        return _provenance(kind, preset).source
    except (AttributeError, TypeError, ValueError):
        return TraceSource(SOURCE_PROJECT, f"project-{kind}-law")


def _geometry_rows(
    rows: _Rows,
    inp: Mapping[str, Any],
    project_source: TraceSource = PROJECT_SHEAR,
    *,
    include_tendons: bool = True,
) -> str:
    block = GeometryBlock.from_section(inp["section"])
    raw_rings = (
        tuple(tuple(float(value) for value in point) for point in inp["outer"]),
        *tuple(
            tuple(tuple(float(value) for value in point) for point in ring)
            for ring in (inp.get("holes") or ())
        ),
    )
    _same(raw_rings, block.rings, "raw/section concrete geometry")
    geometry_groups = [("bar", inp.get("bars") or (), block.bars)]
    if include_tendons:
        geometry_groups.append(
            ("tendon", inp.get("tendons") or (), block.tendons)
        )
    for kind, raw, elements in geometry_groups:
        raw = _sequence(raw, f"raw {kind} geometry")
        if len(raw) != len(elements):
            raise ValueError(f"raw/section {kind} geometry has wrong cardinality")
        for index, (record, element) in enumerate(zip(raw, elements)):
            x, y, area_mm2 = _sequence(record, f"raw {kind} {index}")
            _same(float(x), element.x, f"raw/section {kind} {index}.x")
            _same(float(y), element.y, f"raw/section {kind} {index}.y")
            _same(
                float(area_mm2) * 1.0e-6,
                element.area,
                f"raw/section {kind} {index}.area",
            )
    leaves: list[str] = []
    for ring_index, ring in enumerate(block.rings):
        for point_index, (x, y) in enumerate(ring):
            prefix = f"geometry-ring-{ring_index:03d}-point-{point_index:04d}"
            leaves.append(rows.input(f"{prefix}-x", "Concrete vertex x", LENGTH_M, x))
            leaves.append(rows.input(f"{prefix}-y", "Concrete vertex y", LENGTH_M, y))
    element_groups = [("bar", block.bars)]
    if include_tendons:
        element_groups.append(("tendon", block.tendons))
    for kind, elements in element_groups:
        for index, element in enumerate(elements):
            prefix = f"geometry-{kind}-{index:04d}"
            leaves.append(rows.input(f"{prefix}-x", f"{kind} x", LENGTH_M, element.x))
            leaves.append(rows.input(f"{prefix}-y", f"{kind} y", LENGTH_M, element.y))
            leaves.append(rows.input(f"{prefix}-area", f"{kind} area", AREA_M2, element.area))
    return rows.computed(
        "geometry-vector",
        "Immutable section geometry block",
        ONE,
        project_source,
        len(leaves),
        *leaves,
        expression="ordered immutable geometry leaves",
    )


def _law_rows(
    rows: _Rows,
    inp: Mapping[str, Any],
    *,
    include_assignments: bool,
    project_source: TraceSource = PROJECT_SHEAR,
    include_tendons: bool = True,
) -> str:
    laws: list[tuple[str, tuple[tuple[str, float], ...], TraceSource]] = []
    if include_assignments:
        if include_tendons:
            blocks = section_trace_blocks(inp)
            assigned = (blocks.concrete, *blocks.bars, *blocks.tendons)
        else:
            geometry = GeometryBlock.from_section(inp["section"])
            concrete_block = _concrete_block(inp)
            bar_blocks = _materials(
                inp,
                kind="bar",
                count=len(geometry.bars),
                default=inp.get("steel"),
            )
            assigned = (concrete_block, *bar_blocks)
        for index, block in enumerate(assigned):
            prefix = (
                "concrete"
                if block.kind == "concrete"
                else f"{block.kind}-{index:04d}-"
                f"{trace_identity_token(block.element_id)}-"
                f"{trace_identity_token(block.material_id)}"
            )
            laws.append((prefix, block.values, block.provenance.source))
        steel = inp.get("steel")
        if steel is not None:
            laws.append((
                "capacity-steel",
                _law_values(steel),
                _material_source(inp, "bar", steel),
            ))
    else:
        concrete = inp["concrete"]
        laws.append((
            "concrete",
            _law_values(concrete),
            _material_source(inp, "concrete", concrete),
        ))
        steel = inp.get("steel")
        if steel is not None:
            laws.append((
                "steel", _law_values(steel),
                _material_source(inp, "bar", steel),
            ))
        if include_tendons:
            geometry = GeometryBlock.from_section(inp["section"])
            tendon_blocks = _materials(
                inp,
                kind="tendon",
                count=len(geometry.tendons),
                default=inp.get("prestress"),
            )
            for index, block in enumerate(tendon_blocks):
                prefix = (
                    f"tendon-{index:04d}-"
                    f"{trace_identity_token(block.element_id)}-"
                    f"{trace_identity_token(block.material_id)}"
                )
                laws.append((prefix, block.values, block.provenance.source))
    leaves: list[str] = []
    for prefix, values, source in laws:
        for name, value in values:
            unit = STRESS if name in {"fck", "fytk", "fyck", "futk", "Es"} else ONE
            leaves.append(
                rows.method(
                    f"material-{prefix}-{name.replace('_', '-').lower()}",
                    f"{prefix} law {name}",
                    unit,
                    source,
                    value,
                )
            )
    return rows.computed(
        "material-vector",
        "Immutable assigned material-law block",
        ONE,
        project_source,
        len(leaves),
        *leaves,
        expression="ordered immutable material-law leaves",
    )


def _plan(
    rows: _Rows,
    *,
    family_id: str,
    coverage_id: str,
    member_id: str,
    calculation: str,
    method: str,
    axes,
    failed: bool,
    failure_reason: str | None = None,
    warnings: tuple[str, ...] = (),
    assumptions: tuple[str, ...] = (),
) -> _Evidence:
    rows.final(None if failed else rows.values[-1][1], failed=failed)
    plan = MemberPlan(
        family_id,
        member_id,
        calculation,
        coverage_id,
        method,
        axes,
        "failed" if failed else "finite",
        tuple(rows.specs),
    )
    return _Evidence(
        plan,
        tuple(rows.values),
        failure_reason if failed else None,
        warnings,
        assumptions,
    )


def _result(value: float | None, *, failed: bool, reason: str | None) -> TraceResult:
    if failed:
        return TraceResult(RESULT_FAILED, None, reason or _FAILURE_TEXT)
    if value is None or not math.isfinite(float(value)):
        raise ValueError("finite PR-08C step became non-finite")
    return TraceResult(RESULT_FINITE, float(value))


def _calculation(evidence: _Evidence) -> TraceCalculation:
    values = dict(evidence.values)
    units = {spec.step_id: spec.unit for spec in evidence.plan.steps}
    steps = []
    for spec in evidence.plan.steps:
        failed = spec.quantity_role == ROLE_FINAL and evidence.failure_reason is not None
        value = values[spec.step_id]
        steps.append(
            TraceStep(
                step_id=spec.step_id,
                title=spec.title,
                dependencies=tuple(
                    TraceDependency(dependency, units[dependency])
                    for dependency in spec.dependencies
                ),
                quantity_role=spec.quantity_role,
                source=spec.source,
                symbol=spec.step_id,
                unit=spec.unit,
                actual_expression=spec.expression,
                substituted_expression=(
                    "failed" if failed else repr(value)
                ),
                result=_result(
                    value,
                    failed=failed,
                    reason=evidence.failure_reason,
                ),
            )
        )
    return TraceCalculation(
        calculation_id=evidence.plan.calculation_id,
        coverage_id=evidence.plan.coverage_id,
        title=evidence.plan.member_id.replace("-", " ").title(),
        method_id=evidence.plan.method_id,
        axes=evidence.plan.axes,
        final_step_id="assessment-result",
        steps=tuple(steps),
        warnings=evidence.warnings,
        assumptions=evidence.assumptions,
    )


def _bundle(
    evidence: tuple[_Evidence, ...],
    *,
    input_sha256: str,
    result_sha256: str,
) -> TraceBundle:
    plans = tuple(item.plan for item in evidence)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=tuple(_calculation(item) for item in evidence),
    )
    audit_trace_registry(bundle, expected_registry(plans))
    return validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )


def _candidate_directions(
    inp: Mapping[str, Any], out: Mapping[str, Any], expected
) -> dict[str, Mapping[str, Any]]:
    shear_out = _mapping(out.get("shear"), "shear result")
    if "directions" in shear_out:
        directions = _mapping(shear_out["directions"], "shear directions")
    elif len(expected) == 1:
        directions = {next(iter(expected)): shear_out}
    else:
        raise ValueError("directional shear result is missing a direction")
    if set(directions) != set(expected) or tuple(
        key for key in ("vx", "vy") if key in directions
    ) != tuple(expected):
        raise ValueError("directional shear result has wrong order/cardinality")
    return {key: _mapping(directions[key], f"shear {key}") for key in expected}


def _face_candidates(
    direction: Mapping[str, Any], expected_count: int
) -> tuple[Mapping[str, Any], ...]:
    raw = direction.get("face_candidates")
    if raw is None and expected_count == 1:
        return (direction,)
    candidates = _sequence(raw, "shear face candidates")
    if len(candidates) != expected_count:
        raise ValueError("shear face candidates have wrong cardinality")
    return tuple(_mapping(item, "shear face candidate") for item in candidates)


def _selected_shear_links(link_context: Mapping[str, Any]) -> Mapping[str, Any]:
    """Replay the retained live-shear minimax angle selector."""

    def at(cot):
        return link_context["build"](cot, cot)

    demand = link_context["v_ed"]
    utilities = (
        lambda cot: combined.ratio(demand, at(cot)["vrd_s"]),
        lambda cot: combined.ratio(demand, at(cot)["vrd_max"]),
    )
    cot, _utilisation = combined.governing_strut_cot(
        utilities, link_context["cot_min"], link_context["cot_max"]
    )
    return at(cot)


def _shear_evidence(
    inp: Mapping[str, Any], out: Mapping[str, Any], context: Mapping[str, Any]
) -> tuple[_Evidence, ...]:
    n_prestress = capacity.prestress_axial(inp)
    n_ed_comp = -_finite(inp["P_pl"], "P_pl") + n_prestress
    directional = any(
        key in inp for key in ("shear_Vx", "shear_Vy", "shear_components")
    )
    if directional:
        expected = capacity.build_directional_shear_contexts(
            inp, n_prestress, n_ed_comp
        )
    else:
        payload, links = capacity.build_shear_context(inp, n_prestress, n_ed_comp)
        expected = {} if payload is None else {
            payload["component"]: {
                "component": payload["component"],
                "axis": payload["axis"],
                "associated_moment": (
                    inp["Mx_pl"] if payload["axis"] == "x" else inp["My_pl"]
                ),
                "face_mode": "selected",
                "both_faces_evaluated": False,
                "candidates": [(payload, links)],
            }
        }
    if not expected:
        raise ValueError("CT-006 needs an active retained shear direction")
    directions = _candidate_directions(inp, out, expected)
    result: list[_Evidence] = []
    for component in (key for key in ("vx", "vy") if key in expected):
        definition = expected[component]
        pairs = tuple(definition["candidates"])
        actual_candidates = _face_candidates(directions[component], len(pairs))
        assessments = []
        for order, ((payload, link_context), wrapper) in enumerate(
            zip(pairs, actual_candidates), start=1
        ):
            actual = _mapping(wrapper.get("shear", wrapper), "shear face result")
            face = "negative" if payload["tension_low"] else "positive"
            if "shear" in wrapper:
                _same(
                    wrapper.get("tension_low"),
                    payload["tension_low"],
                    "shear wrapper face",
                )
            if bool(actual.get("tension_low")) is not payload["tension_low"]:
                raise ValueError("shear face sign contradicts original actions")
            for key in (
                "component", "axis", "v_ed", "bw", "d", "asl", "ac",
                "n_ed", "n_prestress", "n_ed_comp", "model_2023",
            ):
                _same(actual.get(key), payload[key], f"shear {component}/{face}.{key}")
            _same(actual.get("method"), inp["shear_method"], "shear method")
            resistance_c = _mapping(payload["res"], "authoritative VRd,c")
            actual_c = _mapping(actual.get("res"), "candidate VRd,c")
            if not bool(resistance_c.get("valid")):
                if bool(actual_c.get("valid")):
                    raise ValueError("failed shear face was promoted to finite")
                rows = _Rows()
                rows.input("input-signed-demand", "Signed shear demand", FORCE,
                           capacity.shear_direction_specs(inp)[component]["signed_v_ed"])
                rows.input("input-axial-action", "Tension-positive axial action", FORCE,
                           inp["P_pl"])
                rows.computed("failure-state", "Invalid shear mechanics", ONE,
                              PROJECT_SHEAR, 1.0, "input-signed-demand",
                              "input-axial-action")
                member = f"{component}-{face}"
                result.append(_plan(
                    rows,
                    family_id=SHEAR_FAMILY,
                    coverage_id=SHEAR_COVERAGE,
                    member_id=member,
                    calculation=calculation_id(context, "shear", member),
                    method=method_id(inp["shear_method"], "shear", "failed"),
                    axes=member_axes(
                        context, component=component, axis=payload["axis"],
                        face=face, order=str(order), cardinality=str(len(pairs)),
                        branch="failed",
                    ),
                    failed=True,
                    failure_reason=str(resistance_c.get("reason") or _FAILURE_TEXT),
                ))
                assessments.append((face, "INVALID", math.inf))
                continue
            _same(actual_c, resistance_c, f"shear {component}/{face}.res")
            rule_source = shear_rule_source(
                inp["shear_method"], links=link_context is not None
            )
            selected = resistance_c
            actual_util = actual.get("util")
            cot = None
            if link_context is not None:
                actual_links = _mapping(actual.get("links"), "candidate shear links")
                actual_link_res = _mapping(actual_links.get("res"), "link resistance")
                selected = _selected_shear_links(link_context)
                if not bool(selected.get("valid")):
                    if bool(actual_link_res.get("valid")):
                        raise ValueError("invalid shear links were promoted to finite")
                    rows = _Rows()
                    rows.input(
                        "input-signed-demand", "Signed shear demand", FORCE,
                        capacity.shear_direction_specs(inp)[component]["signed_v_ed"],
                    )
                    rows.input(
                        "input-links-present", "Shear links selected", ONE, True
                    )
                    rows.computed(
                        "failure-state", "Invalid shear-link mechanics", ONE,
                        PROJECT_SHEAR, 1.0, "input-signed-demand",
                        "input-links-present",
                    )
                    member = f"{component}-{face}"
                    result.append(_plan(
                        rows,
                        family_id=SHEAR_FAMILY,
                        coverage_id=SHEAR_COVERAGE,
                        member_id=member,
                        calculation=calculation_id(context, "shear", member),
                        method=method_id(inp["shear_method"], "shear", "failed-links"),
                        axes=member_axes(
                            context, component=component, axis=payload["axis"],
                            face=face, order=str(order), cardinality=str(len(pairs)),
                            branch="failed",
                        ),
                        failed=True,
                        failure_reason="authoritative shear-link resistance is invalid",
                    ))
                    assessments.append((face, "NOT ASSESSED", math.inf))
                    continue
                cot = _finite(selected.get("cot"), "shared cot(theta)", positive=True)
                if not (
                    link_context["cot_min"] - _TOL
                    <= cot
                    <= link_context["cot_max"] + _TOL
                ):
                    raise ValueError("shared cot(theta) is outside the original band")
                # The original-range call replays the retained solver-owned angle
                # selector. Pinning a candidate-provided cot would only prove
                # downstream consistency and would accept a coherent alternate.
                _same(actual_link_res, selected, f"shear {component}/{face}.links.res")
                actual_util = actual_links.get("util")
                expected_link_inputs = {
                    "asw": link_context["asw"],
                    "asw_over_s": link_context["asw_over_s"],
                    "legs": link_context["link_legs"],
                    "dia": inp["shear_link_dia"],
                    "s": inp["shear_link_s"],
                    "fywk": inp["shear_fywk"],
                    "cot_min": link_context["cot_min"],
                    "cot_max": link_context["cot_max"],
                    "model_2023": link_context["model_2023"],
                    "z_source": link_context["z_src"],
                    "required": bool(payload["v_ed"] > link_context["vrd_c"]),
                }
                for key, value in expected_link_inputs.items():
                    if key not in actual_links:
                        raise ValueError(f"candidate shear links are missing {key}")
                    _same(actual_links[key], value, f"shear links.{key}")
            resistance = selected["vrd"] if link_context is not None else selected["vrd_c"]
            resistance = _finite(resistance, "shear resistance", positive=True)
            demand = _finite(payload["v_ed"], "absolute shear demand")
            utilisation = demand / resistance
            _same(actual_util, utilisation, f"shear {component}/{face}.util")
            status = "PASS" if utilisation <= 1.0 + _TOL else "FAIL"
            if "shear_status" in wrapper:
                _same(wrapper["shear_status"], status, "shear candidate status")
            assessments.append((face, status, utilisation))

            rows = _Rows()
            geometry = _geometry_rows(rows, inp)
            materials = _law_rows(rows, inp, include_assignments=True)
            original_moment = (
                inp["My_pl"] if component == "vx" else inp["Mx_pl"]
            )
            bw_input = (
                inp.get("shear_vx_bw", 0.0)
                if component == "vx"
                else inp.get("shear_vy_bw", 0.0)
            ) if directional else inp.get("shear_bw", 0.0)
            action_ids = (
                rows.input("input-signed-demand", "Signed shear demand", FORCE,
                           capacity.shear_direction_specs(inp)[component]["signed_v_ed"]),
                rows.input("input-axial-action", "Tension-positive axial action", FORCE,
                           inp["P_pl"]),
                rows.input("input-associated-moment", "Associated origin moment", MOMENT,
                           original_moment),
            )
            action = rows.computed(
                "action-vector", "Directional shear action", ONE, PROJECT_SHEAR,
                len(action_ids), *action_ids,
            )
            associated = rows.computed(
                "associated-centroid-moment",
                "Associated moment at concrete centroid",
                MOMENT,
                PROJECT_SHEAR,
                definition["associated_moment"],
                action,
                geometry,
                materials,
            )
            bw_override = rows.input(
                "input-web-width-override",
                "Entered web-width override",
                LENGTH_MM,
                bw_input,
            )
            dlower = (
                rows.input(
                    "input-lower-aggregate-size",
                    "Lower aggregate size",
                    LENGTH_MM,
                    inp["shear_dlower"],
                )
                if payload["model_2023"]
                else None
            )
            if "DK NA" in inp["shear_method"]:
                rows.method("method-dk-na", "Danish shear values selected", ONE,
                            DK_SHEAR, 1.0)
            bw = rows.computed("effective-web-width", "Effective web width", LENGTH_MM,
                               PROJECT_SHEAR, payload["bw"], geometry, bw_override)
            depth = rows.computed("effective-depth", "Effective depth", LENGTH_MM,
                                  PROJECT_SHEAR, payload["d"], geometry, materials,
                                  action, associated)
            asl = rows.computed("tension-reinforcement-area", "Tension reinforcement area",
                                AREA_MM2, PROJECT_SHEAR, payload["asl"], geometry, action)
            prestress = rows.computed(
                "prestress-axial", "Locked-in prestress axial force", FORCE,
                PROJECT_SHEAR, n_prestress, geometry, materials,
            )
            ncomp = rows.computed(
                "compression-positive-axial", "Net compression-positive axial",
                FORCE, PROJECT_SHEAR, n_ed_comp, action, prestress,
            )
            vrd_c = rows.computed(
                "concrete-shear-resistance", "Concrete shear resistance", FORCE,
                shear_rule_source(inp["shear_method"], links=False),
                resistance_c["vrd_c"], bw, depth, asl, ncomp, materials,
                associated, *((dlower,) if dlower is not None else ()),
            )
            deps = [action, geometry, materials, vrd_c]
            if link_context is not None:
                link_inputs = (
                    rows.input("input-cot-min", "Entered minimum cotangent", ANGLE,
                               inp["strut_cot_min"]),
                    rows.input("input-cot-max", "Entered maximum cotangent", ANGLE,
                               inp["strut_cot_max"]),
                    rows.input("input-link-legs", "Effective link legs", ONE,
                               link_context["link_legs"]),
                    rows.input("input-link-diameter", "Link diameter", LENGTH_MM,
                               inp["shear_link_dia"]),
                    rows.input("input-link-spacing", "Link spacing", LENGTH_MM,
                               inp["shear_link_s"]),
                    rows.input("input-link-fywk", "Link characteristic yield", STRESS,
                               inp["shear_fywk"]),
                )
                link_vector = rows.computed(
                    "link-input-vector", "Entered shear-link definition", ONE,
                    PROJECT_SHEAR, len(link_inputs), *link_inputs,
                )
                cot_id = rows.computed(
                    "shared-cot-theta", "Retained shared member cotangent", ANGLE,
                    PROJECT_SHARED_ANGLE, cot, action, geometry, materials,
                    link_vector,
                )
                asw_s = rows.computed(
                    "asw-over-s", "Link area per spacing", LENGTH_MM, PROJECT_SHEAR,
                    selected["asw_over_s"], link_vector,
                )
                vrd_s = rows.computed(
                    "link-yield-resistance", "Link-yield shear resistance", FORCE,
                    rule_source, selected["vrd_s"], bw, depth, asw_s, cot_id, materials,
                )
                vrd_max = rows.computed(
                    "strut-crushing-resistance", "Strut-crushing shear resistance", FORCE,
                    rule_source, selected["vrd_max"], bw, depth, ncomp, cot_id, materials,
                )
                governing = rows.computed(
                    "governing-resistance", "Governing shear resistance", FORCE,
                    rule_source, resistance, vrd_s, vrd_max,
                    expression="min(VRd,s, VRd,max)",
                )
                deps.extend((cot_id, asw_s, vrd_s, vrd_max, governing))
            else:
                governing = vrd_c
            util_id = rows.computed(
                "utilisation", "Directional shear utilisation", RATIO,
                PROJECT_SHEAR, utilisation, action, governing,
                expression="abs(VEd) / VRd",
            )
            rows.computed(
                "verdict", "Directional shear verdict", ONE, PROJECT_SHEAR,
                1.0 if status == "PASS" else 0.0, util_id,
                expression="utilisation <= 1 + 1e-9",
            )
            member = f"{component}-{face}"
            result.append(_plan(
                rows,
                family_id=SHEAR_FAMILY,
                coverage_id=SHEAR_COVERAGE,
                member_id=member,
                calculation=calculation_id(context, "shear", member),
                method=method_id(
                    inp["shear_method"], "shear",
                    "links" if link_context is not None else "concrete",
                ),
                axes=member_axes(
                    context, component=component, axis=payload["axis"], face=face,
                    order=str(order), cardinality=str(len(pairs)), branch="finite",
                    ductility_class=str(
                        inp.get("transverse_ductility_class", "B")
                    ).upper(),
                ),
                failed=False,
                assumptions=(
                    "Vx and Vy are independent uniaxial checks; no "
                    "cross-direction interaction is inferred.",
                    "Sector public axial action is tension-positive.",
                ),
            ))
        direction = directions[component]
        definition_inputs = {
            "face_mode": definition["face_mode"],
            "both_faces_evaluated": definition["both_faces_evaluated"],
            "associated_moment": definition["associated_moment"],
            "signed_v_ed": capacity.shear_direction_specs(inp)[component][
                "signed_v_ed"
            ],
        }
        for key, value in definition_inputs.items():
            if key not in direction:
                raise ValueError(f"shear direction is missing {key}")
            _same(direction[key], value, f"shear direction.{key}")
        governing = max(
            assessments,
            key=lambda item: capacity.assessment_key(item[1], item[2]),
        )
        if "governing_face" in direction:
            _same(direction["governing_face"], governing[0], "shear governing face")
        if "status" in direction:
            expected_status = capacity.aggregate_assessment_status(
                item[1] for item in assessments
            )
            _same(direction["status"], expected_status, "shear aggregate status")
    return tuple(result)


def _torsion_input_rows(rows: _Rows, inp: Mapping[str, Any]) -> str:
    inputs = [
        rows.input("input-gamma-ct", "Concrete tensile factor", ONE,
                   inp["torsion_gamma_ct"]),
        rows.input("input-wall-thickness", "Wall-thickness override", LENGTH_MM,
                   inp["torsion_tef"]),
        rows.input("input-cot-min", "Entered minimum cotangent", ANGLE,
                   inp["strut_cot_min"]),
        rows.input("input-cot-max", "Entered maximum cotangent", ANGLE,
                   inp["strut_cot_max"]),
        rows.input("input-link-diameter", "Closed-link diameter", LENGTH_MM,
                   inp["shear_link_dia"]),
        rows.input("input-link-spacing", "Closed-link spacing", LENGTH_MM,
                   inp["shear_link_s"]),
        rows.input("input-link-fywk", "Closed-link characteristic yield", STRESS,
                   inp["shear_fywk"]),
        rows.input("input-closed-detailing", "Closed detailing selected", ONE,
                   inp["torsion_nu_v"]),
        rows.input("input-subdivision", "Subdivision selected", ONE,
                   inp.get("torsion_subdivide", False)),
    ]
    for sub_index, dimensions in enumerate(
        inp.get("torsion_subrects") or (), start=1
    ):
        for name, value in zip(("x", "y", "b", "h"), dimensions):
            inputs.append(rows.input(
                f"input-subtube-{sub_index:03d}-{name}",
                f"Sub-tube {sub_index} {name}",
                LENGTH_MM,
                value,
            ))
    return rows.computed(
        "torsion-input-vector", "Entered torsion definition", ONE,
        PROJECT_TORSION, len(inputs), *inputs,
    )


def _torsion_evidence(
    inp: Mapping[str, Any], out: Mapping[str, Any], context: Mapping[str, Any]
) -> tuple[_Evidence, ...]:
    actual = _mapping(out.get("torsion"), "torsion result")
    n_prestress = capacity.prestress_axial(inp)
    n_ed_comp = -_finite(inp["P_pl"], "P_pl") + n_prestress
    try:
        _finite(inp["torsion_T"], "torsion_T")
        torsion_context = capacity.build_torsion_context(inp, n_ed_comp)
    except (KeyError, TypeError, ValueError) as exc:
        rows = _Rows()
        failure_marker = rows.method(
            "failure-input-state",
            "Malformed torsion input state",
            ONE,
            PROJECT_TORSION,
            1.0,
        )
        rows.computed("failure-state", "Invalid torsion input", ONE,
                      PROJECT_TORSION, 1.0, failure_marker)
        return (_plan(
            rows,
            family_id=TORSION_FAMILY,
            coverage_id=TORSION_COVERAGE,
            member_id="aggregate",
            calculation=calculation_id(context, "torsion", "aggregate"),
            method=method_id(inp["torsion_method"], "torsion", "failed"),
            axes=member_axes(context, member="aggregate", order="1",
                             cardinality="1", branch="failed"),
            failed=True,
            failure_reason=str(exc),
        ),)
    if torsion_context is None:
        raise ValueError("CT-007 needs an active retained torsion calculation")
    if not all(bool(item.get("valid")) for item in torsion_context["subtubes"]):
        if bool(actual.get("valid")):
            raise ValueError("invalid torsion geometry was promoted to finite")
        rows = _Rows()
        rows.input("input-torsion-demand", "Applied torsion", MOMENT,
                   torsion_context["t_ed"])
        rows.input("input-subdivision-request", "Subdivision requested", ONE,
                   torsion_context["subdivision_requested"])
        rows.computed("failure-state", "Invalid torsion tube", ONE,
                      PROJECT_TORSION, 1.0, "input-torsion-demand",
                      "input-subdivision-request")
        reason = str(torsion_context["tube"].get("reason") or _FAILURE_TEXT)
        return (_plan(
            rows,
            family_id=TORSION_FAMILY,
            coverage_id=TORSION_COVERAGE,
            member_id="aggregate",
            calculation=calculation_id(context, "torsion", "aggregate"),
            method=method_id(inp["torsion_method"], "torsion", "failed"),
            axes=member_axes(context, member="aggregate", order="1",
                             cardinality="1", branch="failed"),
            failed=True,
            failure_reason=reason,
        ),)
    actual_subs = (
        _sequence(actual.get("subtubes"), "torsion subtubes")
        if torsion_context["subdivide"]
        else (_mapping(actual.get("primary", actual), "torsion primary"),)
    )
    expected_count = len(torsion_context["subtubes"])
    if len(actual_subs) != expected_count:
        raise ValueError("torsion tube cardinality contradicts original subdivision")
    shared_cot = None
    if torsion_context["t_ed"] > 0.0:
        def tube_at(cot, tube, demand):
            kwargs = dict(
                torsion_context["_tk"], cot_min=cot, cot_max=cot
            )
            return capacity.tube_torsion(tube, demand, **kwargs)

        utilities = tuple(
            lambda cot, tube=tube, demand=demand: tube_at(
                cot, tube, demand
            )["util"]
            for tube, demand in zip(
                torsion_context["subtubes"], torsion_context["ted_parts"]
            )
        )
        shared_cot, _utilisation = combined.governing_strut_cot(
            utilities,
            torsion_context["tcot_min"],
            torsion_context["tcot_max"],
        )
    rebuilt = []
    for index, (tube, demand) in enumerate(
        zip(
            torsion_context["subtubes"],
            torsion_context["ted_parts"],
        )
    ):
        # The unpinned original range invokes the retained solver-owned selector.
        # Candidate cot values never participate in governing-state selection.
        kwargs = torsion_context["_tk"]
        if shared_cot is not None:
            kwargs = dict(
                kwargs, cot_min=shared_cot, cot_max=shared_cot
            )
        expected = capacity.tube_torsion(tube, demand, **kwargs)
        cot = _finite(expected.get("cot"), "torsion cot", positive=True)
        if not (
            torsion_context["tcot_min"] - _TOL
            <= cot
            <= torsion_context["tcot_max"] + _TOL
        ):
            raise ValueError("torsion cot(theta) is outside the original band")
        if torsion_context["subdivide"]:
            expected.update(
                stiffness=torsion_context["consts"][index],
                x_mm=torsion_context["sub_dims"][index][0],
                y_mm=torsion_context["sub_dims"][index][1],
                b_mm=torsion_context["sub_dims"][index][2],
                h_mm=torsion_context["sub_dims"][index][3],
            )
        _same(actual_subs[index], expected, f"torsion tube {index + 1}")
        rebuilt.append(expected)
    total_resistance = sum(item["trd"] for item in rebuilt)
    total_asl = sum(item["asl_req"] for item in rebuilt)
    governing = max(range(len(rebuilt)), key=lambda item: rebuilt[item]["util"])
    utilisation = rebuilt[governing]["util"]
    _same(actual.get("trd"), total_resistance, "torsion aggregate resistance")
    _same(actual.get("asl_req"), total_asl, "torsion aggregate longitudinal steel")
    _same(actual.get("util"), utilisation, "torsion aggregate utilisation")
    expected_governing = governing if torsion_context["subdivide"] else None
    top_expected = {
        "tube": rebuilt[0]["tube"],
        "trd_s": rebuilt[0]["trd_s"],
        "trd_max": rebuilt[0]["trd_max"],
        "trd_c": rebuilt[0]["trd_c"],
        "cot": rebuilt[0]["cot"],
        "theta_deg": rebuilt[0]["theta_deg"],
        "t_ed": torsion_context["t_ed"],
        "fcd": torsion_context["fcd"],
        "fywd": torsion_context["fywd_t"],
        "fyd_long": torsion_context["fyd_long"],
        "nu": rebuilt[0]["nu"],
        "alpha_cw": torsion_context["alpha_cw"],
        "fctd": torsion_context["fctd"],
        "fctk_005": torsion_context["fctk_005"],
        "gamma_c": torsion_context["gamma_c"],
        "gamma_ct": torsion_context["gamma_ct"],
        "gamma_s": torsion_context["gamma_s"],
        "nu_v_detailing": torsion_context["nu_detail_applied"],
        "sigma_cp": torsion_context["sigma_cp"],
        "n_prestress": n_prestress,
        "asw_t": torsion_context["asw_t"],
        "asw_over_s": torsion_context["asw_over_s_t"],
        "dia": inp["shear_link_dia"],
        "s": inp["shear_link_s"],
        "cot_min": torsion_context["tcot_min"],
        "cot_max": torsion_context["tcot_max"],
        "method": inp["torsion_method"],
        "governs": rebuilt[0]["governs"],
        "valid": True,
        "reason": torsion_context["tube"].get("reason"),
        "subdivided": torsion_context["subdivide"],
        "governing_sub": expected_governing,
        "compound_detected": torsion_context["compound_detected"],
        "subdivision_requested": torsion_context["subdivision_requested"],
        "subdivision_valid": torsion_context["subdivision_valid"],
        "subdivision_reason": torsion_context["subdivision_reason"],
    }
    for key, value in top_expected.items():
        if key not in actual:
            raise ValueError(f"torsion result is missing {key}")
        _same(actual[key], value, f"torsion.{key}")
    evidence: list[_Evidence] = []
    cardinality = len(rebuilt) + 1
    for index, item in enumerate(rebuilt, start=1):
        rows = _Rows()
        geometry = _geometry_rows(rows, inp, PROJECT_TORSION)
        materials = _law_rows(
            rows,
            inp,
            include_assignments=False,
            project_source=PROJECT_TORSION,
        )
        demand_id = rows.input("input-torsion-demand", "Total applied torsion", MOMENT,
                               torsion_context["t_ed"])
        axial_id = rows.input("input-axial-action", "Tension-positive axial action", FORCE,
                              inp["P_pl"])
        torsion_inputs = _torsion_input_rows(rows, inp)
        dk_method = None
        if "DK NA" in inp["torsion_method"]:
            dk_method = rows.method(
                "method-dk-na", "Danish torsion values selected", ONE,
                DK_TORSION, 1.0,
            )
        share = rows.computed(
            "tube-torsion-demand", "Tube torque share", MOMENT,
            PROJECT_TORSION, item["t_ed"], demand_id, geometry,
            torsion_inputs,
            expression="TEd * C_i / sum(C)",
        )
        tef = rows.computed("effective-wall-thickness", "Effective wall thickness",
                            LENGTH_MM, PROJECT_TORSION, item["tube"]["tef"],
                            geometry, torsion_inputs)
        ak = rows.computed("tube-area", "Area enclosed by wall centreline", AREA_M2,
                           PROJECT_TORSION, item["tube"]["Ak"], geometry, tef)
        prestress = rows.computed(
            "prestress-axial", "Locked-in prestress axial force", FORCE,
            PROJECT_TORSION, n_prestress, geometry, materials,
        )
        ncomp = rows.computed(
            "compression-positive-axial", "Net compression-positive axial", FORCE,
            PROJECT_TORSION, n_ed_comp, axial_id, prestress,
        )
        alpha_cw = rows.computed(
            "alpha-cw", "Axial compression factor", RATIO, BASE_TORSION,
            torsion_context["alpha_cw"], ncomp, geometry, materials,
        )
        fctd = rows.computed(
            "fctd", "Design concrete tensile strength", STRESS,
            PROJECT_TORSION, torsion_context["fctd"], torsion_inputs, materials,
        )
        fywd = rows.computed(
            "fywd", "Design closed-link yield", STRESS, PROJECT_TORSION,
            torsion_context["fywd_t"], torsion_inputs, materials,
        )
        fyd_long = rows.computed(
            "fyd-longitudinal", "Design longitudinal yield", STRESS,
            PROJECT_TORSION, torsion_context["fyd_long"], materials,
        )
        nu = rows.computed(
            "torsion-effectiveness", "Torsion effectiveness factor", RATIO,
            DK_TORSION if dk_method is not None else BASE_TORSION,
            item["nu"], materials, torsion_inputs,
            *((dk_method,) if dk_method is not None else ()),
        )
        cot_id = rows.computed("shared-cot-theta", "Retained tube cotangent",
                               ANGLE, PROJECT_SHARED_ANGLE, item["cot"], share,
                               geometry, materials, ncomp, torsion_inputs)
        trd_s = rows.computed("stirrup-resistance", "Torsion stirrup resistance", MOMENT,
                              BASE_TORSION, item["trd_s"], share, ak, cot_id,
                              fywd, torsion_inputs)
        trd_max = rows.computed("strut-resistance", "Torsion strut resistance", MOMENT,
                                BASE_TORSION, item["trd_max"], ak, tef, cot_id,
                                materials, alpha_cw, nu, torsion_inputs)
        rows.computed("cracking-resistance", "Torsional cracking resistance",
                      MOMENT, BASE_TORSION, item["trd_c"], ak, tef, fctd)
        trd = rows.computed("governing-resistance", "Governing torsion resistance",
                            MOMENT, BASE_TORSION, item["trd"], trd_s, trd_max,
                            expression="min(TRd,s, TRd,max)")
        rows.computed("longitudinal-steel", "Required longitudinal torsion steel",
                      AREA_MM2, BASE_TORSION, item["asl_req"], share, ak,
                      cot_id, fyd_long)
        util = rows.computed("utilisation", "Tube torsion utilisation", RATIO,
                             PROJECT_TORSION, item["util"], share, trd,
                             expression="TEd,i / TRd,i")
        verdict = item["util"] <= 1.0 + _TOL
        rows.computed("verdict", "Tube torsion verdict", ONE, PROJECT_TORSION,
                      verdict, util, expression="utilisation <= 1 + 1e-9")
        member = f"tube-{index:03d}"
        evidence.append(_plan(
            rows,
            family_id=TORSION_FAMILY,
            coverage_id=TORSION_COVERAGE,
            member_id=member,
            calculation=calculation_id(context, "torsion", member),
            method=method_id(inp["torsion_method"], "torsion", "tube"),
            axes=member_axes(context, member="tube", tube=str(index),
                             order=str(index), cardinality=str(cardinality),
                             branch="finite", subdivided=str(
                                 bool(torsion_context["subdivide"])
                             ).lower()),
            failed=False,
            assumptions=("Sector public torsion demand retains its entered sign.",),
        ))
    rows = _Rows()
    geometry = _geometry_rows(rows, inp, PROJECT_TORSION)
    materials = _law_rows(
        rows,
        inp,
        include_assignments=False,
        project_source=PROJECT_TORSION,
    )
    demand_id = rows.input("input-torsion-demand", "Total applied torsion", MOMENT,
                           torsion_context["t_ed"])
    axial_id = rows.input(
        "input-axial-action", "Tension-positive axial action", FORCE,
        inp["P_pl"],
    )
    torsion_inputs = _torsion_input_rows(rows, inp)
    for index, item in enumerate(rebuilt, start=1):
        rows.computed(
            f"tube-{index:03d}-resistance", f"Tube {index} resistance", MOMENT,
            PROJECT_TORSION, item["trd"], demand_id, axial_id, geometry,
            materials, torsion_inputs,
        )
        rows.computed(
            f"tube-{index:03d}-utilisation", f"Tube {index} utilisation", RATIO,
            PROJECT_TORSION, item["util"], demand_id, axial_id, geometry,
            materials, torsion_inputs,
        )
    resistance_ids = tuple(
        f"tube-{index:03d}-resistance" for index in range(1, len(rebuilt) + 1)
    )
    util_ids = tuple(
        f"tube-{index:03d}-utilisation" for index in range(1, len(rebuilt) + 1)
    )
    total = rows.computed("aggregate-resistance", "Aggregate torsion resistance",
                          MOMENT, PROJECT_TORSION, total_resistance, *resistance_ids,
                          expression="sum(TRd,i)")
    gov = rows.computed("governing-tube", "Governing tube index", ONE,
                        PROJECT_TORSION, governing + 1, *util_ids,
                        expression="argmax(TEd,i / TRd,i)")
    util = rows.computed("utilisation", "Governing torsion utilisation", RATIO,
                         PROJECT_TORSION, utilisation, gov, *util_ids)
    verdict = utilisation <= 1.0 + _TOL
    rows.computed("verdict", "Aggregate torsion verdict", ONE, PROJECT_TORSION,
                  verdict, util, total)
    evidence.append(_plan(
        rows,
        family_id=TORSION_FAMILY,
        coverage_id=TORSION_COVERAGE,
        member_id="aggregate",
        calculation=calculation_id(context, "torsion", "aggregate"),
        method=method_id(inp["torsion_method"], "torsion", "aggregate"),
        axes=member_axes(context, member="aggregate", order=str(cardinality),
                         cardinality=str(cardinality), branch="finite",
                         subdivided=str(
                             bool(torsion_context["subdivide"])
                         ).lower()),
        failed=False,
    ))
    return tuple(evidence)


def _transverse_request(inp: Mapping[str, Any]) -> dict[str, Any]:
    n_prestress = capacity.prestress_axial(inp)
    n_ed_comp = -_finite(inp["P_pl"], "P_pl") + n_prestress
    shear_specs = []
    if inp.get("shear_on"):
        directional = capacity.build_directional_shear_contexts(
            inp, n_prestress, n_ed_comp
        )
        if not directional:
            payload, links = capacity.build_shear_context(inp, n_prestress, n_ed_comp)
            directional = {} if payload is None else {
                payload["component"]: {"candidates": [(payload, links)]}
            }
        for component in (key for key in ("vx", "vy") if key in directional):
            candidates = tuple(directional[component]["candidates"])
            depths = [item[0]["d"] for item in candidates if item[0]["d"] > 0.0]
            payload, links = candidates[0]
            valid = all(bool(item[0]["res"].get("valid")) for item in candidates)
            links_required = (
                any(item[0]["v_ed"] > item[0]["res"]["vrd_c"] + _TOL
                    for item in candidates)
                if valid else None
            )
            shear_specs.append({
                "component": component,
                "links_present": bool(inp.get("shear_links")),
                "links_required": links_required,
                "requirement_clause": "8.2.2" if payload["model_2023"] else "6.2.2",
                "bw_mm": payload["bw"],
                "d_mm": min(depths, default=0.0),
                "legs": (
                    links["link_legs"]
                    if links is not None
                    else inp.get(
                        "shear_vx_link_legs"
                        if component == "vx" else "shear_vy_link_legs",
                        0.0,
                    )
                ),
                "transverse_leg_spacing_mm": inp.get(
                    "shear_vx_transverse_leg_spacing"
                    if component == "vx" else "shear_vy_transverse_leg_spacing",
                    0.0,
                ),
                "measurement_axis": "y" if component == "vx" else "x",
            })
    torsion_specs = []
    if inp.get("torsion_on"):
        context = capacity.build_torsion_context(inp, n_ed_comp)
        if context is not None:
            for index, tube in enumerate(context["subtubes"], start=1):
                torsion_specs.append({
                    "label": f"Tube {index}" if context["subdivide"] else "Tube",
                    "valid": bool(tube.get("valid")),
                    "reason": tube.get("reason"),
                    "tef_mm": tube.get("tef", 0.0),
                    "uk_mm": float(tube.get("uk", 0.0)) * 1000.0,
                    "minimum_dimension_mm": tube.get("minimum_dimension_mm", 0.0),
                })
    return dict(
        edition=inp["detailing_edition"],
        fck_mpa=inp["concrete"].fck,
        fywk_mpa=inp["shear_fywk"],
        diameter_mm=inp["shear_link_dia"],
        spacing_mm=inp["shear_link_s"],
        shear_directions=shear_specs,
        torsion_tubes=torsion_specs,
        ductility_class=inp.get("transverse_ductility_class", "B"),
        apply_ductility_reduction=inp.get("transverse_apply_ductility_reduction", False),
        member_type=inp.get("detailing_member_type", detailing.MEMBER_BEAM),
    )


def _detailing_element_rows(rows: _Rows, inp: Mapping[str, Any]) -> str:
    records = list(inp.get("bar_elements") or [])
    if inp.get("detailing_include_tendons"):
        records.extend(inp.get("tendon_elements") or [])
    leaves = []
    for index, item in enumerate(records):
        item = _mapping(item, f"detailing element {index}")
        identity = trace_identity_token(
            "\x00".join((
                str(item.get("id") or index + 1),
                str(item.get("kind") or "bar"),
                str(item.get("material_id") or ""),
            ))
        )
        prefix = f"element-{index:04d}-{identity}"
        for key, title in (
            ("x_mm", "Element x"),
            ("y_mm", "Element y"),
            ("diameter_mm", "Element diameter"),
        ):
            leaves.append(rows.input(
                f"{prefix}-{key.replace('_', '-')}",
                title,
                LENGTH_MM,
                item[key],
            ))
    return rows.computed(
        "detailing-element-vector",
        "Ordered included detailing elements",
        ONE,
        PROJECT_DETAILING,
        len(leaves),
        *leaves,
    )


def _detail_member(
    *,
    inp: Mapping[str, Any],
    context: Mapping[str, Any],
    edition: str,
    subfamily: str,
    member: str,
    order: int,
    cardinality: int,
    original_inputs: tuple[tuple[str, str, Any, Any], ...],
    expected: Mapping[str, Any] | None,
    actual: Mapping[str, Any] | None,
    failure_status: str | None = None,
    failure_reason: str | None = None,
) -> _Evidence:
    rows = _Rows()
    owned_axes = {}
    if subfamily == "longitudinal":
        owned_axes = {
            "member_type": str(
                inp.get("detailing_member_type", detailing.MEMBER_BEAM)
            ),
            "cut_direction": str(
                inp.get("detailing_cut_direction", detailing.CUT_TRANSVERSE)
            ),
        }
    elif subfamily == "clear-spacing":
        owned_axes = {
            "include_tendons": str(
                bool(inp.get("detailing_include_tendons"))
            ).lower(),
        }
    elif subfamily == "transverse":
        owned_axes = {
            "member_type": str(
                inp.get("detailing_member_type", detailing.MEMBER_BEAM)
            ),
            "ductility_class": str(
                inp.get("transverse_ductility_class", "B")
            ).upper(),
            "ductility_reduction": str(bool(inp.get(
                "transverse_apply_ductility_reduction", False
            ))).lower(),
        }
    input_ids = []
    for step_id, title, unit, value in original_inputs:
        input_ids.append(rows.input(step_id, title, unit, value))
    if failure_status is not None:
        if actual is not None:
            _same(actual.get("status"), failure_status, f"{subfamily} failure status")
        rows.computed("failure-state", "Explicit detailing state", ONE,
                      PROJECT_DETAILING, 1.0, *input_ids)
        return _plan(
            rows,
            family_id=DETAILING_FAMILY,
            coverage_id=DETAILING_COVERAGE,
            member_id=member,
            calculation=calculation_id(context, "detailing", member),
            method=method_id(edition, "detailing", subfamily),
            axes=member_axes(context, subfamily=subfamily, member=member,
                             order=str(order), cardinality=str(cardinality),
                             branch="failed", **owned_axes),
            failed=True,
            failure_reason=failure_reason or failure_status,
        )
    if subfamily == "longitudinal":
        input_ids.append(_geometry_rows(
            rows,
            inp,
            PROJECT_DETAILING,
            include_tendons=False,
        ))
        input_ids.append(_law_rows(
            rows,
            inp,
            include_assignments=True,
            project_source=PROJECT_DETAILING,
            include_tendons=False,
        ))
    elif subfamily == "clear-spacing":
        input_ids.append(_detailing_element_rows(rows, inp))
    elif subfamily == "transverse":
        input_ids.append(_geometry_rows(
            rows, inp, PROJECT_DETAILING
        ))
        input_ids.append(_law_rows(
            rows,
            inp,
            include_assignments=True,
            project_source=PROJECT_DETAILING,
        ))
        action_inputs = (
            ("input-transverse-p", "Tension-positive axial action", FORCE,
             inp["P_pl"]),
            ("input-transverse-mx", "Applied Mx", MOMENT, inp["Mx_pl"]),
            ("input-transverse-my", "Applied My", MOMENT, inp["My_pl"]),
            ("input-transverse-vx", "Signed Vx", FORCE,
             capacity.shear_direction_specs(inp)["vx"]["signed_v_ed"]),
            ("input-transverse-vy", "Signed Vy", FORCE,
             capacity.shear_direction_specs(inp)["vy"]["signed_v_ed"]),
            ("input-transverse-t", "Applied torsion", MOMENT,
             inp.get("torsion_T", 0.0)),
        )
        for step_id, title, unit, value in action_inputs:
            input_ids.append(rows.input(step_id, title, unit, value))
        optional_inputs = (
            ("shear_vx_bw", "Vx web-width override", LENGTH_MM),
            ("shear_vy_bw", "Vy web-width override", LENGTH_MM),
            ("shear_vx_link_legs", "Vx effective link legs", ONE),
            ("shear_vy_link_legs", "Vy effective link legs", ONE),
            (
                "shear_vx_transverse_leg_spacing",
                "Vx transverse leg spacing",
                LENGTH_MM,
            ),
            (
                "shear_vy_transverse_leg_spacing",
                "Vy transverse leg spacing",
                LENGTH_MM,
            ),
            ("torsion_tef", "Torsion wall-thickness override", LENGTH_MM),
            (
                "transverse_apply_ductility_reduction",
                "Ductility reduction selected",
                ONE,
            ),
        )
        for key, title, unit in optional_inputs:
            if key in inp:
                input_ids.append(rows.input(
                    f"input-{key.replace('_', '-')}", title, unit, inp[key]
                ))
        for index, dimensions in enumerate(
            inp.get("torsion_subrects") or (), start=1
        ):
            for name, value in zip(("x", "y", "b", "h"), dimensions):
                input_ids.append(rows.input(
                    f"input-detailing-subtube-{index:03d}-{name}",
                    f"Detailing sub-tube {index} {name}",
                    LENGTH_MM,
                    value,
                ))
    if expected is None or actual is None:
        raise ValueError("finite detailing member needs expected and actual evidence")
    _same(actual, expected, f"detailing {member}")
    rule = detailing_rule_source(edition, subfamily)
    if "DK NA" in edition and subfamily == "transverse":
        rows.method("method-dk-na", "Danish transverse ratio selected", ONE,
                    DK_TRANSVERSE, 1.0)
    evidence_id = rows.computed(
        "authoritative-check", "Authoritative detailing check", ONE,
        PROJECT_DETAILING, len(expected), *input_ids,
    )
    numeric_ids = []
    preferred = (
        "demand_kn", "resistance_kn", "as_min_mm2", "as_provided_mm2",
        "provided", "limit", "utilisation", "centre_distance_mm", "clear_mm",
        "required_mm", "margin_mm", "phi_first_mm", "phi_second_mm",
    )
    units = {
        "demand_kn": FORCE, "resistance_kn": FORCE,
        "as_min_mm2": AREA_MM2, "as_provided_mm2": AREA_MM2,
        "provided": RATIO if expected.get("kind") == "minimum_ratio" else LENGTH_MM,
        "limit": RATIO if expected.get("kind") == "minimum_ratio" else LENGTH_MM,
        "utilisation": RATIO, "centre_distance_mm": LENGTH_MM,
        "clear_mm": LENGTH_MM, "required_mm": LENGTH_MM, "margin_mm": LENGTH_MM,
        "phi_first_mm": LENGTH_MM, "phi_second_mm": LENGTH_MM,
    }
    for key in preferred:
        value = expected.get(key)
        if type(value) in {int, float} and math.isfinite(float(value)):
            numeric_ids.append(rows.computed(
                key.replace("_", "-"), key.replace("_", " ").title(), units[key],
                rule, value, evidence_id, *input_ids,
            ))
    status = str(expected.get("status") or "").upper()
    if status not in {"PASS", "FAIL"}:
        raise ValueError("finite detailing member lacks a genuine verdict")
    rows.computed("verdict", "Detailing verdict", ONE, PROJECT_DETAILING,
                  status == "PASS", evidence_id, *numeric_ids)
    return _plan(
        rows,
        family_id=DETAILING_FAMILY,
        coverage_id=DETAILING_COVERAGE,
        member_id=member,
        calculation=calculation_id(context, "detailing", member),
        method=method_id(edition, "detailing", subfamily),
        axes=member_axes(context, subfamily=subfamily, member=member,
                         order=str(order), cardinality=str(cardinality),
                         branch="finite", **owned_axes),
        failed=False,
    )


def _detailing_evidence(
    inp: Mapping[str, Any], out: Mapping[str, Any], context: Mapping[str, Any]
) -> tuple[_Evidence, ...]:
    edition = inp["detailing_edition"]
    pending: list[dict[str, Any]] = []
    if inp.get("minimum_reinforcement_on"):
        expected = detailing.minimum_reinforcement(
            inp["section"],
            inp.get("bar_elements") or [],
            inp.get("bar_materials") or [],
            inp["concrete"],
            edition=edition,
            fctm_mpa=inp["sls_fctm"],
            n_ed_tension_kn=inp["P_pl"],
            mx_ed_knm=inp["Mx_pl"],
            my_ed_knm=inp["My_pl"],
            member_type=inp.get("detailing_member_type", detailing.MEMBER_BEAM),
            cut_direction=inp.get("detailing_cut_direction", detailing.CUT_TRANSVERSE),
        )
        actual = _mapping(out.get("minimum_reinforcement"), "minimum reinforcement")
        _same(actual.get("status"), expected["status"], "minimum aggregate status")
        if expected["status"] in {"PASS", "FAIL"}:
            for key in (
                "edition", "member_type", "cut_direction",
                "modelled_reinforcement_direction", "clause",
            ):
                _same(actual.get(key), expected.get(key), f"minimum.{key}")
        checks = tuple(expected.get("checks") or ())
        actual_checks = _sequence(actual.get("checks") or (), "minimum checks")
        if checks:
            if len(actual_checks) != len(checks):
                raise ValueError("minimum reinforcement has wrong cardinality")
            for index, check in enumerate(checks, start=1):
                pending.append(dict(
                    subfamily="longitudinal", member=f"longitudinal-{index:03d}",
                    inputs=(
                        ("input-axial-action", "Tension-positive axial action", FORCE, inp["P_pl"]),
                        ("input-mx", "Applied Mx", MOMENT, inp["Mx_pl"]),
                        ("input-my", "Applied My", MOMENT, inp["My_pl"]),
                        ("input-fctm", "Mean tensile strength", STRESS, inp["sls_fctm"]),
                    ),
                    expected=check, actual=_mapping(actual_checks[index - 1], "minimum check"),
                    status=None if check["status"] in {"PASS", "FAIL"} else check["status"],
                    reason=check.get("reason") or expected.get("reason"),
                ))
        else:
            pending.append(dict(
                subfamily="longitudinal", member="longitudinal-state",
                inputs=((
                    "input-axial-action", "Tension-positive axial action",
                    FORCE, inp["P_pl"],
                ),),
                expected=None, actual=actual, status=expected["status"],
                reason=expected.get("reason"),
            ))
    if inp.get("clear_spacing_on"):
        expected = detailing.clear_spacing(
            list(inp.get("bar_elements") or []) + list(inp.get("tendon_elements") or []),
            d_upper_mm=inp["detailing_d_upper"],
            edition=edition,
            include_tendons=inp.get("detailing_include_tendons", False),
        )
        actual = _mapping(out.get("clear_spacing"), "clear spacing")
        _same(actual.get("status"), expected["status"], "spacing aggregate status")
        if expected["status"] in {"PASS", "FAIL"}:
            for key in (
                "edition", "clause", "d_upper_mm", "include_tendons",
                "governing",
            ):
                _same(actual.get(key), expected.get(key), f"clear spacing.{key}")
        pairs = tuple(expected.get("pairs") or ())
        actual_pairs = _sequence(actual.get("pairs") or (), "clear spacing pairs")
        if pairs:
            if len(actual_pairs) != len(pairs):
                raise ValueError("clear-spacing pairs have wrong cardinality")
            for index, pair in enumerate(pairs, start=1):
                pending.append(dict(
                    subfamily="clear-spacing", member=f"clear-spacing-{index:03d}",
                    inputs=(
                        ("input-d-upper", "Maximum aggregate size", LENGTH_MM,
                         inp["detailing_d_upper"]),
                        ("input-include-tendons", "Include tendon envelopes", ONE,
                         inp.get("detailing_include_tendons", False)),
                    ),
                    expected=pair, actual=_mapping(actual_pairs[index - 1], "clear pair"),
                    status=None, reason=None,
                ))
        else:
            pending.append(dict(
                subfamily="clear-spacing", member="clear-spacing-state",
                inputs=(("input-d-upper", "Maximum aggregate size", LENGTH_MM,
                         inp["detailing_d_upper"]),),
                expected=None, actual=actual, status=expected["status"],
                reason=expected.get("reason"),
            ))
    if inp.get("transverse_detailing_on"):
        request = _transverse_request(inp)
        expected = detailing.transverse_reinforcement(**request)
        actual = _mapping(out.get("transverse_reinforcement"), "transverse reinforcement")
        _same(actual.get("status"), expected["status"], "transverse aggregate status")
        if expected["checks"]:
            for key in (
                "edition", "member_type", "governing",
                "governing_utilisation", "minimum_ratio", "diameter_mm",
                "spacing_mm", "fywk_mpa",
            ):
                _same(actual.get(key), expected.get(key), f"transverse.{key}")
        checks = tuple(expected.get("checks") or ())
        actual_checks = _sequence(actual.get("checks") or (), "transverse checks")
        if checks:
            if len(actual_checks) != len(checks):
                raise ValueError("transverse checks have wrong cardinality")
            for index, check in enumerate(checks, start=1):
                pending.append(dict(
                    subfamily="transverse", member=f"transverse-{index:03d}",
                    inputs=(
                        (
                            "input-fck", "Concrete characteristic strength",
                            STRESS, request["fck_mpa"],
                        ),
                        ("input-fywk", "Link characteristic yield", STRESS, request["fywk_mpa"]),
                        ("input-link-diameter", "Link diameter", LENGTH_MM, request["diameter_mm"]),
                        ("input-link-spacing", "Link spacing", LENGTH_MM, request["spacing_mm"]),
                    ),
                    expected=check, actual=_mapping(actual_checks[index - 1], "transverse check"),
                    status=None if check["status"] in {"PASS", "FAIL"} else check["status"],
                    reason=check.get("reason"),
                ))
        else:
            pending.append(dict(
                subfamily="transverse", member="transverse-state",
                inputs=(("input-link-spacing", "Link spacing", LENGTH_MM,
                         request["spacing_mm"]),),
                expected=None, actual=actual, status=expected["status"],
                reason=expected.get("reason"),
            ))
    if not pending:
        raise ValueError("CT-008 needs an active retained detailing result")
    cardinality = len(pending)
    return tuple(
        _detail_member(
            inp=inp,
            context=context,
            edition=edition,
            subfamily=item["subfamily"],
            member=item["member"],
            order=index,
            cardinality=cardinality,
            original_inputs=item["inputs"],
            expected=item["expected"],
            actual=item["actual"],
            failure_status=item["status"],
            failure_reason=item["reason"],
        )
        for index, item in enumerate(pending, start=1)
    )


def _build(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None,
    families: tuple[str, ...],
) -> TraceBundle:
    try:
        source_input = _mapping(inp, "PR-08C input")
        source_output = _mapping(out, "PR-08C result")
        trace_context = {} if context is None else _mapping(context, "PR-08C context")
        evidence: list[_Evidence] = []
        if "shear" in families:
            evidence.extend(_shear_evidence(source_input, source_output, trace_context))
        if "torsion" in families:
            evidence.extend(_torsion_evidence(source_input, source_output, trace_context))
        if "detailing" in families:
            evidence.extend(_detailing_evidence(source_input, source_output, trace_context))
        return _bundle(
            tuple(evidence), input_sha256=input_sha256, result_sha256=result_sha256
        )
    except TraceValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid PR-08C evidence: {exc}") from exc


def build_shear_trace_family(
    inp: Mapping[str, Any], out: Mapping[str, Any], *, input_sha256: str,
    result_sha256: str, context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    return _build(inp, out, input_sha256=input_sha256, result_sha256=result_sha256,
                  context=context, families=("shear",))


def build_torsion_trace_family(
    inp: Mapping[str, Any], out: Mapping[str, Any], *, input_sha256: str,
    result_sha256: str, context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    return _build(inp, out, input_sha256=input_sha256, result_sha256=result_sha256,
                  context=context, families=("torsion",))


def build_detailing_trace_family(
    inp: Mapping[str, Any], out: Mapping[str, Any], *, input_sha256: str,
    result_sha256: str, context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    return _build(inp, out, input_sha256=input_sha256, result_sha256=result_sha256,
                  context=context, families=("detailing",))


def build_pr08c_trace_families(
    inp: Mapping[str, Any], out: Mapping[str, Any], *, input_sha256: str,
    result_sha256: str, context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    families = tuple(
        name for name, active in (
            ("shear", inp.get("shear_on")),
            ("torsion", inp.get("torsion_on")),
            ("detailing", any(inp.get(key) for key in (
                "minimum_reinforcement_on", "clear_spacing_on",
                "transverse_detailing_on",
            ))),
        )
        if active
    )
    return _build(inp, out, input_sha256=input_sha256, result_sha256=result_sha256,
                  context=context, families=families)


__all__ = [
    "build_detailing_trace_family", "build_pr08c_trace_families",
    "build_shear_trace_family", "build_torsion_trace_family",
]
