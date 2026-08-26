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
import math
from numbers import Integral, Real

# Characteristic modulus of elasticity of reinforcement, MPa (Ek in the manual).
ES = 2.0e5

_STRENGTH_ORDER_REL_TOL = 1.0e-12


def _positive_finite_quotient(
    numerator: float,
    denominator: float,
) -> float | None:
    """Return a positive finite quotient, or ``None`` at the numeric boundary."""

    try:
        quotient = numerator / denominator
    except (OverflowError, ZeroDivisionError):
        return None
    return quotient if math.isfinite(quotient) and quotient > 0.0 else None


def design_ordinate_is_positive_finite(
    characteristic_strength: float,
    partial_factor: float,
) -> bool:
    """Return whether one derived design-stress ordinate is usable."""

    return (
        _positive_finite_quotient(characteristic_strength, partial_factor)
        is not None
    )


def _factored_yield_strain(
    characteristic_strength: float,
    strength_factor: float,
    elastic_modulus: float,
    modulus_factor: float,
) -> float | None:
    """Return a usable yield strain from separately factored ordinates."""

    design_strength = _positive_finite_quotient(
        characteristic_strength, strength_factor
    )
    design_slope = _positive_finite_quotient(
        elastic_modulus, modulus_factor
    )
    if design_strength is None or design_slope is None:
        return None
    return _positive_finite_quotient(design_strength, design_slope)


def governing_yield_strain(
    characteristic_strength: float,
    strength_factor: float,
    elastic_modulus: float,
    modulus_factor: float,
) -> float | None:
    """Return the greater usable characteristic/design yield strain."""

    characteristic_yield = _positive_finite_quotient(
        characteristic_strength, elastic_modulus
    )
    design_yield = _factored_yield_strain(
        characteristic_strength,
        strength_factor,
        elastic_modulus,
        modulus_factor,
    )
    if characteristic_yield is None or design_yield is None:
        return None
    return max(characteristic_yield, design_yield)


def design_ultimate_not_below_yield(
    ultimate_strength: float,
    ultimate_factor: float,
    yield_strength: float,
    yield_factor: float,
) -> bool:
    """Return whether the factored ultimate ordinate is non-descending.

    Decimal engineering inputs can produce adjacent binary results when two
    divisions are mathematically equal. Accept only a tight relative round-off
    band: an absolute tolerance would incorrectly accept a materially descending
    branch merely because its stresses are small.
    """

    design_ultimate = _positive_finite_quotient(
        ultimate_strength, ultimate_factor
    )
    design_yield = _positive_finite_quotient(yield_strength, yield_factor)
    if design_ultimate is None or design_yield is None:
        return False
    return design_ultimate >= design_yield or math.isclose(
        design_ultimate,
        design_yield,
        rel_tol=_STRENGTH_ORDER_REL_TOL,
        abs_tol=0.0,
    )


def _linear_branch_value(
    coordinate: float,
    start_coordinate: float,
    end_coordinate: float,
    start_value: float,
    end_value: float,
) -> float:
    """Interpolate one non-descending branch without product-before-division.

    Material constructors establish finite ordered endpoints and a positive
    coordinate span. Returning the endpoints explicitly and forming the bounded
    interpolation fraction first keeps every accepted branch finite at extreme
    but representable input scales.
    """

    if coordinate <= start_coordinate:
        return start_value
    if coordinate >= end_coordinate:
        return end_value
    fraction = (coordinate - start_coordinate) / (
        end_coordinate - start_coordinate
    )
    return start_value + (end_value - start_value) * fraction


def _finite_value(value: float, label: str) -> float:
    """Return one finite material value with an owning-field diagnostic."""

    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite value")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite value") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite value")
    return number


def _require_positive_finite(value: float, label: str) -> float:
    try:
        number = _finite_value(value, label)
    except ValueError as exc:
        raise ValueError(f"{label} must be a positive finite value") from exc
    if number <= 0.0:
        raise ValueError(f"{label} must be a positive finite value")
    return number


