"""Build and rasterise a stable Sector report QA fixture.

The normal report tests inspect PDF text. This fixture also passes every page
through PDFium so CI exercises the artifact an engineer actually opens. The
real Plotly/Kaleido exporter is retained so the gate also fails when the figures
an engineer expects in the issued report cannot be produced.
"""

from __future__ import annotations

import argparse
import datetime
import functools
import io
import math
import pathlib
import re
import sys

import pypdf

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import case_analysis
import fatigue_analysis as fatigue_analysis
import fatigue_inputs
import material_catalog
import result_presentation
import sector_report

from sector import (
    __version__,
    capacity,
    codes,
    combined,
    detailing,
    shear,
    torsion,
)
from sector.design_standards import DesignBasisKey
from sector.materials import Concrete
from sector.section import Section
from tools.publication_preflight import (
    REPORT_FURNITURE,
    RasterCrop,
    preflight_pdf,
    render_pdf,
    validate_crops,
    validate_raster_pages,
)
from tools.publication_preflight import (
    validate_caption_colocation as validate_report_table_colocation,
)

__all__ = (
    "detect_sparse_report_pages",
    "render_pdf",
    "validate_equation_source_colocation",
    "validate_outline_destinations",
    "validate_rendered_pages",
    "validate_report_page_semantics",
    "validate_report_table_colocation",
    "validate_results_overview_pagination",
    "validate_worked_example_text",
)

_AUDIT_SPARSE_BODY_BOX = (0.08, 0.10, 0.92, 0.92)
_AUDIT_SPARSE_BODY_THRESHOLD = 0.35

# Geometry, concrete law, two steel laws, clear-spacing and minimum-reinforcement
# geometry, derived shear geometry, shear truss, torsion tube, two V-T interaction
# figures, one plastic interaction and state, one elastic state and strain profile,
# and four grouped-fatigue figures. An intentional fixture change must update this
# explicit contract.
_EXPECTED_FIGURE_COUNT = 19
_EXPECTED_PLASTIC_WORKED_HEADING = (
    "Worked plastic calculation (utilisation direction)"
)
_REPORT_CROPS = (
    RasterCrop(
        "report contents",
        2,
        (0.10, 0.08, 0.92, 0.90),
        "2c9a641d5a3deaa164b02cd5f2ec12db9bf1a587cbf63043906e1c5ea5ed12b0",
    ),
    RasterCrop(
        "report page furniture",
        2,
        (0.09, 0.02, 0.92, 0.98),
        "3da20f127a5fb3dfe813b76ca5780b8caf98f22db3f6766e9b34b64bcd6f5c0d",
    ),
)


class _FixedDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 7, 19, 12, 0, 0)
        return value if tz is None else value.replace(tzinfo=tz)


