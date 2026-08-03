"""Independent numerical oracle for the complete F-036 reference project.

This module deliberately imports no Sector calculation package.  It reconstructs
one representative result for each mathematical method from the frozen project
inputs, standard equations, and explicitly retained low-level intermediates.
"""

from __future__ import annotations

import math

import numpy as np


WIDTH_M = 0.200
HEIGHT_M = 0.300
FCK_MPA = 30.0
GAMMA_C = 1.45
FCD_MPA = FCK_MPA / GAMMA_C
FCTM_MPA = 2.896468153816889
ES_MPA = 200_000.0
EC_MPA = 33_000.0
FYK_MPA = 550.0
GAMMA_S = 1.20
FYD_MPA = FYK_MPA / GAMMA_S
EPS_C2 = 0.002
EPS_CU = 0.0035

# y coordinate in metres and area in square metres.  The x coordinates cancel
# in the independently checked V=90 degree uniaxial plastic state.
BARS = (
    (-0.120, 0.000500),
    (-0.120, 0.000500),
    (0.120, 0.000400),
    (0.120, 0.000400),
)


def plastic_pure_mx() -> dict[str, float]:
    """Integrate the parabola-rectangle law and bisect axial equilibrium."""

    points, weights = np.polynomial.legendre.leggauss(256)

    def state(depth: float) -> tuple[float, float, float, float]:
        y_top = HEIGHT_M / 2.0
        y_na = y_top - depth
        gradient = EPS_CU / depth
        lo = max(-HEIGHT_M / 2.0, y_na)
        hi = y_top
        ordinates = 0.5 * (hi - lo) * points + 0.5 * (hi + lo)
        strains = gradient * (ordinates - y_na)
        stresses = np.where(
            strains <= EPS_C2,
            FCD_MPA * (1.0 - (1.0 - strains / EPS_C2) ** 2),
            FCD_MPA,
        )
        scale = WIDTH_M * 1000.0 * 0.5 * (hi - lo)
        concrete_force = scale * float(np.dot(weights, stresses))
        concrete_moment = scale * float(np.dot(weights, stresses * ordinates))
        steel_forces = tuple(
            max(-FYD_MPA, min(FYD_MPA, ES_MPA * gradient * (y - y_na)))
            * area * 1000.0
            for y, area in BARS
        )
        steel_force = sum(steel_forces)
        steel_moment = sum(
            force * y for force, (y, _area) in zip(steel_forces, BARS)
        )
        return (
            concrete_force + steel_force,
            concrete_force,
            steel_force,
            concrete_moment + steel_moment,
        )

    low = 1.0e-9 * HEIGHT_M
    high = HEIGHT_M
    for _ in range(100):
        middle = 0.5 * (low + high)
        if state(middle)[0] > 0.0:
            high = middle
        else:
            low = middle
    depth = 0.5 * (low + high)
    residual, concrete_force, steel_force, moment = state(depth)
    return {
        "compression_depth_m": depth,
        "axial_residual_kn": residual,
        "concrete_force_kn": concrete_force,
        "steel_force_kn": steel_force,
        "mx_knm": moment,
    }


def applied_ray(
    capacity_points: tuple[tuple[float, float], ...],
    *,
    mx_knm: float,
    my_knm: float,
) -> dict[str, float | int]:
    """Intersect an applied ray with the retained ordered capacity polygon."""

    demand = math.hypot(mx_knm, my_knm)
    if demand < 1.0e-9:
        return {"resistance_knm": 0.0, "utilisation": 0.0, "segment": -1}

    def cross(first: tuple[float, float], second: tuple[float, float]) -> float:
        return first[0] * second[1] - first[1] * second[0]

    ray = (mx_knm, my_knm)
    hits = []
    for index, start in enumerate(capacity_points):
        end = capacity_points[(index + 1) % len(capacity_points)]
        edge = (end[0] - start[0], end[1] - start[1])
        denominator = cross(ray, edge)
        if abs(denominator) <= 1.0e-12:
            continue
        distance_factor = cross(start, edge) / denominator
        edge_factor = cross(start, ray) / denominator
        if -1.0e-9 <= edge_factor <= 1.0 + 1.0e-9 and distance_factor > 1.0e-9:
            hits.append((distance_factor, index))
    if not hits:
        return {
            "resistance_knm": math.inf,
            "utilisation": math.inf,
            "segment": -1,
        }
    distance_factor, segment = min(hits)
    return {
        "resistance_knm": distance_factor * demand,
        "utilisation": 1.0 / distance_factor,
        "segment": segment,
    }


