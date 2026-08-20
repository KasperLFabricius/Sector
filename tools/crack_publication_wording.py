"""Dormant QA detector for retired ordinary crack-limit publication language."""

from __future__ import annotations

import re


_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "shared-crack-limit-language",
        re.compile(
            r"(?:\bshared\b(?:[^\w,.!?;:]+\w+){0,5}[^\w,.!?;:]+\b"
            r"(?:crack(?:[^\w,.!?;:]+width)?|"
            r"permitted[^\w,.!?;:]+width|criteri(?:on|a))\b|"
            r"\b(?:crack(?:[^\w,.!?;:]+width)?|"
            r"permitted[^\w,.!?;:]+width|criteri(?:on|a))\b"
            r"(?:[^\w,.!?;:]+\w+){0,5}[^\w,.!?;:]+\bshared\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "blank-or-absent-criterion-language",
        re.compile(
            r"(?:\b(?:with|if)\s+no\s+criteri(?:on|a)\b|"
            r"\bwithout\s+(?:a\s+)?criteri(?:on|a)\b|"
            r"\bno\s+criteri(?:on|a)(?:\s+is)?\s+"
            r"(?:entered|supplied|provided|set)\b|"
            r"\b(?:blank|absent)\b"
            r"(?:[^\w.!?;:]+\w+){0,6}[^\w.!?;:]+\b"
            r"(?:crack(?:[^\w.!?;:]+width)?|"
            r"permitted[^\w.!?;:]+width|criteri(?:on|a))\b|"
            r"\b(?:crack(?:[^\w.!?;:]+width)?|"
            r"permitted[^\w.!?;:]+width|criteri(?:on|a))\b"
            r"(?:[^\w.!?;:]+\w+){0,6}[^\w.!?;:]+\b"
            r"(?:blank|absent)\b)",
            re.IGNORECASE,
        ),
    ),
)


def retired_crack_wording_rules(value: object) -> tuple[str, ...]:
    """Return stable rule IDs for retired language in one publication passage."""
    if not isinstance(value, str):
        return ("invalid-text",)
    normalized = " ".join(value.split())
    return tuple(name for name, pattern in _RULES if pattern.search(normalized))


__all__ = ["retired_crack_wording_rules"]
