"""Dormant QA detector for retired ordinary crack-limit publication language."""

from __future__ import annotations

import re


_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "shared-crack-limit-language",
        re.compile(
            r"(?:\bshared\b(?:[^\w.!?;:]+\w+){0,5}[^\w.!?;:]+\b"
            r"(?:crack(?:[^\w.!?;:]+width)?|"
            r"permitted[^\w.!?;:]+width|criteri(?:on|a))\b|"
            r"\b(?:crack(?:[^\w.!?;:]+width)?|"
            r"permitted[^\w.!?;:]+width|criteri(?:on|a))\b"
            r"(?:[^\w.!?;:]+\w+){0,5}[^\w.!?;:]+\bshared\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "blank-or-absent-criterion-language",
        re.compile(
            r"(?:\bwith no criterion\b|\bwithout a criterion\b|"
            r"\bif no criterion\b|\bno criterion (?:is )?(?:entered|supplied)\b|"
            r"\bblank\b.{0,80}\bcriterion\b|"
            r"\bleave blank\b.{0,80}\b(?:crack|width|criterion)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "singular-optional-criterion-language",
        re.compile(
            r"(?:\b(?:one|an) optional\b.{0,80}\b(?:permitted width|criterion)\b|"
            r"\boptional user-specified\b.{0,40}\bcriterion\b)",
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
