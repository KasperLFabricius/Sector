"""Named material parameter presets for the Material Parameters panel.

Each material type (concrete, mild reinforcement) offers a set of presets: the
legacy stress-strain curve types, which prefill that curve's parameters, and the
Eurocode editions, which prefill the code-defined partial factors and design
coefficients. A preset only *prefills* values -- every parameter stays editable,
and the Eurocode presets are derived from :mod:`sector.codes` so the factors
match the design-code material laws exactly.

Each preset is a flat dict of the fields the material law needs (including its
``curve`` type). The ``*_FIELD_META`` tables give the editable numeric fields
(label, min, max, step), and ``MILD_FIELDS_BY_CURVE`` lists which fields apply to
each mild-steel curve so the UI shows the relevant ones.
"""

from __future__ import annotations

from . import codes
from .materials import Concrete, MildSteel, Prestress

_DEFAULT_FCK = 35.0
_DEFAULT_FYK = 500.0
# A reinforcement strain limit far beyond any attainable section strain, i.e.
# the EC2 horizontal branch with no strain limit (concrete crushing governs).
_NO_STRAIN_LIMIT = 1.0


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

CONCRETE_FIELD_META = {
    "fck": ("fck (MPa)", 8.0, 100.0, 1.0),
    "gamma_c": ("gamma_c", 1.0, 2.0, 0.01),
    "alpha_cc": ("alpha_cc", 0.5, 1.0, 0.01),
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

def _mild_presets():
    presets = {
        "Curve 1 (bilinear hardening)":
            {"curve": 1, "fytk": 550.0, "fyck": 550.0, "futk": 600.0, "eut": 0.05,
             "gamma_y": 1.0, "gamma_u": 1.0, "gamma_E": 1.0},
        "Curve 2 (elastic-perfectly-plastic)":
            {"curve": 2, "fytk": 500.0, "fyck": 500.0, "eut": 0.05, "gamma_y": 1.0},
        # ey0c (the second yield's total compression strain) must exceed the
        # first compression yield strain k*fytk/ES (~0.00248 here); otherwise the
        # second-yield branch is skipped and the compression curve jumps.
        "Curve 3 (two yield points)":
            {"curve": 3, "fytk": 550.0, "fyck": 550.0, "futk": 600.0, "eut": 0.05,
             "gamma_y": 1.0, "gamma_u": 1.0, "gamma_E": 1.0,
             "k": 0.9, "ey0t": 0.002, "ey0c": 0.005},
    }
    # Eurocode editions: curve 1 with an un-factored modulus (gamma_E = 1) and a
    # flat post-yield branch (futk = fyk, gamma_u = gamma_s) and no strain limit
    # -- EC2's design diagram (see sector.codes).
    for label, code in codes.CODES.items():
        presets[label] = {
            "curve": 1, "fytk": _DEFAULT_FYK, "fyck": _DEFAULT_FYK,
            "futk": _DEFAULT_FYK, "eut": _NO_STRAIN_LIMIT,
            "gamma_y": code.gamma_s, "gamma_u": code.gamma_s, "gamma_E": 1.0,
        }
    return presets


MILD_PRESETS = _mild_presets()

MILD_FIELD_META = {
    "fytk": ("fytk (MPa)", 100.0, 800.0, 10.0),
    "fyck": ("fyck (MPa)", 100.0, 800.0, 10.0),
    "futk": ("futk (MPa)", 100.0, 1000.0, 10.0),
    "eut": ("eut (strain)", 0.001, 1.0, 0.005),
    "gamma_y": ("gamma_y", 1.0, 1.5, 0.01),
    "gamma_u": ("gamma_u", 1.0, 1.5, 0.01),
    "gamma_E": ("gamma_E", 0.8, 1.5, 0.01),
    "k": ("k (f1 / fytk)", 0.5, 1.0, 0.01),
    "ey0t": ("ey0t (strain)", 0.0, 0.05, 0.001),
    "ey0c": ("ey0c (strain)", 0.0, 0.05, 0.001),
}

MILD_FIELDS_BY_CURVE = {
    1: ["fytk", "fyck", "futk", "eut", "gamma_y", "gamma_u", "gamma_E"],
    2: ["fytk", "fyck", "eut", "gamma_y"],
    3: ["fytk", "fyck", "futk", "eut", "gamma_y", "gamma_u", "gamma_E",
        "k", "ey0t", "ey0c"],
}


def build_mild(curve, **fields) -> MildSteel:
    """Build a :class:`~sector.materials.MildSteel` from the panel parameters."""
    curve = int(curve)
    used = {f: float(fields[f]) for f in MILD_FIELDS_BY_CURVE[curve] if f in fields}
    return MildSteel(curve=curve, **used)


# ---------------------------------------------------------------------------
# Prestressing steel (tendons)
# ---------------------------------------------------------------------------

def _prestress_presets():
    presets = {}
    # The built-in characteristic curves: only the prestrain and partial factor.
    for n in (1, 2, 3, 4, 5):
        presets["Curve %d (built-in)" % n] = {"curve": n, "IS": 0.0059,
                                              "gamma_y": 1.1}
    presets["Curve 6 (bilinear)"] = {
        "curve": 6, "IS": 0.0059, "fytk": 1600.0, "futk": 1860.0, "eut": 0.035,
        "gamma_y": 1.1, "gamma_u": 1.1, "gamma_E": 1.0}
    presets["Curve 7 (two yield)"] = {
        "curve": 7, "IS": 0.0059, "fytk": 1600.0, "futk": 1860.0, "eut": 0.035,
        "k": 0.9, "ey0t": 0.002, "gamma_y": 1.1, "gamma_u": 1.1, "gamma_E": 1.0}
    # Eurocode editions: a bilinear (curve 6) design diagram, fpd = fp0,1k/gamma_s,
    # default values for a Y1860 strand. Ep is 195 GPa for 2005 / the DK NA and
    # 200 GPa for 2023 -- expressed through gamma_E since the engine modulus is
    # 200 GPa (ES / gamma_E).
    for label, code in codes.CODES.items():
        ep_gpa = 200.0 if code.key == "EC2-2023" else 195.0
        presets[label] = {
            "curve": 6, "IS": 0.0, "fytk": 1640.0, "futk": 1860.0, "eut": 0.035,
            "gamma_y": code.gamma_s, "gamma_u": code.gamma_s,
            "gamma_E": round(200.0 / ep_gpa, 4)}
    return presets


PRESTRESS_PRESETS = _prestress_presets()

PRESTRESS_FIELD_META = {
    "IS": ("Prestrain IS (strain)", 0.0, 0.02, 0.0005),
    "fytk": ("fp0.1k (MPa)", 100.0, 2000.0, 10.0),
    "futk": ("fpk (MPa)", 100.0, 2200.0, 10.0),
    "eut": ("eut (strain)", 0.001, 0.1, 0.001),
    "gamma_y": ("gamma_y", 1.0, 1.5, 0.01),
    "gamma_u": ("gamma_u", 1.0, 1.5, 0.01),
    "gamma_E": ("gamma_E", 0.8, 1.5, 0.01),
    "k": ("k (f1 / fp0.1k)", 0.5, 1.0, 0.01),
    "ey0t": ("ey0t (strain)", 0.0, 0.05, 0.001),
}

PRESTRESS_FIELDS_BY_CURVE = {
    1: ["IS", "gamma_y"], 2: ["IS", "gamma_y"], 3: ["IS", "gamma_y"],
    4: ["IS", "gamma_y"], 5: ["IS", "gamma_y"],
    6: ["IS", "fytk", "futk", "eut", "gamma_y", "gamma_u", "gamma_E"],
    7: ["IS", "fytk", "futk", "eut", "k", "ey0t", "gamma_y", "gamma_u", "gamma_E"],
}


def build_prestress(curve, **fields) -> Prestress:
    """Build a :class:`~sector.materials.Prestress` from the panel parameters."""
    curve = int(curve)
    used = {f: float(fields[f]) for f in PRESTRESS_FIELDS_BY_CURVE[curve] if f in fields}
    return Prestress(curve=curve, **used)
