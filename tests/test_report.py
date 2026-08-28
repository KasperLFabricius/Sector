"""Tests for the PDF report builder (content + robustness, figures disabled)."""

from __future__ import annotations

import ast
import copy
import inspect
import io
import math
import pathlib
import re
import sys
import textwrap
from dataclasses import asdict
from types import SimpleNamespace as NS

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_analysis  # noqa: E402
import fatigue_inputs  # noqa: E402
import material_catalog  # noqa: E402
import publication_image_export  # noqa: E402
import result_presentation  # noqa: E402
import sector_report  # noqa: E402

from sector import capacity, codes, detailing, geometry  # noqa: E402
from sector import combined as combined_core  # noqa: E402
from sector import elastic as elastic_core  # noqa: E402
from sector import fatigue as fatigue_core  # noqa: E402
from sector import plastic as plastic_core  # noqa: E402
from sector import shear as shear_core  # noqa: E402
from sector import torsion as torsion_core  # noqa: E402
from sector.design_standards import (  # noqa: E402
    Capability,
    DesignBasisKey,
    capability_binding,
    get_design_basis,
)
from sector.fatigue import CONCRETE_PROJECT_MINER  # noqa: E402
from sector.materials import Concrete, MildSteel, Prestress  # noqa: E402


_build_report_from_completed_payload = sector_report.build_report


def _build_report_with_selection(meta, inp, out, *args, **kwargs):
    """Mirror run_analysis assembly for report unit-test payloads."""
    completed = dict(out or {})
    completed.setdefault(
        "worked_example_selection",
        result_presentation.worked_example_selection(inp, completed),
    )
    # This legacy module exercises the exhaustive equation/evidence surface.
    # Product-default Standard and cross-profile equality are covered in the
    # dedicated PR-07B profile integration suite.
    if "profile" not in kwargs and "qa_appendix" not in kwargs:
        kwargs["profile"] = "Audit"
    return _build_report_from_completed_payload(
        meta, inp, completed, *args, **kwargs
    )


sector_report.build_report = _build_report_with_selection


def _inp():
    return {
        "mode": "Both",
        "plastic_case": {
            "id": "PL-TEST",
            "type": "ALS",
            "source": "Combination register C1",
        },
        "elastic_case": {
            "id": "EL-TEST",
            "type": "FLS",
            "source": "Combination register C2",
        },
        "outer": [(-0.1, -0.15), (0.1, -0.15), (0.1, 0.15), (-0.1, 0.15)],
        "holes": [], "bars": [(0.0, -0.12, 500.0)], "tendons": [],
        "concrete": Concrete(fck=30.0, gamma_c=1.5, curve=2),
        "steel": MildSteel(fytk=500.0, fyck=500.0, futk=500.0, eut=0.05,
                           gamma_y=1.15, curve=2),
        "prestress": None,
        "concrete_preset": "EN 1992-1-1:2005",
        "concrete_k_tc": 1.0,
        "concrete_eta_cc": 1.0,
        "mild_preset": "EN 1992-1-1:2005",
        "prestress_preset": "EN 1992-1-1:2005",
        "P_pl": 0.0, "Mx_pl": 100.0, "My_pl": 0.0,
        "P_el_l": 0.0, "Mx_el_l": 80.0, "My_el_l": 0.0,
        "P_el_s": 0.0, "Mx_el_s": 20.0, "My_el_s": 0.0,
        "nl": 15.0, "ns": 200.0 / 33.0, "el_phi": 1.475,
        "sls_fctm": 2.9, "sls_cw": True, "conc_Ec": 33.0,
        "shear_gamma_v": 1.40,
        "torsion_gamma_ct": 1.70,
        "v_min": 0.0, "v_max": 360.0, "v_inc": 90.0,
    }


def _crack():
    # Units as returned by CrackWidthResult: wk/sr_max/phi/cover in mm; hc_ef in m;
    # ac_eff in m^2; esm_ecm dimensionless.
    rho = 2.72 / 99.0
    ac_eff = 0.0005 / rho
    concrete_reduction = 0.4 * 2.9 / rho * (1.0 + 6.06 * rho)
    mean_strain = 0.213 / 235.0
    sigma_s = mean_strain * 200_000.0 + concrete_reduction
    mean = {
        "record_kind": "CrackMeanStrainOperands",
        "sigma_s": sigma_s, "kt": 0.4, "fctm": 2.9,
        "rho_p_eff": rho, "alpha_e": 6.06, "es": 200_000.0,
        "concrete_tension_reduction": concrete_reduction,
        "formula_candidate": mean_strain,
        "lower_bound_factor": 0.6,
        "lower_bound_candidate": 0.6 * sigma_s / 200_000.0,
        "selected_candidate": "formula-7.9",
        "selected_esm_ecm": mean_strain,
    }
    spacing = {
        "record_kind": "CrackSpacing2005Operands",
        "cover": 40.0, "diameter": 16.0, "rho_p_eff": rho,
        "k1": 0.8, "k2": 0.5, "k3_base": 3.4, "k3_used": 3.4,
        "k4": 0.425, "nearest_neighbour_spacing": 100.0,
        "close_spacing_limit": 240.0, "tension_zone_depth": 0.15,
        "formula_7_11": 235.0, "geometric_7_14": 195.0,
        "selected_candidate": "formula-7.11", "selected_spacing": 235.0,
    }
    candidate = {
        "element_type": "Bar", "element_no": 1, "element_id": "bar 1",
        "x_mm": 0.0, "y_mm": -120.0, "area_mm2": 500.0,
        "wk": 0.213, "sr_max": 235.0, "esm_ecm": mean_strain,
        "sigma_s": sigma_s, "rho_p_eff": rho, "ac_eff": ac_eff,
        "hc_ef": 0.125, "phi": 16.0, "cover": 40.0,
        "coarse": False, "edition": "2004", "kw": 1.0,
        "k1_r": 1.0, "kfl": 1.0, "sr_max_geometric": False,
        "as_eff": 0.0005, "ap_eff": 0.0,
        "ap_eff_weighted": 0.0, "xi1": None,
        "reinforcement_type": "mild", "bc_ef": 0.0,
        "direct_tension": False, "scope": "dominant direction",
        "direction_deg": 90.0, "equivalent_diameter": 25.231,
        "diameter_source": "provided", "cover_source": "geometry",
        "bond_coefficient": 0.8, "modular_ratio": 6.06,
        "mean_strain_operands": mean,
        "spacing_operands": spacing,
    }
    effective_area = {
        "record_kind": "CrackEffectiveArea2005Fine",
        "section_depth": 0.3, "effective_depth": 0.25,
        "tension_zone_depth": 0.4, "h_minus_d": 0.05,
        "candidate_2_5_h_minus_d": 0.125,
        "candidate_h_minus_x_over_3": 0.13333333333333333,
        "candidate_h_over_2": 0.15,
        "selected_candidate": "2.5(h-d)", "selected_hc_eff": 0.125,
        "band_limit": -0.025, "ac_eff": ac_eff,
    }
    return dict(
        candidate,
        gov_bar=1,
        effective_area_operands=effective_area,
        effective_reinforcement_2023=None,
        governing_rule="maximum-wk-then-lowest-bar-index",
        governing_candidate=dict(candidate),
        candidates=[candidate],
    )


def _wide_crack():
    crack = copy.deepcopy(_crack())
    spacing = crack["governing_candidate"]["spacing_operands"]
    spacing.update({
        "nearest_neighbour_spacing": math.inf,
        "tension_zone_depth": 235.0 / 1.3 / 1000.0,
        "geometric_7_14": 235.0,
        "selected_candidate": "formula-7.14",
        "selected_spacing": 235.0,
    })
    crack["governing_candidate"]["sr_max_geometric"] = True
    crack["sr_max_geometric"] = True
    crack["candidates"][0] = copy.deepcopy(crack["governing_candidate"])
    return crack


def _coarse_crack(*, wk=0.213):
    crack = copy.deepcopy(_crack())
    crack.update(coarse=True, wk=wk)
    crack["governing_candidate"].update(coarse=True, wk=wk)
    crack["candidates"][0].update(coarse=True, wk=wk)
    crack["effective_area_operands"] = {
        "record_kind": "CrackEffectiveArea2005Coarse",
        "section_depth": 0.3, "compression_face_axis": -0.15,
        "tension_face_axis": 0.15, "reinforcement_centroid_axis": 0.12,
        "band_limit_axis": -0.005, "band_centroid_axis": 0.12,
        "centroid_gap": 0.0, "selected_hc_eff": 0.155,
        "ac_eff": crack["ac_eff"],
        "selected_candidate": "centroid-matched-band",
    }
    return crack


def _crack_2023():
    crack = copy.deepcopy(_crack())
    rho = crack["rho_p_eff"]
    spacing_value = 1.5 * 40.0 + (0.77 * 0.9 / 7.2) * 16.0 / rho
    mean_strain = 0.213 / (1.7 * 1.13 * spacing_value)
    reduction = 0.4 * 2.9 / rho * (1.0 + 6.06 * rho)
    sigma_s = mean_strain * 200_000.0 + reduction
    mean = {
        "record_kind": "CrackMeanStrainOperands",
        "sigma_s": sigma_s, "kt": 0.4, "fctm": 2.9,
        "rho_p_eff": rho, "alpha_e": 6.06, "es": 200_000.0,
        "concrete_tension_reduction": reduction,
        "formula_candidate": mean_strain, "lower_bound_factor": 0.6,
        "lower_bound_candidate": 0.6 * sigma_s / 200_000.0,
        "selected_candidate": "formula-9.11",
        "selected_esm_ecm": mean_strain,
    }
    spacing = {
        "record_kind": "CrackSpacing2023Operands",
        "cover": 40.0, "diameter": 16.0, "rho_p_eff": rho,
        "cover_coefficient": 1.5, "bond_coefficient_k1": 0.8,
        "bond_factor_kb": 0.9, "flexural_factor_raw": 0.77,
        "flexural_factor": 0.77, "flexural_factor_method": "formula-9.17",
        "transformed_tension_depth": 0.2, "cap_tension_depth": 0.2,
        "diameter_ratio_divisor": 7.2, "formula_spacing": spacing_value,
        "cap_spacing": 1.3 / 1.7 * 0.2 * 1000.0,
        "selected_candidate": "formula-9.15",
        "selected_spacing": spacing_value,
    }
    candidate = crack["governing_candidate"]
    candidate.update(
        edition="2023", kw=1.7, k1_r=1.13, kfl=0.77,
        wk=0.213, sr_max=spacing_value, esm_ecm=mean_strain,
        sigma_s=sigma_s, mean_strain_operands=mean,
        spacing_operands=spacing,
    )
    crack.update(candidate)
    crack.update(
        gov_bar=1,
        effective_area_operands={
            "record_kind": "CrackEffectiveArea2023Bending",
            "section_depth": 0.3, "tension_zone_depth": 0.2,
            "near_layer_depth": 0.025, "far_layer_depth": 0.025,
            "near_layer_diameter": 16.0,
            "candidate_ay_plus_5phi": 0.105,
            "candidate_10phi": 0.16, "candidate_3_5ay": 0.0875,
            "base_selected_candidate": "3.5ay", "base_height": 0.0875,
            "layer_spread": 0.0, "height_before_section_caps": 0.0875,
            "candidate_h_minus_x": 0.2, "candidate_h_over_2": 0.15,
            "final_selected_candidate": "layer-band",
            "selected_hc_eff": 0.0875, "band_limit": 0.0625,
            "ac_eff": crack["ac_eff"],
        },
        effective_reinforcement_2023={
            "record_kind": "EffectiveReinforcement2023",
            "as_eff": 0.0005, "ap_eff": 0.0,
            "ap_eff_weighted": 0.0, "rho_p_eff": rho,
            "xi1_by_element": [None], "ac_eff": crack["ac_eff"],
            "rho_numerator": 0.0005, "reference_mild_diameter": 16.0,
            "elements": [],
        },
        governing_candidate=candidate,
        candidates=[copy.deepcopy(candidate)],
    )
    return crack


def _plastic_point():
    return {
        "V": 0.0,
        "Mx": 100.0,
        "My": 0.0,
        "na_x": 0.0,
        "na_y": 0.05,
        "eps_c": 0.35,
        "eps_s": 2.0,
        "eps_s_comp": -0.1,
        "eps_cable": 0.0,
        "kappa": 0.02,
        "comp_force": 250.0,
        "lever": 0.2,
        "dx": 0.0,
        "dy": 0.2,
        "converged": True,
        "axial_requested": 0.0,
        "axial_achieved": 0.0,
        "axial_residual": 0.0,
        "axial_tolerance": 1.0e-6,
        "axial_reachable": True,
        "compression_depth": 0.175,
        "neutral_axis_offset": 0.0,
        "strain_gradient_x": 0.0,
        "strain_gradient_y": -0.02,
        "strain_offset": 0.0,
        "search_lower_depth": 0.01,
        "search_upper_depth": 0.29,
        "search_lower_axial": -45.0,
        "search_upper_axial": 62.0,
        "search_iterations": 8,
        "concrete_force": 250.0,
        "concrete_mx": 70.0,
        "concrete_my": 0.0,
        "bar_force": -250.0,
        "bar_mx": 30.0,
        "bar_my": 0.0,
        "tendon_force": 0.0,
        "tendon_mx": 0.0,
        "tendon_my": 0.0,
        "compression_mx": 70.0,
        "compression_my": 0.0,
        "tension_force": -250.0,
        "tension_mx": 30.0,
        "tension_my": 0.0,
        "concrete_corner_states": [{
            "point_no": 1,
            "ring": "Outer",
            "ring_point_no": 1,
            "x_mm": -100.0,
            "y_mm": -150.0,
            "section_strain_permille": 3.0,
            "strain_permille": -3.0,
            "stress_mpa": -20.0,
        }],
        "reinforcement_states": [{
            "element_type": "Bar",
            "element_no": 1,
            "element_id": "bar 1",
            "material_id": "M1",
            "material_name": "B500",
            "state": "Tension",
            "x_mm": 0.0,
            "y_mm": -120.0,
            "area_mm2": 500.0,
            "section_strain_permille": -2.5,
            "initial_strain_permille": 0.0,
            "strain_permille": 2.5,
            "stress_mpa": 500.0,
            "force_kn": 250.0,
            "internal_force_kn": -250.0,
            "internal_mx_knm": 30.0,
            "internal_my_knm": 0.0,
        }],
        "curvature_candidates": [{
            "mode": "concrete_crushing",
            "element_index": None,
            "element_id": None,
            "strain_limit": 0.0035,
            "distance_from_na_m": 0.175,
            "curvature_per_m": 0.02,
            "selected": True,
        }],
        "curvature_selection": {
            "mode": "concrete_crushing",
            "element_index": None,
            "curvature_per_m": 0.02,
        },
    }


def _elastic_state(mx):
    return {
        "raw_stress_plane": {
            "sigma0_kpa": 0.0,
            "gradient_x_kpa_per_m": mx,
            "gradient_y_kpa_per_m": 0.0,
        },
        "iterations": 4,
        "converged": True,
        "equilibrium": {
            "matrix": [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ],
            "target": {"n": 0.0, "mx": mx, "my": 0.0},
            "internal": {"n": 0.0, "mx": mx, "my": 0.0},
            "residual": {"n": 0.0, "mx": 0.0, "my": 0.0},
            "residual_scale": abs(mx),
            "normalised_residual": 0.0,
            "relative_tolerance": 1.0e-8,
        },
    }


def _out():
    return {
        "plastic": {"mx": [100.0, 0.0, -100.0, 0.0], "my": [0.0, 100.0, 0.0, -100.0],
                    "max_mx": 100.0, "max_my": 100.0, "min_mx": -100.0, "min_my": -100.0,
                    "util": 0.8, "util_valid": True, "util_reason": None,
                    "util_origin_inside_or_on": True, "closed": True,
                    "check_util": True, "applied": (80.0, 0.0), "converged": True,
                    "worked_point_index": 0,
                    "worked_point_basis": "utilisation direction",
                    "points": [_plastic_point()]},
        "elastic": {"total": [150.0], "long": [120.0], "dif": [30.0],
                    "rst1": [90.404040404],
                    "max_conc": 12.0, "max_conc_xy": (0.0, 0.15), "max_conc_point": 4,
                    "na_x": 0.0, "na_y": 0.04, "max_steel": 150.0, "max_steel_bar": 1,
                    "max_steel_element": "bar 1",
                    "converged": True, "cracked": True, "lambda_cr": 0.4,
                    "sigma_ct": 7.2, "fctm": 2.9, "show_cw": True,
                    "stress_plane": (-12000.0, 0.0, 80000.0),
                    "elements": [{
                        "element_type": "Bar", "element_no": 1,
                        "element_id": "bar 1", "x_mm": 0.0, "y_mm": -120.0,
                        "area_mm2": 500.0, "strain_permille": 0.75,
                        "total_mpa": 150.0, "long_mpa": 120.0,
                        "dif_mpa": 30.0, "rst1_mpa": 90.404040404,
                        "long_passive_mpa": 100.0,
                        "reduced_long_mpa": 59.595959596,
                        "locked_in_mpa": 0.0,
                    }],
                    "concrete_corners": [
                        {"point_no": 1, "ring": "Outer", "ring_point_no": 1,
                         "x_mm": -100.0, "y_mm": -150.0,
                         "strain_permille": -0.72727, "stress_mpa": -24.0},
                        {"point_no": 2, "ring": "Outer", "ring_point_no": 2,
                         "x_mm": 100.0, "y_mm": -150.0,
                         "strain_permille": -0.72727, "stress_mpa": -24.0},
                        {"point_no": 3, "ring": "Outer", "ring_point_no": 3,
                         "x_mm": 100.0, "y_mm": 150.0,
                         "strain_permille": 0.0, "stress_mpa": 0.0},
                        {"point_no": 4, "ring": "Outer", "ring_point_no": 4,
                         "x_mm": -100.0, "y_mm": 150.0,
                         "strain_permille": 0.0, "stress_mpa": 0.0},
                    ],
                    "stress_outputs": {
                        "concrete": {
                            "value": 12.0,
                            "quantity": "maximum concrete compression",
                            "unit": "MPa",
                            "calculation_state": "CALCULATED",
                        },
                        "reinforcement": {
                            "value": 150.0,
                            "quantity": "maximum reinforcement tension",
                            "unit": "MPa",
                            "governing": "bar 1",
                            "element_no": 1,
                            "calculation_state": "CALCULATED",
                        },
                        "prestress": {
                            "value": None,
                            "quantity": "maximum tendon tension",
                            "unit": "MPa",
                            "calculation_state": "NOT APPLICABLE",
                        },
                    },
                    "props_un": {"area": 0.06, "cx": 0.0, "cy": 0.0, "Ix": 4.5e-4,
                                 "Iy": 2.0e-4, "Ixy": 0.0},
                    "props_cr": {"area": 0.03, "cx": 0.0, "cy": 0.02, "Ix": 2.1e-4,
                                 "Iy": 1.0e-4, "Ixy": 0.0},
                    "crack": _crack(), "crack_short": _crack(),
                    "crack_output": {
                        "long_term": {
                            "duration": "long_term",
                            "value": 0.213,
                            "case": "Long-term",
                            "governing": "bar 1",
                            "unit": "mm",
                            "calculation_state": "CALCULATED",
                        },
                        "short_term": {
                            "duration": "short_term",
                            "value": 0.213,
                            "case": "Short-term",
                            "governing": "bar 1",
                            "unit": "mm",
                            "calculation_state": "CALCULATED",
                        },
                    },
                    "crack_code": "EN 1992-1-1:2005", "crack_member": None,
                    "accepted_states": {
                        "long_term": _elastic_state(80.0),
                        "instantaneous_combined": _elastic_state(95.0),
                    },
                    "superposition": {
                        "long_term_modular_ratio": 15.0,
                        "short_term_modular_ratio": 200.0 / 33.0,
                        "long_term_reduction_factor": 1.0 - (200.0 / 33.0) / 15.0,
                        "prestress_resultant": {"n": 0.0, "mx": 0.0, "my": 0.0},
                        "combined_target_before_neutralisation": {
                            "n": 29.797979798,
                            "mx": 91.424242424,
                            "my": 0.0,
                        },
                        "neutralising_resultant": {
                            "n": 29.797979798,
                            "mx": -3.575757576,
                            "my": 0.0,
                        },
                    }},
        "section_properties": {
            "rings": [{
                "ring_id": "outer", "role": "gross outline",
                "area_m2": 0.06, "first_x_m3": 0.0, "first_y_m3": 0.0,
                "second_xx_m4": 2.0e-4, "second_yy_m4": 4.5e-4,
                "product_xy_m4": 0.0,
            }],
            "net_concrete": {
                "area_m2": 0.06, "first_x_m3": 0.0, "first_y_m3": 0.0,
                "second_xx_m4": 2.0e-4, "second_yy_m4": 4.5e-4,
                "product_xy_m4": 0.0, "centroid_x_m": 0.0,
                "centroid_y_m": 0.0, "ix_centroid_m4": 4.5e-4,
                "iy_centroid_m4": 2.0e-4, "ixy_centroid_m4": 0.0,
            },
        },
        "material_properties": {
            "concrete": {"design_strength_mpa": 20.0},
            "mild": [{"material_id": "-", "design_yield_mpa": 500.0 / 1.15}],
            "prestress": [],
        },
        "prestress_initial": {
            "elements": [],
            "internal_resultant_origin": {"n_kn": 0.0, "mx_knm": 0.0,
                                          "my_knm": 0.0},
            "equivalent_action_origin": {"n_kn": 0.0, "mx_knm": 0.0,
                                         "my_knm": 0.0},
        },
        "elastic_shared": {
            "concrete_modulus_mpa": 33_000.0,
            "effective_concrete_modulus_mpa": 33_000.0 / 2.475,
            "creep_coefficient": 1.475,
            "materials": [{
                "material_id": "M1", "material_family": "mild",
                "modulus_mpa": 200_000.0,
                "short_term": 200_000.0 / 33_000.0,
                "long_term": 15.0,
            }],
        },
    }


def _fatigue_report_fixture():
    inp = _inp()
    inp.update({
        "mode": "",
        "fatigue_on": True,
        "fatigue_edition": DesignBasisKey.PUBLISHED_2023.value,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": True,
        "fatigue_concrete_method": "Explicit Palmgren-Miner spectrum",
        "fatigue_gamma_ff": 1.10,
        "fatigue_gamma_s": 1.15,
        "fatigue_gamma_c": 1.50,
        "fatigue_t0_days": 28.0,
        "fatigue_beta_cc_t0": 0.92,
        "fatigue_concrete_k1": 1.0,
        "fatigue_concrete_c": 14.0,
        "bar_elements": [{
            "id": "R1",
            "kind": "bar",
            "x_mm": 0.0,
            "y_mm": -120.0,
            "area_mm2": 500.0,
            "diameter_mm": 25.23,
            "material_id": "M1",
            "fatigue_detail_id": "F1",
        }],
        "tendon_elements": [],
        fatigue_inputs.BASIS_KEY: {
            "method": fatigue_inputs.METHOD_GROUPED,
            "notes": "Traffic model TM-7; cycle count CC-4; independent spectra",
        },
        fatigue_inputs.SPECTRUM_TABLE_KEY:
            fatigue_inputs.normalise_spectrum_table([
                {
                    "spectrum": "Traffic A",
                    "name": "FAT-A1",
                    "description": "Heavy vehicles",
                    "cycles": 2.0e5,
                    "n_long_ed_kn": -300.0,
                    "mx_long_ed_knm": 40.0,
                    "n_short_ed_kn": 20.0,
                    "mx_short_ed_knm": 25.0,
                },
                {
                    "spectrum": "Traffic B",
                    "name": "FAT-B1",
                    "description": "Permit vehicles",
                    "cycles": 4.0e4,
                    "n_long_ed_kn": -250.0,
                    "my_long_ed_knm": 15.0,
                    "n_short_ed_kn": -10.0,
                    "my_short_ed_knm": 30.0,
                },
                {
                    "spectrum": "Traffic C",
                    "name": "FAT-C1",
                    "description": "Non-governing service traffic",
                    "cycles": 1.0e5,
                    "n_long_ed_kn": -150.0,
                    "mx_long_ed_knm": 10.0,
                    "n_short_ed_kn": 5.0,
                    "mx_short_ed_knm": 12.0,
                },
            ]),
    })

    def spectrum(
        name,
        bin_name,
        reinforcement_utilisation,
        concrete_utilisation,
    ):
        yield_limit_mpa = 500.0 / 1.15
        governing_stress_mpa = yield_limit_mpa * reinforcement_utilisation
        stress_long_mpa = governing_stress_mpa - 66.0
        sn_reference_cycles = 2.0e6
        sn_reference_ratio = 2.0
        cycles_to_failure = 64.0e6
        damage = 2.0e5 / cycles_to_failure
        yield_long = NS(
            state="long-term endpoint",
            stress_mpa=stress_long_mpa,
            branch="tension yield",
            characteristic_strength_mpa=500.0,
            design_limit_mpa=yield_limit_mpa,
            utilisation=abs(stress_long_mpa) / yield_limit_mpa,
        )
        yield_total = NS(
            state="design total endpoint",
            stress_mpa=governing_stress_mpa,
            branch="tension yield",
            characteristic_strength_mpa=500.0,
            design_limit_mpa=yield_limit_mpa,
            utilisation=reinforcement_utilisation,
        )
        steel_bin = NS(
            bin_name=bin_name,
            cycles=2.0e5,
            converged=True,
            stress_long_mpa=stress_long_mpa,
            stress_total_mpa=governing_stress_mpa / 1.10,
            stress_total_design_mpa=governing_stress_mpa,
            stress_total_elastic_mpa=governing_stress_mpa / 1.10,
            stress_range_mpa=60.0,
            stress_range_elastic_mpa=60.0,
            bond_adjustment=1.0,
            bond_method="Perfect bond",
            design_stress_range_mpa=66.0,
            delta_sigma_rsk_mpa=151.8,
            delta_sigma_rd_mpa=132.0,
            sn_exponent=5.0,
            cycles_to_failure=cycles_to_failure,
            log10_cycles_to_failure=math.log10(cycles_to_failure),
            damage=damage,
            governing_stress_mpa=governing_stress_mpa,
            yield_limit_mpa=yield_limit_mpa,
            yield_utilisation=reinforcement_utilisation,
            sn_reference_cycles=sn_reference_cycles,
            sn_slope_1=5.0,
            sn_slope_2=9.0,
            sn_knee_stress_range_mpa=132.0,
            sn_branch="upper S-N branch",
            sn_reference_ratio=sn_reference_ratio,
            material_factor=1.15,
            stress_total_design_elastic_mpa=governing_stress_mpa,
            design_stress_range_elastic_mpa=66.0,
            yield_long_check=yield_long,
            yield_design_total_check=yield_total,
            governing_yield_check=yield_total,
            zero_cyclic_range=False,
        )
        screen_utilisation = 66.0 / 73.0
        screen = NS(
            status="PASS - DETAILED CHECK NOT REQUIRED",
            applicable=True,
            passed=True,
            detail_class="unwelded straight reinforcing bar",
            range_basis="design",
            threshold_mpa=73.0,
            governing_range_mpa=66.0,
            utilisation=screen_utilisation,
            governing_bin=bin_name,
            total_cycles=2.0e5,
            source="DS/EN 1992-1-1:2023, 10.4(1)",
            reason="Stress range is within the supported simplified limit",
        )
        steel_utilisation = max(
            reinforcement_utilisation,
            screen_utilisation,
        )
        steel = NS(
            element_id="R1",
            kind="mild",
            detail_id="F1",
            diameter_mm=25.23,
            bins=(steel_bin,),
            damage=damage,
            damage_utilisation=damage,
            governing_damage_bin=bin_name,
            yield_utilisation=reinforcement_utilisation,
            governing_yield_bin=bin_name,
            utilisation=steel_utilisation,
            converged=True,
            passed=True,
            governing_criterion=(
                "yield/proof stress"
                if reinforcement_utilisation > screen_utilisation
                else "simplified stress-range screen"
            ),
            governing_bin=bin_name,
            simplified_screen=screen,
        )
        fcd_fat_mpa = 14.72
        e_cd_min = 0.20
        e_cd_max = concrete_utilisation
        concrete_cycles_to_failure = 20.0e6
        concrete_damage = 2.0e5 / concrete_cycles_to_failure
        concrete_bin = NS(
            bin_name=bin_name,
            cycles=2.0e5,
            converged=True,
            compression_long_mpa=e_cd_min * fcd_fat_mpa / 1.10,
            compression_total_mpa=e_cd_max * fcd_fat_mpa / 1.10,
            compression_min_design_mpa=e_cd_min * fcd_fat_mpa,
            compression_max_design_mpa=e_cd_max * fcd_fat_mpa,
            stress_ratio=e_cd_min / e_cd_max,
            e_cd_min=e_cd_min,
            e_cd_max=e_cd_max,
            cycles_to_failure=concrete_cycles_to_failure,
            log10_cycles_to_failure=math.log10(concrete_cycles_to_failure),
            damage=concrete_damage,
            stress_utilisation=concrete_utilisation,
            equivalent_utilisation=None,
            life_branch="variable compression",
            life_coefficient=14.0,
            life_range_term=0.75,
            compression_total_design_mpa=e_cd_max * fcd_fat_mpa,
            compression_min_state="long-term endpoint",
            compression_max_state="design total endpoint",
        )
        concrete = NS(
            fibre_index=4,
            x_m=0.1,
            y_m=-0.15,
            bins=(concrete_bin,),
            fcd_fat_mpa=fcd_fat_mpa,
            damage=concrete_damage,
            damage_utilisation=concrete_damage,
            governing_damage_bin=bin_name,
            stress_utilisation=concrete_utilisation,
            governing_stress_bin=bin_name,
            utilisation=concrete_utilisation,
            converged=True,
            passed=True,
            method=fatigue_core.CONCRETE_MINER,
            equivalent_utilisation=None,
            governing_equivalent_bin=None,
            governing_criterion="compressive stress",
            governing_bin=bin_name,
        )
        search = NS(
            x_m=0.1,
            y_m=-0.15,
            damage=max(concrete_utilisation - 0.002, 0.0),
            upper_damage=max(concrete_utilisation - 0.001, 0.0),
            divisions=96,
            boxes_evaluated=128,
            points_evaluated=772,
            absolute_gap=0.001,
            relative_gap=0.10,
            converged=True,
            method=fatigue_core.CONCRETE_MINER,
        )
        state = NS(
            name=bin_name,
            description="Grouped bin",
            cycles=2.0e5,
            converged=True,
            bond_method="Perfect bond",
            design_action_factor=1.10,
            zero_cyclic_action=False,
        )
        concrete_strength = NS(
            edition=fatigue_core.EC2_2023,
            fck_mpa=30.0,
            gamma_c=1.50,
            beta_cc_t0=0.92,
            base_strength_mpa=18.4,
            alpha_cc=None,
            k1=None,
            high_strength_reduction=None,
            eta_cc_raw=(40.0 / 30.0) ** (1.0 / 3.0),
            eta_cc_cap=1.0,
            eta_cc=1.0,
            eta_cc_fat_raw=0.85,
            eta_cc_fat_cap=0.8,
            eta_cc_fat=0.8,
            fcd_fat_mpa=fcd_fat_mpa,
        )
        if steel_utilisation >= concrete_utilisation:
            governing_domain = "reinforcement"
            governing_criterion = steel.governing_criterion
        else:
            governing_domain = "concrete"
            governing_criterion = "compressive stress"
        return NS(
            spectrum_name=name,
            bins=(state,),
            reinforcement=(steel,),
            concrete=(concrete,),
            concrete_search=search,
            fcd_fat_mpa=fcd_fat_mpa,
            governing_reinforcement_id="R1",
            governing_concrete_fibre=4,
            utilisation=max(steel_utilisation, concrete_utilisation),
            converged=True,
            passed=True,
            concrete_method=fatigue_core.CONCRETE_MINER,
            concrete_strength=concrete_strength,
            governing_domain=governing_domain,
            governing_criterion=governing_criterion,
            miner_damage=max(
                damage,
                concrete_damage,
                search.damage,
            ),
            yield_utilisation=reinforcement_utilisation,
        )

    spectra = (
        spectrum("Traffic A", "FAT-A1", 0.82, 0.35),
        spectrum("Traffic B", "FAT-B1", 0.55, 0.91),
        spectrum("Traffic C", "FAT-C1", 0.41, 0.50),
    )
    basis = get_design_basis(DesignBasisKey.PUBLISHED_2023)
    reinforcement_binding = capability_binding(
        basis.key,
        Capability.REINFORCEMENT_FATIGUE,
    )
    concrete_binding = capability_binding(
        basis.key,
        Capability.CONCRETE_FATIGUE_DAMAGE_SUM,
    )
    payload = {
        "basis_key": basis.key.value,
        "basis_label": basis.label,
        "basis_disclosure": basis.disclosure,
        "edition": basis.label,
        "solver_edition": fatigue_inputs.EC2_2023,
        "checks": {"reinforcement": True, "concrete": True},
        "concrete_method": "Explicit Palmgren-Miner spectrum",
        "basis": inp[fatigue_inputs.BASIS_KEY],
        "method_reference": fatigue_inputs.METHOD_REFERENCES[
            fatigue_inputs.METHOD_GROUPED
        ],
        "calculation_references": {
            "reinforcement": reinforcement_binding.source,
            "concrete": concrete_binding.source,
        },
        "capability_bindings": {
            "reinforcement": {
                "capability": reinforcement_binding.capability.value,
                "source": reinforcement_binding.source,
                "disclosure": reinforcement_binding.disclosure,
            },
            "concrete": {
                "capability": concrete_binding.capability.value,
                "source": concrete_binding.source,
                "disclosure": concrete_binding.disclosure,
            },
        },
        "warnings": ("Cycle-count method requires project review",),
        "partial_factors": {
            "gamma_c": 1.50,
            "gamma_s": 1.15,
            "gamma_ff": 1.10,
        },
        "concrete_parameters": {
            "fck_mpa": 30.0,
            "beta_cc_t0": 0.92,
            "alpha_cc": 1.0,
            "k1": 1.0,
            "c": 14.0,
            "method": "Explicit Palmgren-Miner spectrum",
        },
        "reinforcement_properties": (
            NS(
                element_id="R1",
                kind="mild",
                detail_id="F1",
                diameter_mm=25.23,
                n_star=2.0e6,
                k1=5.0,
                k2=9.0,
                delta_sigma_rsk_mpa=160.0,
                fytk_mpa=500.0,
                fyck_mpa=500.0,
                bond_ratio_xi=None,
                bond_equivalent_diameter_mm=None,
            ),
        ),
        "fatigue_detail_basis": ({
            "id": "F1",
            "name": "Straight bars",
            "kind": "mild",
            "preset": fatigue_inputs.PRESET_2023_BARS,
            "n_star": 2.0e6,
            "k1": 5.0,
            "k2": 9.0,
            "delta_sigma_rsk_mpa": 160.0,
            "source": "DS/EN 1992-1-1:2023, Table E.1",
        },),
        "t0_days": 28.0,
        "elements": tuple(inp["bar_elements"]),
        "spectra": spectra,
        "governing_spectrum": "Traffic B",
        "governing_domain": "concrete",
        "governing_criterion": "compressive stress",
        "governing_reinforcement_id": "R1",
        "governing_concrete_fibre": 4,
        "governing_reinforcement_example": {
            "spectrum_name": "Traffic A",
            "element_id": "R1",
            "utilisation": 66.0 / 73.0,
            "criterion": "simplified stress-range screen",
            "bin_name": "FAT-A1",
        },
        "governing_concrete_example": {
            "spectrum_name": "Traffic B",
            "fibre_index": 4,
            "utilisation": 0.91,
            "criterion": "compressive stress",
            "bin_name": "FAT-B1",
            "search_upper_bound_governs": False,
        },
        "utilisation": 0.91,
        "miner_damage": spectra[1].miner_damage,
        "yield_utilisation": spectra[1].yield_utilisation,
        "converged": True,
        "passed": True,
    }
    return inp, {"fatigue": payload}


