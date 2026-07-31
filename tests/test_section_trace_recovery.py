from __future__ import annotations
import copy
import dataclasses
import math
import pytest
from sector import codes
from sector.calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_POSITIVE_INFINITY,
    RESULT_UNDEFINED,
    TraceValidationError,
    create_bundle,
    seal_bundle,
    validate_bundle,
)
from sector.combined import radial_util
from sector.materials import Concrete, MildSteel, Prestress
from sector.plastic import plastic_capacity_at_angle, solve_interaction, solve_plastic
from sector.section import Section
from sector.section_trace_blocks import section_trace_blocks
from sector.trace_builders import create_section_trace_bundle, plastic_calculations, section_trace_registry
from sector.trace_registry import audit_trace_registry
@pytest.fixture(scope="module")
def section_case():
    section = Section.from_polygon(
        [(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)], [(0.06, 0.05, 500.0), (0.24, 0.55, 500.0)],
    )
    concrete, steel = codes.EC2_2005.concrete(35.0), codes.EC2_2005.steel(500.0)
    points = solve_plastic(section, concrete, steel, 0.0, 0.0, 360.0, 90.0, n_bands=20)
    mx, my = [item.Mx for item in points], [item.My for item in points]
    util, gov = radial_util(mx, my, 10.0, 20.0)
    interactions = {}
    for axis, angle in (("x", 90.0), ("y", 0.0)):
        values = solve_interaction(section, concrete, steel, angle, n_points=4, n_bands=20)
        interactions[axis] = {
            "N": [-item.axial for item in values], "M": [getattr(item, f"M{axis}") for item in values], "converged": all(item.converged for item in values),
        }
    inp = {
        "section": section, "concrete": concrete, "steel": steel, "concrete_preset": codes.EC2_2005.label, "mild_preset": codes.EC2_2005.label,
        "P_pl": 0.0, "Mx_pl": 10.0, "My_pl": 20.0,
    }
    out = {
        "plastic": {
            "points": points, "mx": mx, "my": my, "util": util, "util_gov": gov, "converged": all(item.converged for item in points), "interaction": interactions,
        },
    }
    return inp, out
def _bundle(inp, out):
    return create_section_trace_bundle(inp, out, context={"case": "recovery"}, input_sha256="1" * 64, result_sha256="2" * 64)
def test_all_selected_chains_are_complete_and_reconstruct_solver_results(section_case):
    inp, out = section_case
    bundle = _bundle(inp, out)
    assert [item.coverage_id for item in bundle.calculations] == ["ct-002", "ct-003", "ct-004", "ct-004"]
    for calculation in bundle.calculations:
        seen = set()
        for step in calculation.steps:
            assert all(dep.step_id in seen for dep in step.dependencies)
            seen.add(step.step_id)
        reachable, pending = set(), [calculation.final_step_id]
        lookup = {step.step_id: step for step in calculation.steps}
        while pending:
            step_id = pending.pop()
            if step_id not in reachable:
                reachable.add(step_id)
                pending.extend(dep.step_id for dep in lookup[step_id].dependencies)
        assert reachable == seen
    by_id = {item.calculation_id.rsplit(".", 1)[-1]: item for item in bundle.calculations}
    capacity = by_id["capacity"]
    steps = {step.step_id: step for step in capacity.steps}
    assert steps["m-rd-resultant"].result.value == pytest.approx(
        math.hypot(steps["mx-rd"].result.value, steps["my-rd"].result.value)
    )
    assert {"section-geometry", "bar-assignment-001", "bar-assignment-002"} <= {
        dep.step_id for dep in steps["curvature"].dependencies
    }
    interactions = [item for item in bundle.calculations if item.coverage_id == "ct-004"]
    assert {next(axis.value for axis in item.axes if axis.name == "axis") for item in interactions} == {"x", "y"}
    assert all(item.steps[-1].result.state == RESULT_FINITE for item in bundle.calculations)
