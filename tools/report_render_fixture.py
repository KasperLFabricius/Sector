"""Build and rasterise a stable Sector report QA fixture.

The normal report tests inspect PDF text. This fixture also passes every page
through PDFium so CI exercises the artifact an engineer actually opens. The
real Plotly/Kaleido exporter is retained so the gate also fails when the figures
an engineer expects in the issued report cannot be produced.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import functools
import math
import pathlib
import re
import sys
from dataclasses import asdict

import pypdf

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import case_analysis
import fatigue_analysis
import fatigue_inputs
import load_cases
import material_catalog
import result_presentation
import sector_report

from sector import (
    __version__,
    capacity,
    codes,
    combined,
    detailing,
    shear,
    torsion,
)
from sector.design_standards import DesignBasisKey
from sector.materials import Concrete
from sector.section import Section
from tools.publication_preflight import (
    REPORT_FURNITURE,
    RasterCrop,
    preflight_pdf,
    render_pdf,
    validate_crops,
    validate_raster_pages,
)
from tools.publication_preflight import (
    validate_caption_colocation as validate_report_table_colocation,
)

__all__ = (
    "render_pdf",
    "validate_outline_destinations",
    "validate_rendered_pages",
    "validate_report_page_semantics",
    "validate_report_table_colocation",
    "validate_worked_example_text",
)

# Geometry, concrete law, two steel laws, clear-spacing and minimum-reinforcement
# geometry, derived shear geometry, shear truss, torsion tube, two V-T interaction
# figures, one plastic interaction and state, one elastic state and strain profile,
# and four grouped-fatigue figures. An intentional fixture change must update this
# explicit contract.
_EXPECTED_FIGURE_COUNT = 19
_EXPECTED_PLASTIC_WORKED_HEADING = (
    "Worked plastic calculation (utilisation direction)"
)
_REPORT_CROPS = (
    RasterCrop(
        "report overview",
        2,
        (0.10, 0.08, 0.92, 0.90),
        "b65332482da8ad1429aee2e1f3b57a8c91688c1d6d3088c2871436c75769a661",
    ),
    RasterCrop(
        "report page furniture",
        2,
        (0.09, 0.02, 0.92, 0.98),
        "9b64441a8c8f251fa433daa8a2d9848b8ccc36d52db7897627296f62f8ad71a8",
    ),
)


class _FixedDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 7, 19, 12, 0, 0)
        return value if tz is None else value.replace(tzinfo=tz)


def validate_outline_destinations(reader: pypdf.PdfReader) -> list[tuple[str, int]]:
    """Return outline titles/pages after proving every link reaches its heading."""

    def normalized_text(value: object) -> str:
        # PDF extractors insert line breaks when a long visible heading wraps.
        # Bookmark titles are unwrapped strings, so compare semantic whitespace
        # rather than page-layout line boundaries.
        return " ".join(str(value).split())
    entries = []

    def visit(items):
        for item in items:
            if isinstance(item, list):
                visit(item)
                continue
            title = str(getattr(item, "title", item))
            page = reader.get_destination_page_number(item) + 1
            if page < 1 or page > len(reader.pages):
                raise AssertionError(
                    f"outline destination is invalid: {title!r} -> page {page}"
                )
            page_text = reader.pages[page - 1].extract_text() or ""
            if normalized_text(title) not in normalized_text(page_text):
                raise AssertionError(
                    f"outline destination misses its heading: {title!r} -> page {page}"
                )
            entries.append((title, page))

    visit(reader.outline)
    if not entries:
        raise AssertionError("the PDF contains no outline destinations")
    return entries


def _inputs() -> dict:
    plastic_cases = [
        {
            "name": "PL-QA-1",
            "description": "Routine combination | Source: QA register",
            "n_ed_kn": 0.0,
            "mx_ed_knm": 80.0,
            "my_ed_knm": 0.0,
            "v_ed_kn": 30.0,
            "t_ed_knm": 25.0,
            "check_minimum_reinforcement": True,
        },
        {
            "name": "PL-QA-2",
            "description": "Governing combination | Source: QA register",
            "n_ed_kn": 0.0,
            "mx_ed_knm": 125.0,
            "my_ed_knm": 0.0,
            "v_ed_kn": 0.0,
            "t_ed_knm": 0.0,
            "check_minimum_reinforcement": False,
        },
    ]
    elastic_cases = [
        {
            "name": "EL-QA-1",
            "description": "Characteristic stresses | Source: QA register",
            "n_long_ed_kn": 0.0,
            "mx_long_ed_knm": 80.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 20.0,
            "my_short_ed_knm": 0.0,
            "calculate_crack_width": True,
        },
        {
            "name": "EL-QA-2",
            "description": "Frequent response | Source: QA register",
            "n_long_ed_kn": 0.0,
            "mx_long_ed_knm": 45.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 10.0,
            "my_short_ed_knm": 0.0,
            "calculate_crack_width": False,
        },
    ]
    mild_catalogue, second_id = material_catalog.add_entry(
        material_catalog.default_catalog("mild"), "mild"
    )
    mild_catalogue["items"][0].update({
        "name": "New B500 reinforcement",
        "description": "Primary reinforcement",
    })
    mild_catalogue["items"][1].update({
        "name": "Existing reinforcement",
        "description": "Verified from archive test certificate",
        "fytk": 235.0,
        "fyck": 235.0,
        "futk": 360.0,
    })
    mild_materials = {
        item["id"]: material_catalog.build_material(item, "mild")
        for item in mild_catalogue["items"]
    }
    outer = [(-0.1, -0.15), (0.1, -0.15), (0.1, 0.15), (-0.1, 0.15)]
    bars = [(0.0, -0.12, 500.0), (0.0, 0.12, 400.0)]
    fatigue_catalogue = fatigue_inputs.default_catalog()
    fatigue_catalogue["items"][0].update({
        "name": "Straight reinforcing bars",
        "description": "QA fixture detail",
    })
    fatigue_spectrum = [
        {
            "spectrum": "Road traffic",
            "name": "FAT-QA-H",
            "description": "Heavy vehicle range | Source: QA spectrum",
            "cycles": 1.0e5,
            "n_long_ed_kn": 0.0,
            "mx_long_ed_knm": 8.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 4.0,
            "my_short_ed_knm": 0.0,
        },
        {
            "spectrum": "Road traffic",
            "name": "FAT-QA-M",
            "description": "Frequent vehicle range | Source: QA spectrum",
            "cycles": 1.0e6,
            "n_long_ed_kn": 0.0,
            "mx_long_ed_knm": 8.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 2.0,
            "my_short_ed_knm": 0.0,
        },
    ]
    fatigue_basis = fatigue_inputs.default_basis()
    fatigue_basis.update({
        "notes": (
            "QA traffic spectrum REF-FAT-01; QA cycle register REF-CYC-01; "
            "single loaded lane in the QA fixture; issued-report regression spectrum"
        ),
    })
    return {
        "mode": "Both",
        "plastic_cases": plastic_cases,
        "elastic_cases": elastic_cases,
        "fatigue_on": True,
        "fatigue_edition": DesignBasisKey.FIRST_GEN_DK_NA_2024.value,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": True,
        "fatigue_concrete_method": "Explicit Palmgren-Miner spectrum",
        "fatigue_gamma_ff": 1.0,
        "fatigue_gamma_s": 1.15,
        "fatigue_gamma_c": 1.50,
        "fatigue_beta_cc_t0": 1.0,
        "fatigue_t0_days": 28.0,
        "fatigue_concrete_k1": 0.85,
        "fatigue_concrete_c": 14.0,
        fatigue_inputs.DETAIL_CATALOG_KEY: fatigue_catalogue,
        fatigue_inputs.SPECTRUM_TABLE_KEY: fatigue_spectrum,
        fatigue_inputs.BASIS_KEY: fatigue_basis,
        "shear_on": True,
        "shear_links": True,
        "shear_method": codes.EC2_2005_DKNA.label,
        "shear_vx_link_legs": 2.0,
        "shear_vy_link_legs": 2.0,
        "shear_link_dia": 10.0,
        "shear_link_s": 150.0,
        "shear_fywk": 500.0,
        "torsion_on": True,
        "torsion_method": codes.EC2_2005_DKNA.label,
        "torsion_gamma_ct": codes.EC2_2005_DKNA.gamma_ct,
        "combined_on": True,
        "combined_method": codes.EC2_2005_DKNA.label,
        "combined_mv_independent": False,
        "strut_cot_min": 1.0,
        "strut_cot_max": 2.5,
        "minimum_reinforcement_on": True,
        "transverse_detailing_on": True,
        "clear_spacing_on": True,
        "detailing_edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "detailing_member_type": detailing.MEMBER_BEAM,
        "detailing_cut_direction": detailing.CUT_TRANSVERSE,
        "detailing_d_upper": 16.0,
        "detailing_include_tendons": False,
        "transverse_ductility_class": "B",
        "transverse_apply_ductility_reduction": False,
        "shear_vx_transverse_leg_spacing": 0.0,
        "shear_vy_transverse_leg_spacing": 0.0,
        "plastic_case": {
            "id": "PL-QA-1",
            "type": plastic_cases[0]["description"],
            "source": "QA fixture combination register",
        },
        "elastic_case": {
            "id": "EL-QA-1",
            "type": elastic_cases[0]["description"],
            "source": "QA fixture combination register",
        },
        "outer": outer,
        "holes": [],
        "bars": bars,
        "tendons": [],
        "section": Section.from_polygon(
            corners=outer,
            holes=[],
            bars_xy_area_mm2=bars,
            tendons_xy_area_mm2=[],
        ),
        "bar_elements": [
            {
                "id": "R1", "x_mm": 0.0, "y_mm": -120.0,
                "area_mm2": 500.0, "diameter_mm": 25.23,
                "size_mode": "Area", "material_id": "M1",
                "fatigue_detail_id": "F1",
            },
            {
                "id": "R2", "x_mm": 0.0, "y_mm": 120.0,
                "area_mm2": 400.0, "diameter_mm": 22.57,
                "size_mode": "Area", "material_id": second_id,
                "fatigue_detail_id": "F1",
            },
        ],
        "tendon_elements": [],
        "concrete": Concrete(fck=30.0, gamma_c=1.5, curve=2),
        "steel": mild_materials["M1"],
        "mild_material_catalog": mild_catalogue,
        "mild_materials": mild_materials,
        "bar_materials": [mild_materials["M1"], mild_materials[second_id]],
        "capacity_steel_material_id": second_id,
        "prestress": None,
        "P_pl": 0.0,
        "Mx_pl": 80.0,
        "My_pl": 0.0,
        "P_el_l": 0.0,
        "Mx_el_l": 80.0,
        "My_el_l": 0.0,
        "P_el_s": 0.0,
        "Mx_el_s": 20.0,
        "My_el_s": 0.0,
        "nl": 15.0,
        "ns": 6.0,
        "conc_Ec": 33.0,
        "sls_fctm": 2.9,
        "sls_cw": True,
        "v_min": 0.0,
        "v_max": 360.0,
        "v_inc": 90.0,
        "extent": 0.2,
    }


def _plastic_point() -> dict:
    """Return the retained accepted-state operands for the worked capacity point."""
    return {
        "V": 0.0,
        "Mx": 100.0,
        "My": 0.0,
        "na_x": 0.0,
        "na_y": -0.0075,
        "eps_c": 0.35,
        "eps_s": 0.25,
        "eps_s_comp": -0.1,
        "eps_cable": 0.0,
        "kappa": 0.0035 / 0.1575,
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
        "compression_depth": 0.1575,
        "neutral_axis_offset": -0.0075,
        "strain_gradient_x": 0.0,
        "strain_gradient_y": 0.0035 / 0.1575,
        "strain_offset": 1.0 / 6000.0,
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
            "point_no": 4,
            "ring": "Outer",
            "ring_point_no": 4,
            "x_mm": -100.0,
            "y_mm": 150.0,
            "section_strain_permille": 3.5,
            "strain_permille": -3.5,
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
            "distance_from_na_m": 0.1575,
            "curvature_per_m": 0.0035 / 0.1575,
            "selected": True,
        }],
        "curvature_selection": {
            "mode": "concrete_crushing",
            "element_index": None,
            "curvature_per_m": 0.0035 / 0.1575,
        },
    }


def _elastic_state(mx: float) -> dict:
    """Return one retained accepted elastic state without rerunning the solver."""
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


def _crack() -> dict:
    """Return a complete retained 2005 crack-width worked example."""
    rho = 2.72 / 99.0
    ac_eff = 0.0005 / rho
    concrete_reduction = 0.4 * 2.9 / rho * (1.0 + 6.06 * rho)
    mean_strain = 0.213 / 235.0
    sigma_s = mean_strain * 200_000.0 + concrete_reduction
    mean = {
        "record_kind": "CrackMeanStrainOperands",
        "sigma_s": sigma_s,
        "kt": 0.4,
        "fctm": 2.9,
        "rho_p_eff": rho,
        "alpha_e": 6.06,
        "es": 200_000.0,
        "concrete_tension_reduction": concrete_reduction,
        "formula_candidate": mean_strain,
        "lower_bound_factor": 0.6,
        "lower_bound_candidate": 0.6 * sigma_s / 200_000.0,
        "selected_candidate": "formula-7.9",
        "selected_esm_ecm": mean_strain,
    }
    spacing = {
        "record_kind": "CrackSpacing2005Operands",
        "cover": 40.0,
        "diameter": 16.0,
        "rho_p_eff": rho,
        "k1": 0.8,
        "k2": 0.5,
        "k3_base": 3.4,
        "k3_used": 3.4,
        "k4": 0.425,
        "nearest_neighbour_spacing": 100.0,
        "close_spacing_limit": 240.0,
        "tension_zone_depth": 0.15,
        "formula_7_11": 235.0,
        "geometric_7_14": 195.0,
        "selected_candidate": "formula-7.11",
        "selected_spacing": 235.0,
    }
    candidate = {
        "element_type": "Bar",
        "element_no": 1,
        "element_id": "bar 1",
        "x_mm": 0.0,
        "y_mm": -120.0,
        "area_mm2": 500.0,
        "wk": 0.213,
        "sr_max": 235.0,
        "esm_ecm": mean_strain,
        "sigma_s": sigma_s,
        "rho_p_eff": rho,
        "ac_eff": ac_eff,
        "hc_ef": 0.125,
        "phi": 16.0,
        "cover": 40.0,
        "coarse": False,
        "edition": "2004",
        "kw": 1.0,
        "k1_r": 1.0,
        "kfl": 1.0,
        "sr_max_geometric": False,
        "as_eff": 0.0005,
        "ap_eff": 0.0,
        "ap_eff_weighted": 0.0,
        "xi1": None,
        "reinforcement_type": "mild",
        "bc_ef": 0.0,
        "direct_tension": False,
        "scope": "dominant direction",
        "direction_deg": 90.0,
        "equivalent_diameter": 25.231,
        "diameter_source": "provided",
        "cover_source": "geometry",
        "bond_coefficient": 0.8,
        "modular_ratio": 6.06,
        "mean_strain_operands": mean,
        "spacing_operands": spacing,
    }
    effective_area = {
        "record_kind": "CrackEffectiveArea2005Fine",
        "section_depth": 0.3,
        "effective_depth": 0.25,
        "tension_zone_depth": 0.4,
        "h_minus_d": 0.05,
        "candidate_2_5_h_minus_d": 0.125,
        "candidate_h_minus_x_over_3": 0.13333333333333333,
        "candidate_h_over_2": 0.15,
        "selected_candidate": "2.5(h-d)",
        "selected_hc_eff": 0.125,
        "band_limit": -0.025,
        "ac_eff": ac_eff,
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


def _results(inp: dict | None = None) -> dict:
    inp = inp or _inputs()
    code = codes.EC2_2005_DKNA
    link_dia = 10.0
    link_spacing = 150.0
    link_legs = 2.0
    fywk = 500.0
    fywd = fywk / 1.15
    capacity_material = inp["mild_materials"][
        inp["capacity_steel_material_id"]
    ]
    fyd_long = capacity_material.fytk / capacity_material.gamma_y
    fcd = 30.0 / 1.5
    gamma_ct = float(inp["torsion_gamma_ct"])
    fctk_005 = 0.7 * codes.fctm(30.0)
    fctd = fctk_005 / gamma_ct
    shear_z_mm = 243.0
    link_asw = link_legs * math.pi * link_dia ** 2 / 4.0
    link_asw_over_s = link_asw / link_spacing
    torsion_asw = math.pi * link_dia ** 2 / 4.0
    torsion_asw_over_s = torsion_asw / link_spacing
    tube = torsion.tube_properties(
        inp["outer"], inp.get("holes"), inp.get("torsion_tef", 0.0)
    )
    shear_res = shear.vrd_c(
        30.0, code, bw_mm=200.0, d_mm=270.0,
        asl_mm2=500.0, n_ed_comp_kn=0.0, ac_m2=0.06, gamma_c=1.5,
    )

    @functools.lru_cache(maxsize=4096)
    def link_at(cot: float) -> dict:
        return shear.vrd_links(
            30.0, code, bw_mm=200.0, d_mm=270.0,
            asw_over_s=link_asw_over_s, fywk=fywk,
            n_ed_comp_kn=0.0, ac_m2=0.06,
            cot_min=cot, cot_max=cot, z_mm=shear_z_mm,
            fcd_mpa=fcd, gamma_s=1.15,
        )

    @functools.lru_cache(maxsize=4096)
    def torsion_at(cot: float) -> dict:
        return capacity.tube_torsion(
            tube, 25.0, tcode=code, fck=30.0, fcd=fcd, alpha_cw=1.0,
            fywd=fywd, asw_over_s=torsion_asw_over_s,
            cot_min=cot, cot_max=cot, nu_detail=False,
            fctd=fctd, fyd_long=fyd_long,
        )

    def longitudinal_at(cot: float) -> dict:
        torsion_result = torsion_at(cot)
        ftd_t_cot = torsion_result["asl_req"] * fyd_long / 1000.0
        return combined.longitudinal_check(
            80.0, 100.0, 0.5 * 30.0 * cot, ftd_t_cot,
            shear_z_mm / 1000.0,
        )

    angle_utilisations = [
        lambda cot: combined.ratio(30.0, link_at(cot)["vrd_s"]),
        lambda cot: combined.ratio(30.0, link_at(cot)["vrd_max"]),
        lambda cot: torsion_at(cot)["util"],
        lambda cot: combined.ratio(25.0, torsion_at(cot)["trd_s"]),
        lambda cot: combined.crushing_interaction(
            25.0, torsion_at(cot)["trd_max"],
            30.0, link_at(cot)["vrd_max"],
        ),
        lambda cot: longitudinal_at(cot)["util"],
        lambda cot: combined.dkna_sum(
            0.80,
            combined.ratio(30.0, link_at(cot)["vrd"]),
            torsion_at(cot)["util"],
            m_v_independent=False,
        ),
    ]
    member_cot, _ = combined.governing_strut_cot(
        angle_utilisations, 1.0, 2.5,
    )
    plastic = {
        "mx": [100.0, 0.0, -100.0, 0.0],
        "my": [0.0, 100.0, 0.0, -100.0],
        "max_mx": 100.0,
        "max_my": 100.0,
        "min_mx": -100.0,
        "min_my": -100.0,
        "util": 0.8,
        "closed": True,
        "check_util": True,
        "applied": (80.0, 0.0),
        "converged": True,
        "worked_point_index": 0,
        "worked_point_basis": "utilisation direction",
        "points": [_plastic_point()],
    }
    elastic = {
        "total": [150.0],
        "long": [120.0],
        "dif": [30.0],
        "rst1": [0.0],
        "max_conc": 12.0,
        "max_conc_xy": (0.0, 0.15),
        "max_conc_point": 4,
        "na_x": 0.0,
        "na_y": 0.04,
        "max_steel": 150.0,
        "max_steel_bar": 1,
        "max_steel_element": "bar 1",
        "converged": True,
        "cracked": True,
        "lambda_cr": 0.4,
        "sigma_ct": 7.2,
        "fctm": 2.9,
        "show_cw": True,
        "stress_plane": (-12000.0, 0.0, 80000.0),
        "elements": [{
            "element_type": "Bar",
            "element_no": 1,
            "element_id": "bar 1",
            "x_mm": 0.0,
            "y_mm": -120.0,
            "area_mm2": 500.0,
            "strain_permille": 0.75,
            "total_mpa": 150.0,
            "long_mpa": 120.0,
            "dif_mpa": 30.0,
            "rst1_mpa": 0.0,
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
        "props_un": {
            "area": 0.06,
            "cx": 0.0,
            "cy": 0.0,
            "Ix": 4.5e-4,
            "Iy": 2.0e-4,
            "Ixy": 0.0,
        },
        "props_cr": {
            "area": 0.03,
            "cx": 0.0,
            "cy": 0.02,
            "Ix": 2.1e-4,
            "Iy": 1.0e-4,
            "Ixy": 0.0,
        },
        "crack": _crack(),
        "crack_short": _crack(),
        "crack_output": {
            "value": 0.213,
            "case": "Long-term",
            "governing": "bar 1",
            "unit": "mm",
            "calculation_state": "CALCULATED",
        },
        "crack_code": "EN 1992-1-1:2005",
        "crack_member": None,
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
        },
    }
    shear_payload = {
        "res": shear_res,
        "v_ed": 30.0,
        "util": 30.0 / shear_res["vrd_c"],
        "axis": "x",
        "tension_low": True,
        "bw": 200.0,
        "bw_auto": 200.0,
        "bw_user": False,
        "d": 270.0,
        "asl": 500.0,
        "asl_bar_ids": [1],
        "asl_cg": -0.12,
        "ac": 0.06,
        "fck": 30.0,
        "n_ed": 0.0,
        "n_prestress": 0.0,
        "centroid": (0.0, 0.0),
        "method": code.label,
        "model_2023": False,
    }
    link_resistance = link_at(member_cot)
    shear_payload["links"] = {
        "res": link_resistance,
        "util": 30.0 / link_resistance["vrd"],
        "asw": link_asw,
        "asw_over_s": link_asw_over_s,
        "legs": link_legs,
        "dia": link_dia,
        "s": link_spacing,
        "fywk": fywk,
        "cot_min": 1.0,
        "cot_max": 2.5,
        "delta_ftd": 0.5 * 30.0 * member_cot,
        "longitudinal_shear_force": 0.5 * 30.0 * member_cot,
        "cot_limit_lo": 1.0,
        "cot_limit_hi": 2.5,
        "z_source": "plastic internal lever arm",
        "out_of_limits": False,
        "required": bool(30.0 > shear_res["vrd_c"]),
        "theta_mode": "utilisation",
        "chord": None,
        "chord_off": None,
    }
    primary_torsion = torsion_at(member_cot)
    interaction = {
        "valid": True,
        "cot": member_cot,
        "theta_deg": primary_torsion["theta_deg"],
        "trd_max": primary_torsion["trd_max"],
        "vrd_max": link_resistance["vrd_max"],
        "t_ed": 25.0,
        "v_ed": 30.0,
        "value": combined.crushing_interaction(
            25.0, primary_torsion["trd_max"],
            30.0, link_resistance["vrd_max"],
        ),
    }
    minimum_interaction = (
        25.0 / primary_torsion["trd_c"]
        + 30.0 / shear_res["vrd_c"]
    )
    torsion_payload = {
        "tube": tube,
        "trd_s": primary_torsion["trd_s"],
        "trd_max": primary_torsion["trd_max"],
        "trd": primary_torsion["trd"],
        "trd_c": primary_torsion["trd_c"],
        "cot": primary_torsion["cot"],
        "theta_deg": primary_torsion["theta_deg"],
        "util": primary_torsion["util"],
        "asl_req": primary_torsion["asl_req"],
        "t_ed": 25.0,
        "fcd": fcd,
        "fywd": fywd,
        "fyd_long": fyd_long,
        "nu": primary_torsion["nu"],
        "alpha_cw": 1.0,
        "fctk_005": fctk_005,
        "gamma_ct": gamma_ct,
        "fctd": fctd,
        "asw_t": torsion_asw,
        "asw_over_s": torsion_asw_over_s,
        "dia": link_dia,
        "s": link_spacing,
        "cot_min": 1.0,
        "cot_max": 2.5,
        "method": code.label,
        "governs": primary_torsion["governs"],
        "valid": True,
        "cot_limit_lo": 1.0,
        "cot_limit_hi": 2.5,
        "out_of_limits": False,
        "subdivided": False,
        "theta_mode": "utilisation",
        "primary": primary_torsion,
        "subtubes": None,
        "interaction": interaction,
        "min_reinf": {
            "applicable": True,
            "value": minimum_interaction,
            "ok": bool(minimum_interaction <= 1.0),
            "t_ed": 25.0,
            "trd_c": primary_torsion["trd_c"],
            "v_ed": 30.0,
            "vrd_c": shear_res["vrd_c"],
            "solid": True,
            "model_2023": False,
        },
    }
    for retained_name in (
        "angle_selection",
        "steel_resistance",
        "strut_resistance",
        "resistance_selection",
        "cracking_resistance",
        "longitudinal_reinforcement",
    ):
        torsion_payload[retained_name] = primary_torsion[retained_name]
    shear_util = shear_payload["links"]["util"]
    torsion_util = torsion_payload["util"]
    shear_fraction = (
        0.0
        if 30.0 <= shear_res["vrd_c"]
        else 30.0 / link_resistance["vrd_s"]
    )
    torsion_stirrup_fraction = 25.0 / primary_torsion["trd_s"]
    stirrup_util = shear_fraction + torsion_stirrup_fraction
    ftd_t = primary_torsion["asl_req"] * fyd_long / 1000.0
    longitudinal = combined.longitudinal_check(
        80.0, plastic["max_mx"], shear_payload["links"]["delta_ftd"],
        ftd_t, shear_z_mm / 1000.0,
    )
    longitudinal.update(
        valid=True,
        axis="x",
        tension_low=True,
        biaxial=False,
        conditional=True,
        off_util=0.0,
        m_off=0.0,
        has_torsion=True,
        gets_shift=True,
        off_not_evaluated=None,
        theta_mode="utilisation",
    )
    dkna_selection = combined.dkna_interaction_result(
        plastic["util"], shear_util, torsion_util,
        m_v_independent=False,
    )
    combined_payload = {
        "valid": True,
        "method": code.label,
        "r_m": plastic["util"],
        "r_v": shear_util,
        "r_t": torsion_util,
        "m_v_independent": False,
        "dkna_sum": dkna_selection.utilisation,
        "dkna_ok": dkna_selection.ok,
        "dkna_selection": asdict(dkna_selection),
        "outside_default_range": False,
        "crushing": interaction,
        "transverse": {
            "valid": True,
            "cot": member_cot,
            "theta_deg": primary_torsion["theta_deg"],
            "u_stirrup": stirrup_util,
            "u_crush": interaction["value"],
            "governing": max(stirrup_util, interaction["value"]),
            "governs": (
                "crushing"
                if interaction["value"] > stirrup_util
                else "stirrups"
            ),
            "ok": bool(max(stirrup_util, interaction["value"]) <= 1.0),
            "shear_fraction": shear_fraction,
            "torsion_fraction": torsion_stirrup_fraction,
            "shear_credited": bool(shear_fraction == 0.0),
            "vrd_c": shear_res["vrd_c"],
            "v_ed": 30.0,
        },
        "longitudinal": longitudinal,
        "asl_torsion": primary_torsion["asl_req"],
        "delta_ftd": shear_payload["links"]["delta_ftd"],
        "links": True,
    }
    plastic_2 = copy.deepcopy(plastic)
    plastic_2.update(util=1.25, applied=(125.0, 0.0))
    elastic_2 = copy.deepcopy(elastic)
    elastic_2["show_cw"] = False
    elastic_2["max_steel"] = 245.0
    elastic_2["elements"][0]["total_mpa"] = 245.0
    elastic_2["stress_outputs"]["reinforcement"]["value"] = 245.0
    minimum = {
        "status": "PASS",
        "edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "member_type": detailing.MEMBER_BEAM,
        "cut_direction": detailing.CUT_TRANSVERSE,
        "modelled_reinforcement_direction": "longitudinal",
        "clause": "9.2.1.1(1), Formula (9.1N)",
        "checks": [{
            "type": "minimum area", "status": "PASS",
            "axis": "x", "face": "bottom",
            "as_provided_mm2": 500.0, "as_min_mm2": 320.0,
            "utilisation": 0.64, "bt_mm": 200.0, "d_mm": 270.0,
            "fctm_mpa": 2.9, "fyk_mpa": 500.0, "bar_ids": ["R1"],
            "tension_direction": [0.0, -1.0], "neutral_c_m": 0.0,
            "neutral_point_m": [0.0, 0.0],
            "model": "gross-concrete resultant tension half-plane",
        }],
        "limitations": [
            "Prestressing tendons are not credited.",
            "Ordinary reinforcement is assumed anchored to develop the entered fyk.",
        ],
    }
    spacing_pair = {
        "status": "PASS", "first_id": "R1", "second_id": "R2",
        "first_kind": "bar", "second_kind": "bar", "clear_mm": 216.1,
        "required_mm": 25.23, "margin_mm": 190.87,
        "centre_distance_mm": 240.0, "phi_first_mm": 25.23,
        "phi_second_mm": 22.57,
    }
    spacing = {
        "status": "PASS",
        "edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "clause": "8.2(2)", "d_upper_mm": 16.0,
        "include_tendons": False, "pairs": [spacing_pair],
        "governing": spacing_pair, "reason": None,
        "limitations": ["Pairwise edge-to-edge distance is checked."],
    }
    transverse_detailing = detailing.transverse_reinforcement(
        edition=inp["detailing_edition"],
        fck_mpa=inp["concrete"].fck,
        fywk_mpa=fywk,
        diameter_mm=link_dia,
        spacing_mm=link_spacing,
        member_type=inp["detailing_member_type"],
        shear_directions=[{
            "component": "vy",
            "bw_mm": shear_payload["bw"],
            "d_mm": shear_payload["d"],
            "legs": link_legs,
            "transverse_leg_spacing_mm": 0.0,
            "measurement_axis": "x",
        }],
        torsion_tubes=[{
            "label": "Tube",
            "valid": tube["valid"],
            "reason": tube.get("reason"),
            "tef_mm": tube["tef"],
            "uk_mm": tube["uk"] * 1000.0,
            "minimum_dimension_mm": tube["minimum_dimension_mm"],
        }],
    )
    inputs = _inputs()
    plastic_rows = case_analysis.case_records(inputs, "plastic")
    elastic_rows = case_analysis.case_records(inputs, "elastic")
    fatigue = fatigue_analysis.run_analysis(inputs)
    material_properties = {
        "concrete": {
            "variant": "2005",
            "characteristic_strength_mpa": inp["concrete"].fck,
            "strength_factor": inp["concrete"].alpha_cc,
            "partial_factor": inp["concrete"].gamma_c,
            "eta_cc": inp.get("concrete_eta_cc"),
            "k_tc": inp.get("concrete_k_tc"),
            "design_strength_mpa": inp["concrete"].fcd,
        },
        "mild": [
            {
                "material_id": material_id,
                "characteristic_yield_mpa": material.fytk,
                "yield_factor": material.gamma_y,
                "design_yield_mpa": capacity.design_yield(material),
            }
            for material_id, material in inp["mild_materials"].items()
        ],
        "prestress": [],
    }
    out = {
        "material_properties": material_properties,
        "plastic": plastic,
        "elastic": elastic,
        "fatigue": fatigue,
        "shear": shear_payload,
        "torsion": torsion_payload,
        "combined": combined_payload,
        "transverse_reinforcement": transverse_detailing,
        "clear_spacing": spacing,
        "plastic_cases": [
            {"name": "PL-QA-1", "actions": plastic_rows[0], "evaluated": True,
             "signature": case_analysis.case_signature(
                 plastic_rows[0], load_cases.PLASTIC_TABLE_KEY),
             "results": {
                 "plastic": plastic, "shear": shear_payload,
                 "torsion": torsion_payload,
                 "combined": combined_payload,
                 "minimum_reinforcement": minimum,
                 "transverse_reinforcement": transverse_detailing,
             }},
            {"name": "PL-QA-2", "actions": plastic_rows[1], "evaluated": True,
             "signature": case_analysis.case_signature(
                 plastic_rows[1], load_cases.PLASTIC_TABLE_KEY),
             "results": {"plastic": plastic_2}},
        ],
        "elastic_cases": [
            {"name": "EL-QA-1", "actions": elastic_rows[0], "evaluated": True,
             "signature": case_analysis.case_signature(
                 elastic_rows[0], load_cases.ELASTIC_TABLE_KEY),
             "results": {"elastic": elastic}},
            {"name": "EL-QA-2", "actions": elastic_rows[1], "evaluated": True,
             "signature": case_analysis.case_signature(
                 elastic_rows[1], load_cases.ELASTIC_TABLE_KEY),
             "results": {"elastic": elastic_2}},
        ],
    }
    return out


def validate_fixture_engineering(inp: dict, out: dict) -> None:
    """Prove that the report fixture's displayed operands reproduce its results."""

    def close(label: str, actual: float, expected: float) -> None:
        if not math.isclose(actual, expected, rel_tol=1.0e-10, abs_tol=1.0e-10):
            raise AssertionError(
                f"inconsistent fixture {label}: {actual!r} != {expected!r}"
            )

    retained_materials = out["material_properties"]
    close(
        "concrete design strength",
        retained_materials["concrete"]["design_strength_mpa"],
        inp["concrete"].fcd,
    )
    retained_mild = {
        row["material_id"]: row for row in retained_materials["mild"]
    }
    for material_id, material in inp["mild_materials"].items():
        close(
            f"{material_id} design yield",
            retained_mild[material_id]["design_yield_mpa"],
            capacity.design_yield(material),
        )

    plastic_worked = out["plastic_cases"][1]["results"]["plastic"]
    worked_index = plastic_worked.get("worked_point_index")
    if worked_index != 0:
        raise AssertionError("the governing plastic worked-point identity is missing")
    point = plastic_worked["points"][worked_index]
    close(
        "plastic axial equilibrium",
        point["axial_achieved"],
        point["concrete_force"] + point["bar_force"] + point["tendon_force"],
    )
    close(
        "plastic Mx equilibrium",
        point["Mx"],
        point["concrete_mx"] + point["bar_mx"] + point["tendon_mx"],
    )
    for state_kind in ("concrete_corner_states", "reinforcement_states"):
        state = point[state_kind][0]
        retained_plane_strain = (
            point["strain_offset"]
            + point["strain_gradient_x"] * state["x_mm"] / 1000.0
            + point["strain_gradient_y"] * state["y_mm"] / 1000.0
        )
        close(
            f"plastic {state_kind} strain plane",
            state["section_strain_permille"] / 1000.0,
            retained_plane_strain,
        )
        close(
            f"plastic {state_kind} material strain sign",
            state["strain_permille"],
            -state["section_strain_permille"],
        )
    close(
        "plastic reported concrete strain",
        point["eps_c"] * 10.0,
        point["concrete_corner_states"][0]["section_strain_permille"],
    )
    close(
        "plastic reported tensile strain",
        point["eps_s"] * 10.0,
        point["reinforcement_states"][0]["strain_permille"],
    )
    selected_curvature = point["curvature_selection"]["curvature_per_m"]
    curvature_candidate = next(
        row for row in point["curvature_candidates"] if row["selected"]
    )
    close(
        "plastic curvature candidate",
        curvature_candidate["curvature_per_m"],
        curvature_candidate["strain_limit"]
        / curvature_candidate["distance_from_na_m"],
    )
    close("plastic curvature selection", selected_curvature, point["kappa"])

    elastic_worked = out["elastic_cases"][1]["results"]["elastic"]
    superposition = elastic_worked["superposition"]
    close(
        "elastic modular-ratio reduction",
        superposition["long_term_reduction_factor"],
        1.0
        - superposition["short_term_modular_ratio"]
        / superposition["long_term_modular_ratio"],
    )
    element = elastic_worked["elements"][0]
    close(
        "elastic reduced long-term stress",
        element["reduced_long_mpa"],
        element["long_passive_mpa"]
        * superposition["long_term_reduction_factor"],
    )
    neutralising = superposition["neutralising_resultant"]
    close(
        "elastic neutralising axial force",
        neutralising["n"],
        element["reduced_long_mpa"] * element["area_mm2"] / 1000.0,
    )
    close(
        "elastic neutralising Mx",
        neutralising["mx"],
        element["reduced_long_mpa"]
        * element["area_mm2"]
        * element["y_mm"]
        / 1_000_000.0,
    )
    for name, state in elastic_worked["accepted_states"].items():
        equilibrium = state["equilibrium"]
        for resultant in ("n", "mx", "my"):
            close(
                f"elastic {name} {resultant} residual",
                equilibrium["residual"][resultant],
                equilibrium["internal"][resultant]
                - equilibrium["target"][resultant],
            )

    crack = out["elastic_cases"][0]["results"]["elastic"]["crack"]
    candidate = crack["governing_candidate"]
    spacing = candidate["spacing_operands"]
    mean = candidate["mean_strain_operands"]
    close(
        "crack effective reinforcement ratio",
        candidate["rho_p_eff"],
        candidate["as_eff"] / candidate["ac_eff"],
    )
    close(
        "crack spacing Formula (7.11)",
        spacing["selected_spacing"],
        spacing["k3_used"] * spacing["cover"]
        + spacing["k1"]
        * spacing["k2"]
        * spacing["k4"]
        * spacing["diameter"]
        / spacing["rho_p_eff"],
    )
    close(
        "crack mean-strain formula candidate",
        mean["formula_candidate"],
        (mean["sigma_s"] - mean["concrete_tension_reduction"]) / mean["es"],
    )
    close(
        "crack width",
        crack["wk"],
        spacing["selected_spacing"] * mean["selected_esm_ecm"],
    )

    case = next(
        row for row in inp["plastic_cases"] if row["name"] == "PL-QA-1"
    )
    if not (
        inp["shear_on"]
        and inp["shear_links"]
        and inp["torsion_on"]
        and inp["combined_on"]
    ):
        raise AssertionError("the complete fixture checks are not enabled")

    shear_out = out["shear"]
    links = shear_out["links"]
    lk = links["res"]
    close("VEd", shear_out["v_ed"], case["v_ed_kn"])
    close(
        "VRd,s",
        lk["vrd_s"],
        links["asw_over_s"] * lk["z"] * lk["fywd"] * lk["cot"] / 1000.0,
    )
    close(
        "VRd,max",
        lk["vrd_max"],
        (
            lk["alpha_cw"]
            * shear_out["bw"]
            * lk["z"]
            * lk["nu1"]
            * lk["fcd"]
            / (lk["cot"] + 1.0 / lk["cot"])
            / 1000.0
        ),
    )
    close("shear utilisation", links["util"], shear_out["v_ed"] / lk["vrd"])

    torsion_out = out["torsion"]
    tube = torsion_out["tube"]
    expected_tube = torsion.tube_properties(
        inp["outer"], inp.get("holes"), inp.get("torsion_tef", 0.0)
    )
    for key in ("A", "u", "tef", "Ak", "uk"):
        close(f"torsion tube {key}", tube[key], expected_tube[key])
    capacity_material = inp["mild_materials"][
        inp["capacity_steel_material_id"]
    ]
    expected_fyd_long = capacity_material.fytk / capacity_material.gamma_y
    close("torsion longitudinal design strength", torsion_out["fyd_long"],
          expected_fyd_long)
    close(
        "torsion tensile factor",
        torsion_out["gamma_ct"],
        inp["torsion_gamma_ct"],
    )
    close(
        "torsion design tensile strength",
        torsion_out["fctd"],
        torsion_out["fctk_005"] / torsion_out["gamma_ct"],
    )
    close("TEd", torsion_out["t_ed"], case["t_ed_knm"])
    close(
        "TRd,s",
        torsion_out["trd_s"],
        torsion.trd_s(
            tube["Ak"], torsion_out["fywd"],
            torsion_out["asw_over_s"], torsion_out["cot"],
        ),
    )
    close(
        "TRd,max",
        torsion_out["trd_max"],
        torsion.trd_max(
            30.0, codes.EC2_2005_DKNA, tube["Ak"], tube["tef"],
            torsion_out["alpha_cw"], torsion_out["cot"],
            fcd_mpa=torsion_out["fcd"],
        ),
    )
    close(
        "TRd,c",
        torsion_out["trd_c"],
        torsion.trd_c(torsion_out["fctd"], tube["Ak"], tube["tef"]),
    )
    close(
        "torsion longitudinal area",
        torsion_out["asl_req"],
        torsion.asl_required(
            torsion_out["t_ed"], tube["uk"], tube["Ak"],
            torsion_out["fyd_long"], torsion_out["cot"],
        ),
    )
    close(
        "torsion utilisation",
        torsion_out["util"],
        torsion_out["t_ed"] / torsion_out["trd"],
    )

    detailing_out = out["transverse_reinforcement"]
    detailing_checks = {
        (check["scope"], check["kind"]): check
        for check in detailing_out["checks"]
    }
    leg_area = math.pi * inp["shear_link_dia"] ** 2 / 4.0
    shear_ratio = detailing_checks[("Shear VY", "minimum_ratio")]
    close(
        "shear detailing ratio",
        shear_ratio["provided"],
        2.0 * leg_area / (
            inp["shear_link_s"] * shear_out["bw"]
        ),
    )
    close(
        "shear longitudinal spacing limit",
        detailing_checks[("Shear VY", "longitudinal_spacing")]["limit"],
        0.75 * shear_out["d"],
    )
    close(
        "shear transverse leg spacing",
        detailing_checks[("Shear VY", "transverse_leg_spacing")]["provided"],
        shear_out["bw"],
    )
    torsion_ratio = detailing_checks[("Torsion Tube", "minimum_ratio")]
    close(
        "torsion detailing ratio",
        torsion_ratio["provided"],
        leg_area / (inp["shear_link_s"] * tube["tef"]),
    )
    torsion_spacing = detailing_checks[("Torsion Tube", "torsion_spacing")]
    close(
        "torsion detailing spacing limit",
        torsion_spacing["limit"],
        min(
            tube["uk"] * 1000.0 / 8.0,
            tube["minimum_dimension_mm"],
        ),
    )

    result = out["combined"]
    close(
        "concrete interaction",
        result["crushing"]["value"],
        combined.crushing_interaction(
            torsion_out["t_ed"], torsion_out["trd_max"],
            shear_out["v_ed"], lk["vrd_max"],
        ),
    )
    close(
        "combined utilisation",
        result["dkna_sum"],
        combined.dkna_sum(
            result["r_m"], result["r_v"], result["r_t"],
            m_v_independent=result["m_v_independent"],
        ),
    )

    @functools.lru_cache(maxsize=4096)
    def link_at(cot: float) -> dict:
        return shear.vrd_links(
            shear_out["fck"], codes.EC2_2005_DKNA,
            bw_mm=shear_out["bw"], d_mm=shear_out["d"],
            asw_over_s=links["asw_over_s"], fywk=links["fywk"],
            n_ed_comp_kn=0.0, ac_m2=shear_out["ac"],
            cot_min=cot, cot_max=cot, z_mm=lk["z"],
            fcd_mpa=lk["fcd"], gamma_s=lk["gamma_s"],
        )

    @functools.lru_cache(maxsize=4096)
    def torsion_at(cot: float) -> dict:
        return capacity.tube_torsion(
            tube, torsion_out["t_ed"], tcode=codes.EC2_2005_DKNA,
            fck=shear_out["fck"], fcd=torsion_out["fcd"],
            alpha_cw=torsion_out["alpha_cw"], fywd=torsion_out["fywd"],
            asw_over_s=torsion_out["asw_over_s"],
            cot_min=cot, cot_max=cot, nu_detail=False,
            fctd=torsion_out["fctd"], fyd_long=expected_fyd_long,
        )

    def longitudinal_util(cot: float) -> float:
        torsion_result = torsion_at(cot)
        ftd_t_cot = (
            torsion_result["asl_req"] * torsion_out["fyd_long"] / 1000.0
        )
        return combined.longitudinal_check(
            result["longitudinal"]["m_ed"],
            result["longitudinal"]["m_rd"],
            0.5 * shear_out["v_ed"] * cot,
            ftd_t_cot,
            result["longitudinal"]["z"],
        )["util"]

    member_cot, _ = combined.governing_strut_cot(
        [
            lambda cot: combined.ratio(
                shear_out["v_ed"], link_at(cot)["vrd_s"]
            ),
            lambda cot: combined.ratio(
                shear_out["v_ed"], link_at(cot)["vrd_max"]
            ),
            lambda cot: torsion_at(cot)["util"],
            lambda cot: combined.ratio(
                torsion_out["t_ed"], torsion_at(cot)["trd_s"]
            ),
            lambda cot: combined.crushing_interaction(
                torsion_out["t_ed"], torsion_at(cot)["trd_max"],
                shear_out["v_ed"], link_at(cot)["vrd_max"],
            ),
            longitudinal_util,
            lambda cot: combined.dkna_sum(
                result["r_m"],
                combined.ratio(shear_out["v_ed"], link_at(cot)["vrd"]),
                torsion_at(cot)["util"],
                m_v_independent=result["m_v_independent"],
            ),
        ],
        links["cot_min"],
        links["cot_max"],
    )
    close("shared member cotangent", lk["cot"], member_cot)
    close("torsion member cotangent", torsion_out["cot"], member_cot)
    close(
        "longitudinal lever arm",
        result["longitudinal"]["z"],
        lk["z"] / 1000.0,
    )

    expected_longitudinal = combined.longitudinal_check(
        result["longitudinal"]["m_ed"],
        result["longitudinal"]["m_rd"],
        links["delta_ftd"],
        torsion_out["asl_req"] * torsion_out["fyd_long"] / 1000.0,
        result["longitudinal"]["z"],
    )
    for key in ("ftd_v", "ftd_t", "mv", "mt", "m_total", "util"):
        close(
            f"longitudinal {key}",
            result["longitudinal"][key],
            expected_longitudinal[key],
        )


