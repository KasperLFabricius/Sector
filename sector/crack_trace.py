"""Solver-owned unpublished CT-009 crack-width trace (2004 + DK NA branch).

The family binds the CT-005-validated elastic planes, cracked states and bar
stresses as named upstream-evidence leaves and replays only the retained crack
kernels from them: ``analyse_cracking`` (crack-side gate), ``combined_cracking``
and ``evaluate_crack_width`` with the retained app argument mapping, in the
retained composition order of ``app/sector_app.py``. Crack widths are
output-only quantities (Product Identity): finals aggregate the retained
calculation states (CALCULATED / NOT ASSESSED / NOT APPLICABLE / INVALID) and
never a PASS/FAIL verdict.
"""

from __future__ import annotations

import dataclasses
import math
import numbers
from collections.abc import Mapping
from typing import Any

import numpy as np

from . import sls as sls_core
from .calculation_trace import (
    RESULT_FINITE, RESULT_NEGATIVE_INFINITY, RESULT_POSITIVE_INFINITY,
    RESULT_UNDEFINED, TraceBundle, TraceCalculation, TraceDependency,
    TraceResult, TraceStep, TraceValidationError, create_bundle,
    validate_bundle,
)
from .crack_trace_contract import (
    CANDIDATE_KEYS, CASE_LABELS_BASE, CASE_LABELS_DK, COVERAGE_ID,
    CRACK_KEYS, CRACK_STATE_CODES, CandidateShape, CaseShape, CrackShape,
    ElementShape, METHOD_ID, OUTPUT_KEYS, OutputShape, VariantShape,
    case_label_token, disposition_id, element_prefix, expected_case_steps,
    expected_output_steps, expected_registry,
)
from .detailing_trace import _compare_value
from .elastic import solve_elastic_combined
from .section import Bar, Section
from .section_trace_blocks import context_axes, context_id, section_trace_blocks
from .serviceability import analyse_cracking, combined_cracking, evaluate_crack_width
from .torsion_trace import _boolean, _compare, _mapping, _number, \
    _retained_mapping, _sequence
from .trace_registry import audit_trace_registry


_DRIFT = "authoritative CT-009 output inventory drifted"
_REFERENCE_ES = 200_000.0
_PLASTIC_ACTION_KEYS = frozenset(("P_pl", "Mx_pl", "My_pl"))
_INFINITE_REASON = (
    "Retained crack quantity is unbounded; the retained value is represented, "
    "never replaced by a fabricated finite number."
)
_NAN_REASON = (
    "Retained crack quantity is undefined; the retained value is represented, "
    "never replaced by a fabricated finite number."
)
_NO_GOVERNING_REASON = (
    "The retained crack output made no governing-case selection on this "
    "branch; no finite selection index is fabricated."
)
# Every retained crack publication surface owned by this family.
_CRACK_SURFACES = ("crack", "crack_short", "crack_coarse",
                   "crack_short_coarse", "crack_output", "crack_code",
                   "crack_edition", "crack_member")
_ACTIVE_SURFACES = ("crack", "crack_short", "crack_code", "crack_edition",
                    "crack_member", "crack_output")
_COARSE_SURFACES = ("crack_coarse", "crack_short_coarse")


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not value:
        raise TraceValidationError(f"{label} must be non-empty text")
    return value


def _compare_retained(actual: Any, expected: Any, label: str) -> None:
    """Compare an upstream-published number under the CT-005 conventions.

    The retained app publishes these surfaces as plain or NumPy floats; a
    retained non-converged solve may publish non-finite values, which must be
    matched truthfully, never replaced by a finite lookalike (or vice versa).
    """

    if not isinstance(actual, numbers.Real) or isinstance(
            actual, (bool, np.bool_)):
        raise TraceValidationError(f"{label} must be numerical")
    got = float(actual)
    wanted = float(expected)
    if math.isnan(wanted):
        if not math.isnan(got):
            raise TraceValidationError(
                f"{label} differs from authoritative replay")
        return
    if math.isnan(got):
        raise TraceValidationError(f"{label} must not be NaN")
    if math.isinf(wanted):
        if (not math.isinf(got)
                or math.copysign(1.0, got) != math.copysign(1.0, wanted)):
            raise TraceValidationError(
                f"{label} has the wrong explicit infinity")
        return
    if not math.isfinite(got) or not math.isclose(
            got, wanted, rel_tol=1.0e-9, abs_tol=1.0e-9):
        raise TraceValidationError(
            f"{label} differs from authoritative replay")


