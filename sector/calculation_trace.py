"""Solver-owned, serialisable calculation traces for PI-019.

The model in this module is deliberately presentation-neutral. Engineering
solvers and solver-adjacent trace builders populate it; Streamlit, the
calculation report and the manual only validate and render its records.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


TRACE_SCHEMA = "sector.calculation-trace.v1"

ROLE_USER_INPUT = "user_input"
ROLE_METHOD_VALUE = "method_value"
ROLE_COMPUTED = "computed_intermediate"
ROLE_FINAL = "final_result"
QUANTITY_ROLES = frozenset(
    {ROLE_USER_INPUT, ROLE_METHOD_VALUE, ROLE_COMPUTED, ROLE_FINAL}
)

PROVENANCE_INPUT = "input"
PROVENANCE_STANDARD = "standard"
PROVENANCE_PROJECT = "project"
PROVENANCE_VALUES = frozenset(
    {PROVENANCE_INPUT, PROVENANCE_STANDARD, PROVENANCE_PROJECT}
)

_LEAF_OPERATORS = frozenset({"input", "method"})
_UNCHECKED_OPERATORS = frozenset({"solver"})
_ARITHMETIC_OPERATORS = frozenset(
    {
        "identity",
        "add",
        "sum",
        "subtract",
        "multiply",
        "product",
        "divide",
        "power",
        "pow10",
        "log10",
        "sqrt",
        "cbrt",
        "min",
        "max",
        "abs",
        "hypot",
        "negate",
    }
)
_OPERATORS = _LEAF_OPERATORS | _UNCHECKED_OPERATORS | _ARITHMETIC_OPERATORS
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# A controlled vocabulary catches accidental or adversarial unit replacement.
# "1" means dimensionless. Compound units are explicit because renderers must not
# infer or transform engineering dimensions.
KNOWN_UNITS = frozenset(
    {
        "1",
        "%",
        "mm",
        "m",
        "mm2",
        "mm2/mm",
        "m2",
        "mm3",
        "m3",
        "MPa",
        "GPa",
        "kPa",
        "kN",
        "kN/m",
        "kNm",
        "Nmm",
        "N",
        "N/mm",
        "1/m",
        "cycles",
        "degrees",
    }
)


def trace_identity_token(value: Any) -> str:
    """Return an injective ID-safe token for one exact user-visible label."""

    return f"u{str(value).encode('utf-8').hex()}"


_UNIT_DIMENSION = {
    "1": "dimensionless",
    "%": "dimensionless",
    "cycles": "dimensionless",
    "mm": "length",
    "m": "length",
    "mm2/mm": "length",
    "mm2": "area",
    "m2": "area",
    "mm3": "volume",
    "m3": "volume",
    "MPa": "stress",
    "GPa": "stress",
    "kPa": "stress",
    "kN": "force",
    "N": "force",
    "kN/m": "force_per_length",
    "N/mm": "force_per_length",
    "kNm": "moment",
    "Nmm": "moment",
    "1/m": "inverse_length",
    "degrees": "angle",
}


class TraceValidationError(ValueError):
    """Raised when a calculation trace is missing, stale or internally invalid."""


def _exact_mapping(
    value: Any,
    *,
    label: str,
    keys: frozenset[str],
) -> Mapping[str, Any]:
    """Require the exact JSON object shape owned by the current schema."""

    if not isinstance(value, Mapping):
        raise TraceValidationError(f"{label} must be an object")
    actual = set(value.keys())
    if actual != set(keys):
        missing = sorted((str(item) for item in keys - actual))
        extra = sorted((str(item) for item in actual - keys))
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unexpected {', '.join(extra)}")
        raise TraceValidationError(f"{label} fields: {'; '.join(details)}")
    return value


def _string_list(value: Any, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TraceValidationError(f"{label} must be a JSON list")
    if any(not isinstance(item, str) for item in value):
        raise TraceValidationError(f"{label} entries must be text")
    return tuple(value)


@dataclass(frozen=True)
class SourceCitation:
    """Exact local-standard citation for one method value or equation."""

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
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceCitation":
        value = _exact_mapping(
            value,
            label="source_citation",
            keys=frozenset({"document", "clause", "locator"}),
        )
        return cls(
            document=value["document"],
            clause=value["clause"],
            locator=value["locator"],
        )


@dataclass(frozen=True)
class TraceEvaluation:
    """Machine-readable arithmetic proof for a trace step.

    ``factor`` and ``offset`` are limited to unit conversion or final scaling.
    Every engineering constant still appears as a dependency step. ``solver`` is
    reserved for a clearly labelled project-defined numerical solve whose compact
    result cannot be reconstructed by these elementary operations.
    """

    operator: str
    operand_ids: tuple[str, ...] = ()
    result_unit: str = "1"
    factor: float = 1.0
    offset: float = 0.0
    exponent: float | None = None
    relative_tolerance: float = 1.0e-9
    absolute_tolerance: float = 1.0e-9

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "operand_ids": list(self.operand_ids),
            "result_unit": self.result_unit,
            "factor": self.factor,
            "offset": self.offset,
            "exponent": self.exponent,
            "relative_tolerance": self.relative_tolerance,
            "absolute_tolerance": self.absolute_tolerance,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TraceEvaluation":
        value = _exact_mapping(
            value,
            label="evaluation",
            keys=frozenset(
                {
                    "operator",
                    "operand_ids",
                    "result_unit",
                    "factor",
                    "offset",
                    "exponent",
                    "relative_tolerance",
                    "absolute_tolerance",
                }
            ),
        )
        return cls(
            operator=value["operator"],
            operand_ids=_string_list(
                value["operand_ids"],
                label="evaluation operand_ids",
            ),
            result_unit=value["result_unit"],
            # Preserve raw scalar types until validation. Converting here would
            # silently turn hostile Boolean values into 0.0/1.0.
            factor=value["factor"],
            offset=value["offset"],
            exponent=value["exponent"],
            relative_tolerance=value["relative_tolerance"],
            absolute_tolerance=value["absolute_tolerance"],
        )


@dataclass(frozen=True)
class TraceStep:
    """One ordered quantity in a standards calculation derivation."""

    step_id: str
    title: str
    dependency_ids: tuple[str, ...]
    quantity_role: str
    provenance: str
    symbol: str
    unit: str
    source_citation: SourceCitation | None
    symbolic_expression: str
    substituted_expression: str
    evaluated_value: float
    evaluation: TraceEvaluation
    warnings: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "dependency_ids": list(self.dependency_ids),
            "quantity_role": self.quantity_role,
            "provenance": self.provenance,
            "symbol": self.symbol,
            "unit": self.unit,
            "source_citation": (
                None if self.source_citation is None else self.source_citation.to_dict()
            ),
            "symbolic_expression": self.symbolic_expression,
            "substituted_expression": self.substituted_expression,
            "evaluated_value": self.evaluated_value,
            "evaluation": self.evaluation.to_dict(),
            "warnings": list(self.warnings),
            "assumptions": list(self.assumptions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TraceStep":
        value = _exact_mapping(
            value,
            label="trace step",
            keys=frozenset(
                {
                    "step_id",
                    "title",
                    "dependency_ids",
                    "quantity_role",
                    "provenance",
                    "symbol",
                    "unit",
                    "source_citation",
                    "symbolic_expression",
                    "substituted_expression",
                    "evaluated_value",
                    "evaluation",
                    "warnings",
                    "assumptions",
                }
            ),
        )
        source = value["source_citation"]
        return cls(
            step_id=value["step_id"],
            title=value["title"],
            dependency_ids=_string_list(
                value["dependency_ids"],
                label="trace step dependency_ids",
            ),
            quantity_role=value["quantity_role"],
            provenance=value["provenance"],
            symbol=value["symbol"],
            unit=value["unit"],
            source_citation=(
                None
                if source is None
                else SourceCitation.from_dict(source)
            ),
            symbolic_expression=value["symbolic_expression"],
            substituted_expression=value["substituted_expression"],
            # Preserve the raw type so ``True`` cannot pass as ``1.0``.
            evaluated_value=value["evaluated_value"],
            evaluation=TraceEvaluation.from_dict(value["evaluation"]),
            warnings=_string_list(value["warnings"], label="trace step warnings"),
            assumptions=_string_list(
                value["assumptions"],
                label="trace step assumptions",
            ),
        )


@dataclass(frozen=True)
class TraceCalculation:
    """One complete, dependency-ordered engineering calculation."""

    calculation_id: str
    coverage_id: str
    title: str
    method_id: str
    method_label: str
    standard_based: bool
    user_defined_method: bool
    final_step_id: str
    steps: tuple[TraceStep, ...]
    context: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "calculation_id": self.calculation_id,
            "coverage_id": self.coverage_id,
            "title": self.title,
            "method_id": self.method_id,
            "method_label": self.method_label,
            "standard_based": self.standard_based,
            "user_defined_method": self.user_defined_method,
            "final_step_id": self.final_step_id,
            "steps": [step.to_dict() for step in self.steps],
            "context": [[key, value] for key, value in self.context],
            "warnings": list(self.warnings),
            "assumptions": list(self.assumptions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TraceCalculation":
        value = _exact_mapping(
            value,
            label="trace calculation",
            keys=frozenset(
                {
                    "calculation_id",
                    "coverage_id",
                    "title",
                    "method_id",
                    "method_label",
                    "standard_based",
                    "user_defined_method",
                    "final_step_id",
                    "steps",
                    "context",
                    "warnings",
                    "assumptions",
                }
            ),
        )
        steps = value["steps"]
        if not isinstance(steps, list):
            raise TraceValidationError("trace calculation steps must be a JSON list")
        context = value["context"]
        if not isinstance(context, list):
            raise TraceValidationError("trace calculation context must be a JSON list")
        parsed_context: list[tuple[str, str]] = []
        for position, item in enumerate(context, start=1):
            if (
                not isinstance(item, list)
                or len(item) != 2
                or not all(isinstance(part, str) for part in item)
            ):
                raise TraceValidationError(
                    "trace calculation context entry "
                    f"{position} must be a two-text JSON list"
                )
            parsed_context.append((item[0], item[1]))
        return cls(
            calculation_id=value["calculation_id"],
            coverage_id=value["coverage_id"],
            title=value["title"],
            method_id=value["method_id"],
            method_label=value["method_label"],
            standard_based=value["standard_based"],
            user_defined_method=value["user_defined_method"],
            final_step_id=value["final_step_id"],
            steps=tuple(
                TraceStep.from_dict(item) for item in steps
            ),
            context=tuple(parsed_context),
            warnings=_string_list(
                value["warnings"],
                label="trace calculation warnings",
            ),
            assumptions=_string_list(
                value["assumptions"],
                label="trace calculation assumptions",
            ),
        )


@dataclass(frozen=True)
class TraceBundle:
    """Current-input-correlated set of trace calculations."""

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
            "calculations": [
                calculation.to_dict() for calculation in self.calculations
            ],
            "warnings": list(self.warnings),
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TraceBundle":
        value = _exact_mapping(
            value,
            label="calculation-trace bundle",
            keys=frozenset(
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
        calculations = value["calculations"]
        if not isinstance(calculations, list):
            raise TraceValidationError(
                "calculation-trace calculations must be a JSON list"
            )
        return cls(
            schema=value["schema"],
            input_sha256=value["input_sha256"],
            result_sha256=value["result_sha256"],
            calculations=tuple(
                TraceCalculation.from_dict(item)
                for item in calculations
            ),
            warnings=_string_list(
                value["warnings"],
                label="calculation-trace warnings",
            ),
            content_sha256=value["content_sha256"],
        )


def _normalise(value: Any, *, omit_keys: frozenset[str]) -> Any:
    """Return a deterministic JSON-compatible representation."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            # Solver result payloads legitimately use infinity for quantities
            # such as zero-demand fatigue life.  Preserve that state exactly in
            # freshness fingerprints without permitting it in a trace step
            # (step validation below remains strictly finite).
            if math.isnan(value):
                return {"__sector_float__": "nan"}
            return {
                "__sector_float__": (
                    "positive_infinity" if value > 0.0 else "negative_infinity"
                )
            }
        return 0.0 if value == 0.0 else value
    if isinstance(value, enum.Enum):
        return _normalise(value.value, omit_keys=omit_keys)
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value):
        return {
            field.name: _normalise(
                getattr(value, field.name), omit_keys=omit_keys
            )
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(key): _normalise(item, omit_keys=omit_keys)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in omit_keys
        }
    if isinstance(value, (list, tuple)):
        return [_normalise(item, omit_keys=omit_keys) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_normalise(item, omit_keys=omit_keys) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))

    # Numpy scalars/arrays and pandas frames are optional runtime dependencies.
    if hasattr(value, "item") and callable(value.item):
        try:
            return _normalise(value.item(), omit_keys=omit_keys)
        except (TypeError, ValueError):
            pass
    if hasattr(value, "tolist") and callable(value.tolist):
        try:
            return _normalise(value.tolist(), omit_keys=omit_keys)
        except (TypeError, ValueError):
            pass
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return _normalise(
                value.to_dict(orient="split"), omit_keys=omit_keys
            )
        except TypeError:
            return _normalise(value.to_dict(), omit_keys=omit_keys)
    raise TraceValidationError(
        f"cannot fingerprint value of type {type(value).__name__}"
    )


