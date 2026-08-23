"""Fail-closed scope guard for visible Sector end-user manual text."""

from __future__ import annotations

import re


FORBIDDEN_ADMIN_PHRASES = (
    "governing repository contract",
    "docs/product_identity.md",
    "current schema",
    "schema version",
    "matching Sector release",
    "official Sector source ZIP",
    "source ZIP",
    "release channel",
    "BUILD_SECTOR_PORTABLE.bat",
    "README-PORTABLE.txt",
    "Sector.exe",
    "64-bit CPython",
    "SmartScreen",
    "SHA-256",
    "checksum",
    "source revision",
    "canonical receipt",
    "portable Windows build",
    "verified unsigned portable release",
    "recorded content reason",
    "visual approval",
    "Page policy",
)

_FORBIDDEN_PATTERNS = (
    re.compile(r"\b(?:hard limit|target)\s+\d+\s+pages?\b", re.IGNORECASE),
    re.compile(
        r"\b(?:former|previous|legacy|retired|released)\s+Sector"
        r"(?:\s+(?:version|release))?\s+v?\d",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:former|previous|legacy|retired)\s+"
        r"(?:Sector\s+)?(?:version|release|schema|behaviou?r)\b",
        re.IGNORECASE,
    ),
)


def validate_end_user_manual_scope(visible_text: object) -> None:
    """Reject development and former-version administration in visible text."""

    if type(visible_text) is not str:
        raise AssertionError("manual end-user scope content must be text")

    flat_text = " ".join(visible_text.split())
    folded = flat_text.casefold()
    findings = [
        phrase
        for phrase in FORBIDDEN_ADMIN_PHRASES
        if phrase.casefold() in folded
    ]
    findings.extend(
        match.group(0)
        for pattern in _FORBIDDEN_PATTERNS
        if (match := pattern.search(flat_text)) is not None
    )
    if findings:
        raise AssertionError(
            "manual contains end-user-scope excluded text: "
            + ", ".join(findings)
        )


__all__ = [
    "FORBIDDEN_ADMIN_PHRASES",
    "validate_end_user_manual_scope",
]
