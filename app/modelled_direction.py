"""Canonical display contract for the modelled reinforcement direction.

The engineering result owns the direction once a calculation has been
retained.  Before calculation, the selected section cut supplies the same
member-relative meaning.  A project alias is presentation metadata only: it
may explain local terminology, but it never replaces the canonical
``longitudinal`` or ``transverse`` direction.
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
import string

from sector import detailing

LONGITUDINAL = "longitudinal"
TRANSVERSE = "transverse"
CANONICAL_DIRECTIONS = (LONGITUDINAL, TRANSVERSE)

ALIAS_KEY = "modelled_direction_alias"
MAX_ALIAS_CHARS = 60

_LINE_BREAKS = frozenset("\r\n\v\f\x85\u2028\u2029")
_MARKDOWN_PUNCTUATION = frozenset(string.punctuation)


def _canonical_value(value: object, *, source: str) -> str | None:
    """Return one canonical direction, rejecting an unsupported value."""

    if value is None:
        return None
    text = str(value).strip().casefold()
    if not text:
        return None
    if text not in CANONICAL_DIRECTIONS:
        raise ValueError(
            f"{source} must be longitudinal or transverse"
        )
    return text


def direction_from_cut(cut_direction: object = None) -> str:
    """Map a section-cut direction to the modelled member direction.

    A missing cut uses Sector's existing transverse-cut default.  Unsupported
    non-empty values are rejected so no third direction can reach a published
    label.
    """

    if cut_direction is None or not str(cut_direction).strip():
        cut = detailing.CUT_TRANSVERSE
    else:
        cut = str(cut_direction).strip()
    if cut == detailing.CUT_TRANSVERSE:
        return LONGITUDINAL
    if cut == detailing.CUT_LONGITUDINAL:
        return TRANSVERSE
    raise ValueError("detailing cut direction is not supported")


def canonical_direction(
    result: Mapping[str, object] | None = None,
    *,
    cut_direction: object = None,
) -> str:
    """Resolve the result-owned direction, falling back to the section cut."""

    retained = (
        _canonical_value(
            result.get("modelled_reinforcement_direction"),
            source="retained modelled reinforcement direction",
        )
        if isinstance(result, Mapping)
        else None
    )
    return retained or direction_from_cut(cut_direction)


def normalise_alias(value: object = None) -> str:
    """Return an optional, trimmed single-line project alias.

    Blank input is the canonical representation of no alias.  Newline-like
    Unicode characters are rejected before ordinary horizontal whitespace is
    collapsed for stable persistence and publication.
    """

    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("modelled direction alias must be text")
    if any(character in _LINE_BREAKS for character in value):
        raise ValueError("modelled direction alias must be a single line")
    normalised = " ".join(value.split())
    if len(normalised) > MAX_ALIAS_CHARS:
        raise ValueError(
            "modelled direction alias must be at most 60 characters"
        )
    return normalised


def label(direction: object, alias: object = None) -> str:
    """Label one canonical direction, always placing it before the alias."""

    canonical = _canonical_value(direction, source="modelled direction")
    if canonical is None:
        raise ValueError("modelled direction must be longitudinal or transverse")
    project_alias = normalise_alias(alias)
    base = canonical.capitalize()
    if not project_alias:
        return base
    return f"{base} (project alias: {project_alias})"


def resolved_label(
    result: Mapping[str, object] | None = None,
    *,
    cut_direction: object = None,
    alias: object = None,
) -> str:
    """Resolve and label the modelled direction for any product surface."""

    return label(
        canonical_direction(result, cut_direction=cut_direction),
        alias,
    )


def resolved_html_label(
    result: Mapping[str, object] | None = None,
    *,
    cut_direction: object = None,
    alias: object = None,
) -> str:
    """Return the resolved label escaped for an HTML publication surface."""

    return escape(
        resolved_label(
            result,
            cut_direction=cut_direction,
            alias=alias,
        )
    )


def _markdown_literal(value: str) -> str:
    """Escape ASCII punctuation so Streamlit renders project text literally."""

    return "".join(
        f"\\{character}"
        if character in _MARKDOWN_PUNCTUATION
        else character
        for character in value
    )


def resolved_markdown_label(
    result: Mapping[str, object] | None = None,
    *,
    cut_direction: object = None,
    alias: object = None,
) -> str:
    """Return the resolved label with a literal-safe Streamlit alias."""

    canonical = canonical_direction(
        result, cut_direction=cut_direction
    ).capitalize()
    project_alias = normalise_alias(alias)
    if not project_alias:
        return canonical
    return (
        f"{canonical} (project alias: "
        f"{_markdown_literal(project_alias)})"
    )
