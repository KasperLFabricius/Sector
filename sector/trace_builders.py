"""Solver-adjacent CT-002 through CT-004 calculation-trace builders."""
from __future__ import annotations
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any
from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY,
    RESULT_UNDEFINED,
    ROLE_COMPUTED,
    ROLE_FINAL,
    ROLE_USER_INPUT,
    SOURCE_INPUT,
    SOURCE_PROJECT,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceSource,
    TraceStep,
    TraceUnit,
    create_bundle,
)
from .section_trace_blocks import (
    MaterialBlock,
    SectionTraceBlocks,
    context_axes,
    context_id,
    section_trace_blocks,
)
from .trace_registry import (
    TraceFamilyContract,
    TraceMemberContract,
    TraceRegistryContract,
    TraceSourceContract,
    audit_trace_registry,
)
INPUT = TraceSource(SOURCE_INPUT, "user-input")
GEOMETRY = TraceSource(SOURCE_PROJECT, "sector-section-geometry")
ASSIGNMENT = TraceSource(SOURCE_PROJECT, "sector-material-assignment")
PLASTIC = TraceSource(SOURCE_PROJECT, "sector-plastic-section-equilibrium")
RADIAL = TraceSource(SOURCE_PROJECT, "sector-radial-envelope-intersection")
UNITS = {
    "1": TraceUnit("1", "dimensionless"),
    "m": TraceUnit("m", "length"),
    "m2": TraceUnit("m2", "area"),
    "kN": TraceUnit("kN", "force"),
    "kNm": TraceUnit("kNm", "moment"),
    "MPa": TraceUnit("MPa", "stress"),
    "1/m": TraceUnit("1/m", "curvature"),
    "degrees": TraceUnit("degrees", "angle"),
}
def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-") or "value"
def _number(value: Any) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise ValueError("expected a finite non-Boolean number")
    return float(value)
def _fmt(value: float) -> str:
    return f"{value:.9g}"
def _value(value: Any, *names: str) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return None
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None
def _result(value: Any, *, invalid_reason: str) -> TraceResult:
    if type(value) is bool or value is None:
        return TraceResult(RESULT_FAILED, None, invalid_reason)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return TraceResult(RESULT_FAILED, None, invalid_reason)
    if math.isnan(number):
        return TraceResult(RESULT_UNDEFINED, None, invalid_reason)
    if number == math.inf:
        return TraceResult(RESULT_POSITIVE_INFINITY, None, invalid_reason)
    if number == -math.inf:
        return TraceResult(RESULT_NEGATIVE_INFINITY, None, invalid_reason)
    return TraceResult(RESULT_FINITE, number)
class _Calculation:
    def __init__(
        self,
        calculation_id: str,
        coverage_id: str,
        title: str,
        method_id: str,
        axes: tuple,
    ):
        self.calculation_id = calculation_id
        self.coverage_id = coverage_id
        self.title = title
        self.method_id = method_id
        self.axes = axes
        self.steps: list[TraceStep] = []
    def add(
        self,
        step_id: str,
        title: str,
        symbol: str,
        unit: str,
        result: TraceResult,
        *,
        source: TraceSource,
        dependencies: Sequence[str] = (),
        role: str = ROLE_COMPUTED,
        expression: str = "solver-owned value",
        substitution: str | None = None,
        warning: str | None = None,
        assumption: str | None = None,
    ) -> str:
        deps = tuple(
            TraceDependency(item, next(step.unit for step in self.steps if step.step_id == item))
            for item in dependencies
        )
        text = substitution or (
            _fmt(result.value) if result.state == RESULT_FINITE else str(result.reason)
        )
        self.steps.append(
            TraceStep(
                step_id,
                title,
                deps,
                role,
                source,
                symbol,
                UNITS[unit],
                expression,
                text,
                result,
                (warning,) if warning else (),
                (assumption,) if assumption else (),
            )
        )
        return step_id
    def input(self, step_id: str, title: str, symbol: str, unit: str, value: Any) -> str:
        number = _number(value)
        return self.add(
            step_id,
            title,
            symbol,
            unit,
            TraceResult(RESULT_FINITE, number),
            source=INPUT,
            role=ROLE_USER_INPUT,
            expression=f"{symbol} is an exact solver input",
            substitution=f"{symbol} = {_fmt(number)} {unit}",
        )
    def finish(
        self,
        final_step_id: str,
        *,
        warnings: tuple[str, ...] = (),
        assumptions: tuple[str, ...] = (),
    ) -> TraceCalculation:
        return TraceCalculation(
            self.calculation_id,
            self.coverage_id,
            self.title,
            self.method_id,
            self.axes,
            final_step_id,
            tuple(self.steps),
            warnings,
            assumptions,
        )
