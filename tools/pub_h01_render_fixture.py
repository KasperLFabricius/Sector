"""Render retained PUB-H01 formatting evidence, separate from native member QA."""

from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import io
import math
import pathlib
import pickle
import json
import re
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

from sector import capacity, codes, combined, shear
from tools import report_render_fixture


def _fixture_input() -> dict:
    inp = report_render_fixture._inputs()
    inp.update(
        mode="Plastic",
        sls_heightened_on=False,
        combined_on=True,
        combined_method=codes.EC2_2005.label,
        shear_on=True,
        shear_method=codes.EC2_2005.label,
        torsion_on=True,
        torsion_method=codes.EC2_2005.label,
    )
    return inp


def _fixed_member_angle_results(inp: dict, source: dict) -> tuple[dict, dict, dict]:
    """Rebuild the complete first-generation state at the frozen cot(theta)."""

    code = codes.EC2_2005
    cot = 1.156
    theta_deg = math.degrees(math.atan2(1.0, cot))
    fck = 30.0
    fcd = fck / 1.5
    fywk = 500.0
    gamma_s = 1.15
    fywd = fywk / gamma_s
    link_dia = 10.0
    link_spacing = 150.0
    link_legs = 2.0
    link_asw = link_legs * math.pi * link_dia ** 2 / 4.0
    link_asw_over_s = link_asw / link_spacing
    torsion_asw = math.pi * link_dia ** 2 / 4.0
    torsion_asw_over_s = torsion_asw / link_spacing
    fctk_005 = 0.7 * codes.fctm(fck)
    fctd = fctk_005 / code.gamma_ct
    shear_result = shear.vrd_c(
        fck,
        code,
        bw_mm=200.0,
        d_mm=270.0,
        asl_mm2=500.0,
        n_ed_comp_kn=0.0,
        ac_m2=0.06,
        gamma_c=1.5,
    )
    link_result = shear.vrd_links(
        fck,
        code,
        bw_mm=200.0,
        d_mm=270.0,
        asw_over_s=link_asw_over_s,
        fywk=fywk,
        n_ed_comp_kn=0.0,
        ac_m2=0.06,
        cot_min=cot,
        cot_max=cot,
        z_mm=243.0,
        fcd_mpa=fcd,
        gamma_s=gamma_s,
    )
    torsion_result = capacity.tube_torsion(
        source["torsion"]["tube"],
        25.0,
        tcode=code,
        fck=fck,
        fcd=fcd,
        alpha_cw=1.0,
        fywd=fywd,
        asw_over_s=torsion_asw_over_s,
        cot_min=cot,
        cot_max=cot,
        nu_detail=False,
        fctd=fctd,
        fyd_long=fywd,
        closed_links_present=True,
    )

    shear_payload = copy.deepcopy(source["shear"])
    shear_payload.update(
        res=shear_result,
        util=30.0 / shear_result["vrd_c"],
        method=code.label,
        model_2023=False,
    )
    shear_payload["links"].update(
        res=link_result,
        util=30.0 / link_result["vrd"],
        delta_ftd=0.5 * 30.0 * cot,
        longitudinal_shear_force=0.5 * 30.0 * cot,
        cot_min=1.0,
        cot_max=2.5,
    )

    interaction = {
        "valid": True,
        "cot": cot,
        "theta_deg": theta_deg,
        "trd_max": torsion_result["trd_max"],
        "vrd_max": link_result["vrd_max"],
        "t_ed": 25.0,
        "v_ed": 30.0,
        "value": combined.crushing_interaction(
            25.0,
            torsion_result["trd_max"],
            30.0,
            link_result["vrd_max"],
        ),
    }
    minimum_screen = dataclasses.asdict(
        combined.minimum_reinforcement_screen_result(
            25.0,
            torsion_result["trd_c"],
            30.0,
            shear_result["vrd_c"],
            solid_rectangle=True,
            subdivided=False,
            model_2023=False,
            shear_available=True,
            dk_na=False,
            shear_method=code.label,
            torsion_method=code.label,
            n_ed=0.0,
            mx_ed=80.0,
            my_ed=0.0,
        )
    )
    torsion_payload = copy.deepcopy(source["torsion"])
    torsion_payload.update(
        trd_s=torsion_result["trd_s"],
        trd_max=torsion_result["trd_max"],
        trd=torsion_result["trd"],
        trd_c=torsion_result["trd_c"],
        cot=cot,
        theta_deg=theta_deg,
        util=torsion_result["util"],
        asl_req=torsion_result["asl_req"],
        applicability=capacity.torsion_applicability(inp, 25.0),
        fcd=fcd,
        fywd=fywd,
        fyd_long=fywd,
        nu=torsion_result["nu"],
        fctk_005=fctk_005,
        gamma_ct=code.gamma_ct,
        fctd=fctd,
        asw_t=torsion_asw,
        asw_over_s=torsion_asw_over_s,
        method=code.label,
        governs=torsion_result["governs"],
        primary=torsion_result,
        interaction=interaction,
        min_reinf=minimum_screen,
    )
    for retained_name in (
        "angle_selection",
        "steel_resistance",
        "strut_resistance",
        "resistance_selection",
        "cracking_resistance",
        "longitudinal_reinforcement",
    ):
        torsion_payload[retained_name] = torsion_result[retained_name]

    torsion_fraction = 25.0 / torsion_result["trd_s"]
    crushing_value = interaction["value"]
    transverse = {
        "valid": True,
        "cot": cot,
        "theta_deg": theta_deg,
        "u_stirrup": torsion_fraction,
        "u_crush": crushing_value,
        "governing": max(torsion_fraction, crushing_value),
        "governs": (
            "stirrups" if torsion_fraction >= crushing_value else "crushing"
        ),
        "ok": max(torsion_fraction, crushing_value) <= 1.0 + 1.0e-9,
        "shear_fraction": 0.0,
        "torsion_fraction": torsion_fraction,
        "shear_credited": True,
        "vrd_c": shear_result["vrd_c"],
        "v_ed": 30.0,
    }
    direct = {
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
        "cap_shear_force": True,
        "mv_uncapped": 4.213620,
        "shear_headroom": 20.0,
        "shear_term_selection": "uncapped",
        "m_off": 0.0,
        "has_torsion": True,
        "gets_shift": True,
        "theta_mode": "utilisation",
    }
    combined_payload = {
        "valid": True,
        "method": code.label,
        "outside_default_range": False,
        "crushing": interaction,
        "transverse": transverse,
        "longitudinal": direct,
        "longitudinal_all_conditional": True,
        "asl_torsion": torsion_result["asl_req"],
        "delta_ftd": 0.5 * 30.0 * cot,
        "links": True,
        "torsion_longitudinal_assessment": {
            "status": "NOT ASSESSED",
            "ok": None,
            "reason": "longitudinal_torsion_reinforcement_not_verified",
            "required_asl_mm2": 500.0,
            "required_design_force_kn": 200.0,
            "provided_design_force_kn": 400.0,
            "reference_fyd_mpa": 400.0,
            "demand_ratio": 0.50,
            "area_sufficient": True,
        },
    }
    combined_payload["overall_longitudinal_assessment"] = (
        capacity.combined_longitudinal_assessment(combined_payload)
    )
    return shear_payload, torsion_payload, combined_payload


