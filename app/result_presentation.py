"""Shared result-presentation helpers for the Streamlit UI and PDF report.

The functions in this module format retained results and reconstruct the current
operands needed to verify their publication authority. They do not replace or
alter the retained engineering results.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
import dataclasses
import functools
import html
import math
from numbers import Real
import pickle
import sys
import threading

import case_analysis
import fatigue_presentation
import load_cases
import viz

from app import engineer_messages
from app import modelled_direction
from sector import capacity, codes, combined as combined_core
from sector import geometry as section_geometry
from sector import shear as shear_core
from sector.design_standards import get_design_basis
from sector.engineer_message import EngineerMessage

_DEGREE = chr(0x00B0)
_THETA = chr(0x03B8)
_RHO = chr(0x03C1)
_THETA_DISPLAY_ABS_TOL_DEG = 5.0e-2

_SINGLE_CASE_ID = "__single__"
_MISSING = object()
_PUBLICATION_SOLVES = ContextVar("publication_solves", default=None)


@dataclasses.dataclass
class _PublicationSolveScope:
    thread_id: int
    cache: dict
    live: bool = True


@contextmanager
def publication_calculation_scope():
    """Reuse identical pure solves only within one publication evaluation.

    Every retained operand is still reconciled on every call. Nested consumers
    share this synchronous evaluation's cache. Independent calls and threads,
    including copied thread contexts, start fresh.
    """
    active = _PUBLICATION_SOLVES.get()
    if active is not None and active.live and active.thread_id == threading.get_ident():
        yield
        return
    owner = _PublicationSolveScope(threading.get_ident(), {})
    token = _PUBLICATION_SOLVES.set(owner)
    try:
        yield
    finally:
        owner.live = False
        owner.cache.clear()
        _PUBLICATION_SOLVES.reset(token)


def _publication_key_bytes(args, kwargs):
    """Key supported Section/material values and standard case-table state."""
    import numpy as np
    from pandas import DataFrame, Index, NA, RangeIndex, StringDtype
    from sector.materials import Concrete, MildSteel, Prestress
    from sector.section import Bar, Section

    # Retain traversed objects: temporary table lists must not have their ids
    # recycled while this traversal is still checking later custom state.
    seen = {}

    def supported_dtype(dtype):
        if isinstance(dtype, np.dtype):
            return dtype.metadata is None and dtype.fields is None and dtype.kind in "biufcOUS"
        if type(dtype) is StringDtype:
            return dtype.storage in {"python", "pyarrow"} and supported(dtype.na_value)
        return False

    def supported(value):
        if value is NA:
            return True
        kind = type(value)
        if kind in {type(None), bool, int, float, str, bytes}:
            return True
        if id(value) in seen:
            return True
        seen[id(value)] = value
        if kind is dict:
            return all(supported(key) and supported(item) for key, item in value.items())
        if kind in {list, tuple}:
            return all(supported(item) for item in value)
        if kind in {Bar, Section, Concrete, MildSteel, Prestress}:
            return supported(vars(value))
        if kind is np.ndarray:
            return supported_dtype(value.dtype) and (
                not value.dtype.hasobject or supported(value.tolist())
            )
        if isinstance(value, np.generic) and kind.__module__ == "numpy":
            return supported(value.item())
        if kind is DataFrame:
            if type(value._metadata) is not list or value._metadata:
                return False
            if not all(type(axis) in {Index, RangeIndex} for axis in (value.index, value.columns)):
                return False
            if not all(supported_dtype(dtype) for dtype in (
                value.index.dtype, value.columns.dtype, *value.dtypes,
            )):
                return False
            return all(supported(item) for item in (
                value.attrs, list(value.index), list(value.columns),
                list(value.index.names), list(value.columns.names),
                value.to_numpy().tolist(),
            ))
        return False

    if not supported((args, kwargs)):
        raise TypeError("publication solve input has custom or unsupported state")
    return pickle.dumps((args, kwargs), protocol=5)


def _publication_solver_result(solver, *args, **kwargs):
    active = _PUBLICATION_SOLVES.get()
    if active is None or not active.live or active.thread_id != threading.get_ident():
        return solver(*args, **kwargs)
    cache = active.cache

    def current_key():
        plastic_module = sys.modules.get("sector.plastic")
        return (
            solver, capacity.conditional_capacity, capacity.plastic_capacity_at_angle,
            getattr(plastic_module, "conditional_capacity", None),
            getattr(plastic_module, "plastic_capacity_at_angle", None),
            _publication_key_bytes(args, kwargs),
        )

    try:
        # Include the entire typed input, not a selected field list or object
        # identity. Encoding only: these bytes are never deserialized.
        key = current_key()
    except Exception:
        # Unsupported input objects retain the original calculation behavior.
        return solver(*args, **kwargs)
    if key in cache:
        return cache[key]
    result = solver(*args, **kwargs)
    try:
        unchanged = current_key() == key
    except Exception:
        unchanged = False
    # The two supported helpers return immutable scalar pairs. Do not expose
    # a shared mutable return if a caller supplies a different solver seam.
    immutable_pair = type(result) is tuple and len(result) == 2 and all(
        type(value) in {float, bool, str, type(None)} for value in result
    )
    if unchanged and immutable_pair:
        cache[key] = result
    return result

_PLASTIC_ACTION_SET_REQUIRED = EngineerMessage(
    "PLASTIC-ACTION-SET",
    "Enter a Plastic action-set ID before calculating",
)
_ELASTIC_ACTION_SET_REQUIRED = EngineerMessage(
    "ELASTIC-ACTION-SET",
    "Enter an Elastic action-set ID before calculating",
)
_RESULT_REASON_FALLBACKS = {
    "plastic": EngineerMessage(
        "PLASTIC-RESULT-DETAIL",
        "Review the Plastic capacity envelope and applied actions",
    ),
    "minimum_reinforcement": EngineerMessage(
        "MINIMUM-REINFORCEMENT-DETAIL",
        "Review the minimum-reinforcement inputs and result status",
    ),
    "transverse_reinforcement": EngineerMessage(
        "TRANSVERSE-REINFORCEMENT-DETAIL",
        "Review the shear and torsion link-detailing inputs and result status",
    ),
    "shear": EngineerMessage(
        "SHEAR-RESULT-DETAIL",
        "Review the shear inputs and result status",
    ),
    "torsion": EngineerMessage(
        "TORSION-RESULT-DETAIL",
        "Review the torsion inputs and result status",
    ),
    "combined": EngineerMessage(
        "COMBINED-RESULT-DETAIL",
        "Review the combined M-V-T prerequisites and result status",
    ),
    "crack": EngineerMessage(
        "CRACK-RESULT-DETAIL",
        "Review the crack-width inputs and calculation status",
    ),
    "fatigue": EngineerMessage(
        "FATIGUE-RESULT-DETAIL",
        "Review the fatigue inputs and result status",
    ),
    "generic": EngineerMessage(
        "RESULT-DETAIL",
        "Review the calculation inputs and result status",
    ),
}
_PLASTIC_REASON_MESSAGES = {
    "M-M envelope coordinates are malformed or non-finite": EngineerMessage(
        "PLASTIC-ENVELOPE-COORDINATES",
        "The M-M capacity envelope contains an invalid coordinate; review the section inputs",
    ),
    "M-M envelope is self-intersecting, self-touching, or self-overlapping": EngineerMessage(
        "PLASTIC-ENVELOPE-TOPOLOGY",
        "The M-M capacity envelope does not form one valid closed boundary",
    ),
    "Global moment origin lies outside the closed M-M envelope": EngineerMessage(
        "PLASTIC-ENVELOPE-ORIGIN",
        "The closed M-M capacity envelope does not contain the zero-moment origin",
    ),
    "Applied moment components are non-finite": EngineerMessage(
        "PLASTIC-APPLIED-MOMENT",
        "Enter finite applied bending moments Mx,Ed and My,Ed",
    ),
    "Collapsed M-M envelope resistance is not finite and positive": EngineerMessage(
        "PLASTIC-COLLAPSED-ENVELOPE",
        "The collapsed M-M capacity envelope has no positive finite resistance",
    ),
    "No admissible positive M-M envelope intersection in the applied direction": EngineerMessage(
        "PLASTIC-ENVELOPE-INTERSECTION",
        "The applied moment direction has no admissible positive M-M capacity intersection",
    ),
    "Initial M-M envelope crossing interval is not numerically resolvable": EngineerMessage(
        "PLASTIC-INITIAL-CROSSING",
        "The initial M-M capacity-envelope crossing could not be resolved",
    ),
    "Applied ray initially leaves the admissible M-M envelope": EngineerMessage(
        "PLASTIC-APPLIED-RAY",
        "The applied moment ray immediately leaves the admissible M-M capacity envelope",
    ),
    "M-M envelope crossing interval is not numerically resolvable": EngineerMessage(
        "PLASTIC-CROSSING",
        "The governing M-M capacity-envelope crossing could not be resolved",
    ),
    "No verified inside-to-outside M-M envelope crossing in the applied direction": EngineerMessage(
        "PLASTIC-VERIFIED-CROSSING",
        "No verified M-M capacity-envelope boundary was found in the applied direction",
    ),
    "M-M envelope intersection is not finite and positive": EngineerMessage(
        "PLASTIC-FINITE-INTERSECTION",
        "The governing M-M capacity intersection is not positive and finite",
    ),
}
_MINIMUM_REINFORCEMENT_REASON_MESSAGES = {
    "No ordinary reinforcement bar lies in the tension zone.": EngineerMessage(
        "MINIMUM-REINFORCEMENT-TENSION-ZONE",
        "No ordinary reinforcement bar lies in the tension zone.",
    ),
    (
        "nominal resistance is too close to the cracking demand for a stable "
        "assessment at the available angular resolution"
    ): EngineerMessage(
        "MINIMUM-REINFORCEMENT-ANGULAR-RESOLUTION",
        "The nominal resistance is too close to the cracking demand for a stable "
        "assessment; assess this case separately",
    ),
    "nominal governing interval could not be refined consistently": EngineerMessage(
        "MINIMUM-REINFORCEMENT-GOVERNING-DIRECTION",
        "The governing nominal resistance direction could not be refined "
        "consistently; assess this case separately",
    ),
}
_TRANSVERSE_REASON_MESSAGES = {
    "minimum shear reinforcement is required for this beam": EngineerMessage(
        "TRANSVERSE-MINIMUM-LINKS",
        "Provide the minimum shear reinforcement required for this beam",
    ),
    "shear resistance without links is insufficient": EngineerMessage(
        "TRANSVERSE-LINKS-REQUIRED",
        "Provide shear links because the resistance without links is insufficient",
    ),
    "shear resistance without links is invalid": EngineerMessage(
        "TRANSVERSE-SHEAR-INVALID",
        "Review the shear resistance without links before assessing link detailing",
    ),
    "effective depth is unavailable for the 2023 minimum-link applicability check": EngineerMessage(
        "TRANSVERSE-EFFECTIVE-DEPTH",
        "Provide a valid effective depth for the 2023 minimum-link applicability check",
    ),
    "no active shear or torsion action requiring link-detailing checks": EngineerMessage(
        "TRANSVERSE-NOT-APPLICABLE",
        "No active shear or torsion action requires a link-detailing check",
    ),
    "gross web breadth exceeds the spacing limit; enter the actual maximum centre-to-centre leg spacing for a definitive assessment": EngineerMessage(
        "TRANSVERSE-LEG-SPACING",
        "Enter the actual maximum centre-to-centre leg spacing for a definitive assessment",
    ),
}
_SHEAR_REASON_MESSAGES = {
    "Enter a positive finite number of effective link legs for each active "
    "shear direction": EngineerMessage(
        "SHEAR-LINK-LEGS",
        "Enter a positive finite number of effective link legs for each active "
        "shear direction",
    ),
    "selected strut-angle range is outside the permitted method range": EngineerMessage(
        "SHEAR-STRUT-ANGLE-RANGE",
        "The entered compression-strut range is outside the permitted range for "
        "the selected method; restore the entered limits to the permitted band or "
        "use a separately substantiated applicable method",
    ),
    "stirrups (VRd,s)": EngineerMessage(
        "SHEAR-GOVERNS-STIRRUPS",
        "stirrups (VRd,s)",
    ),
    "crushing (VRd,max)": EngineerMessage(
        "SHEAR-GOVERNS-CRUSHING",
        "crushing (VRd,max)",
    ),
    "links (tau_Rd,sy)": EngineerMessage(
        "SHEAR-GOVERNS-LINK-YIELD",
        "link-yield resistance governs",
    ),
    "compression field (sigma_cd)": EngineerMessage(
        "SHEAR-GOVERNS-COMPRESSION-FIELD",
        "concrete compression-field resistance governs",
    ),
    "the calculated face-aligned arm is unavailable": EngineerMessage(
        "SHEAR-LINK-ARM",
        "The face-aligned lever arm is unavailable; review the Plastic result and link inputs",
    ),
    "no shear check": EngineerMessage(
        "SHEAR-NOT-REQUESTED",
        "No shear calculation is available for this direction",
    ),
    "zero resistance": EngineerMessage(
        "SHEAR-ZERO-RESISTANCE",
        "The calculated shear resistance is zero",
    ),
    "exact calculated plastic lever arm z is unavailable": EngineerMessage(
        "SHEAR-LINK-ARM-UNAVAILABLE",
        "Calculate a valid Plastic lever arm before assessing the shear links",
    ),
    "invalid reinforced-shear input": EngineerMessage(
        "SHEAR-LINK-INPUT",
        "Review the reinforced-shear geometry, link reinforcement, and material inputs",
    ),
    "provided-link resistance evidence is unavailable": EngineerMessage(
        "SHEAR-LINK-RESISTANCE-EVIDENCE",
        "Recalculate the reinforced-shear check before relying on the provided-link resistance",
    ),
    "provided-link input evidence is unavailable": EngineerMessage(
        "SHEAR-LINK-INPUT-EVIDENCE",
        "Recalculate the reinforced-shear check after confirming the current method, link, angle and section inputs",
    ),
    "provided-link concrete evidence is unavailable": EngineerMessage(
        "SHEAR-LINK-CONCRETE-EVIDENCE",
        "Recalculate the reinforced-shear check after confirming the concrete strength and design factors",
    ),
    "provided-link material evidence is unavailable": EngineerMessage(
        "SHEAR-LINK-MATERIAL-EVIDENCE",
        "Recalculate the reinforced-shear check after confirming the reinforcement strength and design factor",
    ),
    "calculated link lever-arm evidence is unavailable": EngineerMessage(
        "SHEAR-LINK-ARM-EVIDENCE",
        "Recalculate the reinforced-shear check after confirming the governing Plastic action set and lever arm",
    ),
    "retained shear action evidence is unavailable": EngineerMessage(
        "SHEAR-ACTION-EVIDENCE",
        "Recalculate the applied shear action and resistance before relying on this result",
    ),
    "the governing shear section geometry was not established": EngineerMessage(
        "SHEAR-SECTION-GEOMETRY",
        "Select the shear section form and enter the governing web geometry for this direction",
    ),
    "the variable-width shear geometry was not established": EngineerMessage(
        "SHEAR-VARIABLE-WIDTH",
        "Enter the governing web width and reinforcement inclination for the variable-width section",
    ),
    "the circular shear geometry was not established": EngineerMessage(
        "SHEAR-CIRCULAR-GEOMETRY",
        "Enter the governing web width, hoop diameter and fitted-section lever arm for the circular section",
    ),
    "the selected shear method does not assess this section form": EngineerMessage(
        "SHEAR-SECTION-METHOD",
        "Use a separately applicable member calculation for this section form and selected shear method",
    ),
    "the web-duct geometry was not established": EngineerMessage(
        "SHEAR-DUCT-GEOMETRY",
        "Enter the duct type and outer diameters at the most unfavourable web level",
    ),
    "the nominal web width is not positive": EngineerMessage(
        "SHEAR-NOMINAL-WIDTH",
        "Revise the web and duct geometry so the nominal web width remains positive",
    ),
    "2023 axial-compression applicability conditions were not demonstrated": EngineerMessage(
        "SHEAR-2023-AXIAL-COMPRESSION",
        "Net axial compression is present; this cross-section calculation does "
        "not establish the force assigned to the web or the action-state "
        "compression-chord depth needed to select the applicable 2023 route. "
        "Complete a member-level assessment, including Annex G where required",
    ),
    "reinforced-shear prerequisite was not assessed": EngineerMessage(
        "SHEAR-LINK-PREREQUISITE",
        "Complete the reinforced-shear calculation before assessing the combined check",
    ),
    "calculated plastic lever arm unavailable: section model is not available": EngineerMessage(
        "SHEAR-LINK-SECTION",
        "The calculated Plastic lever arm is unavailable because the section model is not available",
    ),
    "calculated plastic lever arm unavailable: the exact face-aligned Plastic solve did not converge": EngineerMessage(
        "SHEAR-LINK-CONVERGENCE",
        "The exact face-aligned Plastic calculation did not converge, so the link lever arm is unavailable",
    ),
    "calculated plastic lever arm unavailable: the face-aligned tension-compression resultant arm is zero or degenerate": EngineerMessage(
        "SHEAR-LINK-DEGENERATE",
        "The face-aligned tension-compression resultant arm is zero or degenerate, so the link lever arm is unavailable",
    ),
    "required_longitudinal_chord_failed": EngineerMessage(
        "SHEAR-LONGITUDINAL-CHORD-FAIL",
        "One or more required longitudinal chords exceed the calculated conditional bending resistance",
    ),
    "required_longitudinal_chord_coverage_incomplete": EngineerMessage(
        "SHEAR-LONGITUDINAL-CHORD-COVERAGE",
        "Complete both required longitudinal chord checks before relying on the shear assessment",
    ),
    "required_longitudinal_chords_satisfied": EngineerMessage(
        "SHEAR-LONGITUDINAL-CHORD-PASS",
        "The required longitudinal chords are within the calculated conditional bending resistances",
    ),
    "no_longitudinal_chord_action": EngineerMessage(
        "SHEAR-LONGITUDINAL-CHORD-NO-ACTION",
        "No longitudinal chord action requires assessment",
    ),
}
_TORSION_REASON_MESSAGES = {
    "torsion design basis not established": EngineerMessage(
        "TORSION-BASIS-NOT-ESTABLISHED",
        "Select whether the entered torsion is equilibrium torsion or a deliberately retained compatibility-torsion design action",
    ),
    "compatibility torsion requires member or system assessment": EngineerMessage(
        "TORSION-COMPATIBILITY-MEMBER-ASSESSMENT",
        "Compatibility torsion requires a separate member or system assessment before a sectional resistance verdict can be given",
    ),
    "torsion member scope not established": EngineerMessage(
        "TORSION-MEMBER-SCOPE-NOT-ESTABLISHED",
        "Confirm that the section is closed or solid and that warping torsion does not govern, or use an applicable member assessment",
    ),
    "open or warping-sensitive torsion requires member analysis": EngineerMessage(
        "TORSION-WARPING-MEMBER-ASSESSMENT",
        "Open thin-walled or warping-sensitive sections require a separate member assessment before a sectional resistance verdict can be given",
    ),
    "selected strut-angle range is outside the permitted method range": EngineerMessage(
        "TORSION-STRUT-ANGLE-RANGE",
        "The entered compression-strut range is outside the permitted range for "
        "the selected torsion method; restore the entered limits to the permitted "
        "band or use a separately substantiated applicable method",
    ),
    "stirrups (TRd,s)": EngineerMessage(
        "TORSION-GOVERNS-STIRRUPS",
        "stirrups (TRd,s)",
    ),
    "crushing (TRd,max)": EngineerMessage(
        "TORSION-GOVERNS-CRUSHING",
        "crushing (TRd,max)",
    ),
    "closed_links_not_present": EngineerMessage(
        "TORSION-CLOSED-LINKS",
        "Closed torsion links are required before the transverse/strut resistance component can be assessed",
    ),
    "closed_link_reinforcement_not_positive": EngineerMessage(
        "TORSION-LINK-AREA",
        "Enter a positive closed-link reinforcement area before assessing torsion resistance",
    ),
    "full torsion resistance not assessed": EngineerMessage(
        "TORSION-NOT-ASSESSED",
        "The torsion transverse/strut resistance component has not been assessed",
    ),
    "torsion tube evidence is invalid": EngineerMessage(
        "TORSION-TUBE-INVALID",
        "The equivalent torsion tube is invalid; review the section geometry and torsion inputs",
    ),
    "torsion result is invalid": EngineerMessage(
        "TORSION-RESULT-INVALID",
        "The torsion result is invalid; review the section geometry and torsion inputs",
    ),
    "torsion_resistance_exceeded": EngineerMessage(
        "TORSION-RESISTANCE-EXCEEDED",
        "The applied torsion exceeds the calculated transverse-steel or concrete-strut resistance",
    ),
    "longitudinal_torsion_reinforcement_evidence_unavailable": EngineerMessage(
        "TORSION-LONGITUDINAL-EVIDENCE",
        "Complete the torsion resistance calculation and the passive-bar material assignments before assessing the longitudinal reinforcement",
    ),
    "combined_longitudinal_evidence_inconsistent": EngineerMessage(
        "TORSION-LONGITUDINAL-RECALCULATE",
        "Recalculate the longitudinal torsion reinforcement assessment before relying on its status",
    ),
    "longitudinal_torsion_reinforcement_insufficient": EngineerMessage(
        "TORSION-LONGITUDINAL-INSUFFICIENT",
        "The total design tensile resistance of the modelled passive bars is below the Formula (6.28) longitudinal torsion demand",
    ),
    "longitudinal_torsion_reinforcement_not_verified": EngineerMessage(
        "TORSION-LONGITUDINAL-NOT-VERIFIED",
        "Verify that sufficient passive reinforcement remains beyond bending demand, is distributed around every torsion-tube side and is anchored along the member",
    ),
    "no_longitudinal_torsion_demand": EngineerMessage(
        "TORSION-LONGITUDINAL-ZERO",
        "No longitudinal torsion reinforcement is required for this zero-torsion result",
    ),
    "multi-cell (2+ voids)": EngineerMessage(
        "TORSION-MULTI-CELL",
        "The section contains multiple cells; subdivide it into single-cell torsion tubes",
    ),
    "compound outline requires subdivision": EngineerMessage(
        "TORSION-SUBDIVISION",
        "The compound outline requires subdivision before torsion can be assessed",
    ),
    "degenerate outline": EngineerMessage(
        "TORSION-DEGENERATE-OUTLINE",
        "The section outline cannot form a valid equivalent torsion tube",
    ),
    "wall exceeds section": EngineerMessage(
        "TORSION-WALL-THICKNESS",
        "The equivalent torsion-tube wall thickness exceeds the section geometry",
    ),
    "no outline": EngineerMessage(
        "TORSION-NO-OUTLINE",
        "A valid section outline is required for the torsion calculation",
    ),
    "torsion wall reinforcement locations are missing": EngineerMessage(
        "TORSION-WALL-BARS-MISSING",
        "Torsion is not assessed because longitudinal reinforcement locations are required around every equivalent-tube wall",
    ),
    "torsion wall reinforcement locations are invalid": EngineerMessage(
        "TORSION-WALL-BARS-INVALID",
        "Torsion is not assessed because one or more longitudinal reinforcement locations cannot be used for the equivalent-tube walls",
    ),
    "torsion wall reinforcement mapping is incomplete": EngineerMessage(
        "TORSION-WALL-BARS-INCOMPLETE",
        "Torsion is not assessed because longitudinal reinforcement has not been established for every equivalent-tube wall",
    ),
    "torsion wall reinforcement mapping is ambiguous": EngineerMessage(
        "TORSION-WALL-BARS-AMBIGUOUS",
        "Torsion is not assessed because the longitudinal reinforcement cannot be assigned unambiguously to every equivalent-tube wall",
    ),
    "torsion sub-tube reinforcement locations are missing": EngineerMessage(
        "TORSION-SUBTUBE-BARS-MISSING",
        "Torsion is not assessed because each sub-tube needs longitudinal reinforcement locations around all four walls",
    ),
    "torsion sub-tube reinforcement locations are invalid": EngineerMessage(
        "TORSION-SUBTUBE-BARS-INVALID",
        "Torsion is not assessed because one or more longitudinal reinforcement locations cannot be used for the sub-tubes",
    ),
    "torsion sub-tube reinforcement mapping is incomplete": EngineerMessage(
        "TORSION-SUBTUBE-BARS-INCOMPLETE",
        "Torsion is not assessed because longitudinal reinforcement has not been established for every sub-tube wall",
    ),
    "torsion sub-tube reinforcement assignment is ambiguous": EngineerMessage(
        "TORSION-SUBTUBE-BARS-AMBIGUOUS",
        "Torsion is not assessed because reinforcement on a shared sub-tube boundary cannot be assigned unambiguously",
    ),
    "torsion wall lower bound exceeds real wall": EngineerMessage(
        "TORSION-WALL-INTERVAL",
        "Torsion is not assessed because the reinforcement-based wall-thickness lower bound exceeds the available hollow wall",
    ),
    "torsion wall automatic thickness varies by wall": EngineerMessage(
        "TORSION-WALL-VARIATION",
        "Torsion is not assessed because the wall-specific limits do not support one automatic equivalent-tube thickness",
    ),
    "torsion wall override is below reinforcement lower bound": EngineerMessage(
        "TORSION-WALL-OVERRIDE-LOW",
        "Torsion is not assessed because the entered wall thickness is below the reinforcement-based lower bound",
    ),
    "torsion wall override exceeds real wall": EngineerMessage(
        "TORSION-WALL-OVERRIDE-HIGH",
        "Torsion is not assessed because the entered wall thickness exceeds an available hollow wall",
    ),
}

_TORSION_WALL_APPLICABILITY_REASONS = frozenset(
    reason for reason in _TORSION_REASON_MESSAGES if reason.startswith("torsion wall")
) | frozenset(
    reason
    for reason in _TORSION_REASON_MESSAGES
    if reason.startswith("torsion sub-tube reinforcement")
) | frozenset({
    "torsion design basis not established",
    "compatibility torsion requires member or system assessment",
    "torsion member scope not established",
    "open or warping-sensitive torsion requires member analysis",
})
_COMBINED_REASON_MESSAGES = {
    "selected strut-angle range is outside the permitted method range": EngineerMessage(
        "COMBINED-STRUT-ANGLE-RANGE",
        "The entered compression-strut range is outside the common permitted "
        "range; restore the entered limits to the permitted band or use a "
        "separately substantiated applicable method",
    ),
    "no evaluable shared angle": EngineerMessage(
        "COMBINED-SHARED-ANGLE",
        "No common strut angle could be evaluated for the combined M-V-T check",
    ),
    "shared member-angle calculation is invalid": EngineerMessage(
        "COMBINED-MEMBER-ANGLE",
        "The common member-angle calculation is invalid; review the shear and torsion prerequisites",
    ),
    "Combined calculation is invalid": EngineerMessage(
        "COMBINED-INVALID",
        "The combined M-V-T calculation is invalid; review its prerequisites",
    ),
    "combined_longitudinal_evidence_inconsistent": EngineerMessage(
        "COMBINED-LONGITUDINAL-EVIDENCE",
        "Recalculate the combined longitudinal reinforcement assessment before relying on its status",
    ),
    "combined_longitudinal_pure_axis_substitute": EngineerMessage(
        "COMBINED-LONGITUDINAL-SUBSTITUTE",
        "A required chord face uses a pure-axis substitute; complete its conditional resistance calculation before relying on the longitudinal assessment",
    ),
    "combined_longitudinal_shear_axis_unavailable": EngineerMessage(
        "COMBINED-LONGITUDINAL-SHEAR-AXIS",
        "No valid shear-axis longitudinal chord check is available; complete the required face calculations and recalculate",
    ),
    "combined_longitudinal_chord_not_solved": EngineerMessage(
        "COMBINED-LONGITUDINAL-NOT-SOLVED",
        "One or more torsion-tensioned longitudinal chord faces were not solved; complete every required face calculation and recalculate",
    ),
    "combined_longitudinal_subdivided_coverage": EngineerMessage(
        "COMBINED-LONGITUDINAL-SUBDIVIDED",
        "The subdivided section does not have complete longitudinal chord coverage; complete the required tube-wall assessment before relying on the result",
    ),
}
_CRACK_REASON_MESSAGES = {
    "Crack-width calculation was not requested for this Elastic case.": EngineerMessage(
        "CRACK-NOT-REQUESTED",
        "Crack-width calculation was not requested for this Elastic case",
    ),
    "The crack-width criterion must be a non-negative finite number.": EngineerMessage(
        "CRACK-LIMIT-NUMBER",
        "Enter a non-negative finite crack-width limit",
    ),
    "The user-specified crack-width criterion requires a nonblank criterion source.": EngineerMessage(
        "CRACK-LIMIT-SOURCE",
        "Enter the source of the user-specified crack-width limit",
    ),
    "No calculated crack width is available for assessment.": EngineerMessage(
        "CRACK-NO-RESULT",
        "No calculated crack width is available; review the Elastic case and crack-width inputs",
    ),
    "The long-term permitted crack width is 0 mm; no comparison was requested.": EngineerMessage(
        "CRACK-LONG-NO-COMPARISON",
        "The long-term crack width is reported without comparison because its limit is 0 mm",
    ),
    "The short-term permitted crack width is 0 mm; no comparison was requested.": EngineerMessage(
        "CRACK-SHORT-NO-COMPARISON",
        "The short-term crack width is reported without comparison because its limit is 0 mm",
    ),
    "The calculated crack width must be expressed in millimetres before comparison with the user-specified criterion.": EngineerMessage(
        "CRACK-RESULT-UNIT",
        "Express the calculated crack width in millimetres before comparing it with the limit",
    ),
    "The calculated crack width is within the user-specified limit.": EngineerMessage(
        "CRACK-WITHIN-LIMIT",
        "The calculated crack width is within the user-specified limit",
    ),
    "The calculated crack width exceeds the user-specified limit.": EngineerMessage(
        "CRACK-EXCEEDS-LIMIT",
        "The calculated crack width exceeds the user-specified limit",
    ),
    "Crack width was not requested for this run.": EngineerMessage(
        "CRACK-RUN-NOT-REQUESTED",
        "Crack width was not requested for this run.",
    ),
    "The selected action state is outside the validated ordinary crack-width scope.": EngineerMessage(
        "CRACK-ACTION-STATE-SCOPE",
        "The selected action state is outside the validated ordinary crack-width scope.",
    ),
    "Move every tendon far enough inside the physical top and bottom slab faces to provide non-negative clear cover before relying on crack-width results.": EngineerMessage(
        "CRACK-SLAB-TENDON-COVER",
        "Move every tendon far enough inside the physical top and bottom slab faces to provide non-negative clear cover before relying on crack-width results.",
    ),
    "Section uncracked; no width is available.": EngineerMessage(
        "CRACK-SECTION-UNCRACKED",
        "Section uncracked; no width is available.",
    ),
}
_FATIGUE_REASON_MESSAGES = {
    "No simplified fatigue-screen result is available": EngineerMessage(
        "FATIGUE-SCREEN-UNAVAILABLE",
        "No simplified fatigue-screen result is available",
    ),
    "No supported simplified fatigue rule is assigned": EngineerMessage(
        "FATIGUE-SCREEN-RULE",
        "No supported simplified fatigue rule is assigned to this detail",
    ),
    "Custom/imported fatigue details are not assigned a simplified limit": EngineerMessage(
        "FATIGUE-SCREEN-CUSTOM",
        "Custom fatigue details are not assigned a simplified stress-range limit",
    ),
    "Named fatigue detail does not belong to the selected design basis": EngineerMessage(
        "FATIGUE-SCREEN-DESIGN-BASIS",
        "The selected fatigue detail does not belong to the selected design basis",
    ),
    "The calculated cycle total is not finite": EngineerMessage(
        "FATIGUE-SCREEN-CYCLES",
        "The calculated fatigue cycle total is not finite",
    ),
    "One or more fatigue bins did not converge": EngineerMessage(
        "FATIGUE-SCREEN-CONVERGENCE",
        "One or more fatigue bins did not converge",
    ),
    "The calculated stress-range data are invalid": EngineerMessage(
        "FATIGUE-SCREEN-RANGE",
        "The calculated fatigue stress-range data are invalid",
    ),
    "The calculated stress ranges do not match the endpoint stresses": EngineerMessage(
        "FATIGUE-SCREEN-ENDPOINTS",
        "The calculated fatigue stress ranges do not match the endpoint stresses",
    ),
    "At least one fatigue bin has no tensile endpoint": EngineerMessage(
        "FATIGUE-SCREEN-TENSION",
        "At least one fatigue bin has no tensile stress endpoint",
    ),
    "Stress range is within the supported simplified limit": EngineerMessage(
        "FATIGUE-SCREEN-PASS",
        "The governing stress range is within the supported simplified limit",
    ),
    "Stress range exceeds the shortcut limit; detailed assessment governs": EngineerMessage(
        "FATIGUE-SCREEN-DETAILED",
        "The governing stress range exceeds the simplified limit; use the detailed assessment",
    ),
    "DS/EN 1992-1-1 6.8.6 shortcut covers unwelded or welded reinforcing bars in tension": EngineerMessage(
        "FATIGUE-FIRST-GENERATION-SCOPE",
        "DS/EN 1992-1-1 6.8.6 shortcut covers unwelded or welded reinforcing bars in tension",
    ),
    "DS/EN 1992-1-1:2023 10.4 does not assign this preset a simplified limit": EngineerMessage(
        "FATIGUE-PUBLISHED-2023-SCOPE",
        "DS/EN 1992-1-1:2023 10.4 does not assign this preset a simplified limit",
    ),
}
_RESULT_REASON_MESSAGES = {
    "plastic": _PLASTIC_REASON_MESSAGES,
    "minimum_reinforcement": _MINIMUM_REINFORCEMENT_REASON_MESSAGES,
    "transverse_reinforcement": _TRANSVERSE_REASON_MESSAGES,
    "shear": _SHEAR_REASON_MESSAGES,
    "torsion": _TORSION_REASON_MESSAGES,
    "combined": _COMBINED_REASON_MESSAGES,
    "crack": _CRACK_REASON_MESSAGES,
    "fatigue": _FATIGUE_REASON_MESSAGES,
}


def result_reason(value, family: str, *, context: str | None = None) -> str:
    """Publish one retained result reason only through positive provenance."""

    selected_family = family if family in _RESULT_REASON_FALLBACKS else "generic"
    return engineer_messages.resolve_state(
        value,
        authored=_RESULT_REASON_MESSAGES.get(selected_family, {}),
        fallback=_RESULT_REASON_FALLBACKS[selected_family],
        context=context or f"{selected_family} retained result reason",
    ).text

GOVERNING_OVERVIEW_STATUS_PRECEDENCE = (
    "INVALID",
    "FAIL",
    "EXCEEDS USER-SPECIFIED LIMIT",
    "PROVIDED AREA BELOW CALCULATED REQUIREMENT",
    "STALE",
    "REVIEW",
    "NOT ASSESSED",
    "CONDITIONAL",
    "CALCULATED - NO LIMIT COMPARISON",
    "PASS",
    "WITHIN USER-SPECIFIED LIMIT",
    "PROVIDED AREA AT LEAST CALCULATED REQUIREMENT",
    "CALCULATED",
    "NOT RUN",
    "NOT CALCULATED",
    "NOT APPLICABLE",
    "NOT REQUESTED",
)
_GOVERNING_OVERVIEW_STATUS_RANK = {
    status: rank
    for rank, status in enumerate(GOVERNING_OVERVIEW_STATUS_PRECEDENCE)
}
GOVERNING_OVERVIEW_INFORMATION_STATUSES = frozenset({
    "NOT RUN",
    "NOT CALCULATED",
    "NOT APPLICABLE",
    "NOT REQUESTED",
})


def is_boolean_scalar(value):
    """Return whether a retained scalar is a built-in or NumPy Boolean."""

    value_type = type(value)
    return isinstance(value, bool) or (
        value_type.__module__ == "numpy"
        and value_type.__name__ in {"bool", "bool_"}
    )


def _publication_metric(value, *, allow_positive_infinity=False):
    """Return one eligible retained publication-ranking metric."""
    if value is None:
        return None
    if is_boolean_scalar(value) or not isinstance(value, Real):
        return None
    try:
        metric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if math.isfinite(metric):
        return metric
    if allow_positive_infinity and metric == math.inf:
        return metric
    return None


def _publication_utilisation(value, *, allow_positive_infinity=False):
    """Return one strict, non-negative retained utilisation scalar."""

    metric = _publication_metric(
        value,
        allow_positive_infinity=allow_positive_infinity,
    )
    if metric is None or metric < 0.0:
        return None
    return metric


def _publication_cases(out, family, *, inp=None, current_only=False):
    """Return ordered named-case result payloads for one analysis family."""

    if current_only and inp is not None:
        return [
            (case_id, case_out)
            for case_id, _case_input, case_out, current in (
                _worked_case_contexts(inp, out, family)
            )
            if current
        ]
    entries = (out or {}).get(f"{family}_cases")
    if entries is None:
        return [(_SINGLE_CASE_ID, out or {})]
    cases = []
    for entry in entries:
        name = str(entry.get("name") or (entry.get("actions") or {}).get("name") or "")
        if name:
            cases.append((name, entry.get("results") or {}))
    return cases


def plastic_result_predates_origin_contract(result):
    """Return whether a checked closed result lacks the radial-validity contract."""

    return (
        result.get("util_valid") is None
        and bool(result.get("check_util", True))
        and bool(result.get("closed", True))
    )


def combined_bending_assessment_blocker(results, inp=None):
    """Return why retained combined evidence cannot trust a prerequisite."""

    results = results or {}
    combined = results.get("combined")
    torsion = results.get("torsion")
    scope_note = combined_publication_scope_note(combined)
    if scope_note is not None:
        return scope_note
    if (
        combined is not None
        and isinstance(torsion, Mapping)
        and (
            applicability_status := torsion_applicability_publication_status(
                torsion
            )
        ) is not None
        and applicability_status != "APPLICABLE"
    ):
        return (
            "Torsion prerequisite is not assessed: "
            + torsion_applicability_note(torsion)
        )
    if (
        combined is not None
        and isinstance(torsion, Mapping)
        and (
            "tube_valid" in torsion
            or "full_resistance_assessed" in torsion
        )
    ):
        if torsion.get("tube_valid") is not True:
            reason = result_reason(
                torsion.get("reason") or "torsion tube evidence is invalid",
                "torsion",
                context="combined prerequisite torsion-tube reason",
            )
        elif (
            "closed_links_present" in torsion
            and torsion.get("closed_links_present") is not True
        ):
            reason = result_reason(
                torsion.get("assessment_reason")
                or "closed_links_not_present",
                "torsion",
                context="combined prerequisite closed-links reason",
            )
        elif torsion.get("full_resistance_assessed") is not True:
            reason = result_reason(
                torsion.get("assessment_reason")
                or torsion.get("reason")
                or "full torsion resistance not assessed",
                "torsion",
                context="combined prerequisite torsion-assessment reason",
            )
        elif torsion.get("valid") is not True:
            reason = result_reason(
                torsion.get("reason") or "torsion result is invalid",
                "torsion",
                context="combined prerequisite torsion-result reason",
            )
        else:
            reason = ""
        if reason:
            return "Torsion prerequisite is not assessed: " + reason
    plastic = results.get("plastic")
    if (
        results.get("combined") is not None
        and isinstance(plastic, Mapping)
        and plastic_result_predates_origin_contract(plastic)
    ):
        return (
            "The saved bending result cannot confirm that the M-M envelope "
            "contains the origin. Recalculate before assessing M-V-T interaction."
        )
    if (
        combined is not None
        and inp is not None
        and combined_publication_evidence_is_current(inp, results)[0]
        is not True
    ):
        return (
            "Combined component evidence is not current. Recalculate the "
            "shear, torsion and M-V-T checks."
        )
    return None


def combined_dkna_screen_label(result):
    """Return the public inclusion rule for one retained DK NA result."""

    return (
        "max(N+M+T, N+V+T)"
        if (result or {}).get("m_v_independent") is True
        else "N+M+V+T"
    )


def combined_uses_dkna(result):
    """Return whether one retained/input combined method is the Danish edition."""

    if not isinstance(result, Mapping):
        return False
    method = str(result.get("method") or "")
    if method:
        return method in {codes.EC2_2005_DKNA.label, "DK NA"}
    directions = result.get("directions")
    if isinstance(directions, Mapping) and any(
        combined_uses_dkna(item) for item in directions.values()
    ):
        return True
    # Compatibility for retained pre-contract report fixtures. Current Base-EN
    # results always carry an explicit method and therefore never enter this path.
    return any(
        key in result
        for key in (
            "dkna_sum",
            "dkna_valid",
            "dkna_selection",
            "action_alone",
            "m_v_separation_condition",
        )
    )


def base_en_combined_direction_items(result):
    """Return both required Base-EN biaxial direction records, or fail closed.

    A biaxial retained result is publication-complete only when both independent
    Vx+T and Vy+T payloads carry the current Base-EN direction contract.  Merely
    being a mapping is insufficient: an empty or stale record must not let the
    surviving direction become a governing worked example.
    """

    if not isinstance(result, Mapping) or result.get("biaxial") is not True:
        return None
    directions = result.get("directions")
    if not isinstance(directions, Mapping):
        return None
    items = []
    for component in ("vx", "vy"):
        item = directions.get(component)
        if (
            not isinstance(item, Mapping)
            or type(item.get("valid")) is not bool
            or item.get("method") != codes.EC2_2005.label
        ):
            return None
        if item["valid"]:
            transverse = item.get("transverse")
            if (
                not isinstance(transverse, Mapping)
                or type(transverse.get("valid")) is not bool
                or not any(
                    isinstance(item.get(key), Mapping)
                    for key in (
                        "longitudinal",
                        "governing_longitudinal",
                        "longitudinal_assessment",
                    )
                )
            ):
                return None
        elif not (
            any(key in item for key in ("have_m", "have_v", "have_t"))
            or bool(item.get("reason"))
            or "torsion_assessment_status" in item
        ):
            return None
        items.append((component, item))
    return tuple(items)


def combined_dkna_limit_satisfied(result):
    """Return the numerical limit comparison without promoting its authority."""

    result = result or {}
    utilisation = _publication_metric(result.get("dkna_sum"))
    if utilisation is None:
        return None
    calculated = viz.util_ok(utilisation)
    retained = result.get("dkna_limit_satisfied")
    if type(retained) is bool:
        return retained and calculated
    return calculated


def combined_dkna_status(result):
    """Return the fail-closed public state of one retained DK NA screen."""

    result = result or {}
    torsion_status = str(
        result.get("torsion_assessment_status") or ""
    ).upper()
    chord_assessment = result.get("longitudinal_assessment")
    chord_status = (
        str(chord_assessment.get("status") or "").upper()
        if isinstance(chord_assessment, Mapping)
        else ""
    )
    if torsion_status == "FAIL":
        return "FAIL"
    if chord_status == "FAIL":
        return "FAIL"
    valid = result.get("valid") is True
    dkna_valid = result.get("dkna_valid", valid) is True
    if not valid or not dkna_valid:
        return "NOT ASSESSED"
    satisfied = combined_dkna_limit_satisfied(result)
    if satisfied is None:
        return "NOT ASSESSED"
    if not satisfied:
        return "FAIL"
    if torsion_status and torsion_status != "PASS":
        return "NOT ASSESSED"
    if chord_status and chord_status != "PASS":
        return "NOT ASSESSED"
    if result.get("m_v_independent") is True:
        return "CONDITIONAL"
    retained = str(result.get("dkna_status") or "").upper()
    return retained if retained in {"PASS", "FAIL"} else "PASS"


def combined_torsion_assessment_note(result):
    """Explain a torsion prerequisite that governs the combined result."""

    result = result or {}
    status = str(result.get("torsion_assessment_status") or "").upper()
    if status not in {"FAIL", "NOT ASSESSED"}:
        return ""
    reason = result_reason(
        result.get("torsion_assessment_reason")
        or "longitudinal_torsion_reinforcement_not_verified",
        "torsion",
        context="combined torsion prerequisite reason",
    )
    return f"{status}: {reason}."


def combined_torsion_governing_note(result):
    """Explain how the torsion prerequisite and DK NA limit govern together."""

    torsion_note = combined_torsion_assessment_note(result)
    if not torsion_note:
        return ""
    if combined_dkna_limit_satisfied(result) is False:
        return (
            "FAIL: The DK NA action-alone sum exceeds its numerical limit; "
            "this definite combined failure governs. "
            + torsion_note
        )
    return (
        torsion_note
        + " The DK NA action-alone sum remains numerical component evidence; "
          "it is not an overall M-V-T verdict."
    )


def combined_longitudinal_chord_assessment_note(result):
    """Explain a required longitudinal-chord state governing M-V-T."""

    assessment = (result or {}).get("longitudinal_assessment")
    if not isinstance(assessment, Mapping):
        return ""
    status = str(assessment.get("status") or "").upper()
    if status not in {"FAIL", "NOT ASSESSED"}:
        return ""
    reason = result_reason(
        assessment.get("reason")
        or "required_longitudinal_chord_coverage_incomplete",
        "shear",
        context="combined longitudinal chord prerequisite reason",
    )
    return f"{status}: {reason}."


def combined_governing_assessment_note(result):
    """Explain every physical prerequisite that governs the M-V-T status."""

    torsion_note = combined_torsion_assessment_note(result)
    chord_note = combined_longitudinal_chord_assessment_note(result)
    if torsion_note and not chord_note:
        return combined_torsion_governing_note(result)
    notes = " ".join(filter(None, (torsion_note, chord_note)))
    if not notes:
        return ""
    if combined_dkna_limit_satisfied(result) is False:
        return (
            "FAIL: The DK NA action-alone sum exceeds its numerical limit; "
            "this definite combined failure governs. "
            + notes
        )
    return (
        notes
        + " The DK NA action-alone sum remains numerical component evidence; "
          "it is not an overall M-V-T verdict."
    )


def combined_dkna_assumption_note(result):
    """Return concise engineer guidance for the assumption-only separate route."""

    if (result or {}).get("m_v_independent") is not True:
        return ""
    satisfied = combined_dkna_limit_satisfied(result)
    if satisfied is False:
        return (
            "FAIL: the governing sum exceeds the numerical limit even under the "
            "favourable separate M/V design assumption. The ordinary simultaneous "
            "sum cannot be smaller, so the failed numerical check governs regardless "
            "of that assumption."
        )
    if satisfied is None:
        return (
            "NOT ASSESSED: no numerical limit comparison is available for the "
            "separate M/V design assumption. Check the section, actions and "
            "action-alone resistances, then recalculate."
        )
    return (
        "CONDITIONAL: the separate M/V route is a design assumption that additional "
        "shear longitudinal reinforcement beyond bending is provided. The governing sum "
        "is within the numerical limit under that assumption. Verify the reinforcement area, "
        "distribution and anchorage separately."
    )


def shear_link_arm_publication_provenance(inp, shear_result):
    """Bind a retained links arm to the current Plastic action and face."""

    unavailable = {
        "valid": False,
        "component": None,
        "angle_deg": None,
        "case_id": None,
        "axial_kn": None,
        "source": None,
        "reason": "calculated link lever-arm evidence is unavailable",
    }
    if not isinstance(inp, Mapping) or not isinstance(shear_result, Mapping):
        return unavailable
    links = shear_result.get("links")
    if not isinstance(links, Mapping):
        return unavailable
    link_result = links.get("res")
    geometry = links.get("shear_geometry") or shear_result.get("shear_geometry")
    if not isinstance(link_result, Mapping) or not isinstance(geometry, Mapping):
        return unavailable
    if geometry.get("resolved_form") == "Circular section":
        if links.get("z_source") != "circular_fitted_section":
            return unavailable
        return {
            **unavailable,
            "valid": True,
            "source": "circular_fitted_section",
            "reason": None,
        }

    axis = shear_result.get("axis")
    tension_low = shear_result.get("tension_low")
    if type(axis) is not str or axis not in {"x", "y"} or type(tension_low) is not bool:
        return unavailable
    expected_component = "z_y" if axis == "x" else "z_x"
    expected_angle = {
        ("x", True): 90.0,
        ("x", False): -90.0,
        ("y", True): 0.0,
        ("y", False): 180.0,
    }[(axis, tension_low)]
    plastic_case = inp.get("plastic_case")
    expected_case = (
        str(plastic_case.get("id") or "").strip()
        if isinstance(plastic_case, Mapping)
        else ""
    )
    input_axial = _publication_metric(inp.get("P_pl"))
    result_axial = _publication_metric(shear_result.get("n_ed"))
    retained_axial = _publication_metric(links.get("z_source_axial_kn"))
    retained_angle = _publication_metric(links.get("z_source_angle_deg"))
    retained_case = links.get("z_source_case")
    angular_delta = (
        None
        if retained_angle is None
        else (retained_angle - expected_angle) % 360.0
    )
    angle_matches = bool(
        angular_delta is not None
        and (
            math.isclose(angular_delta, 0.0, rel_tol=0.0, abs_tol=1.0e-9)
            or math.isclose(angular_delta, 360.0, rel_tol=0.0, abs_tol=1.0e-9)
        )
    )
    if (
        links.get("z_source") != "plastic internal lever arm"
        or links.get("z_component") != expected_component
        or type(retained_case) is not str
        or not expected_case
        or retained_case != expected_case
        or not angle_matches
        or input_axial is None
        or result_axial is None
        or retained_axial is None
    ):
        return unavailable
    if not (
        math.isclose(
            input_axial,
            result_axial,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        )
        and math.isclose(
            input_axial,
            retained_axial,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        )
    ):
        return unavailable
    return {
        "valid": True,
        "component": expected_component,
        "angle_deg": expected_angle,
        "case_id": expected_case,
        "axial_kn": input_axial,
        "source": "plastic internal lever arm",
        "reason": None,
    }


def _strict_current_directional_shear_specs(inp, unavailable_reason):
    """Return canonical current Vx/Vy records or fail closed.

    A named-case ``shear_components`` mapping is retained engineering evidence,
    not an alternative input authority.  When present, every alias must agree
    with the raw action and face controls before any directional result can be
    published.
    """

    if not isinstance(inp, Mapping):
        return None, unavailable_reason

    def finite_builtin(value):
        return type(value) in {int, float} and math.isfinite(float(value))

    raw_actions = {}
    for component, raw_key in (("vx", "shear_Vx"), ("vy", "shear_Vy")):
        value = inp.get(raw_key, 0.0)
        if not finite_builtin(value):
            return None, unavailable_reason
        raw_actions[component] = float(value)

    components = inp.get("shear_components")
    if "shear_components" in inp:
        if not isinstance(components, Mapping) or set(components) != {"vx", "vy"}:
            return None, unavailable_reason
        for component, axis, face_key in (
            ("vx", "y", "shear_face_x"),
            ("vy", "x", "shear_face_y"),
        ):
            record = components.get(component)
            if not isinstance(record, Mapping) or set(record) != {
                "signed_v_ed",
                "v_ed",
                "axis",
                "face",
                "active",
            }:
                return None, unavailable_reason
            signed = record.get("signed_v_ed")
            magnitude = record.get("v_ed")
            raw_face = inp.get(face_key, "auto")
            active = inp.get("shear_on") is True and abs(raw_actions[component]) > 0.0
            if (
                not finite_builtin(signed)
                or not finite_builtin(magnitude)
                or float(magnitude) < 0.0
                or not math.isclose(
                    float(magnitude),
                    abs(float(signed)),
                    rel_tol=1.0e-12,
                    abs_tol=1.0e-12,
                )
                or not math.isclose(
                    float(signed),
                    raw_actions[component],
                    rel_tol=1.0e-12,
                    abs_tol=1.0e-12,
                )
                or record.get("axis") != axis
                or type(raw_face) is not str
                or record.get("face") != raw_face
                or type(record.get("active")) is not bool
                or record.get("active") is not active
            ):
                return None, unavailable_reason

    for key in ("P_pl", "Mx_pl", "My_pl"):
        if not finite_builtin(inp.get(key)):
            return None, unavailable_reason
    try:
        specs = capacity.shear_direction_specs(inp)
    except (
        capacity.CapacityInputError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None, unavailable_reason
    return specs, None


def _current_shear_action_evidence(inp, shear_result, unavailable_reason):
    """Reconcile one retained shear direction, face and signed action."""

    if not isinstance(inp, Mapping) or not isinstance(shear_result, Mapping):
        return None, unavailable_reason
    if inp.get("shear_on") is not True:
        return None, unavailable_reason
    method = inp.get("shear_method")
    if (
        type(method) is not str
        or method not in capacity.SHEAR_METHODS
        or shear_result.get("method") != method
    ):
        return None, unavailable_reason
    code = capacity.SHEAR_METHODS[method]
    model_2023 = getattr(code, "shear_model", "2005") == "2023"
    if shear_result.get("model_2023") is not model_2023:
        return None, unavailable_reason

    axis = shear_result.get("axis")
    component = shear_result.get("component")
    tension_low = shear_result.get("tension_low")
    if (
        type(axis) is not str
        or axis not in {"x", "y"}
        or component not in {"vx", "vy"}
        or component != ("vy" if axis == "x" else "vx")
        or type(tension_low) is not bool
    ):
        return None, unavailable_reason

    directional = any(
        key in inp for key in ("shear_Vx", "shear_Vy", "shear_components")
    )
    try:
        if directional:
            specs, _spec_reason = _strict_current_directional_shear_specs(
                inp, unavailable_reason
            )
            if specs is None:
                return None, unavailable_reason
            spec = specs[component]
            expected_v = float(spec["v_ed"])
            expected_signed_v = float(spec["signed_v_ed"])
            expected_bw_override = float(spec["bw"])
            admissible_faces = capacity.shear_face_candidates(
                spec["face"], spec["moment"]
            )
            if axis != spec["axis"] or tension_low not in admissible_faces:
                return None, unavailable_reason
        else:
            if inp.get("shear_axis") != axis or inp.get("shear_tension") is not tension_low:
                return None, unavailable_reason
            expected_signed_v = float(inp.get("shear_V"))
            expected_v = abs(expected_signed_v)
            expected_bw_override = float(inp.get("shear_bw"))
            admissible_faces = (tension_low,)
    except (
        capacity.CapacityInputError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None, unavailable_reason
    if not all(
        math.isfinite(value)
        for value in (expected_v, expected_signed_v, expected_bw_override)
    ) or expected_v < 0.0 or expected_bw_override < 0.0:
        return None, unavailable_reason
    retained_v = _publication_metric(shear_result.get("v_ed"))
    retained_signed_v = capacity.validated_signed_shear_demand(shear_result)
    if (
        retained_v is None
        or retained_signed_v is None
        or not math.isclose(
            retained_v, abs(expected_v), rel_tol=1.0e-12, abs_tol=1.0e-12
        )
        or not math.isclose(
            retained_signed_v,
            expected_signed_v,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        )
    ):
        return None, unavailable_reason
    return {
        "method": method,
        "code": code,
        "model_2023": model_2023,
        "axis": axis,
        "component": component,
        "tension_low": tension_low,
        "directional": directional,
        "expected_v": expected_v,
        "expected_signed_v": expected_signed_v,
        "expected_bw_override": expected_bw_override,
        "admissible_faces": tuple(admissible_faces),
    }, None


def shear_publication_signed_demand(inp, shear_result):
    """Return the applied load only when its retained action matches the input.

    Demand remains useful when a resistance method is unavailable. It still
    requires the same method, direction, face and signed-action reconciliation
    used by the publication guards.
    """
    action, _reason = _current_shear_action_evidence(
        inp, shear_result, "retained shear action evidence is unavailable",
    )
    return None if action is None else action["expected_signed_v"]


def concrete_shear_publication_input_is_current(inp, shear_result):
    """Reconcile the retained concrete shear route to the current inputs.

    This boundary deliberately derives only the concrete-route authority.  It
    does not inspect the provided-links child, so malformed link evidence cannot
    manufacture or suppress an otherwise current concrete-only result.
    """

    unavailable_reason = "concrete shear input evidence is unavailable"
    action, _reason = _current_shear_action_evidence(
        inp, shear_result, unavailable_reason
    )
    if action is None:
        return False, unavailable_reason
    method = action["method"]
    code = action["code"]
    model_2023 = action["model_2023"]
    axis = action["axis"]
    component = action["component"]
    tension_low = action["tension_low"]
    directional = action["directional"]
    expected_v = action["expected_v"]
    expected_signed_v = action["expected_signed_v"]
    expected_bw_override = action["expected_bw_override"]
    admissible_faces = action["admissible_faces"]

    outer = inp.get("outer")
    holes = inp.get("holes") or ()
    bars = inp.get("bars")
    if (
        not isinstance(outer, (list, tuple))
        or not outer
        or not isinstance(bars, (list, tuple))
    ):
        return False, unavailable_reason
    try:
        area, cx, cy = capacity.gross_area_centroid(outer, holes)
        _, mx_prestress, my_prestress = capacity.prestress_resultants(inp, cx, cy)
        n_prestress = capacity.prestress_axial(inp)
        centroid_coord = cy if axis == "x" else cx
        asl, cg, asl_ids = shear_core.tension_reinforcement_selection(
            bars, axis, tension_low, centroid_coord
        )
        d_mm = shear_core.effective_depth(outer, axis, tension_low, cg)
        bw_auto = shear_core.min_web_width(outer, holes, axis)
        bw_mm = expected_bw_override if expected_bw_override > 0.0 else bw_auto
        concrete = inp.get("concrete")
        steel = inp.get("steel")
        fck = float(getattr(concrete, "fck"))
        fcd = float(getattr(concrete, "fcd"))
        gamma_c = float(getattr(concrete, "gamma_c"))
        fyd_flex = float(capacity.design_yield(steel))
        p_pl = float(inp.get("P_pl"))
        mx_pl = float(inp.get("Mx_pl"))
        my_pl = float(inp.get("My_pl"))
        n_ed_comp = -p_pl + n_prestress
        if axis == "x":
            moment_reference_shift = p_pl * cy - mx_prestress
            m_ed_2023 = mx_pl + moment_reference_shift
            m_prestress = mx_prestress
        else:
            moment_reference_shift = p_pl * cx - my_prestress
            m_ed_2023 = my_pl + moment_reference_shift
            m_prestress = my_prestress
        ddg = code.shear_ddg(fck, inp.get("shear_dlower")) if model_2023 else 0.0
        gamma_v = (
            shear_core.validate_gamma_v(inp.get("shear_gamma_v"), label="gamma_V")
            if model_2023
            else None
        )
        expected_geometry = shear_core.resolve_shear_geometry(
            model_2023=model_2023,
            solid_rectangle=section_geometry.section_is_approximately_solid_rectangle(
                outer, holes
            ),
            section_form=inp.get(
                "shear_section_form", shear_core.SHEAR_SECTION_AUTO
            ),
            bw_mm=bw_mm,
            bw_user=bool(expected_bw_override > 0.0),
            links_present=inp.get("shear_links") is True,
            web_inclination_deg=inp.get(
                f"shear_{component}_web_inclination_deg",
                inp.get("shear_web_inclination_deg", 0.0),
            ),
            hoop_diameter_mm=inp.get("shear_hoop_diameter", 0.0),
            fitted_z_mm=inp.get(
                f"shear_{component}_fitted_z", inp.get("shear_fitted_z", 0.0)
            ),
            duct_case=inp.get("shear_duct_case", shear_core.SHEAR_DUCT_NONE),
            duct_sum_mm=inp.get(
                f"shear_{component}_duct_sum", inp.get("shear_duct_sum", 0.0)
            ),
            duct_largest_mm=inp.get(
                f"shear_{component}_duct_largest",
                inp.get("shear_duct_largest", 0.0),
            ),
        )
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return False, unavailable_reason

    def values_match(retained, expected):
        if is_boolean_scalar(expected):
            return type(retained) is bool and retained is expected
        if isinstance(expected, Real):
            return bool(
                not is_boolean_scalar(retained)
                and isinstance(retained, Real)
                and math.isfinite(float(retained))
                and math.isfinite(float(expected))
                and math.isclose(
                    float(retained),
                    float(expected),
                    rel_tol=1.0e-12,
                    abs_tol=1.0e-12,
                )
            )
        if isinstance(expected, (tuple, list)):
            return bool(
                isinstance(retained, (tuple, list))
                and len(retained) == len(expected)
                and all(values_match(left, right) for left, right in zip(retained, expected))
            )
        if isinstance(expected, Mapping):
            return bool(
                isinstance(retained, Mapping)
                and set(retained) == set(expected)
                and all(
                    values_match(retained.get(key), value)
                    for key, value in expected.items()
                )
            )
        return retained == expected

    expected_top = {
        "component": component,
        "axis": axis,
        "tension_low": tension_low,
        "bw": bw_mm,
        "bw_auto": bw_auto,
        "bw_user": bool(expected_bw_override > 0.0),
        "d": d_mm,
        "asl": asl,
        "asl_bar_ids": asl_ids,
        "asl_cg": cg,
        "ac": area,
        "fck": fck,
        "n_ed": p_pl,
        "n_prestress": n_prestress,
        "n_ed_comp": n_ed_comp,
        "m_ed_2023": m_ed_2023,
        "moment_reference_shift": moment_reference_shift,
        "m_prestress": m_prestress,
        "centroid": (cx, cy),
        "method": method,
        "model_2023": model_2023,
        "ddg": ddg,
        "fyd_flex": fyd_flex,
    }
    if not all(
        values_match(shear_result.get(key), expected)
        for key, expected in expected_top.items()
    ):
        return False, unavailable_reason

    retained_result = shear_result.get("res")
    if not isinstance(retained_result, Mapping):
        return False, unavailable_reason
    expected_result = {
        "fck": fck,
        "bw": expected_geometry.get("concrete_bw_mm"),
        "d": d_mm,
        "asl": asl,
        "model": "2023" if model_2023 else "2005",
    }
    if model_2023:
        expected_result.update(
            fyd=fyd_flex,
            ddg=ddg,
            n_ed_tension=-n_ed_comp,
            m_ed=m_ed_2023,
            v_ed=expected_v,
            gamma_v=gamma_v,
        )
    else:
        expected_result.update(
            fcd=fcd,
            gamma_c=gamma_c,
            ac=area,
            n_ed_comp=n_ed_comp,
        )
    if not all(
        values_match(retained_result.get(key), expected)
        for key, expected in expected_result.items()
    ):
        return False, unavailable_reason

    try:
        expected_kernel = shear_core.vrd_c(
            fck,
            code,
            expected_geometry.get("concrete_bw_mm"),
            d_mm,
            asl,
            n_ed_comp,
            area,
            fyd_mpa=fyd_flex,
            ddg_mm=(ddg or 32.0),
            m_ed_knm=m_ed_2023,
            v_ed_kn=expected_v,
            fcd_mpa=fcd,
            gamma_c=gamma_c,
            gamma_v=gamma_v,
        )
    except (TypeError, ValueError, OverflowError):
        return False, unavailable_reason
    expected_resistance = _publication_metric(expected_kernel.get("vrd_c"))
    retained_utilisation = _publication_utilisation(shear_result.get("util"))
    if (
        expected_resistance is None
        or expected_resistance <= 0.0
        or retained_utilisation is None
        or not values_match(retained_result, expected_kernel)
        or not math.isclose(
            retained_utilisation,
            expected_v / expected_resistance,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        )
    ):
        return False, unavailable_reason

    retained_geometry = shear_result.get("shear_geometry")
    if not isinstance(retained_geometry, Mapping):
        return False, unavailable_reason
    concrete_geometry_keys = (
        "concrete_valid",
        "concrete_reason",
        "section_form",
        "resolved_form",
        "bw_mm",
        "concrete_bw_mm",
        "duct_case",
        "duct_sum_mm",
        "duct_largest_mm",
        "duct_factor_concrete",
        "duct_threshold_mm",
        "duct_reduction_applied_concrete",
    )
    if not all(
        values_match(retained_geometry.get(key), expected_geometry.get(key))
        for key in concrete_geometry_keys
    ):
        return False, unavailable_reason

    if directional:
        face_candidates = shear_result.get("face_candidates")
        if (
            not isinstance(face_candidates, list)
            or len(face_candidates) != len(admissible_faces)
            or shear_result.get("both_faces_evaluated")
            is not (len(admissible_faces) == 2)
        ):
            return False, unavailable_reason
        reconciled = []
        for expected_face in admissible_faces:
            matches = [
                candidate
                for candidate in face_candidates
                if isinstance(candidate, Mapping)
                and candidate.get("tension_low") is expected_face
            ]
            if len(matches) != 1:
                return False, unavailable_reason
            candidate = matches[0]
            candidate_shear = candidate.get("shear")
            if not isinstance(candidate_shear, Mapping):
                return False, unavailable_reason
            candidate_input = dict(inp)
            for key in ("shear_Vx", "shear_Vy", "shear_components"):
                candidate_input.pop(key, None)
            candidate_input.update(
                shear_axis=axis,
                shear_tension=expected_face,
                shear_V=expected_v,
                shear_bw=expected_bw_override,
            )
            if concrete_shear_publication_input_is_current(
                candidate_input, candidate_shear
            )[0] is not True:
                return False, unavailable_reason
            concrete_metric = _publication_utilisation(
                candidate_shear.get("util")
            )
            if concrete_metric is None:
                return False, unavailable_reason
            reconciled.append((candidate, concrete_metric))
        governing, _governing_metric = max(
            reconciled,
            key=lambda item: item[1],
        )
        retained_nominal = shear_result.get("nominal_resistance")
        concrete_is_nominal = bool(
            isinstance(retained_nominal, Mapping)
            and retained_nominal.get("valid") is True
            and retained_nominal.get("route") == "concrete"
        )
        if concrete_is_nominal and tension_low is not governing["tension_low"]:
            return False, unavailable_reason
    return True, None


def directional_shear_publication_evidence_is_current(
    inp,
    shear_result,
    *,
    plastic_result=None,
    include_companions=True,
):
    """Reconcile mandatory shear faces and the requested companion domains."""

    unavailable_reason = "face-specific shear evidence is unavailable"
    if not isinstance(inp, Mapping) or not isinstance(shear_result, Mapping):
        return False, unavailable_reason
    action, _reason = _current_shear_action_evidence(
        inp,
        shear_result,
        unavailable_reason,
    )
    if action is None:
        return False, unavailable_reason
    face_candidates = shear_result.get("face_candidates")
    if face_candidates is None:
        return True, None
    admissible_faces = action["admissible_faces"]
    if (
        not action["directional"]
        or not isinstance(face_candidates, list)
        or len(face_candidates) != len(admissible_faces)
    ):
        return False, unavailable_reason

    allowed_statuses = {
        "PASS",
        "FAIL",
        "NOT RUN",
        "NOT ASSESSED",
        "NOT APPLICABLE",
        "CONDITIONAL",
    }
    combined_available = not (
        isinstance(plastic_result, Mapping)
        and plastic_result_predates_origin_contract(plastic_result)
    )

    def summary_metric(value, *, allow_positive_infinity=False):
        metric = _publication_metric(value, allow_positive_infinity=allow_positive_infinity)
        return metric if metric is not None and metric >= 0.0 else None

    def candidate_input_for(face):
        return _current_shear_face_input(inp, action, face)

    def combined_state(
        candidate_input,
        candidate_shear,
        torsion,
        combined,
        current_transverse,
    ):
        if combined is None:
            return "NOT RUN", 0.0
        retained_transverse = combined.get("transverse")
        if current_transverse is None:
            if retained_transverse is not None:
                return None, None
        elif not _publication_mapping_contains_current(
            retained_transverse,
            current_transverse,
        ):
            return None, None
        rows = [
            row
            for row in result_summary_rows(
                candidate_input,
                {
                    "plastic": plastic_result,
                    "shear": candidate_shear,
                    "torsion": torsion,
                    "combined": combined,
                },
            )
            if row.get("view") == "M-V-T Combined"
        ]
        status = overall_summary_status(rows)
        metrics = []
        for row in rows:
            value = row.get("util")
            if value is None:
                continue
            longitudinal = capacity.combined_longitudinal_assessment(combined)
            infinite_chord_failure = bool(
                row.get("overview_key") == "combined:longitudinal"
                and row.get("status") == "FAIL"
                and longitudinal.get("chord_status") == "FAIL"
                and _has_valid_zero_capacity_chord_failure(longitudinal, "chord_util")
            )
            metric = summary_metric(value, allow_positive_infinity=infinite_chord_failure)
            if metric is None:
                return None, None
            metrics.append(metric)
        return status, max(metrics, default=0.0)

    reconciled = []
    for expected_face in admissible_faces:
        matches = [
            candidate
            for candidate in face_candidates
            if isinstance(candidate, Mapping)
            and candidate.get("tension_low") is expected_face
        ]
        if len(matches) != 1:
            return False, unavailable_reason
        candidate = matches[0]
        candidate_shear = candidate.get("shear")
        if not isinstance(candidate_shear, Mapping):
            return False, unavailable_reason
        torsion = candidate.get("torsion")
        candidate_input = candidate_input_for(expected_face)
        if concrete_shear_publication_input_is_current(
            candidate_input,
            candidate_shear,
        )[0] is not True:
            return False, unavailable_reason

        nominal = nominal_shear_resistance(
            candidate_shear,
            links_selected=inp.get("shear_links") is True,
            input_payload=candidate_input,
            torsion_result=torsion,
        )
        retained_links = capacity.provided_link_shear_assessment(
            candidate_shear
        )
        links = candidate_shear.get("links")
        if nominal.get("valid") is True:
            shear_status = nominal.get("status")
            shear_metric = summary_metric(nominal.get("utilisation"))
            if shear_status not in allowed_statuses or shear_metric is None:
                return False, unavailable_reason
            if inp.get("shear_links") is True and isinstance(links, Mapping):
                current_links = provided_link_publication_assessment(
                    candidate_input,
                    candidate_shear,
                    torsion_result=torsion,
                )
                longitudinal = provided_link_longitudinal_publication_assessment(
                    candidate_input,
                    candidate_shear,
                    torsion_result=torsion,
                )
                if current_links.valid is not True:
                    return False, unavailable_reason
                longitudinal_status = longitudinal.get("status")
                if longitudinal.get("valid") is not True:
                    # The complete native substitute inventory remains current
                    # context, with its original unavailable longitudinal verdict.
                    # Current links have already rebuilt every angle participant.
                    if _retained_fallback_angle_candidates(candidate_shear) is None:
                        return False, unavailable_reason
                    longitudinal_status = links["longitudinal_assessment"]["status"]
                if longitudinal_status != "NOT APPLICABLE":
                    shear_status = capacity.aggregate_assessment_status((
                        str(shear_status),
                        str(longitudinal_status),
                    ))
        else:
            shear_status = str(nominal.get("status") or "NOT ASSESSED").upper()
            if shear_status not in {"NOT ASSESSED", "INVALID"}:
                shear_status = "NOT ASSESSED"
            shear_metric = 0.0
            link_result = links.get("res") if isinstance(links, Mapping) else None
            if retained_links.valid is True or not isinstance(link_result, Mapping):
                return False, unavailable_reason
            if not all((
                link_result.get("valid") is False,
                link_result.get("calculation_state") == "NOT ASSESSED",
                link_result.get("vrd") is None,
                links.get("util") is None,
            )):
                return False, unavailable_reason

        expected_ok = (
            True
            if shear_status == "PASS"
            else False
            if shear_status == "FAIL"
            else None
        )
        if not all((
            candidate_shear.get("resistance_status") == nominal.get("status"),
            candidate_shear.get("assessment_status") == shear_status,
            candidate_shear.get("assessment_ok") is expected_ok,
            candidate.get("shear_status") == shear_status,
            summary_metric(candidate.get("shear_metric")) == shear_metric,
        )):
            return False, unavailable_reason

        if not include_companions:
            reconciled.append({
                "candidate": candidate,
                "shear_status": shear_status,
                "shear_metric": shear_metric,
            })
            continue

        torsion = candidate.get("torsion")
        current_children = None
        if torsion is None:
            torsion_status, torsion_metric = "NOT RUN", 0.0
            minimum_status, minimum_metric = "NOT RUN", 0.0
            detailing_status, detailing_scope_key = None, None
        elif isinstance(torsion, Mapping):
            current_children = _current_shear_torsion_children(
                candidate_input,
                candidate_shear,
                torsion,
            )
            if not isinstance(current_children, Mapping):
                return False, unavailable_reason
            interaction = torsion.get("interaction")
            current_interaction = current_children.get("interaction")
            if current_interaction is None:
                if interaction is not None:
                    return False, unavailable_reason
                torsion_status, torsion_metric = "NOT ASSESSED", 0.0
            else:
                if not _publication_mapping_contains_current(
                    interaction,
                    current_interaction,
                ):
                    return False, unavailable_reason
                torsion_status = interaction_assessment_status(
                    current_interaction
                )
                torsion_metric = summary_metric(
                    current_interaction.get("value")
                )
            minimum = torsion.get("min_reinf") or {}
            current_minimum = current_children.get("minimum_reinforcement")
            if not _publication_mapping_contains_current(
                minimum,
                current_minimum,
            ):
                return False, unavailable_reason
            minimum_status = minimum_reinforcement_screen_status(minimum)
            if minimum:
                detailing_status = minimum_reinforcement_detailing_status(minimum)
                detailing_scope_key = str(
                    minimum.get("detailing_scope_key") or ""
                ).strip()
                try:
                    expected_detailing = capacity.formula_631_detailing_state(
                        inp,
                        shear_result,
                        torsion,
                    )
                except (KeyError, TypeError, ValueError, OverflowError):
                    return False, unavailable_reason
                if (
                    detailing_status,
                    detailing_scope_key,
                ) != expected_detailing:
                    return False, unavailable_reason
            else:
                detailing_status, detailing_scope_key = None, None
            if not minimum.get("applicable"):
                minimum_metric = 0.0
            else:
                minimum_metric = summary_metric(current_minimum.get("value"))
            if torsion_metric is None or minimum_metric is None:
                return False, unavailable_reason
        else:
            return False, unavailable_reason

        combined = candidate.get("combined")
        if combined is not None and not isinstance(combined, Mapping):
            return False, unavailable_reason
        combined_status, combined_metric = None, None
        if combined_available:
            combined_status, combined_metric = combined_state(
                candidate_input,
                candidate_shear,
                torsion,
                combined,
                (
                    current_children.get("combined_transverse")
                    if isinstance(current_children, Mapping)
                    else None
                ),
            )
            if combined_status is None or combined_metric is None:
                return False, unavailable_reason
        expected_aliases = {
            "torsion": (torsion_status, torsion_metric),
            "min_reinf": (minimum_status, minimum_metric),
        }
        if combined_available:
            expected_aliases["combined"] = (combined_status, combined_metric)
        for prefix, (status, metric) in expected_aliases.items():
            if (
                status not in allowed_statuses
                or candidate.get(f"{prefix}_status") != status
                or summary_metric(
                    candidate.get(f"{prefix}_metric"),
                    allow_positive_infinity=(
                        prefix == "combined" and status == "FAIL" and metric == math.inf
                    ),
                ) != metric
            ):
                return False, unavailable_reason
        reconciled.append({
            "candidate": candidate,
            "shear_status": shear_status,
            "shear_metric": shear_metric,
            "torsion_status": torsion_status,
            "torsion_metric": torsion_metric,
            "minimum_status": minimum_status,
            "minimum_metric": minimum_metric,
            "detailing_status": detailing_status,
            "detailing_scope_key": detailing_scope_key,
            "combined_status": combined_status,
            "combined_metric": combined_metric,
        })

    domain_specs = {"shear": ("shear_status", "shear_metric", True)}
    if include_companions:
        domain_specs.update({
            "vt": (
                "torsion_status",
                "torsion_metric",
                any((item["candidate"].get("torsion") or {}).get("interaction") is not None
                    for item in reconciled),
            ),
            "minimum_reinforcement": (
                "minimum_status",
                "minimum_metric",
                any((item["candidate"].get("torsion") or {}).get("min_reinf") is not None
                    for item in reconciled),
            ),
            "combined": (
                "combined_status",
                "combined_metric",
                combined_available
                and any(item["candidate"].get("combined") is not None for item in reconciled),
            ),
        })
    expected_domains = {}
    for domain, (status_key, metric_key, active) in domain_specs.items():
        if not active:
            continue
        governing = max(
            reconciled,
            key=lambda item: capacity.assessment_key(
                item[status_key], item[metric_key]
            ),
        )
        aggregate = capacity.aggregate_assessment_status(
            item[status_key] for item in reconciled
        )
        candidate = governing["candidate"]
        if domain == "shear":
            cot = (((candidate.get("shear") or {}).get("links") or {}).get("res") or {}).get("cot")
        elif domain == "vt":
            cot = ((candidate.get("torsion") or {}).get("interaction") or {}).get("cot")
        elif domain == "combined":
            combined = candidate.get("combined") or {}
            transverse = combined.get("transverse") or {}
            cot = (
                transverse.get("cot")
                if transverse.get("valid") and transverse.get("cot") is not None
                else (combined.get("crushing") or {}).get("cot")
            )
        else:
            cot = None
        if cot is not None:
            cot = summary_metric(cot)
            if cot is None or cot <= 0.0:
                return False, unavailable_reason
        expected_domains[domain] = {
            "face": (
                "negative"
                if candidate.get("tension_low") is True
                else "positive"
            ),
            "cot": cot,
            "status": aggregate,
            "util": governing[metric_key],
        }
        if domain == "minimum_reinforcement":
            expected_domains[domain].update(
                detailing_status=governing["detailing_status"],
                detailing_scope_key=governing["detailing_scope_key"],
            )

    retained_domains = shear_result.get("governing_domains")
    if not isinstance(retained_domains, Mapping) or not set(retained_domains) <= {
        "shear", "vt", "minimum_reinforcement", "combined",
    }:
        return False, unavailable_reason
    checked_domains = set(retained_domains)
    if not include_companions:
        checked_domains &= {"shear"}
    elif not combined_available:
        checked_domains.discard("combined")
    if checked_domains != set(expected_domains):
        return False, unavailable_reason
    for key, expected in expected_domains.items():
        retained = retained_domains.get(key)
        if not isinstance(retained, Mapping) or set(retained) != set(expected):
            return False, unavailable_reason
        for field, value in expected.items():
            retained_value = retained.get(field)
            if isinstance(value, Real) and not is_boolean_scalar(value):
                if summary_metric(
                    retained_value,
                    allow_positive_infinity=(
                        key == "combined" and field == "util"
                        and expected["status"] == "FAIL" and value == math.inf
                    ),
                ) != float(value):
                    return False, unavailable_reason
            elif retained_value != value:
                return False, unavailable_reason

    shear_governing = max(
        reconciled,
        key=lambda item: capacity.assessment_key(
            item["shear_status"], item["shear_metric"]
        ),
    )
    expected_status = capacity.aggregate_assessment_status(
        item["shear_status"] for item in reconciled
    )
    face_key = "shear_face_x" if action["component"] == "vx" else "shear_face_y"
    if not all((
        shear_result.get("status") == expected_status,
        shear_result.get("governing_face") == (
            "negative"
            if shear_governing["candidate"].get("tension_low") is True
            else "positive"
        ),
        shear_result.get("face_mode") == str(inp.get(face_key, "auto")),
    )):
        return False, unavailable_reason
    return True, None


def _single_shear_publication_input_is_current(
    inp,
    shear_result,
    *,
    plastic_result=None,
    torsion_result=None,
):
    """Return whether any retained shear operands can be shown for this input.

    Retained-child corruption remains separate: a current concrete component may
    still be shown as context while a malformed links child is NOT ASSESSED.  A
    genuine current-input mismatch, however, suppresses the complete stale
    direction before any operands are published.
    """

    links = shear_result.get("links") if isinstance(shear_result, Mapping) else None
    link_result = links.get("res") if isinstance(links, Mapping) else None
    if (
        inp.get("shear_links") is True
        and isinstance(link_result, Mapping)
        and link_result.get("valid") is True
        and type(links.get("required")) is not bool
    ):
        return False, "provided-link resistance evidence is unavailable"

    if isinstance(shear_result, Mapping) and shear_result.get(
        "face_candidates"
    ) is not None:
        direction_current, direction_reason = (
            directional_shear_publication_evidence_is_current(
                inp,
                shear_result,
                plastic_result=plastic_result,
                include_companions=False,
            )
        )
        if direction_current is not True:
            concrete_current, concrete_reason = (
                concrete_shear_publication_input_is_current(inp, shear_result)
            )
            links = shear_result.get("links")
            provided = (
                provided_link_publication_assessment(
                    inp, shear_result, torsion_result=torsion_result,
                )
                if isinstance(links, Mapping)
                else None
            )
            if concrete_current is not True or (
                provided is not None and provided.valid is True
            ):
                return False, direction_reason or concrete_reason
            return True, None

    try:
        raw_selection = capacity.select_nominal_shear_resistance(
            shear_result,
            links_selected=inp.get("shear_links") is True,
        )
    except (capacity.CapacityInputError, TypeError, ValueError, OverflowError):
        return True, None
    if raw_selection.valid is True and raw_selection.route == "concrete":
        return concrete_shear_publication_input_is_current(inp, shear_result)
    if raw_selection.valid is not True:
        concrete = shear_result.get("res") if isinstance(shear_result, Mapping) else None
        if isinstance(concrete, Mapping) and concrete.get("valid") is True:
            concrete_current, reason = concrete_shear_publication_input_is_current(
                inp, shear_result
            )
            if concrete_current is not True:
                return False, reason
        return True, None
    retained_links = capacity.provided_link_shear_assessment(
        shear_result
    )
    if retained_links.valid is not True:
        return True, None
    current_links = provided_link_publication_assessment(
        inp, shear_result, torsion_result=torsion_result,
    )
    if current_links.valid is not True:
        return False, current_links.reason
    return True, None


def shear_publication_input_is_current(
    inp,
    shear_result,
    *,
    plastic_result=None,
    torsion_result=None,
    validate_directions=True,
):
    """Reconcile a complete shear family, including its directional wrapper."""

    unavailable_reason = "shear result evidence is unavailable"
    if not isinstance(inp, Mapping) or not isinstance(shear_result, Mapping):
        return False, unavailable_reason
    directional = any(
        key in inp for key in ("shear_Vx", "shear_Vy", "shear_components")
    )
    wrapper = any(
        key in shear_result for key in ("directions", "active_directions", "biaxial")
    )
    if not directional:
        if wrapper:
            return False, unavailable_reason
        return _single_shear_publication_input_is_current(
            inp,
            shear_result,
            plastic_result=plastic_result,
            torsion_result=torsion_result,
        )

    specs, _spec_reason = _strict_current_directional_shear_specs(
        inp,
        unavailable_reason,
    )
    if specs is None:
        return False, unavailable_reason
    expected_active = [
        component
        for component in ("vx", "vy")
        if inp.get("shear_on") is True and specs[component]["v_ed"] > 0.0
    ]
    if len(expected_active) == 2:
        directions = shear_result.get("directions")
        active = shear_result.get("active_directions")
        if (
            not wrapper
            or not isinstance(directions, Mapping)
            or set(directions) != set(expected_active)
            or type(active) is not list
            or active != expected_active
            or shear_result.get("biaxial") is not True
        ):
            return False, unavailable_reason
        for component in expected_active:
            child = directions.get(component)
            if not isinstance(child, Mapping):
                return False, unavailable_reason
            action, _reason = _current_shear_action_evidence(
                inp,
                child,
                unavailable_reason,
            )
            if action is None or action["component"] != component:
                return False, unavailable_reason
            if validate_directions and _single_shear_publication_input_is_current(
                inp,
                child,
                plastic_result=plastic_result,
                torsion_result=torsion_result,
            )[0] is not True:
                return False, unavailable_reason
        return True, None

    if wrapper or len(expected_active) != 1:
        return False, unavailable_reason
    action, _reason = _current_shear_action_evidence(
        inp,
        shear_result,
        unavailable_reason,
    )
    if action is None or action["component"] != expected_active[0]:
        return False, unavailable_reason
    return _single_shear_publication_input_is_current(
        inp,
        shear_result,
        plastic_result=plastic_result,
        torsion_result=torsion_result,
    )


def shear_direction_publication_input_is_current(
    inp,
    shear_result,
    *,
    plastic_result=None,
    torsion_result=None,
):
    """Reconcile one child after its complete directional wrapper was checked."""

    return _single_shear_publication_input_is_current(
        inp,
        shear_result,
        plastic_result=plastic_result,
        torsion_result=torsion_result,
    )


def _current_shear_face_input(inp, action, tension_low):
    """Reproduce the raw face kernel's magnitude after checking its signed parent."""
    candidate_input = dict(inp)
    for key in ("shear_Vx", "shear_Vy", "shear_components"):
        candidate_input.pop(key, None)
    direction = capacity.shear_direction_specs(inp)[action["component"]]
    candidate_input.update(
        shear_axis=action["axis"],
        shear_tension=tension_low,
        shear_V=action["expected_v"],
        shear_bw=action["expected_bw_override"],
        shear_link_legs=direction["legs"],
    )
    return candidate_input


