"""Solver-owned unpublished CT-010 reinforcement fatigue trace (PR-08D.3a).

The family binds the retained fatigue composition exactly: the app validates
the direct inputs first (``fatigue_analysis.validation_errors``) and only then
runs the retained engine (``analyse_grouped_spectra`` wrapping
``solve_fatigue_bin`` / ``solve_elastic_combined``). The invalid branch is a
legitimate failed evidence state selected before candidate numerics; the valid
branch replays the retained S-N, mixed-bond, Palmgren-Miner and yield-screen
kernels and binds the engine's published bin states as evidence. Reinforcement
members exist per retained (spectrum, element) assignment when
``fatigue_check_steel`` is true; the concrete fatigue members are the named
PR-08D.3b siblings.

Upstream boundary rule: every leaf sealed under the engine-evidence source is
CONSUMED from the published ``out["fatigue"]`` payload, which is first
cross-checked exactly against the authoritative replay; the replay itself is
composition, never evidence. A divergent engine therefore fails the build
closed instead of sealing relabeled values.
"""

from __future__ import annotations

import dataclasses
import math
import pathlib
import sys
from collections.abc import Mapping
from typing import Any

from .calculation_trace import (
    RESULT_FAILED, RESULT_FINITE, RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY, RESULT_UNDEFINED, TraceBundle, TraceCalculation,
    TraceDependency, TraceResult, TraceStep, TraceValidationError,
    create_bundle, validate_bundle,
)
from .elastic import CombinedElasticResult
from .fatigue import (
    FatigueBinState, FatigueSpectrumResult, ReinforcementBinResult,
    ReinforcementFatigueProperties, ReinforcementFatigueResult,
)
from .fatigue_trace_contract import (
    BASIS_KEYS, BIN_RESULT_FIELDS, BIN_STATE_FIELDS, CHECK_KEYS,
    CONCRETE_EXCLUDED_BIN_FIELDS, CONCRETE_EXCLUDED_KEYS,
    CONCRETE_EXCLUDED_RESULT_FIELDS, COVERAGE_ID, EDITIONS, FACTOR_KEYS,
    INVALID_KEYS, METHOD_ID, PROPERTY_FIELDS, RAW_SOLVER_FIELDS,
    RESULT_FIELDS, SPECTRUM_RESULT_FIELDS, STATUS_CODES, VALID_KEYS,
    ElementMemberShape, FatigueShape, InvalidShape, OutputShape,
    SpectrumOutputShape, bin_description_id, bin_prefix,
    expected_element_steps,
    expected_invalid_steps, expected_output_steps, expected_registry,
    invalid_error_id, material_leaf_id, output_element_prefix, spectrum_prefix,
    trace_identity_token,
)
from .section_trace_blocks import context_axes, context_id, section_trace_blocks
from .torsion_trace import _boolean, _mapping, _number, _retained_mapping
from .trace_registry import audit_trace_registry


_DRIFT = "authoritative CT-010 output inventory drifted"
_PLASTIC_ACTION_KEYS = frozenset(("P_pl", "Mx_pl", "My_pl"))
_SECTION_ERROR_KEYS = ("geometry_error", "void_error", "steel_error",
                       "material_error")
_INFINITE_REASON = (
    "Retained fatigue quantity is unbounded; the retained value is "
    "represented, never replaced by a fabricated finite number."
)
_NAN_REASON = (
    "Retained fatigue quantity is undefined; the retained value is "
    "represented, never replaced by a fabricated finite number."
)
_ASSUMPTIONS = (
    "Retained reinforcement fatigue replay; the concrete fatigue members "
    "are the named PR-08D.3b siblings.",
)
# Field-order pins for the exact candidate closure.
_FIELD_PINS = {
    ReinforcementFatigueProperties: PROPERTY_FIELDS,
    ReinforcementBinResult: BIN_RESULT_FIELDS,
    ReinforcementFatigueResult: RESULT_FIELDS,
    FatigueBinState: BIN_STATE_FIELDS,
    FatigueSpectrumResult: SPECTRUM_RESULT_FIELDS,
}
# Named excluded siblings: presence and type are pinned, values carry no
# CT-010 guarantee until PR-08D.3b (concrete) / CT-005 (raw solver planes).
_SKIP_FIELDS = {
    FatigueBinState: frozenset(
        (*CONCRETE_EXCLUDED_BIN_FIELDS, *RAW_SOLVER_FIELDS)),
    FatigueSpectrumResult: frozenset(CONCRETE_EXCLUDED_RESULT_FIELDS),
}

