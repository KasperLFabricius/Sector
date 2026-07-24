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
import io
import pathlib
import sys

from PIL import Image
import pypdf
import pypdfium2 as pdfium

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sector_report  # noqa: E402
import fatigue_analysis  # noqa: E402
import fatigue_inputs  # noqa: E402
import material_catalog  # noqa: E402
from sector import __version__  # noqa: E402
from sector import codes, shear  # noqa: E402
from sector.materials import Concrete  # noqa: E402
from sector.section import Section  # noqa: E402

# Geometry, concrete law, steel law, two plastic interactions, two plastic
# states, two elastic states, two elastic strain profiles, one derived shear
# geometry, one minimum-reinforcement figure, one clear-spacing figure and four
# grouped-fatigue figures. An intentional fixture change must update this
# explicit contract.
_EXPECTED_FIGURE_COUNT = 19


class _FixedDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 7, 19, 12, 0, 0)
        return value if tz is None else value.replace(tzinfo=tz)


def validate_outline_destinations(reader: pypdf.PdfReader) -> list[tuple[str, int]]:
    """Return outline titles/pages after proving every link reaches its heading."""
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
            if title not in page_text:
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
            "t_ed_knm": 0.0,
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
            "check_stress": True,
            "check_crack_width": True,
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
            "check_stress": True,
            "check_crack_width": False,
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
        "spectrum_source": "QA traffic spectrum REF-FAT-01",
        "cycle_count_source": "QA cycle register REF-CYC-01",
        "dynamic_effects": fatigue_inputs.DYNAMIC_INCLUDED,
        "cycle_counting": fatigue_inputs.COUNTING_RAINFLOW,
        "concurrence_basis": "Single loaded lane in the QA fixture",
        "atypical_traffic": fatigue_inputs.ATYPICAL_CONSIDERED,
        "approval_reference": "QA-FAT-APP-01",
        "authority_adjustments": "No additional adjustment; actions are final",
        "notes": "Issued-report regression spectrum",
    })
    return {
        "mode": "Both",
        "plastic_cases": plastic_cases,
        "elastic_cases": elastic_cases,
        "fatigue_on": True,
        "fatigue_edition": fatigue_inputs.EC2_2005_DKNA,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": True,
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
        "torsion_on": False,
        "combined_on": False,
        "minimum_reinforcement_on": True,
        "clear_spacing_on": True,
        "detailing_edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "detailing_d_upper": 16.0,
        "detailing_include_tendons": False,
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
                "fatigue_detail_id": "F1", "group_id": "B1",
                "spacing_group_id": "",
            },
            {
                "id": "R2", "x_mm": 0.0, "y_mm": 120.0,
                "area_mm2": 400.0, "diameter_mm": 22.57,
                "size_mode": "Area", "material_id": second_id,
                "fatigue_detail_id": "F1", "group_id": "B2",
                "spacing_group_id": "",
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
        "sls_wk_limit": 0.30,
        "sls_conc_limit_pct": 60.0,
        "sls_steel_limit_pct": 80.0,
        "sls_pre_limit_pct": 75.0,
        "sls_limit_source": "QA fixture SLS criteria",
        "v_min": 0.0,
        "v_max": 360.0,
        "v_inc": 90.0,
        "extent": 0.2,
    }


def _crack() -> dict:
    candidate = {
        "element_type": "Bar",
        "element_no": 1,
        "element_id": "bar 1",
        "x_mm": 0.0,
        "y_mm": -120.0,
        "area_mm2": 500.0,
        "wk": 0.213,
        "sr_max": 235.0,
        "esm_ecm": 8.4e-4,
        "sigma_s": 215.0,
        "rho_p_eff": 0.04,
        "ac_eff": 0.0125,
        "hc_ef": 0.125,
        "phi": 16.0,
        "cover": 40.0,
        "coarse": False,
        "edition": "2004",
        "kw": 1.0,
        "k1_r": 1.0,
        "kfl": 1.0,
        "sr_max_geometric": False,
    }
    return dict(candidate, gov_bar=1, candidates=[candidate])