def _geometry(calc: _Calculation, blocks: SectionTraceBlocks) -> str:
    leaves: list[str] = []
    for ring_index, ring in enumerate(blocks.geometry.rings):
        label = "outer" if ring_index == 0 else f"hole-{ring_index:03d}"
        for index, (x, y) in enumerate(ring, start=1):
            prefix = f"geometry-{label}-{index:03d}"
            leaves.extend(
                (
                    calc.input(f"{prefix}-x", f"{label} vertex {index} x", "x", "m", x),
                    calc.input(f"{prefix}-y", f"{label} vertex {index} y", "y", "m", y),
                )
            )
    for kind, elements in (("bar", blocks.geometry.bars), ("tendon", blocks.geometry.tendons)):
        for index, item in enumerate(elements, start=1):
            prefix = f"geometry-{kind}-{index:03d}"
            leaves.extend(
                (
                    calc.input(f"{prefix}-x", f"{kind} {index} x", "x", "m", item.x),
                    calc.input(f"{prefix}-y", f"{kind} {index} y", "y", "m", item.y),
                    calc.input(f"{prefix}-area", f"{kind} {index} area", "A", "m2", item.area),
                )
            )
    return calc.add(
        "section-geometry",
        "Exact ordered section geometry",
        "geometry",
        "1",
        TraceResult(RESULT_FINITE, 1.0),
        source=GEOMETRY,
        dependencies=leaves,
        expression="geometry = ordered rings + aligned point areas",
        assumption="A value of 1 records exact solver geometry, not a verdict.",
    )
def _material_unit(name: str) -> str:
    return "MPa" if name in {"fck", "fytk", "fyck", "futk", "Es"} else "1"
def _plastic_materials(calc: _Calculation, blocks: SectionTraceBlocks) -> tuple[str, ...]:
    outputs: list[str] = []
    groups: dict[tuple, str] = {}
    assignment_counts = {"bar": 0, "tendon": 0}
    for material in (blocks.concrete, *blocks.bars, *blocks.tendons):
        key = (material.kind, material.values, material.provenance.source)
        law = groups.get(key)
        if law is None:
            prefix = "concrete" if material.kind == "concrete" else (
                f"{material.kind}-{len([k for k in groups if k[0] == material.kind]) + 1:03d}"
            )
            leaves = [
                calc.input(
                    f"{prefix}-{_slug(name)}",
                    f"{material.kind} {name}",
                    name,
                    _material_unit(name),
                    value,
                )
                for name, value in material.values
            ]
            law = calc.add(
                f"{prefix}-law",
                f"Selected {material.kind} constitutive law",
                f"law_{material.kind}",
                "1",
                TraceResult(RESULT_FINITE, 1.0),
                source=material.provenance.source,
                dependencies=leaves,
                expression="law = exact recorded constitutive parameter vector",
            )
            groups[key] = law
        if material.kind == "concrete":
            outputs.append(law)
        else:
            assignment_counts[material.kind] += 1
            index = assignment_counts[material.kind]
            assignment = calc.add(
                f"{material.kind}-assignment-{index:03d}",
                f"Material assignment for {material.element_id}",
                f"I_{material.kind}",
                "1",
                TraceResult(RESULT_FINITE, 1.0),
                source=ASSIGNMENT,
                dependencies=(law,),
                expression=f"{material.element_id} -> {material.material_id}",
            )
            outputs.append(assignment)
    return tuple(outputs)
def _plastic_base(
    calc: _Calculation,
    inp: Mapping[str, Any],
    blocks: SectionTraceBlocks,
) -> tuple[str, ...]:
    values = dict(blocks.plastic_actions.values)
    actions = (
        calc.input("n-ed", "Applied axial force", "NEd", "kN", values["P_pl"]),
        calc.input("mx-ed", "Applied x-axis moment", "MxEd", "kNm", values["Mx_pl"]),
        calc.input("my-ed", "Applied y-axis moment", "MyEd", "kNm", values["My_pl"]),
    )
    return (*actions, _geometry(calc, blocks), *_plastic_materials(calc, blocks))
def _failed_final(calc: _Calculation, source: TraceSource, deps: Sequence[str], reason: str) -> str:
    return calc.add(
        "solver-state",
        "Explicit unavailable solver result",
        "state",
        "1",
        TraceResult(RESULT_FAILED, None, reason),
        source=source,
        dependencies=deps,
        role=ROLE_FINAL,
        warning=reason,
        expression="state = failed",
    )