def validate_outline_destinations(reader: pypdf.PdfReader) -> list[tuple[str, int]]:
    """Return outline titles/pages after proving every link reaches its heading."""

    def normalized_text(value: object) -> str:
        # PDF extractors insert line breaks when a long visible heading wraps.
        # Bookmark titles are unwrapped strings, so compare semantic whitespace
        # rather than page-layout line boundaries.
        return " ".join(str(value).split())
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
            if normalized_text(title) not in normalized_text(page_text):
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
            "vy_ed_kn": 30.0,
            "t_ed_knm": 25.0,
            "check_minimum_reinforcement": True,
        },
        {
            "name": "PL-QA-2",
            "description": "Governing combination | Source: QA register",
            "n_ed_kn": 0.0,
            "mx_ed_knm": 125.0,
            "my_ed_knm": 0.0,
            "vy_ed_kn": 0.0,
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
            "calculate_crack_width": True,
        },
        {
            "name": "EL-QA-2",
            "description": "Governing elastic response | Source: QA register",
            "n_long_ed_kn": 0.0,
            "mx_long_ed_knm": 90.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 25.0,
            "my_short_ed_knm": 0.0,
            "calculate_crack_width": False,
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
    bars = [
        (-0.07, -0.12, 250.0),
        (0.07, 0.12, 200.0),
        (0.07, -0.12, 250.0),
        (-0.07, 0.12, 200.0),
    ]
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
        "notes": (
            "QA traffic spectrum REF-FAT-01; QA cycle register REF-CYC-01; "
            "single loaded lane in the QA fixture; issued-report regression spectrum"
        ),
    })
    return {
        "mode": "Both",
        "plastic_cases": plastic_cases,
        capacity.TORSION_CASE_AUTHORITIES_KEY: {
            record["name"]: {
                capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                    capacity.TORSION_DESIGN_EQUILIBRIUM
                ),
                capacity.TORSION_CASE_MEMBER_SCOPE_KEY: (
                    capacity.TORSION_MEMBER_CLOSED
                ),
            }
            for record in plastic_cases
        },
        "elastic_cases": elastic_cases,
        "fatigue_on": True,
        "fatigue_edition": DesignBasisKey.FIRST_GEN_DK_NA_2024.value,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": True,
        "fatigue_concrete_method": "Explicit Palmgren-Miner spectrum",
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
        "shear_links": True,
        "shear_method": codes.EC2_2005_DKNA.label,
        "shear_gamma_v": 1.40,
        "shear_section_form": shear.SHEAR_SECTION_AUTO,
        "shear_duct_case": shear.SHEAR_DUCT_NONE,
        "shear_hoop_diameter": 0.0,
        "shear_vx_bw": 0.0,
        "shear_vy_bw": 0.0,
        "shear_vx_web_inclination_deg": 0.0,
        "shear_vy_web_inclination_deg": 0.0,
        "shear_vx_fitted_z": 0.0,
        "shear_vy_fitted_z": 0.0,
        "shear_vx_duct_sum": 0.0,
        "shear_vy_duct_sum": 0.0,
        "shear_vx_duct_largest": 0.0,
        "shear_vy_duct_largest": 0.0,
        "shear_vx_link_legs": 2.0,
        "shear_vy_link_legs": 2.0,
        "shear_link_dia": 10.0,
        "shear_link_s": 150.0,
        "shear_fywk": 500.0,
        "torsion_on": True,
        "torsion_tef": 60.0,
        "torsion_nu_v": False,
        "torsion_subdivide": False,
        "torsion_subrects": [],
        "torsion_method": codes.EC2_2005_DKNA.label,
        "torsion_design_basis": capacity.TORSION_DESIGN_EQUILIBRIUM,
        "torsion_member_scope": capacity.TORSION_MEMBER_CLOSED,
        "torsion_gamma_ct": codes.EC2_2005_DKNA.gamma_ct,
        "combined_on": True,
        "combined_method": codes.EC2_2005_DKNA.label,
        "combined_mv_independent": False,
        "strut_cot_min": 1.0,
        "strut_cot_max": 2.5,
        "minimum_reinforcement_on": True,
        "transverse_detailing_on": True,
        "clear_spacing_on": True,
        "detailing_edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "detailing_member_type": detailing.MEMBER_BEAM,
        "detailing_cut_direction": detailing.CUT_TRANSVERSE,
        "detailing_d_upper": 16.0,
        "detailing_include_tendons": False,
        "transverse_ductility_class": "B",
        "transverse_apply_ductility_reduction": False,
        "shear_vx_transverse_leg_spacing": 0.0,
        "shear_vy_transverse_leg_spacing": 0.0,
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
                "id": "R1", "x_mm": -70.0, "y_mm": -120.0,
                "area_mm2": 250.0, "diameter_mm": 17.84,
                "size_mode": "Area", "material_id": "M1",
                "fatigue_detail_id": "F1",
            },
            {
                "id": "R2", "x_mm": 70.0, "y_mm": 120.0,
                "area_mm2": 200.0, "diameter_mm": 15.96,
                "size_mode": "Area", "material_id": second_id,
                "fatigue_detail_id": "F1",
            },
            {
                "id": "R3", "x_mm": 70.0, "y_mm": -120.0,
                "area_mm2": 250.0, "diameter_mm": 17.84,
                "size_mode": "Area", "material_id": "M1",
                "fatigue_detail_id": "F1",
            },
            {
                "id": "R4", "x_mm": -70.0, "y_mm": 120.0,
                "area_mm2": 200.0, "diameter_mm": 15.96,
                "size_mode": "Area", "material_id": second_id,
                "fatigue_detail_id": "F1",
            },
        ],
        "tendon_elements": [],
        "concrete": Concrete(fck=30.0, gamma_c=1.5, curve=2),
        # Match native input assembly: the capacity reference follows the selected
        # material; the per-bar laws below retain the mixed reinforcement cage.
        "steel": mild_materials[second_id],
        "mild_material_catalog": mild_catalogue,
        "mild_materials": mild_materials,
        "bar_materials": [
            mild_materials["M1"],
            mild_materials[second_id],
            mild_materials["M1"],
            mild_materials[second_id],
        ],
        "capacity_steel_material_id": second_id,
        "prestress": None,
        "prestress_material_catalog": material_catalog.default_catalog("prestress"),
        "P_pl": 0.0,
        "Mx_pl": 80.0,
        "My_pl": 0.0,
        "check_util": True,
        "interaction": False,
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
        "sls_phi": 0.0,
        "sls_code": DesignBasisKey.FIRST_GEN_DK_NA_2024.value,
        "sls_member": "Beam",
        "sls_bond": "Ribbed / high bond (k1 = 0.8)",
        "sls_k1": 0.8,
        "sls_long_term_permitted_crack_width_mm": 0.20,
        "sls_short_term_permitted_crack_width_mm": 0.20,
        "sls_heightened_permitted_crack_width_mm": 0.20,
        "sls_heightened_on": True,
        "sls_heightened_reference_case": "EL-QA-1",
        "sls_heightened_reinforcement_surface": "smooth",
        "sls_heightened_effective_tensile_strength_mpa": 2.9,
        "sls_heightened_fine_effective_tension_area_mm2": 60_000.0,
        "sls_heightened_coarse_effective_tension_area_mm2": 90_000.0,
        "v_min": 0.0,
        "v_max": 360.0,
        "v_inc": 90.0,
        "extent": 0.2,
    }


def _results(inp: dict | None = None) -> dict:
    """Use the application's native producer for every enabled fixture family."""
    import sector_app

    return sector_app.run_analysis(inp if inp is not None else _inputs())


