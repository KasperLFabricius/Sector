"""Render the frozen PUB-H01 Brief, Standard and Audit report evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
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

import result_presentation
import sector_report

from sector import capacity, codes
from tools import report_render_fixture


def _fixture_input() -> dict:
    inp = report_render_fixture._inputs()
    inp.update(
        mode="Plastic",
        combined_on=True,
        combined_method=codes.EC2_2005.label,
        shear_on=True,
        shear_method=codes.EC2_2005.label,
        torsion_on=True,
        torsion_method=codes.EC2_2005.label,
    )
    return inp


def _exact_combined_result(source: dict) -> dict:
    combined = copy.deepcopy(source)
    for key in (
        "r_n",
        "r_m",
        "r_v",
        "r_t",
        "m_v_independent",
        "dkna_sum",
        "dkna_valid",
        "dkna_ok",
        "dkna_selection",
        "action_alone",
        "source_clause",
        "governing_longitudinal",
        "longitudinal_assessment",
        "longitudinal_candidates",
        "longitudinal_fallback",
        "overall_longitudinal_assessment",
    ):
        combined.pop(key, None)
    direct = {
        **combined["longitudinal"],
        "valid": True,
        "status": "FAIL",
        "ok": False,
        "axis": "x",
        "tension_low": True,
        "conditional": True,
        "biaxial": False,
        "off_util": 0.0,
        "off_not_evaluated": None,
        "m_ed": 80.0,
        "mv": 4.213620,
        "mt": 39.711696,
        "m_total": 123.925316,
        "m_rd": 100.0,
        "ftd_v": 17.34,
        "ftd_t": 326.8452380952381,
        "z": 0.243,
        "util": 1.2392531643,
        "capped": False,
    }
    combined.update(
        valid=True,
        method=codes.EC2_2005.label,
        longitudinal=direct,
        longitudinal_all_conditional=True,
        torsion_longitudinal_assessment={
            "status": "NOT ASSESSED",
            "ok": None,
            "reason": "longitudinal_torsion_reinforcement_not_verified",
            "demand_ratio": 0.50,
        },
    )
    combined["overall_longitudinal_assessment"] = (
        capacity.combined_longitudinal_assessment(combined)
    )
    return combined


def _fixture_output(inp: dict) -> dict:
    out = report_render_fixture._results(inp)
    combined = _exact_combined_result(out["combined"])
    out["combined"] = combined
    out["plastic_cases"][0]["results"]["combined"] = combined
    out["worked_example_selection"] = (
        result_presentation.worked_example_selection(inp, out)
    )
    return out


def _report_pdf(profile: str) -> bytes:
    inp = _fixture_input()
    return sector_report.build_report(
        {
            "proj_no": "QA-PUB-H01",
            "proj_name": "Canonical result publication",
            "section": "200 x 300 mm reference section",
            "author": "Sector QA",
            "calculation_state": "Current calculation",
        },
        inp,
        _fixture_output(inp),
        figures=False,
        profile=profile,
    )


def _flat_pdf_text(pdf: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    return " ".join(
        " ".join((page.extract_text() or "").split())
        for page in reader.pages
    )


def _validate_report(pdf: bytes, profile: str) -> None:
    if not pdf.startswith(b"%PDF"):
        raise AssertionError(f"{profile} report is not a PDF")
    text = _flat_pdf_text(pdf)
    for expected in (
        "Combined longitudinal reinforcement",
        "123.9 %",
        "FAIL",
    ):
        if expected not in text:
            raise AssertionError(f"{profile} report is missing: {expected}")
    for forbidden in (
        "Longitudinal reinforcement inf",
        "Combined longitudinal reinforcement PL-QA-1 NOT ASSESSED",
        "Traceback",
    ):
        if forbidden in text:
            raise AssertionError(f"{profile} report exposes: {forbidden}")
    if profile in {"Standard", "Audit"}:
        for expected in (
            "80.000 kNm",
            "4.214 kNm",
            "39.712 kNm",
            "123.925 kNm",
            "100.000 kNm",
        ):
            if expected not in text:
                raise AssertionError(f"{profile} report is missing: {expected}")


def write_fixture(output: pathlib.Path) -> list[pathlib.Path]:
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for profile in ("Brief", "Standard", "Audit"):
        pdf = _report_pdf(profile)
        _validate_report(pdf, profile)
        path = output / f"pub-h01-{profile.casefold()}-report.pdf"
        path.write_bytes(pdf)
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    paths = write_fixture(args.output)
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        pages = len(pypdf.PdfReader(path).pages)
        print(f"{path.name}: {pages} pages, sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
