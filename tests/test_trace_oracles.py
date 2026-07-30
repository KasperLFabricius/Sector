"""Independent PI-019 dependency oracles and manual reuse checks."""

from __future__ import annotations

import io
import math
import pathlib
import sys

import pytest
from pypdf import PdfReader

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tests"))

import calculation_trace_presentation as presentation
import manual
import test_elastic
import test_plastic_handcalc
from sector import codes, trace_builders
from sector.calculation_trace import (
    PROVENANCE_INPUT,
    PROVENANCE_STANDARD,
    ROLE_FINAL,
    ROLE_USER_INPUT,
    create_bundle,
    fingerprint_payload,
    validate_bundle,
)
from sector.elastic import solve_elastic
from sector.materials import Concrete, MildSteel, Prestress
from sector.plastic import plastic_capacity_at_angle, solve_interaction
from sector.section import Section
from sector.trace_examples import reference_bundle


EXPECTED_COVERAGE = frozenset(f"CT-{index:03d}" for index in range(1, 28))


def _independent_arithmetic(step, values):
    """Evaluate one trace operation without using the production evaluator."""

    evaluation = step.evaluation
    operator = evaluation.operator
    if operator in {"input", "method", "solver"}:
        return None
    operands = [values[item] for item in evaluation.operand_ids]
    if operator == "identity":
        raw = operands[0]
    elif operator in {"add", "sum"}:
        raw = sum(operands)
    elif operator == "subtract":
        raw = operands[0] - operands[1]
    elif operator in {"multiply", "product"}:
        raw = math.prod(operands)
    elif operator == "divide":
        raw = operands[0] / operands[1]
    elif operator == "power":
        raw = operands[0] ** float(evaluation.exponent)
    elif operator == "pow10":
        raw = 10.0 ** operands[0]
    elif operator == "log10":
        raw = math.log10(operands[0])
    elif operator == "sqrt":
        raw = math.sqrt(operands[0])
    elif operator == "cbrt":
        raw = math.copysign(
            abs(operands[0]) ** (1.0 / 3.0),
            operands[0],
        )
    elif operator == "min":
        raw = min(operands)
    elif operator == "max":
        raw = max(operands)
    elif operator == "abs":
        raw = abs(operands[0])
    elif operator == "hypot":
        raw = math.hypot(*operands)
    elif operator == "negate":
        raw = -operands[0]
    else:  # pragma: no cover - a new operator must add an independent oracle
        raise AssertionError(f"unhandled trace operator {operator!r}")
    return raw * evaluation.factor + evaluation.offset


def _steps(calculation):
    return {step.step_id: step for step in calculation.steps}


def _representative(bundle, coverage_id, *, method_id=None):
    matches = [
        item
        for item in bundle.calculations
        if item.coverage_id == coverage_id
        and (method_id is None or item.method_id == method_id)
    ]
    assert matches, (coverage_id, method_id)
    return max(
        matches,
        key=lambda item: abs(
            next(
                step.evaluated_value
                for step in item.steps
                if step.step_id == item.final_step_id
            )
        ),
    )


def test_reference_bundle_covers_every_retained_family_and_method_variant():
    bundle = validate_bundle(reference_bundle())
    assert {item.coverage_id for item in bundle.calculations} == EXPECTED_COVERAGE

    methods = {
        (item.coverage_id, item.method_id)
        for item in bundle.calculations
    }
    required_methods = {
        ("CT-001", "ec2-2005"),
        ("CT-001", "ec2-2005-dkna2024"),
        ("CT-001", "ec2-2023"),
        ("CT-001", "user-defined-concrete"),
        ("CT-001", "user-defined-reinforcement"),
        ("CT-002", "ec2-2005"),
        ("CT-002", "ec2-2005-dkna2024"),
        ("CT-002", "ec2-2023"),
        ("CT-002", "mixed-standard-project-material-section-solve"),
        ("CT-002", "user-defined-material-section-solve"),
        ("CT-004", "ec2-2005"),
        ("CT-004", "ec2-2005-dkna2024"),
        ("CT-004", "ec2-2023"),
        ("CT-004", "mixed-standard-project-material-section-solve"),
        ("CT-004", "user-defined-material-section-solve"),
        ("CT-005", "sector-fixed-prestress-decompression"),
        ("CT-005", "sector-linear-elastic-scaling"),
        ("CT-005", "sector-transformed-section-equilibrium"),
        ("CT-006", "ec2-2005"),
        ("CT-007", "ec2-2005-dkna-fine"),
        ("CT-007", "ec2-2005-dkna-coarse"),
        ("CT-008", "ec2-2023-bending"),
        ("CT-008", "ec2-2023-direct-tension"),
        ("CT-009", "ec2-2005"),
        ("CT-009", "ec2-2005-dkna"),
        ("CT-010", "ec2-2023"),
        ("CT-011", "ec2-2005"),
        ("CT-011", "ec2-2005-dkna"),
        ("CT-012", "ec2-2023"),
        ("CT-013", "ec2-2005"),
        ("CT-013", "ec2-2005-dkna"),
        ("CT-019", "ec2-2005-transverse"),
        ("CT-019", "ec2-2023-transverse"),
        ("CT-020", "ec2-2005-clear-spacing"),
        ("CT-020", "ec2-2023-clear-spacing"),
        ("CT-021", "ec2-2005-reinforcement-sn"),
        ("CT-021", "ec2-2023-reinforcement-sn"),
        ("CT-022", "ec2-2005-equivalent"),
        ("CT-023", "ec2-bridge-corrected-miner"),
        ("CT-024", "ec2-2023-equivalent"),
        ("CT-024", "ec2-2023-miner"),
    }
    assert required_methods <= methods

    for calculation in bundle.calculations:
        assert calculation.steps
        assert sum(
            step.quantity_role == ROLE_FINAL
            for step in calculation.steps
        ) == 1
        if calculation.user_defined_method:
            assert not calculation.standard_based
            assert all(
                step.source_citation is None for step in calculation.steps
            )
        for step in calculation.steps:
            assert step.title.strip()
            assert step.symbol.strip()
            assert step.unit.strip()
            assert step.symbolic_expression.strip()
            assert step.substituted_expression.strip()
            if step.provenance == PROVENANCE_STANDARD:
                assert step.source_citation is not None
                assert step.source_citation.document.strip()
                assert step.source_citation.clause.strip()
                assert step.source_citation.locator.strip()
            if step.quantity_role == ROLE_USER_INPUT:
                assert step.provenance == PROVENANCE_INPUT
                assert step.source_citation is None