def _results() -> dict:
    shear_res = shear.vrd_c(
        30.0, codes.EC2_2005_DKNA, bw_mm=200.0, d_mm=270.0,
        asl_mm2=500.0, n_ed_comp_kn=0.0, ac_m2=0.06, gamma_c=1.5,
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
        "points": [{
            "V": 0.0,
            "Mx": 100.0,
            "My": 0.0,
            "na_x": 0.0,
            "na_y": 0.05,
            "eps_c": 0.35,
            "eps_s": 2.0,
            "eps_s_comp": -0.1,
            "eps_cable": 0.0,
            "kappa": 0.02,
            "comp_force": 300.0,
            "lever": 0.2,
            "dx": 0.0,
            "dy": 0.2,
        }],
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
            "concrete": {"value": 12.0, "limit": 18.0, "util": 2 / 3,
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
        "sls_limit_source": "QA fixture SLS criteria",
        "sls_wk_limit": 0.30,
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
        "crack_assessment": {
            "value": 0.213,
            "limit": 0.30,
            "util": 0.71,
            "margin": 0.087,
            "status": "OK",
            "case": "Long-term",
            "governing": "bar 1",
            "criterion": "0.3 mm",
        },
        "crack_code": "EN 1992-1-1:2005",
        "crack_member": None,
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
        "method": codes.EC2_2005_DKNA.label,
        "model_2023": False,
    }
    plastic_2 = copy.deepcopy(plastic)
    plastic_2.update(util=1.25, applied=(125.0, 0.0))
    elastic_2 = copy.deepcopy(elastic)
    elastic_2["show_cw"] = False
    elastic_2["max_steel"] = 245.0
    elastic_2["elements"][0]["total_mpa"] = 245.0
    elastic_2["stress_assessments"]["reinforcement"].update(
        value=245.0, util=245.0 / 400.0, margin=155.0
    )
    minimum = {
        "status": "PASS",
        "edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
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
        "phi_second_mm": 22.57, "spacing_group_id": "",
        "declared_exception": False,
    }
    spacing = {
        "status": "PASS",
        "edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "clause": "8.2(2)", "d_upper_mm": 16.0,
        "include_tendons": False, "pairs": [spacing_pair],
        "governing": spacing_pair, "reason": None,
        "limitations": ["Pairwise edge-to-edge distance is checked."],
    }
    inputs = _inputs()
    plastic_rows = inputs["plastic_cases"]
    elastic_rows = inputs["elastic_cases"]
    fatigue = fatigue_analysis.run_analysis(inputs)
    return {
        "plastic": plastic,
        "elastic": elastic,
        "fatigue": fatigue,
        "shear": shear_payload,
        "clear_spacing": spacing,
        "plastic_cases": [
            {"name": "PL-QA-1", "actions": plastic_rows[0], "evaluated": True,
             "results": {
                 "plastic": plastic, "shear": shear_payload,
                 "minimum_reinforcement": minimum,
             }},
            {"name": "PL-QA-2", "actions": plastic_rows[1], "evaluated": True,
             "results": {"plastic": plastic_2}},
        ],
        "elastic_cases": [
            {"name": "EL-QA-1", "actions": elastic_rows[0], "evaluated": True,
             "results": {"elastic": elastic}},
            {"name": "EL-QA-2", "actions": elastic_rows[1], "evaluated": True,
             "results": {"elastic": elastic_2}},
        ],
    }


@functools.lru_cache(maxsize=1)
def build_fixture_pdf() -> bytes:
    """Build the report with stable time and the real figure-export path."""
    original_datetime = sector_report.datetime.datetime
    sector_report.datetime.datetime = _FixedDateTime
    try:
        return sector_report.build_report(
            {
                "proj_no": "QA-REFERENCE",
                "proj_name": "Rendered report regression",
                "section": "Reference section",
                "author": "Sector QA",
                "source_revision": "fixture000000000000000000000000000000000",
            },
            _inputs(),
            _results(),
            version=__version__,
            figures=True,
        )
    finally:
        sector_report.datetime.datetime = original_datetime


def validate_pdf_content(pdf: bytes) -> str:
    """Reject a report that lost figures or core engineering content."""
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if "figure unavailable" in text.lower():
        raise AssertionError("the report contains an unavailable-figure placeholder")

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
    if images != _EXPECTED_FIGURE_COUNT:
        raise AssertionError(
            f"expected {_EXPECTED_FIGURE_COUNT} exported engineering figures, "
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
         if "Governing case worked" in (page.extract_text() or "")),
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
    if "Sweep start V.min" not in settings_page:
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
        "Results overview - FAIL",
        "Governing combination",
        "M1 New B500 reinforcement",
        "M2 Existing reinforcement",
        "Verified from archive test certificate",
        "R1 M1",
        "R2 M2",
        "Vx,Ed = 0",
        "Vy,Ed = 0",
        "Plastic section capacity - PL-QA-1",
        "Plastic section capacity - PL-QA-2",
        "Longitudinal minimum reinforcement - PL-QA-1",
        "Reinforcement clear spacing",
        "R1 - R2",
        "Elastic section response and stress limits - EL-QA-1",
        "Elastic section response and stress limits - EL-QA-2",
        "Cracking and crack width - EL-QA-1",
        "Cracking threshold - EL-QA-2",
        "Grouped fatigue",
        "Road traffic",
        "FAT-QA-H",
        "FAT-QA-M",
        "QA traffic spectrum REF-FAT-01",
        "Spectrum summary",
        "Reinforcement fatigue",
        "Concrete fatigue",
        "Certified governing-fibre search",
        "Torsion and shear fatigue are not assessed",
        "125.0 %",
        "245.000 MPa",
        "Crack-width candidates",
        f"Generated 2026-07-19 12:00 by Sector {__version__}",
    ):
        if expected not in text and expected not in flat_text:
            raise AssertionError(f"expected report content is missing: {expected}")
    return text


