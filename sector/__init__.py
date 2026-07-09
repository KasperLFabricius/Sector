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
from .plastic import (
    InteractionPoint,
    PlasticPoint,
    plastic_capacity_at_angle,
    solve_interaction,
    solve_plastic,
)
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
    "InteractionPoint",
    "solve_interaction",
]

# The single source of truth for the Sector version (the app imports this as
# APP_VERSION). Pre-1.0 internal scheme: 0.XX, bumped by 0.01 per change while the
# tool is still evolving toward a production 1.0.
__version__ = "0.44"