_BIN_ACTION_COLUMNS = (
    ("n-long", "n_long_ed_kn"), ("mx-long", "mx_long_ed_knm"),
    ("my-long", "my_long_ed_knm"), ("n-short", "n_short_ed_kn"),
    ("mx-short", "mx_short_ed_knm"), ("my-short", "my_short_ed_knm"),
)


def _app_modules():
    """The retained fatigue adapter is an app-layer module by design."""

    try:
        import fatigue_analysis
        import fatigue_inputs
    except ImportError:  # pragma: no cover - direct sector-only imports
        sys.path.insert(0, str(
            pathlib.Path(__file__).resolve().parent.parent / "app"))
        import fatigue_analysis
        import fatigue_inputs
    return fatigue_analysis, fatigue_inputs


def _flag(inp: Mapping[str, Any], key: str) -> bool:
    """Exact-typed check flag; an absent widget key is the retained False."""

    if key not in inp or inp.get(key) is None:
        return False
    return _boolean(inp.get(key), key)


def _exact(actual: Any, expected: Any, label: str) -> None:
    """Exact closure of byte-identical retained kernel outputs.

    The candidate payload and the authoritative replay run the same retained
    kernels on the same inputs, so numeric closure is EXACT (the CT-011
    lesson): a tolerant comparator would open a reseal window.
    """

    if expected is None or type(expected) in {bool, str, int}:
        if type(actual) is not type(expected) or actual != expected:
            raise TraceValidationError(
                f"{label} differs from authoritative replay")
        return
    if type(expected) is float:
        if type(actual) is not float or (
                actual != expected
                and not (math.isnan(actual) and math.isnan(expected))):
            raise TraceValidationError(
                f"{label} differs from authoritative replay")
        return
    if dataclasses.is_dataclass(expected) and not isinstance(expected, type):
        if type(actual) is not type(expected):
            raise TraceValidationError(f"{label} has the wrong retained type")
        names = tuple(item.name for item in dataclasses.fields(type(expected)))
        pin = _FIELD_PINS.get(type(expected))
        if pin is not None and names != pin:
            raise TraceValidationError(_DRIFT)
        skip = _SKIP_FIELDS.get(type(expected), frozenset())
        for name in names:
            got = getattr(actual, name)
            wanted = getattr(expected, name)
            if name in skip:
                if type(got) is not type(wanted):
                    raise TraceValidationError(
                        f"{label}.{name} has the wrong retained type")
                if (name in RAW_SOLVER_FIELDS and wanted is not None
                        and type(wanted) is not CombinedElasticResult):
                    raise TraceValidationError(_DRIFT)
                continue
            _exact(got, wanted, f"{label}.{name}")
        return
    if isinstance(expected, Mapping):
        actual = _mapping(actual, label)
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(
                f"{label} retained keys/order differ: {tuple(actual)!r}")
        for key in expected:
            _exact(actual[key], expected[key], f"{label}.{key}")
        return
    if type(expected) in {tuple, list}:
        if type(actual) is not type(expected) or len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality differs")
        for index, (got, wanted) in enumerate(zip(actual, expected)):
            _exact(got, wanted, f"{label}[{index}]")
        return
    raise TraceValidationError(f"{label} has an unsupported retained type")


def _pin_retained_shapes(fatigue_inputs) -> None:
    """Fail closed when the retained inventories this slice froze drift."""

    if tuple(fatigue_inputs.EDITIONS) != EDITIONS:
        raise TraceValidationError(_DRIFT)
    for kind, pin in _FIELD_PINS.items():
        if tuple(item.name for item in dataclasses.fields(kind)) != pin:
            raise TraceValidationError(_DRIFT)


