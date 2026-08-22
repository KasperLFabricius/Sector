"""Focused contracts for immutable report presentation profiles."""

from __future__ import annotations

import ast
import pathlib
from dataclasses import FrozenInstanceError, fields, replace

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

from app import report_profiles as profiles


def test_profile_keys_labels_order_and_default_are_exact():
    assert profiles.REPORT_PROFILE_KEYS == ("Brief", "Standard", "Audit")
    assert tuple(profiles.REPORT_PROFILES) == profiles.REPORT_PROFILE_KEYS
    assert tuple(
        (profile.key, profile.label)
        for profile in profiles.REPORT_PROFILES.values()
    ) == (
        ("Brief", "Brief"),
        ("Standard", "Standard"),
        ("Audit", "Audit"),
    )
    assert profiles.DEFAULT_PROFILE is profiles.STANDARD_PROFILE
    assert profiles.resolve_profile() is profiles.STANDARD_PROFILE


def test_profile_objects_and_registry_are_immutable_slots_and_hashable():
    policy = profiles.BRIEF_PROFILE
    with pytest.raises(FrozenInstanceError):
        policy.label = "Audit"  # type: ignore[misc]
    with pytest.raises(TypeError):
        profiles.REPORT_PROFILES["Brief"] = profiles.AUDIT_PROFILE  # type: ignore[index]

    assert not hasattr(policy, "__dict__")
    assert len(set(profiles.REPORT_PROFILES.values())) == 3
    assert replace(policy) == policy


def test_profile_depth_and_page_controls_match_the_frozen_policy():
    brief = profiles.BRIEF_PROFILE
    standard = profiles.STANDARD_PROFILE
    audit = profiles.AUDIT_PROFILE

    assert (
        brief.input_scope,
        brief.non_governing_scope,
        brief.equation_scope,
        brief.substitution_scope,
        brief.provenance_scope,
        brief.glossary_scope,
    ) == (
        "effective",
        "governing-only",
        "interpretive",
        "none",
        "revision",
        "short",
    )
    assert not brief.include_qa_appendix
    assert brief.hard_page_limit is None
    assert brief.target_page_limit is None
    assert not brief.target_exception_requires_reason
    assert not brief.target_exception_requires_visual_approval
    assert brief.sparse_page_body_coverage_threshold is None

    assert (
        standard.input_scope,
        standard.non_governing_scope,
        standard.equation_scope,
        standard.substitution_scope,
        standard.provenance_scope,
        standard.glossary_scope,
    ) == ("used", "complete", "used", "governing", "key", "used")
    assert not standard.include_qa_appendix
    assert standard.hard_page_limit is None
    assert standard.target_page_limit == 30
    assert standard.target_exception_requires_reason
    assert standard.target_exception_requires_visual_approval

    assert (
        audit.input_scope,
        audit.non_governing_scope,
        audit.equation_scope,
        audit.substitution_scope,
        audit.provenance_scope,
        audit.glossary_scope,
    ) == (
        "canonical",
        "complete",
        "used-and-theory",
        "every-retained",
        "complete",
        "complete",
    )
    assert audit.include_qa_appendix
    assert audit.hard_page_limit is None
    assert audit.target_page_limit is None
    assert audit.sparse_page_body_coverage_threshold == pytest.approx(0.35)


def test_profiles_describe_omissions_and_audit_disclaims_certification():
    assert all(profile.description for profile in profiles.REPORT_PROFILES.values())
    assert all(profile.omitted_detail for profile in profiles.REPORT_PROFILES.values())
    assert "does not mean approved, compliant or certified" in (
        profiles.AUDIT_PROFILE.description
    )
    assert "complete effective inputs" in profiles.BRIEF_PROFILE.description
    assert "worked result chain" not in profiles.BRIEF_PROFILE.description


def test_figures_remain_outside_the_profile_policy():
    field_names = {field.name for field in fields(profiles.ReportProfilePolicy)}
    assert not any("figure" in name for name in field_names)


@pytest.mark.parametrize(
    ("value", "qa_appendix", "expected"),
    (
        (None, None, profiles.STANDARD_PROFILE),
        ("Brief", None, profiles.BRIEF_PROFILE),
        ("Standard", None, profiles.STANDARD_PROFILE),
        ("Audit", None, profiles.AUDIT_PROFILE),
        (None, False, profiles.STANDARD_PROFILE),
        (None, True, profiles.AUDIT_PROFILE),
        ("Standard", False, profiles.STANDARD_PROFILE),
        ("Audit", True, profiles.AUDIT_PROFILE),
    ),
)
def test_resolve_profile_accepts_only_exact_compatible_selections(
    value,
    qa_appendix,
    expected,
):
    assert profiles.resolve_profile(value, qa_appendix) is expected


@pytest.mark.parametrize(
    ("value", "qa_appendix"),
    (
        ("Brief", False),
        ("Brief", True),
        ("Standard", True),
        ("Audit", False),
    ),
)
def test_resolve_profile_rejects_conflicting_new_and_legacy_selections(
    value,
    qa_appendix,
):
    with pytest.raises(ValueError, match="conflicts"):
        profiles.resolve_profile(value, qa_appendix)


@pytest.mark.parametrize("value", ("brief", "STANDARD", "Audit ", "", "Default report"))
def test_resolve_profile_rejects_unknown_or_inexact_strings(value):
    with pytest.raises(ValueError, match="unknown report profile"):
        profiles.resolve_profile(value)


@pytest.mark.parametrize("value", (0, False, object(), profiles.BRIEF_PROFILE))
def test_resolve_profile_rejects_non_string_profile_values(value):
    with pytest.raises(TypeError, match="string or None"):
        profiles.resolve_profile(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("qa_appendix", (0, 1, "yes", object()))
def test_resolve_profile_rejects_non_boolean_legacy_values(qa_appendix):
    with pytest.raises(TypeError, match="bool or None"):
        profiles.resolve_profile(qa_appendix=qa_appendix)  # type: ignore[arg-type]


def test_policy_module_is_stdlib_only_and_lazy_safe():
    tree = ast.parse((ROOT / "app" / "report_profiles.py").read_text("utf-8"))
    imports = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module != "__future__"
    )
    assert imports == {"collections", "dataclasses", "types", "typing"}
