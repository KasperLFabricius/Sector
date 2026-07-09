"""Combined bending + shear + torsion (M-V-T) interaction checks.

Sector computes each action's resistance separately (the plastic M-M envelope, the
shear ``VRd``, the torsion ``TRd``); the combined check ties them together under one
consistent code edition.

Two interaction rules are provided:

* Concrete-strut crushing (EN 1992-1-1 6.3.2(4), Expression 6.29):
  ``TEd/TRd,max + VEd/VRd,max <= 1`` -- shear and torsion crush the same web struts,
  evaluated at a common strut angle.
* The DK NA:2024 general combined rule (6.3.2(6)): ``sum(SEd/SRd) <= 1`` over the
  acting sectional forces, each ``SRd`` the resistance to that force acting alone.
  When the longitudinal reinforcement provided for shear (beyond what bending needs)
  is present, ``M`` and ``V`` are not summed simultaneously; instead two independent
  checks are made (``M`` with ``T``, and ``V`` with ``T``) and the governing one
  taken. The axial force ``N`` is folded into the bending utilisation ``r_m`` (the
  plastic M-M envelope is traced at the applied ``N``), so it is not summed again.
"""

from __future__ import annotations

import math


def ratio(demand: float, resistance: float) -> float:
    """Utilisation ``demand / resistance``; ``inf`` when a demand has no resistance."""
    if resistance > 0.0:
        return demand / resistance
    return math.inf if demand > 0.0 else 0.0


def crushing_interaction(t_ed: float, trd_max: float, v_ed: float,
                         vrd_max: float) -> float:
    """EN 1992-1-1 (6.29): ``TEd/TRd,max + VEd/VRd,max``."""
    return ratio(t_ed, trd_max) + ratio(v_ed, vrd_max)


def dkna_sum(r_m: float, r_v: float, r_t: float, *, m_v_independent: bool) -> float:
    """DK NA:2024 6.3.2(6) ``sum(SEd/SRd)``, the governing value.

    ``r_m`` / ``r_v`` / ``r_t`` are the bending / shear / torsion utilisations (each
    the demand over the resistance to that action alone; ``N`` is folded into
    ``r_m``). With ``m_v_independent`` the bending and shear terms are not added
    together -- the governing of ``(r_m + r_t)`` and ``(r_v + r_t)`` is returned --
    otherwise all three are summed.
    """
    if m_v_independent:
        return max(r_m + r_t, r_v + r_t)
    return r_m + r_v + r_t