def _capacity(
    inp: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
    blocks: SectionTraceBlocks,
) -> TraceCalculation:
    cid = context_id(context)
    calc = _Calculation(
        f"plastic.{cid}.capacity",
        "ct-002",
        "Plastic section capacity at the selected solver state",
        blocks.plastic_method_id,
        context_axes(context),
    )
    base = _plastic_base(calc, inp, blocks)
    points, mx, my = list(result.get("points") or ()), list(result.get("mx") or ()), list(result.get("my") or ())
    reason = None
    if not points or len(points) != len(mx) or len(mx) != len(my):
        reason = "plastic envelope point arrays are missing or misaligned"
    else:
        raw_index = result.get("util_gov")
        if type(raw_index) is not int or not 0 <= raw_index < len(points):
            reason = "selected plastic solver index is missing or invalid"
            return calc.finish(_failed_final(calc, PLASTIC, base, reason), warnings=(reason,))
        index = raw_index
        point = points[index]
        values = {
            "angle": _value(point, "V"),
            "curvature": _value(point, "kappa", "curvature"),
            "axial": (
                _value(point, "axial")
                if isinstance(point, Mapping)
                else -float(_value(point, "axial"))
                if _value(point, "axial") is not None
                else None
            ),
            "compression": _value(point, "comp_force", "compression_force"),
            "lever": _value(point, "lever", "lever_arm"),
        }
        try:
            values = {key: _number(value) for key, value in values.items()}
            mx_value, my_value = _number(mx[index]), _number(my[index])
            point_mx, point_my = _number(_value(point, "Mx")), _number(_value(point, "My"))
            if not math.isclose(mx_value, point_mx) or not math.isclose(my_value, point_my):
                reason = "retained envelope and selected plastic point disagree"
            if not bool(_value(point, "converged") if _value(point, "converged") is not None else result.get("converged")):
                reason = "plastic section equilibrium did not converge"
        except (TypeError, ValueError):
            reason = "selected plastic point omits a finite solver intermediate"
    if reason:
        final = _failed_final(calc, PLASTIC, base, reason)
        return calc.finish(final, warnings=(reason,))
    angle = calc.add(
        "na-angle", "Selected neutral-axis angle", "V", "degrees",
        TraceResult(RESULT_FINITE, values["angle"]), source=PLASTIC, dependencies=base,
    )
    curvature = calc.add(
        "curvature", "Governing ultimate curvature", "kappa", "1/m",
        TraceResult(RESULT_FINITE, values["curvature"]), source=PLASTIC,
        dependencies=(angle, *base),
    )
    axial = calc.add(
        "axial-resultant", "Integrated axial resistance", "NRd", "kN",
        TraceResult(RESULT_FINITE, values["axial"]), source=PLASTIC,
        dependencies=(curvature, *base),
    )
    applied = _number(inp.get("P_pl", 0.0))
    residual_value = values["axial"] - applied
    residual = calc.add(
        "axial-residual", "Axial equilibrium residual", "DeltaN", "kN",
        TraceResult(RESULT_FINITE, residual_value), source=PLASTIC,
        dependencies=(axial, "n-ed"), expression="DeltaN = NRd - NEd",
        substitution=f"DeltaN = {_fmt(values['axial'])} - {_fmt(applied)} = {_fmt(residual_value)} kN",
    )
    equilibrium = calc.add(
        "equilibrium", "Converged axial equilibrium", "Ieq", "1",
        TraceResult(RESULT_FINITE, 1.0), source=PLASTIC, dependencies=(residual,),
        assumption="A value of 1 records the solver convergence state, not a verdict.",
    )
    compression = calc.add(
        "compression-resultant", "Integrated compression resultant", "CRd", "kN",
        TraceResult(RESULT_FINITE, values["compression"]), source=PLASTIC,
        dependencies=(equilibrium, curvature),
    )
    lever = calc.add(
        "internal-lever-arm", "Internal resultant lever arm", "z", "m",
        TraceResult(RESULT_FINITE, values["lever"]), source=PLASTIC,
        dependencies=(compression,),
    )
    mx_step = calc.add(
        "mx-rd", "Integrated x-axis moment resistance", "MxRd", "kNm",
        TraceResult(RESULT_FINITE, mx_value), source=PLASTIC,
        dependencies=(equilibrium, compression, lever),
    )
    my_step = calc.add(
        "my-rd", "Integrated y-axis moment resistance", "MyRd", "kNm",
        TraceResult(RESULT_FINITE, my_value), source=PLASTIC,
        dependencies=(equilibrium, compression, lever),
    )
    final_value = math.hypot(mx_value, my_value)
    final = calc.add(
        "m-rd-resultant", "Resultant resistance at selected state", "MRd", "kNm",
        TraceResult(RESULT_FINITE, final_value), source=PLASTIC,
        dependencies=(mx_step, my_step), role=ROLE_FINAL,
        expression="MRd = sqrt(MxRd^2 + MyRd^2)",
        substitution=f"MRd = sqrt({_fmt(mx_value)}^2 + {_fmt(my_value)}^2) = {_fmt(final_value)} kNm",
    )
    return calc.finish(final)
