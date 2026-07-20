"""Shared result-presentation helpers for the Streamlit UI and PDF report.

The functions in this module derive display-only assessment state and QA tables
from an already-computed analysis payload. They do not alter or repeat the
engineering solvers.
"""

from __future__ import annotations

import math

import viz

_MM = 1000.0


def plastic_uls_assessment(pl):
    """Return the semantic ULS status for a plastic M-M result.

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
        detail = ("One or more neutral-axis sweep points did not converge; "
                  "the displayed values are diagnostic only")
    elif not checked:
        status = "NOT ASSESSED"
        detail = ("Capacity-only run; enable the applied-moment utilisation "
                  "check to issue a verdict")
    elif not complete or util is None:
        status = "NOT ASSESSED"
        detail = ("The neutral-axis sweep is an open arc; a closed 360 degree "
                  "envelope is required for an applied-action verdict")
    elif not math.isfinite(util):
        status = "FAIL"
        detail = "The applied action has no finite capacity intersection"
    elif viz.util_ok(util):
        status = "PASS"
        detail = "Applied-action utilisation does not exceed the 100 % ULS limit"
    else:
        status = "FAIL"
        detail = "Applied-action utilisation exceeds the 100 % ULS limit"

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


def plastic_state_evidence(inp, point):
    """Build concrete-corner and reinforcement evidence at one plastic state.

    Strain and stress are tension-positive. Reinforcement force is derived only
    for presentation from the solver-consistent material law:
    ``F [kN] = sigma [MPa] * A [mm2] / 1000``.
    """
    hp = viz.plastic_halfplane(
        point["V"], point["na_x"], point["na_y"],
    )
    a, b, c = hp
    kappa = float(point["kappa"])

    concrete_rows = []
    point_no = 0
    rings = [("Outer", inp.get("outer") or [])]
    rings.extend(
        (f"Hole {index}", ring)
        for index, ring in enumerate(inp.get("holes") or [], start=1)
    )
    concrete = inp.get("concrete")
    for ring_name, ring in rings:
        for ring_point_no, vertex in enumerate(ring, start=1):
            point_no += 1
            x, y = float(vertex[0]), float(vertex[1])
            strain = -kappa * (a * x + b * y + c)
            stress = concrete.stress(strain, design=True) if concrete is not None else 0.0
            concrete_rows.append({
                "point_no": point_no,
                "ring": ring_name,
                "ring_point_no": ring_point_no,
                "x_mm": x * _MM,
                "y_mm": y * _MM,
                "strain_permille": strain * _MM,
                "stress_mpa": stress,
            })

    element_rows = []

    def append_elements(points, element_type, material, prestrain=0.0):
        if material is None:
            return
        for element_no, element in enumerate(points or [], start=1):
            x, y = float(element[0]), float(element[1])
            area = float(element[2]) if len(element) > 2 else 0.0
            strain = prestrain - kappa * (a * x + b * y + c)
            stress = material.stress(strain, design=True)
            state = ("Tension" if strain > 1e-12 else
                     "Compression" if strain < -1e-12 else "Neutral")
            element_rows.append({
                "element_type": element_type,
                "element_no": element_no,
                "element_id": f"{element_type.lower()} {element_no}",
                "state": state,
                "x_mm": x * _MM,
                "y_mm": y * _MM,
                "area_mm2": area,
                "strain_permille": strain * _MM,
                "stress_mpa": stress,
                "force_kn": stress * area / _MM,
            })

    append_elements(inp.get("bars"), "Bar", inp.get("steel"))
    prestress = inp.get("prestress")
    append_elements(
        inp.get("tendons"),
        "Tendon",
        prestress,
        float(getattr(prestress, "IS", 0.0)) if prestress is not None else 0.0,
    )
    return {
        "halfplane": hp,
        "concrete": concrete_rows,
        "elements": element_rows,
    }


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
