"""Sector -- reinforced-concrete cross-section analysis.

Sector computes the elastic stresses (cracked-section) or the plastic bending
capacity of a polygonal reinforced (and optionally prestressed) concrete
cross-section. The package is organised as a verifiable, headless computation
core with a separate presentation layer (Streamlit UI and PDF reports) layered
on top.

The stable public API is resolved on first use. Importing :mod:`sector` alone
therefore exposes release metadata without importing numerical libraries or
compiling calculation kernels that the caller may never use.
"""

from __future__ import annotations

from importlib import import_module

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
    "SpectrumBin",
    "ReinforcementFatigueProperties",
    "ConcreteFatigueProperties",
    "ConcreteFibreSearch",
    "FatigueSpectrumResult",
    "steel_fatigue_life",
    "concrete_fatigue_strength",
    "concrete_fatigue_life",
    "concrete_equivalent_utilisation",
    "locate_governing_concrete_fibre",
    "analyse_fatigue_spectrum",
    "analyse_grouped_spectra",
    "PlasticPoint",
    "plastic_capacity_at_angle",
    "solve_plastic",
    "InteractionPoint",
    "solve_interaction",
]

# Public re-exports are kept explicit so the stable API can be audited without
# importing every solver. PEP 562's module ``__getattr__`` resolves and caches
# the concrete object the first time it is requested.
_EXPORTS = {
    "AreaMoments": ("geometry", "AreaMoments"),
    "area_moments": ("geometry", "area_moments"),
    "area_moments_rings": ("geometry", "area_moments_rings"),
    "clip_halfplane": ("geometry", "clip_halfplane"),
    "orient": ("geometry", "orient"),
    "signed_area": ("geometry", "signed_area"),
    "Bar": ("section", "Bar"),
    "Section": ("section", "Section"),
    "Concrete": ("materials", "Concrete"),
    "MildSteel": ("materials", "MildSteel"),
    "Prestress": ("materials", "Prestress"),
    "ElasticResult": ("elastic", "ElasticResult"),
    "CombinedElasticResult": ("elastic", "CombinedElasticResult"),
    "solve_elastic": ("elastic", "solve_elastic"),
    "solve_elastic_combined": ("elastic", "solve_elastic_combined"),
    "SpectrumBin": ("fatigue", "SpectrumBin"),
    "ReinforcementFatigueProperties": (
        "fatigue",
        "ReinforcementFatigueProperties",
    ),
    "ConcreteFatigueProperties": ("fatigue", "ConcreteFatigueProperties"),
    "ConcreteFibreSearch": ("fatigue", "ConcreteFibreSearch"),
    "FatigueSpectrumResult": ("fatigue", "FatigueSpectrumResult"),
    "steel_fatigue_life": ("fatigue", "steel_fatigue_life"),
    "concrete_fatigue_strength": ("fatigue", "concrete_fatigue_strength"),
    "concrete_fatigue_life": ("fatigue", "concrete_fatigue_life"),
    "concrete_equivalent_utilisation": (
        "fatigue",
        "concrete_equivalent_utilisation",
    ),
    "locate_governing_concrete_fibre": (
        "fatigue",
        "locate_governing_concrete_fibre",
    ),
    "analyse_fatigue_spectrum": ("fatigue", "analyse_fatigue_spectrum"),
    "analyse_grouped_spectra": ("fatigue", "analyse_grouped_spectra"),
    "PlasticPoint": ("plastic", "PlasticPoint"),
    "plastic_capacity_at_angle": ("plastic", "plastic_capacity_at_angle"),
    "solve_plastic": ("plastic", "solve_plastic"),
    "InteractionPoint": ("plastic", "InteractionPoint"),
    "solve_interaction": ("plastic", "solve_interaction"),
}

# Submodules historically available through ``from sector import <module>``.
_MODULES = {
    name: name
    for name in (
        "bridge",
        "build_info",
        "capacity",
        "codes",
        "combined",
        "design_standards",
        "detailing",
        "elastic",
        "fatigue",
        "geometry",
        "kernels",
        "material_presets",
        "materials",
        "plastic",
        "section",
        "serviceability",
        "shear",
        "sls",
        "templates",
        "torsion",
    )
}


def __getattr__(name: str):
    """Resolve and cache one advertised public object or submodule."""

    target = _EXPORTS.get(name)
    if target is not None:
        module_name, attribute = target
        value = getattr(import_module(f".{module_name}", __name__), attribute)
    elif name in _MODULES:
        value = import_module(f".{_MODULES[name]}", __name__)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__():
    """Advertise lazy public names without resolving them."""

    return sorted(set(globals()) | set(__all__) | set(_MODULES))


# Single source of truth for release and ownership metadata shown by the app,
# reports, manuals, saved-project provenance and packaged-build manifest.
__version__ = "0.93"
__product_name__ = "Sector"
__description__ = "Structural-analysis and design calculation tool"
__author__ = "Kasper Lindskov Fabricius"
__licensee__ = "Sweco Danmark A/S"
__copyright__ = (
    "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."
)
