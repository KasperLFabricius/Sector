"""CT-009 crack-width trace: closed-form oracles, inventory, identity, graph.

The oracle tests are independent of the traced kernels: the cracked neutral
axis, steel stress, effective area, (7.9)/(7.11)/(7.14) and the DK NA
variants are recomputed with plain closed forms for rectangles and compared
against the sealed steps and the published crack surfaces.
"""

from __future__ import annotations

import copy
import dataclasses
import math
from collections.abc import Mapping

import numpy as np
import pytest

from app.sector_app import _crack_dict as app_crack_dict
from app.sector_app import run_analysis
from sector import codes
from sector import sls as sls_core
from sector.calculation_trace import (
    RESULT_FINITE, RESULT_NEGATIVE_INFINITY, RESULT_POSITIVE_INFINITY,
    RESULT_UNDEFINED, ROLE_COMPUTED, ROLE_FINAL, ROLE_USER_INPUT, TraceAxis,
    TraceDependency, TraceResult, TraceUnit, TraceValidationError,
    bundle_to_json, seal_bundle, trace_identity_token,
)
from sector.codes import fctm
from sector.crack_trace import (
    _calculation, build_crack_trace_family, validate_crack_trace_family,
)
from sector.crack_trace_contract import (
    ADAPTER_SOURCE, CASE_LABELS_DK, COVERAGE_ID, CRACK_STATE_CODES, FAMILY_ID,
    INPUT_SOURCE, METHOD_ID, MM, ONE, REGISTRY_ID, case_label_token,
)
from sector.elastic import solve_elastic_combined
from sector.materials import Prestress
from sector.section import Bar, Section
from sector.section_trace_blocks import section_trace_blocks
from sector.serviceability import analyse_cracking, combined_cracking, crack_width


INPUT_SHA, RESULT_SHA = "a" * 64, "b" * 64
CONTEXT = {"case": "CT-009 crack"}
REFERENCE_ES = 200_000.0
ES = 200_000.0
FCT = fctm(30.0)
# Rectangular anchor beam: 0.3 x 0.6 m, 3 x 491 mm2 at y = 0.05 (d = 0.55).
B, H, D_EFF = 0.3, 0.6, 0.55
AS_TOTAL = 3.0 * 491.0e-6
COVER = 37.5  # auto clear cover: 50 mm to centre - 25/2 mm radius
K2, K3, K4 = 0.5, 3.4, 0.425


@pytest.fixture(autouse=True)
def _isolate_autosave(monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct009-crack-no-autosave")


def _beam_section():
    return Section.from_polygon(
        corners=[(0.0, 0.0), (B, 0.0), (B, H), (0.0, H)],
        bars_xy_area_mm2=[(0.075, 0.05, 491.0), (0.15, 0.05, 491.0),
                          (0.225, 0.05, 491.0)],
    )


def _beam_input(**over):
    inp = {
        "mode": "Elastic",
        "section": _beam_section(),
        "concrete": codes.EC2_2005.concrete(30.0),
        "steel": codes.EC2_2005.steel(500.0),
        "concrete_preset": codes.EC2_2005.label,
        "mild_preset": codes.EC2_2005.label,
        "bar_elements": [
            {"id": "B-1", "material_id": "B500", "diameter_mm": 25.0},
            {"id": "B-2", "material_id": "B500", "diameter_mm": 25.0},
            {"id": "B-3", "material_id": "B500", "diameter_mm": 25.0},
        ],
        "P_el_l": 0.0, "Mx_el_l": 150.0, "My_el_l": 0.0,
        "P_el_s": 0.0, "Mx_el_s": 30.0, "My_el_s": 0.0,
        "nl": 6.0, "ns": 6.0,
        "sls_fctm": FCT, "sls_cw": True, "sls_phi": 0.0, "sls_k1": 0.8,
        "sls_code": "EN 1992-1-1:2005", "sls_dk_na": False,
        "sls_edition": "2004", "sls_member": "Beam", "sls_tendon_xi": 0.0,
    }
    inp.update(over)
    return inp


def _folded(inp):
    scoped = {key: value for key, value in inp.items()
              if key not in ("P_pl", "Mx_pl", "My_pl")}
    blocks = section_trace_blocks(scoped)
    section = Section(
        [np.asarray(ring) for ring in blocks.geometry.rings],
        bars=[Bar(item.x, item.y, item.area)
              for item in (*blocks.geometry.bars, *blocks.geometry.tendons)],
    )
    moduli = np.asarray([dict(item.values)["Es"]
                         for item in (*blocks.bars, *blocks.tendons)],
                        dtype=float)
    n_mult = moduli / REFERENCE_ES if moduli.size else None
    locked = (np.asarray(
        [0.0] * len(blocks.bars)
        + [dict(item.values)["Es"] * dict(item.values)["IS"] * 1000.0
           for item in blocks.tendons]) if blocks.tendons else None)
    return blocks, section, moduli, n_mult, locked


def _candidate_output(inp, *, converged_override=None):
    """Reproduce the retained app crack publication, independently of CT-009."""

    blocks, section, moduli, n_mult, locked = _folded(inp)
    nb, nt = len(blocks.bars), len(blocks.tendons)
    p_l, p_s = -inp["P_el_l"], -inp["P_el_s"]
    r = solve_elastic_combined(
        section, p_l, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
        p_s, inp["Mx_el_s"], inp["My_el_s"], inp["ns"],
        n_mult=n_mult, prestress_stress=locked)
    dk = inp["sls_dk_na"]
    include_hx = (not dk) or inp["sls_member"] == "Slab" or bool(nt)
    if inp["sls_phi"] > 0.0:
        phi = inp["sls_phi"]
    else:
        phi = [item["diameter_mm"]
               for item in (list(inp.get("bar_elements", []))
                            + list(inp.get("tendon_elements", [])))]
    k1_bars = [inp["sls_k1"]] * nb + [1.6] * nt
    cr_l = analyse_cracking(
        section, p_l, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
        fctm=inp["sls_fctm"], Es=list(moduli), beta=0.5, kt=0.4,
        bar_diameter=phi, k1=k1_bars, k3_cover_dependent=dk,
        include_hx_term=include_hx, edition=inp["sls_edition"],
        n_mult=n_mult, prestress_stress=locked)
    converged = (r.converged and cr_l.uncracked.converged
                 and cr_l.cracked_state.converged)
    if converged_override is not None:
        converged = converged_override
    crk_t, lam_t, sig_t = combined_cracking(
        section, p_l, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
        p_s, inp["Mx_el_s"], inp["My_el_s"], inp["ns"],
        fctm=inp["sls_fctm"], n_mult=n_mult, prestress_stress=locked)
    if lam_t < cr_l.lambda_cr:
        cracked, lam, sig = crk_t, lam_t, sig_t
    else:
        cracked, lam, sig = cr_l.cracked, cr_l.lambda_cr, cr_l.sigma_ct
    bar_ids = [item["id"] for item in inp.get("bar_elements", [])]
    tendon_ids = [item["id"] for item in inp.get("tendon_elements", [])]
    elastic = dict(
        total=[s / 1000.0 for s in r.bar_stress_total],
        converged=converged,
        stress_plane=(r.short_term.eps0, r.short_term.kx, r.short_term.ky),
        cracked=cracked, lambda_cr=lam, sigma_ct=sig,
        fctm=inp["sls_fctm"], show_cw=inp["sls_cw"],
        crack=None, crack_short=None,
    )
    if inp["sls_cw"] and cracked:
        cw_stress = np.asarray(r.bar_stress_total, dtype=float)
        if locked is not None:
            cw_stress = cw_stress - locked
        short_state = dataclasses.replace(r.short_term, bar_stress=cw_stress)
        types = ["mild"] * nb + ["prestress"] * nt
        xi = float(inp.get("sls_tendon_xi", 0.0))
        tendon_xi = None if not nt or xi <= 0.0 else [1.0] * nb + [xi] * nt

        def _cw(state, n, kt, coarse):
            return crack_width(
                section, state, n, fctm=inp["sls_fctm"], Es=list(moduli),
                kt=kt, bar_diameter=phi, k1=k1_bars, k3_cover_dependent=dk,
                include_hx_term=include_hx, coarse=coarse,
                edition=inp["sls_edition"], n_mult=n_mult,
                reinforcement_types=types, bond_ratio_xi=tendon_xi)

        elastic.update(
            crack=app_crack_dict(
                _cw(cr_l.cracked_state, inp["nl"], 0.4, False),
                bar_ids, tendon_ids),
            crack_short=app_crack_dict(
                _cw(short_state, inp["ns"], 0.6, False), bar_ids, tendon_ids),
            crack_code=inp["sls_code"], crack_edition=inp["sls_edition"],
            crack_member=(inp["sls_member"] if dk else None),
        )
        if dk:
            elastic.update(
                crack_coarse=app_crack_dict(
                    _cw(cr_l.cracked_state, inp["nl"], 0.4, True),
                    bar_ids, tendon_ids),
                crack_short_coarse=app_crack_dict(
                    _cw(short_state, inp["ns"], 0.6, True),
                    bar_ids, tendon_ids),
            )
    if (elastic.get("crack_coarse") is not None
            or elastic.get("crack_short_coarse") is not None):
        crack_cases = {
            "Long-term (fine)": elastic.get("crack"),
            "Short-term (fine)": elastic.get("crack_short"),
            "Long-term (coarse)": elastic.get("crack_coarse"),
            "Short-term (coarse)": elastic.get("crack_short_coarse"),
        }
    else:
        crack_cases = {
            "Long-term": elastic.get("crack"),
            "Short-term": elastic.get("crack_short"),
        }
    elastic["crack_output"] = sls_core.crack_outputs(
        crack_cases, valid=converged)
    return {"elastic": elastic}


def _build(inp, out):
    return build_crack_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT)


