from __future__ import annotations

import inspect
import math

import numpy as np
import pytest

from app.crack_criterion_value import normalise_ordinary_crack_criterion_mm


class _FloatTypeError(float):
    def __float__(self) -> float:
        raise TypeError("hostile conversion")


class _FloatValueError(float):
    def __float__(self) -> float:
        raise ValueError("hostile conversion")


class _FloatOverflowError(float):
    def __float__(self) -> float:
        raise OverflowError("hostile conversion")


class _FloatConvertible:
    def __float__(self) -> float:
        return 0.20


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, 0.0),
        (-0.0, 0.0),
        (0.25, 0.25),
        (1.75, 1.75),
        (np.float32(0.20), 0.20),
        (np.float64(1.25), 1.25),
        (np.int64(2), 2.0),
    ],
)
def test_crack_criterion_value_normalizes_supported_scalars(
    value: object,
    expected: float,
) -> None:
    normalized = normalise_ordinary_crack_criterion_mm(value)

    assert type(normalized) is float
    assert normalized == pytest.approx(expected)
    if expected == 0.0:
        assert math.copysign(1.0, normalized) == 1.0


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        np.bool_(True),
        np.bool_(False),
        "0.20",
        b"0.20",
        bytearray(b"0.20"),
        -0.01,
        math.nan,
        math.inf,
        -math.inf,
        [],
        {},
        complex(0.20, 0.0),
        np.complex64(0.20 + 0.0j),
        np.complex128(0.20 + 0.0j),
        np.array(0.20),
        np.array([0.20]),
        _FloatConvertible(),
        _FloatTypeError(0.20),
        _FloatValueError(0.20),
        _FloatOverflowError(0.20),
        pytest.param(10**10000, id="overflowing-int"),
    ],
)
def test_crack_criterion_value_rejects_malformed_or_unsafe_scalars(
    value: object,
) -> None:
    assert normalise_ordinary_crack_criterion_mm(value) is None


def test_crack_criterion_value_does_not_mutate_mutable_rejections() -> None:
    values: list[object] = [[0.20], {"value": 0.20}, bytearray(b"0.20")]
    snapshots = [[0.20], {"value": 0.20}, bytearray(b"0.20")]

    for value in values:
        assert normalise_ordinary_crack_criterion_mm(value) is None

    assert values == snapshots

    array = np.array([0.20])
    array_snapshot = array.copy()
    assert normalise_ordinary_crack_criterion_mm(array) is None
    np.testing.assert_array_equal(array, array_snapshot)


def test_crack_criterion_value_has_one_required_object_parameter() -> None:
    parameters = tuple(
        inspect.signature(normalise_ordinary_crack_criterion_mm).parameters.values()
    )

    assert len(parameters) == 1
    assert parameters[0].name == "value"
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters[0].default is inspect.Parameter.empty
