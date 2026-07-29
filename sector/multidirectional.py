"""Fail-closed multidirectional crack and shear interaction methods.

The one-direction crack solver and the directional ``Vx``/``Vy`` shear solvers
remain authoritative for their component results.  This module adds only
explicitly selected interaction methods.  It never infers an interaction from
two component PASS results.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from numbers import Real

from . import danish_bridge, sls


CRACK_METHOD_NONE = "not-assessed"
CRACK_METHOD_DK_2004 = "crack-dk-na-2004-7.3.4"
CRACK_METHOD_EN_2023 = "crack-en-2023-g.5"
CRACK_METHOD_PROJECT = "crack-project-power-sum"

SHEAR_METHOD_NONE = "not-assessed"
SHEAR_METHOD_EN_2023 = "shear-en-2023-8.2.1(5)"
SHEAR_METHOD_PROJECT = "shear-project-power-sum"

DEPTH_ROUTE_PIECEWISE = "Formulas (8.22)-(8.24) piecewise depth"
DEPTH_ROUTE_ROTATED = "Formula (8.25) rotated depth"
DEPTH_ROUTES = (DEPTH_ROUTE_PIECEWISE, DEPTH_ROUTE_ROTATED)

CRACK_METHOD_LABELS = {
    CRACK_METHOD_NONE: "Not assessed - component crack results only",
    CRACK_METHOD_DK_2004: (
        "DS/EN 1992-1-1:2004 + DK NA 7.3.4(4)"
    ),
    CRACK_METHOD_EN_2023: "EN 1992-1-1:2023 Annex G.5",
    CRACK_METHOD_PROJECT: "Approved project crack power sum",
}
SHEAR_METHOD_LABELS = {
    SHEAR_METHOD_NONE: "Not assessed - independent Vx/Vy only",
    SHEAR_METHOD_EN_2023: "EN 1992-1-1:2023 8.2.1(5) planar resultant",
    SHEAR_METHOD_PROJECT: "Approved project shear power sum",
}

CRACK_METHODS = tuple(CRACK_METHOD_LABELS)
SHEAR_METHODS = tuple(SHEAR_METHOD_LABELS)

CRACK_SOURCE_DK_2004 = (
    "EN 1992-1-1:2004 + AC:2008, 7.3.4(4), Formula (7.15); "
    "DS/EN 1992-1-1 DK NA:2021 rev. 2024-01-09, 7.3.4(4), "
    "Formula (7.101 NA)"
)
CRACK_SOURCE_EN_2023 = (
    "EN 1992-1-1:2023, 9.2.3(7) and normative Annex G.5, "
    "Formulas (G.22)-(G.27)"
)
SHEAR_SOURCE_EN_2023 = (
    "EN 1992-1-1:2023, 8.2.1(5), Formulas (8.21)-(8.26)"
)
SHEAR_EN_2023_ROTATION_SCOPE = (
    "The vector demand resultant is rotationally invariant; the full qualified "
    "interaction remains directional because external resistance isotropy is "
    "not evidenced."
)

CRACK_CODE_DK_2004 = "DS/EN 1992-1-1 + DK NA"
CRACK_CODE_EN_2023 = "EN 1992-1-1:2023"
SHEAR_CODE_EN_2023 = "DS/EN 1992-1-1:2023"

INTERACTION_RESULT_SCHEMA = "sector.multidirectional.interaction.v1"
INTERACTION_BUNDLE_SCHEMA = "sector.multidirectional.bundle.v1"
DIRECTIONAL_SHEAR_CASE_SCHEMA = "sector.multidirectional.shear-case.v1"

_PASS_TOLERANCE = 1.0e-9
_VALUE_REL_TOLERANCE = 1.0e-9
_VALUE_ABS_TOLERANCE = 1.0e-12
_FINITE_UTILISATION_CAP = 1.0e300


CRACK_INPUT_KEYS = (
    "crack_interaction_on",
    "crack_interaction_method",
    "crack_interaction_case_id",
    "crack_interaction_criterion_id",
    "crack_interaction_combination",
    "crack_interaction_axis_x",
    "crack_interaction_axis_y",
    "crack_interaction_orthogonal",
    "crack_interaction_plane_stress",
    "crack_interaction_membrane",
    "crack_interaction_no_discontinuity",
    "crack_interaction_domain_confirmed",
    "crack_interaction_angle_deg",
    "crack_interaction_spacing_x_mm",
    "crack_interaction_spacing_y_mm",
    "crack_interaction_strain_x",
    "crack_interaction_strain_y",
    "crack_interaction_transverse_strain",
    "crack_interaction_component_x_mm",
    "crack_interaction_component_y_mm",
    "crack_interaction_limit_x_mm",
    "crack_interaction_limit_y_mm",
    "crack_interaction_exponent",
    "crack_interaction_source",
    "crack_interaction_approval",
)

SHEAR_INPUT_KEYS = (
    "shear_interaction_on",
    "shear_interaction_method",
    "shear_interaction_axis_x",
    "shear_interaction_axis_y",
    "shear_interaction_planar_member",
    "shear_interaction_same_control_point",
    "shear_interaction_per_unit_width",
    "shear_interaction_out_of_plane",
    "shear_interaction_domain_confirmed",
    "shear_interaction_depth_route",
    "shear_interaction_resultant_resistance_kn_per_m",
    "shear_interaction_exponent",
    "shear_interaction_source",
    "shear_interaction_approval",
)

INTERACTION_INPUT_KEYS = CRACK_INPUT_KEYS + SHEAR_INPUT_KEYS

CRACK_NUMERIC_INPUT_KEYS = (
    "crack_interaction_angle_deg",
    "crack_interaction_spacing_x_mm",
    "crack_interaction_spacing_y_mm",
    "crack_interaction_strain_x",
    "crack_interaction_strain_y",
    "crack_interaction_transverse_strain",
    "crack_interaction_component_x_mm",
    "crack_interaction_component_y_mm",
    "crack_interaction_limit_x_mm",
    "crack_interaction_limit_y_mm",
    "crack_interaction_exponent",
)
SHEAR_NUMERIC_INPUT_KEYS = (
    "shear_interaction_resultant_resistance_kn_per_m",
    "shear_interaction_exponent",
)
INTERACTION_NUMERIC_INPUT_KEYS = (
    CRACK_NUMERIC_INPUT_KEYS + SHEAR_NUMERIC_INPUT_KEYS
)
INTERACTION_BOOLEAN_INPUT_KEYS = (
    "crack_interaction_on",
    "crack_interaction_orthogonal",
    "crack_interaction_plane_stress",
    "crack_interaction_membrane",
    "crack_interaction_no_discontinuity",
    "crack_interaction_domain_confirmed",
    "shear_interaction_on",
    "shear_interaction_planar_member",
    "shear_interaction_same_control_point",
    "shear_interaction_per_unit_width",
    "shear_interaction_out_of_plane",
    "shear_interaction_domain_confirmed",
)
INTERACTION_SELECTION_INPUT_KEYS = (
    "crack_interaction_method",
    "crack_interaction_combination",
    "shear_interaction_method",
    "shear_interaction_depth_route",
)
INTERACTION_TEXT_INPUT_KEYS = tuple(
    key
    for key in INTERACTION_INPUT_KEYS
    if key not in INTERACTION_NUMERIC_INPUT_KEYS
    and key not in INTERACTION_BOOLEAN_INPUT_KEYS
    and key not in INTERACTION_SELECTION_INPUT_KEYS
)

_CRACK_DEFAULTS = {
    "crack_interaction_on": False,
    "crack_interaction_method": CRACK_METHOD_NONE,
    "crack_interaction_case_id": "",
    "crack_interaction_criterion_id": "",
    "crack_interaction_combination": sls.COMBINATION_UNSPECIFIED,
    "crack_interaction_axis_x": "x reinforcement direction",
    "crack_interaction_axis_y": "y reinforcement direction",
    "crack_interaction_orthogonal": False,
    "crack_interaction_plane_stress": False,
    "crack_interaction_membrane": False,
    "crack_interaction_no_discontinuity": False,
    "crack_interaction_domain_confirmed": False,
    "crack_interaction_angle_deg": 45.0,
    "crack_interaction_spacing_x_mm": 150.0,
    "crack_interaction_spacing_y_mm": 150.0,
    "crack_interaction_strain_x": 0.0005,
    "crack_interaction_strain_y": 0.0005,
    "crack_interaction_transverse_strain": 0.0,
    "crack_interaction_component_x_mm": 0.0,
    "crack_interaction_component_y_mm": 0.0,
    "crack_interaction_limit_x_mm": 0.3,
    "crack_interaction_limit_y_mm": 0.3,
    "crack_interaction_exponent": 2.0,
    "crack_interaction_source": "",
    "crack_interaction_approval": "",
}

_SHEAR_DEFAULTS = {
    "shear_interaction_on": False,
    "shear_interaction_method": SHEAR_METHOD_NONE,
    "shear_interaction_axis_x": "global x / Vx",
    "shear_interaction_axis_y": "global y / Vy",
    "shear_interaction_planar_member": False,
    "shear_interaction_same_control_point": False,
    "shear_interaction_per_unit_width": False,
    "shear_interaction_out_of_plane": False,
    "shear_interaction_domain_confirmed": False,
    "shear_interaction_depth_route": DEPTH_ROUTE_PIECEWISE,
    "shear_interaction_resultant_resistance_kn_per_m": 0.0,
    "shear_interaction_exponent": 2.0,
    "shear_interaction_source": "",
    "shear_interaction_approval": "",
}


class InteractionInputError(ValueError):
    """Malformed or unusable interaction input."""


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _fingerprint(value) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _audit_value(value):
    """Return a JSON-safe value without disguisising rejected input state."""

    if value is None or isinstance(value, str):
        return value
    if _is_boolean(value):
        return bool(value)
    if isinstance(value, Real):
        number = float(value)
        if math.isfinite(number):
            return number
        return {
            "rejected_type": type(value).__qualname__,
            "rejected_value": repr(value),
        }
    if isinstance(value, Mapping):
        return {
            str(key): _audit_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_audit_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(
            (_audit_value(item) for item in value),
            key=repr,
        )
    return {
        "rejected_type": (
            f"{type(value).__module__}.{type(value).__qualname__}"
        ),
        "rejected_value": repr(value),
    }


def _is_boolean(value) -> bool:
    value_type = type(value)
    return isinstance(value, bool) or (
        value_type.__name__ == "bool"
        and value_type.__module__.split(".", 1)[0] in {"numpy", "pandas"}
    )


def _real(value, label: str, *, positive=False, nonnegative=False) -> float:
    if _is_boolean(value) or not isinstance(value, Real):
        raise InteractionInputError(
            f"{label} must be a finite real number; Boolean/text values "
            "are not accepted"
        )
    number = float(value)
    if not math.isfinite(number):
        raise InteractionInputError(f"{label} must be finite")
    if positive and number <= 0.0:
        raise InteractionInputError(f"{label} must be greater than zero")
    if nonnegative and number < 0.0:
        raise InteractionInputError(f"{label} must not be negative")
    return number


def _required_text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InteractionInputError(f"{label} must be stated")
    return value.strip()


def _strict_boolean(value, label: str) -> bool:
    if not isinstance(value, bool):
        raise InteractionInputError(
            f"{label} must be an explicit Boolean selection"
        )
    return value


def _close(left, right) -> bool:
    try:
        return math.isclose(
            float(left),
            float(right),
            rel_tol=_VALUE_REL_TOLERANCE,
            abs_tol=_VALUE_ABS_TOLERANCE,
        )
    except (TypeError, ValueError):
        return False


def _bounded_power_ratio(
    numerator: float,
    denominator: float,
    exponent: float,
) -> tuple[float, bool]:
    """Evaluate a positive power ratio without rejecting finite custom inputs."""

    if numerator == 0.0:
        return 0.0, False
    ratio = numerator / denominator
    if math.isfinite(ratio) and ratio > 0.0:
        try:
            direct = ratio ** exponent
        except OverflowError:
            direct = math.inf
        if math.isfinite(direct):
            if direct <= _FINITE_UTILISATION_CAP:
                return direct, False
            return _FINITE_UTILISATION_CAP, True

    logarithm = exponent * (
        math.log(numerator) - math.log(denominator)
    )
    if logarithm >= math.log(_FINITE_UTILISATION_CAP):
        return _FINITE_UTILISATION_CAP, True
    try:
        value = math.exp(logarithm)
    except OverflowError:
        return _FINITE_UTILISATION_CAP, True
    return value, False


def _bounded_power_sum(
    numerator_x: float,
    denominator_x: float,
    numerator_y: float,
    denominator_y: float,
    exponent: float,
) -> tuple[float, float, float, bool, bool, bool]:
    term_x, bounded_x = _bounded_power_ratio(
        numerator_x, denominator_x, exponent
    )
    term_y, bounded_y = _bounded_power_ratio(
        numerator_y, denominator_y, exponent
    )
    raw_sum = term_x + term_y
    bounded_sum = raw_sum > _FINITE_UTILISATION_CAP
    utilisation = min(raw_sum, _FINITE_UTILISATION_CAP)
    return (
        term_x,
        term_y,
        utilisation,
        bounded_x,
        bounded_y,
        bounded_x or bounded_y or bounded_sum,
    )


def _configuration(inp: Mapping | None, defaults: Mapping, keys: Sequence[str]):
    source = inp if isinstance(inp, Mapping) else {}
    return {
        key: copy.deepcopy(source.get(key, defaults[key]))
        for key in keys
    }


def _rejected_input_keys(
    inp: Mapping | None,
    relevant_keys: Sequence[str],
) -> tuple[str, ...]:
    """Return live-state fields already rejected by an input boundary."""

    if not isinstance(inp, Mapping):
        return ()
    raw = inp.get("invalid_interaction_input_keys", ())
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return ()
    relevant = set(relevant_keys)
    return tuple(sorted({
        str(key)
        for key in raw
        if str(key) in relevant
    }))


def crack_configuration(inp: Mapping | None) -> dict:
    """Return the complete crack-interaction input snapshot."""

    return _configuration(inp, _CRACK_DEFAULTS, CRACK_INPUT_KEYS)


def shear_configuration(inp: Mapping | None) -> dict:
    """Return the complete shear-interaction input snapshot."""

    return _configuration(inp, _SHEAR_DEFAULTS, SHEAR_INPUT_KEYS)


def interaction_configuration(inp: Mapping | None) -> dict:
    """Return both independent interaction configurations."""

    return {
        "crack": crack_configuration(inp),
        "shear": shear_configuration(inp),
    }


def _crack_case_identity(record: Mapping | None) -> str:
    """Return a structurally valid bound or configured Elastic case identity."""

    if not isinstance(record, Mapping):
        return ""
    for container_name, field_name in (
        ("criterion", "elastic_case"),
        ("configuration", "crack_interaction_case_id"),
    ):
        container = record.get(container_name)
        if not isinstance(container, Mapping):
            continue
        case_id = container.get(field_name)
        if isinstance(case_id, str) and case_id.strip():
            return case_id
    return ""


def _result_base(kind: str, config: Mapping, method: str) -> dict:
    labels = (
        CRACK_METHOD_LABELS if kind == "crack" else SHEAR_METHOD_LABELS
    )
    return {
        "schema": INTERACTION_RESULT_SCHEMA,
        "kind": kind,
        "enabled": bool(
            config.get(
                "crack_interaction_on"
                if kind == "crack"
                else "shear_interaction_on"
            )
        ),
        "method": method,
        "method_name": labels.get(method, str(method or "")),
        "configuration": _audit_value(dict(config)),
        "interaction_assessed": False,
        "status": "NOT ASSESSED",
        "verdict": "REVIEW",
        "qualification": None,
        "utilisation": None,
        "components": [],
        "terms": [],
        "reason": "",
        "issues": [],
    }


def _seal_result(record: Mapping) -> dict:
    safe = copy.deepcopy(dict(record))
    safe.pop("evidence_fingerprint", None)
    safe["evidence_fingerprint"] = _fingerprint(safe)
    return safe


def _seal_directional_shear_case(
    case_id: str,
    components: Sequence[Mapping],
) -> dict:
    """Seal a separate copy of the current directional solver evidence."""

    record = {
        "schema": DIRECTIONAL_SHEAR_CASE_SCHEMA,
        "case": str(case_id or ""),
        "components": copy.deepcopy(list(components)),
    }
    record["fingerprint"] = _fingerprint(record)
    return record


def _not_assessed(
    kind: str,
    config: Mapping,
    method: str,
    reason: str,
    *,
    issues: Sequence[str] = (),
    status: str = "NOT ASSESSED",
) -> dict:
    record = _result_base(kind, config, method)
    record.update(
        status=status,
        reason=str(reason),
        issues=[str(issue) for issue in issues if str(issue).strip()],
    )
    return _seal_result(record)


def _not_applicable(
    kind: str,
    config: Mapping,
    method: str,
    reason: str,
) -> dict:
    record = _result_base(kind, config, method)
    record.update(
        interaction_assessed=True,
        status="NOT APPLICABLE",
        verdict="NOT APPLICABLE",
        reason=str(reason),
    )
    return _seal_result(record)


def _invalid(
    kind: str,
    config: Mapping,
    method: str,
    error: Exception | str,
) -> dict:
    reason = str(error)
    return _not_assessed(
        kind,
        config,
        method,
        reason,
        issues=(reason,),
        status="INVALID",
    )


def _axes(config: Mapping, prefix: str) -> dict:
    axis_x = _required_text(config.get(f"{prefix}_axis_x"), "x-axis definition")
    axis_y = _required_text(config.get(f"{prefix}_axis_y"), "y-axis definition")
    if axis_x.casefold() == axis_y.casefold():
        raise InteractionInputError("x and y axis definitions must be distinct")
    return {"x": axis_x, "y": axis_y}


def _domain(
    config: Mapping,
    checks: Sequence[tuple[str, str]],
) -> tuple[dict, list[str]]:
    evidence = {}
    missing = []
    for key, label in checks:
        selected = _strict_boolean(config.get(key), label)
        evidence[label] = selected
        if not selected:
            missing.append(label)
    return evidence, missing


def _elastic_cases(results: Mapping | None) -> list[tuple[str, Mapping]]:
    result_map = results if isinstance(results, Mapping) else {}
    entries = result_map.get("elastic_cases")
    cases = []
    if isinstance(entries, Sequence) and not isinstance(entries, (str, bytes)):
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            name = str(entry.get("name") or "").strip()
            elastic = (entry.get("results") or {}).get("elastic")
            if isinstance(elastic, Mapping):
                cases.append((name, elastic))
        return cases
    elastic = result_map.get("elastic")
    if isinstance(elastic, Mapping):
        metadata = elastic.get("elastic_case")
        name = (
            str((metadata or {}).get("id") or "").strip()
            if isinstance(metadata, Mapping)
            else ""
        )
        cases.append((name or "Elastic", elastic))
    return cases


def _current_crack_criterion(
    results: Mapping,
    *,
    case_id: str,
    criterion_id: str,
    combination: str,
) -> tuple[dict, dict]:
    """Return one current criterion plus its verified immutable binding."""

    matches = [
        (name, elastic)
        for name, elastic in _elastic_cases(results)
        if name == case_id
    ]
    if len(matches) != 1:
        raise InteractionInputError(
            "the selected Elastic case must exist exactly once in the current "
            f"calculation; found {len(matches)} matches for {case_id!r}"
        )
    _name, elastic = matches[0]
    if not elastic.get("show_cw"):
        raise InteractionInputError(
            "the selected Elastic case has no current crack-width calculation"
        )
    assessment = elastic.get("crack_assessment")
    if not isinstance(assessment, Mapping):
        raise InteractionInputError(
            "the selected Elastic case has no structured crack assessment"
        )
    raw_criteria = assessment.get("criteria")
    if not isinstance(raw_criteria, Sequence) or isinstance(
        raw_criteria, (str, bytes)
    ):
        raise InteractionInputError(
            "current crack criteria are missing or malformed"
        )
    candidates = [
        item
        for item in raw_criteria
        if isinstance(item, Mapping)
        and str(item.get("criterion_id") or item.get("id") or "").strip()
        == criterion_id
    ]
    if len(candidates) != 1:
        raise InteractionInputError(
            "the selected crack criterion must exist exactly once in the "
            f"current case; found {len(candidates)} matches for {criterion_id!r}"
        )
    criterion = dict(candidates[0])
    current_combination = sls.canonical_combination(
        criterion.get("required_combination")
    )
    if current_combination != combination:
        raise InteractionInputError(
            "the selected interaction combination does not match the current "
            f"criterion ({combination!r} != {current_combination!r})"
        )
    if str(criterion.get("status") or "").upper() not in {"OK", "EXCEEDED"}:
        raise InteractionInputError(
            "the selected crack criterion has no current accepted response "
            "binding; its status is "
            f"{criterion.get('status') or 'missing'}"
        )
    responses = elastic.get("crack_responses")
    contexts = elastic.get("crack_response_contexts")
    scope = elastic.get("crack_response_mapping_scope")
    binding, issues = sls.validated_current_acceptance_evidence_binding(
        criterion,
        responses,
        response_contexts=contexts,
        response_mapping_scope=scope,
    )
    if issues or binding is None:
        raise InteractionInputError(
            "the selected crack criterion is not bound to current immutable "
            "response evidence: "
            + ("; ".join(issues) or "unknown binding error")
        )
    return criterion, binding


def _crack_basis(config: Mapping, results: Mapping) -> tuple[dict, dict, dict]:
    case_id = _required_text(
        config.get("crack_interaction_case_id"),
        "Elastic case identity",
    )
    criterion_id = _required_text(
        config.get("crack_interaction_criterion_id"),
        "crack criterion identity",
    )
    raw_combination = config.get("crack_interaction_combination")
    if not isinstance(raw_combination, str):
        raise InteractionInputError(
            "crack interaction combination must be a structured selection"
        )
    combination = sls.canonical_combination(raw_combination)
    if combination not in sls.SLS_COMBINATIONS[1:]:
        raise InteractionInputError(
            "crack interaction requires an explicit valid SLS combination"
        )
    criterion, binding = _current_crack_criterion(
        results,
        case_id=case_id,
        criterion_id=criterion_id,
        combination=combination,
    )
    limit = _real(
        (binding.get("criterion") or {}).get("limit_mm"),
        "current crack criterion limit",
        positive=True,
    )
    evidence = {
        "elastic_case": case_id,
        "criterion_id": criterion_id,
        "required_combination": combination,
        "response_duration": criterion.get("response_duration"),
        "limit_mm": limit,
        "acceptance_evidence": copy.deepcopy(binding),
        "acceptance_fingerprint": binding.get("fingerprint"),
    }
    return criterion, binding, evidence


def _crack_selected_edition_matches(
    method: str,
    inp: Mapping,
) -> tuple[bool, str]:
    selected_code = str(inp.get("sls_code") or "").strip()
    selected_edition = str(inp.get("sls_edition") or "").strip()
    if method == CRACK_METHOD_DK_2004:
        direct_dk = (
            selected_code == CRACK_CODE_DK_2004
            and selected_edition == "2004"
        )
        bridge_dk = (
            selected_code == danish_bridge.METHODOLOGY
            and selected_edition == sls.EDITION_BRIDGE_DK_2015
        )
        matches = direct_dk or bridge_dk
        return matches, (
            "the DK inclined-crack method requires the DS/EN 1992-1-1 "
            "+ DK NA code/edition pair (or its exact Danish bridge referral)"
        )
    if method == CRACK_METHOD_EN_2023:
        return (
            selected_code == CRACK_CODE_EN_2023
            and selected_edition == "2023"
        ), (
            "the Annex G.5 method requires the explicit EN 1992-1-1:2023 "
            "crack code/edition pair"
        )
    return True, ""


def assess_crack_interaction(
    inp: Mapping,
    results: Mapping,
) -> dict:
    """Assess the separately selected multidirectional crack method."""

    config = crack_configuration(inp)
    method = config.get("crack_interaction_method")
    rejected = _rejected_input_keys(inp, CRACK_INPUT_KEYS)
    if rejected:
        return _invalid(
            "crack",
            config,
            str(method or ""),
            "the live input boundary rejected multidirectional crack fields "
            f"({', '.join(rejected)}); explicitly repair them before calculation",
        )
    if not isinstance(config.get("crack_interaction_on"), bool):
        return _invalid(
            "crack",
            config,
            str(method or ""),
            "crack interaction enablement must be an explicit Boolean selection",
        )
    if not config["crack_interaction_on"]:
        return _not_assessed(
            "crack",
            config,
            str(method or CRACK_METHOD_NONE),
            "Multidirectional crack interaction is not selected; canonical "
            "one-direction crack results are retained.",
        )
    if not isinstance(method, str):
        return _invalid(
            "crack",
            config,
            str(method or ""),
            "crack interaction method must be a structured text selection",
        )
    if method not in CRACK_METHODS or method == CRACK_METHOD_NONE:
        return _not_assessed(
            "crack",
            config,
            str(method or CRACK_METHOD_NONE),
            "No supported crack-interaction methodology is selected.",
        )
    try:
        axes = _axes(config, "crack_interaction")
        _criterion, _binding, criterion_evidence = _crack_basis(
            config, results
        )
        edition_matches, edition_reason = _crack_selected_edition_matches(
            method, inp
        )
        if not edition_matches:
            return _not_assessed(
                "crack",
                config,
                method,
                edition_reason,
            )

        record = _result_base("crack", config, method)
        record.update(
            axes=axes,
            criterion=criterion_evidence,
            selected_crack_code=str(inp.get("sls_code") or ""),
            selected_crack_edition=str(inp.get("sls_edition") or ""),
        )

        if method == CRACK_METHOD_DK_2004:
            domain, missing = _domain(config, (
                (
                    "crack_interaction_orthogonal",
                    "reinforcement is provided in two orthogonal directions",
                ),
                (
                    "crack_interaction_plane_stress",
                    "the assessed point is in a plane-stress state",
                ),
                (
                    "crack_interaction_no_discontinuity",
                    "no unmodelled discontinuity affects the assessed region",
                ),
            ))
            angle = _real(
                config.get("crack_interaction_angle_deg"),
                "inclined-crack angle",
            )
            if not (15.0 < angle < 90.0):
                missing.append(
                    "the principal-tensile-stress angle must be greater than "
                    "15 degrees and less than 90 degrees"
                )
            if missing:
                return _not_assessed(
                    "crack",
                    config,
                    method,
                    "The DK inclined-crack method is outside or missing its "
                    "stated applicability domain: " + "; ".join(missing) + ".",
                    issues=missing,
                )
            sx = _real(
                config.get("crack_interaction_spacing_x_mm"),
                "x-direction crack spacing",
                positive=True,
            )
            sy = _real(
                config.get("crack_interaction_spacing_y_mm"),
                "y-direction crack spacing",
                positive=True,
            )
            ex = _real(
                config.get("crack_interaction_strain_x"),
                "x-direction strain-difference term",
                nonnegative=True,
            )
            ey = _real(
                config.get("crack_interaction_strain_y"),
                "y-direction strain-difference term",
                nonnegative=True,
            )
            theta = math.radians(angle)
            term_x = math.cos(theta) / sx
            term_y = math.sin(theta) / sy
            spacing = 1.0 / (term_x + term_y)
            strain = ex + ey
            width = spacing * strain
            limit = criterion_evidence["limit_mm"]
            utilisation = width / limit
            passed = utilisation <= 1.0 + _PASS_TOLERANCE
            record.update(
                source=CRACK_SOURCE_DK_2004,
                authority="Normative Eurocode plus Danish National Annex",
                domain={"checks": domain, "satisfied": True},
                angle={
                    "value_deg": angle,
                    "definition": (
                        "from the x reinforcement direction to the principal "
                        "tensile-stress direction"
                    ),
                },
                formula=(
                    "1/sr = cos(theta)/sr,x + sin(theta)/sr,y; "
                    "delta_epsilon = delta_epsilon_x + delta_epsilon_y; "
                    "wk = sr*delta_epsilon"
                ),
                parameters={
                    "spacing_x_mm": sx,
                    "spacing_y_mm": sy,
                    "strain_x": ex,
                    "strain_y": ey,
                    "combined_spacing_mm": spacing,
                    "combined_strain": strain,
                    "crack_width_mm": width,
                    "limit_mm": limit,
                },
                components=[
                    {
                        "id": "x",
                        "axis": axes["x"],
                        "spacing_mm": sx,
                        "strain_term": ex,
                    },
                    {
                        "id": "y",
                        "axis": axes["y"],
                        "spacing_mm": sy,
                        "strain_term": ey,
                    },
                ],
                terms=[
                    {"id": "spacing-x", "value_per_mm": term_x},
                    {"id": "spacing-y", "value_per_mm": term_y},
                    {"id": "strain-x", "value": ex},
                    {"id": "strain-y", "value": ey},
                ],
                interaction_assessed=True,
                status="PASS" if passed else "FAIL",
                verdict="PASS" if passed else "FAIL",
                utilisation=utilisation,
                reason=(
                    "The selected DK inclined-crack interaction is within "
                    "its confirmed domain."
                ),
            )
            return _seal_result(record)

        if method == CRACK_METHOD_EN_2023:
            domain, missing = _domain(config, (
                (
                    "crack_interaction_orthogonal",
                    "reinforcement is provided in two orthogonal directions",
                ),
                (
                    "crack_interaction_membrane",
                    "the assessed region is a membrane element",
                ),
                (
                    "crack_interaction_no_discontinuity",
                    "the assessed membrane region has no discontinuity",
                ),
            ))
            angle = _real(
                config.get("crack_interaction_angle_deg"),
                "principal-compressive-strain angle",
            )
            if not (15.0 < angle < 75.0):
                missing.append(
                    "the principal-compressive-strain angle must be greater "
                    "than 15 degrees and less than 75 degrees"
                )
            if missing:
                return _not_assessed(
                    "crack",
                    config,
                    method,
                    "The Annex G.5 method is outside or missing its stated "
                    "applicability domain: " + "; ".join(missing) + ".",
                    issues=missing,
                )
            sx = _real(
                config.get("crack_interaction_spacing_x_mm"),
                "x-direction mean crack spacing",
                positive=True,
            )
            sy = _real(
                config.get("crack_interaction_spacing_y_mm"),
                "y-direction mean crack spacing",
                positive=True,
            )
            ex = _real(
                config.get("crack_interaction_strain_x"),
                "x-direction strain-difference term",
                nonnegative=True,
            )
            ey = _real(
                config.get("crack_interaction_strain_y"),
                "y-direction strain-difference term",
                nonnegative=True,
            )
            e2 = _real(
                config.get("crack_interaction_transverse_strain"),
                "absolute transverse strain term",
            )
            theta = math.radians(angle)
            term_x = math.sin(theta) / sx
            term_y = math.cos(theta) / sy
            spacing = 1.0 / (term_x + term_y)
            strain = ex + ey + abs(e2)
            width = spacing * strain
            limit = criterion_evidence["limit_mm"]
            utilisation = width / limit
            passed = utilisation <= 1.0 + _PASS_TOLERANCE
            record.update(
                source=CRACK_SOURCE_EN_2023,
                authority="Normative Eurocode; no Danish NA inferred",
                domain={"checks": domain, "satisfied": True},
                angle={
                    "value_deg": angle,
                    "definition": (
                        "between the principal compressive-strain axis and "
                        "the x reinforcement direction"
                    ),
                },
                formula=(
                    "1/sr = sin(theta)/sr,x + cos(theta)/sr,y; "
                    "delta_epsilon = delta_epsilon_x + delta_epsilon_y "
                    "+ abs(epsilon_2); wk = sr*delta_epsilon"
                ),
                parameters={
                    "spacing_x_mm": sx,
                    "spacing_y_mm": sy,
                    "strain_x": ex,
                    "strain_y": ey,
                    "absolute_transverse_strain": abs(e2),
                    "combined_spacing_mm": spacing,
                    "combined_strain": strain,
                    "crack_width_mm": width,
                    "limit_mm": limit,
                },
                components=[
                    {
                        "id": "x",
                        "axis": axes["x"],
                        "spacing_mm": sx,
                        "strain_term": ex,
                    },
                    {
                        "id": "y",
                        "axis": axes["y"],
                        "spacing_mm": sy,
                        "strain_term": ey,
                    },
                ],
                terms=[
                    {"id": "spacing-x", "value_per_mm": term_x},
                    {"id": "spacing-y", "value_per_mm": term_y},
                    {"id": "strain-x", "value": ex},
                    {"id": "strain-y", "value": ey},
                    {"id": "strain-transverse", "value": abs(e2)},
                ],
                interaction_assessed=True,
                status="PASS" if passed else "FAIL",
                verdict="PASS" if passed else "FAIL",
                utilisation=utilisation,
                reason=(
                    "The selected EN 1992-1-1:2023 Annex G.5 interaction "
                    "is within its confirmed domain."
                ),
            )
            return _seal_result(record)

        domain, missing = _domain(config, ((
            "crack_interaction_domain_confirmed",
            "the approved project crack-interaction domain is confirmed",
        ),))
        if missing:
            return _not_assessed(
                "crack",
                config,
                method,
                "The approved project crack method has no confirmed domain.",
                issues=missing,
            )
        source = _required_text(
            config.get("crack_interaction_source"),
            "project crack-interaction source",
        )
        approval = _required_text(
            config.get("crack_interaction_approval"),
            "project crack-interaction approval",
        )
        width_x = _real(
            config.get("crack_interaction_component_x_mm"),
            "x-direction crack width",
            nonnegative=True,
        )
        width_y = _real(
            config.get("crack_interaction_component_y_mm"),
            "y-direction crack width",
            nonnegative=True,
        )
        limit_x = _real(
            config.get("crack_interaction_limit_x_mm"),
            "x-direction crack-width limit",
            positive=True,
        )
        limit_y = _real(
            config.get("crack_interaction_limit_y_mm"),
            "y-direction crack-width limit",
            positive=True,
        )
        exponent = _real(
            config.get("crack_interaction_exponent"),
            "project crack-interaction exponent",
            positive=True,
        )
        (
            term_x,
            term_y,
            utilisation,
            bounded_x,
            bounded_y,
            calculation_saturated,
        ) = _bounded_power_sum(
            width_x,
            limit_x,
            width_y,
            limit_y,
            exponent,
        )
        passed = utilisation <= 1.0 + _PASS_TOLERANCE
        record.update(
            source=source,
            approval=approval,
            authority="Approved project-defined methodology",
            domain={"checks": domain, "satisfied": True},
            formula=(
                "eta = (wk,x/wlim,x)^p + (wk,y/wlim,y)^p"
            ),
            parameters={
                "exponent": exponent,
                "limit_x_mm": limit_x,
                "limit_y_mm": limit_y,
            },
            components=[
                {
                    "id": "x",
                    "axis": axes["x"],
                    "crack_width_mm": width_x,
                    "limit_mm": limit_x,
                },
                {
                    "id": "y",
                    "axis": axes["y"],
                    "crack_width_mm": width_y,
                    "limit_mm": limit_y,
                },
            ],
            terms=[
                {"id": "x", "value": term_x, "bounded": bounded_x},
                {"id": "y", "value": term_y, "bounded": bounded_y},
            ],
            calculation_saturated=calculation_saturated,
            rotationally_invariant=bool(
                _close(exponent, 2.0) and _close(limit_x, limit_y)
            ),
            interaction_assessed=True,
            status="PASS" if passed else "FAIL",
            verdict=(
                "APPROVED CUSTOM PASS"
                if passed
                else "APPROVED CUSTOM FAIL"
            ),
            qualification="APPROVED CUSTOM",
            utilisation=utilisation,
            reason=(
                "The selected project-defined crack interaction is within "
                "its confirmed approved domain."
                + (
                    " Its utilisation exceeds the finite calculation range; "
                    "the reported value is a conservative finite lower bound."
                    if calculation_saturated
                    else ""
                )
            ),
        )
        return _seal_result(record)
    except (InteractionInputError, TypeError, ValueError) as exc:
        return _invalid("crack", config, str(method or ""), exc)


def _component_resistance(
    direction: Mapping,
    component: str,
) -> dict:
    if not isinstance(direction, Mapping):
        raise InteractionInputError(
            f"current {component} shear result is missing or malformed"
        )
    status = str(direction.get("status") or "").upper()
    if status not in {"PASS", "FAIL"}:
        raise InteractionInputError(
            f"current {component} shear result has no assessable component "
            f"verdict ({status or 'missing'})"
        )
    if direction.get("component") != component:
        raise InteractionInputError(
            f"current {component} shear result has a missing or contradictory "
            "component identity"
        )
    demand = _real(
        direction.get("v_ed"),
        f"{component} demand",
        nonnegative=True,
    )
    width = _real(
        direction.get("bw"),
        f"{component} effective width",
        positive=True,
    )
    depth = _real(
        direction.get("d"),
        f"{component} effective depth",
        positive=True,
    )
    links = direction.get("links")
    if links is not None:
        if not isinstance(links, Mapping):
            raise InteractionInputError(
                f"current {component} link result is malformed"
            )
        resistance_data = links.get("res")
        if not isinstance(resistance_data, Mapping) or not resistance_data.get(
            "valid"
        ):
            raise InteractionInputError(
                f"current {component} link resistance is invalid"
            )
        if not links.get("code_applicable", True):
            raise InteractionInputError(
                f"current {component} link result is outside its code domain"
            )
        resistance = _real(
            resistance_data.get("vrd"),
            f"{component} governing shear resistance",
            positive=True,
        )
        visible_utilisation = links.get("util")
        resistance_kind = "VRd = min(VRd,s, VRd,max)"
    else:
        resistance_data = direction.get("res")
        if not isinstance(resistance_data, Mapping) or not resistance_data.get(
            "valid"
        ):
            raise InteractionInputError(
                f"current {component} concrete shear resistance is invalid"
            )
        resistance = _real(
            resistance_data.get("vrd_c"),
            f"{component} concrete shear resistance",
            positive=True,
        )
        visible_utilisation = direction.get("util")
        resistance_kind = "VRd,c"
    expected_utilisation = demand / resistance
    if not _close(visible_utilisation, expected_utilisation):
        raise InteractionInputError(
            f"current {component} demand, resistance, and utilisation are "
            "internally inconsistent"
        )
    expected_status = (
        "PASS"
        if expected_utilisation <= 1.0 + _PASS_TOLERANCE
        else "FAIL"
    )
    if status != expected_status:
        raise InteractionInputError(
            f"current {component} component verdict contradicts its "
            "utilisation"
        )
    signed = direction.get("signed_v_ed", demand)
    signed_demand = _real(signed, f"{component} signed demand")
    if not _close(abs(signed_demand), demand):
        raise InteractionInputError(
            f"current {component} signed and absolute demands conflict"
        )
    return {
        "id": component,
        "axis": _required_text(
            direction.get("axis"),
            f"{component} component axis",
        ),
        "signed_demand_kn": signed_demand,
        "demand_kn": demand,
        "resistance_kn": resistance,
        "resistance_kind": resistance_kind,
        "utilisation": expected_utilisation,
        "width_mm": width,
        "depth_mm": depth,
        "status": status,
        "method": _required_text(
            direction.get("method"),
            f"{component} component method",
        ),
        "governing_face": direction.get("governing_face"),
    }


def _current_shear_components(case_results: Mapping) -> list[dict]:
    shear = case_results.get("shear")
    if not isinstance(shear, Mapping):
        return []
    raw_directions = shear.get("directions")
    if raw_directions is None:
        return []
    if not isinstance(raw_directions, Mapping):
        raise InteractionInputError(
            "current directional shear evidence is not a mapping"
        )
    unexpected = set(raw_directions) - {"vx", "vy"}
    if unexpected:
        raise InteractionInputError(
            "current directional shear evidence contains unknown component "
            f"identities: {', '.join(sorted(map(str, unexpected)))}"
        )
    return [
        _component_resistance(raw_directions[component], component)
        for component in ("vx", "vy")
        if component in raw_directions
    ]


def _effective_depth(
    qx: float,
    qy: float,
    dx: float,
    dy: float,
    route: str,
) -> tuple[float, float, str]:
    angle = math.degrees(math.atan2(qy, qx))
    if route == DEPTH_ROUTE_ROTATED:
        radians = math.radians(angle)
        depth = dx * math.cos(radians) ** 2 + dy * math.sin(radians) ** 2
        return depth, angle, "Formula (8.25)"
    if route != DEPTH_ROUTE_PIECEWISE:
        raise InteractionInputError(
            "effective-depth route is missing or not supported"
        )
    ratio = math.inf if qx <= 0.0 and qy > 0.0 else (
        0.0 if qx <= 0.0 else qy / qx
    )
    if ratio <= 0.5:
        return dx, angle, "Formula (8.22)"
    if ratio < 2.0:
        return 0.5 * (dx + dy), angle, "Formula (8.23)"
    return dy, angle, "Formula (8.24)"


def assess_shear_interaction(
    inp: Mapping,
    case_results: Mapping,
    *,
    case_id: str = "",
) -> dict:
    """Assess one Plastic/capacity case's selected biaxial shear method."""

    config = shear_configuration(inp)
    method = config.get("shear_interaction_method")
    rejected = _rejected_input_keys(inp, SHEAR_INPUT_KEYS)
    if rejected:
        return _invalid(
            "shear",
            config,
            str(method or ""),
            "the live input boundary rejected biaxial shear fields "
            f"({', '.join(rejected)}); explicitly repair them before calculation",
        )
    if not isinstance(config.get("shear_interaction_on"), bool):
        return _invalid(
            "shear",
            config,
            str(method or ""),
            "shear interaction enablement must be an explicit Boolean selection",
        )
    try:
        components = _current_shear_components(case_results)
    except (InteractionInputError, TypeError, ValueError) as exc:
        return _invalid("shear", config, str(method or ""), exc)
    if len(components) == 1:
        record = _not_applicable(
            "shear",
            config,
            str(method or SHEAR_METHOD_NONE),
            "Only one non-zero shear component is present; its independent "
            "component result is retained.",
        )
        record["components"] = copy.deepcopy(components)
        record["case_id"] = str(case_id or "")
        return _seal_result(record)
    if len(components) != 2 or {item["id"] for item in components} != {
        "vx",
        "vy",
    }:
        return _invalid(
            "shear",
            config,
            str(method or ""),
            "current shear component evidence is missing, duplicated, or "
            "does not prove a uniaxial state",
        )
    if not config["shear_interaction_on"]:
        record = _not_assessed(
            "shear",
            config,
            str(method or SHEAR_METHOD_NONE),
            "Independent Vx and Vy results are retained; no biaxial shear "
            "interaction methodology is selected.",
        )
        record["components"] = copy.deepcopy(components)
        record["case_id"] = str(case_id or "")
        return _seal_result(record)
    if not isinstance(method, str):
        record = _invalid(
            "shear",
            config,
            str(method or ""),
            "shear interaction method must be a structured text selection",
        )
        record["components"] = copy.deepcopy(components)
        record["case_id"] = str(case_id or "")
        return _seal_result(record)
    if method not in SHEAR_METHODS or method == SHEAR_METHOD_NONE:
        record = _not_assessed(
            "shear",
            config,
            str(method or SHEAR_METHOD_NONE),
            "No supported biaxial shear-interaction methodology is selected.",
        )
        record["components"] = copy.deepcopy(components)
        record["case_id"] = str(case_id or "")
        return _seal_result(record)
    try:
        axes = _axes(config, "shear_interaction")
        component_by_id = {item["id"]: item for item in components}
        vx = component_by_id["vx"]
        vy = component_by_id["vy"]
        record = _result_base("shear", config, method)
        record.update(
            case_id=str(case_id or ""),
            axes=axes,
            components=copy.deepcopy(components),
        )

        if method == SHEAR_METHOD_EN_2023:
            domain, missing = _domain(config, (
                (
                    "shear_interaction_planar_member",
                    "the member is a solid slab, shell, or other planar member",
                ),
                (
                    "shear_interaction_same_control_point",
                    "Vx and Vy refer to the same physical control point",
                ),
                (
                    "shear_interaction_per_unit_width",
                    "both components use a compatible per-unit-width basis",
                ),
                (
                    "shear_interaction_out_of_plane",
                    "both components are out-of-plane shear forces",
                ),
            ))
            selected_methods = {vx["method"], vy["method"]}
            if selected_methods != {SHEAR_CODE_EN_2023}:
                missing.append(
                    "both current directional resistances must use the explicit "
                    "DS/EN 1992-1-1:2023 shear method"
                )
            if missing:
                record.update(
                    domain={"checks": domain, "satisfied": False},
                    reason=(
                        "The EN 1992-1-1:2023 planar shear method is outside "
                        "or missing its stated domain: "
                        + "; ".join(missing)
                        + "."
                    ),
                    issues=missing,
                )
                return _seal_result(record)
            source = _required_text(
                config.get("shear_interaction_source"),
                "resultant-direction resistance source",
            )
            approval = _required_text(
                config.get("shear_interaction_approval"),
                "resultant-direction resistance approval",
            )
            resistance = _real(
                config.get(
                    "shear_interaction_resultant_resistance_kn_per_m"
                ),
                "resultant-direction resistance per unit width",
                positive=True,
            )
            qx = vx["demand_kn"] / (vx["width_mm"] / 1000.0)
            qy = vy["demand_kn"] / (vy["width_mm"] / 1000.0)
            resultant = math.hypot(qx, qy)
            route = config.get("shear_interaction_depth_route")
            if not isinstance(route, str):
                raise InteractionInputError(
                    "effective-depth route must be a structured selection"
                )
            depth, angle, depth_clause = _effective_depth(
                qx,
                qy,
                vx["depth_mm"],
                vy["depth_mm"],
                route,
            )
            utilisation = resultant / resistance
            passed = utilisation <= 1.0 + _PASS_TOLERANCE
            record.update(
                source=SHEAR_SOURCE_EN_2023,
                resistance_source=source,
                approval=approval,
                authority=(
                    "Normative Eurocode demand combination with externally "
                    "evidenced resultant-direction resistance"
                ),
                domain={"checks": domain, "satisfied": True},
                formula=(
                    "vEd = sqrt(vEd,x^2 + vEd,y^2); eta = vEd/vRd"
                ),
                parameters={
                    "demand_x_kn_per_m": qx,
                    "demand_y_kn_per_m": qy,
                    "resultant_demand_kn_per_m": resultant,
                    "resultant_resistance_kn_per_m": resistance,
                    "effective_depth_mm": depth,
                    "effective_depth_route": route,
                    "effective_depth_clause": depth_clause,
                    "principal_shear_angle_deg": angle,
                },
                terms=[
                    {"id": "x-squared", "value": qx ** 2},
                    {"id": "y-squared", "value": qy ** 2},
                ],
                demand_resultant_rotationally_invariant=True,
                rotationally_invariant=False,
                rotation_scope=SHEAR_EN_2023_ROTATION_SCOPE,
                interaction_assessed=True,
                status="PASS" if passed else "FAIL",
                verdict="QUALIFIED PASS" if passed else "QUALIFIED FAIL",
                qualification=(
                    "QUALIFIED - resultant-direction resistance supplied "
                    "with project source and approval"
                ),
                utilisation=utilisation,
                reason=(
                    "The selected planar resultant demand is within its "
                    "confirmed domain; the resistance conclusion remains "
                    "qualified because its resultant-direction resistance is "
                    "externally evidenced."
                ),
            )
            return _seal_result(record)

        domain, missing = _domain(config, ((
            "shear_interaction_domain_confirmed",
            "the approved project shear-interaction domain is confirmed",
        ),))
        if missing:
            record.update(
                domain={"checks": domain, "satisfied": False},
                reason=(
                    "The approved project shear method has no confirmed domain."
                ),
                issues=missing,
            )
            return _seal_result(record)
        source = _required_text(
            config.get("shear_interaction_source"),
            "project shear-interaction source",
        )
        approval = _required_text(
            config.get("shear_interaction_approval"),
            "project shear-interaction approval",
        )
        exponent = _real(
            config.get("shear_interaction_exponent"),
            "project shear-interaction exponent",
            positive=True,
        )
        (
            term_x,
            term_y,
            utilisation,
            bounded_x,
            bounded_y,
            calculation_saturated,
        ) = _bounded_power_sum(
            vx["demand_kn"],
            vx["resistance_kn"],
            vy["demand_kn"],
            vy["resistance_kn"],
            exponent,
        )
        passed = utilisation <= 1.0 + _PASS_TOLERANCE
        isotropic = bool(
            _close(exponent, 2.0)
            and _close(vx["resistance_kn"], vy["resistance_kn"])
        )
        record.update(
            source=source,
            approval=approval,
            authority="Approved project-defined methodology",
            domain={"checks": domain, "satisfied": True},
            formula=(
                "eta = (abs(Vx)/VRd,x)^p + (abs(Vy)/VRd,y)^p"
            ),
            parameters={"exponent": exponent},
            terms=[
                {"id": "vx", "value": term_x, "bounded": bounded_x},
                {"id": "vy", "value": term_y, "bounded": bounded_y},
            ],
            calculation_saturated=calculation_saturated,
            rotationally_invariant=isotropic,
            interaction_assessed=True,
            status="PASS" if passed else "FAIL",
            verdict=(
                "APPROVED CUSTOM PASS"
                if passed
                else "APPROVED CUSTOM FAIL"
            ),
            qualification="APPROVED CUSTOM",
            utilisation=utilisation,
            reason=(
                "The selected project-defined shear interaction is within "
                "its confirmed approved domain."
                + (
                    " Its utilisation exceeds the finite calculation range; "
                    "the reported value is a conservative finite lower bound."
                    if calculation_saturated
                    else ""
                )
            ),
        )
        return _seal_result(record)
    except (InteractionInputError, TypeError, ValueError) as exc:
        record = _invalid("shear", config, str(method or ""), exc)
        record["components"] = copy.deepcopy(components)
        record["case_id"] = str(case_id or "")
        return _seal_result(record)


