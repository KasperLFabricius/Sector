"""CT-009 base crack-width oracle, contract, and adversarial tests."""

from __future__ import annotations

import copy
import dataclasses
import math

import numpy as np
import pytest

from app import material_catalog
from sector import bridge, codes
from sector.calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_UNDEFINED,
    TraceResult,
    TraceValidationError,
    seal_bundle,
)
from sector.crack_trace import (
    build_crack_trace_family,
    validate_crack_trace_family,
)
from sector.crack_trace_contract import CODE, DOCUMENT, SECOND_MOMENT
from sector.elastic import solve_elastic_combined, transformed_properties
from sector.materials import ES as REFERENCE_ES
from sector.section import Bar, Section
from sector.section_trace_blocks import section_trace_blocks
from sector.serviceability import (
    CrackWidthEvaluation,
    analyse_cracking,
    combined_cracking,
    evaluate_crack_width,
)
from sector.sls import crack_outputs


INPUT_SHA = "9" * 64
RESULT_SHA = "8" * 64
CONTEXT = {"case": "CT-009 base", "stage": 4}


@pytest.fixture(autouse=True)
def _isolate_autosave(monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct009-base-no-autosave")


def _element(identifier, x, y, diameter, material_id="M1"):
    return {
        "id": identifier,
        "kind": "bar",
        "x_mm": x,
        "y_mm": y,
        "diameter_mm": diameter,
        "material_id": material_id,
        "fatigue_detail_id": "",
    }


def _input(**changes):
    outer = [(0.0, 0.0), (0.30, 0.0), (0.30, 0.60), (0.0, 0.60)]
    bars = [
        (0.075, 0.05, 491.0),
        (0.150, 0.05, 491.0),
        (0.225, 0.05, 491.0),
    ]
    entry = material_catalog.default_entry(
        "mild", material_id="M1", preset=codes.EC2_2005.label
    )
    entry["name"] = "B500 crack reinforcement"
    entry["description"] = "Published ribbed reinforcement identity"
    steel = material_catalog.build_material(entry, "mild")
    ec = 33.0
    creep = 1.0
    inp = {
        "section": Section.from_polygon(outer, bars),
        "outer": outer,
        "holes": [],
        "bars": bars,
        "tendons": [],
        "concrete": codes.EC2_2005.concrete(30.0),
        "steel": steel,
        "prestress": None,
        "concrete_preset": codes.EC2_2005.label,
        "concrete_material_id": "C30-base",
        "mild_preset": codes.EC2_2005.label,
        "prestress_preset": codes.EC2_2005.label,
        "bar_elements": [
            _element("R1", 75.0, 50.0, 25.0),
            _element("R2", 150.0, 50.0, 25.0),
            _element("R3", 225.0, 50.0, 25.0),
        ],
        "tendon_elements": [],
        "bar_materials": [steel, steel, steel],
        "tendon_materials": None,
        "mild_material_catalog": {
            "version": 1, "next_id": 2, "items": [entry],
        },
        "prestress_material_catalog": material_catalog.default_catalog(
            "prestress"
        ),
        "P_pl": 0.0,
        "Mx_pl": 0.0,
        "My_pl": 0.0,
        "mode": "Elastic",
        "P_el_l": 0.0,
        "Mx_el_l": 150.0,
        "My_el_l": 0.0,
        "P_el_s": 0.0,
        "Mx_el_s": 30.0,
        "My_el_s": 0.0,
        "conc_Ec": ec,
        "el_phi": creep,
        "ns": REFERENCE_ES / (ec * 1000.0),
        "nl": REFERENCE_ES * (1.0 + creep) / (ec * 1000.0),
        "sls_fctm": 2.9,
        "sls_cw": True,
        "sls_phi": 25.0,
        "sls_k1": 0.8,
        "sls_tendon_xi": 0.0,
        "sls_code": CODE,
        "sls_edition": "2004",
        "sls_dk_na": False,
        "sls_member": "Beam",
    }
    inp.update(changes)
    return inp


def _tendon_input():
    inp = _input(sls_phi=0.0)
    tendon = (0.15, 0.08, 176.7)
    entry = material_catalog.default_entry(
        "prestress", material_id="P1", preset=codes.EC2_2005.label
    )
    entry["name"] = "Bonded tendon"
    entry["description"] = "Base-method prestress identity"
    law = material_catalog.build_material(entry, "prestress")
    inp.update(
        tendons=[tendon],
        section=Section.from_polygon(
            inp["outer"], inp["bars"], tendons_xy_area_mm2=[tendon]
        ),
        prestress=law,
        prestress_preset=codes.EC2_2005.label,
        tendon_elements=[{
            "id": "P1",
            "kind": "tendon",
            "x_mm": 150.0,
            "y_mm": 80.0,
            "diameter_mm": 15.0,
            "material_id": "P1",
            "fatigue_detail_id": "",
        }],
        tendon_materials=[law],
        prestress_material_catalog={
            "version": 1, "next_id": 2, "items": [entry],
        },
    )
    return inp


def _folded(inp):
    blocks = section_trace_blocks(inp)
    section = Section(
        [np.asarray(ring) for ring in blocks.geometry.rings],
        bars=[
            Bar(item.x, item.y, item.area)
            for item in (*blocks.geometry.bars, *blocks.geometry.tendons)
        ],
    )
    materials = (*blocks.bars, *blocks.tendons)
    moduli = np.asarray(
        [dict(item.values)["Es"] for item in materials], dtype=float
    )
    n_mult = moduli / REFERENCE_ES
    locked = None
    if blocks.tendons:
        locked = np.asarray(
            [0.0] * len(blocks.bars) + [
                dict(item.values)["Es"] * dict(item.values)["IS"] * 1000.0
                for item in blocks.tendons
            ]
        )
    return blocks, section, moduli, n_mult, locked


def _payload(result, blocks):
    if result is None:
        return None
    ids = [item.element_id for item in (*blocks.bars, *blocks.tendons)]
    n_bars = len(blocks.bars)

    def identity(index):
        if index < n_bars:
            return "Bar", index + 1, ids[index]
        return "Tendon", index - n_bars + 1, ids[index]

    def candidate(item):
        kind, number, identifier = identity(item.bar_index)
        return {
            "element_type": kind,
            "element_no": number,
            "element_id": identifier,
            "x_mm": item.x * 1000.0,
            "y_mm": item.y * 1000.0,
            "area_mm2": item.area,
            "wk": item.wk,
            "sr_max": item.sr_max,
            "esm_ecm": item.esm_ecm,
            "sigma_s": item.sigma_s,
            "rho_p_eff": item.rho_p_eff,
            "ac_eff": item.ac_eff,
            "hc_ef": item.hc_ef,
            "phi": item.phi,
            "cover": item.cover,
            "coarse": item.coarse,
            "edition": item.edition,
            "kw": item.kw,
            "k1_r": item.k1_r,
            "kfl": item.kfl,
            "sr_max_geometric": item.sr_max_geometric,
        }

    kind, number, identifier = identity(result.gov_bar)
    return {
        "wk": result.wk,
        "sr_max": result.sr_max,
        "esm_ecm": result.esm_ecm,
        "sigma_s": result.sigma_s,
        "rho_p_eff": result.rho_p_eff,
        "ac_eff": result.ac_eff,
        "hc_ef": result.hc_ef,
        "phi": result.phi,
        "cover": result.cover,
        "gov_bar": result.gov_bar + 1,
        "element_type": kind,
        "element_no": number,
        "element_id": identifier,
        "coarse": result.coarse,
        "edition": result.edition,
        "kw": result.kw,
        "k1_r": result.k1_r,
        "kfl": result.kfl,
        "sr_max_geometric": result.sr_max_geometric,
        "candidates": [candidate(item) for item in result.candidates],
    }


def _candidate(inp):
    """Independently reproduce the retained CT-009 app output subset."""

    blocks, section, moduli, n_mult, locked = _folded(inp)
    p_long, p_short = -inp["P_el_l"], -inp["P_el_s"]
    combined = solve_elastic_combined(
        section,
        p_long, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
        p_short, inp["Mx_el_s"], inp["My_el_s"], inp["ns"],
        n_mult=n_mult,
        prestress_stress=locked,
    )
    diameter = (
        inp["sls_phi"] if inp["sls_phi"] > 0.0
        else [item["diameter_mm"] for item in (
            inp["bar_elements"] + inp["tendon_elements"]
        )]
    )
    k1 = [inp["sls_k1"]] * len(blocks.bars) + [1.6] * len(blocks.tendons)
    long = analyse_cracking(
        section,
        p_long, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
        fctm=inp["sls_fctm"],
        Es=moduli,
        beta=0.5,
        kt=0.4,
        bar_diameter=diameter,
        k1=k1,
        edition="2004",
        n_mult=n_mult,
        prestress_stress=locked,
    )
    peak_cracked, peak_factor, peak_sigma = combined_cracking(
        section,
        p_long, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
        p_short, inp["Mx_el_s"], inp["My_el_s"], inp["ns"],
        fctm=inp["sls_fctm"],
        n_mult=n_mult,
        prestress_stress=locked,
    )
    if peak_factor < long.lambda_cr:
        cracked, factor, sigma_ct, governing = (
            peak_cracked, peak_factor, peak_sigma, combined.short_term
        )
    else:
        cracked, factor, sigma_ct, governing = (
            long.cracked, long.lambda_cr, long.sigma_ct, long.cracked_state
        )
    props_un = transformed_properties(
        section, inp["nl"], cracked=False, n_mult=n_mult
    )
    props_cr = (
        transformed_properties(
            section, inp["nl"], eps0=governing.eps0,
            kx=governing.kx, ky=governing.ky,
            cracked=True, n_mult=n_mult,
        ) if cracked else None
    )
    prop = lambda item: {
        "area": item.area,
        "cx": item.cx,
        "cy": item.cy,
        "Ix": item.Ix,
        "Iy": item.Iy,
        "Ixy": item.Ixy,
    }
    output = {
        "converged": (
            combined.converged
            and long.uncracked.converged
            and long.cracked_state.converged
        ),
        "cracked": cracked,
        "lambda_cr": factor,
        "sigma_ct": sigma_ct,
        "fctm": inp["sls_fctm"],
        "show_cw": inp["sls_cw"],
        "props_un": prop(props_un),
        "props_cr": prop(props_cr) if props_cr is not None else None,
        "crack": None,
        "crack_short": None,
    }
    if cracked:
        short_stress = np.asarray(combined.bar_stress_total)
        if locked is not None:
            short_stress = short_stress - locked
        short_state = dataclasses.replace(
            combined.short_term, bar_stress=short_stress
        )
        kinds = ["mild"] * len(blocks.bars) + ["prestress"] * len(blocks.tendons)

        def evaluate(state, ratio, kt):
            return evaluate_crack_width(
                section,
                state,
                ratio,
                fctm=inp["sls_fctm"],
                Es=moduli,
                kt=kt,
                bar_diameter=diameter,
                k1=k1,
                edition="2004",
                n_mult=n_mult,
                reinforcement_types=kinds,
            )

        long_eval = evaluate(long.cracked_state, inp["nl"], 0.4)
        short_eval = evaluate(short_state, inp["ns"], 0.6)
        assert isinstance(long_eval, CrackWidthEvaluation)
        output.update(
            crack=_payload(long_eval.result, blocks),
            crack_short=_payload(short_eval.result, blocks),
            crack_code=CODE,
            crack_edition="2004",
            crack_member=None,
        )
    output["crack_output"] = crack_outputs(
        {"Long-term": output["crack"], "Short-term": output["crack_short"]},
        valid=output["converged"],
    )
    return {"elastic": output}


def _bundle(inp=None, out=None):
    inp = _input() if inp is None else inp
    out = _candidate(inp) if out is None else out
    bundle = build_crack_trace_family(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    )
    assert bundle is not None
    return bundle


def _step(calculation, step_id):
    return next(item for item in calculation.steps if item.step_id == step_id)


def _reachable(calculation):
    dependencies = {
        item.step_id: tuple(dep.step_id for dep in item.dependencies)
        for item in calculation.steps
    }
    seen = set()
    pending = [calculation.final_step_id]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(dependencies[current])
    return seen


def test_base_trace_round_trip_order_registry_and_complete_leaf_closure():
    inp = _input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    assert len(bundle.calculations) == 3
    assert [dict((axis.name, axis.value) for axis in item.axes)["crack_case"]
            for item in bundle.calculations] == [
                "long-term", "short-term", "aggregate",
            ]
    for calculation in bundle.calculations:
        assert _reachable(calculation) == {
            item.step_id for item in calculation.steps
        }
    assert validate_crack_trace_family(
        bundle,
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    ) == bundle


def test_independent_formula_oracle_and_second_moment_units():
    inp = _input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    for calculation, output_key in zip(
        bundle.calculations[:2], ("crack", "crack_short")
    ):
        result = out["elastic"][output_key]
        assert result["wk"] == pytest.approx(
            result["sr_max"] * result["esm_ecm"], rel=1.0e-12
        )
        assert calculation.steps[-1].result.state == RESULT_FINITE
        assert calculation.steps[-1].result.value == pytest.approx(result["wk"])
    aggregate = bundle.calculations[-1]
    for name in ("ix", "iy", "ixy"):
        assert _step(aggregate, f"uncracked-property-{name}").unit == SECOND_MOMENT
        assert _step(aggregate, f"cracked-property-{name}").unit == SECOND_MOMENT


def test_actual_app_retained_base_payload_matches_independent_replay():
    from app.sector_app import _run_single_analysis

    inp = _input()
    out = _run_single_analysis(inp)
    bundle = _bundle(inp, out)
    assert bundle.calculations[0].steps[-1].result.value == pytest.approx(
        out["elastic"]["crack"]["wk"]
    )
    assert validate_crack_trace_family(
        bundle,
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    ) == bundle


def test_actual_app_prestress_payload_keeps_tendon_identity_and_load_stress():
    from app.sector_app import _run_single_analysis

    inp = _tendon_input()
    out = _run_single_analysis(inp)
    bundle = _bundle(inp, out)
    candidates = (
        out["elastic"]["crack"]["candidates"]
        + out["elastic"]["crack_short"]["candidates"]
    )
    assert any(item["element_type"] == "Tendon" for item in candidates)
    assert any(item["element_id"] == "P1" for item in candidates)
    assert validate_crack_trace_family(
        bundle,
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    ) == bundle


def test_every_standard_step_cites_only_selected_en_1992_1_1_document():
    bundle = _bundle()
    standard_steps = [
        step for calculation in bundle.calculations for step in calculation.steps
        if step.source.kind == "standard"
    ]
    assert standard_steps
    assert {step.source.citation.document for step in standard_steps} == {DOCUMENT}
    assert all("1992-2" not in step.source.citation.document
               for step in standard_steps)
    assert all("DK" not in step.source.method_id for step in standard_steps)


def test_complete_geometry_material_catalogue_and_concrete_identity_is_sealed():
    first = _input(concrete_material_id="same-law-C1")
    first_bundle = _bundle(first, _candidate(first))
    second = _input(concrete_material_id="same-law-C2")
    second_bundle = _bundle(second, _candidate(second))
    assert first_bundle.content_sha256 != second_bundle.content_sha256

    described = _input()
    described["mild_material_catalog"] = copy.deepcopy(
        described["mild_material_catalog"]
    )
    described["mild_material_catalog"]["items"][0]["description"] = (
        "Changed published catalogue description"
    )
    assert _bundle(described, _candidate(described)).content_sha256 != (
        _bundle().content_sha256
    )


def test_fatigue_assignment_value_is_inert_but_presence_position_and_type_are_pinned():
    baseline = _input()
    baseline_bundle = _bundle(baseline, _candidate(baseline))
    changed = _input()
    changed["bar_elements"][0]["fatigue_detail_id"] = "D-irrelevant"
    assert _bundle(changed, _candidate(changed)) == baseline_bundle

    wrong_type = _input()
    wrong_type["bar_elements"][0]["fatigue_detail_id"] = []
    with pytest.raises(TraceValidationError, match="retain text type"):
        _bundle(wrong_type, _candidate(wrong_type))

    missing = _input()
    missing["bar_elements"][0].pop("fatigue_detail_id")
    with pytest.raises(TraceValidationError, match="retain fatigue_detail_id"):
        _bundle(missing, _candidate(missing))

    reordered = _input()
    record = reordered["bar_elements"][0]
    reordered["bar_elements"][0] = {
        "fatigue_detail_id": record["fatigue_detail_id"],
        **{key: value for key, value in record.items()
           if key != "fatigue_detail_id"},
    }
    assert _bundle(reordered, _candidate(reordered)).content_sha256 != (
        baseline_bundle.content_sha256
    )


def test_dk_member_and_2023_tendon_ratio_values_are_inert_but_types_are_pinned():
    baseline = _input()
    expected = _bundle(baseline, _candidate(baseline))
    changed = _input(sls_member="Slab", sls_tendon_xi=float("nan"))
    assert _bundle(changed, _candidate(changed)) == expected

    wrong_member = _input(sls_member=[])
    with pytest.raises(TraceValidationError, match="sls_member must be text"):
        _bundle(wrong_member, _candidate(_input()))
    wrong_ratio = _input(sls_tendon_xi=[])
    with pytest.raises(TraceValidationError, match="excluded sibling"):
        _bundle(wrong_ratio, _candidate(_input()))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["elastic"]["props_un"].__setitem__("Ix", 9.0),
        lambda value: value["elastic"]["crack"].__setitem__(
            "gov_bar",
            value["elastic"]["crack"]["gov_bar"] % len(
                value["elastic"]["crack"]["candidates"]
            ) + 1,
        ),
        lambda value: value["elastic"]["crack"]["candidates"][0].__setitem__(
            "sr_max", 999.0
        ),
        lambda value: value["elastic"]["crack_output"].__setitem__(
            "governing", "forged"
        ),
    ],
)
def test_candidate_property_selector_candidate_and_aggregate_tamper_is_rejected(
    mutate,
):
    inp = _input()
    out = _candidate(inp)
    mutate(out)
    with pytest.raises(TraceValidationError, match="authoritative replay"):
        _bundle(inp, out)


