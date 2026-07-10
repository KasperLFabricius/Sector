"""Tests for the PDF report builder (content + robustness, figures disabled)."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import sector_report  # noqa: E402
from sector.materials import Concrete, MildSteel  # noqa: E402


def _inp():
    return {
        "mode": "Both",
        "outer": [(-0.1, -0.15), (0.1, -0.15), (0.1, 0.15), (-0.1, 0.15)],
        "holes": [], "bars": [(0.0, -0.12, 5.0e-4)], "tendons": [],
        "concrete": Concrete(fck=30.0, gamma_c=1.5, curve=2),
        "steel": MildSteel(fytk=500.0, fyck=500.0, futk=500.0, eut=0.05,
                           gamma_y=1.15, curve=2),
        "prestress": None,
        "P_pl": 0.0, "Mx_pl": 100.0, "My_pl": 0.0,
        "P_el_l": 0.0, "Mx_el_l": 80.0, "My_el_l": 0.0,
        "P_el_s": 0.0, "Mx_el_s": 20.0, "My_el_s": 0.0,
        "nl": 15.0, "ns": 6.0, "sls_fctm": 2.9, "sls_cw": True,
        "v_min": 0.0, "v_max": 360.0, "v_inc": 90.0,
    }


def _crack():
    # Units as returned by CrackWidthResult: wk/sr_max/phi/cover in mm; hc_ef in m;
    # ac_eff in m^2; esm_ecm dimensionless.
    return {"wk": 0.213, "sr_max": 235.0, "esm_ecm": 8.4e-4, "sigma_s": 215.0,
            "rho_p_eff": 0.04, "ac_eff": 0.0125, "hc_ef": 0.125, "phi": 16.0,
            "cover": 40.0, "gov_bar": 1}


def _out():
    return {
        "plastic": {"mx": [100.0, 0.0, -100.0, 0.0], "my": [0.0, 100.0, 0.0, -100.0],
                    "max_mx": 100.0, "max_my": 100.0, "min_mx": -100.0, "min_my": -100.0,
                    "util": 0.8, "closed": True,
                    "check_util": True, "applied": (80.0, 0.0), "converged": True,
                    "points": [{"V": 0.0, "Mx": 100.0, "My": 0.0, "na_x": 0.0,
                                "na_y": 0.05, "eps_c": 0.35, "eps_s": 2.0,
                                "eps_s_comp": -0.1, "eps_cable": 0.0, "kappa": 0.02,
                                "comp_force": 300.0, "lever": 0.2, "dx": 0.0,
                                "dy": 0.2}]},
        "elastic": {"total": [150.0], "long": [120.0], "dif": [30.0], "rst1": [0.0],
                    "max_conc": 12.0, "max_conc_xy": (0.0, 0.15), "max_conc_point": 3,
                    "na_x": 0.0, "na_y": 0.04, "max_steel": 150.0, "max_steel_bar": 1,
                    "converged": True, "cracked": True, "lambda_cr": 0.4,
                    "sigma_ct": 7.2, "fctm": 2.9, "show_cw": True,
                    "props_un": {"area": 0.06, "cx": 0.0, "cy": 0.0, "Ix": 4.5e-4,
                                 "Iy": 2.0e-4, "Ixy": 0.0},
                    "props_cr": {"area": 0.03, "cx": 0.0, "cy": 0.02, "Ix": 2.1e-4,
                                 "Iy": 1.0e-4, "Ixy": 0.0},
                    "crack": _crack(), "crack_short": _crack(),
                    "crack_code": "EN 1992-1-1:2005", "crack_member": None}}


def test_report_pdf_generates():
    pdf = sector_report.build_report({"proj_no": "P-1", "author": "KLA"},
                                     _inp(), _out(), version="0.1.0", figures=False)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 3000


def test_report_mirrors_the_views():
    txt = _pdf_text(sector_report.build_report({}, _inp(), _out(), figures=False))
    assert "Comp" in txt and "NA x" in txt         # full plastic table columns
    assert "Cracked" in txt                        # cracked transformed-props column
    assert "both load cases" in txt                # full crack-width table
    assert "Sweep start" in txt                    # explicit Vstart/Vend/Vinc
    assert "Utilisation check" in txt              # analysis settings documented
    assert "Max / Min" in txt                      # both extremes for Mx and My


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
    out["elastic"]["crack"] = dict(_crack(), sr_max_geometric=True)
    out["elastic"]["crack_short"] = dict(_crack(), sr_max_geometric=True)
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "(7.14)" in txt
    assert "close centres" in txt


def test_report_dk_na_shows_fine_and_coarse_columns():
    # The DK NA option reports the fine and the coarse crack system side by side,
    # each for both load cases (four crack-width columns).
    out = _out()
    out["elastic"]["crack"] = dict(_crack(), coarse=False, wk=0.20)
    out["elastic"]["crack_short"] = dict(_crack(), coarse=False, wk=0.25)
    out["elastic"]["crack_coarse"] = dict(_crack(), coarse=True, wk=0.10)
    out["elastic"]["crack_short_coarse"] = dict(_crack(), coarse=True, wk=0.12)
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
    out["elastic"]["crack_coarse"] = dict(_crack(), coarse=True)
    out["elastic"]["crack_short_coarse"] = dict(_crack(), coarse=True)
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
    out["elastic"]["crack_coarse"] = dict(_crack(), coarse=True, wk=0.30)
    out["elastic"]["crack_short_coarse"] = dict(_crack(), coarse=True, wk=0.30)
    out["elastic"]["crack_code"] = "DS/EN 1992-1-1 + DK NA"
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert chr(0xBD) in txt            # the 1/2 glyph rendered in Eq (7.8)


def test_report_ec2_2023_shows_refined_formula():
    # The EN 1992-1-1:2023 worked example shows the refined (9.8) formula with kw.
    out = _out()
    out["elastic"]["crack"] = dict(_crack(), edition="2023", kw=1.7, k1_r=1.13, kfl=0.77)
    out["elastic"]["crack_short"] = dict(_crack(), edition="2023", kw=1.7, k1_r=1.13,
                                         kfl=0.77)
    out["elastic"]["crack_code"] = "EN 1992-1-1:2023"
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "9.8" in txt and "9.2.3" in txt      # the 2023 clause and crack formula
    assert "1.7" in txt                          # kw in the worked substitution


def test_ensure_image_server_starts_once(monkeypatch):
    # The app-wide kaleido server starts exactly once per process (even across
    # threads / repeated calls) and is registered to stop only at interpreter exit,
    # not after each report -- so a second report reuses the running browser.
    calls = {"start": 0, "stop": 0, "atexit": 0}
    monkeypatch.setattr(sector_report, "_kaleido_server_api",
                        lambda: ((lambda **k: calls.__setitem__("start", calls["start"] + 1)),
                                 (lambda **k: calls.__setitem__("stop", calls["stop"] + 1))))
    monkeypatch.setattr(sector_report.atexit, "register",
                        lambda f: calls.__setitem__("atexit", calls["atexit"] + 1))
    monkeypatch.setattr(sector_report, "_image_server_started", False)
    for _ in range(3):
        sector_report.ensure_image_server()
    assert calls["start"] == 1            # started once despite three calls
    assert calls["atexit"] == 1           # stop deferred to interpreter exit
    assert calls["stop"] == 0             # never stopped mid-session


def test_ensure_image_server_without_kaleido_is_safe(monkeypatch):
    # No kaleido / no sync-server API: it must not raise and must not retry.
    monkeypatch.setattr(sector_report, "_kaleido_server_api", lambda: (None, None))
    monkeypatch.setattr(sector_report, "_image_server_started", False)
    sector_report.ensure_image_server()
    assert sector_report._image_server_started is True


def test_tables_only_report_does_not_start_the_image_server(monkeypatch):
    # A figures-disabled report renders no figures, so it must not launch a browser.
    calls = {"n": 0}
    monkeypatch.setattr(sector_report, "ensure_image_server",
                        lambda: calls.__setitem__("n", calls["n"] + 1))
    sector_report.build_report({}, _inp(), _out(), figures=False)
    assert calls["n"] == 0


def test_report_includes_the_nm_interaction_when_present():
    # An opt-in N-M interaction payload (both bending axes) adds titled sections to
    # the plastic part.
    out = _out()
    branch = dict(N=[-500.0, 0.0, 1500.0, 4000.0], M=[80.0, 300.0, 340.0, 0.0],
                  applied=(200.0, 100.0), converged=True)
    out["plastic"]["interaction"] = dict(x=branch, y=branch)
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "interaction" in txt.lower()
    assert "squash" in txt.lower()
    assert "N-M" in txt or ("Mx" in txt and "My" in txt)   # both axes titled


def test_report_handles_plastic_only():
    out = {"plastic": _out()["plastic"]}
    pdf = sector_report.build_report({}, _inp(), out, figures=False)
    assert pdf[:4] == b"%PDF"


def test_report_capacity_only_omits_utilisation():
    # A capacity-only run (utilisation not checked) reports no utilisation value.
    out = _out()
    out["plastic"].update(util=None, check_util=False, applied=None)
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


def _shear_out_2023():
    return {"res": {"vrd_c": 85.4, "tau_rdc": 0.575, "tau_basic": 0.575,
                    "tau_min": 0.538, "rho_l": 0.00893, "z": 495.0, "ddg": 32.0,
                    "fyd": 434.8, "gamma_v": 1.40, "model": "2023", "valid": True},
            "v_ed": 50.0, "util": 50.0 / 85.4, "axis": "x", "tension_low": True,
            "bw": 300.0, "bw_auto": 300.0, "bw_user": False, "d": 550.0,
            "asl": 1473.0, "ac": 0.18, "fck": 35.0, "n_ed": 0.0,
            "method": "DS/EN 1992-1-1:2023", "model_2023": True, "ddg": 32.0,
            "fyd_flex": 434.8}


def test_report_shear_2023_section():
    out = _out()
    out["shear"] = _shear_out_2023()
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "8.27" in txt and "8.20" in txt          # the 2023 clauses
    assert "8.2.2" in txt                            # the 2023 section reference
    assert "85.4" in txt                             # VRd,c
    assert "d" in txt and "dg" in txt                # ddg appears


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


def test_report_shear_2023_tension_warning():
    # F2: the 2023 tau_Rd,c ignores a net axial tension -- warn in the report.
    out = _out()
    sh = _shear_out_2023()
    sh["n2023_tension"] = True
    out["shear"] = sh
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "UNCONSERVATIVE" in txt


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
    tube = {"A": 0.18, "u": 1.8, "tef": 100.0, "Ak": 0.1, "uk": 1.4,
            "tef_auto": 100.0, "tef_capped": False, "tef_user": False,
            "hollow": False, "valid": True}
    out = {"tube": tube, "trd_s": 76.4, "trd_max": 76.4, "trd": 76.4, "trd_c": 31.0,
           "cot": 1.751, "theta_deg": 29.7, "util": 40.0 / 76.4, "asl_req": 1176.0,
           "t_ed": 40.0, "fcd": 24.14, "fywd": 416.67, "fyd_long": 416.67,
           "nu": 0.3675, "alpha_cw": 1.0, "fctd": 1.55, "asw_t": 78.5,
           "asw_over_s": 0.5236, "dia": 10.0, "s": 150.0, "cot_min": 1.0,
           "cot_max": 2.5, "method": "DS/EN 1992-1-1:2005 + DK NA:2024",
           "governs": "stirrups (TRd,s)", "valid": True, "cot_limit_lo": 1.0,
           "cot_limit_hi": 2.5, "out_of_limits": False}
    if interaction:
        out["interaction"] = dict(valid=True, cot=1.0, theta_deg=45.0, trd_max=88.7,
                                  vrd_max=650.0, t_ed=40.0, v_ed=150.0,
                                  value=40.0 / 88.7 + 150.0 / 650.0)
    return out


def test_report_includes_torsion_section():
    out = _out()
    out["torsion"] = _torsion_out()
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Torsion" in txt
    assert "6.30" in txt and "6.28" in txt          # the clause formulae
    assert "76.4" in txt                            # TRd
    assert chr(0x3B8) in txt                        # theta glyph rendered
    assert "1176" in txt                            # required Asl


def _subtube(b, h, tef, ak, c, ted, trd, util, gov):
    return dict(tube={"tef": tef, "Ak": ak, "valid": True}, b_mm=b, h_mm=h,
                stiffness=c, t_ed=ted, trd=trd, util=util, governs=gov,
                trd_s=trd, trd_max=trd + 5.0, trd_c=trd * 0.4, cot=1.75, nu=0.37)


def test_report_torsion_subdivided():
    out = _out()
    t = _torsion_out()
    t["subdivided"] = True
    t["subtubes"] = [
        _subtube(300, 600, 100.0, 0.10, 0.0037, 24.6, 90.0, 24.6 / 90.0,
                 "stirrups (TRd,s)"),
        _subtube(1000, 200, 91.0, 0.15, 0.0023, 15.4, 58.5, 15.4 / 58.5,
                 "crushing (TRd,max)")]
    t["trd"] = 148.5
    t["util"] = 40.0 / 148.5
    t["asl_req"] = 1400.0
    out["torsion"] = t
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Sub-tubes" in txt                        # the compound-section heading
    assert "6.3.1(3)" in txt                         # the sub-division clause
    assert "web" in txt


def test_report_torsion_shows_combined_interaction():
    out = _out()
    out["torsion"] = _torsion_out(interaction=True)
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "6.29" in txt                            # the combined crushing clause
    assert "Combined shear" in txt


def test_report_torsion_shows_min_reinf_screen():
    # F7: the 6.31 minimum-reinforcement screen appears when applicable.
    out = _out()
    t = _torsion_out()
    t["min_reinf"] = dict(applicable=True, value=0.52, ok=True, t_ed=40.0,
                          trd_c=31.0, v_ed=30.0, vrd_c=136.0, solid=True,
                          model_2023=False)
    out["torsion"] = t
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "6.31" in txt                            # the screen clause
    assert "minimum reinforcement suffices" in txt  # the verdict wording


def _combined_out(mv_independent=False):
    return {"valid": True, "method": "DS/EN 1992-1-1:2005 + DK NA:2024",
            "r_m": 0.6, "r_v": 0.4, "r_t": 0.3, "m_v_independent": mv_independent,
            "dkna_sum": (max(0.9, 0.7) if mv_independent else 1.3),
            "dkna_ok": (max(0.9, 0.7) if mv_independent else 1.3) <= 1.0,
            "crushing": dict(valid=True, cot=1.0, theta_deg=45.0, trd_max=88.7,
                             vrd_max=650.0, t_ed=40.0, v_ed=150.0,
                             value=40.0 / 88.7 + 150.0 / 650.0),
            "asl_torsion": 1176.0, "delta_ftd": 200.0, "links": True}


def test_report_includes_combined_section():
    out = _out()
    out["combined"] = _combined_out()
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Combined bending" in txt or "M-V-T" in txt
    assert "6.3.2(6)" in txt                        # the DK NA combined rule
    assert "EXCEEDED" in txt                        # sum 1.3 > 1


def test_report_combined_longitudinal_check():
    out = _out()
    c = _combined_out()
    c["longitudinal"] = dict(valid=True, axis="x", z=0.54, m_ed=100.0, m_rd=400.0,
                             ftd_v=200.0, ftd_t=120.0, mv=108.0, mt=32.4,
                             m_total=240.4, util=240.4 / 400.0, ok=True, capped=False)
    out["combined"] = c
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Longitudinal reinforcement" in txt
    assert "6.2.3(7)" in txt                        # the shear-shift cap clause
    assert "tension chord" in txt


def test_report_combined_longitudinal_biaxial_warns():
    out = _out()
    c = _combined_out()
    c["longitudinal"] = dict(valid=True, axis="x", z=0.5, m_ed=20.0, m_rd=300.0,
                             ftd_v=187.5, ftd_t=100.0, mv=60.0, mt=25.0, m_total=105.0,
                             util=105.0 / 300.0, ok=True, capped=False,
                             tension_low=True, off_util=0.83, biaxial=True)
    out["combined"] = c
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Biaxial bending" in txt                 # the off-axis warning
    assert "off-axis chord" in txt


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
    assert "crushing utilisation" in txt            # crushing shown separately
    assert "Governing (stirrups)" in txt            # governing labelled by mechanism


def test_report_skips_invalid_combined():
    out = _out()
    out["combined"] = {"valid": False, "have_m": True, "have_v": False,
                       "have_t": False, "method": "x"}
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Combined bending" not in txt


def _links_out():
    return {"res": {"vrd_s": 540.0, "vrd_max": 648.9, "vrd": 540.0, "cot": 2.5,
                    "theta_deg": 21.8, "z": 495.0, "fywd": 416.67, "nu1": 0.525,
                    "alpha_cw": 1.0, "sigma_cp": 0.0, "fcd": 24.14,
                    "governs": "stirrups (VRd,s)", "valid": True},
            "util": 80.0 / 540.0, "asw": 157.08, "asw_over_s": 1.047, "legs": 2.0,
            "dia": 10.0, "s": 150.0, "fywk": 500.0, "cot_min": 1.0, "cot_max": 2.5,
            "delta_ftd": 375.0, "cot_limit_lo": 1.0, "cot_limit_hi": 2.5,
            "z_source": "plastic internal lever arm",
            "out_of_limits": False, "required": True}


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


def test_report_shear_links_out_of_limits_note():
    out = _out()
    sh = _shear_out()
    lk = _links_out()
    lk["cot_max"], lk["out_of_limits"] = 3.0, True
    sh["links"] = lk
    out["shear"] = sh
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "outside the code range" in txt


def test_fig_png_times_out_instead_of_hanging():
    # v0.62: the report's kaleido export runs off the main thread with a join
    # timeout, so a stuck browser yields a placeholder (None) instead of freezing
    # report generation -- matching the manual's export guard.
    import time

    class _SlowFig:
        def to_image(self, **kw):
            time.sleep(5.0)
            return b"never"

    assert sector_report._fig_png(_SlowFig(), 100, 100, timeout=0.3) is None
