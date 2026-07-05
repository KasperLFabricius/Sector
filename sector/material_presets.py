"""Named material parameter presets for the Material Parameters panel.

Each material type (concrete, mild reinforcement) offers a set of presets: the
built-in stress-strain curve types, which prefill that curve's parameters, and the
Eurocode editions, which prefill the code-defined partial factors and design
coefficients. A preset only *prefills* values -- every parameter stays editable,
and the Eurocode presets are derived from :mod:`sector.codes` so the factors
match the design-code material laws exactly.

Each preset is a flat dict of the fields the material law needs (including its
``curve`` type). The ``*_FIELD_META`` tables give the editable numeric fields
(label, min, max, step); the panel shows them all (a flat form), so the available
inputs never change with the preset. ``*_FIELDS_BY_CURVE`` lists which fields each
curve actually uses -- ``build_*`` keeps only those when constructing the law, so
the parameters a curve ignores have no effect.
"""

from __future__ import annotations

from . import codes
from .materials import Concrete, MildSteel, Prestress

_DEFAULT_FCK = 35.0
_DEFAULT_FYK = 500.0
# Strain fields are entered and stored in per-mille; ``build_*`` converts them to
# the fractions the material laws use.
_PERMILLE_FIELDS = ("eut", "ey0t", "ey0c", "IS")


def _to_fractions(used):
    """Convert the per-mille strain fields in a parameter dict to fractions."""
    for f in _PERMILLE_FIELDS:
        if f in used:
            used[f] = used[f] / 1000.0
    return used


# ---------------------------------------------------------------------------
# Concrete
# ---------------------------------------------------------------------------

# Default concrete strain limits and exponent (per mille / dimensionless): the
# normal-strength parabola-rectangle (eps_c2 = 0.2%, eps_cu2 = 0.35%, n = 2).
_DEFAULT_EPS_C2 = 2.0
_DEFAULT_EPS_CU2 = 3.5
_DEFAULT_N = 2.0


def _concrete_presets():
    base = {"eps_c2": _DEFAULT_EPS_C2, "eps_cu2": _DEFAULT_EPS_CU2, "n": _DEFAULT_N}
    presets = {
        "Curve 1 (cubic)":
            {"curve": 1, "fck": _DEFAULT_FCK, "gamma_c": 1.0, "alpha_cc": 1.0, **base},
        "Curve 2 (parabola-rectangle)":
            {"curve": 2, "fck": _DEFAULT_FCK, "gamma_c": 1.0, "alpha_cc": 1.0, **base},
    }
    for label, code in codes.CODES.items():
        presets[label] = {
            "curve": 2,
            "fck": _DEFAULT_FCK,
            "gamma_c": code.gamma_c,
            "alpha_cc": round(code.concrete_factor(_DEFAULT_FCK), 4),
            **base,
        }
    return presets


CONCRETE_PRESETS = _concrete_presets()

CONCRETE_FIELDS = ["fck", "gamma_c", "alpha_cc", "eps_c2", "eps_cu2", "n"]

# Bounds are deliberately permissive: a preset only prefills typical values, and
# every field stays freely editable. The lower bounds are the smallest the engine
# accepts (concrete needs fck, gamma_c and alpha_cc strictly positive); they are
# not code limits.
# Labels carry LaTeX ($...$) so Streamlit renders proper Greek and sub/superscripts.
CONCRETE_FIELD_META = {
    "fck": (r"$f_{ck}$ (MPa)", 1.0, 200.0, 1.0),
    "gamma_c": (r"$\gamma_c$", 1.0, 3.0, 0.01),
    "alpha_cc": (r"$\alpha_{cc}$", 0.01, 1.2, 0.01),
    "eps_c2": (r"$\varepsilon_{c2}$ (permille)", 0.5, 5.0, 0.05),
    "eps_cu2": (r"$\varepsilon_{cu2}$ (permille)", 0.5, 8.0, 0.05),
    "n": (r"$n$ (parabola exponent)", 1.0, 4.0, 0.05),
}

# Help text shown as a hover tooltip next to each field.
CONCRETE_HELP = {
    "fck": "Characteristic compressive cylinder strength of the concrete.",
    "gamma_c": "Partial safety factor on the concrete strength (design = "
               "characteristic / gamma_c).",
    "alpha_cc": "Coefficient for long-term and loading effects on the concrete "
                "design strength (fcd = alpha_cc * fck / gamma_c).",
    "eps_c2": "Compressive strain at peak stress (parabola apex). EC2 Table 3.1: "
              "0.2 permille up to C50/60, larger above (use Auto).",
    "eps_cu2": "Ultimate (crushing) compressive strain. EC2 Table 3.1: 0.35 "
               "permille up to C50/60, smaller above (use Auto).",
    "n": "Exponent of the parabola-rectangle ascending branch. EC2 Table 3.1: "
         "2.0 up to C50/60, smaller above (use Auto).",
}