def test_retained_output_reordering_and_type_replacement_is_rejected():
    inp = _input()
    out = _candidate(inp)
    elastic = out["elastic"]
    out["elastic"] = {key: elastic[key] for key in reversed(tuple(elastic))}
    with pytest.raises(TraceValidationError, match="inventory/order"):
        _bundle(inp, out)

    out = _candidate(inp)
    out["elastic"]["props_un"] = list(out["elastic"]["props_un"].values())
    with pytest.raises(TraceValidationError, match="authoritative replay"):
        _bundle(inp, out)


@pytest.mark.parametrize(
    "extra",
    [
        ("crack_coarse", None),
        ("crack_short_coarse", None),
        ("crack_forged", {}),
        ("props_forged", {}),
    ],
)
def test_stale_or_unknown_owned_output_siblings_are_rejected(extra):
    inp = _input()
    out = _candidate(inp)
    out["elastic"][extra[0]] = extra[1]
    with pytest.raises(TraceValidationError, match="inventory/order"):
        _bundle(inp, out)


def test_coherently_resealed_trace_tamper_is_rejected():
    inp = _input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    first = bundle.calculations[0]
    step = first.steps[0]
    changed_step = dataclasses.replace(
        step,
        result=TraceResult(RESULT_FINITE, step.result.value + 1.0),
    )
    changed_calculation = dataclasses.replace(
        first, steps=(changed_step, *first.steps[1:])
    )
    changed = seal_bundle(dataclasses.replace(
        bundle,
        calculations=(changed_calculation, *bundle.calculations[1:]),
        content_sha256="",
    ))
    with pytest.raises(TraceValidationError, match="authoritative input replay"):
        validate_crack_trace_family(
            changed,
            inp,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context=CONTEXT,
        )