def _replay(inp: Mapping[str, Any]) -> dict[str, Any]:
    """Replay the retained composition (app _run_fatigue_or_invalid) exactly.

    Validation runs FIRST from direct inputs; the engine only runs on a clean
    preflight. Fatigue is computed once per run (case-table independent) and
    never suppresses or masks other results.
    """

    if "fatigue_on" not in inp or inp.get("fatigue_on") is None:
        return {"active": False}
    if not _boolean(inp.get("fatigue_on"), "fatigue_on"):
        return {"active": False}
    if inp.get("section") is None or any(
            inp.get(key) for key in _SECTION_ERROR_KEYS):
        # The retained run_analysis publishes no fatigue surface at all here.
        return {"active": False}
    fatigue_analysis, fatigue_inputs = _app_modules()
    _pin_retained_shapes(fatigue_inputs)
    # Exact boundary typing for the direct gate flags on both branches.
    check_steel = _flag(inp, "fatigue_check_steel")
    _flag(inp, "fatigue_check_concrete")
    errors = tuple(fatigue_analysis.validation_errors(inp))
    if errors:
        return {
            "active": True, "branch": "invalid",
            "payload": fatigue_analysis.invalid_result(inp, list(errors)),
        }
    # Exact typing of the direct numeric inputs on the calculated branch
    # (the retained validation tolerates numeric text; the trace does not).
    for key in ("nl", "ns", "fatigue_gamma_ff"):
        _number(inp.get(key), key, positive=True)
    if check_steel:
        _number(inp.get("fatigue_gamma_s"), "fatigue_gamma_s", positive=True)
    payload = fatigue_analysis.run_analysis(inp)
    prepared = fatigue_analysis.prepare(inp)
    groups = fatigue_inputs.spectrum_groups(
        inp[fatigue_inputs.SPECTRUM_TABLE_KEY])
    return {
        "active": True, "branch": "valid", "payload": payload,
        "prepared": prepared, "groups": groups,
    }


def _scoped_blocks(inp):
    """Section/material identity blocks scoped to this family."""

    scoped = {key: value for key, value in inp.items()
              if key not in _PLASTIC_ACTION_KEYS}
    return section_trace_blocks(scoped)


def _reject_2023_sources(blocks) -> None:
    """A used 2023 material law can never produce finite CT-010 evidence.

    Scanned only on the active reinforcement branch: the retained disabled,
    fenced and invalid states are legitimate absence/failed states whatever
    material edition is assigned (branch selection from direct inputs first).
    The 2023 fatigue EDITION stays a legitimate retained method.
    """

    for block in (blocks.concrete, *blocks.bars, *blocks.tendons):
        source = block.provenance.source
        if source.citation is not None and "2023" in source.citation.document:
            raise TraceValidationError(
                "2023 material provenance is published but not implemented "
                "for CT-010"
            )


def _validate_invalid(candidate: Any, expected: Mapping[str, Any]) -> None:
    if tuple(expected) != INVALID_KEYS:
        raise TraceValidationError(_DRIFT)
    candidate = _retained_mapping(candidate, INVALID_KEYS, (),
                                  "candidate invalid fatigue result")
    # The pinned asymmetry: the leading ``valid`` key exists here only.
    if candidate["valid"] is not False or expected["valid"] is not False:
        raise TraceValidationError(
            "candidate invalid fatigue result.valid must be exactly False")
    for key in INVALID_KEYS:
        _exact(candidate[key], expected[key],
               f"candidate invalid fatigue result.{key}")


def _validate_valid(candidate: Any, expected: Mapping[str, Any]) -> None:
    if tuple(expected) != VALID_KEYS:
        raise TraceValidationError(_DRIFT)
    if "valid" in _mapping(candidate, "candidate fatigue result"):
        raise TraceValidationError(
            "valid fatigue result cannot carry the invalid-branch valid key")
    candidate = _retained_mapping(candidate, VALID_KEYS, (),
                                  "candidate fatigue result")
    for pin, keys in (("checks", CHECK_KEYS), ("partial_factors", FACTOR_KEYS),
                      ("basis", BASIS_KEYS)):
        if tuple(expected[pin]) != keys:
            raise TraceValidationError(_DRIFT)
    for key in VALID_KEYS:
        if key in CONCRETE_EXCLUDED_KEYS:
            # Named excluded siblings (PR-08D.3b): presence and position are
            # pinned by the key inventory and their exact retained type;
            # values carry no CT-010 members.
            if type(candidate[key]) is not type(expected[key]):
                raise TraceValidationError(
                    f"candidate fatigue {key} retained type differs from "
                    "authoritative replay")
            continue
        _exact(candidate[key], expected[key], f"candidate fatigue {key}")