def _current_shear_calculation_input(inp, shear_result):
    """Translate one retained direction onto the shared uniaxial kernel input."""

    action, _reason = _current_shear_action_evidence(
        inp,
        shear_result,
        "shear result evidence is unavailable",
    )
    if action is None:
        return None, None
    calculation_input = dict(inp)
    if action["directional"]:
        for key in ("shear_Vx", "shear_Vy", "shear_components"):
            calculation_input.pop(key, None)
        try:
            direction = capacity.shear_direction_specs(inp)[action["component"]]
        except (
            capacity.CapacityInputError,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
        ):
            return None, None
        calculation_input.update(
            shear_axis=action["axis"],
            shear_tension=action["tension_low"],
            shear_V=action["expected_v"],
            shear_bw=action["expected_bw_override"],
            shear_link_legs=direction["legs"],
        )
    return action, calculation_input


def _current_member_angle_selection(inp, shear_result, torsion_result):
    """Rebuild the exact current common-angle minimax selection."""

    if not isinstance(inp, Mapping) or not isinstance(shear_result, Mapping):
        return None
    links = shear_result.get("links")
    if not isinstance(links, Mapping):
        return None
    action, calculation_input = _current_shear_calculation_input(
        inp,
        shear_result,
    )
    if action is None or calculation_input is None:
        return None
    try:
        p_ed = float(calculation_input["P_pl"])
        n_prestress = capacity.prestress_axial(calculation_input)
        n_ed_comp = -p_ed + n_prestress
        _shear_payload, link_context = capacity.build_shear_context(
            calculation_input,
            n_prestress,
            n_ed_comp,
        )
        torsion_context = capacity.build_torsion_context(
            calculation_input,
            n_ed_comp,
        )
        link_context, torsion_context = capacity.shared_member_angle_contexts(
            calculation_input, link_context, torsion_context
        )
    except (
        capacity.CapacityInputError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None
    if not isinstance(link_context, Mapping):
        return None
    if (
        isinstance(torsion_context, Mapping)
        and torsion_context.get("applicability_blocked") is True
    ):
        torsion_context = None

    v_ed = _publication_metric(link_context.get("v_ed"))
    vrd_c = _publication_metric(link_context.get("vrd_c"))
    cot_min = _publication_metric(link_context.get("cot_min"))
    cot_max = _publication_metric(link_context.get("cot_max"))
    if (
        v_ed is None
        or cot_min is None
        or cot_max is None
        or cot_min <= 0.0
        or cot_max <= 0.0
    ):
        return None

    try:
        link_probe = link_context["build"](cot_min, cot_min)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    links_valid = bool(
        isinstance(link_probe, Mapping)
        and link_probe.get("valid") is True
        and _publication_metric(link_probe.get("vrd_s")) not in {None, 0.0}
        and _publication_metric(link_probe.get("vrd_max")) not in {None, 0.0}
    )
    torsion_geometry_valid = bool(
        isinstance(torsion_context, Mapping)
        and isinstance(torsion_context.get("subtubes"), (list, tuple))
        and torsion_context["subtubes"]
        and all(
            isinstance(tube, Mapping) and tube.get("valid") is True
            for tube in torsion_context["subtubes"]
        )
    )
    torsion_live = bool(
        torsion_geometry_valid
        and torsion_context.get("closed_links_present") is True
        and _publication_metric(torsion_context.get("asw_over_s_t")) not in {
            None,
            0.0,
        }
        and isinstance(torsion_context.get("angle_applicability"), Mapping)
        and torsion_context["angle_applicability"].get("applicable") is True
        and _publication_metric(torsion_context.get("t_ed")) not in {None, 0.0}
    )
    concrete_route_applicable = bool(
        vrd_c is not None and vrd_c > 0.0 and v_ed <= vrd_c
    )
    shear_live = bool(
        links_valid
        and v_ed > 0.0
        and (not concrete_route_applicable or torsion_live)
    )
    if not shear_live and not torsion_live:
        return None
    if links.get("theta_mode") != (
        "utilisation" if shear_live else "resistance"
    ):
        return None

    # Only the eligible participants set the band. Independently invalid shear
    # evidence cannot constrain a valid loaded torsion result.
    if not shear_live and torsion_live:
        cot_min = torsion_context["tcot_min"]
        cot_max = torsion_context["tcot_max"]

    @functools.lru_cache(maxsize=4096)
    def link_at(cot):
        return link_context["build"](cot, cot)

    @functools.lru_cache(maxsize=4096)
    def torsion_at(cot):
        if not torsion_geometry_valid:
            return ()
        kwargs = dict(
            torsion_context["_tk"],
            cot_min=cot,
            cot_max=cot,
        )
        return tuple(
            capacity.tube_torsion(tube, action, **kwargs)
            for tube, action in zip(
                torsion_context["subtubes"],
                torsion_context["ted_parts"],
                strict=True,
            )
        )

    objectives = []
    labels = []

    def add_objective(label, evaluator):
        labels.append(label)
        objectives.append(evaluator)

    if shear_live:
        add_objective(
            "shear link yielding",
            lambda cot: combined_core.ratio(v_ed, link_at(cot)["vrd_s"]),
        )
        add_objective(
            "shear strut crushing",
            lambda cot: combined_core.ratio(v_ed, link_at(cot)["vrd_max"]),
        )
    if torsion_live:
        for index in range(len(torsion_context["subtubes"])):
            add_objective(
                f"torsion sub-tube {index + 1}",
                lambda cot, index=index: torsion_at(cot)[index]["util"],
            )
    if links_valid and torsion_live:
        add_objective(
            "shared closed stirrup",
            lambda cot: (
                (0.0 if v_ed <= vrd_c else combined_core.ratio(
                    v_ed,
                    link_at(cot)["vrd_s"],
                ))
                + combined_core.ratio(
                    torsion_at(cot)[0]["t_ed"],
                    torsion_at(cot)[0]["trd_s"],
                )
            ),
        )
        add_objective(
            "shared shear-torsion strut",
            lambda cot: combined_core.crushing_interaction(
                torsion_at(cot)[0]["t_ed"],
                torsion_at(cot)[0]["trd_max"],
                v_ed,
                link_at(cot)["vrd_max"],
            ),
        )

    retained_chords = capacity.provided_link_longitudinal_publication_assessment(
        shear_result
    )
    candidates = retained_chords.get("candidates") or ()
    if links.get("longitudinal_fallback") is not None:
        # A preserved substitute is not verified longitudinal resistance. It was
        # nevertheless an input to the native provisional angle search. Rebuild
        # that same inventory without promoting the strict chord assessment.
        candidates = _retained_fallback_angle_candidates(shear_result)
        if candidates is None or not torsion_live or torsion_context.get("subdivide"):
            return None
    current_candidates = []
    for candidate in candidates:
        rebuilt = _current_link_chord_candidate(
            inp,
            shear_result,
            candidate,
            torsion_result=torsion_result,
        )
        if rebuilt is None:
            return None
        current_candidates.append((candidate, rebuilt))

    def torsion_force(cot):
        if not torsion_live:
            return 0.0
        primary = torsion_at(cot)[0]
        asl_req = _publication_metric(primary.get("asl_req"))
        fyd_long = _publication_metric(torsion_context.get("fyd_long"))
        if asl_req is None or fyd_long is None:
            return math.inf
        return asl_req * fyd_long / 1000.0

    model_2023 = links.get("model_2023") is True
    for candidate, rebuilt in current_candidates:
        if rebuilt["m_rd"] <= 0.0 or not (shear_live or torsion_live):
            continue
        role = candidate["role"]
        axis = candidate["axis"]
        tension_low = candidate["tension_low"]
        face = "negative" if tension_low else "positive"
        label = (
            f"{axis}-axis {face} longitudinal chord"
            if role == "shear_axis"
            else f"{axis}-axis {face} off-axis chord"
        )
        gets_shift = candidate.get("gets_shift") is True
        if model_2023 and role == "shear_axis":
            add_objective(
                label,
                lambda cot, candidate=candidate, rebuilt=rebuilt,
                gets_shift=gets_shift: (
                    combined_core.longitudinal_chord_check_2023(
                        rebuilt["m_ed_signed"],
                        rebuilt["m_rd"],
                        (
                            v_ed * cot
                            if shear_live and gets_shift
                            and not concrete_route_applicable
                            else 0.0
                        ),
                        torsion_force(cot),
                        rebuilt["z"],
                        tension_low=candidate["tension_low"],
                        flexural_tension_low=candidate["flexural_tension_low"],
                        n_ed=p_ed,
                    )["util"]
                ),
            )
        else:
            add_objective(
                label,
                lambda cot, rebuilt=rebuilt, gets_shift=gets_shift: (
                    combined_core.longitudinal_check(
                        rebuilt["m_ed"],
                        rebuilt["m_rd"],
                        (
                            0.5 * v_ed * cot
                            if shear_live and gets_shift
                            and not concrete_route_applicable
                            else 0.0
                        ),
                        torsion_force(cot),
                        rebuilt["z"],
                        cap_shear_force=True,
                    )["util"]
                ),
            )
    if not objectives:
        return None
    expected = dataclasses.asdict(
        combined_core.governing_strut_result(
            objectives,
            cot_min,
            cot_max,
        )
    )
    expected["objective_labels"] = tuple(labels)
    expected["governing_objectives"] = tuple(
        labels[index] for index in expected["governing_component_indices"]
    )
    return expected


def _publication_mapping_contains_current(retained, expected):
    """Compare one retained child with a freshly rebuilt current child."""

    if not isinstance(retained, Mapping) or not isinstance(expected, Mapping):
        return False
    for key, current in expected.items():
        if key not in retained:
            return False
        value = retained[key]
        if type(current) is bool or current is None or isinstance(current, str):
            if type(value) is not type(current) or value != current:
                return False
        elif isinstance(current, Real):
            infinite_failure = bool(
                key in {"util", "chord_util"}
                and expected.get("status") == "FAIL"
                and expected.get("ok") is False
                and (key != "chord_util" or expected.get("chord_status") == "FAIL")
                and not isinstance(value, bool)
                and isinstance(value, Real)
                and float(value) == math.inf
                and float(current) == math.inf
                and _has_valid_zero_capacity_chord_failure(expected, key)
            )
            if (
                type(value) is bool
                or not isinstance(value, Real)
                or (not math.isfinite(float(value)) and not infinite_failure)
                or not math.isclose(
                    float(value),
                    float(current),
                    rel_tol=1.0e-10,
                    abs_tol=1.0e-10,
                )
            ):
                return False
        elif isinstance(current, Mapping):
            if not _publication_mapping_contains_current(value, current):
                return False
        elif value != current:
            return False
    return True


def _has_valid_zero_capacity_chord_failure(record, key):
    """Allow infinity only with the complete retained zero-capacity arithmetic."""

    candidate = (
        record if "m_rd" in record else record.get(
            "chord_governing" if key == "chord_util" else "governing"
        )
    )
    try:
        verified = capacity._combined_longitudinal_candidate(candidate)
    except (TypeError, ValueError, OverflowError):
        return False
    return bool(
        verified is not None
        and verified["m_rd"] == 0.0
        and verified["m_total"] > 0.0
        and verified["util"] == math.inf
    )


def _retained_fallback_angle_candidates(shear_result):
    """Validate the complete provisional inventory before current reconstruction."""

    links = shear_result.get("links") or {}
    candidates = links.get("chord_candidates")
    axis = shear_result.get("axis")
    tension_low = shear_result.get("tension_low")
    if (
        not isinstance(candidates, (list, tuple)) or len(candidates) != 4
        or type(axis) is not str or axis not in {"x", "y"}
        or type(tension_low) is not bool or links.get("model_2023") is not False
    ):
        return None
    other_axis = "y" if axis == "x" else "x"
    identities = []
    for candidate in candidates:
        if (
            not isinstance(candidate, Mapping)
            or type(candidate.get("role")) is not str
            or type(candidate.get("axis")) is not str
            or type(candidate.get("tension_low")) is not bool
            or type(candidate.get("conditional")) is not bool
            or _publication_utilisation(
                candidate.get("util"), allow_positive_infinity=True,
            ) is None
        ):
            return None
        identities.append((candidate["role"], candidate["axis"], candidate["tension_low"]))
    if set(identities) != {
        ("shear_axis", axis, True), ("shear_axis", axis, False),
        ("off_axis", other_axis, True), ("off_axis", other_axis, False),
    }:
        return None
    substitutes = [item for item in candidates if item["conditional"] is False]
    if len(substitutes) != 1:
        return None
    substitute = substitutes[0]
    substitute_capacity = _publication_metric(substitute.get("m_rd"))
    longitudinal_shear_force = _publication_metric(links.get("longitudinal_shear_force"))
    if (
        substitute["role"] != "shear_axis"
        or substitute["tension_low"] is not tension_low
        or substitute.get("gets_shift") is not True
        or substitute_capacity is None or substitute_capacity <= 0.0
        or links.get("longitudinal_all_conditional") is not False
        or longitudinal_shear_force is None or longitudinal_shear_force < 0.0
    ):
        return None
    # Reuse the strict arithmetic and complete-face metadata contracts, relaxing
    # only the already identified substitute's conditional flag in local copies.
    # The actual inventory remains provisional and is never returned as assessed.
    structural_candidates = [dict(item, conditional=True) for item in candidates]
    if any(
        capacity._combined_longitudinal_candidate(item) is None
        for item in structural_candidates
    ) or not capacity.combined_longitudinal_chord_evidence_is_valid(
        dict(links, chord_candidates=structural_candidates),
        shear_axis=axis,
        shear_tension_low=tension_low,
        shear_live=longitudinal_shear_force > 0.0,
        torsion_live=True,
        torsion_subdivided=False,
    ):
        return None
    shear_candidates = [item for item in candidates if item["role"] == "shear_axis"]
    off_candidates = [item for item in candidates if item["role"] == "off_axis"]
    expected_aliases = {
        "longitudinal_fallback": substitute,
        "governing_longitudinal": max(candidates, key=lambda item: float(item["util"])),
        "chord": max(shear_candidates, key=lambda item: float(item["util"])),
        "chord_off": max(off_candidates, key=lambda item: float(item["util"])),
    }
    if any(
        not _publication_mapping_contains_current(links.get(key), expected)
        or set(links[key]) != set(expected)
        for key, expected in expected_aliases.items()
    ):
        return None
    derived = capacity.longitudinal_chord_assessment(
        links,
        shear_axis=axis,
        shear_tension_low=tension_low,
        shear_live=longitudinal_shear_force > 0.0,
        torsion_live=True,
        torsion_subdivided=False,
    )
    retained = links.get("longitudinal_assessment")
    if (
        not _publication_mapping_contains_current(retained, derived)
        or set(retained) != set(derived)
    ):
        return None
    return tuple(candidates)


def _current_torsion_root_state(torsion_context, subtubes):
    """Rebuild the producer's root aliases for one or several torsion tubes."""

    primary = dict(subtubes[0])
    root = dict(
        primary,
        subdivided=torsion_context.get("subdivide") is True,
        torque_distribution=torsion_context.get("torque_distribution"),
        governing_sub=None,
    )
    if torsion_context.get("subdivide") is not True:
        return root
    tube_valid = all(item.get("tube_valid") is True for item in subtubes)
    resistance_assessed = all(
        item.get("transverse_resistance_assessed") is True for item in subtubes
    )
    valid = bool(tube_valid and resistance_assessed)
    root.update(
        trd=sum(item["trd"] for item in subtubes) if valid else None,
        asl_req=(
            sum(item["asl_req"] for item in subtubes)
            if tube_valid
            and (torsion_context.get("angle_applicability") or {}).get(
                "applicable"
            )
            is True
            else None
        ),
        util=max(item["util"] for item in subtubes) if valid else None,
        t_ed=torsion_context.get("t_ed"),
        valid=valid,
        governing_sub=(
            max(range(len(subtubes)), key=lambda index: subtubes[index]["util"])
            if valid else None
        ),
    )
    return root


def _current_torsion_only_children(inp):
    """Rebuild the producer's independent torsion-only angle and tube state."""

    calculation_input = dict(inp, shear_on=False, combined_on=False)
    try:
        p_ed = float(calculation_input["P_pl"])
        n_prestress = capacity.prestress_axial(calculation_input)
        n_ed_comp = -p_ed + n_prestress
        torsion_context = capacity.build_torsion_context(
            calculation_input,
            n_ed_comp,
        )
    except (
        capacity.CapacityInputError,
        capacity.CapacityResultError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None
    if (
        not isinstance(torsion_context, Mapping)
        or torsion_context.get("applicability_blocked") is True
        or not isinstance(torsion_context.get("subtubes"), (list, tuple))
        or not torsion_context["subtubes"]
        or not isinstance(torsion_context.get("ted_parts"), (list, tuple))
        or not torsion_context["ted_parts"]
    ):
        return None

    torsion_live = bool(
        torsion_context.get("closed_links_present") is True
        and _publication_metric(torsion_context.get("asw_over_s_t"))
        not in {None, 0.0}
        and _publication_metric(torsion_context.get("t_ed")) not in {None, 0.0}
        and all(tube.get("valid") is True for tube in torsion_context["subtubes"])
        and torsion_context["angle_applicability"].get("applicable") is True
    )

    @functools.lru_cache(maxsize=4096)
    def torsion_at(cot):
        return tuple(
            capacity.tube_torsion(
                tube,
                action,
                **dict(torsion_context["_tk"], cot_min=cot, cot_max=cot),
            )
            for tube, action in zip(
                torsion_context["subtubes"],
                torsion_context["ted_parts"],
                strict=True,
            )
        )

    try:
        objectives = tuple(
            lambda cot, index=index: torsion_at(cot)[index]["util"]
            for index in range(len(torsion_context["subtubes"]))
        )
        labels = tuple(
            f"torsion sub-tube {index + 1}"
            for index in range(len(torsion_context["subtubes"]))
        )
        expected_angle = None
        if torsion_live:
            expected_angle = dataclasses.asdict(
                combined_core.governing_strut_result(
                    objectives,
                    torsion_context["tcot_min"],
                    torsion_context["tcot_max"],
                )
            )
            expected_angle["objective_labels"] = labels
            expected_angle["governing_objectives"] = tuple(
                labels[index]
                for index in expected_angle["governing_component_indices"]
            )
            current_subtubes = torsion_at(expected_angle["cot"])
        else:
            current_subtubes = tuple(
                capacity.tube_torsion(tube, action, **torsion_context["_tk"])
                for tube, action in zip(
                    torsion_context["subtubes"],
                    torsion_context["ted_parts"],
                    strict=True,
                )
            )
        minimum = capacity.minimum_reinforcement_screen_from_context(
            calculation_input, None, torsion_context, current_subtubes[0],
        )
        minimum.pop("detailing_status", None)
        minimum.pop("detailing_scope_key", None)
    except (
        capacity.CapacityInputError,
        capacity.CapacityResultError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None
    return {
        "torsion_primary": current_subtubes[0],
        "torsion_root": _current_torsion_root_state(
            torsion_context,
            current_subtubes,
        ),
        "torsion_subtubes": current_subtubes,
        "member_angle_selection": expected_angle,
        "theta_mode": (
            "utilisation" if torsion_live else "resistance"
            if all(item.get("transverse_resistance_assessed") is True
                   for item in current_subtubes)
            else "transparency"
        ),
        "interaction": None,
        "minimum_reinforcement": minimum,
    }


def _current_shear_torsion_children(inp, shear_result, torsion_result):
    """Rebuild the current Formulae (6.29) and (6.31) face children."""

    if not isinstance(torsion_result, Mapping):
        return None
    _action, calculation_input = _current_shear_calculation_input(
        inp,
        shear_result,
    )
    if calculation_input is None:
        return None
    try:
        p_ed = float(calculation_input["P_pl"])
        n_prestress = capacity.prestress_axial(calculation_input)
        n_ed_comp = -p_ed + n_prestress
        shear_payload, link_context = capacity.build_shear_context(
            calculation_input,
            n_prestress,
            n_ed_comp,
        )
        torsion_context = capacity.build_torsion_context(
            calculation_input,
            n_ed_comp,
        )
        link_context, torsion_context = capacity.shared_member_angle_contexts(
            calculation_input, link_context, torsion_context
        )
    except (
        capacity.CapacityInputError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None
    if (
        not isinstance(shear_payload, Mapping)
        or not isinstance(torsion_context, Mapping)
        or torsion_context.get("applicability_blocked") is True
        or not isinstance(torsion_context.get("subtubes"), (list, tuple))
        or not torsion_context["subtubes"]
        or not isinstance(torsion_context.get("ted_parts"), (list, tuple))
        or not torsion_context["ted_parts"]
    ):
        return None
    if link_context is None:
        # With no closed links, the producer still retains the independent
        # concrete cracking / Formula (6.31) screen. Its absent member angle is
        # justified by the current missing participant, never by retained flags.
        current = _current_torsion_only_children(calculation_input)
        if not isinstance(current, Mapping) or (
            current.get("member_angle_selection") is not None
        ):
            return None
        minimum = capacity.minimum_reinforcement_screen_from_context(
            calculation_input, shear_payload, torsion_context,
            current["torsion_primary"],
        )
        minimum.pop("detailing_status", None)
        minimum.pop("detailing_scope_key", None)
        return dict(
            current, minimum_reinforcement=minimum,
            combined_transverse=None, interaction=None,
        )
    if not isinstance(link_context, Mapping):
        return None
    expected_angle = _current_member_angle_selection(
        inp,
        shear_result,
        torsion_result,
    )
    if not isinstance(expected_angle, Mapping):
        return None
    cot = _publication_metric(expected_angle.get("cot"))
    if cot is None or cot <= 0.0:
        return None
    try:
        current_subtubes = tuple(
            capacity.tube_torsion(
                tube,
                action,
                **dict(torsion_context["_tk"], cot_min=cot, cot_max=cot),
            )
            for tube, action in zip(
                torsion_context["subtubes"],
                torsion_context["ted_parts"],
                strict=True,
            )
        )
        primary = current_subtubes[0]
        minimum = capacity.minimum_reinforcement_screen_from_context(
            calculation_input,
            shear_payload,
            torsion_context,
            primary,
        )
        minimum.pop("detailing_status", None)
        minimum.pop("detailing_scope_key", None)
        interaction = capacity.shear_torsion_crushing_from_context(
            shear_payload,
            link_context,
            torsion_context,
            cot,
        )
        current_links = link_context["build"](cot, cot)
        transverse = (
            capacity.combined_transverse_from_children(
                shear_payload,
                primary,
                {"res": current_links},
                interaction,
            )
            if current_links.get("valid") is True
            and primary.get("transverse_resistance_assessed") is True
            else None
        )
    except (
        capacity.CapacityInputError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None
    return {
        "interaction": interaction,
        "minimum_reinforcement": minimum,
        "combined_transverse": transverse,
        "torsion_primary": primary,
        "torsion_root": _current_torsion_root_state(
            torsion_context,
            current_subtubes,
        ),
        "torsion_subtubes": current_subtubes,
        "member_angle_selection": expected_angle,
        "theta_mode": "utilisation",
    }


def _single_torsion_publication_evidence_is_current(
    torsion_result,
    current,
):
    unavailable = "torsion result evidence is unavailable"
    if not isinstance(torsion_result, Mapping) or not isinstance(current, Mapping):
        return False, unavailable
    if torsion_result.get("theta_mode") != current.get("theta_mode"):
        return False, unavailable
    retained_angle = torsion_result.get("member_angle_selection")
    expected_angle = current.get("member_angle_selection")
    if expected_angle is None:
        if retained_angle is not None or current.get("theta_mode") != "transparency":
            return False, unavailable
    elif (
        not isinstance(retained_angle, Mapping)
        or not isinstance(expected_angle, Mapping)
        or set(retained_angle) != set(expected_angle)
        or not _publication_mapping_contains_current(retained_angle, expected_angle)
    ):
        return False, unavailable
    expected_primary = current.get("torsion_primary")
    if not _publication_mapping_contains_current(
        torsion_result.get("primary"),
        expected_primary,
    ):
        return False, unavailable
    expected_subtubes = current.get("torsion_subtubes")
    retained_subtubes = torsion_result.get("subtubes")
    if not isinstance(expected_subtubes, tuple) or not expected_subtubes:
        return False, unavailable
    if len(expected_subtubes) == 1:
        if retained_subtubes is not None:
            return False, unavailable
    elif (
        not isinstance(retained_subtubes, (list, tuple))
        or len(retained_subtubes) != len(expected_subtubes)
        or any(
            not _publication_mapping_contains_current(retained, expected)
            for retained, expected in zip(
                retained_subtubes,
                expected_subtubes,
                strict=True,
            )
        )
    ):
        return False, unavailable

    expected_root = current.get("torsion_root")
    if not isinstance(expected_root, Mapping):
        return False, unavailable
    expected_util = expected_root.get("util")
    expected_status = (
        "NOT ASSESSED"
        if expected_root.get("valid") is not True or expected_util is None
        else "PASS"
        if math.isfinite(expected_util) and expected_util <= 1.0
        else "FAIL"
    )
    if (
        type(torsion_result.get("resistance_status")) is not str
        or torsion_result["resistance_status"] != expected_status
    ):
        return False, unavailable
    for key in (
        "trd_s",
        "trd_max",
        "trd",
        "trd_c",
        "cot",
        "theta_deg",
        "util",
        "asl_req",
        "t_ed",
        "governs",
        "valid",
        "resistance_selection",
        "subdivided",
        "torque_distribution",
        "governing_sub",
    ):
        if key in expected_root and not _publication_mapping_contains_current(
            {key: torsion_result.get(key)},
            {key: expected_root[key]},
        ):
            return False, unavailable
    for retained_key, expected_key in (
        ("interaction", "interaction"),
        ("min_reinf", "minimum_reinforcement"),
    ):
        expected = current.get(expected_key)
        retained = torsion_result.get(retained_key)
        if expected is None:
            if retained is not None:
                return False, unavailable
        elif not _publication_mapping_contains_current(retained, expected):
            return False, unavailable
    return True, None


def torsion_direction_publication_evidence_is_current(
    inp, shear_result, torsion_result,
):
    """Bind independently governed V+T and minimum screens to their own faces."""
    unavailable = "torsion result evidence is unavailable"
    if not isinstance(shear_result, Mapping) or not isinstance(torsion_result, Mapping):
        return False, unavailable
    candidates = shear_result.get("face_candidates")
    if candidates is None:
        return _single_torsion_publication_evidence_is_current(
            torsion_result,
            _current_shear_torsion_children(inp, shear_result, torsion_result),
        )
    action, _reason = _current_shear_action_evidence(inp, shear_result, unavailable)
    if (
        action is None or not isinstance(candidates, list)
        or len(candidates) != len(action["admissible_faces"])
    ):
        return False, unavailable
    reconciled = []
    for face in action["admissible_faces"]:
        matches = [
            candidate for candidate in candidates
            if isinstance(candidate, Mapping) and candidate.get("tension_low") is face
        ]
        if len(matches) != 1:
            return False, unavailable
        candidate = matches[0]
        child = candidate.get("torsion")
        candidate_input = _current_shear_face_input(inp, action, face)
        current = _current_shear_torsion_children(
            candidate_input, candidate.get("shear"), child,
        )
        if _single_torsion_publication_evidence_is_current(child, current)[0] is not True:
            return False, unavailable
        interaction = current.get("interaction") or {}
        minimum = current.get("minimum_reinforcement") or {}
        vt_status = interaction_assessment_status(interaction)
        vt_metric = _publication_metric(interaction.get("value"))
        minimum_status = minimum_reinforcement_screen_status(minimum)
        minimum_metric = (
            _publication_metric(minimum.get("value"))
            if minimum.get("applicable") is True else 0.0
        )
        if (interaction.get("value") is not None and vt_metric is None) or (
            minimum_metric is None
        ):
            return False, unavailable
        reconciled.append({
            "face": "negative" if face else "positive", "child": child,
            "interaction": interaction, "vt_status": vt_status,
            "vt_metric": vt_metric or 0.0,
            "minimum_status": minimum_status, "minimum_metric": minimum_metric,
        })
    vt_governing = max(
        reconciled,
        key=lambda item: capacity.assessment_key(item["vt_status"], item["vt_metric"]),
    )
    minimum_governing = max(
        reconciled,
        key=lambda item: capacity.assessment_key(
            item["minimum_status"], item["minimum_metric"],
        ),
    )
    vt_active = any(item["child"].get("interaction") is not None for item in reconciled)
    minimum_status = capacity.aggregate_assessment_status(
        item["minimum_status"] for item in reconciled
    )
    expected = dict(
        vt_governing["child"],
        directional_interaction_status=capacity.aggregate_assessment_status(
            item["vt_status"] for item in reconciled
        ),
        directional_governing_face=vt_governing["face"] if vt_active else None,
        directional_governing_cot=(
            vt_governing["interaction"].get("cot") if vt_active else None
        ),
    )
    if minimum_governing["child"].get("min_reinf") is not None:
        expected.update(
            min_reinf=dict(
                minimum_governing["child"]["min_reinf"],
                directional_status=minimum_status,
                governing_face=minimum_governing["face"],
            ),
            directional_min_reinf_status=minimum_status,
            directional_min_reinf_governing_face=minimum_governing["face"],
        )
    if not _publication_mapping_contains_current(torsion_result, expected):
        return False, unavailable
    return True, None


def torsion_angle_selection_note(torsion_result):
    """Describe the participants of already-validated torsion angle evidence."""
    if torsion_result.get("theta_mode") != "utilisation":
        return "The strut angle maximises torsion resistance within the entered bounds."
    selection = torsion_result.get("member_angle_selection") or {}
    labels = selection.get("objective_labels") or ()
    if any(label in labels for label in (
        "shear link yielding", "shear strut crushing",
        "shared closed stirrup", "shared shear-torsion strut",
    )):
        return (
            "The member strut angle is shared by shear and torsion under "
            "6.3.2(2) and minimises the governing utilisation."
        )
    return (
        "The member strut angle minimises the governing torsion utilisation "
        "across the active sub-tubes."
    )


def torsion_publication_component_is_current(
    inp, shear_result, torsion_result, *, component=None,
):
    """Validate standalone torsion or one independent biaxial V+T participant."""
    unavailable = "torsion result evidence is unavailable"
    if not isinstance(inp, Mapping) or not isinstance(torsion_result, Mapping):
        return False, unavailable
    directional = torsion_result.get("directional_interactions")
    if directional is None:
        if component is not None:
            return False, unavailable
        return torsion_publication_evidence_is_current(inp, shear_result, torsion_result)
    specs, _reason = _strict_current_directional_shear_specs(inp, unavailable)
    if not isinstance(directional, Mapping) or specs is None:
        return False, unavailable
    active = {key for key, value in specs.items() if value["v_ed"] > 0.0}
    if inp.get("shear_on") is not True or active != {"vx", "vy"}:
        return False, unavailable
    if component is None:
        return _single_torsion_publication_evidence_is_current(
            torsion_result, _current_torsion_only_children(inp),
        )
    directions = shear_result.get("directions") if isinstance(shear_result, Mapping) else None
    if component not in active or not isinstance(directions, Mapping):
        return False, unavailable
    return torsion_direction_publication_evidence_is_current(
        inp, directions.get(component), directional.get(component),
    )


def torsion_publication_evidence_is_current(inp, shear_result, torsion_result):
    """Bind every torsion value to its exact current angle participants."""

    unavailable = "torsion result evidence is unavailable"
    if not isinstance(inp, Mapping) or not isinstance(torsion_result, Mapping):
        return False, unavailable
    directional = torsion_result.get("directional_interactions")
    if directional is not None:
        if not isinstance(directional, Mapping):
            return False, unavailable
        if torsion_publication_component_is_current(
            inp, shear_result, torsion_result,
        )[0] is not True:
            return False, unavailable
        shear_directions = (
            shear_result.get("directions")
            if isinstance(shear_result, Mapping)
            else None
        )
        if (
            not isinstance(shear_directions, Mapping)
            or set(directional) != {"vx", "vy"}
            or set(shear_directions) != {"vx", "vy"}
        ):
            return False, unavailable
        for component, child in directional.items():
            shear_child = shear_directions.get(component)
            if torsion_direction_publication_evidence_is_current(
                inp, shear_child, child,
            )[0] is not True:
                return False, unavailable
        return True, None

    if isinstance(shear_result, Mapping):
        return torsion_direction_publication_evidence_is_current(
            inp, shear_result, torsion_result,
        )
    else:
        directional_input = any(
            key in inp for key in ("shear_Vx", "shear_Vy", "shear_components")
        )
        if directional_input:
            specs, _reason = _strict_current_directional_shear_specs(inp, unavailable)
            if specs is None:
                return False, unavailable
            active_shear = inp.get("shear_on") is True and any(
                spec["v_ed"] > 0.0 for spec in specs.values()
            )
        else:
            value = inp.get("shear_V")
            if inp.get("shear_on") is True and (
                is_boolean_scalar(value) or not isinstance(value, Real)
                or not math.isfinite(float(value))
            ):
                return False, unavailable
            active_shear = inp.get("shear_on") is True and abs(float(value)) > 0.0
        if active_shear:
            return False, unavailable
        current = _current_torsion_only_children(inp)
    return _single_torsion_publication_evidence_is_current(
        torsion_result,
        current,
    )


def combined_publication_scope_note(result):
    """Withhold a retained 2023 Combined route outside the supported methods."""

    if not isinstance(result, Mapping):
        return None
    directions = result.get("directions")
    members = [result]
    if isinstance(directions, Mapping):
        members.extend(directions.values())
    for member in members:
        if not isinstance(member, Mapping):
            continue
        candidates = [member.get("longitudinal"), member.get("governing_longitudinal")]
        retained = member.get("longitudinal_candidates")
        if isinstance(retained, (list, tuple)):
            candidates.extend(retained)
        malformed_formula = any(
            isinstance(candidate, Mapping)
            and "chord_formula" in candidate
            and candidate["chord_formula"] is not None
            and not isinstance(candidate["chord_formula"], str)
            for candidate in candidates
        )
        if malformed_formula:
            return "NOT ASSESSED: the retained Combined chord formula is invalid."
        if member.get("longitudinal_model_2023") is True or any(
            isinstance(candidate, Mapping)
            and isinstance(candidate.get("chord_formula"), str)
            and candidate["chord_formula"] in {"8.51", "8.52"}
            for candidate in candidates
        ):
            return (
                "NOT ASSESSED: 2023 Combined bending, shear and torsion is outside "
                "the supported release scope. Use the separate 2023 shear chord "
                "check or a supported shared edition for Combined."
            )
    return None


def _single_combined_publication_evidence_is_current(
    inp,
    calculation_input,
    plastic_result,
    shear_result,
    torsion_result,
    combined_result,
):
    """Reconcile one retained combined direction to current component children."""

    unavailable = "combined component evidence is unavailable"
    if not all(
        isinstance(value, Mapping)
        for value in (inp, shear_result, torsion_result, combined_result)
    ):
        return False, unavailable
    if (
        inp.get("combined_on") is not True
        or combined_result.get("method") != inp.get("combined_method")
        or type(combined_result.get("valid")) is not bool
    ):
        return False, unavailable
    if not isinstance(plastic_result, Mapping):
        return False, unavailable
    scope_note = combined_publication_scope_note(combined_result)
    if scope_note is not None:
        return False, scope_note
    if (
        torsion_result.get("longitudinal_assessment") is not None
        and torsion_longitudinal_assessment(
            torsion_result, input_payload=calculation_input,
        )["evidence_consistent"] is not True
    ):
        return False, unavailable
    expected_out = {
        "plastic": plastic_result,
        "shear": shear_result,
        "torsion": torsion_result,
    }
    try:
        nominal = capacity.select_nominal_shear_resistance(
            shear_result,
            links_selected=calculation_input.get("shear_links") is True,
        )
    except (capacity.CapacityInputError, TypeError, ValueError, OverflowError):
        return False, unavailable
    if nominal.valid is True and nominal.route == "links":
        if provided_link_publication_assessment(
            calculation_input,
            shear_result,
            torsion_result=torsion_result,
        ).valid is not True:
            return False, unavailable
    elif nominal.valid is True and nominal.route == "concrete":
        if concrete_shear_publication_input_is_current(
            calculation_input,
            shear_result,
        )[0] is not True:
            return False, unavailable
    try:
        capacity.finalize_combined(dict(calculation_input), expected_out)
    except (
        capacity.CapacityInputError,
        capacity.CapacityResultError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        return False, unavailable
    expected_combined = expected_out.get("combined")
    if not _publication_mapping_contains_current(
        combined_result,
        expected_combined,
    ):
        return False, unavailable
    allowed_metadata = {"component", "governing_face", "governing_cot"}
    if set(combined_result) - set(expected_combined) - allowed_metadata:
        return False, unavailable
    if expected_combined.get("valid") is not True:
        return True, None

    current = _current_shear_torsion_children(
        calculation_input,
        shear_result,
        torsion_result,
    )
    if not isinstance(current, Mapping):
        return False, unavailable
    for retained_key, current_key in (
        ("crushing", "interaction"),
        ("transverse", "combined_transverse"),
    ):
        retained = combined_result.get(retained_key)
        expected = current.get(current_key)
        if expected is None:
            if retained is not None:
                return False, unavailable
        elif not _publication_mapping_contains_current(retained, expected):
            return False, unavailable

    links = shear_result.get("links")
    if not isinstance(links, Mapping):
        return False, unavailable
    expected_angle = _current_member_angle_selection(
        calculation_input,
        shear_result,
        torsion_result,
    )
    retained_angle = combined_result.get("member_angle_selection")
    if expected_angle is None:
        if retained_angle != links.get("member_angle_selection"):
            return False, unavailable
    elif not _publication_mapping_contains_current(
        retained_angle,
        expected_angle,
    ):
        return False, unavailable

    copied_link_fields = (
        ("longitudinal", "chord", False),
        ("chord_off", "chord_off", False),
        ("longitudinal_candidates", "chord_candidates", False),
        ("governing_longitudinal", "governing_longitudinal", True),
        ("longitudinal_fallback", "longitudinal_fallback", True),
        ("longitudinal_all_conditional", "longitudinal_all_conditional", True),
        ("longitudinal_assessment", "longitudinal_assessment", True),
    )
    for retained_key, source_key, retain_none in copied_link_fields:
        expected_present = source_key in links and (
            retain_none or links[source_key] is not None
        )
        if expected_present:
            if combined_result.get(retained_key, _MISSING) != links[source_key]:
                return False, unavailable
        elif retained_key in combined_result:
            return False, unavailable

    copied_torsion = {
        "torsion_assessment_status": "assessment_status",
        "torsion_assessment_reason": "overall_reason",
        "torsion_longitudinal_assessment": "longitudinal_assessment",
        "t_ed": "t_ed",
        "asl_torsion": "asl_req",
        "torsion_subdivided": "subdivided",
    }
    for retained_key, source_key in copied_torsion.items():
        if (
            retained_key not in combined_result
            or combined_result[retained_key] != torsion_result.get(source_key)
        ):
            return False, unavailable
    return True, None


def _combined_direction_source(inp, shear_result, combined_result):
    """Return the exact candidate face that supplied one combined direction."""

    face_candidates = shear_result.get("face_candidates")
    if not isinstance(face_candidates, list):
        _action, calculation_input = _current_shear_calculation_input(
            inp,
            shear_result,
        )
        if calculation_input is None:
            return None
        return inp, calculation_input, shear_result, None, combined_result
    face = combined_result.get("governing_face")
    expected_tension = True if face == "negative" else False if face == "positive" else None
    if expected_tension is None:
        return None
    matches = [
        candidate
        for candidate in face_candidates
        if isinstance(candidate, Mapping)
        and candidate.get("tension_low") is expected_tension
        and isinstance(candidate.get("combined"), Mapping)
    ]
    if len(matches) != 1:
        return None
    candidate = matches[0]
    source_combined = candidate["combined"]
    if not _publication_mapping_contains_current(
        combined_result,
        source_combined,
    ):
        return None
    action, _reason = _current_shear_action_evidence(
        inp,
        shear_result,
        "combined component evidence is unavailable",
    )
    if action is None or expected_tension not in action["admissible_faces"]:
        return None
    candidate_input = _current_shear_face_input(inp, action, expected_tension)
    return (
        inp,
        candidate_input,
        candidate.get("shear"),
        candidate.get("torsion"),
        combined_result,
    )


def combined_publication_evidence_is_current(inp, results):
    """Bind every published combined child to current shear/torsion evidence."""

    unavailable = "combined component evidence is unavailable"
    if not isinstance(inp, Mapping) or not isinstance(results, Mapping):
        return False, unavailable
    combined = results.get("combined")
    shear = results.get("shear")
    torsion = results.get("torsion")
    plastic = results.get("plastic")
    if (
        not isinstance(combined, Mapping)
        or not isinstance(shear, Mapping)
        or not isinstance(plastic, Mapping)
    ):
        return False, unavailable
    if combined.get("method") != inp.get("combined_method"):
        return False, unavailable
    scope_note = combined_publication_scope_note(combined)
    if scope_note is not None:
        return False, scope_note

    if combined.get("biaxial") is True:
        directions = combined.get("directions")
        shear_directions = shear.get("directions")
        if (
            not isinstance(directions, Mapping)
            or not isinstance(shear_directions, Mapping)
            or set(directions) != {"vx", "vy"}
        ):
            return False, unavailable
        for component in ("vx", "vy"):
            combined_child = directions.get(component)
            shear_child = shear_directions.get(component)
            if not isinstance(combined_child, Mapping) or not isinstance(
                shear_child,
                Mapping,
            ):
                return False, unavailable
            source = _combined_direction_source(inp, shear_child, combined_child)
            if source is None:
                return False, unavailable
            (
                authority_input,
                candidate_input,
                candidate_shear,
                candidate_torsion,
                retained,
            ) = source
            if candidate_torsion is None and isinstance(torsion, Mapping):
                candidate_torsion = (
                    (torsion.get("directional_interactions") or {}).get(component)
                )
            if _single_combined_publication_evidence_is_current(
                authority_input,
                candidate_input,
                plastic,
                candidate_shear,
                candidate_torsion,
                retained,
            )[0] is not True:
                return False, unavailable
        return True, None

    source = _combined_direction_source(inp, shear, combined)
    if source is None:
        return False, unavailable
    (
        authority_input,
        candidate_input,
        candidate_shear,
        candidate_torsion,
        retained,
    ) = source
    if candidate_torsion is None:
        candidate_torsion = torsion
    return _single_combined_publication_evidence_is_current(
        authority_input,
        candidate_input,
        plastic,
        candidate_shear,
        candidate_torsion,
        retained,
    )


def provided_link_publication_assessment(
    inp,
    shear_result,
    *,
    torsion_result=None,
):
    """Bind every public links operand to the current calculation input."""

    face_candidates = (
        shear_result.get("face_candidates")
        if isinstance(shear_result, Mapping)
        else None
    )
    if isinstance(face_candidates, list):
        matching = [
            candidate
            for candidate in face_candidates
            if isinstance(candidate, Mapping)
            and candidate.get("tension_low") is shear_result.get("tension_low")
            and isinstance(candidate.get("torsion"), Mapping)
        ]
        # A directional result owns its selected face; a supplied case root
        # cannot replace missing or ambiguous companion evidence on that face.
        torsion_result = matching[0]["torsion"] if len(matching) == 1 else None
    expected_angle = _current_member_angle_selection(
        inp,
        shear_result,
        torsion_result,
    )
    assessment = capacity.provided_link_shear_publication_assessment(
        shear_result,
        expected_member_angle_selection=expected_angle,
    )
    if assessment.valid is not True:
        return assessment
    unavailable_reason = "provided-link input evidence is unavailable"

    def unavailable(reason=unavailable_reason):
        return capacity.ProvidedLinkShearAssessment(
            valid=False,
            resistance=None,
            utilisation=None,
            status="NOT ASSESSED",
            ok=None,
            reason=reason,
        )

    if not isinstance(inp, Mapping) or not isinstance(shear_result, Mapping):
        return unavailable()
    links = (
        shear_result.get("links")
        if isinstance(shear_result, Mapping)
        else None
    )
    link_result = links.get("res") if isinstance(links, Mapping) else None
    if not isinstance(links, Mapping) or not isinstance(link_result, Mapping):
        return unavailable()
    action, _reason = _current_shear_action_evidence(
        inp,
        shear_result,
        unavailable_reason,
    )
    if action is None:
        return unavailable()
    method = action["method"]
    if (
        inp.get("shear_links") is not True
    ):
        return unavailable()
    selected_code = action["code"]
    model_2023 = action["model_2023"]
    if links.get("model_2023") is not model_2023:
        return unavailable()
    if model_2023:
        ductility_class = inp.get("transverse_ductility_class")
        angle_limits = links.get("angle_limits")
        if (
            type(ductility_class) is not str
            or ductility_class not in {"A", "B", "C"}
            or not isinstance(angle_limits, Mapping)
            or angle_limits.get("ductility_class") != ductility_class
        ):
            return unavailable()

    concrete = inp.get("concrete")
    fck = _publication_metric(getattr(concrete, "fck", None))
    fcd = _publication_metric(getattr(concrete, "fcd", None))
    retained_fck = _publication_metric(shear_result.get("fck"))
    retained_fcd = _publication_metric(link_result.get("fcd"))
    if (
        fck is None
        or fck <= 0.0
        or fcd is None
        or fcd <= 0.0
        or retained_fck is None
        or retained_fcd is None
        or not math.isclose(fck, retained_fck, rel_tol=1.0e-12, abs_tol=1.0e-12)
        or not math.isclose(fcd, retained_fcd, rel_tol=1.0e-12, abs_tol=1.0e-12)
    ):
        return unavailable("provided-link concrete evidence is unavailable")

    fywk = _publication_metric(
        inp.get("shear_fywk")
    )
    steel = inp.get("steel")
    gamma_s = _publication_metric(getattr(steel, "gamma_y", None))
    retained_fywk = _publication_metric(links.get("fywk"))
    retained_fywd = _publication_metric(
        link_result.get("fywd")
    )
    if (
        fywk is None
        or fywk <= 0.0
        or gamma_s is None
        or gamma_s <= 0.0
        or retained_fywd is None
        or retained_fywd <= 0.0
        or retained_fywk is None
        or not math.isclose(fywk, retained_fywk, rel_tol=1.0e-12, abs_tol=1.0e-12)
    ):
        return unavailable("provided-link material evidence is unavailable")
    if not math.isclose(
        retained_fywd,
        fywk / gamma_s,
        rel_tol=1.0e-12,
        abs_tol=1.0e-12,
    ):
        return unavailable("provided-link material evidence is unavailable")

    axis = action["axis"]
    component = action["component"]
    input_fields = {
        "dia": inp.get("shear_link_dia"),
        "s": inp.get("shear_link_s"),
        "legs": inp.get(
            f"shear_{component}_link_legs",
            inp.get("shear_link_legs"),
        ),
    }
    for key, value in input_fields.items():
        expected = _publication_metric(value)
        retained = _publication_metric(links.get(key))
        if (
            expected is None
            or expected <= 0.0
            or retained is None
            or not math.isclose(
                expected,
                retained,
                rel_tol=1.0e-12,
                abs_tol=1.0e-12,
            )
        ):
            return unavailable()

    raw_cot_min = _publication_metric(inp.get("strut_cot_min"))
    raw_cot_max = _publication_metric(inp.get("strut_cot_max"))
    if (
        raw_cot_min is None
        or raw_cot_min <= 0.0
        or raw_cot_max is None
        or raw_cot_max <= 0.0
    ):
        return unavailable()
    expected_cot_min, expected_cot_max = sorted((raw_cot_min, raw_cot_max))
    for key, expected in (
        ("cot_min", expected_cot_min),
        ("cot_max", expected_cot_max),
    ):
        retained = _publication_metric(links.get(key))
        if retained is None or not math.isclose(
            expected,
            retained,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        ):
            return unavailable()

    outer = inp.get("outer")
    holes = inp.get("holes") or ()
    if not isinstance(outer, (list, tuple)) or not outer:
        return unavailable()
    bw_override = _publication_metric(inp.get(f"shear_{component}_bw", 0.0))
    if bw_override is None or bw_override < 0.0:
        return unavailable()
    try:
        bw_auto = shear_core.min_web_width(outer, holes, axis)
        expected_geometry = shear_core.resolve_shear_geometry(
            model_2023=model_2023,
            solid_rectangle=(
                section_geometry.section_is_approximately_solid_rectangle(
                    outer,
                    holes,
                )
            ),
            section_form=inp.get(
                "shear_section_form",
                shear_core.SHEAR_SECTION_AUTO,
            ),
            bw_mm=bw_override if bw_override > 0.0 else bw_auto,
            bw_user=bool(bw_override > 0.0),
            links_present=True,
            web_inclination_deg=inp.get(
                f"shear_{component}_web_inclination_deg",
                inp.get("shear_web_inclination_deg", 0.0),
            ),
            hoop_diameter_mm=inp.get("shear_hoop_diameter", 0.0),
            fitted_z_mm=inp.get(
                f"shear_{component}_fitted_z",
                inp.get("shear_fitted_z", 0.0),
            ),
            duct_case=inp.get("shear_duct_case", shear_core.SHEAR_DUCT_NONE),
            duct_sum_mm=inp.get(
                f"shear_{component}_duct_sum",
                inp.get("shear_duct_sum", 0.0),
            ),
            duct_largest_mm=inp.get(
                f"shear_{component}_duct_largest",
                inp.get("shear_duct_largest", 0.0),
            ),
        )
    except (TypeError, ValueError, OverflowError):
        return unavailable()
    retained_geometry = links.get("shear_geometry")
    if (
        not isinstance(retained_geometry, Mapping)
        or set(retained_geometry) != set(expected_geometry)
    ):
        return unavailable()
    for key, expected in expected_geometry.items():
        retained = retained_geometry.get(key)
        if isinstance(expected, float):
            if (
                is_boolean_scalar(retained)
                or not isinstance(retained, Real)
                or not math.isclose(
                    float(retained),
                    expected,
                    rel_tol=1.0e-12,
                    abs_tol=1.0e-12,
                )
            ):
                return unavailable()
        elif retained != expected:
            return unavailable()
    retained_z = _publication_metric(link_result.get("z"))
    retained_basis = links.get("z_input_basis")
    if retained_z is None or retained_z <= 0.0 or not isinstance(
        retained_basis, Mapping
    ):
        return unavailable("calculated link lever-arm evidence is unavailable")
    try:
        if expected_geometry.get("resolved_form") == "Circular section":
            expected_z = _publication_metric(expected_geometry.get("fitted_z_mm"))
            expected_z_source = "circular_fitted_section"
        else:
            _area, cx, cy = capacity.gross_area_centroid(outer, holes)
            bars = inp.get("bars")
            if not isinstance(bars, (list, tuple)):
                return unavailable("calculated link lever-arm evidence is unavailable")
            _asl, cg, _bar_ids = shear_core.tension_reinforcement_selection(
                bars,
                axis,
                action["tension_low"],
                cy if axis == "x" else cx,
            )
            current_d = shear_core.effective_depth(
                outer,
                axis,
                action["tension_low"],
                cg,
            )
            retained_d = _publication_metric(shear_result.get("d"))
            if (
                retained_d is None
                or current_d <= 0.0
                or not math.isclose(
                    retained_d,
                    current_d,
                    rel_tol=1.0e-12,
                    abs_tol=1.0e-12,
                )
            ):
                return unavailable("calculated link lever-arm evidence is unavailable")
            expected_z, expected_z_source = _publication_solver_result(
                capacity.shear_lever_arm,
                inp,
                axis,
                action["tension_low"],
                current_d,
            )
        if (
            expected_z is None
            or expected_z <= 0.0
            or not math.isclose(
                retained_z,
                expected_z,
                rel_tol=1.0e-12,
                abs_tol=1.0e-12,
            )
            or links.get("z_source") != expected_z_source
        ):
            return unavailable("calculated link lever-arm evidence is unavailable")
        current_basis = capacity.shear_link_arm_publication_basis(
            inp,
            axis,
            action["tension_low"],
            expected_z,
        )
    except (capacity.CapacityInputError, TypeError, ValueError, OverflowError):
        return unavailable("calculated link lever-arm evidence is unavailable")
    if dict(retained_basis) != current_basis:
        return unavailable("calculated link lever-arm evidence is unavailable")
    provenance = shear_link_arm_publication_provenance(inp, shear_result)
    if provenance["valid"] is True:
        return assessment
    return capacity.ProvidedLinkShearAssessment(
        valid=False,
        resistance=None,
        utilisation=None,
        status="NOT ASSESSED",
        ok=None,
        reason=provenance["reason"],
    )


def _current_torsion_longitudinal_force(inp, cot, torsion_result):
    """Rebuild the primary-tube torsion chord force from current inputs."""

    if not isinstance(torsion_result, Mapping):
        return None
    p_ed = _publication_metric(inp.get("P_pl"))
    retained_cot = _publication_metric(cot)
    if p_ed is None or retained_cot is None or retained_cot <= 0.0:
        return None
    try:
        n_prestress = capacity.prestress_axial(inp)
        context = capacity.build_torsion_context(
            inp,
            -p_ed + n_prestress,
        )
        if (
            not isinstance(context, Mapping)
            or context.get("applicability_blocked") is True
            or not isinstance(context.get("_tk"), Mapping)
            or not isinstance(context.get("subtubes"), (list, tuple))
            or not context["subtubes"]
            or not isinstance(context.get("ted_parts"), (list, tuple))
            or not context["ted_parts"]
        ):
            return None
        tube_kwargs = dict(
            context["_tk"],
            cot_min=retained_cot,
            cot_max=retained_cot,
        )
        current_primary = capacity.tube_torsion(
            context["subtubes"][0],
            context["ted_parts"][0],
            **tube_kwargs,
        )
    except (
        capacity.CapacityInputError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None
    current_asl = _publication_metric(current_primary.get("asl_req"))
    current_fyd = _publication_metric(context.get("fyd_long"))
    current_cot = _publication_metric(current_primary.get("cot"))
    primary = torsion_result.get("primary")
    retained_asl = _publication_metric(
        primary.get("asl_req") if isinstance(primary, Mapping) else None
    )
    retained_primary_cot = _publication_metric(
        primary.get("cot") if isinstance(primary, Mapping) else None
    )
    retained_fyd = _publication_metric(torsion_result.get("fyd_long"))
    if (
        current_primary.get("tube_valid") is not True
        or current_asl is None
        or current_asl < 0.0
        or current_fyd is None
        or current_fyd <= 0.0
        or current_cot is None
        or retained_asl is None
        or retained_primary_cot is None
        or retained_fyd is None
        or not math.isclose(
            current_asl,
            retained_asl,
            rel_tol=2.0e-8,
            abs_tol=5.0e-7,
        )
        or not math.isclose(
            current_cot,
            retained_primary_cot,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        )
        or not math.isclose(
            current_fyd,
            retained_fyd,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        )
    ):
        return None
    return current_asl * current_fyd / 1000.0


def _current_link_chord_candidate(
    inp,
    shear_result,
    candidate,
    *,
    torsion_result=None,
):
    """Rebuild one retained chord from current actions and conditional capacity."""

    unavailable_reason = "longitudinal chord evidence is unavailable"
    action, _reason = _current_shear_action_evidence(
        inp,
        shear_result,
        unavailable_reason,
    )
    if action is None or not isinstance(candidate, Mapping):
        return None
    role = candidate.get("role")
    axis = candidate.get("axis")
    tension_low = candidate.get("tension_low")
    if role not in {"shear_axis", "off_axis"} or type(tension_low) is not bool:
        return None
    shear_axis = action["axis"]
    if axis != (shear_axis if role == "shear_axis" else "y" if shear_axis == "x" else "x"):
        return None

    p_ed = float(inp["P_pl"])
    mx_ed = float(inp["Mx_pl"])
    my_ed = float(inp["My_pl"])
    links = shear_result.get("links") or {}
    model_2023 = links.get("model_2023") is True
    own_origin = mx_ed if axis == "x" else my_ed
    other_origin = my_ed if axis == "x" else mx_ed
    reference_shift = 0.0
    if model_2023 and role == "shear_axis":
        try:
            _area, cx, cy = capacity.gross_area_centroid(
                inp.get("outer") or (),
                inp.get("holes") or (),
            )
            _n_pre, mx_pre, my_pre = capacity.prestress_resultants(inp, cx, cy)
        except (TypeError, ValueError, OverflowError, capacity.CapacityInputError):
            return None
        reference_shift = p_ed * (cy if axis == "x" else cx) - (
            mx_pre if axis == "x" else my_pre
        )
    moment_signed = own_origin + reference_shift
    m_off = other_origin
    try:
        m_rd, conditional = _publication_solver_result(
            capacity.shear_face_mrd,
            inp,
            axis,
            tension_low,
            m_off=m_off,
            moment_reference_shift=reference_shift,
        )
    except (
        capacity.CapacityInputError,
        capacity.CapacityResultError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None
    if role == "off_axis" and conditional is not True:
        return None

    outer = inp.get("outer")
    holes = inp.get("holes") or ()
    bars = inp.get("bars")
    if not isinstance(outer, (list, tuple)) or not isinstance(bars, (list, tuple)):
        return None
    component = "vy" if axis == "x" else "vx"
    try:
        if inp.get("shear_section_form") == shear_core.SHEAR_SECTION_CIRCULAR:
            circular = shear_core.resolve_circular_shear_geometry(
                bw_mm=inp.get(f"shear_{component}_bw"),
                hoop_diameter_mm=inp.get("shear_hoop_diameter"),
                fitted_z_mm=inp.get(f"shear_{component}_fitted_z"),
            )
            if circular.get("valid") is not True:
                return None
            z_mm = float(circular["fitted_z_mm"])
            z_source = "circular_fitted_section"
        else:
            _area, cx, cy = capacity.gross_area_centroid(outer, holes)
            _asl, cg, _ids = shear_core.tension_reinforcement_selection(
                bars,
                axis,
                tension_low,
                cy if axis == "x" else cx,
            )
            d_mm = shear_core.effective_depth(outer, axis, tension_low, cg)
            z_mm, z_source = _publication_solver_result(
                capacity.shear_lever_arm,
                inp,
                axis,
                tension_low,
                d_mm,
            )
            if z_mm is None:
                return None
    except (
        capacity.CapacityInputError,
        capacity.CapacityResultError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None

    link_result = links.get("res") or {}
    cot = _publication_metric(link_result.get("cot"))
    concrete = shear_result.get("res") or {}
    vrd_c = _publication_metric(concrete.get("vrd_c"))
    if cot is None or cot <= 0.0 or vrd_c is None or vrd_c <= 0.0:
        return None
    concrete_current = concrete_shear_publication_input_is_current(
        inp,
        shear_result,
    )[0]
    if concrete_current is not True:
        return None
    shear_force = (
        (1.0 if model_2023 else 0.5) * action["expected_v"] * cot
        if action["expected_v"] > vrd_c
        else 0.0
    )
    gets_shift = role == "shear_axis" and (
        model_2023 or tension_low is action["tension_low"]
    )
    ftd_v = shear_force if gets_shift else 0.0

    if inp.get("torsion_on") is True:
        entered_torsion = _publication_metric(inp.get("torsion_T"))
        signed_hint = _publication_metric(
            inp.get("torsion_T_signed", inp.get("torsion_T"))
        )
        if entered_torsion is None or signed_hint is None:
            return None
    else:
        entered_torsion = 0.0
        signed_hint = 0.0
    torsion_magnitude = abs(entered_torsion)
    expected_signed_torsion = math.copysign(torsion_magnitude, signed_hint)
    torsion_requested = inp.get("torsion_on") is True and torsion_magnitude > 0.0
    if role == "shear_axis":
        circular_off_missing = False
        if (
            torsion_requested
            and inp.get("shear_section_form") == shear_core.SHEAR_SECTION_CIRCULAR
            and inp.get("torsion_subdivide") is not True
        ):
            off_component = "vx" if axis == "x" else "vy"
            try:
                off_geometry = shear_core.resolve_circular_shear_geometry(
                    bw_mm=inp.get(f"shear_{off_component}_bw"),
                    hoop_diameter_mm=inp.get("shear_hoop_diameter"),
                    fitted_z_mm=inp.get(f"shear_{off_component}_fitted_z"),
                )
            except (TypeError, ValueError, OverflowError):
                return None
            circular_off_missing = off_geometry.get("valid") is not True
        if circular_off_missing is not (
            candidate.get("off_not_evaluated") == "circular_geometry"
        ):
            return None
    ftd_t = 0.0
    if torsion_requested:
        if not isinstance(torsion_result, Mapping):
            return None
        retained_torsion = _publication_metric(torsion_result.get("t_ed"))
        retained_signed_torsion = _publication_metric(
            torsion_result.get("t_ed_signed")
        )
        if (
            retained_torsion is None
            or retained_signed_torsion is None
            or not math.isclose(
                retained_torsion,
                torsion_magnitude,
                rel_tol=1.0e-12,
                abs_tol=1.0e-12,
            )
            or not math.isclose(
                retained_signed_torsion,
                expected_signed_torsion,
                rel_tol=1.0e-12,
                abs_tol=1.0e-12,
            )
        ):
            return None
        ftd_t = _current_torsion_longitudinal_force(
            inp,
            cot,
            torsion_result,
        )
        if ftd_t is None:
            return None

    try:
        if model_2023 and role == "shear_axis":
            flexural_tension_low = (
                True
                if moment_signed > 0.0
                else False
                if moment_signed < 0.0
                else action["tension_low"]
            )
            rebuilt = combined_core.longitudinal_chord_check_2023(
                moment_signed,
                m_rd,
                ftd_v,
                ftd_t,
                z_mm / 1000.0,
                tension_low=tension_low,
                flexural_tension_low=flexural_tension_low,
                n_ed=p_ed,
            )
        else:
            rebuilt = combined_core.longitudinal_check(
                combined_core.chord_applied_moment(moment_signed, tension_low),
                m_rd,
                ftd_v,
                ftd_t,
                z_mm / 1000.0,
                cap_shear_force=True,
            )
    except (TypeError, ValueError, OverflowError):
        return None

    def values_match(retained, expected):
        if type(retained) is bool or type(expected) is bool:
            return type(retained) is bool and retained is expected
        if isinstance(expected, Real):
            value = _publication_metric(retained, allow_positive_infinity=True)
            return bool(
                value is not None
                and (
                    value == float(expected)
                    or (
                        math.isfinite(value)
                        and math.isfinite(float(expected))
                        and math.isclose(
                            value,
                            float(expected),
                            rel_tol=2.0e-8,
                            abs_tol=5.0e-7,
                        )
                    )
                )
            )
        return retained == expected

    if not all(values_match(candidate.get(key), value) for key, value in rebuilt.items()):
        return None
    expected_metadata = {
        "role": role,
        "axis": axis,
        "tension_low": tension_low,
        "conditional": conditional,
        "m_off": m_off,
        "z_src": z_source,
    }
    if role == "shear_axis":
        expected_metadata.update(
            gets_shift=gets_shift,
            has_torsion=torsion_requested,
        )
        if model_2023:
            expected_metadata.update(
                m_ed_origin_signed=own_origin,
                moment_reference_shift=reference_shift,
                flexural_tension_low=flexural_tension_low,
            )
    if not all(
        values_match(candidate.get(key), value)
        for key, value in expected_metadata.items()
    ):
        return None
    return rebuilt


def provided_link_longitudinal_publication_assessment(
    inp,
    shear_result,
    *,
    torsion_result=None,
):
    """Return chord evidence only when its current link state is authoritative."""

    retained = capacity.provided_link_longitudinal_publication_assessment(
        shear_result
    )
    face_candidates = (
        shear_result.get("face_candidates")
        if isinstance(shear_result, Mapping)
        else None
    )
    if isinstance(face_candidates, list):
        matching = [
            candidate
            for candidate in face_candidates
            if isinstance(candidate, Mapping)
            and candidate.get("tension_low") is shear_result.get("tension_low")
            and isinstance(candidate.get("torsion"), Mapping)
        ]
        torsion_result = matching[0]["torsion"] if len(matching) == 1 else None
    provided = provided_link_publication_assessment(
        inp,
        shear_result,
        torsion_result=torsion_result,
    )
    if provided.valid is True and retained.get("valid") is True:
        candidates = retained.get("candidates") or ()
        if all(
            _current_link_chord_candidate(
                inp,
                shear_result,
                candidate,
                torsion_result=torsion_result,
            )
            is not None
            for candidate in candidates
        ):
            return retained
    return {
        "valid": False,
        "assessment": {
            "status": "NOT ASSESSED",
            "ok": None,
            "util": None,
            "reason": "longitudinal chord evidence is unavailable",
            "coverage_complete": False,
            "governing": None,
        },
        "governing": None,
        "fallback": None,
        "candidates": (),
        "chord_off": None,
    }


def nominal_shear_resistance(
    result,
    *,
    links_selected=None,
    input_payload=None,
    torsion_result=None,
):
    """Return a freshly derived and exactly reconciled nominal shear route."""

    if links_selected is None:
        links_selected = (
            isinstance(result, Mapping) and result.get("links") is not None
        )
    candidate = dict(result or {})
    concrete = dict(candidate.get("res") or {})
    concrete_util = _publication_metric(candidate.get("util"))
    concrete_resistance = _publication_metric(concrete.get("vrd_c"))
    if candidate.get("v_ed") is None and (
        concrete_util is not None and concrete_resistance is not None
    ):
        candidate["v_ed"] = concrete_util * concrete_resistance
    links = candidate.get("links")
    if isinstance(links, dict):
        links = dict(links)
        link_result = dict(links.get("res") or {})
        link_util = _publication_metric(links.get("util"))
        demand = _publication_metric(candidate.get("v_ed"))
        if link_result.get("vrd") is None and (
            link_util is not None and link_util > 0.0 and demand is not None
        ):
            link_result["vrd"] = demand / link_util
        links["res"] = link_result
        candidate["links"] = links
    selected = capacity.select_nominal_shear_resistance(
        candidate,
        links_selected=bool(links_selected),
    )
    canonical = {
        "valid": selected.valid,
        "route": selected.route,
        "resistance": selected.resistance,
        "utilisation": selected.utilisation,
        "status": selected.status,
        "ok": selected.ok,
        "concrete_applicable": selected.concrete_applicable,
        "links_selected": selected.links_selected,
        "links_required": selected.links_required,
        "reason": selected.reason,
    }
    if capacity.validated_signed_shear_demand(candidate) is None:
        canonical.update(
            valid=False,
            route=None,
            resistance=None,
            utilisation=None,
            status="NOT ASSESSED",
            ok=None,
            concrete_applicable=None,
            links_required=None,
            reason="retained shear action evidence is unavailable",
        )
    elif canonical["valid"] is True and canonical["route"] == "concrete":
        current, reason = concrete_shear_publication_input_is_current(
            input_payload, result
        ) if input_payload is not None else (True, None)
        if current is not True:
            canonical.update(
                valid=False,
                route=None,
                resistance=None,
                utilisation=None,
                status="NOT ASSESSED",
                ok=None,
                concrete_applicable=None,
                links_required=None,
                reason=reason,
            )
        elif input_payload is not None and bool(links_selected):
            retained_links = capacity.provided_link_shear_assessment(
                result
            )
            if retained_links.valid is True:
                current_links = provided_link_publication_assessment(
                    input_payload,
                    result,
                    torsion_result=torsion_result,
                )
                if current_links.valid is not True:
                    canonical.update(
                        valid=False,
                        route=None,
                        resistance=None,
                        utilisation=None,
                        status="NOT ASSESSED",
                        ok=None,
                        concrete_applicable=None,
                        links_required=None,
                        reason=current_links.reason,
                    )
    elif canonical["valid"] is True and canonical["route"] == "links":
        provided = (
            provided_link_publication_assessment(
                input_payload,
                result,
                torsion_result=torsion_result,
            )
            if input_payload is not None
            else capacity.provided_link_shear_publication_assessment(result)
        )
        if provided.valid is not True:
            canonical.update(
                valid=False,
                route=None,
                resistance=None,
                utilisation=None,
                status="NOT ASSESSED",
                ok=None,
                concrete_applicable=None,
                links_required=None,
                reason=provided.reason,
            )

    # A stale retained alias must not replace the more specific fail-closed
    # reason already established from the current calculation evidence.  The
    # generic alias-mismatch reason is reserved for a contradiction against an
    # otherwise valid canonical selection.
    if canonical["valid"] is not True:
        return canonical

    retained = (
        result.get("nominal_resistance")
        if isinstance(result, Mapping)
        else None
    )
    if retained is None:
        return canonical
    if not isinstance(retained, Mapping):
        return {
            **canonical,
            "valid": False,
            "route": None,
            "resistance": None,
            "utilisation": None,
            "status": "NOT ASSESSED",
            "ok": None,
            "concrete_applicable": None,
            "links_required": None,
            "reason": "nominal shear resistance evidence is unavailable",
        }

    retained_resistance = _publication_metric(retained.get("resistance"))
    retained_utilisation = _publication_metric(retained.get("utilisation"))
    canonical_resistance = _publication_metric(canonical.get("resistance"))
    canonical_utilisation = _publication_metric(canonical.get("utilisation"))
    numeric_matches = bool(
        (retained_resistance is None) is (canonical_resistance is None)
        and (retained_utilisation is None) is (canonical_utilisation is None)
        and (
            retained_resistance is None
            or math.isclose(
                retained_resistance,
                canonical_resistance,
                rel_tol=1.0e-10,
                abs_tol=1.0e-10,
            )
        )
        and (
            retained_utilisation is None
            or math.isclose(
                retained_utilisation,
                canonical_utilisation,
                rel_tol=1.0e-10,
                abs_tol=1.0e-10,
            )
        )
    )
    exact_fields = (
        "valid",
        "route",
        "status",
        "ok",
        "concrete_applicable",
        "links_selected",
        "links_required",
        "reason",
    )
    if numeric_matches and all(
        retained.get(key) == canonical.get(key) for key in exact_fields
    ):
        return dict(retained)
    return {
        **canonical,
        "valid": False,
        "route": None,
        "resistance": None,
        "utilisation": None,
        "status": "NOT ASSESSED",
        "ok": None,
        "concrete_applicable": None,
        "links_required": None,
        "reason": "nominal shear resistance evidence is unavailable",
    }


def _transverse_metric(
    family,
    result,
    *,
    input_payload=None,
    shear_result=None,
    torsion_result=None,
    plastic_result=None,
    directional_owner=None,
):
    """Rank an already-computed shear, torsion or combined result."""
    if not isinstance(result, Mapping):
        return None
    shear_owner = result
    if family == "shear" and directional_owner is not None:
        owner_directions = (
            directional_owner.get("directions")
            if isinstance(directional_owner, Mapping)
            else None
        )
        if not isinstance(owner_directions, Mapping) or not any(
            child is result for child in owner_directions.values()
        ):
            return None
        shear_owner = directional_owner
    if (
        family == "shear"
        and input_payload is not None
        and shear_publication_input_is_current(
            input_payload,
            shear_owner,
            plastic_result=plastic_result,
            validate_directions=False,
            torsion_result=torsion_result,
        )[0]
        is not True
    ):
        return None
    if (
        family == "torsion"
        and input_payload is not None
        and torsion_publication_component_is_current(
            input_payload,
            shear_result,
            result,
        )[0]
        is not True
    ):
        return None

    def shear_metric(item):
        if input_payload and shear_direction_publication_input_is_current(
            input_payload, item, plastic_result=plastic_result,
            torsion_result=torsion_result,
        )[0] is not True:
            return None
        selected = nominal_shear_resistance(
            item,
            links_selected=(
                input_payload.get("shear_links") is True
                if isinstance(input_payload, Mapping)
                else None
            ),
            input_payload=input_payload,
            torsion_result=torsion_result,
        )
        if selected.get("valid") is not True:
            if not input_payload:
                # Isolated presentation-unit fixtures predating the current
                # input contract carry only a validity flag and utilisation.
                # Production named cases always have a non-empty case input
                # and cannot enter this compatibility branch.
                concrete = item.get("res") or {}
                links = item.get("links")
                if concrete.get("valid") is True and concrete.get("vrd_c") is None:
                    if isinstance(links, Mapping):
                        link_result = links.get("res") or {}
                        return (
                            _publication_metric(
                                links.get("util"),
                                allow_positive_infinity=True,
                            )
                            if link_result.get("valid") is True
                            and link_result.get("vrd") is None
                            else None
                        )
                    return _publication_metric(
                        item.get("util"),
                        allow_positive_infinity=True,
                    )
            return None
        return _publication_metric(
            selected.get("utilisation"), allow_positive_infinity=True
        )

    def combined_metric(item):
        if not item.get("valid"):
            return None
        if not combined_uses_dkna(item):
            physical = combined_physical_components(item)
            values = []
            for component in physical:
                if component.get("status") not in {"PASS", "FAIL"}:
                    return None
                value = _publication_utilisation(
                    component.get("util"), allow_positive_infinity=True
                )
                if value is None:
                    return None
                values.append(value)
            return max(values, default=None)
        if combined_dkna_status(item) not in {"PASS", "FAIL", "CONDITIONAL"}:
            return None
        return _publication_metric(
            item.get("dkna_sum"), allow_positive_infinity=True
        )

    directions = result.get("directions")
    if family in {"shear", "combined"}:
        if family == "combined" and not combined_uses_dkna(result):
            if result.get("biaxial") is True:
                direction_items = base_en_combined_direction_items(result)
                if direction_items is None:
                    return None
                items = [item for _, item in direction_items]
            else:
                items = [result]
            values = []
            for item in items:
                metric = combined_metric(item)
                if metric is None:
                    return None
                values.append(metric)
            return max(values) if values else None
        if directions is not None and not isinstance(directions, Mapping):
            return None
        items = [
            directions[key]
            for key in ("vx", "vy")
            if isinstance(directions, Mapping) and key in directions
        ]
        if not items:
            items = [result]
        extractor = shear_metric if family == "shear" else combined_metric
        metrics = [extractor(item) for item in items]
        values = [metric for metric in metrics if metric is not None]
    else:
        metric = None
        if family == "torsion":
            if (
                torsion_assessment_status(result, input_payload=input_payload)
                in {"PASS", "FAIL"}
                or (
                    not input_payload
                    and result.get("valid") is True
                    and torsion_applicability_publication_status(result)
                    == "APPLICABLE"
                )
            ):
                metric = _publication_metric(
                    result.get("util"), allow_positive_infinity=True
                )
        elif result.get("valid"):
            metric = _publication_metric(
                result.get("util"), allow_positive_infinity=True
            )
        values = [] if metric is None else [metric]
    return max(values) if values else None


def _transverse_direction(
    family,
    result,
    *,
    input_payload=None,
    shear_result=None,
    torsion_result=None,
    plastic_result=None,
):
    """Return the retained governing direction, with first-direction tie-break."""
    if not isinstance(result, Mapping):
        return None
    if (
        family == "combined"
        and not combined_uses_dkna(result)
        and result.get("biaxial") is True
    ):
        retained = base_en_combined_direction_items(result)
        if retained is None:
            return None
        directions = dict(retained)
    else:
        directions = result.get("directions")
        if not isinstance(directions, Mapping):
            return None
    best = None
    for order, component in enumerate(("vx", "vy")):
        item = directions.get(component)
        if not isinstance(item, Mapping):
            continue
        metric = _transverse_metric(
            family,
            item,
            input_payload=input_payload,
            shear_result=shear_result,
            torsion_result=torsion_result,
            plastic_result=plastic_result,
            directional_owner=result if family == "shear" else None,
        )
        if metric is None:
            continue
        score = (metric, -order)
        if best is None or score > best[0]:
            best = (score, component)
    return None if best is None else best[1]


def plastic_publication_authority(inp, case_results, global_results=None):
    """Prefer local evidence; bind a primary fallback to its row and actions."""

    if not isinstance(case_results, Mapping):
        return None
    if "plastic" in case_results:
        local = case_results["plastic"]
        return local if isinstance(local, Mapping) else None
    if not isinstance(inp, Mapping) or not isinstance(global_results, Mapping):
        return None
    primary = global_results.get("plastic")
    entries = global_results.get("plastic_cases")
    selected_case = inp.get("plastic_case")
    if (
        not isinstance(primary, Mapping)
        or not isinstance(entries, list)
        or not entries
        or not isinstance(entries[0], Mapping)
        or not isinstance(selected_case, Mapping)
    ):
        return None
    entry = entries[0]  # case_analysis._primary_results exposes this row only.
    name = selected_case.get("id")
    actions = entry.get("actions")
    if (
        type(name) is not str
        or not name
        or entry.get("name") != name
        or entry.get("evaluated") is not True
        or not isinstance(actions, Mapping)
        or actions.get(load_cases.NAME) != name
    ):
        return None
    try:
        matches = [
            record for record in case_analysis.case_records(inp, "plastic")
            if record.get(load_cases.NAME) == name
        ]
        if len(matches) != 1:
            return None
        record = matches[0]
        key = load_cases.PLASTIC_TABLE_KEY
        expected = case_analysis.case_signature(record, key, inp)
        if (
            tuple(entry.get("signature") or ()) != expected
            or case_analysis.case_signature(actions, key, inp) != expected
        ):
            return None
        current = case_analysis.plastic_case_input(inp, record)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    for operand in ("P_pl", "Mx_pl", "My_pl"):
        selected = _publication_metric(inp.get(operand))
        registered = _publication_metric(current.get(operand))
        if selected is None or registered is None or selected != registered:
            return None

    # The root is a compatibility projection. Matching row metadata alone must
    # not authorize a Plastic payload transplanted from another N/M case.
    check_util = current.get("check_util", True)
    if type(check_util) is not bool or primary.get("check_util") is not check_util:
        return None
    applied = primary.get("applied")
    if check_util:
        if not isinstance(applied, (list, tuple)) or len(applied) != 2:
            return None
        for value, operand in zip(applied, ("Mx_pl", "My_pl")):
            metric = _publication_metric(value)
            if metric is None or metric != _publication_metric(current.get(operand)):
                return None
    elif applied is not None:
        return None
    points = primary.get("points")
    if not isinstance(points, list) or not points:
        return None
    requested_axial = -float(current["P_pl"])
    if any(
        not isinstance(point, Mapping)
        or _publication_metric(point.get("axial_requested")) != requested_axial
        for point in points
    ):
        return None
    return primary


def _worked_case_contexts(inp, out, family):
    """Return named cases with their exact current-row/signature authority."""

    context_family = (
        "plastic" if family in {"shear", "torsion", "combined"} else family
    )
    entries = (out or {}).get(f"{context_family}_cases")
    if entries is None:
        return [(_SINGLE_CASE_ID, inp, out or {}, True)]

    # A few isolated presentation-unit fixtures intentionally omit the input
    # table. Production calculations always carry the canonical table and take
    # the strict branch below.
    if not isinstance(inp, Mapping) or f"{context_family}_cases" not in inp:
        return [
            (
                str(
                    entry.get("name")
                    or (entry.get("actions") or {}).get("name")
                    or ""
                ),
                None,
                entry.get("results") or {},
                True,
            )
            for entry in entries
            if isinstance(entry, Mapping)
        ]

    try:
        records = case_analysis.case_records(inp, context_family)
    except (KeyError, TypeError, ValueError, OverflowError):
        records = []
    by_name: dict[str, list[Mapping]] = {}
    for record in records:
        name = str(record.get(load_cases.NAME) or "")
        by_name.setdefault(name, []).append(record)
    key = (
        load_cases.PLASTIC_TABLE_KEY
        if context_family == "plastic"
        else load_cases.ELASTIC_TABLE_KEY
    )
    contexts = []
    represented_current_names = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        actions = entry.get("actions")
        name = str(entry.get("name") or (actions or {}).get("name") or "")
        matches = by_name.get(name, [])
        record = matches[0] if len(matches) == 1 else None
        if record is not None:
            represented_current_names.add(name)
        current = False
        case_input = None
        if record is not None and isinstance(actions, Mapping):
            try:
                expected_signature = case_analysis.case_signature(
                    record,
                    key,
                    inp,
                )
                action_signature = case_analysis.case_signature(
                    actions,
                    key,
                    inp,
                )
                retained_signature = tuple(entry.get("signature") or ())
                unevaluated_current_row = bool(
                    entry.get("evaluated") is False
                    and not (entry.get("results") or {})
                )
                current = bool(
                    action_signature == expected_signature
                    and (
                        retained_signature == expected_signature
                        or unevaluated_current_row
                    )
                )
                case_input = (
                    case_analysis.plastic_case_input(inp, record)
                    if context_family == "plastic"
                    else case_analysis.elastic_case_input(inp, record)
                )
            except (KeyError, TypeError, ValueError, OverflowError):
                current = False
        case_results = entry.get("results") or {}
        if context_family == "plastic" and current:
            primary = plastic_publication_authority(case_input, case_results, out)
            if "plastic" not in case_results and primary is not None:
                case_results = dict(case_results, plastic=primary)
        contexts.append((name, case_input, case_results, current))
    for record in records:
        name = str(record.get(load_cases.NAME) or "")
        if name in represented_current_names:
            continue
        try:
            case_input = (
                case_analysis.plastic_case_input(inp, record)
                if context_family == "plastic"
                else case_analysis.elastic_case_input(inp, record)
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        contexts.append((name, case_input, {}, True))
    return contexts


def _worked_family_selection(inp, out, family):
    """Select one named case and any required direction for a worked family."""
    best = None
    for order, (case_id, case_input, case_out, current) in enumerate(
        _worked_case_contexts(inp, out, family)
    ):
        if not current:
            continue
        if family == "combined" and combined_bending_assessment_blocker(
            case_out,
            case_input,
        ):
            continue
        result = case_out.get(family)
        if not result:
            continue
        if (
            family == "torsion"
            and torsion_applicability_publication_status(result) != "APPLICABLE"
        ):
            continue
        direction = None
        if family == "plastic":
            if not result.get("converged"):
                continue
            assessment = plastic_action_assessment(result)
            utilisation = _publication_metric(
                assessment.get("util"), allow_positive_infinity=True
            )
            if utilisation is not None:
                score = (2, utilisation, -order)
            else:
                values = [
                    metric
                    for name in ("max_mx", "min_mx", "max_my", "min_my")
                    if (metric := _publication_metric(result.get(name))) is not None
                ]
                if not values:
                    continue
                score = (1, max(abs(value) for value in values), -order)
        elif family in {"shear", "torsion", "combined"}:
            metric = _transverse_metric(
                family,
                result,
                input_payload=case_input,
                shear_result=case_out.get("shear"),
                torsion_result=case_out.get("torsion"),
                plastic_result=case_out.get("plastic"),
            )
            if metric is None:
                continue
            score = (2, metric, -order)
            if family in {"shear", "combined"} and result.get("directions"):
                direction = _transverse_direction(
                    family,
                    result,
                    input_payload=case_input,
                    shear_result=case_out.get("shear"),
                    torsion_result=case_out.get("torsion"),
                    plastic_result=case_out.get("plastic"),
                )
                if direction is None:
                    continue
        else:
            if not result.get("converged"):
                continue
            values = [
                metric
                for name in ("max_conc", "max_steel")
                if (metric := _publication_metric(result.get(name))) is not None
            ]
            if not values:
                continue
            score = (1, max(abs(value) for value in values), -order)
        if best is None or score > best[0]:
            best = (score, {"case_id": case_id, "component": direction})
    return None if best is None else best[1]


def _worked_check_selection(inp, out, key):
    """Select one named detailing case from retained check utilisations."""
    best = None
    for order, (case_id, case_out) in enumerate(
        _publication_cases(out, "plastic", inp=inp, current_only=True)
    ):
        result = case_out.get(key)
        if not result:
            continue
        values = [
            metric
            for check in result.get("checks") or ()
            if check.get("status") in {"PASS", "FAIL"}
            and (metric := _publication_metric(
                check.get("utilisation"), allow_positive_infinity=True
            )) is not None
        ]
        stored = _publication_metric(
            result.get("governing_utilisation"), allow_positive_infinity=True
        )
        if result.get("status") in {"PASS", "FAIL"} and stored is not None:
            values.append(stored)
        if not values:
            continue
        score = (max(values), -order)
        if best is None or score > best[0]:
            best = (score, {"case_id": case_id})
    return None if best is None else best[1]


def _worked_crack_selection(inp, out):
    """Select the global ordinary or fine/coarse crack-width branches."""
    cases = _publication_cases(out, "elastic", inp=inp, current_only=True)
    has_coarse = any(
        (case_out.get("elastic") or {}).get(key) is not None
        for _, case_out in cases
        for key in ("crack_coarse", "crack_short_coarse")
    )
    systems = (
        (
            ("fine", (("crack", "long-term (fine)"),
                      ("crack_short", "short-term (fine)"))),
            ("coarse", (("crack_coarse", "long-term (coarse)"),
                        ("crack_short_coarse", "short-term (coarse)"))),
        )
        if has_coarse else
        (("governing", (("crack", "long-term"),
                        ("crack_short", "short-term"))),)
    )
    selected = []
    for system, branches in systems:
        best = None
        for case_order, (case_id, case_out) in enumerate(cases):
            elastic = case_out.get("elastic") or {}
            if not elastic.get("converged"):
                continue
            for branch_order, (branch, label) in enumerate(branches):
                crack = elastic.get(branch)
                value = _publication_metric((crack or {}).get("wk"))
                if value is None or value < 0.0:
                    continue
                score = (value, -case_order, -branch_order)
                if best is None or score > best[0]:
                    best = (score, {
                        "case_id": case_id,
                        "system": system,
                        "branch": branch,
                        "label": label,
                    })
        if best is not None:
            selected.append(best[1])
    return selected


def _worked_crack_comparison_selection(inp, out):
    """Select a comparison only when the largest retained width is assessed.

    The optional comparison must not change which physical crack result is
    critical.  In particular, a smaller width paired with a tighter user limit
    must not displace the largest calculated width or create another worked
    chapter when that global width has no user criterion.
    """
    best = None
    assessed_states = {
        "WITHIN USER-SPECIFIED LIMIT",
        "EXCEEDS USER-SPECIFIED LIMIT",
    }
    for order, (case_id, case_out) in enumerate(
        _publication_cases(out, "elastic", inp=inp, current_only=True)
    ):
        elastic = case_out.get("elastic") or {}
        outputs = elastic.get("crack_output") or {}
        for duration_order, duration in enumerate(("long_term", "short_term")):
            output = outputs.get(duration) or {}
            value = _publication_metric(output.get("value"))
            if value is None or value < 0.0:
                continue
            score = (value, -order, -duration_order)
            if best is None or score > best[0]:
                best = (
                    score,
                    case_id,
                    duration,
                    output.get("calculation_state"),
                )
    if best is None or best[3] not in assessed_states:
        return None
    return {"case_id": best[1], "duration": best[2]}


def _cracking_threshold_selection(inp, out):
    best = None
    for order, (case_id, case_out) in enumerate(
        _publication_cases(out, "elastic", inp=inp, current_only=True)
    ):
        elastic = case_out.get("elastic") or {}
        value = _publication_metric(elastic.get("lambda_cr"))
        if not elastic.get("converged") or value is None or value < 0.0:
            continue
        score = (-value, -order)
        if best is None or score > best[0]:
            best = (score, {"case_id": case_id})
    return None if best is None else best[1]


def _torsion_subcheck_selection(inp, out):
    """Select each valid retained torsion subcheck, accepting governing +inf."""
    selected = {}
    for case_order, (case_id, case_input, case_out, current) in enumerate(
        _worked_case_contexts(inp, out, "torsion")
    ):
        if not current:
            continue
        torsion = case_out.get("torsion") or {}
        if torsion_applicability_publication_status(torsion) != "APPLICABLE":
            continue
        if case_input is not None and torsion_publication_component_is_current(
            case_input, case_out.get("shear"), torsion,
        )[0] is not True:
            continue
        directional = torsion.get("directional_interactions") or {}
        items = [(key, directional[key]) for key in ("vx", "vy") if key in directional]
        if not items:
            items = [(None, torsion)]
        for direction_order, (component, item) in enumerate(items):
            if component is not None and case_input is not None and (
                torsion_publication_component_is_current(
                    case_input, case_out.get("shear"), torsion, component=component,
                )[0] is not True
            ):
                continue
            for key, payload_key, eligible in (
                ("interaction", "interaction", lambda value: value.get("valid")),
                ("minimum_reinforcement", "min_reinf",
                 lambda value: value.get("applicable")),
            ):
                payload = item.get(payload_key) or {}
                value = _publication_metric(
                    payload.get("value"), allow_positive_infinity=True
                )
                if not eligible(payload) or value is None:
                    continue
                score = (value, -case_order, -direction_order)
                if key not in selected or score > selected[key][0]:
                    selected[key] = (score, {
                        "case_id": case_id,
                        "component": component,
                    })
    return {key: item[1] for key, item in selected.items()}


@publication_calculation_scope()
def worked_example_selection(inp, out):
    """Build the bounded, family-specific worked-example publication contract.

    This is called once after analysis assembly. It selects identities only and
    never changes or recomputes an engineering result.
    """
    families = {
        family: _worked_family_selection(inp, out, family)
        for family in ("plastic", "elastic", "shear", "torsion", "combined")
    }
    families.update({
        key: _worked_check_selection(inp, out, key)
        for key in ("minimum_reinforcement", "transverse_reinforcement")
    })
    return {
        "schema": 1,
        "families": {key: value for key, value in families.items() if value is not None},
        "crack_examples": _worked_crack_selection(inp, out),
        "crack_comparison": _worked_crack_comparison_selection(inp, out),
        "cracking_threshold": _cracking_threshold_selection(inp, out),
        "torsion_subchecks": _torsion_subcheck_selection(inp, out),
        "heightened_crack_control": (
            {"result_key": "heightened_crack_control"}
            if isinstance((out or {}).get("heightened_crack_control"), Mapping)
            else None
        ),
    }


_WORKED_FAMILY_KEYS = frozenset({
    "plastic",
    "elastic",
    "shear",
    "torsion",
    "combined",
    "minimum_reinforcement",
    "transverse_reinforcement",
})
_WORKED_SELECTION_KEYS = frozenset({
    "schema",
    "families",
    "crack_examples",
    "crack_comparison",
    "cracking_threshold",
    "torsion_subchecks",
    "heightened_crack_control",
})
_WORKED_DIRECTION_COMPONENTS = frozenset({None, "vx", "vy"})
_WORKED_TORSION_SUBCHECK_KEYS = frozenset({
    "interaction",
    "minimum_reinforcement",
})


def _worked_case_identity(item, *, component=False):
    if not isinstance(item, Mapping):
        return False
    case_id = item.get("case_id")
    if type(case_id) is not str or not case_id.strip():
        return False
    if component:
        direction = item.get("component")
        if direction is not None and type(direction) is not str:
            return False
    return True


def _valid_worked_family_identity(family, item, *, directional=False):
    if not _worked_case_identity(item, component=True):
        return False
    if family in {"minimum_reinforcement", "transverse_reinforcement"}:
        return set(item) == {"case_id"}
    if set(item) != {"case_id", "component"}:
        return False
    component = item.get("component")
    allowed = (
        _WORKED_DIRECTION_COMPONENTS
        if directional or family in {"shear", "combined"}
        else {None}
    )
    return component in allowed


_WORKED_CRACK_EXAMPLE_SHAPES = frozenset({
    ("governing", "crack", "long-term"),
    ("governing", "crack_short", "short-term"),
    ("fine", "crack", "long-term (fine)"),
    ("fine", "crack_short", "short-term (fine)"),
    ("coarse", "crack_coarse", "long-term (coarse)"),
    ("coarse", "crack_short_coarse", "short-term (coarse)"),
})


def _valid_worked_crack_example(item):
    """Return whether a retained crack selection has the complete schema-1 shape."""

    if not _worked_case_identity(item):
        return False
    if set(item) != {"case_id", "system", "branch", "label"}:
        return False
    values = (item.get("system"), item.get("branch"), item.get("label"))
    if not all(type(value) is str for value in values):
        return False
    return values in _WORKED_CRACK_EXAMPLE_SHAPES


def _valid_worked_crack_examples(items):
    if not isinstance(items, (list, tuple)):
        return False
    if not all(_valid_worked_crack_example(item) for item in items):
        return False
    systems = tuple(item["system"] for item in items)
    return systems in {
        (),
        ("governing",),
        ("fine",),
        ("coarse",),
        ("fine", "coarse"),
    }


def validated_worked_example_selection(inp, out):
    """Validate retained family identities against the complete current result.

    Report generation still fails closed when the completed calculation has no
    selection contract.  When a structurally valid contract is present, each
    retained family is checked against the current result collection so a stale
    identity cannot hide the actual governing worked calculation.
    """

    retained = (out or {}).get("worked_example_selection")
    if (
        not isinstance(retained, Mapping)
        or set(retained) != _WORKED_SELECTION_KEYS
        or type(retained.get("schema")) is not int
        or retained.get("schema") != 1
    ):
        return {}
    families = retained.get("families")
    if not isinstance(families, Mapping):
        return {}
    for family, item in families.items():
        if (
            family not in _WORKED_FAMILY_KEYS
            or not _valid_worked_family_identity(family, item)
        ):
            return {}
    crack_examples = retained.get("crack_examples", ())
    if not _valid_worked_crack_examples(crack_examples):
        return {}
    comparison = retained.get("crack_comparison")
    if comparison is not None and (
        not _worked_case_identity(comparison)
        or set(comparison) != {"case_id", "duration"}
        or type(comparison.get("duration")) is not str
        or comparison.get("duration") not in {"long_term", "short_term"}
    ):
        return {}
    threshold = retained.get("cracking_threshold")
    if threshold is not None and (
        not _worked_case_identity(threshold)
        or set(threshold) != {"case_id"}
    ):
        return {}
    torsion_subchecks = retained.get("torsion_subchecks", {})
    if (
        not isinstance(torsion_subchecks, Mapping)
        or not set(torsion_subchecks).issubset(_WORKED_TORSION_SUBCHECK_KEYS)
        or not all(
            _valid_worked_family_identity("torsion", item, directional=True)
            for item in torsion_subchecks.values()
        )
    ):
        return {}
    heightened = retained.get("heightened_crack_control")
    if heightened is not None and (
        not isinstance(heightened, Mapping)
        or set(heightened) != {"result_key"}
        or heightened.get("result_key") != "heightened_crack_control"
    ):
        return {}

    return worked_example_selection(inp, out)


def plastic_action_assessment(pl):
    """Return the semantic status for a plastic M-M applied-action result.

    A utilisation verdict is valid only for a converged, closed envelope with the
    applied-action check enabled. Capacity-only and partial-sweep results remain
    useful capacity evidence, but are explicitly not assessments.
    """
    checked = bool(pl.get("check_util", True))
    complete = bool(pl.get("closed", True))
    converged = bool(pl.get("converged", True))
    util = pl.get("util")

    if not converged:
        status = "INVALID"
        detail = "Neutral-axis sweep did not converge; values are diagnostic only"
    elif not checked:
        status = "NOT ASSESSED"
        detail = "Capacity only; applied-moment check disabled"
    elif not complete:
        status = "NOT ASSESSED"
        detail = (
            f"Open arc; close the 360{_DEGREE} envelope to assess utilisation"
        )
    elif pl.get("util_valid") is False:
        status = "INVALID"
        detail = result_reason(
            pl.get("util_reason"),
            "plastic",
            context="plastic utilisation reason",
        )
    elif plastic_result_predates_origin_contract(pl):
        status = "NOT ASSESSED"
        detail = (
            "The saved result cannot confirm that the M-M envelope contains "
            "the origin; recalculate"
        )
    elif util is None:
        status = "NOT ASSESSED"
        detail = "The closed envelope has no available utilisation result"
    elif not math.isfinite(util):
        status = "FAIL"
        detail = "No finite capacity intersection"
    elif viz.util_ok(util):
        status = "PASS"
        detail = ""
    else:
        status = "FAIL"
        detail = ""

    assessed = status in {"PASS", "FAIL"}
    margin = (1.0 - util
              if assessed and util is not None and math.isfinite(util)
              else None)
    gov_i = pl.get("util_gov")
    points = pl.get("points") or []
    gov_angle = (
        points[gov_i].get("V")
        if isinstance(gov_i, int) and 0 <= gov_i < len(points)
        else None
    )
    return {
        "status": status,
        "detail": detail,
        "util": util if assessed else None,
        "margin": margin,
        "governing_angle": gov_angle,
        "assessed": assessed,
    }


def plastic_assessment_text(assessment):
    """Return one compact, solver-neutral plastic-bending verdict."""
    parts = [f"{assessment.get('status', 'NOT ASSESSED')} - Plastic bending"]
    util = assessment.get("util")
    if assessment.get("assessed"):
        if util is not None and math.isfinite(util):
            parts.append(f"utilisation {util * 100:.1f} %")
        else:
            parts.append("utilisation not finite")
    if assessment.get("detail"):
        parts.append(str(assessment["detail"]))
    return " | ".join(parts)


def plastic_state_rows(point):
    """Return retained rows for one accepted plastic state.

    The calculation family has already evaluated every material response.  This
    helper only exposes those immutable rows and reconstructs the neutral-axis
    line used for drawing; it never calls a material law or repeats a solver.
    """

    return {
        "halfplane": viz.plastic_halfplane(
            point["V"], point["na_x"], point["na_y"],
        ),
        "concrete": list(point.get("concrete_corner_states") or ()),
        "elements": list(point.get("reinforcement_states") or ()),
    }


def plastic_compression_depth_mm(point):
    """Return only the retained plastic compression-zone depth in millimetres."""

    if not isinstance(point, Mapping):
        return None
    value = point.get("compression_depth")
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        depth_m = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(depth_m) or depth_m < 0.0:
        return None
    if depth_m == 0.0:
        return 0.0
    depth_mm = depth_m * 1000.0
    return depth_mm if math.isfinite(depth_mm) else None


def nm_boundary_rows(interaction):
    """Return a point-by-point table for both numerical N-M boundaries."""
    x_data = (interaction or {}).get("x") or {}
    y_data = (interaction or {}).get("y") or {}
    x_n, x_m = list(x_data.get("N") or []), list(x_data.get("M") or [])
    y_n, y_m = list(y_data.get("N") or []), list(y_data.get("M") or [])
    count = max(len(x_n), len(x_m), len(y_n), len(y_m))

    def at(values, index):
        return values[index] if index < len(values) else None

    return [
        {
            "Point": index + 1,
            "N, Mx boundary (kN)": at(x_n, index),
            "Mx (kNm)": at(x_m, index),
            "N, My boundary (kN)": at(y_n, index),
            "My (kNm)": at(y_m, index),
        }
        for index in range(count)
    ]


def action_set(inp, family):
    """Return one normalised action-set record from a current input payload."""
    key = "elastic_case" if family == "elastic" else "plastic_case"
    record = (inp or {}).get(key) or {}
    return {
        "id": str(record.get("id") or "").strip(),
        "type": str(record.get("type") or "").strip(),
        "source": str(record.get("source") or "").strip(),
    }


def action_set_text(inp, family, *, include_source=True):
    record = action_set(inp, family)
    text = record["id"] or "ID NOT SET"
    if record["type"]:
        text += f" | {record['type']}"
    if include_source and record["source"]:
        text += f" | Source: {record['source']}"
    return text


def shear_link_arm_source_label(source):
    """Return an engineer-facing label for a retained link-arm source."""

    labels = {
        "circular_fitted_section": "fitted circular section",
        "plastic internal lever arm": "calculated Plastic lever arm",
        "0.9 d": "0.9d",
    }
    return labels.get(str(source or "").strip(), "calculation basis unavailable")


def strut_angle_applicability_publication(value):
    """Return safe optional out-of-range angle operands for public guidance."""

    if not isinstance(value, Mapping) or value.get("applicable") is not False:
        return None
    method = value.get("method")
    if type(method) is not str or method not in capacity.SHEAR_METHODS:
        return None
    numbers = {}
    for key in (
        "requested_min",
        "requested_max",
        "permitted_min",
        "permitted_max",
    ):
        number = _publication_metric(value.get(key))
        if number is None or number <= 0.0:
            return None
        numbers[key] = number
    if not (
        numbers["requested_min"] <= numbers["requested_max"]
        and numbers["permitted_min"] <= numbers["permitted_max"]
    ):
        return None
    return {**numbers, "method": method}


def shear_geometry_basis(inp, shear_result, *, torsion_result=None):
    """Describe the retained ``d``/``z`` values and their calculation roles."""

    item = shear_result if isinstance(shear_result, Mapping) else {}
    retained_result = item.get("res")
    result = retained_result if isinstance(retained_result, Mapping) else {}
    retained_links = item.get("links")
    links_malformed = retained_links is not None and not isinstance(
        retained_links,
        Mapping,
    )
    links = retained_links if isinstance(retained_links, Mapping) else {}
    retained_link_result = links.get("res")
    link_result = (
        retained_link_result
        if isinstance(retained_link_result, Mapping)
        else {}
    )
    d_mm = _publication_metric(item.get("d"))
    d_text = "-" if d_mm is None else f"{d_mm:.3f} mm"
    d_note = "effective depth used in V<sub>Rd,c</sub>"
    retained_geometry = (
        links.get("shear_geometry")
        if links
        else item.get("shear_geometry")
    )
    geometry_basis = (
        retained_geometry if isinstance(retained_geometry, Mapping) else {}
    )
    circular_fitted = (
        _publication_metric(geometry_basis.get("fitted_z_mm"))
        if geometry_basis.get("resolved_form") == "Circular section"
        else None
    )

    if links_malformed or (links and not isinstance(retained_geometry, Mapping)):
        return {
            "z_mm": None,
            "d_note": d_note,
            "z_note": None,
            "statement": (
                f"Effective depth d = {d_text} is used in V_Rd,c. "
                "The reinforced-shear geometry is not assessed; recalculate the "
                "shear check before using a links resistance."
            ),
        }
    if links:
        provided = provided_link_publication_assessment(
            inp, item, torsion_result=torsion_result,
        )
        z_mm = _publication_metric(link_result.get("z"))
        if provided.valid is not True or z_mm is None or z_mm <= 0.0:
            reason = result_reason(
                provided.reason
                or links.get("assessment_reason")
                or link_result.get("reason")
                or "the calculated face-aligned arm is unavailable",
                "shear",
                context="shear geometry-basis link reason",
            )
            return {
                "z_mm": None,
                "d_note": d_note,
                "z_note": None,
                "statement": (
                    f"Effective depth d = {d_text} is used in V_Rd,c. "
                    f"The links resistance is not assessed: {reason}."
                ),
            }
        if circular_fitted is not None:
            return {
                "z_mm": z_mm,
                "d_note": d_note,
                "z_note": (
                    "fitted-section arm for the circular section<br>"
                    "used in V<sub>Rd,s</sub> and V<sub>Rd,max</sub>"
                ),
                "statement": (
                    f"Fitted-section arm z = {z_mm:.3f} mm is used for the circular "
                    "shear section in accordance with DS/EN 1992-1-1:2023 "
                    "8.2.3(9)."
                ),
            }
        provenance = shear_link_arm_publication_provenance(inp, item)
        if provenance["valid"] is not True:
            return {
                "z_mm": None,
                "d_note": d_note,
                "z_note": None,
                "statement": (
                    f"Effective depth d = {d_text} is used in V_Rd,c. "
                    "The calculated links arm is not assessed; recalculate the "
                    "Plastic action set and shear check."
                ),
            }
        component = provenance["component"]
        case_id = provenance["case_id"]
        case_id_html = html.escape(case_id, quote=True)
        face = viz.tension_face_label(
            item.get("tension_low", True), item.get("axis")
        )
        angle = provenance["angle_deg"]
        state = f"{face} face-aligned state"
        if angle is not None:
            state = f"{face} {angle:.0f}{_DEGREE} state"
        return {
            "z_mm": z_mm,
            "d_note": d_note,
            "z_note": (
                f"|{component}| from {case_id_html}, {state}<br>"
                "used in V<sub>Rd,s</sub> and V<sub>Rd,max</sub>"
            ),
            "statement": (
                f"Calculated arm z = {z_mm:.3f} mm = |{component}| from "
                f"{case_id}, {state}; used in V_Rd,s and V_Rd,max. "
                f"Effective depth d = {d_text} is used in V_Rd,c."
            ),
        }

    z_mm = _publication_metric(result.get("z"))
    if item.get("model_2023") and z_mm is not None and z_mm > 0.0:
        return {
            "z_mm": z_mm,
            "d_note": "defines z = 0.9d",
            "z_note": (
                "0.9d per DS/EN 1992-1-1:2023 8.2.1(3)<br>"
                "used in V<sub>Rd,c</sub>"
            ),
            "statement": (
                f"Standard-defined arm z = {z_mm:.3f} mm = 0.9d per "
                "DS/EN 1992-1-1:2023 8.2.1(3); used in V_Rd,c."
            ),
        }
    return {
        "z_mm": None,
        "d_note": d_note,
        "z_note": None,
        "statement": (
            f"Effective depth d = {d_text} is used in V_Rd,c; the selected "
            "2005 no-links resistance has no z operand."
        ),
    }


def required_action_set_errors(inp):
    """Return missing required Plastic/Elastic action-set identifiers."""
    mode = str((inp or {}).get("mode") or "")
    plastic_active = (
        mode in {"Plastic", "Both"}
        or bool((inp or {}).get("shear_on"))
        or bool((inp or {}).get("torsion_on"))
        or bool((inp or {}).get("combined_on"))
    )
    elastic_active = mode in {"Elastic", "Both"}
    errors = []
    if plastic_active and not action_set(inp, "plastic")["id"]:
        errors.append(_PLASTIC_ACTION_SET_REQUIRED)
    if elastic_active and not action_set(inp, "elastic")["id"]:
        errors.append(_ELASTIC_ACTION_SET_REQUIRED)
    return errors


def _summary_row(
    check,
    family,
    status,
    result="-",
    criterion="-",
    util=None,
    view="-",
    note="",
    inp=None,
    *,
    overview_key=None,
    overview_parent=None,
    overview_placeholder=False,
):
    case = action_set(inp, family)
    row = {
        "check": check,
        "family": family,
        "case": case["id"] or "-",
        "case_type": case["type"] or "-",
        "source": case["source"] or "-",
        "status": status,
        "result": result,
        "criterion": criterion,
        "util": util,
        "view": view,
        "note": note,
    }
    if overview_key is not None:
        row["overview_key"] = str(overview_key)
    if overview_parent is not None:
        row["overview_parent"] = str(overview_parent)
    if overview_placeholder:
        row["overview_placeholder"] = True
    return row


def _ordinary_crack_summary_row(inp, output):
    """Format one retained duration-specific output without deriving a verdict."""
    status = str(output.get("calculation_state") or "NOT ASSESSED")
    value = _publication_metric(output.get("value"))
    criterion = _publication_metric(output.get("criterion_mm"))
    ratio = _publication_metric(output.get("ratio"))
    result = "-" if value is None else f"{value:.3f} mm"
    if criterion is None:
        criterion_text = "User criterion not specified"
    elif criterion == 0.0:
        criterion_text = "No comparison requested"
    else:
        criterion_text = f"User-specified limit {criterion:.3f} mm"
    note_parts = [
        str(output.get(key) or "").strip()
        for key in ("reason", "case", "governing", "criterion_source")
    ]
    if ratio is not None:
        note_parts.append(f"w_k / w_k,criterion = {ratio:.3f}")
    duration = str(output.get("duration") or "").strip()
    duration_label = {
        "long_term": "Long-term",
        "short_term": "Short-term",
    }.get(duration, "Unspecified duration")
    return _summary_row(
        f"Crack width - {duration_label}",
        "elastic",
        status,
        result,
        criterion_text,
        None,
        "Elastic Results",
        "; ".join(part for part in note_parts if part),
        inp,
        overview_key=f"crack_width:{duration or 'unspecified'}",
        overview_parent="crack_width",
    )


def _heightened_crack_summary_row(result):
    """Format both retained Formula 7.100 NA area comparisons."""
    fine = result.get("fine") if isinstance(result.get("fine"), Mapping) else {}
    coarse = (
        result.get("coarse")
        if isinstance(result.get("coarse"), Mapping)
        else {}
    )
    fine_required = _publication_metric(
        fine.get("required_reinforcement_area_mm2")
    )
    coarse_required = _publication_metric(
        coarse.get("required_reinforcement_area_mm2")
    )
    provided = _publication_metric(result.get("provided_reinforcement_area_mm2"))
    ratio = _publication_metric(result.get("governing_comparison_ratio"))
    result_text = (
        f"Fine As,req {fine_required:.1f} mm2; coarse As,req "
        f"{coarse_required:.1f} mm2; As,prov {provided:.1f} mm2"
        if fine_required is not None
        and coarse_required is not None
        and provided is not None
        else "-"
    )
    note = (
        f"Reference {result.get('reference_case_id') or '-'} / "
        f"{result.get('ordinary_crack_branch') or '-'}; governing "
        f"{result.get('governing_crack_system') or '-'}; "
        + str(result.get("disclosure") or result.get("source") or "")
    )
    if ratio is not None:
        note = f"As,req / As,prov = {ratio:.3f}; {note}".rstrip("; ")
    return _summary_row(
        "DK heightened crack-control minimum",
        "elastic",
        str(result.get("governing_status") or "NOT ASSESSED"),
        result_text,
        "User-declared Formula 7.100 NA applicability",
        None,
        "Elastic Results",
        note,
        None,
        overview_key="heightened_crack_control",
    )


def _util_summary_status(util, *, valid=True):
    if not valid:
        return "INVALID"
    if util is None:
        return "NOT ASSESSED"
    metric = _publication_utilisation(util, allow_positive_infinity=True)
    if metric is None:
        return "NOT ASSESSED"
    if not math.isfinite(metric):
        return "FAIL"
    return "PASS" if viz.util_ok(metric) else "FAIL"


def torsion_assessment_status(torsion, *, input_payload=None):
    """Return the canonical overall torsion state, including Formula (6.28)."""

    torsion = torsion or {}
    if torsion.get("valid") is not True:
        return "NOT ASSESSED"
    longitudinal = torsion_longitudinal_assessment(
        torsion, input_payload=input_payload,
    )
    if isinstance(torsion.get("longitudinal_assessment"), Mapping):
        resistance_status = _util_summary_status(
            torsion.get("util"),
            valid=torsion.get("valid") is True,
        )
        return capacity.aggregate_assessment_status((
            resistance_status,
            longitudinal["status"],
        ))
    # Older retained results have no longitudinal-verification state. They must
    # not regain an overall PASS merely because the resistance component exists.
    t_ed = _publication_metric(torsion.get("t_ed"))
    if t_ed is None or t_ed != 0.0:
        return "NOT ASSESSED"
    return _util_summary_status(torsion.get("util"), valid=True)


def torsion_longitudinal_assessment(torsion, *, input_payload=None):
    """Return sanitized Formula (6.28) evidence for every public surface."""

    torsion = torsion or {}
    retained = torsion.get("longitudinal_assessment")
    assessment = capacity.validated_torsion_longitudinal_assessment(
        retained,
        owner=torsion,
    )
    if input_payload is None:
        return assessment
    if isinstance(input_payload, Mapping) and isinstance(retained, Mapping):
        try:
            expected = capacity.torsion_longitudinal_assessment(
                input_payload,
                assessment.get("required_by_tube_mm2") or (),
                resistance_assessed=torsion.get("valid") is True,
            )
        except (AttributeError, TypeError, ValueError, OverflowError):
            expected = None
        if isinstance(expected, Mapping) and _publication_mapping_contains_current(
            retained, expected,
        ):
            return assessment
    unavailable = capacity.validated_torsion_longitudinal_assessment(
        None, owner=torsion,
    )
    unavailable["evidence_consistent"] = False
    return unavailable


def torsion_assessment_note(torsion, *, input_payload=None):
    """Return authored engineer guidance for the canonical torsion state."""

    torsion = torsion or {}
    longitudinal = torsion_longitudinal_assessment(
        torsion, input_payload=input_payload,
    )
    if (
        isinstance(torsion.get("longitudinal_assessment"), Mapping)
        and longitudinal["status"] != "PASS"
        and _util_summary_status(
            torsion.get("util"),
            valid=torsion.get("valid") is True,
        )
        == "PASS"
    ):
        return result_reason(
            longitudinal["reason"],
            "torsion",
            context="torsion longitudinal assessment reason",
        )
    return result_reason(
        torsion.get("overall_reason")
        or torsion.get("assessment_reason")
        or torsion.get("reason")
        or "longitudinal_torsion_reinforcement_not_verified",
        "torsion",
        context="torsion overall assessment reason",
    )


def torsion_applicability_note(torsion):
    """Return safe member-scope guidance for a retained torsion result."""

    torsion = torsion or {}
    applicability = torsion.get("applicability")
    if not isinstance(applicability, Mapping):
        return (
            "The torsion design basis and member scope have not been established"
        )
    status = torsion_applicability_publication_status(torsion)
    if status == "APPLICABLE":
        basis = applicability.get("design_basis")
        if basis == capacity.TORSION_DESIGN_EQUILIBRIUM:
            return (
                "Equilibrium torsion is selected; the entered TEd must be resisted "
                "by the section"
            )
        if basis == capacity.TORSION_DESIGN_COMPATIBILITY_RESIDUAL:
            return (
                "Compatibility torsion is retained as a deliberately entered "
                "residual design action; Sector checks that TEd in full but does "
                "not establish redistribution or member/system conditions"
            )
    if status == "NOT APPLICABLE":
        return "No torsion resistance assessment is required for TEd = 0"
    if applicability.get("status") != "NOT ASSESSED":
        return (
            "The torsion design basis, member scope and full-resistance route "
            "are not mutually consistent; confirm the selections and calculate "
            "again"
        )
    return result_reason(
        applicability.get("reason")
        or torsion.get("assessment_reason")
        or "torsion design basis not established",
        "torsion",
        context="torsion applicability reason",
    )


def torsion_publication_t_ed(torsion):
    """Return the only applied torsion value safe for public display."""

    torsion = torsion or {}
    t_ed = _publication_metric(torsion.get("t_ed"))
    if t_ed is None or t_ed < 0.0:
        return None
    return t_ed


def torsion_applicability_publication_status(torsion):
    """Return the only applicability status safe for result publication."""

    torsion = torsion or {}
    if (
        "applicability_blocked" in torsion
        and torsion.get("applicability_blocked") is not False
    ):
        return "NOT ASSESSED"
    applicability = torsion.get("applicability")
    if not isinstance(applicability, Mapping):
        return "NOT ASSESSED"
    status = applicability.get("status")
    if type(status) is not str:
        return "NOT ASSESSED"
    if status not in {"APPLICABLE", "NOT APPLICABLE", "NOT ASSESSED"}:
        return "NOT ASSESSED"
    t_ed = torsion_publication_t_ed(torsion)
    if t_ed is None:
        return "NOT ASSESSED"
    design_basis = applicability.get("design_basis")
    member_scope = applicability.get("member_scope")
    if design_basis not in capacity.TORSION_DESIGN_BASES:
        return "NOT ASSESSED"
    if member_scope not in capacity.TORSION_MEMBER_SCOPES:
        return "NOT ASSESSED"
    if status == "NOT APPLICABLE":
        return "NOT APPLICABLE" if t_ed == 0.0 else "NOT ASSESSED"
    if status != "APPLICABLE":
        return "NOT ASSESSED"
    expected_route = {
        capacity.TORSION_DESIGN_EQUILIBRIUM: "equilibrium full resistance",
        capacity.TORSION_DESIGN_COMPATIBILITY_RESIDUAL: (
            "compatibility residual full resistance"
        ),
    }.get(design_basis)
    if (
        t_ed == 0.0
        or applicability.get("design_basis_valid") is not True
        or applicability.get("member_scope_valid") is not True
        or expected_route is None
        or member_scope != capacity.TORSION_MEMBER_CLOSED
        or applicability.get("full_resistance_route_entered") is not True
        or applicability.get("route") != expected_route
        or applicability.get("reason") is not None
        or applicability.get("guidance") is not None
    ):
        return "NOT ASSESSED"
    return "APPLICABLE"


_MINIMUM_REINFORCEMENT_SCREEN_NOTES = {
    "applicable_first_generation_rectangle": (
        "Formula (6.31) uses the first-generation V_Rd,c result for this "
        "approximately solid rectangular section"
    ),
    "selected_2023_route": (
        "Formula (6.31) is unavailable for the selected 2023 shear method. "
        "Assess shear using the 2023 check; assess torsion and interaction "
        "using their selected methods"
    ),
    "subdivided_section": (
        "For a subdivided compound section, use the complete sub-tube "
        "shear-and-torsion checks; Formula (6.31) is limited to approximately "
        "solid rectangular sections"
    ),
    "section_geometry": (
        "For this section geometry, use the complete shear-and-torsion checks; "
        "Formula (6.31) is evaluated for approximately solid rectangular "
        "sections"
    ),
    "shear_resistance_unavailable": (
        "Calculate the first-generation V_Rd,c shear result to evaluate "
        "Formula (6.31) for this rectangular section"
    ),
    "positive_resistance_unavailable": (
        "A positive T_Rd,c and V_Rd,c are required to evaluate Formula (6.31)"
    ),
    "dkna_combined_normal_or_moment": (
        "With acting N_Ed or M_Ed under the Danish National Annex, use the "
        "DK NA 6.3.2(6) combined N-M-V-T check; Formula (6.31) is not used as "
        "the combined verdict"
    ),
}

_MINIMUM_REINFORCEMENT_DETAILING_NOTES = {
    "separate_detailing_passed": (
        "The overall link minimum ratio and spacing checks pass; arrangement, "
        "anchorage and construction detailing remain separate engineering checks"
    ),
    "separate_detailing_failed": (
        "The overall link-detailing checks fail; revise the entered minimum "
        "ratio, spacing or link provision"
    ),
    "separate_detailing_not_run": (
        "The overall link-detailing check was not selected; Formula (6.31) does "
        "not verify minimum ratio, spacing, arrangement or anchorage"
    ),
    "separate_detailing_incomplete": (
        "The overall link-detailing check is incomplete; minimum ratio, spacing, "
        "arrangement and anchorage are not fully assessed"
    ),
}


def minimum_reinforcement_screen_status(check):
    """Return the retained Formula (6.31) applicability/verdict state."""

    check = check or {}
    retained = str(check.get("status") or "").upper()
    if retained in {"PASS", "FAIL", "NOT ASSESSED", "NOT APPLICABLE"}:
        return retained
    if not check.get("applicable"):
        return "NOT ASSESSED"
    value = _publication_metric(check.get("value"))
    if value is None:
        return "NOT ASSESSED"
    return "PASS" if bool(check.get("ok")) else "FAIL"


def minimum_reinforcement_screen_note(check):
    """Return concise engineer guidance for one Formula (6.31) screen."""

    check = check or {}
    reason = str(check.get("scope_key") or check.get("reason") or "").strip()
    return _MINIMUM_REINFORCEMENT_SCREEN_NOTES.get(
        reason,
        (
            "Formula (6.31) requires an approximately solid rectangular section "
            "and a first-generation V_Rd,c shear result"
        ),
    )


def minimum_reinforcement_screen_outcome(check):
    """Return the limited low-action outcome without implying detailing adequacy."""

    status = minimum_reinforcement_screen_status(check)
    if status == "PASS":
        return "low-action condition satisfied"
    if status == "FAIL":
        return "low-action condition not satisfied"
    return status


def minimum_reinforcement_detailing_status(check):
    """Return the independent minimum/link-detailing assessment state."""

    retained = str((check or {}).get("detailing_status") or "").upper()
    if retained in {"PASS", "FAIL", "NOT RUN", "NOT ASSESSED"}:
        return retained
    return "NOT RUN"


def minimum_reinforcement_detailing_note(check):
    """Return engineer guidance for the independent detailing state."""

    key = str((check or {}).get("detailing_scope_key") or "").strip()
    if not key:
        key = "separate_detailing_not_run"
    return _MINIMUM_REINFORCEMENT_DETAILING_NOTES.get(
        key,
        _MINIMUM_REINFORCEMENT_DETAILING_NOTES["separate_detailing_incomplete"],
    )


def _map_assessment_status(status):
    return {
        "OK": "PASS",
        "EXCEEDED": "FAIL",
        "PASS": "PASS",
        "FAIL": "FAIL",
        "INVALID": "INVALID",
        "NOT ASSESSED": "NOT ASSESSED",
        "NOT APPLICABLE": "NOT APPLICABLE",
        "NOT CALCULATED": "NOT CALCULATED",
        "CALCULATED": "CALCULATED",
        "REVIEW": "REVIEW",
    }.get(str(status or "").upper(), "NOT ASSESSED")


def assessment_status_label(status):
    """Map solver-specific acceptance states to the UI/report vocabulary."""
    return _map_assessment_status(status)


def minimum_area_check(minimum, check):
    """Identify a 2005-family Formula (9.1N) result, including failed rows."""
    return bool(
        str((check or {}).get("type") or "").casefold() == "minimum area"
        or "9.1n" in str((minimum or {}).get("clause") or "").casefold()
    )


def interaction_assessment_status(interaction):
    """Acceptance state for a mathematically valid V+T interaction."""
    interaction = interaction or {}
    value = interaction.get("value")
    if not interaction.get("valid") or value is None:
        return "NOT ASSESSED"
    value = _publication_utilisation(value, allow_positive_infinity=True)
    if value is None:
        return "NOT ASSESSED"
    if not math.isfinite(value):
        return "FAIL"
    return "PASS" if value <= 1.0 + 1.0e-9 else "FAIL"


def _percent(util):
    metric = _publication_utilisation(util, allow_positive_infinity=True)
    if metric is None:
        return "-"
    return "infinite" if not math.isfinite(metric) else f"{metric * 100:.1f} %"


def required_chord_fallback(payload):
    """Return the retained required face using a pure-axis fallback, if any."""
    payload = payload or {}
    fallback = payload.get("longitudinal_fallback")
    return fallback if isinstance(fallback, dict) else None


def combined_physical_components(combined):
    """Return the three auditable physical M-V-T component assessments.

    The solver keeps a maximum across mechanisms for angle optimisation and the
    overall case status. Presentation must not call that maximum a transverse-
    reinforcement utilisation: concrete strut crushing, closed-stirrup demand and
    longitudinal-chord demand are different physical checks.
    """
    combined = combined if isinstance(combined, Mapping) else {}
    transverse = combined.get("transverse")
    if not isinstance(transverse, Mapping):
        missing_note = "Shear links are required for the combined component checks"
        concrete = {
            "key": "concrete",
            "label": "Concrete compression strut",
            "status": "NOT ASSESSED",
            "util": None,
            "valid": False,
            "note": missing_note,
        }
        stirrup = {
            "key": "stirrup",
            "label": "Closed stirrup",
            "status": "NOT ASSESSED",
            "util": None,
            "valid": False,
            "note": missing_note,
        }
    else:
        transverse_valid = bool(transverse.get("valid"))
        concrete_util = _publication_utilisation(
            transverse.get("u_crush"), allow_positive_infinity=True
        )
        cot = _publication_metric(transverse.get("cot"))
        if cot is not None and cot <= 0.0:
            cot = None
        transverse_theta = _publication_metric(transverse.get("theta_deg"))
        if (
            transverse_theta is not None
            and not 0.0 < transverse_theta < 90.0
        ):
            transverse_theta = None
        derived_theta = (
            math.degrees(math.atan2(1.0, cot))
            if cot is not None
            else None
        )
        crushing = combined.get("crushing")
        angle_evidence_consistent = True
        concrete_evidence_consistent = True
        if isinstance(crushing, Mapping):
            interaction_util = _publication_utilisation(
                crushing.get("value"), allow_positive_infinity=True
            )
            interaction_cot = _publication_metric(crushing.get("cot"))
            if interaction_cot is not None and interaction_cot <= 0.0:
                interaction_cot = None
            interaction_theta = _publication_metric(
                crushing.get("theta_deg")
            )
            if (
                interaction_theta is not None
                and not 0.0 < interaction_theta < 90.0
            ):
                interaction_theta = None
            angle_evidence_consistent = bool(
                cot is not None
                and interaction_cot is not None
                and transverse_theta is not None
                and interaction_theta is not None
                and derived_theta is not None
                and math.isclose(
                    cot,
                    interaction_cot,
                    rel_tol=1.0e-12,
                    abs_tol=1.0e-12,
                )
                and math.isclose(
                    transverse_theta,
                    derived_theta,
                    rel_tol=1.0e-12,
                    abs_tol=_THETA_DISPLAY_ABS_TOL_DEG,
                )
                and math.isclose(
                    interaction_theta,
                    derived_theta,
                    rel_tol=1.0e-12,
                    abs_tol=_THETA_DISPLAY_ABS_TOL_DEG,
                )
            )
            concrete_evidence_consistent = bool(
                crushing.get("valid") is True
                and concrete_util is not None
                and interaction_util is not None
                and angle_evidence_consistent
                and (
                    concrete_util == interaction_util
                    if not (
                        math.isfinite(concrete_util)
                        and math.isfinite(interaction_util)
                    )
                    else math.isclose(
                        concrete_util,
                        interaction_util,
                        rel_tol=1.0e-12,
                        abs_tol=1.0e-12,
                    )
                )
            )
            if not concrete_evidence_consistent:
                concrete_util = None
        stirrup_util = _publication_utilisation(
            transverse.get("u_stirrup"), allow_positive_infinity=True
        )
        stirrup_valid = bool(
            transverse_valid
            and (
                not isinstance(crushing, Mapping)
                or angle_evidence_consistent
            )
        )
        if not stirrup_valid:
            stirrup_util = None
        concrete = {
            "key": "concrete",
            "label": "Concrete compression strut",
            "status": (
                "NOT ASSESSED"
                if transverse_valid and not concrete_evidence_consistent
                else _util_summary_status(
                    concrete_util,
                    valid=transverse_valid,
                )
            ),
            "util": concrete_util,
            "valid": transverse_valid and concrete_evidence_consistent,
            "angle_valid": bool(
                cot is not None
                and derived_theta is not None
                and (
                    not isinstance(crushing, Mapping)
                    or angle_evidence_consistent
                )
            ),
            "cot": (
                cot
                if not isinstance(crushing, Mapping)
                or angle_evidence_consistent
                else None
            ),
            "theta_deg": (
                derived_theta
                if not isinstance(crushing, Mapping)
                or angle_evidence_consistent
                else None
            ),
            "note": (
                "Formula (6.29) evidence is incomplete; recalculate the shared "
                "member-angle check"
                if transverse_valid and not concrete_evidence_consistent
                else
                f"V-T crushing at cot {_THETA} = {cot:.2f}"
                if transverse_valid and cot is not None
                else "V-T crushing at the shared member angle"
                if transverse_valid
                else "Combined strut check is invalid"
            ),
        }
        stirrup = {
            "key": "stirrup",
            "label": "Closed stirrup",
            "status": (
                "NOT ASSESSED"
                if transverse_valid and not stirrup_valid
                else _util_summary_status(
                    stirrup_util,
                    valid=stirrup_valid,
                )
            ),
            "util": stirrup_util,
            "valid": stirrup_valid,
            "note": (
                f"Shear {_percent(transverse.get('shear_fraction'))} + "
                f"torsion {_percent(transverse.get('torsion_fraction'))}"
                if stirrup_valid
                else "Common member-angle evidence is incomplete; recalculate "
                "the shared closed-stirrup check"
                if transverse_valid
                else "Combined stirrup check is invalid"
            ),
        }

    assessment = capacity.combined_longitudinal_assessment(combined)
    overall_status = str(assessment.get("status") or "NOT ASSESSED").upper()
    overall_util = _publication_utilisation(
        assessment.get("util"), allow_positive_infinity=True
    )
    if overall_status in {"PASS", "FAIL"}:
        if _util_summary_status(overall_util) != overall_status:
            overall_status = "NOT ASSESSED"
            overall_util = None
    elif overall_status != "NOT ASSESSED":
        overall_status = "NOT ASSESSED"
        overall_util = None

    chord_status = str(
        assessment.get("chord_status") or "NOT ASSESSED"
    ).upper()
    chord_util = _publication_utilisation(
        assessment.get("chord_util"), allow_positive_infinity=True
    )
    if chord_status in {"PASS", "FAIL"}:
        if _util_summary_status(chord_util) != chord_status:
            chord_status = "NOT ASSESSED"
            chord_util = None
    elif chord_status not in {"NOT ASSESSED", "NOT APPLICABLE"}:
        chord_status = "NOT ASSESSED"
        chord_util = None
    chord_governing = assessment.get("chord_governing")
    if not isinstance(chord_governing, Mapping):
        chord_governing = None
    chord_reason = assessment.get("chord_reason")
    chord_note = result_reason(
        chord_reason,
        (
            "combined"
            if isinstance(chord_reason, str)
            and chord_reason.startswith("combined_longitudinal_")
            else "shear"
        ),
        context="combined longitudinal chord assessment",
    )
    if chord_reason == "combined_longitudinal_pure_axis_substitute":
        fallback = required_chord_fallback(combined) or {}
        fallback_face = (
            "negative" if fallback.get("tension_low", True) else "positive"
        )
        chord_note = (
            f"Required {fallback.get('axis', '?')}-axis {fallback_face} face "
            "uses a pure-axis substitute; complete its conditional resistance "
            "calculation before relying on the longitudinal assessment"
        )
    torsion_status = str(
        assessment.get("torsion_status") or "NOT ASSESSED"
    ).upper()
    torsion_note = result_reason(
        assessment.get("torsion_reason")
        or "longitudinal_torsion_reinforcement_not_verified",
        "torsion",
        context="combined longitudinal torsion assessment reason",
    )
    notes = []
    if chord_status != "PASS":
        notes.append(chord_note)
    if torsion_status != "PASS":
        notes.append(torsion_note)
    if not notes and chord_governing is not None:
        face = (
            "negative"
            if chord_governing.get("tension_low", True)
            else "positive"
        )
        notes.append(
            f"Governing {chord_governing.get('axis', '?')}-axis {face} face"
        )
    if assessment.get("reason") == "combined_longitudinal_evidence_inconsistent":
        notes = [
            result_reason(
                assessment.get("reason"),
                "combined",
                context="combined longitudinal assessment",
            )
        ]
    longitudinal_component = {
        "key": "longitudinal",
        "label": "Longitudinal reinforcement",
        "status": overall_status,
        "util": overall_util,
        "valid": overall_status in {"PASS", "FAIL"},
        "note": "; ".join(notes),
        "assessment": assessment,
        "governing_source": assessment.get("governing_source"),
        "governing_mechanism": assessment.get("governing_mechanism"),
        "governing": chord_governing,
        "coverage": (
            None
            if assessment.get("chord_coverage_complete") is True
            else "incomplete"
        ),
        "chord_status": chord_status,
        "chord_util": chord_util,
        "chord_note": chord_note,
        "torsion_status": torsion_status,
        "torsion_assessment": assessment.get("torsion_assessment"),
    }
    return [concrete, stirrup, longitudinal_component]


def _registered_fatigue_basis_label(value):
    try:
        return get_design_basis(value).label
    except ValueError:
        return None


def fatigue_summary_rows(inp, results, *, stale=False):
    """Return one conservative aggregate row for an enabled fatigue analysis."""

    inp = inp or {}
    results = results or {}
    if not bool(inp.get("fatigue_on")):
        return []
    fatigue = results.get("fatigue")
    basis = inp.get("fatigue_basis") or {}
    edition = _registered_fatigue_basis_label(
        inp.get("fatigue_edition")
    ) or "-"
    case = "-"
    status = "NOT RUN"
    result_text = "-"
    util = None
    note = "Calculate to assess the grouped spectra"
    if fatigue is not None:
        # The result payload owns the basis that was actually calculated. This
        # remains true when the live inputs have since changed and the row is stale.
        basis = fatigue.get("basis") or basis
        edition = str(
            fatigue.get("basis_label")
            or fatigue.get("edition")
            or _registered_fatigue_basis_label(fatigue.get("basis_key"))
            or edition
        )
        case = str(fatigue.get("governing_spectrum") or "-")
        try:
            util = float(fatigue.get("utilisation"))
        except (TypeError, ValueError):
            util = None
        result_text = _percent(util)
        status = fatigue_presentation.overall_status(
            fatigue, stale=stale
        )
        note = fatigue_presentation.overall_note(fatigue, stale=stale)
    return [{
        "check": "Fatigue",
        "family": "fatigue",
        "case": case,
        "case_type": edition,
        "source": str(
            basis.get("spectrum_source") or basis.get("method") or "-"
        ),
        "status": status,
        "result": result_text,
        "criterion": "<= 100 %",
        "util": util,
        "view": "Fatigue Results",
        "note": note,
        "overview_key": "fatigue",
    }]


def non_governing_fatigue_spectrum_rows(inp, results, *, stale=False):
    """Return retained independently checked spectra outside the aggregate row."""

    inp = inp or {}
    results = results or {}
    if not bool(inp.get("fatigue_on")):
        return []
    fatigue = results.get("fatigue")
    if fatigue is None:
        return []
    basis = fatigue.get("basis") or inp.get("fatigue_basis") or {}
    edition = str(
        fatigue.get("basis_label")
        or fatigue.get("edition")
        or _registered_fatigue_basis_label(fatigue.get("basis_key"))
        or _registered_fatigue_basis_label(inp.get("fatigue_edition"))
        or "-"
    )
    governing_name = str(fatigue.get("governing_spectrum") or "")
    governing_skipped = False
    rows = []
    for spectrum in fatigue_presentation.spectrum_rows(fatigue):
        name = str(spectrum.get("spectrum") or "-")
        if not governing_skipped and name == governing_name:
            governing_skipped = True
            continue
        status = str(spectrum.get("status") or "INVALID")
        if stale:
            status = "STALE"
        util = spectrum.get("utilisation")
        rows.append({
            "check": "Fatigue",
            "family": "fatigue",
            "case": name,
            "case_type": edition,
            "source": str(
                basis.get("spectrum_source") or basis.get("method") or "-"
            ),
            "status": status,
            "result": _percent(util),
            "criterion": "<= 100 %",
            "util": util,
            "view": "Fatigue Results",
            "note": "Independently checked non-governing spectrum",
        })
    return rows


def _base_en_combined_summary_rows(inp, combined):
    rows = []
    biaxial = combined.get("biaxial") is True
    direction_items = (
        base_en_combined_direction_items(combined) if biaxial else ()
    )
    if biaxial and direction_items is None:
        rows.append(_summary_row(
            "Combined M-V-T supported components",
            "plastic",
            "NOT ASSESSED",
            result="-",
            criterion="Complete Vx+T and Vy+T direction results",
            util=None,
            view="M-V-T Combined",
            note=(
                "Both directional combined calculations are required. "
                "Check the actions and component results, then recalculate"
            ),
            inp=inp,
            overview_key="combined:physical",
        ))
        physical_items = []
    elif biaxial:
        physical_items = [
            ("Vx+T" if component == "vx" else "Vy+T", item)
            for component, item in direction_items
        ]
    else:
        physical_items = [("", combined)]
    for direction_label, item in physical_items:
        prefix = f"Combined {direction_label} " if direction_label else "Combined "
        if item.get("valid"):
            for physical in combined_physical_components(item):
                rows.append(_summary_row(
                    prefix + physical["label"].lower(),
                    "plastic",
                    physical["status"],
                    _percent(physical["util"]),
                    "<= 100 %",
                    physical["util"],
                    "M-V-T Combined",
                    physical["note"],
                    inp,
                    overview_key=f"combined:{physical['key']}",
                ))
        else:
            missing = [
                label
                for key, label in (
                    ("have_m", "M"),
                    ("have_v", "V"),
                    ("have_t", "T"),
                )
                if key in item and not item.get(key)
            ]
            note = "Missing prerequisite: " + ", ".join(missing)
            if item.get("reason"):
                note += "; " + result_reason(
                    item["reason"],
                    "combined",
                    context="Base EN combined prerequisite reason",
                )
            rows.append(_summary_row(
                prefix + "supported components",
                "plastic",
                "NOT ASSESSED",
                view="M-V-T Combined",
                note=note,
                inp=inp,
                overview_key="combined:physical",
            ))
    if biaxial and direction_items is not None:
        rows.append(_summary_row(
            "Generic Vx-Vy-T interaction",
            "plastic",
            "NOT CALCULATED",
            result="Independent Vx+T and Vy+T calculations",
            criterion="Not calculated",
            view="M-V-T Combined",
            note="No aggregate cross-direction verdict",
            inp=inp,
            overview_key="combined:cross_direction",
        ))
    return rows


def _torsion_component_summary_rows(inp, results, torsion):
    """Assemble current torsion components after the caller's authority guard."""
    rows = []
    torsion_applicability_status = torsion_applicability_publication_status(
        torsion
    )
    torsion_applicability_blocks = (
        torsion_applicability_status is not None
        and torsion_applicability_status != "APPLICABLE"
    ) or torsion.get("applicability_blocked") is True
    if torsion_applicability_status is not None:
        applicability_case = (
            action_set(inp, "plastic")["id"] or "Unnamed case"
        )
        rows.append(_summary_row(
            "Torsion applicability",
            "plastic",
            torsion_applicability_status,
            torsion_applicability_status,
            "Design basis and member scope",
            None,
            "Torsion",
            torsion_applicability_note(torsion),
            inp,
            overview_key=f"torsion:applicability:{applicability_case}",
            overview_parent="torsion",
        ))
    torsion_tube_valid = (
        torsion.get("tube_valid") is True
        if "tube_valid" in torsion
        else torsion.get("valid") is True
    )
    torsion_transverse_resistance_assessed = (
        torsion.get("transverse_resistance_assessed") is True
        if "transverse_resistance_assessed" in torsion
        else torsion.get("full_resistance_assessed") is True
        if "full_resistance_assessed" in torsion
        else torsion.get("valid") is True
    )
    if torsion_applicability_blocks:
        torsion_tube_valid = False
        torsion_transverse_resistance_assessed = False
    if (
        "closed_links_present" in torsion
        and torsion.get("closed_links_present") is not True
    ):
        torsion_transverse_resistance_assessed = False
    if not torsion_tube_valid:
        if torsion_applicability_blocks:
            tube_status = (
                "NOT APPLICABLE"
                if torsion_applicability_status == "NOT APPLICABLE"
                else "NOT ASSESSED"
            )
            tube_note = torsion_applicability_note(torsion)
        else:
            tube_reason = str(torsion.get("reason") or "")
            tube_status = (
                "NOT ASSESSED"
                if tube_reason in _TORSION_WALL_APPLICABILITY_REASONS
                else "INVALID"
            )
            tube_note = result_reason(
                torsion.get("reason") or "torsion tube evidence is invalid",
                "torsion",
                context="torsion summary geometry reason",
            )
        rows.append(_summary_row(
            "Torsion",
            "plastic",
            tube_status,
            "-",
            "-",
            None,
            "Torsion",
            tube_note,
            inp,
            overview_key="torsion",
        ))
    elif not torsion_transverse_resistance_assessed:
        rows.append(_summary_row(
            "Torsion",
            "plastic",
            "NOT ASSESSED",
            "-",
            "-",
            None,
            "Torsion",
            result_reason(
                torsion.get("assessment_reason")
                or torsion.get("reason")
                or "full torsion resistance not assessed",
                "torsion",
                context="torsion summary assessment reason",
            ),
            inp,
            overview_key="torsion",
        ))
    else:
        overall_status = torsion_assessment_status(torsion, input_payload=inp)
        rows.append(_summary_row(
            "Torsion",
            "plastic",
            overall_status,
            overall_status,
            "Resistance, longitudinal steel and detailing",
            None,
            "Torsion",
            torsion_assessment_note(torsion, input_payload=inp),
            inp,
            overview_key="torsion",
        ))
        rows.append(_summary_row(
            "Torsion transverse/strut resistance",
            "plastic",
            str(torsion.get("resistance_status") or _util_summary_status(
                torsion.get("util"),
                valid=torsion.get("valid") is True,
            )),
            _percent(torsion.get("util")),
            "<= 100 %",
            torsion.get("util"),
            "Torsion",
            result_reason(
                torsion.get("governs")
                or torsion.get("reason")
                or "torsion result is invalid",
                "torsion",
                context="torsion resistance-component summary reason",
            ),
            inp,
            overview_key="torsion:resistance",
            overview_parent="torsion",
        ))
        longitudinal = torsion_longitudinal_assessment(torsion, input_payload=inp)
        if isinstance(torsion.get("longitudinal_assessment"), Mapping):
            required = longitudinal.get("required_asl_mm2")
            provided = longitudinal.get("provided_equivalent_area_mm2")
            result_text = (
                f"{required:.0f} / {provided:.0f} mm2"
                if required is not None and provided is not None
                else "-"
            )
            rows.append(_summary_row(
                "Torsion longitudinal reinforcement",
                "plastic",
                str(longitudinal.get("status") or "NOT ASSESSED"),
                result_text,
                "Required / modelled upper bound",
                longitudinal.get("demand_ratio"),
                "Torsion",
                result_reason(
                    longitudinal.get("reason")
                    or "longitudinal_torsion_reinforcement_not_verified",
                    "torsion",
                    context="torsion longitudinal summary reason",
                ),
                inp,
                overview_key="torsion:longitudinal",
                overview_parent="torsion",
            ))

    def append_minimum_reinforcement_screen(
        minimum,
        *,
        label="Formula (6.31) minimum-reinforcement screen",
        overview_key="torsion:minimum_reinforcement",
    ):
        if not isinstance(minimum, Mapping):
            return
        status = minimum_reinforcement_screen_status(minimum)
        value = _publication_metric(minimum.get("value"))
        scope_note = minimum_reinforcement_screen_note(minimum)
        if status == "PASS":
            note = (
                "Low-action condition satisfied; designed shear-and-torsion "
                "reinforcement beyond the minimum is not required by Formula "
                "(6.31). This does not verify the required minimum detailing; "
                + scope_note
            )
        elif status == "FAIL":
            note = (
                "Low-action condition not satisfied; designed "
                "shear-and-torsion reinforcement is required; " + scope_note
            )
        else:
            note = scope_note
        row = _summary_row(
            label,
            "plastic",
            status,
            _percent(value) if minimum.get("applicable") else "-",
            (
                "<= 100 %"
                if minimum.get("applicable")
                else "Approximately solid rectangular; first-generation route"
            ),
            value if minimum.get("applicable") else None,
            "Torsion",
            note,
            inp,
            overview_key=overview_key,
            overview_parent="torsion",
        )
        # Applicability is the engineering result of this bounded screen.
        # Keep its explanation in the shared overview rather than reducing
        # it to a status-only calculation-state line.
        row["overview_scope_in_result_table"] = True
        rows.append(row)
        detailing_status = minimum_reinforcement_detailing_status(minimum)
        detailing_row = _summary_row(
            label + " - separate link detailing",
            "plastic",
            detailing_status,
            detailing_status,
            "Minimum ratio and spacing",
            None,
            "Detailing",
            minimum_reinforcement_detailing_note(minimum),
            inp,
            overview_key=overview_key + ":detailing",
            overview_parent="torsion",
        )
        detailing_row["overview_scope_in_result_table"] = True
        rows.append(detailing_row)

    if not torsion_applicability_blocks:
        directional_screens = torsion.get("directional_interactions") or {}
        if directional_screens:
            for component, label in (
                ("vx", "Vx+T Formula (6.31) minimum-reinforcement screen"),
                ("vy", "Vy+T Formula (6.31) minimum-reinforcement screen"),
            ):
                item = directional_screens.get(component) or {}
                if torsion_publication_component_is_current(
                    inp, results.get("shear"), torsion, component=component,
                )[0] is not True:
                    rows.append(_summary_row(
                        label, "plastic", "NOT ASSESSED", "-", "-", None,
                        "Torsion", "Recalculate this directional torsion check", inp,
                        overview_key=f"torsion:minimum_reinforcement:{component}",
                        overview_parent="torsion",
                    ))
                    continue
                append_minimum_reinforcement_screen(
                    item.get("min_reinf"),
                    label=label,
                    overview_key=f"torsion:minimum_reinforcement:{component}",
                )
        else:
            append_minimum_reinforcement_screen(torsion.get("min_reinf"))

    return (
        rows, torsion_tube_valid,
        torsion_transverse_resistance_assessed, torsion_applicability_blocks,
    )


@publication_calculation_scope()
def result_summary_rows(inp, results, *, stale=False):
    """Build the shared UI/PDF overview without rerunning any solver."""
    inp = inp or {}
    results = results or {}
    rows = []
    mode = str(inp.get("mode") or "")
    plastic_requested = mode in {"Plastic", "Both"}
    elastic_requested = mode in {"Elastic", "Both"}

    pl = results.get("plastic")
    if pl is not None and plastic_requested:
        assessment = plastic_action_assessment(pl)
        rows.append(_summary_row(
            "Plastic bending",
            "plastic",
            assessment["status"],
            _percent(assessment["util"]),
            "<= 100 %",
            assessment["util"],
            "Plastic Results",
            assessment["detail"],
            inp,
            overview_key="plastic_bending",
        ))
    elif plastic_requested:
        rows.append(_summary_row(
            "Plastic bending", "plastic", "NOT RUN",
            view="Plastic Results", note="Calculate required", inp=inp,
            overview_key="plastic_bending",
        ))

    elastic = results.get("elastic")
    if elastic is None and elastic_requested:
        rows.append(_summary_row(
            "Elastic stresses", "elastic", "NOT RUN",
            view="Elastic Results", note="Calculate required", inp=inp,
            overview_key="elastic_stresses:scope",
            overview_parent="elastic_stresses",
            overview_placeholder=True,
        ))
        if inp.get("sls_cw"):
            rows.append(_summary_row(
                "Crack width", "elastic", "NOT RUN",
                view="Elastic Results", note="Calculate required", inp=inp,
                overview_key="crack_width:scope",
                overview_parent="crack_width",
                overview_placeholder=True,
            ))
    elif elastic is not None and elastic_requested:
        converged = bool(elastic.get("converged", True))
        outputs = elastic.get("stress_outputs") or {}
        names = [
            ("Concrete stress", "concrete"),
            ("Reinforcement stress", "reinforcement"),
        ]
        if inp.get("tendons"):
            names.append(("Tendon stress", "prestress"))
        if not outputs:
            rows.append(_summary_row(
                "Elastic stresses",
                "elastic",
                "INVALID" if not converged else "NOT RUN",
                view="Elastic Results",
                note=("Elastic analysis did not converge" if not converged
                      else "No elastic stress result is available"),
                inp=inp,
                overview_key="elastic_stresses",
                overview_parent="elastic_stresses",
            ))
        else:
            for label, key in names:
                output = outputs.get(key) or {}
                status = (
                    "INVALID" if not converged
                    else str(
                        output.get("calculation_state") or "NOT CALCULATED"
                    )
                )
                value = output.get("value")
                result = "-" if value is None else f"{value:.3f} MPa"
                rows.append(_summary_row(
                    label, "elastic", status, result, "Output only",
                    None, "Elastic Results",
                    output.get("governing") or output.get("quantity") or "", inp,
                    overview_key=f"elastic_stress:{key}",
                    overview_parent="elastic_stresses",
                ))
        try:
            lambda_cr = float(elastic.get("lambda_cr"))
        except (TypeError, ValueError):
            lambda_cr = None
        if lambda_cr is not None and not math.isfinite(lambda_cr):
            lambda_cr = None
        if not converged:
            cracking_status = "INVALID"
            cracking_result = "-"
            cracking_note = "Elastic analysis did not converge"
        elif lambda_cr is None:
            cracking_status = "NOT CALCULATED"
            cracking_result = "-"
            cracking_note = "No cracking-threshold result returned"
        else:
            cracking_status = "CALCULATED"
            cracking_state = (
                "cracked" if elastic.get("cracked") else "uncracked"
            )
            cracking_result = f"lambda_cr {lambda_cr:.3f}; {cracking_state}"
            cracking_note = "Stage-I cracking threshold/state"
        rows.append(_summary_row(
            "Cracking threshold/state", "elastic", cracking_status,
            cracking_result, "Output only", None, "Elastic Results",
            cracking_note, inp,
            overview_key="cracking_threshold",
        ))
        output = elastic.get("crack_output")
        if isinstance(output, Mapping):
            for duration in ("long_term", "short_term"):
                duration_output = output.get(duration)
                if isinstance(duration_output, Mapping):
                    rows.append(
                        _ordinary_crack_summary_row(inp, duration_output)
                    )
        elif elastic.get("show_cw") or inp.get("sls_cw"):
            rows.append(_summary_row(
                "Crack width", "elastic", "NOT ASSESSED",
                view="Elastic Results",
                note="No calculated crack-width result is available",
                inp=inp,
                overview_key="crack_width",
                overview_parent="crack_width",
            ))

    minimum = results.get("minimum_reinforcement")
    minimum_direction = modelled_direction.resolved_label(
        minimum,
        cut_direction=inp.get("detailing_cut_direction"),
        alias=inp.get(modelled_direction.ALIAS_KEY),
    )
    minimum_label = f"{minimum_direction} minimum reinforcement"
    if minimum is None and inp.get("minimum_reinforcement_on"):
        rows.append(_summary_row(
            minimum_label, "plastic", "NOT RUN",
            view="Detailing", note="Calculate required", inp=inp,
            overview_key="minimum_reinforcement",
        ))
    elif minimum is not None and inp.get("minimum_reinforcement_on"):
        checks = minimum.get("checks") or []
        if not checks:
            minimum_note = (
                result_reason(
                    minimum.get("reason"),
                    "minimum_reinforcement",
                    context="minimum-reinforcement summary reason",
                )
                if minimum.get("reason")
                else str(minimum.get("clause") or "")
            )
            rows.append(_summary_row(
                minimum_label,
                "plastic",
                _map_assessment_status(minimum.get("status")),
                view="Detailing",
                note=minimum_note,
                inp=inp,
                overview_key="minimum_reinforcement",
            ))
        for check in checks:
            util = check.get("utilisation")
            face = check.get("face")
            axis = check.get("axis")
            suffix = (
                " Mx+My resultant"
                if axis == "xy"
                else f" M{axis} {face}" if axis and face else ""
            )
            if minimum_area_check(minimum, check):
                required = check.get("as_min_mm2")
                result_text = (
                    f"As,prov {check.get('as_provided_mm2', 0.0):.1f} mm2; "
                    "As,min "
                    + ("-" if required is None else f"{float(required):.1f} mm2")
                )
                criterion = "As,prov >= As,min"
            elif check.get("type") == "pure tension":
                resistance = check.get("resistance_kn")
                demand = check.get("demand_kn")
                result_text = (
                    "Rnom "
                    + ("-" if resistance is None else f"{float(resistance):.1f}")
                    + " kN; Rcr "
                    + ("-" if demand is None else f"{float(demand):.1f}")
                    + " kN"
                )
                criterion = "Rnom >= Rcr"
            else:
                resistance = check.get("mr_nom_knm")
                demand = check.get("m_cr_knm")
                result_text = (
                    "MR,nom "
                    + ("-" if resistance is None else f"{float(resistance):.1f}")
                    + " kNm; Mcr "
                    + ("-" if demand is None else f"{float(demand):.1f}")
                    + " kNm"
                )
                criterion = "MR,nom >= Mcr"
            note_parts = [str(minimum.get("clause") or "")]
            if check.get("axial_feasible") is not None:
                note_parts.append(
                    "nominal axial equilibrium verified"
                    if check.get("axial_feasible")
                    else "nominal axial equilibrium not available"
                )
            if check.get("reason"):
                note_parts.append(result_reason(
                    check["reason"],
                    "minimum_reinforcement",
                    context="minimum-reinforcement check reason",
                ))
            rows.append(_summary_row(
                f"{minimum_label}{suffix}",
                "plastic",
                _map_assessment_status(check.get("status")),
                result_text,
                criterion,
                util,
                "Detailing",
                "; ".join(part for part in note_parts if part),
                inp,
                overview_key="minimum_reinforcement",
            ))

    transverse = results.get("transverse_reinforcement")
    if transverse is None and inp.get("transverse_detailing_on"):
        rows.append(_summary_row(
            "Shear/torsion link detailing",
            "plastic",
            "NOT RUN",
            view="Detailing",
            note="Calculate required",
            inp=inp,
            overview_key="link_detailing:scope",
            overview_parent="link_detailing",
            overview_placeholder=True,
        ))
    elif transverse is not None and inp.get("transverse_detailing_on"):
        checks = transverse.get("checks") or []
        transverse_note = (
            result_reason(
                transverse.get("reason"),
                "transverse_reinforcement",
                context="transverse-reinforcement summary reason",
            )
            if transverse.get("reason")
            else str(transverse.get("edition") or "")
        )
        governing_utilisation = _publication_metric(
            transverse.get("governing_utilisation")
        )
        if governing_utilisation is not None and governing_utilisation < 0.0:
            governing_utilisation = None
        rows.append(_summary_row(
            "Shear/torsion link detailing",
            "plastic",
            _map_assessment_status(transverse.get("status")),
            result=(
                "-"
                if governing_utilisation is None
                else _percent(governing_utilisation)
            ),
            criterion=(
                "-" if governing_utilisation is None else "<= 100 %"
            ),
            util=governing_utilisation,
            view="Detailing",
            note=transverse_note,
            inp=inp,
            overview_key="link_detailing",
            overview_parent="link_detailing",
        ))
        labels = {
            "minimum_ratio": "minimum ratio",
            "longitudinal_spacing": "longitudinal spacing",
            "transverse_leg_spacing": "transverse leg spacing",
            "torsion_spacing": "closed-link spacing",
            "required_links": "required links",
            "minimum_link_applicability": "minimum-link applicability",
        }
        for check in checks:
            kind = str(check.get("kind") or "")
            check_label = labels.get(kind, kind)
            if kind == "transverse_leg_spacing" and check.get("measurement_axis"):
                check_label += f" along {check['measurement_axis']}"
            provided = check.get("provided")
            limit = check.get("limit")
            if kind == "required_links":
                result_text = "No links defined"
                criterion = "Links required"
            elif kind == "minimum_ratio":
                result_text = (
                    "-"
                    if provided is None
                    else f"{_RHO}w,prov = {float(provided):.5f}"
                )
                criterion = (
                    "-"
                    if limit is None
                    else f"{_RHO}w,prov >= {_RHO}w,min = {float(limit):.5f}"
                )
            else:
                result_text = (
                    "-"
                    if provided is None
                    else f"sprov = {float(provided):.1f} mm"
                )
                criterion = (
                    "-"
                    if limit is None
                    else f"sprov <= smax = {float(limit):.1f} mm"
                )
            note = "; ".join(
                part for part in (
                    str(check.get("clause") or ""),
                    (
                        result_reason(
                            check.get("reason"),
                            "transverse_reinforcement",
                            context="transverse-reinforcement check reason",
                        )
                        if check.get("reason")
                        else ""
                    ),
                    (
                        "spacing " + str(check.get("spacing_source"))
                        if check.get("spacing_source") else ""
                    ),
                )
                if part
            )
            rows.append(_summary_row(
                f"{check.get('scope', 'Shear/torsion links')} "
                f"{check_label}",
                "plastic",
                _map_assessment_status(check.get("status")),
                result_text,
                criterion,
                check.get("utilisation"),
                "Detailing",
                note,
                inp,
                overview_key=f"link_detailing:{kind or 'unspecified'}",
                overview_parent="link_detailing",
            ))

    spacing = results.get("clear_spacing")
    if spacing is None and inp.get("clear_spacing_on"):
        rows.append(_summary_row(
            "Reinforcement clear spacing", "section", "NOT RUN",
            view="Detailing", note="Calculate required", inp=inp,
            overview_key="clear_spacing",
        ))
    elif spacing is not None and inp.get("clear_spacing_on"):
        governing = spacing.get("governing") or {}
        clear = governing.get("clear_mm")
        required = governing.get("required_mm")
        util = (
            float(required) / float(clear)
            if required is not None and clear is not None and float(clear) > 0.0
            else math.inf if governing and required is not None else None
        )
        result_text = (
            f"{clear:.1f} mm ({governing.get('first_id', '?')}-"
            f"{governing.get('second_id', '?')})"
            if clear is not None else "-"
        )
        criterion = f">= {required:.1f} mm" if required is not None else "-"
        rows.append(_summary_row(
            "Reinforcement clear spacing",
            "section",
            _map_assessment_status(spacing.get("status")),
            result_text,
            criterion,
            util,
            "Detailing",
            str(spacing.get("clause") or ""),
            inp,
            overview_key="clear_spacing",
        ))

    shear = results.get("shear")
    shear_torsion = results.get("torsion")
    if shear is None and inp.get("shear_on"):
        rows.append(_summary_row(
            "Shear", "plastic", "NOT RUN",
            view="Shear", note="Calculate required", inp=inp,
            overview_key="shear:scope",
            overview_parent="shear",
            overview_placeholder=True,
        ))
    elif shear is not None and inp.get("shear_on"):
        if shear_publication_input_is_current(
            inp,
            shear,
            plastic_result=results.get("plastic"),
            validate_directions=False,
            torsion_result=shear_torsion,
        )[0] is not True:
            shear = {}
        links_selected = inp.get("shear_links") is True

        def append_direction(component, direction):
            suffix = {"vx": " Vx", "vy": " Vy"}.get(component, "")
            action_label = {"vx": "Vx,Ed", "vy": "Vy,Ed"}.get(component, "VEd")
            if shear_direction_publication_input_is_current(
                inp, direction, plastic_result=results.get("plastic"),
                torsion_result=shear_torsion,
            )[0] is not True:
                direction = {}
            if capacity.validated_signed_shear_demand(direction) is None:
                note = result_reason(
                    "retained shear action evidence is unavailable",
                    "shear",
                    context="shear summary signed action",
                )
                rows.append(_summary_row(
                    f"Shear{suffix} without links",
                    "plastic",
                    "NOT ASSESSED",
                    "-",
                    "-",
                    None,
                    "Shear",
                    note,
                    inp,
                    overview_key="shear:without_links",
                    overview_parent="shear",
                ))
                if links_selected:
                    rows.append(_summary_row(
                        f"Shear{suffix} with links",
                        "plastic",
                        "NOT ASSESSED",
                        "-",
                        "-",
                        None,
                        "Shear",
                        note,
                        inp,
                        overview_key="shear:with_links",
                        overview_parent="shear",
                    ))
                return
            direction_result = direction.get("res") or {}
            geometry_record = direction.get("shear_geometry") or {}
            direction_state = str(
                direction_result.get("calculation_state") or ""
            ).upper()
            selected_resistance = nominal_shear_resistance(
                direction,
                links_selected=links_selected,
                input_payload=inp,
                torsion_result=shear_torsion,
            )
            selected_route = selected_resistance.get("route")
            resistance = direction_result.get("vrd_c")
            concrete_current = concrete_shear_publication_input_is_current(
                inp, direction
            )[0] is True
            concrete_utilisation = _publication_utilisation(
                direction.get("util")
            )
            concrete_component_available = bool(
                concrete_current
                and direction_result.get("valid") is True
                and _publication_metric(resistance) is not None
                and _publication_metric(resistance) > 0.0
                and concrete_utilisation is not None
            )
            result = (
                f"{_percent(direction.get('util'))} "
                f"({action_label} / VRd,c)"
                if resistance is not None else "-"
            )
            result_criterion = "<= 100 %"
            result_utilisation = direction.get("util")
            if (
                selected_resistance.get("valid") is not True
                and concrete_component_available
            ):
                without_links_status = (
                    "PASS"
                    if concrete_utilisation <= 1.0
                    else "NOT APPLICABLE"
                )
                without_links_note = (
                    str(direction.get("method") or "")
                    + "; the concrete-only component remains current. The "
                      "selected provided-link route is NOT ASSESSED and is "
                      "reported separately."
                )
            elif selected_resistance.get("valid") is not True:
                without_links_status = str(
                    selected_resistance.get("status") or "NOT ASSESSED"
                ).upper()
                result = "-"
                result_criterion = "-"
                result_utilisation = None
                without_links_note = result_reason(
                    selected_resistance.get("reason")
                    or direction_result.get("reason"),
                    "shear",
                    context="shear summary nominal-resistance reason",
                )
            elif selected_route == "links":
                without_links_status = "NOT APPLICABLE"
                without_links_note = (
                    "The action exceeds VRd,c; the designed-link resistance route applies"
                )
            elif direction_state == "NOT ASSESSED":
                without_links_status = "NOT ASSESSED"
                without_links_note = result_reason(
                    direction_result.get("reason"),
                    "shear",
                    context="shear summary geometry reason",
                )
            else:
                without_links_status = _util_summary_status(
                    direction.get("util"),
                    valid=bool(direction_result.get("valid")),
                )
                without_links_note = (
                    str(direction.get("method") or "")
                    + (
                        "; selected nominal resistance route; provided-link resistance "
                        "and detailing are reported separately"
                        if links_selected
                        else ""
                    )
                    + "; section form: "
                    + str(
                        geometry_record.get("resolved_form")
                        or geometry_record.get("section_form")
                        or "-"
                    )
                    + "; web duct condition: "
                    + str(geometry_record.get("duct_case") or "-")
                )
            rows.append(_summary_row(
                f"Shear{suffix} without links",
                "plastic",
                without_links_status,
                result,
                result_criterion,
                result_utilisation,
                "Shear",
                without_links_note,
                inp,
                overview_key="shear:without_links",
                overview_parent="shear",
            ))
            if not links_selected:
                return
            links = direction.get("links")
            if links is None:
                rows.append(_summary_row(
                    f"Shear{suffix} with links", "plastic", "NOT ASSESSED",
                    view="Shear", note="Selected method does not evaluate links",
                    inp=inp,
                    overview_key="shear:with_links",
                    overview_parent="shear",
                ))
            elif not isinstance(links, Mapping):
                rows.append(_summary_row(
                    f"Shear{suffix} with links",
                    "plastic",
                    "NOT ASSESSED",
                    "-",
                    "-",
                    None,
                    "Shear",
                    result_reason(
                        "provided-link resistance evidence is unavailable",
                        "shear",
                        context="provided-link resistance assessment",
                    ),
                    inp,
                    overview_key="shear:with_links",
                    overview_parent="shear",
                ))
            else:
                retained_link_result = links.get("res")
                link_result = (
                    retained_link_result
                    if isinstance(retained_link_result, Mapping)
                    else {}
                )
                provided_link = provided_link_publication_assessment(
                    inp, direction, torsion_result=shear_torsion,
                )
                if selected_resistance.get("valid") is not True:
                    rows.append(_summary_row(
                        f"Shear{suffix} with links",
                        "plastic",
                        "NOT ASSESSED",
                        "-",
                        "-",
                        None,
                        "Shear",
                        result_reason(
                            selected_resistance.get("reason"),
                            "shear",
                            context="shear summary unavailable nominal route",
                        ),
                        inp,
                        overview_key="shear:with_links",
                        overview_parent="shear",
                    ))
                    return
                if provided_link.valid is not True:
                    explicit_reason = None
                    if (
                        link_result.get("valid") is False
                        and link_result.get("calculation_state")
                        == "NOT ASSESSED"
                    ):
                        explicit_reason = (
                            links.get("assessment_reason")
                            or link_result.get("reason")
                        )
                    rows.append(_summary_row(
                        f"Shear{suffix} with links",
                        "plastic",
                        "NOT ASSESSED",
                        "-",
                        "-",
                        None,
                        "Shear",
                        result_reason(
                            explicit_reason or provided_link.reason,
                            "shear",
                            context="provided-link resistance assessment",
                        ),
                        inp,
                        overview_key="shear:with_links",
                        overview_parent="shear",
                    ))
                    return
                chord_publication = (
                    provided_link_longitudinal_publication_assessment(
                        inp,
                        direction,
                        torsion_result=(
                            (shear_torsion.get("directional_interactions") or {}).get(
                                component
                            )
                            if isinstance(shear_torsion, Mapping)
                            and isinstance(
                                shear_torsion.get("directional_interactions"),
                                Mapping,
                            )
                            else shear_torsion
                        ),
                    )
                )
                chord_assessment = chord_publication.get("assessment")
                if chord_publication.get("valid") is not True:
                    chord_assessment = {
                        "status": "NOT ASSESSED",
                        "ok": None,
                        "util": None,
                        "reason": "longitudinal chord evidence is unavailable",
                        "coverage_complete": False,
                        "governing": None,
                    }
                if selected_route == "concrete" and selected_resistance.get("valid"):
                    link_geometry = links.get("shear_geometry") or geometry_record
                    angle_applicability = link_result.get(
                        "angle_applicability"
                    ) or links.get("angle_applicability")
                    link_note = (
                        "The concrete route is applicable because the action does "
                        "not exceed VRd,c. The provided-link resistance is an "
                        "independent non-governing resistance subcheck; "
                        "minimum reinforcement and link detailing are assessed "
                        "separately."
                    )
                    if link_result.get("valid"):
                        link_factor = _publication_metric(
                            links.get("asw_factor")
                        )
                        if link_factor is None:
                            link_factor = 1.0
                        link_note += (
                            "; section form: "
                            + str(
                                link_geometry.get("resolved_form")
                                or link_geometry.get("section_form")
                                or "-"
                            )
                            + f"; effective Asw factor "
                            f"{link_factor:.5f}"
                            + "; "
                            + result_reason(
                                link_result.get("governs"),
                                "shear",
                                context="non-governing provided-link resistance",
                            )
                        )
                    if (
                        isinstance(angle_applicability, dict)
                        and angle_applicability.get("active", True) is True
                        and angle_applicability.get("applicable") is False
                    ):
                        link_note += "; " + result_reason(
                            link_result.get("reason"),
                            "shear",
                            context="inactive out-of-range provided-link result",
                        )
                        rows.append(_summary_row(
                            f"Shear{suffix} with links",
                            "plastic",
                            "NOT ASSESSED",
                            "-",
                            "-",
                            None,
                            "Shear",
                            link_note,
                            inp,
                            overview_key="shear:with_links",
                            overview_parent="shear",
                        ))
                        return
                    chord_active = False
                    chord_status = "NOT APPLICABLE"
                    chord_util = None
                    if isinstance(chord_assessment, dict):
                        chord_status = str(
                            chord_assessment.get("status") or "NOT ASSESSED"
                        ).upper()
                        chord_util = chord_assessment.get("util")
                        chord_active = chord_status != "NOT APPLICABLE"
                    overall_status = provided_link.status
                    overall_result = (
                        f"{_percent(provided_link.utilisation)} (non-governing)"
                    )
                    overall_util = provided_link.utilisation
                    if chord_active:
                        link_note += "; " + result_reason(
                            chord_assessment.get("reason"),
                            "shear",
                            context="dependent longitudinal chord assessment",
                        )
                    rows.append(_summary_row(
                        f"Shear{suffix} with links",
                        "plastic",
                        overall_status,
                        overall_result,
                        "<= 100 %",
                        overall_util,
                        "Shear",
                        link_note,
                        inp,
                        overview_key="shear:with_links",
                        overview_parent="shear",
                    ))
                    if chord_active:
                        rows.append(_summary_row(
                            f"Shear{suffix} longitudinal chords",
                            "plastic",
                            chord_status,
                            _percent(chord_util),
                            "<= 100 %",
                            chord_util,
                            "Shear",
                            result_reason(
                                chord_assessment.get("reason"),
                                "shear",
                                context="shear longitudinal chord assessment",
                            ),
                            inp,
                            overview_key="shear:longitudinal_chords",
                            overview_parent="shear",
                        ))
                    return
                link_status = provided_link.status
                link_util = provided_link.utilisation
                overall_status = link_status
                overall_util = link_util
                overall_note = result_reason(
                    links.get("assessment_reason")
                    or link_result.get("reason")
                    or link_result.get("governs")
                    or "the calculated face-aligned arm is unavailable",
                    "shear",
                    context="shear summary link reason",
                )
                link_geometry_note = ""
                if link_result.get("valid"):
                    link_geometry = links.get("shear_geometry") or geometry_record
                    link_geometry_note = (
                        "; section form: "
                        + str(
                            link_geometry.get("resolved_form")
                            or link_geometry.get("section_form")
                            or "-"
                        )
                        + f"; effective Asw factor "
                        f"{float(links.get('asw_factor', 1.0)):.5f}"
                        + f"; compression-field bw "
                        f"{float(link_result.get('bw', direction.get('bw', 0.0))):.1f} mm"
                        + "; web duct condition: "
                        + str(link_geometry.get("duct_case") or "-")
                    )
                if isinstance(chord_assessment, dict):
                    chord_status = str(
                        chord_assessment.get("status") or "NOT ASSESSED"
                    ).upper()
                    chord_util = chord_assessment.get("util")
                overall_note += link_geometry_note
                rows.append(_summary_row(
                    f"Shear{suffix} with links",
                    "plastic",
                    overall_status,
                    _percent(overall_util),
                    "<= 100 %",
                    overall_util,
                    "Shear",
                    overall_note,
                    inp,
                    overview_key="shear:with_links",
                    overview_parent="shear",
                ))
                if isinstance(chord_assessment, dict):
                    rows.append(_summary_row(
                        f"Shear{suffix} longitudinal chords",
                        "plastic",
                        chord_status,
                        _percent(chord_util),
                        "<= 100 %",
                        chord_util,
                        "Shear",
                        result_reason(
                            chord_assessment.get("reason"),
                            "shear",
                            context="shear longitudinal chord assessment",
                        ),
                        inp,
                        overview_key="shear:longitudinal_chords",
                        overview_parent="shear",
                    ))

        directions = shear.get("directions") or {}
        if directions:
            for component in ("vx", "vy"):
                if component in directions:
                    append_direction(component, directions[component])
            if shear.get("biaxial"):
                rows.append(_summary_row(
                    "Generic cross-direction shear interaction",
                    "plastic",
                    "NOT CALCULATED",
                    result="Independent Vx and Vy calculations",
                    criterion="Not calculated",
                    view="Shear",
                    note="No aggregate cross-direction verdict",
                    inp=inp,
                    overview_key="shear:cross_direction",
                ))
        else:
            append_direction("", shear)

    torsion = results.get("torsion")
    torsion_tube_valid = False
    torsion_transverse_resistance_assessed = False
    torsion_applicability_status = None
    torsion_applicability_blocks = False
    torsion_current = None
    torsion_current_reason = None
    if torsion is not None and inp.get("torsion_on"):
        torsion_current, torsion_current_reason = (
            torsion_publication_component_is_current(
                inp,
                results.get("shear"),
                torsion,
            )
        )
    if torsion is not None and inp.get("torsion_on") and torsion_current is not True:
        rows.append(_summary_row(
            "Torsion",
            "plastic",
            "NOT ASSESSED",
            "-",
            "-",
            None,
            "Torsion",
            result_reason(
                torsion_current_reason,
                "torsion",
                context="torsion summary current-evidence reason",
            ),
            inp,
            overview_key="torsion",
        ))
    elif torsion is None and inp.get("torsion_on"):
        rows.append(_summary_row(
            "Torsion", "plastic", "NOT RUN",
            view="Torsion", note="Calculate required", inp=inp,
            overview_key="torsion",
        ))
    elif torsion is not None and inp.get("torsion_on"):
        (
            torsion_rows, torsion_tube_valid,
            torsion_transverse_resistance_assessed, torsion_applicability_blocks,
        ) = _torsion_component_summary_rows(inp, results, torsion)
        rows.extend(torsion_rows)

    combined = results.get("combined")
    if combined is None and inp.get("combined_on"):
        dkna_basis = (
            inp.get("combined_method") == codes.EC2_2005_DKNA.label
        )
        torsion_not_assessed = (
            torsion is not None
            and (
                torsion_applicability_blocks
                or (
                    torsion_tube_valid
                    and not torsion_transverse_resistance_assessed
                )
            )
        )
        rows.append(_summary_row(
            (
                "Combined M-V-T - DK NA sum"
                if dkna_basis
                else "Combined M-V-T supported components"
            ),
            "plastic",
            "NOT ASSESSED" if torsion_not_assessed else "NOT RUN",
            view="M-V-T Combined",
            note=(
                result_reason(
                    torsion.get("assessment_reason")
                    or torsion.get("reason")
                    or "full torsion resistance not assessed",
                    "torsion",
                    context="combined summary torsion reason",
                )
                if torsion_not_assessed
                else "Calculate required"
            ),
            inp=inp,
            overview_key=(
                "combined:dkna_sum" if dkna_basis else "combined:physical"
            ),
        ))
    elif (
        inp.get("combined_on")
        and (
            combined_blocker := combined_bending_assessment_blocker(
                results,
                inp,
            )
        )
        is not None
    ):
        dkna_basis = combined_uses_dkna(combined or inp)
        rows.append(_summary_row(
            (
                "Combined M-V-T - DK NA sum"
                if dkna_basis
                else "Combined M-V-T supported components"
            ),
            "plastic",
            "NOT ASSESSED",
            result="-",
            criterion="<= 100 %",
            util=None,
            view="M-V-T Combined",
            note=combined_blocker,
            inp=inp,
            overview_key=(
                "combined:dkna_sum" if dkna_basis else "combined:physical"
            ),
        ))
    elif (
        combined is not None
        and inp.get("combined_on")
        and not combined_uses_dkna(combined)
    ):
        rows.extend(_base_en_combined_summary_rows(inp, combined))
    elif (
        combined is not None
        and inp.get("combined_on")
        and combined_uses_dkna(combined)
    ):
        directions = combined.get("directions") or {}
        if combined.get("biaxial") and directions:
            for component in ("vx", "vy"):
                direction = directions.get(component)
                if not direction:
                    continue
                label = "Vx+T" if component == "vx" else "Vy+T"
                util = direction.get("dkna_sum")
                status = combined_dkna_status(direction)
                governing_note = combined_governing_assessment_note(direction)
                if governing_note:
                    direction_note = governing_note
                elif status == "NOT ASSESSED":
                    direction_note = (
                        "DK NA screen: "
                        + combined_dkna_screen_label(direction)
                        + "; "
                        + str(
                            direction.get("dkna_reason")
                            or "Action-alone resistance unavailable"
                        )
                    )
                else:
                    method = str(direction.get("method") or "")
                    direction_note = ((method + "; ") if method else "")
                    direction_note += (
                        "DK NA screen: "
                        + combined_dkna_screen_label(direction)
                        + "; "
                    )
                    assumption_note = combined_dkna_assumption_note(direction)
                    if assumption_note:
                        direction_note += assumption_note + " "
                    direction_note += (
                        "Internal cross-section resistance check; does not replace "
                        "a separate Annex F member and detailing assessment where "
                        "applicable"
                    )
                rows.append(_summary_row(
                    f"Combined {label} - DK NA sum",
                    "plastic",
                    status,
                    _percent(util),
                    "<= 100 %",
                    util,
                    "M-V-T Combined",
                    direction_note,
                    inp,
                    overview_key="combined:dkna_sum",
                ))
                if direction.get("valid"):
                    for physical in combined_physical_components(direction):
                        rows.append(_summary_row(
                            f"Combined {label} {physical['label'].lower()}",
                            "plastic",
                            physical["status"],
                            _percent(physical["util"]),
                            "<= 100 %",
                            physical["util"],
                            "M-V-T Combined",
                            physical["note"],
                            inp,
                            overview_key=f"combined:{physical['key']}",
                        ))
            rows.append(_summary_row(
                "Generic Vx-Vy-T interaction",
                "plastic",
                "NOT CALCULATED",
                result="Independent Vx+T and Vy+T calculations",
                criterion="Not calculated",
                view="M-V-T Combined",
                note="No aggregate cross-direction verdict",
                inp=inp,
                overview_key="combined:cross_direction",
            ))
            if stale and results:
                for row in rows:
                    if row["status"] not in {"NOT RUN", "NOT APPLICABLE"}:
                        previous = row["status"]
                        row["status"] = "STALE"
                        row["note"] = f"Last status: {previous}; inputs changed"
            return rows
        valid = bool(combined.get("valid"))
        dkna_valid = combined.get("dkna_valid", valid) is True
        util = combined.get("dkna_sum")
        missing = [
            label
            for key, label in (
                ("have_m", "M"),
                ("have_v", "V"),
                ("have_t", "T"),
            )
            if key in combined and not combined.get(key)
        ]
        if valid and dkna_valid:
            method_note = str(combined.get("method") or "")
            combined_note = ((method_note + "; ") if method_note else "")
            combined_note += (
                "DK NA screen: " + combined_dkna_screen_label(combined) + "; "
            )
            assumption_note = combined_dkna_assumption_note(combined)
            if assumption_note:
                combined_note += assumption_note + " "
            combined_note += (
                "Internal cross-section resistance check; does not replace a "
                "separate Annex F member and detailing assessment where applicable"
            )
        elif valid:
            combined_note = (
                "DK NA screen: "
                + combined_dkna_screen_label(combined)
                + "; "
                + result_reason(
                    combined.get("dkna_reason")
                    or "An action-alone resistance could not be determined",
                    "combined",
                    context="combined action-alone result reason",
                )
            )
        elif missing:
            combined_note = (
                "DK NA screen: "
                + combined_dkna_screen_label(combined)
                + "; Missing prerequisite: "
                + ", ".join(missing)
            )
            if combined.get("reason"):
                combined_note += "; " + result_reason(
                    combined["reason"],
                    "combined",
                    context="combined summary missing-prerequisite reason",
                )
        else:
            combined_note = (
                "DK NA screen: "
                + combined_dkna_screen_label(combined)
                + "; "
                + result_reason(
                    combined.get("reason") or "Combined calculation is invalid",
                    "combined",
                    context="combined summary result reason",
                )
            )
        combined_status = combined_dkna_status(combined)
        governing_note = combined_governing_assessment_note(combined)
        if governing_note:
            combined_note = governing_note
        rows.append(_summary_row(
            "Combined M-V-T - DK NA sum",
            "plastic",
            combined_status,
            _percent(util),
            "<= 100 %",
            util,
            "M-V-T Combined",
            combined_note,
            inp,
            overview_key="combined:dkna_sum",
        ))
        if valid:
            for component in combined_physical_components(combined):
                rows.append(_summary_row(
                    f"Combined {component['label'].lower()}",
                    "plastic",
                    component["status"],
                    _percent(component["util"]),
                    "<= 100 %",
                    component["util"],
                    "M-V-T Combined",
                    component["note"],
                    inp,
                    overview_key=f"combined:{component['key']}",
                ))

    heightened = results.get("heightened_crack_control")
    if isinstance(heightened, Mapping):
        rows.append(_heightened_crack_summary_row(heightened))

    if stale and results:
        for row in rows:
            retained_concrete_context = bool(
                row.get("overview_key") == "shear:without_links"
                and _publication_utilisation(row.get("util")) is not None
            )
            if (
                row["status"] not in {"NOT RUN", "NOT APPLICABLE"}
                or retained_concrete_context
            ):
                previous = row["status"]
                row["status"] = "STALE"
                row["note"] = f"Last status: {previous}; inputs changed"
    return rows


def _noncurrent_case_summary_rows(rows):
    """Withhold stale case values while retaining one row per result view."""

    retained = []
    withheld_groups = set()
    for source in rows:
        row = dict(source)
        view = str(row.get("view") or "")
        group = view or str(row.get("family") or "result")
        if group in withheld_groups:
            continue
        withheld_groups.add(group)
        row.update(
            status="NOT ASSESSED",
            result="-",
            criterion="-",
            util=None,
            note=(
                "Recalculate this action set before relying on the result"
            ),
        )
        retained.append(row)
    return retained


@publication_calculation_scope()
def multi_case_summary_rows(inp, results, *, stale=False):
    """Build one ordered result register across every canonical case row."""
    inp = inp or {}
    results = results or {}
    if "plastic_cases" not in inp and "elastic_cases" not in inp:
        return (
            result_summary_rows(inp, results, stale=stale)
            + fatigue_summary_rows(inp, results, stale=stale)
        )

    mode = str(inp.get("mode") or "")
    requested = {
        "plastic": (
            mode in {"Plastic", "Both"}
            or bool(inp.get("shear_on"))
            or bool(inp.get("torsion_on"))
            or bool(inp.get("combined_on"))
            or bool(inp.get("minimum_reinforcement_on"))
            or bool(inp.get("transverse_detailing_on"))
        ),
        "elastic": mode in {"Elastic", "Both"},
    }
    rows = []
    for family in ("plastic", "elastic"):
        if not requested[family]:
            continue
        result_key = f"{family}_cases"
        entries = results.get(result_key)
        if entries is None:
            contexts = []
            for record in case_analysis.case_records(inp, family):
                case_inp = (
                    case_analysis.plastic_case_input(inp, record)
                    if family == "plastic"
                    else case_analysis.elastic_case_input(inp, record)
                )
                contexts.append((
                    str(record.get(load_cases.NAME) or ""),
                    case_inp,
                    {},
                    True,
                ))
        else:
            contexts = _worked_case_contexts(inp, results, family)
        entry_list = list(entries or ())
        for index, (
            _case_name,
            authoritative_input,
            case_results,
            current,
        ) in enumerate(contexts):
            if authoritative_input is None and not current:
                # A removed or renamed retained row has no current input identity.
                continue
            if isinstance(authoritative_input, Mapping):
                case_inp = dict(authoritative_input)
            elif index < len(entry_list):
                actions = entry_list[index].get("actions") or {}
                case_inp = (
                    case_analysis.plastic_case_input(inp, actions)
                    if family == "plastic"
                    else case_analysis.elastic_case_input(inp, actions)
                )
            else:
                case_inp = dict(inp)
            # Clear spacing is section-wide and is appended once below.
            case_inp["clear_spacing_on"] = False
            if family == "elastic":
                # Reinforcement detailing is a plastic/member check. An elastic-case
                # snapshot may retain the global result for convenience, but it
                # must not manufacture a second PL-case publication row.
                case_inp["minimum_reinforcement_on"] = False
                case_inp["transverse_detailing_on"] = False
            if family == "elastic" and "transverse_reinforcement" in case_results:
                case_results = dict(case_results)
                case_results.pop("transverse_reinforcement", None)
            case_rows = result_summary_rows(
                case_inp,
                case_results,
                stale=stale,
            )
            if family == "plastic" and not current:
                case_rows = _noncurrent_case_summary_rows(case_rows)
            elif family == "elastic" and not current:
                case_rows = _noncurrent_case_summary_rows(case_rows)
            rows.extend(case_rows)
            if family != "plastic":
                continue

            vx_zero = abs(float(case_inp.get("shear_Vx", 0.0))) <= 0.0
            vy_zero = abs(float(case_inp.get("shear_Vy", 0.0))) <= 0.0
            v_zero = vx_zero and vy_zero
            t_zero = abs(float(case_inp.get("torsion_T_signed", 0.0))) <= 0.0
            if inp.get("shear_on"):
                for component, is_zero in (("Vx", vx_zero), ("Vy", vy_zero)):
                    if is_zero:
                        rows.append(_summary_row(
                            f"Shear {component}", "plastic", "NOT APPLICABLE",
                            result=f"{component},Ed = 0", view="Shear",
                            note="Zero component; not evaluated", inp=case_inp,
                            overview_key="shear:scope",
                            overview_parent="shear",
                            overview_placeholder=True,
                        ))
            if inp.get("torsion_on") and t_zero:
                rows.append(_summary_row(
                    "Torsion", "plastic", "NOT APPLICABLE",
                    result="TEd = 0", view="Torsion",
                    note="Zero action; not evaluated", inp=case_inp,
                    overview_key="torsion",
                ))
            if inp.get("combined_on") and (v_zero or t_zero):
                zero = (
                    "Vx,Ed = Vy,Ed = TEd = 0"
                    if v_zero and t_zero
                    else "Vx,Ed = Vy,Ed = 0" if v_zero else "TEd = 0"
                )
                rows.append(_summary_row(
                    "Combined M-V-T", "plastic", "NOT APPLICABLE",
                    result=zero, view="M-V-T Combined",
                    note="Zero action; not evaluated", inp=case_inp,
                    overview_key="combined:dkna_sum",
                ))
            shear_action_live = not v_zero and bool(inp.get("shear_on"))
            torsion_action_live = not t_zero and bool(inp.get("torsion_on"))
            transverse_live = shear_action_live or torsion_action_live
            if inp.get("transverse_detailing_on") and not transverse_live:
                rows.append(_summary_row(
                    "Shear/torsion link detailing",
                    "plastic",
                    "NOT APPLICABLE",
                    result="No active non-zero VEd or TEd",
                    view="Detailing",
                    note="Zero relevant action; not evaluated",
                    inp=case_inp,
                    overview_key="link_detailing:scope",
                    overview_parent="link_detailing",
                    overview_placeholder=True,
                ))
    # Clear spacing is a section-wide result, not a load-case result. Add it once
    # after the case loops rather than repeating it for every Plastic row.
    if inp.get("clear_spacing_on"):
        spacing_only_inp = dict(
            inp,
            mode="",
            plastic_case={},
            elastic_case={},
            minimum_reinforcement_on=False,
            transverse_detailing_on=False,
            shear_on=False,
            torsion_on=False,
            combined_on=False,
        )
        rows.extend(result_summary_rows(
            spacing_only_inp,
            {"clear_spacing": results.get("clear_spacing")}
            if results.get("clear_spacing") is not None else {},
            stale=stale,
        ))
    heightened = results.get("heightened_crack_control")
    if isinstance(heightened, Mapping):
        row = _heightened_crack_summary_row(heightened)
        if stale:
            previous = row["status"]
            row["status"] = "STALE"
            row["note"] = f"Last status: {previous}; inputs changed"
        rows.append(row)
    rows.extend(fatigue_summary_rows(inp, results, stale=stale))
    return rows


def overall_summary_status(rows):
    """Return the most conservative state represented in a summary table."""
    states = {row.get("status") for row in rows}
    for status in (
        "INVALID", "FAIL", "STALE", "REVIEW", "NOT ASSESSED", "CONDITIONAL",
        "NOT RUN", "PASS", "CALCULATED", "NOT CALCULATED", "NOT APPLICABLE",
    ):
        if status in states:
            return status
    return "NOT RUN"


def _governing_overview_utilisation(row):
    value = row.get("util")
    if (
        is_boolean_scalar(value)
        or not isinstance(value, Real)
    ):
        return None
    metric = float(value)
    if metric < 0.0 or metric == -math.inf or math.isnan(metric):
        return None
    return metric


def _governing_summary_selection(rows):
    """Return retained rows and the selected source index for each check type."""

    retained = []
    selected = {}
    order = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError("result overview rows must be objects")
        retained.append(row)
    parents_with_children = {
        str(row.get("overview_parent"))
        for row in retained
        if row.get("overview_parent")
        and not bool(row.get("overview_placeholder"))
    }
    for index, row in enumerate(retained):
        parent = str(row.get("overview_parent") or "")
        if row.get("overview_placeholder") and parent in parents_with_children:
            continue
        semantic_key = str(row.get("overview_key") or row.get("check") or "")
        key = (str(row.get("family") or ""), semantic_key)
        status = str(row.get("status") or "")
        rank = _GOVERNING_OVERVIEW_STATUS_RANK.get(status, -1)
        utilisation = _governing_overview_utilisation(row)
        if key not in selected:
            order.append(key)
            selected[key] = (index, row, rank, utilisation)
            continue
        _current_index, _current, current_rank, current_utilisation = selected[key]
        replace_current = rank < current_rank
        if rank == current_rank:
            replace_current = bool(
                utilisation is not None
                and (
                    current_utilisation is None
                    or utilisation > current_utilisation
                )
            )
        if replace_current:
            selected[key] = (index, row, rank, utilisation)
    return retained, order, selected


def governing_summary_rows(rows):
    """Select one conservative retained row per semantic check type."""

    _retained, order, selected = _governing_summary_selection(rows)
    return [dict(selected[key][1]) for key in order]


def governing_result_rows(rows):
    """Return selected rows that carry an applicable retained result."""

    return [
        dict(row)
        for row in rows
        if (
            row.get("overview_scope_in_result_table") is True
            or str(row.get("status") or "").upper()
            not in GOVERNING_OVERVIEW_INFORMATION_STATUSES
        )
    ]


def governing_information_rows(rows):
    """Return selected scope and calculation-state rows outside conclusions."""

    return [
        dict(row)
        for row in rows
        if (
            row.get("overview_scope_in_result_table") is not True
            and str(row.get("status") or "").upper()
            in GOVERNING_OVERVIEW_INFORMATION_STATUSES
        )
    ]


def non_governing_summary_rows(rows):
    """Return every retained row not selected for the governing overview."""

    retained, _order, selected = _governing_summary_selection(rows)
    selected_indices = {item[0] for item in selected.values()}
    return [
        dict(row)
        for index, row in enumerate(retained)
        if index not in selected_indices
    ]


def summary_governing_flags(rows):
    """Mark the largest utilisation among rows that carry acceptance verdicts."""
    def eligible(row):
        util = row.get("util")
        return bool(
            row.get("status") in {"PASS", "FAIL"}
            and util is not None
            and (math.isfinite(util) or util == math.inf)
        )

    candidates = [row["util"] for row in rows if eligible(row)]
    governing = max(candidates) if candidates else None
    return [
        bool(
            governing is not None
            and eligible(row)
            and (
                row["util"] == governing
                if governing == math.inf
                else math.isclose(
                    row["util"], governing, rel_tol=1e-12, abs_tol=1e-12
                )
            )
        )
        for row in rows
    ]


def summary_governing_case_flags(rows):
    """Mark the highest accepted utilisation for each check across cases."""
    eligible = {}
    for row in rows:
        util = row.get("util")
        if (
            row.get("status") in {"PASS", "FAIL"}
            and util is not None
            and (math.isfinite(util) or util == math.inf)
        ):
            eligible.setdefault(row.get("check"), []).append(util)
    governing = {
        check: max(values) for check, values in eligible.items() if values
    }
    flags = []
    for row in rows:
        value = governing.get(row.get("check"))
        util = row.get("util")
        flags.append(bool(
            value is not None
            and row.get("status") in {"PASS", "FAIL"}
            and util is not None
            and (
                util == value
                if value == math.inf
                else math.isclose(util, value, rel_tol=1e-12, abs_tol=1e-12)
            )
        ))
    return flags