def fingerprint_payload(
    value: Any,
    *,
    omit_keys: Iterable[str] = ("calculation_trace",),
) -> str:
    """Return a deterministic SHA-256 fingerprint for inputs or solver results."""

    normalised = _normalise(value, omit_keys=frozenset(omit_keys))
    encoded = json.dumps(
        normalised,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _content_payload(bundle: TraceBundle) -> dict[str, Any]:
    payload = bundle.to_dict()
    payload["content_sha256"] = ""
    return payload


def _content_sha256(bundle: TraceBundle) -> str:
    return fingerprint_payload(_content_payload(bundle), omit_keys=())


def seal_bundle(bundle: TraceBundle) -> TraceBundle:
    """Return ``bundle`` with a deterministic content seal."""

    unsealed = dataclasses.replace(bundle, content_sha256="")
    return dataclasses.replace(unsealed, content_sha256=_content_sha256(unsealed))


def create_bundle(
    *,
    input_sha256: str,
    result_sha256: str,
    calculations: Sequence[TraceCalculation],
    warnings: Sequence[str] = (),
) -> TraceBundle:
    """Construct, seal and validate one trace bundle."""

    bundle = TraceBundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=tuple(calculations),
        warnings=tuple(str(item) for item in warnings),
    )
    sealed = seal_bundle(bundle)
    validate_bundle(sealed)
    return sealed


