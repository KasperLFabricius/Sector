"""Build and rasterise the focused PR-05 Danish bridge report fixture."""

from __future__ import annotations

import argparse
import copy
import dataclasses
import io
import pathlib
import sys

import pypdf

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bridge_inputs  # noqa: E402
import bridge_analysis  # noqa: E402
import sector_report  # noqa: E402
from sector import (  # noqa: E402
    __version__,
    bridge,
    conformance,
    danish_bridge,
    sls,
)
from sector.codes import fctm  # noqa: E402
from sector.section import Section  # noqa: E402
from sector.serviceability import analyse_cracking  # noqa: E402
from tools import report_render_fixture  # noqa: E402


def fixture_decisions() -> tuple[bridge.ApplicabilityDecision, ...]:
    return tuple(
        bridge.ApplicabilityDecision(
            check_id,
            (
                bridge.REQUIRED
                if check_id in {"section_analysis", "sls_crack"}
                else bridge.NOT_APPLICABLE
            ),
            f"DB-{check_id}",
        )
        for check_id in bridge.APPLICABILITY_CHECK_IDS
    )


def fixture_inputs() -> dict:
    """Return a stable, complete Danish basis beside inherited section inputs."""

    inp = report_render_fixture._inputs()
    inp.update({
        "mode": "Elastic",
        "design_methodology": bridge.EN1992_2_DK_NA,
        "sls_code": bridge.EN1992_2_DK_NA,
        "sls_edition": sls.EDITION_BRIDGE_DK_2015,
        "sls_dk_na": True,
        "sls_member": "Beam",
        "sls_has_tendons": False,
        "sls_wk_limit": 0.20,
        "sls_fctm": fctm(30.0),
        "sls_phi": 20.0,
        "sls_dk_member_class": danish_bridge.MEMBER_NONPRESTRESSED,
        "fatigue_on": False,
        "torsion_on": False,
        "bridge_asset_class": danish_bridge.ASSET_ROAD,
        "bridge_infrastructure_manager": (
            danish_bridge.MANAGER_ROAD_DIRECTORATE
        ),
        "bridge_manager_source": "VD bridge basis 2023+corr.2026",
        "bridge_project_basis_source": "DB-05 section 2.3",
        "bridge_authority_approval_reference": "",
        "bridge_traffic_fatigue_applicability": (
            danish_bridge.FATIGUE_NOT_APPLICABLE
        ),
        "bridge_traffic_fatigue_model": "",
        "bridge_traffic_fatigue_source": "",
        "bridge_environment_class": (
            danish_bridge.ENVIRONMENT_EXTRA_AGGRESSIVE
        ),
        "bridge_environment_source": "DB-05 section 4.2",
        "bridge_special_rules": "No mapped special relaxation",
        "bridge_departure_applicability": (
            danish_bridge.APPLICABILITY_NOT_APPLICABLE
        ),
        "bridge_departure_source": "",
        "bridge_deviations": "",
        "bridge_control_class": danish_bridge.CONTROL_NORMAL,
        "bridge_control_source": "DB-05 section 2.4",
        "bridge_consequence_class": danish_bridge.CONSEQUENCE_CC2,
        "bridge_consequence_source": "DB-05 section 2.5",
        "bridge_high_strength_approval": (
            danish_bridge.APPROVAL_NOT_APPLICABLE
        ),
        "bridge_high_strength_approval_reference": "",
        "bridge_execution_conditions_source": "",
        "bridge_surface_condition": danish_bridge.SURFACE_WATERPROOFED,
        "bridge_deicing_applicability": (
            danish_bridge.APPLICABILITY_REQUIRED
        ),
        "bridge_deicing_source": "DB-05 drawing G-02",
        "bridge_cover_category": danish_bridge.COVER_NONPRESTRESSED,
        "bridge_nominal_cover_mm": 20.0,
        "bridge_cover_source": "Drawing B-105 section A",
        "bridge_collision_risk_applicability": (
            danish_bridge.APPLICABILITY_NOT_APPLICABLE
        ),
        "bridge_alpha_cc_basis": conformance.STANDARD_BASIS,
        "bridge_alpha_cc_custom_methodology": "",
        "bridge_alpha_cc_approval_reference": "",
        "bridge_alpha_ct": 1.0,
        "bridge_alpha_ct_basis": conformance.STANDARD_BASIS,
        "bridge_alpha_ct_custom_methodology": "",
        "bridge_alpha_ct_approval_reference": "",
        "P_el_l": 0.0,
        "Mx_el_l": 180.0,
        "My_el_l": 0.0,
        "P_el_s": 0.0,
        "Mx_el_s": 90.0,
        "My_el_s": 0.0,
        "shear_on": False,
        "combined_on": False,
        "minimum_reinforcement_on": False,
        "transverse_detailing_on": False,
        "clear_spacing_on": False,
    })
    outer = [
        (-0.15, -0.30),
        (0.15, -0.30),
        (0.15, 0.30),
        (-0.15, 0.30),
    ]
    bars = [
        (-0.075, -0.270, 491.0),
        (0.000, -0.270, 491.0),
        (0.075, -0.270, 491.0),
    ]
    inp.update({
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
                "id": f"R{index}",
                "x_mm": x * 1000.0,
                "y_mm": y * 1000.0,
                "area_mm2": area,
                "diameter_mm": 20.0,
                "size_mode": "Area",
                "material_id": "M1",
                "fatigue_detail_id": "",
            }
            for index, (x, y, area) in enumerate(bars, start=1)
        ],
        "bar_materials": [inp["steel"], inp["steel"], inp["steel"]],
        "plastic_cases": [],
    })
    inp[bridge_inputs.COVERAGE_TABLE_KEY] = (
        bridge_inputs.table_from_records(
            [
                {
                    "check_id": item.check_id,
                    "applicability": item.applicability,
                    "source": item.source,
                    "notes": item.notes,
                }
                for item in fixture_decisions()
            ],
            bridge_inputs.COVERAGE_TABLE_KEY,
        )
    )
    elastic_case = inp["elastic_cases"][0]
    elastic_case.update({
        "name": "EL-PR05-DK-1",
        "description": (
            "Danish bridge Frequent crack width | "
            "Source: PR-05 controlled numerical fixture"
        ),
        "long_combination": sls.COMBINATION_QUASI_PERMANENT,
        "total_combination": sls.COMBINATION_FREQUENT,
        "n_long_ed_kn": 0.0,
        "mx_long_ed_knm": 180.0,
        "my_long_ed_knm": 0.0,
        "n_short_ed_kn": 0.0,
        "mx_short_ed_knm": 90.0,
        "my_short_ed_knm": 0.0,
    })
    inp["elastic_cases"] = [elastic_case]
    inp["elastic_case"] = {
        "id": "EL-PR05-DK-1",
        "type": "Danish bridge Frequent crack-width response",
        "source": "PR-05 controlled numerical fixture",
    }
    return inp


