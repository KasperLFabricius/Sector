"""Headless serviceability assessment and result-evidence helpers.

The elastic solver returns numerical section states.  This module turns those
states into explicit, auditable acceptance checks and element/corner tables
without depending on Streamlit or the PDF renderer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Iterable as IterableCollection
from collections.abc import Set as SetCollection
from typing import Iterable, Mapping, Sequence

from . import danish_bridge


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

EDITION_BRIDGE_2005_AC = "bridge-2005-ac2008"
EDITION_BRIDGE_DK_2015 = "bridge-2005-dkna2015"
BRIDGE_EXPOSURE_NOT_ESTABLISHED = "Not established"
BRIDGE_EXPOSURE_X0_XC1 = "X0 / XC1"
BRIDGE_EXPOSURE_XC2_XC4 = "XC2 / XC3 / XC4"
BRIDGE_EXPOSURE_XD_XS = "XD / XS"
BRIDGE_EXPOSURE_CLASSES = (
    BRIDGE_EXPOSURE_NOT_ESTABLISHED,
    BRIDGE_EXPOSURE_X0_XC1,
    BRIDGE_EXPOSURE_XC2_XC4,
    BRIDGE_EXPOSURE_XD_XS,
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

CRACK_ACCEPTANCE_EVIDENCE_SCHEMA = (
    "sector.crack-acceptance-evidence/v1"
)

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


def _optional_text(value) -> str | None:
    """Return stripped text without coercing containers or Booleans."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _upper_text(value) -> str:
    """Return a normalized typed status/configuration token."""
    return (_optional_text(value) or "").upper()


def canonical_combination(value) -> str:
    """Return a stable SLS-combination token without inferring from duration."""
    text = _optional_text(value) or ""
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


def _contains_non_finite_numeric_value(value) -> bool:
    """Return whether structured audit evidence contains NaN or infinity."""
    if value is None or is_boolean_value(value):
        return False
    if isinstance(value, (str, bytes, bytearray)):
        return False

    value_type = type(value)
    module_root = value_type.__module__.split(".", 1)[0]
    if module_root == "pandas":
        to_numpy = getattr(value, "to_numpy", None)
        if callable(to_numpy):
            return _contains_non_finite_numeric_value(to_numpy())

    if isinstance(value, Mapping):
        return (
            any(
                _contains_non_finite_numeric_value(item)
                for item in value.keys()
            )
            or any(
                _contains_non_finite_numeric_value(item)
                for item in value.values()
            )
        )

    if isinstance(value, IterableCollection):
        try:
            iterator = iter(value)
        except TypeError:
            item = getattr(value, "item", None)
            if module_root == "numpy" and callable(item):
                return _contains_non_finite_numeric_value(item())
            return False
        return any(
            _contains_non_finite_numeric_value(item)
            for item in iterator
        )

    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return not math.isfinite(number)


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


def _finite_signed_numeric_value(value) -> float | None:
    """Return finite scalar evidence without accepting text or Booleans."""
    if (
        value is None
        or isinstance(value, (str, bytes))
        or contains_boolean_value(value)
    ):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _explicit_evidence_field(
    value,
    *,
    allow_nested_booleans: bool = False,
) -> bool:
    """Return whether an audit-evidence field is explicit and non-empty."""
    if (
        value is None
        or (
            is_boolean_value(value)
            if allow_nested_booleans
            else contains_boolean_value(value)
        )
        or _contains_non_finite_numeric_value(value)
    ):
        return False
    if isinstance(value, (str, bytes)):
        return bool(value.strip())
    try:
        return len(value) > 0
    except TypeError:
        return _finite_signed_numeric_value(value) is not None


def _validated_response_context(
    raw_context,
) -> tuple[dict, tuple[str, ...]]:
    """Normalize typed response identity/routing evidence."""
    if not isinstance(raw_context, Mapping):
        return {
            "combination": COMBINATION_UNSPECIFIED,
            "duration": None,
            "response_id": None,
            "provenance": None,
            "solver_provenance": None,
        }, ("context is absent or not a mapping",)

    raw = dict(raw_context)
    issues = []
    for key, label in (
        ("combination", "SLS combination"),
        ("duration", "duration state"),
        ("response_id", "response identity"),
        ("provenance", "mapping provenance"),
    ):
        if raw.get(key) is not None and not isinstance(raw.get(key), str):
            issues.append(f"{label} is not typed text")
    solver_provenance = raw.get("solver_provenance")
    if (
        solver_provenance is not None
        and not _explicit_evidence_field(
            solver_provenance,
            allow_nested_booleans=True,
        )
    ):
        issues.append("solver provenance is invalid")
    return {
        "combination": canonical_combination(raw.get("combination")),
        "duration": _optional_text(raw.get("duration")),
        "response_id": _optional_text(raw.get("response_id")),
        "provenance": _optional_text(raw.get("provenance")),
        "solver_provenance": copy.deepcopy(solver_provenance),
    }, tuple(issues)


def _validated_response_mapping_scope(
    raw_scope,
    *,
    allow_empty: bool = False,
) -> tuple[list[dict], tuple[str, ...]]:
    """Normalize the table-wide mapping independently of an assessment."""
    if raw_scope is None:
        if allow_empty:
            return [], ()
        return [], (
            "Table-wide response mapping scope is missing.",
        )
    if isinstance(
        raw_scope,
        (Mapping, str, bytes, bytearray),
    ) or is_boolean_value(raw_scope):
        return [], (
            "Table-wide response mapping scope is not a structured sequence.",
        )
    try:
        raw_items = tuple(raw_scope)
    except TypeError:
        return [], (
            "Table-wide response mapping scope is not iterable.",
        )
    if not raw_items:
        if allow_empty:
            return [], ()
        return [], (
            "Table-wide response mapping scope contains no response mappings.",
        )

    scope = []
    issues = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, Mapping):
            issues.append(
                f"Table-wide response mapping {index + 1} is not a mapping."
            )
            continue
        context, context_issues = _validated_response_context(raw)
        if context_issues:
            issues.append(
                f"Table-wide response mapping {index + 1} is invalid: "
                f"{'; '.join(context_issues)}."
            )
        response_id = context["response_id"]
        if not response_id:
            issues.append(
                f"Table-wide response mapping {index + 1} has no explicit "
                "response identity."
            )
        for value, label in (
            (context["duration"], "duration state"),
            (context["provenance"], "mapping provenance"),
            (_optional_text(raw.get("response")), "response label"),
            (_optional_text(raw.get("elastic_case")), "elastic-case identity"),
            (_optional_text(raw.get("state")), "response-state identity"),
        ):
            if value is None:
                issues.append(
                    f"Table-wide response mapping {index + 1} has no "
                    f"explicit {label}."
                )
        scope.append({
            "combination": context["combination"],
            "duration": context["duration"],
            "response": (
                _optional_text(raw.get("response"))
                or response_id
                or f"response {index + 1}"
            ),
            "response_id": response_id,
            "elastic_case": _optional_text(raw.get("elastic_case")),
            "state": _optional_text(raw.get("state")),
            "provenance": context["provenance"],
            "solver_provenance": context["solver_provenance"],
        })

    response_ids = [
        item["response_id"]
        for item in scope
        if item["response_id"] is not None
    ]
    duplicate_ids = sorted({
        response_id
        for response_id in response_ids
        if response_ids.count(response_id) > 1
    })
    if duplicate_ids:
        issues.append(
            "Table-wide response mapping scope duplicates response "
            f"identity: {', '.join(duplicate_ids)}."
        )
    return scope, tuple(issues)


def _validated_decompression_evidence(
    raw_evidence,
    *,
    fallback_solver_provenance=None,
) -> tuple[dict | None, tuple[str, ...]]:
    """Normalize complete typed decompression evidence or explain rejection."""
    if not isinstance(raw_evidence, Mapping):
        return None, ("evidence is absent or not a mapping",)

    raw = dict(raw_evidence)
    status = _upper_text(raw.get("status"))
    if status not in {"OK", "EXCEEDED", "NOT APPLICABLE"}:
        return None, ("acceptance status is missing or invalid",)
    evidence = {"status": status}
    raw_value = raw.get("value")
    raw_governing = raw.get("governing")
    explicit_solver_provenance = raw.get("solver_provenance")
    solver_provenance = explicit_solver_provenance

    issues = []
    if status in {"OK", "EXCEEDED"} or raw_value is not None:
        value = _finite_signed_numeric_value(raw_value)
        if value is None:
            issues.append("concrete-stress value is not a finite numeric scalar")
        else:
            evidence["value"] = value
    if (
        status in {"OK", "EXCEEDED"}
        or raw_governing is not None
    ):
        if not _explicit_evidence_field(raw_governing):
            issues.append("governing concrete location is missing")
        else:
            evidence["governing"] = copy.deepcopy(raw_governing)
    if not _explicit_evidence_field(
        solver_provenance,
        allow_nested_booleans=True,
    ):
        issues.append("solver provenance is missing")
    else:
        evidence["solver_provenance"] = copy.deepcopy(solver_provenance)
    if (
        explicit_solver_provenance is not None
        and fallback_solver_provenance is not None
        and (
            not _explicit_evidence_field(
                fallback_solver_provenance,
                allow_nested_booleans=True,
            )
            or not _evidence_values_equal(
                explicit_solver_provenance,
                fallback_solver_provenance,
            )
        )
    ):
        issues.append(
            "solver provenance conflicts with the response context"
        )
    reason = _optional_text(raw.get("reason"))
    if reason:
        evidence["reason"] = reason
    return (None if issues else evidence), tuple(issues)


def _evidence_values_equal(left, right) -> bool:
    """Compare normalized structured evidence without unsafe truth coercion."""
    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return False


def _decompression_evidence_conflicts(
    reference: Mapping,
    candidate: Mapping,
) -> tuple[str, ...]:
    """Return acceptance-relevant fields that differ between two responses."""
    conflicts = []
    if reference.get("status") != candidate.get("status"):
        conflicts.append("status")
    left_value = reference.get("value")
    right_value = candidate.get("value")
    if left_value is None or right_value is None:
        values_equal = left_value is None and right_value is None
    else:
        left_number = _finite_signed_numeric_value(left_value)
        right_number = _finite_signed_numeric_value(right_value)
        values_equal = (
            left_number is not None
            and right_number is not None
            and math.isclose(
                left_number,
                right_number,
                rel_tol=1e-9,
                abs_tol=1e-12,
            )
        )
    if not values_equal:
        conflicts.append("value")
    if not _evidence_values_equal(
        reference.get("governing"),
        candidate.get("governing"),
    ):
        conflicts.append("governing location")
    if not _evidence_values_equal(
        reference.get("solver_provenance"),
        candidate.get("solver_provenance"),
    ):
        conflicts.append("solver provenance")
    return tuple(conflicts)