def validate_fixture_engineering(inp: dict, out: dict) -> None:
    """Prove that the report fixture's displayed operands reproduce its results."""

    def close(label: str, actual: float, expected: float) -> None:
        if not math.isclose(actual, expected, rel_tol=1.0e-10, abs_tol=1.0e-10):
            raise AssertionError(
                f"inconsistent fixture {label}: {actual!r} != {expected!r}"
            )

    retained_materials = out["material_properties"]
    close(
        "concrete design strength",
        retained_materials["concrete"]["design_strength_mpa"],
        inp["concrete"].fcd,
    )
    retained_mild = {
        row["material_id"]: row for row in retained_materials["mild"]
    }
    for material_id, material in inp["mild_materials"].items():
        close(
            f"{material_id} design yield",
            retained_mild[material_id]["design_yield_mpa"],
            capacity.design_yield(material),
        )

    plastic_worked = out["plastic_cases"][1]["results"]["plastic"]
    worked_index = plastic_worked.get("worked_point_index")
    if type(worked_index) is not int or not 0 <= worked_index < len(plastic_worked["points"]):
        raise AssertionError("the governing plastic worked-point identity is missing")
    point = plastic_worked["points"][worked_index]
    actions = inp["plastic_cases"][1]
    close("plastic applied Mx", plastic_worked["applied"][0], actions["mx_ed_knm"])
    close("plastic applied My", plastic_worked["applied"][1], actions["my_ed_knm"])
    # This fixture has positive uniaxial Mx. Its governing sweep point is on
    # that same ray, so demand / point resistance independently reproduces util.
    close("plastic uniaxial input My", actions["my_ed_knm"], 0.0)
    close("plastic uniaxial resistance My", point["My"], 0.0)
    if actions["mx_ed_knm"] <= 0.0 or point["Mx"] <= 0.0:
        raise AssertionError("the fixture requires positive uniaxial Mx")
    close("plastic demand", plastic_worked["util_demand"], actions["mx_ed_knm"])
    close("plastic resistance", plastic_worked["util_resistance"], point["Mx"])
    close(
        "plastic utilisation", plastic_worked["util"],
        actions["mx_ed_knm"] / point["Mx"],
    )
    close(
        "plastic axial equilibrium",
        point["axial_achieved"],
        point["concrete_force"] + point["bar_force"] + point["tendon_force"],
    )
    close(
        "plastic Mx equilibrium",
        point["Mx"],
        point["concrete_mx"] + point["bar_mx"] + point["tendon_mx"],
    )
    for state_kind in ("concrete_corner_states", "reinforcement_states"):
        state = point[state_kind][0]
        retained_plane_strain = (
            point["strain_offset"]
            + point["strain_gradient_x"] * state["x_mm"] / 1000.0
            + point["strain_gradient_y"] * state["y_mm"] / 1000.0
        )
        close(
            f"plastic {state_kind} strain plane",
            state["section_strain_permille"] / 1000.0,
            retained_plane_strain,
        )
        close(
            f"plastic {state_kind} material strain sign",
            state["strain_permille"],
            -state["section_strain_permille"],
        )
    close(
        "plastic reported concrete strain",
        point["eps_c"] * 10.0,
        min(state["strain_permille"] for state in point["concrete_corner_states"]),
    )
    close(
        "plastic reported tensile strain",
        point["eps_s"] * 10.0,
        max(state["strain_permille"] for state in point["reinforcement_states"]),
    )
    selected_curvature = point["curvature_selection"]["curvature_per_m"]
    curvature_candidate = next(
        row for row in point["curvature_candidates"] if row["selected"]
    )
    close(
        "plastic curvature candidate",
        curvature_candidate["curvature_per_m"],
        curvature_candidate["strain_limit"]
        / curvature_candidate["distance_from_na_m"],
    )
    close("plastic curvature selection", selected_curvature, point["kappa"])

    for entry, actions in zip(out["elastic_cases"], inp["elastic_cases"]):
        if entry["name"] != actions["name"] or entry["actions"] != actions:
            raise AssertionError("the native Elastic case lost its input identity")
        elastic_worked = entry["results"]["elastic"]
        superposition = elastic_worked["superposition"]
        reduction = superposition["long_term_reduction_factor"]
        close("elastic modular-ratio reduction", reduction, 1.0 - inp["ns"] / inp["nl"])
        elements = elastic_worked["elements"]
        if len(elements) != len(inp["bar_elements"]) or inp["tendons"]:
            raise AssertionError("the fixture requires its complete native mild-bar cage")
        for index, (element, bar) in enumerate(zip(elements, inp["bar_elements"])):
            if element["element_id"] != bar["id"]:
                raise AssertionError("the native Elastic element lost its input identity")
            if element["material_id"] != bar["material_id"]:
                raise AssertionError("inconsistent fixture Elastic material identity")
            close("elastic element modulus", element["modulus_mpa"],
                  inp["mild_materials"][bar["material_id"]].Es)
            for key in ("area_mm2", "x_mm", "y_mm"):
                close(f"elastic element {key}", element[key], bar[key])
            close("elastic reduced long-term stress", element["reduced_long_mpa"],
                  element["long_passive_mpa"] * reduction)
            close("elastic total stress", element["total_mpa"],
                  element["reduced_long_mpa"] + element["rst1_mpa"] + element["locked_in_mpa"])
            close("elastic difference stress", element["dif_mpa"],
                  element["total_mpa"] - element["long_mpa"])
            for array, field in (("total", "total_mpa"), ("long", "long_mpa"),
                                 ("dif", "dif_mpa"), ("rst1", "rst1_mpa")):
                close(f"elastic {array} array", elastic_worked[array][index], element[field])
        neutralising = superposition["neutralising_resultant"]
        combined_target = superposition["combined_target_before_neutralisation"]
        for resultant, coordinate, scale in (("n", None, 1000.0),
                                             ("mx", "y_mm", 1_000_000.0),
                                             ("my", "x_mm", 1_000_000.0)):
            close(f"elastic neutralising {resultant}", neutralising[resultant],
                  sum(element["reduced_long_mpa"] * element["area_mm2"]
                      * (element[coordinate] if coordinate else 1.0) / scale
                      for element in elements))
            # The native stiffness equations use tension-positive resultants.
            # This fixture has zero axial load and prestress; bending targets
            # are the negatives of the engineer-facing input moments.
            long_action = actions[f"{resultant}_long_ed_{'kn' if resultant == 'n' else 'knm'}"]
            short_action = actions[f"{resultant}_short_ed_{'kn' if resultant == 'n' else 'knm'}"]
            if resultant == "n":
                close("elastic fixture axial long action", long_action, 0.0)
                close("elastic fixture axial short action", short_action, 0.0)
            close(f"elastic combined {resultant} input target",
                  combined_target[resultant], -(long_action + short_action))
            close(f"elastic long {resultant} input target",
                  elastic_worked["accepted_states"]["long_term"]["equilibrium"]["target"][resultant],
                  -long_action)
            close(f"elastic instantaneous {resultant} input target",
                  elastic_worked["accepted_states"]["instantaneous_combined"]["equilibrium"]["target"][resultant],
                  combined_target[resultant] - neutralising[resultant])
        for name, state in elastic_worked["accepted_states"].items():
            equilibrium = state["equilibrium"]
            plane = state["raw_stress_plane"]
            operands = [plane[key] for key in (
                "sigma0_kpa", "gradient_x_kpa_per_m", "gradient_y_kpa_per_m",
            )]
            for index, resultant in enumerate(("n", "mx", "my")):
                close(f"elastic {name} matrix {resultant}",
                      equilibrium["internal"][resultant],
                      sum(a * b for a, b in zip(equilibrium["matrix"][index], operands)))
                close(f"elastic {name} {resultant} residual",
                      equilibrium["residual"][resultant],
                      equilibrium["internal"][resultant] - equilibrium["target"][resultant])
            if not state["converged"] or equilibrium["normalised_residual"] > equilibrium["relative_tolerance"]:
                raise AssertionError("the native Elastic equilibrium did not converge")
        maximum_steel = max(element["total_mpa"] for element in elements)
        close("elastic maximum reinforcement stress", elastic_worked["max_steel"], maximum_steel)
        close("elastic reinforcement stress output",
              elastic_worked["stress_outputs"]["reinforcement"]["value"], maximum_steel)
        corners = elastic_worked["concrete_corners"]
        maximum_concrete = max(0.0, -min(corner["stress_mpa"] for corner in corners))
        close("elastic maximum concrete compression", elastic_worked["max_conc"], maximum_concrete)
        close("elastic concrete stress output",
              elastic_worked["stress_outputs"]["concrete"]["value"], maximum_concrete)
        governing_corner = next(c for c in corners if c["point_no"] == elastic_worked["max_conc_point"])
        close("elastic governing concrete point", -governing_corner["stress_mpa"], maximum_concrete)


    elastic_reference = out["elastic_cases"][0]["results"]["elastic"]
    for branch_name in ("crack", "crack_short", "crack_coarse", "crack_short_coarse"):
        crack = elastic_reference[branch_name]
        candidates = crack["candidates"]
        if [row["element_id"] for row in candidates] != ["R1", "R3"]:
            raise AssertionError("inconsistent fixture crack candidate inventory")
        if crack["governing_candidate"] != candidates[0] or crack["element_id"] != candidates[0]["element_id"]:
            raise AssertionError("inconsistent fixture crack governing candidate identity")
        for candidate in candidates:
            spacing = candidate["spacing_operands"]
            mean = candidate["mean_strain_operands"]
            coarse = branch_name.endswith("coarse")
            short = "short" in branch_name
            if candidate["coarse"] is not coarse or crack["coarse"] is not coarse:
                raise AssertionError("inconsistent fixture crack system identity")
            element = next(e for e in elastic_reference["elements"] if e["element_id"] == candidate["element_id"])
            for key in ("x_mm", "y_mm", "area_mm2"):
                close(f"{branch_name} candidate {key}", candidate[key], element[key])
            for key, operand in (("sigma_s", "sigma_s"), ("esm_ecm", "selected_esm_ecm"), ("rho_p_eff", "rho_p_eff")):
                close(f"{branch_name} candidate {key}", candidate[key], mean[operand])
            for key, operand in (("sr_max", "selected_spacing"), ("cover", "cover"), ("phi", "diameter"), ("rho_p_eff", "rho_p_eff")):
                close(f"{branch_name} candidate {key}", candidate[key], spacing[operand])
            close(f"{branch_name} source steel stress", mean["sigma_s"],
                  element["total_mpa"] if short else element["long_mpa"])
            close(f"{branch_name} duration coefficient", mean["kt"], 0.6 if short else 0.4)
            close(f"{branch_name} effective reinforcement ratio", candidate["rho_p_eff"],
                  candidate["as_eff"] / candidate["ac_eff"])
            close(f"{branch_name} spacing Formula (7.11)", spacing["selected_spacing"],
                  spacing["k3_used"] * spacing["cover"] + spacing["k1"] * spacing["k2"]
                  * spacing["k4"] * spacing["diameter"] / spacing["rho_p_eff"])
            close(f"{branch_name} concrete tension reduction", mean["concrete_tension_reduction"],
                  mean["kt"] * mean["fctm"] / mean["rho_p_eff"] * (1.0 + mean["alpha_e"] * mean["rho_p_eff"]))
            close(f"{branch_name} mean-strain formula candidate", mean["formula_candidate"],
                  (mean["sigma_s"] - mean["concrete_tension_reduction"]) / mean["es"])
            close(f"{branch_name} mean-strain lower candidate", mean["lower_bound_candidate"],
                  0.6 * mean["sigma_s"] / mean["es"])
            close(f"{branch_name} selected mean strain", mean["selected_esm_ecm"],
                  max(mean["formula_candidate"], mean["lower_bound_candidate"]))
            width = (0.5 if coarse else 1.0) * spacing["selected_spacing"] * mean["selected_esm_ecm"]
            close(f"{branch_name} candidate width", candidate["wk"], width)
        close(f"{branch_name} published width", crack["wk"], candidates[0]["wk"])
        close(f"{branch_name} governing width", crack["wk"], max(row["wk"] for row in candidates))

    heightened = out["heightened_crack_control"]
    input_bars = {bar["id"]: bar for bar in inp["bar_elements"]}
    contributions = heightened["contributions"]
    if {item["element_id"] for item in contributions} != {"R1", "R3"}:
        raise AssertionError("the heightened fixture lost its native contributing bars")
    for item in contributions:
        bar = input_bars[item["element_id"]]
        close("heightened contribution area", item["area_mm2"], bar["area_mm2"])
        close("heightened contribution diameter", item["diameter_mm"],
              math.sqrt(4.0 * bar["area_mm2"] / math.pi))
    close("heightened provided area", heightened["provided_reinforcement_area_mm2"],
          sum(item["area_mm2"] for item in contributions))
    close("heightened governing diameter", heightened["bar_diameter_mm"],
          max(item["diameter_mm"] for item in contributions))
    for branch_name in ("fine", "coarse"):
        branch = heightened[branch_name]
        close(
            f"heightened {branch_name} base reinforcement ratio",
            branch["base_reinforcement_ratio"],
            math.sqrt(
                branch["bar_diameter_mm"]
                * branch["effective_tensile_strength_mpa"]
                / (
                    4.0
                    * branch["reinforcement_modulus_mpa"]
                    * branch["crack_system_factor"]
                    * branch["permitted_crack_width_mm"]
                )
            ),
        )
        close(
            f"heightened {branch_name} required reinforcement area",
            branch["required_reinforcement_area_mm2"],
            branch["reinforcement_surface_multiplier"]
            * branch["base_reinforcement_ratio"]
            * branch["effective_tension_area_mm2"],
        )

    case = next(
        row for row in inp["plastic_cases"] if row["name"] == "PL-QA-1"
    )
    if not (
        inp["shear_on"]
        and inp["shear_links"]
        and inp["torsion_on"]
        and inp["combined_on"]
    ):
        raise AssertionError("the complete fixture checks are not enabled")

    shear_out = out["shear"]
    links = shear_out["links"]
    lk = links["res"]
    close("VEd", shear_out["v_ed"], case["vy_ed_kn"])
    close(
        "VRd,s",
        lk["vrd_s"],
        links["asw_over_s"] * lk["z"] * lk["fywd"] * lk["cot"] / 1000.0,
    )
    close(
        "VRd,max",
        lk["vrd_max"],
        (
            lk["alpha_cw"]
            * shear_out["bw"]
            * lk["z"]
            * lk["nu1"]
            * lk["fcd"]
            / (lk["cot"] + 1.0 / lk["cot"])
            / 1000.0
        ),
    )
    close("shear utilisation", links["util"], shear_out["v_ed"] / lk["vrd"])

    torsion_out = out["torsion"]
    tube = torsion_out["tube"]
    expected_tube = torsion.tube_properties_with_reinforcement(
        inp["outer"], inp.get("holes"), inp["bars"], inp["torsion_tef"],
    )
    if not expected_tube["valid"]:
        raise AssertionError("the fixture's physical torsion walls are not established")
    for key in ("A", "u", "tef", "Ak", "uk"):
        close(f"torsion tube {key}", tube[key], expected_tube[key])
    capacity_material = inp["mild_materials"][
        inp["capacity_steel_material_id"]
    ]
    expected_fyd_long = capacity_material.fytk / capacity_material.gamma_y
    close("torsion longitudinal design strength", torsion_out["fyd_long"],
          expected_fyd_long)
    close(
        "torsion tensile factor",
        torsion_out["gamma_ct"],
        inp["torsion_gamma_ct"],
    )
    close(
        "torsion design tensile strength",
        torsion_out["fctd"],
        torsion_out["fctk_005"] / torsion_out["gamma_ct"],
    )
    close("TEd", torsion_out["t_ed"], case["t_ed_knm"])
    close(
        "TRd,s",
        torsion_out["trd_s"],
        torsion.trd_s(
            tube["Ak"], torsion_out["fywd"],
            torsion_out["asw_over_s"], torsion_out["cot"],
        ),
    )
    close(
        "TRd,max",
        torsion_out["trd_max"],
        torsion.trd_max(
            30.0, codes.EC2_2005_DKNA, tube["Ak"], tube["tef"],
            torsion_out["alpha_cw"], torsion_out["cot"],
            fcd_mpa=torsion_out["fcd"],
        ),
    )
    close(
        "TRd,c",
        torsion_out["trd_c"],
        torsion.trd_c(torsion_out["fctd"], tube["Ak"], tube["tef"]),
    )
    close(
        "torsion longitudinal area",
        torsion_out["asl_req"],
        torsion.asl_required(
            torsion_out["t_ed"], tube["uk"], tube["Ak"],
            torsion_out["fyd_long"], torsion_out["cot"],
        ),
    )
    close(
        "torsion utilisation",
        torsion_out["util"],
        torsion_out["t_ed"] / torsion_out["trd"],
    )

    detailing_out = out["transverse_reinforcement"]
    detailing_checks = {
        (check["scope"], check["kind"]): check
        for check in detailing_out["checks"]
    }
    leg_area = math.pi * inp["shear_link_dia"] ** 2 / 4.0
    shear_ratio = detailing_checks[("Shear VY", "minimum_ratio")]
    close(
        "shear detailing ratio",
        shear_ratio["provided"],
        2.0 * leg_area / (
            inp["shear_link_s"] * shear_out["bw"]
        ),
    )
    close(
        "shear longitudinal spacing limit",
        detailing_checks[("Shear VY", "longitudinal_spacing")]["limit"],
        0.75 * shear_out["d"],
    )
    close(
        "shear transverse leg spacing",
        detailing_checks[("Shear VY", "transverse_leg_spacing")]["provided"],
        shear_out["bw"],
    )
    torsion_ratio = detailing_checks[("Torsion Tube", "minimum_ratio")]
    close(
        "torsion detailing ratio",
        torsion_ratio["provided"],
        leg_area / (inp["shear_link_s"] * tube["tef"]),
    )
    torsion_spacing = detailing_checks[("Torsion Tube", "torsion_spacing")]
    close(
        "torsion detailing spacing limit",
        torsion_spacing["limit"],
        min(
            tube["uk"] * 1000.0 / 8.0,
            tube["minimum_dimension_mm"],
        ),
    )

    result = out["combined"]
    close(
        "concrete interaction",
        result["crushing"]["value"],
        combined.crushing_interaction(
            torsion_out["t_ed"], torsion_out["trd_max"],
            shear_out["v_ed"], lk["vrd_max"],
        ),
    )
    close(
        "combined utilisation",
        result["dkna_sum"],
        combined.dkna_sum(
            result["r_m"], result["r_v"], result["r_t"],
            r_n=result.get("r_n", 0.0),
            m_v_independent=result["m_v_independent"],
        ),
    )

    member_input = case_analysis.plastic_case_input(inp, case)
    current_checks = (
        result_presentation.directional_shear_publication_evidence_is_current(
            member_input, shear_out, plastic_result=out["plastic"],
        ),
        result_presentation.torsion_publication_evidence_is_current(
            member_input, shear_out, torsion_out,
        ),
        result_presentation.combined_publication_evidence_is_current(member_input, out),
    )
    if any(check != (True, None) for check in current_checks):
        raise AssertionError(f"the complete member fixture is not current: {current_checks!r}")

    member_cot = lk["cot"]
    close("torsion member cotangent", torsion_out["cot"], member_cot)
    candidates = links["chord_candidates"]
    if len(candidates) != 4 or {
        (item["axis"], item["tension_low"]) for item in candidates
    } != {("x", True), ("x", False), ("y", True), ("y", False)}:
        raise AssertionError("the member fixture must retain all four physical chords")
    concrete_credit = shear_out["v_ed"] <= shear_out["res"]["vrd_c"]
    for candidate in candidates:
        if not candidate["valid"] or not candidate["conditional"]:
            raise AssertionError("a report fixture chord lost its conditional evidence")
        ftd_v = (0.0 if concrete_credit or not candidate.get("gets_shift", False)
                 else 0.5 * shear_out["v_ed"] * member_cot)
        ftd_t = torsion_out["asl_req"] * torsion_out["fyd_long"] / 1000.0
        expected_mv = ftd_v * candidate["z"]
        if candidate["m_rd"] > 0.0:
            expected_mv = min(expected_mv,
                              max(candidate["m_rd"] - candidate["m_ed"], 0.0))
        expected_mt = ftd_t * candidate["z"] / 2.0
        for key, expected in (
            ("ftd_v", ftd_v), ("ftd_t", ftd_t),
            ("mv", expected_mv), ("mt", expected_mt),
            ("m_total", candidate["m_ed"] + expected_mv + expected_mt),
        ):
            close(f"{candidate['axis']}/{candidate['tension_low']} chord {key}",
                  candidate[key], expected)
        if candidate["m_rd"] == 0.0:
            if not math.isinf(candidate["util"]) or candidate["status"] != "FAIL":
                raise AssertionError("zero chord capacity must retain its definite failure")
        else:
            close("physical chord utilisation", candidate["util"],
                  candidate["m_total"] / candidate["m_rd"])
    expected_selection = result_presentation._current_member_angle_selection(
        member_input, shear_out, torsion_out,
    )
    if expected_selection != links["member_angle_selection"]:
        raise AssertionError("native and publication member-angle selection disagree")


