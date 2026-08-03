"""Current-schema PR-09 worked project and its independent hand-check oracle.

The project text is assembled from original user inputs only.  It contains no
result payload; loading it follows the ordinary project parser and calculating it
follows the ordinary app orchestration.  ``ORACLE`` is deliberately literal and
must never be generated from a candidate result object.
"""

from __future__ import annotations

import functools

import pandas as pd

import bridge_inputs
import fatigue_inputs
import load_cases
import material_catalog
import project_io
import reinforcement_table
from sector import __version__ as sector_version
from sector import bridge, codes, detailing
from sector.build_info import source_revision


EXAMPLE_NAME = "Sector 0.91 complete worked beam"
PROJECT_FILENAME = "Sector_0.91_complete_worked_example.json"
HAND_PACK_FILENAME = "Sector_0.91_complete_worked_example_hand_pack.md"
METHOD = codes.EC2_2005_DKNA.label
BRIDGE_METHOD = bridge.EN1992_2_DK_NA


# Frozen independently from the result returned by the downloadable project.
# Values are unrounded binary-float outputs.  The focused test also reconstructs
# representative formulae from the original inputs rather than trusting these
# literals alone.
ORACLE = {
    "sector_version": "0.91",
    "project_schema": 23,
    "section": {
        "width_mm": 300.0,
        "height_mm": 600.0,
        "gross_area_m2": 0.18,
        "bar_ids": ("R1", "R2", "R3", "R4", "R5"),
        "material_id": "M1",
        "preset": METHOD,
    },
    "methods": {
        "plastic": "80-band strain compatibility; reachable axial bisection",
        "elastic": "cracked transformed section; residual infinity norm",
        "fatigue": "DS/EN 1992-1-1:2005 + DK NA:2024 grouped spectrum",
        "shear": METHOD,
        "torsion": METHOD,
        "combined": METHOD,
        "bridge": BRIDGE_METHOD,
    },
    "families": (
        "plastic_cases",
        "elastic_cases",
        "fatigue",
        "clear_spacing",
        "bridge",
    ),
    "values": {
        "plastic.utilisation": 0.8671106620666015,
        "plastic.max_mx_knm": 345.97660151589446,
        "plastic.axial_residual_kn": -2.0849029169767164e-09,
        "elastic.max_concrete_compression_mpa": 9.861986019524323,
        "elastic.short_crack_width_mm": 0.16762742388253854,
        "fatigue.utilisation": 0.28790016682927444,
        "shear.utilisation": 0.38145424977941156,
        "torsion.utilisation": 0.30035714285714293,
        "combined.utilisation": 1.548922054703156,
        "bridge.brittle_required_area_mm2": 2500.0,
    },
    "states": {
        "plastic.converged": True,
        "elastic.converged": True,
        "fatigue.converged": True,
        "clear_spacing.status": "PASS",
    },
}


def _geometry_tables() -> dict:
    corners = pd.DataFrame({
        "x (mm)": [-150.0, 150.0, 150.0, -150.0],
        "y (mm)": [-300.0, -300.0, 300.0, 300.0],
    })
    holes = pd.DataFrame(columns=["x (mm)", "y (mm)"], dtype="float64")
    bars = reinforcement_table.normalise_table(
        [
            {
                "ID": "R1", "x (mm)": -100.0, "y (mm)": -250.0,
                "size mode": "Diameter", "diameter (mm)": 25.0,
                "material ID": "M1", "fatigue detail ID": "F1",
            },
            {
                "ID": "R2", "x (mm)": 0.0, "y (mm)": -250.0,
                "size mode": "Diameter", "diameter (mm)": 25.0,
                "material ID": "M1", "fatigue detail ID": "F1",
            },
            {
                "ID": "R3", "x (mm)": 100.0, "y (mm)": -250.0,
                "size mode": "Diameter", "diameter (mm)": 25.0,
                "material ID": "M1", "fatigue detail ID": "F1",
            },
            {
                "ID": "R4", "x (mm)": -100.0, "y (mm)": 250.0,
                "size mode": "Diameter", "diameter (mm)": 16.0,
                "material ID": "M1", "fatigue detail ID": "F1",
            },
            {
                "ID": "R5", "x (mm)": 100.0, "y (mm)": 250.0,
                "size mode": "Diameter", "diameter (mm)": 16.0,
                "material ID": "M1", "fatigue detail ID": "F1",
            },
        ],
        "bar",
    )
    return {
        "corners_base": corners,
        "hole_base": holes,
        "bars_base": bars,
        "tendons_base": reinforcement_table.empty_table(),
    }


