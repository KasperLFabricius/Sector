"""Exact PR-08C shear, torsion, and detailing trace declarations."""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    ROLE_COMPUTED,
    ROLE_FINAL,
    ROLE_METHOD_VALUE,
    ROLE_USER_INPUT,
    SOURCE_INPUT,
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    SourceCitation,
    TraceAxis,
    TraceSource,
    TraceUnit,
)
from .section_trace_blocks import DOC_2005, context_axes, context_id
from .trace_registry import (
    TraceFamilyContract,
    TraceMemberContract,
    TraceRegistryContract,
    TraceSourceContract,
    TraceStepMetadataContract,
)


SHEAR_COVERAGE = "ct-006"
TORSION_COVERAGE = "ct-007"
DETAILING_COVERAGE = "ct-008"

SHEAR_FAMILY = "ct-006-directional-shear"
TORSION_FAMILY = "ct-007-torsion"
DETAILING_FAMILY = "ct-008-detailing"
REGISTRY_ID = "sector-pr-08c-shear-torsion-detailing-v1"

DOC_DK_NA = "DS/EN 1992-1-1 DK NA:2024 (rev. 2024-02-01)"

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
PROJECT_SHEAR = TraceSource(SOURCE_PROJECT, "sector-shear-mechanics")
PROJECT_TORSION = TraceSource(SOURCE_PROJECT, "sector-torsion-mechanics")
PROJECT_DETAILING = TraceSource(SOURCE_PROJECT, "sector-detailing-mechanics")
PROJECT_SHARED_ANGLE = TraceSource(
    SOURCE_PROJECT, "sector-member-strut-angle-selector"
)
PROJECT_2023_SHEAR = TraceSource(
    SOURCE_PROJECT, "sector-published-not-implemented-2023-shear"
)
PROJECT_2023_DETAILING = TraceSource(
    SOURCE_PROJECT, "sector-published-not-implemented-2023-detailing"
)

BASE_SHEAR_C = TraceSource(
    SOURCE_STANDARD,
    "ds-en-1992-1-1-2004-a1-ac-shear-concrete",
    DOC_2005,
    SourceCitation(DOC_2005, "6.2.2", "Formulae (6.2a), (6.2b), (6.3N)"),
)
BASE_SHEAR_LINKS = TraceSource(
    SOURCE_STANDARD,
    "ds-en-1992-1-1-2004-a1-ac-shear-links",
    DOC_2005,
    SourceCitation(DOC_2005, "6.2.3", "Formulae (6.8), (6.9)"),
)
DK_SHEAR = TraceSource(
    SOURCE_STANDARD,
    "ds-en-1992-1-1-dk-na-2024-shear",
    "DS/EN 1992-1-1:2005 + DK NA:2024",
    SourceCitation(
        DOC_DK_NA,
        "6.2.2(1); 6.2.3(3)",
        "v_min coefficient; nu_v expression",
    ),
)
BASE_TORSION = TraceSource(
    SOURCE_STANDARD,
    "ds-en-1992-1-1-2004-a1-ac-torsion",
    DOC_2005,
    SourceCitation(DOC_2005, "6.3.1-6.3.2", "Formulae (6.27), (6.28), (6.30)"),
)
DK_TORSION = TraceSource(
    SOURCE_STANDARD,
    "ds-en-1992-1-1-dk-na-2024-torsion",
    "DS/EN 1992-1-1:2005 + DK NA:2024",
    SourceCitation(DOC_DK_NA, "5.103-5.104 NA", "torsion effectiveness factor"),
)
BASE_MINIMUM = TraceSource(
    SOURCE_STANDARD,
    "ds-en-1992-1-1-2004-a1-ac-minimum-reinforcement",
    DOC_2005,
    SourceCitation(DOC_2005, "9.2.1.1; 9.3.1.1", "Formula (9.1N)"),
)
BASE_CLEAR_SPACING = TraceSource(
    SOURCE_STANDARD,
    "ds-en-1992-1-1-2004-a1-ac-clear-spacing",
    DOC_2005,
    SourceCitation(DOC_2005, "8.2(2)", "minimum clear distance"),
)
BASE_TRANSVERSE = TraceSource(
    SOURCE_STANDARD,
    "ds-en-1992-1-1-2004-a1-ac-transverse-detailing",
    DOC_2005,
    SourceCitation(DOC_2005, "9.2.2-9.2.3", "Formulae (9.4)-(9.8)"),
)
DK_TRANSVERSE = TraceSource(
    SOURCE_STANDARD,
    "ds-en-1992-1-1-dk-na-2024-transverse-detailing",
    "DS/EN 1992-1-1:2005 + DK NA:2024",
    SourceCitation(DOC_DK_NA, "9.2.2(5)", "minimum transverse ratio value"),
)

