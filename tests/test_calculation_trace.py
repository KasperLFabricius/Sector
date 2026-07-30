"""PI-019 trace schema, freshness and adversarial validation tests."""

from __future__ import annotations

import dataclasses
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import analysis_trace
import calculation_trace_presentation as presentation
from sector import bridge, detailing, trace_builders
from sector.materials import Concrete
from sector.section import Section
from sector.trace_examples import reference_bundle
from sector.calculation_trace import (
    PROVENANCE_INPUT,
    PROVENANCE_PROJECT,
    PROVENANCE_STANDARD,
    ROLE_FINAL,
    ROLE_METHOD_VALUE,
    ROLE_USER_INPUT,
    SourceCitation,
    TraceBundle,
    TraceCalculation,
    TraceEvaluation,
    TraceStep,
    TraceValidationError,
    create_bundle,
    fingerprint_payload,
    seal_bundle,
    trace_identity_token,
    validate_bundle,
)


SOURCE = SourceCitation(
    document="DS/EN 1992-1-1:2023",
    clause="test clause",
    locator="Formula (T.1)",
)


def _simple_calculation() -> TraceCalculation:
    return TraceCalculation(
        calculation_id="test.standard.product",
        coverage_id="CT-001",
        title="Independent product",
        method_id="test-standard",
        method_label="Test standard method",
        standard_based=True,
        user_defined_method=False,
        final_step_id="result",
        steps=(
            TraceStep(
                step_id="entered",
                title="Entered quantity",
                dependency_ids=(),
                quantity_role=ROLE_USER_INPUT,
                provenance=PROVENANCE_INPUT,
                symbol="x",
                unit="kN",
                source_citation=None,
                symbolic_expression="x = user input",
                substituted_expression="x = 2 kN",
                evaluated_value=2.0,
                evaluation=TraceEvaluation(
                    operator="input",
                    result_unit="kN",
                ),
            ),
            TraceStep(
                step_id="factor",
                title="Method factor",
                dependency_ids=(),
                quantity_role=ROLE_METHOD_VALUE,
                provenance=PROVENANCE_STANDARD,
                symbol="k",
                unit="1",
                source_citation=SOURCE,
                symbolic_expression="k = selected method value",
                substituted_expression="k = 3",
                evaluated_value=3.0,
                evaluation=TraceEvaluation(
                    operator="method",
                    result_unit="1",
                ),
            ),
            TraceStep(
                step_id="result",
                title="Final product",
                dependency_ids=("entered", "factor"),
                quantity_role=ROLE_FINAL,
                provenance=PROVENANCE_STANDARD,
                symbol="R",
                unit="kN",
                source_citation=SOURCE,
                symbolic_expression="R = k x",
                substituted_expression="R = 3 x 2 = 6 kN",
                evaluated_value=6.0,
                evaluation=TraceEvaluation(
                    operator="multiply",
                    operand_ids=("entered", "factor"),
                    result_unit="kN",
                ),
            ),
        ),
        context=(("case_id", "TEST-1"), ("family", "test")),
    )


def _bundle(calculation: TraceCalculation | None = None) -> TraceBundle:
    return create_bundle(
        input_sha256=fingerprint_payload({"input": 1}, omit_keys=()),
        result_sha256=fingerprint_payload({"result": 6}, omit_keys=()),
        calculations=(calculation or _simple_calculation(),),
    )


def _reseal(payload: dict) -> dict:
    model = TraceBundle.from_dict(payload)
    return seal_bundle(model).to_dict()