def apply_to_results(inp: Mapping, results: Mapping) -> dict:
    """Attach crack and per-case shear interaction evidence to live results."""

    if not isinstance(results, dict):
        return results
    crack_result = assess_crack_interaction(inp, results)
    results["crack_interaction"] = crack_result
    elastic_entries = results.get("elastic_cases")
    if isinstance(elastic_entries, list):
        selected_case = _crack_case_identity(crack_result)
        for entry in elastic_entries:
            if not isinstance(entry, dict):
                continue
            elastic = (entry.get("results") or {}).get("elastic")
            if not isinstance(elastic, dict):
                continue
            elastic.pop("crack_interaction", None)
            if str(entry.get("name") or "") == selected_case:
                elastic["crack_interaction"] = copy.deepcopy(crack_result)
    elif isinstance(results.get("elastic"), dict):
        results["elastic"]["crack_interaction"] = copy.deepcopy(crack_result)

    shear_cases = []
    plastic_entries = results.get("plastic_cases")
    if isinstance(plastic_entries, list):
        for entry in plastic_entries:
            if not isinstance(entry, dict):
                continue
            case_results = entry.get("results")
            if not isinstance(case_results, dict):
                continue
            interaction = assess_shear_interaction(
                inp,
                case_results,
                case_id=str(entry.get("name") or ""),
            )
            shear = case_results.get("shear")
            if isinstance(shear, dict):
                _apply_shear_aggregate(interaction, shear)
            shear_cases.append({
                "case": str(entry.get("name") or ""),
                "interaction": interaction,
            })
        if plastic_entries:
            first_results = plastic_entries[0].get("results") or {}
            if isinstance(first_results.get("shear"), Mapping):
                results["shear"] = first_results["shear"]
    else:
        interaction = assess_shear_interaction(
            inp,
            results,
            case_id=str(
                ((inp.get("plastic_case") or {}).get("id") or "")
                if isinstance(inp.get("plastic_case"), Mapping)
                else ""
            ),
        )
        shear = results.get("shear")
        if isinstance(shear, dict):
            _apply_shear_aggregate(interaction, shear)
        shear_cases.append({
            "case": interaction.get("case_id") or "Plastic",
            "interaction": interaction,
        })
    results["shear_interactions"] = shear_cases
    return results


