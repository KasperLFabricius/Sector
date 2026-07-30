"""Attach and validate the PI-019 trace at the analysis/publication boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import case_analysis
from sector.calculation_trace import (
    TraceBundle,
    TraceValidationError,
    create_bundle,
    fingerprint_payload,
    trace_identity_token,
    validate_bundle,
)
from sector import trace_builders


TRACE_KEY = "calculation_trace"


def input_fingerprint(inp: Mapping[str, Any]) -> str:
    """Fingerprint the exact freshness signature used by the application."""

    if "signature" not in inp:
        raise TraceValidationError(
            "calculation traces require the current application input signature"
        )
    return fingerprint_payload(inp["signature"], omit_keys=())


def result_fingerprint(result: Mapping[str, Any]) -> str:
    """Fingerprint solver output while excluding its attached trace evidence."""

    return fingerprint_payload(result, omit_keys=(TRACE_KEY,))


def _context(
    family: str,
    case_id: Any,
    description: Any = "",
    *,
    named_case: bool = False,
) -> dict[str, str]:
    case_text = str(case_id)
    context = {
        "family": str(family),
        "case_id": case_text,
    }
    if named_case:
        # The readable slug is not injective (for example, ``A+B`` and ``A B``).
        # Carry the exact UTF-8 bytes as a private ID component so every valid
        # case name has a stable collision-free calculation namespace.  Trace
        # builders omit private context keys from the published record.
        context["_case_identity"] = trace_identity_token(case_text)
    if str(description or "").strip():
        context["description"] = str(description).strip()
    return context


def _coverage_count(
    calculations: Sequence[Any],
    coverage_ids: set[str],
) -> int:
    return sum(
        calculation.coverage_id in coverage_ids
        for calculation in calculations
    )


def _record_value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _require_coverage_count(
    calculations: Sequence[Any],
    *,
    label: str,
    coverage_ids: set[str],
    expected: int,
) -> None:
    actual = _coverage_count(calculations, coverage_ids)
    if actual != expected:
        raise TraceValidationError(
            f"{label} trace coverage is incomplete: expected {expected}, "
            f"found {actual}"
        )


def _require_coverage_minimum(
    calculations: Sequence[Any],
    *,
    label: str,
    coverage_ids: set[str],
    minimum: int,
) -> None:
    actual = _coverage_count(calculations, coverage_ids)
    if actual < minimum:
        raise TraceValidationError(
            f"{label} trace coverage is incomplete: expected at least "
            f"{minimum}, found {actual}"
        )


def _completed_check_indices(payload: Mapping[str, Any]) -> list[str]:
    return [
        str(index)
        for index, check in enumerate(payload.get("checks") or (), start=1)
        if isinstance(check, Mapping)
        and str(check.get("status") or "").upper() in {"PASS", "FAIL"}
    ]


def _require_indexed_check_coverage(
    calculations: Sequence[Any],
    *,
    payload: Mapping[str, Any],
    label: str,
    coverage_ids: set[str],
) -> None:
    expected = _completed_check_indices(payload)
    if (
        str(payload.get("status") or "").upper() in {"PASS", "FAIL"}
        and not expected
    ):
        raise TraceValidationError(
            f"{label} declares a completed result without a completed check"
        )
    actual = [
        dict(calculation.context).get("check")
        for calculation in calculations
        if calculation.coverage_id in coverage_ids
    ]
    if sorted(actual) != sorted(expected):
        raise TraceValidationError(
            f"{label} trace coverage is incomplete: expected checks "
            f"{', '.join(expected) or 'none'}, found "
            f"{', '.join(actual) or 'none'}"
        )


def _shear_records(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Mirror the solver result's retained direction/face record structure."""

    directions = payload.get("directions")
    records: list[Mapping[str, Any]] = []
    if isinstance(directions, Mapping):
        direction_values = [
            item for item in directions.values() if isinstance(item, Mapping)
        ]
    else:
        direction_values = [payload]
    for direction in direction_values:
        candidates = list(direction.get("face_candidates") or ())
        if candidates:
            records.extend(
                candidate["shear"]
                for candidate in candidates
                if isinstance(candidate, Mapping)
                and isinstance(candidate.get("shear"), Mapping)
            )
        else:
            records.append(direction)
    return records