def test_schema_carries_roles_units_sources_equations_and_order():
    bundle = _bundle()
    model = validate_bundle(bundle)
    calculation = model.calculations[0]

    assert [step.step_id for step in calculation.steps] == [
        "entered",
        "factor",
        "result",
    ]
    assert calculation.steps[-1].dependency_ids == ("entered", "factor")
    assert calculation.steps[0].quantity_role == ROLE_USER_INPUT
    assert calculation.steps[1].quantity_role == ROLE_METHOD_VALUE
    assert calculation.steps[-1].quantity_role == ROLE_FINAL
    assert calculation.steps[-1].unit == "kN"
    assert calculation.steps[-1].source_citation == SOURCE
    assert calculation.steps[-1].symbolic_expression == "R = k x"
    assert calculation.steps[-1].substituted_expression == "R = 3 x 2 = 6 kN"

    views = presentation.calculation_presentations(model)
    assert views[0].steps[-1].value_text == "6 kN"
    assert views[0].steps[-1].dependency_text == "entered, factor"
    assert "Formula (T.1)" in views[0].steps[-1].source_text


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda data: data["calculations"][0]["steps"][2].update(
                dependency_ids=["missing", "factor"],
                evaluation={
                    **data["calculations"][0]["steps"][2]["evaluation"],
                    "operand_ids": ["missing", "factor"],
                },
            ),
            "missing or forward dependency",
        ),
        (
            lambda data: data["calculations"][0]["steps"][2].update(
                dependency_ids=["entered", "entered"],
                evaluation={
                    **data["calculations"][0]["steps"][2]["evaluation"],
                    "operand_ids": ["entered", "entered"],
                },
            ),
            "duplicate dependency",
        ),
        (
            lambda data: data["calculations"][0]["steps"][2].update(
                unit="m",
            ),
            "evaluation unit",
        ),
        (
            lambda data: data["calculations"][0]["steps"][2].update(
                evaluated_value=7.0,
            ),
            "does not match dependency reconstruction",
        ),
        (
            lambda data: data["calculations"][0]["steps"][0].update(
                evaluated_value=True,
            ),
            "non-Boolean number",
        ),
        (
            lambda data: data["calculations"][0]["steps"][0].update(
                evaluated_value=math.inf,
            ),
            "must be finite",
        ),
    ],
)
def test_adversarial_graph_unit_value_and_scalar_tampering(mutator, message):
    payload = _bundle().to_dict()
    mutator(payload)
    payload = _reseal(payload)
    with pytest.raises(TraceValidationError, match=message):
        validate_bundle(payload)


def test_duplicate_step_id_and_duplicate_calculation_id_are_rejected():
    payload = _bundle().to_dict()
    payload["calculations"][0]["steps"][1]["step_id"] = "entered"
    payload = _reseal(payload)
    with pytest.raises(TraceValidationError, match="duplicate step ID"):
        validate_bundle(payload)

    model = _bundle()
    duplicate = dataclasses.replace(
        model,
        calculations=(model.calculations[0], model.calculations[0]),
        content_sha256="",
    )
    duplicate = seal_bundle(duplicate)
    with pytest.raises(TraceValidationError, match="duplicate calculation ID"):
        validate_bundle(duplicate)


def _sealed_builder_bundle(
    calculations: list[TraceCalculation],
) -> TraceBundle:
    return create_bundle(
        input_sha256=fingerprint_payload({"input": 1}, omit_keys=()),
        result_sha256=fingerprint_payload({"result": 1}, omit_keys=()),
        calculations=tuple(calculations),
    )


def test_completed_minimum_reinforcement_failures_have_finite_traces():
    empty_section = Section.from_polygon(
        [(-0.30, -0.30), (0.30, -0.30), (0.30, 0.30), (-0.30, 0.30)],
        [],
    )
    missing_face = {
        "minimum_reinforcement": detailing.minimum_reinforcement_2005(
            empty_section,
            [],
            [],
            fctm_mpa=2.9,
            n_ed_tension_kn=0.0,
            mx_ed_knm=100.0,
            my_ed_knm=0.0,
        )
    }
    calculations = trace_builders.minimum_reinforcement_calculations(
        {},
        missing_face,
        context={"family": "direct", "case_id": "direct"},
    )
    model = validate_bundle(_sealed_builder_bundle(calculations))
    calculation = model.calculations[0]
    steps = {step.step_id: step for step in calculation.steps}
    final = steps[calculation.final_step_id]

    assert calculation.coverage_id == "CT-017"
    assert final.step_id == "finite-formula-result-available"
    assert final.evaluated_value == 0.0
    assert all(
        math.isfinite(step.evaluated_value)
        for step in calculation.steps
    )
    assert steps["selected-formula"].source_citation is not None
    assert steps["selected-formula"].source_citation.clause == "9.2.1.1(1)"
    assert "no finite numerical result" in " ".join(
        calculation.warnings
    )

    pure_tension = {
        "minimum_reinforcement": detailing.minimum_reinforcement_2023(
            empty_section,
            [],
            [],
            Concrete(30.0, gamma_c=1.5),
            fctm_mpa=2.9,
            n_ed_tension_kn=100.0,
            mx_ed_knm=0.0,
            my_ed_knm=0.0,
        )
    }
    calculation = trace_builders.minimum_reinforcement_calculations(
        {},
        pure_tension,
        context={"family": "direct", "case_id": "direct"},
    )[0]
    steps = {step.step_id: step for step in calculation.steps}
    final = steps[calculation.final_step_id]
    demand_value = pure_tension["minimum_reinforcement"]["checks"][0][
        "demand_kn"
    ]
    assert calculation.coverage_id == "CT-018"
    assert final.evaluated_value == pytest.approx(-demand_value)
    assert final.dependency_ids == (
        "nominal-steel-force",
        "cracking-force",
    )
    assert final.evaluated_value == pytest.approx(
        steps[final.dependency_ids[0]].evaluated_value
        - steps[final.dependency_ids[1]].evaluated_value
    )

    axial_infeasible = {
        "minimum_reinforcement": {
            "status": "FAIL",
            "edition": "DS/EN 1992-1-1:2023",
            "clause": "12.2(2)(a), Formula (12.1)",
            "n_ed_tension_kn": 1000.0,
            "checks": [{
                "type": "bending with axial force",
                "status": "FAIL",
                "utilisation": None,
                "axial_feasible": False,
                "nominal_axial_resistance_kn": 982.0,
                "reason": (
                    "nominal reinforcement tension resistance is below "
                    "NEd,min"
                ),
            }],
            "limitations": (),
        }
    }
    calculation = trace_builders.minimum_reinforcement_calculations(
        {},
        axial_infeasible,
        context={"family": "direct", "case_id": "direct"},
    )[0]
    steps = {step.step_id: step for step in calculation.steps}
    final = steps[calculation.final_step_id]
    assert final.step_id == "axial-resistance-margin"
    assert final.evaluated_value == pytest.approx(-18.0)
    assert final.evaluated_value == pytest.approx(
        steps["nominal-axial-resistance"].evaluated_value
        - steps["n-ed-min"].evaluated_value
    )