def _bundle(inp, out=None):
    bundle = _build(inp, _candidate_output(inp) if out is None else out)
    assert bundle is not None
    return bundle


def _validate(bundle, inp, out):
    return validate_crack_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT)


def _member_steps(bundle, suffix):
    for calculation in bundle.calculations:
        if calculation.calculation_id.endswith(suffix):
            return {step.step_id: step for step in calculation.steps}
    raise AssertionError(f"member {suffix} not published")


# ---- independent closed forms for rectangles in pure sagging ---------------

def _cracked_depth(b, d, n_as):
    """Stage II neutral-axis depth for a singly reinforced rectangle."""

    return (-n_as + math.sqrt(n_as * n_as + 2.0 * b * n_as * d)) / b


def _beam_oracle(moment, *, kt, dk=False, coarse=False, include_hx=True):
    """Closed-form (7.8)-(7.14) + DK NA crack width for the anchor beam."""

    x = _cracked_depth(B, D_EFF, 6.0 * AS_TOTAL)
    z = D_EFF - x / 3.0
    sigma = moment / (AS_TOTAL * z) / 1000.0  # MPa
    if coarse:
        hc = 2.0 * (H - D_EFF)  # centroid-matched band (figure 7.100 NA)
    else:
        terms = [2.5 * (H - D_EFF), H / 2.0]
        if include_hx:
            terms.append((H - x) / 3.0)
        hc = min(terms)
    ac = B * hc
    rho = AS_TOTAL / ac
    k3 = K3 * (25.0 / COVER) ** (2.0 / 3.0) if dk else K3
    sr = k3 * COVER + 0.8 * K2 * K4 * 25.0 / rho
    esm = max((sigma - kt * FCT / rho * (1.0 + 6.0 * rho)) / ES,
              0.6 * sigma / ES)
    wk = (0.5 if coarse else 1.0) * sr * esm
    return dict(x=x, sigma=sigma, hc=hc, ac=ac, rho=rho, sr=sr, esm=esm, wk=wk)


# ---- oracle tests -----------------------------------------------------------

def test_long_term_79_711_closed_form_and_total_binding():
    inp = _beam_input()
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    steps = _member_steps(bundle, "-long-term")
    oracle = _beam_oracle(150.0, kt=0.4)

    assert steps["fine-hc-ef"].result.value == pytest.approx(oracle["hc"])
    assert steps["fine-ac-eff"].result.value == pytest.approx(oracle["ac"])
    assert steps["fine-rho-p-eff"].result.value == pytest.approx(oracle["rho"])
    assert steps["fine-candidate-00-sigma-s"].result.value == pytest.approx(
        oracle["sigma"], rel=1e-4)
    assert steps["fine-candidate-00-cover"].result.value == pytest.approx(
        COVER, abs=1e-6)
    assert steps["fine-candidate-00-sr-max"].result.value == pytest.approx(
        oracle["sr"], rel=1e-6)
    assert steps["fine-candidate-00-esm-ecm"].result.value == pytest.approx(
        oracle["esm"], rel=1e-4)
    assert steps["fine-wk"].result.value == pytest.approx(
        oracle["wk"], rel=1e-4)
    # The published anchor value (worked hand calculation, 0.1975 mm).
    assert steps["fine-wk"].result.value == pytest.approx(0.1975, rel=0.02)
    # Total operand binding: every candidate, not only the governing one.
    crack = out["elastic"]["crack"]
    assert crack["wk"] == steps["fine-wk"].result.value
    # All three bars sit at the same depth; the governing one is a numerical
    # tie broken by the retained sort, and the identity binding must agree.
    assert crack["element_id"] == f"B-{crack['gov_bar']}"
    assert steps["fine-governing"].result.value == float(crack["gov_bar"] - 1)
    assert len(crack["candidates"]) == 3
    for candidate in crack["candidates"]:
        index = candidate["element_no"] - 1
        prefix = f"fine-candidate-{index:02d}"
        assert steps[f"{prefix}-wk"].result.value == candidate["wk"]
        assert steps[f"{prefix}-sigma-s"].result.value == candidate["sigma_s"]
        assert steps[f"{prefix}-sr-max"].result.value == candidate["sr_max"]
        assert steps[f"{prefix}-esm-ecm"].result.value == candidate["esm_ecm"]
        assert steps[f"{prefix}-cover"].result.value == candidate["cover"]
    assert steps["ct-009-long-term-result"].result.value == 1.0
    assert steps["ct-009-long-term-result"].result.state == RESULT_FINITE
    assert _validate(bundle, inp, out) is not None


