"""CT-005 elastic/first-cracking trace, oracle, and hostile contract tests."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from sector import codes
from sector.calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_POSITIVE_INFINITY,
    ROLE_METHOD_VALUE,
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    TraceAxis,
    TraceDependency,
    TraceResult,
    TraceSource,
    TraceUnit,
    TraceValidationError,
    bundle_to_json,
    create_bundle,
    seal_bundle,
    validate_bundle,
)
from sector.elastic import (
    solve_elastic_combined,
    transformed_properties,
)
from sector.elastic_trace import (
    build_elastic_trace_family,
    validate_elastic_trace_family,
)
from sector.elastic_trace_contract import (
    BRANCH_FAILED,
    BRANCH_FINITE,
    expected_registry,
    trace_shape,
)
from sector.geometry import area_moments, clip_halfplane
from sector.materials import Prestress
from sector.section import Bar, Section
from sector.section_trace_blocks import section_trace_blocks
from sector.serviceability import analyse_cracking, combined_cracking
from sector.sls import concrete_corner_rows, element_rows, stress_outputs
from sector.trace_registry import audit_trace_registry


INPUT_SHA = "c" * 64
RESULT_SHA = "d" * 64
CONTEXT = {"case": "mixed elastic", "stage": 5}
REFERENCE_ES = 200_000.0


@pytest.fixture(autouse=True)
def _isolate_autosave(monkeypatch):
    """This headless slice does not need the repository-wide tmp_path fixture."""

    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct005-headless-no-autosave")


def _mixed_input():
    section = Section.from_polygon(
        corners=[
            (-0.34, -0.38), (0.30, -0.34), (0.36, 0.19),
            (0.08, 0.43), (-0.29, 0.31),
        ],
        bars_xy_area_mm2=[
            (-0.24, -0.26, 620.0),
            (0.22, 0.24, 480.0),
        ],
        tendons_xy_area_mm2=[(0.12, -0.22, 780.0)],
    )
    ec_gpa = 34.0
    phi = 1.35
    return {
        "section": section,
        "concrete": codes.EC2_2005.concrete(35.0),
        "steel": codes.EC2_2005.steel(500.0),
        "prestress": Prestress(curve=1, IS=0.0042, Es=195_000.0),
        "concrete_preset": codes.EC2_2005.label,
        "mild_preset": codes.EC2_2005.label,
        "prestress_preset": "project tendon",
        "bar_elements": [
            {"id": "B-left", "material_id": "B500"},
            {"id": "B-right", "material_id": "B500"},
        ],
        "tendon_elements": [
            {"id": "T-low", "material_id": "P-project"},
        ],
        "P_el_l": -180.0,
        "Mx_el_l": 105.0,
        "My_el_l": 31.0,
        "P_el_s": 35.0,
        "Mx_el_s": 42.0,
        "My_el_s": -18.0,
        "conc_Ec": ec_gpa,
        "el_phi": phi,
        "sls_fctm": 3.15,
        "ns": REFERENCE_ES / (ec_gpa * 1000.0),
        "nl": REFERENCE_ES * (1.0 + phi) / (ec_gpa * 1000.0),
    }


def _folded(inp):
    blocks = section_trace_blocks(inp)
    section = Section(
        [np.asarray(ring) for ring in blocks.geometry.rings],
        bars=[
            Bar(item.x, item.y, item.area)
            for item in (*blocks.geometry.bars, *blocks.geometry.tendons)
        ],
    )
    laws = (*blocks.bars, *blocks.tendons)
    moduli = np.asarray([dict(item.values)["Es"] for item in laws], dtype=float)
    n_mult = moduli / REFERENCE_ES
    locked = (
        np.asarray(
            [0.0] * len(blocks.bars)
            + [dict(item.values)["Es"] * dict(item.values)["IS"] * 1000.0
               for item in blocks.tendons]
        )
        if blocks.tendons else None
    )
    return blocks, section, moduli, n_mult, locked


def _candidate_output(inp):
    """Reproduce the retained headless app payload, independently of CT-005."""

    blocks, section, moduli, n_mult, locked = _folded(inp)
    nb = len(blocks.bars)
    p_l, p_s = -inp["P_el_l"], -inp["P_el_s"]
    result = solve_elastic_combined(
        section,
        p_l, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
        p_s, inp["Mx_el_s"], inp["My_el_s"], inp["ns"],
        n_mult=n_mult if n_mult.size else None,
        prestress_stress=locked,
    )
    total = np.asarray(result.bar_stress_total) / 1000.0
    long = np.asarray(result.bar_stress_long) / 1000.0
    dif = np.asarray(result.bar_stress_dif) / 1000.0
    rst1 = np.asarray(result.bar_stress_rst1) / 1000.0
    bar_ids = [item["id"] for item in inp.get("bar_elements", ())]
    tendon_ids = [item["id"] for item in inp.get("tendon_elements", ())]
    bar_material_ids = [item["material_id"] for item in inp.get("bar_elements", ())]
    tendon_material_ids = [
        item["material_id"] for item in inp.get("tendon_elements", ())
    ]
    bars = [
        (item.x, item.y, item.area * 1.0e6) for item in blocks.geometry.bars
    ]
    tendons = [
        (item.x, item.y, item.area * 1.0e6) for item in blocks.geometry.tendons
    ]
    elements = element_rows(
        bars,
        tendons,
        total=total,
        long=long,
        dif=dif,
        rst1=rst1,
        es_mpa=list(moduli[:nb]),
        ep_mpa=list(moduli[nb:]) if blocks.tendons else None,
        bar_ids=bar_ids,
        tendon_ids=tendon_ids,
        bar_material_ids=bar_material_ids,
        tendon_material_ids=tendon_material_ids,
        bar_material_names=[""] * len(bar_ids),
        tendon_material_names=[""] * len(tendon_ids),
    )
    corners = concrete_corner_rows(
        blocks.geometry.rings[0],
        blocks.geometry.rings[1:],
        stress_plane=result.short_term.strain_plane,
        ec_mpa=inp["conc_Ec"] * 1000.0,
    )
    governing = max(elements, key=lambda row: row["total_mpa"]) if elements else None
    if governing is not None and governing["total_mpa"] <= 0.0:
        governing = None
    output_stresses = stress_outputs(
        total,
        n_bars=nb,
        max_concrete_compression=result.max_concrete_compression / 1000.0,
        valid=result.converged,
        bar_ids=bar_ids,
        tendon_ids=tendon_ids,
    )
    if locked is None:
        pre_resultant = None
    else:
        x, y, area = section.bar_arrays()
        force = locked * area
        pre_resultant = (
            float(force.sum()), float((force * y).sum()), float((force * x).sum())
        )
    elastic = {
        "total": list(total), "long": list(long), "dif": list(dif),
        "rst1": list(rst1),
        "max_conc": result.max_concrete_compression / 1000.0,
        "max_conc_xy": tuple(result.short_term.max_concrete_xy),
        "max_conc_point": int(result.max_concrete_point) + 1,
        "na_x": result.na_x_intercept, "na_y": result.na_y_intercept,
        "max_steel": governing["total_mpa"] if governing else 0.0,
        "max_steel_bar": int(np.argmax(total)) + 1 if governing else 0,
        "max_steel_type": governing["element_type"] if governing else None,
        "max_steel_element": governing["element_id"] if governing else None,
        "prestress": pre_resultant,
        "converged": result.converged,
        "stress_plane": result.short_term.strain_plane,
        "elements": elements,
        "concrete_corners": corners,
        "stress_outputs": output_stresses,
    }
    cr_l = analyse_cracking(
        section,
        p_l, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
        fctm=inp["sls_fctm"], Es=moduli,
        n_mult=n_mult if n_mult.size else None,
        prestress_stress=locked,
    )
    cr_t, lam_t, sig_t = combined_cracking(
        section,
        p_l, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
        p_s, inp["Mx_el_s"], inp["My_el_s"], inp["ns"],
        fctm=inp["sls_fctm"],
        n_mult=n_mult if n_mult.size else None,
        prestress_stress=locked,
    )
    converged = result.converged and cr_l.uncracked.converged and cr_l.cracked_state.converged
    elastic["converged"] = converged
    if lam_t < cr_l.lambda_cr:
        cracked, factor, sigma_ct, state = cr_t, lam_t, sig_t, result.short_term
    else:
        cracked, factor, sigma_ct, state = (
            cr_l.cracked, cr_l.lambda_cr, cr_l.sigma_ct, cr_l.cracked_state
        )
    props_un = transformed_properties(
        section, inp["nl"], cracked=False,
        n_mult=n_mult if n_mult.size else None,
    )
    props_cr = (
        transformed_properties(
            section, inp["nl"], eps0=state.eps0, kx=state.kx, ky=state.ky,
            cracked=True, n_mult=n_mult if n_mult.size else None,
        ) if cracked else None
    )
    props = lambda item: {
        "area": item.area, "cx": item.cx, "cy": item.cy,
        "Ix": item.Ix, "Iy": item.Iy, "Ixy": item.Ixy,
    }
    elastic.update(
        cracked=cracked,
        lambda_cr=factor,
        sigma_ct=sigma_ct,
        fctm=inp["sls_fctm"],
        props_un=props(props_un),
        props_cr=props(props_cr) if props_cr is not None else None,
    )
    return {"elastic": elastic}


def _gross_moments(section):
    result = None
    for ring in section.integration_rings():
        moments = area_moments(ring)
        if result is None:
            result = np.asarray([
                moments.area, moments.sx, moments.sy,
                moments.sxx, moments.syy, moments.sxy,
            ])
        else:
            result += np.asarray([
                moments.area, moments.sx, moments.sy,
                moments.sxx, moments.syy, moments.sxy,
            ])
    return result


def _matrix(moment_values, x, y, area, ratio):
    a, sx, sy, sxx, syy, sxy = moment_values
    matrix = np.asarray([
        [a, sx, sy],
        [sy, sxy, syy],
        [sx, sxx, sxy],
    ], dtype=float)
    for xi, yi, ai, ni in zip(x, y, area, ratio):
        matrix += ni * ai * np.asarray([
            [1.0, xi, yi],
            [yi, xi * yi, yi * yi],
            [xi, xi * xi, xi * yi],
        ])
    return matrix


def _oracle_uncracked(section, target, ratio):
    x, y, area = section.bar_arrays()
    return np.linalg.solve(_matrix(_gross_moments(section), x, y, area, ratio), target)


def _oracle_cracked(section, target, ratio):
    """Test-owned active-set/Newton solve from public low-level geometry only."""

    x, y, area = section.bar_arrays()
    plane = _oracle_uncracked(section, target, ratio)
    for _ in range(60):
        moments = np.zeros(6)
        for ring in section.integration_rings():
            clipped = clip_halfplane(ring, -plane[1], -plane[2], -plane[0])
            item = area_moments(clipped)
            moments += np.asarray([
                item.area, item.sx, item.sy, item.sxx, item.syy, item.sxy,
            ])
        a, sx, sy, sxx, syy, sxy = moments
        concrete = np.asarray([
            plane[0] * a + plane[1] * sx + plane[2] * sy,
            plane[0] * sy + plane[1] * sxy + plane[2] * syy,
            plane[0] * sx + plane[1] * sxx + plane[2] * sxy,
        ])
        steel_stress = ratio * (plane[0] + plane[1] * x + plane[2] * y)
        force = steel_stress * area
        internal = concrete + np.asarray([
            force.sum(), (force * y).sum(), (force * x).sum(),
        ])
        correction = np.linalg.solve(
            _matrix(moments, x, y, area, ratio), target - internal
        )
        plane += correction
        if np.linalg.norm(correction) <= 1.0e-10 * max(1.0, np.linalg.norm(plane)):
            return plane
    raise AssertionError("independent cracked oracle did not converge")


def _oracle(inp):
    blocks, section, moduli, n_mult, locked = _folded(inp)
    del blocks
    x, y, area = section.bar_arrays()
    pre = np.zeros(3)
    if locked is not None:
        force = locked * area
        pre = np.asarray([force.sum(), (force * y).sum(), (force * x).sum()])
    long_target = np.asarray([
        inp["P_el_l"], -inp["Mx_el_l"], -inp["My_el_l"],
    ]) - pre
    long_plane = _oracle_cracked(section, long_target, inp["nl"] * n_mult)
    long_passive = inp["nl"] * n_mult * (
        long_plane[0] + long_plane[1] * x + long_plane[2] * y
    )
    neutral = long_passive * (1.0 - inp["ns"] / inp["nl"])
    neutral_force = neutral * area
    neutral_resultant = np.asarray([
        neutral_force.sum(), (neutral_force * y).sum(), (neutral_force * x).sum()
    ])
    total_target = np.asarray([
        inp["P_el_l"] + inp["P_el_s"],
        -(inp["Mx_el_l"] + inp["Mx_el_s"]),
        -(inp["My_el_l"] + inp["My_el_s"]),
    ]) - pre - neutral_resultant
    total_plane = _oracle_cracked(section, total_target, inp["ns"] * n_mult)
    rst1 = inp["ns"] * n_mult * (
        total_plane[0] + total_plane[1] * x + total_plane[2] * y
    )
    total_stress = neutral + rst1 + (np.zeros_like(rst1) if locked is None else locked)

    long_total = _oracle_uncracked(section, long_target, inp["nl"] * n_mult)
    long_external = _oracle_uncracked(
        section,
        np.asarray([inp["P_el_l"], -inp["Mx_el_l"], -inp["My_el_l"]]),
        inp["nl"] * n_mult,
    )
    short_external = _oracle_uncracked(
        section,
        np.asarray([inp["P_el_s"], -inp["Mx_el_s"], -inp["My_el_s"]]),
        inp["ns"] * n_mult,
    )
    vertices = section.concrete_vertices()
    evaluate = lambda plane: (
        plane[0] + plane[1] * vertices[:, 0] + plane[2] * vertices[:, 1]
    ) / 1000.0
    sig_lt = evaluate(long_total)
    sig_le = evaluate(long_external)
    sig_se = evaluate(short_external)
    fixed = sig_lt - sig_le
    path_factors = {}
    for name, external in (
        ("long", sig_le), ("total", sig_le + sig_se),
    ):
        loaded = external > (1.0e-9 if locked is not None else 0.0)
        candidates = np.full(len(vertices), math.inf)
        candidates[loaded] = np.maximum(
            0.0, (inp["sls_fctm"] - fixed[loaded]) / external[loaded]
        )
        path_factors[name] = float(candidates.min())
    path = "total" if path_factors["total"] < path_factors["long"] else "long"
    total_fibre_strain = (
        total_plane[0]
        + total_plane[1] * vertices[:, 0]
        + total_plane[2] * vertices[:, 1]
        + inp["el_phi"] * (
            long_plane[0]
            + long_plane[1] * vertices[:, 0]
            + long_plane[2] * vertices[:, 1]
        )
    ) / (inp["conc_Ec"] * 1000.0)
    return (
        long_plane,
        total_plane,
        total_stress / 1000.0,
        total_fibre_strain,
        path_factors[path],
    )


def _bundle(inp=None, out=None):
    inp = _mixed_input() if inp is None else inp
    out = _candidate_output(inp) if out is None else out
    return build_elastic_trace_family(
        inp, out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    )


def _step(bundle, step_id):
    return next(step for step in bundle.calculations[0].steps if step.step_id == step_id)


def test_mixed_response_matches_independent_oracle_and_full_contract():
    inp = _mixed_input()
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    long_plane, total_plane, total_stress, fibre_strain, factor = _oracle(inp)

    assert bundle.calculations[0].coverage_id == "ct-005"
    assert dict((axis.name, axis.value) for axis in bundle.calculations[0].axes)["sign"] == "tension-positive-n"
    assert _step(bundle, "ct-005-elastic-first-cracking-result").result.state == RESULT_FINITE
    for prefix, expected in (("long-cracked", long_plane), ("total-cracked", total_plane)):
        for component, value in zip(("q0", "qx", "qy"), expected):
            assert _step(bundle, f"{prefix}-plane-{component}").result.value == pytest.approx(value, rel=2e-9, abs=2e-8)
    for index, expected in enumerate(total_stress):
        kind = "bar" if index < 2 else "tendon"
        local = index if kind == "bar" else index - 2
        assert _step(bundle, f"element-{kind}-{local:04d}-total-stress").result.value == pytest.approx(expected, rel=2e-9)
    for index, expected in enumerate(fibre_strain):
        assert _step(bundle, f"response-fibre-{index:04d}-strain").result.value == pytest.approx(
            expected, rel=5.0e-9, abs=5.0e-11
        )

    blocks, section, moduli, _n_mult, _locked = _folded(inp)
    x, y, _area = section.bar_arrays()
    compatible = (
        total_plane[0] + total_plane[1] * x + total_plane[2] * y
        + inp["el_phi"] * (long_plane[0] + long_plane[1] * x + long_plane[2] * y)
    ) / (inp["conc_Ec"] * 1000.0)
    initial = np.asarray(
        [0.0] * len(blocks.bars)
        + [dict(material.values)["IS"] * 1000.0 for material in blocks.tendons]
    )
    np.testing.assert_allclose(
        total_stress / moduli * 1000.0,
        compatible + initial,
        rtol=2.0e-9,
        atol=2.0e-9,
    )
    assert _step(bundle, "governing-cracking-factor").result.value == pytest.approx(factor, rel=2e-9)
    for component in ("n", "mx", "my"):
        assert abs(_step(bundle, f"long-equilibrium-residual-{component}").result.value) < 1e-6
        assert abs(_step(bundle, f"total-equilibrium-residual-{component}").result.value) < 1e-6
    validate_elastic_trace_family(
        bundle, inp, out,
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA, context=CONTEXT,
    )


def test_nonfinite_plastic_only_actions_cannot_mask_ct005():
    baseline_input = _mixed_input()
    baseline_output = _candidate_output(baseline_input)
    baseline = _bundle(baseline_input, baseline_output).calculations[0]

    for key, value in (
        ("P_pl", math.nan),
        ("Mx_pl", math.inf),
        ("My_pl", -math.inf),
    ):
        inp = _mixed_input()
        out = _candidate_output(inp)
        inp[key] = value
        bundle = _bundle(inp, out)
        assert bundle.calculations[0] == baseline
        validate_elastic_trace_family(
            bundle, inp, out,
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA, context=CONTEXT,
        )


def test_genuine_no_finite_cracking_is_explicit_positive_infinity():
    section = Section.from_polygon(
        [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    )
    inp = {
        "section": section,
        "concrete": codes.EC2_2005.concrete(30.0),
        "concrete_preset": codes.EC2_2005.label,
        "P_el_l": -500.0, "Mx_el_l": 0.0, "My_el_l": 0.0,
        "P_el_s": 0.0, "Mx_el_s": 0.0, "My_el_s": 0.0,
        "conc_Ec": 33.0, "el_phi": 1.0, "sls_fctm": 2.9,
        "ns": REFERENCE_ES / 33_000.0,
        "nl": REFERENCE_ES * 2.0 / 33_000.0,
    }
    out = _candidate_output(inp)
    assert math.isinf(out["elastic"]["lambda_cr"])
    bundle = _bundle(inp, out)
    final = _step(bundle, "ct-005-elastic-first-cracking-result")
    assert final.result.state == RESULT_POSITIVE_INFINITY
    assert final.result.value is None
    assert _step(bundle, "governing-cracking-factor").result.state == RESULT_POSITIVE_INFINITY
    assert "Infinity" not in bundle_to_json(bundle)


def test_finite_no_prestress_linear_scaling_branch():
    section = Section.from_polygon(
        [(-0.20, -0.30), (0.20, -0.30), (0.20, 0.30), (-0.20, 0.30)],
        [(-0.14, -0.24, 500.0), (0.14, -0.24, 500.0)],
    )
    inp = {
        "section": section,
        "concrete": codes.EC2_2005.concrete(30.0),
        "steel": codes.EC2_2005.steel(500.0),
        "concrete_preset": codes.EC2_2005.label,
        "mild_preset": codes.EC2_2005.label,
        "P_el_l": 0.0, "Mx_el_l": 70.0, "My_el_l": 0.0,
        "P_el_s": 0.0, "Mx_el_s": 15.0, "My_el_s": 0.0,
        "conc_Ec": 33.0, "el_phi": 1.1, "sls_fctm": 2.9,
        "ns": REFERENCE_ES / 33_000.0,
        "nl": REFERENCE_ES * 2.1 / 33_000.0,
    }
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    factor = _step(bundle, "governing-cracking-factor")
    assert factor.result.state == RESULT_FINITE
    assert factor.result.value == pytest.approx(out["elastic"]["lambda_cr"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda out: out["elastic"].__setitem__("stress_plane", (99.0, 1.0, 2.0)),
        lambda out: out["elastic"]["total"].__setitem__(0, out["elastic"]["total"][0] + 4.0),
        lambda out: out["elastic"].__setitem__("max_conc_point", 99),
        lambda out: out["elastic"].__setitem__("lambda_cr", out["elastic"]["lambda_cr"] + 0.2),
        lambda out: out["elastic"]["concrete_corners"][0].__setitem__("strain_permille", 9.0),
        lambda out: out["elastic"]["props_un"].__setitem__("Ixy", 0.0),
    ],
)
def test_coherent_candidate_plane_stress_fibre_and_result_tamper_is_rejected(mutate):
    inp = _mixed_input()
    out = _candidate_output(inp)
    mutate(out)
    with pytest.raises(TraceValidationError):
        _bundle(inp, out)


def test_failure_trace_is_minimal_and_ignores_candidate_numerical_fields(monkeypatch):
    inp = _mixed_input()
    import sector.elastic_trace_replay as replay

    original = replay.solve_elastic_combined

    def failed(*args, **kwargs):
        return dataclasses.replace(original(*args, **kwargs), converged=False)

    monkeypatch.setattr(replay, "solve_elastic_combined", failed)
    minimal = {"elastic": {"converged": False}}
    fabricated = {
        "elastic": {
            "converged": False,
            "stress_plane": (9.0, 9.0, 9.0),
            "total": [1.0e99],
            "lambda_cr": 0.01,
        }
    }
    first = _bundle(inp, minimal)
    second = _bundle(inp, fabricated)
    assert first.to_dict() == second.to_dict()
    calculation = first.calculations[0]
    assert dict((axis.name, axis.value) for axis in calculation.axes)["branch"] == BRANCH_FAILED
    assert calculation.steps[-1].result.state == RESULT_FAILED
    assert not any("plane-q" in step.step_id or "total-stress" in step.step_id for step in calculation.steps)


def test_failure_cannot_be_promoted_and_finite_cannot_be_demoted(monkeypatch):
    inp = _mixed_input()
    out = _candidate_output(inp)
    out["elastic"]["converged"] = False
    with pytest.raises(TraceValidationError):
        _bundle(inp, out)

    import sector.elastic_trace_replay as replay
    original = replay.solve_elastic_combined
    monkeypatch.setattr(
        replay, "solve_elastic_combined",
        lambda *args, **kwargs: dataclasses.replace(
            original(*args, **kwargs), converged=False
        ),
    )
    with pytest.raises(TraceValidationError):
        _bundle(inp, {"elastic": {"converged": True}})


def test_nonfinite_input_is_rejected_and_nonfinite_intermediate_is_failed(monkeypatch):
    inp = _mixed_input()
    bad = dict(inp, P_el_s=math.inf)
    with pytest.raises(TraceValidationError):
        _bundle(bad, {"elastic": {"converged": False}})

    import sector.elastic_trace_replay as replay
    original = replay.solve_elastic_combined

    def nonfinite(*args, **kwargs):
        result = original(*args, **kwargs)
        broken = dataclasses.replace(result.short_term, eps0=math.nan)
        return dataclasses.replace(result, short_term=broken)

    monkeypatch.setattr(replay, "solve_elastic_combined", nonfinite)
    failed = _bundle(inp, {"elastic": {"converged": False}})
    assert failed.calculations[0].steps[-1].result.state == RESULT_FAILED


def _reseal_with_calculation(bundle, calculation):
    return seal_bundle(dataclasses.replace(bundle, calculations=(calculation,)))


@pytest.mark.parametrize("tamper", ["method", "axis", "order", "dependency", "unit", "value"])
def test_resealed_identity_graph_dimension_and_value_tamper_is_rejected(tamper):
    inp = _mixed_input()
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    calculation = bundle.calculations[0]
    steps = list(calculation.steps)
    if tamper == "method":
        calculation = dataclasses.replace(calculation, method_id="wrong-elastic-method")
    elif tamper == "axis":
        axes = list(calculation.axes)
        index = next(i for i, axis in enumerate(axes) if axis.name == "sign")
        axes[index] = TraceAxis("sign", "compression-positive-n")
        calculation = dataclasses.replace(calculation, axes=tuple(axes))
    elif tamper == "order":
        steps[-2], steps[-3] = steps[-3], steps[-2]
        calculation = dataclasses.replace(calculation, steps=tuple(steps))
    elif tamper == "dependency":
        index = next(i for i, step in enumerate(steps) if step.step_id == "elastic-response-evidence")
        steps[index] = dataclasses.replace(steps[index], dependencies=steps[index].dependencies[:-1])
        calculation = dataclasses.replace(calculation, steps=tuple(steps))
    elif tamper == "unit":
        index = next(i for i, step in enumerate(steps) if step.step_id == "maximum-concrete-compression")
        replacement = TraceUnit("kPa", "stress")
        old = steps[index]
        steps[index] = dataclasses.replace(old, unit=replacement)
        for j, step in enumerate(steps):
            dependencies = tuple(
                TraceDependency(dep.step_id, replacement if dep.step_id == old.step_id else dep.unit)
                for dep in step.dependencies
            )
            steps[j] = dataclasses.replace(step, dependencies=dependencies)
        calculation = dataclasses.replace(calculation, steps=tuple(steps))
    else:
        index = next(i for i, step in enumerate(steps) if step.step_id == "total-cracked-plane-q0")
        old = steps[index]
        steps[index] = dataclasses.replace(
            old,
            result=TraceResult(RESULT_FINITE, old.result.value + 1.0),
            substituted_expression=old.substituted_expression + " tampered",
        )
        calculation = dataclasses.replace(calculation, steps=tuple(steps))
    with pytest.raises(TraceValidationError):
        tampered = _reseal_with_calculation(bundle, calculation)
        validate_elastic_trace_family(
            tampered, inp, out,
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA, context=CONTEXT,
        )


def test_standard_project_and_same_kind_source_substitution_is_rejected():
    inp = _mixed_input()
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    calculation = bundle.calculations[0]
    standard_index = next(
        i for i, step in enumerate(calculation.steps)
        if step.quantity_role == ROLE_METHOD_VALUE and step.source.kind == SOURCE_STANDARD
    )
    project_index = next(
        i for i, step in enumerate(calculation.steps)
        if step.quantity_role == ROLE_METHOD_VALUE and step.source.kind == SOURCE_PROJECT
        and step.step_id != "reference-steel-modulus"
    )
    for replacement in (
        calculation.steps[project_index].source,
        TraceSource(
            SOURCE_STANDARD,
            calculation.steps[standard_index].source.method_id,
            calculation.steps[standard_index].source.edition,
            dataclasses.replace(
                calculation.steps[standard_index].source.citation,
                locator="swapped same-kind locator",
            ),
        ),
    ):
        steps = list(calculation.steps)
        steps[standard_index] = dataclasses.replace(steps[standard_index], source=replacement)
        tampered = _reseal_with_calculation(
            bundle, dataclasses.replace(calculation, steps=tuple(steps))
        )
        with pytest.raises(TraceValidationError):
            validate_elastic_trace_family(
                tampered, inp, out,
                input_sha256=INPUT_SHA, result_sha256=RESULT_SHA, context=CONTEXT,
            )


def test_missing_duplicate_unrelated_family_and_stale_seals_cannot_mask_ct005():
    inp = _mixed_input()
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    shape = trace_shape(
        section_trace_blocks(inp), CONTEXT, BRANCH_FINITE,
        out["elastic"]["cracked"],
    )
    registry = expected_registry(shape)
    calculation = bundle.calculations[0]
    unrelated = dataclasses.replace(
        calculation,
        calculation_id="elastic.unrelated.section-response-first-cracking",
        coverage_id="ct-004",
    )
    masked = create_bundle(
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        calculations=(unrelated,),
    )
    with pytest.raises(TraceValidationError):
        audit_trace_registry(masked, registry)
    duplicate = dataclasses.replace(
        calculation,
        calculation_id="elastic.duplicate.section-response-first-cracking",
    )
    extra = create_bundle(
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        calculations=(calculation, duplicate),
    )
    with pytest.raises(TraceValidationError):
        audit_trace_registry(extra, registry)
    with pytest.raises(TraceValidationError):
        validate_bundle(bundle, expected_input_sha256="e" * 64)
    with pytest.raises(TraceValidationError):
        validate_bundle(bundle, expected_result_sha256="f" * 64)


def test_all_used_input_geometry_material_and_provenance_leaves_reach_final():
    bundle = _bundle()
    calculation = bundle.calculations[0]
    by_id = {step.step_id: step for step in calculation.steps}
    reachable = {calculation.final_step_id}
    pending = [calculation.final_step_id]
    while pending:
        current = pending.pop()
        for dependency in by_id[current].dependencies:
            if dependency.step_id not in reachable:
                reachable.add(dependency.step_id)
                pending.append(dependency.step_id)
    leaves = {
        step.step_id for step in calculation.steps
        if not step.dependencies and (
            step.step_id.startswith("input-action-")
            or step.step_id.startswith("input-elastic-")
            or step.step_id.startswith("geometry-")
            or step.step_id.startswith("material-")
        )
    }
    assert leaves
    assert leaves <= reachable


def test_infinite_branch_cannot_be_replaced_by_large_finite_number():
    section = Section.from_polygon(
        [(-0.2, -0.2), (0.2, -0.2), (0.2, 0.2), (-0.2, 0.2)]
    )
    inp = {
        "section": section,
        "concrete": codes.EC2_2005.concrete(30.0),
        "P_el_l": -100.0, "Mx_el_l": 0.0, "My_el_l": 0.0,
        "P_el_s": 0.0, "Mx_el_s": 0.0, "My_el_s": 0.0,
        "conc_Ec": 33.0, "el_phi": 0.0, "sls_fctm": 2.9,
        "ns": REFERENCE_ES / 33_000.0, "nl": REFERENCE_ES / 33_000.0,
    }
    out = _candidate_output(inp)
    out["elastic"]["lambda_cr"] = 1.0e99
    with pytest.raises(TraceValidationError):
        _bundle(inp, out)
