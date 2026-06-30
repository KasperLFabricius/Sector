"""Unit test for the plastic radial-utilisation helper.

``_radial_util`` rates an applied (Mx, My) point against the M-M capacity
envelope: it is the applied radius over the envelope radius in the same
direction (1.0 = on the boundary, <1 inside, >1 outside).
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))


def _radial_util():
    import sector_app
    return sector_app._radial_util


def _circle(r, n=72):
    th = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    return r * np.cos(th), r * np.sin(th)


def test_radial_util_circular_envelope():
    f = _radial_util()
    mx, my = _circle(100.0)                       # capacity radius 100 in every direction
    assert f(mx, my, 50.0, 0.0) == pytest.approx(0.5)
    assert f(mx, my, 0.0, 80.0) == pytest.approx(0.8)
    assert f(mx, my, 60.0, 80.0) == pytest.approx(1.0)   # hypot 100 -> on the boundary
    assert f(mx, my, 0.0, 0.0) == 0.0                    # no applied moment -> 0
    assert f(mx, my, 150.0, 0.0) == pytest.approx(1.5)   # outside the envelope


def test_radial_util_uses_the_capacity_in_the_applied_direction():
    # A section stronger about x (envelope reaches 100 along Mx, 50 along My): the
    # same applied radius gives a different utilisation depending on direction.
    f = _radial_util()
    th = np.linspace(0.0, 2.0 * np.pi, 72, endpoint=False)
    mx, my = 100.0 * np.cos(th), 50.0 * np.sin(th)       # axis intercepts 100 / 50
    assert f(mx, my, 50.0, 0.0) == pytest.approx(0.5)    # along Mx: 50/100
    assert f(mx, my, 0.0, 25.0) == pytest.approx(0.5)    # along My: 25/50
    assert f(mx, my, 0.0, 50.0) == pytest.approx(1.0)    # My capacity, on boundary