def test_short_term_kt06_governing_max_wk_and_output_rule():
    inp = _beam_input()
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    steps = _member_steps(bundle, "-short-term")
    oracle = _beam_oracle(180.0, kt=0.6)  # nl == ns: total = one 180 solve
    assert steps["fine-candidate-00-sigma-s"].result.value == pytest.approx(
        oracle["sigma"], rel=1e-4)
    assert steps["fine-candidate-00-esm-ecm"].result.value == pytest.approx(
        oracle["esm"], rel=1e-4)
    assert steps["fine-wk"].result.value == pytest.approx(
        oracle["wk"], rel=1e-4)
    # The short-term case (larger total action) governs the crack output.
    output = out["elastic"]["crack_output"]
    assert output["case"] == "Short-term"
    assert output["value"] == max(out["elastic"]["crack"]["wk"],
                                  out["elastic"]["crack_short"]["wk"])
    assert output["governing"] == out["elastic"]["crack_short"]["element_id"]
    assert output["unit"] == "mm"
    assert output["calculation_state"] == "CALCULATED"
    ost = _member_steps(bundle, "-crack-output")
    short_token = case_label_token("Short-term")
    long_token = case_label_token("Long-term")
    assert set(ost) == {
        "input-cw-enabled", "input-dk-na", "upstream-converged",
        f"case-{long_token}-available", f"case-{long_token}-wk",
        f"case-{short_token}-available", f"case-{short_token}-wk",
        "governing-case", "ct-009-crack-output-result",
    }
    assert ost["governing-case"].result.value == 1.0
    assert ost[f"case-{short_token}-wk"].result.value == output["value"]
    assert ost["ct-009-crack-output-result"].result.value == (
        CRACK_STATE_CODES["CALCULATED"])


def test_mean_strain_floor_governs_close_to_cracking():
    inp = _beam_input(Mx_el_l=62.0, Mx_el_s=0.0)
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    steps = _member_steps(bundle, "-long-term")
    oracle = _beam_oracle(62.0, kt=0.4)
    sigma = steps["fine-candidate-00-sigma-s"].result.value
    assert sigma == pytest.approx(oracle["sigma"], rel=1e-4)
    # The (7.9) main term is below the 0.6 sigma_s/Es floor here.
    assert (sigma - 0.4 * FCT / oracle["rho"] * (1.0 + 6.0 * oracle["rho"])
            ) / ES < 0.6 * sigma / ES
    assert steps["fine-candidate-00-esm-ecm"].result.value == pytest.approx(
        0.6 * sigma / ES, rel=1e-12)
    assert _validate(bundle, inp, out) is not None


def test_dk_na_k3_coarse_halving_and_4_case_table():
    inp = _beam_input(sls_dk_na=True, sls_code="DS/EN 1992-1-1 + DK NA",
                      sls_member="Beam")
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    steps = _member_steps(bundle, "-long-term")
    fine = _beam_oracle(150.0, kt=0.4, dk=True, include_hx=False)
    coarse = _beam_oracle(150.0, kt=0.4, dk=True, coarse=True)
    # DK NA 7.3.4(3): k3 (25/c)^(2/3) narrows the fine spacing.
    assert steps["fine-candidate-00-sr-max"].result.value == pytest.approx(
        fine["sr"], rel=1e-6)
    assert fine["sr"] < _beam_oracle(150.0, kt=0.4)["sr"]
    # DK NA 7.3.4(1) coarse system: centroid-matched band and wk/2.
    assert steps["coarse-hc-ef"].result.value == pytest.approx(0.10, abs=1e-9)
    assert steps["coarse-ac-eff"].result.value == pytest.approx(0.03, rel=1e-9)
    assert steps["coarse-rho-p-eff"].result.value == pytest.approx(
        coarse["rho"], rel=1e-9)
    assert steps["coarse-wk"].result.value == pytest.approx(
        coarse["wk"], rel=1e-4)
    assert steps["coarse-wk"].result.value == pytest.approx(
        0.5 * out["elastic"]["crack_coarse"]["sr_max"]
        * out["elastic"]["crack_coarse"]["esm_ecm"], rel=1e-12)
    assert out["elastic"]["crack_coarse"]["coarse"] is True
    # Four retained cases with the exact labels, in order.
    output = out["elastic"]["crack_output"]
    assert output["case"] in CASE_LABELS_DK
    ost = _member_steps(bundle, "-crack-output")
    for label in CASE_LABELS_DK:
        assert f"case-{case_label_token(label)}-available" in ost
    wks = {label: out["elastic"][key]["wk"] for label, key in zip(
        CASE_LABELS_DK,
        ("crack", "crack_short", "crack_coarse", "crack_short_coarse"))}
    assert output["value"] == max(wks.values())
    assert wks[output["case"]] == output["value"]
    assert _validate(bundle, inp, out) is not None
    # The DK member surfaces must exist, even where their value is null.
    for key in ("crack_coarse", "crack_short_coarse", "crack_member"):
        missing = copy.deepcopy(out)
        del missing["elastic"][key]
        with pytest.raises(TraceValidationError):
            _build(inp, missing)


def test_dk_na_hx_drop_is_member_type_dependent():
    def deep_input(member):
        section = Section.from_polygon(
            corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 1.0), (0.0, 1.0)],
            bars_xy_area_mm2=[(0.15, 0.2, 1500.0)],
        )
        return _beam_input(
            section=section,
            bar_elements=[{"id": "B-1", "material_id": "B500",
                           "diameter_mm": 25.0}],
            Mx_el_l=300.0, Mx_el_s=0.0, sls_dk_na=True,
            sls_code="DS/EN 1992-1-1 + DK NA", sls_member=member)

    x = _cracked_depth(0.3, 0.8, 6.0 * 1500.0e-6)
    beam = _member_steps(_bundle(deep_input("Beam")), "-long-term")
    # Beam: (h-x)/3 dropped (DK NA 7.3.2(3)); hc,ef = min(2.5(h-d), h/2).
    assert beam["fine-hc-ef"].result.value == pytest.approx(0.5, abs=1e-9)
    assert beam["input-member-type"].result.value == 0.0
    slab = _member_steps(_bundle(deep_input("Slab")), "-long-term")
    assert slab["fine-hc-ef"].result.value == pytest.approx(
        (1.0 - x) / 3.0, rel=1e-4)
    assert slab["input-member-type"].result.value == 1.0


def _mixed_spacing_input():
    """Three bars: a close (7.11) pair and one isolated (7.14) bar."""

    return _beam_input(
        section=Section.from_polygon(
            corners=[(0.0, 0.0), (0.9, 0.0), (0.9, 0.4), (0.0, 0.4)],
            bars_xy_area_mm2=[(0.10, 0.05, 500.0), (0.15, 0.05, 500.0),
                              (0.80, 0.05, 500.0)],
        ),
        bar_elements=[
            {"id": "B-1", "material_id": "B500", "diameter_mm": 25.0},
            {"id": "B-2", "material_id": "B500", "diameter_mm": 25.0},
            {"id": "B-3", "material_id": "B500", "diameter_mm": 25.0},
        ],
        Mx_el_l=100.0, Mx_el_s=0.0)


def test_wide_spacing_714_assigned_per_candidate():
    # A lone bar in a wide section takes (7.14) 1.3(h-x) directly.
    lone = _beam_input(
        section=Section.from_polygon(
            corners=[(0.0, 0.0), (0.6, 0.0), (0.6, 0.4), (0.0, 0.4)],
            bars_xy_area_mm2=[(0.3, 0.05, 800.0)],
        ),
        bar_elements=[{"id": "B-1", "material_id": "B500",
                       "diameter_mm": 25.0}],
        Mx_el_l=60.0, Mx_el_s=0.0)
    out = _candidate_output(lone)
    bundle = _bundle(lone, out)
    steps = _member_steps(bundle, "-long-term")
    x = _cracked_depth(0.6, 0.35, 6.0 * 800.0e-6)
    assert out["elastic"]["crack"]["sr_max_geometric"] is True
    assert steps["fine-candidate-00-sr-max"].result.value == pytest.approx(
        1.3 * (0.4 - x) * 1000.0, rel=1e-4)

    # Mixed: a close pair keeps (7.11); the isolated bar takes (7.14).
    mixed = _mixed_spacing_input()
    mixed_out = _candidate_output(mixed)
    flags = {item["element_no"]: item["sr_max_geometric"]
             for item in mixed_out["elastic"]["crack"]["candidates"]}
    assert flags == {1: False, 2: False, 3: True}
    assert _validate(_bundle(mixed, mixed_out), mixed, mixed_out) is not None