def test_report_includes_complete_grouped_fatigue_evidence():
    inp, out = _fatigue_report_fixture()

    text = " ".join(_pdf_text(sector_report.build_report(
        {"proj_no": "FAT-QA"}, inp, out, figures=False
    )).split())

    assert "Grouped fatigue" in text
    assert "REVIEW - Traffic B" in text
    assert all(name in text for name in ("Traffic A", "Traffic B", "Traffic C"))
    assert "FAT-A1" in text and "FAT-B1" in text
    assert "Reinforcement fatigue" in text
    assert "Simplified stress-range screen" in text
    assert "PASS - DETAILED CHECK NOT REQUIRED" in text
    assert "unwelded straight reinforcing bar" in text
    assert "DS/EN 1992-1-1:2023, 10.4(1)" in text
    assert "66.000 MPa" in text and "73.000 MPa" in text
    assert "Concrete fatigue" in text
    assert "Bounded governing-fibre search" in text
    assert "Upper D" in text
    assert "Fatigue total" in text
    assert "Bond factor / method" in text
    assert "bond transformation" in text
    assert "action-factored Elastic stress range" in text
    assert "action-level" in text
    assert "Annex E.5" in text and "Formulae (E.7)-(E.8)" in text
    assert "published reference; project adoption required" in text
    assert "no Danish National Annex is applied" in text
    assert "reinforcement_fatigue" in text
    assert "concrete_fatigue_damage_sum" in text
    assert "different spectrum names are not combined" in text
    assert "Max Miner D" in text
    assert "Max yield / proof" in text
    assert "Governing util." in text
    assert "governing utilisation" in text
    assert "Status / range" in text
    assert "shear and torsion fatigue remain separate checks" in text
    compact = text.replace(" ", "")
    delta_sigma = chr(0x394) + chr(0x3C3)
    sigma = chr(0x3C3)
    eta = chr(0x3B7)
    assert (
        delta_sigma + "Ed,el,i=|" + sigma + "total,Ed,el,i-"
        + sigma + "long,i|"
    ) in compact
    assert (
        delta_sigma + "Ed,i=" + eta + "b" + delta_sigma + "Ed,el,i"
    ) in compact
    assert "delta " + sigma not in text
    assert text.count(delta_sigma) >= 7
    assert chr(0x3B2) in text  # beta_cc(t0) uses the Greek symbol


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_report_profiles_publish_retained_simplified_fatigue_screen(profile):
    inp, out = _fatigue_report_fixture()

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False, profile=profile
    )).split())

    assert "Simplified stress-range screen" in text
    assert "PASS - DETAILED CHECK NOT REQUIRED" in text
    assert "66.000" in text
    assert "73.000" in text
    assert "DS/EN 1992-1-1:2023, 10.4(1)" in text
    assert "Miner D" in text
    assert "Yield / proof util." in text


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_report_profiles_publish_retained_unsupported_fatigue_fallback(profile):
    inp, out = _fatigue_report_fixture()
    result = out["fatigue"]["spectra"][0].reinforcement[0]
    screen = result.simplified_screen
    screen.status = "NOT APPLICABLE"
    screen.applicable = False
    screen.passed = None
    screen.detail_class = "unsupported published-2023 detail"
    screen.range_basis = ""
    screen.threshold_mpa = None
    screen.governing_range_mpa = None
    screen.utilisation = None
    screen.governing_bin = None
    screen.source = "DS/EN 1992-1-1:2023, 10.4(1)"
    screen.reason = (
        "DS/EN 1992-1-1:2023 10.4 does not assign this preset a "
        "simplified limit"
    )
    result.governing_criterion = "Miner damage"
    result.governing_bin = result.governing_damage_bin
    result.utilisation = result.damage

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False, profile=profile
    )).split())

    assert "NOT APPLICABLE" in text
    assert "unsupported published-2023 detail" in text
    assert screen.reason in text
    assert screen.source in text
    assert "Miner D" in text


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_report_profiles_publish_retained_invalid_fatigue_screen(profile):
    inp, out = _fatigue_report_fixture()
    payload = out["fatigue"]
    payload["governing_reinforcement_example"] = None
    expected = []
    untrusted_reasons = []
    for index, spectrum in enumerate(payload["spectra"], start=1):
        for result in spectrum.reinforcement:
            result.element_id = f"SCREEN-R{index}"
            screen = result.simplified_screen
            screen.status = "INVALID"
            screen.applicable = False
            screen.passed = None
            screen.detail_class = f"invalid retained screen class {index}"
            screen.range_basis = f"retained range basis {index}"
            screen.governing_range_mpa = None
            screen.utilisation = None
            screen.governing_bin = None
            screen.source = f"retained invalid-screen source {index}"
            screen.reason = f"Retained screen evidence group {index} is invalid"
            untrusted_reasons.append(screen.reason)
            expected.extend((
                result.element_id,
                screen.detail_class,
                screen.range_basis,
                screen.source,
            ))

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False, profile=profile
    )).split())

    assert text.count("INVALID") == 3
    assert all(token in text for token in expected)
    assert "Review the fatigue inputs and result status" in text
    assert all(reason not in text for reason in untrusted_reasons)


def test_fatigue_report_limits_worked_detail_to_independent_global_extrema():
    inp, out = _fatigue_report_fixture()

    text = " ".join(_pdf_body_text(sector_report.build_report(
        {}, inp, out, figures=False
    )).split())

    # Every independently checked spectrum remains visible in compact evidence.
    assert all(name in text for name in ("Traffic A", "Traffic B", "Traffic C"))
    # Reinforcement and concrete intentionally govern in different spectra.
    assert text.count(
        "Textbook calculation - governing reinforcement fatigue"
    ) == 1
    assert text.count("Textbook calculation - governing concrete fatigue") == 1
    assert "Spectrum - Traffic A" in text
    assert "Spectrum - Traffic B" in text
    assert "Spectrum - Traffic C" not in text
    assert "Governing reinforcement element - R1" in text
    assert "Governing concrete fibre - 4" in text


def test_fatigue_worked_formulas_use_retained_operands(monkeypatch):
    inp, out = _fatigue_report_fixture()
    payload = out["fatigue"]
    steel_bin = payload["spectra"][0].reinforcement[0].bins[0]
    steel_bin.material_factor = 1.234567
    steel_bin.sn_reference_ratio = 7.654321
    concrete_strength = payload["spectra"][1].concrete_strength
    concrete_strength.beta_cc_t0 = 0.923456
    concrete_strength.eta_cc_fat = 0.712345
    concrete_strength.fcd_fat_mpa = 16.54321
    payload["spectra"][1].concrete[0].fcd_fat_mpa = 16.54321

    calls = {}

    def capture(_self, _expression, **kwargs):
        key = kwargs.get("equation_key")
        if key:
            calls.setdefault(key, []).append(kwargs)

    monkeypatch.setattr(sector_report.ReportBuilder, "_formula", capture)
    pdf = sector_report.build_report({}, inp, out, figures=False)

    assert pdf.startswith(b"%PDF")
    assert "1.234567" in calls[
        "fatigue.reinforcement.design-resistance-range"
    ][0]["subst"]
    assert "7.654321" in calls["fatigue.reinforcement.sn-life"][0]["subst"]
    utilisation_subst = calls["fatigue.reinforcement.utilisation"][0]["subst"]
    assert "u<sub>screen</sub>" in utilisation_subst
    assert "0.90410959" in utilisation_subst
    assert "0.92345600" in calls[
        "fatigue.concrete.strength"
    ][0]["subst"]
    assert "0.71234500" in calls["fatigue.concrete.strength"][0]["subst"]
    assert "16.54321000" in calls["fatigue.concrete.strength"][0]["result"]


def test_fatigue_worked_examples_fail_closed_when_operands_are_missing(
    monkeypatch,
):
    inp, out = _fatigue_report_fixture()
    payload = out["fatigue"]
    payload["spectra"][0].reinforcement[0].bins[0].material_factor = None
    payload["spectra"][1].concrete[0].fcd_fat_mpa = None

    calls = []

    def capture(_self, _expression, **kwargs):
        if kwargs.get("equation_key"):
            calls.append(kwargs["equation_key"])

    monkeypatch.setattr(sector_report.ReportBuilder, "_formula", capture)
    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False
    )).split())

    assert text.count("Worked example unavailable") >= 2
    assert not any(key.startswith("fatigue.reinforcement.") for key in calls)
    assert not any(
        key in {
            "fatigue.concrete.normalised-stress",
            "fatigue.concrete.life",
            "fatigue.concrete.bin-damage",
            "fatigue.concrete.miner-sum",
            "fatigue.concrete.equivalent",
            "fatigue.concrete.stress-utilisation",
            "fatigue.concrete.utilisation",
        }
        for key in calls
    )


def test_figures_off_fatigue_report_consumes_completed_payload_only(monkeypatch):
    inp, out = _fatigue_report_fixture()

    def poison(*_args, **_kwargs):
        raise AssertionError("report attempted to recalculate completed fatigue")

    for name in (
        "steel_fatigue_life",
        "concrete_fatigue_strength_result",
        "concrete_fatigue_strength",
        "concrete_fatigue_life",
        "solve_fatigue_bin",
        "analyse_fatigue_spectrum",
    ):
        monkeypatch.setattr(fatigue_core, name, poison)
    monkeypatch.setattr(
        fatigue_analysis, "_global_reinforcement_example", poison
    )
    monkeypatch.setattr(fatigue_analysis, "_global_concrete_example", poison)

    pdf = sector_report.build_report({}, inp, out, figures=False)

    assert pdf.startswith(b"%PDF")


def test_reinforcement_fatigue_lead_and_first_equation_share_bounded_group():
    inp, out = _fatigue_report_fixture()
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, inp, out, figures=False, profile="Audit",
    )

    builder._fatigue()

    matching = []
    for index, flowable in enumerate(builder.flow):
        equations = getattr(flowable, "_sector_equations", ())
        keys = {equation._sector_equation_key for equation in equations}
        if "fatigue.reinforcement.design-stress-range" in keys:
            matching.append((index, flowable, keys))

    assert len(matching) == 1
    index, group, keys = matching[0]
    assert keys == {"fatigue.reinforcement.design-stress-range"}
    assert isinstance(builder.flow[index - 1], sector_report.CondPageBreak)
    paragraphs = [
        item.getPlainText()
        for item in group._content
        if isinstance(item, sector_report.Paragraph)
    ]
    assert re.fullmatch(
        r"\d+\.\d+ Textbook calculation - governing reinforcement fatigue",
        paragraphs[0],
    )
    assert any(
        "globally governing reinforcement element and bin" in text
        for text in paragraphs
    )
    assert any(
        isinstance(item, sector_report._EquationFlowable)
        and item._sector_equation_key
        == "fatigue.reinforcement.design-resistance-range"
        for item in builder.flow[index + 1:]
    )


def test_fatigue_report_has_no_python_max_or_solver_selection_fallback():
    methods = (
        sector_report.ReportBuilder._fatigue,
        sector_report.ReportBuilder._fatigue_reinforcement_formulas,
        sector_report.ReportBuilder._fatigue_concrete_formulas,
    )
    source = "\n".join(textwrap.dedent(inspect.getsource(method)) for method in methods)
    tree = ast.parse(source)

    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "max"
        for node in ast.walk(tree)
    )
    assert all(
        forbidden not in source
        for forbidden in (
            "steel_fatigue_life(",
            "concrete_fatigue_strength_result(",
            "concrete_fatigue_strength(",
            "concrete_fatigue_life(",
            "solve_fatigue_bin(",
            "analyse_fatigue_spectrum(",
            "_global_reinforcement_example(",
            "_global_concrete_example(",
        )
    )


def test_report_includes_damage_equivalent_concrete_method_evidence():
    inp, out = _fatigue_report_fixture()
    payload = out["fatigue"]
    method = "Damage-equivalent stress amplitude"
    inp["fatigue_concrete_method"] = method
    payload["concrete_method"] = method
    payload["concrete_parameters"]["method"] = method
    equivalent_binding = capability_binding(
        DesignBasisKey.PUBLISHED_2023,
        Capability.CONCRETE_FATIGUE_EQUIVALENT,
    )
    payload["calculation_references"]["concrete"] = equivalent_binding.source
    payload["capability_bindings"]["concrete"] = {
        "capability": equivalent_binding.capability.value,
        "source": equivalent_binding.source,
        "disclosure": equivalent_binding.disclosure,
    }
    for spectrum in payload["spectra"]:
        spectrum.concrete_method = method
        for result in spectrum.concrete:
            result.method = method
            result.equivalent_utilisation = 0.82
            result.governing_equivalent_bin = result.bins[0].bin_name
            result.damage = 0.0
            result.damage_utilisation = 0.0
            result.utilisation = 0.82
            for item in result.bins:
                item.damage = 0.0
                item.cycles_to_failure = math.inf
                item.log10_cycles_to_failure = math.inf
                item.equivalent_utilisation = 0.82
        spectrum.concrete_search.method = method
        spectrum.concrete_search.damage = 0.82
        spectrum.concrete_search.upper_damage = 0.821

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False
    )).split())

    assert method in text
    assert "Formula (E.2)" in text
    assert "Equivalent utilisation" in text
    assert "Cycle count" in text and "Not used" in text
    assert "cycle count is not used for concrete" in text


def test_report_discloses_first_generation_formula_6106_bounded_scope():
    inp, out = _fatigue_report_fixture()
    payload = out["fatigue"]
    basis = get_design_basis(DesignBasisKey.FIRST_GEN_DK_NA_2024)
    reinforcement_binding = capability_binding(
        basis.key,
        Capability.REINFORCEMENT_FATIGUE,
    )
    concrete_binding = capability_binding(
        basis.key,
        Capability.CONCRETE_FATIGUE_DAMAGE_SUM,
    )
    inp["fatigue_edition"] = basis.key.value
    payload.update({
        "basis_key": basis.key.value,
        "basis_label": basis.label,
        "basis_disclosure": basis.disclosure,
        "edition": basis.label,
        "solver_edition": concrete_binding.solver_edition,
        "calculation_references": {
            "reinforcement": reinforcement_binding.source,
            "concrete": concrete_binding.source,
        },
        "capability_bindings": {
            "reinforcement": {
                "capability": reinforcement_binding.capability.value,
                "source": reinforcement_binding.source,
                "disclosure": reinforcement_binding.disclosure,
            },
            "concrete": {
                "capability": concrete_binding.capability.value,
                "source": concrete_binding.source,
                "disclosure": concrete_binding.disclosure,
            },
        },
    })

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False
    )).split())

    assert basis.label in text
    assert basis.disclosure in text
    assert "DS/EN 1992-2:2005/AC:2008 Formula 6.106" in text
    assert "Fatigue calculation using a user-supplied section-action spectrum" in text
    assert "section-action spectrum" in text
    scope = text.lower()
    assert "traffic models, dynamic effects, lane/track concurrence" in scope
    assert "owner-specific checks are outside this section calculation" in scope
    assert "first-generation fatigue equations" in text
    assert "user-supplied factors" in text


def test_report_marks_project_defined_concrete_miner_as_uncited():
    inp, out = _fatigue_report_fixture()
    payload = out["fatigue"]
    inp["fatigue_concrete_method"] = CONCRETE_PROJECT_MINER
    payload["concrete_method"] = CONCRETE_PROJECT_MINER
    payload["concrete_parameters"]["method"] = CONCRETE_PROJECT_MINER
    payload["calculation_references"]["concrete"] = (
        "Project-defined concrete Miner S-N relation (uncited)"
    )
    del payload["capability_bindings"]["concrete"]

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False
    )).split())

    assert CONCRETE_PROJECT_MINER in text
    assert "Project-defined / uncited" in text
    assert (
        "No registered standard capability is claimed for this "
        "project-defined relation"
    ) in text
    assert "Project-defined concrete Miner S-N relation (uncited)" in text
    assert Capability.CONCRETE_FATIGUE_DAMAGE_SUM.value not in text
    assert "Formula 6.106" not in text


def test_report_fatigue_chapter_uses_the_engine_failure_state():
    inp, out = _fatigue_report_fixture()
    payload = out["fatigue"]
    payload["warnings"] = ()
    payload["passed"] = False
    payload["utilisation"] = 1.20
    payload["governing_spectrum"] = "Traffic B"
    payload["spectra"][1].passed = False
    payload["spectra"][1].utilisation = 1.20

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False
    )).split())

    assert "FAIL - Traffic B" in text
    assert "120.0 %" in text


def test_report_records_invalid_fatigue_without_suppressing_other_results():
    inp, out = _fatigue_report_fixture()
    basis = get_design_basis(DesignBasisKey.PUBLISHED_2023)
    out["fatigue"] = {
        "valid": False,
        "converged": False,
        "passed": False,
        "errors": (
            "R1: fatigue detail ID is required",
            "At least one fatigue spectrum bin is required",
        ),
        "warnings": (),
        "basis_key": basis.key.value,
        "basis_label": basis.label,
        "basis_disclosure": basis.disclosure,
        "edition": basis.label,
        "solver_edition": fatigue_inputs.EC2_2023,
        "checks": {"reinforcement": True, "concrete": True},
        "basis": inp[fatigue_inputs.BASIS_KEY],
        "calculation_references": {},
        "capability_bindings": {},
        "partial_factors": {
            "gamma_c": 1.50,
            "gamma_s": 1.15,
            "gamma_ff": 1.10,
        },
        "concrete_parameters": None,
        "fatigue_detail_basis": (),
        "spectra": (),
        "governing_spectrum": None,
        "utilisation": None,
    }

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False
    )).split())

    assert "INVALID - fatigue not assessed" in text
    assert "other requested analyses were calculated" in text
    assert "R1: fatigue detail ID is required" not in text
    assert "At least one fatigue spectrum bin is required" not in text
    assert "Review the calculation inputs and recalculate before using this report" in text
    assert "No fatigue resistance verdict has been issued" in text
    assert "No fatigue calculation method was applied" in text
    assert "No fatigue methodology or resistance verdict was applied" in text
    assert "Each named spectrum is checked independently" not in text
    assert "Grouped fatigue spectra are assessed independently" not in text


def test_report_escapes_user_defined_fatigue_settings():
    inp, out = _fatigue_report_fixture()
    payload = out["fatigue"]
    payload["governing_spectrum"] = "Traffic <A> & B"
    payload["basis"]["notes"] = "Register A & B <issued>"
    payload["fatigue_detail_basis"][0]["name"] = "Bar <detail> & coupler"
    payload["fatigue_detail_basis"][0]["source"] = "Drawing A&B <rev 2>"

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False
    )).split())

    assert "Traffic <A> & B" in text
    assert "Register A & B <issued>" in text
    assert "Bar <detail> & coupler" in text
    assert "Drawing A&B <rev 2>" in text


def test_report_preserves_literal_engineering_token_identifiers():
    inp, out = _fatigue_report_fixture()
    literal_name = "sigma gamma phi alpha beta eta"
    out["fatigue"]["governing_spectrum"] = literal_name
    out["fatigue"]["spectra"][0].spectrum_name = literal_name

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False
    )).split())

    assert literal_name in text
    protected = sector_report._greek(sector_report._html_escape(literal_name))
    assert "&#951;" not in protected  # no beta -> b + Greek eta suffix collision


def test_report_preserves_notation_like_case_and_cover_identities():
    inp = _inp()
    inp["plastic_case"]["id"] = "Case 1e-12 % in 100 m2"
    meta = {
        "proj_no": "Project 2E+03 deg",
        "proj_name": "Bridge 100 m2",
        "section": "Section cm3 / mm4",
        "rev": "1e-9%",
        "author": "Engineer 1,25e-6",
    }

    text = " ".join(_pdf_text(sector_report.build_report(
        meta, inp, _out(), figures=False
    )).split())

    for literal in (*meta.values(), inp["plastic_case"]["id"]):
        assert literal in text


def test_report_escapes_hostile_comments_without_activating_link_markup():
    import pypdf

    url = "https://attacker.invalid/review?left=1&right=2"
    comments = f'Check A < B & C; <link href="{url}">open review</link>'
    pdf = sector_report.build_report(
        {"comments": comments}, _inp(), _out(), figures=False, profile="Brief"
    )
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = " ".join(
        " ".join((page.extract_text() or "").split()) for page in reader.pages
    )
    uri_actions = []
    for page in reader.pages:
        for reference in page.get("/Annots", ()):
            annotation = reference.get_object()
            action = annotation.get("/A")
            if action is not None:
                action = action.get_object()
                if action.get("/URI") is not None:
                    uri_actions.append(str(action["/URI"]))

    assert comments in text
    assert uri_actions == []


def test_report_adoption_warning_covers_used_2023_material_catalogues():
    concrete = _inp()
    concrete["concrete_preset"] = "EN 1992-1-1:2023"

    reinforcement = _inp()
    reinforcement.update({
        "bar_elements": [{"material_id": "M2"}],
        "mild_material_catalog": {
            "items": [
                {"id": "M1", "preset": "EN 1992-1-1:2005"},
                {"id": "M2", "preset": "EN 1992-1-1:2023"},
            ],
        },
    })

    prestress = _inp()
    prestress.update({
        "bars": [],
        "tendons": [(0.0, -0.12, 5.0e-4)],
        "tendon_elements": [{"material_id": "P2"}],
        "prestress_material_catalog": {
            "items": [
                {"id": "P1", "preset": "EN 1992-1-1:2005"},
                {"id": "P2", "preset": "EN 1992-1-1:2023"},
            ],
        },
    })

    for inp in (concrete, reinforcement, prestress):
        assert "2023 reference option requires project adoption" in (
            sector_report._report_adoption_warning(inp)
        )


def test_report_adoption_warning_ignores_unused_2023_catalogue_entries():
    inp = _inp()
    inp.update({
        "bar_elements": [{"material_id": "M2"}],
        "mild_material_catalog": {
            "items": [
                {"id": "M1", "preset": "EN 1992-1-1:2023"},
                {"id": "M2", "preset": "EN 1992-1-1:2005"},
            ],
        },
    })

    assert sector_report._report_adoption_warning(inp) == ""


def test_report_api_retains_legacy_qa_appendix_positional_slot():
    build_parameters = tuple(
        inspect.signature(_build_report_from_completed_payload).parameters
    )
    builder_parameters = tuple(inspect.signature(
        sector_report.ReportBuilder
    ).parameters)

    assert build_parameters[6:8] == ("qa_appendix", "profile")
    assert builder_parameters[7:9] == ("qa_appendix", "profile")
    standard = sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, "", False, None, False
    )
    audit = sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, "", False, None, True
    )
    assert standard.profile.key == "Standard"
    assert audit.profile.key == "Audit"


def test_report_outline_decodes_literal_engineering_token_case_id():
    import io
    import pypdf

    inp = _inp()
    inp["plastic_case"]["id"] = "sigma"
    pdf = sector_report.build_report({}, inp, _out(), figures=False)
    reader = pypdf.PdfReader(io.BytesIO(pdf))

    titles = []
    pending = list(reader.outline)
    while pending:
        item = pending.pop(0)
        if isinstance(item, list):
            pending[0:0] = item
        else:
            titles.append(str(getattr(item, "title", item)))

    assert any(title.endswith("sigma") for title in titles)
    assert not any("&#115;igma" in title for title in titles)


def test_report_contents_escape_decoded_hostile_case_heading():
    import pypdf

    inp = _inp()
    url = "https://attacker.invalid/case"
    case_id = f'PL <link href="{url}">open review</link> & literal'
    inp["plastic_case"]["id"] = case_id

    reader = pypdf.PdfReader(io.BytesIO(
        sector_report.build_report({}, inp, _out(), figures=False)
    ))
    text = " ".join(
        " ".join((page.extract_text() or "").split()) for page in reader.pages
    )
    outline_titles = []
    pending = list(reader.outline)
    while pending:
        item = pending.pop(0)
        if isinstance(item, list):
            pending[0:0] = item
        else:
            outline_titles.append(str(getattr(item, "title", item)))
    uri_actions = []
    for page in reader.pages:
        for reference in page.get("/Annots", ()):
            action = reference.get_object().get("/A")
            if action is not None and action.get_object().get("/URI") is not None:
                uri_actions.append(str(action.get_object()["/URI"]))

    assert case_id in text
    assert any(title.endswith(case_id) for title in outline_titles)
    assert uri_actions == []


def test_report_preserves_negative_infinite_concrete_log_life():
    inp, out = _fatigue_report_fixture()
    concrete_bin = out["fatigue"]["spectra"][1].concrete[0].bins[0]
    concrete_bin.log10_cycles_to_failure = -math.inf

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False
    )).split())

    assert "-inf" in text


def test_report_fatigue_chapter_requests_all_engineering_figures(monkeypatch):
    inp, out = _fatigue_report_fixture()
    titles = []

    monkeypatch.setattr(sector_report, "ensure_image_server", lambda: None)

    def capture(_self, figure, *_args, **_kwargs):
        titles.append(str(figure.layout.title.text or ""))

    monkeypatch.setattr(sector_report.ReportBuilder, "_fig", capture)
    sector_report.build_report({}, inp, out, figures=True)

    assert sum(title.startswith("Fatigue utilisation") for title in titles) == 2
    assert sum(title.startswith("S-N assessment") for title in titles) == 1
    assert sum(title.startswith("Miner damage - R1") for title in titles) == 1
    assert sum(
        title.startswith("Miner damage - concrete fibre")
        for title in titles
    ) == 1


def test_report_pdf_generates():
    pdf = sector_report.build_report(
        {"proj_no": "P-1", "author": "KLA", "source_revision": "a" * 40},
        _inp(), _out(), version="0.1.0", figures=False,
    )
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 3000


def test_report_shared_preparation_survives_poisoned_calculators(monkeypatch):
    """A completed elastic payload is the report's only numerical authority."""

    entry = material_catalog.default_entry(
        "prestress", preset="Curve 1 (built-in)"
    )
    law = material_catalog.build_material(entry, "prestress")
    inp = _inp()
    inp.update({
        "mode": "Elastic",
        "tendons": [(0.0, -0.12, 5.0e-4)],
        "tendon_elements": [{
            "id": "T1", "x_mm": 0.0, "y_mm": -120.0,
            "area_mm2": 500.0, "diameter_mm": 25.23,
            "size_mode": "Area", "material_id": "P1",
            "fatigue_detail_id": "",
        }],
        "prestress_material_catalog": {
            "version": 1, "next_id": 2, "items": [entry],
        },
        "prestress_materials": {"P1": law},
        "tendon_materials": [law],
        "prestress": law,
        "prestress_preset": entry["preset"],
    })
    locked_stress = law.Es * law.IS
    force = locked_stress * 500.0 / 1000.0
    out = _out()
    out.pop("plastic")
    out["material_properties"]["prestress"] = [{
        "material_id": "P1",
        "characteristic_stress_at_rupture_mpa": law.stress(
            law.rupture_strain, design=False
        ),
    }]
    out["prestress_initial"] = {
        "elements": [{
            "tendon_index": 0, "element_id": "T1", "material_id": "P1",
            "initial_strain": law.IS, "modulus_mpa": law.Es,
            "locked_in_stress_mpa": locked_stress, "area_mm2": 500.0,
            "force_kn": force, "x_m": 0.0, "y_m": -0.12,
            "mx_knm": force * -0.12, "my_knm": 0.0,
        }],
        "internal_resultant_origin": {
            "n_kn": force, "mx_knm": force * -0.12, "my_knm": 0.0,
        },
        "equivalent_action_origin": {
            "n_kn": -force, "mx_knm": force * -0.12, "my_knm": 0.0,
        },
    }
    out["elastic_shared"]["materials"].append({
        "material_id": "P1", "material_family": "prestress",
        "modulus_mpa": law.Es, "short_term": law.Es / 33_000.0,
        "long_term": law.Es / 33_000.0 * 2.475,
    })

    def poisoned(*_args, **_kwargs):
        raise AssertionError("report reran an engineering calculator")

    for module, names in (
        (geometry, ("area_moment_breakdown", "area_moments",
                    "area_moments_rings")),
        (capacity, ("design_yield", "locked_in_prestress_result",
                    "prestress_resultants")),
        (elastic_core, ("calculate_modular_ratios",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, poisoned)
    monkeypatch.setattr(Concrete, "fcd", property(poisoned))
    monkeypatch.setattr(Concrete, "stress", poisoned)
    monkeypatch.setattr(MildSteel, "stress", poisoned)
    monkeypatch.setattr(Prestress, "stress", poisoned)

    pdf = sector_report.build_report(
        {}, inp, out, figures=False, qa_appendix=False,
    )
    text = " ".join(_pdf_text(pdf).split())
    assert pdf[:4] == b"%PDF"
    assert "Concrete section properties" in text
    assert "Design strength" in text
    assert "Initial prestress action" in text
    assert "Elastic material transformation" in text


def _many_retained_curvature_candidates(candidate_count=29):
    candidates = [{
        "mode": "concrete_crushing",
        "element_index": None,
        "element_id": None,
        "strain_limit": 0.003440392741656883,
        "distance_from_na_m": 0.175,
        "curvature_per_m": 0.01965938709518219,
        "selected": True,
    }]
    for index in range(1, candidate_count):
        curvature = 0.03 + index / 1000.0
        candidates.append({
            "mode": "bar_tension_rupture",
            "element_index": index - 1,
            "element_id": f"A01-R-{index:02d}",
            "strain_limit": curvature * 0.05,
            "distance_from_na_m": 0.05,
            "curvature_per_m": curvature,
            "selected": False,
        })
    return candidates


def test_curvature_selection_substitution_is_bounded_and_retained():
    one = [{"selected": True, "curvature_per_m": 0.02}]
    one_before = copy.deepcopy(one)
    selected = {"curvature_per_m": 0.02}
    selected_before = copy.deepcopy(selected)

    assert sector_report._curvature_selection_substitution(one, selected) == (
        "= min(kappa<sub>1</sub>) = kappa<sub>1</sub> = 0.020000000 1/m"
    )
    assert one == one_before
    assert selected == selected_before

    tied = [
        {"selected": False, "curvature_per_m": 0.02},
        {"selected": True, "curvature_per_m": 0.02},
    ]
    assert sector_report._curvature_selection_substitution(tied, selected) == (
        "= min(kappa<sub>i=1:2</sub>) = kappa<sub>2</sub> = "
        "0.020000000 1/m"
    )

    many = _many_retained_curvature_candidates()
    many_before = copy.deepcopy(many)
    substitution = sector_report._curvature_selection_substitution(
        many,
        {"curvature_per_m": many[0]["curvature_per_m"]},
    )
    assert substitution == (
        "= min(kappa<sub>i=1:29</sub>) = kappa<sub>1</sub> = "
        "0.019659387 1/m"
    )
    assert "," not in substitution
    assert all(
        sector_report._fmt(candidate["curvature_per_m"], 9) not in substitution
        for candidate in many[1:]
    )
    assert many == many_before


def test_complete_profiles_compact_many_curvature_candidates_without_loss():
    out = _out()
    candidates = _many_retained_curvature_candidates()
    point = out["plastic"]["points"][0]
    point["curvature_candidates"] = copy.deepcopy(candidates)
    point["curvature_selection"] = {
        "mode": candidates[0]["mode"],
        "element_index": candidates[0]["element_index"],
        "curvature_per_m": candidates[0]["curvature_per_m"],
    }
    before = copy.deepcopy(out)

    standard_pdf = sector_report.build_report(
        {}, _inp(), out, figures=False, profile="Standard"
    )
    assert standard_pdf[:4] == b"%PDF"
    standard = " ".join(_pdf_text(standard_pdf).split())
    assert "Governing ultimate curvature" in standard
    assert "Ultimate-curvature candidates" not in standard
    assert "i = 1 : 29" in standard
    assert "1.966e-2" in standard
    for candidate in candidates[1:]:
        assert candidate["element_id"] not in standard
        assert sector_report._fmt(candidate["curvature_per_m"], 8) not in standard

    audit_pdf = sector_report.build_report(
        {}, _inp(), out, figures=False, profile="Audit"
    )
    assert audit_pdf[:4] == b"%PDF"
    audit = " ".join(_pdf_text(audit_pdf).split())
    assert "Ultimate-curvature candidates" in audit
    assert "i = 1 : 29" in audit
    assert "1.966e-2" in audit
    assert "0.01965939" in audit
    for candidate in candidates[1:]:
        assert candidate["element_id"] in audit
        assert sector_report._fmt(candidate["curvature_per_m"], 8) in audit

    brief = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), out, figures=False, profile="Brief"
    )).split())
    assert "Ultimate-curvature candidates" not in brief
    assert out == before


def test_curvature_selection_is_not_inferred_from_incomplete_retained_evidence(
    monkeypatch,
):
    out = _out()
    point = out["plastic"]["points"][0]
    point["curvature_candidates"] = _many_retained_curvature_candidates(2)
    for candidate in point["curvature_candidates"]:
        candidate["selected"] = False
    before = copy.deepcopy(out)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("report inferred a missing selected candidate")

    monkeypatch.setattr(
        sector_report,
        "_curvature_selection_substitution",
        forbidden,
    )
    pdf = sector_report.build_report(
        {}, _inp(), out, figures=False, profile="Standard"
    )
    text = " ".join(_pdf_text(pdf).split())
    assert "Ultimate-curvature candidates" not in text
    assert "governing ultimate curvature" not in text
    assert out == before

    audit_text = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), out, figures=False, profile="Audit"
    )).split())
    assert "Ultimate-curvature candidates" in audit_text

    absent = copy.deepcopy(out)
    absent_point = absent["plastic"]["points"][0]
    absent_point.pop("curvature_candidates")
    absent_point.pop("curvature_selection")
    absent_before = copy.deepcopy(absent)
    absent_text = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), absent, figures=False, profile="Standard"
    )).split())
    assert "Ultimate-curvature candidates" not in absent_text
    assert absent == absent_before


