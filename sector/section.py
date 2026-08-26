"""Cross-section model: a polygonal concrete outline plus reinforcement bars.

The geometry is intentionally minimal and unit-agnostic in storage, but Sector
works in SI: coordinates in metres and bar areas in square metres. Helpers are
provided to build a section from the units engineers usually have to hand
(coordinates in metres, bar areas in mm^2).

A section's concrete is one or more *rings*. The first ring is the outer
boundary; any further rings are holes (voids). Orientation in storage is not
significant -- the integration code orients each ring as needed (outer
counter-clockwise, holes clockwise) so that signed area integrals net the holes
out of the solid automatically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from .geometry import (
    TopologyValidation,
    orient,
    ring_without_terminal_closure,
    signed_area,
    validate_section_topology,
)

MM2_TO_M2 = 1.0e-6


def finite_action(value: object, label: str) -> float:
    """Return one finite solver action or reject it before analysis starts."""

    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


@dataclass(frozen=True)
class Bar:
    """A reinforcement bar treated as a point area.

    Attributes
    ----------
    x, y:
        Bar centroid coordinates, in metres.
    area:
        Cross-sectional area, in square metres.
    """

    x: float
    y: float
    area: float


@dataclass
class Section:
    """A reinforced-concrete cross-section.

    Parameters
    ----------
    concrete:
        A list of rings, each an ``(N, 2)`` array of ``(x, y)`` vertices in
        metres. ``concrete[0]`` is the outer boundary; ``concrete[1:]`` are
        holes. Vertices are stored exactly as given (input order is preserved
        so output can refer to "point n"); orientation is normalised only when
        integrating.
    bars:
        The mild reinforcement bars.
    tendons:
        The prestressing tendons (treated as point areas, like bars). Used by
        the plastic analysis with a prestress material; ignored by the elastic
        analysis (where a tendon is modelled as an ordinary bar).
    """

    concrete: list[np.ndarray]
    bars: list[Bar] = field(default_factory=list)
    tendons: list[Bar] = field(default_factory=list)

    def __post_init__(self) -> None:
        rings = list(self.concrete)
        if not rings:
            raise ValueError("a section needs at least one concrete ring")
        validate_section_topology(rings[0], rings[1:]).require_valid()
        self.concrete = [np.array(r, dtype=float, copy=True) for r in rings]
        self.require_valid_reinforcement()

    # -- construction helpers ------------------------------------------------

    @classmethod
    def from_polygon(
        cls,
        corners: Sequence[Sequence[float]],
        bars_xy_area_mm2: Sequence[Sequence[float]] = (),
        holes: Sequence[Sequence[Sequence[float]]] = (),
        tendons_xy_area_mm2: Sequence[Sequence[float]] = (),
    ) -> "Section":
        """Build a section from a single outer outline and optional holes.

        ``corners`` and ``holes`` are vertex lists in metres (any winding).
        ``bars_xy_area_mm2`` and ``tendons_xy_area_mm2`` are sequences of
        ``(x, y, area_mm2)`` with the area in mm^2 (the usual engineering unit),
        converted to m^2 on the way in.
        """
        rings = [corners, *holes]
        bars = [Bar(float(x), float(y), float(a) * MM2_TO_M2) for x, y, a in bars_xy_area_mm2]
        tendons = [Bar(float(x), float(y), float(a) * MM2_TO_M2)
                   for x, y, a in tendons_xy_area_mm2]
        return cls(rings, bars, tendons)

    # -- derived geometry ----------------------------------------------------

    def validate_geometry(self) -> TopologyValidation:
        """Run Sector's canonical polygon-topology gate for this section."""
        try:
            rings = list(self.concrete)
        except TypeError:
            rings = []
        outer = rings[0] if rings else np.empty((0, 2), dtype=float)
        return validate_section_topology(outer, rings[1:])

    def require_valid_geometry(self) -> None:
        """Raise before analysis if the stored rings no longer form valid concrete.

        Validation also runs at construction. Solver entry points call this method
        defensively because ``concrete`` is a public mutable list
        and a caller can replace a ring after creating the section.
        """
        self.validate_geometry().require_valid()

    @staticmethod
    def _require_valid_elements(elements: Sequence[Bar], label: str) -> None:
        try:
            retained = tuple(elements)
        except TypeError as exc:
            raise ValueError(f"{label} reinforcement must be a sequence") from exc
        for index, element in enumerate(retained, start=1):
            try:
                x = float(element.x)
                y = float(element.y)
                area = float(element.area)
            except (AttributeError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    f"{label} {index} must have finite coordinates and a positive area"
                ) from exc
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError(f"{label} {index} coordinates must be finite")
            if not math.isfinite(area) or area <= 0.0:
                raise ValueError(f"{label} {index} area must be positive and finite")

    def require_valid_reinforcement(self) -> None:
        """Reject invalid bar/tendon geometry before a solver can consume it."""

        self._require_valid_elements(self.bars, "bar")
        self._require_valid_elements(self.tendons, "tendon")

    def require_valid_analysis_inputs(self) -> None:
        """Defensively recheck all mutable section data at solver entry."""

        self.require_valid_geometry()
        self.require_valid_reinforcement()

    def integration_rings(self) -> list[np.ndarray]:
        """Rings oriented for signed integration: outer CCW, holes CW.

        Summing signed area integrals over these rings yields the solid minus
        the holes.
        """
        self.require_valid_geometry()
        out = [
            orient(ring_without_terminal_closure(self.concrete[0]), ccw=True)
        ]
        out += [
            orient(ring_without_terminal_closure(r), ccw=False)
            for r in self.concrete[1:]
        ]
        return out

    def concrete_vertices(self) -> np.ndarray:
        """All concrete vertices in input order, stacked ``(M, 2)``.

        The row index (0-based) is the natural "point" identifier reported with
        the maximum concrete stress.
        """
        return np.vstack(self.concrete) if self.concrete else np.empty((0, 2))

    @staticmethod
    def _xya(bars: list[Bar]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if not bars:
            return (np.empty(0), np.empty(0), np.empty(0))
        x = np.array([b.x for b in bars], dtype=float)
        y = np.array([b.y for b in bars], dtype=float)
        a = np.array([b.area for b in bars], dtype=float)
        return x, y, a

    def bar_arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return mild-bar ``x``, ``y`` and ``area`` as three parallel arrays."""
        return self._xya(self.bars)

    def tendon_arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return tendon ``x``, ``y`` and ``area`` as three parallel arrays."""
        return self._xya(self.tendons)

    @property
    def gross_area(self) -> float:
        """Solid concrete area (outer minus holes), always positive."""
        total = abs(signed_area(self.concrete[0]))
        for r in self.concrete[1:]:
            total -= abs(signed_area(r))
        return total