def test_frozen_plane_units_and_dependency_edges():
    # The plane-leaf units and the realigned operand edges are FROZEN: a
    # contract-side revert (unit redeclaration drift or edge severance) must
    # fail here, not only in review. The step ids below are built literally,
    # independent of the contract's own helpers.
    from sector.crack_trace_contract import (
        RAW_GRADIENT as CRACK_RAW_GRADIENT, RAW_STRESS as CRACK_RAW_STRESS,
    )
    from sector.elastic_trace_contract import RAW_GRADIENT, RAW_STRESS

    # Single-sourced from the CT-005 contract: identical objects.
    assert CRACK_RAW_STRESS is RAW_STRESS
    assert CRACK_RAW_GRADIENT is RAW_GRADIENT

    inp = _mixed_spacing_input()
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    steps = _member_steps(bundle, "-long-term")

    # Literal retained plane-leaf units (CT-005 solver plane conventions).
    assert steps["upstream-plane-eps0"].unit == TraceUnit("kN/m2", "stress")
    for name in ("kx", "ky"):
        assert steps[f"upstream-plane-{name}"].unit == TraceUnit(
            "kN/m3", "stress_gradient")

    token = trace_identity_token
    prefixes = tuple(
        f"element-{index:02d}-{token('bar')}-{token(element_id)}-"
        f"{token('B500')}"
        for index, element_id in enumerate(("B-1", "B-2", "B-3")))
    stress_leaves = tuple(f"upstream-{prefix}-stress" for prefix in prefixes)
    planes = ("upstream-plane-eps0", "upstream-plane-kx", "upstream-plane-ky")

    def edges(step_id):
        return tuple(dep.step_id for dep in steps[step_id].dependencies)

    # hc,ef: geometry + bending plane + effective-depth stress operands.
    assert edges("fine-hc-ef") == (
        "normalised-crack-inputs", *planes, *stress_leaves)
    # rho_p,eff: the in-band element inventory and the effective area.
    assert edges("fine-rho-p-eff") == ("normalised-crack-inputs",
                                       "fine-ac-eff")
    # Clear cover: geometry + the used diameter (element or override).
    assert edges("fine-candidate-00-cover") == (
        "normalised-crack-inputs", f"{prefixes[0]}-diameter",
        "input-phi-override")
    # (7.9) mean strain operands.
    assert edges("fine-candidate-00-esm-ecm") == (
        "fine-candidate-00-sigma-s", "fine-rho-p-eff", "input-fctm",
        "input-modular-ratio", f"{prefixes[0]}-es")
    # (7.11) close-spacing branch (candidates 0 and 1).
    assert edges("fine-candidate-00-sr-max") == (
        "fine-candidate-00-cover", f"{prefixes[0]}-diameter",
        f"{prefixes[0]}-k1", "fine-rho-p-eff")
    # (7.14) wide-spacing branch (the isolated candidate 2).
    assert edges("fine-candidate-02-sr-max") == (
        "fine-candidate-02-cover", "normalised-crack-inputs", *planes)


def test_biaxial_governing_candidate_is_max_wk():
    inp = _beam_input(My_el_l=25.0)
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    crack = out["elastic"]["crack"]
    wks = [item["wk"] for item in crack["candidates"]]
    assert crack["wk"] == max(wks)
    assert wks == sorted(wks, reverse=True)
    steps = _member_steps(bundle, "-long-term")
    assert steps["fine-governing"].result.value == float(crack["gov_bar"] - 1)
    assert steps["fine-wk"].result.value == crack["wk"]
    # Candidate cardinality and order are input-derived, never trusted.
    for operation in ("pop", "duplicate", "reverse"):
        changed = copy.deepcopy(out)
        rows = changed["elastic"]["crack"]["candidates"]
        if operation == "pop":
            rows.pop()
        elif operation == "duplicate":
            rows.append(copy.deepcopy(rows[0]))
        else:
            rows.reverse()
        with pytest.raises(TraceValidationError):
            _build(inp, changed)


# ---- retained absence, disposition and invalidation states -----------------

def test_uncracked_and_show_cw_absence_states():
    uncracked = _beam_input(Mx_el_l=20.0, Mx_el_s=0.0)
    out = _candidate_output(uncracked)
    assert out["elastic"]["cracked"] is False
    assert out["elastic"]["crack"] is None
    assert out["elastic"]["crack_output"]["calculation_state"] == (
        "NOT APPLICABLE")
    assert _build(uncracked, out) is None
    assert validate_crack_trace_family(
        None, uncracked, out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) is None

    disabled = _beam_input(sls_cw=False)
    disabled_out = _candidate_output(disabled)
    assert disabled_out["elastic"]["cracked"] is True
    assert _build(disabled, disabled_out) is None
    # A fabricated crack dict on the disabled branch is rejected.
    fabricated = copy.deepcopy(disabled_out)
    fabricated["elastic"]["crack"] = _candidate_output(
        _beam_input())["elastic"]["crack"]
    with pytest.raises(TraceValidationError, match="null"):
        _build(disabled, fabricated)
    # Inactive runs cannot publish the active-only surfaces.
    for key in ("crack_code", "crack_edition", "crack_member",
                "crack_coarse"):
        poisoned = copy.deepcopy(disabled_out)
        poisoned["elastic"][key] = None
        with pytest.raises(TraceValidationError, match="cannot be published"):
            _build(disabled, poisoned)
    # A missing crack_output surface fails closed on the inactive branch too.
    missing = copy.deepcopy(disabled_out)
    del missing["elastic"]["crack_output"]
    with pytest.raises(TraceValidationError, match="crack_output"):
        _build(disabled, missing)
    # An active bundle presented against the inactive input is stale.
    active_inp = _beam_input()
    active_out = _candidate_output(active_inp)
    bundle = _bundle(active_inp, active_out)
    with pytest.raises(TraceValidationError, match="inactive"):
        validate_crack_trace_family(
            bundle, disabled, disabled_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)


