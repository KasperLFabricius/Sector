"""Material stress-strain laws for plastic (ultimate) section analysis.

These are the nonlinear laws the plastic analysis integrates over a section to
find its ultimate capacity. Each law maps a strain to a stress, with both the
characteristic curve and the design curve (the characteristic stress ordinate
divided by the relevant partial safety factor).

Conventions
-----------
* Strain and stress are **tension positive**. Concrete therefore carries stress
  only at negative (compressive) strain and nothing in tension; reinforcement
  carries both.
* Strains are fractions (0.0035, not 0.35 %); the manual states several limits
  in percent and those are converted on input where noted.
* Stresses are in MPa.

Currently implemented: concrete (types 1 and 2) and mild reinforcement (types 1
and 2). Mild steel type 3, and the prestressing-steel laws, are added with the
prestressing work.
"""

from __future__ import annotations

from dataclasses import dataclass

# Characteristic modulus of elasticity of reinforcement, MPa (Ek in the manual).
ES = 2.0e5

# Concrete strain limits (compression, magnitude): peak at 0.2 %, ultimate 0.35 %.
EPS_C_PEAK = 0.002
EPS_CU = 0.0035


@dataclass(frozen=True)
class Concrete:
    """Concrete in compression; tensile strength is taken as zero.

    Parameters
    ----------
    fck:
        Characteristic compressive strength, MPa.
    gamma_c:
        Partial safety factor for concrete (design = characteristic / gamma_c).
    curve:
        Stress-strain curve type, 1 or 2 (see the manual). Type 2 is the
        parabola-rectangle; type 1 a cubic ascending branch.
    """

    fck: float
    gamma_c: float = 1.0
    curve: int = 2

    def __post_init__(self) -> None:
        if self.curve not in (1, 2):
            raise ValueError("concrete curve must be 1 or 2")
        if self.fck <= 0:
            raise ValueError("fck must be positive")

    def _char_compressive(self, e_pct: float) -> float:
        """Characteristic compressive stress (MPa, >=0) at strain ``e_pct`` (%).

        ``e_pct`` is the compressive strain in percent, 0 <= e_pct <= 0.35.
        """
        fc = self.fck
        if e_pct < 0.0:
            return 0.0
        if e_pct >= EPS_C_PEAK * 100.0:  # 0.2 %
            if e_pct <= EPS_CU * 100.0 + 1e-12:  # plateau up to 0.35 %
                return fc
            return 0.0  # crushed beyond the ultimate strain
        if self.curve == 2:
            return 10.0 * e_pct * (1.0 - 2.5 * e_pct) * fc
        # curve == 1
        e0 = 51.0 * fc / (13.0 + fc)
        return (10.0 * e0 * e_pct
                + 100.0 * (0.75 * fc - e0) * e_pct ** 2
                + 250.0 * (e0 - fc) * e_pct ** 3)

    def stress(self, eps: float, *, design: bool = True) -> float:
        """Stress (MPa, tension positive) at tension-positive strain ``eps``.

        Concrete carries no tension, so this is zero for ``eps >= 0`` and a
        negative (compressive) value for ``eps < 0``.
        """
        if eps >= 0.0:
            return 0.0
        f = self._char_compressive(-eps * 100.0)
        if design:
            f /= self.gamma_c
        return -f

    @property
    def fcd(self) -> float:
        return self.fck / self.gamma_c


@dataclass(frozen=True)
class MildSteel:
    """Mild reinforcement, linear elastic then yielding (tension positive).

    Two curve types are supported:

    * **type 1** -- bilinear with strain hardening: elastic at slope
      ``ES/gamma_E`` to the design yield ``fytk/gamma_y``, then a hardening
      branch to ``futk/gamma_u`` at the rupture strain ``eut``. Compression is
      elastic to ``-fyck/gamma_y`` then a flat plateau (no hardening).
    * **type 2** -- elastic-perfectly-plastic: elastic at slope ``ES/gamma_y``
      to the design yield, then flat.

    Beyond the tensile rupture strain ``eut`` the bar is treated as fractured and
    carries no force (the plastic solver additionally limits the section strain
    profile so the governing failure -- concrete crushing or steel rupture --
    keeps the ultimate state within these limits).

    Parameters
    ----------
    fytk, fyck:
        Characteristic yield stress in tension / compression, MPa.
    eut:
        Rupture strain (fraction, e.g. 0.05 for 5 %). Used by type 1.
    futk:
        Characteristic rupture stress in tension, MPa. Used by type 1.
    gamma_y, gamma_u, gamma_E:
        Partial safety factors for yield, rupture and modulus.
    curve:
        1 or 2.
    """

    fytk: float
    fyck: float
    eut: float = 0.05
    futk: float = 0.0
    gamma_y: float = 1.0
    gamma_u: float = 1.0
    gamma_E: float = 1.0
    curve: int = 2

    def __post_init__(self) -> None:
        if self.curve not in (1, 2):
            raise ValueError("mild steel curve must be 1 or 2")
        if self.curve == 1 and self.futk <= 0:
            raise ValueError("type 1 needs a rupture stress futk > 0")

    def stress(self, eps: float, *, design: bool = True) -> float:
        """Stress (MPa, tension positive) at tension-positive strain ``eps``."""
        gy = self.gamma_y if design else 1.0
        gu = self.gamma_u if design else 1.0
        gE = self.gamma_E if design else 1.0

        fyt = self.fytk / gy   # design tensile yield
        fyc = self.fyck / gy   # design compressive yield (magnitude)

        if self.curve == 2:
            slope = ES / gy
            if eps >= 0.0:
                if eps > self.eut:
                    return 0.0  # ruptured: no force beyond the rupture strain
                return min(slope * eps, fyt)
            return max(slope * eps, -fyc)

        # type 1: hardening in tension, flat plateau in compression
        slope = ES / gE
        if eps >= 0.0:
            if eps > self.eut:
                return 0.0  # ruptured: no force beyond the rupture strain
            eps_y = fyt / slope
            if eps <= eps_y:
                return slope * eps
            fu = self.futk / gu
            # Hardening branch, reaching the design rupture stress at eut.
            return fyt + (fu - fyt) * (eps - eps_y) / (self.eut - eps_y)
        eps_yc = -fyc / slope
        if eps >= eps_yc:
            return slope * eps
        return -fyc
