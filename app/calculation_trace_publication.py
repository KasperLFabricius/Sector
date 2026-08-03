"""Publish and present the accepted CT-002--CT-011 trace families.

The numerical families remain owned by their ``sector.*_trace`` modules.  This
module supplies the bounded PR-08E integration boundary: deterministic case
context, exact result correlation, family-local failure reporting and one
presentation row model shared by the app, report and manual.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

import case_analysis
import project_io
from sector.bridge_trace import (
    build_bridge_trace_family,
    validate_bridge_trace_family,
)
from sector.calculation_trace import (
    RESULT_FINITE,
    SOURCE_INPUT,
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    TraceBundle,
    TraceCalculation,
    TraceSource,
    TraceValidationError,
    trace_identity_token,
    validate_bundle,
)
from sector.crack_trace import build_crack_trace_family, validate_crack_trace_family
from sector.detailing_trace import (
    build_detailing_trace_family,
    validate_detailing_trace_family,
)
from sector.elastic_trace import build_elastic_trace_family, validate_elastic_trace_family
from sector.fatigue_trace import build_fatigue_trace_family, validate_fatigue_trace_family
from sector.plastic_capacity_trace import (
    build_plastic_capacity_trace_family,
    validate_plastic_capacity_trace_family,
)
from sector.plastic_interaction_trace import (
    build_plastic_interaction_trace_families,
    validate_plastic_interaction_trace_families,
)
from sector.shear_trace import build_shear_trace_family, validate_shear_trace_family
from sector.torsion_trace import build_torsion_trace_family, validate_torsion_trace_family


PUBLICATION_KEY = project_io.CALCULATION_TRACE_KEY
PUBLICATION_SCHEMA = "sector.calculation-trace-publication.v1"
_PUBLICATION_FIELDS = frozenset({
    "schema",
    "context",
    "input_sha256",
    "result_sha256",
    "result_scope",
    "bundles",
    "errors",
    "content_sha256",
})
_RESULT_SCOPE = "result"
_CASE_SHARED_SCOPE = "case-result+shared-clear-spacing"


@dataclass(frozen=True, slots=True)
class PublishedCalculation:
    context: dict[str, Any]
    input_sha256: str
    result_sha256: str
    content_sha256: str
    calculation: TraceCalculation


@dataclass(frozen=True, slots=True)
class PublishedError:
    context: dict[str, Any]
    coverage_id: str
    message: str


def _publication_content_sha256(publication: Mapping[str, Any]) -> str:
    payload = dict(publication)
    payload["content_sha256"] = ""
    try:
        canonical = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise TraceValidationError(
            f"trace publication is not strict JSON data: {exc}"
        ) from exc
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _publication(
    *,
    context: Mapping[str, Any],
    input_sha256: str,
    result_sha256: str,
    result_scope: str,
    bundles: list[dict[str, Any]],
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    value = {
        "schema": PUBLICATION_SCHEMA,
        "context": dict(context),
        "input_sha256": input_sha256,
        "result_sha256": result_sha256,
        "result_scope": result_scope,
        "bundles": bundles,
        "errors": errors,
        "content_sha256": "",
    }
    value["content_sha256"] = _publication_content_sha256(value)
    return value


def _error(coverage_id: str, exc: TraceValidationError) -> dict[str, str]:
    return {"coverage_id": coverage_id, "message": str(exc)}


def _attempt(
    coverage_id: str,
    builder: Callable[[], TraceBundle | None],
    bundles: list[dict[str, Any]],
    errors: list[dict[str, str]],
) -> None:
    try:
        bundle = builder()
    except TraceValidationError as exc:
        errors.append(_error(coverage_id, exc))
        return
    if bundle is not None:
        bundles.append(validate_bundle(bundle).to_dict())


def _case_specs(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any],
) -> tuple[tuple[str, Callable[[], TraceBundle | None]], ...]:
    specs: list[tuple[str, Callable[[], TraceBundle | None]]] = []
    if "plastic" in out:
        specs.append(("ct-002", lambda: build_plastic_capacity_trace_family(
            inp, out, input_sha256=input_sha256,
            result_sha256=result_sha256, context=context,
        )))
        interaction = (out.get("plastic") or {}).get("interaction")
        if inp.get("interaction") and interaction is not None:
            specs.append(("ct-003-004", lambda:
                build_plastic_interaction_trace_families(
                    inp, out, input_sha256=input_sha256,
                    result_sha256=result_sha256, context=context,
                )
            ))
    if "elastic" in out:
        specs.append(("ct-005", lambda: build_elastic_trace_family(
            inp, out, input_sha256=input_sha256,
            result_sha256=result_sha256, context=context,
        )))
    if "shear" in out:
        specs.append(("ct-006", lambda: build_shear_trace_family(
            inp, out.get("shear") or {}, input_sha256=input_sha256,
            result_sha256=result_sha256, context=context,
            plastic_out=out.get("plastic"),
        )))
    if "torsion" in out:
        specs.append(("ct-007", lambda: build_torsion_trace_family(
            inp, out.get("torsion") or {}, input_sha256=input_sha256,
            result_sha256=result_sha256, context=context,
        )))
    if any(key in out for key in (
        "clear_spacing", "transverse_reinforcement", "minimum_reinforcement"
    )):
        specs.append(("ct-008", lambda: build_detailing_trace_family(
            inp, out, input_sha256=input_sha256,
            result_sha256=result_sha256, context=context,
        )))
    if "elastic" in out:
        specs.append(("ct-009", lambda: build_crack_trace_family(
            inp, out, input_sha256=input_sha256,
            result_sha256=result_sha256, context=context,
        )))
    return tuple(specs)


def _global_specs(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any],
) -> tuple[tuple[str, Callable[[], TraceBundle | None]], ...]:
    specs: list[tuple[str, Callable[[], TraceBundle | None]]] = []
    if "fatigue" in out:
        specs.append(("ct-010", lambda: build_fatigue_trace_family(
            inp, {"fatigue": out.get("fatigue")}, input_sha256=input_sha256,
            result_sha256=result_sha256, context=context,
        )))
    if "bridge" in out:
        specs.append(("ct-011", lambda: build_bridge_trace_family(
            inp, {"bridge": out.get("bridge")}, input_sha256=input_sha256,
            result_sha256=result_sha256, context=context,
        )))
    return tuple(specs)


def _attach(
    owner: dict[str, Any],
    result_view: Mapping[str, Any],
    context: Mapping[str, Any],
    input_sha256: str,
    result_scope: str,
    spec_factory: Callable[..., Sequence[
        tuple[str, Callable[[], TraceBundle | None]]
    ]],
    inp: Mapping[str, Any],
) -> None:
    owner.pop(PUBLICATION_KEY, None)
    result_sha256 = project_io.result_sha256(result_view)
    bundles: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for coverage_id, builder in spec_factory(
        inp,
        result_view,
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        context=context,
    ):
        _attempt(coverage_id, builder, bundles, errors)
    if bundles or errors:
        owner[PUBLICATION_KEY] = _publication(
            context=context,
            input_sha256=input_sha256,
            result_sha256=result_sha256,
            result_scope=result_scope,
            bundles=bundles,
            errors=errors,
        )


def attach_calculation_traces(
    inp: Mapping[str, Any],
    result: dict[str, Any],
    *,
    input_sha256: str | None = None,
) -> dict[str, Any]:
    """Attach applicable trace bundles without allowing one family to mask another."""

    if type(result) is not dict:
        raise TypeError("calculation result must be a mutable plain dictionary")
    digest = input_sha256 or project_io.result_sha256(inp)
    has_cases = "plastic_cases" in result or "elastic_cases" in result
    if not has_cases:
        context = {"analysis": "single"}
        result.pop(PUBLICATION_KEY, None)
        result_sha256 = project_io.result_sha256(result)
        bundles: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for coverage_id, builder in (
            *_case_specs(
                inp, result, input_sha256=digest,
                result_sha256=result_sha256, context=context,
            ),
            *_global_specs(
                inp, result, input_sha256=digest,
                result_sha256=result_sha256, context=context,
            ),
        ):
            _attempt(coverage_id, builder, bundles, errors)
        if bundles or errors:
            result[PUBLICATION_KEY] = _publication(
                context=context,
                input_sha256=digest,
                result_sha256=result_sha256,
                result_scope=_RESULT_SCOPE,
                bundles=bundles,
                errors=errors,
            )
        return result

    shared_clear = result.get("clear_spacing")
    for family in ("plastic", "elastic"):
        entries = result.get(f"{family}_cases") or ()
        for index, entry in enumerate(entries):
            if type(entry) is not dict or type(entry.get("results")) is not dict:
                raise TypeError("case-table results must be mutable plain dictionaries")
            case_inp = (
                case_analysis.plastic_case_input(inp, entry["actions"])
                if family == "plastic"
                else case_analysis.elastic_case_input(inp, entry["actions"])
            )
            owner = entry["results"]
            owner.pop(PUBLICATION_KEY, None)
            result_view = dict(owner)
            scope = _RESULT_SCOPE
            if shared_clear is not None:
                result_view["clear_spacing"] = shared_clear
                scope = _CASE_SHARED_SCOPE
            _attach(
                owner,
                result_view,
                case_analysis.trace_context(family, index, entry),
                digest,
                scope,
                _case_specs,
                case_inp,
            )

    _attach(
        result,
        result,
        {"analysis": "project"},
        digest,
        _RESULT_SCOPE,
        _global_specs,
        inp,
    )
    return result


def _publication_entries(result: Mapping[str, Any]):
    for family in ("plastic", "elastic"):
        for entry in result.get(f"{family}_cases") or ():
            if isinstance(entry, Mapping) and isinstance(entry.get("results"), Mapping):
                yield entry["results"], result, family, entry
    yield result, result, None, None


def _validated_publications(result: Mapping[str, Any]):
    if not isinstance(result, Mapping):
        raise TraceValidationError("published result must be a mapping")
    for owner, root, family, entry in _publication_entries(result):
        publication = owner.get(PUBLICATION_KEY)
        if publication is None:
            continue
        if type(publication) is not dict or set(publication) != set(_PUBLICATION_FIELDS):
            raise TraceValidationError("malformed calculation-trace publication")
        if publication["schema"] != PUBLICATION_SCHEMA:
            raise TraceValidationError(
                f"unsupported calculation-trace publication {publication['schema']!r}"
            )
        if type(publication["context"]) is not dict:
            raise TraceValidationError("trace publication context must be an object")
        if any(type(key) is not str for key in publication["context"]):
            raise TraceValidationError("trace publication context keys must be text")
        if (
            type(publication["input_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", publication["input_sha256"]) is None
        ):
            raise TraceValidationError("trace publication input SHA-256 is invalid")
        if (
            type(publication["content_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", publication["content_sha256"]) is None
            or publication["content_sha256"]
            != _publication_content_sha256(publication)
        ):
            raise TraceValidationError("trace publication content seal is invalid")
        scope = publication["result_scope"]
        if scope == _RESULT_SCOPE:
            result_view = owner
        elif scope == _CASE_SHARED_SCOPE:
            if "clear_spacing" not in root:
                raise TraceValidationError(
                    "case trace publication lost its shared clear-spacing result"
                )
            result_view = dict(owner)
            result_view["clear_spacing"] = root["clear_spacing"]
        else:
            raise TraceValidationError(f"unknown trace result scope {scope!r}")
        actual_result_sha256 = project_io.result_sha256(result_view)
        if publication["result_sha256"] != actual_result_sha256:
            raise TraceValidationError(
                "calculation-trace publication does not match its retained result"
            )
        if type(publication["bundles"]) is not list:
            raise TraceValidationError("trace publication bundles must be a list")
        if type(publication["errors"]) is not list:
            raise TraceValidationError("trace publication errors must be a list")
        yield publication, result_view, family, entry


def _published_input(
    inp: Mapping[str, Any],
    family: str | None,
    entry: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    if family is None:
        return inp
    if entry is None or not isinstance(entry.get("actions"), Mapping):
        raise TraceValidationError("published case lost its original actions")
    if family == "plastic":
        return case_analysis.plastic_case_input(inp, entry["actions"])
    if family == "elastic":
        return case_analysis.elastic_case_input(inp, entry["actions"])
    raise TraceValidationError(f"unknown published case family {family!r}")


def _replay_published_bundle(
    encoded: Mapping[str, Any],
    inp: Mapping[str, Any],
    result_view: Mapping[str, Any],
    publication: Mapping[str, Any],
) -> TraceBundle:
    """Replay one stored family from original inputs before it reaches a renderer."""

    candidate = validate_bundle(
        encoded,
        expected_input_sha256=publication["input_sha256"],
        expected_result_sha256=publication["result_sha256"],
    )
    coverage = frozenset(item.coverage_id for item in candidate.calculations)
    kwargs = {
        "input_sha256": publication["input_sha256"],
        "result_sha256": publication["result_sha256"],
        "context": publication["context"],
    }
    if coverage == {"ct-002"}:
        checked = validate_plastic_capacity_trace_family(
            candidate, inp, result_view, **kwargs
        )
    elif coverage and coverage <= {"ct-003", "ct-004"}:
        checked = validate_plastic_interaction_trace_families(
            candidate, inp, result_view, **kwargs
        )
    elif coverage == {"ct-005"}:
        checked = validate_elastic_trace_family(
            candidate, inp, result_view, **kwargs
        )
    elif coverage == {"ct-006"}:
        checked = validate_shear_trace_family(
            candidate,
            inp,
            result_view.get("shear") or {},
            plastic_out=result_view.get("plastic"),
            **kwargs,
        )
    elif coverage == {"ct-007"}:
        checked = validate_torsion_trace_family(
            candidate, inp, result_view.get("torsion") or {}, **kwargs
        )
    elif coverage == {"ct-008"}:
        checked = validate_detailing_trace_family(
            candidate, inp, result_view, **kwargs
        )
    elif coverage == {"ct-009"}:
        checked = validate_crack_trace_family(
            candidate, inp, result_view, **kwargs
        )
    elif coverage == {"ct-010"}:
        checked = validate_fatigue_trace_family(
            candidate,
            inp,
            {"fatigue": result_view.get("fatigue")},
            **kwargs,
        )
    elif coverage == {"ct-011"}:
        checked = validate_bridge_trace_family(
            candidate,
            inp,
            {"bridge": result_view.get("bridge")},
            **kwargs,
        )
    else:
        raise TraceValidationError(
            f"unsupported published trace coverage {sorted(coverage)!r}"
        )
    if checked is None:
        raise TraceValidationError("published trace is not applicable to its inputs")
    return checked


def published_calculations(
    result: Mapping[str, Any],
    inp: Mapping[str, Any],
) -> tuple[PublishedCalculation, ...]:
    """Independently replay and return every calculation in publication order."""

    if not isinstance(inp, Mapping):
        raise TraceValidationError("published calculation inputs must be a mapping")
    records: list[PublishedCalculation] = []
    seen: set[tuple[str, str]] = set()
    for publication, result_view, family, entry in _validated_publications(result):
        context = dict(publication["context"])
        context_key = repr(sorted(context.items()))
        replay_inp = _published_input(inp, family, entry)
        for encoded in publication["bundles"]:
            bundle = _replay_published_bundle(
                encoded, replay_inp, result_view, publication
            )
            for calculation in bundle.calculations:
                axes = {axis.name: axis.value for axis in calculation.axes}
                for key, value in context.items():
                    if axes.get(trace_identity_token(key)) != str(value):
                        raise TraceValidationError(
                            "published calculation context differs from its trace axes"
                        )
                identity = (context_key, calculation.calculation_id)
                if identity in seen:
                    raise TraceValidationError(
                        "duplicate published calculation identity"
                    )
                seen.add(identity)
                records.append(PublishedCalculation(
                    context=context,
                    input_sha256=bundle.input_sha256,
                    result_sha256=bundle.result_sha256,
                    content_sha256=bundle.content_sha256,
                    calculation=calculation,
                ))
    return tuple(records)


def published_errors(result: Mapping[str, Any]) -> tuple[PublishedError, ...]:
    """Return transparent family-local publication failures after seal checks."""

    records: list[PublishedError] = []
    for publication, _result_view, _family, _entry in _validated_publications(result):
        context = dict(publication["context"])
        seen: set[str] = set()
        for error in publication["errors"]:
            if type(error) is not dict or set(error) != {"coverage_id", "message"}:
                raise TraceValidationError("malformed trace publication error")
            coverage_id, message = error["coverage_id"], error["message"]
            if (
                type(coverage_id) is not str
                or not coverage_id
                or coverage_id in seen
                or type(message) is not str
                or not message
            ):
                raise TraceValidationError("invalid trace publication error identity")
            seen.add(coverage_id)
            records.append(PublishedError(context, coverage_id, message))
    return tuple(records)


def format_source(source: TraceSource) -> str:
    """Format exact trace provenance without inventing a citation."""

    if source.kind == SOURCE_STANDARD:
        citation = source.citation
        return "; ".join((
            citation.document,
            f"edition {source.edition}",
            f"clause {citation.clause}",
            citation.locator,
            f"method {source.method_id}",
        ))
    if source.kind == SOURCE_PROJECT:
        return f"Project-defined / uncited; method {source.method_id}"
    if source.kind == SOURCE_INPUT:
        return f"User input; method {source.method_id}"
    raise TraceValidationError(f"unknown trace source kind {source.kind!r}")


def format_trace_rows(calculation: TraceCalculation) -> tuple[dict[str, Any], ...]:
    """Return the sole tabular renderer model for one solver-owned calculation."""

    rows = []
    for sequence, step in enumerate(calculation.steps, start=1):
        result = (
            repr(step.result.value)
            if step.result.state == RESULT_FINITE
            else str(step.result.reason)
        )
        rows.append({
            "sequence": sequence,
            "step": step.title,
            "step_id": step.step_id,
            "role": step.quantity_role,
            "symbol": step.symbol,
            "expression": step.actual_expression,
            "substitution": step.substituted_expression,
            "state": step.result.state,
            "result": result,
            "unit": step.unit.symbol,
            "source": format_source(step.source),
            "dependencies": ", ".join(
                f"{item.step_id} [{item.unit.symbol}]"
                for item in step.dependencies
            ) or "-",
            "warnings": " | ".join(step.warnings) or "-",
            "assumptions": " | ".join(step.assumptions) or "-",
        })
    return tuple(rows)


def context_label(context: Mapping[str, Any]) -> str:
    analysis = context.get("analysis")
    if analysis == "case-table":
        return (
            f"{context.get('family')} case {context.get('case_index')}: "
            f"{context.get('case_name') or '-'}"
        )
    return str(analysis or "calculation")


def calculation_label(record: PublishedCalculation) -> str:
    calculation = record.calculation
    context_axes = {
        trace_identity_token(key) for key in record.context
    }
    axes = ", ".join(
        f"{axis.name}={axis.value}"
        for axis in calculation.axes
        if axis.name not in context_axes
    )
    suffix = f" ({axes})" if axes else ""
    return (
        f"{calculation.coverage_id.upper()} | {context_label(record.context)} | "
        f"{calculation.title}{suffix}"
    )