def _require_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise TraceValidationError(f"{label} must be non-empty text")


def _require_id(value: str, label: str) -> None:
    _require_text(value, label)
    if not _ID_RE.fullmatch(value):
        raise TraceValidationError(
            f"{label} must use lowercase letters, digits, dot, dash or underscore"
        )


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TraceValidationError(f"{label} must be a non-Boolean number")
    number = float(value)
    if not math.isfinite(number):
        raise TraceValidationError(f"{label} must be finite")
    return number


def _evaluate(
    evaluation: TraceEvaluation,
    values: Mapping[str, float],
) -> float | None:
    operator = evaluation.operator
    if operator in _LEAF_OPERATORS | _UNCHECKED_OPERATORS:
        return None
    operands = [values[item] for item in evaluation.operand_ids]
    if operator == "identity":
        raw = operands[0]
    elif operator in {"add", "sum"}:
        raw = sum(operands)
    elif operator == "subtract":
        raw = operands[0] - operands[1]
    elif operator in {"multiply", "product"}:
        raw = math.prod(operands)
    elif operator == "divide":
        raw = operands[0] / operands[1]
    elif operator == "power":
        raw = operands[0] ** float(evaluation.exponent)
    elif operator == "pow10":
        raw = 10.0 ** operands[0]
    elif operator == "log10":
        raw = math.log10(operands[0])
    elif operator == "sqrt":
        raw = math.sqrt(operands[0])
    elif operator == "cbrt":
        raw = math.copysign(abs(operands[0]) ** (1.0 / 3.0), operands[0])
    elif operator == "min":
        raw = min(operands)
    elif operator == "max":
        raw = max(operands)
    elif operator == "abs":
        raw = abs(operands[0])
    elif operator == "hypot":
        raw = math.hypot(*operands)
    elif operator == "negate":
        raw = -operands[0]
    else:  # pragma: no cover - guarded before this helper
        raise TraceValidationError(f"unsupported trace operator {operator!r}")
    return raw * evaluation.factor + evaluation.offset


