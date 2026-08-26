"""Shared result-presentation helpers for the Streamlit UI and PDF report.

The functions in this module derive display-only assessment state and QA tables
from an already-computed analysis payload. They do not alter or repeat the
engineering solvers.
"""

from __future__ import annotations

from collections.abc import Mapping
import html
import math
from numbers import Real

import case_analysis
import fatigue_presentation
import viz

from app import engineer_messages
from app import modelled_direction
from sector.design_standards import get_design_basis
from sector.engineer_message import EngineerMessage

_DEGREE = chr(0x00B0)
_THETA = chr(0x03B8)
_RHO = chr(0x03C1)

_SINGLE_CASE_ID = "__single__"

_PLASTIC_ACTION_SET_REQUIRED = EngineerMessage(
    "PLASTIC-ACTION-SET",
    "Enter a Plastic action-set ID before calculating",
)
_ELASTIC_ACTION_SET_REQUIRED = EngineerMessage(
    "ELASTIC-ACTION-SET",
    "Enter an Elastic action-set ID before calculating",
)
_RESULT_REASON_FALLBACKS = {
    "plastic": EngineerMessage(
        "PLASTIC-RESULT-DETAIL",
        "Review the Plastic capacity envelope and applied actions",
    ),
    "minimum_reinforcement": EngineerMessage(
        "MINIMUM-REINFORCEMENT-DETAIL",
        "Review the minimum-reinforcement inputs and result status",
    ),
    "transverse_reinforcement": EngineerMessage(
        "TRANSVERSE-REINFORCEMENT-DETAIL",
        "Review the shear and torsion link-detailing inputs and result status",
    ),
    "shear": EngineerMessage(
        "SHEAR-RESULT-DETAIL",
        "Review the shear inputs and result status",
    ),
    "torsion": EngineerMessage(
        "TORSION-RESULT-DETAIL",
        "Review the torsion inputs and result status",
    ),
    "combined": EngineerMessage(
        "COMBINED-RESULT-DETAIL",
        "Review the combined M-V-T prerequisites and result status",
    ),
    "crack": EngineerMessage(
        "CRACK-RESULT-DETAIL",
        "Review the crack-width inputs and calculation status",
    ),
    "fatigue": EngineerMessage(
        "FATIGUE-RESULT-DETAIL",
        "Review the fatigue inputs and result status",
    ),
    "generic": EngineerMessage(
        "RESULT-DETAIL",
        "Review the calculation inputs and result status",
    ),
}
_PLASTIC_REASON_MESSAGES = {
    "M-M envelope coordinates are malformed or non-finite": EngineerMessage(
        "PLASTIC-ENVELOPE-COORDINATES",
        "The M-M capacity envelope contains an invalid coordinate; review the section inputs",
    ),
    "M-M envelope is self-intersecting, self-touching, or self-overlapping": EngineerMessage(
        "PLASTIC-ENVELOPE-TOPOLOGY",
        "The M-M capacity envelope does not form one valid closed boundary",
    ),
    "Global moment origin lies outside the closed M-M envelope": EngineerMessage(
        "PLASTIC-ENVELOPE-ORIGIN",
        "The closed M-M capacity envelope does not contain the zero-moment origin",
    ),
    "Applied moment components are non-finite": EngineerMessage(
        "PLASTIC-APPLIED-MOMENT",
        "Enter finite applied bending moments Mx,Ed and My,Ed",
    ),
    "Collapsed M-M envelope resistance is not finite and positive": EngineerMessage(
        "PLASTIC-COLLAPSED-ENVELOPE",
        "The collapsed M-M capacity envelope has no positive finite resistance",
    ),
    "No admissible positive M-M envelope intersection in the applied direction": EngineerMessage(
        "PLASTIC-ENVELOPE-INTERSECTION",
        "The applied moment direction has no admissible positive M-M capacity intersection",
    ),
    "Initial M-M envelope crossing interval is not numerically resolvable": EngineerMessage(
        "PLASTIC-INITIAL-CROSSING",
        "The initial M-M capacity-envelope crossing could not be resolved",
    ),
    "Applied ray initially leaves the admissible M-M envelope": EngineerMessage(
        "PLASTIC-APPLIED-RAY",
        "The applied moment ray immediately leaves the admissible M-M capacity envelope",
    ),
    "M-M envelope crossing interval is not numerically resolvable": EngineerMessage(
        "PLASTIC-CROSSING",
        "The governing M-M capacity-envelope crossing could not be resolved",
    ),
    "No verified inside-to-outside M-M envelope crossing in the applied direction": EngineerMessage(
        "PLASTIC-VERIFIED-CROSSING",
        "No verified M-M capacity-envelope boundary was found in the applied direction",
    ),
    "M-M envelope intersection is not finite and positive": EngineerMessage(
        "PLASTIC-FINITE-INTERSECTION",
        "The governing M-M capacity intersection is not positive and finite",
    ),
}
_MINIMUM_REINFORCEMENT_REASON_MESSAGES = {
    "No ordinary reinforcement bar lies in the tension zone.": EngineerMessage(
        "MINIMUM-REINFORCEMENT-TENSION-ZONE",
        "No ordinary reinforcement bar lies in the tension zone.",
    ),
    (
        "nominal resistance is too close to the cracking demand for a stable "
        "assessment at the available angular resolution"
    ): EngineerMessage(
        "MINIMUM-REINFORCEMENT-ANGULAR-RESOLUTION",
        "The nominal resistance is too close to the cracking demand for a stable "
        "assessment; assess this case separately",
    ),
    "nominal governing interval could not be refined consistently": EngineerMessage(
        "MINIMUM-REINFORCEMENT-GOVERNING-DIRECTION",
        "The governing nominal resistance direction could not be refined "
        "consistently; assess this case separately",
    ),
}
_TRANSVERSE_REASON_MESSAGES = {
    "minimum shear reinforcement is required for this beam": EngineerMessage(
        "TRANSVERSE-MINIMUM-LINKS",
        "Provide the minimum shear reinforcement required for this beam",
    ),
    "shear resistance without links is insufficient": EngineerMessage(
        "TRANSVERSE-LINKS-REQUIRED",
        "Provide shear links because the resistance without links is insufficient",
    ),
    "shear resistance without links is invalid": EngineerMessage(
        "TRANSVERSE-SHEAR-INVALID",
        "Review the shear resistance without links before assessing link detailing",
    ),
    "effective depth is unavailable for the 2023 minimum-link applicability check": EngineerMessage(
        "TRANSVERSE-EFFECTIVE-DEPTH",
        "Provide a valid effective depth for the 2023 minimum-link applicability check",
    ),
    "no active shear or torsion action requiring link-detailing checks": EngineerMessage(
        "TRANSVERSE-NOT-APPLICABLE",
        "No active shear or torsion action requires a link-detailing check",
    ),
    "gross web breadth exceeds the spacing limit; enter the actual maximum centre-to-centre leg spacing for a definitive assessment": EngineerMessage(
        "TRANSVERSE-LEG-SPACING",
        "Enter the actual maximum centre-to-centre leg spacing for a definitive assessment",
    ),
}
_SHEAR_REASON_MESSAGES = {
    "stirrups (VRd,s)": EngineerMessage(
        "SHEAR-GOVERNS-STIRRUPS",
        "stirrups (VRd,s)",
    ),
    "crushing (VRd,max)": EngineerMessage(
        "SHEAR-GOVERNS-CRUSHING",
        "crushing (VRd,max)",
    ),
    "the calculated face-aligned arm is unavailable": EngineerMessage(
        "SHEAR-LINK-ARM",
        "The face-aligned lever arm is unavailable; review the Plastic result and link inputs",
    ),
    "no shear check": EngineerMessage(
        "SHEAR-NOT-REQUESTED",
        "No shear calculation is available for this direction",
    ),
    "zero resistance": EngineerMessage(
        "SHEAR-ZERO-RESISTANCE",
        "The calculated shear resistance is zero",
    ),
    "exact calculated plastic lever arm z is unavailable": EngineerMessage(
        "SHEAR-LINK-ARM-UNAVAILABLE",
        "Calculate a valid Plastic lever arm before assessing the shear links",
    ),
    "invalid reinforced-shear input": EngineerMessage(
        "SHEAR-LINK-INPUT",
        "Review the reinforced-shear geometry, link reinforcement, and material inputs",
    ),
    "reinforced-shear prerequisite was not assessed": EngineerMessage(
        "SHEAR-LINK-PREREQUISITE",
        "Complete the reinforced-shear calculation before assessing the combined check",
    ),
    "calculated plastic lever arm unavailable: section model is not available": EngineerMessage(
        "SHEAR-LINK-SECTION",
        "The calculated Plastic lever arm is unavailable because the section model is not available",
    ),
    "calculated plastic lever arm unavailable: the exact face-aligned Plastic solve did not converge": EngineerMessage(
        "SHEAR-LINK-CONVERGENCE",
        "The exact face-aligned Plastic calculation did not converge, so the link lever arm is unavailable",
    ),
    "calculated plastic lever arm unavailable: the face-aligned tension-compression resultant arm is zero or degenerate": EngineerMessage(
        "SHEAR-LINK-DEGENERATE",
        "The face-aligned tension-compression resultant arm is zero or degenerate, so the link lever arm is unavailable",
    ),
}
_TORSION_REASON_MESSAGES = {
    "stirrups (TRd,s)": EngineerMessage(
        "TORSION-GOVERNS-STIRRUPS",
        "stirrups (TRd,s)",
    ),
    "crushing (TRd,max)": EngineerMessage(
        "TORSION-GOVERNS-CRUSHING",
        "crushing (TRd,max)",
    ),
    "closed_links_not_present": EngineerMessage(
        "TORSION-CLOSED-LINKS",
        "Closed torsion links are required before full torsion resistance can be assessed",
    ),
    "closed_link_reinforcement_not_positive": EngineerMessage(
        "TORSION-LINK-AREA",
        "Enter a positive closed-link reinforcement area before assessing torsion resistance",
    ),
    "full torsion resistance not assessed": EngineerMessage(
        "TORSION-NOT-ASSESSED",
        "Full torsion resistance has not been assessed",
    ),
    "torsion tube evidence is invalid": EngineerMessage(
        "TORSION-TUBE-INVALID",
        "The equivalent torsion tube is invalid; review the section geometry and torsion inputs",
    ),
    "torsion result is invalid": EngineerMessage(
        "TORSION-RESULT-INVALID",
        "The torsion result is invalid; review the section geometry and torsion inputs",
    ),
    "multi-cell (2+ voids)": EngineerMessage(
        "TORSION-MULTI-CELL",
        "The section contains multiple cells; subdivide it into single-cell torsion tubes",
    ),
    "compound outline requires subdivision": EngineerMessage(
        "TORSION-SUBDIVISION",
        "The compound outline requires subdivision before torsion can be assessed",
    ),
    "degenerate outline": EngineerMessage(
        "TORSION-DEGENERATE-OUTLINE",
        "The section outline cannot form a valid equivalent torsion tube",
    ),
    "wall exceeds section": EngineerMessage(
        "TORSION-WALL-THICKNESS",
        "The equivalent torsion-tube wall thickness exceeds the section geometry",
    ),
    "no outline": EngineerMessage(
        "TORSION-NO-OUTLINE",
        "A valid section outline is required for the torsion calculation",
    ),
}
_COMBINED_REASON_MESSAGES = {
    "no evaluable shared angle": EngineerMessage(
        "COMBINED-SHARED-ANGLE",
        "No common strut angle could be evaluated for the combined M-V-T check",
    ),
    "shared member-angle calculation is invalid": EngineerMessage(
        "COMBINED-MEMBER-ANGLE",
        "The common member-angle calculation is invalid; review the shear and torsion prerequisites",
    ),
    "Combined calculation is invalid": EngineerMessage(
        "COMBINED-INVALID",
        "The combined M-V-T calculation is invalid; review its prerequisites",
    ),
}
_CRACK_REASON_MESSAGES = {
    "Crack-width calculation was not requested for this Elastic case.": EngineerMessage(
        "CRACK-NOT-REQUESTED",
        "Crack-width calculation was not requested for this Elastic case",
    ),
    "The crack-width criterion must be a non-negative finite number.": EngineerMessage(
        "CRACK-LIMIT-NUMBER",
        "Enter a non-negative finite crack-width limit",
    ),
    "The user-specified crack-width criterion requires a nonblank criterion source.": EngineerMessage(
        "CRACK-LIMIT-SOURCE",
        "Enter the source of the user-specified crack-width limit",
    ),
    "No calculated crack width is available for assessment.": EngineerMessage(
        "CRACK-NO-RESULT",
        "No calculated crack width is available; review the Elastic case and crack-width inputs",
    ),
    "The long-term permitted crack width is 0 mm; no comparison was requested.": EngineerMessage(
        "CRACK-LONG-NO-COMPARISON",
        "The long-term crack width is reported without comparison because its limit is 0 mm",
    ),
    "The short-term permitted crack width is 0 mm; no comparison was requested.": EngineerMessage(
        "CRACK-SHORT-NO-COMPARISON",
        "The short-term crack width is reported without comparison because its limit is 0 mm",
    ),
    "The calculated crack width must be expressed in millimetres before comparison with the user-specified criterion.": EngineerMessage(
        "CRACK-RESULT-UNIT",
        "Express the calculated crack width in millimetres before comparing it with the limit",
    ),
    "The calculated crack width is within the user-specified limit.": EngineerMessage(
        "CRACK-WITHIN-LIMIT",
        "The calculated crack width is within the user-specified limit",
    ),
    "The calculated crack width exceeds the user-specified limit.": EngineerMessage(
        "CRACK-EXCEEDS-LIMIT",
        "The calculated crack width exceeds the user-specified limit",
    ),
    "Crack width was not requested for this run.": EngineerMessage(
        "CRACK-RUN-NOT-REQUESTED",
        "Crack width was not requested for this run.",
    ),
    "The selected action state is outside the validated ordinary crack-width scope.": EngineerMessage(
        "CRACK-ACTION-STATE-SCOPE",
        "The selected action state is outside the validated ordinary crack-width scope.",
    ),
    "Move every tendon far enough inside the physical top and bottom slab faces to provide non-negative clear cover before relying on crack-width results.": EngineerMessage(
        "CRACK-SLAB-TENDON-COVER",
        "Move every tendon far enough inside the physical top and bottom slab faces to provide non-negative clear cover before relying on crack-width results.",
    ),
    "Section uncracked; no width is available.": EngineerMessage(
        "CRACK-SECTION-UNCRACKED",
        "Section uncracked; no width is available.",
    ),
}
_FATIGUE_REASON_MESSAGES = {
    "No simplified fatigue-screen result is available": EngineerMessage(
        "FATIGUE-SCREEN-UNAVAILABLE",
        "No simplified fatigue-screen result is available",
    ),
    "No supported simplified fatigue rule is assigned": EngineerMessage(
        "FATIGUE-SCREEN-RULE",
        "No supported simplified fatigue rule is assigned to this detail",
    ),
    "Custom/imported fatigue details are not assigned a simplified limit": EngineerMessage(
        "FATIGUE-SCREEN-CUSTOM",
        "Custom fatigue details are not assigned a simplified stress-range limit",
    ),
    "Named fatigue detail does not belong to the selected design basis": EngineerMessage(
        "FATIGUE-SCREEN-DESIGN-BASIS",
        "The selected fatigue detail does not belong to the selected design basis",
    ),
    "The calculated cycle total is not finite": EngineerMessage(
        "FATIGUE-SCREEN-CYCLES",
        "The calculated fatigue cycle total is not finite",
    ),
    "One or more fatigue bins did not converge": EngineerMessage(
        "FATIGUE-SCREEN-CONVERGENCE",
        "One or more fatigue bins did not converge",
    ),
    "The calculated stress-range data are invalid": EngineerMessage(
        "FATIGUE-SCREEN-RANGE",
        "The calculated fatigue stress-range data are invalid",
    ),
    "The calculated stress ranges do not match the endpoint stresses": EngineerMessage(
        "FATIGUE-SCREEN-ENDPOINTS",
        "The calculated fatigue stress ranges do not match the endpoint stresses",
    ),
    "At least one fatigue bin has no tensile endpoint": EngineerMessage(
        "FATIGUE-SCREEN-TENSION",
        "At least one fatigue bin has no tensile stress endpoint",
    ),
    "Stress range is within the supported simplified limit": EngineerMessage(
        "FATIGUE-SCREEN-PASS",
        "The governing stress range is within the supported simplified limit",
    ),
    "Stress range exceeds the shortcut limit; detailed assessment governs": EngineerMessage(
        "FATIGUE-SCREEN-DETAILED",
        "The governing stress range exceeds the simplified limit; use the detailed assessment",
    ),
    "DS/EN 1992-1-1 6.8.6 shortcut covers unwelded or welded reinforcing bars in tension": EngineerMessage(
        "FATIGUE-FIRST-GENERATION-SCOPE",
        "DS/EN 1992-1-1 6.8.6 shortcut covers unwelded or welded reinforcing bars in tension",
    ),
    "DS/EN 1992-1-1:2023 10.4 does not assign this preset a simplified limit": EngineerMessage(
        "FATIGUE-PUBLISHED-2023-SCOPE",
        "DS/EN 1992-1-1:2023 10.4 does not assign this preset a simplified limit",
    ),
}
_RESULT_REASON_MESSAGES = {
    "plastic": _PLASTIC_REASON_MESSAGES,
    "minimum_reinforcement": _MINIMUM_REINFORCEMENT_REASON_MESSAGES,
    "transverse_reinforcement": _TRANSVERSE_REASON_MESSAGES,
    "shear": _SHEAR_REASON_MESSAGES,
    "torsion": _TORSION_REASON_MESSAGES,
    "combined": _COMBINED_REASON_MESSAGES,
    "crack": _CRACK_REASON_MESSAGES,
    "fatigue": _FATIGUE_REASON_MESSAGES,
}