def test_completed_transverse_failures_have_finite_exact_clause_traces():
    required_links = {
        "transverse_reinforcement": detailing.transverse_reinforcement(
            edition=detailing.EC2_2005_DKNA,
            member_type=detailing.MEMBER_SLAB,
            fck_mpa=30.0,
            fywk_mpa=500.0,
            diameter_mm=10.0,
            spacing_mm=150.0,
            shear_directions=[{
                "component": "vx",
                "links_present": False,
                "links_required": True,
                "requirement_clause": "6.2.2",
            }],
        )
    }
    calculation = trace_builders.transverse_detailing_calculations(
        {},
        required_links,
        context={"family": "direct", "case_id": "direct"},
    )[0]
    model = validate_bundle(_sealed_builder_bundle([calculation]))
    calculation = model.calculations[0]
    steps = {step.step_id: step for step in calculation.steps}
    final = steps[calculation.final_step_id]

    assert calculation.coverage_id == "CT-019"
    assert steps["required-link-state"].source_citation.clause == "6.2.2"
    assert final.evaluated_value == -1.0
    assert final.evaluated_value == pytest.approx(
        steps["provided-link-state"].evaluated_value
        - steps["required-link-state"].evaluated_value
    )
    assert math.isfinite(final.evaluated_value)

    coefficient = 0.08
    required_ratio = coefficient * math.sqrt(30.0) / 500.0
    zero_ratio = {
        "transverse_reinforcement": {
            "status": "FAIL",
            "edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
            "fywk_mpa": 500.0,
            "checks": [{
                "kind": "minimum_ratio",
                "scope": "Shear VX",
                "status": "FAIL",
                "provided": 0.0,
                "limit": required_ratio,
                "utilisation": math.inf,
                "criterion": "provided ratio >= minimum ratio",
                "clause": "9.2.2(5), Formulae (9.4)-(9.5)",
            }],
            "minimum_ratio": {
                "coefficient": coefficient,
                "ductility_factor": 1.0,
            },
            "limitations": (),
        }
    }
    calculation = trace_builders.transverse_detailing_calculations(
        {"concrete": Concrete(30.0, gamma_c=1.5)},
        zero_ratio,
        context={"family": "direct", "case_id": "direct"},
    )[0]
    model = validate_bundle(_sealed_builder_bundle([calculation]))
    calculation = model.calculations[0]
    steps = {step.step_id: step for step in calculation.steps}
    final = steps[calculation.final_step_id]
    assert final.evaluated_value == pytest.approx(-required_ratio)
    assert final.evaluated_value == pytest.approx(
        steps["provided-ratio"].evaluated_value
        - steps["required-ratio"].evaluated_value
    )