def test_manual_examples_include_tendon_capacity_and_elastic_dependency_chains():
    bundle = reference_bundle()
    tendon_sources = {
        "ec2-2005": (
            trace_builders.CIT_TENDON_PROOF_2005,
            trace_builders.CIT_TENDON_RUPTURE_2005,
            trace_builders.CIT_TENDON_MODULUS_2005,
        ),
        "ec2-2023": (
            trace_builders.CIT_TENDON_PROOF_2023,
            trace_builders.CIT_TENDON_RUPTURE_2023,
            trace_builders.CIT_TENDON_MODULUS_2023,
        ),
    }
    for method_id, expected in tendon_sources.items():
        capacity = _representative(
            bundle,
            "CT-002",
            method_id=method_id,
        )
        steps = _steps(capacity)
        assert (
            steps["tendon-001-fpd"].source_citation,
            steps["tendon-001-fpud"].source_citation,
            steps["tendon-001-design-slope"].source_citation,
        ) == expected

    fixed = _representative(
        bundle,
        "CT-005",
        method_id="sector-fixed-prestress-decompression",
    )
    fixed_steps = _steps(fixed)
    assignment = "elastic-tendon-assignment-001"
    assert assignment in fixed_steps["sigma-pre"].dependency_ids
    assert assignment in fixed_steps["sigma-ext"].dependency_ids
    assert fixed_steps[
        "elastic-tendon-001-locked-prestress"
    ].dependency_ids == (
        "elastic-tendon-001-es",
        "elastic-tendon-001-initial-strain",
    )


def test_manual_section_solver_examples_publish_complete_geometry_chains():
    bundle = reference_bundle()
    affected = [
        calculation
        for calculation in bundle.calculations
        if calculation.coverage_id in {"CT-002", "CT-004", "CT-005"}
    ]
    assert len(affected) == 13

    for calculation in affected:
        steps = _steps(calculation)
        geometry = steps["section-geometry"]
        geometry_leaves = geometry.dependency_ids
        assert geometry_leaves
        assert all(step_id.startswith("geometry-") for step_id in geometry_leaves)
        assert all(
            steps[step_id].quantity_role == ROLE_USER_INPUT
            for step_id in geometry_leaves
        )
        assert all(
            steps[step_id].unit in {"m", "mm2"}
            for step_id in geometry_leaves
        )

        reachable = set()
        pending = [calculation.final_step_id]
        while pending:
            step_id = pending.pop()
            if step_id in reachable:
                continue
            reachable.add(step_id)
            pending.extend(steps[step_id].dependency_ids)
        assert "section-geometry" in reachable
        assert set(geometry_leaves) <= reachable


def test_independent_oracle_reconstructs_every_dependency_and_arithmetic_step():
    bundle = reference_bundle()
    reconstructed = 0
    visited = 0
    for calculation in bundle.calculations:
        values = {}
        for step in calculation.steps:
            visited += 1
            assert tuple(step.dependency_ids) == tuple(
                step.evaluation.operand_ids
            )
            assert all(item in values for item in step.dependency_ids)
            expected = _independent_arithmetic(step, values)
            if expected is not None:
                reconstructed += 1
                assert math.isclose(
                    expected,
                    step.evaluated_value,
                    rel_tol=step.evaluation.relative_tolerance,
                    abs_tol=step.evaluation.absolute_tolerance,
                ), (
                    calculation.calculation_id,
                    step.step_id,
                    expected,
                    step.evaluated_value,
                )
            values[step.step_id] = step.evaluated_value
        assert calculation.final_step_id in values

    assert visited > 400
    assert reconstructed > 250


