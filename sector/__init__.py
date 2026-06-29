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

from .elastic import (
    CombinedElasticResult,
    ElasticResult,
    solve_elastic,
    solve_elastic_combined,
)
from .geometry import (
    AreaMoments,
    area_moments,
    area_moments_rings,
    clip_halfplane,
    orient,
    signed_area,
)
from .materials import Concrete, MildSteel, Prestress
from .plastic import PlasticPoint, plastic_capacity_at_angle, solve_plastic
from .section import Bar, Section

__all__ = [
    "AreaMoments",
    "area_moments",
    "area_moments_rings",
    "clip_halfplane",
    "orient",
    "signed_area",
    "Bar",
    "Section",
    "Concrete",
    "MildSteel",
    "Prestress",
    "ElasticResult",
    "CombinedElasticResult",
    "solve_elastic",
    "solve_elastic_combined",
    "PlasticPoint",
    "plastic_capacity_at_angle",
    "solve_plastic",
]

# The single source of truth for the Sector version (the app imports this as
# APP_VERSION). Semantic versioning: MINOR for a feature, PATCH for a fix, MAJOR
# once production-ready (pre-1.0 = internal, still evolving).
__version__ = "0.2.0"
