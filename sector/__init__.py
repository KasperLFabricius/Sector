"""Sector -- reinforced-concrete cross-section analysis.

Sector computes the elastic stresses (cracked-section) or the plastic bending
capacity of a polygonal reinforced (and optionally prestressed) concrete
cross-section. The package is organised as a verifiable, headless computation
core with a separate presentation layer (Streamlit UI and PDF reports) layered
on top.

This module re-exports the stable geometry kernels; further sub-modules
(materials, section model, elastic/plastic solvers) are added as the core
grows.
"""

from __future__ import annotations

from .geometry import (
    AreaMoments,
    area_moments,
    area_moments_rings,
    clip_halfplane,
    orient,
    signed_area,
)

__all__ = [
    "AreaMoments",
    "area_moments",
    "area_moments_rings",
    "clip_halfplane",
    "orient",
    "signed_area",
]

__version__ = "0.1.0"
