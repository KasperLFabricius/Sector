"""Frozen semantic contracts for generated-report equation blocks.

Solver and result objects own the numerical values.  This module owns the
publication identity around them: every equation's symbols, final quantity and
unit, and the semantic role of its authored publication rows.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


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
    ("basis.detailing.transverse-ratios", None): _relation(
        ("rho<sub>w</sub>", "shear-link reinforcement ratio"),
        ("A<sub>sw</sub>", "effective shear-link area", "mm2"),
        ("s", "longitudinal link spacing", "mm"),
        ("b<sub>w</sub>", "effective web breadth", "mm"),
        ("rho<sub>w,T</sub>", "torsion-link reinforcement ratio"),
        ("A<sub>leg</sub>", "area of one effective closed-link leg", "mm2"),
        ("t<sub>ef</sub>", "effective torsion-wall thickness", "mm"),
    ),
    ("detailing.minimum.area-2005", None): _calculation_relation(
        ("A<sub>s,min</sub>", "required minimum longitudinal reinforcement", "mm2"),
        ("f<sub>ctm</sub>", "mean concrete tensile strength", "MPa"),
        ("f<sub>yk</sub>", "characteristic reinforcement yield strength", "MPa"),
        ("b<sub>t</sub>", "mean width of the tension zone", "mm"),
        ("d", "effective depth", "mm"),
    ),
    ("detailing.minimum.tension-2023", None): _calculation_relation(
        ("R<sub>nom</sub>", "nominal reinforcement tensile resistance", "kN"),
        ("A<sub>s,i</sub>", "area of reinforcement element i", "mm2"),
        ("f<sub>yk,i</sub>", "characteristic yield strength of element i", "MPa"),
        ("R<sub>cr</sub>", "gross-section cracking tension", "kN"),
        ("A<sub>c</sub>", "gross concrete area", "mm2"),
        ("f<sub>ctm</sub>", "mean concrete tensile strength", "MPa"),
    ),
    ("detailing.minimum.bending-2023", None): _calculation_relation(
        ("M<sub>R,nom</sub>", "nominal bending resistance", "kNm"),
        ("M<sub>cr</sub>", "cracking moment", "kNm"),
        ("N<sub>Ed</sub>", "applied design axial force", "kN"),
    ),
    ("detailing.links.minimum-ratio", None): _calculation_relation(
        ("rho<sub>w,min</sub>", "minimum shear-link ratio"),
        ("f<sub>ck</sub>", "characteristic concrete compressive strength", "MPa"),
        ("f<sub>ywk</sub>", "characteristic link yield strength", "MPa"),
    ),
    ("detailing.clear-spacing.requirement", None): _calculation_relation(
        ("c<sub>req</sub>", "required clear reinforcement spacing", "mm"),
        ("phi<sub>max</sub>", "larger detailing diameter of the pair", "mm"),
        ("D<sub>upper</sub>", "upper aggregate size", "mm"),
    ),
    ("plastic.worked.axial-equilibrium", None): _result(
        "N", "kN",
        ("T", "reinforcement tensile resultant", "kN"),
        ("F<sub>c</sub>", "concrete compressive resultant", "kN"),
        ("N", "applied axial force", "kN"),
        ("residual", "absolute axial-equilibrium residual", "kN"),
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
        substitution_role="none",
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
        substitution_role="none",
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
        substitution_role="none",
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
        substitution_role="none",
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
    ("cracking.threshold", None): _result(
        "lambda<sub>cr</sub>", "dimensionless",
        ("lambda<sub>cr</sub>", "load factor to first cracking"),
        ("f<sub>ct,eff</sub>", "effective concrete tensile strength", "MPa"),
        ("sigma<sub>ct,I</sub>", "Stage-I extreme tensile stress", "MPa"),
    ),
    ("crack.2005.spacing", "geometric"): _result(
        "s<sub>r,max</sub>", "mm",
        ("s<sub>r,max</sub>", "maximum crack spacing", "mm"),
        ("h", "section depth in the crack direction", "mm"),
        ("x", "neutral-axis depth", "mm"),
        substitution_role="none",
        applicability_note_required=True,
    ),
    ("crack.2005.spacing", "reinforcement"): _calculation_relation(
        ("s<sub>r,max</sub>", "maximum crack spacing", "mm"),
        ("k<sub>1</sub>", "bond coefficient"),
        ("k<sub>2</sub>", "strain-distribution coefficient"),
        ("k<sub>3</sub>", "cover coefficient"),
        ("k<sub>4</sub>", "recommended crack-spacing coefficient"),
        ("c", "clear cover", "mm"),
        ("phi", "bar diameter", "mm"),
        ("rho<sub>p,eff</sub>", "effective reinforcement ratio"),
    ),
    ("crack.2005.mean-strain", None): _calculation_relation(
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
    ("crack.2023.spacing", None): EquationContract(
        _symbols(
            ("s<sub>r,m,cal</sub>", "calculated mean crack spacing", "mm"),
            ("c", "clear cover", "mm"),
            ("k<sub>fl</sub>", "flexural coefficient"),
            ("k<sub>b</sub>", "bond coefficient"),
            ("phi", "bar diameter", "mm"),
            ("rho<sub>p,eff</sub>", "effective reinforcement ratio"),
            ("k<sub>w</sub>", "crack-width factor"),
            ("h-x", "tension-zone depth", "mm"),
        ),
        substitution_role="numerical",
        publication_role="calculation",
    ),
    ("crack.2023.mean-strain", None): _calculation_relation(
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
}


def _validate_catalogue() -> None:
    if len(_CONTRACTS) != 62:
        raise RuntimeError(f"Expected 62 report equation contracts, got {len(_CONTRACTS)}.")
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
