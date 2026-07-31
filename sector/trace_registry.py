"""Declarative exact-family contracts for PI-019 calculation traces."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .calculation_trace import (
    RESULT_STATES,
    SOURCE_KINDS,
    SOURCE_STANDARD,
    TraceAxis,
    TraceBundle,
    TraceSource,
    TraceValidationError,
    validate_bundle,
)


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class TraceSourceContract:
    """One exact leaf-level source method and optional standards edition."""

    kind: str
    method_id: str
    edition: str | None = None


@dataclass(frozen=True, slots=True)
class TraceMemberContract:
    """Exact identity and result requirements for one retained calculation."""

    member_id: str
    calculation_id: str
    coverage_id: str
    method_id: str
    axes: tuple[TraceAxis, ...]
    sources: frozenset[TraceSourceContract]
    result_states: frozenset[str]
    step_ids: tuple[str, ...] = ()
    step_dependencies: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class TraceFamilyContract:
    family_id: str
    members: tuple[TraceMemberContract, ...]


@dataclass(frozen=True, slots=True)
class TraceRegistryContract:
    registry_id: str
    families: tuple[TraceFamilyContract, ...]


def _require_id(value: object, label: str) -> None:
    if type(value) is not str or not _ID_RE.fullmatch(value):
        raise TraceValidationError(f"{label} must be a lowercase stable ID")


def _require_text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise TraceValidationError(f"{label} must be non-empty trimmed text")


def _validate_source_contract(source: object, label: str) -> None:
    if type(source) is not TraceSourceContract:
        raise TraceValidationError(f"{label} sources must contain TraceSourceContract values")
    _require_id(source.kind, f"{label} source kind")
    if source.kind not in SOURCE_KINDS:
        raise TraceValidationError(f"{label} has unknown source kind {source.kind!r}")
    _require_id(source.method_id, f"{label} source method_id")
    if source.kind == SOURCE_STANDARD:
        _require_text(source.edition, f"{label} source edition")
    elif source.edition is not None:
        raise TraceValidationError(f"{label} non-standard source cannot declare an edition")


def _source_contract(source: TraceSource) -> TraceSourceContract:
    return TraceSourceContract(
        kind=source.kind,
        method_id=source.method_id,
        edition=source.edition,
    )


def _validate_registry(registry: object) -> dict[str, tuple[TraceFamilyContract, TraceMemberContract]]:
    if type(registry) is not TraceRegistryContract:
        raise TraceValidationError("registry must be a TraceRegistryContract")
    _require_id(registry.registry_id, "registry_id")
    if type(registry.families) is not tuple or not registry.families:
        raise TraceValidationError("registry needs an immutable non-empty family tuple")

    family_ids: set[str] = set()
    member_ids: set[str] = set()
    expected: dict[str, tuple[TraceFamilyContract, TraceMemberContract]] = {}
    for family in registry.families:
        if type(family) is not TraceFamilyContract:
            raise TraceValidationError("registry families must contain TraceFamilyContract values")
        _require_id(family.family_id, "registry family_id")
        if family.family_id in family_ids:
            raise TraceValidationError(f"{registry.registry_id} has duplicate family {family.family_id}")
        family_ids.add(family.family_id)
        if type(family.members) is not tuple or not family.members:
            raise TraceValidationError(f"{family.family_id} needs an immutable non-empty member tuple")
        for member in family.members:
            if type(member) is not TraceMemberContract:
                raise TraceValidationError(f"{family.family_id} members must be TraceMemberContract values")
            for label, value in (
                ("member_id", member.member_id),
                ("calculation_id", member.calculation_id),
                ("coverage_id", member.coverage_id),
                ("method_id", member.method_id),
            ):
                _require_id(value, f"{family.family_id} {label}")
            if member.member_id in member_ids:
                raise TraceValidationError(
                    f"{registry.registry_id} has duplicate member {member.member_id}"
                )
            member_ids.add(member.member_id)
            if member.calculation_id in expected:
                raise TraceValidationError(
                    f"{registry.registry_id} has non-injective calculation ID "
                    f"{member.calculation_id}"
                )
            if type(member.axes) is not tuple:
                raise TraceValidationError(f"{member.member_id} axes must be a tuple")
            axis_names: set[str] = set()
            for axis in member.axes:
                if type(axis) is not TraceAxis:
                    raise TraceValidationError(
                        f"{member.member_id} axes must contain TraceAxis values"
                    )
                _require_id(axis.name, f"{member.member_id} axis name")
                _require_text(axis.value, f"{member.member_id} axis value")
                if axis.name in axis_names:
                    raise TraceValidationError(
                        f"{member.member_id} has duplicate axis {axis.name}"
                    )
                axis_names.add(axis.name)
            if type(member.sources) is not frozenset or not member.sources:
                raise TraceValidationError(
                    f"{member.member_id} needs a non-empty source contract set"
                )
            for source in member.sources:
                _validate_source_contract(source, member.member_id)
            if (
                type(member.result_states) is not frozenset
                or not member.result_states
            ):
                raise TraceValidationError(
                    f"{member.member_id} declares invalid result states"
                )
            for state in member.result_states:
                _require_id(state, f"{member.member_id} result state")
            if not member.result_states <= RESULT_STATES:
                raise TraceValidationError(
                    f"{member.member_id} declares invalid result states"
                )
            if type(member.step_ids) is not tuple or type(member.step_dependencies) is not tuple:
                raise TraceValidationError(
                    f"{member.member_id} step contracts must be immutable tuples"
                )
            for step_id in member.step_ids:
                _require_id(step_id, f"{member.member_id} step ID")
            dependency_steps = []
            for dependency in member.step_dependencies:
                if type(dependency) is not tuple or len(dependency) != 2:
                    raise TraceValidationError(
                        f"{member.member_id} has malformed dependency contract"
                    )
                step_id, dependency_ids = dependency
                _require_id(step_id, f"{member.member_id} dependency step ID")
                if type(dependency_ids) is not tuple:
                    raise TraceValidationError(
                        f"{member.member_id} dependency IDs must be a tuple"
                    )
                for dependency_id in dependency_ids:
                    _require_id(
                        dependency_id,
                        f"{member.member_id} dependency ID",
                    )
                dependency_steps.append(step_id)
            if member.step_ids and tuple(dependency_steps) != member.step_ids:
                raise TraceValidationError(
                    f"{member.member_id} dependency map must match exact step order"
                )
            expected[member.calculation_id] = (family, member)
    return expected


def audit_trace_registry(
    bundle: TraceBundle,
    registry: TraceRegistryContract,
) -> TraceBundle:
    """Validate exact members, axes, local sources, editions, and result states."""

    model = validate_bundle(bundle)
    expected = _validate_registry(registry)
    actual = {item.calculation_id: item for item in model.calculations}
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected {', '.join(unexpected)}")
        raise TraceValidationError(
            f"{registry.registry_id} registry is incomplete: {'; '.join(details)}"
        )

    for calculation_id, (family, member) in expected.items():
        calculation = actual[calculation_id]
        final = next(
            item
            for item in calculation.steps
            if item.step_id == calculation.final_step_id
        )
        sources = frozenset(_source_contract(item.source) for item in calculation.steps)
        mismatches = []
        if calculation.coverage_id != member.coverage_id:
            mismatches.append(
                f"coverage {calculation.coverage_id!r}, expected {member.coverage_id!r}"
            )
        if calculation.method_id != member.method_id:
            mismatches.append(
                f"method {calculation.method_id!r}, expected {member.method_id!r}"
            )
        if calculation.axes != member.axes:
            mismatches.append(
                f"axes {calculation.axes!r}, expected {member.axes!r}"
            )
        if sources != member.sources:
            mismatches.append(f"sources {sources!r}, expected {member.sources!r}")
        if final.result.state not in member.result_states:
            mismatches.append(
                f"result state {final.result.state!r}, expected one of "
                f"{sorted(member.result_states)!r}"
            )
        actual_step_ids = tuple(step.step_id for step in calculation.steps)
        if member.step_ids and actual_step_ids != member.step_ids:
            mismatches.append(
                f"step IDs {actual_step_ids!r}, expected {member.step_ids!r}"
            )
        actual_dependencies = tuple(
            (
                step.step_id,
                tuple(dependency.step_id for dependency in step.dependencies),
            )
            for step in calculation.steps
        )
        if (
            member.step_dependencies
            and actual_dependencies != member.step_dependencies
        ):
            mismatches.append("dependency graph differs from the selected contract")
        if mismatches:
            raise TraceValidationError(
                f"{family.family_id}/{member.member_id} identity mismatch: "
                + "; ".join(mismatches)
            )
    return model