def _validate_citation(citation: SourceCitation, label: str) -> None:
    _require_text(citation.document, f"{label} document")
    _require_text(citation.clause, f"{label} clause")
    _require_text(citation.locator, f"{label} equation/table locator")


def _validate_unit_relation(
    step: TraceStep,
    seen: Mapping[str, TraceStep],
    label: str,
) -> None:
    """Reject dimensionally impossible relations where the model is unambiguous."""

    operator = step.evaluation.operator
    if operator in _LEAF_OPERATORS | _UNCHECKED_OPERATORS:
        return
    operand_dimensions = [
        _UNIT_DIMENSION[seen[item].unit] for item in step.dependency_ids
    ]
    result_dimension = _UNIT_DIMENSION[step.unit]
    same_dimension_operators = {
        "identity",
        "add",
        "sum",
        "subtract",
        "min",
        "max",
        "abs",
        "hypot",
        "negate",
    }
    expected: str | None = None
    if operator in same_dimension_operators:
        if len(set(operand_dimensions)) != 1:
            raise TraceValidationError(
                f"{label}: {operator} operands have incompatible units"
            )
        expected = operand_dimensions[0]
    elif operator == "multiply":
        material = [
            dimension
            for dimension in operand_dimensions
            if dimension != "dimensionless"
        ]
        if len(material) <= 1:
            expected = material[0] if material else "dimensionless"
    elif operator == "product":
        material = [
            dimension
            for dimension in operand_dimensions
            if dimension != "dimensionless"
        ]
        if len(material) <= 1:
            expected = material[0] if material else "dimensionless"
    elif operator == "divide":
        numerator, denominator = operand_dimensions
        if numerator == denominator:
            expected = "dimensionless"
        elif denominator == "dimensionless":
            expected = numerator
    elif operator == "power":
        exponent = step.evaluation.exponent
        if operand_dimensions[0] == "dimensionless":
            expected = "dimensionless"
        elif exponent == 1.0:
            expected = operand_dimensions[0]
        elif operand_dimensions[0] == "length" and exponent == 2.0:
            expected = "area"
        elif operand_dimensions[0] == "length" and exponent == 3.0:
            expected = "volume"
    elif operator in {"log10", "pow10"}:
        if operand_dimensions[0] != "dimensionless":
            raise TraceValidationError(
                f"{label}: {operator} operand must be dimensionless"
            )
        expected = "dimensionless"
    elif operator == "sqrt" and operand_dimensions[0] == "dimensionless":
        expected = "dimensionless"
    elif operator == "cbrt" and operand_dimensions[0] == "dimensionless":
        expected = "dimensionless"

    if expected is not None and result_dimension != expected:
        raise TraceValidationError(
            f"{label}: result unit {step.unit!r} is dimensionally incompatible "
            f"with {operator} dependencies"
        )


