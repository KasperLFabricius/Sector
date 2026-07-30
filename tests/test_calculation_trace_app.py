"""Application, Streamlit and report reuse checks for PI-019 traces."""

from __future__ import annotations

import copy
import dataclasses
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
from sector.calculation_trace import (
    PROVENANCE_PROJECT,
    PROVENANCE_STANDARD,
    ROLE_FINAL,
    SourceCitation,
    TraceCalculation,
    TraceEvaluation,
    TraceStep,
    TraceValidationError,
)
from sector.trace_registry import (
    EXPLICIT_STATE,
    TraceFamilyExpectation,
    audit_trace_registry,
)
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


def _calculation_for(member, *, warning=None):
    document = next(iter(member.required_documents), None)
    source = (
        SourceCitation(document=document, clause="test", locator="test")
        if document is not None
        else None
    )
    step = TraceStep(
        step_id="result",
        title="Registry fixture result",
        dependency_ids=(),
        quantity_role=ROLE_FINAL,
        provenance=(
            PROVENANCE_STANDARD if source is not None else PROVENANCE_PROJECT
        ),
        symbol="R",
        unit="1",
        source_citation=source,
        symbolic_expression="R = solver result",
        substituted_expression="R = 1",
        evaluated_value=1.0,
        evaluation=TraceEvaluation(
            operator="solver",
            operand_ids=(),
            result_unit="1",
        ),
        warnings=((warning,) if warning else ()),
    )
    return TraceCalculation(
        calculation_id=member.calculation_id,
        coverage_id=member.coverage_id,
        title=member.member_id,
        method_id=member.method_id,
        method_label=member.method_id,
        standard_based=member.standard_based,
        user_defined_method=member.user_defined_method,
        final_step_id="result",
        steps=(step,),
        context=member.context,
        warnings=((warning,) if warning else ()),
    )


def _case_family(family_id, inp, result, context):
    families = analysis_trace.trace_coverage_registry.registered_families(
        analysis_trace.trace_coverage_registry.CASE_CALCULATION_FAMILY_REGISTRY,
        inp=inp,
        result=result,
        context=context,
    )
    return next(family for family in families if family.family_id == family_id)


def _global_family(family_id, inp, result):
    families = analysis_trace.trace_coverage_registry.registered_families(
        analysis_trace.trace_coverage_registry.GLOBAL_CALCULATION_FAMILY_REGISTRY,
        inp=inp,
        result=result,
        context=analysis_trace._context("global", "global"),
    )
    return next(family for family in families if family.family_id == family_id)


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
            "minimum longitudinal reinforcement calculation family "
            "trace registry is incomplete"
        ),
    ):
        analysis_trace.build_bundle(inp, result)


def test_named_case_audit_rejects_dropped_radial_and_first_cracking_traces(
    monkeypatch,
):
    at = _calculated_both()
    inp = at.session_state["_latest_inputs"]
    result = copy.deepcopy(at.session_state["results"])
    result.pop(analysis_trace.TRACE_KEY)

    plastic_builder = analysis_trace.trace_builders.plastic_calculations

    def without_radial(*args, **kwargs):
        return [
            calculation
            for calculation in plastic_builder(*args, **kwargs)
            if calculation.coverage_id != "CT-003"
        ]

    monkeypatch.setattr(
        analysis_trace.trace_builders,
        "plastic_calculations",
        without_radial,
    )
    with pytest.raises(
        TraceValidationError,
        match="plastic calculation family trace registry is incomplete",
    ):
        analysis_trace.build_bundle(inp, result)

    monkeypatch.setattr(
        analysis_trace.trace_builders,
        "plastic_calculations",
        plastic_builder,
    )
    elastic_builder = analysis_trace.trace_builders.elastic_calculations

    def without_cracking_factor(*args, **kwargs):
        return [
            calculation
            for calculation in elastic_builder(*args, **kwargs)
            if not calculation.calculation_id.endswith("-cracking-factor")
        ]

    monkeypatch.setattr(
        analysis_trace.trace_builders,
        "elastic_calculations",
        without_cracking_factor,
    )
    with pytest.raises(
        TraceValidationError,
        match=(
            "elastic and crack-width calculation family trace registry "
            "is incomplete"
        ),
    ):
        analysis_trace.build_bundle(inp, result)


