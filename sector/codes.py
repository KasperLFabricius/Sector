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
    """

    key: str
    label: str
    gamma_c: float
    gamma_s: float
    alpha_cc: float = 1.0
    eta_cc_ref: Optional[float] = None
    k_tc: float = 1.0

    def concrete_factor(self, fck: float) -> float:
        """Effective coefficient on the design concrete strength for ``fck``."""
        if self.eta_cc_ref is not None:
            eta_cc = min((self.eta_cc_ref / fck) ** (1.0 / 3.0), 1.0)
            return eta_cc * self.k_tc
        return self.alpha_cc

    def concrete(self, fck: float) -> Concrete:
        """Concrete law for characteristic strength ``fck`` (MPa) under this code."""
        return Concrete(fck=fck, gamma_c=self.gamma_c, curve=2,
                        alpha_cc=self.concrete_factor(fck))

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
)

# Registry of selectable codes, keyed by their display label.
CODES = {
    EC2_2005.label: EC2_2005,
    EC2_2005_DKNA.label: EC2_2005_DKNA,
    EC2_2023.label: EC2_2023,
}