def test_report_publishes_retained_plastic_and_elastic_textbook_chains():
    text = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), _out(), figures=False, qa_appendix=False,
    )).split())

    for heading in (
        "Worked plastic calculation (utilisation direction)",
        "Converged strain plane",
        "Governing ultimate curvature",
        "Compression-depth solution",
        "Section resultants at convergence",
        "Step 1 - converged long-term state",
        "Step 2 - neutralise the long-term concrete stress",
        "Step 3 - converged instantaneous combined state",
        "Step 4 - combine the element stress components",
    ):
        assert heading in text
    assert "3.5e-3" in text
    assert "0.175 m" in text
    assert "Compression-zone depth c 175.000 mm" in text
    assert "Bisection iterations 8" in text
    assert "250 + -250 + 0 kN" in text
    assert "100 MPa" in text
    assert "59.596 MPa" in text
    assert "internal bisection sequence and integration bands are not published" in (
        text.casefold()
    )
    assert "converged reference-stress plane" in text
    assert "not a physical-unit norm" in text


def test_report_uses_retained_nonzero_worked_point_for_both_depth_rows():
    out = _out()
    first = out["plastic"]["points"][0]
    first["compression_depth"] = 0.111
    second = copy.deepcopy(first)
    second["V"] = 45.0
    second["compression_depth"] = 0.222
    out["plastic"]["points"] = [first, second]
    out["plastic"]["worked_point_index"] = 1
    before = copy.deepcopy(out)

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), out, figures=False, qa_appendix=False,
    )).split())

    assert "Selected sweep point 2 of 2" in text
    assert "Compression-zone depth c 222.000 mm" in text
    assert "Lever components zx, zy" in text
    assert "lever-arm components, not effective depth d" not in text
    assert "Solved compression depth 222.000000 mm" in text
    assert "Compression-zone depth c 111.000 mm" not in text
    assert "Solved compression depth 111.000000 mm" not in text
    assert out == before


def test_audit_report_reconciles_plastic_arm_source_and_face_specific_depths():
    inp = _inp()
    out = _out()
    out["plastic"]["effective_depths"] = capacity.plastic_effective_depths(inp)
    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False, profile="Audit",
    )).split())

    assert "Source: PL-TEST" in text
    assert "Internal lever arm z" in text
    assert "Lever components zx, zy" in text
    assert "Face-specific effective depth" in text
    for face in ("bottom (-y)", "top (+y)", "left (-x)", "right (+x)"):
        assert face in text
    assert "Tension bars" in text
    assert "Asl centroid" in text


@pytest.mark.parametrize(
    "retained",
    (None, True, "0.175", -0.175, math.nan, math.inf),
)
def test_report_keeps_malformed_compression_depth_unavailable(retained):
    out = _out()
    point = out["plastic"]["points"][0]
    if retained is None:
        point.pop("compression_depth")
    else:
        point["compression_depth"] = retained
    before = copy.deepcopy(out)

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), out, figures=False, qa_appendix=False,
    )).split())

    assert "Compression-zone depth c -" in text
    assert "Compression-depth solution unavailable" in text
    assert "Solved compression depth" not in text
    assert out == before


def test_completed_textbook_report_never_calls_a_solver_or_material_law(monkeypatch):
    def poisoned(*_args, **_kwargs):
        raise AssertionError("report reran an engineering calculator")

    for module, names in (
        (plastic_core, (
            "solve_plastic", "solve_interaction", "_curvature_at_depth",
            "_accumulate", "_accumulate_at_depth",
        )),
        (elastic_core, (
            "solve_elastic", "solve_elastic_uncracked", "solve_elastic_combined",
            "transformed_properties", "_newton_solve",
        )),
        (shear_core, (
            "vrd_c", "vrd_c_2023", "vrd_links", "vrd_links_2023",
            "optimum_strut_angle",
        )),
        (torsion_core, (
            "stiffness_distribution_result", "trd_s_result", "trd_max_result",
            "trd_c_result", "asl_required_result", "select_torsion_resistance",
        )),
        (combined_core, (
            "crushing_interaction_result", "governing_strut_result",
            "dkna_interaction_result", "longitudinal_check",
        )),
    ):
        for name in names:
            monkeypatch.setattr(module, name, poisoned)
    monkeypatch.setattr(Concrete, "stress", poisoned)
    monkeypatch.setattr(MildSteel, "stress", poisoned)
    monkeypatch.setattr(Prestress, "stress", poisoned)

    pdf = sector_report.build_report(
        {}, _inp(), _out(), figures=False, qa_appendix=False,
    )
    assert pdf[:4] == b"%PDF"


def test_textbook_report_fails_closed_when_retained_state_is_incomplete():
    out = _out()
    point = out["plastic"]["points"][0]
    point.pop("search_lower_depth")
    point.pop("concrete_mx")
    out["elastic"].pop("accepted_states")

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), out, figures=False, qa_appendix=False,
    )).split())

    assert "Compression-depth solution unavailable" in text
    assert "converged bracket, depth and residual summary are unavailable" in text
    assert "Section resultants at convergence unavailable" in text
    assert "concrete, mild-steel or tendon resultants are unavailable" in text
    assert "Worked elastic calculation unavailable" in text
    assert "converged elastic states are unavailable" in text


def test_transverse_textbook_report_fails_closed_without_retained_operands():
    out = _out()
    shear = _shear_out()
    shear["links"] = _links_out()
    shear["links"]["res"].pop("tan")
    torsion = _torsion_out()
    torsion.pop("strut_resistance")
    combined = _combined_out()
    combined.pop("dkna_selection")
    out.update(shear=shear, torsion=torsion, combined=combined)

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), out, figures=False, qa_appendix=False,
    )).split())

    assert "selected strut-angle terms are missing" in text
    assert "selected torsion terms are unavailable" in text
    assert "required DK NA component sums are unavailable" in text
    assert "EQ-SHEAR.LINKS.VRDS" not in text
    assert "EQ-TORSION.RESISTANCE.GOVERNING" not in text
    assert "EQ-COMBINED.DK-NA.SUM" not in text


def test_textbook_report_methods_have_no_engineering_fallbacks():
    source = "\n".join((
        inspect.getsource(sector_report.ReportBuilder._plastic_worked),
        inspect.getsource(sector_report.ReportBuilder._elastic_worked),
        inspect.getsource(sector_report.ReportBuilder._shear),
        inspect.getsource(sector_report.ReportBuilder._shear_direction),
        inspect.getsource(sector_report.ReportBuilder._shear_links),
        inspect.getsource(sector_report.ReportBuilder._torsion),
        inspect.getsource(sector_report.ReportBuilder._subtube_section),
        inspect.getsource(sector_report.ReportBuilder._combined),
        inspect.getsource(sector_report.ReportBuilder._combined_direction),
    ))
    forbidden = (
        ".stress(",
        "solve_plastic(",
        "solve_interaction(",
        "_curvature_at_depth(",
        "_accumulate(",
        "solve_elastic(",
        "solve_elastic_combined(",
        "transformed_properties(",
        "_newton_solve(",
        "max(pts",
        "1.0 / lk['cot']",
        "t['cot'] / (1.0 + t['cot'] ** 2)",
        "stiffness_distribution_result(",
        "trd_s_result(",
        "trd_max_result(",
        "crushing_interaction_result(",
        "dkna_interaction_result(",
        "governing_strut_result(",
    )
    assert not [pattern for pattern in forbidden if pattern in source]


def test_report_shared_blocks_have_no_engineering_fallbacks():
    source = inspect.getsource(sector_report.ReportBuilder)
    forbidden = (
        "math.sqrt(4.0 * point[2] / math.pi)",
        "c.fcd",
        "st.fytk / st.gamma_y",
        "p.stress(",
        "material.Es / ec_mpa",
        "ns_v * (1.0 + phi)",
        "area_moment_breakdown(",
        "area_moments(",
        "area_moments_rings(",
        "design_yield(",
        "locked_in_prestress_result(",
        "prestress_resultants(",
        "calculate_modular_ratios(",
    )
    assert not [pattern for pattern in forbidden if pattern in source]


def test_report_includes_minimum_reinforcement_and_clear_spacing_evidence():
    inp = _inp()
    inp.update({
        "mode": "Plastic",
        "minimum_reinforcement_on": True,
        "clear_spacing_on": True,
        "detailing_edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "detailing_d_upper": 16.0,
        "detailing_include_tendons": False,
        "bars": [(-0.04, -0.12, 314.0), (0.04, -0.12, 314.0)],
        "bar_elements": [
            {
                "id": "R1", "x_mm": -40.0, "y_mm": -120.0,
                "area_mm2": 314.0, "diameter_mm": 20.0,
                "size_mode": "Diameter", "material_id": "M1",
                "fatigue_detail_id": "",
            },
            {
                "id": "R2", "x_mm": 40.0, "y_mm": -120.0,
                "area_mm2": 314.0, "diameter_mm": 20.0,
                "size_mode": "Diameter", "material_id": "M1",
                "fatigue_detail_id": "",
            },
        ],
    })
    minimum = {
        "status": "PASS",
        "edition": inp["detailing_edition"],
        "clause": "9.2.1.1(1), Formula (9.1N)",
        "checks": [{
            "type": "minimum area", "status": "PASS", "axis": "xy",
            "face": "resultant tension zone",
            "as_provided_mm2": 628.0, "as_min_mm2": 81.432,
            "utilisation": 81.432 / 628.0, "bt_mm": 200.0,
            "d_mm": 270.0, "fctm_mpa": 2.9, "fyk_mpa": 500.0,
            "strength_coefficient": 0.26 * 2.9 / 500.0,
            "floor_coefficient": 0.0013,
            "selected_coefficient": 0.26 * 2.9 / 500.0,
            "governing_coefficient": "0.26 fctm / fyk",
            "bar_ids": ["R1", "R2"],
        }],
        "limitations": ["Prestressing tendons are not credited."],
    }
    spacing = {
        "status": "PASS", "edition": inp["detailing_edition"],
        "clause": "8.2(2)", "d_upper_mm": 16.0,
        "governing": {
            "status": "PASS", "first_id": "R1", "second_id": "R2",
            "first_kind": "bar", "second_kind": "bar", "clear_mm": 60.0,
            "required_mm": 21.0, "margin_mm": 39.0,
            "dx_mm": 80.0, "dy_mm": 0.0, "centre_distance_mm": 80.0,
            "phi_first_mm": 20.0, "phi_second_mm": 20.0,
            "required_candidates_mm": {
                "larger element diameter": 20.0,
                "aggregate allowance": 21.0,
                "absolute minimum": 20.0,
            },
            "governing_requirement": "aggregate allowance",
        },
        "pairs": [],
        "limitations": ["Pairwise edge-to-edge distance is checked."],
    }
    spacing["pairs"] = [dict(spacing["governing"])]

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp,
        {"minimum_reinforcement": minimum, "clear_spacing": spacing},
        figures=False,
    )).split())

    assert "Longitudinal minimum reinforcement" in text
    assert "Mx + My" in text
    assert "resultant tension zone" in text
    assert "A s,min" in text or "As,min" in text
    assert "Reinforcement clear spacing" in text
    assert "R1 - R2" in text
    assert "1.508e-3" in text
    assert "1.3e-3" in text
    assert "81.432 mm" in text
    assert "aggregate allowance" in text
    assert "80" in text and "60 mm" in text
    assert "Lap / bundle ID" not in text
    assert "D upper = 16.0 mm" in text or "Dupper = 16.0 mm" in text


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_report_profiles_publish_core_m02_refinement_evidence(profile):
    inp = _inp()
    inp.update({
        "mode": "Plastic",
        "minimum_reinforcement_on": True,
        "detailing_edition": detailing.EC2_2023,
        "detailing_member_type": "Beam",
        "detailing_cut_direction": detailing.CUT_TRANSVERSE,
    })
    minimum = {
        "status": "FAIL",
        "edition": detailing.EC2_2023,
        "clause": "12.2(2)(a), Formula (12.1)",
        "member_type": "Beam",
        "cut_direction": detailing.CUT_TRANSVERSE,
        "checks": [{
            "type": "bending with axial force",
            "status": "FAIL",
            "utilisation": 1.0005909664448163,
            "m_cr_knm": 800.7222093632556,
            "mr_nom_knm": 800.249288886036,
            "cracking_factor": 800.7222093632556,
            "cracking_fctm_mpa": 7.258066978469918,
            "cracking_governing_axial_stress_mpa": 0.0,
            "cracking_governing_bending_stress_mpa": (
                7.258066978469918 / 800.7222093632556
            ),
            "model": "biaxial refined nominal envelope",
            "nominal_axial_resistance_kn": 1609.0,
            "axial_feasible": True,
            "as_provided_mm2": 3218.0,
            "bar_ids": ["R1", "R2", "R3", "R4", "R5", "R6"],
            "nominal_solution": {
                "resolution_state": "RESOLVED",
                "governing_increment_deg": 0.1,
                "governing_target_increment_deg": 0.1,
                "governing_interval_deg": 0.083,
                "accepted_point_count": 65,
                "all_points_converged": True,
                "utilisation_lower_bound": 1.00056,
                "utilisation_upper_bound": 1.00062,
                "refinement_history": [
                    {"target_increment_deg": 15.0},
                    {"target_increment_deg": 1.0},
                    {"target_increment_deg": 0.1},
                ],
            },
        }],
        "limitations": [],
    }
    actions = {
        "name": "CORE-M02-357",
        "description": "Refined nominal resistance",
        "n_ed_kn": 0.0,
        "mx_ed_knm": 0.9986295347545738,
        "my_ed_knm": -0.05233595624294437,
        "vx_ed_kn": 0.0,
        "vy_ed_kn": 0.0,
        "vx_face": "auto",
        "vy_face": "auto",
        "t_ed_knm": 0.0,
        "check_minimum_reinforcement": True,
    }
    inp["plastic_cases"] = [actions]
    out = {
        "plastic_cases": [{
            "actions": actions,
            "evaluated": True,
            "results": {"minimum_reinforcement": minimum},
        }]
    }

    text = " ".join(_pdf_text(sector_report.build_report(
        {},
        inp,
        out,
        figures=False,
        profile=profile,
    )).split())

    assert "FAIL" in text
    assert "MR,nom 800.2 kNm; Mcr 800.7 kNm" in text
    if profile == "Brief":
        assert "CORE-M02-357" in text
        return
    assert "100.1 %" in text
    assert "governing utilisation" in text
    assert "Angular resolution: initial 15° envelope" in text
    assert "achieved governing interval 0.083° for the 0.100° target" in text
    assert "65 angles retained; all retained angles converged; assessment resolved" in text
    assert "utilisation interval 100.0560 to 100.0620 %" in text


def test_report_maps_unresolved_core_m02_result_to_engineering_guidance():
    inp = _inp()
    inp.update({
        "mode": "Plastic",
        "minimum_reinforcement_on": True,
        "detailing_edition": detailing.EC2_2023,
        "detailing_member_type": "Beam",
        "detailing_cut_direction": detailing.CUT_TRANSVERSE,
    })
    reason = (
        "nominal resistance is too close to the cracking demand for a stable "
        "assessment at the available angular resolution"
    )
    minimum = {
        "status": "NOT ASSESSED",
        "reason": reason,
        "edition": detailing.EC2_2023,
        "clause": "12.2(2)(a), Formula (12.1)",
        "member_type": "Beam",
        "cut_direction": detailing.CUT_TRANSVERSE,
        "checks": [{
            "type": "bending with axial force",
            "status": "NOT ASSESSED",
            "utilisation": None,
            "m_cr_knm": 800.0,
            "mr_nom_knm": None,
            "reason": reason,
            "model": "biaxial refined nominal envelope",
            "nominal_solution": {
                "resolution_state": "UNRESOLVED",
                "governing_increment_deg": 0.01,
                "governing_target_increment_deg": 0.01,
                "governing_interval_deg": 0.0095,
                "accepted_point_count": 83,
                "all_points_converged": True,
                "utilisation_lower_bound": 0.9999995,
                "utilisation_upper_bound": 1.0000015,
                "refinement_history": [
                    {"target_increment_deg": 15.0},
                    {"target_increment_deg": 1.0},
                    {"target_increment_deg": 0.1},
                    {"target_increment_deg": 0.01},
                ],
            },
        }],
        "limitations": [],
    }
    actions = {
        "name": "CORE-M02-LIMIT",
        "description": "Unresolved nominal resistance",
        "n_ed_kn": 0.0,
        "mx_ed_knm": 1.0,
        "my_ed_knm": 0.0,
        "vx_ed_kn": 0.0,
        "vy_ed_kn": 0.0,
        "vx_face": "auto",
        "vy_face": "auto",
        "t_ed_knm": 0.0,
        "check_minimum_reinforcement": True,
    }
    inp["plastic_cases"] = [actions]
    out = {
        "plastic_cases": [{
            "actions": actions,
            "evaluated": True,
            "results": {"minimum_reinforcement": minimum},
        }]
    }

    text = " ".join(_pdf_text(sector_report.build_report(
        {},
        inp,
        out,
        figures=False,
        profile="Standard",
    )).split())

    assert "NOT ASSESSED - The nominal resistance is too close" in text
    assert "assess this case separately" in text
    assert "achieved governing interval 0.009° for the 0.010° target" in text
    assert "utilisation interval 99.9999 to 100.0002 %" in text
    assert "separate assessment required" in text
    assert "available angular resolution" not in text


@pytest.mark.parametrize("profile", ("Standard", "Audit"))
def test_report_hides_retained_angle_boundary_for_moved_direction_failure(
    profile,
):
    inp = _inp()
    inp.update({
        "mode": "Plastic",
        "minimum_reinforcement_on": True,
        "detailing_edition": detailing.EC2_2023,
        "detailing_member_type": "Beam",
        "detailing_cut_direction": detailing.CUT_TRANSVERSE,
    })
    reason = "nominal governing interval could not be refined consistently"
    minimum = {
        "status": "NOT ASSESSED",
        "reason": reason,
        "edition": detailing.EC2_2023,
        "clause": "12.2(2)(a), Formula (12.1)",
        "member_type": "Beam",
        "cut_direction": detailing.CUT_TRANSVERSE,
        "checks": [{
            "type": "bending with axial force",
            "status": "NOT ASSESSED",
            "utilisation": None,
            "m_cr_knm": 800.0,
            "mr_nom_knm": None,
            "reason": reason,
            "model": "biaxial refined nominal envelope",
            "nominal_solution": {
                "resolution_state": "UNRESOLVED",
                "governing_increment_deg": 0.01,
                "governing_target_increment_deg": 0.01,
                "governing_interval_deg": 15.0,
                "accepted_point_count": 3080,
                "all_points_converged": True,
                "utilisation_lower_bound": None,
                "utilisation_upper_bound": None,
                "refinement_history": [
                    {"target_increment_deg": 15.0},
                    {"target_increment_deg": 1.0},
                    {"target_increment_deg": 0.1},
                    {"target_increment_deg": 0.01},
                ],
            },
        }],
        "limitations": [],
    }
    actions = {
        "name": "CORE-M02-MOVED",
        "description": "Moving nominal resistance direction",
        "n_ed_kn": 0.0,
        "mx_ed_knm": 1.0,
        "my_ed_knm": 0.0,
        "vx_ed_kn": 0.0,
        "vy_ed_kn": 0.0,
        "vx_face": "auto",
        "vy_face": "auto",
        "t_ed_knm": 0.0,
        "check_minimum_reinforcement": True,
    }
    inp["plastic_cases"] = [actions]
    out = {
        "plastic_cases": [{
            "actions": actions,
            "evaluated": True,
            "results": {"minimum_reinforcement": minimum},
        }]
    }

    text = " ".join(_pdf_text(sector_report.build_report(
        {},
        inp,
        out,
        figures=False,
        profile=profile,
    )).split())

    assert (
        "NOT ASSESSED - The governing nominal resistance direction could not "
        "be refined consistently" in text
    )
    assert "assess this case separately" in text
    assert "achieved governing interval 15.000° for the 0.010° target" in text
    assert "3080 angles retained" in text
    assert "separate assessment required" in text
    assert "4097" not in text
    assert "point limit" not in text.lower()
    assert "PLASTIC_SWEEP_MAX_POINTS" not in text
    assert "refinement_window_count" not in text


def test_report_publishes_canonical_direction_and_html_safe_project_alias():
    inp = _inp()
    inp.update({
        "mode": "Plastic",
        "minimum_reinforcement_on": True,
        "detailing_edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "detailing_member_type": "Slab",
        "detailing_cut_direction": detailing.CUT_LONGITUDINAL,
        "modelled_direction_alias": "sigma m2 1e-3 <north>",
    })
    minimum = {
        "status": "NOT ASSESSED",
        "reason": "No selected capacity case.",
        "edition": inp["detailing_edition"],
        "clause": "9.2.1.1(1), Formula (9.1N)",
        "member_type": "Slab",
        "cut_direction": detailing.CUT_LONGITUDINAL,
        "modelled_reinforcement_direction": "transverse",
        "checks": [],
    }

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, {"minimum_reinforcement": minimum}, figures=False,
    )).split())

    label = "Transverse (project alias: sigma m2 1e-3 <north>)"
    assert "Project direction alias" not in text
    assert "Modelled reinforcement direction " + label in text
    assert "Minimum reinforcement - " + label in text
    assert label + " minimum reinforcement" in text
    assert "Modelled direction: " + label in text
    assert "Longitudinal (project alias:" not in text


def test_report_cover_keeps_canonical_direction_when_minimum_check_is_off():
    inp = _inp()
    inp.update({
        "minimum_reinforcement_on": False,
        "detailing_cut_direction": detailing.CUT_TRANSVERSE,
        "modelled_direction_alias": "<b>span axis</b>",
    })

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, {}, figures=False,
    )).split())

    assert "Project direction alias" not in text
    assert (
        "Modelled reinforcement direction Longitudinal "
        "(project alias: <b>span axis</b>)"
    ) in text


def test_results_overview_escapes_supported_markup_in_check_labels(monkeypatch):
    hostile = (
        "Longitudinal (project alias: <b>span</b> "
        '<link href="https://example.test">deck</link> sigma m2 1e-3)'
    )
    monkeypatch.setattr(
        result_presentation,
        "multi_case_summary_rows",
        lambda *_args: [{
            "check": hostile,
            "case": "PL-01",
            "status": "NOT ASSESSED",
            "result": "-",
            "criterion": "Output only",
        }],
    )
    monkeypatch.setattr(
        result_presentation,
        "summary_governing_case_flags",
        lambda _rows: [False],
    )
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, _inp(), {}, figures=False
    )

    builder._results_overview()

    paragraphs = []

    def collect(value):
        if hasattr(value, "getPlainText"):
            paragraphs.append(value.getPlainText())
        if hasattr(value, "_cellvalues"):
            collect(value._cellvalues)
        if hasattr(value, "_content"):
            collect(value._content)
        if isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    collect(builder.flow)
    overview_label = next(
        text for text in paragraphs if "project alias:" in text
    )
    assert "<b>span</b>" in overview_label
    assert '<link href="https://example.test">deck</link>' in overview_label
    assert "sigma m2 1e-3" in overview_label


def test_report_includes_shear_torsion_link_detailing_evidence():
    inp = _inp()
    inp.update({
        "mode": "Plastic",
        "transverse_detailing_on": True,
        "detailing_edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "detailing_member_type": "Beam",
        "detailing_cut_direction": "Transverse cut",
        "transverse_ductility_class": "B",
        "transverse_apply_ductility_reduction": False,
        "shear_vx_transverse_leg_spacing": 0.0,
        "shear_vy_transverse_leg_spacing": 200.0,
    })
    result = {
        "status": "FAIL",
        "edition": inp["detailing_edition"],
        "member_type": inp["detailing_member_type"],
        "diameter_mm": 10.0,
        "spacing_mm": 150.0,
        "fywk_mpa": 500.0,
        "minimum_ratio": {
            "coefficient": 0.063,
            "ductility_factor": 1.0,
            "ductility_reduction_applied": False,
            "clause": "9.2.2(5), Formulae (9.4)-(9.5)",
        },
        "governing": {
            "scope": "Torsion Tube",
            "utilisation": 1.20,
        },
        "checks": [
            {
                "kind": "minimum_ratio",
                "scope": "Shear VY",
                "status": "PASS",
                "provided": 0.00120,
                "limit": 0.00069,
                "utilisation": 0.575,
                "clause": "9.2.2(5)",
            },
            {
                "kind": "torsion_spacing",
                "scope": "Torsion Tube",
                "status": "FAIL",
                "provided": 300.0,
                "limit": 250.0,
                "utilisation": 1.20,
                "clause": "9.2.3(3)",
                "governing_limit": "u_k/8",
            },
        ],
        "limitations": [
            "Stirrup anchorage is assumed. Reduce fywk when full anchorage is "
            "not available."
        ],
    }
    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, {"transverse_reinforcement": result}, figures=False,
    )).split())

    assert "Shear/torsion link detailing" in text
    assert "Beam" in text
    assert "Minimum ratio" in text
    assert "Closed-link spacing" in text
    assert "0.00069" in text
    assert "governing limit: u_k/8" in text
    assert "sqrt" not in text


def test_report_states_when_required_shear_links_are_not_defined():
    inp = _inp()
    inp.update({
        "mode": "Plastic",
        "transverse_detailing_on": True,
        "detailing_edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "detailing_member_type": "Beam",
    })
    result = {
        "status": "FAIL",
        "edition": inp["detailing_edition"],
        "member_type": "Beam",
        "diameter_mm": 10.0,
        "spacing_mm": 150.0,
        "fywk_mpa": 500.0,
        "checks": [{
            "kind": "required_links",
            "scope": "Shear VX",
            "status": "FAIL",
            "provided": 0.0,
            "limit": 1.0,
            "utilisation": math.inf,
            "clause": "6.2.2",
            "reason": "shear resistance without links is insufficient",
        }],
    }
    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, {"transverse_reinforcement": result}, figures=False,
    )).split())
    assert "Required links" in text
    assert "not defined" in text
    assert "required" in text
    assert "Provide shear links because the resistance without links is insufficient" in text


def test_report_explains_one_sided_transverse_spacing_screen():
    inp = _inp()
    inp.update({
        "mode": "Plastic",
        "transverse_detailing_on": True,
        "detailing_edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "detailing_member_type": "Beam",
        "shear_vx_transverse_leg_spacing": 0.0,
        "shear_vy_transverse_leg_spacing": 0.0,
    })
    result = detailing.transverse_reinforcement(
        edition=inp["detailing_edition"],
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=10.0,
        spacing_mm=150.0,
        shear_directions=[{
            "component": "vx",
            "bw_mm": 600.0,
            "d_mm": 305.0,
            "legs": 2.0,
            "transverse_leg_spacing_mm": 0.0,
            "measurement_axis": "y",
        }],
    )
    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, {"transverse_reinforcement": result}, figures=False,
    )).split())
    assert result["status"] == "NOT ASSESSED"
    assert "Transverse leg spacing (along y)" in text
    assert "gross-web upper-bound screen" in text
    assert "actual maximum centre-to-centre leg spacing" in text
    assert "cannot prove FAIL" in text


def test_report_keeps_failed_2005_no_bar_result_in_minimum_area_format():
    inp = _inp()
    inp.update({
        "mode": "Plastic",
        "minimum_reinforcement_on": True,
        "detailing_edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
    })
    minimum = {
        "status": "FAIL",
        "edition": inp["detailing_edition"],
        "clause": "9.2.1.1(1), Formula (9.1N)",
        "checks": [{
            "type": "minimum area", "status": "FAIL", "axis": "xy",
            "face": "resultant tension zone", "as_provided_mm2": 0.0,
            "as_min_mm2": None, "utilisation": None, "bt_mm": None,
            "d_mm": None, "fctm_mpa": 2.9, "fyk_mpa": None,
            "bar_ids": [],
            "reason": "No ordinary reinforcement bar lies in the tension zone.",
        }],
    }

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, {"minimum_reinforcement": minimum}, figures=False,
    )).split())

    assert "Formula (9.1N)" in text
    assert "Outcome:" in text
    assert "No ordinary reinforcement bar lies in the tension zone." in text
    assert "MR,nom" not in text
    assert "Formula (12.1)" not in text


def test_report_traces_multiple_materials_to_element_assignments():
    inp = _inp()
    catalogue, second_id = material_catalog.add_entry(
        material_catalog.default_catalog("mild"), "mild"
    )
    catalogue["items"][0]["name"] = "New reinforcement"
    catalogue["items"][1].update({
        "name": "Existing reinforcement",
        "description": "Verified from archive test certificate",
        "fytk": 235.0,
        "fyck": 235.0,
        "futk": 360.0,
    })
    laws = {
        item["id"]: material_catalog.build_material(item, "mild")
        for item in catalogue["items"]
    }
    inp.update({
        "bars": [(0.0, -0.12, 500.0), (0.0, 0.12, 400.0)],
        "bar_elements": [
            {"id": "R1", "x_mm": 0.0, "y_mm": -120.0,
             "area_mm2": 500.0, "diameter_mm": 25.23,
             "size_mode": "Area", "material_id": "M1",
             "fatigue_detail_id": ""},
            {"id": "R2", "x_mm": 0.0, "y_mm": 120.0,
             "area_mm2": 400.0, "diameter_mm": 22.57,
             "size_mode": "Area", "material_id": second_id,
             "fatigue_detail_id": ""},
        ],
        "mild_material_catalog": catalogue,
        "mild_materials": laws,
        "bar_materials": [laws["M1"], laws[second_id]],
        "steel": laws["M1"],
        "capacity_steel_material_id": second_id,
    })

    out = _out()
    out["material_properties"]["mild"] = [
        {
            "material_id": material_id,
            "design_yield_mpa": laws[material_id].fytk / laws[material_id].gamma_y,
        }
        for material_id in ("M1", second_id)
    ]
    txt = _pdf_text(sector_report.build_report({}, inp, out, figures=False))
    flat = " ".join(txt.split())

    assert "M1 New reinforcement" in flat
    assert "M2 Existing reinforcement" in flat
    assert "Verified from archive test certificate" in flat
    assert "R1 M1" in flat and "R2 M2" in flat


def test_report_describes_built_in_prestress_without_false_zero_strengths():
    entry = material_catalog.default_entry(
        "prestress", preset="Curve 1 (built-in)"
    )
    catalogue = {"version": 1, "next_id": 2, "items": [entry]}
    law = material_catalog.build_material(entry, "prestress")
    inp = _inp()
    inp.update({
        "bars": [],
        "bar_elements": [],
        "tendons": [(0.0, -0.12, 5.0e-4)],
        "tendon_elements": [{
            "id": "T1", "x_mm": 0.0, "y_mm": -120.0,
            "area_mm2": 500.0, "diameter_mm": 25.23,
            "size_mode": "Area", "material_id": "P1",
            "fatigue_detail_id": "",
        }],
        "prestress_material_catalog": catalogue,
        "prestress_materials": {"P1": law},
        "tendon_materials": [law],
        "prestress": law,
        "prestress_preset": entry["preset"],
    })

    out = _out()
    out["material_properties"]["prestress"] = [{
        "material_id": "P1",
        "characteristic_stress_at_rupture_mpa": law.stress(
            law.rupture_strain, design=False
        ),
    }]
    out["prestress_initial"] = {
        "elements": [{
            "tendon_index": 0, "element_id": "T1", "material_id": "P1",
            "initial_strain": law.IS, "modulus_mpa": law.Es,
            "locked_in_stress_mpa": law.Es * law.IS,
            "area_mm2": 500.0, "force_kn": law.Es * law.IS * 500.0 / 1000.0,
            "x_m": 0.0, "y_m": -0.12,
            "mx_knm": law.Es * law.IS * 500.0 / 1000.0 * -0.12,
            "my_knm": 0.0,
        }],
        "internal_resultant_origin": {
            "n_kn": law.Es * law.IS * 500.0 / 1000.0,
            "mx_knm": law.Es * law.IS * 500.0 / 1000.0 * -0.12,
            "my_knm": 0.0,
        },
        "equivalent_action_origin": {
            "n_kn": -law.Es * law.IS * 500.0 / 1000.0,
            "mx_knm": law.Es * law.IS * 500.0 / 1000.0 * -0.12,
            "my_knm": 0.0,
        },
    }
    txt = _pdf_text(sector_report.build_report({}, inp, out, figures=False))
    flat = " ".join(txt.split())

    assert "Built-in fixed curve 1" in flat
    assert "Characteristic stress at rupture strain" in flat
    assert "1645.000 MPa" in flat
    assert "Proof strength" not in flat
    assert "Ultimate strength" not in flat
    assert "normative source not assigned" in flat


@pytest.mark.parametrize(
    "preset",
    [
        "Custom / imported",
        "Curve 1 (bilinear hardening)",
        "Curve 2 (elastic-perfectly-plastic)",
    ],
)
def test_report_does_not_assign_eurocode_source_to_custom_or_generic_steel(preset):
    entry = material_catalog.default_entry("mild", preset=preset)
    entry["preset"] = preset
    catalogue = {"version": 1, "next_id": 2, "items": [entry]}
    law = material_catalog.build_material(entry, "mild")
    inp = _inp()
    inp.update({
        "bar_elements": [{
            "id": "R1", "x_mm": 0.0, "y_mm": -120.0,
            "area_mm2": 500.0, "diameter_mm": 25.23,
            "size_mode": "Area", "material_id": "M1",
            "fatigue_detail_id": "",
        }],
        "mild_material_catalog": catalogue,
        "mild_materials": {"M1": law},
        "bar_materials": [law],
        "steel": law,
    })

    out = _out()
    out["material_properties"]["mild"] = [{
        "material_id": "M1",
        "design_yield_mpa": law.fytk / law.gamma_y,
    }]
    flat = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False,
    )).split())

    assert "no normative curve source assigned" in flat
    assert "3.2.7" not in flat
    assert "uncited" in flat
    if preset == "Curve 2 (elastic-perfectly-plastic)":
        assert "User-defined / project-defined Curve 2 preset" in flat
        assert "General Curve 3 law" in flat


def test_report_footer_identifies_the_organisational_licensee():
    txt = _pdf_text(sector_report.build_report(
        {"source_revision": "abcdef1234567890"},
        _inp(),
        _out(),
        version="0.91",
        figures=False,
    ))
    flat = " ".join(txt.split())
    assert "Sector 0.91 - Sweco Danmark A/S" in flat
    assert "abcdef123456" not in flat


def test_report_front_matter_identifies_action_sets_and_result_statuses():
    txt = _pdf_text(sector_report.build_report(
        {"source_revision": "abcdef1234567890"},
        _inp(),
        _out(),
        figures=False,
    ))
    assert "Results overview" in txt
    assert "Results overview - PASS" not in txt
    assert "PL-TEST" in txt and "EL-TEST" in txt
    assert "Combination register C1" in txt
    assert "Combination register C2" in txt
    assert "abcdef123456" not in txt
    assert "Concrete stress" in txt and "Crack width" in txt