def _combined_expected_counts(
    combined: Mapping[str, Any],
) -> tuple[int, int, int]:
    if combined.get("biaxial") and isinstance(
        combined.get("directions"), Mapping
    ):
        counts = [
            _combined_expected_counts(direction)
            for direction in combined["directions"].values()
            if isinstance(direction, Mapping)
        ]
        if counts:
            return tuple(sum(items) for items in zip(*counts))
        return (0, 0, 0)
    if not combined.get("valid"):
        return (0, 0, 0)
    transverse = combined.get("transverse")
    ct014 = int(
        isinstance(transverse, Mapping) and bool(transverse.get("valid"))
    )
    candidates = list(combined.get("longitudinal_candidates") or ())
    if not candidates:
        candidates = [
            item
            for item in (
                combined.get("longitudinal"),
                combined.get("chord_off"),
            )
            if isinstance(item, Mapping)
        ]
    ct015 = sum(
        isinstance(item, Mapping) and bool(item.get("valid", True))
        for item in candidates
    )
    ct016 = int(combined.get("dkna_sum") is not None)
    return (ct014, ct015, ct016)


def _require_case_trace_coverage(
    result: Mapping[str, Any],
    calculations: Sequence[Any],
) -> None:
    """Fail closed unless every completed case-level family is represented."""

    plastic = result.get("plastic")
    if isinstance(plastic, Mapping):
        _require_coverage_minimum(
            calculations,
            label="plastic section capacity",
            coverage_ids={"CT-002"},
            minimum=1,
        )

    elastic = result.get("elastic")
    if isinstance(elastic, Mapping):
        _require_coverage_minimum(
            calculations,
            label="elastic section equilibrium",
            coverage_ids={"CT-005"},
            minimum=1,
        )
        expected_cracks = sum(
            isinstance(elastic.get(key), Mapping)
            for key in (
                "crack",
                "crack_short",
                "crack_coarse",
                "crack_short_coarse",
            )
        )
        _require_coverage_count(
            calculations,
            label="crack-width calculations",
            coverage_ids={"CT-006", "CT-007", "CT-008"},
            expected=expected_cracks,
        )

    shear = result.get("shear")
    if isinstance(shear, Mapping):
        retained = _shear_records(shear)
        valid = [
            record
            for record in retained
            if isinstance(record.get("res"), Mapping)
            and bool(record["res"].get("valid"))
        ]
        _require_coverage_count(
            calculations,
            label="shear without links",
            coverage_ids={"CT-009", "CT-010"},
            expected=len(valid),
        )
        valid_links = [
            record
            for record in valid
            if isinstance(record.get("links"), Mapping)
            and isinstance(record["links"].get("res"), Mapping)
            and bool(record["links"]["res"].get("valid"))
        ]
        _require_coverage_count(
            calculations,
            label="shear with links",
            coverage_ids={"CT-011", "CT-012"},
            expected=len(valid_links),
        )

    torsion = result.get("torsion")
    if isinstance(torsion, Mapping) and torsion.get("valid"):
        tubes = list(torsion.get("subtubes") or ())
        if not tubes and isinstance(torsion.get("primary"), Mapping):
            tubes = [torsion["primary"]]
        expected_torsion = sum(
            isinstance(tube, Mapping) and bool(tube.get("valid"))
            for tube in tubes
        )
        expected_torsion += int(
            isinstance(torsion.get("min_reinf"), Mapping)
            and bool(torsion["min_reinf"].get("applicable"))
        )
        _require_coverage_count(
            calculations,
            label="torsion calculations",
            coverage_ids={"CT-013"},
            expected=expected_torsion,
        )

    expected_014 = int(
        isinstance(torsion, Mapping)
        and isinstance(torsion.get("interaction"), Mapping)
        and bool(torsion["interaction"].get("valid"))
    )
    expected_015 = 0
    expected_016 = 0
    combined = result.get("combined")
    if isinstance(combined, Mapping):
        add_014, expected_015, expected_016 = _combined_expected_counts(
            combined
        )
        expected_014 += add_014
    for coverage_id, label, expected in (
        ("CT-014", "combined transverse interaction", expected_014),
        ("CT-015", "combined longitudinal chord", expected_015),
        ("CT-016", "Danish combined interaction", expected_016),
    ):
        _require_coverage_count(
            calculations,
            label=label,
            coverage_ids={coverage_id},
            expected=expected,
        )

    minimum = result.get("minimum_reinforcement")
    if isinstance(minimum, Mapping):
        _require_indexed_check_coverage(
            calculations,
            payload=minimum,
            label="minimum longitudinal reinforcement",
            coverage_ids={"CT-017", "CT-018"},
        )

    transverse = result.get("transverse_reinforcement")
    if isinstance(transverse, Mapping):
        _require_indexed_check_coverage(
            calculations,
            payload=transverse,
            label="transverse detailing",
            coverage_ids={"CT-019"},
        )


