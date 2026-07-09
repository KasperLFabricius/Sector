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


def test_report_handles_uncracked_section():
    out = _out()
    out["elastic"]["cracked"] = False
    out["elastic"]["crack"] = None
    out["elastic"]["crack_short"] = None
    out["elastic"]["props_cr"] = None
    pdf = sector_report.build_report({}, _inp(), out, figures=False)
    assert pdf[:4] == b"%PDF"