@functools.lru_cache(maxsize=2)
def build_fixture_pdf(*, figures: bool = True) -> bytes:
    """Build the report with stable time and an optional figure-export path."""
    original_datetime = sector_report.datetime.datetime
    sector_report.datetime.datetime = _FixedDateTime
    try:
        inp = _inputs()
        out = _results(inp)
        validate_fixture_engineering(inp, out)
        out["worked_example_selection"] = (
            result_presentation.worked_example_selection(inp, out)
        )
        return sector_report.build_report(
            {
                "proj_no": "QA-REFERENCE",
                "proj_name": "Rendered report regression",
                "section": "Reference section",
                "author": "Sector QA",
                "source_revision": "fixture000000000000000000000000000000000",
            },
            inp,
            out,
            version=__version__,
            figures=figures,
        )
    finally:
        sector_report.datetime.datetime = original_datetime


def validate_worked_example_text(text: str) -> None:
    """Reject missing or fail-closed governing textbook calculation chains."""
    unavailable = re.search(
        r"\bworked\b[\s\S]{0,180}?\bunavailable\b",
        text,
        flags=re.IGNORECASE,
    )
    if unavailable:
        raise AssertionError(
            "the report contains an unavailable worked-example placeholder: "
            + " ".join(unavailable.group(0).split())
        )
    flat_text = " ".join(text.split())
    for expected in (
        _EXPECTED_PLASTIC_WORKED_HEADING,
        "Accepted strain plane",
        "Ultimate-curvature candidates",
        "Step 1 - accepted long-term state",
        "Step 2 - neutralise the long-term concrete stress",
        "Step 3 - accepted instantaneous combined state",
        "Crack width worked - governing case",
        "Formula (7.11) selected",
    ):
        if expected not in text and expected not in flat_text:
            raise AssertionError(
                f"the governing worked calculation is incomplete: {expected}"
            )


