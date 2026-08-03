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
DK_CODE = "DS/EN 1992-1-1 + DK NA"
DK_DOCUMENT = "DS/EN 1992-1-1 DK NA:2024 rev. 2024-02-01"
DK_SOURCE_EDITION = f"{DOCUMENT} with {DK_DOCUMENT}"
DK_FAMILY_ID = "ct-009-crack-width-2004-building-dk"
DK_METHOD_ID = "sector-dk-na-2024-crack-width-replay"
DK_REGISTRY_ID = "sector-ct-009-crack-width-2004-building-dk-v1"
BRIDGE_BASE_CODE = "DS/EN 1992-2:2005 + AC:2008"
BRIDGE_BASE_DOCUMENT = BRIDGE_BASE_CODE
BRIDGE_BASE_FAMILY_ID = "ct-009-crack-width-2004-bridge-base"
BRIDGE_BASE_METHOD_ID = "sector-en-1992-2-2005-crack-width-route-replay"
BRIDGE_BASE_REGISTRY_ID = "sector-ct-009-crack-width-2004-bridge-base-v1"
BRIDGE_DK_CODE = "DS/EN 1992-2 DK NA:2015"
BRIDGE_DK_DOCUMENT = BRIDGE_DK_CODE
BRIDGE_DK_FAMILY_ID = "ct-009-crack-width-2004-bridge-dk"
BRIDGE_DK_METHOD_ID = "sector-dk-na-2015-bridge-crack-width-route-replay"
BRIDGE_DK_REGISTRY_ID = "sector-ct-009-crack-width-2004-bridge-dk-v1"
CODE_2023 = "EN 1992-1-1:2023"
EDITION_2023 = "2023"
DOCUMENT_2023 = "DS/EN 1992-1-1:2023"
FAMILY_2023 = "ct-009-crack-width-2023-bending"
METHOD_2023_APPLICABILITY = (
    "sector-en-1992-1-1-2023-crack-width-applicability-replay"
)
METHOD_2023_BENDING = "sector-en-1992-1-1-2023-refined-bending-replay"
METHOD_2023_AGGREGATE = "sector-en-1992-1-1-2023-crack-width-aggregate"
METHOD_2023_FAILED = "sector-en-1992-1-1-2023-crack-width-failure"
REGISTRY_2023 = "sector-ct-009-crack-width-2023-bending-v1"

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


def _dk_standard(method: str, clause: str, locator: str) -> TraceSource:
    return TraceSource(
        SOURCE_STANDARD,
        method,
        DK_SOURCE_EDITION,
        SourceCitation(DK_DOCUMENT, clause, locator),
    )


