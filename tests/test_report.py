"""Tests for the PDF report builder (content + robustness, figures disabled)."""

from __future__ import annotations

import copy
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import sector_report  # noqa: E402
import material_catalog  # noqa: E402
from sector.materials import Concrete, MildSteel  # noqa: E402


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
        "design_basis": {
            "status": "Edition-aligned: EN 1992-1-1:2005",
            "components": [
                {"role": "Concrete material", "selection": "EN 1992-1-1:2005"},
                {"role": "Reinforcing steel", "selection": "EN 1992-1-1:2005"},
            ],
            "mixed": False, "limitations": [],
        },
        "P_pl": 0.0, "Mx_pl": 100.0, "My_pl": 0.0,
        "P_el_l": 0.0, "Mx_el_l": 80.0, "My_el_l": 0.0,
        "P_el_s": 0.0, "Mx_el_s": 20.0, "My_el_s": 0.0,
        "nl": 15.0, "ns": 6.0, "sls_fctm": 2.9, "sls_cw": True,
        "conc_Ec": 33.0,
        "sls_wk_limit": 0.30, "sls_conc_limit_pct": 60.0,
        "sls_steel_limit_pct": 80.0, "sls_pre_limit_pct": 75.0,
        "sls_limit_source": "DB-SLS-01 section 4",
        "v_min": 0.0, "v_max": 360.0, "v_inc": 90.0,
    }


def _crack():
    # Units as returned by CrackWidthResult: wk/sr_max/phi/cover in mm; hc_ef in m;
    # ac_eff in m^2; esm_ecm dimensionless.
    candidate = {
        "element_type": "Bar", "element_no": 1, "element_id": "bar 1",
        "x_mm": 0.0, "y_mm": -120.0, "area_mm2": 500.0,
        "wk": 0.213, "sr_max": 235.0, "esm_ecm": 8.4e-4,
        "sigma_s": 215.0, "rho_p_eff": 0.04, "ac_eff": 0.0125,
        "hc_ef": 0.125, "phi": 16.0, "cover": 40.0,
        "coarse": False, "edition": "2004", "kw": 1.0,
        "k1_r": 1.0, "kfl": 1.0, "sr_max_geometric": False,
    }
    return dict(candidate, gov_bar=1, candidates=[candidate])


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
                        "dif_mpa": 30.0, "rst1_mpa": 0.0,
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
                    "stress_assessments": {
                        "concrete": {"value": 12.0, "limit": 18.0, "util": 2/3,
                                     "margin": 6.0, "status": "OK",
                                     "criterion": "60% fck"},
                        "reinforcement": {"value": 150.0, "limit": 400.0,
                                          "util": 0.375, "margin": 250.0,
                                          "status": "OK", "criterion": "80% fyk",
                                          "governing": "bar 1"},
                        "prestress": {"value": None, "limit": None, "util": None,
                                      "margin": None, "status": "NOT APPLICABLE",
                                      "criterion": "75% fpk"},
                    },
                    "sls_limit_source": "DB-SLS-01 section 4",
                    "sls_wk_limit": 0.30,
                    "props_un": {"area": 0.06, "cx": 0.0, "cy": 0.0, "Ix": 4.5e-4,
                                 "Iy": 2.0e-4, "Ixy": 0.0},
                    "props_cr": {"area": 0.03, "cx": 0.0, "cy": 0.02, "Ix": 2.1e-4,
                                 "Iy": 1.0e-4, "Ixy": 0.0},
                    "crack": _crack(), "crack_short": _crack(),
                    "crack_assessment": {
                        "value": 0.213, "limit": 0.30, "util": 0.71,
                        "margin": 0.087, "status": "OK",
                        "case": "Long-term", "governing": "bar 1",
                        "criterion": "0.3 mm",
                    },
                    "crack_code": "EN 1992-1-1:2005", "crack_member": None}}


