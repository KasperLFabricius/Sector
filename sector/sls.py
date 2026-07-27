"""Headless serviceability assessment and result-evidence helpers.

The elastic solver returns numerical section states.  This module turns those
states into explicit, auditable acceptance checks and element/corner tables
without depending on Streamlit or the PDF renderer.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Iterable as IterableCollection
from typing import Iterable, Mapping, Sequence


COMBINATION_UNSPECIFIED = "Not designated"
COMBINATION_CHARACTERISTIC = "Characteristic"
COMBINATION_FREQUENT = "Frequent"
COMBINATION_QUASI_PERMANENT = "Quasi-permanent"
SLS_COMBINATIONS = (
    COMBINATION_UNSPECIFIED,
    COMBINATION_CHARACTERISTIC,
    COMBINATION_FREQUENT,
    COMBINATION_QUASI_PERMANENT,
)

CRITERION_MODE_STANDARD = "Standard-derived"
CRITERION_MODE_PROJECT = "Project-defined"
CRITERION_MODE_LEGACY = "Legacy ambiguity - review required"
CRITERION_MODES = (
    CRITERION_MODE_STANDARD,
    CRITERION_MODE_PROJECT,
    CRITERION_MODE_LEGACY,
)

PRESTRESS_REINFORCED_UNBONDED = "Reinforced / unbonded prestress"
PRESTRESS_BONDED = "Bonded prestress"
PRESTRESS_CLASSES = (
    PRESTRESS_REINFORCED_UNBONDED,
    PRESTRESS_BONDED,
)

PROTECTION_NOT_ESTABLISHED = "Not established"
PROTECTION_LEVEL_1_OR_PRETENSIONED = (
    "Protection Level 1 / pretensioned member"
)
PROTECTION_LEVEL_2_OR_3 = "Protection Level 2 or 3"
PROTECTION_CLASSES = (
    PROTECTION_NOT_ESTABLISHED,
    PROTECTION_LEVEL_1_OR_PRETENSIONED,
    PROTECTION_LEVEL_2_OR_3,
)

EXPOSURE_NOT_ESTABLISHED = "Not established"
EXPOSURE_X0_XC1 = "X0 / XC1"
EXPOSURE_XC2_XC4 = "XC2 / XC3 / XC4"
EXPOSURE_XD_XS = "XD1-3 / XS1-3"
EXPOSURE_XF = "XF1-4"
EXPOSURE_CLASSES_2023 = (
    EXPOSURE_NOT_ESTABLISHED,
    EXPOSURE_X0_XC1,
    EXPOSURE_XC2_XC4,
    EXPOSURE_XD_XS,
    EXPOSURE_XF,
)

DECOMPRESSION_NOT_ESTABLISHED = "Not established"
DECOMPRESSION_REQUIRED = "Required"
DECOMPRESSION_NOT_REQUIRED = "Not required"
DECOMPRESSION_OPTIONS = (
    DECOMPRESSION_NOT_ESTABLISHED,
    DECOMPRESSION_REQUIRED,
    DECOMPRESSION_NOT_REQUIRED,
)

CRITERION_APPEARANCE = "Appearance crack width"
CRITERION_DURABILITY = "Durability crack width"
CRITERION_DECOMPRESSION = "Decompression"

CRACK_NUMERIC_INPUT_KEYS = (
    "sls_fctm",
    "sls_phi",
    "sls_tendon_xi",
    "sls_appearance_limit",
    "sls_project_characteristic_limit",
    "sls_project_frequent_limit",
    "sls_project_quasi_permanent_limit",
    "sls_wk_limit",
    "sls_conc_limit_pct",
    "sls_steel_limit_pct",
    "sls_pre_limit_pct",
)


def canonical_combination(value) -> str:
    """Return a stable SLS-combination token without inferring from duration."""
    text = str(value or "").strip()
    aliases = {
        "": COMBINATION_UNSPECIFIED,
        "none": COMBINATION_UNSPECIFIED,
        "unspecified": COMBINATION_UNSPECIFIED,
        "not designated": COMBINATION_UNSPECIFIED,
        "characteristic": COMBINATION_CHARACTERISTIC,
        "rare": COMBINATION_CHARACTERISTIC,
        "frequent": COMBINATION_FREQUENT,
        "quasi-permanent": COMBINATION_QUASI_PERMANENT,
        "quasi permanent": COMBINATION_QUASI_PERMANENT,
        "qp": COMBINATION_QUASI_PERMANENT,
    }
    return aliases.get(text.casefold(), text)


def is_boolean_value(value) -> bool:
    """Return whether ``value`` is a Python/NumPy Boolean scalar or array."""
    value_type = type(value)
    numpy_value = value_type.__module__.split(".", 1)[0] == "numpy"
    return (
        isinstance(value, bool)
        or (
            value_type.__name__ in {"bool", "bool_"}
            and numpy_value
        )
        or (
            numpy_value
            and getattr(getattr(value, "dtype", None), "kind", None) == "b"
        )
    )


def contains_boolean_value(value) -> bool:
    """Return whether a scalar or finite input container contains a Boolean."""
    if is_boolean_value(value):
        return True
    if isinstance(value, (str, bytes, bytearray)):
        return False

    value_type = type(value)
    module_root = value_type.__module__.split(".", 1)[0]
    if module_root == "pandas":
        to_numpy = getattr(value, "to_numpy", None)
        if callable(to_numpy):
            return contains_boolean_value(to_numpy())

    if isinstance(value, Mapping):
        return (
            any(contains_boolean_value(item) for item in value.keys())
            or any(contains_boolean_value(item) for item in value.values())
        )

    if isinstance(value, IterableCollection):
        try:
            iterator = iter(value)
        except TypeError:
            item = getattr(value, "item", None)
            if module_root == "numpy" and callable(item):
                return contains_boolean_value(item())
            return False
        return any(contains_boolean_value(item) for item in iterator)
    return False


def crack_width_numeric_value(value) -> float | None:
    """Return a finite non-negative crack width without Boolean coercion."""
    if contains_boolean_value(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0.0:
        return None
    return number


def publication_safe_crack_assessment(
    assessment: Mapping | None,
    rejected_responses: Sequence[Mapping] = (),
) -> dict:
    """Downgrade an assessment that conflicts with current response evidence."""
    safe = (
        copy.deepcopy(dict(assessment))
        if isinstance(assessment, Mapping)
        else {}
    )
    rejected = []
    for index, raw in enumerate(rejected_responses):
        item = dict(raw) if isinstance(raw, Mapping) else {}
        rejected.append({
            "response": str(
                item.get("response") or f"response {index + 1}"
            ),
            "reason": str(
                item.get("reason")
                or item.get("result_validation")
                or "Calculated crack response was rejected."
            ),
            "solver_provenance": item.get("solver_provenance"),
        })
    if not rejected:
        return safe

    names = [item["response"] for item in rejected]
    details = " ".join(dict.fromkeys(
        item["reason"] for item in rejected
    ))
    reason = (
        "Publication rejected current crack-response evidence for "
        f"{', '.join(names)}. Any prior acceptance assessment was invalidated; "
        "repair or recalculate the rejected response before issuing a verdict. "
        f"Details: {details}"
    )
    safe.update(
        status="NOT ASSESSED",
        verdict="REVIEW",
        value=None,
        util=None,
        margin=None,
        case=", ".join(names),
        governing=None,
        response_duration=None,
        reason=reason,
        solver_provenance=[
            {
                "response": item["response"],
                "solver": item["solver_provenance"],
            }
            for item in rejected
        ],
        publication_validation={
            "status": "REJECTED",
            "reason": reason,
            "rejected_responses": rejected,
        },
    )
    criteria = []
    for raw in safe.get("criteria") or []:
        if not isinstance(raw, Mapping):
            continue
        item = copy.deepcopy(dict(raw))
        if str(item.get("status") or "").upper() != "NOT APPLICABLE":
            item.update(
                status="NOT ASSESSED",
                value=None,
                util=None,
                margin=None,
                case=None,
                governing=None,
                response_duration=None,
                reason=reason,
            )
        criteria.append(item)
    safe["criteria"] = criteria
    return safe


def publication_safe_crack_control_record(record: Mapping | None) -> dict | None:
    """Cross-check a stored crack snapshot before save, load or display."""
    if record is None:
        return None
    if not isinstance(record, Mapping):
        return None
    safe = copy.deepcopy(dict(record))
    raw_cases = safe.get("cases")
    if not isinstance(raw_cases, list):
        safe["cases"] = []
        return safe

    cases = []
    for case_index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, Mapping):
            cases.append({
                "case": f"Elastic {case_index + 1}",
                "assessment": publication_safe_crack_assessment(
                    None,
                    [{
                        "response": f"case {case_index + 1}",
                        "reason": "Stored crack-control case is not a mapping.",
                    }],
                ),
                "responses": [],
            })
            continue

        case = copy.deepcopy(dict(raw_case))
        raw_responses = case.get("responses")
        if not isinstance(raw_responses, list):
            raw_responses = []
        responses = []
        rejected = []
        criterion_responses = {}
        for response_index, raw_response in enumerate(raw_responses):
            if not isinstance(raw_response, Mapping):
                name = f"response {response_index + 1}"
                response = {
                    "name": name,
                    "wk_mm": None,
                    "acceptance_role": "criterion input",
                    "result_validation": (
                        "Stored crack-response record rejected: response is "
                        "not a mapping."
                    ),
                }
            else:
                response = copy.deepcopy(dict(raw_response))
                name = str(
                    response.get("name") or f"response {response_index + 1}"
                )
                width = response.get("wk_mm")
                if (
                    width is not None
                    and crack_width_numeric_value(width) is None
                ):
                    response["wk_mm"] = None
                    response["result_validation"] = (
                        "Stored crack-width value rejected; no numeric "
                        "acceptance evidence retained."
                    )
                elif (
                    width is None
                    and str(response.get("solver_status") or "").upper()
                    != "NOT APPLICABLE"
                    and not str(
                        response.get("result_validation") or ""
                    ).strip()
                ):
                    response["result_validation"] = (
                        "Stored crack response has no validated numeric width."
                    )

            validation = str(
                response.get("result_validation") or ""
            ).strip()
            width = crack_width_numeric_value(response.get("wk_mm"))
            context = response.get("context")
            solver = (
                context.get("solver_provenance")
                if isinstance(context, Mapping)
                else None
            )
            if validation:
                rejected.append({
                    "response": name,
                    "reason": validation,
                    "solver_provenance": solver,
                })
            elif (
                str(response.get("acceptance_role") or "").lower()
                != "informational"
            ):
                criterion_responses[name] = response
            responses.append(response)

        assessment = (
            dict(case.get("assessment"))
            if isinstance(case.get("assessment"), Mapping)
            else {}
        )
        acceptance_items = []
        if (
            str(assessment.get("verdict") or "").upper()
            in {"PASS", "FAIL"}
            or str(assessment.get("status") or "").upper()
            in {"OK", "EXCEEDED"}
        ):
            acceptance_items.append(("assessment", assessment))
        for criterion_index, raw_criterion in enumerate(
            assessment.get("criteria") or []
        ):
            if not isinstance(raw_criterion, Mapping):
                continue
            criterion = dict(raw_criterion)
            if str(criterion.get("status") or "").upper() in {
                "OK",
                "EXCEEDED",
            }:
                acceptance_items.append(
                    (f"criterion {criterion_index + 1}", criterion)
                )

        def item_response_names(item):
            case_name = str(item.get("case") or "").strip()
            if case_name:
                return [case_name]
            matched = item.get("matched_responses")
            if not isinstance(matched, (list, tuple)):
                return []
            return [
                str(name).strip()
                for name in matched
                if str(name).strip()
            ]

        def response_solver_provenance(names):
            for name in names:
                response = criterion_responses.get(name)
                if not isinstance(response, Mapping):
                    continue
                context = response.get("context")
                if isinstance(context, Mapping):
                    return context.get("solver_provenance")
            return assessment.get("solver_provenance")

        def acceptance_evidence_issue(label, item):
            names = item_response_names(item)
            if not names:
                return (
                    f"Stored {label} has no governing response identity.",
                    names,
                )
            missing = [
                name for name in names
                if name not in criterion_responses
            ]
            if missing:
                return (
                    f"Stored {label} is governed by "
                    f"{', '.join(missing)}, but no current criterion-input "
                    "response with that identity is available.",
                    names,
                )

            kind = str(
                item.get("kind") or item.get("criterion") or ""
            )
            expected_status = str(item.get("status") or "").upper()
            if kind == CRITERION_DECOMPRESSION:
                for name in names:
                    evidence = criterion_responses[name].get(
                        "decompression"
                    )
                    if not isinstance(evidence, Mapping):
                        return (
                            f"Stored {label} is governed by {name}, but its "
                            "current decompression evidence is absent.",
                            names,
                        )
                    evidence_status = str(
                        evidence.get("status") or ""
                    ).upper()
                    if evidence_status != expected_status:
                        return (
                            f"Stored {label} status {expected_status or '-'} "
                            f"does not match current {name} decompression "
                            f"status {evidence_status or '-'}.",
                            names,
                        )
                return None

            expected_value = crack_width_numeric_value(item.get("value"))
            widths = [
                crack_width_numeric_value(
                    criterion_responses[name].get("wk_mm")
                )
                for name in names
            ]
            if expected_value is None or any(
                width is None for width in widths
            ):
                return (
                    f"Stored {label} has no validated crack-width value "
                    "matching its current governing response.",
                    names,
                )
            current_value = max(widths)
            if not math.isclose(
                expected_value,
                current_value,
                rel_tol=1e-9,
                abs_tol=1e-12,
            ):
                return (
                    f"Stored {label} crack width {expected_value:.12g} mm "
                    f"does not match current governing response "
                    f"{current_value:.12g} mm.",
                    names,
                )
            return None

        if not rejected:
            for label, item in acceptance_items:
                issue = acceptance_evidence_issue(label, item)
                if issue is None:
                    continue
                reason, names = issue
                rejected.append({
                    "response": (
                        ", ".join(names)
                        or str(item.get("case") or label)
                    ),
                    "reason": reason,
                    "solver_provenance": response_solver_provenance(names),
                })
                break
        case["assessment"] = publication_safe_crack_assessment(
            assessment,
            rejected,
        )
        case["responses"] = responses
        cases.append(case)
    safe["cases"] = cases
    return safe


def crack_numeric_input_issues(inp: Mapping) -> tuple[str, ...]:
    """Identify Boolean crack/SLS numerics before any numeric coercion."""
    return tuple(
        key
        for key in CRACK_NUMERIC_INPUT_KEYS
        if key in inp and contains_boolean_value(inp.get(key))
    )


def require_non_boolean_crack_numeric_inputs(inp: Mapping) -> None:
    """Reject Boolean SLS numerics before a solver/result boundary."""
    issues = crack_numeric_input_issues(inp)
    if issues:
        raise ValueError(
            "Boolean values are not accepted for SLS numeric inputs: "
            + ", ".join(issues)
        )


def _finite_positive(value) -> float | None:
    if contains_boolean_value(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0.0 else None


def _standard_reference(edition: str, kind: str, dk_na: bool) -> str:
    if edition == "2023":
        table = "Table 9.1" if kind == CRITERION_APPEARANCE else "Table 9.2"
        return f"DS/EN 1992-1-1:2023 section 9.2.1(6), {table}"
    base = "DS/EN 1992-1-1:2004 section 7.3.1(5), Table 7.1N"
    if dk_na:
        return (
            base
            + "; DS/EN 1992-1-1 DK NA:2024 section 7.3.1(5), Table 7.1 NA"
        )
    return base


def _criterion_source(reference: str, project_source: str) -> str:
    project_source = str(project_source or "").strip()
    return (
        f"{reference}; project applicability source: {project_source}"
        if project_source
        else reference
    )


def _criterion_record(
    criterion_id: str,
    kind: str,
    *,
    source_type: str,
    source: str,
    required_combination: str | None,
    limit_mm: float | None,
    applicability: Mapping,
    configuration_reason: str | None = None,
    configuration_status: str | None = None,
) -> dict:
    status = str(configuration_status or "").strip().upper()
    if not status:
        status = "NOT ASSESSED" if configuration_reason else "READY"
    return {
        "id": criterion_id,
        "kind": kind,
        "source_type": source_type,
        "source": str(source or "").strip(),
        "required_combination": (
            canonical_combination(required_combination)
            if required_combination is not None
            else None
        ),
        "limit_mm": limit_mm,
        "applicability": dict(applicability),
        "configuration_status": status,
        "configuration_reason": configuration_reason,
    }


def crack_criteria_from_inputs(inp: Mapping) -> list[dict]:
    """Build explicit crack-control criteria from auditable user inputs.

    Duration is intentionally absent from this function. Standard criteria route
    to an SLS combination from edition and prestress class; project criteria are
    created only for combinations carrying their own positive limit. Legacy
    projects never inherit the former one-limit-for-all-responses behaviour.
    """
    mode = str(
        inp.get("sls_criterion_mode") or CRITERION_MODE_LEGACY
    ).strip()
    source = str(inp.get("sls_limit_source") or "").strip()
    edition = str(inp.get("sls_edition") or "").strip()
    code = str(inp.get("sls_code") or "").strip()
    member = str(inp.get("sls_member") or "").strip()
    exposure = str(inp.get("sls_exposure_context") or "").strip()
    exposure_class = str(
        inp.get("sls_exposure_class") or EXPOSURE_NOT_ESTABLISHED
    ).strip()
    prestress_class = str(inp.get("sls_prestress_class") or "").strip()
    protection_class = str(
        inp.get("sls_protection_class") or PROTECTION_NOT_ESTABLISHED
    ).strip()
    dk_na = bool(inp.get("sls_dk_na"))
    applicability = {
        "edition": edition or None,
        "code": code or None,
        "member": member or None,
        "prestress_class": prestress_class or None,
        "exposure": exposure or None,
        "exposure_class": exposure_class,
        "protection_class": protection_class,
        "method": code or None,
    }

    invalid_numeric_keys = crack_numeric_input_issues(inp)
    if invalid_numeric_keys:
        return [_criterion_record(
            "invalid-crack-numerics",
            CRITERION_DURABILITY,
            source_type=mode or "Unknown",
            source=source,
            required_combination=None,
            limit_mm=None,
            applicability={
                **applicability,
                "rejected_numeric_inputs": list(invalid_numeric_keys),
            },
            configuration_reason=(
                "Boolean values are not numeric crack-control inputs "
                f"({', '.join(invalid_numeric_keys)}). Enter and explicitly "
                "confirm real numeric values before assessment."
            ),
        )]

    carried_invalid_keys = tuple(
        str(key)
        for key in (inp.get("sls_invalid_numeric_inputs") or ())
        if str(key) in CRACK_NUMERIC_INPUT_KEYS
    )
    if carried_invalid_keys:
        return [_criterion_record(
            "rejected-crack-numeric-state",
            CRITERION_DURABILITY,
            source_type=mode or "Unknown",
            source=source,
            required_combination=None,
            limit_mm=None,
            applicability={
                **applicability,
                "rejected_numeric_inputs": list(carried_invalid_keys),
            },
            configuration_reason=(
                "Rejected Boolean/non-numeric crack-control state remains "
                f"unrepaired ({', '.join(carried_invalid_keys)}). Edit or "
                "explicitly confirm every listed numeric value."
            ),
        )]

    if mode == CRITERION_MODE_LEGACY:
        return [_criterion_record(
            "legacy-ambiguous",
            CRITERION_DURABILITY,
            source_type=CRITERION_MODE_LEGACY,
            source=source,
            required_combination=None,
            limit_mm=_finite_positive(inp.get("sls_wk_limit")),
            applicability=applicability,
            configuration_reason=(
                "The saved criterion predates structured SLS-combination "
                "applicability. Select a standard-derived or project-defined "
                "criterion and explicitly designate the calculated responses."
            ),
        )]

    if mode == CRITERION_MODE_PROJECT:
        criteria = []
        limit_keys = (
            (
                COMBINATION_CHARACTERISTIC,
                "sls_project_characteristic_limit",
                "project-characteristic",
            ),
            (
                COMBINATION_FREQUENT,
                "sls_project_frequent_limit",
                "project-frequent",
            ),
            (
                COMBINATION_QUASI_PERMANENT,
                "sls_project_quasi_permanent_limit",
                "project-quasi-permanent",
            ),
        )
        for combination, key, criterion_id in limit_keys:
            limit = _finite_positive(inp.get(key))
            if limit is None:
                continue
            reason = None
            if not source:
                reason = (
                    "A project-defined criterion requires a document, clause or "
                    "approved project-requirement source."
                )
            criteria.append(_criterion_record(
                criterion_id,
                CRITERION_DURABILITY,
                source_type=CRITERION_MODE_PROJECT,
                source=source,
                required_combination=combination,
                limit_mm=limit,
                applicability={
                    **applicability,
                    "project_selected_combination": combination,
                },
                configuration_reason=reason,
            ))
        if criteria:
            return criteria
        return [_criterion_record(
            "project-missing-applicability",
            CRITERION_DURABILITY,
            source_type=CRITERION_MODE_PROJECT,
            source=source,
            required_combination=None,
            limit_mm=None,
            applicability=applicability,
            configuration_reason=(
                "No project-defined combination has a positive crack-width "
                "limit. Enter a separate limit for every applicable combination."
            ),
        )]

    if mode != CRITERION_MODE_STANDARD:
        return [_criterion_record(
            "unknown-criterion-mode",
            CRITERION_DURABILITY,
            source_type=mode or "Unknown",
            source=source,
            required_combination=None,
            limit_mm=None,
            applicability=applicability,
            configuration_reason=f"Unknown crack-criterion source mode: {mode!r}.",
        )]

    base_reasons = []
    if edition not in {"2004", "2023"}:
        base_reasons.append("The selected code edition is not supported.")
    if prestress_class not in PRESTRESS_CLASSES:
        base_reasons.append(
            "Select whether the member is reinforced/unbonded or bonded prestress."
        )
    if edition == "2004" and not exposure:
        base_reasons.append(
            "State the exposure/application context used to establish applicability."
        )
    base_reason = " ".join(base_reasons) or None
    criteria = []

    if bool(inp.get("sls_check_appearance")):
        reason = base_reason
        if edition != "2023":
            reason = " ".join(filter(None, (
                reason,
                "The standard-derived appearance criterion is implemented only "
                "for DS/EN 1992-1-1:2023 Table 9.1.",
            )))
        criteria.append(_criterion_record(
            "standard-appearance",
            CRITERION_APPEARANCE,
            source_type=CRITERION_MODE_STANDARD,
            source=_criterion_source(
                _standard_reference(
                    edition, CRITERION_APPEARANCE, dk_na
                ),
                source,
            ),
            # Table 9.1 routes the calculated appearance crack width to
            # quasi-permanent actions independently of the tendon class.
            required_combination=COMBINATION_QUASI_PERMANENT,
            limit_mm=_finite_positive(inp.get("sls_appearance_limit")),
            applicability=applicability,
            configuration_reason=reason,
        ))

    durability_selected = bool(inp.get("sls_check_durability"))
    if durability_selected and edition == "2023":
        route_reason = base_reason
        if exposure_class not in EXPOSURE_CLASSES_2023[1:]:
            route_reason = " ".join(filter(None, (
                route_reason,
                "Select the governing 2023 Table 9.2 exposure-class group.",
            )))
        if (
            prestress_class == PRESTRESS_BONDED
            and protection_class not in PROTECTION_CLASSES[1:]
        ):
            route_reason = " ".join(filter(None, (
                route_reason,
                "Select the bonded-tendon protection-level / pretensioning group.",
            )))
        if route_reason:
            criteria.append(_criterion_record(
                "standard-durability-routing",
                CRITERION_DURABILITY,
                source_type=CRITERION_MODE_STANDARD,
                source=_criterion_source(
                    _standard_reference(
                        edition, CRITERION_DURABILITY, dk_na
                    ),
                    source,
                ),
                required_combination=None,
                limit_mm=_finite_positive(inp.get("sls_wk_limit")),
                applicability=applicability,
                configuration_reason=route_reason,
            ))
        else:
            group_pl1 = (
                prestress_class == PRESTRESS_BONDED
                and protection_class == PROTECTION_LEVEL_1_OR_PRETENSIONED
            )
            reference = _criterion_source(
                _standard_reference(
                    edition, CRITERION_DURABILITY, dk_na
                ),
                source,
            )
            crack_combination = None
            decompression_combination = None
            if group_pl1:
                if exposure_class in {EXPOSURE_X0_XC1, EXPOSURE_XC2_XC4}:
                    crack_combination = COMBINATION_FREQUENT
                if exposure_class == EXPOSURE_XC2_XC4:
                    decompression_combination = COMBINATION_QUASI_PERMANENT
                elif exposure_class in {EXPOSURE_XD_XS, EXPOSURE_XF}:
                    decompression_combination = COMBINATION_FREQUENT
            elif exposure_class in {EXPOSURE_XC2_XC4, EXPOSURE_XD_XS}:
                # Reinforced/unbonded members and bonded tendons with Protection
                # Levels 2/3 occupy the same Table 9.2 branch.
                crack_combination = COMBINATION_QUASI_PERMANENT

            if crack_combination is not None:
                criteria.append(_criterion_record(
                    "standard-durability",
                    CRITERION_DURABILITY,
                    source_type=CRITERION_MODE_STANDARD,
                    source=reference,
                    required_combination=crack_combination,
                    limit_mm=_finite_positive(inp.get("sls_wk_limit")),
                    applicability=applicability,
                ))
            if decompression_combination is not None:
                criteria.append(_criterion_record(
                    "standard-decompression",
                    CRITERION_DECOMPRESSION,
                    source_type=CRITERION_MODE_STANDARD,
                    source=reference,
                    required_combination=decompression_combination,
                    limit_mm=None,
                    applicability={
                        **applicability,
                        "decompression_applicability": "Table 9.2 required",
                    },
                ))
            if (
                crack_combination is None
                and decompression_combination is None
            ):
                criteria.append(_criterion_record(
                    "standard-table-9.2-no-crack-route",
                    CRITERION_DURABILITY,
                    source_type=CRITERION_MODE_STANDARD,
                    source=reference,
                    required_combination=None,
                    limit_mm=None,
                    applicability=applicability,
                    configuration_status="NOT APPLICABLE",
                    configuration_reason=(
                        "Table 9.2 defines no crack-width or decompression "
                        "criterion for the selected member/protection and "
                        "exposure group. Any separate concrete-compression "
                        "criterion is outside this crack-control verdict."
                    ),
                ))

    if durability_selected and edition == "2004":
        durability_combination = (
            COMBINATION_FREQUENT
            if prestress_class == PRESTRESS_BONDED
            else COMBINATION_QUASI_PERMANENT
        )
        criteria.append(_criterion_record(
            "standard-durability",
            CRITERION_DURABILITY,
            source_type=CRITERION_MODE_STANDARD,
            source=_criterion_source(
                _standard_reference(
                    edition, CRITERION_DURABILITY, dk_na
                ),
                source,
            ),
            required_combination=durability_combination,
            limit_mm=_finite_positive(inp.get("sls_wk_limit")),
            applicability=applicability,
            configuration_reason=base_reason,
        ))

    if edition == "2004" and prestress_class == PRESTRESS_BONDED:
        decompression = str(
            inp.get("sls_decompression_applicability")
            or DECOMPRESSION_NOT_ESTABLISHED
        ).strip()
        if decompression == DECOMPRESSION_REQUIRED:
            criteria.append(_criterion_record(
                "standard-decompression",
                CRITERION_DECOMPRESSION,
                source_type=CRITERION_MODE_STANDARD,
                source=_criterion_source(
                    _standard_reference(
                        edition, CRITERION_DURABILITY, dk_na
                    ),
                    source,
                ),
                required_combination=COMBINATION_QUASI_PERMANENT,
                limit_mm=None,
                applicability={
                    **applicability,
                    "decompression_applicability": decompression,
                },
                configuration_reason=base_reason,
            ))
        elif decompression != DECOMPRESSION_NOT_REQUIRED:
            criteria.append(_criterion_record(
                "standard-decompression-applicability",
                CRITERION_DECOMPRESSION,
                source_type=CRITERION_MODE_STANDARD,
                source=_criterion_source(
                    _standard_reference(
                        edition, CRITERION_DURABILITY, dk_na
                    ),
                    source,
                ),
                required_combination=COMBINATION_QUASI_PERMANENT,
                limit_mm=None,
                applicability={
                    **applicability,
                    "decompression_applicability": decompression,
                },
                configuration_reason=(
                    "Establish whether quasi-permanent decompression is required "
                    "for this bonded-prestress exposure/application."
                ),
            ))

    if criteria:
        return criteria
    return [_criterion_record(
        "standard-no-criterion",
        CRITERION_DURABILITY,
        source_type=CRITERION_MODE_STANDARD,
        source=source or code,
        required_combination=None,
        limit_mm=None,
        applicability=applicability,
        configuration_reason=(
            "No standard appearance or durability criterion is selected."
        ),
    )]


def _element_id(ids: Sequence[str] | None, index: int, fallback: str) -> str:
    """Return a non-blank stable ID when supplied, otherwise ``fallback``."""
    if ids is not None and index < len(ids):
        value = str(ids[index]).strip()
        if value:
            return value
    return fallback


def _per_element(value, count: int, label: str) -> list:
    """Broadcast a scalar or validate one value per element."""
    if count == 0:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = list(value)
        if len(values) != count:
            raise ValueError(f"need {count} {label} values, got {len(values)}")
        return values
    return [value] * count


def upper_limit_assessment(
    value: float | None,
    limit: float | None,
    *,
    valid: bool = True,
    applicable: bool = True,
) -> dict:
    """Assess a positive result against an upper limit.

    ``limit <= 0`` deliberately means that no criterion was supplied.  Numerical
    results remain visible, but the public status is then ``NOT ASSESSED`` rather
    than an implied pass.
    """
    if contains_boolean_value(value) or contains_boolean_value(limit):
        raise ValueError(
            "Boolean values are not accepted as an SLS value or limit"
        )
    if not valid:
        return {
            "value": value, "limit": limit, "util": None, "margin": None,
            "status": "INVALID",
        }
    if not applicable or value is None:
        return {
            "value": value, "limit": limit, "util": None, "margin": None,
            "status": "NOT APPLICABLE",
        }
    if not math.isfinite(float(value)):
        return {
            "value": value, "limit": limit, "util": None, "margin": None,
            "status": "INVALID",
        }
    if limit is None or not math.isfinite(float(limit)) or float(limit) <= 0.0:
        return {
            "value": float(value), "limit": limit, "util": None, "margin": None,
            "status": "NOT ASSESSED",
        }
    value_f, limit_f = float(value), float(limit)
    return {
        "value": value_f,
        "limit": limit_f,
        "util": value_f / limit_f,
        "margin": limit_f - value_f,
        "status": "OK" if value_f <= limit_f else "EXCEEDED",
    }


def stress_assessments(
    total_stress: Sequence[float],
    *,
    n_bars: int,
    max_concrete_compression: float,
    fck: float,
    fyk: float | Sequence[float],
    fpk: float | Sequence[float] | None,
    concrete_limit_pct: float,
    reinforcement_limit_pct: float,
    prestress_limit_pct: float,
    valid: bool,
    bar_ids: Sequence[str] | None = None,
    tendon_ids: Sequence[str] | None = None,
) -> dict:
    """Build separate concrete, mild-steel and tendon stress assessments."""
    if isinstance(total_stress, Mapping):
        raise ValueError(
            "total_stress must be an ordered finite numeric sequence; "
            "mappings are not accepted"
        )
    if isinstance(total_stress, (str, bytes, bytearray)):
        raise ValueError(
            "total_stress must be an ordered finite numeric sequence"
        )
    try:
        total_values = tuple(total_stress)
    except TypeError as exc:
        raise ValueError(
            "total_stress must be an ordered finite numeric sequence"
        ) from exc
    boolean_inputs = {
        "total_stress": total_values,
        "max_concrete_compression": max_concrete_compression,
        "fck": fck,
        "fyk": fyk,
        "fpk": fpk,
        "concrete_limit_pct": concrete_limit_pct,
        "reinforcement_limit_pct": reinforcement_limit_pct,
        "prestress_limit_pct": prestress_limit_pct,
    }
    rejected = [
        name
        for name, value in boolean_inputs.items()
        if value is not None and contains_boolean_value(value)
    ]
    if rejected:
        raise ValueError(
            "Boolean values are not accepted for SLS stress inputs: "
            + ", ".join(rejected)
        )
    total = [float(v) for v in total_values]
    mild = total[:n_bars]
    prestress = total[n_bars:]

    fyk_values = [float(v) for v in _per_element(fyk, len(mild), "fyk")]
    fpk_values = ([float(v) for v in _per_element(fpk, len(prestress), "fpk")]
                  if fpk is not None else [])

    def _governing(values: Sequence[float], strengths: Sequence[float], pct: float):
        if not values:
            return None, None, None
        tension = [max(float(value), 0.0) for value in values]
        limits = [float(pct) / 100.0 * float(strength) for strength in strengths]
        if pct > 0.0 and any(limit > 0.0 for limit in limits):
            def score(index):
                limit = limits[index]
                return tension[index] / limit if limit > 0.0 else math.inf
            index = max(range(len(values)), key=score)
        else:
            index = max(range(len(values)), key=lambda j: tension[j])
        return tension[index], limits[index], index + 1

    mild_value, mild_limit, mild_no = _governing(
        mild, fyk_values, reinforcement_limit_pct
    )
    pre_value, pre_limit, pre_no = _governing(
        prestress, fpk_values, prestress_limit_pct
    ) if fpk_values else (None, None, None)
    concrete = upper_limit_assessment(
        max(float(max_concrete_compression), 0.0),
        float(concrete_limit_pct) / 100.0 * float(fck),
        valid=valid,
    )
    reinforcement = upper_limit_assessment(
        mild_value,
        mild_limit,
        valid=valid,
        applicable=bool(mild),
    )
    prestressing = upper_limit_assessment(
        pre_value,
        pre_limit,
        valid=valid,
        applicable=bool(prestress) and bool(fpk_values),
    )
    concrete.update(
        criterion=f"{float(concrete_limit_pct):g}% fck",
        governing="concrete compression",
    )
    reinforcement.update(
        criterion=f"{float(reinforcement_limit_pct):g}% fyk",
        governing=(_element_id(bar_ids, mild_no - 1, f"bar {mild_no}")
                   if mild_no is not None else None),
        element_no=mild_no,
    )
    prestressing.update(
        criterion=f"{float(prestress_limit_pct):g}% fpk",
        governing=(_element_id(tendon_ids, pre_no - 1, f"tendon {pre_no}")
                   if pre_no is not None else None),
        element_no=pre_no,
    )
    return {
        "concrete": concrete,
        "reinforcement": reinforcement,
        "prestress": prestressing,
    }


def crack_assessment(
    cases: Mapping[str, Mapping | None],
    *,
    limit_mm: float | None = None,
    valid: bool,
    dispositions: Mapping[str, Mapping | None] | None = None,
    response_contexts: Mapping[str, Mapping | None] | None = None,
    response_mapping_scope: Sequence[Mapping] | None = None,
    criteria: Sequence[Mapping] | None = None,
) -> dict:
    """Route crack-control criteria to explicitly designated SLS responses.

    A response duration never implies a combination. Only responses whose
    structured context matches a criterion's required combination may govern it;
    every other calculated response stays informational. Missing or duplicate
    response-state mappings fail closed as ``NOT ASSESSED``.
    """
    supplied_criteria = [dict(item) for item in (criteria or [])]
    if not supplied_criteria:
        supplied_criteria = [_criterion_record(
            "legacy-call-ambiguous",
            CRITERION_DURABILITY,
            source_type=CRITERION_MODE_LEGACY,
            source="",
            required_combination=None,
            limit_mm=_finite_positive(limit_mm),
            applicability={},
            configuration_reason=(
                "No structured criterion applicability was supplied; duration "
                "labels cannot be used as SLS-combination designations."
            ),
        )]

    contexts = {}
    for name in cases:
        raw = (response_contexts or {}).get(name) or {}
        contexts[name] = {
            "combination": canonical_combination(raw.get("combination")),
            "duration": str(raw.get("duration") or "").strip() or None,
            "response_id": str(
                raw.get("response_id") or name
            ).strip(),
            "provenance": str(raw.get("provenance") or "").strip() or None,
            "solver_provenance": raw.get("solver_provenance"),
        }

    mapping_scope = []
    for index, raw in enumerate(response_mapping_scope or ()):
        if not isinstance(raw, Mapping):
            continue
        response_id = str(raw.get("response_id") or "").strip()
        mapping_scope.append({
            "combination": canonical_combination(raw.get("combination")),
            "duration": str(raw.get("duration") or "").strip() or None,
            "response": str(
                raw.get("response")
                or raw.get("response_id")
                or f"response {index + 1}"
            ).strip(),
            "response_id": response_id or f"scope-response-{index + 1}",
            "elastic_case": (
                str(raw.get("elastic_case") or "").strip() or None
            ),
            "state": str(raw.get("state") or "").strip() or None,
            "provenance": (
                str(raw.get("provenance") or "").strip() or None
            ),
            "solver_provenance": raw.get("solver_provenance"),
        })

    if not valid:
        out = upper_limit_assessment(None, limit_mm, valid=False)
        out.update(
            case=None,
            governing=None,
            criterion=(
                f"{float(limit_mm):g} mm"
                if _finite_positive(limit_mm) is not None
                else "structured crack-control criteria"
            ),
            reason="The elastic analysis did not converge.",
            verdict="REVIEW",
            criteria=[],
            response_contexts=contexts,
            response_mapping_scope=mapping_scope,
            informational_responses=list(cases),
        )
        return out

    validated_widths: dict[str, float] = {}
    rejected_widths = []
    for name, response in cases.items():
        if response is None:
            continue
        if not isinstance(response, Mapping):
            rejected_widths.append(name)
            continue
        width = crack_width_numeric_value(response.get("wk"))
        if width is None:
            rejected_widths.append(name)
        else:
            validated_widths[name] = width

    criterion_results = []
    if rejected_widths:
        criterion_results.append({
            "criterion_id": "calculated-crack-response-integrity",
            "kind": "Calculated crack-width response integrity",
            "criterion_source_type": "Solver result validation",
            "criterion_source": "Calculated response integrity gate",
            "applicability": {
                "rejected_responses": list(rejected_widths),
            },
            "required_combination": None,
            "limit": None,
            "util": None,
            "margin": None,
            "value": None,
            "case": ", ".join(rejected_widths),
            "governing": None,
            "response_duration": None,
            "response_provenance": [
                {
                    "response": name,
                    "response_id": contexts[name]["response_id"],
                    "combination": contexts[name]["combination"],
                    "duration": contexts[name]["duration"],
                    "mapping": contexts[name]["provenance"],
                }
                for name in rejected_widths
            ],
            "solver_provenance": [
                {
                    "response": name,
                    "solver": contexts[name]["solver_provenance"],
                }
                for name in rejected_widths
            ],
            "matched_responses": list(rejected_widths),
            "status": "NOT ASSESSED",
            "reason": (
                "Calculated crack-width result rejected for "
                f"{', '.join(rejected_widths)}: w_k is Boolean-bearing, "
                "missing, non-scalar, non-finite or negative. Every non-null "
                "calculated response, including informational responses, is "
                "validated before combination routing. No overall acceptance "
                "verdict was issued."
            ),
        })
    matched_names: set[str] = set()
    disposition_map = dispositions or {}

    for criterion in supplied_criteria:
        item = dict(criterion)
        required = item.get("required_combination")
        required = (
            canonical_combination(required) if required is not None else None
        )
        limit = _finite_positive(item.get("limit_mm"))
        label = str(item.get("kind") or "Crack width")
        base = {
            "criterion_id": item.get("id"),
            "kind": label,
            "criterion_source_type": item.get("source_type"),
            "criterion_source": item.get("source"),
            "applicability": dict(item.get("applicability") or {}),
            "required_combination": required,
            "limit": limit,
            "util": None,
            "margin": None,
            "value": None,
            "case": None,
            "governing": None,
            "response_duration": None,
            "response_provenance": None,
            "solver_provenance": None,
            "matched_responses": [],
        }
        configuration_reason = item.get("configuration_reason")
        configuration_status = str(
            item.get("configuration_status") or ""
        ).upper()
        if configuration_status == "NOT APPLICABLE":
            base.update(
                status="NOT APPLICABLE",
                reason=str(
                    configuration_reason
                    or "The criterion is not applicable to the selected scope."
                ),
            )
            criterion_results.append(base)
            continue
        if (
            configuration_status == "NOT ASSESSED"
            or configuration_reason
        ):
            base.update(
                status="NOT ASSESSED",
                reason=str(
                    configuration_reason
                    or "Criterion applicability is not established."
                ),
            )
            criterion_results.append(base)
            continue
        if required not in SLS_COMBINATIONS[1:]:
            base.update(
                status="NOT ASSESSED",
                reason="The criterion has no valid required SLS combination.",
            )
            criterion_results.append(base)
            continue

        scoped_candidates = [
            context
            for context in mapping_scope
            if context["combination"] == required
        ]
        scoped_response_ids = {
            context["response_id"] for context in scoped_candidates
        }
        if len(scoped_response_ids) > 1:
            base.update(
                status="NOT ASSESSED",
                case=", ".join(
                    context["response"] for context in scoped_candidates
                ),
                matched_responses=[
                    context["response"] for context in scoped_candidates
                ],
                response_provenance=[
                    {
                        "response": context["response"],
                        "response_id": context["response_id"],
                        "elastic_case": context["elastic_case"],
                        "combination": context["combination"],
                        "duration": context["duration"],
                        "mapping": context["provenance"],
                    }
                    for context in scoped_candidates
                ],
                solver_provenance=[
                    {
                        "response": context["response"],
                        "solver": context["solver_provenance"],
                    }
                    for context in scoped_candidates
                ],
                reason=(
                    f"More than one independent response state is designated as "
                    f"the {required} combination across checked Elastic cases; "
                    "applicability is ambiguous."
                ),
            )
            criterion_results.append(base)
            continue

        candidates = [
            name
            for name, context in contexts.items()
            if context["combination"] == required
        ]
        response_ids = {
            contexts[name]["response_id"] for name in candidates
        }
        if not candidates:
            base.update(
                status="NOT ASSESSED",
                case=required,
                response_provenance=[
                    {
                        "response": name,
                        "combination": context["combination"],
                        "duration": context["duration"],
                        "mapping": context["provenance"],
                    }
                    for name, context in contexts.items()
                ],
                solver_provenance=[
                    {
                        "response": name,
                        "solver": context["solver_provenance"],
                    }
                    for name, context in contexts.items()
                ],
                reason=(
                    f"No calculated response is explicitly designated as the "
                    f"{required} combination. No duration-to-combination "
                    "assumption was made."
                ),
            )
            criterion_results.append(base)
            continue
        if len(response_ids) != 1:
            base.update(
                status="NOT ASSESSED",
                case=", ".join(candidates),
                matched_responses=candidates,
                response_provenance=[
                    {
                        "response": name,
                        "combination": contexts[name]["combination"],
                        "duration": contexts[name]["duration"],
                        "mapping": contexts[name]["provenance"],
                    }
                    for name in candidates
                ],
                solver_provenance=[
                    {
                        "response": name,
                        "solver": contexts[name]["solver_provenance"],
                    }
                    for name in candidates
                ],
                reason=(
                    f"More than one independent response state is designated as "
                    f"the {required} combination; applicability is ambiguous."
                ),
            )
            criterion_results.append(base)
            continue

        matched_names.update(candidates)
        base["matched_responses"] = candidates
        base["response_duration"] = contexts[candidates[0]]["duration"]
        base["response_provenance"] = contexts[candidates[0]]["provenance"]
        base["solver_provenance"] = contexts[candidates[0]][
            "solver_provenance"
        ]
        candidate_dispositions = [
            (name, disposition_map.get(name))
            for name in candidates
            if disposition_map.get(name) is not None
        ]
        blocking = [
            (name, disposition)
            for name, disposition in candidate_dispositions
            if str(disposition.get("status") or "").upper()
            in {"NOT ASSESSED", "INVALID"}
        ]
        if blocking:
            base.update(
                status="NOT ASSESSED",
                case=", ".join(name for name, _disposition in blocking),
                solver_provenance=[
                    {
                        "response": name,
                        "status": disposition.get("status"),
                        "reason": disposition.get("reason"),
                        "scope": disposition.get("scope"),
                    }
                    for name, disposition in blocking
                ],
                reason=" ".join(
                    f"{name}: "
                    f"{disposition.get('reason') or 'Solver applicability was not established.'}"
                    for name, disposition in blocking
                ),
            )
            criterion_results.append(base)
            continue

        rejected_candidates = [
            name
            for name in candidates
            if cases.get(name) is not None and name in rejected_widths
        ]
        if rejected_candidates:
            base.update(
                status="NOT ASSESSED",
                case=", ".join(rejected_candidates),
                reason=(
                    "Calculated crack-width result rejected for "
                    f"{', '.join(rejected_candidates)}: w_k is Boolean-bearing, "
                    "missing, non-scalar, non-finite or negative. No acceptance "
                    "verdict was issued."
                ),
                solver_provenance=[
                    {
                        "response": name,
                        "solver": contexts[name]["solver_provenance"],
                    }
                    for name in rejected_candidates
                ],
            )
            criterion_results.append(base)
            continue

        if label == CRITERION_DECOMPRESSION:
            decompression = [
                (name, (cases.get(name) or {}).get("decompression"))
                for name in candidates
                if (cases.get(name) or {}).get("decompression") is not None
            ]
            if not decompression:
                base.update(
                    status="NOT ASSESSED",
                    case=", ".join(candidates),
                    reason=(
                        f"The {required} response is present, but the current "
                        "section solver does not produce the concrete-stress "
                        "evidence required for a decompression verdict."
                    ),
                )
                criterion_results.append(base)
                continue
            name, evidence = decompression[0]
            evidence = dict(evidence)
            status = str(evidence.get("status") or "NOT ASSESSED").upper()
            if status not in {"OK", "EXCEEDED", "NOT APPLICABLE"}:
                status = "NOT ASSESSED"
            base.update(
                status=status,
                case=name,
                value=evidence.get("value"),
                governing=evidence.get("governing"),
                reason=str(
                    evidence.get("reason")
                    or f"Decompression checked for the {required} response."
                ),
                solver_provenance=evidence.get(
                    "solver_provenance", base["solver_provenance"]
                ),
            )
            criterion_results.append(base)
            continue

        if limit is None:
            base.update(
                status="NOT ASSESSED",
                case=", ".join(candidates),
                reason=(
                    f"The {label.lower()} criterion has no positive limit for "
                    f"the {required} combination."
                ),
            )
            criterion_results.append(base)
            continue

        available = [
            (name, cases.get(name))
            for name in candidates
            if cases.get(name) is not None
        ]
        if not available:
            reasons = [
                str(disposition.get("reason"))
                for _name, disposition in candidate_dispositions
                if disposition.get("reason")
            ]
            base.update(
                status="NOT APPLICABLE",
                case=", ".join(candidates),
                reason=(
                    " ".join(dict.fromkeys(reasons))
                    if reasons
                    else f"No {required} crack-width response is applicable."
                ),
            )
            criterion_results.append(base)
            continue

        checked_available = [
            (name, response, validated_widths[name])
            for name, response in available
        ]
        name, governing, governing_width = max(
            checked_available,
            key=lambda item: item[2],
        )
        assessed = upper_limit_assessment(
            governing_width,
            limit,
            valid=True,
        )
        base.update(assessed)
        base.update(
            case=name,
            governing=governing.get(
                "element_id", f"element {governing.get('gov_bar', '-')}"
            ),
            reason=(
                f"Assessed only against the explicitly designated {required} "
                "response; other duration states are informational."
            ),
        )
        criterion_results.append(base)

    statuses = [item["status"] for item in criterion_results]
    if any(status == "INVALID" for status in statuses):
        overall_status = "INVALID"
    elif any(status == "NOT ASSESSED" for status in statuses):
        overall_status = "NOT ASSESSED"
    elif any(status == "EXCEEDED" for status in statuses):
        overall_status = "EXCEEDED"
    elif any(status == "OK" for status in statuses):
        overall_status = "OK"
    else:
        overall_status = "NOT APPLICABLE"

    if overall_status in {"INVALID", "NOT ASSESSED"}:
        governing_criterion = next(
            item
            for item in criterion_results
            if item["status"] == overall_status
            or (
                overall_status == "NOT ASSESSED"
                and item["status"] == "NOT ASSESSED"
            )
        )
    elif overall_status == "EXCEEDED":
        governing_criterion = max(
            (
                item
                for item in criterion_results
                if item["status"] == "EXCEEDED"
            ),
            key=lambda item: float(item.get("util") or 0.0),
        )
    elif overall_status == "OK":
        governing_criterion = max(
            (item for item in criterion_results if item["status"] == "OK"),
            key=lambda item: float(item.get("util") or 0.0),
        )
    else:
        governing_criterion = criterion_results[0]

    informational = [name for name in cases if name not in matched_names]
    verdict = {
        "OK": "PASS",
        "EXCEEDED": "FAIL",
        "NOT APPLICABLE": "NOT APPLICABLE",
    }.get(overall_status, "REVIEW")
    return {
        "value": governing_criterion.get("value"),
        "limit": governing_criterion.get("limit"),
        "util": governing_criterion.get("util"),
        "margin": governing_criterion.get("margin"),
        "status": overall_status,
        "verdict": verdict,
        "case": governing_criterion.get("case"),
        "governing": governing_criterion.get("governing"),
        "criterion": governing_criterion.get("kind"),
        "required_combination": governing_criterion.get(
            "required_combination"
        ),
        "criterion_source": governing_criterion.get("criterion_source"),
        "applicability": governing_criterion.get("applicability"),
        "response_duration": governing_criterion.get("response_duration"),
        "response_provenance": governing_criterion.get(
            "response_provenance"
        ),
        "solver_provenance": governing_criterion.get("solver_provenance"),
        "reason": governing_criterion.get("reason"),
        "criteria": criterion_results,
        "response_contexts": contexts,
        "response_mapping_scope": mapping_scope,
        "informational_responses": informational,
    }


def element_rows(
    bars: Sequence[Sequence[float]],
    tendons: Sequence[Sequence[float]],
    *,
    total: Sequence[float],
    long: Sequence[float],
    dif: Sequence[float],
    rst1: Sequence[float],
    es_mpa: float | Sequence[float],
    ep_mpa: float | Sequence[float] | None,
    bar_ids: Sequence[str] | None = None,
    tendon_ids: Sequence[str] | None = None,
    bar_material_ids: Sequence[str] | None = None,
    tendon_material_ids: Sequence[str] | None = None,
    bar_material_names: Sequence[str] | None = None,
    tendon_material_names: Sequence[str] | None = None,
) -> list[dict]:
    """Return a complete, explicitly typed SLS row for every bar and tendon."""
    rows: list[dict] = []
    bar_moduli = [float(v) for v in _per_element(es_mpa, len(bars), "Es")]
    fallback_es = bar_moduli[0] if bar_moduli else 200_000.0
    tendon_moduli = (
        [float(v) for v in _per_element(ep_mpa, len(tendons), "Ep")]
        if ep_mpa is not None else [fallback_es] * len(tendons)
    )
    elements = [
        ("Bar", i + 1,
         _element_id(bar_ids, i, f"bar {i + 1}"), p, bar_moduli[i],
         _element_id(bar_material_ids, i, ""),
         _element_id(bar_material_names, i, ""))
        for i, p in enumerate(bars)
    ]
    elements.extend(
        ("Tendon", i + 1,
         _element_id(tendon_ids, i, f"tendon {i + 1}"),
         p, tendon_moduli[i],
         _element_id(tendon_material_ids, i, ""),
         _element_id(tendon_material_names, i, ""))
        for i, p in enumerate(tendons)
    )
    arrays = ([float(v) for v in total], [float(v) for v in long],
              [float(v) for v in dif], [float(v) for v in rst1])
    for i, (kind, number, element_id, point, modulus,
            material_id, material_name) in enumerate(elements):
        stress = arrays[0][i]
        rows.append({
            "element_type": kind,
            "element_no": number,
            "element_id": element_id,
            "material_id": material_id or None,
            "material_name": material_name or None,
            "x_mm": float(point[0]) * 1000.0,
            "y_mm": float(point[1]) * 1000.0,
            "area_mm2": float(point[2]),
            "strain_permille": stress / modulus * 1000.0 if modulus else math.nan,
            "total_mpa": stress,
            "long_mpa": arrays[1][i],
            "dif_mpa": arrays[2][i],
            "rst1_mpa": arrays[3][i],
        })
    return rows


def concrete_corner_rows(
    outer: Sequence[Sequence[float]],
    holes: Iterable[Sequence[Sequence[float]]],
    *,
    stress_plane: Sequence[float],
    ec_mpa: float,
) -> list[dict]:
    """Evaluate the cracked concrete stress/strain plane at every polygon corner."""
    eps0, kx, ky = (float(v) for v in stress_plane)
    rows: list[dict] = []
    point_no = 0
    rings = [("Outer", 1, outer)]
    rings.extend(("Void", i + 1, ring) for i, ring in enumerate(holes))
    for ring_type, ring_no, ring in rings:
        for local_no, point in enumerate(ring, start=1):
            point_no += 1
            x, y = float(point[0]), float(point[1])
            raw_kpa = eps0 + kx * x + ky * y
            rows.append({
                "point_no": point_no,
                "ring": ring_type if ring_type == "Outer" else f"Void {ring_no}",
                "ring_point_no": local_no,
                "x_mm": x * 1000.0,
                "y_mm": y * 1000.0,
                "strain_permille": (
                    raw_kpa / (float(ec_mpa) * 1000.0) * 1000.0
                    if ec_mpa else math.nan
                ),
                # Cracked concrete carries compression only.  The compatible
                # tensile strain remains useful evidence while its stress is zero.
                "stress_mpa": min(raw_kpa / 1000.0, 0.0),
            })
    return rows
