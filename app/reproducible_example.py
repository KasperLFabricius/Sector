"""Complete current-schema F-036 reference project and independent hand pack."""

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
from sector import bridge, codes, detailing


PROJECT_NAME = "Sector_v091_complete_reference.json"
CHECK_NAME = "Sector_v091_complete_reference_check.md"
DK_PRESET = codes.EC2_2005_DKNA.label


def _bars() -> pd.DataFrame:
    return reinforcement_table.normalise_table(
        [
            {
                "ID": "R1",
                "x (mm)": -60.0,
                "y (mm)": -120.0,
                "size mode": reinforcement_table.AREA_MODE,
                "area (mm2)": 500.0,
                "material ID": "M1",
                "fatigue detail ID": "F1",
            },
            {
                "ID": "R2",
                "x (mm)": 60.0,
                "y (mm)": -120.0,
                "size mode": reinforcement_table.AREA_MODE,
                "area (mm2)": 500.0,
                "material ID": "M1",
                "fatigue detail ID": "F1",
            },
            {
                "ID": "R3",
                "x (mm)": -60.0,
                "y (mm)": 120.0,
                "size mode": reinforcement_table.AREA_MODE,
                "area (mm2)": 400.0,
                "material ID": "M1",
                "fatigue detail ID": "F1",
            },
            {
                "ID": "R4",
                "x (mm)": 60.0,
                "y (mm)": 120.0,
                "size mode": reinforcement_table.AREA_MODE,
                "area (mm2)": 400.0,
                "material ID": "M1",
                "fatigue detail ID": "F1",
            },
        ],
        "bar",
    )