def test_repeated_element_assignments_share_one_complete_material_law_record():
    calculation = _representative(
        reference_bundle(),
        "CT-002",
        method_id="ec2-2005-dkna2024",
    )
    steps = _steps(calculation)
    assignments = [
        step
        for step in calculation.steps
        if step.step_id.startswith("bar-assignment-")
    ]
    laws = [
        step
        for step in calculation.steps
        if step.step_id.startswith("bar-") and step.step_id.endswith("-law")
    ]
    assert len(assignments) > 1
    assert len(laws) == 1
    assert all(step.dependency_ids == (laws[0].step_id,) for step in assignments)


@pytest.mark.parametrize(
    "coverage_id",
    [
        "CT-001",
        "CT-002",
        "CT-005",
        "CT-006",
        "CT-007",
        "CT-008",
        "CT-009",
        "CT-010",
        "CT-011",
        "CT-012",
        "CT-013",
        "CT-021",
        "CT-022",
        "CT-023",
        "CT-024",
        "CT-025",
        "CT-026",
        "CT-027",
    ],
)
def test_representative_governing_result_is_finite_and_nonzero(coverage_id):
    calculation = _representative(reference_bundle(), coverage_id)
    final = _steps(calculation)[calculation.final_step_id]
    assert math.isfinite(final.evaluated_value)
    assert abs(final.evaluated_value) > 0.0


def test_material_crack_fatigue_and_bridge_formula_anchors():
    bundle = reference_bundle()

    material = _representative(
        bundle,
        "CT-001",
        method_id="ec2-2005-dkna2024",
    )
    steps = _steps(material)
    if "fcd" in steps:
        assert steps["fcd"].evaluated_value == pytest.approx(
            steps["strength-factor"].evaluated_value
            * steps["fck"].evaluated_value
            / steps["gamma-c"].evaluated_value
        )
    else:
        assert steps["fyd"].evaluated_value == pytest.approx(
            steps["fyk"].evaluated_value
            / steps["gamma-s"].evaluated_value
        )

    for coverage in ("CT-006", "CT-007", "CT-008"):
        crack = _representative(bundle, coverage)
        final = _steps(crack)[crack.final_step_id]
        expected = _independent_arithmetic(
            final,
            {step.step_id: step.evaluated_value for step in crack.steps},
        )
        assert final.evaluated_value == pytest.approx(expected)

    for coverage in ("CT-022", "CT-023", "CT-024"):
        fatigue = _representative(bundle, coverage)
        steps = _steps(fatigue)
        assert steps["fcd-fat"].evaluated_value == pytest.approx(
            steps["fcd-fat-numerator"].evaluated_value
            / steps["gamma-c"].evaluated_value
        )
        final = steps[fatigue.final_step_id]
        assert final.evaluated_value == pytest.approx(
            _independent_arithmetic(
                final,
                {step.step_id: step.evaluated_value for step in fatigue.steps},
            )
        )

    bridge_method = _representative(bundle, "CT-025")
    bridge_wall = _representative(bundle, "CT-026")
    bridge_crack = _representative(bundle, "CT-027")
    assert _steps(bridge_method)[bridge_method.final_step_id].evaluated_value == (
        pytest.approx((1000.0 * 1000.0 / (0.8 * 500.0)) / 3000.0)
    )
    assert _steps(bridge_wall)[bridge_wall.final_step_id].evaluated_value == (
        pytest.approx(200.0 / 500.0 + 50.0 / 250.0)
    )
    assert _steps(bridge_crack)[bridge_crack.final_step_id].evaluated_value == (
        pytest.approx(
            (0.4 * 0.8 * 2.9 * 100_000.0 / 200.0) / 600.0
        )
    )


def test_reinforcement_trace_uses_actual_steel_preset_not_concrete_preset():
    concrete = Concrete(fck=35.0, gamma_c=1.5, curve=2)
    steel = MildSteel(
        fytk=610.0,
        fyck=590.0,
        futk=650.0,
        eut=0.045,
        gamma_y=1.07,
        gamma_u=1.09,
        gamma_E=1.03,
        curve=3,
    )
    common = {
        "concrete": concrete,
        "steel": steel,
        "concrete_preset": codes.EC2_2023.label,
    }

    custom = trace_builders.material_calculations(
        {**common, "mild_preset": "Custom / imported"},
    )[1]
    assert custom.user_defined_method
    assert not custom.standard_based
    assert all(step.source_citation is None for step in custom.steps)

    standard = trace_builders.material_calculations(
        {**common, "mild_preset": codes.EC2_2005.label},
    )[1]
    assert standard.method_id == "ec2-2005"
    assert _steps(standard)["fyd"].source_citation.document == (
        trace_builders.DOC_2005
    )

    catalog_custom = trace_builders.material_calculations(
        {
            **common,
            "mild_preset": codes.EC2_2005.label,
            "capacity_steel_material_id": "M2",
            "mild_material_catalog": {
                "items": [
                    {"id": "M1", "preset": codes.EC2_2005.label},
                    {"id": "M2", "preset": "Custom / imported"},
                ]
            },
        },
    )[1]
    assert catalog_custom.user_defined_method
    assert all(step.source_citation is None for step in catalog_custom.steps)


