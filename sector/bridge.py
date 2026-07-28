"""Typed DS/EN 1992-2:2005 + AC:2008 methodology coverage and checks.

EN 1992-2 is not a collection of optional labels.  Its relevant EN 1992-1-1
clauses apply unless EN 1992-2 deletes, varies, or supplements them.  This
module records that relationship explicitly and owns the bridge-only acceptance
evidence that Sector can currently evaluate.

The module is deliberately independent of Streamlit and pandas.  Application
adapters may construct the frozen evidence records below, but only this module
decides whether a bridge methodology check is complete, applicable, passing, or
blocking.  A missing applicability decision is never inferred from geometry or
from a disabled widget.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any, Mapping, Sequence


COMPONENT_METHODS = "Independent component methods"
EN1992_2_BASE = "DS/EN 1992-2:2005 + AC:2008"
METHODOLOGIES = (COMPONENT_METHODS, EN1992_2_BASE)

NOT_ESTABLISHED = "Not established - review required"
REQUIRED = "Required"
NOT_APPLICABLE = "Not applicable"
APPLICABILITY_OPTIONS = (NOT_ESTABLISHED, REQUIRED, NOT_APPLICABLE)

BRITTLE_NOT_ESTABLISHED = "Not established - review required"
BRITTLE_METHOD_A = "Method a - reduced prestress resistance"
BRITTLE_METHOD_B = "Method b - minimum reinforcement"
BRITTLE_METHOD_C = "Method c - agreed inspection regime"
BRITTLE_METHODS = (
    BRITTLE_NOT_ESTABLISHED,
    BRITTLE_METHOD_A,
    BRITTLE_METHOD_B,
    BRITTLE_METHOD_C,
)

MINIMUM_SCOPE_NOT_ESTABLISHED = "Not established - review required"
MINIMUM_SCOPE_WEB = "Web"
MINIMUM_SCOPE_FLANGE = "Flange"
MINIMUM_SCOPE_WEB_AND_FLANGE = "Web and flange"
MINIMUM_SCOPES = (
    MINIMUM_SCOPE_NOT_ESTABLISHED,
    MINIMUM_SCOPE_WEB,
    MINIMUM_SCOPE_FLANGE,
    MINIMUM_SCOPE_WEB_AND_FLANGE,
)

SHEAR_SCOPE_NOT_ESTABLISHED = "Not established - review required"
SHEAR_SCOPE_MEMBER = "Inherited member shear only"
SHEAR_SCOPE_INTERFACE = "Bridge web/interface provisions required"
SHEAR_SCOPES = (
    SHEAR_SCOPE_NOT_ESTABLISHED,
    SHEAR_SCOPE_MEMBER,
    SHEAR_SCOPE_INTERFACE,
)

BRIDGE_EXPOSURE_NOT_ESTABLISHED = "Not established - review required"
BRIDGE_EXPOSURE_X0_XC1 = "X0 / XC1"
BRIDGE_EXPOSURE_XC2_XC4 = "XC2 / XC3 / XC4"
BRIDGE_EXPOSURE_XD_XS = "XD / XF / XS"
BRIDGE_EXPOSURE_OTHER = "Other / project-defined"
BRIDGE_EXPOSURES = (
    BRIDGE_EXPOSURE_NOT_ESTABLISHED,
    BRIDGE_EXPOSURE_X0_XC1,
    BRIDGE_EXPOSURE_XC2_XC4,
    BRIDGE_EXPOSURE_XD_XS,
    BRIDGE_EXPOSURE_OTHER,
)

DISPOSITION_INHERITED = "inherited"
DISPOSITION_OVERRIDDEN = "overridden"
DISPOSITION_ADDED = "added"
DISPOSITION_NOT_ASSESSED = "not assessed"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_INVALID = "INVALID"
STATUS_NOT_ASSESSED = "NOT ASSESSED"
STATUS_NOT_APPLICABLE = "NOT APPLICABLE"
STATUS_NOT_RUN = "NOT RUN"
STATUS_REVIEW = "REVIEW"

BRIDGE_EVIDENCE_SCHEMA = "sector.bridge-methodology-evidence/v1"

_TOL = 1.0e-9


@dataclass(frozen=True)
class CoverageRule:
    """One row in the base bridge standards-coverage matrix."""

    check_id: str
    title: str
    disposition: str
    inherited_reference: str
    bridge_reference: str
    implementation: str
    applicability_required: bool = False


COVERAGE_RULES = (
    CoverageRule(
        "section_analysis",
        "Cross-section analysis and material laws",
        DISPOSITION_INHERITED,
        "DS/EN 1992-1-1:2004, sections 3, 5 and 6.1",
        "DS/EN 1992-2:2005, 1.1.2 and clause-by-clause inheritance",
        "Existing verified 2005-family section/material solvers are inherited.",
        True,
    ),
    CoverageRule(
        "prestress_brittle",
        "Prestressed brittle-failure avoidance",
        DISPOSITION_ADDED,
        "DS/EN 1992-1-1:2004, 5.10 and 9.2.1",
        "DS/EN 1992-2:2005, 5.10.1(106) and 6.1(109)-(110)",
        "Method b is calculated per tensile region. Methods a and c remain "
        "explicitly not assessed.",
        True,
    ),
    CoverageRule(
        "member_shear",
        "Ordinary member shear",
        DISPOSITION_INHERITED,
        "DS/EN 1992-1-1:2004, 6.2",
        "DS/EN 1992-2:2005, 6.2 inherited and supplemented",
        "The base 2005 member-shear solver is inherited when the project records "
        "that no added bridge shear/interface provision applies.",
    ),
    CoverageRule(
        "bridge_shear_detailing",
        "Bridge shear and interface detailing",
        DISPOSITION_ADDED,
        "DS/EN 1992-1-1:2004, 6.2 and 9.2.2",
        "DS/EN 1992-2:2005, 6.2 including 6.2.106",
        "Inherited member shear is reportable. Web/interface interaction that "
        "requires an added bridge model is blocking not assessed.",
        True,
    ),
    CoverageRule(
        "box_wall_torsion",
        "Box-wall shear and torsion",
        DISPOSITION_OVERRIDDEN,
        "DS/EN 1992-1-1:2004, 6.3.2",
        "DS/EN 1992-2:2005, 6.3.2(101)-(104); AC:2008 corrections",
        "Every declared box wall is checked separately at one common strut angle.",
        True,
    ),
    CoverageRule(
        "reinforcement_fatigue",
        "Reinforcement fatigue",
        DISPOSITION_INHERITED,
        "DS/EN 1992-1-1:2004, 6.8.4-6.8.6",
        "DS/EN 1992-2:2005, 6.8",
        "The grouped reinforcement spectrum solver is inherited with explicit "
        "traffic-spectrum authority provenance.",
        True,
    ),
    CoverageRule(
        "concrete_fatigue",
        "Concrete compression fatigue",
        DISPOSITION_ADDED,
        "DS/EN 1992-1-1:2004, 6.8.7 simplified criterion",
        "DS/EN 1992-2:2005, 6.8.7(101), Expression (6.106), corrected by AC:2008",
        "The corrected explicit Miner life equation is available only through "
        "this bridge method or an approved project-basis adoption.",
        True,
    ),
    CoverageRule(
        "shear_torsion_fatigue",
        "Shear and torsion fatigue",
        DISPOSITION_NOT_ASSESSED,
        "DS/EN 1992-1-1:2004, 6.8",
        "DS/EN 1992-2:2005, 6.8",
        "Sector does not calculate shear or torsion fatigue in this PR.",
        True,
    ),
    CoverageRule(
        "sls_stress",
        "Bridge SLS concrete stress",
        DISPOSITION_OVERRIDDEN,
        "DS/EN 1992-1-1:2004, 7.2",
        "DS/EN 1992-2:2005, 7.2(102)",
        "The 0.60 fck criterion is routed only to an explicitly characteristic "
        "response and its stated bridge exposure/applicability.",
        True,
    ),
    CoverageRule(
        "sls_crack",
        "Bridge crack width and decompression",
        DISPOSITION_OVERRIDDEN,
        "DS/EN 1992-1-1:2004, 7.3",
        "DS/EN 1992-2:2005, 7.3.1(105), Table 7.101N",
        "Bridge member/exposure routing is handled by the canonical structured "
        "crack-acceptance mechanism.",
        True,
    ),
    CoverageRule(
        "web_flange_minimum",
        "Separate web/flange minimum crack reinforcement",
        DISPOSITION_OVERRIDDEN,
        "DS/EN 1992-1-1:2004, 7.3.2 and Expression (7.1)",
        "DS/EN 1992-2:2005, 7.3.2(102)-(105); AC:2008 correction",
        "Required web and flange components are calculated separately.",
        True,
    ),
    CoverageRule(
        "deflection",
        "Bridge deflection",
        DISPOSITION_NOT_ASSESSED,
        "DS/EN 1992-1-1:2004, 7.4",
        "DS/EN 1992-2:2005, 7.4 with AC:2008 deletion correction",
        "Sector does not calculate member deflection in this cross-section model.",
        True,
    ),
    CoverageRule(
        "segmental_joints",
        "Opened segmental-joint shear/torsion",
        DISPOSITION_NOT_ASSESSED,
        "Not an EN 1992-1-1 member check",
        "DS/EN 1992-2:2005, 6.3.2 and Annex MM",
        "Opened segmental-joint provisions are outside the implemented solver.",
        True,
    ),
)

APPLICABILITY_CHECK_IDS = tuple(
    rule.check_id for rule in COVERAGE_RULES if rule.applicability_required
)


@dataclass(frozen=True)
class ApplicabilityDecision:
    check_id: str
    applicability: str = NOT_ESTABLISHED
    source: str = ""
    notes: str = ""


@dataclass(frozen=True)
class PrestressBrittleRegion:
    region_id: str
    m_rep_knm: Any
    z_s_m: Any
    f_yk_mpa: Any
    as_provided_mm2: Any


@dataclass(frozen=True)
class BoxWallEvidence:
    wall_id: str
    cot_theta: Any
    v_ed_kn: Any
    v_rd_max_kn: Any
    t_ed_equivalent_kn: Any
    t_rd_max_equivalent_kn: Any


@dataclass(frozen=True)
class MinimumCrackComponent:
    component: str
    act_mm2: Any
    k_c: Any
    k: Any
    fct_eff_mpa: Any
    sigma_s_mpa: Any
    as_provided_mm2: Any
    restrained_shrinkage: Any = False


@dataclass(frozen=True)
class StressResponse:
    response_id: str
    combination: str
    compression_mpa: Any
    solver_status: str
    solver_provenance: str


@dataclass(frozen=True)
class ExternalEvidence:
    status: str = STATUS_NOT_RUN
    result: str = "-"
    criterion: str = "-"
    source: str = ""
    reason: str = ""
    utilisation: Any = None
    evidence: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class BridgeBaseEvidence:
    """Complete typed evidence presented to the base bridge methodology gate."""

    methodology: str
    decisions: tuple[ApplicabilityDecision, ...]
    has_tendons: bool
    has_hollow_section: bool
    fck_mpa: Any
    brittle_method: str = BRITTLE_NOT_ESTABLISHED
    brittle_regions: tuple[PrestressBrittleRegion, ...] = ()
    expected_box_walls: Any = 0
    box_walls: tuple[BoxWallEvidence, ...] = ()
    minimum_scope: str = MINIMUM_SCOPE_NOT_ESTABLISHED
    minimum_components: tuple[MinimumCrackComponent, ...] = ()
    shear_scope: str = SHEAR_SCOPE_NOT_ESTABLISHED
    bridge_exposure: str = BRIDGE_EXPOSURE_NOT_ESTABLISHED
    stress_responses: tuple[StressResponse, ...] = ()
    section_analysis: ExternalEvidence = ExternalEvidence()
    shear: ExternalEvidence = ExternalEvidence()
    reinforcement_fatigue: ExternalEvidence = ExternalEvidence()
    concrete_fatigue: ExternalEvidence = ExternalEvidence()
    sls_crack: ExternalEvidence = ExternalEvidence()
    configuration_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class BridgeCheckResult:
    check_id: str
    title: str
    disposition: str
    status: str
    result: str
    criterion: str
    source: str
    reason: str
    utilisation: float | None = None
    evidence: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence"] = [
            dict(item) for item in self.evidence
        ]
        return result


def coverage_matrix() -> list[dict[str, Any]]:
    """Return the immutable four-state standards comparison as dictionaries."""

    return [asdict(rule) for rule in COVERAGE_RULES]


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool) or type(value).__name__ == "bool_"


def _real(value: Any, label: str, *, positive: bool = False) -> float:
    if _is_bool(value) or isinstance(value, str):
        raise ValueError(f"{label} must be a finite real number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite real number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite real number")
    if positive and number <= 0.0:
        raise ValueError(f"{label} must be greater than zero")
    return number


def _canonical_binding_value(value: Any, *, path: str):
    """Return strict JSON evidence without silently stringifying containers."""

    if value is None:
        return None
    if _is_bool(value):
        return bool(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        raise ValueError(f"{path} is binary rather than JSON evidence")
    if isinstance(value, Mapping):
        output = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str) or not raw_key:
                raise ValueError(f"{path} contains a non-text or empty key")
            output[raw_key] = _canonical_binding_value(
                raw_value,
                path=f"{path}.{raw_key}",
            )
        return {key: output[key] for key in sorted(output)}
    if isinstance(value, (list, tuple)):
        return [
            _canonical_binding_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, (set, frozenset)):
        raise ValueError(f"{path} is unordered evidence")
    if isinstance(value, (int, float)) or type(value).__module__ == "numpy":
        if _is_bool(value):
            return bool(value)
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path} is not finite numeric evidence") from exc
        if not math.isfinite(number):
            raise ValueError(f"{path} is not finite numeric evidence")
        return number
    raise ValueError(f"{path} is not typed JSON evidence")


def _binding_check(raw: Mapping, *, index: int) -> dict[str, Any]:
    """Return the immutable acceptance-relevant body of one bridge check."""

    output = {}
    for key in (
        "check_id",
        "status",
        "result",
        "criterion",
        "source",
        "reason",
    ):
        value = raw.get(key)
        if not isinstance(value, str):
            raise ValueError(
                f"bridge check {index} {key} is not typed text"
            )
        output[key] = value
    utilisation = raw.get("utilisation")
    output["utilisation"] = (
        None
        if utilisation is None
        else _real(
            utilisation,
            f"bridge check {index} utilisation",
        )
    )
    evidence = raw.get("evidence")
    if not isinstance(evidence, (list, tuple)):
        raise ValueError(
            f"bridge check {index} evidence is not a structured list"
        )
    output["evidence"] = _canonical_binding_value(
        evidence,
        path=f"bridge check {index} evidence",
    )
    return output


def bridge_evidence_fingerprint(
    checks: Sequence[Mapping],
    configuration_errors: Sequence[str] = (),
) -> str:
    """Return the immutable SHA-256 binding for a bridge assessment body."""

    if not isinstance(checks, (list, tuple)):
        raise ValueError("bridge checks are not a structured list")
    if not isinstance(configuration_errors, (list, tuple)) or not all(
        isinstance(item, str) for item in configuration_errors
    ):
        raise ValueError(
            "bridge configuration errors are not a typed text list"
        )
    body = {
        "schema": BRIDGE_EVIDENCE_SCHEMA,
        "methodology": EN1992_2_BASE,
        "checks": [
            _binding_check(raw, index=index)
            for index, raw in enumerate(checks, start=1)
        ],
        "configuration_errors": list(configuration_errors),
    }
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _with_evidence_binding(record: dict[str, Any]) -> dict[str, Any]:
    record["evidence_schema"] = BRIDGE_EVIDENCE_SCHEMA
    record["evidence_fingerprint"] = bridge_evidence_fingerprint(
        record.get("checks") or [],
        record.get("configuration_errors") or [],
    )
    return record


def _rule(check_id: str) -> CoverageRule:
    return next(rule for rule in COVERAGE_RULES if rule.check_id == check_id)


def _result(
    check_id: str,
    status: str,
    *,
    result: str = "-",
    criterion: str = "-",
    source: str = "",
    reason: str = "",
    utilisation: float | None = None,
    evidence: Sequence[Mapping[str, Any]] = (),
) -> BridgeCheckResult:
    rule = _rule(check_id)
    return BridgeCheckResult(
        check_id=check_id,
        title=rule.title,
        disposition=rule.disposition,
        status=status,
        result=result,
        criterion=criterion,
        source=source or rule.bridge_reference,
        reason=reason,
        utilisation=utilisation,
        evidence=tuple(dict(item) for item in evidence),
    )


def _decision_map(
    decisions: Sequence[ApplicabilityDecision],
) -> tuple[dict[str, ApplicabilityDecision], tuple[str, ...]]:
    found: dict[str, ApplicabilityDecision] = {}
    errors: list[str] = []
    for decision in decisions:
        check_id = str(decision.check_id or "").strip()
        if check_id not in APPLICABILITY_CHECK_IDS:
            errors.append(f"unknown bridge applicability check {check_id!r}")
            continue
        if check_id in found:
            errors.append(f"duplicate bridge applicability check {check_id!r}")
            continue
        found[check_id] = decision
    for check_id in APPLICABILITY_CHECK_IDS:
        found.setdefault(check_id, ApplicabilityDecision(check_id))
    return found, tuple(errors)


def _decision_gate(
    check_id: str,
    decision: ApplicabilityDecision,
    *,
    physically_required: bool = False,
) -> BridgeCheckResult | None:
    applicability = str(decision.applicability or "").strip()
    source = str(decision.source or "").strip()
    if applicability not in APPLICABILITY_OPTIONS:
        return _result(
            check_id,
            STATUS_NOT_ASSESSED,
            reason="Applicability token is unknown; select it again.",
        )
    if applicability == NOT_ESTABLISHED:
        return _result(
            check_id,
            STATUS_NOT_ASSESSED,
            reason="Project applicability is not established.",
        )
    if not source:
        return _result(
            check_id,
            STATUS_NOT_ASSESSED,
            reason="The applicability decision requires a project-basis source.",
        )
    if applicability == NOT_APPLICABLE:
        if physically_required:
            return _result(
                check_id,
                STATUS_NOT_ASSESSED,
                source=source,
                reason=(
                    "The model contains physical evidence that triggers this "
                    "bridge check; a not-applicable decision cannot be accepted."
                ),
            )
        return _result(
            check_id,
            STATUS_NOT_APPLICABLE,
            source=source,
            reason=str(decision.notes or "").strip() or "Explicitly not applicable.",
        )
    return None


def minimum_brittle_reinforcement_area(
    m_rep_knm: Any,
    z_s_m: Any,
    f_yk_mpa: Any,
) -> float:
    """Return Method-b ``As,min = Mrep / (zs fyk)`` in square millimetres."""

    moment = _real(m_rep_knm, "Mrep", positive=True)
    lever = _real(z_s_m, "zs", positive=True)
    strength = _real(f_yk_mpa, "fyk", positive=True)
    return 1000.0 * moment / (lever * strength)


def _assess_brittle(
    evidence: BridgeBaseEvidence,
    decision: ApplicabilityDecision,
) -> BridgeCheckResult:
    gate = _decision_gate(
        "prestress_brittle",
        decision,
        physically_required=bool(evidence.has_tendons),
    )
    if gate is not None:
        return gate
    if not evidence.has_tendons:
        return _result(
            "prestress_brittle",
            STATUS_NOT_APPLICABLE,
            source=decision.source,
            reason="The section contains no prestressing tendons.",
        )
    if evidence.brittle_method != BRITTLE_METHOD_B:
        if evidence.brittle_method in (BRITTLE_METHOD_A, BRITTLE_METHOD_C):
            reason = (
                f"{evidence.brittle_method} is recorded but is not calculated "
                "by Sector; retain the external verification as a review action."
            )
        else:
            reason = "Select the project-adopted 6.1(109) brittle-failure method."
        return _result(
            "prestress_brittle",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason=reason,
        )
    if not evidence.brittle_regions:
        return _result(
            "prestress_brittle",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason="Method b requires at least one tensile-region row.",
        )

    rows: list[dict[str, Any]] = []
    invalid: list[str] = []
    seen: set[str] = set()
    any_failure = False
    governing = 0.0
    for index, region in enumerate(evidence.brittle_regions, start=1):
        region_id = str(region.region_id or "").strip()
        if not region_id:
            invalid.append(f"row {index}: tensile-region ID is required")
            continue
        folded = region_id.casefold()
        if folded in seen:
            invalid.append(f"{region_id}: duplicate tensile-region ID")
            continue
        seen.add(folded)
        try:
            required = minimum_brittle_reinforcement_area(
                region.m_rep_knm,
                region.z_s_m,
                region.f_yk_mpa,
            )
            provided = _real(
                region.as_provided_mm2,
                f"{region_id}: As,provided",
                positive=True,
            )
        except ValueError as exc:
            invalid.append(str(exc))
            continue
        utilisation = required / provided
        governing = max(governing, utilisation)
        passed = provided + _TOL >= required
        any_failure = any_failure or not passed
        rows.append({
            "region_id": region_id,
            "m_rep_knm": float(region.m_rep_knm),
            "z_s_m": float(region.z_s_m),
            "f_yk_mpa": float(region.f_yk_mpa),
            "as_required_mm2": required,
            "as_provided_mm2": provided,
            "utilisation": utilisation,
            "status": STATUS_PASS if passed else STATUS_FAIL,
        })
    if any_failure:
        reason = "One or more tensile regions have insufficient Method-b steel."
        if invalid:
            reason += " Other rows are incomplete: " + "; ".join(invalid)
        return _result(
            "prestress_brittle",
            STATUS_FAIL,
            result=f"governing As,min / As,provided = {governing:.3f}",
            criterion="As,provided >= Mrep / (zs fyk) in every tensile region",
            source=decision.source,
            reason=reason,
            utilisation=governing,
            evidence=rows,
        )
    if invalid:
        return _result(
            "prestress_brittle",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason="; ".join(invalid),
            evidence=rows,
        )
    return _result(
        "prestress_brittle",
        STATUS_PASS,
        result=f"governing As,min / As,provided = {governing:.3f}",
        criterion="As,provided >= Mrep / (zs fyk) in every tensile region",
        source=decision.source,
        reason="Method b evaluated for every declared tensile region.",
        utilisation=governing,
        evidence=rows,
    )


def box_wall_interaction(
    v_ed_kn: Any,
    v_rd_max_kn: Any,
    t_ed_equivalent_kn: Any,
    t_rd_max_equivalent_kn: Any,
) -> float:
    """Return the per-wall linear shear-plus-torsion interaction."""

    v_ed = abs(_real(v_ed_kn, "wall VEd"))
    v_rd = _real(v_rd_max_kn, "wall VRd,max", positive=True)
    t_ed = abs(_real(t_ed_equivalent_kn, "wall torsion-equivalent action"))
    t_rd = _real(
        t_rd_max_equivalent_kn,
        "wall torsion-equivalent resistance",
        positive=True,
    )
    return v_ed / v_rd + t_ed / t_rd


def _assess_box_walls(
    evidence: BridgeBaseEvidence,
    decision: ApplicabilityDecision,
) -> BridgeCheckResult:
    physical = bool(evidence.has_hollow_section and evidence.box_walls)
    gate = _decision_gate(
        "box_wall_torsion",
        decision,
        physically_required=physical,
    )
    if gate is not None:
        return gate
    try:
        expected_number = _real(
            evidence.expected_box_walls,
            "expected box-wall count",
            positive=True,
        )
        expected = int(expected_number)
        if not math.isclose(expected_number, expected, abs_tol=0.0):
            raise ValueError("expected box-wall count must be an integer")
    except ValueError as exc:
        return _result(
            "box_wall_torsion",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason=str(exc),
        )
    if expected != len(evidence.box_walls):
        return _result(
            "box_wall_torsion",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason=(
                f"Expected {expected} wall rows but received "
                f"{len(evidence.box_walls)}."
            ),
        )

    rows: list[dict[str, Any]] = []
    invalid: list[str] = []
    seen: set[str] = set()
    cots: list[float] = []
    any_failure = False
    governing = 0.0
    for index, wall in enumerate(evidence.box_walls, start=1):
        wall_id = str(wall.wall_id or "").strip()
        if not wall_id:
            invalid.append(f"row {index}: wall ID is required")
            continue
        folded = wall_id.casefold()
        if folded in seen:
            invalid.append(f"{wall_id}: duplicate wall ID")
            continue
        seen.add(folded)
        try:
            cot = _real(
                wall.cot_theta,
                f"{wall_id}: cot(theta)",
                positive=True,
            )
            utilisation = box_wall_interaction(
                wall.v_ed_kn,
                wall.v_rd_max_kn,
                wall.t_ed_equivalent_kn,
                wall.t_rd_max_equivalent_kn,
            )
        except ValueError as exc:
            invalid.append(str(exc))
            continue
        cots.append(cot)
        governing = max(governing, utilisation)
        passed = utilisation <= 1.0 + _TOL
        any_failure = any_failure or not passed
        rows.append({
            "wall_id": wall_id,
            "cot_theta": cot,
            "v_ed_kn": float(wall.v_ed_kn),
            "v_rd_max_kn": float(wall.v_rd_max_kn),
            "t_ed_equivalent_kn": float(wall.t_ed_equivalent_kn),
            "t_rd_max_equivalent_kn": float(
                wall.t_rd_max_equivalent_kn
            ),
            "utilisation": utilisation,
            "status": STATUS_PASS if passed else STATUS_FAIL,
        })
    if cots and not all(
        math.isclose(cot, cots[0], rel_tol=0.0, abs_tol=1.0e-9)
        for cot in cots[1:]
    ):
        invalid.append(
            "Every box wall must use the same compression-field cot(theta)."
        )
    if any_failure:
        reason = "One or more box walls exceed the shear-plus-torsion limit."
        if invalid:
            reason += " Other wall evidence is incomplete: " + "; ".join(invalid)
        return _result(
            "box_wall_torsion",
            STATUS_FAIL,
            result=f"governing wall interaction = {governing:.3f}",
            criterion="VEd/VRd,max + TEd,wall/TRd,max,wall <= 1.0",
            source=decision.source,
            reason=reason,
            utilisation=governing,
            evidence=rows,
        )
    if invalid:
        return _result(
            "box_wall_torsion",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason="; ".join(invalid),
            evidence=rows,
        )
    return _result(
        "box_wall_torsion",
        STATUS_PASS,
        result=f"governing wall interaction = {governing:.3f}",
        criterion="VEd/VRd,max + TEd,wall/TRd,max,wall <= 1.0",
        source=decision.source,
        reason="Every declared box wall uses one common strut angle.",
        utilisation=governing,
        evidence=rows,
    )


def minimum_crack_reinforcement_area(
    act_mm2: Any,
    k_c: Any,
    k: Any,
    fct_eff_mpa: Any,
    sigma_s_mpa: Any,
    *,
    restrained_shrinkage: Any = False,
) -> tuple[float, float]:
    """Return ``(As,min, fct,eff used)`` for bridge Expression (7.1)."""

    act = _real(act_mm2, "Act", positive=True)
    kc = _real(k_c, "kc", positive=True)
    factor = _real(k, "k", positive=True)
    fct = _real(fct_eff_mpa, "fct,eff", positive=True)
    sigma = _real(sigma_s_mpa, "sigma_s", positive=True)
    if not isinstance(restrained_shrinkage, bool):
        raise ValueError("restrained_shrinkage must be Boolean")
    fct_used = max(fct, 2.9) if restrained_shrinkage else fct
    return kc * factor * fct_used * act / sigma, fct_used


def _required_minimum_components(scope: str) -> tuple[str, ...]:
    if scope == MINIMUM_SCOPE_WEB:
        return ("web",)
    if scope == MINIMUM_SCOPE_FLANGE:
        return ("flange",)
    if scope == MINIMUM_SCOPE_WEB_AND_FLANGE:
        return ("web", "flange")
    return ()


def _assess_minimum_components(
    evidence: BridgeBaseEvidence,
    decision: ApplicabilityDecision,
) -> BridgeCheckResult:
    gate = _decision_gate("web_flange_minimum", decision)
    if gate is not None:
        return gate
    required = _required_minimum_components(evidence.minimum_scope)
    if not required:
        return _result(
            "web_flange_minimum",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason="Select whether web, flange, or both components apply.",
        )

    rows: list[dict[str, Any]] = []
    invalid: list[str] = []
    seen: set[str] = set()
    any_failure = False
    governing = 0.0
    for index, component in enumerate(
        evidence.minimum_components,
        start=1,
    ):
        name = str(component.component or "").strip().casefold()
        if name not in {"web", "flange"}:
            invalid.append(f"row {index}: component must be Web or Flange")
            continue
        if name in seen:
            invalid.append(f"{name}: duplicate component row")
            continue
        seen.add(name)
        try:
            required_area, fct_used = minimum_crack_reinforcement_area(
                component.act_mm2,
                component.k_c,
                component.k,
                component.fct_eff_mpa,
                component.sigma_s_mpa,
                restrained_shrinkage=component.restrained_shrinkage,
            )
            provided = _real(
                component.as_provided_mm2,
                f"{name}: As,provided",
                positive=True,
            )
        except ValueError as exc:
            invalid.append(str(exc))
            continue
        utilisation = required_area / provided
        governing = max(governing, utilisation)
        passed = provided + _TOL >= required_area
        any_failure = any_failure or not passed
        rows.append({
            "component": name,
            "act_mm2": float(component.act_mm2),
            "k_c": float(component.k_c),
            "k": float(component.k),
            "fct_eff_input_mpa": float(component.fct_eff_mpa),
            "fct_eff_used_mpa": fct_used,
            "sigma_s_mpa": float(component.sigma_s_mpa),
            "as_required_mm2": required_area,
            "as_provided_mm2": provided,
            "restrained_shrinkage": component.restrained_shrinkage,
            "utilisation": utilisation,
            "status": STATUS_PASS if passed else STATUS_FAIL,
        })
    missing = [name for name in required if name not in seen]
    if missing:
        invalid.append("missing required component(s): " + ", ".join(missing))
    extra = [name for name in seen if name not in required]
    if extra:
        invalid.append(
            "component row is outside the selected applicability: "
            + ", ".join(extra)
        )
    if any_failure:
        reason = "One or more bridge components have insufficient crack steel."
        if invalid:
            reason += " Other component evidence is incomplete: " + "; ".join(
                invalid
            )
        return _result(
            "web_flange_minimum",
            STATUS_FAIL,
            result=f"governing As,min / As,provided = {governing:.3f}",
            criterion="As,provided >= kc k fct,eff Act / sigma_s separately",
            source=decision.source,
            reason=reason,
            utilisation=governing,
            evidence=rows,
        )
    if invalid:
        return _result(
            "web_flange_minimum",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason="; ".join(invalid),
            evidence=rows,
        )
    return _result(
        "web_flange_minimum",
        STATUS_PASS,
        result=f"governing As,min / As,provided = {governing:.3f}",
        criterion="As,provided >= kc k fct,eff Act / sigma_s separately",
        source=decision.source,
        reason="Every selected web/flange component is evaluated separately.",
        utilisation=governing,
        evidence=rows,
    )


def _external_result(
    check_id: str,
    evidence: ExternalEvidence,
    decision: ApplicabilityDecision,
    *,
    extra_reason: str = "",
    physically_required: bool = False,
) -> BridgeCheckResult:
    gate = _decision_gate(
        check_id,
        decision,
        physically_required=physically_required,
    )
    if gate is not None:
        return gate
    status = str(evidence.status or "").strip().upper()
    if status not in {
        STATUS_PASS,
        STATUS_FAIL,
        STATUS_INVALID,
        STATUS_NOT_ASSESSED,
        STATUS_NOT_APPLICABLE,
        STATUS_NOT_RUN,
        STATUS_REVIEW,
    }:
        status = STATUS_NOT_ASSESSED
    if status in {STATUS_NOT_RUN, STATUS_REVIEW}:
        status = STATUS_NOT_ASSESSED
    utilisation = None
    if evidence.utilisation is not None:
        try:
            utilisation = _real(evidence.utilisation, f"{check_id} utilisation")
        except ValueError:
            status = STATUS_INVALID
    reason = "; ".join(
        part
        for part in (
            str(evidence.reason or "").strip(),
            extra_reason,
        )
        if part
    )
    return _result(
        check_id,
        status,
        result=str(evidence.result or "-"),
        criterion=str(evidence.criterion or "-"),
        source=str(evidence.source or decision.source),
        reason=reason,
        utilisation=utilisation,
        evidence=evidence.evidence,
    )


def _assess_shear(
    evidence: BridgeBaseEvidence,
    decision: ApplicabilityDecision,
) -> BridgeCheckResult:
    gate = _decision_gate("bridge_shear_detailing", decision)
    if gate is not None:
        return gate
    if evidence.shear_scope == SHEAR_SCOPE_INTERFACE:
        return _result(
            "bridge_shear_detailing",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason=(
                "The project requires the added bridge web/interface model; "
                "Sector currently reports only inherited member shear."
            ),
        )
    if evidence.shear_scope != SHEAR_SCOPE_MEMBER:
        return _result(
            "bridge_shear_detailing",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason="Bridge shear scope is not established.",
        )
    return _external_result(
        "bridge_shear_detailing",
        evidence.shear,
        decision,
        extra_reason=(
            "Applicability records that the inherited member-shear provisions "
            "are sufficient for this section."
        ),
    )


def _assess_stress(
    evidence: BridgeBaseEvidence,
    decision: ApplicabilityDecision,
) -> BridgeCheckResult:
    gate = _decision_gate("sls_stress", decision)
    if gate is not None:
        return gate
    if evidence.bridge_exposure == BRIDGE_EXPOSURE_NOT_ESTABLISHED:
        return _result(
            "sls_stress",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason="Bridge exposure/applicability is not established.",
        )
    if evidence.bridge_exposure != BRIDGE_EXPOSURE_XD_XS:
        return _result(
            "sls_stress",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason=(
                "The required decision does not identify the XD/XF/XS "
                "application of the 0.60 fck criterion. Mark it not applicable "
                "with a source if the criterion does not apply."
            ),
        )
    try:
        fck = _real(evidence.fck_mpa, "fck", positive=True)
    except ValueError as exc:
        return _result(
            "sls_stress",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason=str(exc),
        )
    matched = [
        response
        for response in evidence.stress_responses
        if str(response.combination or "").strip().casefold()
        == "characteristic"
    ]
    if len(matched) != 1:
        return _result(
            "sls_stress",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason=(
                "Exactly one explicitly characteristic concrete-stress response "
                f"is required; found {len(matched)}."
            ),
        )
    response = matched[0]
    response_id = str(response.response_id or "").strip()
    provenance = str(response.solver_provenance or "").strip()
    if not response_id or not provenance:
        return _result(
            "sls_stress",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason="Characteristic response identity and solver provenance are required.",
        )
    if str(response.solver_status or "").strip().upper() != "CONVERGED":
        return _result(
            "sls_stress",
            STATUS_INVALID,
            source=decision.source,
            reason="The characteristic Elastic response did not converge.",
        )
    try:
        compression = _real(
            response.compression_mpa,
            "characteristic concrete compression",
        )
    except ValueError as exc:
        return _result(
            "sls_stress",
            STATUS_NOT_ASSESSED,
            source=decision.source,
            reason=str(exc),
        )
    limit = 0.60 * fck
    utilisation = compression / limit
    status = STATUS_PASS if compression <= limit + _TOL else STATUS_FAIL
    return _result(
        "sls_stress",
        status,
        result=f"{compression:.3f} MPa ({response_id})",
        criterion=f"characteristic concrete compression <= 0.60 fck = {limit:.3f} MPa",
        source=decision.source,
        reason=provenance,
        utilisation=utilisation,
        evidence=({
            "response_id": response_id,
            "combination": "Characteristic",
            "compression_mpa": compression,
            "limit_mpa": limit,
            "solver_status": response.solver_status,
            "solver_provenance": provenance,
        },),
    )


def _unsupported(
    check_id: str,
    decision: ApplicabilityDecision,
) -> BridgeCheckResult:
    gate = _decision_gate(check_id, decision)
    if gate is not None:
        return gate
    return _result(
        check_id,
        STATUS_NOT_ASSESSED,
        source=decision.source,
        reason=_rule(check_id).implementation,
    )


def _overall_status(checks: Sequence[BridgeCheckResult]) -> str:
    states = {check.status for check in checks}
    for status in (
        STATUS_INVALID,
        STATUS_FAIL,
        STATUS_REVIEW,
        STATUS_NOT_ASSESSED,
        STATUS_NOT_RUN,
        STATUS_PASS,
        STATUS_NOT_APPLICABLE,
    ):
        if status in states:
            return status
    return STATUS_NOT_ASSESSED


def assess_base_methodology(evidence: BridgeBaseEvidence) -> dict[str, Any]:
    """Assess the complete bridge-base coverage gate.

    The return value is JSON-safe and suitable for UI, project calculation
    records, autosave snapshots, and reports.  ``PASS`` means every applicability
    row was explicitly resolved and every required implemented check passed.  It
    is not a claim that Sector performs a complete bridge design.
    """

    if evidence.methodology != EN1992_2_BASE:
        return {
            "methodology": evidence.methodology,
            "active": False,
            "status": STATUS_NOT_APPLICABLE,
            "source": "",
            "coverage_matrix": coverage_matrix(),
            "checks": [],
            "configuration_errors": [],
        }
    decisions, decision_errors = _decision_map(evidence.decisions)
    configuration_errors = tuple(evidence.configuration_errors) + tuple(
        decision_errors
    )
    checks = [
        _external_result(
            "section_analysis",
            evidence.section_analysis,
            decisions["section_analysis"],
            physically_required=True,
        ),
        _assess_brittle(evidence, decisions["prestress_brittle"]),
        _assess_shear(evidence, decisions["bridge_shear_detailing"]),
        _assess_box_walls(evidence, decisions["box_wall_torsion"]),
        _external_result(
            "reinforcement_fatigue",
            evidence.reinforcement_fatigue,
            decisions["reinforcement_fatigue"],
        ),
        _external_result(
            "concrete_fatigue",
            evidence.concrete_fatigue,
            decisions["concrete_fatigue"],
        ),
        _unsupported(
            "shear_torsion_fatigue",
            decisions["shear_torsion_fatigue"],
        ),
        _assess_stress(evidence, decisions["sls_stress"]),
        _external_result(
            "sls_crack",
            evidence.sls_crack,
            decisions["sls_crack"],
        ),
        _assess_minimum_components(
            evidence,
            decisions["web_flange_minimum"],
        ),
        _unsupported("deflection", decisions["deflection"]),
        _unsupported("segmental_joints", decisions["segmental_joints"]),
    ]
    status = (
        STATUS_INVALID
        if configuration_errors
        else _overall_status(checks)
    )
    return _with_evidence_binding({
        "methodology": EN1992_2_BASE,
        "active": True,
        "status": status,
        "source": (
            "DS/EN 1992-2:2005 with EN 1992-2:2005/AC:2008; "
            "relevant DS/EN 1992-1-1:2004 clauses inherited explicitly"
        ),
        "coverage_matrix": coverage_matrix(),
        "checks": [check.to_dict() for check in checks],
        "configuration_errors": list(configuration_errors),
        "limitations": [
            rule.implementation
            for rule in COVERAGE_RULES
            if rule.disposition == DISPOSITION_NOT_ASSESSED
        ],
    })


def publication_safe_record(record: Mapping | None) -> dict[str, Any] | None:
    """Return a canonical fail-closed bridge calculation snapshot.

    Saved calculation records are provenance, not live solver results.  This
    boundary therefore discards stored coverage labels, recomputes aggregate
    status from the check bodies, and downgrades missing, duplicate or malformed
    evidence before a project, autosave or report may publish it.
    """

    if not isinstance(record, Mapping):
        return None
    if record.get("methodology") != EN1992_2_BASE:
        return None
    errors: list[str] = []
    raw_configuration = record.get("configuration_errors", ())
    if not isinstance(raw_configuration, (list, tuple)):
        errors.append(
            "stored bridge configuration errors are not a structured list"
        )
        raw_configuration_errors: list[str] = []
    else:
        raw_configuration_errors = []
        for index, item in enumerate(raw_configuration, start=1):
            if not isinstance(item, str):
                errors.append(
                    "stored bridge configuration error "
                    f"{index} is not typed text"
                )
            elif item:
                raw_configuration_errors.append(item)

    raw_checks = record.get("checks")
    if not isinstance(raw_checks, (list, tuple)):
        errors.append("stored bridge checks are not a structured list")
        raw_checks = ()
    expected = (
        "section_analysis",
        "prestress_brittle",
        "bridge_shear_detailing",
        "box_wall_torsion",
        "reinforcement_fatigue",
        "concrete_fatigue",
        "shear_torsion_fatigue",
        "sls_stress",
        "sls_crack",
        "web_flange_minimum",
        "deflection",
        "segmental_joints",
    )
    by_id: dict[str, Mapping] = {}
    for index, raw in enumerate(raw_checks, start=1):
        if not isinstance(raw, Mapping):
            errors.append(f"bridge check {index} is not an object")
            continue
        raw_check_id = raw.get("check_id")
        if not isinstance(raw_check_id, str):
            errors.append(f"bridge check {index} identity is not typed text")
            continue
        check_id = raw_check_id.strip()
        if check_id not in expected:
            errors.append(f"unknown bridge check {check_id!r}")
            continue
        if check_id in by_id:
            errors.append(f"duplicate bridge check {check_id!r}")
            continue
        by_id[check_id] = raw

    checks = []
    allowed = {
        STATUS_PASS,
        STATUS_FAIL,
        STATUS_INVALID,
        STATUS_NOT_ASSESSED,
        STATUS_NOT_APPLICABLE,
        STATUS_NOT_RUN,
        STATUS_REVIEW,
    }
    for check_id in expected:
        raw = by_id.get(check_id)
        if raw is None:
            errors.append(f"missing bridge check {check_id!r}")
            checks.append(_result(
                check_id,
                STATUS_NOT_ASSESSED,
                reason="Stored bridge evidence is missing.",
            ))
            continue
        raw_status = raw.get("status")
        local_errors: list[str] = []
        if not isinstance(raw_status, str):
            local_errors.append("stored status is not typed text")
            status = STATUS_NOT_ASSESSED
        else:
            status = raw_status.strip().upper()
        if status not in allowed:
            local_errors.append("stored status is unknown")
            status = STATUS_NOT_ASSESSED
        utilisation = raw.get("utilisation")
        if utilisation is not None:
            try:
                utilisation = _real(
                    utilisation,
                    f"{check_id} stored utilisation",
                )
            except ValueError as exc:
                local_errors.append(str(exc))
                utilisation = None
                status = STATUS_NOT_ASSESSED
        raw_evidence = raw.get("evidence")
        if not isinstance(raw_evidence, (list, tuple)):
            local_errors.append("stored evidence rows are malformed")
            raw_evidence = ()
            status = STATUS_NOT_ASSESSED
        elif not all(isinstance(item, Mapping) for item in raw_evidence):
            local_errors.append("stored evidence rows are malformed")
            raw_evidence = ()
            status = STATUS_NOT_ASSESSED
        else:
            try:
                raw_evidence = _canonical_binding_value(
                    raw_evidence,
                    path=f"{check_id} stored evidence",
                )
            except ValueError as exc:
                local_errors.append(str(exc))
                raw_evidence = ()
                status = STATUS_NOT_ASSESSED
        if (
            status in {STATUS_PASS, STATUS_FAIL}
            and check_id in {
                "prestress_brittle",
                "box_wall_torsion",
                "sls_stress",
                "web_flange_minimum",
            }
            and not raw_evidence
        ):
            local_errors.append(
                "stored PASS/FAIL lacks its calculated evidence rows"
            )
            status = STATUS_NOT_ASSESSED

        text_fields = {}
        for key in ("result", "criterion", "source", "reason"):
            value = raw.get(key)
            if not isinstance(value, str):
                local_errors.append(f"stored {key} is not typed text")
                value = ""
            text_fields[key] = value
        if not text_fields["source"].strip():
            local_errors.append("stored source is missing")
            status = STATUS_NOT_ASSESSED
        if status in {STATUS_PASS, STATUS_FAIL}:
            for key in ("result", "criterion"):
                if text_fields[key].strip() in {"", "-"}:
                    local_errors.append(
                        f"stored {key} is missing for PASS/FAIL"
                    )
                    status = STATUS_NOT_ASSESSED

        reason = text_fields["reason"].strip()
        if local_errors:
            reason = "; ".join((*local_errors, reason) if reason else local_errors)
            errors.extend(f"{check_id}: {item}" for item in local_errors)
        checks.append(_result(
            check_id,
            status,
            result=text_fields["result"] or "-",
            criterion=text_fields["criterion"] or "-",
            source=text_fields["source"],
            reason=reason,
            utilisation=utilisation,
            evidence=raw_evidence,
        ))

    canonical_checks = [check.to_dict() for check in checks]
    stored_schema = record.get("evidence_schema")
    stored_fingerprint = record.get("evidence_fingerprint")
    if stored_schema != BRIDGE_EVIDENCE_SCHEMA:
        errors.append("stored bridge evidence schema is missing or unknown")
    try:
        calculated_fingerprint = bridge_evidence_fingerprint(
            canonical_checks,
            raw_configuration_errors,
        )
    except ValueError as exc:
        calculated_fingerprint = ""
        errors.append(str(exc))
    if (
        not isinstance(stored_fingerprint, str)
        or stored_fingerprint != calculated_fingerprint
    ):
        errors.append(
            "stored bridge evidence fingerprint does not match its check bodies"
        )

    configuration_errors = list(dict.fromkeys(
        (*raw_configuration_errors, *errors)
    ))
    safe_status = (
        STATUS_INVALID
        if configuration_errors
        else _overall_status(checks)
    )
    return _with_evidence_binding({
        "methodology": EN1992_2_BASE,
        "active": True,
        "status": safe_status,
        "source": (
            "DS/EN 1992-2:2005 with EN 1992-2:2005/AC:2008; "
            "relevant DS/EN 1992-1-1:2004 clauses inherited explicitly"
        ),
        "coverage_matrix": coverage_matrix(),
        "checks": canonical_checks,
        "configuration_errors": configuration_errors,
        "limitations": [
            rule.implementation
            for rule in COVERAGE_RULES
            if rule.disposition == DISPOSITION_NOT_ASSESSED
        ],
    })
