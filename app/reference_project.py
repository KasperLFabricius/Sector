"""Downloadable current-schema project and compact independent-checking pack.

The reference project is deliberately an input artefact, not a persisted result
bundle.  Frozen expected results live in the accompanying calculation pack and
are reconstructed independently in the tests from the saved original inputs.
"""

from __future__ import annotations

import pandas as pd

import bridge_inputs
import fatigue_inputs
import load_cases
import material_catalog
import project_io
import reinforcement_table
from sector import __version__ as APP_VERSION


PROJECT_FILE_NAME = "Sector_v091_reference_beam.json"
PACK_FILE_NAME = "Sector_v091_reference_beam_check.md"
CONCRETE_PRESET = "DS/EN 1992-1-1:2005 + DK NA:2024"
MILD_PRESET = "DS/EN 1992-1-1:2005 + DK NA:2024"
CRACK_METHOD = "DS/EN 1992-1-1 + DK NA"


def reference_tables() -> dict[str, pd.DataFrame]:
    """Return a fresh canonical table set for the reference beam."""

    tables = {
        "corners_base": pd.DataFrame({
            "x (mm)": [-150.0, 150.0, 150.0, -150.0],
            "y (mm)": [-300.0, -300.0, 300.0, 300.0],
        }),
        "hole_base": pd.DataFrame(
            columns=["x (mm)", "y (mm)"], dtype="float64"
        ),
        "bars_base": reinforcement_table.normalise_table([
            {
                "ID": "R1", "x (mm)": -100.0, "y (mm)": -250.0,
                "size mode": "Diameter", "diameter (mm)": 25.0,
                "material ID": "M1",
            },
            {
                "ID": "R2", "x (mm)": 0.0, "y (mm)": -250.0,
                "size mode": "Diameter", "diameter (mm)": 25.0,
                "material ID": "M1",
            },
            {
                "ID": "R3", "x (mm)": 100.0, "y (mm)": -250.0,
                "size mode": "Diameter", "diameter (mm)": 25.0,
                "material ID": "M1",
            },
            {
                "ID": "R4", "x (mm)": -100.0, "y (mm)": 250.0,
                "size mode": "Diameter", "diameter (mm)": 16.0,
                "material ID": "M1",
            },
            {
                "ID": "R5", "x (mm)": 100.0, "y (mm)": 250.0,
                "size mode": "Diameter", "diameter (mm)": 16.0,
                "material ID": "M1",
            },
        ], "bar"),
        "tendons_base": reinforcement_table.empty_table(),
        load_cases.PLASTIC_TABLE_KEY: load_cases.normalise_table([{
            "name": "PL-REF",
            "description": "Reference biaxial capacity action",
            "n_ed_kn": 0.0,
            "mx_ed_knm": 180.0,
            "my_ed_knm": 30.0,
            "vx_ed_kn": 0.0,
            "vy_ed_kn": 0.0,
            "vx_face": "auto",
            "vy_face": "auto",
            "t_ed_knm": 0.0,
            "check_minimum_reinforcement": False,
        }], load_cases.PLASTIC_TABLE_KEY),
        load_cases.ELASTIC_TABLE_KEY: load_cases.normalise_table([{
            "name": "EL-REF",
            "description": "Reference sustained plus instantaneous action",
            "n_long_ed_kn": 0.0,
            "mx_long_ed_knm": 60.0,
            "my_long_ed_knm": 10.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 30.0,
            "my_short_ed_knm": 5.0,
            "calculate_crack_width": True,
        }], load_cases.ELASTIC_TABLE_KEY),
        fatigue_inputs.SPECTRUM_TABLE_KEY: (
            fatigue_inputs.empty_spectrum_table()
        ),
    }
    for key in bridge_inputs.TABLE_KEYS:
        tables[key] = bridge_inputs.empty_table(key)
    return tables


def reference_scalars() -> dict:
    """Return the complete calculation-relevant scalar input inventory."""

    mild_catalog = material_catalog.default_catalog("mild")
    prestress_catalog = material_catalog.default_catalog("prestress")
    return {
        "mode": "Both",
        "conc_preset": CONCRETE_PRESET,
        "conc_fck": 40.0,
        "conc_gamma_c": 1.45,
        "conc_k_tc": 1.0,
        "conc_alpha_cc": 1.0,
        "conc_eps_c2": 2.0,
        "conc_eps_cu2": 3.5,
        "conc_n": 2.0,
        "conc_Ec": 35.2,
        "sls_fctm": 3.5088212858554386,
        material_catalog.MILD_CATALOG_KEY: mild_catalog,
        material_catalog.PRESTRESS_CATALOG_KEY: prestress_catalog,
        "mild_preset": MILD_PRESET,
        "mild_active_comp": True,
        "mild_fytk": 550.0,
        "mild_fyck": 550.0,
        "mild_futk": 550.0,
        "mild_eut": 50.0,
        "mild_gamma_y": 1.2,
        "mild_gamma_u": 1.2,
        "mild_gamma_E": 1.0,
        "mild_k": 1.0,
        "mild_ey0t": 0.0,
        "mild_ey0c": 0.0,
        "mild_Es": 200.0,
        "capacity_steel_material_id": "M1",
        "v_min": 0.0,
        "v_max": 360.0,
        "v_inc": 15.0,
        "pl_check_util": True,
        "pl_interaction": False,
        "el_phi": 3.0,
        "sls_phi": 0.0,
        "sls_bond": "Ribbed / high bond (k1 = 0.8)",
        "sls_tendon_xi": 0.0,
        "sls_code": CRACK_METHOD,
        "sls_member": "Beam",
        "fatigue_on": False,
        "minimum_reinforcement_on": False,
        "transverse_detailing_on": False,
        "clear_spacing_on": False,
        "shear_on": False,
        "torsion_on": False,
        "combined_on": False,
        "bridge_standard": "Independent component calculations",
        "rep_proj_no": "SECTOR-REF-091",
        "rep_proj_name": "Sector reproducible reference beam",
        "rep_section": "300 x 600 mm beam",
        "rep_rev": "Reference input set 1",
        "rep_author": "Sector reference calculation",
        "rep_comments": (
            "F-036 reproducible input set; example identity is project metadata, "
            "not source/build provenance."
        ),
        "rep_report_content": "Default report",
    }


