"""Structured publication state for ordinary crack-width criteria."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from app.crack_criterion_value import normalise_ordinary_crack_criterion_mm


LONG_TERM_CRACK_LIMIT_KEY = "sls_long_term_permitted_crack_width_mm"
SHORT_TERM_CRACK_LIMIT_KEY = "sls_short_term_permitted_crack_width_mm"


@dataclass(frozen=True, slots=True)
class OrdinaryCrackCriterionPublication:
    """One persisted duration-specific criterion and its application state."""

    duration: Literal["long_term", "short_term"]
    value_mm: float
    calculation_requested: bool
    comparison_enabled: bool


def ordinary_crack_criteria_publication(
    inp: object,
    *,
    calculation_requested: bool,
) -> tuple[OrdinaryCrackCriterionPublication, OrdinaryCrackCriterionPublication] | None:
    """Return both criteria, whether or not calculation was requested.

    A comparison is enabled only for a requested calculation whose matching
    duration criterion is positive. Exact zero therefore stays visible as a
    user-owned value without becoming an acceptance limit.
    """

    if not isinstance(inp, Mapping) or type(calculation_requested) is not bool:
        return None

    long_term = normalise_ordinary_crack_criterion_mm(
        inp.get(LONG_TERM_CRACK_LIMIT_KEY)
    )
    short_term = normalise_ordinary_crack_criterion_mm(
        inp.get(SHORT_TERM_CRACK_LIMIT_KEY)
    )
    if long_term is None or short_term is None:
        return None

    return (
        OrdinaryCrackCriterionPublication(
            duration="long_term",
            value_mm=long_term,
            calculation_requested=calculation_requested,
            comparison_enabled=calculation_requested and long_term > 0.0,
        ),
        OrdinaryCrackCriterionPublication(
            duration="short_term",
            value_mm=short_term,
            calculation_requested=calculation_requested,
            comparison_enabled=calculation_requested and short_term > 0.0,
        ),
    )