@functools.lru_cache(maxsize=8)
def build_fixture_pdf(*, figures: bool = True, profile: str = "Audit") -> bytes:
    """Build the exhaustive QA report with stable time and selected profile.

    Audit remains the default for this publication fixture because its purpose is
    exhaustive equation/provenance coverage. The product default is Standard and
    receives its own profile-specific acceptance gates.
    """
    original_datetime = sector_report.datetime.datetime
    sector_report.datetime.datetime = _FixedDateTime
    try:
        inp = _inputs()
        out = _results(inp)
        validate_fixture_engineering(inp, out)
        out["worked_example_selection"] = (
            result_presentation.worked_example_selection(inp, out)
        )
        return sector_report.build_report(
            {
                "proj_no": "QA-REFERENCE",
                "proj_name": "Rendered report regression",
                "section": "Reference section",
                "author": "Sector QA",
                "source_revision": "fixture000000000000000000000000000000000",
                "calculation_state": "CURRENT - frozen QA fixture",
                "input_sha256": "f" * 64,
            },
            inp,
            out,
            version=__version__,
            figures=figures,
            profile=profile,
        )
    finally:
        sector_report.datetime.datetime = original_datetime


def validate_worked_example_text(text: str) -> None:
    """Reject missing or fail-closed governing textbook calculation chains."""
    unavailable = re.search(
        r"\bworked\b[\s\S]{0,180}?\bunavailable\b",
        text,
        flags=re.IGNORECASE,
    )
    if unavailable:
        raise AssertionError(
            "the report contains an unavailable worked-example placeholder: "
            + " ".join(unavailable.group(0).split())
        )
    flat_text = " ".join(text.split())
    for expected in (
        _EXPECTED_PLASTIC_WORKED_HEADING,
        "Converged strain plane",
        "Ultimate-curvature candidates",
        "Step 1 - converged long-term state",
        "Step 2 - neutralise the long-term concrete stress",
        "Step 3 - converged instantaneous combined state",
        "Crack width worked - governing case",
        "Formula (7.11) selected",
        "User-specified crack-width comparison - critical short-term case",
        "DK heightened crack-control minimum",
        "Formula 7.100 NA",
    ):
        if expected not in text and expected not in flat_text:
            raise AssertionError(
                f"the governing worked calculation is incomplete: {expected}"
            )