def _action_tables() -> dict:
    plastic = load_cases.normalise_table(
        [{
            "name": "PL-WORKED",
            "description": "Complete ULS worked action | Source: PR-09 hand pack",
            "n_ed_kn": 0.0,
            "mx_ed_knm": 300.0,
            "my_ed_knm": 0.0,
            "vx_ed_kn": 80.0,
            "vy_ed_kn": 0.0,
            "vx_face": load_cases.FACE_NEGATIVE,
            "vy_face": load_cases.FACE_AUTO,
            "t_ed_knm": 20.0,
            "check_minimum_reinforcement": True,
        }],
        load_cases.PLASTIC_TABLE_KEY,
    )
    elastic = load_cases.normalise_table(
        [{
            "name": "EL-WORKED",
            "description": "Sustained plus transient SLS | Source: PR-09 hand pack",
            "n_long_ed_kn": 0.0,
            "mx_long_ed_knm": 100.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 50.0,
            "my_short_ed_knm": 0.0,
            "calculate_crack_width": True,
        }],
        load_cases.ELASTIC_TABLE_KEY,
    )
    fatigue = fatigue_inputs.normalise_spectrum_table([
        {
            "spectrum": "Road traffic",
            "name": "FAT-WORKED-H",
            "description": "Heavy traffic bin | Source: PR-09 hand pack",
            "cycles": 1.0e5,
            "n_long_ed_kn": 0.0,
            "mx_long_ed_knm": 60.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 25.0,
            "my_short_ed_knm": 0.0,
        },
        {
            "spectrum": "Road traffic",
            "name": "FAT-WORKED-M",
            "description": "Frequent traffic bin | Source: PR-09 hand pack",
            "cycles": 1.0e6,
            "n_long_ed_kn": 0.0,
            "mx_long_ed_knm": 60.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 15.0,
            "my_short_ed_knm": 0.0,
        },
    ])
    return {
        load_cases.PLASTIC_TABLE_KEY: plastic,
        load_cases.ELASTIC_TABLE_KEY: elastic,
        fatigue_inputs.SPECTRUM_TABLE_KEY: fatigue,
    }


def _bridge_tables() -> dict:
    return {
        bridge_inputs.BRITTLE_TABLE_KEY: bridge_inputs.normalise_table(
            [{
                "region_id": "Bottom chord",
                "m_rep_knm": 1000.0,
                "z_s_m": 0.8,
                "f_yk_mpa": 500.0,
                "as_provided_mm2": 3000.0,
            }],
            bridge_inputs.BRITTLE_TABLE_KEY,
        ),
        bridge_inputs.BOX_WALL_TABLE_KEY: bridge_inputs.normalise_table(
            [{
                "wall_id": "Web",
                "cot_theta": 0.5,
                "v_ed_kn": 200.0,
                "v_rd_max_kn": 500.0,
                "t_ed_equivalent_kn": 50.0,
                "t_rd_max_equivalent_kn": 250.0,
            }],
            bridge_inputs.BOX_WALL_TABLE_KEY,
        ),
        bridge_inputs.MINIMUM_CRACK_TABLE_KEY: bridge_inputs.normalise_table(
            [{
                "component": "Web",
                "act_mm2": 100000.0,
                "k_c": 0.4,
                "k": 0.8,
                "fct_eff_mpa": 3.0,
                "sigma_s_mpa": 200.0,
                "as_provided_mm2": 600.0,
                "restrained_shrinkage": False,
            }],
            bridge_inputs.MINIMUM_CRACK_TABLE_KEY,
        ),
    }


