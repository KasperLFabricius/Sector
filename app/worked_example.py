"""Downloadable current-schema project and its frozen hand-calculation pack.

The example is input data plus independently frozen expected results.  It calls no
analysis routine and is therefore not a second mechanics engine.  CI loads the JSON
through the normal application boundary, calculates it, and compares the retained
results with a separate test-only oracle.
"""

from __future__ import annotations

import math

import pandas as pd

import bridge_inputs
import fatigue_inputs
import load_cases
import material_catalog
import project_io
import reinforcement_table as rebar_table
from sector import __version__ as APP_VERSION


PROJECT_FILENAME = "Sector_PR09B_reproducible_example.json"
HAND_PACK_FILENAME = "Sector_PR09B_hand_calculation_pack.md"


def _bars() -> pd.DataFrame:
    rows = []
    coordinates = [
        (-150.0, -250.0),
        (-90.0, -250.0),
        (-30.0, -250.0),
        (30.0, -250.0),
        (90.0, -250.0),
        (150.0, -250.0),
        (-150.0, 250.0),
        (150.0, 250.0),
    ]
    for number, (x_mm, y_mm) in enumerate(coordinates, start=1):
        rows.append({
            rebar_table.ELEMENT_ID: f"R{number}",
            rebar_table.X: x_mm,
            rebar_table.Y: y_mm,
            rebar_table.SIZE_MODE: rebar_table.DIAMETER_MODE,
            rebar_table.AREA: math.pi * 20.0 ** 2 / 4.0,
            rebar_table.DIAMETER: 20.0,
            rebar_table.MATERIAL_ID: "M1",
            rebar_table.FATIGUE_DETAIL_ID: "F1",
        })
    return rebar_table.normalise_table(
        rows,
        "bar",
        default_mode=rebar_table.DIAMETER_MODE,
    )


def project_tables() -> dict[str, pd.DataFrame]:
    """Return every current project table with stable row order and types."""

    tables = {
        "corners_base": pd.DataFrame({
            "x (mm)": [-200.0, -200.0, 200.0, 200.0],
            "y (mm)": [-300.0, 300.0, 300.0, -300.0],
        }),
        "hole_base": pd.DataFrame(
            columns=["x (mm)", "y (mm)"], dtype="float64"
        ),
        "bars_base": _bars(),
        "tendons_base": rebar_table.empty_table(),
        load_cases.PLASTIC_TABLE_KEY: load_cases.normalise_table([{
            "name": "PL-DEMO",
            "description": "Worked plastic/capacity action",
            "n_ed_kn": 0.0,
            "mx_ed_knm": 90.0,
            "my_ed_knm": 25.0,
            "vx_ed_kn": 80.0,
            "vy_ed_kn": 0.0,
            "vx_face": load_cases.FACE_AUTO,
            "vy_face": load_cases.FACE_AUTO,
            "t_ed_knm": 20.0,
            "check_minimum_reinforcement": True,
        }], load_cases.PLASTIC_TABLE_KEY),
        load_cases.ELASTIC_TABLE_KEY: load_cases.normalise_table([{
            "name": "EL-DEMO",
            "description": "Worked elastic/crack action",
            "n_long_ed_kn": 0.0,
            "mx_long_ed_knm": 60.0,
            "my_long_ed_knm": 5.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 60.0,
            "my_short_ed_knm": 3.0,
            "calculate_crack_width": True,
        }], load_cases.ELASTIC_TABLE_KEY),
        fatigue_inputs.SPECTRUM_TABLE_KEY: (
            fatigue_inputs.normalise_spectrum_table([{
                "spectrum": "S1",
                "name": "FAT-DEMO",
                "description": "Worked fatigue bin",
                "cycles": 100_000.0,
                "n_long_ed_kn": 0.0,
                "mx_long_ed_knm": 30.0,
                "my_long_ed_knm": 0.0,
                "n_short_ed_kn": 0.0,
                "mx_short_ed_knm": 20.0,
                "my_short_ed_knm": 0.0,
            }])
        ),
        bridge_inputs.BRITTLE_TABLE_KEY: bridge_inputs.normalise_table([{
            "region_id": "bottom",
            "m_rep_knm": 1000.0,
            "z_s_m": 0.8,
            "f_yk_mpa": 500.0,
            "as_provided_mm2": 2600.0,
        }], bridge_inputs.BRITTLE_TABLE_KEY),
        bridge_inputs.BOX_WALL_TABLE_KEY: bridge_inputs.normalise_table([{
            "wall_id": "web",
            "cot_theta": 2.0,
            "v_ed_kn": 100.0,
            "v_rd_max_kn": 500.0,
            "t_ed_equivalent_kn": 50.0,
            "t_rd_max_equivalent_kn": 500.0,
        }], bridge_inputs.BOX_WALL_TABLE_KEY),
        bridge_inputs.MINIMUM_CRACK_TABLE_KEY: bridge_inputs.normalise_table([{
            "component": "web",
            "act_mm2": 100_000.0,
            "k_c": 0.4,
            "k": 1.0,
            "fct_eff_mpa": 2.9,
            "sigma_s_mpa": 500.0,
            "as_provided_mm2": 500.0,
            "restrained_shrinkage": False,
        }], bridge_inputs.MINIMUM_CRACK_TABLE_KEY),
    }
    if set(tables) != set(project_io.PROJECT_TABLE_KEYS):
        raise RuntimeError("worked example does not own every current table")
    return tables