def _require_global_trace_coverage(
    result: Mapping[str, Any],
    calculations: Sequence[Any],
) -> None:
    """Fail closed unless every completed global family is represented."""

    spacing = result.get("clear_spacing")
    if isinstance(spacing, Mapping):
        expected_pairs = [
            str(index)
            for index, pair in enumerate(spacing.get("pairs") or (), start=1)
            if isinstance(pair, Mapping)
        ]
        actual_pairs = [
            dict(calculation.context).get("pair")
            for calculation in calculations
            if calculation.coverage_id == "CT-020"
        ]
        if sorted(actual_pairs) != sorted(expected_pairs):
            raise TraceValidationError(
                "clear-spacing trace coverage is incomplete: expected pairs "
                f"{', '.join(expected_pairs) or 'none'}, found "
                f"{', '.join(actual_pairs) or 'none'}"
            )

    fatigue = result.get("fatigue")
    if isinstance(fatigue, Mapping) and not fatigue.get("errors"):
        expected_steel = 0
        expected_concrete = 0
        for spectrum in fatigue.get("spectra") or ():
            expected_steel += sum(
                bool(_record_value(record, "bins"))
                for record in _record_value(
                    spectrum, "reinforcement", ()
                ) or ()
            )
            expected_concrete += sum(
                bool(_record_value(record, "bins"))
                for record in _record_value(spectrum, "concrete", ()) or ()
            )
        _require_coverage_count(
            calculations,
            label="reinforcement fatigue",
            coverage_ids={"CT-021"},
            expected=expected_steel,
        )
        _require_coverage_count(
            calculations,
            label="concrete fatigue",
            coverage_ids={"CT-022", "CT-023", "CT-024"},
            expected=expected_concrete,
        )

    bridge = result.get("bridge")
    if isinstance(bridge, Mapping) and not bridge.get("errors"):
        payload = bridge.get("calculations")
        if isinstance(payload, Mapping):
            for key, coverage_id, label in (
                ("brittle_method_b", "CT-025", "bridge Method B"),
                ("box_walls", "CT-026", "bridge box-wall interaction"),
                (
                    "minimum_crack_reinforcement",
                    "CT-027",
                    "bridge minimum crack reinforcement",
                ),
            ):
                family = payload.get(key)
                expected = (
                    sum(
                        isinstance(row, Mapping)
                        for row in family.get("rows") or ()
                    )
                    if isinstance(family, Mapping)
                    else 0
                )
                _require_coverage_count(
                    calculations,
                    label=label,
                    coverage_ids={coverage_id},
                    expected=expected,
                )


