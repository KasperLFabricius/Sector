"""Independent closed-form oracle for the PR03 crack-control regressions.

This module deliberately imports no Sector calculation code. It implements only
the inspected EN 1992-1-1:2023 scalar relationships needed to establish expected
values before comparing repository outputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class EffectiveRatioOracle:
    as_mm2: float
    ap_mm2: float
    weighted_ap_mm2: float
    ac_eff_mm2: float
    rho_p_eff: float
    xi1_values: tuple[float, ...]


def xi1_2023(
    bond_ratio_xi: float,
    mild_diameter_mm: float,
    tendon_diameter_mm: float,
    *,
    prestress_only: bool = False,
) -> float:
    """EN 1992-1-1:2023 Formula (9.6)."""

    xi = float(bond_ratio_xi)
    if not 0.0 < xi <= 1.0:
        raise ValueError("xi must satisfy 0 < xi <= 1")
    if prestress_only:
        return xi
    phi_s = float(mild_diameter_mm)
    phi_p = float(tendon_diameter_mm)
    if phi_s <= 0.0 or phi_p <= 0.0:
        raise ValueError("diameters must be positive")
    return math.sqrt(xi * phi_s / phi_p)


def effective_ratio_2023(
    as_mm2: float,
    tendons: Iterable[tuple[float, float, float]],
    ac_eff_mm2: float,
    *,
    mild_diameter_mm: float | None,
) -> EffectiveRatioOracle:
    """Formula (9.12) from explicit ``(Ap, xi, phi_p)`` tendon tuples."""

    as_value = float(as_mm2)
    ac_value = float(ac_eff_mm2)
    if as_value < 0.0 or ac_value <= 0.0:
        raise ValueError("areas are outside the oracle domain")
    rows = tuple((float(ap), float(xi), float(phi_p))
                 for ap, xi, phi_p in tendons)
    prestress_only = as_value == 0.0
    xi1_values = tuple(
        xi1_2023(
            xi,
            mild_diameter_mm if mild_diameter_mm is not None else phi_p,
            phi_p,
            prestress_only=prestress_only,
        )
        for _ap, xi, phi_p in rows
    )
    ap_value = sum(ap for ap, _xi, _phi_p in rows)
    weighted = sum(
        ap * xi1 for (ap, _xi, _phi_p), xi1 in zip(rows, xi1_values)
    )
    return EffectiveRatioOracle(
        as_mm2=as_value,
        ap_mm2=ap_value,
        weighted_ap_mm2=weighted,
        ac_eff_mm2=ac_value,
        rho_p_eff=(as_value + weighted) / ac_value,
        xi1_values=xi1_values,
    )


def direct_tension_band_2023(
    distance_to_face_mm: float,
    diameter_mm: float,
    section_dimension_mm: float,
) -> float:
    """Figure 9.3 effective depth/width for one direct-tension face."""

    a = float(distance_to_face_mm)
    phi = float(diameter_mm)
    dimension = float(section_dimension_mm)
    if a <= 0.0 or phi <= 0.0 or dimension <= 0.0:
        raise ValueError("direct-tension dimensions must be positive")
    return min(a + 5.0 * phi, 10.0 * phi, 3.5 * a, 0.5 * dimension)


def rectangular_perimeter_area_2023(
    width_mm: float,
    height_mm: float,
    *,
    left_mm: float = 0.0,
    right_mm: float = 0.0,
    bottom_mm: float = 0.0,
    top_mm: float = 0.0,
) -> float:
    """Union area of Figure 9.3 face bands for a solid rectangle."""

    width = float(width_mm)
    height = float(height_mm)
    inner_width = max(width - float(left_mm) - float(right_mm), 0.0)
    inner_height = max(height - float(bottom_mm) - float(top_mm), 0.0)
    return width * height - inner_width * inner_height


def crack_width_2023(
    *,
    sigma_s_mpa: float,
    es_mpa: float,
    fct_eff_mpa: float,
    rho_p_eff: float,
    alpha_e: float,
    kt: float,
    cover_mm: float,
    diameter_mm: float,
    kb: float,
    kfl: float,
    k1_r: float,
    kw: float = 1.7,
) -> tuple[float, float, float]:
    """Formulae (9.11), (9.15), and (9.8), without the bending cap."""

    sigma = float(sigma_s_mpa)
    es = float(es_mpa)
    rho = float(rho_p_eff)
    strain = max(
        (
            sigma
            - float(kt) * float(fct_eff_mpa) / rho
            * (1.0 + float(alpha_e) * rho)
        )
        / es,
        (1.0 - float(kt)) * sigma / es,
    )
    spacing = (
        1.5 * float(cover_mm)
        + float(kfl) * float(kb) / 7.2 * float(diameter_mm) / rho
    )
    width = float(kw) * float(k1_r) * spacing * strain
    return strain, spacing, width