def build_concrete(curve, fck, gamma_c, alpha_cc,
                   eps_c2=_DEFAULT_EPS_C2, eps_cu2=_DEFAULT_EPS_CU2,
                   n=_DEFAULT_N) -> Concrete:
    """Build a :class:`~sector.materials.Concrete` from the panel parameters.

    ``eps_c2``/``eps_cu2`` are taken in per mille (the diagram's unit) and
    converted to the fractions the law uses.
    """
    return Concrete(fck=float(fck), gamma_c=float(gamma_c), curve=int(curve),
                    alpha_cc=float(alpha_cc),
                    eps_c2=float(eps_c2) / 1000.0, eps_cu2=float(eps_cu2) / 1000.0,
                    n=float(n))


def strength_dependent_alpha_cc(preset, fck):
    """``alpha_cc`` for a preset whose design factor depends on ``fck``, else None.

    EN 1992-1-1:2023 uses ``eta_cc = (40/fck)^(1/3) <= 1`` (times ``k_tc``), so its
    ``alpha_cc`` must follow the chosen strength rather than stay at the prefilled
    default. Constant-``alpha_cc`` editions return ``None``.
    """
    code = codes.CODES.get(preset)
    if code is not None and code.eta_cc_ref is not None:
        return round(code.concrete_factor(float(fck)), 4)
    return None


# ---------------------------------------------------------------------------
# Mild reinforcement
# ---------------------------------------------------------------------------

# All mild-steel presets build the general two-yield law (curve 3), so every
# field is live and shown on the diagram. The shapes are special cases:
#   bilinear              -> k = 1, ey0t = 0 (first and second yield coincide)
#   elastic-perfectly-plastic -> additionally futk = fytk (flat hardening branch)
# ey0t and ey0c are the second yield's plastic offsets (0 collapses it onto the
# first yield), symmetric in tension and compression. The flat-compression shapes
# rely on futk = fytk (so the compression branch hardens to -fyck = flat), not on
# a special ey0c value.
_ES = 200.0   # default steel elastic modulus (panel unit GPa; 200 GPa = 200000 MPa)


def _mild_presets():
    presets = {
        "Curve 1 (bilinear hardening)":
            {"curve": 3, "fytk": 550.0, "fyck": 550.0, "futk": 600.0, "eut": 50.0,
             "gamma_y": 1.0, "gamma_u": 1.0, "gamma_E": 1.0,
             "k": 1.0, "ey0t": 0.0, "ey0c": 0.0, "Es": _ES},
        "Curve 2 (elastic-perfectly-plastic)":
            {"curve": 3, "fytk": 500.0, "fyck": 500.0, "futk": 500.0, "eut": 50.0,
             "gamma_y": 1.0, "gamma_u": 1.0, "gamma_E": 1.0,
             "k": 1.0, "ey0t": 0.0, "ey0c": 0.0, "Es": _ES},
        # ey0c is the second compression yield's plastic offset (per-mille), the
        # mirror of ey0t; both non-zero so the two-yield plateau shows on each side
        # before hardening. 2.25 = the old total 5.0 minus the elastic part
        # fyck/Es (550/200000 = 2.75 permille), so the curve is unchanged.
        "Curve 3 (two yield points)":
            {"curve": 3, "fytk": 550.0, "fyck": 550.0, "futk": 600.0, "eut": 50.0,
             "gamma_y": 1.0, "gamma_u": 1.0, "gamma_E": 1.0,
             "k": 0.9, "ey0t": 2.0, "ey0c": 2.25, "Es": _ES},
    }
    # Eurocode editions: the general law reduced to EC2's flat design diagram --
    # un-factored modulus (gamma_E = 1), flat post-yield branch (futk = fyk,
    # gamma_u = gamma_s). eut defaults to 50 permille (the characteristic ultimate
    # strain euk of class B reinforcement); the design value is typically 0.9*euk
    # (EC2 3.2.7), which the user enters as the design value.
    for label, code in codes.CODES.items():
        # Danish practice uses B550 reinforcement, so the DK NA edition defaults
        # to 550 MPa; the other editions keep the B500 default.
        fyk = 550.0 if "DK NA" in label else _DEFAULT_FYK
        presets[label] = {
            "curve": 3, "fytk": fyk, "fyck": fyk,
            "futk": fyk, "eut": 50.0,
            "gamma_y": code.gamma_s, "gamma_u": code.gamma_s, "gamma_E": 1.0,
            "k": 1.0, "ey0t": 0.0, "ey0c": 0.0, "Es": _ES,
        }
    return presets