ONE = TraceUnit("1", "scalar")
LENGTH_M = TraceUnit("m", "length")
LENGTH_MM = TraceUnit("mm", "length")
AREA_M2 = TraceUnit("m2", "area")
AREA_MM2 = TraceUnit("mm2", "area")
FORCE = TraceUnit("kN", "force")
MOMENT = TraceUnit("kNm", "moment")
STRESS = TraceUnit("MPa", "stress")
RATIO = TraceUnit("1", "ratio")
ANGLE = TraceUnit("cot(theta)", "angle")


@dataclass(frozen=True, slots=True)
class StepSpec:
    step_id: str
    title: str
    unit: TraceUnit
    quantity_role: str
    source: TraceSource
    dependencies: tuple[str, ...] = ()
    expression: str = "retained value"


@dataclass(frozen=True, slots=True)
class MemberPlan:
    family_id: str
    member_id: str
    calculation_id: str
    coverage_id: str
    method_id: str
    axes: tuple[TraceAxis, ...]
    branch: str
    steps: tuple[StepSpec, ...]


def member_axes(context, **values: str) -> tuple[TraceAxis, ...]:
    return context_axes(context, **values)


def calculation_id(context, family: str, member: str) -> str:
    return f"{family}.{context_id(context)}.{member}"


def shear_rule_source(edition: str, *, links: bool) -> TraceSource:
    if "2023" in edition:
        return PROJECT_2023_SHEAR
    return BASE_SHEAR_LINKS if links else BASE_SHEAR_C


def detailing_rule_source(edition: str, subfamily: str) -> TraceSource:
    if "2023" in edition:
        return PROJECT_2023_DETAILING
    return {
        "longitudinal": BASE_MINIMUM,
        "clear-spacing": BASE_CLEAR_SPACING,
        "transverse": BASE_TRANSVERSE,
    }[subfamily]


def method_id(edition: str, family: str, variant: str = "") -> str:
    edition_id = {
        "EN 1992-1-1:2005": "en-1992-1-1-2005",
        "DS/EN 1992-1-1:2005 + DK NA:2024": "ds-en-1992-1-1-2005-dk-na-2024",
        "DS/EN 1992-1-1:2023": "sector-2023-published-not-implemented",
    }.get(edition)
    if edition_id is None:
        raise ValueError("unsupported PR-08C edition")
    suffix = f"-{variant}" if variant else ""
    return f"{edition_id}-{family}{suffix}"


def _source_contract(source: TraceSource) -> TraceSourceContract:
    return TraceSourceContract(source.kind, source.method_id, source.edition)


def expected_registry(plans: tuple[MemberPlan, ...]) -> TraceRegistryContract:
    """Declare every active PR-08C member without reading candidate traces."""

    grouped: dict[str, list[TraceMemberContract]] = {
        SHEAR_FAMILY: [],
        TORSION_FAMILY: [],
        DETAILING_FAMILY: [],
    }
    for plan in plans:
        result_state = RESULT_FINITE if plan.branch == "finite" else RESULT_FAILED
        grouped[plan.family_id].append(
            TraceMemberContract(
                member_id=plan.member_id,
                calculation_id=plan.calculation_id,
                coverage_id=plan.coverage_id,
                method_id=plan.method_id,
                axes=plan.axes,
                sources=frozenset(
                    _source_contract(step.source) for step in plan.steps
                ),
                result_states=frozenset({result_state}),
                step_ids=tuple(step.step_id for step in plan.steps),
                step_dependencies=tuple(
                    (step.step_id, step.dependencies) for step in plan.steps
                ),
                step_metadata=tuple(
                    TraceStepMetadataContract(
                        step.step_id, step.quantity_role, step.source
                    )
                    for step in plan.steps
                ),
            )
        )
    families = tuple(
        TraceFamilyContract(family_id, tuple(grouped[family_id]))
        for family_id in (SHEAR_FAMILY, TORSION_FAMILY, DETAILING_FAMILY)
        if grouped[family_id]
    )
    if not families:
        raise ValueError("no active PR-08C trace family")
    return TraceRegistryContract(REGISTRY_ID, families)


__all__ = [
    "ANGLE", "AREA_M2", "AREA_MM2", "BASE_TORSION", "BASE_TRANSVERSE", "DETAILING_COVERAGE",
    "DETAILING_FAMILY", "DK_SHEAR", "DK_TORSION", "DK_TRANSVERSE", "FORCE",
    "INPUT_SOURCE", "LENGTH_M", "LENGTH_MM", "MOMENT", "MemberPlan", "ONE",
    "PROJECT_DETAILING", "PROJECT_SHARED_ANGLE", "PROJECT_SHEAR", "PROJECT_TORSION",
    "RATIO", "ROLE_COMPUTED", "ROLE_FINAL", "ROLE_METHOD_VALUE", "ROLE_USER_INPUT",
    "SHEAR_COVERAGE", "SHEAR_FAMILY", "STRESS", "StepSpec", "TORSION_COVERAGE",
    "TORSION_FAMILY", "calculation_id", "detailing_rule_source", "expected_registry",
    "member_axes", "method_id", "shear_rule_source",
]