def test_multi_case_report_includes_later_governing_case_and_all_details():
    inp = _inp()
    plastic_rows = [
        {
            "name": "PL-01", "description": "Routine combination",
            "n_ed_kn": 0.0, "mx_ed_knm": 80.0, "my_ed_knm": 0.0,
            "vx_ed_kn": 0.0, "vy_ed_kn": 0.0,
            "vx_face": "auto", "vy_face": "auto", "t_ed_knm": 0.0,
        },
        {
            "name": "PL-02", "description": "Governing combination",
            "n_ed_kn": 0.0, "mx_ed_knm": 125.0, "my_ed_knm": 0.0,
            "vx_ed_kn": 0.0, "vy_ed_kn": 0.0,
            "vx_face": "auto", "vy_face": "auto", "t_ed_knm": 0.0,
        },
    ]
    elastic_rows = [
        {
            "name": "EL-01", "description": "Characteristic stresses",
            "n_long_ed_kn": 0.0, "mx_long_ed_knm": 80.0,
            "my_long_ed_knm": 0.0, "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 20.0, "my_short_ed_knm": 0.0,
            "calculate_crack_width": True,
        },
        {
            "name": "EL-02", "description": "Frequent response",
            "n_long_ed_kn": 0.0, "mx_long_ed_knm": 45.0,
            "my_long_ed_knm": 0.0, "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 10.0, "my_short_ed_knm": 0.0,
            "calculate_crack_width": False,
        },
    ]
    inp["plastic_cases"] = plastic_rows
    inp["elastic_cases"] = elastic_rows

    first = _out()
    second_plastic = copy.deepcopy(first["plastic"])
    second_plastic["util"] = 1.25
    second_plastic["applied"] = (125.0, 0.0)
    second_elastic = copy.deepcopy(first["elastic"])
    second_elastic["show_cw"] = False
    second_elastic["max_steel"] = 456.0
    second_elastic["max_steel_element"] = "bar 1"
    second_elastic["elements"][0]["total_mpa"] = 456.0

    out = {
        # Deliberately retain only the first case in the compatibility projection.
        # The report must consume the canonical entries below instead.
        "plastic": first["plastic"],
        "elastic": first["elastic"],
        "plastic_cases": [
            {"name": row["name"], "actions": row, "evaluated": True,
             "results": {"plastic": result}}
            for row, result in zip(
                plastic_rows, (first["plastic"], second_plastic)
            )
        ],
        "elastic_cases": [
            {"name": row["name"], "actions": row, "evaluated": True,
             "results": {"elastic": result}}
            for row, result in zip(
                elastic_rows, (first["elastic"], second_elastic)
            )
        ],
    }

    pdf = sector_report.build_report({}, inp, out, figures=False)
    txt = _pdf_body_text(pdf)
    outline_titles = _pdf_outline_titles(pdf)
    flat = " ".join(txt.split())
    assert "Results overview" in flat
    assert "Results overview - FAIL" not in flat
    assert all(case in flat for case in ("PL-01", "PL-02", "EL-01", "EL-02"))
    assert "Governing combination" in flat and "Frequent response" in flat
    assert sum(
        "Plastic section capacity" in title
        for title in outline_titles
    ) == 1
    assert sum(
        "Elastic section response and stresses" in title
        for title in outline_titles
    ) == 1
    assert "Plastic section capacity - PL-01" not in flat
    assert "Elastic section response and stresses - EL-01" not in flat
    assert "Cracking threshold and governing crack width - EL-01" in flat
    assert "Plastic section capacity - PL-02" in flat
    assert "Elastic section response and stresses - EL-02" in flat
    assert "Cracking threshold - EL-02" not in flat
    assert "Crack width was not requested for this run." not in flat
    assert "EQ-" not in flat
    assert "Each comparison has its own status" in flat
    assert "125.0 %" in flat
    assert "456.000 MPa" in flat
    assert flat.count("Selected sweep point") == 1
    assert flat.count("The elastic analysis uses an") == 1
    assert flat.count("reference-stress plane") >= 1


def test_report_publishes_only_governing_fine_and_coarse_crack_examples():
    inp = _inp()
    rows = [
        {
            "name": "EL-01", "description": "Coarse governing",
            "n_long_ed_kn": 0.0, "mx_long_ed_knm": 80.0,
            "my_long_ed_knm": 0.0, "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 20.0, "my_short_ed_knm": 0.0,
            "calculate_crack_width": True,
        },
        {
            "name": "EL-02", "description": "Fine governing",
            "n_long_ed_kn": 0.0, "mx_long_ed_knm": 100.0,
            "my_long_ed_knm": 0.0, "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 30.0, "my_short_ed_knm": 0.0,
            "calculate_crack_width": True,
        },
        {
            "name": "EL-03", "description": "Non-governing",
            "n_long_ed_kn": 0.0, "mx_long_ed_knm": 60.0,
            "my_long_ed_knm": 0.0, "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 10.0, "my_short_ed_knm": 0.0,
            "calculate_crack_width": True,
        },
    ]
    inp["elastic_cases"] = rows
    first = copy.deepcopy(_out()["elastic"])
    first.update(
        crack=dict(_crack(), wk=0.20),
        crack_short=dict(_crack(), wk=0.22),
        crack_coarse=_coarse_crack(wk=0.31),
        crack_short_coarse=_coarse_crack(wk=0.29),
        crack_code="DS/EN 1992-1-1 + DK NA",
    )
    second = copy.deepcopy(_out()["elastic"])
    second.update(
        crack=dict(_crack(), wk=0.34),
        crack_short=dict(_crack(), wk=0.33),
        crack_coarse=_coarse_crack(wk=0.24),
        crack_short_coarse=_coarse_crack(wk=0.25),
        crack_code="DS/EN 1992-1-1 + DK NA",
    )
    third = copy.deepcopy(_out()["elastic"])
    third.update(
        crack=dict(_crack(), wk=0.10),
        crack_short=dict(_crack(), wk=0.11),
        crack_coarse=_coarse_crack(wk=0.12),
        crack_short_coarse=_coarse_crack(wk=0.09),
        crack_code="DS/EN 1992-1-1 + DK NA",
    )
    out = _out()
    out["elastic_cases"] = [
        {"name": row["name"], "actions": row, "evaluated": True,
         "results": {"elastic": result}}
            for row, result in zip(rows, (first, second, third))
    ]
    flat = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False, qa_appendix=False,
    )).split())
    assert flat.count("Crack width worked - governing case") == 2
    assert "EQ-CRACKING.THRESHOLD" not in flat
    assert "governing case (long-term (fine))" in flat
    assert "governing case (long-term (coarse))" in flat
    assert "Candidate summary for governing crack example" not in flat
    assert "Case (LT/ST)" not in flat
    assert "EL-03" in flat
    assert "Governing crack width - EL-03" not in flat
    assert "Cracking threshold and governing crack width - EL-03" not in flat


def test_worked_selectors_ignore_invalid_nonfinite_case_results():
    inp = _inp()
    plastic_rows = [
        {
            "name": name,
            "description": description,
            "n_ed_kn": 0.0,
            "mx_ed_knm": 20.0,
            "my_ed_knm": 0.0,
            "vx_ed_kn": 0.0,
            "vy_ed_kn": 0.0,
            "vx_face": "auto",
            "vy_face": "auto",
            "t_ed_knm": 0.0,
        }
        for name, description in (
            ("PL-INVALID", "Invalid plastic"),
            ("PL-VALID", "Valid plastic"),
            ("PL-INFINITE", "Valid infinite failure"),
        )
    ]
    elastic_rows = [
        {
            "name": name,
            "description": description,
            "n_long_ed_kn": 0.0,
            "mx_long_ed_knm": 20.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 5.0,
            "my_short_ed_knm": 0.0,
            "calculate_crack_width": True,
        }
        for name, description in (
            ("EL-INVALID", "Invalid elastic"),
            ("EL-VALID", "Valid elastic"),
        )
    ]
    inp["plastic_cases"] = plastic_rows
    inp["elastic_cases"] = elastic_rows

    invalid_plastic = copy.deepcopy(_out()["plastic"])
    invalid_plastic.update(converged=False, util=math.inf, max_mx=math.inf)
    valid_plastic = copy.deepcopy(_out()["plastic"])
    valid_plastic.update(converged=True, util=0.7)
    infinite_plastic = copy.deepcopy(_out()["plastic"])
    infinite_plastic.update(converged=True, util=math.inf)

    invalid_elastic = copy.deepcopy(_out()["elastic"])
    invalid_elastic.update(
        converged=False,
        max_conc=math.inf,
        max_steel=math.inf,
        crack=dict(_crack(), wk=math.inf),
        crack_short=None,
    )
    valid_elastic = copy.deepcopy(_out()["elastic"])
    valid_elastic.update(
        converged=True,
        max_conc=18.0,
        max_steel=220.0,
        crack=dict(_crack(), wk=0.24),
        crack_short=None,
    )
    invalid_case = {
        "minimum_reinforcement": {
            "status": "INVALID",
            "checks": [{"status": "INVALID", "utilisation": math.inf}],
        },
        "transverse_reinforcement": {
            "status": "INVALID",
            "checks": [{"status": "INVALID", "utilisation": math.inf}],
        },
    }
    finite_checks = {
        "minimum_reinforcement": {
            "status": "PASS",
            "checks": [{"status": "PASS", "utilisation": 0.6}],
        },
        "transverse_reinforcement": {
            "status": "PASS",
            "checks": [{"status": "PASS", "utilisation": 0.8}],
        },
    }
    infinite_checks = {
        "minimum_reinforcement": {
            "status": "FAIL",
            "checks": [{"status": "FAIL", "utilisation": math.inf}],
            "governing_utilisation": math.inf,
        },
        "transverse_reinforcement": {
            "status": "FAIL",
            "checks": [{"status": "FAIL", "utilisation": math.inf}],
            "governing_utilisation": math.inf,
        },
    }
    out = {
        "plastic_cases": [
            {
                "actions": plastic_rows[0],
                "evaluated": True,
                "results": {"plastic": invalid_plastic, **invalid_case},
            },
            {
                "actions": plastic_rows[1],
                "evaluated": True,
                "results": {"plastic": valid_plastic, **finite_checks},
            },
            {
                "actions": plastic_rows[2],
                "evaluated": True,
                "results": {"plastic": infinite_plastic, **infinite_checks},
            },
        ],
        "elastic_cases": [
            {
                "actions": elastic_rows[0],
                "evaluated": True,
                "results": {"elastic": invalid_elastic},
            },
            {
                "actions": elastic_rows[1],
                "evaluated": True,
                "results": {"elastic": valid_elastic},
            },
        ],
    }

    selected = result_presentation.worked_example_selection(inp, out)

    assert selected["families"]["plastic"]["case_id"] == "PL-INFINITE"
    assert selected["families"]["elastic"]["case_id"] == "EL-VALID"
    assert selected["families"]["minimum_reinforcement"]["case_id"] == (
        "PL-INFINITE"
    )
    assert selected["families"]["transverse_reinforcement"]["case_id"] == (
        "PL-INFINITE"
    )
    assert {item["case_id"] for item in selected["crack_examples"]} == {
        "EL-VALID"
    }


def test_report_builder_consumes_selection_and_does_not_choose_candidates():
    source = inspect.getsource(sector_report.ReportBuilder)

    assert "def _select_critical" not in source
    assert "def _critical_transverse_direction" not in source
    assert "id(case_out)" not in source
    assert "_transverse_metric" not in source
    assert 'get("worked_example_selection")' in source


def test_report_fails_closed_when_worked_example_selection_is_absent():
    text = " ".join(_pdf_text(_build_report_from_completed_payload(
        {}, _inp(), _out(), figures=False, qa_appendix=False,
    )).split())

    assert "Worked plastic calculation" not in text
    assert "Crack width worked - governing case" not in text


@pytest.mark.parametrize(
    "selection",
    (
        {"schema": 99, "families": {"plastic": {"case_id": "__single__"}}},
        {"schema": 1, "families": ["plastic"], "crack_examples": "crack"},
        {
            "schema": 1,
            "families": {},
            "crack_examples": ["crack"],
            "cracking_threshold": ["elastic"],
            "torsion_subchecks": ["torsion"],
        },
        {
            "schema": 1,
            "families": {
                "plastic": ["PL-TEST"],
                "shear": {"case_id": "__single__", "component": []},
            },
            "crack_examples": [{
                "case_id": "__single__", "branch": [], "label": "invalid",
            }],
            "cracking_threshold": None,
            "torsion_subchecks": {"interaction": ["__single__"]},
        },
    ),
)
def test_report_fails_closed_on_corrupt_worked_example_selection(selection):
    out = _out()
    out["worked_example_selection"] = selection

    text = " ".join(_pdf_text(_build_report_from_completed_payload(
        {}, _inp(), out, figures=False, qa_appendix=False,
    )).split())

    assert "Worked plastic calculation" not in text
    assert "Crack width worked - governing case" not in text


def test_crack_worked_example_fails_closed_on_partial_selected_branch():
    inp = _inp()
    out = _out()
    out["worked_example_selection"] = (
        result_presentation.worked_example_selection(inp, out)
    )
    del out["elastic"]["crack"]["governing_candidate"][
        "spacing_operands"
    ]["k1"]

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False, qa_appendix=False,
    )).split())

    assert "Worked calculation unavailable" in text
    assert "spacing.k1" in text
    assert "EQ-CRACK.2005.SPACING" not in text


def test_crack_worked_example_rejects_an_unknown_retained_formula_branch():
    inp = _inp()
    out = _out()
    out["worked_example_selection"] = (
        result_presentation.worked_example_selection(inp, out)
    )
    out["elastic"]["crack"]["governing_candidate"][
        "spacing_operands"
    ]["selected_candidate"] = "unknown-formula"

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False, qa_appendix=False,
    )).split())

    assert "Worked calculation unavailable" in text
    assert "spacing.selected_candidate-supported" in text
    assert "EQ-CRACK.2005.SPACING" not in text


def _tension_zone_cap_crack_2023():
    crack = _crack_2023()
    candidate = crack["governing_candidate"]
    spacing = candidate["spacing_operands"]
    cap_spacing = spacing["formula_spacing"] * 0.5
    spacing.update({
        "cap_tension_depth": cap_spacing * crack["kw"] / 1.3 / 1000.0,
        "cap_spacing": cap_spacing,
        "selected_candidate": "tension-zone-cap",
        "selected_spacing": cap_spacing,
    })
    crack_width = crack["kw"] * crack["k1_r"] * cap_spacing * crack["esm_ecm"]
    crack.update(sr_max=cap_spacing, wk=crack_width)
    candidate.update(sr_max=cap_spacing, wk=crack_width)
    crack["candidates"] = [copy.deepcopy(candidate)]
    return crack


def test_crack_2023_tension_zone_cap_is_a_supported_worked_branch():
    inp = _inp()
    out = _out()
    crack = _tension_zone_cap_crack_2023()
    out["elastic"].update(
        crack=crack,
        crack_short=None,
        crack_code="EN 1992-1-1:2023",
    )

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False, qa_appendix=False,
    )).split())

    assert "selected: tension-zone-cap" in text
    assert "EQ-CRACK.2023.SPACING" not in text
    assert "Equation (" in text
    assert "Worked calculation unavailable" not in text


def test_crack_2023_tension_zone_cap_fails_closed_without_cap_depth():
    inp = _inp()
    out = _out()
    crack = _tension_zone_cap_crack_2023()
    del crack["governing_candidate"]["spacing_operands"]["cap_tension_depth"]
    out["elastic"].update(
        crack=crack,
        crack_short=None,
        crack_code="EN 1992-1-1:2023",
    )

    text = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False, qa_appendix=False,
    )).split())

    assert "Worked calculation unavailable" in text
    assert "spacing.cap_tension_depth" in text
    assert "EQ-CRACK.2023.SPACING" not in text


@pytest.mark.parametrize(
    ("selection_key", "payload_key", "renderer", "formula"),
    (
        (
            "interaction", "interaction", "_torsion_interaction_example",
            "Formula 6.29",
        ),
        (
            "minimum_reinforcement", "min_reinf",
            "_torsion_minimum_reinforcement_example", "Formula 6.31",
        ),
    ),
)
def test_infinite_torsion_subcheck_with_partial_operands_is_unavailable(
    selection_key, payload_key, renderer, formula,
):
    payload = (
        {"valid": True, "value": math.inf}
        if payload_key == "interaction"
        else {"applicable": True, "value": math.inf}
    )
    out = {
        "torsion": {payload_key: payload},
        "worked_example_selection": {
            "schema": 1,
            "families": {},
            "crack_examples": [],
            "cracking_threshold": None,
            "torsion_subchecks": {
                selection_key: {"case_id": "__single__", "component": None},
            },
        },
    }
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, _inp(), out, figures=False,
    )

    getattr(builder, renderer)()
    text = " ".join(
        item.getPlainText()
        for item in builder.flow
        if hasattr(item, "getPlainText")
    )

    assert "Worked calculation unavailable" in text
    assert formula in text


def test_report_publishes_one_globally_critical_cracking_threshold():
    inp = _inp()
    inp["mode"] = "Elastic"
    rows = [
        {
            "name": name,
            "description": description,
            "n_long_ed_kn": 0.0,
            "mx_long_ed_knm": moment,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 0.0,
            "my_short_ed_knm": 0.0,
            "calculate_crack_width": False,
        }
        for name, description, moment in (
            ("EL-A", "Uncracked", 30.0),
            ("EL-B", "Critical threshold", 80.0),
            ("EL-C", "Intermediate", 50.0),
        )
    ]
    inp["elastic_cases"] = rows
    results = []
    for lambda_cr, cracked in ((1.40, False), (0.80, True), (1.10, False)):
        elastic = copy.deepcopy(_out()["elastic"])
        elastic.update(
            converged=True,
            show_cw=False,
            lambda_cr=lambda_cr,
            cracked=cracked,
            crack=None,
            crack_short=None,
            crack_coarse=None,
            crack_short_coarse=None,
        )
        results.append(elastic)
    out = {
        "elastic_cases": [
            {
                "actions": row,
                "evaluated": True,
                "results": {"elastic": elastic},
            }
            for row, elastic in zip(rows, results)
        ]
    }

    flat = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False, qa_appendix=False,
    )).split())

    assert all(name in flat for name in ("EL-A", "EL-B", "EL-C"))
    assert "Cracking threshold - EL-B" in flat
    assert "Cracking threshold - EL-A" not in flat
    assert "Cracking threshold - EL-C" not in flat
    assert "EQ-CRACKING.THRESHOLD" not in flat
    assert (
        "0.8 -> section is cracked "
        "(strictly below 1: cracked; 1 or above: uncracked)"
    ) in flat


def test_report_publishes_ordinary_cracking_threshold_relation():
    out = _out()
    out.pop("plastic")
    out["elastic"].update(
        converged=True,
        show_cw=False,
        lambda_cr=(out["elastic"]["fctm"] / out["elastic"]["sigma_ct"]),
        cracked=True,
        crack=None,
        crack_short=None,
        crack_coarse=None,
        crack_short_coarse=None,
    )

    ordinary_inp = _inp()
    ordinary_inp["mode"] = "Elastic"
    ordinary = " ".join(_pdf_text(sector_report.build_report(
        {}, ordinary_inp, out, figures=False, qa_appendix=False,
    )).split())
    compact_ordinary = ordinary.replace(" ", "")
    assert (
        chr(0x03BB) + "cr=fct,eff/" + chr(0x03C3) + "ct,I"
    ) in compact_ordinary
    assert "Locked-in prestress remains fixed" not in ordinary
    assert "lambda_cr 0.403; cracked" in ordinary


def test_report_escapes_user_entered_action_provenance():
    inp = _inp()
    inp["plastic_case"] = {
        "id": "PL&A<1>",
        "type": "Other / project-specific",
        "source": "Model A & register <C1>",
    }
    txt = _pdf_text(sector_report.build_report({}, inp, _out(), figures=False))
    assert "PL&A<1>" in txt
    assert "Model A & register <C1>" in txt


def test_report_mirrors_the_views():
    txt = _pdf_text(sector_report.build_report({}, _inp(), _out(), figures=False))
    flat = " ".join(txt.split())
    assert "Fcomp" in txt and "NA x" in txt        # full plastic table columns
    assert "PASS - Plastic bending" in txt
    assert " pp" not in flat
    assert "does not exceed" not in flat
    assert "Long-term crack-width output" in flat
    assert "Short-term crack-width output" in flat
    assert "Calculation state: CALCULATED" in flat
    assert "Governing concrete corner response" in txt
    assert "Governing reinforcement and tendon response" in txt
    assert "Cracked" in txt                        # cracked transformed-props column
    assert "both load cases" in txt                # full crack-width table
    assert "Sweep start" in txt                    # explicit Vstart/Vend/Vinc
    assert "Utilisation check" in txt              # analysis settings documented
    assert "Max / Min" in txt                      # both extremes for Mx and My


def test_legacy_qa_appendix_flag_maps_to_standard_and_audit_profiles():
    default_text = _pdf_text(sector_report.build_report(
        {}, _inp(), _out(), figures=False, qa_appendix=False
    ))
    qa_text = _pdf_text(sector_report.build_report(
        {}, _inp(), _out(), figures=False, qa_appendix=True
    ))

    assert "Report profile Standard" in " ".join(default_text.split())
    assert "QA appendix - references and notes" not in default_text
    assert "Report profile Audit" in " ".join(qa_text.split())
    assert "Values and statuses match the other report profiles" in " ".join(
        qa_text.split()
    )
    assert "QA appendix - references and notes" in qa_text


def test_report_includes_sls_outputs_strain_and_candidate_evidence():
    txt = _pdf_text(sector_report.build_report({}, _inp(), _out(), figures=False))
    assert "Elastic stress outputs" in txt
    assert "No stress-limit criterion is applied" in txt
    assert "DB-SLS-01 section 4" not in txt
    assert "60% fck" not in txt and "80% fyk" not in txt
    assert "Ixy" in txt
    assert "Reinforcement and tendon response" in txt
    assert "Concrete corner stress and strain" in txt
    assert "Candidate summary for governing crack example" in txt
    assert "Crack-width element diameter" in txt
    assert "Element diameter" in txt
    assert "Bar diameter" not in txt
    assert "bar 1" in txt
    assert "0.213 mm" in txt
    assert "0.300 mm" not in txt
    assert chr(0x394) + chr(0x3B5) in txt
    assert "delta eps" not in txt


def test_report_does_not_round_small_nonzero_product_inertia_to_zero():
    out = _out()
    out["elastic"]["props_un"]["Ixy"] = 1.234567e-8
    out["elastic"]["props_cr"]["Ixy"] = -2.345678e-9
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    times = chr(0x00D7)
    assert f"1.23457 {times} 10-8" in txt
    assert f"-2.34568 {times} 10-9" in txt


def test_crack_candidate_table_stays_inside_a4_content_width():
    assert sum(sector_report._CRACK_CANDIDATE_COL_WIDTHS) <= \
        sector_report._A4_CONTENT_WIDTH


def test_report_marks_nonconverged_elastic_results_invalid():
    out = _out()
    out["elastic"]["converged"] = False
    for item in out["elastic"]["stress_outputs"].values():
        item["calculation_state"] = "INVALID"
        item["value"] = None
    for assessment in out["elastic"]["crack_output"].values():
        assessment["calculation_state"] = "INVALID"
        assessment["value"] = None
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "INVALID - Elastic result" in txt
    assert "diagnostic only" in txt
    assert "no verified cracking classification" in txt


def test_report_marks_no_crack_width_as_output_not_applicable():
    out = _out()
    elastic = out["elastic"]
    elastic.update(
        cracked=False,
        crack=None,
        crack_short=None,
        crack_output={
            "long_term": {
                "duration": "long_term",
                "value": None,
                "calculation_state": "NOT ASSESSED",
                "case": None,
                "governing": None,
                "unit": "mm",
                "reason": "Section uncracked; no width is available.",
            },
            "short_term": {
                "duration": "short_term",
                "value": None,
                "calculation_state": "NOT ASSESSED",
                "case": None,
                "governing": None,
                "unit": "mm",
                "reason": "Section uncracked; no width is available.",
            },
        },
    )
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "NOT ASSESSED" in txt
    assert "Section uncracked; no width is available." in txt
    assert "No crack width: section uncracked or no reinforcement" not in txt
    assert "No user-specified crack-width criterion" in txt
    assert "DB-SLS-01 section 4" not in txt


def test_threshold_case_with_unrequested_width_keeps_only_retained_reason():
    inp = _inp()
    inp["sls_cw"] = False
    out = _out()
    elastic = out["elastic"]
    elastic.update(
        show_cw=False,
        crack=None,
        crack_short=None,
        crack_coarse=None,
        crack_short_coarse=None,
        crack_output={
            duration: {
                "duration": duration,
                "value": None,
                "case": None,
                "governing": None,
                "unit": "mm",
                "calculation_state": "NOT REQUESTED",
                "criterion_mm": None,
                "ratio": None,
                "criterion_source": None,
                "reason": "Crack width was not requested for this run.",
                "comparison_equation": None,
            }
            for duration in ("long_term", "short_term")
        },
    )

    text = _pdf_text(sector_report.build_report({}, inp, out, figures=False))

    assert "Cracking threshold - EL-TEST" in text
    assert "NOT REQUESTED" in text
    assert "Crack width was not requested for this run." in text
    assert "No crack width: section uncracked or no reinforcement" not in text


def test_stale_crack_selection_with_no_values_never_infers_physical_reason():
    inp = _inp()
    out = _out()
    out["worked_example_selection"] = (
        result_presentation.worked_example_selection(inp, out)
    )
    retained_reason = (
        "The selected action state is outside the validated ordinary crack-width "
        "scope."
    )
    out["elastic"].update(
        crack=None,
        crack_short=None,
        crack_coarse=None,
        crack_short_coarse=None,
        crack_output={
            duration: {
                "duration": duration,
                "value": None,
                "case": None,
                "governing": None,
                "unit": "mm",
                "calculation_state": "NOT ASSESSED",
                "criterion_mm": None,
                "ratio": None,
                "criterion_source": None,
                "reason": retained_reason,
                "comparison_equation": None,
            }
            for duration in ("long_term", "short_term")
        },
    )

    text = _pdf_text(sector_report.build_report({}, inp, out, figures=False))

    assert retained_reason in text
    assert "No crack width: section uncracked or no reinforcement" not in text
    assert "does not infer a physical reason" not in text


def test_report_publishes_one_retained_critical_user_crack_comparison():
    out = _out()
    out["elastic"]["crack_output"] = {
        "long_term": {
            "duration": "long_term",
            "value": 0.213,
            "case": "Long-term",
            "governing": "bar 1",
            "unit": "mm",
            "calculation_state": "WITHIN USER-SPECIFIED LIMIT",
            "criterion_mm": 0.300,
            "ratio": 0.710,
            "criterion_source": "User input - Analysis settings - long-term",
            "reason": (
                "The calculated crack width is within the user-specified limit."
            ),
            "comparison_equation": "w_k / w_k,criterion",
        },
    }

    flat = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), out, figures=False, qa_appendix=False,
    )).split())

    assert flat.count(
        "User-specified crack-width comparison - critical long-term case"
    ) == 1
    assert "EQ-CRACK.USER-LIMIT.COMPARISON" not in flat
    assert "0.213 mm / 0.3 mm" in flat
    assert "u w = 0.71" in flat or "uw = 0.71" in flat
    assert "WITHIN USER-SPECIFIED LIMIT" in flat
    assert "No user-specified crack-width criterion" not in flat


def test_report_applies_one_duration_criterion_without_noncritical_chapter():
    inp = _inp()
    inp["sls_long_term_permitted_crack_width_mm"] = 0.10
    rows = [
        {
            "name": "EL-GLOBAL-WIDTH",
            "description": "Global physical crack width",
            "n_long_ed_kn": 0.0,
            "mx_long_ed_knm": 80.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 0.0,
            "my_short_ed_knm": 0.0,
            "calculate_crack_width": True,
        },
        {
            "name": "EL-NONCRITICAL-LIMIT",
            "description": "Smaller assessed crack width",
            "n_long_ed_kn": 0.0,
            "mx_long_ed_knm": 40.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 0.0,
            "my_short_ed_knm": 0.0,
            "calculate_crack_width": True,
        },
    ]
    inp["elastic_cases"] = rows
    global_result = copy.deepcopy(_out()["elastic"])
    global_result.update(
        crack=dict(_crack(), wk=0.40),
        crack_short=None,
        crack_coarse=None,
        crack_short_coarse=None,
        crack_output={
            "long_term": {
                "duration": "long_term",
                "value": 0.40,
                "case": "Long-term",
                "governing": "bar 1",
                "unit": "mm",
                "calculation_state": "EXCEEDS USER-SPECIFIED LIMIT",
                "criterion_mm": 0.10,
                "ratio": 4.0,
                "criterion_source": "User input - Analysis settings - long-term",
                "reason": (
                    "The calculated crack width exceeds the user-specified limit."
                ),
                "comparison_equation": "w_k / w_k,criterion",
            },
        },
    )
    assessed_result = copy.deepcopy(_out()["elastic"])
    assessed_result.update(
        crack=dict(_crack(), wk=0.20),
        crack_short=None,
        crack_coarse=None,
        crack_short_coarse=None,
        crack_output={
            "long_term": {
                "duration": "long_term",
                "value": 0.20,
                "case": "Long-term",
                "governing": "bar 1",
                "unit": "mm",
                "calculation_state": "EXCEEDS USER-SPECIFIED LIMIT",
                "criterion_mm": 0.10,
                "ratio": 2.0,
                "criterion_source": "User input - Analysis settings - long-term",
                "reason": (
                    "The calculated crack width exceeds the user-specified limit."
                ),
                "comparison_equation": "w_k / w_k,criterion",
            },
        },
    )
    out = _out()
    out["elastic_cases"] = [
        {
            "name": row["name"],
            "actions": row,
            "evaluated": True,
            "results": {"elastic": result},
        }
        for row, result in zip(rows, (global_result, assessed_result))
    ]

    summaries = result_presentation.multi_case_summary_rows(inp, out)
    assert any(
        row["case"] == "EL-NONCRITICAL-LIMIT"
        and row["check"] == "Crack width - Long-term"
        and row["status"] == "EXCEEDS USER-SPECIFIED LIMIT"
        for row in summaries
    )

    flat = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False, qa_appendix=False,
    )).split())

    assert flat.count("Crack width worked - governing case") == 1
    assert "Governing crack width - EL-NONCRITICAL-LIMIT" not in flat
    assert "Governing crack-width comparison - EL-NONCRITICAL-LIMIT" not in flat
    assert flat.count(
        "User-specified crack-width comparison - critical long-term case"
    ) == 1
    assert "EQ-CRACK.USER-LIMIT.COMPARISON" not in flat


def _heightened_crack_result():
    common = {
        "basis_key": DesignBasisKey.FIRST_GEN_DK_NA_2024.value,
        "reinforcement_surface": "smooth",
        "bar_diameter_mm": 16.0,
        "diameter_source": "largest contributing mild bar",
        "effective_tensile_strength_mpa": 2.9,
        "reinforcement_modulus_mpa": 200_000.0,
        "permitted_crack_width_mm": 0.20,
        "provided_reinforcement_area_mm2": 900.0,
        "source": (
            "DS/EN 1992-1-1 DK NA:2024, supplementary provision to "
            "7.3.2(1)P, Formula 7.100 NA"
        ),
        "disclosure": (
            "The user supplies the permitted crack width and decides applicability."
        ),
        "formula_identity": "Formula 7.100 NA",
        "reference_case_id": "EL-REF",
        "ordinary_crack_branch": "Short-term (fine)",
    }
    fine = {
        **common,
        "crack_system": "fine",
        "effective_tension_area_mm2": 60_000.0,
        "crack_system_factor": 1.0,
        "reinforcement_surface_multiplier": math.sqrt(2.0),
        "base_reinforcement_ratio": 0.0170293864,
        "required_reinforcement_ratio": 0.0240831892,
        "required_reinforcement_area_mm2": 1444.991352,
        "comparison_ratio": 1.605546,
        "status": "PROVIDED AREA BELOW CALCULATED REQUIREMENT",
    }
    coarse = {
        **common,
        "crack_system": "coarse",
        "effective_tension_area_mm2": 90_000.0,
        "crack_system_factor": 2.0,
        "reinforcement_surface_multiplier": math.sqrt(2.0),
        "base_reinforcement_ratio": 0.0120415946,
        "required_reinforcement_ratio": 0.0170293864,
        "required_reinforcement_area_mm2": 1532.644776,
        "comparison_ratio": 1.70293864,
        "status": "PROVIDED AREA BELOW CALCULATED REQUIREMENT",
    }
    return {
        **coarse,
        "fine": fine,
        "coarse": coarse,
        "governing_crack_system": "coarse",
        "governing_required_reinforcement_area_mm2": 1532.644776,
        "governing_comparison_ratio": 1.70293864,
        "governing_status": "PROVIDED AREA BELOW CALCULATED REQUIREMENT",
        "diameter_governing_element_ids": ["R1"],
        "modulus_governing_material_ids": ["M1"],
        "contributions": [{
            "element_id": "R1",
            "material_id": "M1",
            "material_name": "B500B",
            "area_mm2": 900.0,
            "diameter_mm": 16.0,
            "diameter_source": "provided",
            "reinforcement_modulus_mpa": 200_000.0,
        }],
    }


def test_report_publishes_dual_heightened_crack_chain_from_retained_values():
    out = _out()
    out["heightened_crack_control"] = _heightened_crack_result()

    flat = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), out, figures=False, qa_appendix=False,
    )).split())

    assert "DK heightened crack-control minimum" in flat
    assert "EQ-CRACK.HEIGHTENED.BASE-RATIO" not in flat
    assert "EQ-CRACK.HEIGHTENED.REQUIRED-RATIO" not in flat
    assert "EQ-CRACK.HEIGHTENED.REQUIRED-AREA" not in flat
    assert "EQ-CRACK.HEIGHTENED.AREA-COMPARISON" not in flat
    assert "1.414" in flat
    assert "1445" in flat
    assert "1532.6" in flat
    assert "EL-REF" in flat
    assert "R1" in flat
    assert "coarse" in flat
    assert "PROVIDED AREA BELOW CALCULATED REQUIREMENT" in flat
    assert "watertightness" in flat


def test_report_heightened_crack_partial_payload_fails_closed():
    out = _out()
    heightened = _heightened_crack_result()
    del heightened["fine"]["base_reinforcement_ratio"]
    out["heightened_crack_control"] = heightened

    flat = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), out, figures=False, qa_appendix=False,
    )).split())

    assert "Worked calculation unavailable" in flat
    assert "fine.base_reinforcement_ratio" in flat
    assert "EQ-CRACK.HEIGHTENED.BASE-RATIO" not in flat