def test_case_audit_requires_every_plastic_interaction_axis():
    context = analysis_trace._context("direct", "direct")
    payload = {
        "plastic": {
            "util": 0.5,
            "interaction": {
                "x": {"N": [0.0], "M": [1.0]},
                "y": {"N": [0.0], "M": [1.0]},
            },
        },
    }
    family = _case_family("plastic", {}, payload, context)
    calculations = [
        _calculation_for(member)
        for member in family.members
        if member.member_id != "plastic.interaction.y"
    ]

    with pytest.raises(
        TraceValidationError,
        match="plastic calculation family trace registry is incomplete",
    ):
        analysis_trace._require_case_trace_coverage(
            {},
            payload,
            calculations,
            context=context,
        )

    calculations.append(
        _calculation_for(
            next(
                member
                for member in family.members
                if member.member_id == "plastic.interaction.y"
            )
        )
    )
    analysis_trace._require_case_trace_coverage(
        {},
        payload,
        calculations,
        context=context,
    )


def test_case_audit_matches_exact_crack_and_shear_method_families():
    context = analysis_trace._context("direct", "direct")
    elastic = {
        "elastic": {
            "crack": {
                "edition": "2023",
                "coarse": False,
                "direct_tension": False,
            },
        },
    }
    elastic_family = _case_family(
        "elastic",
        {"sls_dk_na": False},
        elastic,
        context,
    )
    wrong_crack = [_calculation_for(member) for member in elastic_family.members]
    crack_index = next(
        index
        for index, member in enumerate(elastic_family.members)
        if member.member_id == "crack.crack"
    )
    wrong_crack[crack_index] = dataclasses.replace(
        wrong_crack[crack_index],
        coverage_id="CT-006",
        method_id="ec2-2005",
    )
    with pytest.raises(
        TraceValidationError,
        match="crack.crack trace identity mismatch",
    ):
        analysis_trace._require_case_trace_coverage(
            {"sls_dk_na": False},
            elastic,
            wrong_crack,
            context=context,
        )

    shear = {
        "shear": {
            "res": {"valid": True, "model": "2023"},
            "model_2023": True,
            "util": 0.5,
        },
    }
    shear_family = _case_family("shear", {}, shear, context)
    wrong_shear = [_calculation_for(shear_family.members[0])]
    wrong_shear[0] = dataclasses.replace(
        wrong_shear[0],
        coverage_id="CT-009",
        method_id="ec2-2005",
    )
    with pytest.raises(
        TraceValidationError,
        match="shear.without-links.*trace identity mismatch",
    ):
        analysis_trace._require_case_trace_coverage(
            {},
            shear,
            wrong_shear,
            context=context,
        )


def test_case_audit_matches_exact_minimum_and_transverse_editions():
    context = analysis_trace._context("direct", "direct")
    minimum = {
        "minimum_reinforcement": {
            "edition": "EN 1992-1-1:2023",
            "checks": [{"status": "PASS", "utilisation": 0.5}],
        },
    }
    minimum_family = _case_family(
        "minimum-reinforcement",
        {},
        minimum,
        context,
    )
    wrong_minimum = _calculation_for(minimum_family.members[0])
    wrong_minimum = dataclasses.replace(
        wrong_minimum,
        coverage_id="CT-017",
        method_id="ec2-2005-formula-9-1n",
    )
    with pytest.raises(
        TraceValidationError,
        match="minimum-reinforcement.check.1 trace identity mismatch",
    ):
        analysis_trace._require_case_trace_coverage(
            {},
            minimum,
            [wrong_minimum],
            context=context,
        )

    transverse = {
        "transverse_reinforcement": {
            "edition": "EN 1992-1-1:2023",
            "checks": [
                {
                    "status": "FAIL",
                    "kind": "spacing",
                    "utilisation": 1.2,
                }
            ],
        },
    }
    transverse_family = _case_family(
        "transverse-reinforcement",
        {},
        transverse,
        context,
    )
    wrong_transverse = _calculation_for(transverse_family.members[0])
    wrong_transverse = dataclasses.replace(
        wrong_transverse,
        method_id="ec2-2005-transverse",
    )
    with pytest.raises(
        TraceValidationError,
        match="transverse-reinforcement.check.1 trace identity mismatch",
    ):
        analysis_trace._require_case_trace_coverage(
            {},
            transverse,
            [wrong_transverse],
            context=context,
        )