def test_direct_tension_is_a_retained_not_assessed_disposition():
    inp = _beam_input(
        section=Section.from_polygon(
            corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.4), (0.0, 0.4)],
            bars_xy_area_mm2=[(0.15, 0.05, 800.0), (0.15, 0.35, 800.0)],
        ),
        bar_elements=[
            {"id": "B-1", "material_id": "B500", "diameter_mm": 25.0},
            {"id": "B-2", "material_id": "B500", "diameter_mm": 25.0},
        ],
        P_el_l=800.0, Mx_el_l=0.0, Mx_el_s=0.0)
    out = _candidate_output(inp)
    assert out["elastic"]["cracked"] is True
    assert out["elastic"]["crack"] is None
    assert out["elastic"]["crack_output"]["calculation_state"] == (
        "NOT APPLICABLE")
    bundle = _bundle(inp, out)
    steps = _member_steps(bundle, "-long-term")
    assert steps["fine-state"].result.value == CRACK_STATE_CODES[
        "NOT ASSESSED"]
    assert steps["ct-009-long-term-result"].result.value == (
        CRACK_STATE_CODES["NOT ASSESSED"])
    # The retained reason is tokenized into the sealed disposition step id.
    disposition = next(step_id for step_id in steps
                       if step_id.startswith("fine-disposition-"))
    assert disposition.startswith("fine-disposition-u")
    # No fabricated numerics anywhere on the not-assessed branch.
    assert not any(step_id.endswith("-wk") for step_id in steps)
    ost = _member_steps(bundle, "-crack-output")
    assert ost["ct-009-crack-output-result"].result.value == (
        CRACK_STATE_CODES["NOT APPLICABLE"])
    assert not any(step_id.endswith("-wk") for step_id in ost)
    # No governing case exists on this branch: sealed as an explicit
    # absent-by-state disposition, never a fabricated finite argmax.
    governing = ost["governing-case"]
    assert governing.result.state == RESULT_UNDEFINED
    assert governing.result.value is None
    assert "no governing-case selection" in governing.result.reason
    assert _validate(bundle, inp, out) is not None


def test_case_without_tension_reinforcement_is_not_applicable():
    # Long case: pure axial compression (all bars compressed) -> the retained
    # NOT APPLICABLE disposition; the peak (combined) action cracks and gives
    # a CALCULATED short case. Centred section so N stays a pure axial action.
    inp = _beam_input(
        section=Section.from_polygon(
            corners=[(-0.15, -0.3), (0.15, -0.3), (0.15, 0.3), (-0.15, 0.3)],
            bars_xy_area_mm2=[(-0.075, -0.25, 491.0), (0.0, -0.25, 491.0),
                              (0.075, -0.25, 491.0)],
        ),
        P_el_l=-500.0, Mx_el_l=0.0, Mx_el_s=230.0)
    out = _candidate_output(inp)
    assert out["elastic"]["cracked"] is True
    assert out["elastic"]["crack"] is None
    assert out["elastic"]["crack_short"] is not None
    bundle = _bundle(inp, out)
    long_steps = _member_steps(bundle, "-long-term")
    assert long_steps["ct-009-long-term-result"].result.value == (
        CRACK_STATE_CODES["NOT APPLICABLE"])
    short_steps = _member_steps(bundle, "-short-term")
    assert short_steps["ct-009-short-term-result"].result.value == (
        CRACK_STATE_CODES["CALCULATED"])
    assert out["elastic"]["crack_output"]["case"] == "Short-term"
    ost = _member_steps(bundle, "-crack-output")
    long_token = case_label_token("Long-term")
    assert ost[f"case-{long_token}-available"].result.value == 0.0
    assert f"case-{long_token}-wk" not in ost
    assert _validate(bundle, inp, out) is not None


def test_non_convergence_invalidation_is_retained_evidence(monkeypatch):
    import sector.crack_trace as module

    inp = _beam_input()
    original = module.solve_elastic_combined
    monkeypatch.setattr(
        module, "solve_elastic_combined",
        lambda *args, **kwargs: dataclasses.replace(
            original(*args, **kwargs), converged=False))
    out = _candidate_output(inp, converged_override=False)
    assert out["elastic"]["crack_output"]["calculation_state"] == "INVALID"
    assert out["elastic"]["crack_output"]["value"] is None
    assert out["elastic"]["crack"] is not None  # retained: still computed
    bundle = _build(inp, out)
    ost = _member_steps(bundle, "-crack-output")
    assert ost["ct-009-crack-output-result"].result.value == (
        CRACK_STATE_CODES["INVALID"])
    assert ost["upstream-converged"].result.value == 0.0
    # The case wk operands exist, but the retained output selected no
    # governing case: the step must be an explicit undefined disposition,
    # never a fabricated finite argmax.
    governing = ost["governing-case"]
    assert governing.result.state == RESULT_UNDEFINED
    assert governing.result.value is None
    assert "no governing-case selection" in governing.result.reason
    assert _validate(bundle, inp, out) is not None
    # Reseal attack: injecting a finite 0.0 governing-case argmax on the
    # INVALID branch is rejected by the closure comparison.
    output_calc = next(c for c in bundle.calculations
                       if c.calculation_id.endswith("-crack-output"))
    forged_steps = tuple(
        dataclasses.replace(
            step, result=TraceResult(RESULT_FINITE, 0.0),
            substituted_expression="governing-case = 0 1")
        if step.step_id == "governing-case" else step
        for step in output_calc.steps)
    forged = seal_bundle(dataclasses.replace(
        bundle, calculations=tuple(
            dataclasses.replace(c, steps=forged_steps)
            if c is output_calc else c for c in bundle.calculations)))
    with pytest.raises(TraceValidationError):
        _validate(forged, inp, out)
    # Promotion attempt: candidate claims convergence against a failed replay.
    promoted = _candidate_output(inp, converged_override=True)
    with pytest.raises(TraceValidationError):
        _build(inp, promoted)


def test_demotion_of_a_converged_run_is_rejected():
    inp = _beam_input()
    out = _candidate_output(inp, converged_override=False)
    with pytest.raises(TraceValidationError):
        _build(inp, out)


# ---- scope, edition and identity attacks ------------------------------------

def test_2023_edition_and_2023_materials_never_finite():
    active = _beam_input(sls_edition="2023", sls_code="EN 1992-1-1:2023")
    with pytest.raises(TraceValidationError, match="next slice"):
        _build(active, {"elastic": {}})
    # A 2023 edition with the crack gate off is a plain absence state.
    idle = _beam_input(sls_edition="2023", sls_code="EN 1992-1-1:2023",
                       sls_cw=False)
    assert _build(idle, _candidate_output(idle)) is None
    # A used 2023 material law can never produce finite CT-009 evidence.
    materials = _beam_input(steel=codes.EC2_2023.steel(500.0),
                            mild_preset=codes.EC2_2023.label)
    with pytest.raises(TraceValidationError, match="2023 material"):
        _build(materials, {"elastic": {}})
    # The 2023-material fence guards the ACTIVE crack branch only: the
    # retained show_cw-off and uncracked states stay legitimate absence
    # states whatever material edition is assigned.
    materials_off = _beam_input(steel=codes.EC2_2023.steel(500.0),
                                mild_preset=codes.EC2_2023.label,
                                sls_cw=False)
    materials_off_out = _candidate_output(materials_off)
    assert materials_off_out["elastic"]["cracked"] is True
    assert _build(materials_off, materials_off_out) is None
    assert validate_crack_trace_family(
        None, materials_off, materials_off_out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) is None
    materials_uncracked = _beam_input(steel=codes.EC2_2023.steel(500.0),
                                      mild_preset=codes.EC2_2023.label,
                                      Mx_el_l=20.0, Mx_el_s=0.0)
    materials_uncracked_out = _candidate_output(materials_uncracked)
    assert materials_uncracked_out["elastic"]["cracked"] is False
    assert _build(materials_uncracked, materials_uncracked_out) is None
    # 2023 CONCRETE provenance on an active crack run is equally fenced.
    concrete_2023 = _beam_input(concrete=codes.EC2_2023.concrete(30.0),
                                concrete_preset=codes.EC2_2023.label)
    with pytest.raises(TraceValidationError, match="2023 material"):
        _build(concrete_2023, {"elastic": {}})
    with pytest.raises(TraceValidationError, match="edition"):
        _build(_beam_input(sls_edition="2005"), {"elastic": {}})


