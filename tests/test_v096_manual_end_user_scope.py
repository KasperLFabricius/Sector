"""Adversarial current end-user scope contracts for Sector v0.96."""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual

from tools.manual_end_user_scope import (
    FORBIDDEN_ADMIN_PHRASES,
    validate_end_user_manual_scope,
)


def _visible_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _visible_strings(item)


def test_current_manual_blocks_pass_the_end_user_scope_guard():
    visible_text = "\n".join(_visible_strings(manual.manual_blocks()))

    validate_end_user_manual_scope(visible_text)


@pytest.mark.parametrize("phrase", FORBIDDEN_ADMIN_PHRASES)
def test_end_user_scope_rejects_each_administration_phrase(phrase):
    with pytest.raises(
        AssertionError,
        match="end-user-scope excluded text",
    ):
        validate_end_user_manual_scope(
            "Current operating guidance. " + phrase + "."
        )


@pytest.mark.parametrize(
    "former_version_text",
    (
        "Former Sector version 0.94 used another route.",
        "Previous Sector release 0.94 behaved differently.",
        "Legacy schema behaviour is retained here.",
        "Retired Sector v0.93 instructions follow.",
        "Released Sector 0.92 projects used another format.",
    ),
)
def test_end_user_scope_rejects_former_version_narrative(former_version_text):
    with pytest.raises(
        AssertionError,
        match="end-user-scope excluded text",
    ):
        validate_end_user_manual_scope(former_version_text)


def test_end_user_scope_allows_current_operation_and_traceable_identity():
    validate_end_user_manual_scope(
        "Sector user manual. Version: 0.95. Source revision: abc123. "
        "Loading restores inputs and clears earlier results. The previous "
        "calculation is not reused; press Calculate before using results."
    )


@pytest.mark.parametrize("invalid", (None, 95, b"manual", [], {}))
def test_end_user_scope_rejects_nontext_content(invalid):
    with pytest.raises(AssertionError, match="must be text"):
        validate_end_user_manual_scope(invalid)


def test_manual_profile_table_contains_user_information_only():
    profile_table = next(
        block
        for block in manual.manual_blocks()
        if block[0] == "table" and block[1][0] == "Profile"
    )
    assert profile_table[1] == [
        "Profile",
        "Purpose",
        "Declared omitted detail",
    ]
    assert all(len(row) == 3 for row in profile_table[2])

    source = (ROOT / "app" / "manual.py").read_text(encoding="utf-8")
    assert "project_io" not in source
    assert "target_page_limit" not in source
    assert "hard_page_limit" not in source


def test_workflow_table_uses_three_readable_native_markup_columns():
    workflow_table = next(
        block
        for block in manual.manual_blocks()
        if block[0] == "table" and block[1][0] == "Workflow / outcome"
    )
    assert workflow_table[1] == [
        "Workflow / outcome",
        "Before and do",
        "Expected state / if blocked",
    ]
    assert all(len(row) == 3 for row in workflow_table[2])
    visible = " ".join(_visible_strings(workflow_table))
    assert "**Before:**" in visible
    assert "**Do:**" in visible
    assert "<b>" not in visible


def test_obsolete_current_schema_statement_guard_was_removed():
    assert not (ROOT / "tools" / "manual_current_schema_statements.py").exists()
    assert not (ROOT / "tests" / "test_manual_current_schema_statements.py").exists()