def fixture_record(inp: dict, elastic: dict) -> dict:
    """Return the immutable Danish bridge record published by the fixture."""

    return bridge.assess_base_methodology(bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_DK_NA,
        decisions=fixture_decisions(),
        has_tendons=False,
        has_hollow_section=False,
        fck_mpa=inp["concrete"].fck,
        section_analysis=bridge.ExternalEvidence(
            status=bridge.STATUS_PASS,
            result="section solve converged",
            criterion="requested solver converges",
            source="bridge inherited section solver",
            reason="QA fixture section evidence",
        ),
        sls_crack=bridge_analysis.crack_evidence(
            {"elastic": elastic},
            inp=inp,
        ),
        danish_basis=bridge_inputs.danish_basis_from_inputs(inp),
    ))


def _crack_payload(result, inp: dict) -> dict | None:
    """Flatten one calculated crack system into the report result schema."""

    if result is None:
        return None
    payload = dataclasses.asdict(result)
    bars = list(inp.get("bar_elements") or ())

    def identity(index: int) -> tuple[str, int, str]:
        number = index + 1
        element_id = (
            str(bars[index].get("id") or f"bar {number}")
            if index < len(bars) and isinstance(bars[index], dict)
            else f"bar {number}"
        )
        return "Bar", number, element_id

    kind, number, element_id = identity(result.gov_bar)
    payload.update({
        "gov_bar": result.gov_bar + 1,
        "element_type": kind,
        "element_no": number,
        "element_id": element_id,
    })
    for candidate in payload["candidates"]:
        index = int(candidate.pop("bar_index"))
        kind, number, element_id = identity(index)
        candidate.update({
            "element_type": kind,
            "element_no": number,
            "element_id": element_id,
            "x_mm": candidate.pop("x") * 1000.0,
            "y_mm": candidate.pop("y") * 1000.0,
            "area_mm2": candidate.pop("area"),
        })
    return payload


