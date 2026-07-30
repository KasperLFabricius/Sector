"""Headless serviceability output and result-table helpers.

The elastic solver returns numerical section states. This module exposes those
states as reproducible calculation outputs without applying stress, crack-width,
exposure, durability, decompression or load-combination acceptance criteria.
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


def crack_outputs(
    cases: Mapping[str, Mapping | None],
    *,
    valid: bool,
) -> dict:
    """Return the largest calculated crack width across the supplied actions."""
    available = [(name, case) for name, case in cases.items() if case is not None]
    if not valid:
        return {
            "value": None,
            "case": None,
            "governing": None,
            "unit": "mm",
            "calculation_state": "INVALID",
        }
    if not available:
        return {
            "value": None,
            "case": None,
            "governing": None,
            "unit": "mm",
            "calculation_state": "NOT APPLICABLE",
        }
    name, governing = max(available, key=lambda item: float(item[1].get("wk", 0.0)))
    return {
        "value": float(governing.get("wk", 0.0)),
        "case": name,
        "governing": governing.get(
            "element_id", f"element {governing.get('gov_bar', '-')}"
        ),
        "unit": "mm",
        "calculation_state": "CALCULATED",
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