def _validate_calculation(
    calculation: TraceCalculation,
    *,
    verify_arithmetic: bool,
) -> None:
    _require_id(calculation.calculation_id, "calculation_id")
    if not re.fullmatch(r"CT-[0-9]{3}", calculation.coverage_id):
        raise TraceValidationError(
            f"{calculation.calculation_id}: coverage_id must be CT-nnn"
        )
    _require_id(calculation.method_id, f"{calculation.calculation_id} method_id")
    _require_text(calculation.title, f"{calculation.calculation_id} title")
    _require_text(
        calculation.method_label, f"{calculation.calculation_id} method_label"
    )
    if not isinstance(calculation.standard_based, bool):
        raise TraceValidationError(
            f"{calculation.calculation_id}: standard_based must be Boolean"
        )
    if not isinstance(calculation.user_defined_method, bool):
        raise TraceValidationError(
            f"{calculation.calculation_id}: user_defined_method must be Boolean"
        )
    if calculation.user_defined_method and calculation.standard_based:
        raise TraceValidationError(
            f"{calculation.calculation_id}: a user-defined method cannot be "
            "labelled standards-based"
        )
    context_keys = [key for key, _value in calculation.context]
    if len(set(context_keys)) != len(context_keys):
        raise TraceValidationError(
            f"{calculation.calculation_id}: duplicate context key"
        )
    for position, (key, value) in enumerate(calculation.context, start=1):
        _require_text(key, f"{calculation.calculation_id} context {position} key")
        _require_text(
            value,
            f"{calculation.calculation_id} context {position} value",
        )
    if not calculation.steps:
        raise TraceValidationError(
            f"{calculation.calculation_id}: at least one trace step is required"
        )

    seen: dict[str, TraceStep] = {}
    values: dict[str, float] = {}
    for position, step in enumerate(calculation.steps, start=1):
        label = f"{calculation.calculation_id} step {position}"
        _require_id(step.step_id, f"{label} step_id")
        if step.step_id in seen:
            raise TraceValidationError(
                f"{calculation.calculation_id}: duplicate step ID {step.step_id}"
            )
        _require_text(step.title, f"{label} title")
        _require_text(step.symbol, f"{label} symbol")
        _require_text(step.symbolic_expression, f"{label} symbolic_expression")
        _require_text(step.substituted_expression, f"{label} substituted_expression")
        if step.quantity_role not in QUANTITY_ROLES:
            raise TraceValidationError(
                f"{label}: unknown quantity role {step.quantity_role!r}"
            )
        if step.provenance not in PROVENANCE_VALUES:
            raise TraceValidationError(
                f"{label}: unknown provenance {step.provenance!r}"
            )
        if step.unit not in KNOWN_UNITS:
            raise TraceValidationError(f"{label}: unsupported unit {step.unit!r}")
        if step.evaluation.result_unit != step.unit:
            raise TraceValidationError(
                f"{label}: evaluation unit {step.evaluation.result_unit!r} "
                f"does not match quantity unit {step.unit!r}"
            )
        value = _finite_number(step.evaluated_value, f"{label} evaluated_value")
        if len(set(step.dependency_ids)) != len(step.dependency_ids):
            raise TraceValidationError(f"{label}: duplicate dependency ID")
        if step.evaluation.operator not in _OPERATORS:
            raise TraceValidationError(
                f"{label}: unsupported operator {step.evaluation.operator!r}"
            )
        operand_count = len(step.evaluation.operand_ids)
        exact_arities = {
            "identity": 1,
            "subtract": 2,
            "divide": 2,
            "power": 1,
            "pow10": 1,
            "log10": 1,
            "sqrt": 1,
            "cbrt": 1,
            "abs": 1,
            "negate": 1,
        }
        minimum_arities = {
            "add": 1,
            "sum": 1,
            "multiply": 2,
            "product": 1,
            "min": 1,
            "max": 1,
            "hypot": 2,
        }
        required = exact_arities.get(step.evaluation.operator)
        if required is not None and operand_count != required:
            raise TraceValidationError(
                f"{label}: operator {step.evaluation.operator!r} requires "
                f"{required} operand(s)"
            )
        minimum = minimum_arities.get(step.evaluation.operator)
        if minimum is not None and operand_count < minimum:
            raise TraceValidationError(
                f"{label}: operator {step.evaluation.operator!r} requires at "
                f"least {minimum} operand(s)"
            )
        if tuple(step.evaluation.operand_ids) != tuple(step.dependency_ids):
            raise TraceValidationError(
                f"{label}: dependency_ids and evaluation operand_ids diverge"
            )
        missing = [item for item in step.dependency_ids if item not in seen]
        if missing:
            raise TraceValidationError(
                f"{label}: missing or forward dependency {', '.join(missing)}"
            )
        _validate_unit_relation(step, seen, label)
        if step.evaluation.operator in _LEAF_OPERATORS and step.dependency_ids:
            raise TraceValidationError(f"{label}: leaf steps cannot have dependencies")
        if (
            step.quantity_role in {ROLE_COMPUTED, ROLE_FINAL}
            and not step.dependency_ids
            and step.evaluation.operator != "solver"
        ):
            raise TraceValidationError(
                f"{label}: a computed/final step needs dependencies or a "
                "labelled numerical solver result"
            )
        if step.evaluation.operator == "power" and step.evaluation.exponent is None:
            raise TraceValidationError(f"{label}: power requires an exponent")
        if step.evaluation.exponent is not None:
            _finite_number(step.evaluation.exponent, f"{label} evaluation exponent")
        _finite_number(step.evaluation.factor, f"{label} evaluation factor")
        _finite_number(step.evaluation.offset, f"{label} evaluation offset")
        rel_tol = _finite_number(
            step.evaluation.relative_tolerance,
            f"{label} relative tolerance",
        )
        abs_tol = _finite_number(
            step.evaluation.absolute_tolerance,
            f"{label} absolute tolerance",
        )
        if rel_tol < 0.0 or abs_tol < 0.0:
            raise TraceValidationError(f"{label}: tolerances cannot be negative")

        if calculation.user_defined_method and step.source_citation is not None:
            raise TraceValidationError(
                f"{label}: user-defined methods cannot carry standards citations"
            )
        if step.provenance == PROVENANCE_STANDARD:
            if step.source_citation is None:
                raise TraceValidationError(
                    f"{label}: a standard-derived step needs an exact citation"
                )
            _validate_citation(step.source_citation, label)
        elif step.source_citation is not None:
            raise TraceValidationError(
                f"{label}: input/project steps cannot carry a standards citation"
            )
        if step.quantity_role == ROLE_USER_INPUT and step.provenance != PROVENANCE_INPUT:
            raise TraceValidationError(
                f"{label}: a user input must have input provenance"
            )
        if verify_arithmetic:
            try:
                reconstructed = _evaluate(step.evaluation, values)
            except (ArithmeticError, OverflowError, ValueError) as exc:
                raise TraceValidationError(
                    f"{label}: arithmetic reconstruction failed: {exc}"
                ) from exc
            if reconstructed is not None and not math.isclose(
                reconstructed,
                value,
                rel_tol=rel_tol,
                abs_tol=abs_tol,
            ):
                raise TraceValidationError(
                    f"{label}: evaluated value {value:.12g} does not match "
                    f"dependency reconstruction {reconstructed:.12g}"
                )
        seen[step.step_id] = step
        values[step.step_id] = value

    if calculation.final_step_id not in seen:
        raise TraceValidationError(
            f"{calculation.calculation_id}: final_step_id is missing"
        )
    if seen[calculation.final_step_id].quantity_role != ROLE_FINAL:
        raise TraceValidationError(
            f"{calculation.calculation_id}: final step must have final_result role"
        )
    final_count = sum(
        step.quantity_role == ROLE_FINAL for step in calculation.steps
    )
    if final_count != 1:
        raise TraceValidationError(
            f"{calculation.calculation_id}: exactly one final_result is required"
        )