def result_reason(value, family: str, *, context: str | None = None) -> str:
    """Publish one retained result reason only through positive provenance."""

    selected_family = family if family in _RESULT_REASON_FALLBACKS else "generic"
    return engineer_messages.resolve_state(
        value,
        authored=_RESULT_REASON_MESSAGES.get(selected_family, {}),
        fallback=_RESULT_REASON_FALLBACKS[selected_family],
        context=context or f"{selected_family} retained result reason",
    ).text

GOVERNING_OVERVIEW_STATUS_PRECEDENCE = (
    "INVALID",
    "FAIL",
    "EXCEEDS USER-SPECIFIED LIMIT",
    "PROVIDED AREA BELOW CALCULATED REQUIREMENT",
    "STALE",
    "REVIEW",
    "NOT ASSESSED",
    "CALCULATED - NO LIMIT COMPARISON",
    "PASS",
    "WITHIN USER-SPECIFIED LIMIT",
    "PROVIDED AREA AT LEAST CALCULATED REQUIREMENT",
    "CALCULATED",
    "NOT RUN",
    "NOT CALCULATED",
    "NOT APPLICABLE",
    "NOT REQUESTED",
)
_GOVERNING_OVERVIEW_STATUS_RANK = {
    status: rank
    for rank, status in enumerate(GOVERNING_OVERVIEW_STATUS_PRECEDENCE)
}
GOVERNING_OVERVIEW_INFORMATION_STATUSES = frozenset({
    "NOT RUN",
    "NOT CALCULATED",
    "NOT APPLICABLE",
    "NOT REQUESTED",
})


def _publication_metric(value, *, allow_positive_infinity=False):
    """Return one eligible retained publication-ranking metric."""
    if value is None:
        return None
    try:
        metric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(metric):
        return metric
    if allow_positive_infinity and metric == math.inf:
        return metric
    return None


def _publication_cases(out, family):
    """Return ordered named-case result payloads for one analysis family."""
    entries = (out or {}).get(f"{family}_cases")
    if entries is None:
        return [(_SINGLE_CASE_ID, out or {})]
    cases = []
    for entry in entries:
        name = str(entry.get("name") or (entry.get("actions") or {}).get("name") or "")
        if name:
            cases.append((name, entry.get("results") or {}))
    return cases


def plastic_result_predates_origin_contract(result):
    """Return whether a checked closed result lacks the radial-validity contract."""

    return (
        result.get("util_valid") is None
        and bool(result.get("check_util", True))
        and bool(result.get("closed", True))
    )


