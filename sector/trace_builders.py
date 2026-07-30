"""Solver-adjacent PI-019 calculation-trace builders.

The numerical kernels remain authoritative.  These builders receive the exact
kernel inputs and returned intermediates, then assemble a dependency-ordered,
machine-checkable derivation.  Presentation code consumes the resulting model
and never evaluates an engineering expression.
"""

from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from . import codes
from .calculation_trace import (
    PROVENANCE_INPUT,
    PROVENANCE_PROJECT,
    PROVENANCE_STANDARD,
    ROLE_COMPUTED,
    ROLE_FINAL,
    ROLE_METHOD_VALUE,
    ROLE_USER_INPUT,
    SourceCitation,
    TraceCalculation,
    TraceEvaluation,
    TraceStep,
    trace_identity_token,
)


DOC_2005 = "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010"
DOC_DKNA = "DS/EN 1992-1-1 DK NA:2024"
DOC_2023 = "DS/EN 1992-1-1:2023"
DOC_BRIDGE = "DS/EN 1992-2:2005"
DOC_BRIDGE_AC = "DS/EN 1992-2 AC:2008"


def citation(document: str, clause: str, locator: str) -> SourceCitation:
    return SourceCitation(document=document, clause=clause, locator=locator)


CIT_FCD_2005 = citation(DOC_2005, "3.1.6(1)", "Formula (3.15)")
CIT_FCD_2023 = citation(DOC_2023, "5.1.6", "Formulae (5.4)-(5.5)")
CIT_FYD_2005 = citation(DOC_2005, "3.2.7", "Formula (3.8)")
CIT_FYD_2023 = citation(DOC_2023, "5.2.4", "design yield relation")
CIT_TENDON_PROOF_2005 = citation(
    DOC_2005,
    "3.3.6(6)",
    "f_pd = f_p0.1k / gamma_S; Figure 3.10",
)
CIT_TENDON_RUPTURE_2005 = citation(
    DOC_2005,
    "3.3.6(7)",
    "inclined design branch; Figure 3.10",
)
CIT_TENDON_MODULUS_2005 = citation(
    DOC_2005,
    "3.3.6(2)-(3)",
    "design modulus assumptions",
)
CIT_TENDON_PROOF_2023 = citation(
    DOC_2023,
    "5.3.3(1)",
    "Formula (5.12)",
)
CIT_TENDON_RUPTURE_2023 = citation(
    DOC_2023,
    "5.3.3(2)(a)",
    "inclined design branch; Figure 5.3",
)
CIT_TENDON_MODULUS_2023 = citation(
    DOC_2023,
    "5.3.3(3)",
    "design modulus assumptions",
)
CIT_FCTK_005_2005 = citation(
    DOC_2005, "Table 3.1", "fctk,0.05 = 0.7 fctm"
)
CIT_FCTD_2005 = citation(DOC_2005, "3.1.6(2)", "Formula (3.16)")
CIT_PLASTIC_2005 = citation(DOC_2005, "6.1", "section equilibrium")
CIT_PLASTIC_2023 = citation(DOC_2023, "8.1.2", "section equilibrium")
CIT_CRACK_2005_STRAIN = citation(DOC_2005, "7.3.4(2)", "Formula (7.9)")
CIT_CRACK_2005_SPACING = citation(DOC_2005, "7.3.4(3)", "Formula (7.11)")
CIT_CRACK_2005_GEOMETRIC = citation(DOC_2005, "7.3.4(4)", "Formula (7.14)")
CIT_CRACK_2005_FINAL = citation(DOC_2005, "7.3.4(1)", "Formula (7.8)")
CIT_CRACK_DK_SPACING = citation(DOC_DKNA, "7.3.4(3)", "k3 expression")
CIT_CRACK_DK_COARSE = citation(
    DOC_DKNA, "7.3.4(1)", "coarse crack system and Figure 7.100 NA"
)
CIT_CRACK_2023_STRAIN = citation(DOC_2023, "9.2.3", "Formula (9.11)")
CIT_CRACK_2023_RHO = citation(DOC_2023, "9.2.3", "Formula (9.12)")
CIT_CRACK_2023_SPACING = citation(
    DOC_2023, "9.2.3", "Formulae (9.15)-(9.18)"
)
CIT_CRACK_2023_FINAL = citation(DOC_2023, "9.2.3", "Formulae (9.8)-(9.9)")
CIT_SHEAR_2005 = citation(DOC_2005, "6.2.2(1)", "Formulae (6.2a)-(6.3)")
CIT_SHEAR_DK_VMIN = citation(DOC_DKNA, "6.2.2(1)", "vmin expression")
CIT_SHEAR_2023 = citation(
    DOC_2023, "8.2.1-8.2.2", "Formulae (8.18), (8.20), (8.27), (8.29)-(8.31)"
)
CIT_LINKS_2005 = citation(DOC_2005, "6.2.3", "Formulae (6.8)-(6.9)")
CIT_LINKS_DK = citation(
    DOC_DKNA, "6.2.3(2)-(3)", "national compression-field parameters"
)
CIT_LINKS_2023 = citation(DOC_2023, "8.2.3", "Formulae (8.42), (8.44)")
CIT_TORSION = citation(DOC_2005, "6.3.2", "Formulae (6.26)-(6.31)")
CIT_TORSION_DK = citation(DOC_DKNA, "6.3.2(6)", "modified interaction")
CIT_COMBINED_629 = citation(DOC_2005, "6.3.2(4)", "Formula (6.29)")
CIT_CHORD_2005 = citation(DOC_2005, "6.2.3(7)", "Formula (6.18)")
CIT_CHORD_2023 = citation(
    DOC_2023, "8.2.3(8)", "Formulae (8.50)-(8.52)"
)
CIT_DK_SUM = citation(DOC_DKNA, "6.3.2(6)", "sum(SEd/SRd)")
CIT_MIN_LONG_2005 = citation(DOC_2005, "9.2.1.1(1)", "Formula (9.1N)")
CIT_MIN_LONG_DK = citation(DOC_DKNA, "9.2.1.1(1)", "national value")
CIT_MIN_LONG_2023 = citation(DOC_2023, "12.2(2)", "Formulae (12.1)-(12.2)")
CIT_TRANSVERSE_2005 = citation(
    DOC_2005, "9.2.2(5)-(8)", "Formulae (9.4)-(9.8)"
)
CIT_TRANSVERSE_2023 = citation(
    DOC_2023, "12.2(4)", "Formula (12.4) and Table 12.1"
)
CIT_CLEAR_2005 = citation(DOC_2005, "8.2(2)", "minimum clear spacing")
CIT_CLEAR_2023 = citation(DOC_2023, "11.2(2)", "minimum clear spacing")
CIT_FATIGUE_STEEL_2005 = citation(
    DOC_2005, "6.8.4", "Tables 6.3N/6.4N"
)
CIT_FATIGUE_STEEL_2023 = citation(DOC_2023, "E.5", "Tables E.1/E.2")
CIT_FATIGUE_CONC_EQ_2005 = citation(DOC_2005, "6.8.7", "Formula (6.72)")
CIT_FATIGUE_CONC_EQ_2023 = citation(DOC_2023, "E.4.3", "Formula (E.2)")
CIT_FATIGUE_CONC_STRENGTH_2005 = citation(
    DOC_2005, "6.8.7", "Formula (6.76)"
)
CIT_FATIGUE_CONC_STRENGTH_2023 = citation(
    DOC_2023, "10.5", "Formula (10.5)"
)
CIT_FATIGUE_CONC_MINER_2005 = citation(
    DOC_BRIDGE, "6.8.7(101)", "Formula (6.105) and Formulae (6.107)-(6.109)"
)
CIT_FATIGUE_CONC_MINER_AC = citation(
    DOC_BRIDGE_AC, "6.8.7(101)", "corrected Formula (6.106)"
)
CIT_FATIGUE_CONC_MINER_SUM_2023 = citation(
    DOC_2023, "E.5.1", "Formula (E.3)"
)
CIT_FATIGUE_CONC_MINER_2023 = citation(
    DOC_2023, "E.5.3", "Formulae (E.7)-(E.8)"
)
CIT_BRIDGE_METHOD_B = citation(
    DOC_BRIDGE, "6.1(109)-(110)", "Formula (6.101a)"
)
CIT_BRIDGE_BOX = citation(
    DOC_BRIDGE, "6.3.2(101)-(104)", "Formulae (6.29)-(6.30)"
)
CIT_BRIDGE_CRACK = citation(DOC_BRIDGE, "7.3.2(102)-(105)", "Formula (7.1)")


def _slug(value: Any, fallback: str = "item") -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text or fallback


def _identified_slug(value: Any) -> str:
    """Keep a readable slug while making the exact label namespace injective."""

    return f"{_slug(value)}-{trace_identity_token(value)}"


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a non-Boolean finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _fmt(value: float) -> str:
    number = float(value)
    if number == 0.0:
        return "0"
    magnitude = abs(number)
    if magnitude >= 1.0e5 or magnitude < 1.0e-4:
        return f"{number:.6e}"
    return f"{number:.8g}"


def _math_text(value: Any) -> str:
    """Return plain engineering notation suitable for every renderer."""

    return str(value).replace("sqrt", "\N{SQUARE ROOT}")


def _value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _plastic_point_value(
    point: Any,
    retained_key: str,
    kernel_key: str,
    default: Any = None,
) -> Any:
    """Read a plastic state without confusing retained and kernel field names."""

    if isinstance(point, Mapping):
        if retained_key in point:
            return point[retained_key]
        return point.get(kernel_key, default)
    return getattr(point, kernel_key, default)


def _plastic_point_axial(point: Any, default: Any) -> Any:
    """Return the public tension-positive axial resultant of a plastic state."""

    if isinstance(point, Mapping):
        return point.get("axial", default)
    value = getattr(point, "axial", None)
    return default if value is None else -float(value)


class _Calc:
    """Small deterministic DSL for one dependency-ordered calculation."""

    def __init__(
        self,
        *,
        calculation_id: str,
        coverage_id: str,
        title: str,
        method_id: str,
        method_label: str,
        standard_based: bool,
        user_defined_method: bool = False,
        context: Mapping[str, Any] | None = None,
        warnings: Sequence[str] = (),
        assumptions: Sequence[str] = (),
    ) -> None:
        self.calculation_id = _slug(calculation_id)
        self.coverage_id = coverage_id
        self.title = title
        self.method_id = _slug(method_id)
        self.method_label = method_label
        self.standard_based = bool(standard_based)
        self.user_defined_method = bool(user_defined_method)
        self.context = tuple(
            (str(key), str(value))
            for key, value in sorted((context or {}).items())
            if str(key) != "_case_identity"
        )
        self.warnings = tuple(str(item) for item in warnings if str(item))
        self.assumptions = tuple(str(item) for item in assumptions if str(item))
        self.steps: list[TraceStep] = []
        self._ids: set[str] = set()

    def step(
        self,
        step_id: str,
        *,
        title: str,
        role: str,
        provenance: str,
        symbol: str,
        unit: str,
        value: Any,
        symbolic: str,
        substituted: str | None = None,
        dependencies: Sequence[str] = (),
        operator: str,
        source: SourceCitation | None = None,
        factor: float = 1.0,
        offset: float = 0.0,
        exponent: float | None = None,
        warnings: Sequence[str] = (),
        assumptions: Sequence[str] = (),
        relative_tolerance: float = 1.0e-8,
        absolute_tolerance: float = 1.0e-8,
    ) -> str:
        sid = _slug(step_id)
        if sid in self._ids:
            raise ValueError(f"{self.calculation_id}: duplicate step {sid}")
        self._ids.add(sid)
        number = _number(value, f"{self.calculation_id}.{sid}")
        deps = tuple(_slug(item) for item in dependencies)
        symbol_text = _math_text(symbol)
        symbolic_text = _math_text(symbolic)
        self.steps.append(
            TraceStep(
                step_id=sid,
                title=title,
                dependency_ids=deps,
                quantity_role=role,
                provenance=provenance,
                symbol=symbol_text,
                unit=unit,
                source_citation=source,
                symbolic_expression=symbolic_text,
                substituted_expression=(
                    _math_text(substituted)
                    if substituted is not None
                    else f"{symbol_text} = {_fmt(number)} {unit}"
                ),
                evaluated_value=number,
                evaluation=TraceEvaluation(
                    operator=operator,
                    operand_ids=deps,
                    result_unit=unit,
                    factor=factor,
                    offset=offset,
                    exponent=exponent,
                    relative_tolerance=relative_tolerance,
                    absolute_tolerance=absolute_tolerance,
                ),
                warnings=tuple(str(item) for item in warnings if str(item)),
                assumptions=tuple(
                    str(item) for item in assumptions if str(item)
                ),
            )
        )
        return sid

    def input(
        self,
        step_id: str,
        title: str,
        symbol: str,
        unit: str,
        value: Any,
        *,
        warning: str = "",
        assumption: str = "",
    ) -> str:
        number = _number(value, step_id)
        return self.step(
            step_id,
            title=title,
            role=ROLE_USER_INPUT,
            provenance=PROVENANCE_INPUT,
            symbol=symbol,
            unit=unit,
            value=number,
            symbolic=f"{symbol} = user input",
            substituted=f"{symbol} = {_fmt(number)} {unit}",
            operator="input",
            warnings=(warning,),
            assumptions=(assumption,),
        )

    def method(
        self,
        step_id: str,
        title: str,
        symbol: str,
        unit: str,
        value: Any,
        source: SourceCitation,
    ) -> str:
        number = _number(value, step_id)
        return self.step(
            step_id,
            title=title,
            role=ROLE_METHOD_VALUE,
            provenance=PROVENANCE_STANDARD,
            symbol=symbol,
            unit=unit,
            value=number,
            symbolic=f"{symbol} = selected method value",
            substituted=f"{symbol} = {_fmt(number)} {unit}",
            operator="method",
            source=source,
        )

    def project_value(
        self,
        step_id: str,
        title: str,
        symbol: str,
        unit: str,
        value: Any,
        *,
        dependencies: Sequence[str] = (),
        role: str = ROLE_COMPUTED,
        assumption: str = "",
    ) -> str:
        number = _number(value, step_id)
        return self.step(
            step_id,
            title=title,
            role=role,
            provenance=PROVENANCE_PROJECT,
            symbol=symbol,
            unit=unit,
            value=number,
            symbolic=f"{symbol} = Sector numerical procedure",
            substituted=f"{symbol} = {_fmt(number)} {unit}",
            dependencies=dependencies,
            operator="solver",
            assumptions=(assumption,),
        )

    def computed(
        self,
        step_id: str,
        *,
        title: str,
        symbol: str,
        unit: str,
        value: Any,
        symbolic: str,
        substituted: str,
        dependencies: Sequence[str],
        operator: str,
        source: SourceCitation | None,
        provenance: str | None = None,
        role: str = ROLE_COMPUTED,
        factor: float = 1.0,
        offset: float = 0.0,
        exponent: float | None = None,
        warning: str = "",
        assumption: str = "",
    ) -> str:
        return self.step(
            step_id,
            title=title,
            role=role,
            provenance=(
                provenance
                if provenance is not None
                else (
                    PROVENANCE_STANDARD
                    if source is not None
                    else PROVENANCE_PROJECT
                )
            ),
            symbol=symbol,
            unit=unit,
            value=value,
            symbolic=symbolic,
            substituted=substituted,
            dependencies=dependencies,
            operator=operator,
            source=source,
            factor=factor,
            offset=offset,
            exponent=exponent,
            warnings=(warning,),
            assumptions=(assumption,),
        )

    def finish(self, final_step_id: str) -> TraceCalculation:
        return TraceCalculation(
            calculation_id=self.calculation_id,
            coverage_id=self.coverage_id,
            title=self.title,
            method_id=self.method_id,
            method_label=self.method_label,
            standard_based=self.standard_based,
            user_defined_method=self.user_defined_method,
            final_step_id=_slug(final_step_id),
            steps=tuple(self.steps),
            context=self.context,
            warnings=self.warnings,
            assumptions=self.assumptions,
        )


def _demand_resistance_final(
    calc: _Calc,
    *,
    ratio_value: Any,
    demand_step: str,
    resistance_step: str,
    demand_value: Any,
    resistance_value: Any,
    ratio_step_id: str,
    ratio_title: str,
    ratio_symbol: str,
    ratio_symbolic: str,
    ratio_substituted: str,
    source: SourceCitation,
    quantity_unit: str = "kN",
) -> str:
    """Trace a finite utilisation or a finite margin for unbounded demand ratio.

    Solver result payloads deliberately use infinity when a positive demand is
    divided by zero or an explicitly tolerance-zero provision. Trace steps stay
    strictly finite so seals, arithmetic reconstruction and JSON consumers
    cannot silently accept non-finite values. The exceptional branch therefore
    publishes the same demand and resistance leaves followed by their finite
    project-defined margin; the solver-owned infinite utilisation remains in
    the result payload and is stated explicitly as a warning.
    """

    ratio = float(ratio_value)
    if math.isfinite(ratio):
        return calc.computed(
            ratio_step_id,
            title=ratio_title,
            symbol=ratio_symbol,
            unit="1",
            value=ratio,
            symbolic=ratio_symbolic,
            substituted=ratio_substituted,
            dependencies=(demand_step, resistance_step),
            operator="divide",
            source=source,
            role=ROLE_FINAL,
        )

    demand = _number(demand_value, f"{calc.calculation_id}.demand")
    resistance = _number(
        resistance_value, f"{calc.calculation_id}.resistance"
    )
    if not (
        math.isinf(ratio)
        and ratio > 0.0
        and 0.0 <= resistance < demand
        and demand > 0.0
    ):
        raise ValueError(
            f"{calc.calculation_id}: unexpected non-finite utilisation"
        )
    margin = resistance - demand
    if resistance == 0.0:
        reason = "the finite resistance is zero"
    else:
        reason = (
            "the solver classifies the finite provision as effectively zero "
            "for this check"
        )
    warning = (
        f"{ratio_symbol} is infinite because {reason} while demand is "
        "positive. The solver result retains that infinite utilisation; the "
        "trace publishes the finite resistance-minus-demand comparison "
        "instead."
    )
    return calc.computed(
        f"{ratio_step_id}-resistance-margin",
        title="Finite resistance-minus-demand margin",
        symbol="Delta_Rd-Ed",
        unit=quantity_unit,
        value=margin,
        symbolic="Delta_Rd-Ed = R_Rd - E_d",
        substituted=(
            f"Delta_Rd-Ed = {_fmt(resistance)} - {_fmt(demand)} "
            f"= {_fmt(margin)} {quantity_unit}"
        ),
        dependencies=(resistance_step, demand_step),
        operator="subtract",
        source=None,
        provenance=PROVENANCE_PROJECT,
        role=ROLE_FINAL,
        warning=warning,
        assumption=(
            "A negative margin is the finite representation of the genuine "
            "demand-versus-resistance failure."
        ),
    )


def _code_from_preset(raw_value: Any) -> codes.DesignCode | None:
    """Return the code edition named by one actual material preset."""

    raw = str(raw_value or "")
    if raw in codes.CODES:
        return codes.CODES[raw]
    for item in codes.CODES.values():
        if raw in {item.key, item.label}:
            return item
    return None


def _preset_code(inp: Mapping) -> codes.DesignCode | None:
    return _code_from_preset(inp.get("concrete_preset"))


def _catalog_items(inp: Mapping, key: str) -> tuple[Mapping, ...]:
    """Return primitive material-catalogue entries without normalising values."""

    raw = inp.get(key)
    items = raw.get("items") if isinstance(raw, Mapping) else raw
    if (
        not isinstance(items, Sequence)
        or isinstance(items, (str, bytes, bytearray))
    ):
        return ()
    return tuple(item for item in items if isinstance(item, Mapping))


def _catalog_preset(
    inp: Mapping,
    *,
    key: str,
    material_id: Any,
) -> str:
    selected = str(material_id or "").strip()
    if selected:
        for item in _catalog_items(inp, key):
            if str(item.get("id") or "").strip() == selected:
                return str(item.get("preset") or "")
    return ""


def _capacity_steel_preset(inp: Mapping) -> str:
    """Return the preset belonging to the steel law actually passed as ``steel``."""

    return _catalog_preset(
        inp,
        key="mild_material_catalog",
        material_id=inp.get("capacity_steel_material_id"),
    ) or str(inp.get("mild_preset") or "")


def _assigned_material_preset(
    inp: Mapping,
    *,
    kind: str,
    index: int,
) -> str:
    """Return the preset attached to one solver-aligned bar or tendon law."""

    if kind == "bar":
        element_key = "bar_elements"
        catalog_key = "mild_material_catalog"
        fallback_key = "mild_preset"
    elif kind == "tendon":
        element_key = "tendon_elements"
        catalog_key = "prestress_material_catalog"
        fallback_key = "prestress_preset"
    else:  # pragma: no cover - private caller contract
        raise ValueError(f"unknown material kind {kind!r}")

    elements = inp.get(element_key)
    if (
        isinstance(elements, Sequence)
        and not isinstance(elements, (str, bytes, bytearray))
        and 0 <= index < len(elements)
        and isinstance(elements[index], Mapping)
    ):
        preset = _catalog_preset(
            inp,
            key=catalog_key,
            material_id=elements[index].get("material_id"),
        )
        if preset:
            return preset
    return str(inp.get(fallback_key) or "")


def _standard_document(inp: Mapping) -> str:
    code = _preset_code(inp)
    if code is not None and code.key == "EC2-2023":
        return DOC_2023
    if code is not None and "DKNA" in code.key:
        return DOC_DKNA
    return DOC_2005


def _context_id(context: Mapping[str, Any] | None) -> str:
    if not context:
        return "global"
    family = _slug(context.get("family"), "case")
    case = _slug(context.get("case_id"), "direct")
    identity = _slug(context.get("_case_identity"), "")
    face = _slug(context.get("face"), "")
    component = _slug(context.get("component"), "")
    return ".".join(
        item for item in (family, case, identity, component, face) if item
    )