@pytest.mark.parametrize(
    ("mutation", "missing_text"),
    (
        (
            lambda payload: payload["coarse"].pop(
                "reinforcement_surface_multiplier"
            ),
            "coarse.reinforcement_surface_multiplier",
        ),
        (
            lambda payload: payload.pop("modulus_governing_material_ids"),
            "modulus_governing_material_ids",
        ),
        (
            lambda payload: payload["contributions"][0].pop("material_id"),
            "contributions[1].material_id",
        ),
    ),
)
def test_report_heightened_crack_provenance_fails_closed(
    mutation,
    missing_text,
):
    out = _out()
    heightened = _heightened_crack_result()
    mutation(heightened)
    out["heightened_crack_control"] = heightened

    flat = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), out, figures=False, qa_appendix=False,
    )).split())

    assert "Worked calculation unavailable" in flat
    assert missing_text in flat


def test_report_renders_greek_glyphs():
    # The ASCII engineering tokens are rendered as Greek glyphs in the PDF.
    txt = _pdf_text(sector_report.build_report({}, _inp(), _out(), figures=False))
    assert chr(0x3C3) in txt        # sigma
    assert chr(0x3BA) in txt        # kappa
    assert "kappa" not in txt and "sigma" not in txt


def test_report_crack_width_uses_millimetres_not_metres():
    # wk/sr_max/phi/cover are already in mm; the report must not multiply by 1000.
    txt = _pdf_text(sector_report.build_report({}, _inp(), _out(), figures=False))
    assert "235.0" in txt and "235000" not in txt     # sr_max stays mm
    assert "0.213" in txt                              # wk in mm (0.213 mm)
    assert "213.000" not in txt                        # wk not 1000x (would be 213 mm)


def test_report_crack_example_publishes_every_retained_interim_selection():
    flat = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), _out(), figures=False, qa_appendix=False,
    )).split())
    assert "2.5(h-d)" in flat
    assert "A c,eff" in flat or "Ac,eff" in flat
    assert "first candidate" in flat
    assert "lower bound" in flat
    assert "formula-7.9" in flat
    assert "close-centre threshold" in flat
    assert "Formula (7.11) selected" in flat
    assert "235 mm" in flat


def test_report_reinforcement_areas_are_already_square_millimetres():
    inp = _inp()
    inp["bars"] = [(0.0, -0.12, 321.123)]
    inp["tendons"] = [(0.0, 0.12, 654.321)]
    txt = _pdf_text(sector_report.build_report({}, inp, {}, figures=False))
    assert "321.123" in txt
    assert "654.321" in txt
    assert "321123000" not in txt
    assert "654321000" not in txt


def test_oversized_reinforcement_table_repeats_its_header():
    inp = _inp()
    inp["bars"] = [
        (0.0, -0.12, 300.0 + index)
        for index in range(120)
    ]
    pdf = sector_report.build_report({}, inp, {}, figures=False)

    import io
    import pypdf

    pages = [page.extract_text() or ""
             for page in pypdf.PdfReader(io.BytesIO(pdf)).pages]
    bar_pages = [page for page in pages if "Area (mm" in page]
    assert len(bar_pages) >= 2
    assert all("x (mm)" in page and "y (mm)" in page for page in bar_pages)


def test_report_crack_worked_uses_the_governing_case():
    # When the short-term load gives the larger wk, the worked example uses it.
    out = _out()
    out["elastic"]["crack"] = dict(_crack(), wk=0.15)
    out["elastic"]["crack_short"] = dict(_crack(), wk=0.30)
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "short-term" in txt
    assert "governing case (long-term)" not in txt


def test_report_wide_spacing_shows_geometric_formula():
    # A 2004 wide-spacing result carries sr_max as Eq (7.14) = 1.3(h-x); the worked
    # example must render (7.14), not the (7.11) close-centre formula it can't
    # reproduce.
    out = _out()
    out["elastic"]["crack"] = _wide_crack()
    out["elastic"]["crack_short"] = _wide_crack()
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "(7.14)" in txt
    assert "close centres" in txt


def test_report_dk_na_shows_fine_and_coarse_columns():
    # The DK NA option reports the fine and the coarse crack system side by side,
    # each for both load cases (four crack-width columns).
    out = _out()
    out["elastic"]["crack"] = dict(_crack(), coarse=False, wk=0.20)
    out["elastic"]["crack_short"] = dict(_crack(), coarse=False, wk=0.25)
    out["elastic"]["crack_coarse"] = _coarse_crack(wk=0.10)
    out["elastic"]["crack_short_coarse"] = _coarse_crack(wk=0.12)
    out["elastic"]["crack_code"] = "DS/EN 1992-1-1 + DK NA"
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "coarse" in txt.lower() and "fine" in txt.lower()   # both systems in the table


def test_report_shows_coarse_only_results():
    # DK NA edge case: the fine (h-x)/3 band has no tension bar but the coarse
    # centroid-matched band does. The report must still show the coarse widths, not
    # the "No crack width" message.
    out = _out()
    out["elastic"]["crack"] = None
    out["elastic"]["crack_short"] = None
    out["elastic"]["crack_coarse"] = _coarse_crack()
    out["elastic"]["crack_short_coarse"] = _coarse_crack()
    out["elastic"]["crack_code"] = "DS/EN 1992-1-1 + DK NA"
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "No crack width" not in txt
    assert "coarse" in txt.lower()


def test_report_coarse_worked_shows_half_factor_when_it_governs():
    # When the coarse case has the largest wk it is the worked example, and Eq (7.8)
    # shows the 1/2 factor of the coarse crack system.
    out = _out()
    out["elastic"]["crack"] = dict(_crack(), coarse=False, wk=0.10)
    out["elastic"]["crack_short"] = dict(_crack(), coarse=False, wk=0.10)
    out["elastic"]["crack_coarse"] = _coarse_crack(wk=0.30)
    out["elastic"]["crack_short_coarse"] = _coarse_crack(wk=0.30)
    out["elastic"]["crack_code"] = "DS/EN 1992-1-1 + DK NA"
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert chr(0xBD) in txt            # the 1/2 glyph rendered in Eq (7.8)


def test_report_ec2_2023_shows_refined_formula():
    # The EN 1992-1-1:2023 worked example shows the refined (9.8) formula with kw.
    out = _out()
    out["elastic"]["crack"] = _crack_2023()
    out["elastic"]["crack_short"] = _crack_2023()
    out["elastic"]["crack_code"] = "EN 1992-1-1:2023"
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "9.8" in txt and "9.2.3" in txt      # the 2023 clause and crack formula
    assert "1.7" in txt                          # kw in the worked substitution


def test_ensure_image_server_uses_shared_export_coordinator(monkeypatch):
    calls = []
    monkeypatch.setattr(
        publication_image_export,
        "ensure_ready",
        lambda *, timeout: calls.append(timeout),
    )

    sector_report.ensure_image_server(timeout=7.5)

    assert calls == [7.5]


def test_ensure_image_server_fails_closed_when_coordinator_fails(monkeypatch):
    def fail(*, timeout):
        del timeout
        raise publication_image_export.KaleidoExportError("unavailable")

    monkeypatch.setattr(publication_image_export, "ensure_ready", fail)
    with pytest.raises(
        sector_report.ReportFigureError,
        match="report not created",
    ):
        sector_report.ensure_image_server()


def test_tables_only_report_does_not_start_the_image_server(monkeypatch):
    # A figures-disabled report renders no figures, so it must not launch a browser.
    calls = {"n": 0}
    monkeypatch.setattr(sector_report, "ensure_image_server",
                        lambda: calls.__setitem__("n", calls["n"] + 1))
    sector_report.build_report({}, _inp(), _out(), figures=False)
    assert calls["n"] == 0


def test_report_uses_the_canonical_input_table_registry_module():
    assert sector_report.table_fields is sys.modules[
        "app.table_field_definitions"
    ]
    assert "table_field_definitions" not in sys.modules


@pytest.mark.parametrize(
    ("table_key", "field_key", "expected"),
    (
        (
            sector_report.table_fields.PLASTIC_CASES_TABLE_KEY,
            "n_ed_kn",
            "N<sub>Ed</sub>",
        ),
        (
            sector_report.table_fields.PLASTIC_CASES_TABLE_KEY,
            "mx_ed_knm",
            "M<sub>x,Ed</sub>",
        ),
        (
            sector_report.table_fields.FATIGUE_SPECTRUM_TABLE_KEY,
            "n_short_ed_kn",
            "&#916; N<sub>Ed</sub>",
        ),
    ),
)
def test_report_input_table_symbols_are_registered_markup(
    table_key, field_key, expected
):
    markup = sector_report._input_table_symbol(table_key, field_key)
    assert markup == expected
    assert not any(token in markup for token in ("\\", "{", "}"))


def test_tables_only_load_tables_publish_input_policy_without_raw_tex():
    inp = _inp()
    plastic = {
        "name": "PL-INPUT",
        "description": "Input publication",
        "n_ed_kn": 0.0,
        "mx_ed_knm": 1.23456789,
        "my_ed_knm": 0.0,
        "vx_ed_kn": 0.0,
        "vy_ed_kn": 0.0,
        "vx_face": "auto",
        "vy_face": "auto",
        "t_ed_knm": 0.0,
        "check_minimum_reinforcement": False,
    }
    elastic = {
        "name": "EL-INPUT",
        "description": "Input publication",
        "n_long_ed_kn": 0.0,
        "mx_long_ed_knm": 2.34567891,
        "my_long_ed_knm": 0.0,
        "n_short_ed_kn": 0.0,
        "mx_short_ed_knm": 0.0,
        "my_short_ed_knm": 0.0,
        "calculate_crack_width": False,
    }
    inp.update({
        "plastic_cases": [plastic],
        "elastic_cases": [elastic],
        "fatigue_on": True,
        fatigue_inputs.SPECTRUM_TABLE_KEY:
            fatigue_inputs.normalise_spectrum_table([{
                "spectrum": "Spectrum A",
                "name": "FAT-INPUT",
                "description": "Input publication",
                "cycles": 12345.0,
                "n_long_ed_kn": 0.0,
                "mx_long_ed_knm": 0.0,
                "my_long_ed_knm": 0.0,
                "n_short_ed_kn": 3.45678912,
                "mx_short_ed_knm": 0.0,
                "my_short_ed_knm": 0.0,
            }]),
    })
    out = {
        "plastic_cases": [{
            "actions": plastic, "evaluated": False, "results": {},
        }],
        "elastic_cases": [{
            "actions": elastic, "evaluated": False, "results": {},
        }],
    }

    text = _pdf_text(sector_report.build_report(
        {}, inp, out, figures=False, qa_appendix=False,
    ))
    flat = " ".join(text.split())
    policy = (
        "Load-table input accepts a dot or comma as the decimal separator; "
        "blank action cells are treated as zero; calculations use the "
        "parsed numeric precision."
    )
    assert flat.count(policy) == 1
    assert chr(0x394) in text
    assert not any(token in text for token in (r"\Delta", "_{", "}"))


def test_fatigue_action_headers_use_registry_in_loads_and_detail(monkeypatch):
    inp, out = _fatigue_report_fixture()
    # Enter the current table-based Loads route without adding calculation
    # results for either ordinary case family.
    inp["plastic_cases"] = []
    inp["elastic_cases"] = []
    calls = []
    original = sector_report._input_table_symbol

    def registered_symbol(table_key, field_key):
        calls.append((table_key, field_key))
        return original(table_key, field_key)

    monkeypatch.setattr(
        sector_report, "_input_table_symbol", registered_symbol
    )
    text = _pdf_text(sector_report.build_report(
        {}, inp, out, figures=False, qa_appendix=False,
    ))
    table_key = sector_report.table_fields.FATIGUE_SPECTRUM_TABLE_KEY
    for field_key in fatigue_inputs.ACTION_COLUMNS:
        # Once in Loads and again in each selected detailed spectrum unit.
        assert calls.count((table_key, field_key)) >= 2
    assert chr(0x394) in text
    assert r"\Delta" not in text
    assert "_{" not in text


def test_report_includes_the_nm_interaction_when_present():
    # An opt-in N-M interaction payload (both bending axes) adds titled sections to
    # the plastic part.
    out = _out()
    branch = dict(N=[-500.0, 0.0, 1500.0, 4000.0], M=[80.0, 300.0, 340.0, 0.0],
                  applied=(200.0, 100.0), converged=True)
    out["plastic"]["interaction"] = dict(x=branch, y=branch)
    txt = _pdf_text(sector_report.build_report(
        {}, _inp(), out, figures=False, profile="Standard"
    ))
    assert "interaction" in txt.lower()
    assert "squash" in txt.lower()
    assert "N-M" in txt or ("Mx" in txt and "My" in txt)   # both axes titled
    assert "Numerical N-M boundary" not in txt
    assert "4000.000" not in txt

    audit = _pdf_text(sector_report.build_report(
        {}, _inp(), out, figures=False, profile="Audit"
    ))
    assert "Numerical N-M boundary" in audit
    assert "4000.000" in audit


def test_long_nm_boundary_repeats_its_numeric_traceability_header():
    out = _out()
    branch = {
        "N": [float(index * 25 - 1000) for index in range(90)],
        "M": [float(300 - abs(index - 45) * 5) for index in range(90)],
        "applied": (0.0, 80.0),
        "converged": True,
    }
    out["plastic"]["interaction"] = {"x": branch, "y": branch}
    pdf = sector_report.build_report(
        {}, _inp(), out, figures=False, profile="Audit"
    )

    import io
    import pypdf

    pages = [page.extract_text() or ""
             for page in pypdf.PdfReader(io.BytesIO(pdf)).pages]
    table_pages = [page for page in pages if "N (Mx curve)" in page]
    assert len(table_pages) >= 2
    assert all("N (My curve)" in page and "Point" in page for page in table_pages)


def test_report_marks_failed_and_invalid_plastic_assessments_explicitly():
    failed = _out()
    failed["plastic"]["util"] = 1.25
    txt = _pdf_text(sector_report.build_report({}, _inp(), failed, figures=False))
    assert "FAIL - Plastic bending" in txt
    assert " pp" not in txt

    invalid = _out()
    invalid["plastic"]["converged"] = False
    txt = _pdf_text(sector_report.build_report({}, _inp(), invalid, figures=False))
    assert "INVALID - Plastic bending" in txt
    assert "diagnostic only" in txt
    assert "Utilisation (applied direction)" not in txt

    capacity_invalid = _out()
    capacity_invalid["plastic"].update(
        converged=False, check_util=False, applied=None
    )
    txt = _pdf_text(sector_report.build_report(
        {}, _inp(), capacity_invalid, figures=False
    ))
    assert "INVALID - Plastic bending" in txt
    assert "diagnostic only" in txt
    assert "not checked (capacity only)" not in txt

    origin_invalid = _out()
    origin_invalid["plastic"].update(
        util=None,
        util_valid=False,
        util_reason="Global moment origin lies outside the closed M-M envelope",
        util_origin_inside_or_on=False,
        util_gov=None,
        worked_point_basis="peak resultant moment",
    )
    txt = _pdf_text(sector_report.build_report(
        {}, _inp(), origin_invalid, figures=False
    ))
    assert "INVALID - Plastic bending" in txt
    assert "does not contain the zero-moment origin" in txt
    assert "Global moment origin lies outside the closed M-M envelope" not in txt
    assert "open arc" not in txt.casefold()
    assert "Utilisation (applied direction)" not in txt
    assert "Worked plastic calculation (peak resultant moment)" in txt

    legacy = _out()
    legacy["plastic"].pop("util_valid")
    txt = _pdf_text(sector_report.build_report({}, _inp(), legacy, figures=False))
    assert "saved result cannot confirm that the M-M envelope contains" in txt
    assert "Utilisation (applied direction)" not in txt

    absent = _out()
    absent["plastic"].update(util=None, util_valid=True, util_gov=None)
    txt = _pdf_text(sector_report.build_report({}, _inp(), absent, figures=False))
    assert "closed envelope has no available utilisation result" in txt
    assert "open arc" not in txt.casefold()


def test_legacy_multi_case_utilisation_cannot_select_or_publish_worked_point():
    inp = _inp()
    rows = [
        {
            "name": name,
            "description": description,
            "n_ed_kn": 0.0,
            "mx_ed_knm": moment,
            "my_ed_knm": 0.0,
            "vx_ed_kn": 0.0,
            "vy_ed_kn": 0.0,
            "vx_face": "auto",
            "vy_face": "auto",
            "t_ed_knm": 0.0,
        }
        for name, description, moment in (
            ("PL-LEGACY-HIGH", "High stale utilisation", 80.0),
            ("PL-LEGACY-CAPACITY", "Larger retained capacity", 20.0),
        )
    ]
    inp["plastic_cases"] = rows
    high_stale_util = copy.deepcopy(_out()["plastic"])
    high_stale_util.update(util=1.4, worked_point_basis="utilisation direction")
    high_stale_util.pop("util_valid")
    larger_capacity = copy.deepcopy(_out()["plastic"])
    larger_capacity.update(
        util=0.2,
        mx=[200.0, 0.0, -200.0, 0.0],
        max_mx=200.0,
        min_mx=-200.0,
        worked_point_basis="utilisation direction",
    )
    larger_capacity.pop("util_valid")
    out = _out()
    out["plastic_cases"] = [
        {
            "name": row["name"],
            "actions": row,
            "evaluated": True,
            "results": {"plastic": result},
        }
        for row, result in zip(
            rows, (high_stale_util, larger_capacity), strict=True
        )
    ]

    selected = result_presentation.worked_example_selection(inp, out)
    assert selected["families"]["plastic"]["case_id"] == "PL-LEGACY-CAPACITY"

    out["worked_example_selection"] = selected
    txt = " ".join(_pdf_text(_build_report_from_completed_payload(
        {}, inp, out, figures=False,
    )).split())
    assert "saved result cannot confirm that the M-M envelope contains" in txt
    assert "Worked plastic calculation unavailable" in txt
    assert "Worked plastic calculation (utilisation direction)" not in txt


def test_legacy_plastic_cannot_publish_retained_combined_verdict():
    out = _out()
    out["plastic"].pop("util_valid")
    out["combined"] = _combined_out()
    inp = _inp()
    inp.update(combined_on=True, shear_on=True, torsion_on=True)

    txt = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False,
    )).split())

    assert "Combined bending + shear + torsion" in txt
    assert (
        "saved bending result cannot confirm that the M-M envelope contains "
        "the origin" in txt
    )
    assert "Recalculate before assessing M-V-T interaction" in txt
    assert "recalculate" in txt.casefold()
    assert "Governing combined worked example" not in txt
    assert "130.0 %" not in txt


def test_report_handles_plastic_only():
    out = {"plastic": _out()["plastic"]}
    inp = _inp()
    inp["mode"] = "Plastic"
    pdf = sector_report.build_report({}, inp, out, figures=False)
    assert pdf[:4] == b"%PDF"
    txt = _pdf_text(pdf)
    assert "Cracked-section elastic stresses" not in txt
    assert "crack width" not in txt.lower()


def test_report_plastic_only_omits_inactive_sls_action_set():
    out = {"plastic": _out()["plastic"]}
    inp = _inp()
    inp["mode"] = "Plastic"
    txt = _pdf_text(sector_report.build_report({}, inp, out, figures=False))
    assert "PL-TEST" in txt
    assert "EL-TEST" not in txt


def test_report_elastic_only_omits_plastic_theory():
    out = {"elastic": _out()["elastic"]}
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Plastic section capacity" not in txt
    assert "Cracked-section elastic stresses" in txt


def test_report_capacity_only_omits_utilisation():
    # A capacity-only run (utilisation not checked) reports no utilisation value.
    out = _out()
    out["plastic"].update(
        util=None,
        util_valid=None,
        util_reason=None,
        util_origin_inside_or_on=None,
        check_util=False,
        applied=None,
    )
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "capacity only" in txt
    assert "applied direction" not in txt    # no utilisation percentage row
    assert "Plastic (applied)" not in txt    # ignored moments not listed as loads


def test_report_tolerates_plastic_payload_without_applied():
    # An older plastic payload may have a utilisation but no 'applied' point; the
    # report must not crash indexing it.
    out = _out()
    out["plastic"].pop("applied", None)
    pdf = sector_report.build_report({}, _inp(), out, figures=False)
    assert pdf[:4] == b"%PDF"


def test_report_handles_no_results():
    pdf = sector_report.build_report({}, _inp(), {}, figures=False)
    assert pdf[:4] == b"%PDF"


def _pdf_text(pdf):
    import io
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    return "\n".join(page.extract_text() for page in reader.pages)


def _outline_items(items):
    for item in items:
        if isinstance(item, list):
            yield from _outline_items(item)
        else:
            yield item


def _pdf_outline_titles(pdf):
    import io
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(pdf))
    return tuple(
        str(getattr(item, "title", ""))
        for item in _outline_items(reader.outline)
    )


def _pdf_body_text(pdf):
    """Return report content from the linked Results summary onward."""
    import io
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(pdf))

    results = next(
        item
        for item in _outline_items(reader.outline)
        if str(getattr(item, "title", "")).endswith("Results summary")
    )
    first_page = reader.get_destination_page_number(results)
    return "\n".join(
        (page.extract_text() or "") for page in reader.pages[first_page:]
    )


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_report_profiles_publish_exact_2023_input_and_material_sources(profile):
    import sector.material_presets as mp

    edition = codes.EC2_2023.label
    inp = _inp()
    inp.update({
        "concrete_preset": edition,
        "mild_preset": edition,
        "prestress_preset": edition,
        "prestress": mp.build_prestress(**mp.PRESTRESS_PRESETS[edition]),
        "tendons": [(0.0, 0.10, 200.0)],
        "detailing_edition": detailing.EC2_2023,
        "minimum_reinforcement_on": True,
        "transverse_detailing_on": True,
        "clear_spacing_on": True,
    })
    text = _pdf_text(sector_report.build_report(
        {}, inp, _out(), figures=False, profile=profile
    ))
    normalised = " ".join(text.split())
    for source in (
        "DS/EN 1992-1-1:2023, 5.1.5, Table 5.2 and Annex B.5",
        "DS/EN 1992-1-1:2023, 12.2(2), Formulae (12.1)-(12.2), and Table 12.2",
        "DS/EN 1992-1-1:2023, 8.2.1(2), 12.2(4), Tables 12.1 and 12.2, 12.3.3 and 12.4.2",
        "DS/EN 1992-1-1:2023, 11.2(2)",
        "DS/EN 1992-1-1:2023, 8.1.1(2)-(3) and 8.1.2(1), Formula (8.4)",
        "DS/EN 1992-1-1:2023, 5.2.4(1)-(3), Formula (5.11) and Figure 5.2",
        "DS/EN 1992-1-1:2023, 5.3.3(1)-(3), Formula (5.12) and Figure 5.3",
    ):
        assert source in normalised
    assert chr(0x2030) in text
    assert "per mille" not in text.casefold()
    assert "permille" not in text.casefold()


def test_report_omits_unused_material_sections():
    # Bars only -> mild steel is reported, prestress is omitted.
    inp = _inp()
    txt = _pdf_text(sector_report.build_report({}, inp, _out(), figures=False))
    assert "Design yield" in txt
    assert "Initial prestrain" not in txt
    # Tendons only -> prestress is reported, mild steel is omitted.
    import sector.material_presets as mp
    inp2 = _inp()
    inp2["bars"] = []
    inp2["tendons"] = [(0.0, -0.12, 5.0e-4)]
    inp2["prestress"] = mp.build_prestress(**list(mp.PRESTRESS_PRESETS.values())[0])
    txt2 = _pdf_text(sector_report.build_report({}, inp2, _out(), figures=False))
    assert "Initial prestrain" in txt2
    assert "Design yield" not in txt2
    # No mild bars -> no compression bar-strain split (would be a spurious eps_s,c row).
    assert "Most-compressed bar" not in txt2


def test_report_ec2_2023_material_strength_is_edition_aware():
    from sector.materials import Concrete

    inp = _inp()
    eta = (40.0 / 45.0) ** (1.0 / 3.0)
    inp["concrete"] = Concrete(
        fck=45.0, gamma_c=1.5, alpha_cc=0.85 * eta, curve=2,
    )
    inp["concrete_preset"] = "DS/EN 1992-1-1:2023"
    inp["concrete_eta_cc"] = eta
    inp["concrete_k_tc"] = 0.85
    inp["mild_preset"] = "DS/EN 1992-1-1:2023"
    inp["design_basis"] = {
        "status": "Edition-aligned: EN 1992-1-1:2023",
        "components": [
            {"role": "Concrete material", "selection": "DS/EN 1992-1-1:2023"},
            {"role": "Reinforcing steel", "selection": "DS/EN 1992-1-1:2023"},
        ],
        "mixed": False, "limitations": [],
    }
    out = {"material_properties": {
        "concrete": {"design_strength_mpa": inp["concrete"].fcd},
        "mild": [], "prestress": [],
    }}
    txt = _pdf_text(sector_report.build_report({}, inp, out, figures=False))
    flat = " ".join(txt.split())
    assert "5.1.6" in txt and "5.3" in txt and "5.4" in txt
    assert "8.1.2" in txt and "8.4" in txt
    assert "0.85" in txt
    assert f"{eta:.6f}" in txt
    assert f"{0.85 * eta:.6f}" in txt
    assert f"{inp['concrete'].fcd:.3f}" in txt
    assert chr(0x3B7) in txt  # eta_cc uses the Greek symbol
    assert "Curve 3 Eurocode design preset" in " ".join(txt.split())
    assert "3.15" not in txt
    assert "published project-adoption basis" in flat
    assert "no Danish National Annex is applied" in flat
    assert "confinement enhancement is not included or assessed" in flat


def test_concrete_table_and_design_strength_equation_share_one_layout_group():
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, _inp(), _out(), figures=False,
    )
    builder._h1("Inputs")
    builder._h2("Concrete")
    builder._concrete_block()

    matching_groups = []
    for flowable in builder.flow:
        if not isinstance(flowable, sector_report.KeepTogether):
            continue
        equation_keys = {
            item._sector_equation_key
            for item in getattr(flowable, "_sector_equations", ())
        }
        if "materials.concrete.fcd" in equation_keys:
            matching_groups.append((flowable, equation_keys))

    assert len(matching_groups) == 1
    group, equation_keys = matching_groups[0]
    assert any(
        isinstance(item, sector_report._PaginatedReportTable)
        for item in group._content
    )
    assert equation_keys == {"materials.concrete.fcd"}
    assert not any(
        isinstance(item, sector_report._EquationFlowable)
        for item in group._content
    )
    assert any(
        isinstance(item, sector_report._EquationFlowable)
        and item._sector_equation_key == "materials.concrete.curve-2"
        for item in builder.flow
    )

    # Put the bounded calculation near a page foot.  It must move as one measured
    # unit instead of releasing the equation onto the following page.
    import pypdf

    paginated = sector_report.ReportBuilder(
        io.BytesIO(), {}, _inp(), _out(), figures=False,
    )
    paginated._h1("Inputs")
    paginated.flow.append(sector_report.Spacer(1, 500))
    paginated._h2("Concrete")
    paginated._concrete_block()
    pdf = io.BytesIO()
    sector_report.SimpleDocTemplate(
        pdf,
        pagesize=sector_report.A4,
        leftMargin=20 * sector_report.mm,
        rightMargin=20 * sector_report.mm,
        topMargin=25 * sector_report.mm,
        bottomMargin=20 * sector_report.mm,
    ).build(list(paginated.flow))
    pages = [page.extract_text() or "" for page in pypdf.PdfReader(pdf).pages]
    table_pages = [
        index for index, text in enumerate(pages)
        if "Characteristic strength" in text
    ]
    equation_pages = [
        index for index, text in enumerate(pages)
        if "= 20 MPa" in text
    ]
    assert table_pages == equation_pages
    assert table_pages and table_pages[0] > 0


def test_report_prints_actual_custom_half_and_double_partial_factors():
    inp = _inp()
    inp["concrete"] = Concrete(
        fck=30.0, gamma_c=0.5, alpha_cc=1.0, curve=2
    )
    inp["steel"] = MildSteel(
        fytk=500.0,
        fyck=500.0,
        futk=550.0,
        eut=0.05,
        gamma_y=2.0,
        curve=2,
    )

    out = {"material_properties": {
        "concrete": {"design_strength_mpa": inp["concrete"].fcd},
        "mild": [{"material_id": "-", "design_yield_mpa": 250.0}],
        "prestress": [],
    }}
    text = " ".join(_pdf_text(
        sector_report.build_report({}, inp, out, figures=False)
    ).split())

    assert "60.000 MPa" in text
    assert "250.000 MPa" in text
    assert "0.500" in text
    assert "2.000" in text
    assert "final project inputs and are used directly" in text


def test_report_ec2_2023_k_tc_one_states_the_full_assumption():
    inp = _inp()
    inp["concrete_preset"] = "DS/EN 1992-1-1:2023"
    inp["concrete_eta_cc"] = 1.0
    inp["concrete_k_tc"] = 1.0
    inp["mild_preset"] = "DS/EN 1992-1-1:2023"
    out = {"material_properties": {
        "concrete": {"design_strength_mpa": inp["concrete"].fcd},
        "mild": [], "prestress": [],
    }}
    txt = _pdf_text(sector_report.build_report({}, inp, out, figures=False))
    assert "28 days" in txt and "56 days" in txt
    assert "at least 3 months" in txt
    assert "National" in txt and "Annex" in txt


def test_report_ignores_removed_design_basis_aggregate():
    inp = _inp()
    inp["design_basis"] = {
        "status": "Mixed/custom design basis - review every selected method",
        "components": [
            {"role": "Concrete material", "selection": "DS/EN 1992-1-1:2023"},
            {"role": "Torsion", "selection": "DS/EN 1992-1-1:2005 + DK NA:2024"},
        ],
        "mixed": True,
        "limitations": [
            "Sector does not implement the torsion check to EN 1992-1-1:2023."
        ],
    }
    txt = _pdf_text(sector_report.build_report({}, inp, {}, figures=False))
    assert "Design basis qualification" not in txt
    assert "Mixed/custom design basis" not in txt
    assert "does not implement the torsion check" not in txt


def test_report_ignores_removed_authority_approval_and_cover_calculator_metadata():
    inp = _inp()
    inp.update({
        "infrastructure_manager": "OBSOLETE-MANAGER-MARKER",
        "asset_class": "OBSOLETE-ASSET-MARKER",
        "project_basis": "OBSOLETE-BASIS-MARKER",
        "cover_calculator": {"cover_mm": 999.0},
    })
    meta = {
        "checker": "OBSOLETE-CHECKER-MARKER",
        "approver": "OBSOLETE-APPROVER-MARKER",
    }

    text = _pdf_text(sector_report.build_report(
        meta, inp, _out(), figures=False
    ))

    for marker in (
        "OBSOLETE-MANAGER-MARKER",
        "OBSOLETE-ASSET-MARKER",
        "OBSOLETE-BASIS-MARKER",
        "OBSOLETE-CHECKER-MARKER",
        "OBSOLETE-APPROVER-MARKER",
        "999.0",
    ):
        assert marker not in text


def test_report_ignores_stale_bridge_and_trace_payloads():
    inp = _inp()
    out = _out()
    out["bridge"] = {
        "selected_standard": "OBSOLETE-BRIDGE-STANDARD",
        "calculations": {"brittle_method_b": object()},
        "failures": [{"message": "OBSOLETE-BRIDGE-FAILURE"}],
    }
    out["calculation_traces"] = {
        "bundles": [{"untrusted": object()}],
        "errors": [{"message": "must remain inert"}],
    }
    text = " ".join(_pdf_text(
        sector_report.build_report({}, inp, out, figures=False)
    ).split())

    for removed in (
        "Independent bridge calculations",
        "Optional brittle Method B",
        "OBSOLETE-BRIDGE-STANDARD",
        "OBSOLETE-BRIDGE-FAILURE",
        "Calculation trace",
        "must remain inert",
    ):
        assert removed not in text


def test_report_handles_uncracked_section():
    out = _out()
    out["elastic"]["cracked"] = False
    out["elastic"]["crack"] = None
    out["elastic"]["crack_short"] = None
    out["elastic"]["props_cr"] = None
    pdf = sector_report.build_report({}, _inp(), out, figures=False)
    assert pdf[:4] == b"%PDF"


def _shear_out():
    return {"res": {"vrd_c": 103.4, "k": 1.603, "rho_l": 0.0089, "sigma_cp": 0.0,
                    "fcd": 24.14, "v_basic": 0.627, "v_floor": 0.535, "crd_c": 0.1241,
                    "vmin": 0.535, "k1": 0.15, "valid": True},
            "v_ed": 80.0, "util": 80.0 / 103.4, "axis": "x", "tension_low": True,
            "bw": 300.0, "bw_auto": 300.0, "bw_user": False, "d": 550.0,
            "asl": 1473.0, "ac": 0.18, "fck": 35.0, "n_ed": 0.0,
            "method": "DS/EN 1992-1-1:2005 + DK NA:2024"}


def test_report_includes_shear_section():
    out = _out()
    out["shear"] = _shear_out()
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Shear resistance" in txt          # the section heading
    assert "6.2.2" in txt                     # the clause reference
    assert "103.4" in txt                     # the VRd,c value
    assert "Utilisation" in txt
    assert "selected 2005 no-links resistance has no z operand" in txt