def combined_bending_assessment_blocker(results):
    """Return why retained combined evidence cannot trust a prerequisite."""

    results = results or {}
    combined = results.get("combined")
    torsion = results.get("torsion")
    if (
        combined is not None
        and isinstance(torsion, Mapping)
        and (
            "tube_valid" in torsion
            or "full_resistance_assessed" in torsion
        )
    ):
        if torsion.get("tube_valid") is not True:
            reason = result_reason(
                torsion.get("reason") or "torsion tube evidence is invalid",
                "torsion",
                context="combined prerequisite torsion-tube reason",
            )
        elif (
            "closed_links_present" in torsion
            and torsion.get("closed_links_present") is not True
        ):
            reason = result_reason(
                torsion.get("assessment_reason")
                or "closed_links_not_present",
                "torsion",
                context="combined prerequisite closed-links reason",
            )
        elif torsion.get("full_resistance_assessed") is not True:
            reason = result_reason(
                torsion.get("assessment_reason")
                or torsion.get("reason")
                or "full torsion resistance not assessed",
                "torsion",
                context="combined prerequisite torsion-assessment reason",
            )
        elif torsion.get("valid") is not True:
            reason = result_reason(
                torsion.get("reason") or "torsion result is invalid",
                "torsion",
                context="combined prerequisite torsion-result reason",
            )
        else:
            reason = ""
        if reason:
            return "Torsion prerequisite is not assessed: " + reason
    plastic = results.get("plastic")
    if (
        results.get("combined") is not None
        and isinstance(plastic, Mapping)
        and plastic_result_predates_origin_contract(plastic)
    ):
        return (
            "The saved bending result cannot confirm that the M-M envelope "
            "contains the origin. Recalculate before assessing M-V-T interaction."
        )
    return None


def _transverse_metric(family, result):
    """Rank an already-computed shear, torsion or combined result."""
    def shear_metric(item):
        links = item.get("links") or {}
        if links:
            if not (links.get("res") or {}).get("valid"):
                return None
            return _publication_metric(
                links.get("util"), allow_positive_infinity=True
            )
        if not (item.get("res") or {}).get("valid"):
            return None
        return _publication_metric(item.get("util"), allow_positive_infinity=True)

    def combined_metric(item):
        if not item.get("valid"):
            return None
        return _publication_metric(
            item.get("dkna_sum"), allow_positive_infinity=True
        )

    directions = result.get("directions") or {}
    if family in {"shear", "combined"}:
        items = [directions[key] for key in ("vx", "vy") if key in directions]
        if not items:
            items = [result]
        extractor = shear_metric if family == "shear" else combined_metric
        values = [metric for item in items if (metric := extractor(item)) is not None]
    else:
        metric = (
            _publication_metric(result.get("util"), allow_positive_infinity=True)
            if result.get("valid") else None
        )
        values = [] if metric is None else [metric]
    return max(values) if values else None


def _transverse_direction(family, result):
    """Return the retained governing direction, with first-direction tie-break."""
    best = None
    for order, component in enumerate(("vx", "vy")):
        item = (result.get("directions") or {}).get(component)
        if not item:
            continue
        metric = _transverse_metric(family, item)
        if metric is None:
            continue
        score = (metric, -order)
        if best is None or score > best[0]:
            best = (score, component)
    return None if best is None else best[1]


def _worked_family_selection(out, family):
    """Select one named case and any required direction for a worked family."""
    context_family = "plastic" if family in {"shear", "torsion", "combined"} else family
    best = None
    for order, (case_id, case_out) in enumerate(_publication_cases(out, context_family)):
        if family == "combined" and combined_bending_assessment_blocker(case_out):
            continue
        result = case_out.get(family)
        if not result:
            continue
        direction = None
        if family == "plastic":
            if not result.get("converged"):
                continue
            assessment = plastic_action_assessment(result)
            utilisation = _publication_metric(
                assessment.get("util"), allow_positive_infinity=True
            )
            if utilisation is not None:
                score = (2, utilisation, -order)
            else:
                values = [
                    metric
                    for name in ("max_mx", "min_mx", "max_my", "min_my")
                    if (metric := _publication_metric(result.get(name))) is not None
                ]
                if not values:
                    continue
                score = (1, max(abs(value) for value in values), -order)
        elif family in {"shear", "torsion", "combined"}:
            metric = _transverse_metric(family, result)
            if metric is None:
                continue
            score = (2, metric, -order)
            if family in {"shear", "combined"} and result.get("directions"):
                direction = _transverse_direction(family, result)
                if direction is None:
                    continue
        else:
            if not result.get("converged"):
                continue
            values = [
                metric
                for name in ("max_conc", "max_steel")
                if (metric := _publication_metric(result.get(name))) is not None
            ]
            if not values:
                continue
            score = (1, max(abs(value) for value in values), -order)
        if best is None or score > best[0]:
            best = (score, {"case_id": case_id, "component": direction})
    return None if best is None else best[1]


def _worked_check_selection(out, key):
    """Select one named detailing case from retained check utilisations."""
    best = None
    for order, (case_id, case_out) in enumerate(_publication_cases(out, "plastic")):
        result = case_out.get(key)
        if not result:
            continue
        values = [
            metric
            for check in result.get("checks") or ()
            if check.get("status") in {"PASS", "FAIL"}
            and (metric := _publication_metric(
                check.get("utilisation"), allow_positive_infinity=True
            )) is not None
        ]
        stored = _publication_metric(
            result.get("governing_utilisation"), allow_positive_infinity=True
        )
        if result.get("status") in {"PASS", "FAIL"} and stored is not None:
            values.append(stored)
        if not values:
            continue
        score = (max(values), -order)
        if best is None or score > best[0]:
            best = (score, {"case_id": case_id})
    return None if best is None else best[1]


def _worked_crack_selection(out):
    """Select the global ordinary or fine/coarse crack-width branches."""
    cases = _publication_cases(out, "elastic")
    has_coarse = any(
        (case_out.get("elastic") or {}).get(key) is not None
        for _, case_out in cases
        for key in ("crack_coarse", "crack_short_coarse")
    )
    systems = (
        (
            ("fine", (("crack", "long-term (fine)"),
                      ("crack_short", "short-term (fine)"))),
            ("coarse", (("crack_coarse", "long-term (coarse)"),
                        ("crack_short_coarse", "short-term (coarse)"))),
        )
        if has_coarse else
        (("governing", (("crack", "long-term"),
                        ("crack_short", "short-term"))),)
    )
    selected = []
    for system, branches in systems:
        best = None
        for case_order, (case_id, case_out) in enumerate(cases):
            elastic = case_out.get("elastic") or {}
            if not elastic.get("converged"):
                continue
            for branch_order, (branch, label) in enumerate(branches):
                crack = elastic.get(branch)
                value = _publication_metric((crack or {}).get("wk"))
                if value is None or value < 0.0:
                    continue
                score = (value, -case_order, -branch_order)
                if best is None or score > best[0]:
                    best = (score, {
                        "case_id": case_id,
                        "system": system,
                        "branch": branch,
                        "label": label,
                    })
        if best is not None:
            selected.append(best[1])
    return selected


def _worked_crack_comparison_selection(out):
    """Select a comparison only when the largest retained width is assessed.

    The optional comparison must not change which physical crack result is
    critical.  In particular, a smaller width paired with a tighter user limit
    must not displace the largest calculated width or create another worked
    chapter when that global width has no user criterion.
    """
    best = None
    assessed_states = {
        "WITHIN USER-SPECIFIED LIMIT",
        "EXCEEDS USER-SPECIFIED LIMIT",
    }
    for order, (case_id, case_out) in enumerate(_publication_cases(out, "elastic")):
        elastic = case_out.get("elastic") or {}
        outputs = elastic.get("crack_output") or {}
        for duration_order, duration in enumerate(("long_term", "short_term")):
            output = outputs.get(duration) or {}
            value = _publication_metric(output.get("value"))
            if value is None or value < 0.0:
                continue
            score = (value, -order, -duration_order)
            if best is None or score > best[0]:
                best = (
                    score,
                    case_id,
                    duration,
                    output.get("calculation_state"),
                )
    if best is None or best[3] not in assessed_states:
        return None
    return {"case_id": best[1], "duration": best[2]}


def _cracking_threshold_selection(out):
    best = None
    for order, (case_id, case_out) in enumerate(_publication_cases(out, "elastic")):
        elastic = case_out.get("elastic") or {}
        value = _publication_metric(elastic.get("lambda_cr"))
        if not elastic.get("converged") or value is None or value < 0.0:
            continue
        score = (-value, -order)
        if best is None or score > best[0]:
            best = (score, {"case_id": case_id})
    return None if best is None else best[1]


def _torsion_subcheck_selection(out):
    """Select each valid retained torsion subcheck, accepting governing +inf."""
    selected = {}
    for case_order, (case_id, case_out) in enumerate(_publication_cases(out, "plastic")):
        torsion = case_out.get("torsion") or {}
        directional = torsion.get("directional_interactions") or {}
        items = [(key, directional[key]) for key in ("vx", "vy") if key in directional]
        if not items:
            items = [(None, torsion)]
        for direction_order, (component, item) in enumerate(items):
            for key, payload_key, eligible in (
                ("interaction", "interaction", lambda value: value.get("valid")),
                ("minimum_reinforcement", "min_reinf",
                 lambda value: value.get("applicable")),
            ):
                payload = item.get(payload_key) or {}
                value = _publication_metric(
                    payload.get("value"), allow_positive_infinity=True
                )
                if not eligible(payload) or value is None:
                    continue
                score = (value, -case_order, -direction_order)
                if key not in selected or score > selected[key][0]:
                    selected[key] = (score, {
                        "case_id": case_id,
                        "component": component,
                    })
    return {key: item[1] for key, item in selected.items()}


def worked_example_selection(inp, out):
    """Build the bounded, family-specific worked-example publication contract.

    This is called once after analysis assembly. It selects identities only and
    never changes or recomputes an engineering result.
    """
    del inp  # reserved for future publication options; results own all rankings
    families = {
        family: _worked_family_selection(out, family)
        for family in ("plastic", "elastic", "shear", "torsion", "combined")
    }
    families.update({
        key: _worked_check_selection(out, key)
        for key in ("minimum_reinforcement", "transverse_reinforcement")
    })
    return {
        "schema": 1,
        "families": {key: value for key, value in families.items() if value is not None},
        "crack_examples": _worked_crack_selection(out),
        "crack_comparison": _worked_crack_comparison_selection(out),
        "cracking_threshold": _cracking_threshold_selection(out),
        "torsion_subchecks": _torsion_subcheck_selection(out),
        "heightened_crack_control": (
            {"result_key": "heightened_crack_control"}
            if isinstance((out or {}).get("heightened_crack_control"), Mapping)
            else None
        ),
    }