def cracked_elastic_and_crack_width() -> dict[str, object]:
    """Solve the transformed rectangle and the 2005 DK crack expression."""

    modular_ratio = ES_MPA / EC_MPA
    y_top = HEIGHT_M / 2.0
    low = -HEIGHT_M / 2.0
    high = y_top
    for _ in range(100):
        y_na = 0.5 * (low + high)
        first_moment = (
            WIDTH_M * 0.5 * (y_top - y_na) ** 2
            + modular_ratio * sum(area * (y - y_na) for y, area in BARS)
        )
        if first_moment > 0.0:
            low = y_na
        else:
            high = y_na
    y_na = 0.5 * (low + high)
    second_moment = (
        WIDTH_M * (y_top - y_na) ** 3 / 3.0
        + modular_ratio * sum(area * (y - y_na) ** 2 for y, area in BARS)
    )
    curvature = 55.0 / (EC_MPA * 1000.0 * second_moment)
    concrete_compression = EC_MPA * 1000.0 * curvature * (y_top - y_na) / 1000.0
    steel_stress = tuple(
        ES_MPA * 1000.0 * curvature * (y_na - y) / 1000.0
        for y, _area in BARS
    )

    diameter = math.sqrt(4.0 * 500.0 / math.pi)
    clear_cover = 30.0 - diameter / 2.0
    effective_depth = 75.0
    rho_eff = 1000.0 / (WIDTH_M * 1000.0 * effective_depth)
    k3 = 3.4 * (25.0 / clear_cover) ** (2.0 / 3.0)
    sr_max = (
        k3 * clear_cover
        + 0.8 * 0.5 * 0.425 * diameter / rho_eff
    )
    mean_strain = max(
        (
            steel_stress[0]
            - 0.6 * FCTM_MPA / rho_eff
            * (1.0 + modular_ratio * rho_eff)
        ) / ES_MPA,
        0.6 * steel_stress[0] / ES_MPA,
    )
    return {
        "neutral_axis_y_m": y_na,
        "second_moment_m4": second_moment,
        "curvature_per_m": curvature,
        "concrete_compression_mpa": concrete_compression,
        "steel_stress_mpa": steel_stress,
        "diameter_mm": diameter,
        "clear_cover_mm": clear_cover,
        "rho_eff": rho_eff,
        "sr_max_mm": sr_max,
        "mean_strain": mean_strain,
        "crack_width_mm": sr_max * mean_strain,
    }


def member_checks(
    *,
    lever_arm_mm: float,
    bending_utilisation: float,
) -> dict[str, float]:
    """Reconstruct shear, torsion, detailing and combined interactions."""

    bw_mm = 200.0
    d_mm = 270.0
    asl_mm2 = 1000.0
    k = min(1.0 + math.sqrt(200.0 / d_mm), 2.0)
    rho_l = min(asl_mm2 / (bw_mm * d_mm), 0.02)
    crdc = 0.18 / GAMMA_C
    vmin = 0.035 * k ** 1.5 * math.sqrt(FCK_MPA) / GAMMA_C * 1.5
    basic = crdc * k * (100.0 * rho_l * FCK_MPA) ** (1.0 / 3.0)
    vrd_c = max(basic, vmin) * bw_mm * d_mm / 1000.0

    link_area = 2.0 * math.pi * 10.0**2 / 4.0
    asw_per_s = link_area / 150.0
    fywd = 500.0 / GAMMA_S
    nu1 = 0.55  # DK NA:2024 selected value for the 2005-family shear branch.
    # With the shared combined-M-V-T angle, the active objective is
    # a/cot + b(cot + 1/cot). Its stationary point is sqrt((a+b)/b),
    # sampled by the retained three-decimal angle search.
    effective_wall_mm = 60.0
    ak_m2 = (0.200 - 0.060) * (0.300 - 0.060)
    nu_torsion = 0.385
    shear_utilisation_coefficient = (
        30.0 / (asw_per_s * lever_arm_mm * fywd / 1000.0)
    )
    torsion_resistance_coefficient = (
        2.0 * nu_torsion * FCD_MPA * ak_m2 * effective_wall_mm
    )
    torsion_utilisation_coefficient = 20.0 / torsion_resistance_coefficient
    cot = round(math.sqrt(
        (shear_utilisation_coefficient + torsion_utilisation_coefficient)
        / torsion_utilisation_coefficient
    ), 3)
    cot = min(max(cot, 1.0), 2.5)
    vrd_s = asw_per_s * lever_arm_mm * fywd * cot / 1000.0
    vrd_max = (
        bw_mm * lever_arm_mm * nu1 * FCD_MPA
        / (cot + 1.0 / cot) / 1000.0
    )
    shear_links_utilisation = 30.0 / min(vrd_s, vrd_max)

    torsion_asw_per_s = math.pi * 10.0**2 / 4.0 / 150.0
    trd_s = torsion_asw_per_s * 2.0 * ak_m2 * fywd * cot
    trd_max = (
        2.0 * nu_torsion * FCD_MPA * ak_m2 * effective_wall_mm
        * cot / (cot**2 + 1.0)
    )
    fctk005 = 0.7 * FCTM_MPA
    fctd = fctk005 / 1.70
    trd_c = 2.0 * ak_m2 * effective_wall_mm * fctd
    torsion_utilisation = 20.0 / min(trd_s, trd_max)

    diameter = math.sqrt(4.0 * 500.0 / math.pi)
    clear_spacing = 120.0 - diameter
    required_spacing = max(20.0, diameter, 16.0 + 5.0)
    minimum_link_ratio = 0.063 * math.sqrt(FCK_MPA) / 500.0
    provided_link_ratio = link_area / (150.0 * bw_mm)
    torsion_spacing_limit = min(2.0 * (140.0 + 240.0) / 8.0, 200.0)

    return {
        "k": k,
        "rho_l": rho_l,
        "vrd_c_kn": vrd_c,
        "cot_theta": cot,
        "vrd_s_kn": vrd_s,
        "vrd_max_kn": vrd_max,
        "shear_links_utilisation": shear_links_utilisation,
        "trd_s_knm": trd_s,
        "trd_max_knm": trd_max,
        "trd_c_knm": trd_c,
        "torsion_utilisation": torsion_utilisation,
        "combined_sum": (
            bending_utilisation
            + shear_links_utilisation
            + torsion_utilisation
        ),
        "clear_spacing_mm": clear_spacing,
        "required_spacing_mm": required_spacing,
        "minimum_link_ratio": minimum_link_ratio,
        "provided_link_ratio": provided_link_ratio,
        "torsion_spacing_limit_mm": torsion_spacing_limit,
        "torsion_spacing_utilisation": 150.0 / torsion_spacing_limit,
    }


