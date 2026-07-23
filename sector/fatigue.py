"""Headless fatigue verification for reinforced-concrete cross-sections.

The module evaluates grouped constant-amplitude spectra with the existing
cracked Elastic solver.  Each bin contains a non-cyclic long-term action and a
cyclic short-term increment.  Reinforcement stress ranges are therefore the
difference between the combined and long-term Elastic results.

Two explicit Eurocode methods are supported:

* reinforcing and prestressing steel use the two-slope S-N curves and linear
  Palmgren-Miner damage summation in EN 1992-1-1, including the edition-specific
  bond correction for sections combining mild reinforcement and bonded tendons;
* concrete compression uses the corrected EN 1992-2:2005 expression or the
  equivalent EN 1992-1-1:2023 Annex E expression, accumulated at each fixed
  concrete fibre.

All partial factors are complete caller inputs.  This module does not apply
control-class, construction-category, consequence-class or authority-specific
multipliers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import heapq
import math

import numpy as np

from .elastic import CombinedElasticResult, solve_elastic_combined
from .geometry import (
    clip_halfplane,
    points_inside_concrete,
    polygon_is_convex,
    signed_area,
)
from .section import Bar, Section


EC2_2005 = "2005"
EC2_2023 = "2023"
MILD = "mild"
PRESTRESS = "prestress"
DAMAGE_LIMIT = 1.0
_MPA_DIVISOR = 1000.0
_LOG10_FLOAT_MAX = math.log10(np.finfo(float).max)
_LOG10_FLOAT_TINY = math.log10(np.nextafter(0.0, 1.0))
_DEFAULT_FIBRE_SEARCH_DIVISIONS = 4
_DEFAULT_FIBRE_SEARCH_MAX_DEPTH = 26
_DEFAULT_FIBRE_SEARCH_MAX_BOXES = 200_000
_DEFAULT_FIBRE_SEARCH_REL_TOL = 1.0e-3
_DEFAULT_FIBRE_SEARCH_ABS_TOL = 1.0e-8


def _finite(value: float, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _positive(value: float, label: str) -> float:
    number = _finite(value, label)
    if number <= 0.0:
        raise ValueError(f"{label} must be greater than zero")
    return number


def _normalise_edition(value: str) -> str:
    text = str(value).strip()
    if "2023" in text:
        return EC2_2023
    if "2005" in text or "2004" in text:
        return EC2_2005
    raise ValueError("fatigue edition must identify EN 1992:2005 or EN 1992:2023")


def _pow10(log10_value: float) -> float:
    if math.isinf(log10_value):
        return math.inf if log10_value > 0.0 else 0.0
    if log10_value > _LOG10_FLOAT_MAX:
        return math.inf
    if log10_value < _LOG10_FLOAT_TINY:
        return 0.0
    return 10.0 ** log10_value


def _damage(applied_cycles: float, log10_cycles_to_failure: float) -> float:
    cycles = _positive(applied_cycles, "applied cycles")
    if math.isinf(log10_cycles_to_failure):
        return 0.0 if log10_cycles_to_failure > 0.0 else math.inf
    return _pow10(math.log10(cycles) - log10_cycles_to_failure)


def _unique_names(values, label: str) -> None:
    seen: dict[str, str] = {}
    for value in values:
        text = str(value).strip()
        folded = text.casefold()
        if not text:
            raise ValueError(f"{label} name is required")
        if folded in seen:
            raise ValueError(
                f"{label} name '{text}' duplicates '{seen[folded]}'"
            )
        seen[folded] = text


@dataclass(frozen=True)
class SpectrumBin:
    """One constant-amplitude bin, using Elastic's compression-positive ``P``."""

    name: str
    cycles: float
    p_long_kn: float = 0.0
    mx_long_knm: float = 0.0
    my_long_knm: float = 0.0
    p_short_kn: float = 0.0
    mx_short_knm: float = 0.0
    my_short_knm: float = 0.0
    description: str = ""

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("fatigue bin name is required")
        _positive(self.cycles, f"{self.name}: cycles")
        for field in (
            "p_long_kn",
            "mx_long_knm",
            "my_long_knm",
            "p_short_kn",
            "mx_short_knm",
            "my_short_knm",
        ):
            _finite(getattr(self, field), f"{self.name}: {field}")


@dataclass(frozen=True)
class ReinforcementFatigueProperties:
    """Resolved S-N and yield data for one solver bar or tendon."""

    element_id: str
    kind: str
    detail_id: str
    diameter_mm: float
    n_star: float
    k1: float
    k2: float
    delta_sigma_rsk_mpa: float
    fytk_mpa: float
    fyck_mpa: float | None = None
    bond_ratio_xi: float | None = None
    bond_equivalent_diameter_mm: float | None = None

    def __post_init__(self) -> None:
        if not str(self.element_id).strip():
            raise ValueError("reinforcement element ID is required")
        if str(self.kind).strip().lower() not in (MILD, PRESTRESS):
            raise ValueError(f"{self.element_id}: kind must be mild or prestress")
        if not str(self.detail_id).strip():
            raise ValueError(f"{self.element_id}: fatigue detail ID is required")
        for field in (
            "diameter_mm",
            "n_star",
            "k1",
            "k2",
            "delta_sigma_rsk_mpa",
            "fytk_mpa",
        ):
            _positive(getattr(self, field), f"{self.element_id}: {field}")
        if self.fyck_mpa is not None:
            _positive(self.fyck_mpa, f"{self.element_id}: fyck_mpa")
        if self.bond_ratio_xi is not None:
            _positive(
                self.bond_ratio_xi,
                f"{self.element_id}: bond_ratio_xi",
            )
        if self.bond_equivalent_diameter_mm is not None:
            _positive(
                self.bond_equivalent_diameter_mm,
                f"{self.element_id}: bond_equivalent_diameter_mm",
            )


@dataclass(frozen=True)
class ConcreteFatigueProperties:
    """Concrete parameters required by the selected explicit fatigue method."""

    edition: str
    fck_mpa: float
    gamma_c: float
    beta_cc_t0: float
    alpha_cc: float = 1.0
    k1: float = 0.85
    c: float = 14.0

    def __post_init__(self) -> None:
        _normalise_edition(self.edition)
        for field in (
            "fck_mpa",
            "gamma_c",
            "beta_cc_t0",
            "alpha_cc",
            "k1",
            "c",
        ):
            _positive(getattr(self, field), f"concrete {field}")


@dataclass(frozen=True)
class FatigueLife:
    """Cycles to failure, retained in logarithmic form for numerical stability."""

    cycles: float
    log10_cycles: float
    exponent: float


@dataclass(frozen=True)
class FatigueBinState:
    """Elastic response of one spectrum bin in report-ready units."""

    name: str
    description: str
    cycles: float
    converged: bool
    bar_stress_long_mpa: tuple[float, ...]
    bar_stress_total_mpa: tuple[float, ...]
    concrete_compression_long_mpa: tuple[float, ...]
    concrete_compression_total_mpa: tuple[float, ...]
    elastic_result: CombinedElasticResult | None
    bar_stress_fatigue_total_mpa: tuple[float, ...] = ()
    bond_method: str = "Perfect bond"
    design_action_factor: float = 1.0
    design_elastic_result: CombinedElasticResult | None = None
    bar_stress_design_total_mpa: tuple[float, ...] = ()
    bar_stress_fatigue_design_total_mpa: tuple[float, ...] = ()
    concrete_compression_design_total_mpa: tuple[float, ...] = ()


@dataclass(frozen=True)
class ReinforcementBinResult:
    bin_name: str
    cycles: float
    converged: bool
    stress_long_mpa: float
    stress_total_mpa: float
    stress_total_design_mpa: float
    stress_total_elastic_mpa: float
    stress_range_mpa: float
    stress_range_elastic_mpa: float
    bond_adjustment: float
    bond_method: str
    design_stress_range_mpa: float
    delta_sigma_rsk_mpa: float
    delta_sigma_rd_mpa: float
    sn_exponent: float
    cycles_to_failure: float
    log10_cycles_to_failure: float
    damage: float
    governing_stress_mpa: float
    yield_limit_mpa: float
    yield_utilisation: float