def _calculation(calculation_id, title, axes, specs, values, *,
                 failed_reason=None):
    units = {spec.step_id: spec.unit for spec in specs}
    steps = []
    for spec in specs:
        final = spec.quantity_role == "final_result"
        if failed_reason is not None and final:
            result = TraceResult(RESULT_FAILED, None, failed_reason)
            substituted = f"{spec.step_id} = failed"
        else:
            numeric = float(values[spec.step_id])
            if math.isnan(numeric):
                result = TraceResult(RESULT_UNDEFINED, None, _NAN_REASON)
                substituted = f"{spec.step_id} = undefined"
            elif math.isinf(numeric):
                state = (RESULT_POSITIVE_INFINITY if numeric > 0.0
                         else RESULT_NEGATIVE_INFINITY)
                result = TraceResult(state, None, _INFINITE_REASON)
                substituted = f"{spec.step_id} = {state}"
            else:
                result = TraceResult(RESULT_FINITE, numeric)
                substituted = (
                    f"{spec.step_id} = {numeric:.17g} {spec.unit.symbol}")
        steps.append(TraceStep(
            spec.step_id, spec.title,
            tuple(TraceDependency(name, units[name])
                  for name in spec.dependencies),
            spec.quantity_role, spec.source, spec.step_id, spec.unit,
            _actual_expression(spec), substituted, result,
        ))
    return TraceCalculation(
        calculation_id, COVERAGE_ID, title, METHOD_ID, axes,
        steps[-1].step_id, tuple(steps), (), _ASSUMPTIONS,
    )


_EXACT_EXPRESSIONS = {
    "normalised-fatigue-inputs": "Complete validated fatigue input identity",
    "damage-total": "D = sum n_i/N_i over bins (Palmgren-Miner)",
    "governing-damage-bin": "governing = argmax D_i over bins",
    "yield-utilisation": "yield utilisation = max over bins",
    "governing-yield-bin": "governing = argmax yield utilisation over bins",
    "utilisation": "utilisation = max(D, yield utilisation)",
    "converged": "converged = all engine bin solves converged",
    "reinforcement-converged": "converged = all element assessments converged",
    "reinforcement-passed": ("worst-first over elements: FAIL = 0 when any "
                             "element fails, else PASS = 1"),
    "governing-spectrum": "governing = argmax utilisation over spectra",
    "family-utilisation": "utilisation = governing spectrum utilisation",
}
_SUFFIX_EXPRESSIONS = (
    ("-design-stress-range",
     "delta_sigma_Ed = |sigma_total(gamma_Ff) - sigma_long|"),
    ("-stress-range", "delta_sigma = |sigma_total - sigma_long| "
                      "(bond-corrected fatigue totals)"),
    ("-bond-adjustment",
     "bond adjustment = delta_sigma / delta_sigma_elastic"),
    ("-sn-exponent",
     "k = k1 if delta_sigma_Ed >= delta_sigma_Rsk/gamma_s else k2; "
     "retained k = 0 with unbounded life when delta_sigma_Ed = 0"),
    ("-log10-cycles-to-failure",
     "log10 N = log10 N* + k log10(delta_sigma_Rsk/(gamma_s delta_sigma_Ed))"),
    ("-damage", "D_i = n_i / N_i"),
    ("-yield-limit",
     "limit = fytk/gamma_s (tension) or fyck/gamma_s (compression)"),
    ("-yield-utilisation",
     "yield utilisation = |governing sigma| / limit"),
    ("-governing-element", "governing = argmax utilisation over elements"),
    ("-utilisation", "utilisation = max over reinforcement elements"),
)


def _actual_expression(spec) -> str:
    if spec.quantity_role in ("computed_intermediate", "final_result"):
        if spec.step_id in _EXACT_EXPRESSIONS:
            return _EXACT_EXPRESSIONS[spec.step_id]
        if spec.step_id.startswith("invalid-error-"):
            return "Retained fatigue preflight error published as evidence"
        if spec.step_id.endswith("-result"):
            return ("PASS = 1 when converged and D <= 1.0 and yield "
                    "utilisation <= 1.0, else FAIL = 0")
        for suffix, text in _SUFFIX_EXPRESSIONS:
            if spec.step_id.endswith(suffix):
                return text
    return f"Bind {spec.title.lower()}"


