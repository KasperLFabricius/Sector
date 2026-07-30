"""Presentation-only adapters for the shared PI-019 calculation-trace model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import streamlit as st

from sector.calculation_trace import (
    SourceCitation,
    TraceBundle,
    TraceCalculation,
    TraceStep,
)


ROLE_LABELS = {
    "user_input": "User input",
    "method_value": "Standard/method value",
    "computed_intermediate": "Computed intermediate",
    "final_result": "Final result",
}


@dataclass(frozen=True)
class StepPresentation:
    """Text-only rendering data copied from one validated trace step."""

    number: int
    step_id: str
    title: str
    role: str
    symbol: str
    unit: str
    value_text: str
    dependency_text: str
    symbolic_expression: str
    substituted_expression: str
    source_text: str
    warnings: tuple[str, ...]
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class CalculationPresentation:
    """Text-only rendering data copied from one validated calculation."""

    calculation_id: str
    coverage_id: str
    title: str
    method_label: str
    context_text: str
    standard_label: str
    warnings: tuple[str, ...]
    assumptions: tuple[str, ...]
    steps: tuple[StepPresentation, ...]


def format_number(value: float) -> str:
    """Format an already evaluated quantity without recalculating it."""

    number = float(value)
    if number == 0.0:
        return "0"
    if abs(number) >= 1.0e6 or abs(number) < 1.0e-5:
        return f"{number:.6e}"
    return f"{number:.8g}"


def citation_text(source: SourceCitation | None) -> str:
    if source is None:
        return ""
    return f"{source.document}; clause {source.clause}; {source.locator}"


def _step_view(number: int, step: TraceStep) -> StepPresentation:
    unit_suffix = "" if step.unit == "1" else f" {step.unit}"
    return StepPresentation(
        number=number,
        step_id=step.step_id,
        title=step.title,
        role=ROLE_LABELS[step.quantity_role],
        symbol=step.symbol,
        unit=step.unit,
        value_text=f"{format_number(step.evaluated_value)}{unit_suffix}",
        dependency_text=(
            ", ".join(step.dependency_ids)
            if step.dependency_ids
            else "trace leaf"
        ),
        symbolic_expression=step.symbolic_expression,
        substituted_expression=step.substituted_expression,
        source_text=citation_text(step.source_citation),
        warnings=tuple(step.warnings),
        assumptions=tuple(step.assumptions),
    )


def calculation_presentations(
    bundle: TraceBundle,
    calculations: Iterable[TraceCalculation] | None = None,
) -> tuple[CalculationPresentation, ...]:
    """Return renderer-neutral text copied from a validated trace bundle."""

    source = bundle.calculations if calculations is None else calculations
    views = []
    for calculation in source:
        context = " | ".join(
            f"{key}: {value}" for key, value in calculation.context
        )
        views.append(
            CalculationPresentation(
                calculation_id=calculation.calculation_id,
                coverage_id=calculation.coverage_id,
                title=calculation.title,
                method_label=calculation.method_label,
                context_text=context,
                standard_label=(
                    "Standards-based method"
                    if calculation.standard_based
                    else (
                        "User-defined method"
                        if calculation.user_defined_method
                        else "Project-defined numerical procedure"
                    )
                ),
                warnings=tuple(calculation.warnings),
                assumptions=tuple(calculation.assumptions),
                steps=tuple(
                    _step_view(index, step)
                    for index, step in enumerate(calculation.steps, start=1)
                ),
            )
        )
    return tuple(views)


def render_streamlit(bundle: TraceBundle) -> None:
    """Render validated records in dependency order; perform no engineering math."""

    st.caption(
        "Solver-owned ordered derivations. Values are rendered from the sealed "
        "trace; this view does not evaluate an engineering formula."
    )
    for calculation in calculation_presentations(bundle):
        with st.expander(
            f"{calculation.coverage_id} - {calculation.title}",
            expanded=False,
        ):
            st.markdown(f"**Method:** {calculation.method_label}")
            st.caption(calculation.standard_label)
            if calculation.context_text:
                st.caption(calculation.context_text)
            for text in calculation.warnings:
                st.warning(text)
            for text in calculation.assumptions:
                st.info(text)
            for step in calculation.steps:
                st.markdown(
                    f"**{step.number}. {step.title}** "
                    f"(`{step.step_id}`; {step.role})"
                )
                st.code(
                    f"{step.symbolic_expression}\n"
                    f"{step.substituted_expression}\n"
                    f"Result: {step.symbol} = {step.value_text}",
                    language=None,
                )
                st.caption(f"Dependencies: {step.dependency_text}")
                if step.source_text:
                    st.caption(f"Source: {step.source_text}")
                for text in step.warnings:
                    st.warning(text)
                for text in step.assumptions:
                    st.info(text)
