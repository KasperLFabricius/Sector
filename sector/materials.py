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
    alpha_cc:
        Coefficient on the design compressive strength accounting for long-term
        and unfavourable loading effects, so the design strength is
        ``alpha_cc * fck / gamma_c``. Defaults to 1.0 (no reduction).
    """

    fck: float
    gamma_c: float = 1.0
    curve: int = 2
    alpha_cc: float = 1.0
    eps_c2: float = EPS_C_PEAK   # strain at peak stress (parabola apex), fraction
    eps_cu2: float = EPS_CU      # ultimate (crushing) strain, fraction
    n: float = 2.0              # parabola-rectangle exponent

    def __post_init__(self) -> None:
        if self.curve not in (1, 2):
            raise ValueError("concrete curve must be 1 or 2")
        if self.fck <= 0:
            raise ValueError("fck must be positive")
        if self.alpha_cc <= 0:
            raise ValueError("alpha_cc must be positive")
        if self.eps_c2 <= 0.0 or self.eps_cu2 < self.eps_c2:
            raise ValueError("need 0 < eps_c2 <= eps_cu2")
        if self.n <= 0.0:
            raise ValueError("parabola exponent n must be positive")

    def _char_compressive(self, e_pct: float) -> float:
        """Characteristic compressive stress (MPa, >=0) at strain ``e_pct`` (%).

        ``e_pct`` is the compressive strain in percent. The parabola-rectangle
        (curve 2) rises as ``fck * [1 - (1 - eps/eps_c2)^n]`` to the peak at
        ``eps_c2``, then holds ``fck`` to the ultimate strain ``eps_cu2``; making
        ``eps_c2``, ``eps_cu2`` and ``n`` parameters covers the strength-dependent
        values EC2 Table 3.1 gives for concrete above C50/60. Curve 1 is the
        program's fixed cubic, defined for the normal-strength peak at 0.2 %.
        """
        fc = self.fck
        if e_pct < 0.0:
            return 0.0
        peak_pct = self.eps_c2 * 100.0
        if e_pct >= peak_pct:
            if e_pct <= self.eps_cu2 * 100.0 + 1e-12:  # plateau up to eps_cu2
                return fc
            return 0.0  # crushed beyond the ultimate strain
        if self.curve == 2:
            r = e_pct / peak_pct                       # eps / eps_c2
            return fc * (1.0 - (1.0 - r) ** self.n)
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
            f = f * self.alpha_cc / self.gamma_c
        return -f

    @property
    def fcd(self) -> float:
        return self.alpha_cc * self.fck / self.gamma_c

    def diagram_markers(self, *, design: bool = True):
        """Points of interest for a stress-strain plot.

        Returns ``(strain, stress, eps_key, sigma_key)`` points to label. Strains
        are fractions (compression negative); stresses MPa. ``eps_key`` /
        ``sigma_key`` are ASCII identifiers the UI maps to symbols; either may be
        ``None`` when that coordinate is not a distinct value to label here.
        """
        peak = self.stress(-self.eps_c2, design=design)  # compression (negative)
        fkey = "fcd" if design else "fck"
        return [
            (-self.eps_c2, peak, "eps_c2", fkey),
            (-self.eps_cu2, peak, "eps_cu2", None),  # same stress level as eps_c2
        ]


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
      ``ey0t``), then hardening to ``futk`` at ``eut``. Compression mirrors it
      symmetrically: the second yield ``fyck`` has plastic strain ``ey0c`` (its
      total strain is ``ey0c + fyck/slope``), then it hardens to ``futk`` at
      ``eut``. Both offsets are zero for a single yield point.

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
        The second yield point's plastic strain in tension and in compression
        (fractions); 0 collapses it onto the first yield. Type 3 only.
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
    Es: float = ES   # elastic (strain) modulus, MPa
    active_in_compression: bool = True   # False -> tension-only (no compression)

    def __post_init__(self) -> None:
        if self.curve not in (1, 2, 3):
            raise ValueError("mild steel curve must be 1, 2 or 3")
        if self.curve in (1, 3) and self.futk <= 0:
            raise ValueError("types 1 and 3 need a rupture stress futk > 0")

    def stress(self, eps: float, *, design: bool = True) -> float:
        """Stress (MPa, tension positive) at tension-positive strain ``eps``."""
        if not self.active_in_compression and eps < 0.0:
            return 0.0          # tension-only reinforcement carries no compression
        gy = self.gamma_y if design else 1.0
        gu = self.gamma_u if design else 1.0
        gE = self.gamma_E if design else 1.0

        fyt = self.fytk / gy   # design tensile yield
        fyc = self.fyck / gy   # design compressive yield (magnitude)

        if self.curve == 2:
            slope = self.Es / gy
            if eps >= 0.0:
                if eps > self.eut:
                    return 0.0  # ruptured: no force beyond the rupture strain
                return min(slope * eps, fyt)
            if -eps > self.eut:
                return 0.0  # rupture is symmetric: also fractures in compression
            return max(slope * eps, -fyc)

        if self.curve == 3:
            # Two yield points: tension uses fytk, compression uses fyck (so the
            # compression yield is an independent input).
            slope = self.Es / gE
            f1 = self.k * fyt          # first tensile yield stress
            f2 = fyt                   # second tensile yield stress
            fu = self.futk / gu
            if eps >= 0.0:
                return _trilinear_tension(eps, slope, f1, f2, fu, self.ey0t, self.eut)
            if fyc <= 0.0:
                return 0.0       # fyck = 0: no compression capacity
            # Compression mirror of the tension law: the second yield fyck sits at
            # the *plastic* offset ey0c, i.e. at the total strain ey0c + fyck/slope
            # (symmetric with the tensile ey0t), and the rupture is symmetric too --
            # the bar fractures past eut in compression as in tension.
            a = -eps
            if a > self.eut:
                return 0.0
            f1c = self.k * fyc         # first compressive yield stress
            e1 = f1c / slope
            e2c = self.ey0c + fyc / slope   # total strain of the second yield
            if a <= e1:
                return -slope * a
            if a <= e2c:
                span = e2c - e1
                return -(f1c + (fyc - f1c) * (a - e1) / span) if span > 0 else -fyc
            if e2c < a < self.eut and self.eut > e2c:
                return -(fyc + (fu - fyc) * (a - e2c) / (self.eut - e2c))
            return -fu

        # type 1: hardening in tension, plateau in compression; rupture is symmetric
        slope = self.Es / gE
        if eps >= 0.0:
            if eps > self.eut:
                return 0.0  # ruptured: no force beyond the rupture strain
            eps_y = fyt / slope
            if eps <= eps_y:
                return slope * eps
            fu = self.futk / gu
            # Hardening branch, reaching the design rupture stress at eut.
            return fyt + (fu - fyt) * (eps - eps_y) / (self.eut - eps_y)
        if -eps > self.eut:
            return 0.0  # rupture is symmetric: also fractures in compression
        eps_yc = -fyc / slope
        if eps >= eps_yc:
            return slope * eps
        return -fyc

    def elastic_slope(self, *, design: bool = True) -> float:
        """Slope of the elastic branch (MPa per unit strain).

        The design modulus carries its own partial factor: ``ES / gamma_E`` for
        the hardening / two-yield curves and ``ES / gamma_y`` for the elastic-
        perfectly-plastic curve (which ties the modulus to the yield factor). So
        the design slope differs from the characteristic one when a partial
        factor on the modulus is applied.
        """
        g = self.gamma_y if self.curve == 2 else self.gamma_E
        return self.Es / (g if design else 1.0)

    def diagram_markers(self, *, design: bool = True):
        """Labelled points of interest; the compression-side markers are dropped
        when the bar is tension-only (``active_in_compression`` is False)."""
        pts = self._markers(design=design)
        # The law ruptures symmetrically, so mark the compression rupture at -eut
        # too (parity with the tension-side eut marker); the stress there is the
        # compression value just before the drop. Filtered out below when the bar
        # is tension-only.
        pts = pts + [(-self.eut, self.stress(-self.eut, design=design), "eut", None)]
        if not self.active_in_compression:
            pts = [m for m in pts if m[0] >= 0.0]
        return pts

    def _markers(self, *, design: bool = True):
        """Points of interest labelled with the *input* parameters.

        Returns ``(strain, stress, eps_key, sigma_key)`` points (see
        :meth:`Concrete.diagram_markers`) keyed by the inputs the user enters --
        the yield (``fytk``) and rupture (``futk``) stresses, the compression
        yield (``fyck``), the rupture and second-yield strains (``eut``,
        ``ey0t``, ``ey0c``) and the first-yield level ``k*fytk`` -- so editing
        any input visibly moves a labelled point. Partial factors are not shown.
        """
        gy = self.gamma_y if design else 1.0
        gE = self.gamma_E if design else 1.0
        gu = self.gamma_u if design else 1.0
        fyt = self.fytk / gy
        fyc = self.fyck / gy

        if self.curve == 2:
            slope = self.Es / gy
            # Perfectly plastic: the ultimate stress equals the yield stress.
            return [(fyt / slope, fyt, None, "fytk"),
                    (self.eut, fyt, "eut", "fytk"),
                    (-fyc / slope, -fyc, None, "fyck")]

        slope = self.Es / gE
        fu = self.futk / gu
        if self.curve == 1:
            return [(fyt / slope, fyt, None, "fytk"),
                    (self.eut, fu, "eut", "futk"),
                    (-fyc / slope, -fyc, None, "fyck")]

        # curve 3: general two-yield law -- tension uses fytk, compression fyck.
        pts = [(self.ey0t + fyt / slope, fyt,
                "ey0t" if self.ey0t > 0.0 else None, "fytk"),
               (self.eut, fu, "eut", "futk"),
               (-(self.ey0c + fyc / slope), -fyc,
                "ey0c" if self.ey0c > 0.0 else None, "fyck")]
        if self.k < 1.0:                      # distinct first yield -> reveals k
            pts.append((self.k * fyt / slope, self.k * fyt, None, "k_fytk"))
            pts.append((-self.k * fyc / slope, -self.k * fyc, None, "k_fyck"))
        else:                                 # k = 1: mark fyck at the yield corner
            pts.append((-fyc / slope, -fyc, None, "fyck"))
        return pts


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
    Es: float = ES   # elastic (strain) modulus, MPa

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
            slope = self.Es / gE
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
            slope = self.Es / gE
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

    def diagram_markers(self, *, design: bool = True):
        """Points of interest labelled with the *input* parameters (tension only).

        For the user-defined laws this returns the proof and ultimate stresses
        (``fp0.1k`` = ``fytk``, ``fpk`` = ``futk``), the rupture strain ``eut``,
        the prestrain ``IS`` and -- when ``k < 1`` -- the first-yield level. The
        built-in characteristic curves are fixed, so only ``IS`` is marked.
        """
        is_marker = ([(self.IS, self.stress(self.IS, design=design), "IS", None)]
                     if self.IS > 0.0 else [])
        if self.curve not in (6, 7):
            rupt = self.rupture_strain
            return [(rupt, self.stress(rupt, design=design), "eut", None)] + is_marker

        gy = self.gamma_y if design else 1.0
        gE = self.gamma_E if design else 1.0
        gu = self.gamma_u if design else 1.0
        slope = self.Es / gE
        fyt = self.fytk / gy          # fp0.1k (factored if design)
        fu = self.futk / gu           # fpk
        # The proof stress is reached after the plastic strain ey0t (curve 7).
        pts = [(self.ey0t + fyt / slope, fyt,
                "ey0t" if self.ey0t > 0.0 else None, "fp01k"),
               (self.eut, fu, "eut", "fpk")]
        if self.k < 1.0:              # distinct first yield -> reveals k
            pts.insert(0, (self.k * fyt / slope, self.k * fyt, None, "k_fp01k"))
        return pts + is_marker