def _apply_shear_aggregate(interaction: Mapping, shear: dict) -> None:
    """Update one aggregate without erasing its directional component results."""

    shear["interaction"] = copy.deepcopy(dict(interaction))
    shear["interaction_assessed"] = bool(
        interaction.get("interaction_assessed")
    )
    shear["interaction_status"] = str(
        interaction.get("status") or ""
    )
    shear["interaction_verdict"] = str(
        interaction.get("verdict") or interaction.get("status") or ""
    )
    direction_statuses = [
        str((direction or {}).get("status") or "").upper()
        for direction in (shear.get("directions") or {}).values()
        if isinstance(direction, Mapping)
    ]
    interaction_status = str(interaction.get("status") or "").upper()
    qualification = interaction.get("qualification")
    if "INVALID" in direction_statuses or interaction_status == "INVALID":
        shear["status"] = "INVALID"
    elif "FAIL" in direction_statuses or interaction_status == "FAIL":
        shear["status"] = "FAIL"
    elif (
        interaction_status == "PASS"
        and interaction.get("interaction_assessed")
        and not qualification
        and direction_statuses
        and all(status == "PASS" for status in direction_statuses)
    ):
        shear["status"] = "PASS"
    elif shear.get("biaxial"):
        # Qualified/project results are valuable conclusions but do not become an
        # unqualified aggregate PASS in Sector's selected-standard status field.
        shear["status"] = "REVIEW"


