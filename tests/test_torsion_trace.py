"""Independent CT-007 numerical, inventory, provenance, and graph controls."""

from __future__ import annotations

import copy
import dataclasses
import math
from collections.abc import Mapping

import pytest

from app import material_catalog
from app.sector_app import _run_capacity_checks
from sector import codes, templates
from sector.calculation_trace import (
    SOURCE_PROJECT, SOURCE_STANDARD, TraceDependency, TraceSource, TraceUnit,
    TraceValidationError, seal_bundle,
)
from sector.section import Section
from sector.torsion_trace import (
    _replay, _validate_candidate, build_torsion_trace_family,
    torsion_trace_applicability, validate_torsion_trace_family,
)
from sector.torsion_trace_contract import (
    BASE_ANGLE_SOURCE, BASE_NU_SOURCE, CORE_INPUT_KEYS, DK_ANGLE_SOURCE,
    DK_NU_DETAIL_SOURCE, DK_NU_T_SOURCE, TOP_EXCLUDED,
    expected_registry,
)
from sector.trace_registry import audit_trace_registry


INPUT_SHA, RESULT_SHA = "a" * 64, "b" * 64
CONTEXT = {"case": "CT-007 torsion"}


@pytest.fixture(autouse=True)
def _isolate_autosave(monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct007-torsion-no-autosave")


def _input(*, method=codes.EC2_2005_DKNA, demand=40.0, subdivided=False,
           zero=False, **changes):
    if subdivided:
        outer = templates.t_section(1.0, 0.2, 0.3, 0.6)
        rectangles = [(0.0, -100.0, 300.0, 600.0),
                      (0.0, 300.0, 1000.0, 200.0)]
        bars = []
    else:
        outer = templates.rectangle(0.3, 0.6)
        rectangles, bars = [], [(-0.10, -0.25, 500.0)]
    entries = [material_catalog.default_entry(
        "mild", material_id=material_id, preset=method.label
    ) for material_id in ("M1", "M2")]
    steel = material_catalog.build_material(entries[1], "mild")
    inp = dict(
        outer=outer, holes=[], bars=bars, tendons=[],
        section=Section.from_polygon(outer, bars),
        concrete=method.concrete(35.0), steel=steel, prestress=None,
        concrete_preset=method.label, mild_preset=method.label,
        bar_elements=[{"id": "B1", "material_id": "M1"}] if bars else [],
        bar_materials=[material_catalog.build_material(entries[0], "mild")] if bars else [],
        mild_material_catalog={"version": 1, "next_id": 3, "items": entries},
        capacity_steel_material_id="M2", P_pl=0.0, Mx_pl=0.0, My_pl=0.0,
        shear_on=False, shear_method=method.label, shear_axis="x",
        shear_tension=True, shear_bw=0.0, shear_dlower=16.0, shear_V=0.0,
        shear_links=False, shear_link_legs=2.0, shear_link_dia=10.0,
        shear_link_s=150.0, shear_fywk=500.0,
        strut_cot_min=1.0, strut_cot_max=2.5,
        torsion_on=True, torsion_method=method.label, torsion_tef=0.0,
        torsion_nu_v=False, torsion_gamma_ct=method.gamma_ct,
        torsion_T=0.0 if zero else demand, torsion_subdivide=subdivided,
        torsion_subrects=rectangles, combined_on=False,
        combined_method="DS/EN 1992-1-1 + DK NA",
        combined_mv_independent=False,
    )
    inp.update(changes)
    return inp


def _candidate(inp):
    out = {}
    _run_capacity_checks(inp, out)
    return out.get("torsion", {})


def _bundle(inp, out=None):
    bundle = build_torsion_trace_family(
        inp, _candidate(inp) if out is None else out,
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA, context=CONTEXT,
    )
    assert bundle is not None
    return bundle


def _steps(bundle):
    return {step.step_id: step for step in bundle.calculations[0].steps}


def _rect_tube(b, h):
    area, perimeter = b * h, 2.0 * (b + h)
    tef_m = area / perimeter
    return area, perimeter, tef_m * 1000.0, (b - tef_m) * (h - tef_m), 2.0 * (b + h - 2.0 * tef_m)


def _rectangle_constant(b, h):
    short, long = min(b, h), max(b, h)
    ratio = short / long
    return long * short ** 3 * (1.0 / 3.0 - 0.21 * ratio * (1.0 - ratio ** 4 / 12.0))


def _tube_values(t_ed, ak, tef, uk, cot, *, fcd, nu, fywd, asw_s, fctd, fyd):
    trds = asw_s * 2.0 * ak * fywd * cot
    trdmax = 2.0 * nu * fcd * ak * (tef / 1000.0) * cot / (1.0 + cot * cot) * 1000.0
    trd = min(trds, trdmax)
    return dict(trds=trds, trdmax=trdmax, trd=trd,
                trdc=2.0 * ak * (tef / 1000.0) * fctd * 1000.0,
                asl=t_ed * uk * cot / (2.0 * ak * fyd) * 1000.0,
                util=t_ed / trd)


@pytest.mark.parametrize("method", [codes.EC2_2005, codes.EC2_2005_DKNA])
def test_single_tube_oracle_enumerates_selector_and_closes_base_dk(method):
    inp = _input(method=method)
    steps = _steps(_bundle(inp))
    area, perimeter, tef, ak, uk = _rect_tube(0.3, 0.6)
    gamma_s = inp["steel"].gamma_y
    fcd, fywd, fyd = inp["concrete"].fcd, 500.0 / gamma_s, inp["steel"].fytk / gamma_s
    asw_s = math.pi * 10.0 ** 2 / 4.0 / 150.0
    nu = (0.6 * (1.0 - 35.0 / 250.0) if method is codes.EC2_2005
          else 0.7 * (0.7 - 35.0 / 200.0))
    fctm, gamma_ct = 0.3 * 35.0 ** (2.0 / 3.0), inp["torsion_gamma_ct"]
    fctd = 0.7 * fctm / gamma_ct
    scan = []
    for index in range(1501):
        cot = 1.0 + 1.5 * index / 1500.0
        values = _tube_values(40.0, ak, tef, uk, cot, fcd=fcd, nu=nu,
                              fywd=fywd, asw_s=asw_s, fctd=fctd, fyd=fyd)
        scan.append(((values["util"], values["util"], cot), cot, values))
    _, cot, expected = min(scan)
    for name, value in (("outer-area", area), ("outer-perimeter", perimeter),
                        ("tef", tef), ("ak", ak), ("uk", uk),
                        ("trd-s", expected["trds"]), ("trd-max", expected["trdmax"]),
                        ("trd", expected["trd"]), ("trd-c", expected["trdc"]),
                        ("asl-required", expected["asl"]),
                        ("utilisation", expected["util"])):
        assert steps[f"tube-00-{name}"].result.value == pytest.approx(value)
    assert steps["selector-cot"].result.value == pytest.approx(cot)
    assert steps["aggregate-utilisation"].result.value == pytest.approx(expected["util"])
    assert steps["aggregate-verdict"].result.value == float(expected["util"] <= 1.0 + 1e-9)
    assert steps["torsion-nu"].source == (BASE_NU_SOURCE if method is codes.EC2_2005 else DK_NU_T_SOURCE)
    assert steps["method-cot-limit-low"].source == (
        BASE_ANGLE_SOURCE if method is codes.EC2_2005 else DK_ANGLE_SOURCE
    )


def test_subtube_oracle_closes_order_stiffness_shares_aggregate_and_zero_branch():
    inp = _input(subdivided=True)
    steps = _steps(_bundle(inp))
    dims = ((0.3, 0.6), (1.0, 0.2))
    constants = [_rectangle_constant(*item) for item in dims]
    shares = [40.0 * value / sum(constants) for value in constants]
    fcd, gamma_s = inp["concrete"].fcd, inp["steel"].gamma_y
    fywd, fyd = 500.0 / gamma_s, inp["steel"].fytk / gamma_s
    asw_s, nu = math.pi * 10.0 ** 2 / 4.0 / 150.0, 0.7 * (0.7 - 35.0 / 200.0)
    fctd = 0.7 * 0.3 * 35.0 ** (2.0 / 3.0) / inp["torsion_gamma_ct"]
    scan = []
    for index in range(1501):
        cot = 1.0 + 1.5 * index / 1500.0
        values = []
        for demand, (b, h) in zip(shares, dims):
            _a, _u, tef, ak, uk = _rect_tube(b, h)
            values.append(_tube_values(demand, ak, tef, uk, cot, fcd=fcd, nu=nu,
                                       fywd=fywd, asw_s=asw_s, fctd=fctd, fyd=fyd))
        utilities = [item["util"] for item in values]
        scan.append(((max(utilities), sum(utilities), cot), cot, values))
    _, cot, expected = min(scan)
    assert steps["selector-cot"].result.value == pytest.approx(cot)
    assert steps["total-torsion-stiffness"].result.value == pytest.approx(sum(constants))
    assert [steps[f"tube-{i:02d}-demand"].result.value for i in range(2)] == pytest.approx(shares)
    assert steps["aggregate-resistance"].result.value == pytest.approx(sum(item["trd"] for item in expected))
    assert steps["aggregate-asl-required"].result.value == pytest.approx(sum(item["asl"] for item in expected))
    assert steps["aggregate-governing-tube"].result.value == float(max(range(2), key=lambda i: expected[i]["util"]))

    zero = _input(subdivided=True, zero=True)
    zero_steps = _steps(_bundle(zero))
    for index, (b, h) in enumerate(dims):
        _a, _u, tef, _ak, _uk = _rect_tube(b, h)
        a = asw_s * fywd
        b_value = nu * fcd * tef
        exact = min(max(max(math.sqrt(max(b_value / a - 1.0, 0.0)), 1.0), 1.0), 2.5)
        assert zero_steps[f"tube-{index:02d}-cot"].result.value == pytest.approx(exact)
        assert zero_steps[f"tube-{index:02d}-utilisation"].result.value == 0.0
    assert zero_steps["selector-mode"].result.value == 0.0
    banded = _steps(_bundle(_input(zero=True, strut_cot_min=1.2,
                                   strut_cot_max=1.4)))
    _a, _u, tef_b, _ak, _uk = _rect_tube(0.3, 0.6)
    clamp = min(max(max(math.sqrt(
        max(nu * fcd * tef_b / (asw_s * fywd) - 1.0, 0.0)), 1.0), 1.2), 1.4)
    assert banded["tube-00-cot"].result.value == pytest.approx(clamp)
    reversed_steps = _steps(_bundle(_input(strut_cot_min=2.5, strut_cot_max=1.0)))
    assert reversed_steps["input-cot-min"].result.value == 2.5
    assert reversed_steps["input-cot-max"].result.value == 1.0
    assert reversed_steps["selector-cot"].result.value == pytest.approx(
        _steps(_bundle(_input()))["selector-cot"].result.value
    )


def test_selected_capacity_material_id_controls_source_custom_and_2023_boundary():
    inp = _input(method=codes.EC2_2005)
    inp["mild_material_catalog"]["items"][0]["preset"] = "Custom / imported"
    steps = _steps(_bundle(inp))
    assert steps["link-fywd"].source.kind == SOURCE_STANDARD
    axes = {axis.name: axis.value for axis in _bundle(inp).calculations[0].axes}
    assert axes["capacity_steel_material_id"] == "M2"
    detailed = _steps(_bundle(_input(torsion_nu_v=True)))
    assert detailed["torsion-nu"].source == DK_NU_DETAIL_SOURCE
    assert detailed["nu-detailing-applied"].result.value == 1.0
    base_flag = _steps(_bundle(_input(method=codes.EC2_2005, torsion_nu_v=True)))
    assert base_flag["torsion-nu"].source == BASE_NU_SOURCE
    assert base_flag["nu-detailing-applied"].result.value == 0.0
    assert base_flag["input-nu-detailing"].result.value == 1.0

    tendon_input = _input()
    tendon_entry = material_catalog.default_entry(
        "prestress", material_id="P1", preset=codes.EC2_2005_DKNA.label
    )
    tendon_entry["IS"] = 3.0
    prestress = material_catalog.build_material(tendon_entry, "prestress")
    tendon = (0.0, 0.0, 1000.0)
    tendon_input.update(
        tendons=[tendon], prestress=prestress,
        tendon_elements=[{"id": "T1", "material_id": "P1"}],
        tendon_materials=[prestress],
        prestress_material_catalog={"version": 1, "next_id": 2,
                                    "items": [tendon_entry]},
        section=Section.from_polygon(tendon_input["outer"], tendon_input["bars"],
                                     (), [tendon]),
    )
    tendon_steps = _steps(_bundle(tendon_input))
    expected_force = prestress.Es * prestress.IS * 1000.0 * tendon[2] / 1.0e6
    assert tendon_steps["tendon-00-locked-force"].result.value == pytest.approx(expected_force)
    assert tendon_steps["prestress-axial"].result.value == pytest.approx(expected_force)

    custom = copy.deepcopy(inp)
    custom["mild_material_catalog"]["items"][1]["preset"] = "Custom / imported"
    assert _steps(_bundle(custom))["link-fywd"].source == TraceSource(
        SOURCE_PROJECT, "project-bar-law"
    )
    future = copy.deepcopy(inp)
    future["mild_material_catalog"]["items"][1]["preset"] = codes.EC2_2023.label
    with pytest.raises(TraceValidationError, match="2023"):
        _bundle(future, {})
    for defect in ("duplicate", "missing", "mismatch"):
        broken = _input(method=codes.EC2_2005)
        items = broken["mild_material_catalog"]["items"]
        if defect == "duplicate": items.append(copy.deepcopy(items[1]))
        elif defect == "missing": items.pop()
        else: items[1]["gamma_y"] += 0.01
        with pytest.raises(TraceValidationError):
            _bundle(broken, {})


def test_failing_section_publishes_genuine_fail_verdicts_and_final():
    failing = _steps(_bundle(_input(demand=400.0)))
    assert failing["aggregate-utilisation"].result.value > 1.0
    assert failing["tube-00-verdict"].result.value == 0.0
    assert failing["aggregate-verdict"].result.value == 0.0
    assert failing["ct-007-torsion-result"].result.state == "finite"
    assert failing["ct-007-torsion-result"].result.value == 0.0
    passing = _steps(_bundle(_input()))
    assert passing["aggregate-verdict"].result.value == 1.0
    assert passing["ct-007-torsion-result"].result.value == 1.0


def test_axial_action_signs_and_lossy_tendon_area_roundtrip():
    compressed = _steps(_bundle(_input(P_pl=-400.0)))
    sigma = 400.0 / (0.3 * 0.6) / 1000.0
    fcd = codes.EC2_2005_DKNA.concrete(35.0).fcd
    assert compressed["compression-positive-axial"].result.value == pytest.approx(400.0)
    assert compressed["mean-compression-stress"].result.value == pytest.approx(sigma)
    assert compressed["alpha-cw"].result.value == pytest.approx(1.0 + sigma / fcd)
    tensioned = _steps(_bundle(_input(P_pl=400.0)))
    assert tensioned["compression-positive-axial"].result.value == pytest.approx(-400.0)
    assert tensioned["mean-compression-stress"].result.value == pytest.approx(-sigma)
    assert tensioned["alpha-cw"].result.value == 1.0

    lossy_area = 2730.5666700424044
    assert float(Section.from_polygon(
        templates.rectangle(0.3, 0.6), (), (), [(0.0, 0.0, lossy_area)]
    ).tendons[0].area) * 1.0e6 != lossy_area
    entry = material_catalog.default_entry(
        "prestress", material_id="P1", preset=codes.EC2_2005_DKNA.label
    )
    prestress = material_catalog.build_material(entry, "prestress")
    tendon = (0.05, -0.10, lossy_area)
    inp = _input()
    inp.update(
        tendons=[tendon], prestress=prestress,
        tendon_elements=[{"id": "T1", "material_id": "P1"}],
        tendon_materials=[prestress],
        prestress_material_catalog={"version": 1, "next_id": 2, "items": [entry]},
        section=Section.from_polygon(inp["outer"], inp["bars"], (), [tendon]),
    )
    assert _steps(_bundle(inp))["ct-007-torsion-result"].result.state == "finite"


def test_entered_tef_override_and_hollow_wall_cap_close_identity():
    override = _steps(_bundle(_input(torsion_tef=80.0)))
    assert override["input-tef-override"].result.value == 80.0
    assert override["tube-00-tef"].result.value == pytest.approx(80.0)
    assert override["tube-00-tef-user"].result.value == 1.0
    assert override["tube-00-tef-capped"].result.value == 0.0

    outer, hole = templates.rectangle(0.4, 0.6), templates.rectangle(0.2, 0.4)
    hollow = _input()
    hollow.update(outer=outer, holes=[hole],
                  section=Section.from_polygon(outer, hollow["bars"], [hole]))
    steps = _steps(_bundle(hollow))
    assert steps["tube-00-hollow"].result.value == 1.0
    assert steps["tube-00-tef-capped"].result.value == 1.0
    assert steps["tube-00-tef"].result.value == pytest.approx(100.0)
    assert steps["tube-00-tef-auto"].result.value == pytest.approx(120.0)


def test_directional_dispatch_payloads_validate_and_extras_stay_inert():
    zero_active = _input(shear_Vx=0.0, shear_Vy=0.0)
    assert _bundle(zero_active).to_dict() == _bundle(_input()).to_dict()

    single = _input(shear_on=True, shear_links=False, shear_V=75.0,
                    shear_Vx=75.0, shear_Vy=0.0)
    biaxial = _input(shear_on=True, shear_links=False, shear_V=75.0,
                     shear_Vx=60.0, shear_Vy=75.0)
    for inp in (single, biaxial):
        out = _candidate(inp)
        bundle = _bundle(inp, out)
        assert bundle.calculations[0].steps[-1].result.state == "finite"
        assert validate_torsion_trace_family(
            bundle, inp, out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT,
        ) is not None


def test_used_2023_concrete_and_tendon_assignments_cannot_be_finite():
    concrete_2023 = _input()
    concrete_2023.update(
        concrete=codes.EC2_2023.concrete(35.0),
        concrete_preset=codes.EC2_2023.label,
    )
    with pytest.raises(TraceValidationError, match="2023 material provenance"):
        _bundle(concrete_2023, {})

    tendon_entry = material_catalog.default_entry(
        "prestress", material_id="P1", preset=codes.EC2_2023.label
    )
    prestress = material_catalog.build_material(tendon_entry, "prestress")
    tendon = (0.0, 0.0, 1000.0)
    tendon_2023 = _input()
    tendon_2023.update(
        tendons=[tendon], prestress=prestress,
        tendon_elements=[{"id": "T1", "material_id": "P1"}],
        tendon_materials=[prestress],
        prestress_material_catalog={"version": 1, "next_id": 2,
                                    "items": [tendon_entry]},
        section=Section.from_polygon(tendon_2023["outer"], tendon_2023["bars"],
                                     (), [tendon]),
    )
    with pytest.raises(TraceValidationError, match="2023 material provenance"):
        _bundle(tendon_2023, {})


def _walk(value, path=(), top=False):
    if isinstance(value, Mapping):
        excluded = TOP_EXCLUDED if top else ()
        keys = tuple(key for key in value if key not in excluded)
        yield "mapping", path, keys
        for key in keys:
            yield from _walk(value[key], (*path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk(item, (*path, index))
    else:
        yield "leaf", path, value


def _at(value, path):
    for key in path: value = value[key]
    return value


def _replaced(value, path, replacement):
    if not path: return replacement
    key, *tail = path
    clone = dict(value) if isinstance(value, Mapping) else list(value)
    clone[key] = _replaced(clone[key], tail, replacement)
    return clone


def _mutated(value):
    if type(value) is bool: return not value
    if type(value) is int: return value + 1
    if isinstance(value, float): return value + 0.271828
    if isinstance(value, str): return value + "-tampered"
    return 0.0


def test_every_retained_output_member_is_exact_and_excluded_siblings_are_inert():
    inp, out = _input(subdivided=True), None
    out = _candidate(inp)
    expected = _replay(inp, out, CONTEXT).expected_output
    for kind, path, detail in list(_walk(out, top=True)):
        if kind == "leaf":
            with pytest.raises(TraceValidationError):
                _validate_candidate(_replaced(copy.deepcopy(out), path, _mutated(detail)), expected)
            continue
        changed = copy.deepcopy(out); _at(changed, path)["unexpected-ct007-field"] = 0.0
        with pytest.raises(TraceValidationError): _validate_candidate(changed, expected)
        for key in detail:
            changed = copy.deepcopy(out); del _at(changed, path)[key]
            with pytest.raises(TraceValidationError): _validate_candidate(changed, expected)
        if len(detail) > 1:
            changed = copy.deepcopy(out); node = _at(changed, path)
            items = [(key, node[key]) for key in reversed(detail)]
            node.clear(); node.update(items)
            with pytest.raises(TraceValidationError): _validate_candidate(changed, expected)
    duplicate = copy.deepcopy(out); duplicate["subtubes"].append(copy.deepcopy(duplicate["subtubes"][0]))
    with pytest.raises(TraceValidationError, match="cardinality"):
        _validate_candidate(duplicate, expected)
    reordered, missing = copy.deepcopy(out), copy.deepcopy(out)
    reordered["subtubes"].reverse(); missing["subtubes"].pop()
    for changed in (reordered, missing):
        with pytest.raises(TraceValidationError): _validate_candidate(changed, expected)

    baseline = _bundle(inp, out).to_dict()
    variants = []
    for operation in ("remove", "mutate"):
        changed = copy.deepcopy(out)
        for key in TOP_EXCLUDED:
            if operation == "remove": changed.pop(key, None)
            else: changed[key] = math.nan
        variants.append(changed)
    assert all(_bundle(inp, changed).to_dict() == baseline for changed in variants)


def test_coherent_alternate_cot_downstream_and_zero_cot_tamper_fail():
    for inp in (_input(), _input(zero=True)):
        out = _candidate(inp); evidence = _replay(inp, out, CONTEXT)
        changed = copy.deepcopy(out); primary = changed["primary"]
        cot = 1.125
        tube = primary["tube"]
        trds = changed["asw_over_s"] * 2.0 * tube["Ak"] * changed["fywd"] * cot
        trdmax = 2.0 * changed["nu"] * changed["alpha_cw"] * changed["fcd"] * tube["Ak"] * (tube["tef"] / 1000.0) * cot / (1.0 + cot * cot) * 1000.0
        trd = min(trds, trdmax); util = changed["t_ed"] / trd
        primary.update(trd_s=trds, trd_max=trdmax, trd=trd, cot=cot,
                       theta_deg=math.degrees(math.atan(1.0 / cot)), util=util,
                       asl_req=changed["t_ed"] * tube["uk"] * cot /
                       (2.0 * tube["Ak"] * changed["fyd_long"]) * 1000.0)
        for key in ("trd_s", "trd_max", "trd", "cot", "theta_deg", "util", "asl_req"):
            changed[key] = primary[key]
        with pytest.raises(TraceValidationError):
            _validate_candidate(changed, evidence.expected_output)


def test_failure_first_unrelated_masking_input_inventory_and_applicability():
    disabled = _input(torsion_on=False)
    assert torsion_trace_applicability(disabled) == "not-applicable-disabled"
    assert build_torsion_trace_family(disabled, {}, input_sha256=INPUT_SHA,
                                      result_sha256=RESULT_SHA) is None
    no_section = _input(section=None)
    assert torsion_trace_applicability(no_section) == "not-applicable-no-section"
    failed_inp = _input(subdivided=True, torsion_subdivide=False)
    failed = _bundle(failed_inp, _candidate(failed_inp))
    assert failed.calculations[0].steps[-1].result.state == "failed"
    failed_ids = [step.step_id for step in failed.calculations[0].steps]
    assert failed_ids[-2:] == ["authoritative-failure-state", "ct-007-torsion-result"]
    assert not any("trd" in sid or "utilisation" in sid or "verdict" in sid
                   or "selector" in sid for sid in failed_ids)
    finite_candidate = _candidate(_input())
    for candidate in ({}, {"trd": math.nan}, finite_candidate):
        assert _bundle(failed_inp, candidate).to_dict() == failed.to_dict()
    masked = _input(Mx_pl=math.nan, My_pl=math.inf, shear_V=math.nan,
                    shear_dlower=math.nan, v_min=math.nan,
                    bar_materials=[object()])
    assert _bundle(masked, _candidate(_input())).to_dict() == _bundle(_input()).to_dict()
    sub = _input(subdivided=True, torsion_tef=math.nan)
    assert _bundle(sub, _candidate(_input(subdivided=True))).to_dict() == _bundle(_input(subdivided=True)).to_dict()
    for bad in (math.nan, math.inf, -1.0):
        with pytest.raises(TraceValidationError): _bundle(_input(torsion_T=bad), {})
    nonfinite = _input(shear_fywk=1.0e308, shear_link_dia=1000.0)
    assert _bundle(nonfinite, {}).calculations[0].steps[-1].result.state == "failed"
    for key in (*CORE_INPUT_KEYS, "torsion_tef"):
        broken = _input(); broken.pop(key, None)
        if key == "section":
            assert build_torsion_trace_family(
                broken, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA
            ) is None
        else:
            with pytest.raises(TraceValidationError): _bundle(broken, {})
    with pytest.raises(TraceValidationError, match="2023"):
        _bundle(_input(method=codes.EC2_2023), {})


def test_applicability_separates_torsion_only_from_shared_angle_branches():
    for standalone in (_input(), _input(zero=True)):
        assert torsion_trace_applicability(standalone) == "torsion"
        assert _bundle(standalone).calculations[0].steps[-1].result.state == "finite"

    shear_without_links = _input(shear_on=True, shear_links=False, shear_V=75.0)
    assert torsion_trace_applicability(shear_without_links) == "torsion"
    assert _bundle(shear_without_links).calculations[0].steps[-1].result.state == "finite"

    standalone_bundle = _bundle(_input())
    shared_branches = (
        (_input(shear_on=True, shear_links=True, shear_V=75.0),
         "not-applicable-reinforced-shear-shared-angle"),
        (_input(shear_on=True, shear_links=True, shear_V=0.0),
         "not-applicable-reinforced-shear-shared-angle"),
        (_input(combined_on=True), "not-applicable-combined-shared-angle"),
    )
    for coupled, branch in shared_branches:
        assert torsion_trace_applicability(coupled) == branch
        assert build_torsion_trace_family(
            coupled, {"cot": math.nan}, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT,
        ) is None
        assert validate_torsion_trace_family(
            None, coupled, {}, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT,
        ) is None
        with pytest.raises(TraceValidationError, match="not-applicable"):
            validate_torsion_trace_family(
                standalone_bundle, coupled, {}, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT,
            )


def test_graph_reachability_edges_sources_units_and_stale_seals_fail():
    inp, out = _input(), None; out = _candidate(inp)
    bundle = _bundle(inp, out); evidence = _replay(inp, out, CONTEXT)
    registry = expected_registry(evidence.shape)
    calculation = bundle.calculations[0]
    by_id = {step.step_id: step for step in calculation.steps}
    reached, pending = set(), [calculation.final_step_id]
    while pending:
        step_id = pending.pop(); reached.add(step_id)
        pending.extend(dep.step_id for dep in by_id[step_id].dependencies if dep.step_id not in reached)
    assert reached == set(by_id)
    for si, step in enumerate(calculation.steps):
        for di in range(len(step.dependencies)):
            steps = list(calculation.steps)
            steps[si] = dataclasses.replace(step, dependencies=step.dependencies[:di] + step.dependencies[di + 1:])
            with pytest.raises(TraceValidationError):
                tampered = seal_bundle(dataclasses.replace(
                    bundle, calculations=(dataclasses.replace(calculation, steps=tuple(steps)),)
                ))
                audit_trace_registry(tampered, registry)
    steps = list(calculation.steps); index = next(i for i, s in enumerate(steps) if s.step_id == "torsion-nu")
    steps[index] = dataclasses.replace(steps[index], source=BASE_NU_SOURCE)
    source_tamper = seal_bundle(dataclasses.replace(
        bundle, calculations=(dataclasses.replace(calculation, steps=tuple(steps)),)
    ))
    target, wrong = "aggregate-resistance", TraceUnit("kN", "force")
    unit_steps = tuple(dataclasses.replace(
        step, unit=wrong if step.step_id == target else step.unit,
        dependencies=tuple(TraceDependency(dep.step_id, wrong if dep.step_id == target else dep.unit)
                           for dep in step.dependencies)
    ) for step in calculation.steps)
    unit_tamper = seal_bundle(dataclasses.replace(
        bundle, calculations=(dataclasses.replace(calculation, steps=unit_steps),)
    ))
    value_steps = list(calculation.steps)
    value_steps[-1] = dataclasses.replace(
        value_steps[-1], result=dataclasses.replace(value_steps[-1].result, value=0.0)
    )
    content_tamper = seal_bundle(dataclasses.replace(
        bundle, calculations=(dataclasses.replace(calculation, steps=tuple(value_steps)),)
    ))
    identity_tamper = seal_bundle(dataclasses.replace(
        bundle, calculations=(dataclasses.replace(calculation, method_id="wrong-method"),)
    ))
    axes_tamper = seal_bundle(dataclasses.replace(
        bundle, calculations=(dataclasses.replace(calculation, axes=tuple(
            dataclasses.replace(axis, value="M1")
            if axis.name == "capacity_steel_material_id" else axis
            for axis in calculation.axes)),)
    ))
    # A full reversal cannot even be sealed (forward-dependency rejection), so
    # the reorder tamper swaps two dependency-free input leaves instead.
    swapped = list(calculation.steps)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    reorder_tamper = seal_bundle(dataclasses.replace(
        bundle, calculations=(dataclasses.replace(
            calculation, steps=tuple(swapped)),)
    ))
    for candidate in (source_tamper, unit_tamper, content_tamper, identity_tamper,
                      axes_tamper, reorder_tamper,
                      dataclasses.replace(bundle, input_sha256="c" * 64),
                      dataclasses.replace(bundle, result_sha256="c" * 64),
                      dataclasses.replace(bundle, calculations=bundle.calculations * 2)):
        with pytest.raises(TraceValidationError):
            validate_torsion_trace_family(candidate, inp, out,
                                           input_sha256=INPUT_SHA,
                                           result_sha256=RESULT_SHA,
                                           context=CONTEXT)