def test_report_pdf_generates():
    pdf = sector_report.build_report(
        {"proj_no": "P-1", "author": "KLA", "source_revision": "a" * 40},
        _inp(), _out(), version="0.1.0", figures=False,
    )
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 3000


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
             "fatigue_detail_id": "", "group_id": "B1"},
            {"id": "R2", "x_mm": 0.0, "y_mm": 120.0,
             "area_mm2": 400.0, "diameter_mm": 22.57,
             "size_mode": "Area", "material_id": second_id,
             "fatigue_detail_id": "", "group_id": "B2"},
        ],
        "mild_material_catalog": catalogue,
        "mild_materials": laws,
        "bar_materials": [laws["M1"], laws[second_id]],
        "steel": laws["M1"],
        "capacity_steel_material_id": second_id,
    })

    txt = _pdf_text(sector_report.build_report(
        {}, inp, _out(), figures=False,
    ))
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
            "fatigue_detail_id": "", "group_id": "",
        }],
        "prestress_material_catalog": catalogue,
        "prestress_materials": {"P1": law},
        "tendon_materials": [law],
        "prestress": law,
        "prestress_preset": entry["preset"],
    })

    txt = _pdf_text(sector_report.build_report({}, inp, _out(), figures=False))
    flat = " ".join(txt.split())

    assert "Built-in fixed curve 1" in flat
    assert "Characteristic stress at rupture strain" in flat
    assert "1645.000 MPa" in flat
    assert "Proof strength" not in flat
    assert "Ultimate strength" not in flat
    assert "normative source not assigned" in flat


@pytest.mark.parametrize(
    "preset",
    ["Custom / imported", "Curve 1 (bilinear hardening)"],
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
            "fatigue_detail_id": "", "group_id": "",
        }],
        "mild_material_catalog": catalogue,
        "mild_materials": {"M1": law},
        "bar_materials": [law],
        "steel": law,
    })

    flat = " ".join(_pdf_text(sector_report.build_report(
        {}, inp, _out(), figures=False,
    )).split())

    assert "no normative curve source assigned" in flat
    assert "3.2.7" not in flat


def test_report_footer_identifies_the_organisational_licensee():
    txt = _pdf_text(sector_report.build_report(
        {"source_revision": "abcdef1234567890"},
        _inp(),
        _out(),
        version="0.90",
        figures=False,
    ))
    assert "Sector 0.90 - abcdef123456 - Sweco Danmark A/S" in " ".join(txt.split())