def _standard_2023(method: str, locator: str) -> TraceSource:
    return TraceSource(
        SOURCE_STANDARD,
        method,
        DOCUMENT_2023,
        SourceCitation(DOCUMENT_2023, "9.2.3", locator),
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
DK_ROUTE = _dk_standard(
    "dk-na-2024-crack-width-route",
    "7.3.2(3), 7.3.4(1), 7.3.4(3)",
    "fine/coarse systems, member rule and cover-dependent k3",
)
BRIDGE_BASE_ROUTE = TraceSource(
    SOURCE_STANDARD,
    "en-1992-2-2005-crack-width-route",
    BRIDGE_BASE_DOCUMENT,
    SourceCitation(
        BRIDGE_BASE_DOCUMENT,
        "7.3.4(101)",
        "recommended method: EN 1992-1-1 7.3.4",
    ),
)
BRIDGE_DK_ROUTE = TraceSource(
    SOURCE_STANDARD,
    "dk-na-2015-bridge-crack-width-route",
    BRIDGE_DK_DOCUMENT,
    SourceCitation(
        BRIDGE_DK_DOCUMENT,
        "7.3.4(101)",
        "no national choice",
    ),
)
ROUTE_2023 = _standard_2023(
    "en-1992-1-1-2023-crack-width-route",
    "refined calculation of crack width",
)
EFFECTIVE_AREA_2023 = _standard_2023(
    "en-1992-1-1-2023-effective-tension-area",
    "Figure 9.3",
)
EFFECTIVE_RATIO_2023 = _standard_2023(
    "en-1992-1-1-2023-effective-reinforcement-ratio",
    "Formula (9.12)",
)
MEAN_STRAIN_2023 = _standard_2023(
    "en-1992-1-1-2023-mean-strain-difference",
    "Formula (9.11)",
)
SPACING_2023 = _standard_2023(
    "en-1992-1-1-2023-mean-crack-spacing",
    "Formula (9.15)",
)
CURVATURE_2023 = _standard_2023(
    "en-1992-1-1-2023-curvature-factor",
    "Formula (9.9)",
)
FLEXURAL_2023 = _standard_2023(
    "en-1992-1-1-2023-flexural-coefficient",
    "Formula (9.17)",
)
BOND_2023 = _standard_2023(
    "en-1992-1-1-2023-bond-factor",
    "Formula (9.18)",
)
CRACK_WIDTH_2023 = _standard_2023(
    "en-1992-1-1-2023-calculated-crack-width",
    "Formula (9.8)",
)
DK_EFFECTIVE_AREA_FINE = _dk_standard(
    "dk-na-2024-effective-tension-area-fine",
    "7.3.2(3)",
    "(h-x)/3 applies only to slabs and prestressed members",
)
DK_EFFECTIVE_AREA_COARSE = _dk_standard(
    "dk-na-2024-effective-tension-area-coarse",
    "7.3.4(1)",
    "Figure 7.100 NA centroid-matched coarse effective area",
)
DK_SPACING_CLOSE = _dk_standard(
    "dk-na-2024-cover-dependent-crack-spacing",
    "7.3.4(3)",
    "k3 = 3.4(25/c)^(2/3)",
)
DK_CRACK_WIDTH_COARSE = _dk_standard(
    "dk-na-2024-coarse-crack-width",
    "7.3.4(1)",
    "multiply the right-hand side of Expression (7.8) by one half",
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
    method_id: str | None = None


def registry_for(
    members: tuple[MemberShape, ...],
    *,
    dk_na: bool = False,
    route: str | None = None,
) -> TraceRegistryContract:
    """Create the exact registry for the reconstructed result branch."""

    if not members:
        raise ValueError("CT-009 registry requires at least one member")
    identities = {
        (False, None): (METHOD_ID, FAMILY_ID, REGISTRY_ID),
        (True, None): (DK_METHOD_ID, DK_FAMILY_ID, DK_REGISTRY_ID),
        (False, "bridge-base"): (
            BRIDGE_BASE_METHOD_ID,
            BRIDGE_BASE_FAMILY_ID,
            BRIDGE_BASE_REGISTRY_ID,
        ),
        (True, "bridge-dk"): (
            BRIDGE_DK_METHOD_ID,
            BRIDGE_DK_FAMILY_ID,
            BRIDGE_DK_REGISTRY_ID,
        ),
        (False, "building-2023-bending"): (
            None,
            FAMILY_2023,
            REGISTRY_2023,
        ),
    }
    try:
        method_id, family_id, registry_id = identities[(dk_na, route)]
    except KeyError as exc:
        raise ValueError("unsupported CT-009 registry route") from exc
    contracts = []
    for item in members:
        selected_method = method_id if method_id is not None else item.method_id
        if selected_method is None:
            raise ValueError("CT-009 2023 member requires an exact method identity")
        contracts.append(TraceMemberContract(
            member_id=item.member_id,
            calculation_id=item.calculation_id,
            coverage_id=COVERAGE_ID,
            method_id=selected_method,
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
        ))
    return TraceRegistryContract(
        registry_id,
        (TraceFamilyContract(family_id, tuple(contracts)),),
    )


FINITE_STATES = frozenset({RESULT_FINITE})
UNDEFINED_STATES = frozenset({RESULT_UNDEFINED})
FAILED_STATES = frozenset({RESULT_FAILED})
