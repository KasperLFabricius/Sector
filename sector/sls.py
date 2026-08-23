"""Headless serviceability output and result-table helpers.

The elastic solver returns numerical section states. This module exposes those
states as reproducible calculation outputs. Long-term and short-term ordinary
crack widths may each be compared with their own positive user criterion from
Analysis settings; no exposure, durability, decompression or load-combination
criterion is inferred.
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence

from .sls_identity import (
    HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY as HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY,
    LONG_TERM_PERMITTED_CRACK_WIDTH_KEY as LONG_TERM_PERMITTED_CRACK_WIDTH_KEY,
    LONG_TERM_PERMITTED_CRACK_WIDTH_SOURCE,
    SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY as SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY,
    SHORT_TERM_PERMITTED_CRACK_WIDTH_SOURCE,
)

CRACK_NOT_REQUESTED = "NOT REQUESTED"
CRACK_NOT_ASSESSED = "NOT ASSESSED"
CRACK_CALCULATED_UNASSESSED = "CALCULATED - NO LIMIT COMPARISON"
CRACK_WITHIN_USER_LIMIT = "WITHIN USER-SPECIFIED LIMIT"
CRACK_EXCEEDS_USER_LIMIT = "EXCEEDS USER-SPECIFIED LIMIT"
CRACK_COMPARISON_EQUATION = "w_k / w_k,criterion"


def _is_boolean_scalar(value: object) -> bool:
    value_type = type(value)
    return isinstance(value, bool) or (
        value_type.__module__.partition(".")[0] in {"numpy", "pandas"}
        and value_type.__name__.lower().rstrip("_") in {"bool", "boolean"}
    )


def crack_criterion_source(duration: str) -> str:
    """Return the stable provenance label for one duration-specific setting."""

    if duration == "long_term":
        return LONG_TERM_PERMITTED_CRACK_WIDTH_SOURCE
    if duration == "short_term":
        return SHORT_TERM_PERMITTED_CRACK_WIDTH_SOURCE
    raise ValueError("duration must be exactly 'long_term' or 'short_term'")


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


def stress_outputs(
    total_stress: Sequence[float],
    *,
    n_bars: int,
    max_concrete_compression: float,
    valid: bool,
    bar_ids: Sequence[str] | None = None,
    tendon_ids: Sequence[str] | None = None,
) -> dict:
    """Return governing concrete, reinforcement and tendon stresses.

    Compression is reported as a positive magnitude. Reinforcement and tendon
    results report the maximum tensile stress. These are output quantities, not
    acceptance checks.
    """
    total = [float(v) for v in total_stress]
    mild = total[:n_bars]
    prestress = total[n_bars:]

    def _governing(values: Sequence[float]):
        if not values:
            return None, None
        tension = [max(float(value), 0.0) for value in values]
        index = max(range(len(values)), key=lambda j: tension[j])
        return tension[index], index + 1

    mild_value, mild_no = _governing(mild)
    pre_value, pre_no = _governing(prestress)
    state = "CALCULATED" if valid else "INVALID"
    return {
        "concrete": {
            "value": (
                max(float(max_concrete_compression), 0.0)
                if valid else None
            ),
            "quantity": "maximum concrete compression",
            "unit": "MPa",
            "calculation_state": state,
        },
        "reinforcement": {
            "value": mild_value if valid else None,
            "quantity": "maximum reinforcement tension",
            "unit": "MPa",
            "governing": (
                _element_id(bar_ids, mild_no - 1, f"bar {mild_no}")
                if mild_no is not None else None
            ),
            "element_no": mild_no,
            "calculation_state": state if mild else "NOT APPLICABLE",
        },
        "prestress": {
            "value": pre_value if valid else None,
            "quantity": "maximum tendon tension",
            "unit": "MPa",
            "governing": (
                _element_id(tendon_ids, pre_no - 1, f"tendon {pre_no}")
                if pre_no is not None else None
            ),
            "element_no": pre_no,
            "calculation_state": state if prestress else "NOT APPLICABLE",
        },
    }


def _ordinary_criterion(value: object) -> tuple[float | None, str | None]:
    """Return a finite non-negative criterion or a fail-closed reason."""

    if value is None:
        return 0.0, None
    if _is_boolean_scalar(value):
        return None, (
            "The crack-width criterion must be a non-negative finite number."
        )
    if isinstance(value, (str, bytes)):
        return None, (
            "The crack-width criterion must be a non-negative finite number."
        )
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None, (
            "The crack-width criterion must be a non-negative finite number."
        )
    if not math.isfinite(number) or number < 0.0:
        return None, (
            "The crack-width criterion must be a non-negative finite number."
        )
    return number, None


def _finite_crack_value(value: object) -> float | None:
    """Return one non-negative finite width, otherwise ``None``."""

    if _is_boolean_scalar(value):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0.0 else None


def assess_crack_output(
    output: Mapping,
    *,
    duration: str,
    requested: bool,
    criterion_mm: object = 0.0,
    criterion_source: str | None = None,
) -> dict:
    """Apply one duration-matched, user-owned ordinary crack comparison.

    The returned ``calculation_state`` is the single authoritative public state;
    no parallel verdict is emitted. Existing crack identity fields are retained
    and the comparison is deliberately local to the crack-width family.
    """

    if duration not in {"long_term", "short_term"}:
        raise ValueError("duration must be exactly 'long_term' or 'short_term'")
    criterion, criterion_error = _ordinary_criterion(criterion_mm)
    source = (
        str(criterion_source).strip()
        if criterion_mm is not None and criterion_source is not None
        else None
    )
    value = _finite_crack_value(output.get("value"))
    result = {
        "duration": duration,
        "value": value,
        "case": output.get("case"),
        "governing": output.get("governing"),
        "unit": output.get("unit") or "mm",
        "calculation_state": CRACK_NOT_ASSESSED,
        "criterion_mm": criterion,
        "ratio": None,
        "criterion_source": source,
        "reason": None,
        "comparison_equation": None,
    }

    if not requested:
        result.update(
            value=None,
            case=None,
            governing=None,
            calculation_state=CRACK_NOT_REQUESTED,
            reason="Crack-width calculation was not requested for this Elastic case.",
        )
        return result

    if criterion_error is not None:
        result.update(calculation_state=CRACK_NOT_ASSESSED, reason=criterion_error)
        return result

    if criterion is not None and criterion > 0.0 and not source:
        result.update(
            calculation_state=CRACK_NOT_ASSESSED,
            reason=(
                "The user-specified crack-width criterion requires a nonblank "
                "criterion source."
            ),
        )
        return result

    if value is None:
        retained_reason = str(output.get("reason") or "").strip()
        result.update(
            calculation_state=CRACK_NOT_ASSESSED,
            reason=(
                retained_reason
                or "No calculated crack width is available for assessment."
            ),
        )
        return result

    if criterion == 0.0:
        label = "Long-term" if duration == "long_term" else "Short-term"
        result.update(
            calculation_state=CRACK_CALCULATED_UNASSESSED,
            reason=(
                f"The {label.lower()} permitted crack width is 0 mm; no "
                "comparison was requested."
            ),
        )
        return result

    if result["unit"] != "mm":
        result.update(
            calculation_state=CRACK_NOT_ASSESSED,
            reason=(
                "The calculated crack width must be retained in millimetres "
                "before comparison with the user-specified criterion."
            ),
        )
        return result

    ratio = value / criterion
    within = ratio <= 1.0
    result.update(
        calculation_state=(
            CRACK_WITHIN_USER_LIMIT if within else CRACK_EXCEEDS_USER_LIMIT
        ),
        ratio=ratio,
        reason=(
            "The calculated crack width is within the user-specified limit."
            if within
            else "The calculated crack width exceeds the user-specified limit."
        ),
        comparison_equation=CRACK_COMPARISON_EQUATION,
    )
    return result


def _case_result(value: object) -> tuple[object | None, str | None]:
    """Unwrap a result mapping or a CrackWidthEvaluation-like object."""

    if value is None:
        return None, None
    if isinstance(value, Mapping):
        if "wk" in value:
            return value, None
        if "status" in value and "result" in value:
            reason = str(value.get("reason") or "").strip() or None
            return value.get("result"), reason
        return value, None
    if hasattr(value, "status") and hasattr(value, "result"):
        reason = str(getattr(value, "reason", "") or "").strip() or None
        return getattr(value, "result", None), reason
    return value, None


def _result_field(value: object, key: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _duration_crack_output(
    cases: Mapping[str, object | None],
    *,
    duration: str,
    valid: bool,
    requested: bool,
    criterion_mm: object,
    criterion_source: str | None = None,
) -> dict:
    """Return one duration's largest width and optional comparison."""

    available: list[tuple[str, object]] = []
    unavailable_reasons: list[str] = []
    for name, value in cases.items():
        crack, reason = _case_result(value)
        if crack is None:
            if reason and reason not in unavailable_reasons:
                unavailable_reasons.append(reason)
            continue
        width = _finite_crack_value(_result_field(crack, "wk"))
        if width is None:
            if reason and reason not in unavailable_reasons:
                unavailable_reasons.append(reason)
            continue
        available.append((name, crack))

    if not valid:
        raw = {
            "value": None,
            "case": None,
            "governing": None,
            "unit": "mm",
            "reason": (
                "; ".join(unavailable_reasons)
                if unavailable_reasons
                else (
                    "The Elastic calculation is invalid; crack width is not "
                    "assessed."
                )
            ),
        }
    elif not available:
        raw = {
            "value": None,
            "case": None,
            "governing": None,
            "unit": "mm",
            "reason": (
                unavailable_reasons[0]
                if len(unavailable_reasons) == 1
                else (
                    "; ".join(unavailable_reasons)
                    if unavailable_reasons
                    else "No calculated crack width is available for assessment."
                )
            ),
        }
    else:
        name, governing = max(
            available,
            key=lambda item: float(_result_field(item[1], "wk", 0.0)),
        )
        governing_id = _result_field(governing, "element_id")
        if not governing_id:
            bar_index = _result_field(governing, "gov_bar", "-")
            if not isinstance(governing, Mapping) and isinstance(bar_index, int):
                bar_index += 1
            governing_id = f"element {bar_index}"
        raw = {
            "value": float(_result_field(governing, "wk", 0.0)),
            "case": name,
            "governing": governing_id,
            "unit": "mm",
            "reason": None,
        }
    return assess_crack_output(
        raw,
        duration=duration,
        requested=requested,
        criterion_mm=criterion_mm,
        criterion_source=criterion_source,
    )


def crack_outputs(
    long_term_cases: Mapping[str, object | None],
    short_term_cases: Mapping[str, object | None],
    *,
    valid: bool,
    requested: bool = True,
    long_term_criterion_mm: object = 0.0,
    short_term_criterion_mm: object = 0.0,
    long_term_criterion_source: str | None = None,
    short_term_criterion_source: str | None = None,
) -> dict:
    """Return independent long-term and short-term crack assessments.

    Each mapping may contain an existing flattened crack mapping or a
    ``CrackWidthEvaluation``-like object. The latter keeps the exact reason from
    :func:`sector.serviceability.evaluate_crack_width` when no width is
    available. Candidates never compete across durations.
    """

    return {
        "long_term": _duration_crack_output(
            long_term_cases,
            duration="long_term",
            valid=valid,
            requested=requested,
            criterion_mm=long_term_criterion_mm,
            criterion_source=long_term_criterion_source,
        ),
        "short_term": _duration_crack_output(
            short_term_cases,
            duration="short_term",
            valid=valid,
            requested=requested,
            criterion_mm=short_term_criterion_mm,
            criterion_source=short_term_criterion_source,
        ),
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
            "modulus_mpa": modulus,
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
