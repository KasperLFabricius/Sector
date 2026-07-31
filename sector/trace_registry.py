"""Declarative exact-family contracts for PI-019 calculation traces."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .calculation_trace import (
    QUANTITY_ROLES,
    RESULT_STATES,
    SOURCE_KINDS,
    SOURCE_STANDARD,
    SourceCitation,
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
class TraceStepMetadataContract:
    """Exact canonical role and complete source identity for one step ID."""

    step_id: str
    quantity_role: str
    source: TraceSource


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
    step_metadata: tuple[TraceStepMetadataContract, ...] = ()


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


def _validate_exact_source(source: object, label: str) -> None:
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


def _validate_step_contract(member: TraceMemberContract) -> None:
    label = member.member_id
    if (
        type(member.step_ids) is not tuple
        or type(member.step_dependencies) is not tuple
        or type(member.step_metadata) is not tuple
    ):
        raise TraceValidationError(
            f"{label} step contracts must be immutable tuples"
        )

    step_ids: list[str] = []
    for step_id in member.step_ids:
        _require_id(step_id, f"{label} step ID")
        if step_id in step_ids:
            raise TraceValidationError(
                f"{label} has duplicate step ID {step_id}"
            )
        step_ids.append(step_id)

    dependency_rows: list[tuple[str, tuple[str, ...]]] = []
    dependency_step_ids: set[str] = set()
    for dependency in member.step_dependencies:
        if type(dependency) is not tuple or len(dependency) != 2:
            raise TraceValidationError(
                f"{label} has malformed dependency contract"
            )
        step_id, dependency_ids = dependency
        _require_id(step_id, f"{label} dependency step ID")
        if step_id in dependency_step_ids:
            raise TraceValidationError(
                f"{label} has duplicate dependency step {step_id}"
            )
        dependency_step_ids.add(step_id)
        if type(dependency_ids) is not tuple:
            raise TraceValidationError(
                f"{label} dependency IDs must be a tuple"
            )

        seen_dependencies: set[str] = set()
        for dependency_id in dependency_ids:
            _require_id(dependency_id, f"{label} dependency ID")
            if dependency_id in seen_dependencies:
                raise TraceValidationError(
                    f"{label} step {step_id} has duplicate dependency "
                    f"{dependency_id}"
                )
            seen_dependencies.add(dependency_id)
        dependency_rows.append((step_id, dependency_ids))

    metadata_step_ids: set[str] = set()
    for metadata in member.step_metadata:
        if type(metadata) is not TraceStepMetadataContract:
            raise TraceValidationError(
                f"{label} step metadata must contain "
                "TraceStepMetadataContract values"
            )
        _require_id(metadata.step_id, f"{label} metadata step ID")
        if metadata.step_id in metadata_step_ids:
            raise TraceValidationError(
                f"{label} has duplicate metadata step {metadata.step_id}"
            )
        metadata_step_ids.add(metadata.step_id)
        _require_id(metadata.quantity_role, f"{label} metadata quantity role")
        if metadata.quantity_role not in QUANTITY_ROLES:
            raise TraceValidationError(
                f"{label} step {metadata.step_id} has unknown quantity role "
                f"{metadata.quantity_role!r}"
            )
        _validate_exact_source(
            metadata.source,
            f"{label} step {metadata.step_id} metadata source",
        )

    if not dependency_rows:
        return

    row_order = tuple(step_id for step_id, _ in dependency_rows)
    if step_ids and row_order != tuple(step_ids):
        raise TraceValidationError(
            f"{label} dependency map must match exact step order"
        )

    declared_order = tuple(step_ids) if step_ids else row_order
    positions = {
        step_id: position for position, step_id in enumerate(declared_order)
    }
    for step_id, dependency_ids in dependency_rows:
        for dependency_id in dependency_ids:
            if dependency_id not in positions:
                raise TraceValidationError(
                    f"{label} step {step_id} has missing dependency "
                    f"{dependency_id}"
                )
            if positions[dependency_id] >= positions[step_id]:
                raise TraceValidationError(
                    f"{label} step {step_id} has forward dependency "
                    f"{dependency_id}"
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
            _validate_step_contract(member)
            expected[member.calculation_id] = (family, member)
    return expected


def audit_trace_registry(
    bundle: TraceBundle,
    registry: TraceRegistryContract,
) -> TraceBundle:
    """Validate exact family identity and independently selected step contracts."""

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
        if member.step_dependencies:
            actual_dependencies = tuple(
                (
                    step.step_id,
                    tuple(
                        dependency.step_id
                        for dependency in step.dependencies
                    ),
                )
                for step in calculation.steps
            )
            if actual_dependencies != member.step_dependencies:
                mismatches.append(
                    "dependency graph differs from the selected contract"
                )
        if member.step_metadata:
            actual_metadata_ids = tuple(step.step_id for step in calculation.steps)
            declared_metadata_ids = tuple(
                metadata.step_id for metadata in member.step_metadata
            )
            missing_metadata = sorted(
                set(actual_metadata_ids) - set(declared_metadata_ids)
            )
            unknown_metadata = sorted(
                set(declared_metadata_ids) - set(actual_metadata_ids)
            )
            if missing_metadata:
                mismatches.append(
                    "missing step metadata for " + ", ".join(missing_metadata)
                )
            if unknown_metadata:
                mismatches.append(
                    "unknown/extra step metadata for "
                    + ", ".join(unknown_metadata)
                )
            if not missing_metadata and not unknown_metadata:
                if declared_metadata_ids != actual_metadata_ids:
                    mismatches.append(
                        "step metadata rows differ from calculation step order"
                    )
                declared_metadata = {
                    metadata.step_id: metadata for metadata in member.step_metadata
                }
                for step in calculation.steps:
                    metadata = declared_metadata[step.step_id]
                    if step.quantity_role != metadata.quantity_role:
                        mismatches.append(
                            f"step {step.step_id} quantity role "
                            f"{step.quantity_role!r}, expected "
                            f"{metadata.quantity_role!r}"
                        )
                    if step.source != metadata.source:
                        mismatches.append(
                            f"step {step.step_id} source {step.source!r}, "
                            f"expected {metadata.source!r}"
                        )
        if mismatches:
            raise TraceValidationError(
                f"{family.family_id}/{member.member_id} identity mismatch: "
                + "; ".join(mismatches)
            )
    return model