def test_plastic_trace_depends_on_every_assigned_bar_and_tendon_law():
    section = Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        holes=[
            [(0.13, 0.25), (0.17, 0.25), (0.17, 0.35), (0.13, 0.35)]
        ],
        bars_xy_area_mm2=[
            (0.08, 0.05, 700.0),
            (0.22, 0.55, 700.0),
        ],
        tendons_xy_area_mm2=[(0.15, 0.08, 500.0)],
    )
    concrete = Concrete(
        fck=35.0,
        gamma_c=1.45,
        curve=2,
        alpha_cc=0.92,
        eps_c2=0.0021,
        eps_cu2=0.0034,
        n=2.1,
    )
    standard_bar = MildSteel(
        fytk=500.0,
        fyck=500.0,
        futk=500.0,
        eut=0.05,
        gamma_y=1.15,
        gamma_u=1.15,
        gamma_E=1.0,
        curve=3,
    )
    custom_bar = MildSteel(
        fytk=620.0,
        fyck=430.0,
        futk=680.0,
        eut=0.032,
        gamma_y=1.08,
        gamma_u=1.12,
        gamma_E=1.04,
        curve=3,
        k=0.86,
        ey0t=0.0015,
        ey0c=0.0012,
        Es=205_000.0,
        active_in_compression=False,
    )
    tendon = Prestress(
        curve=7,
        IS=0.0058,
        gamma_y=1.12,
        gamma_u=1.15,
        gamma_E=1.03,
        fytk=1600.0,
        eut=0.036,
        futk=1820.0,
        k=0.9,
        ey0t=0.001,
        Es=195_000.0,
    )
    point = plastic_capacity_at_angle(
        section,
        concrete,
        standard_bar,
        0.0,
        90.0,
        prestress=tendon,
        bar_materials=[standard_bar, custom_bar],
        tendon_materials=[tendon],
    )
    assert point.converged
    inp = {
        "section": section,
        "P_pl": 0.0,
        "Mx_pl": point.Mx,
        "My_pl": point.My,
        "concrete": concrete,
        "steel": standard_bar,
        "prestress": tendon,
        "concrete_preset": codes.EC2_2023.label,
        "mild_preset": codes.EC2_2005.label,
        "prestress_preset": "Custom / imported",
        "bar_materials": [standard_bar, custom_bar],
        "tendon_materials": [tendon],
        "bar_elements": [
            {"id": "B1", "material_id": "M1"},
            {"id": "B2", "material_id": "M2"},
        ],
        "tendon_elements": [{"id": "T1", "material_id": "P1"}],
        "mild_material_catalog": {
            "items": [
                {"id": "M1", "preset": codes.EC2_2005.label},
                {"id": "M2", "preset": "Custom / imported"},
            ]
        },
        "prestress_material_catalog": {
            "items": [{"id": "P1", "preset": "Custom / imported"}]
        },
    }
    out = {
        "plastic": {
            "points": [point],
            "mx": [point.Mx],
            "my": [point.My],
            "converged": True,
        }
    }
    interaction = solve_interaction(
        section,
        concrete,
        standard_bar,
        90.0,
        prestress=tendon,
        bar_materials=[standard_bar, custom_bar],
        tendon_materials=[tendon],
        n_points=4,
        n_bands=30,
    )
    assert all(item.converged for item in interaction)
    out["plastic"]["interaction"] = {
        "x": {
            "N": [-item.axial for item in interaction],
            "M": [item.Mx for item in interaction],
            "converged": True,
        }
    }
    calculations = trace_builders.plastic_calculations(
        inp,
        out,
        context={"family": "oracle", "case_id": "heterogeneous-laws"},
    )
    calculation = next(
        item for item in calculations if item.coverage_id == "CT-002"
    )
    assert calculation.method_id == "mixed-standard-project-material-section-solve"
    assert not calculation.standard_based
    assert not calculation.user_defined_method
    create_bundle(
        input_sha256=fingerprint_payload(inp, omit_keys=()),
        result_sha256=fingerprint_payload(out, omit_keys=()),
        calculations=(calculation,),
    )
    steps = _steps(calculation)
    assignment_ids = (
        "bar-assignment-001",
        "bar-assignment-002",
        "tendon-assignment-001",
    )
    assert set(assignment_ids) <= set(steps["curvature"].dependency_ids)
    assert set(assignment_ids) <= set(steps["axial-resultant"].dependency_ids)
    assert "section-geometry" in steps["curvature"].dependency_ids
    assert "section-geometry" in steps["axial-resultant"].dependency_ids
    geometry_leaf_ids = {
        step_id
        for step_id in steps
        if step_id.startswith("geometry-")
        and step_id != "section-geometry"
    }
    assert geometry_leaf_ids == set(
        steps["section-geometry"].dependency_ids
    )
    assert len(geometry_leaf_ids) == 25
    reconstructed_section = Section.from_polygon(
        corners=[
            (
                steps[f"geometry-outer-{index:03d}-x"].evaluated_value,
                steps[f"geometry-outer-{index:03d}-y"].evaluated_value,
            )
            for index in range(1, 5)
        ],
        holes=[
            [
                (
                    steps[
                        f"geometry-hole-001-{index:03d}-x"
                    ].evaluated_value,
                    steps[
                        f"geometry-hole-001-{index:03d}-y"
                    ].evaluated_value,
                )
                for index in range(1, 5)
            ]
        ],
        bars_xy_area_mm2=[
            (
                steps[f"geometry-bar-{index:03d}-x"].evaluated_value,
                steps[f"geometry-bar-{index:03d}-y"].evaluated_value,
                steps[f"geometry-bar-{index:03d}-area"].evaluated_value,
            )
            for index in range(1, 3)
        ],
        tendons_xy_area_mm2=[
            (
                steps["geometry-tendon-001-x"].evaluated_value,
                steps["geometry-tendon-001-y"].evaluated_value,
                steps["geometry-tendon-001-area"].evaluated_value,
            )
        ],
    )
    replayed = plastic_capacity_at_angle(
        reconstructed_section,
        concrete,
        standard_bar,
        0.0,
        steps["na-angle"].evaluated_value,
        prestress=tendon,
        bar_materials=[standard_bar, custom_bar],
        tendon_materials=[tendon],
    )
    assert replayed.axial == pytest.approx(
        -steps["axial-resultant"].evaluated_value
    )
    assert replayed.Mx == pytest.approx(steps["mx-rd"].evaluated_value)
    assert replayed.My == pytest.approx(steps["my-rd"].evaluated_value)
    assert steps["bar-assignment-001"].dependency_ids == ("bar-001-law",)
    assert steps["bar-assignment-002"].dependency_ids == ("bar-002-law",)
    assert steps["tendon-assignment-001"].dependency_ids == (
        "tendon-001-law",
    )
    assert "bar-001-fyd" in steps["bar-001-law"].dependency_ids
    assert "bar-002-design-slope" in steps["bar-002-law"].dependency_ids
    assert "bar-002-eut" in steps["bar-002-law"].dependency_ids
    assert "tendon-001-initial-strain" in (
        steps["tendon-001-law"].dependency_ids
    )
    assert "tendon-001-design-slope" in (
        steps["tendon-001-law"].dependency_ids
    )
    assert steps["bar-001-fyd"].source_citation.document == (
        trace_builders.DOC_2005
    )
    assert steps["bar-002-fyd"].source_citation is None
    assert all(
        steps[step_id].source_citation is None
        for step_id in steps["tendon-001-law"].dependency_ids
    )

    nm = next(item for item in calculations if item.coverage_id == "CT-004")
    create_bundle(
        input_sha256=fingerprint_payload(inp, omit_keys=()),
        result_sha256=fingerprint_payload(out, omit_keys=()),
        calculations=(nm,),
    )
    nm_steps = _steps(nm)
    assert {
        "section-geometry",
        "concrete-law",
        "bar-assignment-001",
        "bar-assignment-002",
        "tendon-assignment-001",
    } <= set(nm_steps["boundary-state"].dependency_ids)
    assert nm_steps["bar-assignment-001"].dependency_ids == ("bar-001-law",)
    assert nm_steps["bar-assignment-002"].dependency_ids == ("bar-002-law",)
    assert nm_steps["tendon-assignment-001"].dependency_ids == (
        "tendon-001-law",
    )
    assert nm_steps["n-rd"].evaluated_value == pytest.approx(
        out["plastic"]["interaction"]["x"]["N"][
            max(
                range(len(interaction)),
                key=lambda item: abs(interaction[item].Mx),
            )
        ]
    )
    assert nm_steps[nm.final_step_id].evaluated_value == pytest.approx(
        max((item.Mx for item in interaction), key=abs)
    )

    standard_tendon_inp = {
        **inp,
        "prestress_preset": codes.EC2_2023.label,
        "prestress_material_catalog": {
            "items": [{"id": "P1", "preset": codes.EC2_2023.label}]
        },
    }
    standard_tendon = next(
        item
        for item in trace_builders.plastic_calculations(
            standard_tendon_inp,
            out,
            context={
                "family": "oracle",
                "case_id": "standard-tendon-law",
            },
        )
        if item.coverage_id == "CT-002"
    )
    standard_steps = _steps(standard_tendon)
    assert standard_steps["tendon-001-fpd"].source_citation == (
        trace_builders.CIT_TENDON_PROOF_2023
    )
    assert standard_steps["tendon-001-fpud"].source_citation == (
        trace_builders.CIT_TENDON_RUPTURE_2023
    )
    assert standard_steps["tendon-001-design-slope"].source_citation == (
        trace_builders.CIT_TENDON_MODULUS_2023
    )
    standard_2005_inp = {
        **inp,
        "prestress_preset": codes.EC2_2005_DKNA.label,
        "prestress_material_catalog": {
            "items": [{"id": "P1", "preset": codes.EC2_2005_DKNA.label}]
        },
    }
    standard_2005 = next(
        item
        for item in trace_builders.plastic_calculations(
            standard_2005_inp,
            out,
            context={
                "family": "oracle",
                "case_id": "standard-tendon-law-2005",
            },
        )
        if item.coverage_id == "CT-002"
    )
    standard_2005_steps = _steps(standard_2005)
    assert standard_2005_steps["tendon-001-fpd"].source_citation == (
        trace_builders.CIT_TENDON_PROOF_2005
    )
    assert standard_2005_steps["tendon-001-fpud"].source_citation == (
        trace_builders.CIT_TENDON_RUPTURE_2005
    )
    assert standard_2005_steps[
        "tendon-001-design-slope"
    ].source_citation == trace_builders.CIT_TENDON_MODULUS_2005