def validate_pdf_content(
    pdf: bytes,
    *,
    expected_figure_count: int = _EXPECTED_FIGURE_COUNT,
) -> str:
    """Reject a report that lost expected figures or core engineering content."""
    reader, page_texts = preflight_pdf(pdf, min_pages=6)
    text = "\n".join(page_texts)
    if "figure unavailable" in text.lower():
        raise AssertionError("the report contains an unavailable-figure placeholder")
    validate_worked_example_text(text)
    # Plain ``sqrt(...)`` and ``sum(...)`` are intentional solver-owned symbolic
    # relations. Continue rejecting actual LaTeX/layout leaks.
    for token in (
        "Cfrac", "Big", "sincos", "delta eps",
        "varepsilon", "qquadk", "quadf", "kN.m",
    ):
        if token.casefold() in text.casefold():
            raise AssertionError(
                f"the report exposes an unrendered mathematics token: {token}"
            )
    for symbol in (chr(0x00B0), chr(0x00B7), chr(0x03B2)):
        if symbol not in text:
            raise AssertionError(
                f"the report is missing rendered mathematics symbol U+{ord(symbol):04X}"
            )

    images = 0
    for page in reader.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        xobjects = resources.get_object().get("/XObject")
        if xobjects is None:
            continue
        for reference in xobjects.get_object().values():
            if reference.get_object().get("/Subtype") == "/Image":
                images += 1
    if images != expected_figure_count:
        raise AssertionError(
            f"expected {expected_figure_count} exported engineering figures, "
            f"found {images}"
        )

    outlines = validate_outline_destinations(reader)
    if len(outlines) < 6:
        raise AssertionError(
            f"expected navigable section bookmarks, found {len(outlines)}"
        )

    for number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        if "Project: QA-REFERENCE" not in page_text:
            raise AssertionError(
                f"page {number} is missing the repeated project/section header"
            )

    concrete_page = next(
        (page.extract_text() or "" for page in reader.pages
         if "Characteristic strength" in (page.extract_text() or "")),
        "",
    )
    if "= 20.000 MPa" not in concrete_page:
        raise AssertionError("the concrete worked formula is split across pages")

    governing_page = next(
        (page.extract_text() or "" for page in reader.pages
         if _EXPECTED_PLASTIC_WORKED_HEADING in (page.extract_text() or "")),
        "",
    )
    if "NA intercepts" not in governing_page:
        raise AssertionError("the governing-case heading is separated from its table")

    existing_material_page = next(
        (page.extract_text() or "" for page in reader.pages
         if "Verified from archive test certificate" in (page.extract_text() or "")),
        "",
    )
    if not all(value in existing_material_page for value in (
        "Yield partial factor", "Design yield", "= 195.833 MPa"
    )):
        raise AssertionError(
            "a material heading/provenance is separated from its definition"
        )

    settings_page = next(
        (page.extract_text() or "" for page in reader.pages
         if "Analysis settings" in (page.extract_text() or "")),
        "",
    )
    if "Sweep start" not in settings_page:
        raise AssertionError("the analysis-settings heading is separated from its table")
    for heading, first_case in (
        ("Plastic / capacity cases", "PL-QA-1"),
        ("Elastic cases", "EL-QA-1"),
        ("Grouped fatigue spectra", "FAT-QA-H"),
    ):
        page_text = next(
            (
                page.extract_text() or ""
                for page in reader.pages
                if heading in (page.extract_text() or "")
            ),
            "",
        )
        if first_case not in page_text:
            raise AssertionError(
                f"the {heading} heading is separated from its first row"
            )

    flat_text = " ".join(text.split())
    for expected in (
        "QA-REFERENCE",
        "Sweco Danmark A/S",
        "Rendered report regression",
        "Results overview",
        "Governing combination",
        "M1 New B500 reinforcement",
        "M2 Existing reinforcement",
        "Verified from archive test certificate",
        "R1 M1",
        "R2 M2",
        "Vx,Ed = 0",
        "Vy,Ed = 0",
        "Plastic section capacity - PL-QA-2",
        _EXPECTED_PLASTIC_WORKED_HEADING,
        "Accepted strain plane",
        "Ultimate-curvature candidates",
        "Longitudinal minimum reinforcement - PL-QA-1",
        "Shear/torsion link detailing - PL-QA-1",
        "Closed-link spacing",
        "Reinforcement clear spacing",
        "R1 - R2",
        "Elastic section response and stresses - EL-QA-2",
        "Step 1 - accepted long-term state",
        "Step 2 - neutralise the long-term concrete stress",
        "Step 3 - accepted instantaneous combined state",
        "Cracking threshold and governing crack width - EL-QA-1",
        "Crack width worked - governing case",
        "Formula (7.11) selected",
        "Grouped fatigue",
        "Road traffic",
        "FAT-QA-H",
        "FAT-QA-M",
        "QA traffic spectrum REF-FAT-01",
        "Spectrum summary",
        "Reinforcement fatigue",
        "Concrete fatigue",
        "Textbook calculation - governing reinforcement fatigue",
        "Textbook calculation - governing concrete fatigue",
        "Bounded governing-fibre search",
        "DS/EN 1992-2:2005/AC:2008",
        "6.106",
        "Torsion and shear fatigue are not assessed",
        "Physical resistance components",
        "Concrete compression strut",
        "Closed stirrup",
        "Longitudinal reinforcement",
        "Torsion (thin-walled tube)",
        "Concrete tensile factor",
        "125.0 %",
        "245.000 MPa",
        "Candidate summary for governing crack example",
        f"Generated 2026-07-19 12:00 by Sector {__version__}",
    ):
        if expected not in text and expected not in flat_text:
            raise AssertionError(f"expected report content is missing: {expected}")

    for removed in (
        "Independent bridge calculations",
        "Optional brittle Method B",
        "Box-wall shear and torsion",
        "Web/flange minimum crack reinforcement",
        "DS/EN 1992-2:2005 6.1(109)-(110)",
    ):
        if removed in text or removed in flat_text:
            raise AssertionError(
                f"removed component-mapped bridge content remains: {removed}"
            )

    validate_report_page_semantics(page_texts)
    overview_pages = [
        number
        for number, page_text in enumerate(page_texts, start=1)
        if "Results overview across calculated checks" in page_text
    ]
    governing_note_pages = [
        number
        for number, page_text in enumerate(page_texts, start=1)
        if "Gov. marks the highest PASS/FAIL utilisation" in page_text
    ]
    if overview_pages != governing_note_pages or len(overview_pages) != 1:
        raise AssertionError(
            "the stable results overview no longer fits one complete page"
        )
    return text


