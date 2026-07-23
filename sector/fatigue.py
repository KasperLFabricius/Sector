"""Headless fatigue verification for reinforced-concrete cross-sections.

The module evaluates grouped constant-amplitude spectra with the existing
cracked Elastic solver.  Each bin contains a non-cyclic long-term action and a
cyclic short-term increment.  Reinforcement stress ranges are therefore the
difference between the combined and long-term Elastic results.

Two explicit Eurocode methods are supported:

* reinforcing and prestressing steel use the two-slope S-N curves and linear
  Palmgren-Miner damage summation in EN 1992-1-1;
* concrete compression uses the corrected EN 1992-2:2005 expression or the
  equivalent EN 1992-1-1:2023 Annex E expression, accumulated at each fixed
  concrete fibre.

All partial factors are complete caller inputs.  This module does not apply
control-class, construction-category, consequence-class or authority-specific
multipliers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math

import numpy as np

from .elastic import CombinedElasticResult, solve_elastic_combined
from .section import Section


EC2_2005 = "2005"
EC2_2023 = "2023"
MILD = "mild"
PRESTRESS = "prestress"
DAMAGE_LIMIT = 1.0
_MPA_DIVISOR = 1000.0
_LOG10_FLOAT_MAX = math.log10(np.finfo(float).max)
_LOG10_FLOAT_TINY = math.log10(np.nextafter(0.0, 1.0))


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
    elastic_result: CombinedElasticResult


@dataclass(frozen=True)
class ReinforcementBinResult:
    bin_name: str
    cycles: float
    converged: bool
    stress_long_mpa: float
    stress_total_mpa: float
    stress_range_mpa: float
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
class FatigueSpectrumResult:
    spectrum_name: str
    bins: tuple[FatigueBinState, ...]
    reinforcement: tuple[ReinforcementFatigueResult, ...]
    concrete: tuple[ConcreteFibreFatigueResult, ...]
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


def solve_fatigue_bin(
    section: Section,
    bin_input: SpectrumBin,
    nl: float,
    ns: float,
    *,
    n_mult: np.ndarray | None = None,
    prestress_stress: np.ndarray | None = None,
    displace_concrete: bool = False,
) -> FatigueBinState:
    """Solve one spectrum bin and expose both cyclic endpoints."""

    _positive(nl, "long-term modular ratio")
    _positive(ns, "short-term modular ratio")
    result = solve_elastic_combined(
        section,
        bin_input.p_long_kn,
        bin_input.mx_long_knm,
        bin_input.my_long_knm,
        nl,
        bin_input.p_short_kn,
        bin_input.mx_short_knm,
        bin_input.my_short_knm,
        ns,
        n_mult=n_mult,
        prestress_stress=prestress_stress,
        displace_concrete=displace_concrete,
    )
    vertices = section.concrete_vertices()
    return FatigueBinState(
        name=str(bin_input.name).strip(),
        description=str(bin_input.description).strip(),
        cycles=float(bin_input.cycles),
        converged=bool(result.converged),
        bar_stress_long_mpa=tuple(
            float(value) / _MPA_DIVISOR
            for value in result.bar_stress_long
        ),
        bar_stress_total_mpa=tuple(
            float(value) / _MPA_DIVISOR
            for value in result.bar_stress_total
        ),
        concrete_compression_long_mpa=_concrete_compression_mpa(
            result.long, vertices
        ),
        concrete_compression_total_mpa=_concrete_compression_mpa(
            result.short_term, vertices
        ),
        elastic_result=result,
    )


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
        if len(state.bar_stress_long_mpa) != len(props):
            raise ValueError(
                "reinforcement fatigue properties must match solver bar order"
            )

    output = []
    for index, item in enumerate(props):
        bins = []
        for state in solved:
            stress_long = float(state.bar_stress_long_mpa[index])
            stress_total = float(state.bar_stress_total_mpa[index])
            stress_range = abs(stress_total - stress_long)
            life = steel_fatigue_life(
                stress_range,
                n_star=item.n_star,
                k1=item.k1,
                k2=item.k2,
                delta_sigma_rsk_mpa=item.delta_sigma_rsk_mpa,
                gamma_s=material_factor,
                gamma_ff=action_factor,
            )
            damage = _damage(state.cycles, life.log10_cycles)
            long_limit, long_util = _yield_assessment(
                stress_long, item, material_factor
            )
            total_limit, total_util = _yield_assessment(
                stress_total, item, material_factor
            )
            if total_util >= long_util:
                governing_stress = stress_total
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
                stress_range_mpa=stress_range,
                design_stress_range_mpa=action_factor * stress_range,
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
        if (
            len(state.concrete_compression_long_mpa) != len(points)
            or len(state.concrete_compression_total_mpa) != len(points)
        ):
            raise ValueError(
                "concrete fatigue stresses must match the fixed fibre array"
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
            sigma_min = action_factor * min(sigma_long, sigma_total)
            sigma_max = action_factor * max(sigma_long, sigma_total)
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
    gamma_s: float = 1.15,
    gamma_ff: float = 1.0,
    check_reinforcement: bool = True,
    check_concrete: bool = True,
    n_mult: np.ndarray | None = None,
    prestress_stress: np.ndarray | None = None,
    displace_concrete: bool = False,
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
    bar_count = len(section.bar_arrays()[0])
    properties = tuple(reinforcement)
    if check_reinforcement and bar_count == 0:
        raise ValueError(
            f"{name}: reinforcement fatigue check requires at least one bar "
            "or tendon"
        )
    if check_reinforcement and len(properties) != bar_count:
        raise ValueError(
            f"{name}: {bar_count} solver bars require {bar_count} "
            "reinforcement fatigue property records"
        )
    if check_concrete and concrete is None:
        raise ValueError(f"{name}: concrete fatigue properties are required")

    states = tuple(
        solve_fatigue_bin(
            section,
            bin_input,
            nl,
            ns,
            n_mult=n_mult,
            prestress_stress=prestress_stress,
            displace_concrete=displace_concrete,
        )
        for bin_input in bin_inputs
    )
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
            section.concrete_vertices(),
            states,
            concrete,
            gamma_ff=gamma_ff,
        )
        if check_concrete and concrete is not None
        else ()
    )
    all_results = (*steel_results, *concrete_results)
    converged = all(state.converged for state in states)
    utilisation = max(
        (result.utilisation for result in all_results),
        default=0.0,
    )
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
