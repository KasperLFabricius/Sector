"""Frozen semantic contracts for generated-report equation blocks.

Solver and result objects own the numerical values.  This module owns the
publication identity around them: every equation's symbols, final quantity and
unit, and the semantic role of its authored publication rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_KEY_RE = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
_MATERIAL_KEY_RE = re.compile(r"materials\.steel\.fyd-[1-9][0-9]*")
_PUBLICATION_ROLES = frozenset(("theory", "calculation"))
_SUBSTITUTION_ROLES = frozenset(("none", "numerical"))
_MATERIAL_TEMPLATE_KEY = "materials.steel.fyd-N"


@dataclass(frozen=True, slots=True)
class EquationSymbol:
    """One symbol retained by an equation and its publication meaning."""

    markup: str
    meaning: str
    unit: str = "dimensionless"


@dataclass(frozen=True, slots=True)
class EquationContract:
    """Complete non-visual publication contract for one equation variant."""

    symbols: tuple[EquationSymbol, ...]
    result_symbol: str | None = None
    result_unit: str | None = None
    substitution_role: str = "none"
    publication_role: str = "theory"
    applicability_note_required: bool = False

    @property
    def expects_result(self) -> bool:
        return self.result_symbol is not None

    @property
    def expects_substitution(self) -> bool:
        return self.substitution_role != "none"


def _symbols(*rows: tuple[str, str] | tuple[str, str, str]) -> tuple[EquationSymbol, ...]:
    return tuple(
        EquationSymbol(row[0], row[1], row[2] if len(row) == 3 else "dimensionless")
        for row in rows
    )


def _relation(*rows: tuple[str, str] | tuple[str, str, str]) -> EquationContract:
    return EquationContract(_symbols(*rows))


def _calculation_relation(
    *rows: tuple[str, str] | tuple[str, str, str],
) -> EquationContract:
    """Mark an existing live calculation whose worked block is incomplete."""

    return EquationContract(_symbols(*rows), publication_role="calculation")


def _result(
    result_symbol: str,
    result_unit: str,
    *rows: tuple[str, str] | tuple[str, str, str],
    substitution_role: str = "numerical",
    applicability_note_required: bool = False,
) -> EquationContract:
    return EquationContract(
        _symbols(*rows),
        result_symbol=result_symbol,
        result_unit=result_unit,
        substitution_role=substitution_role,
        publication_role="calculation",
        applicability_note_required=applicability_note_required,
    )


_CONTRACTS: dict[tuple[str, str | None], EquationContract] = {
    ("materials.concrete.fcd", "2005"): _result(
        "f<sub>cd</sub>", "MPa",
        ("f<sub>cd</sub>", "design concrete compressive strength", "MPa"),
        ("alpha<sub>cc</sub>", "concrete strength coefficient"),
        ("f<sub>ck</sub>", "characteristic concrete compressive strength", "MPa"),
        ("gamma<sub>c</sub>", "partial factor for concrete"),
    ),
    ("materials.concrete.fcd", "2023"): _result(
        "f<sub>cd</sub>", "MPa",
        ("f<sub>cd</sub>", "design concrete compressive strength", "MPa"),
        ("eta<sub>cc</sub>", "concrete strength reduction factor"),
        ("k<sub>tc</sub>", "time and sustained-loading factor"),
        ("f<sub>ck</sub>", "characteristic concrete compressive strength", "MPa"),
        ("gamma<sub>c</sub>", "partial factor for concrete"),
    ),
    ("materials.concrete.curve-2", None): _relation(
        ("sigma<sub>c</sub>", "concrete compressive stress", "MPa"),
        ("f<sub>cd</sub>", "design concrete compressive strength", "MPa"),
        ("eps<sub>c</sub>", "concrete compressive strain"),
        ("eps<sub>c2</sub>", "strain at the start of the plateau"),
        ("eps<sub>cu2</sub>", "ultimate concrete compressive strain"),
        ("n", "parabola exponent"),
    ),
    (_MATERIAL_TEMPLATE_KEY, None): _result(
        "f<sub>yd</sub>", "MPa",
        ("f<sub>yd</sub>", "design reinforcement strength", "MPa"),
        ("f<sub>ytk</sub>", "characteristic reinforcement strength", "MPa"),
        ("gamma<sub>y</sub>", "partial factor for reinforcement strength"),
    ),
    ("geometry.concrete.net-area", None): _result(
        "A<sub>c</sub>", "m2",
        ("A<sub>c</sub>", "net concrete area", "m2"),
        ("A<sub>j</sub>", "signed area contribution of ring j", "m2"),
    ),
    ("geometry.concrete.centroid-x", None): _result(
        "x<sub>c</sub>", "m",
        ("x<sub>c</sub>", "net concrete centroid x-coordinate", "m"),
        ("S<sub>x</sub>", "first moment integral of x", "m3"),
        ("A<sub>c</sub>", "net concrete area", "m2"),
    ),
    ("geometry.concrete.centroid-y", None): _result(
        "y<sub>c</sub>", "m",
        ("y<sub>c</sub>", "net concrete centroid y-coordinate", "m"),
        ("S<sub>y</sub>", "first moment integral of y", "m3"),
        ("A<sub>c</sub>", "net concrete area", "m2"),
    ),
    ("geometry.concrete.centroidal-ix", None): _result(
        "I<sub>x,c</sub>", "m4",
        ("I<sub>x,c</sub>", "centroidal second moment about x", "m4"),
        ("S<sub>yy</sub>", "origin second-moment integral of y squared", "m4"),
        ("A<sub>c</sub>", "net concrete area", "m2"),
        ("y<sub>c</sub>", "net concrete centroid y-coordinate", "m"),
    ),
    ("geometry.concrete.centroidal-iy", None): _result(
        "I<sub>y,c</sub>", "m4",
        ("I<sub>y,c</sub>", "centroidal second moment about y", "m4"),
        ("S<sub>xx</sub>", "origin second-moment integral of x squared", "m4"),
        ("A<sub>c</sub>", "net concrete area", "m2"),
        ("x<sub>c</sub>", "net concrete centroid x-coordinate", "m"),
    ),
    ("geometry.concrete.centroidal-ixy", None): _result(
        "I<sub>xy,c</sub>", "m4",
        ("I<sub>xy,c</sub>", "centroidal product moment", "m4"),
        ("S<sub>xy</sub>", "origin product-moment integral", "m4"),
        ("A<sub>c</sub>", "net concrete area", "m2"),
        ("x<sub>c</sub>", "net concrete centroid x-coordinate", "m"),
        ("y<sub>c</sub>", "net concrete centroid y-coordinate", "m"),
    ),
    ("elastic.concrete.effective-modulus", None): _result(
        "E<sub>c,eff</sub>", "MPa",
        ("E<sub>c,eff</sub>", "effective long-term concrete modulus", "MPa"),
        ("E<sub>c</sub>", "entered concrete elastic modulus", "MPa"),
        ("phi", "entered creep coefficient"),
    ),
    ("elastic.modular-ratio.short", None): _result(
        "n<sub>s,i</sub>", "dimensionless",
        ("n<sub>s,i</sub>", "short-term modular ratio for material i"),
        ("E<sub>i</sub>", "material-i elastic modulus", "MPa"),
        ("E<sub>c</sub>", "entered concrete elastic modulus", "MPa"),
    ),
    ("elastic.modular-ratio.long", None): _result(
        "n<sub>l,i</sub>", "dimensionless",
        ("n<sub>l,i</sub>", "long-term modular ratio for material i"),
        ("n<sub>s,i</sub>", "short-term modular ratio for material i"),
        ("phi", "entered creep coefficient"),
    ),
    ("prestress.initial-stress", None): _result(
        "sigma<sub>p,0,i</sub>", "MPa",
        ("sigma<sub>p,0,i</sub>", "locked-in initial stress of tendon i", "MPa"),
        ("E<sub>p,i</sub>", "elastic modulus of tendon i", "MPa"),
        ("eps<sub>p,0,i</sub>", "entered initial strain of tendon i"),
    ),
    ("prestress.element-force", None): _result(
        "F<sub>p,0,i</sub>", "kN",
        ("F<sub>p,0,i</sub>", "locked-in tensile force of tendon i", "kN"),
        ("sigma<sub>p,0,i</sub>", "locked-in initial stress of tendon i", "MPa"),
        ("A<sub>p,i</sub>", "area of tendon i", "mm2"),
    ),
    ("prestress.resultant-n", None): _result(
        "N<sub>p,0</sub>", "kN",
        ("N<sub>p,0</sub>", "locked-in tendon tensile resultant", "kN"),
        ("F<sub>p,0,i</sub>", "locked-in tensile force of tendon i", "kN"),
    ),
    ("prestress.resultant-mx", None): _result(
        "M<sub>p,x,0</sub>", "kNm",
        ("M<sub>p,x,0</sub>", "locked-in tendon moment resultant about x", "kNm"),
        ("F<sub>p,0,i</sub>", "locked-in tensile force of tendon i", "kN"),
        ("y<sub>i</sub>", "tendon-i y-coordinate about the declared origin", "m"),
    ),
    ("prestress.resultant-my", None): _result(
        "M<sub>p,y,0</sub>", "kNm",
        ("M<sub>p,y,0</sub>", "locked-in tendon moment resultant about y", "kNm"),
        ("F<sub>p,0,i</sub>", "locked-in tensile force of tendon i", "kN"),
        ("x<sub>i</sub>", "tendon-i x-coordinate about the declared origin", "m"),
    ),
    ("basis.plastic.governing-curvature", None): _relation(
        ("kappa<sub>u</sub>", "governing ultimate curvature", "1/mm"),
        ("eps<sub>cu2</sub>", "ultimate concrete compressive strain"),
        ("c", "concrete compression depth", "mm"),
        ("eps<sub>su,i</sub>", "ultimate strain of mild bar i"),
        ("d<sub>s,i</sub>", "bar-i distance from the neutral axis", "mm"),
        ("eps<sub>pu,j</sub>", "ultimate total strain of tendon j"),
        ("eps<sub>p0,j</sub>", "initial strain of tendon j"),
        ("d<sub>p,j</sub>", "tendon-j distance from the neutral axis", "mm"),
    ),
    ("basis.plastic.equilibrium", None): _relation(
        ("F<sub>c</sub>", "concrete resultant", "kN"),
        ("F<sub>s</sub>", "mild-reinforcement resultant", "kN"),
        ("F<sub>p</sub>", "prestressing-steel resultant", "kN"),
        ("N", "applied axial force", "kN"),
        ("M", "section moment resultant", "kNm"),
        ("F<sub>i</sub>", "element or material resultant i", "kN"),
        ("d<sub>i</sub>", "lever arm of resultant i", "m"),
    ),
    ("basis.fatigue.stress-range", None): _relation(
        ("Delta sigma<sub>i</sub>", "design stress range for element i", "MPa"),
        ("gamma<sub>Ff</sub>", "fatigue action factor"),
        ("sigma", "stress reconstructed by the retained elastic solver", "MPa"),
        ("long", "sustained section-action state", "kN/kNm"),
        ("short", "cyclic section-action increment", "kN/kNm"),
    ),
    ("basis.fatigue.reinforcement-miner", None): _relation(
        ("D", "reinforcement Miner damage"),
        ("n<sub>i</sub>", "applied cycles in bin i", "cycles"),
        ("N<sub>R,i</sub>", "design fatigue life for bin i", "cycles"),
    ),
    ("basis.fatigue.concrete-miner", None): _relation(
        ("D<sub>c</sub>", "concrete Miner damage"),
        ("n<sub>i</sub>", "applied cycles in bin i", "cycles"),
        ("N<sub>R,i</sub>", "concrete fatigue life for bin i", "cycles"),
    ),
    ("fatigue.reinforcement.design-stress-range", None): _result(
        "Delta sigma<sub>Ed,i</sub>", "MPa",
        (
            "Delta sigma<sub>Ed,i</sub>",
            "design reinforcement stress range for bin i",
            "MPa",
        ),
        (
            "Delta sigma<sub>Ed,el,i</sub>",
            "elastic design reinforcement stress range before bond adjustment",
            "MPa",
        ),
        (
            "sigma<sub>total,Ed,el,i</sub>",
            "elastic reinforcement stress at the action-factored fatigue state",
            "MPa",
        ),
        (
            "sigma<sub>long,i</sub>",
            "reinforcement stress at the sustained state",
            "MPa",
        ),
        ("eta<sub>b</sub>", "retained bond stress-range adjustment factor"),
        applicability_note_required=True,
    ),
    ("fatigue.reinforcement.design-resistance-range", None): _result(
        "Delta sigma<sub>Rd</sub>", "MPa",
        ("Delta sigma<sub>Rd</sub>", "design fatigue stress-range resistance", "MPa"),
        (
            "Delta sigma<sub>Rsk</sub>",
            "characteristic fatigue stress-range resistance",
            "MPa",
        ),
        ("gamma<sub>s</sub>", "partial factor for reinforcement fatigue"),
    ),
    ("fatigue.reinforcement.sn-life", "power-law"): _result(
        "N<sub>R,i</sub>", "cycles",
        ("N<sub>R,i</sub>", "design fatigue life for bin i", "cycles"),
        ("N<super>*</super>", "reference number of cycles", "cycles"),
        ("Delta sigma<sub>Rd</sub>", "design fatigue stress-range resistance", "MPa"),
        ("Delta sigma<sub>Ed,i</sub>", "design stress range for bin i", "MPa"),
        ("k", "S-N curve exponent for the retained branch"),
        applicability_note_required=True,
    ),
    ("fatigue.reinforcement.sn-life", "zero-range"): _result(
        "N<sub>R,i</sub>", "cycles",
        ("N<sub>R,i</sub>", "unbounded design fatigue life for bin i", "cycles"),
        ("Delta sigma<sub>Ed,i</sub>", "design stress range for bin i", "MPa"),
        applicability_note_required=True,
    ),
    ("fatigue.reinforcement.bin-damage", None): _result(
        "D<sub>i</sub>", "dimensionless",
        ("D<sub>i</sub>", "Miner damage contribution from bin i"),
        ("n<sub>i</sub>", "applied cycles in bin i", "cycles"),
        ("N<sub>R,i</sub>", "design fatigue life for bin i", "cycles"),
    ),
    ("fatigue.reinforcement.miner-sum", None): _result(
        "D", "dimensionless",
        ("D", "total reinforcement Miner damage"),
        ("D<sub>i</sub>", "Miner damage contribution from bin i"),
    ),
    ("fatigue.reinforcement.yield-limit", None): _result(
        "sigma<sub>Rd</sub>", "MPa",
        ("sigma<sub>Rd</sub>", "design reinforcement stress limit", "MPa"),
        (
            "f<sub>yk/proof</sub>",
            "characteristic yield or proof strength for the retained branch",
            "MPa",
        ),
        ("gamma<sub>s</sub>", "partial factor for reinforcement strength"),
        applicability_note_required=True,
    ),
    ("fatigue.reinforcement.yield-utilisation", None): _result(
        "u<sub>yield</sub>", "dimensionless",
        ("u<sub>yield</sub>", "reinforcement yield or proof-stress utilisation"),
        ("sigma<sub>Ed</sub>", "governing design reinforcement stress", "MPa"),
        ("sigma<sub>Rd</sub>", "design reinforcement stress limit", "MPa"),
    ),
    ("fatigue.reinforcement.utilisation", None): _result(
        "u", "dimensionless",
        ("u", "governing reinforcement fatigue utilisation"),
        ("D", "total reinforcement Miner damage"),
        ("u<sub>yield</sub>", "reinforcement yield or proof-stress utilisation"),
        applicability_note_required=True,
    ),
    ("fatigue.concrete.strength", "2005"): _result(
        "f<sub>cd,fat</sub>", "MPa",
        ("f<sub>cd,fat</sub>", "design concrete fatigue strength", "MPa"),
        ("k<sub>1</sub>", "concrete fatigue strength factor"),
        ("beta<sub>cc</sub>", "concrete age strength factor"),
        ("alpha<sub>cc</sub>", "concrete strength coefficient"),
        ("f<sub>ck</sub>", "characteristic concrete compressive strength", "MPa"),
        ("gamma<sub>c</sub>", "partial factor for concrete"),
    ),
    ("fatigue.concrete.strength", "2023"): _result(
        "f<sub>cd,fat</sub>", "MPa",
        ("f<sub>cd,fat</sub>", "design concrete fatigue strength", "MPa"),
        ("beta<sub>cc</sub>", "concrete age strength factor"),
        ("f<sub>ck</sub>", "characteristic concrete compressive strength", "MPa"),
        ("eta<sub>cc,fat</sub>", "concrete fatigue strength reduction factor"),
        ("gamma<sub>c</sub>", "partial factor for concrete"),
    ),
    ("fatigue.concrete.eta-cc", None): _result(
        "eta<sub>cc</sub>", "dimensionless",
        ("eta<sub>cc</sub>", "concrete compressive-strength reduction factor"),
        ("f<sub>ck</sub>", "characteristic concrete compressive strength", "MPa"),
    ),
    ("fatigue.concrete.eta-cc-fat", None): _result(
        "eta<sub>cc,fat</sub>", "dimensionless",
        ("eta<sub>cc,fat</sub>", "concrete fatigue strength reduction factor"),
        ("eta<sub>cc</sub>", "concrete compressive-strength reduction factor"),
    ),
    ("fatigue.concrete.normalised-stress", None): _result(
        "E<sub>cd,min/max</sub>", "dimensionless",
        (
            "E<sub>cd,min/max</sub>",
            "normalized minimum and maximum design concrete stresses",
        ),
        (
            "sigma<sub>c,min/max,Ed</sub>",
            "minimum and maximum design concrete compressive stresses",
            "MPa",
        ),
        ("f<sub>cd,fat</sub>", "design concrete fatigue strength", "MPa"),
        applicability_note_required=True,
    ),
    ("fatigue.concrete.equivalent", None): _result(
        "u<sub>eq</sub>", "dimensionless",
        ("u<sub>eq</sub>", "equivalent-amplitude concrete fatigue utilisation"),
        ("E<sub>cd,max</sub>", "normalized maximum design concrete stress"),
        ("E<sub>cd,min</sub>", "normalized minimum design concrete stress"),
    ),
    ("fatigue.concrete.life", "variable-compression"): _result(
        "N<sub>R,i</sub>", "cycles",
        ("N<sub>R,i</sub>", "design concrete fatigue life for bin i", "cycles"),
        (
            "log<sub>10</sub>N<sub>R,i</sub>",
            "base-10 logarithm of the design fatigue life",
        ),
        ("C", "retained concrete fatigue-life coefficient"),
        ("E<sub>cd,max</sub>", "normalized maximum design concrete stress"),
        ("sigma<sub>c,min</sub>", "minimum concrete compressive stress", "MPa"),
        ("sigma<sub>c,max</sub>", "maximum concrete compressive stress", "MPa"),
        applicability_note_required=True,
    ),
    ("fatigue.concrete.life", "zero-compression"): _result(
        "N<sub>R,i</sub>", "cycles",
        ("N<sub>R,i</sub>", "unbounded design concrete fatigue life for bin i", "cycles"),
        ("sigma<sub>c,min</sub>", "minimum concrete compressive stress", "MPa"),
        ("sigma<sub>c,max</sub>", "maximum concrete compressive stress", "MPa"),
        applicability_note_required=True,
    ),
    ("fatigue.concrete.life", "constant-compression"): _result(
        "N<sub>R,i</sub>", "cycles",
        ("N<sub>R,i</sub>", "unbounded design concrete fatigue life for bin i", "cycles"),
        ("sigma<sub>c,min</sub>", "minimum concrete compressive stress", "MPa"),
        ("sigma<sub>c,max</sub>", "maximum concrete compressive stress", "MPa"),
        applicability_note_required=True,
    ),
    ("fatigue.concrete.bin-damage", None): _result(
        "D<sub>i</sub>", "dimensionless",
        ("D<sub>i</sub>", "concrete Miner damage contribution from bin i"),
        ("n<sub>i</sub>", "applied cycles in bin i", "cycles"),
        ("N<sub>R,i</sub>", "design concrete fatigue life for bin i", "cycles"),
    ),
    ("fatigue.concrete.miner-sum", None): _result(
        "D", "dimensionless",
        ("D", "total concrete Miner damage"),
        ("D<sub>i</sub>", "concrete Miner damage contribution from bin i"),
    ),
    ("fatigue.concrete.stress-utilisation", None): _result(
        "u<sub>sigma</sub>", "dimensionless",
        ("u<sub>sigma</sub>", "concrete compressive-stress utilisation"),
        ("E<sub>cd,max</sub>", "normalized maximum design concrete stress"),
    ),
    ("fatigue.concrete.utilisation", None): _result(
        "u", "dimensionless",
        ("u", "governing concrete fatigue utilisation"),
        ("D", "total concrete Miner damage"),
        ("u<sub>sigma</sub>", "concrete compressive-stress utilisation"),
        ("u<sub>eq</sub>", "equivalent-amplitude concrete fatigue utilisation"),
        ("u<sub>bound</sub>", "retained bounded-search fatigue utilisation"),
        applicability_note_required=True,
    ),
    ("basis.detailing.transverse-ratios", None): _relation(
        ("rho<sub>w</sub>", "shear-link reinforcement ratio"),
        ("A<sub>sw</sub>", "effective shear-link area", "mm2"),
        ("s", "longitudinal link spacing", "mm"),
        ("b<sub>w</sub>", "effective web breadth", "mm"),
        ("rho<sub>w,T</sub>", "torsion-link reinforcement ratio"),
        ("A<sub>leg</sub>", "area of one effective closed-link leg", "mm2"),
        ("t<sub>ef</sub>", "effective torsion-wall thickness", "mm"),
    ),
    ("detailing.minimum.area-2005", None): _result(
        "A<sub>s,min</sub>", "mm2",
        ("A<sub>s,min</sub>", "required minimum longitudinal reinforcement", "mm2"),
        ("f<sub>ctm</sub>", "mean concrete tensile strength", "MPa"),
        ("f<sub>yk</sub>", "characteristic reinforcement yield strength", "MPa"),
        ("b<sub>t</sub>", "mean width of the tension zone", "mm"),
        ("d", "effective depth", "mm"),
    ),
    ("detailing.minimum.tension-2023", None): _result(
        "R<sub>nom</sub>", "kN",
        ("R<sub>nom</sub>", "nominal reinforcement tensile resistance", "kN"),
        ("A<sub>s,i</sub>", "area of reinforcement element i", "mm2"),
        ("f<sub>yk,i</sub>", "characteristic yield strength of element i", "MPa"),
        ("R<sub>cr</sub>", "gross-section cracking tension", "kN"),
        ("A<sub>c</sub>", "gross concrete area", "mm2"),
        ("f<sub>ctm</sub>", "mean concrete tensile strength", "MPa"),
    ),
    ("detailing.minimum.cracking-factor-2023", None): _result(
        "lambda<sub>cr</sub>", "dimensionless",
        ("lambda<sub>cr</sub>", "factor from the entered bending action to first cracking"),
        ("f<sub>ctm</sub>", "mean concrete tensile strength", "MPa"),
        ("sigma<sub>N,v</sub>", "axial stress at the governing concrete vertex", "MPa"),
        ("sigma<sub>M,v</sub>", "entered bending-action stress at that vertex", "MPa"),
        ("M<sub>cr</sub>", "resulting cracking moment", "kNm"),
    ),
    ("detailing.minimum.nominal-equilibrium-2023", None): _result(
        "Delta N", "kN",
        ("Delta N", "retained final nominal-section axial residual", "kN"),
        ("N<sub>int</sub>", "retained internal nominal axial force", "kN"),
        ("N<sub>target</sub>", "requested nominal axial force", "kN"),
    ),
    ("detailing.minimum.bending-2023", None): _result(
        "M<sub>cr</sub>/M<sub>R,nom</sub>", "dimensionless",
        ("M<sub>R,nom</sub>", "nominal bending resistance", "kNm"),
        ("M<sub>cr</sub>", "cracking moment", "kNm"),
        ("M<sub>cr</sub>/M<sub>R,nom</sub>", "minimum-reinforcement utilisation"),
        ("N<sub>Ed</sub>", "applied design axial force", "kN"),
    ),
    ("detailing.links.minimum-ratio", None): _result(
        "rho<sub>w,min</sub>", "dimensionless",
        ("rho<sub>w,min</sub>", "minimum shear-link ratio"),
        ("f<sub>ck</sub>", "characteristic concrete compressive strength", "MPa"),
        ("f<sub>ywk</sub>", "characteristic link yield strength", "MPa"),
    ),
    ("detailing.links.provided-ratio", "shear"): _result(
        "rho<sub>w</sub>", "dimensionless",
        ("rho<sub>w</sub>", "provided vertical shear-link ratio"),
        ("n<sub>leg</sub>", "number of effective vertical link legs"),
        ("A<sub>leg</sub>", "area of one link leg", "mm2"),
        ("s", "longitudinal link spacing", "mm"),
        ("b<sub>w</sub>", "effective web breadth", "mm"),
        ("rho<sub>w,min</sub>", "minimum link ratio"),
    ),
    ("detailing.links.provided-ratio", "torsion"): _result(
        "rho<sub>w,T</sub>", "dimensionless",
        ("rho<sub>w,T</sub>", "provided closed torsion-link ratio"),
        ("A<sub>leg</sub>", "area of one closed-link leg", "mm2"),
        ("s", "longitudinal link spacing", "mm"),
        ("t<sub>ef</sub>", "effective torsion wall thickness", "mm"),
        ("rho<sub>w,min</sub>", "minimum link ratio"),
    ),
    ("detailing.links.spacing-limit", "longitudinal"): _result(
        "s<sub>l,max</sub>", "mm",
        ("s<sub>l,max</sub>", "maximum longitudinal shear-link spacing", "mm"),
        ("d", "effective depth", "mm"),
        ("s<sub>l</sub>", "provided longitudinal link spacing", "mm"),
    ),
    ("detailing.links.spacing-limit", "transverse"): _result(
        "s<sub>t,max</sub>", "mm",
        ("s<sub>t,max</sub>", "maximum transverse distance between link legs", "mm"),
        ("d", "effective depth", "mm"),
        ("s<sub>t</sub>", "provided transverse distance between legs", "mm"),
    ),
    ("detailing.links.spacing-limit", "torsion"): _result(
        "s<sub>max</sub>", "mm",
        ("s<sub>max</sub>", "maximum longitudinal closed-link spacing", "mm"),
        ("u<sub>k</sub>", "torsion centre-line perimeter", "mm"),
        ("s", "provided longitudinal link spacing", "mm"),
    ),
    ("detailing.clear-spacing.distance", None): _result(
        "c<sub>12</sub>", "mm",
        ("r<sub>12</sub>", "centre-to-centre distance of the pair", "mm"),
        ("Delta x", "x-coordinate difference", "mm"),
        ("Delta y", "y-coordinate difference", "mm"),
        ("phi<sub>1</sub>", "first element detailing diameter", "mm"),
        ("phi<sub>2</sub>", "second element detailing diameter", "mm"),
        ("c<sub>12</sub>", "clear edge-to-edge distance", "mm"),
    ),
    ("detailing.clear-spacing.requirement", None): _result(
        "c<sub>req</sub>", "mm",
        ("c<sub>req</sub>", "required clear reinforcement spacing", "mm"),
        ("phi<sub>max</sub>", "larger detailing diameter of the pair", "mm"),
        ("D<sub>upper</sub>", "upper aggregate size", "mm"),
    ),
    ("plastic.worked.strain-plane", None): _result(
        "eps<sub>sec</sub>", "dimensionless",
        ("eps<sub>sec</sub>", "section strain, compression positive"),
        ("eps<sub>0</sub>", "retained strain-plane offset"),
        ("g<sub>x</sub>", "retained strain gradient in x", "1/m"),
        ("g<sub>y</sub>", "retained strain gradient in y", "1/m"),
        ("x", "section x-coordinate", "m"),
        ("y", "section y-coordinate", "m"),
    ),
    ("plastic.worked.curvature-candidate", None): _result(
        "kappa<sub>i</sub>", "1/m",
        ("kappa<sub>i</sub>", "ultimate-curvature candidate i", "1/m"),
        ("eps<sub>lim,i</sub>", "retained effective strain limit"),
        ("d<sub>i</sub>", "positive distance from the neutral axis", "m"),
    ),
    ("plastic.worked.curvature-selection", None): _result(
        "kappa<sub>u</sub>", "1/m",
        ("kappa<sub>u</sub>", "governing ultimate curvature", "1/m"),
        ("kappa<sub>c</sub>", "concrete-crushing curvature candidate", "1/m"),
        ("kappa<sub>s,i</sub>", "bar rupture curvature candidate i", "1/m"),
        ("kappa<sub>p,j</sub>", "tendon rupture curvature candidate j", "1/m"),
    ),
    ("plastic.worked.axial-equilibrium", None): _result(
        "N<sub>int</sub>", "kN",
        ("N<sub>int</sub>", "accepted internal axial resultant", "kN"),
        ("F<sub>c</sub>", "concrete axial resultant", "kN"),
        ("F<sub>s</sub>", "mild-reinforcement axial resultant", "kN"),
        ("F<sub>p</sub>", "prestressing-steel axial resultant", "kN"),
        ("residual", "signed axial-equilibrium residual", "kN"),
    ),
    ("plastic.worked.moment-x", None): _result(
        "M<sub>x</sub>", "kNm",
        ("M<sub>x</sub>", "accepted section moment about x", "kNm"),
        ("M<sub>c,x</sub>", "concrete moment contribution about x", "kNm"),
        ("M<sub>s,x</sub>", "mild-reinforcement moment contribution about x", "kNm"),
        ("M<sub>p,x</sub>", "prestressing-steel moment contribution about x", "kNm"),
    ),
    ("plastic.worked.moment-y", None): _result(
        "M<sub>y</sub>", "kNm",
        ("M<sub>y</sub>", "accepted section moment about y", "kNm"),
        ("M<sub>c,y</sub>", "concrete moment contribution about y", "kNm"),
        ("M<sub>s,y</sub>", "mild-reinforcement moment contribution about y", "kNm"),
        ("M<sub>p,y</sub>", "prestressing-steel moment contribution about y", "kNm"),
    ),
    ("plastic.worked.element-force", None): _result(
        "F<sub>i</sub>", "kN",
        ("F<sub>i</sub>", "tension-positive force of reinforcement element i", "kN"),
        ("sigma<sub>i</sub>", "retained material stress of element i", "MPa"),
        ("A<sub>i</sub>", "entered area of element i", "mm2"),
    ),
    ("elastic.long.stress-plane", None): _result(
        "sigma<sub>ref</sub>", "kN/m2",
        ("sigma<sub>ref</sub>", "raw Ec=1 reference stress", "kN/m2"),
        ("sigma<sub>0</sub>", "retained reference-stress offset", "kN/m2"),
        ("g<sub>x</sub>", "retained reference-stress gradient in x", "kN/m3"),
        ("g<sub>y</sub>", "retained reference-stress gradient in y", "kN/m3"),
        ("x", "section x-coordinate", "m"),
        ("y", "section y-coordinate", "m"),
    ),
    ("elastic.instantaneous.stress-plane", None): _result(
        "sigma<sub>ref</sub>", "kN/m2",
        ("sigma<sub>ref</sub>", "raw Ec=1 reference stress", "kN/m2"),
        ("sigma<sub>0</sub>", "retained reference-stress offset", "kN/m2"),
        ("g<sub>x</sub>", "retained reference-stress gradient in x", "kN/m3"),
        ("g<sub>y</sub>", "retained reference-stress gradient in y", "kN/m3"),
        ("x", "section x-coordinate", "m"),
        ("y", "section y-coordinate", "m"),
    ),
    ("elastic.long.equilibrium-n", None): _result(
        "N<sub>int</sub>", "kN",
        ("N<sub>int</sub>", "accepted long-term internal axial resultant", "kN"),
        ("J", "retained final transformed equilibrium row", "mixed section units"),
        ("q", "retained raw reference-stress plane", "mixed stress units"),
        ("target", "solver target resultant", "kN"),
        ("residual", "signed final equilibrium residual", "kN"),
    ),
    ("elastic.long.equilibrium-mx", None): _result(
        "M<sub>x,int</sub>", "kNm",
        ("M<sub>x,int</sub>", "accepted long-term internal moment about x", "kNm"),
        ("J", "retained final transformed equilibrium row", "mixed section units"),
        ("q", "retained raw reference-stress plane", "mixed stress units"),
        ("target", "solver target resultant", "kNm"),
        ("residual", "signed final equilibrium residual", "kNm"),
    ),
    ("elastic.long.equilibrium-my", None): _result(
        "M<sub>y,int</sub>", "kNm",
        ("M<sub>y,int</sub>", "accepted long-term internal moment about y", "kNm"),
        ("J", "retained final transformed equilibrium row", "mixed section units"),
        ("q", "retained raw reference-stress plane", "mixed stress units"),
        ("target", "solver target resultant", "kNm"),
        ("residual", "signed final equilibrium residual", "kNm"),
    ),
    ("elastic.instantaneous.equilibrium-n", None): _result(
        "N<sub>int</sub>", "kN",
        ("N<sub>int</sub>", "accepted instantaneous internal axial resultant", "kN"),
        ("J", "retained final transformed equilibrium row", "mixed section units"),
        ("q", "retained raw reference-stress plane", "mixed stress units"),
        ("target", "solver target resultant", "kN"),
        ("residual", "signed final equilibrium residual", "kN"),
    ),
    ("elastic.instantaneous.equilibrium-mx", None): _result(
        "M<sub>x,int</sub>", "kNm",
        ("M<sub>x,int</sub>", "accepted instantaneous internal moment about x", "kNm"),
        ("J", "retained final transformed equilibrium row", "mixed section units"),
        ("q", "retained raw reference-stress plane", "mixed stress units"),
        ("target", "solver target resultant", "kNm"),
        ("residual", "signed final equilibrium residual", "kNm"),
    ),
    ("elastic.instantaneous.equilibrium-my", None): _result(
        "M<sub>y,int</sub>", "kNm",
        ("M<sub>y,int</sub>", "accepted instantaneous internal moment about y", "kNm"),
        ("J", "retained final transformed equilibrium row", "mixed section units"),
        ("q", "retained raw reference-stress plane", "mixed stress units"),
        ("target", "solver target resultant", "kNm"),
        ("residual", "signed final equilibrium residual", "kNm"),
    ),
    ("elastic.combined.reduction-factor", None): _result(
        "r", "dimensionless",
        ("r", "long-term steel-stress reduction factor"),
        ("n<sub>s</sub>", "short-term modular ratio"),
        ("n<sub>l</sub>", "long-term modular ratio"),
    ),
    ("elastic.combined.reduced-long-stress", None): _result(
        "sigma<sub>s2,i</sub>", "MPa",
        ("sigma<sub>s2,i</sub>", "reduced passive long-term stress", "MPa"),
        ("r", "long-term steel-stress reduction factor"),
        ("sigma<sub>s1,passive,i</sub>", "passive long-term element stress", "MPa"),
    ),
    ("elastic.combined.neutralising-n", None): _result(
        "N<sub>neu</sub>", "kN",
        ("N<sub>neu</sub>", "neutralising axial resultant", "kN"),
        ("sigma<sub>s2,i</sub>", "reduced passive long-term stress", "MPa"),
        ("A<sub>i</sub>", "element area", "mm2"),
    ),
    ("elastic.combined.neutralising-mx", None): _result(
        "M<sub>neu,x</sub>", "kNm",
        ("M<sub>neu,x</sub>", "neutralising moment about x", "kNm"),
        ("sigma<sub>s2,i</sub>", "reduced passive long-term stress", "MPa"),
        ("A<sub>i</sub>", "element area", "mm2"),
        ("y<sub>i</sub>", "element y-coordinate", "mm"),
    ),
    ("elastic.combined.neutralising-my", None): _result(
        "M<sub>neu,y</sub>", "kNm",
        ("M<sub>neu,y</sub>", "neutralising moment about y", "kNm"),
        ("sigma<sub>s2,i</sub>", "reduced passive long-term stress", "MPa"),
        ("A<sub>i</sub>", "element area", "mm2"),
        ("x<sub>i</sub>", "element x-coordinate", "mm"),
    ),
    ("elastic.combined.target-n", None): _result(
        "N<sub>target</sub>", "kN",
        ("N<sub>target</sub>", "instantaneous axial target after neutralisation", "kN"),
        ("N<sub>comb</sub>", "combined target before neutralisation", "kN"),
        ("N<sub>neu</sub>", "retained neutralising resultant", "kN"),
    ),
    ("elastic.combined.target-mx", None): _result(
        "M<sub>x,target</sub>", "kNm",
        (
            "M<sub>x,target</sub>",
            "instantaneous moment-x target after neutralisation",
            "kNm",
        ),
        ("M<sub>x,comb</sub>", "combined target before neutralisation", "kNm"),
        ("M<sub>x,neu</sub>", "retained neutralising resultant", "kNm"),
    ),
    ("elastic.combined.target-my", None): _result(
        "M<sub>y,target</sub>", "kNm",
        (
            "M<sub>y,target</sub>",
            "instantaneous moment-y target after neutralisation",
            "kNm",
        ),
        ("M<sub>y,comb</sub>", "combined target before neutralisation", "kNm"),
        ("M<sub>y,neu</sub>", "retained neutralising resultant", "kNm"),
    ),
    ("elastic.combined.total-stress", None): _result(
        "sigma<sub>total,i</sub>", "MPa",
        ("sigma<sub>total,i</sub>", "total retained element stress", "MPa"),
        ("sigma<sub>s2,i</sub>", "reduced passive long-term stress", "MPa"),
        ("sigma<sub>RST1,i</sub>", "instantaneous response stress", "MPa"),
        ("sigma<sub>p0,i</sub>", "locked-in prestress", "MPa"),
    ),
    ("elastic.combined.difference-stress", None): _result(
        "sigma<sub>DIF,i</sub>", "MPa",
        ("sigma<sub>DIF,i</sub>", "total-minus-long element stress", "MPa"),
        ("sigma<sub>total,i</sub>", "total retained element stress", "MPa"),
        ("sigma<sub>long,i</sub>", "reported long-term element stress", "MPa"),
    ),
    ("shear.2023.effective-span", None): _result(
        "a<sub>cs</sub>", "mm",
        ("a<sub>cs</sub>", "effective shear span", "mm"),
        ("M<sub>Ed</sub>", "applied design moment", "kNm"),
        ("V<sub>Ed</sub>", "applied design shear", "kN"),
        ("d", "effective depth", "mm"),
    ),
    ("shear.2023.axial-factor", None): _result(
        "k<sub>vp</sub>d", "mm",
        ("k<sub>vp</sub>", "action-dependent shear-depth factor"),
        ("d", "effective depth", "mm"),
        ("a<sub>cs</sub>", "effective shear span", "mm"),
        ("N<sub>Ed</sub>", "applied design axial force, tension positive", "kN"),
        ("V<sub>Ed</sub>", "applied design shear", "kN"),
        ("k<sub>vp</sub>d", "modified depth used in the basic resistance", "mm"),
    ),
    ("shear.2023.tau-basic", None): _result(
        "tau<sub>Rd,c</sub>", "MPa",
        ("tau<sub>Rd,c</sub>", "basic shear-stress resistance", "MPa"),
        ("gamma<sub>v</sub>", "partial factor for shear resistance"),
        ("rho<sub>l</sub>", "longitudinal reinforcement ratio"),
        ("f<sub>ck</sub>", "characteristic concrete compressive strength", "MPa"),
        ("d<sub>dg</sub>", "aggregate-size parameter", "mm"),
        ("k<sub>vp</sub>d", "modified effective depth", "mm"),
    ),
    ("shear.2023.tau-minimum", None): _result(
        "tau<sub>Rd,c,min</sub>", "MPa",
        ("tau<sub>Rd,c,min</sub>", "minimum shear-stress resistance", "MPa"),
        ("gamma<sub>v</sub>", "partial factor for shear resistance"),
        ("f<sub>ck</sub>", "characteristic concrete compressive strength", "MPa"),
        ("f<sub>yd</sub>", "design reinforcement strength", "MPa"),
        ("d<sub>dg</sub>", "aggregate-size parameter", "mm"),
        ("d", "effective depth", "mm"),
    ),
    ("shear.2023.vrdc", None): _result(
        "V<sub>Rd,c</sub>", "kN",
        ("V<sub>Rd,c</sub>", "design shear resistance without links", "kN"),
        ("tau<sub>Rd,c</sub>", "basic shear-stress resistance", "MPa"),
        ("tau<sub>Rd,c,min</sub>", "minimum shear-stress resistance", "MPa"),
        ("b<sub>w</sub>", "effective web breadth", "mm"),
        ("z", "internal lever arm", "mm"),
    ),
    ("shear.2023.utilisation", None): _result(
        "utilisation", "dimensionless",
        ("V<sub>Ed</sub>", "absolute applied design shear", "kN"),
        ("V<sub>Rd,c</sub>", "design shear resistance without links", "kN"),
        ("utilisation", "demand divided by resistance"),
    ),
    ("shear.2005.stress-basic", None): _result(
        "v", "MPa",
        ("v", "basic design shear stress", "MPa"),
        ("C<sub>Rd,c</sub>", "concrete shear coefficient"),
        ("k", "size-effect factor"),
        ("rho<sub>l</sub>", "longitudinal reinforcement ratio"),
        ("f<sub>ck</sub>", "characteristic concrete compressive strength", "MPa"),
        ("k<sub>1</sub>", "axial-stress coefficient"),
        ("sigma<sub>cp</sub>", "concrete axial stress, compression positive", "MPa"),
    ),
    ("shear.2005.stress-minimum", None): _result(
        "v<sub>min,eff</sub>", "MPa",
        ("v<sub>min,eff</sub>", "effective minimum design shear stress", "MPa"),
        ("v<sub>min</sub>", "minimum shear-stress term", "MPa"),
        ("k<sub>1</sub>", "axial-stress coefficient"),
        ("sigma<sub>cp</sub>", "concrete axial stress, compression positive", "MPa"),
    ),
    ("shear.2005.vrdc", None): _result(
        "V<sub>Rd,c</sub>", "kN",
        ("V<sub>Rd,c</sub>", "design shear resistance without links", "kN"),
        ("v", "basic design shear stress", "MPa"),
        ("v<sub>min,eff</sub>", "effective minimum shear stress", "MPa"),
        ("b<sub>w</sub>", "effective web breadth", "mm"),
        ("d", "effective depth", "mm"),
    ),
    ("shear.2005.utilisation", None): _result(
        "utilisation", "dimensionless",
        ("V<sub>Ed</sub>", "absolute applied design shear", "kN"),
        ("V<sub>Rd,c</sub>", "design shear resistance without links", "kN"),
        ("utilisation", "demand divided by resistance"),
    ),
    ("shear.links.tau-yield", None): _result(
        "tau<sub>Rd,sy</sub>", "MPa",
        ("tau<sub>Rd,sy</sub>", "link-yield shear-stress resistance", "MPa"),
        ("rho<sub>w</sub>", "shear-link reinforcement ratio"),
        ("f<sub>ywd</sub>", "design link yield strength", "MPa"),
        ("theta", "compression-field angle", "degrees"),
    ),
    ("shear.links.sigma-field", None): _result(
        "sigma<sub>cd</sub>", "MPa",
        ("sigma<sub>cd</sub>", "compression-field stress", "MPa"),
        ("tau<sub>Ed</sub>", "applied design shear stress", "MPa"),
        ("theta", "compression-field angle", "degrees"),
        ("nu", "compression-field strength factor"),
        ("f<sub>cd</sub>", "design concrete compressive strength", "MPa"),
    ),
    ("shear.links.vrds", "2023"): _result(
        "V<sub>Rd,s</sub>", "kN",
        ("V<sub>Rd,s</sub>", "link-yield shear resistance", "kN"),
        ("tau<sub>Rd,sy</sub>", "link-yield shear-stress resistance", "MPa"),
        ("b<sub>w</sub>", "effective web breadth", "mm"),
        ("z", "internal lever arm", "mm"),
    ),
    ("shear.links.vrds", "2005"): _result(
        "V<sub>Rd,s</sub>", "kN",
        ("V<sub>Rd,s</sub>", "link-yield shear resistance", "kN"),
        ("A<sub>sw</sub>/s", "effective link area per spacing", "mm2/mm"),
        ("z", "internal lever arm", "mm"),
        ("f<sub>ywd</sub>", "design link yield strength", "MPa"),
        ("theta", "compression-strut angle", "degrees"),
    ),
    ("shear.links.vrdmax", "2023"): _result(
        "V<sub>Rd,max</sub>", "kN",
        ("V<sub>Rd,max</sub>", "compression-field shear resistance", "kN"),
        ("nu f<sub>cd</sub>", "compression-field stress limit", "MPa"),
        ("b<sub>w</sub>", "effective web breadth", "mm"),
        ("z", "internal lever arm", "mm"),
        ("theta", "compression-field angle", "degrees"),
    ),
    ("shear.links.vrdmax", "2005"): _result(
        "V<sub>Rd,max</sub>", "kN",
        ("V<sub>Rd,max</sub>", "concrete-strut shear resistance", "kN"),
        ("alpha<sub>cw</sub>", "compression-chord factor"),
        ("b<sub>w</sub>", "effective web breadth", "mm"),
        ("z", "internal lever arm", "mm"),
        ("nu<sub>1</sub>", "strut effectiveness factor"),
        ("f<sub>cd</sub>", "design concrete compressive strength", "MPa"),
        ("theta", "compression-strut angle", "degrees"),
    ),
    ("shear.links.vrd", None): _result(
        "V<sub>Rd</sub>", "kN",
        ("V<sub>Rd</sub>", "governing design shear resistance with links", "kN"),
        ("V<sub>Rd,s</sub>", "link-yield shear resistance", "kN"),
        ("V<sub>Rd,max</sub>", "concrete compression resistance", "kN"),
    ),
    ("shear.links.utilisation", None): _result(
        "utilisation", "dimensionless",
        ("V<sub>Ed</sub>", "absolute applied design shear", "kN"),
        ("V<sub>Rd</sub>", "governing design shear resistance", "kN"),
        ("utilisation", "demand divided by resistance"),
    ),
    ("shear.chord.demand", "2005"): _result(
        "M<sub>Ed,total</sub>", "kNm",
        ("M<sub>Ed,total</sub>", "total longitudinal-chord demand", "kNm"),
        ("M<sub>Ed</sub>", "bending demand on the chord", "kNm"),
        ("Delta F<sub>td</sub>", "shear-induced longitudinal tension", "kN"),
        ("F<sub>td,T</sub>", "distributed torsion longitudinal force", "kN"),
        ("z", "internal lever arm", "m"),
    ),
    ("shear.chord.demand", "2023"): _result(
        "M<sub>Ed,total</sub>", "kNm",
        ("M<sub>Ed,total</sub>", "total longitudinal-chord demand", "kNm"),
        ("M<sub>Ed</sub>", "bending demand on the chord", "kNm"),
        ("N<sub>Vd</sub>", "shear-induced longitudinal force", "kN"),
        ("F<sub>td,T</sub>", "distributed torsion longitudinal force", "kN"),
        ("z", "internal lever arm", "m"),
    ),
    ("shear.chord.utilisation", None): _result(
        "utilisation", "dimensionless",
        ("M<sub>Ed,total</sub>", "total longitudinal-chord demand", "kNm"),
        ("M<sub>Rd</sub>", "available chord bending resistance", "kNm"),
        ("utilisation", "demand divided by resistance"),
    ),
    ("combined.dk-na.sum", None): _result(
        "sum(S<sub>Ed</sub>/S<sub>Rd</sub>)", "dimensionless",
        ("r<sub>M</sub>", "bending utilisation with axial force folded in"),
        ("r<sub>V</sub>", "stand-alone shear utilisation"),
        ("r<sub>T</sub>", "stand-alone torsion utilisation"),
        ("sum(S<sub>Ed</sub>/S<sub>Rd</sub>)", "governing DK NA interaction sum"),
        applicability_note_required=True,
    ),
    ("combined.crushing.interaction", None): _result(
        "interaction", "dimensionless",
        ("T<sub>Ed</sub>", "applied design torsion", "kNm"),
        ("T<sub>Rd,max</sub>", "torsion concrete-strut resistance", "kNm"),
        ("V<sub>Ed</sub>", "applied design shear", "kN"),
        ("V<sub>Rd,max</sub>", "shear concrete-strut resistance", "kN"),
        ("interaction", "combined concrete-strut interaction value"),
    ),
    ("combined.stirrup.utilisation", None): _result(
        "closed-stirrup utilisation", "dimensionless",
        ("shear share", "fraction of closed-stirrup capacity used by shear"),
        ("torsion share", "fraction of closed-stirrup capacity used by torsion"),
        ("closed-stirrup utilisation", "sum of the credited shear and torsion shares"),
    ),
    ("combined.chord.demand", None): _result(
        "M<sub>Ed,total</sub>", "kNm",
        ("M<sub>Ed,total</sub>", "total longitudinal-chord demand", "kNm"),
        ("M<sub>Ed</sub>", "bending demand on the chord", "kNm"),
        ("Delta F<sub>td</sub>", "shear-induced longitudinal tension", "kN"),
        ("F<sub>td,T</sub>", "distributed torsion longitudinal force", "kN"),
        ("z", "internal lever arm", "m"),
    ),
    ("combined.chord.utilisation", None): _result(
        "utilisation", "dimensionless",
        ("M<sub>Ed,total</sub>", "total longitudinal-chord demand", "kNm"),
        ("M<sub>Rd</sub>", "available chord bending resistance", "kNm"),
        ("utilisation", "demand divided by resistance"),
    ),
    ("torsion.off-axis-chord.demand", None): _result(
        "M<sub>Ed,total</sub>", "kNm",
        ("M<sub>Ed,total</sub>", "total off-axis chord demand", "kNm"),
        ("M<sub>Ed</sub>", "bending demand on the off-axis chord", "kNm"),
        ("F<sub>td,T</sub>", "distributed torsion longitudinal force", "kN"),
        ("z", "internal lever arm", "m"),
    ),
    ("torsion.off-axis-chord.utilisation", None): _result(
        "utilisation", "dimensionless",
        ("M<sub>Ed,total</sub>", "total off-axis chord demand", "kNm"),
        ("M<sub>Rd</sub>", "available conditional chord resistance", "kNm"),
        ("utilisation", "demand divided by resistance"),
    ),
    ("torsion.subtube.governing-utilisation", None): _result(
        "governing utilisation", "dimensionless",
        ("T<sub>Ed,i</sub>", "torsion assigned to sub-tube i", "kNm"),
        ("T<sub>Rd,i</sub>", "torsion resistance of sub-tube i", "kNm"),
        ("governing utilisation", "largest sub-tube demand/resistance ratio"),
    ),
    ("torsion.subtube.stiffness-share", None): _result(
        "lambda<sub>i</sub>", "dimensionless",
        ("lambda<sub>i</sub>", "fraction of applied torque assigned to sub-tube i"),
        ("C<sub>i</sub>", "uncracked torsional stiffness of sub-tube i"),
        ("&#8721; C<sub>j</sub>", "sum of positive sub-tube torsional stiffnesses"),
    ),
    ("torsion.subtube.torque-share", None): _result(
        "T<sub>Ed,i</sub>", "kNm",
        ("T<sub>Ed,i</sub>", "torsion assigned to sub-tube i", "kNm"),
        ("lambda<sub>i</sub>", "stiffness-proportional torque fraction"),
        ("T<sub>Ed</sub>", "applied design torsion", "kNm"),
    ),
    ("torsion.shear.crushing-interaction", None): _result(
        "interaction", "dimensionless",
        ("T<sub>Ed</sub>", "applied design torsion", "kNm"),
        ("T<sub>Rd,max</sub>", "torsion concrete-strut resistance", "kNm"),
        ("V<sub>Ed</sub>", "applied design shear", "kN"),
        ("V<sub>Rd,max</sub>", "shear concrete-strut resistance", "kN"),
        ("interaction", "combined concrete-strut interaction value"),
    ),
    ("torsion.resistance.steel", None): _result(
        "T<sub>Rd,s</sub>", "kNm",
        ("T<sub>Rd,s</sub>", "closed-link torsion resistance", "kNm"),
        ("A<sub>sw</sub>/s", "effective closed-link area per spacing", "mm2/mm"),
        ("A<sub>k</sub>", "area enclosed by the torsion centre-line", "m2"),
        ("f<sub>ywd</sub>", "design link yield strength", "MPa"),
        ("theta", "compression-strut angle", "degrees"),
    ),
    ("torsion.resistance.crushing", None): _result(
        "T<sub>Rd,max</sub>", "kNm",
        ("T<sub>Rd,max</sub>", "torsion concrete-strut resistance", "kNm"),
        ("nu", "torsion strut effectiveness factor"),
        ("alpha<sub>cw</sub>", "compression-chord factor"),
        ("f<sub>cd</sub>", "design concrete compressive strength", "MPa"),
        ("A<sub>k</sub>", "area enclosed by the torsion centre-line", "m2"),
        ("t<sub>ef</sub>", "effective torsion-wall thickness", "m"),
        ("theta", "compression-strut angle", "degrees"),
    ),
    ("torsion.resistance.governing", None): _result(
        "T<sub>Rd</sub>", "kNm",
        ("T<sub>Rd</sub>", "governing design torsion resistance", "kNm"),
        ("T<sub>Rd,s</sub>", "closed-link torsion resistance", "kNm"),
        ("T<sub>Rd,max</sub>", "torsion concrete-strut resistance", "kNm"),
    ),
    ("torsion.cracking.fctd", None): _result(
        "f<sub>ctd</sub>", "MPa",
        ("f<sub>ctd</sub>", "design concrete tensile strength", "MPa"),
        ("f<sub>ctk,0.05</sub>", "lower characteristic concrete tensile strength", "MPa"),
        ("gamma<sub>ct</sub>", "partial factor for concrete tension"),
    ),
    ("torsion.cracking.resistance", None): _result(
        "T<sub>Rd,c</sub>", "kNm",
        ("T<sub>Rd,c</sub>", "torsional cracking resistance", "kNm"),
        ("A<sub>k</sub>", "area enclosed by the torsion centre-line", "m2"),
        ("t<sub>ef</sub>", "effective torsion-wall thickness", "m"),
        ("f<sub>ctd</sub>", "design concrete tensile strength", "MPa"),
    ),
    ("torsion.utilisation", None): _result(
        "utilisation", "dimensionless",
        ("T<sub>Ed</sub>", "applied design torsion", "kNm"),
        ("T<sub>Rd</sub>", "governing design torsion resistance", "kNm"),
        ("utilisation", "demand divided by resistance"),
    ),
    ("torsion.longitudinal-steel", None): _result(
        "sum A<sub>sl</sub>", "mm2",
        ("sum A<sub>sl</sub>", "required longitudinal torsion reinforcement", "mm2"),
        ("T<sub>Ed</sub>", "applied design torsion", "kNm"),
        ("u<sub>k</sub>", "perimeter of the torsion centre-line", "m"),
        ("theta", "compression-strut angle", "degrees"),
        ("A<sub>k</sub>", "area enclosed by the torsion centre-line", "m2"),
        ("f<sub>yd</sub>", "design longitudinal-steel strength", "MPa"),
    ),
    ("torsion.minimum-reinforcement.screen", None): _result(
        "screen", "dimensionless",
        ("T<sub>Ed</sub>", "applied design torsion", "kNm"),
        ("T<sub>Rd,c</sub>", "torsional cracking resistance", "kNm"),
        ("V<sub>Ed</sub>", "applied design shear", "kN"),
        ("V<sub>Rd,c</sub>", "shear resistance without links", "kN"),
        ("screen", "minimum-reinforcement interaction value"),
    ),
    ("cracking.threshold", "ordinary"): _result(
        "lambda<sub>cr</sub>", "dimensionless",
        ("lambda<sub>cr</sub>", "load factor to first cracking"),
        ("f<sub>ct,eff</sub>", "effective concrete tensile strength", "MPa"),
        ("sigma<sub>ct,I</sub>", "Stage-I extreme tensile stress", "MPa"),
    ),
    ("cracking.threshold", "prestress"): _relation(
        ("lambda<sub>cr</sub>", "external-action factor to first cracking"),
        (
            "sigma<sub>pre,i</sub>",
            "fixed prestress concrete tensile stress at fibre i",
            "MPa",
        ),
        (
            "sigma<sub>ext,i</sub>",
            "external-action concrete tensile stress increment at fibre i",
            "MPa",
        ),
        ("f<sub>ct,eff</sub>", "effective concrete tensile strength", "MPa"),
    ),
    ("crack.effective-area.2005", "fine"): _result(
        "h<sub>c,eff</sub>", "mm",
        ("h<sub>c,eff</sub>", "selected effective tension-zone height", "mm"),
        ("h", "section depth in the modelled crack direction", "mm"),
        ("d", "effective reinforcement depth", "mm"),
        ("x", "neutral-axis depth", "mm"),
        ("A<sub>c,eff</sub>", "effective concrete tension area", "m2"),
    ),
    ("crack.effective-area.2005", "coarse"): _result(
        "A<sub>c,eff</sub>", "m2",
        ("A<sub>c,eff</sub>", "centroid-matched effective concrete area", "m2"),
        ("s&#772;<sub>c,eff</sub>", "effective-area centroid axis", "m"),
        ("s&#772;<sub>s,t</sub>", "tension-reinforcement centroid axis", "m"),
        ("h<sub>c,eff</sub>", "selected effective tension-zone height", "mm"),
    ),
    ("crack.effective-area.2023", "bending"): _result(
        "h<sub>c,eff</sub>", "mm",
        ("h<sub>c,eff</sub>", "selected effective tension-zone height", "mm"),
        ("a<sub>y</sub>", "near-layer depth from the tension face", "mm"),
        ("phi", "near-layer reinforcement diameter", "mm"),
        ("Delta a<sub>y</sub>", "reinforcement-layer spread", "mm"),
        ("h-x", "tension-zone depth", "mm"),
        ("A<sub>c,eff</sub>", "effective concrete tension area", "m2"),
    ),
    ("crack.effective-area.2023", "direct-tension"): _result(
        "A<sub>c,eff</sub>", "m2",
        ("A<sub>c,eff</sub>", "union of the four effective perimeter bands", "m2"),
        ("b", "rectangular section width", "m"),
        ("h", "rectangular section height", "m"),
        ("c<sub>l</sub>", "left effective band", "m"),
        ("c<sub>r</sub>", "right effective band", "m"),
        ("c<sub>b</sub>", "bottom effective band", "m"),
        ("c<sub>t</sub>", "top effective band", "m"),
    ),
    ("crack.effective-reinforcement.ratio", "2005"): _result(
        "rho<sub>p,eff</sub>", "dimensionless",
        ("rho<sub>p,eff</sub>", "effective reinforcement ratio"),
        ("A<sub>s,eff</sub>", "mild reinforcement in the effective area", "m2"),
        ("A<sub>p,eff</sub>", "prestressing reinforcement in the effective area", "m2"),
        ("A<sub>c,eff</sub>", "effective concrete tension area", "m2"),
    ),
    ("crack.effective-reinforcement.ratio", "2023"): _result(
        "rho<sub>p,eff</sub>", "dimensionless",
        ("rho<sub>p,eff</sub>", "effective reinforcement ratio"),
        ("A<sub>s,eff</sub>", "mild reinforcement in the effective area", "m2"),
        ("xi<sub>1,j</sub>", "bond-weighting factor for tendon j"),
        ("A<sub>p,j</sub>", "prestressing reinforcement area j", "m2"),
        ("A<sub>c,eff</sub>", "effective concrete tension area", "m2"),
    ),
    ("crack.2005.spacing", "geometric"): _result(
        "s<sub>r,max</sub>", "mm",
        ("s<sub>r,max</sub>", "maximum crack spacing", "mm"),
        ("h", "section depth in the crack direction", "mm"),
        ("x", "neutral-axis depth", "mm"),
        applicability_note_required=True,
    ),
    ("crack.2005.spacing", "reinforcement"): _result(
        "s<sub>r,max</sub>", "mm",
        ("s<sub>r,max</sub>", "maximum crack spacing", "mm"),
        ("k<sub>1</sub>", "bond coefficient"),
        ("k<sub>2</sub>", "strain-distribution coefficient"),
        ("k<sub>3</sub>", "cover coefficient"),
        ("k<sub>4</sub>", "recommended crack-spacing coefficient"),
        ("c", "clear cover", "mm"),
        ("phi", "bar diameter", "mm"),
        ("rho<sub>p,eff</sub>", "effective reinforcement ratio"),
        applicability_note_required=True,
    ),
    ("crack.2005.mean-strain", None): _result(
        "eps<sub>sm</sub>-eps<sub>cm</sub>", "dimensionless",
        ("eps<sub>sm</sub>-eps<sub>cm</sub>", "mean reinforcement/concrete strain difference"),
        ("sigma<sub>s</sub>", "reinforcement stress", "MPa"),
        ("k<sub>t</sub>", "load-duration factor"),
        ("f<sub>ct,eff</sub>", "effective concrete tensile strength", "MPa"),
        ("rho<sub>p,eff</sub>", "effective reinforcement ratio"),
        ("alpha<sub>e</sub>", "reinforcement/concrete modular ratio"),
        ("E<sub>s</sub>", "reinforcement elastic modulus", "MPa"),
    ),
    ("crack.2005.width", None): _result(
        "w<sub>k</sub>", "mm",
        ("w<sub>k</sub>", "characteristic crack width", "mm"),
        ("s<sub>r,max</sub>", "maximum crack spacing", "mm"),
        ("eps<sub>sm</sub>-eps<sub>cm</sub>", "mean reinforcement/concrete strain difference"),
    ),
    ("crack.2023.spacing", None): _result(
            "s<sub>r,m,cal</sub>", "mm",
            ("s<sub>r,m,cal</sub>", "calculated mean crack spacing", "mm"),
            ("c", "clear cover", "mm"),
            ("k<sub>fl</sub>", "flexural coefficient"),
            ("k<sub>b</sub>", "bond coefficient"),
            ("phi", "bar diameter", "mm"),
            ("rho<sub>p,eff</sub>", "effective reinforcement ratio"),
            ("k<sub>w</sub>", "crack-width factor"),
            ("h-x", "tension-zone depth", "mm"),
            applicability_note_required=True,
    ),
    ("crack.2023.mean-strain", None): _result(
        "eps<sub>sm</sub>-eps<sub>cm</sub>", "dimensionless",
        ("eps<sub>sm</sub>-eps<sub>cm</sub>", "mean reinforcement/concrete strain difference"),
        ("sigma<sub>s</sub>", "reinforcement stress", "MPa"),
        ("k<sub>t</sub>", "load-duration factor"),
        ("f<sub>ct,eff</sub>", "effective concrete tensile strength", "MPa"),
        ("rho<sub>p,eff</sub>", "effective reinforcement ratio"),
        ("alpha<sub>e</sub>", "reinforcement/concrete modular ratio"),
        ("E<sub>s</sub>", "reinforcement elastic modulus", "MPa"),
    ),
    ("crack.2023.width", None): _result(
        "w<sub>k</sub>", "mm",
        ("w<sub>k,cal</sub>", "calculated characteristic crack width", "mm"),
        ("w<sub>k</sub>", "published crack width, equal to w<sub>k,cal</sub>", "mm"),
        ("k<sub>w</sub>", "crack-width factor"),
        ("k<sub>1/r</sub>", "bar-position curvature factor"),
        ("s<sub>r,m,cal</sub>", "calculated mean crack spacing", "mm"),
        ("eps<sub>sm</sub>-eps<sub>cm</sub>", "mean reinforcement/concrete strain difference"),
    ),
    ("crack.user-limit.comparison", None): _result(
        "u<sub>w</sub>", "dimensionless",
        ("u<sub>w</sub>", "user-specified crack-width comparison ratio"),
        ("w<sub>k</sub>", "calculated characteristic crack width", "mm"),
        ("w<sub>k,criterion</sub>", "user-specified crack-width criterion", "mm"),
        applicability_note_required=True,
    ),
    ("crack.heightened.base-ratio", None): _result(
        "rho<sub>s,min,base</sub>", "dimensionless",
        ("rho<sub>s,min,base</sub>", "base heightened minimum reinforcement ratio"),
        ("phi", "bar diameter", "mm"),
        ("f<sub>ct,eff</sub>", "user-supplied effective tensile strength", "MPa"),
        ("E<sub>sk</sub>", "reinforcement elastic modulus", "MPa"),
        ("k", "fine/coarse crack-system factor"),
        ("w<sub>k</sub>", "user-supplied permitted crack width", "mm"),
        applicability_note_required=True,
    ),
    ("crack.heightened.required-ratio", None): _result(
        "rho<sub>s,min</sub>", "dimensionless",
        ("rho<sub>s,min</sub>", "required heightened minimum reinforcement ratio"),
        ("m<sub>s</sub>", "reinforcement-surface multiplier"),
        ("rho<sub>s,min,base</sub>", "base heightened minimum reinforcement ratio"),
        applicability_note_required=True,
    ),
    ("crack.heightened.required-area", None): _result(
        "A<sub>s,req</sub>", "mm2",
        ("A<sub>s,req</sub>", "required reinforcement area", "mm2"),
        ("rho<sub>s,min</sub>", "required heightened minimum reinforcement ratio"),
        ("A<sub>c,eff</sub>", "user-supplied effective tension area", "mm2"),
    ),
    ("crack.heightened.area-comparison", None): _result(
        "u<sub>A</sub>", "dimensionless",
        ("u<sub>A</sub>", "required-to-provided reinforcement area ratio"),
        ("A<sub>s,req</sub>", "required reinforcement area", "mm2"),
        (
            "A<sub>s,prov</sub>",
            "auto-derived retained mild-reinforcement area",
            "mm2",
        ),
        applicability_note_required=True,
    ),
}


def _validate_catalogue() -> None:
    if len(_CONTRACTS) != 144:
        raise RuntimeError(
            f"Expected 144 report equation contracts, got {len(_CONTRACTS)}."
        )
    for (key, variant), contract in _CONTRACTS.items():
        if key != _MATERIAL_TEMPLATE_KEY and not _KEY_RE.fullmatch(key):
            raise RuntimeError(f"Invalid equation-contract key: {key!r}.")
        if variant is not None and not _KEY_RE.fullmatch(variant):
            raise RuntimeError(f"Invalid equation-contract variant: {variant!r}.")
        if not contract.symbols:
            raise RuntimeError(f"Equation contract {key!r} has no symbols.")
        symbol_names = [symbol.markup for symbol in contract.symbols]
        if any(not name.strip() for name in symbol_names):
            raise RuntimeError(f"Equation contract {key!r} has a blank symbol.")
        if len(symbol_names) != len(set(symbol_names)):
            raise RuntimeError(f"Equation contract {key!r} has duplicate symbols.")
        for symbol in contract.symbols:
            if not symbol.meaning.strip() or not symbol.unit.strip():
                raise RuntimeError(f"Equation contract {key!r} has an incomplete symbol.")
        if contract.publication_role not in _PUBLICATION_ROLES:
            raise RuntimeError(f"Equation contract {key!r} has an invalid publication role.")
        if contract.substitution_role not in _SUBSTITUTION_ROLES:
            raise RuntimeError(f"Equation contract {key!r} has an invalid role.")
        if contract.publication_role == "theory" and (
            contract.expects_result
            or contract.expects_substitution
            or contract.applicability_note_required
        ):
            raise RuntimeError(
                f"Theory equation contract {key!r} advertises calculation output."
            )
        if contract.expects_result:
            if not contract.result_symbol.strip() or not contract.result_unit:
                raise RuntimeError(f"Equation contract {key!r} has an incomplete result.")
            if contract.result_symbol not in symbol_names:
                raise RuntimeError(
                    f"Equation contract {key!r} leaves its result symbol undefined."
                )
        elif contract.result_unit is not None:
            raise RuntimeError(f"Relation-only equation {key!r} advertises a result unit.")


_validate_catalogue()


def equation_contract(
    equation_key: str, variant: str | None = None
) -> EquationContract:
    """Return the exact contract for a validated live equation key and variant."""

    key = str(equation_key)
    lookup_key = _MATERIAL_TEMPLATE_KEY if _MATERIAL_KEY_RE.fullmatch(key) else key
    lookup = (lookup_key, variant)
    try:
        return _CONTRACTS[lookup]
    except KeyError as exc:
        variants = tuple(
            value for candidate, value in _CONTRACTS if candidate == lookup_key
        )
        if variants:
            raise ValueError(
                f"Equation {key!r} requires one of variants {variants!r}; "
                f"got {variant!r}."
            ) from exc
        raise ValueError(f"No report equation contract for {key!r}.") from exc


def validate_equation_payload(
    equation_key: str,
    contract: EquationContract,
    *,
    expression: object,
    substitution: object,
    applicability_note: object,
    result: object,
) -> None:
    """Fail atomically when a live call disagrees with its frozen contract."""

    if not isinstance(expression, str) or not expression.strip():
        raise ValueError(f"Equation {equation_key} requires a symbolic expression.")
    has_substitution = isinstance(substitution, str) and bool(substitution.strip())
    has_note = isinstance(applicability_note, str) and bool(applicability_note.strip())
    valid_substitution = (
        has_substitution
        if contract.substitution_role == "numerical"
        else not has_substitution
    )
    if not valid_substitution:
        raise ValueError(
            f"Equation {equation_key} requires {contract.substitution_role} "
            "substitution content in its dedicated field."
        )
    if has_note != contract.applicability_note_required:
        expected_note = (
            "an applicability note"
            if contract.applicability_note_required
            else "no applicability note"
        )
        raise ValueError(f"Equation {equation_key} requires {expected_note}.")
    has_result = isinstance(result, str) and bool(result.strip())
    if has_result != contract.expects_result:
        expected = "a final result" if contract.expects_result else "no final result"
        raise ValueError(f"Equation {equation_key} requires {expected}.")


def equation_contract_items() -> tuple[
    tuple[tuple[str, str | None], EquationContract], ...
]:
    """Return the immutable catalogue in authored insertion order for QA."""

    return tuple(_CONTRACTS.items())