def build_bundle(inp: Mapping[str, Any], result: Mapping[str, Any]) -> TraceBundle:
    """Build one immutable trace bundle from current inputs and solver results."""

    calculations = []
    calculations.extend(
        trace_builders.material_calculations(
            inp,
            context=_context("global", "materials"),
        )
    )

    named = "plastic_cases" in result or "elastic_cases" in result
    if named:
        for entry in result.get("plastic_cases") or ():
            if not isinstance(entry, Mapping):
                continue
            action = entry.get("actions")
            case_result = entry.get("results")
            if not isinstance(action, Mapping) or not isinstance(
                case_result, Mapping
            ):
                continue
            case_inp = case_analysis.plastic_case_input(inp, action)
            case_context = _context(
                "plastic",
                entry.get("name") or action.get("name") or "case",
                entry.get("description"),
                named_case=True,
            )
            case_calculations = trace_builders.case_calculations(
                case_inp,
                case_result,
                context=case_context,
            )
            _require_case_trace_coverage(case_result, case_calculations)
            calculations.extend(case_calculations)
        for entry in result.get("elastic_cases") or ():
            if not isinstance(entry, Mapping):
                continue
            action = entry.get("actions")
            case_result = entry.get("results")
            if not isinstance(action, Mapping) or not isinstance(
                case_result, Mapping
            ):
                continue
            case_inp = case_analysis.elastic_case_input(inp, action)
            case_context = _context(
                "elastic",
                entry.get("name") or action.get("name") or "case",
                entry.get("description"),
                named_case=True,
            )
            case_calculations = trace_builders.case_calculations(
                case_inp,
                case_result,
                context=case_context,
            )
            _require_case_trace_coverage(case_result, case_calculations)
            calculations.extend(case_calculations)
    else:
        case_calculations = trace_builders.case_calculations(
            inp,
            result,
            context=_context("direct", "direct"),
        )
        _require_case_trace_coverage(result, case_calculations)
        calculations.extend(case_calculations)

    global_calculations = trace_builders.global_calculations(
        inp,
        result,
        context=_context("global", "global"),
    )
    _require_global_trace_coverage(result, global_calculations)
    calculations.extend(global_calculations)
    if not calculations:
        raise TraceValidationError(
            "the solver result contains no calculation that can be traced"
        )
    return create_bundle(
        input_sha256=input_fingerprint(inp),
        result_sha256=result_fingerprint(result),
        calculations=calculations,
    )


def attach_trace(
    inp: Mapping[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Attach current trace evidence when the current signature is available."""

    if not result or "signature" not in inp:
        return result
    try:
        bundle = build_bundle(inp, result)
    except TraceValidationError as exc:
        # An active supported calculation must never be silently published with
        # an incomplete trace.  Invalid bridge/fatigue input errors are not
        # completed calculations and therefore do not require a bundle.
        completed = any(
            key in result
            for key in (
                "plastic",
                "elastic",
                "shear",
                "torsion",
                "combined",
                "minimum_reinforcement",
                "transverse_reinforcement",
                "clear_spacing",
                "plastic_cases",
                "elastic_cases",
            )
        )
        completed = completed or bool(
            (result.get("fatigue") or {}).get("spectra")
            if isinstance(result.get("fatigue"), Mapping)
            else False
        )
        completed = completed or bool(
            (result.get("bridge") or {}).get("calculations")
            if isinstance(result.get("bridge"), Mapping)
            else False
        )
        if completed:
            raise TraceValidationError(
                f"completed solver output cannot be published: {exc}"
            ) from exc
        return result
    result[TRACE_KEY] = bundle.to_dict()
    return result


def validated_bundle(
    inp: Mapping[str, Any],
    result: Mapping[str, Any],
) -> TraceBundle:
    """Return current, untampered trace evidence or fail closed."""

    payload = result.get(TRACE_KEY)
    if not isinstance(payload, Mapping):
        raise TraceValidationError(
            "current solver output has no calculation-trace bundle"
        )
    return validate_bundle(
        payload,
        expected_input_sha256=input_fingerprint(inp),
        expected_result_sha256=result_fingerprint(result),
    )