def project_tables() -> dict:
    """Return fresh canonical input tables for the complete example."""

    return {**_geometry_tables(), **_action_tables(), **_bridge_tables()}


def project_scalars() -> dict:
    """Return original current-schema scalar inputs, with no derived results."""

    mild = material_catalog.default_catalog("mild")
    mild["items"][0].update({
        "name": "B550 reinforcement - Eurocode horizontal design branch",
        "description": "Single material used by the complete worked beam",
    })
    fatigue_catalogue = fatigue_inputs.default_catalog()
    fatigue_catalogue["items"][0].update({
        "name": "Straight reinforcing bars",
        "description": "Worked traffic-spectrum detail",
    })
    fatigue_basis = fatigue_inputs.default_basis()
    fatigue_basis.update({
        "notes": (
            "PR-09 worked traffic spectrum; cycle counts and actions are explicit "
            "project inputs; no inferred combination."
        ),
    })
    code = codes.EC2_2005_DKNA
    return {
        "mode": "Both",
        "v_min": 0.0,
        "v_max": 360.0,
        "v_inc": 15.0,
        "pl_check_util": True,
        "pl_interaction": False,
        "conc_preset": METHOD,
        "conc_fck": 40.0,
        "conc_gamma_c": code.gamma_c,
        "conc_alpha_cc": code.concrete_factor(40.0),
        "conc_eps_c2": 2.0,
        "conc_eps_cu2": 3.5,
        "conc_n": 2.0,
        "conc_Ec": 35.0,
        "sls_fctm": 3.5,
        material_catalog.MILD_CATALOG_KEY: mild,
        material_catalog.PRESTRESS_CATALOG_KEY:
            material_catalog.default_catalog("prestress"),
        "capacity_steel_material_id": "M1",
        "el_phi": 2.0,
        "sls_cw": True,
        "sls_phi": 0.0,
        "sls_bond": "Ribbed / high bond (k1 = 0.8)",
        "sls_tendon_xi": 0.6,
        "sls_code": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "sls_member": "Beam",
        "shear_on": True,
        "shear_method": METHOD,
        "shear_vx_bw": 300.0,
        "shear_vy_bw": 300.0,
        "shear_dlower": 25.0,
        "shear_links": True,
        "shear_vx_link_legs": 2.0,
        "shear_vy_link_legs": 2.0,
        "shear_vx_transverse_leg_spacing": 250.0,
        "shear_vy_transverse_leg_spacing": 250.0,
        "shear_link_dia": 10.0,
        "shear_link_s": 150.0,
        "shear_fywk": 550.0,
        "strut_cot_min": 1.0,
        "strut_cot_max": 2.5,
        "torsion_on": True,
        "torsion_method": METHOD,
        "torsion_T": 20.0,
        "torsion_tef": 0.0,
        "torsion_nu_v": False,
        "torsion_gamma_ct": code.gamma_ct,
        "torsion_subdivide": False,
        "combined_on": True,
        "combined_method": METHOD,
        "combined_mv_independent": False,
        "minimum_reinforcement_on": True,
        "transverse_detailing_on": True,
        "clear_spacing_on": True,
        "detailing_edition": METHOD,
        "detailing_member_type": detailing.MEMBER_BEAM,
        "detailing_cut_direction": detailing.CUT_TRANSVERSE,
        "detailing_d_upper": 16.0,
        "detailing_include_tendons": False,
        "transverse_ductility_class": "B",
        "transverse_apply_ductility_reduction": False,
        "fatigue_on": True,
        "fatigue_edition": fatigue_inputs.EC2_2005_DKNA,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": True,
        "fatigue_concrete_method": "Explicit Palmgren-Miner spectrum",
        "fatigue_gamma_c": 1.50,
        "fatigue_gamma_s": 1.15,
        "fatigue_gamma_ff": 1.0,
        "fatigue_beta_cc_t0": 1.0,
        "fatigue_t0_days": 28.0,
        "fatigue_concrete_k1": 0.85,
        "fatigue_concrete_c": 14.0,
        fatigue_inputs.DETAIL_CATALOG_KEY: fatigue_catalogue,
        fatigue_inputs.BASIS_KEY: fatigue_basis,
        "bridge_standard": BRIDGE_METHOD,
        "rep_proj_no": "PR-09-WORKED",
        "rep_proj_name": EXAMPLE_NAME,
        "rep_section": "300 x 600 mm beam",
        "rep_rev": "EXAMPLE",
        "rep_author": "Sector worked example",
        "rep_comments": "Recalculate after loading; results are never stored.",
        "rep_report_content": "Default report + QA appendix",
    }


