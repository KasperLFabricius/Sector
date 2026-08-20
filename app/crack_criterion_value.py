"""Fail-closed normalization for user-owned ordinary crack-width criteria."""

from __future__ import annotations

import math
from numbers import Real

import numpy as np


def normalise_ordinary_crack_criterion_mm(value: object) -> float | None:
    """Return one finite non-negative criterion as a built-in ``float``.

    Boolean and text-like values are identities rather than numeric project
    scalars and are therefore rejected before conversion. Conversion failures
    are contained so a malformed retained value cannot escape this boundary.
    Signed zero is normalized to positive zero because both spell the same
    explicit no-comparison criterion.
    """

    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(normalized) or normalized < 0.0:
        return None
    return 0.0 if normalized == 0.0 else normalized
