"""Frozen registry and provenance contract for CT-009 2004 crack width."""

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
DK_DOCUMENT = "DS/EN 1992-1-1 DK NA:2024 rev. 2024-02-01"
BRIDGE_DOCUMENT = "DS/EN 1992-2:2005 + AC:2008"
BRIDGE_DK_DOCUMENT = "DS/EN 1992-2 DK NA:2015"
DK_SOURCE_EDITION = f"{DOCUMENT} with {DK_DOCUMENT}"

INPUT = TraceSource(SOURCE_INPUT, "sector-crack-width-input")
BOUNDARY = TraceSource(SOURCE_PROJECT, "sector-crack-width-boundary-replay")
ELASTIC = TraceSource(SOURCE_PROJECT, "sector-elastic-section-state-replay")
GEOMETRY = TraceSource(SOURCE_PROJECT, "sector-effective-area-geometry")
SELECTION = TraceSource(SOURCE_PROJECT, "sector-governing-crack-selection")


def _standard(method: str, clause: str, locator: str) -> TraceSource:
    return TraceSource(
        SOURCE_STANDARD,
        method,
        EDITION,
        SourceCitation(DOCUMENT, clause, locator),
    )


def _standard_document(
    method: str,
    edition: str,
    document: str,
    clause: str,
    locator: str,
) -> TraceSource:
    return TraceSource(
        SOURCE_STANDARD,
        method,
        edition,
        SourceCitation(document, clause, locator),
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
BASE_ROUTE = _standard(
    "en-1992-1-1-2004-crack-width-route",
    "7.3.4(1)",
    "calculation of characteristic crack width",
)
DK_ROUTE = _standard_document(
    "dk-na-2024-crack-width-route",
    DK_SOURCE_EDITION,
    DK_DOCUMENT,
    "7.3.2(3), 7.3.4(1), 7.3.4(3)",
    "fine/coarse systems, member rule and cover-dependent k3",
)
DK_EFFECTIVE_AREA_FINE = _standard_document(
    "dk-na-2024-effective-tension-area-fine",
    DK_SOURCE_EDITION,
    DK_DOCUMENT,
    "7.3.2(3)",
    "(h-x)/3 applies only to slabs and prestressed members",
)
DK_EFFECTIVE_AREA_COARSE = _standard_document(
    "dk-na-2024-effective-tension-area-coarse",
    DK_SOURCE_EDITION,
    DK_DOCUMENT,
    "7.3.4(1)",
    "Figure 7.100 NA centroid-matched coarse effective area",
)
DK_SPACING_CLOSE = _standard_document(
    "dk-na-2024-cover-dependent-crack-spacing",
    DK_SOURCE_EDITION,
    DK_DOCUMENT,
    "7.3.4(3)",
    "k3 = 3.4(25/c)^(2/3)",
)
DK_CRACK_WIDTH_COARSE = _standard_document(
    "dk-na-2024-coarse-crack-width",
    DK_SOURCE_EDITION,
    DK_DOCUMENT,
    "7.3.4(1)",
    "multiply the right-hand side of Expression (7.8) by one half",
)
BRIDGE_ROUTE = _standard_document(
    "en-1992-2-2005-crack-width-route",
    BRIDGE_DOCUMENT,
    BRIDGE_DOCUMENT,
    "7.3.4(101)",
    "recognized methods; recommended use of EN 1992-1-1 7.3.4",
)
BRIDGE_DK_ROUTE = _standard_document(
    "dk-na-2015-bridge-crack-width-route",
    f"{BRIDGE_DOCUMENT} with {BRIDGE_DK_DOCUMENT}",
    BRIDGE_DK_DOCUMENT,
    "7.3.4(101)",
    "method for calculating crack widths: no national choice",
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
class MemberShape:
    member_id: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]
    steps: tuple[tuple[str, str, TraceSource, tuple[str, ...]], ...]
    states: frozenset[str]


@dataclass(frozen=True, slots=True)
class CrackRoute:
    route_id: str
    code: str
    dk_na: bool
    family_id: str
    method_id: str
    registry_id: str
    title: str
    route_sources: tuple[TraceSource, ...]


BASE_CRACK_ROUTE = CrackRoute(
    "building-base",
    CODE,
    False,
    FAMILY_ID,
    METHOD_ID,
    REGISTRY_ID,
    "EN 1992-1-1:2004",
    (BASE_ROUTE,),
)
BUILDING_DK_ROUTE = CrackRoute(
    "building-dk",
    "DS/EN 1992-1-1 + DK NA",
    True,
    "ct-009-crack-width-2004-building-dk",
    "sector-dk-na-2024-crack-width-replay",
    "sector-ct-009-crack-width-2004-building-dk-v1",
    "DS/EN 1992-1-1:2004 with DK NA:2024",
    (BASE_ROUTE, DK_ROUTE),
)
BRIDGE_BASE_ROUTE = CrackRoute(
    "bridge-base",
    BRIDGE_DOCUMENT,
    False,
    "ct-009-crack-width-2004-bridge-base",
    "sector-en-1992-2-2005-crack-width-replay",
    "sector-ct-009-crack-width-2004-bridge-base-v1",
    "DS/EN 1992-2:2005 crack-width route",
    (BRIDGE_ROUTE,),
)
BRIDGE_DK_CRACK_ROUTE = CrackRoute(
    "bridge-dk",
    BRIDGE_DK_DOCUMENT,
    True,
    "ct-009-crack-width-2004-bridge-dk",
    "sector-en-1992-2-dk-2015-crack-width-replay",
    "sector-ct-009-crack-width-2004-bridge-dk-v1",
    "DS/EN 1992-2:2005 with DK NA:2015 crack-width route",
    (BRIDGE_ROUTE, BRIDGE_DK_ROUTE, DK_ROUTE),
)
CRACK_ROUTES = (
    BASE_CRACK_ROUTE,
    BUILDING_DK_ROUTE,
    BRIDGE_BASE_ROUTE,
    BRIDGE_DK_CRACK_ROUTE,
)


def registry_for(
    members: tuple[MemberShape, ...],
    route: CrackRoute = BASE_CRACK_ROUTE,
) -> TraceRegistryContract:
    """Create the exact registry for the reconstructed result branch."""

    if not members:
        raise ValueError("CT-009 registry requires at least one member")
    contracts = tuple(
        TraceMemberContract(
            member_id=item.member_id,
            calculation_id=item.calculation_id,
            coverage_id=COVERAGE_ID,
            method_id=route.method_id,
            axes=item.axes,
            sources=frozenset(
                TraceSourceContract(source.kind, source.method_id, source.edition)
                for _step, _role, source, _dependencies in item.steps
            ),
            result_states=item.states,
            step_ids=tuple(step for step, _role, _source, _deps in item.steps),
            step_dependencies=tuple(
                (step, dependencies)
                for step, _role, _source, dependencies in item.steps
            ),
            step_metadata=tuple(
                TraceStepMetadataContract(step, role, source)
                for step, role, source, _dependencies in item.steps
            ),
        )
        for item in members
    )
    return TraceRegistryContract(
        route.registry_id,
        (TraceFamilyContract(route.family_id, contracts),),
    )


FINITE_STATES = frozenset({RESULT_FINITE})
UNDEFINED_STATES = frozenset({RESULT_UNDEFINED})
FAILED_STATES = frozenset({RESULT_FAILED})
