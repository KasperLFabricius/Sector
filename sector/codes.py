"""Design-code presets that assemble the material laws for a chosen edition.

A design code fixes the partial safety factors and design coefficients and builds
the concrete and reinforcement laws, so the user selects a code and a material
grade rather than entering factors by hand. Selecting a code is optional -- the
materials can still be defined manually for full control.

Concrete (ULS)
    All editions use the parabola-rectangle design diagram
    ``sigma = fcd * [1 - (1 - eps/eps_c2)^n]`` up to ``eps_c2``, then a plateau at
    ``fcd`` to the ultimate strain ``eps_cu``. For the normal-strength classes
    offered here (up to C50/60) ``eps_c2 = 0.2%``, ``eps_cu = 0.35%`` and ``n = 2``
    in every edition, which is exactly the curve the solver is verified against;
    the editions differ only in the design strength ``fcd``:

    * EN 1992-1-1:2005 and the DK NA: ``fcd = alpha_cc * fck / gamma_c`` with
      ``alpha_cc = 1.0``.
    * EN 1992-1-1:2023: ``fcd = eta_cc * k_tc * fck / gamma_c`` with the
      strength-dependent ``eta_cc = (fck_ref / fck)^(1/3) <= 1`` (``fck_ref =
      40 MPa``) and the sustained-load factor ``k_tc = 1.0``. The 2023 ultimate
      parabola keeps constant strains for all classes, so this maps onto the same
      ``alpha_cc`` coefficient.

Reinforcement (ULS)
    The design diagram with a horizontal top branch at ``fyd = fyk / gamma_s`` and
    no strain limit -- option (b) of the reinforcement design assumptions, which
    the DK NA mandates -- i.e. an elastic-perfectly-plastic law. The elastic
    modulus is left un-factored at ``Es`` (the code reduces the yield stress, not
    the modulus), so bars below yield carry their correct ``Es * eps`` force.

Partial factors are the recommended / national values for the persistent and
transient design situation. The Danish factors are the normal control-class
values (the national consequence/control factor ``gamma_3 = 1.0``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .materials import Concrete, MildSteel

# Concrete strength classes -> characteristic cylinder strength fck (MPa).
CONCRETE_CLASSES = {
    "C12/15": 12.0,
    "C16/20": 16.0,
    "C20/25": 20.0,
    "C25/30": 25.0,
    "C30/37": 30.0,
    "C35/45": 35.0,
    "C40/50": 40.0,
    "C45/55": 45.0,
    "C50/60": 50.0,
}

# Reinforcement grades -> characteristic yield strength fyk (MPa).
STEEL_GRADES = {
    "B500": 500.0,
    "B550": 550.0,
}

# A horizontal-branch reinforcement law has no strain limit; this stand-in
# rupture strain is far beyond any attainable section strain, so the concrete
# crushing strain always governs (matching design option (b)).
_NO_STRAIN_LIMIT = 1.0


def fctm(fck: float) -> float:
    """Mean axial tensile strength ``f_ctm`` (MPa), EC2 Table 3.1.

    ``f_ctm = 0.30 * fck^(2/3)`` up to C50/60; above that
    ``f_ctm = 2.12 * ln(1 + fcm/10)`` with the mean strength ``fcm = fck + 8``.
    This is the strength used for the serviceability cracking check
    (``fct,eff = fctm`` when cracking is expected at >= 28 days).
    """
    if fck <= 50.0:
        return 0.30 * fck ** (2.0 / 3.0)
    return 2.12 * math.log(1.0 + (fck + 8.0) / 10.0)


def eps_c2(fck: float) -> float:
    """Strain at peak concrete stress ``eps_c2`` (fraction), EC2 Table 3.1.

    ``0.2%`` up to C50/60; above that the strength-dependent
    ``2.0 + 0.085*(fck-50)^0.53`` (per mille).
    """
    if fck <= 50.0:
        return 0.002
    return (2.0 + 0.085 * (fck - 50.0) ** 0.53) / 1000.0


def eps_cu2(fck: float) -> float:
    """Ultimate concrete strain ``eps_cu2`` (fraction), EC2 Table 3.1.

    ``0.35%`` up to C50/60; above that ``2.6 + 35*((90-fck)/100)^4`` (per mille).
    """
    if fck <= 50.0:
        return 0.0035
    return (2.6 + 35.0 * ((90.0 - fck) / 100.0) ** 4) / 1000.0


def n_exponent(fck: float) -> float:
    """Parabola-rectangle exponent ``n``, EC2 Table 3.1.

    ``2.0`` up to C50/60; above that ``1.4 + 23.4*((90-fck)/100)^4``.
    """
    if fck <= 50.0:
        return 2.0
    return 1.4 + 23.4 * ((90.0 - fck) / 100.0) ** 4


def ecm(fck: float) -> float:
    """Secant modulus of elasticity ``E_cm`` (MPa), EC2 Table 3.1.

    ``E_cm = 22000 * (fcm/10)^0.3`` with ``fcm = fck + 8`` (quartzite
    aggregate). Used to form the serviceability modular ratio
    ``alpha_e = Es / E_cm`` when a default is wanted; the analysis itself takes
    the modular ratio per load so creep can be carried explicitly.
    """
    return 22000.0 * ((fck + 8.0) / 10.0) ** 0.3


@dataclass(frozen=True)
class DesignCode:
    """A set of code-defined material parameters.

    Parameters
    ----------
    key, label:
        Short identifier and the human-readable code designation shown in the UI.
    gamma_c, gamma_s:
        Partial safety factors for concrete and reinforcement.
    alpha_cc:
        Constant coefficient on the design concrete strength (editions that use a
        fixed ``alpha_cc``).
    eta_cc_ref:
        If set, the design strength uses the strength-dependent factor
        ``eta_cc = (eta_cc_ref / fck)^(1/3) <= 1`` instead of ``alpha_cc``
        (EN 1992-1-1:2023, with ``eta_cc_ref = 40 MPa``).
    k_tc:
        Sustained-load / time factor on the design concrete strength (2023).
    const_strains:
        Keep the ultimate parabola strains (``eps_c2 = 0.2%``, ``eps_cu2 = 0.35%``,
        ``n = 2``) constant for every class instead of the EC2 Table 3.1
        strength-dependent values. EN 1992-1-1:2023 keeps them constant.
    """

    key: str
    label: str
    gamma_c: float
    gamma_s: float
    alpha_cc: float = 1.0
    eta_cc_ref: Optional[float] = None
    k_tc: float = 1.0
    const_strains: bool = False
    # Shear (EN 1992-1-1:2005 sec. 6.2.2 members without shear reinforcement). The
    # ``shear_model`` selects the resistance formula; "2005" is the variable-strut
    # family (2005 + DK NA), "2023" the strain-based sec. 8.2 (added later). CRd,c and
    # k1 are the recommended values (the DK NA keeps them); the DK NA changes only
    # v_min: the recommended v_min = 0.035*k^1.5*sqrt(fck), the DK NA:2024
    # v_min = (0.051/gamma_c)*k^1.5*sqrt(fck), selected by ``shear_vmin_over_gamma_c``.
    shear_model: str = "2005"
    shear_crd_c: float = 0.18
    shear_k1: float = 0.15
    shear_vmin_coeff: float = 0.035
    shear_vmin_over_gamma_c: bool = False
    # Shear WITH links (sec. 6.2.3, variable strut inclination). ``nu1`` is the
    # strength reduction factor for concrete cracked in shear used in VRd,max: the
    # recommended nu = 0.6*(1 - fck/250), or -- when ``shear_nu_v`` is set (the
    # DK NA:2024 plasticity pure-shear factor nu_v, 5.103 NA, applied to the truss
    # struts by 5.101 NA) -- nu_v = 0.7 - fck/200 >= 0.45. The strut angle is bounded
    # by cot(theta) in [shear_cot_min_limit, shear_cot_max_limit] (6.7N / 6.7a NA,
    # both 1..2.5); the user may widen these (with a warning) per the roadmap.
    shear_nu_v: bool = False
    shear_cot_min_limit: float = 1.0
    shear_cot_max_limit: float = 2.5
    # EN 1992-1-1:2023 sec. 8.2.2 (strain-based, members without shear reinforcement):
    # tau_Rd,c = (0.66/gamma_v)*(100*rho_l*fck*ddg/d)^(1/3) >= tau_Rd,c,min (8.27),
    # tau_Rd,c,min = (11/gamma_v)*sqrt(fck/fyd*ddg/d) (8.20). gamma_v is the shear
    # partial factor (Table 4.3: 1.40 recommended); ddg the aggregate size parameter.
    shear_gamma_v: float = 1.40

    def shear_ddg(self, fck: float, d_lower_mm: float) -> float:
        """Aggregate size parameter ``ddg`` (mm), sec. 8.2.1(4).

        ``ddg = 16 + Dlower`` (<= 40 mm) for ``fck <= 60``; above C60 the aggregate
        term is scaled by ``(60/fck)^2``. ``Dlower`` is the lower sieve size of the
        coarsest aggregate fraction (~16-32 mm), or ``Dmax`` when known.
        """
        term = d_lower_mm if fck <= 60.0 else d_lower_mm * (60.0 / fck) ** 2
        return min(16.0 + term, 40.0)

    def shear_crd_c_over_gamma(self) -> float:
        """``C_Rd,c = 0.18 / gamma_c`` -- the VRd,c coefficient (2005 sec. 6.2.2(1))."""
        return self.shear_crd_c / self.gamma_c

    def shear_nu1(self, fck: float) -> float:
        """Strength reduction factor ``nu1`` for concrete cracked in shear (VRd,max).

        Recommended ``nu = 0.6*(1 - fck/250)`` (6.6N); the DK NA:2024 uses its
        plasticity pure-shear effectiveness factor ``nu_v = 0.7 - fck/200 >= 0.45``
        (5.103 NA), which 5.101 NA applies to the truss compression struts.
        """
        if self.shear_nu_v:
            return max(0.7 - fck / 200.0, 0.45)
        return 0.6 * (1.0 - fck / 250.0)

    def torsion_nu(self, fck: float) -> float:
        """Concrete-strut effectiveness factor ``nu`` for torsion (TRd,max, 6.30).

        Recommended ``nu = 0.6*(1 - fck/250)`` (via 6.2.2(6)); the DK NA:2024 uses its
        plasticity pure-torsion factor ``nu_t = 0.7*(0.7 - fck/200)`` (5.104 NA), a
        further 0.7 reduction on the pure-shear expression for the circulatory shear
        flow of torsion. The 0.45 lower bound of 5.103 NA belongs to ``nu_v`` ONLY --
        5.104 NA states no floor for ``nu_t``, so above C50 it keeps falling
        (C60: 0.28, not the floored 0.7*0.45 = 0.315, which is unconservative).
        """
        if self.shear_nu_v:
            return max(0.7 * (0.7 - fck / 200.0), 0.0)   # 5.104 NA (no nu_v floor)
        return 0.6 * (1.0 - fck / 250.0)

    def shear_alpha_cw(self, sigma_cp: float, fcd: float) -> float:
        """Compression-chord coefficient ``alpha_cw`` (6.11N).

        ``sigma_cp`` is the mean concrete compressive stress (compression positive):
        1 for a non-prestressed / tensile section, rising to 1.25 then falling to 0 as
        ``sigma_cp`` approaches ``fcd`` (the strut is already near crushing).
        """
        if fcd <= 0.0 or sigma_cp <= 0.0:
            return 1.0
        r = sigma_cp / fcd
        if r <= 0.25:
            return 1.0 + r
        if r <= 0.5:
            return 1.25
        if r < 1.0:
            return 2.5 * (1.0 - r)
        return 0.0

    def shear_vmin(self, k: float, fck: float) -> float:
        """``v_min`` (MPa) for shear resistance without links, sec. 6.2.2(1).

        Recommended ``0.035*k^1.5*sqrt(fck)``; the DK NA:2024 uses
        ``(0.051/gamma_c)*k^1.5*sqrt(fck)`` (``shear_vmin_over_gamma_c``).
        """
        coeff = self.shear_vmin_coeff
        if self.shear_vmin_over_gamma_c:
            coeff = coeff / self.gamma_c
        return coeff * k ** 1.5 * math.sqrt(fck)

    def concrete_factor(self, fck: float) -> float:
        """Effective coefficient on the design concrete strength for ``fck``."""
        if self.eta_cc_ref is not None:
            eta_cc = min((self.eta_cc_ref / fck) ** (1.0 / 3.0), 1.0)
            return eta_cc * self.k_tc
        return self.alpha_cc

    def strain_law(self, fck: float) -> tuple[float, float, float]:
        """``(eps_c2, eps_cu2, n)`` (fractions) for ``fck`` under this edition.

        Constant ``0.2%``/``0.35%``/``2`` when the edition keeps constant strains
        (``const_strains``, EN 1992-1-1:2023); otherwise the EC2 Table 3.1 values,
        which are strength-dependent above C50/60.
        """
        if self.const_strains:
            return 0.002, 0.0035, 2.0
        return eps_c2(fck), eps_cu2(fck), n_exponent(fck)

    def concrete(self, fck: float) -> Concrete:
        """Concrete law for characteristic strength ``fck`` (MPa) under this code.

        Unless the edition keeps constant strains (``const_strains``), the strain
        limits and parabola exponent follow EC2 Table 3.1, so a class above C50/60
        gets its strength-dependent ``eps_c2``/``eps_cu2``/``n`` automatically
        (constant ``0.2%``/``0.35%``/``2`` up to C50/60).
        """
        e_c2, e_cu2, n = self.strain_law(fck)
        return Concrete(fck=fck, gamma_c=self.gamma_c, curve=2,
                        alpha_cc=self.concrete_factor(fck),
                        eps_c2=e_c2, eps_cu2=e_cu2, n=n)

    def steel(self, fyk: float) -> MildSteel:
        """Reinforcement law for characteristic yield ``fyk`` (MPa) under this code.

        EC2's design diagram: a horizontal top branch at the design yield
        ``fyd = fyk / gamma_s`` with no strain limit (design option (b)). The
        code reduces the yield stress but keeps the elastic modulus, so ``Es`` is
        left un-factored. This is built with curve 1 -- ``gamma_E = 1`` (un-
        factored modulus) and a flat post-yield branch (``futk = fyk``,
        ``gamma_u = gamma_s``) -- i.e. elastic-perfectly-plastic with the full
        modulus on the elastic branch.
        """
        return MildSteel(fytk=fyk, fyck=fyk, futk=fyk, eut=_NO_STRAIN_LIMIT,
                         gamma_y=self.gamma_s, gamma_u=self.gamma_s,
                         gamma_E=1.0, curve=1)


# EN 1992-1-1:2005, recommended values (alpha_cc = 1.0, gamma_c = 1.5,
# gamma_s = 1.15). For concrete up to C50/60 the design parabola-rectangle is
# exactly the curve the solver already uses.
EC2_2005 = DesignCode(
    key="EC2-2005",
    label="EN 1992-1-1:2005",
    gamma_c=1.5,
    gamma_s=1.15,
    alpha_cc=1.0,
)

# DS/EN 1992-1-1:2005 with the Danish National Annex (2024): in-situ reinforced
# concrete at normal control class (gamma_3 = 1.0). The NA does not change
# alpha_cc and mandates the horizontal reinforcement branch.
EC2_2005_DKNA = DesignCode(
    key="EC2-2005-DKNA2024",
    label="DS/EN 1992-1-1:2005 + DK NA:2024",
    gamma_c=1.45,
    gamma_s=1.20,
    alpha_cc=1.0,
    # DK NA:2024 sec. 6.2.2(1): v_min = (0.051/gamma_c)*k^1.5*sqrt(fck).
    shear_vmin_coeff=0.051,
    shear_vmin_over_gamma_c=True,
    # DK NA:2024 sec. 6.2.3(3): the truss strut effectiveness factor is the plasticity
    # pure-shear factor nu_v = 0.7 - fck/200 >= 0.45 (5.103 NA), not the recommended nu.
    shear_nu_v=True,
)

# DS/EN 1992-1-1:2023: gamma_c = 1.5, gamma_s = 1.15, with the strength-dependent
# design-strength factor eta_cc = (40/fck)^(1/3) <= 1 and k_tc = 1.0. The
# ultimate parabola keeps constant strains for all classes.
EC2_2023 = DesignCode(
    key="EC2-2023",
    label="DS/EN 1992-1-1:2023",
    gamma_c=1.5,
    gamma_s=1.15,
    eta_cc_ref=40.0,
    k_tc=1.0,
    const_strains=True,   # the 2023 ultimate parabola keeps constant strains
    shear_model="2023",   # strain-based sec. 8.2 (implemented later)
)

# Registry of selectable codes, keyed by their display label.
CODES = {
    EC2_2005.label: EC2_2005,
    EC2_2005_DKNA.label: EC2_2005_DKNA,
    EC2_2023.label: EC2_2023,
}
