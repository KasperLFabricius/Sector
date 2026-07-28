"""Application adapter for the DS/EN 1992-2 base methodology gate.

The numerical solvers remain owned by their established modules.  This adapter
only reconstructs typed bridge evidence from the exact calculated case payload
and canonical bridge input tables, then delegates every bridge-method verdict to
``sector.bridge``.  It never infers an SLS combination from response duration.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

import bridge_inputs
import fatigue_analysis
import fatigue_inputs
import fatigue_presentation
import result_presentation as presentation
from sector import bridge, conformance
from sector import sls


_STATUS_ORDER = {
    bridge.STATUS_INVALID: 0,
    bridge.STATUS_FAIL: 1,
    bridge.STATUS_REVIEW: 2,
    bridge.STATUS_NOT_ASSESSED: 3,
    bridge.STATUS_NOT_RUN: 4,
    bridge.STATUS_PASS: 5,
    bridge.STATUS_NOT_APPLICABLE: 6,
}


def _status(value) -> str:
    text = str(value or "").strip().upper()
    aliases = {
        "OK": bridge.STATUS_PASS,
        "EXCEEDED": bridge.STATUS_FAIL,
        "NOT CHECKED": bridge.STATUS_NOT_ASSESSED,
    }
    text = aliases.get(text, text)
    return (
        text
        if text in _STATUS_ORDER
        else bridge.STATUS_NOT_ASSESSED
    )


def _finite(value) -> float | None:
    if isinstance(value, bool) or type(value).__name__ == "bool_":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _typed_bool(value) -> bool | None:
    if isinstance(value, bool) or type(value).__name__ == "bool_":
        return bool(value)
    return None


def _sequence(value) -> tuple:
    if value is None or isinstance(
        value,
        (str, bytes, bytearray, Mapping),
    ):
        return ()
    try:
        return tuple(value)
    except TypeError:
        return ()


def _messages(value) -> tuple[str, ...]:
    return tuple(
        item.strip()
        for item in _sequence(value)
        if isinstance(item, str) and item.strip()
    )


def _positive_infinity(value) -> bool:
    if _typed_bool(value) is not None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isinf(number) and number > 0.0


def _utilisation_text(value) -> str:
    number = _finite(value)
    if number is not None:
        return f"{100.0 * number:.1f} %"
    return "infinite" if _positive_infinity(value) else "-"


def _structured_evidence(value):
    """Return a JSON-safe typed evidence value and whether it was valid."""

    if value is None or isinstance(value, (str, bool)):
        return value, True
    if type(value).__name__ == "bool_":
        return bool(value), True
    if isinstance(value, (int, float)):
        number = float(value)
        return (value, True) if math.isfinite(number) else (None, False)
    if isinstance(value, Mapping):
        output = {}
        for key, item in value.items():
            if not isinstance(key, str):
                return None, False
            normalised, valid = _structured_evidence(item)
            if not valid:
                return None, False
            output[key] = normalised
        return output, True
    if isinstance(value, (list, tuple)):
        output = []
        for item in value:
            normalised, valid = _structured_evidence(item)
            if not valid:
                return None, False
            output.append(normalised)
        return output, True
    return None, False


def _external(
    records: Sequence[Mapping],
    *,
    empty_reason: str,
    source: str,
) -> bridge.ExternalEvidence:
    """Aggregate already-decided rows without turning missing evidence into PASS."""

    rows = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        row = dict(record)
        status = _status(row.get("status"))
        raw_utilisation = row.get("util")
        utilisation = _finite(raw_utilisation)
        unbounded_failure = (
            status == bridge.STATUS_FAIL
            and _positive_infinity(raw_utilisation)
        )
        requires_utilisation = bool(row.pop("_requires_utilisation", False))
        invalid_utilisation = (
            raw_utilisation is not None
            and utilisation is None
            and not unbounded_failure
        )
        if utilisation is not None and utilisation < 0.0:
            invalid_utilisation = True
            utilisation = None
        if (
            status in {bridge.STATUS_PASS, bridge.STATUS_FAIL}
            and requires_utilisation
            and utilisation is None
            and not unbounded_failure
        ):
            invalid_utilisation = True
        if invalid_utilisation:
            status = bridge.STATUS_INVALID
            note = row.get("note") or row.get("reason")
            prefix = (
                str(note).strip() + "; "
                if isinstance(note, str) and note.strip()
                else ""
            )
            row["note"] = (
                prefix + "acceptance utilisation is missing or invalid"
            )
        row["status"] = status
        row["util"] = utilisation
        row["unbounded_utilisation"] = unbounded_failure
        rows.append(row)
    if not rows:
        return bridge.ExternalEvidence(
            status=bridge.STATUS_NOT_RUN,
            source=source,
            reason=empty_reason,
        )
    statuses = [_status(row.get("status")) for row in rows]
    status = min(statuses, key=lambda item: _STATUS_ORDER[item])
    governing = next(
        (
            row
            for row in rows
            if (
                _status(row.get("status")) == bridge.STATUS_FAIL
                and row.get("unbounded_utilisation") is True
            )
        ),
        None,
    )
    utilisation = None
    if governing is None:
        utilisations = [
            number
            for number in (_finite(row.get("util")) for row in rows)
            if number is not None
        ]
        utilisation = max(utilisations, default=None)
    if governing is None and utilisation is not None:
        governing = next(
            (
                row
                for row in rows
                if _finite(row.get("util")) == utilisation
            ),
            None,
        )
    if governing is None:
        governing = rows[statuses.index(status)]
    reason = "; ".join(
        dict.fromkeys(
            str(row.get("note") or row.get("reason") or "").strip()
            for row in rows
            if str(row.get("note") or row.get("reason") or "").strip()
        )
    )
    return bridge.ExternalEvidence(
        status=status,
        result=str(governing.get("result") or "-"),
        criterion=str(governing.get("criterion") or "-"),
        source=str(governing.get("source") or source),
        reason=reason,
        utilisation=utilisation,
        evidence=tuple(rows),
    )


def stress_responses(results: Mapping) -> tuple[bridge.StressResponse, ...]:
    """Rebuild long/total concrete-stress evidence from explicit case mappings."""

    entries = results.get("elastic_cases")
    if entries is None:
        elastic = results.get("elastic")
        elastic_record = elastic if isinstance(elastic, Mapping) else {}
        elastic_case = elastic_record.get("elastic_case")
        if not isinstance(elastic_case, Mapping):
            elastic_case = {}
        entries = [{
            "name": str(
                elastic_case.get("id")
                or "Elastic"
            ),
            "actions": {
                "long_combination": sls.COMBINATION_UNSPECIFIED,
                "total_combination": sls.COMBINATION_UNSPECIFIED,
            },
            "results": {"elastic": elastic_record},
        }]
    output = []
    for entry in _sequence(entries):
        if not isinstance(entry, Mapping):
            continue
        actions = entry.get("actions")
        actions = actions if isinstance(actions, Mapping) else {}
        case_results = entry.get("results")
        case_results = (
            case_results if isinstance(case_results, Mapping) else {}
        )
        elastic = case_results.get("elastic")
        elastic = elastic if isinstance(elastic, Mapping) else {}
        raw_case_name = entry.get("name")
        case_name = (
            raw_case_name.strip()
            if isinstance(raw_case_name, str) and raw_case_name.strip()
            else "Elastic"
        )
        converged = _typed_bool(elastic.get("converged")) is True
        context_valid = (
            isinstance(entry.get("actions"), Mapping)
            and isinstance(entry.get("results"), Mapping)
            and isinstance(case_results.get("elastic"), Mapping)
            and isinstance(raw_case_name, str)
            and bool(raw_case_name.strip())
        )
        for state, combination_key, value_key, label in (
            (
                "long",
                "long_combination",
                "max_conc_long",
                "sustained / long-term",
            ),
            (
                "total",
                "total_combination",
                "max_conc",
                "instantaneous total",
            ),
        ):
            combination = sls.canonical_combination(
                actions.get(
                    combination_key,
                    sls.COMBINATION_UNSPECIFIED,
                )
            )
            output.append(bridge.StressResponse(
                response_id=f"{case_name}:{state}",
                combination=combination,
                compression_mpa=elastic.get(value_key),
                solver_status=(
                    "CONVERGED"
                    if converged and context_valid
                    else "INVALID"
                ),
                solver_provenance=(
                    f"Elastic case {case_name!r}, {label} response; "
                    f"{combination_key} table field"
                    + (
                        ""
                        if context_valid
                        else "; response context is malformed"
                    )
                ),
            ))
    return tuple(output)


def member_shear_evidence(
    inp: Mapping,
    results: Mapping,
) -> bridge.ExternalEvidence:
    """Reuse the established summary decisions for inherited member shear."""

    try:
        summary_rows = presentation.multi_case_summary_rows(inp, results)
    except (AttributeError, TypeError, ValueError):
        return bridge.ExternalEvidence(
            status=bridge.STATUS_INVALID,
            source=(
                "DS/EN 1992-1-1:2004 clause 6.2, inherited by "
                "DS/EN 1992-2"
            ),
            reason="Inherited member-shear result evidence is malformed.",
        )
    rows = [
        {
            **row,
            "_requires_utilisation": (
                _status(row.get("status"))
                in {bridge.STATUS_PASS, bridge.STATUS_FAIL}
            ),
        }
        for row in summary_rows
        if isinstance(row, Mapping) and row.get("view") == "Shear"
    ]
    return _external(
        rows,
        empty_reason="No inherited member-shear result was calculated.",
        source="DS/EN 1992-1-1:2004 clause 6.2, inherited by DS/EN 1992-2",
    )


def section_analysis_evidence(
    inp: Mapping,
    results: Mapping,
) -> bridge.ExternalEvidence:
    """Confirm inherited method alignment and exact requested solver completion."""

    selections = [("concrete material", inp.get("concrete_preset"))]

    def add_assigned_materials(
        role,
        catalog_key,
        element_key,
        geometry_key,
        legacy_key,
        extra_ids=(),
    ):
        catalog = inp.get(catalog_key)
        items = [
            item
            for item in _sequence(
                catalog.get("items")
                if isinstance(catalog, Mapping)
                else None
            )
            if isinstance(item, Mapping)
        ]
        by_id = {
            str(item.get("id") or "").strip(): item
            for item in items
            if str(item.get("id") or "").strip()
        }
        assigned = []
        for element in _sequence(inp.get(element_key)):
            if not isinstance(element, Mapping):
                continue
            material_id = str(element.get("material_id") or "").strip()
            if material_id and material_id not in assigned:
                assigned.append(material_id)
        for material_id in extra_ids:
            material_id = str(material_id or "").strip()
            if material_id and material_id not in assigned:
                assigned.append(material_id)
        if assigned:
            for material_id in assigned:
                item = by_id.get(material_id)
                selections.append((
                    f"{role} {material_id}",
                    None if item is None else item.get("preset"),
                ))
        elif inp.get(geometry_key):
            fallback = inp.get(legacy_key)
            if not str(fallback or "").strip() and len(items) == 1:
                fallback = items[0].get("preset")
            selections.append((role, fallback))

    reference_ids = (
        (inp.get("capacity_steel_material_id"),)
        if bool(inp.get("shear_on")) or bool(inp.get("torsion_on"))
        else ()
    )
    add_assigned_materials(
        "reinforcing steel",
        "mild_material_catalog",
        "bar_elements",
        "bars",
        "mild_preset",
        reference_ids,
    )
    add_assigned_materials(
        "prestressing steel",
        "prestress_material_catalog",
        "tendon_elements",
        "tendons",
        "prestress_preset",
    )
    active_methods = (
        ("crack width", inp.get("sls_code"), bool(inp.get("sls_cw"))),
        ("shear", inp.get("shear_method"), bool(inp.get("shear_on"))),
        ("torsion", inp.get("torsion_method"), bool(inp.get("torsion_on"))),
        (
            "longitudinal detailing",
            inp.get("detailing_edition"),
            bool(inp.get("minimum_reinforcement_on")),
        ),
        ("fatigue", inp.get("fatigue_edition"), bool(inp.get("fatigue_on"))),
    )
    selections.extend(
        (role, value)
        for role, value, active in active_methods
        if active
    )

    def compatible(value) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        if "1992-2:2005" in text or text == bridge.EN1992_2_BASE:
            return True
        return (
            ("2005" in text or "2004" in text)
            and "2023" not in text
            and "DK NA" not in text
        )

    missing = [role for role, value in selections if not str(value or "").strip()]
    incompatible = [
        f"{role}: {value}"
        for role, value in selections
        if str(value or "").strip() and not compatible(value)
    ]
    if missing or incompatible:
        reasons = []
        if missing:
            reasons.append("missing method identity: " + ", ".join(missing))
        if incompatible:
            reasons.append(
                "not in the inherited base 2005 family: "
                + "; ".join(incompatible)
            )
        return bridge.ExternalEvidence(
            status=bridge.STATUS_NOT_ASSESSED,
            result="-",
            criterion="Every active inherited method is base EN 1992-1-1:2004/2005",
            source="DS/EN 1992-2:2005 clause-by-clause inheritance",
            reason="; ".join(reasons),
        )

    solver_errors = []
    solver_rows = []
    mode = str(inp.get("mode") or "").strip()
    requested = []
    if mode in {"Plastic", "Both"}:
        requested.append("plastic")
    if mode in {"Elastic", "Both"}:
        requested.append("elastic")
    if not requested:
        solver_errors.append("bending analysis mode is missing or unknown")
    for family in requested:
        entries = results.get(f"{family}_cases")
        if entries is None:
            entries = [{
                "name": family.capitalize(),
                "results": {family: results.get(family)},
            }]
        if not isinstance(entries, (list, tuple)) or not entries:
            solver_errors.append(
                f"no calculated {family} case evidence is available"
            )
            continue
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, Mapping):
                solver_errors.append(
                    f"{family} case {index} is not structured evidence"
                )
                continue
            nested = entry.get("results")
            payload = (
                nested.get(family)
                if isinstance(nested, Mapping)
                else None
            )
            raw_case_name = entry.get("name")
            case_name = (
                raw_case_name.strip()
                if isinstance(raw_case_name, str) and raw_case_name.strip()
                else f"{family} case {index}"
            )
            if not isinstance(raw_case_name, str) or not raw_case_name.strip():
                solver_errors.append(
                    f"{case_name}: case identity is missing or malformed"
                )
            if not isinstance(payload, Mapping):
                solver_errors.append(
                    f"{case_name}: calculated {family} result is missing"
                )
                continue
            converged = payload.get("converged")
            if not (
                (isinstance(converged, bool) and converged)
                or (
                    type(converged).__name__ == "bool_"
                    and bool(converged)
                )
            ):
                solver_errors.append(
                    f"{case_name}: {family} solver did not converge"
                )
                continue
            solver_rows.append(f"{case_name}: {family} converged")
    if solver_errors:
        return bridge.ExternalEvidence(
            status=bridge.STATUS_INVALID,
            result="-",
            criterion="Every requested inherited section solve converges",
            source="DS/EN 1992-2:2005 clause-by-clause inheritance",
            reason="; ".join(solver_errors),
        )
    return bridge.ExternalEvidence(
        status=bridge.STATUS_PASS,
        result=(
            f"{len(selections)} active component method(s) aligned; "
            f"{len(solver_rows)} requested section solve(s) converged"
        ),
        criterion=(
            "Every active inherited method is base EN 1992-1-1:2004/2005 "
            "and every requested section solve converges"
        ),
        source="DS/EN 1992-2:2005 clause-by-clause inheritance",
        reason="; ".join(
            [
                *(f"{role}: {value}" for role, value in selections),
                *solver_rows,
            ]
        ),
    )


def _bridge_fatigue_context_errors(
    inp: Mapping | None,
    payload: Mapping,
    *,
    check_key: str,
) -> tuple[str, ...]:
    context = fatigue_analysis.bridge_publication_context(inp)
    return fatigue_analysis.bridge_result_context_errors(
        payload,
        context,
        check_key=check_key,
    )


def reinforcement_fatigue_evidence(
    results: Mapping,
    inp: Mapping | None = None,
) -> bridge.ExternalEvidence:
    """Return the reinforcement-only fatigue verdict."""

    payload = fatigue_analysis.publication_safe_result(
        results.get("fatigue"),
        design_methodology=(
            inp.get("design_methodology")
            if isinstance(inp, Mapping)
            else None
        ),
    )
    if not isinstance(payload, Mapping):
        return bridge.ExternalEvidence(
            status=bridge.STATUS_NOT_RUN,
            source="DS/EN 1992-1-1:2004 clauses 6.8.4-6.8.6, inherited",
            reason="No reinforcement fatigue result was calculated.",
        )
    checks = payload.get("checks")
    if not isinstance(checks, Mapping):
        return bridge.ExternalEvidence(
            status=bridge.STATUS_INVALID,
            source="DS/EN 1992-1-1:2004 clauses 6.8.4-6.8.6, inherited",
            reason="Fatigue check-selection evidence is malformed.",
        )
    enabled = _typed_bool(checks.get("reinforcement"))
    if enabled is None:
        return bridge.ExternalEvidence(
            status=bridge.STATUS_INVALID,
            source="DS/EN 1992-1-1:2004 clauses 6.8.4-6.8.6, inherited",
            reason="Reinforcement fatigue enablement is not typed Boolean evidence.",
        )
    context_errors = _bridge_fatigue_context_errors(
        inp,
        payload,
        check_key="reinforcement",
    )
    if context_errors:
        return bridge.ExternalEvidence(
            status=bridge.STATUS_INVALID,
            source="DS/EN 1992-1-1:2004 clauses 6.8.4-6.8.6, inherited",
            reason="; ".join(context_errors),
        )
    if not enabled:
        return bridge.ExternalEvidence(
            status=bridge.STATUS_NOT_RUN,
            source="DS/EN 1992-1-1:2004 clauses 6.8.4-6.8.6, inherited",
            reason="The reinforcement fatigue check is disabled.",
        )
    rows = []
    factor_basis = payload.get("factor_basis")
    if not isinstance(factor_basis, Mapping):
        return bridge.ExternalEvidence(
            status=bridge.STATUS_INVALID,
            source="DS/EN 1992-1-1:2004 clauses 6.8.4-6.8.6, inherited",
            reason="Fatigue factor-basis evidence is malformed.",
        )
    partial_factors = payload.get("partial_factors")
    if not isinstance(partial_factors, Mapping):
        return bridge.ExternalEvidence(
            status=bridge.STATUS_INVALID,
            source="DS/EN 1992-1-1:2004 clauses 6.8.4-6.8.6, inherited",
            reason="Fatigue partial-factor evidence is malformed.",
        )
    gamma_ff = float(partial_factors["gamma_ff"])
    reinforcement_parameter_records = [
        dict(record)
        for record in (payload.get("parameter_conformance") or ())
        if (
            isinstance(record, Mapping)
            and record.get("parameter_id") == "fatigue.gamma_s"
        )
    ]
    reinforcement_requires_review = any(
        record.get("state") != conformance.STATE_CONFORMS
        for record in reinforcement_parameter_records
    )
    for spectrum in fatigue_presentation.items(payload, "spectra"):
        for row in fatigue_presentation.reinforcement_rows(spectrum):
            analytical_status = _status(row.get("status"))
            rows.append({
                "status": (
                    bridge.STATUS_REVIEW
                    if reinforcement_requires_review
                    else analytical_status
                ),
                "analytical_status": analytical_status,
                "result": _utilisation_text(row.get("utilisation")),
                "criterion": "<= 100 %",
                "util": row.get("utilisation"),
                "_requires_utilisation": True,
                "source": (
                    payload.get("calculation_references", {}).get(
                        "reinforcement"
                    )
                    if isinstance(
                        payload.get("calculation_references"),
                        Mapping,
                    )
                    else ""
                ),
                "note": (
                    f"spectrum {fatigue_presentation.value(spectrum, 'spectrum_name', '-')}; "
                    f"element {row.get('element_id', '-')}; "
                    f"{payload.get('qualified_verdict') or ''}"
                ),
                "fatigue_parameter_conformance": (
                    reinforcement_parameter_records
                ),
                "methodology": payload.get("design_methodology"),
                "fatigue_edition": payload.get("edition"),
                "fatigue_factor_mode": factor_basis.get("mode"),
                "fatigue_factor_approval": (
                    factor_basis.get("approval_reference") or ""
                ),
                "fatigue_gamma_ff": gamma_ff,
            })
    warnings = _messages(payload.get("warnings"))
    errors = _messages(payload.get("errors"))
    if warnings and rows and all(
        _status(row.get("status")) == bridge.STATUS_PASS for row in rows
    ):
        rows.append({
            "status": bridge.STATUS_REVIEW,
            "result": "-",
            "criterion": "Complete approved fatigue basis",
            "util": None,
            "note": "; ".join(warnings),
        })
    if errors:
        rows.append({
            "status": bridge.STATUS_INVALID,
            "result": "-",
            "criterion": "<= 100 %",
            "util": None,
            "note": "; ".join(errors),
        })
    return _external(
        rows,
        empty_reason="Reinforcement fatigue evidence is incomplete.",
        source="DS/EN 1992-1-1:2004 clauses 6.8.4-6.8.6, inherited",
    )


def concrete_fatigue_evidence(
    results: Mapping,
    inp: Mapping | None = None,
) -> bridge.ExternalEvidence:
    """Return the concrete-only fatigue verdict, not the mixed fatigue aggregate."""

    payload = fatigue_analysis.publication_safe_result(
        results.get("fatigue"),
        design_methodology=(
            inp.get("design_methodology")
            if isinstance(inp, Mapping)
            else None
        ),
    )
    if not isinstance(payload, Mapping):
        return bridge.ExternalEvidence(
            status=bridge.STATUS_NOT_RUN,
            source="DS/EN 1992-2:2005/AC:2008, corrected Expression (6.106)",
            reason="No concrete fatigue result was calculated.",
        )
    checks = payload.get("checks")
    if not isinstance(checks, Mapping):
        return bridge.ExternalEvidence(
            status=bridge.STATUS_INVALID,
            source="DS/EN 1992-2:2005/AC:2008, corrected Expression (6.106)",
            reason="Fatigue check-selection evidence is malformed.",
        )
    enabled = _typed_bool(checks.get("concrete"))
    if enabled is None:
        return bridge.ExternalEvidence(
            status=bridge.STATUS_INVALID,
            source="DS/EN 1992-2:2005/AC:2008, corrected Expression (6.106)",
            reason="Concrete fatigue enablement is not typed Boolean evidence.",
        )
    context_errors = _bridge_fatigue_context_errors(
        inp,
        payload,
        check_key="concrete",
    )
    if context_errors:
        return bridge.ExternalEvidence(
            status=bridge.STATUS_INVALID,
            source="DS/EN 1992-2:2005/AC:2008, corrected Expression (6.106)",
            reason="; ".join(context_errors),
        )
    if not enabled:
        return bridge.ExternalEvidence(
            status=bridge.STATUS_NOT_RUN,
            source="DS/EN 1992-2:2005/AC:2008, corrected Expression (6.106)",
            reason="The concrete fatigue check is disabled.",
        )
    concrete_parameters = payload.get("concrete_parameters")
    if not isinstance(concrete_parameters, Mapping):
        return bridge.ExternalEvidence(
            status=bridge.STATUS_INVALID,
            source="DS/EN 1992-2:2005/AC:2008, corrected Expression (6.106)",
            reason="Concrete fatigue parameter evidence is malformed.",
        )
    miner_record = concrete_parameters.get("parameter_conformance")
    if not isinstance(miner_record, Mapping):
        return bridge.ExternalEvidence(
            status=bridge.STATUS_INVALID,
            source="DS/EN 1992-2:2005/AC:2008, corrected Expression (6.106)",
            reason="Concrete Miner conformance evidence is missing.",
        )
    factor_basis = payload.get("factor_basis")
    if not isinstance(factor_basis, Mapping):
        return bridge.ExternalEvidence(
            status=bridge.STATUS_INVALID,
            source="DS/EN 1992-2:2005/AC:2008, corrected Expression (6.106)",
            reason="Fatigue factor-basis evidence is malformed.",
        )
    partial_factors = payload.get("partial_factors")
    if not isinstance(partial_factors, Mapping):
        return bridge.ExternalEvidence(
            status=bridge.STATUS_INVALID,
            source="DS/EN 1992-2:2005/AC:2008, corrected Expression (6.106)",
            reason="Fatigue partial-factor evidence is malformed.",
        )
    gamma_ff = float(partial_factors["gamma_ff"])
    concrete_parameter_records = [
        dict(record)
        for record in (payload.get("parameter_conformance") or ())
        if (
            isinstance(record, Mapping)
            and record.get("parameter_id") in {
                "fatigue.gamma_c",
                "concrete_fatigue.miner_c",
            }
        )
    ]
    concrete_requires_review = any(
        record.get("state") != conformance.STATE_CONFORMS
        for record in concrete_parameter_records
    )
    assessment_status = (
        bridge.STATUS_REVIEW
        if concrete_requires_review
        else ""
    )
    qualified_verdict = str(
        payload.get("qualified_verdict") or ""
    ).strip()
    rows = []
    for spectrum in fatigue_presentation.items(payload, "spectra"):
        for row in fatigue_presentation.concrete_rows(spectrum):
            analytical_status = _status(row.get("status"))
            rows.append({
                "status": (
                    bridge.STATUS_REVIEW
                    if assessment_status == bridge.STATUS_REVIEW
                    else analytical_status
                ),
                "analytical_status": analytical_status,
                "result": _utilisation_text(row.get("utilisation")),
                "criterion": "<= 100 %",
                "util": row.get("utilisation"),
                "_requires_utilisation": True,
                "source": (
                    payload.get("calculation_references", {}).get("concrete")
                    if isinstance(
                        payload.get("calculation_references"),
                        Mapping,
                    )
                    else ""
                ),
                "methodology": payload.get("design_methodology"),
                "concrete_method": payload.get("concrete_method"),
                "concrete_miner_basis": payload.get(
                    "concrete_miner_basis"
                ),
                "concrete_miner_source": (
                    payload.get("concrete_miner_source") or ""
                ),
                "miner_coefficient_c": concrete_parameters.get("c"),
                "parameter_conformance": dict(miner_record),
                "fatigue_parameter_conformance": concrete_parameter_records,
                "fatigue_edition": payload.get("edition"),
                "fatigue_factor_mode": factor_basis.get("mode"),
                "fatigue_factor_approval": (
                    factor_basis.get("approval_reference") or ""
                ),
                "fatigue_gamma_ff": gamma_ff,
                "note": (
                    f"spectrum {fatigue_presentation.value(spectrum, 'spectrum_name', '-')}; "
                    f"concrete fibre {row.get('fibre_index', '-')}; "
                    f"{qualified_verdict or assessment_status}"
                ),
            })
    errors = _messages(payload.get("errors"))
    if errors:
        rows.append({
            "status": bridge.STATUS_INVALID,
            "result": "-",
            "criterion": "<= 100 %",
            "util": None,
            "note": "; ".join(errors),
        })
    return _external(
        rows,
        empty_reason="Concrete fatigue evidence is incomplete.",
        source="DS/EN 1992-2:2005/AC:2008, corrected Expression (6.106)",
    )


def crack_evidence(results: Mapping) -> bridge.ExternalEvidence:
    """Aggregate each unique bridge crack criterion at its matched response only."""

    entries = results.get("elastic_cases")
    if entries is None:
        entries = [{
            "name": "Elastic",
            "results": {"elastic": results.get("elastic")},
        }]
    grouped: dict[str, list[dict]] = {}
    configuration: dict[str, list[dict]] = {}
    for entry in _sequence(entries):
        if not isinstance(entry, Mapping):
            continue
        case_results = entry.get("results")
        if not isinstance(case_results, Mapping):
            continue
        elastic = case_results.get("elastic")
        if not isinstance(elastic, Mapping):
            continue
        assessment = elastic.get("crack_assessment")
        if not isinstance(assessment, Mapping):
            continue
        current_responses = elastic.get("crack_responses")
        current_contexts = elastic.get("crack_response_contexts")
        current_mapping_scope = elastic.get(
            "crack_response_mapping_scope"
        )
        for criterion in _sequence(assessment.get("criteria")):
            if not isinstance(criterion, Mapping):
                continue
            criterion_id = str(
                criterion.get("criterion_id")
                or criterion.get("id")
                or ""
            ).strip()
            if not criterion_id.startswith(
                ("bridge-standard-", "bridge-dk-standard-")
            ):
                continue
            record = dict(criterion)
            if _status(record.get("status")) in {
                bridge.STATUS_PASS,
                bridge.STATUS_FAIL,
            }:
                binding, binding_issues = (
                    sls.validated_current_acceptance_evidence_binding(
                        record,
                        current_responses,
                        response_contexts=current_contexts,
                        response_mapping_scope=current_mapping_scope,
                    )
                )
                if binding_issues or binding is None:
                    record.update(
                        status=bridge.STATUS_NOT_ASSESSED,
                        value=None,
                        util=None,
                        acceptance_evidence=None,
                        reason=(
                            "Canonical crack acceptance evidence is missing, "
                            "malformed, stale, or conflicts with the current "
                            "response binding: "
                            + (
                                "; ".join(binding_issues)
                                or "unknown evidence error"
                            )
                            + "."
                        ),
                    )
                else:
                    record["acceptance_evidence"] = binding
                    record["limit_mm"] = binding["criterion"]["limit_mm"]
            matched = record.get("matched_responses")
            matched_valid = (
                isinstance(matched, (list, tuple))
                and all(
                    isinstance(label, str) and bool(label.strip())
                    for label in matched
                )
                and len({
                    label.strip()
                    for label in matched
                    if isinstance(label, str)
                }) == len(matched)
            )
            if not matched_valid:
                record.update(
                    status=bridge.STATUS_NOT_ASSESSED,
                    value=None,
                    util=None,
                    matched_responses=[],
                    reason=(
                        "Matched SLS response labels are malformed or "
                        "ambiguous."
                    ),
                )
            configuration.setdefault(criterion_id, []).append(record)
            if matched_valid and matched:
                grouped.setdefault(criterion_id, []).append(record)

    rows = []
    for criterion_id, records in configuration.items():
        matched = grouped.get(criterion_id, [])
        if not matched:
            sample = records[0]
            rows.append({
                "status": bridge.STATUS_NOT_ASSESSED,
                "result": "-",
                "criterion": str(
                    sample.get("criterion") or sample.get("kind") or "-"
                ),
                "util": None,
                "source": sample.get("criterion_source"),
                "note": str(
                    sample.get("reason")
                    or "The required SLS combination has no matched response."
                ),
            })
            continue
        if len(matched) != 1:
            sample = matched[0]
            rows.append({
                "status": bridge.STATUS_NOT_ASSESSED,
                "result": "-",
                "criterion": str(
                    sample.get("criterion") or sample.get("kind") or "-"
                ),
                "util": None,
                "source": sample.get("criterion_source"),
                "note": (
                    "The bridge criterion identity "
                    f"{criterion_id!r} has {len(matched)} independently matched "
                    "records. Exactly one canonically bound criterion is "
                    "required before acceptance."
                ),
                "criterion_id": criterion_id,
                "matched_responses": [],
                "acceptance_evidence": None,
            })
            continue
        for record in matched:
            kind = record.get("kind")
            status = _status(record.get("status"))
            value = _finite(record.get("value"))
            utilisation = _finite(record.get("util"))
            source = record.get("criterion_source")
            source_valid = isinstance(source, str) and bool(source.strip())
            raw_solver_provenance = record.get("solver_provenance")
            solver_provenance, solver_provenance_valid = _structured_evidence(
                raw_solver_provenance
            )
            solver_provenance_valid = (
                solver_provenance_valid
                and isinstance(
                    raw_solver_provenance,
                    (str, Mapping, list, tuple),
                )
                and bool(raw_solver_provenance)
            )
            acceptance_evidence, acceptance_evidence_valid = (
                _structured_evidence(record.get("acceptance_evidence"))
            )
            limit = None
            if kind != sls.CRITERION_DECOMPRESSION:
                limit = _finite(record.get("limit_mm"))
            if (
                status in {bridge.STATUS_PASS, bridge.STATUS_FAIL}
                and (
                    value is None
                    or not source_valid
                    or not solver_provenance_valid
                    or not acceptance_evidence_valid
                    or (
                        kind != sls.CRITERION_DECOMPRESSION
                        and (limit is None or limit <= 0.0)
                    )
                )
            ):
                status = bridge.STATUS_INVALID
            rows.append({
                "status": status,
                "result": (
                    "-"
                    if value is None
                    else (
                        f"{value:.3f} MPa"
                        if kind == sls.CRITERION_DECOMPRESSION
                        else f"{value:.3f} mm"
                    )
                ),
                "criterion": (
                    "concrete stress <= 0 MPa"
                    if kind == sls.CRITERION_DECOMPRESSION
                    else (
                        "-"
                        if limit is None
                        else f"<= {limit:.3f} mm"
                    )
                ),
                "util": utilisation,
                "source": source if source_valid else "",
                "note": (
                    record.get("reason")
                    if isinstance(record.get("reason"), str)
                    else ""
                ),
                "criterion_id": criterion_id,
                "kind": kind if isinstance(kind, str) else "",
                "required_combination": (
                    record.get("required_combination")
                    if isinstance(record.get("required_combination"), str)
                    else ""
                ),
                "matched_responses": [
                    label.strip()
                    for label in record.get("matched_responses", [])
                ],
                "response_duration": (
                    record.get("response_duration")
                    if isinstance(record.get("response_duration"), str)
                    else ""
                ),
                "response_provenance": (
                    record.get("response_provenance")
                    if isinstance(record.get("response_provenance"), str)
                    else ""
                ),
                "solver_provenance": (
                    solver_provenance
                    if solver_provenance_valid
                    else None
                ),
                "acceptance_evidence": (
                    acceptance_evidence
                    if acceptance_evidence_valid
                    else None
                ),
            })
    return _external(
        rows,
        empty_reason=(
            "No calculated bridge Table 7.101N or Table 7.101N DK NA "
            "crack/decompression criterion was found."
        ),
        source=(
            "DS/EN 1992-2:2005, Table 7.101N; DS/EN 1992-2 "
            "DK NA:2015, Table 7.101N DK NA"
        ),
    )


danish_basis_from_inputs = bridge_inputs.danish_basis_from_inputs
danish_basis_context = bridge_inputs.danish_basis_context


def build_evidence(inp: Mapping, results: Mapping) -> bridge.BridgeBaseEvidence:
    """Construct the one complete typed evidence object used by the core gate."""

    adapter_errors = []
    if not isinstance(results, Mapping):
        adapter_errors.append("bridge calculation results are not structured evidence")
        results = {}
    methodology = str(
        inp.get("design_methodology") or bridge.COMPONENT_METHODS
    ).strip()
    tables = {}
    table_errors = []
    for key in bridge_inputs.TABLE_KEYS:
        try:
            frame = bridge_inputs.normalise_table(inp.get(key), key)
            table_errors.extend(bridge_inputs.table_errors(frame, key))
        except (TypeError, ValueError) as exc:
            table_errors.append(f"{key}: {exc}")
            frame = bridge_inputs.empty_table(key)
        tables[key] = frame
    concrete = inp.get("concrete")
    fck = getattr(concrete, "fck", inp.get("conc_fck"))
    danish_basis = (
        danish_basis_from_inputs(inp)
        if methodology == bridge.EN1992_2_DK_NA
        else None
    )
    return bridge.BridgeBaseEvidence(
        methodology=methodology,
        decisions=bridge_inputs.decisions(
            tables[bridge_inputs.COVERAGE_TABLE_KEY]
        ),
        has_tendons=bool(inp.get("tendons")),
        has_hollow_section=bool(inp.get("holes")),
        fck_mpa=fck,
        brittle_method=str(
            inp.get("bridge_brittle_method")
            or bridge.BRITTLE_NOT_ESTABLISHED
        ),
        brittle_regions=bridge_inputs.brittle_regions(
            tables[bridge_inputs.BRITTLE_TABLE_KEY]
        ),
        expected_box_walls=inp.get("bridge_expected_box_walls", 0),
        box_walls=bridge_inputs.box_walls(
            tables[bridge_inputs.BOX_WALL_TABLE_KEY]
        ),
        minimum_scope=str(
            inp.get("bridge_minimum_scope")
            or bridge.MINIMUM_SCOPE_NOT_ESTABLISHED
        ),
        minimum_components=bridge_inputs.minimum_components(
            tables[bridge_inputs.MINIMUM_TABLE_KEY]
        ),
        shear_scope=str(
            inp.get("bridge_shear_scope")
            or bridge.SHEAR_SCOPE_NOT_ESTABLISHED
        ),
        bridge_exposure=str(
            inp.get("bridge_exposure")
            or bridge.BRIDGE_EXPOSURE_NOT_ESTABLISHED
        ),
        stress_responses=stress_responses(results),
        section_analysis=section_analysis_evidence(inp, results),
        shear=member_shear_evidence(inp, results),
        reinforcement_fatigue=reinforcement_fatigue_evidence(results, inp),
        concrete_fatigue=concrete_fatigue_evidence(results, inp),
        sls_crack=crack_evidence(results),
        danish_basis=danish_basis,
        configuration_errors=tuple(dict.fromkeys(
            (*table_errors, *adapter_errors)
        )),
    )


def assess(inp: Mapping, results: Mapping) -> dict:
    """Return the JSON-safe methodology gate for one completed calculation."""

    if not isinstance(inp, Mapping):
        return bridge.assess_base_methodology(bridge.BridgeBaseEvidence(
            methodology=bridge.EN1992_2_BASE,
            decisions=(),
            has_tendons=False,
            has_hollow_section=False,
            fck_mpa=None,
            configuration_errors=(
                "bridge calculation inputs are not structured evidence",
            ),
        ))
    return bridge.assess_base_methodology(build_evidence(inp, results))