def validate_equation_source_colocation(
    page_texts: list[str],
    *,
    expected_equation_count: int = 107,
) -> None:
    """Require every governed equation identity and source on the same page."""
    equation_count = 0
    for page_number, page_text in enumerate(page_texts, start=1):
        identities = re.findall(
            r"(?m)^(?:Equation \([0-9]+\.[0-9]+\)|Method relation)\s*$",
            page_text,
        )
        sources = re.findall(r"(?m)^Source / method note:", page_text)
        if len(identities) != len(sources):
            raise AssertionError(
                f"equation/source page split on page {page_number}: "
                f"{len(identities)} identities and {len(sources)} visible sources"
            )
        equation_count += len(identities)
    if equation_count != expected_equation_count:
        raise AssertionError(
            f"expected {expected_equation_count} governed equations, "
            f"found {equation_count}"
        )


def validate_pdf_content(
    pdf: bytes,
    *,
    expected_figure_count: int = _EXPECTED_FIGURE_COUNT,
) -> str:
    """Reject a report that lost expected figures or core engineering content."""
    reader, page_texts = preflight_pdf(pdf, min_pages=6)
    text = "\n".join(page_texts)
    validate_equation_source_colocation(page_texts)
    if "figure unavailable" in text.lower():
        raise AssertionError("the report contains an unavailable-figure placeholder")
    validate_worked_example_text(text)
    # Plain ``sqrt(...)`` and ``sum(...)`` are intentional solver-owned symbolic
    # relations. Continue rejecting actual LaTeX/layout leaks.
    for token in (
        "Cfrac", "Big", "sincos", "delta eps",
        "varepsilon", "qquadk", "quadf", "kN.m",
    ):
        if token.casefold() in text.casefold():
            raise AssertionError(
                f"the report exposes an unrendered mathematics token: {token}"
            )
    for symbol in (chr(0x00B0), chr(0x00B7), chr(0x03B2)):
        if symbol not in text:
            raise AssertionError(
                f"the report is missing rendered mathematics symbol U+{ord(symbol):04X}"
            )

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
    if images != expected_figure_count:
        raise AssertionError(
            f"expected {expected_figure_count} exported engineering figures, "
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
    if "= 20 MPa" not in concrete_page:
        raise AssertionError("the concrete worked formula is split across pages")

    governing_page = next(
        (page.extract_text() or "" for page in reader.pages
         if (
             _EXPECTED_PLASTIC_WORKED_HEADING in (page.extract_text() or "")
             and "NA intercepts" in (page.extract_text() or "")
         )),
        "",
    )
    if not governing_page:
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

    settings_pages = []
    for page in reader.pages:
        has_settings_h2 = False

        def collect_settings_h2(text, _cm, _tm, _font, font_size):
            nonlocal has_settings_h2
            value = " ".join(text.split())
            if (
                (
                    value == "Analysis settings"
                    or re.fullmatch(r"\d+\.\d+ Analysis settings", value)
                )
                and math.isclose(float(font_size), 11.5, abs_tol=1.0e-6)
            ):
                has_settings_h2 = True

        page_text = page.extract_text(visitor_text=collect_settings_h2) or ""
        if has_settings_h2:
            settings_pages.append(page_text)
    if len(settings_pages) != 1:
        raise AssertionError(
            "expected exactly one Analysis settings level-2 heading, "
            f"found {len(settings_pages)}"
        )
    settings_page = settings_pages[0]
    if "Sweep start" not in settings_page:
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
        "Results overview",
        "Governing combination",
        "M1 New B500 reinforcement",
        "M2 Existing reinforcement",
        "Verified from archive test certificate",
        "R1 M1",
        "R2 M2",
        "Vx,Ed = 0",
        "Vy,Ed = 0",
        "Plastic section capacity - PL-QA-2",
        _EXPECTED_PLASTIC_WORKED_HEADING,
        "Converged strain plane",
        "Ultimate-curvature candidates",
        "Longitudinal minimum reinforcement - PL-QA-1",
        "Shear/torsion link detailing - PL-QA-1",
        "Closed-link spacing",
        "Reinforcement clear spacing",
        "R1 - R2",
        "Elastic section response and stresses - EL-QA-2",
        "Step 1 - converged long-term state",
        "Step 2 - neutralise the long-term concrete stress",
        "Step 3 - converged instantaneous combined state",
        "Governing crack width - EL-QA-1",
        "Cracking threshold - EL-QA-2",
        "Crack width worked - governing case",
        "Formula (7.11) selected",
        "Grouped fatigue",
        "Road traffic",
        "FAT-QA-H",
        "FAT-QA-M",
        "QA traffic spectrum REF-FAT-01",
        "Spectrum summary",
        "Reinforcement fatigue",
        "Concrete fatigue",
        "Textbook calculation - governing reinforcement fatigue",
        "Textbook calculation - governing concrete fatigue",
        "Bounded governing-fibre search",
        "DS/EN 1992-2:2005/AC:2008",
        "6.106",
        "shear and torsion fatigue remain separate checks",
        "Physical resistance components",
        "Concrete compression strut",
        "Closed stirrup",
        "Longitudinal reinforcement",
        "Torsion (thin-walled tube)",
        "Concrete tensile factor",
        # Native PL-QA-2: 125 kNm / 56.6043642884 kNm. The retained 125.0%
        # formatting vector remains in test_multi_case_report_includes_later_
        # governing_case_and_all_details; it is not this native calculation.
        "220.8 %",
        # The native governing Elastic result; retained 245.000/456.000 MPa
        # formatting vectors have independent multi-case unit coverage.
        "955.462 MPa",
        "Candidate summary for governing crack example",
        f"Generated 2026-07-19 12:00 by Sector {__version__}",
    ):
        if expected not in text and expected not in flat_text:
            raise AssertionError(f"expected report content is missing: {expected}")

    for removed in (
        "Independent bridge calculations",
        "Optional brittle Method B",
        "Box-wall shear and torsion",
        "Web/flange minimum crack reinforcement",
        "DS/EN 1992-2:2005 6.1(109)-(110)",
    ):
        if removed in text or removed in flat_text:
            raise AssertionError(
                f"removed component-mapped bridge content remains: {removed}"
            )

    validate_report_page_semantics(page_texts)
    validate_results_overview_pagination(page_texts)
    return text