def _require_nonnegative_finite(value: float, label: str) -> float:
    try:
        number = _finite_value(value, label)
    except ValueError as exc:
        raise ValueError(f"{label} must be a non-negative finite value") from exc
    if number < 0.0:
        raise ValueError(f"{label} must be a non-negative finite value")
    return number


def _require_governing_yield_strain(
    characteristic_strength: float,
    strength_factor: float,
    elastic_modulus: float,
    modulus_factor: float,
    label: str,
) -> float:
    yield_strain = governing_yield_strain(
        characteristic_strength,
        strength_factor,
        elastic_modulus,
        modulus_factor,
    )
    if yield_strain is None:
        raise ValueError(f"{label} must be a positive finite value")
    return yield_strain


def _require_yield_before_rupture(
    yield_strain: float,
    rupture_strain: float,
    label: str,
) -> None:
    """Reject a law whose active yield point reaches or exceeds rupture."""

    if not math.isfinite(yield_strain) or yield_strain <= 0.0:
        raise ValueError(f"{label} must be a positive finite value")
    if yield_strain >= rupture_strain:
        raise ValueError(f"{label} must be below the rupture strain eut")


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
        return _linear_branch_value(eps, e1, e2, f1, f2)
    if eut <= e2:
        return f2  # degenerate: no room for a hardening branch
    return _linear_branch_value(eps, e2, eut, f2, fu)


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
        _require_positive_finite(self.fck, "fck")
        _require_positive_finite(self.gamma_c, "gamma_c")
        _require_positive_finite(self.alpha_cc, "alpha_cc")
        if (
            not math.isfinite(float(self.eps_c2))
            or not math.isfinite(float(self.eps_cu2))
            or self.eps_c2 <= 0.0
            or self.eps_cu2 < self.eps_c2
        ):
            raise ValueError("need 0 < eps_c2 <= eps_cu2")
        _require_positive_finite(self.n, "parabola exponent n")

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
        if (
            isinstance(self.curve, bool)
            or not isinstance(self.curve, Integral)
            or self.curve not in (1, 2, 3)
        ):
            raise ValueError("mild steel curve must be 1, 2 or 3")
        if type(self.active_in_compression) is not bool:
            raise ValueError("active_in_compression must be a Boolean")
        fytk = _require_positive_finite(self.fytk, "fytk")
        # A zero compression yield is the established tension-only sentinel.  It
        # remains a finite material input, but it owns no compression branch and
        # therefore no compression yield/rupture relation.
        fyck = _require_nonnegative_finite(self.fyck, "fyck")
        eut = _require_positive_finite(self.eut, "eut")
        gamma_y = _require_positive_finite(self.gamma_y, "gamma_y")
        Es = _require_positive_finite(self.Es, "Es")
        if not design_ordinate_is_positive_finite(fytk, gamma_y):
            raise ValueError("fytk/gamma_y must be a positive finite value")
        if (
            self.active_in_compression
            and fyck > 0.0
            and not design_ordinate_is_positive_finite(fyck, gamma_y)
        ):
            raise ValueError("fyck/gamma_y must be a positive finite value")

        if self.curve == 2:
            tension_yield = _require_governing_yield_strain(
                fytk, gamma_y, Es, gamma_y, "tensile yield strain"
            )
            _require_yield_before_rupture(
                tension_yield,
                eut,
                "tensile yield strain",
            )
            if self.active_in_compression and fyck > 0.0:
                compression_yield = _require_governing_yield_strain(
                    fyck,
                    gamma_y,
                    Es,
                    gamma_y,
                    "compressive yield strain",
                )
                _require_yield_before_rupture(
                    compression_yield,
                    eut,
                    "compressive yield strain",
                )
            return

        gamma_u = _require_positive_finite(self.gamma_u, "gamma_u")
        gamma_E = _require_positive_finite(self.gamma_E, "gamma_E")
        futk = _require_positive_finite(self.futk, "futk")
        if futk < fytk:
            raise ValueError("futk must be greater than or equal to fytk")
        if (
            self.curve == 3
            and self.active_in_compression
            and fyck > 0.0
            and futk < fyck
        ):
            raise ValueError(
                "futk must be greater than or equal to active fyck"
            )
        if not design_ultimate_not_below_yield(
            futk, gamma_u, fytk, gamma_y
        ):
            raise ValueError(
                "futk/gamma_u must be greater than or equal to fytk/gamma_y"
            )
        if (
            self.curve == 3
            and self.active_in_compression
            and fyck > 0.0
            and not design_ultimate_not_below_yield(
                futk, gamma_u, fyck, gamma_y
            )
        ):
            raise ValueError(
                "futk/gamma_u must be greater than or equal to active "
                "fyck/gamma_y"
            )

        tension_yield = _require_governing_yield_strain(
            fytk,
            gamma_y,
            Es,
            gamma_E,
            "tensile yield strain",
        )
        if self.curve == 1:
            _require_yield_before_rupture(
                tension_yield,
                eut,
                "tensile yield strain",
            )
            if self.active_in_compression and fyck > 0.0:
                compression_yield = _require_governing_yield_strain(
                    fyck,
                    gamma_y,
                    Es,
                    gamma_E,
                    "compressive yield strain",
                )
                _require_yield_before_rupture(
                    compression_yield,
                    eut,
                    "compressive yield strain",
                )
            return

        k = _finite_value(self.k, "k")
        if not 0.0 < k <= 1.0:
            raise ValueError("k must satisfy 0 < k <= 1")
        ey0t = _require_nonnegative_finite(self.ey0t, "ey0t")
        _require_yield_before_rupture(
            ey0t + tension_yield,
            eut,
            "second tensile yield strain ey0t + fytk/Es",
        )
        ey0c = _finite_value(self.ey0c, "ey0c")
        if self.active_in_compression and fyck > 0.0:
            if ey0c < 0.0:
                raise ValueError("ey0c must be a non-negative finite value")
            compression_yield = _require_governing_yield_strain(
                fyck,
                gamma_y,
                Es,
                gamma_E,
                "compressive yield strain",
            )
            _require_yield_before_rupture(
                ey0c + compression_yield,
                eut,
                "second compressive yield strain ey0c + fyck/Es",
            )

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
                return -(
                    _linear_branch_value(a, e1, e2c, f1c, fyc)
                    if span > 0
                    else fyc
                )
            if e2c < a < self.eut and self.eut > e2c:
                return -_linear_branch_value(
                    a, e2c, self.eut, fyc, fu
                )
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
            return _linear_branch_value(
                eps, eps_y, self.eut, fyt, fu
            )
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
        """Labelled points of interest for branches the law actually carries."""
        pts = self._markers(design=design)
        # A positive fyck and the explicit compression toggle jointly own the
        # compression branch.  Inactive offsets are retained as project inputs,
        # but cannot create a plotted yield or rupture point by changing the sign
        # of a derived coordinate.
        if self.active_in_compression and self.fyck > 0.0:
            pts = pts + [
                (-self.eut, self.stress(-self.eut, design=design), "eut", None)
            ]
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
        compression_active = self.active_in_compression and self.fyck > 0.0

        if self.curve == 2:
            slope = self.Es / gy
            # Perfectly plastic: the ultimate stress equals the yield stress.
            pts = [(fyt / slope, fyt, None, "fytk"),
                   (self.eut, fyt, "eut", "fytk")]
            if compression_active:
                pts.append((-fyc / slope, -fyc, None, "fyck"))
            return pts

        slope = self.Es / gE
        fu = self.futk / gu
        if self.curve == 1:
            pts = [(fyt / slope, fyt, None, "fytk"),
                   (self.eut, fu, "eut", "futk")]
            if compression_active:
                pts.append((-fyc / slope, -fyc, None, "fyck"))
            return pts

        # curve 3: general two-yield law -- tension uses fytk, compression fyck.
        pts = [(self.ey0t + fyt / slope, fyt,
                "ey0t" if self.ey0t > 0.0 else None, "fytk"),
               (self.eut, fu, "eut", "futk")]
        if compression_active:
            pts.append((-(self.ey0c + fyc / slope), -fyc,
                        "ey0c" if self.ey0c > 0.0 else None, "fyck"))
        if self.k < 1.0:                      # distinct first yield -> reveals k
            pts.append((self.k * fyt / slope, self.k * fyt, None, "k_fytk"))
            if compression_active:
                pts.append(
                    (-self.k * fyc / slope, -self.k * fyc, None, "k_fyck")
                )
        elif compression_active:              # mark fyck at the yield corner
            pts.append((-fyc / slope, -fyc, None, "fyck"))
        return pts