def test_method_and_edition_selection_is_exact_for_standard_mixed_and_project(section_case):
    inp, _ = section_case
    assert section_trace_blocks(inp).plastic_method_id == "ec2-2005"
    mixed = {
        **inp,
        "bar_materials": [codes.EC2_2023.steel(500.0)] * 2,
        "mild_preset": codes.EC2_2023.label,
    }
    blocks = section_trace_blocks(mixed)
    assert blocks.plastic_method_id == "mixed-standard-project-material-section-solve"
    assert {blocks.concrete.provenance.source.edition, blocks.bars[0].provenance.source.edition} == {
        codes.EC2_2005.label, codes.EC2_2023.label
    }
    project = {
        **inp,
        "concrete": Concrete(37.0, 1.31, alpha_cc=0.91),
        "steel": MildSteel(610.0, 590.0, futk=650.0, eut=0.04, curve=1),
        "concrete_preset": "Custom / imported", "mild_preset": "Custom / imported",
    }
    project_blocks = section_trace_blocks(project)
    assert project_blocks.plastic_method_id == "user-defined-material-section-solve"
    assert all(item.provenance.source.citation is None for item in (project_blocks.concrete, *project_blocks.bars))
    with pytest.raises(ValueError, match="aligned catalog provenance"):
        section_trace_blocks({**inp, "bar_materials": [inp["steel"], project["steel"]]})
def test_heterogeneous_bar_tendon_and_hole_inputs_reach_plastic_final():
    section = Section.from_polygon(
        [(0, 0), (0.3, 0), (0.3, 0.6), (0, 0.6)],
        [(0.06, 0.05, 500), (0.24, 0.55, 500)],
        holes=[[(0.13, 0.25), (0.17, 0.25), (0.17, 0.35), (0.13, 0.35)]],
        tendons_xy_area_mm2=[(0.15, 0.08, 400)],
    )
    concrete, standard = codes.EC2_2005.concrete(35), codes.EC2_2005.steel(500)
    custom = MildSteel(620, 430, futk=680, eut=0.032, curve=1, Es=205000)
    tendon = Prestress(curve=7, IS=0.0058, fytk=1600, futk=1820, eut=0.036, Es=195000)
    point = plastic_capacity_at_angle(section, concrete, standard, 0, 90, bar_materials=[standard, custom], tendon_materials=[tendon], n_bands=20)
    inp = {
        "section": section, "concrete": concrete, "steel": standard, "prestress": tendon,
        "concrete_preset": codes.EC2_2005.label, "prestress_preset": codes.EC2_2023.label,
        "bar_materials": [standard, custom], "tendon_materials": [tendon],
        "bar_elements": [{"id": "B1", "material_id": "M1"}, {"id": "B2", "material_id": "M2"}],
        "mild_material_catalog": {"items": [{"id": "M1", "preset": codes.EC2_2005.label}, {"id": "M2", "preset": "Custom / imported"}]},
        "P_pl": 0.0, "Mx_pl": point.Mx, "My_pl": point.My,
    }
    calc = plastic_calculations(inp, {"plastic": {"points": [point], "mx": [point.Mx], "my": [point.My], "util_gov": 0, "converged": point.converged}}, context={"case": "heterogeneous"})[0]
    steps = {step.step_id: step for step in calc.steps}
    assert calc.method_id == "mixed-standard-project-material-section-solve"
    assert {"section-geometry", "bar-assignment-001", "bar-assignment-002", "tendon-assignment-001"} <= {dep.step_id for dep in steps["curvature"].dependencies}
    assert steps["bar-001-law"].source.edition == codes.EC2_2005.label
    assert steps["bar-002-law"].source.citation is None
    assert steps["tendon-001-law"].source.edition == codes.EC2_2023.label