def validate_report_page_semantics(page_texts: list[str]) -> None:
    """Reject a report page containing only repeated document furniture."""
    footer_prefix = f"Sector {__version__} - "
    for number, page_text in enumerate(page_texts, start=1):
        semantic_lines = []
        for raw_line in page_text.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            if line.startswith("Project: QA-REFERENCE"):
                continue
            if line.startswith("Rev: "):
                continue
            if line.startswith(footer_prefix):
                continue
            if re.fullmatch(r"Page \d+ of \d+", line):
                continue
            semantic_lines.append(line)
        if not semantic_lines:
            raise AssertionError(
                f"page {number} contains document furniture but no report body"
            )


def validate_rendered_pages(
    pages, *, require_document_control=False, furniture=None, min_pages=6
):
    """Retain the fixture API while delegating to the shared raster gate."""
    if require_document_control and furniture is None:
        furniture = REPORT_FURNITURE
    return validate_raster_pages(
        pages, min_pages=min_pages, furniture=furniture
    )


def write_fixture(output: pathlib.Path) -> list[pathlib.Path]:
    """Write the stable PDF and rendered page PNG evidence."""
    output.mkdir(parents=True, exist_ok=True)
    pdf = build_fixture_pdf()
    validate_pdf_content(pdf)
    pdf_path = output / "sector-report-reference.pdf"
    pdf_path.write_bytes(pdf)
    pages = render_pdf(pdf)
    validate_rendered_pages(
        pages, min_pages=6, furniture=REPORT_FURNITURE
    )
    validate_crops(pages, _REPORT_CROPS)
    paths = [pdf_path]
    for index, page in enumerate(pages, start=1):
        path = output / f"sector-report-page-{index:02d}.png"
        page.save(path, format="PNG")
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    paths = write_fixture(args.output)
    print(f"Rendered {len(paths) - 1} report pages to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
