"""Declarative completeness invariants for solver-owned calculation traces.

The numerical kernels and trace builders remain authoritative.  This module
does not evaluate an engineering expression; it verifies that the exact trace
members declared for one selected solver result were produced injectively and
remain structurally publishable.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .calculation_trace import TraceCalculation, TraceValidationError


FINITE_RESULT = "finite"
EXPLICIT_STATE = "explicit-state"
TraceResultState = Literal["finite", "explicit-state"]


@dataclass(frozen=True)
class TraceMemberExpectation:
    """Exact identity and publication state required for one calculation."""

    member_id: str
    calculation_id: str
    coverage_id: str
    method_id: str
    context: tuple[tuple[str, str], ...]
    standard_based: bool
    user_defined_method: bool
    standard_family: str
    result_state: TraceResultState = FINITE_RESULT
    required_documents: frozenset[str] = frozenset()
    forbidden_documents: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TraceFamilyExpectation:
    """One registered family and every member required by the selected case."""

    family_id: str
    label: str
    coverage_ids: frozenset[str]
    members: tuple[TraceMemberExpectation, ...]


def _calculation_documents(calculation: TraceCalculation) -> frozenset[str]:
    return frozenset(
        step.source_citation.document
        for step in calculation.steps
        if step.source_citation is not None
    )


def _warning_text(calculation: TraceCalculation) -> str:
    return " ".join(
        (
            *calculation.warnings,
            *(
                warning
                for step in calculation.steps
                for warning in step.warnings
            ),
        )
    ).strip()


def _audit_structure(
    calculation: TraceCalculation,
    expectation: TraceMemberExpectation,
) -> None:
    """Enforce dependency closure and finite trace-state representation."""

    seen: set[str] = set()
    final_found = False
    for step in calculation.steps:
        if step.step_id in seen:
            raise TraceValidationError(
                f"{expectation.member_id}: duplicate step ID {step.step_id}"
            )
        if len(set(step.dependency_ids)) != len(step.dependency_ids):
            raise TraceValidationError(
                f"{expectation.member_id}: duplicate dependency ID"
            )
        missing = [
            dependency
            for dependency in step.dependency_ids
            if dependency not in seen
        ]
        if missing:
            raise TraceValidationError(
                f"{expectation.member_id}: missing or forward dependency "
                f"{', '.join(missing)}"
            )
        value = step.evaluated_value
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise TraceValidationError(
                f"{expectation.member_id}: trace values must be finite "
                "non-Boolean numbers"
            )
        seen.add(step.step_id)
        final_found = final_found or step.step_id == calculation.final_step_id

    if not final_found:
        raise TraceValidationError(
            f"{expectation.member_id}: final trace step is missing"
        )
    if (
        expectation.result_state == EXPLICIT_STATE
        and not _warning_text(calculation)
    ):
        raise TraceValidationError(
            f"{expectation.member_id}: an explicit solver failure/non-finite "
            "state requires a published warning"
        )


def audit_trace_registry(
    calculations: Sequence[TraceCalculation],
    *,
    scope_id: str,
    families: Sequence[TraceFamilyExpectation],
) -> None:
    """Audit one selected solver scope against a declarative family registry."""

    family_ids: set[str] = set()
    coverage_owner: dict[str, str] = {}
    member_ids: set[str] = set()
    expected_calculation_ids: set[str] = set()
    for family in families:
        if family.family_id in family_ids:
            raise TraceValidationError(
                f"{scope_id}: duplicate registry family {family.family_id}"
            )
        family_ids.add(family.family_id)
        if not family.coverage_ids:
            raise TraceValidationError(
                f"{scope_id}: registry family {family.family_id} owns no "
                "coverage IDs"
            )
        for coverage_id in family.coverage_ids:
            previous = coverage_owner.get(coverage_id)
            if previous is not None:
                raise TraceValidationError(
                    f"{scope_id}: coverage ID {coverage_id} is owned by both "
                    f"{previous} and {family.family_id}"
                )
            coverage_owner[coverage_id] = family.family_id
        for member in family.members:
            if member.member_id in member_ids:
                raise TraceValidationError(
                    f"{scope_id}: duplicate registry member {member.member_id}"
                )
            member_ids.add(member.member_id)
            if member.calculation_id in expected_calculation_ids:
                raise TraceValidationError(
                    f"{scope_id}: non-injective expected calculation ID "
                    f"{member.calculation_id}"
                )
            expected_calculation_ids.add(member.calculation_id)
            if member.coverage_id not in family.coverage_ids:
                raise TraceValidationError(
                    f"{scope_id}: {member.member_id} uses unowned coverage ID "
                    f"{member.coverage_id}"
                )

    actual_by_id: dict[str, TraceCalculation] = {}
    for calculation in calculations:
        if calculation.calculation_id in actual_by_id:
            raise TraceValidationError(
                f"{scope_id}: duplicate calculation ID "
                f"{calculation.calculation_id}"
            )
        actual_by_id[calculation.calculation_id] = calculation
        if calculation.coverage_id not in coverage_owner:
            raise TraceValidationError(
                f"{scope_id}: unregistered trace coverage "
                f"{calculation.coverage_id}"
            )

    for family in families:
        expected = {
            member.calculation_id: member
            for member in family.members
        }
        actual = {
            calculation.calculation_id: calculation
            for calculation in calculations
            if calculation.coverage_id in family.coverage_ids
        }
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        if missing or unexpected:
            details = []
            if missing:
                details.append(f"missing {', '.join(missing)}")
            if unexpected:
                details.append(f"unexpected {', '.join(unexpected)}")
            raise TraceValidationError(
                f"{family.label} trace registry is incomplete: "
                + "; ".join(details)
            )

        for calculation_id, member in expected.items():
            calculation = actual[calculation_id]
            actual_context = tuple(calculation.context)
            mismatches = []
            if calculation.coverage_id != member.coverage_id:
                mismatches.append(
                    f"coverage {calculation.coverage_id!r}, expected "
                    f"{member.coverage_id!r}"
                )
            if calculation.method_id != member.method_id:
                mismatches.append(
                    f"method {calculation.method_id!r}, expected "
                    f"{member.method_id!r}"
                )
            if actual_context != member.context:
                mismatches.append(
                    f"context {actual_context!r}, expected {member.context!r}"
                )
            if calculation.standard_based is not member.standard_based:
                mismatches.append(
                    f"standard_based={calculation.standard_based!r}, expected "
                    f"{member.standard_based!r}"
                )
            if (
                calculation.user_defined_method
                is not member.user_defined_method
            ):
                mismatches.append(
                    "user_defined_method="
                    f"{calculation.user_defined_method!r}, expected "
                    f"{member.user_defined_method!r}"
                )

            documents = _calculation_documents(calculation)
            missing_documents = sorted(
                member.required_documents - documents
            )
            forbidden_documents = sorted(
                member.forbidden_documents & documents
            )
            if missing_documents:
                mismatches.append(
                    f"standard family {member.standard_family!r} is missing "
                    f"{', '.join(missing_documents)}"
                )
            if forbidden_documents:
                mismatches.append(
                    f"standard family {member.standard_family!r} includes "
                    f"forbidden {', '.join(forbidden_documents)}"
                )
            if member.standard_based and not documents:
                mismatches.append(
                    f"standard family {member.standard_family!r} has no "
                    "standards citation"
                )
            if member.user_defined_method and documents:
                mismatches.append(
                    "user-defined method carries a standards citation"
                )
            if mismatches:
                raise TraceValidationError(
                    f"{member.member_id} trace identity mismatch: "
                    + "; ".join(mismatches)
                )
            _audit_structure(calculation, member)
