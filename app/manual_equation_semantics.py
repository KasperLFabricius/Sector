"""Symbols, units, dimensions and direct uses for Part C manual equations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from manual_equation_source import (
    MANUAL_EQUATION_SOURCES,
    ManualEquationSource,
    SourcedManualEquation,
    bind_manual_equation_sources,
)


DIMENSIONLESS = "dimensionless"
ACTIONS = "actions"
CYCLES = "cycles"
DAYS = "days"
DEGREES = "degrees"
MPA = "MPa"
MPA_HALF = "MPa^(1/2)"
MPA_TWO_THIRDS = "MPa^(2/3)"
MM = "mm"
MM2 = "mm2"
METRE = "m"
METRE2 = "m2"
PER_METRE = "1/m"
KN = "kN"
KNM = "kNm"

UNITS = frozenset(
    (
        DIMENSIONLESS,
        ACTIONS,
        CYCLES,
        DAYS,
        DEGREES,
        MPA,
        MPA_HALF,
        MPA_TWO_THIRDS,
        MM,
        MM2,
        METRE,
        METRE2,
        PER_METRE,
        KN,
        KNM,
    )
)


@dataclass(frozen=True, slots=True)
class ManualEquationSymbol:
    """One exact published symbol, meaning and physical unit."""

    markup: str
    meaning: str
    unit: str


@dataclass(frozen=True, slots=True)
class ManualEquationSemantics:
    """Complete non-visual semantics for one accepted manual equation."""

    ordinal: int
    key: str
    number: str
    symbols: tuple[ManualEquationSymbol, ...]
    dimensional_note: str
    direct_uses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SemanticManualEquation:
    """One accepted sourced expression bound to its exact semantics."""

    equation: SourcedManualEquation
    semantics: ManualEquationSemantics


def _symbol(
    markup: str,
    meaning: str,
    unit: str = DIMENSIONLESS,
) -> ManualEquationSymbol:
    return ManualEquationSymbol(markup, meaning, unit)


def _semantics(
    ordinal: int,
    key: str,
    number: str,
    symbols: tuple[ManualEquationSymbol, ...],
    dimensional_note: str,
    direct_uses: tuple[str, ...] = (),
) -> ManualEquationSemantics:
    return ManualEquationSemantics(
        ordinal,
        key,
        number,
        symbols,
        dimensional_note,
        direct_uses,
    )


MANUAL_EQUATION_SEMANTICS = (
    _semantics(
        1,
        "manual.material.concrete-law",
        "C3-1",
        (
            _symbol(r"\sigma_c", "concrete compressive stress", MPA),
            _symbol(r"f_{cd}", "design concrete compressive strength", MPA),
            _symbol(r"\varepsilon_c", "concrete compressive strain"),
            _symbol(r"\varepsilon_{c2}", "strain at the start of the plateau"),
            _symbol(r"\varepsilon_{cu2}", "ultimate concrete compressive strain"),
            _symbol("n", "parabola exponent"),
        ),
        "The stress branch is MPa times a dimensionless material law; every "
        "strain and strain limit is dimensionless.",
    ),
    _semantics(
        2,
        "manual.material.steel-law",
        "C3-2",
        (
            _symbol(r"\sigma_s", "mild-reinforcement stress", MPA),
            _symbol(r"E_{s,d}", "design reinforcement modulus", MPA),
            _symbol(r"\varepsilon_s", "mild-reinforcement strain"),
            _symbol(r"\varepsilon_{yd}", "design yield strain"),
            _symbol(r"f_{yd}", "design yield strength", MPA),
            _symbol(r"f_{yk}", "characteristic yield strength", MPA),
            _symbol(r"\gamma_s", "reinforcement partial factor"),
        ),
        "Modulus times strain gives MPa, strength divided by a partial factor "
        "gives MPa, and strength divided by modulus gives dimensionless strain.",
    ),
    _semantics(
        3,
        "manual.material.prestress-law",
        "C3-3",
        (
            _symbol(r"\varepsilon_{p,j}", "total strain of tendon j"),
            _symbol(r"\varepsilon_{p,IS,j}", "initial strain of tendon j"),
            _symbol(r"\kappa", "section curvature", PER_METRE),
            _symbol(r"s_{p,j}", "depth coordinate of tendon j", METRE),
            _symbol(r"s_{na}", "neutral-axis depth coordinate", METRE),
            _symbol(r"\sigma_p", "prestressing-steel stress", MPA),
            _symbol(
                r"f(\varepsilon_p)",
                "selected prestressing law evaluated at total strain",
                MPA,
            ),
            _symbol(r"\varepsilon_p", "prestressing-steel total strain"),
            _symbol(r"f_{pd}", "design 0.1 percent proof strength", MPA),
            _symbol(
                r"f_{p0.1k}",
                "characteristic 0.1 percent proof strength",
                MPA,
            ),
            _symbol(r"\gamma_s", "prestressing-steel partial factor"),
        ),
        "Curvature times a coordinate difference is dimensionless strain; the "
        "selected material law maps that strain to MPa, and strength divided by "
        "the partial factor remains MPa.",
    ),
    _semantics(
        4,
        "manual.plastic.governing-curvature",
        "C4-1",
        (
            _symbol(r"\kappa", "governing ultimate curvature", PER_METRE),
            _symbol(r"\varepsilon_{cu2}", "ultimate concrete strain magnitude"),
            _symbol(r"c", "concrete compression depth", METRE),
            _symbol(r"\varepsilon_{u,i}", "ultimate strain of active bar i"),
            _symbol(r"s_{na}", "neutral-axis depth coordinate", METRE),
            _symbol(r"s_{b,i}", "depth coordinate of bar i", METRE),
            _symbol(r"\varepsilon_{pu,j}", "ultimate total strain of tendon j"),
            _symbol(r"\varepsilon_{p,IS,j}", "initial strain of tendon j"),
            _symbol(r"s_{p,j}", "depth coordinate of tendon j", METRE),
        ),
        "Every material-limit candidate is dimensionless strain divided by a "
        "distance in metres, so every branch and the governing minimum has unit "
        "1/m.",
    ),
    _semantics(
        5,
        "manual.detailing.minimum-2005",
        "C5-1",
        (
            _symbol(
                r"A_{s,min}",
                "required minimum longitudinal reinforcement area",
                MM2,
            ),
            _symbol(r"A_{s,prov}", "provided longitudinal reinforcement area", MM2),
            _symbol(r"f_{ctm}", "mean concrete tensile strength", MPA),
            _symbol(r"f_{yk}", "characteristic reinforcement strength", MPA),
            _symbol(r"b_t", "mean width of the tension zone", MM),
            _symbol(r"d", "effective depth", MM),
        ),
        "The strength ratio is dimensionless and b_t times d is mm2, so both "
        "the required and provided areas are compared in mm2.",
    ),
    _semantics(
        6,
        "manual.detailing.minimum-2023-bending",
        "C5-2",
        (
            _symbol(
                r"M_{R,nom}",
                "nominal bending resistance at the stated axial force",
                KNM,
            ),
            _symbol(
                r"M_{cr}",
                "gross-section cracking moment at the stated axial force",
                KNM,
            ),
            _symbol(r"N_{Ed}", "applied design axial force", KN),
        ),
        "Both moment functions are evaluated at the same N_Ed in kN and are "
        "compared in kNm.",
    ),
    _semantics(
        7,
        "manual.detailing.minimum-2023-axial",
        "C5-3",
        (
            _symbol(r"A_{s,i}", "area of reinforcement element i", MM2),
            _symbol(
                r"f_{yk,i}",
                "characteristic yield strength of element i",
                MPA,
            ),
            _symbol(r"A_c", "gross concrete area", MM2),
            _symbol(r"f_{ctm}", "mean concrete tensile strength", MPA),
        ),
        "Each side is a force because MPa equals N/mm2 and each strength is "
        "multiplied by an area in mm2.",
    ),
    _semantics(
        8,
        "manual.detailing.clear-spacing",
        "C5-4",
        (
            _symbol(r"c_{clear}", "provided clear reinforcement spacing", MM),
            _symbol(r"\phi_{max}", "larger detailing diameter of the pair", MM),
            _symbol(r"D_{upper}", "upper aggregate size", MM),
        ),
        "Every maximum branch is a length in mm, including the explicit 5 mm "
        "allowance and 20 mm lower bound.",
    ),
    _semantics(
        9,
        "manual.detailing.links.minimum-ratio",
        "C5-5",
        (
            _symbol(r"\rho_w", "provided shear-link reinforcement ratio"),
            _symbol(r"A_{sw}", "effective shear-link area", MM2),
            _symbol(r"s", "longitudinal link spacing", MM),
            _symbol(r"b_w", "effective web breadth", MM),
            _symbol(r"\rho_{w,min}", "minimum shear-link ratio"),
            _symbol(r"c", "edition-selected minimum-ratio coefficient", MPA_HALF),
            _symbol(
                r"f_{ck}",
                "characteristic concrete compressive strength",
                MPA,
            ),
            _symbol(r"f_{ywk}", "characteristic link yield strength", MPA),
        ),
        "A_sw/(s b_w) is dimensionless. The coefficient c retains unit "
        "MPa^(1/2), so c sqrt(f_ck)/f_ywk is also dimensionless.",
    ),
    _semantics(
        10,
        "manual.detailing.links.spacing",
        "C5-6",
        (
            _symbol(r"s_l", "maximum longitudinal link spacing", MM),
            _symbol(r"s_t", "maximum transverse link spacing", MM),
            _symbol(r"d", "effective depth", MM),
        ),
        "Every compared term is a length in mm, including the explicit 600 mm "
        "upper bound.",
    ),
    _semantics(
        11,
        "manual.detailing.torsion.minimum-ratio",
        "C5-7",
        (
            _symbol(r"\rho_{w,T}", "provided torsion-link reinforcement ratio"),
            _symbol(r"A_{leg}", "area of one effective closed-link leg", MM2),
            _symbol(r"s", "longitudinal closed-link spacing", MM),
            _symbol(r"t_{ef}", "effective torsion-wall thickness", MM),
            _symbol(r"\rho_{w,min}", "minimum link ratio from Equation C5-5"),
        ),
        "A_leg/(s t_ef) is dimensionless and is compared with the dimensionless "
        "minimum ratio from Equation C5-5.",
        ("manual.detailing.links.minimum-ratio",),
    ),
    _semantics(
        12,
        "manual.crack.2005.width",
        "C7-1",
        (
            _symbol(r"w_k", "characteristic crack width", MM),
            _symbol(r"s_{r,max}", "maximum crack spacing from Equation C7-2", MM),
            _symbol(r"\varepsilon_{sm}", "mean reinforcement strain"),
            _symbol(r"\varepsilon_{cm}", "mean concrete strain between cracks"),
            _symbol(r"\sigma_s", "reinforcement stress", MPA),
            _symbol(r"k_t", "load-duration factor"),
            _symbol(r"f_{ct,eff}", "effective concrete tensile strength", MPA),
            _symbol(r"\rho_{p,eff}", "effective reinforcement ratio"),
            _symbol(r"\alpha_e", "effective modular ratio"),
            _symbol(r"E_s", "reinforcement modulus", MPA),
        ),
        "Every stress divided by E_s is dimensionless strain; the spacing from "
        "Equation C7-2 in mm times the retained strain difference gives w_k in mm.",
        ("manual.crack.2005.spacing",),
    ),
    _semantics(
        13,
        "manual.crack.2005.spacing",
        "C7-2",
        (
            _symbol(r"s_{r,max}", "maximum crack spacing", MM),
            _symbol(r"k_3", "cover coefficient"),
            _symbol(r"c", "reinforcement cover", MM),
            _symbol(r"k_1", "bond coefficient"),
            _symbol(r"k_2", "strain-distribution coefficient"),
            _symbol(r"k_4", "bar-diameter coefficient"),
            _symbol(r"\phi", "reinforcement diameter", MM),
            _symbol(r"\rho_{p,eff}", "effective reinforcement ratio"),
            _symbol(r"h", "section depth", MM),
            _symbol(r"x", "neutral-axis depth", MM),
        ),
        "All coefficients and the reinforcement ratio are dimensionless, so both "
        "the reinforcement branch and 1.3(h-x) resolve to mm.",
    ),
    _semantics(
        14,
        "manual.crack.2023.width",
        "C7-3",
        (
            _symbol(r"w_k", "characteristic crack width", MM),
            _symbol(r"k_w", "characteristic crack-width factor"),
            _symbol(r"k_1/r", "position-dependent strain factor"),
            _symbol(
                r"s_{r,m,cal}",
                "calculated mean crack spacing from Equation C7-4",
                MM,
            ),
            _symbol(r"\varepsilon_{sm}", "mean reinforcement strain"),
            _symbol(r"\varepsilon_{cm}", "mean concrete strain between cracks"),
            _symbol(r"h", "section depth", MM),
            _symbol(r"x", "neutral-axis depth", MM),
            _symbol(r"a_{y,i}", "bar position from the tension face", MM),
        ),
        "The position ratio and strain difference are dimensionless; the spacing "
        "from Equation C7-4 in mm therefore gives w_k in mm.",
        ("manual.crack.2023.spacing",),
    ),
    _semantics(
        15,
        "manual.crack.2023.spacing",
        "C7-4",
        (
            _symbol(r"s_{r,m,cal}", "calculated mean crack spacing", MM),
            _symbol(r"c", "reinforcement cover", MM),
            _symbol(r"k_{fl}", "flange factor"),
            _symbol(r"k_b", "bond coefficient"),
            _symbol(r"\phi", "reinforcement diameter", MM),
            _symbol(r"\rho_{p,eff}", "effective reinforcement ratio"),
            _symbol(r"k_w", "characteristic crack-width factor"),
            _symbol(r"h", "section depth", MM),
            _symbol(r"x", "neutral-axis depth", MM),
        ),
        "Every coefficient and ratio is dimensionless, so the calculated spacing "
        "and its 1.3(h-x)/k_w cap are both lengths in mm.",
    ),
    _semantics(
        16,
        "manual.fatigue.stress-range",
        "C8-1",
        (
            _symbol(r"\Delta\sigma_{Ed,i}", "design stress range in bin i", MPA),
            _symbol(
                r"\sigma(S)",
                "stress returned by the retained elastic solver for action state S",
                MPA,
            ),
            _symbol(r"S_l", "sustained section-action state", ACTIONS),
            _symbol(r"S_s", "cyclic section-action increment", ACTIONS),
            _symbol(r"\gamma_{Ff}", "fatigue action factor"),
        ),
        "The action factor scales an action vector without changing its action "
        "units; the retained elastic operator maps both action states to MPa, so "
        "their absolute stress difference is MPa.",
    ),
    _semantics(
        17,
        "manual.fatigue.reinforcement.design-range",
        "C8-2",
        (
            _symbol(r"\Delta\sigma_{Rd}", "design reference stress range", MPA),
            _symbol(
                r"\Delta\sigma_{Rsk}",
                "characteristic reference stress range",
                MPA,
            ),
            _symbol(r"\gamma_s", "reinforcement fatigue partial factor"),
        ),
        "Dividing the characteristic stress range in MPa by a dimensionless "
        "partial factor preserves MPa.",
    ),
    _semantics(
        18,
        "manual.fatigue.reinforcement.life",
        "C8-3",
        (
            _symbol(r"N_{R,i}", "design fatigue life for bin i", CYCLES),
            _symbol(r"N^*", "S-N knee life", CYCLES),
            _symbol(
                r"\Delta\sigma_{Rd}",
                "design reference range from Equation C8-2",
                MPA,
            ),
            _symbol(
                r"\Delta\sigma_{Ed,i}",
                "design stress range from Equation C8-1",
                MPA,
            ),
            _symbol(r"k", "selected S-N slope"),
        ),
        "The stress ratio and its power are dimensionless, so multiplying by N* "
        "leaves the fatigue life in cycles.",
        (
            "manual.fatigue.reinforcement.design-range",
            "manual.fatigue.stress-range",
        ),
    ),
    _semantics(
        19,
        "manual.fatigue.reinforcement.miner",
        "C8-4",
        (
            _symbol(r"D", "reinforcement Miner damage"),
            _symbol(r"n_i", "applied cycles in bin i", CYCLES),
            _symbol(
                r"N_{R,i}",
                "design fatigue life from Equation C8-3",
                CYCLES,
            ),
        ),
        "Each applied-life ratio divides cycles by cycles, so every term and the "
        "Miner sum are dimensionless.",
        ("manual.fatigue.reinforcement.life",),
    ),
    _semantics(
        20,
        "manual.fatigue.concrete.strength-2005",
        "C8-5",
        (
            _symbol(r"f_{cd,fat}", "design concrete fatigue strength", MPA),
            _symbol(r"k_1", "2005 concrete fatigue-strength coefficient"),
            _symbol(r"\beta_{cc}(t_0)", "concrete age factor"),
            _symbol(r"t_0", "age at the start of cyclic loading", DAYS),
            _symbol(r"\alpha_{cc}", "concrete strength coefficient"),
            _symbol(
                r"f_{ck}",
                "characteristic concrete compressive strength",
                MPA,
            ),
            _symbol(r"\gamma_{c,fat}", "concrete fatigue partial factor"),
        ),
        "The literal 250 has unit MPa, so (1-f_ck/250 MPa) is dimensionless; "
        "all other factors are dimensionless and the result retains MPa.",
    ),
    _semantics(
        21,
        "manual.fatigue.concrete.strength-2023",
        "C8-6",
        (
            _symbol(r"\eta_{cc}", "concrete strength reduction factor"),
            _symbol(r"\eta_{cc,fat}", "concrete fatigue reduction factor"),
            _symbol(
                r"f_{ck}",
                "characteristic concrete compressive strength",
                MPA,
            ),
            _symbol(r"\beta_{cc}(t_0)", "concrete age factor"),
            _symbol(r"t_0", "age at the start of cyclic loading", DAYS),
            _symbol(r"\gamma_{c,fat}", "concrete fatigue partial factor"),
            _symbol(r"f_{cd,fat}", "design concrete fatigue strength", MPA),
        ),
        "The literal 40 has unit MPa, so (40 MPa/f_ck)^(1/3) is dimensionless; "
        "the reduction and age factors are dimensionless and f_cd,fat retains MPa.",
    ),
    _semantics(
        22,
        "manual.fatigue.concrete.life",
        "C8-7",
        (
            _symbol(r"N_R", "concrete fatigue life", CYCLES),
            _symbol(r"C", "selected concrete fatigue-life coefficient"),
            _symbol(r"E_{max}", "maximum design stress ratio"),
            _symbol(r"R", "minimum-to-maximum compression-stress ratio"),
        ),
        "log10 acts on the numerical cycle count N_R/(1 cycle); C, E_max, R and "
        "the complete right-hand side are dimensionless.",
    ),
    _semantics(
        23,
        "manual.fatigue.concrete.equivalent",
        "C8-8",
        (
            _symbol(r"E_{max}", "maximum concrete fatigue stress ratio"),
            _symbol(r"E_{min}", "minimum concrete fatigue stress ratio"),
        ),
        "The stress ratio, square root, numerical coefficient and final criterion "
        "are all dimensionless.",
    ),
    _semantics(
        24,
        "manual.shear.no-links.variable",
        "C9-1",
        (
            _symbol(r"V_{Rd,c}", "design shear resistance without links", KN),
            _symbol(
                r"C_{Rd,c}",
                "empirical concrete shear coefficient",
                MPA_TWO_THIRDS,
            ),
            _symbol(r"k", "size-effect factor"),
            _symbol(r"\rho_l", "longitudinal tension-reinforcement ratio"),
            _symbol(
                r"f_{ck}",
                "characteristic concrete compressive strength",
                MPA,
            ),
            _symbol(r"k_1", "axial-stress coefficient"),
            _symbol(
                r"\sigma_{cp}",
                "concrete axial stress, compression positive",
                MPA,
            ),
            _symbol(r"b_w", "effective web breadth", MM),
            _symbol(r"d", "effective depth", MM),
        ),
        "C_Rd,c has unit MPa^(2/3), so it times the cube root of f_ck is MPa; "
        "the bracket is MPa, MPa times b_w d in mm2 gives N, and publication "
        "converts that force to kN.",
    ),
    _semantics(
        25,
        "manual.shear.no-links.minimum",
        "C9-2",
        (
            _symbol(r"V_{Rd,c}", "minimum design shear resistance", KN),
            _symbol(r"v_{min}", "minimum shear-stress term", MPA),
            _symbol(r"k_1", "axial-stress coefficient"),
            _symbol(
                r"\sigma_{cp}",
                "concrete axial stress, compression positive",
                MPA,
            ),
            _symbol(r"b_w", "effective web breadth", MM),
            _symbol(r"d", "effective depth", MM),
        ),
        "The bracket is MPa; multiplying by b_w d in mm2 gives N, which is "
        "published as kN.",
    ),
    _semantics(
        26,
        "manual.shear.action-factor-2023",
        "C9-3",
        (
            _symbol(r"a_{cs}", "effective shear span", METRE),
            _symbol(r"M_{Ed}", "applied design moment", KNM),
            _symbol(r"V_{Ed}", "applied design shear", KN),
            _symbol(r"d", "effective depth in the action-factor relation", METRE),
            _symbol(r"k_{vp}", "action-dependent shear-depth factor"),
            _symbol(
                r"N_{Ed}",
                "applied design axial force, tension positive",
                KN,
            ),
        ),
        "M_Ed/V_Ed has unit kNm/kN = m and therefore compares with d in m; "
        "N_Ed/|V_Ed| and d/(3 a_cs) are dimensionless, so k_vp is dimensionless.",
    ),
    _semantics(
        27,
        "manual.shear.links-2005",
        "C9-4",
        (
            _symbol(r"V_{Rd,s}", "shear-link resistance", KN),
            _symbol(r"A_{sw}", "effective shear-link area", MM2),
            _symbol(r"s", "longitudinal link spacing", MM),
            _symbol(r"z", "internal lever arm", MM),
            _symbol(r"f_{ywd}", "design link yield strength", MPA),
            _symbol(r"\theta", "concrete strut angle", DEGREES),
            _symbol(r"V_{Rd,max}", "concrete-strut shear resistance", KN),
            _symbol(r"\alpha_{cw}", "compression-chord factor"),
            _symbol(r"b_w", "effective web breadth", MM),
            _symbol(r"\nu_1", "concrete strut effectiveness factor"),
            _symbol(r"f_{cd}", "design concrete compressive strength", MPA),
        ),
        "A_sw z/s and b_w z are areas in mm2; multiplying by MPa gives N, "
        "which is published as kN. Trigonometric factors are dimensionless.",
    ),
    _semantics(
        28,
        "manual.shear.links-2023",
        "C9-5",
        (
            _symbol(r"\tau_{Rd,sy}", "link-controlled shear-stress resistance", MPA),
            _symbol(r"\rho_w", "shear-link ratio from Equation C5-5"),
            _symbol(r"f_{ywd}", "design link yield strength", MPA),
            _symbol(r"\theta", "concrete strut angle", DEGREES),
            _symbol(r"\sigma_{cd}", "concrete strut stress", MPA),
            _symbol(r"\tau_{Ed}", "applied design shear stress", MPA),
            _symbol(r"\nu", "concrete strut effectiveness factor"),
            _symbol(r"f_{cd}", "design concrete compressive strength", MPA),
        ),
        "The link ratio and trigonometric factors are dimensionless; both the "
        "link branch and concrete-strut inequality therefore compare stresses in MPa.",
        ("manual.detailing.links.minimum-ratio",),
    ),
    _semantics(
        29,
        "manual.torsion.resistance",
        "C10-1",
        (
            _symbol(r"T_{Rd,s}", "closed-link torsion resistance", KNM),
            _symbol(r"A_{sw}", "effective closed-link area", MM2),
            _symbol(r"s", "longitudinal closed-link spacing", MM),
            _symbol(r"A_k", "area enclosed by the wall centre-line", METRE2),
            _symbol(r"f_{ywd}", "design link yield strength", MPA),
            _symbol(r"\theta", "concrete strut angle", DEGREES),
            _symbol(r"T_{Rd,max}", "concrete-strut torsion resistance", KNM),
            _symbol(r"\nu", "concrete strut effectiveness factor"),
            _symbol(r"\alpha_{cw}", "compression-chord factor"),
            _symbol(r"f_{cd}", "design concrete compressive strength", MPA),
            _symbol(r"t_{ef}", "effective torsion-wall thickness", METRE),
        ),
        "The steel branch converts A_sw/s from mm2/mm and A_k from m2 before "
        "combining with MPa and publishing N mm as kNm. The crushing branch "
        "likewise converts A_k in m2 and t_ef in m so MPa A_k t_ef is published "
        "as kNm; all trigonometric factors are dimensionless.",
    ),
    _semantics(
        30,
        "manual.torsion.strut-interaction",
        "C10-2",
        (
            _symbol(r"T_{Ed}", "applied design torsion", KNM),
            _symbol(
                r"T_{Rd,max}",
                "concrete-strut torsion resistance from Equation C10-1",
                KNM,
            ),
            _symbol(r"V_{Ed}", "applied design shear", KN),
            _symbol(
                r"V_{Rd,max}",
                "concrete-strut shear resistance from Equation C9-4",
                KN,
            ),
        ),
        "Each demand is divided by a resistance with the same unit, so both "
        "ratios and their sum are dimensionless.",
        (
            "manual.torsion.resistance",
            "manual.shear.links-2005",
        ),
    ),
    _semantics(
        31,
        "manual.combined.strut-interaction",
        "C11-1",
        (
            _symbol(r"T_{Ed}", "applied design torsion", KNM),
            _symbol(r"T_{Rd,max}", "concrete-strut torsion resistance", KNM),
            _symbol(r"V_{Ed}", "applied design shear", KN),
            _symbol(r"V_{Rd,max}", "concrete-strut shear resistance", KN),
        ),
        "Each demand is divided by a resistance with the same unit, so the "
        "combined concrete-strut interaction is dimensionless.",
        ("manual.torsion.strut-interaction",),
    ),
    _semantics(
        32,
        "manual.combined.utilisation",
        "C11-2",
        (
            _symbol(r"S_{Ed}", "design action effect", ACTIONS),
            _symbol(r"S_{Rd}", "matching design resistance", ACTIONS),
        ),
        "Every paired demand and resistance has the same concrete action unit, "
        "so each ratio and the complete sum are dimensionless.",
    ),
)


DIRECT_DEPENDENCY_EDGES = (
    ("manual.detailing.torsion.minimum-ratio", "manual.detailing.links.minimum-ratio"),
    ("manual.crack.2005.width", "manual.crack.2005.spacing"),
    ("manual.crack.2023.width", "manual.crack.2023.spacing"),
    (
        "manual.fatigue.reinforcement.life",
        "manual.fatigue.reinforcement.design-range",
    ),
    ("manual.fatigue.reinforcement.life", "manual.fatigue.stress-range"),
    (
        "manual.fatigue.reinforcement.miner",
        "manual.fatigue.reinforcement.life",
    ),
    ("manual.shear.links-2023", "manual.detailing.links.minimum-ratio"),
    ("manual.torsion.strut-interaction", "manual.torsion.resistance"),
    ("manual.torsion.strut-interaction", "manual.shear.links-2005"),
    ("manual.combined.strut-interaction", "manual.torsion.strut-interaction"),
)


def _validate_acyclic(keys: tuple[str, ...]) -> None:
    dependencies = {
        record.key: record.direct_uses for record in MANUAL_EQUATION_SEMANTICS
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise RuntimeError("Manual equation dependency graph contains a cycle.")
        if key in visited:
            return
        visiting.add(key)
        for dependency in dependencies[key]:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in keys:
        visit(key)


def _validate_catalogue() -> None:
    if type(MANUAL_EQUATION_SEMANTICS) is not tuple:
        raise RuntimeError("Manual equation semantics must retain tuple identity.")
    if len(MANUAL_EQUATION_SEMANTICS) != 32:
        raise RuntimeError("Expected exactly 32 manual equation semantics.")
    keys = tuple(item.key for item in MANUAL_EQUATION_SEMANTICS)
    if tuple(item.ordinal for item in MANUAL_EQUATION_SEMANTICS) != tuple(
        range(1, 33)
    ):
        raise RuntimeError("Manual equation semantic ordinals must be contiguous.")
    if len(set(keys)) != 32:
        raise RuntimeError("Manual equation semantic keys must be unique.")

    source_keys = tuple(item.key for item in MANUAL_EQUATION_SOURCES)
    for record, source in zip(
        MANUAL_EQUATION_SEMANTICS,
        MANUAL_EQUATION_SOURCES,
    ):
        if type(record) is not ManualEquationSemantics:
            raise RuntimeError("Manual equation semantics must retain exact type.")
        if (
            type(record.ordinal) is not int
            or type(record.key) is not str
            or type(record.number) is not str
            or type(record.symbols) is not tuple
            or type(record.dimensional_note) is not str
            or type(record.direct_uses) is not tuple
        ):
            raise RuntimeError(f"Semantic field type drifted at {source.number}.")
        if (record.ordinal, record.key, record.number) != (
            source.ordinal,
            source.key,
            source.number,
        ):
            raise RuntimeError(f"Semantic identity drifted at {source.number}.")
        if not record.symbols:
            raise RuntimeError(f"Equation {record.number} has no symbols.")
        symbol_names = []
        for symbol in record.symbols:
            if type(symbol) is not ManualEquationSymbol:
                raise RuntimeError(f"Symbol type drifted at {record.number}.")
            values = (symbol.markup, symbol.meaning, symbol.unit)
            if any(type(value) is not str for value in values):
                raise RuntimeError(f"Symbol field type drifted at {record.number}.")
            if any(not value.strip() or not value.isascii() for value in values):
                raise RuntimeError(f"Incomplete symbol at {record.number}.")
            if symbol.unit not in UNITS:
                raise RuntimeError(f"Unknown symbol unit at {record.number}.")
            symbol_names.append(symbol.markup)
        if len(symbol_names) != len(set(symbol_names)):
            raise RuntimeError(f"Duplicate symbol at {record.number}.")
        if (
            not record.dimensional_note.strip()
            or not record.dimensional_note.isascii()
        ):
            raise RuntimeError(f"Incomplete dimensional note at {record.number}.")
        if any(
            type(key) is not str or not key or not key.isascii()
            for key in record.direct_uses
        ):
            raise RuntimeError(f"Invalid dependency at {record.number}.")
        if len(record.direct_uses) != len(set(record.direct_uses)):
            raise RuntimeError(f"Duplicate dependency at {record.number}.")
        if record.key in record.direct_uses:
            raise RuntimeError(f"Self dependency at {record.number}.")
        if any(key not in source_keys for key in record.direct_uses):
            raise RuntimeError(f"Unknown dependency at {record.number}.")

    edges = tuple(
        (record.key, dependency)
        for record in MANUAL_EQUATION_SEMANTICS
        for dependency in record.direct_uses
    )
    if edges != DIRECT_DEPENDENCY_EDGES:
        raise RuntimeError("Manual equation dependency graph drifted.")
    _validate_acyclic(keys)


_validate_catalogue()


def bind_manual_equation_semantics(
    equations: tuple[SourcedManualEquation, ...],
    catalogue: tuple[
        ManualEquationSemantics, ...
    ] = MANUAL_EQUATION_SEMANTICS,
) -> tuple[SemanticManualEquation, ...]:
    """Bind canonical sourced expressions to the canonical semantic catalogue."""

    if type(equations) is not tuple:
        raise ValueError("Sourced manual equations must retain tuple identity.")
    if type(catalogue) is not tuple or catalogue != MANUAL_EQUATION_SEMANTICS:
        raise ValueError("Canonical manual equation semantic catalogue changed.")
    if len(equations) != 32:
        raise ValueError("Sourced manual equation cardinality changed.")
    if any(type(item) is not SourcedManualEquation for item in equations):
        raise ValueError("Sourced manual equation type changed.")

    for equation, source in zip(equations, MANUAL_EQUATION_SOURCES):
        candidate_source = equation.source
        if type(candidate_source) is not ManualEquationSource:
            raise ValueError(f"Sourced identity type changed at {source.number}.")
        candidate_fields = (
            candidate_source.ordinal,
            candidate_source.key,
            candidate_source.number,
            candidate_source.source_kind,
            candidate_source.source_text,
        )
        expected_fields = (
            source.ordinal,
            source.key,
            source.number,
            source.source_kind,
            source.source_text,
        )
        if type(candidate_fields[0]) is not int or any(
            type(value) is not str for value in candidate_fields[1:]
        ):
            raise ValueError(
                f"Sourced identity field type changed at {source.number}."
            )
        if candidate_fields != expected_fields:
            raise ValueError(f"Sourced identity changed at {source.number}.")

    rebound = bind_manual_equation_sources(
        tuple(item.equation for item in equations)
    )
    if equations != rebound:
        raise ValueError("Sourced manual equation identity changed.")

    bound = []
    for equation, semantics, source in zip(
        equations,
        MANUAL_EQUATION_SEMANTICS,
        MANUAL_EQUATION_SOURCES,
    ):
        if equation.source != source:
            raise ValueError(f"Sourced identity changed at {semantics.number}.")
        if (semantics.ordinal, semantics.key, semantics.number) != (
            source.ordinal,
            source.key,
            source.number,
        ):
            raise ValueError(f"Semantic identity changed at {semantics.number}.")
        bound.append(SemanticManualEquation(equation, semantics))
    return tuple(bound)


def semantic_catalogue_sha256() -> str:
    """Return one deterministic seal over every retained semantic field."""

    rows = []
    for item in MANUAL_EQUATION_SEMANTICS:
        symbols = "\x1c".join(
            "\x1d".join((symbol.markup, symbol.meaning, symbol.unit))
            for symbol in item.symbols
        )
        dependencies = "\x1b".join(item.direct_uses)
        rows.append(
            "\x1f".join(
                (
                    str(item.ordinal),
                    item.key,
                    item.number,
                    symbols,
                    item.dimensional_note,
                    dependencies,
                )
            )
        )
    return hashlib.sha256("\x1e".join(rows).encode("ascii")).hexdigest()
