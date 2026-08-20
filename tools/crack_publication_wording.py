"""Dormant QA detector for retired ordinary crack-limit publication language."""

from __future__ import annotations

import re


_CRACK_LIMIT_FIELD = (
    r"(?:criteri(?:on|a)|"
    r"crack(?:[-\s]+widths?)?[-\s]+criteri(?:on|a)|"
    r"permitted(?:[-\s]+crack)?[-\s]+widths?|"
    r"crack[-\s]+widths?)"
)

_RETAINED_RESULT_SUFFIX = (
    r"(?![-\s]+(?:result|evidence|branch|calculation|output)\b)"
)


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
        "with-or-if-no-crack-limit-field-language",
        re.compile(
            rf"\b(?:with|if)\s+no\s+{_CRACK_LIMIT_FIELD}\b"
            rf"{_RETAINED_RESULT_SUFFIX}",
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