def _crack_dict(cw, bar_ids, tendon_ids):
    """Faithful replica of the retained app _crack_dict flattening."""

    if cw is None:
        return None
    n_bars = len(bar_ids)

    def element(index):
        if index < n_bars:
            return "Bar", index + 1, bar_ids[index]
        tendon_index = index - n_bars
        return "Tendon", tendon_index + 1, tendon_ids[tendon_index]

    def candidate(c):
        kind, number, element_id = element(c.bar_index)
        return dict(
            element_type=kind, element_no=number, element_id=element_id,
            x_mm=c.x * 1000.0, y_mm=c.y * 1000.0, area_mm2=c.area,
            wk=c.wk, sr_max=c.sr_max, esm_ecm=c.esm_ecm, sigma_s=c.sigma_s,
            rho_p_eff=c.rho_p_eff, ac_eff=c.ac_eff, hc_ef=c.hc_ef, phi=c.phi,
            cover=c.cover, coarse=c.coarse, edition=c.edition, kw=c.kw,
            k1_r=c.k1_r, kfl=c.kfl, sr_max_geometric=c.sr_max_geometric,
        )

    kind, number, element_id = element(cw.gov_bar)
    return dict(
        wk=cw.wk, sr_max=cw.sr_max, esm_ecm=cw.esm_ecm, sigma_s=cw.sigma_s,
        rho_p_eff=cw.rho_p_eff, ac_eff=cw.ac_eff, hc_ef=cw.hc_ef, phi=cw.phi,
        cover=cw.cover, gov_bar=cw.gov_bar + 1, element_type=kind,
        element_no=number, element_id=element_id, coarse=cw.coarse,
        edition=cw.edition, kw=cw.kw, k1_r=cw.k1_r, kfl=cw.kfl,
        sr_max_geometric=cw.sr_max_geometric,
        candidates=[candidate(c) for c in cw.candidates],
    )


def _state(inp):
    """Validate the retained SLS crack inputs the app reads on an elastic run."""

    edition = inp.get("sls_edition")
    if edition not in {"2004", "2023"}:
        raise TraceValidationError(
            "sls_edition must be a retained crack edition")
    dk = _boolean(inp.get("sls_dk_na"), "sls_dk_na")
    # The retained app only reads sls_member under the DK NA (short-circuit at
    # the include_hx selection) and only publishes crack_member there.
    member = inp.get("sls_member") if dk else None
    if dk and type(member) is not str:
        raise TraceValidationError("sls_member must be text under the DK NA")
    return dict(
        edition=edition, dk=dk, member=member,
        slab=bool(dk and member == "Slab"),
        cw=_boolean(inp.get("sls_cw"), "sls_cw"),
        fctm=_number(inp.get("sls_fctm"), "sls_fctm", nonnegative=True),
        phi=_number(inp.get("sls_phi"), "sls_phi", nonnegative=True),
        k1=_number(inp.get("sls_k1"), "sls_k1", positive=True),
        nl=_number(inp.get("nl"), "nl", positive=True),
        ns=_number(inp.get("ns"), "ns", positive=True),
        p_l=_number(inp.get("P_el_l"), "P_el_l"),
        mx_l=_number(inp.get("Mx_el_l"), "Mx_el_l"),
        my_l=_number(inp.get("My_el_l"), "My_el_l"),
        p_s=_number(inp.get("P_el_s"), "P_el_s"),
        mx_s=_number(inp.get("Mx_el_s"), "Mx_el_s"),
        my_s=_number(inp.get("My_el_s"), "My_el_s"),
    )