def test_report_front_matter_identifies_action_sets_and_result_statuses():
    txt = _pdf_text(sector_report.build_report(
        {"source_revision": "abcdef1234567890"},
        _inp(),
        _out(),
        figures=False,
    ))
    assert "Results overview - PASS" in txt
    assert "PL-TEST" in txt and "EL-TEST" in txt
    assert "Combination register C1" in txt
    assert "Combination register C2" in txt
    assert "abcdef123456" in txt
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
            "check_stress": True, "check_crack_width": True,
        },
        {
            "name": "EL-02", "description": "Frequent response",
            "n_long_ed_kn": 0.0, "mx_long_ed_knm": 45.0,
            "my_long_ed_knm": 0.0, "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 10.0, "my_short_ed_knm": 0.0,
            "check_stress": True, "check_crack_width": False,
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

    txt = _pdf_text(sector_report.build_report({}, inp, out, figures=False))
    flat = " ".join(txt.split())
    assert "Results overview - FAIL" in flat
    assert all(case in flat for case in ("PL-01", "PL-02", "EL-01", "EL-02"))
    assert "Governing combination" in flat and "Frequent response" in flat
    assert flat.count(". Plastic section capacity") == 2
    assert flat.count(". Elastic section response and stress limits") == 2
    assert "Plastic section capacity - PL-02" in flat
    assert "Elastic section response and stress limits - EL-02" in flat
    assert "Cracking threshold - EL-02" in flat
    assert "Acceptance: stress limits on; crack width off." in flat
    assert "Gov. marks the highest PASS/FAIL utilisation" in flat
    assert "125.0 %" in flat
    assert "456.000 MPa" in flat


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
    assert "Fc" in txt and "NA x" in txt           # full plastic table columns
    assert "PASS - Plastic bending" in txt
    assert "margin +20.0 pp" in flat
    assert "does not exceed" not in flat
    assert "PASS - Crack width | governing" in flat
    assert "Governing concrete corner response" in txt
    assert "Governing reinforcement and tendon response" in txt
    assert "Cracked" in txt                        # cracked transformed-props column
    assert "both load cases" in txt                # full crack-width table
    assert "Sweep start" in txt                    # explicit Vstart/Vend/Vinc
    assert "Utilisation check" in txt              # analysis settings documented
    assert "Max / Min" in txt                      # both extremes for Mx and My


def test_report_includes_sls_criteria_strain_and_candidate_evidence():
    txt = _pdf_text(sector_report.build_report({}, _inp(), _out(), figures=False))
    assert "Stress-limit assessment" in txt
    assert "DB-SLS-01 section 4" in txt
    assert "60% fck" in txt and "80% fyk" in txt
    assert "Ixy" in txt
    assert "Reinforcement and tendon response" in txt
    assert "Concrete corner stress and strain" in txt
    assert "Crack-width candidates" in txt
    assert "Crack-width element diameter" in txt
    assert "Element diameter" in txt
    assert "Bar diameter" not in txt
    assert "bar 1" in txt
    assert "0.300 mm" in txt and "0.213 mm" in txt


def test_report_does_not_round_small_nonzero_product_inertia_to_zero():
    out = _out()
    out["elastic"]["props_un"]["Ixy"] = 1.234567e-8
    out["elastic"]["props_cr"]["Ixy"] = -2.345678e-9
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "1.23457e-08" in txt
    assert "-2.34568e-09" in txt


def test_crack_candidate_table_stays_inside_a4_content_width():
    assert sum(sector_report._CRACK_CANDIDATE_COL_WIDTHS) <= \
        sector_report._A4_CONTENT_WIDTH


def test_report_marks_nonconverged_elastic_results_invalid():
    out = _out()
    out["elastic"]["converged"] = False
    for item in out["elastic"]["stress_assessments"].values():
        item["status"] = "INVALID"
    out["elastic"]["crack_assessment"]["status"] = "INVALID"
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "INVALID - Elastic result" in txt
    assert "diagnostic only" in txt
    assert "no verified cracking classification" in txt


def test_report_keeps_crack_criterion_when_no_width_is_calculated():
    out = _out()
    elastic = out["elastic"]
    elastic.update(
        cracked=False,
        crack=None,
        crack_short=None,
        crack_assessment={
            "value": None,
            "limit": 0.30,
            "util": None,
            "margin": None,
            "status": "NOT APPLICABLE",
            "case": None,
            "governing": None,
            "criterion": "0.3 mm",
        },
    )
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "NOT APPLICABLE" in txt
    assert "limit 0.300 mm" in txt
    assert "No crack width:" in txt
    assert "DB-SLS-01 section 4" in txt


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
    assert "Numerical N-M boundary" in txt
    assert "4000.000" in txt                               # exact boundary values tabulated


def test_long_nm_boundary_repeats_its_numeric_traceability_header():
    out = _out()
    branch = {
        "N": [float(index * 25 - 1000) for index in range(90)],
        "M": [float(300 - abs(index - 45) * 5) for index in range(90)],
        "applied": (0.0, 80.0),
        "converged": True,
    }
    out["plastic"]["interaction"] = {"x": branch, "y": branch}
    pdf = sector_report.build_report({}, _inp(), out, figures=False)

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
    assert "margin -25.0 pp" in txt

    invalid = _out()
    invalid["plastic"]["converged"] = False
    txt = _pdf_text(sector_report.build_report({}, _inp(), invalid, figures=False))
    assert "INVALID - Plastic bending" in txt
    assert "diagnostic only" in txt


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
    txt = _pdf_text(sector_report.build_report({}, inp, {}, figures=False))
    assert "5.1.6" in txt and "5.3" in txt and "5.4" in txt
    assert "8.1.2" in txt and "8.4" in txt
    assert "0.85" in txt
    assert f"{eta:.6f}" in txt
    assert f"{0.85 * eta:.6f}" in txt
    assert f"{inp['concrete'].fcd:.3f}" in txt
    assert "3.15" not in txt


def test_report_ec2_2023_k_tc_one_states_the_full_assumption():
    inp = _inp()
    inp["concrete_preset"] = "DS/EN 1992-1-1:2023"
    inp["concrete_eta_cc"] = 1.0
    inp["concrete_k_tc"] = 1.0
    inp["mild_preset"] = "DS/EN 1992-1-1:2023"
    txt = _pdf_text(sector_report.build_report({}, inp, {}, figures=False))
    assert "28 days" in txt and "56 days" in txt
    assert "at least 3 months" in txt
    assert "National" in txt and "Annex" in txt


def test_report_discloses_mixed_design_basis_and_scope_limitations():
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
    assert "Design basis qualification" in txt
    assert "Mixed/custom design basis" in txt
    assert "Scope limitation" in txt
    assert "does not implement the torsion check" in txt


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


def test_report_biaxial_shear_separates_directions_and_withholds_interaction():
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
        governing_component="vx",
        biaxial=True,
        interaction_assessed=False,
        interaction_status="NOT ASSESSED",
        status="REVIEW",
    )

    txt = " ".join(_pdf_text(
        sector_report.build_report({}, _inp(), out, figures=False)
    ).split())

    assert "Vx,Ed" in txt and "Vy,Ed" in txt
    assert "independent Vx/Vy checks" in txt
    assert "Biaxial interaction: NOT ASSESSED" in txt
    assert "undocumented interaction" in txt