def validate_bundle(
    bundle: TraceBundle | Mapping[str, Any],
    *,
    expected_input_sha256: str | None = None,
    expected_result_sha256: str | None = None,
    verify_arithmetic: bool = True,
) -> TraceBundle:
    """Validate schema, order, arithmetic, content seal and freshness.

    The returned immutable model is safe for a renderer to consume. Renderers do
    not calculate engineering values; they display the already evaluated records.
    """

    try:
        model = (
            bundle
            if isinstance(bundle, TraceBundle)
            else TraceBundle.from_dict(bundle)
        )
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(
            f"malformed calculation-trace payload: {exc}"
        ) from exc
    if model.schema != TRACE_SCHEMA:
        raise TraceValidationError(
            f"unsupported calculation-trace schema {model.schema!r}"
        )
    for label, digest in (
        ("input_sha256", model.input_sha256),
        ("result_sha256", model.result_sha256),
        ("content_sha256", model.content_sha256),
    ):
        if not _SHA256_RE.fullmatch(digest):
            raise TraceValidationError(f"{label} must be a lowercase SHA-256")
    if expected_input_sha256 is not None and model.input_sha256 != expected_input_sha256:
        raise TraceValidationError(
            "calculation trace does not match the current input signature"
        )
    if (
        expected_result_sha256 is not None
        and model.result_sha256 != expected_result_sha256
    ):
        raise TraceValidationError(
            "calculation trace does not match the solver result payload"
        )
    expected_content = _content_sha256(model)
    if model.content_sha256 != expected_content:
        raise TraceValidationError("calculation trace content seal is invalid")
    if not model.calculations:
        raise TraceValidationError("a calculation trace bundle cannot be empty")
    calculation_ids: set[str] = set()
    for calculation in model.calculations:
        if calculation.calculation_id in calculation_ids:
            raise TraceValidationError(
                f"duplicate calculation ID {calculation.calculation_id}"
            )
        calculation_ids.add(calculation.calculation_id)
        _validate_calculation(
            calculation,
            verify_arithmetic=verify_arithmetic,
        )
    return model


def calculation_context(calculation: TraceCalculation) -> dict[str, str]:
    """Return a calculation's immutable context as a normal mapping."""

    return dict(calculation.context)


def filter_calculations(
    bundle: TraceBundle,
    **context: str,
) -> tuple[TraceCalculation, ...]:
    """Select calculations by exact context fields without changing their order."""

    requested = {str(key): str(value) for key, value in context.items()}
    return tuple(
        calculation
        for calculation in bundle.calculations
        if all(
            calculation_context(calculation).get(key) == value
            for key, value in requested.items()
        )
    )