def _reject_2023_sources(blocks):
    """A used 2023 material law can never produce finite CT-009 evidence.

    Scanned only on the active crack branch: the retained show_cw-off,
    uncracked and non-elastic states are legitimate absence states whatever
    material edition is assigned (branch selection from direct inputs first).
    """

    for block in (blocks.concrete, *blocks.bars, *blocks.tendons):
        source = block.provenance.source
        if source.citation is not None and "2023" in source.citation.document:
            raise TraceValidationError(
                "2023 material provenance is published but not implemented "
                "for CT-009"
            )


def _scoped_blocks(inp):
    """Section/material blocks scoped to this family."""

    scoped = {key: value for key, value in inp.items()
              if key not in _PLASTIC_ACTION_KEYS}
    blocks = section_trace_blocks(scoped)
    section = Section(
        [np.asarray(ring) for ring in blocks.geometry.rings],
        bars=[Bar(item.x, item.y, item.area)
              for item in (*blocks.geometry.bars, *blocks.geometry.tendons)],
    )
    moduli = np.asarray([dict(block.values)["Es"]
                         for block in (*blocks.bars, *blocks.tendons)],
                        dtype=float)
    n_mult = moduli / _REFERENCE_ES if moduli.size else None
    locked = (np.asarray(
        [0.0] * len(blocks.bars)
        + [dict(block.values)["Es"] * dict(block.values)["IS"] * 1000.0
           for block in blocks.tendons]) if blocks.tendons else None)
    return blocks, section, moduli, n_mult, locked


def _element_records(inp, key, count, label):
    records = [_mapping(item, f"{label} element")
               for item in _sequence(inp.get(key, ()), key)]
    ids = [_text(item.get("id"), f"{label} element id") for item in records]
    if len(ids) != count:
        raise TraceValidationError("crack element identity must align")
    return records, ids


