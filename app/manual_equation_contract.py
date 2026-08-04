"""Strict semantic contract for the authored Part C manual equations.

The manual prose remains the publication source.  This module independently
identifies every display equation and rejects a missing, moved, reordered,
duplicated or altered equation before a renderer may consume the catalogue.
It deliberately contains no PDF or Streamlit rendering code.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable, Sequence


_DISPLAY_EQUATION_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_KEY_RE = re.compile(r"manual\.[a-z0-9]+(?:[.-][a-z0-9]+)*\Z")
_NUMBER_RE = re.compile(r"C(?:3|4|5|7|8|9|10|11)-[1-9][0-9]*\Z")
_SOURCE_KINDS = frozenset({"standard", "mixed", "project"})
_UNITS = frozenset({
    "1", "1/m", "MPa", "MPa^(1/2)", "MPa^(2/3)", "actions",
    "cycles", "days", "degrees", "kN", "kNm", "m", "m2", "mm",
    "mm2", "mm2/mm",
})
_IGNORED_COMMANDS = frozenset({
    "Big", "big", "cdot", "cos", "cot", "frac", "ge", "geq", "left",
    "le", "leq", "log", "max", "min", "qquad", "quad", "right", "sin",
    "sqrt", "sum", "tan", "text", "tfrac", "times",
})


@dataclass(frozen=True)
class ManualSymbol:
    """One equation-local symbol with its retained meaning and unit."""

    latex: str
    meaning: str
    unit: str


@dataclass(frozen=True)
class ManualEquationSpec:
    """Immutable authored identity independent of the publication renderer."""

    key: str
    number: str
    part: str
    section: str
    subsection: str
    expression_sha256: str
    symbols: tuple[ManualSymbol, ...]
    dimensional_note: str
    source_kind: str
    source: str
    uses: tuple[str, ...] = ()


@dataclass(frozen=True)
class RegisteredManualEquation:
    """A source expression sealed to its independently authored specification."""

    spec: ManualEquationSpec
    expression: str


def _q(latex: str, meaning: str, unit: str = "1") -> ManualSymbol:
    return ManualSymbol(latex, meaning, unit)


_PART_C = "Part C - Theory & methodology"


def _spec(
    key: str,
    number: str,
    section: str,
    subsection: str,
    digest: str,
    symbols: Sequence[ManualSymbol],
    dimensional_note: str,
    source_kind: str,
    source: str,
    uses: Sequence[str] = (),
) -> ManualEquationSpec:
    return ManualEquationSpec(
        key=key,
        number=number,
        part=_PART_C,
        section=section,
        subsection=subsection,
        expression_sha256=digest,
        symbols=tuple(symbols),
        dimensional_note=dimensional_note,
        source_kind=source_kind,
        source=source,
        uses=tuple(uses),
    )


MANUAL_EQUATION_SPECS = (
    _spec(
        "manual.material.concrete-law", "C3-1", "Material laws",
        "Concrete (parabola-rectangle)",
        "9056b4525fcd292ebd5769b7277ae491522d54ea6e8ee60f79d4ee0af2da6477",
        (
            _q(r"\sigma_{c}", "concrete compression stress", "MPa"),
            _q(r"f_{cd}", "design concrete compressive strength", "MPa"),
            _q(r"\varepsilon_{c}", "concrete compression strain"),
            _q(r"\varepsilon_{c2}", "strain at the plateau start"),
            _q("n", "parabola exponent"),
            _q(r"\varepsilon_{cu2}", "ultimate concrete compression strain"),
        ),
        "The strain ratios and exponent are dimensionless, so both stress branches retain MPa.",
        "standard",
        "DS/EN 1992-1-1:2005 3.1.7, Formula (3.17), with the selected edition's retained material parameters.",
    ),
    _spec(
        "manual.material.steel-law", "C3-2", "Material laws", "Mild steel",
        "5972f92c2cf2dd2c16ab580e95c70f98ebe947a2baaef960c67252ac294a9c11",
        (
            _q(r"\sigma_{s}", "mild-steel stress", "MPa"),
            _q(r"E_{s,d}", "design steel modulus", "MPa"),
            _q(r"\varepsilon_{s}", "mild-steel strain"),
            _q(r"\varepsilon_{yd}", "design yield strain"),
            _q(r"f_{yd}", "design yield strength", "MPa"),
            _q(r"f_{yk}", "characteristic yield strength", "MPa"),
            _q(r"\gamma_{s}", "steel partial factor"),
        ),
        "MPa times strain gives MPa; strength divided by a dimensionless factor remains MPa; MPa/MPa gives strain.",
        "project",
        "Project-defined general Curve 3 law; no normative citation is assigned to the generic editable law.",
    ),
    _spec(
        "manual.material.prestress-law", "C3-3", "Material laws",
        "Prestressing steel",
        "e61a85aca0ae68096eae6d42740d5e556e839b765c69ec57f61ecc5c146cbaa5",
        (
            _q(r"\varepsilon_{p,j}", "total strain in tendon j"),
            _q(r"\varepsilon_{p,IS,j}", "locked-in initial strain in tendon j"),
            _q(r"\kappa", "section curvature", "1/m"),
            _q(r"s_{p,j}", "projected tendon coordinate", "m"),
            _q(r"s_{na}", "projected neutral-axis coordinate", "m"),
            _q(r"\sigma_{p}", "prestressing-steel stress", "MPa"),
            _q("f", "selected prestressing material law", "MPa"),
            _q(r"\varepsilon_{p}", "prestressing-steel strain supplied to the material law"),
            _q(r"f_{pd}", "design prestressing strength", "MPa"),
            _q(r"f_{p0.1k}", "characteristic 0.1 percent proof strength", "MPa"),
            _q(r"\gamma_{s}", "prestressing-steel partial factor"),
        ),
        "Curvature times a metre coordinate difference is strain; the material law returns MPa; strength divided by the partial factor remains MPa.",
        "mixed",
        "Project-defined locked-in-strain convention combined with the selected DS/EN 1992-1-1 prestressing-strength basis.",
    ),
    _spec(
        "manual.plastic.governing-curvature", "C4-1",
        "Plastic capacity analysis", "The governing curvature",
        "a9125f6b7747160f86ebfe580b489be8e94a3719ff435f274d411ee1cb1c5cda",
        (
            _q(r"\kappa", "governing section curvature", "1/m"),
            _q(r"\varepsilon_{cu2}", "ultimate concrete compression strain"),
            _q("c", "compression-zone depth", "m"),
            _q(r"\varepsilon_{u,i}", "active ultimate strain for mild bar i"),
            _q(r"s_{na}", "projected neutral-axis coordinate", "m"),
            _q(r"s_{b,i}", "projected coordinate of mild bar i", "m"),
            _q(r"\varepsilon_{pu,j}", "ultimate total strain for tendon j"),
            _q(r"\varepsilon_{p,IS,j}", "locked-in initial strain for tendon j"),
            _q(r"s_{p,j}", "projected coordinate of tendon j", "m"),
        ),
        "Every candidate is a dimensionless strain divided by a metre distance, hence 1/m before the minimum is selected.",
        "project",
        "Project-defined capacity-search selector using retained material strain limits; no separate normative solver citation is assigned.",
    ),
    _spec(
        "manual.detailing.minimum-2005", "C5-1", "Reinforcement detailing",
        "EN 1992-1-1:2005 and DK NA:2024",
        "7e00772db83d146d7df046f67ea3d9830cd8f1c2210d0421e2dbf57c42265a6b",
        (
            _q(r"A_{s,min}", "required minimum longitudinal reinforcement area", "mm2"),
            _q(r"f_{ctm}", "mean concrete tensile strength", "MPa"),
            _q(r"f_{yk}", "characteristic reinforcement yield strength", "MPa"),
            _q(r"b_{t}", "mean width of the tension half", "mm"),
            _q("d", "effective depth", "mm"),
            _q(r"A_{s,prov}", "provided longitudinal reinforcement area", "mm2"),
        ),
        "The strength ratio is dimensionless and b_t d is mm2, so both required and provided areas compare in mm2.",
        "standard",
        "DS/EN 1992-1-1:2005 9.2.1.1(1), Formula (9.1N), with DK NA:2024 where selected.",
    ),
    _spec(
        "manual.detailing.minimum-2023-bending", "C5-2",
        "Reinforcement detailing", "EN 1992-1-1:2023",
        "a3e8a44022ab1eeac1eb1e85361b1735d337f4289aabfa4748a06a31eb7f8c9d",
        (
            _q(r"M_{R,nom}", "nominal cracking resistance at the applied axial action", "kNm"),
            _q(r"N_{Ed}", "design axial action", "kN"),
            _q(r"M_{cr}", "uncracked cracking action", "kNm"),
        ),
        "Both sides of the inequality are moments in kNm; N_Ed is the common kN argument to their reconstruction.",
        "standard",
        "DS/EN 1992-1-1:2023 minimum-reinforcement bending-with-axial-force method retained by Sector.",
    ),
    _spec(
        "manual.detailing.minimum-2023-axial", "C5-3",
        "Reinforcement detailing", "EN 1992-1-1:2023",
        "f52a3042781e1a85e83ae53f1e0031d3e5828a191421ba1c00bb968e81587822",
        (
            _q(r"A_{s,i}", "area of mild bar i", "mm2"),
            _q(r"f_{yk,i}", "characteristic yield strength of mild bar i", "MPa"),
            _q(r"A_{c}", "gross concrete area", "mm2"),
            _q(r"f_{ctm}", "mean concrete tensile strength", "MPa"),
        ),
        "Area in mm2 times MPa gives force in N on both sides of the inequality.",
        "standard",
        "DS/EN 1992-1-1:2023 direct-tension minimum-reinforcement method retained by Sector.",
    ),
    _spec(
        "manual.detailing.clear-spacing", "C5-4", "Reinforcement detailing",
        "Clear spacing",
        "f41ec7e90828e88a52fe0d33bb42a5637f4e92b874b2f3576f0c112b34bdfc46",
        (
            _q(r"c_{clear}", "clear distance between a checked element pair", "mm"),
            _q(r"\phi_{max}", "larger element diameter in the pair", "mm"),
            _q(r"D_{upper}", "entered upper aggregate size", "mm"),
        ),
        "All maximum candidates and the checked clear spacing are millimetres.",
        "standard",
        "DS/EN 1992-1-1:2005 8.2 clear-spacing rule retained by Sector.",
    ),
    _spec(
        "manual.detailing.links.minimum-ratio", "C5-5",
        "Reinforcement detailing", "Shear and torsion reinforcement",
        "e39e98501124b045f90745c456fc6947ff91331fae7c48b4a107c95e6f89536b",
        (
            _q(r"\rho_{w}", "provided shear-link ratio"),
            _q(r"A_{sw}", "area of active shear-link legs", "mm2"),
            _q("s", "longitudinal link spacing", "mm"),
            _q(r"b_{w}", "effective web breadth", "mm"),
            _q(r"\rho_{w,min}", "minimum link ratio"),
            _q("c", "edition coefficient multiplying square-root strength", "MPa^(1/2)"),
            _q(r"f_{ck}", "characteristic concrete compressive strength", "MPa"),
            _q(r"f_{ywk}", "characteristic link yield strength", "MPa"),
        ),
        "A_sw/(s b_w) is dimensionless. The coefficient c carries MPa^(1/2), so c sqrt(f_ck)/f_ywk is also dimensionless.",
        "standard",
        "Selected DS/EN 1992-1-1 and Danish National Annex minimum-link ratio; c is 0.063 MPa^(1/2) for the 2005 DK basis or 0.08 MPa^(1/2) for 2023.",
    ),
    _spec(
        "manual.detailing.links.spacing", "C5-6", "Reinforcement detailing",
        "Shear and torsion reinforcement",
        "46578627e65dc94444a986bcd27740da82bd1c07073227810451b24b18498144",
        (
            _q(r"s_{l}", "longitudinal shear-link spacing", "mm"),
            _q("d", "effective depth", "mm"),
            _q(r"s_{t}", "transverse shear-link spacing", "mm"),
        ),
        "Every spacing limit and effective depth is expressed in millimetres.",
        "standard",
        "Selected DS/EN 1992-1-1 shear-link spacing limits retained by Sector.",
    ),
    _spec(
        "manual.detailing.torsion.minimum-ratio", "C5-7",
        "Reinforcement detailing", "Shear and torsion reinforcement",
        "10d5445bf8ce120f10d189ac9cce5c24d2c6d3018f122cd1ae4cd680488f13e9",
        (
            _q(r"\rho_{w,T}", "provided torsion-wall link ratio"),
            _q(r"A_{leg}", "area of one closed-link leg", "mm2"),
            _q("s", "longitudinal closed-link spacing", "mm"),
            _q(r"t_{ef}", "effective torsion-wall thickness", "mm"),
            _q(r"\rho_{w,min}", "minimum link ratio"),
        ),
        "A_leg/(s t_ef) is dimensionless and is compared with the dimensionless minimum ratio from Equation C5-5.",
        "standard",
        "Selected DS/EN 1992-1-1 torsion-link detailing rule retained by Sector.",
        ("manual.detailing.links.minimum-ratio",),
    ),
    _spec(
        "manual.crack.2005.width", "C7-1",
        "Serviceability: cracking and crack width",
        "Crack width - EN 1992-1-1:2005",
        "4451827db7ec3ec1f7c7f07f3660b6ba6cf2cb44dd35f56b63595a2d594bfc42",
        (
            _q(r"w_{k}", "characteristic crack width", "mm"),
            _q(r"s_{r,max}", "maximum crack spacing", "mm"),
            _q(r"\varepsilon_{sm}", "mean reinforcement strain"),
            _q(r"\varepsilon_{cm}", "mean concrete strain between cracks"),
            _q(r"\sigma_{s}", "reinforcement stress", "MPa"),
            _q(r"k_{t}", "load-duration factor"),
            _q(r"f_{ct,eff}", "effective concrete tensile strength", "MPa"),
            _q(r"\rho_{p,eff}", "effective reinforcement ratio"),
            _q(r"\alpha_{e}", "modular ratio"),
            _q(r"E_{s}", "reinforcement modulus", "MPa"),
        ),
        "Both strain-difference candidates are dimensionless; multiplying the governing strain by s_r,max in mm gives w_k in mm.",
        "standard",
        "DS/EN 1992-1-1:2005 7.3.4, Formulas (7.8) and (7.9).",
        ("manual.crack.2005.spacing",),
    ),
    _spec(
        "manual.crack.2005.spacing", "C7-2",
        "Serviceability: cracking and crack width",
        "Crack width - EN 1992-1-1:2005",
        "e674c66afb21190f639015cce8da6a954fdcc19f8ddd326020667e25536c8fe3",
        (
            _q(r"s_{r,max}", "maximum crack spacing", "mm"),
            _q(r"k_{3}", "cover coefficient"),
            _q("c", "cover to reinforcement", "mm"),
            _q(r"k_{1}", "bond coefficient"),
            _q(r"k_{2}", "strain-distribution coefficient"),
            _q(r"k_{4}", "recommended crack-spacing coefficient"),
            _q(r"\phi", "reinforcement diameter", "mm"),
            _q(r"\rho_{p,eff}", "effective reinforcement ratio"),
            _q("h", "section depth", "mm"),
            _q("x", "neutral-axis depth", "mm"),
        ),
        "Each branch is a sum or product of millimetre lengths and dimensionless coefficients, so s_r,max is in mm.",
        "standard",
        "DS/EN 1992-1-1:2005 Formulas (7.11) and (7.14), with the selected Danish National Annex cover rule where applicable.",
    ),
    _spec(
        "manual.crack.2023.width", "C7-3",
        "Serviceability: cracking and crack width",
        "EN 1992-1-1:2023 refined model",
        "4c15d71e9d8e368108149af68afc41acc767712cd71aa1ad7af0223bb5ae3d10",
        (
            _q(r"w_{k}", "characteristic crack width", "mm"),
            _q(r"k_{w}", "crack-width coefficient"),
            _q(r"k_{1}", "bar curvature numerator", "mm"),
            _q("r", "bar curvature denominator", "mm"),
            _q(r"s_{r,m,cal}", "calculated mean crack spacing", "mm"),
            _q(r"\varepsilon_{sm}", "mean reinforcement strain"),
            _q(r"\varepsilon_{cm}", "mean concrete strain between cracks"),
            _q("h", "section depth", "mm"),
            _q("x", "neutral-axis depth", "mm"),
            _q(r"a_{y,i}", "bar-specific distance in the curvature factor", "mm"),
        ),
        "k_1/r and the strain difference are dimensionless; multiplying by s_r,m,cal in mm gives w_k in mm.",
        "standard",
        "DS/EN 1992-1-1:2023 9.2.3, including the bar curvature factor in Formula (9.9).",
        ("manual.crack.2023.spacing",),
    ),
    _spec(
        "manual.crack.2023.spacing", "C7-4",
        "Serviceability: cracking and crack width",
        "EN 1992-1-1:2023 refined model",
        "3232760c0b31c26275f004adf2bf978d25bf8452b182b6966e3bfeb455cae8ea",
        (
            _q(r"s_{r,m,cal}", "calculated mean crack spacing", "mm"),
            _q("c", "cover to reinforcement", "mm"),
            _q(r"k_{fl}", "flexural coefficient"),
            _q(r"k_{b}", "bond coefficient"),
            _q(r"\phi", "reinforcement diameter", "mm"),
            _q(r"\rho_{p,eff}", "effective reinforcement ratio"),
            _q(r"k_{w}", "crack-width coefficient"),
            _q("h", "section depth", "mm"),
            _q("x", "neutral-axis depth", "mm"),
        ),
        "Both the calculated branch and upper bound are millimetre lengths multiplied by dimensionless coefficients.",
        "standard",
        "DS/EN 1992-1-1:2023 Formula (9.15), with retained Formulas (9.16)-(9.18) inputs.",
    ),
    _spec(
        "manual.fatigue.stress-range", "C8-1", "Grouped fatigue",
        "Elastic stress ranges",
        "1c6d20674b30556d5158662f2eed158f78f16c0ec52b6134bf9ee4e728707878",
        (
            _q(r"\Delta\sigma_{Ed,i}", "design stress range in spectrum bin i", "MPa"),
            _q(r"\sigma", "retained Elastic stress response", "MPa"),
            _q(r"S_{l}", "sustained action state", "actions"),
            _q(r"\gamma_{Ff}", "fatigue action factor"),
            _q(r"S_{s}", "cyclic action increment", "actions"),
        ),
        "The factored action sum is evaluated by the same MPa stress response; the absolute difference of the two stresses is MPa.",
        "mixed",
        "Project-defined replay of retained Elastic states with the fatigue action factor supplied by the selected standard method.",
    ),
    _spec(
        "manual.fatigue.reinforcement.design-range", "C8-2",
        "Grouped fatigue", "Reinforcement S-N and Miner check",
        "79409e2d84eb04d50e0b3ecdb1a23cbaee4988c086d4d63375c8dc87267f5514",
        (
            _q(r"\Delta\sigma_{Rd}", "design reference stress range", "MPa"),
            _q(r"\Delta\sigma_{Rsk}", "characteristic reference stress range", "MPa"),
            _q(r"\gamma_{s}", "fatigue-strength partial factor"),
        ),
        "A stress range in MPa divided by a dimensionless partial factor remains MPa.",
        "standard",
        "Selected DS/EN 1992 reinforcement-fatigue S-N detail and partial-factor basis.",
    ),
    _spec(
        "manual.fatigue.reinforcement.life", "C8-3", "Grouped fatigue",
        "Reinforcement S-N and Miner check",
        "525ca21ac74aa72c0202fba278ff55bfc0e4c951c7c4b29a1d0776e657bad217",
        (
            _q(r"N_{R,i}", "resistance life for spectrum bin i", "cycles"),
            _q(r"N^*", "reference S-N knee life", "cycles"),
            _q(r"\Delta\sigma_{Rd}", "design reference stress range", "MPa"),
            _q(r"\Delta\sigma_{Ed,i}", "design stress range in spectrum bin i", "MPa"),
            _q("k", "active S-N slope"),
        ),
        "The MPa stress ratio and its power are dimensionless, so multiplying by N^* retains cycles.",
        "standard",
        "Selected DS/EN 1992 reinforcement-fatigue two-slope S-N relation.",
        ("manual.fatigue.reinforcement.design-range",),
    ),
    _spec(
        "manual.fatigue.reinforcement.miner", "C8-4", "Grouped fatigue",
        "Reinforcement S-N and Miner check",
        "ace577b8ce30e7129bda1cc84198419a4fea29b0472f100afe793caddca79564",
        (
            _q("D", "accumulated Miner damage"),
            _q(r"n_{i}", "applied cycles in spectrum bin i", "cycles"),
            _q(r"N_{R,i}", "resistance life for spectrum bin i", "cycles"),
        ),
        "Each cycles/cycles fraction and their sum are dimensionless.",
        "standard",
        "Palmgren-Miner damage accumulation used by the selected DS/EN 1992 fatigue method.",
        ("manual.fatigue.reinforcement.life",),
    ),
    _spec(
        "manual.fatigue.concrete.strength-2005", "C8-5", "Grouped fatigue",
        "Concrete compression fatigue",
        "5123cf1171bbf2a16ddc81bf351ebaff1c8aa4f26bdec70f846f81f1a1b68ce9",
        (
            _q(r"f_{cd,fat}", "design concrete fatigue strength", "MPa"),
            _q(r"k_{1}", "fatigue strength coefficient"),
            _q(r"\beta_{cc}", "strength-development factor"),
            _q(r"t_{0}", "concrete age at first fatigue loading", "days"),
            _q(r"\alpha_{cc}", "long-term strength coefficient"),
            _q(r"f_{ck}", "characteristic concrete compressive strength", "MPa"),
            _q(r"\gamma_{c,fat}", "concrete fatigue partial factor"),
        ),
        "All coefficients are dimensionless; the literal 250 carries MPa, making the final bracket dimensionless and f_cd,fat MPa.",
        "standard",
        "DS/EN 1992-1-1:2005 concrete-compression fatigue strength basis retained by Sector.",
    ),
    _spec(
        "manual.fatigue.concrete.strength-2023", "C8-6", "Grouped fatigue",
        "Concrete compression fatigue",
        "85e38c135904be5a3507e919a0649d9c209549ebb4ee3f0875ac978984e09eda",
        (
            _q(r"\eta_{cc}", "concrete strength reduction factor"),
            _q(r"f_{ck}", "characteristic concrete compressive strength", "MPa"),
            _q(r"\eta_{cc,fat}", "fatigue concrete reduction factor"),
            _q(r"f_{cd,fat}", "design concrete fatigue strength", "MPa"),
            _q(r"\beta_{cc}", "strength-development factor"),
            _q(r"t_{0}", "concrete age at first fatigue loading", "days"),
            _q(r"\gamma_{c,fat}", "concrete fatigue partial factor"),
        ),
        "The literal 40 carries MPa, so 40/f_ck and both eta factors are dimensionless; the final strength remains MPa.",
        "standard",
        "DS/EN 1992-1-1:2023 concrete-compression fatigue strength basis retained by Sector.",
    ),
    _spec(
        "manual.fatigue.concrete.life", "C8-7", "Grouped fatigue",
        "Concrete compression fatigue",
        "5a8cca7a9e50c8a23d37882d0fb575d459dcd187d9fd4e2a4c580da5cf154528",
        (
            _q(r"N_{R}", "concrete fatigue resistance life", "cycles"),
            _q("C", "selected concrete fatigue-life coefficient"),
            _q(r"E_{max}", "maximum normalized concrete compression stress"),
            _q("R", "minimum-to-maximum concrete stress ratio"),
        ),
        "The logarithm uses the numerical cycle count and its right-hand side is dimensionless; N_R is reported in cycles.",
        "standard",
        "Selected DS/EN 1992 concrete-compression fatigue life relation retained by Sector.",
    ),
    _spec(
        "manual.fatigue.concrete.equivalent", "C8-8", "Grouped fatigue",
        "Concrete compression fatigue",
        "4a70d70fdded41c242471c53a26554257d8444562547f5763c882c00a137bdcf",
        (
            _q(r"E_{max}", "maximum normalized concrete compression stress"),
            _q(r"E_{min}", "minimum normalized concrete compression stress"),
        ),
        "Both normalized stress levels, their ratio, the square root and the utilization are dimensionless.",
        "standard",
        "Selected DS/EN 1992 damage-equivalent concrete-compression fatigue criterion retained by Sector.",
    ),
    _spec(
        "manual.shear.no-links.variable", "C9-1",
        "Shear resistance without shear reinforcement", "",
        "e5a101ffeb8ed99a3ad22d269c843d73ab17a4830858ddcec135b958a9d0ee6c",
        (
            _q(r"V_{Rd,c}", "design shear resistance without links", "kN"),
            _q(r"C_{Rd,c}", "empirical shear coefficient", "MPa^(2/3)"),
            _q("k", "size-effect factor"),
            _q(r"\rho_{l}", "longitudinal tension-reinforcement ratio"),
            _q(r"f_{ck}", "characteristic concrete compressive strength", "MPa"),
            _q(r"k_{1}", "axial-stress coefficient"),
            _q(r"\sigma_{cp}", "mean axial concrete compression stress", "MPa"),
            _q(r"b_{w}", "effective web breadth", "mm"),
            _q("d", "effective depth", "mm"),
        ),
        "C_Rd,c carries MPa^(2/3), so its product with f_ck^(1/3) is MPa and can be added to k_1 sigma_cp; MPa mm2 is converted from N to kN.",
        "standard",
        "DS/EN 1992-1-1:2005 Formula (6.2a), including the selected National Annex coefficient convention.",
    ),
    _spec(
        "manual.shear.no-links.minimum", "C9-2",
        "Shear resistance without shear reinforcement", "",
        "1279f09a95518892baa612be76e48350f9cf565aed5efd94aecadcf165c7cc67",
        (
            _q(r"V_{Rd,c}", "minimum design shear resistance without links", "kN"),
            _q(r"v_{min}", "minimum shear stress", "MPa"),
            _q(r"k_{1}", "axial-stress coefficient"),
            _q(r"\sigma_{cp}", "mean axial concrete compression stress", "MPa"),
            _q(r"b_{w}", "effective web breadth", "mm"),
            _q("d", "effective depth", "mm"),
        ),
        "The bracket is MPa and b_w d is mm2; the resulting N is converted to kN.",
        "standard",
        "DS/EN 1992-1-1:2005 Formula (6.2b), including the selected National Annex v_min convention.",
    ),
    _spec(
        "manual.shear.action-factor-2023", "C9-3",
        "Shear resistance without shear reinforcement", "",
        "57910d0569783bc00ef2c62b0755400dc51059b6ffd96017e3f7b50d92a5190d",
        (
            _q(r"a_{cs}", "shear action length", "m"),
            _q(r"M_{Ed}", "design bending action", "kNm"),
            _q(r"V_{Ed}", "design shear action", "kN"),
            _q("d", "effective depth converted from the stored millimetre value", "m"),
            _q(r"k_{vp}", "axial-force shear factor"),
            _q(r"N_{Ed}", "design axial action, tension positive", "kN"),
        ),
        "M_Ed/V_Ed and d are both metres, so a_cs is metres; both force and length ratios in k_vp are dimensionless.",
        "standard",
        "DS/EN 1992-1-1:2023 Formula (8.27) action-dependent shear factor retained by Sector.",
    ),
    _spec(
        "manual.shear.links-2005", "C9-4",
        "Shear resistance without shear reinforcement",
        "Members with shear reinforcement (links)",
        "8bbbf0a6261d72eea45965ba33b6b45bb65ff56f67fa308f8020f7f01598aed7",
        (
            _q(r"V_{Rd,s}", "link-controlled shear resistance", "kN"),
            _q(r"A_{sw}", "area of active shear-link legs", "mm2"),
            _q("s", "longitudinal link spacing", "mm"),
            _q("z", "internal lever arm", "mm"),
            _q(r"f_{ywd}", "design link yield strength", "MPa"),
            _q(r"\theta", "compression-strut angle", "degrees"),
            _q(r"V_{Rd,max}", "concrete-strut shear resistance", "kN"),
            _q(r"\alpha_{cw}", "chord compression factor"),
            _q(r"b_{w}", "effective web breadth", "mm"),
            _q(r"\nu_{1}", "shear strut effectiveness factor"),
            _q(r"f_{cd}", "design concrete compressive strength", "MPa"),
        ),
        "A_sw/s times z times MPa and b_w z times MPa both give N; Sector converts each resistance to kN before comparison.",
        "standard",
        "DS/EN 1992-1-1:2005 Formulas (6.8) and (6.9), with the selected National Annex factors and angle limits.",
    ),
    _spec(
        "manual.shear.links-2023", "C9-5",
        "Shear resistance without shear reinforcement",
        "Members with shear reinforcement (links)",
        "85cfe8d83d492a4af5a911a3a7c1dc332f88dcf75ae2b1434c6ed6fef91d3439",
        (
            _q(r"\tau_{Rd,sy}", "link-controlled shear stress", "MPa"),
            _q(r"\rho_{w}", "provided shear-link ratio"),
            _q(r"f_{ywd}", "design link yield strength", "MPa"),
            _q(r"\theta", "compression-strut angle", "degrees"),
            _q(r"\sigma_{cd}", "compression-field stress", "MPa"),
            _q(r"\tau_{Ed}", "design shear stress", "MPa"),
            _q(r"\nu", "concrete strut effectiveness factor"),
            _q(r"f_{cd}", "design concrete compressive strength", "MPa"),
        ),
        "All trigonometric terms and ratios are dimensionless, leaving every stress term in MPa.",
        "standard",
        "DS/EN 1992-1-1:2023 Formulas (8.42) and (8.44).",
        ("manual.detailing.links.minimum-ratio",),
    ),
    _spec(
        "manual.torsion.resistance", "C10-1", "Torsion (thin-walled tube)", "",
        "a5291e17e74a23e3ec4f59d6a894be40eb72247ab67a266cb5f0a7d14667bff6",
        (
            _q(r"T_{Rd,s}", "link-controlled torsion resistance", "kNm"),
            _q(r"A_{sw}", "area of one closed-link leg", "mm2"),
            _q("s", "longitudinal closed-link spacing", "mm"),
            _q(r"A_{k}", "area enclosed by the effective shear-flow centreline", "m2"),
            _q(r"f_{ywd}", "design link yield strength", "MPa"),
            _q(r"\theta", "torsion compression-strut angle", "degrees"),
            _q(r"T_{Rd,max}", "concrete-strut torsion resistance", "kNm"),
            _q(r"\nu", "torsion strut effectiveness factor"),
            _q(r"\alpha_{cw}", "chord compression factor"),
            _q(r"f_{cd}", "design concrete compressive strength", "MPa"),
            _q(r"t_{ef}", "effective torsion-wall thickness", "m"),
        ),
        "A_sw/s is retained in mm2/mm while A_k is m2 and f_ywd is MPa; the solver's explicit mixed-unit conversion gives kNm. The strut branch uses MPa m2 m and is likewise converted to kNm.",
        "standard",
        "DS/EN 1992-1-1:2005 torsional wall shear flow Formula (6.27), transverse equilibrium Formula (6.8), and concrete-strut Formula (6.30).",
    ),
    _spec(
        "manual.torsion.strut-interaction", "C10-2",
        "Torsion (thin-walled tube)", "",
        "0fde836b7555c3d5e63a45cc971b43eb8b53aeb68405c7294673b1704575b79b",
        (
            _q(r"T_{Ed}", "design torsion action", "kNm"),
            _q(r"T_{Rd,max}", "concrete-strut torsion resistance", "kNm"),
            _q(r"V_{Ed}", "design shear action", "kN"),
            _q(r"V_{Rd,max}", "concrete-strut shear resistance", "kN"),
        ),
        "Each demand/resistance ratio is dimensionless before the two interaction terms are added.",
        "standard",
        "DS/EN 1992-1-1:2005 Formula (6.29).",
        ("manual.torsion.resistance", "manual.shear.links-2005"),
    ),
    _spec(
        "manual.combined.strut-interaction", "C11-1",
        "Combined M-V-T interaction", "",
        "0fde836b7555c3d5e63a45cc971b43eb8b53aeb68405c7294673b1704575b79b",
        (
            _q(r"T_{Ed}", "design torsion action", "kNm"),
            _q(r"T_{Rd,max}", "concrete-strut torsion resistance", "kNm"),
            _q(r"V_{Ed}", "design shear action", "kN"),
            _q(r"V_{Rd,max}", "concrete-strut shear resistance", "kN"),
        ),
        "Each demand/resistance ratio is dimensionless before the two interaction terms are added.",
        "standard",
        "DS/EN 1992-1-1:2005 Formula (6.29), reused in the combined assessment.",
        ("manual.torsion.strut-interaction",),
    ),
    _spec(
        "manual.combined.utilisation", "C11-2",
        "Combined M-V-T interaction", "",
        "850bd52dcea64b9e779bc904fa701d42d2d47657af17ea0f1ab0f32263f3ab8b",
        (
            _q(r"S_{Ed}", "design demand for one checked action family", "actions"),
            _q(r"S_{Rd}", "standalone resistance for the same action family", "actions"),
        ),
        "Every numerator and denominator are matching action quantities, so every ratio and their sum are dimensionless.",
        "standard",
        "DK NA:2024 6.3.2(6) interaction form as retained by Sector.",
    ),
)

_FROZEN_INVENTORY_SHA256 = {
    "identity": "f225373dafbe17de1b14d9451ce5aa954e9a2db273edf78c43b81c5090d7e5e8",
    "sources": "b5f89bef1fff29aee683cef9313f453a6d057649c16c61cc220aeba7450be9c1",
    "symbols": "e23f42d7f5805311a4f3ac9205f2670c42e4f6c04bf8388fe9e2fb3c5b556ce1",
    "dimensions": "3c4cf16f8cfa2f89c0af952b495eae9b0949dd7fdbc939c8ff9ad664ca2b4887",
    "dependencies": "566c401f3b6aa3e5fb3f53ef85ebcfa00081bf547fa7a94410e47e919de1fc4c",
}


def _normalise_expression(expression: str) -> str:
    return " ".join(expression.split())


def _expression_sha256(expression: str) -> str:
    return hashlib.sha256(expression.encode("ascii")).hexdigest()


def equation_symbol_tokens(expression: str) -> tuple[str, ...]:
    """Return ordered semantic symbols from one accepted LaTeX expression."""

    value = re.sub(r"\\text\{[^{}]*\}", " ", expression)
    composite_spans = []
    positioned_tokens = []
    for match in re.finditer(
        r"\\Delta\\sigma(?:_\{([^{}]*)\}|_([A-Za-z0-9.,]+))?", value
    ):
        subscript = (match.group(1) or match.group(2) or "").rstrip(".,;")
        token = r"\Delta\sigma" + (f"_{{{subscript}}}" if subscript else "")
        positioned_tokens.append((match.start(), token))
        composite_spans.append(match.span())
    for start, end in reversed(composite_spans):
        value = value[:start] + " " * (end - start) + value[end:]

    pattern = re.compile(
        r"\\([A-Za-z]+)(?:_\{([^{}]*)\}|_([A-Za-z0-9.,]+))?"
        r"|([A-Za-z])(?:_\{([^{}]*)\}|_([A-Za-z0-9.,]+))?(\^\*)?"
    )
    for match in pattern.finditer(value):
        command = match.group(1)
        if command is not None:
            if command in _IGNORED_COMMANDS:
                continue
            base = "\\" + command
            subscript = match.group(2) or match.group(3) or ""
            suffix = ""
        else:
            base = match.group(4)
            subscript = match.group(5) or match.group(6) or ""
            suffix = match.group(7) or ""
        subscript = subscript.rstrip(".,;")
        token = base + (f"_{{{subscript}}}" if subscript else "") + suffix
        positioned_tokens.append((match.start(), token))
    tokens = []
    for _position, token in sorted(positioned_tokens):
        if token not in tokens:
            tokens.append(token)
    return tuple(tokens)


def _inventory_sha256_for(specs: Sequence[ManualEquationSpec], field: str) -> str:
    if field == "identity":
        rows = (
            f"{spec.key}|{spec.number}|{spec.part}|{spec.section}|"
            f"{spec.subsection}|{spec.expression_sha256}"
            for spec in specs
        )
    elif field == "sources":
        rows = (f"{spec.key}|{spec.source_kind}|{spec.source}" for spec in specs)
    elif field == "symbols":
        rows = (
            f"{spec.key}|{symbol.latex}|{symbol.meaning}|{symbol.unit}"
            for spec in specs for symbol in spec.symbols
        )
    elif field == "dimensions":
        rows = (f"{spec.key}|{spec.dimensional_note}" for spec in specs)
    elif field == "dependencies":
        rows = (f"{spec.key}|{','.join(spec.uses)}" for spec in specs)
    else:
        raise ValueError(f"Unknown manual equation inventory field: {field!r}.")
    return hashlib.sha256("\n".join(rows).encode("ascii")).hexdigest()


def _validate_specs(specs: Sequence[ManualEquationSpec]) -> None:
    if len(specs) != 32:
        raise ValueError("The Part C contract must contain exactly 32 equations.")
    keys = tuple(spec.key for spec in specs)
    numbers = tuple(spec.number for spec in specs)
    if len(set(keys)) != len(keys) or any(not _KEY_RE.fullmatch(key) for key in keys):
        raise ValueError("Manual equation keys must be unique and canonical.")
    if len(set(numbers)) != len(numbers) or any(
        not _NUMBER_RE.fullmatch(number) for number in numbers
    ):
        raise ValueError("Manual equation numbers must be unique and section-based.")
    for spec in specs:
        if spec.part != _PART_C or not spec.section:
            raise ValueError(f"{spec.key} has an invalid manual location.")
        if not re.fullmatch(r"[0-9a-f]{64}", spec.expression_sha256):
            raise ValueError(f"{spec.key} has an invalid expression digest.")
        if spec.source_kind not in _SOURCE_KINDS or not spec.source.strip():
            raise ValueError(f"{spec.key} has incomplete source identity.")
        if not spec.dimensional_note.strip() or not spec.symbols:
            raise ValueError(f"{spec.key} has an incomplete dimensional contract.")
        symbol_names = tuple(symbol.latex for symbol in spec.symbols)
        if len(set(symbol_names)) != len(symbol_names):
            raise ValueError(f"{spec.key} has duplicate local symbols.")
        for symbol in spec.symbols:
            if not symbol.latex or not symbol.meaning.strip() or symbol.unit not in _UNITS:
                raise ValueError(f"{spec.key} has an invalid symbol definition.")
        if len(set(spec.uses)) != len(spec.uses) or spec.key in spec.uses:
            raise ValueError(f"{spec.key} has invalid dependency links.")
        if any(target not in keys for target in spec.uses):
            raise ValueError(f"{spec.key} references an unknown equation.")
    for field, expected in _FROZEN_INVENTORY_SHA256.items():
        if _inventory_sha256_for(specs, field) != expected:
            raise ValueError(f"The frozen manual equation {field} inventory changed.")


def _source_equations(blocks: Iterable[Sequence[object]]):
    part = section = subsection = ""
    for block in blocks:
        if not block:
            raise ValueError("Manual publication blocks cannot contain empty items.")
        kind = block[0]
        if kind == "part":
            part = str(block[1])
            section = subsection = ""
        elif kind == "h1":
            section = str(block[1])
            subsection = ""
        elif kind == "h2":
            subsection = str(block[1])
        elif kind == "md":
            for expression in _DISPLAY_EQUATION_RE.findall(str(block[1])):
                yield part, section, subsection, _normalise_expression(expression)


def register_manual_equations(
    blocks: Iterable[Sequence[object]],
    specs: Sequence[ManualEquationSpec] = MANUAL_EQUATION_SPECS,
) -> tuple[RegisteredManualEquation, ...]:
    """Seal accepted manual blocks to the complete immutable equation contract."""

    specs = tuple(specs)
    _validate_specs(specs)
    source = tuple(_source_equations(blocks))
    if len(source) != len(specs):
        raise ValueError(
            f"Manual equation cardinality changed: expected {len(specs)}, got {len(source)}."
        )
    registered = []
    for spec, (part, section, subsection, expression) in zip(specs, source):
        if (part, section, subsection) != (spec.part, spec.section, spec.subsection):
            raise ValueError(f"Manual equation {spec.key} moved from its frozen location.")
        if _expression_sha256(expression) != spec.expression_sha256:
            raise ValueError(f"Manual equation {spec.key} expression changed.")
        expected_symbols = tuple(symbol.latex for symbol in spec.symbols)
        actual_symbols = equation_symbol_tokens(expression)
        if actual_symbols != expected_symbols:
            raise ValueError(
                f"Manual equation {spec.key} symbol inventory changed: "
                f"expected {expected_symbols!r}, got {actual_symbols!r}."
            )
        registered.append(RegisteredManualEquation(spec, expression))
    return tuple(registered)


def inventory_sha256(field: str) -> str:
    """Return a stable seal for one complete advertised registry field."""

    return _inventory_sha256_for(MANUAL_EQUATION_SPECS, field)


_validate_specs(MANUAL_EQUATION_SPECS)