def _shear_out_2023():
    from sector import codes as _codes, shear as _shear

    fyd = 500.0 / 1.15
    res = _shear.vrd_c_2023(
        35.0, _codes.EC2_2023, 300.0, 550.0, 1473.0, fyd, 32.0,
        n_ed_tension_kn=300.0, m_ed_knm=110.0, v_ed_kn=50.0,
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
    assert "d" in txt and "dg" in txt                # ddg appears
    assert "k" in txt and "vp" in txt                # k_vp appears


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
           "cot_limit_hi": 2.5, "out_of_limits": False, "code_applicable": True}
    if interaction:
        out["interaction"] = dict(valid=True, cot=1.0, theta_deg=45.0, trd_max=88.7,
                                  vrd_max=650.0, t_ed=40.0, v_ed=150.0,
                                  value=40.0 / 88.7 + 150.0 / 650.0,
                                  code_applicable=True)
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


def _subtube(b, h, tef, ak, c, ted, trd, util, gov, cx=0.0, cy=0.0):
    return dict(tube={"tef": tef, "Ak": ak, "valid": True}, b_mm=b, h_mm=h,
                x_mm=cx, y_mm=cy,
                stiffness=c, t_ed=ted, trd=trd, util=util, governs=gov,
                trd_s=trd, trd_max=trd + 5.0, trd_c=trd * 0.4, cot=1.75, nu=0.37)