def _element_shape(context, si, spectrum_name, ei, props, material_id, bins,
                   bin_descriptions, blocks, mixed, edition):
    calculation_id = (
        f"ct-010-{context_id(context)}-s{si:02d}-"
        f"{trace_identity_token(spectrum_name)}-e{ei:02d}-"
        f"{trace_identity_token(props.element_id)}-"
        f"{trace_identity_token(material_id)}-"
        f"{trace_identity_token(props.detail_id)}"
    )
    return ElementMemberShape(
        spectrum_index=si, spectrum_name=spectrum_name, element_index=ei,
        kind=props.kind, element_id=props.element_id,
        material_id=material_id, detail_id=props.detail_id, bins=bins,
        bin_descriptions=bin_descriptions, blocks=blocks,
        has_fyck=props.fyck_mpa is not None,
        has_bond_xi=props.bond_ratio_xi is not None,
        has_bond_diameter=props.bond_equivalent_diameter_mm is not None,
        mixed=mixed, edition=edition, calculation_id=calculation_id,
        axes=context_axes(context, member="reinforcement",
                          spectrum_index=str(si), element_index=str(ei),
                          bin_count=str(len(bins)), fatigue_edition=edition,
                          mixed=str(mixed).lower()),
    )


def _element_values(shape, rows, prepared, result, props, es):
    if result.element_id != props.element_id:
        raise TraceValidationError(_DRIFT)
    values: dict[str, Any] = {
        "input-check-steel": 1.0,
        "input-edition": float(EDITIONS.index(shape.edition)),
        "input-gamma-s": float(prepared.gamma_s),
        "input-gamma-ff": float(prepared.gamma_ff),
        "input-nl": float(prepared.nl),
        "input-ns": float(prepared.ns),
        "input-diameter": float(props.diameter_mm),
        "detail-n-star": float(props.n_star),
        "detail-k1": float(props.k1),
        "detail-k2": float(props.k2),
        "detail-delta-sigma-rsk": float(props.delta_sigma_rsk_mpa),
        "detail-fytk": float(props.fytk_mpa),
        "element-es": float(es),
        "normalised-fatigue-inputs": 1.0,
    }
    for ring_index, ring in enumerate(shape.blocks.geometry.rings):
        for point_index, (x, y) in enumerate(ring):
            prefix = f"geometry-ring-{ring_index:03d}-point-{point_index:04d}"
            values[f"{prefix}-x"] = x
            values[f"{prefix}-y"] = y
    for kind, elements in (
        ("bar", shape.blocks.geometry.bars),
        ("tendon", shape.blocks.geometry.tendons),
    ):
        for index, element in enumerate(elements):
            prefix = f"geometry-{kind}-{index:04d}"
            values[f"{prefix}-x"] = element.x
            values[f"{prefix}-y"] = element.y
            values[f"{prefix}-area"] = element.area
    values["geometry-vector"] = 1.0
    for material in (
        shape.blocks.concrete,
        *shape.blocks.bars,
        *shape.blocks.tendons,
    ):
        for name, value in material.values:
            values[material_leaf_id(material, name)] = value
    values["material-vector"] = 1.0
    if shape.has_fyck:
        values["detail-fyck"] = float(props.fyck_mpa)
    if shape.has_bond_xi:
        values["detail-bond-xi"] = float(props.bond_ratio_xi)
    if shape.has_bond_diameter:
        values["detail-bond-eq-diameter"] = float(
            props.bond_equivalent_diameter_mm)
    if len(result.bins) != len(shape.bins) or len(rows) != len(shape.bins):
        raise TraceValidationError(_DRIFT)
    for index, (name, description, row, bin_result) in enumerate(
            zip(shape.bins, shape.bin_descriptions, rows, result.bins)):
        if bin_result.bin_name != name:
            raise TraceValidationError(_DRIFT)
        prefix = bin_prefix(index, name)
        values[bin_description_id(index, name, description)] = 1.0
        values[f"{prefix}-cycles"] = float(row["cycles"])
        for suffix, column in _BIN_ACTION_COLUMNS:
            values[f"{prefix}-{suffix}"] = float(row[column])
        values.update({
            f"{prefix}-upstream-converged": float(bin_result.converged),
            f"{prefix}-upstream-stress-long": bin_result.stress_long_mpa,
            f"{prefix}-upstream-stress-total": bin_result.stress_total_mpa,
            f"{prefix}-upstream-stress-total-elastic":
                bin_result.stress_total_elastic_mpa,
            f"{prefix}-upstream-stress-total-design":
                bin_result.stress_total_design_mpa,
            f"{prefix}-stress-range": bin_result.stress_range_mpa,
            f"{prefix}-bond-adjustment": bin_result.bond_adjustment,
            f"{prefix}-design-stress-range":
                bin_result.design_stress_range_mpa,
            f"{prefix}-sn-exponent": bin_result.sn_exponent,
            f"{prefix}-log10-cycles-to-failure":
                bin_result.log10_cycles_to_failure,
            f"{prefix}-damage": bin_result.damage,
            f"{prefix}-yield-limit": bin_result.yield_limit_mpa,
            f"{prefix}-yield-utilisation": bin_result.yield_utilisation,
        })
    status = STATUS_CODES["PASS" if result.passed else "FAIL"]
    values.update({
        "damage-total": result.damage,
        "governing-damage-bin": float(
            shape.bins.index(result.governing_damage_bin)),
        "yield-utilisation": result.yield_utilisation,
        "governing-yield-bin": float(
            shape.bins.index(result.governing_yield_bin)),
        "utilisation": result.utilisation,
        "converged": float(result.converged),
        "passed": status,
        "ct-010-element-result": status,
    })
    return values