def _native_sparse_link_report_fixture():
    # The frozen 80/103.417/29.452 route oracle retained no link geometry.
    # Reverse the native 2005 kernel once to define a reproducible test layout.
    demand_kn = 80.0
    concrete_resistance_kn = 103.417
    link_resistance_kn = 29.452
    link_diameter_mm = 4.0
    link_legs = 2.0
    link_area_mm2 = link_legs * math.pi * link_diameter_mm**2 / 4.0
    link_arm_mm = 495.0
    fywk_mpa = 500.0
    cot_min = 1.0
    cot_max = 2.5
    asw_over_s = link_resistance_kn * 1000.0 / (
        link_arm_mm
        * (fywk_mpa / codes.EC2_2005_DKNA.gamma_s)
        * cot_max
    )
    link_spacing_mm = link_area_mm2 / asw_over_s

    link_result = shear_core.vrd_links(
        35.0,
        codes.EC2_2005_DKNA,
        300.0,
        550.0,
        asw_over_s,
        fywk_mpa,
        0.0,
        0.18,
        cot_min,
        cot_max,
        z_mm=link_arm_mm,
        v_ed_kn=demand_kn,
    )
    links = {
        "res": link_result,
        "util": demand_kn / link_result["vrd"],
        "asw": link_area_mm2,
        "asw_over_s": asw_over_s,
        "effective_asw_over_s": asw_over_s,
        "asw_factor": 1.0,
        "legs": link_legs,
        "dia": link_diameter_mm,
        "s": link_spacing_mm,
        "fywk": fywk_mpa,
        "cot_min": cot_min,
        "cot_max": cot_max,
        "cot_limit_lo": cot_min,
        "cot_limit_hi": cot_max,
        "delta_ftd": 0.0,
        "longitudinal_shear_force": 0.0,
        "longitudinal_assessment": {
            "status": "NOT APPLICABLE",
            "reason": "no_longitudinal_chord_action",
        },
        "z_source": "plastic internal lever arm",
        "z_component": "z_y",
        "z_source_angle_deg": 90.0,
        "z_source_case": "PL-TEST",
        "z_source_axial_kn": 0.0,
        "out_of_limits": False,
        "required": False,
        "shear_geometry": {
            "bw_mm": 300.0,
            "resolved_form": "rectangular",
            "duct_case": "none",
            "duct_sum_mm": 0.0,
            "duct_factor_links": 1.0,
        },
    }

    transverse = detailing.transverse_reinforcement(
        edition=detailing.EC2_2005_DKNA,
        fck_mpa=35.0,
        fywk_mpa=fywk_mpa,
        diameter_mm=link_diameter_mm,
        spacing_mm=link_spacing_mm,
        shear_directions=[{
            "component": "vy",
            "bw_mm": 300.0,
            "d_mm": 550.0,
            "legs": link_legs,
            "transverse_leg_spacing_mm": 300.0,
            "links_present": True,
            "links_required": False,
        }],
    )

    sh = _shear_out()
    sh["res"]["vrd_c"] = concrete_resistance_kn
    sh["util"] = demand_kn / concrete_resistance_kn
    sh["links"] = links
    sh["nominal_resistance"] = asdict(
        capacity.select_nominal_shear_resistance(sh, links_selected=True)
    )
    sh.update(
        resistance_status="PASS",
        assessment_status="PASS",
        assessment_ok=True,
    )

    inp = _inp()
    inp.update(
        shear_on=True,
        shear_links=True,
        transverse_detailing_on=True,
        shear_method=codes.EC2_2005_DKNA.label,
        shear_link_legs=link_legs,
        shear_link_dia=link_diameter_mm,
        shear_link_s=link_spacing_mm,
    )
    return inp, sh, transverse


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_report_profiles_keep_sparse_links_separate_from_nominal_capacity(
    profile,
):
    inp, sh, transverse = _native_sparse_link_report_fixture()
    links = sh["links"]
    minimum_ratio = next(
        check for check in transverse["checks"]
        if check["kind"] == "minimum_ratio"
    )
    assert links["res"]["vrd"] == pytest.approx(29.452)
    assert links["s"] == pytest.approx(440.00644085487903)
    assert links["asw_over_s"] == pytest.approx(
        links["asw"] / links["s"]
    )
    assert transverse["diameter_mm"] == links["dia"]
    assert transverse["spacing_mm"] == links["s"]
    assert minimum_ratio["legs"] == links["legs"]
    assert minimum_ratio["provided"] == pytest.approx(
        links["asw_over_s"] / sh["bw"]
    )
    assert transverse["governing"] == minimum_ratio
    assert transverse["governing_utilisation"] == pytest.approx(
        minimum_ratio["utilisation"]
    )
    detailing_utilisation = (
        f"{100.0 * transverse['governing_utilisation']:.1f} %"
    )
    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {},
                inp,
                {"shear": sh, "transverse_reinforcement": transverse},
                figures=False,
                profile=profile,
            )
        ).split()
    )

    assert "Shear without links" in text
    assert "PASS" in text
    assert "77.4 % (VEd / VRd,c)" in text
    assert "Shear with links" in text
    assert "NOT APPLICABLE" in text
    assert "271.6 % (non-governing)" in text
    assert "Shear/torsion link detailing" in text
    assert "FAIL" in text
    assert "271.6 % (EXCEEDED)" not in text
    if profile != "Brief":
        assert "103.417" in text
        assert "29.452" in text
        assert "2 x 4 / 440 mm" in text
        assert text.count(detailing_utilisation) >= 2
        assert "Separate link detailing assessment: FAIL" in text
        assert "non-governing comparison" in text
        assert "no longitudinal shear force is applied" in text


def test_report_audits_independent_governing_faces_and_angles():
    out = _out()
    sh = _shear_out()
    negative = copy.deepcopy(sh)
    positive = copy.deepcopy(sh)
    positive.update(tension_low=False, util=0.65)
    sh.update(
        component="vy",
        face_mode="auto",
        both_faces_evaluated=True,
        governing_face="negative",
        face_candidates=[
            dict(
                tension_low=True, shear=negative, shear_status="PASS",
                torsion_status="PASS", combined_status="PASS",
            ),
            dict(
                tension_low=False, shear=positive, shear_status="PASS",
                torsion_status="FAIL", combined_status="FAIL",
            ),
        ],
        governing_domains={
            "shear": dict(face="negative", cot=1.25, status="PASS", util=0.77),
            "vt": dict(face="positive", cot=1.75, status="FAIL", util=1.10),
            "combined": dict(face="positive", cot=1.75, status="FAIL", util=1.20),
        },
    )
    out["shear"] = sh

    text = " ".join(_pdf_text(
        sector_report.build_report({}, _inp(), out, figures=False)
    ).split())
    assert "Independent governing selections" in text
    assert "bottom (-y)" in text and "top (+y)" in text
    assert "1.250" in text and "1.750" in text
    assert "V+T (6.29)" in text


def test_report_legacy_blocker_sanitizes_both_face_combined_cells_only():
    out = _out()
    out["plastic"].pop("util_valid")
    out["combined"] = _combined_out()
    sh = _shear_out()
    negative = copy.deepcopy(sh)
    positive = copy.deepcopy(sh)
    positive.update(tension_low=False, util=0.65)
    sh.update(
        component="vy",
        both_faces_evaluated=True,
        face_candidates=[
            dict(
                tension_low=True,
                shear=negative,
                shear_status="SHEAR KEPT A",
                torsion_status="V+T KEPT A",
                combined_status="STALE COMBINED A",
            ),
            dict(
                tension_low=False,
                shear=positive,
                shear_status="SHEAR KEPT B",
                torsion_status="V+T KEPT B",
                combined_status="STALE COMBINED B",
            ),
        ],
        governing_domains={
            "shear": dict(
                face="negative", cot=1.25, status="SHEAR KEPT", util=0.77,
            ),
            "vt": dict(
                face="positive", cot=1.75, status="V+T KEPT", util=1.10,
            ),
            "combined": dict(
                face="positive", cot=1.75, status="STALE DOMAIN", util=9.87654,
            ),
        },
    )
    out["shear"] = sh
    before = copy.deepcopy(out)
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, _inp(), out, figures=False,
    )
    tables = []
    builder._table = lambda rows, *args, **kwargs: tables.append(copy.deepcopy(rows))

    builder._shear_direction(sh, component="vy")

    face_rows = next(rows for rows in tables if rows[0][-1] == "Combined")
    assert [row[-3:] for row in face_rows[1:]] == [
        ["SHEAR KEPT A", "V+T KEPT A", "NOT ASSESSED"],
        ["SHEAR KEPT B", "V+T KEPT B", "NOT ASSESSED"],
    ]
    governing_rows = next(
        rows for rows in tables if rows[0][0] == "Check"
        and rows[0][-1] == "Status / outcome"
    )
    by_check = {row[0]: row for row in governing_rows[1:]}
    assert by_check["Shear"][-2:] == ["77.0 %", "SHEAR KEPT"]
    assert by_check["V+T (6.29)"][-2:] == ["110.0 %", "V+T KEPT"]
    assert by_check["Combined"] == [
        "Combined", "-", "-", "-", "NOT ASSESSED",
    ]
    rendered_text = " ".join(
        item.getPlainText()
        for item in builder.flow
        if hasattr(item, "getPlainText")
    )
    assert (
        "saved bending result cannot confirm that the M-M envelope contains "
        "the origin" in rendered_text
    )
    assert "Recalculate before assessing M-V-T interaction" in rendered_text
    assert out == before


def test_brief_governing_depth_does_not_publish_worked_selection_register():
    inp = _inp()
    actions = [
        {
            "name": "PL-LEGACY", "description": "Legacy",
            "n_ed_kn": 0.0, "mx_ed_knm": 0.0, "my_ed_knm": 0.0,
            "vx_ed_kn": 1.0, "vy_ed_kn": 0.0,
            "vx_face": "auto", "vy_face": "auto", "t_ed_knm": 1.0,
        },
        {
            "name": "PL-CURRENT", "description": "Current",
            "n_ed_kn": 0.0, "mx_ed_knm": 0.0, "my_ed_knm": 0.0,
            "vx_ed_kn": 2.0, "vy_ed_kn": 0.0,
            "vx_face": "auto", "vy_face": "auto", "t_ed_knm": 2.0,
        },
    ]
    inp["plastic_cases"] = actions
    legacy_plastic = copy.deepcopy(_out()["plastic"])
    legacy_plastic.pop("util_valid")
    out = {
        "plastic_cases": [
            {
                "actions": actions[0],
                "evaluated": True,
                "results": {
                    "plastic": legacy_plastic,
                    "combined": _combined_out(),
                },
            },
            {
                "actions": actions[1],
                "evaluated": True,
                "results": {
                    "plastic": copy.deepcopy(_out()["plastic"]),
                    "shear": _shear_out(),
                    "combined": _combined_out(),
                },
            },
        ],
        "worked_example_selection": {
            "schema": 1,
            "families": {
                "combined": {"case_id": "PL-LEGACY", "component": None},
                "shear": {"case_id": "PL-CURRENT", "component": None},
            },
            "crack_examples": [],
        },
    }
    selection_before = copy.deepcopy(out["worked_example_selection"])
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, inp, out, figures=False, profile="Brief",
    )
    tables = []
    builder._table = lambda rows, *args, **kwargs: tables.append(copy.deepcopy(rows))

    builder._brief_governing_register()

    rendered_text = " ".join(
        item.getPlainText()
        for item in builder.flow
        if hasattr(item, "getPlainText")
    )
    assert tables == []
    assert "Governing results and limitations" in rendered_text
    assert "Worked derivations, result chains and non-governing results begin" in rendered_text
    assert "Selected governing worked examples" not in rendered_text
    assert "PL-LEGACY" not in rendered_text
    assert "PL-CURRENT" not in rendered_text
    assert out["worked_example_selection"] == selection_before


def test_audit_appendix_claims_combined_method_only_for_assessable_case():
    inp = _inp()
    actions = [
        {
            "name": "PL-A", "description": "First",
            "n_ed_kn": 0.0, "mx_ed_knm": 0.0, "my_ed_knm": 0.0,
            "vx_ed_kn": 1.0, "vy_ed_kn": 0.0,
            "vx_face": "auto", "vy_face": "auto", "t_ed_knm": 1.0,
        },
        {
            "name": "PL-B", "description": "Second",
            "n_ed_kn": 0.0, "mx_ed_knm": 0.0, "my_ed_knm": 0.0,
            "vx_ed_kn": 2.0, "vy_ed_kn": 0.0,
            "vx_face": "auto", "vy_face": "auto", "t_ed_knm": 2.0,
        },
    ]
    inp["plastic_cases"] = actions
    legacy = copy.deepcopy(_out()["plastic"])
    legacy.pop("util_valid")
    out = {
        "plastic_cases": [
            {
                "actions": actions[0], "evaluated": True,
                "results": {
                    "plastic": copy.deepcopy(legacy),
                    "combined": _combined_out(),
                },
            },
            {
                "actions": actions[1], "evaluated": True,
                "results": {
                    "plastic": copy.deepcopy(legacy),
                    "combined": _combined_out(),
                },
            },
        ],
    }
    before = copy.deepcopy(out)
    sentence = (
        "The combined M-V-T chapter states the selected edition, the common "
        "strut-angle basis and the applicable interaction expressions."
    )

    def appendix_text(payload):
        builder = sector_report.ReportBuilder(
            io.BytesIO(), {}, inp, payload, figures=False, profile="Audit",
        )
        builder._appendix()
        return " ".join(
            item.getPlainText()
            for item in builder.flow
            if hasattr(item, "getPlainText")
        )

    assert sentence not in appendix_text(out)
    out["plastic_cases"][1]["results"]["plastic"]["util_valid"] = True
    assert sentence in appendix_text(out)
    out["plastic_cases"][1]["results"]["plastic"].pop("util_valid")
    assert out == before


def test_report_biaxial_shear_separates_directions_without_aggregate_interaction():
    out = _out()
    vx = copy.deepcopy(_shear_out())
    vx.update(component="vx", axis="y", tension_low=True, status="PASS")
    vy = copy.deepcopy(_shear_out())
    vy.update(component="vy", axis="x", tension_low=False, v_ed=65.0,
              util=65.0 / vy["res"]["vrd_c"], status="PASS")
    out["shear"] = dict(
        vx,
        directions={"vx": vx, "vy": vy},
        active_directions=["vx", "vy"],
        biaxial=True,
    )

    txt = " ".join(_pdf_text(
        sector_report.build_report({}, _inp(), out, figures=False)
    ).split())

    assert "Vx,Ed" in txt and "Vy,Ed" in txt
    assert "calculated independently" in txt
    assert "Generic cross-direction interaction is not calculated" in txt
    assert "no aggregate shear verdict is issued" in txt


def _shear_out_2023(gamma_v=1.40):
    from sector import codes as _codes, shear as _shear

    fyd = 500.0 / 1.15
    res = _shear.vrd_c_2023(
        35.0, _codes.EC2_2023, 300.0, 550.0, 1473.0, fyd, 32.0,
        n_ed_tension_kn=300.0, m_ed_knm=110.0, v_ed_kn=50.0,
        gamma_v=gamma_v,
    )
    return {"res": res,
            "v_ed": 50.0, "util": 50.0 / res["vrd_c"], "axis": "x",
            "tension_low": True,
            "bw": 300.0, "bw_auto": 300.0, "bw_user": False, "d": 550.0,
            "asl": 1473.0, "ac": 0.18, "fck": 35.0, "n_ed": 300.0,
            "method": "DS/EN 1992-1-1:2023", "model_2023": True, "ddg": 32.0,
            "fyd_flex": fyd, "m_ed_2023": 110.0, "m_prestress": 0.0,
            "centroid": (0.0, 0.0)}


def test_report_shear_2023_section():
    out = _out()
    sh = _shear_out_2023()
    out["shear"] = sh
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "8.27" in txt and "8.20" in txt          # the 2023 clauses
    assert "8.30" in txt and "8.31" in txt          # action/axial modification
    assert "8.2.2" in txt                            # the 2023 section reference
    assert f"{sh['res']['vrd_c']:.3f}" in txt        # VRd,c
    assert "Standard-defined arm z = 495.000 mm = 0.9d" in txt
    assert "8.2.1(3)" in txt
    assert "d" in txt and "dg" in txt                # ddg appears
    assert "k" in txt and "vp" in txt                # k_vp appears
    assert chr(0x221A) in txt                        # radical, not "sqrt"
    assert not any(
        token in txt for token in ("sqrt", "Cfrac", "Big", "sincos")
    )


@pytest.mark.parametrize("profile", ("Standard", "Audit"))
def test_report_shear_2023_reproduces_selected_gamma_v_and_references(profile):
    inp = _inp()
    inp.update({
        "shear_on": True,
        "shear_method": codes.EC2_2023.label,
        "shear_gamma_v": 1.234,
    })
    out = _out()
    out["shear"] = _shear_out_2023(gamma_v=1.234)

    txt = _pdf_text(
        sector_report.build_report(
            {}, inp, out, figures=False, profile=profile
        )
    )

    assert "Shear partial factor" in txt
    assert txt.count("1.234") >= 3
    assert re.search(r"1\.23(?:\D|$)", txt) is None
    assert "4.3.3" in txt
    assert "Table 4.3 NDP" in " ".join(txt.split())
    assert "8.2.2" in txt


def test_report_shear_shows_prestress_precompression():
    # F1: a prestressed section adds a tendon-precompression row (sigma_cp credit).
    out = _out()
    sh = _shear_out()
    sh["n_prestress"] = 900.0
    sh["res"]["sigma_cp"] = 4.5
    out["shear"] = sh
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Tendon precompression" in txt
    assert "900" in txt


def test_report_shear_2023_documents_axial_factor():
    out = _out()
    sh = _shear_out_2023()
    out["shear"] = sh
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Formula (8.31)" in txt
    assert f"{sh['res']['k_vp']:.4f}" in txt
    assert "parallel to the member axis" in txt
    assert "UNCONSERVATIVE" not in txt


def test_report_shear_2023_invalid_is_reportable():
    # Codex P2: an invalid 2023 result (from the engine) must render without a KeyError.
    from sector import codes as _codes, shear as _shear
    res = _shear.vrd_c_2023(35.0, _codes.EC2_2023, 300.0, 0.0, 1473.0, 434.8, 32.0)
    out = _out()
    sh = _shear_out_2023()
    sh["res"] = res
    out["shear"] = sh
    pdf = sector_report.build_report({}, _inp(), out, figures=False)
    assert pdf[:4] == b"%PDF"


def test_report_shear_flags_exceeded():
    out = _out()
    sh = _shear_out()
    sh["v_ed"], sh["util"] = 200.0, 200.0 / 103.4
    out["shear"] = sh
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "EXCEEDED" in txt


def test_report_without_shear_omits_the_section():
    txt = _pdf_text(sector_report.build_report({}, _inp(), _out(), figures=False))
    assert "Shear resistance" not in txt


def _torsion_out(interaction=False):
    walls = tuple(
        {
            "wall": index,
            "bar_indices": bar_indices,
            "a_mm": 50.0,
            "lower_bound_mm": 100.0,
            "real_wall_mm": None,
        }
        for index, bar_indices in enumerate(
            ((1, 4), (1, 2), (2, 3), (3, 4)), start=1
        )
    )
    wall_evidence = {
        "complete": True,
        "reason": None,
        "a_over_u_mm": 100.0,
        "override_mm": 0.0,
        "selected_tef_mm": 100.0,
        "selection": "A/u and reinforcement lower bound",
        "walls": walls,
    }
    tube = {"A": 0.18, "u": 1.8, "tef": 100.0, "Ak": 0.1, "uk": 1.4,
            "tef_auto": 100.0, "tef_capped": False, "tef_user": False,
            "tef_selection": "A/u and reinforcement lower bound",
            "wall_evidence": wall_evidence,
            "hollow": False, "valid": True}
    angle = shear_core.optimum_strut_angle(
        0.5236 * 416.67,
        codes.EC2_2005_DKNA.torsion_nu(35.0) * 24.14 * 100.0,
        1.0,
        2.5,
    )
    steel = torsion_core.trd_s_result(0.1, 416.67, 0.5236, angle.cot)
    strut = torsion_core.trd_max_result(
        35.0, codes.EC2_2005_DKNA, 0.1, 100.0, 1.0, angle.cot,
        fcd_mpa=24.14,
    )
    resistance = torsion_core.select_torsion_resistance(
        steel.trd_s, strut.trd_max, asw_over_s=0.5236
    )
    cracking = torsion_core.trd_c_result(1.3218, 0.1, 100.0)
    longitudinal = torsion_core.asl_required_result(
        40.0, 1.4, 0.1, 416.67, angle.cot
    )
    out = {"tube": tube, "trd_s": steel.trd_s, "trd_max": strut.trd_max,
           "trd": resistance.resistance, "trd_c": cracking.trd_c,
           "cot": angle.cot, "theta_deg": angle.theta_deg,
           "util": 40.0 / resistance.resistance,
           "asl_req": longitudinal.asl_required_mm2,
           "t_ed": 40.0, "fcd": 24.14, "fywd": 416.67, "fyd_long": 416.67,
           "nu": 0.3675, "alpha_cw": 1.0, "fctk_005": 2.247,
           "gamma_ct": 1.70, "fctd": 1.3218, "asw_t": 78.5,
           "asw_over_s": 0.5236, "dia": 10.0, "s": 150.0, "cot_min": 1.0,
           "cot_max": 2.5, "method": "DS/EN 1992-1-1:2005 + DK NA:2024",
           "governs": resistance.governs, "valid": True, "cot_limit_lo": 1.0,
           "cot_limit_hi": 2.5, "out_of_limits": False,
           "tube_valid": True, "closed_links_present": True,
           "transverse_resistance_assessed": True,
           "full_resistance_assessed": True,
           "resistance_status": "PASS",
           "assessment_status": "NOT ASSESSED", "assessment_ok": None,
           "overall_reason": "longitudinal_torsion_reinforcement_not_verified",
           "longitudinal_assessment": {
               "status": "NOT ASSESSED",
               "reason": "longitudinal_torsion_reinforcement_not_verified",
               "required_asl_mm2": longitudinal.asl_required_mm2,
               "required_by_tube_mm2": (longitudinal.asl_required_mm2,),
               "required_design_force_kn": (
                   longitudinal.asl_required_mm2 * 416.67 / 1000.0
               ),
               "provided_gross_area_mm2": 2513.274,
               "provided_design_force_kn": 1047.198,
               "provided_equivalent_area_mm2": 2513.274,
               "reference_fyd_mpa": 416.67,
               "demand_ratio": longitudinal.asl_required_mm2 / 2513.274,
               "area_sufficient": True,
               "distribution_verified": False,
               "all_perimeter_sides_verified": False,
               "bending_reserve_verified": False,
               "anchorage_verified": False,
               "tube_allocation_verified": False,
           },
           "angle_selection": asdict(angle),
           "steel_resistance": asdict(steel),
           "strut_resistance": asdict(strut),
           "resistance_selection": asdict(resistance),
           "cracking_resistance": asdict(cracking),
           "longitudinal_reinforcement": asdict(longitudinal)}
    if interaction:
        retained = combined_core.crushing_interaction_result(
            40.0, 88.7, 150.0, 650.0
        )
        out["interaction"] = dict(
            valid=True, cot=1.0, theta_deg=45.0,
            trd_max=88.7, vrd_max=650.0,
            t_ed=40.0, v_ed=150.0,
            value=retained.utilisation,
            torsion_ratio=retained.torsion_ratio,
            shear_ratio=retained.shear_ratio,
            ok=retained.ok,
        )
    return out


def test_report_includes_torsion_section():
    out = _out()
    out["torsion"] = _torsion_out()
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Torsion" in txt
    assert "6.30" in txt and "6.28" in txt          # the clause formulae
    assert "76.4" in txt                            # TRd
    assert "26.436" in txt                          # TRd,c with gamma_ct = 1.70
    assert "1.700" in txt                           # actual tensile factor provenance
    assert "fctd = fctk,0.05 /" in txt
    assert chr(0x3B8) in txt                        # theta glyph rendered
    assert "1177" in txt                            # required Asl
    assert "NOT ASSESSED" in txt                    # overall, not component PASS
    assert "All modelled passive bars" in txt
    assert "every torsion-tube side" in txt
    assert "anchorage along the member" in txt
    assert chr(0x2211) in txt                       # summation operator
    assert chr(0x00B7) in txt                       # centred multiplication/unit dot
    assert chr(0x00B0) in txt                       # degree symbol
    assert not any(
        token in txt for token in ("sqrt", "Cfrac", "Big", "sincos", "sum A", "kN.m")
    )


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_report_profiles_publish_torsion_wall_selection_evidence(profile):
    torsion = _torsion_out()
    inp = _inp()
    inp.update(torsion_on=True, shear_links=True)

    pdf = sector_report.build_report(
        {}, inp, {"torsion": torsion}, figures=False, profile=profile
    )
    text = " ".join(_pdf_text(pdf).split())

    assert "Torsion" in text and "NOT ASSESSED" in text
    assert "Torsion transverse/strut resistance" in text and "52.4 %" in text
    if profile != "Brief":
        import pypdf

        page_texts = [
            page.extract_text() or ""
            for page in pypdf.PdfReader(io.BytesIO(pdf)).pages
        ]
        wall_pages = [
            page_text
            for page_text in page_texts
            if re.search(
                r"(?m)^(?:\d+\.\d+ )?Equivalent-tube wall selection\s*$",
                page_text,
            )
            and "Base thickness" in page_text
        ]
        assert len(wall_pages) == 1
        assert "Equivalent-tube wall selection" in text
        assert "Subsection: Equivalent-tube wall selection" in text
        assert "Minimum-reinforcement screen (Formula 6.31): Quantity" not in text
        assert "Base thickness" in text and "A/u" in text
        assert "A/u and reinforcement lower bound" in text
        assert "Lower bound 2a" in text
        assert "50.0 mm" in text and "100.0 mm" in text


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_report_profiles_fail_closed_for_incomplete_torsion_wall_evidence(profile):
    torsion = _torsion_out()
    raw_reason = "torsion wall reinforcement mapping is incomplete"
    torsion.update(
        valid=False,
        tube_valid=False,
        transverse_resistance_assessed=False,
        full_resistance_assessed=False,
        resistance_status="NOT ASSESSED",
        assessment_status="NOT ASSESSED",
        reason=raw_reason,
        trd=999.123,
        util=9.99,
        asl_req=888.0,
    )
    torsion["tube"] = dict(
        torsion["tube"],
        valid=False,
        tef=0.0,
        Ak=0.0,
        uk=0.0,
        reason=raw_reason,
        wall_evidence={
            "complete": False,
            "reason": raw_reason,
            "a_over_u_mm": 100.0,
            "override_mm": 0.0,
            "selected_tef_mm": None,
            "selection": "none",
            "walls": (
                {
                    "wall": 1,
                    "bar_indices": (1, 4),
                    "a_mm": 80.0,
                    "lower_bound_mm": 160.0,
                    "real_wall_mm": None,
                },
            ),
        },
    )
    inp = _inp()
    inp.update(torsion_on=True, shear_links=True)

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, {"torsion": torsion}, figures=False, profile=profile
            )
        ).split()
    )

    assert "Torsion" in text and "NOT ASSESSED" in text
    assert "not been established for every equivalent-tube wall" in text
    if profile != "Brief":
        assert "Base thickness A/u" in text and "100.0 mm" in text
        assert "Lower bound 2a" in text and "160.0 mm" in text
    assert sector_report._fmt(999.123, 3) not in text
    assert raw_reason not in text


@pytest.mark.parametrize(
    ("profile", "status", "provided"),
    [
        ("Brief", "NOT ASSESSED", 2513.274),
        ("Standard", "NOT ASSESSED", 2513.274),
        ("Audit", "NOT ASSESSED", 2513.274),
        ("Brief", "FAIL", 1000.0),
        ("Standard", "FAIL", 1000.0),
        ("Audit", "FAIL", 1000.0),
    ],
)
def test_report_profiles_share_longitudinal_torsion_status(
    profile,
    status,
    provided,
):
    out = _out()
    t = _torsion_out()
    reason = (
        "longitudinal_torsion_reinforcement_insufficient"
        if status == "FAIL"
        else "longitudinal_torsion_reinforcement_not_verified"
    )
    t.update(
        assessment_status=status,
        assessment_ok=False if status == "FAIL" else None,
        overall_reason=reason,
    )
    t["longitudinal_assessment"].update(
        status=status,
        reason=reason,
        provided_gross_area_mm2=provided,
        provided_design_force_kn=provided * 416.67 / 1000.0,
        provided_equivalent_area_mm2=provided,
        demand_ratio=t["asl_req"] / provided,
        area_sufficient=status != "FAIL",
    )
    out["torsion"] = t
    inp = _inp()
    inp.update(torsion_on=True, shear_links=True)

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    assert "Torsion" in text
    assert status in text
    assert "1177" in text
    assert f"{provided:.0f}" in text
    assert "Required / modelled upper bound" in text or profile != "Brief"
    if status == "FAIL":
        assert "below the Formula (6.28) longitudinal torsion demand" in text
    else:
        assert "every torsion-tube side" in text
        assert "anchored along the member" in text


def test_report_withholds_full_torsion_verdict_without_current_closed_links():
    torsion = _torsion_out()
    stale_full_resistance = 999.123
    torsion.update(
        tube_valid=True,
        closed_links_present=False,
        transverse_resistance_assessed=False,
        full_resistance_assessed=False,
        assessment_reason="closed_links_not_present",
        valid=False,
        trd=stale_full_resistance,
        util=9.99,
        governs="STALE FULL RESISTANCE",
        directional_interactions={
            "vx": {
                "directional_interaction_status": "STALE DIRECTIONAL PASS",
                "directional_governing_face": "positive",
                "directional_governing_cot": 1.5,
                "util": 0.10,
                "interaction": {"value": 0.10},
                "directional_min_reinf_governing_face": "positive",
                "min_reinf": {
                    "applicable": True,
                    "status": "PASS",
                    "scope_key": "applicable_first_generation_rectangle",
                    "value": 0.52,
                    "ok": True,
                    "t_ed": 15.0,
                    "trd_c": 60.0,
                    "v_ed": 27.0,
                    "vrd_c": 100.0,
                },
            },
        },
    )
    inp = _inp()
    inp.update(
        torsion_on=True,
        shear_links=False,
        torsion_nu_v=True,
    )

    for profile in ("Brief", "Standard", "Audit"):
        text = " ".join(
            _pdf_text(
                sector_report.build_report(
                    {},
                    inp,
                    {"torsion": torsion},
                    figures=False,
                    profile=profile,
                )
            ).split()
        )

        assert "Torsion" in text
        assert "NOT ASSESSED" in text
        assert "Shared links / closed torsion stirrup present" in text
        assert "Requested" in text and "detailing allowance" in text
        assert sector_report._fmt(stale_full_resistance, 3) not in text
        assert "STALE FULL RESISTANCE" not in text
        assert "STALE DIRECTIONAL PASS" not in text
        assert "6.31" in text
        assert "low-action condition satisfied" in text.casefold()
        assert "separate link detailing" in text.casefold()
        assert "NOT RUN" in text
        if profile == "Brief":
            continue
        assert "Directional minimum-reinforcement screens" in text
        assert "approximately solid rectangular section" in text
        assert "torsion transverse/strut resistance" in text
        assert "requires current shared links / closed stirrups" in text
        assert "Concrete cap only" in text
        assert "Cracking transparency" in text
        assert "Formula (6.28) demand" in text
        assert "supports the concrete cap and reinforcement demand" in text
        assert "its utilisation require current closed links" in text
        assert "Torsion resistance from the thin-walled closed-tube" not in text
        assert "T Rd = min" not in text


def test_report_directional_vt_table_retains_actual_verdict_outside_default_range():
    out = _out()
    torsion = _torsion_out(interaction=True)
    directional = copy.deepcopy(torsion)
    directional.update(
        cot_max=3.0,
        out_of_limits=True,
        directional_governing_face="negative",
        directional_governing_cot=1.0,
        directional_min_reinf_governing_face="negative",
        min_reinf=dict(
            applicable=True, value=0.52, ok=True, t_ed=40.0,
            trd_c=100.0, v_ed=12.0, vrd_c=100.0, solid=True,
            model_2023=False,
        ),
    )
    torsion["directional_interactions"] = {
        "vx": directional,
        "vy": copy.deepcopy(directional),
    }
    out["torsion"] = torsion

    text = " ".join(_pdf_text(
        sector_report.build_report({}, _inp(), out, figures=False)
    ).split())
    for label in ("Vx+T", "Vy+T"):
        start = text.index(label)
        # The local reference, caption and repeated context precede the retained
        # row; keep the probe inside this compact interaction table.
        assert "PASS" in text[start:start + 520]
    assert "Directional minimum-reinforcement screens" in text
    assert "low-action condition satisfied" in text
    assert "Separate detailing" in text
    assert "left (-x)" in text and "bottom (-y)" in text


def test_report_compound_torsion_requires_subdivision():
    out = _out()
    t = _torsion_out()
    t["valid"] = False
    t["tube"]["valid"] = False
    t["reason"] = "compound outline requires subdivision"
    t["compound_detected"] = True
    out["torsion"] = t
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Torsion not evaluated" in txt
    assert "6.3.1(3)" in txt
    assert "Enable sub-tubes" in txt
    assert "Current shared links / closed torsion stirrups are required" not in txt


def _subtube(
    b,
    h,
    tef,
    ak,
    c,
    ted,
    trd,
    util,
    gov,
    cx=0.0,
    cy=0.0,
    *,
    bar_position_start=1,
):
    steel = torsion_core.trd_s_result(ak, 416.67, 0.5236, 1.75)
    strut = torsion_core.trd_max_result(
        35.0, codes.EC2_2005_DKNA, ak, tef, 1.0, 1.75,
        fcd_mpa=24.14,
    )
    resistance = torsion_core.select_torsion_resistance(
        steel.trd_s, strut.trd_max, asw_over_s=0.5236
    )
    a_over_u = b * h / (2.0 * (b + h))
    a = tef / 2.0
    selection = (
        "A/u and reinforcement lower bound"
        if a_over_u == pytest.approx(tef)
        else "reinforcement lower bound"
    )
    wall_evidence = {
        "complete": True,
        "a_over_u_mm": a_over_u,
        "selected_tef_mm": tef,
        "selection": selection,
        "walls": tuple(
            {
                "wall": index,
                "bar_indices": (bar_position_start + index - 1,),
                "a_mm": a,
                "lower_bound_mm": tef,
                "real_wall_mm": None,
            }
            for index in range(1, 5)
        ),
    }
    return dict(
        tube={
            "tef": tef,
            "tef_auto": a_over_u,
            "tef_selection": selection,
            "Ak": ak,
            "valid": True,
            "wall_evidence": wall_evidence,
        }, b_mm=b, h_mm=h,
        x_mm=cx, y_mm=cy, stiffness=c, t_ed=ted,
        trd=resistance.resistance, util=ted / resistance.resistance,
        governs=resistance.governs, trd_s=steel.trd_s,
        trd_max=strut.trd_max, trd_c=trd * 0.4, cot=1.75, nu=0.37,
        steel_resistance=asdict(steel), strut_resistance=asdict(strut),
        resistance_selection=asdict(resistance),
    )


def test_report_torsion_subdivided():
    out = _out()
    t = _torsion_out(interaction=True)               # subdivided run with shear links
    subs = [_subtube(300, 600, 100.0, 0.10, 0.0037, 24.6, 90.0, 24.6 / 90.0,
                     "stirrups (TRd,s)", 0.0, -100.0),
            _subtube(1000, 200, 91.0, 0.15, 0.0023, 15.4, 20.0, 15.4 / 20.0,
                     "crushing (TRd,max)", 0.0, 300.0,
                     bar_position_start=5)]
    t["subdivided"] = True
    t["subtubes"] = subs
    t["trd"] = sum(s["trd"] for s in subs)
    # P1: governing = the worst sub-tube (part 2 here), not the pooled TEd/sum(TRd).
    t["util"] = max(s["util"] for s in subs)
    t["governing_sub"] = max(range(len(subs)), key=lambda index: subs[index]["util"])
    subs[0]["asl_req"] = 850.0
    subs[1]["asl_req"] = 550.0
    t["asl_req"] = 1400.0
    t["longitudinal_assessment"].update(
        required_asl_mm2=1400.0,
        required_by_tube_mm2=(850.0, 550.0),
        required_design_force_kn=1400.0 * 416.67 / 1000.0,
        demand_ratio=1400.0 / 2513.274,
    )
    stiffness_sum = sum(s["stiffness"] for s in subs)
    t["torque_distribution"] = {
        "applied_torque": 40.0,
        "positive_stiffness_sum": stiffness_sum,
        "shares": tuple(
            {
                "index": index,
                "stiffness": sub["stiffness"],
                "fraction": sub["stiffness"] / stiffness_sum,
                "torque": sub["t_ed"],
            }
            for index, sub in enumerate(subs)
        ),
    }
    out["torsion"] = t
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Sub-tubes" in txt                        # the compound-section heading
    assert "6.3.1(3)" in txt                         # the sub-division clause
    assert "web" in txt
    assert "governing" in txt                        # P1: governing (max) utilisation
    assert "6.29" in txt                             # P2: crushing printed in sub-report
    assert "850" in txt and "550" in txt            # Formula 6.28 per sub-tube
    assert "Equivalent-tube wall selection" in txt
    assert "Base A/u" in txt
    assert "100.0 mm" in txt and "83.3 mm" in txt
    assert "A/u and reinforcement lower bound" in txt
    assert "reinforcement lower bound" in txt
    assert "Bar positions" in txt
    assert all(f"Wall {wall}\n {wall}" in txt for wall in range(1, 5))
    assert all(f"Wall {wall}\n {wall + 4}" in txt for wall in range(1, 5))