@pytest.mark.parametrize(
    "code,edition,dk",
    [
        ("DS/EN 1992-1-1 + DK NA", "2004", True),
        ("EN 1992-1-1:2023", "2023", False),
        (bridge.EN1992_2_BASE, "2004", False),
        (bridge.EN1992_2_DK_NA, "2004", True),
    ],
)
def test_dk_2023_and_bridge_selectors_are_explicitly_outside_base_slice(
    code, edition, dk,
):
    inp = _input(sls_code=code, sls_edition=edition, sls_dk_na=dk)
    assert build_crack_trace_family(
        inp,
        _candidate(_input()),
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    ) is None


def test_base_selector_flag_mismatch_is_rejected():
    inp = _input(sls_dk_na=True)
    with pytest.raises(TraceValidationError, match="dk_na=false"):
        build_crack_trace_family(
            inp,
            _candidate(_input()),
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )


def test_uncracked_branch_publishes_no_fabricated_width_or_verdict():
    inp = _input(Mx_el_l=1.0, Mx_el_s=0.0)
    out = _candidate(inp)
    assert out["elastic"]["cracked"] is False
    assert out["elastic"]["crack"] is None
    bundle = _bundle(inp, out)
    assert all(
        calculation.steps[-1].result.state == RESULT_UNDEFINED
        for calculation in bundle.calculations
    )
    assert all(
        calculation.steps[-1].result.value is None
        for calculation in bundle.calculations
    )
    assert not any(
        "util" in step.step_id or "verdict" in step.step_id
        for calculation in bundle.calculations for step in calculation.steps
    )


