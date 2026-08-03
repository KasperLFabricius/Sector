"""Frozen CT-009 contract for the EN 1992-1-1:2004 base branch."""

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
METRE = TraceUnit("m", "length")
MILLIMETRE = TraceUnit("mm", "length")
SQUARE_METRE = TraceUnit("m2", "area")
SQUARE_MILLIMETRE = TraceUnit("mm2", "area")
FOURTH_METRE = TraceUnit("m4", "second_moment")
KILONEWTON = TraceUnit("kN", "force")
KILONEWTON_METRE = TraceUnit("kNm", "moment")
MEGAPASCAL = TraceUnit("MPa", "stress")
KILONEWTON_PER_SQUARE_METRE = TraceUnit("kN/m2", "stress")
KILONEWTON_PER_CUBIC_METRE = TraceUnit("kN/m3", "stress_gradient")


@dataclass(frozen=True, slots=True)
class MemberContractShape:
    member_id: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]
    steps: tuple[tuple[str, str, TraceSource, tuple[str, ...]], ...]
    result_states: frozenset[str]


def registry_for(
    members: tuple[MemberContractShape, ...],
) -> TraceRegistryContract:
    """Build the exact dynamic registry for the selected result branch."""

    if not members:
        raise ValueError("CT-009 registry cannot be empty")
    contracts = []
    for member in members:
        contracts.append(TraceMemberContract(
            member_id=member.member_id,
            calculation_id=member.calculation_id,
            coverage_id=COVERAGE_ID,
            method_id=METHOD_ID,
            axes=member.axes,
            sources=frozenset(
                TraceSourceContract(source.kind, source.method_id, source.edition)
                for _step, _role, source, _dependencies in member.steps
            ),
            result_states=member.result_states,
            step_ids=tuple(step for step, _role, _source, _deps in member.steps),
            step_dependencies=tuple(
                (step, dependencies)
                for step, _role, _source, dependencies in member.steps
            ),
            step_metadata=tuple(
                TraceStepMetadataContract(step, role, source)
                for step, role, source, _dependencies in member.steps
            ),
        ))
    return TraceRegistryContract(
        REGISTRY_ID,
        (TraceFamilyContract(FAMILY_ID, tuple(contracts)),),
    )


FINITE_STATES = frozenset({RESULT_FINITE})
UNDEFINED_STATES = frozenset({RESULT_UNDEFINED})
FAILED_STATES = frozenset({RESULT_FAILED})
