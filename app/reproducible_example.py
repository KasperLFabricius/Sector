"""Current-schema input download and checker notes for manual example F-036."""

from __future__ import annotations

from textwrap import dedent

import pandas as pd

import bridge_inputs
import fatigue_inputs
import load_cases
import material_catalog
import project_io
import reinforcement_table
from sector import __version__


PROJECT_NAME = "Sector_v091_reproducible_beam.json"
CHECK_NAME = "Sector_v091_reproducible_beam_check.md"
DK_PRESET = "DS/EN 1992-1-1:2005 + DK NA:2024"


def _reinforcement() -> pd.DataFrame:
    records = []
    positions = (
        (-100.0, -250.0, 25.0),
        (0.0, -250.0, 25.0),
        (100.0, -250.0, 25.0),
        (-100.0, 250.0, 16.0),
        (100.0, 250.0, 16.0),
    )
    for number, (x_mm, y_mm, diameter_mm) in enumerate(positions, start=1):
        records.append({
            "ID": f"R{number}",
            "x (mm)": x_mm,
            "y (mm)": y_mm,
            "size mode": reinforcement_table.DIAMETER_MODE,
            "diameter (mm)": diameter_mm,
            "material ID": "M1",
        })
    return reinforcement_table.normalise_table(records, "bar")


def project_tables() -> dict[str, pd.DataFrame]:
    """Create a new canonical table mapping for every project download."""

    tables = {
        "corners_base": pd.DataFrame(
            [(-150.0, -300.0), (150.0, -300.0),
             (150.0, 300.0), (-150.0, 300.0)],
            columns=("x (mm)", "y (mm)"),
            dtype="float64",
        ),
        "hole_base": pd.DataFrame(
            columns=("x (mm)", "y (mm)"), dtype="float64"
        ),
        "bars_base": _reinforcement(),
        "tendons_base": reinforcement_table.empty_table(),
        load_cases.PLASTIC_TABLE_KEY: load_cases.normalise_table(
            [{
                "name": "PL-REF",
                "description": "Reference biaxial capacity action",
                "n_ed_kn": 0.0,
                "mx_ed_knm": 180.0,
                "my_ed_knm": 30.0,
                "vx_ed_kn": 0.0,
                "vy_ed_kn": 0.0,
                "vx_face": load_cases.FACE_AUTO,
                "vy_face": load_cases.FACE_AUTO,
                "t_ed_knm": 0.0,
                "check_minimum_reinforcement": False,
            }],
            load_cases.PLASTIC_TABLE_KEY,
        ),
        load_cases.ELASTIC_TABLE_KEY: load_cases.normalise_table(
            [{
                "name": "EL-REF",
                "description": "Reference sustained and instantaneous action",
                "n_long_ed_kn": 0.0,
                "mx_long_ed_knm": 60.0,
                "my_long_ed_knm": 10.0,
                "n_short_ed_kn": 0.0,
                "mx_short_ed_knm": 30.0,
                "my_short_ed_knm": 5.0,
                "calculate_crack_width": True,
            }],
            load_cases.ELASTIC_TABLE_KEY,
        ),
        fatigue_inputs.SPECTRUM_TABLE_KEY:
            fatigue_inputs.empty_spectrum_table(),
    }
    tables.update({
        key: bridge_inputs.empty_table(key)
        for key in bridge_inputs.TABLE_KEYS
    })
    return tables


def project_scalars() -> dict:
    """Return every scalar controlling an enabled reference-example branch."""

    return {
        "mode": "Both",
        "conc_preset": DK_PRESET,
        "conc_fck": 40.0,
        "conc_gamma_c": 1.45,
        "conc_k_tc": 1.0,
        "conc_alpha_cc": 1.0,
        "conc_eps_c2": 2.0,
        "conc_eps_cu2": 3.5,
        "conc_n": 2.0,
        "conc_Ec": 35.2,
        "sls_fctm": 3.5088212858554386,
        material_catalog.MILD_CATALOG_KEY:
            material_catalog.default_catalog("mild"),
        material_catalog.PRESTRESS_CATALOG_KEY:
            material_catalog.default_catalog("prestress"),
        "mild_preset": DK_PRESET,
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
        "sls_code": "DS/EN 1992-1-1 + DK NA",
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
            "F-036 example identity is ordinary project metadata and does not "
            "replace source/build provenance."
        ),
        "rep_report_content": "Default report",
    }


def input_sha256() -> str:
    return project_io.input_sha256(project_tables(), project_scalars())


