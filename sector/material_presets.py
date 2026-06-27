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
# A reinforcement strain limit far beyond any attainable section strain, i.e.
# the EC2 horizontal branch with no strain limit (concrete crushing governs).
# Strain inputs are in per-mille (to match the diagram axis), so this is 1000.
_NO_STRAIN_LIMIT = 1000.0

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

def _concrete_presets():
    presets = {
        "Curve 1 (cubic)":
            {"curve": 1, "fck": _DEFAULT_FCK, "gamma_c": 1.0, "alpha_cc": 1.0},
        "Curve 2 (parabola-rectangle)":
            {"curve": 2, "fck": _DEFAULT_FCK, "gamma_c": 1.0, "alpha_cc": 1.0},
    }
    for label, code in codes.CODES.items():
        presets[label] = {
            "curve": 2,
            "fck": _DEFAULT_FCK,
            "gamma_c": code.gamma_c,
            "alpha_cc": round(code.concrete_factor(_DEFAULT_FCK), 4),
        }
    return presets


CONCRETE_PRESETS = _concrete_presets()

CONCRETE_FIELDS = ["fck", "gamma_c", "alpha_cc"]

# Bounds are deliberately permissive: a preset only prefills typical values, and
# every field stays freely editable. The lower bounds are the smallest the engine
# accepts (concrete needs fck, gamma_c and alpha_cc strictly positive); they are
# not code limits.
CONCRETE_FIELD_META = {
    "fck": ("fck (MPa)", 1.0, 200.0, 1.0),
    "gamma_c": ("gamma_c", 1.0, 3.0, 0.01),
    "alpha_cc": ("alpha_cc", 0.01, 1.2, 0.01),
}

# Help text shown as a hover tooltip next to each field.
CONCRETE_HELP = {
    "fck": "Characteristic compressive cylinder strength of the concrete.",
    "gamma_c": "Partial safety factor on the concrete strength (design = "
               "characteristic / gamma_c).",
    "alpha_cc": "Coefficient for long-term and loading effects on the concrete "
                "design strength (fcd = alpha_cc * fck / gamma_c).",
}


def build_concrete(curve, fck, gamma_c, alpha_cc) -> Concrete:
    """Build a :class:`~sector.materials.Concrete` from the panel parameters."""
    return Concrete(fck=float(fck), gamma_c=float(gamma_c), curve=int(curve),
                    alpha_cc=float(alpha_cc))


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
# A large ey0c keeps the compression side flat at -fyck (no compression
# hardening) for those shapes, matching the named curve 1/2 behaviour.
_ES = 200000.0   # default steel strain modulus, MPa


def _mild_presets():
    presets = {
        "Curve 1 (bilinear hardening)":
            {"curve": 3, "fytk": 550.0, "fyck": 550.0, "futk": 600.0, "eut": 50.0,
             "gamma_y": 1.0, "gamma_u": 1.0, "gamma_E": 1.0,
             "k": 1.0, "ey0t": 0.0, "ey0c": _NO_STRAIN_LIMIT, "Es": _ES},
        "Curve 2 (elastic-perfectly-plastic)":
            {"curve": 3, "fytk": 500.0, "fyck": 500.0, "futk": 500.0, "eut": 50.0,
             "gamma_y": 1.0, "gamma_u": 1.0, "gamma_E": 1.0,
             "k": 1.0, "ey0t": 0.0, "ey0c": _NO_STRAIN_LIMIT, "Es": _ES},
        # ey0c (the second yield's total compression strain, per-mille) must
        # exceed the first compression yield strain k*fyck/Es (~2.48 permille
        # here); otherwise the second-yield branch is skipped and it jumps.
        "Curve 3 (two yield points)":
            {"curve": 3, "fytk": 550.0, "fyck": 550.0, "futk": 600.0, "eut": 50.0,
             "gamma_y": 1.0, "gamma_u": 1.0, "gamma_E": 1.0,
             "k": 0.9, "ey0t": 2.0, "ey0c": 5.0, "Es": _ES},
    }
    # Eurocode editions: the general law reduced to EC2's flat design diagram --
    # un-factored modulus (gamma_E = 1), flat post-yield branch (futk = fyk,
    # gamma_u = gamma_s) and no strain limit (see sector.codes).
    for label, code in codes.CODES.items():
        presets[label] = {
            "curve": 3, "fytk": _DEFAULT_FYK, "fyck": _DEFAULT_FYK,
            "futk": _DEFAULT_FYK, "eut": _NO_STRAIN_LIMIT,
            "gamma_y": code.gamma_s, "gamma_u": code.gamma_s, "gamma_E": 1.0,
            "k": 1.0, "ey0t": 0.0, "ey0c": _NO_STRAIN_LIMIT, "Es": _ES,
        }
    return presets


