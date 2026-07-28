"""Build and rasterise the focused PR-05 Danish bridge report fixture."""

from __future__ import annotations

import argparse
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
import sector_report  # noqa: E402
from sector import __version__, bridge, conformance, danish_bridge  # noqa: E402
from tools import report_render_fixture  # noqa: E402


def fixture_inputs() -> dict:
    """Return a stable, complete Danish basis beside inherited section inputs."""

    inp = report_render_fixture._inputs()
    inp.update({
        "design_methodology": bridge.EN1992_2_DK_NA,
        "sls_code": bridge.EN1992_2_DK_NA,
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
        "bridge_environment_class": danish_bridge.ENVIRONMENT_AGGRESSIVE,
        "bridge_environment_source": "DB-05 section 4.2",
        "bridge_special_rules": "No mapped special relaxation",
        "bridge_deviations": "None recorded",
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
        "bridge_nominal_cover_mm": 45.0,
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
    })
    return inp


def fixture_record(inp: dict) -> dict:
    """Return the immutable Danish bridge record published by the fixture."""

    decisions = tuple(
        bridge.ApplicabilityDecision(
            check_id,
            (
                bridge.REQUIRED
                if check_id == "section_analysis"
                else bridge.NOT_APPLICABLE
            ),
            f"DB-{check_id}",
        )
        for check_id in bridge.APPLICABILITY_CHECK_IDS
    )
    return bridge.assess_base_methodology(bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_DK_NA,
        decisions=decisions,
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
        danish_basis=bridge_inputs.danish_basis_from_inputs(inp),
    ))


def build_fixture_pdf() -> bytes:
    inp = fixture_inputs()
    return sector_report.build_report(
        {
            "proj_no": "QA-PR05",
            "proj_name": "Danish bridge methodology fixture",
            "section": "Road bridge section",
            "author": "Sector QA",
            "source_revision": "working-tree-pr05",
        },
        inp,
        {"bridge_methodology": fixture_record(inp)},
        version=__version__,
        figures=False,
    )


def validate_pdf_content(pdf: bytes) -> tuple[int, ...]:
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    texts = tuple(page.extract_text() or "" for page in reader.pages)
    normalized = " ".join(texts)
    for expected in (
        bridge.EN1992_2_DK_NA,
        "Danish infrastructure-manager and project basis",
        danish_bridge.MANAGER_ROAD_DIRECTORATE,
        "DB-05 section 4.2",
        "DB-05 drawing G-02",
        "mapped_deicing_x_m",
        "mapped_deicing_y_m",
        "Danish bridge nominal cover",
        "Danish annex applicability",
        "Danish bridge QA basis",
        "Danish bridge applicability provenance",
        "Danish bridge coefficient provenance",
    ):
        if expected not in normalized:
            raise AssertionError(f"expected PR-05 report evidence is missing: {expected}")
    affected = tuple(
        index
        for index, text in enumerate(texts, start=1)
        if (
            "Bridge methodology" in text
            or "Danish infrastructure-manager" in text
            or "mapped_deicing" in text
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
    report_render_fixture.validate_rendered_pages(pages)
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
