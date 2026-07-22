"""Headless serviceability assessment and result-evidence helpers.

The elastic solver returns numerical section states.  This module turns those
states into explicit, auditable acceptance checks and element/corner tables
without depending on Streamlit or the PDF renderer.
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence


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
    total = [float(v) for v in total_stress]
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
    limit_mm: float,
    valid: bool,
) -> dict:
    """Assess the largest reported crack width across all enabled cases."""
    available = [(name, case) for name, case in cases.items() if case is not None]
    if not available:
        out = upper_limit_assessment(None, limit_mm, valid=valid, applicable=False)
        out.update(case=None, governing=None, criterion=f"{float(limit_mm):g} mm")
        return out
    name, governing = max(available, key=lambda item: float(item[1].get("wk", 0.0)))
    out = upper_limit_assessment(
        float(governing.get("wk", 0.0)), float(limit_mm), valid=valid,
    )
    out.update(
        case=name,
        governing=governing.get("element_id", f"element {governing.get('gov_bar', '-')}"),
        criterion=f"{float(limit_mm):g} mm",
    )
    return out


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