def _replay(inp, context):
    """Replay the retained composition (app run_analysis 5256-5382) exactly."""

    mode = inp.get("mode")
    if type(mode) is not str:
        raise TraceValidationError("mode must be text")
    if mode not in ("Elastic", "Both") or inp.get("section") is None:
        return dict(elastic_ran=False, active=False)
    state = _state(inp)
    blocks, section, moduli, n_mult, locked = _scoped_blocks(inp)
    nb, nt = len(blocks.bars), len(blocks.tendons)
    bar_records, bar_ids = _element_records(inp, "bar_elements", nb, "bar")
    tendon_records, tendon_ids = _element_records(
        inp, "tendon_elements", nt, "tendon")
    # Diameter binding follows the retained kernel exactly: a supplied
    # non-positive per-element diameter falls back to the equivalent circular
    # diameter from the element area; a positive override applies to all.
    derived = [math.sqrt(4.0 * item.area * 1.0e6 / math.pi)
               for item in (*blocks.geometry.bars, *blocks.geometry.tendons)]
    if state["phi"] > 0.0:
        phi = state["phi"]
        phi_used = [state["phi"]] * (nb + nt)
    else:
        phi = [_number(item.get("diameter_mm"), "element diameter")
               for item in (*bar_records, *tendon_records)]
        phi_used = [supplied if supplied > 0.0 else fallback
                    for supplied, fallback in zip(phi, derived)]
    k1_bars = [state["k1"]] * nb + [1.6] * nt
    include_hx = (not state["dk"]) or state["slab"] or bool(nt)
    result = solve_elastic_combined(
        section, -state["p_l"], state["mx_l"], state["my_l"], state["nl"],
        -state["p_s"], state["mx_s"], state["my_s"], state["ns"],
        n_mult=n_mult, prestress_stress=locked)
    cr_l = analyse_cracking(
        section, -state["p_l"], state["mx_l"], state["my_l"], state["nl"],
        fctm=state["fctm"], Es=list(moduli), beta=0.5, kt=0.4,
        bar_diameter=phi, k1=k1_bars, k3_cover_dependent=state["dk"],
        include_hx_term=include_hx, edition="2004", n_mult=n_mult,
        prestress_stress=locked)
    converged = (result.converged and cr_l.uncracked.converged
                 and cr_l.cracked_state.converged)
    crk_t, lam_t, sig_t = combined_cracking(
        section, -state["p_l"], state["mx_l"], state["my_l"], state["nl"],
        -state["p_s"], state["mx_s"], state["my_s"], state["ns"],
        fctm=state["fctm"], n_mult=n_mult, prestress_stress=locked)
    if lam_t < cr_l.lambda_cr:
        cracked, lambda_cr, sigma_ct = crk_t, lam_t, sig_t
    else:
        cracked, lambda_cr, sigma_ct = (cr_l.cracked, cr_l.lambda_cr,
                                        cr_l.sigma_ct)
    replay = dict(
        state=state, elastic_ran=True, blocks=blocks, moduli=moduli,
        bar_ids=bar_ids, tendon_ids=tendon_ids, phi_used=phi_used,
        k1_bars=k1_bars, cracked=cracked, lambda_cr=lambda_cr,
        sigma_ct=sigma_ct, converged=converged, result=result,
        active=bool(state["cw"] and cracked),
    )
    if not replay["active"]:
        replay["crack_output"] = sls_core.crack_outputs(
            {label: None for label in CASE_LABELS_BASE}, valid=converged)
        return replay
    if state["edition"] != "2004":
        raise TraceValidationError(
            "CT-009 covers the retained 2004 crack branch only; the 2023 "
            "methods are the next slice"
        )
    _reject_2023_sources(blocks)
    state["code"] = _text(inp.get("sls_code"), "sls_code")
    state["xi"] = (_number(inp.get("sls_tendon_xi", 0.0), "sls_tendon_xi",
                           nonnegative=True) if nt else 0.0)
    cw_stress = np.asarray(result.bar_stress_total, dtype=float)
    if locked is not None:
        cw_stress = cw_stress - locked
    short_state = dataclasses.replace(result.short_term, bar_stress=cw_stress)
    reinforcement_types = ["mild"] * nb + ["prestress"] * nt
    tendon_xi = (None if not nt or state["xi"] <= 0.0
                 else [1.0] * nb + [state["xi"]] * nt)

    def _cw(cracked_state, n, kt, coarse):
        return evaluate_crack_width(
            section, cracked_state, n, fctm=state["fctm"], Es=list(moduli),
            kt=kt, bar_diameter=phi, k1=k1_bars,
            k3_cover_dependent=state["dk"], include_hx_term=include_hx,
            coarse=coarse, edition="2004", n_mult=n_mult,
            reinforcement_types=reinforcement_types, bond_ratio_xi=tendon_xi)

    # Retained call order: long fine, short fine, then the DK coarse pair.
    evaluations = {
        "long-term": {False: _cw(cr_l.cracked_state, state["nl"], 0.4, False)},
        "short-term": {False: _cw(short_state, state["ns"], 0.6, False)},
    }
    if state["dk"]:
        evaluations["long-term"][True] = _cw(
            cr_l.cracked_state, state["nl"], 0.4, True)
        evaluations["short-term"][True] = _cw(
            short_state, state["ns"], 0.6, True)
    dicts = {name: {coarse: _crack_dict(evaluation.result, bar_ids, tendon_ids)
                    for coarse, evaluation in per_case.items()}
             for name, per_case in evaluations.items()}
    # Retained table rule: four cases exactly when a coarse result exists.
    coarse_present = state["dk"] and (
        dicts["long-term"][True] is not None
        or dicts["short-term"][True] is not None)
    if coarse_present:
        labels = CASE_LABELS_DK
        cases = dict(zip(CASE_LABELS_DK, (
            dicts["long-term"][False], dicts["short-term"][False],
            dicts["long-term"][True], dicts["short-term"][True])))
    else:
        labels = CASE_LABELS_BASE
        cases = dict(zip(CASE_LABELS_BASE, (
            dicts["long-term"][False], dicts["short-term"][False])))
    replay.update(
        evaluations=evaluations, dicts=dicts, labels=labels, cases=cases,
        planes={"long-term": cr_l.cracked_state, "short-term": short_state},
        ratios={"long-term": state["nl"], "short-term": state["ns"]},
        crack_output=sls_core.crack_outputs(cases, valid=converged),
    )
    return replay