MILD_PRESETS = _mild_presets()

# Permissive bounds: stresses may be zero (e.g. a tendon-free compression yield
# fyck = 0), partial factors run from 1 (characteristic) upward, and the modulus
# factor may dip below 1 when Ep exceeds the 200 GPa reference. These are input
# limits to keep the widgets sane, not Eurocode limits.
MILD_FIELD_META = {
    "fytk": (r"$f_{ytk}$ (MPa)", 0.0, 5000.0, 10.0),
    "fyck": (r"$f_{yck}$ (MPa)", 0.0, 5000.0, 10.0),
    "futk": (r"$f_{utk}$ (MPa)", 0.0, 5000.0, 10.0),
    # min 0 keeps the step grid (min + k*step) on round values like 50 and 1000;
    # the eut >= yield clamp guards the lower end at build time.
    "eut": (r"$\varepsilon_{ut}$ (permille)", 0.0, 2000.0, 0.5),
    "gamma_y": (r"$\gamma_y$", 1.0, 2.0, 0.01),
    "gamma_u": (r"$\gamma_u$", 1.0, 2.0, 0.01),
    "gamma_E": (r"$\gamma_E$", 0.5, 2.0, 0.01),
    "k": (r"$k$ ($f_1 / f_{ytk}$)", 0.0, 1.0, 0.01),
    "ey0t": (r"$\varepsilon_{0t}$ (permille)", 0.0, 1000.0, 0.1),
    "ey0c": (r"$\varepsilon_{0c}$ (permille)", 0.0, 1000.0, 0.1),
    "Es": (r"$E_s$ (GPa)", 1.0, 500.0, 1.0),
}

MILD_HELP = {
    "fytk": "Characteristic yield stress in tension.",
    "fyck": "Characteristic yield stress in compression (set 0 for no "
            "compression capacity).",
    "futk": "Characteristic ultimate (rupture) stress in tension.",
    "eut": "Design rupture strain (applied symmetrically in tension and "
           "compression). Per EC2 3.2.7 the design value is typically 0.9*euk "
           "(e.g. ~45 permille for class B steel, euk = 50 permille); enter the "
           "design value.",
    "gamma_y": "Partial safety factor on the yield stress.",
    "gamma_u": "Partial safety factor on the ultimate stress.",
    "gamma_E": "Partial safety factor on the elastic modulus.",
    "k": "Ratio of the first to the second yield stress (f1 / fytk). Use k = 1 "
         "for a single yield point (bilinear or elastic-perfectly-plastic).",
    "ey0t": "Plastic strain at the second tensile yield. Use 0 for a single "
            "yield point.",
    "ey0c": "Plastic strain at the second compression yield (mirror of ey0t). "
            "Use 0 for a single compression yield.",
    "Es": "Elastic (Young's) modulus of the reinforcement.",
}

MILD_FIELDS_BY_CURVE = {
    1: ["fytk", "fyck", "futk", "eut", "gamma_y", "gamma_u", "gamma_E", "Es"],
    2: ["fytk", "fyck", "eut", "gamma_y", "Es"],
    3: ["fytk", "fyck", "futk", "eut", "gamma_y", "gamma_u", "gamma_E",
        "k", "ey0t", "ey0c", "Es"],
}


def build_mild(curve, *, active_in_compression=True, **fields) -> MildSteel:
    """Build a :class:`~sector.materials.MildSteel` from the panel parameters.

    Strain fields arrive in per-mille and are converted to the fractions the law
    uses. ``active_in_compression`` False makes the bar tension-only.
    """
    curve = int(curve)
    used = {f: float(fields[f]) for f in MILD_FIELDS_BY_CURVE[curve] if f in fields}
    if "Es" in used:
        used["Es"] *= 1000.0   # panel unit GPa -> the material law's MPa
    return MildSteel(curve=curve, active_in_compression=bool(active_in_compression),
                     **_to_fractions(used))


# ---------------------------------------------------------------------------
# Prestressing steel (tendons)
# ---------------------------------------------------------------------------

