"""Code-authored presentation inventory for generated-report equations.

The report builder owns equation identity and source lines. This module owns the
separate F039 publication contract: every retained symbolic equation resolves to
an explicit symbol dictionary and, when it publishes a result, one canonical
result unit. Nothing here evaluates an engineering expression.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


SymbolDefinition = tuple[str, str, str]


@dataclass(frozen=True)
class EquationBlockSpec:
    """Immutable symbol and result-unit contract for one equation variant."""

    symbols: tuple[SymbolDefinition, ...]
    result_unit: str | None

    def __post_init__(self):
        if type(self.symbols) is not tuple or not self.symbols:
            raise ValueError("An equation block requires symbol definitions.")
        seen = set()
        for row in self.symbols:
            if type(row) is not tuple or len(row) != 3:
                raise ValueError("Each equation symbol requires name, meaning and unit.")
            name, meaning, unit = row
            if any(type(value) is not str or not value.strip() for value in row):
                raise ValueError("Equation symbol fields must be non-blank strings.")
            if name in seen:
                raise ValueError(f"Duplicate equation symbol definition: {name}.")
            seen.add(name)
        if self.result_unit is not None and (
            type(self.result_unit) is not str or not self.result_unit.strip()
        ):
            raise ValueError("An equation result unit must be a non-blank string.")


def _spec(result_unit, *symbols):
    return EquationBlockSpec(tuple(symbols), result_unit)


# Keys are (stable equation key, explicit branch variant). Canonical units use
# the same ASCII vocabulary as the calculation-trace layer; the report notation
# renderer supplies powers and other print typography.
_SPECS = {
    ("materials.concrete.fcd", "2023"): _spec(
        "MPa",
        ("f<sub>cd</sub>", "design concrete compressive strength", "MPa"),
        ("eta<sub>cc</sub>", "2023 strength-reduction factor", "1"),
        ("k<sub>tc</sub>", "time-dependent strength factor", "1"),
        ("f<sub>ck</sub>", "characteristic concrete strength", "MPa"),
        ("gamma<sub>c</sub>", "concrete partial factor", "1"),
    ),
    ("materials.concrete.fcd", "2005"): _spec(
        "MPa",
        ("f<sub>cd</sub>", "design concrete compressive strength", "MPa"),
        ("alpha<sub>cc</sub>", "long-term strength coefficient", "1"),
        ("f<sub>ck</sub>", "characteristic concrete strength", "MPa"),
        ("gamma<sub>c</sub>", "concrete partial factor", "1"),
    ),
    ("materials.concrete.curve-2", None): _spec(
        None,
        ("sigma<sub>c</sub>", "concrete compressive stress", "MPa"),
        ("f<sub>cd</sub>", "design concrete compressive strength", "MPa"),
        ("eps<sub>c</sub>", "concrete compressive strain", "1"),
        ("eps<sub>c2</sub>", "strain at peak concrete stress", "1"),
        ("eps<sub>cu2</sub>", "ultimate concrete strain", "1"),
        ("n", "Curve 2 exponent", "1"),
    ),
    ("materials.steel.fyd-*", None): _spec(
        "MPa",
        ("f<sub>yd</sub>", "design reinforcement yield strength", "MPa"),
        ("f<sub>ytk</sub>", "characteristic tensile yield strength", "MPa"),
        ("gamma<sub>y</sub>", "reinforcement partial factor", "1"),
    ),
    ("basis.plastic.governing-curvature", None): _spec(
        None,
        ("kappa<sub>u</sub>", "governing ultimate curvature", "1/m"),
        ("eps<sub>cu2</sub>", "ultimate concrete strain", "1"),
        ("c", "neutral-axis compression depth", "m"),
        ("eps<sub>su,i</sub>", "ultimate strain of bar i", "1"),
        ("d<sub>s,i</sub>", "bar i distance from the neutral axis", "m"),
        ("eps<sub>pu,j</sub>", "ultimate strain of tendon j", "1"),
        ("eps<sub>p0,j</sub>", "initial strain of tendon j", "1"),
        ("d<sub>p,j</sub>", "tendon j distance from the neutral axis", "m"),
        ("i", "mild-reinforcement element index", "1"),
        ("j", "prestressing-tendon element index", "1"),
    ),
    ("basis.plastic.equilibrium", None): _spec(
        None,
        ("F<sub>c</sub>", "concrete resultant force", "kN"),
        ("F<sub>s</sub>", "reinforcement resultant force", "kN"),
        ("F<sub>p</sub>", "prestressing resultant force", "kN"),
        ("N", "section axial force", "kN"),
        ("M", "section moment", "kNm"),
        ("F<sub>i</sub>", "force contribution i", "kN"),
        ("d<sub>i</sub>", "lever arm of contribution i", "m"),
        ("i", "section force-contribution index", "1"),
    ),
    ("basis.fatigue.stress-range", None): _spec(
        None,
        ("&#916;sigma<sub>i</sub>", "design stress range in element i", "MPa"),
        ("sigma", "element stress from the stated action", "MPa"),
        ("long", "long-term action set", "mixed kN/kNm"),
        ("short", "short-term action increment", "mixed kN/kNm"),
        ("gamma<sub>Ff</sub>", "fatigue action factor", "1"),
        ("i", "reinforcement or tendon element index", "1"),
    ),
    ("basis.fatigue.reinforcement-miner", None): _spec(
        None,
        ("D", "reinforcement Miner damage", "1"),
        ("n<sub>i</sub>", "cycles in spectrum bin i", "cycles"),
        ("N<sub>R,i</sub>", "resistance life for bin i", "cycles"),
        ("i", "fatigue-spectrum bin index", "1"),
    ),
    ("basis.fatigue.concrete-miner", None): _spec(
        None,
        ("D<sub>c</sub>", "concrete Miner damage", "1"),
        ("n<sub>i</sub>", "cycles in spectrum bin i", "cycles"),
        ("N<sub>R,i</sub>", "concrete resistance life for bin i", "cycles"),
        ("i", "fatigue-spectrum bin index", "1"),
    ),
    ("basis.detailing.transverse-ratios", None): _spec(
        None,
        ("rho<sub>w</sub>", "vertical shear-link ratio", "1"),
        ("A<sub>sw</sub>", "shear-link area within spacing s", "mm2"),
        ("s", "longitudinal link spacing", "mm"),
        ("b<sub>w</sub>", "effective web breadth", "mm"),
        ("rho<sub>w,T</sub>", "torsion-wall link ratio", "1"),
        ("A<sub>leg</sub>", "one closed-link leg area", "mm2"),
        ("t<sub>ef</sub>", "effective tube-wall thickness", "mm"),
    ),
    ("detailing.minimum.area-2005", None): _spec(
        None,
        ("A<sub>s,min</sub>", "minimum longitudinal reinforcement area", "mm2"),
        ("f<sub>ctm</sub>", "mean concrete tensile strength", "MPa"),
        ("f<sub>yk</sub>", "characteristic reinforcement yield strength", "MPa"),
        ("b<sub>t</sub>", "mean width of the tension zone", "mm"),
        ("d", "effective depth normal to the neutral line", "mm"),
    ),
    ("detailing.minimum.tension-2023", None): _spec(
        None,
        ("R<sub>nom</sub>", "nominal reinforcement tensile resistance", "kN"),
        ("A<sub>s,i</sub>", "area of reinforcement element i", "mm2"),
        ("f<sub>yk,i</sub>", "characteristic strength of element i", "MPa"),
        ("R<sub>cr</sub>", "concrete cracking force", "kN"),
        ("A<sub>c</sub>", "concrete area", "mm2"),
        ("f<sub>ctm</sub>", "mean concrete tensile strength", "MPa"),
        ("i", "reinforcement element index", "1"),
    ),
    ("detailing.minimum.bending-2023", None): _spec(
        None,
        ("M<sub>R,nom</sub>", "nominal moment resistance", "kNm"),
        ("N<sub>Ed</sub>", "applied design axial force", "kN"),
        ("M<sub>cr</sub>", "cracking moment at the applied axial force", "kNm"),
    ),
    ("detailing.links.minimum-ratio", None): _spec(
        None,
        ("rho<sub>w,min</sub>", "minimum transverse reinforcement ratio", "1"),
        ("f<sub>ck</sub>", "characteristic concrete strength", "MPa"),
        ("f<sub>ywk</sub>", "characteristic link yield strength", "MPa"),
    ),
    ("detailing.clear-spacing.requirement", None): _spec(
        None,
        ("c<sub>req</sub>", "required clear bar spacing", "mm"),
        ("phi<sub>max</sub>", "larger adjacent bar diameter", "mm"),
        ("D<sub>upper</sub>", "upper aggregate size", "mm"),
    ),
    ("plastic.worked.axial-equilibrium", None): _spec(
        "kN",
        ("T", "total reinforcement tension", "kN"),
        ("F<sub>c</sub>", "concrete compression resultant", "kN"),
        ("N", "section axial force", "kN"),
    ),
    ("shear.2023.effective-span", None): _spec(
        "mm",
        ("a<sub>cs</sub>", "effective shear span", "mm"),
        ("M<sub>Ed</sub>", "design bending moment", "kNm"),
        ("V<sub>Ed</sub>", "design shear force", "kN"),
        ("d", "effective depth", "mm"),
    ),
    ("shear.2023.axial-factor", None): _spec(
        "mm",
        ("k<sub>vp</sub>", "axial-action shear factor", "1"),
        ("N<sub>Ed</sub>", "design axial tension", "kN"),
        ("V<sub>Ed</sub>", "design shear force", "kN"),
        ("d", "effective depth", "mm"),
        ("a<sub>cs</sub>", "effective shear span", "mm"),
    ),
    ("shear.2023.tau-basic", None): _spec(
        "MPa",
        ("tau<sub>Rd,c</sub>", "basic concrete shear stress resistance", "MPa"),
        ("gamma<sub>v</sub>", "shear resistance factor", "1"),
        ("rho<sub>l</sub>", "longitudinal reinforcement ratio", "1"),
        ("f<sub>ck</sub>", "characteristic concrete strength", "MPa"),
        ("d<sub>dg</sub>", "aggregate-size parameter", "mm"),
        ("k<sub>vp</sub>", "axial-action shear factor", "1"),
        ("d", "effective depth", "mm"),
    ),
    ("shear.2023.tau-minimum", None): _spec(
        "MPa",
        ("tau<sub>Rd,c,min</sub>", "minimum concrete shear stress resistance", "MPa"),
        ("gamma<sub>v</sub>", "shear resistance factor", "1"),
        ("f<sub>ck</sub>", "characteristic concrete strength", "MPa"),
        ("f<sub>yd</sub>", "design reinforcement yield strength", "MPa"),
        ("d<sub>dg</sub>", "aggregate-size parameter", "mm"),
        ("d", "effective depth", "mm"),
    ),
    ("shear.2023.vrdc", None): _spec(
        "kN",
        ("V<sub>Rd,c</sub>", "concrete shear resistance", "kN"),
        ("tau<sub>Rd,c</sub>", "basic concrete shear stress resistance", "MPa"),
        ("tau<sub>Rd,c,min</sub>", "minimum concrete shear stress resistance", "MPa"),
        ("b<sub>w</sub>", "effective web breadth", "mm"),
        ("z", "internal lever arm", "mm"),
    ),
    ("shear.2023.utilisation", None): _spec(
        "1",
        ("V<sub>Ed</sub>", "design shear demand", "kN"),
        ("V<sub>Rd,c</sub>", "concrete shear resistance", "kN"),
    ),
    ("shear.2005.stress-basic", None): _spec(
        "MPa",
        ("v", "basic concrete shear stress resistance", "MPa"),
        ("C<sub>Rd,c</sub>", "concrete shear coefficient", "1"),
        ("k", "size-effect factor", "1"),
        ("rho<sub>l</sub>", "longitudinal reinforcement ratio", "1"),
        ("f<sub>ck</sub>", "characteristic concrete strength", "MPa"),
        ("k<sub>1</sub>", "axial-stress coefficient", "1"),
        ("sigma<sub>cp</sub>", "mean concrete compression", "MPa"),
    ),
    ("shear.2005.stress-minimum", None): _spec(
        "MPa",
        ("v<sub>min,eff</sub>", "effective minimum shear stress resistance", "MPa"),
        ("v<sub>min</sub>", "minimum shear stress resistance", "MPa"),
        ("k<sub>1</sub>", "axial-stress coefficient", "1"),
        ("sigma<sub>cp</sub>", "mean concrete compression", "MPa"),
    ),
    ("shear.2005.vrdc", None): _spec(
        "kN",
        ("V<sub>Rd,c</sub>", "concrete shear resistance", "kN"),
        ("v", "basic concrete shear stress resistance", "MPa"),
        ("v<sub>min,eff</sub>", "effective minimum shear stress resistance", "MPa"),
        ("b<sub>w</sub>", "effective web breadth", "mm"),
        ("d", "effective depth", "mm"),
    ),
    ("shear.2005.utilisation", None): _spec(
        "1",
        ("V<sub>Ed</sub>", "design shear demand", "kN"),
        ("V<sub>Rd,c</sub>", "concrete shear resistance", "kN"),
    ),
    ("shear.links.tau-yield", None): _spec(
        "MPa",
        ("tau<sub>Rd,sy</sub>", "link-yield shear stress resistance", "MPa"),
        ("rho<sub>w</sub>", "transverse reinforcement ratio", "1"),
        ("f<sub>ywd</sub>", "design link yield strength", "MPa"),
        ("theta", "compression-strut angle", "degrees"),
    ),
    ("shear.links.sigma-field", None): _spec(
        "MPa",
        ("sigma<sub>cd</sub>", "compression-field stress", "MPa"),
        ("tau<sub>Ed</sub>", "design shear stress", "MPa"),
        ("theta", "compression-strut angle", "degrees"),
        ("nu", "concrete strut effectiveness factor", "1"),
        ("f<sub>cd</sub>", "design concrete compressive strength", "MPa"),
    ),
    ("shear.links.vrds", "2023"): _spec(
        "kN",
        ("V<sub>Rd,s</sub>", "link-yield shear resistance", "kN"),
        ("tau<sub>Rd,sy</sub>", "link-yield shear stress resistance", "MPa"),
        ("b<sub>w</sub>", "effective web breadth", "mm"),
        ("z", "internal lever arm", "mm"),
    ),
    ("shear.links.vrdmax", "2023"): _spec(
        "kN",
        ("V<sub>Rd,max</sub>", "maximum strut-controlled shear resistance", "kN"),
        ("nu", "concrete strut effectiveness factor", "1"),
        ("f<sub>cd</sub>", "design concrete compressive strength", "MPa"),
        ("b<sub>w</sub>", "effective web breadth", "mm"),
        ("z", "internal lever arm", "mm"),
        ("theta", "compression-strut angle", "degrees"),
    ),
    ("shear.links.vrds", "2005"): _spec(
        "kN",
        ("V<sub>Rd,s</sub>", "link-yield shear resistance", "kN"),
        ("A<sub>sw</sub>/s", "link area per longitudinal spacing", "mm2/mm"),
        ("z", "internal lever arm", "mm"),
        ("f<sub>ywd</sub>", "design link yield strength", "MPa"),
        ("theta", "compression-strut angle", "degrees"),
    ),
    ("shear.links.vrdmax", "2005"): _spec(
        "kN",
        ("V<sub>Rd,max</sub>", "maximum strut-controlled shear resistance", "kN"),
        ("alpha<sub>cw</sub>", "axial-stress strut coefficient", "1"),
        ("b<sub>w</sub>", "effective web breadth", "mm"),
        ("z", "internal lever arm", "mm"),
        ("nu<sub>1</sub>", "concrete strut effectiveness factor", "1"),
        ("f<sub>cd</sub>", "design concrete compressive strength", "MPa"),
        ("theta", "compression-strut angle", "degrees"),
    ),
    ("shear.links.vrd", None): _spec(
        "kN",
        ("V<sub>Rd</sub>", "governing reinforced shear resistance", "kN"),
        ("V<sub>Rd,s</sub>", "link-yield shear resistance", "kN"),
        ("V<sub>Rd,max</sub>", "maximum strut-controlled shear resistance", "kN"),
    ),
    ("shear.links.utilisation", None): _spec(
        "1",
        ("V<sub>Ed</sub>", "design shear demand", "kN"),
        ("V<sub>Rd</sub>", "governing reinforced shear resistance", "kN"),
    ),
    ("shear.chord.demand", "2023"): _spec(
        "kNm",
        ("M<sub>Ed,total</sub>", "total longitudinal-chord moment demand", "kNm"),
        ("M<sub>Ed</sub>", "bending moment contribution", "kNm"),
        ("N<sub>Vd</sub>", "additional longitudinal shear force", "kN"),
        ("F<sub>td,T</sub>", "longitudinal torsion force", "kN"),
        ("z", "longitudinal-chord lever arm", "m"),
    ),
    ("shear.chord.demand", "2005"): _spec(
        "kNm",
        ("M<sub>Ed,total</sub>", "total longitudinal-chord moment demand", "kNm"),
        ("M<sub>Ed</sub>", "bending moment contribution", "kNm"),
        ("&#916;F<sub>td</sub>", "additional longitudinal shear force", "kN"),
        ("F<sub>td,T</sub>", "longitudinal torsion force", "kN"),
        ("z", "longitudinal-chord lever arm", "m"),
    ),
    ("shear.chord.utilisation", None): _spec(
        "1",
        ("M<sub>Ed,total</sub>", "total longitudinal-chord moment demand", "kNm"),
        ("M<sub>Rd</sub>", "available longitudinal-chord moment resistance", "kNm"),
    ),
    ("combined.dk-na.sum", None): _spec(
        "1",
        ("S<sub>Ed</sub>", "design effect of an acting sectional force", "matched action unit"),
        ("S<sub>Rd</sub>", "resistance to that sectional force acting alone", "matched action unit"),
        ("r<sub>M</sub>", "bending utilisation", "1"),
        ("r<sub>V</sub>", "shear utilisation", "1"),
        ("r<sub>T</sub>", "torsion utilisation", "1"),
        ("i", "acting sectional-force index", "1"),
    ),
    ("combined.crushing.interaction", None): _spec(
        "1",
        ("T<sub>Ed</sub>", "design torsion demand", "kNm"),
        ("T<sub>Rd,max</sub>", "strut-controlled torsion resistance", "kNm"),
        ("V<sub>Ed</sub>", "design shear demand", "kN"),
        ("V<sub>Rd,max</sub>", "strut-controlled shear resistance", "kN"),
    ),
    ("combined.stirrup.utilisation", None): _spec(
        "1",
        ("shear share", "fraction of closed-stirrup capacity used by shear", "1"),
        ("torsion share", "fraction of closed-stirrup capacity used by torsion", "1"),
    ),
    ("combined.chord.demand", None): _spec(
        "kNm",
        ("M<sub>Ed,total</sub>", "total longitudinal-chord moment demand", "kNm"),
        ("M<sub>Ed</sub>", "bending moment contribution", "kNm"),
        ("&#916;F<sub>td</sub>", "additional longitudinal shear force", "kN"),
        ("F<sub>td,T</sub>", "longitudinal torsion force", "kN"),
        ("z", "longitudinal-chord lever arm", "m"),
    ),
    ("combined.chord.utilisation", None): _spec(
        "1",
        ("M<sub>Ed,total</sub>", "total longitudinal-chord moment demand", "kNm"),
        ("M<sub>Rd</sub>", "available longitudinal-chord moment resistance", "kNm"),
    ),
    ("torsion.off-axis-chord.demand", None): _spec(
        "kNm",
        ("M<sub>Ed,total</sub>", "total off-axis chord moment demand", "kNm"),
        ("M<sub>Ed</sub>", "bending moment contribution", "kNm"),
        ("F<sub>td,T</sub>", "longitudinal torsion force", "kN"),
        ("z", "off-axis chord lever arm", "m"),
    ),
    ("torsion.off-axis-chord.utilisation", None): _spec(
        "1",
        ("M<sub>Ed,total</sub>", "total off-axis chord moment demand", "kNm"),
        ("M<sub>Rd</sub>", "available off-axis chord moment resistance", "kNm"),
    ),
    ("torsion.subtube.governing-utilisation", None): _spec(
        "1",
        ("T<sub>Ed,i</sub>", "design torsion assigned to sub-tube i", "kNm"),
        ("T<sub>Rd,i</sub>", "torsion resistance of sub-tube i", "kNm"),
        ("i", "sub-tube index", "1"),
    ),
    ("torsion.shear.crushing-interaction", None): _spec(
        "1",
        ("T<sub>Ed</sub>", "design torsion demand", "kNm"),
        ("T<sub>Rd,max</sub>", "strut-controlled torsion resistance", "kNm"),
        ("V<sub>Ed</sub>", "design shear demand", "kN"),
        ("V<sub>Rd,max</sub>", "strut-controlled shear resistance", "kN"),
    ),
    ("torsion.resistance.steel", None): _spec(
        "kNm",
        ("T<sub>Rd,s</sub>", "transverse-steel torsion resistance", "kNm"),
        ("A<sub>sw</sub>/s", "closed-link area per spacing", "mm2/mm"),
        ("A<sub>k</sub>", "area enclosed by the effective tube centreline", "m2"),
        ("f<sub>ywd</sub>", "design link yield strength", "MPa"),
        ("theta", "compression-strut angle", "degrees"),
    ),
    ("torsion.resistance.crushing", None): _spec(
        "kNm",
        ("T<sub>Rd,max</sub>", "strut-controlled torsion resistance", "kNm"),
        ("nu", "concrete strut effectiveness factor", "1"),
        ("alpha<sub>cw</sub>", "axial-stress strut coefficient", "1"),
        ("f<sub>cd</sub>", "design concrete compressive strength", "MPa"),
        ("A<sub>k</sub>", "area enclosed by the effective tube centreline", "m2"),
        ("t<sub>ef</sub>", "effective tube-wall thickness", "m"),
        ("theta", "compression-strut angle", "degrees"),
    ),
    ("torsion.resistance.governing", None): _spec(
        "kNm",
        ("T<sub>Rd</sub>", "governing torsion resistance", "kNm"),
        ("T<sub>Rd,s</sub>", "transverse-steel torsion resistance", "kNm"),
        ("T<sub>Rd,max</sub>", "strut-controlled torsion resistance", "kNm"),
    ),
    ("torsion.cracking.fctd", None): _spec(
        "MPa",
        ("f<sub>ctd</sub>", "design concrete tensile strength", "MPa"),
        ("f<sub>ctk,0.05</sub>", "lower characteristic tensile strength", "MPa"),
        ("gamma<sub>ct</sub>", "concrete tension partial factor", "1"),
    ),
    ("torsion.cracking.resistance", None): _spec(
        "kNm",
        ("T<sub>Rd,c</sub>", "torsional cracking resistance", "kNm"),
        ("A<sub>k</sub>", "area enclosed by the effective tube centreline", "m2"),
        ("t<sub>ef</sub>", "effective tube-wall thickness", "m"),
        ("f<sub>ctd</sub>", "design concrete tensile strength", "MPa"),
    ),
    ("torsion.utilisation", None): _spec(
        "1",
        ("T<sub>Ed</sub>", "design torsion demand", "kNm"),
        ("T<sub>Rd</sub>", "governing torsion resistance", "kNm"),
    ),
    ("torsion.longitudinal-steel", None): _spec(
        "mm2",
        ("A<sub>sl</sub>", "required additional longitudinal steel area", "mm2"),
        ("T<sub>Ed</sub>", "design torsion demand", "kNm"),
        ("u<sub>k</sub>", "effective tube centreline perimeter", "m"),
        ("theta", "compression-strut angle", "degrees"),
        ("A<sub>k</sub>", "area enclosed by the effective tube centreline", "m2"),
        ("f<sub>yd</sub>", "design longitudinal steel strength", "MPa"),
    ),
    ("torsion.minimum-reinforcement.screen", None): _spec(
        "1",
        ("T<sub>Ed</sub>", "design torsion demand", "kNm"),
        ("T<sub>Rd,c</sub>", "torsional cracking resistance", "kNm"),
        ("V<sub>Ed</sub>", "design shear demand", "kN"),
        ("V<sub>Rd,c</sub>", "concrete shear resistance", "kN"),
    ),
    ("cracking.threshold", None): _spec(
        "1",
        ("lambda<sub>cr</sub>", "first-cracking load factor", "1"),
        ("f<sub>ct,eff</sub>", "effective concrete tensile strength", "MPa"),
        ("sigma<sub>ct,I</sub>", "Stage-I extreme tensile stress", "MPa"),
    ),
    ("crack.2005.spacing", "coarse"): _spec(
        "mm",
        ("s<sub>r,max</sub>", "maximum crack spacing", "mm"),
        ("h", "section depth in the cracking direction", "mm"),
        ("x", "neutral-axis depth", "mm"),
    ),
    ("crack.2005.spacing", "fine"): _spec(
        None,
        ("s<sub>r,max</sub>", "maximum crack spacing", "mm"),
        ("k<sub>1</sub>", "bond-property coefficient", "1"),
        ("k<sub>2</sub>", "strain-distribution coefficient", "1"),
        ("k<sub>3</sub>", "cover coefficient", "1"),
        ("k<sub>4</sub>", "bar-diameter coefficient", "1"),
        ("c", "reinforcement cover", "mm"),
        ("phi", "governing bar diameter", "mm"),
        ("rho<sub>p,eff</sub>", "effective reinforcement ratio", "1"),
    ),
    ("crack.2005.mean-strain", None): _spec(
        None,
        ("eps<sub>sm</sub>", "mean reinforcement strain", "1"),
        ("eps<sub>cm</sub>", "mean concrete strain between cracks", "1"),
        ("sigma<sub>s</sub>", "reinforcement stress in the cracked section", "MPa"),
        ("k<sub>t</sub>", "load-duration factor", "1"),
        ("f<sub>ct,eff</sub>", "effective concrete tensile strength", "MPa"),
        ("rho<sub>p,eff</sub>", "effective reinforcement ratio", "1"),
        ("alpha<sub>e</sub>", "reinforcement-to-concrete modulus ratio", "1"),
        ("E<sub>s</sub>", "reinforcement elastic modulus", "MPa"),
    ),
    ("crack.2005.width", None): _spec(
        "mm",
        ("w<sub>k</sub>", "characteristic crack width", "mm"),
        ("s<sub>r,max</sub>", "maximum crack spacing", "mm"),
        ("eps<sub>sm</sub>", "mean reinforcement strain", "1"),
        ("eps<sub>cm</sub>", "mean concrete strain between cracks", "1"),
    ),
    ("crack.2023.spacing", None): _spec(
        None,
        ("s<sub>r,m,cal</sub>", "calculated mean crack spacing", "mm"),
        ("c", "reinforcement cover", "mm"),
        ("k<sub>fl</sub>", "flexural coefficient", "1"),
        ("k<sub>b</sub>", "bond coefficient", "1"),
        ("phi", "governing bar diameter", "mm"),
        ("rho<sub>p,eff</sub>", "effective reinforcement ratio", "1"),
        ("k<sub>w</sub>", "crack-width coefficient", "1"),
        ("h", "section depth in the cracking direction", "mm"),
        ("x", "neutral-axis depth", "mm"),
    ),
    ("crack.2023.mean-strain", None): _spec(
        None,
        ("eps<sub>sm</sub>", "mean reinforcement strain", "1"),
        ("eps<sub>cm</sub>", "mean concrete strain between cracks", "1"),
        ("sigma<sub>s</sub>", "reinforcement stress in the cracked section", "MPa"),
        ("k<sub>t</sub>", "load-duration factor", "1"),
        ("f<sub>ct,eff</sub>", "effective concrete tensile strength", "MPa"),
        ("rho<sub>p,eff</sub>", "effective reinforcement ratio", "1"),
        ("alpha<sub>e</sub>", "reinforcement-to-concrete modulus ratio", "1"),
        ("E<sub>s</sub>", "reinforcement elastic modulus", "MPa"),
    ),
    ("crack.2023.width", None): _spec(
        "mm",
        ("w<sub>k,cal</sub>", "calculated crack width", "mm"),
        ("k<sub>w</sub>", "crack-width coefficient", "1"),
        ("k<sub>1/r</sub>", "per-bar curvature coefficient", "1"),
        ("s<sub>r,m,cal</sub>", "calculated mean crack spacing", "mm"),
        ("eps<sub>sm</sub>", "mean reinforcement strain", "1"),
        ("eps<sub>cm</sub>", "mean concrete strain between cracks", "1"),
    ),
}


_STEEL_KEY_RE = re.compile(r"^materials\.steel\.fyd-[1-9][0-9]*$")


def equation_block_spec(equation_key, variant=None):
    """Resolve one retained equation key/variant or fail closed."""
    key = str(equation_key)
    if _STEEL_KEY_RE.fullmatch(key):
        key = "materials.steel.fyd-*"
    lookup = (key, variant)
    try:
        return _SPECS[lookup]
    except KeyError as exc:
        suffix = "" if variant is None else f" variant {variant!r}"
        raise ValueError(
            f"No report equation-block specification for {equation_key!r}{suffix}."
        ) from exc


def equation_block_spec_items():
    """Return the immutable catalog entries for completeness audits."""
    return tuple(sorted(_SPECS.items(), key=lambda item: str(item[0])))