def test_elastic_trace_exposes_each_modulus_ratio_and_locked_prestress():
    bar_1 = MildSteel(fytk=500.0, fyck=500.0, Es=200_000.0)
    bar_2 = MildSteel(fytk=500.0, fyck=500.0, Es=210_000.0)
    tendon = Prestress(curve=1, IS=0.005, Es=195_000.0)
    elastic_section = Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        bars_xy_area_mm2=[
            (0.08, 0.05, 700.0),
            (0.22, 0.55, 700.0),
        ],
        tendons_xy_area_mm2=[(0.15, 0.08, 500.0)],
    )
    ns = 200_000.0 / 40_000.0
    nl = ns * (1.0 + 1.2)
    inp = {
        "section": elastic_section,
        "P_el_l": -250.0,
        "Mx_el_l": 120.0,
        "My_el_l": 15.0,
        "P_el_s": 50.0,
        "Mx_el_s": 35.0,
        "My_el_s": -5.0,
        "conc_Ec": 40.0,
        "el_phi": 1.2,
        "ns": ns,
        "nl": nl,
        "steel": bar_1,
        "prestress": tendon,
        "bar_materials": [bar_1, bar_2],
        "tendon_materials": [tendon],
        "bar_elements": [
            {"id": "B1", "material_id": "M1"},
            {"id": "B2", "material_id": "M2"},
        ],
        "tendon_elements": [{"id": "T1", "material_id": "P1"}],
        "mild_material_catalog": {
            "items": [
                {"id": "M1", "preset": codes.EC2_2005.label},
                {"id": "M2", "preset": "Custom / imported"},
            ]
        },
        "prestress_material_catalog": {
            "items": [{"id": "P1", "preset": codes.EC2_2023.label}]
        },
    }
    out = {
        "elastic": {
            "max_conc": 12.0,
            "max_steel": 180.0,
            "lambda_cr": 2.0,
            "fctm": 3.2,
            "sigma_ct": 2.2,
            "cracking_threshold": {
                "method": "fixed-prestress-decompression",
                "fixed_prestress_mpa": -1.0,
                "external_tension_mpa": 2.1,
                "available_tension_mpa": 4.2,
                "raw_factor": 2.0,
                "governing_fibre_index": 1,
            },
        }
    }
    calculations = trace_builders.elastic_calculations(
        inp,
        out,
        context={"family": "oracle", "case_id": "elastic-material-laws"},
    )
    create_bundle(
        input_sha256=fingerprint_payload(inp, omit_keys=()),
        result_sha256=fingerprint_payload(out, omit_keys=()),
        calculations=tuple(calculations),
    )
    section = next(
        item
        for item in calculations
        if item.calculation_id.endswith("section-equilibrium")
    )
    section_steps = _steps(section)
    assignments = {
        "elastic-bar-assignment-001",
        "elastic-bar-assignment-002",
        "elastic-tendon-assignment-001",
    }
    assert "section-geometry" in section_steps["max-concrete"].dependency_ids
    assert "section-geometry" in (
        section_steps["max-reinforcement"].dependency_ids
    )
    assert assignments <= set(
        section_steps["max-concrete"].dependency_ids
    )
    assert assignments <= set(
        section_steps["max-reinforcement"].dependency_ids
    )
    assert section_steps[
        "elastic-bar-002-n-ratio-short"
    ].evaluated_value == pytest.approx(210_000.0 / 40_000.0)
    assert section_steps[
        "elastic-bar-002-n-ratio-long"
    ].evaluated_value == pytest.approx(
        210_000.0 * (1.0 + 1.2) / 40_000.0
    )
    assert section_steps[
        "elastic-tendon-001-n-ratio-short"
    ].evaluated_value == pytest.approx(195_000.0 / 40_000.0)
    assert section_steps[
        "elastic-tendon-001-locked-prestress"
    ].evaluated_value == pytest.approx(195_000.0 * 0.005)

    threshold = next(
        item
        for item in calculations
        if item.calculation_id.endswith("cracking-factor")
    )
    threshold_steps = _steps(threshold)
    assert "section-geometry" in threshold_steps["sigma-ext"].dependency_ids
    assert "section-geometry" in threshold_steps["sigma-pre"].dependency_ids
    assert assignments <= set(threshold_steps["sigma-ext"].dependency_ids)
    assert assignments <= set(threshold_steps["sigma-pre"].dependency_ids)
    assert (
        threshold_steps["elastic-tendon-001-locked-prestress"].dependency_ids
        == (
            "elastic-tendon-001-es",
            "elastic-tendon-001-initial-strain",
        )
    )
    assert all(
        step.source_citation is None
        for step in threshold.steps
        if step.step_id.startswith("elastic-")
    )


