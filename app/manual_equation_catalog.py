"""Immutable semantic catalogue for the authored manual display equations.

The equations remain authored exactly once in :mod:`manual`.  This module pins
their publication identity, position, expression digest, symbols, provenance and
genuine prior-equation dependencies without copying the formula text.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable


_KEY_RE = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_DISPLAY_EQUATION_RE = re.compile(r"\$\$(.+?)\$\$([.,;:]?)", re.DOTALL)
_SOURCE_KINDS = frozenset(("standard", "mixed", "project"))
_PART_C = "Part C - Theory & methodology"
_PROJECT_SOURCE = "Project-defined / uncited."


_UNIT_LATEX = {
    "dimensionless": "1",
    "MPa": r"\text{MPa}",
    "mm": r"\text{mm}",
    "mm2": r"\text{mm}^2",
    "mm2/mm": r"\text{mm}^2/\text{mm}",
    "m": r"\text{m}",
    "1/m": r"\text{m}^{-1}",
    "kN": r"\text{kN}",
    "kNm": r"\text{kN}\,\text{m}",
    "degrees": r"{}^{\circ}",
    "cycles": r"\text{cycles}",
    "days": r"\text{days}",
    "action-specific": r"\text{action-specific}",
}


@dataclass(frozen=True, slots=True)
class ManualEquationSymbol:
    """One exact symbol definition shown below a manual equation."""

    latex: str
    meaning: str
    unit: str = "dimensionless"


@dataclass(frozen=True, slots=True)
class ManualEquationContract:
    """Complete publication identity for one authored display equation."""

    key: str
    number: str
    part: str
    section: str
    subsection: str | None
    expression_sha256: str
    symbols: tuple[ManualEquationSymbol, ...]
    source_kind: str
    source: str
    uses: tuple[str, ...] = ()

    @property
    def public_id(self) -> str:
        return "MEQ-" + self.key.upper()

    @property
    def anchor(self) -> str:
        return "manual-equation-" + self.key.replace(".", "__")


@dataclass(frozen=True, slots=True)
class ManualEquationOccurrence:
    """One validated equation occurrence bound to its immutable contract."""

    contract: ManualEquationContract
    expression: str
    punctuation: str


@dataclass(frozen=True, slots=True)
class ManualMarkdownSegment:
    """Exact contiguous Markdown, optionally carrying one equation occurrence."""

    markdown: str
    equation: ManualEquationOccurrence | None = None


def _s(latex: str, meaning: str, unit: str = "dimensionless") -> ManualEquationSymbol:
    return ManualEquationSymbol(latex, meaning, unit)


def _e(
    key: str,
    number: str,
    section: str,
    subsection: str | None,
    expression_sha256: str,
    symbols: tuple[ManualEquationSymbol, ...],
    source_kind: str,
    source: str,
    *,
    uses: tuple[str, ...] = (),
) -> ManualEquationContract:
    return ManualEquationContract(
        key, number, _PART_C, section, subsection, expression_sha256,
        symbols, source_kind, source, uses,
    )


_CONTRACTS = (
    _e(
        "materials.concrete.curve-2", "C.3.1-1", "Material laws",
        "Concrete (parabola-rectangle)",
        "9056b4525fcd292ebd5769b7277ae491522d54ea6e8ee60f79d4ee0af2da6477",
        (
            _s(r"\sigma_c", "concrete compressive stress", "MPa"),
            _s(r"f_{cd}", "design concrete compressive strength", "MPa"),
            _s(r"\varepsilon_c", "concrete compressive strain"),
            _s(r"\varepsilon_{c2}", "strain at the start of the plateau"),
            _s(r"\varepsilon_{cu2}", "ultimate concrete compressive strain"),
            _s("n", "parabola exponent"),
        ),
        "standard",
        "DS/EN 1992-1-1 3.1.7, Formula (3.17), and Table 3.1; "
        "EN 1992-1-1:2023 8.1.2(1), Formula (8.4), with the design-strength "
        "factors in 5.1.6(1).",
    ),
    _e(
        "materials.steel.initial-branch", "C.3.2-1", "Material laws",
        "Mild steel",
        "5972f92c2cf2dd2c16ab580e95c70f98ebe947a2baaef960c67252ac294a9c11",
        (
            _s(r"\sigma_s", "mild-steel stress", "MPa"),
            _s(r"E_{s,d}", "design elastic modulus of mild steel", "MPa"),
            _s(r"\varepsilon_s", "mild-steel strain"),
            _s(r"\varepsilon_{yd}", "design yield strain"),
            _s(r"f_{yd}", "design yield strength", "MPa"),
            _s(r"f_{yk}", "characteristic yield strength", "MPa"),
            _s(r"\gamma_s", "partial factor for reinforcement strength"),
        ),
        "mixed",
        "DS/EN 1992-1-1 3.2.7 for edition presets; the generic Curve 2 "
        "relation remains Project-defined / uncited.",
    ),
    _e(
        "materials.prestress.total-strain", "C.3.3-1", "Material laws",
        "Prestressing steel",
        "e61a85aca0ae68096eae6d42740d5e556e839b765c69ec57f61ecc5c146cbaa5",
        (
            _s(r"\varepsilon_{p,j}", "total strain of tendon j"),
            _s(r"\varepsilon_{p,IS,j}", "locked-in initial strain of tendon j"),
            _s(r"\kappa", "section curvature", "1/m"),
            _s(r"s_{p,j}", "tendon-j coordinate on the strain gradient", "m"),
            _s(r"s_{na}", "neutral-axis coordinate", "m"),
            _s(r"\sigma_p", "prestressing-steel stress", "MPa"),
            _s(r"f(\varepsilon_p)", "selected tendon stress-strain law", "MPa"),
            _s(r"f_{pd}", "design tendon proof strength", "MPa"),
            _s(r"f_{p0.1k}", "characteristic 0.1 percent proof strength", "MPa"),
            _s(r"\gamma_s", "partial factor for prestressing steel"),
            _s("j", "tendon index"),
        ),
        "mixed",
        "Project-defined / uncited plane-section strain compatibility; "
        "DS/EN 1992-1-1 3.3.6 supplies the selected tendon-law strength relation.",
    ),
    _e(
        "plastic.governing-curvature", "C.4.2-1", "Plastic capacity analysis",
        "The governing curvature",
        "a9125f6b7747160f86ebfe580b489be8e94a3719ff435f274d411ee1cb1c5cda",
        (
            _s(r"\kappa", "governing section curvature", "1/m"),
            _s(r"\varepsilon_{cu2}", "ultimate concrete compressive strain"),
            _s("c", "concrete compression depth", "m"),
            _s(r"\varepsilon_{u,i}", "ultimate strain of mild bar i"),
            _s(r"s_{na}", "neutral-axis coordinate", "m"),
            _s(r"s_{b,i}", "coordinate of mild bar i", "m"),
            _s(r"\varepsilon_{pu,j}", "ultimate total strain of tendon j"),
            _s(r"\varepsilon_{p,IS,j}", "locked-in initial strain of tendon j"),
            _s(r"s_{p,j}", "coordinate of tendon j", "m"),
            _s("i", "mild-bar index"),
            _s("j", "tendon index"),
        ),
        "project", _PROJECT_SOURCE,
    ),
    _e(
        "detailing.minimum.2005", "C.5.1-1", "Reinforcement detailing",
        "EN 1992-1-1:2005 and DK NA:2024",
        "7e00772db83d146d7df046f67ea3d9830cd8f1c2210d0421e2dbf57c42265a6b",
        (
            _s(r"A_{s,min}", "required minimum tension reinforcement", "mm2"),
            _s(r"f_{ctm}", "mean concrete tensile strength", "MPa"),
            _s(r"f_{yk}", "characteristic reinforcement strength", "MPa"),
            _s(r"b_t", "mean width of the resultant tension zone", "mm"),
            _s("d", "effective depth normal to the neutral line", "mm"),
            _s(r"A_{s,prov}", "provided tension reinforcement", "mm2"),
        ),
        "standard",
        "DS/EN 1992-1-1 9.2.1.1(1), Formula (9.1N); DK NA:2024.",
    ),
    _e(
        "detailing.minimum.2023-bending", "C.5.2-1", "Reinforcement detailing",
        "EN 1992-1-1:2023",
        "a3e8a44022ab1eeac1eb1e85361b1735d337f4289aabfa4748a06a31eb7f8c9d",
        (
            _s(r"M_{R,nom}", "nominal moment resistance", "kNm"),
            _s(r"M_{cr}", "cracking moment", "kNm"),
            _s(r"N_{Ed}", "applied design axial force", "kN"),
        ),
        "standard",
        "DS/EN 1992-1-1:2023 12.2(2)(a), Formula (12.1).",
    ),
    _e(
        "detailing.minimum.2023-tension", "C.5.2-2", "Reinforcement detailing",
        "EN 1992-1-1:2023",
        "f52a3042781e1a85e83ae53f1e0031d3e5828a191421ba1c00bb968e81587822",
        (
            _s(r"A_{s,i}", "area of mild bar i", "mm2"),
            _s(r"f_{yk,i}", "characteristic strength of mild bar i", "MPa"),
            _s(r"A_c", "gross concrete area", "mm2"),
            _s(r"f_{ctm}", "mean concrete tensile strength", "MPa"),
            _s("i", "mild-bar index"),
        ),
        "standard",
        "DS/EN 1992-1-1:2023 12.2(2)(b), Formula (12.2).",
    ),
    _e(
        "detailing.clear-spacing", "C.5.3-1", "Reinforcement detailing",
        "Clear spacing",
        "f41ec7e90828e88a52fe0d33bb42a5637f4e92b874b2f3576f0c112b34bdfc46",
        (
            _s(r"c_{clear}", "clear edge-to-edge element spacing", "mm"),
            _s(r"\phi_{max}", "largest adjacent detailing diameter", "mm"),
            _s(r"D_{upper}", "entered upper aggregate size", "mm"),
        ),
        "standard",
        "DS/EN 1992-1-1 8.2(2); DS/EN 1992-1-1:2023 11.2(2).",
    ),
    _e(
        "detailing.links.minimum-ratio", "C.5.4-1", "Reinforcement detailing",
        "Shear and torsion reinforcement",
        "e39e98501124b045f90745c456fc6947ff91331fae7c48b4a107c95e6f89536b",
        (
            _s(r"\rho_w", "provided vertical-link reinforcement ratio"),
            _s(r"A_{sw}", "effective vertical-link area", "mm2"),
            _s("s", "longitudinal link spacing", "mm"),
            _s(r"b_w", "web width", "mm"),
            _s(r"\rho_{w,min}", "minimum link reinforcement ratio"),
            _s("c", "edition-specific minimum-ratio coefficient"),
            _s(r"f_{ck}", "characteristic concrete compressive strength", "MPa"),
            _s(r"f_{ywk}", "characteristic link yield strength", "MPa"),
        ),
        "standard",
        "DS/EN 1992-1-1 9.2.2(5), Formulae (9.4)-(9.5); "
        "DS/EN 1992-1-1:2023 12.2(4), Formula (12.4).",
    ),
    _e(
        "detailing.links.spacing", "C.5.4-2", "Reinforcement detailing",
        "Shear and torsion reinforcement",
        "46578627e65dc94444a986bcd27740da82bd1c07073227810451b24b18498144",
        (
            _s(r"s_l", "longitudinal spacing of link sets", "mm"),
            _s(r"s_t", "maximum transverse distance between effective legs", "mm"),
            _s("d", "effective shear depth", "mm"),
        ),
        "standard",
        "DS/EN 1992-1-1 9.2.2(5)-(8), Formulae (9.4)-(9.8); "
        "DS/EN 1992-1-1:2023 12.2(4), Table 12.1.",
    ),
    _e(
        "detailing.torsion.minimum-ratio", "C.5.4-3",
        "Reinforcement detailing", "Shear and torsion reinforcement",
        "10d5445bf8ce120f10d189ac9cce5c24d2c6d3018f122cd1ae4cd680488f13e9",
        (
            _s(r"\rho_{w,T}", "provided torsion-wall link ratio"),
            _s(r"A_{leg}", "area of one effective closed-link leg", "mm2"),
            _s("s", "longitudinal closed-link spacing", "mm"),
            _s(r"t_{ef}", "effective torsion-wall thickness", "mm"),
            _s(r"\rho_{w,min}", "minimum link reinforcement ratio"),
        ),
        "standard",
        "DS/EN 1992-1-1 9.2.3(3); DS/EN 1992-1-1:2023 "
        "Table 12.1 and 12.3.3.",
    ),
    _e(
        "crack.2005.width-strain", "C.7.2-1",
        "Serviceability: cracking and crack width",
        "Crack width - EN 1992-1-1:2005",
        "4451827db7ec3ec1f7c7f07f3660b6ba6cf2cb44dd35f56b63595a2d594bfc42",
        (
            _s(r"w_k", "characteristic crack width", "mm"),
            _s(r"s_{r,max}", "maximum crack spacing", "mm"),
            _s(r"\varepsilon_{sm}", "mean reinforcement strain"),
            _s(r"\varepsilon_{cm}", "mean concrete strain between cracks"),
            _s(r"\sigma_s", "reinforcement stress in the cracked section", "MPa"),
            _s(r"k_t", "load-duration factor"),
            _s(r"f_{ct,eff}", "effective concrete tensile strength", "MPa"),
            _s(r"\rho_{p,eff}", "effective reinforcement ratio"),
            _s(r"\alpha_e", "reinforcement-to-concrete modulus ratio"),
            _s(r"E_s", "reinforcement elastic modulus", "MPa"),
        ),
        "standard",
        "DS/EN 1992-1-1:2005 7.3.4, Formulae (7.8)-(7.9).",
    ),
    _e(
        "crack.2005.spacing", "C.7.2-2",
        "Serviceability: cracking and crack width",
        "Crack width - EN 1992-1-1:2005",
        "e674c66afb21190f639015cce8da6a954fdcc19f8ddd326020667e25536c8fe3",
        (
            _s(r"s_{r,max}", "maximum crack spacing", "mm"),
            _s(r"k_1", "bond coefficient"),
            _s(r"k_2", "strain-distribution coefficient"),
            _s(r"k_3", "cover coefficient"),
            _s(r"k_4", "bar-diameter coefficient"),
            _s("c", "reinforcement cover", "mm"),
            _s(r"\phi", "governing bar diameter", "mm"),
            _s(r"\rho_{p,eff}", "effective reinforcement ratio"),
            _s("h", "overall section depth", "mm"),
            _s("x", "compression-zone depth", "mm"),
        ),
        "standard",
        "DS/EN 1992-1-1:2005 7.3.4, Formulae (7.11) and (7.14); "
        "DK NA variants are stated in the accompanying text.",
    ),
    _e(
        "crack.2023.width", "C.7.5-1",
        "Serviceability: cracking and crack width",
        "EN 1992-1-1:2023 refined model",
        "4c15d71e9d8e368108149af68afc41acc767712cd71aa1ad7af0223bb5ae3d10",
        (
            _s(r"w_k", "characteristic crack width", "mm"),
            _s(r"k_w", "characteristic-width factor"),
            _s(r"k_1/r", "bar-specific curvature factor"),
            _s(r"s_{r,m,cal}", "calculated mean crack spacing", "mm"),
            _s(r"\varepsilon_{sm}", "mean reinforcement strain"),
            _s(r"\varepsilon_{cm}", "mean concrete strain between cracks"),
            _s("h", "overall section depth", "mm"),
            _s("x", "compression-zone depth", "mm"),
            _s(r"a_{y,i}", "bar-i distance from the tensile face", "mm"),
            _s("i", "reinforcement-bar index"),
        ),
        "standard",
        "DS/EN 1992-1-1:2023 9.2.3, Formulae (9.8)-(9.9).",
    ),
    _e(
        "crack.2023.spacing", "C.7.5-2",
        "Serviceability: cracking and crack width",
        "EN 1992-1-1:2023 refined model",
        "3232760c0b31c26275f004adf2bf978d25bf8452b182b6966e3bfeb455cae8ea",
        (
            _s(r"s_{r,m,cal}", "calculated mean crack spacing", "mm"),
            _s("c", "reinforcement cover", "mm"),
            _s(r"k_{fl}", "flexural coefficient"),
            _s(r"k_b", "bond factor"),
            _s(r"\phi", "governing bar diameter", "mm"),
            _s(r"\rho_{p,eff}", "effective reinforcement ratio"),
            _s(r"k_w", "characteristic-width factor"),
            _s("h", "overall section depth", "mm"),
            _s("x", "compression-zone depth", "mm"),
        ),
        "standard",
        "DS/EN 1992-1-1:2023 9.2.3, Formula (9.15).",
    ),
    _e(
        "fatigue.elastic.stress-range", "C.8.1-1", "Grouped fatigue",
        "Elastic stress ranges",
        "1c6d20674b30556d5158662f2eed158f78f16c0ec52b6134bf9ee4e728707878",
        (
            _s(r"\Delta\sigma_{Ed,i}", "design stress range in spectrum bin i", "MPa"),
            _s(r"\sigma(S)", "elastic stress response to action state S", "MPa"),
            _s(r"S_l", "sustained basic action state", "action-specific"),
            _s(r"S_s", "cyclic action increment", "action-specific"),
            _s(r"\gamma_{Ff}", "fatigue action factor"),
            _s("i", "spectrum-bin index"),
        ),
        "project", _PROJECT_SOURCE,
    ),
    _e(
        "fatigue.reinforcement.design-range", "C.8.2-1", "Grouped fatigue",
        "Reinforcement S-N and Miner check",
        "79409e2d84eb04d50e0b3ecdb1a23cbaee4988c086d4d63375c8dc87267f5514",
        (
            _s(r"\Delta\sigma_{Rd}", "design fatigue reference range", "MPa"),
            _s(r"\Delta\sigma_{Rsk}", "characteristic fatigue reference range", "MPa"),
            _s(r"\gamma_s", "partial factor for fatigue strength"),
        ),
        "mixed",
        "DS/EN 1992-1-1:2005+A1:2014 6.8.4 and Tables 6.3N/6.4N; "
        "DS/EN 1992-1-1:2023 Annex E.5 and Tables E.1/E.2; a custom detail "
        "remains Project-defined / uncited.",
    ),
    _e(
        "fatigue.reinforcement.life", "C.8.2-2", "Grouped fatigue",
        "Reinforcement S-N and Miner check",
        "525ca21ac74aa72c0202fba278ff55bfc0e4c951c7c4b29a1d0776e657bad217",
        (
            _s(r"N_{R,i}", "fatigue life for spectrum bin i", "cycles"),
            _s(r"N^*", "reference number of cycles", "cycles"),
            _s(r"\Delta\sigma_{Rd}", "design fatigue reference range", "MPa"),
            _s(r"\Delta\sigma_{Ed,i}", "design stress range in spectrum bin i", "MPa"),
            _s("k", "selected S-N curve slope"),
            _s("i", "spectrum-bin index"),
        ),
        "mixed",
        "DS/EN 1992-1-1:2005+A1:2014 6.8.4 and Tables 6.3N/6.4N; "
        "DS/EN 1992-1-1:2023 Annex E.5 and Tables E.1/E.2; a custom detail "
        "remains Project-defined / uncited.",
        uses=("fatigue.reinforcement.design-range",),
    ),
    _e(
        "fatigue.reinforcement.miner", "C.8.2-3", "Grouped fatigue",
        "Reinforcement S-N and Miner check",
        "ace577b8ce30e7129bda1cc84198419a4fea29b0472f100afe793caddca79564",
        (
            _s("D", "Miner damage sum"),
            _s(r"n_i", "applied cycles in spectrum bin i", "cycles"),
            _s(r"N_{R,i}", "fatigue life for spectrum bin i", "cycles"),
            _s("i", "spectrum-bin index"),
        ),
        "mixed",
        "DS/EN 1992-1-1:2005+A1:2014 6.8.4; DS/EN 1992-1-1:2023 "
        "Annex E.5; a custom detail remains Project-defined / uncited.",
        uses=("fatigue.reinforcement.life",),
    ),
    _e(
        "fatigue.concrete.strength-2005", "C.8.4-1", "Grouped fatigue",
        "Concrete compression fatigue",
        "5123cf1171bbf2a16ddc81bf351ebaff1c8aa4f26bdec70f846f81f1a1b68ce9",
        (
            _s(r"f_{cd,fat}", "design concrete fatigue strength", "MPa"),
            _s(r"k_1", "fatigue strength coefficient"),
            _s(r"\beta_{cc}(t_0)", "concrete age factor at first loading"),
            _s(r"t_0", "concrete age at first fatigue loading", "days"),
            _s(r"\alpha_{cc}", "concrete strength coefficient"),
            _s(r"f_{ck}", "characteristic concrete compressive strength", "MPa"),
            _s(r"\gamma_{c,fat}", "partial factor for concrete fatigue"),
        ),
        "standard",
        "DS/EN 1992-1-1:2005+A1:2014 6.8.7, Formula (6.76); "
        "DS/EN 1992-2:2005/AC:2008 corrected 6.106.",
    ),
    _e(
        "fatigue.concrete.strength-2023", "C.8.4-2", "Grouped fatigue",
        "Concrete compression fatigue",
        "85e38c135904be5a3507e919a0649d9c209549ebb4ee3f0875ac978984e09eda",
        (
            _s(r"\eta_{cc}", "concrete strength reduction factor"),
            _s(r"f_{ck}", "characteristic concrete compressive strength", "MPa"),
            _s(r"\eta_{cc,fat}", "fatigue concrete reduction factor"),
            _s(r"f_{cd,fat}", "design concrete fatigue strength", "MPa"),
            _s(r"\beta_{cc}(t_0)", "concrete age factor at first loading"),
            _s(r"t_0", "concrete age at first fatigue loading", "days"),
            _s(r"\gamma_{c,fat}", "partial factor for concrete fatigue"),
        ),
        "standard",
        "DS/EN 1992-1-1:2023 10.5, Formula (10.5).",
    ),
    _e(
        "fatigue.concrete.life", "C.8.4-3", "Grouped fatigue",
        "Concrete compression fatigue",
        "5a8cca7a9e50c8a23d37882d0fb575d459dcd187d9fd4e2a4c580da5cf154528",
        (
            _s(r"N_R", "concrete fatigue life", "cycles"),
            _s("C", "selected concrete S-N coefficient"),
            _s(r"E_{max}", "maximum normalized concrete compression"),
            _s("R", "minimum-to-maximum compression ratio"),
        ),
        "mixed",
        "DS/EN 1992-2:2005/AC:2008 6.106; DS/EN 1992-1-1:2023 "
        "E.5.3, Formulae (E.7)-(E.8); a user-defined relation remains "
        "Project-defined / uncited.",
    ),
    _e(
        "fatigue.concrete.equivalent", "C.8.4-4", "Grouped fatigue",
        "Concrete compression fatigue",
        "4a70d70fdded41c242471c53a26554257d8444562547f5763c882c00a137bdcf",
        (
            _s(r"E_{max}", "maximum normalized concrete compression"),
            _s(r"E_{min}", "minimum normalized concrete compression"),
        ),
        "standard",
        "DS/EN 1992-1-1:2005 6.8.7, Formula (6.72); "
        "DS/EN 1992-1-1:2023 E.4.3, Formula (E.2).",
    ),
    _e(
        "shear.2005.basic", "C.9-1",
        "Shear resistance without shear reinforcement", None,
        "e5a101ffeb8ed99a3ad22d269c843d73ab17a4830858ddcec135b958a9d0ee6c",
        (
            _s(r"V_{Rd,c}", "design shear resistance without links", "kN"),
            _s(r"C_{Rd,c}", "concrete shear coefficient"),
            _s("k", "size-effect factor"),
            _s(r"\rho_l", "longitudinal tension-reinforcement ratio"),
            _s(r"f_{ck}", "characteristic concrete compressive strength", "MPa"),
            _s(r"k_1", "axial-stress coefficient"),
            _s(r"\sigma_{cp}", "code-sign concrete axial stress", "MPa"),
            _s(r"b_w", "web width", "mm"),
            _s("d", "effective shear depth", "mm"),
        ),
        "standard",
        "DS/EN 1992-1-1 6.2.2(1), Formula (6.2a); DK NA 6.2.2(1).",
    ),
    _e(
        "shear.2005.minimum", "C.9-2",
        "Shear resistance without shear reinforcement", None,
        "1279f09a95518892baa612be76e48350f9cf565aed5efd94aecadcf165c7cc67",
        (
            _s(r"V_{Rd,c}", "minimum design shear resistance", "kN"),
            _s(r"v_{min}", "minimum shear stress", "MPa"),
            _s(r"k_1", "axial-stress coefficient"),
            _s(r"\sigma_{cp}", "code-sign concrete axial stress", "MPa"),
            _s(r"b_w", "web width", "mm"),
            _s("d", "effective shear depth", "mm"),
        ),
        "standard",
        "DS/EN 1992-1-1 6.2.2(1), Formula (6.2b); DK NA 6.2.2(1).",
    ),
    _e(
        "shear.2023.action-factor", "C.9-3",
        "Shear resistance without shear reinforcement", None,
        "57910d0569783bc00ef2c62b0755400dc51059b6ffd96017e3f7b50d92a5190d",
        (
            _s(r"a_{cs}", "effective shear span", "mm"),
            _s(r"M_{Ed}", "applied design moment", "kNm"),
            _s(r"V_{Ed}", "applied design shear", "kN"),
            _s("d", "effective shear depth", "mm"),
            _s(r"k_{vp}", "axial-force action factor"),
            _s(r"N_{Ed}", "applied design axial force, tension positive", "kN"),
        ),
        "standard",
        "DS/EN 1992-1-1:2023 Formula (8.30) and 8.2.2(4), Formula (8.31).",
    ),
    _e(
        "shear.links.2005", "C.9.1-1",
        "Shear resistance without shear reinforcement",
        "Members with shear reinforcement (links)",
        "8bbbf0a6261d72eea45965ba33b6b45bb65ff56f67fa308f8020f7f01598aed7",
        (
            _s(r"V_{Rd,s}", "link-yield shear resistance", "kN"),
            _s(r"A_{sw}", "effective vertical-link area", "mm2"),
            _s("s", "longitudinal link spacing", "mm"),
            _s("z", "internal lever arm", "mm"),
            _s(r"f_{ywd}", "design link yield strength", "MPa"),
            _s(r"\theta", "compression-strut angle", "degrees"),
            _s(r"V_{Rd,max}", "concrete-strut shear resistance", "kN"),
            _s(r"\alpha_{cw}", "compression-chord factor"),
            _s(r"b_w", "web width", "mm"),
            _s(r"\nu_1", "shear-strut effectiveness factor"),
            _s(r"f_{cd}", "design concrete compressive strength", "MPa"),
        ),
        "standard",
        "DS/EN 1992-1-1 6.2.3, Formulae (6.8)-(6.9); DK NA 6.2.3.",
    ),
    _e(
        "shear.links.2023", "C.9.1-2",
        "Shear resistance without shear reinforcement",
        "Members with shear reinforcement (links)",
        "85cfe8d83d492a4af5a911a3a7c1dc332f88dcf75ae2b1434c6ed6fef91d3439",
        (
            _s(r"\tau_{Rd,sy}", "link-yield shear stress resistance", "MPa"),
            _s(r"\rho_w", "vertical-link reinforcement ratio"),
            _s(r"f_{ywd}", "design link yield strength", "MPa"),
            _s(r"\theta", "compression-strut angle", "degrees"),
            _s(r"\sigma_{cd}", "concrete compression-field stress", "MPa"),
            _s(r"\tau_{Ed}", "applied design shear stress", "MPa"),
            _s(r"\nu", "concrete-strut effectiveness factor"),
            _s(r"f_{cd}", "design concrete compressive strength", "MPa"),
        ),
        "standard",
        "DS/EN 1992-1-1:2023 Formulae (8.42) and (8.44).",
    ),
    _e(
        "torsion.resistance", "C.10-1", "Torsion (thin-walled tube)", None,
        "a5291e17e74a23e3ec4f59d6a894be40eb72247ab67a266cb5f0a7d14667bff6",
        (
            _s(r"T_{Rd,s}", "closed-link torsion resistance", "kNm"),
            _s(r"A_{sw}", "effective closed-link area", "mm2"),
            _s("s", "longitudinal closed-link spacing", "mm"),
            _s(r"A_k", "area enclosed by the torsion centre-line", "mm2"),
            _s(r"f_{ywd}", "design link yield strength", "MPa"),
            _s(r"\theta", "compression-strut angle", "degrees"),
            _s(r"T_{Rd,max}", "concrete-strut torsion resistance", "kNm"),
            _s(r"\nu", "torsion-strut effectiveness factor"),
            _s(r"\alpha_{cw}", "compression-chord factor"),
            _s(r"f_{cd}", "design concrete compressive strength", "MPa"),
            _s(r"t_{ef}", "effective torsion-wall thickness", "mm"),
        ),
        "standard",
        "DS/EN 1992-1-1 6.3.2, Formula (6.30); wall shear flow (6.27) "
        "and transverse equilibrium (6.8).",
    ),
    _e(
        "torsion.shear-interaction", "C.10-2", "Torsion (thin-walled tube)", None,
        "0fde836b7555c3d5e63a45cc971b43eb8b53aeb68405c7294673b1704575b79b",
        (
            _s(r"T_{Ed}", "applied design torsion", "kNm"),
            _s(r"T_{Rd,max}", "concrete-strut torsion resistance", "kNm"),
            _s(r"V_{Ed}", "applied design shear", "kN"),
            _s(r"V_{Rd,max}", "concrete-strut shear resistance", "kN"),
        ),
        "standard", "DS/EN 1992-1-1 6.3.2, Formula (6.29).",
        uses=("torsion.resistance",),
    ),
    _e(
        "combined.strut-interaction", "C.11-1", "Combined M-V-T interaction", None,
        "0fde836b7555c3d5e63a45cc971b43eb8b53aeb68405c7294673b1704575b79b",
        (
            _s(r"T_{Ed}", "applied design torsion", "kNm"),
            _s(r"T_{Rd,max}", "concrete-strut torsion resistance", "kNm"),
            _s(r"V_{Ed}", "applied design shear", "kN"),
            _s(r"V_{Rd,max}", "concrete-strut shear resistance", "kN"),
        ),
        "standard", "DS/EN 1992-1-1 6.3.2, Formula (6.29).",
        uses=("torsion.shear-interaction",),
    ),
    _e(
        "combined.dk-na-sum", "C.11-2", "Combined M-V-T interaction", None,
        "850bd52dcea64b9e779bc904fa701d42d2d47657af17ea0f1ab0f32263f3ab8b",
        (
            _s(r"S_{Ed}", "design effect of one acting sectional force", "action-specific"),
            _s(r"S_{Rd}", "resistance to that force acting alone", "action-specific"),
            _s(r"\sum(S_{Ed}/S_{Rd})", "governing sectional-force interaction sum"),
        ),
        "standard", "DS/EN 1992-1-1 DK NA:2024 6.3.2(6).",
    ),
)


def _validate_catalogue() -> None:
    if len(_CONTRACTS) != 32:
        raise RuntimeError(f"Expected 32 manual equation contracts, got {len(_CONTRACTS)}.")
    keys: set[str] = set()
    numbers: set[str] = set()
    for contract in _CONTRACTS:
        if not _KEY_RE.fullmatch(contract.key) or contract.key in keys:
            raise RuntimeError(f"Invalid or duplicate manual equation key: {contract.key!r}.")
        if contract.number in numbers:
            raise RuntimeError(f"Duplicate manual equation number: {contract.number!r}.")
        if not _SHA256_RE.fullmatch(contract.expression_sha256):
            raise RuntimeError(f"Invalid expression digest for {contract.key!r}.")
        if not contract.part or not contract.section:
            raise RuntimeError(f"Incomplete manual context for {contract.key!r}.")
        if not contract.symbols:
            raise RuntimeError(f"Manual equation {contract.key!r} has no symbols.")
        symbol_names = [symbol.latex for symbol in contract.symbols]
        if any(not name.strip() for name in symbol_names):
            raise RuntimeError(f"Manual equation {contract.key!r} has a blank symbol.")
        if len(symbol_names) != len(set(symbol_names)):
            raise RuntimeError(f"Manual equation {contract.key!r} has duplicate symbols.")
        for symbol in contract.symbols:
            if not symbol.meaning.strip() or symbol.unit not in _UNIT_LATEX:
                raise RuntimeError(f"Manual equation {contract.key!r} has an incomplete symbol.")
        if contract.source_kind not in _SOURCE_KINDS or not contract.source.strip():
            raise RuntimeError(f"Manual equation {contract.key!r} has invalid provenance.")
        if contract.source_kind == "project" and contract.source != _PROJECT_SOURCE:
            raise RuntimeError(f"Project equation {contract.key!r} must remain uncited.")
        if (
            contract.source_kind == "mixed"
            and "Project-defined / uncited" not in contract.source
        ):
            raise RuntimeError(f"Mixed equation {contract.key!r} hides its project source.")
        unknown = [key for key in contract.uses if key not in keys]
        if unknown:
            raise RuntimeError(
                f"Manual equation {contract.key!r} references non-prior keys {unknown!r}."
            )
        keys.add(contract.key)
        numbers.add(contract.number)


_validate_catalogue()
_BY_KEY = {contract.key: contract for contract in _CONTRACTS}


def manual_equation_contracts() -> tuple[ManualEquationContract, ...]:
    """Return the immutable catalogue in authored publication order."""

    return _CONTRACTS


def manual_equation_contract(key: str) -> ManualEquationContract:
    """Return one exact manual equation contract by semantic key."""

    try:
        return _BY_KEY[str(key)]
    except KeyError as exc:
        raise ValueError(f"Unknown manual equation key: {key!r}.") from exc


def unit_latex(unit: str) -> str:
    """Return the shared LaTeX presentation for one canonical unit."""

    try:
        return _UNIT_LATEX[unit]
    except KeyError as exc:
        raise ValueError(f"Unknown manual equation unit: {unit!r}.") from exc


def _expression_sha256(expression: str) -> str:
    return hashlib.sha256(expression.encode("utf-8")).hexdigest()


def catalogue_manual_blocks(blocks: Iterable[tuple]) -> tuple[tuple, ...]:
    """Bind every authored display equation to its exact catalogue contract.

    Returned Markdown blocks retain their original text at index 1 and add the
    complete ordered segment tuple at index 2.  Unknown, missing, moved,
    reordered or altered display equations fail before either renderer publishes.
    """

    output = []
    contract_index = 0
    part_index = 0
    part = section = subsection = None
    section_index = subsection_index = 0
    equation_in_scope = 0

    for raw_block in blocks:
        block = tuple(raw_block)
        kind = block[0]
        if kind == "part":
            part_index += 1
            part = block[1]
            section = subsection = None
            section_index = subsection_index = 0
            equation_in_scope = 0
        elif kind == "h1":
            section_index += 1
            subsection_index = 0
            section = block[1]
            subsection = None
            equation_in_scope = 0
        elif kind == "h2":
            subsection_index += 1
            subsection = block[1]
            equation_in_scope = 0

        if kind != "md":
            output.append(block)
            continue

        text = block[1]
        segments: list[ManualMarkdownSegment] = []
        cursor = 0
        for match in _DISPLAY_EQUATION_RE.finditer(text):
            if contract_index >= len(_CONTRACTS):
                raise ValueError("The manual contains an unknown display equation.")
            contract = _CONTRACTS[contract_index]
            expression = match.group(1).strip()
            punctuation = match.group(2)
            equation_in_scope += 1
            part_code = chr(ord("A") + part_index - 1)
            number = (
                f"{part_code}.{section_index}.{subsection_index}-{equation_in_scope}"
                if subsection_index
                else f"{part_code}.{section_index}-{equation_in_scope}"
            )
            context = (part, section, subsection)
            expected_context = (contract.part, contract.section, contract.subsection)
            if context != expected_context:
                raise ValueError(
                    f"Manual equation {contract.key!r} moved from "
                    f"{expected_context!r} to {context!r}."
                )
            if number != contract.number:
                raise ValueError(
                    f"Manual equation {contract.key!r} moved from number "
                    f"{contract.number} to {number}."
                )
            if _expression_sha256(expression) != contract.expression_sha256:
                raise ValueError(
                    f"Manual equation {contract.key!r} no longer matches its "
                    "frozen expression."
                )
            if match.start() > cursor:
                segments.append(ManualMarkdownSegment(text[cursor:match.start()]))
            occurrence = ManualEquationOccurrence(contract, expression, punctuation)
            segments.append(ManualMarkdownSegment(match.group(0), occurrence))
            cursor = match.end()
            contract_index += 1
        if cursor < len(text):
            segments.append(ManualMarkdownSegment(text[cursor:]))
        if not segments:
            segments.append(ManualMarkdownSegment(text))
        if "".join(segment.markdown for segment in segments) != text:
            raise RuntimeError("Manual Markdown segmentation changed authored content.")
        output.append((kind, text, tuple(segments)))

    if contract_index != len(_CONTRACTS):
        missing = tuple(contract.key for contract in _CONTRACTS[contract_index:])
        raise ValueError(f"The manual is missing catalogued display equations: {missing!r}.")
    return tuple(output)