def project_json() -> str:
    """Build a current-schema project using project_io's genuine revision path."""

    return project_io.dump_project(
        project_tables(), project_scalars(), app_version=__version__
    )


def checking_pack() -> str:
    """Publish original inputs, frozen outputs and every exceptional method branch."""

    return dedent(f"""
        # Sector v{__version__} reproducible beam checking pack

        Input SHA-256: `{input_sha256()}`  
        Project schema: `{project_io.VERSION}`

        ## Scope, units and signs

        The emitted report covers conventions, section/materials, analysis basis,
        named actions, plastic capacity/utilisation, elastic response/cracking and
        provenance. Fatigue, shear, torsion, combined M-V-T, detailing and bridge
        calculation families are disabled. Solver geometry is in metres, actions in
        kN/kNm and elastic stresses in kN/m2 before division by 1000 to MPa.
        External axial compression is positive; reinforcement tension is positive.

        ## Original inputs

        Centred 0.300 x 0.600 m rectangle. R1-R3 are 25 mm bars at y=-0.250 m
        and x=-0.100, 0, +0.100 m. R4-R5 are 16 mm bars at y=+0.250 m and
        x=-0.100, +0.100 m. Every bar retains B550 material ID M1. C40/50 has
        fck=40 MPa, gamma_c=1.45, alpha_cc=1, eps_c2=0.002,
        eps_cu2=0.0035 and n=2. PL-REF is (N,Mx,My)=(0,180,30).
        EL-REF long is (0,60,10), with short increment (0,30,5). Ec=35200 MPa,
        Es=200000 MPa and creep phi=3 give nl=22.727272727272727 and
        ns=5.681818181818182.

        ## Frozen unrounded results

        The 24 plastic angles 0,15,...,345 degrees all converge. Applied radius is
        182.4828759089466 kNm; crossed-chord resistance is 330.5985879649080 kNm;
        utilisation is 0.5519771788266579. Governing stored member index 3 is the
        V=45 degree endpoint with Mx=323.4705855644198 kNm,
        My=58.22334819001088 kNm and axial residual
        8.436700227321126e-10 kN.

        The combined Elastic solve converges. TOTAL bar stresses R1-R5 are
        [163.1938982695797, 128.33217244841316, 93.47044662724659,
        -23.970703497881885, -93.694155140215] MPa. Maximum concrete compression
        is 9.056070470526570 MPa. The long action alone is uncracked with factor
        1.180243298120012; the peak factor is 0.7095506619292463. The short-term
        fine-system crack is 0.1142440041397812 mm at 233.3502362346533 mm
        spacing, governed by zero-based bar index 0 (R1).

        ## Complete numerical-method rules

        Plastic axial solve: c_lo=1e-9 c_full and c_hi=c_full. Double c_hi up to
        80 times while its axial force is below N. Equality at either endpoint is
        reachable. For an in-range N, bisect up to 100 times and stop early when
        c_hi-c_lo < 1e-12 c_full. Evaluate the final midpoint. Convergence is
        exactly endpoint reachability AND |sum(F)-N| <= 1e-6 max(1,|N|).
        Reaching the bisection cap is not an independent failure flag.

        Cracked Elastic solve: start with the uncracked linear strain plane; if
        that matrix is singular, start from zero. Reclip the compression zone on
        every Newton iteration. Converge within 100 iterations when
        max(abs(internal-target)) <= 1e-9 max(1,max(abs(target))). A singular
        iteration tangent or cap exit before the residual test passes leaves
        converged false.

        Applied ray: demand below 1e-9 returns zero utilisation and no resistance
        or governing member. A chord is parallel when |cross(ray,edge)|<=1e-12.
        Accept -1e-9<=s<=1+1e-9 and forward t>1e-9, then use the nearest forward
        crossing. No crossing returns infinite utilisation and no resistance/member.
        The governing member is the crossed chord endpoint closest to the crossing;
        equal endpoint distances select the first endpoint in sweep order.

        Concrete-fatigue search: start with 4 x 4 boxes; maximum depth is 26 and
        maximum evaluated boxes is 200000. Empty or fully dominated unresolved
        heaps are converged. For finite values, certify when
        upper-best <= 1e-8 + 1e-3 max(|best|,1e-12). A depth/box limit reached
        before that certificate leaves converged false. Exception: if the best
        sampled damage is positive infinity, publish upper=best=+infinity and
        converged true; the recorded absolute and relative gaps remain infinity.

        Report calculations, dependency checks and verdicts use unrounded values.
        Fixed decimal counts and six-significant-digit diagnostic formatting are
        display operations only and never feed mechanics or verdicts.
    """).strip() + "\n"
