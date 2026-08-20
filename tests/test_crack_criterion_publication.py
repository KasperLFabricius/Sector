from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from app.crack_criterion_publication import (
    LONG_TERM_CRACK_LIMIT_KEY,
    SHORT_TERM_CRACK_LIMIT_KEY,
    ordinary_crack_criteria_publication,
)


def _criteria(*, long_term: object = 0.30, short_term: object = 0.20) -> dict[str, object]:
    return {
        LONG_TERM_CRACK_LIMIT_KEY: long_term,
        SHORT_TERM_CRACK_LIMIT_KEY: short_term,
    }


def test_crack_criteria_publication_retains_both_duration_limits_when_inactive() -> None:
    inp = _criteria(long_term=0.30, short_term=0.0)
    before = copy.deepcopy(inp)

    publication = ordinary_crack_criteria_publication(
        inp,
        calculation_requested=False,
    )

    assert publication is not None
    assert tuple(item.duration for item in publication) == ("long_term", "short_term")
    assert tuple(item.value_mm for item in publication) == pytest.approx((0.30, 0.0))
    assert all(item.calculation_requested is False for item in publication)
    assert all(item.comparison_enabled is False for item in publication)
    assert inp == before


def test_crack_criteria_publication_enables_only_positive_active_comparisons() -> None:
    publication = ordinary_crack_criteria_publication(
        _criteria(long_term=-0.0, short_term=np.float32(0.25)),
        calculation_requested=True,
    )

    assert publication is not None
    long_term, short_term = publication
    assert type(long_term.value_mm) is float
    assert type(short_term.value_mm) is float
    assert math.copysign(1.0, long_term.value_mm) == 1.0
    assert long_term.calculation_requested is True
    assert long_term.comparison_enabled is False
    assert short_term.calculation_requested is True
    assert short_term.comparison_enabled is True


@pytest.mark.parametrize("missing_key", [LONG_TERM_CRACK_LIMIT_KEY, SHORT_TERM_CRACK_LIMIT_KEY])
def test_crack_criteria_publication_rejects_missing_duration(missing_key: str) -> None:
    inp = _criteria()
    del inp[missing_key]
    before = copy.deepcopy(inp)

    assert (
        ordinary_crack_criteria_publication(inp, calculation_requested=True) is None
    )
    assert inp == before


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        np.bool_(True),
        np.bool_(False),
        "0.30",
        b"0.30",
        -0.01,
        math.nan,
        math.inf,
        -math.inf,
    ],
)
@pytest.mark.parametrize("key", [LONG_TERM_CRACK_LIMIT_KEY, SHORT_TERM_CRACK_LIMIT_KEY])
def test_crack_criteria_publication_rejects_malformed_limits(
    key: str,
    value: object,
) -> None:
    inp = _criteria()
    inp[key] = value
    before = copy.deepcopy(inp)

    assert (
        ordinary_crack_criteria_publication(inp, calculation_requested=True) is None
    )
    assert inp == before


@pytest.mark.parametrize("requested", [None, 0, 1, "yes", [], {}])
def test_crack_criteria_publication_requires_exact_boolean_request(
    requested: object,
) -> None:
    assert (
        ordinary_crack_criteria_publication(  # type: ignore[arg-type]
            _criteria(),
            calculation_requested=requested,
        )
        is None
    )


@pytest.mark.parametrize("inp", [None, [], (), "criteria", 0])
def test_crack_criteria_publication_rejects_non_mapping_input(inp: object) -> None:
    assert (
        ordinary_crack_criteria_publication(inp, calculation_requested=False) is None
    )