def project_tables() -> dict[str, pd.DataFrame]:
    tables = {
        "corners_base": pd.DataFrame(
            [(-100.0, -150.0), (100.0, -150.0),
             (100.0, 150.0), (-100.0, 150.0)],
            columns=("x (mm)", "y (mm)"),
            dtype="float64",
        ),
        "hole_base": pd.DataFrame(
            columns=("x (mm)", "y (mm)"), dtype="float64"
        ),
        "bars_base": _bars(),
        "tendons_base": reinforcement_table.empty_table(),
        load_cases.PLASTIC_TABLE_KEY: load_cases.normalise_table(
            [{
                "name": "PL-COMPLETE",
                "description": "Complete ULS reference action",
                "n_ed_kn": 0.0,
                "mx_ed_knm": 80.0,
                "my_ed_knm": 10.0,
                "vx_ed_kn": 0.0,
                "vy_ed_kn": 30.0,
                "vx_face": load_cases.FACE_AUTO,
                "vy_face": load_cases.FACE_AUTO,
                "t_ed_knm": 20.0,
                "check_minimum_reinforcement": True,
            }],
            load_cases.PLASTIC_TABLE_KEY,
        ),
        load_cases.ELASTIC_TABLE_KEY: load_cases.normalise_table(
            [{
                "name": "EL-COMPLETE",
                "description": "Complete cracked SLS reference action",
                "n_long_ed_kn": 0.0,
                "mx_long_ed_knm": 0.0,
                "my_long_ed_knm": 0.0,
                "n_short_ed_kn": 0.0,
                "mx_short_ed_knm": 55.0,
                "my_short_ed_knm": 0.0,
                "calculate_crack_width": True,
            }],
            load_cases.ELASTIC_TABLE_KEY,
        ),
        fatigue_inputs.SPECTRUM_TABLE_KEY:
            fatigue_inputs.normalise_spectrum_table([
                {
                    "spectrum": "Road reference",
                    "name": "FAT-HIGH",
                    "description": "High cyclic range",
                    "cycles": 100000.0,
                    "n_long_ed_kn": 0.0,
                    "mx_long_ed_knm": 5.0,
                    "my_long_ed_knm": 0.0,
                    "n_short_ed_kn": 0.0,
                    "mx_short_ed_knm": 4.0,
                    "my_short_ed_knm": 0.0,
                },
                {
                    "spectrum": "Road reference",
                    "name": "FAT-LOW",
                    "description": "Frequent cyclic range",
                    "cycles": 1000000.0,
                    "n_long_ed_kn": 0.0,
                    "mx_long_ed_knm": 5.0,
                    "my_long_ed_knm": 0.0,
                    "n_short_ed_kn": 0.0,
                    "mx_short_ed_knm": 2.0,
                    "my_short_ed_knm": 0.0,
                },
            ]),
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
                "wall_id": "Left wall",
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
    return tables


def project_scalars() -> dict:
    fatigue_basis = fatigue_inputs.default_basis()
    fatigue_basis["notes"] = "F-036 independent two-bin reference spectrum"
    return {
        "mode": "Both",
        "conc_preset": DK_PRESET,
        "conc_fck": 30.0,
        "conc_gamma_c": 1.45,
        "conc_k_tc": 1.0,
        "conc_alpha_cc": 1.0,
        "conc_eps_c2": 2.0,
        "conc_eps_cu2": 3.5,
        "conc_n": 2.0,
        "conc_Ec": 33.0,
        "sls_fctm": 2.896468153816889,
        material_catalog.MILD_CATALOG_KEY:
            material_catalog.default_catalog("mild"),
        material_catalog.PRESTRESS_CATALOG_KEY:
            material_catalog.default_catalog("prestress"),
        fatigue_inputs.DETAIL_CATALOG_KEY: fatigue_inputs.default_catalog(),
        fatigue_inputs.BASIS_KEY: fatigue_basis,
        "capacity_steel_material_id": "M1",
        "label_scale": 1.0,
        "label_min_gap": 0.04,
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
        "pre_preset": "EN 1992-1-1:2005",
        "pre_IS": 0.0,
        "pre_fytk": 1640.0,
        "pre_futk": 1860.0,
        "pre_eut": 35.0,
        "pre_gamma_y": 1.15,
        "pre_gamma_u": 1.15,
        "pre_gamma_E": 1.0,
        "pre_k": 1.0,
        "pre_ey0t": 0.0,
        "pre_Es": 195.0,
        "v_min": 0.0,
        "v_max": 360.0,
        "v_inc": 30.0,
        "pl_check_util": True,
        "pl_interaction": True,
        "el_phi": 0.0,
        "sls_phi": 0.0,
        "sls_bond": "Ribbed / high bond (k1 = 0.8)",
        "sls_tendon_xi": 0.0,
        "sls_code": "DS/EN 1992-1-1 + DK NA",
        "sls_member": "Beam",
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
        "minimum_reinforcement_on": True,
        "transverse_detailing_on": True,
        "clear_spacing_on": True,
        "detailing_edition": detailing.EC2_2005_DKNA,
        "detailing_member_type": detailing.MEMBER_BEAM,
        "detailing_cut_direction": detailing.CUT_TRANSVERSE,
        "detailing_d_upper": 16.0,
        "detailing_include_tendons": False,
        "transverse_ductility_class": "B",
        "transverse_apply_ductility_reduction": False,
        "shear_on": True,
        "shear_method": DK_PRESET,
        "shear_vx_bw": 0.0,
        "shear_vy_bw": 0.0,
        "shear_dlower": 16.0,
        "shear_links": True,
        "shear_vx_link_legs": 2.0,
        "shear_vy_link_legs": 2.0,
        "shear_link_dia": 10.0,
        "shear_link_s": 150.0,
        "shear_fywk": 500.0,
        "shear_vx_transverse_leg_spacing": 0.0,
        "shear_vy_transverse_leg_spacing": 0.0,
        "strut_cot_min": 1.0,
        "strut_cot_max": 2.5,
        "torsion_on": True,
        "torsion_method": DK_PRESET,
        "torsion_tef": 0.0,
        "torsion_nu_v": False,
        "torsion_gamma_ct": 1.70,
        "torsion_subdivide": False,
        "combined_on": True,
        "combined_method": DK_PRESET,
        "combined_mv_independent": False,
        "bridge_standard": bridge.EN1992_2_DK_NA,
        "rep_proj_no": "SECTOR-F036",
        "rep_proj_name": "Sector complete reproducible example",
        "rep_section": "200 x 300 mm complete reference section",
        "rep_rev": "Reference input set 1",
        "rep_author": "Sector reference calculation",
        "rep_comments": "All main report calculation families enabled.",
        "rep_report_content": "Default report + QA appendix",
        "autosave_on": True,
        "autosave_min": 5,
    }


def input_sha256() -> str:
    return project_io.input_sha256(project_tables(), project_scalars())


def project_json() -> str:
    return project_io.dump_project(
        project_tables(), project_scalars(), app_version=__version__
    )


def checking_pack() -> str:
    """Return the independently derived checking record for the download."""

    return dedent(f"""
        # Sector v{__version__} complete reference checking pack

        Input SHA-256: `{input_sha256()}`
        Project schema: `{project_io.VERSION}`

        This hand pack is completed from original inputs and published equations.
        It does not use a Sector solver as its oracle. The project enables every
        main calculation/report family. The values below retain sufficient digits
        to compare numerical results before report formatting.

        ## Frozen project vector

        - Concrete rectangle: b=0.200 m, h=0.300 m, no voids.
        - Bars: R1/R2, As=500 mm2 at y=-0.120 m; R3/R4, As=400 mm2
          at y=+0.120 m. All use material M1 and fatigue detail F1.
        - Concrete: fck=30 MPa, gamma_c=1.45, alpha_cc=1.0,
          eps_c2=0.002, eps_cu2=0.0035, n=2, Ec=33000 MPa.
        - Steel M1: fyk=550 MPa, gamma_s=1.20, Es=200000 MPa.
        - Plastic case PL-COMPLETE: N=0 kN, Mx=80 kNm, My=10 kNm,
          Vy=30 kN and T=20 kNm.
        - Elastic case EL-COMPLETE: short-term Mx=55 kNm; all other
          long/short actions are zero; crack width is enabled.
        - Fatigue spectrum Road reference: sustained Mx=5 kNm, increments
          4 kNm for 100000 cycles and 2 kNm for 1000000 cycles.

        ## Plastic capacity and applied ray

        At V=90 degrees, integrate the parabola-rectangle concrete stress over
        y_na..0.150 m and the four independent steel forces. Bisection of
        sum(F)=0 gives c=0.057251 m, Fc=+191.777 kN, Fs=-191.777 kN and
        Mx,Rd=111.1862 kNm. The full 30-degree sweep gives:

        - max Mx = 111.1861634625 kNm; min Mx = -89.7293204011 kNm;
        - max My = 54.2925518910 kNm; min My = -54.2925518910 kNm;
        - demand magnitude = sqrt(80^2+10^2) = 80.6225774830 kNm;
        - forward chord resistance = 108.7677576668 kNm;
        - utilisation = 0.7412359987, governing segment index 2.

        ## Cracked elastic and crack width

        With n=Es/Ec=6.0606060606, solve
        b(0.150-y_na)^2/2+n sum[As(y_i-y_na)]=0. This gives
        y_na=0.06034632684 m and Icr=0.000262414719934 m4. For Mx=55 kNm:

        - curvature = 0.006351269727 1/m;
        - top concrete compression = 18.7906837879 MPa;
        - R1/R2 tension = 229.0856332160 MPa;
        - R3/R4 compression = 75.7753136848 MPa.

        The fine short-term DK crack branch has phi=25.23132522 mm,
        clear cover=17.38433739 mm, Ac,eff=15000 mm2, rho_p,eff=1/15,
        sr,max=139.645079986 mm and eps_sm-eps_cm=0.000962424042.
        Therefore wk=0.1343977823 mm, governed by R1 (CALCULATED).

        ## Detailing and member resistance

        - Clear spacing R1-R2: 120-25.23132522=94.76867478 mm;
          required=max(20,25.23132522,16+5)=25.23132522 mm: PASS.
        - Longitudinal minimum area: max(0.26 fctm/fyk,0.0013) bt d
          with bt=174.95547514 mm and d=286.99031153 mm gives
          As,min=68.75023549 mm2 versus As,provided=1000 mm2: PASS.
        - Link area/s = 157.07963268/150=1.047197551 mm2/mm.
          rho_w=0.005235987756 versus rho_w,min=0.000690130422: PASS.
        - Torsion link spacing limit=min(uk/8,minimum dimension)=95 mm;
          150/95=1.578947368: FAIL. This is the genuine detailing verdict.
        - Concrete shear resistance VRd,c=47.59286047 kN; 30/VRd,c
          gives utilisation 0.630346647: PASS.
        - With retained plastic lever arm z=242.58799301 mm and optimum
          cot(theta)=1.206, VRd,s=127.653869995 kN and
          VRd,max=271.275663689 kN. Link utilisation=0.2350105015.
        - For tef=60 mm, Ak=0.0336 m2, TRd,s=17.680883454 kNm,
          TRd,max=15.780839433 kNm and TRd,c=4.808818657 kNm.
          Torsion utilisation=1.2673597045: FAIL (crushing governs).
        - Combined sum=0.741235999+0.235010501+1.267359704
          =2.243606205: FAIL.

        ## Fatigue

        Linear cracked response scales the 55 kNm state. At R1 the two ranges
        are 229.085633216 x 4/55=16.660773325 MPa and x 2/55
        =8.330386662 MPa. Detail F1 has N*=1000000, k1=5, k2=9 and
        Delta sigma Rsk=162.5 MPa. Delta sigma Rd=162.5/1.15
        =141.304347826 MPa, so both ranges use k2=9. Miner damage is
        4.490112462e-10. The governing yield utilisation is
        37.486739981/(550/1.15)=0.0783813654.

        Concrete fcd,fat=0.85 x 30/1.50 x (1-30/250)=14.96 MPa.
        The top fibre has max compressions 3.074839165 MPa and
        2.391541573 MPa, producing total Miner damage 2.071598896e-12
        and stress utilisation 3.074839165/14.96=0.2055373774.
        The adaptive spatial bound stops not converged at depth 26 with
        232 boxes, 1164 points and absolute gap 1.099792897e-8. Therefore the
        spectrum verdict is FAIL because numerical convergence is required, even
        though every retained element/fibre utilisation is below one.

        ## Independent bridge kernels

        - Brittle Method B: As,req=1000x1000/(0.8x500)=2500 mm2;
          2500/3000=0.8333333333: PASS.
        - Box wall: 200/500+50/250=0.6000000000: PASS.
        - Minimum crack reinforcement: As,min=0.4x0.8x3x100000/200
          =480 mm2; 480/600=0.8000000000: PASS.

        ## Report and trace completeness

        A calculated report must contain Section and materials, Basis of analysis,
        Plastic section capacity, Elastic section response, Cracking and crack
        width, Grouped fatigue, Shear resistance, Torsion, M-V-T interaction,
        minimum reinforcement, link detailing, clear spacing, Independent bridge
        calculations and Calculation trace. Every applicable trace must publish
        with zero errors and the same input SHA-256 printed above. This project
        activates CT-002 through CT-005 and CT-008 through CT-011. CT-006 and
        CT-007 are deliberately not separate publications when combined M-V-T is
        enabled: the accepted combined branch owns their one shared strut angle.

        ## Numerical algorithms and failure states

        Plastic axial search starts at c_lo=1e-9 c_full and c_hi=c_full, expands
        the upper bound at most 80 times, bisects at most 100 times and may stop at
        c_hi-c_lo < 1e-12 c_full. Endpoint equality is reachable. Convergence is
        reachability AND |sum(F)-N| <= 1e-6 max(1,|N|); cap exhaustion alone is not
        failure. Cracked Elastic starts from the uncracked plane, or zero for a
        singular initial matrix, reclips concrete every Newton step and requires
        max|R| <= 1e-9 max(1,max|target|) within 100 iterations; a singular tangent
        exits not converged.

        Applied-ray demand below 1e-9 has zero utilisation and no resistance/member.
        Chords with |cross(ray,edge)|<=1e-12 are parallel; accept
        -1e-9<=s<=1+1e-9 and forward t>1e-9, using the nearest crossing. No crossing
        has positive-infinite utilisation and no invented resistance/member. Equal
        endpoint distances select the first endpoint in sweep order.

        Concrete fatigue uses 4 x 4 initial boxes, depth 26, at most 200000 boxes,
        relative tolerance 1e-3 and absolute tolerance 1e-8. Empty or dominated
        unresolved heaps converge; finite damage requires
        upper-best <= 1e-8 + 1e-3 max(|best|,1e-12). A prior depth/box limit is not
        converged. Positive-infinite best damage is the explicit exception:
        upper=best=+infinity and converged=true with infinite recorded gaps.

        Report mechanics and verdicts use retained unrounded values. Decimal and
        significant-digit formatting is presentation only.
    """).strip() + "\n"