def project_scalars() -> dict:
    """Return every current scalar input; no output depends on a UI default."""

    mild_catalog = material_catalog.default_catalog("mild")
    prestress_catalog = material_catalog.default_catalog("prestress")
    mild = mild_catalog["items"][0]
    prestress = prestress_catalog["items"][0]
    values = {
        # Quick Section state describes the same explicit point tables.
        "qsv_shape": "Rectangle",
        "qsv_b_mm": 400.0,
        "qsv_h_mm": 600.0,
        "qsv_bf_mm": 400.0,
        "qsv_hf_mm": 120.0,
        "qsv_bw_mm": 200.0,
        "qsv_hw_mm": 480.0,
        "qsv_wall_mm": 80.0,
        "qsv_dia_mm": 600.0,
        "qsv_ring_n": 8,
        "qsv_ring_d": 20.0,
        "qsv_ring_c_mm": 50.0,
        "qsv_qs_rebar_mode": "By number",
        "qsv_qs_cover_to_edge": False,
        "qsv_bot_n": 6,
        "qsv_bot_d": 20.0,
        "qsv_bot_s": 60.0,
        "qsv_top_n": 2,
        "qsv_top_d": 20.0,
        "qsv_top_s": 300.0,
        "qsv_bot_c_mm": 50.0,
        "qsv_top_c_mm": 50.0,
        "qsv_bot_n2": 6,
        "qsv_top_n2": 2,
        "qsv_bot_layers": 1,
        "qsv_top_layers": 1,
        "qsv_layer_s": 60.0,
        "qsv_bot_off_d": 0.0,
        "qsv_top_off_d": 0.0,
        "qsv_tnd_n": 0,
        "qsv_tnd_a": 150.0,
        "qsv_tnd_c_mm": 100.0,
        "qsv_tnd_layers": 1,
        "qsv_tnd_layer_s": 60.0,
        # Concrete and the complete material catalogues.
        "conc_preset": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "conc_fck": 35.0,
        "conc_gamma_c": 1.45,
        "conc_k_tc": 1.0,
        "conc_alpha_cc": 1.0,
        "conc_eps_c2": 2.0,
        "conc_eps_cu2": 3.5,
        "conc_n": 2.0,
        "conc_Ec": 34.1,
        "sls_fctm": 3.21,
        material_catalog.MILD_CATALOG_KEY: mild_catalog,
        material_catalog.PRESTRESS_CATALOG_KEY: prestress_catalog,
        fatigue_inputs.DETAIL_CATALOG_KEY: fatigue_inputs.default_catalog(),
        fatigue_inputs.BASIS_KEY: fatigue_inputs.default_basis(),
        "mild_preset": mild["preset"],
        "mild_active_comp": mild["active_in_compression"],
        "mild_fytk": mild["fytk"],
        "mild_fyck": mild["fyck"],
        "mild_futk": mild["futk"],
        "mild_eut": mild["eut"],
        "mild_gamma_y": mild["gamma_y"],
        "mild_gamma_u": mild["gamma_u"],
        "mild_gamma_E": mild["gamma_E"],
        "mild_k": mild["k"],
        "mild_ey0t": mild["ey0t"],
        "mild_ey0c": mild["ey0c"],
        "mild_Es": mild["Es"],
        "pre_preset": prestress["preset"],
        "pre_IS": prestress["IS"],
        "pre_fytk": prestress["fytk"],
        "pre_futk": prestress["futk"],
        "pre_eut": prestress["eut"],
        "pre_gamma_y": prestress["gamma_y"],
        "pre_gamma_u": prestress["gamma_u"],
        "pre_gamma_E": prestress["gamma_E"],
        "pre_k": prestress["k"],
        "pre_ey0t": prestress["ey0t"],
        "pre_Es": prestress["Es"],
        # Analysis and crack controls.
        "mode": "Both",
        "v_min": 0.0,
        "v_max": 360.0,
        "v_inc": 15.0,
        "pl_check_util": True,
        "pl_interaction": False,
        "el_phi": 3.0,
        "sls_cw": True,
        "sls_phi": 0.0,
        "sls_bond": "Ribbed / high bond (k1 = 0.8)",
        "sls_tendon_xi": 0.0,
        "sls_code": "EN 1992-1-1:2005",
        "sls_member": "Beam",
        "bridge_standard": "DS/EN 1992-2:2005 + AC:2008",
        # Fatigue.
        "fatigue_on": True,
        "fatigue_edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "fatigue_check_steel": True,
        "fatigue_check_concrete": True,
        "fatigue_concrete_method": "Explicit Palmgren-Miner spectrum",
        "fatigue_gamma_c": 1.595,
        "fatigue_gamma_s": 1.32,
        "fatigue_gamma_ff": 1.0,
        "fatigue_beta_cc_t0": 1.0,
        "fatigue_t0_days": 28.0,
        "fatigue_concrete_k1": 0.85,
        "fatigue_concrete_c": 14.0,
        # Longitudinal and transverse detailing.
        "minimum_reinforcement_on": True,
        "transverse_detailing_on": True,
        "clear_spacing_on": True,
        "detailing_edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "detailing_member_type": "Beam",
        "detailing_cut_direction": "Transverse cut",
        "detailing_d_upper": 16.0,
        "detailing_include_tendons": False,
        "transverse_ductility_class": "B",
        "transverse_apply_ductility_reduction": False,
        # Directional shear.
        "shear_on": True,
        "shear_method": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "shear_Vx": 0.0,
        "shear_Vy": 0.0,
        "shear_face_x": load_cases.FACE_AUTO,
        "shear_face_y": load_cases.FACE_AUTO,
        "shear_vx_bw": 0.0,
        "shear_vy_bw": 0.0,
        "shear_dlower": 16.0,
        "shear_links": True,
        "shear_vx_link_legs": 2.0,
        "shear_vy_link_legs": 2.0,
        "shear_link_dia": 10.0,
        "shear_link_s": 150.0,
        "shear_fywk": 500.0,
        "shear_vx_transverse_leg_spacing": 200.0,
        "shear_vy_transverse_leg_spacing": 200.0,
        "strut_cot_min": 1.0,
        "strut_cot_max": 2.5,
        # Torsion and M-V-T. Inert subdivision fields remain explicit.
        "torsion_on": True,
        "torsion_method": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "torsion_T": 0.0,
        "torsion_tef": 0.0,
        "torsion_nu_v": False,
        "torsion_gamma_ct": 1.7,
        "torsion_subdivide": False,
        "torsion_nsub": 0,
        "torsion_sub_x0": 0.0,
        "torsion_sub_y0": 0.0,
        "torsion_sub_x1": 0.0,
        "torsion_sub_y1": 0.0,
        "torsion_sub_x2": 0.0,
        "torsion_sub_y2": 0.0,
        "torsion_sub_x3": 0.0,
        "torsion_sub_y3": 0.0,
        "torsion_sub_b0": 0.0,
        "torsion_sub_h0": 0.0,
        "torsion_sub_b1": 0.0,
        "torsion_sub_h1": 0.0,
        "torsion_sub_b2": 0.0,
        "torsion_sub_h2": 0.0,
        "torsion_sub_b3": 0.0,
        "torsion_sub_h3": 0.0,
        "combined_on": True,
        "combined_method": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "combined_mv_independent": False,
        "capacity_steel_material_id": "M1",
        "label_scale": 1.0,
        "label_min_gap": 0.04,
        # Report identity and local preferences.
        "rep_proj_no": "SECTOR-PR09B",
        "rep_proj_name": "Reproducible worked example",
        "rep_section": "400 x 600 mm reinforced-concrete section",
        "rep_rev": "A",
        "rep_author": "Sector example",
        "rep_comments": "Numerical-method hand pack companion.",
        "rep_report_content": "Default report + QA appendix",
        "autosave_on": False,
        "autosave_min": 5,
    }
    missing = set(project_io.SCALAR_KEYS) - set(values)
    extra = set(values) - set(project_io.SCALAR_KEYS)
    if missing or extra:
        raise RuntimeError(
            f"worked example scalar mismatch; missing={sorted(missing)}, "
            f"extra={sorted(extra)}"
        )
    return values