def validate_results_overview_pagination(page_texts: list[str]) -> tuple[int, ...]:
    """Require one readable overview across its bounded native continuations."""
    caption = "Results overview across calculated checks"
    intro = (
        "The table shows the governing result for each check type."
    )
    notes = (
        "The table shows one governing row per engineering check type.",
        "The table shows one governing row for each engineering check type.",
    )
    final_row_tokens = ("Fatigue", "Road traffic", "20.8 %")
    normalized_pages = [" ".join(page_text.split()) for page_text in page_texts]
    overview_indexes = [
        index
        for index, page_text in enumerate(page_texts)
        if caption in page_text
    ]
    if not 1 <= len(overview_indexes) <= 3:
        raise AssertionError(
            "the stable results overview must occupy one to three pages"
        )
    if overview_indexes != list(
        range(overview_indexes[0], overview_indexes[-1] + 1)
    ):
        raise AssertionError("results-overview continuation pages are not contiguous")

    first_index = overview_indexes[0]
    final_index = overview_indexes[-1]
    if intro not in normalized_pages[first_index]:
        raise AssertionError("the results-overview lead-in left its first page")
    note_indexes = [
        index
        for index, page_text in enumerate(normalized_pages)
        if any(note in page_text for note in notes)
    ]
    if note_indexes != [final_index]:
        raise AssertionError(
            "the results-overview governing note left its final page"
        )
    final_page_text = normalized_pages[final_index]
    note_position = min(
        final_page_text.index(note)
        for note in notes
        if note in final_page_text
    )
    missing_final_row_tokens = [
        token for token in final_row_tokens if token not in final_page_text
    ]
    if missing_final_row_tokens:
        raise AssertionError(
            "the results-overview final row left its continuation page: "
            + ", ".join(missing_final_row_tokens)
        )
    final_row_position = max(
        final_page_text.index(token) for token in final_row_tokens
    )
    if not final_page_text.index(caption) < final_row_position < note_position:
        raise AssertionError(
            "the results-overview final row and governing note are out of reading order"
        )

    overview_text = " ".join(
        " ".join(page_texts[index].split()) for index in overview_indexes
    )
    # This native fixture has no separate stale/unrun governing information rows;
    # their conditional heading is checked in the information-row report tests.
    for expected in (
        "Checks and comparisons",
        "Calculated outputs",
        "Plastic bending",
        "Formula (6.31) minimum-reinforcement screen - separate link detailing",
        "DK heightened crack-control minimum",
        "Fatigue",
    ):
        # PDF extraction separates words wrapped at their existing hyphens.
        # Every letter and number in the required label must still be present.
        if not re.search(re.escape(expected).replace(r"\-", r"-\s*"), overview_text):
            raise AssertionError(
                f"results-overview content is missing: {expected}"
            )
    for continuation_index in overview_indexes[1:]:
        if "(continued)" not in normalized_pages[continuation_index]:
            raise AssertionError(
                "a results-overview continuation page lacks its continuation label"
            )
    return tuple(index + 1 for index in overview_indexes)