def test_explicit_infinite_undefined_and_failed_members_cannot_be_masked(section_case):
    inp, out = section_case
    hostile = copy.deepcopy(out)
    hostile["plastic"]["util"] = math.inf
    hostile["plastic"]["interaction"].pop("y")
    bundle = _bundle(inp, hostile)
    states = {(item.coverage_id, item.calculation_id.rsplit("-", 1)[-1]): item.steps[-1].result.state for item in bundle.calculations}
    assert states[("ct-003", "utilisation")] == RESULT_POSITIVE_INFINITY
    assert states[("ct-004", "y")] == RESULT_FAILED
    undefined = copy.deepcopy(out)
    undefined["plastic"]["util"] = math.nan
    radial = next(item for item in _bundle(inp, undefined).calculations if item.coverage_id == "ct-003")
    assert radial.steps[-1].result.state == RESULT_UNDEFINED
    unselected = copy.deepcopy(out)
    unselected["plastic"]["util_gov"] = None
    capacity = next(item for item in _bundle(inp, unselected).calculations if item.coverage_id == "ct-002")
    assert capacity.steps[-1].result.state == RESULT_FAILED
    retained = copy.deepcopy(out)
    retained["plastic"]["points"] = [
        {key: getattr(item, key) for key in ("V", "Mx", "My", "curvature", "compression_force", "lever_arm", "converged")}
        for item in retained["plastic"]["points"]
    ]
    capacity = next(item for item in _bundle(inp, retained).calculations if item.coverage_id == "ct-002")
    assert capacity.steps[-1].result.state == RESULT_FAILED
def test_registry_rejects_missing_axis_edition_dependency_tamper_and_stale(section_case):
    inp, out = section_case
    bundle, registry = _bundle(inp, out), section_trace_registry(inp, out, context={"case": "recovery"})
    without_radial = create_bundle(
        input_sha256=bundle.input_sha256, result_sha256=bundle.result_sha256,
        calculations=tuple(item for item in bundle.calculations if item.coverage_id != "ct-003"),
    )
    with pytest.raises(TraceValidationError, match="missing"):
        audit_trace_registry(without_radial, registry)
    x_index = next(i for i, item in enumerate(bundle.calculations) if item.calculation_id.endswith("interaction-x"))
    wrong_axis = dataclasses.replace(bundle.calculations[x_index], axes=bundle.calculations[x_index + 1].axes)
    with pytest.raises(TraceValidationError, match="axes"):
        audit_trace_registry(create_bundle(input_sha256="1" * 64, result_sha256="2" * 64, calculations=(*bundle.calculations[:x_index], wrong_axis, *bundle.calculations[x_index + 1:])), registry)
    capacity = bundle.calculations[0]
    source_index = next(i for i, step in enumerate(capacity.steps) if step.source.edition)
    wrong_source = dataclasses.replace(capacity.steps[source_index].source, edition=codes.EC2_2023.label)
    wrong_step = dataclasses.replace(capacity.steps[source_index], source=wrong_source)
    wrong_capacity = dataclasses.replace(capacity, steps=(*capacity.steps[:source_index], wrong_step, *capacity.steps[source_index + 1:]))
    with pytest.raises(TraceValidationError, match="sources"):
        audit_trace_registry(create_bundle(input_sha256="1" * 64, result_sha256="2" * 64, calculations=(wrong_capacity, *bundle.calculations[1:])), registry)
    radial_index = next(i for i, item in enumerate(bundle.calculations) if item.coverage_id == "ct-003")
    radial = bundle.calculations[radial_index]
    reversed_final = dataclasses.replace(radial.steps[-1], dependencies=tuple(reversed(radial.steps[-1].dependencies)))
    changed = dataclasses.replace(radial, steps=(*radial.steps[:-1], reversed_final))
    with pytest.raises(TraceValidationError, match="dependency graph"):
        audit_trace_registry(create_bundle(input_sha256="1" * 64, result_sha256="2" * 64, calculations=(*bundle.calculations[:radial_index], changed, *bundle.calculations[radial_index + 1:])), registry)
    tampered = dataclasses.replace(bundle.calculations[0].steps[-1].result, value=0.0)
    invalid = dataclasses.replace(bundle, calculations=(dataclasses.replace(bundle.calculations[0], steps=(*bundle.calculations[0].steps[:-1], dataclasses.replace(bundle.calculations[0].steps[-1], result=tampered))), *bundle.calculations[1:]))
    with pytest.raises(TraceValidationError, match="seal"):
        validate_bundle(invalid)
    with pytest.raises(TraceValidationError, match="input fingerprint"):
        validate_bundle(bundle, expected_input_sha256="3" * 64)
    with pytest.raises(TraceValidationError, match="duplicate calculation"):
        create_bundle(input_sha256="1" * 64, result_sha256="2" * 64, calculations=(*bundle.calculations, bundle.calculations[0]))