@dataclass(frozen=True)
class ReinforcementFatigueResult:
    element_id: str
    kind: str
    detail_id: str
    diameter_mm: float
    bins: tuple[ReinforcementBinResult, ...]
    damage: float
    damage_utilisation: float
    governing_damage_bin: str
    yield_utilisation: float
    governing_yield_bin: str
    utilisation: float
    converged: bool
    passed: bool


@dataclass(frozen=True)
class ConcreteBinResult:
    bin_name: str
    cycles: float
    converged: bool
    compression_long_mpa: float
    compression_total_mpa: float
    compression_min_design_mpa: float
    compression_max_design_mpa: float
    stress_ratio: float
    e_cd_min: float
    e_cd_max: float
    cycles_to_failure: float
    log10_cycles_to_failure: float
    damage: float
    stress_utilisation: float


@dataclass(frozen=True)
class ConcreteFibreFatigueResult:
    fibre_index: int
    x_m: float
    y_m: float
    bins: tuple[ConcreteBinResult, ...]
    fcd_fat_mpa: float
    damage: float
    damage_utilisation: float
    governing_damage_bin: str
    stress_utilisation: float
    governing_stress_bin: str
    utilisation: float
    converged: bool
    passed: bool


@dataclass(frozen=True)
class ConcreteFibreSearch:
    """Adaptive same-fibre search evidence for concrete fatigue damage."""

    x_m: float
    y_m: float
    damage: float
    upper_damage: float
    divisions: int
    boxes_evaluated: int
    points_evaluated: int
    absolute_gap: float
    relative_gap: float
    converged: bool

    @property
    def relative_change(self) -> float:
        """Compatibility alias for the superseded heuristic-search field."""

        return self.relative_gap


@dataclass(frozen=True)
class FatigueSpectrumResult:
    spectrum_name: str
    bins: tuple[FatigueBinState, ...]
    reinforcement: tuple[ReinforcementFatigueResult, ...]
    concrete: tuple[ConcreteFibreFatigueResult, ...]
    concrete_search: ConcreteFibreSearch | None
    fcd_fat_mpa: float | None
    governing_reinforcement_id: str | None
    governing_concrete_fibre: int | None
    utilisation: float
    converged: bool
    passed: bool


def steel_fatigue_life(
    stress_range_mpa: float,
    *,
    n_star: float,
    k1: float,
    k2: float,
    delta_sigma_rsk_mpa: float,
    gamma_s: float,
    gamma_ff: float,
) -> FatigueLife:
    """Return S-N life for one reinforcement stress range.

    The branch condition and life expression follow EN 1992-1-1:2023
    E.5.2.  The same two-slope curve is used by EN 1992-1-1:2004+A1:2014
    6.8.4 and Tables 6.3N/6.4N.
    """

    stress_range = _finite(stress_range_mpa, "stress range")
    if stress_range < 0.0:
        raise ValueError("stress range must be zero or greater")
    n_ref = _positive(n_star, "N*")
    slope_1 = _positive(k1, "k1")
    slope_2 = _positive(k2, "k2")
    reference = _positive(
        delta_sigma_rsk_mpa, "characteristic reference stress range"
    )
    material_factor = _positive(gamma_s, "gamma_s")
    action_factor = _positive(gamma_ff, "gamma_Ff")
    if stress_range == 0.0:
        return FatigueLife(math.inf, math.inf, 0.0)

    knee = reference / (material_factor * action_factor)
    exponent = slope_1 if stress_range >= knee else slope_2
    ratio = reference / (
        material_factor * action_factor * stress_range
    )
    log10_cycles = math.log10(n_ref) + exponent * math.log10(ratio)
    return FatigueLife(
        cycles=_pow10(log10_cycles),
        log10_cycles=log10_cycles,
        exponent=exponent,
    )


def concrete_fatigue_strength(
    properties: ConcreteFatigueProperties,
) -> float:
    """Return ``fcd,fat`` in MPa for the selected Eurocode edition."""

    edition = _normalise_edition(properties.edition)
    fck = float(properties.fck_mpa)
    gamma_c = float(properties.gamma_c)
    beta = float(properties.beta_cc_t0)
    if edition == EC2_2005:
        value = (
            float(properties.k1)
            * beta
            * float(properties.alpha_cc)
            * fck
            / gamma_c
            * (1.0 - fck / 250.0)
        )
    else:
        eta_cc = min((40.0 / fck) ** (1.0 / 3.0), 1.0)
        eta_cc_fat = min(0.85 * eta_cc, 0.8)
        value = beta * fck / gamma_c * eta_cc_fat
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError("calculated concrete fatigue strength must be positive")
    return value


def concrete_fatigue_life(
    compression_max_mpa: float,
    compression_min_mpa: float,
    *,
    fcd_fat_mpa: float,
    c: float = 14.0,
) -> FatigueLife:
    """Return concrete compressive fatigue life for one fixed fibre.

    EN 1992-2:2005/AC:2008 6.106 and EN 1992-1-1:2023 E.7-E.8
    have the same form.  Compression is supplied as a positive magnitude.
    """

    sigma_max = _finite(compression_max_mpa, "maximum compression")
    sigma_min = _finite(compression_min_mpa, "minimum compression")
    if sigma_min < 0.0 or sigma_max < 0.0:
        raise ValueError("concrete compression magnitudes cannot be negative")
    if sigma_min > sigma_max:
        raise ValueError("minimum compression cannot exceed maximum compression")
    strength = _positive(fcd_fat_mpa, "fcd,fat")
    coefficient = _positive(c, "concrete fatigue coefficient C")
    if sigma_max == 0.0:
        return FatigueLife(math.inf, math.inf, 0.0)

    e_max = sigma_max / strength
    ratio = sigma_min / sigma_max
    if math.isclose(ratio, 1.0, rel_tol=1.0e-12, abs_tol=1.0e-12):
        return FatigueLife(math.inf, math.inf, 0.0)
    denominator = math.sqrt(max(1.0 - ratio, 0.0))
    exponent = coefficient * (1.0 - e_max) / denominator
    return FatigueLife(
        cycles=_pow10(exponent),
        log10_cycles=exponent,
        exponent=exponent,
    )


def _concrete_compression_mpa(
    result,
    vertices: np.ndarray,
) -> tuple[float, ...]:
    plane = (
        float(result.eps0)
        + float(result.kx) * vertices[:, 0]
        + float(result.ky) * vertices[:, 1]
    )
    return tuple(float(value) for value in np.maximum(-plane, 0.0) / _MPA_DIVISOR)