def plastic_action_assessment(pl):
    """Return the semantic status for a plastic M-M applied-action result.

    A utilisation verdict is valid only for a converged, closed envelope with the
    applied-action check enabled. Capacity-only and partial-sweep results remain
    useful capacity evidence, but are explicitly not assessments.
    """
    checked = bool(pl.get("check_util", True))
    complete = bool(pl.get("closed", True))
    converged = bool(pl.get("converged", True))
    util = pl.get("util")

    if not converged:
        status = "INVALID"
        detail = "Neutral-axis sweep did not converge; values are diagnostic only"
    elif not checked:
        status = "NOT ASSESSED"
        detail = "Capacity only; applied-moment check disabled"
    elif not complete:
        status = "NOT ASSESSED"
        detail = (
            f"Open arc; close the 360{_DEGREE} envelope to assess utilisation"
        )
    elif pl.get("util_valid") is False:
        status = "INVALID"
        detail = result_reason(
            pl.get("util_reason"),
            "plastic",
            context="plastic utilisation reason",
        )
    elif plastic_result_predates_origin_contract(pl):
        status = "NOT ASSESSED"
        detail = (
            "The saved result cannot confirm that the M-M envelope contains "
            "the origin; recalculate"
        )
    elif util is None:
        status = "NOT ASSESSED"
        detail = "The closed envelope has no available utilisation result"
    elif not math.isfinite(util):
        status = "FAIL"
        detail = "No finite capacity intersection"
    elif viz.util_ok(util):
        status = "PASS"
        detail = ""
    else:
        status = "FAIL"
        detail = ""

    assessed = status in {"PASS", "FAIL"}
    margin = (1.0 - util
              if assessed and util is not None and math.isfinite(util)
              else None)
    gov_i = pl.get("util_gov")
    points = pl.get("points") or []
    gov_angle = (
        points[gov_i].get("V")
        if isinstance(gov_i, int) and 0 <= gov_i < len(points)
        else None
    )
    return {
        "status": status,
        "detail": detail,
        "util": util if assessed else None,
        "margin": margin,
        "governing_angle": gov_angle,
        "assessed": assessed,
    }


def plastic_assessment_text(assessment):
    """Return one compact, solver-neutral plastic-bending verdict."""
    parts = [f"{assessment.get('status', 'NOT ASSESSED')} - Plastic bending"]
    util = assessment.get("util")
    if assessment.get("assessed"):
        if util is not None and math.isfinite(util):
            parts.append(f"utilisation {util * 100:.1f} %")
        else:
            parts.append("utilisation not finite")
    if assessment.get("detail"):
        parts.append(str(assessment["detail"]))
    return " | ".join(parts)


def plastic_state_rows(point):
    """Return retained rows for one accepted plastic state.

    The calculation family has already evaluated every material response.  This
    helper only exposes those immutable rows and reconstructs the neutral-axis
    line used for drawing; it never calls a material law or repeats a solver.
    """

    return {
        "halfplane": viz.plastic_halfplane(
            point["V"], point["na_x"], point["na_y"],
        ),
        "concrete": list(point.get("concrete_corner_states") or ()),
        "elements": list(point.get("reinforcement_states") or ()),
    }


def plastic_compression_depth_mm(point):
    """Return only the retained plastic compression-zone depth in millimetres."""

    if not isinstance(point, Mapping):
        return None
    value = point.get("compression_depth")
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        depth_m = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(depth_m) or depth_m < 0.0:
        return None
    if depth_m == 0.0:
        return 0.0
    depth_mm = depth_m * 1000.0
    return depth_mm if math.isfinite(depth_mm) else None


def nm_boundary_rows(interaction):
    """Return a point-by-point table for both numerical N-M boundaries."""
    x_data = (interaction or {}).get("x") or {}
    y_data = (interaction or {}).get("y") or {}
    x_n, x_m = list(x_data.get("N") or []), list(x_data.get("M") or [])
    y_n, y_m = list(y_data.get("N") or []), list(y_data.get("M") or [])
    count = max(len(x_n), len(x_m), len(y_n), len(y_m))

    def at(values, index):
        return values[index] if index < len(values) else None

    return [
        {
            "Point": index + 1,
            "N, Mx boundary (kN)": at(x_n, index),
            "Mx (kNm)": at(x_m, index),
            "N, My boundary (kN)": at(y_n, index),
            "My (kNm)": at(y_m, index),
        }
        for index in range(count)
    ]


def action_set(inp, family):
    """Return one normalised action-set record from a current input payload."""
    key = "elastic_case" if family == "elastic" else "plastic_case"
    record = (inp or {}).get(key) or {}
    return {
        "id": str(record.get("id") or "").strip(),
        "type": str(record.get("type") or "").strip(),
        "source": str(record.get("source") or "").strip(),
    }


def action_set_text(inp, family, *, include_source=True):
    record = action_set(inp, family)
    text = record["id"] or "ID NOT SET"
    if record["type"]:
        text += f" | {record['type']}"
    if include_source and record["source"]:
        text += f" | Source: {record['source']}"
    return text


def shear_geometry_basis(inp, shear_result):
    """Describe the retained ``d``/``z`` values and their calculation roles."""

    item = shear_result or {}
    result = item.get("res") or {}
    links = item.get("links") or {}
    link_result = links.get("res") or {}
    d_mm = _publication_metric(item.get("d"))
    d_text = "-" if d_mm is None else f"{d_mm:.3f} mm"
    d_note = "effective depth used in V<sub>Rd,c</sub>"

    if links:
        z_mm = _publication_metric(link_result.get("z"))
        if not link_result.get("valid") or z_mm is None or z_mm <= 0.0:
            reason = result_reason(
                links.get("assessment_reason")
                or link_result.get("reason")
                or "the calculated face-aligned arm is unavailable",
                "shear",
                context="shear geometry-basis link reason",
            )
            return {
                "z_mm": None,
                "d_note": d_note,
                "z_note": None,
                "statement": (
                    f"Effective depth d = {d_text} is used in V_Rd,c. "
                    f"The links resistance is not assessed: {reason}."
                ),
            }
        component = str(links.get("z_component") or (
            "z_y" if item.get("axis") == "x" else "z_x"
        ))
        case_id = str(links.get("z_source_case") or "").strip()
        if not case_id:
            case_id = action_set(inp, "plastic")["id"] or "Plastic action set"
        case_id_html = html.escape(case_id, quote=True)
        face = viz.tension_face_label(
            item.get("tension_low", True), item.get("axis")
        )
        angle = _publication_metric(links.get("z_source_angle_deg"))
        state = f"{face} face-aligned state"
        if angle is not None:
            state = f"{face} {angle:.0f}{_DEGREE} state"
        return {
            "z_mm": z_mm,
            "d_note": d_note,
            "z_note": (
                f"|{component}| from {case_id_html}, {state}<br>"
                "used in V<sub>Rd,s</sub> and V<sub>Rd,max</sub>"
            ),
            "statement": (
                f"Calculated arm z = {z_mm:.3f} mm = |{component}| from "
                f"{case_id}, {state}; used in V_Rd,s and V_Rd,max. "
                f"Effective depth d = {d_text} is used in V_Rd,c."
            ),
        }

    z_mm = _publication_metric(result.get("z"))
    if item.get("model_2023") and z_mm is not None and z_mm > 0.0:
        return {
            "z_mm": z_mm,
            "d_note": "defines z = 0.9d",
            "z_note": (
                "0.9d per DS/EN 1992-1-1:2023 8.2.1(3)<br>"
                "used in V<sub>Rd,c</sub>"
            ),
            "statement": (
                f"Standard-defined arm z = {z_mm:.3f} mm = 0.9d per "
                "DS/EN 1992-1-1:2023 8.2.1(3); used in V_Rd,c."
            ),
        }
    return {
        "z_mm": None,
        "d_note": d_note,
        "z_note": None,
        "statement": (
            f"Effective depth d = {d_text} is used in V_Rd,c; the selected "
            "2005 no-links resistance has no z operand."
        ),
    }


def required_action_set_errors(inp):
    """Return missing required Plastic/Elastic action-set identifiers."""
    mode = str((inp or {}).get("mode") or "")
    plastic_active = (
        mode in {"Plastic", "Both"}
        or bool((inp or {}).get("shear_on"))
        or bool((inp or {}).get("torsion_on"))
        or bool((inp or {}).get("combined_on"))
    )
    elastic_active = mode in {"Elastic", "Both"}
    errors = []
    if plastic_active and not action_set(inp, "plastic")["id"]:
        errors.append(_PLASTIC_ACTION_SET_REQUIRED)
    if elastic_active and not action_set(inp, "elastic")["id"]:
        errors.append(_ELASTIC_ACTION_SET_REQUIRED)
    return errors


def _summary_row(
    check,
    family,
    status,
    result="-",
    criterion="-",
    util=None,
    view="-",
    note="",
    inp=None,
    *,
    overview_key=None,
    overview_parent=None,
    overview_placeholder=False,
):
    case = action_set(inp, family)
    row = {
        "check": check,
        "family": family,
        "case": case["id"] or "-",
        "case_type": case["type"] or "-",
        "source": case["source"] or "-",
        "status": status,
        "result": result,
        "criterion": criterion,
        "util": util,
        "view": view,
        "note": note,
    }
    if overview_key is not None:
        row["overview_key"] = str(overview_key)
    if overview_parent is not None:
        row["overview_parent"] = str(overview_parent)
    if overview_placeholder:
        row["overview_placeholder"] = True
    return row


def _ordinary_crack_summary_row(inp, output):
    """Format one retained duration-specific output without deriving a verdict."""
    status = str(output.get("calculation_state") or "NOT ASSESSED")
    value = _publication_metric(output.get("value"))
    criterion = _publication_metric(output.get("criterion_mm"))
    ratio = _publication_metric(output.get("ratio"))
    result = "-" if value is None else f"{value:.3f} mm"
    if criterion is None:
        criterion_text = "User criterion not specified"
    elif criterion == 0.0:
        criterion_text = "No comparison requested"
    else:
        criterion_text = f"User-specified limit {criterion:.3f} mm"
    note_parts = [
        str(output.get(key) or "").strip()
        for key in ("reason", "case", "governing", "criterion_source")
    ]
    if ratio is not None:
        note_parts.append(f"w_k / w_k,criterion = {ratio:.3f}")
    duration = str(output.get("duration") or "").strip()
    duration_label = {
        "long_term": "Long-term",
        "short_term": "Short-term",
    }.get(duration, "Unspecified duration")
    return _summary_row(
        f"Crack width - {duration_label}",
        "elastic",
        status,
        result,
        criterion_text,
        None,
        "Elastic Results",
        "; ".join(part for part in note_parts if part),
        inp,
        overview_key=f"crack_width:{duration or 'unspecified'}",
        overview_parent="crack_width",
    )