def _output_evidence(payload, names, context):
    joint = payload["checks"]["concrete"]
    spectra = tuple(payload["spectra"])
    shape = OutputShape(
        joint=joint,
        spectra=tuple(
            SpectrumOutputShape(
                name,
                tuple(item.element_id for item in result.reinforcement),
            )
            for name, result in zip(names, spectra)
        ),
        calculation_id=(
            f"ct-010-{context_id(context)}-reinforcement-output"),
        axes=context_axes(context, member="reinforcement-output",
                          spectrum_count=str(len(names)),
                          joint=str(joint).lower()),
    )
    values: dict[str, Any] = {
        "input-check-steel": 1.0,
        "input-check-concrete": float(joint),
    }
    all_converged, all_passed = [], []
    for si, (spectrum, result) in enumerate(zip(shape.spectra, spectra)):
        for ei, (element_id, element) in enumerate(
                zip(spectrum.element_ids, result.reinforcement)):
            prefix = output_element_prefix(si, spectrum.name, ei, element_id)
            values[f"{prefix}-utilisation"] = element.utilisation
            values[f"{prefix}-converged"] = float(element.converged)
            values[f"{prefix}-passed"] = float(element.passed)
            all_converged.append(element.converged)
            all_passed.append(element.passed)
        prefix = spectrum_prefix(si, spectrum.name)
        values[f"{prefix}-governing-element"] = float(
            spectrum.element_ids.index(result.governing_reinforcement_id))
        if not joint:
            values[f"{prefix}-utilisation"] = result.utilisation
    values["reinforcement-converged"] = float(all(all_converged))
    status = STATUS_CODES["PASS" if all(all_passed) else "FAIL"]
    values["reinforcement-passed"] = status
    if not joint:
        values["governing-spectrum"] = float(
            names.index(payload["governing_spectrum"]))
        values["family-utilisation"] = float(payload["utilisation"])
        # On the steel-only branch the retained family verdict is fully
        # reinforcement-derived; the two encodings must agree exactly.
        if (bool(payload["converged"]) != all(all_converged)
                or bool(payload["passed"]) != all(all_passed)):
            raise TraceValidationError(_DRIFT)
    values["ct-010-reinforcement-output-result"] = status
    return shape, values