def test_completed_family_coverage_cannot_be_masked_by_unrelated_trace():
    unrelated = _simple_calculation()
    result = {
        "minimum_reinforcement": {
            "status": "FAIL",
            "checks": [
                {"status": "FAIL"},
                {"status": "PASS"},
            ],
        }
    }
    one_check = dataclasses.replace(
        unrelated,
        calculation_id="minimum.check-1",
        coverage_id="CT-017",
        context=(("check", "1"),),
    )

    with pytest.raises(
        TraceValidationError,
        match="unregistered trace coverage|trace registry is incomplete",
    ):
        analysis_trace._require_case_trace_coverage(
            {},
            result,
            [unrelated],
        )
    with pytest.raises(
        TraceValidationError,
        match="trace registry is incomplete",
    ):
        analysis_trace._require_case_trace_coverage(
            {},
            result,
            [one_check],
        )


def test_exact_label_identity_token_is_injective_and_id_safe():
    assert trace_identity_token("A+B") == "u412b42"
    assert trace_identity_token("A B") == "u412042"
    assert trace_identity_token("A+B") != trace_identity_token("A B")
    assert trace_identity_token("\N{LATIN CAPITAL LETTER A WITH RING ABOVE}") == (
        "uc385"
    )


def test_fatigue_spectrum_and_element_labels_have_injective_ids():
    n_star = 1.0e6
    delta_rd = 180.0
    stress = 100.0
    exponent = 5.0
    cycles = 1.0e5
    log_life = math.log10(n_star) + exponent * math.log10(
        delta_rd / stress
    )
    damage = 10.0 ** (math.log10(cycles) - log_life)

    def reinforcement(element_id):
        return {
            "element_id": element_id,
            "detail_id": "D1",
            "damage": damage,
            "yield_utilisation": 0.01,
            "utilisation": 0.01,
            "bins": (
                {
                    "bin_name": "B1",
                    "design_stress_range_mpa": stress,
                    "cycles": cycles,
                    "sn_exponent": exponent,
                    "delta_sigma_rd_mpa": delta_rd,
                    "log10_cycles_to_failure": log_life,
                    "damage": damage,
                },
            ),
        }

    element_ids = ("R+1", "R 1")
    payload = {
        "edition": "DS/EN 1992-1-1:2005",
        "partial_factors": {"gamma_s": 1.0},
        "fatigue_detail_basis": ({"id": "D1", "custom": False},),
        "reinforcement_properties": tuple(
            {
                "element_id": element_id,
                "n_star": n_star,
                "delta_sigma_rsk_mpa": delta_rd,
            }
            for element_id in element_ids
        ),
        "spectra": tuple(
            {
                "spectrum_name": spectrum_name,
                "reinforcement": tuple(
                    reinforcement(element_id)
                    for element_id in element_ids
                ),
                "concrete": (),
            }
            for spectrum_name in ("Traffic+A", "Traffic A")
        ),
    }
    out = {"fatigue": payload}
    calculations = trace_builders.fatigue_calculations(
        {},
        out,
        context={"family": "fatigue", "case_id": "global"},
    )
    bundle = create_bundle(
        input_sha256=fingerprint_payload({}, omit_keys=()),
        result_sha256=fingerprint_payload(out, omit_keys=()),
        calculations=tuple(calculations),
    )

    calculation_ids = [
        calculation.calculation_id for calculation in bundle.calculations
    ]
    assert len(calculation_ids) == 4
    assert len(calculation_ids) == len(set(calculation_ids))
    assert {
        dict(calculation.context)["spectrum"]
        for calculation in bundle.calculations
    } == {"Traffic+A", "Traffic A"}
    assert {
        dict(calculation.context)["element"]
        for calculation in bundle.calculations
    } == set(element_ids)


def test_content_seal_and_exact_input_result_freshness_fail_closed():
    bundle = _bundle()
    payload = bundle.to_dict()
    payload["calculations"][0]["steps"][2]["substituted_expression"] = "tampered"
    with pytest.raises(TraceValidationError, match="content seal"):
        validate_bundle(payload)

    with pytest.raises(TraceValidationError, match="current input signature"):
        validate_bundle(bundle, expected_input_sha256="0" * 64)
    with pytest.raises(TraceValidationError, match="solver result payload"):
        validate_bundle(bundle, expected_result_sha256="f" * 64)


