from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError, fields
import inspect
from types import MappingProxyType

import numpy as np
import pytest

from app.crack_criterion_publication import (
    LONG_TERM_CRACK_LIMIT_KEY,
    SHORT_TERM_CRACK_LIMIT_KEY,
    OrdinaryCrackCriterionPublication,
    ordinary_crack_criteria_publication,
)


def _criteria(
    *,
    long_term: object = 0.30,
    short_term: object = 0.20,
) -> dict[str, object]:
    return {
        LONG_TERM_CRACK_LIMIT_KEY: long_term,
        SHORT_TERM_CRACK_LIMIT_KEY: short_term,
    }


def test_crack_publication_persisted_key_identities_are_exact() -> None:
    assert LONG_TERM_CRACK_LIMIT_KEY == "sls_long_term_permitted_crack_width_mm"
    assert SHORT_TERM_CRACK_LIMIT_KEY == "sls_short_term_permitted_crack_width_mm"


@pytest.mark.parametrize(
    ("requested", "long_term", "short_term", "expected_comparisons"),
    [
        (False, 0.0, 0.0, (False, False)),
        (False, 0.30, 0.0, (False, False)),
        (False, 0.0, 0.20, (False, False)),
        (False, 0.30, 0.20, (False, False)),
        (True, 0.0, 0.0, (False, False)),
        (True, 0.30, 0.0, (True, False)),
        (True, 0.0, 0.20, (False, True)),
        (True, 0.30, 0.20, (True, True)),
    ],
)
def test_crack_publication_retains_both_ordered_duration_criteria(
    requested: bool,
    long_term: float,
    short_term: float,
    expected_comparisons: tuple[bool, bool],
) -> None:
    inp = _criteria(
        long_term=np.float32(long_term),
        short_term=-0.0 if short_term == 0.0 else short_term,
    )
    before = copy.deepcopy(inp)

    publication = ordinary_crack_criteria_publication(
        inp,
        calculation_requested=requested,
    )

    assert publication is not None
    assert tuple(item.duration for item in publication) == ("long_term", "short_term")
    assert tuple(item.value_mm for item in publication) == pytest.approx(
        (long_term, short_term)
    )
    assert all(type(item.value_mm) is float for item in publication)
    assert tuple(item.calculation_requested for item in publication) == (
        requested,
        requested,
    )
    assert tuple(item.comparison_enabled for item in publication) == expected_comparisons
    assert inp == before


def test_crack_publication_accepts_read_only_mapping_without_mutation() -> None:
    source = _criteria()
    inp = MappingProxyType(source)

    publication = ordinary_crack_criteria_publication(
        inp,
        calculation_requested=False,
    )

    assert publication is not None
    assert source == _criteria()


@pytest.mark.parametrize(
    "requested",
    [None, 0, 1, "yes", b"yes", [], (), {}, np.bool_(True), np.bool_(False)],
)
def test_crack_publication_requires_exact_builtin_boolean_request(
    requested: object,
) -> None:
    inp = _criteria()
    before = copy.deepcopy(inp)

    assert (
        ordinary_crack_criteria_publication(  # type: ignore[arg-type]
            inp,
            calculation_requested=requested,
        )
        is None
    )
    assert inp == before


@pytest.mark.parametrize(
    "inp",
    [None, [], (), "criteria", b"criteria", 0, object(), np.array(0.20)],
)
def test_crack_publication_rejects_non_mapping_input(inp: object) -> None:
    assert (
        ordinary_crack_criteria_publication(inp, calculation_requested=False) is None
    )


@pytest.mark.parametrize(
    "missing_key",
    [LONG_TERM_CRACK_LIMIT_KEY, SHORT_TERM_CRACK_LIMIT_KEY],
)
def test_crack_publication_requires_both_duration_keys(missing_key: str) -> None:
    inp = _criteria()
    del inp[missing_key]
    before = copy.deepcopy(inp)

    assert (
        ordinary_crack_criteria_publication(inp, calculation_requested=True) is None
    )
    assert inp == before


@pytest.mark.parametrize("key", [LONG_TERM_CRACK_LIMIT_KEY, SHORT_TERM_CRACK_LIMIT_KEY])
@pytest.mark.parametrize("value", [None, True, np.bool_(False), -0.01, np.array(0.20)])
def test_crack_publication_rejects_invalid_duration_value_without_mutation(
    key: str,
    value: object,
) -> None:
    inp = _criteria()
    inp[key] = value
    before = copy.deepcopy(inp)

    assert (
        ordinary_crack_criteria_publication(inp, calculation_requested=True) is None
    )
    if isinstance(value, np.ndarray):
        assert isinstance(inp[key], np.ndarray)
        np.testing.assert_array_equal(inp[key], before[key])
        other_key = (
            SHORT_TERM_CRACK_LIMIT_KEY
            if key == LONG_TERM_CRACK_LIMIT_KEY
            else LONG_TERM_CRACK_LIMIT_KEY
        )
        assert inp[other_key] == before[other_key]
    else:
        assert inp == before


def test_crack_publication_result_shape_has_no_aggregate_verdict() -> None:
    assert tuple(field.name for field in fields(OrdinaryCrackCriterionPublication)) == (
        "duration",
        "value_mm",
        "calculation_requested",
        "comparison_enabled",
    )

    item = OrdinaryCrackCriterionPublication(
        duration="long_term",
        value_mm=0.30,
        calculation_requested=True,
        comparison_enabled=True,
    )
    with pytest.raises(FrozenInstanceError):
        item.value_mm = 0.20  # type: ignore[misc]


def test_crack_publication_has_required_keyword_only_request_parameter() -> None:
    parameters = tuple(
        inspect.signature(ordinary_crack_criteria_publication).parameters.values()
    )

    assert tuple(parameter.name for parameter in parameters) == (
        "inp",
        "calculation_requested",
    )
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters[0].default is inspect.Parameter.empty
    assert parameters[1].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters[1].default is inspect.Parameter.empty