def test_infinite_first_cracking_result_has_a_complete_finite_state_trace():
    ratio = 200_000.0 / 34_000.0
    inp = {
        "section": Section.from_polygon(
            corners=[
                (0.0, 0.0),
                (0.3, 0.0),
                (0.3, 0.6),
                (0.0, 0.6),
            ],
        ),
        "P_el_l": 0.0,
        "Mx_el_l": 0.0,
        "My_el_l": 0.0,
        "P_el_s": 0.0,
        "Mx_el_s": 0.0,
        "My_el_s": 0.0,
        "conc_Ec": 34.0,
        "el_phi": 0.0,
        "ns": ratio,
        "nl": ratio,
        "sls_fctm": 3.2,
    }
    out = {
        "elastic": {
            "max_conc": 0.4,
            "max_steel": 0.0,
            "lambda_cr": math.inf,
            "fctm": 3.2,
            "sigma_ct": -0.15,
            "cracking_threshold": {
                "method": "proportional-external-action",
                "fctm_mpa": 3.2,
                "sigma_ct_mpa": -0.15,
                "factor": math.inf,
                "raw_factor": math.inf,
                "fixed_prestress_mpa": None,
                "external_tension_mpa": None,
                "available_tension_mpa": None,
                "governing_fibre_index": None,
            },
        }
    }
    calculations = trace_builders.elastic_calculations(
        inp,
        out,
        context={"family": "oracle", "case_id": "infinite-cracking"},
    )
    cracking = next(
        item for item in calculations if item.calculation_id.endswith("cracking-factor")
    )
    create_bundle(
        input_sha256=fingerprint_payload(inp, omit_keys=()),
        result_sha256=fingerprint_payload(out, omit_keys=()),
        calculations=(cracking,),
    )
    steps = _steps(cracking)
    assert cracking.final_step_id == "finite-factor-available"
    assert steps[cracking.final_step_id].evaluated_value == 0.0
    assert steps["positive-stage-i-tension"].evaluated_value == 0.0
    assert "infinite" in steps[cracking.final_step_id].substituted_expression
    assert any("lambda_cr is infinite" in item for item in cracking.warnings)