def _heightened_crack_summary_row(result):
    """Format both retained Formula 7.100 NA area comparisons."""
    fine = result.get("fine") if isinstance(result.get("fine"), Mapping) else {}
    coarse = (
        result.get("coarse")
        if isinstance(result.get("coarse"), Mapping)
        else {}
    )
    fine_required = _publication_metric(
        fine.get("required_reinforcement_area_mm2")
    )
    coarse_required = _publication_metric(
        coarse.get("required_reinforcement_area_mm2")
    )
    provided = _publication_metric(result.get("provided_reinforcement_area_mm2"))
    ratio = _publication_metric(result.get("governing_comparison_ratio"))
    result_text = (
        f"Fine As,req {fine_required:.1f} mm2; coarse As,req "
        f"{coarse_required:.1f} mm2; As,prov {provided:.1f} mm2"
        if fine_required is not None
        and coarse_required is not None
        and provided is not None
        else "-"
    )
    note = (
        f"Reference {result.get('reference_case_id') or '-'} / "
        f"{result.get('ordinary_crack_branch') or '-'}; governing "
        f"{result.get('governing_crack_system') or '-'}; "
        + str(result.get("disclosure") or result.get("source") or "")
    )
    if ratio is not None:
        note = f"As,req / As,prov = {ratio:.3f}; {note}".rstrip("; ")
    return _summary_row(
        "DK heightened crack-control minimum",
        "elastic",
        str(result.get("governing_status") or "NOT ASSESSED"),
        result_text,
        "User-declared Formula 7.100 NA applicability",
        None,
        "Elastic Results",
        note,
        None,
        overview_key="heightened_crack_control",
    )


def _util_summary_status(util, *, valid=True):
    if not valid:
        return "INVALID"
    if util is None:
        return "NOT ASSESSED"
    if not math.isfinite(util):
        return "FAIL"
    return "PASS" if viz.util_ok(util) else "FAIL"


def _map_assessment_status(status):
    return {
        "OK": "PASS",
        "EXCEEDED": "FAIL",
        "PASS": "PASS",
        "FAIL": "FAIL",
        "INVALID": "INVALID",
        "NOT ASSESSED": "NOT ASSESSED",
        "NOT APPLICABLE": "NOT APPLICABLE",
        "NOT CALCULATED": "NOT CALCULATED",
        "CALCULATED": "CALCULATED",
        "REVIEW": "REVIEW",
    }.get(str(status or "").upper(), "NOT ASSESSED")


def assessment_status_label(status):
    """Map solver-specific acceptance states to the UI/report vocabulary."""
    return _map_assessment_status(status)


def minimum_area_check(minimum, check):
    """Identify a 2005-family Formula (9.1N) result, including failed rows."""
    return bool(
        str((check or {}).get("type") or "").casefold() == "minimum area"
        or "9.1n" in str((minimum or {}).get("clause") or "").casefold()
    )


def interaction_assessment_status(interaction):
    """Acceptance state for a mathematically valid V+T interaction."""
    interaction = interaction or {}
    value = interaction.get("value")
    if not interaction.get("valid") or value is None:
        return "NOT ASSESSED"
    value = float(value)
    if not math.isfinite(value):
        return "FAIL"
    return "PASS" if value <= 1.0 + 1.0e-9 else "FAIL"


def _percent(util):
    if util is None:
        return "-"
    return "infinite" if not math.isfinite(util) else f"{util * 100:.1f} %"


def required_chord_fallback(payload):
    """Return the retained required face using a pure-axis fallback, if any."""
    payload = payload or {}
    fallback = payload.get("longitudinal_fallback")
    return fallback if isinstance(fallback, dict) else None


def combined_physical_components(combined):
    """Return the three auditable physical M-V-T component assessments.

    The solver keeps a maximum across mechanisms for angle optimisation and the
    overall case status. Presentation must not call that maximum a transverse-
    reinforcement utilisation: concrete strut crushing, closed-stirrup demand and
    longitudinal-chord demand are different physical checks.
    """
    combined = combined or {}
    transverse = combined.get("transverse")
    if transverse is None:
        missing_note = "Shear links are required for the combined component checks"
        concrete = {
            "key": "concrete",
            "label": "Concrete compression strut",
            "status": "NOT ASSESSED",
            "util": None,
            "valid": False,
            "note": missing_note,
        }
        stirrup = {
            "key": "stirrup",
            "label": "Closed stirrup",
            "status": "NOT ASSESSED",
            "util": None,
            "valid": False,
            "note": missing_note,
        }
    else:
        transverse_valid = bool(transverse.get("valid"))
        concrete_util = transverse.get("u_crush")
        stirrup_util = transverse.get("u_stirrup")
        try:
            cot = float(transverse.get("cot"))
        except (TypeError, ValueError):
            cot = None
        concrete = {
            "key": "concrete",
            "label": "Concrete compression strut",
            "status": _util_summary_status(
                concrete_util,
                valid=transverse_valid,
            ),
            "util": concrete_util,
            "valid": transverse_valid,
            "note": (
                f"V-T crushing at cot {_THETA} = {cot:.2f}"
                if transverse_valid and cot is not None
                else "V-T crushing at the shared member angle"
                if transverse_valid
                else "Combined strut check is invalid"
            ),
        }
        stirrup = {
            "key": "stirrup",
            "label": "Closed stirrup",
            "status": _util_summary_status(
                stirrup_util,
                valid=transverse_valid,
            ),
            "util": stirrup_util,
            "valid": transverse_valid,
            "note": (
                f"Shear {_percent(transverse.get('shear_fraction'))} + "
                f"torsion {_percent(transverse.get('torsion_fraction'))}"
                if transverse_valid else "Combined stirrup check is invalid"
            ),
        }

    longitudinal = combined.get("longitudinal")
    chord_off = combined.get("chord_off")

    governing = combined.get("governing_longitudinal")
    if not isinstance(governing, dict) or not governing.get("valid"):
        governing = None
    coverage = (
        longitudinal.get("off_not_evaluated")
        if longitudinal is not None else None
    )
    conditional = bool(combined.get("longitudinal_all_conditional"))
    main_valid = bool(longitudinal is not None and longitudinal.get("valid"))
    long_valid = governing is not None and main_valid
    long_util = governing.get("util") if governing is not None else None
    if not main_valid:
        long_status = "NOT ASSESSED"
        long_note = "No valid shear-axis longitudinal chord check"
    elif not long_valid:
        long_status = "NOT ASSESSED"
        long_note = "No valid longitudinal chord check"
    elif coverage:
        long_status = "NOT ASSESSED"
        long_note = (
            "Incomplete chord coverage for a subdivided section"
            if coverage == "subdivided"
            else "One or more torsion-tensioned chord faces were not solved"
        )
    elif not conditional:
        long_status = "NOT ASSESSED"
        fallback = required_chord_fallback(combined) or {}
        face = "negative" if fallback.get("tension_low", True) else "positive"
        long_note = (
            f"Required {fallback.get('axis', '?')}-axis {face} face uses "
            "a pure-axis substitute; no demand-versus-resistance verdict"
        )
    else:
        long_status = _util_summary_status(
            long_util,
            valid=long_valid,
        )
        face = "negative" if governing.get("tension_low", True) else "positive"
        long_note = f"Governing {governing.get('axis', '?')}-axis {face} face"
    longitudinal_component = {
        "key": "longitudinal",
        "label": "Longitudinal reinforcement",
        "status": long_status,
        "util": long_util,
        "valid": long_valid,
        "note": long_note,
        "governing": governing,
        "coverage": coverage,
    }
    return [concrete, stirrup, longitudinal_component]


def _registered_fatigue_basis_label(value):
    try:
        return get_design_basis(value).label
    except ValueError:
        return None


def fatigue_summary_rows(inp, results, *, stale=False):
    """Return one conservative aggregate row for an enabled fatigue analysis."""

    inp = inp or {}
    results = results or {}
    if not bool(inp.get("fatigue_on")):
        return []
    fatigue = results.get("fatigue")
    basis = inp.get("fatigue_basis") or {}
    edition = _registered_fatigue_basis_label(
        inp.get("fatigue_edition")
    ) or "-"
    case = "-"
    status = "NOT RUN"
    result_text = "-"
    util = None
    note = "Calculate to assess the grouped spectra"
    if fatigue is not None:
        # The result payload owns the basis that was actually calculated. This
        # remains true when the live inputs have since changed and the row is stale.
        basis = fatigue.get("basis") or basis
        edition = str(
            fatigue.get("basis_label")
            or fatigue.get("edition")
            or _registered_fatigue_basis_label(fatigue.get("basis_key"))
            or edition
        )
        case = str(fatigue.get("governing_spectrum") or "-")
        try:
            util = float(fatigue.get("utilisation"))
        except (TypeError, ValueError):
            util = None
        result_text = _percent(util)
        status = fatigue_presentation.overall_status(
            fatigue, stale=stale
        )
        note = fatigue_presentation.overall_note(fatigue, stale=stale)
    return [{
        "check": "Fatigue",
        "family": "fatigue",
        "case": case,
        "case_type": edition,
        "source": str(
            basis.get("spectrum_source") or basis.get("method") or "-"
        ),
        "status": status,
        "result": result_text,
        "criterion": "<= 100 %",
        "util": util,
        "view": "Fatigue Results",
        "note": note,
        "overview_key": "fatigue",
    }]


def non_governing_fatigue_spectrum_rows(inp, results, *, stale=False):
    """Return retained independently checked spectra outside the aggregate row."""

    inp = inp or {}
    results = results or {}
    if not bool(inp.get("fatigue_on")):
        return []
    fatigue = results.get("fatigue")
    if fatigue is None:
        return []
    basis = fatigue.get("basis") or inp.get("fatigue_basis") or {}
    edition = str(
        fatigue.get("basis_label")
        or fatigue.get("edition")
        or _registered_fatigue_basis_label(fatigue.get("basis_key"))
        or _registered_fatigue_basis_label(inp.get("fatigue_edition"))
        or "-"
    )
    governing_name = str(fatigue.get("governing_spectrum") or "")
    governing_skipped = False
    rows = []
    for spectrum in fatigue_presentation.spectrum_rows(fatigue):
        name = str(spectrum.get("spectrum") or "-")
        if not governing_skipped and name == governing_name:
            governing_skipped = True
            continue
        status = str(spectrum.get("status") or "INVALID")
        if stale:
            status = "STALE"
        util = spectrum.get("utilisation")
        rows.append({
            "check": "Fatigue",
            "family": "fatigue",
            "case": name,
            "case_type": edition,
            "source": str(
                basis.get("spectrum_source") or basis.get("method") or "-"
            ),
            "status": status,
            "result": _percent(util),
            "criterion": "<= 100 %",
            "util": util,
            "view": "Fatigue Results",
            "note": "Independently checked non-governing spectrum",
        })
    return rows