def test_global_audit_matches_exact_concrete_fatigue_family():
    result = {
        "fatigue": {
            "edition": "EN 1992-1-1:2023",
            "spectra": [
                {
                    "spectrum_name": "Traffic",
                    "concrete": [
                        {
                            "bins": [{}],
                            "method": "equivalent",
                            "fibre_index": 0,
                        }
                    ],
                }
            ],
        }
    }
    fatigue_family = _global_family("fatigue", {}, result)
    correct = [_calculation_for(fatigue_family.members[0])]
    wrong = [
        dataclasses.replace(
            correct[0],
            coverage_id="CT-022",
            method_id="ec2-2005-equivalent",
        )
    ]
    with pytest.raises(
        TraceValidationError,
        match="fatigue.concrete.*trace identity mismatch",
    ):
        analysis_trace._require_global_trace_coverage({}, result, wrong)

    analysis_trace._require_global_trace_coverage({}, result, correct)


def test_registry_owns_every_retained_coverage_id_once():
    registrations = (
        *analysis_trace.trace_coverage_registry.CASE_CALCULATION_FAMILY_REGISTRY,
        *analysis_trace.trace_coverage_registry.GLOBAL_CALCULATION_FAMILY_REGISTRY,
    )
    coverage = [
        coverage_id
        for registration in registrations
        for coverage_id in registration.coverage_ids
    ]
    assert len(coverage) == len(set(coverage))
    assert set(coverage) == {
        f"CT-{index:03d}" for index in range(1, 28)
    }


def test_registry_rejects_noninjective_expected_calculation_ids():
    context = analysis_trace._context("direct", "direct")
    family = _case_family(
        "plastic",
        {},
        {"plastic": {}},
        context,
    )
    member = family.members[0]
    duplicate = dataclasses.replace(
        member,
        member_id="plastic.capacity.alias",
    )
    malformed = dataclasses.replace(
        family,
        members=(member, duplicate),
    )
    with pytest.raises(
        TraceValidationError,
        match="non-injective expected calculation ID",
    ):
        audit_trace_registry([], scope_id="test", families=[malformed])


def test_registry_enforces_dependency_closure_and_explicit_state_warning():
    context = analysis_trace._context("direct", "direct")
    family = _case_family(
        "plastic",
        {},
        {"plastic": {}},
        context,
    )
    member = family.members[0]
    calculation = _calculation_for(member)
    broken_step = dataclasses.replace(
        calculation.steps[0],
        dependency_ids=("missing",),
        evaluation=dataclasses.replace(
            calculation.steps[0].evaluation,
            operand_ids=("missing",),
        ),
    )
    broken = dataclasses.replace(calculation, steps=(broken_step,))
    with pytest.raises(
        TraceValidationError,
        match="missing or forward dependency",
    ):
        audit_trace_registry(
            [broken],
            scope_id="test",
            families=[family],
        )

    explicit_member = dataclasses.replace(
        member,
        result_state=EXPLICIT_STATE,
    )
    explicit_family = TraceFamilyExpectation(
        family_id=family.family_id,
        label=family.label,
        coverage_ids=family.coverage_ids,
        members=(explicit_member,),
    )
    with pytest.raises(
        TraceValidationError,
        match="requires a published warning",
    ):
        audit_trace_registry(
            [calculation],
            scope_id="test",
            families=[explicit_family],
        )
    audit_trace_registry(
        [_calculation_for(explicit_member, warning="explicit solver state")],
        scope_id="test",
        families=[explicit_family],
    )


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
