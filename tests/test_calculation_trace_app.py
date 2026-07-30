"""Application, Streamlit and report reuse checks for PI-019 traces."""

from __future__ import annotations

import copy
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tests"))

import analysis_trace
import sector_report
import test_app_smoke as smoke
from sector.calculation_trace import TraceValidationError
from tools.report_render_fixture import (
    render_pdf,
    validate_rendered_pages,
    validate_trace_pagination,
)


def _calculated_both():
    at = smoke._fresh()
    at.run()
    smoke._set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Both"),
    )
    assert not at.exception
    return at


def test_run_analysis_attaches_one_current_sealed_bundle():
    at = _calculated_both()
    inp = at.session_state["_latest_inputs"]
    result = at.session_state["results"]

    bundle = analysis_trace.validated_bundle(inp, result)
    coverage = [item.coverage_id for item in bundle.calculations]
    assert {"CT-001", "CT-002", "CT-003", "CT-005"} <= set(coverage)
    assert bundle.input_sha256 == analysis_trace.input_fingerprint(inp)
    assert bundle.result_sha256 == analysis_trace.result_fingerprint(result)
    assert all(item.steps[-1].quantity_role == "final_result"
               for item in bundle.calculations)


def test_unrelated_material_trace_cannot_mask_dropped_completed_family(
    monkeypatch,
):
    at = _calculated_both()
    inp = at.session_state["_latest_inputs"]
    result = copy.deepcopy(at.session_state["results"])
    result.pop(analysis_trace.TRACE_KEY)
    result["plastic_cases"][0]["results"]["minimum_reinforcement"] = {
        "status": "FAIL",
        "edition": "EN 1992-1-1:2005",
        "checks": [{
            "status": "FAIL",
            "utilisation": None,
            "as_min_mm2": None,
        }],
    }

    monkeypatch.setattr(
        analysis_trace.trace_builders,
        "minimum_reinforcement_calculations",
        lambda *_args, **_kwargs: [],
    )

    with pytest.raises(
        TraceValidationError,
        match=(
            "minimum longitudinal reinforcement trace coverage is "
            "incomplete"
        ),
    ):
        analysis_trace.build_bundle(inp, result)


def test_named_case_trace_ids_are_collision_free_and_context_stays_public():
    import load_cases

    at = smoke._fresh()
    at.run()
    smoke._set(at, ("radio", "mode", "Plastic"))
    plastic = at.session_state[load_cases.PLASTIC_TABLE_KEY]
    first = plastic.iloc[0].to_dict()
    smoke._replace_case_table(
        at,
        load_cases.PLASTIC_TABLE_KEY,
        [
            {**first, "name": "A+B"},
            {
                **first,
                "name": "A B",
                "mx_ed_knm": float(first["mx_ed_knm"]) + 10.0,
            },
        ],
    )

    smoke._calculate(at)

    assert not at.exception
    inp = at.session_state["_latest_inputs"]
    result = at.session_state["results"]
    bundle = analysis_trace.validated_bundle(inp, result)
    calculation_ids = [
        calculation.calculation_id for calculation in bundle.calculations
    ]
    assert len(calculation_ids) == len(set(calculation_ids))

    case_calculations = [
        calculation
        for calculation in bundle.calculations
        if dict(calculation.context).get("family") == "plastic"
    ]
    assert {
        dict(calculation.context)["case_id"]
        for calculation in case_calculations
    } == {"A+B", "A B"}
    assert all(
        all(not key.startswith("_") for key, _value in calculation.context)
        for calculation in case_calculations
    )
    ids_by_case = {
        case_name: {
            calculation.calculation_id
            for calculation in case_calculations
            if dict(calculation.context)["case_id"] == case_name
        }
        for case_name in ("A+B", "A B")
    }
    assert ids_by_case["A+B"].isdisjoint(ids_by_case["A B"])


def test_plastic_trace_uses_exact_retained_governing_state_values():
    at = smoke._fresh()
    at.run()
    smoke._set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Both"),
        ("number_input", "pl_P", -500.0),
    )
    assert not at.exception

    inp = at.session_state["_latest_inputs"]
    result = at.session_state["results"]
    plastic = result["plastic"]
    index = plastic.get("util_gov")
    if index is None or not 0 <= int(index) < len(plastic["points"]):
        index = max(
            range(len(plastic["points"])),
            key=lambda item: math.hypot(
                float(plastic["mx"][item]),
                float(plastic["my"][item]),
            ),
        )
    point = plastic["points"][int(index)]
    assert point["axial"] != 0.0
    assert point["kappa"] != 0.0
    assert point["comp_force"] != 0.0
    assert point["lever"] != 0.0

    bundle = analysis_trace.validated_bundle(inp, result)
    calculation = next(
        item
        for item in bundle.calculations
        if item.coverage_id == "CT-002"
    )
    steps = {step.step_id: step for step in calculation.steps}
    assert steps["curvature"].evaluated_value == pytest.approx(point["kappa"])
    assert steps["axial-resultant"].evaluated_value == pytest.approx(
        point["axial"]
    )
    assert steps["compression-resultant"].evaluated_value == pytest.approx(
        point["comp_force"]
    )
    assert steps["internal-lever-arm"].evaluated_value == pytest.approx(
        point["lever"]
    )
    assert steps["equilibrium"].evaluated_value == (
        1.0 if point["converged"] else 0.0
    )