def test_resealed_tampered_intermediate_is_rejected_by_arithmetic_proof():
    payload = reference_bundle().to_dict()
    target = next(
        step
        for calculation in payload["calculations"]
        for step in calculation["steps"]
        if step["quantity_role"] == "computed_intermediate"
        and step["evaluation"]["operator"] not in {"input", "method", "solver"}
    )
    target["evaluated_value"] = float(target["evaluated_value"]) + 1.0
    payload = _reseal(payload)

    with pytest.raises(
        TraceValidationError,
        match="does not match dependency reconstruction",
    ):
        validate_bundle(payload)


def test_user_defined_method_cannot_receive_an_invented_standard_citation():
    calculation = _simple_calculation()
    hostile = dataclasses.replace(
        calculation,
        method_id="custom-method",
        method_label="User-defined method",
        standard_based=False,
        user_defined_method=True,
        steps=tuple(
            dataclasses.replace(
                step,
                provenance=(
                    PROVENANCE_PROJECT
                    if step.provenance == PROVENANCE_STANDARD
                    else step.provenance
                ),
            )
            for step in calculation.steps
        ),
    )
    with pytest.raises(
        TraceValidationError,
        match="user-defined methods cannot carry standards citations",
    ):
        _bundle(hostile)


def test_malformed_serialised_context_is_rejected_as_trace_validation_error():
    payload = _bundle().to_dict()
    payload["calculations"][0]["context"] = [["only-one-item"]]
    with pytest.raises(TraceValidationError, match="malformed"):
        validate_bundle(payload)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda data: data.update(unrecognised_bundle_field=True),
        lambda data: data["calculations"][0].update(
            unrecognised_calculation_field=True
        ),
        lambda data: data["calculations"][0]["steps"][0].update(
            unrecognised_step_field=True
        ),
        lambda data: data["calculations"][0]["steps"][0]["evaluation"].update(
            unrecognised_evaluation_field=True
        ),
        lambda data: data["calculations"][0]["steps"][1][
            "source_citation"
        ].update(unrecognised_citation_field=True),
    ],
)
def test_unknown_serialised_fields_are_rejected_even_with_the_original_seal(
    mutator,
):
    payload = _bundle().to_dict()
    mutator(payload)

    with pytest.raises(TraceValidationError, match="unexpected"):
        validate_bundle(payload)


def test_serialised_collections_must_retain_the_current_json_shape():
    payload = _bundle().to_dict()
    payload["calculations"][0]["steps"][0]["warnings"] = "not-a-list"

    with pytest.raises(TraceValidationError, match="JSON list"):
        validate_bundle(payload)


def test_resealed_dimensionally_incompatible_units_are_rejected():
    payload = _bundle().to_dict()
    result = payload["calculations"][0]["steps"][2]
    result["unit"] = "m"
    result["evaluation"]["result_unit"] = "m"
    payload = _reseal(payload)

    with pytest.raises(TraceValidationError, match="dimensionally incompatible"):
        validate_bundle(payload)


def test_result_fingerprint_preserves_legitimate_infinite_solver_outputs():
    digest = fingerprint_payload(
        {"zero_demand_life": math.inf, "negative": -math.inf},
        omit_keys=(),
    )
    assert len(digest) == 64
    assert digest == fingerprint_payload(
        {"negative": -math.inf, "zero_demand_life": math.inf},
        omit_keys=(),
    )


