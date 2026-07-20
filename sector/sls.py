"""Headless serviceability assessment and result-evidence helpers.

The elastic solver returns numerical section states.  This module turns those
states into explicit, auditable acceptance checks and element/corner tables
without depending on Streamlit or the PDF renderer.
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence


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
    fyk: float,
    fpk: float | None,
    concrete_limit_pct: float,
    reinforcement_limit_pct: float,
    prestress_limit_pct: float,
    valid: bool,
) -> dict:
    """Build separate concrete, mild-steel and tendon stress assessments."""
    total = [float(v) for v in total_stress]
    mild = total[:n_bars]
    prestress = total[n_bars:]

    def _max_tension(values: Sequence[float]):
        if not values:
            return None, None
        i = max(range(len(values)), key=lambda j: values[j])
        return max(values[i], 0.0), i + 1

    mild_value, mild_no = _max_tension(mild)
    pre_value, pre_no = _max_tension(prestress)
    concrete = upper_limit_assessment(
        max(float(max_concrete_compression), 0.0),
        float(concrete_limit_pct) / 100.0 * float(fck),
        valid=valid,
    )
    reinforcement = upper_limit_assessment(
        mild_value,
        float(reinforcement_limit_pct) / 100.0 * float(fyk),
        valid=valid,
        applicable=bool(mild),
    )
    prestressing = upper_limit_assessment(
        pre_value,
        (float(prestress_limit_pct) / 100.0 * float(fpk)
         if fpk is not None else None),
        valid=valid,
        applicable=bool(prestress) and fpk is not None,
    )
    concrete.update(
        criterion=f"{float(concrete_limit_pct):g}% fck",
        governing="concrete compression",
    )
    reinforcement.update(
        criterion=f"{float(reinforcement_limit_pct):g}% fyk",
        governing=(f"bar {mild_no}" if mild_no is not None else None),
        element_no=mild_no,
    )
    prestressing.update(
        criterion=f"{float(prestress_limit_pct):g}% fpk",
        governing=(f"tendon {pre_no}" if pre_no is not None else None),
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
    es_mpa: float,
    ep_mpa: float | None,
) -> list[dict]:
    """Return a complete, explicitly typed SLS row for every bar and tendon."""
    rows: list[dict] = []
    elements = [
        ("Bar", i + 1, p, float(es_mpa))
        for i, p in enumerate(bars)
    ]
    tendon_modulus = float(ep_mpa) if ep_mpa is not None else float(es_mpa)
    elements.extend(
        ("Tendon", i + 1, p, tendon_modulus)
        for i, p in enumerate(tendons)
    )
    arrays = ([float(v) for v in total], [float(v) for v in long],
              [float(v) for v in dif], [float(v) for v in rst1])
    for i, (kind, number, point, modulus) in enumerate(elements):
        stress = arrays[0][i]
        rows.append({
            "element_type": kind,
            "element_no": number,
            "element_id": f"{kind.lower()} {number}",
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