def test_trace_view_renders_the_same_bundle_and_blocks_stale_publication():
    at = _calculated_both()
    smoke._select_view(at, "Calculation Trace")
    assert not at.exception
    assert any(
        "Solver-owned ordered derivations" in item.value
        for item in at.caption
    )
    assert any("CT-002" in item.label for item in at.expander)

    smoke._goto_page(at, "Inputs")
    smoke._set(at, ("number_input", "pl_Mx", 123.0))
    smoke._select_view(at, "Calculation Trace")
    assert any(
        "publication is blocked" in item.value
        for item in at.error
    )


def test_tampered_trace_is_rejected_by_publication_boundary():
    at = _calculated_both()
    inp = at.session_state["_latest_inputs"]
    result = copy.deepcopy(at.session_state["results"])
    result["calculation_trace"]["calculations"][0]["steps"][-1][
        "evaluated_value"
    ] += 1.0

    with pytest.raises(TraceValidationError, match="content seal"):
        analysis_trace.validated_bundle(inp, result)


def test_report_renders_trace_without_invoking_legacy_formula_chapters(
    monkeypatch,
):
    at = _calculated_both()
    inp = at.session_state["_latest_inputs"]
    result = at.session_state["results"]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("legacy report formula renderer was invoked")

    for name in (
        "_plastic",
        "_elastic",
        "_cracking",
        "_shear",
        "_torsion",
        "_combined",
        "_clear_spacing",
        "_fatigue",
        "_bridge",
    ):
        monkeypatch.setattr(sector_report.ReportBuilder, name, forbidden)

    pdf = sector_report.build_report(
        {"proj_no": "PI-019", "section": "TRACE"},
        inp,
        result,
        version="0.91",
        figures=False,
        qa_appendix=False,
    )
    text = " ".join(smoke._pdf_text(pdf)) if hasattr(smoke, "_pdf_text") else ""
    if not text:
        from pypdf import PdfReader
        import io

        text = " ".join(
            page.extract_text() or ""
            for page in PdfReader(io.BytesIO(pdf)).pages
        )
    assert "Ordered calculation trace" in text
    assert "CT-002" in text
    assert "Symbolic:" in text
    assert "Substitution:" in text
    assert "Dependencies:" in text
    validate_trace_pagination(pdf)
    pages = render_pdf(pdf)
    validate_rendered_pages(pages, require_document_control=True)


def test_report_rejects_stale_result_trace():
    at = _calculated_both()
    inp = copy.copy(at.session_state["_latest_inputs"])
    result = at.session_state["results"]
    inp["signature"] = (*tuple(inp["signature"]), "changed")

    with pytest.raises(TraceValidationError, match="current input signature"):
        sector_report.build_report(
            {},
            inp,
            result,
            figures=False,
            qa_appendix=False,
        )


def test_positive_custom_concrete_factor_is_retained_as_an_input():
    at = smoke._fresh()
    at.run()
    smoke._set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Both"),
        ("number_input", "conc_gamma_c", 1.80),
    )
    assert not at.exception

    inp = at.session_state["_latest_inputs"]
    result = at.session_state["results"]
    bundle = analysis_trace.validated_bundle(inp, result)
    calculation = next(
        item
        for item in bundle.calculations
        if item.coverage_id == "CT-001"
        and item.title == "Concrete design compression strength"
    )
    by_id = {step.step_id: step for step in calculation.steps}

    assert by_id["gamma-c"].quantity_role == "user_input"
    assert by_id["gamma-c"].evaluated_value == pytest.approx(1.80)
    assert by_id["fcd"].evaluated_value == pytest.approx(
        by_id["strength-factor"].evaluated_value
        * by_id["fck"].evaluated_value
        / 1.80
    )
    wording = " ".join(
        (
            *calculation.warnings,
            *by_id["gamma-c"].warnings,
            *by_id["gamma-c"].assumptions,
        )
    ).casefold()
    assert "retained" in wording
    assert "differs" in wording
    assert not any(
        forbidden in wording
        for forbidden in ("clamp", "approved", "conformity", "certified")
    )
