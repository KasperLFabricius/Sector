"""Frozen CT-010a reinforcement-fatigue trace identity and graph contract."""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY,
    RESULT_UNDEFINED,
    SOURCE_INPUT,
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    SourceCitation,
    TraceAxis,
    TraceSource,
    TraceUnit,
)
from .trace_registry import (
    TraceFamilyContract,
    TraceMemberContract,
    TraceRegistryContract,
    TraceSourceContract,
    TraceStepMetadataContract,
)


COVERAGE_ID = "ct-010"
FAMILY_ID = "ct-010-reinforcement-fatigue"
REGISTRY_ID = "sector-ct-010a-reinforcement-fatigue-v1"
METHOD_ID = "sector-retained-reinforcement-fatigue-replay"
OUTPUT_MEMBER_ID = "reinforcement-output"
INVALID_MEMBER_ID = "invalid"

# These application controls are retained as exact typed identities. Missing is
# itself a retained state; successful replay decides which values are required.
RAW_INPUT_KEYS = (
    "fatigue_on",
    "fatigue_check_steel",
    "fatigue_check_concrete",
    "fatigue_edition",
    "fatigue_concrete_method",
    "fatigue_gamma_c",
    "fatigue_gamma_s",
    "fatigue_gamma_ff",
    "fatigue_beta_cc_t0",
    "fatigue_t0_days",
    "fatigue_concrete_k1",
    "fatigue_concrete_c",
    "nl",
    "ns",
    "concrete_material_id",
    "concrete_preset",
)

NORMAL_SUCCESS_KEYS = (
    "edition",
    "checks",
    "concrete_method",
    "basis",
    "method_reference",
    "calculation_references",
    "warnings",
    "partial_factors",
    "concrete_parameters",
    "reinforcement_properties",
    "fatigue_detail_basis",
    "t0_days",
    "elements",
    "spectra",
    "governing_spectrum",
    "utilisation",
    "converged",
    "passed",
)
INVALID_KEYS = (
    "valid",
    "converged",
    "passed",
    "errors",
    "warnings",
    "edition",
    "checks",
    "basis",
    "method_reference",
    "calculation_references",
    "partial_factors",
    "concrete_parameters",
    "fatigue_detail_basis",
    "t0_days",
    "elements",
    "spectra",
    "governing_spectrum",
    "utilisation",
)

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-fatigue-input")
BOUNDARY_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-fatigue-boundary-normalisation"
)
REPLAY_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-fatigue-authoritative-replay"
)
VERDICT_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-fatigue-reinforcement-verdict"
)

ONE = TraceUnit("1", "scalar")
CYCLES = TraceUnit("cycles", "cycle_count")
STRESS = TraceUnit("MPa", "stress")
DAMAGE = TraceUnit("1", "damage")


@dataclass(frozen=True, slots=True)
class StepSpec:
    step_id: str
    title: str
    unit: TraceUnit
    quantity_role: str
    source: TraceSource
    dependencies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemberPlan:
    member_id: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]
    specs: tuple[StepSpec, ...]
    result_states: frozenset[str]


class StepRows:
    """Small ordered builder used by both the trace and its registry."""

    def __init__(self) -> None:
        self.rows: list[StepSpec] = []

    def add(
        self,
        step_id: str,
        title: str,
        unit: TraceUnit,
        role: str,
        source: TraceSource,
        *dependencies: str,
    ) -> str:
        self.rows.append(
            StepSpec(
                step_id,
                title,
                unit,
                role,
                source,
                tuple(dependencies),
            )
        )
        return step_id


def standard_sources(edition: str) -> tuple[TraceSource, TraceSource]:
    """Return exact S-N and yield sources for the selected retained edition."""

    if "2023" in edition:
        document = "DS/EN 1992-1-1:2023"
        sn_clause = "Annex E.5"
        sn_locator = "Tables E.1/E.2 and two-slope S-N relationship"
        yield_clause = "5.2.4 and Annex E.5"
    else:
        document = "DS/EN 1992-1-1:2005+A1:2014"
        sn_clause = "6.8.4"
        sn_locator = "Tables 6.3N/6.4N and two-slope S-N relationship"
        yield_clause = "3.2 and 6.8"
    sn = TraceSource(
        SOURCE_STANDARD,
        "en-1992-reinforcement-fatigue-sn",
        document,
        SourceCitation(document, sn_clause, sn_locator),
    )
    yield_source = TraceSource(
        SOURCE_STANDARD,
        "en-1992-reinforcement-fatigue-yield",
        document,
        SourceCitation(
            document,
            yield_clause,
            "design proof stress and absolute stress utilisation",
        ),
    )
    return sn, yield_source


FINAL_STATES = frozenset(
    {
        RESULT_FINITE,
        RESULT_POSITIVE_INFINITY,
        RESULT_NEGATIVE_INFINITY,
        RESULT_UNDEFINED,
        RESULT_FAILED,
    }
)


def _member_contract(plan: MemberPlan) -> TraceMemberContract:
    return TraceMemberContract(
        member_id=plan.member_id,
        calculation_id=plan.calculation_id,
        coverage_id=COVERAGE_ID,
        method_id=METHOD_ID,
        axes=plan.axes,
        sources=frozenset(
            TraceSourceContract(
                spec.source.kind,
                spec.source.method_id,
                spec.source.edition,
            )
            for spec in plan.specs
        ),
        result_states=plan.result_states,
        step_ids=tuple(spec.step_id for spec in plan.specs),
        step_dependencies=tuple(
            (spec.step_id, spec.dependencies) for spec in plan.specs
        ),
        step_metadata=tuple(
            TraceStepMetadataContract(
                spec.step_id,
                spec.quantity_role,
                spec.source,
            )
            for spec in plan.specs
        ),
    )


def expected_registry(plans: tuple[MemberPlan, ...]) -> TraceRegistryContract:
    if not plans:
        raise ValueError("CT-010a registry needs at least one member")
    return TraceRegistryContract(
        REGISTRY_ID,
        (
            TraceFamilyContract(
                FAMILY_ID,
                tuple(_member_contract(plan) for plan in plans),
            ),
        ),
    )