def validate_report_page_semantics(page_texts: list[str]) -> None:
    """Reject a report page containing only repeated document furniture."""
    footer_prefix = f"Sector {__version__} - "
    for number, page_text in enumerate(page_texts, start=1):
        semantic_lines = []
        for raw_line in page_text.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            if line.startswith("Project: QA-REFERENCE"):
                continue
            if line.startswith("Rev: "):
                continue
            if line.startswith(footer_prefix):
                continue
            if re.fullmatch(r"Page \d+ of \d+", line):
                continue
            semantic_lines.append(line)
        if not semantic_lines:
            raise AssertionError(
                f"page {number} contains document furniture but no report body"
            )


def validate_rendered_pages(
    pages, *, require_document_control=False, furniture=None, min_pages=6
):
    """Retain the fixture API while delegating to the shared raster gate."""
    if require_document_control and furniture is None:
        furniture = REPORT_FURNITURE
    return validate_raster_pages(
        pages, min_pages=min_pages, furniture=furniture
    )


def detect_sparse_report_pages(
    pages,
    page_texts: list[str],
    *,
    opener_pages=(),
    threshold: float = _AUDIT_SPARSE_BODY_THRESHOLD,
) -> tuple[tuple[int, float], ...]:
    """Return non-opener pages below the Audit usable-body coverage threshold.

    Coverage is the vertical span occupied by raster ink inside the usable body
    box, rather than whole-page pixel density.  That makes ordinary text pages
    comparable while excluding repeated header/footer furniture.  The result is
    deliberately evidence, not an automatic layout rewrite: every returned page
    requires an explicit colour/grayscale review before acceptance.
    """
    if len(pages) != len(page_texts):
        raise ValueError("raster pages and extracted page text must have equal length")
    if not 0.0 < threshold < 1.0:
        raise ValueError("sparse-page threshold must be between zero and one")
    excluded = {int(page) for page in opener_pages}
    sparse = []
    for number, image in enumerate(pages, start=1):
        if number in excluded:
            continue
        width, height = image.size
        left, top, right, bottom = _AUDIT_SPARSE_BODY_BOX
        body = image.convert("L").crop(
            (
                int(left * width),
                int(top * height),
                int(right * width),
                int(bottom * height),
            )
        )
        getter = getattr(body, "get_flattened_data", body.getdata)
        pixels = list(getter())
        body_width, body_height = body.size
        ink_rows = [
            row
            for row in range(body_height)
            if sum(
                pixels[row * body_width + column] < 245
                for column in range(body_width)
            )
            >= 3
        ]
        coverage = (
            (ink_rows[-1] - ink_rows[0] + 1) / body_height
            if ink_rows
            else 0.0
        )
        if coverage < threshold:
            sparse.append((number, coverage))
    return tuple(sparse)