def result_summary_rows(inp, results, *, stale=False):
    """Build the shared UI/PDF overview without rerunning any solver."""
    inp = inp or {}
    results = results or {}
    rows = []
    mode = str(inp.get("mode") or "")
    plastic_requested = mode in {"Plastic", "Both"}
    elastic_requested = mode in {"Elastic", "Both"}

    pl = results.get("plastic")
    if pl is not None and plastic_requested:
        assessment = plastic_action_assessment(pl)
        rows.append(_summary_row(
            "Plastic bending",
            "plastic",
            assessment["status"],
            _percent(assessment["util"]),
            "<= 100 %",
            assessment["util"],
            "Plastic Results",
            assessment["detail"],
            inp,
            overview_key="plastic_bending",
        ))
    elif plastic_requested:
        rows.append(_summary_row(
            "Plastic bending", "plastic", "NOT RUN",
            view="Plastic Results", note="Calculate required", inp=inp,
            overview_key="plastic_bending",
        ))

    elastic = results.get("elastic")
    if elastic is None and elastic_requested:
        rows.append(_summary_row(
            "Elastic stresses", "elastic", "NOT RUN",
            view="Elastic Results", note="Calculate required", inp=inp,
            overview_key="elastic_stresses:scope",
            overview_parent="elastic_stresses",
            overview_placeholder=True,
        ))
        if inp.get("sls_cw"):
            rows.append(_summary_row(
                "Crack width", "elastic", "NOT RUN",
                view="Elastic Results", note="Calculate required", inp=inp,
                overview_key="crack_width:scope",
                overview_parent="crack_width",
                overview_placeholder=True,
            ))
    elif elastic is not None and elastic_requested:
        converged = bool(elastic.get("converged", True))
        outputs = elastic.get("stress_outputs") or {}
        names = [
            ("Concrete stress", "concrete"),
            ("Reinforcement stress", "reinforcement"),
        ]
        if inp.get("tendons"):
            names.append(("Tendon stress", "prestress"))
        if not outputs:
            rows.append(_summary_row(
                "Elastic stresses",
                "elastic",
                "INVALID" if not converged else "NOT RUN",
                view="Elastic Results",
                note=("Elastic analysis did not converge" if not converged
                      else "No elastic stress result is available"),
                inp=inp,
                overview_key="elastic_stresses",
                overview_parent="elastic_stresses",
            ))
        else:
            for label, key in names:
                output = outputs.get(key) or {}
                status = (
                    "INVALID" if not converged
                    else str(
                        output.get("calculation_state") or "NOT CALCULATED"
                    )
                )
                value = output.get("value")
                result = "-" if value is None else f"{value:.3f} MPa"
                rows.append(_summary_row(
                    label, "elastic", status, result, "Output only",
                    None, "Elastic Results",
                    output.get("governing") or output.get("quantity") or "", inp,
                    overview_key=f"elastic_stress:{key}",
                    overview_parent="elastic_stresses",
                ))
        try:
            lambda_cr = float(elastic.get("lambda_cr"))
        except (TypeError, ValueError):
            lambda_cr = None
        if lambda_cr is not None and not math.isfinite(lambda_cr):
            lambda_cr = None
        if not converged:
            cracking_status = "INVALID"
            cracking_result = "-"
            cracking_note = "Elastic analysis did not converge"
        elif lambda_cr is None:
            cracking_status = "NOT CALCULATED"
            cracking_result = "-"
            cracking_note = "No cracking-threshold result returned"
        else:
            cracking_status = "CALCULATED"
            cracking_state = (
                "cracked" if elastic.get("cracked") else "uncracked"
            )
            cracking_result = f"lambda_cr {lambda_cr:.3f}; {cracking_state}"
            cracking_note = "Stage-I cracking threshold/state"
        rows.append(_summary_row(
            "Cracking threshold/state", "elastic", cracking_status,
            cracking_result, "Output only", None, "Elastic Results",
            cracking_note, inp,
            overview_key="cracking_threshold",
        ))
        output = elastic.get("crack_output")
        if isinstance(output, Mapping):
            for duration in ("long_term", "short_term"):
                duration_output = output.get(duration)
                if isinstance(duration_output, Mapping):
                    rows.append(
                        _ordinary_crack_summary_row(inp, duration_output)
                    )
        elif elastic.get("show_cw") or inp.get("sls_cw"):
            rows.append(_summary_row(
                "Crack width", "elastic", "NOT ASSESSED",
                view="Elastic Results",
                note="No calculated crack-width result is available",
                inp=inp,
                overview_key="crack_width",
                overview_parent="crack_width",
            ))

    minimum = results.get("minimum_reinforcement")
    minimum_direction = modelled_direction.resolved_label(
        minimum,
        cut_direction=inp.get("detailing_cut_direction"),
        alias=inp.get(modelled_direction.ALIAS_KEY),
    )
    minimum_label = f"{minimum_direction} minimum reinforcement"
    if minimum is None and inp.get("minimum_reinforcement_on"):
        rows.append(_summary_row(
            minimum_label, "plastic", "NOT RUN",
            view="Detailing", note="Calculate required", inp=inp,
            overview_key="minimum_reinforcement",
        ))
    elif minimum is not None and inp.get("minimum_reinforcement_on"):
        checks = minimum.get("checks") or []
        if not checks:
            minimum_note = (
                result_reason(
                    minimum.get("reason"),
                    "minimum_reinforcement",
                    context="minimum-reinforcement summary reason",
                )
                if minimum.get("reason")
                else str(minimum.get("clause") or "")
            )
            rows.append(_summary_row(
                minimum_label,
                "plastic",
                _map_assessment_status(minimum.get("status")),
                view="Detailing",
                note=minimum_note,
                inp=inp,
                overview_key="minimum_reinforcement",
            ))
        for check in checks:
            util = check.get("utilisation")
            face = check.get("face")
            axis = check.get("axis")
            suffix = (
                " Mx+My resultant"
                if axis == "xy"
                else f" M{axis} {face}" if axis and face else ""
            )
            if minimum_area_check(minimum, check):
                required = check.get("as_min_mm2")
                result_text = (
                    f"As,prov {check.get('as_provided_mm2', 0.0):.1f} mm2; "
                    "As,min "
                    + ("-" if required is None else f"{float(required):.1f} mm2")
                )
                criterion = "As,prov >= As,min"
            elif check.get("type") == "pure tension":
                resistance = check.get("resistance_kn")
                demand = check.get("demand_kn")
                result_text = (
                    "Rnom "
                    + ("-" if resistance is None else f"{float(resistance):.1f}")
                    + " kN; Rcr "
                    + ("-" if demand is None else f"{float(demand):.1f}")
                    + " kN"
                )
                criterion = "Rnom >= Rcr"
            else:
                resistance = check.get("mr_nom_knm")
                demand = check.get("m_cr_knm")
                result_text = (
                    "MR,nom "
                    + ("-" if resistance is None else f"{float(resistance):.1f}")
                    + " kNm; Mcr "
                    + ("-" if demand is None else f"{float(demand):.1f}")
                    + " kNm"
                )
                criterion = "MR,nom >= Mcr"
            note_parts = [str(minimum.get("clause") or "")]
            if check.get("axial_feasible") is not None:
                note_parts.append(
                    "nominal axial equilibrium verified"
                    if check.get("axial_feasible")
                    else "nominal axial equilibrium not available"
                )
            if check.get("reason"):
                note_parts.append(result_reason(
                    check["reason"],
                    "minimum_reinforcement",
                    context="minimum-reinforcement check reason",
                ))
            rows.append(_summary_row(
                f"{minimum_label}{suffix}",
                "plastic",
                _map_assessment_status(check.get("status")),
                result_text,
                criterion,
                util,
                "Detailing",
                "; ".join(part for part in note_parts if part),
                inp,
                overview_key="minimum_reinforcement",
            ))

    transverse = results.get("transverse_reinforcement")
    if transverse is None and inp.get("transverse_detailing_on"):
        rows.append(_summary_row(
            "Shear/torsion link detailing",
            "plastic",
            "NOT RUN",
            view="Detailing",
            note="Calculate required",
            inp=inp,
            overview_key="link_detailing:scope",
            overview_parent="link_detailing",
            overview_placeholder=True,
        ))
    elif transverse is not None and inp.get("transverse_detailing_on"):
        checks = transverse.get("checks") or []
        if not checks:
            transverse_note = (
                result_reason(
                    transverse.get("reason"),
                    "transverse_reinforcement",
                    context="transverse-reinforcement summary reason",
                )
                if transverse.get("reason")
                else str(transverse.get("edition") or "")
            )
            rows.append(_summary_row(
                "Shear/torsion link detailing",
                "plastic",
                _map_assessment_status(transverse.get("status")),
                view="Detailing",
                note=transverse_note,
                inp=inp,
                overview_key="link_detailing",
                overview_parent="link_detailing",
            ))
        labels = {
            "minimum_ratio": "minimum ratio",
            "longitudinal_spacing": "longitudinal spacing",
            "transverse_leg_spacing": "transverse leg spacing",
            "torsion_spacing": "closed-link spacing",
            "required_links": "required links",
            "minimum_link_applicability": "minimum-link applicability",
        }
        for check in checks:
            kind = str(check.get("kind") or "")
            check_label = labels.get(kind, kind)
            if kind == "transverse_leg_spacing" and check.get("measurement_axis"):
                check_label += f" along {check['measurement_axis']}"
            provided = check.get("provided")
            limit = check.get("limit")
            if kind == "required_links":
                result_text = "No links defined"
                criterion = "Links required"
            elif kind == "minimum_ratio":
                result_text = (
                    "-"
                    if provided is None
                    else f"{_RHO}w,prov = {float(provided):.5f}"
                )
                criterion = (
                    "-"
                    if limit is None
                    else f"{_RHO}w,prov >= {_RHO}w,min = {float(limit):.5f}"
                )
            else:
                result_text = (
                    "-"
                    if provided is None
                    else f"sprov = {float(provided):.1f} mm"
                )
                criterion = (
                    "-"
                    if limit is None
                    else f"sprov <= smax = {float(limit):.1f} mm"
                )
            note = "; ".join(
                part for part in (
                    str(check.get("clause") or ""),
                    (
                        result_reason(
                            check.get("reason"),
                            "transverse_reinforcement",
                            context="transverse-reinforcement check reason",
                        )
                        if check.get("reason")
                        else ""
                    ),
                    (
                        "spacing " + str(check.get("spacing_source"))
                        if check.get("spacing_source") else ""
                    ),
                )
                if part
            )
            rows.append(_summary_row(
                f"{check.get('scope', 'Shear/torsion links')} "
                f"{check_label}",
                "plastic",
                _map_assessment_status(check.get("status")),
                result_text,
                criterion,
                check.get("utilisation"),
                "Detailing",
                note,
                inp,
                overview_key=f"link_detailing:{kind or 'unspecified'}",
                overview_parent="link_detailing",
            ))

    spacing = results.get("clear_spacing")
    if spacing is None and inp.get("clear_spacing_on"):
        rows.append(_summary_row(
            "Reinforcement clear spacing", "section", "NOT RUN",
            view="Detailing", note="Calculate required", inp=inp,
            overview_key="clear_spacing",
        ))
    elif spacing is not None and inp.get("clear_spacing_on"):
        governing = spacing.get("governing") or {}
        clear = governing.get("clear_mm")
        required = governing.get("required_mm")
        util = (
            float(required) / float(clear)
            if required is not None and clear is not None and float(clear) > 0.0
            else math.inf if governing and required is not None else None
        )
        result_text = (
            f"{clear:.1f} mm ({governing.get('first_id', '?')}-"
            f"{governing.get('second_id', '?')})"
            if clear is not None else "-"
        )
        criterion = f">= {required:.1f} mm" if required is not None else "-"
        rows.append(_summary_row(
            "Reinforcement clear spacing",
            "section",
            _map_assessment_status(spacing.get("status")),
            result_text,
            criterion,
            util,
            "Detailing",
            str(spacing.get("clause") or ""),
            inp,
            overview_key="clear_spacing",
        ))

    shear = results.get("shear")
    if shear is None and inp.get("shear_on"):
        rows.append(_summary_row(
            "Shear", "plastic", "NOT RUN",
            view="Shear", note="Calculate required", inp=inp,
            overview_key="shear:scope",
            overview_parent="shear",
            overview_placeholder=True,
        ))
    elif shear is not None and inp.get("shear_on"):
        links_selected = inp.get("shear_links") is True

        def append_direction(component, direction):
            suffix = {"vx": " Vx", "vy": " Vy"}.get(component, "")
            action_label = {"vx": "Vx,Ed", "vy": "Vy,Ed"}.get(component, "VEd")
            resistance = (direction.get("res") or {}).get("vrd_c")
            result = (
                f"{_percent(direction.get('util'))} "
                f"({action_label} / VRd,c)"
                if resistance is not None else "-"
            )
            rows.append(_summary_row(
                f"Shear{suffix} without links",
                "plastic",
                (
                    "NOT APPLICABLE"
                    if links_selected
                    else _util_summary_status(
                        direction.get("util"),
                        valid=bool((direction.get("res") or {}).get("valid")),
                    )
                ),
                result,
                "<= 100 %",
                direction.get("util"),
                "Shear",
                (
                    "Links present; use the reinforced shear check"
                    if links_selected else str(direction.get("method") or "")
                ),
                inp,
                overview_key="shear:without_links",
                overview_parent="shear",
            ))
            if not links_selected:
                return
            links = direction.get("links")
            if links is None:
                rows.append(_summary_row(
                    f"Shear{suffix} with links", "plastic", "NOT ASSESSED",
                    view="Shear", note="Selected method does not evaluate links",
                    inp=inp,
                    overview_key="shear:with_links",
                    overview_parent="shear",
                ))
            else:
                link_result = links.get("res") or {}
                calculation_state = link_result.get("calculation_state")
                rows.append(_summary_row(
                    f"Shear{suffix} with links",
                    "plastic",
                    (
                        str(calculation_state)
                        if calculation_state
                        else _util_summary_status(
                            links.get("util"),
                            valid=bool(link_result.get("valid")),
                        )
                    ),
                    _percent(links.get("util")),
                    "<= 100 %",
                    links.get("util"),
                    "Shear",
                    result_reason(
                        links.get("assessment_reason")
                        or link_result.get("reason")
                        or link_result.get("governs")
                        or "the calculated face-aligned arm is unavailable",
                        "shear",
                        context="shear summary link reason",
                    ),
                    inp,
                    overview_key="shear:with_links",
                    overview_parent="shear",
                ))

        directions = shear.get("directions") or {}
        if directions:
            for component in ("vx", "vy"):
                if component in directions:
                    append_direction(component, directions[component])
            if shear.get("biaxial"):
                rows.append(_summary_row(
                    "Generic cross-direction shear interaction",
                    "plastic",
                    "NOT CALCULATED",
                    result="Independent Vx and Vy calculations",
                    criterion="Not calculated",
                    view="Shear",
                    note="No aggregate cross-direction verdict",
                    inp=inp,
                    overview_key="shear:cross_direction",
                ))
        else:
            append_direction("", shear)

    torsion = results.get("torsion")
    torsion_tube_valid = False
    torsion_full_resistance_assessed = False
    if torsion is None and inp.get("torsion_on"):
        rows.append(_summary_row(
            "Torsion", "plastic", "NOT RUN",
            view="Torsion", note="Calculate required", inp=inp,
            overview_key="torsion",
        ))
    elif torsion is not None and inp.get("torsion_on"):
        torsion_tube_valid = (
            torsion.get("tube_valid") is True
            if "tube_valid" in torsion
            else torsion.get("valid") is True
        )
        torsion_full_resistance_assessed = (
            torsion.get("full_resistance_assessed") is True
            if "full_resistance_assessed" in torsion
            else torsion.get("valid") is True
        )
        if (
            "closed_links_present" in torsion
            and torsion.get("closed_links_present") is not True
        ):
            torsion_full_resistance_assessed = False
        if (
            torsion_tube_valid
            and not torsion_full_resistance_assessed
        ):
            rows.append(_summary_row(
                "Torsion",
                "plastic",
                "NOT ASSESSED",
                "-",
                "-",
                None,
                "Torsion",
                result_reason(
                    torsion.get("assessment_reason")
                    or torsion.get("reason")
                    or "full torsion resistance not assessed",
                    "torsion",
                    context="torsion summary assessment reason",
                ),
                inp,
                overview_key="torsion",
            ))
        else:
            rows.append(_summary_row(
                "Torsion",
                "plastic",
                _util_summary_status(
                    torsion.get("util"),
                    valid=torsion.get("valid") is True,
                ),
                _percent(torsion.get("util")),
                "<= 100 %",
                torsion.get("util"),
                "Torsion",
                result_reason(
                    torsion.get("governs")
                    or torsion.get("reason")
                    or "torsion result is invalid",
                    "torsion",
                    context="torsion summary result reason",
                ),
                inp,
                overview_key="torsion",
            ))

    combined = results.get("combined")
    if combined is None and inp.get("combined_on"):
        torsion_not_assessed = (
            torsion is not None
            and torsion_tube_valid
            and not torsion_full_resistance_assessed
        )
        rows.append(_summary_row(
            "Combined M-V-T",
            "plastic",
            "NOT ASSESSED" if torsion_not_assessed else "NOT RUN",
            view="M-V-T Combined",
            note=(
                result_reason(
                    torsion.get("assessment_reason")
                    or torsion.get("reason")
                    or "full torsion resistance not assessed",
                    "torsion",
                    context="combined summary torsion reason",
                )
                if torsion_not_assessed
                else "Calculate required"
            ),
            inp=inp,
            overview_key="combined:dkna_sum",
        ))
    elif (
        inp.get("combined_on")
        and (combined_blocker := combined_bending_assessment_blocker(results))
        is not None
    ):
        rows.append(_summary_row(
            "Combined M-V-T - DK NA sum",
            "plastic",
            "NOT ASSESSED",
            result="-",
            criterion="<= 100 %",
            util=None,
            view="M-V-T Combined",
            note=combined_blocker,
            inp=inp,
            overview_key="combined:dkna_sum",
        ))
    elif combined is not None and inp.get("combined_on"):
        directions = combined.get("directions") or {}
        if combined.get("biaxial") and directions:
            for component in ("vx", "vy"):
                direction = directions.get(component)
                if not direction:
                    continue
                label = "Vx+T" if component == "vx" else "Vy+T"
                util = direction.get("dkna_sum")
                status = (
                    "NOT ASSESSED"
                    if not direction.get("valid")
                    else "PASS" if direction.get("dkna_ok") else "FAIL"
                )
                rows.append(_summary_row(
                    f"Combined {label} - DK NA sum",
                    "plastic",
                    status,
                    _percent(util),
                    "<= 100 %",
                    util,
                    "M-V-T Combined",
                    str(direction.get("method") or ""),
                    inp,
                    overview_key="combined:dkna_sum",
                ))
                if direction.get("valid"):
                    for physical in combined_physical_components(direction):
                        rows.append(_summary_row(
                            f"Combined {label} {physical['label'].lower()}",
                            "plastic",
                            physical["status"],
                            _percent(physical["util"]),
                            "<= 100 %",
                            physical["util"],
                            "M-V-T Combined",
                            physical["note"],
                            inp,
                            overview_key=f"combined:{physical['key']}",
                        ))
            rows.append(_summary_row(
                "Generic Vx-Vy-T interaction",
                "plastic",
                "NOT CALCULATED",
                result="Independent Vx+T and Vy+T calculations",
                criterion="Not calculated",
                view="M-V-T Combined",
                note="No aggregate cross-direction verdict",
                inp=inp,
                overview_key="combined:cross_direction",
            ))
            if stale and results:
                for row in rows:
                    if row["status"] not in {"NOT RUN", "NOT APPLICABLE"}:
                        previous = row["status"]
                        row["status"] = "STALE"
                        row["note"] = f"Last status: {previous}; inputs changed"
            return rows
        valid = bool(combined.get("valid"))
        util = combined.get("dkna_sum")
        missing = [
            label
            for key, label in (
                ("have_m", "M"),
                ("have_v", "V"),
                ("have_t", "T"),
            )
            if key in combined and not combined.get(key)
        ]
        if valid:
            combined_note = str(combined.get("method") or "")
        elif missing:
            combined_note = "Missing prerequisite: " + ", ".join(missing)
            if combined.get("reason"):
                combined_note += "; " + result_reason(
                    combined["reason"],
                    "combined",
                    context="combined summary missing-prerequisite reason",
                )
        else:
            combined_note = result_reason(
                combined.get("reason") or "Combined calculation is invalid",
                "combined",
                context="combined summary result reason",
            )
        combined_status = (
            "NOT ASSESSED"
            if not valid and missing
            else _util_summary_status(
                util,
                valid=valid,
            )
        )
        rows.append(_summary_row(
            "Combined M-V-T - DK NA sum",
            "plastic",
            combined_status,
            _percent(util),
            "<= 100 %",
            util,
            "M-V-T Combined",
            combined_note,
            inp,
            overview_key="combined:dkna_sum",
        ))
        if valid:
            for component in combined_physical_components(combined):
                rows.append(_summary_row(
                    f"Combined {component['label'].lower()}",
                    "plastic",
                    component["status"],
                    _percent(component["util"]),
                    "<= 100 %",
                    component["util"],
                    "M-V-T Combined",
                    component["note"],
                    inp,
                    overview_key=f"combined:{component['key']}",
                ))

    heightened = results.get("heightened_crack_control")
    if isinstance(heightened, Mapping):
        rows.append(_heightened_crack_summary_row(heightened))

    if stale and results:
        for row in rows:
            if row["status"] not in {"NOT RUN", "NOT APPLICABLE"}:
                previous = row["status"]
                row["status"] = "STALE"
                row["note"] = f"Last status: {previous}; inputs changed"
    return rows


