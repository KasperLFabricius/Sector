"""Semantic contracts for the accepted Part C manual equations.

This module owns symbol meanings, canonical publication units, result identity,
dimensional class and equation-to-equation dependencies.  Authored location and
source provenance are supplied by the two accepted predecessor contracts.
Rendering belongs to later PR-11 slices.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from manual_equation_location import (
    LocatedManualEquation,
    MANUAL_EQUATION_LOCATIONS,
    ManualEquationLocation,
)
from manual_equation_source import (
    MANUAL_EQUATION_SOURCES,
    ManualEquationSource,
    SourcedManualEquation,
)


_UNITS = frozenset(
    (
        "1",
        "1/mm",
        "MPa",
        "N",
        "N mm",
        "case action",
        "cycles",
        "days",
        "matching action",
        "mm",
        "mm^2",
        "rad",
    )
)


@dataclass(frozen=True, slots=True)
class ManualEquationTerm:
    """One exact mathematical term and its publication meaning and unit."""

    markup: str
    meaning: str
    unit: str


@dataclass(frozen=True, slots=True)
class ManualEquationContract:
    """Complete non-visual semantic contract for one manual equation."""

    ordinal: int
    key: str
    number: str
    symbols: tuple[ManualEquationTerm, ...]
    results: tuple[ManualEquationTerm, ...]
    dimensional_class: str
    uses: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContractedManualEquation:
    """One canonical sourced equation bound to its semantic contract."""

    equation: SourcedManualEquation
    contract: ManualEquationContract


def _terms(
    *rows: tuple[str, str, str],
) -> tuple[ManualEquationTerm, ...]:
    return tuple(ManualEquationTerm(*row) for row in rows)


def _contract(
    ordinal: int,
    key: str,
    number: str,
    symbols: tuple[ManualEquationTerm, ...],
    results: tuple[ManualEquationTerm, ...],
    dimensional_class: str,
    uses: tuple[str, ...] = (),
) -> ManualEquationContract:
    return ManualEquationContract(
        ordinal,
        key,
        number,
        symbols,
        results,
        dimensional_class,
        uses,
    )


MANUAL_EQUATION_CONTRACTS = (
    _contract(
        1, "manual.material.concrete-law", "C3-1",
        _terms(
            (r"\sigma_c", "concrete design stress", "MPa"),
            (r"f_{cd}", "design concrete compressive strength", "MPa"),
            (r"\varepsilon_c", "concrete strain", "1"),
            (r"\varepsilon_{c2}", "strain at peak concrete stress", "1"),
            (r"\varepsilon_{cu2}", "ultimate concrete strain", "1"),
            (r"n", "parabola exponent", "1"),
        ),
        _terms((r"\sigma_c", "concrete design stress", "MPa")),
        "stress law",
    ),
    _contract(
        2, "manual.material.steel-law", "C3-2",
        _terms(
            (r"\sigma_s", "reinforcing-steel design stress", "MPa"),
            (r"E_{s,d}", "design reinforcing-steel modulus", "MPa"),
            (r"\varepsilon_s", "reinforcing-steel strain", "1"),
            (r"\varepsilon_{yd}", "design yield strain", "1"),
            (r"f_{yd}", "design yield strength", "MPa"),
            (r"f_{yk}", "characteristic yield strength", "MPa"),
            (r"\gamma_s", "reinforcing-steel partial factor", "1"),
        ),
        _terms(
            (r"\sigma_s", "reinforcing-steel design stress", "MPa"),
            (r"f_{yd}", "design yield strength", "MPa"),
            (r"\varepsilon_{yd}", "design yield strain", "1"),
        ),
        "stress and strain law",
    ),
    _contract(
        3, "manual.material.prestress-law", "C3-3",
        _terms(
            (r"\varepsilon_{p,j}", "total strain of tendon j", "1"),
            (r"\varepsilon_{p,IS,j}", "locked-in strain of tendon j", "1"),
            (r"\kappa", "section curvature", "1/mm"),
            (r"s_{p,j}", "tendon-j coordinate normal to the neutral axis", "mm"),
            (r"s_{na}", "neutral-axis coordinate", "mm"),
            (r"\sigma_p", "prestressing-steel design stress", "MPa"),
            (r"f(\varepsilon_p)",
             "stress returned by the selected prestressing-steel law", "MPa"),
            (r"\varepsilon_p", "prestressing-steel total strain", "1"),
            (r"f_{pd}", "design 0.1 percent proof strength", "MPa"),
            (r"f_{p0.1k}", "characteristic 0.1 percent proof strength", "MPa"),
            (r"\gamma_s", "prestressing-steel partial factor", "1"),
        ),
        _terms(
            (r"\varepsilon_{p,j}", "total strain of tendon j", "1"),
            (r"\sigma_p", "prestressing-steel design stress", "MPa"),
            (r"f_{pd}", "design 0.1 percent proof strength", "MPa"),
        ),
        "strain and stress law",
    ),
    _contract(
        4, "manual.plastic.governing-curvature", "C4-1",
        _terms(
            (r"\kappa", "governing section curvature", "1/mm"),
            (r"\varepsilon_{cu2}", "ultimate concrete strain", "1"),
            (r"c", "compression-zone depth", "mm"),
            (r"\varepsilon_{u,i}", "ultimate strain of reinforcing bar i", "1"),
            (r"s_{na}", "neutral-axis coordinate", "mm"),
            (r"s_{b,i}", "bar-i coordinate normal to the neutral axis", "mm"),
            (r"\varepsilon_{pu,j}", "ultimate strain of tendon j", "1"),
            (r"\varepsilon_{p,IS,j}", "locked-in strain of tendon j", "1"),
            (r"s_{p,j}", "tendon-j coordinate normal to the neutral axis", "mm"),
            (r"i", "reinforcing-bar index", "1"),
            (r"j", "tendon index", "1"),
        ),
        _terms((r"\kappa", "governing section curvature", "1/mm")),
        "curvature selection",
        (
            "manual.material.concrete-law",
            "manual.material.steel-law",
            "manual.material.prestress-law",
        ),
    ),
    _contract(
        5, "manual.detailing.minimum-2005", "C5-1",
        _terms(
            (r"A_{s,min}", "required minimum reinforcement area", "mm^2"),
            (r"A_{s,prov}", "provided reinforcement area", "mm^2"),
            (r"f_{ctm}", "mean concrete tensile strength", "MPa"),
            (r"f_{yk}", "characteristic reinforcing-steel yield strength", "MPa"),
            (r"b_t", "mean breadth of the tension half-plane", "mm"),
            (r"d", "effective depth", "mm"),
        ),
        _terms((r"A_{s,min}", "required minimum reinforcement area", "mm^2")),
        "area check",
    ),
    _contract(
        6, "manual.detailing.minimum-2023-bending", "C5-2",
        _terms(
            (r"M_{R,nom}", "nominal bending resistance", "N mm"),
            (r"M_{cr}", "cracking moment", "N mm"),
            (r"N_{Ed}", "design axial force", "N"),
        ),
        _terms((r"M_{R,nom}", "nominal bending resistance", "N mm")),
        "moment check",
    ),
    _contract(
        7, "manual.detailing.minimum-2023-axial", "C5-3",
        _terms(
            (r"A_{s,i}", "area of reinforcing bar i", "mm^2"),
            (r"f_{yk,i}", "characteristic yield strength of bar i", "MPa"),
            (r"A_c", "gross concrete area", "mm^2"),
            (r"f_{ctm}", "mean concrete tensile strength", "MPa"),
            (r"i", "reinforcing-bar index", "1"),
        ),
        _terms(
            (r"\sum_i A_{s,i}f_{yk,i}",
             "provided characteristic tensile resistance", "N"),
        ),
        "force check",
    ),
    _contract(
        8, "manual.detailing.clear-spacing", "C5-4",
        _terms(
            (r"c_{clear}", "clear distance between included elements", "mm"),
            (r"\phi_{max}", "larger included reinforcement diameter", "mm"),
            (r"D_{upper}", "upper aggregate size", "mm"),
        ),
        _terms((r"c_{clear}", "clear distance between included elements", "mm")),
        "length check",
    ),
    _contract(
        9, "manual.detailing.links.minimum-ratio", "C5-5",
        _terms(
            (r"\rho_w", "provided shear-link reinforcement ratio", "1"),
            (r"\rho_{w,min}", "minimum shear-link reinforcement ratio", "1"),
            (r"A_{sw}", "shear-link area within one spacing", "mm^2"),
            (r"s", "longitudinal link spacing", "mm"),
            (r"b_w", "effective web breadth", "mm"),
            (r"c", "edition-specific minimum-ratio coefficient", "1"),
            (r"f_{ck}", "characteristic concrete compressive strength", "MPa"),
            (r"f_{ywk}", "characteristic link yield strength", "MPa"),
        ),
        _terms(
            (r"\rho_w", "provided shear-link reinforcement ratio", "1"),
            (r"\rho_{w,min}", "minimum shear-link reinforcement ratio", "1"),
        ),
        "dimensionless ratio check",
    ),
    _contract(
        10, "manual.detailing.links.spacing", "C5-6",
        _terms(
            (r"s_l", "longitudinal link spacing", "mm"),
            (r"s_t", "maximum transverse distance between link legs", "mm"),
            (r"d", "effective depth", "mm"),
        ),
        _terms(
            (r"s_l", "longitudinal link spacing", "mm"),
            (r"s_t", "maximum transverse distance between link legs", "mm"),
        ),
        "length checks",
    ),
    _contract(
        11, "manual.detailing.torsion.minimum-ratio", "C5-7",
        _terms(
            (r"\rho_{w,T}", "provided torsion-link wall ratio", "1"),
            (r"A_{leg}", "area of one closed-link leg", "mm^2"),
            (r"s", "longitudinal closed-link spacing", "mm"),
            (r"t_{ef}", "effective torsion-wall thickness", "mm"),
            (r"\rho_{w,min}", "minimum link reinforcement ratio", "1"),
        ),
        _terms((r"\rho_{w,T}", "provided torsion-link wall ratio", "1")),
        "dimensionless ratio check",
        ("manual.detailing.links.minimum-ratio",),
    ),
    _contract(
        12, "manual.crack.2005.width", "C7-1",
        _terms(
            (r"w_k", "characteristic crack width", "mm"),
            (r"s_{r,max}", "maximum crack spacing", "mm"),
            (r"\varepsilon_{sm}", "mean reinforcement strain", "1"),
            (r"\varepsilon_{cm}", "mean concrete strain between cracks", "1"),
            (r"\sigma_s", "reinforcement stress", "MPa"),
            (r"k_t", "load-duration factor", "1"),
            (r"f_{ct,eff}", "effective concrete tensile strength", "MPa"),
            (r"\rho_{p,eff}", "effective reinforcement ratio", "1"),
            (r"\alpha_e", "reinforcement-to-concrete modulus ratio", "1"),
            (r"E_s", "reinforcing-steel modulus", "MPa"),
        ),
        _terms(
            (r"w_k", "characteristic crack width", "mm"),
            (r"\varepsilon_{sm}-\varepsilon_{cm}",
             "mean strain difference", "1"),
        ),
        "crack-width relation",
        ("manual.crack.2005.spacing",),
    ),
    _contract(
        13, "manual.crack.2005.spacing", "C7-2",
        _terms(
            (r"s_{r,max}", "maximum crack spacing", "mm"),
            (r"k_1", "bond-property coefficient", "1"),
            (r"k_2", "strain-distribution coefficient", "1"),
            (r"k_3", "cover coefficient", "1"),
            (r"k_4", "bar-diameter coefficient", "1"),
            (r"c", "reinforcement cover", "mm"),
            (r"\phi", "reinforcement diameter", "mm"),
            (r"\rho_{p,eff}", "effective reinforcement ratio", "1"),
            (r"h", "section depth", "mm"),
            (r"x", "neutral-axis depth", "mm"),
        ),
        _terms((r"s_{r,max}", "maximum crack spacing", "mm")),
        "length relation",
    ),
    _contract(
        14, "manual.crack.dk-na-heightened", "C7-5",
        _terms(
            (r"\rho_{s,min}", "required heightened minimum reinforcement ratio", "1"),
            (r"m_s", "reinforcement-surface multiplier", "1"),
            (r"\phi", "bar diameter", "mm"),
            (r"f_{ct,eff}", "user-supplied effective tensile strength", "MPa"),
            (r"E_{sk}", "reinforcement elastic modulus", "MPa"),
            (r"k", "fine/coarse crack-system factor", "1"),
            (r"w_k", "user-supplied permitted crack width", "mm"),
        ),
        _terms(
            (r"\rho_{s,min}", "required heightened minimum reinforcement ratio", "1"),
        ),
        "dimensionless reinforcement-ratio relation",
    ),
    _contract(
        15, "manual.crack.2023.width", "C7-3",
        _terms(
            (r"w_k", "characteristic crack width", "mm"),
            (r"k_w", "characteristic-to-mean crack factor", "1"),
            (r"\frac{k_1}{r}", "per-bar curvature factor", "1"),
            (r"s_{r,m,cal}", "calculated mean crack spacing", "mm"),
            (r"\varepsilon_{sm}", "mean reinforcement strain", "1"),
            (r"\varepsilon_{cm}", "mean concrete strain between cracks", "1"),
            (r"h", "section depth", "mm"),
            (r"x", "neutral-axis depth", "mm"),
            (r"a_{y,i}", "bar-i distance from the tension face", "mm"),
            (r"i", "reinforcing-bar index", "1"),
        ),
        _terms(
            (r"w_k", "characteristic crack width", "mm"),
            (r"\frac{k_1}{r}", "per-bar curvature factor", "1"),
        ),
        "crack-width relation",
        ("manual.crack.2023.spacing",),
    ),
    _contract(
        16, "manual.crack.2023.spacing", "C7-4",
        _terms(
            (r"s_{r,m,cal}", "calculated mean crack spacing", "mm"),
            (r"c", "reinforcement cover", "mm"),
            (r"k_{fl}", "flexural strain-distribution coefficient", "1"),
            (r"k_b", "bond coefficient", "1"),
            (r"\phi", "reinforcement diameter", "mm"),
            (r"\rho_{p,eff}", "effective reinforcement ratio", "1"),
            (r"k_w", "characteristic-to-mean crack factor", "1"),
            (r"h", "section depth", "mm"),
            (r"x", "neutral-axis depth", "mm"),
        ),
        _terms((r"s_{r,m,cal}", "calculated mean crack spacing", "mm")),
        "length relation",
    ),
    _contract(
        17, "manual.fatigue.stress-range", "C8-1",
        _terms(
            (r"\Delta\sigma_{Ed,i}", "design stress range in bin i", "MPa"),
            (r"\sigma(S)", "stress reconstructed for action state S", "MPa"),
            (r"S_l", "sustained or basic action state", "case action"),
            (r"S_s", "cyclic action increment", "case action"),
            (r"\gamma_{Ff}", "fatigue action partial factor", "1"),
            (r"i", "spectrum-bin index", "1"),
        ),
        _terms(
            (r"\Delta\sigma_{Ed,i}", "design stress range in bin i", "MPa"),
        ),
        "stress-range relation",
    ),
    _contract(
        18, "manual.fatigue.reinforcement.design-range", "C8-2",
        _terms(
            (r"\Delta\sigma_{Rd}", "design fatigue-detail stress range", "MPa"),
            (r"\Delta\sigma_{Rsk}",
             "characteristic fatigue-detail reference range", "MPa"),
            (r"\gamma_s", "reinforcement fatigue partial factor", "1"),
        ),
        _terms(
            (r"\Delta\sigma_{Rd}", "design fatigue-detail stress range", "MPa"),
        ),
        "stress relation",
    ),
    _contract(
        19, "manual.fatigue.reinforcement.life", "C8-3",
        _terms(
            (r"N_{R,i}", "resistant cycle count for bin i", "cycles"),
            (r"N^*", "reference cycle count", "cycles"),
            (r"\Delta\sigma_{Rd}", "design fatigue-detail stress range", "MPa"),
            (r"\Delta\sigma_{Ed,i}", "design stress range in bin i", "MPa"),
            (r"k", "active S-N slope", "1"),
            (r"i", "spectrum-bin index", "1"),
        ),
        _terms((r"N_{R,i}", "resistant cycle count for bin i", "cycles")),
        "cycle-life relation",
        (
            "manual.fatigue.stress-range",
            "manual.fatigue.reinforcement.design-range",
        ),
    ),
    _contract(
        20, "manual.fatigue.reinforcement.miner", "C8-4",
        _terms(
            (r"D", "Palmgren-Miner damage", "1"),
            (r"n_i", "applied cycle count in bin i", "cycles"),
            (r"N_{R,i}", "resistant cycle count for bin i", "cycles"),
            (r"i", "spectrum-bin index", "1"),
        ),
        _terms((r"D", "Palmgren-Miner damage", "1")),
        "dimensionless damage check",
        ("manual.fatigue.reinforcement.life",),
    ),
    _contract(
        21, "manual.fatigue.concrete.strength-2005", "C8-5",
        _terms(
            (r"f_{cd,fat}", "design concrete fatigue strength", "MPa"),
            (r"k_1", "fatigue-strength coefficient", "1"),
            (r"\beta_{cc}(t_0)", "concrete age factor at first loading", "1"),
            (r"t_0", "concrete age at first fatigue loading", "days"),
            (r"\alpha_{cc}", "concrete strength coefficient", "1"),
            (r"f_{ck}", "characteristic concrete compressive strength", "MPa"),
            (r"\gamma_{c,fat}", "concrete fatigue partial factor", "1"),
        ),
        _terms((r"f_{cd,fat}", "design concrete fatigue strength", "MPa")),
        "stress relation",
    ),
    _contract(
        22, "manual.fatigue.concrete.strength-2023", "C8-6",
        _terms(
            (r"\eta_{cc}", "concrete strength-effect factor", "1"),
            (r"\eta_{cc,fat}", "fatigue concrete strength-effect factor", "1"),
            (r"f_{cd,fat}", "design concrete fatigue strength", "MPa"),
            (r"f_{ck}", "characteristic concrete compressive strength", "MPa"),
            (r"\beta_{cc}(t_0)", "concrete age factor at first loading", "1"),
            (r"t_0", "concrete age at first fatigue loading", "days"),
            (r"\gamma_{c,fat}", "concrete fatigue partial factor", "1"),
        ),
        _terms(
            (r"\eta_{cc}", "concrete strength-effect factor", "1"),
            (r"\eta_{cc,fat}", "fatigue concrete strength-effect factor", "1"),
            (r"f_{cd,fat}", "design concrete fatigue strength", "MPa"),
        ),
        "dimensionless factors and stress relation",
    ),
    _contract(
        23, "manual.fatigue.concrete.life", "C8-7",
        _terms(
            (r"N_R", "resistant cycle count", "cycles"),
            (r"C", "selected concrete S-N coefficient", "1"),
            (r"E_{max}", "maximum normalized concrete stress", "1"),
            (r"R", "minimum-to-maximum concrete stress ratio", "1"),
        ),
        _terms((r"N_R", "resistant cycle count", "cycles")),
        "cycle-life relation",
        (
            "manual.fatigue.concrete.strength-2005",
            "manual.fatigue.concrete.strength-2023",
        ),
    ),
    _contract(
        24, "manual.fatigue.concrete.equivalent", "C8-8",
        _terms(
            (r"E_{max}", "maximum normalized equivalent stress", "1"),
            (r"E_{min}", "minimum normalized equivalent stress", "1"),
        ),
        _terms(
            (r"E_{max}+0.43\sqrt{1-E_{min}/E_{max}}",
             "damage-equivalent concrete fatigue criterion", "1"),
        ),
        "dimensionless fatigue check",
        (
            "manual.fatigue.concrete.strength-2005",
            "manual.fatigue.concrete.strength-2023",
        ),
    ),
    _contract(
        25, "manual.shear.no-links.variable", "C9-1",
        _terms(
            (r"V_{Rd,c}", "design shear resistance without links", "N"),
            (r"C_{Rd,c}", "edition-specific shear coefficient", "1"),
            (r"k", "size-effect factor", "1"),
            (r"\rho_l", "longitudinal reinforcement ratio", "1"),
            (r"f_{ck}", "characteristic concrete compressive strength", "MPa"),
            (r"k_1", "axial-stress coefficient", "1"),
            (r"\sigma_{cp}", "concrete axial stress", "MPa"),
            (r"b_w", "effective web breadth", "mm"),
            (r"d", "effective depth", "mm"),
        ),
        _terms((r"V_{Rd,c}", "design shear resistance without links", "N")),
        "force relation",
    ),
    _contract(
        26, "manual.shear.no-links.minimum", "C9-2",
        _terms(
            (r"V_{Rd,c}", "minimum design shear resistance without links", "N"),
            (r"v_{min}", "minimum shear stress", "MPa"),
            (r"k_1", "axial-stress coefficient", "1"),
            (r"\sigma_{cp}", "concrete axial stress", "MPa"),
            (r"b_w", "effective web breadth", "mm"),
            (r"d", "effective depth", "mm"),
        ),
        _terms(
            (r"V_{Rd,c}", "minimum design shear resistance without links", "N"),
        ),
        "force relation",
    ),
    _contract(
        27, "manual.shear.action-factor-2023", "C9-3",
        _terms(
            (r"a_{cs}", "shear-span parameter", "mm"),
            (r"k_{vp}", "axial-action shear factor", "1"),
            (r"M_{Ed}", "design bending moment", "N mm"),
            (r"V_{Ed}", "design shear force", "N"),
            (r"N_{Ed}", "design axial force, tension positive", "N"),
            (r"d", "effective depth", "mm"),
        ),
        _terms(
            (r"a_{cs}", "shear-span parameter", "mm"),
            (r"k_{vp}", "axial-action shear factor", "1"),
        ),
        "length and dimensionless factor",
    ),
    _contract(
        28, "manual.shear.links-2005", "C9-4",
        _terms(
            (r"V_{Rd,s}", "shear-link resistance", "N"),
            (r"V_{Rd,max}", "maximum concrete-strut shear resistance", "N"),
            (r"A_{sw}", "shear-link area within one spacing", "mm^2"),
            (r"s", "longitudinal link spacing", "mm"),
            (r"z", "internal lever arm", "mm"),
            (r"f_{ywd}", "design link yield strength", "MPa"),
            (r"\theta", "concrete-strut angle", "rad"),
            (r"\alpha_{cw}", "compression-chord factor", "1"),
            (r"b_w", "effective web breadth", "mm"),
            (r"\nu_1", "concrete-strut effectiveness factor", "1"),
            (r"f_{cd}", "design concrete compressive strength", "MPa"),
        ),
        _terms(
            (r"V_{Rd,s}", "shear-link resistance", "N"),
            (r"V_{Rd,max}", "maximum concrete-strut shear resistance", "N"),
        ),
        "force relations",
    ),
    _contract(
        29, "manual.shear.links-2023", "C9-5",
        _terms(
            (r"\tau_{Rd,sy}", "link-provided design shear stress", "MPa"),
            (r"\rho_w", "provided shear-link reinforcement ratio", "1"),
            (r"f_{ywd}", "design link yield strength", "MPa"),
            (r"\theta", "concrete-strut angle", "rad"),
            (r"\sigma_{cd}", "concrete-strut compressive stress", "MPa"),
            (r"\tau_{Ed}", "design shear stress", "MPa"),
            (r"\nu", "concrete-strut effectiveness factor", "1"),
            (r"f_{cd}", "design concrete compressive strength", "MPa"),
        ),
        _terms(
            (r"\tau_{Rd,sy}", "link-provided design shear stress", "MPa"),
            (r"\sigma_{cd}", "concrete-strut compressive stress", "MPa"),
        ),
        "stress relations",
        ("manual.detailing.links.minimum-ratio",),
    ),
    _contract(
        30, "manual.torsion.resistance", "C10-1",
        _terms(
            (r"T_{Rd,s}", "torsion-link resistance", "N mm"),
            (r"T_{Rd,max}", "maximum concrete-strut torsion resistance", "N mm"),
            (r"A_{sw}", "closed-link area within one spacing", "mm^2"),
            (r"s", "longitudinal closed-link spacing", "mm"),
            (r"A_k", "area enclosed by the effective wall centre-line", "mm^2"),
            (r"f_{ywd}", "design link yield strength", "MPa"),
            (r"\theta", "concrete-strut angle", "rad"),
            (r"\nu", "concrete-strut effectiveness factor", "1"),
            (r"\alpha_{cw}", "compression-chord factor", "1"),
            (r"f_{cd}", "design concrete compressive strength", "MPa"),
            (r"t_{ef}", "effective torsion-wall thickness", "mm"),
        ),
        _terms(
            (r"T_{Rd,s}", "torsion-link resistance", "N mm"),
            (r"T_{Rd,max}", "maximum concrete-strut torsion resistance", "N mm"),
        ),
        "moment relations",
    ),
    _contract(
        31, "manual.torsion.strut-interaction", "C10-2",
        _terms(
            (r"T_{Ed}", "design torsional moment", "N mm"),
            (r"T_{Rd,max}", "maximum concrete-strut torsion resistance", "N mm"),
            (r"V_{Ed}", "design shear force", "N"),
            (r"V_{Rd,max}", "maximum concrete-strut shear resistance", "N"),
        ),
        _terms(
            (r"T_{Ed}/T_{Rd,max}+V_{Ed}/V_{Rd,max}",
             "combined torsion-shear strut utilization", "1"),
        ),
        "dimensionless interaction check",
        (
            "manual.shear.links-2005",
            "manual.torsion.resistance",
        ),
    ),
    _contract(
        32, "manual.combined.strut-interaction", "C11-1",
        _terms(
            (r"T_{Ed}", "design torsional moment", "N mm"),
            (r"T_{Rd,max}", "maximum concrete-strut torsion resistance", "N mm"),
            (r"V_{Ed}", "design shear force", "N"),
            (r"V_{Rd,max}", "maximum concrete-strut shear resistance", "N"),
        ),
        _terms(
            (r"T_{Ed}/T_{Rd,max}+V_{Ed}/V_{Rd,max}",
             "combined torsion-shear strut utilization", "1"),
        ),
        "dimensionless interaction check",
        (
            "manual.shear.links-2005",
            "manual.torsion.resistance",
        ),
    ),
    _contract(
        33, "manual.combined.utilisation", "C11-2",
        _terms(
            (r"S_{Ed}", "one design sectional action", "matching action"),
            (r"S_{Rd}", "resistance to that action acting alone", "matching action"),
        ),
        _terms(
            (r"\sum(S_{Ed}/S_{Rd})",
             "Danish general sectional-force utilization", "1"),
        ),
        "dimensionless interaction check",
        (
            "manual.shear.links-2005",
            "manual.shear.links-2023",
            "manual.torsion.resistance",
        ),
    ),
)


def _validate_term(term: ManualEquationTerm, *, label: str) -> None:
    if type(term) is not ManualEquationTerm:
        raise RuntimeError(f"{label} must retain ManualEquationTerm type.")
    if not all(
        type(value) is str and value and value.isascii()
        for value in (term.markup, term.meaning, term.unit)
    ):
        raise RuntimeError(f"{label} must contain non-empty ASCII strings.")
    if term.unit not in _UNITS:
        raise RuntimeError(f"{label} has unsupported unit {term.unit!r}.")


def _validate_dependency_graph() -> None:
    by_key = {item.key: item for item in MANUAL_EQUATION_CONTRACTS}
    state: dict[str, int] = {}

    def visit(key: str) -> None:
        marker = state.get(key, 0)
        if marker == 1:
            raise RuntimeError("Manual equation dependencies must be acyclic.")
        if marker == 2:
            return
        state[key] = 1
        for dependency in by_key[key].uses:
            visit(dependency)
        state[key] = 2

    for key in by_key:
        visit(key)


def _validate_catalogue() -> None:
    if type(MANUAL_EQUATION_CONTRACTS) is not tuple:
        raise RuntimeError("Manual equation contract catalogue must remain a tuple.")
    if len(MANUAL_EQUATION_CONTRACTS) != 33:
        raise RuntimeError("Expected exactly 33 manual equation contracts.")
    if tuple(item.ordinal for item in MANUAL_EQUATION_CONTRACTS) != tuple(
        range(1, 34)
    ):
        raise RuntimeError("Manual equation contract ordinals must be contiguous.")

    canonical_keys = tuple(item.key for item in MANUAL_EQUATION_LOCATIONS)
    canonical_numbers = tuple(item.number for item in MANUAL_EQUATION_LOCATIONS)
    if tuple(item.key for item in MANUAL_EQUATION_CONTRACTS) != canonical_keys:
        raise RuntimeError("Manual equation contract keys must match locations.")
    if tuple(item.number for item in MANUAL_EQUATION_CONTRACTS) != canonical_numbers:
        raise RuntimeError("Manual equation contract numbers must match locations.")

    key_set = set(canonical_keys)
    for item in MANUAL_EQUATION_CONTRACTS:
        if type(item) is not ManualEquationContract:
            raise RuntimeError("Contract catalogue entries must retain exact type.")
        if not item.symbols or not item.results:
            raise RuntimeError(f"Incomplete semantic contract: {item.key!r}.")
        for label, terms in (("symbols", item.symbols), ("results", item.results)):
            if type(terms) is not tuple:
                raise RuntimeError(f"{item.key} {label} must remain a tuple.")
            for index, term in enumerate(terms):
                _validate_term(term, label=f"{item.key} {label}[{index}]")
            markups = tuple(term.markup for term in terms)
            if len(markups) != len(set(markups)):
                raise RuntimeError(f"{item.key} {label} must be unique.")
        if (
            type(item.dimensional_class) is not str
            or not item.dimensional_class
            or not item.dimensional_class.isascii()
        ):
            raise RuntimeError(f"Invalid dimensional class: {item.key!r}.")
        if type(item.uses) is not tuple:
            raise RuntimeError(f"{item.key} dependencies must remain a tuple.")
        if len(item.uses) != len(set(item.uses)):
            raise RuntimeError(f"{item.key} dependencies must be unique.")
        if any(
            type(dependency) is not str
            or not dependency.isascii()
            or dependency not in key_set
            or dependency == item.key
            for dependency in item.uses
        ):
            raise RuntimeError(f"Invalid dependency in {item.key!r}.")
    _validate_dependency_graph()


_validate_catalogue()


def bind_manual_equation_contracts(
    equations: tuple[SourcedManualEquation, ...],
    catalogue: tuple[ManualEquationContract, ...] = MANUAL_EQUATION_CONTRACTS,
) -> tuple[ContractedManualEquation, ...]:
    """Bind exact canonical semantics to exact canonical sourced equations."""

    if type(catalogue) is not tuple or len(catalogue) != 33:
        raise ValueError("Canonical manual equation contract catalogue changed.")
    if any(
        type(item) is not ManualEquationContract
        or type(item.symbols) is not tuple
        or type(item.results) is not tuple
        or type(item.uses) is not tuple
        or any(type(term) is not ManualEquationTerm for term in item.symbols)
        or any(type(term) is not ManualEquationTerm for term in item.results)
        for item in catalogue
    ):
        raise ValueError("Canonical manual equation contract catalogue changed.")
    if catalogue != MANUAL_EQUATION_CONTRACTS:
        raise ValueError("Canonical manual equation contract catalogue changed.")
    if type(equations) is not tuple:
        raise ValueError("Sourced manual equations must remain a tuple.")
    if len(equations) != 33:
        raise ValueError(
            f"Sourced manual equation cardinality changed: expected 33, "
            f"got {len(equations)}."
        )

    bound: list[ContractedManualEquation] = []
    for equation, location, source, contract in zip(
        equations,
        MANUAL_EQUATION_LOCATIONS,
        MANUAL_EQUATION_SOURCES,
        MANUAL_EQUATION_CONTRACTS,
    ):
        if type(equation) is not SourcedManualEquation:
            raise ValueError("Sourced manual equation type changed.")
        if type(equation.equation) is not LocatedManualEquation:
            raise ValueError("Located manual equation type changed.")
        if type(equation.equation.location) is not ManualEquationLocation:
            raise ValueError("Manual equation location type changed.")
        if type(equation.source) is not ManualEquationSource:
            raise ValueError("Manual equation source type changed.")
        if equation.equation.location != location:
            raise ValueError("Sourced manual equation location identity changed.")
        expression = equation.equation.expression
        if type(expression) is not str or not expression.isascii():
            raise ValueError("Sourced manual equation expression type changed.")
        digest = hashlib.sha256(expression.encode("ascii")).hexdigest()
        if digest != location.expression_sha256:
            raise ValueError("Sourced manual equation expression changed.")
        if equation.source != source:
            raise ValueError("Sourced manual equation provenance changed.")
        if (contract.ordinal, contract.key, contract.number) != (
            location.ordinal,
            location.key,
            location.number,
        ):
            raise ValueError("Manual equation contract identity changed.")
        bound.append(ContractedManualEquation(equation, contract))
    return tuple(bound)


def contract_catalogue_sha256() -> str:
    """Return a deterministic seal over every retained semantic field."""

    rows = [
        [
            item.ordinal,
            item.key,
            item.number,
            [[term.markup, term.meaning, term.unit] for term in item.symbols],
            [[term.markup, term.meaning, term.unit] for term in item.results],
            item.dimensional_class,
            list(item.uses),
        ]
        for item in MANUAL_EQUATION_CONTRACTS
    ]
    canonical = json.dumps(
        rows,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
