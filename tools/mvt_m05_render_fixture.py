"""Render the four frozen MVT-M05 practising-engineer PDF artifacts."""

from __future__ import annotations

import argparse
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

import manual
import sector_report

from sector import capacity, codes
from tools import report_render_fixture


def _blocked_input() -> dict:
    inp = report_render_fixture._inputs()
    inp.update(
        mode="Plastic",
        shear_on=True,
        torsion_on=True,
        combined_on=True,
        torsion_method=codes.EC2_2005_DKNA.label,
        torsion_T=-40.0,
        torsion_design_basis=capacity.TORSION_DESIGN_COMPATIBILITY_MEMBER,
        torsion_member_scope=capacity.TORSION_MEMBER_OPEN,
    )
    inp["plastic_case"]["t_ed_knm"] = -40.0
    inp["plastic_cases"][0]["t_ed_knm"] = -40.0
    return inp


def _blocked_result() -> dict:
    applicability = capacity.torsion_applicability(
        {
            "torsion_design_basis": capacity.TORSION_DESIGN_COMPATIBILITY_MEMBER,
            "torsion_member_scope": capacity.TORSION_MEMBER_OPEN,
        },
        40.0,
    )
    return capacity.unassessed_torsion_applicability(
        {
            "applicability": applicability,
            "t_ed": 40.0,
            "t_ed_signed": -40.0,
            "method": codes.EC2_2005_DKNA.label,
        }
    )


def _blocked_output(inp: dict) -> dict:
    out = report_render_fixture._results(inp)
    blocked = _blocked_result()
    out["torsion"] = blocked
    first_case = out["plastic_cases"][0]
    first_case["actions"]["t_ed_knm"] = -40.0
    first_case["results"]["torsion"] = blocked
    out["worked_example_selection"] = (
        report_render_fixture.result_presentation.worked_example_selection(
            inp, out
        )
    )
    return out


def _report_pdf(profile: str) -> bytes:
    inp = _blocked_input()
    return sector_report.build_report(
        {
            "proj_no": "QA-APPLICABILITY",
            "proj_name": "Torsion member-scope assessment",
            "section": "Reference section",
            "author": "Sector QA",
            "calculation_state": "Current calculation",
        },
        inp,
        _blocked_output(inp),
        figures=False,
        profile=profile,
    )


def _flat_pdf_text(pdf: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    return " ".join(
        " ".join((page.extract_text() or "").split()) for page in reader.pages
    )


def _validate_report(pdf: bytes, profile: str) -> None:
    if not pdf.startswith(b"%PDF"):
        raise AssertionError(f"{profile} report is not a PDF")
    text = _flat_pdf_text(pdf)
    for expected in (
        "Compatibility torsion",
        "Open thin-walled or warping-sensitive section",
        "NOT ASSESSED",
        "separate member or system assessment",
    ):
        if expected not in text:
            raise AssertionError(f"{profile} report is missing: {expected}")
    for forbidden in ("Traceback", "schema", "payload", "999"):
        if forbidden in text:
            raise AssertionError(f"{profile} report exposes: {forbidden}")
    if profile in {"Standard", "Audit"}:
        for expected in (
            "Torsion applicability and member scope",
            "6.3.1(1)-(3)",
            "6.3.3(1)-(2)",
        ):
            if expected not in text:
                raise AssertionError(f"{profile} report is missing: {expected}")


def _validate_manual(pdf: bytes) -> None:
    if not pdf.startswith(b"%PDF"):
        raise AssertionError("manual is not a PDF")
    text = _flat_pdf_text(pdf)
    for expected in (
        "equilibrium torsion, which must be resisted",
        "open thin-walled or warping-sensitive members",
        "warping-torsion/member assessment",
        "Sector does not establish redistribution, restraints or member response",
    ):
        if expected not in text:
            raise AssertionError(f"manual is missing: {expected}")


def write_fixture(output: pathlib.Path) -> list[pathlib.Path]:
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for profile in ("Brief", "Standard", "Audit"):
        pdf = _report_pdf(profile)
        _validate_report(pdf, profile)
        path = output / f"mvt-m05-{profile.casefold()}-report.pdf"
        path.write_bytes(pdf)
        paths.append(path)
    manual_pdf = manual.build_manual_pdf_bytes()
    _validate_manual(manual_pdf)
    manual_path = output / "mvt-m05-illustrated-manual.pdf"
    manual_path.write_bytes(manual_pdf)
    paths.append(manual_path)
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
