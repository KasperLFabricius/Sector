"""Dormant visible schema-reference check for the issued user manual."""

from __future__ import annotations

import re


_HSPACE = r"[\t \u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]"
_QUOTE_CHARS = r"\"'\u00ab\u00bb\u2018\u2019\u201c\u201d\u201e\u201f\u2039\u203a"
_QUOTE = rf"[{_QUOTE_CHARS}]"
_DASH_CHARS = r"\-\u2010\u2011\u2012\u2013\u2014"
_DASH = rf"[{_DASH_CHARS}]"
_SEPARATOR = rf"[:=#{_DASH_CHARS}]"
_REFERENCE_SUFFIX = (
    rf"[^\s,;:!?()\[\]{{}}<>"
    rf"{_QUOTE_CHARS}\u2026\u3002]*"
)
_SCHEMA_REFERENCE = re.compile(
    r"\bschema\b"
    rf"(?:{_HSPACE}+version)?"
    rf"{_QUOTE}?{_HSPACE}*"
    rf"(?:{_SEPARATOR}{_HSPACE}*)?"
    rf"{_QUOTE}?{_HSPACE}*"
    rf"(?:version{_HSPACE}*(?:{_SEPARATOR}{_HSPACE}*)?)?"
    rf"{_QUOTE}?{_HSPACE}*"
    rf"(?:{_SEPARATOR}{_HSPACE}*)?"
    rf"v?{_HSPACE}*"
    rf"(?P<version>\d{_REFERENCE_SUFFIX})",
    flags=re.IGNORECASE,
)
_NAMED_NONPROJECT_SCHEMA_PREFIX = re.compile(
    rf"\b(?:JSON|OpenAPI|XML|XSD)"
    rf"(?:{_HSPACE}+|{_HSPACE}*{_DASH}{_HSPACE}*)\Z",
    flags=re.IGNORECASE,
)


def validate_no_noncurrent_manual_schema_references(
    flat_text: object,
    *,
    project_schema: int,
) -> None:
    """Reject visible schema identities other than the supplied current one."""

    if type(flat_text) is not str:
        raise AssertionError("manual schema-reference content must be text")
    if type(project_schema) is not int or project_schema <= 0:
        raise AssertionError("current project schema must be a positive integer")

    visible_versions = {
        match.group("version").rstrip(".")
        for match in _SCHEMA_REFERENCE.finditer(flat_text)
        if not _NAMED_NONPROJECT_SCHEMA_PREFIX.search(
            flat_text[: match.start()]
        )
    }
    noncurrent_versions = sorted(
        version
        for version in visible_versions
        if version != str(project_schema)
    )
    if noncurrent_versions:
        raise AssertionError(
            "the manual contains non-current schema references: "
            + ", ".join(noncurrent_versions)
        )
