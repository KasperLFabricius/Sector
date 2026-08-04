"""Fail-closed publication spine for the accepted Part C equations.

The manual remains authored as Markdown.  This module binds that live block
stream through the accepted location, source and semantic contracts, then
replaces only the 32 canonical display expressions with typed equation blocks.
It contains no Streamlit, ReportLab, solver or report-renderer dependency.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from manual_equation_contract import (
    ContractedManualEquation,
    MANUAL_EQUATION_CONTRACTS,
    ManualEquationContract,
    bind_manual_equation_contracts,
)
from manual_equation_location import (
    DISPLAY_DELIMITER,
    MANUAL_EQUATION_LOCATIONS,
    PART_C,
    LocatedManualEquation,
    ManualEquationLocation,
    register_manual_equation_locations,
)
from manual_equation_source import (
    MANUAL_EQUATION_SOURCES,
    SOURCE_MIXED,
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    ManualEquationSource,
    SourcedManualEquation,
    bind_manual_equation_sources,
)


EQUATION_BLOCK = "equation"
SOURCE_KIND_LABELS = {
    SOURCE_STANDARD: "Standard source",
    SOURCE_MIXED: "Mixed source",
    SOURCE_PROJECT: "Project-defined method",
}


def _normalise_expression(raw: str) -> str:
    expression = re.sub(r"\s+", " ", raw).strip()
    if not expression or not expression.isascii():
        raise ValueError("Published manual equation must retain ASCII expression text.")
    return expression


def bind_manual_publication_equations(
    blocks: Iterable[tuple[str, object]],
) -> tuple[ContractedManualEquation, ...]:
    """Bind the live manual through every accepted equation contract layer."""

    frozen_blocks = tuple(blocks)
    located = register_manual_equation_locations(frozen_blocks)
    sourced = bind_manual_equation_sources(located)
    return bind_manual_equation_contracts(sourced)


def manual_publication_blocks(
    blocks: Iterable[tuple[str, object]],
) -> tuple[tuple[str, object], ...]:
    """Return manual blocks with canonical Part C displays typed for rendering.

    Prose fragments are preserved in their original order and text.  A renderer
    never discovers or selects equation identity, provenance or semantics: all
    of those fields arrive in one exact ``ContractedManualEquation`` payload.
    """

    frozen_blocks = tuple(blocks)
    equations = bind_manual_publication_equations(frozen_blocks)
    equation_index = 0
    part = ""
    published: list[tuple[str, object]] = []

    for block in frozen_blocks:
        if not isinstance(block, tuple) or len(block) < 2:
            raise ValueError("Manual block must remain a tuple with two fields.")
        kind = block[0]
        payload = block[1]
        if kind == "part":
            if type(payload) is not str:
                raise ValueError("Manual part payload must retain string type.")
            part = payload

        if (
            part != PART_C
            or kind != "md"
            or type(payload) is not str
            or DISPLAY_DELIMITER not in payload
        ):
            published.append(block)
            continue

        fragments = payload.split(DISPLAY_DELIMITER)
        if len(fragments) % 2 == 0:
            raise ValueError("Part C contains an unpaired display delimiter.")
        for fragment_index, fragment in enumerate(fragments):
            if fragment_index % 2 == 0:
                if fragment:
                    published.append(("md", fragment))
                continue
            if equation_index >= len(equations):
                raise ValueError("Part C publishes an unknown display equation.")
            equation = equations[equation_index]
            expression = equation.equation.equation.expression
            if _normalise_expression(fragment) != expression:
                raise ValueError(
                    f"Manual equation {equation.contract.number} expression changed."
                )
            published.append((EQUATION_BLOCK, equation))
            equation_index += 1

    if equation_index != len(equations):
        raise ValueError(
            f"Published equation cardinality changed: expected {len(equations)}, "
            f"got {equation_index}."
        )
    return tuple(published)


def dependency_numbers(
    equation: ContractedManualEquation,
    catalogue: tuple[ManualEquationContract, ...] = MANUAL_EQUATION_CONTRACTS,
) -> tuple[str, ...]:
    """Resolve one canonical dependency list to stable public numbers."""

    _validate_published_equation(equation)
    if type(catalogue) is not tuple or catalogue != MANUAL_EQUATION_CONTRACTS:
        raise ValueError("Canonical manual equation contract catalogue changed.")
    by_key = {item.key: item.number for item in catalogue}
    return tuple(by_key[key] for key in equation.contract.uses)


def source_kind_label(equation: ContractedManualEquation) -> str:
    """Return the visible label for an exact canonical source classification."""

    _validate_published_equation(equation)
    try:
        return SOURCE_KIND_LABELS[equation.equation.source.source_kind]
    except KeyError as exc:
        raise ValueError("Published equation source kind changed.") from exc


def _validate_published_equation(equation: ContractedManualEquation) -> None:
    """Reject any renderer payload not equal to one exact canonical chain."""

    if type(equation) is not ContractedManualEquation:
        raise ValueError("Published equation type changed.")
    sourced = equation.equation
    if type(sourced) is not SourcedManualEquation:
        raise ValueError("Published sourced equation type changed.")
    located = sourced.equation
    if type(located) is not LocatedManualEquation:
        raise ValueError("Published located equation type changed.")
    if type(located.location) is not ManualEquationLocation:
        raise ValueError("Published equation location type changed.")
    if type(sourced.source) is not ManualEquationSource:
        raise ValueError("Published equation source type changed.")
    ordinal = equation.contract.ordinal
    if type(ordinal) is not int or not 1 <= ordinal <= len(MANUAL_EQUATION_CONTRACTS):
        raise ValueError("Published equation ordinal changed.")
    index = ordinal - 1
    if equation.contract != MANUAL_EQUATION_CONTRACTS[index]:
        raise ValueError("Published equation contract identity changed.")
    if located.location != MANUAL_EQUATION_LOCATIONS[index]:
        raise ValueError("Published equation location identity changed.")
    if sourced.source != MANUAL_EQUATION_SOURCES[index]:
        raise ValueError("Published equation source identity changed.")
    expression = located.expression
    if type(expression) is not str or not expression.isascii():
        raise ValueError("Published equation expression type changed.")
    digest = hashlib.sha256(expression.encode("ascii")).hexdigest()
    if digest != located.location.expression_sha256:
        raise ValueError("Published equation expression changed.")