def interaction_calculation_record(results: Mapping | None) -> dict | None:
    """Return the sealed multidirectional result bundle for project publication."""

    if not isinstance(results, Mapping):
        return None
    crack = results.get("crack_interaction")
    shear_cases = results.get("shear_interactions")
    evidence_seen = (
        isinstance(crack, Mapping)
        or isinstance(shear_cases, list)
    )
    representation_issues = []

    nested_crack_records = []
    elastic_entries = results.get("elastic_cases")
    if isinstance(elastic_entries, list):
        for entry in elastic_entries:
            if not isinstance(entry, Mapping):
                continue
            nested = (
                ((entry.get("results") or {}).get("elastic") or {}).get(
                    "crack_interaction"
                )
            )
            if isinstance(nested, Mapping):
                evidence_seen = True
                nested_crack_records.append((
                    str(entry.get("name") or ""),
                    nested,
                ))
    elif isinstance(results.get("elastic"), Mapping):
        nested = results["elastic"].get("crack_interaction")
        if isinstance(nested, Mapping):
            evidence_seen = True
            nested_crack_records.append((
                str(
                    ((results["elastic"].get("elastic_case") or {}).get("id"))
                    or ""
                ),
                nested,
            ))
    if nested_crack_records and not isinstance(crack, Mapping):
        representation_issues.append(
            "top-level crack interaction evidence is missing while "
            "Elastic-case evidence remains"
        )
    if isinstance(crack, Mapping):
        for case_name, nested in nested_crack_records:
            if dict(nested) != dict(crack):
                representation_issues.append(
                    "top-level and Elastic-case crack interaction evidence "
                    f"conflict for {case_name or 'the current case'}"
                )
        selected_case = _crack_case_identity(crack)
        if selected_case and (
            len(nested_crack_records) != 1
            or sum(
                case_name == selected_case
                for case_name, _nested in nested_crack_records
            ) != 1
        ):
            representation_issues.append(
                "the selected crack interaction is not represented exactly "
                f"once in Elastic case {selected_case}"
            )

    case_interactions = {}
    directional_shear_cases = []
    if isinstance(shear_cases, list):
        for item in shear_cases:
            if not isinstance(item, Mapping):
                continue
            case_name = item.get("case")
            interaction = item.get("interaction")
            if isinstance(case_name, str) and isinstance(
                interaction, Mapping
            ):
                case_interactions.setdefault(case_name, []).append(interaction)
    nested_shear_records = []
    plastic_entries = results.get("plastic_cases")
    if isinstance(plastic_entries, list):
        for entry in plastic_entries:
            if not isinstance(entry, Mapping):
                continue
            case_name = str(entry.get("name") or "")
            case_results = entry.get("results")
            if isinstance(case_results, Mapping):
                try:
                    directional_shear_cases.append(
                        _seal_directional_shear_case(
                            case_name,
                            _current_shear_components(case_results),
                        )
                    )
                except (InteractionInputError, TypeError, ValueError) as exc:
                    representation_issues.append(
                        "current directional shear evidence cannot be sealed "
                        f"for {case_name or 'an unnamed case'}: {exc}"
                    )
            shear = (case_results or {}).get("shear")
            if not isinstance(shear, Mapping):
                continue
            nested = shear.get("interaction")
            if isinstance(nested, Mapping):
                evidence_seen = True
                nested_shear_records.append((case_name, nested))
            matches = case_interactions.get(case_name, [])
            if len(matches) != 1:
                representation_issues.append(
                    "Plastic-case shear interaction is not represented exactly "
                    f"once for {case_name or 'an unnamed case'}"
                )
            elif not isinstance(nested, Mapping) or dict(nested) != dict(
                matches[0]
            ):
                representation_issues.append(
                    "top-level and Plastic-case shear interaction evidence "
                    f"conflict for {case_name or 'an unnamed case'}"
                )
    elif isinstance(results.get("shear"), Mapping):
        nested = results["shear"].get("interaction")
        basis_case_name = str(
            ((nested or {}).get("case_id") or "")
            if isinstance(nested, Mapping)
            else ""
        ) or "Plastic"
        try:
            directional_shear_cases.append(
                _seal_directional_shear_case(
                    basis_case_name,
                    _current_shear_components(results),
                )
            )
        except (InteractionInputError, TypeError, ValueError) as exc:
            representation_issues.append(
                "current directional shear evidence cannot be sealed for "
                f"{basis_case_name}: {exc}"
            )
        if isinstance(nested, Mapping):
            evidence_seen = True
            nested_shear_records.append((
                basis_case_name,
                nested,
            ))
        matches = [
            item
            for values in case_interactions.values()
            for item in values
        ]
        if len(matches) != 1:
            representation_issues.append(
                "the current shear interaction is not represented exactly "
                "once in the calculation bundle"
            )
        elif not isinstance(nested, Mapping) or dict(nested) != dict(matches[0]):
            representation_issues.append(
                "top-level and current-case shear interaction evidence conflict"
            )
    elif isinstance(shear_cases, list):
        for item in shear_cases:
            if not isinstance(item, Mapping):
                continue
            case_name = str(item.get("case") or "Plastic")
            try:
                directional_shear_cases.append(
                    _seal_directional_shear_case(
                        case_name,
                        _current_shear_components(results),
                    )
                )
            except (InteractionInputError, TypeError, ValueError) as exc:
                representation_issues.append(
                    "current directional shear evidence cannot be sealed for "
                    f"{case_name}: {exc}"
                )

    if not evidence_seen:
        return None

    bundle_crack = (
        crack
        if isinstance(crack, Mapping)
        else (
            nested_crack_records[0][1]
            if nested_crack_records
            else None
        )
    )
    if isinstance(bundle_crack, Mapping):
        stored_config = bundle_crack.get("configuration")
        if isinstance(stored_config, Mapping):
            reassessment_inputs = dict(stored_config)
            reassessment_inputs["sls_code"] = str(
                bundle_crack.get("selected_crack_code") or ""
            )
            reassessment_inputs["sls_edition"] = str(
                bundle_crack.get("selected_crack_edition") or ""
            )
            reassessed_crack = assess_crack_interaction(
                reassessment_inputs,
                results,
            )
            if dict(reassessed_crack) != dict(bundle_crack):
                representation_issues.append(
                    "crack interaction evidence does not match the current "
                    "canonical crack results"
                )
        else:
            representation_issues.append(
                "crack interaction has no reassessable configuration"
            )
    bundle_shear_cases = (
        shear_cases
        if isinstance(shear_cases, list)
        else [
            {
                "case": case_name or "Plastic",
                "interaction": interaction,
            }
            for case_name, interaction in nested_shear_records
        ]
    )
    for case_name, nested in nested_shear_records:
        case_results = None
        if isinstance(plastic_entries, list):
            matching_results = [
                entry.get("results")
                for entry in plastic_entries
                if isinstance(entry, Mapping)
                and str(entry.get("name") or "") == case_name
                and isinstance(entry.get("results"), Mapping)
            ]
            if len(matching_results) == 1:
                case_results = matching_results[0]
        elif isinstance(results.get("shear"), Mapping):
            case_results = results
        stored_config = nested.get("configuration")
        if (
            isinstance(case_results, Mapping)
            and isinstance(stored_config, Mapping)
        ):
            reassessed_shear = assess_shear_interaction(
                stored_config,
                case_results,
                case_id=str(nested.get("case_id") or ""),
            )
            if dict(reassessed_shear) != dict(nested):
                representation_issues.append(
                    "shear interaction evidence does not match current "
                    f"directional results for {case_name or 'an unnamed case'}"
                )
        else:
            representation_issues.append(
                "shear interaction cannot be reassessed against exactly one "
                f"current case for {case_name or 'an unnamed case'}"
            )
    bundle = {
        "schema": INTERACTION_BUNDLE_SCHEMA,
        "crack": (
            copy.deepcopy(dict(bundle_crack))
            if isinstance(bundle_crack, Mapping)
            else None
        ),
        "shear_cases": copy.deepcopy(
            bundle_shear_cases
        ),
        "directional_shear_cases": copy.deepcopy(
            directional_shear_cases
        ),
    }
    if representation_issues:
        bundle["representation_issues"] = list(
            dict.fromkeys(representation_issues)
        )
    bundle["fingerprint"] = _fingerprint(bundle)
    return bundle


