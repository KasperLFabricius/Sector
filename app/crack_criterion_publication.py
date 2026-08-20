"""Structured publication state for ordinary crack-width criteria."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Literal


LONG_TERM_CRACK_LIMIT_KEY = "sls_long_term_permitted_crack_width_mm"
SHORT_TERM_CRACK_LIMIT_KEY = "sls_short_term_permitted_crack_width_mm"


@dataclass(frozen=True, slots=True)
class OrdinaryCrackCriterionPublication:
    """One persisted duration-specific criterion and its application state."""

    duration: Literal["long_term", "short_term"]
    value_mm: float
    calculation_applied: bool
    comparison_enabled: bool


def _finite_nonnegative(value: object) -> float | None:
    if isinstance(value, (bool, str, bytes, bytearray)):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(normalized) or normalized < 0.0:
        return None
    return 0.0 if normalized == 0.0 else normalized


def ordinary_crack_criteria_publication(
    inp: object,
    *,
    calculation_requested: bool,
) -> tuple[OrdinaryCrackCriterionPublication, OrdinaryCrackCriterionPublication] | None:
    """Return both stored ordinary criteria, including when calculation is inactive.

    ``comparison_enabled`` is true only for a requested calculation with a
    positive matching limit. Exact zero therefore remains a published value
    without becoming an acceptance criterion.
    """

    if not isinstance(inp, Mapping) or type(calculation_requested) is not bool:
        return None

    long_term = _finite_nonnegative(inp.get(LONG_TERM_CRACK_LIMIT_KEY))
    short_term = _finite_nonnegative(inp.get(SHORT_TERM_CRACK_LIMIT_KEY))
    if long_term is None or short_term is None:
        return None

    return (
        OrdinaryCrackCriterionPublication(
            duration="long_term",
            value_mm=long_term,
            calculation_applied=calculation_requested,
            comparison_enabled=calculation_requested and long_term > 0.0,
        ),
        OrdinaryCrackCriterionPublication(
            duration="short_term",
            value_mm=short_term,
            calculation_applied=calculation_requested,
            comparison_enabled=calculation_requested and short_term > 0.0,
        ),
    )