def test_failed_solver_trace_is_minimal_and_failure_numerics_are_inert(monkeypatch):
    inp = _input()
    import sector.crack_trace as trace

    original = trace.solve_elastic_combined

    def failed(*args, **kwargs):
        return dataclasses.replace(original(*args, **kwargs), converged=False)

    monkeypatch.setattr(trace, "solve_elastic_combined", failed)
    first_out = {
        "elastic": {
            "converged": False,
            "crack_output": {
                "value": None,
                "case": None,
                "governing": None,
                "unit": "mm",
                "calculation_state": "INVALID",
            },
        }
    }
    second_out = copy.deepcopy(first_out)
    second_out["elastic"]["forged_numerical"] = 1.0e99
    first = _bundle(inp, first_out)
    second = _bundle(inp, second_out)
    assert first.calculations[0].steps[-1].result.state == RESULT_FAILED
    assert first.calculations[0].steps[-1].result.value is None
    assert first.content_sha256 != second.content_sha256
    assert len(first.calculations) == 1
    assert not any(
        "property" in step.step_id or "candidate" in step.step_id
        for step in first.calculations[0].steps
    )


def test_active_result_and_failure_aggregate_cannot_be_deleted(monkeypatch):
    inp = _input()
    with pytest.raises(TraceValidationError, match="missing.*elastic output"):
        build_crack_trace_family(
            inp,
            {},
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )
    with pytest.raises(TraceValidationError, match="missing.*elastic output"):
        validate_crack_trace_family(
            None,
            inp,
            {},
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
        )

    import sector.crack_trace as trace
    original = trace.solve_elastic_combined

    def failed(*args, **kwargs):
        return dataclasses.replace(original(*args, **kwargs), converged=False)

    monkeypatch.setattr(trace, "solve_elastic_combined", failed)
    with pytest.raises(TraceValidationError, match="requires retained INVALID"):
        _bundle(inp, {"elastic": {"converged": False}})


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("value"),
        lambda value: value.__setitem__("value", 0.0),
        lambda value: value.__setitem__("case", "forged"),
        lambda value: value.__setitem__("governing", "forged"),
        lambda value: value.__setitem__("unit", "m"),
        lambda value: value.__setitem__("calculation_state", "CALCULATED"),
        lambda value: value.update(extra=None),
        lambda value: value.__setitem__("value", value.pop("value")),
    ],
)
def test_failed_aggregate_exact_inventory_values_and_types_are_pinned(
    monkeypatch, mutate,
):
    inp = _input()
    import sector.crack_trace as trace
    original = trace.solve_elastic_combined

    def failed(*args, **kwargs):
        return dataclasses.replace(original(*args, **kwargs), converged=False)

    monkeypatch.setattr(trace, "solve_elastic_combined", failed)
    aggregate = {
        "value": None,
        "case": None,
        "governing": None,
        "unit": "mm",
        "calculation_state": "INVALID",
    }
    mutate(aggregate)
    with pytest.raises(TraceValidationError, match="crack_output"):
        _bundle(inp, {"elastic": {
            "converged": False,
            "crack_output": aggregate,
        }})


def test_missing_and_non_boolean_dispatch_controls_are_rejected():
    for key in ("sls_cw", "sls_dk_na"):
        missing = _input()
        del missing[key]
        with pytest.raises(TraceValidationError, match=f"requires {key}"):
            build_crack_trace_family(
                missing,
                _candidate(_input()),
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )
        wrong = _input()
        wrong[key] = 1
        with pytest.raises(TraceValidationError, match="exact built-in Boolean"):
            build_crack_trace_family(
                wrong,
                _candidate(_input()),
                input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA,
            )


def test_positive_custom_area_keeps_exact_section_conversion_path():
    inp = _input()
    inp["bars"][0] = (0.075, 0.05, 0.1)
    inp["section"] = Section.from_polygon(inp["outer"], inp["bars"])
    inp["bar_elements"][0]["diameter_mm"] = math.sqrt(4.0 * 0.1 / math.pi)
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    assert bundle is not None
    retained = out["elastic"]["crack"]["candidates"]
    if any(item["element_id"] == "R1" for item in retained):
        item = next(value for value in retained if value["element_id"] == "R1")
        assert item["area_mm2"] == inp["section"].bar_arrays()[2][0] * 1.0e6
