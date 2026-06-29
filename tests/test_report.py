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
    return {"wk": 2.0e-4, "sr_max": 0.235, "esm_ecm": 8.4e-4, "sigma_s": 200.0,
            "rho_p_eff": 0.04, "ac_eff": 0.0125, "hc_ef": 0.125, "phi": 0.016,
            "cover": 0.04, "gov_bar": 1}


def _out():
    return {
        "plastic": {"mx": [100.0, 0.0, -100.0, 0.0], "my": [0.0, 100.0, 0.0, -100.0],
                    "max_mx": 100.0, "max_my": 100.0, "util": 0.8, "closed": True,
                    "check_util": True, "applied": (80.0, 0.0), "converged": True,
                    "points": [{"V": 0.0, "Mx": 100.0, "My": 0.0, "na_x": 0.0,
                                "na_y": 0.05, "eps_c": 0.35, "eps_s": 2.0,
                                "eps_cable": 0.0, "kappa": 0.02, "comp_force": 300.0,
                                "lever": 0.2, "dx": 0.0, "dy": 0.2}]},
        "elastic": {"total": [150.0], "long": [120.0], "dif": [30.0], "rst1": [0.0],
                    "max_conc": -12.0, "max_conc_xy": (0.0, 0.15), "max_conc_point": 3,
                    "na_x": 0.0, "na_y": 0.04, "max_steel": 150.0, "max_steel_bar": 1,
                    "converged": True, "cracked": True, "lambda_cr": 0.4,
                    "sigma_ct": 7.2, "fctm": 2.9, "show_cw": True,
                    "props_un": {"area": 0.06, "cx": 0.0, "cy": 0.0, "Ix": 4.5e-4,
                                 "Iy": 2.0e-4, "Ixy": 0.0},
                    "props_cr": None, "crack": _crack(), "crack_short": _crack(),
                    "crack_code": "EN 1992-1-1:2005", "crack_member": None}}


def test_report_pdf_generates():
    pdf = sector_report.build_report({"proj_no": "P-1", "author": "KLA"},
                                     _inp(), _out(), version="0.1.0", figures=False)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 3000


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
    assert "applied direction" not in txt   # no utilisation percentage row


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
    pdf = sector_report.build_report({}, _inp(), out, figures=False)
    assert pdf[:4] == b"%PDF"