def _elements(replay):
    blocks = replay["blocks"]
    return tuple(
        ElementShape(kind, element_id, block.material_id)
        for kind, ids, items in (("bar", replay["bar_ids"], blocks.bars),
                                 ("tendon", replay["tendon_ids"],
                                  blocks.tendons))
        for element_id, block in zip(ids, items)
    )


def _case_evidence(replay, name, context, shape_elements):
    state = replay["state"]
    variants = []
    for coarse, evaluation in replay["evaluations"][name].items():
        if evaluation.status == "CALCULATED":
            result = evaluation.result
            candidates = tuple(CandidateShape(c.bar_index, c.sr_max_geometric)
                               for c in result.candidates)
            variants.append(VariantShape(coarse, "CALCULATED", "", candidates))
        else:
            variants.append(VariantShape(coarse, evaluation.status,
                                         evaluation.reason, ()))
    case = CaseShape(
        name, tuple(variants), f"ct-009-{context_id(context)}-{name}",
        context_axes(context, crack_case=name, crack_edition="2004",
                     dk_na=str(state["dk"]).lower(),
                     variant_count=str(len(variants))),
    )
    plane = replay["planes"][name]
    values: dict[str, Any] = {
        "input-cw-enabled": 1.0, "input-dk-na": float(state["dk"]),
        "input-edition-2004": 1.0, "input-fctm": state["fctm"],
        "input-phi-override": state["phi"], "input-k1": state["k1"],
        "input-modular-ratio": replay["ratios"][name],
        "input-axial-long": state["p_l"], "input-mx-long": state["mx_l"],
        "input-my-long": state["my_l"],
        "normalised-crack-inputs": 1.0,
        "upstream-plane-eps0": float(plane.eps0),
        "upstream-plane-kx": float(plane.kx),
        "upstream-plane-ky": float(plane.ky),
    }
    if state["dk"]:
        values["input-member-type"] = float(state["slab"])
    if replay["blocks"].tendons:
        values["input-tendon-xi"] = state["xi"]
    if name == "short-term":
        values.update({"input-axial-short": state["p_s"],
                       "input-mx-short": state["mx_s"],
                       "input-my-short": state["my_s"]})
    stresses = np.asarray(plane.bar_stress, dtype=float) / 1000.0
    for index, element in enumerate(shape_elements):
        prefix = element_prefix(index, element)
        values[f"{prefix}-es"] = float(replay["moduli"][index])
        values[f"{prefix}-diameter"] = float(replay["phi_used"][index])
        values[f"{prefix}-k1"] = float(replay["k1_bars"][index])
        values[f"upstream-{prefix}-stress"] = float(stresses[index])
    codes = []
    for variant in case.variants:
        v = "coarse" if variant.coarse else "fine"
        if variant.status != "CALCULATED":
            values[disposition_id(v, variant.reason)] = 1.0
            values[f"{v}-state"] = CRACK_STATE_CODES[variant.status]
            codes.append(CRACK_STATE_CODES[variant.status])
            continue
        result = replay["evaluations"][name][variant.coarse].result
        values.update({f"{v}-hc-ef": result.hc_ef, f"{v}-ac-eff": result.ac_eff,
                       f"{v}-rho-p-eff": result.rho_p_eff,
                       f"{v}-governing": float(result.gov_bar),
                       f"{v}-wk": result.wk,
                       f"{v}-state": CRACK_STATE_CODES["CALCULATED"]})
        codes.append(CRACK_STATE_CODES["CALCULATED"])
        for candidate in result.candidates:
            c = f"{v}-candidate-{candidate.bar_index:02d}"
            values.update({
                f"{c}-sigma-s": candidate.sigma_s,
                f"{c}-cover": candidate.cover,
                f"{c}-esm-ecm": candidate.esm_ecm,
                f"{c}-sr-max": candidate.sr_max,
                f"{c}-wk": candidate.wk,
            })
    values[f"ct-009-{name}-result"] = max(codes)
    return case, values