def render_pdf(pdf: bytes, scale: float = 1.5) -> list[Image.Image]:
    """Rasterise all pages through PDFium and return independent PIL images."""
    document = pdfium.PdfDocument(pdf)
    pages = []
    try:
        for index in range(len(document)):
            page = document[index]
            bitmap = page.render(scale=scale)
            try:
                pages.append(bitmap.to_pil().convert("RGB").copy())
            finally:
                bitmap.close()
                page.close()
    finally:
        document.close()
    return pages


def _pixels(image: Image.Image) -> list[int]:
    """Return flat pixel values across supported Pillow releases."""
    getter = getattr(image, "get_flattened_data", image.getdata)
    return list(getter())


def validate_rendered_pages(
    pages: list[Image.Image],
    *,
    require_document_control: bool = False,
) -> None:
    """Reject blank, clipped, malformed or ink-saturated report pages."""
    if len(pages) < 6:
        raise AssertionError(f"expected at least 6 report pages, got {len(pages)}")

    for number, image in enumerate(pages, start=1):
        width, height = image.size
        ratio = width / height
        if not 0.70 < ratio < 0.72:
            raise AssertionError(f"page {number} is not A4 portrait: {width}x{height}")

        grey = image.convert("L")
        pixels = _pixels(grey)
        dark = sum(value < 245 for value in pixels)
        fraction = dark / len(pixels)
        if not 0.002 < fraction < 0.45:
            raise AssertionError(
                f"page {number} has implausible ink coverage {fraction:.4f}"
            )

        bbox = Image.eval(
            Image.frombytes("L", grey.size, bytes(
                255 if value < 250 else 0 for value in pixels
            )),
            lambda value: value,
        ).getbbox()
        if bbox is None:
            raise AssertionError(f"page {number} rendered blank")

        edge = max(min(width, height) // 250, 2)
        edge_pixels = (
            _pixels(grey.crop((0, 0, width, edge)))
            + _pixels(grey.crop((0, height - edge, width, height)))
            + _pixels(grey.crop((0, 0, edge, height)))
            + _pixels(grey.crop((width - edge, 0, width, height)))
        )
        edge_dark = sum(value < 245 for value in edge_pixels) / len(edge_pixels)
        if edge_dark > 0.01:
            raise AssertionError(
                f"page {number} has content clipped against the page edge"
            )

        if require_document_control:
            # Text extraction can still find header/footer strings when a PDF
            # graphics-state error makes them invisible. Check their rendered
            # text zones independently of the body and horizontal rules.
            furniture_regions = {
                "header project": (
                    int(0.09 * width), int(0.028 * height),
                    int(0.72 * width), int(0.044 * height),
                ),
                "header revision": (
                    int(0.80 * width), int(0.028 * height),
                    int(0.92 * width), int(0.044 * height),
                ),
                "footer identity": (
                    int(0.09 * width), int(0.952 * height),
                    int(0.65 * width), int(0.967 * height),
                ),
                "footer page number": (
                    int(0.78 * width), int(0.952 * height),
                    int(0.92 * width), int(0.967 * height),
                ),
            }
            for label, box in furniture_regions.items():
                region_pixels = _pixels(grey.crop(box))
                region_dark = sum(
                    value < 245 for value in region_pixels
                ) / len(region_pixels)
                if region_dark < 0.01:
                    raise AssertionError(
                        f"page {number} has no visible {label}"
                    )


def write_fixture(output: pathlib.Path) -> list[pathlib.Path]:
    """Write the stable PDF and rendered page PNG evidence."""
    output.mkdir(parents=True, exist_ok=True)
    pdf = build_fixture_pdf()
    validate_pdf_content(pdf)
    pdf_path = output / "sector-report-reference.pdf"
    pdf_path.write_bytes(pdf)
    pages = render_pdf(pdf)
    validate_rendered_pages(pages, require_document_control=True)
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