def test_report_invalid_subtube_partition_withholds_verdict():
    out = _out()
    t = _torsion_out()
    t["valid"] = False
    t["tube"]["valid"] = False
    t["reason"] = "invalid sub-tube partition: sub-rectangle 1 extends outside"
    t["subdivision_requested"] = True
    t["subdivision_valid"] = False
    t["subdivision_reason"] = "sub-rectangle 1 extends outside"
    out["torsion"] = t
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    flat = " ".join(txt.split())
    assert "Torsion not assessed" in flat
    assert "sub-tubes do not partition the concrete section" in flat
    assert "gaps, overlaps or boundary crossings" in flat
    assert "Torsion resistance and dependent interaction" in flat
    assert "checks are not calculated" in flat


def test_report_torsion_shows_combined_interaction():
    out = _out()
    out["torsion"] = _torsion_out(interaction=True)
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "6.29" in txt                            # the combined crushing clause
    assert "Combined shear" in txt


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_report_torsion_shows_min_reinf_screen(profile):
    # F7: the 6.31 minimum-reinforcement screen appears when applicable.
    out = _out()
    t = _torsion_out()
    t["min_reinf"] = dict(
        applicable=True,
        status="PASS",
        scope_key="applicable_first_generation_rectangle",
        value=0.52,
        ok=True,
        t_ed=40.0,
        trd_c=100.0,
        v_ed=30.0,
        vrd_c=250.0,
        torsion_ratio=0.4,
        shear_ratio=0.12,
        governs="torsion",
        solid=True,
        model_2023=False,
        detailing_status="PASS",
        detailing_scope_key="separate_detailing_passed",
    )
    out["torsion"] = t
    inp = _inp()
    inp.update(torsion_on=True, shear_on=True)
    txt = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )
    assert "6.31" in txt                            # the screen clause
    assert "low-action condition satisfied" in txt.casefold()
    assert "separate link detailing" in txt.casefold()
    assert "PASS" in txt
    assert "approximately solid rectangular section" in txt


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
@pytest.mark.parametrize(
    ("condition_status", "value", "condition_text"),
    (
        ("PASS", 0.80, "low-action condition satisfied"),
        ("FAIL", 1.20, "low-action condition not satisfied"),
    ),
)
@pytest.mark.parametrize(
    ("detailing_status", "detailing_scope_key", "detailing_text"),
    (
        ("PASS", "separate_detailing_passed", "minimum ratio and spacing"),
        ("FAIL", "separate_detailing_failed", "checks fail"),
        ("NOT RUN", "separate_detailing_not_run", "was not selected"),
    ),
)
def test_report_profiles_separate_formula_631_condition_from_detailing(
    profile,
    condition_status,
    value,
    condition_text,
    detailing_status,
    detailing_scope_key,
    detailing_text,
):
    out = _out()
    torsion = _torsion_out()
    torsion["min_reinf"] = dict(
        applicable=True,
        status=condition_status,
        scope_key="applicable_first_generation_rectangle",
        value=value,
        ok=condition_status == "PASS",
        t_ed=40.0,
        trd_c=100.0,
        v_ed=30.0,
        vrd_c=75.0 if condition_status == "FAIL" else 250.0,
        torsion_ratio=0.4,
        shear_ratio=value - 0.4,
        governs="torsion" if condition_status == "PASS" else "shear",
        solid=True,
        model_2023=False,
        detailing_status=detailing_status,
        detailing_scope_key=detailing_scope_key,
    )
    out["torsion"] = torsion
    inp = _inp()
    inp.update(torsion_on=True, shear_on=True)

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    assert condition_text in text.casefold()
    assert "separate link detailing" in text.casefold()
    assert re.search(
        r"separate link detailing.{0,240}\b"
        + re.escape(detailing_status.casefold())
        + r"\b",
        text.casefold(),
    )
    assert detailing_text in text
    assert "minimum reinforcement suffices" not in text.casefold()
    assert "minimum sufficient" not in text.casefold()


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_report_profiles_use_selected_2023_scope_when_shear_is_disabled(profile):
    out = _out()
    torsion = _torsion_out()
    torsion["min_reinf"] = dict(
        applicable=False,
        status="NOT APPLICABLE",
        scope_key="selected_2023_route",
        value=None,
        ok=None,
        t_ed=15.0,
        trd_c=26.435,
        v_ed=None,
        vrd_c=None,
        torsion_ratio=None,
        shear_ratio=None,
        governs=None,
        solid=True,
        model_2023=True,
        shear_method=codes.EC2_2023.label,
        torsion_method=codes.EC2_2005_DKNA.label,
        detailing_status="NOT RUN",
        detailing_scope_key="separate_detailing_not_run",
    )
    out["torsion"] = torsion
    inp = _inp()
    inp.update(
        torsion_on=True,
        shear_on=False,
        shear_method=codes.EC2_2023.label,
        torsion_method=codes.EC2_2005_DKNA.label,
    )

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    assert "unavailable for the selected 2023 shear method" in text
    assert "Assess shear using the 2023 check" in text
    assert "assess torsion and interaction using their selected methods" in text
    assert "reported 2023 shear check" not in text
    assert "2023 shear-and-torsion" not in text
    assert "Calculate the first-generation V_Rd,c" not in text
    assert "low-action condition satisfied" not in text.casefold()


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
@pytest.mark.parametrize(
    ("n_ed", "mx_ed", "my_ed", "applicable"),
    (
        (0.0, 0.0, 0.0, True),
        (-20.0, 0.0, 0.0, False),
        (20.0, 0.0, 0.0, False),
        (0.0, -15.0, 0.0, False),
        (0.0, 15.0, 0.0, False),
        (0.0, 0.0, -10.0, False),
        (0.0, 0.0, 10.0, False),
    ),
)
def test_report_profiles_retain_dkna_formula_631_normal_and_moment_scope(
    profile,
    n_ed,
    mx_ed,
    my_ed,
    applicable,
):
    out = _out()
    torsion = _torsion_out()
    torsion["min_reinf"] = dict(
        applicable=applicable,
        status="PASS" if applicable else "NOT APPLICABLE",
        scope_key=(
            "applicable_first_generation_rectangle"
            if applicable else "dkna_combined_normal_or_moment"
        ),
        value=0.65 if applicable else None,
        ok=True if applicable else None,
        t_ed=15.0,
        trd_c=50.0,
        v_ed=35.0,
        vrd_c=100.0,
        torsion_ratio=0.3 if applicable else None,
        shear_ratio=0.35 if applicable else None,
        governs="shear" if applicable else None,
        solid=True,
        model_2023=False,
        dk_na=True,
        shear_method=codes.EC2_2005_DKNA.label,
        torsion_method=codes.EC2_2005_DKNA.label,
        n_ed=n_ed,
        mx_ed=mx_ed,
        my_ed=my_ed,
        normal_or_moment_active=not applicable,
        detailing_status="NOT RUN",
        detailing_scope_key="separate_detailing_not_run",
    )
    out["torsion"] = torsion
    inp = _inp()
    inp.update(
        torsion_on=True,
        shear_on=True,
        shear_method=codes.EC2_2005_DKNA.label,
        torsion_method=codes.EC2_2005_DKNA.label,
        P_pl=n_ed,
        Mx_pl=mx_ed,
        My_pl=my_ed,
    )

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    if applicable:
        assert "low-action condition satisfied" in text.casefold()
    else:
        assert "With acting N_Ed or M_Ed under the Danish National Annex" in text
        assert "DK NA 6.3.2(6) combined N-M-V-T check" in text
        assert "low-action condition satisfied" not in text.casefold()


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
@pytest.mark.parametrize(
    ("scope_context", "scope_overrides"),
    (
        ("nonrectangular", {"solid_rectangle": False}),
        ("hollow", {"solid_rectangle": False}),
        (
            "subdivided",
            {"solid_rectangle": False, "subdivided": True},
        ),
        (
            "unavailable-shear",
            {"shear_available": False, "v_ed": None, "vrd_c": None},
        ),
        (
            "selected-2023",
            {
                "model_2023": True,
                "shear_method": codes.EC2_2023.label,
                "torsion_method": codes.EC2_2005_DKNA.label,
            },
        ),
    ),
    ids=lambda value: value if isinstance(value, str) else None,
)
@pytest.mark.parametrize(
    ("action", "value"),
    (
        ("n_ed", -20.0),
        ("n_ed", 20.0),
        ("mx_ed", -15.0),
        ("mx_ed", 15.0),
        ("my_ed", -10.0),
        ("my_ed", 10.0),
    ),
)
def test_report_profiles_keep_dkna_requirement_across_other_631_scope_limits(
    profile,
    scope_context,
    scope_overrides,
    action,
    value,
):
    inputs = dict(
        t_ed=15.0,
        trd_c=60.0,
        v_ed=30.0,
        vrd_c=120.0,
        solid_rectangle=True,
        subdivided=False,
        model_2023=False,
        shear_available=True,
        dk_na=True,
        shear_method=codes.EC2_2005_DKNA.label,
        torsion_method=codes.EC2_2005_DKNA.label,
        n_ed=0.0,
        mx_ed=0.0,
        my_ed=0.0,
    )
    inputs.update(scope_overrides)
    inputs[action] = value
    minimum = asdict(
        combined_core.minimum_reinforcement_screen_result(**inputs)
    )
    out = _out()
    torsion = _torsion_out()
    torsion["min_reinf"] = minimum
    out["torsion"] = torsion
    inp = _inp()
    inp.update(
        torsion_on=True,
        shear_on=inputs["shear_available"],
        shear_method=inputs["shear_method"],
        torsion_method=inputs["torsion_method"],
        P_pl=inputs["n_ed"],
        Mx_pl=inputs["mx_ed"],
        My_pl=inputs["my_ed"],
    )

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    assert minimum["status"] == "NOT APPLICABLE"
    assert minimum["scope_key"] == "dkna_combined_normal_or_moment"
    assert scope_context in {
        "nonrectangular", "hollow", "subdivided", "unavailable-shear",
        "selected-2023",
    }
    if scope_context == "selected-2023":
        assert minimum["model_2023"] is True
        assert minimum["shear_method"] == codes.EC2_2023.label
        assert minimum["torsion_method"] == codes.EC2_2005_DKNA.label
    assert "With acting N_Ed or M_Ed under the Danish National Annex" in text
    assert "DK NA 6.3.2(6) combined N-M-V-T check" in text
    assert "low-action condition satisfied" not in text.casefold()


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
@pytest.mark.parametrize(
    ("status", "reason", "note"),
    (
        (
            "NOT APPLICABLE",
            "section_geometry",
            "For this section geometry",
        ),
        (
            "NOT APPLICABLE",
            "subdivided_section",
            "For a subdivided compound section",
        ),
        (
            "NOT APPLICABLE",
            "selected_2023_route",
            "unavailable for the selected 2023 shear method",
        ),
        (
            "NOT ASSESSED",
            "shear_resistance_unavailable",
            "Calculate the first-generation V_Rd,c shear result",
        ),
    ),
)
def test_report_profiles_publish_formula_631_scope_without_false_sufficiency(
    profile,
    status,
    reason,
    note,
):
    out = _out()
    t = _torsion_out()
    t["min_reinf"] = dict(
        applicable=False,
        status=status,
        scope_key=reason,
        value=None,
        ok=None,
        t_ed=40.0,
        trd_c=26.435,
        v_ed=30.0 if reason != "shear_resistance_unavailable" else None,
        vrd_c=136.0 if reason != "shear_resistance_unavailable" else None,
        torsion_ratio=None,
        shear_ratio=None,
        governs=None,
        solid=False,
        model_2023=reason == "selected_2023_route",
    )
    out["torsion"] = t
    inp = _inp()
    inp.update(torsion_on=True, shear_on=True)
    if reason == "selected_2023_route":
        t["min_reinf"].update(
            shear_method=codes.EC2_2023.label,
            torsion_method=codes.EC2_2005_DKNA.label,
        )
        inp.update(
            shear_method=codes.EC2_2023.label,
            torsion_method=codes.EC2_2005_DKNA.label,
        )

    txt = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    assert "6.31" in txt
    assert "minimum-reinforcement screen" in txt.casefold()
    assert status in txt
    assert note in txt
    assert "low-action condition satisfied" not in txt.casefold()
    if reason == "selected_2023_route":
        assert "Assess shear using the 2023 check" in txt
        assert "assess torsion and interaction using their selected methods" in txt
        assert "reported 2023 shear check" not in txt
        assert "2023 shear-and-torsion" not in txt


def _combined_out(mv_independent=False):
    dkna = combined_core.dkna_interaction_result(
        0.0, None,
        60.0, 100.0,
        40.0, 100.0,
        30.0, 100.0,
        m_v_independent=mv_independent,
    )
    crushing = combined_core.crushing_interaction_result(
        40.0, 88.7, 150.0, 650.0
    )
    action_alone = {
        "n": {
            "symbol": "N", "demand": 0.0, "resistance": None,
            "valid": True, "source_clause": "DS/EN 1992-1-1 DK NA:2024, 6.3.2(6)",
        },
        "m": {
            "symbol": "M", "demand": 60.0, "resistance": 100.0,
            "valid": True, "source_clause": "DS/EN 1992-1-1 DK NA:2024, 6.3.2(6)",
        },
        "v": {
            "symbol": "V", "demand": 40.0, "resistance": 100.0,
            "valid": True, "source_clause": "DS/EN 1992-1-1 DK NA:2024, 6.3.2(6)",
        },
        "t": {
            "symbol": "T", "demand": 30.0, "resistance": 100.0,
            "valid": True, "source_clause": "DS/EN 1992-1-1 DK NA:2024, 6.3.2(6)",
        },
    }
    return {
        "valid": True, "method": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "r_n": 0.0, "r_m": 0.6, "r_v": 0.4, "r_t": 0.3,
        "m_v_independent": mv_independent,
        "dkna_sum": dkna.utilisation, "dkna_valid": dkna.valid,
        "dkna_conditional": dkna.conditional,
        "dkna_limit_satisfied": dkna.limit_satisfied,
        "dkna_status": dkna.status,
        "dkna_ok": dkna.ok,
        "dkna_selection": asdict(dkna),
        "m_v_separation_condition": {
            "declared": mv_independent,
            "mechanically_verified": False,
            "verification_state": (
                "design assumption" if mv_independent else "not selected"
            ),
        },
        "action_alone": action_alone,
        "crushing": dict(
            valid=True, cot=1.0, theta_deg=45.0,
            trd_max=88.7, vrd_max=650.0, t_ed=40.0, v_ed=150.0,
            value=crushing.utilisation,
            torsion_ratio=crushing.torsion_ratio,
            shear_ratio=crushing.shear_ratio,
            ok=crushing.ok,
        ),
        "asl_torsion": 1176.0, "delta_ftd": 200.0, "links": True,
    }


def _base_en_combined_out():
    combined = _combined_out()
    for key in (
        "r_n", "r_m", "r_v", "r_t", "m_v_independent", "dkna_sum",
        "dkna_valid", "dkna_conditional", "dkna_limit_satisfied",
        "dkna_status", "dkna_ok", "dkna_selection",
        "m_v_separation_condition", "action_alone",
    ):
        combined.pop(key, None)
    combined["method"] = codes.EC2_2005.label
    combined["transverse"] = {
        "valid": True,
        "cot": 1.5,
        "u_stirrup": 0.58,
        "u_crush": 0.72,
        "shear_fraction": 0.28,
        "torsion_fraction": 0.30,
    }
    chord = {
        "valid": True,
        "axis": "x",
        "tension_low": True,
        "m_ed": 60.0,
        "mv": 20.0,
        "mt": 10.0,
        "m_total": 90.0,
        "m_rd": 150.0,
        "util": 0.60,
        "ok": True,
        "conditional": True,
    }
    combined["longitudinal"] = chord
    combined["longitudinal_assessment"] = {
        "status": "PASS",
        "util": 0.60,
        "coverage_complete": True,
        "governing": "x-axis negative face",
        "reason": "Complete longitudinal chord coverage",
    }
    _retain_combined_chords(combined, chord)
    return combined


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_report_base_en_publishes_physical_checks_without_dkna_artifacts(profile):
    inp = _inp()
    inp.update(
        mode="Plastic",
        combined_on=True,
        combined_method=codes.EC2_2005.label,
        combined_mv_independent=True,
        shear_on=True,
        torsion_on=True,
    )
    out = {"plastic": _out()["plastic"], "combined": _base_en_combined_out()}
    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    folded = text.casefold()
    assert "concrete compression strut" in folded
    assert "closed stirrup" in folded
    assert "longitudinal reinforcement" in folded
    assert "DK NA" not in text
    assert "action-alone" not in text
    assert "DK NA sum" not in text
    assert "N+M+V+T" not in text
    assert "max(N+M+T, N+V+T)" not in text
    assert "Separate M/V route selected as a design assumption" not in text
    if profile in {"Standard", "Audit"}:
        assert "Supported Base-EN physical interactions" in text
        assert "Concrete compression strut (6.29)" in text
        assert "Shared closed stirrup: shear + torsion" in text


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_report_base_en_keeps_biaxial_directions_without_dkna_aggregate(profile):
    inp = _inp()
    inp.update(
        mode="Plastic",
        combined_on=True,
        combined_method=codes.EC2_2005.label,
        combined_mv_independent=True,
        shear_on=True,
        torsion_on=True,
    )
    vx = _base_en_combined_out()
    vy = copy.deepcopy(vx)
    vx.update(component="vx", governing_face="negative", governing_cot=1.25)
    vy.update(component="vy", governing_face="positive", governing_cot=1.75)
    out = {
        "plastic": _out()["plastic"],
        "combined": {
            "method": codes.EC2_2005.label,
            "biaxial": True,
            "directions": {"vx": vx, "vy": vy},
        },
    }
    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    assert "Vx+T" in text
    assert "Vy+T" in text
    assert "DK NA" not in text
    assert "DK NA sum" not in text
    assert "N+M+V+T" not in text
    if profile in {"Standard", "Audit"}:
        assert "Representative Base-EN directional calculation" in text
        assert "No simultaneous Vx + Vy + T verdict is inferred" in text


@pytest.mark.parametrize("profile", ["Standard", "Audit"])
def test_report_base_en_keeps_only_the_governing_combined_worked_case(profile):
    inp = _inp()
    inp.update(
        mode="Plastic",
        combined_on=True,
        combined_method=codes.EC2_2005.label,
        shear_on=True,
        torsion_on=True,
    )
    actions = [
        {
            "name": "PL-LOW", "description": "Lower combined utilisation",
            "n_ed_kn": 0.0, "mx_ed_knm": 40.0, "my_ed_knm": 0.0,
            "vx_ed_kn": 20.0, "vy_ed_kn": 0.0,
            "vx_face": "auto", "vy_face": "auto", "t_ed_knm": 10.0,
        },
        {
            "name": "PL-GOV", "description": "Governing combined utilisation",
            "n_ed_kn": 0.0, "mx_ed_knm": 100.0, "my_ed_knm": 0.0,
            "vx_ed_kn": 80.0, "vy_ed_kn": 0.0,
            "vx_face": "auto", "vy_face": "auto", "t_ed_knm": 40.0,
        },
    ]
    inp["plastic_cases"] = actions

    def combined_case(util):
        result = _base_en_combined_out()
        result["transverse"].update(
            u_crush=util,
            u_stirrup=util - 0.05,
            shear_fraction=util - 0.25,
            torsion_fraction=0.20,
        )
        result["longitudinal"].update(util=util - 0.10, ok=True)
        result["longitudinal_assessment"].update(
            status="PASS",
            util=util - 0.10,
        )
        result["governing_longitudinal"] = result["longitudinal"]
        result["longitudinal_candidates"] = [result["longitudinal"]]
        return result

    low = combined_case(0.40)
    governing = combined_case(0.85)
    out = {
        "plastic_cases": [
            {
                "name": actions[0]["name"],
                "actions": actions[0],
                "evaluated": True,
                "results": {
                    "plastic": copy.deepcopy(_out()["plastic"]),
                    "combined": low,
                },
            },
            {
                "name": actions[1]["name"],
                "actions": actions[1],
                "evaluated": True,
                "results": {
                    "plastic": copy.deepcopy(_out()["plastic"]),
                    "combined": governing,
                },
            },
        ],
    }
    out["worked_example_selection"] = (
        result_presentation.worked_example_selection(inp, out)
    )

    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, inp, out, figures=False, profile=profile
    )
    assert builder._needs_diagnostic_chapter("combined", low) is False
    incomplete = dict(low, valid=False, reason="missing combined prerequisite")
    assert builder._needs_diagnostic_chapter("combined", incomplete) is True

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )
    assert "Combined bending + shear + torsion (M-V-T) - PL-LOW" not in text
    assert "Combined bending + shear + torsion (M-V-T) - PL-GOV" in text
    assert "The complete combined M-V-T worked example is published only" not in text
    assert "DK NA sum" not in text


def _retain_combined_chords(payload, *candidates):
    retained = [item for item in candidates if item is not None]
    payload["longitudinal_candidates"] = retained
    payload["governing_longitudinal"] = (
        max(retained, key=lambda item: item["util"])
        if retained else None
    )
    payload["longitudinal_fallback"] = next(
        (item for item in retained if not item.get("conditional", True)),
        None,
    )
    payload["longitudinal_all_conditional"] = bool(retained) and (
        payload["longitudinal_fallback"] is None
    )
    return payload


@pytest.mark.parametrize("profile", ("Standard", "Audit"))
def test_report_combined_zero_2023_chord_candidates_stays_not_assessed(
    profile,
):
    inp = _inp()
    inp.update(combined_on=True, shear_on=True, torsion_on=True)
    out = _out()
    combined_result = _combined_out()
    combined_result.update(
        longitudinal_model_2023=True,
        longitudinal_assessment={
            "status": "NOT ASSESSED",
            "ok": None,
            "util": None,
            "reason": "required_longitudinal_chord_coverage_incomplete",
            "coverage_complete": False,
            "governing": None,
        },
    )
    out["combined"] = combined_result

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {},
                inp,
                out,
                figures=False,
                profile=profile,
            )
        ).split()
    )

    assert "Required 2023 longitudinal chord faces" in text
    assert "Longitudinal chord assessment: NOT ASSESSED" in text
    assert "Complete both required longitudinal chord checks" in text
    assert "Enable shear links for the full utilisation check" not in text
    assert "both beyond the bending steel" not in text
    assert "SHEAR-LONGITUDINAL" not in text


def test_report_publishes_only_governing_transverse_family_worked_examples():
    inp = _inp()
    rows = [
        {
            "name": "PL-LOW", "description": "Lower transverse actions",
            "n_ed_kn": 0.0, "mx_ed_knm": 40.0, "my_ed_knm": 0.0,
            "vx_ed_kn": 20.0, "vy_ed_kn": 30.0,
            "vx_face": "auto", "vy_face": "auto", "t_ed_knm": 20.0,
        },
        {
            "name": "PL-GOV", "description": "Governing transverse actions",
            "n_ed_kn": 0.0, "mx_ed_knm": 100.0, "my_ed_knm": 30.0,
            "vx_ed_kn": 45.0, "vy_ed_kn": 80.0,
            "vx_face": "auto", "vy_face": "auto", "t_ed_knm": 40.0,
        },
    ]
    inp["plastic_cases"] = rows

    shear_low = _shear_out()
    shear_low.update(v_ed=30.0, signed_v_ed=30.0,
                     util=30.0 / shear_low["res"]["vrd_c"])
    vx = copy.deepcopy(_shear_out())
    vx.update(component="vx", axis="y", signed_v_ed=45.0, v_ed=45.0,
              util=45.0 / vx["res"]["vrd_c"], status="PASS")
    vy = copy.deepcopy(_shear_out())
    vy.update(component="vy", axis="x", signed_v_ed=80.0, v_ed=80.0,
              util=80.0 / vy["res"]["vrd_c"], status="PASS")
    shear_governing = dict(
        vy, directions={"vx": vx, "vy": vy}, biaxial=True,
        active_directions=["vx", "vy"],
    )

    torsion_low = _torsion_out()
    torsion_low.update(t_ed=20.0, util=20.0 / torsion_low["trd"])
    torsion_governing = _torsion_out()

    def combined_with(r_m, r_v, r_t, component):
        item = _combined_out()
        selection = combined_core.dkna_interaction_result(
            0.0, None,
            r_m, 1.0,
            r_v, 1.0,
            r_t, 1.0,
            m_v_independent=False,
        )
        item.update(
            component=component,
            r_m=r_m, r_v=r_v, r_t=r_t,
            dkna_sum=selection.utilisation,
            dkna_ok=selection.ok,
            dkna_selection=asdict(selection),
            governing_face="negative" if component == "vx" else "positive",
            governing_cot=1.25 if component == "vx" else 1.75,
        )
        return item

    combined_low = combined_with(0.10, 0.10, 0.10, "vy")
    combined_vx = combined_with(0.15, 0.15, 0.10, "vx")
    combined_vy = combined_with(0.60, 0.40, 0.30, "vy")
    combined_governing = dict(
        combined_vy,
        directions={"vx": combined_vx, "vy": combined_vy},
        biaxial=True,
    )

    out = {
        "plastic_cases": [
            {
                "name": rows[0]["name"], "actions": rows[0], "evaluated": True,
                "results": {
                    "shear": shear_low,
                    "torsion": torsion_low,
                    "combined": combined_low,
                },
            },
            {
                "name": rows[1]["name"], "actions": rows[1], "evaluated": True,
                "results": {
                    "shear": shear_governing,
                    "torsion": torsion_governing,
                    "combined": combined_governing,
                },
            },
        ]
    }

    flat = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, out, figures=False, qa_appendix=False,
    )).split())

    assert "PL-LOW" in flat and "PL-GOV" in flat
    assert "Shear resistance - PL-LOW" not in flat
    assert "Torsion (thin-walled tube) - PL-LOW" not in flat
    assert "Combined bending + shear + torsion (M-V-T) - PL-LOW" not in flat
    assert "EQ-SHEAR.2005.VRDC" not in flat
    assert "EQ-TORSION.RESISTANCE.GOVERNING" not in flat
    assert "EQ-COMBINED.DK-NA.SUM" not in flat
    assert flat.count("The complete shear worked example is published only") == 1
    assert flat.count("The complete torsion worked example is published only") == 1
    assert flat.count("complete combined M-V-T worked example is published only") == 1
    assert "Vx+T" in flat and "Vy+T" in flat


def test_transverse_worked_selector_uses_only_valid_applicable_final_checks():
    inp = _inp()
    actions = [
        {
            "name": "PL-A", "description": "First",
            "n_ed_kn": 0.0, "mx_ed_knm": 0.0, "my_ed_knm": 0.0,
            "vx_ed_kn": 1.0, "vy_ed_kn": 0.0,
            "vx_face": "auto", "vy_face": "auto", "t_ed_knm": 1.0,
        },
        {
            "name": "PL-B", "description": "Second",
            "n_ed_kn": 0.0, "mx_ed_knm": 0.0, "my_ed_knm": 0.0,
            "vx_ed_kn": 2.0, "vy_ed_kn": 0.0,
            "vx_face": "auto", "vy_face": "auto", "t_ed_knm": 2.0,
        },
        {
            "name": "PL-INVALID", "description": "Invalid",
            "n_ed_kn": 0.0, "mx_ed_knm": 0.0, "my_ed_knm": 0.0,
            "vx_ed_kn": 3.0, "vy_ed_kn": 0.0,
            "vx_face": "auto", "vy_face": "auto", "t_ed_knm": 3.0,
        },
    ]
    inp["plastic_cases"] = actions

    first = {
        "shear": {
            "res": {"valid": True}, "util": 0.99,
            "links": {"res": {"valid": True}, "util": 0.40},
        },
        "torsion": {
            "valid": True, "util": 0.40,
            "min_reinf": {"applicable": True, "value": 9.0},
            "interaction": {"valid": True, "value": 8.0},
        },
        "combined": {
            "valid": True, "dkna_sum": 0.60,
            "crushing": {"valid": True, "value": 7.0},
        },
    }
    second = {
        "shear": {
            "res": {"valid": True}, "util": 0.85,
            "links": {"res": {"valid": True}, "util": 0.80},
        },
        "torsion": {"valid": True, "util": 0.75},
        "combined": {"valid": True, "dkna_sum": 0.90},
    }
    invalid = {
        "shear": {
            "res": {"valid": False}, "util": math.inf,
            "links": {"res": {"valid": False}, "util": math.inf},
        },
        "torsion": {"valid": False, "util": math.inf},
        "combined": {"valid": False, "dkna_sum": math.inf},
    }
    out = {
        "plastic_cases": [
            {"actions": actions[0], "results": first, "evaluated": True},
            {"actions": actions[1], "results": second, "evaluated": True},
            {"actions": actions[2], "results": invalid, "evaluated": True},
        ]
    }

    selected = result_presentation.worked_example_selection(inp, out)

    assert selected["families"]["shear"]["case_id"] == "PL-B"
    assert selected["families"]["torsion"]["case_id"] == "PL-B"
    assert selected["families"]["combined"]["case_id"] == "PL-B"
    assert selected["torsion_subchecks"]["interaction"]["case_id"] == "PL-A"
    assert selected["torsion_subchecks"]["minimum_reinforcement"][
        "case_id"
    ] == "PL-A"


def test_report_includes_combined_section():
    out = _out()
    out["combined"] = _combined_out()
    inp = _inp()
    inp.update(strut_cot_min=1.0, strut_cot_max=2.5)
    txt = _pdf_text(sector_report.build_report({}, inp, out, figures=False))
    flat = " ".join(txt.split())
    assert "Combined bending" in txt or "M-V-T" in txt
    assert "6.3.2(6)" in txt                        # the DK NA combined rule
    assert "FAIL" in txt                            # sum 1.3 > 1
    assert "Axial N" in txt
    assert "action acting alone" in flat
    assert "entered biaxial moment direction" in flat
    assert "does not replace a separate member and detailing assessment" in flat
    assert "Annex F" in flat
    assert "DS/EN 1992-1-1 DK NA:2024, 6.3.2(6)" in flat
    assert (
        "Source / method note: DS/EN 1992-1-1 DK NA:2024, 6.3.2(6)"
        in flat
    )
    assert "Shared compression-strut cot " + chr(0x03B8) + "min" in txt
    assert "Shared compression-strut cot " + chr(0x03B8) + "max" in txt


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_report_profiles_share_dkna_value_and_status(profile):
    out = _out()
    out["combined"] = _combined_out()
    inp = _inp()
    inp.update(combined_on=True, shear_on=True, torsion_on=True)
    txt = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )
    assert "Combined M-V-T" in txt
    assert "DK NA sum" in txt
    assert "130.0 %" in txt
    assert "FAIL" in txt
    if profile != "Brief":
        assert "Axial N" in txt
        assert "6.3.2(6)" in txt
        assert "entered biaxial moment direction" in txt


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
@pytest.mark.parametrize("torsion_status", ["NOT ASSESSED", "FAIL"])
def test_report_combined_status_retains_longitudinal_torsion_gate(
    profile,
    torsion_status,
):
    out = _out()
    torsion = _torsion_out()
    reason = (
        "longitudinal_torsion_reinforcement_insufficient"
        if torsion_status == "FAIL"
        else "longitudinal_torsion_reinforcement_not_verified"
    )
    torsion.update(
        assessment_status=torsion_status,
        overall_reason=reason,
    )
    torsion["longitudinal_assessment"].update(
        status=torsion_status,
        reason=reason,
    )
    out["torsion"] = torsion

    selection = combined_core.dkna_interaction_result(
        0.0,
        None,
        0.2,
        1.0,
        0.2,
        1.0,
        0.2,
        1.0,
        m_v_independent=False,
    )
    combined = _combined_out()
    combined.update(
        r_m=0.2,
        r_v=0.2,
        r_t=0.2,
        dkna_sum=selection.utilisation,
        dkna_valid=selection.valid,
        dkna_limit_satisfied=selection.limit_satisfied,
        dkna_status=selection.status,
        dkna_ok=selection.ok,
        dkna_selection=asdict(selection),
        assessment_status=torsion_status,
        torsion_assessment_status=torsion_status,
        torsion_assessment_reason=reason,
        torsion_longitudinal_assessment=torsion[
            "longitudinal_assessment"
        ],
    )
    out["combined"] = combined
    inp = _inp()
    inp.update(
        combined_on=True,
        shear_on=True,
        torsion_on=True,
        shear_links=True,
    )

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    assert torsion_status in text
    assert "60.0 %" in text
    assert "numerical component evidence" in text
    assert "not an overall M-V-T verdict" in text
    assert f"Overall {torsion_status}: {torsion_status}" not in text


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_report_definite_dkna_failure_outranks_unverified_torsion(profile):
    out = _out()
    torsion = _torsion_out()
    out["torsion"] = torsion
    combined = _combined_out(mv_independent=True)
    combined.update(
        dkna_sum=1.10,
        dkna_limit_satisfied=False,
        dkna_status="FAIL",
        dkna_ok=False,
        torsion_assessment_status="NOT ASSESSED",
        torsion_assessment_reason=(
            "longitudinal_torsion_reinforcement_not_verified"
        ),
        torsion_longitudinal_assessment=torsion[
            "longitudinal_assessment"
        ],
    )
    combined["dkna_selection"].update(
        utilisation=1.10,
        limit_satisfied=False,
        status="FAIL",
        ok=False,
    )
    out["combined"] = combined
    inp = _inp()
    inp.update(
        combined_on=True,
        combined_mv_independent=True,
        shear_on=True,
        torsion_on=True,
        shear_links=True,
    )

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    assert "FAIL" in text
    assert "definite combined failure governs" in text
    assert "not an overall M-V-T verdict" not in text


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_report_profiles_label_independent_dkna_route_truthfully(profile):
    out = _out()
    out["combined"] = _combined_out(mv_independent=True)
    inp = _inp()
    inp.update(combined_on=True, shear_on=True, torsion_on=True)
    txt = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )
    assert "max(N+M+T, N+V+T)" in txt
    assert "CONDITIONAL" in txt
    assert "design assumption" in txt
    assert "area, distribution and anchorage" in txt
    assert "reinforcement is confirmed" not in txt
    assert "N+M+V+T" not in txt


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_report_separate_mv_over_limit_fails_even_under_assumption(profile):
    inp = _inp()
    inp.update(
        mode="Plastic",
        combined_on=True,
        combined_mv_independent=True,
    )
    base_out = _out()
    out = {"plastic": base_out["plastic"]}
    combined = _combined_out(mv_independent=True)
    combined.update(
        dkna_sum=1.30,
        dkna_limit_satisfied=False,
        dkna_status="FAIL",
        dkna_ok=False,
    )
    combined["dkna_selection"].update(
        utilisation=1.30,
        limit_satisfied=False,
        status="FAIL",
        ok=False,
    )
    out["combined"] = combined
    txt = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    assert re.search(
        r"Combined M-V-T - DK NA sum PL-TEST FAIL 130\.0 %",
        txt,
    )
    assert "exceeds the numerical limit even under the favourable" in txt
    assert "failed numerical check governs regardless" in txt