def _fixture_output(inp: dict) -> dict:
    out = report_render_fixture._results(inp)
    shear_payload, torsion_payload, combined = _fixed_member_angle_results(
        inp,
        out,
    )
    out["shear"] = shear_payload
    out["torsion"] = torsion_payload
    out["combined"] = combined
    out["plastic_cases"][0]["results"].update(
        shear=shear_payload,
        torsion=torsion_payload,
        combined=combined,
    )
    out["worked_example_selection"] = (
        result_presentation.worked_example_selection(inp, out)
    )
    return out


def _report_pdf(profile: str, *, evidence_path: pathlib.Path | None = None) -> bytes:
    """Exercise the frozen operands through actual retained component formatters."""
    inp = _fixture_input()
    out = _fixture_output(inp)
    original = pickle.dumps((inp,out))
    buffer = io.BytesIO()
    builder = sector_report.ReportBuilder(buffer, {}, inp, out, figures=False, profile=profile)
    contexts = builder._case_contexts("plastic")
    assert [result_presentation.action_set(ci,"plastic")["id"] for ci,co in contexts] == ["PL-QA-1","PL-QA-2"]
    matching = [(ci,co) for ci,co in contexts if result_presentation.action_set(ci,"plastic")["id"] == "PL-QA-1"]
    assert len(matching) == 1
    case_input,case_output = matching[0]
    assert case_input["_report_case_current"] is True
    assert case_output["combined"] is out["combined"]
    assert case_output["torsion"] is out["torsion"]
    assert result_presentation.action_set(case_input,"plastic")["id"] == "PL-QA-1"
    current,reason = result_presentation.combined_publication_evidence_is_current(case_input,case_output)
    assert current is False
    assert result_presentation.combined_bending_assessment_blocker(case_output,case_input) is not None
    combined_result = case_output["combined"]
    rows = result_presentation._base_en_combined_summary_rows(case_input,combined_result)
    target = next(row for row in rows if row["overview_key"] == "combined:longitudinal")
    assert target["status"] == "FAIL" and target["case"] == "PL-QA-1"
    assert math.isclose(target["util"],1.2392531643,rel_tol=1e-8)
    builder.inp,builder.out = case_input,case_output
    builder._h1("Retained PUB-H01 formatting fixture - " + profile)
    builder._p("Frozen component operands for report formatting verification. "
               "This document is not a current member calculation. Native calculation "
               "and complete report qualification are performed separately.")
    fields = ("check","case","status","result")
    expected_rows = [[str(row[key]) for key in fields] for row in rows]
    builder._table([["Check","Action set","Status","Result"],*expected_rows],
                   [85*sector_report.mm,25*sector_report.mm,30*sector_report.mm,30*sector_report.mm])
    def tables(items):
        for item in items:
            if isinstance(item,sector_report.Table):yield item
            elif isinstance(item,sector_report.KeepTogether):yield from tables(item._content)
    actual_tables=list(tables(builder.flow))
    assert len(actual_tables)==1
    table=actual_tables[0]
    actual_rows=[[cell.getPlainText() if hasattr(cell,"getPlainText") else str(cell) for cell in row]
                 for row in table._cellvalues[table._sector_data_start:]]
    assert actual_rows==expected_rows
    if profile in {"Standard","Audit"}:
        builder._combined_base_en_components(combined_result)
        builder._torsion_components(case_output["torsion"],critical=True)
    sector_report.SimpleDocTemplate(buffer,pagesize=sector_report.A4,
        leftMargin=20*sector_report.mm,rightMargin=20*sector_report.mm,
        topMargin=25*sector_report.mm,bottomMargin=20*sector_report.mm).build(list(builder.flow))
    assert pickle.dumps((inp,out))==original
    if evidence_path is not None:
        evidence_path.write_text(json.dumps({"scope":"Retained formatting only",
            "native_combined_current":current,"native_rejection_reason":reason,
            "rows":rows,"canonical_longitudinal":capacity.combined_longitudinal_assessment(combined_result),
            "retained_input_output_sha256":hashlib.sha256(original).hexdigest()},default=str,indent=2))
        evidence_path.with_suffix(".pickle").write_bytes(original)
    return buffer.getvalue()


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
    combined_row = re.compile(
        r"Combined longitudinal reinforcement\s+PL-QA-1\s+"
        r"FAIL\s+123[.,]9\s*%"
    )
    if combined_row.search(text) is None:
        raise AssertionError(
            f"{profile} report does not bind the 123.9 % failure to the "
            "combined longitudinal row"
        )
    for forbidden in (
        "Longitudinal reinforcement inf",
        "Combined longitudinal reinforcement PL-QA-1 NOT ASSESSED",
        "Traceback",
    ):
        if forbidden in text:
            raise AssertionError(f"{profile} report exposes: {forbidden}")
    if profile in {"Standard", "Audit"}:
        operand_row = re.compile(
            r"MEd\s+Shear shift\s+Torsion share\s+MEd,total\s+MRd\s+"
            r"Chord utilisation\s+80[.,]000 kNm\s+4[.,]214 kNm\s+"
            r"39[.,]712 kNm\s+123[.,]925 kNm\s+100[.,]000 kNm\s+"
            r"123[.,]9\s*%\s+FAIL"
        )
        if operand_row.search(text) is None:
            raise AssertionError(
                f"{profile} report does not retain one reconciled "
                "combined-longitudinal operand chain"
            )
        overall_assessment = re.compile(
            r"Overall longitudinal reinforcement assessment:\s+"
            r"123[.,]9\s*%\s+FAIL\.\s+Governing check:\s+"
            r"combined M \+ V \+ T tension chord\."
        )
        if overall_assessment.search(text) is None:
            raise AssertionError(
                f"{profile} report does not retain the separate governing "
                "longitudinal assessment"
            )
        for expected in (
            "Common member angle cot \u03b8 = 1.156",
            "Strut angle \u03b8 40.9\u00b0 (cot \u03b8 = 1.156)",
        ):
            if expected not in text:
                raise AssertionError(f"{profile} report is missing: {expected}")


def write_fixture(output: pathlib.Path) -> list[pathlib.Path]:
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for profile in ("Brief", "Standard", "Audit"):
        pdf = _report_pdf(profile, evidence_path=output / ("retained-pub-h01-" + profile.casefold() + ".json"))
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
