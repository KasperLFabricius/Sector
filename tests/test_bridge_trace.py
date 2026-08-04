"""Independent CT-011 numerical, inventory, identity, and graph controls."""

from __future__ import annotations

import copy
import dataclasses
import math
from collections.abc import Mapping

import pytest

from app.sector_app import _run_bridge_or_invalid, run_analysis
from sector import bridge
from sector.bridge_trace import (
    _box_evidence, _brittle_evidence, _crack_evidence, _replay,
    _validate_candidate, build_bridge_trace_family,
    validate_bridge_trace_family,
)
from sector.bridge_trace_contract import (
    BOX_SOURCE, BridgeShape, DK_WARNING_SOURCE, WALL_COMMON_COT_WARNING,
    WALL_COT_RANGE_WARNING, expected_registry,
)
from sector.calculation_trace import (
    TraceDependency, TraceUnit, TraceValidationError, seal_bundle,
)
from sector.trace_registry import audit_trace_registry


INPUT_SHA, RESULT_SHA = "a" * 64, "b" * 64
CONTEXT = {"case": "CT-011 bridge"}


@pytest.fixture(autouse=True)
def _isolate_autosave(monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct011-bridge-no-autosave")


def _brittle_row(**changes):
    row = {"region_id": "bottom", "m_rep_knm": 1000.0, "z_s_m": 0.8,
           "f_yk_mpa": 500.0, "as_provided_mm2": 2600.0}
    row.update(changes)
    return row


def _wall_row(**changes):
    row = {"wall_id": "web-1", "cot_theta": 1.5, "v_ed_kn": 300.0,
           "v_rd_max_kn": 900.0, "t_ed_equivalent_kn": 100.0,
           "t_rd_max_equivalent_kn": 400.0}
    row.update(changes)
    return row


def _crack_row(**changes):
    row = {"component": "Web", "act_mm2": 200000.0, "k_c": 0.4, "k": 0.65,
           "fct_eff_mpa": 2.5, "sigma_s_mpa": 200.0,
           "as_provided_mm2": 900.0, "restrained_shrinkage": True}
    row.update(changes)
    return row


def _input(**changes):
    inp = {"section": None, "bridge_standard": bridge.COMPONENT_METHODS,
           "bridge_brittle_base": None, "bridge_box_walls_base": None,
           "bridge_minimum_crack_base": None}
    inp.update(changes)
    return inp


def _candidate(inp):
    return {"bridge": _run_bridge_or_invalid(inp)}


def _bundle(inp, out=None):
    bundle = build_bridge_trace_family(
        inp, _candidate(inp) if out is None else out,
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA, context=CONTEXT,
    )
    assert bundle is not None
    return bundle


def _steps(bundle, member):
    for calculation in bundle.calculations:
        if calculation.calculation_id.endswith(member):
            return {step.step_id: step for step in calculation.steps}
    raise AssertionError(f"member {member} not published")


def _prefix(steps, suffix):
    return next(step_id[:-len(suffix) - 1] for step_id in steps
                if step_id.endswith(suffix) and step_id.startswith(
                    ("region-", "wall-", "component-")))


def test_brittle_oracle_boundary_dk_warning_and_standard_identity():
    required = 1000.0 * 1000.0 / (0.8 * 500.0)
    inp = _input(bridge_brittle_base=[_brittle_row()])
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    steps = _steps(bundle, "brittle-method-b")
    prefix = _prefix(steps, "as-required")
    assert steps[f"{prefix}-as-required"].result.value == pytest.approx(
        required)
    assert steps[f"{prefix}-utilisation"].result.value == pytest.approx(
        required / 2600.0)
    assert steps[f"{prefix}-status"].result.value == 1.0
    assert steps["dk-method-warning"].result.value == 0.0
    assert steps["dk-method-warning"].source != DK_WARNING_SOURCE
    assert out["bridge"]["calculations"]["brittle_method_b"]["warning"] == ""
    assert steps["ct-011-brittle-method-b-result"].result.value == 1.0

    # PASS/FAIL boundary at utilisation = 1 +/- 1e-9.
    exact = _input(bridge_brittle_base=[
        _brittle_row(as_provided_mm2=required)])
    assert _steps(_bundle(exact), "brittle-method-b")[
        "ct-011-brittle-method-b-result"].result.value == 1.0
    failing = _input(bridge_brittle_base=[
        _brittle_row(as_provided_mm2=required / 1.001)])
    steps = _steps(_bundle(failing), "brittle-method-b")
    assert steps["ct-011-brittle-method-b-result"].result.value == 0.0

    # The DK NA warning is retained evidence: warn, never suppress.
    danish = _input(bridge_standard=bridge.EN1992_2_DK_NA,
                    bridge_brittle_base=[_brittle_row()])
    danish_out = _candidate(danish)
    payload = danish_out["bridge"]["calculations"]["brittle_method_b"]
    assert "different" in payload["warning"]
    assert payload["rows"][0]["as_required_mm2"] == pytest.approx(required)
    steps = _steps(_bundle(danish, danish_out), "brittle-method-b")
    assert steps["dk-method-warning"].result.value == 1.0
    assert steps["dk-method-warning"].source == DK_WARNING_SOURCE

    # Same tables under a different retained standard seal differently.
    base = _input(bridge_standard=bridge.EN1992_2_BASE,
                  bridge_brittle_base=[_brittle_row()])
    base_out = _candidate(base)
    base_bundle = _bundle(base, base_out)
    assert base_bundle.to_dict() != bundle.to_dict()
    with pytest.raises(TraceValidationError):
        validate_bridge_trace_family(
            bundle, base, base_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)


def test_box_wall_oracle_and_retained_warnings():
    inp = _input(bridge_box_walls_base=[_wall_row()])
    out = _candidate(inp)
    steps = _steps(_bundle(inp, out), "box-walls")
    prefix = _prefix(steps, "utilisation")
    assert steps[f"{prefix}-utilisation"].result.value == pytest.approx(
        300.0 / 900.0 + 100.0 / 400.0)
    assert steps["common-cot-warning"].result.value == 0.0
    assert steps["cot-range-warning"].result.value == 0.0
    assert out["bridge"]["calculations"]["box_walls"]["warnings"] == []
    assert steps["ct-011-box-walls-result"].result.value == 1.0

    warned = _input(bridge_box_walls_base=[
        _wall_row(), _wall_row(wall_id="web-2", cot_theta=3.0,
                               v_ed_kn=800.0)])
    warned_out = _candidate(warned)
    payload = warned_out["bridge"]["calculations"]["box_walls"]
    assert payload["warnings"] == [WALL_COMMON_COT_WARNING,
                                   WALL_COT_RANGE_WARNING]
    steps = _steps(_bundle(warned, warned_out), "box-walls")
    assert steps["common-cot-warning"].result.value == 1.0
    assert steps["cot-range-warning"].result.value == 1.0
    # 800/900 + 100/400 > 1: worst-first member FAIL.
    assert steps["ct-011-box-walls-result"].result.value == 0.0


def test_minimum_crack_oracle_with_restrained_floor():
    inp = _input(bridge_minimum_crack_base=[
        _crack_row(),
        _crack_row(component="Flange", restrained_shrinkage=False,
                   as_provided_mm2=1700.0),
    ])
    out = _candidate(inp)
    steps = _steps(_bundle(inp, out), "minimum-crack-reinforcement")
    floored = 0.4 * 0.65 * 2.9 * 200000.0 / 200.0
    plain = 0.4 * 0.65 * 2.5 * 200000.0 / 200.0
    rows = out["bridge"]["calculations"]["minimum_crack_reinforcement"]["rows"]
    assert rows[0]["fct_eff_used_mpa"] == 2.9
    assert rows[1]["fct_eff_used_mpa"] == 2.5
    web = _prefix(steps, "fct-eff-used")
    assert steps[f"{web}-fct-eff-used"].result.value == 2.9
    assert steps[f"{web}-as-required"].result.value == pytest.approx(floored)
    assert rows[0]["as_required_mm2"] == pytest.approx(floored)
    assert rows[1]["as_required_mm2"] == pytest.approx(plain)
    assert rows[0]["utilisation"] == pytest.approx(floored / 900.0)
    assert steps["ct-011-minimum-crack-reinforcement-result"].result.value == (
        1.0 if floored <= 900.0 and plain <= 1700.0 else 0.0)


def test_error_branch_states_are_finite_retained_evidence():
    cases = (
        _input(bridge_standard="EN 1993",
               bridge_brittle_base=[_brittle_row()]),
        _input(bridge_brittle_base=[_brittle_row(),
                                    _brittle_row(region_id="Bottom")]),
        _input(bridge_brittle_base=[_brittle_row(m_rep_knm="junk")]),
    )
    for inp in cases:
        out = _candidate(inp)
        payload = out["bridge"]
        assert tuple(payload) == ("selected_standard", "scope",
                                  "calculations", "errors")
        assert payload["calculations"] == {}
        bundle = _bundle(inp, out)
        assert len(bundle.calculations) == 1
        final = bundle.calculations[0].steps[-1]
        assert final.result.state == "failed"
        assert final.result.reason == (
            "Retained bridge adapter error: " + payload["errors"][0]).strip()
        assert validate_bridge_trace_family(
            bundle, inp, out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT) is not None
        for tamper in (
            lambda o: o["bridge"].update(errors=("other",)),
            lambda o: o["bridge"]["calculations"].update(fake={}),
            lambda o: o["bridge"].update(scope="tampered"),
        ):
            changed = copy.deepcopy(out)
            tamper(changed)
            with pytest.raises(TraceValidationError):
                validate_bridge_trace_family(
                    bundle, inp, changed, input_sha256=INPUT_SHA,
                    result_sha256=RESULT_SHA, context=CONTEXT)


def test_inactive_family_and_composition_masking():
    idle = _input()
    assert build_bridge_trace_family(
        idle, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA) is None
    with pytest.raises(TraceValidationError, match="inactive"):
        build_bridge_trace_family(
            idle, {"bridge": {"calculations": {}}}, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA)
    assert validate_bridge_trace_family(
        None, idle, {}, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA) is None

    # Retained composition: bridge runs even when the section is invalid. The
    # family remains independently buildable until its retirement slice, but
    # run_analysis no longer attaches publication metadata.
    active = _input(bridge_brittle_base=[_brittle_row()],
                    bridge_box_walls_base=[_wall_row()],
                    bridge_minimum_crack_base=[_crack_row()],
                    geometry_error=None)
    out = run_analysis(active)
    assert set(out) == {"bridge"}
    bundle = _bundle(active, out)
    assert len(bundle.calculations) == 3
    with pytest.raises(TraceValidationError, match="inactive"):
        validate_bridge_trace_family(
            bundle, idle, {}, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)

    # Unrelated junk inputs cannot mask the family in either direction.
    masked = dict(active, Mx_pl=math.nan, shear_V=math.nan,
                  sls_fctm=math.nan, torsion_T=math.nan,
                  bar_materials=[object()])
    assert build_bridge_trace_family(
        masked, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT).to_dict() == bundle.to_dict()


def _walk(value, path=()):
    if isinstance(value, Mapping):
        yield "mapping", path, tuple(value)
        for key in value:
            yield from _walk(value[key], (*path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk(item, (*path, index))
    else:
        yield "leaf", path, value


def _at(value, path):
    for key in path:
        value = value[key]
    return value


def _replaced(value, path, replacement):
    if not path:
        return replacement
    key, *tail = path
    clone = dict(value) if isinstance(value, Mapping) else list(value)
    clone[key] = _replaced(clone[key], tail, replacement)
    return clone


def _mutated(value):
    if type(value) is bool:
        return not value
    if isinstance(value, float):
        return value + 0.271828
    if isinstance(value, str):
        return value + "-tampered"
    return 0.0


def test_inventory_walk_rejects_every_candidate_mutation():
    inp = _input(bridge_brittle_base=[_brittle_row()],
                 bridge_box_walls_base=[_wall_row()],
                 bridge_minimum_crack_base=[_crack_row()])
    out = _candidate(inp)
    replay = _replay(inp)
    candidate = out["bridge"]
    _validate_candidate(copy.deepcopy(candidate), replay)
    for kind, path, detail in list(_walk(candidate)):
        if kind == "leaf":
            with pytest.raises(TraceValidationError):
                _validate_candidate(
                    _replaced(copy.deepcopy(candidate), path,
                              _mutated(detail)), replay)
            continue
        changed = copy.deepcopy(candidate)
        _at(changed, path)["unexpected-ct011-field"] = 0.0
        with pytest.raises(TraceValidationError):
            _validate_candidate(changed, replay)
        for key in detail:
            changed = copy.deepcopy(candidate)
            del _at(changed, path)[key]
            with pytest.raises(TraceValidationError):
                _validate_candidate(changed, replay)
        if len(detail) > 1:
            changed = copy.deepcopy(candidate)
            node = _at(changed, path)
            items = [(key, node[key]) for key in reversed(detail)]
            node.clear()
            node.update(items)
            with pytest.raises(TraceValidationError):
                _validate_candidate(changed, replay)


def test_row_identity_typing_order_and_cardinality():
    inp = _input(bridge_brittle_base=[
        _brittle_row(), _brittle_row(region_id="top", m_rep_knm=800.0)])
    out = _candidate(inp)
    bundle = _bundle(inp, out)

    # Changing only an identity string reseals differently and is rejected.
    renamed = _input(bridge_brittle_base=[
        _brittle_row(region_id="soffit"),
        _brittle_row(region_id="top", m_rep_knm=800.0)])
    renamed_out = _candidate(renamed)
    with pytest.raises(TraceValidationError):
        validate_bridge_trace_family(
            bundle, renamed, renamed_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    assert validate_bridge_trace_family(
        _bundle(renamed, renamed_out), renamed, renamed_out,
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None

    # Candidate row order and cardinality are input-derived.
    for operation in ("reverse", "pop", "duplicate"):
        changed = copy.deepcopy(out)
        rows = changed["bridge"]["calculations"]["brittle_method_b"]["rows"]
        if operation == "reverse":
            rows.reverse()
        elif operation == "pop":
            rows.pop()
        else:
            rows.append(copy.deepcopy(rows[0]))
        with pytest.raises(TraceValidationError):
            validate_bridge_trace_family(
                bundle, inp, changed, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT)

    # Exact typing: an integer lookalike for the retained Boolean fails.
    crack = _input(bridge_minimum_crack_base=[_crack_row()])
    crack_out = _candidate(crack)
    crack_bundle = _bundle(crack, crack_out)
    row = crack_out["bridge"]["calculations"][
        "minimum_crack_reinforcement"]["rows"][0]
    assert type(row["restrained_shrinkage"]) is bool
    changed = copy.deepcopy(crack_out)
    changed["bridge"]["calculations"]["minimum_crack_reinforcement"][
        "rows"][0]["restrained_shrinkage"] = 1
    with pytest.raises(TraceValidationError):
        validate_bridge_trace_family(
            crack_bundle, crack, changed, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    # An integer flag in the ENTERED table is the retained False default.
    coerced = _input(bridge_minimum_crack_base=[
        _crack_row(restrained_shrinkage=1)])
    rows = _candidate(coerced)["bridge"]["calculations"][
        "minimum_crack_reinforcement"]["rows"]
    assert rows[0]["restrained_shrinkage"] is False
    assert rows[0]["fct_eff_used_mpa"] == 2.5

    # bridge_standard junk with a table error stays fail-closed typing-wise.
    with pytest.raises(TraceValidationError, match="bridge_standard"):
        build_bridge_trace_family(
            _input(bridge_standard=object(),
                   bridge_brittle_base=[_brittle_row()]),
            {"bridge": {}}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA)


def test_graph_reachability_edges_sources_units_axes_and_stale_seals():
    inp = _input(bridge_brittle_base=[_brittle_row()],
                 bridge_box_walls_base=[_wall_row()],
                 bridge_minimum_crack_base=[_crack_row()])
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    replay = _replay(inp)
    registry = expected_registry(BridgeShape(
        brittle=_brittle_evidence(replay, CONTEXT)[0],
        box=_box_evidence(replay, CONTEXT)[0],
        crack=_crack_evidence(replay, CONTEXT)[0],
    ))
    for calculation in bundle.calculations:
        by_id = {step.step_id: step for step in calculation.steps}
        reached, pending = set(), [calculation.final_step_id]
        while pending:
            step_id = pending.pop()
            reached.add(step_id)
            pending.extend(dep.step_id for dep in by_id[step_id].dependencies
                           if dep.step_id not in reached)
        assert reached == set(by_id)
    for ci, calculation in enumerate(bundle.calculations):
        for si, step in enumerate(calculation.steps):
            for di in range(len(step.dependencies)):
                steps = list(calculation.steps)
                steps[si] = dataclasses.replace(
                    step, dependencies=step.dependencies[:di]
                    + step.dependencies[di + 1:])
                calculations = list(bundle.calculations)
                calculations[ci] = dataclasses.replace(
                    calculation, steps=tuple(steps))
                with pytest.raises(TraceValidationError):
                    tampered = seal_bundle(dataclasses.replace(
                        bundle, calculations=tuple(calculations)))
                    audit_trace_registry(tampered, registry)

    brittle = bundle.calculations[0]

    def _retarget(**changes):
        return seal_bundle(dataclasses.replace(
            bundle, calculations=(dataclasses.replace(brittle, **changes),
                                  *bundle.calculations[1:])))

    steps = list(brittle.steps)
    index = next(i for i, s in enumerate(steps)
                 if s.step_id.endswith("-as-required"))
    steps[index] = dataclasses.replace(steps[index], source=BOX_SOURCE)
    source_tamper = _retarget(steps=tuple(steps))
    target = brittle.steps[index].step_id
    wrong = TraceUnit("kN", "force")
    unit_steps = tuple(dataclasses.replace(
        step, unit=wrong if step.step_id == target else step.unit,
        dependencies=tuple(TraceDependency(
            dep.step_id, wrong if dep.step_id == target else dep.unit)
            for dep in step.dependencies)) for step in brittle.steps)
    unit_tamper = _retarget(steps=unit_steps)
    value_steps = list(brittle.steps)
    value_steps[-1] = dataclasses.replace(
        value_steps[-1],
        result=dataclasses.replace(value_steps[-1].result, value=0.0))
    content_tamper = _retarget(steps=tuple(value_steps))
    axes_tamper = _retarget(axes=tuple(
        dataclasses.replace(axis, value=bridge.EN1992_2_BASE)
        if axis.name == "bridge_standard" else axis for axis in brittle.axes))
    swapped = list(brittle.steps)
    swapped[1], swapped[2] = swapped[2], swapped[1]
    reorder_tamper = _retarget(steps=tuple(swapped))
    for candidate in (source_tamper, unit_tamper, content_tamper, axes_tamper,
                      reorder_tamper,
                      dataclasses.replace(bundle, input_sha256="c" * 64),
                      dataclasses.replace(bundle, result_sha256="c" * 64),
                      dataclasses.replace(bundle,
                                          calculations=bundle.calculations * 2)):
        with pytest.raises(TraceValidationError):
            validate_bridge_trace_family(
                candidate, inp, out, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT)
    assert validate_bridge_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None


def test_brittle_status_source_and_check_row_shapes():
    inp = _input(bridge_brittle_base=[_brittle_row()])
    out = _candidate(inp)
    payload = out["bridge"]["calculations"]["brittle_method_b"]
    assert tuple(payload) == ("method", "equation", "source",
                              "selected_standard", "warning", "rows")
    assert tuple(payload["rows"][0]) == (
        "region_id", "m_rep_knm", "z_s_m", "f_yk_mpa", "as_required_mm2",
        "as_provided_mm2", "utilisation", "status")
    assert payload["method"] == bridge.BRITTLE_METHOD_B
    assert payload["equation"] == bridge.BRITTLE_METHOD_B_EQUATION
    assert payload["source"] == bridge.BRITTLE_METHOD_B_SOURCE


def test_cross_table_error_precedence_matches_retained_interleaving():
    # Retained calculate() interleaves records -> kernel per table, so an
    # earlier table's KERNEL error precedes a later table's RECORDS error.
    case_a = _input(
        bridge_brittle_base=[_brittle_row(),
                             _brittle_row(region_id="Bottom")],
        bridge_box_walls_base=[_wall_row(v_ed_kn="junk")])
    out_a = _candidate(case_a)
    assert "duplicate tensile-region ID" in out_a["bridge"]["errors"][0]
    bundle_a = _bundle(case_a, out_a)
    assert out_a["bridge"]["errors"][0] in (
        bundle_a.calculations[0].steps[-1].result.reason)

    case_b = _input(
        bridge_box_walls_base=[_wall_row(),
                               _wall_row(wall_id="WEB-1", v_ed_kn=100.0)],
        bridge_minimum_crack_base=[_crack_row(act_mm2="junk")])
    out_b = _candidate(case_b)
    assert "duplicate wall ID" in out_b["bridge"]["errors"][0]
    bundle_b = _bundle(case_b, out_b)
    assert out_b["bridge"]["errors"][0] in (
        bundle_b.calculations[0].steps[-1].result.reason)
    assert validate_bridge_trace_family(
        bundle_b, case_b, out_b, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) is not None


def test_unbounded_retained_row_values_seal_as_positive_infinity():
    # Retained kernels can overflow to inf from finite entered operands and
    # publish FAIL; the trace represents that, never fabricating finites.
    inp = _input(
        bridge_brittle_base=[_brittle_row(m_rep_knm=1.0e308, z_s_m=0.5)],
        bridge_box_walls_base=[_wall_row(v_ed_kn=1.0e308,
                                         v_rd_max_kn=1.0e-8)],
        bridge_minimum_crack_base=[_crack_row(act_mm2=1.0e308,
                                              sigma_s_mpa=1.0e-8)])
    out = _candidate(inp)
    calculations = out["bridge"]["calculations"]
    assert math.isinf(
        calculations["brittle_method_b"]["rows"][0]["as_required_mm2"])
    assert math.isinf(calculations["box_walls"]["rows"][0]["utilisation"])
    assert math.isinf(calculations["minimum_crack_reinforcement"]["rows"][0][
        "as_required_mm2"])
    assert all(payload["rows"][0]["status"] == "FAIL"
               for payload in calculations.values())
    bundle = _bundle(inp, out)
    for member, suffix in (("brittle-method-b", "as-required"),
                           ("box-walls", "utilisation"),
                           ("minimum-crack-reinforcement", "as-required")):
        steps = _steps(bundle, member)
        prefix = _prefix(steps, suffix)
        step = steps[f"{prefix}-{suffix}"]
        assert step.result.state == "positive_infinity"
        assert "unbounded" in step.result.reason
        assert steps[f"{prefix}-status"].result.value == 0.0
        assert steps[f"ct-011-{member}-result"].result.value == 0.0
        assert steps[f"ct-011-{member}-result"].result.state == "finite"
    assert validate_bridge_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None
    # A finite lookalike replacing the retained unbounded value is rejected.
    changed = copy.deepcopy(out)
    changed["bridge"]["calculations"]["box_walls"]["rows"][0][
        "utilisation"] = 1.0e12
    with pytest.raises(TraceValidationError):
        validate_bridge_trace_family(
            bundle, inp, changed, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)


def test_member_status_steps_carry_the_aggregation_legend():
    inp = _input(bridge_brittle_base=[_brittle_row()])
    steps = _steps(_bundle(inp), "brittle-method-b")
    member = steps["brittle-method-b-status"]
    assert "worst-first" in member.actual_expression
    prefix = _prefix(steps, "status")
    assert "1e-9" in steps[f"{prefix}-status"].actual_expression


def test_nan_retained_row_values_seal_as_undefined_states():
    # inf/inf inside the retained kernel publishes NaN rows with FAIL; the
    # trace seals them as explicit undefined states, never finite ones.
    inp = _input(bridge_brittle_base=[_brittle_row(
        m_rep_knm=1.0e308, z_s_m=1.0e200, f_yk_mpa=1.0e200)])
    out = _candidate(inp)
    row = out["bridge"]["calculations"]["brittle_method_b"]["rows"][0]
    assert math.isnan(row["as_required_mm2"])
    assert math.isnan(row["utilisation"])
    assert row["status"] == "FAIL"
    bundle = _bundle(inp, out)
    steps = _steps(bundle, "brittle-method-b")
    prefix = _prefix(steps, "as-required")
    assert steps[f"{prefix}-as-required"].result.state == "undefined"
    assert "undefined" in steps[f"{prefix}-as-required"].result.reason
    assert steps[f"{prefix}-status"].result.value == 0.0
    assert steps["ct-011-brittle-method-b-result"].result.value == 0.0
    assert validate_bridge_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None
    # NaN-vs-finite reseals fail closed in both directions.
    finite_lookalike = copy.deepcopy(out)
    finite_lookalike["bridge"]["calculations"]["brittle_method_b"]["rows"][0][
        "as_required_mm2"] = 1.0e12
    with pytest.raises(TraceValidationError):
        validate_bridge_trace_family(
            bundle, inp, finite_lookalike, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    normal = _input(bridge_brittle_base=[_brittle_row()])
    normal_out = _candidate(normal)
    normal_bundle = _bundle(normal, normal_out)
    poisoned = copy.deepcopy(normal_out)
    poisoned["bridge"]["calculations"]["brittle_method_b"]["rows"][0][
        "utilisation"] = math.nan
    with pytest.raises(TraceValidationError):
        validate_bridge_trace_family(
            normal_bundle, normal, poisoned, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)


def test_whitespace_standard_error_branch_seals_end_to_end():
    inp = _input(bridge_standard="   ",
                 bridge_brittle_base=[_brittle_row()])
    out = _candidate(inp)
    payload = out["bridge"]
    assert payload["selected_standard"] == "   "
    assert payload["errors"][0] == "unknown selected bridge standard: "
    bundle = _bundle(inp, out)
    final = bundle.calculations[0].steps[-1]
    assert final.result.state == "failed"
    assert final.result.reason == (
        "Retained bridge adapter error: " + payload["errors"][0]).strip()
    axis = next(item for item in bundle.calculations[0].axes
                if item.name == "bridge_standard")
    assert axis.value and axis.value.startswith("u")
    assert validate_bridge_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None


def test_numeric_closure_is_exact_not_tolerant():
    inp = _input(bridge_brittle_base=[_brittle_row()],
                 bridge_box_walls_base=[_wall_row()],
                 bridge_minimum_crack_base=[_crack_row()])
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    # A sub-tolerance relative perturbation (1e-12 << the shared comparator's
    # 1e-9) must be rejected: bridge candidates are byte-identical retained
    # kernel outputs, so closure is exact.
    targets = (
        ("brittle_method_b", "as_required_mm2"),
        ("box_walls", "utilisation"),
        ("minimum_crack_reinforcement", "as_required_mm2"),
    )
    for member, field in targets:
        changed = copy.deepcopy(out)
        row = changed["bridge"]["calculations"][member]["rows"][0]
        row[field] = row[field] * (1.0 + 1.0e-12)
        with pytest.raises(TraceValidationError):
            build_bridge_trace_family(
                inp, changed, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT,
            )
        with pytest.raises(TraceValidationError):
            validate_bridge_trace_family(
                bundle, inp, changed, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT,
            )