def _design_elastic_result(
    state: FatigueBinState,
    gamma_ff: float,
) -> CombinedElasticResult:
    """Return the action-factored result, never a stress-scaled substitute."""

    action_factor = _positive(gamma_ff, "gamma_Ff")
    design = state.design_elastic_result
    if design is None:
        if not math.isclose(
            action_factor,
            1.0,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise ValueError(
                "gamma_Ff other than 1 requires an action-level design "
                "Elastic result"
            )
        design = state.elastic_result
    elif not math.isclose(
        float(state.design_action_factor),
        action_factor,
        rel_tol=0.0,
        abs_tol=1.0e-12,
    ):
        raise ValueError(
            "fatigue state design action factor does not match gamma_Ff"
        )
    if design is None:
        raise ValueError(
            "concrete fatigue search requires retained Elastic results"
        )
    return design


def _concrete_damage_field(
    points: np.ndarray,
    states: Sequence[FatigueBinState],
    properties: ConcreteFatigueProperties,
    gamma_ff: float,
) -> np.ndarray:
    """Return accumulated same-point concrete damage for many fibre locations."""

    fibres = np.asarray(points, dtype=float)
    if fibres.ndim != 2 or fibres.shape[1] != 2 or not len(fibres):
        raise ValueError("concrete fatigue search points must be an (N, 2) array")
    if not np.isfinite(fibres).all():
        raise ValueError("concrete fatigue search points must be finite")
    strength = concrete_fatigue_strength(properties)
    damage = np.zeros(len(fibres), dtype=float)
    for state in states:
        result = _design_elastic_result(state, gamma_ff)
        long = np.asarray(
            _concrete_compression_mpa(result.long, fibres),
            dtype=float,
        )
        total = np.asarray(
            _concrete_compression_mpa(result.short_term, fibres),
            dtype=float,
        )
        sigma_min = np.minimum(long, total)
        sigma_max = np.maximum(long, total)
        ratio = np.divide(
            sigma_min,
            sigma_max,
            out=np.zeros_like(sigma_max),
            where=sigma_max > 0.0,
        )
        no_range = np.isclose(
            sigma_min,
            sigma_max,
            rtol=1.0e-12,
            atol=1.0e-12,
        )
        denominator = np.sqrt(np.maximum(1.0 - ratio, 0.0))
        exponent = np.full(len(fibres), math.inf, dtype=float)
        active = ~no_range
        exponent[active] = (
            float(properties.c)
            * (1.0 - sigma_max[active] / strength)
            / denominator[active]
        )
        log10_damage = math.log10(float(state.cycles)) - exponent
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            partial = np.power(
                10.0,
                np.clip(
                    log10_damage,
                    _LOG10_FLOAT_TINY,
                    _LOG10_FLOAT_MAX,
                ),
            )
        partial[log10_damage < _LOG10_FLOAT_TINY] = 0.0
        partial[log10_damage > _LOG10_FLOAT_MAX] = math.inf
        partial[no_range] = 0.0
        damage += partial
    return damage


def _clip_ring_to_box(
    ring: np.ndarray,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> np.ndarray:
    clipped = clip_halfplane(ring, 1.0, 0.0, -x_min)
    clipped = clip_halfplane(clipped, -1.0, 0.0, x_max)
    clipped = clip_halfplane(clipped, 0.0, 1.0, -y_min)
    return clip_halfplane(clipped, 0.0, -1.0, y_max)


def _points_inside_convex_ring(
    points: np.ndarray,
    ring: np.ndarray,
) -> np.ndarray:
    """Fast boundary-inclusive point test for a known convex ring."""

    vertices = np.asarray(ring, dtype=float)
    following = np.roll(vertices, -1, axis=0)
    edges = following - vertices
    relative = np.asarray(points, dtype=float)[:, None, :] - vertices[None, :, :]
    cross = (
        edges[None, :, 0] * relative[:, :, 1]
        - edges[None, :, 1] * relative[:, :, 0]
    )
    tolerance = 1.0e-10 * np.maximum(
        np.linalg.norm(edges, axis=1),
        1.0,
    )
    if signed_area(vertices) >= 0.0:
        return np.all(cross >= -tolerance[None, :], axis=1)
    return np.all(cross <= tolerance[None, :], axis=1)


def _box_concrete_samples(
    section: Section,
    bounds: tuple[float, float, float, float],
    *,
    simple_convex: bool = False,
) -> np.ndarray:
    """Return section/box intersection samples, or empty for no intersection."""

    x_min, x_max, y_min, y_max = bounds
    corners = np.asarray([
        (x_min, y_min),
        (x_max, y_min),
        (x_max, y_max),
        (x_min, y_max),
        ((x_min + x_max) / 2.0, (y_min + y_max) / 2.0),
    ])
    if simple_convex:
        corner_mask = _points_inside_convex_ring(
            corners,
            section.concrete[0],
        )
    else:
        corner_mask = points_inside_concrete(
            corners,
            section.concrete[0],
            section.concrete[1:],
        )
    if simple_convex and bool(np.all(corner_mask[:4])):
        return corners

    clipped = [
        _clip_ring_to_box(
            np.asarray(ring, dtype=float),
            x_min,
            x_max,
            y_min,
            y_max,
        )
        for ring in section.concrete
    ]
    pieces = [corners]
    pieces.extend(ring for ring in clipped if len(ring))
    candidates = np.vstack(pieces)
    if simple_convex:
        mask = _points_inside_convex_ring(
            candidates,
            section.concrete[0],
        )
    else:
        mask = points_inside_concrete(
            candidates,
            section.concrete[0],
            section.concrete[1:],
        )
    return np.unique(candidates[mask], axis=0)


@dataclass(frozen=True)
class _ConcreteSearchData:
    long_planes: np.ndarray
    total_planes: np.ndarray
    log10_cycles: np.ndarray
    strength_mpa: float
    coefficient_c: float


def _concrete_search_data(
    states: Sequence[FatigueBinState],
    properties: ConcreteFatigueProperties,
    gamma_ff: float,
) -> _ConcreteSearchData:
    long_planes = []
    total_planes = []
    log10_cycles = []
    for state in states:
        result = _design_elastic_result(state, gamma_ff)
        long_planes.append((
            -float(result.long.eps0) / _MPA_DIVISOR,
            -float(result.long.kx) / _MPA_DIVISOR,
            -float(result.long.ky) / _MPA_DIVISOR,
        ))
        total_planes.append((
            -float(result.short_term.eps0) / _MPA_DIVISOR,
            -float(result.short_term.kx) / _MPA_DIVISOR,
            -float(result.short_term.ky) / _MPA_DIVISOR,
        ))
        log10_cycles.append(math.log10(float(state.cycles)))
    return _ConcreteSearchData(
        long_planes=np.asarray(long_planes, dtype=float),
        total_planes=np.asarray(total_planes, dtype=float),
        log10_cycles=np.asarray(log10_cycles, dtype=float),
        strength_mpa=concrete_fatigue_strength(properties),
        coefficient_c=float(properties.c),
    )


def _search_compressions(
    points: np.ndarray,
    planes: np.ndarray,
) -> np.ndarray:
    coordinates = np.column_stack((
        np.ones(len(points), dtype=float),
        np.asarray(points, dtype=float),
    ))
    return np.maximum(coordinates @ planes.T, 0.0)


def _search_damage_field(
    points: np.ndarray,
    data: _ConcreteSearchData,
) -> np.ndarray:
    long = _search_compressions(points, data.long_planes)
    total = _search_compressions(points, data.total_planes)
    sigma_min = np.minimum(long, total)
    sigma_max = np.maximum(long, total)
    ratio = np.divide(
        sigma_min,
        sigma_max,
        out=np.zeros_like(sigma_max),
        where=sigma_max > 0.0,
    )
    no_range = np.isclose(
        sigma_min,
        sigma_max,
        rtol=1.0e-12,
        atol=1.0e-12,
    )
    denominator = np.sqrt(np.maximum(1.0 - ratio, 0.0))
    exponent = np.full_like(sigma_max, math.inf)
    active = ~no_range
    exponent[active] = (
        data.coefficient_c
        * (1.0 - sigma_max[active] / data.strength_mpa)
        / denominator[active]
    )
    log10_damage = data.log10_cycles[None, :] - exponent
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        partial = np.power(
            10.0,
            np.clip(
                log10_damage,
                _LOG10_FLOAT_TINY,
                _LOG10_FLOAT_MAX,
            ),
        )
    partial[log10_damage < _LOG10_FLOAT_TINY] = 0.0
    partial[log10_damage > _LOG10_FLOAT_MAX] = math.inf
    partial[no_range] = 0.0
    return np.sum(partial, axis=1)


def _box_damage_upper_bound(
    bounds: tuple[float, float, float, float],
    data: _ConcreteSearchData,
) -> float:
    """Conservative accumulated-damage upper bound over an axis-aligned box.

    For a potentially passing concrete state, damage increases with maximum
    compression and decreases with minimum compression.  Affine plane extrema
    occur at box corners, so using each bin's upper maximum and lower minimum
    gives a conservative bound even though those extrema need not coincide.
    A box that can reach ``fcd,fat`` receives an infinite damage bound and is
    subdivided; the independent stress check already makes a real exceedance
    fail.
    """

    x_min, x_max, y_min, y_max = bounds
    corners = np.asarray([
        (x_min, y_min),
        (x_max, y_min),
        (x_max, y_max),
        (x_min, y_max),
    ])
    long = _search_compressions(corners, data.long_planes)
    total = _search_compressions(corners, data.total_planes)
    long_low = np.min(long, axis=0)
    long_high = np.max(long, axis=0)
    total_low = np.min(total, axis=0)
    total_high = np.max(total, axis=0)
    range_high = np.maximum(
        np.abs(long_high - total_low),
        np.abs(total_high - long_low),
    )
    sigma_max = np.maximum(long_high, total_high)
    active = (sigma_max > 0.0) & (range_high > 1.0e-12)
    if np.any(active & (sigma_max >= data.strength_mpa)):
        return math.inf
    sigma_min = np.minimum(long_low, total_low)
    ratio = np.divide(
        sigma_min,
        sigma_max,
        out=np.zeros_like(sigma_max),
        where=sigma_max > 0.0,
    )
    ratio = np.clip(ratio, 0.0, 1.0)
    denominator = np.sqrt(
        np.maximum(1.0 - ratio, np.finfo(float).tiny)
    )
    exponent = np.full_like(sigma_max, math.inf)
    exponent[active] = (
        data.coefficient_c
        * (1.0 - sigma_max[active] / data.strength_mpa)
        / denominator[active]
    )
    partial = np.asarray([
        _pow10(log_cycles - life_exponent)
        for log_cycles, life_exponent in zip(
            data.log10_cycles,
            exponent,
        )
    ])
    upper = float(np.sum(partial))
    return math.inf if math.isinf(upper) else upper


def _box_split_axis(
    bounds: tuple[float, float, float, float],
    data: _ConcreteSearchData,
) -> int:
    """Choose the axis whose split most reduces the stress intervals."""

    x_min, x_max, y_min, y_max = bounds
    planes = np.vstack((data.long_planes, data.total_planes))
    x_score = float(np.max(np.abs(planes[:, 1]))) * (x_max - x_min)
    y_score = float(np.max(np.abs(planes[:, 2]))) * (y_max - y_min)
    if math.isclose(x_score, y_score, rel_tol=1.0e-12, abs_tol=1.0e-30):
        return 0 if (x_max - x_min) >= (y_max - y_min) else 1
    return 0 if x_score > y_score else 1


@dataclass(frozen=True)
class _ConcreteSearchBox:
    bounds: tuple[float, float, float, float]
    depth: int
    upper_damage: float


def locate_governing_concrete_fibre(
    section: Section,
    states: Sequence[FatigueBinState],
    properties: ConcreteFatigueProperties,
    *,
    gamma_ff: float,
    initial_divisions: int = _DEFAULT_FIBRE_SEARCH_DIVISIONS,
    max_depth: int = _DEFAULT_FIBRE_SEARCH_MAX_DEPTH,
    max_boxes: int = _DEFAULT_FIBRE_SEARCH_MAX_BOXES,
    relative_tolerance: float = _DEFAULT_FIBRE_SEARCH_REL_TOL,
    absolute_tolerance: float = _DEFAULT_FIBRE_SEARCH_ABS_TOL,
) -> ConcreteFibreSearch:
    """Locate and *bound* the governing same-fibre concrete damage.

    A priority branch-and-bound search retains both the highest evaluated damage
    and a conservative upper bound over every unsampled concrete box.  Search
    convergence therefore means that the global bound gap meets the requested
    tolerance; repeated equal samples alone can never certify a pass.
    """

    solved = tuple(states)
    if not solved:
        raise ValueError("at least one fatigue bin is required")
    start = int(initial_divisions)
    depth_limit = int(max_depth)
    box_limit = int(max_boxes)
    rel_tol = _positive(relative_tolerance, "concrete search relative tolerance")
    abs_tol = _positive(absolute_tolerance, "concrete search absolute tolerance")
    if start < 1:
        raise ValueError("concrete search initial divisions must be at least 1")
    if depth_limit < 1:
        raise ValueError("concrete search max depth must be at least 1")
    if box_limit < start * start:
        raise ValueError(
            "concrete search max boxes must cover the initial grid"
        )

    outer = np.asarray(section.concrete[0], dtype=float)
    x_min, x_max = float(np.min(outer[:, 0])), float(np.max(outer[:, 0]))
    y_min, y_max = float(np.min(outer[:, 1])), float(np.max(outer[:, 1]))
    if x_max <= x_min or y_max <= y_min:
        raise ValueError("concrete fatigue search needs a non-degenerate section")

    vertices = section.concrete_vertices()
    search_data = _concrete_search_data(
        solved,
        properties,
        gamma_ff,
    )
    vertex_damage = _search_damage_field(vertices, search_data)
    best_index = int(np.argmax(vertex_damage))
    best_point = np.asarray(vertices[best_index], dtype=float)
    best_damage = float(vertex_damage[best_index])
    points_evaluated = len(vertices)
    boxes_evaluated = 0
    max_depth_seen = 0
    counter = 0
    heap: list[tuple[float, int, _ConcreteSearchBox]] = []
    simple_convex = (
        len(section.concrete) == 1
        and polygon_is_convex(section.concrete[0])
    )

    def consider(
        bounds: tuple[float, float, float, float],
        depth: int,
    ) -> None:
        nonlocal best_point, best_damage, points_evaluated
        nonlocal boxes_evaluated, max_depth_seen, counter
        samples = _box_concrete_samples(
            section,
            bounds,
            simple_convex=simple_convex,
        )
        if not len(samples):
            return
        upper = _box_damage_upper_bound(
            bounds,
            search_data,
        )
        values = _search_damage_field(samples, search_data)
        points_evaluated += len(samples)
        boxes_evaluated += 1
        index = int(np.argmax(values))
        sampled = float(values[index])
        if sampled > best_damage:
            best_damage = sampled
            best_point = np.asarray(samples[index], dtype=float)
        upper = max(upper, sampled)
        max_depth_seen = max(max_depth_seen, depth)
        if upper > best_damage:
            counter += 1
            box = _ConcreteSearchBox(bounds, depth, upper)
            heapq.heappush(heap, (-upper, counter, box))

    x_edges = np.linspace(x_min, x_max, start + 1)
    y_edges = np.linspace(y_min, y_max, start + 1)
    for ix in range(start):
        for iy in range(start):
            consider(
                (
                    float(x_edges[ix]),
                    float(x_edges[ix + 1]),
                    float(y_edges[iy]),
                    float(y_edges[iy + 1]),
                ),
                0,
            )

    # If every initial box is already bounded by the best sampled value,
    # there is no unresolved search region and the certificate is complete.
    converged = not heap
    while heap:
        while heap and -heap[0][0] <= best_damage:
            heapq.heappop(heap)
        if not heap:
            converged = True
            break
        upper = max(best_damage, -heap[0][0])
        if math.isfinite(upper) and math.isfinite(best_damage):
            gap = max(0.0, upper - best_damage)
            permitted = abs_tol + rel_tol * max(abs(best_damage), 1.0e-12)
            if gap <= permitted:
                converged = True
                break
        if boxes_evaluated >= box_limit:
            break
        box = heap[0][2]
        if box.depth >= depth_limit:
            break
        heapq.heappop(heap)
        bx0, bx1, by0, by1 = box.bounds
        child_depth = box.depth + 1
        if _box_split_axis(box.bounds, search_data) == 0:
            midpoint = (bx0 + bx1) / 2.0
            children = (
                (bx0, midpoint, by0, by1),
                (midpoint, bx1, by0, by1),
            )
        else:
            midpoint = (by0 + by1) / 2.0
            children = (
                (bx0, bx1, by0, midpoint),
                (bx0, bx1, midpoint, by1),
            )
        for bounds in children:
            consider(bounds, child_depth)

    upper_damage = (
        max(best_damage, -heap[0][0])
        if heap
        else best_damage
    )
    if math.isinf(best_damage) and best_damage > 0.0:
        upper_damage = best_damage
        converged = True
    if math.isfinite(upper_damage) and math.isfinite(best_damage):
        absolute_gap = max(0.0, upper_damage - best_damage)
        relative_gap = absolute_gap / max(abs(upper_damage), 1.0e-12)
    else:
        absolute_gap = math.inf
        relative_gap = math.inf

    return ConcreteFibreSearch(
        x_m=float(best_point[0]),
        y_m=float(best_point[1]),
        damage=float(best_damage),
        upper_damage=float(upper_damage),
        divisions=start * (2 ** max_depth_seen),
        boxes_evaluated=boxes_evaluated,
        points_evaluated=points_evaluated,
        absolute_gap=float(absolute_gap),
        relative_gap=float(relative_gap),
        converged=converged,
    )


def _states_at_concrete_fibres(
    states: Sequence[FatigueBinState],
    fibres: np.ndarray,
) -> tuple[FatigueBinState, ...]:
    """Replace only the concrete stress arrays at the requested fixed fibres."""

    output = []
    for state in states:
        raw = state.elastic_result
        if raw is None:
            raise ValueError(
                "concrete fatigue fibres require retained Elastic results"
            )
        design = state.design_elastic_result or raw
        output.append(replace(
            state,
            concrete_compression_long_mpa=_concrete_compression_mpa(
                raw.long,
                fibres,
            ),
            concrete_compression_total_mpa=_concrete_compression_mpa(
                raw.short_term,
                fibres,
            ),
            concrete_compression_design_total_mpa=(
                _concrete_compression_mpa(
                    design.short_term,
                    fibres,
                )
            ),
        ))
    return tuple(output)


def _fatigue_solver_section(
    section: Section,
    *,
    tendon_area_factors: Sequence[float] | None = None,
) -> tuple[Section, tuple[Bar, ...]]:
    """Return the Elastic section in canonical mild-then-tendon order."""

    mild = tuple(section.bars)
    tendons = tuple(section.tendons)
    if tendon_area_factors is None:
        tendon_bars = tendons
    else:
        factors = np.asarray(tendon_area_factors, dtype=float)
        if factors.shape != (len(tendons),):
            raise ValueError(
                "tendon area factors must match the tendon count"
            )
        if not np.isfinite(factors).all() or np.any(factors <= 0.0):
            raise ValueError("tendon area factors must be finite and positive")
        tendon_bars = tuple(
            Bar(tendon.x, tendon.y, tendon.area * float(factor))
            for tendon, factor in zip(tendons, factors)
        )
    elements = (*mild, *tendon_bars)
    solver_section = Section(
        concrete=[np.asarray(ring, dtype=float) for ring in section.concrete],
        bars=list(elements),
    )
    return solver_section, elements


def _validated_solver_vector(
    values: np.ndarray | None,
    count: int,
    label: str,
    *,
    require_positive: bool = False,
) -> np.ndarray | None:
    """Reject NumPy broadcasting at the fatigue-to-Elastic boundary."""

    if values is None:
        return None
    try:
        vector = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{label} must be a finite vector with exactly {count} values"
        ) from exc
    if vector.shape != (count,):
        raise ValueError(
            f"{label} must have shape ({count},), got {vector.shape}"
        )
    if not np.isfinite(vector).all():
        raise ValueError(f"{label} values must be finite")
    if require_positive and np.any(vector <= 0.0):
        raise ValueError(f"{label} values must be greater than zero")
    return vector


def solve_fatigue_bin(
    section: Section,
    bin_input: SpectrumBin,
    nl: float,
    ns: float,
    *,
    gamma_ff: float = 1.0,
    n_mult: np.ndarray | None = None,
    prestress_stress: np.ndarray | None = None,
    displace_concrete: bool = False,
) -> FatigueBinState:
    """Solve characteristic and action-factored cyclic endpoints."""

    _positive(nl, "long-term modular ratio")
    _positive(ns, "short-term modular ratio")
    action_factor = _positive(gamma_ff, "gamma_Ff")
    solver_section, elements = _fatigue_solver_section(section)
    modular_factors = _validated_solver_vector(
        n_mult,
        len(elements),
        "n_mult",
        require_positive=True,
    )
    initial_stress = _validated_solver_vector(
        prestress_stress,
        len(elements),
        "prestress_stress",
    )
    def solve(short_factor: float) -> CombinedElasticResult:
        return solve_elastic_combined(
            solver_section,
            bin_input.p_long_kn,
            bin_input.mx_long_knm,
            bin_input.my_long_knm,
            nl,
            short_factor * bin_input.p_short_kn,
            short_factor * bin_input.mx_short_knm,
            short_factor * bin_input.my_short_knm,
            ns,
            n_mult=modular_factors,
            prestress_stress=initial_stress,
            displace_concrete=displace_concrete,
        )

    result = solve(1.0)
    design_result = (
        result
        if math.isclose(
            action_factor,
            1.0,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        )
        else solve(action_factor)
    )
    vertices = solver_section.concrete_vertices()
    raw_total = tuple(
        float(value) / _MPA_DIVISOR
        for value in result.bar_stress_total
    )
    design_total = tuple(
        float(value) / _MPA_DIVISOR
        for value in design_result.bar_stress_total
    )
    return FatigueBinState(
        name=str(bin_input.name).strip(),
        description=str(bin_input.description).strip(),
        cycles=float(bin_input.cycles),
        converged=bool(result.converged and design_result.converged),
        bar_stress_long_mpa=tuple(
            float(value) / _MPA_DIVISOR
            for value in result.bar_stress_long
        ),
        bar_stress_total_mpa=raw_total,
        concrete_compression_long_mpa=_concrete_compression_mpa(
            result.long, vertices
        ),
        concrete_compression_total_mpa=_concrete_compression_mpa(
            result.short_term, vertices
        ),
        elastic_result=result,
        bar_stress_fatigue_total_mpa=raw_total,
        design_action_factor=action_factor,
        design_elastic_result=design_result,
        bar_stress_design_total_mpa=design_total,
        bar_stress_fatigue_design_total_mpa=design_total,
        concrete_compression_design_total_mpa=(
            _concrete_compression_mpa(
                design_result.short_term,
                vertices,
            )
        ),
    )


def _validate_reinforcement_mapping(
    section: Section,
    properties: Sequence[ReinforcementFatigueProperties],
    solver_element_ids: Sequence[str] | None,
) -> tuple[str, ...]:
    """Tie each fatigue record to one canonical solver element."""

    mild_count = len(section.bars)
    tendon_count = len(section.tendons)
    count = mild_count + tendon_count
    if solver_element_ids is None:
        element_ids = (
            tuple(f"R{index + 1}" for index in range(mild_count))
            + tuple(f"P{index + 1}" for index in range(tendon_count))
        )
    else:
        element_ids = tuple(str(value).strip() for value in solver_element_ids)
        if len(element_ids) != count:
            raise ValueError(
                f"solver_element_ids must contain exactly {count} values"
            )
    _unique_names(element_ids, "solver reinforcement element")

    props = tuple(properties)
    if len(props) != count:
        raise ValueError(
            f"{count} solver bars or tendons require {count} fatigue "
            "property records"
        )
    for index, (item, expected_id) in enumerate(zip(props, element_ids)):
        actual_id = str(item.element_id).strip()
        if actual_id != expected_id:
            raise ValueError(
                f"fatigue property record {index + 1} has element ID "
                f"'{actual_id}', expected '{expected_id}'"
            )
        expected_kind = MILD if index < mild_count else PRESTRESS
        actual_kind = str(item.kind).strip().lower()
        if actual_kind != expected_kind:
            raise ValueError(
                f"{expected_id}: kind must be '{expected_kind}' to match "
                "the solver element"
            )
    return element_ids


def _mixed_bond_parameters(
    section: Section,
    properties: Sequence[ReinforcementFatigueProperties],
) -> tuple[np.ndarray, float]:
    """Return tendon ``sqrt(xi*phi_s/phi_p)`` values and 2005 eta."""

    mild_count = len(section.bars)
    props = tuple(properties)
    phi_s = max(float(item.diameter_mm) for item in props[:mild_count])
    betas = []
    for item in props[mild_count:]:
        if item.bond_ratio_xi is None:
            raise ValueError(
                f"{item.element_id}: bond_ratio_xi is required when mild "
                "reinforcement and bonded tendons are combined"
            )
        if item.bond_equivalent_diameter_mm is None:
            raise ValueError(
                f"{item.element_id}: bond_equivalent_diameter_mm is required "
                "when mild reinforcement and bonded tendons are combined"
            )
        beta = math.sqrt(
            float(item.bond_ratio_xi)
            * phi_s
            / float(item.bond_equivalent_diameter_mm)
        )
        if not math.isfinite(beta) or beta <= 0.0:
            raise ValueError(
                f"{item.element_id}: calculated bond factor must be finite "
                "and positive"
            )
        betas.append(beta)

    mild_area = sum(
        _positive(bar.area, f"mild bar {index + 1} area")
        for index, bar in enumerate(section.bars)
    )
    tendon_areas = np.asarray(
        [
            _positive(tendon.area, f"tendon {index + 1} area")
            for index, tendon in enumerate(section.tendons)
        ],
        dtype=float,
    )
    beta_vector = np.asarray(betas, dtype=float)
    denominator = mild_area + float(np.sum(tendon_areas * beta_vector))
    eta = (mild_area + float(np.sum(tendon_areas))) / denominator
    if not math.isfinite(eta) or eta <= 0.0:
        raise ValueError("calculated 2005 bond correction eta is invalid")
    return beta_vector, eta


def _apply_reinforcement_bond_correction(
    section: Section,
    bins: Sequence[SpectrumBin],
    states: Sequence[FatigueBinState],
    properties: Sequence[ReinforcementFatigueProperties],
    edition: str | None,
    nl: float,
    ns: float,
    *,
    gamma_ff: float,
    n_mult: np.ndarray | None,
    prestress_stress: np.ndarray | None,
    displace_concrete: bool,
) -> tuple[FatigueBinState, ...]:
    """Apply the edition-specific mixed rebar/tendon bond model."""

    solved = tuple(states)
    mild_count = len(section.bars)
    tendon_count = len(section.tendons)
    if mild_count == 0 or tendon_count == 0:
        return solved
    if edition is None:
        raise ValueError(
            "fatigue_edition is required when mild reinforcement and bonded "
            "tendons are combined"
        )
    selected = _normalise_edition(edition)
    betas, eta = _mixed_bond_parameters(section, properties)
    count = mild_count + tendon_count
    modular_factors = _validated_solver_vector(
        n_mult,
        count,
        "n_mult",
        require_positive=True,
    )
    initial_stress = _validated_solver_vector(
        prestress_stress,
        count,
        "prestress_stress",
    )

    if selected == EC2_2005:
        factors = np.concatenate((
            np.full(mild_count, eta, dtype=float),
            np.ones(tendon_count, dtype=float),
        ))
        method = (
            "EN 1992-1-1:2005 6.8.2(2) reinforcing-steel bond "
            f"correction (eta={eta:.6g}); tendon range unadjusted"
        )
        corrected = []
        for state in solved:
            long = np.asarray(state.bar_stress_long_mpa, dtype=float)
            total = np.asarray(state.bar_stress_total_mpa, dtype=float)
            design_total = np.asarray(
                state.bar_stress_design_total_mpa,
                dtype=float,
            )
            fatigue_total = long + factors * (total - long)
            fatigue_design_total = (
                long + factors * (design_total - long)
            )
            corrected.append(replace(
                state,
                bar_stress_fatigue_total_mpa=tuple(
                    float(value) for value in fatigue_total
                ),
                bar_stress_fatigue_design_total_mpa=tuple(
                    float(value) for value in fatigue_design_total
                ),
                bond_method=method,
            ))
        return tuple(corrected)

    equivalent_section, _ = _fatigue_solver_section(
        section,
        tendon_area_factors=betas,
    )
    if modular_factors is None:
        modular_factors = np.ones(count, dtype=float)
    if initial_stress is None:
        initial_stress = np.zeros(count, dtype=float)
    equivalent_initial_stress = initial_stress.copy()
    equivalent_initial_stress[mild_count:] /= betas
    equivalent_states = tuple(
        solve_fatigue_bin(
            equivalent_section,
            bin_input,
            nl,
            ns,
            gamma_ff=gamma_ff,
            n_mult=modular_factors,
            prestress_stress=equivalent_initial_stress,
            displace_concrete=displace_concrete,
        )
        for bin_input in bins
    )
    method = "EN 1992-1-1:2023 10.3(2) equivalent tendon area"
    corrected = []
    for state, equivalent in zip(solved, equivalent_states):
        long = np.asarray(state.bar_stress_long_mpa, dtype=float)
        equivalent_long = np.asarray(
            equivalent.bar_stress_long_mpa,
            dtype=float,
        )
        equivalent_total = np.asarray(
            equivalent.bar_stress_total_mpa,
            dtype=float,
        )
        equivalent_design_total = np.asarray(
            equivalent.bar_stress_design_total_mpa,
            dtype=float,
        )
        corrected_range = equivalent_total - equivalent_long
        corrected_design_range = (
            equivalent_design_total - equivalent_long
        )
        corrected_range[mild_count:] *= betas
        corrected_design_range[mild_count:] *= betas
        corrected.append(replace(
            state,
            converged=bool(state.converged and equivalent.converged),
            bar_stress_fatigue_total_mpa=tuple(
                float(value) for value in long + corrected_range
            ),
            bar_stress_fatigue_design_total_mpa=tuple(
                float(value)
                for value in long + corrected_design_range
            ),
            bond_method=method,
        ))
    return tuple(corrected)


def _yield_assessment(
    stress_mpa: float,
    properties: ReinforcementFatigueProperties,
    gamma_s: float,
) -> tuple[float, float]:
    if stress_mpa >= 0.0:
        characteristic = float(properties.fytk_mpa)
    else:
        characteristic = float(
            properties.fyck_mpa
            if properties.fyck_mpa is not None
            else properties.fytk_mpa
        )
    limit = characteristic / gamma_s
    return limit, abs(float(stress_mpa)) / limit


def assess_reinforcement_spectrum(
    properties: Sequence[ReinforcementFatigueProperties],
    states: Sequence[FatigueBinState],
    *,
    gamma_s: float,
    gamma_ff: float,
) -> tuple[ReinforcementFatigueResult, ...]:
    """Accumulate steel damage independently for every bar or tendon."""

    material_factor = _positive(gamma_s, "gamma_s")
    action_factor = _positive(gamma_ff, "gamma_Ff")
    props = tuple(properties)
    solved = tuple(states)
    if not solved:
        raise ValueError("at least one fatigue bin is required")
    _unique_names(
        (state.name for state in solved),
        "fatigue bin",
    )
    _unique_names(
        (item.element_id for item in props),
        "reinforcement element",
    )
    for state in solved:
        fatigue_total = (
            state.bar_stress_fatigue_total_mpa
            or state.bar_stress_total_mpa
        )
        fatigue_design_total = (
            state.bar_stress_fatigue_design_total_mpa
            or (
                fatigue_total
                if math.isclose(
                    action_factor,
                    1.0,
                    rel_tol=0.0,
                    abs_tol=1.0e-12,
                )
                else ()
            )
        )
        if (
            len(state.bar_stress_long_mpa) != len(props)
            or len(state.bar_stress_total_mpa) != len(props)
            or len(fatigue_total) != len(props)
            or len(fatigue_design_total) != len(props)
        ):
            raise ValueError(
                "reinforcement fatigue properties and action-level design "
                "stresses must match solver bar order"
            )
        if (
            state.bar_stress_fatigue_design_total_mpa
            and not math.isclose(
                float(state.design_action_factor),
                action_factor,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            )
        ):
            raise ValueError(
                "fatigue state design action factor does not match gamma_Ff"
            )

    output = []
    for index, item in enumerate(props):
        bins = []
        for state in solved:
            stress_long = float(state.bar_stress_long_mpa[index])
            stress_total_elastic = float(
                state.bar_stress_total_mpa[index]
            )
            fatigue_total = (
                state.bar_stress_fatigue_total_mpa
                or state.bar_stress_total_mpa
            )
            fatigue_design_total = (
                state.bar_stress_fatigue_design_total_mpa
                or fatigue_total
            )
            stress_total = float(fatigue_total[index])
            stress_total_design = float(fatigue_design_total[index])
            stress_range = abs(stress_total - stress_long)
            design_stress_range = abs(
                stress_total_design - stress_long
            )
            stress_range_elastic = abs(
                stress_total_elastic - stress_long
            )
            if stress_range_elastic > 0.0:
                bond_adjustment = stress_range / stress_range_elastic
            elif stress_range > 0.0:
                bond_adjustment = math.inf
            else:
                bond_adjustment = 1.0
            life = steel_fatigue_life(
                design_stress_range,
                n_star=item.n_star,
                k1=item.k1,
                k2=item.k2,
                delta_sigma_rsk_mpa=item.delta_sigma_rsk_mpa,
                gamma_s=material_factor,
                gamma_ff=1.0,
            )
            damage = _damage(state.cycles, life.log10_cycles)
            long_limit, long_util = _yield_assessment(
                stress_long, item, material_factor
            )
            total_limit, total_util = _yield_assessment(
                stress_total_design, item, material_factor
            )
            if total_util >= long_util:
                governing_stress = stress_total_design
                yield_limit = total_limit
                yield_utilisation = total_util
            else:
                governing_stress = stress_long
                yield_limit = long_limit
                yield_utilisation = long_util
            bins.append(ReinforcementBinResult(
                bin_name=state.name,
                cycles=state.cycles,
                converged=state.converged,
                stress_long_mpa=stress_long,
                stress_total_mpa=stress_total,
                stress_total_design_mpa=stress_total_design,
                stress_total_elastic_mpa=stress_total_elastic,
                stress_range_mpa=stress_range,
                stress_range_elastic_mpa=stress_range_elastic,
                bond_adjustment=bond_adjustment,
                bond_method=state.bond_method,
                design_stress_range_mpa=design_stress_range,
                delta_sigma_rsk_mpa=float(item.delta_sigma_rsk_mpa),
                delta_sigma_rd_mpa=(
                    float(item.delta_sigma_rsk_mpa) / material_factor
                ),
                sn_exponent=life.exponent,
                cycles_to_failure=life.cycles,
                log10_cycles_to_failure=life.log10_cycles,
                damage=damage,
                governing_stress_mpa=governing_stress,
                yield_limit_mpa=yield_limit,
                yield_utilisation=yield_utilisation,
            ))
        damage = sum(result.damage for result in bins)
        damage_governing = max(bins, key=lambda result: result.damage)
        yield_governing = max(
            bins, key=lambda result: result.yield_utilisation
        )
        converged = all(result.converged for result in bins)
        utilisation = max(damage, yield_governing.yield_utilisation)
        output.append(ReinforcementFatigueResult(
            element_id=item.element_id,
            kind=str(item.kind).strip().lower(),
            detail_id=item.detail_id,
            diameter_mm=float(item.diameter_mm),
            bins=tuple(bins),
            damage=damage,
            damage_utilisation=damage,
            governing_damage_bin=damage_governing.bin_name,
            yield_utilisation=yield_governing.yield_utilisation,
            governing_yield_bin=yield_governing.bin_name,
            utilisation=utilisation,
            converged=converged,
            passed=bool(
                converged
                and damage <= DAMAGE_LIMIT
                and yield_governing.yield_utilisation <= 1.0
            ),
        ))
    return tuple(output)


def assess_concrete_spectrum(
    vertices: np.ndarray,
    states: Sequence[FatigueBinState],
    properties: ConcreteFatigueProperties,
    *,
    gamma_ff: float,
) -> tuple[ConcreteFibreFatigueResult, ...]:
    """Accumulate concrete damage at every fixed input fibre."""

    points = np.asarray(vertices, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or not len(points):
        raise ValueError("concrete fatigue fibres must be an (N, 2) array")
    if not np.isfinite(points).all():
        raise ValueError("concrete fatigue fibre coordinates must be finite")
    solved = tuple(states)
    if not solved:
        raise ValueError("at least one fatigue bin is required")
    _unique_names(
        (state.name for state in solved),
        "fatigue bin",
    )
    action_factor = _positive(gamma_ff, "gamma_Ff")
    strength = concrete_fatigue_strength(properties)
    for state in solved:
        design_total = (
            state.concrete_compression_design_total_mpa
            or (
                state.concrete_compression_total_mpa
                if math.isclose(
                    action_factor,
                    1.0,
                    rel_tol=0.0,
                    abs_tol=1.0e-12,
                )
                else ()
            )
        )
        if (
            len(state.concrete_compression_long_mpa) != len(points)
            or len(state.concrete_compression_total_mpa) != len(points)
            or len(design_total) != len(points)
        ):
            raise ValueError(
                "concrete fatigue stresses and action-level design stresses "
                "must match the fixed fibre array"
            )
        if (
            state.concrete_compression_design_total_mpa
            and not math.isclose(
                float(state.design_action_factor),
                action_factor,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            )
        ):
            raise ValueError(
                "fatigue state design action factor does not match gamma_Ff"
            )

    output = []
    for fibre_index, (x, y) in enumerate(points):
        bins = []
        for state in solved:
            sigma_long = float(
                state.concrete_compression_long_mpa[fibre_index]
            )
            sigma_total = float(
                state.concrete_compression_total_mpa[fibre_index]
            )
            design_total = (
                state.concrete_compression_design_total_mpa
                or state.concrete_compression_total_mpa
            )
            sigma_total_design = float(design_total[fibre_index])
            sigma_min = min(sigma_long, sigma_total_design)
            sigma_max = max(sigma_long, sigma_total_design)
            life = concrete_fatigue_life(
                sigma_max,
                sigma_min,
                fcd_fat_mpa=strength,
                c=properties.c,
            )
            damage = _damage(state.cycles, life.log10_cycles)
            ratio = sigma_min / sigma_max if sigma_max > 0.0 else 0.0
            e_min = sigma_min / strength
            e_max = sigma_max / strength
            bins.append(ConcreteBinResult(
                bin_name=state.name,
                cycles=state.cycles,
                converged=state.converged,
                compression_long_mpa=sigma_long,
                compression_total_mpa=sigma_total,
                compression_min_design_mpa=sigma_min,
                compression_max_design_mpa=sigma_max,
                stress_ratio=ratio,
                e_cd_min=e_min,
                e_cd_max=e_max,
                cycles_to_failure=life.cycles,
                log10_cycles_to_failure=life.log10_cycles,
                damage=damage,
                stress_utilisation=e_max,
            ))
        damage = sum(result.damage for result in bins)
        damage_governing = max(bins, key=lambda result: result.damage)
        stress_governing = max(
            bins, key=lambda result: result.stress_utilisation
        )
        converged = all(result.converged for result in bins)
        utilisation = max(damage, stress_governing.stress_utilisation)
        output.append(ConcreteFibreFatigueResult(
            fibre_index=fibre_index,
            x_m=float(x),
            y_m=float(y),
            bins=tuple(bins),
            fcd_fat_mpa=strength,
            damage=damage,
            damage_utilisation=damage,
            governing_damage_bin=damage_governing.bin_name,
            stress_utilisation=stress_governing.stress_utilisation,
            governing_stress_bin=stress_governing.bin_name,
            utilisation=utilisation,
            converged=converged,
            passed=bool(
                converged
                and damage <= DAMAGE_LIMIT
                and stress_governing.stress_utilisation <= 1.0
            ),
        ))
    return tuple(output)


def analyse_fatigue_spectrum(
    spectrum_name: str,
    section: Section,
    bins: Sequence[SpectrumBin],
    nl: float,
    ns: float,
    *,
    reinforcement: Sequence[ReinforcementFatigueProperties] = (),
    concrete: ConcreteFatigueProperties | None = None,
    fatigue_edition: str | None = None,
    solver_element_ids: Sequence[str] | None = None,
    gamma_s: float = 1.15,
    gamma_ff: float = 1.0,
    check_reinforcement: bool = True,
    check_concrete: bool = True,
    n_mult: np.ndarray | None = None,
    prestress_stress: np.ndarray | None = None,
    displace_concrete: bool = False,
    concrete_search_initial_divisions: int = (
        _DEFAULT_FIBRE_SEARCH_DIVISIONS
    ),
    concrete_search_max_depth: int = (
        _DEFAULT_FIBRE_SEARCH_MAX_DEPTH
    ),
    concrete_search_max_boxes: int = (
        _DEFAULT_FIBRE_SEARCH_MAX_BOXES
    ),
    concrete_search_relative_tolerance: float = (
        _DEFAULT_FIBRE_SEARCH_REL_TOL
    ),
    concrete_search_absolute_tolerance: float = (
        _DEFAULT_FIBRE_SEARCH_ABS_TOL
    ),
) -> FatigueSpectrumResult:
    """Solve and assess one independent grouped fatigue spectrum."""

    name = str(spectrum_name).strip()
    if not name:
        raise ValueError("fatigue spectrum name is required")
    bin_inputs = tuple(bins)
    if not bin_inputs:
        raise ValueError(f"{name}: at least one fatigue bin is required")
    if any(not isinstance(item, SpectrumBin) for item in bin_inputs):
        raise ValueError(f"{name}: fatigue bins must be SpectrumBin objects")
    _unique_names(
        (item.name for item in bin_inputs),
        "fatigue bin",
    )
    if not check_reinforcement and not check_concrete:
        raise ValueError("at least one fatigue material check must be enabled")
    bar_count = len(section.bars) + len(section.tendons)
    properties = tuple(reinforcement)
    selected_edition = (
        _normalise_edition(fatigue_edition)
        if fatigue_edition is not None
        else None
    )
    if concrete is not None:
        concrete_edition = _normalise_edition(concrete.edition)
        if (
            selected_edition is not None
            and selected_edition != concrete_edition
        ):
            raise ValueError(
                "fatigue_edition must match the concrete fatigue edition"
            )
        selected_edition = concrete_edition
    if check_reinforcement and bar_count == 0:
        raise ValueError(
            f"{name}: reinforcement fatigue check requires at least one bar "
            "or tendon"
        )
    if check_reinforcement:
        try:
            _validate_reinforcement_mapping(
                section,
                properties,
                solver_element_ids,
            )
        except ValueError as exc:
            raise ValueError(f"{name}: {exc}") from exc
    if (
        check_reinforcement
        and section.bars
        and section.tendons
        and selected_edition is None
    ):
        raise ValueError(
            f"{name}: fatigue_edition is required when mild reinforcement "
            "and bonded tendons are combined"
        )
    if check_concrete and concrete is None:
        raise ValueError(f"{name}: concrete fatigue properties are required")
    _validated_solver_vector(
        n_mult,
        bar_count,
        "n_mult",
        require_positive=True,
    )
    _validated_solver_vector(
        prestress_stress,
        bar_count,
        "prestress_stress",
    )

    states = tuple(
        solve_fatigue_bin(
            section,
            bin_input,
            nl,
            ns,
            gamma_ff=gamma_ff,
            n_mult=n_mult,
            prestress_stress=prestress_stress,
            displace_concrete=displace_concrete,
        )
        for bin_input in bin_inputs
    )
    if check_reinforcement:
        states = _apply_reinforcement_bond_correction(
            section,
            bin_inputs,
            states,
            properties,
            selected_edition,
            nl,
            ns,
            gamma_ff=gamma_ff,
            n_mult=n_mult,
            prestress_stress=prestress_stress,
            displace_concrete=displace_concrete,
        )
    concrete_search = None
    concrete_fibres = section.concrete_vertices()
    if check_concrete and concrete is not None:
        concrete_search = locate_governing_concrete_fibre(
            section,
            states,
            concrete,
            gamma_ff=gamma_ff,
            initial_divisions=concrete_search_initial_divisions,
            max_depth=concrete_search_max_depth,
            max_boxes=concrete_search_max_boxes,
            relative_tolerance=concrete_search_relative_tolerance,
            absolute_tolerance=concrete_search_absolute_tolerance,
        )
        search_point = np.asarray(
            (concrete_search.x_m, concrete_search.y_m),
            dtype=float,
        )
        extent = max(
            float(np.ptp(concrete_fibres[:, 0])),
            float(np.ptp(concrete_fibres[:, 1])),
            1.0,
        )
        duplicate = np.any(
            np.linalg.norm(concrete_fibres - search_point, axis=1)
            <= 1.0e-10 * extent
        )
        if not duplicate:
            concrete_fibres = np.vstack((concrete_fibres, search_point))
        states = _states_at_concrete_fibres(states, concrete_fibres)
    steel_results = (
        assess_reinforcement_spectrum(
            properties,
            states,
            gamma_s=gamma_s,
            gamma_ff=gamma_ff,
        )
        if check_reinforcement
        else ()
    )
    concrete_results = (
        assess_concrete_spectrum(
            concrete_fibres,
            states,
            concrete,
            gamma_ff=gamma_ff,
        )
        if check_concrete and concrete is not None
        else ()
    )
    all_results = (*steel_results, *concrete_results)
    converged = bool(
        all(state.converged for state in states)
        and (
            concrete_search is None
            or concrete_search.converged
        )
    )
    utilisations = [result.utilisation for result in all_results]
    if concrete_search is not None:
        utilisations.append(concrete_search.upper_damage)
    utilisation = max(utilisations, default=0.0)
    governing_steel = (
        max(steel_results, key=lambda result: result.utilisation).element_id
        if steel_results
        else None
    )
    governing_concrete = (
        max(
            concrete_results,
            key=lambda result: result.utilisation,
        ).fibre_index
        if concrete_results
        else None
    )
    return FatigueSpectrumResult(
        spectrum_name=name,
        bins=states,
        reinforcement=steel_results,
        concrete=concrete_results,
        concrete_search=concrete_search,
        fcd_fat_mpa=(
            concrete_fatigue_strength(concrete)
            if check_concrete and concrete is not None
            else None
        ),
        governing_reinforcement_id=governing_steel,
        governing_concrete_fibre=governing_concrete,
        utilisation=utilisation,
        converged=converged,
        passed=bool(
            converged
            and all(result.passed for result in all_results)
            and (
                concrete_search is None
                or concrete_search.upper_damage <= DAMAGE_LIMIT
            )
        ),
    )


def analyse_grouped_spectra(
    section: Section,
    spectra: Mapping[str, Sequence[SpectrumBin]],
    nl: float,
    ns: float,
    **kwargs,
) -> tuple[FatigueSpectrumResult, ...]:
    """Assess each named spectrum independently and preserve input order."""

    if not isinstance(spectra, Mapping) or not spectra:
        raise ValueError("at least one grouped fatigue spectrum is required")
    seen: dict[str, str] = {}
    seen_bins: dict[str, str] = {}
    results = []
    for raw_name, bins in spectra.items():
        name = str(raw_name).strip()
        folded = name.casefold()
        if not name:
            raise ValueError("fatigue spectrum name is required")
        if folded in seen:
            raise ValueError(
                f"fatigue spectrum '{name}' differs only by case from "
                f"'{seen[folded]}'"
            )
        seen[folded] = name
        for bin_input in bins:
            if not isinstance(bin_input, SpectrumBin):
                raise ValueError(
                    f"{name}: fatigue bins must be SpectrumBin objects"
                )
            bin_name = str(bin_input.name).strip()
            folded_bin = bin_name.casefold()
            if folded_bin in seen_bins:
                raise ValueError(
                    f"fatigue bin name '{bin_name}' duplicates "
                    f"'{seen_bins[folded_bin]}'"
                )
            seen_bins[folded_bin] = bin_name
        results.append(
            analyse_fatigue_spectrum(
                name,
                section,
                bins,
                nl,
                ns,
                **kwargs,
            )
        )
    return tuple(results)