def _semantic_number(value) -> float | None:
    if _is_boolean(value) or not isinstance(value, Real):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _shear_component_semantic_issues(
    components,
    label: str,
) -> list[str]:
    """Validate retained directional evidence for every aggregate status."""

    if not isinstance(components, list):
        return [f"{label} component evidence is not a list"]
    if not components:
        return []
    issues = []
    identities = [
        component.get("id")
        for component in components
        if isinstance(component, Mapping)
    ]
    if (
        len(identities) != len(components)
        or any(
            not isinstance(identity, str)
            or identity not in {"vx", "vy"}
            for identity in identities
        )
        or len(identities) != len(set(identities))
    ):
        issues.append(
            f"{label} retained shear component identities are malformed, "
            "duplicated, or unsupported"
        )
    component_axes = []
    for component in components:
        if not isinstance(component, Mapping):
            continue
        component_id = str(component.get("id") or "unknown")
        demand = _semantic_number(component.get("demand_kn"))
        resistance = _semantic_number(component.get("resistance_kn"))
        signed_demand = _semantic_number(
            component.get("signed_demand_kn")
        )
        visible_utilisation = _semantic_number(
            component.get("utilisation")
        )
        width = _semantic_number(component.get("width_mm"))
        depth = _semantic_number(component.get("depth_mm"))
        axis = component.get("axis")
        method_identity = component.get("method")
        resistance_kind = component.get("resistance_kind")
        expected_axis = {"vx": "y", "vy": "x"}.get(component_id)
        if (
            demand is None
            or demand < 0.0
            or resistance is None
            or resistance <= 0.0
            or signed_demand is None
            or visible_utilisation is None
            or visible_utilisation < 0.0
            or width is None
            or width <= 0.0
            or depth is None
            or depth <= 0.0
            or not isinstance(axis, str)
            or not axis.strip()
            or axis.strip().casefold() != expected_axis
            or not isinstance(method_identity, str)
            or not method_identity.strip()
            or not isinstance(resistance_kind, str)
            or not resistance_kind.strip()
        ):
            issues.append(
                f"{label} {component_id} component evidence is malformed"
            )
            continue
        component_axes.append(axis.strip().casefold())
        expected_utilisation = demand / resistance
        expected_status = (
            "PASS"
            if expected_utilisation <= 1.0 + _PASS_TOLERANCE
            else "FAIL"
        )
        if (
            not _close(visible_utilisation, expected_utilisation)
            or not _close(abs(signed_demand), demand)
            or str(component.get("status") or "").upper()
            != expected_status
        ):
            issues.append(
                f"{label} {component_id} component demand, resistance, sign, "
                "utilisation, or verdict is contradictory"
            )
    if (
        len(component_axes) == len(components)
        and len(component_axes) == 2
        and len(set(component_axes)) != 2
    ):
        issues.append(
            f"{label} directional component axes are not distinct"
        )
    return issues


def _directional_shear_case_issues(
    record,
    label: str,
) -> list[str]:
    """Validate separately sealed current directional case evidence."""

    if not isinstance(record, Mapping):
        return [f"{label} is missing or malformed"]
    issues = []
    if record.get("schema") != DIRECTIONAL_SHEAR_CASE_SCHEMA:
        issues.append(f"{label} has an unknown schema")
    case_id = record.get("case")
    if not isinstance(case_id, str) or not case_id.strip():
        issues.append(f"{label} has no case identity")
    fingerprint = record.get("fingerprint")
    body = copy.deepcopy(dict(record))
    body.pop("fingerprint", None)
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        issues.append(f"{label} has an invalid fingerprint")
    else:
        try:
            expected = _fingerprint(body)
        except (TypeError, ValueError):
            expected = None
            issues.append(f"{label} contains non-canonical evidence")
        if expected is not None and fingerprint != expected:
            issues.append(f"{label} fingerprint does not match its body")
    issues.extend(
        _shear_component_semantic_issues(
            record.get("components"),
            label,
        )
    )
    return issues