def _output_evidence(replay, context):
    state = replay["state"]
    labels = replay["labels"]
    cases = replay["cases"]
    available = tuple(cases[label] is not None for label in labels)
    output = replay["crack_output"]
    shape = OutputShape(
        labels, available, output["calculation_state"],
        f"ct-009-{context_id(context)}-crack-output",
        context_axes(context, crack_edition="2004",
                     crack_state=output["calculation_state"].lower().replace(
                         " ", "-"),
                     dk_na=str(state["dk"]).lower()),
    )
    values: dict[str, Any] = {
        "input-cw-enabled": float(state["cw"]),
        "input-dk-na": float(state["dk"]),
        "upstream-converged": float(replay["converged"]),
    }
    for index, (label, present) in enumerate(zip(labels, available)):
        token = case_label_token(label)
        values[f"case-{token}-available"] = float(present)
        if present:
            values[f"case-{token}-wk"] = float(cases[label]["wk"])
    # The retained governing-case selection only exists on the CALCULATED
    # branch; on the INVALID / NOT APPLICABLE branches (case is None) the
    # step is sealed as an explicit absent-by-state disposition, never a
    # fabricated finite argmax.
    states: dict[str, TraceResult] = {}
    if output["calculation_state"] == "CALCULATED":
        values["governing-case"] = float(labels.index(output["case"]))
    else:
        states["governing-case"] = TraceResult(
            RESULT_UNDEFINED, None, _NO_GOVERNING_REASON)
    values["ct-009-crack-output-result"] = CRACK_STATE_CODES[
        output["calculation_state"]]
    return shape, values, states


def _validate_crack_dict(candidate, expected, label):
    if expected is None:
        if candidate is not None:
            raise TraceValidationError(f"{label} must be null")
        return
    if tuple(expected) != CRACK_KEYS:
        raise TraceValidationError(_DRIFT)
    candidate = _retained_mapping(candidate, CRACK_KEYS, (), label)
    for key in CRACK_KEYS:
        if key == "candidates":
            items = _sequence(candidate[key], f"{label}.candidates")
            if len(items) != len(expected[key]):
                raise TraceValidationError(
                    f"{label}.candidates cardinality differs")
            for index, (actual, wanted) in enumerate(zip(items, expected[key])):
                if tuple(wanted) != CANDIDATE_KEYS:
                    raise TraceValidationError(_DRIFT)
                actual = _retained_mapping(actual, CANDIDATE_KEYS, (),
                                           f"{label}.candidates[{index}]")
                for name in CANDIDATE_KEYS:
                    _compare_value(actual[name], wanted[name],
                                   f"{label}.candidates[{index}].{name}")
        else:
            _compare_value(candidate[key], expected[key], f"{label}.{key}")


def _validate_output(candidate, expected, label):
    if tuple(expected) != OUTPUT_KEYS:
        raise TraceValidationError(_DRIFT)
    candidate = _retained_mapping(candidate, OUTPUT_KEYS, (), label)
    for key in OUTPUT_KEYS:
        _compare_value(candidate[key], expected[key], f"{label}.{key}")