# Rupture strain of the built-in prestressing curves (fraction): 3.5 %.
EPS_P_RES = 0.035


def _builtin_prestress_characteristic(curve: int, e: float) -> float:
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


def builtin_prestress_design_ordinate_is_positive_finite(
    curve: int,
    partial_factor: float,
) -> bool:
    """Return whether a fixed prestress law has a usable design ordinate."""

    if isinstance(curve, bool) or not isinstance(curve, Integral):
        return False
    if curve not in (1, 2, 3, 4, 5):
        return False
    characteristic = _builtin_prestress_characteristic(
        curve, EPS_P_RES * 100.0
    )
    return design_ordinate_is_positive_finite(characteristic, partial_factor)


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
        if (
            isinstance(self.curve, bool)
            or not isinstance(self.curve, Integral)
            or self.curve not in (1, 2, 3, 4, 5, 6, 7)
        ):
            raise ValueError("prestress curve must be 1-7")
        initial_strain = _require_nonnegative_finite(self.IS, "IS")
        gamma_y = _require_positive_finite(self.gamma_y, "gamma_y")
        Es = _require_positive_finite(self.Es, "Es")

        if self.curve in (1, 2, 3, 4, 5):
            if initial_strain >= EPS_P_RES:
                raise ValueError("IS must be below the fixed rupture strain")
            if not builtin_prestress_design_ordinate_is_positive_finite(
                self.curve, gamma_y
            ):
                raise ValueError(
                    "fixed prestress design stress must be a positive finite value"
                )
            return

        gamma_u = _require_positive_finite(self.gamma_u, "gamma_u")
        gamma_E = _require_positive_finite(self.gamma_E, "gamma_E")
        fytk = _require_positive_finite(self.fytk, "fp0.1k")
        futk = _require_positive_finite(self.futk, "fpk")
        eut = _require_positive_finite(self.eut, "eut")
        if not design_ordinate_is_positive_finite(fytk, gamma_y):
            raise ValueError(
                "fp0.1k/gamma_y must be a positive finite value"
            )
        if futk < fytk:
            raise ValueError("fpk must be greater than or equal to fp0.1k")
        if not design_ultimate_not_below_yield(
            futk, gamma_u, fytk, gamma_y
        ):
            raise ValueError(
                "fpk/gamma_u must be greater than or equal to "
                "fp0.1k/gamma_y"
            )
        if initial_strain >= eut:
            raise ValueError("IS must be below the rupture strain eut")

        proof_strain = _require_governing_yield_strain(
            fytk,
            gamma_y,
            Es,
            gamma_E,
            "proof strain fp0.1k/Ep",
        )
        if self.curve == 6:
            _require_yield_before_rupture(
                proof_strain,
                eut,
                "proof strain fp0.1k/Ep",
            )
            return

        k = _finite_value(self.k, "k")
        if not 0.0 < k <= 1.0:
            raise ValueError("k must satisfy 0 < k <= 1")
        ey0t = _require_nonnegative_finite(self.ey0t, "ey0t")
        _require_yield_before_rupture(
            ey0t + proof_strain,
            eut,
            "proof strain ey0t + fp0.1k/Ep",
        )

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
        return _builtin_prestress_characteristic(curve, e)

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
            return _linear_branch_value(
                eps, eps_y, self.eut, fyt, fu
            )

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