def project_json() -> str:
    """Serialize the complete example through the authoritative project writer."""

    return project_io.dump_project(
        project_tables(),
        project_scalars(),
        app_version=APP_VERSION,
        revision="worked-example",
    )


def hand_pack_markdown() -> str:
    """Return compact independent-reproduction instructions for the project."""

    return """# Sector PR-09B hand-calculation pack

Companion file: `Sector_PR09B_reproducible_example.json` (current project schema).
Sector version: 0.91. Actions are user-defined; this pack is numerical
reproducibility evidence, not a compliance certificate.

## Inputs and section

- Solid rectangle: 400 x 600 mm; area = 0.24 m2; centroid = (0, 0).
- C35: gamma_c = 1.45, alpha_cc = 1.0, f_cd = 24.137931034482758 MPa.
- Eight phi20 B550 bars: six at y = -250 mm and two at y = +250 mm.
- PL-DEMO: N/Mx/My/Vx/Vy/T = 0/90/25/80/0/20 in kN and kNm.
- EL-DEMO: long Mx/My = 60/5 kNm; short Mx/My = 60/3 kNm.
- S1/FAT-DEMO: 100000 cycles; long/cyclic Mx = 30/20 kNm.

## Report-section oracle (unrounded)

| Section | Independent value / state |
|---|---|
| Clear spacing | clear = 40.0 mm; required = 21.0 mm; PASS |
| Plastic | Mx,max = 441.41060408252827 kNm; My,max = 190.28509810796606 kNm; utilization = 0.22168893734073017; converged |
| Minimum reinforcement | As,min = 289.20898395721923 mm2; As,provided = 1884.9555921538758 mm2; utilization = 0.15343013127792032; PASS |
| Transverse detailing | governing utilization = 0.8743169398907104; PASS |
| Shear Vx | VEd/VRd = 0.33297405120085827; common cot(theta) = 2.5 |
| Torsion | TRd,c/TRd,s/TRd,max/TRd = 42.63434350795596 / 146.6076571675237 / 98.66653983353152 / 98.66653983353152 kNm; utilization = 0.20270296327147638 |
| Combined M-V-T | rM/rV/rT = 0.22168893734073017 / 0.33297405120085827 / 0.20270296327147638; sum = 0.7573659518130649; PASS |
| Elastic/cracking | lambda_cr = 0.7759636907614162; sigma_ct = 4.1367914996772335 MPa; concrete compression = 7.232636006216452 MPa; max steel = 140.80047128144372 MPa |
| Crack width | R1 governs; sr,max = 210.2985683043877 mm; wk = 0.04768998164377517 mm; calculated |
| Grouped fatigue | spectrum S1 utilization = 0.14921587083663004; R1 damage = 1.0234410273738176e-08; concrete search damage/upper = 1.105632868755511e-09 / 9.598384282112247e-09; converged and PASS |
| Bridge Method B | As,required = 2500.0 mm2; utilization = 0.9615384615384616; PASS |
| Bridge box wall | VEd/VRd,max + TEd/TRd,max = 0.30000000000000004; PASS |
| Bridge minimum crack steel | As,required = 231.99999999999997 mm2; utilization = 0.46399999999999997; PASS |

## Governing expressions

- Plastic residual: `sum(F) - N`; convergence requires reachability and
  `abs(residual) <= 1e-6*max(1,abs(N))`.
- Elastic residual: `[Nint-N, Mxint-Mx, Myint-My]`; the infinity norm must not
  exceed `1e-9*max(1,max(abs(target)))`.
- Radial bending utilization: demand radius divided by the nearest forward
  intersection of the applied ray and the closed Mx-My envelope.
- Combined DK rule used here: `rM + rV + rT = 0.7573659518130649 <= 1`.
- Bridge Method B: published equation `As,min = Mrep / (zs fyk)`; with the
  displayed kNm, m and MPa units, `As,min = 1000*Mrep/(zs*fyk)` in mm2.
- Box wall: `VEd/VRd,max + TEd,wall/TRd,max,wall <= 1.0`.
- Bridge minimum crack steel: `As,min = kc k fct,eff Act / sigma_s`.

## Solver stops and failure states

- Plastic: at most 100 bisections; stop when the depth bracket is below
  `1e-12*c_full`. An out-of-range axial action is unreachable, not converged.
- Cracked Elastic: at most 100 Newton iterations from the Stage-I linear solve.
  A singular stiffness or residual outside tolerance is invalid. Stage I itself
  is one linear solve.
- Shared strut angle: evaluate 1501 equally spaced candidates; minimize worst
  utilization, then total utilization, then lower cot(theta).
- Concrete-fatigue fibre: certified priority branch-and-bound; 4 x 4 initial
  boxes, depth 26, at most 200000 boxes, accepted gap
  `1e-8 + 1e-3*max(abs(best),1e-12)`. An uncertified search cannot pass.
- Uncracked crack width is NOT APPLICABLE. Missing/incompatible inputs and failed
  solvers are INVALID and publish no fabricated engineering verdict.
"""
