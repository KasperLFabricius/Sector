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

Implemented: concrete (types 1 and 2), mild reinforcement (types 1-3) and
prestressing steel (types 1-7) -- the full set of laws from the manual.
"""

from __future__ import annotations

from dataclasses import dataclass

# Characteristic modulus of elasticity of reinforcement, MPa (Ek in the manual).
ES = 2.0e5

def _trilinear_tension(eps, slope, f1, f2, fu, ey0t, eut):
    """Two-yield-point (trilinear) tensile stress at strain ``eps`` (>= 0).

    Shared by the two-yield-point laws (mild steel type 3 and prestress type 7):

    * elastic at ``slope`` to the first yield stress ``f1`` (at ``f1/slope``);
    * a second branch to the second yield stress ``f2``, whose *plastic* strain
      is ``ey0t`` -- i.e. the second yield point is at ``ey0t + f2/slope`` (its
      elastic unloading line returns to ``ey0t``);
    * a hardening branch to the rupture stress ``fu`` at the rupture strain
      ``eut``; beyond ``eut`` the bar has fractured and carries nothing.
    """
    if eps > eut:
        return 0.0
    e1 = f1 / slope
    if eps <= e1:
        return slope * eps
    e2 = ey0t + f2 / slope
    if eps <= e2:
        return f1 + (f2 - f1) * (eps - e1) / (e2 - e1)
    if eut <= e2:
        return f2  # degenerate: no room for a hardening branch
    return f2 + (fu - f2) * (eps - e2) / (eut - e2)


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
    * **type 3** -- two yield points (trilinear): elastic to the first yield
      ``k*fytk``, then to the second yield ``fytk`` (whose plastic strain is
      ``ey0t``), then hardening to ``futk`` at ``eut``. Compression mirrors it,
      with the second yield at the compression strain ``ey0c`` (type 3 uses
      ``fytk`` for both senses, so ``fyck`` is ignored).

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
    k:
        Ratio of the first to the second yield stress (``f1/fytk``, ``<= 1``).
        Type 3 only.
    ey0t, ey0c:
        The second yield point's plastic strain in tension and its total strain
        in compression (fractions). Type 3 only.
    curve:
        1, 2 or 3.
    """

    fytk: float
    fyck: float
    eut: float = 0.05
    futk: float = 0.0
    gamma_y: float = 1.0
    gamma_u: float = 1.0
    gamma_E: float = 1.0
    curve: int = 2
    k: float = 1.0
    ey0t: float = 0.0
    ey0c: float = 0.0

    def __post_init__(self) -> None:
        if self.curve not in (1, 2, 3):
            raise ValueError("mild steel curve must be 1, 2 or 3")
        if self.curve in (1, 3) and self.futk <= 0:
            raise ValueError("types 1 and 3 need a rupture stress futk > 0")

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

        if self.curve == 3:
            # Two yield points; type 3 uses fytk in both senses.
            slope = ES / gE
            f1 = self.k * fyt          # first yield stress
            f2 = fyt                   # second yield stress
            fu = self.futk / gu
            if eps >= 0.0:
                return _trilinear_tension(eps, slope, f1, f2, fu, self.ey0t, self.eut)
            # Compression mirror, second yield at the total strain ey0c. Steel
            # does not fracture in compression, so it holds -fu beyond eut.
            a = -eps
            e1 = f1 / slope
            if a <= e1:
                return -slope * a
            if a <= self.ey0c:
                span = self.ey0c - e1
                return -(f1 + (f2 - f1) * (a - e1) / span) if span > 0 else -f2
            if self.ey0c < a < self.eut and self.eut > self.ey0c:
                return -(f2 + (fu - f2) * (a - self.ey0c) / (self.eut - self.ey0c))
            return -fu

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


# Rupture strain of the built-in prestressing curves (fraction): 3.5 %.
EPS_P_RES = 0.035