def test_exact_input_typing_is_enforced():
    base_out = _candidate_output(_beam_input())
    for changes, match in (
        ({"sls_cw": 1}, "Boolean"),
        ({"sls_dk_na": "true"}, "Boolean"),
        ({"sls_fctm": "2.9"}, "number"),
        ({"sls_k1": True}, "number"),
        ({"nl": math.nan}, "finite"),
        ({"mode": 5}, "text"),
    ):
        with pytest.raises(TraceValidationError, match=match):
            _build(_beam_input(**changes), base_out)
    # Element identity: exact text ids and numeric diameters only.
    for element in ({"id": 7, "material_id": "B500", "diameter_mm": 25.0},
                    {"id": "", "material_id": "B500", "diameter_mm": 25.0},
                    {"id": "B-1", "material_id": "B500",
                     "diameter_mm": "25"}):
        inp = _beam_input()
        inp["bar_elements"] = [element] + inp["bar_elements"][1:]
        with pytest.raises(TraceValidationError):
            _build(inp, base_out)
    # Misaligned element inventory.
    misaligned = _beam_input()
    misaligned["bar_elements"] = misaligned["bar_elements"][:2]
    with pytest.raises(TraceValidationError, match="align"):
        _build(misaligned, base_out)
    # DK NA runs bind the member selection as identity.
    dk = _beam_input(sls_dk_na=True, sls_code="DS/EN 1992-1-1 + DK NA",
                     sls_member=None)
    with pytest.raises(TraceValidationError, match="sls_member"):
        _build(dk, base_out)