def material_calculations(
    inp: Mapping,
    *,
    context: Mapping[str, Any] | None = None,
) -> list[TraceCalculation]:
    """Trace the active concrete and capacity-steel design strengths."""

    concrete = inp.get("concrete")
    steel = inp.get("steel")
    if concrete is None or steel is None:
        return []
    code = _preset_code(inp)
    is_2023 = bool(code is not None and code.key == "EC2-2023")
    standard_based = code is not None
    custom = not standard_based
    cid = _context_id(context)
    source_fcd = CIT_FCD_2023 if is_2023 else CIT_FCD_2005

    warnings: list[str] = []
    if code is not None:
        if not math.isclose(
            float(concrete.gamma_c), float(code.gamma_c), rel_tol=0.0, abs_tol=1e-12
        ):
            warnings.append(
                "User-entered gamma_c differs from the selected preset; the "
                "entered positive finite value is retained."
            )
    c = _Calc(
        calculation_id=f"material.{cid}.concrete",
        coverage_id="CT-001",
        title="Concrete design compression strength",
        method_id=(code.key if code is not None else "user-defined-concrete"),
        method_label=(
            code.label if code is not None else "User-defined concrete law"
        ),
        standard_based=standard_based,
        user_defined_method=custom,
        context=context,
        warnings=warnings,
    )
    fck = c.input("fck", "Characteristic cylinder strength", "fck", "MPa", concrete.fck)
    gamma_c = c.input(
        "gamma-c",
        "Final concrete partial factor",
        "gamma_c",
        "1",
        concrete.gamma_c,
        warning=warnings[0] if warnings else "",
    )
    alpha = c.input(
        "strength-factor",
        (
            "Final eta_cc times k_tc"
            if is_2023
            else "Final concrete strength coefficient"
        ),
        "alpha_eff",
        "1",
        concrete.alpha_cc,
    )
    numerator_value = float(concrete.alpha_cc) * float(concrete.fck)
    numerator = c.computed(
        "fcd-numerator",
        title="Factored characteristic strength",
        symbol="alpha_eff fck",
        unit="MPa",
        value=numerator_value,
        symbolic="alpha_eff fck",
        substituted=(
            f"{_fmt(concrete.alpha_cc)} x {_fmt(concrete.fck)} "
            f"= {_fmt(numerator_value)} MPa"
        ),
        dependencies=(alpha, fck),
        operator="multiply",
        source=(source_fcd if standard_based else None),
        provenance=(
            PROVENANCE_STANDARD if standard_based else PROVENANCE_PROJECT
        ),
    )
    fcd = c.computed(
        "fcd",
        title="Concrete design compression strength",
        symbol="fcd",
        unit="MPa",
        value=concrete.fcd,
        symbolic="fcd = alpha_eff fck / gamma_c",
        substituted=(
            f"fcd = {_fmt(numerator_value)} / {_fmt(concrete.gamma_c)} "
            f"= {_fmt(concrete.fcd)} MPa"
        ),
        dependencies=(numerator, gamma_c),
        operator="divide",
        source=(source_fcd if standard_based else None),
        provenance=(
            PROVENANCE_STANDARD if standard_based else PROVENANCE_PROJECT
        ),
        role=ROLE_FINAL,
    )

    steel_code = _code_from_preset(_capacity_steel_preset(inp))
    steel_standard = steel_code is not None
    steel_is_2023 = bool(
        steel_code is not None and steel_code.key == "EC2-2023"
    )
    swarnings: list[str] = []
    if steel_code is not None and not math.isclose(
        float(steel.gamma_y),
        float(steel_code.gamma_s),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        swarnings.append(
            "User-entered gamma_s differs from the selected preset; the entered "
            "positive finite value is retained."
        )
    s = _Calc(
        calculation_id=f"material.{cid}.steel",
        coverage_id="CT-001",
        title="Reinforcement design yield strength",
        method_id=(
            steel_code.key
            if steel_code is not None
            else "user-defined-reinforcement"
        ),
        method_label=(
            steel_code.label
            if steel_code is not None
            else "User-defined reinforcement law"
        ),
        standard_based=steel_standard,
        user_defined_method=not steel_standard,
        context=context,
        warnings=swarnings,
    )
    fyk = s.input("fyk", "Characteristic yield strength", "fyk", "MPa", steel.fytk)
    gamma_s = s.input(
        "gamma-s",
        "Final reinforcement partial factor",
        "gamma_s",
        "1",
        steel.gamma_y,
        warning=swarnings[0] if swarnings else "",
    )
    fyd_value = float(steel.fytk) / float(steel.gamma_y)
    fyd = s.computed(
        "fyd",
        title="Reinforcement design yield strength",
        symbol="fyd",
        unit="MPa",
        value=fyd_value,
        symbolic="fyd = fyk / gamma_s",
        substituted=(
            f"fyd = {_fmt(steel.fytk)} / {_fmt(steel.gamma_y)} "
            f"= {_fmt(fyd_value)} MPa"
        ),
        dependencies=(fyk, gamma_s),
        operator="divide",
        source=(
            (CIT_FYD_2023 if steel_is_2023 else CIT_FYD_2005)
            if steel_standard
            else None
        ),
        provenance=(
            PROVENANCE_STANDARD if steel_standard else PROVENANCE_PROJECT
        ),
        role=ROLE_FINAL,
    )
    return [c.finish(fcd), s.finish(fyd)]


def _material_sequence(inp: Mapping, key: str, fallback: Any) -> tuple[Any, ...]:
    """Mirror the solver's explicit-material versus scalar-fallback contract."""

    if key in inp:
        raw = inp.get(key)
        if raw is None:
            return ()
        if (
            isinstance(raw, Sequence)
            and not isinstance(raw, (str, bytes, bytearray))
        ):
            return tuple(raw)
        raise ValueError(f"{key} must be a material sequence")
    return () if fallback is None else (fallback,)


def _material_law_key(
    material: Any,
    *,
    preset: str,
    material_id: str,
) -> tuple[Any, ...]:
    """Return a deterministic key for one distinct solver constitutive law."""

    if dataclasses.is_dataclass(material):
        values = (
            type(material).__name__,
            tuple(
                (field.name, getattr(material, field.name))
                for field in dataclasses.fields(material)
            ),
        )
    else:
        values = (type(material).__name__, repr(material))
    return (
        "catalog" if material_id else "value",
        material_id,
        preset,
        *values,
    )


def _trace_concrete_capacity_law(
    calc: _Calc,
    concrete: Any,
    *,
    fcd_step: str,
) -> str:
    """Expose every concrete-law parameter consumed by the plastic solver."""

    curve = calc.input(
        "concrete-curve",
        "Selected concrete stress-strain curve",
        "curve_c",
        "1",
        _value(concrete, "curve"),
    )
    eps_c2 = calc.input(
        "eps-c2",
        "Concrete peak compression strain",
        "eps_c2",
        "1",
        _value(concrete, "eps_c2"),
    )
    eps_cu2 = calc.input(
        "eps-cu2",
        "Concrete ultimate compression strain",
        "eps_cu2",
        "1",
        _value(concrete, "eps_cu2"),
    )
    exponent = calc.input(
        "concrete-exponent",
        "Concrete ascending-branch exponent",
        "n_c",
        "1",
        _value(concrete, "n"),
    )
    return calc.project_value(
        "concrete-law",
        "Concrete constitutive law passed to section equilibrium",
        "law_c",
        "1",
        1.0,
        dependencies=(fcd_step, curve, eps_c2, eps_cu2, exponent),
        assumption=(
            "A value of 1 records the exact concrete-law parameter set consumed "
            "by the solver; it is not an approval or conformity verdict."
        ),
    )


def _trace_mild_capacity_law(
    calc: _Calc,
    material: Any,
    *,
    index: int,
    preset: str,
    element_id: str,
) -> str:
    """Expose one element-aligned reinforcement constitutive law."""

    prefix = f"bar-{index + 1:03d}"
    suffix = f" for {element_id}" if element_id else ""
    code = _code_from_preset(preset)
    source = (
        CIT_FYD_2023
        if code is not None and code.key == "EC2-2023"
        else CIT_FYD_2005
        if code is not None
        else None
    )
    curve = calc.input(
        f"{prefix}-curve",
        f"Selected reinforcement curve{suffix}",
        f"curve_s,{index + 1}",
        "1",
        _value(material, "curve"),
    )
    fytk = calc.input(
        f"{prefix}-fytk",
        f"Characteristic tensile yield strength{suffix}",
        f"fytk,{index + 1}",
        "MPa",
        _value(material, "fytk"),
    )
    fyck = calc.input(
        f"{prefix}-fyck",
        f"Characteristic compression yield strength{suffix}",
        f"fyck,{index + 1}",
        "MPa",
        _value(material, "fyck"),
    )
    futk = calc.input(
        f"{prefix}-futk",
        f"Characteristic rupture strength{suffix}",
        f"futk,{index + 1}",
        "MPa",
        _value(material, "futk"),
    )
    gamma_y = calc.input(
        f"{prefix}-gamma-y",
        f"Final reinforcement yield factor{suffix}",
        f"gamma_y,{index + 1}",
        "1",
        _value(material, "gamma_y"),
    )
    gamma_u = calc.input(
        f"{prefix}-gamma-u",
        f"Final reinforcement rupture factor{suffix}",
        f"gamma_u,{index + 1}",
        "1",
        _value(material, "gamma_u"),
    )
    gamma_e = calc.input(
        f"{prefix}-gamma-e",
        f"Final reinforcement modulus factor{suffix}",
        f"gamma_E,{index + 1}",
        "1",
        _value(material, "gamma_E"),
    )
    es = calc.input(
        f"{prefix}-es",
        f"Reinforcement elastic modulus{suffix}",
        f"Es,{index + 1}",
        "MPa",
        _value(material, "Es"),
    )
    eut = calc.input(
        f"{prefix}-eut",
        f"Reinforcement rupture strain{suffix}",
        f"eut,{index + 1}",
        "1",
        _value(material, "eut"),
    )
    k = calc.input(
        f"{prefix}-k",
        f"First-to-second yield ratio{suffix}",
        f"k_s,{index + 1}",
        "1",
        _value(material, "k"),
    )
    ey0t = calc.input(
        f"{prefix}-ey0t",
        f"Second tensile-yield plastic strain{suffix}",
        f"ey0t,{index + 1}",
        "1",
        _value(material, "ey0t"),
    )
    ey0c = calc.input(
        f"{prefix}-ey0c",
        f"Second compression-yield plastic strain{suffix}",
        f"ey0c,{index + 1}",
        "1",
        _value(material, "ey0c"),
    )
    active = calc.input(
        f"{prefix}-compression-active",
        f"Compression branch active state{suffix}",
        f"I_comp,{index + 1}",
        "1",
        1.0 if bool(_value(material, "active_in_compression", True)) else 0.0,
        assumption="1 means active and 0 means tension-only.",
    )
    fyd_value = float(_value(material, "fytk")) / float(
        _value(material, "gamma_y")
    )
    fyd = calc.computed(
        f"{prefix}-fyd",
        title=f"Design tensile yield strength{suffix}",
        symbol=f"fyd,{index + 1}",
        unit="MPa",
        value=fyd_value,
        symbolic=f"fyd,{index + 1} = fytk,{index + 1}/gamma_y,{index + 1}",
        substituted=(
            f"fyd,{index + 1} = {_fmt(_value(material, 'fytk'))}/"
            f"{_fmt(_value(material, 'gamma_y'))} = {_fmt(fyd_value)} MPa"
        ),
        dependencies=(fytk, gamma_y),
        operator="divide",
        source=source,
        provenance=(
            PROVENANCE_STANDARD if source is not None else PROVENANCE_PROJECT
        ),
    )
    fycd_value = float(_value(material, "fyck")) / float(
        _value(material, "gamma_y")
    )
    fycd = calc.computed(
        f"{prefix}-fycd",
        title=f"Design compression yield strength{suffix}",
        symbol=f"fycd,{index + 1}",
        unit="MPa",
        value=fycd_value,
        symbolic=f"fycd,{index + 1} = fyck,{index + 1}/gamma_y,{index + 1}",
        substituted=(
            f"fycd,{index + 1} = {_fmt(_value(material, 'fyck'))}/"
            f"{_fmt(_value(material, 'gamma_y'))} = {_fmt(fycd_value)} MPa"
        ),
        dependencies=(fyck, gamma_y),
        operator="divide",
        source=None,
        provenance=PROVENANCE_PROJECT,
    )
    fud_value = float(_value(material, "futk")) / float(
        _value(material, "gamma_u")
    )
    fud = calc.computed(
        f"{prefix}-fud",
        title=f"Design rupture strength{suffix}",
        symbol=f"fud,{index + 1}",
        unit="MPa",
        value=fud_value,
        symbolic=f"fud,{index + 1} = futk,{index + 1}/gamma_u,{index + 1}",
        substituted=(
            f"fud,{index + 1} = {_fmt(_value(material, 'futk'))}/"
            f"{_fmt(_value(material, 'gamma_u'))} = {_fmt(fud_value)} MPa"
        ),
        dependencies=(futk, gamma_u),
        operator="divide",
        source=None,
        provenance=PROVENANCE_PROJECT,
    )
    slope_factor_value = (
        float(_value(material, "gamma_y"))
        if int(_value(material, "curve")) == 2
        else float(_value(material, "gamma_E"))
    )
    slope_factor = calc.project_value(
        f"{prefix}-slope-factor",
        f"Selected elastic-slope factor{suffix}",
        f"gamma_slope,{index + 1}",
        "1",
        slope_factor_value,
        dependencies=(curve, gamma_y, gamma_e),
        assumption=(
            "Curve 2 uses gamma_y; curves 1 and 3 use the independently entered "
            "gamma_E."
        ),
    )
    slope_value = float(_value(material, "Es")) / slope_factor_value
    slope = calc.computed(
        f"{prefix}-design-slope",
        title=f"Design elastic slope{suffix}",
        symbol=f"Esd,{index + 1}",
        unit="MPa",
        value=slope_value,
        symbolic=f"Esd,{index + 1} = Es,{index + 1}/gamma_slope,{index + 1}",
        substituted=(
            f"Esd,{index + 1} = {_fmt(_value(material, 'Es'))}/"
            f"{_fmt(slope_factor_value)} = {_fmt(slope_value)} MPa"
        ),
        dependencies=(es, slope_factor),
        operator="divide",
        source=None,
        provenance=PROVENANCE_PROJECT,
    )
    preset_note = (
        f"Actual assigned preset: {preset}."
        if preset
        else "No recognised preset was attached; the law is user-defined."
    )
    return calc.project_value(
        f"{prefix}-law",
        f"Reinforcement constitutive law assigned{suffix}",
        f"law_s,{index + 1}",
        "1",
        1.0,
        dependencies=(
            curve,
            fyd,
            fycd,
            fud,
            slope,
            eut,
            k,
            ey0t,
            ey0c,
            active,
        ),
        assumption=(
            f"{preset_note} A value of 1 records the complete law supplied to "
            "the solver; it is not a conformity verdict."
        ),
    )


def _trace_tendon_capacity_law(
    calc: _Calc,
    material: Any,
    *,
    index: int,
    preset: str,
    element_id: str,
) -> str:
    """Expose one element-aligned tendon law, including fixed prestrain."""

    prefix = f"tendon-{index + 1:03d}"
    suffix = f" for {element_id}" if element_id else ""
    code = _code_from_preset(preset)
    if code is not None and code.key == "EC2-2023":
        proof_source = CIT_TENDON_PROOF_2023
        rupture_source = CIT_TENDON_RUPTURE_2023
        modulus_source = CIT_TENDON_MODULUS_2023
    elif code is not None:
        proof_source = CIT_TENDON_PROOF_2005
        rupture_source = CIT_TENDON_RUPTURE_2005
        modulus_source = CIT_TENDON_MODULUS_2005
    else:
        proof_source = rupture_source = modulus_source = None
    curve_value = int(_value(material, "curve"))
    curve = calc.input(
        f"{prefix}-curve",
        f"Selected tendon curve{suffix}",
        f"curve_p,{index + 1}",
        "1",
        curve_value,
    )
    initial = calc.input(
        f"{prefix}-initial-strain",
        f"Effective tendon prestrain{suffix}",
        f"eps_p0,{index + 1}",
        "1",
        _value(material, "IS"),
    )
    gamma_y = calc.input(
        f"{prefix}-gamma-y",
        f"Final tendon stress factor{suffix}",
        f"gamma_p,{index + 1}",
        "1",
        _value(material, "gamma_y"),
    )
    rupture = calc.input(
        f"{prefix}-rupture-strain",
        f"Tendon rupture strain used by the selected curve{suffix}",
        f"eps_pu,{index + 1}",
        "1",
        _value(material, "rupture_strain"),
    )
    dependencies: list[str] = [curve, initial, gamma_y, rupture]
    if curve_value in (6, 7):
        fytk = calc.input(
            f"{prefix}-fytk",
            f"Characteristic tendon proof strength{suffix}",
            f"fp01k,{index + 1}",
            "MPa",
            _value(material, "fytk"),
        )
        futk = calc.input(
            f"{prefix}-futk",
            f"Characteristic tendon rupture strength{suffix}",
            f"fpk,{index + 1}",
            "MPa",
            _value(material, "futk"),
        )
        gamma_u = calc.input(
            f"{prefix}-gamma-u",
            f"Final tendon rupture factor{suffix}",
            f"gamma_pu,{index + 1}",
            "1",
            _value(material, "gamma_u"),
        )
        gamma_e = calc.input(
            f"{prefix}-gamma-e",
            f"Final tendon modulus factor{suffix}",
            f"gamma_pE,{index + 1}",
            "1",
            _value(material, "gamma_E"),
        )
        es = calc.input(
            f"{prefix}-es",
            f"Tendon elastic modulus{suffix}",
            f"Ep,{index + 1}",
            "MPa",
            _value(material, "Es"),
        )
        k = calc.input(
            f"{prefix}-k",
            f"First-to-second tendon yield ratio{suffix}",
            f"k_p,{index + 1}",
            "1",
            _value(material, "k"),
        )
        ey0t = calc.input(
            f"{prefix}-ey0t",
            f"Second tendon-yield plastic strain{suffix}",
            f"ey0p,{index + 1}",
            "1",
            _value(material, "ey0t"),
        )
        fpd_value = float(_value(material, "fytk")) / float(
            _value(material, "gamma_y")
        )
        fpd = calc.computed(
            f"{prefix}-fpd",
            title=f"Design tendon proof strength{suffix}",
            symbol=f"fpd,{index + 1}",
            unit="MPa",
            value=fpd_value,
            symbolic=f"fpd,{index + 1} = fp01k,{index + 1}/gamma_p,{index + 1}",
            substituted=(
                f"fpd,{index + 1} = {_fmt(_value(material, 'fytk'))}/"
                f"{_fmt(_value(material, 'gamma_y'))} = {_fmt(fpd_value)} MPa"
            ),
            dependencies=(fytk, gamma_y),
            operator="divide",
            source=proof_source,
            provenance=(
                PROVENANCE_STANDARD
                if proof_source is not None
                else PROVENANCE_PROJECT
            ),
        )
        fpud_value = float(_value(material, "futk")) / float(
            _value(material, "gamma_u")
        )
        fpud = calc.computed(
            f"{prefix}-fpud",
            title=f"Design tendon rupture strength{suffix}",
            symbol=f"fpud,{index + 1}",
            unit="MPa",
            value=fpud_value,
            symbolic=f"fpud,{index + 1} = fpk,{index + 1}/gamma_pu,{index + 1}",
            substituted=(
                f"fpud,{index + 1} = {_fmt(_value(material, 'futk'))}/"
                f"{_fmt(_value(material, 'gamma_u'))} = {_fmt(fpud_value)} MPa"
            ),
            dependencies=(futk, gamma_u),
            operator="divide",
            source=rupture_source,
            provenance=(
                PROVENANCE_STANDARD
                if rupture_source is not None
                else PROVENANCE_PROJECT
            ),
        )
        slope_value = float(_value(material, "Es")) / float(
            _value(material, "gamma_E")
        )
        slope = calc.computed(
            f"{prefix}-design-slope",
            title=f"Design tendon elastic slope{suffix}",
            symbol=f"Epd,{index + 1}",
            unit="MPa",
            value=slope_value,
            symbolic=f"Epd,{index + 1} = Ep,{index + 1}/gamma_pE,{index + 1}",
            substituted=(
                f"Epd,{index + 1} = {_fmt(_value(material, 'Es'))}/"
                f"{_fmt(_value(material, 'gamma_E'))} = {_fmt(slope_value)} MPa"
            ),
            dependencies=(es, gamma_e),
            operator="divide",
            source=modulus_source,
            provenance=(
                PROVENANCE_STANDARD
                if modulus_source is not None
                else PROVENANCE_PROJECT
            ),
        )
        dependencies.extend((fpd, fpud, slope, k, ey0t))
    preset_note = (
        f"Actual assigned preset: {preset}."
        if preset
        else "No recognised preset was attached; the law is user-defined."
    )
    return calc.project_value(
        f"{prefix}-law",
        f"Tendon constitutive law assigned{suffix}",
        f"law_p,{index + 1}",
        "1",
        1.0,
        dependencies=tuple(dependencies),
        assumption=(
            f"{preset_note} The total strain is effective prestrain plus section "
            "strain. A value of 1 records the complete law supplied to the solver; "
            "it is not a conformity verdict."
        ),
    )


def _trace_plastic_concrete_law(
    calc: _Calc,
    inp: Mapping,
    *,
    code: codes.DesignCode | None,
) -> str:
    """Expose the concrete design strength and constitutive-law inputs."""

    concrete = inp["concrete"]
    fck = calc.input(
        "fck",
        "Characteristic concrete cylinder strength",
        "fck",
        "MPa",
        concrete.fck,
    )
    gamma_c = calc.input(
        "gamma-c",
        "Final concrete partial factor",
        "gamma_c",
        "1",
        concrete.gamma_c,
    )
    alpha = calc.input(
        "strength-factor",
        "Final concrete design-strength coefficient",
        "alpha_eff",
        "1",
        concrete.alpha_cc,
    )
    fcd_numerator_value = float(concrete.alpha_cc) * float(concrete.fck)
    fcd_source = (
        CIT_FCD_2023
        if code is not None and code.key == "EC2-2023"
        else CIT_FCD_2005
        if code is not None
        else None
    )
    fcd_numerator = calc.computed(
        "fcd-numerator",
        title="Factored characteristic concrete strength",
        symbol="alpha_eff fck",
        unit="MPa",
        value=fcd_numerator_value,
        symbolic="Q_c = alpha_eff fck",
        substituted=(
            f"Q_c = {_fmt(concrete.alpha_cc)} x {_fmt(concrete.fck)} "
            f"= {_fmt(fcd_numerator_value)} MPa"
        ),
        dependencies=(alpha, fck),
        operator="multiply",
        source=fcd_source,
        provenance=(
            PROVENANCE_STANDARD
            if fcd_source is not None
            else PROVENANCE_PROJECT
        ),
    )
    fcd = calc.computed(
        "fcd",
        title="Concrete design strength passed to section equilibrium",
        symbol="fcd",
        unit="MPa",
        value=concrete.fcd,
        symbolic="fcd = alpha_eff fck/gamma_c",
        substituted=(
            f"fcd = {_fmt(fcd_numerator_value)}/{_fmt(concrete.gamma_c)} "
            f"= {_fmt(concrete.fcd)} MPa"
        ),
        dependencies=(fcd_numerator, gamma_c),
        operator="divide",
        source=fcd_source,
        provenance=(
            PROVENANCE_STANDARD
            if fcd_source is not None
            else PROVENANCE_PROJECT
        ),
    )
    return _trace_concrete_capacity_law(
        calc,
        concrete,
        fcd_step=fcd,
    )


def _element_material_identity(
    elements: Any,
    *,
    index: int,
) -> tuple[str, str]:
    """Return stable element and material identifiers for an aligned law."""

    if (
        isinstance(elements, Sequence)
        and not isinstance(elements, (str, bytes, bytearray))
        and index < len(elements)
        and isinstance(elements[index], Mapping)
    ):
        return (
            str(elements[index].get("id") or ""),
            str(elements[index].get("material_id") or ""),
        )
    return "", ""


def _section_geometry(
    inp: Mapping,
) -> tuple[
    tuple[tuple[float, float], ...],
    tuple[tuple[tuple[float, float], ...], ...],
    tuple[tuple[float, float, float], ...],
    tuple[tuple[float, float, float], ...],
]:
    """Return the exact ordered geometry arrays supplied to section solvers."""

    section = inp.get("section")
    if "outer" in inp:
        outer_source = inp.get("outer")
        if outer_source is None:
            outer_source = ()
    elif section is not None:
        outer_source = section.concrete[0]
    else:
        outer_source = ()
    if "holes" in inp:
        holes_source = inp.get("holes")
        if holes_source is None:
            holes_source = ()
    elif section is not None:
        holes_source = section.concrete[1:]
    else:
        holes_source = ()
    if "bars" in inp:
        bars_source = inp.get("bars")
        if bars_source is None:
            bars_source = ()
    elif section is not None:
        bars_source = (
            (bar.x, bar.y, bar.area * 1.0e6)
            for bar in section.bars
        )
    else:
        bars_source = ()
    if "tendons" in inp:
        tendons_source = inp.get("tendons")
        if tendons_source is None:
            tendons_source = ()
    elif section is not None:
        tendons_source = (
            (tendon.x, tendon.y, tendon.area * 1.0e6)
            for tendon in section.tendons
        )
    else:
        tendons_source = ()

    outer = tuple(
        (float(point[0]), float(point[1]))
        for point in outer_source
    )
    holes = tuple(
        tuple((float(point[0]), float(point[1])) for point in ring)
        for ring in holes_source
    )
    bars = tuple(
        (float(item[0]), float(item[1]), float(item[2]))
        for item in bars_source
    )
    tendons = tuple(
        (float(item[0]), float(item[1]), float(item[2]))
        for item in tendons_source
    )
    if len(outer) < 3:
        raise ValueError(
            "section calculation trace requires the solver's ordered outer "
            "boundary geometry"
        )
    return outer, holes, bars, tendons


def _trace_section_geometry(calc: _Calc, inp: Mapping) -> str:
    """Expose every section vertex and point-element coordinate/area."""

    outer, holes, bars, tendons = _section_geometry(inp)
    inputs: list[str] = []
    for index, (x, y) in enumerate(outer, start=1):
        inputs.extend(
            (
                calc.input(
                    f"geometry-outer-{index:03d}-x",
                    f"Outer-boundary vertex {index} x-coordinate",
                    f"x_o,{index}",
                    "m",
                    x,
                ),
                calc.input(
                    f"geometry-outer-{index:03d}-y",
                    f"Outer-boundary vertex {index} y-coordinate",
                    f"y_o,{index}",
                    "m",
                    y,
                ),
            )
        )
    for ring_index, ring in enumerate(holes, start=1):
        for vertex_index, (x, y) in enumerate(ring, start=1):
            inputs.extend(
                (
                    calc.input(
                        (
                            f"geometry-hole-{ring_index:03d}-"
                            f"{vertex_index:03d}-x"
                        ),
                        (
                            f"Hole {ring_index} vertex {vertex_index} "
                            "x-coordinate"
                        ),
                        f"x_h,{ring_index},{vertex_index}",
                        "m",
                        x,
                    ),
                    calc.input(
                        (
                            f"geometry-hole-{ring_index:03d}-"
                            f"{vertex_index:03d}-y"
                        ),
                        (
                            f"Hole {ring_index} vertex {vertex_index} "
                            "y-coordinate"
                        ),
                        f"y_h,{ring_index},{vertex_index}",
                        "m",
                        y,
                    ),
                )
            )
    for index, (x, y, area) in enumerate(bars, start=1):
        element_id, _material_id = _element_material_identity(
            inp.get("bar_elements"),
            index=index - 1,
        )
        label = element_id or f"bar {index}"
        inputs.extend(
            (
                calc.input(
                    f"geometry-bar-{index:03d}-x",
                    f"{label} x-coordinate",
                    f"x_s,{index}",
                    "m",
                    x,
                ),
                calc.input(
                    f"geometry-bar-{index:03d}-y",
                    f"{label} y-coordinate",
                    f"y_s,{index}",
                    "m",
                    y,
                ),
                calc.input(
                    f"geometry-bar-{index:03d}-area",
                    f"{label} area",
                    f"A_s,{index}",
                    "mm2",
                    area,
                ),
            )
        )
    for index, (x, y, area) in enumerate(tendons, start=1):
        element_id, _material_id = _element_material_identity(
            inp.get("tendon_elements"),
            index=index - 1,
        )
        label = element_id or f"tendon {index}"
        inputs.extend(
            (
                calc.input(
                    f"geometry-tendon-{index:03d}-x",
                    f"{label} x-coordinate",
                    f"x_p,{index}",
                    "m",
                    x,
                ),
                calc.input(
                    f"geometry-tendon-{index:03d}-y",
                    f"{label} y-coordinate",
                    f"y_p,{index}",
                    "m",
                    y,
                ),
                calc.input(
                    f"geometry-tendon-{index:03d}-area",
                    f"{label} area",
                    f"A_p,{index}",
                    "mm2",
                    area,
                ),
            )
        )
    return calc.project_value(
        "section-geometry",
        "Ordered section geometry supplied to the numerical solver",
        "I_geometry",
        "1",
        1.0,
        dependencies=tuple(inputs),
        assumption=(
            "The dependency order records the complete outer ring, each hole "
            "ring, and every reinforcement/tendon point with its area. A value "
            "of 1 records the solver input vector and is not a conformity verdict."
        ),
    )


def _trace_assigned_capacity_laws(
    calc: _Calc,
    inp: Mapping,
    *,
    bar_laws: Sequence[Any],
    bar_presets: Sequence[str],
    tendon_laws: Sequence[Any],
    tendon_presets: Sequence[str],
) -> tuple[str, ...]:
    """Expose every element-aligned constitutive law used by a plastic solve."""

    assigned_law_steps: list[str] = []
    bar_elements = inp.get("bar_elements")
    bar_groups: dict[tuple[Any, ...], str] = {}
    for index, (material, preset) in enumerate(zip(bar_laws, bar_presets)):
        element_id, material_id = _element_material_identity(
            bar_elements,
            index=index,
        )
        key = _material_law_key(
            material,
            preset=preset,
            material_id=material_id,
        )
        law_step = bar_groups.get(key)
        if law_step is None:
            law_step = _trace_mild_capacity_law(
                calc,
                material,
                index=len(bar_groups),
                preset=preset,
                element_id=material_id or element_id,
            )
            bar_groups[key] = law_step
        assignment_label = element_id or f"bar {index + 1}"
        assigned_law_steps.append(
            calc.project_value(
                f"bar-assignment-{index + 1:03d}",
                f"Constitutive-law assignment for {assignment_label}",
                f"I_bar-law,{index + 1}",
                "1",
                1.0,
                dependencies=(law_step,),
                assumption=(
                    f"{assignment_label} uses "
                    f"{material_id or preset or 'the recorded fallback law'}. "
                    "A value of 1 records the solver assignment and is not a "
                    "conformity verdict."
                ),
            )
        )

    tendon_elements = inp.get("tendon_elements")
    tendon_groups: dict[tuple[Any, ...], str] = {}
    for index, (material, preset) in enumerate(
        zip(tendon_laws, tendon_presets)
    ):
        element_id, material_id = _element_material_identity(
            tendon_elements,
            index=index,
        )
        key = _material_law_key(
            material,
            preset=preset,
            material_id=material_id,
        )
        law_step = tendon_groups.get(key)
        if law_step is None:
            law_step = _trace_tendon_capacity_law(
                calc,
                material,
                index=len(tendon_groups),
                preset=preset,
                element_id=material_id or element_id,
            )
            tendon_groups[key] = law_step
        assignment_label = element_id or f"tendon {index + 1}"
        assigned_law_steps.append(
            calc.project_value(
                f"tendon-assignment-{index + 1:03d}",
                f"Constitutive-law assignment for {assignment_label}",
                f"I_tendon-law,{index + 1}",
                "1",
                1.0,
                dependencies=(law_step,),
                assumption=(
                    f"{assignment_label} uses "
                    f"{material_id or preset or 'the recorded fallback law'}. "
                    "A value of 1 records the solver assignment and is not a "
                    "conformity verdict."
                ),
            )
        )
    return tuple(assigned_law_steps)


def plastic_calculations(
    inp: Mapping,
    out: Mapping,
    *,
    context: Mapping[str, Any],
) -> list[TraceCalculation]:
    """Trace the numerical section-capacity solve and radial utilisation."""

    result = out.get("plastic")
    if not isinstance(result, Mapping):
        return []
    points = list(result.get("points") or ())
    mx = list(result.get("mx") or ())
    my = list(result.get("my") or ())
    if not points or not mx or len(mx) != len(my):
        return []
    code = _preset_code(inp)
    section_source = (
        CIT_PLASTIC_2023
        if code is not None and code.key == "EC2-2023"
        else CIT_PLASTIC_2005
        if code is not None
        else None
    )
    steel = inp.get("steel")
    bar_laws = _material_sequence(inp, "bar_materials", steel)
    tendon_laws = _material_sequence(
        inp,
        "tendon_materials",
        inp.get("prestress"),
    )
    bar_presets = tuple(
        _assigned_material_preset(inp, kind="bar", index=index)
        if "bar_materials" in inp
        else _capacity_steel_preset(inp)
        for index in range(len(bar_laws))
    )
    tendon_presets = tuple(
        _assigned_material_preset(inp, kind="tendon", index=index)
        if "tendon_materials" in inp
        else str(inp.get("prestress_preset") or "")
        for index in range(len(tendon_laws))
    )
    assigned_codes = tuple(
        _code_from_preset(preset)
        for preset in (*bar_presets, *tendon_presets)
    )
    custom_assigned_law = any(item is None for item in assigned_codes)
    assigned_standard_law = any(item is not None for item in assigned_codes)
    standard_based = code is not None and not custom_assigned_law
    user_defined_method = code is None and not assigned_standard_law
    hybrid_method = not standard_based and not user_defined_method
    cid = _context_id(context)
    applied_x = float(inp.get("Mx_pl", 0.0))
    applied_y = float(inp.get("My_pl", 0.0))
    applied_rad = math.hypot(applied_x, applied_y)
    util = result.get("util")
    gov_index = result.get("util_gov")
    if gov_index is None or not (0 <= int(gov_index) < len(points)):
        gov_index = max(
            range(len(points)),
            key=lambda index: math.hypot(float(mx[index]), float(my[index])),
        )
    gov_index = int(gov_index)
    point = points[gov_index]
    capacity_rad = math.hypot(float(mx[gov_index]), float(my[gov_index]))

    calc = _Calc(
        calculation_id=f"plastic.{cid}.capacity",
        coverage_id="CT-002",
        title="Plastic section capacity at the governing traced state",
        method_id=(
            code.key
            if standard_based
            else "mixed-standard-project-material-section-solve"
            if hybrid_method
            else "user-defined-material-section-solve"
        ),
        method_label=(
            (
                f"{code.label}; Sector fibre equilibrium with explicitly "
                "assigned project/user material laws"
                if custom_assigned_law
                else f"{code.label}; Sector fibre equilibrium"
            )
            if code is not None
            else (
                "Mixed standard-selected reinforcement/tendon and user-defined "
                "concrete law; Sector fibre equilibrium"
                if hybrid_method
                else "User-defined material laws; Sector fibre equilibrium"
            )
        ),
        standard_based=standard_based,
        user_defined_method=user_defined_method,
        context=context,
        assumptions=(
            "Sector solves axial-force equilibrium and integrates the selected "
            "constitutive laws over the section; this numerical discretisation "
            "is project-defined.",
            (
                "One or more assigned reinforcement/tendon laws are project- or "
                "user-defined. Their recorded values receive no invented "
                "standards citation."
                if custom_assigned_law
                else ""
            ),
        ),
    )
    n_ed = calc.input("n-ed", "Applied axial force", "NEd", "kN", inp.get("P_pl", 0.0))
    angle = calc.project_value(
        "na-angle",
        "Governing neutral-axis sweep angle",
        "V",
        "degrees",
        _value(point, "V", 0.0),
        assumption=(
            "Selected from the user-defined sweep after the solver identified "
            "the governing traced state."
        ),
    )
    concrete_law = _trace_plastic_concrete_law(calc, inp, code=code)
    section_geometry = _trace_section_geometry(calc, inp)
    assigned_law_steps = _trace_assigned_capacity_laws(
        calc,
        inp,
        bar_laws=bar_laws,
        bar_presets=bar_presets,
        tendon_laws=tendon_laws,
        tendon_presets=tendon_presets,
    )
    curvature = calc.project_value(
        "curvature",
        "Governing ultimate curvature",
        "kappa",
        "1/m",
        _plastic_point_value(point, "kappa", "curvature", 0.0),
        dependencies=(
            angle,
            section_geometry,
            concrete_law,
            *assigned_law_steps,
        ),
        assumption=(
            "The smallest selected concrete, reinforcement or tendon strain "
            "limit governs the solver-owned linear strain plane."
        ),
    )
    achieved_axial_value = _plastic_point_axial(
        point,
        inp.get("P_pl", 0.0),
    )
    achieved_axial = calc.computed(
        "axial-resultant",
        title="Integrated axial resistance",
        symbol="N_Rd",
        unit="kN",
        value=achieved_axial_value,
        symbolic="N_Rd = sum(F_i)",
        substituted=f"N_Rd = sum(F_i) = {_fmt(achieved_axial_value)} kN",
        dependencies=(
            curvature,
            section_geometry,
            concrete_law,
            *assigned_law_steps,
        ),
        operator="solver",
        source=section_source,
        provenance=(
            PROVENANCE_STANDARD
            if section_source is not None
            else PROVENANCE_PROJECT
        ),
        assumption=(
            "Concrete bands, reinforcement points and tendon points are "
            "integrated by the section solver."
        ),
    )
    residual_value = float(achieved_axial_value) - float(
        inp.get("P_pl", 0.0)
    )
    residual = calc.computed(
        "axial-residual",
        title="Axial equilibrium residual",
        symbol="Delta N",
        unit="kN",
        value=residual_value,
        symbolic="Delta N = N_Rd - N_Ed",
        substituted=(
            f"Delta N = {_fmt(achieved_axial_value)} - "
            f"{_fmt(inp.get('P_pl', 0.0))} = {_fmt(residual_value)} kN"
        ),
        dependencies=(achieved_axial, n_ed),
        operator="subtract",
        source=section_source,
        provenance=(
            PROVENANCE_STANDARD
            if section_source is not None
            else PROVENANCE_PROJECT
        ),
    )
    convergence = calc.project_value(
        "equilibrium",
        "Converged section-force equilibrium",
        "equilibrium",
        "1",
        1.0 if bool(_value(point, "converged", result.get("converged"))) else 0.0,
        dependencies=(residual,),
        assumption=(
            "A value of 1 records the solver's explicit residual-tolerance "
            "decision; it is not a compliance or approval verdict."
        ),
    )
    compression_force = calc.project_value(
        "compression-resultant",
        "Integrated compression resultant",
        "C_Rd",
        "kN",
        _plastic_point_value(
            point,
            "comp_force",
            "compression_force",
            0.0,
        ),
        dependencies=(convergence, curvature),
        assumption="Solver-owned sum of compressive material forces.",
    )
    lever_arm = calc.project_value(
        "internal-lever-arm",
        "Internal resultant lever arm",
        "z",
        "m",
        _plastic_point_value(point, "lever", "lever_arm", 0.0),
        dependencies=(compression_force,),
        assumption="Distance between the solver-owned force resultants.",
    )
    mx_rd = calc.computed(
        "mx-rd",
        title="Integrated x-axis moment resistance",
        symbol="Mx,Rd",
        unit="kNm",
        value=mx[gov_index],
        symbolic="Mx,Rd = sum(F_i y_i)",
        substituted=f"Mx,Rd = sum(F_i y_i) = {_fmt(mx[gov_index])} kNm",
        dependencies=(convergence, compression_force, lever_arm),
        operator="solver",
        source=section_source,
        provenance=(
            PROVENANCE_STANDARD
            if section_source is not None
            else PROVENANCE_PROJECT
        ),
        assumption=(
            "The section solver integrates concrete, reinforcement and tendon "
            "forces about the x-axis."
        ),
    )
    my_rd = calc.computed(
        "my-rd",
        title="Integrated y-axis moment resistance",
        symbol="My,Rd",
        unit="kNm",
        value=my[gov_index],
        symbolic="My,Rd = sum(F_i x_i)",
        substituted=f"My,Rd = sum(F_i x_i) = {_fmt(my[gov_index])} kNm",
        dependencies=(convergence, compression_force, lever_arm),
        operator="solver",
        source=section_source,
        provenance=(
            PROVENANCE_STANDARD
            if section_source is not None
            else PROVENANCE_PROJECT
        ),
        assumption=(
            "The section solver integrates concrete, reinforcement and tendon "
            "forces about the y-axis."
        ),
    )
    capacity = calc.computed(
        "m-rd-resultant",
        title="Resultant resistance at traced state",
        symbol="MRd",
        unit="kNm",
        value=capacity_rad,
        symbolic="MRd = sqrt(Mx,Rd^2 + My,Rd^2)",
        substituted=(
            f"MRd = sqrt({_fmt(mx[gov_index])}^2 + "
            f"{_fmt(my[gov_index])}^2) = {_fmt(capacity_rad)} kNm"
        ),
        dependencies=(mx_rd, my_rd),
        operator="hypot",
        source=section_source,
        provenance=(
            PROVENANCE_STANDARD
            if section_source is not None
            else PROVENANCE_PROJECT
        ),
        role=ROLE_FINAL,
    )
    calculations = [calc.finish(capacity)]

    if util is not None and math.isfinite(float(util)):
        radial = _Calc(
            calculation_id=f"plastic.{cid}.radial-utilisation",
            coverage_id="CT-003",
            title="Radial demand-to-envelope utilisation",
            method_id="sector-radial-envelope-intersection",
            method_label="Sector geometric ray/polygon intersection",
            standard_based=False,
            context=context,
            assumptions=(
                "The closed capacity polygon is intersected by the applied-moment "
                "ray. This is a project-defined geometric procedure.",
            ),
        )
        mx_ed = radial.input("mx-ed", "Applied x-axis moment", "Mx,Ed", "kNm", applied_x)
        my_ed = radial.input("my-ed", "Applied y-axis moment", "My,Ed", "kNm", applied_y)
        m_ed = radial.computed(
            "m-ed",
            title="Applied resultant moment",
            symbol="MEd",
            unit="kNm",
            value=applied_rad,
            symbolic="MEd = sqrt(Mx,Ed^2 + My,Ed^2)",
            substituted=(
                f"MEd = sqrt({_fmt(applied_x)}^2 + {_fmt(applied_y)}^2) "
                f"= {_fmt(applied_rad)} kNm"
            ),
            dependencies=(mx_ed, my_ed),
            operator="hypot",
            source=None,
        )
        radial_resistance = (
            applied_rad / float(util) if float(util) > 0.0 else capacity_rad
        )
        m_rd = radial.project_value(
            "m-rd-ray",
            "Capacity-envelope intersection on applied ray",
            "MRd,ray",
            "kNm",
            radial_resistance,
            dependencies=(mx_ed, my_ed),
        )
        eta = radial.computed(
            "eta-m",
            title="Moment utilisation",
            symbol="eta_M",
            unit="1",
            value=util,
            symbolic="eta_M = MEd / MRd,ray",
            substituted=(
                f"eta_M = {_fmt(applied_rad)} / {_fmt(radial_resistance)} "
                f"= {_fmt(float(util))}"
            ),
            dependencies=(m_ed, m_rd),
            operator="divide",
            source=None,
            role=ROLE_FINAL,
        )
        calculations.append(radial.finish(eta))

    interaction = result.get("interaction")
    if isinstance(interaction, Mapping):
        for axis in ("x", "y"):
            branch = interaction.get(axis)
            if not isinstance(branch, Mapping):
                continue
            n_values = list(branch.get("N") or ())
            m_values = list(branch.get("M") or ())
            if not n_values or len(n_values) != len(m_values):
                continue
            index = max(
                range(len(m_values)),
                key=lambda item: abs(float(m_values[item])),
            )
            nm = _Calc(
                calculation_id=f"plastic.{cid}.interaction-{axis}",
                coverage_id="CT-004",
                title=f"N-M{axis} interaction boundary traced state",
                method_id=(
                    code.key
                    if standard_based
                    else "mixed-standard-project-material-section-solve"
                    if hybrid_method
                    else "user-defined-material-section-solve"
                ),
                method_label=(
                    (
                        f"{code.label}; Sector fibre equilibrium with explicitly "
                        "assigned project/user material laws"
                        if custom_assigned_law
                        else f"{code.label}; Sector fibre equilibrium"
                    )
                    if code is not None
                    else (
                        "Mixed standard-selected reinforcement/tendon and "
                        "user-defined concrete law; Sector fibre equilibrium"
                        if hybrid_method
                        else "User-defined material laws; Sector fibre equilibrium"
                    )
                ),
                standard_based=standard_based,
                user_defined_method=user_defined_method,
                context={**context, "axis": axis},
                assumptions=(
                    "The complete interaction boundary is retained in the solver "
                    "result; the trace records the maximum absolute moment state.",
                ),
            )
            interaction_concrete_law = _trace_plastic_concrete_law(
                nm,
                inp,
                code=code,
            )
            interaction_geometry = _trace_section_geometry(nm, inp)
            interaction_assigned_laws = _trace_assigned_capacity_laws(
                nm,
                inp,
                bar_laws=bar_laws,
                bar_presets=bar_presets,
                tendon_laws=tendon_laws,
                tendon_presets=tendon_presets,
            )
            state = nm.project_value(
                "boundary-state",
                "Converged interaction state",
                "state",
                "1",
                1.0 if branch.get("converged") else 0.0,
                dependencies=(
                    interaction_geometry,
                    interaction_concrete_law,
                    *interaction_assigned_laws,
                ),
                assumption="Sector numerical section equilibrium.",
            )
            n_rd = nm.project_value(
                "n-rd",
                "Axial resistance at traced state",
                "NRd",
                "kN",
                n_values[index],
                dependencies=(state,),
            )
            m_rd_nm = nm.project_value(
                "m-rd",
                "Moment resistance at traced state",
                f"M{axis},Rd",
                "kNm",
                m_values[index],
                dependencies=(state, n_rd),
                role=ROLE_FINAL,
            )
            calculations.append(nm.finish(m_rd_nm))
    return calculations


def _trace_elastic_actions(
    calc: _Calc,
    inp: Mapping,
) -> tuple[str, ...]:
    """Expose the complete long- and short-term external action vector."""

    return (
        calc.input(
            "n-long",
            "Long-term axial action",
            "Nlong",
            "kN",
            inp.get("P_el_l", 0.0),
        ),
        calc.input(
            "mx-long",
            "Long-term x moment",
            "Mx,long",
            "kNm",
            inp.get("Mx_el_l", 0.0),
        ),
        calc.input(
            "my-long",
            "Long-term y moment",
            "My,long",
            "kNm",
            inp.get("My_el_l", 0.0),
        ),
        calc.input(
            "n-short",
            "Short-term axial increment",
            "Nshort",
            "kN",
            inp.get("P_el_s", 0.0),
        ),
        calc.input(
            "mx-short",
            "Short-term x-moment increment",
            "Mx,short",
            "kNm",
            inp.get("Mx_el_s", 0.0),
        ),
        calc.input(
            "my-short",
            "Short-term y-moment increment",
            "My,short",
            "kNm",
            inp.get("My_el_s", 0.0),
        ),
    )


def _trace_elastic_reference_ratios(
    calc: _Calc,
    inp: Mapping,
) -> tuple[str, str, str]:
    """Expose the solver reference modulus and short/long modular ratios."""

    ec_gpa = calc.input(
        "concrete-modulus",
        "Entered concrete elastic modulus",
        "Ecm",
        "GPa",
        inp.get("conc_Ec", 0.0),
    )
    ec_mpa_value = 1000.0 * float(inp.get("conc_Ec", 0.0))
    ec_mpa = calc.computed(
        "concrete-modulus-mpa",
        title="Concrete elastic modulus in solver units",
        symbol="Ecm,MPa",
        unit="MPa",
        value=ec_mpa_value,
        symbolic="Ecm,MPa = 1000 Ecm,GPa",
        substituted=(
            f"Ecm,MPa = 1000 x {_fmt(inp.get('conc_Ec', 0.0))} "
            f"= {_fmt(ec_mpa_value)} MPa"
        ),
        dependencies=(ec_gpa,),
        operator="identity",
        factor=1000.0,
        source=None,
    )
    es_reference = calc.project_value(
        "reference-steel-modulus",
        "Solver reference reinforcement modulus",
        "Es,ref",
        "MPa",
        200000.0,
        assumption=(
            "Element-specific elastic moduli are applied by solver multipliers "
            "relative to this 200 GPa reference."
        ),
    )
    ns = calc.computed(
        "n-ratio-short",
        title="Short-term reference modular ratio",
        symbol="nshort",
        unit="1",
        value=inp.get("ns", 1.0),
        symbolic="nshort = Es,ref/Ecm",
        substituted=(
            f"nshort = 200000/{_fmt(ec_mpa_value)} "
            f"= {_fmt(inp.get('ns', 1.0))}"
        ),
        dependencies=(es_reference, ec_mpa),
        operator="divide",
        source=None,
    )
    phi = calc.input(
        "creep-coefficient",
        "Entered creep coefficient",
        "phi",
        "1",
        inp.get("el_phi", 0.0),
    )
    one = calc.project_value(
        "one",
        "Unity",
        "1",
        "1",
        1.0,
        assumption="Arithmetic unity for the project-defined modular-ratio model.",
    )
    creep_multiplier_value = 1.0 + float(inp.get("el_phi", 0.0))
    creep_multiplier = calc.computed(
        "creep-multiplier",
        title="Long-term modular-ratio multiplier",
        symbol="1+phi",
        unit="1",
        value=creep_multiplier_value,
        symbolic="q_phi = 1 + phi",
        substituted=(
            f"q_phi = 1 + {_fmt(inp.get('el_phi', 0.0))} "
            f"= {_fmt(creep_multiplier_value)}"
        ),
        dependencies=(one, phi),
        operator="add",
        source=None,
    )
    nl = calc.computed(
        "n-ratio-long",
        title="Long-term reference modular ratio",
        symbol="nlong",
        unit="1",
        value=inp.get("nl", 1.0),
        symbolic="nlong = nshort(1+phi)",
        substituted=(
            f"nlong = {_fmt(inp.get('ns', 1.0))} x "
            f"{_fmt(creep_multiplier_value)} = {_fmt(inp.get('nl', 1.0))}"
        ),
        dependencies=(ns, creep_multiplier),
        operator="multiply",
        source=None,
    )
    return es_reference, ns, nl


def _trace_elastic_material_laws(
    calc: _Calc,
    inp: Mapping,
    *,
    es_reference_step: str,
    ratio_steps: Sequence[tuple[str, str, float]],
) -> tuple[str, ...]:
    """Expose element-specific transformed-section laws and tendon prestress."""

    steel = inp.get("steel")
    bar_laws = _material_sequence(inp, "bar_materials", steel)
    tendon_laws = _material_sequence(
        inp,
        "tendon_materials",
        inp.get("prestress"),
    )
    bar_presets = tuple(
        _assigned_material_preset(inp, kind="bar", index=index)
        if "bar_materials" in inp
        else _capacity_steel_preset(inp)
        for index in range(len(bar_laws))
    )
    tendon_presets = tuple(
        _assigned_material_preset(inp, kind="tendon", index=index)
        if "tendon_materials" in inp
        else str(inp.get("prestress_preset") or "")
        for index in range(len(tendon_laws))
    )

    assignments: list[str] = []
    for kind, laws, presets, elements, label in (
        (
            "bar",
            bar_laws,
            bar_presets,
            inp.get("bar_elements"),
            "reinforcement",
        ),
        (
            "tendon",
            tendon_laws,
            tendon_presets,
            inp.get("tendon_elements"),
            "tendon",
        ),
    ):
        groups: dict[tuple[Any, ...], str] = {}
        for index, (material, preset) in enumerate(zip(laws, presets)):
            element_id, material_id = _element_material_identity(
                elements,
                index=index,
            )
            key = _material_law_key(
                material,
                preset=preset,
                material_id=material_id,
            )
            law_step = groups.get(key)
            if law_step is None:
                group_index = len(groups)
                prefix = f"elastic-{kind}-{group_index + 1:03d}"
                suffix = (
                    f" for {material_id or element_id}"
                    if material_id or element_id
                    else ""
                )
                es_value = float(_value(material, "Es"))
                es = calc.input(
                    f"{prefix}-es",
                    f"{label.title()} elastic modulus{suffix}",
                    f"E_{kind[0]},{group_index + 1}",
                    "MPa",
                    es_value,
                )
                multiplier_value = es_value / 200000.0
                multiplier = calc.computed(
                    f"{prefix}-modulus-multiplier",
                    title=f"{label.title()} reference-modulus multiplier{suffix}",
                    symbol=f"m_E,{kind[0]}{group_index + 1}",
                    unit="1",
                    value=multiplier_value,
                    symbolic=(
                        f"m_E,{kind[0]}{group_index + 1} = "
                        f"E_{kind[0]},{group_index + 1}/Es,ref"
                    ),
                    substituted=(
                        f"m_E,{kind[0]}{group_index + 1} = "
                        f"{_fmt(es_value)}/200000 = "
                        f"{_fmt(multiplier_value)}"
                    ),
                    dependencies=(es, es_reference_step),
                    operator="divide",
                    source=None,
                )
                law_dependencies: list[str] = [es, multiplier]
                for period, base_step, base_value in ratio_steps:
                    ratio_value = float(base_value) * multiplier_value
                    ratio = calc.computed(
                        f"{prefix}-n-ratio-{period}",
                        title=(
                            f"{period.title()} {label} modular ratio{suffix}"
                        ),
                        symbol=f"n_{period},{kind[0]}{group_index + 1}",
                        unit="1",
                        value=ratio_value,
                        symbolic=(
                            f"n_{period},{kind[0]}{group_index + 1} = "
                            f"n_{period},ref m_E,{kind[0]}{group_index + 1}"
                        ),
                        substituted=(
                            f"n_{period},{kind[0]}{group_index + 1} = "
                            f"{_fmt(base_value)} x {_fmt(multiplier_value)} "
                            f"= {_fmt(ratio_value)}"
                        ),
                        dependencies=(base_step, multiplier),
                        operator="multiply",
                        source=None,
                    )
                    law_dependencies.append(ratio)
                if kind == "tendon":
                    initial_value = float(_value(material, "IS"))
                    initial = calc.input(
                        f"{prefix}-initial-strain",
                        f"Effective tendon prestrain{suffix}",
                        f"eps_p0,{group_index + 1}",
                        "1",
                        initial_value,
                    )
                    locked_value = es_value * initial_value
                    locked = calc.computed(
                        f"{prefix}-locked-prestress",
                        title=f"Locked-in tendon prestress{suffix}",
                        symbol=f"sigma_p0,{group_index + 1}",
                        unit="MPa",
                        value=locked_value,
                        symbolic=(
                            f"sigma_p0,{group_index + 1} = "
                            f"E_p,{group_index + 1} eps_p0,{group_index + 1}"
                        ),
                        substituted=(
                            f"sigma_p0,{group_index + 1} = "
                            f"{_fmt(es_value)} x {_fmt(initial_value)} "
                            f"= {_fmt(locked_value)} MPa"
                        ),
                        dependencies=(es, initial),
                        operator="multiply",
                        source=None,
                    )
                    law_dependencies.extend((initial, locked))
                preset_note = (
                    f"Recorded material preset: {preset}."
                    if preset
                    else "No recognised preset is attached; values are user-defined."
                )
                law_step = calc.project_value(
                    f"{prefix}-law",
                    f"Elastic {label} law supplied to transformed section{suffix}",
                    f"law_el,{kind[0]}{group_index + 1}",
                    "1",
                    1.0,
                    dependencies=tuple(law_dependencies),
                    assumption=(
                        f"{preset_note} A value of 1 records the exact "
                        "solver material vector and is not a conformity verdict."
                    ),
                )
                groups[key] = law_step
            assignment_label = element_id or f"{label} {index + 1}"
            assignments.append(
                calc.project_value(
                    f"elastic-{kind}-assignment-{index + 1:03d}",
                    f"Elastic-law assignment for {assignment_label}",
                    f"I_el,{kind[0]}{index + 1}",
                    "1",
                    1.0,
                    dependencies=(law_step,),
                    assumption=(
                        f"{assignment_label} uses "
                        f"{material_id or preset or 'the recorded fallback law'}. "
                        "A value of 1 records the aligned solver assignment."
                    ),
                )
            )
    return tuple(assignments)


def _infinite_cracking_factor_calculation(
    inp: Mapping,
    result: Mapping,
    *,
    context: Mapping[str, Any],
    cid: str,
) -> TraceCalculation:
    """Trace a legitimate infinite cracking factor using finite state leaves."""

    lambda_value = float(result["lambda_cr"])
    if not (math.isinf(lambda_value) and lambda_value > 0.0):
        raise ValueError(
            f"elastic.{cid}.cracking-factor: unexpected non-finite lambda_cr"
        )
    threshold_record = result.get("cracking_threshold")
    fixed_prestress = (
        isinstance(threshold_record, Mapping)
        and threshold_record.get("method") == "fixed-prestress-decompression"
    )
    state_warning = (
        "lambda_cr is infinite because the selected external action produces no "
        "positive concrete tensile-stress increment. The solver result retains "
        "that infinite value; the trace publishes finite reachability leaves and "
        "a zero finite-factor-availability state."
    )
    threshold = _Calc(
        calculation_id=f"elastic.{cid}.cracking-factor",
        coverage_id="CT-005",
        title="First-cracking load-factor availability",
        method_id=(
            "sector-fixed-prestress-decompression"
            if fixed_prestress
            else "sector-linear-elastic-scaling"
        ),
        method_label=(
            "Sector fixed-prestress decompression procedure"
            if fixed_prestress
            else "Sector linear-elastic cracking-factor procedure"
        ),
        standard_based=False,
        context=context,
        warnings=(state_warning,),
        assumptions=(
            (
                "The tendon prestress is a fixed action; the external action "
                "vector alone would be scaled to first cracking.",
            )
            if fixed_prestress
            else ()
        ),
    )
    action_steps = _trace_elastic_actions(threshold, inp)
    section_geometry = _trace_section_geometry(threshold, inp)
    es_reference, ns, nl = _trace_elastic_reference_ratios(threshold, inp)
    material_assignments = _trace_elastic_material_laws(
        threshold,
        inp,
        es_reference_step=es_reference,
        ratio_steps=(
            ("short", ns, float(inp.get("ns", 1.0))),
            ("long", nl, float(inp.get("nl", 1.0))),
        ),
    )
    solver_dependencies = (
        *action_steps,
        section_geometry,
        ns,
        nl,
        *material_assignments,
    )
    fctm_value = _number(
        result.get("fctm", inp.get("sls_fctm", 0.0)),
        "fctm",
    )
    fctm = threshold.input(
        "fctm",
        "User-selected mean tensile strength",
        "fctm",
        "MPa",
        fctm_value,
    )
    zero = threshold.project_value(
        "zero-tension",
        "Zero positive-tension threshold",
        "0",
        "MPa",
        0.0,
        role=ROLE_METHOD_VALUE,
        assumption=(
            "A positive external tensile-stress increment is required for a "
            "finite positive cracking factor."
        ),
    )
    if fixed_prestress:
        fibre = threshold_record.get("governing_fibre_index")
        fibre_note = (
            f"Solver-selected greatest external-tension fibre index {int(fibre)}."
            if fibre is not None and not isinstance(fibre, bool)
            else "Solver-selected greatest external-tension concrete fibre."
        )
        sigma_pre_value = _number(
            threshold_record.get("fixed_prestress_mpa"),
            "fixed_prestress_mpa",
        )
        sigma_ext_value = _number(
            threshold_record.get("external_tension_mpa"),
            "external_tension_mpa",
        )
        available_value = _number(
            threshold_record.get("available_tension_mpa"),
            "available_tension_mpa",
        )
        sigma_pre = threshold.project_value(
            "sigma-pre",
            "Fixed prestress stress at selected fibre",
            "sigma_pre,g",
            "MPa",
            sigma_pre_value,
            dependencies=(section_geometry, nl, *material_assignments),
            assumption=fibre_note,
        )
        sigma_ext = threshold.project_value(
            "sigma-ext",
            "External-action tensile stress at selected fibre",
            "sigma_ext,g",
            "MPa",
            sigma_ext_value,
            dependencies=solver_dependencies,
            assumption=fibre_note,
        )
        available = threshold.computed(
            "available-tension",
            title="Tensile-stress increment available before cracking",
            symbol="Delta_sigma_cr,g",
            unit="MPa",
            value=available_value,
            symbolic="Delta_sigma_cr,g = fctm - sigma_pre,g",
            substituted=(
                f"Delta_sigma_cr,g = {_fmt(fctm_value)} - "
                f"({_fmt(sigma_pre_value)}) = {_fmt(available_value)} MPa"
            ),
            dependencies=(fctm, sigma_pre),
            operator="subtract",
            source=None,
        )
        positive_tension_value = max(0.0, sigma_ext_value)
        positive_tension = threshold.computed(
            "positive-external-tension",
            title="Positive external tensile-stress increment",
            symbol="sigma_ext,+",
            unit="MPa",
            value=positive_tension_value,
            symbolic="sigma_ext,+ = max(0, sigma_ext,g)",
            substituted=(
                f"sigma_ext,+ = max(0, {_fmt(sigma_ext_value)}) = "
                f"{_fmt(positive_tension_value)} MPa"
            ),
            dependencies=(zero, sigma_ext),
            operator="max",
            source=None,
        )
        final_dependencies = (available, positive_tension)
    else:
        sigma_ct_value = _number(result.get("sigma_ct", 0.0), "sigma_ct")
        sigma_ct = threshold.project_value(
            "sigma-ct",
            "Stage-I extreme concrete tension",
            "sigma_ct",
            "MPa",
            sigma_ct_value,
            dependencies=solver_dependencies,
            assumption="Retained from the solver-owned Stage-I strain plane.",
        )
        positive_tension_value = max(0.0, sigma_ct_value)
        positive_tension = threshold.computed(
            "positive-stage-i-tension",
            title="Positive Stage-I concrete tension",
            symbol="sigma_ct,+",
            unit="MPa",
            value=positive_tension_value,
            symbolic="sigma_ct,+ = max(0, sigma_ct)",
            substituted=(
                f"sigma_ct,+ = max(0, {_fmt(sigma_ct_value)}) = "
                f"{_fmt(positive_tension_value)} MPa"
            ),
            dependencies=(zero, sigma_ct),
            operator="max",
            source=None,
        )
        final_dependencies = (fctm, positive_tension)
    availability = threshold.computed(
        "finite-factor-available",
        title="Finite first-cracking factor available state",
        symbol="I_lambda,finite",
        unit="1",
        value=0.0,
        symbolic=(
            "I_lambda,finite = 0 when the positive external tensile increment "
            "is zero"
        ),
        substituted=(
            f"I_lambda,finite = 0 because the positive tensile increment is "
            f"{_fmt(positive_tension_value)} MPa; lambda_cr = infinite"
        ),
        dependencies=final_dependencies,
        operator="solver",
        source=None,
        provenance=PROVENANCE_PROJECT,
        role=ROLE_FINAL,
        warning=state_warning,
        assumption=(
            "The finite state indicator records reachability only. It is not a "
            "stress/crack acceptance limit or a global verdict."
        ),
    )
    return threshold.finish(availability)


def elastic_calculations(
    inp: Mapping,
    out: Mapping,
    *,
    context: Mapping[str, Any],
) -> list[TraceCalculation]:
    """Trace the project-defined elastic equilibrium outputs."""

    result = out.get("elastic")
    if not isinstance(result, Mapping):
        return []
    cid = _context_id(context)
    calc = _Calc(
        calculation_id=f"elastic.{cid}.section-equilibrium",
        coverage_id="CT-005",
        title="Cracked/uncracked elastic section equilibrium",
        method_id="sector-transformed-section-equilibrium",
        method_label="Sector transformed-section numerical procedure",
        standard_based=False,
        context=context,
        assumptions=(
            "Sector solves the transformed-section strain plane and superposes "
            "long- and short-term action states. No normative equation number is "
            "assigned to this project-defined numerical procedure.",
        ),
    )
    action_steps = _trace_elastic_actions(calc, inp)
    section_geometry = _trace_section_geometry(calc, inp)
    es_reference, ns, nl = _trace_elastic_reference_ratios(calc, inp)
    material_assignments = _trace_elastic_material_laws(
        calc,
        inp,
        es_reference_step=es_reference,
        ratio_steps=(
            ("short", ns, float(inp.get("ns", 1.0))),
            ("long", nl, float(inp.get("nl", 1.0))),
        ),
    )
    deps = (
        *action_steps,
        section_geometry,
        nl,
        ns,
        *material_assignments,
    )
    max_conc = calc.project_value(
        "max-concrete",
        "Maximum concrete compression",
        "sigma_c,max",
        "MPa",
        result.get("max_conc", 0.0),
        dependencies=deps,
    )
    max_steel = calc.project_value(
        "max-reinforcement",
        "Maximum reinforcement tension",
        "sigma_s,max",
        "MPa",
        result.get("max_steel", 0.0),
        dependencies=deps,
    )
    max_conc_magnitude_value = abs(float(result.get("max_conc", 0.0)))
    max_conc_magnitude = calc.computed(
        "max-concrete-magnitude",
        title="Concrete stress magnitude",
        symbol="abs(sigma_c,max)",
        unit="MPa",
        value=max_conc_magnitude_value,
        symbolic="q_c = abs(sigma_c,max)",
        substituted=f"q_c = {_fmt(max_conc_magnitude_value)} MPa",
        dependencies=(max_conc,),
        operator="abs",
        source=None,
    )
    max_steel_magnitude_value = abs(float(result.get("max_steel", 0.0)))
    max_steel_magnitude = calc.computed(
        "max-reinforcement-magnitude",
        title="Reinforcement stress magnitude",
        symbol="abs(sigma_s,max)",
        unit="MPa",
        value=max_steel_magnitude_value,
        symbolic="q_s = abs(sigma_s,max)",
        substituted=f"q_s = {_fmt(max_steel_magnitude_value)} MPa",
        dependencies=(max_steel,),
        operator="abs",
        source=None,
    )
    governing = max(max_conc_magnitude_value, max_steel_magnitude_value)
    final = calc.computed(
        "governing-stress-magnitude",
        title="Governing reported stress magnitude",
        symbol="abs(sigma)_max",
        unit="MPa",
        value=governing,
        symbolic="abs(sigma)_max = max(q_c, q_s)",
        substituted=(
            f"abs(sigma)_max = max({_fmt(max_conc_magnitude_value)}, "
            f"{_fmt(max_steel_magnitude_value)}) = {_fmt(governing)} MPa"
        ),
        dependencies=(max_conc_magnitude, max_steel_magnitude),
        operator="max",
        source=None,
        role=ROLE_FINAL,
        assumption=(
            "Stress and crack-width outputs are numerical results without an "
            "acceptance limit."
        ),
    )
    calculations = [calc.finish(final)]

    if result.get("lambda_cr") is not None and not math.isfinite(
        float(result["lambda_cr"])
    ):
        calculations.append(
            _infinite_cracking_factor_calculation(
                inp,
                result,
                context=context,
                cid=cid,
            )
        )
        return calculations

    if result.get("lambda_cr") is not None and math.isfinite(
        float(result["lambda_cr"])
    ):
        threshold_record = result.get("cracking_threshold")
        fixed_prestress = (
            isinstance(threshold_record, Mapping)
            and threshold_record.get("method")
            == "fixed-prestress-decompression"
        )
        threshold = _Calc(
            calculation_id=f"elastic.{cid}.cracking-factor",
            coverage_id="CT-005",
            title="First-cracking load factor",
            method_id=(
                "sector-fixed-prestress-decompression"
                if fixed_prestress
                else "sector-linear-elastic-scaling"
            ),
            method_label=(
                "Sector fixed-prestress decompression procedure"
                if fixed_prestress
                else "Sector linear-elastic cracking-factor procedure"
            ),
            standard_based=False,
            context=context,
            assumptions=(
                (
                    "The tendon prestress is a fixed action; the external "
                    "action vector alone is scaled to first cracking.",
                )
                if fixed_prestress
                else ()
            ),
        )
        threshold_actions = _trace_elastic_actions(threshold, inp)
        threshold_geometry = _trace_section_geometry(threshold, inp)
        (
            threshold_es_reference,
            threshold_ns,
            threshold_nl,
        ) = _trace_elastic_reference_ratios(threshold, inp)
        threshold_material_assignments = _trace_elastic_material_laws(
            threshold,
            inp,
            es_reference_step=threshold_es_reference,
            ratio_steps=(
                (
                    "short",
                    threshold_ns,
                    float(inp.get("ns", 1.0)),
                ),
                (
                    "long",
                    threshold_nl,
                    float(inp.get("nl", 1.0)),
                ),
            ),
        )
        threshold_solver_dependencies = (
            *threshold_actions,
            threshold_geometry,
            threshold_ns,
            threshold_nl,
            *threshold_material_assignments,
        )
        fctm = threshold.input(
            "fctm",
            "User-selected mean tensile strength",
            "fctm",
            "MPa",
            result.get("fctm", inp.get("sls_fctm", 0.0)),
        )
        if fixed_prestress:
            fibre = threshold_record.get("governing_fibre_index")
            fibre_note = (
                f"Solver-selected governing concrete fibre index {int(fibre)}."
                if fibre is not None and not isinstance(fibre, bool)
                else "Solver-selected governing concrete fibre."
            )
            sigma_pre_value = _number(
                threshold_record.get("fixed_prestress_mpa"),
                "fixed_prestress_mpa",
            )
            sigma_ext_value = _number(
                threshold_record.get("external_tension_mpa"),
                "external_tension_mpa",
            )
            available_value = _number(
                threshold_record.get("available_tension_mpa"),
                "available_tension_mpa",
            )
            sigma_pre = threshold.project_value(
                "sigma-pre",
                "Fixed prestress stress at governing fibre",
                "sigma_pre,g",
                "MPa",
                sigma_pre_value,
                dependencies=(
                    threshold_geometry,
                    threshold_nl,
                    *threshold_material_assignments,
                ),
                assumption=fibre_note,
            )
            sigma_ext = threshold.project_value(
                "sigma-ext",
                "External-action tensile stress at governing fibre",
                "sigma_ext,g",
                "MPa",
                sigma_ext_value,
                dependencies=threshold_solver_dependencies,
                assumption=fibre_note,
            )
            available = threshold.computed(
                "available-tension",
                title="Tensile-stress increment available before cracking",
                symbol="Delta_sigma_cr,g",
                unit="MPa",
                value=available_value,
                symbolic="Delta_sigma_cr,g = fctm - sigma_pre,g",
                substituted=(
                    f"Delta_sigma_cr,g = "
                    f"{_fmt(_number(result.get('fctm', 0.0), 'fctm'))} "
                    f"- ({_fmt(sigma_pre_value)}) = "
                    f"{_fmt(available_value)} MPa"
                ),
                dependencies=(fctm, sigma_pre),
                operator="subtract",
                source=None,
            )
            raw_value = _number(
                threshold_record.get("raw_factor"),
                "raw_factor",
            )
            if raw_value < 0.0:
                raw_lam = threshold.computed(
                    "lambda-cr-raw",
                    title="Unclamped first-cracking factor",
                    symbol="lambda_cr,raw",
                    unit="1",
                    value=raw_value,
                    symbolic=(
                        "lambda_cr,raw = "
                        "Delta_sigma_cr,g / sigma_ext,g"
                    ),
                    substituted=(
                        f"lambda_cr,raw = {_fmt(available_value)} / "
                        f"{_fmt(sigma_ext_value)} = {_fmt(raw_value)}"
                    ),
                    dependencies=(available, sigma_ext),
                    operator="divide",
                    source=None,
                )
                zero = threshold.project_value(
                    "zero",
                    "Non-negative load-factor bound",
                    "0",
                    "1",
                    0.0,
                    role=ROLE_METHOD_VALUE,
                    assumption="Sector does not report a negative load factor.",
                )
                lam = threshold.computed(
                    "lambda-cr",
                    title="First-cracking load factor",
                    symbol="lambda_cr",
                    unit="1",
                    value=result["lambda_cr"],
                    symbolic="lambda_cr = max(0, lambda_cr,raw)",
                    substituted=(
                        f"lambda_cr = max(0, {_fmt(raw_value)}) = "
                        f"{_fmt(float(result['lambda_cr']))}"
                    ),
                    dependencies=(zero, raw_lam),
                    operator="max",
                    source=None,
                    role=ROLE_FINAL,
                )
            else:
                lam = threshold.computed(
                    "lambda-cr",
                    title="First-cracking load factor",
                    symbol="lambda_cr",
                    unit="1",
                    value=result["lambda_cr"],
                    symbolic=(
                        "lambda_cr = "
                        "Delta_sigma_cr,g / sigma_ext,g"
                    ),
                    substituted=(
                        f"lambda_cr = {_fmt(available_value)} / "
                        f"{_fmt(sigma_ext_value)} = "
                        f"{_fmt(float(result['lambda_cr']))}"
                    ),
                    dependencies=(available, sigma_ext),
                    operator="divide",
                    source=None,
                    role=ROLE_FINAL,
                )
        else:
            sigma_ct = threshold.project_value(
                "sigma-ct",
                "Stage-I extreme concrete tension",
                "sigma_ct",
                "MPa",
                result.get("sigma_ct", 0.0),
                dependencies=threshold_solver_dependencies,
                assumption=(
                    "Retained from the solver-owned Stage-I strain plane."
                ),
            )
            lam = threshold.computed(
                "lambda-cr",
                title="First-cracking load factor",
                symbol="lambda_cr",
                unit="1",
                value=result["lambda_cr"],
                symbolic="lambda_cr = fctm / sigma_ct",
                substituted=(
                    f"lambda_cr = "
                    f"{_fmt(_number(result.get('fctm', 0.0), 'fctm'))} "
                    f"/ {_fmt(_number(result.get('sigma_ct', 0.0), 'sigma_ct'))} "
                    f"= {_fmt(float(result['lambda_cr']))}"
                ),
                dependencies=(fctm, sigma_ct),
                operator="divide",
                source=None,
                role=ROLE_FINAL,
            )
        calculations.append(threshold.finish(lam))
    return calculations


def _crack_trace(
    inp: Mapping,
    record: Mapping,
    *,
    context: Mapping[str, Any],
    label: str,
) -> TraceCalculation:
    edition_2023 = str(record.get("edition") or "") == "2023"
    coarse = bool(record.get("coarse"))
    direct = bool(record.get("direct_tension"))
    dk = bool(inp.get("sls_dk_na")) and not edition_2023
    coverage_id = "CT-008" if edition_2023 else ("CT-007" if dk else "CT-006")
    if edition_2023:
        method_label = (
            "DS/EN 1992-1-1:2023 direct-tension crack width"
            if direct
            else "DS/EN 1992-1-1:2023 refined bending crack width"
        )
    elif dk:
        method_label = (
            "DS/EN 1992-1-1:2005 + DK NA:2024 coarse crack system"
            if coarse
            else "DS/EN 1992-1-1:2005 + DK NA:2024 fine crack system"
        )
    else:
        method_label = "DS/EN 1992-1-1:2005 ordinary crack width"
    calc = _Calc(
        calculation_id=f"crack.{_context_id(context)}.{_slug(label)}",
        coverage_id=coverage_id,
        title=f"Crack width - {label}",
        method_id=(
            "ec2-2023-direct-tension"
            if edition_2023 and direct
            else "ec2-2023-bending"
            if edition_2023
            else "ec2-2005-dkna-coarse"
            if dk and coarse
            else "ec2-2005-dkna-fine"
            if dk
            else "ec2-2005"
        ),
        method_label=method_label,
        standard_based=True,
        context={**context, "crack_case": label},
        assumptions=(
            "Crack width is a numerical output without an acceptance limit.",
        ),
    )

    sigma = calc.project_value(
        "sigma-s",
        "Governing Stage-II reinforcement stress",
        "sigma_s",
        "MPa",
        record["sigma_s"],
        assumption=(
            "Retained from the solver-owned cracked elastic section state; it "
            "is not a separately entered stress."
        ),
    )
    fctm = calc.input(
        "fctm",
        "Selected effective tensile strength",
        "fct,eff",
        "MPa",
        inp.get("sls_fctm", 0.0),
    )
    es = calc.input(
        "es",
        "Governing reinforcement elastic modulus",
        "Es",
        "MPa",
        record.get("es_mpa", 0.0),
    )
    kt = calc.method(
        "kt",
        "Load-duration factor",
        "kt",
        "1",
        record.get("kt", 0.0),
        CIT_CRACK_2023_STRAIN if edition_2023 else CIT_CRACK_2005_STRAIN,
    )
    alpha_e = calc.project_value(
        "alpha-e",
        "Effective modular ratio used by the section solve",
        "alpha_e",
        "1",
        record.get("alpha_e", 0.0),
        assumption=(
            "The modular ratio follows the selected elastic section state and "
            "element modulus."
        ),
    )
    as_eff = calc.project_value(
        "as-eff",
        "Mild reinforcement in effective tension area",
        "As,eff",
        "m2",
        record.get("as_eff", 0.0),
        assumption="Selected from the solver-owned effective tension area.",
    )
    ap_term_value = (
        record.get("ap_eff_weighted", 0.0)
        if edition_2023
        else record.get("ap_eff", 0.0)
    )
    ap_eff = calc.project_value(
        "ap-eff-term",
        (
            "Bond-weighted tendon area in effective tension area"
            if edition_2023
            else "Tendon area in effective tension area"
        ),
        "Ap,eff,term",
        "m2",
        ap_term_value,
        assumption=(
            "For 2023 this is sum(xi1 Ap); for the 2005 family it is the "
            "unweighted tendon area."
        ),
    )
    reinforcement_area_value = float(record.get("as_eff", 0.0)) + float(
        ap_term_value
    )
    reinforcement_area = calc.computed(
        "effective-reinforcement-area",
        title="Effective reinforcement numerator",
        symbol="As,eff + Ap,eff,term",
        unit="m2",
        value=reinforcement_area_value,
        symbolic="Aeff,reinf = As,eff + Ap,eff,term",
        substituted=(
            f"Aeff,reinf = {_fmt(record.get('as_eff', 0.0))} + "
            f"{_fmt(ap_term_value)} = {_fmt(reinforcement_area_value)} m2"
        ),
        dependencies=(as_eff, ap_eff),
        operator="add",
        source=(CIT_CRACK_2023_RHO if edition_2023 else CIT_CRACK_2005_STRAIN),
    )
    ac_eff = calc.project_value(
        "ac-eff",
        "Effective concrete tension area",
        "Ac,eff",
        "m2",
        record["ac_eff"],
        assumption=(
            "The geometric effective-area construction is retained by the "
            "serviceability solver."
        ),
    )
    rho = calc.computed(
        "rho-p-eff",
        title="Effective reinforcement ratio",
        symbol="rho_p,eff",
        unit="1",
        value=record["rho_p_eff"],
        symbolic="rho_p,eff = Aeff,reinf / Ac,eff",
        substituted=(
            f"rho_p,eff = {_fmt(reinforcement_area_value)} / "
            f"{_fmt(record['ac_eff'])} = {_fmt(record['rho_p_eff'])}"
        ),
        dependencies=(reinforcement_area, ac_eff),
        operator="divide",
        source=(CIT_CRACK_2023_RHO if edition_2023 else CIT_CRACK_2005_STRAIN),
    )
    alpha_rho_value = float(record.get("alpha_e", 0.0)) * float(
        record["rho_p_eff"]
    )
    alpha_rho = calc.computed(
        "alpha-rho",
        title="Modular-ratio reinforcement term",
        symbol="alpha_e rho_p,eff",
        unit="1",
        value=alpha_rho_value,
        symbolic="alpha_e rho_p,eff",
        substituted=(
            f"{_fmt(record.get('alpha_e', 0.0))} x "
            f"{_fmt(record['rho_p_eff'])} = {_fmt(alpha_rho_value)}"
        ),
        dependencies=(alpha_e, rho),
        operator="multiply",
        source=(CIT_CRACK_2023_STRAIN if edition_2023 else CIT_CRACK_2005_STRAIN),
    )
    one = calc.method(
        "one-strain",
        "Unity term",
        "1",
        "1",
        1.0,
        CIT_CRACK_2023_STRAIN if edition_2023 else CIT_CRACK_2005_STRAIN,
    )
    bracket_value = 1.0 + alpha_rho_value
    bracket = calc.computed(
        "strain-bracket",
        title="Mean-strain bracket",
        symbol="1 + alpha_e rho_p,eff",
        unit="1",
        value=bracket_value,
        symbolic="B = 1 + alpha_e rho_p,eff",
        substituted=f"B = 1 + {_fmt(alpha_rho_value)} = {_fmt(bracket_value)}",
        dependencies=(one, alpha_rho),
        operator="add",
        source=(CIT_CRACK_2023_STRAIN if edition_2023 else CIT_CRACK_2005_STRAIN),
    )
    fct_over_rho_value = float(inp.get("sls_fctm", 0.0)) / float(
        record["rho_p_eff"]
    )
    fct_over_rho = calc.computed(
        "fct-over-rho",
        title="Tension-stiffening strength term",
        symbol="fct,eff / rho_p,eff",
        unit="MPa",
        value=fct_over_rho_value,
        symbolic="Q = fct,eff / rho_p,eff",
        substituted=(
            f"Q = {_fmt(inp.get('sls_fctm', 0.0))} / "
            f"{_fmt(record['rho_p_eff'])} = {_fmt(fct_over_rho_value)} MPa"
        ),
        dependencies=(fctm, rho),
        operator="divide",
        source=(CIT_CRACK_2023_STRAIN if edition_2023 else CIT_CRACK_2005_STRAIN),
    )
    reduction_value = (
        float(record.get("kt", 0.0)) * fct_over_rho_value * bracket_value
    )
    reduction = calc.computed(
        "tension-stiffening-reduction",
        title="Tension-stiffening reduction",
        symbol="kt Q B",
        unit="MPa",
        value=reduction_value,
        symbolic="R = kt (fct,eff/rho_p,eff) (1 + alpha_e rho_p,eff)",
        substituted=(
            f"R = {_fmt(record.get('kt', 0.0))} x "
            f"{_fmt(fct_over_rho_value)} x {_fmt(bracket_value)} "
            f"= {_fmt(reduction_value)} MPa"
        ),
        dependencies=(kt, fct_over_rho, bracket),
        operator="product",
        source=(CIT_CRACK_2023_STRAIN if edition_2023 else CIT_CRACK_2005_STRAIN),
    )
    reduced_stress_value = float(record["sigma_s"]) - reduction_value
    reduced_stress = calc.computed(
        "reduced-stress",
        title="Reduced reinforcement stress",
        symbol="sigma_s - R",
        unit="MPa",
        value=reduced_stress_value,
        symbolic="sigma_red = sigma_s - R",
        substituted=(
            f"sigma_red = {_fmt(record['sigma_s'])} - "
            f"{_fmt(reduction_value)} = {_fmt(reduced_stress_value)} MPa"
        ),
        dependencies=(sigma, reduction),
        operator="subtract",
        source=(CIT_CRACK_2023_STRAIN if edition_2023 else CIT_CRACK_2005_STRAIN),
    )
    strain_candidate_value = reduced_stress_value / float(record["es_mpa"])
    strain_candidate = calc.computed(
        "strain-candidate",
        title="Mean-strain expression",
        symbol="eps_candidate",
        unit="1",
        value=strain_candidate_value,
        symbolic="eps_candidate = (sigma_s - R) / Es",
        substituted=(
            f"eps_candidate = {_fmt(reduced_stress_value)} / "
            f"{_fmt(record['es_mpa'])} = {_fmt(strain_candidate_value)}"
        ),
        dependencies=(reduced_stress, es),
        operator="divide",
        source=(CIT_CRACK_2023_STRAIN if edition_2023 else CIT_CRACK_2005_STRAIN),
    )
    floor_factor = calc.method(
        "strain-floor-factor",
        "Mean-strain lower-bound factor",
        "kfloor",
        "1",
        record.get("strain_floor_factor", 0.0),
        CIT_CRACK_2023_STRAIN if edition_2023 else CIT_CRACK_2005_STRAIN,
    )
    floor_stress_value = float(record["sigma_s"]) * float(
        record.get("strain_floor_factor", 0.0)
    )
    floor_stress = calc.computed(
        "floor-stress",
        title="Lower-bound stress numerator",
        symbol="kfloor sigma_s",
        unit="MPa",
        value=floor_stress_value,
        symbolic="sigma_floor = kfloor sigma_s",
        substituted=(
            f"sigma_floor = {_fmt(record.get('strain_floor_factor', 0.0))} x "
            f"{_fmt(record['sigma_s'])} = {_fmt(floor_stress_value)} MPa"
        ),
        dependencies=(floor_factor, sigma),
        operator="multiply",
        source=(CIT_CRACK_2023_STRAIN if edition_2023 else CIT_CRACK_2005_STRAIN),
    )
    floor_strain_value = floor_stress_value / float(record["es_mpa"])
    floor_strain = calc.computed(
        "floor-strain",
        title="Mean-strain lower bound",
        symbol="eps_floor",
        unit="1",
        value=floor_strain_value,
        symbolic="eps_floor = sigma_floor / Es",
        substituted=(
            f"eps_floor = {_fmt(floor_stress_value)} / "
            f"{_fmt(record['es_mpa'])} = {_fmt(floor_strain_value)}"
        ),
        dependencies=(floor_stress, es),
        operator="divide",
        source=(CIT_CRACK_2023_STRAIN if edition_2023 else CIT_CRACK_2005_STRAIN),
    )
    strain = calc.computed(
        "mean-strain-difference",
        title="Mean strain difference",
        symbol="eps_sm - eps_cm",
        unit="1",
        value=record["esm_ecm"],
        symbolic="eps_sm - eps_cm = max(eps_candidate, eps_floor)",
        substituted=(
            f"max({_fmt(strain_candidate_value)}, {_fmt(floor_strain_value)}) "
            f"= {_fmt(record['esm_ecm'])}"
        ),
        dependencies=(strain_candidate, floor_strain),
        operator="max",
        source=(CIT_CRACK_2023_STRAIN if edition_2023 else CIT_CRACK_2005_STRAIN),
    )

    cover = calc.project_value(
        "cover",
        "Governing element clear cover",
        "c",
        "mm",
        record["cover"],
        assumption=(
            "Derived from the current section boundary and the solver-selected "
            "governing reinforcement element."
        ),
    )
    phi = calc.project_value(
        "diameter",
        "Governing element equivalent diameter",
        "phi",
        "mm",
        record["phi"],
        assumption=(
            "Retained from the solver-selected reinforcement element or "
            "equivalent-diameter calculation."
        ),
    )
    k1 = calc.input(
        "bond-k1",
        "Selected bond coefficient",
        "k1",
        "1",
        record.get("bond_k1", 0.0),
    )

    if edition_2023:
        c15 = calc.method(
            "cover-coefficient",
            "Cover coefficient",
            "1.5",
            "1",
            1.5,
            CIT_CRACK_2023_SPACING,
        )
        cover_term_value = 1.5 * float(record["cover"])
        cover_term = calc.computed(
            "cover-term",
            title="Crack-spacing cover term",
            symbol="1.5 c",
            unit="mm",
            value=cover_term_value,
            symbolic="s_c = 1.5 c",
            substituted=(
                f"s_c = 1.5 x {_fmt(record['cover'])} "
                f"= {_fmt(cover_term_value)} mm"
            ),
            dependencies=(c15, cover),
            operator="multiply",
            source=CIT_CRACK_2023_SPACING,
        )
        kfl = calc.method(
            "kfl",
            "Flexural spacing coefficient",
            "kfl",
            "1",
            record.get("kfl", 1.0),
            CIT_CRACK_2023_SPACING,
        )
        kb = calc.method(
            "kb",
            "Bond spacing coefficient",
            "kb",
            "1",
            record.get("spacing_kb", 0.0),
            CIT_CRACK_2023_SPACING,
        )
        c72 = calc.method(
            "spacing-denominator",
            "Spacing denominator",
            "7.2",
            "1",
            7.2,
            CIT_CRACK_2023_SPACING,
        )
        kfl_kb_value = float(record.get("kfl", 1.0)) * float(
            record.get("spacing_kb", 0.0)
        )
        kfl_kb = calc.computed(
            "kfl-kb",
            title="Flexural and bond coefficient product",
            symbol="kfl kb",
            unit="1",
            value=kfl_kb_value,
            symbolic="K = kfl kb",
            substituted=f"K = {_fmt(kfl_kb_value)}",
            dependencies=(kfl, kb),
            operator="multiply",
            source=CIT_CRACK_2023_SPACING,
        )
        spacing_coeff_value = kfl_kb_value / 7.2
        spacing_coeff = calc.computed(
            "spacing-coefficient",
            title="Reinforcement spacing coefficient",
            symbol="kfl kb / 7.2",
            unit="1",
            value=spacing_coeff_value,
            symbolic="Kphi = kfl kb / 7.2",
            substituted=(
                f"Kphi = {_fmt(kfl_kb_value)} / 7.2 "
                f"= {_fmt(spacing_coeff_value)}"
            ),
            dependencies=(kfl_kb, c72),
            operator="divide",
            source=CIT_CRACK_2023_SPACING,
        )
        phi_over_rho_value = float(record["phi"]) / float(record["rho_p_eff"])
        phi_over_rho = calc.computed(
            "phi-over-rho",
            title="Diameter-to-ratio term",
            symbol="phi / rho_p,eff",
            unit="mm",
            value=phi_over_rho_value,
            symbolic="P = phi / rho_p,eff",
            substituted=(
                f"P = {_fmt(record['phi'])} / {_fmt(record['rho_p_eff'])} "
                f"= {_fmt(phi_over_rho_value)} mm"
            ),
            dependencies=(phi, rho),
            operator="divide",
            source=CIT_CRACK_2023_SPACING,
        )
        reinforcement_term_value = spacing_coeff_value * phi_over_rho_value
        reinforcement_term = calc.computed(
            "reinforcement-spacing-term",
            title="Reinforcement crack-spacing term",
            symbol="(kfl kb / 7.2) phi/rho_p,eff",
            unit="mm",
            value=reinforcement_term_value,
            symbolic="s_phi = Kphi P",
            substituted=(
                f"s_phi = {_fmt(spacing_coeff_value)} x "
                f"{_fmt(phi_over_rho_value)} = "
                f"{_fmt(reinforcement_term_value)} mm"
            ),
            dependencies=(spacing_coeff, phi_over_rho),
            operator="multiply",
            source=CIT_CRACK_2023_SPACING,
        )
        spacing_uncapped_value = cover_term_value + reinforcement_term_value
        spacing_uncapped = calc.computed(
            "spacing-uncapped",
            title="Uncapped calculated mean crack spacing",
            symbol="sr,m,uncapped",
            unit="mm",
            value=spacing_uncapped_value,
            symbolic="sr,m,uncapped = 1.5c + (kfl kb/7.2) phi/rho_p,eff",
            substituted=(
                f"sr,m,uncapped = {_fmt(cover_term_value)} + "
                f"{_fmt(reinforcement_term_value)} "
                f"= {_fmt(spacing_uncapped_value)} mm"
            ),
            dependencies=(cover_term, reinforcement_term),
            operator="add",
            source=CIT_CRACK_2023_SPACING,
        )
        if direct:
            spacing = calc.computed(
                "crack-spacing",
                title="Calculated mean crack spacing",
                symbol="sr,m,cal",
                unit="mm",
                value=record["sr_max"],
                symbolic="sr,m,cal = sr,m,uncapped",
                substituted=(
                    f"sr,m,cal = {_fmt(record['sr_max'])} mm"
                ),
                dependencies=(spacing_uncapped,),
                operator="identity",
                source=CIT_CRACK_2023_SPACING,
            )
        else:
            hx = calc.project_value(
                "h-minus-x",
                "Cracked tension-zone depth",
                "h-x",
                "mm",
                record.get("h_minus_x_mm", 0.0),
                assumption="Obtained from the solver-owned cracked strain plane.",
            )
            kw_for_cap = calc.method(
                "kw-cap",
                "Mean-to-calculated crack factor",
                "kw",
                "1",
                record.get("kw", 1.7),
                CIT_CRACK_2023_FINAL,
            )
            cap_coefficient_value = 1.3 / float(record.get("kw", 1.7))
            cap_coefficient = calc.project_value(
                "spacing-cap-coefficient",
                "Spacing-cap coefficient 1.3/kw",
                "1.3/kw",
                "1",
                cap_coefficient_value,
                dependencies=(kw_for_cap,),
                assumption=(
                    "The quotient is retained by the solver trace builder; kw is "
                    "the cited method value."
                ),
            )
            cap_value = cap_coefficient_value * float(
                record.get("h_minus_x_mm", 0.0)
            )
            cap = calc.computed(
                "spacing-cap",
                title="Geometric crack-spacing cap",
                symbol="sr,m,cap",
                unit="mm",
                value=cap_value,
                symbolic="sr,m,cap = (1.3/kw)(h-x)",
                substituted=(
                    f"sr,m,cap = {_fmt(cap_coefficient_value)} x "
                    f"{_fmt(record.get('h_minus_x_mm', 0.0))} "
                    f"= {_fmt(cap_value)} mm"
                ),
                dependencies=(cap_coefficient, hx),
                operator="multiply",
                source=CIT_CRACK_2023_SPACING,
            )
            spacing = calc.computed(
                "crack-spacing",
                title="Calculated mean crack spacing",
                symbol="sr,m,cal",
                unit="mm",
                value=record["sr_max"],
                symbolic="sr,m,cal = min(sr,m,uncapped, sr,m,cap)",
                substituted=(
                    f"sr,m,cal = min({_fmt(spacing_uncapped_value)}, "
                    f"{_fmt(cap_value)}) = {_fmt(record['sr_max'])} mm"
                ),
                dependencies=(spacing_uncapped, cap),
                operator="min",
                source=CIT_CRACK_2023_SPACING,
            )
        kw = calc.method(
            "kw",
            "Mean-to-calculated crack factor",
            "kw",
            "1",
            record.get("kw", 1.7),
            CIT_CRACK_2023_FINAL,
        )
        k1r = calc.method(
            "curvature-factor",
            "Curvature factor",
            "k1/r",
            "1",
            record.get("k1_r", 1.0),
            CIT_CRACK_2023_FINAL,
        )
        final_deps = (kw, k1r, spacing, strain)
        symbolic_final = "wk,cal = kw (k1/r) sr,m,cal (eps_sm - eps_cm)"
        source_final = CIT_CRACK_2023_FINAL
    else:
        if bool(record.get("sr_max_geometric")):
            hx = calc.project_value(
                "h-minus-x",
                "Cracked tension-zone depth",
                "h-x",
                "mm",
                record.get("h_minus_x_mm", 0.0),
                assumption="Obtained from the solver-owned cracked strain plane.",
            )
            factor_13 = calc.method(
                "geometric-spacing-factor",
                "Geometric spacing factor",
                "1.3",
                "1",
                1.3,
                CIT_CRACK_2005_GEOMETRIC,
            )
            spacing = calc.computed(
                "crack-spacing",
                title="Geometric maximum crack spacing",
                symbol="sr,max",
                unit="mm",
                value=record["sr_max"],
                symbolic="sr,max = 1.3(h-x)",
                substituted=(
                    f"sr,max = 1.3 x "
                    f"{_fmt(record.get('h_minus_x_mm', 0.0))} "
                    f"= {_fmt(record['sr_max'])} mm"
                ),
                dependencies=(factor_13, hx),
                operator="multiply",
                source=CIT_CRACK_2005_GEOMETRIC,
            )
        else:
            if dk:
                k3_base = calc.method(
                    "k3-base",
                    "Base cover coefficient",
                    "k3",
                    "1",
                    3.4,
                    CIT_CRACK_DK_SPACING,
                )
                c25 = calc.method(
                    "cover-reference",
                    "Cover reference",
                    "25",
                    "mm",
                    25.0,
                    CIT_CRACK_DK_SPACING,
                )
                cover_ratio_value = 25.0 / float(record["cover"])
                cover_ratio = calc.computed(
                    "cover-ratio",
                    title="Cover reference ratio",
                    symbol="25/c",
                    unit="1",
                    value=cover_ratio_value,
                    symbolic="r_c = 25/c",
                    substituted=(
                        f"r_c = 25 / {_fmt(record['cover'])} "
                        f"= {_fmt(cover_ratio_value)}"
                    ),
                    dependencies=(c25, cover),
                    operator="divide",
                    source=CIT_CRACK_DK_SPACING,
                )
                cover_power_value = cover_ratio_value ** (2.0 / 3.0)
                cover_power = calc.computed(
                    "cover-power",
                    title="Cover-dependent exponent",
                    symbol="(25/c)^(2/3)",
                    unit="1",
                    value=cover_power_value,
                    symbolic="p_c = (25/c)^(2/3)",
                    substituted=f"p_c = {_fmt(cover_power_value)}",
                    dependencies=(cover_ratio,),
                    operator="power",
                    exponent=2.0 / 3.0,
                    source=CIT_CRACK_DK_SPACING,
                )
                k3_value = float(record.get("spacing_k3", 0.0))
                k3 = calc.computed(
                    "k3-effective",
                    title="Cover-dependent coefficient",
                    symbol="k3,eff",
                    unit="1",
                    value=k3_value,
                    symbolic="k3,eff = 3.4(25/c)^(2/3)",
                    substituted=(
                        f"k3,eff = 3.4 x {_fmt(cover_power_value)} "
                        f"= {_fmt(k3_value)}"
                    ),
                    dependencies=(k3_base, cover_power),
                    operator="multiply",
                    source=CIT_CRACK_DK_SPACING,
                )
                spacing_source = CIT_CRACK_DK_SPACING
            else:
                k3 = calc.method(
                    "k3-effective",
                    "Cover coefficient",
                    "k3",
                    "1",
                    record.get("spacing_k3", 3.4),
                    CIT_CRACK_2005_SPACING,
                )
                k3_value = float(record.get("spacing_k3", 3.4))
                spacing_source = CIT_CRACK_2005_SPACING
            cover_term_value = k3_value * float(record["cover"])
            cover_term = calc.computed(
                "cover-term",
                title="Cover crack-spacing term",
                symbol="k3 c",
                unit="mm",
                value=cover_term_value,
                symbolic="s_c = k3 c",
                substituted=(
                    f"s_c = {_fmt(k3_value)} x {_fmt(record['cover'])} "
                    f"= {_fmt(cover_term_value)} mm"
                ),
                dependencies=(k3, cover),
                operator="multiply",
                source=spacing_source,
            )
            k2 = calc.method(
                "k2",
                "Strain-distribution coefficient",
                "k2",
                "1",
                record.get("spacing_k2", 0.0),
                CIT_CRACK_2005_SPACING,
            )
            k4 = calc.method(
                "k4",
                "Crack-spacing coefficient",
                "k4",
                "1",
                record.get("spacing_k4", 0.0),
                CIT_CRACK_2005_SPACING,
            )
            numerator_value = (
                float(record.get("bond_k1", 0.0))
                * float(record.get("spacing_k2", 0.0))
                * float(record.get("spacing_k4", 0.0))
                * float(record["phi"])
            )
            numerator = calc.computed(
                "reinforcement-spacing-numerator",
                title="Reinforcement spacing numerator",
                symbol="k1 k2 k4 phi",
                unit="mm",
                value=numerator_value,
                symbolic="Snum = k1 k2 k4 phi",
                substituted=(
                    f"Snum = {_fmt(record.get('bond_k1', 0.0))} x "
                    f"{_fmt(record.get('spacing_k2', 0.0))} x "
                    f"{_fmt(record.get('spacing_k4', 0.0))} x "
                    f"{_fmt(record['phi'])} = {_fmt(numerator_value)} mm"
                ),
                dependencies=(k1, k2, k4, phi),
                operator="product",
                source=CIT_CRACK_2005_SPACING,
            )
            reinforcement_term_value = numerator_value / float(
                record["rho_p_eff"]
            )
            reinforcement_term = calc.computed(
                "reinforcement-spacing-term",
                title="Reinforcement crack-spacing term",
                symbol="k1 k2 k4 phi / rho_p,eff",
                unit="mm",
                value=reinforcement_term_value,
                symbolic="s_phi = Snum / rho_p,eff",
                substituted=(
                    f"s_phi = {_fmt(numerator_value)} / "
                    f"{_fmt(record['rho_p_eff'])} "
                    f"= {_fmt(reinforcement_term_value)} mm"
                ),
                dependencies=(numerator, rho),
                operator="divide",
                source=CIT_CRACK_2005_SPACING,
            )
            spacing = calc.computed(
                "crack-spacing",
                title="Maximum crack spacing",
                symbol="sr,max",
                unit="mm",
                value=record["sr_max"],
                symbolic="sr,max = k3 c + k1 k2 k4 phi/rho_p,eff",
                substituted=(
                    f"sr,max = {_fmt(cover_term_value)} + "
                    f"{_fmt(reinforcement_term_value)} "
                    f"= {_fmt(record['sr_max'])} mm"
                ),
                dependencies=(cover_term, reinforcement_term),
                operator="add",
                source=CIT_CRACK_2005_SPACING,
            )
        wk_factor = calc.method(
            "wk-factor",
            "Fine/coarse crack-width factor",
            "kw,system",
            "1",
            record.get("wk_factor", 1.0),
            CIT_CRACK_DK_COARSE if coarse else CIT_CRACK_2005_FINAL,
        )
        final_deps = (wk_factor, spacing, strain)
        symbolic_final = "wk = kw,system sr,max (eps_sm - eps_cm)"
        source_final = CIT_CRACK_DK_COARSE if coarse else CIT_CRACK_2005_FINAL

    final_value = float(record["wk"])
    wk = calc.computed(
        "wk",
        title="Calculated crack width",
        symbol="wk",
        unit="mm",
        value=final_value,
        symbolic=symbolic_final,
        substituted=(
            f"wk = {' x '.join(_fmt(calc.steps[[s.step_id for s in calc.steps].index(dep)].evaluated_value) for dep in final_deps)} "
            f"= {_fmt(final_value)} mm"
        ),
        dependencies=final_deps,
        operator="product",
        source=source_final,
        role=ROLE_FINAL,
    )
    return calc.finish(wk)


def crack_calculations(
    inp: Mapping,
    out: Mapping,
    *,
    context: Mapping[str, Any],
) -> list[TraceCalculation]:
    elastic = out.get("elastic")
    if not isinstance(elastic, Mapping):
        return []
    fields = (
        ("crack", "Long-term fine"),
        ("crack_short", "Short-term fine"),
        ("crack_coarse", "Long-term coarse"),
        ("crack_short_coarse", "Short-term coarse"),
    )
    calculations = []
    for key, label in fields:
        record = elastic.get(key)
        if isinstance(record, Mapping):
            calculations.append(
                _crack_trace(inp, record, context=context, label=label)
            )
    return calculations


def _shear_no_links_2005(
    inp: Mapping,
    shear_out: Mapping,
    *,
    context: Mapping[str, Any],
) -> TraceCalculation:
    result = shear_out["res"]
    dk = "DK" in str(shear_out.get("method") or "").upper()
    calc = _Calc(
        calculation_id=f"shear.{_context_id(context)}.without-links",
        coverage_id="CT-009",
        title="Shear resistance without links",
        method_id="ec2-2005-dkna" if dk else "ec2-2005",
        method_label=(
            "DS/EN 1992-1-1:2005 + DK NA:2024"
            if dk
            else "DS/EN 1992-1-1:2005"
        ),
        standard_based=True,
        context=context,
    )
    fck = calc.input("fck", "Characteristic concrete strength", "fck", "MPa", shear_out["fck"])
    if shear_out.get("bw_user"):
        bw = calc.input(
            "bw",
            "Web width",
            "bw",
            "mm",
            shear_out["bw"],
            assumption="User-entered width retained.",
        )
    else:
        bw = calc.project_value(
            "bw",
            "Web width",
            "bw",
            "mm",
            shear_out["bw"],
            assumption=(
                "Derived minimum solid web width retained from section geometry."
            ),
        )
    depth = calc.project_value(
        "effective-depth",
        "Effective depth from compression face to tension steel",
        "d",
        "mm",
        shear_out["d"],
        assumption="Derived from the selected tension-face reinforcement.",
    )
    asl = calc.project_value(
        "asl",
        "Selected tension reinforcement area",
        "Asl",
        "mm2",
        shear_out["asl"],
        assumption=(
            "Solver-selected tension-side bars: "
            + ", ".join(str(item) for item in shear_out.get("asl_bar_ids") or ())
        ),
    )
    n_comp = calc.input(
        "n-ed-compression",
        "Net axial force, compression positive",
        "NEd,comp",
        "kN",
        shear_out.get("n_ed_comp", 0.0),
    )
    ac = calc.project_value(
        "ac",
        "Gross concrete area",
        "Ac",
        "m2",
        shear_out["ac"],
        assumption="Integrated from the validated section geometry.",
    )
    fcd = calc.project_value(
        "fcd",
        "Concrete design strength used",
        "fcd",
        "MPa",
        result["fcd"],
        assumption=(
            "Retained from the bundle's separately traced current concrete "
            "design-strength calculation."
        ),
    )
    gamma_c = calc.input(
        "gamma-c",
        "Final user-entered concrete factor",
        "gamma_c",
        "1",
        result["gamma_c"],
    )
    one = calc.method("one", "Unity", "1", "1", 1.0, CIT_SHEAR_2005)
    two = calc.method("two", "Upper k limit", "2", "1", 2.0, CIT_SHEAR_2005)
    d_ref = calc.method(
        "d-reference",
        "Reference depth",
        "200",
        "mm",
        200.0,
        CIT_SHEAR_2005,
    )
    depth_ratio_value = 200.0 / float(shear_out["d"])
    depth_ratio = calc.computed(
        "depth-ratio",
        title="Reference-depth ratio",
        symbol="200/d",
        unit="1",
        value=depth_ratio_value,
        symbolic="r_d = 200/d",
        substituted=(
            f"r_d = 200 / {_fmt(shear_out['d'])} "
            f"= {_fmt(depth_ratio_value)}"
        ),
        dependencies=(d_ref, depth),
        operator="divide",
        source=CIT_SHEAR_2005,
    )
    root_value = math.sqrt(depth_ratio_value)
    root = calc.computed(
        "depth-root",
        title="Square-root depth term",
        symbol="sqrt(200/d)",
        unit="1",
        value=root_value,
        symbolic="q_d = sqrt(200/d)",
        substituted=f"q_d = sqrt({_fmt(depth_ratio_value)}) = {_fmt(root_value)}",
        dependencies=(depth_ratio,),
        operator="sqrt",
        source=CIT_SHEAR_2005,
    )
    k_uncapped_value = 1.0 + root_value
    k_uncapped = calc.computed(
        "k-uncapped",
        title="Uncapped size factor",
        symbol="1 + sqrt(200/d)",
        unit="1",
        value=k_uncapped_value,
        symbolic="k_uncapped = 1 + sqrt(200/d)",
        substituted=f"k_uncapped = 1 + {_fmt(root_value)} = {_fmt(k_uncapped_value)}",
        dependencies=(one, root),
        operator="add",
        source=CIT_SHEAR_2005,
    )
    k = calc.computed(
        "k",
        title="Size factor",
        symbol="k",
        unit="1",
        value=result["k"],
        symbolic="k = min(1 + sqrt(200/d), 2.0)",
        substituted=(
            f"k = min({_fmt(k_uncapped_value)}, 2.0) "
            f"= {_fmt(result['k'])}"
        ),
        dependencies=(k_uncapped, two),
        operator="min",
        source=CIT_SHEAR_2005,
    )
    web_area_value = float(shear_out["bw"]) * float(shear_out["d"])
    web_area = calc.computed(
        "bw-d",
        title="Web effective area",
        symbol="bw d",
        unit="mm2",
        value=web_area_value,
        symbolic="A_v = bw d",
        substituted=(
            f"A_v = {_fmt(shear_out['bw'])} x {_fmt(shear_out['d'])} "
            f"= {_fmt(web_area_value)} mm2"
        ),
        dependencies=(bw, depth),
        operator="multiply",
        source=CIT_SHEAR_2005,
    )
    rho_raw_value = float(shear_out["asl"]) / web_area_value
    rho_raw = calc.computed(
        "rho-raw",
        title="Uncapped longitudinal reinforcement ratio",
        symbol="rho_l,raw",
        unit="1",
        value=rho_raw_value,
        symbolic="rho_l,raw = Asl/(bw d)",
        substituted=(
            f"rho_l,raw = {_fmt(shear_out['asl'])} / {_fmt(web_area_value)} "
            f"= {_fmt(rho_raw_value)}"
        ),
        dependencies=(asl, web_area),
        operator="divide",
        source=CIT_SHEAR_2005,
    )
    rho_cap = calc.method(
        "rho-cap",
        "Longitudinal ratio cap",
        "rho_l,max",
        "1",
        0.02,
        CIT_SHEAR_2005,
    )
    rho = calc.computed(
        "rho-l",
        title="Longitudinal reinforcement ratio",
        symbol="rho_l",
        unit="1",
        value=result["rho_l"],
        symbolic="rho_l = min(Asl/(bw d), 0.02)",
        substituted=(
            f"rho_l = min({_fmt(rho_raw_value)}, 0.02) "
            f"= {_fmt(result['rho_l'])}"
        ),
        dependencies=(rho_raw, rho_cap),
        operator="min",
        source=CIT_SHEAR_2005,
    )
    axial_stress_raw_value = float(shear_out.get("n_ed_comp", 0.0)) / float(
        shear_out["ac"]
    ) / 1000.0
    axial_stress_raw = calc.computed(
        "sigma-cp-raw",
        title="Mean axial concrete stress",
        symbol="sigma_cp,raw",
        unit="MPa",
        value=axial_stress_raw_value,
        symbolic="sigma_cp,raw = NEd,comp/Ac",
        substituted=(
            f"sigma_cp,raw = {_fmt(shear_out.get('n_ed_comp', 0.0))} / "
            f"{_fmt(shear_out['ac'])} / 1000 "
            f"= {_fmt(axial_stress_raw_value)} MPa"
        ),
        dependencies=(n_comp, ac),
        operator="divide",
        factor=0.001,
        source=CIT_SHEAR_2005,
    )
    sigma_cap_factor = calc.method(
        "sigma-cap-factor",
        "Axial stress cap factor",
        "0.2",
        "1",
        0.2,
        CIT_SHEAR_2005,
    )
    sigma_cap_value = 0.2 * float(result["fcd"])
    sigma_cap = calc.computed(
        "sigma-cap",
        title="Axial stress cap",
        symbol="0.2 fcd",
        unit="MPa",
        value=sigma_cap_value,
        symbolic="sigma_cp,max = 0.2 fcd",
        substituted=(
            f"sigma_cp,max = 0.2 x {_fmt(result['fcd'])} "
            f"= {_fmt(sigma_cap_value)} MPa"
        ),
        dependencies=(sigma_cap_factor, fcd),
        operator="multiply",
        source=CIT_SHEAR_2005,
    )
    sigma_cp = calc.computed(
        "sigma-cp",
        title="Axial compression term",
        symbol="sigma_cp",
        unit="MPa",
        value=result["sigma_cp"],
        symbolic="sigma_cp = min(sigma_cp,raw, 0.2 fcd)",
        substituted=(
            f"sigma_cp = min({_fmt(axial_stress_raw_value)}, "
            f"{_fmt(sigma_cap_value)}) = {_fmt(result['sigma_cp'])} MPa"
        ),
        dependencies=(axial_stress_raw, sigma_cap),
        operator="min",
        source=CIT_SHEAR_2005,
    )
    crdc_num = calc.method(
        "crdc-numerator",
        "Recommended shear coefficient numerator",
        "0.18",
        "1",
        0.18,
        CIT_SHEAR_2005,
    )
    crdc = calc.computed(
        "crdc",
        title="Design shear coefficient",
        symbol="C_Rd,c",
        unit="1",
        value=result["crd_c"],
        symbolic="C_Rd,c = 0.18/gamma_c",
        substituted=(
            f"C_Rd,c = 0.18 / {_fmt(result['gamma_c'])} "
            f"= {_fmt(result['crd_c'])}"
        ),
        dependencies=(crdc_num, gamma_c),
        operator="divide",
        source=CIT_SHEAR_2005,
    )
    hundred = calc.method(
        "hundred",
        "Reinforcement-ratio scale",
        "100",
        "1",
        100.0,
        CIT_SHEAR_2005,
    )
    cube_argument_value = (
        100.0 * float(result["rho_l"]) * float(shear_out["fck"])
    )
    cube_argument = calc.computed(
        "cube-argument",
        title="Concrete shear cube-root argument",
        symbol="100 rho_l fck",
        unit="MPa",
        value=cube_argument_value,
        symbolic="Q = 100 rho_l fck",
        substituted=(
            f"Q = 100 x {_fmt(result['rho_l'])} x "
            f"{_fmt(shear_out['fck'])} = {_fmt(cube_argument_value)} MPa"
        ),
        dependencies=(hundred, rho, fck),
        operator="product",
        source=CIT_SHEAR_2005,
    )
    cube_root_value = cube_argument_value ** (1.0 / 3.0)
    cube_root = calc.computed(
        "cube-root",
        title="Concrete shear cube-root term",
        symbol="Q^(1/3)",
        unit="MPa",
        value=cube_root_value,
        symbolic="q = (100 rho_l fck)^(1/3)",
        substituted=(
            f"q = ({_fmt(cube_argument_value)})^(1/3) "
            f"= {_fmt(cube_root_value)} MPa"
        ),
        dependencies=(cube_argument,),
        operator="cbrt",
        source=CIT_SHEAR_2005,
    )
    concrete_term_value = float(result["crd_c"]) * float(result["k"]) * cube_root_value
    concrete_term = calc.computed(
        "concrete-term",
        title="Concrete contribution",
        symbol="C_Rd,c k q",
        unit="MPa",
        value=concrete_term_value,
        symbolic="v_c = C_Rd,c k (100 rho_l fck)^(1/3)",
        substituted=(
            f"v_c = {_fmt(result['crd_c'])} x {_fmt(result['k'])} x "
            f"{_fmt(cube_root_value)} = {_fmt(concrete_term_value)} MPa"
        ),
        dependencies=(crdc, k, cube_root),
        operator="product",
        source=CIT_SHEAR_2005,
    )
    k1 = calc.method(
        "k1",
        "Axial stress coefficient",
        "k1",
        "1",
        result["k1"],
        CIT_SHEAR_2005,
    )
    axial_term_value = float(result["k1"]) * float(result["sigma_cp"])
    axial_term = calc.computed(
        "axial-term",
        title="Axial stress contribution",
        symbol="k1 sigma_cp",
        unit="MPa",
        value=axial_term_value,
        symbolic="v_N = k1 sigma_cp",
        substituted=(
            f"v_N = {_fmt(result['k1'])} x {_fmt(result['sigma_cp'])} "
            f"= {_fmt(axial_term_value)} MPa"
        ),
        dependencies=(k1, sigma_cp),
        operator="multiply",
        source=CIT_SHEAR_2005,
    )
    basic = calc.computed(
        "v-basic",
        title="Basic design shear stress",
        symbol="v_Rd,c,basic",
        unit="MPa",
        value=result["v_basic"],
        symbolic="v_Rd,c,basic = v_c + v_N",
        substituted=(
            f"v_Rd,c,basic = {_fmt(concrete_term_value)} + "
            f"{_fmt(axial_term_value)} = {_fmt(result['v_basic'])} MPa"
        ),
        dependencies=(concrete_term, axial_term),
        operator="add",
        source=CIT_SHEAR_2005,
    )
    k_power_value = float(result["k"]) ** 1.5
    k_power = calc.computed(
        "k-power",
        title="Minimum-shear size term",
        symbol="k^1.5",
        unit="1",
        value=k_power_value,
        symbolic="q_k = k^1.5",
        substituted=f"q_k = {_fmt(result['k'])}^1.5 = {_fmt(k_power_value)}",
        dependencies=(k,),
        operator="power",
        exponent=1.5,
        source=CIT_SHEAR_DK_VMIN if dk else CIT_SHEAR_2005,
    )
    fck_root_value = math.sqrt(float(shear_out["fck"]))
    fck_root = calc.computed(
        "fck-root",
        title="Concrete-strength square-root term",
        symbol="sqrt(fck)",
        unit="MPa",
        value=fck_root_value,
        symbolic="q_f = sqrt(fck)",
        substituted=(
            f"q_f = sqrt({_fmt(shear_out['fck'])}) "
            f"= {_fmt(fck_root_value)}"
        ),
        dependencies=(fck,),
        operator="sqrt",
        source=CIT_SHEAR_DK_VMIN if dk else CIT_SHEAR_2005,
    )
    if dk:
        vmin_num = calc.method(
            "vmin-numerator",
            "Danish minimum-shear coefficient numerator",
            "0.051",
            "1",
            0.051,
            CIT_SHEAR_DK_VMIN,
        )
        vmin_coefficient_value = 0.051 / float(result["gamma_c"])
        vmin_coefficient = calc.computed(
            "vmin-coefficient",
            title="Danish minimum-shear coefficient",
            symbol="0.051/gamma_c",
            unit="1",
            value=vmin_coefficient_value,
            symbolic="c_vmin = 0.051/gamma_c",
            substituted=(
                f"c_vmin = 0.051 / {_fmt(result['gamma_c'])} "
                f"= {_fmt(vmin_coefficient_value)}"
            ),
            dependencies=(vmin_num, gamma_c),
            operator="divide",
            source=CIT_SHEAR_DK_VMIN,
        )
        vmin_source = CIT_SHEAR_DK_VMIN
    else:
        vmin_coefficient_value = 0.035
        vmin_coefficient = calc.method(
            "vmin-coefficient",
            "Recommended minimum-shear coefficient",
            "0.035",
            "1",
            0.035,
            CIT_SHEAR_2005,
        )
        vmin_source = CIT_SHEAR_2005
    vmin = calc.computed(
        "vmin",
        title="Minimum design shear stress",
        symbol="vmin",
        unit="MPa",
        value=result["vmin"],
        symbolic="vmin = c_vmin k^1.5 sqrt(fck)",
        substituted=(
            f"vmin = {_fmt(vmin_coefficient_value)} x {_fmt(k_power_value)} "
            f"x {_fmt(fck_root_value)} = {_fmt(result['vmin'])} MPa"
        ),
        dependencies=(vmin_coefficient, k_power, fck_root),
        operator="product",
        source=vmin_source,
    )
    floor = calc.computed(
        "v-floor",
        title="Minimum shear-stress branch",
        symbol="v_Rd,c,min",
        unit="MPa",
        value=result["v_floor"],
        symbolic="v_Rd,c,min = vmin + k1 sigma_cp",
        substituted=(
            f"v_Rd,c,min = {_fmt(result['vmin'])} + "
            f"{_fmt(axial_term_value)} = {_fmt(result['v_floor'])} MPa"
        ),
        dependencies=(vmin, axial_term),
        operator="add",
        source=vmin_source,
    )
    zero = calc.method(
        "zero-stress",
        "Non-negative resistance floor",
        "0",
        "MPa",
        0.0,
        CIT_SHEAR_2005,
    )
    stress_value = max(
        float(result["v_basic"]), float(result["v_floor"]), 0.0
    )
    stress = calc.computed(
        "vrdc-stress",
        title="Governing design shear stress",
        symbol="v_Rd,c",
        unit="MPa",
        value=stress_value,
        symbolic="v_Rd,c = max(v_Rd,c,basic, v_Rd,c,min, 0)",
        substituted=(
            f"v_Rd,c = max({_fmt(result['v_basic'])}, "
            f"{_fmt(result['v_floor'])}, 0) = {_fmt(stress_value)} MPa"
        ),
        dependencies=(basic, floor, zero),
        operator="max",
        source=CIT_SHEAR_2005,
    )
    stress_area_value = stress_value * web_area_value
    stress_area = calc.computed(
        "stress-area",
        title="Shear stress times effective area",
        symbol="v_Rd,c bw d",
        unit="N",
        value=stress_area_value,
        symbolic="R_N = v_Rd,c bw d",
        substituted=(
            f"R_N = {_fmt(stress_value)} x {_fmt(web_area_value)} "
            f"= {_fmt(stress_area_value)} N"
        ),
        dependencies=(stress, web_area),
        operator="multiply",
        source=CIT_SHEAR_2005,
    )
    vrd = calc.computed(
        "vrd-c",
        title="Shear resistance without links",
        symbol="VRd,c",
        unit="kN",
        value=result["vrd_c"],
        symbolic="VRd,c = v_Rd,c bw d / 1000",
        substituted=(
            f"VRd,c = {_fmt(stress_area_value)} / 1000 "
            f"= {_fmt(result['vrd_c'])} kN"
        ),
        dependencies=(stress_area,),
        operator="identity",
        factor=0.001,
        source=CIT_SHEAR_2005,
    )
    demand = calc.input(
        "v-ed",
        "Applied shear demand",
        "VEd",
        "kN",
        shear_out["v_ed"],
    )
    final = _demand_resistance_final(
        calc,
        ratio_value=shear_out["util"],
        demand_step=demand,
        resistance_step=vrd,
        demand_value=shear_out["v_ed"],
        resistance_value=result["vrd_c"],
        ratio_step_id="eta-v",
        ratio_title="Shear demand-to-resistance utilisation",
        ratio_symbol="eta_V",
        ratio_symbolic="eta_V = VEd/VRd,c",
        ratio_substituted=(
            f"eta_V = {_fmt(shear_out['v_ed'])} / {_fmt(result['vrd_c'])} "
            f"= {_fmt(shear_out['util'])}"
        ),
        source=CIT_SHEAR_2005,
    )
    return calc.finish(final)


def _shear_no_links_2023(
    inp: Mapping,
    shear_out: Mapping,
    *,
    context: Mapping[str, Any],
) -> TraceCalculation:
    result = shear_out["res"]
    calc = _Calc(
        calculation_id=f"shear.{_context_id(context)}.without-links",
        coverage_id="CT-010",
        title="Strain-based shear resistance without links",
        method_id="ec2-2023",
        method_label="DS/EN 1992-1-1:2023 strain-based shear method",
        standard_based=True,
        context=context,
    )
    fck = calc.input("fck", "Characteristic concrete strength", "fck", "MPa", shear_out["fck"])
    if shear_out.get("bw_user"):
        bw = calc.input(
            "bw",
            "Web width",
            "bw",
            "mm",
            shear_out["bw"],
            assumption="User-entered width retained.",
        )
    else:
        bw = calc.project_value(
            "bw",
            "Web width",
            "bw",
            "mm",
            shear_out["bw"],
            assumption=(
                "Derived minimum solid web width retained from section geometry."
            ),
        )
    depth = calc.project_value(
        "effective-depth",
        "Effective depth",
        "d",
        "mm",
        shear_out["d"],
        assumption="Derived from the selected tension reinforcement.",
    )
    asl = calc.project_value(
        "asl",
        "Selected tension reinforcement area",
        "Asl",
        "mm2",
        shear_out["asl"],
    )
    fyd = calc.project_value(
        "fyd",
        "Flexural reinforcement design yield",
        "fyd",
        "MPa",
        result["fyd"],
        assumption=(
            "Retained from the bundle's separately traced current "
            "reinforcement design-strength calculation."
        ),
    )
    gamma_v = calc.input(
        "gamma-v",
        "Final shear partial factor",
        "gamma_v",
        "1",
        result["gamma_v"],
    )
    v_ed = calc.input("v-ed", "Applied shear demand", "VEd", "kN", result["v_ed"])
    m_ed = calc.input("m-ed", "Associated bending moment", "MEd", "kNm", result["m_ed"])
    n_ed = calc.input(
        "n-ed",
        "Axial force, tension positive",
        "NEd",
        "kN",
        result["n_ed_tension"],
    )
    web_area_value = float(shear_out["bw"]) * float(shear_out["d"])
    web_area = calc.computed(
        "bw-d",
        title="Web effective area",
        symbol="bw d",
        unit="mm2",
        value=web_area_value,
        symbolic="A_v = bw d",
        substituted=(
            f"A_v = {_fmt(shear_out['bw'])} x {_fmt(shear_out['d'])} "
            f"= {_fmt(web_area_value)} mm2"
        ),
        dependencies=(bw, depth),
        operator="multiply",
        source=CIT_SHEAR_2023,
    )
    rho_value = float(shear_out["asl"]) / web_area_value
    rho = calc.computed(
        "rho-l",
        title="Longitudinal reinforcement ratio",
        symbol="rho_l",
        unit="1",
        value=result["rho_l"],
        symbolic="rho_l = Asl/(bw d)",
        substituted=(
            f"rho_l = {_fmt(shear_out['asl'])} / {_fmt(web_area_value)} "
            f"= {_fmt(result['rho_l'])}"
        ),
        dependencies=(asl, web_area),
        operator="divide",
        source=CIT_SHEAR_2023,
    )
    z_factor = calc.method(
        "z-factor",
        "Nominal lever-arm factor",
        "0.9",
        "1",
        0.9,
        CIT_SHEAR_2023,
    )
    z = calc.computed(
        "z",
        title="Nominal shear lever arm",
        symbol="z",
        unit="mm",
        value=result["z"],
        symbolic="z = 0.9 d",
        substituted=(
            f"z = 0.9 x {_fmt(shear_out['d'])} = {_fmt(result['z'])} mm"
        ),
        dependencies=(z_factor, depth),
        operator="multiply",
        source=CIT_SHEAR_2023,
    )
    d_lower = calc.input(
        "d-lower",
        "Lower sieve size / entered aggregate parameter",
        "Dlower",
        "mm",
        inp.get("shear_dlower", 0.0),
    )
    if float(shear_out["fck"]) <= 60.0:
        aggregate_term = calc.computed(
            "aggregate-term",
            title="Strength-adjusted aggregate term",
            symbol="Dterm",
            unit="mm",
            value=inp.get("shear_dlower", 0.0),
            symbolic="Dterm = Dlower for fck <= 60 MPa",
            substituted=(
                f"Dterm = {_fmt(inp.get('shear_dlower', 0.0))} mm"
            ),
            dependencies=(d_lower,),
            operator="identity",
            source=CIT_SHEAR_2023,
        )
        aggregate_term_value = float(inp.get("shear_dlower", 0.0))
    else:
        sixty = calc.method(
            "strength-reference",
            "Aggregate strength reference",
            "60",
            "MPa",
            60.0,
            CIT_SHEAR_2023,
        )
        ratio_value = 60.0 / float(shear_out["fck"])
        ratio = calc.computed(
            "strength-ratio",
            title="Aggregate strength ratio",
            symbol="60/fck",
            unit="1",
            value=ratio_value,
            symbolic="r_f = 60/fck",
            substituted=f"r_f = 60/{_fmt(shear_out['fck'])} = {_fmt(ratio_value)}",
            dependencies=(sixty, fck),
            operator="divide",
            source=CIT_SHEAR_2023,
        )
        ratio_sq_value = ratio_value ** 2.0
        ratio_sq = calc.computed(
            "strength-ratio-squared",
            title="Squared aggregate strength ratio",
            symbol="(60/fck)^2",
            unit="1",
            value=ratio_sq_value,
            symbolic="r_f2 = (60/fck)^2",
            substituted=f"r_f2 = {_fmt(ratio_sq_value)}",
            dependencies=(ratio,),
            operator="power",
            exponent=2.0,
            source=CIT_SHEAR_2023,
        )
        aggregate_term_value = float(inp.get("shear_dlower", 0.0)) * ratio_sq_value
        aggregate_term = calc.computed(
            "aggregate-term",
            title="Strength-adjusted aggregate term",
            symbol="Dterm",
            unit="mm",
            value=aggregate_term_value,
            symbolic="Dterm = Dlower (60/fck)^2",
            substituted=(
                f"Dterm = {_fmt(inp.get('shear_dlower', 0.0))} x "
                f"{_fmt(ratio_sq_value)} = {_fmt(aggregate_term_value)} mm"
            ),
            dependencies=(d_lower, ratio_sq),
            operator="multiply",
            source=CIT_SHEAR_2023,
        )
    sixteen = calc.method(
        "aggregate-offset",
        "Aggregate offset",
        "16",
        "mm",
        16.0,
        CIT_SHEAR_2023,
    )
    ddg_raw_value = 16.0 + aggregate_term_value
    ddg_raw = calc.computed(
        "ddg-raw",
        title="Uncapped aggregate parameter",
        symbol="ddg,raw",
        unit="mm",
        value=ddg_raw_value,
        symbolic="ddg,raw = 16 + Dterm",
        substituted=(
            f"ddg,raw = 16 + {_fmt(aggregate_term_value)} "
            f"= {_fmt(ddg_raw_value)} mm"
        ),
        dependencies=(sixteen, aggregate_term),
        operator="add",
        source=CIT_SHEAR_2023,
    )
    forty = calc.method(
        "aggregate-cap",
        "Aggregate parameter cap",
        "40",
        "mm",
        40.0,
        CIT_SHEAR_2023,
    )
    ddg = calc.computed(
        "ddg",
        title="Aggregate parameter",
        symbol="ddg",
        unit="mm",
        value=result["ddg"],
        symbolic="ddg = min(16 + Dterm, 40)",
        substituted=(
            f"ddg = min({_fmt(ddg_raw_value)}, 40) = {_fmt(result['ddg'])} mm"
        ),
        dependencies=(ddg_raw, forty),
        operator="min",
        source=CIT_SHEAR_2023,
    )
    m_abs = calc.computed(
        "m-abs",
        title="Absolute associated moment",
        symbol="abs(MEd)",
        unit="kNm",
        value=abs(float(result["m_ed"])),
        symbolic="Mabs = abs(MEd)",
        substituted=f"Mabs = abs({_fmt(result['m_ed'])}) = {_fmt(abs(float(result['m_ed'])))} kNm",
        dependencies=(m_ed,),
        operator="abs",
        source=CIT_SHEAR_2023,
    )
    lever_from_actions_value = abs(float(result["m_ed"])) / float(
        result["v_ed"]
    ) * 1000.0
    lever_from_actions = calc.computed(
        "action-lever",
        title="Action shear-span ratio",
        symbol="abs(MEd/VEd)",
        unit="mm",
        value=lever_from_actions_value,
        symbolic="a_action = abs(MEd)/abs(VEd)",
        substituted=(
            f"a_action = {_fmt(abs(float(result['m_ed'])))} / "
            f"{_fmt(result['v_ed'])} x 1000 "
            f"= {_fmt(lever_from_actions_value)} mm"
        ),
        dependencies=(m_abs, v_ed),
        operator="divide",
        factor=1000.0,
        source=CIT_SHEAR_2023,
    )
    a_cs = calc.computed(
        "a-cs",
        title="Effective shear span",
        symbol="a_cs",
        unit="mm",
        value=result["a_cs"],
        symbolic="a_cs = max(abs(MEd/VEd), d)",
        substituted=(
            f"a_cs = max({_fmt(lever_from_actions_value)}, "
            f"{_fmt(shear_out['d'])}) = {_fmt(result['a_cs'])} mm"
        ),
        dependencies=(lever_from_actions, depth),
        operator="max",
        source=CIT_SHEAR_2023,
    )
    three = calc.method(
        "three",
        "Formula denominator coefficient",
        "3",
        "1",
        3.0,
        CIT_SHEAR_2023,
    )
    three_a_value = 3.0 * float(result["a_cs"])
    three_a = calc.computed(
        "three-a",
        title="Axial-factor denominator length",
        symbol="3 a_cs",
        unit="mm",
        value=three_a_value,
        symbolic="D_N = 3 a_cs",
        substituted=f"D_N = 3 x {_fmt(result['a_cs'])} = {_fmt(three_a_value)} mm",
        dependencies=(three, a_cs),
        operator="multiply",
        source=CIT_SHEAR_2023,
    )
    depth_ratio_axial_value = float(shear_out["d"]) / three_a_value
    depth_ratio_axial = calc.computed(
        "depth-over-three-a",
        title="Depth-to-shear-span term",
        symbol="d/(3a_cs)",
        unit="1",
        value=depth_ratio_axial_value,
        symbolic="q_N = d/(3a_cs)",
        substituted=(
            f"q_N = {_fmt(shear_out['d'])}/{_fmt(three_a_value)} "
            f"= {_fmt(depth_ratio_axial_value)}"
        ),
        dependencies=(depth, three_a),
        operator="divide",
        source=CIT_SHEAR_2023,
    )
    axial_ratio_value = float(result["n_ed_tension"]) / float(result["v_ed"])
    axial_ratio = calc.computed(
        "axial-shear-ratio",
        title="Axial-to-shear action ratio",
        symbol="NEd/abs(VEd)",
        unit="1",
        value=axial_ratio_value,
        symbolic="r_N = NEd/abs(VEd)",
        substituted=(
            f"r_N = {_fmt(result['n_ed_tension'])}/{_fmt(result['v_ed'])} "
            f"= {_fmt(axial_ratio_value)}"
        ),
        dependencies=(n_ed, v_ed),
        operator="divide",
        source=CIT_SHEAR_2023,
    )
    axial_term_value = axial_ratio_value * depth_ratio_axial_value
    axial_term = calc.computed(
        "axial-term",
        title="Axial shear factor increment",
        symbol="NEd/abs(VEd) d/(3a_cs)",
        unit="1",
        value=axial_term_value,
        symbolic="q_vp = r_N q_N",
        substituted=(
            f"q_vp = {_fmt(axial_ratio_value)} x "
            f"{_fmt(depth_ratio_axial_value)} = {_fmt(axial_term_value)}"
        ),
        dependencies=(axial_ratio, depth_ratio_axial),
        operator="multiply",
        source=CIT_SHEAR_2023,
    )
    one = calc.method("one", "Unity", "1", "1", 1.0, CIT_SHEAR_2023)
    kvp_raw_value = 1.0 + axial_term_value
    kvp_raw = calc.computed(
        "kvp-raw",
        title="Unfloored axial-action factor",
        symbol="k_vp,raw",
        unit="1",
        value=kvp_raw_value,
        symbolic="k_vp,raw = 1 + q_vp",
        substituted=f"k_vp,raw = 1 + {_fmt(axial_term_value)} = {_fmt(kvp_raw_value)}",
        dependencies=(one, axial_term),
        operator="add",
        source=CIT_SHEAR_2023,
    )
    kvp_floor = calc.method(
        "kvp-floor",
        "Axial-action factor floor",
        "0.1",
        "1",
        0.1,
        CIT_SHEAR_2023,
    )
    kvp = calc.computed(
        "kvp",
        title="Axial-action factor",
        symbol="k_vp",
        unit="1",
        value=result["k_vp"],
        symbolic="k_vp = max(k_vp,raw, 0.1)",
        substituted=(
            f"k_vp = max({_fmt(kvp_raw_value)}, 0.1) "
            f"= {_fmt(result['k_vp'])}"
        ),
        dependencies=(kvp_raw, kvp_floor),
        operator="max",
        source=CIT_SHEAR_2023,
    )
    d_kvp = calc.computed(
        "d-kvp",
        title="Axial-adjusted depth",
        symbol="k_vp d",
        unit="mm",
        value=result["d_kvp"],
        symbolic="d_v = k_vp d",
        substituted=(
            f"d_v = {_fmt(result['k_vp'])} x {_fmt(shear_out['d'])} "
            f"= {_fmt(result['d_kvp'])} mm"
        ),
        dependencies=(kvp, depth),
        operator="multiply",
        source=CIT_SHEAR_2023,
    )
    fck_over_fyd_value = float(shear_out["fck"]) / float(result["fyd"])
    fck_over_fyd = calc.computed(
        "fck-over-fyd",
        title="Concrete-to-steel strength ratio",
        symbol="fck/fyd",
        unit="1",
        value=fck_over_fyd_value,
        symbolic="r_f = fck/fyd",
        substituted=f"r_f = {_fmt(fck_over_fyd_value)}",
        dependencies=(fck, fyd),
        operator="divide",
        source=CIT_SHEAR_2023,
    )
    ddg_over_d_value = float(result["ddg"]) / float(shear_out["d"])
    ddg_over_d = calc.computed(
        "ddg-over-d",
        title="Aggregate-to-depth ratio",
        symbol="ddg/d",
        unit="1",
        value=ddg_over_d_value,
        symbolic="r_dg = ddg/d",
        substituted=f"r_dg = {_fmt(ddg_over_d_value)}",
        dependencies=(ddg, depth),
        operator="divide",
        source=CIT_SHEAR_2023,
    )
    min_root_arg_value = fck_over_fyd_value * ddg_over_d_value
    min_root_arg = calc.computed(
        "tau-min-root-argument",
        title="Minimum shear root argument",
        symbol="fck/fyd ddg/d",
        unit="1",
        value=min_root_arg_value,
        symbolic="q_min = (fck/fyd)(ddg/d)",
        substituted=f"q_min = {_fmt(min_root_arg_value)}",
        dependencies=(fck_over_fyd, ddg_over_d),
        operator="multiply",
        source=CIT_SHEAR_2023,
    )
    min_root_value = math.sqrt(min_root_arg_value)
    min_root = calc.computed(
        "tau-min-root",
        title="Minimum shear square-root term",
        symbol="sqrt(q_min)",
        unit="1",
        value=min_root_value,
        symbolic="q_min,root = sqrt(q_min)",
        substituted=f"q_min,root = {_fmt(min_root_value)}",
        dependencies=(min_root_arg,),
        operator="sqrt",
        source=CIT_SHEAR_2023,
    )
    eleven = calc.method(
        "eleven",
        "Minimum shear coefficient",
        "11",
        "MPa",
        11.0,
        CIT_SHEAR_2023,
    )
    eleven_over_gamma_value = 11.0 / float(result["gamma_v"])
    eleven_over_gamma = calc.computed(
        "eleven-over-gamma",
        title="Factored minimum shear coefficient",
        symbol="11/gamma_v",
        unit="MPa",
        value=eleven_over_gamma_value,
        symbolic="c_min = 11/gamma_v",
        substituted=f"c_min = 11/{_fmt(result['gamma_v'])} = {_fmt(eleven_over_gamma_value)} MPa",
        dependencies=(eleven, gamma_v),
        operator="divide",
        source=CIT_SHEAR_2023,
    )
    tau_min = calc.computed(
        "tau-min",
        title="Minimum design shear stress",
        symbol="tau_Rd,c,min",
        unit="MPa",
        value=result["tau_min"],
        symbolic="tau_Rd,c,min = (11/gamma_v) sqrt((fck/fyd)(ddg/d))",
        substituted=(
            f"tau_Rd,c,min = {_fmt(eleven_over_gamma_value)} x "
            f"{_fmt(min_root_value)} = {_fmt(result['tau_min'])} MPa"
        ),
        dependencies=(eleven_over_gamma, min_root),
        operator="multiply",
        source=CIT_SHEAR_2023,
    )
    hundred = calc.method(
        "hundred",
        "Reinforcement-ratio scale",
        "100",
        "1",
        100.0,
        CIT_SHEAR_2023,
    )
    basic_num_value = (
        100.0
        * float(result["rho_l"])
        * float(shear_out["fck"])
        * float(result["ddg"])
    )
    basic_num = calc.computed(
        "tau-basic-numerator",
        title="Basic shear cube-root numerator",
        symbol="100 rho_l fck ddg",
        unit="MPa",
        value=basic_num_value,
        symbolic="Q_basic = 100 rho_l fck ddg",
        substituted=f"Q_basic = {_fmt(basic_num_value)}",
        dependencies=(hundred, rho, fck, ddg),
        operator="product",
        source=CIT_SHEAR_2023,
    )
    basic_arg_value = basic_num_value / float(result["d_kvp"])
    basic_arg = calc.computed(
        "tau-basic-argument",
        title="Basic shear cube-root argument",
        symbol="100 rho_l fck ddg/(k_vp d)",
        unit="MPa",
        value=basic_arg_value,
        symbolic="q_basic = Q_basic/(k_vp d)",
        substituted=f"q_basic = {_fmt(basic_num_value)}/{_fmt(result['d_kvp'])} = {_fmt(basic_arg_value)}",
        dependencies=(basic_num, d_kvp),
        operator="divide",
        source=CIT_SHEAR_2023,
    )
    basic_root_value = basic_arg_value ** (1.0 / 3.0)
    basic_root = calc.computed(
        "tau-basic-root",
        title="Basic shear cube-root term",
        symbol="q_basic^(1/3)",
        unit="MPa",
        value=basic_root_value,
        symbolic="q_basic,root = q_basic^(1/3)",
        substituted=f"q_basic,root = {_fmt(basic_root_value)}",
        dependencies=(basic_arg,),
        operator="cbrt",
        source=CIT_SHEAR_2023,
    )
    c066 = calc.method(
        "coefficient-066",
        "Basic shear coefficient",
        "0.66",
        "1",
        0.66,
        CIT_SHEAR_2023,
    )
    c066_gamma_value = 0.66 / float(result["gamma_v"])
    c066_gamma = calc.computed(
        "coefficient-066-gamma",
        title="Factored basic shear coefficient",
        symbol="0.66/gamma_v",
        unit="1",
        value=c066_gamma_value,
        symbolic="c_basic = 0.66/gamma_v",
        substituted=f"c_basic = 0.66/{_fmt(result['gamma_v'])} = {_fmt(c066_gamma_value)}",
        dependencies=(c066, gamma_v),
        operator="divide",
        source=CIT_SHEAR_2023,
    )
    tau_basic = calc.computed(
        "tau-basic",
        title="Basic design shear stress",
        symbol="tau_Rd,c,basic",
        unit="MPa",
        value=result["tau_basic"],
        symbolic="tau_Rd,c,basic = (0.66/gamma_v) q_basic^(1/3)",
        substituted=(
            f"tau_Rd,c,basic = {_fmt(c066_gamma_value)} x "
            f"{_fmt(basic_root_value)} = {_fmt(result['tau_basic'])} MPa"
        ),
        dependencies=(c066_gamma, basic_root),
        operator="multiply",
        source=CIT_SHEAR_2023,
    )
    tau = calc.computed(
        "tau-rdc",
        title="Governing design shear stress",
        symbol="tau_Rd,c",
        unit="MPa",
        value=result["tau_rdc"],
        symbolic="tau_Rd,c = max(tau_Rd,c,basic, tau_Rd,c,min)",
        substituted=(
            f"tau_Rd,c = max({_fmt(result['tau_basic'])}, "
            f"{_fmt(result['tau_min'])}) = {_fmt(result['tau_rdc'])} MPa"
        ),
        dependencies=(tau_basic, tau_min),
        operator="max",
        source=CIT_SHEAR_2023,
    )
    area_z_value = float(shear_out["bw"]) * float(result["z"])
    area_z = calc.computed(
        "bw-z",
        title="Web lever-arm area",
        symbol="bw z",
        unit="mm2",
        value=area_z_value,
        symbolic="A_vz = bw z",
        substituted=f"A_vz = {_fmt(area_z_value)} mm2",
        dependencies=(bw, z),
        operator="multiply",
        source=CIT_SHEAR_2023,
    )
    force_n_value = float(result["tau_rdc"]) * area_z_value
    force_n = calc.computed(
        "resistance-newtons",
        title="Shear resistance before unit conversion",
        symbol="tau_Rd,c bw z",
        unit="N",
        value=force_n_value,
        symbolic="VRd,c,N = tau_Rd,c bw z",
        substituted=f"VRd,c,N = {_fmt(force_n_value)} N",
        dependencies=(tau, area_z),
        operator="multiply",
        source=CIT_SHEAR_2023,
    )
    vrd = calc.computed(
        "vrd-c",
        title="Shear resistance without links",
        symbol="VRd,c",
        unit="kN",
        value=result["vrd_c"],
        symbolic="VRd,c = tau_Rd,c bw z / 1000",
        substituted=f"VRd,c = {_fmt(force_n_value)}/1000 = {_fmt(result['vrd_c'])} kN",
        dependencies=(force_n,),
        operator="identity",
        factor=0.001,
        source=CIT_SHEAR_2023,
    )
    final = _demand_resistance_final(
        calc,
        ratio_value=shear_out["util"],
        demand_step=v_ed,
        resistance_step=vrd,
        demand_value=result["v_ed"],
        resistance_value=result["vrd_c"],
        ratio_step_id="eta-v",
        ratio_title="Shear demand-to-resistance utilisation",
        ratio_symbol="eta_V",
        ratio_symbolic="eta_V = VEd/VRd,c",
        ratio_substituted=(
            f"eta_V = {_fmt(result['v_ed'])}/{_fmt(result['vrd_c'])} "
            f"= {_fmt(shear_out['util'])}"
        ),
        source=CIT_SHEAR_2023,
    )
    return calc.finish(final)


def _shear_links_trace(
    inp: Mapping,
    shear_out: Mapping,
    *,
    context: Mapping[str, Any],
) -> TraceCalculation | None:
    links = shear_out.get("links")
    if not isinstance(links, Mapping) or not isinstance(links.get("res"), Mapping):
        return None
    result = links["res"]
    if not result.get("valid"):
        return None
    is_2023 = bool(links.get("model_2023") or result.get("model") == "2023")
    is_dk = not is_2023 and "DK" in str(shear_out.get("method") or "").upper()
    source = CIT_LINKS_2023 if is_2023 else CIT_LINKS_2005
    parameter_source = CIT_LINKS_DK if is_dk else source
    warnings = []
    if links.get("out_of_limits"):
        warnings.append(
            "The user-entered strut-angle range extends outside the selected "
            "method default; the actual positive finite range is retained."
        )
    calc = _Calc(
        calculation_id=f"shear.{_context_id(context)}.with-links",
        coverage_id="CT-012" if is_2023 else "CT-011",
        title="Shear resistance with links",
        method_id=(
            "ec2-2023"
            if is_2023
            else "ec2-2005-dkna"
            if is_dk
            else "ec2-2005"
        ),
        method_label=(
            "DS/EN 1992-1-1:2023 compression-field method"
            if is_2023
            else "DS/EN 1992-1-1:2005 + DK NA:2024 variable-strut method"
            if is_dk
            else "DS/EN 1992-1-1:2005 variable-strut method"
        ),
        standard_based=True,
        context=context,
        warnings=warnings,
        assumptions=(
            "The selected cot(theta) is the solver-owned member-angle result "
            "inside the retained user-entered range.",
        ),
    )
    demand = calc.input("v-ed", "Applied shear demand", "VEd", "kN", shear_out["v_ed"])
    if shear_out.get("bw_user"):
        bw = calc.input(
            "bw",
            "Web width",
            "bw",
            "mm",
            shear_out["bw"],
            assumption="User-entered width retained.",
        )
    else:
        bw = calc.project_value(
            "bw",
            "Web width",
            "bw",
            "mm",
            shear_out["bw"],
            assumption=(
                "Derived minimum solid web width retained from section geometry."
            ),
        )
    z = calc.project_value(
        "z",
        "Shear lever arm",
        "z",
        "mm",
        result["z"],
        assumption=str(links.get("z_source") or "solver-derived lever arm"),
    )
    dia = calc.input("link-diameter", "Link diameter", "phi_w", "mm", links["dia"])
    legs = calc.input("link-legs", "Effective link legs", "n_legs", "1", links["legs"])
    spacing = calc.input("link-spacing", "Longitudinal link spacing", "s", "mm", links["s"])
    asw = calc.project_value(
        "asw",
        "Link area crossing the shear plane",
        "Asw",
        "mm2",
        links["asw"],
        dependencies=(dia, legs),
        assumption="Circular link-leg areas summed by the geometry helper.",
    )
    asw_over_s = calc.computed(
        "asw-over-s",
        title="Transverse reinforcement per unit length",
        symbol="Asw/s",
        unit="mm2/mm",
        value=links["asw_over_s"],
        symbolic="Asw/s = Asw / s",
        substituted=(
            f"Asw/s = {_fmt(links['asw'])}/{_fmt(links['s'])} "
            f"= {_fmt(links['asw_over_s'])} mm2/mm"
        ),
        dependencies=(asw, spacing),
        operator="divide",
        source=source,
    )
    fywk = calc.input("fywk", "Characteristic link yield strength", "fywk", "MPa", links["fywk"])
    gamma_s = calc.input("gamma-s", "Final reinforcement partial factor", "gamma_s", "1", result["gamma_s"])
    fywd = calc.computed(
        "fywd",
        title="Link design yield strength",
        symbol="fywd",
        unit="MPa",
        value=result["fywd"],
        symbolic="fywd = fywk/gamma_s",
        substituted=(
            f"fywd = {_fmt(links['fywk'])}/{_fmt(result['gamma_s'])} "
            f"= {_fmt(result['fywd'])} MPa"
        ),
        dependencies=(fywk, gamma_s),
        operator="divide",
        source=source,
    )
    cot_min = calc.input(
        "cot-min",
        "Entered lower cot(theta)",
        "cot_min",
        "1",
        links["cot_min"],
        warning=warnings[0] if warnings else "",
    )
    cot_max = calc.input(
        "cot-max",
        "Entered upper cot(theta)",
        "cot_max",
        "1",
        links["cot_max"],
    )
    cot = calc.project_value(
        "cot-theta",
        "Selected common member strut angle",
        "cot(theta)",
        "1",
        result["cot"],
        dependencies=(cot_min, cot_max, demand),
        assumption=(
            "Sector selects the member angle by the stated resistance or "
            "governing-utilisation objective; no separate renderer optimisation."
        ),
    )
    one = calc.method("one", "Unity", "1", "1", 1.0, source)
    tan = calc.computed(
        "tan-theta",
        title="Strut-angle tangent",
        symbol="tan(theta)",
        unit="1",
        value=1.0 / float(result["cot"]),
        symbolic="tan(theta) = 1/cot(theta)",
        substituted=f"tan(theta) = 1/{_fmt(result['cot'])} = {_fmt(1.0 / float(result['cot']))}",
        dependencies=(one, cot),
        operator="divide",
        source=source,
    )
    denom_value = float(result["cot"]) + 1.0 / float(result["cot"])
    denom = calc.computed(
        "angle-denominator",
        title="Compression-field angle denominator",
        symbol="cot(theta)+tan(theta)",
        unit="1",
        value=denom_value,
        symbolic="q_theta = cot(theta) + tan(theta)",
        substituted=f"q_theta = {_fmt(denom_value)}",
        dependencies=(cot, tan),
        operator="add",
        source=source,
    )
    yielding_n_value = (
        float(links["asw_over_s"])
        * float(result["fywd"])
        * float(result["z"])
        * float(result["cot"])
    )
    yielding_n = calc.computed(
        "vrd-s-newtons",
        title="Link-yielding resistance before unit conversion",
        symbol="Asw/s z fywd cot(theta)",
        unit="N",
        value=yielding_n_value,
        symbolic="VRd,s,N = (Asw/s) z fywd cot(theta)",
        substituted=f"VRd,s,N = {_fmt(yielding_n_value)} N",
        dependencies=(asw_over_s, z, fywd, cot),
        operator="product",
        source=source,
    )
    vrd_s = calc.computed(
        "vrd-s",
        title="Link-yielding shear resistance",
        symbol="VRd,s",
        unit="kN",
        value=result["vrd_s"],
        symbolic="VRd,s = VRd,s,N/1000",
        substituted=f"VRd,s = {_fmt(yielding_n_value)}/1000 = {_fmt(result['vrd_s'])} kN",
        dependencies=(yielding_n,),
        operator="identity",
        factor=0.001,
        source=source,
    )
    fcd = calc.project_value(
        "fcd",
        "Concrete design strength used",
        "fcd",
        "MPa",
        result["fcd"],
        assumption=(
            "Retained from the bundle's separately traced current concrete "
            "design-strength calculation."
        ),
    )
    nu = calc.method(
        "nu",
        "Compression-field effectiveness factor",
        "nu",
        "1",
        result.get("nu", result.get("nu1", 0.0)),
        parameter_source,
    )
    alpha = calc.computed(
        "alpha-cw",
        title="Compression-chord coefficient",
        symbol="alpha_cw",
        unit="1",
        value=result.get("alpha_cw", 1.0),
        symbolic="alpha_cw = selected compression-field branch",
        substituted=f"alpha_cw = {_fmt(result.get('alpha_cw', 1.0))}",
        dependencies=(fcd,),
        operator="solver",
        source=source,
        assumption=(
            "The value is retained from the solver branch using the net axial "
            "compression state."
        ),
    )
    crushing_num_value = (
        float(result.get("alpha_cw", 1.0))
        * float(shear_out["bw"])
        * float(result["z"])
        * float(result.get("nu", result.get("nu1", 0.0)))
        * float(result["fcd"])
    )
    crushing_num = calc.computed(
        "vrd-max-numerator",
        title="Compression-field resistance numerator",
        symbol="alpha_cw bw z nu fcd",
        unit="N",
        value=crushing_num_value,
        symbolic="Rmax,N = alpha_cw bw z nu fcd",
        substituted=f"Rmax,N = {_fmt(crushing_num_value)} N",
        dependencies=(alpha, bw, z, nu, fcd),
        operator="product",
        source=source,
    )
    crushing_n_value = crushing_num_value / denom_value
    crushing_n = calc.computed(
        "vrd-max-newtons",
        title="Compression-field resistance before unit conversion",
        symbol="Rmax,N/[cot(theta)+tan(theta)]",
        unit="N",
        value=crushing_n_value,
        symbolic="VRd,max,N = Rmax,N/q_theta",
        substituted=f"VRd,max,N = {_fmt(crushing_num_value)}/{_fmt(denom_value)} = {_fmt(crushing_n_value)} N",
        dependencies=(crushing_num, denom),
        operator="divide",
        source=source,
    )
    vrd_max = calc.computed(
        "vrd-max",
        title="Compression-field shear resistance",
        symbol="VRd,max",
        unit="kN",
        value=result["vrd_max"],
        symbolic="VRd,max = VRd,max,N/1000",
        substituted=f"VRd,max = {_fmt(crushing_n_value)}/1000 = {_fmt(result['vrd_max'])} kN",
        dependencies=(crushing_n,),
        operator="identity",
        factor=0.001,
        source=source,
    )
    vrd = calc.computed(
        "vrd",
        title="Governing shear resistance with links",
        symbol="VRd",
        unit="kN",
        value=result["vrd"],
        symbolic="VRd = min(VRd,s, VRd,max)",
        substituted=(
            f"VRd = min({_fmt(result['vrd_s'])}, {_fmt(result['vrd_max'])}) "
            f"= {_fmt(result['vrd'])} kN"
        ),
        dependencies=(vrd_s, vrd_max),
        operator="min",
        source=source,
    )
    final = _demand_resistance_final(
        calc,
        ratio_value=links["util"],
        demand_step=demand,
        resistance_step=vrd,
        demand_value=shear_out["v_ed"],
        resistance_value=result["vrd"],
        ratio_step_id="eta-v",
        ratio_title="Shear demand-to-resistance utilisation",
        ratio_symbol="eta_V",
        ratio_symbolic="eta_V = VEd/VRd",
        ratio_substituted=(
            f"eta_V = {_fmt(shear_out['v_ed'])}/{_fmt(result['vrd'])} "
            f"= {_fmt(links['util'])}"
        ),
        source=source,
    )
    return calc.finish(final)


def _shear_records(
    shear_out: Mapping,
) -> list[tuple[dict[str, str], Mapping]]:
    directions = shear_out.get("directions")
    if isinstance(directions, Mapping):
        records = []
        for component, direction in directions.items():
            if not isinstance(direction, Mapping):
                continue
            candidates = list(direction.get("face_candidates") or ())
            if candidates:
                for index, candidate in enumerate(candidates, start=1):
                    face_shear = candidate.get("shear")
                    if isinstance(face_shear, Mapping):
                        records.append(
                            (
                                {
                                    "component": str(component),
                                    "face": (
                                        "negative"
                                        if candidate.get("tension_low")
                                        else "positive"
                                    ),
                                    "candidate": str(index),
                                },
                                face_shear,
                            )
                        )
            else:
                records.append(({"component": str(component)}, direction))
        return records
    candidates = list(shear_out.get("face_candidates") or ())
    if candidates:
        records = []
        for index, candidate in enumerate(candidates, start=1):
            face_shear = candidate.get("shear")
            if isinstance(face_shear, Mapping):
                records.append(
                    (
                        {
                            "component": str(shear_out.get("component") or ""),
                            "face": (
                                "negative"
                                if candidate.get("tension_low")
                                else "positive"
                            ),
                            "candidate": str(index),
                        },
                        face_shear,
                    )
                )
        return records
    return [({"component": str(shear_out.get("component") or "")}, shear_out)]


def shear_calculations(
    inp: Mapping,
    out: Mapping,
    *,
    context: Mapping[str, Any],
) -> list[TraceCalculation]:
    shear_out = out.get("shear")
    if not isinstance(shear_out, Mapping):
        return []
    calculations = []
    for extra, record in _shear_records(shear_out):
        result = record.get("res")
        if not isinstance(result, Mapping) or not result.get("valid"):
            continue
        record_context = {**context, **extra}
        if result.get("model") == "2023" or record.get("model_2023"):
            calculations.append(
                _shear_no_links_2023(inp, record, context=record_context)
            )
        else:
            calculations.append(
                _shear_no_links_2005(inp, record, context=record_context)
            )
        links = _shear_links_trace(inp, record, context=record_context)
        if links is not None:
            calculations.append(links)
    return calculations


def _torsion_tube_trace(
    inp: Mapping,
    torsion_out: Mapping,
    tube_result: Mapping,
    *,
    context: Mapping[str, Any],
    tube_label: str,
) -> TraceCalculation:
    dk = "DK" in str(torsion_out.get("method") or "").upper()
    warnings = []
    if torsion_out.get("out_of_limits"):
        warnings.append(
            "The entered cot(theta) range extends outside the selected method "
            "default; the actual positive finite values are retained."
        )
    calc = _Calc(
        calculation_id=f"torsion.{_context_id(context)}.{_slug(tube_label)}",
        coverage_id="CT-013",
        title=f"Thin-walled tube torsion - {tube_label}",
        method_id="ec2-2005-dkna" if dk else "ec2-2005",
        method_label=(
            "DS/EN 1992-1-1:2005 + DK NA:2024 thin-walled tube"
            if dk
            else "DS/EN 1992-1-1:2005 thin-walled tube"
        ),
        standard_based=True,
        context={**context, "tube": tube_label},
        warnings=warnings,
    )
    tube = tube_result["tube"]
    t_ed_total = calc.input(
        "t-ed-total",
        "Applied member torque",
        "TEd,total",
        "kNm",
        inp.get("torsion_T", torsion_out["t_ed"]),
    )
    t_ed = calc.project_value(
        "t-ed",
        "Torque assigned to tube",
        "TEd",
        "kNm",
        tube_result["t_ed"],
        dependencies=(t_ed_total,),
        assumption=(
            "For a subdivided section the solver distributes the entered member "
            "torque by the retained torsional stiffnesses; for a single tube the "
            "assigned torque equals the entered member torque."
        ),
    )
    ak = calc.project_value(
        "ak",
        "Area enclosed by wall centre-line",
        "Ak",
        "m2",
        tube["Ak"],
        assumption="Computed from the solver-owned inward-offset tube geometry.",
    )
    if tube.get("tef_user"):
        tef = calc.input(
            "tef",
            "Explicit effective wall thickness",
            "tef",
            "mm",
            tube["tef"],
            assumption=(
                "The positive finite custom thickness is retained as entered."
            ),
        )
    else:
        tef = calc.project_value(
            "tef",
            "Section-derived effective wall thickness",
            "tef",
            "mm",
            tube["tef"],
            dependencies=(ak,),
            assumption=(
                "Derived by the solver from A/u and capped at the physical wall "
                "thickness where applicable."
            ),
        )
    uk = calc.project_value(
        "uk",
        "Wall centre-line perimeter",
        "uk",
        "m",
        tube["uk"],
        dependencies=(ak,),
        assumption="Computed from the same solver-owned tube geometry.",
    )
    link_diameter = calc.input(
        "link-diameter",
        "Closed-link diameter",
        "phi_w",
        "mm",
        torsion_out.get("dia", inp.get("shear_link_dia", 0.0)),
    )
    link_spacing = calc.input(
        "link-spacing",
        "Closed-link longitudinal spacing",
        "s",
        "mm",
        torsion_out.get("s", inp.get("shear_link_s", 0.0)),
    )
    asw_value = math.pi * float(
        torsion_out.get("dia", inp.get("shear_link_dia", 0.0))
    ) ** 2.0 / 4.0
    asw = calc.computed(
        "asw",
        title="Area of one closed-link leg",
        symbol="Asw",
        unit="mm2",
        value=asw_value,
        symbolic="Asw = pi phi_w^2 / 4",
        substituted=(
            f"Asw = pi x {_fmt(torsion_out.get('dia', inp.get('shear_link_dia', 0.0)))}^2 "
            f"/ 4 = {_fmt(asw_value)} mm2"
        ),
        dependencies=(link_diameter,),
        operator="power",
        exponent=2.0,
        factor=math.pi / 4.0,
        source=None,
    )
    asw_over_s = calc.computed(
        "asw-over-s",
        title="Closed transverse reinforcement per unit length",
        symbol="Asw/s",
        unit="mm2/mm",
        value=torsion_out["asw_over_s"],
        symbolic="Asw/s = Asw / s",
        substituted=(
            f"Asw/s = {_fmt(asw_value)} / "
            f"{_fmt(torsion_out.get('s', inp.get('shear_link_s', 0.0)))} "
            f"= {_fmt(torsion_out['asw_over_s'])} mm2/mm"
        ),
        dependencies=(asw, link_spacing),
        operator="divide",
        source=None,
    )
    fywk = calc.input(
        "fywk",
        "Characteristic closed-link yield strength",
        "fywk",
        "MPa",
        inp.get("shear_fywk", 0.0),
    )
    gamma_s = calc.input(
        "gamma-s",
        "Final reinforcement partial factor",
        "gamma_s",
        "1",
        torsion_out.get("gamma_s", getattr(inp.get("steel"), "gamma_y", 0.0)),
    )
    fywd = calc.computed(
        "fywd",
        title="Transverse reinforcement design yield",
        symbol="fywd",
        unit="MPa",
        value=torsion_out["fywd"],
        symbolic="fywd = fywk / gamma_s",
        substituted=(
            f"fywd = {_fmt(inp.get('shear_fywk', 0.0))} / "
            f"{_fmt(torsion_out.get('gamma_s', getattr(inp.get('steel'), 'gamma_y', 0.0)))} "
            f"= {_fmt(torsion_out['fywd'])} MPa"
        ),
        dependencies=(fywk, gamma_s),
        operator="divide",
        source=CIT_FYD_2005,
    )
    cot = calc.project_value(
        "cot-theta",
        "Selected common member strut angle",
        "cot(theta)",
        "1",
        tube_result["cot"],
        dependencies=(t_ed,),
        assumption=(
            "The common angle is retained from the solver member-angle selection."
        ),
    )
    two = calc.method("two", "Tube equilibrium factor", "2", "1", 2.0, CIT_TORSION)
    trds_value = (
        float(torsion_out["asw_over_s"])
        * 2.0
        * float(tube["Ak"])
        * float(torsion_out["fywd"])
        * float(tube_result["cot"])
    )
    trds = calc.computed(
        "trd-s",
        title="Closed-link torsion resistance",
        symbol="TRd,s",
        unit="kNm",
        value=tube_result["trd_s"],
        symbolic="TRd,s = (Asw/s) 2 Ak fywd cot(theta)",
        substituted=(
            f"TRd,s = {_fmt(torsion_out['asw_over_s'])} x 2 x "
            f"{_fmt(tube['Ak'])} x {_fmt(torsion_out['fywd'])} x "
            f"{_fmt(tube_result['cot'])} = {_fmt(trds_value)} kNm"
        ),
        dependencies=(asw_over_s, two, ak, fywd, cot),
        operator="product",
        source=CIT_TORSION,
    )
    cot_squared_value = float(tube_result["cot"]) ** 2.0
    cot_squared = calc.computed(
        "cot-squared",
        title="Squared cotangent",
        symbol="cot(theta)^2",
        unit="1",
        value=cot_squared_value,
        symbolic="q_cot = cot(theta)^2",
        substituted=f"q_cot = {_fmt(cot_squared_value)}",
        dependencies=(cot,),
        operator="power",
        exponent=2.0,
        source=CIT_TORSION,
    )
    one = calc.method("one", "Unity", "1", "1", 1.0, CIT_TORSION)
    trig_denom_value = 1.0 + cot_squared_value
    trig_denom = calc.computed(
        "trig-denominator",
        title="Trigonometric denominator",
        symbol="1+cot(theta)^2",
        unit="1",
        value=trig_denom_value,
        symbolic="D_theta = 1 + cot(theta)^2",
        substituted=f"D_theta = 1 + {_fmt(cot_squared_value)} = {_fmt(trig_denom_value)}",
        dependencies=(one, cot_squared),
        operator="add",
        source=CIT_TORSION,
    )
    sin_cos_value = float(tube_result["cot"]) / trig_denom_value
    sin_cos = calc.computed(
        "sin-cos",
        title="sin(theta) cos(theta) term",
        symbol="sin(theta)cos(theta)",
        unit="1",
        value=sin_cos_value,
        symbolic="sin(theta)cos(theta) = cot(theta)/(1+cot(theta)^2)",
        substituted=(
            f"sin(theta)cos(theta) = {_fmt(tube_result['cot'])}/"
            f"{_fmt(trig_denom_value)} = {_fmt(sin_cos_value)}"
        ),
        dependencies=(cot, trig_denom),
        operator="divide",
        source=CIT_TORSION,
    )
    nu = calc.method(
        "nu",
        "Concrete strut effectiveness factor",
        "nu",
        "1",
        tube_result["nu"],
        CIT_TORSION_DK if dk else CIT_TORSION,
    )
    fcd = calc.project_value(
        "fcd",
        "Concrete design strength used",
        "fcd",
        "MPa",
        torsion_out["fcd"],
        assumption=(
            "Retained from the separately traced material design-strength "
            "calculation."
        ),
    )
    sigma_cp = calc.project_value(
        "sigma-cp",
        "Mean axial concrete compression used by the method",
        "sigma_cp",
        "MPa",
        torsion_out.get("sigma_cp", 0.0),
        dependencies=(fcd,),
        assumption=(
            "Computed from the current axial action, prestress and gross concrete "
            "area; compression is positive in this method."
        ),
    )
    alpha = calc.computed(
        "alpha-cw",
        title="Compression-chord coefficient",
        symbol="alpha_cw",
        unit="1",
        value=torsion_out["alpha_cw"],
        symbolic="alpha_cw = clause 6.2.3 compression-field branch",
        substituted=f"alpha_cw = {_fmt(torsion_out['alpha_cw'])}",
        dependencies=(sigma_cp, fcd),
        operator="solver",
        source=CIT_TORSION,
        assumption=(
            "The piecewise clause branch is evaluated in the solver and retained "
            "without renderer recomputation."
        ),
    )
    trdmax_value = (
        2.0
        * float(tube_result["nu"])
        * float(torsion_out["alpha_cw"])
        * float(torsion_out["fcd"])
        * float(tube["Ak"])
        * float(tube["tef"])
        * sin_cos_value
    )
    trdmax = calc.computed(
        "trd-max",
        title="Concrete-strut torsion resistance",
        symbol="TRd,max",
        unit="kNm",
        value=tube_result["trd_max"],
        symbolic="TRd,max = 2 nu alpha_cw fcd Ak tef sin(theta)cos(theta)",
        substituted=(
            f"TRd,max = 2 x {_fmt(tube_result['nu'])} x "
            f"{_fmt(torsion_out['alpha_cw'])} x {_fmt(torsion_out['fcd'])} "
            f"x {_fmt(tube['Ak'])} x {_fmt(tube['tef'])} x "
            f"{_fmt(sin_cos_value)} = {_fmt(trdmax_value)} kNm"
        ),
        dependencies=(two, nu, alpha, fcd, ak, tef, sin_cos),
        operator="product",
        source=CIT_TORSION,
    )
    trd = calc.computed(
        "trd",
        title="Governing torsion resistance",
        symbol="TRd",
        unit="kNm",
        value=tube_result["trd"],
        symbolic="TRd = min(TRd,s, TRd,max)",
        substituted=(
            f"TRd = min({_fmt(tube_result['trd_s'])}, "
            f"{_fmt(tube_result['trd_max'])}) = {_fmt(tube_result['trd'])} kNm"
        ),
        dependencies=(trds, trdmax),
        operator="min",
        source=CIT_TORSION,
    )
    fctk_005 = calc.method(
        "fctk-005",
        "Selected characteristic lower tensile strength",
        "fctk,0.05",
        "MPa",
        torsion_out.get("fctk_005", 0.0),
        CIT_FCTK_005_2005,
    )
    gamma_ct = calc.input(
        "gamma-ct",
        "Final user-entered tensile-strength factor",
        "gamma_ct",
        "1",
        torsion_out.get("gamma_ct", 0.0),
    )
    fctd = calc.computed(
        "fctd",
        title="Concrete design tensile strength used",
        symbol="fctd",
        unit="MPa",
        value=torsion_out["fctd"],
        symbolic="fctd = fctk,0.05 / gamma_ct",
        substituted=(
            f"fctd = {_fmt(torsion_out.get('fctk_005', 0.0))} / "
            f"{_fmt(torsion_out.get('gamma_ct', 0.0))} "
            f"= {_fmt(torsion_out['fctd'])} MPa"
        ),
        dependencies=(fctk_005, gamma_ct),
        operator="divide",
        source=CIT_FCTD_2005,
    )
    trdc_value = (
        2.0
        * float(tube["Ak"])
        * float(tube["tef"])
        * float(torsion_out["fctd"])
    )
    calc.computed(
        "trd-c",
        title="Torsional cracking resistance",
        symbol="TRd,c",
        unit="kNm",
        value=tube_result["trd_c"],
        symbolic="TRd,c = 2 Ak tef fctd",
        substituted=(
            f"TRd,c = 2 x {_fmt(tube['Ak'])} x {_fmt(tube['tef'])} x "
            f"{_fmt(torsion_out['fctd'])} = {_fmt(trdc_value)} kNm"
        ),
        dependencies=(two, ak, tef, fctd),
        operator="product",
        source=CIT_TORSION,
    )
    fyk_long = calc.input(
        "fyk-long",
        "Characteristic longitudinal reinforcement yield",
        "fyk,long",
        "MPa",
        getattr(inp.get("steel"), "fytk", 0.0),
    )
    fyd_long = calc.computed(
        "fyd-long",
        title="Longitudinal reinforcement design yield",
        symbol="fyd,long",
        unit="MPa",
        value=torsion_out["fyd_long"],
        symbolic="fyd,long = fyk,long / gamma_s",
        substituted=(
            f"fyd,long = {_fmt(getattr(inp.get('steel'), 'fytk', 0.0))} / "
            f"{_fmt(torsion_out.get('gamma_s', getattr(inp.get('steel'), 'gamma_y', 0.0)))} "
            f"= {_fmt(torsion_out['fyd_long'])} MPa"
        ),
        dependencies=(fyk_long, gamma_s),
        operator="divide",
        source=CIT_FYD_2005,
    )
    asl_num_value = (
        float(tube_result["t_ed"])
        * float(tube["uk"])
        * float(tube_result["cot"])
    )
    asl_num = calc.computed(
        "asl-numerator",
        title="Longitudinal reinforcement numerator",
        symbol="TEd uk cot(theta)",
        unit="kNm",
        value=asl_num_value,
        symbolic="Q_Asl = TEd uk cot(theta)",
        substituted=f"Q_Asl = {_fmt(asl_num_value)}",
        dependencies=(t_ed, uk, cot),
        operator="product",
        source=CIT_TORSION,
    )
    asl_den_value = 2.0 * float(tube["Ak"]) * float(torsion_out["fyd_long"])
    asl_den = calc.computed(
        "asl-denominator",
        title="Longitudinal reinforcement denominator",
        symbol="2 Ak fyd",
        unit="kN",
        value=asl_den_value,
        symbolic="D_Asl = 2 Ak fyd",
        substituted=f"D_Asl = {_fmt(asl_den_value)}",
        dependencies=(two, ak, fyd_long),
        operator="product",
        source=CIT_TORSION,
    )
    calc.computed(
        "asl-required",
        title="Required longitudinal torsion reinforcement",
        symbol="sum Asl",
        unit="mm2",
        value=tube_result["asl_req"],
        symbolic="sum Asl = TEd uk cot(theta)/(2 Ak fyd) x 1000",
        substituted=(
            f"sum Asl = {_fmt(asl_num_value)}/{_fmt(asl_den_value)} x 1000 "
            f"= {_fmt(tube_result['asl_req'])} mm2"
        ),
        dependencies=(asl_num, asl_den),
        operator="divide",
        factor=1000.0,
        source=CIT_TORSION,
    )
    util = calc.computed(
        "eta-t",
        title="Torsion demand-to-resistance utilisation",
        symbol="eta_T",
        unit="1",
        value=tube_result["util"],
        symbolic="eta_T = TEd/TRd",
        substituted=(
            f"eta_T = {_fmt(tube_result['t_ed'])}/{_fmt(tube_result['trd'])} "
            f"= {_fmt(tube_result['util'])}"
        ),
        dependencies=(t_ed, trd),
        operator="divide",
        source=CIT_TORSION,
        role=ROLE_FINAL,
    )
    return calc.finish(util)


def torsion_calculations(
    inp: Mapping,
    out: Mapping,
    *,
    context: Mapping[str, Any],
) -> list[TraceCalculation]:
    torsion_out = out.get("torsion")
    if not isinstance(torsion_out, Mapping) or not torsion_out.get("valid"):
        return []
    results = list(torsion_out.get("subtubes") or ())
    if not results:
        primary = torsion_out.get("primary")
        if isinstance(primary, Mapping):
            results = [primary]
    calculations = []
    for index, result in enumerate(results, start=1):
        if isinstance(result, Mapping) and result.get("valid"):
            calculations.append(
                _torsion_tube_trace(
                    inp,
                    torsion_out,
                    result,
                    context=context,
                    tube_label=f"Tube {index}",
                )
            )
    screen = torsion_out.get("min_reinf")
    if isinstance(screen, Mapping) and screen.get("applicable"):
        calc = _Calc(
            calculation_id=f"torsion.{_context_id(context)}.minimum-screen",
            coverage_id="CT-013",
            title="Minimum shear-plus-torsion reinforcement screen",
            method_id="ec2-2005-formula-6-31",
            method_label="DS/EN 1992-1-1:2005 Formula (6.31)",
            standard_based=True,
            context=context,
        )
        ted = calc.input("t-ed", "Applied torque", "TEd", "kNm", screen["t_ed"])
        trdc = calc.project_value(
            "trd-c",
            "Torsional cracking resistance",
            "TRd,c",
            "kNm",
            screen["trd_c"],
            assumption="Retained from the separately traced tube calculation.",
        )
        ved = calc.input("v-ed", "Applied shear", "VEd", "kN", screen["v_ed"])
        vrdc = calc.project_value(
            "vrd-c",
            "Shear resistance without links",
            "VRd,c",
            "kN",
            screen["vrd_c"],
            assumption="Retained from the separately traced shear calculation.",
        )
        tratio = calc.computed(
            "torsion-ratio",
            title="Torsion ratio",
            symbol="TEd/TRd,c",
            unit="1",
            value=float(screen["t_ed"]) / float(screen["trd_c"]),
            symbolic="r_T = TEd/TRd,c",
            substituted=f"r_T = {_fmt(float(screen['t_ed']) / float(screen['trd_c']))}",
            dependencies=(ted, trdc),
            operator="divide",
            source=CIT_TORSION,
        )
        vratio = calc.computed(
            "shear-ratio",
            title="Shear ratio",
            symbol="VEd/VRd,c",
            unit="1",
            value=float(screen["v_ed"]) / float(screen["vrd_c"]),
            symbolic="r_V = VEd/VRd,c",
            substituted=f"r_V = {_fmt(float(screen['v_ed']) / float(screen['vrd_c']))}",
            dependencies=(ved, vrdc),
            operator="divide",
            source=CIT_TORSION,
        )
        value = calc.computed(
            "minimum-screen",
            title="Minimum reinforcement interaction value",
            symbol="r_T + r_V",
            unit="1",
            value=screen["value"],
            symbolic="eta_min = TEd/TRd,c + VEd/VRd,c",
            substituted=f"eta_min = {_fmt(float(screen['t_ed']) / float(screen['trd_c']))} + {_fmt(float(screen['v_ed']) / float(screen['vrd_c']))} = {_fmt(screen['value'])}",
            dependencies=(tratio, vratio),
            operator="add",
            source=CIT_TORSION,
            role=ROLE_FINAL,
        )
        calculations.append(calc.finish(value))
    return calculations


def _ratio_step(
    calc: _Calc,
    prefix: str,
    title: str,
    demand_symbol: str,
    resistance_symbol: str,
    demand_unit: str,
    demand: float,
    resistance: float,
    source: SourceCitation,
) -> str:
    d = calc.input(
        f"{prefix}-demand",
        f"{title} demand",
        demand_symbol,
        demand_unit,
        demand,
    )
    r = calc.project_value(
        f"{prefix}-resistance",
        f"{title} resistance",
        resistance_symbol,
        demand_unit,
        resistance,
        assumption=(
            "Resistance is solver output traced in its governing calculation."
        ),
    )
    return calc.computed(
        f"{prefix}-ratio",
        title=f"{title} demand-to-resistance ratio",
        symbol=f"r_{prefix}",
        unit="1",
        value=float(demand) / float(resistance),
        symbolic=f"r_{prefix} = {demand_symbol}/{resistance_symbol}",
        substituted=f"r_{prefix} = {_fmt(demand)}/{_fmt(resistance)} = {_fmt(float(demand) / float(resistance))}",
        dependencies=(d, r),
        operator="divide",
        source=source,
    )


def combined_calculations(
    inp: Mapping,
    out: Mapping,
    *,
    context: Mapping[str, Any],
) -> list[TraceCalculation]:
    combined_out = out.get("combined")
    torsion_out = out.get("torsion")
    calculations: list[TraceCalculation] = []
    if isinstance(torsion_out, Mapping):
        interaction = torsion_out.get("interaction")
        if isinstance(interaction, Mapping) and interaction.get("valid"):
            calc = _Calc(
                calculation_id=f"combined.{_context_id(context)}.crushing",
                coverage_id="CT-014",
                title="Combined shear-torsion concrete-strut crushing",
                method_id="ec2-formula-6-29",
                method_label="DS/EN 1992-1-1:2005 Formula (6.29)",
                standard_based=True,
                context=context,
            )
            tratio = _ratio_step(
                calc,
                "t",
                "Torsion",
                "TEd",
                "TRd,max",
                "kNm",
                interaction["t_ed"],
                interaction["trd_max"],
                CIT_COMBINED_629,
            )
            vratio = _ratio_step(
                calc,
                "v",
                "Shear",
                "VEd",
                "VRd,max",
                "kN",
                interaction["v_ed"],
                interaction["vrd_max"],
                CIT_COMBINED_629,
            )
            final = calc.computed(
                "crushing-interaction",
                title="Combined crushing utilisation",
                symbol="eta_VT,max",
                unit="1",
                value=interaction["value"],
                symbolic="eta_VT,max = TEd/TRd,max + VEd/VRd,max",
                substituted=(
                    f"eta_VT,max = "
                    f"{_fmt(float(interaction['t_ed']) / float(interaction['trd_max']))} "
                    f"+ {_fmt(float(interaction['v_ed']) / float(interaction['vrd_max']))} "
                    f"= {_fmt(interaction['value'])}"
                ),
                dependencies=(tratio, vratio),
                operator="add",
                source=CIT_COMBINED_629,
                role=ROLE_FINAL,
            )
            calculations.append(calc.finish(final))
    if not isinstance(combined_out, Mapping):
        return calculations
    if combined_out.get("biaxial") and isinstance(
        combined_out.get("directions"), Mapping
    ):
        for component, direction in combined_out["directions"].items():
            if isinstance(direction, Mapping):
                calculations.extend(
                    combined_calculations(
                        inp,
                        {"combined": direction},
                        context={**context, "component": component},
                    )
                )
        return calculations
    if not combined_out.get("valid"):
        return calculations

    transverse = combined_out.get("transverse")
    if isinstance(transverse, Mapping) and transverse.get("valid"):
        calc = _Calc(
            calculation_id=f"combined.{_context_id(context)}.shared-stirrups",
            coverage_id="CT-014",
            title="Shared shear-torsion transverse reinforcement",
            method_id="ec2-shared-transverse-reinforcement",
            method_label="DS/EN 1992-1-1:2005 clauses 6.2.3 and 6.3.2",
            standard_based=True,
            context=context,
        )
        shear_fraction = calc.project_value(
            "shear-fraction",
            "Solver-owned shear link fraction",
            "eta_V,s",
            "1",
            transverse["shear_fraction"],
            assumption="Derived from the active shear link demand and resistance.",
        )
        torsion_fraction = calc.project_value(
            "torsion-fraction",
            "Solver-owned torsion link fraction",
            "eta_T,s",
            "1",
            transverse["torsion_fraction"],
            assumption=(
                "Derived from the active closed-link torsion demand and resistance."
            ),
        )
        stirrup = calc.computed(
            "stirrup-utilisation",
            title="Shared stirrup utilisation",
            symbol="eta_s",
            unit="1",
            value=transverse["u_stirrup"],
            symbolic="eta_s = eta_V,s + eta_T,s",
            substituted=(
                f"eta_s = {_fmt(transverse['shear_fraction'])} + "
                f"{_fmt(transverse['torsion_fraction'])} "
                f"= {_fmt(transverse['u_stirrup'])}"
            ),
            dependencies=(shear_fraction, torsion_fraction),
            operator="add",
            source=CIT_COMBINED_629,
        )
        crush = calc.project_value(
            "crushing-utilisation",
            "Concrete-strut crushing utilisation",
            "eta_crush",
            "1",
            transverse["u_crush"],
            assumption=(
                "Retained from the separately traced concrete-strut interaction."
            ),
        )
        governing = calc.computed(
            "governing-transverse",
            title="Governing transverse utilisation",
            symbol="eta_transverse",
            unit="1",
            value=transverse["governing"],
            symbolic="eta_transverse = max(eta_s, eta_crush)",
            substituted=(
                f"eta_transverse = max({_fmt(transverse['u_stirrup'])}, "
                f"{_fmt(transverse['u_crush'])}) "
                f"= {_fmt(transverse['governing'])}"
            ),
            dependencies=(stirrup, crush),
            operator="max",
            source=CIT_COMBINED_629,
            role=ROLE_FINAL,
        )
        calculations.append(calc.finish(governing))

    candidates = list(combined_out.get("longitudinal_candidates") or ())
    if not candidates:
        candidates = [
            item
            for item in (
                combined_out.get("longitudinal"),
                combined_out.get("chord_off"),
            )
            if isinstance(item, Mapping)
        ]
    for index, chord in enumerate(candidates, start=1):
        if not isinstance(chord, Mapping) or not chord.get("valid", True):
            continue
        source = (
            CIT_CHORD_2023
            if str(chord.get("longitudinal_shear_symbol") or "").upper() == "NVD"
            or bool((out.get("shear") or {}).get("model_2023"))
            else CIT_CHORD_2005
        )
        calc = _Calc(
            calculation_id=f"combined.{_context_id(context)}.chord-{index}",
            coverage_id="CT-015",
            title=f"Longitudinal chord addition {index}",
            method_id="ec2-longitudinal-chord",
            method_label=(
                "DS/EN 1992-1-1:2023 longitudinal shear force"
                if source == CIT_CHORD_2023
                else "DS/EN 1992-1-1:2005 longitudinal chord addition"
            ),
            standard_based=True,
            context={**context, "chord": index},
            warnings=(
                (
                    "The 2005 shear-force contribution was capped by the "
                    "solver-owned clause branch."
                )
                if chord.get("capped")
                else ""
            ,),
        )
        m_ed = calc.input("m-ed", "Bending moment on chord", "MEd", "kNm", chord["m_ed"])
        m_rd = calc.project_value(
            "m-rd",
            "Conditional chord bending resistance",
            "MRd",
            "kNm",
            chord["m_rd"],
            assumption="Retained from the conditional plastic section solve.",
        )
        ftd_v = calc.project_value(
            "ftd-v",
            "Additional longitudinal shear force",
            "Ftd,V",
            "kN",
            chord["ftd_v"],
            assumption="Retained from the selected shear clause branch.",
        )
        ftd_t = calc.project_value(
            "ftd-t",
            "Longitudinal torsion force",
            "Ftd,T",
            "kN",
            chord["ftd_t"],
            assumption="Retained from the thin-walled tube equilibrium.",
        )
        z = calc.project_value(
            "z",
            "Chord lever arm",
            "z",
            "m",
            chord["z"],
            assumption="Retained from the solver-owned section equilibrium.",
        )
        mv_uncapped = calc.computed(
            "mv-uncapped",
            title="Uncapped shear moment addition",
            symbol="Ftd,V z",
            unit="kNm",
            value=float(chord["ftd_v"]) * float(chord["z"]),
            symbolic="Delta M_V,uncapped = Ftd,V z",
            substituted=f"Delta M_V,uncapped = {_fmt(float(chord['ftd_v']) * float(chord['z']))} kNm",
            dependencies=(ftd_v, z),
            operator="multiply",
            source=source,
        )
        mv = calc.project_value(
            "mv",
            "Applied shear moment addition after selected clause branch",
            "Delta M_V",
            "kNm",
            chord["mv"],
            dependencies=(mv_uncapped, m_ed, m_rd),
            assumption=(
                "The solver applies the 2005 peak-moment cap where selected; "
                "the 2023 force is not capped."
            ),
        )
        half = calc.method("half", "One-chord torsion share", "0.5", "1", 0.5, source)
        mt_full = calc.computed(
            "mt-full",
            title="Torsion-force lever-arm product",
            symbol="Ftd,T z",
            unit="kNm",
            value=float(chord["ftd_t"]) * float(chord["z"]),
            symbolic="M_T,full = Ftd,T z",
            substituted=f"M_T,full = {_fmt(float(chord['ftd_t']) * float(chord['z']))} kNm",
            dependencies=(ftd_t, z),
            operator="multiply",
            source=source,
        )
        mt = calc.computed(
            "mt",
            title="One-chord torsion moment addition",
            symbol="Ftd,T z/2",
            unit="kNm",
            value=chord["mt"],
            symbolic="Delta M_T = 0.5 Ftd,T z",
            substituted=f"Delta M_T = 0.5 x {_fmt(float(chord['ftd_t']) * float(chord['z']))} = {_fmt(chord['mt'])} kNm",
            dependencies=(half, mt_full),
            operator="multiply",
            source=source,
        )
        total = calc.computed(
            "m-total",
            title="Total chord moment demand",
            symbol="MEd,total",
            unit="kNm",
            value=chord["m_total"],
            symbolic="MEd,total = MEd + Delta M_V + Delta M_T",
            substituted=f"MEd,total = {_fmt(chord['m_ed'])} + {_fmt(chord['mv'])} + {_fmt(chord['mt'])} = {_fmt(chord['m_total'])} kNm",
            dependencies=(m_ed, mv, mt),
            operator="sum",
            source=source,
        )
        util = _demand_resistance_final(
            calc,
            ratio_value=chord["util"],
            demand_step=total,
            resistance_step=m_rd,
            demand_value=chord["m_total"],
            resistance_value=chord["m_rd"],
            ratio_step_id="eta-chord",
            ratio_title="Longitudinal chord utilisation",
            ratio_symbol="eta_chord",
            ratio_symbolic="eta_chord = MEd,total/MRd",
            ratio_substituted=(
                f"eta_chord = {_fmt(chord['m_total'])}/"
                f"{_fmt(chord['m_rd'])} = {_fmt(chord['util'])}"
            ),
            source=source,
            quantity_unit="kNm",
        )
        calculations.append(calc.finish(util))

    if combined_out.get("dkna_sum") is not None:
        calc = _Calc(
            calculation_id=f"combined.{_context_id(context)}.dkna-sum",
            coverage_id="CT-016",
            title="Danish M-V-T interaction sum",
            method_id="dkna-2024-6-3-2-6",
            method_label="DS/EN 1992-1-1 DK NA:2024 clause 6.3.2(6)",
            standard_based=True,
            context=context,
        )
        ratio_values = {
            "m": float(combined_out["r_m"]),
            "v": float(combined_out["r_v"]),
            "t": float(combined_out["r_t"]),
        }
        if not all(math.isfinite(value) for value in ratio_values.values()):
            branch_symbolic = (
                "eta_DK = max(r_M + r_T, r_V + r_T)"
                if combined_out.get("m_v_independent")
                else "eta_DK = r_M + r_V + r_T"
            )
            selector = calc.step(
                "selected-interaction-equation",
                title="Selected Danish interaction equation",
                role=ROLE_METHOD_VALUE,
                provenance=PROVENANCE_STANDARD,
                symbol="I_method",
                unit="1",
                value=1.0,
                symbolic=branch_symbolic,
                substituted=(
                    f"Selected method: {branch_symbolic}; "
                    "I_method = 1"
                ),
                operator="method",
                source=CIT_DK_SUM,
            )
            dependencies = [selector]
            unbounded = []
            for suffix, symbol in (("m", "r_M"), ("v", "r_V"), ("t", "r_T")):
                value = ratio_values[suffix]
                if math.isfinite(value):
                    dependencies.append(
                        calc.project_value(
                            f"r-{suffix}",
                            f"Finite {symbol} component",
                            symbol,
                            "1",
                            value,
                            assumption=(
                                "Retained from the corresponding "
                                "solver-owned demand/resistance trace."
                            ),
                        )
                    )
                else:
                    unbounded.append(symbol)
                    dependencies.append(
                        calc.project_value(
                            f"r-{suffix}-finite",
                            f"Finite-state indicator for {symbol}",
                            f"I_finite,{suffix}",
                            "1",
                            0.0,
                            assumption=(
                                f"The solver result for {symbol} is "
                                "unbounded; a zero indicator records that "
                                "no finite numeric component exists."
                            ),
                        )
                    )
            warning = (
                f"{branch_symbolic} is unbounded because "
                f"{', '.join(unbounded)} is not finite. The genuine infinite "
                "solver utilisation remains in the result payload; no finite "
                "standard result is invented for the trace."
            )
            available = calc.step(
                "finite-combined-result-available",
                title="Finite combined-result availability",
                role=ROLE_FINAL,
                provenance=PROVENANCE_PROJECT,
                symbol="I_finite,DK",
                unit="1",
                value=0.0,
                symbolic=(
                    "I_finite,DK = 1 when every interaction component is "
                    "finite; otherwise 0"
                ),
                substituted=(
                    "I_finite,DK = 0; unbounded components: "
                    f"{', '.join(unbounded)}"
                ),
                dependencies=tuple(dependencies),
                operator="solver",
                warnings=(warning,),
                assumptions=(
                    "This availability indicator is not a compliance, "
                    "approval or code-completeness verdict.",
                ),
            )
            calculations.append(calc.finish(available))
            return calculations
        rm = calc.project_value(
            "r-m",
            "Bending demand-to-resistance ratio",
            "r_M",
            "1",
            combined_out["r_m"],
            assumption="Retained from the governing plastic-section trace.",
        )
        rv = calc.project_value(
            "r-v",
            "Shear demand-to-resistance ratio",
            "r_V",
            "1",
            combined_out["r_v"],
            assumption="Retained from the governing shear trace.",
        )
        rt = calc.project_value(
            "r-t",
            "Torsion demand-to-resistance ratio",
            "r_T",
            "1",
            combined_out["r_t"],
            assumption="Retained from the governing torsion trace.",
        )
        if combined_out.get("m_v_independent"):
            mt_value = float(combined_out["r_m"]) + float(combined_out["r_t"])
            vt_value = float(combined_out["r_v"]) + float(combined_out["r_t"])
            mt = calc.computed(
                "m-t-sum",
                title="Bending-plus-torsion branch",
                symbol="r_M+r_T",
                unit="1",
                value=mt_value,
                symbolic="eta_MT = r_M + r_T",
                substituted=f"eta_MT = {_fmt(mt_value)}",
                dependencies=(rm, rt),
                operator="add",
                source=CIT_DK_SUM,
            )
            vt = calc.computed(
                "v-t-sum",
                title="Shear-plus-torsion branch",
                symbol="r_V+r_T",
                unit="1",
                value=vt_value,
                symbolic="eta_VT = r_V + r_T",
                substituted=f"eta_VT = {_fmt(vt_value)}",
                dependencies=(rv, rt),
                operator="add",
                source=CIT_DK_SUM,
            )
            deps = (mt, vt)
            op = "max"
            symbolic = "eta_DK = max(r_M+r_T, r_V+r_T)"
            substituted = f"eta_DK = max({_fmt(mt_value)}, {_fmt(vt_value)}) = {_fmt(combined_out['dkna_sum'])}"
        else:
            deps = (rm, rv, rt)
            op = "sum"
            symbolic = "eta_DK = r_M + r_V + r_T"
            substituted = f"eta_DK = {_fmt(combined_out['r_m'])} + {_fmt(combined_out['r_v'])} + {_fmt(combined_out['r_t'])} = {_fmt(combined_out['dkna_sum'])}"
        final = calc.computed(
            "dkna-sum",
            title="Danish combined utilisation",
            symbol="eta_DK",
            unit="1",
            value=combined_out["dkna_sum"],
            symbolic=symbolic,
            substituted=substituted,
            dependencies=deps,
            operator=op,
            source=CIT_DK_SUM,
            role=ROLE_FINAL,
        )
        calculations.append(calc.finish(final))
    return calculations


def minimum_reinforcement_calculations(
    inp: Mapping,
    out: Mapping,
    *,
    context: Mapping[str, Any],
) -> list[TraceCalculation]:
    result = out.get("minimum_reinforcement")
    if not isinstance(result, Mapping):
        return []
    checks = list(result.get("checks") or ())
    calculations = []
    edition = str(result.get("edition") or "")
    is_2023 = "2023" in edition
    for index, check in enumerate(checks, start=1):
        if not isinstance(check, Mapping):
            continue
        if str(check.get("status") or "").upper() not in {"PASS", "FAIL"}:
            continue
        if not is_2023 and check.get("as_min_mm2") is not None:
            source = (
                CIT_MIN_LONG_DK if "DK" in edition.upper() else CIT_MIN_LONG_2005
            )
            calc = _Calc(
                calculation_id=f"detailing.{_context_id(context)}.minimum-longitudinal-{index}",
                coverage_id="CT-017",
                title="Minimum longitudinal reinforcement",
                method_id=(
                    "ec2-2005-dkna-formula-9-1n"
                    if "DK" in edition.upper()
                    else "ec2-2005-formula-9-1n"
                ),
                method_label=(
                    "DS/EN 1992-1-1:2005 + DK NA:2024 Formula (9.1N)"
                    if "DK" in edition.upper()
                    else "DS/EN 1992-1-1:2005 Formula (9.1N)"
                ),
                standard_based=True,
                context={**context, "check": index},
                assumptions=tuple(result.get("limitations") or ()),
            )
            fctm = calc.input("fctm", "Mean concrete tensile strength", "fctm", "MPa", check["fctm_mpa"])
            fyk = calc.input("fyk", "Governing characteristic steel yield", "fyk", "MPa", check["fyk_mpa"])
            bt = calc.project_value(
                "bt",
                "Mean width of resultant tension zone",
                "bt",
                "mm",
                check["bt_mm"],
                assumption="Computed from the solver-owned resultant tension half-plane.",
            )
            depth = calc.project_value(
                "d",
                "Effective depth of selected tension reinforcement",
                "d",
                "mm",
                check["d_mm"],
            )
            c026 = calc.method("coefficient-026", "Formula coefficient", "0.26", "1", 0.26, source)
            ratio_value = 0.26 * float(check["fctm_mpa"]) / float(check["fyk_mpa"])
            numerator = calc.computed(
                "coefficient-times-fctm",
                title="Strength coefficient numerator",
                symbol="0.26 fctm",
                unit="MPa",
                value=0.26 * float(check["fctm_mpa"]),
                symbolic="q = 0.26 fctm",
                substituted=f"q = {_fmt(0.26 * float(check['fctm_mpa']))} MPa",
                dependencies=(c026, fctm),
                operator="multiply",
                source=source,
            )
            ratio = calc.computed(
                "strength-ratio",
                title="Strength-dependent minimum ratio",
                symbol="0.26 fctm/fyk",
                unit="1",
                value=ratio_value,
                symbolic="rho_1 = 0.26 fctm/fyk",
                substituted=f"rho_1 = {_fmt(ratio_value)}",
                dependencies=(numerator, fyk),
                operator="divide",
                source=source,
            )
            floor = calc.method("ratio-floor", "Minimum ratio floor", "0.0013", "1", 0.0013, source)
            rho_value = max(ratio_value, 0.0013)
            rho = calc.computed(
                "minimum-ratio",
                title="Governing minimum ratio",
                symbol="rho_min",
                unit="1",
                value=rho_value,
                symbolic="rho_min = max(0.26 fctm/fyk, 0.0013)",
                substituted=f"rho_min = max({_fmt(ratio_value)}, 0.0013) = {_fmt(rho_value)}",
                dependencies=(ratio, floor),
                operator="max",
                source=source,
            )
            area_value = float(check["bt_mm"]) * float(check["d_mm"])
            area = calc.computed(
                "bt-d",
                title="Tension-zone reference area",
                symbol="bt d",
                unit="mm2",
                value=area_value,
                symbolic="Aref = bt d",
                substituted=f"Aref = {_fmt(area_value)} mm2",
                dependencies=(bt, depth),
                operator="multiply",
                source=source,
            )
            as_min = calc.computed(
                "as-min",
                title="Required minimum reinforcement",
                symbol="As,min",
                unit="mm2",
                value=check["as_min_mm2"],
                symbolic="As,min = rho_min bt d",
                substituted=f"As,min = {_fmt(rho_value)} x {_fmt(area_value)} = {_fmt(check['as_min_mm2'])} mm2",
                dependencies=(rho, area),
                operator="multiply",
                source=source,
            )
            provided = calc.project_value(
                "as-provided",
                "Provided selected reinforcement",
                "As,prov",
                "mm2",
                check["as_provided_mm2"],
                assumption=(
                    "Summed from the solver-selected reinforcement elements in "
                    "the governing tension zone."
                ),
            )
            ratio_value = (
                float(check["utilisation"])
                if check.get("utilisation") is not None
                else math.inf
            )
            util = _demand_resistance_final(
                calc,
                ratio_value=ratio_value,
                demand_step=as_min,
                resistance_step=provided,
                demand_value=check["as_min_mm2"],
                resistance_value=check["as_provided_mm2"],
                ratio_step_id="eta-as",
                ratio_title="Minimum reinforcement demand-to-provided ratio",
                ratio_symbol="eta_As",
                ratio_symbolic="eta_As = As,min/As,prov",
                ratio_substituted=(
                    f"eta_As = {_fmt(check['as_min_mm2'])}/"
                    f"{_fmt(check['as_provided_mm2'])} = "
                    f"{_fmt(ratio_value)}"
                ),
                source=source,
                quantity_unit="mm2",
            )
            calculations.append(calc.finish(util))
        elif not is_2023:
            source = (
                CIT_MIN_LONG_DK if "DK" in edition.upper() else CIT_MIN_LONG_2005
            )
            reason = str(
                check.get("reason")
                or "the selected tension zone has no usable reinforcement"
            )
            calc = _Calc(
                calculation_id=(
                    f"detailing.{_context_id(context)}."
                    f"minimum-longitudinal-{index}"
                ),
                coverage_id="CT-017",
                title="Minimum longitudinal reinforcement",
                method_id=(
                    "ec2-2005-dkna-formula-9-1n"
                    if "DK" in edition.upper()
                    else "ec2-2005-formula-9-1n"
                ),
                method_label=(
                    "DS/EN 1992-1-1:2005 + DK NA:2024 Formula (9.1N)"
                    if "DK" in edition.upper()
                    else "DS/EN 1992-1-1:2005 Formula (9.1N)"
                ),
                standard_based=True,
                context={
                    **context,
                    "check": index,
                    "status": check.get("status"),
                },
                warnings=(
                    f"The solver-owned check is FAIL: {reason}. Formula "
                    "(9.1N) has no finite numerical result for this selected "
                    "tension zone, so no minimum area or utilisation is "
                    "invented.",
                ),
                assumptions=tuple(result.get("limitations") or ()),
            )
            selected = calc.step(
                "selected-formula",
                title="Selected minimum-reinforcement formula",
                role=ROLE_METHOD_VALUE,
                provenance=PROVENANCE_STANDARD,
                symbol="I_method",
                unit="1",
                value=1.0,
                symbolic=(
                    "As,min = max(0.26 fctm/fyk, 0.0013) bt d"
                ),
                substituted=(
                    "Formula (9.1N) selected; I_method = 1"
                ),
                operator="method",
                source=source,
            )
            fctm = calc.input(
                "fctm",
                "Mean concrete tensile strength",
                "fctm",
                "MPa",
                check["fctm_mpa"],
            )
            bt_value = (
                float(check["bt_mm"])
                if check.get("bt_mm") is not None
                else 0.0
            )
            bt = calc.project_value(
                "bt",
                "Mean width of resultant tension zone",
                "bt",
                "mm",
                bt_value,
                assumption=(
                    "Computed from the solver-owned resultant tension "
                    "half-plane; zero records an unavailable finite width."
                ),
            )
            depth_value = (
                float(check["d_mm"])
                if check.get("d_mm") is not None
                else 0.0
            )
            depth = calc.project_value(
                "d",
                "Effective depth of selected tension reinforcement",
                "d",
                "mm",
                depth_value,
                assumption=(
                    "Zero records that no usable selected tension "
                    "reinforcement depth exists."
                ),
            )
            provided = calc.project_value(
                "as-provided",
                "Provided selected reinforcement",
                "As,prov",
                "mm2",
                check.get("as_provided_mm2", 0.0),
                assumption=(
                    "Summed from the solver-selected reinforcement elements "
                    "in the governing tension zone."
                ),
            )
            fyk_available_value = (
                1.0
                if check.get("fyk_mpa") is not None
                and math.isfinite(float(check["fyk_mpa"]))
                and float(check["fyk_mpa"]) > 0.0
                else 0.0
            )
            fyk_available = calc.project_value(
                "fyk-available",
                "Selected reinforcement strength availability",
                "I_fyk",
                "1",
                fyk_available_value,
                assumption=(
                    "One means a positive finite governing fyk exists for "
                    "the selected tension reinforcement; zero means it does "
                    "not."
                ),
            )
            available = calc.step(
                "finite-formula-result-available",
                title="Finite Formula (9.1N) result availability",
                role=ROLE_FINAL,
                provenance=PROVENANCE_PROJECT,
                symbol="I_finite,As,min",
                unit="1",
                value=0.0,
                symbolic=(
                    "I_finite,As,min = 1 when fctm, fyk, bt, d and selected "
                    "reinforcement are usable; otherwise 0"
                ),
                substituted=(
                    "I_finite,As,min = 0; "
                    f"As,prov = {_fmt(check.get('as_provided_mm2', 0.0))} "
                    f"mm2, d = {_fmt(depth_value)} mm, "
                    f"I_fyk = {_fmt(fyk_available_value)}"
                ),
                dependencies=(
                    selected,
                    fctm,
                    bt,
                    depth,
                    provided,
                    fyk_available,
                ),
                operator="solver",
                warnings=(
                    "The zero indicator records an unavailable finite "
                    "standard-formula result and the solver-owned failure "
                    "state; it is not a compliance or approval verdict.",
                ),
                assumptions=(
                    "No missing standard quantity is replaced with a project "
                    "default.",
                ),
            )
            calculations.append(calc.finish(available))
        elif is_2023:
            calc = _Calc(
                calculation_id=f"detailing.{_context_id(context)}.minimum-longitudinal-{index}",
                coverage_id="CT-018",
                title="2023 minimum longitudinal reinforcement",
                method_id="ec2-2023-formula-12-1-or-12-2",
                method_label=f"DS/EN 1992-1-1:2023 {result.get('clause')}",
                standard_based=True,
                context={**context, "check": index},
                assumptions=tuple(result.get("limitations") or ()),
            )
            if check.get("type") == "pure tension":
                demand = calc.project_value(
                    "cracking-force",
                    "Concrete cracking force",
                    "Fcr",
                    "kN",
                    check["demand_kn"],
                    assumption=(
                        "Retained from the current elastic first-cracking state."
                    ),
                )
                resistance = calc.project_value(
                    "nominal-steel-force",
                    "Nominal reinforcement force",
                    "FRk",
                    "kN",
                    check["resistance_kn"],
                    assumption=(
                        "Retained from the current nominal reinforcement "
                        "resistance calculation."
                    ),
                )
                ratio_value = (
                    float(check["utilisation"])
                    if check.get("utilisation") is not None
                    else math.inf
                )
                final = _demand_resistance_final(
                    calc,
                    ratio_value=ratio_value,
                    demand_step=demand,
                    resistance_step=resistance,
                    demand_value=check["demand_kn"],
                    resistance_value=check["resistance_kn"],
                    ratio_step_id="eta-minimum",
                    ratio_title=(
                        "Pure-tension minimum reinforcement utilisation"
                    ),
                    ratio_symbol="eta_min",
                    ratio_symbolic="eta_min = Fcr/FRk",
                    ratio_substituted=(
                        f"eta_min = {_fmt(check['demand_kn'])}/"
                        f"{_fmt(check['resistance_kn'])} = "
                        f"{_fmt(ratio_value)}"
                    ),
                    source=CIT_MIN_LONG_2023,
                )
            elif check.get("axial_feasible") is False:
                axial_demand = calc.input(
                    "n-ed-min",
                    "Minimum-reinforcement axial demand",
                    "NEd,min",
                    "kN",
                    result.get("n_ed_tension_kn", 0.0),
                )
                axial_resistance = calc.project_value(
                    "nominal-axial-resistance",
                    "Nominal reinforcement axial resistance",
                    "NR,nom",
                    "kN",
                    check.get("nominal_axial_resistance_kn", 0.0),
                    assumption=(
                        "Retained from the current nominal reinforcement "
                        "capacity envelope."
                    ),
                )
                margin_value = (
                    float(check.get("nominal_axial_resistance_kn", 0.0))
                    - float(result.get("n_ed_tension_kn", 0.0))
                )
                final = calc.computed(
                    "axial-resistance-margin",
                    title="Finite nominal axial resistance margin",
                    symbol="Delta_N",
                    unit="kN",
                    value=margin_value,
                    symbolic="Delta_N = NR,nom - NEd,min",
                    substituted=(
                        f"Delta_N = "
                        f"{_fmt(check.get('nominal_axial_resistance_kn', 0.0))}"
                        f" - {_fmt(result.get('n_ed_tension_kn', 0.0))} = "
                        f"{_fmt(margin_value)} kN"
                    ),
                    dependencies=(axial_resistance, axial_demand),
                    operator="subtract",
                    source=None,
                    provenance=PROVENANCE_PROJECT,
                    role=ROLE_FINAL,
                    warning=(
                        str(check.get("reason") or "nominal axial state is "
                            "outside the computed resistance envelope")
                    ),
                    assumption=(
                        "A negative margin is the finite representation of "
                        "the solver-owned demand-versus-resistance failure; "
                        "no moment resistance is invented."
                    ),
                )
            else:
                mcr = calc.project_value(
                    "m-cr",
                    "First-cracking resultant moment",
                    "Mcr",
                    "kNm",
                    check.get("m_cr_knm", 0.0),
                    assumption="Obtained from the solver-owned elastic cracking action.",
                )
                mr = calc.project_value(
                    "mr-nom",
                    "Nominal section resistance at the cracking axial force",
                    "MR,nom",
                    "kNm",
                    check.get("mr_nom_knm", 0.0),
                    dependencies=(mcr,),
                    assumption="Sector numerical nominal-capacity envelope.",
                )
                ratio_value = (
                    float(check["utilisation"])
                    if check.get("utilisation") is not None
                    else math.inf
                )
                final = _demand_resistance_final(
                    calc,
                    ratio_value=ratio_value,
                    demand_step=mcr,
                    resistance_step=mr,
                    demand_value=check.get("m_cr_knm", 0.0),
                    resistance_value=check.get("mr_nom_knm", 0.0),
                    ratio_step_id="eta-minimum",
                    ratio_title="Bending minimum reinforcement utilisation",
                    ratio_symbol="eta_min",
                    ratio_symbolic="eta_min = Mcr/MR,nom",
                    ratio_substituted=(
                        f"eta_min = "
                        f"{_fmt(check.get('m_cr_knm', 0.0))}/"
                        f"{_fmt(check.get('mr_nom_knm', 0.0))} = "
                        f"{_fmt(ratio_value)}"
                    ),
                    source=CIT_MIN_LONG_2023,
                    quantity_unit="kNm",
                )
            calculations.append(calc.finish(final))
    return calculations


def _transverse_check_source(
    check: Mapping,
    *,
    is_2023: bool,
) -> SourceCitation:
    """Return the exact selected base-standard clause for one link check."""

    fallback = CIT_TRANSVERSE_2023 if is_2023 else CIT_TRANSVERSE_2005
    return citation(
        DOC_2023 if is_2023 else DOC_2005,
        str(check.get("clause") or fallback.clause),
        str(check.get("criterion") or fallback.locator),
    )


def transverse_detailing_calculations(
    inp: Mapping,
    out: Mapping,
    *,
    context: Mapping[str, Any],
) -> list[TraceCalculation]:
    result = out.get("transverse_reinforcement")
    if not isinstance(result, Mapping):
        return []
    is_2023 = "2023" in str(result.get("edition") or "")
    calculations = []
    minimum = result.get("minimum_ratio") or {}
    for index, check in enumerate(result.get("checks") or (), start=1):
        if not isinstance(check, Mapping):
            continue
        if str(check.get("status") or "").upper() not in {"PASS", "FAIL"}:
            continue
        source = _transverse_check_source(check, is_2023=is_2023)
        calc = _Calc(
            calculation_id=f"detailing.{_context_id(context)}.transverse-{index}",
            coverage_id="CT-019",
            title=f"Transverse detailing - {check.get('scope', index)}",
            method_id="ec2-2023-transverse" if is_2023 else "ec2-2005-transverse",
            method_label=(
                f"{'DS/EN 1992-1-1:2023' if is_2023 else 'DS/EN 1992-1-1:2005 family'} "
                f"{check.get('clause')}"
            ),
            standard_based=True,
            context={**context, "check": index, "kind": check.get("kind")},
            assumptions=tuple(result.get("limitations") or ()),
        )
        if check.get("kind") == "minimum_ratio":
            fck = calc.input("fck", "Characteristic concrete strength", "fck", "MPa", inp["concrete"].fck)
            fywk = calc.input("fywk", "Characteristic link yield strength", "fywk", "MPa", result["fywk_mpa"])
            coefficient = calc.method(
                "coefficient",
                "Edition-specific transverse ratio coefficient",
                "c_rho",
                "1",
                minimum.get("coefficient", 0.0),
                source,
            )
            root = calc.computed(
                "sqrt-fck",
                title="Concrete strength square root",
                symbol="sqrt(fck)",
                unit="MPa",
                value=math.sqrt(float(inp["concrete"].fck)),
                symbolic="q_f = sqrt(fck)",
                substituted=f"q_f = {_fmt(math.sqrt(float(inp['concrete'].fck)))}",
                dependencies=(fck,),
                operator="sqrt",
                source=source,
            )
            numerator_value = float(minimum.get("coefficient", 0.0)) * math.sqrt(float(inp["concrete"].fck))
            numerator = calc.computed(
                "ratio-numerator",
                title="Minimum ratio numerator",
                symbol="c_rho sqrt(fck)",
                unit="MPa",
                value=numerator_value,
                symbolic="Q_rho = c_rho sqrt(fck)",
                substituted=f"Q_rho = {_fmt(numerator_value)}",
                dependencies=(coefficient, root),
                operator="multiply",
                source=source,
            )
            base_ratio_value = numerator_value / float(result["fywk_mpa"])
            base_ratio = calc.computed(
                "base-ratio",
                title="Base minimum transverse ratio",
                symbol="rho_w,min,base",
                unit="1",
                value=base_ratio_value,
                symbolic="rho_w,min,base = Q_rho/fywk",
                substituted=f"rho_w,min,base = {_fmt(base_ratio_value)}",
                dependencies=(numerator, fywk),
                operator="divide",
                source=source,
            )
            ductility = calc.method(
                "ductility-factor",
                "Explicit ductility reduction factor",
                "k_duct",
                "1",
                minimum.get("ductility_factor", 1.0),
                source,
            )
            required = calc.computed(
                "required-ratio",
                title="Required minimum transverse ratio",
                symbol="rho_w,min",
                unit="1",
                value=check["limit"],
                symbolic="rho_w,min = rho_w,min,base k_duct",
                substituted=f"rho_w,min = {_fmt(base_ratio_value)} x {_fmt(minimum.get('ductility_factor', 1.0))} = {_fmt(check['limit'])}",
                dependencies=(base_ratio, ductility),
                operator="multiply",
                source=source,
            )
            provided = calc.project_value(
                "provided-ratio",
                "Provided transverse ratio",
                "rho_w,prov",
                "1",
                check["provided"],
                assumption=(
                    "Derived from the entered link geometry, spacing and current "
                    "web width."
                ),
            )
            ratio_value = float(check["utilisation"])
            final = _demand_resistance_final(
                calc,
                ratio_value=ratio_value,
                demand_step=required,
                resistance_step=provided,
                demand_value=check["limit"],
                resistance_value=check["provided"],
                ratio_step_id="eta-transverse",
                ratio_title="Minimum transverse ratio utilisation",
                ratio_symbol="eta_rho",
                ratio_symbolic="eta_rho = rho_w,min/rho_w,prov",
                ratio_substituted=(
                    f"eta_rho = {_fmt(check['limit'])}/"
                    f"{_fmt(check['provided'])} = {_fmt(ratio_value)}"
                ),
                source=source,
                quantity_unit="1",
            )
        elif check.get("kind") == "required_links":
            required = calc.step(
                "required-link-state",
                title="Selected link requirement",
                role=ROLE_METHOD_VALUE,
                provenance=PROVENANCE_STANDARD,
                symbol="I_links,req",
                unit="1",
                value=check["limit"],
                symbolic=str(
                    check.get("criterion")
                    or "shear links provided where required"
                ),
                substituted=(
                    f"Selected requirement state I_links,req = "
                    f"{_fmt(check['limit'])}"
                ),
                operator="method",
                source=source,
                assumptions=(
                    "The 0/1 value is a trace encoding of the selected "
                    "requirement state, not a standard equation or a global "
                    "conformity verdict.",
                ),
            )
            provided = calc.input(
                "provided-link-state",
                "Entered link-provision state",
                "I_links,prov",
                "1",
                check["provided"],
                assumption=(
                    "One means links are present for this selected action; "
                    "zero means they are absent."
                ),
            )
            margin_value = (
                float(check["provided"]) - float(check["limit"])
            )
            final = calc.computed(
                "link-provision-margin",
                title="Finite provision-minus-requirement margin",
                symbol="Delta_links",
                unit="1",
                value=margin_value,
                symbolic=(
                    "Delta_links = I_links,prov - I_links,req"
                ),
                substituted=(
                    f"Delta_links = {_fmt(check['provided'])} - "
                    f"{_fmt(check['limit'])} = {_fmt(margin_value)}"
                ),
                dependencies=(provided, required),
                operator="subtract",
                source=None,
                provenance=PROVENANCE_PROJECT,
                role=ROLE_FINAL,
                warning=(
                    "The solver result retains infinite required-link "
                    "utilisation because links are absent while required. "
                    "The trace publishes the finite provision-minus-"
                    "requirement comparison instead."
                ),
                assumption=(
                    "A negative binary margin records the genuine selected "
                    "requirement-versus-provision failure. It is not a "
                    "compliance, approval or code-completeness verdict."
                ),
            )
        else:
            provided = calc.input("provided-spacing", "Provided spacing", "s_prov", "mm", check["provided"])
            limit = calc.method("spacing-limit", "Selected method spacing limit", "s_max", "mm", check["limit"], source)
            final = _demand_resistance_final(
                calc,
                ratio_value=check["utilisation"],
                demand_step=provided,
                resistance_step=limit,
                demand_value=check["provided"],
                resistance_value=check["limit"],
                ratio_step_id="eta-spacing",
                ratio_title="Spacing demand-to-limit utilisation",
                ratio_symbol="eta_s",
                ratio_symbolic="eta_s = s_prov/s_max",
                ratio_substituted=(
                    f"eta_s = {_fmt(check['provided'])}/"
                    f"{_fmt(check['limit'])} = "
                    f"{_fmt(check['utilisation'])}"
                ),
                source=source,
                quantity_unit="mm",
            )
        calculations.append(calc.finish(final))
    return calculations


def clear_spacing_calculations(
    inp: Mapping,
    out: Mapping,
    *,
    context: Mapping[str, Any],
) -> list[TraceCalculation]:
    result = out.get("clear_spacing")
    if not isinstance(result, Mapping):
        return []
    is_2023 = "2023" in str(result.get("edition") or "")
    source = CIT_CLEAR_2023 if is_2023 else CIT_CLEAR_2005
    calculations = []
    for index, pair in enumerate(result.get("pairs") or (), start=1):
        if not isinstance(pair, Mapping):
            continue
        calc = _Calc(
            calculation_id=f"detailing.global.clear-spacing-{index}",
            coverage_id="CT-020",
            title=f"Clear spacing {pair.get('first_id')} to {pair.get('second_id')}",
            method_id="ec2-2023-clear-spacing" if is_2023 else "ec2-2005-clear-spacing",
            method_label=(
                "DS/EN 1992-1-1:2023 clause 11.2(2)"
                if is_2023
                else "DS/EN 1992-1-1:2005 clause 8.2(2)"
            ),
            standard_based=True,
            context={**context, "pair": index},
            assumptions=tuple(result.get("limitations") or ()),
        )
        centre = calc.project_value(
            "centre-distance",
            "Centre-to-centre distance",
            "a_cc",
            "mm",
            pair["centre_distance_mm"],
            assumption="Euclidean distance between the two entered element centres.",
        )
        phi1 = calc.input("phi-first", "First element diameter", "phi_1", "mm", pair["phi_first_mm"])
        phi2 = calc.input("phi-second", "Second element diameter", "phi_2", "mm", pair["phi_second_mm"])
        half = calc.method("half", "Radius factor", "0.5", "1", 0.5, source)
        diameter_sum = calc.computed(
            "diameter-sum",
            title="Sum of element diameters",
            symbol="phi_1+phi_2",
            unit="mm",
            value=float(pair["phi_first_mm"]) + float(pair["phi_second_mm"]),
            symbolic="phi_sum = phi_1 + phi_2",
            substituted=f"phi_sum = {_fmt(float(pair['phi_first_mm']) + float(pair['phi_second_mm']))} mm",
            dependencies=(phi1, phi2),
            operator="add",
            source=source,
        )
        radii = calc.computed(
            "radii-sum",
            title="Sum of element radii",
            symbol="0.5(phi_1+phi_2)",
            unit="mm",
            value=0.5 * (float(pair["phi_first_mm"]) + float(pair["phi_second_mm"])),
            symbolic="r_sum = 0.5 phi_sum",
            substituted=f"r_sum = {_fmt(0.5 * (float(pair['phi_first_mm']) + float(pair['phi_second_mm'])))} mm",
            dependencies=(half, diameter_sum),
            operator="multiply",
            source=source,
        )
        clear = calc.computed(
            "clear-spacing",
            title="Pairwise clear spacing",
            symbol="a_clear",
            unit="mm",
            value=pair["clear_mm"],
            symbolic="a_clear = a_cc - 0.5(phi_1+phi_2)",
            substituted=f"a_clear = {_fmt(pair['centre_distance_mm'])} - {_fmt(0.5 * (float(pair['phi_first_mm']) + float(pair['phi_second_mm'])))} = {_fmt(pair['clear_mm'])} mm",
            dependencies=(centre, radii),
            operator="subtract",
            source=source,
        )
        phi_max = calc.computed(
            "phi-max",
            title="Larger element diameter",
            symbol="phi_max",
            unit="mm",
            value=max(float(pair["phi_first_mm"]), float(pair["phi_second_mm"])),
            symbolic="phi_max = max(phi_1, phi_2)",
            substituted=f"phi_max = {_fmt(max(float(pair['phi_first_mm']), float(pair['phi_second_mm'])))} mm",
            dependencies=(phi1, phi2),
            operator="max",
            source=source,
        )
        d_upper = calc.input("d-upper", "Entered upper aggregate size", "Dupper", "mm", result["d_upper_mm"])
        five = calc.method("aggregate-addition", "Aggregate spacing addition", "5", "mm", 5.0, source)
        aggregate_term = calc.computed(
            "aggregate-term",
            title="Aggregate-based spacing term",
            symbol="Dupper+5",
            unit="mm",
            value=float(result["d_upper_mm"]) + 5.0,
            symbolic="a_D = Dupper + 5 mm",
            substituted=f"a_D = {_fmt(result['d_upper_mm'])} + 5 = {_fmt(float(result['d_upper_mm']) + 5.0)} mm",
            dependencies=(d_upper, five),
            operator="add",
            source=source,
        )
        twenty = calc.method("absolute-minimum", "Absolute spacing minimum", "20", "mm", 20.0, source)
        required = calc.computed(
            "required-spacing",
            title="Required clear spacing",
            symbol="a_min",
            unit="mm",
            value=pair["required_mm"],
            symbolic="a_min = max(phi_max, Dupper+5, 20 mm)",
            substituted=f"a_min = max({_fmt(max(float(pair['phi_first_mm']), float(pair['phi_second_mm'])))}, {_fmt(float(result['d_upper_mm']) + 5.0)}, 20) = {_fmt(pair['required_mm'])} mm",
            dependencies=(phi_max, aggregate_term, twenty),
            operator="max",
            source=source,
        )
        margin = calc.computed(
            "spacing-margin",
            title="Clear-spacing margin",
            symbol="a_clear-a_min",
            unit="mm",
            value=pair["margin_mm"],
            symbolic="margin = a_clear - a_min",
            substituted=f"margin = {_fmt(pair['clear_mm'])} - {_fmt(pair['required_mm'])} = {_fmt(pair['margin_mm'])} mm",
            dependencies=(clear, required),
            operator="subtract",
            source=source,
            role=ROLE_FINAL,
        )
        calculations.append(calc.finish(margin))
    return calculations


def _detail_custom_map(payload: Mapping) -> dict[str, bool]:
    return {
        str(record.get("id") or ""): bool(record.get("custom"))
        for record in payload.get("fatigue_detail_basis") or ()
        if isinstance(record, Mapping)
    }


def _fatigue_steel_trace(
    payload: Mapping,
    spectrum: Any,
    reinforcement: Any,
    properties: Any,
    *,
    context: Mapping[str, Any],
    custom: bool,
) -> TraceCalculation | None:
    bins = tuple(_value(reinforcement, "bins", ()) or ())
    if not bins:
        return None
    is_2023 = "2023" in str(payload.get("edition") or "")
    source = CIT_FATIGUE_STEEL_2023 if is_2023 else CIT_FATIGUE_STEEL_2005
    calc = _Calc(
        calculation_id=(
            f"fatigue.{_identified_slug(_value(spectrum, 'spectrum_name'))}."
            "reinforcement."
            f"{_identified_slug(_value(reinforcement, 'element_id'))}"
        ),
        coverage_id="CT-021",
        title=(
            f"Reinforcement fatigue - {_value(reinforcement, 'element_id')} / "
            f"{_value(spectrum, 'spectrum_name')}"
        ),
        method_id=(
            "user-defined-sn-detail"
            if custom
            else "ec2-2023-reinforcement-sn"
            if is_2023
            else "ec2-2005-reinforcement-sn"
        ),
        method_label=(
            "User-defined/imported S-N resistance"
            if custom
            else "DS/EN 1992-1-1:2023 reinforcement S-N method"
            if is_2023
            else "DS/EN 1992-1-1:2005 reinforcement S-N method"
        ),
        standard_based=not custom,
        user_defined_method=custom,
        context={
            **context,
            "spectrum": _value(spectrum, "spectrum_name"),
            "element": _value(reinforcement, "element_id"),
        },
        warnings=(
            "The assigned custom/imported resistance values are retained and "
            "are not relabelled as standards conformity."
            if custom
            else "",
        ),
    )
    n_star_source = None if custom else source
    n_star_method = (
        calc.input(
            "n-star",
            "Assigned S-N knee cycles",
            "N*",
            "cycles",
            _value(properties, "n_star"),
        )
        if custom
        else calc.method(
            "n-star",
            "S-N knee cycles",
            "N*",
            "cycles",
            _value(properties, "n_star"),
            source,
        )
    )
    delta = (
        calc.input(
            "delta-sigma-rsk",
            "Assigned characteristic reference stress range",
            "Delta sigma_Rsk",
            "MPa",
            _value(properties, "delta_sigma_rsk_mpa"),
        )
        if custom
        else calc.method(
            "delta-sigma-rsk",
            "Characteristic reference stress range",
            "Delta sigma_Rsk",
            "MPa",
            _value(properties, "delta_sigma_rsk_mpa"),
            source,
        )
    )
    gamma_s_value = float((payload.get("partial_factors") or {}).get("gamma_s") or 1.0)
    gamma_s = calc.input(
        "gamma-s",
        "Final reinforcement fatigue factor",
        "gamma_s",
        "1",
        gamma_s_value,
    )
    damage_steps = []
    for index, bin_result in enumerate(bins, start=1):
        prefix = f"bin-{index}"
        stress_value = float(_value(bin_result, "design_stress_range_mpa"))
        stress = calc.project_value(
            f"{prefix}-stress-range",
            f"{_value(bin_result, 'bin_name')} design stress range",
            f"Delta sigma_Ed,{index}",
            "MPa",
            stress_value,
            assumption=(
                "Obtained from the solver-owned elastic action pair, including "
                "the retained action and bond treatment."
            ),
        )
        cycles = calc.input(
            f"{prefix}-cycles",
            f"{_value(bin_result, 'bin_name')} applied cycles",
            f"n_{index}",
            "cycles",
            _value(bin_result, "cycles"),
        )
        if stress_value <= 0.0:
            zero_damage = calc.computed(
                f"{prefix}-damage",
                title=f"{_value(bin_result, 'bin_name')} Miner damage",
                symbol=f"D_{index}",
                unit="1",
                value=0.0,
                symbolic="D_i = 0 for Delta sigma_Ed = 0",
                substituted="D_i = 0",
                dependencies=(stress,),
                operator="identity",
                factor=0.0,
                source=n_star_source,
                provenance=(
                    PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
                ),
            )
            damage_steps.append(zero_damage)
            continue
        exponent_value = float(_value(bin_result, "sn_exponent"))
        exponent = (
            calc.input(
                f"{prefix}-sn-exponent",
                "Assigned S-N branch exponent",
                f"k_{index}",
                "1",
                exponent_value,
            )
            if custom
            else calc.method(
                f"{prefix}-sn-exponent",
                "Selected S-N branch exponent",
                f"k_{index}",
                "1",
                exponent_value,
                source,
            )
        )
        delta_rd_value = float(_value(bin_result, "delta_sigma_rd_mpa"))
        delta_rd = calc.computed(
            f"{prefix}-delta-rd",
            title="Design reference stress range",
            symbol=f"Delta sigma_Rd,{index}",
            unit="MPa",
            value=delta_rd_value,
            symbolic="Delta sigma_Rd = Delta sigma_Rsk/gamma_s",
            substituted=(
                f"Delta sigma_Rd = "
                f"{_fmt(_value(properties, 'delta_sigma_rsk_mpa'))}/"
                f"{_fmt(gamma_s_value)} = {_fmt(delta_rd_value)} MPa"
            ),
            dependencies=(delta, gamma_s),
            operator="divide",
            source=n_star_source,
            provenance=(
                PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
            ),
        )
        ratio_value = delta_rd_value / stress_value
        ratio = calc.computed(
            f"{prefix}-sn-ratio",
            title="S-N stress ratio",
            symbol=f"r_sigma,{index}",
            unit="1",
            value=ratio_value,
            symbolic="r_sigma = Delta sigma_Rd/Delta sigma_Ed",
            substituted=f"r_sigma = {_fmt(delta_rd_value)}/{_fmt(stress_value)} = {_fmt(ratio_value)}",
            dependencies=(delta_rd, stress),
            operator="divide",
            source=n_star_source,
            provenance=(
                PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
            ),
        )
        log_nstar_value = math.log10(float(_value(properties, "n_star")))
        log_nstar = calc.computed(
            f"{prefix}-log-nstar",
            title="Logarithmic knee cycles",
            symbol="log10(N*)",
            unit="1",
            value=log_nstar_value,
            symbolic="L* = log10(N*)",
            substituted=f"L* = log10({_fmt(_value(properties, 'n_star'))}) = {_fmt(log_nstar_value)}",
            dependencies=(n_star_method,),
            operator="log10",
            source=n_star_source,
            provenance=(
                PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
            ),
        )
        log_ratio_value = math.log10(ratio_value)
        log_ratio = calc.computed(
            f"{prefix}-log-ratio",
            title="Logarithmic stress ratio",
            symbol="log10(r_sigma)",
            unit="1",
            value=log_ratio_value,
            symbolic="L_sigma = log10(r_sigma)",
            substituted=f"L_sigma = log10({_fmt(ratio_value)}) = {_fmt(log_ratio_value)}",
            dependencies=(ratio,),
            operator="log10",
            source=n_star_source,
            provenance=(
                PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
            ),
        )
        slope_term_value = exponent_value * log_ratio_value
        slope_term = calc.computed(
            f"{prefix}-slope-term",
            title="S-N logarithmic slope term",
            symbol="k log10(r_sigma)",
            unit="1",
            value=slope_term_value,
            symbolic="L_k = k L_sigma",
            substituted=f"L_k = {_fmt(exponent_value)} x {_fmt(log_ratio_value)} = {_fmt(slope_term_value)}",
            dependencies=(exponent, log_ratio),
            operator="multiply",
            source=n_star_source,
            provenance=(
                PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
            ),
        )
        log_life = calc.computed(
            f"{prefix}-log-life",
            title="Logarithmic cycles to failure",
            symbol=f"log10(N_R,{index})",
            unit="1",
            value=_value(bin_result, "log10_cycles_to_failure"),
            symbolic="log10(N_R) = log10(N*) + k log10(r_sigma)",
            substituted=(
                f"log10(N_R) = {_fmt(log_nstar_value)} + "
                f"{_fmt(slope_term_value)} = "
                f"{_fmt(_value(bin_result, 'log10_cycles_to_failure'))}"
            ),
            dependencies=(log_nstar, slope_term),
            operator="add",
            source=n_star_source,
            provenance=(
                PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
            ),
        )
        log_cycles_value = math.log10(float(_value(bin_result, "cycles")))
        log_cycles = calc.computed(
            f"{prefix}-log-cycles",
            title="Logarithmic applied cycles",
            symbol=f"log10(n_{index})",
            unit="1",
            value=log_cycles_value,
            symbolic="L_n = log10(n_i)",
            substituted=f"L_n = {_fmt(log_cycles_value)}",
            dependencies=(cycles,),
            operator="log10",
            source=n_star_source,
            provenance=(
                PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
            ),
        )
        log_damage_value = log_cycles_value - float(
            _value(bin_result, "log10_cycles_to_failure")
        )
        log_damage = calc.computed(
            f"{prefix}-log-damage",
            title="Logarithmic Miner damage",
            symbol=f"log10(D_{index})",
            unit="1",
            value=log_damage_value,
            symbolic="log10(D_i) = log10(n_i) - log10(N_R,i)",
            substituted=f"log10(D_i) = {_fmt(log_cycles_value)} - {_fmt(_value(bin_result, 'log10_cycles_to_failure'))} = {_fmt(log_damage_value)}",
            dependencies=(log_cycles, log_life),
            operator="subtract",
            source=n_star_source,
            provenance=(
                PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
            ),
        )
        damage = calc.computed(
            f"{prefix}-damage",
            title=f"{_value(bin_result, 'bin_name')} Miner damage",
            symbol=f"D_{index}",
            unit="1",
            value=_value(bin_result, "damage"),
            symbolic="D_i = 10^log10(D_i)",
            substituted=f"D_i = 10^{_fmt(log_damage_value)} = {_fmt(_value(bin_result, 'damage'))}",
            dependencies=(log_damage,),
            operator="pow10",
            source=n_star_source,
            provenance=(
                PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
            ),
        )
        damage_steps.append(damage)
    damage_total = calc.computed(
        "damage-total",
        title="Palmgren-Miner damage sum",
        symbol="D",
        unit="1",
        value=_value(reinforcement, "damage"),
        symbolic="D = sum(D_i)",
        substituted=f"D = {_fmt(_value(reinforcement, 'damage'))}",
        dependencies=tuple(damage_steps),
        operator="sum",
        source=n_star_source,
        provenance=(PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD),
    )
    yield_util = calc.project_value(
        "yield-utilisation",
        "Governing design yield/proof-stress utilisation",
        "eta_y",
        "1",
        _value(reinforcement, "yield_utilisation"),
        assumption=(
            "The governing signed reinforcement stress and the assigned "
            "yield/proof limit are retained by the solver."
        ),
    )
    final = calc.computed(
        "reinforcement-fatigue-utilisation",
        title="Governing reinforcement fatigue utilisation",
        symbol="eta_fat,s",
        unit="1",
        value=_value(reinforcement, "utilisation"),
        symbolic="eta_fat,s = max(D, eta_y)",
        substituted=f"eta_fat,s = max({_fmt(_value(reinforcement, 'damage'))}, {_fmt(_value(reinforcement, 'yield_utilisation'))}) = {_fmt(_value(reinforcement, 'utilisation'))}",
        dependencies=(damage_total, yield_util),
        operator="max",
        source=n_star_source,
        provenance=(PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD),
        role=ROLE_FINAL,
    )
    return calc.finish(final)


def _concrete_fatigue_strength_steps(
    calc: _Calc,
    payload: Mapping,
    *,
    source: SourceCitation | None,
    custom: bool,
) -> str:
    params = payload.get("concrete_parameters") or {}
    partials = payload.get("partial_factors") or {}
    is_2023 = "2023" in str(payload.get("edition") or "")
    provenance = PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
    fck = calc.input("fck", "Characteristic concrete strength", "fck", "MPa", params["fck_mpa"])
    gamma_c = calc.input("gamma-c", "Final concrete fatigue factor", "gamma_c,fat", "1", partials["gamma_c"])
    beta = calc.input("beta-cc", "Entered strength-development factor", "beta_cc(t0)", "1", params["beta_cc_t0"])
    if is_2023:
        forty = calc.method("forty", "Reference strength", "40", "MPa", 40.0, source) if source else calc.input("forty", "User method reference strength", "40", "MPa", 40.0)
        ratio_value = 40.0 / float(params["fck_mpa"])
        ratio = calc.computed(
            "eta-ratio",
            title="Concrete strength reference ratio",
            symbol="40/fck",
            unit="1",
            value=ratio_value,
            symbolic="r_eta = 40/fck",
            substituted=f"r_eta = {_fmt(ratio_value)}",
            dependencies=(forty, fck),
            operator="divide",
            source=source,
            provenance=provenance,
        )
        root_value = ratio_value ** (1.0 / 3.0)
        root = calc.computed(
            "eta-root",
            title="Concrete strength cube-root factor",
            symbol="(40/fck)^(1/3)",
            unit="1",
            value=root_value,
            symbolic="q_eta = (40/fck)^(1/3)",
            substituted=f"q_eta = {_fmt(root_value)}",
            dependencies=(ratio,),
            operator="cbrt",
            source=source,
            provenance=provenance,
        )
        one = calc.method("one-eta", "Eta upper limit", "1", "1", 1.0, source) if source else calc.input("one-eta", "User method eta upper limit", "1", "1", 1.0)
        eta_value = min(root_value, 1.0)
        eta = calc.computed(
            "eta-cc",
            title="Concrete strength factor",
            symbol="eta_cc",
            unit="1",
            value=eta_value,
            symbolic="eta_cc = min((40/fck)^(1/3), 1)",
            substituted=f"eta_cc = {_fmt(eta_value)}",
            dependencies=(root, one),
            operator="min",
            source=source,
            provenance=provenance,
        )
        c085 = calc.method("coefficient-085", "Fatigue eta coefficient", "0.85", "1", 0.85, source) if source else calc.input("coefficient-085", "User method coefficient", "0.85", "1", 0.85)
        scaled_value = 0.85 * eta_value
        scaled = calc.computed(
            "eta-scaled",
            title="Scaled concrete fatigue factor",
            symbol="0.85 eta_cc",
            unit="1",
            value=scaled_value,
            symbolic="eta_scaled = 0.85 eta_cc",
            substituted=f"eta_scaled = {_fmt(scaled_value)}",
            dependencies=(c085, eta),
            operator="multiply",
            source=source,
            provenance=provenance,
        )
        c08 = calc.method("eta-fat-cap", "Fatigue eta cap", "0.8", "1", 0.8, source) if source else calc.input("eta-fat-cap", "User method cap", "0.8", "1", 0.8)
        eta_fat_value = min(scaled_value, 0.8)
        eta_fat = calc.computed(
            "eta-cc-fat",
            title="Concrete fatigue strength factor",
            symbol="eta_cc,fat",
            unit="1",
            value=eta_fat_value,
            symbolic="eta_cc,fat = min(0.85 eta_cc, 0.8)",
            substituted=f"eta_cc,fat = {_fmt(eta_fat_value)}",
            dependencies=(scaled, c08),
            operator="min",
            source=source,
            provenance=provenance,
        )
        numerator_value = float(params["beta_cc_t0"]) * float(params["fck_mpa"]) * eta_fat_value
        numerator = calc.computed(
            "fcd-fat-numerator",
            title="Concrete fatigue strength numerator",
            symbol="beta_cc fck eta_cc,fat",
            unit="MPa",
            value=numerator_value,
            symbolic="Q_fat = beta_cc(t0) fck eta_cc,fat",
            substituted=f"Q_fat = {_fmt(numerator_value)} MPa",
            dependencies=(beta, fck, eta_fat),
            operator="product",
            source=source,
            provenance=provenance,
        )
    else:
        k1 = calc.input("concrete-k1", "Entered concrete fatigue coefficient", "k1", "1", params["k1"])
        alpha = calc.input("alpha-cc", "Entered concrete strength coefficient", "alpha_cc", "1", params["alpha_cc"])
        f250 = calc.method("fck-reference", "Fatigue strength reference", "250", "MPa", 250.0, source) if source else calc.input("fck-reference", "User method reference", "250", "MPa", 250.0)
        ratio_value = float(params["fck_mpa"]) / 250.0
        ratio = calc.computed(
            "fck-over-250",
            title="Concrete fatigue strength ratio",
            symbol="fck/250",
            unit="1",
            value=ratio_value,
            symbolic="r_250 = fck/250",
            substituted=f"r_250 = {_fmt(ratio_value)}",
            dependencies=(fck, f250),
            operator="divide",
            source=source,
            provenance=provenance,
        )
        one = calc.method("one-strength", "Unity", "1", "1", 1.0, source) if source else calc.input("one-strength", "User method unity", "1", "1", 1.0)
        reduction_value = 1.0 - ratio_value
        reduction = calc.computed(
            "strength-reduction",
            title="Concrete fatigue strength reduction",
            symbol="1-fck/250",
            unit="1",
            value=reduction_value,
            symbolic="r_fat = 1 - fck/250",
            substituted=f"r_fat = {_fmt(reduction_value)}",
            dependencies=(one, ratio),
            operator="subtract",
            source=source,
            provenance=provenance,
        )
        numerator_value = (
            float(params["k1"])
            * float(params["beta_cc_t0"])
            * float(params["alpha_cc"])
            * float(params["fck_mpa"])
            * reduction_value
        )
        numerator = calc.computed(
            "fcd-fat-numerator",
            title="Concrete fatigue strength numerator",
            symbol="k1 beta_cc alpha_cc fck (1-fck/250)",
            unit="MPa",
            value=numerator_value,
            symbolic="Q_fat = k1 beta_cc(t0) alpha_cc fck (1-fck/250)",
            substituted=f"Q_fat = {_fmt(numerator_value)} MPa",
            dependencies=(k1, beta, alpha, fck, reduction),
            operator="product",
            source=source,
            provenance=provenance,
        )
    fcd_value = float(numerator_value) / float(partials["gamma_c"])
    return calc.computed(
        "fcd-fat",
        title="Design concrete fatigue strength",
        symbol="fcd,fat",
        unit="MPa",
        value=fcd_value,
        symbolic="fcd,fat = Q_fat/gamma_c,fat",
        substituted=f"fcd,fat = {_fmt(numerator_value)}/{_fmt(partials['gamma_c'])} = {_fmt(fcd_value)} MPa",
        dependencies=(numerator, gamma_c),
        operator="divide",
        source=source,
        provenance=provenance,
    )


def _fatigue_concrete_trace(
    payload: Mapping,
    spectrum: Any,
    fibre: Any,
    *,
    context: Mapping[str, Any],
) -> TraceCalculation | None:
    bins = tuple(_value(fibre, "bins", ()) or ())
    if not bins:
        return None
    edition_2023 = "2023" in str(payload.get("edition") or "")
    method = str(_value(fibre, "method", payload.get("concrete_method")) or "")
    equivalent = "equivalent" in method.casefold()
    custom = "user-defined" in method.casefold() or "project" in method.casefold()
    if equivalent:
        coverage_id = "CT-024" if edition_2023 else "CT-022"
        method_source = (
            CIT_FATIGUE_CONC_EQ_2023
            if edition_2023
            else CIT_FATIGUE_CONC_EQ_2005
        )
        life_source = method_source
        miner_source = method_source
    else:
        coverage_id = "CT-024" if edition_2023 else "CT-023"
        method_source = (
            CIT_FATIGUE_CONC_MINER_2023
            if edition_2023
            else CIT_FATIGUE_CONC_MINER_2005
        )
        life_source = (
            CIT_FATIGUE_CONC_MINER_2023
            if edition_2023
            else CIT_FATIGUE_CONC_MINER_AC
        )
        miner_source = (
            CIT_FATIGUE_CONC_MINER_SUM_2023
            if edition_2023
            else CIT_FATIGUE_CONC_MINER_2005
        )
    strength_source = (
        CIT_FATIGUE_CONC_STRENGTH_2023
        if edition_2023
        else CIT_FATIGUE_CONC_STRENGTH_2005
    )
    if custom:
        method_source = None
        life_source = None
        miner_source = None
        strength_source = None
    calc = _Calc(
        calculation_id=(
            f"fatigue.{_identified_slug(_value(spectrum, 'spectrum_name'))}."
            f"concrete.fibre-{int(_value(fibre, 'fibre_index', 0)) + 1}"
        ),
        coverage_id=coverage_id,
        title=(
            f"Concrete fatigue - {_value(spectrum, 'spectrum_name')} / "
            f"fibre {int(_value(fibre, 'fibre_index', 0)) + 1}"
        ),
        method_id=(
            "user-defined-concrete-miner"
            if custom
            else "ec2-2023-equivalent"
            if edition_2023 and equivalent
            else "ec2-2023-miner"
            if edition_2023
            else "ec2-2005-equivalent"
            if equivalent
            else "ec2-bridge-corrected-miner"
        ),
        method_label=(
            "User-defined concrete Miner S-N relation"
            if custom
            else (
                "DS/EN 1992-1-1:2023 Formula (E.2)"
                if edition_2023
                else "DS/EN 1992-1-1:2005 Formula (6.72)"
            )
            if equivalent
            else (
                "DS/EN 1992-1-1:2023 Formulae (E.7)-(E.8)"
                if edition_2023
                else "DS/EN 1992-2:2005/AC:2008 corrected Formula (6.106)"
            )
        ),
        standard_based=not custom,
        user_defined_method=custom,
        context={
            **context,
            "spectrum": _value(spectrum, "spectrum_name"),
            "fibre": int(_value(fibre, "fibre_index", 0)) + 1,
        },
        warnings=(
            "The positive finite custom coefficient is retained and is not "
            "labelled as standards conformity."
            if custom
            else "",
        ),
    )
    fcd = _concrete_fatigue_strength_steps(
        calc, payload, source=strength_source, custom=custom
    )
    damage_steps = []
    equivalent_steps = []
    stress_steps = []
    for index, bin_result in enumerate(bins, start=1):
        prefix = f"bin-{index}"
        sigma_min = calc.project_value(
            f"{prefix}-sigma-min",
            f"{_value(bin_result, 'bin_name')} minimum compression",
            f"sigma_cd,min,{index}",
            "MPa",
            _value(bin_result, "compression_min_design_mpa"),
            assumption="Solver-owned same-fibre action pair.",
        )
        sigma_max = calc.project_value(
            f"{prefix}-sigma-max",
            f"{_value(bin_result, 'bin_name')} maximum compression",
            f"sigma_cd,max,{index}",
            "MPa",
            _value(bin_result, "compression_max_design_mpa"),
            assumption="Solver-owned same-fibre action pair.",
        )
        emax = calc.computed(
            f"{prefix}-e-max",
            title="Maximum normalised concrete stress",
            symbol=f"Ecd,max,{index}",
            unit="1",
            value=_value(bin_result, "e_cd_max"),
            symbolic="Ecd,max = sigma_cd,max/fcd,fat",
            substituted=f"Ecd,max = {_fmt(_value(bin_result, 'compression_max_design_mpa'))}/{_fmt(_value(fibre, 'fcd_fat_mpa'))} = {_fmt(_value(bin_result, 'e_cd_max'))}",
            dependencies=(sigma_max, fcd),
            operator="divide",
            source=method_source,
            provenance=(
                PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
            ),
        )
        stress_steps.append(emax)
        if float(_value(bin_result, "compression_max_design_mpa")) <= 0.0:
            zero = calc.computed(
                f"{prefix}-zero",
                title="Zero-compression fatigue result",
                symbol=f"eta_c,{index}",
                unit="1",
                value=0.0,
                symbolic="eta_c = 0 where sigma_cd,max = 0",
                substituted="eta_c = 0",
                dependencies=(sigma_max,),
                operator="identity",
                factor=0.0,
                source=method_source,
                provenance=(
                    PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
                ),
            )
            (equivalent_steps if equivalent else damage_steps).append(zero)
            continue
        ratio = calc.computed(
            f"{prefix}-stress-ratio",
            title="Concrete stress ratio",
            symbol=f"R_{index}",
            unit="1",
            value=_value(bin_result, "stress_ratio"),
            symbolic="R = sigma_cd,min/sigma_cd,max",
            substituted=f"R = {_fmt(_value(bin_result, 'compression_min_design_mpa'))}/{_fmt(_value(bin_result, 'compression_max_design_mpa'))} = {_fmt(_value(bin_result, 'stress_ratio'))}",
            dependencies=(sigma_min, sigma_max),
            operator="divide",
            source=method_source,
            provenance=(
                PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
            ),
        )
        one = (
            calc.method(
                f"{prefix}-one", "Unity", "1", "1", 1.0, method_source
            )
            if method_source
            else calc.input(f"{prefix}-one", "User method unity", "1", "1", 1.0)
        )
        one_minus_r_value = 1.0 - float(_value(bin_result, "stress_ratio"))
        one_minus_r = calc.computed(
            f"{prefix}-one-minus-r",
            title="Stress-range ratio complement",
            symbol=f"1-R_{index}",
            unit="1",
            value=one_minus_r_value,
            symbolic="q_R = 1-R",
            substituted=f"q_R = {_fmt(one_minus_r_value)}",
            dependencies=(one, ratio),
            operator="subtract",
            source=method_source,
            provenance=(
                PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
            ),
        )
        root_value = math.sqrt(max(one_minus_r_value, 0.0))
        root = calc.computed(
            f"{prefix}-range-root",
            title="Concrete stress-range square root",
            symbol=f"sqrt(1-R_{index})",
            unit="1",
            value=root_value,
            symbolic="q_R,root = sqrt(1-R)",
            substituted=f"q_R,root = {_fmt(root_value)}",
            dependencies=(one_minus_r,),
            operator="sqrt",
            source=method_source,
            provenance=(
                PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
            ),
        )
        if equivalent:
            c043 = (
                calc.method(
                    f"{prefix}-coefficient-043",
                    "Equivalent-amplitude coefficient",
                    "0.43",
                    "1",
                    0.43,
                    method_source,
                )
                if method_source
                else calc.input(
                    f"{prefix}-coefficient-043",
                    "User method coefficient",
                    "0.43",
                    "1",
                    0.43,
                )
            )
            root_term_value = 0.43 * root_value
            root_term = calc.computed(
                f"{prefix}-root-term",
                title="Equivalent-amplitude range term",
                symbol="0.43 sqrt(1-R)",
                unit="1",
                value=root_term_value,
                symbolic="q_eq = 0.43 sqrt(1-R)",
                substituted=f"q_eq = {_fmt(root_term_value)}",
                dependencies=(c043, root),
                operator="multiply",
                source=method_source,
                provenance=(
                    PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
                ),
            )
            eq = calc.computed(
                f"{prefix}-equivalent",
                title="Concrete equivalent-amplitude utilisation",
                symbol=f"eta_eq,{index}",
                unit="1",
                value=_value(bin_result, "equivalent_utilisation"),
                symbolic="eta_eq = Ecd,max + 0.43 sqrt(1-R)",
                substituted=f"eta_eq = {_fmt(_value(bin_result, 'e_cd_max'))} + {_fmt(root_term_value)} = {_fmt(_value(bin_result, 'equivalent_utilisation'))}",
                dependencies=(emax, root_term),
                operator="add",
                source=method_source,
                provenance=(
                    PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
                ),
            )
            equivalent_steps.append(eq)
        else:
            c_value = float((payload.get("concrete_parameters") or {}).get("c") or 14.0)
            c_step = (
                calc.input(
                    f"{prefix}-c",
                    "User-defined concrete fatigue coefficient",
                    "C",
                    "1",
                    c_value,
                )
                if custom
                else calc.method(
                    f"{prefix}-c",
                    "Concrete fatigue coefficient",
                    "C",
                    "1",
                    c_value,
                    life_source,
                )
            )
            one_minus_e_value = 1.0 - float(_value(bin_result, "e_cd_max"))
            one_minus_e = calc.computed(
                f"{prefix}-one-minus-emax",
                title="Concrete fatigue stress reserve",
                symbol="1-Ecd,max",
                unit="1",
                value=one_minus_e_value,
                symbolic="q_E = 1-Ecd,max",
                substituted=f"q_E = {_fmt(one_minus_e_value)}",
                dependencies=(one, emax),
                operator="subtract",
                source=life_source,
                provenance=(
                    PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
                ),
            )
            numerator_value = c_value * one_minus_e_value
            numerator = calc.computed(
                f"{prefix}-life-numerator",
                title="Concrete fatigue-life numerator",
                symbol="C(1-Ecd,max)",
                unit="1",
                value=numerator_value,
                symbolic="Q_N = C(1-Ecd,max)",
                substituted=f"Q_N = {_fmt(numerator_value)}",
                dependencies=(c_step, one_minus_e),
                operator="multiply",
                source=life_source,
                provenance=(
                    PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
                ),
            )
            log_life = calc.computed(
                f"{prefix}-log-life",
                title="Logarithmic concrete fatigue life",
                symbol=f"log10(N_R,{index})",
                unit="1",
                value=_value(bin_result, "log10_cycles_to_failure"),
                symbolic="log10(N_R) = C(1-Ecd,max)/sqrt(1-R)",
                substituted=f"log10(N_R) = {_fmt(numerator_value)}/{_fmt(root_value)} = {_fmt(_value(bin_result, 'log10_cycles_to_failure'))}",
                dependencies=(numerator, root),
                operator="divide",
                source=life_source,
                provenance=(
                    PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
                ),
            )
            cycles = calc.input(
                f"{prefix}-cycles",
                f"{_value(bin_result, 'bin_name')} applied cycles",
                f"n_{index}",
                "cycles",
                _value(bin_result, "cycles"),
            )
            log_cycles_value = math.log10(float(_value(bin_result, "cycles")))
            log_cycles = calc.computed(
                f"{prefix}-log-cycles",
                title="Logarithmic applied cycles",
                symbol=f"log10(n_{index})",
                unit="1",
                value=log_cycles_value,
                symbolic="L_n = log10(n_i)",
                substituted=f"L_n = {_fmt(log_cycles_value)}",
                dependencies=(cycles,),
                operator="log10",
                source=miner_source,
                provenance=(
                    PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
                ),
            )
            log_damage_value = log_cycles_value - float(
                _value(bin_result, "log10_cycles_to_failure")
            )
            log_damage = calc.computed(
                f"{prefix}-log-damage",
                title="Logarithmic concrete Miner damage",
                symbol=f"log10(D_{index})",
                unit="1",
                value=log_damage_value,
                symbolic="log10(D_i) = log10(n_i)-log10(N_R,i)",
                substituted=f"log10(D_i) = {_fmt(log_damage_value)}",
                dependencies=(log_cycles, log_life),
                operator="subtract",
                source=miner_source,
                provenance=(
                    PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
                ),
            )
            damage = calc.computed(
                f"{prefix}-damage",
                title=f"{_value(bin_result, 'bin_name')} concrete Miner damage",
                symbol=f"D_{index}",
                unit="1",
                value=_value(bin_result, "damage"),
                symbolic="D_i = 10^log10(D_i)",
                substituted=f"D_i = 10^{_fmt(log_damage_value)} = {_fmt(_value(bin_result, 'damage'))}",
                dependencies=(log_damage,),
                operator="pow10",
                source=miner_source,
                provenance=(
                    PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD
                ),
            )
            damage_steps.append(damage)
    if equivalent:
        equivalent_max = calc.computed(
            "equivalent-governing",
            title="Governing equivalent-amplitude utilisation",
            symbol="eta_eq,max",
            unit="1",
            value=_value(fibre, "equivalent_utilisation"),
            symbolic="eta_eq,max = max(eta_eq,i)",
            substituted=f"eta_eq,max = {_fmt(_value(fibre, 'equivalent_utilisation'))}",
            dependencies=tuple(equivalent_steps),
            operator="max",
            source=None,
            provenance=PROVENANCE_PROJECT,
        )
        final_deps = (
            calc.project_value(
                "stress-utilisation",
                "Governing maximum stress utilisation",
                "eta_sigma",
                "1",
                _value(fibre, "stress_utilisation"),
                dependencies=tuple(stress_steps),
            ),
            equivalent_max,
        )
    else:
        damage_total = calc.computed(
            "damage-total",
            title="Concrete Palmgren-Miner damage sum",
            symbol="D",
            unit="1",
            value=_value(fibre, "damage"),
            symbolic="D = sum(D_i)",
            substituted=f"D = {_fmt(_value(fibre, 'damage'))}",
            dependencies=tuple(damage_steps),
            operator="sum",
            source=miner_source,
            provenance=(PROVENANCE_PROJECT if custom else PROVENANCE_STANDARD),
        )
        stress_util = calc.project_value(
            "stress-utilisation",
            "Governing maximum stress utilisation",
            "eta_sigma",
            "1",
            _value(fibre, "stress_utilisation"),
            dependencies=tuple(stress_steps),
        )
        final_deps = (damage_total, stress_util)
    final = calc.computed(
        "concrete-fatigue-utilisation",
        title="Governing concrete fatigue utilisation",
        symbol="eta_fat,c",
        unit="1",
        value=_value(fibre, "utilisation"),
        symbolic="eta_fat,c = max(D, eta_sigma, eta_eq where applicable)",
        substituted=f"eta_fat,c = {_fmt(_value(fibre, 'utilisation'))}",
        dependencies=final_deps,
        operator="max",
        source=None,
        provenance=PROVENANCE_PROJECT,
        role=ROLE_FINAL,
    )
    return calc.finish(final)


def fatigue_calculations(
    inp: Mapping,
    out: Mapping,
    *,
    context: Mapping[str, Any],
) -> list[TraceCalculation]:
    payload = out.get("fatigue")
    if not isinstance(payload, Mapping) or payload.get("errors"):
        return []
    properties = {
        str(_value(item, "element_id")): item
        for item in payload.get("reinforcement_properties") or ()
    }
    custom_details = _detail_custom_map(payload)
    calculations = []
    for spectrum in payload.get("spectra") or ():
        for reinforcement in _value(spectrum, "reinforcement", ()) or ():
            element_id = str(_value(reinforcement, "element_id"))
            prop = properties.get(element_id)
            if prop is None:
                continue
            detail_id = str(_value(reinforcement, "detail_id"))
            trace = _fatigue_steel_trace(
                payload,
                spectrum,
                reinforcement,
                prop,
                context=context,
                custom=custom_details.get(detail_id, False),
            )
            if trace is not None:
                calculations.append(trace)
        for fibre in _value(spectrum, "concrete", ()) or ():
            trace = _fatigue_concrete_trace(
                payload,
                spectrum,
                fibre,
                context=context,
            )
            if trace is not None:
                calculations.append(trace)
    return calculations


def _bridge_method_b_trace(
    result: Mapping,
    row: Mapping,
    *,
    context: Mapping[str, Any],
) -> TraceCalculation:
    region = str(_value(row, "region_id"))
    warning = str(result.get("warning") or "")
    calc = _Calc(
        calculation_id=f"bridge.global.method-b-{_identified_slug(region)}",
        coverage_id="CT-025",
        title=f"Bridge Method B minimum steel - {region}",
        method_id="en1992-2-method-b",
        method_label="DS/EN 1992-2:2005 Method B",
        standard_based=True,
        context={**context, "component": region},
        warnings=(warning,),
        assumptions=(
            "This is an explicitly selected independent component calculation; "
            "it is not a bridge-compliance or authority-applicability verdict.",
        ),
    )
    moment = calc.input(
        "representative-moment",
        "Representative cracking moment",
        "M_rep",
        "kNm",
        _value(row, "m_rep_knm"),
    )
    moment_nmm = calc.computed(
        "representative-moment-nmm",
        title="Representative moment in Nmm",
        symbol="M_rep,Nmm",
        unit="Nmm",
        value=1.0e6 * float(_value(row, "m_rep_knm")),
        symbolic="M_rep,Nmm = 10^6 M_rep",
        substituted=(
            f"M_rep,Nmm = 10^6 x {_fmt(_value(row, 'm_rep_knm'))} "
            f"= {_fmt(1.0e6 * float(_value(row, 'm_rep_knm')))} Nmm"
        ),
        dependencies=(moment,),
        operator="identity",
        factor=1.0e6,
        source=CIT_BRIDGE_METHOD_B,
    )
    lever = calc.input(
        "lever-arm",
        "Internal lever arm",
        "z_s",
        "m",
        _value(row, "z_s_m"),
    )
    lever_mm = calc.computed(
        "lever-arm-mm",
        title="Internal lever arm in millimetres",
        symbol="z_s,mm",
        unit="mm",
        value=1000.0 * float(_value(row, "z_s_m")),
        symbolic="z_s,mm = 1000 z_s",
        substituted=(
            f"z_s,mm = 1000 x {_fmt(_value(row, 'z_s_m'))} "
            f"= {_fmt(1000.0 * float(_value(row, 'z_s_m')))} mm"
        ),
        dependencies=(lever,),
        operator="identity",
        factor=1000.0,
        source=CIT_BRIDGE_METHOD_B,
    )
    strength = calc.input(
        "steel-strength",
        "Characteristic steel strength",
        "f_yk",
        "MPa",
        _value(row, "f_yk_mpa"),
    )
    denominator_value = (
        1000.0
        * float(_value(row, "z_s_m"))
        * float(_value(row, "f_yk_mpa"))
    )
    denominator = calc.computed(
        "force-per-length",
        title="Lever-arm and steel-strength product",
        symbol="z_s f_yk",
        unit="N/mm",
        value=denominator_value,
        symbolic="Q_B = z_s,mm f_yk",
        substituted=(
            f"Q_B = {_fmt(1000.0 * float(_value(row, 'z_s_m')))} x "
            f"{_fmt(_value(row, 'f_yk_mpa'))} = "
            f"{_fmt(denominator_value)} N/mm"
        ),
        dependencies=(lever_mm, strength),
        operator="multiply",
        source=CIT_BRIDGE_METHOD_B,
    )
    required = calc.computed(
        "required-area",
        title="Required Method B reinforcement",
        symbol="A_s,min",
        unit="mm2",
        value=_value(row, "as_required_mm2"),
        symbolic="A_s,min = M_rep/(z_s f_yk)",
        substituted=(
            f"A_s,min = {_fmt(1.0e6 * float(_value(row, 'm_rep_knm')))}"
            f"/{_fmt(denominator_value)} = "
            f"{_fmt(_value(row, 'as_required_mm2'))} mm2"
        ),
        dependencies=(moment_nmm, denominator),
        operator="divide",
        source=CIT_BRIDGE_METHOD_B,
    )
    provided = calc.input(
        "provided-area",
        "Provided reinforcement area",
        "A_s,prov",
        "mm2",
        _value(row, "as_provided_mm2"),
    )
    final = calc.computed(
        "utilisation",
        title="Method B demand-to-provided-area utilisation",
        symbol="eta_B",
        unit="1",
        value=_value(row, "utilisation"),
        symbolic="eta_B = A_s,min/A_s,prov",
        substituted=(
            f"eta_B = {_fmt(_value(row, 'as_required_mm2'))}/"
            f"{_fmt(_value(row, 'as_provided_mm2'))} = "
            f"{_fmt(_value(row, 'utilisation'))}"
        ),
        dependencies=(required, provided),
        operator="divide",
        source=CIT_BRIDGE_METHOD_B,
        role=ROLE_FINAL,
    )
    return calc.finish(final)


def _bridge_box_wall_trace(
    result: Mapping,
    row: Mapping,
    *,
    context: Mapping[str, Any],
) -> TraceCalculation:
    wall = str(_value(row, "wall_id"))
    warnings = tuple(str(item) for item in result.get("warnings") or ())
    calc = _Calc(
        calculation_id=f"bridge.global.box-wall-{_identified_slug(wall)}",
        coverage_id="CT-026",
        title=f"Bridge box-wall shear/torsion interaction - {wall}",
        method_id="en1992-2-box-wall-interaction",
        method_label="DS/EN 1992-2:2005 separate box-wall interaction",
        standard_based=True,
        context={**context, "component": wall},
        warnings=warnings,
        assumptions=(
            "The supplied positive cot(theta) is retained exactly; a value "
            "outside the cited method's default range produces a warning, not "
            "clamping or a conformity statement.",
        ),
    )
    calc.input(
        "cot-theta",
        "Selected common strut-angle cotangent",
        "cot(theta)",
        "1",
        _value(row, "cot_theta"),
    )
    v_ed_signed = calc.input(
        "shear-demand",
        "Entered signed wall shear demand",
        "V_Ed",
        "kN",
        _value(row, "v_ed_kn"),
    )
    v_ed_value = abs(float(_value(row, "v_ed_kn")))
    v_ed = calc.computed(
        "shear-demand-magnitude",
        title="Wall shear-demand magnitude",
        symbol="|V_Ed|",
        unit="kN",
        value=v_ed_value,
        symbolic="V_Ed,abs = |V_Ed|",
        substituted=(
            f"V_Ed,abs = |{_fmt(_value(row, 'v_ed_kn'))}| "
            f"= {_fmt(v_ed_value)} kN"
        ),
        dependencies=(v_ed_signed,),
        operator="abs",
        source=CIT_BRIDGE_BOX,
    )
    v_rd = calc.input(
        "shear-resistance",
        "Wall maximum shear resistance",
        "V_Rd,max",
        "kN",
        _value(row, "v_rd_max_kn"),
    )
    v_ratio_value = abs(float(_value(row, "v_ed_kn"))) / float(
        _value(row, "v_rd_max_kn")
    )
    v_ratio = calc.computed(
        "shear-ratio",
        title="Wall shear interaction term",
        symbol="eta_V",
        unit="1",
        value=v_ratio_value,
        symbolic="eta_V = |V_Ed|/V_Rd,max",
        substituted=(
            f"eta_V = {_fmt(abs(float(_value(row, 'v_ed_kn'))))}/"
            f"{_fmt(_value(row, 'v_rd_max_kn'))} = {_fmt(v_ratio_value)}"
        ),
        dependencies=(v_ed, v_rd),
        operator="divide",
        source=CIT_BRIDGE_BOX,
    )
    t_ed_signed = calc.input(
        "torsion-demand",
        "Entered signed wall torsion-equivalent demand",
        "T_Ed,wall",
        "kN",
        _value(row, "t_ed_equivalent_kn"),
    )
    t_ed_value = abs(float(_value(row, "t_ed_equivalent_kn")))
    t_ed = calc.computed(
        "torsion-demand-magnitude",
        title="Wall torsion-equivalent demand magnitude",
        symbol="|T_Ed,wall|",
        unit="kN",
        value=t_ed_value,
        symbolic="T_Ed,wall,abs = |T_Ed,wall|",
        substituted=(
            f"T_Ed,wall,abs = |{_fmt(_value(row, 't_ed_equivalent_kn'))}| "
            f"= {_fmt(t_ed_value)} kN"
        ),
        dependencies=(t_ed_signed,),
        operator="abs",
        source=CIT_BRIDGE_BOX,
    )
    t_rd = calc.input(
        "torsion-resistance",
        "Wall torsion-equivalent resistance",
        "T_Rd,max,wall",
        "kN",
        _value(row, "t_rd_max_equivalent_kn"),
    )
    t_ratio_value = abs(float(_value(row, "t_ed_equivalent_kn"))) / float(
        _value(row, "t_rd_max_equivalent_kn")
    )
    t_ratio = calc.computed(
        "torsion-ratio",
        title="Wall torsion interaction term",
        symbol="eta_T",
        unit="1",
        value=t_ratio_value,
        symbolic="eta_T = |T_Ed,wall|/T_Rd,max,wall",
        substituted=(
            f"eta_T = {_fmt(abs(float(_value(row, 't_ed_equivalent_kn'))))}/"
            f"{_fmt(_value(row, 't_rd_max_equivalent_kn'))} = "
            f"{_fmt(t_ratio_value)}"
        ),
        dependencies=(t_ed, t_rd),
        operator="divide",
        source=CIT_BRIDGE_BOX,
    )
    final = calc.computed(
        "utilisation",
        title="Per-wall shear/torsion utilisation",
        symbol="eta_wall",
        unit="1",
        value=_value(row, "utilisation"),
        symbolic=(
            "eta_wall = |V_Ed|/V_Rd,max + "
            "|T_Ed,wall|/T_Rd,max,wall"
        ),
        substituted=(
            f"eta_wall = {_fmt(v_ratio_value)} + {_fmt(t_ratio_value)} "
            f"= {_fmt(_value(row, 'utilisation'))}"
        ),
        dependencies=(v_ratio, t_ratio),
        operator="add",
        source=CIT_BRIDGE_BOX,
        role=ROLE_FINAL,
    )
    return calc.finish(final)


def _bridge_minimum_crack_trace(
    row: Mapping,
    *,
    context: Mapping[str, Any],
) -> TraceCalculation:
    component = str(_value(row, "component"))
    restrained = bool(_value(row, "restrained_shrinkage"))
    calc = _Calc(
        calculation_id=(
            f"bridge.global.minimum-crack-{_identified_slug(component)}"
        ),
        coverage_id="CT-027",
        title=f"Bridge minimum crack reinforcement - {component}",
        method_id="en1992-2-minimum-crack-reinforcement",
        method_label="DS/EN 1992-2:2005 Formula (7.1)",
        standard_based=True,
        context={**context, "component": component},
        assumptions=(
            (
                "Restrained shrinkage is selected, so fct,eff is not taken "
                "below 2.9 MPa."
                if restrained
                else "Restrained shrinkage is not selected."
            ),
        ),
    )
    act = calc.input(
        "tension-area",
        "Concrete area in tension",
        "A_ct",
        "mm2",
        _value(row, "act_mm2"),
    )
    kc = calc.input(
        "stress-distribution-factor",
        "Entered stress-distribution factor",
        "k_c",
        "1",
        _value(row, "k_c"),
    )
    k = calc.input(
        "self-equilibrating-factor",
        "Entered self-equilibrating-stress factor",
        "k",
        "1",
        _value(row, "k"),
    )
    fct = calc.input(
        "entered-tensile-strength",
        "Entered effective tensile strength",
        "f_ct,eff",
        "MPa",
        _value(row, "fct_eff_mpa"),
    )
    if restrained:
        lower = calc.method(
            "restrained-shrinkage-lower-bound",
            "Restrained-shrinkage tensile-strength lower bound",
            "f_ct,eff,min",
            "MPa",
            2.9,
            CIT_BRIDGE_CRACK,
        )
        fct_used = calc.computed(
            "used-tensile-strength",
            title="Effective tensile strength used",
            symbol="f_ct,eff,used",
            unit="MPa",
            value=_value(row, "fct_eff_used_mpa"),
            symbolic="f_ct,eff,used = max(f_ct,eff, 2.9 MPa)",
            substituted=(
                f"f_ct,eff,used = max({_fmt(_value(row, 'fct_eff_mpa'))}, "
                f"2.9) = {_fmt(_value(row, 'fct_eff_used_mpa'))} MPa"
            ),
            dependencies=(fct, lower),
            operator="max",
            source=CIT_BRIDGE_CRACK,
        )
    else:
        fct_used = calc.computed(
            "used-tensile-strength",
            title="Effective tensile strength used",
            symbol="f_ct,eff,used",
            unit="MPa",
            value=_value(row, "fct_eff_used_mpa"),
            symbolic="f_ct,eff,used = f_ct,eff",
            substituted=(
                f"f_ct,eff,used = {_fmt(_value(row, 'fct_eff_mpa'))} MPa"
            ),
            dependencies=(fct,),
            operator="identity",
            source=CIT_BRIDGE_CRACK,
        )
    kc_k_value = float(_value(row, "k_c")) * float(_value(row, "k"))
    kc_k = calc.computed(
        "combined-method-factor",
        title="Combined method factor",
        symbol="k_c k",
        unit="1",
        value=kc_k_value,
        symbolic="q_k = k_c k",
        substituted=f"q_k = {_fmt(kc_k_value)}",
        dependencies=(kc, k),
        operator="multiply",
        source=CIT_BRIDGE_CRACK,
    )
    force_value = (
        kc_k_value
        * float(_value(row, "fct_eff_used_mpa"))
        * float(_value(row, "act_mm2"))
    )
    force = calc.computed(
        "tension-force",
        title="Cracking tension-force numerator",
        symbol="F_cr",
        unit="N",
        value=force_value,
        symbolic="F_cr = k_c k f_ct,eff,used A_ct",
        substituted=(
            f"F_cr = {_fmt(kc_k_value)} x "
            f"{_fmt(_value(row, 'fct_eff_used_mpa'))} x "
            f"{_fmt(_value(row, 'act_mm2'))} = {_fmt(force_value)} N"
        ),
        dependencies=(kc_k, fct_used, act),
        operator="product",
        source=CIT_BRIDGE_CRACK,
    )
    sigma = calc.input(
        "steel-stress",
        "Entered steel stress",
        "sigma_s",
        "MPa",
        _value(row, "sigma_s_mpa"),
    )
    required = calc.computed(
        "required-area",
        title="Required minimum crack reinforcement",
        symbol="A_s,min",
        unit="mm2",
        value=_value(row, "as_required_mm2"),
        symbolic="A_s,min = k_c k f_ct,eff A_ct/sigma_s",
        substituted=(
            f"A_s,min = {_fmt(force_value)}/"
            f"{_fmt(_value(row, 'sigma_s_mpa'))} = "
            f"{_fmt(_value(row, 'as_required_mm2'))} mm2"
        ),
        dependencies=(force, sigma),
        operator="divide",
        source=CIT_BRIDGE_CRACK,
    )
    provided = calc.input(
        "provided-area",
        "Provided reinforcement area",
        "A_s,prov",
        "mm2",
        _value(row, "as_provided_mm2"),
    )
    final = calc.computed(
        "utilisation",
        title="Minimum crack-reinforcement utilisation",
        symbol="eta_cr,min",
        unit="1",
        value=_value(row, "utilisation"),
        symbolic="eta_cr,min = A_s,min/A_s,prov",
        substituted=(
            f"eta_cr,min = {_fmt(_value(row, 'as_required_mm2'))}/"
            f"{_fmt(_value(row, 'as_provided_mm2'))} = "
            f"{_fmt(_value(row, 'utilisation'))}"
        ),
        dependencies=(required, provided),
        operator="divide",
        source=CIT_BRIDGE_CRACK,
        role=ROLE_FINAL,
    )
    return calc.finish(final)


def bridge_calculations(
    out: Mapping,
    *,
    context: Mapping[str, Any],
) -> list[TraceCalculation]:
    payload = out.get("bridge")
    if not isinstance(payload, Mapping) or payload.get("errors"):
        return []
    calculations = payload.get("calculations")
    if not isinstance(calculations, Mapping):
        return []
    traces: list[TraceCalculation] = []
    method_b = calculations.get("brittle_method_b")
    if isinstance(method_b, Mapping):
        traces.extend(
            _bridge_method_b_trace(method_b, row, context=context)
            for row in method_b.get("rows") or ()
            if isinstance(row, Mapping)
        )
    box_walls = calculations.get("box_walls")
    if isinstance(box_walls, Mapping):
        traces.extend(
            _bridge_box_wall_trace(box_walls, row, context=context)
            for row in box_walls.get("rows") or ()
            if isinstance(row, Mapping)
        )
    crack = calculations.get("minimum_crack_reinforcement")
    if isinstance(crack, Mapping):
        traces.extend(
            _bridge_minimum_crack_trace(row, context=context)
            for row in crack.get("rows") or ()
            if isinstance(row, Mapping)
        )
    return traces


def case_calculations(
    inp: Mapping,
    out: Mapping,
    *,
    context: Mapping[str, Any],
) -> list[TraceCalculation]:
    """Build every trace owned by one direct or named solver invocation."""

    calculations: list[TraceCalculation] = []
    for builder in (
        plastic_calculations,
        elastic_calculations,
        crack_calculations,
        shear_calculations,
        torsion_calculations,
        combined_calculations,
        minimum_reinforcement_calculations,
        transverse_detailing_calculations,
    ):
        calculations.extend(builder(inp, out, context=context))
    return calculations


def global_calculations(
    inp: Mapping,
    out: Mapping,
    *,
    context: Mapping[str, Any],
) -> list[TraceCalculation]:
    """Build traces for calculations that are not owned by an action row."""

    calculations: list[TraceCalculation] = []
    calculations.extend(clear_spacing_calculations(inp, out, context=context))
    calculations.extend(fatigue_calculations(inp, out, context=context))
    calculations.extend(bridge_calculations(out, context=context))
    return calculations