def multi_case_summary_rows(inp, results, *, stale=False):
    """Build one ordered result register across every canonical case row."""
    inp = inp or {}
    results = results or {}
    if "plastic_cases" not in inp and "elastic_cases" not in inp:
        return (
            result_summary_rows(inp, results, stale=stale)
            + fatigue_summary_rows(inp, results, stale=stale)
        )

    mode = str(inp.get("mode") or "")
    requested = {
        "plastic": (
            mode in {"Plastic", "Both"}
            or bool(inp.get("shear_on"))
            or bool(inp.get("torsion_on"))
            or bool(inp.get("combined_on"))
            or bool(inp.get("minimum_reinforcement_on"))
            or bool(inp.get("transverse_detailing_on"))
        ),
        "elastic": mode in {"Elastic", "Both"},
    }
    rows = []
    for family in ("plastic", "elastic"):
        if not requested[family]:
            continue
        result_key = f"{family}_cases"
        entries = results.get(result_key)
        if entries is None:
            entries = [
                {
                    "actions": record,
                    "results": {},
                    "evaluated": False,
                }
                for record in case_analysis.case_records(inp, family)
            ]
        for entry in entries:
            actions = entry.get("actions") or {}
            if family == "plastic":
                case_inp = case_analysis.plastic_case_input(inp, actions)
                # Clear spacing is section-wide and is appended once below.
                case_inp["clear_spacing_on"] = False
            else:
                case_inp = case_analysis.elastic_case_input(inp, actions)
            case_results = entry.get("results") or {}
            rows.extend(
                result_summary_rows(case_inp, case_results, stale=stale)
            )
            if family != "plastic":
                continue

            vx_zero = abs(float(actions.get("vx_ed_kn", 0.0))) <= 0.0
            vy_zero = abs(float(actions.get("vy_ed_kn", 0.0))) <= 0.0
            v_zero = vx_zero and vy_zero
            t_zero = abs(float(actions.get("t_ed_knm", 0.0))) <= 0.0
            if inp.get("shear_on"):
                for component, is_zero in (("Vx", vx_zero), ("Vy", vy_zero)):
                    if is_zero:
                        rows.append(_summary_row(
                            f"Shear {component}", "plastic", "NOT APPLICABLE",
                            result=f"{component},Ed = 0", view="Shear",
                            note="Zero component; not evaluated", inp=case_inp,
                            overview_key="shear:scope",
                            overview_parent="shear",
                            overview_placeholder=True,
                        ))
            if inp.get("torsion_on") and t_zero:
                rows.append(_summary_row(
                    "Torsion", "plastic", "NOT APPLICABLE",
                    result="TEd = 0", view="Torsion",
                    note="Zero action; not evaluated", inp=case_inp,
                    overview_key="torsion",
                ))
            if inp.get("combined_on") and (v_zero or t_zero):
                zero = (
                    "Vx,Ed = Vy,Ed = TEd = 0"
                    if v_zero and t_zero
                    else "Vx,Ed = Vy,Ed = 0" if v_zero else "TEd = 0"
                )
                rows.append(_summary_row(
                    "Combined M-V-T", "plastic", "NOT APPLICABLE",
                    result=zero, view="M-V-T Combined",
                    note="Zero action; not evaluated", inp=case_inp,
                    overview_key="combined:dkna_sum",
                ))
            shear_action_live = not v_zero and bool(inp.get("shear_on"))
            torsion_action_live = not t_zero and bool(inp.get("torsion_on"))
            transverse_live = shear_action_live or torsion_action_live
            if inp.get("transverse_detailing_on") and not transverse_live:
                rows.append(_summary_row(
                    "Shear/torsion link detailing",
                    "plastic",
                    "NOT APPLICABLE",
                    result="No active non-zero VEd or TEd",
                    view="Detailing",
                    note="Zero relevant action; not evaluated",
                    inp=case_inp,
                    overview_key="link_detailing:scope",
                    overview_parent="link_detailing",
                    overview_placeholder=True,
                ))
    # Clear spacing is a section-wide result, not a load-case result. Add it once
    # after the case loops rather than repeating it for every Plastic row.
    if inp.get("clear_spacing_on"):
        spacing_only_inp = dict(
            inp,
            mode="",
            plastic_case={},
            elastic_case={},
            minimum_reinforcement_on=False,
            transverse_detailing_on=False,
            shear_on=False,
            torsion_on=False,
            combined_on=False,
        )
        rows.extend(result_summary_rows(
            spacing_only_inp,
            {"clear_spacing": results.get("clear_spacing")}
            if results.get("clear_spacing") is not None else {},
            stale=stale,
        ))
    heightened = results.get("heightened_crack_control")
    if isinstance(heightened, Mapping):
        row = _heightened_crack_summary_row(heightened)
        if stale:
            previous = row["status"]
            row["status"] = "STALE"
            row["note"] = f"Last status: {previous}; inputs changed"
        rows.append(row)
    rows.extend(fatigue_summary_rows(inp, results, stale=stale))
    return rows