MILD_PRESETS = _mild_presets()

# Permissive bounds: stresses may be zero (e.g. a tendon-free compression yield
# fyck = 0), partial factors run from 1 (characteristic) upward, and the modulus
# factor may dip below 1 when Ep exceeds the 200 GPa reference. These are input
# limits to keep the widgets sane, not Eurocode limits.
MILD_FIELD_META = {
    "fytk": ("fytk (MPa)", 0.0, 5000.0, 10.0),
    "fyck": ("fyck (MPa)", 0.0, 5000.0, 10.0),
    "futk": ("futk (MPa)", 0.0, 5000.0, 10.0),
    # min 0 keeps the step grid (min + k*step) on round values like 50 and 1000;
    # the eut >= yield clamp guards the lower end at build time.
    "eut": ("eut (permille)", 0.0, 2000.0, 0.5),
    "gamma_y": ("gamma_y", 1.0, 2.0, 0.01),
    "gamma_u": ("gamma_u", 1.0, 2.0, 0.01),
    "gamma_E": ("gamma_E", 0.5, 2.0, 0.01),
    "k": ("k (f1 / fytk)", 0.0, 1.0, 0.01),
    "ey0t": ("ey0t (permille)", 0.0, 1000.0, 0.1),
    "ey0c": ("ey0c (permille)", 0.0, 1000.0, 0.1),
    "Es": ("Es (MPa)", 1000.0, 500000.0, 1000.0),
}

MILD_HELP = {
    "fytk": "Characteristic yield stress in tension.",
    "fyck": "Characteristic yield stress in compression (set 0 for no "
            "compression capacity).",
    "futk": "Characteristic ultimate (rupture) stress in tension.",
    "eut": "Tensile strain at rupture.",
    "gamma_y": "Partial safety factor on the yield stress.",
    "gamma_u": "Partial safety factor on the ultimate stress.",
    "gamma_E": "Partial safety factor on the elastic modulus.",
    "k": "Ratio of the first to the second yield stress (f1 / fytk). Use k = 1 "
         "for a single yield point (bilinear or elastic-perfectly-plastic).",
    "ey0t": "Plastic strain at the second tensile yield. Use 0 for a single "
            "yield point.",
    "ey0c": "Total strain at the second compression yield. A large value keeps "
            "the compression side flat at fyck (no second yield).",
    "Es": "Elastic (Young's) modulus of the reinforcement.",
}

MILD_FIELDS_BY_CURVE = {
    1: ["fytk", "fyck", "futk", "eut", "gamma_y", "gamma_u", "gamma_E", "Es"],
    2: ["fytk", "fyck", "eut", "gamma_y", "Es"],
    3: ["fytk", "fyck", "futk", "eut", "gamma_y", "gamma_u", "gamma_E",
        "k", "ey0t", "ey0c", "Es"],
}


def build_mild(curve, **fields) -> MildSteel:
    """Build a :class:`~sector.materials.MildSteel` from the panel parameters.

    Strain fields arrive in per-mille and are converted to the fractions the law
    uses.
    """
    curve = int(curve)
    used = {f: float(fields[f]) for f in MILD_FIELDS_BY_CURVE[curve] if f in fields}
    return MildSteel(curve=curve, **_to_fractions(used))


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
        ep_mpa = 200000.0 if code.key == "EC2-2023" else 195000.0
        presets[label] = {
            "curve": 7, "IS": 0.0, "fytk": 1640.0, "futk": 1860.0, "eut": 35.0,
            "k": 1.0, "ey0t": 0.0, "gamma_y": code.gamma_s,
            "gamma_u": code.gamma_s, "gamma_E": 1.0, "Es": ep_mpa}
    return presets


PRESTRESS_PRESETS = _prestress_presets()

PRESTRESS_FIELD_META = {
    "IS": ("Prestrain IS (permille)", 0.0, 50.0, 0.1),
    "fytk": ("fp0.1k (MPa)", 0.0, 5000.0, 10.0),
    "futk": ("fpk (MPa)", 0.0, 5000.0, 10.0),
    "eut": ("eut (permille)", 0.0, 2000.0, 0.5),
    "gamma_y": ("gamma_y", 1.0, 2.0, 0.01),
    "gamma_u": ("gamma_u", 1.0, 2.0, 0.01),
    "gamma_E": ("gamma_E", 0.5, 2.0, 0.01),
    "k": ("k (f1 / fp0.1k)", 0.0, 1.0, 0.01),
    "ey0t": ("ey0t (permille)", 0.0, 1000.0, 0.1),
    "Es": ("Ep (MPa)", 1000.0, 500000.0, 1000.0),
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
    return Prestress(curve=curve, **_to_fractions(used))