def test_infinite_prestress_cracking_trace_retains_fixed_and_external_leaves():
    ratio = 200_000.0 / 34_000.0
    inp = {
        "section": Section.from_polygon(
            corners=[
                (0.0, 0.0),
                (0.3, 0.0),
                (0.3, 0.6),
                (0.0, 0.6),
            ],
        ),
        "P_el_l": 0.0,
        "Mx_el_l": 0.0,
        "My_el_l": 0.0,
        "P_el_s": 0.0,
        "Mx_el_s": 0.0,
        "My_el_s": 0.0,
        "conc_Ec": 34.0,
        "el_phi": 0.0,
        "ns": ratio,
        "nl": ratio,
        "sls_fctm": 3.2,
    }
    out = {
        "elastic": {
            "max_conc": 1.1,
            "max_steel": 0.0,
            "lambda_cr": math.inf,
            "fctm": 3.2,
            "sigma_ct": 0.0,
            "cracking_threshold": {
                "method": "fixed-prestress-decompression",
                "fctm_mpa": 3.2,
                "sigma_ct_mpa": 0.0,
                "factor": math.inf,
                "raw_factor": math.inf,
                "fixed_prestress_mpa": -1.1,
                "external_tension_mpa": 0.0,
                "available_tension_mpa": 4.3,
                "governing_fibre_index": 2,
            },
        }
    }
    calculations = trace_builders.elastic_calculations(
        inp,
        out,
        context={"family": "oracle", "case_id": "infinite-prestress"},
    )
    cracking = next(
        item for item in calculations if item.calculation_id.endswith("cracking-factor")
    )
    create_bundle(
        input_sha256=fingerprint_payload(inp, omit_keys=()),
        result_sha256=fingerprint_payload(out, omit_keys=()),
        calculations=(cracking,),
    )
    steps = _steps(cracking)
    assert steps["sigma-pre"].evaluated_value == pytest.approx(-1.1)
    assert steps["sigma-ext"].evaluated_value == 0.0
    assert steps["available-tension"].evaluated_value == pytest.approx(4.3)
    assert steps["positive-external-tension"].evaluated_value == 0.0
    assert steps[cracking.final_step_id].evaluated_value == 0.0