def _record_semantic_issues(record: Mapping, label: str) -> list[str]:
    """Reject a re-sealed record that contradicts its own bound evidence."""

    issues = []
    kind = record.get("kind")
    if kind not in {"crack", "shear"}:
        return [f"{label} has an unknown interaction kind"]
    config = record.get("configuration")
    if not isinstance(config, Mapping):
        return [f"{label} has no complete configuration snapshot"]
    prefix = f"{kind}_interaction"
    on_key = f"{prefix}_on"
    method_key = f"{prefix}_method"
    expected_enabled = config.get(on_key)
    if not isinstance(expected_enabled, bool):
        issues.append(
            f"{label} configuration has malformed enablement evidence"
        )
    if (
        not isinstance(record.get("enabled"), bool)
        or record.get("enabled") is not expected_enabled
    ):
        issues.append(
            f"{label} enablement contradicts its configuration"
        )
    expected_method = config.get(method_key)
    if record.get("method") != expected_method:
        issues.append(f"{label} method contradicts its configuration")
    labels = (
        CRACK_METHOD_LABELS if kind == "crack" else SHEAR_METHOD_LABELS
    )
    if record.get("method_name") != labels.get(
        record.get("method"),
        str(record.get("method") or ""),
    ):
        issues.append(f"{label} method name contradicts its method identity")

    components = record.get("components")
    component_by_id = {
        item.get("id"): item
        for item in components
        if isinstance(item, Mapping)
        and isinstance(item.get("id"), str)
    } if isinstance(components, list) else {}
    terms = record.get("terms")
    if not isinstance(terms, list):
        issues.append(f"{label} interaction terms are not a list")
        term_by_id = {}
    else:
        term_ids = [
            item.get("id")
            for item in terms
            if isinstance(item, Mapping)
        ]
        valid_term_ids = (
            len(term_ids) == len(terms)
            and all(
                isinstance(term_id, str) and term_id
                for term_id in term_ids
            )
        )
        if not valid_term_ids:
            issues.append(f"{label} contains a malformed interaction term")
        elif len(term_ids) != len(set(term_ids)):
            issues.append(f"{label} contains duplicate interaction terms")
        term_by_id = {
            item.get("id"): item
            for item in terms
            if isinstance(item, Mapping)
            and isinstance(item.get("id"), str)
        }

    status = str(record.get("status") or "").upper()
    assessed = record.get("interaction_assessed")
    if not isinstance(assessed, bool):
        issues.append(f"{label} has malformed assessment-state evidence")
    utilisation = _semantic_number(record.get("utilisation"))
    if status in {"PASS", "FAIL"}:
        if assessed is not True:
            issues.append(
                f"{label} claims {status} without an assessed interaction"
            )
        if utilisation is None or utilisation < 0.0:
            issues.append(
                f"{label} has no finite non-negative utilisation"
            )
        elif status == "PASS" and utilisation > 1.0 + _PASS_TOLERANCE:
            issues.append(
                f"{label} PASS contradicts its utilisation"
            )
        elif status == "FAIL" and utilisation <= 1.0 + _PASS_TOLERANCE:
            issues.append(
                f"{label} FAIL contradicts its utilisation"
            )
        if not str(record.get("verdict") or "").upper().endswith(status):
            issues.append(f"{label} verdict contradicts its status")
    else:
        expected_nonpass_state = {
            "NOT ASSESSED": (False, "REVIEW"),
            "INVALID": (False, "REVIEW"),
            "NOT APPLICABLE": (True, "NOT APPLICABLE"),
        }.get(status)
        if expected_nonpass_state is None:
            issues.append(f"{label} has an unsupported conclusion status")
        else:
            expected_assessed, expected_verdict = expected_nonpass_state
            if (
                assessed is not expected_assessed
                or str(record.get("verdict") or "").upper()
                != expected_verdict
            ):
                issues.append(
                    f"{label} non-pass assessment state or verdict is "
                    "contradictory"
                )
        if kind == "crack" and status == "NOT APPLICABLE":
            issues.append(
                f"{label} uses NOT APPLICABLE, which is not a valid crack-"
                "interaction disposition"
            )
        if record.get("utilisation") is not None:
            issues.append(
                f"{label} appears downgraded while retaining a calculated "
                "utilisation"
            )
        if terms:
            issues.append(
                f"{label} appears downgraded while retaining interaction terms"
            )
        retained_conclusion_fields = [
            key
            for key in (
                "angle",
                "approval",
                "authority",
                "calculation_saturated",
                "demand_resultant_rotationally_invariant",
                "formula",
                "parameters",
                "resistance_source",
                "rotation_scope",
                "rotationally_invariant",
                "source",
            )
            if record.get(key) not in (None, "", [], {})
        ]
        if record.get("qualification") not in (None, ""):
            retained_conclusion_fields.append("qualification")
        if retained_conclusion_fields:
            issues.append(
                f"{label} appears downgraded while retaining calculated "
                "conclusion fields: "
                + ", ".join(retained_conclusion_fields)
            )
        domain = record.get("domain")
        if domain is not None and (
            not isinstance(domain, Mapping)
            or not isinstance(domain.get("checks"), Mapping)
            or domain.get("satisfied") is not False
        ):
            issues.append(
                f"{label} non-pass domain evidence is malformed or claims "
                "a satisfied calculation domain"
            )
        raw_issues = record.get("issues")
        if (
            not isinstance(raw_issues, list)
            or any(not isinstance(issue, str) for issue in raw_issues)
            or not isinstance(record.get("reason"), str)
            or not record.get("reason").strip()
        ):
            issues.append(
                f"{label} non-pass reason or issue evidence is malformed"
            )
        if kind == "crack" and (
            components
            or any(
                record.get(key) not in (None, "", [], {})
                for key in (
                    "axes",
                    "criterion",
                    "selected_crack_code",
                    "selected_crack_edition",
                )
            )
        ):
            issues.append(
                f"{label} appears downgraded while retaining crack "
                "calculation evidence"
            )
        if (
            kind == "shear"
            and record.get("axes") is not None
            and record.get("axes")
            != {
                "x": config.get("shear_interaction_axis_x"),
                "y": config.get("shear_interaction_axis_y"),
            }
        ):
            issues.append(
                f"{label} retained shear axes contradict its configuration"
            )

    if kind == "shear" and components:
        issues.extend(_shear_component_semantic_issues(components, label))

    if status not in {"PASS", "FAIL"}:
        return issues

    expected_axes = {
        "x": config.get(f"{prefix}_axis_x"),
        "y": config.get(f"{prefix}_axis_y"),
    }
    if record.get("axes") != expected_axes:
        issues.append(f"{label} axes contradict its configuration")
    expected_component_ids = (
        {"x", "y"} if kind == "crack" else {"vx", "vy"}
    )
    if (
        not isinstance(components, list)
        or len(components) != 2
        or set(component_by_id) != expected_component_ids
    ):
        issues.append(
            f"{label} does not contain exactly the required component "
            "identities"
        )

    if kind == "crack":
        criterion = record.get("criterion")
        if not isinstance(criterion, Mapping):
            issues.append(f"{label} has no immutable crack criterion evidence")
        else:
            binding, binding_issues = (
                sls._validated_acceptance_evidence_binding(  # noqa: SLF001
                    criterion.get("acceptance_evidence")
                )
            )
            if binding_issues or binding is None:
                issues.append(
                    f"{label} has invalid immutable crack acceptance evidence: "
                    + "; ".join(binding_issues)
                )
            else:
                bound_criterion = binding.get("criterion") or {}
                if any((
                    criterion.get("elastic_case")
                    != config.get("crack_interaction_case_id"),
                    criterion.get("criterion_id")
                    != config.get("crack_interaction_criterion_id"),
                    criterion.get("required_combination")
                    != config.get("crack_interaction_combination"),
                    criterion.get("acceptance_fingerprint")
                    != binding.get("fingerprint"),
                    not _close(
                        criterion.get("limit_mm"),
                        bound_criterion.get("limit_mm"),
                    ),
                    bound_criterion.get("id")
                    != config.get("crack_interaction_criterion_id"),
                    bound_criterion.get("required_combination")
                    != config.get("crack_interaction_combination"),
                )):
                    issues.append(
                        f"{label} crack criterion contradicts its immutable "
                        "acceptance evidence or selected route"
                    )
    method = record.get("method")
    expected_utilisation = None
    if method == CRACK_METHOD_PROJECT:
        exponent = _semantic_number(
            config.get("crack_interaction_exponent")
        )
        width_x = _semantic_number(
            config.get("crack_interaction_component_x_mm")
        )
        width_y = _semantic_number(
            config.get("crack_interaction_component_y_mm")
        )
        limit_x = _semantic_number(
            config.get("crack_interaction_limit_x_mm")
        )
        limit_y = _semantic_number(
            config.get("crack_interaction_limit_y_mm")
        )
        if (
            exponent is not None
            and exponent > 0.0
            and width_x is not None
            and width_x >= 0.0
            and width_y is not None
            and width_y >= 0.0
            and limit_x is not None
            and limit_x > 0.0
            and limit_y is not None
            and limit_y > 0.0
        ):
            (
                expected_x,
                expected_y,
                expected_utilisation,
                expected_bounded_x,
                expected_bounded_y,
                expected_saturated,
            ) = _bounded_power_sum(
                width_x,
                limit_x,
                width_y,
                limit_y,
                exponent,
            )
            expected_terms = {"x": expected_x, "y": expected_y}
            expected_bounds = {
                "x": expected_bounded_x,
                "y": expected_bounded_y,
            }
            for term_id, expected in expected_terms.items():
                term = term_by_id.get(term_id) or {}
                if (
                    not _close(term.get("value"), expected)
                    or term.get("bounded") is not expected_bounds[term_id]
                ):
                    issues.append(
                        f"{label} {term_id} term contradicts current inputs"
                    )
            if (
                record.get("calculation_saturated")
                is not expected_saturated
            ):
                issues.append(
                    f"{label} finite-range marker contradicts current inputs"
                )
            expected_components = {
                "x": (width_x, limit_x),
                "y": (width_y, limit_y),
            }
            for component_id, (width, limit) in expected_components.items():
                component = component_by_id.get(component_id) or {}
                if (
                    not _close(component.get("crack_width_mm"), width)
                    or not _close(component.get("limit_mm"), limit)
                    or component.get("axis")
                    != expected_axes[component_id]
                ):
                    issues.append(
                        f"{label} {component_id} component contradicts "
                        "current inputs"
                    )
            if record.get("parameters") != {
                "exponent": exponent,
                "limit_x_mm": limit_x,
                "limit_y_mm": limit_y,
            }:
                issues.append(
                    f"{label} project crack parameters contradict current "
                    "inputs"
                )
            expected_rotation = bool(
                _close(exponent, 2.0) and _close(limit_x, limit_y)
            )
            if (
                record.get("rotationally_invariant")
                is not expected_rotation
            ):
                issues.append(
                    f"{label} rotation property contradicts current inputs"
                )
        if set(term_by_id) != {"x", "y"}:
            issues.append(
                f"{label} project crack term identities are incomplete"
            )
        if (
            record.get("formula")
            != "eta = (wk,x/wlim,x)^p + (wk,y/wlim,y)^p"
            or record.get("authority")
            != "Approved project-defined methodology"
            or record.get("domain")
            != {
                "checks": {
                    "the approved project crack-interaction domain is "
                    "confirmed": True,
                },
                "satisfied": True,
            }
        ):
            issues.append(
                f"{label} project crack formula, authority, or domain is "
                "contradictory"
            )
        if (
            record.get("source")
            != config.get("crack_interaction_source")
            or record.get("approval")
            != config.get("crack_interaction_approval")
            or record.get("qualification") != "APPROVED CUSTOM"
        ):
            issues.append(
                f"{label} project source, approval, or qualification "
                "contradicts its configuration"
            )
    elif method in {CRACK_METHOD_DK_2004, CRACK_METHOD_EN_2023}:
        parameters = record.get("parameters")
        criterion = record.get("criterion")
        limit = (
            _semantic_number(criterion.get("limit_mm"))
            if isinstance(criterion, Mapping)
            else None
        )
        angle = _semantic_number(
            config.get("crack_interaction_angle_deg")
        )
        spacing_x = _semantic_number(
            config.get("crack_interaction_spacing_x_mm")
        )
        spacing_y = _semantic_number(
            config.get("crack_interaction_spacing_y_mm")
        )
        strain_x = _semantic_number(
            config.get("crack_interaction_strain_x")
        )
        strain_y = _semantic_number(
            config.get("crack_interaction_strain_y")
        )
        if (
            angle is not None
            and spacing_x is not None
            and spacing_x > 0.0
            and spacing_y is not None
            and spacing_y > 0.0
            and strain_x is not None
            and strain_x >= 0.0
            and strain_y is not None
            and strain_y >= 0.0
            and limit is not None
            and limit > 0.0
        ):
            radians = math.radians(angle)
            if method == CRACK_METHOD_DK_2004:
                spacing_terms = {
                    "spacing-x": math.cos(radians) / spacing_x,
                    "spacing-y": math.sin(radians) / spacing_y,
                }
                transverse = 0.0
            else:
                spacing_terms = {
                    "spacing-x": math.sin(radians) / spacing_x,
                    "spacing-y": math.cos(radians) / spacing_y,
                }
                raw_transverse = _semantic_number(
                    config.get("crack_interaction_transverse_strain")
                )
                transverse = (
                    abs(raw_transverse)
                    if raw_transverse is not None
                    else None
                )
            if transverse is not None:
                combined_spacing = 1.0 / sum(spacing_terms.values())
                combined_strain = strain_x + strain_y + transverse
                expected_width = combined_spacing * combined_strain
                expected_utilisation = expected_width / limit
                expected_terms = {
                    **spacing_terms,
                    "strain-x": strain_x,
                    "strain-y": strain_y,
                }
                if method == CRACK_METHOD_EN_2023:
                    expected_terms["strain-transverse"] = transverse
                for term_id, expected in expected_terms.items():
                    term = term_by_id.get(term_id) or {}
                    value_key = (
                        "value_per_mm"
                        if term_id.startswith("spacing-")
                        else "value"
                    )
                    if not _close(term.get(value_key), expected):
                        issues.append(
                            f"{label} {term_id} term contradicts "
                            "current inputs"
                        )
                if not isinstance(parameters, Mapping) or any((
                    not _close(
                        parameters.get("combined_spacing_mm"),
                        combined_spacing,
                    ),
                    not _close(
                        parameters.get("combined_strain"),
                        combined_strain,
                    ),
                    not _close(
                        parameters.get("crack_width_mm"),
                        expected_width,
                    ),
                    not _close(parameters.get("limit_mm"), limit),
                )):
                    issues.append(
                        f"{label} calculated crack parameters contradict "
                        "current inputs"
                    )
        expected_source = (
            CRACK_SOURCE_DK_2004
            if method == CRACK_METHOD_DK_2004
            else CRACK_SOURCE_EN_2023
        )
        if record.get("source") != expected_source:
            issues.append(f"{label} standard source is contradictory")
        if record.get("qualification") is not None:
            issues.append(
                f"{label} standard result has an unexpected qualification"
            )
        if method == CRACK_METHOD_DK_2004:
            expected_formula = (
                "1/sr = cos(theta)/sr,x + sin(theta)/sr,y; "
                "delta_epsilon = delta_epsilon_x + delta_epsilon_y; "
                "wk = sr*delta_epsilon"
            )
            expected_authority = (
                "Normative Eurocode plus Danish National Annex"
            )
            expected_domain = {
                "checks": {
                    "reinforcement is provided in two orthogonal directions": (
                        True
                    ),
                    "the assessed point is in a plane-stress state": True,
                    "no unmodelled discontinuity affects the assessed region": (
                        True
                    ),
                },
                "satisfied": True,
            }
            expected_angle_definition = (
                "from the x reinforcement direction to the principal "
                "tensile-stress direction"
            )
            expected_term_ids = {
                "spacing-x",
                "spacing-y",
                "strain-x",
                "strain-y",
            }
        else:
            expected_formula = (
                "1/sr = sin(theta)/sr,x + cos(theta)/sr,y; "
                "delta_epsilon = delta_epsilon_x + delta_epsilon_y "
                "+ abs(epsilon_2); wk = sr*delta_epsilon"
            )
            expected_authority = (
                "Normative Eurocode; no Danish NA inferred"
            )
            expected_domain = {
                "checks": {
                    "reinforcement is provided in two orthogonal directions": (
                        True
                    ),
                    "the assessed region is a membrane element": True,
                    "the assessed membrane region has no discontinuity": True,
                },
                "satisfied": True,
            }
            expected_angle_definition = (
                "between the principal compressive-strain axis and the x "
                "reinforcement direction"
            )
            expected_term_ids = {
                "spacing-x",
                "spacing-y",
                "strain-x",
                "strain-y",
                "strain-transverse",
            }
        angle_record = record.get("angle")
        if (
            record.get("formula") != expected_formula
            or record.get("authority") != expected_authority
            or record.get("domain") != expected_domain
            or set(term_by_id) != expected_term_ids
            or not isinstance(angle_record, Mapping)
            or not _close(angle_record.get("value_deg"), angle)
            or angle_record.get("definition")
            != expected_angle_definition
        ):
            issues.append(
                f"{label} standard crack formula, authority, domain, angle, "
                "or terms are contradictory"
            )
        for component_id, spacing_value, strain_value in (
            ("x", spacing_x, strain_x),
            ("y", spacing_y, strain_y),
        ):
            component = component_by_id.get(component_id) or {}
            if (
                component.get("axis") != expected_axes[component_id]
                or not _close(component.get("spacing_mm"), spacing_value)
                or not _close(component.get("strain_term"), strain_value)
            ):
                issues.append(
                    f"{label} {component_id} standard crack component "
                    "contradicts current inputs"
                )
    elif method == SHEAR_METHOD_PROJECT:
        exponent = _semantic_number(
            config.get("shear_interaction_exponent")
        )
        expected_terms = {}
        expected_bounds = {}
        if exponent is not None and exponent > 0.0:
            usable = {}
            for component_id in ("vx", "vy"):
                component = component_by_id.get(component_id) or {}
                demand = _semantic_number(component.get("demand_kn"))
                resistance = _semantic_number(
                    component.get("resistance_kn")
                )
                if (
                    demand is None
                    or demand < 0.0
                    or resistance is None
                    or resistance <= 0.0
                ):
                    issues.append(
                        f"{label} {component_id} component is unusable"
                    )
                    continue
                usable[component_id] = (demand, resistance)
            if len(usable) == 2:
                (
                    expected_x,
                    expected_y,
                    expected_utilisation,
                    expected_bounded_x,
                    expected_bounded_y,
                    expected_saturated,
                ) = _bounded_power_sum(
                    usable["vx"][0],
                    usable["vx"][1],
                    usable["vy"][0],
                    usable["vy"][1],
                    exponent,
                )
                expected_terms = {"vx": expected_x, "vy": expected_y}
                expected_bounds = {
                    "vx": expected_bounded_x,
                    "vy": expected_bounded_y,
                }
                for component_id, expected in expected_terms.items():
                    term = term_by_id.get(component_id) or {}
                    if (
                        not _close(term.get("value"), expected)
                        or term.get("bounded")
                        is not expected_bounds[component_id]
                    ):
                        issues.append(
                            f"{label} {component_id} term contradicts "
                            "its component evidence"
                        )
                if (
                    record.get("calculation_saturated")
                    is not expected_saturated
                ):
                    issues.append(
                        f"{label} finite-range marker contradicts "
                        "component evidence"
                    )
                expected_rotation = bool(
                    _close(exponent, 2.0)
                    and _close(
                        usable["vx"][1],
                        usable["vy"][1],
                    )
                )
                if (
                    record.get("rotationally_invariant")
                    is not expected_rotation
                ):
                    issues.append(
                        f"{label} rotation property contradicts component "
                        "evidence"
                    )
            if record.get("parameters") != {"exponent": exponent}:
                issues.append(
                    f"{label} project shear parameters contradict current "
                    "inputs"
                )
        if set(term_by_id) != {"vx", "vy"}:
            issues.append(
                f"{label} project shear term identities are incomplete"
            )
        if (
            record.get("formula")
            != "eta = (abs(Vx)/VRd,x)^p + (abs(Vy)/VRd,y)^p"
            or record.get("authority")
            != "Approved project-defined methodology"
            or record.get("domain")
            != {
                "checks": {
                    "the approved project shear-interaction domain is "
                    "confirmed": True,
                },
                "satisfied": True,
            }
        ):
            issues.append(
                f"{label} project shear formula, authority, or domain is "
                "contradictory"
            )
        if (
            record.get("source")
            != config.get("shear_interaction_source")
            or record.get("approval")
            != config.get("shear_interaction_approval")
            or record.get("qualification") != "APPROVED CUSTOM"
        ):
            issues.append(
                f"{label} project source, approval, or qualification "
                "contradicts its configuration"
            )
    elif method == SHEAR_METHOD_EN_2023:
        parameters = record.get("parameters")
        resistance = _semantic_number(
            config.get(
                "shear_interaction_resultant_resistance_kn_per_m"
            )
        )
        vx = component_by_id.get("vx") or {}
        vy = component_by_id.get("vy") or {}
        demand_x = _semantic_number(vx.get("demand_kn"))
        demand_y = _semantic_number(vy.get("demand_kn"))
        width_x = _semantic_number(vx.get("width_mm"))
        width_y = _semantic_number(vy.get("width_mm"))
        depth_x = _semantic_number(vx.get("depth_mm"))
        depth_y = _semantic_number(vy.get("depth_mm"))
        if (
            resistance is not None
            and resistance > 0.0
            and demand_x is not None
            and demand_x >= 0.0
            and demand_y is not None
            and demand_y >= 0.0
            and width_x is not None
            and width_x > 0.0
            and width_y is not None
            and width_y > 0.0
            and depth_x is not None
            and depth_x > 0.0
            and depth_y is not None
            and depth_y > 0.0
        ):
            qx = demand_x / (width_x / 1000.0)
            qy = demand_y / (width_y / 1000.0)
            resultant = math.hypot(qx, qy)
            expected_utilisation = resultant / resistance
            route = config.get("shear_interaction_depth_route")
            try:
                depth, angle, clause = _effective_depth(
                    qx, qy, depth_x, depth_y, route
                )
            except InteractionInputError:
                depth = angle = clause = None
            expected_parameters = {
                "demand_x_kn_per_m": qx,
                "demand_y_kn_per_m": qy,
                "resultant_demand_kn_per_m": resultant,
                "resultant_resistance_kn_per_m": resistance,
                "effective_depth_mm": depth,
                "effective_depth_route": route,
                "effective_depth_clause": clause,
                "principal_shear_angle_deg": angle,
            }
            if not isinstance(parameters, Mapping) or any(
                (
                    parameters.get(key) != expected
                    if isinstance(expected, str)
                    else not _close(parameters.get(key), expected)
                )
                for key, expected in expected_parameters.items()
            ):
                issues.append(
                    f"{label} resultant parameters contradict component "
                    "evidence"
                )
            for term_id, expected in {
                "x-squared": qx ** 2,
                "y-squared": qy ** 2,
            }.items():
                if not _close(
                    (term_by_id.get(term_id) or {}).get("value"),
                    expected,
                ):
                    issues.append(
                        f"{label} {term_id} term contradicts component evidence"
                    )
        if (
            record.get("source") != SHEAR_SOURCE_EN_2023
            or record.get("resistance_source")
            != config.get("shear_interaction_source")
            or record.get("approval")
            != config.get("shear_interaction_approval")
            or not str(record.get("qualification") or "").startswith(
                "QUALIFIED"
            )
        ):
            issues.append(
                f"{label} source, approval, or qualification is contradictory"
            )
        if (
            record.get("formula")
            != "vEd = sqrt(vEd,x^2 + vEd,y^2); eta = vEd/vRd"
            or record.get("authority")
            != (
                "Normative Eurocode demand combination with externally "
                "evidenced resultant-direction resistance"
            )
            or record.get("domain")
            != {
                "checks": {
                    "the member is a solid slab, shell, or other planar "
                    "member": True,
                    "Vx and Vy refer to the same physical control point": True,
                    "both components use a compatible per-unit-width basis": (
                        True
                    ),
                    "both components are out-of-plane shear forces": True,
                },
                "satisfied": True,
            }
            or set(term_by_id) != {"x-squared", "y-squared"}
            or record.get(
                "demand_resultant_rotationally_invariant"
            ) is not True
            or record.get("rotationally_invariant") is not False
            or record.get("rotation_scope")
            != SHEAR_EN_2023_ROTATION_SCOPE
        ):
            issues.append(
                f"{label} resultant formula, authority, domain, terms, or "
                "rotation property is contradictory"
            )
    else:
        issues.append(f"{label} PASS/FAIL uses an unsupported method")

    if (
        expected_utilisation is None
        or utilisation is None
        or not _close(utilisation, expected_utilisation)
    ):
        issues.append(
            f"{label} utilisation contradicts its bound calculation terms"
        )
    return issues


