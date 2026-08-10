"""Pure first-generation Danish heightened crack-control calculation.

The calculation in this module is intentionally narrow.  It evaluates only
the user-selected DS/EN 1992-1-1 DK NA:2024 Formula 7.100 NA route and makes
no inference about whether that supplementary provision applies to a member.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from numbers import Real

from sector.design_standards import (
    Capability,
    DesignBasisKey,
    capability_binding,
    parse_design_basis_key,
)


class CrackSystem(StrEnum):
    """Exact crack-system choices defined by Formula 7.100 NA."""

    FINE = "fine"
    COARSE = "coarse"


class ReinforcementSurface(StrEnum):
    """Exact reinforcement-surface choices used by Formula 7.100 NA."""

    RIBBED = "ribbed"
    SMOOTH = "smooth"


class HeightenedCrackControlStatus(StrEnum):
    """Bounded area-comparison outcomes; these are not compliance claims."""

    PROVIDED_AREA_AT_LEAST_CALCULATED_REQUIREMENT = (
        "PROVIDED AREA AT LEAST CALCULATED REQUIREMENT"
    )
    PROVIDED_AREA_BELOW_CALCULATED_REQUIREMENT = (
        "PROVIDED AREA BELOW CALCULATED REQUIREMENT"
    )


@dataclass(frozen=True, slots=True)
class HeightenedCrackControlResult:
    """Complete retained operands and result for one Formula 7.100 NA check."""

    basis_key: DesignBasisKey
    crack_system: CrackSystem
    reinforcement_surface: ReinforcementSurface
    bar_diameter_mm: float
    effective_tensile_strength_mpa: float
    reinforcement_modulus_mpa: float
    permitted_crack_width_mm: float
    effective_tension_area_mm2: float
    provided_reinforcement_area_mm2: float
    source: str
    disclosure: str
    formula_identity: str
    crack_system_factor: float
    reinforcement_surface_multiplier: float
    base_reinforcement_ratio: float
    required_reinforcement_ratio: float
    required_reinforcement_area_mm2: float
    comparison_ratio: float
    status: HeightenedCrackControlStatus


_FORMULA_IDENTITY = "Formula 7.100 NA"
_CRACK_SYSTEM_FACTORS = {
    CrackSystem.FINE: 1.0,
    CrackSystem.COARSE: 2.0,
}
_SURFACE_MULTIPLIERS = {
    ReinforcementSurface.RIBBED: 1.0,
    ReinforcementSurface.SMOOTH: math.sqrt(2.0),
}


def _exact_crack_system(value: object) -> CrackSystem:
    if isinstance(value, CrackSystem):
        return value
    if isinstance(value, str):
        try:
            return CrackSystem(value)
        except ValueError:
            pass
    raise ValueError("crack_system must be exactly 'fine' or 'coarse'")


def _exact_reinforcement_surface(value: object) -> ReinforcementSurface:
    if isinstance(value, ReinforcementSurface):
        return value
    if isinstance(value, str):
        try:
            return ReinforcementSurface(value)
        except ValueError:
            pass
    raise ValueError("reinforcement_surface must be exactly 'ribbed' or 'smooth'")


def _positive_finite(value: object, label: str) -> float:
    value_type = type(value)
    boolean_scalar = isinstance(value, bool) or (
        value_type.__module__.partition(".")[0] in {"numpy", "pandas"}
        and value_type.__name__.lower().rstrip("_") in {"bool", "boolean"}
    )
    if (
        boolean_scalar
        or not isinstance(value, Real)
    ):
        raise ValueError(f"{label} must be a positive finite real number")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{label} must be a positive finite real number")
    return number


def _positive_finite_result(value: float, label: str) -> float:
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{label} must be a positive finite calculated result")
    return value


def calculate_heightened_crack_control(
    *,
    basis: object,
    crack_system: object,
    reinforcement_surface: object,
    bar_diameter_mm: object,
    effective_tensile_strength_mpa: object,
    reinforcement_modulus_mpa: object,
    permitted_crack_width_mm: object,
    effective_tension_area_mm2: object,
    provided_reinforcement_area_mm2: object,
) -> HeightenedCrackControlResult:
    """Evaluate the explicitly selected DK NA:2024 Formula 7.100 NA check.

    The base ratio is ``sqrt(phi*fct_eff/(4*E_sk*k*w_k))``.  ``k`` is one for
    the fine crack system and two for the coarse system.  Smooth reinforcement
    multiplies that complete base ratio by ``sqrt(2)``; ribbed reinforcement
    uses a multiplier of one.
    """

    basis_key = parse_design_basis_key(basis)
    if basis_key is not DesignBasisKey.FIRST_GEN_DK_NA_2024:
        raise ValueError(
            "Formula 7.100 NA is implemented only for "
            f"{DesignBasisKey.FIRST_GEN_DK_NA_2024.value}"
        )
    binding = capability_binding(
        basis_key,
        Capability.HEIGHTENED_CRACK_CONTROL,
    )
    system = _exact_crack_system(crack_system)
    surface = _exact_reinforcement_surface(reinforcement_surface)
    diameter = _positive_finite(bar_diameter_mm, "bar diameter phi")
    tensile_strength = _positive_finite(
        effective_tensile_strength_mpa,
        "effective tensile strength fct_eff",
    )
    modulus = _positive_finite(
        reinforcement_modulus_mpa,
        "reinforcement modulus E_sk",
    )
    permitted_width = _positive_finite(
        permitted_crack_width_mm,
        "permitted crack width w_k",
    )
    effective_area = _positive_finite(
        effective_tension_area_mm2,
        "effective tension area Ac_eff",
    )
    provided_area = _positive_finite(
        provided_reinforcement_area_mm2,
        "provided reinforcement area As_provided",
    )

    factor = _CRACK_SYSTEM_FACTORS[system]
    multiplier = _SURFACE_MULTIPLIERS[surface]
    base_ratio = _positive_finite_result(
        math.sqrt(
            diameter * tensile_strength / (4.0 * modulus * factor * permitted_width)
        ),
        "base reinforcement ratio",
    )
    required_ratio = _positive_finite_result(
        multiplier * base_ratio,
        "required reinforcement ratio",
    )
    required_area = _positive_finite_result(
        required_ratio * effective_area,
        "required reinforcement area",
    )
    comparison_ratio = _positive_finite_result(
        required_area / provided_area,
        "required-to-provided area ratio",
    )
    if provided_area >= required_area:
        status = (
            HeightenedCrackControlStatus.PROVIDED_AREA_AT_LEAST_CALCULATED_REQUIREMENT
        )
    else:
        status = HeightenedCrackControlStatus.PROVIDED_AREA_BELOW_CALCULATED_REQUIREMENT

    return HeightenedCrackControlResult(
        basis_key=basis_key,
        crack_system=system,
        reinforcement_surface=surface,
        bar_diameter_mm=diameter,
        effective_tensile_strength_mpa=tensile_strength,
        reinforcement_modulus_mpa=modulus,
        permitted_crack_width_mm=permitted_width,
        effective_tension_area_mm2=effective_area,
        provided_reinforcement_area_mm2=provided_area,
        source=binding.source,
        disclosure=binding.disclosure,
        formula_identity=_FORMULA_IDENTITY,
        crack_system_factor=factor,
        reinforcement_surface_multiplier=multiplier,
        base_reinforcement_ratio=base_ratio,
        required_reinforcement_ratio=required_ratio,
        required_reinforcement_area_mm2=required_area,
        comparison_ratio=comparison_ratio,
        status=status,
    )
