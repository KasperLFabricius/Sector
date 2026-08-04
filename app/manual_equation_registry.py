"""Fail-closed publication registry for the authored Part C manual equations.

Formula text stays authored only in :mod:`manual`.  This registry binds each
display equation to its independently reconstructed location, identity,
dimensional symbol inventory, provenance and genuine equation dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable


_DISPLAY_RE = re.compile(r"\$\$(.+?)\$\$([.,;:]?)", re.DOTALL)
_KEY_RE = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
_PART_C = "Part C - Theory & methodology"
_PROJECT = "Project-defined / uncited."

_UNIT_MARKUP = {
    "1": "1",
    "MPa": r"\text{MPa}",
    "m": r"\text{m}",
    "mm": r"\text{mm}",
    "m2": r"\text{m}^{2}",
    "mm2": r"\text{mm}^{2}",
    "mm2/mm": r"\text{mm}^{2}/\text{mm}",
    "1/m": r"\text{m}^{-1}",
    "kN": r"\text{kN}",
    "kNm": r"\text{kN}\,\text{m}",
    "degrees": r"{}^{\circ}",
    "cycles": r"\text{cycles}",
    "actions": r"\text{action-specific}",
}


@dataclass(frozen=True, slots=True)
class ManualSymbol:
    latex: str
    meaning: str
    unit: str = "1"


@dataclass(frozen=True, slots=True)
class ManualEquationSpec:
    key: str
    number: str
    section: str
    subsection: str | None
    expression_sha256: str
    symbols: tuple[ManualSymbol, ...]
    source_kind: str
    source: str
    dimensional_note: str
    uses: tuple[str, ...] = ()

    @property
    def public_id(self) -> str:
        return "MEQ-" + self.key.upper()

    @property
    def anchor(self) -> str:
        return "manual-equation-" + self.key.replace(".", "--")


@dataclass(frozen=True, slots=True)
class ManualEquationOccurrence:
    spec: ManualEquationSpec
    expression: str
    punctuation: str


@dataclass(frozen=True, slots=True)
class ManualMarkdownSegment:
    markdown: str
    equation: ManualEquationOccurrence | None = None


def _s(latex: str, meaning: str, unit: str = "1") -> ManualSymbol:
    return ManualSymbol(latex, meaning, unit)


def _e(
    key: str,
    number: str,
    section: str,
    subsection: str | None,
    digest: str,
    symbols: tuple[ManualSymbol, ...],
    source_kind: str,
    source: str,
    dimensional_note: str,
    *,
    uses: tuple[str, ...] = (),
) -> ManualEquationSpec:
    return ManualEquationSpec(
        key, number, section, subsection, digest, symbols, source_kind,
        source, dimensional_note, uses,
    )


_SPECS = (
    _e(
        "material.concrete.curve2", "C.3.1-1", "Material laws",
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
        "EN 1992-1-1:2023 8.1.2(1), Formula (8.4), with design-strength "
        "factors from 5.1.6(1).",
        "Stress terms are MPa; every strain and the exponent are dimensionless.",
    ),
    _e(
        "material.reinforcement.initial", "C.3.2-1", "Material laws",
        "Mild steel",
        "5972f92c2cf2dd2c16ab580e95c70f98ebe947a2baaef960c67252ac294a9c11",
        (
            _s(r"\sigma_s", "reinforcement stress", "MPa"),
            _s(r"E_{s,d}", "design reinforcement elastic modulus", "MPa"),
            _s(r"\varepsilon_s", "reinforcement strain"),
            _s(r"\varepsilon_{yd}", "design yield strain"),
            _s(r"f_{yd}", "design yield strength", "MPa"),
            _s(r"f_{yk}", "characteristic yield strength", "MPa"),
            _s(r"\gamma_s", "reinforcement partial factor"),
        ),
        "mixed",
        "DS/EN 1992-1-1 3.2.7 and DS/EN 1992-1-1:2023 5.2.4 for edition "
        "presets; the generic editable relation is Project-defined / uncited.",
        "Stress and modulus terms are MPa; strains and the partial factor are dimensionless.",
    ),
    _e(
        "material.prestress.compatibility", "C.3.3-1", "Material laws",
        "Prestressing steel",
        "e61a85aca0ae68096eae6d42740d5e556e839b765c69ec57f61ecc5c146cbaa5",
        (
            _s(r"\varepsilon_{p,j}", "total strain of tendon j"),
            _s(r"\varepsilon_{p,IS,j}", "locked-in initial strain of tendon j"),
            _s(r"\kappa", "compression-positive section curvature", "1/m"),
            _s(r"s_{p,j}", "projected coordinate of tendon j", "m"),
            _s(r"s_{na}", "neutral-axis projected coordinate", "m"),
            _s(r"\sigma_p", "prestressing-steel stress", "MPa"),
            _s(r"f(\varepsilon_p)", "selected tendon law evaluated at total strain", "MPa"),
            _s(r"f_{pd}", "design tendon proof strength", "MPa"),
            _s(r"f_{p0.1k}", "characteristic tendon proof strength", "MPa"),
            _s(r"\gamma_s", "prestressing-steel partial factor"),
            _s("j", "tendon index"),
        ),
        "mixed",
        "Project-defined / uncited plane-section compatibility; DS/EN 1992-1-1 "
        "3.3.6 and DS/EN 1992-1-1:2023 5.3.3 supply the selected tendon-law relation.",
        "The retained solver uses metres and 1/m, so curvature times a coordinate difference is strain.",
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
            _s(r"s_{na}", "neutral-axis projected coordinate", "m"),
            _s(r"s_{b,i}", "projected coordinate of mild bar i", "m"),
            _s(r"\varepsilon_{pu,j}", "ultimate total strain of tendon j"),
            _s(r"\varepsilon_{p,IS,j}", "locked-in initial strain of tendon j"),
            _s(r"s_{p,j}", "projected coordinate of tendon j", "m"),
            _s("i", "mild-bar index"),
            _s("j", "tendon index"),
        ),
        "project", _PROJECT,
        "Every candidate is a dimensionless strain divided by a retained metre distance, giving 1/m.",
    ),
    _e(
        "detailing.minimum.2005", "C.5.1-1", "Reinforcement detailing",
        "EN 1992-1-1:2005 and DK NA:2024",
        "7e00772db83d146d7df046f67ea3d9830cd8f1c2210d0421e2dbf57c42265a6b",
        (
            _s(r"A_{s,min}", "required minimum tension reinforcement", "mm2"),
            _s(r"f_{ctm}", "mean concrete tensile strength", "MPa"),
            _s(r"f_{yk}", "characteristic reinforcement strength", "MPa"),
            _s(r"b_t", "mean width of the tension zone", "mm"),
            _s("d", "effective depth", "mm"),
            _s(r"A_{s,prov}", "provided tension reinforcement", "mm2"),
        ),
        "standard", "DS/EN 1992-1-1 9.2.1.1(1), Formula (9.1N); DK NA:2024.",
        "The strength ratio is dimensionless and b_t times d gives mm2.",
    ),
    _e(
        "detailing.minimum.2023-bending", "C.5.2-1", "Reinforcement detailing",
        "EN 1992-1-1:2023",
        "a3e8a44022ab1eeac1eb1e85361b1735d337f4289aabfa4748a06a31eb7f8c9d",
        (
            _s(r"M_{R,nom}", "nominal bending resistance", "kNm"),
            _s(r"M_{cr}", "gross-section cracking moment", "kNm"),
            _s(r"N_{Ed}", "applied design axial force", "kN"),
        ),
        "standard", "DS/EN 1992-1-1:2023 12.2(2)(a), Formula (12.1).",
        "Both compared moment functions use kNm at the same N_Ed in kN.",
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
        "standard", "DS/EN 1992-1-1:2023 12.2(2)(b), Formula (12.2).",
        "Both sides are area in mm2 times stress in MPa and therefore force in N.",
    ),
    _e(
        "detailing.clear-spacing", "C.5.3-1", "Reinforcement detailing",
        "Clear spacing",
        "f41ec7e90828e88a52fe0d33bb42a5637f4e92b874b2f3576f0c112b34bdfc46",
        (
            _s(r"c_{clear}", "clear edge-to-edge element spacing", "mm"),
            _s(r"\phi_{max}", "larger adjacent detailing diameter", "mm"),
            _s(r"D_{upper}", "entered upper aggregate size", "mm"),
        ),
        "standard", "DS/EN 1992-1-1 8.2(2); DS/EN 1992-1-1:2023 11.2(2).",
        "All operands of max, including the literal offsets, are millimetres.",
    ),
    _e(
        "detailing.links.minimum-ratio", "C.5.4-1", "Reinforcement detailing",
        "Shear and torsion reinforcement",
        "e39e98501124b045f90745c456fc6947ff91331fae7c48b4a107c95e6f89536b",
        (
            _s(r"\rho_w", "provided shear-link reinforcement ratio"),
            _s(r"A_{sw}", "effective shear-link area", "mm2"),
            _s("s", "longitudinal link spacing", "mm"),
            _s(r"b_w", "effective web breadth", "mm"),
            _s(r"\rho_{w,min}", "minimum shear-link ratio"),
            _s("c", "edition coefficient for the minimum-link relation"),
            _s(r"f_{ck}", "characteristic concrete strength", "MPa"),
            _s(r"f_{ywk}", "characteristic link yield strength", "MPa"),
        ),
        "standard",
        "DS/EN 1992-1-1 9.2.2(5), Formulae (9.4)-(9.5); "
        "DS/EN 1992-1-1:2023 12.2(4), Formula (12.4).",
        "A_sw divided by s times b_w is dimensionless; the edition coefficient carries the retained MPa convention.",
    ),
    _e(
        "detailing.links.spacing", "C.5.4-2", "Reinforcement detailing",
        "Shear and torsion reinforcement",
        "46578627e65dc94444a986bcd27740da82bd1c07073227810451b24b18498144",
        (
            _s(r"s_l", "maximum longitudinal link spacing", "mm"),
            _s(r"s_t", "maximum transverse leg spacing", "mm"),
            _s("d", "effective depth", "mm"),
        ),
        "standard",
        "DS/EN 1992-1-1 9.2.2(5)-(8), Formulae (9.4)-(9.8); "
        "DS/EN 1992-1-1:2023 12.2(4), Table 12.1.",
        "Every compared spacing and literal bound is in millimetres.",
    ),
    _e(
        "detailing.torsion.minimum-ratio", "C.5.4-3", "Reinforcement detailing",
        "Shear and torsion reinforcement",
        "10d5445bf8ce120f10d189ac9cce5c24d2c6d3018f122cd1ae4cd680488f13e9",
        (
            _s(r"\rho_{w,T}", "provided torsion-link reinforcement ratio"),
            _s(r"A_{leg}", "area of one effective closed-link leg", "mm2"),
            _s("s", "longitudinal link spacing", "mm"),
            _s(r"t_{ef}", "effective torsion-wall thickness", "mm"),
            _s(r"\rho_{w,min}", "minimum link ratio from Equation C.5.4-1"),
        ),
        "standard",
        "DS/EN 1992-1-1 9.2.3(3); DS/EN 1992-1-1:2023 Table 12.1 and 12.3.3.",
        "A_leg divided by s times t_ef is dimensionless.",
        uses=("detailing.links.minimum-ratio",),
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
            _s(r"\sigma_s", "reinforcement stress", "MPa"),
            _s(r"k_t", "load-duration factor"),
            _s(r"f_{ct,eff}", "effective concrete tensile strength", "MPa"),
            _s(r"\rho_{p,eff}", "effective reinforcement ratio"),
            _s(r"\alpha_e", "reinforcement/concrete modular ratio"),
            _s(r"E_s", "reinforcement elastic modulus", "MPa"),
        ),
        "standard", "DS/EN 1992-1-1:2005 7.3.4, Formulae (7.8)-(7.9).",
        "Crack spacing in mm times a dimensionless mean-strain difference gives crack width in mm.",
        uses=("crack.2005.spacing",),
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
            _s(r"k_4", "recommended spacing coefficient"),
            _s("c", "clear cover", "mm"),
            _s(r"\phi", "bar diameter", "mm"),
            _s(r"\rho_{p,eff}", "effective reinforcement ratio"),
            _s("h", "section depth in the crack direction", "mm"),
            _s("x", "neutral-axis depth from the compression face", "mm"),
        ),
        "standard",
        "DS/EN 1992-1-1:2005 7.3.4, Formulae (7.11) and (7.14); "
        "DK NA variants are stated in the accompanying text.",
        "Every additive spacing term and h minus x are millimetres.",
    ),
    _e(
        "crack.2023.width", "C.7.5-1",
        "Serviceability: cracking and crack width",
        "EN 1992-1-1:2023 refined model",
        "4c15d71e9d8e368108149af68afc41acc767712cd71aa1ad7af0223bb5ae3d10",
        (
            _s(r"w_k", "characteristic crack width", "mm"),
            _s(r"k_w", "crack-width factor"),
            _s(r"k_1/r", "bar-position curvature factor"),
            _s(r"s_{r,m,cal}", "calculated mean crack spacing", "mm"),
            _s(r"\varepsilon_{sm}", "mean reinforcement strain"),
            _s(r"\varepsilon_{cm}", "mean concrete strain between cracks"),
            _s("h", "section depth in the crack direction", "mm"),
            _s("x", "neutral-axis depth from the compression face", "mm"),
            _s(r"a_{y,i}", "bar-i distance from the tension face", "mm"),
        ),
        "standard", "DS/EN 1992-1-1:2023 9.2.3, Formulae (9.8)-(9.9).",
        "The curvature factor is a ratio of millimetre lengths; spacing times strain gives millimetres.",
        uses=("crack.2023.spacing",),
    ),
    _e(
        "crack.2023.spacing", "C.7.5-2",
        "Serviceability: cracking and crack width",
        "EN 1992-1-1:2023 refined model",
        "3232760c0b31c26275f004adf2bf978d25bf8452b182b6966e3bfeb455cae8ea",
        (
            _s(r"s_{r,m,cal}", "calculated mean crack spacing", "mm"),
            _s("c", "clear cover", "mm"),
            _s(r"k_{fl}", "flexural coefficient"),
            _s(r"k_b", "bond coefficient"),
            _s(r"\phi", "bar diameter", "mm"),
            _s(r"\rho_{p,eff}", "effective reinforcement ratio"),
            _s(r"k_w", "crack-width factor"),
            _s("h", "section depth in the crack direction", "mm"),
            _s("x", "neutral-axis depth from the compression face", "mm"),
        ),
        "standard", "DS/EN 1992-1-1:2023 9.2.3, Formula (9.15).",
        "All spacing terms and the upper bound are millimetres.",
    ),
    _e(
        "fatigue.elastic.stress-range", "C.8.1-1", "Grouped fatigue",
        "Elastic stress ranges",
        "1c6d20674b30556d5158662f2eed158f78f16c0ec52b6134bf9ee4e728707878",
        (
            _s(r"\Delta\sigma_{Ed,i}", "design stress range for bin i", "MPa"),
            _s(r"\sigma(\cdot)", "stress reconstructed by the retained elastic solver", "MPa"),
            _s(r"S_l", "sustained section-action state", "actions"),
            _s(r"S_s", "cyclic section-action increment", "actions"),
            _s(r"\gamma_{Ff}", "fatigue action factor"),
            _s("i", "spectrum-bin index"),
        ),
        "project", _PROJECT,
        "Both solver stress evaluations are MPa; compatible action components are combined before solving.",
    ),
    _e(
        "fatigue.reinforcement.design-range", "C.8.2-1", "Grouped fatigue",
        "Reinforcement S-N and Miner check",
        "79409e2d84eb04d50e0b3ecdb1a23cbaee4988c086d4d63375c8dc87267f5514",
        (
            _s(r"\Delta\sigma_{Rd}", "design S-N reference stress range", "MPa"),
            _s(r"\Delta\sigma_{Rsk}", "characteristic S-N reference range", "MPa"),
            _s(r"\gamma_s", "fatigue-strength partial factor"),
        ),
        "mixed",
        "DS/EN 1992-1-1:2005+A1:2014 6.8.4 and Tables 6.3N/6.4N; "
        "DS/EN 1992-1-1:2023 Annex E.5 and Tables E.1/E.2; a custom detail is "
        "Project-defined / uncited.",
        "A stress range in MPa divided by a dimensionless partial factor remains MPa.",
    ),
    _e(
        "fatigue.reinforcement.life", "C.8.2-2", "Grouped fatigue",
        "Reinforcement S-N and Miner check",
        "525ca21ac74aa72c0202fba278ff55bfc0e4c951c7c4b29a1d0776e657bad217",
        (
            _s(r"N_{R,i}", "design fatigue life for bin i", "cycles"),
            _s(r"N^*", "reference cycle count at the S-N knee", "cycles"),
            _s(r"\Delta\sigma_{Rd}", "design S-N reference stress range", "MPa"),
            _s(r"\Delta\sigma_{Ed,i}", "design applied stress range for bin i", "MPa"),
            _s("k", "active S-N branch slope"),
            _s("i", "spectrum-bin index"),
        ),
        "mixed",
        "DS/EN 1992-1-1:2005+A1:2014 6.8.4 and Tables 6.3N/6.4N; "
        "DS/EN 1992-1-1:2023 Annex E.5 and Tables E.1/E.2; a custom detail is "
        "Project-defined / uncited.",
        "The MPa stress ratio is dimensionless, so multiplying N* retains cycles.",
        uses=("fatigue.reinforcement.design-range",),
    ),
    _e(
        "fatigue.reinforcement.miner", "C.8.2-3", "Grouped fatigue",
        "Reinforcement S-N and Miner check",
        "ace577b8ce30e7129bda1cc84198419a4fea29b0472f100afe793caddca79564",
        (
            _s("D", "Palmgren-Miner cumulative reinforcement damage"),
            _s(r"n_i", "applied cycles in bin i", "cycles"),
            _s(r"N_{R,i}", "design fatigue life for bin i", "cycles"),
            _s("i", "spectrum-bin index"),
        ),
        "mixed",
        "DS/EN 1992-1-1:2005+A1:2014 6.8.4; DS/EN 1992-1-1:2023 "
        "Annex E.5; a custom detail is Project-defined / uncited.",
        "Every cycle-count ratio and their sum are dimensionless.",
        uses=("fatigue.reinforcement.life",),
    ),
    _e(
        "fatigue.concrete.strength-2005", "C.8.4-1", "Grouped fatigue",
        "Concrete compression fatigue",
        "5123cf1171bbf2a16ddc81bf351ebaff1c8aa4f26bdec70f846f81f1a1b68ce9",
        (
            _s(r"f_{cd,fat}", "design concrete fatigue strength", "MPa"),
            _s(r"k_1", "fatigue-strength coefficient"),
            _s(r"\beta_{cc}(t_0)", "strength-development factor at first loading"),
            _s(r"\alpha_{cc}", "concrete strength coefficient"),
            _s(r"f_{ck}", "characteristic concrete strength", "MPa"),
            _s(r"\gamma_{c,fat}", "concrete fatigue partial factor"),
            _s("250", "reference strength used in the final reduction", "MPa"),
        ),
        "standard",
        "DS/EN 1992-1-1:2005+A1:2014 6.8.7, Formula (6.76); "
        "DS/EN 1992-2:2005/AC:2008 corrected 6.106.",
        "f_ck and the literal reference strength 250 are both MPa; all other factors are dimensionless.",
    ),
    _e(
        "fatigue.concrete.strength-2023", "C.8.4-2", "Grouped fatigue",
        "Concrete compression fatigue",
        "85e38c135904be5a3507e919a0649d9c209549ebb4ee3f0875ac978984e09eda",
        (
            _s(r"\eta_{cc}", "concrete strength reduction factor"),
            _s("40", "reference strength in the eta_cc relation", "MPa"),
            _s(r"f_{ck}", "characteristic concrete strength", "MPa"),
            _s(r"\eta_{cc,fat}", "fatigue concrete strength factor"),
            _s(r"f_{cd,fat}", "design concrete fatigue strength", "MPa"),
            _s(r"\beta_{cc}(t_0)", "strength-development factor at first loading"),
            _s(r"\gamma_{c,fat}", "concrete fatigue partial factor"),
        ),
        "standard", "DS/EN 1992-1-1:2023 10.5, Formula (10.5).",
        "The reference 40 and f_ck are both MPa; eta factors are dimensionless and f_cd,fat remains MPa.",
    ),
    _e(
        "fatigue.concrete.life", "C.8.4-3", "Grouped fatigue",
        "Concrete compression fatigue",
        "5a8cca7a9e50c8a23d37882d0fb575d459dcd187d9fd4e2a4c580da5cf154528",
        (
            _s(r"N_R", "concrete fatigue life expressed as a cycle count", "cycles"),
            _s("C", "selected concrete fatigue-life coefficient"),
            _s(r"E_{max}", "maximum normalized concrete stress"),
            _s(r"E_{min}", "minimum normalized concrete stress"),
            _s("R", "minimum-to-maximum normalized stress ratio"),
        ),
        "mixed",
        "DS/EN 1992-2:2005/AC:2008 6.106; DS/EN 1992-1-1:2023 E.5.3, "
        "Formulae (E.7)-(E.8); a user-defined relation is Project-defined / uncited.",
        "The logarithm acts on the numerical cycle count; its right-hand side is dimensionless.",
    ),
    _e(
        "fatigue.concrete.equivalent", "C.8.4-4", "Grouped fatigue",
        "Concrete compression fatigue",
        "4a70d70fdded41c242471c53a26554257d8444562547f5763c882c00a137bdcf",
        (
            _s(r"E_{max}", "maximum normalized concrete stress"),
            _s(r"E_{min}", "minimum normalized concrete stress"),
        ),
        "standard",
        "DS/EN 1992-1-1:2005 6.8.7, Formula (6.72); "
        "DS/EN 1992-1-1:2023 E.4.3, Formula (E.2).",
        "Both normalized stresses, the square-root term and the final criterion are dimensionless.",
    ),
    _e(
        "shear.2005.basic", "C.9-1", "Shear resistance without shear reinforcement",
        None,
        "e5a101ffeb8ed99a3ad22d269c843d73ab17a4830858ddcec135b958a9d0ee6c",
        (
            _s(r"V_{Rd,c}", "design shear resistance without links", "kN"),
            _s(r"C_{Rd,c}", "concrete shear coefficient"),
            _s("k", "size-effect factor"),
            _s(r"\rho_l", "longitudinal reinforcement ratio"),
            _s(r"f_{ck}", "characteristic concrete strength", "MPa"),
            _s(r"k_1", "axial-stress coefficient"),
            _s(r"\sigma_{cp}", "concrete axial stress, compression positive", "MPa"),
            _s(r"b_w", "effective web breadth", "mm"),
            _s("d", "effective depth", "mm"),
        ),
        "standard", "DS/EN 1992-1-1 6.2.2(1), Formula (6.2a); DK NA 6.2.2(1).",
        "The bracket is MPa; multiplying by b_w and d in mm2 and dividing by 1000 gives the published kN.",
    ),
    _e(
        "shear.2005.minimum", "C.9-2", "Shear resistance without shear reinforcement",
        None,
        "1279f09a95518892baa612be76e48350f9cf565aed5efd94aecadcf165c7cc67",
        (
            _s(r"V_{Rd,c}", "minimum design shear resistance without links", "kN"),
            _s(r"v_{min}", "minimum shear-stress term", "MPa"),
            _s(r"k_1", "axial-stress coefficient"),
            _s(r"\sigma_{cp}", "concrete axial stress, compression positive", "MPa"),
            _s(r"b_w", "effective web breadth", "mm"),
            _s("d", "effective depth", "mm"),
        ),
        "standard", "DS/EN 1992-1-1 6.2.2(1), Formula (6.2b); DK NA 6.2.2(1).",
        "The bracket is MPa; multiplying by b_w and d in mm2 and dividing by 1000 gives the published kN.",
    ),
    _e(
        "shear.2023.action-factor", "C.9-3",
        "Shear resistance without shear reinforcement", None,
        "57910d0569783bc00ef2c62b0755400dc51059b6ffd96017e3f7b50d92a5190d",
        (
            _s(r"a_{cs}", "effective shear span", "m"),
            _s(r"M_{Ed}", "applied design moment", "kNm"),
            _s(r"V_{Ed}", "applied design shear", "kN"),
            _s("d", "effective depth expressed for this equation", "m"),
            _s(r"k_{vp}", "action-dependent shear-depth factor"),
            _s(r"N_{Ed}", "applied design axial force, tension positive", "kN"),
        ),
        "standard", "DS/EN 1992-1-1:2023 Formula (8.30) and 8.2.2(4), Formula (8.31).",
        "M_Ed/V_Ed, a_cs and d are all metres here. The solver's stored d in mm is converted consistently before the max and ratio.",
    ),
    _e(
        "shear.links.2005", "C.9.1-1",
        "Shear resistance without shear reinforcement",
        "Members with shear reinforcement (links)",
        "8bbbf0a6261d72eea45965ba33b6b45bb65ff56f67fa308f8020f7f01598aed7",
        (
            _s(r"V_{Rd,s}", "link-yield shear resistance", "kN"),
            _s(r"A_{sw}/s", "effective link area per spacing", "mm2/mm"),
            _s("z", "internal lever arm", "mm"),
            _s(r"f_{ywd}", "design link yield strength", "MPa"),
            _s(r"\theta", "compression-strut angle", "degrees"),
            _s(r"V_{Rd,max}", "concrete-strut shear resistance", "kN"),
            _s(r"\alpha_{cw}", "compression-chord factor"),
            _s(r"b_w", "effective web breadth", "mm"),
            _s(r"\nu_1", "strut effectiveness factor"),
            _s(r"f_{cd}", "design concrete strength", "MPa"),
        ),
        "standard", "DS/EN 1992-1-1 6.2.3, Formulae (6.8)-(6.9); DK NA 6.2.3.",
        "The retained mm/MPa kernels convert force results to kN; every trigonometric factor is dimensionless.",
    ),
    _e(
        "shear.links.2023", "C.9.1-2",
        "Shear resistance without shear reinforcement",
        "Members with shear reinforcement (links)",
        "85cfe8d83d492a4af5a911a3a7c1dc332f88dcf75ae2b1434c6ed6fef91d3439",
        (
            _s(r"\tau_{Rd,sy}", "link-yield shear-stress resistance", "MPa"),
            _s(r"\rho_w", "provided shear-link reinforcement ratio"),
            _s(r"f_{ywd}", "design link yield strength", "MPa"),
            _s(r"\theta", "compression-field angle", "degrees"),
            _s(r"\sigma_{cd}", "compression-field stress", "MPa"),
            _s(r"\tau_{Ed}", "applied design shear stress", "MPa"),
            _s(r"\nu", "compression-field strength factor"),
            _s(r"f_{cd}", "design concrete strength", "MPa"),
        ),
        "standard", "DS/EN 1992-1-1:2023 Formulae (8.42) and (8.44).",
        "Each equation is a dimensionless factor times stress in MPa.",
        uses=("detailing.links.minimum-ratio",),
    ),
    _e(
        "torsion.resistance", "C.10-1", "Torsion (thin-walled tube)", None,
        "a5291e17e74a23e3ec4f59d6a894be40eb72247ab67a266cb5f0a7d14667bff6",
        (
            _s(r"T_{Rd,s}", "closed-link torsion resistance", "kNm"),
            _s(r"A_{sw}/s", "effective closed-link area per spacing", "mm2/mm"),
            _s(r"A_k", "area enclosed by the torsion centre-line", "m2"),
            _s(r"f_{ywd}", "design link yield strength", "MPa"),
            _s(r"\theta", "compression-strut angle", "degrees"),
            _s(r"T_{Rd,max}", "torsion concrete-strut resistance", "kNm"),
            _s(r"\nu", "torsion strut effectiveness factor"),
            _s(r"\alpha_{cw}", "compression-chord factor"),
            _s(r"f_{cd}", "design concrete strength", "MPa"),
            _s(r"t_{ef}", "effective torsion-wall thickness in this equation", "m"),
        ),
        "standard",
        "DS/EN 1992-1-1 6.3.2, Formula (6.30); wall shear flow (6.27) and "
        "transverse equilibrium (6.8).",
        "The retained kernel uses A_k in m2. It converts entered t_ef from mm to m for T_Rd,max; the documented mm2/mm-MPa-m2 identity gives T_Rd,s in kNm.",
    ),
    _e(
        "torsion.shear-interaction", "C.10-2", "Torsion (thin-walled tube)", None,
        "0fde836b7555c3d5e63a45cc971b43eb8b53aeb68405c7294673b1704575b79b",
        (
            _s(r"T_{Ed}", "applied design torsion", "kNm"),
            _s(r"T_{Rd,max}", "torsion concrete-strut resistance", "kNm"),
            _s(r"V_{Ed}", "applied design shear", "kN"),
            _s(r"V_{Rd,max}", "shear concrete-strut resistance", "kN"),
        ),
        "standard", "DS/EN 1992-1-1 6.3.2, Formula (6.29).",
        "Each demand/resistance pair has identical units, so the interaction sum is dimensionless.",
        uses=("torsion.resistance", "shear.links.2005"),
    ),
    _e(
        "combined.strut-interaction", "C.11-1", "Combined M-V-T interaction", None,
        "0fde836b7555c3d5e63a45cc971b43eb8b53aeb68405c7294673b1704575b79b",
        (
            _s(r"T_{Ed}", "applied design torsion", "kNm"),
            _s(r"T_{Rd,max}", "torsion concrete-strut resistance", "kNm"),
            _s(r"V_{Ed}", "applied design shear", "kN"),
            _s(r"V_{Rd,max}", "shear concrete-strut resistance", "kN"),
        ),
        "standard", "DS/EN 1992-1-1 6.3.2, Formula (6.29).",
        "Each demand/resistance pair has identical units, so the interaction sum is dimensionless.",
        uses=("torsion.shear-interaction",),
    ),
    _e(
        "combined.dk-na-sum", "C.11-2", "Combined M-V-T interaction", None,
        "850bd52dcea64b9e779bc904fa701d42d2d47657af17ea0f1ab0f32263f3ab8b",
        (
            _s(r"S_{Ed}", "one acting sectional-force demand, by action family", "actions"),
            _s(r"S_{Rd}", "resistance to the same sectional-force action", "actions"),
        ),
        "standard", "DS/EN 1992-1-1 DK NA:2024 6.3.2(6).",
        "Every term divides a demand by the resistance for that same action and is dimensionless.",
    ),
)


def _validate_registry() -> None:
    if len(_SPECS) != 32:
        raise RuntimeError(f"Expected 32 manual equations, got {len(_SPECS)}.")
    keys = tuple(spec.key for spec in _SPECS)
    numbers = tuple(spec.number for spec in _SPECS)
    if len(set(keys)) != len(keys) or any(not _KEY_RE.fullmatch(key) for key in keys):
        raise RuntimeError("Manual equation keys must be unique and canonical.")
    if len(set(numbers)) != len(numbers):
        raise RuntimeError("Manual equation numbers must be unique.")
    known = set(keys)
    for spec in _SPECS:
        if not spec.symbols or not spec.dimensional_note.strip():
            raise RuntimeError(f"Incomplete manual equation {spec.key!r}.")
        names = tuple(symbol.latex for symbol in spec.symbols)
        if len(set(names)) != len(names):
            raise RuntimeError(f"Duplicate symbol in manual equation {spec.key!r}.")
        for symbol in spec.symbols:
            if not symbol.latex.strip() or not symbol.meaning.strip():
                raise RuntimeError(f"Blank symbol field in manual equation {spec.key!r}.")
            if symbol.unit not in _UNIT_MARKUP:
                raise RuntimeError(f"Unknown unit {symbol.unit!r} in {spec.key!r}.")
        if spec.source_kind == "project":
            if spec.source != _PROJECT:
                raise RuntimeError(f"Project equation {spec.key!r} has a citation.")
        elif spec.source_kind == "mixed":
            if "Project-defined / uncited" not in spec.source:
                raise RuntimeError(f"Mixed equation {spec.key!r} hides its project part.")
        elif spec.source_kind != "standard":
            raise RuntimeError(f"Invalid source kind in {spec.key!r}.")
        if any(dependency not in known or dependency == spec.key for dependency in spec.uses):
            raise RuntimeError(f"Invalid equation dependency in {spec.key!r}.")


_validate_registry()
_BY_KEY = {spec.key: spec for spec in _SPECS}


def manual_equation_specs() -> tuple[ManualEquationSpec, ...]:
    return _SPECS


def manual_equation_spec(key: str) -> ManualEquationSpec:
    try:
        return _BY_KEY[str(key)]
    except KeyError as exc:
        raise ValueError(f"Unknown manual equation key: {key!r}.") from exc


def unit_markup(unit: str) -> str:
    try:
        return _UNIT_MARKUP[str(unit)]
    except KeyError as exc:
        raise ValueError(f"Unknown manual equation unit: {unit!r}.") from exc


def expression_sha256(expression: str) -> str:
    return hashlib.sha256(expression.strip().encode("utf-8")).hexdigest()


def register_manual_blocks(blocks: Iterable[tuple]) -> tuple[tuple, ...]:
    """Validate and segment all authored display equations before publication."""

    output = []
    spec_index = 0
    part_index = section_index = subsection_index = equation_index = 0
    part = section = subsection = None

    for raw in blocks:
        block = tuple(raw)
        kind = block[0]
        if kind == "part":
            part_index += 1
            section_index = subsection_index = equation_index = 0
            part, section, subsection = block[1], None, None
        elif kind == "h1":
            section_index += 1
            subsection_index = equation_index = 0
            section, subsection = block[1], None
        elif kind == "h2":
            subsection_index += 1
            equation_index = 0
            subsection = block[1]

        if kind != "md":
            output.append(block)
            continue

        text = block[1]
        segments = []
        cursor = 0
        for match in _DISPLAY_RE.finditer(text):
            if spec_index >= len(_SPECS):
                raise ValueError("The manual contains an unknown display equation.")
            spec = _SPECS[spec_index]
            equation_index += 1
            letter = chr(ord("A") + part_index - 1)
            number = (
                f"{letter}.{section_index}.{subsection_index}-{equation_index}"
                if subsection_index
                else f"{letter}.{section_index}-{equation_index}"
            )
            if (part, section, subsection) != (_PART_C, spec.section, spec.subsection):
                raise ValueError(f"Manual equation {spec.key!r} moved to another context.")
            if number != spec.number:
                raise ValueError(f"Manual equation {spec.key!r} moved from {spec.number}.")
            expression = match.group(1).strip()
            if expression_sha256(expression) != spec.expression_sha256:
                raise ValueError(f"Manual equation {spec.key!r} changed expression.")
            if match.start() > cursor:
                segments.append(ManualMarkdownSegment(text[cursor:match.start()]))
            occurrence = ManualEquationOccurrence(spec, expression, match.group(2))
            segments.append(ManualMarkdownSegment(match.group(0), occurrence))
            cursor = match.end()
            spec_index += 1
        if cursor < len(text):
            segments.append(ManualMarkdownSegment(text[cursor:]))
        if not segments:
            segments.append(ManualMarkdownSegment(text))
        if "".join(segment.markdown for segment in segments) != text:
            raise RuntimeError("Manual equation segmentation changed authored Markdown.")
        output.append((kind, text, tuple(segments)))

    if spec_index != len(_SPECS):
        missing = tuple(spec.key for spec in _SPECS[spec_index:])
        raise ValueError(f"The manual is missing registered equations: {missing!r}.")
    return tuple(output)
