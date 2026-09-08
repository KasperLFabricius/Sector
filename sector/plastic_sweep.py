"""Bounded neutral-axis sweep validation without importing the solver."""

from __future__ import annotations

import math

from .section import finite_action

# The interactive product exposes increments down to one degree, while focused
# engineering references also use 0.1 degree resolution.  A 4,097-point ceiling
# retains those references (including one extra interval when strict represented
# gaps require it), but rejects hostile/unusable requests before allocating an
# angle tuple or entering the solver.
PLASTIC_SWEEP_MAX_POINTS = 4_097
_FULL_TURN_DEGREES = 360

class PlasticSweepResolutionError(ValueError):
    """A sweep cannot be represented safely at the requested resolution."""


class PlasticSweepSpanError(PlasticSweepResolutionError):
    """A sweep's finite endpoints have an unrepresentable separation."""


def plastic_sweep_is_full_turn(v_min: float, v_max: float) -> bool:
    """Return whether the represented endpoints are separated by exactly 360 deg.

    The comparison uses the exact rational values represented by both floats, so
    a partial endpoint immediately below a full turn is never absorbed by a
    tolerance intended for ordinary numerical calculations.
    """

    start = finite_action(v_min, "minimum neutral-axis angle")
    end = finite_action(v_max, "maximum neutral-axis angle")
    start_numerator, start_denominator = start.as_integer_ratio()
    end_numerator, end_denominator = end.as_integer_ratio()
    exact_span_numerator = (
        end_numerator * start_denominator
        - start_numerator * end_denominator
    )
    exact_span_denominator = end_denominator * start_denominator
    return exact_span_numerator == _FULL_TURN_DEGREES * exact_span_denominator


def plastic_sweep_angles(
    v_min: float,
    v_max: float,
    v_inc: float,
) -> tuple[float, ...]:
    """Return an inclusive neutral-axis sweep with ``v_inc`` as a maximum step.

    Both endpoints are retained.  When the requested maximum increment does not
    divide the span, the span is divided into the smallest whole number of equal
    intervals whose actual step does not exceed ``v_inc``.  A zero span therefore
    contains one angle.  Reversed bounds and non-positive increments are invalid.
    Requests above :data:`PLASTIC_SWEEP_MAX_POINTS`, or whose adjacent angles
    cannot be represented as distinct floats within the maximum step, fail before
    the tuple is allocated.
    """

    start = finite_action(v_min, "minimum neutral-axis angle")
    end = finite_action(v_max, "maximum neutral-axis angle")
    maximum_step = finite_action(v_inc, "neutral-axis angle increment")
    if end < start:
        raise ValueError(
            "maximum neutral-axis angle must be greater than or equal to the minimum"
        )
    if maximum_step <= 0.0:
        raise ValueError("neutral-axis angle increment must be positive")
    span = end - start
    if not math.isfinite(span):
        raise PlasticSweepSpanError(
            "neutral-axis angle span cannot be represented safely"
        )
    if span == 0.0:
        return (start,)

    ratio = span / maximum_step
    if not math.isfinite(ratio):
        raise PlasticSweepResolutionError(
            "neutral-axis angle increment is too small for the span"
        )
    intervals = max(1, math.ceil(ratio))
    if intervals + 1 > PLASTIC_SWEEP_MAX_POINTS:
        raise PlasticSweepResolutionError(
            "neutral-axis sweep requests too many angles; increase the maximum "
            "increment"
        )

    # Validate the represented angle sequence before allocating its tuple.  A
    # large coordinate offset can otherwise round adjacent requested angles to
    # the same float, followed by a terminal gap larger than ``maximum_step``.
    while True:
        actual_step = span / intervals
        previous = start
        gap_too_large = False
        for index in range(1, intervals + 1):
            current = end if index == intervals else start + index * actual_step
            if current <= previous:
                raise PlasticSweepResolutionError(
                    "neutral-axis sweep angles are not distinct at this numerical "
                    "scale; use a larger maximum increment or smaller angle values"
                )
            if current - previous > maximum_step:
                gap_too_large = True
                break
            previous = current
        if not gap_too_large:
            break
        intervals += 1
        if intervals + 1 > PLASTIC_SWEEP_MAX_POINTS:
            raise PlasticSweepResolutionError(
                "neutral-axis sweep requests too many angles; increase the maximum "
                "increment"
            )
    return tuple(
        start
        if index == 0
        else end
        if index == intervals
        else start + index * actual_step
        for index in range(intervals + 1)
    )