def _expected_bundle(inp, out, input_sha256, result_sha256, context):
    replay = _replay(inp)
    candidate = out.get("fatigue")
    if not replay["active"]:
        if "fatigue" in out or candidate is not None:
            raise TraceValidationError(
                "inactive CT-010 input cannot carry a fatigue surface")
        return None
    if candidate is None:
        raise TraceValidationError(
            "active CT-010 input must publish the fatigue surface")
    if replay["branch"] == "invalid":
        _validate_invalid(candidate, replay["payload"])
        # Bind the PUBLISHED (now exactly cross-checked) payload as evidence.
        payload = {key: candidate[key] for key in INVALID_KEYS}
        errors = tuple(payload["errors"])
        shape = InvalidShape(
            errors=errors,
            calculation_id=f"ct-010-{context_id(context)}-invalid",
            axes=context_axes(context, member="invalid",
                              error_count=str(len(errors))),
        )
        values: dict[str, Any] = {
            "input-fatigue-on": 1.0,
            "input-check-steel": float(_flag(inp, "fatigue_check_steel")),
            "input-check-concrete": float(
                _flag(inp, "fatigue_check_concrete")),
        }
        for index, message in enumerate(errors):
            values[invalid_error_id(index, message)] = 1.0
        calculation = _calculation(
            shape.calculation_id, "Fatigue invalid input state", shape.axes,
            expected_invalid_steps(shape), values,
            failed_reason=("Retained fatigue validation failed: "
                           + "; ".join(errors)),
        )
        bundle = create_bundle(
            input_sha256=input_sha256, result_sha256=result_sha256,
            calculations=(calculation,),
        )
        audit_trace_registry(bundle, expected_registry(
            FatigueShape((), None, shape)))
        return bundle

    _validate_valid(candidate, replay["payload"])
    # Bind the PUBLISHED (now exactly cross-checked) payload as evidence:
    # the replay is composition, the published surface is the upstream leaf.
    payload = {key: candidate[key] for key in VALID_KEYS}
    if not payload["checks"]["reinforcement"]:
        # No reinforcement members exist: the concrete-only branch is the
        # named PR-08D.3b sibling and supplied candidate bundles fail.
        return None
    prepared = replay["prepared"]
    blocks = _scoped_blocks(inp)
    _reject_2023_sources(blocks)
    material_blocks = (*blocks.bars, *blocks.tendons)
    if (tuple(block.element_id for block in material_blocks)
            != tuple(prepared.solver_element_ids)):
        raise TraceValidationError("fatigue element identity must align")
    mixed = bool(blocks.geometry.bars) and bool(blocks.geometry.tendons)
    edition = payload["edition"]
    if edition not in EDITIONS:
        raise TraceValidationError(_DRIFT)
    names = tuple(replay["groups"])
    spectra = tuple(payload["spectra"])
    if len(names) != len(spectra):
        raise TraceValidationError(_DRIFT)
    element_shapes, calculations = [], []
    for si, (spectrum_name, result) in enumerate(zip(names, spectra)):
        if result.spectrum_name != spectrum_name:
            raise TraceValidationError(_DRIFT)
        rows = replay["groups"][spectrum_name]
        bins = tuple(str(row["name"]) for row in rows)
        bin_descriptions = tuple(str(row["description"]) for row in rows)
        if len(result.reinforcement) != len(prepared.reinforcement):
            raise TraceValidationError(_DRIFT)
        for ei, props in enumerate(prepared.reinforcement):
            block = material_blocks[ei]
            shape = _element_shape(context, si, spectrum_name, ei, props,
                                   block.material_id, bins, bin_descriptions,
                                   blocks, mixed, edition)
            values = _element_values(
                shape, rows, prepared, result.reinforcement[ei], props,
                dict(block.values)["Es"])
            element_shapes.append(shape)
            calculations.append(_calculation(
                shape.calculation_id,
                f"Reinforcement fatigue {spectrum_name} / {props.element_id}",
                shape.axes, expected_element_steps(shape), values))
    output_shape, output_values = _output_evidence(payload, names, context)
    calculations.append(_calculation(
        output_shape.calculation_id, "Reinforcement fatigue output selection",
        output_shape.axes, expected_output_steps(output_shape),
        output_values))
    bundle = create_bundle(
        input_sha256=input_sha256, result_sha256=result_sha256,
        calculations=tuple(calculations),
    )
    audit_trace_registry(bundle, expected_registry(
        FatigueShape(tuple(element_shapes), output_shape, None)))
    return bundle


def build_fatigue_trace_family(
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build and seal the applicable CT-010 reinforcement fatigue family."""

    try:
        out = _mapping(out, "retained result mapping")
        return _expected_bundle(inp, out, input_sha256, result_sha256,
                                {} if context is None else context)
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError,
            ValueError) as exc:
        raise TraceValidationError(
            f"invalid CT-010 fatigue evidence: {exc}") from exc


def validate_fatigue_trace_family(
    bundle: TraceBundle | dict[str, Any] | None,
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Reject stale or coherently resealed CT-010 value/graph/source tampering."""

    expected = build_fatigue_trace_family(
        inp, out, input_sha256=input_sha256, result_sha256=result_sha256,
        context=context,
    )
    if expected is None:
        if bundle is not None:
            raise TraceValidationError(
                "this CT-010 branch cannot carry a reinforcement trace")
        return None
    candidate = validate_bundle(
        bundle, expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError(
            "CT-010 trace differs from authoritative input replay"
        )
    return candidate
