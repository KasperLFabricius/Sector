"""Exact CT-009 base crack-width trace contract.

This module owns only the EN 1992-1-1:2004 base-standard branch.  Danish
National Annex and EN 1992-2 source routing are deliberately separate slices.
"""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
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


COVERAGE_ID = "ct-009"
FAMILY_ID = "ct-009-crack-width-2004-base"
METHOD_ID = "sector-en-1992-1-1-2004-crack-width-replay"
REGISTRY_ID = "sector-ct-009-crack-width-2004-base-v1"

CODE = "EN 1992-1-1:2005"
EDITION = "2004"
DOCUMENT = "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010"

INPUT = TraceSource(SOURCE_INPUT, "sector-crack-width-input")
BOUNDARY = TraceSource(SOURCE_PROJECT, "sector-crack-width-boundary-replay")
ELASTIC = TraceSource(SOURCE_PROJECT, "sector-elastic-section-state-replay")
GEOMETRY = TraceSource(SOURCE_PROJECT, "sector-effective-area-geometry")
SELECTION = TraceSource(SOURCE_PROJECT, "sector-governing-crack-selection")


def _standard(method_id: str, clause: str, locator: str) -> TraceSource:
    return TraceSource(
        SOURCE_STANDARD,
        method_id,
        EDITION,
        SourceCitation(DOCUMENT, clause, locator),
    )


EFFECTIVE_AREA = _standard(
    "en-1992-1-1-2004-effective-tension-area",
    "7.3.2(3)",
    "Figure 7.1 and h_c,eff definition",
)
MEAN_STRAIN = _standard(
    "en-1992-1-1-2004-mean-strain-difference",
    "7.3.4(2)",
    "Expression (7.9)",
)
SPACING_CLOSE = _standard(
    "en-1992-1-1-2004-close-centre-crack-spacing",
    "7.3.4(3)",
    "Expression (7.11)",
)
SPACING_WIDE = _standard(
    "en-1992-1-1-2004-wide-spacing-crack-spacing",
    "7.3.4(4)",
    "Expression (7.14)",
)
CRACK_WIDTH = _standard(
    "en-1992-1-1-2004-crack-width",
    "7.3.4(1)",
    "Expression (7.8)",
)

ONE = TraceUnit("1", "scalar")
LENGTH = TraceUnit("m", "length")
LENGTH_MM = TraceUnit("mm", "length")
AREA = TraceUnit("m2", "area")
AREA_MM2 = TraceUnit("mm2", "area")
SECOND_MOMENT = TraceUnit("m4", "second_moment")
FORCE = TraceUnit("kN", "force")
MOMENT = TraceUnit("kNm", "moment")
STRESS = TraceUnit("MPa", "stress")
STRAIN = TraceUnit("1", "strain")


@dataclass(frozen=True, slots=True)
class StepShape:
    step_id: str
    title: str
    unit: TraceUnit
    role: str
    source: TraceSource
    dependencies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemberShape:
    member_id: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]
    steps: tuple[StepShape, ...]
    result_states: frozenset[str]


def registry_for(members: tuple[MemberShape, ...]) -> TraceRegistryContract:
    """Declare exact ordered member, step, graph, role and source identity."""

    if not members:
        raise ValueError("CT-009 base registry cannot be empty")
    rows = []
    for member in members:
        rows.append(TraceMemberContract(
            member_id=member.member_id,
            calculation_id=member.calculation_id,
            coverage_id=COVERAGE_ID,
            method_id=METHOD_ID,
            axes=member.axes,
            sources=frozenset(
                TraceSourceContract(
                    step.source.kind,
                    step.source.method_id,
                    step.source.edition,
                )
                for step in member.steps
            ),
            result_states=member.result_states,
            step_ids=tuple(step.step_id for step in member.steps),
            step_dependencies=tuple(
                (step.step_id, step.dependencies) for step in member.steps
            ),
            step_metadata=tuple(
                TraceStepMetadataContract(
                    step.step_id,
                    step.role,
                    step.source,
                )
                for step in member.steps
            ),
        ))
    return TraceRegistryContract(
        REGISTRY_ID,
        (TraceFamilyContract(FAMILY_ID, tuple(rows)),),
    )


SUCCESS_STATES = frozenset({RESULT_FINITE})
NOT_APPLICABLE_STATES = frozenset({RESULT_UNDEFINED})
FAILURE_STATES = frozenset({RESULT_FAILED})


__all__ = (
    "BOUNDARY", "CODE", "COVERAGE_ID", "CRACK_WIDTH", "EDITION",
    "EFFECTIVE_AREA", "ELASTIC", "FAMILY_ID", "GEOMETRY", "INPUT",
    "MEAN_STRAIN", "METHOD_ID", "REGISTRY_ID", "SELECTION",
    "SPACING_CLOSE", "SPACING_WIDE", "MemberShape", "StepShape",
    "registry_for",
)