def test_report_torsion_subdivided():
    out = _out()
    t = _torsion_out(interaction=True)               # subdivided run with shear links
    subs = [_subtube(300, 600, 100.0, 0.10, 0.0037, 24.6, 90.0, 24.6 / 90.0,
                     "stirrups (TRd,s)", 0.0, -100.0),
            _subtube(1000, 200, 91.0, 0.15, 0.0023, 15.4, 20.0, 15.4 / 20.0,
                     "crushing (TRd,max)", 0.0, 300.0)]
    t["subdivided"] = True
    t["subtubes"] = subs
    t["trd"] = 110.0
    # P1: governing = the worst sub-tube (part 2 here), not the pooled TEd/sum(TRd).
    t["util"] = max(s["util"] for s in subs)
    t["governing_sub"] = 1
    t["asl_req"] = 1400.0
    out["torsion"] = t
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Sub-tubes" in txt                        # the compound-section heading
    assert "6.3.1(3)" in txt                         # the sub-division clause
    assert "web" in txt
    assert "governing" in txt                        # P1: governing (max) utilisation
    assert "6.29" in txt                             # P2: crushing printed in sub-report


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
    assert "Torsion not evaluated" in txt
    assert "positioned sub-rectangles" in txt
    assert "No torsion or dependent interaction compliance verdict" in txt


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


def test_report_biaxial_shear_torsion_has_two_screens_and_no_three_way_verdict():
    out = _out()
    vx = _combined_out(mv_independent=True)
    vy = copy.deepcopy(vx)
    vx.update(dkna_sum=0.70, dkna_ok=True)
    vy.update(r_v=0.35, dkna_sum=0.65, dkna_ok=True)
    out["combined"] = dict(
        vx,
        directions={"vx": vx, "vy": vy},
        biaxial=True,
        interaction_assessed=False,
        interaction_status="NOT ASSESSED",
        status="REVIEW",
    )

    txt = " ".join(_pdf_text(
        sector_report.build_report({}, _inp(), out, figures=False)
    ).split())

    assert "Vx+T and Vy+T screens" in txt
    assert "simultaneous Vx,Ed + Vy,Ed + TEd interaction is NOT ASSESSED" in txt
    assert "no three-component interaction expression is inferred" in txt


def test_report_combined_out_of_range_withholds_dependent_verdicts():
    out = _out()
    c = _combined_out()
    c["code_applicable"] = False
    c["crushing"]["code_applicable"] = False
    c["longitudinal"] = dict(
        valid=True, axis="x", z=0.54, m_ed=100.0, m_rd=400.0,
        ftd_v=200.0, ftd_t=120.0, mv=108.0, mt=32.4,
        m_total=240.4, util=240.4 / 400.0, ok=True, capped=False,
    )
    out["combined"] = c
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "exploratory" in txt
    assert txt.count("NO CODE VERDICT") >= 3


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


def test_report_combined_longitudinal_biaxial_fallback_warns():
    # Only the FALLBACK path (conditional solve failed -> pure-axis MRd) warns;
    # a successful conditional MRd is the honest capacity and needs no warning.
    out = _out()
    c = _combined_out()
    c["longitudinal"] = dict(valid=True, axis="x", z=0.5, m_ed=20.0, m_rd=300.0,
                             ftd_v=187.5, ftd_t=100.0, mv=60.0, mt=25.0, m_total=105.0,
                             util=105.0 / 300.0, ok=True, capped=False,
                             tension_low=True, off_util=0.83, biaxial=True,
                             m_off=90.0, conditional=False)
    out["combined"] = c
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "Biaxial bending" in txt                 # the fallback warning
    assert "pure-axis fallback" in txt


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
    out["combined"] = c
    # Collapse the PDF's line wrapping so multi-word phrases can be asserted.
    txt = " ".join(_pdf_text(sector_report.build_report({}, _inp(), out,
                                                        figures=False)).split())
    assert "conditional on the coexisting My = 90.0 kNm" in txt
    assert "Biaxial bending" not in txt
    assert "pure-axis fallback" not in txt


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
    out["combined"] = c
    txt = " ".join(_pdf_text(sector_report.build_report({}, _inp(), out,
                                                        figures=False)).split())
    assert "per sub-tube" in txt                     # the subdivided disclosure fired


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
    out["combined"] = c
    txt = " ".join(_pdf_text(sector_report.build_report({}, _inp(), out,
                                                        figures=False)).split())
    assert "may not be the critical face" in txt


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
                          tension_low=True, m_off=20.0, conditional=True)
    out["combined"] = c
    txt = " ".join(_pdf_text(sector_report.build_report({}, _inp(), out,
                                                        figures=False)).split())
    assert "Off-axis chord (about y" in txt          # header now names the governing face
    assert "conditional on the coexisting Mx = 20.0 kNm" in txt


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
            "out_of_limits": False, "code_applicable": True, "required": True}


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
    lk["cot_max"], lk["out_of_limits"], lk["code_applicable"] = 3.0, True, False
    sh["links"] = lk
    out["shear"] = sh
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "outside the code range" in txt
    assert "NO CODE VERDICT" in txt