def _validate_surfaces(eout, replay):
    state = replay["state"]
    # Upstream consistency with the CT-005-validated published surfaces. A
    # retained non-converged solve may publish non-finite values; they are
    # compared truthfully, never replaced or silently accepted.
    plane = _sequence(eout.get("stress_plane"), "elastic stress plane")
    short = replay["result"].short_term
    if len(plane) != 3:
        raise TraceValidationError("published short plane cardinality differs")
    for actual, wanted, name in zip(plane, (short.eps0, short.kx, short.ky),
                                    ("eps0", "kx", "ky")):
        _compare_retained(actual, float(wanted),
                          f"published short plane {name}")
    published_total = _sequence(eout.get("total"), "published total stresses")
    total = np.asarray(replay["result"].bar_stress_total, dtype=float) / 1000.0
    if len(published_total) != total.size:
        raise TraceValidationError("published stress cardinality differs")
    for index, wanted in enumerate(total):
        _compare_retained(published_total[index], float(wanted),
                          f"published total stress {index}")
    _compare(eout.get("converged"), replay["converged"],
             "published SLS convergence")
    _compare(eout.get("cracked"), replay["cracked"], "published cracked state")
    _compare_retained(eout.get("lambda_cr"), float(replay["lambda_cr"]),
                      "published cracking factor")
    _compare_value(eout.get("fctm"), state["fctm"], "published fctm")
    _compare(eout.get("show_cw"), state["cw"], "published crack switch")
    if "crack_output" not in eout:
        raise TraceValidationError("crack_output surface must be published")

    if not replay["active"]:
        for key in ("crack", "crack_short"):
            if key not in eout or eout.get(key) is not None:
                raise TraceValidationError(
                    f"inactive crack surface {key} must be published as null")
        for key in (*_COARSE_SURFACES, "crack_code", "crack_edition",
                    "crack_member"):
            if key in eout:
                raise TraceValidationError(
                    f"inactive crack surface {key} cannot be published")
        _validate_output(eout.get("crack_output"), replay["crack_output"],
                         "candidate crack output")
        return
    for key in _ACTIVE_SURFACES:
        if key not in eout:
            raise TraceValidationError(
                f"active crack surface {key} must be published")
    if state["dk"]:
        for key in _COARSE_SURFACES:
            if key not in eout:
                raise TraceValidationError(
                    f"DK NA crack surface {key} must be published")
    else:
        for key in _COARSE_SURFACES:
            if key in eout:
                raise TraceValidationError(
                    f"edition-impossible crack surface {key}")
    dicts = replay["dicts"]
    _validate_crack_dict(eout.get("crack"), dicts["long-term"][False],
                         "candidate long crack")
    _validate_crack_dict(eout.get("crack_short"), dicts["short-term"][False],
                         "candidate short crack")
    if state["dk"]:
        _validate_crack_dict(eout.get("crack_coarse"),
                             dicts["long-term"][True],
                             "candidate long coarse crack")
        _validate_crack_dict(eout.get("crack_short_coarse"),
                             dicts["short-term"][True],
                             "candidate short coarse crack")
    _compare(eout.get("crack_code"), state["code"], "candidate crack code")
    _compare(eout.get("crack_edition"), "2004", "candidate crack edition")
    _compare(eout.get("crack_member"),
             state["member"] if state["dk"] else None,
             "candidate crack member")
    _validate_output(eout.get("crack_output"), replay["crack_output"],
                     "candidate crack output")