def _outline_opener_pages(reader: pypdf.PdfReader) -> tuple[int, ...]:
    """Return one-based pages for top-level report outline destinations."""
    return tuple(
        sorted(
            {
                reader.get_destination_page_number(item) + 1
                for item in reader.outline
                if not isinstance(item, list)
            }
        )
    )


def write_fixture(output: pathlib.Path) -> list[pathlib.Path]:
    """Write the stable PDF and rendered page PNG evidence."""
    output.mkdir(parents=True, exist_ok=True)
    pdf = build_fixture_pdf()
    validate_pdf_content(pdf)
    pdf_path = output / "sector-report-reference.pdf"
    pdf_path.write_bytes(pdf)
    pages = render_pdf(pdf)
    validate_rendered_pages(
        pages, min_pages=6, furniture=REPORT_FURNITURE
    )
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    page_texts = [page.extract_text() or "" for page in reader.pages]
    sparse = detect_sparse_report_pages(
        pages,
        page_texts,
        opener_pages=_outline_opener_pages(reader),
    )
    if sparse:
        summary = ", ".join(
            f"{page} ({coverage:.1%})" for page, coverage in sparse
        )
        print(f"Audit sparse non-opener pages requiring review: {summary}")
    validate_crops(pages, _REPORT_CROPS)
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