def test_bridge_traces_reconstruct_method_b_box_wall_and_minimum_crack():
    method_b = bridge.calculate_brittle_method_b(
        [
            bridge.PrestressBrittleRegion(
                "bottom",
                m_rep_knm=1000.0,
                z_s_m=0.8,
                f_yk_mpa=500.0,
                as_provided_mm2=3000.0,
            )
        ],
        selected_standard=bridge.EN1992_2_DK_NA,
    )
    walls = bridge.calculate_box_walls(
        [
            bridge.BoxWall(
                "left",
                cot_theta=0.5,
                v_ed_kn=200.0,
                v_rd_max_kn=500.0,
                t_ed_equivalent_kn=50.0,
                t_rd_max_equivalent_kn=250.0,
            )
        ]
    )
    crack = bridge.calculate_minimum_crack_reinforcement(
        [
            bridge.MinimumCrackComponent(
                "web",
                act_mm2=100_000.0,
                k_c=0.4,
                k=0.8,
                fct_eff_mpa=2.5,
                sigma_s_mpa=200.0,
                as_provided_mm2=600.0,
                restrained_shrinkage=True,
            )
        ]
    )
    out = {
        "bridge": {
            "calculations": {
                "brittle_method_b": method_b,
                "box_walls": walls,
                "minimum_crack_reinforcement": crack,
            }
        }
    }
    calculations = trace_builders.bridge_calculations(
        out,
        context={"family": "manual", "case_id": "bridge"},
    )
    model = create_bundle(
        input_sha256=fingerprint_payload("bridge-input", omit_keys=()),
        result_sha256=fingerprint_payload(out, omit_keys=()),
        calculations=calculations,
    )

    by_coverage = {item.coverage_id: item for item in model.calculations}
    assert by_coverage["CT-025"].steps[-1].evaluated_value == pytest.approx(
        (1000.0 * 1000.0 / (0.8 * 500.0)) / 3000.0
    )
    assert by_coverage["CT-026"].steps[-1].evaluated_value == pytest.approx(
        200.0 / 500.0 + 50.0 / 250.0
    )
    assert by_coverage["CT-027"].steps[-1].evaluated_value == pytest.approx(
        (0.4 * 0.8 * 2.9 * 100_000.0 / 200.0) / 600.0
    )

    cot_step = next(
        step
        for step in by_coverage["CT-026"].steps
        if step.step_id == "cot-theta"
    )
    assert cot_step.quantity_role == ROLE_USER_INPUT
    assert cot_step.evaluated_value == pytest.approx(0.5)
    assert any(
        "actual values were retained" in warning
        for warning in by_coverage["CT-026"].warnings
    )


def test_bridge_user_labels_have_injective_trace_ids():
    labels = ("A+B", "A B")
    method_b = bridge.calculate_brittle_method_b(
        [
            bridge.PrestressBrittleRegion(
                label,
                m_rep_knm=1000.0,
                z_s_m=0.8,
                f_yk_mpa=500.0,
                as_provided_mm2=3000.0,
            )
            for label in labels
        ],
        selected_standard=bridge.EN1992_2_DK_NA,
    )
    walls = bridge.calculate_box_walls(
        [
            bridge.BoxWall(
                label,
                cot_theta=1.5,
                v_ed_kn=200.0,
                v_rd_max_kn=500.0,
                t_ed_equivalent_kn=50.0,
                t_rd_max_equivalent_kn=250.0,
            )
            for label in labels
        ]
    )
    crack = bridge.calculate_minimum_crack_reinforcement(
        [
            bridge.MinimumCrackComponent(
                "web",
                act_mm2=100_000.0,
                k_c=0.4,
                k=0.8,
                fct_eff_mpa=2.5,
                sigma_s_mpa=200.0,
                as_provided_mm2=600.0,
                restrained_shrinkage=True,
            )
        ]
    )
    out = {
        "bridge": {
            "calculations": {
                "brittle_method_b": method_b,
                "box_walls": walls,
                "minimum_crack_reinforcement": crack,
            }
        }
    }
    calculations = trace_builders.bridge_calculations(
        out,
        context={"family": "test", "case_id": "label-identity"},
    )
    bundle = create_bundle(
        input_sha256=fingerprint_payload("bridge-labels", omit_keys=()),
        result_sha256=fingerprint_payload(out, omit_keys=()),
        calculations=calculations,
    )

    assert len(bundle.calculations) == 5
    assert len({item.calculation_id for item in bundle.calculations}) == 5
    for coverage_id in ("CT-025", "CT-026"):
        records = [
            calculation
            for calculation in bundle.calculations
            if calculation.coverage_id == coverage_id
        ]
        assert {
            dict(calculation.context)["component"]
            for calculation in records
        } == set(labels)
    crack_trace = next(
        calculation
        for calculation in bundle.calculations
        if calculation.coverage_id == "CT-027"
    )
    assert dict(crack_trace.context)["component"] == "web"


@pytest.mark.parametrize("value", [True, math.inf, math.nan])
def test_trace_builder_rejects_boolean_or_nonfinite_custom_values(value):
    result = {
        "rows": [
            {
                "wall_id": "W1",
                "cot_theta": value,
                "v_ed_kn": 1.0,
                "v_rd_max_kn": 2.0,
                "t_ed_equivalent_kn": 1.0,
                "t_rd_max_equivalent_kn": 2.0,
                "utilisation": 1.0,
            }
        ],
        "warnings": [],
    }
    with pytest.raises(ValueError, match="non-Boolean finite|finite"):
        trace_builders.bridge_calculations(
            {"bridge": {"calculations": {"box_walls": result}}},
            context={"family": "test", "case_id": "hostile"},
        )