def minimum_longitudinal_area(*, bt_mm: float, d_mm: float) -> float:
    """EN 1992-1-1:2005 Formula 9.1N from retained tension-zone geometry."""

    return max(
        0.26 * FCTM_MPA / FYK_MPA * bt_mm * d_mm,
        0.0013 * bt_mm * d_mm,
    )


def fatigue() -> dict[str, float]:
    """Rebuild R1 S-N/Miner and the top-fibre concrete spectrum."""

    elastic = cracked_elastic_and_crack_width()
    steel_at_55 = float(elastic["steel_stress_mpa"][0])
    concrete_at_55 = float(elastic["concrete_compression_mpa"])
    stress_ranges = (steel_at_55 * 4.0 / 55.0, steel_at_55 * 2.0 / 55.0)
    applied_cycles = (100_000.0, 1_000_000.0)
    reference = 162.5
    gamma_s_fatigue = 1.15
    knee = reference / gamma_s_fatigue
    steel_damage = 0.0
    for stress_range, cycles in zip(stress_ranges, applied_cycles):
        exponent = 5.0 if stress_range >= knee else 9.0
        life = 1_000_000.0 * (reference / gamma_s_fatigue / stress_range) ** exponent
        steel_damage += cycles / life

    fcd_fat = 0.85 * FCK_MPA / 1.50 * (1.0 - FCK_MPA / 250.0)
    concrete_damage = 0.0
    concrete_stress_utilisation = 0.0
    for total_moment, cycles in zip((9.0, 7.0), applied_cycles):
        sigma_min = concrete_at_55 * 5.0 / 55.0
        sigma_max = concrete_at_55 * total_moment / 55.0
        ratio = sigma_min / sigma_max
        log10_life = 14.0 * (1.0 - sigma_max / fcd_fat) / math.sqrt(1.0 - ratio)
        concrete_damage += cycles / (10.0**log10_life)
        concrete_stress_utilisation = max(
            concrete_stress_utilisation, sigma_max / fcd_fat
        )
    yield_utilisation = (steel_at_55 * 9.0 / 55.0) / (FYK_MPA / 1.15)
    return {
        "steel_high_range_mpa": stress_ranges[0],
        "steel_low_range_mpa": stress_ranges[1],
        "steel_damage": steel_damage,
        "steel_yield_utilisation": yield_utilisation,
        "fcd_fat_mpa": fcd_fat,
        "concrete_damage": concrete_damage,
        "concrete_stress_utilisation": concrete_stress_utilisation,
    }


def bridge() -> dict[str, float]:
    """Direct substitutions for the three independent bridge kernels."""

    brittle_required = 1000.0 * 1000.0 / (0.8 * 500.0)
    box_wall_utilisation = 200.0 / 500.0 + 50.0 / 250.0
    crack_required = 0.4 * 0.8 * 3.0 * 100_000.0 / 200.0
    return {
        "brittle_required_mm2": brittle_required,
        "brittle_utilisation": brittle_required / 3000.0,
        "box_wall_utilisation": box_wall_utilisation,
        "crack_required_mm2": crack_required,
        "crack_utilisation": crack_required / 600.0,
    }