def _radial(
    inp: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
    blocks: SectionTraceBlocks,
) -> TraceCalculation:
    cid = context_id(context)
    calc = _Calculation(
        f"plastic.{cid}.radial-utilisation",
        "ct-003",
        "Radial demand-to-envelope utilisation",
        "sector-radial-envelope-intersection",
        context_axes(context),
    )
    base = _plastic_base(calc, inp, blocks)
    mx, my = list(result.get("mx") or ()), list(result.get("my") or ())
    envelope: list[str] = []
    valid = len(mx) == len(my) and len(mx) >= 3
    for index, (x_value, y_value) in enumerate(zip(mx, my), start=1):
        x_result = _result(x_value, invalid_reason="non-finite envelope x ordinate")
        y_result = _result(y_value, invalid_reason="non-finite envelope y ordinate")
        valid = valid and x_result.state == y_result.state == RESULT_FINITE
        envelope.extend(
            (
                calc.add(f"envelope-{index:03d}-mx", f"Envelope point {index} Mx", "Mx", "kNm", x_result, source=PLASTIC, dependencies=base),
                calc.add(f"envelope-{index:03d}-my", f"Envelope point {index} My", "My", "kNm", y_result, source=PLASTIC, dependencies=base),
            )
        )
    util = result.get("util")
    final_result = TraceResult(RESULT_POSITIVE_INFINITY, None, "the applied ray misses the closed capacity envelope") if util == math.inf else _result(util, invalid_reason="radial utilisation is unavailable")
    if not valid or final_result.state == RESULT_NEGATIVE_INFINITY or (final_result.state == RESULT_FINITE and float(final_result.value) < 0.0):
        final_result = TraceResult(RESULT_FAILED, None, "radial envelope is invalid or utilisation is negative")
    reason = final_result.reason
    final = calc.add(
        "eta-m", "Radial moment utilisation", "etaM", "1", final_result,
        source=RADIAL, dependencies=(*base, *envelope), role=ROLE_FINAL,
        expression="etaM = radial demand / closed-envelope ray intersection",
        warning=reason,
        assumption="Sector geometric procedure; no normative equation is assigned.",
    )
    return calc.finish(final, warnings=(reason,) if reason else ())
def _interaction(
    inp: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
    blocks: SectionTraceBlocks,
    axis: str,
) -> TraceCalculation:
    cid = context_id(context)
    calc = _Calculation(
        f"plastic.{cid}.interaction-{axis}",
        "ct-004",
        f"N-M{axis} interaction boundary",
        blocks.plastic_method_id,
        context_axes(context, axis=axis),
    )
    base = _plastic_base(calc, inp, blocks)
    interaction = result.get("interaction")
    branch = interaction.get(axis) if isinstance(interaction, Mapping) else None
    axial = list(branch.get("N") or ()) if isinstance(branch, Mapping) else []
    moments = list(branch.get("M") or ()) if isinstance(branch, Mapping) else []
    valid = bool(axial) and len(axial) == len(moments) and bool(branch.get("converged"))
    points: list[str] = []
    moment_values: list[float] = []
    if valid:
        try:
            for index, (n_value, m_value) in enumerate(zip(axial, moments), start=1):
                n_number, m_number = _number(n_value), _number(m_value)
                moment_values.append(m_number)
                points.extend(
                    (
                        calc.add(f"boundary-{index:03d}-n", f"Boundary point {index} axial", "NRd", "kN", TraceResult(RESULT_FINITE, n_number), source=PLASTIC, dependencies=base),
                        calc.add(f"boundary-{index:03d}-m", f"Boundary point {index} moment", f"M{axis}Rd", "kNm", TraceResult(RESULT_FINITE, m_number), source=PLASTIC, dependencies=base),
                    )
                )
        except ValueError:
            valid = False
    if not valid:
        reason = f"interaction axis {axis} is missing, misaligned, non-finite, or unconverged"
        final = _failed_final(calc, PLASTIC, (*base, *points), reason)
        return calc.finish(final, warnings=(reason,))
    count = calc.add(
        "boundary-cardinality", "Boundary point count", "npoints", "1",
        TraceResult(RESULT_FINITE, float(len(moment_values))), source=PLASTIC,
        dependencies=points, expression="npoints = exact ordered boundary cardinality",
    )
    governing = max(moment_values, key=abs)
    final = calc.add(
        "governing-m-rd", f"Maximum absolute M{axis} boundary state", f"M{axis}Rd", "kNm",
        TraceResult(RESULT_FINITE, governing), source=PLASTIC,
        dependencies=(count, *points), role=ROLE_FINAL,
        expression=f"M{axis}Rd = argmax |M{axis},i|",
    )
    return calc.finish(final)