def fixture_elastic_result(inp: dict) -> dict:
    """Return a real Danish fine/coarse calculation with routed acceptance."""

    elastic = copy.deepcopy(report_render_fixture._results(inp)["elastic"])
    section = inp["section"]
    common = {
        "fctm": inp["sls_fctm"],
        "Es": 200_000.0,
        "beta": 0.5,
        "bar_diameter": inp["sls_phi"],
        "cover": 20.0,
        "k3_cover_dependent": True,
        "include_hx_term": False,
    }
    long_fine = analyse_cracking(
        section,
        inp["P_el_l"],
        inp["Mx_el_l"],
        inp["My_el_l"],
        inp["nl"],
        kt=0.4,
        **common,
    ).crack
    total_fine = analyse_cracking(
        section,
        inp["P_el_l"] + inp["P_el_s"],
        inp["Mx_el_l"] + inp["Mx_el_s"],
        inp["My_el_l"] + inp["My_el_s"],
        inp["ns"],
        kt=0.6,
        **common,
    ).crack
    long_coarse = analyse_cracking(
        section,
        inp["P_el_l"],
        inp["Mx_el_l"],
        inp["My_el_l"],
        inp["nl"],
        kt=0.4,
        coarse=True,
        **common,
    ).crack
    total_coarse = analyse_cracking(
        section,
        inp["P_el_l"] + inp["P_el_s"],
        inp["Mx_el_l"] + inp["Mx_el_s"],
        inp["My_el_l"] + inp["My_el_s"],
        inp["ns"],
        kt=0.6,
        coarse=True,
        **common,
    ).crack
    responses = {
        "Long-term (fine)": _crack_payload(long_fine, inp),
        "Total (fine)": _crack_payload(total_fine, inp),
        "Long-term (coarse)": _crack_payload(long_coarse, inp),
        "Total (coarse)": _crack_payload(total_coarse, inp),
    }
    states = {
        "Long-term (fine)": (
            sls.COMBINATION_QUASI_PERMANENT,
            "long",
        ),
        "Total (fine)": (sls.COMBINATION_FREQUENT, "total"),
        "Long-term (coarse)": (
            sls.COMBINATION_QUASI_PERMANENT,
            "long",
        ),
        "Total (coarse)": (sls.COMBINATION_FREQUENT, "total"),
    }
    contexts = {
        name: {
            "combination": combination,
            "duration": state,
            "response_id": f"EL-PR05-DK-1:{state}",
            "provenance": (
                "EL-PR05-DK-1 explicit "
                f"{combination} combination mapping"
            ),
            "solver_provenance": {
                "state": state,
                "elastic_case": copy.deepcopy(inp["elastic_case"]),
            },
        }
        for name, (combination, state) in states.items()
    }
    dispositions = {
        name: {
            "status": "CALCULATED",
            "reason": "Danish fine/coarse crack width calculated.",
            "scope": "dominant-direction",
        }
        for name in responses
    }
    mapping_scope = [
        {
            "combination": combination,
            "duration": state,
            "response": response,
            "response_id": f"EL-PR05-DK-1:{state}",
            "elastic_case": "EL-PR05-DK-1",
            "state": state,
            "provenance": (
                "EL-PR05-DK-1 explicit "
                f"{combination} combination mapping"
            ),
            "solver_provenance": {
                "state": state,
                "elastic_case": copy.deepcopy(inp["elastic_case"]),
            },
        }
        for response, combination, state in (
            (
                "Long-term (fine)",
                sls.COMBINATION_QUASI_PERMANENT,
                "long",
            ),
            ("Total (fine)", sls.COMBINATION_FREQUENT, "total"),
        )
    ]
    criteria = sls.crack_criteria_from_inputs(inp)
    assessment = sls.crack_assessment(
        responses,
        valid=True,
        dispositions=dispositions,
        response_contexts=contexts,
        response_mapping_scope=mapping_scope,
        criteria=criteria,
    )
    elastic.update({
        "show_cw": True,
        "crack": responses["Long-term (fine)"],
        "crack_short": responses["Total (fine)"],
        "crack_coarse": responses["Long-term (coarse)"],
        "crack_short_coarse": responses["Total (coarse)"],
        "crack_criteria": criteria,
        "crack_dispositions": dispositions,
        "crack_response_contexts": contexts,
        "crack_response_mapping_scope": mapping_scope,
        "crack_responses": responses,
        "crack_assessment": assessment,
        "crack_code": bridge.EN1992_2_DK_NA,
        "crack_edition": sls.EDITION_BRIDGE_DK_2015,
        "crack_member": "Beam",
        "crack_numerical_method": (
            sls.expected_danish_bridge_crack_numerical_method(inp)
        ),
        "elastic_case": copy.deepcopy(inp["elastic_case"]),
    })
    return elastic