def test_report_torsion_out_of_limits_withholds_verdict():
    out = _out()
    t = _torsion_out()
    t["cot_max"], t["out_of_limits"], t["code_applicable"] = 3.0, True, False
    out["torsion"] = t
    txt = _pdf_text(sector_report.build_report({}, _inp(), out, figures=False))
    assert "exploratory" in txt
    assert "NO CODE VERDICT" in txt


def test_fig_png_times_out_instead_of_hanging():
    # v0.62: the report's kaleido export runs off the main thread with a join
    # timeout, so a stuck browser signals failure (None) instead of freezing report
    # generation. The report builder converts that signal to ReportFigureError.
    import time

    class _SlowFig:
        def to_image(self, **kw):
            time.sleep(5.0)
            return b"never"

    png, timed_out = sector_report._fig_png(_SlowFig(), 100, 100, timeout=0.3)
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
    return {
        "combined": {
            "method": "EN 1992-1-1:2005",
            "valid": True,
            "r_m": 0.50, "r_v": 0.60, "r_t": 0.30,
            "dkna_ok": True, "dkna_sum": 0.90, "m_v_independent": False,
            "longitudinal": {
                "valid": True, "ok": True, "axis": "x", "tension_low": True,
                "m_ed": 100.0, "m_rd": 200.0, "mv": 20.0, "mt": 10.0,
                "ftd_v": 40.0, "ftd_t": 15.0, "z": 0.25, "m_total": 130.0,
                "util": 0.65, "biaxial": False, "capped": False,
                "theta_mode": theta_mode,
            },
        }
    }


def test_report_disjoint_longitudinal_note_avoids_a_shared_angle():
    # theta_mode == "disjoint": shear and torsion bands do not overlap, so the PDF must
    # not claim a shared member angle -- else reports contradict the on-screen warning.
    txt = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), _combined_longitudinal("disjoint"), figures=False)).split())
    assert "do not overlap" in txt
    assert "resistance-optimum angle" in txt
    assert "minimise the governing utilisation" not in txt
    assert "ONE member strut angle shared" not in txt


def test_report_no_load_longitudinal_note_is_not_labelled_disjoint():
    # theta_mode == "resistance": no live shear or torsion. The bands are NOT disjoint
    # (there is simply nothing to optimise), so the PDF must not say "do not overlap".
    txt = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), _combined_longitudinal("resistance"), figures=False)).split())
    assert "No shear or torsion is acting" in txt
    assert "do not overlap" not in txt
    assert "minimise the governing utilisation" not in txt


def test_report_shared_longitudinal_note_states_the_common_angle():
    # theta_mode == "utilisation" is the normal case: one admissible member angle.
    txt = " ".join(_pdf_text(sector_report.build_report(
        {}, _inp(), _combined_longitudinal("utilisation"), figures=False)).split())
    assert "ONE member strut angle shared" in txt
    assert "minimise the governing utilisation" in txt
    assert "do not overlap" not in txt
