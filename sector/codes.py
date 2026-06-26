"""Design-code presets that assemble the material laws for a chosen edition.

A design code fixes the partial safety factors and design coefficients (such as
``alpha_cc``) and builds the concrete and reinforcement laws, so the user selects
a code and a material grade rather than entering factors by hand. Selecting a
code is optional -- the materials can still be defined manually for full control.

Only the normal-strength concrete classes (up to C50/60) are offered for now,
where the design parabola-rectangle parameters are constant; higher classes,
along with further code editions, build on this same structure.
"""

from __future__ import annotations

from dataclasses import dataclass

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
        Coefficient on the design concrete compressive strength.
    eps_ud:
        Design strain limit for the reinforcement (fraction).
    """

    key: str
    label: str
    gamma_c: float
    gamma_s: float
    alpha_cc: float
    eps_ud: float

    def concrete(self, fck: float) -> Concrete:
        """Concrete law for characteristic strength ``fck`` (MPa) under this code."""
        return Concrete(fck=fck, gamma_c=self.gamma_c, curve=2,
                        alpha_cc=self.alpha_cc)

    def steel(self, fyk: float) -> MildSteel:
        """Reinforcement law for characteristic yield ``fyk`` (MPa) under this code.

        An idealised elastic-perfectly-plastic design law (horizontal top branch
        at the design yield), with the strain capped at the design limit
        ``eps_ud``.
        """
        return MildSteel(fytk=fyk, fyck=fyk, eut=self.eps_ud,
                         gamma_y=self.gamma_s, curve=2)


# EN 1992-1-1:2005, recommended values. For concrete up to C50/60 the design
# parabola-rectangle is exactly the curve the solver already uses. The steel
# strain limit is 0.9 * eps_uk for ductility class B (eps_uk = 5%).
EC2_2005 = DesignCode(
    key="EC2-2005",
    label="EN 1992-1-1:2005",
    gamma_c=1.5,
    gamma_s=1.15,
    alpha_cc=1.0,
    eps_ud=0.045,
)

# Registry of selectable codes, keyed by their display label.
CODES = {
    EC2_2005.label: EC2_2005,
}