def _result_fingerprint_issues(record: Mapping, label: str) -> list[str]:
    if not isinstance(record, Mapping):
        return [f"{label} is missing or not a mapping"]
    if record.get("schema") != INTERACTION_RESULT_SCHEMA:
        return [f"{label} has an unknown result schema"]
    fingerprint = record.get("evidence_fingerprint")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        return [f"{label} has an invalid evidence fingerprint"]
    body = copy.deepcopy(dict(record))
    body.pop("evidence_fingerprint", None)
    try:
        expected = _fingerprint(body)
    except (TypeError, ValueError):
        return [f"{label} contains non-canonical or non-finite evidence"]
    if fingerprint != expected:
        return [f"{label} evidence fingerprint does not match its body"]
    components = record.get("components")
    if not isinstance(components, list):
        return [f"{label} component evidence is not a list"]
    identities = [
        item.get("id")
        for item in components
        if isinstance(item, Mapping)
    ]
    if (
        len(identities) != len(components)
        or any(not isinstance(identity, str) for identity in identities)
    ):
        return [f"{label} contains a malformed component record"]
    if len(identities) != len(set(identities)):
        return [f"{label} contains duplicate component identities"]
    if (
        str(record.get("status") or "").upper() == "PASS"
        and not record.get("interaction_assessed")
    ):
        return [f"{label} claims PASS without an assessed interaction"]
    validation = record.get("publication_validation")
    if (
        isinstance(validation, Mapping)
        and validation.get("status") == "REJECTED"
    ) or record.get("qualification") == "PUBLICATION REJECTED":
        return [f"{label} carries a durable publication rejection"]
    return _record_semantic_issues(record, label)


def _rejected_publication_result(
    raw: Mapping,
    issues: Sequence[str],
) -> dict:
    safe = copy.deepcopy(dict(raw))
    safe.update(
        interaction_assessed=False,
        status="NOT ASSESSED",
        verdict="REVIEW",
        qualification="PUBLICATION REJECTED",
        reason=(
            "Stored multidirectional evidence was rejected; recalculate before "
            "publishing a combined conclusion. "
            + "; ".join(dict.fromkeys(issues))
        ),
        publication_validation={
            "status": "REJECTED",
            "issues": list(dict.fromkeys(issues)),
        },
    )
    safe.pop("evidence_fingerprint", None)
    return _seal_result(safe)


def _active_method_cannot_be_not_assessed(
    kind: str,
    current_inputs: Mapping,
    record: Mapping,
) -> bool:
    """Identify active, in-domain selections that require a real conclusion.

    A malformed calculation may legitimately be ``INVALID`` and a uniaxial
    shear state may be ``NOT APPLICABLE``.  Once the explicit method/domain
    gates below are satisfied, however, production cannot emit the softer
    ``NOT ASSESSED`` state.  This prevents a re-sealed PASS/FAIL from being
    downgraded after its calculation evidence is removed.
    """

    if kind == "crack":
        config = crack_configuration(current_inputs)
        if config.get("crack_interaction_on") is not True:
            return False
        method = config.get("crack_interaction_method")
        if method == CRACK_METHOD_PROJECT:
            return config.get("crack_interaction_domain_confirmed") is True
        edition_matches, _reason = _crack_selected_edition_matches(
            str(method or ""),
            current_inputs,
        )
        angle = _semantic_number(
            config.get("crack_interaction_angle_deg")
        )
        if method == CRACK_METHOD_DK_2004:
            return bool(
                edition_matches
                and config.get("crack_interaction_orthogonal") is True
                and config.get("crack_interaction_plane_stress") is True
                and config.get("crack_interaction_no_discontinuity") is True
                and angle is not None
                and 15.0 < angle < 90.0
            )
        if method == CRACK_METHOD_EN_2023:
            return bool(
                edition_matches
                and config.get("crack_interaction_orthogonal") is True
                and config.get("crack_interaction_membrane") is True
                and config.get("crack_interaction_no_discontinuity") is True
                and angle is not None
                and 15.0 < angle < 75.0
            )
        return False

    config = shear_configuration(current_inputs)
    if config.get("shear_interaction_on") is not True:
        return False
    method = config.get("shear_interaction_method")
    if method == SHEAR_METHOD_PROJECT:
        return config.get("shear_interaction_domain_confirmed") is True
    if method != SHEAR_METHOD_EN_2023:
        return False
    if not all(
        config.get(key) is True
        for key in (
            "shear_interaction_planar_member",
            "shear_interaction_same_control_point",
            "shear_interaction_per_unit_width",
            "shear_interaction_out_of_plane",
        )
    ):
        return False
    selected_shear_method = str(
        current_inputs.get("shear_method") or ""
    )
    if selected_shear_method:
        return selected_shear_method == SHEAR_CODE_EN_2023
    components = record.get("components")
    if not isinstance(components, list) or not components:
        return False
    component_methods = [
        component.get("method")
        for component in components
        if isinstance(component, Mapping)
    ]
    return bool(
        len(component_methods) == len(components)
        and all(
            isinstance(component_method, str)
            for component_method in component_methods
        )
        and set(component_methods) == {SHEAR_CODE_EN_2023}
    )