def test_report_biaxial_shear_torsion_has_two_screens_and_no_three_way_verdict():
    out = _out()
    vx = _combined_out(mv_independent=True)
    vy = copy.deepcopy(vx)
    vx.update(
        component="vx", dkna_sum=0.70, dkna_ok=True,
        governing_face="negative", governing_cot=1.25,
    )
    vy.update(
        component="vy", r_v=0.75, dkna_sum=1.05,
        dkna_limit_satisfied=False, dkna_status="FAIL", dkna_ok=False,
        governing_face="positive", governing_cot=1.75,
    )
    out["combined"] = dict(
        vx,
        directions={"vx": vx, "vy": vy},
        biaxial=True,
    )

    txt = " ".join(_pdf_text(
        sector_report.build_report({}, _inp(), out, figures=False)
    ).split())

    assert "are assessed separately" in txt
    assert "simultaneous" in txt
    assert "check is not included" in txt
    assert "requires a separate member check" in txt
    assert "CONDITIONAL" in txt
    assert "105.0 %" in txt and "FAIL" in txt
    assert "Governing face" in txt
    assert "left (-x)" in txt and "top (+y)" in txt
    assert "1.250" in txt and "1.750" in txt


def test_report_dkna_independent_route_keeps_n_and_t_in_both_branches():
    out = _out()
    out["combined"] = _combined_out(mv_independent=True)
    txt = " ".join(
        _pdf_text(
            sector_report.build_report({}, _inp(), out, figures=False)
        ).split()
    )
    assert "rN + rM + rT" in txt
    assert "rN + rV + rT" in txt
    assert "N and T remain in both independent checks" in txt
    assert "CONDITIONAL" in txt
    assert "Verify the reinforcement area, distribution and anchorage" in txt


def test_report_unavailable_action_alone_resistance_is_not_assessed():
    out = _out()
    combined = _combined_out()
    selection = combined_core.dkna_interaction_result(
        0.0,
        None,
        60.0,
        None,
        40.0,
        100.0,
        30.0,
        100.0,
        m_v_independent=False,
    )
    combined.update(
        r_m=None,
        dkna_sum=None,
        dkna_valid=False,
        dkna_ok=None,
        dkna_reason=selection.reason,
        dkna_selection=asdict(selection),
    )
    combined["action_alone"]["m"].update(
        resistance=None,
        valid=False,
        reason=(
            "An action-alone resistance could not be determined. Check the "
            "section, materials and complete Plastic bending sweep."
        ),
    )
    out["combined"] = combined
    txt = " ".join(
        _pdf_text(
            sector_report.build_report({}, _inp(), out, figures=False)
        ).split()
    )
    assert "DK NA interaction: NOT ASSESSED" in txt
    assert "No PASS or FAIL verdict is given" in txt
    assert "complete Plastic bending sweep" in txt


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_report_unassessed_combined_retains_selected_separate_route(profile):
    inp = _inp()
    inp.update(
        combined_on=True,
        combined_mv_independent=True,
        shear_on=True,
        torsion_on=True,
    )
    out = _out()
    out["combined"] = {
        "valid": False,
        "have_m": True,
        "have_v": True,
        "have_t": False,
        "method": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "m_v_independent": True,
        "biaxial": True,
        "directions": {},
    }
    txt = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    assert "max(N+M+T, N+V+T)" in txt
    assert "N+M+V+T" not in txt
    assert "NOT ASSESSED" in txt


def test_report_keeps_only_governing_biaxial_combined_worked_block():
    import io

    out = _out()
    vx = _combined_out(mv_independent=True)
    vy = copy.deepcopy(vx)
    vx.update(component="vx", governing_face="negative", governing_cot=1.25)
    vy.update(component="vy", governing_face="positive", governing_cot=1.75)
    out["combined"] = dict(
        vx,
        directions={"vx": vx, "vy": vy},
        biaxial=True,
    )
    out["worked_example_selection"] = (
        result_presentation.worked_example_selection(_inp(), out)
    )
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, _inp(), out, figures=False
    )
    builder._combined()

    screen_blocks = []
    for flowable in builder.flow:
        if not isinstance(flowable, sector_report.KeepTogether):
            continue
        text = " ".join(
            item.getPlainText()
            for item in flowable._content
            if hasattr(item, "getPlainText")
        )
        if "Governing directional worked example:" in text:
            screen_blocks.append(text)

    assert len(screen_blocks) == 1
    assert all(f"{chr(0x2211)}(SEd/SRd)" in text for text in screen_blocks)


def test_report_combined_out_of_range_retains_values_and_verdicts():
    out = _out()
    c = _combined_out()
    c["outside_default_range"] = True
    c["longitudinal"] = dict(
        valid=True, axis="x", z=0.54, m_ed=100.0, m_rd=400.0,
        ftd_v=200.0, ftd_t=120.0, mv=108.0, mt=32.4,
        m_total=240.4, util=240.4 / 400.0, ok=True, capped=False,
    )
    _retain_combined_chords(c, c["longitudinal"])
    out["combined"] = c
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "selected method's default range" in txt
    assert "actual values are used" in " ".join(txt.lower().split())
    assert "NO CODE VERDICT" not in txt


def test_report_combined_longitudinal_check():
    out = _out()
    c = _combined_out()
    c["longitudinal"] = dict(valid=True, axis="x", z=0.54, m_ed=100.0, m_rd=400.0,
                             ftd_v=200.0, ftd_t=120.0, mv=108.0, mt=32.4,
                             m_total=240.4, util=240.4 / 400.0, ok=True, capped=False)
    _retain_combined_chords(c, c["longitudinal"])
    out["combined"] = c
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Longitudinal reinforcement" in txt
    assert "6.2.3(7)" in txt                        # the shear-shift cap clause
    assert "tension chord" in txt


def test_report_combined_longitudinal_biaxial_fallback_warns():
    # Only the FALLBACK path (conditional solve failed -> pure-axis MRd) warns;
    # a successful conditional MRd is the honest capacity and needs no warning.
    out = _out()
    c = _combined_out()
    c["longitudinal"] = dict(valid=True, axis="x", z=0.5, m_ed=20.0, m_rd=300.0,
                             ftd_v=187.5, ftd_t=100.0, mv=60.0, mt=25.0, m_total=105.0,
                             util=105.0 / 300.0, ok=True, capped=False,
                             tension_low=True, off_util=0.03, biaxial=False,
                             m_off=90.0, conditional=False)
    _retain_combined_chords(c, c["longitudinal"])
    out["combined"] = c
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "required x-axis negative face" in txt
    assert "pure-axis substitute" in txt


def test_report_withholds_verdict_for_preserved_non_governing_fallback():
    out = _out()
    c = _combined_out()
    exact = dict(
        valid=True, axis="x", z=0.5, m_ed=20.0, m_rd=250.0,
        ftd_v=187.5, ftd_t=100.0, mv=60.0, mt=25.0, m_total=105.0,
        util=105.0 / 250.0, ok=True, capped=False,
        tension_low=False, conditional=True,
    )
    fallback = dict(
        exact,
        util=0.20,
        tension_low=True,
        conditional=False,
    )
    off_axis = dict(
        valid=True, axis="y", z=0.4, m_ed=20.0, m_rd=100.0,
        ftd_v=0.0, ftd_t=65.0, mv=0.0, mt=13.0, m_total=33.0,
        util=0.33, ok=True, capped=False,
        tension_low=True, m_off=20.0, conditional=True,
    )
    c["longitudinal"] = exact
    c["chord_off"] = off_axis
    _retain_combined_chords(c, fallback, exact, off_axis)
    out["combined"] = c

    txt = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), out, figures=False
    )).split())

    assert "pure-axis substitute" in txt
    assert (
        "utilisation = 42 % "
        "(NOT ASSESSED - ANOTHER FACE USES A SUBSTITUTE)"
        in txt
    )
    assert (
        "utilisation = 33 % (NOT ASSESSED - CHORD ASSESSMENT INCOMPLETE)"
        in txt
    )


def test_report_combined_longitudinal_conditional_mrd():
    # The conditional MRd states the coexisting off-axis moment it carries; no
    # biaxial warning is printed (the capacity is already honest).
    out = _out()
    c = _combined_out()
    c["longitudinal"] = dict(valid=True, axis="x", z=0.5, m_ed=20.0, m_rd=250.0,
                             ftd_v=187.5, ftd_t=100.0, mv=60.0, mt=25.0, m_total=105.0,
                             util=105.0 / 250.0, ok=True, capped=False,
                             tension_low=True, off_util=0.4, biaxial=True,
                             m_off=90.0, conditional=True, has_torsion=True)
    _retain_combined_chords(c, c["longitudinal"])
    out["combined"] = c
    # Collapse the PDF's line wrapping so multi-word phrases can be asserted.
    txt = " ".join(_pdf_text(sector_report.build_report({}, _inp(), out,
                                                        figures=False)).split())
    assert "conditional on the coexisting My = 90.0 kNm" in txt
    assert "Biaxial bending" not in txt
    assert "pure-axis substitute" not in txt


def test_report_off_axis_skip_disclosed_uniaxially():
    # Codex round-2 P2: a subdivided-section torsion run with NO off-axis bending
    # (biaxial False) must still disclose that the off-axis torsion chord is skipped
    # -- the note must not be gated on biaxial.
    out = _out()
    c = _combined_out()
    c["longitudinal"] = dict(valid=True, axis="x", z=0.5, m_ed=100.0, m_rd=400.0,
                             ftd_v=200.0, ftd_t=120.0, mv=100.0, mt=30.0, m_total=230.0,
                             util=230.0 / 400.0, ok=True, capped=False,
                             tension_low=True, off_util=0.0, biaxial=False,
                             m_off=0.0, conditional=True, has_torsion=True,
                             off_not_evaluated="subdivided")
    _retain_combined_chords(c, c["longitudinal"])
    out["combined"] = c
    txt = " ".join(_pdf_text(sector_report.build_report({}, _inp(), out,
                                                        figures=False)).split())
    assert "per sub-tube" in txt                     # the subdivided disclosure fired
    assert (
        "utilisation = 57.5 % (NOT ASSESSED - CHORD ASSESSMENT INCOMPLETE)"
        in txt
    )


def test_report_partial_torsion_face_coverage_disclosed():
    # Codex round-5 P2: when a chord face carrying the torsion share could not be
    # built (not_solved), the governing chord shown may not be the critical face --
    # the report must say so, even for a uniaxial run.
    out = _out()
    c = _combined_out()
    c["longitudinal"] = dict(valid=True, axis="x", z=0.5, m_ed=100.0, m_rd=400.0,
                             ftd_v=200.0, ftd_t=120.0, mv=100.0, mt=30.0, m_total=230.0,
                             util=230.0 / 400.0, ok=True, capped=False,
                             tension_low=True, off_util=0.0, biaxial=False,
                             m_off=0.0, conditional=True, has_torsion=True,
                             gets_shift=True, off_not_evaluated="not_solved")
    _retain_combined_chords(c, c["longitudinal"])
    out["combined"] = c
    txt = " ".join(_pdf_text(sector_report.build_report({}, _inp(), out,
                                                        figures=False)).split())
    assert "may not be the critical face" in txt
    assert (
        "utilisation = 57.5 % (NOT ASSESSED - CHORD ASSESSMENT INCOMPLETE)"
        in txt
    )


def test_report_off_axis_chord_block():
    # The off-axis chord check renders with its own formula pair: bending plus
    # the torsion share (no shear shift), against the conditional capacity.
    out = _out()
    c = _combined_out()
    c["longitudinal"] = dict(valid=True, axis="x", z=0.5, m_ed=20.0, m_rd=250.0,
                             ftd_v=187.5, ftd_t=100.0, mv=60.0, mt=25.0, m_total=105.0,
                             util=105.0 / 250.0, ok=True, capped=False,
                             tension_low=True, off_util=0.4, biaxial=True,
                             m_off=90.0, conditional=True, has_torsion=True)
    c["chord_off"] = dict(valid=True, axis="y", z=0.3, m_ed=90.0, m_rd=180.0,
                          ftd_v=0.0, ftd_t=100.0, mv=0.0, mt=15.0, m_total=105.0,
                          util=105.0 / 180.0, ok=True, capped=False,
                          tension_low=True, m_off=20.0, conditional=True,
                          z_src="circular_fitted_section")
    _retain_combined_chords(c, c["longitudinal"], c["chord_off"])
    out["combined"] = c
    txt = " ".join(_pdf_text(sector_report.build_report({}, _inp(), out,
                                                        figures=False)).split())
    assert "Off-axis chord (about y" in txt          # header now names the governing face
    assert "conditional on the coexisting Mx = 20.0 kNm" in txt
    assert "fitted circular section" in txt
    assert "circular_fitted_section" not in txt


def test_report_combined_independent_uses_max_form():
    out = _out()
    out["combined"] = _combined_out(mv_independent=True)
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "separately" in txt                      # M & V checked separately


def test_report_combined_transverse_shows_shear_credit():
    out = _out()
    c = _combined_out()
    c["transverse"] = dict(valid=True, cot=2.0, theta_deg=26.6, u_stirrup=0.6,
                           u_crush=0.4, governing=0.6, governs="stirrups", ok=True,
                           shear_fraction=0.0, torsion_fraction=0.6,
                           shear_credited=True, vrd_c=120.0, v_ed=40.0)
    out["combined"] = c
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Shared stirrup" in txt
    assert "concrete carries the shear" in txt      # the VRd,c credit note
    assert "Physical resistance components" in txt
    assert "Concrete compression strut" in txt
    assert "Closed stirrup" in txt
    assert "Longitudinal reinforcement" in txt
    assert "closed-stirrup utilisation" in txt
    assert "crushing utilisation" not in txt
    assert "Governing (stirrups)" not in txt


def test_report_skips_invalid_combined():
    out = _out()
    out["combined"] = {"valid": False, "have_m": True, "have_v": False,
                       "have_t": False, "method": "x"}
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Combined bending" not in txt


def _links_out():
    return {"res": {"vrd_s": 540.0, "vrd_max": 648.9, "vrd": 540.0, "cot": 2.5,
                    "tan": 0.4, "sin_cos": 2.5 / (1.0 + 2.5**2),
                    "theta_deg": 21.8, "z": 495.0, "fywd": 416.67, "nu1": 0.525,
                    "alpha_cw": 1.0, "sigma_cp": 0.0, "fcd": 24.14,
                    "cot_min": 1.0, "cot_max": 2.5,
                    "cot_unconstrained": 3.0,
                    "angle_selection": "upper entered bound",
                    "angle_a": 436.3, "angle_b": 3801.9,
                    "governs": "stirrups (VRd,s)", "valid": True},
            "util": 80.0 / 540.0, "asw": 157.08, "asw_over_s": 1.047, "legs": 2.0,
            "dia": 10.0, "s": 150.0, "fywk": 500.0, "cot_min": 1.0, "cot_max": 2.5,
            "delta_ftd": 375.0, "cot_limit_lo": 1.0, "cot_limit_hi": 2.5,
            "longitudinal_shear_force": 375.0,
            "z_source": "plastic internal lever arm",
            "z_component": "z_y",
            "z_source_angle_deg": 90.0,
            "z_source_case": "PL-TEST",
            "z_source_axial_kn": 0.0,
            "out_of_limits": False, "required": True}


def _h06_circular_shear_out(*, complete=True):
    sh = _shear_out_2023()
    concrete = shear_core.vrd_c_2023(
        35.0,
        codes.EC2_2023,
        400.0,
        550.0,
        1473.0,
        500.0 / 1.15,
        32.0,
        n_ed_tension_kn=300.0,
        m_ed_knm=110.0,
        v_ed_kn=50.0,
    )
    geometry_result = shear_core.resolve_shear_geometry(
        model_2023=True,
        solid_rectangle=False,
        section_form=shear_core.SHEAR_SECTION_CIRCULAR,
        bw_mm=400.0,
        bw_user=True,
        links_present=True,
        hoop_diameter_mm=600.0 if complete else 0.0,
        fitted_z_mm=500.0 if complete else 0.0,
        duct_case=shear_core.SHEAR_DUCT_GROUTED_PLASTIC_THIN,
        duct_sum_mm=80.0,
        duct_largest_mm=40.0,
    )
    sh.update(
        res=concrete,
        util=50.0 / concrete["vrd_c"],
        bw=400.0,
        bw_auto=600.0,
        bw_user=True,
        shear_geometry=geometry_result,
    )
    asw = 2.0 * math.pi * 10.0**2 / 4.0
    gross = asw / 150.0
    if complete:
        link_result = shear_core.vrd_links(
            35.0,
            codes.EC2_2023,
            geometry_result["links_bw_mm"],
            550.0,
            gross * geometry_result["asw_factor"],
            500.0,
            0.0,
            0.18,
            1.0,
            2.5,
            z_mm=geometry_result["fitted_z_mm"],
            fcd_mpa=20.0,
            gamma_s=1.15,
            v_ed_kn=50.0,
        )
    else:
        link_result = shear_core.unassessed_links_result(
            model="2023",
            reason=geometry_result["links_reason"],
            bw_mm=400.0,
            d_mm=550.0,
            asw_over_s=0.0,
        )
    sh["links"] = {
        "res": link_result,
        "util": (
            50.0 / link_result["vrd"] if link_result.get("valid") else None
        ),
        "assessment_reason": link_result.get("reason"),
        "asw": asw,
        "asw_over_s": gross,
        "effective_asw_over_s": (
            gross * geometry_result["asw_factor"] if complete else 0.0
        ),
        "asw_factor": geometry_result.get("asw_factor"),
        "shear_geometry": geometry_result,
        "legs": 2.0,
        "dia": 10.0,
        "s": 150.0,
        "fywk": 500.0,
        "cot_min": 1.0,
        "cot_max": 2.5,
        "delta_ftd": None,
        "longitudinal_shear_force": (
            50.0 * link_result["cot"] if link_result.get("valid") else None
        ),
        "cot_limit_lo": 1.0,
        "cot_limit_hi": 2.5,
        "angle_limits": {
            "clause": "DS/EN 1992-1-1:2023, 8.2.3(4), Formula (8.41)"
        },
        "model_2023": True,
        "z_source": (
            "circular_fitted_section"
            if complete else shear_core.SHEAR_CIRCULAR_REASON
        ),
        "out_of_limits": False,
        "required": False if complete else None,
    }
    return sh


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_report_profiles_retain_h06_circular_and_duct_result(profile):
    inp = _inp()
    inp.update(
        shear_on=True,
        shear_links=True,
        shear_method=codes.EC2_2023.label,
        shear_section_form=shear_core.SHEAR_SECTION_CIRCULAR,
    )
    shear_out = _h06_circular_shear_out()
    out = {"shear": shear_out}

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    selected = capacity.select_nominal_shear_resistance(
        shear_out,
        links_selected=True,
    )
    assert selected.route == "concrete"
    assert "Shear without links" in text
    assert "Shear with links" in text
    assert f"{100.0 * shear_out['links']['util']:.1f} %" in text
    assert "non-governing" in text
    assert "link-yield resistance governs" not in text
    if profile != "Brief":
        assert "Circular section" in text
        assert "Fitted-section arm z = 500.000 mm" in text
        assert "Effective link area / spacing" in text
        assert "0.66667" in text
        assert "Grouted plastic ducts - confirmed thin wall" in text
        assert "336.0 mm" in text
        assert "0.80" in text
        assert "fitted circular section" in text
        assert "circular_fitted_section" not in text


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_report_profiles_fail_closed_for_missing_circular_shear_geometry(profile):
    inp = _inp()
    inp.update(
        shear_on=True,
        shear_links=True,
        shear_method=codes.EC2_2023.label,
        shear_section_form=shear_core.SHEAR_SECTION_CIRCULAR,
    )
    out = {"shear": _h06_circular_shear_out(complete=False)}

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    assert "NOT ASSESSED" in text
    assert "Enter the governing web width, hoop diameter" in text
    assert shear_core.SHEAR_CIRCULAR_REASON not in text
    assert "(OK)" not in text
    assert "(EXCEEDED)" not in text


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_report_profiles_fail_closed_for_invalid_circular_off_axis_arm(profile):
    inp = _inp()
    inp.update(
        shear_on=True,
        shear_links=True,
        torsion_on=True,
        shear_method=codes.EC2_2023.label,
        shear_section_form=shear_core.SHEAR_SECTION_CIRCULAR,
    )
    shear_out = _h06_circular_shear_out()
    chord = {
        "valid": True,
        "role": "shear_axis",
        "chord_role": "flexural_tension",
        "chord_formula": "8.51",
        "axis": "y",
        "tension_low": True,
        "z": 0.5,
        "m_ed": 0.0,
        "face_m_ed_signed": 0.0,
        "m_rd": 400.0,
        "ftd_v": 100.0,
        "ftd_t": 80.0,
        "mv": 50.0,
        "mt": 20.0,
        "m_total": 70.0,
        "util": 0.175,
        "ok": True,
        "status": "NOT ASSESSED",
        "capped": False,
        "conditional": True,
        "m_off": 0.0,
        "has_torsion": True,
        "gets_shift": True,
        "theta_mode": "utilisation",
        "off_not_evaluated": "circular_geometry",
    }
    shear_out["links"].update(
        chord=chord,
        chord_off=None,
        chord_candidates=[chord],
        longitudinal_assessment={
            "status": "NOT ASSESSED",
            "ok": None,
            "util": chord["util"],
            "coverage_complete": False,
            "reason": shear_core.SHEAR_CIRCULAR_REASON,
        },
    )
    shear_out.update(
        assessment_status="NOT ASSESSED",
        assessment_ok=None,
    )

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, {"shear": shear_out}, figures=False, profile=profile
            )
        ).split()
    )

    assert "Shear longitudinal chords" in text
    assert "NOT ASSESSED" in text
    if profile == "Brief":
        assert "Shear longitudinal chords PL-TEST NOT ASSESSED" in text
        assert "Enter the governing web width, hoop diameter" in text
    else:
        assert re.search(
            r"Vy,Ed 50\.000 kN [0-9.]+ kN [0-9.]+ % NOT ASSESSED",
            text,
        )
        assert "NOT ASSESSED - CHORD ASSESSMENT INCOMPLETE" in text
        assert (
            "fitted-section lever arm required for the circular off-axis chord"
            in text
        )
        assert "for both directions" in text
        assert "Longitudinal chord assessment: NOT ASSESSED" in text
    assert shear_core.SHEAR_CIRCULAR_REASON not in text


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_report_directional_shear_table_retains_chord_assessment_status(profile):
    inp = _inp()
    inp.update(
        shear_on=True,
        shear_links=True,
        shear_method=codes.EC2_2023.label,
        shear_section_form=shear_core.SHEAR_SECTION_CIRCULAR,
    )
    direction = _h06_circular_shear_out()
    direction["component"] = "vy"
    direction["signed_v_ed"] = direction["v_ed"]
    direction["status"] = "NOT ASSESSED"
    direction["assessment_status"] = "NOT ASSESSED"
    direction["links"]["longitudinal_assessment"] = {
        "status": "NOT ASSESSED",
        "ok": None,
        "util": 0.175,
        "coverage_complete": False,
        "reason": shear_core.SHEAR_CIRCULAR_REASON,
    }
    aggregate = {
        "directions": {"vy": direction},
        "biaxial": False,
    }

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, {"shear": aggregate}, figures=False, profile=profile
            )
        ).split()
    )

    if profile == "Brief":
        assert "Shear Vy longitudinal chords PL-TEST NOT ASSESSED" in text
        assert "Shear Vy longitudinal chords PL-TEST PASS" not in text
    else:
        assert re.search(
            r"Vy,Ed 50\.000 kN [0-9.]+ kN [0-9.]+ % NOT ASSESSED",
            text,
        )
        assert not re.search(
            r"Vy,Ed 50\.000 kN [0-9.]+ kN [0-9.]+ % PASS",
            text,
        )


def test_report_includes_shear_links_section():
    out = _out()
    sh = _shear_out()
    sh["links"] = _links_out()
    out["shear"] = sh
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Shear reinforcement (links)" in txt
    assert "6.8" in txt and "6.9" in txt           # the two clause formulae
    assert "540" in txt                            # VRd,s / VRd
    assert "stirrups" in txt                       # governing mechanism
    assert chr(0x3B8) in txt                       # theta glyph rendered
    normalized = " ".join(txt.split())
    assert "Calculated arm z = 495.000 mm = |z_y| from PL-TEST" in normalized
    assert "bottom (-y) 90" in normalized
    assert "used in V_Rd,s and V_Rd,max" in normalized


def test_report_with_unavailable_calculated_link_arm_fails_closed():
    out = _out()
    sh = _shear_out()
    links = _links_out()
    links.update(
        util=None,
        longitudinal_shear_force=None,
        assessment_reason=(
            "calculated plastic lever arm unavailable: the exact face-aligned "
            "Plastic solve did not converge"
        ),
    )
    links["res"] = {
        "valid": False,
        "calculation_state": "NOT ASSESSED",
        "reason": "exact calculated plastic lever arm z is unavailable",
        "z": None,
        "vrd_s": None,
        "vrd_max": None,
        "vrd": None,
    }
    sh["links"] = links
    out["shear"] = sh
    inp = _inp()
    inp.update(shear_on=True, shear_links=True)

    txt = _pdf_text(sector_report.build_report({}, inp, out, figures=False))
    normalized = " ".join(txt.split())

    assert "NOT ASSESSED" in txt
    assert (
        "The exact face-aligned Plastic calculation did not converge, so the "
        "link lever arm is unavailable"
    ) in normalized


def test_report_includes_2023_shear_links_stress_checks():
    from sector import codes as _codes, shear as _shear

    out = _out()
    sh = _shear_out_2023()
    demand = 150.0
    sh["v_ed"] = demand
    sh["util"] = demand / sh["res"]["vrd_c"]
    asw = 2.0 * math.pi * 10.0**2 / 4.0
    result = _shear.vrd_links(
        35.0,
        _codes.EC2_2023,
        300.0,
        550.0,
        asw / 150.0,
        500.0,
        0.0,
        0.18,
        1.0,
        2.5,
        z_mm=495.0,
        fcd_mpa=20.0,
        gamma_s=1.15,
        v_ed_kn=demand,
    )
    sh["links"] = {
        "res": result,
        "util": demand / result["vrd"],
        "asw": asw,
        "asw_over_s": asw / 150.0,
        "legs": 2.0,
        "dia": 10.0,
        "s": 150.0,
        "fywk": 500.0,
        "cot_min": 1.0,
        "cot_max": 2.5,
        "delta_ftd": None,
        "longitudinal_shear_force": demand * result["cot"],
        "cot_limit_lo": 1.0,
        "cot_limit_hi": 2.5,
        "angle_limits": {
            "clause": "DS/EN 1992-1-1:2023, 8.2.3(4), Formula (8.41)"
        },
        "model_2023": True,
        "z_source": "0.9 d",
        "out_of_limits": False,
        "required": True,
    }
    out["shear"] = sh
    inp = _inp()
    inp.update(
        shear_on=True,
        shear_links=True,
        shear_method=codes.EC2_2023.label,
    )
    text = _pdf_text(sector_report.build_report({}, inp, out, figures=False))
    assert "8.42" in text and "8.44" in text and "8.50" in text
    assert "0.500" in text
    assert "not implemented" not in text


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_report_profiles_fail_closed_for_2023_links_under_axial_compression(
    profile,
):
    from sector import codes as _codes, shear as _shear

    out = _out()
    sh = _shear_out_2023()
    result = _shear.vrd_links(
        35.0,
        _codes.EC2_2023,
        300.0,
        550.0,
        1.0,
        500.0,
        800.0,
        0.18,
        1.0,
        2.5,
        z_mm=495.0,
        fcd_mpa=20.0,
        gamma_s=1.15,
        v_ed_kn=50.0,
    )
    reason = result["reason"]
    sh["links"] = {
        "res": result,
        "util": None,
        "assessment_reason": reason,
        "asw": 150.0,
        "asw_over_s": 1.0,
        "legs": 2.0,
        "dia": 10.0,
        "s": 150.0,
        "fywk": 500.0,
        "cot_min": 1.0,
        "cot_max": 2.5,
        "model_2023": True,
        "out_of_limits": False,
        "required": True,
        "longitudinal_assessment": {
            "status": "NOT APPLICABLE",
            "ok": None,
            "util": None,
            "reason": "no_longitudinal_chord_action",
        },
    }
    sh.update(
        n_ed_comp=800.0,
        status="PASS",
        resistance_status="NOT ASSESSED",
        assessment_status="NOT ASSESSED",
        assessment_ok=None,
    )
    out["shear"] = sh
    inp = _inp()
    inp.update(
        shear_on=True,
        shear_links=True,
        shear_method=_codes.EC2_2023.label,
    )

    text = " ".join(
        _pdf_text(
            sector_report.build_report(
                {}, inp, out, figures=False, profile=profile
            )
        ).split()
    )

    assert "NOT ASSESSED" in text
    assert "Net axial compression is present" in text
    assert "force assigned to the web" in text
    assert "compression-chord depth" in text
    assert "Annex G" in text
    assert "applicability conditions were not demonstrated" not in text
    assert "No longitudinal chord action requires assessment" not in text
    if profile in {"Standard", "Audit"}:
        assert "Vy,Ed 50.000 kN - - NOT ASSESSED" in text
        assert "- kN inf NOT ASSESSED" not in text


def test_report_shear_links_out_of_limits_note():
    out = _out()
    sh = _shear_out()
    lk = _links_out()
    lk["cot_max"], lk["out_of_limits"] = 3.0, True
    sh["links"] = lk
    out["shear"] = sh
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "outside the selected method's default range" in txt
    assert "entered values are used" in txt.lower()
    assert "NO CODE VERDICT" not in txt


def test_report_torsion_out_of_limits_retains_values_and_verdict():
    out = _out()
    t = _torsion_out()
    t["cot_max"], t["out_of_limits"] = 3.0, True
    out["torsion"] = t
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "outside the selected method's default range" in txt
    assert "entered values are used" in txt.lower()
    assert "NO CODE VERDICT" not in txt


def test_fig_png_preserves_timeout_signal(monkeypatch):
    def timeout(*args, **kwargs):
        del args, kwargs
        raise publication_image_export.KaleidoExportTimeout("wedged")

    monkeypatch.setattr(publication_image_export, "export_png", timeout)
    png, timed_out = sector_report._fig_png(object(), 100, 100, timeout=0.3)
    assert png is None and timed_out is True


def test_report_stops_exporting_after_a_timeout():
    # Once one figure export times out (worker still alive at the join), the builder
    # marks _export_hung and skips every later export instead of blocking for each -- so
    # a figure-rich report fails truthfully and promptly.
    import io as _io
    rb = sector_report.ReportBuilder(_io.BytesIO(), {}, _inp(), _out(), figures=True)
    calls = {"n": 0}

    def _stub(fig, w, h, **kw):
        calls["n"] += 1
        return None, True            # simulate a wedged-browser timeout
    orig = sector_report._fig_png
    try:
        sector_report._fig_png = _stub
        with pytest.raises(sector_report.ReportFigureError, match="timed out"):
            rb._fig(object())        # first export times out -> sets the sentinel
        assert rb._export_hung is True
        with pytest.raises(sector_report.ReportFigureError, match="previously"):
            rb._fig(object())        # second export fails without trying again
    finally:
        sector_report._fig_png = orig
    assert calls["n"] == 1           # only the first figure actually tried to export


def test_report_fails_when_a_requested_figure_cannot_be_exported(monkeypatch):
    monkeypatch.setattr(sector_report, "ensure_image_server", lambda: None)
    monkeypatch.setattr(sector_report, "_fig_png",
                        lambda fig, width, height: (None, False))
    with pytest.raises(sector_report.ReportFigureError, match="report not created"):
        sector_report.build_report({}, _inp(), _out(), figures=True)


def test_report_prints_public_one_based_concrete_point_without_conversion():
    out = _out()
    out["elastic"]["max_conc_point"] = 1
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "point 1" in txt
    assert "point 0" not in txt


def _combined_longitudinal(theta_mode):
    # Minimal combined block that renders only the M+V+T tension-chord note. Crushing
    # and transverse are omitted so the section reduces to the longitudinal paragraph,
    # whose wording is driven purely by theta_mode.
    dkna = combined_core.dkna_interaction_result(
        0.0, None,
        0.50, 1.0,
        0.60, 1.0,
        0.30, 1.0,
        m_v_independent=False,
    )
    payload = {
        "method": "EN 1992-1-1:2005",
        "valid": True,
        "r_n": 0.0, "r_m": 0.50, "r_v": 0.60, "r_t": 0.30,
        "dkna_valid": dkna.valid,
        "dkna_ok": dkna.ok,
        "dkna_sum": dkna.utilisation,
        "dkna_selection": asdict(dkna),
        "m_v_independent": False,
        "longitudinal": {
            "valid": True, "ok": True, "axis": "x", "tension_low": True,
            "m_ed": 100.0, "m_rd": 200.0, "mv": 20.0, "mt": 10.0,
            "ftd_v": 40.0, "ftd_t": 15.0, "z": 0.25, "m_total": 130.0,
            "util": 0.65, "biaxial": False, "capped": False,
            "theta_mode": theta_mode,
        },
    }
    _retain_combined_chords(payload, payload["longitudinal"])
    return {"combined": payload}


def test_report_no_load_longitudinal_note_states_resistance_optimum():
    # theta_mode == "resistance": no live shear or torsion, so there is no live
    # member-angle objective and the capacity result uses its resistance optimum.
    txt = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), _combined_longitudinal("resistance"), figures=False)).split())
    assert "No shear or torsion is acting" in txt
    assert "resistance-optimum" in txt
    assert "minimise the governing utilisation" not in txt


def test_report_shared_longitudinal_note_states_the_common_angle():
    # theta_mode == "utilisation" is the normal case: one admissible member angle.
    txt = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), _combined_longitudinal("utilisation"), figures=False)).split())
    assert "ONE member strut angle shared" in txt
    assert "minimise the governing utilisation" in txt
