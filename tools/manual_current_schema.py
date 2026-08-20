"""Dormant current-schema identity check for the issued user manual."""

from __future__ import annotations

import re


CURRENT_PROJECT_SAVE_WORDING = (
    "Every downloaded project save uses the current schema"
)

_REFERENCE_SUFFIX = r"[^\s,;:!?()\[\]{}\"'<>]*"
_SCHEMA_REFERENCE = re.compile(
    r"\bschema\b[\"']?\s*"
    r"(?:[:=#-]\s*)?"
    r"[\"']?\s*"
    r"(?:version\b\s*(?:[:=#-]\s*)?)?"
    r"[\"']?\s*v?\s*"
    rf"(?P<version>\d{_REFERENCE_SUFFIX})",
    flags=re.IGNORECASE,
)


def current_schema_wording(project_schema: int) -> str:
    """Return the exact issued-manual statement for one current schema."""

    if type(project_schema) is not int or project_schema <= 0:
        raise AssertionError("current project schema must be a positive integer")
    return f"Current projects use schema version {project_schema}"


def validate_current_manual_schema(
    flat_text: object,
    *,
    project_schema: int,
) -> None:
    """Require the current schema and reject other visible schema identities."""

    if not isinstance(flat_text, str):
        raise AssertionError("manual current schema identity must be text")
    schema_wording = current_schema_wording(project_schema)
    if schema_wording not in flat_text:
        raise AssertionError(
            "expected manual content is missing: " + schema_wording
        )
    if CURRENT_PROJECT_SAVE_WORDING not in flat_text:
        raise AssertionError(
            "expected manual content is missing: "
            + CURRENT_PROJECT_SAVE_WORDING
        )

    visible_schema_versions = {
        match.group("version").rstrip(".")
        for match in _SCHEMA_REFERENCE.finditer(flat_text)
    }
    noncurrent_versions = sorted(
        version
        for version in visible_schema_versions
        if version != str(project_schema)
    )
    if noncurrent_versions:
        raise AssertionError(
            "the manual contains non-current schema references: "
            + ", ".join(noncurrent_versions)
        )