def overall_summary_status(rows):
    """Return the most conservative state represented in a summary table."""
    states = {row.get("status") for row in rows}
    for status in (
        "INVALID", "FAIL", "STALE", "REVIEW", "NOT ASSESSED", "NOT RUN",
        "PASS", "CALCULATED", "NOT CALCULATED", "NOT APPLICABLE",
    ):
        if status in states:
            return status
    return "NOT RUN"


def _governing_overview_utilisation(row):
    value = row.get("util")
    if (
        isinstance(value, bool)
        or type(value).__name__ == "bool_"
        or not isinstance(value, Real)
    ):
        return None
    metric = float(value)
    if metric < 0.0 or metric == -math.inf or math.isnan(metric):
        return None
    return metric


def _governing_summary_selection(rows):
    """Return retained rows and the selected source index for each check type."""

    retained = []
    selected = {}
    order = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError("result overview rows must be objects")
        retained.append(row)
    parents_with_children = {
        str(row.get("overview_parent"))
        for row in retained
        if row.get("overview_parent")
        and not bool(row.get("overview_placeholder"))
    }
    for index, row in enumerate(retained):
        parent = str(row.get("overview_parent") or "")
        if row.get("overview_placeholder") and parent in parents_with_children:
            continue
        semantic_key = str(row.get("overview_key") or row.get("check") or "")
        key = (str(row.get("family") or ""), semantic_key)
        status = str(row.get("status") or "")
        rank = _GOVERNING_OVERVIEW_STATUS_RANK.get(status, -1)
        utilisation = _governing_overview_utilisation(row)
        if key not in selected:
            order.append(key)
            selected[key] = (index, row, rank, utilisation)
            continue
        _current_index, _current, current_rank, current_utilisation = selected[key]
        replace_current = rank < current_rank
        if rank == current_rank:
            replace_current = bool(
                utilisation is not None
                and (
                    current_utilisation is None
                    or utilisation > current_utilisation
                )
            )
        if replace_current:
            selected[key] = (index, row, rank, utilisation)
    return retained, order, selected


def governing_summary_rows(rows):
    """Select one conservative retained row per semantic check type."""

    _retained, order, selected = _governing_summary_selection(rows)
    return [dict(selected[key][1]) for key in order]


def governing_result_rows(rows):
    """Return selected rows that carry an applicable retained result."""

    return [
        dict(row)
        for row in rows
        if str(row.get("status") or "").upper()
        not in GOVERNING_OVERVIEW_INFORMATION_STATUSES
    ]


def governing_information_rows(rows):
    """Return selected scope and calculation-state rows outside conclusions."""

    return [
        dict(row)
        for row in rows
        if str(row.get("status") or "").upper()
        in GOVERNING_OVERVIEW_INFORMATION_STATUSES
    ]


def non_governing_summary_rows(rows):
    """Return every retained row not selected for the governing overview."""

    retained, _order, selected = _governing_summary_selection(rows)
    selected_indices = {item[0] for item in selected.values()}
    return [
        dict(row)
        for index, row in enumerate(retained)
        if index not in selected_indices
    ]


def summary_governing_flags(rows):
    """Mark the largest utilisation among rows that carry acceptance verdicts."""
    def eligible(row):
        util = row.get("util")
        return bool(
            row.get("status") in {"PASS", "FAIL"}
            and util is not None
            and (math.isfinite(util) or util == math.inf)
        )

    candidates = [row["util"] for row in rows if eligible(row)]
    governing = max(candidates) if candidates else None
    return [
        bool(
            governing is not None
            and eligible(row)
            and (
                row["util"] == governing
                if governing == math.inf
                else math.isclose(
                    row["util"], governing, rel_tol=1e-12, abs_tol=1e-12
                )
            )
        )
        for row in rows
    ]


def summary_governing_case_flags(rows):
    """Mark the highest accepted utilisation for each check across cases."""
    eligible = {}
    for row in rows:
        util = row.get("util")
        if (
            row.get("status") in {"PASS", "FAIL"}
            and util is not None
            and (math.isfinite(util) or util == math.inf)
        ):
            eligible.setdefault(row.get("check"), []).append(util)
    governing = {
        check: max(values) for check, values in eligible.items() if values
    }
    flags = []
    for row in rows:
        value = governing.get(row.get("check"))
        util = row.get("util")
        flags.append(bool(
            value is not None
            and row.get("status") in {"PASS", "FAIL"}
            and util is not None
            and (
                util == value
                if value == math.inf
                else math.isclose(util, value, rel_tol=1e-12, abs_tol=1e-12)
            )
        ))
    return flags
