"""Independent scalar oracle for PR-06 multidirectional interaction QA.

The module deliberately imports no Sector production package.  It implements
only the frozen closed-form relationships used by the PR-06 regression matrix.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from numbers import Real


@dataclass(frozen=True)
class InteractionPoint:
    x: float
    y: float
    utilisation: float
    passes: bool


def finite_real(value, name: str) -> float:
    """Return a finite scalar while rejecting Boolean and text coercion."""

    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def project_power_sum(
    x,
    resistance_x,
    y,
    resistance_y,
    exponent,
) -> float:
    """Independent approved-project power-sum utilisation."""

    x_value = abs(finite_real(x, "x"))
    y_value = abs(finite_real(y, "y"))
    rx = finite_real(resistance_x, "resistance_x")
    ry = finite_real(resistance_y, "resistance_y")
    p = finite_real(exponent, "exponent")
    if rx <= 0.0 or ry <= 0.0 or p <= 0.0:
        raise ValueError("resistances and exponent must be positive")
    return (x_value / rx) ** p + (y_value / ry) ** p


def power_sum_point(
    x,
    resistance_x,
    y,
    resistance_y,
    exponent,
    *,
    tolerance: float = 1.0e-9,
) -> InteractionPoint:
    utilisation = project_power_sum(
        x,
        resistance_x,
        y,
        resistance_y,
        exponent,
    )
    return InteractionPoint(
        x=float(x),
        y=float(y),
        utilisation=utilisation,
        passes=utilisation <= 1.0 + tolerance,
    )


def crack_dk_2004(
    angle_deg,
    spacing_x_mm,
    spacing_y_mm,
    strain_x,
    strain_y,
) -> tuple[float, float, float]:
    """EN 1992-1-1:2004 7.15 plus DK NA 7.101 strain sum."""

    angle = math.radians(finite_real(angle_deg, "angle"))
    sx = finite_real(spacing_x_mm, "spacing_x")
    sy = finite_real(spacing_y_mm, "spacing_y")
    ex = finite_real(strain_x, "strain_x")
    ey = finite_real(strain_y, "strain_y")
    if sx <= 0.0 or sy <= 0.0 or ex < 0.0 or ey < 0.0:
        raise ValueError("spacings must be positive and strains non-negative")
    spacing = 1.0 / (math.cos(angle) / sx + math.sin(angle) / sy)
    strain = ex + ey
    return spacing, strain, spacing * strain


def crack_en_2023_g5(
    angle_deg,
    spacing_x_mm,
    spacing_y_mm,
    strain_x,
    strain_y,
    transverse_strain,
) -> tuple[float, float, float]:
    """EN 1992-1-1:2023 G.22-G.23 scalar combination."""

    angle = math.radians(finite_real(angle_deg, "angle"))
    sx = finite_real(spacing_x_mm, "spacing_x")
    sy = finite_real(spacing_y_mm, "spacing_y")
    ex = finite_real(strain_x, "strain_x")
    ey = finite_real(strain_y, "strain_y")
    e2 = finite_real(transverse_strain, "transverse_strain")
    if sx <= 0.0 or sy <= 0.0 or ex < 0.0 or ey < 0.0:
        raise ValueError("spacings must be positive and strains non-negative")
    spacing = 1.0 / (math.sin(angle) / sx + math.cos(angle) / sy)
    strain = ex + ey + abs(e2)
    return spacing, strain, spacing * strain


def planar_resultant(
    vx_kn,
    width_x_mm,
    vy_kn,
    width_y_mm,
) -> float:
    """EN 1992-1-1:2023 8.21 resultant demand in kN/m."""

    vx = abs(finite_real(vx_kn, "vx"))
    vy = abs(finite_real(vy_kn, "vy"))
    bx = finite_real(width_x_mm, "width_x")
    by = finite_real(width_y_mm, "width_y")
    if bx <= 0.0 or by <= 0.0:
        raise ValueError("widths must be positive")
    qx = vx / (bx / 1000.0)
    qy = vy / (by / 1000.0)
    return math.hypot(qx, qy)


def piecewise_depth(
    qx_kn_per_m,
    qy_kn_per_m,
    depth_x_mm,
    depth_y_mm,
) -> tuple[float, str]:
    """EN 1992-1-1:2023 8.22-8.24 depth route."""

    qx = abs(finite_real(qx_kn_per_m, "qx"))
    qy = abs(finite_real(qy_kn_per_m, "qy"))
    dx = finite_real(depth_x_mm, "depth_x")
    dy = finite_real(depth_y_mm, "depth_y")
    if dx <= 0.0 or dy <= 0.0:
        raise ValueError("depths must be positive")
    ratio = math.inf if qx == 0.0 and qy > 0.0 else (
        0.0 if qx == 0.0 else qy / qx
    )
    if ratio <= 0.5:
        return dx, "8.22"
    if ratio < 2.0:
        return 0.5 * (dx + dy), "8.23"
    return dy, "8.24"


def rotated_depth(
    qx_kn_per_m,
    qy_kn_per_m,
    depth_x_mm,
    depth_y_mm,
) -> tuple[float, float]:
    """EN 1992-1-1:2023 8.25 rotated effective depth."""

    qx = abs(finite_real(qx_kn_per_m, "qx"))
    qy = abs(finite_real(qy_kn_per_m, "qy"))
    dx = finite_real(depth_x_mm, "depth_x")
    dy = finite_real(depth_y_mm, "depth_y")
    if dx <= 0.0 or dy <= 0.0:
        raise ValueError("depths must be positive")
    angle = math.atan2(qy, qx)
    depth = dx * math.cos(angle) ** 2 + dy * math.sin(angle) ** 2
    return depth, math.degrees(angle)


def rotate(x, y, angle_deg) -> tuple[float, float]:
    """Rigidly rotate a two-component vector."""

    angle = math.radians(finite_real(angle_deg, "rotation"))
    x_value = finite_real(x, "x")
    y_value = finite_real(y, "y")
    return (
        x_value * math.cos(angle) - y_value * math.sin(angle),
        x_value * math.sin(angle) + y_value * math.cos(angle),
    )


def benchmark_matrix() -> dict:
    """Return the frozen independent PR-06 boundary/symmetry matrix."""

    root_half = math.sqrt(0.5)
    epsilon = 1.0e-8
    points = {
        "x_limit": power_sum_point(1.0, 1.0, 0.0, 1.0, 2.0),
        "y_limit": power_sum_point(0.0, 1.0, 1.0, 1.0, 2.0),
        "zero": power_sum_point(0.0, 1.0, 0.0, 1.0, 2.0),
        "balanced": power_sum_point(
            root_half, 1.0, root_half, 1.0, 2.0
        ),
        "below": power_sum_point(
            root_half * (1.0 - epsilon),
            1.0,
            root_half * (1.0 - epsilon),
            1.0,
            2.0,
        ),
        "above": power_sum_point(
            root_half * (1.0 + epsilon),
            1.0,
            root_half * (1.0 + epsilon),
            1.0,
            2.0,
        ),
    }
    rotated = rotate(0.8, 0.3, 37.0)
    return {
        "points": {name: asdict(point) for name, point in points.items()},
        "swap_invariant": math.isclose(
            project_power_sum(0.8, 1.0, 0.3, 1.0, 2.0),
            project_power_sum(0.3, 1.0, 0.8, 1.0, 2.0),
            rel_tol=1.0e-12,
        ),
        "sign_invariant": math.isclose(
            project_power_sum(0.8, 1.0, 0.3, 1.0, 2.0),
            project_power_sum(-0.8, 1.0, -0.3, 1.0, 2.0),
            rel_tol=1.0e-12,
        ),
        "rigid_rotation_invariant": math.isclose(
            project_power_sum(0.8, 1.0, 0.3, 1.0, 2.0),
            project_power_sum(
                rotated[0], 1.0, rotated[1], 1.0, 2.0
            ),
            rel_tol=1.0e-12,
        ),
        "anisotropic_rotation_invariant": math.isclose(
            project_power_sum(0.8, 1.0, 0.3, 2.0, 2.0),
            project_power_sum(
                rotated[0], 1.0, rotated[1], 2.0, 2.0
            ),
            rel_tol=1.0e-12,
        ),
    }


if __name__ == "__main__":
    print(json.dumps(benchmark_matrix(), indent=2, sort_keys=True))