@dataclass(frozen=True)
class Prestress:
    """Prestressing steel; carries tension only.

    Six curve types are supported:

    * **types 1-5** -- the program's built-in characteristic curves, fixed
      polynomials of the tendon strain (in percent) up to the 3.5 % rupture
      strain. Only the initial strain and the partial factor are user input.
    * **type 6** -- a user-defined bilinear curve with hardening: elastic at
      slope ``ES/gamma_E`` to ``fytk/gamma_y``, then a hardening branch to
      ``futk/gamma_u`` at the rupture strain ``eut``.
    * **type 7** -- a user-defined two-yield-point curve: the same trilinear
      tensile law as mild steel type 3 (first yield ``k*fytk``, second yield
      ``fytk`` at plastic strain ``ey0t``, hardening to ``futk`` at ``eut``).

    A tendon takes no compression: the stress is zero for any strain at or below
    zero, and zero beyond the rupture strain (the tendon has fractured).

    Note ``stress`` takes the *total* tendon strain (the effective prestrain
    ``IS`` plus the strain at the tendon from the section's deformation); the
    solver forms that total. ``IS`` is stored here (fraction) for the solver.

    Parameters
    ----------
    curve:
        1-6.
    IS:
        Initial (effective) prestrain, fraction (e.g. 0.0059 for 0.59 %).
    gamma_y, gamma_u, gamma_E:
        Partial safety factors.
    fytk, eut, futk:
        Yield stress (MPa), rupture strain (fraction) and rupture stress (MPa);
        used by types 6 and 7.
    k, ey0t:
        First-to-second yield-stress ratio and the second yield point's plastic
        strain; type 7 only.
    """

    curve: int = 1
    IS: float = 0.0
    gamma_y: float = 1.0
    gamma_u: float = 1.0
    gamma_E: float = 1.0
    fytk: float = 0.0
    eut: float = EPS_P_RES
    futk: float = 0.0
    k: float = 1.0
    ey0t: float = 0.0

    def __post_init__(self) -> None:
        if self.curve not in (1, 2, 3, 4, 5, 6, 7):
            raise ValueError("prestress curve must be 1-7")
        if self.curve in (6, 7) and (self.fytk <= 0 or self.futk <= 0):
            raise ValueError("types 6 and 7 need fytk and futk > 0")

    @property
    def rupture_strain(self) -> float:
        """Effective tensile rupture strain (fraction).

        The built-in curves (1-5) rupture at the fixed ``EPS_P_RES`` regardless
        of the ``eut`` field; only the user-defined curves (6, 7) use ``eut``.
        """
        return self.eut if self.curve in (6, 7) else EPS_P_RES

    @staticmethod
    def _builtin_char(curve: int, e: float) -> float:
        """Characteristic stress (MPa) of a built-in curve at strain ``e`` (%)."""
        if curve == 1:
            if e < 0.6:
                return 2000.0 * e
            if e < 1.0:
                return -2500.0 * e ** 2 + 5000.0 * e - 900.0
            if e < 1.75:
                return 60.0 * e + 1540.0
            return 1645.0
        if curve == 2:
            if e < 0.7:
                return 1850.0 * e
            if e < 1.0:
                return 2743.0 * e ** 3 - 9932.0 * e ** 2 + 11724.0 * e - 2986.0
            return 1462.0 + 86.0 * e
        if curve == 3:
            if e < 0.7:
                return 1850.0 * e
            if e < 1.0:
                return 2037.0 * e ** 3 - 8137.0 * e ** 2 + 10247.0 * e - 2590.0
            return 1473.0 + 85.0 * e
        if curve == 4:
            if e < 0.6:
                return 1950.0 * e
            if e < 1.0:
                return 2286.0 * e ** 3 - 7783.0 * e ** 2 + 8825.0 * e - 1816.0
            return 1403.0 + 105.0 * e
        # curve == 5
        if e < 0.6:
            return 1950.0 * e
        if e < 1.0:
            return 2378.0 * e ** 3 - 8014.0 * e ** 2 + 8998.0 * e - 1857.0
        return 1399.0 + 106.0 * e

    def stress(self, eps: float, *, design: bool = True) -> float:
        """Stress (MPa, tension positive) at *total* tendon strain ``eps``.

        Zero in compression (``eps <= 0``) and beyond rupture.
        """
        if eps <= 0.0:
            return 0.0

        if self.curve == 6:
            if eps > self.eut:
                return 0.0  # fractured
            gy = self.gamma_y if design else 1.0
            gu = self.gamma_u if design else 1.0
            gE = self.gamma_E if design else 1.0
            slope = ES / gE
            fyt = self.fytk / gy
            eps_y = fyt / slope
            if eps <= eps_y:
                return slope * eps
            fu = self.futk / gu
            return fyt + (fu - fyt) * (eps - eps_y) / (self.eut - eps_y)

        if self.curve == 7:
            gy = self.gamma_y if design else 1.0
            gu = self.gamma_u if design else 1.0
            gE = self.gamma_E if design else 1.0
            slope = ES / gE
            return _trilinear_tension(eps, slope, self.k * self.fytk / gy,
                                      self.fytk / gy, self.futk / gu,
                                      self.ey0t, self.eut)

        # built-in curves 1-5
        if eps > EPS_P_RES:  # == self.rupture_strain for these curves
            return 0.0  # fractured beyond the rupture strain
        f = self._builtin_char(self.curve, eps * 100.0)
        if design:
            f /= self.gamma_y
        return f
