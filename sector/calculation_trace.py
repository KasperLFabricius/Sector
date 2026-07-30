"""Immutable, presentation-neutral calculation traces for PI-019."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Sequence


TRACE_SCHEMA = "sector.calculation-trace.v1"

ROLE_USER_INPUT = "user_input"
ROLE_METHOD_VALUE = "method_value"
ROLE_COMPUTED = "computed_intermediate"
ROLE_FINAL = "final_result"
QUANTITY_ROLES = frozenset(
    {ROLE_USER_INPUT, ROLE_METHOD_VALUE, ROLE_COMPUTED, ROLE_FINAL}
)

SOURCE_INPUT = "input"
SOURCE_STANDARD = "standard"
SOURCE_PROJECT = "project"
SOURCE_KINDS = frozenset({SOURCE_INPUT, SOURCE_STANDARD, SOURCE_PROJECT})

RESULT_FINITE = "finite"
RESULT_POSITIVE_INFINITY = "positive_infinity"
RESULT_NEGATIVE_INFINITY = "negative_infinity"
RESULT_UNDEFINED = "undefined"
RESULT_FAILED = "failed"
RESULT_STATES = frozenset(
    {
        RESULT_FINITE,
        RESULT_POSITIVE_INFINITY,
        RESULT_NEGATIVE_INFINITY,
        RESULT_UNDEFINED,
        RESULT_FAILED,
    }
)

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class TraceValidationError(ValueError):
    """Raised when trace data is malformed, stale, incomplete, or tampered."""


def trace_identity_token(label: str) -> str:
    """Encode an exact user-visible label as a stable, injective ID token."""

    if type(label) is not str:
        raise TypeError("trace identity labels must be text")
    return "u" + label.encode("utf-8").hex()


def _exact_mapping(
    value: Any, *, label: str, fields: frozenset[str]
) -> dict[str, Any]:
    if type(value) is not dict:
        raise TraceValidationError(f"{label} must be an object")
    if any(type(key) is not str for key in value):
        raise TraceValidationError(f"{label} field names must be plain text")
    actual = set(value)
    if actual != set(fields):
        missing = sorted(fields - actual)
        extra = sorted(str(item) for item in actual - fields)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unexpected {', '.join(extra)}")
        raise TraceValidationError(f"{label} fields: {'; '.join(details)}")
    return value


def _list(value: Any, *, label: str) -> list[Any]:
    if type(value) is not list:
        raise TraceValidationError(f"{label} must be a JSON list")
    return value


def _text_list(value: Any, *, label: str) -> tuple[str, ...]:
    items = _list(value, label=label)
    if any(type(item) is not str for item in items):
        raise TraceValidationError(f"{label} entries must be text")
    return tuple(items)


@dataclass(frozen=True, slots=True)
class SourceCitation:
    document: str
    clause: str
    locator: str

    def to_dict(self) -> dict[str, str]:
        return {
            "document": self.document,
            "clause": self.clause,
            "locator": self.locator,
        }

    @classmethod
    def from_dict(cls, value: Any) -> SourceCitation:
        value = _exact_mapping(value, label="source citation", fields=frozenset({"document", "clause", "locator"}))
        return cls(value["document"], value["clause"], value["locator"])


@dataclass(frozen=True, slots=True)
class TraceSource:
    """Calculation-local source identity for one trace step."""

    kind: str
    method_id: str
    edition: str | None = None
    citation: SourceCitation | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "method_id": self.method_id,
            "edition": self.edition,
            "citation": None if self.citation is None else self.citation.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Any) -> TraceSource:
        value = _exact_mapping(value, label="trace source", fields=frozenset({"kind", "method_id", "edition", "citation"}))
        citation = value["citation"]
        return cls(
            kind=value["kind"],
            method_id=value["method_id"],
            edition=value["edition"],
            citation=None if citation is None else SourceCitation.from_dict(citation),
        )


@dataclass(frozen=True, slots=True)
class TraceUnit:
    """Exact displayed unit and its declarative physical dimension."""

    symbol: str
    dimension: str

    def to_dict(self) -> dict[str, str]:
        return {"symbol": self.symbol, "dimension": self.dimension}

    @classmethod
    def from_dict(cls, value: Any) -> TraceUnit:
        value = _exact_mapping(value, label="trace unit", fields=frozenset({"symbol", "dimension"}))
        return cls(symbol=value["symbol"], dimension=value["dimension"])


@dataclass(frozen=True, slots=True)
class TraceDependency:
    """One dependency ID and the exact unit consumed by the expression."""

    step_id: str
    unit: TraceUnit

    def to_dict(self) -> dict[str, Any]:
        return {"step_id": self.step_id, "unit": self.unit.to_dict()}

    @classmethod
    def from_dict(cls, value: Any) -> TraceDependency:
        value = _exact_mapping(value, label="trace dependency", fields=frozenset({"step_id", "unit"}))
        return cls(value["step_id"], TraceUnit.from_dict(value["unit"]))


@dataclass(frozen=True, slots=True)
class TraceResult:
    """Finite value or explicit non-finite/failure engineering state."""

    state: str
    value: float | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "value": self.value, "reason": self.reason}

    @classmethod
    def from_dict(cls, value: Any) -> TraceResult:
        value = _exact_mapping(value, label="trace result", fields=frozenset({"state", "value", "reason"}))
        return cls(value["state"], value["value"], value["reason"])


@dataclass(frozen=True, slots=True)
class TraceStep:
    step_id: str
    title: str
    dependencies: tuple[TraceDependency, ...]
    quantity_role: str
    source: TraceSource
    symbol: str
    unit: TraceUnit
    actual_expression: str
    substituted_expression: str
    result: TraceResult
    warnings: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "dependencies": [item.to_dict() for item in self.dependencies],
            "quantity_role": self.quantity_role,
            "source": self.source.to_dict(),
            "symbol": self.symbol,
            "unit": self.unit.to_dict(),
            "actual_expression": self.actual_expression,
            "substituted_expression": self.substituted_expression,
            "result": self.result.to_dict(),
            "warnings": list(self.warnings),
            "assumptions": list(self.assumptions),
        }

    @classmethod
    def from_dict(cls, value: Any) -> TraceStep:
        value = _exact_mapping(
            value,
            label="trace step",
            fields=frozenset(
                {
                    "step_id",
                    "title",
                    "dependencies",
                    "quantity_role",
                    "source",
                    "symbol",
                    "unit",
                    "actual_expression",
                    "substituted_expression",
                    "result",
                    "warnings",
                    "assumptions",
                }
            ),
        )
        return cls(
            step_id=value["step_id"],
            title=value["title"],
            dependencies=tuple(
                TraceDependency.from_dict(item)
                for item in _list(value["dependencies"], label="trace dependencies")
            ),
            quantity_role=value["quantity_role"],
            source=TraceSource.from_dict(value["source"]),
            symbol=value["symbol"],
            unit=TraceUnit.from_dict(value["unit"]),
            actual_expression=value["actual_expression"],
            substituted_expression=value["substituted_expression"],
            result=TraceResult.from_dict(value["result"]),
            warnings=_text_list(value["warnings"], label="trace step warnings"),
            assumptions=_text_list(
                value["assumptions"], label="trace step assumptions"
            ),
        )


@dataclass(frozen=True, slots=True)
class TraceAxis:
    name: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "value": self.value}

    @classmethod
    def from_dict(cls, value: Any) -> TraceAxis:
        value = _exact_mapping(value, label="trace axis", fields=frozenset({"name", "value"}))
        return cls(name=value["name"], value=value["value"])


@dataclass(frozen=True, slots=True)
class TraceCalculation:
    calculation_id: str
    coverage_id: str
    title: str
    method_id: str
    axes: tuple[TraceAxis, ...]
    final_step_id: str
    steps: tuple[TraceStep, ...]
    warnings: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "calculation_id": self.calculation_id,
            "coverage_id": self.coverage_id,
            "title": self.title,
            "method_id": self.method_id,
            "axes": [item.to_dict() for item in self.axes],
            "final_step_id": self.final_step_id,
            "steps": [item.to_dict() for item in self.steps],
            "warnings": list(self.warnings),
            "assumptions": list(self.assumptions),
        }

    @classmethod
    def from_dict(cls, value: Any) -> TraceCalculation:
        value = _exact_mapping(
            value,
            label="trace calculation",
            fields=frozenset(
                {
                    "calculation_id",
                    "coverage_id",
                    "title",
                    "method_id",
                    "axes",
                    "final_step_id",
                    "steps",
                    "warnings",
                    "assumptions",
                }
            ),
        )
        return cls(
            calculation_id=value["calculation_id"],
            coverage_id=value["coverage_id"],
            title=value["title"],
            method_id=value["method_id"],
            axes=tuple(
                TraceAxis.from_dict(item)
                for item in _list(value["axes"], label="trace axes")
            ),
            final_step_id=value["final_step_id"],
            steps=tuple(
                TraceStep.from_dict(item)
                for item in _list(value["steps"], label="trace steps")
            ),
            warnings=_text_list(
                value["warnings"], label="trace calculation warnings"
            ),
            assumptions=_text_list(
                value["assumptions"], label="trace calculation assumptions"
            ),
        )


@dataclass(frozen=True, slots=True)
class TraceBundle:
    input_sha256: str
    result_sha256: str
    calculations: tuple[TraceCalculation, ...]
    schema: str = TRACE_SCHEMA
    warnings: tuple[str, ...] = ()
    content_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "input_sha256": self.input_sha256,
            "result_sha256": self.result_sha256,
            "calculations": [item.to_dict() for item in self.calculations],
            "warnings": list(self.warnings),
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def from_dict(cls, value: Any) -> TraceBundle:
        value = _exact_mapping(
            value,
            label="calculation-trace bundle",
            fields=frozenset(
                {
                    "schema",
                    "input_sha256",
                    "result_sha256",
                    "calculations",
                    "warnings",
                    "content_sha256",
                }
            ),
        )
        return cls(
            schema=value["schema"],
            input_sha256=value["input_sha256"],
            result_sha256=value["result_sha256"],
            calculations=tuple(
                TraceCalculation.from_dict(item)
                for item in _list(
                    value["calculations"], label="trace calculations"
                )
            ),
            warnings=_text_list(value["warnings"], label="trace bundle warnings"),
            content_sha256=value["content_sha256"],
        )


def _require_text(value: Any, label: str) -> None:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise TraceValidationError(f"{label} must be non-empty trimmed text")


def _require_id(value: Any, label: str) -> None:
    _require_text(value, label)
    if not _ID_RE.fullmatch(value):
        raise TraceValidationError(
            f"{label} must use lowercase letters, digits, dot, dash, or underscore"
        )


def _require_text_tuple(value: Any, label: str) -> None:
    if type(value) is not tuple:
        raise TraceValidationError(f"{label} must be an immutable tuple")
    for position, item in enumerate(value, start=1):
        _require_text(item, f"{label} entry {position}")


def _validate_unit(unit: Any, label: str) -> None:
    if type(unit) is not TraceUnit:
        raise TraceValidationError(f"{label} must be a TraceUnit")
    _require_text(unit.symbol, f"{label} symbol")
    _require_id(unit.dimension, f"{label} dimension")


def _validate_source(source: Any, label: str) -> None:
    if type(source) is not TraceSource:
        raise TraceValidationError(f"{label} must be a TraceSource")
    _require_id(source.kind, f"{label} kind")
    if source.kind not in SOURCE_KINDS:
        raise TraceValidationError(f"{label} has unknown kind {source.kind!r}")
    _require_id(source.method_id, f"{label} method_id")
    if source.kind == SOURCE_STANDARD:
        _require_text(source.edition, f"{label} edition")
        if type(source.citation) is not SourceCitation:
            raise TraceValidationError(f"{label} needs an exact standards citation")
        _require_text(source.citation.document, f"{label} citation document")
        _require_text(source.citation.clause, f"{label} citation clause")
        _require_text(source.citation.locator, f"{label} citation locator")
    elif source.edition is not None:
        raise TraceValidationError(f"{label} edition is only valid for a standard")
    elif source.citation is not None:
        raise TraceValidationError(
            f"{label} project/input methods cannot carry a standards citation"
        )


def _validate_result(result: Any, label: str) -> None:
    if type(result) is not TraceResult:
        raise TraceValidationError(f"{label} must be a TraceResult")
    _require_id(result.state, f"{label} state")
    if result.state not in RESULT_STATES:
        raise TraceValidationError(f"{label} has unknown state {result.state!r}")
    if result.state == RESULT_FINITE:
        if type(result.value) not in {int, float}:
            raise TraceValidationError(f"{label} finite value must be a non-Boolean number")
        try:
            finite = math.isfinite(float(result.value))
        except OverflowError:
            finite = False
        if not finite:
            raise TraceValidationError(f"{label} finite value must be finite")
        if result.reason is not None:
            raise TraceValidationError(f"{label} finite value cannot carry a reason")
    else:
        if result.value is not None:
            raise TraceValidationError(f"{label} explicit state needs a null value")
        _require_text(result.reason, f"{label} explicit-state reason")


def _validate_calculation(calculation: Any) -> None:
    if type(calculation) is not TraceCalculation:
        raise TraceValidationError("calculations must be TraceCalculation values")
    _require_id(calculation.calculation_id, "calculation_id")
    _require_id(calculation.coverage_id, f"{calculation.calculation_id} coverage_id")
    _require_id(calculation.method_id, f"{calculation.calculation_id} method_id")
    _require_text(calculation.title, f"{calculation.calculation_id} title")
    if type(calculation.axes) is not tuple:
        raise TraceValidationError(f"{calculation.calculation_id} axes must be a tuple")
    axis_names: set[str] = set()
    for axis in calculation.axes:
        if type(axis) is not TraceAxis:
            raise TraceValidationError(
                f"{calculation.calculation_id} axes must contain TraceAxis values"
            )
        _require_id(axis.name, f"{calculation.calculation_id} axis name")
        _require_text(axis.value, f"{calculation.calculation_id} axis value")
        if axis.name in axis_names:
            raise TraceValidationError(
                f"{calculation.calculation_id} has duplicate axis {axis.name}"
            )
        axis_names.add(axis.name)
    _require_id(calculation.final_step_id, f"{calculation.calculation_id} final_step_id")
    _require_text_tuple(calculation.warnings, f"{calculation.calculation_id} warnings")
    _require_text_tuple(calculation.assumptions, f"{calculation.calculation_id} assumptions")
    if type(calculation.steps) is not tuple or not calculation.steps:
        raise TraceValidationError(
            f"{calculation.calculation_id} needs an immutable non-empty step tuple"
        )

    seen: dict[str, TraceStep] = {}
    for position, step in enumerate(calculation.steps, start=1):
        label = f"{calculation.calculation_id} step {position}"
        if type(step) is not TraceStep:
            raise TraceValidationError(f"{label} must be a TraceStep")
        _require_id(step.step_id, f"{label} step_id")
        if step.step_id in seen:
            raise TraceValidationError(
                f"{calculation.calculation_id} has duplicate step ID {step.step_id}"
            )
        _require_text(step.title, f"{label} title")
        _require_text(step.symbol, f"{label} symbol")
        _require_text(step.actual_expression, f"{label} actual_expression")
        _require_text(
            step.substituted_expression, f"{label} substituted_expression"
        )
        _require_id(step.quantity_role, f"{label} quantity_role")
        if step.quantity_role not in QUANTITY_ROLES:
            raise TraceValidationError(
                f"{label} has unknown quantity role {step.quantity_role!r}"
            )
        _validate_source(step.source, f"{label} source")
        _validate_unit(step.unit, f"{label} unit")
        _validate_result(step.result, f"{label} result")
        _require_text_tuple(step.warnings, f"{label} warnings")
        _require_text_tuple(step.assumptions, f"{label} assumptions")
        if type(step.dependencies) is not tuple:
            raise TraceValidationError(f"{label} dependencies must be a tuple")

        dependency_ids: set[str] = set()
        for dependency in step.dependencies:
            if type(dependency) is not TraceDependency:
                raise TraceValidationError(
                    f"{label} dependencies must contain TraceDependency values"
                )
            _require_id(dependency.step_id, f"{label} dependency step_id")
            _validate_unit(dependency.unit, f"{label} dependency unit")
            if dependency.step_id in dependency_ids:
                raise TraceValidationError(f"{label} has duplicate dependency ID")
            dependency_ids.add(dependency.step_id)
            prior = seen.get(dependency.step_id)
            if prior is None:
                raise TraceValidationError(
                    f"{label} has missing, forward, or cyclic dependency "
                    f"{dependency.step_id}"
                )
            if dependency.unit != prior.unit:
                raise TraceValidationError(
                    f"{label} dependency {dependency.step_id} has a unit mismatch"
                )

        if step.quantity_role == ROLE_USER_INPUT:
            if step.source.kind != SOURCE_INPUT or step.dependencies:
                raise TraceValidationError(
                    f"{label} user inputs need input provenance and no dependencies"
                )
        elif step.quantity_role == ROLE_METHOD_VALUE:
            if step.source.kind not in {SOURCE_STANDARD, SOURCE_PROJECT}:
                raise TraceValidationError(
                    f"{label} method values need standard/project provenance"
                )
            if step.dependencies:
                raise TraceValidationError(
                    f"{label} method values cannot have dependencies"
                )
        elif not step.dependencies:
            raise TraceValidationError(
                f"{label} computed/final quantities need dependencies"
            )
        elif step.source.kind == SOURCE_INPUT:
            raise TraceValidationError(
                f"{label} computed/final quantities cannot have input provenance"
            )
        seen[step.step_id] = step

    final = seen.get(calculation.final_step_id)
    if final is None:
        raise TraceValidationError(
            f"{calculation.calculation_id} final_step_id is missing"
        )
    final_steps = [step for step in calculation.steps if step.quantity_role == ROLE_FINAL]
    if len(final_steps) != 1 or final_steps[0] is not final:
        raise TraceValidationError(
            f"{calculation.calculation_id} needs exactly one matching final_result"
        )

    reachable = {final.step_id}
    pending = [final]
    while pending:
        current = pending.pop()
        for dependency in current.dependencies:
            if dependency.step_id not in reachable:
                reachable.add(dependency.step_id)
                pending.append(seen[dependency.step_id])
    orphaned = sorted(set(seen) - reachable)
    if orphaned:
        raise TraceValidationError(
            f"{calculation.calculation_id} has steps outside the final dependency "
            f"closure: {', '.join(orphaned)}"
        )


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise TraceValidationError(f"trace is not strict JSON data: {exc}") from exc


def _content_sha256(bundle: TraceBundle) -> str:
    payload = bundle.to_dict()
    payload["content_sha256"] = ""
    return hashlib.sha256(_canonical_json(payload).encode("ascii")).hexdigest()


def _validate_structure(bundle: Any, *, require_seal: bool) -> TraceBundle:
    if type(bundle) is not TraceBundle:
        raise TraceValidationError("trace bundle must be a TraceBundle")
    if type(bundle.schema) is not str or bundle.schema != TRACE_SCHEMA:
        raise TraceValidationError(f"unsupported trace schema {bundle.schema!r}")
    for label, digest in (
        ("input_sha256", bundle.input_sha256),
        ("result_sha256", bundle.result_sha256),
    ):
        if type(digest) is not str or not _SHA256_RE.fullmatch(digest):
            raise TraceValidationError(f"{label} must be a lowercase SHA-256")
    if require_seal and (
        type(bundle.content_sha256) is not str
        or not _SHA256_RE.fullmatch(bundle.content_sha256)
    ):
        raise TraceValidationError("content_sha256 must be a lowercase SHA-256")
    _require_text_tuple(bundle.warnings, "trace bundle warnings")
    if type(bundle.calculations) is not tuple or not bundle.calculations:
        raise TraceValidationError(
            "trace bundle needs an immutable non-empty calculation tuple"
        )
    calculation_ids: set[str] = set()
    for calculation in bundle.calculations:
        if (
            type(calculation) is TraceCalculation
            and calculation.calculation_id in calculation_ids
        ):
            raise TraceValidationError(
                f"duplicate calculation ID {calculation.calculation_id}"
            )
        _validate_calculation(calculation)
        calculation_ids.add(calculation.calculation_id)
    return bundle


def seal_bundle(bundle: TraceBundle) -> TraceBundle:
    """Validate and return a bundle with a deterministic content seal."""

    _validate_structure(bundle, require_seal=False)
    unsealed = dataclasses.replace(bundle, content_sha256="")
    return dataclasses.replace(unsealed, content_sha256=_content_sha256(unsealed))


def create_bundle(
    *,
    input_sha256: str,
    result_sha256: str,
    calculations: Sequence[TraceCalculation],
    warnings: Sequence[str] = (),
) -> TraceBundle:
    """Construct, validate, and seal one trace bundle."""

    bundle = TraceBundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=tuple(calculations),
        warnings=tuple(warnings),
    )
    return validate_bundle(seal_bundle(bundle))


def validate_bundle(
    bundle: TraceBundle | dict[str, Any],
    *,
    expected_input_sha256: str | None = None,
    expected_result_sha256: str | None = None,
) -> TraceBundle:
    """Return immutable trace data after strict shape, seal, and freshness checks."""

    try:
        model = bundle if type(bundle) is TraceBundle else TraceBundle.from_dict(bundle)
    except TraceValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"malformed calculation trace: {exc}") from exc
    _validate_structure(model, require_seal=True)
    if model.content_sha256 != _content_sha256(model):
        raise TraceValidationError("calculation trace content seal is invalid")
    if (
        expected_input_sha256 is not None
        and model.input_sha256 != expected_input_sha256
    ):
        raise TraceValidationError(
            "calculation trace does not match the current input fingerprint"
        )
    if (
        expected_result_sha256 is not None
        and model.result_sha256 != expected_result_sha256
    ):
        raise TraceValidationError(
            "calculation trace does not match the current result fingerprint"
        )
    return model


def bundle_to_json(bundle: TraceBundle) -> str:
    """Serialize validated trace data as canonical strict JSON."""

    return _canonical_json(validate_bundle(bundle).to_dict())


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise TraceValidationError(f"duplicate JSON field {key!r}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise TraceValidationError(f"non-finite JSON number {value!r} is forbidden")


def bundle_from_json(payload: str) -> TraceBundle:
    """Deserialize canonical-compatible JSON into validated immutable trace data."""

    if type(payload) is not str:
        raise TraceValidationError("calculation trace JSON must be text")
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except TraceValidationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"malformed calculation trace JSON: {exc}") from exc
    return validate_bundle(value)