def build_fixture_pdf() -> bytes:
    inp = fixture_inputs()
    elastic = fixture_elastic_result(inp)
    return sector_report.build_report(
        {
            "proj_no": "QA-PR05",
            "proj_name": "Danish bridge methodology fixture",
            "section": "Road bridge section",
            "author": "Sector QA",
            "source_revision": "working-tree-pr05",
        },
        inp,
        {
            "elastic": elastic,
            "elastic_cases": [{
                "name": "EL-PR05-DK-1",
                "actions": copy.deepcopy(inp["elastic_cases"][0]),
                "evaluated": True,
                "results": {"elastic": elastic},
            }],
            "bridge_methodology": fixture_record(inp, elastic),
        },
        version=__version__,
        figures=False,
    )


def validate_pdf_content(pdf: bytes) -> tuple[int, ...]:
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    texts = tuple(page.extract_text() or "" for page in reader.pages)
    normalized = " ".join(texts)
    for expected in (
        bridge.EN1992_2_DK_NA,
        "Publication validation status: ACCEPTED",
        "Danish infrastructure-manager and project basis",
        danish_bridge.MANAGER_ROAD_DIRECTORATE,
        "Departure applicability",
        "Departure methodology / source",
        "Departure authority approval",
        "Calculated fatigue authority",
        "Calculated fatigue method",
        "Calculated fatigue spectrum source",
        "Calculated fatigue cycle-count source",
        "Global fatigue analysis enabled",
        "Reinforcement fatigue applicability",
        "Reinforcement fatigue check selected",
        "Concrete fatigue applicability",
        "Concrete fatigue check selected",
        "DB-05 section 4.2",
        "DB-05 drawing G-02",
        "mapped_deicing_x_m",
        "mapped_deicing_y_m",
        "Danish bridge nominal cover",
        "Danish annex applicability",
        "Static national annex routing recorded",
        "Danish bridge QA basis",
        "Danish bridge applicability provenance",
        "Danish bridge coefficient provenance",
        "DS/EN 1992-1-1 DK NA:2013",
        "25/c",
        "Long-term (coarse)",
        "Total (coarse)",
        "Frequent",
        "0.200 mm",
    ):
        if expected not in normalized:
            raise AssertionError(f"expected PR-05 report evidence is missing: {expected}")
    affected = tuple(
        index
        for index, text in enumerate(texts, start=1)
        if (
            "Bridge methodology" in text
            or "Danish infrastructure-manager" in text
            or "Danish annex applicability" in text
            or "mapped_deicing" in text
            or "Long-term (coarse)" in text
            or "25/c" in text
        )
    )
    if not affected:
        raise AssertionError("no Danish bridge methodology page was rendered")
    return affected


def write_fixture(output: pathlib.Path) -> tuple[list[pathlib.Path], tuple[int, ...]]:
    output.mkdir(parents=True, exist_ok=True)
    pdf = build_fixture_pdf()
    affected = validate_pdf_content(pdf)
    pdf_path = output / "sector-pr05-danish-bridge-report.pdf"
    pdf_path.write_bytes(pdf)
    pages = report_render_fixture.render_pdf(pdf)
    report_render_fixture.validate_rendered_pages(
        pages,
        require_document_control=True,
    )
    paths = [pdf_path]
    for index, page in enumerate(pages, start=1):
        path = output / f"sector-pr05-report-page-{index:02d}.png"
        page.save(path, format="PNG")
        paths.append(path)
    return paths, affected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    paths, affected = write_fixture(args.output)
    print(
        f"Rendered {len(paths) - 1} report pages; "
        f"Danish methodology pages: {', '.join(map(str, affected))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