def _calculation(calculation_id, title, axes, specs, values, states=None):
    units = {spec.step_id: spec.unit for spec in specs}
    states = {} if states is None else states
    steps = []
    for spec in specs:
        override = states.get(spec.step_id)
        if override is not None:
            result = override
            substituted = f"{spec.step_id} = {override.state}"
        elif math.isnan(numeric := float(values[spec.step_id])):
            result = TraceResult(RESULT_UNDEFINED, None, _NAN_REASON)
            substituted = f"{spec.step_id} = undefined"
        elif math.isinf(numeric):
            state = (RESULT_POSITIVE_INFINITY if numeric > 0.0
                     else RESULT_NEGATIVE_INFINITY)
            result = TraceResult(state, None, _INFINITE_REASON)
            substituted = f"{spec.step_id} = {state}"
        else:
            result = TraceResult(RESULT_FINITE, numeric)
            substituted = f"{spec.step_id} = {numeric:.17g} {spec.unit.symbol}"
        if spec.step_id.startswith("case-") and spec.step_id.endswith("-wk"):
            actual = "wk_case = retained governing crack width of this case"
        else:
            expressions = (
                ("-esm-ecm", "esm-ecm = max((sigma_s - kt fct/rho (1+n rho))"
                             "/Es, 0.6 sigma_s/Es)"),
                ("-sr-max", "sr_max = k3' c + k1 k2 k4 phi/rho or 1.3 (h-x)"),
                ("-hc-ef", "hc_ef = min(2.5(h-d), [(h-x)/3], h/2) or "
                           "centroid-matched coarse band"),
                ("-rho-p-eff", "rho_p_eff = As_eff / Ac_eff"),
                ("-wk", "wk = [0.5 if coarse] sr_max (esm - ecm)"),
                ("-governing", "governing = argmax wk over candidates"),
                ("governing-case", "governing case = argmax wk over "
                                   "available retained cases when the crack "
                                   "output is CALCULATED; otherwise the "
                                   "retained output makes no selection"),
                ("-state", "retained state code: CALCULATED=1, NOT ASSESSED=3,"
                           " NOT APPLICABLE=4, INVALID=5"),
                ("-result", "retained state code: CALCULATED=1, NOT ASSESSED=3,"
                            " NOT APPLICABLE=4, INVALID=5"),
            )
            actual = next((text for suffix, text in expressions
                           if spec.step_id.endswith(suffix)),
                          f"Bind {spec.title.lower()}")
        steps.append(TraceStep(
            spec.step_id, spec.title,
            tuple(TraceDependency(name, units[name])
                  for name in spec.dependencies),
            spec.quantity_role, spec.source, spec.step_id, spec.unit,
            actual, substituted, result,
        ))
    return TraceCalculation(
        calculation_id, COVERAGE_ID, title, METHOD_ID, axes,
        steps[-1].step_id, tuple(steps), (),
        ("Crack widths are output-only quantities; no limit or compliance "
         "verdict is implied.",),
    )


def _expected_bundle(inp, out, input_sha256, result_sha256, context):
    replay = _replay(inp, context)
    eout = out.get("elastic")
    if not replay.get("elastic_ran"):
        if isinstance(eout, Mapping) and any(
                key in eout for key in _CRACK_SURFACES):
            raise TraceValidationError(
                "inactive CT-009 input cannot carry crack surfaces")
        return None
    eout = _mapping(eout, "retained elastic result")
    _validate_surfaces(eout, replay)
    if not replay["active"]:
        return None
    elements = _elements(replay)
    flags = (replay["state"]["dk"], replay["state"]["slab"],
             bool(replay["blocks"].tendons))
    calculations = []
    cases = []
    for name in ("long-term", "short-term"):
        case, values = _case_evidence(replay, name, context, elements)
        cases.append(case)
        calculations.append(_calculation(
            case.calculation_id, f"Crack width {name} case", case.axes,
            expected_case_steps(CrackShape(*flags, elements, tuple(cases),
                                           None), case),
            values))
    output_shape, output_values, output_states = _output_evidence(
        replay, context)
    shape = CrackShape(*flags, elements, tuple(cases), output_shape)
    calculations.append(_calculation(
        output_shape.calculation_id, "Crack output selection",
        output_shape.axes, expected_output_steps(shape), output_values,
        output_states))
    bundle = create_bundle(
        input_sha256=input_sha256, result_sha256=result_sha256,
        calculations=tuple(calculations),
    )
    audit_trace_registry(bundle, expected_registry(shape))
    return bundle


def build_crack_trace_family(
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build and seal the applicable CT-009 crack-width family."""

    try:
        out = _mapping(out, "retained result mapping")
        return _expected_bundle(inp, out, input_sha256, result_sha256,
                                {} if context is None else context)
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError,
            ValueError) as exc:
        raise TraceValidationError(
            f"invalid CT-009 crack evidence: {exc}") from exc


def validate_crack_trace_family(
    bundle: TraceBundle | dict[str, Any] | None,
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Reject stale or coherently resealed CT-009 value/graph/source tampering."""

    expected = build_crack_trace_family(
        inp, out, input_sha256=input_sha256, result_sha256=result_sha256,
        context=context,
    )
    if expected is None:
        if bundle is not None:
            raise TraceValidationError(
                "inactive CT-009 input cannot carry a trace")
        return None
    candidate = validate_bundle(
        bundle, expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError(
            "CT-009 trace differs from authoritative input replay"
        )
    return candidate
