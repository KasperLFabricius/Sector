"""Dormant current-schema statements for the issued user manual."""

from __future__ import annotations


CURRENT_PROJECT_SAVE_WORDING = (
    "Every downloaded project save uses the current schema"
)


def current_schema_wording(project_schema: int) -> str:
    """Return the exact issued-manual statement for one current schema."""

    if type(project_schema) is not int or project_schema <= 0:
        raise AssertionError("current project schema must be a positive integer")
    return f"Current projects use schema version {project_schema}"


def validate_current_manual_schema_statements(
    flat_text: object,
    *,
    project_schema: int,
) -> None:
    """Require both current-schema statements in visible manual text."""

    if type(flat_text) is not str:
        raise AssertionError("manual current schema statements must be text")
    required_statements = (
        current_schema_wording(project_schema),
        CURRENT_PROJECT_SAVE_WORDING,
    )
    for statement in required_statements:
        if statement not in flat_text:
            raise AssertionError(
                "expected manual content is missing: " + statement
            )