def test_plastic_trace_is_anchored_to_published_handcalculation_fixture():
    case = next(
        item
        for item in test_plastic_handcalc.CASES
        if item["name"] == "Fundamentsbj_lke"
    )
    section, concrete, steel, prestress = test_plastic_handcalc._build(case)
    p_ed, angle, mx_expected, my_expected, *_ = case["rows"][1]
    result = plastic_capacity_at_angle(
        section,
        concrete,
        steel,
        p_ed,
        angle,
        prestress=prestress,
        n_bands=50,
    )
    assert result.converged
    assert result.Mx == pytest.approx(mx_expected, rel=0.03, abs=1.0)
    assert result.My == pytest.approx(my_expected, rel=0.03, abs=1.0)

    inp = {
        "section": section,
        "P_pl": -p_ed,
        "Mx_pl": mx_expected,
        "My_pl": my_expected,
        "concrete": concrete,
        "steel": steel,
        "prestress": prestress,
        "concrete_preset": codes.EC2_2005_DKNA.label,
    }
    out = {
        "plastic": {
            "points": [result],
            "mx": [result.Mx],
            "my": [result.My],
            "converged": True,
        }
    }
    calculation = trace_builders.plastic_calculations(
        inp,
        out,
        context={"family": "oracle", "case_id": "handcalc"},
    )[0]
    create_bundle(
        input_sha256=fingerprint_payload(inp, omit_keys=()),
        result_sha256=fingerprint_payload(out, omit_keys=()),
        calculations=(calculation,),
    )
    steps = _steps(calculation)
    assert steps["axial-resultant"].evaluated_value == pytest.approx(
        -p_ed,
        abs=1.0e-6,
    )
    assert steps["axial-residual"].evaluated_value == pytest.approx(
        0.0,
        abs=1.0e-6,
    )
    assert steps["mx-rd"].evaluated_value == pytest.approx(result.Mx)
    assert steps["my-rd"].evaluated_value == pytest.approx(result.My)
    assert steps[calculation.final_step_id].evaluated_value == pytest.approx(
        math.hypot(result.Mx, result.My)
    )


def test_elastic_trace_is_anchored_to_rectangular_worked_example():
    _, p_ed, mx_ed, my_ed, ratio, max_comp, *_ = (
        test_elastic.WORKED_CASES[0]
    )
    result = solve_elastic(
        test_elastic.rectangular_section(),
        p_ed,
        mx_ed,
        my_ed,
        ratio,
    )
    assert result.converged
    assert result.max_concrete_compression == pytest.approx(
        max_comp,
        rel=0.005,
        abs=20.0,
    )
    max_steel_mpa = max(abs(value) for value in result.bar_stress) / 1000.0
    max_concrete_mpa = result.max_concrete_compression / 1000.0
    inp = {
        "section": test_elastic.rectangular_section(),
        "P_el_l": p_ed,
        "Mx_el_l": mx_ed,
        "My_el_l": my_ed,
        "P_el_s": 0.0,
        "Mx_el_s": 0.0,
        "My_el_s": 0.0,
        "conc_Ec": 200.0 / ratio,
        "el_phi": 0.0,
        "ns": ratio,
        "nl": ratio,
    }
    out = {
        "elastic": {
            "max_conc": max_concrete_mpa,
            "max_steel": max_steel_mpa,
        }
    }
    calculation = trace_builders.elastic_calculations(
        inp,
        out,
        context={"family": "oracle", "case_id": "elastic-worked"},
    )[0]
    create_bundle(
        input_sha256=fingerprint_payload(inp, omit_keys=()),
        result_sha256=fingerprint_payload(out, omit_keys=()),
        calculations=(calculation,),
    )
    steps = _steps(calculation)
    assert steps["n-ratio-short"].evaluated_value == pytest.approx(ratio)
    assert steps["max-concrete"].evaluated_value == pytest.approx(
        max_concrete_mpa
    )
    assert steps["max-reinforcement"].evaluated_value == pytest.approx(
        max_steel_mpa
    )
    assert steps[calculation.final_step_id].evaluated_value == pytest.approx(
        max(max_concrete_mpa, max_steel_mpa)
    )


def test_manual_pdf_reuses_presentations_without_running_engineering_kernels(
    monkeypatch,
):
    assert sum(block[0] == "trace" for block in manual.manual_blocks()) == 1
    bundle = reference_bundle()
    raw_views = presentation.calculation_presentations(bundle)
    calls = []
    original = manual.trace_presentation.calculation_presentations

    def capture(model):
        calls.append(model)
        return original(model)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("manual trace renderer invoked an engineering kernel")

    monkeypatch.setattr(
        manual.trace_presentation,
        "calculation_presentations",
        capture,
    )
    monkeypatch.setattr(manual, "solve_plastic", forbidden)
    monkeypatch.setattr(manual, "analyse_cracking", forbidden)
    monkeypatch.setattr(manual, "steel_fatigue_life", forbidden)

    pdf = manual.build_manual_pdf_bytes(figures=False)
    text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(io.BytesIO(pdf)).pages
    )

    assert calls == [bundle]
    assert "Ordered standards calculation examples" in text
    assert "Symbolic:" in text
    assert "Substitution:" in text
    assert "Dependencies:" in text
    assert "direct-tension crack width" in text
    for coverage_id in sorted(EXPECTED_COVERAGE):
        assert coverage_id in text

    for calculation, view in zip(bundle.calculations, raw_views):
        assert view.calculation_id == calculation.calculation_id
        assert view.coverage_id == calculation.coverage_id
        assert len(view.steps) == len(calculation.steps)
        for step, step_view in zip(calculation.steps, view.steps):
            assert step_view.step_id == step.step_id
            assert step_view.symbolic_expression == step.symbolic_expression
            assert (
                step_view.substituted_expression
                == step.substituted_expression
            )
            unit_suffix = "" if step.unit == "1" else f" {step.unit}"
            assert step_view.value_text == (
                f"{presentation.format_number(step.evaluated_value)}"
                f"{unit_suffix}"
            )