def test_element_identity_renames_reseal_differently():
    inp = _beam_input()
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    renamed = _beam_input()
    renamed["bar_elements"] = [
        {"id": "B-renamed", "material_id": "B500", "diameter_mm": 25.0},
        *inp["bar_elements"][1:],
    ]
    # Stale candidate ids against the renamed input fail closed.
    with pytest.raises(TraceValidationError):
        _build(renamed, out)
    renamed_out = _candidate_output(renamed)
    renamed_bundle = _bundle(renamed, renamed_out)
    assert renamed_bundle.to_dict() != bundle.to_dict()
    with pytest.raises(TraceValidationError):
        validate_crack_trace_family(
            bundle, renamed, renamed_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    # Identity strings live in sealed step ids as injective tokens.
    steps = _member_steps(renamed_bundle, "-long-term")
    token = trace_identity_token("B-renamed")
    assert any(token in step_id for step_id in steps)


def test_exact_published_typing_int_bool_text():
    inp = _beam_input()
    out = _candidate_output(inp)
    for path, value in (
        (("crack", "element_no"), 1.0),
        (("crack", "gov_bar"), 1.0),
        (("crack", "coarse"), 0),
        (("crack", "edition"), 2004),
        (("crack_short", "sr_max_geometric"), 0),
        (("crack_output", "unit"), None),
        (("crack_output", "value"), True),
    ):
        changed = copy.deepcopy(out)
        node = changed["elastic"]
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        with pytest.raises(TraceValidationError):
            _build(inp, changed)


def test_phi_override_and_kernel_faithful_auto_diameter():
    override = _beam_input(sls_phi=20.0)
    out = _candidate_output(override)
    steps = _member_steps(_bundle(override, out), "-long-term")
    assert steps["input-phi-override"].result.value == 20.0
    assert out["elastic"]["crack"]["phi"] == 20.0
    diameter_steps = [step_id for step_id in steps
                      if step_id.endswith("-diameter")]
    assert len(diameter_steps) == 3
    assert all(steps[s].result.value == 20.0 for s in diameter_steps)

    auto = _beam_input()
    auto["bar_elements"][1]["diameter_mm"] = 0.0  # kernel falls back to area
    auto_out = _candidate_output(auto)
    derived = math.sqrt(4.0 * 491.0 / math.pi)
    by_index = {item["element_no"] - 1: item
                for item in auto_out["elastic"]["crack"]["candidates"]}
    assert by_index[1]["phi"] == pytest.approx(derived)
    auto_bundle = _bundle(auto, auto_out)
    auto_steps = _member_steps(auto_bundle, "-long-term")
    diameters = sorted(
        auto_steps[s].result.value for s in auto_steps
        if s.endswith("-diameter"))
    assert diameters == pytest.approx(sorted([25.0, derived, 25.0]))
    assert _validate(auto_bundle, auto, auto_out) is not None


def test_tendon_identity_bond_and_prestress_removed_short_stress():
    section = Section.from_polygon(
        corners=[(0.0, 0.0), (B, 0.0), (B, H), (0.0, H)],
        bars_xy_area_mm2=[(0.075, 0.05, 491.0), (0.225, 0.05, 491.0)],
        tendons_xy_area_mm2=[(0.15, 0.1, 1000.0)],
    )
    inp = _beam_input(
        section=section,
        bar_elements=[
            {"id": "B-1", "material_id": "B500", "diameter_mm": 25.0},
            {"id": "B-2", "material_id": "B500", "diameter_mm": 25.0},
        ],
        tendon_elements=[
            {"id": "T-1", "material_id": "P-1", "diameter_mm": 15.0},
        ],
        prestress=Prestress(curve=1, IS=0.0005, Es=195_000.0),
        prestress_preset="project tendon",
        Mx_el_l=250.0, Mx_el_s=30.0, sls_tendon_xi=0.4)
    out = _candidate_output(inp)
    assert out["elastic"]["cracked"] is True
    bundle = _bundle(inp, out)
    steps = _member_steps(bundle, "-short-term")
    assert steps["input-tendon-xi"].result.value == pytest.approx(0.4)
    # Prestressing tendons always take the plain-bond k1 = 1.6.
    k1_values = sorted(
        steps[s].result.value for s in steps
        if s.endswith("-k1") and s != "input-k1")
    assert k1_values == pytest.approx([0.8, 0.8, 1.6])
    # The short-case upstream stresses are the prestress-removed totals.
    locked_mpa = 195_000.0 * 0.0005  # locked-in tendon stress, MPa
    total = out["elastic"]["total"]
    upstream = sorted(
        steps[s].result.value for s in steps
        if s.startswith("upstream-element-") and s.endswith("-stress"))
    expected = sorted([total[0], total[1], total[2] - locked_mpa])
    assert upstream == pytest.approx(expected, rel=1e-9)
    # Tendon identity is tokenized into sealed step ids.
    assert any(trace_identity_token("T-1") in step_id for step_id in steps)
    assert _validate(bundle, inp, out) is not None


# ---- surface closure, masking and full candidate inventory ------------------

def test_mode_and_section_fencing_and_junk_masking():
    plastic = _beam_input(mode="Plastic")
    assert _build(plastic, {}) is None
    assert validate_crack_trace_family(
        None, plastic, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is None
    with pytest.raises(TraceValidationError, match="inactive"):
        _build(plastic, {"elastic": {"crack": None}})
    assert _build(_beam_input(section=None), {}) is None
    # Junk in plastic-only actions cannot mask or alter the family.
    inp = _beam_input()
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    masked = dict(inp, P_pl=math.nan, Mx_pl=math.inf, My_pl=-math.inf,
                  torsion_T=math.nan, shear_V=math.nan)
    assert _build(masked, out).to_dict() == bundle.to_dict()


def test_edition_impossible_and_missing_surfaces_fail_closed():
    inp = _beam_input()
    out = _candidate_output(inp)
    # Non-DK runs can never publish the coarse surfaces, even as null.
    for key in ("crack_coarse", "crack_short_coarse"):
        poisoned = copy.deepcopy(out)
        poisoned["elastic"][key] = None
        with pytest.raises(TraceValidationError, match="edition-impossible"):
            _build(inp, poisoned)
    # Every owned surface must be present on the active branch.
    for key in ("crack", "crack_short", "crack_code", "crack_edition",
                "crack_member", "crack_output"):
        missing = copy.deepcopy(out)
        del missing["elastic"][key]
        with pytest.raises(TraceValidationError):
            _build(inp, missing)
    # The retained code/edition/member selections are bound identity.
    for key, value in (("crack_code", "EN 1993"), ("crack_edition", "2023"),
                       ("crack_member", "Slab")):
        changed = copy.deepcopy(out)
        changed["elastic"][key] = value
        with pytest.raises(TraceValidationError):
            _build(inp, changed)


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


def _mutated(value):
    if type(value) is bool:
        return not value
    if type(value) is int:
        return value + 1
    if isinstance(value, float):
        return value + 0.271828
    if isinstance(value, str):
        return value + "-tampered"
    return 0.0  # None leaves become a fabricated numeric


def test_inventory_walk_rejects_every_crack_surface_mutation():
    inp = _beam_input()
    out = _candidate_output(inp)
    assert _build(inp, out) is not None
    for surface in ("crack", "crack_short", "crack_output"):
        for kind, path, detail in list(_walk(out["elastic"][surface],
                                             (surface,))):
            if kind == "leaf":
                changed = copy.deepcopy(out)
                parent = _at(changed["elastic"], path[:-1])
                parent[path[-1]] = _mutated(detail)
                with pytest.raises(TraceValidationError):
                    _build(inp, changed)
                continue
            changed = copy.deepcopy(out)
            node = _at(changed["elastic"], path)
            node["unexpected-ct009-field"] = 0.0
            with pytest.raises(TraceValidationError):
                _build(inp, changed)
            for key in detail:
                changed = copy.deepcopy(out)
                node = _at(changed["elastic"], path)
                del node[key]
                with pytest.raises(TraceValidationError):
                    _build(inp, changed)
            if len(detail) > 1:
                changed = copy.deepcopy(out)
                node = _at(changed["elastic"], path)
                items = [(key, node[key]) for key in reversed(detail)]
                node.clear()
                node.update(items)
                with pytest.raises(TraceValidationError):
                    _build(inp, changed)


def test_consumed_upstream_leaves_reject_mutation():
    inp = _beam_input()
    out = _candidate_output(inp)
    assert _build(inp, out) is not None
    mutations = (
        lambda o: o["elastic"].__setitem__("stress_plane", (9.0, 1.0, 2.0)),
        lambda o: o["elastic"]["total"].__setitem__(
            0, o["elastic"]["total"][0] + 4.0),
        lambda o: o["elastic"].__setitem__(
            "total", o["elastic"]["total"][:-1]),
        lambda o: o["elastic"].__setitem__("converged", False),
        lambda o: o["elastic"].__setitem__("cracked", False),
        lambda o: o["elastic"].__setitem__(
            "lambda_cr", o["elastic"]["lambda_cr"] + 0.2),
        lambda o: o["elastic"].__setitem__("lambda_cr", math.nan),
        lambda o: o["elastic"].__setitem__("fctm", FCT + 0.5),
        lambda o: o["elastic"].__setitem__("show_cw", False),
    )
    for mutate in mutations:
        changed = copy.deepcopy(out)
        mutate(changed)
        with pytest.raises(TraceValidationError):
            _build(inp, changed)


# ---- graph, tamper and sealing battery --------------------------------------

def test_graph_reachability_and_dependency_edge_removal():
    inp = _beam_input()
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    assert len(bundle.calculations) == 3
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
                    _validate(tampered, inp, out)


@pytest.mark.parametrize("dk", [False, True])
def test_resealed_identity_value_source_unit_axis_tamper(dk):
    inp = _beam_input(**({"sls_dk_na": True,
                          "sls_code": "DS/EN 1992-1-1 + DK NA",
                          "sls_member": "Beam"} if dk else {}))
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    target = bundle.calculations[0]

    def _retarget(**changes):
        return seal_bundle(dataclasses.replace(
            bundle, calculations=(dataclasses.replace(target, **changes),
                                  *bundle.calculations[1:])))

    steps = list(target.steps)
    wk_index = next(i for i, s in enumerate(steps) if s.step_id == "fine-wk")
    value_steps = list(steps)
    value_steps[wk_index] = dataclasses.replace(
        steps[wk_index],
        result=dataclasses.replace(
            steps[wk_index].result,
            value=steps[wk_index].result.value + 0.01))
    value_tamper = _retarget(steps=tuple(value_steps))
    source_steps = list(steps)
    source_steps[wk_index] = dataclasses.replace(
        steps[wk_index], source=ADAPTER_SOURCE)
    source_tamper = _retarget(steps=tuple(source_steps))
    wrong = TraceUnit("m", "length")
    unit_steps = tuple(dataclasses.replace(
        step, unit=wrong if step.step_id == "fine-wk" else step.unit,
        dependencies=tuple(TraceDependency(
            dep.step_id, wrong if dep.step_id == "fine-wk" else dep.unit)
            for dep in step.dependencies)) for step in steps)
    unit_tamper = _retarget(steps=unit_steps)
    axes_tamper = _retarget(axes=tuple(
        dataclasses.replace(axis, value="true" if axis.value == "false"
                            else "false")
        if axis.name == "dk_na" else axis for axis in target.axes))
    swapped = list(steps)
    swapped[1], swapped[2] = swapped[2], swapped[1]
    order_tamper = _retarget(steps=tuple(swapped))
    method_tamper = _retarget(method_id="wrong-crack-method")
    for candidate in (value_tamper, source_tamper, unit_tamper, axes_tamper,
                      order_tamper, method_tamper,
                      dataclasses.replace(bundle, input_sha256="c" * 64),
                      dataclasses.replace(bundle, result_sha256="c" * 64),
                      dataclasses.replace(
                          bundle, calculations=bundle.calculations * 2)):
        with pytest.raises(TraceValidationError):
            _validate(candidate, inp, out)
    assert _validate(bundle, inp, out) is not None


def test_registry_identity_and_product_identity():
    inp = _beam_input()
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    assert REGISTRY_ID == "sector-ct-009-crack-width-v1"
    assert FAMILY_ID == "ct-009-crack-width"
    suffixes = sorted(
        calculation.calculation_id.rsplit("-", 2)[-2]
        + "-" + calculation.calculation_id.rsplit("-", 2)[-1]
        for calculation in bundle.calculations)
    assert suffixes == ["crack-output", "long-term", "short-term"]
    for calculation in bundle.calculations:
        assert calculation.coverage_id == COVERAGE_ID == "ct-009"
        assert calculation.method_id == METHOD_ID
        assert calculation.assumptions == (
            "Crack widths are output-only quantities; no limit or compliance "
            "verdict is implied.",)
        final = calculation.steps[-1]
        assert final.quantity_role == ROLE_FINAL
        assert final.result.state == RESULT_FINITE
        assert final.result.value in CRACK_STATE_CODES.values()
    # Product Identity: crack widths carry no PASS/FAIL verdict anywhere.
    payload = bundle_to_json(bundle)
    assert "PASS" not in payload and "FAIL" not in payload
    assert "Infinity" not in payload and "NaN" not in payload


def test_nonfinite_retained_values_seal_truthfully():
    # Unit-level probe of the sealing rule: the retained kernels only publish
    # finite crack quantities from finite converged upstream planes (the
    # kernels return NOT ASSESSED dispositions instead of non-finite
    # numbers), so the inf/NaN sealing paths guard non-converged upstream
    # planes bound as evidence leaves. They must represent, never fabricate.
    from sector.crack_trace_contract import _Rows

    rows = _Rows()
    rows.add("input-cw-enabled", "Crack-width reporting enabled", ONE,
             ROLE_USER_INPUT, INPUT_SOURCE)
    rows.add("unbounded-value", "Unbounded retained value", MM,
             ROLE_COMPUTED, ADAPTER_SOURCE, "input-cw-enabled")
    rows.add("negative-unbounded-value", "Negative unbounded retained value",
             MM, ROLE_COMPUTED, ADAPTER_SOURCE, "input-cw-enabled")
    rows.add("undefined-value", "Undefined retained value", MM,
             ROLE_COMPUTED, ADAPTER_SOURCE, "input-cw-enabled")
    rows.add("mini-final", "Mini final state", ONE, ROLE_FINAL,
             ADAPTER_SOURCE, "unbounded-value", "negative-unbounded-value",
             "undefined-value")
    calculation = _calculation(
        "ct-009-mini", "Sealing probe",
        (TraceAxis("probe", "sealing"),), tuple(rows.rows),
        {"input-cw-enabled": 1.0, "unbounded-value": math.inf,
         "negative-unbounded-value": -math.inf,
         "undefined-value": math.nan, "mini-final": 1.0})
    by_id = {step.step_id: step for step in calculation.steps}
    unbounded = by_id["unbounded-value"]
    assert unbounded.result.state == RESULT_POSITIVE_INFINITY
    assert unbounded.result.value is None
    assert "unbounded" in unbounded.result.reason
    assert "positive_infinity" in unbounded.substituted_expression
    negative = by_id["negative-unbounded-value"]
    assert negative.result.state == RESULT_NEGATIVE_INFINITY
    assert negative.result.value is None
    assert "unbounded" in negative.result.reason
    assert "negative_infinity" in negative.substituted_expression
    undefined = by_id["undefined-value"]
    assert undefined.result.state == RESULT_UNDEFINED
    assert undefined.result.value is None
    assert "undefined" in undefined.result.reason
    assert by_id["mini-final"].result.state == RESULT_FINITE


def test_context_and_shape_partition_bundles():
    inp = _beam_input()
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    other = build_crack_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context={"case": "another case"})
    assert other.to_dict() != bundle.to_dict()
    with pytest.raises(TraceValidationError):
        validate_crack_trace_family(
            other, inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
            context=CONTEXT)
    # A 2-case bundle can never validate against a DK 4-case run.
    dk = _beam_input(sls_dk_na=True, sls_code="DS/EN 1992-1-1 + DK NA",
                     sls_member="Beam")
    dk_out = _candidate_output(dk)
    with pytest.raises(TraceValidationError):
        validate_crack_trace_family(
            bundle, dk, dk_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    dk_bundle = _bundle(dk, dk_out)
    long_axes = {axis.name: axis.value
                 for axis in dk_bundle.calculations[0].axes}
    assert long_axes["dk_na"] == "true"
    assert long_axes["variant_count"] == "2"
    assert long_axes["crack_edition"] == "2004"


def test_dk_coarse_surface_tampers_reject_build_and_sealed_bundle():
    inp = _beam_input(sls_dk_na=True, sls_code="DS/EN 1992-1-1 + DK NA",
                      sls_member="Beam")
    out = _candidate_output(inp)
    bundle = _bundle(inp, out)
    tampers = (
        lambda o: o["elastic"]["crack_coarse"].__setitem__(
            "wk", o["elastic"]["crack_coarse"]["wk"] + 0.01),
        lambda o: o["elastic"]["crack_coarse"].__setitem__(
            "sr_max", o["elastic"]["crack_coarse"]["sr_max"] * 1.001),
        lambda o: o["elastic"]["crack_coarse"]["candidates"][1].__setitem__(
            "sigma_s",
            o["elastic"]["crack_coarse"]["candidates"][1]["sigma_s"] + 1.0),
        lambda o: o["elastic"]["crack_short_coarse"].__setitem__(
            "wk", o["elastic"]["crack_short_coarse"]["wk"] + 0.01),
        lambda o: o["elastic"]["crack_short_coarse"].__setitem__(
            "esm_ecm",
            o["elastic"]["crack_short_coarse"]["esm_ecm"] * 1.01),
        lambda o: o["elastic"]["crack_short_coarse"]["candidates"][0]
        .__setitem__("hc_ef", 0.2),
    )
    for tamper in tampers:
        changed = copy.deepcopy(out)
        tamper(changed)
        with pytest.raises(TraceValidationError):
            _build(inp, changed)
        with pytest.raises(TraceValidationError):
            _validate(bundle, inp, changed)
    assert _validate(bundle, inp, out) is not None


def _run_analysis_input(**over):
    from app import material_catalog

    outer = [(0.0, 0.0), (B, 0.0), (B, H), (0.0, H)]
    bars = [(0.075, 0.05, 491.0), (0.15, 0.05, 491.0), (0.225, 0.05, 491.0)]
    entry = material_catalog.default_entry(
        "mild", material_id="B500", preset=codes.EC2_2005.label)
    steel = material_catalog.build_material(entry, "mild")
    inp = _beam_input(
        outer=outer, holes=[], bars=bars, tendons=[],
        prestress=None, steel=steel,
        bar_materials=[steel, steel, steel],
        mild_material_catalog={"version": 1, "next_id": 2, "items": [entry]},
        prestress_material_catalog={"version": 1, "next_id": 1, "items": []},
        conc_Ec=33.0, el_phi=1.0,
        P_pl=0.0, Mx_pl=0.0, My_pl=0.0,
    )
    inp.update(over)
    return inp


def test_retained_run_analysis_composition_builds_and_validates():
    # The retained single-analysis run_analysis composition publishes the
    # crack surfaces this family owns; the trace must build from exactly
    # that payload and validate against it.
    inp = _run_analysis_input()
    out = run_analysis(inp)
    assert out["elastic"]["cracked"] is True
    assert out["elastic"]["crack"] is not None
    assert out["elastic"]["crack_output"]["calculation_state"] == "CALCULATED"
    bundle = build_crack_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT)
    assert bundle is not None and len(bundle.calculations) == 3
    for calculation in bundle.calculations:
        assert calculation.steps[-1].result.state == RESULT_FINITE
    assert _validate(bundle, inp, out) is not None

    # The DK NA composition publishes the 4-case table end to end.
    dk = _run_analysis_input(sls_dk_na=True,
                             sls_code="DS/EN 1992-1-1 + DK NA",
                             sls_member="Beam")
    dk_out = run_analysis(dk)
    assert dk_out["elastic"]["crack_coarse"] is not None
    assert dk_out["elastic"]["crack_output"]["case"] in CASE_LABELS_DK
    dk_bundle = build_crack_trace_family(
        dk, dk_out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT)
    assert dk_bundle is not None and len(dk_bundle.calculations) == 3
    ost = _member_steps(dk_bundle, "-crack-output")
    for label in CASE_LABELS_DK:
        assert f"case-{case_label_token(label)}-available" in ost
    assert _validate(dk_bundle, dk, dk_out) is not None