@functools.lru_cache(maxsize=1)
def project_text() -> str:
    """Return a downloadable project produced by the ordinary serializer."""

    return project_io.dump_project(
        project_tables(),
        project_scalars(),
        app_version=sector_version,
        revision=source_revision(),
    )


def hand_calculation_pack() -> str:
    """Return the compact human-readable companion to :func:`project_text`."""

    values = ORACLE["values"]
    return f"""# {EXAMPLE_NAME} - hand-calculation pack

Sector version: {ORACLE['sector_version']}
Project schema: {ORACLE['project_schema']}
Stored material preset: {METHOD}

## How to reproduce

1. Download and load `{PROJECT_FILENAME}` in Sector.
2. Press Calculate. Results are reconstructed; the project contains no results.
3. Generate `Default report + QA appendix`.
4. Compare unrounded values with the frozen checks below and use the structured
   calculation traces for the complete dependency chain.

## Original section and actions

- Rectangle: 300 x 600 mm; gross concrete area = 0.1800000000000000 m2.
- Concrete: C40/50, {METHOD}, fck = 40 MPa.
- Reinforcement: 3 x 25 mm at y = -250 mm; 2 x 16 mm at y = +250 mm.
- Plastic case: NEd = 0 kN, MxEd = 300 kNm, VxEd = 80 kN, TEd = 20 kNm.
- Elastic case: Mx,long = 100 kNm and Mx,short = 50 kNm.
- Fatigue: two explicit Road traffic bins at 1e5 and 1e6 cycles.

## Independent equations

- Gross area: Ac = 0.300 * 0.600 = 0.180 m2.
- One 25 mm bar: As = pi * 25^2 / 4 = 490.8738521234052 mm2.
- One 16 mm bar: As = pi * 16^2 / 4 = 201.0619298297468 mm2.
- Brittle Method B: As,req = 1000 * 1000 / (0.8 * 500) = 2500 mm2.
- Plastic equilibrium: |Nint - NEd| <= 1e-6 max(1, |NEd|), with endpoint
  reachability also required.
- Elastic equilibrium: ||Rint - Red||inf <= 1e-9 max(1, ||Red||inf).
- Concrete fatigue search: upper - best <= 1e-8 + 1e-3 max(|best|, 1e-12).

## Frozen unrounded outputs

- Plastic utilisation: {values['plastic.utilisation']!r}
- Plastic +Mx capacity: {values['plastic.max_mx_knm']!r} kNm
- Plastic axial residual: {values['plastic.axial_residual_kn']!r} kN
- Elastic maximum concrete compression:
  {values['elastic.max_concrete_compression_mpa']!r} MPa
- Elastic short-term crack width: {values['elastic.short_crack_width_mm']!r} mm
- Fatigue utilisation: {values['fatigue.utilisation']!r}
- Shear utilisation: {values['shear.utilisation']!r}
- Torsion utilisation: {values['torsion.utilisation']!r}
- Combined utilisation: {values['combined.utilisation']!r}
- Brittle Method B required area:
  {values['bridge.brittle_required_area_mm2']!r} mm2

## Result-state rules

Convergence is a calculation state, not a verdict. Unsupported, invalid or
nonconverged branches publish no fabricated resistance, utilisation or PASS/FAIL.
Ordinary report fields use their declared fixed decimals; small nonzero evidence
uses six significant digits. Review the unrounded trace/result values for replay.
"""