_CRACK_CRITERION_STATUSES = {
    "INVALID",
    "EXCEEDED",
    "NOT ASSESSED",
    "OK",
    "NOT APPLICABLE",
}


def _validated_matched_response_names(
    raw_names,
) -> tuple[list[str], tuple[str, ...]]:
    """Normalize an explicit list of response labels without scalar coercion."""
    if raw_names is None:
        return [], ()
    if not isinstance(raw_names, (list, tuple)):
        return [], ("matched responses are not a structured list",)

    names = []
    issues = []
    for index, raw_name in enumerate(raw_names):
        name = _optional_text(raw_name)
        if name is None:
            issues.append(
                f"matched response {index + 1} is not typed non-empty text"
            )
        elif name in names:
            issues.append(f"matched response {name!r} is duplicated")
        else:
            names.append(name)
    return names, tuple(issues)


def _canonical_binding_value(value, *, path: str = "evidence"):
    """Return a JSON-stable typed value or reject unauditable evidence."""
    if value is None:
        return None
    if is_boolean_value(value):
        return bool(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        raise ValueError(f"{path} is binary rather than typed JSON evidence")
    if isinstance(value, Mapping):
        canonical = {}
        for raw_key, raw_value in value.items():
            key = _optional_text(raw_key)
            if key is None:
                raise ValueError(
                    f"{path} contains a non-text or empty mapping key"
                )
            canonical[key] = _canonical_binding_value(
                raw_value,
                path=f"{path}.{key}",
            )
        return {
            key: canonical[key]
            for key in sorted(canonical)
        }
    if isinstance(value, SetCollection):
        raise ValueError(f"{path} is unordered rather than typed JSON evidence")
    if isinstance(value, IterableCollection):
        try:
            items = list(value)
        except TypeError as exc:
            raise ValueError(f"{path} is not iterable evidence") from exc
        return [
            _canonical_binding_value(
                item,
                path=f"{path}[{index}]",
            )
            for index, item in enumerate(items)
        ]
    number = _finite_signed_numeric_value(value)
    if number is None:
        raise ValueError(f"{path} is not finite typed evidence")
    return number


def _criterion_binding_metadata(
    criterion: Mapping,
) -> tuple[dict, tuple[str, ...]]:
    """Normalize criterion identity and applicability for an evidence binding."""
    criterion_id = _optional_text(
        criterion.get("criterion_id") or criterion.get("id")
    )
    kind = _optional_text(
        criterion.get("kind") or criterion.get("criterion")
    )
    source_type = _optional_text(
        criterion.get("criterion_source_type")
        or criterion.get("source_type")
    )
    source = _optional_text(
        criterion.get("criterion_source")
        or criterion.get("source")
    )
    required = canonical_combination(
        criterion.get("required_combination")
    )
    raw_applicability = criterion.get("applicability")
    issues = []
    for value, label in (
        (criterion_id, "criterion identity"),
        (kind, "criterion kind"),
        (source_type, "criterion source type"),
        (source, "criterion source"),
    ):
        if value is None:
            issues.append(f"{label} is missing")
    if required not in SLS_COMBINATIONS[1:]:
        issues.append("required SLS combination is missing or invalid")
    if not isinstance(raw_applicability, Mapping):
        issues.append("criterion applicability is not a mapping")
        applicability = {}
    else:
        try:
            applicability = _canonical_binding_value(
                raw_applicability,
                path="criterion applicability",
            )
        except ValueError as exc:
            applicability = {}
            issues.append(str(exc))

    raw_limit = (
        criterion.get("limit")
        if "limit" in criterion
        else criterion.get("limit_mm")
    )
    limit = (
        None
        if kind == CRITERION_DECOMPRESSION
        else _finite_positive(raw_limit)
    )
    if kind != CRITERION_DECOMPRESSION and limit is None:
        issues.append("crack-width limit is missing or invalid")
    return {
        "id": criterion_id,
        "kind": kind,
        "source_type": source_type,
        "source": source,
        "applicability": applicability,
        "required_combination": required,
        "limit_mm": limit,
    }, tuple(issues)


def _response_width_value(response: Mapping) -> float | None:
    raw_width = (
        response.get("wk_mm")
        if "wk_mm" in response
        else response.get("wk")
    )
    return crack_width_numeric_value(raw_width)


def _response_governing_element(response: Mapping):
    element = response.get("element_id")
    if element is None and response.get("gov_bar") is not None:
        element = f"element {response.get('gov_bar')}"
    return copy.deepcopy(element)


def _canonical_binding_scope(
    mapping_scope: Sequence[Mapping],
) -> list[dict]:
    canonical = [
        _canonical_binding_value(
            item,
            path=f"response mapping scope[{index}]",
        )
        for index, item in enumerate(mapping_scope)
    ]
    return sorted(
        canonical,
        key=lambda item: (
            str(item.get("response_id") or ""),
            str(item.get("response") or ""),
            str(item.get("elastic_case") or ""),
            str(item.get("state") or ""),
        ),
    )


def _build_acceptance_evidence_binding(
    criterion: Mapping,
    responses: Mapping[str, Mapping | None],
    *,
    response_contexts: Mapping[str, Mapping | None] | None = None,
    response_mapping_scope: Sequence[Mapping] = (),
) -> tuple[dict | None, dict | None, tuple[str, ...]]:
    """Reconstruct one immutable criterion-to-response acceptance binding."""
    metadata, metadata_issues = _criterion_binding_metadata(criterion)
    matched, matched_issues = _validated_matched_response_names(
        criterion.get("matched_responses")
    )
    issues = list(metadata_issues) + list(matched_issues)
    if not matched:
        issues.append("matched response labels are missing")

    contexts = {}
    raw_contexts = (
        response_contexts
        if isinstance(response_contexts, Mapping)
        else {}
    )
    for name, raw_response in responses.items():
        response = raw_response if isinstance(raw_response, Mapping) else {}
        raw_context = (
            raw_contexts.get(name)
            if name in raw_contexts
            else response.get("context")
        )
        context, context_issues = _validated_response_context(raw_context)
        contexts[name] = context
        if context_issues:
            issues.append(
                f"{name} response context is invalid: "
                f"{'; '.join(context_issues)}"
            )

    required = metadata["required_combination"]
    response_entries = []
    response_ids = set()
    for name in matched:
        raw_response = responses.get(name)
        if not isinstance(raw_response, Mapping):
            issues.append(
                f"matched response {name!r} has no current mapping evidence"
            )
            continue
        role = _optional_text(raw_response.get("acceptance_role"))
        if role and role.lower() == "informational":
            issues.append(
                f"matched response {name!r} is marked informational"
            )
        context = contexts.get(name) or {}
        response_id = _optional_text(context.get("response_id"))
        if response_id is None:
            issues.append(
                f"matched response {name!r} has no response identity"
            )
        else:
            response_ids.add(response_id)
        if context.get("combination") != required:
            issues.append(
                f"matched response {name!r} does not carry the required "
                f"{required} combination"
            )
        if _optional_text(context.get("duration")) is None:
            issues.append(
                f"matched response {name!r} has no explicit duration state"
            )
        if _optional_text(context.get("provenance")) is None:
            issues.append(
                f"matched response {name!r} has no explicit mapping provenance"
            )
        if not _explicit_evidence_field(
            context.get("solver_provenance"),
            allow_nested_booleans=True,
        ):
            issues.append(
                f"matched response {name!r} has no explicit solver provenance"
            )

        entry = {
            "label": name,
            "response_id": response_id,
            "combination": context.get("combination"),
            "duration": context.get("duration"),
            "mapping_provenance": context.get("provenance"),
            "solver_provenance": copy.deepcopy(
                context.get("solver_provenance")
            ),
        }
        if metadata["kind"] == CRITERION_DECOMPRESSION:
            evidence, evidence_issues = _validated_decompression_evidence(
                raw_response.get("decompression"),
                fallback_solver_provenance=context.get(
                    "solver_provenance"
                ),
            )
            if evidence_issues:
                issues.append(
                    f"{name} decompression evidence is incomplete: "
                    f"{'; '.join(evidence_issues)}"
                )
                evidence = None
            if evidence is not None:
                entry["acceptance"] = {
                    "type": "decompression",
                    "status": evidence.get("status"),
                    "value": evidence.get("value"),
                    "governing": copy.deepcopy(
                        evidence.get("governing")
                    ),
                    "solver_provenance": copy.deepcopy(
                        evidence.get("solver_provenance")
                    ),
                }
        else:
            width = _response_width_value(raw_response)
            if width is None:
                issues.append(
                    f"{name} crack-width evidence is missing or invalid"
                )
            governing_element = _response_governing_element(raw_response)
            if not _explicit_evidence_field(governing_element):
                issues.append(
                    f"{name} governing crack-width element is missing"
                )
            entry["acceptance"] = {
                "type": "crack_width",
                "value_mm": width,
                "governing_element": governing_element,
            }
        response_entries.append(entry)

    if len(response_ids) != 1 and matched:
        issues.append(
            "matched responses do not share one explicit response identity"
        )
    response_id = next(iter(response_ids)) if len(response_ids) == 1 else None

    required_names = {
        name
        for name, context in contexts.items()
        if context.get("combination") == required
    }
    if set(matched) != required_names:
        missing = sorted(required_names - set(matched))
        extra = sorted(set(matched) - required_names)
        details = []
        if missing:
            details.append(
                "unbound required response labels " + ", ".join(missing)
            )
        if extra:
            details.append(
                "non-required matched response labels " + ", ".join(extra)
            )
        issues.append("; ".join(details) or "matched response set changed")

    identity_names = {
        name
        for name, context in contexts.items()
        if response_id is not None
        and context.get("response_id") == response_id
    }
    if response_id is not None and set(matched) != identity_names:
        issues.append(
            "full response-label alias set for the response identity changed"
        )

    if response_entries:
        reference = response_entries[0]
        for entry in response_entries[1:]:
            changed = []
            for key, label in (
                ("response_id", "response identity"),
                ("combination", "SLS combination"),
                ("duration", "duration state"),
                ("mapping_provenance", "mapping provenance"),
                ("solver_provenance", "solver provenance"),
            ):
                if not _evidence_values_equal(
                    reference.get(key),
                    entry.get(key),
                ):
                    changed.append(label)
            if changed:
                issues.append(
                    f"{entry['label']} conflicts across aliases in "
                    f"{', '.join(changed)}"
                )

    try:
        canonical_scope = _canonical_binding_scope(
            response_mapping_scope
        )
    except ValueError as exc:
        canonical_scope = []
        issues.append(str(exc))
    if not canonical_scope:
        issues.append(
            "complete table-wide response mapping scope is missing or empty"
        )
    scope_by_identity = {}
    for item in canonical_scope:
        scope_by_identity.setdefault(item.get("response_id"), []).append(item)
    for name, context in contexts.items():
        current_response_id = _optional_text(context.get("response_id"))
        if current_response_id is None:
            continue
        scoped_contexts = scope_by_identity.get(current_response_id, [])
        if len(scoped_contexts) != 1:
            issues.append(
                f"current response {name!r} identity {current_response_id!r} "
                "is not represented exactly once in the complete table-wide "
                "mapping scope"
            )
            continue
        scoped_context = scoped_contexts[0]
        context_conflicts = []
        for scope_key, context_key, label in (
            ("combination", "combination", "SLS combination"),
            ("duration", "duration", "duration state"),
            ("provenance", "provenance", "mapping provenance"),
        ):
            if not _evidence_values_equal(
                scoped_context.get(scope_key),
                context.get(context_key),
            ):
                context_conflicts.append(label)
        if context_conflicts:
            issues.append(
                f"complete table-wide mapping scope conflicts with current "
                f"response {name!r} in {', '.join(context_conflicts)}"
            )

    if canonical_scope and response_id is not None:
        scoped_identity = [
            item
            for item in canonical_scope
            if item.get("response_id") == response_id
        ]
        if len(scoped_identity) != 1:
            issues.append(
                "response identity is not represented exactly once in "
                "the table-wide mapping scope"
            )
        elif scoped_identity[0].get("combination") != required:
            issues.append(
                "table-wide mapping scope carries a different required "
                "combination"
            )
        elif response_entries:
            scoped = scoped_identity[0]
            reference = response_entries[0]
            scope_conflicts = []
            for scope_key, response_key, label in (
                ("duration", "duration", "duration state"),
                (
                    "provenance",
                    "mapping_provenance",
                    "mapping provenance",
                ),
                (
                    "solver_provenance",
                    "solver_provenance",
                    "solver provenance",
                ),
            ):
                scope_value = scoped.get(scope_key)
                if (
                    scope_value is not None
                    and not _evidence_values_equal(
                        scope_value,
                        reference.get(response_key),
                    )
                ):
                    scope_conflicts.append(label)
            if scope_conflicts:
                issues.append(
                    "table-wide mapping scope conflicts with the matched "
                    "response context in "
                    + ", ".join(scope_conflicts)
                )

    if issues:
        return None, None, tuple(dict.fromkeys(issues))

    try:
        response_entries = sorted(
            (
                _canonical_binding_value(
                    entry,
                    path=f"matched response {entry['label']}",
                )
                for entry in response_entries
            ),
            key=lambda entry: entry["label"],
        )
    except ValueError as exc:
        return None, None, (str(exc),)
    if metadata["kind"] == CRITERION_DECOMPRESSION:
        acceptance = response_entries[0]["acceptance"]
        if acceptance.get("status") not in {"OK", "EXCEEDED"}:
            return None, None, (
                "current decompression evidence does not support an "
                "accepted verdict",
            )
        for entry in response_entries[1:]:
            if entry["acceptance"] != acceptance:
                return None, None, (
                    "matched aliases carry conflicting decompression "
                    "acceptance evidence",
                )
        outcome = {
            "status": acceptance["status"],
            "case": response_entries[0]["label"],
            "value": acceptance.get("value"),
            "governing": acceptance.get("governing"),
            "limit": None,
        }
    else:
        limit = metadata["limit_mm"]
        governing_entry = max(
            response_entries,
            key=lambda entry: (
                entry["acceptance"]["value_mm"],
                entry["label"],
            ),
        )
        value = governing_entry["acceptance"]["value_mm"]
        outcome = {
            "status": "OK" if value <= limit else "EXCEEDED",
            "case": governing_entry["label"],
            "value": value,
            "governing": governing_entry["acceptance"].get(
                "governing_element"
            ),
            "limit": limit,
        }

    body = _canonical_binding_value({
        "schema": CRACK_ACCEPTANCE_EVIDENCE_SCHEMA,
        "criterion": metadata,
        "matched_responses": response_entries,
        "response_mapping_scope": canonical_scope,
        "outcome": outcome,
    })
    validated_body, body_issues = _validated_acceptance_evidence_body(body)
    if body_issues or validated_body is None:
        return None, None, body_issues
    fingerprint = _acceptance_evidence_fingerprint(validated_body)
    binding = {**validated_body, "fingerprint": fingerprint}
    return binding, body["outcome"], ()


_ACCEPTANCE_EVIDENCE_BODY_KEYS = {
    "schema",
    "criterion",
    "matched_responses",
    "response_mapping_scope",
    "outcome",
}
_ACCEPTANCE_EVIDENCE_CRITERION_KEYS = {
    "id",
    "kind",
    "source_type",
    "source",
    "applicability",
    "required_combination",
    "limit_mm",
}
_ACCEPTANCE_EVIDENCE_RESPONSE_KEYS = {
    "label",
    "response_id",
    "combination",
    "duration",
    "mapping_provenance",
    "solver_provenance",
    "acceptance",
}
_ACCEPTANCE_EVIDENCE_SCOPE_KEYS = {
    "combination",
    "duration",
    "response",
    "response_id",
    "elastic_case",
    "state",
    "provenance",
    "solver_provenance",
}
_ACCEPTANCE_EVIDENCE_OUTCOME_KEYS = {
    "status",
    "case",
    "value",
    "governing",
    "limit",
}


def _schema_mapping_keys_issue(
    value: Mapping,
    expected: set[str],
    *,
    label: str,
) -> str | None:
    keys = set(value)
    missing = sorted(expected - keys)
    unexpected = sorted(keys - expected)
    details = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if unexpected:
        details.append("unexpected " + ", ".join(unexpected))
    if not details:
        return None
    return f"{label} fields are invalid ({'; '.join(details)})"


def _acceptance_evidence_fingerprint(body: Mapping) -> str:
    return hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _validated_acceptance_evidence_body(
    raw_body,
) -> tuple[dict | None, tuple[str, ...]]:
    """Validate the complete canonical v1 binding body and its invariants."""
    if not isinstance(raw_body, Mapping):
        return None, ("acceptance-evidence body is not a mapping",)
    try:
        body = _canonical_binding_value(
            raw_body,
            path="acceptance-evidence body",
        )
    except ValueError as exc:
        return None, (str(exc),)

    issues = []
    body_keys_issue = _schema_mapping_keys_issue(
        body,
        _ACCEPTANCE_EVIDENCE_BODY_KEYS,
        label="acceptance-evidence body",
    )
    if body_keys_issue:
        issues.append(body_keys_issue)
    if body.get("schema") != CRACK_ACCEPTANCE_EVIDENCE_SCHEMA:
        issues.append("acceptance-evidence schema is missing or unsupported")

    criterion = body.get("criterion")
    if not isinstance(criterion, Mapping):
        issues.append("acceptance-evidence criterion is not a mapping")
        criterion = {}
    else:
        criterion_keys_issue = _schema_mapping_keys_issue(
            criterion,
            _ACCEPTANCE_EVIDENCE_CRITERION_KEYS,
            label="acceptance-evidence criterion",
        )
        if criterion_keys_issue:
            issues.append(criterion_keys_issue)
    for key, label in (
        ("id", "criterion identity"),
        ("kind", "criterion kind"),
        ("source_type", "criterion source type"),
        ("source", "criterion source"),
    ):
        if _optional_text(criterion.get(key)) is None:
            issues.append(f"acceptance-evidence {label} is missing")
    applicability = criterion.get("applicability")
    if not isinstance(applicability, Mapping) or not applicability:
        issues.append(
            "acceptance-evidence criterion applicability is not an "
            "explicit non-empty mapping"
        )
    required = canonical_combination(
        criterion.get("required_combination")
    )
    if required not in SLS_COMBINATIONS[1:]:
        issues.append(
            "acceptance-evidence required SLS combination is invalid"
        )
    kind = _optional_text(criterion.get("kind"))
    limit = criterion.get("limit_mm")
    typed_limit = _finite_signed_numeric_value(limit)
    if kind == CRITERION_DECOMPRESSION:
        if limit is not None:
            issues.append(
                "acceptance-evidence decompression criterion has a width limit"
            )
    elif typed_limit is None or typed_limit <= 0.0:
        issues.append(
            "acceptance-evidence crack-width limit is missing or invalid"
        )

    matched = body.get("matched_responses")
    if not isinstance(matched, list) or not matched:
        issues.append(
            "acceptance-evidence matched responses are not a non-empty list"
        )
        matched = []
    response_labels = []
    response_ids = []
    typed_responses = []
    for index, raw_response in enumerate(matched):
        label = f"acceptance-evidence matched response {index + 1}"
        if not isinstance(raw_response, Mapping):
            issues.append(f"{label} is not a mapping")
            continue
        response_keys_issue = _schema_mapping_keys_issue(
            raw_response,
            _ACCEPTANCE_EVIDENCE_RESPONSE_KEYS,
            label=label,
        )
        if response_keys_issue:
            issues.append(response_keys_issue)
        response_label = _optional_text(raw_response.get("label"))
        response_id = _optional_text(raw_response.get("response_id"))
        duration = _optional_text(raw_response.get("duration"))
        mapping_provenance = _optional_text(
            raw_response.get("mapping_provenance")
        )
        if response_label is None:
            issues.append(f"{label} has no response label")
        else:
            response_labels.append(response_label)
        if response_id is None:
            issues.append(f"{label} has no response identity")
        else:
            response_ids.append(response_id)
        if canonical_combination(
            raw_response.get("combination")
        ) != required:
            issues.append(
                f"{label} does not carry the required SLS combination"
            )
        if duration is None:
            issues.append(f"{label} has no duration state")
        if mapping_provenance is None:
            issues.append(f"{label} has no mapping provenance")
        if not _explicit_evidence_field(
            raw_response.get("solver_provenance"),
            allow_nested_booleans=True,
        ):
            issues.append(f"{label} has no solver provenance")

        acceptance = raw_response.get("acceptance")
        if not isinstance(acceptance, Mapping):
            issues.append(f"{label} acceptance is not a mapping")
            continue
        acceptance_type = _optional_text(acceptance.get("type"))
        if kind == CRITERION_DECOMPRESSION:
            expected_acceptance_keys = {
                "type",
                "status",
                "value",
                "governing",
                "solver_provenance",
            }
            if acceptance_type != "decompression":
                issues.append(
                    f"{label} acceptance type is not decompression"
                )
            acceptance_keys_issue = _schema_mapping_keys_issue(
                acceptance,
                expected_acceptance_keys,
                label=f"{label} acceptance",
            )
            if acceptance_keys_issue:
                issues.append(acceptance_keys_issue)
            if _upper_text(acceptance.get("status")) not in {
                "OK",
                "EXCEEDED",
            }:
                issues.append(
                    f"{label} decompression status is invalid"
                )
            if _finite_signed_numeric_value(
                acceptance.get("value")
            ) is None:
                issues.append(
                    f"{label} decompression value is not finite numeric "
                    "evidence"
                )
            if not _explicit_evidence_field(
                acceptance.get("governing")
            ):
                issues.append(
                    f"{label} decompression governing location is missing"
                )
            if not _explicit_evidence_field(
                acceptance.get("solver_provenance"),
                allow_nested_booleans=True,
            ):
                issues.append(
                    f"{label} decompression solver provenance is missing"
                )
        else:
            expected_acceptance_keys = {
                "type",
                "value_mm",
                "governing_element",
            }
            if acceptance_type != "crack_width":
                issues.append(
                    f"{label} acceptance type is not crack_width"
                )
            acceptance_keys_issue = _schema_mapping_keys_issue(
                acceptance,
                expected_acceptance_keys,
                label=f"{label} acceptance",
            )
            if acceptance_keys_issue:
                issues.append(acceptance_keys_issue)
            width_value = _finite_signed_numeric_value(
                acceptance.get("value_mm")
            )
            if width_value is None or width_value < 0.0:
                issues.append(
                    f"{label} crack-width value is not finite typed numeric "
                    "evidence"
                )
            if not _explicit_evidence_field(
                acceptance.get("governing_element")
            ):
                issues.append(
                    f"{label} governing crack-width element is missing"
                )
        typed_responses.append(raw_response)

    if len(response_labels) != len(set(response_labels)):
        issues.append("acceptance-evidence response labels are duplicated")
    if len(set(response_ids)) != 1 and matched:
        issues.append(
            "acceptance-evidence matched responses do not share one "
            "response identity"
        )
    if typed_responses:
        reference = typed_responses[0]
        for response in typed_responses[1:]:
            for key, label in (
                ("response_id", "response identity"),
                ("combination", "SLS combination"),
                ("duration", "duration state"),
                ("mapping_provenance", "mapping provenance"),
                ("solver_provenance", "solver provenance"),
            ):
                if not _evidence_values_equal(
                    reference.get(key),
                    response.get(key),
                ):
                    issues.append(
                        "acceptance-evidence aliases conflict in "
                        f"{label}"
                    )

    scope = body.get("response_mapping_scope")
    if not isinstance(scope, list) or not scope:
        issues.append(
            "acceptance-evidence response mapping scope is not a complete "
            "non-empty list"
        )
        scope = []
    scope_ids = []
    typed_scope = []
    for index, raw_scope in enumerate(scope):
        label = f"acceptance-evidence mapping scope entry {index + 1}"
        if not isinstance(raw_scope, Mapping):
            issues.append(f"{label} is not a mapping")
            continue
        scope_keys_issue = _schema_mapping_keys_issue(
            raw_scope,
            _ACCEPTANCE_EVIDENCE_SCOPE_KEYS,
            label=label,
        )
        if scope_keys_issue:
            issues.append(scope_keys_issue)
        scope_id = _optional_text(raw_scope.get("response_id"))
        if scope_id is None:
            issues.append(f"{label} has no response identity")
        else:
            scope_ids.append(scope_id)
        if canonical_combination(
            raw_scope.get("combination")
        ) not in SLS_COMBINATIONS:
            issues.append(f"{label} has an invalid SLS combination")
        for key, field_label in (
            ("duration", "duration state"),
            ("response", "response label"),
            ("elastic_case", "elastic-case identity"),
            ("state", "response-state identity"),
            ("provenance", "mapping provenance"),
        ):
            if _optional_text(raw_scope.get(key)) is None:
                issues.append(f"{label} has no {field_label}")
        scope_solver = raw_scope.get("solver_provenance")
        if (
            scope_solver is not None
            and not _explicit_evidence_field(
                scope_solver,
                allow_nested_booleans=True,
            )
        ):
            issues.append(f"{label} has invalid solver provenance")
        typed_scope.append(raw_scope)
    if len(scope_ids) != len(set(scope_ids)):
        issues.append(
            "acceptance-evidence mapping scope response identities are "
            "duplicated"
        )

    matched_identity = (
        response_ids[0]
        if response_ids and len(set(response_ids)) == 1
        else None
    )
    if matched_identity is not None:
        matching_scope = [
            item
            for item in typed_scope
            if item.get("response_id") == matched_identity
        ]
        if len(matching_scope) != 1:
            issues.append(
                "acceptance-evidence matched response identity is not "
                "represented exactly once in the complete mapping scope"
            )
        elif typed_responses:
            scoped = matching_scope[0]
            reference = typed_responses[0]
            for scope_key, response_key, label in (
                ("combination", "combination", "SLS combination"),
                ("duration", "duration", "duration state"),
                (
                    "provenance",
                    "mapping_provenance",
                    "mapping provenance",
                ),
            ):
                if not _evidence_values_equal(
                    scoped.get(scope_key),
                    reference.get(response_key),
                ):
                    issues.append(
                        "acceptance-evidence mapping scope conflicts with "
                        f"the matched response in {label}"
                    )

    expected_outcome = None
    if typed_responses and kind == CRITERION_DECOMPRESSION:
        acceptance = typed_responses[0].get("acceptance")
        if isinstance(acceptance, Mapping):
            if any(
                response.get("acceptance") != acceptance
                for response in typed_responses[1:]
            ):
                issues.append(
                    "acceptance-evidence decompression aliases carry "
                    "conflicting acceptance evidence"
                )
            expected_outcome = {
                "status": _upper_text(acceptance.get("status")),
                "case": _optional_text(
                    typed_responses[0].get("label")
                ),
                "value": acceptance.get("value"),
                "governing": acceptance.get("governing"),
                "limit": None,
            }
    elif (
        typed_responses
        and typed_limit is not None
        and typed_limit > 0.0
    ):
        numeric_responses = []
        for response in typed_responses:
            acceptance = response.get("acceptance")
            if not isinstance(acceptance, Mapping):
                continue
            width_value = _finite_signed_numeric_value(
                acceptance.get("value_mm")
            )
            if width_value is not None and width_value >= 0.0:
                numeric_responses.append((response, width_value))
        if len(numeric_responses) == len(typed_responses):
            governing_response, value = max(
                numeric_responses,
                key=lambda response_and_value: (
                    response_and_value[1],
                    _optional_text(response_and_value[0].get("label"))
                    or "",
                ),
            )
            expected_outcome = {
                "status": "OK" if value <= typed_limit else "EXCEEDED",
                "case": _optional_text(
                    governing_response.get("label")
                ),
                "value": value,
                "governing": governing_response["acceptance"].get(
                    "governing_element"
                ),
                "limit": typed_limit,
            }

    outcome = body.get("outcome")
    if not isinstance(outcome, Mapping):
        issues.append("acceptance-evidence outcome is not a mapping")
    else:
        outcome_keys_issue = _schema_mapping_keys_issue(
            outcome,
            _ACCEPTANCE_EVIDENCE_OUTCOME_KEYS,
            label="acceptance-evidence outcome",
        )
        if outcome_keys_issue:
            issues.append(outcome_keys_issue)
        if expected_outcome is None:
            issues.append(
                "acceptance-evidence expected outcome cannot be reconstructed"
            )
        elif not _evidence_values_equal(outcome, expected_outcome):
            issues.append(
                "acceptance-evidence outcome is inconsistent with its "
                "criterion and matched responses"
            )

    if issues:
        return None, tuple(dict.fromkeys(issues))
    return body, ()


def _validated_acceptance_evidence_binding(
    raw_binding,
) -> tuple[dict | None, tuple[str, ...]]:
    """Validate the stored immutable binding before comparing current evidence."""
    if not isinstance(raw_binding, Mapping):
        return None, ("acceptance-evidence binding is missing or not a mapping",)
    try:
        binding = _canonical_binding_value(
            raw_binding,
            path="acceptance-evidence binding",
        )
    except ValueError as exc:
        return None, (str(exc),)
    expected_binding_keys = _ACCEPTANCE_EVIDENCE_BODY_KEYS | {"fingerprint"}
    binding_keys_issue = _schema_mapping_keys_issue(
        binding,
        expected_binding_keys,
        label="acceptance-evidence binding",
    )
    if binding_keys_issue:
        return None, (binding_keys_issue,)
    fingerprint = _optional_text(binding.get("fingerprint"))
    if (
        fingerprint is None
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        return None, ("acceptance-evidence fingerprint is invalid",)
    body = {
        key: value
        for key, value in binding.items()
        if key != "fingerprint"
    }
    validated_body, body_issues = _validated_acceptance_evidence_body(body)
    if body_issues or validated_body is None:
        return None, body_issues
    expected = _acceptance_evidence_fingerprint(validated_body)
    if fingerprint != expected:
        return None, (
            "acceptance-evidence fingerprint does not match its stored body",
        )
    return {**validated_body, "fingerprint": fingerprint}, ()


def _acceptance_evidence_binding_conflicts(
    stored: Mapping,
    current: Mapping,
) -> tuple[str, ...]:
    """Describe acceptance-relevant changes between immutable/current bindings."""
    conflicts = []
    stored_criterion = stored.get("criterion") or {}
    current_criterion = current.get("criterion") or {}
    for key, label in (
        ("id", "criterion identity"),
        ("kind", "criterion kind"),
        ("source_type", "criterion source type"),
        ("source", "criterion source"),
        ("applicability", "criterion applicability"),
        ("required_combination", "required SLS combination"),
        ("limit_mm", "acceptance limit"),
    ):
        if stored_criterion.get(key) != current_criterion.get(key):
            conflicts.append(label)

    stored_responses = {
        item.get("label"): item
        for item in (stored.get("matched_responses") or [])
        if isinstance(item, Mapping)
    }
    current_responses = {
        item.get("label"): item
        for item in (current.get("matched_responses") or [])
        if isinstance(item, Mapping)
    }
    if set(stored_responses) != set(current_responses):
        conflicts.append("matched response label set")
    for label in sorted(set(stored_responses) & set(current_responses)):
        stored_response = stored_responses[label]
        current_response = current_responses[label]
        for key, field_label in (
            ("response_id", "response identity"),
            ("combination", "SLS combination"),
            ("duration", "duration state"),
            ("mapping_provenance", "mapping provenance"),
            ("solver_provenance", "solver provenance"),
            ("acceptance", "calculated acceptance evidence"),
        ):
            if stored_response.get(key) != current_response.get(key):
                conflicts.append(f"{label} {field_label}")
    if stored.get("response_mapping_scope") != current.get(
        "response_mapping_scope"
    ):
        conflicts.append("table-wide response mapping scope")
    if stored.get("outcome") != current.get("outcome"):
        conflicts.append("governing acceptance outcome")
    if (
        stored.get("fingerprint") != current.get("fingerprint")
        and not conflicts
    ):
        conflicts.append("acceptance-evidence fingerprint")
    return tuple(dict.fromkeys(conflicts))


def _accepted_item_outcome_conflicts(
    item: Mapping,
    binding: Mapping,
) -> tuple[str, ...]:
    """Bind the stored visible PASS/FAIL fields to its immutable outcome."""
    outcome = binding.get("outcome") or {}
    criterion = binding.get("criterion") or {}
    conflicts = []
    if _upper_text(item.get("status")) != outcome.get("status"):
        conflicts.append(
            "status "
            f"{_upper_text(item.get('status')) or '-'} does not match "
            f"immutable outcome {outcome.get('status') or '-'}"
        )
    if _optional_text(item.get("case")) != _optional_text(
        outcome.get("case")
    ):
        conflicts.append("governing response label")

    expected_value = outcome.get("value")
    stored_value = _finite_signed_numeric_value(item.get("value"))
    if (
        expected_value is None
        and item.get("value") is not None
    ) or (
        expected_value is not None
        and (
            stored_value is None
            or not math.isclose(
                stored_value,
                expected_value,
                rel_tol=1e-9,
                abs_tol=1e-12,
            )
        )
    ):
        conflicts.append("accepted value")
    if not _evidence_values_equal(
        item.get("governing"),
        outcome.get("governing"),
    ):
        conflicts.append("governing evidence")

    expected_limit = outcome.get("limit")
    if criterion.get("kind") == CRITERION_DECOMPRESSION:
        if item.get("limit") is not None:
            conflicts.append("decompression limit")
    else:
        stored_limit = _finite_positive(item.get("limit"))
        if (
            stored_limit is None
            or expected_limit is None
            or not math.isclose(
                stored_limit,
                expected_limit,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            conflicts.append("acceptance limit")
    responses = binding.get("matched_responses") or []
    if responses:
        reference = responses[0]
        if _optional_text(item.get("response_duration")) != _optional_text(
            reference.get("duration")
        ):
            conflicts.append("response duration")
        if _optional_text(item.get("response_provenance")) != _optional_text(
            reference.get("mapping_provenance")
        ):
            conflicts.append("mapping provenance")
        if not _evidence_values_equal(
            item.get("solver_provenance"),
            reference.get("solver_provenance"),
        ):
            conflicts.append("solver provenance")
    return tuple(conflicts)


def validated_current_acceptance_evidence_binding(
    item: Mapping,
    responses: Mapping[str, Mapping | None],
    *,
    response_contexts: Mapping[str, Mapping | None] | None = None,
    response_mapping_scope: Sequence[Mapping] = (),
) -> tuple[dict | None, tuple[str, ...]]:
    """Validate one accepted criterion against immutable and current evidence.

    Raw bridge adapters and stored/publication boundaries use this same typed
    correlation gate. A self-consistent stored fingerprint is insufficient:
    the visible outcome and independently reconstructed current response binding
    must also agree before the acceptance may be republished.
    """

    if not isinstance(item, Mapping):
        return None, ("accepted criterion is not a mapping",)
    if not isinstance(responses, Mapping):
        return None, ("current crack responses are not a mapping",)
    if (
        response_contexts is not None
        and not isinstance(response_contexts, Mapping)
    ):
        return None, ("current crack response contexts are not a mapping",)
    if not isinstance(response_mapping_scope, (list, tuple)):
        return None, (
            "current crack response mapping scope is not a structured list",
        )
    stored_binding, stored_issues = _validated_acceptance_evidence_binding(
        item.get("acceptance_evidence")
    )
    if stored_issues or stored_binding is None:
        return None, (
            "invalid immutable acceptance evidence: "
            + (
                "; ".join(stored_issues)
                or "unknown stored-evidence error"
            ),
        )
    outcome_conflicts = _accepted_item_outcome_conflicts(
        item,
        stored_binding,
    )
    if outcome_conflicts:
        return None, (
            "visible acceptance result does not match its immutable "
            "evidence binding: "
            + "; ".join(outcome_conflicts),
        )
    current_binding, _current_outcome, current_issues = (
        _build_acceptance_evidence_binding(
            item,
            responses,
            response_contexts=response_contexts,
            response_mapping_scope=response_mapping_scope,
        )
    )
    if current_issues or current_binding is None:
        return None, (
            "acceptance evidence cannot be reconstructed: "
            + (
                "; ".join(current_issues)
                or "unknown current-evidence error"
            ),
        )
    binding_conflicts = _acceptance_evidence_binding_conflicts(
        stored_binding,
        current_binding,
    )
    if binding_conflicts:
        return None, (
            "immutable acceptance evidence does not match the current "
            "response binding: "
            + "; ".join(binding_conflicts),
        )
    return current_binding, ()


def _apply_acceptance_evidence_binding(
    item: dict,
    binding: Mapping,
) -> None:
    """Publish visible result/provenance fields from a verified binding."""
    outcome = binding["outcome"]
    criterion = binding["criterion"]
    responses = binding["matched_responses"]
    reference = responses[0]
    canonical_labels = [response["label"] for response in responses]
    stored_labels, stored_label_issues = _validated_matched_response_names(
        item.get("matched_responses")
    )
    matched_labels = (
        stored_labels
        if (
            not stored_label_issues
            and len(stored_labels) == len(canonical_labels)
            and set(stored_labels) == set(canonical_labels)
        )
        else canonical_labels
    )
    item.update(
        status=outcome["status"],
        case=outcome["case"],
        value=outcome["value"],
        governing=copy.deepcopy(outcome["governing"]),
        limit=outcome["limit"],
        required_combination=criterion["required_combination"],
        matched_responses=matched_labels,
        response_duration=reference.get("duration"),
        response_provenance=reference.get("mapping_provenance"),
        solver_provenance=copy.deepcopy(
            reference.get("solver_provenance")
        ),
        acceptance_evidence=copy.deepcopy(binding),
    )
    if criterion["kind"] == CRITERION_DECOMPRESSION:
        item["util"] = None
        item["margin"] = None
    else:
        item["util"] = outcome["value"] / outcome["limit"]
        item["margin"] = outcome["limit"] - outcome["value"]


def _bind_accepted_criterion_results(
    criteria: Sequence[dict],
    responses: Mapping[str, Mapping | None],
    contexts: Mapping[str, Mapping | None],
    mapping_scope: Sequence[Mapping],
) -> None:
    """Attach canonical bindings or downgrade results that cannot be bound."""
    criterion_ids = [
        _optional_text(
            criterion.get("criterion_id") or criterion.get("id")
        )
        for criterion in criteria
    ]
    duplicate_ids = {
        criterion_id
        for criterion_id in criterion_ids
        if criterion_id is not None
        and criterion_ids.count(criterion_id) > 1
    }
    for criterion in criteria:
        criterion_id = _optional_text(
            criterion.get("criterion_id") or criterion.get("id")
        )
        if criterion_id in duplicate_ids:
            criterion.update(
                status="NOT ASSESSED",
                value=None,
                util=None,
                margin=None,
                case=None,
                governing=None,
                response_duration=None,
                acceptance_evidence=None,
                reason=(
                    "Canonical acceptance-evidence binding could not be "
                    "established because criterion identity "
                    f"{criterion_id!r} is duplicated."
                ),
            )
            continue
        if _upper_text(criterion.get("status")) not in {"OK", "EXCEEDED"}:
            criterion["acceptance_evidence"] = None
            continue
        binding, outcome, issues = _build_acceptance_evidence_binding(
            criterion,
            responses,
            response_contexts=contexts,
            response_mapping_scope=mapping_scope,
        )
        if issues or binding is None or outcome is None:
            reason = (
                "Canonical acceptance-evidence binding could not be "
                f"established: {'; '.join(issues) or 'unknown evidence error'}."
            )
            criterion.update(
                status="NOT ASSESSED",
                value=None,
                util=None,
                margin=None,
                case=", ".join(
                    _validated_matched_response_names(
                        criterion.get("matched_responses")
                    )[0]
                ) or None,
                governing=None,
                response_duration=None,
                acceptance_evidence=None,
                reason=reason,
            )
            continue

        _apply_acceptance_evidence_binding(criterion, binding)


def _crack_criteria_outcome(
    criteria: Sequence[Mapping],
) -> tuple[str, Mapping]:
    """Apply the one canonical aggregate precedence to criterion results."""
    items = list(criteria)
    statuses = [_upper_text(item.get("status")) for item in items]
    if any(status == "INVALID" for status in statuses):
        overall_status = "INVALID"
    elif any(status == "EXCEEDED" for status in statuses):
        overall_status = "EXCEEDED"
    elif any(status == "NOT ASSESSED" for status in statuses):
        overall_status = "NOT ASSESSED"
    elif any(status == "OK" for status in statuses):
        overall_status = "OK"
    else:
        overall_status = "NOT APPLICABLE"

    if overall_status in {"INVALID", "NOT ASSESSED"}:
        governing = next(
            item
            for item in items
            if _upper_text(item.get("status")) == overall_status
        )
    elif overall_status in {"EXCEEDED", "OK"}:
        candidates = [
            item
            for item in items
            if _upper_text(item.get("status")) == overall_status
        ]

        def utilisation(item):
            value = _finite_signed_numeric_value(item.get("util"))
            return value if value is not None else 0.0

        governing = max(candidates, key=utilisation)
    else:
        governing = items[0]
    return overall_status, governing


def _crack_aggregate_fields(criteria: Sequence[Mapping]) -> dict:
    """Build top-level acceptance fields from the governing criterion."""
    overall_status, governing = _crack_criteria_outcome(criteria)
    verdict = {
        "OK": "PASS",
        "EXCEEDED": "FAIL",
        "NOT APPLICABLE": "NOT APPLICABLE",
    }.get(overall_status, "REVIEW")
    return {
        "value": governing.get("value"),
        "limit": governing.get("limit"),
        "util": governing.get("util"),
        "margin": governing.get("margin"),
        "status": overall_status,
        "verdict": verdict,
        "case": governing.get("case"),
        "governing": governing.get("governing"),
        "criterion": governing.get("kind"),
        "required_combination": governing.get("required_combination"),
        "criterion_source": governing.get("criterion_source"),
        "applicability": governing.get("applicability"),
        "response_duration": governing.get("response_duration"),
        "response_provenance": governing.get("response_provenance"),
        "solver_provenance": governing.get("solver_provenance"),
        "matched_responses": _validated_matched_response_names(
            governing.get("matched_responses")
        )[0],
        "acceptance_evidence": copy.deepcopy(
            governing.get("acceptance_evidence")
        ),
        "reason": governing.get("reason"),
    }


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
        acceptance_evidence=None,
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
    raw_criteria = safe.get("criteria")
    iterable_criteria = (
        raw_criteria if isinstance(raw_criteria, (list, tuple)) else ()
    )
    for raw in iterable_criteria:
        if not isinstance(raw, Mapping):
            continue
        item = copy.deepcopy(dict(raw))
        if _upper_text(item.get("status")) != "NOT APPLICABLE":
            item.update(
                status="NOT ASSESSED",
                value=None,
                util=None,
                margin=None,
                case=None,
                governing=None,
                response_duration=None,
                acceptance_evidence=None,
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
        current_responses = {}
        criterion_responses = {}
        response_names = set()
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
                name = (
                    _optional_text(response.get("name"))
                    or f"response {response_index + 1}"
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
                    and _upper_text(response.get("solver_status"))
                    != "NOT APPLICABLE"
                    and not _optional_text(
                        response.get("result_validation")
                    )
                ):
                    response["result_validation"] = (
                        "Stored crack response has no validated numeric width."
                    )
            response["name"] = name

            duplicate_name = name in response_names
            response_names.add(name)
            raw_context = response.get("context")
            context, context_issues = _validated_response_context(
                raw_context
            )
            response["context"] = context
            solver = context.get("solver_provenance")
            if context_issues:
                prior_validation = _optional_text(
                    response.get("result_validation")
                )
                context_validation = (
                    "Stored crack-response context rejected: "
                    + "; ".join(context_issues)
                    + "."
                )
                response["result_validation"] = " ".join(
                    part
                    for part in (prior_validation, context_validation)
                    if part
                )
            if response.get("decompression") is not None:
                evidence, evidence_issues = (
                    _validated_decompression_evidence(
                        response.get("decompression"),
                        fallback_solver_provenance=solver,
                    )
                )
                if evidence_issues:
                    response.pop("decompression", None)
                    response["decompression_validation"] = (
                        "Stored decompression evidence rejected: "
                        + "; ".join(evidence_issues)
                        + "."
                    )
                else:
                    response["decompression"] = evidence
            validation = (
                _optional_text(response.get("result_validation")) or ""
            )
            if duplicate_name:
                rejected.append({
                    "response": name,
                    "reason": (
                        "Stored crack-response identities are duplicated; "
                        f"{name!r} is not unique."
                    ),
                    "solver_provenance": solver,
                })
            role = str(
                _optional_text(response.get("acceptance_role")) or ""
            ).lower()
            response["acceptance_role"] = (
                "informational"
                if role == "informational"
                else "criterion input"
            )
            if not duplicate_name:
                current_responses[name] = response
            if validation:
                rejected.append({
                    "response": name,
                    "reason": validation,
                    "solver_provenance": solver,
                })
            elif (
                not duplicate_name
                and response["acceptance_role"] != "informational"
            ):
                criterion_responses[name] = response
            responses.append(response)

        current_mapping_scope, mapping_scope_issues = (
            _validated_response_mapping_scope(
                case.get("response_mapping_scope"),
                allow_empty=True,
            )
        )
        if mapping_scope_issues:
            rejected.append({
                "response": "response mapping scope",
                "reason": " ".join(mapping_scope_issues),
                "solver_provenance": None,
            })
        case["response_mapping_scope"] = current_mapping_scope

        assessment = (
            dict(case.get("assessment"))
            if isinstance(case.get("assessment"), Mapping)
            else {}
        )
        raw_criteria = assessment.get("criteria")
        normalized_criteria = []
        criteria_issue = None
        if raw_criteria is not None:
            if not isinstance(raw_criteria, (list, tuple)):
                criteria_issue = (
                    "Stored crack criteria are not a structured list."
                )
            elif raw_criteria:
                for criterion_index, raw_criterion in enumerate(raw_criteria):
                    if not isinstance(raw_criterion, Mapping):
                        criteria_issue = (
                            "Stored crack criterion "
                            f"{criterion_index + 1} is not a mapping."
                        )
                        break
                    criterion = copy.deepcopy(dict(raw_criterion))
                    status = _upper_text(criterion.get("status"))
                    if status not in _CRACK_CRITERION_STATUSES:
                        criteria_issue = (
                            "Stored crack criterion "
                            f"{criterion_index + 1} has no valid status."
                        )
                        break
                    matched_names, matched_issues = (
                        _validated_matched_response_names(
                            criterion.get("matched_responses")
                        )
                    )
                    if matched_issues:
                        criteria_issue = (
                            "Stored crack criterion "
                            f"{criterion_index + 1} has invalid response "
                            f"identity evidence: {'; '.join(matched_issues)}."
                        )
                        break
                    criterion["status"] = status
                    criterion["matched_responses"] = matched_names
                    normalized_criteria.append(criterion)
                criterion_ids = [
                    _optional_text(
                        criterion.get("criterion_id")
                        or criterion.get("id")
                    )
                    for criterion in normalized_criteria
                ]
                duplicate_ids = sorted({
                    criterion_id
                    for criterion_id in criterion_ids
                    if criterion_id is not None
                    and criterion_ids.count(criterion_id) > 1
                })
                if duplicate_ids:
                    criteria_issue = (
                        "Stored crack criteria duplicate criterion "
                        f"identity: {', '.join(duplicate_ids)}."
                    )
        if criteria_issue:
            assessment["criteria"] = []
            rejected.append({
                "response": "assessment criteria",
                "reason": criteria_issue,
                "solver_provenance": assessment.get(
                    "solver_provenance"
                ),
            })
        elif normalized_criteria:
            assessment["criteria"] = normalized_criteria
            assessment.update(
                _crack_aggregate_fields(normalized_criteria)
            )
        elif raw_criteria is not None:
            assessment["criteria"] = []

        acceptance_items = []
        assessment_criteria = assessment.get("criteria")
        for criterion_index, raw_criterion in enumerate(
            assessment_criteria
            if isinstance(assessment_criteria, (list, tuple))
            else ()
        ):
            if not isinstance(raw_criterion, Mapping):
                continue
            criterion = (
                raw_criterion
                if isinstance(raw_criterion, dict)
                else dict(raw_criterion)
            )
            if _upper_text(criterion.get("status")) in {
                "OK",
                "EXCEEDED",
            }:
                acceptance_items.append(
                    (f"criterion {criterion_index + 1}", criterion)
                )
        if (
            not acceptance_items
            and (
                _upper_text(assessment.get("verdict")) in {"PASS", "FAIL"}
                or _upper_text(assessment.get("status"))
                in {"OK", "EXCEEDED"}
            )
        ):
            acceptance_items.append(("assessment", assessment))

        def item_response_names(item):
            names = []
            case_name = _optional_text(item.get("case"))
            if case_name:
                names.append(case_name)
            matched, _matched_issues = _validated_matched_response_names(
                item.get("matched_responses")
            )
            for name in matched:
                if name not in names:
                    names.append(name)
            return names

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
            _matched_names, matched_issues = (
                _validated_matched_response_names(
                    item.get("matched_responses")
                )
            )
            if matched_issues:
                return (
                    f"Stored {label} has invalid matched-response evidence: "
                    f"{'; '.join(matched_issues)}.",
                    [],
                )
            names = item_response_names(item)
            if not names:
                return (
                    f"Stored {label} has no governing response identity.",
                    names,
                )
            current_binding, binding_issues = (
                validated_current_acceptance_evidence_binding(
                    item,
                    current_responses,
                    response_mapping_scope=current_mapping_scope,
                )
            )
            if binding_issues or current_binding is None:
                return (
                    f"Stored {label} acceptance was rejected: "
                    f"{'; '.join(binding_issues) or 'unknown evidence error'}.",
                    names,
                )
            _apply_acceptance_evidence_binding(item, current_binding)
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
        if not rejected:
            def canonicalize_acceptance_metrics(item):
                kind = str(
                    _optional_text(item.get("kind"))
                    or _optional_text(item.get("criterion"))
                    or ""
                )
                status = _upper_text(item.get("status"))
                if kind == CRITERION_DECOMPRESSION:
                    item["limit"] = None
                    item["util"] = None
                    item["margin"] = None
                elif status in {"OK", "EXCEEDED"}:
                    value = crack_width_numeric_value(item.get("value"))
                    limit = _finite_positive(item.get("limit"))
                    if value is not None and limit is not None:
                        item["value"] = value
                        item["limit"] = limit
                        item["util"] = value / limit
                        item["margin"] = limit - value

            published_criteria = assessment.get("criteria")
            if isinstance(published_criteria, list) and published_criteria:
                for item in published_criteria:
                    canonicalize_acceptance_metrics(item)
                assessment.update(
                    _crack_aggregate_fields(published_criteria)
                )
            else:
                canonicalize_acceptance_metrics(assessment)
        if (
            responses
            or normalized_criteria
            or "response_contexts" in assessment
            or "informational_responses" in assessment
        ):
            assessment["response_contexts"] = {
                (
                    _optional_text(response.get("name"))
                    or f"response {index + 1}"
                ): copy.deepcopy(response.get("context") or {})
                for index, response in enumerate(responses)
            }
            assessment["response_mapping_scope"] = copy.deepcopy(
                current_mapping_scope
            )
            assessment["informational_responses"] = [
                (
                    _optional_text(response.get("name"))
                    or f"response {index + 1}"
                )
                for index, response in enumerate(responses)
                if response.get("acceptance_role") == "informational"
            ]
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
    if edition == EDITION_BRIDGE_2005_AC:
        return (
            "DS/EN 1992-2:2005 section 7.3.1(105), Table 7.101N; "
            "EN 1992-2:2005/AC:2008"
        )
    if edition == EDITION_BRIDGE_DK_2015:
        return (
            "DS/EN 1992-2:2005 section 7.3.1(105), Table 7.101N; "
            "EN 1992-2:2005/AC:2008; DS/EN 1992-2 DK NA:2015, "
            "Table 7.101N DK NA, PDF page 4"
        )
    base = "DS/EN 1992-1-1:2004 section 7.3.1(5), Table 7.1N"
    if dk_na:
        return (
            base
            + "; DS/EN 1992-1-1 DK NA:2024 section 7.3.1(5), Table 7.1 NA"
        )
    return base


def _criterion_source(reference: str, project_source: str) -> str:
    project_source = _optional_text(project_source) or ""
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
    status = _upper_text(configuration_status)
    if not status:
        status = "NOT ASSESSED" if configuration_reason else "READY"
    return {
        "id": criterion_id,
        "kind": kind,
        "source_type": source_type,
        "source": _optional_text(source) or "",
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
    bridge_exposure_class = str(
        inp.get("sls_bridge_exposure_class")
        or BRIDGE_EXPOSURE_NOT_ESTABLISHED
    ).strip()
    dk_bridge_class = str(
        inp.get("bridge_asset_class")
        or danish_bridge.NOT_ESTABLISHED
    ).strip()
    dk_environment_class = str(
        inp.get("bridge_environment_class")
        or danish_bridge.NOT_ESTABLISHED
    ).strip()
    dk_member_class = str(
        inp.get("sls_dk_member_class")
        or danish_bridge.NOT_ESTABLISHED
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
        "bridge_exposure_class": bridge_exposure_class,
        "dk_bridge_class": dk_bridge_class,
        "dk_environment_class": dk_environment_class,
        "dk_member_class": dk_member_class,
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
    if edition not in {
        "2004",
        "2023",
        EDITION_BRIDGE_2005_AC,
        EDITION_BRIDGE_DK_2015,
    }:
        base_reasons.append("The selected code edition is not supported.")
    if prestress_class not in PRESTRESS_CLASSES:
        base_reasons.append(
            "Select whether the member is reinforced/unbonded or bonded prestress."
        )
    if edition == "2004" and not exposure:
        base_reasons.append(
            "State the exposure/application context used to establish applicability."
        )
    if (
        edition == EDITION_BRIDGE_2005_AC
        and bridge_exposure_class not in BRIDGE_EXPOSURE_CLASSES[1:]
    ):
        base_reasons.append(
            "Select the governing DS/EN 1992-2 Table 7.101N exposure group."
        )
    if edition == EDITION_BRIDGE_DK_2015:
        if dk_bridge_class not in {
            danish_bridge.ASSET_ROAD,
            danish_bridge.ASSET_FOOT,
            danish_bridge.ASSET_RAIL,
        }:
            base_reasons.append(
                "Select road bridge, footbridge, or railway bridge explicitly "
                "for Table 7.101N DK NA."
            )
        if dk_environment_class not in {
            danish_bridge.ENVIRONMENT_AGGRESSIVE,
            danish_bridge.ENVIRONMENT_EXTRA_AGGRESSIVE,
        }:
            base_reasons.append(
                "Select Aggressive or Extra aggressive Danish bridge "
                "environment; Moderate is not used for bridges."
            )
        if dk_member_class not in danish_bridge.MEMBER_CLASSES[1:]:
            base_reasons.append(
                "Select non-prestressed or pre/post-tensioned Danish member "
                "class explicitly."
            )
        has_tendons = inp.get("sls_has_tendons")
        if not is_boolean_value(has_tendons):
            base_reasons.append(
                "Danish member routing requires explicit Boolean tendon-"
                "presence evidence from the calculation snapshot."
            )
        else:
            if (
                dk_member_class == danish_bridge.MEMBER_NONPRESTRESSED
                and bool(has_tendons)
            ):
                base_reasons.append(
                    "The non-prestressed route conflicts with tendons in the "
                    "calculation snapshot."
                )
            if (
                dk_member_class == danish_bridge.MEMBER_PRESTRESSED
                and not bool(has_tendons)
            ):
                base_reasons.append(
                    "The prestressed route conflicts with a calculation "
                    "snapshot containing no tendons."
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
    if durability_selected and edition == EDITION_BRIDGE_2005_AC:
        reference = _criterion_source(
            _standard_reference(
                edition, CRITERION_DURABILITY, dk_na
            ),
            source,
        )
        if base_reason:
            criteria.append(_criterion_record(
                "bridge-standard-durability-routing",
                CRITERION_DURABILITY,
                source_type=CRITERION_MODE_STANDARD,
                source=reference,
                required_combination=None,
                limit_mm=None,
                applicability=applicability,
                configuration_reason=base_reason,
            ))
        elif prestress_class == PRESTRESS_REINFORCED_UNBONDED:
            criteria.append(_criterion_record(
                "bridge-standard-durability",
                CRITERION_DURABILITY,
                source_type=CRITERION_MODE_STANDARD,
                source=reference,
                required_combination=COMBINATION_QUASI_PERMANENT,
                limit_mm=0.30,
                applicability=applicability,
            ))
        elif prestress_class == PRESTRESS_BONDED:
            if bridge_exposure_class in {
                BRIDGE_EXPOSURE_X0_XC1,
                BRIDGE_EXPOSURE_XC2_XC4,
            }:
                criteria.append(_criterion_record(
                    "bridge-standard-durability",
                    CRITERION_DURABILITY,
                    source_type=CRITERION_MODE_STANDARD,
                    source=reference,
                    required_combination=COMBINATION_FREQUENT,
                    limit_mm=0.20,
                    applicability=applicability,
                ))
            if bridge_exposure_class == BRIDGE_EXPOSURE_XC2_XC4:
                criteria.append(_criterion_record(
                    "bridge-standard-decompression",
                    CRITERION_DECOMPRESSION,
                    source_type=CRITERION_MODE_STANDARD,
                    source=reference,
                    required_combination=COMBINATION_QUASI_PERMANENT,
                    limit_mm=None,
                    applicability={
                        **applicability,
                        "decompression_applicability": (
                            "Table 7.101N required"
                        ),
                    },
                ))
            elif bridge_exposure_class == BRIDGE_EXPOSURE_XD_XS:
                criteria.append(_criterion_record(
                    "bridge-standard-decompression",
                    CRITERION_DECOMPRESSION,
                    source_type=CRITERION_MODE_STANDARD,
                    source=reference,
                    required_combination=COMBINATION_FREQUENT,
                    limit_mm=None,
                    applicability={
                        **applicability,
                        "decompression_applicability": (
                            "Table 7.101N required"
                        ),
                    },
                ))

    if durability_selected and edition == EDITION_BRIDGE_DK_2015:
        reference = _criterion_source(
            _standard_reference(
                edition, CRITERION_DURABILITY, True
            ),
            source,
        )
        if base_reason:
            criteria.append(_criterion_record(
                "bridge-dk-standard-durability-routing",
                CRITERION_DURABILITY,
                source_type=CRITERION_MODE_STANDARD,
                source=reference,
                required_combination=None,
                limit_mm=None,
                applicability=applicability,
                configuration_reason=base_reason,
            ))
        else:
            extra_aggressive = (
                dk_environment_class
                == danish_bridge.ENVIRONMENT_EXTRA_AGGRESSIVE
            )
            if dk_member_class == danish_bridge.MEMBER_NONPRESTRESSED:
                crack_limit = 0.20 if extra_aggressive else 0.30
            elif dk_bridge_class == danish_bridge.ASSET_RAIL:
                crack_limit = 0.10
            else:
                crack_limit = 0.10 if extra_aggressive else 0.20
            criteria.append(_criterion_record(
                "bridge-dk-standard-durability",
                CRITERION_DURABILITY,
                source_type=CRITERION_MODE_STANDARD,
                source=reference,
                required_combination=COMBINATION_FREQUENT,
                limit_mm=crack_limit,
                applicability=applicability,
            ))
            if dk_member_class == danish_bridge.MEMBER_PRESTRESSED:
                criteria.append(_criterion_record(
                    "bridge-dk-standard-decompression",
                    CRITERION_DECOMPRESSION,
                    source_type=CRITERION_MODE_STANDARD,
                    source=reference,
                    required_combination=COMBINATION_QUASI_PERMANENT,
                    limit_mm=None,
                    applicability={
                        **applicability,
                        "decompression_applicability": (
                            "Table 7.101N DK NA required"
                        ),
                    },
                ))

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
    supplied_criteria = []
    criteria_invalid = False
    if criteria is not None:
        if not isinstance(criteria, (list, tuple)):
            criteria_invalid = True
        else:
            for raw_criterion in criteria:
                if not isinstance(raw_criterion, Mapping):
                    criteria_invalid = True
                    break
                supplied_criteria.append(dict(raw_criterion))
    if criteria_invalid:
        supplied_criteria = [_criterion_record(
            "calculated-criterion-integrity",
            "Crack-control criterion configuration",
            source_type="Configuration validation",
            source="Structured criterion integrity gate",
            required_combination=None,
            limit_mm=None,
            applicability={},
            configuration_reason=(
                "Crack-control criteria are not a structured list of "
                "criterion mappings."
            ),
        )]
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

    routing_integrity_issues = []
    if response_contexts is not None and not isinstance(
        response_contexts, Mapping
    ):
        routing_integrity_issues.append(
            "Response contexts are not a structured mapping."
        )
    context_map = response_contexts if isinstance(
        response_contexts, Mapping
    ) else {}
    contexts = {}
    for name in cases:
        raw = context_map.get(name)
        if raw is None:
            raw = {}
        context, context_issues = _validated_response_context(raw)
        if context_issues:
            routing_integrity_issues.append(
                f"Response context for {name} is invalid: "
                f"{'; '.join(context_issues)}."
            )
        contexts[name] = context

    mapping_scope, mapping_scope_issues = (
        _validated_response_mapping_scope(response_mapping_scope)
    )
    routing_integrity_issues.extend(mapping_scope_issues)

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

    disposition_map = (
        dispositions if isinstance(dispositions, Mapping) else {}
    )
    if dispositions is not None and not isinstance(dispositions, Mapping):
        routing_integrity_issues.append(
            "Solver dispositions are not a structured mapping."
        )
    else:
        for name in cases:
            if (
                name in disposition_map
                and disposition_map[name] is not None
                and not isinstance(disposition_map[name], Mapping)
            ):
                routing_integrity_issues.append(
                    f"Solver disposition for {name} is not structured "
                    "evidence."
                )

    criterion_results = []
    if routing_integrity_issues:
        criterion_results.append({
            "criterion_id": "crack-routing-integrity",
            "kind": "Crack-control routing evidence integrity",
            "criterion_source_type": "Routing validation",
            "criterion_source": "Structured response-routing integrity gate",
            "applicability": {
                "issues": list(dict.fromkeys(routing_integrity_issues)),
            },
            "required_combination": None,
            "limit": None,
            "util": None,
            "margin": None,
            "value": None,
            "case": None,
            "governing": None,
            "response_duration": None,
            "response_provenance": None,
            "solver_provenance": None,
            "matched_responses": [],
            "status": "NOT ASSESSED",
            "reason": " ".join(dict.fromkeys(routing_integrity_issues)),
        })
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
    if routing_integrity_issues:
        outcome = _crack_aggregate_fields(criterion_results)
        outcome.update({
            "criteria": criterion_results,
            "response_contexts": contexts,
            "response_mapping_scope": mapping_scope,
            "informational_responses": list(cases),
        })
        return outcome
    matched_names: set[str] = set()

    for criterion in supplied_criteria:
        item = dict(criterion)
        required = item.get("required_combination")
        required = (
            canonical_combination(required) if required is not None else None
        )
        limit = _finite_positive(item.get("limit_mm"))
        label = _optional_text(item.get("kind")) or "Crack width"
        raw_applicability = item.get("applicability")
        applicability = (
            dict(raw_applicability)
            if isinstance(raw_applicability, Mapping)
            else {}
        )
        base = {
            "criterion_id": item.get("id"),
            "kind": label,
            "criterion_source_type": item.get("source_type"),
            "criterion_source": item.get("source"),
            "applicability": applicability,
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
        missing_metadata = [
            field
            for field, value in (
                ("criterion identity", item.get("id")),
                ("criterion source type", item.get("source_type")),
                ("criterion source", item.get("source")),
            )
            if not isinstance(value, str) or not value.strip()
        ]
        if missing_metadata and not configuration_reason:
            configuration_reason = (
                "Criterion configuration lacks explicit "
                + ", ".join(missing_metadata)
                + "."
            )
        if (
            raw_applicability is not None
            and not isinstance(raw_applicability, Mapping)
        ):
            configuration_reason = (
                "Criterion applicability is not structured evidence."
            )
        configuration_status = _upper_text(
            item.get("configuration_status")
        )
        if configuration_status not in {
            "",
            "READY",
            "NOT APPLICABLE",
            "NOT ASSESSED",
        }:
            configuration_reason = (
                "Criterion configuration status is invalid."
            )
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
            matched_names.update(
                name
                for name, context in contexts.items()
                if context["combination"] == required
            )
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
        if None in response_ids:
            matched_names.update(candidates)
            base.update(
                status="NOT ASSESSED",
                case=", ".join(candidates),
                matched_responses=candidates,
                response_provenance=[
                    {
                        "response": name,
                        "response_id": contexts[name]["response_id"],
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
                    f"The {required} combination has no explicit current "
                    "response identity; applicability cannot be correlated."
                ),
            )
            criterion_results.append(base)
            continue
        if len(response_ids) != 1:
            matched_names.update(candidates)
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
        if (
            scoped_response_ids
            and response_ids != scoped_response_ids
        ):
            matched_names.update(candidates)
            base.update(
                status="NOT ASSESSED",
                case=", ".join(candidates),
                matched_responses=candidates,
                response_provenance=[
                    {
                        "response": name,
                        "response_id": contexts[name]["response_id"],
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
                    f"The current {required} response identity does not "
                    "match the table-wide structured mapping scope. No "
                    "acceptance verdict was issued."
                ),
            )
            criterion_results.append(base)
            continue

        response_id = next(iter(response_ids))
        if mapping_scope:
            scoped_identity = [
                context
                for context in mapping_scope
                if context["response_id"] == response_id
            ]
            if len(scoped_identity) != 1:
                matched_names.update(candidates)
                base.update(
                    status="NOT ASSESSED",
                    case=", ".join(candidates),
                    matched_responses=candidates,
                    reason=(
                        f"The current {required} response identity "
                        f"{response_id!r} is not represented exactly once in "
                        "the table-wide structured mapping scope."
                    ),
                )
                criterion_results.append(base)
                continue
            if scoped_identity[0]["combination"] != required:
                matched_names.update(candidates)
                base.update(
                    status="NOT ASSESSED",
                    case=", ".join(candidates),
                    matched_responses=candidates,
                    response_provenance=[scoped_identity[0]],
                    reason=(
                        f"The table-wide mapping for response identity "
                        f"{response_id!r} designates "
                        f"{scoped_identity[0]['combination']}, not the "
                        f"required {required} combination."
                    ),
                )
                criterion_results.append(base)
                continue
        aliases = [
            name
            for name, context in contexts.items()
            if context["response_id"] == response_id
        ]
        reference_context = contexts[candidates[0]]
        alias_conflicts = []
        for alias in aliases:
            context = contexts[alias]
            fields = []
            if context["combination"] != required:
                fields.append("SLS combination")
            if context["duration"] != reference_context["duration"]:
                fields.append("duration state")
            if context["provenance"] != reference_context["provenance"]:
                fields.append("mapping provenance")
            if not _evidence_values_equal(
                context["solver_provenance"],
                reference_context["solver_provenance"],
            ):
                fields.append("solver provenance")
            if fields:
                alias_conflicts.append(
                    f"{alias} ({', '.join(fields)})"
                )
        if alias_conflicts:
            matched_names.update(aliases)
            base.update(
                status="NOT ASSESSED",
                case=", ".join(aliases),
                matched_responses=aliases,
                response_provenance=[
                    {
                        "response": name,
                        "response_id": contexts[name]["response_id"],
                        "combination": contexts[name]["combination"],
                        "duration": contexts[name]["duration"],
                        "mapping": contexts[name]["provenance"],
                    }
                    for name in aliases
                ],
                solver_provenance=[
                    {
                        "response": name,
                        "solver": contexts[name]["solver_provenance"],
                    }
                    for name in aliases
                ],
                reason=(
                    f"Response labels sharing identity {response_id!r} have "
                    "conflicting structured context: "
                    f"{'; '.join(alias_conflicts)}. No acceptance verdict was "
                    "issued."
                ),
            )
            criterion_results.append(base)
            continue

        matched_names.update(aliases)
        base["matched_responses"] = aliases
        base["response_duration"] = contexts[candidates[0]]["duration"]
        base["response_provenance"] = contexts[candidates[0]]["provenance"]
        base["solver_provenance"] = contexts[candidates[0]][
            "solver_provenance"
        ]
        candidate_dispositions = []
        for name in candidates:
            disposition = disposition_map.get(name)
            if disposition is None:
                continue
            if not isinstance(disposition, Mapping):
                disposition = {
                    "status": "NOT ASSESSED",
                    "reason": (
                        "Solver disposition is not structured evidence."
                    ),
                }
            candidate_dispositions.append((name, disposition))
        blocking = [
            (name, disposition)
            for name, disposition in candidate_dispositions
            if _upper_text(disposition.get("status"))
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
            decompression = {}
            invalid_evidence = {}
            for name in candidates:
                response = cases.get(name)
                evidence, evidence_issues = (
                    _validated_decompression_evidence(
                        (
                            response.get("decompression")
                            if isinstance(response, Mapping)
                            else None
                        ),
                        fallback_solver_provenance=contexts[name][
                            "solver_provenance"
                        ],
                    )
                )
                if evidence_issues:
                    invalid_evidence[name] = evidence_issues
                    continue
                decompression[name] = evidence

            if invalid_evidence:
                issues = [
                    f"{name} ({'; '.join(evidence_issues)})"
                    for name, evidence_issues in invalid_evidence.items()
                ]
                base.update(
                    status="NOT ASSESSED",
                    case=", ".join(candidates),
                    solver_provenance=[
                        {
                            "response": name,
                            "solver": (
                                decompression.get(name, {}).get(
                                    "solver_provenance"
                                )
                                or contexts[name]["solver_provenance"]
                            ),
                        }
                        for name in candidates
                    ],
                    reason=(
                        "Decompression evidence is incomplete for "
                        f"{'; '.join(issues)}. "
                        "Every response label matched to the required "
                        f"{required} combination must provide explicit "
                        "concrete-stress evidence before a verdict is issued."
                    ),
                )
                criterion_results.append(base)
                continue

            name = candidates[0]
            evidence = decompression[name]
            conflicts = []
            for other_name in candidates[1:]:
                other = decompression[other_name]
                fields = _decompression_evidence_conflicts(
                    evidence,
                    other,
                )
                if fields:
                    conflicts.append(
                        f"{other_name} ({', '.join(fields)})"
                    )
            if conflicts:
                base.update(
                    status="NOT ASSESSED",
                    case=", ".join(candidates),
                    solver_provenance=[
                        {
                            "response": candidate,
                            "solver": decompression[candidate].get(
                                "solver_provenance"
                            ),
                        }
                        for candidate in candidates
                    ],
                    reason=(
                        "Response labels sharing the required "
                        f"{required} state provide inconsistent "
                        "decompression evidence: "
                        f"{'; '.join(conflicts)}. No acceptance verdict was "
                        "issued."
                    ),
                )
                criterion_results.append(base)
                continue

            base.update(
                status=evidence["status"],
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

    _bind_accepted_criterion_results(
        criterion_results,
        cases,
        contexts,
        mapping_scope,
    )
    informational = [name for name in cases if name not in matched_names]
    outcome = _crack_aggregate_fields(criterion_results)
    outcome.update({
        "criteria": criterion_results,
        "response_contexts": contexts,
        "response_mapping_scope": mapping_scope,
        "informational_responses": informational,
    })
    return outcome


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