def plastic_calculations(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
) -> list[TraceCalculation]:
    result = out.get("plastic")
    if not isinstance(result, Mapping):
        return []
    blocks = section_trace_blocks(inp)
    calculations = [_capacity(inp, result, context, blocks)]
    if result.get("util") is not None:
        calculations.append(_radial(inp, result, context, blocks))
    if result.get("interaction") is not None:
        calculations.extend(
            _interaction(inp, result, context, blocks, axis) for axis in ("x", "y")
        )
    return calculations
def section_calculations(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
) -> tuple[TraceCalculation, ...]:
    return tuple(plastic_calculations(inp, out, context=context))
def _source_contract(source: TraceSource) -> TraceSourceContract:
    return TraceSourceContract(source.kind, source.method_id, source.edition)
def _contract(
    member_id: str,
    calculation: TraceCalculation,
    sources: frozenset[TraceSourceContract],
    *,
    method_id: str,
    axes: tuple,
) -> TraceMemberContract:
    final = next(step for step in calculation.steps if step.step_id == calculation.final_step_id)
    return TraceMemberContract(
        member_id,
        calculation.calculation_id,
        calculation.coverage_id,
        method_id,
        axes,
        sources,
        frozenset({final.result.state}),
        tuple(step.step_id for step in calculation.steps),
        tuple(
            (step.step_id, tuple(dependency.step_id for dependency in step.dependencies))
            for step in calculation.steps
        ),
    )
def section_trace_registry(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
) -> TraceRegistryContract:
    blocks = section_trace_blocks(inp)
    calculations = {item.calculation_id: item for item in section_calculations(inp, out, context=context)}
    cid = context_id(context)
    axes = context_axes(context)
    material_sources = {_source_contract(item.provenance.source) for item in (blocks.concrete, *blocks.bars, *blocks.tendons)}
    plastic_sources = {
        _source_contract(INPUT),
        _source_contract(GEOMETRY),
        _source_contract(PLASTIC),
        *material_sources,
    }
    if blocks.bars or blocks.tendons:
        plastic_sources.add(_source_contract(ASSIGNMENT))
    families = []
    plastic = out.get("plastic")
    if isinstance(plastic, Mapping):
        capacity_id = f"plastic.{cid}.capacity"
        families.append(
            TraceFamilyContract(
                "plastic-capacity",
                (_contract("plastic-capacity", calculations[capacity_id], frozenset(plastic_sources), method_id=blocks.plastic_method_id, axes=axes),),
            )
        )
        if plastic.get("util") is not None:
            radial_id = f"plastic.{cid}.radial-utilisation"
            families.append(
                TraceFamilyContract(
                    "plastic-radial",
                    (_contract(
                        "plastic-radial",
                        calculations[radial_id],
                        frozenset({*plastic_sources, _source_contract(RADIAL)}),
                        method_id="sector-radial-envelope-intersection",
                        axes=axes,
                    ),),
                )
            )
        if plastic.get("interaction") is not None:
            families.append(
                TraceFamilyContract(
                    "plastic-interaction",
                    tuple(
                        _contract(
                            f"plastic-interaction-{axis}",
                            calculations[f"plastic.{cid}.interaction-{axis}"],
                            frozenset(plastic_sources),
                            method_id=blocks.plastic_method_id,
                            axes=context_axes(context, axis=axis),
                        )
                        for axis in ("x", "y")
                    ),
                )
            )
    return TraceRegistryContract(f"section-{cid}", tuple(families))
def create_section_trace_bundle(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    input_sha256: str,
    result_sha256: str,
):
    calculations = section_calculations(inp, out, context=context)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=calculations,
    )
    return audit_trace_registry(
        bundle,
        section_trace_registry(inp, out, context=context),
    )