def publication_safe_interaction_record(
    record: Mapping | None,
    *,
    current_inputs: Mapping,
) -> dict | None:
    """Validate stored interaction evidence against the current input snapshot.

    A prior rejection is durable.  Repairing a stored record without a new
    calculation cannot upgrade it back to accepted evidence.
    """

    if not isinstance(record, Mapping):
        return None
    raw = copy.deepcopy(dict(record))
    prior_validation = raw.get("publication_validation")
    prior_rejected = (
        isinstance(prior_validation, Mapping)
        and prior_validation.get("status") == "REJECTED"
    )
    issues = []
    if raw.get("schema") != INTERACTION_BUNDLE_SCHEMA:
        issues.append("interaction bundle has an unknown schema")
    representation_issues = raw.get("representation_issues")
    if representation_issues is not None:
        if not isinstance(representation_issues, list):
            issues.append(
                "interaction bundle representation issues are malformed"
            )
        else:
            issues.extend(
                str(issue)
                for issue in representation_issues
                if str(issue).strip()
            )
    fingerprint = raw.get("fingerprint")
    body = copy.deepcopy(raw)
    body.pop("fingerprint", None)
    body.pop("publication_validation", None)
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        issues.append("interaction bundle fingerprint is invalid")
    else:
        try:
            expected = _fingerprint(body)
        except (TypeError, ValueError):
            expected = None
            issues.append(
                "interaction bundle contains non-canonical or non-finite evidence"
            )
        if expected is not None and fingerprint != expected:
            issues.append(
                "interaction bundle fingerprint does not match its body"
            )

    crack = raw.get("crack")
    if isinstance(crack, Mapping):
        issues.extend(_result_fingerprint_issues(crack, "crack interaction"))
        if crack.get("configuration") != crack_configuration(current_inputs):
            issues.append(
                "stored crack-interaction configuration does not match "
                "current inputs"
            )
        if (
            str(crack.get("status") or "").upper() == "NOT ASSESSED"
            and _active_method_cannot_be_not_assessed(
                "crack",
                current_inputs,
                crack,
            )
        ):
            issues.append(
                "stored active crack-interaction conclusion is downgraded or "
                "omits the required current assessment"
            )
        if str(crack.get("status") or "").upper() in {"PASS", "FAIL"}:
            if crack.get("selected_crack_code") != str(
                current_inputs.get("sls_code") or ""
            ):
                issues.append(
                    "stored crack-interaction code edition does not match "
                    "current inputs"
                )
            if (
                "sls_edition" in current_inputs
                and crack.get("selected_crack_edition") != str(
                    current_inputs.get("sls_edition") or ""
                )
            ):
                issues.append(
                    "stored crack-interaction edition does not match "
                    "current inputs"
                )
    elif crack is not None:
        issues.append("stored crack interaction is malformed")
    elif current_inputs.get("crack_interaction_on") is True:
        issues.append(
            "active crack-interaction evidence is missing"
        )

    raw_directional_cases = raw.get("directional_shear_cases")
    directional_cases = (
        raw_directional_cases
        if isinstance(raw_directional_cases, list)
        else []
    )
    if not isinstance(raw_directional_cases, list):
        issues.append(
            "stored directional shear cases are missing or are not a list"
        )
    directional_by_case: dict[str, list[Mapping]] = {}
    for index, directional_case in enumerate(directional_cases):
        label = f"directional shear case {index + 1}"
        issues.extend(
            _directional_shear_case_issues(directional_case, label)
        )
        if not isinstance(directional_case, Mapping):
            continue
        case_id = directional_case.get("case")
        if isinstance(case_id, str) and case_id.strip():
            directional_by_case.setdefault(case_id, []).append(
                directional_case
            )
    if any(
        len(records) != 1
        for records in directional_by_case.values()
    ):
        issues.append(
            "stored directional shear case identities are duplicated"
        )

    raw_cases = raw.get("shear_cases")
    cases = raw_cases if isinstance(raw_cases, list) else []
    if raw_cases is not None and not isinstance(raw_cases, list):
        issues.append("stored shear-interaction cases are not a list")
    case_names = []
    for index, raw_case in enumerate(cases):
        if not isinstance(raw_case, Mapping):
            issues.append(
                f"stored shear-interaction case {index + 1} is malformed"
            )
            continue
        case_name = raw_case.get("case")
        if not isinstance(case_name, str) or not case_name.strip():
            issues.append(
                f"stored shear-interaction case {index + 1} has no identity"
            )
        else:
            case_names.append(case_name)
        interaction = raw_case.get("interaction")
        issues.extend(
            _result_fingerprint_issues(
                interaction,
                f"shear interaction case {case_name or index + 1}",
            )
        )
        if (
            isinstance(interaction, Mapping)
            and interaction.get("configuration")
            != shear_configuration(current_inputs)
        ):
            issues.append(
                f"stored shear-interaction case {case_name or index + 1} "
                "does not match current inputs"
            )
        if (
            isinstance(interaction, Mapping)
            and str(interaction.get("status") or "").upper()
            == "NOT ASSESSED"
            and _active_method_cannot_be_not_assessed(
                "shear",
                current_inputs,
                interaction,
            )
        ):
            issues.append(
                f"stored active shear-interaction case "
                f"{case_name or index + 1} conclusion is downgraded or omits "
                "the required current assessment"
            )
        if (
            isinstance(interaction, Mapping)
            and str(interaction.get("status") or "").upper()
            == "NOT APPLICABLE"
        ):
            basis_matches = (
                directional_by_case.get(case_name, [])
                if isinstance(case_name, str)
                else []
            )
            if len(basis_matches) != 1:
                issues.append(
                    f"stored shear-interaction case "
                    f"{case_name or index + 1} NOT APPLICABLE disposition "
                    "is not bound to exactly one current directional case "
                    "evidence record"
                )
            else:
                basis_components = basis_matches[0].get("components")
                interaction_components = interaction.get("components")
                if (
                    not isinstance(basis_components, list)
                    or len(basis_components) != 1
                    or interaction_components != basis_components
                ):
                    issues.append(
                        f"stored shear-interaction case "
                        f"{case_name or index + 1} NOT APPLICABLE disposition "
                        "does not retain exactly one current directional shear "
                        "component or contradicts that case evidence"
                    )
        current_shear_method = str(current_inputs.get("shear_method") or "")
        raw_components = (
            interaction.get("components")
            if isinstance(interaction, Mapping)
            else None
        )
        if (
            current_shear_method
            and isinstance(interaction, Mapping)
            and isinstance(raw_components, list)
            and raw_components
        ):
            component_methods = {
                str(component.get("method") or "")
                for component in raw_components
                if isinstance(component, Mapping)
            }
            if component_methods != {current_shear_method}:
                issues.append(
                    f"stored shear-interaction case "
                    f"{case_name or index + 1} component method edition "
                    "does not match current inputs"
                )
    if len(case_names) != len(set(case_names)):
        issues.append("stored shear-interaction case identities are duplicated")
    if (
        len(directional_cases) != len(cases)
        or set(directional_by_case) != set(case_names)
    ):
        issues.append(
            "stored directional shear case evidence does not cover exactly "
            "the current shear-interaction cases"
        )
    if current_inputs.get("shear_interaction_on") is True and not cases:
        issues.append("active shear-interaction evidence is missing")

    if prior_rejected:
        issues.append(
            "a prior publication boundary rejected this interaction record"
        )
    if issues:
        safe = {
            "schema": INTERACTION_BUNDLE_SCHEMA,
            "crack": (
                _rejected_publication_result(crack, issues)
                if isinstance(crack, Mapping)
                else None
            ),
            "shear_cases": [
                {
                    "case": str(
                        (item or {}).get("case")
                        or f"case {index + 1}"
                    ),
                    "interaction": (
                        _rejected_publication_result(
                            (item or {}).get("interaction"), issues
                        )
                        if isinstance((item or {}).get("interaction"), Mapping)
                        else None
                    ),
                }
                for index, item in enumerate(cases)
                if isinstance(item, Mapping)
            ],
            "publication_validation": {
                "status": "REJECTED",
                "issues": list(dict.fromkeys(issues)),
                "reason": "; ".join(dict.fromkeys(issues)),
            },
        }
        safe["fingerprint"] = _fingerprint({
            key: value
            for key, value in safe.items()
            if key != "publication_validation"
        })
        return safe

    safe = copy.deepcopy(raw)
    safe["publication_validation"] = {
        "status": "ACCEPTED",
        "issues": [],
    }
    return safe


def _missing_publication_bundle(
    results: Mapping,
    current_inputs: Mapping,
) -> dict | None:
    """Create durable rejection evidence when every aggregate record is absent."""

    issues = []
    crack_record = None
    if current_inputs.get("crack_interaction_on") is True:
        issues.append("active crack-interaction evidence is missing")
        crack_config = crack_configuration(current_inputs)
        missing_crack = _not_assessed(
            "crack",
            crack_config,
            str(crack_config.get("crack_interaction_method") or ""),
            "No current crack-interaction calculation evidence is available.",
        )
        crack_record = _rejected_publication_result(
            missing_crack,
            issues,
        )

    current_cases = []
    plastic_entries = results.get("plastic_cases")
    if isinstance(plastic_entries, list):
        for entry in plastic_entries:
            if not isinstance(entry, Mapping):
                continue
            case_results = entry.get("results")
            if isinstance(case_results, Mapping):
                current_cases.append((
                    str(entry.get("name") or ""),
                    case_results,
                ))
    elif isinstance(results.get("shear"), Mapping):
        current_cases.append((
            str(
                ((current_inputs.get("plastic_case") or {}).get("id") or "")
                if isinstance(current_inputs.get("plastic_case"), Mapping)
                else ""
            ) or "Plastic",
            results,
        ))

    shear_records = []
    shear_active = current_inputs.get("shear_interaction_on") is True
    shear_config = shear_configuration(current_inputs)
    for case_name, case_results in current_cases:
        shear = case_results.get("shear")
        if not isinstance(shear, Mapping):
            continue
        if not shear_active and not shear.get("biaxial"):
            continue
        case_issue = (
            "Biaxial interaction: NOT ASSESSED - independent Vx/Vy checks "
            "remain reportable; no undocumented interaction or aggregate PASS "
            "is available because current interaction evidence is missing for "
            f"{case_name or 'an unnamed case'}"
        )
        issues.append(case_issue)
        missing_shear = _not_assessed(
            "shear",
            shear_config,
            str(shear_config.get("shear_interaction_method") or ""),
            "No current biaxial shear-interaction calculation evidence is "
            "available.",
        )
        try:
            components = _current_shear_components(case_results)
        except (InteractionInputError, TypeError, ValueError) as exc:
            components = []
            issues.append(
                f"current directional shear evidence is unusable for "
                f"{case_name or 'an unnamed case'}: {exc}"
            )
        missing_shear["components"] = copy.deepcopy(components)
        missing_shear["case_id"] = str(case_name or "")
        missing_shear = _seal_result(missing_shear)
        shear_records.append({
            "case": str(case_name or "Plastic"),
            "interaction": missing_shear,
        })
    if shear_active and not shear_records:
        issues.append("active shear-interaction evidence is missing")

    if not issues:
        return None
    rejected_shear_records = [
        {
            "case": item["case"],
            "interaction": _rejected_publication_result(
                item["interaction"],
                issues,
            ),
        }
        for item in shear_records
    ]
    if crack_record is not None:
        crack_record = _rejected_publication_result(
            crack_record,
            issues,
        )
    bundle = {
        "schema": INTERACTION_BUNDLE_SCHEMA,
        "crack": crack_record,
        "shear_cases": rejected_shear_records,
        "publication_validation": {
            "status": "REJECTED",
            "issues": list(dict.fromkeys(issues)),
            "reason": "; ".join(dict.fromkeys(issues)),
        },
    }
    bundle["fingerprint"] = _fingerprint({
        key: value
        for key, value in bundle.items()
        if key != "publication_validation"
    })
    return bundle


def publication_safe_results(
    results: Mapping | None,
    *,
    current_inputs: Mapping,
) -> dict:
    """Return reportable results with interaction evidence revalidated.

    Component crack and directional shear results are retained.  Missing,
    malformed, duplicated, stale, or previously rejected aggregate evidence is
    removed from the aggregate conclusion and cannot become PASS.
    """

    safe_results = copy.deepcopy(
        dict(results) if isinstance(results, Mapping) else {}
    )
    raw_bundle = interaction_calculation_record(safe_results)
    if raw_bundle is None:
        bundle = _missing_publication_bundle(
            safe_results,
            current_inputs,
        )
        if bundle is None:
            return safe_results
    else:
        bundle = publication_safe_interaction_record(
            raw_bundle,
            current_inputs=current_inputs,
        )
    if not isinstance(bundle, Mapping):
        return safe_results

    crack = bundle.get("crack")
    safe_results["crack_interaction"] = (
        copy.deepcopy(dict(crack))
        if isinstance(crack, Mapping)
        else None
    )
    selected_case = _crack_case_identity(crack)
    elastic_entries = safe_results.get("elastic_cases")
    if isinstance(elastic_entries, list):
        for entry in elastic_entries:
            if not isinstance(entry, dict):
                continue
            elastic = (entry.get("results") or {}).get("elastic")
            if not isinstance(elastic, dict):
                continue
            elastic.pop("crack_interaction", None)
            if (
                isinstance(crack, Mapping)
                and str(entry.get("name") or "") == selected_case
            ):
                elastic["crack_interaction"] = copy.deepcopy(dict(crack))
    elif isinstance(safe_results.get("elastic"), dict):
        safe_results["elastic"]["crack_interaction"] = copy.deepcopy(
            dict(crack)
        ) if isinstance(crack, Mapping) else None

    raw_cases = bundle.get("shear_cases")
    cases = raw_cases if isinstance(raw_cases, list) else []
    safe_results["shear_interactions"] = copy.deepcopy(cases)
    by_case: dict[str, list[Mapping]] = {}
    for item in cases:
        if not isinstance(item, Mapping):
            continue
        case_name = item.get("case")
        interaction = item.get("interaction")
        if isinstance(case_name, str) and isinstance(interaction, Mapping):
            by_case.setdefault(case_name, []).append(interaction)

    plastic_entries = safe_results.get("plastic_cases")
    if isinstance(plastic_entries, list):
        for entry in plastic_entries:
            if not isinstance(entry, dict):
                continue
            shear = (entry.get("results") or {}).get("shear")
            if not isinstance(shear, dict):
                continue
            matches = by_case.get(str(entry.get("name") or ""), [])
            if len(matches) == 1:
                _apply_shear_aggregate(matches[0], shear)
            else:
                shear.pop("interaction", None)
                shear["interaction_assessed"] = False
                shear["interaction_status"] = "NOT ASSESSED"
                shear["interaction_verdict"] = "REVIEW"
                if shear.get("biaxial") and shear.get("status") == "PASS":
                    shear["status"] = "REVIEW"
        if plastic_entries:
            first = plastic_entries[0].get("results") or {}
            if isinstance(first.get("shear"), Mapping):
                safe_results["shear"] = first["shear"]
    elif isinstance(safe_results.get("shear"), dict):
        matches = [
            item.get("interaction")
            for item in cases
            if isinstance(item, Mapping)
            and isinstance(item.get("interaction"), Mapping)
        ]
        if len(matches) == 1:
            _apply_shear_aggregate(matches[0], safe_results["shear"])
        else:
            safe_results["shear"].pop("interaction", None)
            safe_results["shear"]["interaction_assessed"] = False
            safe_results["shear"]["interaction_status"] = "NOT ASSESSED"
            safe_results["shear"]["interaction_verdict"] = "REVIEW"
            if (
                safe_results["shear"].get("biaxial")
                and safe_results["shear"].get("status") == "PASS"
            ):
                safe_results["shear"]["status"] = "REVIEW"
    safe_results["_publication_interaction_bundle"] = copy.deepcopy(bundle)
    return safe_results


def validation_errors(inp: Mapping | None) -> tuple[str, ...]:
    """Return active malformed input errors without rejecting positive customs."""

    source = inp if isinstance(inp, Mapping) else {}
    errors = []
    rejected = _rejected_input_keys(source, INTERACTION_INPUT_KEYS)
    if rejected:
        errors.append(
            "rejected multidirectional interaction fields must be explicitly "
            f"repaired ({', '.join(rejected)})"
        )
    for prefix, config, methods in (
        (
            "crack",
            crack_configuration(source),
            CRACK_METHODS,
        ),
        (
            "shear",
            shear_configuration(source),
            SHEAR_METHODS,
        ),
    ):
        on_key = f"{prefix}_interaction_on"
        method_key = f"{prefix}_interaction_method"
        enabled = config.get(on_key)
        if not isinstance(enabled, bool):
            errors.append(
                f"{on_key} must be an explicit Boolean selection"
            )
            continue
        if not enabled:
            continue
        method = config.get(method_key)
        if not isinstance(method, str) or method not in methods:
            errors.append(
                f"{method_key} must name a supported active methodology"
            )
    return tuple(errors)