def project_input_sha256() -> str:
    """Return the deterministic identity of the complete saved input set."""

    return project_io.input_sha256(reference_tables(), reference_scalars())


def project_download() -> str:
    """Serialize the example with current schema and genuine build provenance."""

    return project_io.dump_project(
        reference_tables(),
        reference_scalars(),
        app_version=APP_VERSION,
    )


def calculation_pack() -> str:
    """Return the compact frozen hand-check/oracle pack as ASCII Markdown."""

    digest = project_input_sha256()
    return f"""# Sector v{APP_VERSION} reproducible reference beam

Project input SHA-256: `{digest}`
Project schema: `{project_io.VERSION}`

## Scope and signs

The project emits the main report sections for conventions, section and
materials, basis, named actions, plastic capacity/utilisation, elastic response
and cracking, plus saved-input provenance. Optional fatigue, shear, torsion,
combined M-V-T, detailing and independent bridge families are disabled.

Compression is positive for external axial action. Concrete-engine compression
strain is negative; reinforcement tension stress is positive. Coordinates are in
metres inside the solver, forces in kN, moments in kNm, and stresses returned by
the elastic kernel are kN/m2 before division by 1000 to MPa.

## Original inputs

- Rectangle: x = +/-0.150 m; y = +/-0.300 m.
- Bars R1-R3: diameter 25 mm at x = -0.100, 0, +0.100 m and y = -0.250 m.
- Bars R4-R5: diameter 16 mm at x = -0.100, +0.100 m and y = +0.250 m.
- Every bar retains mild-steel material identity M1, the B550 Curve 3 Eurocode
  preset: Es = 200000 MPa, fyk = 550 MPa and gamma_s = 1.20.
- C40/50: fck = 40 MPa, gamma_c = 1.45, alpha_cc = 1.0,
  eps_c2 = 0.002, eps_cu2 = 0.0035 and n = 2.
- PL-REF: (N, Mx, My) = (0, 180, 30) kN/kNm/kNm.
- EL-REF long: (0, 60, 10); short increment: (0, 30, 5).
- Ec = 35200 MPa and creep phi = 3.0, hence nl = 22.727272727272727
  and ns = 5.681818181818182.

## Plastic reconstruction

Sweep 24 neutral-axis angles V = 0, 15, ..., 345 degrees. At every angle,
bracket and bisect the compression depth for N = 0, integrate the accepted
parabola-rectangle and Curve 3 laws, and retain the polygon in sweep order.
Intersect the applied ray (180, 30) with each closed-polygon chord and take the
nearest forward crossing.

Frozen unrounded checks:

- all 24 angle solves converged;
- applied radius = 182.4828759089466 kNm;
- radial resistance = 330.5985879649080 kNm;
- utilisation = 0.5519771788266579;
- governing stored member index = 3 (V = 45 degrees);
- V = 45 degrees: Mx = 323.4705855644198 kNm,
  My = 58.22334819001088 kNm and axial residual = 8.436700227321126e-10 kN.

## Elastic and crack reconstruction

Solve the long action at nl. Form s2 = s1(1 - ns/nl), take its reinforcement
resultants, then solve the combined action minus those resultants at ns. The
reported TOTAL stress is s2 + RST1 and DIF is TOTAL - LONG.

Frozen unrounded checks:

- the combined elastic state converged;
- total bar stresses R1-R5 (MPa) =
  [163.1938982695797, 128.3321724484132, 93.47044662724659,
  -23.97070349788189, -93.69415514021500];
- maximum concrete compression = 9.056070470526570 MPa;
- sustained cracking factor = 1.180243298120012 (uncracked alone);
- combined cracking factor = 0.7095506619292463 (cracked at peak);
- short-term fine-system crack width = 0.1142440041397812 mm;
- its crack spacing = 233.3502362346533 mm and governing bar index = 0 (R1).

## Convergence, failure and report rules

- Plastic: at most 80 upper-bracket expansions and 100 bisections; stop when
  depth width is below 1e-12 times full depth. A result is converged only when N
  is inside the retained endpoint range and |sum(F)-N| <= 1e-6 max(1, |N|).
  Reaching the bisection cap is not an independent failure state; the final
  midpoint is judged by those same reachability and residual tests.
- Elastic: at most 100 Newton iterations. Convergence requires the largest
  absolute N/M residual <= 1e-9 max(1, max(|N|, |Mx|, |My|)). A singular
  Jacobian or exhausted cap leaves convergence false.
- Applied ray: demand below 1e-9 is zero; a chord is parallel when the cross
  product magnitude is <= 1e-12; the edge band is -1e-9 <= s <= 1+1e-9 and
  the crossing must have t > 1e-9. A missing crossing returns infinite
  utilisation and no resistance/member.
- Concrete-fatigue search (not enabled here): 4 x 4 initial boxes, maximum depth
  26 and 200000 evaluated boxes. It is certified only when upper-best <=
  1e-8 + 1e-3 max(|best|, 1e-12); reaching a resource limit first is not
  converged.
- Every calculation and verdict uses unrounded values. Ordinary report cells use
  their declared fixed decimal count (normally three); small diagnostic evidence
  uses six significant digits. Display formatting never feeds a calculation.
"""