def _prestress_presets():
    presets = {}
    # The built-in characteristic curves are fixed polynomial shapes: only the
    # prestrain and the yield partial factor apply (the parametric fields are
    # inert for these).
    for n in (1, 2, 3, 4, 5):
        presets["Curve %d (built-in)" % n] = {"curve": n, "IS": 5.9,
                                              "gamma_y": 1.1, "Es": _ES}
    # The user-defined shapes build the general two-yield law (curve 7), so every
    # parametric field is live; a bilinear curve is the k = 1, ey0t = 0 case.
    presets["Curve 6 (bilinear)"] = {
        "curve": 7, "IS": 5.9, "fytk": 1600.0, "futk": 1860.0, "eut": 35.0,
        "k": 1.0, "ey0t": 0.0, "gamma_y": 1.1, "gamma_u": 1.1, "gamma_E": 1.0,
        "Es": _ES}
    presets["Curve 7 (two yield)"] = {
        "curve": 7, "IS": 5.9, "fytk": 1600.0, "futk": 1860.0, "eut": 35.0,
        "k": 0.9, "ey0t": 2.0, "gamma_y": 1.1, "gamma_u": 1.1, "gamma_E": 1.0,
        "Es": _ES}
    # Eurocode editions: the general law as EC2's bilinear design diagram, with
    # the prestressing modulus Ep entered directly -- 195 GPa for the 2005
    # editions and the DK NA, 200 GPa for 2023 (fpd = fp0,1k/gamma_s).
    for label, code in codes.CODES.items():
        ep_gpa = 200.0 if code.key == "EC2-2023" else 195.0
        presets[label] = {
            "curve": 7, "IS": 0.0, "fytk": 1640.0, "futk": 1860.0, "eut": 35.0,
            "k": 1.0, "ey0t": 0.0, "gamma_y": code.gamma_s,
            "gamma_u": code.gamma_s, "gamma_E": 1.0, "Es": ep_gpa}
    return presets


PRESTRESS_PRESETS = _prestress_presets()

PRESTRESS_FIELD_META = {
    "IS": (r"Prestrain $\varepsilon_{p}^{(0)}$ (permille)", 0.0, 50.0, 0.1),
    "fytk": (r"$f_{p0.1k}$ (MPa)", 0.0, 5000.0, 10.0),
    "futk": (r"$f_{pk}$ (MPa)", 0.0, 5000.0, 10.0),
    "eut": (r"$\varepsilon_{ut}$ (permille)", 0.0, 2000.0, 0.5),
    "gamma_y": (r"$\gamma_y$", 1.0, 2.0, 0.01),
    "gamma_u": (r"$\gamma_u$", 1.0, 2.0, 0.01),
    "gamma_E": (r"$\gamma_E$", 0.5, 2.0, 0.01),
    "k": (r"$k$ ($f_1 / f_{p0.1k}$)", 0.0, 1.0, 0.01),
    "ey0t": (r"$\varepsilon_{0t}$ (permille)", 0.0, 1000.0, 0.1),
    "Es": (r"$E_p$ (GPa)", 1.0, 500.0, 1.0),
}

PRESTRESS_HELP = {
    "IS": "Initial (effective) prestrain locked into the tendon after losses; "
          "the section strain adds to this.",
    "fytk": "Characteristic 0.1% proof stress (fp0.1k).",
    "futk": "Characteristic ultimate (rupture) stress (fpk).",
    "eut": "Strain at rupture.",
    "gamma_y": "Partial safety factor on the proof stress.",
    "gamma_u": "Partial safety factor on the ultimate stress.",
    "gamma_E": "Partial safety factor on the elastic modulus.",
    "k": "Ratio of the first to the proof stress (f1 / fp0.1k). Use k = 1 for a "
         "bilinear curve.",
    "ey0t": "Plastic strain at the proof stress. Use 0 for a bilinear curve.",
    "Es": "Elastic modulus of the prestressing steel (Ep).",
}

PRESTRESS_FIELDS_BY_CURVE = {
    1: ["IS", "gamma_y", "Es"], 2: ["IS", "gamma_y", "Es"], 3: ["IS", "gamma_y", "Es"],
    4: ["IS", "gamma_y", "Es"], 5: ["IS", "gamma_y", "Es"],
    6: ["IS", "fytk", "futk", "eut", "gamma_y", "gamma_u", "gamma_E", "Es"],
    7: ["IS", "fytk", "futk", "eut", "k", "ey0t", "gamma_y", "gamma_u", "gamma_E", "Es"],
}


def build_prestress(curve, **fields) -> Prestress:
    """Build a :class:`~sector.materials.Prestress` from the panel parameters.

    Strain fields (IS, eut, ey0t) arrive in per-mille and are converted to the
    fractions the law uses.
    """
    curve = int(curve)
    used = {f: float(fields[f]) for f in PRESTRESS_FIELDS_BY_CURVE[curve] if f in fields}
    if "Es" in used:
        used["Es"] *= 1000.0   # panel unit GPa -> the material law's MPa
    return Prestress(curve=curve, **_to_fractions(used))
