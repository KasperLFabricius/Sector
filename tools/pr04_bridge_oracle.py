"""Independent scalar oracle for PR-04 bridge-base regression fixtures.

This file intentionally imports no Sector calculation module.  It mirrors only
the published scalar relationships used by the frozen bridge examples.
"""

from __future__ import annotations

import math

STANDARD_CONCRETE_MINER_C = 14.0
BOX_WALL_COT_THETA_MIN = 1.0
BOX_WALL_COT_THETA_MAX = 2.5
MINIMUM_CRACK_K_MIN = 0.65
MINIMUM_CRACK_K_MAX = 1.0


def brittle_method_b_area_mm2(m_rep_knm, z_s_m, f_yk_mpa):
    return 1000.0 * float(m_rep_knm) / (
        float(z_s_m) * float(f_yk_mpa)
    )


def box_wall_interaction(v_ed_kn, v_rd_max_kn, t_ed_kn, t_rd_max_kn):
    return (
        abs(float(v_ed_kn)) / float(v_rd_max_kn)
        + abs(float(t_ed_kn)) / float(t_rd_max_kn)
    )


def box_wall_cot_theta_is_admissible(cot_theta):
    if isinstance(cot_theta, bool):
        return False
    value = float(cot_theta)
    return (
        math.isfinite(value)
        and BOX_WALL_COT_THETA_MIN <= value <= BOX_WALL_COT_THETA_MAX
    )


def minimum_crack_k_from_dimension_mm(dimension_mm):
    dimension = float(dimension_mm)
    if dimension <= 300.0:
        return MINIMUM_CRACK_K_MAX
    if dimension >= 800.0:
        return MINIMUM_CRACK_K_MIN
    return 1.0 - 0.35 * (dimension - 300.0) / 500.0


def component_minimum_area_mm2(
    act_mm2,
    k_c,
    k,
    fct_eff_mpa,
    sigma_s_mpa,
    *,
    restrained_shrinkage=False,
):
    fct_used = (
        max(float(fct_eff_mpa), 2.9)
        if restrained_shrinkage
        else float(fct_eff_mpa)
    )
    return (
        float(k_c)
        * float(k)
        * fct_used
        * float(act_mm2)
        / float(sigma_s_mpa)
    )


def bridge_stress_limit_mpa(fck_mpa):
    return 0.60 * float(fck_mpa)


def corrected_concrete_log10_life(
    compression_max_mpa,
    compression_min_mpa,
    fcd_fat_mpa,
):
    sigma_max = float(compression_max_mpa)
    sigma_min = float(compression_min_mpa)
    if math.isclose(sigma_max, sigma_min):
        return math.inf
    ratio = sigma_min / sigma_max
    return (
        STANDARD_CONCRETE_MINER_C
        * (1.0 - sigma_max / float(fcd_fat_mpa))
        / math.sqrt(1.0 - ratio)
    )


def approved_project_log10_life(
    compression_max_mpa,
    compression_min_mpa,
    fcd_fat_mpa,
    *,
    coefficient,
):
    sigma_max = float(compression_max_mpa)
    sigma_min = float(compression_min_mpa)
    if math.isclose(sigma_max, sigma_min):
        return math.inf
    ratio = sigma_min / sigma_max
    return (
        float(coefficient)
        * (1.0 - sigma_max / float(fcd_fat_mpa))
        / math.sqrt(1.0 - ratio)
    )


BRIDGE_CRACK_ROUTES = {
    ("reinforced_or_unbonded", "X0 / XC1"): (
        ("width", "Quasi-permanent", 0.30),
    ),
    ("reinforced_or_unbonded", "XC2 / XC3 / XC4"): (
        ("width", "Quasi-permanent", 0.30),
    ),
    ("reinforced_or_unbonded", "XD / XS"): (
        ("width", "Quasi-permanent", 0.30),
    ),
    ("bonded", "X0 / XC1"): (
        ("width", "Frequent", 0.20),
    ),
    ("bonded", "XC2 / XC3 / XC4"): (
        ("width", "Frequent", 0.20),
        ("decompression", "Quasi-permanent", 0.0),
    ),
    ("bonded", "XD / XS"): (
        ("decompression", "Frequent", 0.0),
    ),
}
