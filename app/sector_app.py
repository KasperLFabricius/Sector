"""Sector - reinforced-concrete cross-section analysis (Streamlit interface).

Define a section, select numerical methods and review calculation outputs and
demand-versus-resistance checks.
"""

from __future__ import annotations

import copy
import dataclasses
import functools
import logging
import math
import os
import pathlib
import re
import sys
import time
from datetime import datetime, timezone
from html import escape as _html_escape

# Make both the repo root (for ``sector``) and this app folder (for ``viz``)
# importable when run as a script or via Streamlit's AppTest.
_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import app_run_probe  # noqa: E402
from app import input_issues  # noqa: E402
from app import engineer_messages  # noqa: E402
from app import manual_information_architecture as manual_ia  # noqa: E402
from app import report_profiles  # noqa: E402
from deferred_import import deferred_module  # noqa: E402
from input_stage_host import (  # noqa: E402
    live_fragment_value,
    normalise_stage_selection,
    reset_input_stage_mounts,
    stateful_input_tabs,
)
from point_grid import point_grid, _rows_to_df, _versioned_rows  # noqa: E402
from sector import __author__ as sector_author  # noqa: E402
from sector import __licensee__ as sector_licensee  # noqa: E402
from sector import __version__ as sector_version  # noqa: E402
from sector import codes, design_standards  # noqa: E402
from sector.build_info import source_revision  # noqa: E402
from sector.engineer_message import EngineerMessage  # noqa: E402
from sector.materials import (  # noqa: E402
    ES as STEEL_REFERENCE_MODULUS,
    builtin_prestress_design_ordinate_is_positive_finite,
    design_ordinate_is_positive_finite,
    design_ultimate_not_below_yield,
    governing_yield_strain,
)
from sector.sls_identity import (  # noqa: E402
    HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY,
    LONG_TERM_PERMITTED_CRACK_WIDTH_KEY,
    LONG_TERM_PERMITTED_CRACK_WIDTH_SOURCE,
    SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY,
    SHORT_TERM_PERMITTED_CRACK_WIDTH_SOURCE,
)

# The app has many independent calculation and publication surfaces. Keep their
# modules inert until the active input stage or requested result actually reaches
# them; importing a hidden stage must not dominate first render time.
case_analysis = deferred_module("case_analysis")
fatigue_analysis = deferred_module("fatigue_analysis")
fatigue_inputs = deferred_module("fatigue_inputs")
fatigue_presentation = deferred_module("fatigue_presentation")
load_cases = deferred_module("load_cases")
mat_catalog = deferred_module("material_catalog")
project_io = deferred_module("project_io")
rebar_table = deferred_module("reinforcement_table")
presentation = deferred_module("result_presentation")
heightened_adapter = deferred_module("heightened_crack_adapter")
session_state_migrations = deferred_module("session_state_migrations")
table_fields = deferred_module("app.table_field_definitions")
modelled_direction = deferred_module("app.modelled_direction")
viz = deferred_module("viz")

capacity = deferred_module("sector.capacity")
combined = deferred_module("sector.combined")
detailing = deferred_module("sector.detailing")
elastic_core = deferred_module("sector.elastic")
geometry = deferred_module("sector.geometry")
kernels = deferred_module("sector.kernels")
mp = deferred_module("sector.material_presets")
plastic_core = deferred_module("sector.plastic")
section_core = deferred_module("sector.section")
serviceability_core = deferred_module("sector.serviceability")
heightened_crack_control_core = deferred_module(
    "sector.heightened_crack_control"
)
shear = deferred_module("sector.shear")
sls_core = deferred_module("sector.sls")
templates = deferred_module("sector.templates")
torsion = deferred_module("sector.torsion")


def solve_elastic_combined(*args, **kwargs):
    return elastic_core.solve_elastic_combined(*args, **kwargs)


def transformed_properties(*args, **kwargs):
    return elastic_core.transformed_properties(*args, **kwargs)


def solve_interaction(*args, **kwargs):
    return plastic_core.solve_interaction(*args, **kwargs)


def solve_plastic(*args, **kwargs):
    return plastic_core.solve_plastic(*args, **kwargs)


def analyse_cracking(*args, **kwargs):
    return serviceability_core.analyse_cracking(*args, **kwargs)


def combined_cracking(*args, **kwargs):
    return serviceability_core.combined_cracking(*args, **kwargs)


def crack_width(*args, **kwargs):
    return serviceability_core.crack_width(*args, **kwargs)


def evaluate_crack_width(*args, **kwargs):
    return serviceability_core.evaluate_crack_width(*args, **kwargs)

# The tool version comes from the sector package (the single source of truth); it
# shows in the title, the browser tab, the About panel and the report footer.
APP_VERSION = sector_version
APP_AUTHOR = sector_author
APP_LICENSEE = sector_licensee
APP_EMAIL = "Kasper.LindskovFabricius@sweco.dk"
ROOT = pathlib.Path(__file__).resolve().parent.parent
_LOGGER = logging.getLogger(__name__)

# Greek glyphs for the result tables (st.dataframe renders plain Unicode, not LaTeX,
# so widget labels use $...$ but table headers/cells use these). Written via chr()
# so the source stays ASCII (BMP code points, no surrogate pairs).
_EPS, _SIGMA, _RHO, _PHI = chr(0x3B5), chr(0x3C3), chr(0x3C1), chr(0x3C6)
_GAMMA = chr(0x3B3)
_KAPPA = chr(0x3BA)
_THETA, _NU, _ALPHA, _DELTA = chr(0x3B8), chr(0x3BD), chr(0x3B1), chr(0x394)
_TAU = chr(0x3C4)
_PERMILLE = chr(0x2030)
_DEG = chr(0x00B0)

# EC2 7.11 bond coefficient k1 by bar surface (cannot be inferred from geometry).
_BOND_K1 = {"Ribbed / high bond (k1 = 0.8)": 0.8, "Plain round (k1 = 1.6)": 1.6}

# Lightweight UI identities for the optional fatigue controls. The active
# fatigue adapter validates these exact retained solver identities again when a
# calculation is requested; opening Analysis settings must not import the full
# elastic fatigue engine merely to populate a select box.
_FATIGUE_CONCRETE_MINER = "Explicit Palmgren-Miner spectrum"
_FATIGUE_CONCRETE_PROJECT_MINER = "User-defined Miner S-N relation"
_FATIGUE_CONCRETE_EQUIVALENT = "Damage-equivalent stress amplitude"
_FATIGUE_CONCRETE_METHODS = (
    _FATIGUE_CONCRETE_MINER,
    _FATIGUE_CONCRETE_PROJECT_MINER,
    _FATIGUE_CONCRETE_EQUIVALENT,
)
_FATIGUE_ASSIGNMENT_MESSAGE = EngineerMessage(
    "FATIGUE-ASSIGNMENT",
    "One or more fatigue details are undefined; review the reinforcement assignments",
)
_FATIGUE_DISPLAY_ERROR = EngineerMessage(
    "FATIGUE-DISPLAY-ERROR",
    "Review the fatigue inputs and recalculate",
)
_FATIGUE_DISPLAY_WARNING = EngineerMessage(
    "FATIGUE-DISPLAY-WARNING",
    "Review the selected fatigue basis before using the result",
)
_INPUT_ISSUE_DISPLAY = EngineerMessage(
    "INPUT-ISSUE",
    "Review the highlighted input before calculating",
)
_INPUT_FOCUS_DISPLAY = EngineerMessage(
    "INPUT-FOCUS",
    "Review the cited input before calculating",
)
_REPORT_INPUTS_REQUIRED = EngineerMessage(
    "REPORT-INPUTS",
    "Open Inputs once to initialise the section before generating a report",
)
_REPORT_SECTION_REQUIRED = EngineerMessage(
    "REPORT-SECTION",
    "Define a valid section and resolve any geometry or reinforcement issue before generating a report",
)
_REPORT_PREFLIGHT_DISPLAY = EngineerMessage(
    "REPORT-PREFLIGHT",
    "Review the calculation inputs before generating a report",
)
_REPORT_REUSED_RESULTS = EngineerMessage(
    "REPORT-GENERATED-REUSED",
    "Report generated using the matching current Analysis results",
)
_REPORT_RECALCULATED_RESULTS = EngineerMessage(
    "REPORT-GENERATED-RECALCULATED",
    "Report generated after recalculating the current inputs",
)
_REPORT_GENERATION_FAILED = EngineerMessage(
    "REPORT-GENERATION",
    "Report generation failed. Review the current inputs, recalculate, and try again",
)
_MILD_RUPTURE_STRESS = EngineerMessage(
    "MILD-RUPTURE-STRESS",
    "Enter a positive ultimate tensile strength for the selected mild-steel curve",
)
_PRESTRESS_STRENGTHS = EngineerMessage(
    "PRESTRESS-STRENGTHS",
    "Enter positive proof and ultimate strengths for the selected prestressing curve",
)
_MILD_YIELD_STRENGTHS = EngineerMessage(
    "MILD-YIELD-STRENGTHS",
    "Enter a positive tensile yield strength and a non-negative compression yield strength",
)
_MATERIAL_RUPTURE_STRAIN = EngineerMessage(
    "MATERIAL-RUPTURE-STRAIN",
    "Enter a positive rupture strain above every active yield point",
)
_MATERIAL_STRENGTH_ORDER = EngineerMessage(
    "MATERIAL-STRENGTH-ORDER",
    "Enter strengths and partial factors so the design ultimate strength is not less than every active design yield or proof strength",
)
_MATERIAL_K_RANGE = EngineerMessage(
    "MATERIAL-K-RANGE",
    "Enter k greater than zero and not greater than 1",
)
_MATERIAL_YIELD_OFFSETS = EngineerMessage(
    "MATERIAL-YIELD-OFFSETS",
    "Enter non-negative yield offsets that keep each yield point below rupture",
)
_PRESTRESS_PRESTRAIN = EngineerMessage(
    "PRESTRESS-PRESTRAIN",
    "Enter a finite non-negative prestrain below the rupture strain",
)
_PRESTRESS_DESIGN_STRESS = EngineerMessage(
    "PRESTRESS-DESIGN-STRESS",
    "Enter a prestressing partial factor that gives a finite positive design stress",
)
_MATERIAL_PARTIAL_FACTORS = EngineerMessage(
    "MATERIAL-PARTIAL-FACTORS",
    "Enter positive finite material partial factors for the selected curve",
)
_MATERIAL_MODULUS = EngineerMessage(
    "MATERIAL-MODULUS",
    "Enter a positive finite reinforcement modulus for the selected curve",
)
_MATERIAL_DEFINITION_DISPLAY = EngineerMessage(
    "MATERIAL-DEFINITION",
    "Review the selected material values",
)
_BAR_MATERIAL_ASSIGNMENT = EngineerMessage(
    "BAR-MATERIAL-ASSIGNMENT",
    "Assign every reinforcing bar to a defined mild-steel material",
)
_TENDON_MATERIAL_ASSIGNMENT = EngineerMessage(
    "TENDON-MATERIAL-ASSIGNMENT",
    "Assign every tendon to a defined prestressing-steel material",
)
_MEMBER_MATERIAL_ASSIGNMENT = EngineerMessage(
    "MEMBER-MATERIAL-ASSIGNMENT",
    "Select a defined mild-steel material for the member checks",
)
_MATERIAL_INPUT_BLOCKER = EngineerMessage(
    "MATERIAL-INPUT-BLOCKER",
    "Resolve the material definitions and assignments before calculating",
)
_TORSION_GAMMA_CT_INPUT = EngineerMessage(
    "TORSION-GAMMA-CT",
    "Enter a positive finite concrete tensile partial factor gamma_ct",
)
_SECTION_GEOMETRY_DISPLAY = EngineerMessage(
    "SECTION-GEOMETRY",
    "Review the concrete outline and voids",
)
_SECTION_TOPOLOGY_MESSAGES = {
    "malformed-ring": EngineerMessage(
        "SECTION-RING-SHAPE",
        "Enter each concrete boundary as a numeric list of x-y points",
    ),
    "too-few-points": EngineerMessage(
        "SECTION-RING-POINTS",
        "Enter at least three distinct points for every concrete boundary",
    ),
    "non-finite-point": EngineerMessage(
        "SECTION-FINITE-POINTS",
        "Enter finite x and y coordinates for every concrete-boundary point",
    ),
    "repeated-point": EngineerMessage(
        "SECTION-REPEATED-POINT",
        "Remove repeated or coincident points from the concrete boundary",
    ),
    "degenerate-area": EngineerMessage(
        "SECTION-DEGENERATE-AREA",
        "Adjust the concrete-boundary points to enclose a positive area",
    ),
    "backtracking-edge": EngineerMessage(
        "SECTION-BACKTRACKING-EDGE",
        "Adjust the concrete boundary so adjacent edges do not overlap or reverse",
    ),
    "self-intersection": EngineerMessage(
        "SECTION-SELF-INTERSECTION",
        "Adjust the concrete boundary so its edges do not cross or touch",
    ),
    "hole-boundary-contact": EngineerMessage(
        "SECTION-VOID-BOUNDARY",
        "Move each void wholly inside the concrete without touching the outer boundary",
    ),
    "hole-outside": EngineerMessage(
        "SECTION-VOID-OUTSIDE",
        "Move each void wholly inside the outer concrete boundary",
    ),
    "hole-overlap": EngineerMessage(
        "SECTION-VOID-OVERLAP",
        "Adjust the voids so they do not overlap or touch",
    ),
    "nested-hole": EngineerMessage(
        "SECTION-NESTED-VOID",
        "Remove nested void boundaries from the section geometry",
    ),
}
_SECTION_DISCONNECTED = EngineerMessage(
    "SECTION-DISCONNECTED",
    "Adjust the voids so the concrete outline remains connected",
)
_REINFORCEMENT_OUTSIDE = EngineerMessage(
    "REINFORCEMENT-OUTSIDE",
    "Move every bar and tendon inside the concrete and outside the voids",
)
_REINFORCEMENT_ROW_INPUT = EngineerMessage(
    "REINFORCEMENT-ROW-INPUT",
    "Enter finite coordinates and a positive area and diameter for every bar and tendon",
)
_QUICK_SECTION_DISPLAY = EngineerMessage(
    "QUICK-SECTION",
    "Review the section dimensions and reinforcement layout",
)
_QUICK_BOTTOM_COVER = EngineerMessage(
    "QUICK-BOTTOM-COVER",
    "Reduce the bottom reinforcement cover or enlarge the available section width",
)
_QUICK_TOP_COVER = EngineerMessage(
    "QUICK-TOP-COVER",
    "Reduce the top reinforcement cover or enlarge the available section width",
)
_QUICK_TENDON_COVER = EngineerMessage(
    "QUICK-TENDON-COVER",
    "Reduce the tendon cover or enlarge the available section width",
)
_QUICK_REINFORCEMENT_PLACEMENT = EngineerMessage(
    "QUICK-REINFORCEMENT-PLACEMENT",
    "Adjust the section size, bar diameter, cover, or layer spacing so every bar remains within concrete",
)


def _shear_codes():
    """Return retained shear/torsion editions when that stage needs them."""

    return capacity.SHEAR_CODES


def _shear_methods():
    """Return retained shear methods when that stage needs them."""

    return capacity.SHEAR_METHODS

app_run_probe.open_run(st.session_state)
_startup_probe = app_run_probe.start_phase(st.session_state, "startup")
st.set_page_config(
    layout="wide",
    page_title=f"Sector v{APP_VERSION}",
    initial_sidebar_state="collapsed",
)


@st.cache_resource(show_spinner=False)
def _warm_solver():
    """Compile the plastic kernels once, immediately before their first use.

    Starting this work at module import competed with Streamlit's first render and
    could leave a background compiler active while the engineer navigated.  The
    cached synchronous call keeps startup responsive and makes Calculate own the
    one-time warm-up it actually needs.
    """
    kernels.warmup()
    return True

_logo = ROOT / "assets" / "logo.png"
if _logo.exists():
    st.sidebar.image(str(_logo), width="stretch")

st.title(f"Sector v{APP_VERSION}")
st.caption("Reinforced-concrete cross-section analysis - elastic stresses and plastic capacity")


# ---------------------------------------------------------------------------
# Material parameters panel: one section per material, each with a preset
# dropdown (named curves + Eurocode editions), editable parameters and a live
# stress-strain diagram. A preset only prefills values; all stay editable.
# ---------------------------------------------------------------------------

_PRESET_HELP = (
    "Prefills a named stress-strain law (a named curve shape or a Eurocode "
    "edition). Direct inputs remain editable; edition-derived coefficients are "
    "read-only to keep the selected edition and numerical law aligned."
)

# Default material edition (Danish practice: DS/EN with the DK National Annex).
_DEFAULT_PRESET = "DS/EN 1992-1-1:2005 + DK NA:2024"

# DS/EN 1992-1-1:2023, 5.1.6(1): 0.85 is the general/other-case value. The value
# 1.00 is not an equivalent preference; it is an explicit applicability choice
# for the stated reference-age and delayed-design-loading conditions.
_KTC_CHOICES = {
    "0.85 - General / other cases (default)": 0.85,
    "1.00 - 5.1.6(1) reference-age and loading conditions": 1.0,
}


def _prefill(prefix, preset, presets):
    """Load a preset's defaults into the field keys when the selection changes."""
    prev = f"{prefix}_prev"
    if st.session_state.get(prev) != preset:
        for field, value in presets[preset].items():
            st.session_state[f"{prefix}_{field}"] = value
        st.session_state[prev] = preset


def _input_widget_kwargs(key, kwargs):
    """Attach the input-event journal while preserving an existing callback."""

    options = dict(kwargs)
    callback = options.pop("on_change", None)
    callback_args = tuple(options.pop("args", ()) or ())
    callback_kwargs = dict(options.pop("kwargs", {}) or {})
    options["on_change"] = _record_input_event
    options["args"] = (key, callback, callback_args, callback_kwargs)
    return options


def _manual_warning(box, warning_key, message):
    """Publish one warning tied to an indexed manual troubleshooting entry."""

    manual_ia.warning_reference(warning_key)
    return box.warning(message)


def _number(box, prefix, field, meta, help_map=None, disabled=False):
    label, lo, hi, step = meta[field]
    key = f"{prefix}_{field}"
    return box.number_input(
        label,
        float(lo),
        float(hi),
        step=float(step),
        key=key,
        **_input_widget_kwargs(
            key,
            {
                "help": (help_map or {}).get(field),
                "disabled": disabled,
            },
        ),
    )


def _seeded_number(box, label, lo, hi, default, step, key, **kw):
    """A number_input whose initial value is seeded into session state rather than
    passed as ``value=``.

    A loaded project (or an autosave restore) writes the widget key before the widget
    is created; a widget that also passes ``value=`` then trips Streamlit's "created
    with a default value but also had its value set via the Session State API"
    warning. Seeding via ``setdefault`` (a no-op once the key exists) and omitting
    ``value=`` avoids it while keeping the same default on a fresh session."""
    st.session_state.setdefault(key, default)
    return box.number_input(
        label, lo, hi, step=step, key=key,
        **_input_widget_kwargs(key, kw),
    )


def _seeded_checkbox(box, label, default, key, **kw):
    """A checkbox whose default is seeded into session state rather than passed as
    ``value=`` -- same reason as :func:`_seeded_number`: a loaded project writes the
    key before the widget is built, and a ``value=`` alongside it trips the warning."""
    st.session_state.setdefault(key, default)
    return box.checkbox(label, key=key, **_input_widget_kwargs(key, kw))


def _seeded_toggle(box, label, default, key, **kw):
    """A persisted on/off setting without a competing widget default."""

    st.session_state.setdefault(key, default)
    return box.toggle(label, key=key, **_input_widget_kwargs(key, kw))


def _seeded_selectbox(box, label, options, default, key, **kw):
    """A selectbox whose default is seeded into session state rather than passed as
    ``index=`` -- same reason as :func:`_seeded_number`. ``default`` must be one of
    ``options``."""
    st.session_state.setdefault(key, default)
    if st.session_state[key] not in options:
        st.session_state[key] = default
    return box.selectbox(
        label, options, key=key, **_input_widget_kwargs(key, kw)
    )


def _seeded_segmented_control(box, label, options, default, key, **kw):
    """A required single-choice segmented control with durable widget state."""

    st.session_state.setdefault(key, default)
    if st.session_state[key] not in options:
        raise ValueError(f"unknown persisted selection for {key!r}")
    return box.segmented_control(
        label,
        options,
        selection_mode="single",
        required=True,
        key=key,
        **_input_widget_kwargs(key, kw),
    )


def _seeded_text(box, label, default, key, **kw):
    """A persisted text input that does not conflict with loaded session state."""
    st.session_state.setdefault(key, default)
    return box.text_input(label, key=key, **_input_widget_kwargs(key, kw))


def _seeded_text_area(box, label, default, key, **kw):
    """A persisted multi-line input without a competing widget default."""

    st.session_state.setdefault(key, default)
    return box.text_area(label, key=key, **_input_widget_kwargs(key, kw))


_TORSION_GAMMA_METHOD_KEY = "_torsion_gamma_ct_default_method"
_TORSION_GAMMA_MANAGED_KEY = "_torsion_gamma_ct_uses_method_default"


def _mark_torsion_gamma_ct_custom():
    """Stop method changes from replacing an explicitly edited factor."""
    st.session_state[_TORSION_GAMMA_MANAGED_KEY] = False


def _seed_torsion_gamma_ct(method):
    """Seed or update the editable tensile factor from the selected method.

    A fresh input follows the method default. Once the engineer edits it, later
    method changes preserve that actual value. Loaded projects are marked
    explicit in :func:`_apply_pending_project` before this helper runs.
    """
    code = _shear_codes().get(method, codes.EC2_2005_DKNA)
    default = float(code.gamma_ct)
    previous_method = st.session_state.get(_TORSION_GAMMA_METHOD_KEY)
    if "torsion_gamma_ct" not in st.session_state:
        st.session_state["torsion_gamma_ct"] = default
        st.session_state[_TORSION_GAMMA_MANAGED_KEY] = True
    elif previous_method is None:
        st.session_state.setdefault(_TORSION_GAMMA_MANAGED_KEY, False)
    elif (
        previous_method != method
        and st.session_state.get(_TORSION_GAMMA_MANAGED_KEY, False)
    ):
        st.session_state["torsion_gamma_ct"] = default
        _journal_current_input_values("torsion_gamma_ct")
    st.session_state[_TORSION_GAMMA_METHOD_KEY] = method
    return default


def _safe_build(box, builder, curve, vals, **extra):
    """Build a material once and fail closed without changing entered values."""

    try:
        return builder(curve=curve, **vals, **extra)
    except Exception as exc:
        kind = "mild" if builder is mp.build_mild else "prestress"
        fallback = _material_definition_message(
            {"curve": curve, **vals, **extra}, kind
        )
        detail = engineer_messages.error_detail(
            exc,
            fallback=fallback,
            context="material curve construction",
        )
        _manual_warning(
            box,
            "input-invalid",
            f"Material unavailable: {detail}",
        )
        return None


def _material_definition_message(item, kind):
    """Return field-specific authored guidance for one active material curve."""

    def number(field):
        value = item.get(field)
        if isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return parsed if math.isfinite(parsed) else None

    def positive(field):
        value = number(field)
        return value is not None and value > 0.0

    def nonnegative(field):
        value = number(field)
        return value is not None and value >= 0.0

    try:
        curve = int(item.get("curve"))
        owned = set(
            mp.MILD_FIELDS_BY_CURVE[curve]
            if kind == "mild"
            else mp.PRESTRESS_FIELDS_BY_CURVE[curve]
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return _MATERIAL_DEFINITION_DISPLAY

    if "Es" in owned and not positive("Es"):
        return _MATERIAL_MODULUS
    factors = owned.intersection(("gamma_y", "gamma_u", "gamma_E"))
    if any(not positive(field) for field in factors):
        return _MATERIAL_PARTIAL_FACTORS

    Es = number("Es")
    gamma_y = number("gamma_y")
    gamma_u = number("gamma_u") if "gamma_u" in owned else gamma_y
    gamma_E = number("gamma_E") if "gamma_E" in owned else gamma_y

    if kind == "mild":
        if not positive("fytk") or not nonnegative("fyck"):
            return _MILD_YIELD_STRENGTHS
        if not positive("eut"):
            return _MATERIAL_RUPTURE_STRAIN
        compression_active = (
            item.get("active_in_compression", item.get("active_comp", True))
            and number("fyck") > 0.0
        )
        if (
            not design_ordinate_is_positive_finite(
                number("fytk"), gamma_y
            )
            or (
                compression_active
                and not design_ordinate_is_positive_finite(
                    number("fyck"), gamma_y
                )
            )
        ):
            return _MATERIAL_STRENGTH_ORDER
        if "futk" in owned:
            if not positive("futk"):
                return _MILD_RUPTURE_STRESS
            if (
                number("futk") < number("fytk")
                or not design_ultimate_not_below_yield(
                    number("futk"), gamma_u, number("fytk"), gamma_y
                )
                or (
                    curve == 3
                    and compression_active
                    and (
                        number("futk") < number("fyck")
                        or not design_ultimate_not_below_yield(
                            number("futk"), gamma_u, number("fyck"), gamma_y
                        )
                    )
                )
            ):
                return _MATERIAL_STRENGTH_ORDER
        if "k" in owned and not (
            number("k") is not None and 0.0 < number("k") <= 1.0
        ):
            return _MATERIAL_K_RANGE
        if "ey0t" in owned and not nonnegative("ey0t"):
            return _MATERIAL_YIELD_OFFSETS
        if (
            "ey0c" in owned
            and compression_active
            and not nonnegative("ey0c")
        ):
            return _MATERIAL_YIELD_OFFSETS

        modulus_factor = gamma_E if "gamma_E" in owned else gamma_y
        tension_yield = governing_yield_strain(
            number("fytk"), gamma_y, Es, modulus_factor
        )
        if tension_yield is None:
            return _MATERIAL_RUPTURE_STRAIN
        tension_yield += number("ey0t") if "ey0t" in owned else 0.0
        if not math.isfinite(tension_yield) or tension_yield >= number("eut"):
            return _MATERIAL_RUPTURE_STRAIN
        if compression_active:
            compression_yield = governing_yield_strain(
                number("fyck"), gamma_y, Es, modulus_factor
            )
            if compression_yield is None:
                return _MATERIAL_RUPTURE_STRAIN
            compression_yield += (
                number("ey0c") if "ey0c" in owned else 0.0
            )
            if (
                not math.isfinite(compression_yield)
                or compression_yield >= number("eut")
            ):
                return _MATERIAL_RUPTURE_STRAIN
        return _MATERIAL_DEFINITION_DISPLAY

    if not nonnegative("IS"):
        return _PRESTRESS_PRESTRAIN
    rupture = 35.0 if curve in (1, 2, 3, 4, 5) else number("eut")
    if rupture is None or rupture <= 0.0:
        return _MATERIAL_RUPTURE_STRAIN
    if number("IS") >= rupture:
        return _PRESTRESS_PRESTRAIN
    if curve in (1, 2, 3, 4, 5) and not (
        builtin_prestress_design_ordinate_is_positive_finite(curve, gamma_y)
    ):
        return _PRESTRESS_DESIGN_STRESS
    if curve in (6, 7):
        if not positive("fytk") or not positive("futk"):
            return _PRESTRESS_STRENGTHS
        if (
            not design_ordinate_is_positive_finite(
                number("fytk"), gamma_y
            )
            or number("futk") < number("fytk")
            or not design_ultimate_not_below_yield(
                number("futk"), gamma_u, number("fytk"), gamma_y
            )
        ):
            return _MATERIAL_STRENGTH_ORDER
        if "k" in owned and not (
            number("k") is not None and 0.0 < number("k") <= 1.0
        ):
            return _MATERIAL_K_RANGE
        if "ey0t" in owned and not nonnegative("ey0t"):
            return _MATERIAL_YIELD_OFFSETS
        proof_strain = governing_yield_strain(
            number("fytk"), gamma_y, Es, gamma_E
        )
        if proof_strain is None:
            return _MATERIAL_RUPTURE_STRAIN
        proof_strain += number("ey0t") if "ey0t" in owned else 0.0
        if not math.isfinite(proof_strain) or proof_strain >= rupture:
            return _MATERIAL_RUPTURE_STRAIN
    return _MATERIAL_DEFINITION_DISPLAY


def concrete_panel(box, locked=False, lock_elastic=False, *, heading=True):
    """Concrete material: preset, editable parameters and adjacent preview.

    ``locked`` (elastic-only mode) disables the parameters that do not affect the
    elastic results: gamma_c and alpha_cc set the design strength fcd, which is a
    plastic-only quantity. fck stays editable -- it feeds the serviceability fctm
    (the Auto button) -- and so does the preset, which prefills fck.
    ``lock_elastic`` (plastic-only mode) disables fctm and Ec, which only affect
    the elastic results.
    """
    if heading:
        box.markdown("**Concrete**")
    presets = mp.CONCRETE_PRESETS
    labels = list(presets)
    preset = _seeded_selectbox(box, "Preset", labels, _DEFAULT_PRESET,
                               "conc_preset", help=_PRESET_HELP)
    _prefill("conc", preset, presets)
    curve = presets[preset]["curve"]
    _code = codes.CODES.get(preset)
    is_2023 = _code is not None and _code.eta_cc_ref is not None
    fck = _number(box, "conc", "fck", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP)
    gamma_c = _number(box, "conc", "gamma_c", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP,
                      disabled=locked)

    k_tc = None
    eta_cc = None
    if is_2023:
        by_value = {value: label for label, value in _KTC_CHOICES.items()}
        saved = float(st.session_state.get("conc_k_tc", _code.k_tc))
        if saved not in by_value:
            saved = _code.k_tc
            st.session_state["conc_k_tc"] = saved
        k_tc = _seeded_selectbox(
            box, r"$k_{tc}$ applicability", list(by_value), _code.k_tc,
            "conc_k_tc", format_func=lambda value: by_value[value],
            disabled=locked,
            help="DS/EN 1992-1-1:2023 5.1.6(1): use 0.85 for the general/other "
                 "cases. Select 1.00 only when the stated reference-age and delayed "
                 "design-loading conditions apply.",
        )
        if math.isclose(k_tc, 1.0):
            _manual_warning(
                box,
                "method-applicability",
                r"$k_{tc}=1.00$ is applicable only for $t_{\mathrm{ref}}\leq28$ days "
                r"(CR/CN) or $\leq56$ days (CS) when design loading is not expected until at least "
                "3 months after casting, unless the governing National Annex states "
                "otherwise. The user is explicitly assuming those conditions."
            )
        else:
            box.caption(r"$k_{tc}=0.85$: general/other-case value in 5.1.6(1).")
        eta_cc = min((_code.eta_cc_ref / fck) ** (1.0 / 3.0), 1.0)

    # For EN 2023, the effective coefficient is derived from the independent
    # eta_cc(fck) and explicit k_tc applicability input. It is read-only so the
    # displayed edition cannot diverge from the numerical material law. A custom
    # curve preset remains available when a free effective coefficient is intended.
    auto = mp.strength_dependent_alpha_cc(preset, fck, k_tc)
    if auto is not None:
        st.session_state["conc_alpha_cc"] = auto
        label, lo, hi, step = mp.CONCRETE_FIELD_META["alpha_cc"]
        alpha_cc = box.number_input(
            r"Effective $\eta_{cc} k_{tc}$", float(lo), float(hi), step=float(step),
            key="conc_alpha_cc", disabled=True, format="%.6f",
            help="Derived DS/EN 1992-1-1:2023 design-strength coefficient: "
                 r"$\eta_{cc}=\min[(40/f_{ck})^{1/3},1.0]$, multiplied by the "
                 r"selected $k_{tc}$.",
        )
    else:
        alpha_cc = _number(
            box, "conc", "alpha_cc", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP,
            disabled=locked,
        )

    # Concrete strain limits eps_c2, eps_cu2 and the parabola exponent n shape the
    # Design compression curve (plastic-only). Making them editable lets grades above
    # C50/60 -- where EC2 Table 3.1 makes them strength-dependent -- be modelled;
    # they apply to the parabola-rectangle (curve 2). The Auto button fills the
    # Table 3.1 values for the current grade (constant up to C50/60).
    parabola = curve == 2
    strain_lock = locked or not parabola
    # Auto values follow the selected edition: DS/EN 1992-1-1:2023 keeps the ultimate
    # parabola strains constant for every class, so deriving the Table 3.1
    # strength-dependent values above C50/60 would silently overwrite the 2023 law
    # (the manual button and Auto-calc-all share these). Non-edition curve presets
    # are not in the registry -> fall back to Table 3.1.
    _ec2_f, _ecu2_f, _n_f = (_code.strain_law(fck) if _code is not None
                             else (codes.eps_c2(fck), codes.eps_cu2(fck),
                                   codes.n_exponent(fck)))
    a_ec2 = round(_ec2_f * 1000.0, 2)
    a_ecu2 = round(_ecu2_f * 1000.0, 2)
    a_n = round(_n_f, 3)
    auto_all = st.session_state.get("_auto_all", False)
    if (box.button(f"Auto $\\varepsilon$/n (EC2: {a_ec2:.2f}/{a_ecu2:.2f} {_PERMILLE}, n={a_n:.2f})",
                   key="conc_strain_auto", width="stretch", disabled=strain_lock,
                   help=r"Set $\varepsilon_{c2}$, $\varepsilon_{cu2}$ and $n$ for "
                        "the current grade and edition "
                        "(EC2 Table 3.1, strength-dependent above C50/60; kept constant "
                        r"for DS/EN 1992-1-1:2023). Press again after changing $f_{ck}$ or preset.")
            or (auto_all and not strain_lock)):
        st.session_state["conc_eps_c2"] = a_ec2
        st.session_state["conc_eps_cu2"] = a_ecu2
        st.session_state["conc_n"] = a_n
        if auto_all:
            _journal_current_input_values(
                "conc_eps_c2", "conc_eps_cu2", "conc_n"
            )
    eps_c2 = _number(box, "conc", "eps_c2", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP,
                     disabled=strain_lock)
    eps_cu2 = _number(box, "conc", "eps_cu2", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP,
                      disabled=strain_lock)
    n = _number(box, "conc", "n", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP,
                disabled=strain_lock)
    # The two strains are independent inputs, so the form allows eps_cu2 < eps_c2
    # (the law would reject it). Cross-validate here and lift eps_cu2 to the peak
    # strain so a half-finished edit shows a warning instead of aborting the run.
    if eps_cu2 < eps_c2:
        _manual_warning(
            box,
            "input-invalid",
            r"$\varepsilon_{cu2}$ must be at least $\varepsilon_{c2}$ (the peak "
            "strain); using that value for the diagram and analysis.",
        )
        eps_cu2 = eps_c2

    concrete = mp.build_concrete(curve=curve, fck=fck, gamma_c=gamma_c,
                                 alpha_cc=alpha_cc, eps_c2=eps_c2, eps_cu2=eps_cu2, n=n)
    note = (
        f"  ($\\eta_{{cc}}={eta_cc:.6f}$, $k_{{tc}}={k_tc:.2f}$)"
        if auto is not None else ""
    )
    box.caption(f"curve {curve},  $f_{{cd}}$ = {concrete.fcd:.3f} MPa,  "
                f"$\\varepsilon_{{cu2}}$ = {concrete.eps_cu2 * 1000.0:.3f} {_PERMILLE}{note}")

    # Mean tensile strength fctm feeds the serviceability cracking check. It lives
    # with the concrete (not the loads); the Auto button refreshes it from the
    # current grade because the number_input persists across a grade change.
    fctm_ec = round(codes.fctm(fck), 3)
    st.session_state.setdefault("sls_fctm", fctm_ec)
    if (box.button(f"Auto $f_{{ctm}}$ (EC2: {fctm_ec:.2f} MPa)", key="sls_fctm_auto",
                   width="stretch", disabled=lock_elastic,
                   help=r"Set $f_{ctm}=0.30f_{ck}^{2/3}$ (EC2 Table 3.1) for the current "
                        "concrete grade. Press again after changing the grade.")
            or (auto_all and not lock_elastic)):
        st.session_state["sls_fctm"] = fctm_ec
        if auto_all:
            _journal_current_input_values("sls_fctm")
    fctm_val = box.number_input(r"Tensile strength $f_{ctm}$ (MPa)", 0.0, 10.0, step=0.1,
                                key="sls_fctm",
                                **_input_widget_kwargs(
                                    "sls_fctm",
                                    {
                                        "disabled": lock_elastic,
                                        "help": (
                                            r"Mean axial tensile strength for the "
                                            r"cracking check ($f_{ct,\mathrm{eff}}$). "
                                            "Use Auto for the EC2 value."
                                        ),
                                    },
                                ))

    # Elastic modulus Ec: only used by the elastic analysis, to derive the modular
    # ratios n = Es/Ec. The Auto button sets the EC2 secant modulus for the grade.
    ecm_gpa = round(codes.ecm(fck) / 1000.0, 1)
    st.session_state.setdefault("conc_Ec", ecm_gpa)
    if (box.button(f"Auto $E_c$ (EC2: {ecm_gpa:.1f} GPa)", key="conc_Ec_auto",
                   width="stretch", disabled=lock_elastic,
                   help=r"Set $E_c=E_{cm}=22(f_{cm}/10)^{0.3}$ GPa (EC2 Table 3.1) for the "
                        "current grade.")
            or (auto_all and not lock_elastic)):
        st.session_state["conc_Ec"] = ecm_gpa
        if auto_all:
            _journal_current_input_values("conc_Ec")
    Ec = box.number_input(r"Elastic modulus $E_c$ (GPa)", 1.0, 100.0, step=0.5,
                          key="conc_Ec",
                          **_input_widget_kwargs(
                              "conc_Ec",
                              {
                                  "disabled": lock_elastic,
                                  "help": (
                                      "Concrete secant modulus, used only by the "
                                      r"elastic analysis to derive the modular "
                                      r"ratios $n=E_s/E_c$."
                                  ),
                              },
                          ))
    return concrete, fctm_val, Ec, preset, k_tc, eta_cc


def _seed_material_entry_widgets(entry, kind, prefix, *, overwrite=False):
    """Seed one catalogue entry before its widgets are mounted."""
    values = {
        "name": entry["name"],
        "description": entry.get("description", ""),
        "preset": entry["preset"],
        **{field: entry[field] for field in mat_catalog.fields(kind)},
    }
    if kind == "mild":
        values["active_comp"] = entry["active_in_compression"]
    for field, value in values.items():
        key = f"{prefix}_{field}"
        if overwrite:
            st.session_state[key] = value
        else:
            st.session_state.setdefault(key, value)
    marker = f"{prefix}_prev"
    if overwrite:
        st.session_state[marker] = entry["preset"]
    else:
        st.session_state.setdefault(marker, entry["preset"])


def mild_panel(box, locked=False, *, heading=True, entry=None, prefix="mild"):
    """Mild-steel material: preset, editable parameters and adjacent preview.

    A flat form on the general two-yield law: every parameter is always shown
    and live, so the inputs never change with the preset. A preset only prefills
    the values; the named shapes (bilinear, elastic-perfectly-plastic) are
    special cases of the same law.

    ``locked`` (elastic-only mode) disables the stress-strain law parameters,
    which do not affect the elastic results -- except ``Es``, which sets the
    crack-width mean strain and so stays editable.
    """
    if heading:
        box.markdown("**Mild steel**")
    catalogue_mode = entry is not None
    entry = dict(entry or mat_catalog.default_entry("mild"))
    _seed_material_entry_widgets(entry, "mild", prefix)
    if catalogue_mode:
        box.caption(f"Material ID: {entry['id']}")
        name = _seeded_text(box, "Name", entry["name"], f"{prefix}_name")
        description = _seeded_text(
            box, "Description", entry.get("description", ""),
            f"{prefix}_description",
        )
    else:
        name, description = entry["name"], entry.get("description", "")
    presets = mp.MILD_PRESETS
    labels = list(presets)
    if entry["preset"] not in labels:
        labels.append(entry["preset"])
    preset = _seeded_selectbox(
        box, "Preset", labels, entry["preset"], f"{prefix}_preset",
        help=_PRESET_HELP,
        format_func=mat_catalog.mild_preset_display_label,
    )
    box.caption(
        "Preset source: "
        f"{mat_catalog.mild_preset_classification(preset)}. "
        f"{mat_catalog.mild_preset_kernel_note(preset)}. "
        "Every material field remains a direct calculation input."
    )
    # Selecting a preset whose compression yield is active (fyck > 0) turns the
    # "Active in compression" toggle on, so the preset's compression is not
    # silently dropped. (Checked before _prefill, which updates the change marker.)
    if (preset in presets
            and st.session_state.get(f"{prefix}_prev") != preset
            and presets[preset].get("fyck", 0.0) > 0.0):
        st.session_state[f"{prefix}_active_comp"] = True
    if preset in presets:
        _prefill(prefix, preset, presets)
        curve = presets[preset]["curve"]
    else:
        curve = int(entry["curve"])
        st.session_state[f"{prefix}_prev"] = preset
    st.session_state.setdefault(f"{prefix}_active_comp", True)
    active_comp = box.checkbox(
        "Active in compression",
        key=f"{prefix}_active_comp",
        **_input_widget_kwargs(
            f"{prefix}_active_comp",
            {
                "disabled": locked,
                "help": (
                    "On: the bar carries compression and its compression-side "
                    r"inputs ($f_{yck}$, $\varepsilon_{0c}$) are used. Off: the "
                    "reinforcement is tension-only (no compression), for every "
                    "curve type. This applies to the plastic capacity; the "
                    "elastic analysis is linear and treats the bars in both "
                    "directions."
                ),
            },
        ),
    )
    # The compression-side inputs only matter when compression is active.
    comp_only = {"fyck", "ey0c"}
    mild_field_meta = mp.MILD_FIELD_META
    saved_ey0c = st.session_state.get(f"{prefix}_ey0c")
    try:
        saved_ey0c = float(saved_ey0c)
    except (TypeError, ValueError, OverflowError):
        saved_ey0c = None
    if saved_ey0c is not None and math.isfinite(saved_ey0c):
        # A finite offset remains valid project data while compression is
        # inactive, even if its sign would be invalid for an active branch.
        # Keep that value renderable in the disabled field; constructor
        # validation still blocks it if compression is enabled later.
        mild_field_meta = dict(mp.MILD_FIELD_META)
        label, lo, hi, step = mild_field_meta["ey0c"]
        mild_field_meta["ey0c"] = (
            label,
            min(float(lo), saved_ey0c),
            max(float(hi), saved_ey0c),
            step,
        )
    vals = {f: _number(box, prefix, f, mild_field_meta, mp.MILD_HELP,
                       disabled=(locked and f != "Es")
                       or (f in comp_only and not active_comp))
            for f in mp.MILD_FIELD_META}
    steel = _safe_build(box, mp.build_mild, curve, vals,
                        active_in_compression=active_comp)
    comp = "active" if active_comp else "tension-only"
    if steel is None:
        box.caption("Material diagram unavailable until the values are corrected.")
    else:
        box.caption(f"$f_{{yd}}$ = {steel.fytk / vals['gamma_y']:.3f} MPa,  "
                    f"$E_s$ = {vals['Es']:.0f} GPa,  compression {comp}")
    if not catalogue_mode:
        return steel
    updated = {
        **entry,
        "name": str(name).strip() or entry["id"],
        "description": str(description).strip(),
        "preset": preset,
        "curve": int(curve),
        "active_in_compression": bool(active_comp),
        **{field: float(value) for field, value in vals.items()},
    }
    return steel, updated


def prestress_panel(box, locked=False, *, heading=True, entry=None, prefix="pre"):
    """Prestressing-steel material: preset, editable parameters and adjacent preview.

    A flat form: the user-defined and Eurocode presets build the general
    two-yield law, so every parameter is live. The built-in characteristic
    curves are fixed shapes -- only the prestrain (and yield factor) apply.

    ``locked`` (elastic-only mode) disables the stress-strain law parameters, which
    only the plastic analysis uses. The initial prestrain ``IS`` and the modulus
    ``Es`` (Ep) stay editable: the elastic analysis applies the tendon prestress
    ``Ep*IS`` as a force and uses ``Ep/Ec`` for the tendon's modular ratio.
    """
    if heading:
        box.markdown("**Prestressing steel**")
    catalogue_mode = entry is not None
    entry = dict(entry or mat_catalog.default_entry("prestress"))
    _seed_material_entry_widgets(entry, "prestress", prefix)
    if catalogue_mode:
        box.caption(f"Material ID: {entry['id']}")
        name = _seeded_text(box, "Name", entry["name"], f"{prefix}_name")
        description = _seeded_text(
            box, "Description", entry.get("description", ""),
            f"{prefix}_description",
        )
    else:
        name, description = entry["name"], entry.get("description", "")
    presets = mp.PRESTRESS_PRESETS
    labels = list(presets)
    if entry["preset"] not in labels:
        labels.append(entry["preset"])
    preset = _seeded_selectbox(box, "Preset", labels, entry["preset"],
                               f"{prefix}_preset", help=_PRESET_HELP)
    if preset in presets:
        _prefill(prefix, preset, presets)
        curve = presets[preset]["curve"]
    else:
        curve = int(entry["curve"])
        st.session_state[f"{prefix}_prev"] = preset
    vals = {f: _number(box, prefix, f, mp.PRESTRESS_FIELD_META, mp.PRESTRESS_HELP,
                       disabled=locked and f not in ("IS", "Es"))
            for f in mp.PRESTRESS_FIELD_META}
    pre = _safe_build(box, mp.build_prestress, curve, vals)
    if curve in (1, 2, 3, 4, 5):
        box.caption(f"built-in curve {curve} (fixed shape); only the prestrain "
                    f"$\\varepsilon_p^{{(0)}}={vals['IS']:.3f}$ {_PERMILLE} applies")
    else:
        box.caption(f"$\\varepsilon_p^{{(0)}}={vals['IS']:.3f}$ {_PERMILLE},  "
                    f"$f_{{pd}}={vals['fytk'] / vals['gamma_y']:.3f}$ MPa,  "
                    f"$E_p={vals['Es']:.0f}$ GPa")
    if not catalogue_mode:
        return pre
    updated = {
        **entry,
        "name": str(name).strip() or entry["id"],
        "description": str(description).strip(),
        "preset": preset,
        "curve": int(curve),
        **{field: float(value) for field, value in vals.items()},
    }
    return pre, updated


def _assigned_ids_in_base_table(table_key, column):
    """Return durable grid assignments before catalogues are normalized."""

    value = st.session_state.get(table_key)
    if value is None:
        return ()
    try:
        frame = value if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
    except (TypeError, ValueError):
        return ()
    if column not in frame:
        return ()
    return tuple(
        text
        for raw in frame[column].tolist()
        if (text := str(raw).strip()) and text.casefold() != "nan"
    )


def _ensure_material_catalog_state():
    """Seed and canonicalise both catalogues before section grids are mounted."""
    st.session_state.setdefault("_material_catalog_revision", 0)
    revision = int(st.session_state["_material_catalog_revision"])
    capacity_material_id = rebar_table.text_cell(
        st.session_state.get("capacity_steel_material_id")
    )
    capacity_material_ids = (
        (capacity_material_id,)
        if capacity_material_id
        and (
            st.session_state.get("shear_on")
            or st.session_state.get("torsion_on")
        )
        else ()
    )
    reservations = {
        "mild": (
            *_assigned_ids_in_base_table(
                "bars_base", rebar_table.MATERIAL_ID
            ),
            *capacity_material_ids,
        ),
        "prestress": _assigned_ids_in_base_table(
            "tendons_base", rebar_table.MATERIAL_ID
        ),
    }
    for kind in mat_catalog.KINDS:
        key = mat_catalog.catalog_key(kind)
        st.session_state[key] = mat_catalog.ensure_catalog(
            st.session_state, kind, reserved_ids=reservations[kind]
        )
    available_mild_ids = mat_catalog.material_ids(
        st.session_state[mat_catalog.MILD_CATALOG_KEY], "mild"
    )
    if (
        capacity_material_ids
        and capacity_material_id not in available_mild_ids
    ):
        st.session_state[
            "_capacity_steel_unresolved_material_id"
        ] = capacity_material_id
    else:
        st.session_state.pop(
            "_capacity_steel_unresolved_material_id", None
        )

    # M1/P1 retain the historical widget keys. This keeps keyboard habits and
    # existing integrations stable, while the revision gate ensures a loaded
    # project overwrites stale widget state before the widgets are created. The
    # catalogue order is user/project data, so bind aliases by ID, never position.
    if st.session_state.get("_material_alias_revision") != revision:
        for kind, prefix in (("mild", "mild"), ("prestress", "pre")):
            alias_id = "M1" if kind == "mild" else "P1"
            entry = mat_catalog.entry_map(
                st.session_state[mat_catalog.catalog_key(kind)], kind
            ).get(alias_id)
            if entry is not None:
                _seed_material_entry_widgets(entry, kind, prefix, overwrite=True)
        st.session_state["_material_alias_revision"] = revision


def _catalog_prefix(kind, material_id):
    first_id = "M1" if kind == "mild" else "P1"
    if material_id == first_id:
        return "mild" if kind == "mild" else "pre"
    revision = int(st.session_state.get("_material_catalog_revision", 0))
    return f"{kind}cat_r{revision}_{material_id}"


def _bump_material_catalog_revision():
    st.session_state["_material_catalog_revision"] = (
        int(st.session_state.get("_material_catalog_revision", 0)) + 1
    )


def _material_catalog_panel(box, kind, assigned_ids, *, protected_ids=(),
                            locked=False):
    """Edit one catalogue and return it with the selected material preview law."""
    key = mat_catalog.catalog_key(kind)
    reserved_ids = (*assigned_ids, *protected_ids)
    catalogue = mat_catalog.normalise_catalog(
        st.session_state[key], kind, reserved_ids=reserved_ids
    )
    items = catalogue["items"]
    ids = [item["id"] for item in items]
    labels = {item["id"]: mat_catalog.entry_label(item) for item in items}
    select_key = f"_{kind}_catalog_selected"
    pending_select_key = f"_{kind}_catalog_pending_selected"
    if pending_select_key in st.session_state:
        # An action button is evaluated after the selector has been instantiated,
        # when Streamlit forbids writing that widget key. Carry the requested value
        # across the action-triggered rerun and apply it here, before the next mount.
        st.session_state[select_key] = st.session_state.pop(pending_select_key)
    selected = _seeded_selectbox(
        box, "Material", ids, ids[0], select_key,
        format_func=lambda value: labels.get(value, value),
        help="Material ID and editable name. Assign the ID in the section table.",
    )
    counts = mat_catalog.assigned_counts(assigned_ids)
    protected = {str(value).strip() for value in protected_ids if str(value).strip()}
    box.caption(f"Assigned elements: {counts.get(selected, 0)}")

    actions = box.container(horizontal=True)
    add_clicked = actions.button("Add", key=f"{kind}_catalog_add")
    duplicate_clicked = actions.button(
        "Duplicate", key=f"{kind}_catalog_duplicate", disabled=selected not in ids
    )
    delete_clicked = actions.button(
        "Delete", key=f"{kind}_catalog_delete",
        disabled=(len(ids) <= 1 or counts.get(selected, 0) > 0
                  or selected in protected),
        help=("Assigned materials cannot be deleted. Reassign their elements first."
              if counts.get(selected, 0) > 0 else
              "This material is the active member-check reference. Select another "
              "reference first." if selected in protected else None),
    )
    if add_clicked or duplicate_clicked or delete_clicked:
        _snapshot_completed_input_state()
        if add_clicked:
            catalogue, selected = mat_catalog.add_entry(
                catalogue, kind, reserved_ids=reserved_ids
            )
        elif duplicate_clicked:
            catalogue, selected = mat_catalog.duplicate_entry(
                catalogue, kind, selected, reserved_ids=reserved_ids
            )
        else:
            catalogue = mat_catalog.delete_entry(
                catalogue, kind, selected, assigned_ids=reserved_ids
            )
            selected = catalogue["items"][0]["id"]
            if kind == "mild" and st.session_state.get(
                    "capacity_steel_material_id") not in mat_catalog.material_ids(
                        catalogue, kind):
                # The reference selector was mounted earlier in this run, so carry
                # its replacement to the next run rather than mutating its key now.
                st.session_state["_capacity_steel_pending_material_id"] = selected
        st.session_state[key] = catalogue
        st.session_state[pending_select_key] = selected
        _bump_material_catalog_revision()
        action_keys = [
            key,
            pending_select_key,
            "_material_catalog_revision",
        ]
        if "_capacity_steel_pending_material_id" in st.session_state:
            action_keys.append("_capacity_steel_pending_material_id")
        _journal_current_input_values(*action_keys)
        st.rerun()

    entry = next(item for item in items if item["id"] == selected)
    prefix = _catalog_prefix(kind, selected)
    if kind == "mild":
        material, updated = mild_panel(
            box, locked=locked, heading=False, entry=entry, prefix=prefix
        )
    else:
        material, updated = prestress_panel(
            box, locked=locked, heading=False, entry=entry, prefix=prefix
        )
    catalogue = mat_catalog.replace_entry(catalogue, kind, updated)
    st.session_state[key] = catalogue
    return catalogue, selected, material


def _fatigue_preset_for(edition, kind):
    is_2023 = "2023" in str(edition)
    if kind == fatigue_inputs.PRESTRESS:
        return (
            fatigue_inputs.PRESET_2023_PRETENSION
            if is_2023
            else fatigue_inputs.PRESET_2005_PRETENSION
        )
    return (
        fatigue_inputs.PRESET_2023_BARS
        if is_2023
        else fatigue_inputs.PRESET_2005_BARS
    )


def _ensure_fatigue_catalog_state():
    """Seed the stable S-N detail catalogue before reinforcement grids mount."""

    st.session_state.setdefault("_fatigue_catalog_revision", 0)
    key = fatigue_inputs.DETAIL_CATALOG_KEY
    assigned_ids = (
        *_assigned_ids_in_base_table(
            "bars_base", rebar_table.FATIGUE_DETAIL_ID
        ),
        *_assigned_ids_in_base_table(
            "tendons_base", rebar_table.FATIGUE_DETAIL_ID
        ),
    )
    st.session_state[key] = fatigue_inputs.normalise_catalog(
        st.session_state.get(key), assigned_ids=assigned_ids
    )


def _bump_fatigue_catalog_revision():
    st.session_state["_fatigue_catalog_revision"] = (
        int(st.session_state.get("_fatigue_catalog_revision", 0)) + 1
    )


def _fatigue_catalog_prefix(detail_id):
    revision = int(st.session_state.get("_fatigue_catalog_revision", 0))
    return f"fatiguecat_r{revision}_{detail_id}"


def _fatigue_preset_guidance_basis(preset, selected_basis):
    """Return the exact standard family controlling one named detail preset."""

    preset_edition = fatigue_inputs.preset_edition(preset)
    if preset_edition == fatigue_inputs.EC2_2023:
        return design_standards.DesignBasisKey.PUBLISHED_2023
    if preset_edition == fatigue_inputs.EC2_2005:
        selected = design_standards.get_design_basis(selected_basis)
        if selected.family is design_standards.StandardFamily.FIRST_GENERATION:
            return selected.key
        return design_standards.DesignBasisKey.FIRST_GEN_BASE
    raise ValueError(f"no registered input guidance for fatigue preset {preset!r}")


def _fatigue_detail_value_help(preset, selected_basis, purpose):
    """Build source-bound help without attributing custom values to a code."""

    if preset == fatigue_inputs.CUSTOM_PRESET:
        return (
            f"{purpose} This is a project-defined value; record its governing "
            "source below. No Eurocode source is inferred."
        )
    guidance = design_standards.input_guidance(
        _fatigue_preset_guidance_basis(preset, selected_basis),
        design_standards.InputGuidanceKey.FATIGUE_DETAIL_VALUES,
    )
    preset_source = fatigue_inputs.DETAIL_PRESETS[preset]["source"]
    return (
        f"{purpose} {guidance.guidance} Source for this preset: "
        f"{preset_source}."
    )


# Presentation-only mapping for input provenance. Solver dispatch continues to
# use each calculation's existing stable key or edition input.
_INPUT_PROVENANCE_BASIS_BY_EDITION = {
    codes.EC2_2005.label: design_standards.DesignBasisKey.FIRST_GEN_BASE,
    codes.EC2_2005_DKNA.label: (
        design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024
    ),
    codes.EC2_2023.label: design_standards.DesignBasisKey.PUBLISHED_2023,
}


def _selected_basis_input_help(edition, key):
    """Return source-bound help for one existing exact edition selection."""

    try:
        basis_key = _INPUT_PROVENANCE_BASIS_BY_EDITION[edition]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"no registered input provenance for edition {edition!r}"
        ) from exc
    basis = design_standards.get_design_basis(basis_key)
    guidance = design_standards.input_guidance(basis_key, key)
    return (
        f"Selected basis: {basis.label}. {guidance.tooltip} "
        f"Basis note: {basis.disclosure}"
    )


def _creep_coefficient_help(concrete_preset):
    """Bind creep help to the existing concrete preset without changing phi."""

    purpose = (
        "One global final creep coefficient. Sustained actions use "
        "Ec,eff = Ec/(1+phi)."
    )
    basis_key = (
        _INPUT_PROVENANCE_BASIS_BY_EDITION.get(concrete_preset)
        if type(concrete_preset) is str
        else None
    )
    if basis_key is None:
        return (
            f"{purpose} The selected concrete preset is project-defined; "
            "no Eurocode source is inferred."
        )
    selected_help = _selected_basis_input_help(
        concrete_preset,
        design_standards.InputGuidanceKey.CREEP_COEFFICIENT,
    )
    return (
        f"{purpose} {selected_help}"
    )


def _seed_fatigue_detail_widgets(entry, prefix):
    values = {
        "name": entry["name"],
        "description": entry.get("description", ""),
        "kind": entry["kind"],
        "preset": entry["preset"],
        **{
            field: entry[field]
            for field in (
                "n_star",
                "k1",
                "k2",
                "delta_sigma_rsk_mpa",
                "stress_model",
                "bend_reduction",
                "mandrel_diameter_mm",
                "bond_ratio_xi",
                "bond_equivalent_diameter_mm",
                "source",
            )
        },
    }
    for field, value in values.items():
        st.session_state.setdefault(f"{prefix}_{field}", value)


def _fatigue_detail_catalog_panel(box, assigned_ids, edition):
    """Edit named/custom S-N details and return the canonical catalogue."""

    key = fatigue_inputs.DETAIL_CATALOG_KEY
    catalogue = fatigue_inputs.normalise_catalog(
        st.session_state.get(key), assigned_ids=assigned_ids
    )
    items = catalogue["items"]
    ids = [item["id"] for item in items]
    labels = {item["id"]: fatigue_inputs.entry_label(item) for item in items}
    selected_key = "_fatigue_catalog_selected"
    pending_key = "_fatigue_catalog_pending_selected"
    if pending_key in st.session_state:
        st.session_state[selected_key] = st.session_state.pop(pending_key)
    selected = _seeded_selectbox(
        box,
        "Fatigue detail",
        ids,
        ids[0],
        selected_key,
        format_func=lambda value: labels.get(value, value),
        help="Fatigue detail ID assigned in the section table.",
    )
    counts = fatigue_inputs.assigned_counts(assigned_ids)
    box.caption(f"Assigned elements: {counts.get(selected, 0)}")

    actions = box.container(horizontal=True)
    add_mild = actions.button(
        "Add mild",
        key="fatigue_catalog_add_mild",
        icon=":material/add:",
    )
    add_tendon = actions.button(
        "Add tendon",
        key="fatigue_catalog_add_tendon",
        icon=":material/add:",
    )
    duplicate = actions.button(
        "Duplicate",
        key="fatigue_catalog_duplicate",
        disabled=selected not in ids,
    )
    delete = actions.button(
        "Delete",
        key="fatigue_catalog_delete",
        disabled=len(ids) <= 1 or counts.get(selected, 0) > 0,
        help=(
            "Assigned details cannot be deleted. Reassign the elements first."
            if counts.get(selected, 0) > 0
            else None
        ),
    )
    if add_mild or add_tendon or duplicate or delete:
        _snapshot_completed_input_state()
        if add_mild:
            catalogue, selected = fatigue_inputs.add_entry(
                catalogue,
                preset=_fatigue_preset_for(edition, fatigue_inputs.MILD),
                assigned_ids=assigned_ids,
            )
        elif add_tendon:
            catalogue, selected = fatigue_inputs.add_entry(
                catalogue,
                preset=_fatigue_preset_for(edition, fatigue_inputs.PRESTRESS),
                assigned_ids=assigned_ids,
            )
        elif duplicate:
            catalogue, selected = fatigue_inputs.duplicate_entry(
                catalogue,
                selected,
                assigned_ids=assigned_ids,
            )
        else:
            catalogue = fatigue_inputs.delete_entry(
                catalogue,
                selected,
                assigned_ids=assigned_ids,
            )
            selected = catalogue["items"][0]["id"]
        st.session_state[key] = catalogue
        st.session_state[pending_key] = selected
        _bump_fatigue_catalog_revision()
        _journal_current_input_values(
            key,
            pending_key,
            "_fatigue_catalog_revision",
        )
        st.rerun()

    entry = next(item for item in items if item["id"] == selected)
    prefix = _fatigue_catalog_prefix(selected)
    _seed_fatigue_detail_widgets(entry, prefix)
    name = _seeded_text(box, "Name", entry["name"], f"{prefix}_name")
    description = _seeded_text(
        box,
        "Description",
        entry.get("description", ""),
        f"{prefix}_description",
        help="Optional engineering description used to distinguish similar details.",
    )
    compatible = [
        preset
        for preset, values in fatigue_inputs.DETAIL_PRESETS.items()
        if values["kind"] == entry["kind"]
    ]
    preset_options = compatible + [fatigue_inputs.CUSTOM_PRESET]
    preset = _seeded_selectbox(
        box,
        "Resistance preset",
        preset_options,
        entry["preset"],
        f"{prefix}_preset",
        help="Named Eurocode values are locked. Select Custom / imported to edit.",
    )
    if preset != entry["preset"]:
        updated = (
            fatigue_inputs.apply_preset(entry, preset)
            if preset in fatigue_inputs.DETAIL_PRESETS
            else {**entry, "preset": fatigue_inputs.CUSTOM_PRESET}
        )
        st.session_state[key] = fatigue_inputs.replace_entry(
            catalogue,
            updated,
        )
        st.session_state[pending_key] = selected
        _bump_fatigue_catalog_revision()
        st.rerun()

    custom = preset == fatigue_inputs.CUSTOM_PRESET
    mixed_bond_guidance = design_standards.input_guidance(
        edition,
        design_standards.InputGuidanceKey.FATIGUE_MIXED_BOND,
    )
    kind = _seeded_selectbox(
        box,
        "Element type",
        list(fatigue_inputs.KINDS),
        entry["kind"],
        f"{prefix}_kind",
        disabled=not custom,
        help="Selects the reinforcement or tendon fatigue model.",
        format_func=lambda value: (
            "Mild reinforcement"
            if value == fatigue_inputs.MILD
            else "Prestressing tendon"
        ),
    )
    standard_lock = not custom
    c1, c2 = box.columns(2)
    n_star = _seeded_number(
        c1,
        r"Reference cycles $N^*$",
        1.0,
        1.0e12,
        float(entry["n_star"]),
        1.0e5,
        f"{prefix}_n_star",
        disabled=standard_lock,
        format="%.0f",
        help=_fatigue_detail_value_help(
            preset,
            edition,
            "Cycle count at the knee of the two-slope S-N curve.",
        ),
    )
    delta_sigma = _seeded_number(
        c2,
        r"Reference range $\Delta\sigma_{Rsk}$ (MPa)",
        0.1,
        5000.0,
        float(entry["delta_sigma_rsk_mpa"]),
        1.0,
        f"{prefix}_delta_sigma_rsk_mpa",
        disabled=standard_lock,
        help=_fatigue_detail_value_help(
            preset,
            edition,
            r"Characteristic stress range at $N^*$ before $\gamma_s$ and any "
            "diameter or bend reduction.",
        ),
    )
    k1 = _seeded_number(
        c1,
        r"S-N slope $k_1$",
        0.1,
        50.0,
        float(entry["k1"]),
        0.1,
        f"{prefix}_k1",
        disabled=standard_lock,
        help=_fatigue_detail_value_help(
            preset,
            edition,
            r"S-N exponent for stress ranges at or above the $N^*$ knee.",
        ),
    )
    k2 = _seeded_number(
        c2,
        r"S-N slope $k_2$",
        0.1,
        50.0,
        float(entry["k2"]),
        0.1,
        f"{prefix}_k2",
        disabled=standard_lock,
        help=_fatigue_detail_value_help(
            preset,
            edition,
            r"S-N exponent for stress ranges below the $N^*$ knee.",
        ),
    )
    stress_model = _seeded_selectbox(
        box,
        "Reference-range model",
        list(fatigue_inputs.STRESS_MODELS),
        entry["stress_model"],
        f"{prefix}_stress_model",
        disabled=standard_lock,
        help=_fatigue_detail_value_help(
            preset,
            edition,
            r"Determines whether $\Delta\sigma_{Rsk}$ is fixed or selected from "
            "the element diameter.",
        ),
        format_func=lambda value: {
            fatigue_inputs.FIXED_STRESS: "Fixed reference range",
            fatigue_inputs.EC2_2023_BAR_STRESS:
                "EC2:2023 reinforcing-bar diameter",
            fatigue_inputs.EC2_2023_WELDED_STRESS:
                "EC2:2023 welded-bar diameter",
        }.get(value, value),
    )
    bend_reduction = _seeded_toggle(
        box,
        "Bent-bar reduction",
        bool(entry["bend_reduction"]),
        f"{prefix}_bend_reduction",
        disabled=standard_lock,
        help=_fatigue_detail_value_help(
            preset,
            edition,
            "Apply the selected detail's bent-bar reduction to the "
            "characteristic reference range.",
        ),
    )
    mandrel = _seeded_number(
        box,
        "Mandrel diameter [mm]",
        0.0,
        10000.0,
        float(entry["mandrel_diameter_mm"]),
        1.0,
        f"{prefix}_mandrel_diameter_mm",
        disabled=not bend_reduction,
        help=_fatigue_detail_value_help(
            preset,
            edition,
            "Mandrel diameter used with the element diameter in the bent-bar "
            "reduction.",
        ),
    )
    bond_ratio = _seeded_number(
        c1,
        r"Bond ratio $\xi$ (0 = unset)",
        0.0,
        10.0,
        float(entry["bond_ratio_xi"]),
        0.05,
        f"{prefix}_bond_ratio_xi",
        disabled=kind != fatigue_inputs.PRESTRESS,
        help=(
            "Bond-strength ratio for a bonded tendon in a section that also "
            "contains mild reinforcement; 0 leaves it unspecified. "
            f"{mixed_bond_guidance.tooltip}"
        ),
    )
    bond_diameter = _seeded_number(
        c2,
        "Equivalent tendon diameter [mm]",
        0.0,
        1000.0,
        float(entry["bond_equivalent_diameter_mm"]),
        0.1,
        f"{prefix}_bond_equivalent_diameter_mm",
        disabled=kind != fatigue_inputs.PRESTRESS,
        help=(
            "Equivalent tendon diameter used with the bond ratio for the mixed "
            "reinforcement fatigue adjustment. "
            f"{mixed_bond_guidance.tooltip}"
        ),
    )
    source = _seeded_text(
        box,
        "Resistance source",
        entry.get("source", ""),
        f"{prefix}_source",
        disabled=standard_lock,
        help=_fatigue_detail_value_help(
            preset,
            edition,
            "Standard, clause or project source for the resistance definition.",
        ),
    )
    updated = {
        **entry,
        "name": str(name).strip() or entry["id"],
        "description": str(description).strip(),
        "kind": kind,
        "preset": preset,
        "n_star": float(n_star),
        "k1": float(k1),
        "k2": float(k2),
        "delta_sigma_rsk_mpa": float(delta_sigma),
        "stress_model": stress_model,
        "bend_reduction": bool(bend_reduction),
        "mandrel_diameter_mm": float(mandrel),
        "bond_ratio_xi": float(bond_ratio),
        "bond_equivalent_diameter_mm": float(bond_diameter),
        "source": str(source).strip(),
    }
    catalogue = fatigue_inputs.replace_entry(catalogue, updated)
    st.session_state[key] = catalogue
    if kind != entry["kind"]:
        st.session_state[pending_key] = selected
        _bump_fatigue_catalog_revision()
        st.rerun()
    return catalogue


# ---------------------------------------------------------------------------
# Build the section and materials from the staged input tabs
# ---------------------------------------------------------------------------

# Editable cross-section point tables (the section's source of truth). Coordinates
# are entered and drawn in millimetres; the engine works in metres, so the points
# are converted at the table/plot boundary.
_MM = 1000.0   # millimetres per metre
_CORNER_COLS = ["x (mm)", "y (mm)"]
_REBAR_COLS = list(rebar_table.COLUMNS)


def _pts_to_m(pts):
    """Convert (x, y[, area]) points from mm to m for the engine (area unchanged)."""
    return [(p[0] / _MM, p[1] / _MM) + tuple(p[2:]) for p in pts]


def _pts_to_mm(pts):
    """Convert (x, y[, area]) points from m to mm for the tables (area unchanged).

    The coordinates are rounded to clean the float noise the m->mm scaling adds
    (e.g. -0.15 * 1000 = -150.00000000000003), so the grid shows -150, not a long
    truncated value. 6 decimals is far finer than any real placement tolerance.
    """
    return [(round(p[0] * _MM, 6), round(p[1] * _MM, 6)) + tuple(p[2:]) for p in pts]


def _corners_df(pts):
    """Concrete-corner DataFrame ``(x, y)`` in mm from a list of mm points.

    The columns are forced to ``float64`` (even when empty) so the editor always
    renders numeric inputs -- an object-dtype column lets a paste land a string or
    a list in a cell, which then crashes the numeric parsing.
    """
    return pd.DataFrame(
        [{_CORNER_COLS[0]: float(p[0]), _CORNER_COLS[1]: float(p[1])} for p in pts],
        columns=_CORNER_COLS).astype("float64")


def _rebar_df(
    pts,
    kind="bar",
    *,
    size_mode=rebar_table.AREA_MODE,
    material_id=None,
    diameters_mm=None,
):
    """Canonical stable-ID table from ``(x, y, area)`` mm/mm2 points.

    ``diameters_mm`` keeps a physical bar diameter beside an independently
    equivalent analysis area, as required by per-metre slab reinforcement.
    """

    if diameters_mm is None:
        frame = rebar_table.table_from_points(pts, kind, size_mode=size_mode)
    else:
        diameters = [float(value) for value in diameters_mm]
        if len(diameters) != len(pts):
            raise ValueError("bar diameter metadata must match generated points")
        frame = rebar_table.table_from_points(
            pts,
            kind,
            size_mode=rebar_table.AREA_MODE,
        )
        frame[rebar_table.SIZE_MODE] = rebar_table.INDEPENDENT_MODE
        frame[rebar_table.DIAMETER] = diameters
        frame = rebar_table.normalise_table(
            frame,
            kind,
            default_mode=rebar_table.INDEPENDENT_MODE,
        )
    if material_id is not None and not frame.empty:
        frame[rebar_table.MATERIAL_ID] = str(material_id)
    return frame


def _quick_section_material_id(kind):
    """Return the selected, or first available, material for generated points."""
    catalogue = st.session_state[mat_catalog.catalog_key(kind)]
    available = mat_catalog.material_ids(catalogue, kind)
    selected = rebar_table.text_cell(
        st.session_state.get(f"_{kind}_catalog_selected")
    )
    return selected if selected in available else available[0]


def _to_number(v):
    """Coerce a cell to a finite float, or ``None`` if it is blank/non-numeric
    (NaN, text, a stray list from a paste). Never raises."""
    if isinstance(v, (list, tuple, dict, set, np.ndarray)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _pts_from_df(df, cols):
    """Rows of ``df`` as numeric tuples, keeping only complete, valid points.

    A row is kept only when every coordinate coerces to a finite number; partial
    rows (e.g. an x with no y yet) and any non-numeric cell (a stray paste, text,
    a list) are skipped rather than raising, so editing never crashes the app.
    """
    out = []
    for _, row in df.iterrows():
        vals = [_to_number(row.get(c)) for c in cols]
        if any(v is None for v in vals):
            continue
        out.append(tuple(vals))
    return out


_MAX_VOIDS = 10   # arbitrary cap on the number of separate voids

_POINT_TABLE_LABELS = {
    "corners_base": "Concrete corner points",
    "hole_base": "Concrete void points",
    "bars_base": "Reinforcing bar points",
    "tendons_base": "Tendon points",
}


def _table_field_guide(box, table_key):
    """Publish one compact mathematical guide immediately above an editor."""

    if not bool(getattr(box, "open", True)):
        return

    definitions = table_fields.table_fields(table_key)
    title = table_fields.TABLE_TITLES[table_key]
    guide = box.expander(f"{title} - field guide", expanded=False)
    if table_key in {
        load_cases.PLASTIC_TABLE_KEY,
        load_cases.ELASTIC_TABLE_KEY,
        fatigue_inputs.SPECTRUM_TABLE_KEY,
    }:
        guide.caption(
            "Load-action and fatigue numeric fields accept a dot or comma. "
            "Blank action cells are zero; a malformed nonblank value is kept "
            "and must be corrected."
        )
    else:
        guide.caption(
            "Use the field-specific required, optional, and default rules below."
        )
    rows = [
        "| Notation / field | Meaning and sign | Input rule / source |",
        "|---|---|---|",
    ]
    for definition in definitions:
        notation = (
            definition.label
            if definition.math_symbol == "-"
            else f"${definition.math_symbol}$ - {definition.label}"
        )
        unit = table_fields.latex_unit(definition.unit)
        if unit:
            notation += f" [${unit}$]"
        meaning = " ".join(
            part.strip()
            for part in (
                definition.definition,
                definition.sign,
            )
            if part.strip()
        ).replace("|", "\\|")
        rule = (
            f"{table_fields.input_rule(definition)}. "
            f"Source: {definition.source}."
        ).replace("|", "\\|")
        rows.append(
            f"| {notation} | {meaning} | {rule} |"
        )
    guide.markdown("\n".join(rows))

_BULK_ALL = "All elements"
_BULK_SELECTED = "Selected elements"
_BULK_NO_CHANGE = "__sector_no_change__"
_BULK_CLEAR = "__sector_clear__"


def _reseed_table(base_key, ed_key, df):
    """Replace a point table's contents and make its grid re-seed from them.

    Bumping the version token is what tells the Tabulator grid to rebuild from the
    new base; dropping the stale component value makes the grid fall back to it
    until the frontend reports again. Only this table is touched, so a Load / Clear
    / Add-void never disturbs the others.
    """
    st.session_state[base_key] = df
    st.session_state[ed_key + "_ver"] = st.session_state.get(ed_key + "_ver", 0) + 1
    st.session_state.pop(ed_key, None)


def _grid_material_ids(kind):
    if not kind:
        return None
    key = mat_catalog.catalog_key("mild" if kind == "bar" else "prestress")
    catalogue = st.session_state.get(key)
    return mat_catalog.material_ids(
        catalogue, "mild" if kind == "bar" else "prestress"
    ) if catalogue is not None else None


def _grid_fatigue_detail_ids(kind):
    if not kind:
        return None
    catalogue = st.session_state.get(fatigue_inputs.DETAIL_CATALOG_KEY)
    if catalogue is None:
        return None
    detail_kind = (
        fatigue_inputs.MILD if kind == "bar" else fatigue_inputs.PRESTRESS
    )
    return fatigue_inputs.detail_ids(catalogue, detail_kind)


def _point_data_version(_base_key, table_version):
    """Return the explicit row-seed revision for one point grid.

    Material and fatigue catalogues only change the available select options.
    They must never make the component rebuild its rows: the browser may contain
    a more recent edit than the last Python rerun.  Only an intentional table
    replacement (Load, Clear, Quick Section, Add/Remove void) increments this
    revision through :func:`_reseed_table`.
    """

    return table_version


def _point_table_geometry_frame(value, base_key, cols):
    """Return only the point fields governed by Quick Section placement."""

    if not isinstance(value, pd.DataFrame):
        return None
    kind = _reinforcement_kind(base_key)
    if kind:
        frame = rebar_table.normalise_table(value, kind)
        geometry_columns = (
            rebar_table.X,
            rebar_table.Y,
            rebar_table.SIZE_MODE,
            rebar_table.AREA,
            rebar_table.DIAMETER,
        )
    else:
        frame = value.reindex(columns=cols).copy(deep=True)
        geometry_columns = tuple(cols)
    return frame.reindex(columns=geometry_columns).reset_index(drop=True)


def _record_point_table_event(base_key, ed_key, cols) -> None:
    """Journal a grid event and retire only stale builder provenance.

    Catalogue-option refreshes can emit the unchanged component payload, so the
    applied Quick Section snapshot advances only when placement fields actually
    differ from the last stable table. Slab-density bar/outline edits remain
    fail-closed until the engineer explicitly confirms that the rows are physical
    bars; ordinary layouts and explicit tendon edits can be reconciled directly.
    """

    previous = _point_table_geometry_frame(
        st.session_state.get(base_key), base_key, cols
    )
    current = _point_table_geometry_frame(
        _current_table(base_key, ed_key, cols), base_key, cols
    )
    _record_input_event(ed_key)
    if previous is None or current is None or previous.equals(current):
        return
    _prune_applied_quick_section_settings(base_key)


def _render_point_table(box, base_key, ed_key, cols, id_start=1):
    """Draw the editable grid and return its current contents as a DataFrame.

    One Tabulator grid carries the frozen, auto-numbered ID column (from
    ``id_start``, matching the plot), a frozen header and freely editable numeric
    cells with Excel block paste. The grid owns its live state across reruns and
    only re-seeds when its version token changes (see ``_reseed_table``), so a
    typed or pasted value sticks on the first keystroke instead of lagging behind.
    """
    if not bool(getattr(box, "open", True)):
        base = st.session_state[base_key]
        kind = _reinforcement_kind(base_key)
        return (
            rebar_table.normalise_table(base, kind)
            if kind else base.reindex(columns=cols).copy(deep=True)
        )

    previous_geometry = _point_table_geometry_frame(
        st.session_state.get(base_key), base_key, cols
    )
    version = st.session_state.get(ed_key + "_ver", 0)
    data_version = _point_data_version(base_key, version)
    kind = _reinforcement_kind(base_key)
    material_ids = _grid_material_ids(kind)
    fatigue_ids = _grid_fatigue_detail_ids(kind)
    specs = (
        rebar_table.point_grid_specs(kind, material_ids, fatigue_ids)
        if kind
        else [
            {
                "field": column,
                "title": column,
                "type": "number",
                "help": table_fields.field_definition(base_key, column).help,
            }
            for column in cols
        ]
    )
    options = (
        rebar_table.point_grid_options(kind, material_ids, fatigue_ids)
        if kind else None
    )
    with box:
        edited = point_grid(
            st.session_state[base_key],
            cols,
            key=ed_key,
            id_start=id_start,
            data_version=data_version,
            label=_POINT_TABLE_LABELS.get(
                base_key, "Editable section points"
            ),
            column_specs=specs,
            component_options=options,
            on_change=functools.partial(
                _record_point_table_event,
                base_key,
                ed_key,
                tuple(cols),
            ),
        )
    # Keep a durable, non-widget mirror after every frontend report.  Catalogue
    # buttons, Calculate, navigation and project saving can then all consume the
    # same current rows without depending on component-cleanup timing.
    stable = (
        rebar_table.normalise_table(edited, kind)
        if kind
        else edited.reindex(columns=cols).copy(deep=True)
    )
    current_geometry = _point_table_geometry_frame(stable, base_key, cols)
    if (
        previous_geometry is not None
        and current_geometry is not None
        and not previous_geometry.equals(current_geometry)
    ):
        # Keep the provenance boundary correct even when a component host reports
        # its new payload without replaying the optional callback (for example
        # after a browser/session restoration).
        _prune_applied_quick_section_settings(base_key)
    st.session_state[base_key] = stable.copy(deep=True)
    return stable


def _point_editor(box, base_key, ed_key, cols, id_start=1):
    """Editable point table. A row is only used once all its coordinates are
    filled, so a half-typed point is ignored rather than rejected. Returns the
    valid points, numbered by position (the order they appear)."""
    return _pts_from_df(_render_point_table(box, base_key, ed_key, cols, id_start),
                        cols)


def _reinforcement_kind(base_key):
    if base_key == "bars_base":
        return "bar"
    if base_key == "tendons_base":
        return "tendon"
    return None


def _reinforcement_editor(box, base_key, ed_key):
    """Render one rich element table and return its frame, metadata and points."""
    kind = _reinforcement_kind(base_key)
    current = _current_table(base_key, ed_key, _REBAR_COLS)
    _reinforcement_bulk_assignment(
        box, base_key, ed_key, current, kind,
    )
    frame = rebar_table.normalise_table(
        _render_point_table(box, base_key, ed_key, _REBAR_COLS), kind,
    )
    elements = rebar_table.valid_elements(frame, kind)
    issues = rebar_table.row_issues(frame, kind)
    if issues:
        details = engineer_messages.error_detail(
            issues,
            fallback=_REINFORCEMENT_ROW_INPUT,
            context="reinforcement row validation",
        )
        _manual_warning(
            box,
            "geometry-invalid",
            details,
        )
    points_mm = [
        (item["x_mm"], item["y_mm"], item["area_mm2"])
        for item in elements
    ]
    return frame, elements, points_mm, tuple(issues)


def _reinforcement_bulk_assignment(
    box,
    base_key,
    ed_key,
    frame,
    kind,
):
    """Assign one material/detail ID to all or selected live table rows."""

    frame = rebar_table.normalise_table(frame, kind)
    element_ids = frame[rebar_table.ELEMENT_ID].astype(str).tolist()
    notice_key = f"_{ed_key}_bulk_notice"
    notice = st.session_state.pop(notice_key, None)
    if notice:
        box.success(notice)
    if not element_ids:
        return

    panel = box.expander("Bulk assignments", expanded=False)
    panel.caption(
        "Apply one material and/or fatigue detail to all or selected IDs."
    )
    scope_key = f"_{ed_key}_bulk_scope"
    if st.session_state.get(scope_key) not in {_BULK_ALL, _BULK_SELECTED}:
        st.session_state[scope_key] = _BULK_ALL
    scope = panel.segmented_control(
        "Apply to",
        [_BULK_ALL, _BULK_SELECTED],
        key=scope_key,
        width="stretch",
    )

    selected_key = f"_{ed_key}_bulk_ids"
    selected_state = st.session_state.get(selected_key)
    if not isinstance(selected_state, list):
        selected_state = []
    st.session_state[selected_key] = [
        element_id
        for element_id in selected_state
        if element_id in element_ids
    ]
    selected_ids = panel.multiselect(
        "Element IDs",
        element_ids,
        key=selected_key,
        disabled=scope != _BULK_SELECTED,
    )

    material_ids = list(_grid_material_ids(kind) or ())
    material_catalogue_kind = "mild" if kind == "bar" else "prestress"
    material_catalogue = st.session_state.get(
        mat_catalog.catalog_key(material_catalogue_kind)
    )
    material_entries = (
        mat_catalog.entry_map(
            material_catalogue, material_catalogue_kind
        )
        if material_catalogue is not None
        else {}
    )
    material_options = [_BULK_NO_CHANGE, *material_ids]
    material_key = f"_{ed_key}_bulk_material"
    if st.session_state.get(material_key) not in material_options:
        st.session_state[material_key] = _BULK_NO_CHANGE

    fatigue_ids = list(_grid_fatigue_detail_ids(kind) or ())
    fatigue_catalogue = st.session_state.get(
        fatigue_inputs.DETAIL_CATALOG_KEY
    )
    fatigue_entries = (
        fatigue_inputs.entry_map(fatigue_catalogue)
        if fatigue_catalogue is not None
        else {}
    )
    fatigue_options = [_BULK_NO_CHANGE, _BULK_CLEAR, *fatigue_ids]
    fatigue_key = f"_{ed_key}_bulk_fatigue"
    if st.session_state.get(fatigue_key) not in fatigue_options:
        st.session_state[fatigue_key] = _BULK_NO_CHANGE

    material_col, fatigue_col = panel.columns(2)
    material_id = material_col.selectbox(
        "Material",
        material_options,
        key=material_key,
        format_func=lambda value: (
            "No change"
            if value == _BULK_NO_CHANGE
            else mat_catalog.entry_label(material_entries[value])
            if value in material_entries
            else value
        ),
    )
    fatigue_id = fatigue_col.selectbox(
        "Fatigue detail",
        fatigue_options,
        key=fatigue_key,
        format_func=lambda value: (
            "No change"
            if value == _BULK_NO_CHANGE
            else "Clear assignment"
            if value == _BULK_CLEAR
            else fatigue_inputs.entry_label(fatigue_entries[value])
            if value in fatigue_entries
            else value
        ),
    )

    targets = (
        element_ids
        if scope == _BULK_ALL
        else list(selected_ids)
    )
    assignments = {}
    if material_id != _BULK_NO_CHANGE:
        assignments[rebar_table.MATERIAL_ID] = material_id
    if fatigue_id != _BULK_NO_CHANGE:
        assignments[rebar_table.FATIGUE_DETAIL_ID] = (
            "" if fatigue_id == _BULK_CLEAR else fatigue_id
        )
    apply_disabled = not targets or not assignments
    if panel.button(
        "Apply assignments",
        key=f"_{ed_key}_bulk_apply",
        width="stretch",
        disabled=apply_disabled,
    ):
        updated = rebar_table.assign_rows(
            frame,
            kind,
            targets,
            assignments,
        )
        _reseed_table(base_key, ed_key, updated)
        label = "bars" if kind == "bar" else "tendons"
        st.session_state[notice_key] = f"Updated {len(targets)} {label}."
        st.rerun()


def _void_groups(df, cols):
    """Split the void table into voids: runs of complete (x, y) rows, separated by
    a blank row. Returns the groups in order (each a list of points), including
    short ones (fewer than 3 corners), so callers can both count and validate."""
    groups, current = [], []
    for _, row in df.iterrows():
        vals = [_to_number(row.get(c)) for c in cols]
        if any(v is None for v in vals):     # a blank/partial row separates voids
            if current:
                groups.append(current)
                current = []
        else:
            current.append(tuple(vals))
    if current:
        groups.append(current)
    return groups


def _void_editor(box, base_key, ed_key, id_start=1):
    """Editable void table: several voids in one table, separated by a blank row.
    Returns the hole rings (each void with 3 or more corners), capped at
    ``_MAX_VOIDS`` -- the cap is enforced here, not only on the Add button, so a
    paste of more voids cannot push extra holes into the drawing and analysis."""
    edited = _render_point_table(box, base_key, ed_key, _CORNER_COLS, id_start)
    rings = [g for g in _void_groups(edited, _CORNER_COLS) if len(g) >= 3]
    if len(rings) > _MAX_VOIDS:
        _manual_warning(
            box,
            "geometry-invalid",
            f"Only the first {_MAX_VOIDS} voids are used; "
            f"{len(rings) - _MAX_VOIDS} extra ignored.",
        )
    return rings[:_MAX_VOIDS]


def _void_table_from_groups(groups, trailing_blank=False):
    """Rebuild a void DataFrame from a list of voids, one blank row between each.
    With ``trailing_blank`` a blank row is also appended (an empty void slot)."""
    rows = []
    for i, g in enumerate(groups):
        if i > 0:
            rows.append({c: None for c in _CORNER_COLS})   # separator
        rows.extend({_CORNER_COLS[0]: x, _CORNER_COLS[1]: y} for x, y in g)
    if trailing_blank:
        rows.append({c: None for c in _CORNER_COLS})
    return pd.DataFrame(rows, columns=_CORNER_COLS).astype("float64")


def _current_table(base_key, ed_key, cols):
    """The grid's current rows as a DataFrame.

    The grid reports its full contents (not a delta), so a button handler that runs
    before the grid re-renders (Add / Remove void) reads the last reported value;
    it falls back to the stable base if the grid has not reported yet (just
    re-seeded), so unsaved edits are never discarded.
    """
    value = st.session_state.get(ed_key)
    version = st.session_state.get(ed_key + "_ver", 0)
    rows = _versioned_rows(value, _point_data_version(base_key, version))
    kind = _reinforcement_kind(base_key)
    if rows is None:   # absent, malformed or stale -- use the current base
        frame = st.session_state[base_key].copy().reset_index(drop=True)
    else:
        specs = (
            rebar_table.point_grid_specs(
                kind,
                _grid_material_ids(kind),
                _grid_fatigue_detail_ids(kind),
            )
            if kind else None
        )
        frame = _rows_to_df(rows, cols, specs)
    return (rebar_table.normalise_table(frame, kind) if kind else frame)


_PROJECT_TABLES = (
    ("corners_base", "ed_corners", _CORNER_COLS),
    ("hole_base", "ed_hole", _CORNER_COLS),
    ("bars_base", "ed_bars", _REBAR_COLS),
    ("tendons_base", "ed_tendons", _REBAR_COLS),
)

_CASE_EDITOR_KEYS = {
    load_cases.PLASTIC_TABLE_KEY: "plastic_cases_editor",
    load_cases.ELASTIC_TABLE_KEY: "elastic_cases_editor",
}


def _reseed_case_table(key, value):
    """Replace one canonical load table and reset its native editor seed."""
    st.session_state[key] = load_cases.normalise_table(value, key)
    st.session_state.pop(_CASE_EDITOR_KEYS[key], None)
    st.session_state.pop(f"_{key}_editor_seed", None)


def _case_column_config(key):
    """Readable engineering labels and strict types for one load-case editor."""
    def definition(column):
        return table_fields.field_definition(key, column)

    text = {
        load_cases.NAME: st.column_config.TextColumn(
            "Name *", help=definition(load_cases.NAME).help,
            required=True, pinned=True, width="small",
        ),
        load_cases.DESCRIPTION: st.column_config.TextColumn(
            "Description", help=definition(load_cases.DESCRIPTION).help,
            pinned=True, width="medium",
        ),
    }

    def force(column, label):
        field = definition(column)
        return st.column_config.TextColumn(
            label,
            help=(
                f"{field.help} Enter a dot or comma decimal; blank means zero."
            ),
            required=False,
            default="0",
            width="small",
        )

    if key == load_cases.PLASTIC_TABLE_KEY:
        return {
            **text,
            "n_ed_kn": force("n_ed_kn", "N_Ed [kN]"),
            "mx_ed_knm": force("mx_ed_knm", "Mx_Ed [kNm]"),
            "my_ed_knm": force("my_ed_knm", "My_Ed [kNm]"),
            "vx_ed_kn": force("vx_ed_kn", "Vx_Ed [kN]"),
            "vy_ed_kn": force("vy_ed_kn", "Vy_Ed [kN]"),
            "vx_face": st.column_config.SelectboxColumn(
                "Vx face",
                help=definition("vx_face").help,
                options=list(load_cases.FACE_OPTIONS), default=load_cases.FACE_AUTO,
                required=True, width="small",
            ),
            "vy_face": st.column_config.SelectboxColumn(
                "Vy face",
                help=definition("vy_face").help,
                options=list(load_cases.FACE_OPTIONS), default=load_cases.FACE_AUTO,
                required=True, width="small",
            ),
            "t_ed_knm": force("t_ed_knm", "T_Ed [kNm]"),
            "check_minimum_reinforcement": st.column_config.CheckboxColumn(
                "Min. reinforcement",
                help=definition("check_minimum_reinforcement").help,
                default=False,
                width="small",
            ),
        }
    return {
        **text,
        "n_long_ed_kn": force("n_long_ed_kn", "N_Ed,long [kN]"),
        "mx_long_ed_knm": force("mx_long_ed_knm", "Mx_Ed,long [kNm]"),
        "my_long_ed_knm": force("my_long_ed_knm", "My_Ed,long [kNm]"),
        "n_short_ed_kn": force("n_short_ed_kn", "N_Ed,short [kN]"),
        "mx_short_ed_knm": force("mx_short_ed_knm", "Mx_Ed,short [kNm]"),
        "my_short_ed_knm": force("my_short_ed_knm", "My_Ed,short [kNm]"),
        "calculate_crack_width": st.column_config.CheckboxColumn(
            "Calculate crack width",
            help=definition("calculate_crack_width").help,
            default=False, width="small",
        ),
    }


def _case_table_editor(box, key):
    """Render one native editor while keeping its input seed immutable.

    The editor result is written to the canonical base DataFrame, but the widget
    continues to receive a separate frozen seed for its mounted lifetime. This
    avoids the Streamlit data-editor feedback loop where assigning the returned
    frame back to the frame used as widget input can drop every other edit.
    """
    if not bool(getattr(box, "open", True)):
        current = load_cases.normalise_table(st.session_state.get(key), key)
        return load_cases.active_table(current, key)

    editor_key = _CASE_EDITOR_KEYS[key]
    seed_key = f"_{key}_editor_seed"
    if editor_key not in st.session_state or seed_key not in st.session_state:
        st.session_state[seed_key] = load_cases.normalise_table(
            st.session_state.get(key), key
        )
    seed = load_cases.normalise_table(st.session_state[seed_key], key)
    editor_seed = load_cases.editor_table(seed, key)
    edited = box.data_editor(
        editor_seed,
        key=editor_key,
        **_input_widget_kwargs(
            editor_key,
            {
                "num_rows": "dynamic",
                "hide_index": True,
                "width": "stretch",
                "height": "auto",
                "column_config": _case_column_config(key),
                "column_order": load_cases.TABLE_COLUMNS[key],
            },
        ),
    )
    current = load_cases.normalise_table(edited, key)
    st.session_state[key] = current.copy(deep=True)
    return load_cases.active_table(current, key)


def _load_case_editors(box):
    """Render and return the authoritative Plastic and Elastic case tables."""
    defaults = load_cases.default_tables()
    for key in load_cases.CASE_TABLE_KEYS:
        if key not in st.session_state:
            st.session_state[key] = defaults[key]

    direction_label = modelled_direction.resolved_markdown_label(
        cut_direction=st.session_state.get("detailing_cut_direction"),
        alias=st.session_state.get(modelled_direction.ALIAS_KEY),
    )
    box.info(f"Modelled reinforcement direction: {direction_label}")
    box.markdown("**Plastic and capacity cases**")
    box.caption(
        "One row per named case. Section forces keep their signs. Zero Vx,Ed, "
        "Vy,Ed or TEd skips that component. Select minimum reinforcement only "
        "for cases with the design situation required by the chosen detailing "
        "method. Paste rectangular ranges directly."
    )
    _table_field_guide(box, load_cases.PLASTIC_TABLE_KEY)
    plastic = _case_table_editor(box, load_cases.PLASTIC_TABLE_KEY)
    box.markdown("**Elastic cases**")
    box.caption(
        "Long and short action parts share the global creep coefficient below. "
        "Each action reports stresses and can calculate crack width. Independent "
        "long- and short-term limits apply to their matching branches; Formula "
        "7.100 NA uses a separate limit. Define combination completeness in the "
        "project basis."
    )
    _table_field_guide(box, load_cases.ELASTIC_TABLE_KEY)
    elastic = _case_table_editor(box, load_cases.ELASTIC_TABLE_KEY)
    return {
        load_cases.PLASTIC_TABLE_KEY: plastic,
        load_cases.ELASTIC_TABLE_KEY: elastic,
    }


_FATIGUE_EDITOR_KEY = "fatigue_spectrum_editor"
_NON_REPLAYABLE_INPUT_EVENT_KEYS = frozenset({
    *_CASE_EDITOR_KEYS.values(),
    _FATIGUE_EDITOR_KEY,
})


def _fatigue_spectrum_column_config():
    """Engineering labels and strict types for the grouped-spectrum editor."""
    def definition(column):
        return table_fields.field_definition(
            fatigue_inputs.SPECTRUM_TABLE_KEY, column
        )

    def action(column, label):
        field = definition(column)
        return st.column_config.TextColumn(
            label,
            help=(
                f"{field.help} Enter a dot or comma decimal; blank means zero."
            ),
            required=False,
            default="0",
            width="small",
        )

    return {
        fatigue_inputs.SPECTRUM: st.column_config.TextColumn(
            "Spectrum *",
            help=definition(fatigue_inputs.SPECTRUM).help,
            required=True,
            pinned=True,
            width="small",
        ),
        fatigue_inputs.NAME: st.column_config.TextColumn(
            "Bin name *",
            help=definition(fatigue_inputs.NAME).help,
            required=True,
            pinned=True,
            width="small",
        ),
        fatigue_inputs.DESCRIPTION: st.column_config.TextColumn(
            "Description",
            help=definition(fatigue_inputs.DESCRIPTION).help,
            pinned=True,
            width="medium",
        ),
        fatigue_inputs.CYCLES: st.column_config.TextColumn(
            "Cycles n_i *",
            help=(
                f"{definition(fatigue_inputs.CYCLES).help} Enter a dot or "
                "comma decimal."
            ),
            required=True,
            width="small",
        ),
        "n_long_ed_kn": action("n_long_ed_kn", "N_Ed,long [kN]"),
        "mx_long_ed_knm": action("mx_long_ed_knm", "Mx_Ed,long [kNm]"),
        "my_long_ed_knm": action("my_long_ed_knm", "My_Ed,long [kNm]"),
        "n_short_ed_kn": action("n_short_ed_kn", f"{_DELTA}N_Ed [kN]"),
        "mx_short_ed_knm": action(
            "mx_short_ed_knm", f"{_DELTA}Mx_Ed [kNm]"
        ),
        "my_short_ed_knm": action(
            "my_short_ed_knm", f"{_DELTA}My_Ed [kNm]"
        ),
    }


def _fatigue_spectrum_editor(box):
    """Render the authoritative grouped fatigue spectrum."""

    key = fatigue_inputs.SPECTRUM_TABLE_KEY
    seed_key = f"_{key}_editor_seed"
    if key not in st.session_state:
        st.session_state[key] = fatigue_inputs.empty_spectrum_table()
    if not bool(getattr(box, "open", True)):
        current = fatigue_inputs.normalise_spectrum_table(st.session_state[key])
        return fatigue_inputs.active_spectrum_table(current)
    if _FATIGUE_EDITOR_KEY not in st.session_state or seed_key not in st.session_state:
        st.session_state[seed_key] = fatigue_inputs.normalise_spectrum_table(
            st.session_state[key]
        )
    seed = fatigue_inputs.normalise_spectrum_table(st.session_state[seed_key])
    _table_field_guide(box, fatigue_inputs.SPECTRUM_TABLE_KEY)
    editor_seed = fatigue_inputs.editor_spectrum_table(seed)
    edited = box.data_editor(
        editor_seed,
        key=_FATIGUE_EDITOR_KEY,
        **_input_widget_kwargs(
            _FATIGUE_EDITOR_KEY,
            {
                "num_rows": "dynamic",
                "hide_index": True,
                "width": "stretch",
                "height": "auto",
                "column_config": _fatigue_spectrum_column_config(),
                "column_order": fatigue_inputs.SPECTRUM_COLUMNS,
            },
        ),
    )
    current = fatigue_inputs.normalise_spectrum_table(edited)
    st.session_state[key] = current.copy(deep=True)
    return fatigue_inputs.active_spectrum_table(current)


def _fatigue_basis_prefix():
    revision = int(st.session_state.get("_fatigue_basis_revision", 0))
    return f"fatiguebasis_r{revision}"


def _fatigue_basis_panel(box, *, disabled):
    """Render the direct grouped-spectrum method and optional assumptions."""
    basis = fatigue_inputs.normalise_basis(
        st.session_state.get(fatigue_inputs.BASIS_KEY)
    )
    prefix = _fatigue_basis_prefix()
    method = fatigue_inputs.METHOD_GROUPED
    box.caption(
        f"{method}. Every action and cycle count in the table is used exactly "
        "as entered; the project spectrum defines traffic coverage."
    )
    notes = _seeded_text_area(
        box,
        "Action-set notes",
        basis["notes"],
        f"{prefix}_notes",
        disabled=disabled,
        height=68,
        help="Optional assumptions needed to identify or reproduce the action set.",
    )
    basis = fatigue_inputs.normalise_basis({
        "method": method,
        "notes": notes,
    })
    st.session_state[fatigue_inputs.BASIS_KEY] = basis
    return basis


def _case_table_signature(value, key):
    """Stable hashable table content, including deterministic invalid sentinels."""
    frame = load_cases.active_table(value, key)
    rows = []
    for record in frame.to_dict("records"):
        row = []
        for column in load_cases.TABLE_COLUMNS[key]:
            cell = record[column]
            if column in load_cases.NUMERIC_COLUMNS[key]:
                if (
                    column in load_cases.NULLABLE_NUMERIC_COLUMNS[key]
                    and load_cases.decimal_is_blank(cell)
                ):
                    cell = None
                else:
                    try:
                        number = float(cell)
                    except (TypeError, ValueError, OverflowError):
                        number = math.nan
                    cell = number if math.isfinite(number) else "<invalid>"
            elif column in load_cases.FLAG_COLUMNS[key]:
                cell = bool(cell)
            else:
                cell = str(cell)
            row.append(cell)
        rows.append(tuple(row))
    return tuple(rows)


def _fatigue_spectrum_signature(value):
    """Stable grouped-spectrum content, including invalid numeric sentinels."""

    frame = fatigue_inputs.active_spectrum_table(value)
    rows = []
    for record in frame.to_dict("records"):
        row = []
        for column in fatigue_inputs.SPECTRUM_COLUMNS:
            cell = record[column]
            if column in fatigue_inputs.SPECTRUM_NUMERIC:
                try:
                    number = float(cell)
                except (TypeError, ValueError):
                    number = math.nan
                cell = number if math.isfinite(number) else "<invalid>"
            else:
                cell = str(cell)
            row.append(cell)
        rows.append(tuple(row))
    return tuple(rows)


# Input widgets are not rendered on the Analysis or Report workspace. Streamlit
# consequently
# removes their widget-owned keys at the end of that run, so keep a durable copy
# outside the widget namespace and restore it before either page is rendered.
# Autosave preferences and tracked input-tab choices are session settings rather
# than project inputs, but they need the same treatment while their controls are
# off-screen.
_REPORT_STATE_SCALARS = (
    "rep_proj_no",
    "rep_proj_name",
    "rep_section",
    "rep_rev",
    "rep_author",
    "rep_comments",
    project_io.REPORT_PROFILE_KEY,
)
_REPORT_STATE_SCALAR_SET = frozenset(_REPORT_STATE_SCALARS)
_DURABLE_INPUT_SCALARS = (
    tuple(
        key
        for key in (
            *project_io.SCALAR_KEYS,
            *project_io.PRESENTATION_SCALAR_KEYS,
        )
        if key not in _REPORT_STATE_SCALAR_SET
    )
    + (
        "autosave_on", "autosave_min", "_input_tab", "_material_tab",
        "_material_tab_preference",
        "_material_catalog_revision", "_mild_catalog_selected",
        "_prestress_catalog_selected", "_fatigue_catalog_revision",
        "_fatigue_catalog_selected", "_fatigue_basis_revision",
    )
)
_INPUT_STATE_KEY = "_durable_input_scalars"
_INPUT_BUILD_KEY = "_inputs_build_in_progress"
_REPORT_STATE_KEY = "_durable_report_scalars"
_REPORT_BUILD_KEY = "_report_build_in_progress"
_LAST_WORKSPACE_KEY = "_last_completed_workspace"
_PENDING_INPUT_EVENTS_KEY = "_pending_input_events"
_PENDING_REPORT_EVENTS_KEY = "_pending_report_events"
_INPUT_NAVIGATION_KEYS = frozenset(
    {"_input_tab", "_material_tab", "_material_tab_preference"}
)
_INPUT_ISSUE_FOCUS_KEY = "_input_issue_focus"
_SHOW_INPUT_ISSUES_KEY = "_show_input_validation_issues"
_HEIGHTENED_AUTO_REFERENCE_KEY = "_heightened_auto_reference_case"
_HEIGHTENED_EXPLICIT_REFERENCE_KEY = "_heightened_explicit_reference_case"
_PROJECT_UPLOAD_CONTENT_ID_KEY = "_project_upload_content_identity"
_PROJECT_UPLOAD_GENERATION_KEY = "_project_upload_widget_generation"
_PENDING_PROJECT_CONTENT_ID_KEY = "_pending_project_content_identity"
_PENDING_PROJECT_WIDGET_KEY = "_pending_project_widget_key"


def _input_stage_labels() -> dict[str, str]:
    """Map stable short stage names to the labels mounted by Streamlit."""

    dot = chr(0x00B7)
    stage_labels = tuple(stage.label for stage in manual_ia.INPUT_STAGES)
    return {
        stage_labels[0]: f"1 {dot} {stage_labels[0]}",
        stage_labels[1]: f"2 {dot} {stage_labels[1]}",
        stage_labels[2]: f"3 {dot} {stage_labels[2]}",
        stage_labels[3]: f"4 {dot} {stage_labels[3]}",
        stage_labels[4]: stage_labels[4],
    }
def _record_input_event(
    key,
    callback=None,
    callback_args=(),
    callback_kwargs=None,
) -> None:
    """Journal a real widget event until one Inputs build commits it.

    Streamlit applies the triggering widget value before running its callback.
    Keeping that value separately lets interrupted-run recovery distinguish the
    engineer's edit from defaults created while the superseded script was only
    partly reconstructed. The journal survives further interruptions and is
    cleared only after a complete Inputs render.
    """

    if key == project_io.REPORT_PROFILE_KEY:
        st.session_state.pop("_report_profile_error", None)
    workspace = st.session_state.get("_main_page", "Inputs")
    if workspace == "Inputs" and key in st.session_state:
        pending = dict(st.session_state.get(_PENDING_INPUT_EVENTS_KEY, {}))
        pending[key] = copy.deepcopy(st.session_state[key])
        st.session_state[_PENDING_INPUT_EVENTS_KEY] = pending
    elif workspace == "Report" and key in _REPORT_STATE_SCALAR_SET:
        pending = dict(st.session_state.get(_PENDING_REPORT_EVENTS_KEY, {}))
        pending[key] = copy.deepcopy(st.session_state[key])
        st.session_state[_PENDING_REPORT_EVENTS_KEY] = pending
    if callback is not None:
        callback(*(callback_args or ()), **(callback_kwargs or {}))


def _journal_current_input_values(*keys) -> None:
    """Retain deliberate button-driven mutations across their forced rerun."""

    for key in keys:
        _record_input_event(key)


def _mark_heightened_reference_explicit() -> None:
    """Distinguish a multi-case user choice from the sole-case automatic seed."""

    st.session_state.pop(_HEIGHTENED_AUTO_REFERENCE_KEY, None)
    selected = st.session_state.get("sls_heightened_reference_case")
    if selected:
        st.session_state[_HEIGHTENED_EXPLICIT_REFERENCE_KEY] = selected
    else:
        st.session_state.pop(_HEIGHTENED_EXPLICIT_REFERENCE_KEY, None)


def _snapshot_input_state(inp=None) -> None:
    """Keep live input values available while their widgets are not mounted."""
    saved = dict(st.session_state.get(_INPUT_STATE_KEY, {}))
    for key in _DURABLE_INPUT_SCALARS:
        if key == "_material_tab":
            selection = st.session_state.get(
                "_material_tab_preference", st.session_state.get(key)
            )
            if selection is not None:
                saved[key] = selection
        elif key in st.session_state:
            saved[key] = st.session_state[key]
    st.session_state[_INPUT_STATE_KEY] = saved

    # A component grid's payload is widget-owned too. Commit its latest rows to
    # the stable base DataFrame before navigation can trigger widget cleanup.
    for base, ed, cols in _PROJECT_TABLES:
        if base in st.session_state:
            st.session_state[base] = _current_table(base, ed, cols).copy(deep=True)
    if inp is not None:
        st.session_state["_latest_inputs"] = inp


def _snapshot_report_state() -> None:
    """Keep report-owned document settings while Report is not mounted."""

    saved = dict(st.session_state.get(_REPORT_STATE_KEY, {}))
    for key in _REPORT_STATE_SCALARS:
        if key in st.session_state:
            saved[key] = copy.deepcopy(st.session_state[key])
    st.session_state[_REPORT_STATE_KEY] = saved


def _retained_input_scalar(key, default):
    """Read a conditionally unmounted input without erasing its durable value."""

    durable = st.session_state.get(_INPUT_STATE_KEY, {})
    if key in st.session_state or key in durable:
        return live_fragment_value(st.session_state, durable, key)
    return default


def _snapshot_completed_input_state() -> None:
    """Widget callback: commit only a fully rendered stateful workspace.

    A second browser event can interrupt an Inputs rerun before every widget has
    been reconstructed.  Committing that partial namespace would replace valid
    engineering inputs with widget defaults.  The last completed render remains
    authoritative until the next Inputs build reaches its normal end.
    """
    if (
        st.session_state.get(_LAST_WORKSPACE_KEY) == "Inputs"
        and not st.session_state.get(_INPUT_BUILD_KEY, False)
    ):
        _snapshot_input_state()
        st.session_state.pop(_PENDING_INPUT_EVENTS_KEY, None)
    elif (
        st.session_state.get(_LAST_WORKSPACE_KEY) == "Report"
        and not st.session_state.get(_REPORT_BUILD_KEY, False)
    ):
        _snapshot_report_state()
        st.session_state.pop(_PENDING_REPORT_EVENTS_KEY, None)


def _snapshot_material_tab_state() -> None:
    """Retain the nested material tab before its widget callback reruns."""

    if "_material_tab" in st.session_state:
        st.session_state["_material_tab_preference"] = st.session_state[
            "_material_tab"
        ]
    _snapshot_completed_input_state()


def _restore_input_state(*, replace: bool = False) -> None:
    """Restore input keys from the durable navigation-state mirror.

    ``replace`` is used after an interrupted Inputs build.  Keys created during
    that partial run may still exist, so ``setdefault`` alone cannot recover the
    last complete values.
    """
    restored = set()
    for key, value in st.session_state.get(_INPUT_STATE_KEY, {}).items():
        # A tab event is written before its callback/rerun. Keep that event while
        # replacing engineering values from the last complete Inputs render;
        # otherwise recovery would appear to ignore the engineer's tab click.
        # Returning from Analysis is different: no input-stage event can originate
        # there, and Streamlit may leave a stale default under a remounted selector
        # key. Restore the durable preference in that lifecycle transition.
        returning_from_other_workspace = (
            st.session_state.get("_main_page") == "Inputs"
            and st.session_state.get(_LAST_WORKSPACE_KEY) in {"Analysis", "Report"}
        )
        preserve_navigation = (
            replace
            and key in _INPUT_NAVIGATION_KEYS
            and key in st.session_state
            and not returning_from_other_workspace
        )
        if not preserve_navigation and (replace or key not in st.session_state):
            st.session_state[key] = value
            restored.add(key)
    # Replay every genuine edit that has not yet reached a complete Inputs commit.
    # Multiple rapid events accumulate here, so a later interruption does not
    # discard an earlier edit from the same burst.  A normal Streamlit rerun has
    # already installed the triggering widget value before its callback.  Writing
    # that live value through Session State again is redundant for scalar widgets
    # and forbidden for widgets such as ``data_editor`` that also receive an
    # initial data argument.  Only restore a missing value, or replay a durable
    # scalar that the interrupted-build recovery above deliberately replaced.
    for key, value in st.session_state.get(_PENDING_INPUT_EVENTS_KEY, {}).items():
        if key in _NON_REPLAYABLE_INPUT_EVENT_KEYS:
            continue
        if key not in st.session_state or key in restored:
            st.session_state[key] = copy.deepcopy(value)


def _restore_report_state(*, replace: bool = False) -> None:
    """Restore Report-owned settings before their keyed widgets mount."""

    restored = set()
    for key, value in st.session_state.get(_REPORT_STATE_KEY, {}).items():
        if replace or key not in st.session_state:
            st.session_state[key] = copy.deepcopy(value)
            restored.add(key)
    for key, value in st.session_state.get(
        _PENDING_REPORT_EVENTS_KEY, {}
    ).items():
        if key not in st.session_state or key in restored:
            st.session_state[key] = copy.deepcopy(value)


def _has_uncommitted_inputs(state=None) -> bool:
    """Whether a genuine Inputs edit lacks one fully assembled payload."""

    state = st.session_state if state is None else state
    return bool(
        state.get(_INPUT_BUILD_KEY, False)
        or state.get(_PENDING_INPUT_EVENTS_KEY)
    )


def _open_analysis_content(flag: str) -> None:
    """Leave the input fragment for a full-width auxiliary view."""
    _snapshot_completed_input_state()
    st.session_state["_qs_open"] = flag == "quick_section"
    st.session_state["_next_main_page"] = "Analysis"
    st.rerun(scope="app")


def _open_manual_dialog() -> None:
    """Leave the input fragment to open the manual above the workspace."""
    _snapshot_completed_input_state()
    st.session_state["_manual_open"] = True
    st.rerun(scope="app")


def _set_main_page(page: str) -> None:
    """Select a top-level page from a button callback."""
    st.session_state["_main_page"] = page


def _queue_input_issue_navigation(issue: input_issues.InputIssue) -> None:
    """Queue one safe Analysis-to-Inputs transition before the full rerun."""

    target = issue.target
    if target is None:
        return
    stage_label = _input_stage_labels()[target.stage]
    durable = dict(st.session_state.get(_INPUT_STATE_KEY, {}))
    durable["_input_tab"] = stage_label
    st.session_state["_input_tab"] = stage_label
    if target.material_family is not None:
        durable["_material_tab"] = target.material_family
        durable["_material_tab_preference"] = target.material_family
        st.session_state["_material_tab"] = target.material_family
        st.session_state["_material_tab_preference"] = target.material_family
    if target.material_id is not None:
        selector_key = {
            "Mild steel": "_mild_catalog_selected",
            "Prestressing steel": "_prestress_catalog_selected",
        }[target.material_family]
        durable[selector_key] = target.material_id
        st.session_state[selector_key] = target.material_id
    st.session_state[_INPUT_STATE_KEY] = durable

    # A navigation event from Analysis is authoritative. Do not let an old
    # interrupted Inputs-tab event replay over it during returning-state restore.
    pending = dict(st.session_state.get(_PENDING_INPUT_EVENTS_KEY, {}))
    authoritative_navigation_keys = set(_INPUT_NAVIGATION_KEYS)
    if target.material_id is not None:
        authoritative_navigation_keys.add(selector_key)
    for key in authoritative_navigation_keys:
        pending.pop(key, None)
    if pending:
        st.session_state[_PENDING_INPUT_EVENTS_KEY] = pending
    else:
        st.session_state.pop(_PENDING_INPUT_EVENTS_KEY, None)

    st.session_state[_INPUT_ISSUE_FOCUS_KEY] = {
        "message": issue.message,
        "stage": target.stage,
        "material_family": target.material_family,
        "material_id": target.material_id,
        "widget_key": target.widget_key,
        "widget_label": target.widget_label,
    }
    # The top-level segmented control is already mounted on this run. Follow the
    # existing auxiliary-view lifecycle and apply the destination before its next
    # mount rather than mutating the live widget after creation.
    st.session_state["_next_main_page"] = "Inputs"


def _render_input_issues(
    issues: tuple[input_issues.InputIssue, ...],
    *,
    key_prefix: str,
) -> None:
    """Render one alert per issue and a control only for a trusted target."""

    for index, issue in enumerate(issues, start=1):
        message = engineer_messages.error_detail(
            issue.message,
            fallback=_INPUT_ISSUE_DISPLAY,
            context="input issue renderer",
        )
        if issue.target is None:
            st.error(message)
            continue
        row = st.container(
            horizontal=True,
            vertical_alignment="center",
            gap="small",
        )
        row.error(message)
        button_key = re.sub(
            r"[^a-zA-Z0-9_-]+",
            "-",
            f"{key_prefix}-{index}-{issue.code}",
        )
        target = issue.target
        destination = target.stage
        if target.material_family:
            destination += f" / {target.material_family}"
        if row.button(
            "Go to",
            key=button_key,
            icon=":material/arrow_forward:",
            help=f"Open {destination} to correct this input.",
        ):
            _queue_input_issue_navigation(issue)
            st.rerun(scope="app")


def _section_table_snapshot():
    """Copy the four live point tables for one-step Clear Section recovery."""
    return {
        base: _current_table(base, ed, cols).copy(deep=True)
        for base, ed, cols in _PROJECT_TABLES
    }


def _reseed_section_tables(tables):
    """Restore a complete section-table snapshot and refresh all four grids."""
    for base, ed, cols in _PROJECT_TABLES:
        df = tables.get(base)
        if not isinstance(df, pd.DataFrame):
            kind = _reinforcement_kind(base)
            df = (rebar_table.empty_table() if kind
                  else pd.DataFrame(columns=cols, dtype="float64"))
        kind = _reinforcement_kind(base)
        canonical = (rebar_table.normalise_table(df, kind) if kind
                     else df.reindex(columns=cols).copy(deep=True))
        _reseed_table(base, ed, canonical)


def _clear_section_tables():
    """Empty every point table through the same grid-safe reseed path."""
    _reseed_section_tables({
        base: (rebar_table.empty_table() if _reinforcement_kind(base)
               else pd.DataFrame(columns=cols, dtype="float64"))
        for base, _ed, cols in _PROJECT_TABLES
    })


def _section_tables_are_empty():
    """Whether the four current point tables contain no rows."""
    return all(
        _current_table(base, ed, cols).empty
        for base, ed, cols in _PROJECT_TABLES
    )


def _discard_clear_recovery():
    """Discard pending Clear Section confirmation and undo state."""
    st.session_state.pop("_clear_section_confirm", None)
    st.session_state.pop("_clear_section_undo", None)


def _applied_quick_section_scalars(scalars, state):
    """Overlay proven or safely retained builder settings for persistence."""

    result = dict(scalars)
    applied = state.get(_QS_APPLIED_SETTINGS_KEY)
    retained = state.get(_QS_RETAINED_SETTINGS_KEY)
    for key in project_io.QUICK_SECTION_SCALAR_KEYS:
        result.pop(key, None)
    # Proven applied values take priority over the mutable live builder mirror.
    # With neither provenance nor a loaded retained snapshot, draft qsv_ values
    # are omitted from persistence.
    if isinstance(applied, dict):
        result.update(copy.deepcopy(applied))
    elif isinstance(retained, dict):
        # Current-schema files created before applied-layout tracking can only
        # establish that these were the last saved builder values. Retain them
        # across a draft/Back cycle, but never use them as physical provenance
        # unless reconciliation independently proves the generated layout.
        result.update(copy.deepcopy(retained))
    return result


def _project_state():
    """Return the canonical table/scalar inputs behind a project download."""
    tables = {base: _current_table(base, ed, cols)
              for base, ed, cols in _PROJECT_TABLES if base in st.session_state}
    input_durable = st.session_state.get(_INPUT_STATE_KEY, {})
    report_durable = st.session_state.get(_REPORT_STATE_KEY, {})
    project_scalar_keys = (
        tuple(project_io.SCALAR_KEYS)
        + tuple(project_io.PRESENTATION_SCALAR_KEYS)
    )
    scalars = {}
    for key in project_scalar_keys:
        durable = (
            report_durable
            if key in _REPORT_STATE_SCALAR_SET
            else input_durable
        )
        if key in st.session_state or key in durable:
            scalars[key] = live_fragment_value(
                st.session_state, durable, key
            )
    # Builder preferences can move on after Back, but a saved project must
    # describe the settings that produced the currently applied point tables.
    scalars = _applied_quick_section_scalars(scalars, st.session_state)
    for key in load_cases.CASE_TABLE_KEYS:
        tables[key] = load_cases.normalise_table(
            st.session_state.get(key), key
        )
    fatigue_key = fatigue_inputs.SPECTRUM_TABLE_KEY
    if fatigue_key in st.session_state:
        tables[fatigue_key] = fatigue_inputs.normalise_spectrum_table(
            st.session_state[fatigue_key]
        )
    return tables, scalars


def _project_input_hash() -> str:
    tables, scalars = _project_state()
    return project_io.input_sha256(tables, scalars)


def _project_persistence_hash() -> str:
    tables, scalars = _project_state()
    return project_io.persistence_sha256(tables, scalars)


def _engineering_input_hash(inp) -> str:
    """Fingerprint frozen inputs and explicit solver-result contracts."""

    signature = inp.get("signature")
    if signature is None:
        raise ValueError("engineering input payload has no calculation signature")
    return project_io.result_sha256(("sector-engineering-input-v1", signature))


def _calculation_project_hash(inp) -> str:
    """Retain the legacy canonical-project correlation beside engineering identity."""

    try:
        return _project_input_hash()
    except ValueError:
        # Calculation evidence must remain publishable even when optional project
        # persistence fields are temporarily unsavable. The explicit engineering
        # hash remains authoritative for result reuse.
        return _engineering_input_hash(inp)


def _report_project_state_hash(inp, meta, report_content) -> str:
    """Fingerprint document/project state without conflating it with calculation."""

    try:
        return _project_persistence_hash()
    except ValueError:
        return project_io.result_sha256(
            (
                "sector-report-project-state-v1",
                _engineering_input_hash(inp),
                meta,
                report_content,
            )
        )


def _gather_project() -> str:
    """Serialise current inputs with their source and calculation provenance."""
    tables, scalars = _project_state()
    return project_io.dump_project(
        tables,
        scalars,
        calculation=st.session_state.get("calculation_record"),
        app_version=APP_VERSION,
        revision=source_revision(),
    )


_AUTOSAVE_DEFAULT_MIN = 5     # default autosave interval (minutes), BriCoS-style


def _autosave_path() -> pathlib.Path:
    """The local autosave file. Overridable via ``SECTOR_AUTOSAVE_DIR`` (used by
    tests and for a packaged build's data folder); defaults to ``~/.sector``."""
    base = os.environ.get("SECTOR_AUTOSAVE_DIR") or (pathlib.Path.home() / ".sector")
    return pathlib.Path(base) / "autosave.json"


def _write_autosave(data: str, path) -> bool:
    """Atomically write the project JSON to ``path`` (creating the folder).

    The new content is written to a sibling temp file and then ``os.replace``d in,
    so a crash or power loss mid-write -- the very failure autosave guards against --
    cannot leave the recovery file empty or half-written; the old autosave survives
    until the new one is complete. Returns whether the write succeeded; never raises,
    so a read-only or missing folder cannot break the app."""
    path = pathlib.Path(path)
    tmp = path.parent / (path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)        # atomic on the same filesystem
        return True
    except Exception:
        try:
            tmp.unlink()
        except Exception:
            pass
        return False


def _perform_autosave() -> bool:
    """Write the current project to the autosave file, returning whether it wrote.

    Skips a section with no usable outline (fewer than three complete corners) and a
    project unchanged since the last autosave, so the recovery file is never
    overwritten with nothing or rewritten needlessly."""
    corners = _pts_from_df(_current_table("corners_base", "ed_corners", _CORNER_COLS),
                           _CORNER_COLS)
    if len(corners) < 3:
        return False   # no usable outline yet
    try:
        digest = _project_persistence_hash()
    except Exception:
        return False
    if digest == st.session_state.get("_autosave_hash"):
        return False                                 # unchanged since the last save
    try:
        data = _gather_project()
    except ValueError:
        return False
    if _write_autosave(data, _autosave_path()):
        st.session_state["_autosave_hash"] = digest
        st.session_state["_autosave_last"] = datetime.now().strftime("%H:%M:%S")
        return True
    return False


def _reset_autosave_clock() -> None:
    st.session_state["_autosave_t"] = time.time()    # restart the interval on a change


def _autosave_preferences(state) -> tuple[bool, int]:
    """Return live autosave settings, falling back to the durable input mirror."""
    durable = state.get(_INPUT_STATE_KEY, {})
    if not isinstance(durable, dict):
        durable = {}
    autosave_on = state.get(
        "autosave_on", durable.get("autosave_on", True))
    autosave_min = state.get(
        "autosave_min", durable.get("autosave_min", _AUTOSAVE_DEFAULT_MIN))
    return bool(autosave_on), max(1, int(autosave_min))


def _maybe_autosave() -> None:
    """Autosave on user interaction once the interval has elapsed (the BriCoS model:
    the save rides the reruns that interaction triggers, so the app never reruns or
    saves while idle). Call from the main flow after the inputs are built."""
    # Off-Inputs pages retain the last completed engineering payload. A pending
    # callback or interrupted Inputs build means live widget state can be only a
    # partial newer draft, so no off-page rerun may serialize that hybrid state.
    if (
        st.session_state.get("_main_page", "Inputs") != "Inputs"
        and _has_uncommitted_inputs()
    ):
        return
    # The Project panel is lazy. Streamlit may remove its widget-owned live keys
    # when that panel is no longer rendered, while the completed values remain in
    # the durable input mirror. Analysis-fragment reruns do not execute the outer
    # input recovery flow, so consult that mirror rather than silently reverting
    # to the defaults on those reruns.
    autosave_on, autosave_min = _autosave_preferences(st.session_state)
    if not autosave_on:
        return
    interval = autosave_min * 60
    if time.time() - st.session_state.get("_autosave_t", 0.0) < interval:
        return
    st.session_state["_autosave_t"] = time.time()    # reset whether or not it writes
    if _perform_autosave():
        st.toast("Autosaved.")


def _measured_autosave() -> None:
    """Service autosave inside the optional local run phase."""

    token = app_run_probe.start_phase(st.session_state, "autosave")
    try:
        _maybe_autosave()
    finally:
        app_run_probe.stop_phase(st.session_state, token)


def _autosave_startup() -> None:
    """Once per session, restore the last autosaved project (the BriCoS principle:
    re-open where you left off) and start the autosave clock. A missing autosave
    just leaves the default section; an unreadable one starts fresh with a notice.
    An explicitly uploaded project takes precedence over the autosave."""
    # The Project panel is lazy, but autosave remains an application-level
    # service. Seed its defaults without constructing hidden widgets. If widget
    # cleanup removed a previously mounted control, leave it missing here so the
    # durable mirror can restore the engineer's non-default setting below.
    durable = st.session_state.get(_INPUT_STATE_KEY, {})
    if "autosave_on" not in st.session_state and "autosave_on" not in durable:
        st.session_state["autosave_on"] = True
    if "autosave_min" not in st.session_state and "autosave_min" not in durable:
        st.session_state["autosave_min"] = _AUTOSAVE_DEFAULT_MIN
    if st.session_state.get("_autosave_init"):
        return
    st.session_state["_autosave_init"] = True
    st.session_state["_autosave_t"] = time.time()
    if "_pending_project" in st.session_state:
        return                                       # an upload is already pending
    path = _autosave_path()
    try:
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8")
        tables, scalars = project_io.parse_project(text)
    except ValueError as exc:
        st.session_state["_project_msg"] = (
            "error",
            "Autosave not restored: "
            f"{project_io.engineer_error_message(exc)}. "
            "Starting with the default section.",
        )
        return
    except (OSError, UnicodeError):
        st.session_state["_project_msg"] = (
            "error", "An autosave file was found but could not be read; "
                     "starting with the default section.")
        return
    st.session_state["_pending_project"] = text
    st.session_state["_autosave_restoring"] = True
    st.session_state["_autosave_hash"] = project_io.persistence_sha256(
        tables, scalars
    )


def _autosave_panel(box) -> None:
    """Autosave toggle, interval and status inside the Save / Load panel."""
    enabled = _seeded_checkbox(
        box, "Autosave", True, "autosave_on",
        help="Save inputs locally and restore them on the next launch. A due save "
             "runs on the next interaction.")
    _seeded_number(
        box, "Autosave interval (min)", 1, 120, _AUTOSAVE_DEFAULT_MIN, 1,
        "autosave_min",
        disabled=not enabled, on_change=_reset_autosave_clock,
        help="Minutes between automatic saves.")
    last = st.session_state.get("_autosave_last")
    box.caption(f"Autosaved at {last}." if last
                else "Local recovery is restored on the next launch.")


def _project_not_applied_message(error: Exception) -> str:
    """Return concise authored guidance without publishing raw diagnostics."""

    detail = project_io.engineer_error_message(error).rstrip(".")
    return (
        f"New file was not applied: {detail}. "
        "Select an intact, compatible Sector project file and try again."
    )


def _saved_input_check_copy(matches: object) -> str:
    if matches is True:
        return "saved-input check matches the current saved inputs"
    return "saved-input check does not match the current saved inputs"


def _calculation_input_check_copy(matches: object) -> str:
    if matches is True:
        return "recorded input check matches the current saved inputs"
    return "recorded input check differs from the current saved inputs"


def _project_record_captions(loaded: object) -> tuple[str, ...]:
    """Build engineer-facing project-record copy from validated values only."""

    if not isinstance(loaded, dict):
        return ()
    version = project_io.recorded_sector_version_label(
        loaded.get("sector_version")
    )
    if version is None:
        return ("Loaded project: saving version unavailable",)
    lines = [
        f"Loaded project | recorded Sector version {version} | "
        f"{_saved_input_check_copy(loaded.get('input_hash_valid'))}"
    ]
    calculation = loaded.get("calculation")
    if isinstance(calculation, dict) and calculation:
        performed = project_io.recorded_utc_label(
            calculation.get("performed_at_utc")
        )
        lines.append(
            "Recorded calculation: "
            f"{performed or 'time unavailable'} | "
            f"{_calculation_input_check_copy(calculation.get('matches_saved_inputs'))}"
        )
    return tuple(lines)


def _project_upload_widget_key() -> str:
    """Return the transport widget key; it never contributes to file identity."""

    generation = st.session_state.get(_PROJECT_UPLOAD_GENERATION_KEY, 0)
    if not isinstance(generation, int) or isinstance(generation, bool):
        generation = 0
    generation = max(generation, 0)
    if generation == 0:
        return "project_upload"
    return f"project_upload_{generation}"


def _advance_project_upload_widget(widget_key: str | None = None) -> None:
    """Clear one attempted upload without treating widget state as identity."""

    generation = st.session_state.get(_PROJECT_UPLOAD_GENERATION_KEY, 0)
    if not isinstance(generation, int) or isinstance(generation, bool):
        generation = 0
    st.session_state[_PROJECT_UPLOAD_GENERATION_KEY] = max(generation, 0) + 1
    if widget_key is not None:
        st.session_state.pop(widget_key, None)


def _project_transaction_snapshot() -> dict[str, object]:
    """Deep-copy the complete keyed session namespace before replacement."""

    return copy.deepcopy(st.session_state.to_dict())


def _restore_project_transaction(snapshot: dict[str, object]) -> None:
    """Restore the exact pre-transaction keyed namespace before widgets mount."""

    for key in tuple(st.session_state.to_dict()):
        st.session_state.pop(key, None)
    for key, value in snapshot.items():
        st.session_state[key] = value


def _apply_project_text(text: str) -> None:
    """Apply one validated project before any widgets are created.

    Runs at the top of the script so writing the loaded values into the widget
    keys (and the point-table bases) happens before those widgets exist -- the
    only point at which Streamlit allows their state to be set.
    """
    tables, scalars, parse_info = project_io.parse_project_with_info(text)
    provenance = parse_info["provenance"]
    # The caller owns the all-state transaction. These values are cleared only
    # inside that rollback-protected boundary, after complete project validation.
    st.session_state.pop("_project_migration_warnings", None)
    st.session_state.pop("_loaded_project_migration", None)
    st.session_state.pop(_REPORT_PROFILE_ERROR_KEY, None)
    # A valid project load is an explicit whole-input replacement. Do not replay
    # uncommitted browser events from the project that was open previously.
    st.session_state.pop(_PENDING_INPUT_EVENTS_KEY, None)
    st.session_state.pop(_HEIGHTENED_AUTO_REFERENCE_KEY, None)
    st.session_state.pop(_HEIGHTENED_EXPLICIT_REFERENCE_KEY, None)
    st.session_state.pop(_PENDING_REPORT_EVENTS_KEY, None)
    # A valid project is a whole-project replacement. Current-schema files may
    # intentionally omit any persisted scalar, so remove every live project value
    # before overlaying the parsed file. Missing values are then reconstructed by
    # the same canonical widget/default paths as a clean session, never inherited
    # from the project that happened to be open before the load.
    project_scalar_keys = frozenset(
        (*project_io.SCALAR_KEYS, *project_io.PRESENTATION_SCALAR_KEYS)
    )
    for key in project_scalar_keys:
        st.session_state.pop(key, None)
    # Reset non-persisted controllers whose old values can seed, select or mutate a
    # persisted family after the scalar overlay. An already mounted outer stage is
    # retained below; nested material navigation restarts at its canonical first tab.
    for key in (
        *project_io.PREV_MARKERS,
        "conc_alpha_fck",
        "_auto_all",
        "_material_alias_revision",
        "_mild_catalog_selected",
        "_mild_catalog_pending_selected",
        "_prestress_catalog_selected",
        "_prestress_catalog_pending_selected",
        "_fatigue_catalog_selected",
        "_fatigue_catalog_pending_selected",
        "_capacity_steel_pending_material_id",
        "_capacity_steel_unresolved_material_id",
        "_material_tab",
        "_material_tab_preference",
        "_workspace_label_scale",
        "_workspace_label_min_gap",
        _TORSION_GAMMA_METHOD_KEY,
        _TORSION_GAMMA_MANAGED_KEY,
        _INPUT_BUILD_KEY,
        _REPORT_BUILD_KEY,
        _QS_APPLIED_SETTINGS_KEY,
    ):
        st.session_state.pop(key, None)
    for key in _QS_WIDGET_KEYS:
        st.session_state.pop(key, None)
    _discard_clear_recovery()
    # A preset selector is an action as well as a stored value: changing it
    # prefills the associated editable fields. Reconstruct that action's clean
    # state before applying explicit project fields, then commit the matching
    # marker. This ordering preserves an explicitly loaded field even when its
    # project file omits the selector and the owning material stage mounts during
    # the same run (for example during startup autosave restoration).
    preset_families = (
        ("conc", "conc_preset", _DEFAULT_PRESET, mp.CONCRETE_PRESETS),
        (
            "mild",
            "mild_preset",
            mat_catalog.default_preset("mild"),
            mp.MILD_PRESETS,
        ),
        (
            "pre",
            "pre_preset",
            mat_catalog.default_preset("prestress"),
            mp.PRESTRESS_PRESETS,
        ),
    )
    for prefix, preset_key, default_preset, presets in preset_families:
        effective_preset = scalars.get(preset_key, default_preset)
        if effective_preset not in presets:
            continue
        for field, value in presets[effective_preset].items():
            st.session_state[f"{prefix}_{field}"] = copy.deepcopy(value)
        st.session_state[preset_key] = effective_preset
        st.session_state[f"{prefix}_prev"] = effective_preset
    ed_for_base = {base: ed for base, ed, _ in _PROJECT_TABLES}
    for key in load_cases.CASE_TABLE_KEYS:
        if key not in tables:
            st.session_state.pop(key, None)
            st.session_state.pop(_CASE_EDITOR_KEYS[key], None)
            st.session_state.pop(f"_{key}_editor_seed", None)
    fatigue_key = fatigue_inputs.SPECTRUM_TABLE_KEY
    if fatigue_key not in tables:
        st.session_state.pop(fatigue_key, None)
        st.session_state.pop("fatigue_spectrum_editor", None)
        st.session_state.pop(f"_{fatigue_key}_editor_seed", None)
    for key, df in tables.items():
        if key in load_cases.CASE_TABLE_KEYS:
            _reseed_case_table(key, df)
            continue
        if key == fatigue_key:
            st.session_state[key] = fatigue_inputs.normalise_spectrum_table(df)
            st.session_state.pop("fatigue_spectrum_editor", None)
            st.session_state.pop(f"_{fatigue_key}_editor_seed", None)
            continue
        # Re-seed the grid (bump its version) so it rebuilds from the loaded points
        # rather than keeping the previous session's live state.
        _reseed_table(key, ed_for_base.get(key, key + "_ed"), df)
    for key, value in scalars.items():
        st.session_state[key] = value
    if "torsion_gamma_ct" in scalars:
        effective_torsion_method = (
            scalars.get("combined_method")
            if scalars.get("combined_on")
            else scalars.get("torsion_method")
        )
        st.session_state[_TORSION_GAMMA_METHOD_KEY] = (
            effective_torsion_method or codes.EC2_2005_DKNA.label
        )
        # A loaded value is an explicit persisted input even when it happens to
        # equal the selected method's current default.
        st.session_state[_TORSION_GAMMA_MANAGED_KEY] = False
    # Always rotate catalogue widget namespaces. A sparse file that omits a
    # catalogue must be just as independent of a previously edited catalogue as a
    # file that contains one explicitly.
    _bump_material_catalog_revision()
    _bump_fatigue_catalog_revision()
    st.session_state["_fatigue_basis_revision"] = (
        int(st.session_state.get("_fatigue_basis_revision", 0)) + 1
    )
    for key in list(st.session_state):
        if key.startswith(
            ("mildcat_r", "prestresscat_r", "fatiguecat_r", "fatiguebasis_r")
        ):
            st.session_state.pop(key, None)
    # Rebuild the durable mirror from the replacement only. Retain an already
    # mounted outer stage and the freshly rotated internal widget revisions, but
    # never carry an engineering scalar or family selection across projects.
    durable = {
        "_material_catalog_revision": st.session_state[
            "_material_catalog_revision"
        ],
        "_fatigue_catalog_revision": st.session_state[
            "_fatigue_catalog_revision"
        ],
        "_fatigue_basis_revision": st.session_state["_fatigue_basis_revision"],
    }
    if "_input_tab" in st.session_state:
        durable["_input_tab"] = st.session_state["_input_tab"]
    durable.update(
        {
            key: value
            for key, value in scalars.items()
            if key not in _REPORT_STATE_SCALAR_SET
        }
    )
    st.session_state[_INPUT_STATE_KEY] = durable
    # Existing schema-27 files did not distinguish the last builder preview from
    # an applied layout. Preserve those saved preferences without granting them
    # physical provenance; the slab-density boundary accepts them only after an
    # exact point-table reconciliation. This also prevents a previous project's
    # applied snapshot from surviving a complete replacement.
    st.session_state.pop(_QS_APPLIED_SETTINGS_KEY, None)
    st.session_state.pop(_QS_VERIFIED_DENSITY_SETTINGS_KEY, None)
    st.session_state[_QS_RETAINED_SETTINGS_KEY] = _qs_settings_snapshot(scalars)
    report_durable = {
        key: value
        for key, value in scalars.items()
        if key in _REPORT_STATE_SCALAR_SET
    }
    for key in _REPORT_STATE_SCALARS:
        report_durable.setdefault(
            key,
            _REPORT_DEFAULT if key == project_io.REPORT_PROFILE_KEY else "",
        )
    st.session_state[_REPORT_STATE_KEY] = report_durable
    # Keep each preset's change-marker in step with the loaded preset so the panel
    # does not re-prefill over the loaded field values.
    for marker, src in project_io.PREV_MARKERS.items():
        if src in scalars:
            st.session_state[marker] = scalars[src]
    if "conc_fck" in scalars:
        st.session_state["conc_alpha_fck"] = scalars["conc_fck"]
    for ed in ("ed_corners", "ed_hole", "ed_bars", "ed_tendons"):
        st.session_state.pop(ed, None)
    calculation = provenance.get("calculation")
    if calculation:
        st.session_state["calculation_record"] = calculation
    else:
        st.session_state.pop("calculation_record", None)
    st.session_state["_loaded_project_provenance"] = provenance
    migration_warnings = tuple(parse_info.get("migration_warnings") or ())
    if parse_info.get("migrated"):
        # Keep the structured migration evidence independently of the transient
        # parser result. Plain dict/list/scalar values remain stable across
        # Streamlit reruns and can be consumed by provenance/report surfaces.
        migration_provenance = parse_info.get("migration_provenance") or {}
        st.session_state["_loaded_project_migration"] = {
            "source_schema_version": parse_info["source_schema_version"],
            "target_schema_version": parse_info["target_schema_version"],
            "warnings": list(migration_warnings),
            "migration_provenance": copy.deepcopy(dict(migration_provenance)),
        }
    if migration_warnings:
        st.session_state["_project_migration_warnings"] = migration_warnings
    # Project files intentionally contain inputs, not result payloads. Remove any
    # result/report from the previously open project so it cannot be mistaken for
    # evidence belonging to the newly loaded section.
    for key in (
        "results", "result_sig", "result_plastic_sig", "result_elastic_sig",
        "result_fatigue_sig",
        "result_plastic_case_context_sig", "result_elastic_case_context_sig",
        "result_plastic_bending_context_sig",
        "result_input_snapshot", "_latest_inputs",
        "_case_error", "pl_state", "_report_msg",
        _INPUT_ISSUE_FOCUS_KEY, _SHOW_INPUT_ISSUES_KEY,
    ):
        st.session_state.pop(key, None)
    _clear_report_artifact()
    # Forget the Quick Section builder's last shape so the loaded qsv_ dimensions are
    # not mistaken for an in-builder shape switch: the next builder open takes the
    # first-call branch (records the loaded shape, no re-seed) and keeps b/h as saved.
    st.session_state.pop("qs_shape_prev", None)
    st.session_state["pts_init"] = True   # do not re-seed the tables from a template
    if st.session_state.pop("_autosave_restoring", False):
        st.session_state["_project_msg"] = ("success", "Restored autosaved session.")
    else:
        version = project_io.recorded_sector_version_label(
            provenance.get("sector_version")
        )
        input_matches = provenance.get("input_hash_valid") is True
        if version:
            integrity = _saved_input_check_copy(input_matches)
            detail = f"recorded Sector version {version}; {integrity}"
        else:
            detail = "saving version unavailable"
        message = (
            f"Project loaded ({detail}). Recalculate to create current results."
        )
        if parse_info.get("migrated"):
            message += (
                " Sector converted the project file for this session; the "
                "source file was not changed. Review the converted inputs before "
                "recalculating."
            )
        st.session_state["_project_msg"] = (
            "success" if input_matches else "error",
            message,
        )


def _apply_pending_project() -> None:
    """Apply a pending project as one all-state transaction."""

    text = st.session_state.get("_pending_project")
    if text is None:
        return
    content_identity = st.session_state.get(_PENDING_PROJECT_CONTENT_ID_KEY)
    widget_key = st.session_state.get(_PENDING_PROJECT_WIDGET_KEY)
    try:
        snapshot = _project_transaction_snapshot()
    except Exception as exc:
        st.session_state.pop("_pending_project", None)
        st.session_state.pop(_PENDING_PROJECT_CONTENT_ID_KEY, None)
        st.session_state.pop(_PENDING_PROJECT_WIDGET_KEY, None)
        st.session_state.pop("_autosave_restoring", None)
        if isinstance(widget_key, str):
            _advance_project_upload_widget(widget_key)
        st.session_state["_project_msg"] = (
            "error",
            _project_not_applied_message(exc),
        )
        return

    try:
        st.session_state.pop("_pending_project", None)
        st.session_state.pop(_PENDING_PROJECT_CONTENT_ID_KEY, None)
        st.session_state.pop(_PENDING_PROJECT_WIDGET_KEY, None)
        _apply_project_text(text)
        if isinstance(widget_key, str):
            _advance_project_upload_widget(widget_key)
        if content_identity is None:
            st.session_state.pop(_PROJECT_UPLOAD_CONTENT_ID_KEY, None)
        else:
            # Commit the raw-byte identity last, after every state mutation and
            # dependent-result invalidation has completed successfully.
            st.session_state[_PROJECT_UPLOAD_CONTENT_ID_KEY] = content_identity
    except Exception as exc:
        _restore_project_transaction(snapshot)
        st.session_state.pop("_pending_project", None)
        st.session_state.pop(_PENDING_PROJECT_CONTENT_ID_KEY, None)
        st.session_state.pop(_PENDING_PROJECT_WIDGET_KEY, None)
        st.session_state.pop("_autosave_restoring", None)
        if isinstance(widget_key, str):
            _advance_project_upload_widget(widget_key)
        st.session_state["_project_msg"] = (
            "error",
            _project_not_applied_message(exc),
        )


@st.fragment
def _save_load_panel() -> None:
    """Download the current project and upload one to restore it.

    Rendered in the Project input stage only *after* the
    point tables and inputs have been seeded this run, so the download always
    reflects the live section (not an empty one on a fresh session). Local autosave
    controls rerun only this fragment; loading a project explicitly requests the
    full rerun needed to rebuild every dependent input.
    """
    app_run_probe.open_fragment_run(st.session_state, "save_load")
    box = st.expander("Save / Load", expanded=False)
    try:
        project_data = _gather_project()
        project_error = None
    except ValueError as exc:
        project_data = b""
        project_error = project_io.engineer_error_message(exc)
    box.download_button("Download project", data=project_data,
                        file_name="sector_section.json", mime="application/json",
                        disabled=project_error is not None,
                        width="stretch",
                        help="Save the section, materials, loads and settings to a "
                             "JSON file.")
    if project_error:
        box.error(f"Project download blocked: {project_error}.")
    box.caption(
        f"Saved with Sector {APP_VERSION}; results are recalculated on load."
    )
    loaded = st.session_state.get("_loaded_project_provenance")
    if loaded:
        for caption in _project_record_captions(loaded):
            box.caption(caption)
    loaded_migration = st.session_state.get("_loaded_project_migration")
    if loaded_migration:
        migration = loaded_migration.get("migration_provenance") or {}
        shared = migration.get("shared_value_mm")
        if shared is not None:
            detail = f"shared width {float(shared):g} mm split by duration"
        else:
            detail = "project-file conversion details available"
        box.caption(
            f"Project file updated | {detail}"
        )
    _autosave_panel(box)
    # Retire the pre-0.96.2 filename/size latch if this process hot-reloads from
    # an older session. It is deliberately never consulted.
    st.session_state.pop("_project_upload_id", None)
    upload_widget_key = _project_upload_widget_key()
    up = box.file_uploader("Load project", type=["json"], key=upload_widget_key,
                           help="Restore a section from a downloaded project file.")
    if up is not None:
        try:
            prepared = project_io.prepare_project_upload(up.getvalue())
        except Exception as exc:
            st.session_state["_project_msg"] = (
                "error",
                _project_not_applied_message(exc),
            )
            # A new empty uploader is mounted on the next interaction. The same
            # bytes remain selectable and no failed identity is retained.
            _advance_project_upload_widget()
            app_run_probe.close_fragment_run(st.session_state)
            st.rerun()
        else:
            # A selection on this fresh uploader is an explicit replacement,
            # including when its bytes match the last successfully loaded file.
            st.session_state["_pending_project"] = prepared.text
            st.session_state[_PENDING_PROJECT_CONTENT_ID_KEY] = (
                prepared.content_identity
            )
            st.session_state[_PENDING_PROJECT_WIDGET_KEY] = upload_widget_key
            app_run_probe.close_fragment_run(st.session_state)
            st.rerun()
    msg = st.session_state.pop("_project_msg", None)
    if msg:
        (box.success if msg[0] == "success" else box.error)(msg[1])
    app_run_probe.close_fragment_run(st.session_state)


_REPORT_FIELDS = [
    ("proj_no", "Project no."),
    ("proj_name", "Project name"),
    ("section", "Section"),
    ("rev", "Revision"),
    ("author", "Prepared by"),
]
_REPORT_DEFAULT = report_profiles.DEFAULT_PROFILE.label
_REPORT_CONTENT_OPTIONS = report_profiles.REPORT_PROFILE_KEYS
_REPORT_PROFILE_ERROR_KEY = "_report_profile_error"

# The progress placeholder is mounted by the Report workspace immediately before
# its fragment-local generation call.
_REPORT_PROG = None


def _report_meta():
    """Return the report metadata exactly as shown in the current widgets."""
    meta = {k: st.session_state.get(f"rep_{k}", "")
            for k, _ in _REPORT_FIELDS}
    meta["comments"] = st.session_state.get("rep_comments", "")
    meta[modelled_direction.ALIAS_KEY] = st.session_state.get(
        modelled_direction.ALIAS_KEY, ""
    )
    meta["source_revision"] = source_revision()
    return meta


def _normalise_report_profile_session_state() -> None:
    """Migrate exact pre-profile labels before a keyed widget can mount.

    Streamlit sessions survive code hot reloads and keep an off-screen widget's
    durable mirror. Normalise the live, durable and interrupted-event copies in
    one place. An unknown value is removed with an explicit UI error and any old
    report is cleared; it is never silently treated as Standard.
    """

    container_keys = (
        _INPUT_STATE_KEY,
        _PENDING_INPUT_EVENTS_KEY,
        _REPORT_STATE_KEY,
        _PENDING_REPORT_EVENTS_KEY,
    )
    containers = [st.session_state]
    for container_key in container_keys:
        container = st.session_state.get(container_key)
        if isinstance(container, dict):
            containers.append(container)

    invalid = []
    for container in containers:
        if project_io.REPORT_PROFILE_KEY not in container:
            continue
        value = container[project_io.REPORT_PROFILE_KEY]
        try:
            container[project_io.REPORT_PROFILE_KEY] = (
                project_io.normalise_report_profile(value)
            )
        except ValueError:
            invalid.append(value)
            container.pop(project_io.REPORT_PROFILE_KEY, None)

    if invalid:
        for container in containers:
            container.pop(project_io.REPORT_PROFILE_KEY, None)
        _clear_report_artifact()
        report_durable = dict(st.session_state.get(_REPORT_STATE_KEY, {}))
        report_durable[project_io.REPORT_PROFILE_KEY] = _REPORT_DEFAULT
        st.session_state[_REPORT_STATE_KEY] = report_durable
        st.session_state[project_io.REPORT_PROFILE_KEY] = _REPORT_DEFAULT
        st.session_state[_REPORT_PROFILE_ERROR_KEY] = (
            f"The saved report type is not recognised. Sector reset it to "
            f"{_REPORT_DEFAULT}. Generate a new report before download."
        )

    # v0.93 owned these values in the Inputs mirror. Move them into the Report
    # lifecycle after validating every copy, so an unknown value cannot be hidden
    # by a valid value in another container.
    input_durable = dict(st.session_state.get(_INPUT_STATE_KEY, {}))
    report_durable = dict(st.session_state.get(_REPORT_STATE_KEY, {}))
    for key in _REPORT_STATE_SCALARS:
        if key in input_durable:
            report_durable.setdefault(key, input_durable.pop(key))
    st.session_state[_INPUT_STATE_KEY] = input_durable

    input_pending = dict(st.session_state.get(_PENDING_INPUT_EVENTS_KEY, {}))
    report_pending = dict(st.session_state.get(_PENDING_REPORT_EVENTS_KEY, {}))
    for key in _REPORT_STATE_SCALARS:
        if key in input_pending:
            report_pending[key] = input_pending.pop(key)
    if input_pending:
        st.session_state[_PENDING_INPUT_EVENTS_KEY] = input_pending
    else:
        st.session_state.pop(_PENDING_INPUT_EVENTS_KEY, None)
    if report_pending:
        st.session_state[_PENDING_REPORT_EVENTS_KEY] = report_pending
    else:
        st.session_state.pop(_PENDING_REPORT_EVENTS_KEY, None)

    for key in _REPORT_STATE_SCALARS:
        report_durable.setdefault(
            key,
            _REPORT_DEFAULT if key == project_io.REPORT_PROFILE_KEY else "",
        )
    st.session_state[_REPORT_STATE_KEY] = report_durable


def _report_signature(
    input_signature,
    meta=None,
    report_content=None,
    *,
    product_version=None,
    revision=None,
):
    """Identify the complete input and document-control state behind a PDF."""
    meta = _report_meta() if meta is None else meta
    report_content = (
        st.session_state.get("rep_report_content", _REPORT_DEFAULT)
        if report_content is None else report_content
    )
    document_values = tuple(str(meta.get(k, "")) for k, _ in _REPORT_FIELDS)
    document_values += (
        str(meta.get("comments", "")),
        str(report_content),
        modelled_direction.normalise_alias(
            meta.get(modelled_direction.ALIAS_KEY)
        ),
    )
    if revision is None:
        revision = meta.get("source_revision")
        if revision is None:
            revision = source_revision()
    product_identity = (
        str(APP_VERSION if product_version is None else product_version),
        str(revision),
    )
    return repr(input_signature), document_values, product_identity


def _safe_filename_part(value, fallback):
    """Make one human-readable component safe on Windows and other platforms."""
    part = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", str(value or "").strip())
    part = re.sub(r"\s+", "_", part).strip(" ._-")
    return (part or fallback)[:60]


def _report_filename(meta, generated_on=None):
    """Build an issue-ready filename carrying the key revision identifiers."""
    day = generated_on or datetime.now().date().isoformat()
    project = _safe_filename_part(meta.get("proj_no"), "Project")
    section = _safe_filename_part(meta.get("section"), "Section")
    revision = _safe_filename_part(meta.get("rev"), "DRAFT")
    return f"Sector_{project}_{section}_Rev-{revision}_{day}.pdf"


def _clear_report_artifact():
    """Remove every key that could expose an older PDF after a failed rebuild."""
    for key in (
        "report_buffer",
        "report_bytes",
        "report_signature",
        "report_filename",
        "report_generated_on",
        "report_generation_record",
        "_generating_report",
    ):
        st.session_state.pop(key, None)


def _retained_analysis_for_report(
    inp,
    *,
    state=None,
    product_version=None,
    revision=None,
):
    """Return one copied, internally coherent Analysis result tuple or ``None``."""

    state = st.session_state if state is None else state
    product_version = str(
        APP_VERSION if product_version is None else product_version
    )
    revision = str(source_revision() if revision is None else revision)
    engineering_input_sha256 = _engineering_input_hash(inp)
    retained = copy.deepcopy(
        (
            state.get("results"),
            state.get("result_sig"),
            state.get("result_input_snapshot"),
            state.get("calculation_record"),
        )
    )
    results, result_signature, input_snapshot, calculation = retained
    if not results or not isinstance(calculation, dict):
        return None
    if (
        calculation.get("sector_version") != product_version
        or calculation.get("source_revision") != revision
        or calculation.get("engineering_input_sha256")
        != engineering_input_sha256
        or result_signature != inp.get("signature")
    ):
        return None
    if (
        not isinstance(input_snapshot, dict)
        or input_snapshot.get("signature") != inp.get("signature")
        or _engineering_input_hash(input_snapshot) != engineering_input_sha256
    ):
        return None
    result_sha256 = project_io.result_sha256(results)
    if calculation.get("result_sha256") != result_sha256:
        return None
    return results, calculation, engineering_input_sha256, result_sha256


def _generate_report(inp):
    """Build one PDF from the frozen latest-input payload used by Report."""

    if inp is None:
        _clear_report_artifact()
        st.session_state["_report_msg"] = (
            "error",
            (_REPORT_INPUTS_REQUIRED,),
        )
        return
    if (inp.get("section") is None or inp.get("geometry_error")
            or inp.get("void_error")
            or inp.get("steel_error") or inp.get("material_error")):
        _clear_report_artifact()
        st.session_state["_report_msg"] = (
            "error",
            (_REPORT_SECTION_REQUIRED,),
        )
        return
    case_errors = list(
        case_analysis.validation_errors(inp)
        if "plastic_cases" in inp or "elastic_cases" in inp
        else presentation.required_action_set_errors(inp)
    )
    case_errors.extend(_heightened_crack_control_validation_errors(inp))
    if case_errors:
        _clear_report_artifact()
        st.session_state["_report_msg"] = (
            "error",
            tuple(
                engineer_messages.resolve(
                    value,
                    fallback=_REPORT_PREFLIGHT_DISPLAY,
                    context="report preflight validation",
                )
                for value in case_errors
            ),
        )
        return
    prog = _REPORT_PROG
    bar = prog.progress(0.0, text="Preparing report...") if prog is not None else None

    def _on_progress(frac, text="Generating report..."):
        if bar is not None:
            bar.progress(max(0.0, min(1.0, float(frac))), text=text)

    try:
        import sector_report
        meta = _report_meta()
        current_revision = source_revision()
        meta["source_revision"] = current_revision
        figs = not st.session_state.get("_report_no_figures", False)
        report_content = st.session_state.get(
            "rep_report_content", _REPORT_DEFAULT
        )
        retained = _retained_analysis_for_report(
            inp,
            product_version=APP_VERSION,
            revision=current_revision,
        )
        reuse_results = retained is not None
        if retained is not None:
            out, calculation, engineering_input_sha256, result_sha256 = retained
            result_source = "reused-current-analysis-results"
            calculation_state = "CURRENT - reused matching Analysis results"
        else:
            out = run_analysis(inp)
            calculation = None
            engineering_input_sha256 = _engineering_input_hash(inp)
            result_sha256 = project_io.result_sha256(out)
            result_source = "recalculated-for-report"
            calculation_state = "CURRENT - recalculated for this report"
        project_state_sha256 = _report_project_state_hash(
            inp,
            meta,
            report_content,
        )
        generated_at_utc = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        meta.update({
            "calculation_state": calculation_state,
            # ``input_sha256`` remains the report builder's compatibility key;
            # its value is now explicitly the engineering calculation identity.
            "input_sha256": engineering_input_sha256,
            "engineering_input_sha256": engineering_input_sha256,
            "project_state_sha256": project_state_sha256,
        })
        pdf = sector_report.build_report(meta, inp, out, version=APP_VERSION,
                                         figures=figs, progress=_on_progress,
                                         profile=report_content)
        st.session_state["report_buffer"] = pdf
        st.session_state["report_signature"] = _report_signature(
            inp.get("signature"),
            meta,
            report_content,
        )
        st.session_state["report_filename"] = _report_filename(meta)
        st.session_state["report_generated_on"] = generated_at_utc
        st.session_state["report_generation_record"] = {
            "generated_at_utc": generated_at_utc,
            "input_sha256": engineering_input_sha256,
            "engineering_input_sha256": engineering_input_sha256,
            "project_state_sha256": project_state_sha256,
            "result_sha256": result_sha256,
            "sector_version": APP_VERSION,
            "source_revision": current_revision,
            "result_source": result_source,
            "calculation_state": calculation_state,
        }
        if calculation is not None:
            st.session_state["report_generation_record"][
                "analysis_performed_at_utc"
            ] = calculation.get("performed_at_utc")
        st.session_state["_report_msg"] = (
            "success",
            (
                _REPORT_REUSED_RESULTS
                if reuse_results
                else _REPORT_RECALCULATED_RESULTS,
            ),
        )
    except Exception:                              # never let it crash the app
        _LOGGER.exception("Report generation failed")
        _clear_report_artifact()
        st.session_state["_report_msg"] = (
            "error",
            (_REPORT_GENERATION_FAILED,),
        )
    if prog is not None:
        prog.empty()


@st.fragment
def _report_workspace(inp):
    """Own all report metadata, profile, generation and download controls."""

    app_run_probe.open_fragment_run(st.session_state, "report")
    if st.session_state.get(_REPORT_BUILD_KEY, False):
        _restore_report_state(replace=True)
    else:
        _restore_report_state()
    # A fragment rerun does not execute the top-level startup normaliser. Run it
    # inside the fragment too, after recovery and before the strict keyed control
    # mounts, then restore any exact legacy values moved from the old Inputs mirror.
    _normalise_report_profile_session_state()
    _restore_report_state()
    st.session_state[_REPORT_BUILD_KEY] = True
    uncommitted_input = _has_uncommitted_inputs()

    st.subheader("Report")
    st.caption(
        "Add document details and choose the report depth. Generate uses the "
        "current inputs and the matching Analysis results."
    )
    metadata_box = st.container(border=True)
    metadata_box.markdown("**Document details**")
    _seeded_text(metadata_box, _REPORT_FIELDS[0][1], "", "rep_proj_no")
    _seeded_text(metadata_box, _REPORT_FIELDS[1][1], "", "rep_proj_name")
    _seeded_text(metadata_box, _REPORT_FIELDS[2][1], "", "rep_section")
    c1, c2 = metadata_box.columns(2)
    _seeded_text(c1, "Revision", "", "rep_rev")
    _seeded_text(c2, "Prepared by", "", "rep_author")
    _seeded_text_area(
        metadata_box, "Comments", "", "rep_comments", height=100
    )

    publication_box = st.container(border=True)
    publication_box.markdown("**Publication**")
    if uncommitted_input:
        _manual_warning(
            publication_box,
            "report-stale",
            "Input preparation was interrupted. Open Inputs and allow it to "
            "finish once before generating or downloading a report.",
        )
    profile_error = st.session_state.get(_REPORT_PROFILE_ERROR_KEY)
    if profile_error:
        _manual_warning(
            publication_box,
            "report-generation",
            profile_error,
        )
    report_profile = _seeded_segmented_control(
        publication_box,
        "Report profile",
        list(_REPORT_CONTENT_OPTIONS),
        _REPORT_DEFAULT,
        project_io.REPORT_PROFILE_KEY,
        width="stretch",
        help=(
            "Brief is a rapid-review summary, Standard is the default design-"
            "review report, and Audit adds complete calculation details. The "
            "profile changes presentation depth only; figures remain separate."
        ),
    )
    policy = report_profiles.resolve_profile(report_profile)
    publication_box.caption(policy.description + " " + policy.omitted_detail)
    generate = publication_box.button(
        "Generate report",
        type="primary",
        width="stretch",
        key="gen_report",
        disabled=inp is None or uncommitted_input,
    )
    if inp is None:
        publication_box.info(
            "Open Inputs once to prepare the section and report data."
        )

    global _REPORT_PROG
    _REPORT_PROG = publication_box.empty()
    if generate:
        _snapshot_report_state()
        _generate_report(inp)

    msg = st.session_state.pop("_report_msg", None)
    if msg:
        publisher = (
            publication_box.success if msg[0] == "success" else publication_box.error
        )
        values = msg[1] if isinstance(msg[1], (list, tuple)) else (msg[1],)
        for value in values:
            detail = engineer_messages.error_detail(
                value,
                fallback=_REPORT_PREFLIGHT_DISPLAY,
                context="report publication message",
            )
            publisher(detail)
    if st.session_state.get("report_buffer") and not uncommitted_input:
        current_signature = _report_signature(
            inp.get("signature") if inp is not None else None
        )
        if st.session_state.get("report_signature") == current_signature:
            publication_box.download_button(
                "Download report (PDF)",
                st.session_state["report_buffer"],
                file_name=st.session_state.get(
                    "report_filename",
                    _report_filename(_report_meta()),
                ),
                mime="application/pdf",
                width="stretch",
            )
            record = st.session_state.get("report_generation_record") or {}
            source = record.get("calculation_state")
            generated = record.get("generated_at_utc")
            if source or generated:
                publication_box.caption(
                    " | ".join(value for value in (generated, source) if value)
                )
        else:
            _manual_warning(
                publication_box,
                "report-stale",
                "Report out of date: inputs or report details changed. "
                "Generate it again before downloading.",
            )

    _snapshot_report_state()
    st.session_state.pop(_PENDING_REPORT_EVENTS_KEY, None)
    st.session_state[_REPORT_BUILD_KEY] = False
    st.session_state[_LAST_WORKSPACE_KEY] = "Report"
    if not uncommitted_input:
        _measured_autosave()
    app_run_probe.close_fragment_run(st.session_state)


_QS_SHAPES = [
    "Rectangle",
    "Slab strip",
    "Trapezoid",
    "T-section",
    "L-section",
    "I-section",
    "U-section",
    "Box girder",
    "Circular",
    "Annulus",
]

# b_mm and h_mm are reused across shapes with different meanings and defaults (a
# 400x600 rectangle, an 800x1000 box, a 300 mm slab thickness). Switching shape must
# re-seed them to the new shape's default -- a plain setdefault would keep the
# previous shape's value. The other dimension keys are unique to one shape, so their
# own setdefault default is enough. Mirrors the material-preset prefill.
_QS_SHARED_DIMS = {
    "Rectangle":  {"b_mm": 400.0, "h_mm": 600.0},
    "Slab strip": {"h_mm": 300.0},
    "Box girder": {"b_mm": 800.0, "h_mm": 1000.0},
}


def _qs_shape_prefill(shape):
    """Seed the shared dimension keys with the current shape's defaults when the shape
    selection changes, so the dimension widgets can be created without ``value=``
    (avoiding the "default value + Session State API" warning) while a shape switch
    still resets b/h to that shape's default.

    The very first call in a session only records the shape -- it does not re-seed --
    so a project or autosave restored before the builder is first opened keeps its
    own b/h (the restore is not a shape change). A genuine in-builder shape switch
    (``qs_shape_prev`` already set) still re-seeds."""
    if "qs_shape_prev" not in st.session_state:
        st.session_state["qs_shape_prev"] = shape
        return
    if st.session_state["qs_shape_prev"] != shape:
        for k, v in _QS_SHARED_DIMS.get(shape, {}).items():
            st.session_state[k] = v
        st.session_state["qs_shape_prev"] = shape

# The builder's own widget keys. Streamlit drops a widget's key from session state
# on any run where the widget is not rendered, so while the builder is closed these
# would be lost (resetting the builder to defaults on reopen, and dropping them
# from a saved project). The builder mirrors them to durable "qsv_" keys whenever it
# renders and restores them when it opens; project_io persists the durable copies.
_QS_WIDGET_KEYS = tuple(
    key.removeprefix("qsv_") for key in project_io.QUICK_SECTION_SCALAR_KEYS
)
_QS_APPLIED_SETTINGS_KEY = "_qs_applied_settings"
_QS_RETAINED_SETTINGS_KEY = "_qs_retained_settings"
_QS_VERIFIED_DENSITY_SETTINGS_KEY = "_qs_verified_density_settings"
_QS_PROVENANCE_NOTICE_KEY = "_qs_provenance_notice"
_QS_BAR_SETTING_KEYS = frozenset({
    "qsv_ring_n",
    "qsv_ring_d",
    "qsv_ring_c_mm",
    "qsv_qs_rebar_mode",
    "qsv_qs_cover_to_edge",
    "qsv_bot_n",
    "qsv_bot_d",
    "qsv_bot_s",
    "qsv_top_n",
    "qsv_top_d",
    "qsv_top_s",
    "qsv_bot_c_mm",
    "qsv_top_c_mm",
    "qsv_bot_n2",
    "qsv_top_n2",
    "qsv_bot_layers",
    "qsv_top_layers",
    "qsv_layer_s",
    "qsv_bot_off_d",
    "qsv_top_off_d",
})
_QS_TENDON_SETTING_KEYS = frozenset({
    "qsv_tnd_n",
    "qsv_tnd_a",
    "qsv_tnd_c_mm",
    "qsv_tnd_layers",
    "qsv_tnd_layer_s",
})


def _qs_settings_snapshot(state):
    """Copy only persisted Quick Section values from one complete state."""

    return {
        key: copy.deepcopy(state[key])
        for key in project_io.QUICK_SECTION_SCALAR_KEYS
        if key in state
    }


def _applied_snapshot_is_slab_density(applied) -> bool:
    return (
        isinstance(applied, dict)
        and applied.get("qsv_shape") == "Slab strip"
        and applied.get("qsv_qs_rebar_mode") == "By spacing"
    )


def _prune_applied_quick_section_settings(base_key) -> None:
    """Retire applied builder fields superseded by a real point-table edit."""

    applied = st.session_state.get(_QS_APPLIED_SETTINGS_KEY)
    if not isinstance(applied, dict) or not applied:
        return
    if base_key == "tendons_base":
        retired = _QS_TENDON_SETTING_KEYS
    elif _applied_snapshot_is_slab_density(applied):
        # Density rows are integration representatives, not physical bars. Keep
        # their applied intent so a partial point edit remains visibly fail-closed;
        # the engineer can explicitly convert only after entering physical bars.
        return
    elif base_key == "bars_base":
        retired = _QS_BAR_SETTING_KEYS
    else:
        retired = frozenset(applied)
    updated = {
        key: copy.deepcopy(value)
        for key, value in applied.items()
        if key not in retired
    }
    if updated == applied:
        return
    st.session_state[_QS_APPLIED_SETTINGS_KEY] = updated
    st.session_state[_QS_PROVENANCE_NOTICE_KEY] = (
        "The edited point-table geometry is now retained as explicit input."
    )


def _use_current_bars_as_explicit() -> None:
    """Confirm that current density rows have been replaced by physical bars."""

    applied = st.session_state.get(_QS_APPLIED_SETTINGS_KEY)
    verified = st.session_state.get(_QS_VERIFIED_DENSITY_SETTINGS_KEY)
    source = (
        applied
        if _applied_snapshot_is_slab_density(applied)
        else verified
        if _applied_snapshot_is_slab_density(verified)
        else None
    )
    if source is None:
        return
    st.session_state[_QS_APPLIED_SETTINGS_KEY] = {
        key: copy.deepcopy(value)
        for key, value in source.items()
        if key not in _QS_BAR_SETTING_KEYS
    }
    st.session_state.pop(_QS_VERIFIED_DENSITY_SETTINGS_KEY, None)
    st.session_state[_QS_PROVENANCE_NOTICE_KEY] = (
        "The current reinforcement rows are now treated as explicit physical bars."
    )


def _qs_restore_settings():
    """Seed the builder widgets from their durable copies before they are created.

    Only fills a key that is absent (the closed-builder case); a key already present
    from the live widget this run is left alone, so in-progress edits are kept.
    """
    for k in _QS_WIDGET_KEYS:
        dk = "qsv_" + k
        if k not in st.session_state and dk in st.session_state:
            st.session_state[k] = st.session_state[dk]


def _qs_mirror_settings():
    """Keep draft builder preferences after its widgets are unmounted.

    Project serialisation overlays the separately retained applied snapshot, so a
    draft that is left with Back does not redefine the current point tables.
    """
    durable = dict(st.session_state.get(_INPUT_STATE_KEY, {}))
    for k in _QS_WIDGET_KEYS:
        if k in st.session_state:
            key = "qsv_" + k
            value = copy.deepcopy(st.session_state[k])
            st.session_state[key] = value
            durable[key] = value
    st.session_state[_INPUT_STATE_KEY] = durable


def _qs_interleave(face_group, diameter_mm):
    """A second bar size at the midpoints between a face group's bars.

    Groups the given bars by y-level and places one bar of ``diameter_mm`` at each
    gap midpoint, so a face row of one size is interleaved with another (e.g. a
    Y20/100 row with Y16 bars sitting between them -- two sizes in the same layer
    without overlapping). Midpoints always sit between existing bars, so the
    interleaved bars stay inside the concrete. Each stacked layer is interleaved.
    """
    a = templates.bar_area(float(diameter_mm))
    by_y = {}
    for x, y, _area in face_group:
        by_y.setdefault(round(float(y), 9), []).append(float(x))
    out = []
    for y, xs in by_y.items():
        xs.sort()
        out.extend((0.5 * (xs[i] + xs[i + 1]), y, a) for i in range(len(xs) - 1))
    return out


_SLAB_DENSITY_GUIDANCE = (
    "The slab-spacing layout no longer matches the current point tables. "
    "Reapply the slab layout, or define explicit bars, before relying on "
    "crack-width or clear-spacing results."
)
_SLAB_TENDON_FACE_GUIDANCE = (
    "Move every tendon far enough inside the physical top and bottom slab "
    "faces to provide non-negative clear cover before relying on crack-width "
    "results."
)


def _slab_face_clear_cover_mm(y_m, diameter_mm, bottom_face_m, top_face_m):
    """Clear cover to the nearest real horizontal slab face."""

    values = (y_m, diameter_mm, bottom_face_m, top_face_m)
    if any(isinstance(value, (bool, np.bool_)) for value in values):
        raise ValueError("slab face cover inputs must be numeric")
    y_m = float(y_m)
    diameter_mm = float(diameter_mm)
    bottom_face_m = float(bottom_face_m)
    top_face_m = float(top_face_m)
    if (
        any(not math.isfinite(value) for value in (
            y_m, diameter_mm, bottom_face_m, top_face_m
        ))
        or diameter_mm <= 0.0
        or bottom_face_m >= top_face_m
    ):
        raise ValueError("slab face cover inputs must be finite")
    clear_cover_mm = (
        min(y_m - bottom_face_m, top_face_m - y_m) * _MM
        - diameter_mm / 2.0
    )
    if clear_cover_mm < -1.0e-9:
        raise ValueError("reinforcement envelope is outside a physical slab face")
    return max(clear_cover_mm, 0.0)


def _slab_tendon_face_clear_cover_mm(y_m, diameter_mm, outer):
    """Clear tendon cover to a real slab face, ignoring unit-strip side cuts."""

    face_coordinates = [float(point[1]) for point in outer]
    if not face_coordinates:
        raise ValueError("slab face cover inputs must be finite")
    return _slab_face_clear_cover_mm(
        y_m,
        diameter_mm,
        min(face_coordinates),
        max(face_coordinates),
    )


def _slab_density_layout(
    *,
    height_m,
    cover_to_edge,
    bottom_diameter_mm,
    top_diameter_mm,
    bottom_cover_m,
    top_cover_m,
    bottom_spacing_m,
    top_spacing_m,
    bottom_layers,
    top_layers,
    layer_spacing_m,
    bottom_interleave_diameter_mm=0.0,
    top_interleave_diameter_mm=0.0,
):
    """Build one traceable slab-density analysis and physical-layout record."""

    if type(cover_to_edge) is not bool:
        raise ValueError("slab cover reference must be selected explicitly")
    if any(isinstance(value, (bool, np.bool_)) for value in (
        bottom_layers, top_layers
    )):
        raise ValueError("slab layer counts must be whole numbers")
    if not all(float(value).is_integer() for value in (
        bottom_layers, top_layers
    )):
        raise ValueError("slab layer counts must be whole numbers")
    bottom_layers = int(bottom_layers)
    top_layers = int(top_layers)
    values = (
        height_m,
        bottom_diameter_mm,
        top_diameter_mm,
        bottom_cover_m,
        top_cover_m,
        bottom_spacing_m,
        top_spacing_m,
        layer_spacing_m,
        bottom_interleave_diameter_mm,
        top_interleave_diameter_mm,
    )
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("slab reinforcement inputs must be finite")
    if not 0.05 <= height_m <= 10.0:
        raise ValueError("slab thickness is outside the available range")
    if not all(0.01 <= spacing <= 1.0 for spacing in (
        bottom_spacing_m, top_spacing_m
    )):
        raise ValueError("slab spacing is outside the available range")
    if not all(1.0 <= diameter <= 100.0 for diameter in (
        bottom_diameter_mm, top_diameter_mm
    )):
        raise ValueError("slab reinforcement diameter is outside the available range")
    if not all(0.0 <= cover <= 0.5 for cover in (
        bottom_cover_m, top_cover_m
    )) or not 0.01 <= layer_spacing_m <= 1.0:
        raise ValueError("slab cover and layer spacing must be valid")
    if not all(0.0 <= diameter <= 100.0 for diameter in (
        bottom_interleave_diameter_mm, top_interleave_diameter_mm
    )):
        raise ValueError("slab interleave diameter is outside the available range")
    if not 1 <= bottom_layers <= 10 or not 1 <= top_layers <= 10:
        raise ValueError("slab layer count is outside the available range")

    def centre_cover(cover_m, diameter_mm):
        return cover_m + (diameter_mm / 2000.0 if cover_to_edge else 0.0)

    def first_layer_axis(face_coordinate, direction, cover_m, diameter_mm):
        return face_coordinate + direction * centre_cover(cover_m, diameter_mm)

    faces = {
        "Bottom": {
            "face_coordinate": -height_m / 2.0,
            "cover_m": bottom_cover_m,
            "y_face": first_layer_axis(
                -height_m / 2.0, 1.0, bottom_cover_m, bottom_diameter_mm
            ),
            "direction": 1.0,
            "diameter_mm": float(bottom_diameter_mm),
            "spacing_m": float(bottom_spacing_m),
            "layers": bottom_layers,
            "interleave_diameter_mm": float(bottom_interleave_diameter_mm),
        },
        "Top": {
            "face_coordinate": height_m / 2.0,
            "cover_m": top_cover_m,
            "y_face": first_layer_axis(
                height_m / 2.0, -1.0, top_cover_m, top_diameter_mm
            ),
            "direction": -1.0,
            "diameter_mm": float(top_diameter_mm),
            "spacing_m": float(top_spacing_m),
            "layers": top_layers,
            "interleave_diameter_mm": float(top_interleave_diameter_mm),
        },
    }
    specs = []
    for face in ("Bottom", "Top"):
        record = faces[face]
        specs.append({**record, "face": face, "role": "Primary", "staggered": False})
    for face in ("Bottom", "Top"):
        record = faces[face]
        if record["interleave_diameter_mm"] > 0.0:
            interleave_diameter = record["interleave_diameter_mm"]
            specs.append({
                **record,
                "face": face,
                "role": "Interleave",
                "diameter_mm": interleave_diameter,
                "y_face": first_layer_axis(
                    record["face_coordinate"],
                    record["direction"],
                    record["cover_m"],
                    interleave_diameter,
                ),
                "staggered": True,
            })

    groups = []
    series = []
    analysis_metadata = []
    physical_elements = []
    next_spacing_group = 0
    face_has_interleave = {
        face: faces[face]["interleave_diameter_mm"] > 0.0
        for face in faces
    }
    for spec in specs:
        group = templates.unit_width_bar_layers(
            spec["y_face"],
            spec["direction"],
            spec["layers"],
            layer_spacing_m,
            1.0,
            spec["spacing_m"],
            spec["diameter_mm"],
            staggered=spec["staggered"],
        )
        nominal = templates.unit_width_nominal_bar_layers(
            spec["y_face"],
            spec["direction"],
            spec["layers"],
            layer_spacing_m,
            1.0,
            spec["spacing_m"],
            spec["diameter_mm"],
            staggered=spec["staggered"],
        )
        radius_m = spec["diameter_mm"] / 2000.0
        if any(
            abs(float(y)) + radius_m > height_m / 2.0 + 1.0e-12
            for _x, y, _area in (*group, *nominal)
        ):
            raise engineer_messages.EngineerValidationError(
                _QUICK_REINFORCEMENT_PLACEMENT
            )
        equivalents = templates.unit_width_bar_equivalents(1.0, spec["spacing_m"])
        area_per_layer = templates.bar_area(spec["diameter_mm"]) * equivalents
        series_record = {
            "face": spec["face"],
            "role": spec["role"],
            "diameter_mm": spec["diameter_mm"],
            "spacing_mm": spec["spacing_m"] * _MM,
            "layers": spec["layers"],
            "equivalents_per_layer": equivalents,
            "area_per_layer_mm2_per_m": area_per_layer,
            "total_area_mm2_per_m": area_per_layer * spec["layers"],
        }
        layer_spacing_groups = tuple(
            range(next_spacing_group, next_spacing_group + spec["layers"])
        )
        next_spacing_group += spec["layers"]
        series_record["spacing_groups"] = layer_spacing_groups
        groups.append((group, spec["diameter_mm"], series_record))
        series.append(series_record)

        row_count = len(templates.unit_width_bar_row(
            spec["y_face"],
            1.0,
            spec["spacing_m"],
            spec["diameter_mm"],
            staggered=spec["staggered"],
        ))
        nearest_spacing_mm = spec["spacing_m"] * _MM * (
            0.5 if face_has_interleave[spec["face"]] else 1.0
        )
        for layer in range(spec["layers"]):
            layer_y = (
                spec["y_face"]
                + spec["direction"] * layer * layer_spacing_m
            )
            clear_cover_mm = _slab_face_clear_cover_mm(
                layer_y,
                spec["diameter_mm"],
                -height_m / 2.0,
                height_m / 2.0,
            )
            analysis_metadata.extend({
                "face": spec["face"],
                "role": spec["role"],
                "layer": layer + 1,
                "spacing_group": layer_spacing_groups[layer],
                "cover_mm": clear_cover_mm,
                "nominal_spacing_mm": nearest_spacing_mm,
            } for _index in range(row_count))

        layer_sizes = []
        remaining = list(nominal)
        for layer in range(spec["layers"]):
            y = spec["y_face"] + spec["direction"] * layer * layer_spacing_m
            layer_points = [point for point in remaining if math.isclose(
                point[1], y, rel_tol=0.0, abs_tol=1.0e-12
            )]
            layer_sizes.append(len(layer_points))
            for index, (x, point_y, area) in enumerate(layer_points, start=1):
                physical_elements.append({
                    "id": (
                        f"{spec['face']} layer {layer + 1} "
                        f"{spec['role'].lower()} {index}"
                    ),
                    "kind": "bar",
                    "spacing_group": layer_spacing_groups[layer],
                    "x_mm": x * _MM,
                    "y_mm": point_y * _MM,
                    "area_mm2": area,
                    "diameter_mm": spec["diameter_mm"],
                })
            remaining = [point for point in remaining if not math.isclose(
                point[1], y, rel_tol=0.0, abs_tol=1.0e-12
            )]
        series_record["nominal_positions_per_layer"] = tuple(layer_sizes)

    bars = templates.merge_bars(*(group for group, _diameter, _series in groups))
    diameters = [
        float(diameter)
        for group, diameter, _series in groups
        for _point in group
    ]
    return {
        "bars": bars,
        "diameters_mm": diameters,
        "series": tuple(series),
        "analysis_metadata": tuple(analysis_metadata),
        "physical_elements": tuple(physical_elements),
    }


def _slab_density_layout_from_state(state):
    """Rebuild the saved slab-density intent without trusting point history."""

    if (
        state.get("qsv_shape") != "Slab strip"
        or state.get("qsv_qs_rebar_mode") != "By spacing"
    ):
        return None
    return _slab_density_layout(
        height_m=float(state.get("qsv_h_mm", 300.0)) / _MM,
        cover_to_edge=bool(state.get("qsv_qs_cover_to_edge", False)),
        bottom_diameter_mm=float(state.get("qsv_bot_d", 20.0)),
        top_diameter_mm=float(state.get("qsv_top_d", 20.0)),
        bottom_cover_m=float(state.get("qsv_bot_c_mm", 50.0)) / _MM,
        top_cover_m=float(state.get("qsv_top_c_mm", 50.0)) / _MM,
        bottom_spacing_m=float(state.get("qsv_bot_s", 150.0)) / _MM,
        top_spacing_m=float(state.get("qsv_top_s", 150.0)) / _MM,
        bottom_layers=int(state.get("qsv_bot_layers", 1)),
        top_layers=int(state.get("qsv_top_layers", 1)),
        layer_spacing_m=float(state.get("qsv_layer_s", 60.0)) / _MM,
        bottom_interleave_diameter_mm=float(state.get("qsv_bot_off_d", 0.0)),
        top_interleave_diameter_mm=float(state.get("qsv_top_off_d", 0.0)),
    )


def _slab_density_reconciliation(state, outer, holes, bar_frame):
    """Return verified physical evidence or a fail-closed density disposition."""

    applied_state = state.get(_QS_APPLIED_SETTINGS_KEY)
    retained_state = state.get(_QS_RETAINED_SETTINGS_KEY)
    verified_state = state.get(_QS_VERIFIED_DENSITY_SETTINGS_KEY)
    has_applied_provenance = isinstance(applied_state, dict)
    has_verified_density = isinstance(verified_state, dict)
    has_physical_provenance = has_applied_provenance or has_verified_density
    intent_state = (
        applied_state
        if has_applied_provenance
        else verified_state
        if has_verified_density
        else retained_state
        if isinstance(retained_state, dict)
        else state
    )
    try:
        layout = _slab_density_layout_from_state(intent_state)
    except (TypeError, ValueError, OverflowError):
        return (
            {"status": "UNVERIFIED", "reason": _SLAB_DENSITY_GUIDANCE}
            if has_physical_provenance
            else None
        )
    if layout is None:
        return None
    # ``rectangle`` takes width then height; the slab strip is always exactly 1 m.
    expected_outer = templates.rectangle(
        1.0, float(intent_state.get("qsv_h_mm", 300.0)) / _MM
    )

    def points_match(left, right, *, tolerance=1.0e-9):
        return len(left) == len(right) and all(
            math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tolerance)
            for point_a, point_b in zip(left, right)
            for a, b in zip(point_a, point_b)
        )

    geometry_matches = points_match(outer, expected_outer) and not holes
    try:
        frame = rebar_table.normalise_table(bar_frame, "bar")
        rows = frame.to_dict("records")
        bars_match = len(rows) == len(layout["bars"])
        if bars_match:
            for row, point, diameter in zip(
                rows, layout["bars"], layout["diameters_mm"]
            ):
                actual = (
                    row.get(rebar_table.X),
                    row.get(rebar_table.Y),
                    row.get(rebar_table.AREA),
                    row.get(rebar_table.DIAMETER),
                )
                expected = (
                    point[0] * _MM,
                    point[1] * _MM,
                    point[2],
                    diameter,
                )
                if (
                    row.get(rebar_table.SIZE_MODE) != rebar_table.INDEPENDENT_MODE
                    or not all(
                        value is not None and math.isclose(
                            float(value), float(reference), rel_tol=1.0e-10,
                            abs_tol=1.0e-6,
                        )
                        for value, reference in zip(actual, expected)
                    )
                ):
                    bars_match = False
                    break
    except (TypeError, ValueError, OverflowError):
        bars_match = False
    if not geometry_matches or not bars_match:
        if not has_physical_provenance:
            # A legacy/current-schema qsv_ block may be only a discarded preview.
            # Treat the loaded point tables as explicit rather than disabling
            # physical checks on the strength of unverified builder history.
            return None
        return {
            "status": "UNVERIFIED",
            "reason": _SLAB_DENSITY_GUIDANCE,
            # Only a bar-table replacement inside the unchanged applied slab
            # outline can be confirmed as an explicit physical layout. An outline
            # or void edit still requires a fresh Apply so stale shape dimensions
            # cannot be attached to unrelated section geometry.
            "can_use_explicit_bars": geometry_matches and not bars_match,
        }
    if not has_physical_provenance:
        # Reconciliation proves the slab-density bar/outline relation needed by
        # physical checks. It does not retroactively prove every legacy builder
        # preference (notably tendon preview settings), so keep this evidence
        # separate from an Apply-created persistence snapshot.
        state[_QS_VERIFIED_DENSITY_SETTINGS_KEY] = copy.deepcopy(
            retained_state
            if isinstance(retained_state, dict)
            else _qs_settings_snapshot(state)
        )
    return {**layout, "status": "VERIFIED", "reason": None}


def _slab_density_face_caption(layout, face):
    """Engineer-facing series and total area statement for one slab face."""

    selected = [series for series in layout["series"] if series["face"] == face]
    parts = []
    for series in selected:
        parts.append(
            f"{series['role']} T{series['diameter_mm']:g} @ "
            f"{series['spacing_mm']:g} mm: "
            f"{series['equivalents_per_layer']:.3f} bar-equivalents/m and "
            f"Aₛ = {series['area_per_layer_mm2_per_m']:,.3f} mm²/m per layer."
        )
    layers = selected[0]["layers"]
    per_layer = sum(series["area_per_layer_mm2_per_m"] for series in selected)
    total = per_layer * layers
    parts.append(
        f"{face} total: Aₛ = {per_layer:,.3f} mm²/m per layer and "
        f"{total:,.3f} mm²/m over {layers} layer{'s' if layers != 1 else ''}."
    )
    return " ".join(parts)


def _slab_density_preview_caption(layout, face):
    selected = [series for series in layout["series"] if series["face"] == face]
    layers = selected[0]["layers"]
    names = " + ".join(
        f"{series['role'].lower()} T{series['diameter_mm']:g} @ "
        f"{series['spacing_mm']:g} mm"
        for series in selected
    )
    per_layer = sum(series["area_per_layer_mm2_per_m"] for series in selected)
    return (
        f"{face}: {layers} layer{'s' if layers != 1 else ''}; {names}; "
        f"Aₛ = {per_layer:,.3f} mm²/m per layer and "
        f"{per_layer * layers:,.3f} mm²/m in total."
    )


def _default_quick_section():
    """The section a fresh session starts from (used to seed the point tables): a
    400 x 600 mm rectangle with 6 bottom and 2 top 20 mm bars at 50 mm cover."""
    b, h, cov = 0.4, 0.6, 0.05
    outer = templates.rectangle(b, h)
    bars = templates.merge_bars(
        templates.bar_row(-h / 2 + cov, -b / 2 + cov, b / 2 - cov, 6, 20.0),
        templates.bar_row(h / 2 - cov, -b / 2 + cov, b / 2 - cov, 2, 20.0))
    return outer, [], bars, []


def _quick_section_geometry(box):
    """Render the shape, dimension and reinforcement inputs in ``box`` and return
    the generated geometry and reinforcement (metres / mm areas). Slab-density
    rows also return their physical diameters beside the equivalent point areas.

    Shared by the builder viewport: the widgets keep their own keys so the last
    settings persist between openings. Reinforcement is two rows (bottom / top)
    placed either by bar count or by centre-to-centre spacing (slab ``phi @ s``);
    a circular section uses a perimeter ring.
    """
    shape = _seeded_selectbox(
        box,
        "Shape",
        _QS_SHAPES,
        "Rectangle",
        "shape",
        help="Outline of the concrete cross-section to analyse.",
    )
    _qs_shape_prefill(shape)   # re-seed b/h on a shape change (see the prefill note)
    holes = []
    slab_bar_diameters = None
    bar_envelope_diameters = []
    slab_density_layout = None
    slab_unit_spacing = False
    bottom_span_at = top_span_at = None
    if shape == "Rectangle":
        b = _seeded_number(box, r"Width $b$ (mm)", 50.0, 10000.0, 400.0, 10.0, "b_mm",
                           help="Overall section width.") / 1000.0
        h = _seeded_number(box, r"Height $h$ (mm)", 50.0, 10000.0, 600.0, 10.0, "h_mm",
                           help="Overall section height (depth).") / 1000.0
        outer = templates.rectangle(b, h)
        width_b = b
    elif shape == "Slab strip":
        h = _seeded_number(box, r"Thickness $h$ (mm)", 50.0, 3000.0, 300.0, 10.0, "h_mm",
                           help="Slab thickness; the strip is analysed per 1 m width.") / 1000.0
        b = width_b = 1.0
        outer = templates.slab_strip(h)
    elif shape == "Trapezoid":
        bottom_width = _seeded_number(
            box, "Bottom width (mm)", 50.0, 12000.0, 800.0, 10.0,
            "trap_bottom_mm", help="Width of the horizontal bottom face."
        ) / 1000.0
        top_width = _seeded_number(
            box, "Top width (mm)", 50.0, 12000.0, 500.0, 10.0,
            "trap_top_mm", help="Width of the horizontal top face."
        ) / 1000.0
        h = _seeded_number(
            box, "Height (mm)", 50.0, 12000.0, 700.0, 10.0,
            "trap_h_mm", help="Overall trapezoid height."
        ) / 1000.0
        outer = templates.trapezoid(bottom_width, top_width, h)
        b, width_b = bottom_width, top_width
    elif shape == "T-section":
        orientation_label = _seeded_selectbox(
            box,
            "Orientation",
            ["Flange at top", "Flange at bottom"],
            "Flange at top",
            "t_orientation",
            help="Flip the T vertically without changing its section dimensions.",
        )
        orientation = (
            "upright" if orientation_label == "Flange at top" else "inverted"
        )
        bf = _seeded_number(box, r"Flange width $b_f$ (mm)", 100.0, 12000.0, 1200.0, 10.0, "bf_mm",
                            help="Width of the flange.") / 1000.0
        hf = _seeded_number(box, r"Flange thickness $h_f$ (mm)", 50.0, 2000.0, 200.0, 10.0, "hf_mm",
                            help="Thickness of the flange.") / 1000.0
        bw = _seeded_number(box, r"Web width $b_w$ (mm)", 50.0, 4000.0, 300.0, 10.0, "bw_mm",
                            help="Width of the web.") / 1000.0
        hw = _seeded_number(box, r"Web depth $h_w$ (mm)", 100.0, 6000.0, 600.0, 10.0, "hw_mm",
                            help="Depth of the web below the flange.") / 1000.0
        outer = templates.t_section(bf, hf, bw, hw, orientation=orientation)
        h = hf + hw
        if orientation == "upright":
            b, width_b = bw, bf
            junction_y = h / 2.0 - hf

            def section_width_at(y):
                return bf if y >= junction_y else bw
        else:
            b, width_b = bf, bw
            junction_y = -h / 2.0 + hf

            def section_width_at(y):
                return bf if y <= junction_y else bw
    elif shape == "L-section":
        b = _seeded_number(
            box, "Overall width (mm)", 50.0, 12000.0, 800.0, 10.0,
            "l_b_mm", help="Overall bounding width of the L-section."
        ) / 1000.0
        h = _seeded_number(
            box, "Overall height (mm)", 50.0, 12000.0, 800.0, 10.0,
            "l_h_mm", help="Overall bounding height of the L-section."
        ) / 1000.0
        web = _seeded_number(
            box, "Left web thickness (mm)", 10.0, 6000.0, 200.0, 10.0,
            "l_web_mm", help="Thickness of the vertical left leg."
        ) / 1000.0
        flange = _seeded_number(
            box, "Bottom flange thickness (mm)", 10.0, 6000.0, 200.0, 10.0,
            "l_flange_mm", help="Thickness of the horizontal bottom leg."
        ) / 1000.0
        outer = templates.l_section(b, h, web, flange)
        width_b = b
    elif shape == "I-section":
        bf = _seeded_number(
            box, r"Flange width $b_f$ (mm)", 100.0, 12000.0, 800.0, 10.0,
            "i_bf_mm", help="Common width of the top and bottom flanges."
        ) / 1000.0
        tf = _seeded_number(
            box, r"Flange thickness $t_f$ (mm)", 10.0, 3000.0, 200.0, 10.0,
            "i_tf_mm", help="Common thickness of the top and bottom flanges."
        ) / 1000.0
        bw = _seeded_number(
            box, r"Web width $b_w$ (mm)", 10.0, 6000.0, 250.0, 10.0,
            "i_bw_mm", help="Width of the central web."
        ) / 1000.0
        hw = _seeded_number(
            box, r"Clear web height $h_w$ (mm)", 50.0, 12000.0, 600.0, 10.0,
            "i_hw_mm", help="Clear web height between the two flanges."
        ) / 1000.0
        outer = templates.i_section(bf, tf, bw, hw)
        b = width_b = bf
        h = hw + 2.0 * tf
        flange_limit = h / 2.0 - tf

        def section_width_at(y):
            return bf if abs(y) >= flange_limit else bw
    elif shape == "U-section":
        b = _seeded_number(
            box, "Overall width (mm)", 100.0, 12000.0, 800.0, 10.0,
            "u_b_mm", help="Overall outer width of the open-top U-section."
        ) / 1000.0
        h = _seeded_number(
            box, "Overall height (mm)", 100.0, 12000.0, 800.0, 10.0,
            "u_h_mm", help="Overall outer height of the open-top U-section."
        ) / 1000.0
        web = _seeded_number(
            box, "Side-web thickness (mm)", 10.0, 6000.0, 150.0, 10.0,
            "u_web_mm", help="Common thickness of the two vertical side webs."
        ) / 1000.0
        base = _seeded_number(
            box, "Base thickness (mm)", 10.0, 6000.0, 200.0, 10.0,
            "u_base_mm", help="Thickness of the horizontal bottom base."
        ) / 1000.0
        outer = templates.u_section(b, h, web, base)
        width_b = b
    elif shape == "Box girder":
        b = _seeded_number(box, r"Width $b$ (mm)", 200.0, 12000.0, 800.0, 10.0, "b_mm",
                           help="Overall outer width of the box.") / 1000.0
        h = _seeded_number(box, r"Height $h$ (mm)", 200.0, 12000.0, 1000.0, 10.0, "h_mm",
                           help="Overall outer height of the box.") / 1000.0
        max_wall = round((min(b, h) / 2 - 0.01) * 1000.0, 0)
        # wall_mm has a dimension-dependent maximum, so clamp the seeded value into
        # range before the widget (a wider box left a wall that the narrower one can
        # no longer accept would otherwise error).
        st.session_state.setdefault("wall_mm", min(200.0, max_wall))
        st.session_state["wall_mm"] = min(float(st.session_state["wall_mm"]), max_wall)
        wall = box.number_input("Wall thickness (mm)", 20.0, max_wall, step=10.0,
                                key="wall_mm",
                                help="Thickness of the box walls (uniform).") / 1000.0
        outer, holes = templates.box(b, h, wall)
        width_b = b
    elif shape == "Circular":
        dia = _seeded_number(box, "Diameter (mm)", 100.0, 6000.0, 600.0, 10.0, "dia_mm",
                             help="Outer diameter of the circular section.") / 1000.0
        outer = templates.circular(dia)
        b = h = width_b = dia
    else:  # Annulus
        dia = _seeded_number(
            box, "Outer diameter (mm)", 100.0, 12000.0, 800.0, 10.0,
            "annulus_outer_mm", help="Outer diameter of the annulus."
        ) / 1000.0
        inner_dia = _seeded_number(
            box, "Inner diameter (mm)", 10.0, 11000.0, 400.0, 10.0,
            "annulus_inner_mm", help="Diameter of the central circular void."
        ) / 1000.0
        outer, holes = templates.annulus(dia, inner_dia)
        b = h = width_b = dia

    box.markdown("**Reinforcement**")
    if shape in {"Trapezoid", "L-section", "U-section"}:
        box.info(
            "Automatic reinforcement placement is not defined for this shape. "
            "Apply creates the concrete geometry only; add bars and tendons in "
            "the point tables."
        )
        return outer, holes, [], [], None, None
    # Cover can be measured to the near edge of the bars rather than to their centres
    # -- the centre then sits a bar radius deeper. Applied to the mild bars (bottom /
    # top rows and the circular ring); tendons keep a centre cover.
    cover_to_edge = _seeded_checkbox(
        box, "Cover to bar edge (else to bar centre)", False, "qs_cover_to_edge",
        help=(
            "Measure the cover to the near surface of each bar series, not its "
            "centre. Different interleaved diameters can therefore have different "
            "centre lines while retaining the same clear cover."
        ))
    _edge = lambda cov, dia_mm: cov + (dia_mm / 2000.0 if cover_to_edge else 0.0)
    if shape in {"Circular", "Annulus"}:
        nb = _seeded_number(box, "Perimeter bars", 0, 200, 8, 1, "ring_n",
                            help="Number of bars evenly spaced around the perimeter.")
        rd = _seeded_number(box, "Bar diameter (mm)", 1.0, 100.0, 20.0, 1.0, "ring_d",
                            help="Diameter of each reinforcement bar.")
        cov = _seeded_number(box, "Cover (mm)", 0.0, 500.0, 50.0, 5.0, "ring_c_mm",
                             help="Cover from the section face to the bars.") / 1000.0
        if int(nb) > 0:
            ring_cover = _edge(cov, rd)
            radius = (
                templates.annulus_ring_radius(dia, inner_dia, ring_cover)
                if shape == "Annulus"
                else templates.ring_radius(dia, ring_cover)
            )
            bars = templates.bar_ring(0.0, 0.0, radius, int(nb), rd)
            bar_envelope_diameters = [float(rd)] * len(bars)
        else:
            bars = []
    else:
        spacing_help = (
            "For a slab strip, By spacing uses diameter and spacing to calculate "
            "reinforcement area per metre. By number places explicit bars."
            if shape == "Slab strip"
            else
            "For a finite section, By spacing is the maximum centre-to-centre gap "
            "over the covered face; the builder derives count and actual spacing."
        )
        by_spacing = box.radio(
            "Bar placement", ["By number", "By spacing"], horizontal=True,
            key="qs_rebar_mode",
            help=spacing_help,
        ) == "By spacing"
        slab_unit_spacing = shape == "Slab strip" and by_spacing
        if slab_unit_spacing:
            box.info(
                "Slab-strip spacing defines reinforcement area per metre of slab "
                "width. Bottom and top cover set the corresponding layer depth."
            )
        c1, c2 = box.columns(2)
        c1.markdown("**Bottom**")
        c2.markdown("**Top**")
        rd_bot = _seeded_number(c1, "Bottom dia (mm)", 1.0, 100.0, 20.0, 1.0, "bot_d",
                                help="Bottom bar diameter (mm).")
        rd_top = _seeded_number(c2, "Top dia (mm)", 1.0, 100.0, 20.0, 1.0, "top_d",
                                help="Top bar diameter (mm).")
        bot_cov = _seeded_number(c1, "Bottom cover (mm)", 0.0, 500.0, 50.0, 5.0, "bot_c_mm",
                                 help="Cover at the bottom face.") / 1000.0
        top_cov = _seeded_number(c2, "Top cover (mm)", 0.0, 500.0, 50.0, 5.0, "top_c_mm",
                                 help="Cover at the top face.") / 1000.0
        # Bar-centre covers (add a radius when the cover is measured to the bar edge).
        bot_e, top_e = _edge(bot_cov, rd_bot), _edge(top_cov, rd_top)
        bot_w, top_w = b - 2.0 * bot_e, width_b - 2.0 * top_e
        s_bot = s_top = None
        if by_spacing:
            spacing_label = (
                "nominal spacing" if slab_unit_spacing else "maximum spacing"
            )
            spacing_input_help = (
                "Nominal centre-to-centre spacing used with the entered diameter "
                "to calculate reinforcement area per metre of slab width."
                if slab_unit_spacing
                else
                "Maximum centre-to-centre gap over the covered face. The derived "
                "bar count can make the actual spacing smaller."
            )
            s_bot = _seeded_number(
                c1, f"Bottom {spacing_label} (mm)", 10.0, 1000.0, 150.0, 5.0,
                "bot_s", help=spacing_input_help,
            ) / 1000.0
            s_top = _seeded_number(
                c2, f"Top {spacing_label} (mm)", 10.0, 1000.0, 150.0, 5.0,
                "top_s", help=spacing_input_help,
            ) / 1000.0
            if slab_unit_spacing:
                nb_bot = templates.count_for_unit_width(1.0, s_bot)
                nb_top = templates.count_for_unit_width(1.0, s_top)
            else:
                nb_bot = templates.count_for_spacing(bot_w, s_bot)
                nb_top = templates.count_for_spacing(top_w, s_top)
                bot_actual = bot_w / (nb_bot - 1) if nb_bot > 1 else None
                top_actual = top_w / (nb_top - 1) if nb_top > 1 else None
                c1.caption(
                    f"Face row: {nb_bot} bars; actual c/c spacing = "
                    f"{bot_actual * 1000.0:.1f} mm."
                    if bot_actual is not None
                    else f"Face row: {nb_bot} bar; actual spacing is not applicable."
                )
                c2.caption(
                    f"Face row: {nb_top} bars; actual c/c spacing = "
                    f"{top_actual * 1000.0:.1f} mm."
                    if top_actual is not None
                    else f"Face row: {nb_top} bar; actual spacing is not applicable."
                )

            # For finite sections the count follows each row's own clear span, so a
            # top row narrowed to the web keeps the maximum-spacing contract instead
            # of inheriting the flange count. Slab strips use area density below.
            def n_at_bot(xs, xe):
                return templates.count_for_spacing(xe - xs, s_bot)

            def n_at_top(xs, xe):
                return templates.count_for_spacing(xe - xs, s_top)
        else:
            n_at_bot = n_at_top = None  # by-number: fixed count per layer
            nb_bot = _seeded_number(c1, "Bottom bars", 0, 100, 6, 1, "bot_n",
                                    help="Number of bars in the first bottom layer.")
            nb_top = _seeded_number(c2, "Top bars", 0, 100, 2, 1, "top_n",
                                    help="Number of bars in the first top layer.")
        nl_bot = _seeded_number(c1, "Bottom layers", 1, 10, 1, 1, "bot_layers",
                                help="Number of stacked bar rows at the bottom face.")
        nl_top = _seeded_number(c2, "Top layers", 1, 10, 1, 1, "top_layers",
                                help="Number of stacked bar rows at the top face.")
        # By number, the stacked (upper) layers can hold a different count than the
        # first row. By spacing, each row's count follows its own span, so it is off.
        bot_n2 = _seeded_number(c1, "Bottom upper-layer bars", 0, 100, 6, 1, "bot_n2",
                                disabled=by_spacing or int(nl_bot) <= 1,
                                help="Bars in each bottom layer above the first.")
        top_n2 = _seeded_number(c2, "Top upper-layer bars", 0, 100, 2, 1, "top_n2",
                                disabled=by_spacing or int(nl_top) <= 1,
                                help="Bars in each top layer above the first.")
        ne_bot = int(bot_n2) if (not by_spacing and int(nl_bot) > 1) else None
        ne_top = int(top_n2) if (not by_spacing and int(nl_top) > 1) else None
        bot_has_bars = int(nb_bot) > 0 or (ne_bot is not None and ne_bot > 0)
        top_has_bars = int(nb_top) > 0 or (ne_top is not None and ne_top > 0)
        if (not slab_unit_spacing and shape not in {"T-section", "I-section"}
                and bot_has_bars and bot_w < 0.0):
            raise engineer_messages.EngineerValidationError(_QUICK_BOTTOM_COVER)
        if (not slab_unit_spacing and shape not in {"T-section", "I-section"}
                and top_has_bars and top_w < 0.0):
            raise engineer_messages.EngineerValidationError(_QUICK_TOP_COVER)
        layer_s = _seeded_number(
            box, "Layer spacing (mm)", 10.0, 1000.0, 60.0, 5.0, "layer_s",
            disabled=int(nl_bot) == 1 and int(nl_top) == 1,
            help="Vertical centre-to-centre distance between stacked bar layers "
                 "(used only when a face has more than one layer).") / 1000.0
        # Optional second bar size, interleaved at the midpoints of each face row
        # (0 = off) -- e.g. a Y20/100 row with Y16 bars between them (two sizes in one
        # layer).
        o1, o2 = box.columns(2)
        bot_off_d = _seeded_number(o1, "Bottom interleave dia (mm, 0 = off)", 0.0, 100.0,
                                   0.0, 1.0, "bot_off_d",
                                   help=(
                                       "Second bar size at the midpoints of the bottom "
                                       "row(s); 0 = off. Edge cover applies to this "
                                       "diameter; centre cover retains the primary "
                                       "row's centre line."
                                   ))
        top_off_d = _seeded_number(o2, "Top interleave dia (mm, 0 = off)", 0.0, 100.0,
                                   0.0, 1.0, "top_off_d",
                                   help=(
                                       "Second bar size at the midpoints of the top "
                                       "row(s); 0 = off. Edge cover applies to this "
                                       "diameter; centre cover retains the primary "
                                       "row's centre line."
                                   ))
        if slab_unit_spacing:
            slab_density_layout = _slab_density_layout(
                height_m=h,
                cover_to_edge=cover_to_edge,
                bottom_diameter_mm=rd_bot,
                top_diameter_mm=rd_top,
                bottom_cover_m=bot_cov,
                top_cover_m=top_cov,
                bottom_spacing_m=s_bot,
                top_spacing_m=s_top,
                bottom_layers=int(nl_bot),
                top_layers=int(nl_top),
                layer_spacing_m=layer_s,
                bottom_interleave_diameter_mm=bot_off_d,
                top_interleave_diameter_mm=top_off_d,
            )
            c1.caption(_slab_density_face_caption(slab_density_layout, "Bottom"))
            c2.caption(_slab_density_face_caption(slab_density_layout, "Top"))
        # T/I layers can cross a flange/web junction. Recompute each row's clear
        # face span at its actual y-coordinate so no stacked row can escape a
        # narrower web. The same rule applies from both faces (and after flipping T).
        if shape in {"T-section", "I-section"}:
            def bottom_span_at(y):
                row_width = section_width_at(y)
                if bot_has_bars and row_width < 2.0 * bot_e:
                    raise engineer_messages.EngineerValidationError(
                        _QUICK_BOTTOM_COVER
                    )
                return -row_width / 2 + bot_e, row_width / 2 - bot_e

            def top_span_at(y):
                row_width = section_width_at(y)
                if top_has_bars and row_width < 2.0 * top_e:
                    raise engineer_messages.EngineerValidationError(
                        _QUICK_TOP_COVER
                    )
                return -row_width / 2 + top_e, row_width / 2 - top_e

        if slab_unit_spacing:
            bars = list(slab_density_layout["bars"])
            slab_bar_diameters = list(slab_density_layout["diameters_mm"])
            bar_envelope_diameters = slab_bar_diameters
        elif shape == "Box girder":
            # A box girder's rows split into the side walls once they rise into the
            # hollow, so multi-layer reinforcement keeps its count in the webs.
            bot_group = templates.box_layers(-h / 2 + bot_e, 1.0, int(nl_bot), layer_s,
                                             b, h, wall, bot_e, int(nb_bot),
                                             templates.bar_area(rd_bot), n_extra=ne_bot)
            top_group = templates.box_layers(h / 2 - top_e, -1.0, int(nl_top), layer_s,
                                             b, h, wall, top_e, int(nb_top),
                                             templates.bar_area(rd_top), n_extra=ne_top)
        else:
            bot_group = templates.bar_layers(-h / 2 + bot_e, 1.0, int(nl_bot), layer_s,
                                             -b / 2 + bot_e, b / 2 - bot_e, int(nb_bot),
                                             rd_bot, span_at=bottom_span_at,
                                             n_at=n_at_bot, n_extra=ne_bot)
            top_group = templates.bar_layers(h / 2 - top_e, -1.0, int(nl_top), layer_s,
                                             -width_b / 2 + top_e, width_b / 2 - top_e,
                                             int(nb_top), rd_top, span_at=top_span_at,
                                             n_at=n_at_top, n_extra=ne_top)
        if not slab_unit_spacing:
            groups = [(bot_group, rd_bot), (top_group, rd_top)]
            face_groups = (
                (bot_group, bot_off_d, rd_bot, 1.0),
                (top_group, top_off_d, rd_top, -1.0),
            )
            for grp, off_d, primary_diameter, direction in face_groups:
                if off_d <= 0.0:
                    continue
                inter = _qs_interleave(grp, off_d)
                if cover_to_edge:
                    shift = direction * (off_d - primary_diameter) / 2000.0
                    inter = [(x, y + shift, area) for x, y, area in inter]
                # A row split across a void leaves a gap whose midpoint is not
                # concrete. The same filter guards concave outlines.
                if inter:
                    ok = geometry.points_inside_concrete(
                        [(x, y) for x, y, _a in inter], outer, holes)
                    inter = [p for p, good in zip(inter, ok) if good]
                groups.append((inter, off_d))
            bars = templates.merge_bars(*(group for group, _diameter in groups))
            bar_envelope_diameters = [
                float(diameter)
                for group, diameter in groups
                for _point in group
            ]

    box.markdown("**Prestressing tendons**")
    nt = _seeded_number(box, "Tendons", 0, 200, 0, 1, "tnd_n",
                        help="Number of tendons the Quick Section places (0 = none). "
                             "Tendons can also be entered directly in the points table.")
    a_t = _seeded_number(box, "Area per tendon (mm2)", 1.0, 50000.0, 150.0, 10.0, "tnd_a",
                         help="Cross-sectional area of a single tendon.")
    cov_p = _seeded_number(box, "Tendon cover (mm)", 0.0, 2000.0, 100.0, 10.0, "tnd_c_mm",
                           help="Distance from the bottom face (or the circular "
                                "ring) to the tendons.") / 1000.0
    nl_t = _seeded_number(box, "Tendon layers", 1, 10, 1, 1, "tnd_layers",
                          help="Number of stacked tendon rows from the bottom face "
                               "(ignored for a circular ring).")
    ls_t = _seeded_number(
        box, "Tendon layer spacing (mm)", 10.0, 1000.0, 60.0, 5.0, "tnd_layer_s",
        disabled=int(nl_t) == 1,
        help="Vertical centre-to-centre distance between stacked tendon rows.") / 1000.0
    tendons = []
    if nt > 0:
        if shape in {"Circular", "Annulus"}:
            radius = (
                templates.annulus_ring_radius(b, inner_dia, cov_p)
                if shape == "Annulus"
                else templates.ring_radius(b, cov_p)
            )
            tendons = templates.point_ring(
                0.0, 0.0, radius, int(nt), a_t)
        elif shape == "Box girder":
            tendons = templates.box_layers(-h / 2 + cov_p, 1.0, int(nl_t), ls_t,
                                           b, h, wall, cov_p, int(nt), a_t)
        else:
            if shape in {"T-section", "I-section"}:
                def tendon_span_at(y):
                    row_width = section_width_at(y)
                    if row_width < 2.0 * cov_p:
                        raise engineer_messages.EngineerValidationError(
                            _QUICK_TENDON_COVER
                        )
                    return -row_width / 2 + cov_p, row_width / 2 - cov_p
            else:
                tendon_span_at = None
                if b < 2.0 * cov_p:
                    raise engineer_messages.EngineerValidationError(
                        _QUICK_TENDON_COVER
                    )
            tendons = templates.point_layers(-h / 2 + cov_p, 1.0, int(nl_t), ls_t,
                                             -b / 2 + cov_p, b / 2 - cov_p, int(nt), a_t,
                                             span_at=tendon_span_at)
    generated = bars + tendons
    if generated:
        contained = geometry.points_inside_concrete(
            [(x, y) for x, y, _area in generated], outer, holes
        )
        if not all(contained):
            raise engineer_messages.EngineerValidationError(
                _QUICK_REINFORCEMENT_PLACEMENT
            )
    if bars:
        if len(bar_envelope_diameters) != len(bars):
            raise engineer_messages.EngineerValidationError(
                _QUICK_REINFORCEMENT_PLACEMENT
            )
        if shape in {"Circular", "Annulus"}:
            outer_radius = dia / 2.0
            inner_radius = inner_dia / 2.0 if shape == "Annulus" else None
            envelopes_inside = all(
                math.hypot(float(x), float(y)) + float(diameter) / 2000.0
                <= outer_radius + 1.0e-12
                and (
                    inner_radius is None
                    or math.hypot(float(x), float(y))
                    - float(diameter) / 2000.0
                    >= inner_radius - 1.0e-12
                )
                for (x, y, _area), diameter in zip(
                    bars, bar_envelope_diameters
                )
            )
        elif slab_unit_spacing:
            envelopes_inside = all(
                abs(float(y)) + float(diameter) / 2000.0
                <= h / 2.0 + 1.0e-12
                for (_x, y, _area), diameter in zip(
                    bars, bar_envelope_diameters
                )
            )
        else:
            rings = (outer, *(holes or []))
            envelopes_inside = all(
                geometry.distance_to_boundary(float(x), float(y), rings)
                + 1.0e-12
                >= float(diameter) / 2000.0
                for (x, y, _area), diameter in zip(
                    bars, bar_envelope_diameters
                )
            )
        if not envelopes_inside:
            raise engineer_messages.EngineerValidationError(
                _QUICK_REINFORCEMENT_PLACEMENT
            )
    return (
        outer,
        (holes or []),
        bars,
        tendons,
        slab_bar_diameters,
        slab_density_layout,
    )


@st.fragment
def _quick_section_viewport():
    """Full-width Quick Section builder shown in place of the analysis layout.

    Pick a shape, dimensions and a reinforcement layout with a live preview, then
    Apply to write explicit points into the editable tables (which stay the source
    of truth) or Back to leave them untouched. Mirrors the BriCoS manual viewport:
    a session flag (``_qs_open``) renders this instead of the normal layout.

    The builder is an independent Streamlit fragment. Editing a dimension or layout
    therefore rebuilds only the form and its live preview, not the unchanged input
    tabs. Apply and Back still call a full rerun because they leave this viewport.
    """
    app_run_probe.open_fragment_run(st.session_state, "quick_section")
    _qs_restore_settings()   # bring back the settings from the last time it was open
    st.markdown("## Quick Section builder")
    st.caption("Generate a parametric section. Apply overwrites the corner, bar "
               "and tendon point tables with what is drawn here; Back discards it "
               "and leaves the current points untouched.")
    bcol, acol, _ = st.columns([1, 1, 3])
    back = bcol.button("Back", width="stretch", key="qs_back")
    apply_slot = acol.empty()

    form, preview = st.columns([2, 3])
    generation_error = None
    outer, holes, bars, tendons, bar_diameters = [], [], [], [], None
    slab_density_layout = None
    with form:
        try:
            (
                outer,
                holes,
                bars,
                tendons,
                bar_diameters,
                slab_density_layout,
            ) = _quick_section_geometry(st)
        except Exception as exc:
            generation_error = engineer_messages.error_detail(
                exc,
                fallback=_QUICK_SECTION_DISPLAY,
                context="Quick Section generation",
            )
            st.error(f"Quick Section cannot be generated: {generation_error}.")
    apply = apply_slot.button(
        "Apply to point tables",
        type="primary",
        width="stretch",
        key="qs_apply",
        disabled=generation_error is not None,
    )
    _qs_mirror_settings()   # keep the durable copy current with what is shown
    preview_token = app_run_probe.start_phase(st.session_state, "preview")
    try:
        with preview:
            if generation_error is not None:
                st.info("Preview unavailable until the dimensions are valid.")
            else:
                bar_xy = [(x, y, a) for x, y, a in bars]
                tendon_xy = [(x, y, a) for x, y, a in tendons]
                st.plotly_chart(
                    viz.section_figure(outer, holes, bar_xy, tendons=tendon_xy,
                                       title="Preview", show_labels=True, height=560,
                                       scale=_MM, unit="mm"),
                    width="stretch")
                if slab_density_layout is not None:
                    st.caption(_slab_density_preview_caption(
                        slab_density_layout, "Bottom"
                    ))
                    st.caption(_slab_density_preview_caption(
                        slab_density_layout, "Top"
                    ))
                    bar_summary = f"{len(bars)} slab-density analysis points"
                elif bar_diameters is None:
                    bar_summary = f"{len(bars)} bars"
                else:
                    equivalents = sum(
                        float(point[2]) / templates.bar_area(float(diameter))
                        for point, diameter in zip(bars, bar_diameters)
                    )
                    bar_summary = f"{equivalents:.3f} bar-equivalents/m"
                st.caption(
                    f"{len(outer)} concrete corners, {len(holes)} void(s), "
                    f"{bar_summary}, {len(tendons)} tendons."
                )
    finally:
        app_run_probe.stop_phase(st.session_state, preview_token)

    if back:
        st.session_state["_qs_open"] = False
        st.session_state["_next_main_page"] = "Inputs"
        app_run_probe.close_fragment_run(st.session_state)
        st.rerun()
    if apply:
        # Only Apply advances physical provenance. Preview edits retained for the
        # next builder opening must not redefine the point tables when Back is used.
        _qs_mirror_settings()
        _discard_clear_recovery()
        # Quick Section can be the first surface opened in a fresh session. Seed
        # the catalogues before its generated M/P assignments exist; otherwise the
        # orphan-ID reservation guard quite correctly avoids M1/P1 and creates
        # M2/P2, leaving the new points unresolved. Existing catalogues keep their
        # stable IDs, and generated points use the selected (or first) live entry.
        _ensure_material_catalog_state()
        mild_material_id = _quick_section_material_id("mild")
        prestress_material_id = _quick_section_material_id("prestress")
        qs_hole = [(float(p[0]), float(p[1])) for p in holes[0]] if holes else []
        _reseed_table("corners_base", "ed_corners", _corners_df(_pts_to_mm(
            [(float(p[0]), float(p[1])) for p in outer])))
        _reseed_table("hole_base", "ed_hole", _corners_df(_pts_to_mm(qs_hole)))
        _reseed_table("bars_base", "ed_bars", _rebar_df(_pts_to_mm(
            [(float(p[0]), float(p[1]), float(p[2])) for p in bars]),
            "bar", size_mode=rebar_table.DIAMETER_MODE,
            material_id=mild_material_id,
            diameters_mm=bar_diameters))
        _reseed_table("tendons_base", "ed_tendons", _rebar_df(_pts_to_mm(
            [(float(p[0]), float(p[1]), float(p[2])) for p in tendons]),
            "tendon", size_mode=rebar_table.AREA_MODE,
            material_id=prestress_material_id))
        applied_snapshot = _qs_settings_snapshot(st.session_state)
        st.session_state[_QS_APPLIED_SETTINGS_KEY] = applied_snapshot
        st.session_state[_QS_RETAINED_SETTINGS_KEY] = copy.deepcopy(
            applied_snapshot
        )
        st.session_state.pop(_QS_VERIFIED_DENSITY_SETTINGS_KEY, None)
        st.session_state["pts_init"] = True
        st.session_state["_qs_open"] = False
        st.session_state["_next_main_page"] = "Inputs"
        app_run_probe.close_fragment_run(st.session_state)
        st.rerun()
    app_run_probe.close_fragment_run(st.session_state)


def _modular_ratio_readout(box, mild_entries, prestress_entries,
                           mild_materials, prestress_materials, ec_mpa, phi):
    """Report the actual short/long modular ratio of every used material."""
    def cell(value):
        return str(value).replace("|", r"\|").replace("\r", " ").replace("\n", " ")

    # Plain-text cells (no LaTeX): KaTeX does not render reliably inside a markdown
    # table cell, so keep the maths in the intro line and the table simply readable.
    box.markdown(r"**Modular ratios** (derived from $E_c$, $E_s$, $E_p$, $\varphi$)")
    rows = ["| Material | E (GPa) | Short-term n_s | Long-term n_l |",
            "|:--|--:|--:|--:|"]
    for item, materials in ((entry, mild_materials) for entry in mild_entries):
        law = materials.get(item["id"])
        if law is not None:
            ns = law.Es / ec_mpa
            rows.append(
                f"| {cell(item['id'])} - {cell(item['name'])} | "
                f"{law.Es / 1000.0:.1f} | "
                f"{ns:.3f} | {ns * (1.0 + phi):.3f} |"
            )
    for item, materials in ((entry, prestress_materials)
                            for entry in prestress_entries):
        law = materials.get(item["id"])
        if law is not None:
            ns = law.Es / ec_mpa
            rows.append(
                f"| {cell(item['id'])} - {cell(item['name'])} | "
                f"{law.Es / 1000.0:.1f} | "
                f"{ns:.3f} | {ns * (1.0 + phi):.3f} |"
            )
    if len(rows) == 2:
        rows.append("| No assigned steel elements | - | - | - |")
    box.markdown("\n".join(rows))


# Result-staleness signature keys, split so an input change recomputes only the
# affected analysis on the next Calculate. Shared keys affect both analyses
# (materials + mode); the per-analysis buckets hold keys that touch only that one.
# Anything that could affect both stays shared, so a reused result is never stale.
# n_l/n_s are derived from conc_Ec and el_phi, so those enter the elastic signature.
_SHARED_SIG_KEYS = (
    "conc_preset", "conc_fck", "conc_gamma_c", "conc_k_tc", "conc_alpha_cc",
    "conc_eps_c2", "conc_eps_cu2", "conc_n",
    "mild_preset", "mild_fytk", "mild_fyck", "mild_futk", "mild_eut",
    "mild_gamma_y", "mild_gamma_u", "mild_gamma_E", "mild_k",
    "mild_ey0t", "mild_ey0c", "mild_Es", "mild_active_comp",
    "pre_preset", "pre_IS", "pre_fytk", "pre_futk", "pre_eut", "pre_gamma_y",
    "pre_gamma_u", "pre_gamma_E", "pre_k", "pre_ey0t", "pre_Es",
    "mode", "sls_fctm",
)
_PLASTIC_CONTEXT_SIG_KEYS = (
    "v_min", "v_max", "v_inc",
    "pl_check_util", "pl_interaction",
)
_PLASTIC_RESULT_CONTRACT_TOKEN = (
    "plastic-result-contract",
    "m-m-origin-containment-simple-envelope-v2",
)
_ELASTIC_RESULT_CONTRACT_TOKEN = (
    "elastic-result-contract",
    "prestress-only-cracking-v1",
    "dual-crack-criteria-v1",
)
_CAPACITY_RESULT_CONTRACT_TOKEN = (
    "capacity-result-contract",
    "torsion-subdivision-automatic-tef-v1",
    "closed-torsion-link-authority-v1",
)
_FATIGUE_RESULT_CONTRACT_TOKEN = (
    "fatigue-result-contract",
    "simplified-reinforcement-stress-range-screen-v1",
)
_ELASTIC_CONTEXT_SIG_KEYS = (
    "conc_Ec", "el_phi",
    "sls_phi", "sls_bond", "sls_tendon_xi", "sls_code", "sls_member",
    LONG_TERM_PERMITTED_CRACK_WIDTH_KEY,
    SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY,
    HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY,
    "sls_heightened_on", "sls_heightened_reference_case",
    "sls_heightened_reinforcement_surface",
    "sls_heightened_effective_tensile_strength_mpa",
    "sls_heightened_fine_effective_tension_area_mm2",
    "sls_heightened_coarse_effective_tension_area_mm2",
)
# Shear inputs. Folded into the overall signature (not the plastic/elastic split)
# so a shear-only change marks the results stale without forcing the bending
# analyses to recompute; the shear resistance itself is cheap and recomputed on
# every Calculate. Its geometry/fck/axial dependencies already sit in the shared
# and plastic parts of the signature.
_SHEAR_SIG_KEYS = (
    "shear_on", "shear_method", "shear_Vx", "shear_Vy",
    "shear_face_x", "shear_face_y", "shear_vx_bw", "shear_vy_bw",
    "shear_dlower", "shear_gamma_v",
    "shear_links", "shear_vx_link_legs", "shear_vy_link_legs",
    "shear_link_dia", "shear_link_s", "shear_fywk",
    "shear_vx_transverse_leg_spacing", "shear_vy_transverse_leg_spacing",
    "strut_cot_min", "strut_cot_max",
    "torsion_on", "torsion_method", "torsion_T", "torsion_tef", "torsion_nu_v",
    "torsion_gamma_ct",
    "torsion_subdivide", "torsion_nsub",
    "torsion_sub_x0", "torsion_sub_y0", "torsion_sub_x1", "torsion_sub_y1",
    "torsion_sub_x2", "torsion_sub_y2", "torsion_sub_x3", "torsion_sub_y3",
    "torsion_sub_b0", "torsion_sub_h0", "torsion_sub_b1", "torsion_sub_h1",
    "torsion_sub_b2", "torsion_sub_h2", "torsion_sub_b3", "torsion_sub_h3",
    "combined_on", "combined_method", "combined_mv_independent",
)
_CAPACITY_CONTEXT_SIG_KEYS = tuple(
    key for key in _SHEAR_SIG_KEYS
    if key not in {"shear_V", "torsion_T", "shear_gamma_v"}
) + (
    "minimum_reinforcement_on", "clear_spacing_on",
    "transverse_detailing_on", "detailing_edition",
    "detailing_member_type", "detailing_cut_direction",
    "detailing_d_upper", "detailing_include_tendons",
    "transverse_ductility_class", "transverse_apply_ductility_reduction",
)
def build_inputs(host=st):
    """Render one selected outer input stage and return the full payload."""
    s = host
    normalization_token = app_run_probe.start_phase(
        st.session_state, "normalization"
    )
    _ensure_material_catalog_state()
    _ensure_fatigue_catalog_state()
    st.session_state.setdefault("_fatigue_basis_revision", 0)
    fatigue_catalogue = fatigue_inputs.normalise_catalog(
        st.session_state[fatigue_inputs.DETAIL_CATALOG_KEY]
    )
    st.session_state[fatigue_inputs.BASIS_KEY] = fatigue_inputs.normalise_basis(
        st.session_state.get(fatigue_inputs.BASIS_KEY)
    )
    if fatigue_inputs.SPECTRUM_TABLE_KEY not in st.session_state:
        st.session_state[
            fatigue_inputs.SPECTRUM_TABLE_KEY
        ] = fatigue_inputs.empty_spectrum_table()
    mild_catalogue = mat_catalog.normalise_catalog(
        st.session_state[mat_catalog.MILD_CATALOG_KEY], "mild"
    )
    prestress_catalogue = mat_catalog.normalise_catalog(
        st.session_state[mat_catalog.PRESTRESS_CATALOG_KEY], "prestress"
    )
    mild_material_ids = mat_catalog.material_ids(mild_catalogue, "mild")
    unresolved_capacity_material_id = rebar_table.text_cell(
        st.session_state.get("_capacity_steel_unresolved_material_id")
    )
    if (
        unresolved_capacity_material_id
        and unresolved_capacity_material_id not in mild_material_ids
    ):
        mild_material_ids.append(unresolved_capacity_material_id)
    mat_catalog.material_ids(prestress_catalogue, "prestress")
    app_run_probe.stop_phase(st.session_state, normalization_token)

    # Stateful native tabs retain the active stage across reruns. Their bodies
    # remain active-only through InputStage, so hidden stages do not execute.
    # Panels carry calculation methodology (Elastic / Plastic), not a limit
    # state -- the same analysis can serve several load combinations.
    input_tab_labels = list(_input_stage_labels().values())
    aset, sec_tab, mat_tab, loads, project = stateful_input_tabs(
        s,
        input_tab_labels,
        key="_input_tab",
        state=st.session_state,
        on_change=_snapshot_completed_input_state,
        width="stretch",
    )
    # Geometry tables and their drawing remain visible together. The wider input
    # column keeps the four editable point grids practical on a normal laptop.
    sec, sec_preview = sec_tab.columns([1.15, 0.85], gap="large")
    focus = st.session_state.get(_INPUT_ISSUE_FOCUS_KEY, {})
    focus_widget = str(focus.get("widget_key") or "")
    scw = aset.expander(
        "Elastic crack-width method",
        expanded=focus_widget.startswith("sls_"),
    )
    det = aset.expander("Reinforcement detailing", expanded=False)
    fat = aset.expander(
        "Fatigue",
        expanded=focus_widget.startswith("fatigue_"),
    )
    sts = aset.expander(
        "Shear, torsion & combined (Plastic)",
        expanded=focus_widget.startswith(
            ("shear_", "torsion_", "combined_", "capacity_")
        ),
    )
    about_slot = project.container()
    save_slot = project.container()
    mode = aset.radio(
        "Bending analysis",
        ["Plastic", "Elastic", "Both"],
        key="mode",
        **_input_widget_kwargs(
            "mode",
            {
                "help": (
                    "The bending analysis only -- the shear, torsion and crack "
                    "checks are separate toggles below. Plastic: the bending "
                    "capacity (M-M envelope). Elastic: cracked-section concrete "
                    "and bar stresses for the applied loads. Both: run the two."
                ),
            },
        ),
    )
    plastic_on = mode in ("Plastic", "Both")
    elastic_on = mode in ("Elastic", "Both")
    fatigue_on = _seeded_toggle(
        fat,
        "Fatigue analysis",
        False,
        "fatigue_on",
        help="Use the cracked elastic section to assess grouped fatigue spectra.",
    )
    fatigue_standard_options = tuple(
        basis.key.value
        for basis in design_standards.basis_options(
            design_standards.Capability.REINFORCEMENT_FATIGUE
        )
    )
    fatigue_edition = _seeded_selectbox(
        fat,
        "Fatigue design basis",
        fatigue_standard_options,
        design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024.value,
        "fatigue_edition",
        format_func=lambda value: design_standards.get_design_basis(value).label,
        disabled=not fatigue_on,
        help=(
            "Selects the implemented Eurocode fatigue basis and records it with "
            "each result."
        ),
    )
    fatigue_standard_basis = design_standards.get_design_basis(fatigue_edition)
    fatigue_concrete_method_guidance = design_standards.input_guidance(
        fatigue_edition,
        design_standards.InputGuidanceKey.FATIGUE_CONCRETE_METHOD,
    )
    fatigue_action_factor_guidance = design_standards.input_guidance(
        fatigue_edition,
        design_standards.InputGuidanceKey.FATIGUE_ACTION_PARTIAL_FACTOR,
    )
    fatigue_reinforcement_factor_guidance = design_standards.input_guidance(
        fatigue_edition,
        design_standards.InputGuidanceKey.FATIGUE_REINFORCEMENT_MATERIAL_FACTOR,
    )
    fatigue_concrete_factor_guidance = design_standards.input_guidance(
        fatigue_edition,
        design_standards.InputGuidanceKey.FATIGUE_CONCRETE_MATERIAL_FACTOR,
    )
    fatigue_strength_development_guidance = design_standards.input_guidance(
        fatigue_edition,
        design_standards.InputGuidanceKey.FATIGUE_CONCRETE_STRENGTH_DEVELOPMENT,
    )
    fatigue_strength_k1_guidance = design_standards.input_guidance(
        fatigue_edition,
        design_standards.InputGuidanceKey.FATIGUE_CONCRETE_STRENGTH_K1,
    )
    fatigue_life_c_guidance = design_standards.input_guidance(
        fatigue_edition,
        design_standards.InputGuidanceKey.FATIGUE_CONCRETE_LIFE_C,
    )
    fat.caption(fatigue_standard_basis.disclosure)
    fatigue_check_steel = _seeded_toggle(
        fat,
        "Reinforcement",
        True,
        "fatigue_check_steel",
        disabled=not fatigue_on,
        help="Assess fatigue damage and the design yield/proof-stress limit for "
             "assigned bars and tendons.",
    )
    fatigue_check_concrete = _seeded_toggle(
        fat,
        "Concrete",
        True,
        "fatigue_check_concrete",
        disabled=not fatigue_on,
        help="Assess concrete compression fatigue at the searched section fibres.",
    )
    retained_concrete_method = _retained_input_scalar(
        "fatigue_concrete_method",
        _FATIGUE_CONCRETE_MINER,
    )
    if retained_concrete_method not in _FATIGUE_CONCRETE_METHODS:
        retained_concrete_method = _FATIGUE_CONCRETE_MINER
    if retained_concrete_method == _FATIGUE_CONCRETE_PROJECT_MINER:
        fatigue_concrete_method_help = (
            "User-defined Miner uses the entered cycles and coefficient C in "
            "a project-defined concrete S-N relation recorded with the input."
        )
    else:
        fatigue_concrete_method_help = (
            "Explicit Palmgren-Miner uses the entered cycles in every spectrum "
            "bin. Damage-equivalent checks Formula (6.72) or (E.2); each row's "
            "long/total action pair must then already represent a "
            "damage-equivalent amplitude for 10^6 cycles, and its Cycles value "
            "is ignored for concrete. "
            f"{fatigue_concrete_method_guidance.tooltip}"
        )
    fatigue_concrete_method = _seeded_selectbox(
        fat,
        "Concrete fatigue method",
        list(_FATIGUE_CONCRETE_METHODS),
        _FATIGUE_CONCRETE_MINER,
        "fatigue_concrete_method",
        disabled=not (fatigue_on and fatigue_check_concrete),
        help=fatigue_concrete_method_help,
    )
    fat.caption(
        "Enter final effective partial factors, including applicable control, "
        "construction and consequence-category effects."
    )
    ff1, ff2, ff3 = fat.columns(3)
    fatigue_gamma_ff = _seeded_number(
        ff1,
        r"$\gamma_{Ff}$",
        0.1,
        10.0,
        1.0,
        0.05,
        "fatigue_gamma_ff",
        disabled=not fatigue_on,
        help=(
            "Partial factor on each cyclic action increment before the Elastic "
            f"fatigue solve. {fatigue_action_factor_guidance.tooltip}"
        ),
    )
    fatigue_gamma_s = _seeded_number(
        ff2,
        r"$\gamma_s$",
        0.1,
        10.0,
        1.15,
        0.05,
        "fatigue_gamma_s",
        disabled=not (fatigue_on and fatigue_check_steel),
        help=(
            r"Final material factor reducing $\Delta\sigma_{Rsk}$ and the "
            "reinforcement yield or proof-stress limit. "
            f"{fatigue_reinforcement_factor_guidance.tooltip}"
        ),
    )
    fatigue_gamma_c = _seeded_number(
        ff3,
        r"$\gamma_{c,\mathrm{fat}}$",
        0.1,
        10.0,
        1.50,
        0.05,
        "fatigue_gamma_c",
        disabled=not (fatigue_on and fatigue_check_concrete),
        help=(
            r"Final material factor in the design concrete fatigue strength "
            rf"$f_{{cd,\mathrm{{fat}}}}$. "
            f"{fatigue_concrete_factor_guidance.tooltip}"
        ),
    )
    fc1, fc2 = fat.columns(2)
    fatigue_beta_cc_t0 = _seeded_number(
        fc1,
        r"$\beta_{cc}(t_0)$",
        0.01,
        2.0,
        1.0,
        0.05,
        "fatigue_beta_cc_t0",
        disabled=not (fatigue_on and fatigue_check_concrete),
        help=(
            r"Concrete strength-development factor at the first cyclic loading "
            r"age $t_0$; enter the value from the selected basis. "
            f"{fatigue_strength_development_guidance.tooltip}"
        ),
    )
    fatigue_t0_days = _seeded_number(
        fc2,
        r"Concrete age $t_0$ (days)",
        0.01,
        100000.0,
        28.0,
        1.0,
        "fatigue_t0_days",
        disabled=not (fatigue_on and fatigue_check_concrete),
        help=r"Documents the age at first cyclic loading used with "
             r"$\beta_{cc}(t_0)$; enter the factor separately.",
    )
    fatigue_concrete_k1 = _seeded_number(
        fc1,
        r"Concrete fatigue $k_1$",
        0.01,
        5.0,
        0.85,
        0.05,
        "fatigue_concrete_k1",
        disabled=(
            not (fatigue_on and fatigue_check_concrete)
            or fatigue_standard_basis.family
            is design_standards.StandardFamily.PUBLISHED_2023
        ),
        help=(
            r"Coefficient in the 2005 design strength $f_{cd,\mathrm{fat}}$; "
            "not used by the 2023 expression. "
            f"{fatigue_strength_k1_guidance.tooltip}"
        ),
    )
    if fatigue_concrete_method == _FATIGUE_CONCRETE_PROJECT_MINER:
        fatigue_concrete_c_help = (
            r"Coefficient in the project-defined $\log_{10}N_R$ concrete "
            "fatigue-life relation. Record the selected value and source with "
            "the project inputs."
        )
    else:
        fatigue_concrete_c_help = (
            r"Coefficient in the implemented $\log_{10}N_R$ concrete "
            "fatigue-life relation. "
            f"{fatigue_life_c_guidance.tooltip}"
        )
    fatigue_concrete_c = _seeded_number(
        fc2,
        r"Concrete fatigue $C$",
        0.1,
        100.0,
        14.0,
        0.5,
        "fatigue_concrete_c",
        disabled=(
            not (fatigue_on and fatigue_check_concrete)
            or fatigue_concrete_method == _FATIGUE_CONCRETE_EQUIVALENT
        ),
        help=fatigue_concrete_c_help,
    )
    fat.markdown("**Spectrum basis**")
    fatigue_basis = _fatigue_basis_panel(fat, disabled=not fatigue_on)

    # Load tables are rendered before the crack controls so their per-case
    # choices can enable the numerical crack-width settings in the same rerun.
    case_frames = _load_case_editors(loads)
    if fatigue_on:
        loads.markdown("**Grouped fatigue spectra**")
        loads.caption(
            "Each bin combines sustained/basic actions with the cyclic increment. "
            "Sector solves both states and uses their stress range."
        )
        fatigue_spectrum = _fatigue_spectrum_editor(loads)
    else:
        fatigue_spectrum = fatigue_inputs.active_spectrum_table(
            st.session_state.get(fatigue_inputs.SPECTRUM_TABLE_KEY)
        )
    case_head = load_cases.head_inputs(case_frames)
    pl_case_id = case_head["pl_case_id"]
    pl_case_type = case_head["pl_case_type"]
    pl_case_source = ""
    el_case_id = case_head["el_case_id"]
    el_case_type = case_head["el_case_type"]
    el_case_source = ""
    P_pl = case_head["pl_P"]
    Mx_pl = case_head["pl_Mx"]
    My_pl = case_head["pl_My"]
    torsion_T = case_head["torsion_T"]
    P_el_l = case_head["el_long_P"]
    Mx_el_l = case_head["el_long_Mx"]
    My_el_l = case_head["el_long_My"]
    P_el_s = case_head["el_short_P"]
    Mx_el_s = case_head["el_short_Mx"]
    My_el_s = case_head["el_short_My"]
    sls_cw = bool(
        not case_frames[load_cases.ELASTIC_TABLE_KEY].empty
        and case_frames[load_cases.ELASTIC_TABLE_KEY][
            "calculate_crack_width"
        ].any()
    )
    loads.markdown("**Global Elastic parameter**")
    creep_concrete_preset = st.session_state.get("conc_preset", _DEFAULT_PRESET)
    phi_creep = _seeded_number(
        loads, r"Creep coefficient $\varphi$", 0.0, 5.0, 3.0, 0.1,
        "el_phi", disabled=not (elastic_on or fatigue_on),
        help=_creep_coefficient_help(creep_concrete_preset),
    )
    aset.markdown("**Neutral-axis sweep (plastic)**")
    v_min = _seeded_number(
        aset, r"Start angle $\varphi_{NA,\min}$ ($^\circ$)",
        0.0, 360.0, 0.0, 5.0,
        "v_min", disabled=not plastic_on,
        help="First neutral-axis rotation angle of the plastic sweep.",
    )
    v_max = _seeded_number(
        aset, r"End angle $\varphi_{NA,\max}$ ($^\circ$)",
        0.0, 360.0, 360.0, 5.0,
        "v_max", disabled=not plastic_on,
        help="Last neutral-axis rotation angle of the plastic sweep.",
    )
    v_inc = _seeded_number(
        aset, r"Maximum increment $\Delta\varphi_{NA}$ ($^\circ$)",
        1.0, 90.0, 15.0, 1.0,
        "v_inc", disabled=not plastic_on,
        help="Equal spacing includes both sweep limits, so the actual angular "
             "increment may be smaller. A smaller maximum increment gives a "
             "smoother M-M envelope.",
    )
    check_util = _seeded_checkbox(
        aset, "Check utilisation against applied moment", True, "pl_check_util",
        disabled=not plastic_on,
        help="On: the applied plastic Mx/My are checked against the capacity envelope "
             "(utilisation). Off: report the capacity only -- the applied Mx/My are "
             "ignored and locked.")
    interaction = _seeded_checkbox(
        aset, "N-M interaction diagrams", False, "pl_interaction",
        disabled=not plastic_on,
        help="Trace the axial-moment (N-M) capacity curves about both bending axes "
             "(N-Mx and N-My), from pure tension to the squash load. Shown in the "
             "N-M Interaction view. Adds a short extra sweep to Calculate.")

    scw.caption(
        "Every Elastic action reports concrete and reinforcement stresses. Enable "
        "crack width per action and set independent duration limits; zero reports "
        "the width without comparison."
    )
    cw_long, cw_short = scw.columns(2)
    sls_long_term_permitted_crack_width_mm = _seeded_number(
        cw_long,
        r"Long-term limit $w_{k,long}$ (mm; 0 = no comparison)",
        0.0,
        10.0,
        0.0,
        0.01,
        LONG_TERM_PERMITTED_CRACK_WIDTH_KEY,
        disabled=not elastic_on,
        help=(
            "Applies only to the long-term calculation (sustained action, "
            "kt = 0.4). Zero reports the width without comparison. Use the limit "
            "and action classification required by the project basis."
        ),
    )
    sls_short_term_permitted_crack_width_mm = _seeded_number(
        cw_short,
        r"Short-term limit $w_{k,short}$ (mm; 0 = no comparison)",
        0.0,
        10.0,
        0.0,
        0.01,
        SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY,
        disabled=not elastic_on,
        help=(
            "Applies only to the short-term calculation (instantaneous total "
            "action, kt = 0.6). Zero reports the width without comparison. Use "
            "the limit and action classification required by the project basis."
        ),
    )
    crack_basis_options = tuple(
        basis.key.value
        for basis in design_standards.basis_options(
            design_standards.Capability.ORDINARY_CRACK_WIDTH
        )
    )
    sls_code = _seeded_selectbox(
        scw,
        "Crack-width design basis",
        crack_basis_options,
        design_standards.DesignBasisKey.FIRST_GEN_BASE.value,
        "sls_code",
        format_func=lambda value: design_standards.get_design_basis(value).label,
        disabled=not elastic_on,
        help=(
            "Selects the implemented ordinary crack-width basis and records it "
            "with each result."
        ),
    )
    sls_basis = design_standards.get_design_basis(sls_code)
    ordinary_binding = design_standards.capability_binding(
        sls_code,
        design_standards.Capability.ORDINARY_CRACK_WIDTH,
    )
    ordinary_route = ordinary_binding.ordinary_crack_width_route
    if ordinary_route is None:
        raise ValueError("The selected basis has no ordinary crack-width route")
    ordinary_diameter_guidance = design_standards.input_guidance(
        sls_code,
        design_standards.InputGuidanceKey.ORDINARY_CRACK_DIAMETER,
    )
    ordinary_bond_guidance = design_standards.input_guidance(
        sls_code,
        design_standards.InputGuidanceKey.ORDINARY_CRACK_MILD_BOND,
    )
    scw.caption(sls_basis.disclosure)
    sls_phi = _seeded_number(
        scw, r"Crack-width element diameter $\phi$ (mm, 0 = auto)",
        0.0, 60.0, 0.0, 1.0, "sls_phi",
        disabled=not (elastic_on and sls_cw),
        help="Diameter override for crack spacing, applied to each reinforcement "
             "element; 0 uses each bar or tendon's table diameter (which may itself "
             "be area-derived). "
             f"{ordinary_diameter_guidance.tooltip}")
    # k1 (EC2 7.11 bond coefficient) depends on the bar surface, which the geometry
    # cannot tell, so it is a user choice: 0.8 ribbed / high-bond, 1.6 plain round.
    sls_bond = scw.selectbox(
        r"Mild-steel bond ($k_1$)",
        list(_BOND_K1),
        key="sls_bond",
        **_input_widget_kwargs(
            "sls_bond",
            {
                "disabled": not (elastic_on and sls_cw),
                "help": (
                    "Bond coefficient k1 for the crack calculation, applied to "
                    "the mild reinforcement: 0.8 for ribbed / high-bond bars "
                    "(e.g. Tentor), 1.6 for plain round bars. Prestressing "
                    "tendons always use k1 = 1.6. "
                    f"{ordinary_bond_guidance.tooltip}"
                ),
            },
        ),
    )
    sls_k1 = _BOND_K1[sls_bond]
    if sls_basis.key is design_standards.DesignBasisKey.PUBLISHED_2023:
        tendon_bond_help = design_standards.input_guidance(
            sls_code,
            design_standards.InputGuidanceKey.ORDINARY_CRACK_TENDON_BOND,
        ).tooltip
    else:
        tendon_bond_help = (
            "This input is not used by the selected first-generation ordinary "
            "crack-width method. Its value is saved for use if the calculation "
            "basis is changed to 2023."
        )
    sls_tendon_xi = _seeded_number(
        scw,
        r"Bonded-tendon ratio $\xi$ (0 = unset)",
        0.0,
        10.0,
        0.0,
        0.05,
        "sls_tendon_xi",
        disabled=not (elastic_on and sls_cw),
        help=(
            "2023 mixed mild/prestressing crack calculation: tendon-to-ribbed-"
            "reinforcement bond-strength ratio. Enter the selected method input; "
            f"zero leaves it unspecified. {tendon_bond_help}"
        ),
    )
    sls_dk_na = ordinary_route.report_coarse_system
    sls_edition = ordinary_route.edition
    if sls_basis.key is design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024:
        sls_member_help = design_standards.input_guidance(
            sls_code,
            design_standards.InputGuidanceKey.ORDINARY_CRACK_MEMBER_TYPE,
        ).tooltip
    else:
        sls_member_help = (
            "This input is not used by the selected ordinary crack-width method; "
            "its value is saved for use if the Danish first-generation basis is "
            "selected."
        )
    sls_member = _seeded_selectbox(
        scw,
        "Member type",
        ["Beam", "Slab"],
        "Beam",
        "sls_member",
        disabled=not (elastic_on and sls_cw and sls_dk_na),
        help=(
            "DK NA fine-system selection for the (h-x)/3 effective-height "
            f"term. Ignored by other methods. {sls_member_help}"
        ),
    )

    heightened_basis = (
        sls_basis.key
        is design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024
    )
    if heightened_basis:
        heightened_guidance = design_standards.input_guidance(
            sls_code,
            design_standards.InputGuidanceKey.HEIGHTENED_CRACK_OPERANDS,
        )
        scw.markdown("**Optional DK NA heightened crack control**")
        scw.caption(
            "Formula 7.100 NA is a separate section-level calculation. Fine and "
            "coarse systems use one selected ordinary crack-width reference case; "
            "confirm its project applicability."
        )
        sls_heightened_on = _seeded_toggle(
            scw,
            "Calculate heightened crack control",
            False,
            "sls_heightened_on",
            disabled=not elastic_on,
            help=(
                "Opt in to the separate section-level heightened calculation. "
                f"{heightened_guidance.tooltip}"
            ),
        )
        sls_heightened_permitted_crack_width_mm = _seeded_number(
            scw,
            r"Heightened permitted width $w_{k,Formula\ 7.100}$ (mm)",
            0.0,
            10.0,
            0.0,
            0.01,
            HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY,
            disabled=not (elastic_on and sls_heightened_on),
            help=(
                "Dedicated Formula 7.100 NA operand, independent of both ordinary "
                "duration limits. Enter a positive value and confirm the "
                "heightened calculation applies."
            ),
        )
        crack_reference_names = list(
            heightened_adapter.crack_enabled_case_names(
                case_frames[load_cases.ELASTIC_TABLE_KEY].to_dict("records")
            )
        )
        if len(crack_reference_names) == 1:
            sls_heightened_reference_case = crack_reference_names[0]
            st.session_state["sls_heightened_reference_case"] = (
                sls_heightened_reference_case
            )
            if (
                st.session_state.get(_HEIGHTENED_EXPLICIT_REFERENCE_KEY)
                != sls_heightened_reference_case
            ):
                st.session_state[_HEIGHTENED_AUTO_REFERENCE_KEY] = (
                    sls_heightened_reference_case
                )
            scw.caption(
                "Reference Elastic case: "
                f"{sls_heightened_reference_case} (the sole crack-enabled case)."
            )
        elif len(crack_reference_names) > 1:
            auto_reference = st.session_state.get(
                _HEIGHTENED_AUTO_REFERENCE_KEY
            )
            if (
                auto_reference
                and st.session_state.get("sls_heightened_reference_case")
                == auto_reference
            ):
                st.session_state["sls_heightened_reference_case"] = ""
                durable = dict(st.session_state.get(_INPUT_STATE_KEY, {}))
                durable["sls_heightened_reference_case"] = ""
                st.session_state[_INPUT_STATE_KEY] = durable
            st.session_state.pop(_HEIGHTENED_AUTO_REFERENCE_KEY, None)
            sls_heightened_reference_case = _seeded_selectbox(
                scw,
                "Reference crack-enabled Elastic case",
                ["", *crack_reference_names],
                "",
                "sls_heightened_reference_case",
                format_func=lambda value: value or "Select a reference case",
                disabled=not (elastic_on and sls_heightened_on),
                on_change=_mark_heightened_reference_explicit,
                help=(
                    "Select the ordinary crack result whose contributing mild bars "
                    "provide the diameter, modulus and area."
                ),
            )
            if sls_heightened_reference_case:
                st.session_state[_HEIGHTENED_EXPLICIT_REFERENCE_KEY] = (
                    sls_heightened_reference_case
                )
        else:
            sls_heightened_reference_case = _retained_input_scalar(
                "sls_heightened_reference_case", ""
            )
            if sls_heightened_on:
                scw.error(
                    "Enable ordinary crack width for at least one Elastic case "
                    "before calculating heightened crack control."
                )
        sls_heightened_reinforcement_surface = _seeded_selectbox(
            scw,
            "Reinforcement surface",
            ["ribbed", "smooth"],
            "ribbed",
            "sls_heightened_reinforcement_surface",
            format_func=lambda value: (
                "Ribbed / high bond" if value == "ribbed" else "Smooth"
            ),
            disabled=not (elastic_on and sls_heightened_on),
            help=(
                "Select the reinforcement surface used by the formula. "
                f"{heightened_guidance.tooltip}"
            ),
        )
        hc1, hc2 = scw.columns(2)
        sls_heightened_effective_tensile_strength_mpa = _seeded_number(
            hc1,
            r"Effective tensile strength $f_{ct,eff}$ (MPa)",
            0.0,
            100.0,
            0.0,
            0.1,
            "sls_heightened_effective_tensile_strength_mpa",
            disabled=not (elastic_on and sls_heightened_on),
            help=(
                "Dedicated user-specified operand; it is not inferred from the "
                "concrete grade or ordinary fctm input. "
                f"{heightened_guidance.tooltip}"
            ),
        )
        sls_heightened_fine_effective_tension_area_mm2 = _seeded_number(
            hc2,
            r"Fine-system effective tension area $A_{c,eff,fine}$ (mm2)",
            0.0,
            1.0e12,
            0.0,
            100.0,
            "sls_heightened_fine_effective_tension_area_mm2",
            disabled=not (elastic_on and sls_heightened_on),
            help=(
                "User-supplied effective concrete tension area for the fine system. "
                f"{heightened_guidance.tooltip}"
            ),
        )
        sls_heightened_coarse_effective_tension_area_mm2 = _seeded_number(
            hc1,
            r"Coarse-system effective tension area $A_{c,eff,coarse}$ (mm2)",
            0.0,
            1.0e12,
            0.0,
            100.0,
            "sls_heightened_coarse_effective_tension_area_mm2",
            disabled=not (elastic_on and sls_heightened_on),
            help=(
                "User-supplied effective concrete tension area for the coarse "
                f"system. {heightened_guidance.tooltip}"
            ),
        )
        scw.caption(
            "After calculation, bar diameter follows the ordinary override or "
            "largest contributing mild bar; reinforcement modulus is the minimum "
            "among contributing mild materials; provided area is their total area."
        )
    else:
        # Do not mount unsupported controls. Retain any prior DK operands so a
        # basis switch does not erase user input. An enabled incompatible state is
        # rejected by the shared calculation/report validation below.
        sls_heightened_on = _retained_input_scalar("sls_heightened_on", False)
        sls_heightened_permitted_crack_width_mm = _retained_input_scalar(
            HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY, 0.0
        )
        sls_heightened_reference_case = _retained_input_scalar(
            "sls_heightened_reference_case", ""
        )
        sls_heightened_reinforcement_surface = _retained_input_scalar(
            "sls_heightened_reinforcement_surface", "ribbed"
        )
        sls_heightened_effective_tensile_strength_mpa = _retained_input_scalar(
            "sls_heightened_effective_tensile_strength_mpa", 0.0
        )
        sls_heightened_fine_effective_tension_area_mm2 = _retained_input_scalar(
            "sls_heightened_fine_effective_tension_area_mm2", 0.0
        )
        sls_heightened_coarse_effective_tension_area_mm2 = _retained_input_scalar(
            "sls_heightened_coarse_effective_tension_area_mm2", 0.0
        )
        if sls_heightened_on:
            scw.error(
                "Stored heightened crack control is enabled, but the selected "
                "design basis does not implement it. Select the DK NA:2024 basis "
                "to review or disable the calculation."
            )

    detailing_member_type = _seeded_selectbox(
        det,
        "Member type",
        list(detailing.MEMBER_TYPES),
        detailing.MEMBER_BEAM,
        "detailing_member_type",
        help="Selects member-specific detailing clauses; section analysis and "
             "material factors remain unchanged.",
    )
    if detailing_member_type == detailing.MEMBER_SLAB:
        detailing_cut_direction = _seeded_selectbox(
            det,
            "Section cut direction",
            list(detailing.CUT_DIRECTIONS),
            detailing.CUT_TRANSVERSE,
            "detailing_cut_direction",
            format_func=lambda value: (
                "Transverse cut - longitudinal reinforcement modelled"
                if value == detailing.CUT_TRANSVERSE
                else "Longitudinal cut - transverse reinforcement modelled"
            ),
            help="The model contains only reinforcement normal to the section "
                 "plane. Detailing checks are limited to that acting direction.",
        )
    else:
        detailing_cut_direction = detailing.CUT_TRANSVERSE
        st.session_state["detailing_cut_direction"] = detailing_cut_direction

    modelled_direction_alias = _seeded_text(
        det,
        "Project direction alias (optional)",
        "",
        modelled_direction.ALIAS_KEY,
        max_chars=modelled_direction.MAX_ALIAS_CHARS,
        help=(
            "Optional project wording shown after the standard longitudinal or "
            "transverse direction; presentation only."
        ),
    )
    direction_label = modelled_direction.resolved_markdown_label(
        cut_direction=detailing_cut_direction,
        alias=modelled_direction_alias,
    )
    det.info(f"Modelled reinforcement direction: {direction_label}")

    detailing_help_edition = st.session_state.get(
        "detailing_edition", detailing.EC2_2005_DKNA
    )
    if (
        type(detailing_help_edition) is not str
        or detailing_help_edition not in detailing.EDITIONS
    ):
        detailing_help_edition = detailing.EC2_2005_DKNA
    minimum_reinforcement_help = _selected_basis_input_help(
        detailing_help_edition,
        design_standards.InputGuidanceKey.DETAILING_MINIMUM_REINFORCEMENT,
    )
    transverse_detailing_help = _selected_basis_input_help(
        detailing_help_edition,
        design_standards.InputGuidanceKey.DETAILING_TRANSVERSE_LINKS,
    )
    clear_spacing_help = _selected_basis_input_help(
        detailing_help_edition,
        design_standards.InputGuidanceKey.DETAILING_CLEAR_SPACING,
    )

    minimum_reinforcement_on = _seeded_checkbox(
        det,
        "Check minimum reinforcement in modelled direction",
        False,
        "minimum_reinforcement_on",
        help=minimum_reinforcement_help,
    )
    transverse_detailing_on = _seeded_checkbox(
        det,
        "Check shear/torsion link detailing",
        False,
        "transverse_detailing_on",
        help=transverse_detailing_help,
    )
    clear_spacing_on = _seeded_checkbox(
        det,
        "Check reinforcement clear spacing",
        False,
        "clear_spacing_on",
        help=clear_spacing_help,
    )
    detailing_edition = _seeded_selectbox(
        det,
        "Detailing edition",
        list(detailing.EDITIONS),
        detailing.EC2_2005_DKNA,
        "detailing_edition",
        disabled=not (
            minimum_reinforcement_on
            or transverse_detailing_on
            or clear_spacing_on
        ),
        help="Selects the edition-specific flexural-bar and link "
             "reinforcement and spacing clauses. EC2:2023 is a valid selectable "
             "method.",
    )
    transverse_ductility_class = _seeded_selectbox(
        det,
        "Link reinforcement ductility class",
        ["A", "B", "C"],
        "B",
        "transverse_ductility_class",
        help="Physical ductility class of the link reinforcement. DS/EN 1992-1-1:2023 "
             "uses it for the compression-field angle range and, when explicitly "
             "selected below, the favourable minimum-ratio reduction.",
    )
    transverse_apply_ductility_reduction = _seeded_checkbox(
        det,
        "Apply 2023 ductility-class reduction to minimum ratio",
        False,
        "transverse_apply_ductility_reduction",
        disabled=not (
            transverse_detailing_on
            and detailing_edition == detailing.EC2_2023
        ),
        help="Favourable optional provision in DS/EN 1992-1-1:2023 12.2(4): "
             "reduce the minimum ratio by 10 % for class B or 20 % for class C. "
             "Off keeps the unreduced value.",
    )
    detailing_d_upper = _seeded_number(
        det,
        r"Maximum aggregate size $D_{\mathrm{upper}}$ (mm)",
        0.0,
        100.0,
        16.0,
        1.0,
        "detailing_d_upper",
        disabled=not clear_spacing_on,
        help=r"Upper aggregate size used in "
             r"$\max(\phi,D_{\mathrm{upper}}+5\ \mathrm{mm},20\ \mathrm{mm})$.",
    )
    detailing_include_tendons = _seeded_checkbox(
        det,
        "Include tendons in spacing check",
        False,
        "detailing_include_tendons",
        disabled=not clear_spacing_on,
        help="Use a tendon's entered diameter as its detailing envelope. For a "
             "ducted tendon, enter the duct/envelope diameter before enabling.",
    )
    selected_minimum_cases = (
        int(case_frames[load_cases.PLASTIC_TABLE_KEY][
            "check_minimum_reinforcement"
        ].sum())
        if not case_frames[load_cases.PLASTIC_TABLE_KEY].empty
        else 0
    )
    if minimum_reinforcement_on:
        det.caption(
            f"Selected Plastic/capacity cases: {selected_minimum_cases}. "
            "The case must represent the design situation required by the clause. "
            f"Modelled bars: {direction_label}."
        )
    if transverse_detailing_on:
        det.caption(
            "Link-detailing checks use the shared closed-stirrup definition and run "
            "only for non-zero shear/torsion actions."
        )
    det.caption(
        "Lap and bundle verification is outside this section-plane spacing check."
    )

    shear_codes_by_label = _shear_codes()
    shear_methods_by_label = _shear_methods()

    sts.markdown(r"**Combined $M$-$V$-$T$ interaction**")
    sts.caption(r"Tie the bending (plastic $M$), shear ($V$) and torsion ($T$) checks "
                 "together under one consistent code edition (6.3.2). Enable Plastic "
                 "(or Both), the shear check and the torsion check as well.")
    combined_on = _seeded_checkbox(
        sts, r"Check combined $M$-$V$-$T$", False, "combined_on",
        help=r"Tie the $M$, $V$ and $T$ checks together (crushing 6.29 and the DK NA sum rule); "
             "locks their method to the shared edition below. See the manual.")
    combined_method = _seeded_selectbox(
        sts, "Combined edition (shared)", list(shear_codes_by_label),
        codes.EC2_2005_DKNA.label, key="combined_method", disabled=not combined_on,
        help="The single code edition used for the shear and torsion checks while "
             "Combined is on (their own method selectors are locked to this).")
    combined_mv_independent = _seeded_checkbox(
        sts, r"Apply separate $M$/$V$ route as a design assumption", False,
        "combined_mv_independent", disabled=not combined_on,
        help="DK NA 6.3.2(6): select after verifying the capacity, distribution "
             "and anchorage of the longitudinal reinforcement added for shear "
             "beyond bending. Sector then calculates "
             r"$N+M+T$ and $N+V+T$. A value within the numerical limit is "
             "CONDITIONAL; a value above the limit is FAIL even under the "
             "favourable assumption.")
    # Filled at the end of this block (once the shear/torsion toggles below are
    # known) with any missing combined-check prerequisites -- so the user sees them
    # here, right under the toggle, instead of only after Calculate.
    combined_warn = sts.container()

    sts.markdown("**Shear capacity**")
    sts.caption(r"Directional resistance for $V_{x,Ed}$ and $V_{y,Ed}$. Loads and optional "
                "tension-face overrides are entered per Plastic/capacity case.")
    shear_on = _seeded_checkbox(
        sts, "Check shear capacity", False, "shear_on",
        help=r"Compute directional $V_{Rd,c}$ and utilisation. Enable links below when "
             "shear reinforcement is present.")
    shear_method = _seeded_selectbox(
        sts, "Shear method", list(shear_methods_by_label),
        codes.EC2_2005_DKNA.label,
        key="shear_method", disabled=(not shear_on) or combined_on,
        help=r"Code edition for the shear rules: the 2005 family ($V_{Rd,c}$, 6.2.2(1)) "
             r"or DS/EN 1992-1-1:2023 (8.2.2 without links; 8.2.3 with links). See the "
             "manual for the difference.")
    _eff_shear_method = combined_method if combined_on else shear_method
    _shear_2023 = (
        shear_methods_by_label.get(_eff_shear_method) is not None
        and getattr(
            shear_methods_by_label[_eff_shear_method], "shear_model", "2005"
        ) == "2023"
    )
    shear_dlower = _seeded_number(
        sts, r"Aggregate size $D_{\mathrm{lower}}$ (mm)", 4.0, 40.0, 16.0, 1.0, "shear_dlower",
        disabled=not (shear_on and _shear_2023),
        help=r"Lower sieve size of the coarsest aggregate (2023 method only): "
             r"$d_{dg}=16+D_{\mathrm{lower}}\leq40$ mm for $f_{ck}\leq60$ MPa (8.2.1(4)).")
    shear_gamma_v_active = bool(
        shear_on
        and _shear_2023
        and st.session_state.get("shear_links") is not True
    )
    shear_gamma_v = _seeded_number(
        sts,
        r"Shear partial factor $\gamma_V$",
        None,
        None,
        float(codes.EC2_2023.shear_gamma_v),
        0.05,
        "shear_gamma_v",
        disabled=not shear_gamma_v_active,
        help=(
            "DS/EN 1992-1-1:2023, 4.3.3 and Table 4.3 (NDP) define "
            "the partial factor for shear resistance without shear "
            "reinforcement. 1.40 is the initial value; the selected positive "
            "value is applied in 8.2.2. Confirm the project basis."
        ),
    )
    effective_shear_gamma_v = (
        shear_gamma_v
        if shear_gamma_v_active
        else float(codes.EC2_2023.shear_gamma_v)
    )
    if combined_on:
        sts.caption(f"Shear method set by Combined: {combined_method}")
    bwx, bwy = sts.columns(2)
    shear_vx_bw = _seeded_number(
        bwx, r"$b_{w,x}$ (mm, 0 = auto)", 0.0, 100000.0, 0.0, 10.0,
        "shear_vx_bw", disabled=not shear_on,
        help=r"Web width for $V_{x,Ed}$ (depth along x; left/right faces).",
    )
    shear_vy_bw = _seeded_number(
        bwy, r"$b_{w,y}$ (mm, 0 = auto)", 0.0, 100000.0, 0.0, 10.0,
        "shear_vy_bw", disabled=not shear_on,
        help=r"Web width for $V_{y,Ed}$ (depth along y; bottom/top faces).",
    )
    sts.markdown(r"**Torsion ($T_{Rd}$, thin-walled tube)**")
    sts.caption(
        "EN 1992-1-1 section 6.3 thin-walled-tube calculation. Current closed "
        "links establish the transverse/strut resistance component. Overall "
        "torsion also requires Formula (6.28) longitudinal steel, perimeter "
        "distribution and member anchorage."
    )
    torsion_on = _seeded_checkbox(
        sts, "Check torsion capacity", False, "torsion_on",
        help=r"With current closed links, calculates the $T_{Rd,s}$ / "
             r"$T_{Rd,max}$ resistance component, utilisation and the combined "
             "shear-torsion crushing check. The overall status also considers "
             "longitudinal reinforcement. Without links, only concrete resistance "
             "and reinforcement demand are reported.")
    torsion_method = _seeded_selectbox(
        sts, "Torsion method", list(shear_codes_by_label),
        codes.EC2_2005_DKNA.label,
        key="torsion_method", disabled=(not torsion_on) or combined_on,
        help="Code edition for the torsion rules. The DK NA:2024 uses its plasticity "
             r"pure-torsion strut factor $\nu_t=0.7(0.7-f_{ck}/200)$ (5.104 NA) in "
             r"place of the recommended $\nu=0.6(1-f_{ck}/250)$.")
    if combined_on:
        sts.caption(f"Torsion method set by Combined: {combined_method}")
    effective_torsion_method = combined_method if combined_on else torsion_method
    torsion_gamma_ct_boolean_state = isinstance(
        st.session_state.get("torsion_gamma_ct"), (bool, np.bool_)
    )
    if torsion_gamma_ct_boolean_state:
        # Streamlit number_input normalises injected Boolean scalars to 0.0/1.0.
        # Clear the malformed state before method-default reseeding and widget
        # construction so neither can turn it into a valid-looking coefficient.
        st.session_state["torsion_gamma_ct"] = None
        _mark_torsion_gamma_ct_custom()
    torsion_gamma_default = _seed_torsion_gamma_ct(effective_torsion_method)
    sts.caption(r"The applied torsion $T_{Ed}$ is entered in the Loads panel.")
    _tors = torsion_on
    sts.caption(
        "The selected closed stirrup supplies one leg to torsion; longitudinal "
        "demand uses the selected reinforcing material. Only the enabled shared-"
        "link selection establishes link presence."
    )
    torsion_tef = _seeded_number(
        sts, r"Wall thickness $t_{ef}$ (mm, 0 = auto)", 0.0, 5000.0, 0.0, 5.0,
        "torsion_tef", disabled=not _tors,
        help="Zero derives A/u, capped at the nearest real wall for a single-cell "
             "hollow section. A positive single-tube override cannot exceed that "
             "wall; subdivided tubes require zero and derive each thickness.")
    torsion_gamma_ct = _seeded_number(
        sts,
        r"Concrete tensile factor $\gamma_{ct}$",
        None,
        None,
        torsion_gamma_default,
        0.05,
        "torsion_gamma_ct",
        disabled=not _tors,
        format="%.3f",
        on_change=_mark_torsion_gamma_ct_custom,
        help=(
            r"Direct positive-finite input used in "
            r"$f_{ctd}=f_{ctk,0.05}/\gamma_{ct}$ and $T_{Rd,c}$. "
            f"The selected method starts at {torsion_gamma_default:.2f}; "
            "a custom value is used as entered."
        ),
    )
    torsion_gamma_ct_error = None
    try:
        torsion_gamma_ct_number = float(torsion_gamma_ct)
    except (TypeError, ValueError):
        torsion_gamma_ct_number = None
    if (
        torsion_gamma_ct_boolean_state
        or isinstance(torsion_gamma_ct, (bool, np.bool_))
        or torsion_gamma_ct_number is None
        or not math.isfinite(torsion_gamma_ct_number)
        or torsion_gamma_ct_number <= 0.0
    ):
        torsion_gamma_ct_error = _TORSION_GAMMA_CT_INPUT
        sts.error(engineer_messages.error_detail(
            torsion_gamma_ct_error,
            fallback=_TORSION_GAMMA_CT_INPUT,
            context="torsion concrete tensile factor",
        ))
    elif not math.isclose(
        torsion_gamma_ct_number,
        torsion_gamma_default,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        sts.caption(
            f"Custom gamma_ct = {torsion_gamma_ct_number:g}; the selected "
            f"method default is {torsion_gamma_default:g}. The custom value is "
            "used unchanged."
        )
    torsion_nu_v = _seeded_checkbox(
        sts, r"$\nu_t = \nu_v$ (closed stirrups + distributed long. steel)", False,
        "torsion_nu_v",
        disabled=not (
            _tors and st.session_state.get("shear_links") is True
        ),
        help="DK NA Figure 5.100 NA: for closed peripheral stirrups and uniformly "
             "distributed longitudinal steel on both wall faces, use the pure-"
             "shear nu_v. This is a selected detailing condition, not verification "
             "of the modelled bars or member anchorage. Requires current shared "
             "links and the DK NA edition.")
    torsion_subdivide = _seeded_checkbox(
        sts, "Subdivide into sub-tubes (T / compound section)", False,
        "torsion_subdivide", disabled=not _tors,
        help="EN 1992-1-1 6.3.1(3): define positioned component rectangles for a "
             "T, L, I or flanged section. Rectangle 1 is the web paired with shear; "
             "the partition is validated before resistance is calculated.")
    torsion_subrects = []
    if torsion_subdivide and _tors:
        n_sub = int(_seeded_number(
            sts, "Number of sub-rectangles", 2.0, 4.0, 2.0, 1.0, "torsion_nsub",
            help="Component rectangles: a T = web + flange (2), a double console = web "
                 "+ 2 consoles (3). The first is the web."))
        defaults = (
            (0.0, -100.0, 300.0, 600.0),
            (0.0, 300.0, 1200.0, 200.0),
            (0.0, 0.0, 300.0, 600.0),
            (0.0, 0.0, 300.0, 600.0),
        )
        for i in range(n_sub):
            role = "web" if i == 0 else f"part {i + 1}"
            x_default, y_default, b_default, h_default = defaults[i]
            cx_col, cy_col, cb, ch = sts.columns(4)
            x_i = _seeded_number(
                cx_col, fr"$x_{{{i + 1}}}$ (mm)", -100000.0, 100000.0, x_default, 10.0,
                f"torsion_sub_x{i}", disabled=not _tors,
                help=f"Global x-coordinate of the centre of {role}.")
            y_i = _seeded_number(
                cy_col, fr"$y_{{{i + 1}}}$ (mm)", -100000.0, 100000.0, y_default, 10.0,
                f"torsion_sub_y{i}", disabled=not _tors,
                help=f"Global y-coordinate of the centre of {role}.")
            b_i = _seeded_number(
                cb, fr"$b_{{{i + 1}}}$ (mm) - {role}", 1.0, 100000.0, b_default, 10.0,
                f"torsion_sub_b{i}", disabled=not _tors,
                help=f"Global x-direction width of {role}.")
            h_i = _seeded_number(
                ch, fr"$h_{{{i + 1}}}$ (mm) - {role}", 1.0, 100000.0, h_default, 10.0,
                f"torsion_sub_h{i}", disabled=not _tors,
                help=f"Global y-direction height of {role}.")
            torsion_subrects.append((x_i, y_i, b_i, h_i))
        sts.caption(
            "Define a complete, non-overlapping partition of the concrete net "
            "area. Rectangle 1 is the web used with shear in the combined checks "
            "(6.3.1(3))."
        )
    # One current authority and one stored geometry serve both physical roles. Shear
    # uses the selected number of vertical legs; torsion uses one leg of the same
    # closed, anchored loop. Stored positive geometry never implies presence.
    sts.markdown("**Compression strut and shared links (shear + torsion)**")
    shear_links = _seeded_checkbox(
        sts,
        "Shared links / closed torsion stirrups present",
        False,
        "shear_links",
        disabled=not (shear_on or torsion_on),
        help=(
            "Selects the current physical stirrup. Shear uses the entered effective "
            "legs; torsion requires the same bar as a closed, anchored loop and "
            "uses one leg in Asw/s."
        ),
    )
    _links = bool(shear_on and shear_links)
    _torsion_links = bool(torsion_on and shear_links)
    _shared_links = bool(_links or _torsion_links)
    _strut_model = bool(_links or torsion_on)
    if torsion_nu_v and not _torsion_links:
        sts.caption(
            "The nu_t = nu_v detailing option is inactive while current shared "
            "links / closed torsion stirrups are absent."
        )
    sts.caption(
        "The compression-strut band also supports torsion concrete resistance. "
        "Stirrup geometry applies only with shared links enabled: shear uses n "
        "legs and torsion one closed-loop leg."
    )
    strut_lo, strut_hi = sts.columns(2)
    strut_cot_min = _seeded_number(
        strut_lo,
        r"Compression strut $\cot\theta_{\min}$",
        0.5,
        5.0,
        1.0,
        0.1,
        "strut_cot_min",
        disabled=not _strut_model,
        help=r"Lower bound for the compression-strut angle shared by shear and "
             r"torsion. The 2005 family permits $1\leq\cot\theta\leq2.5$; "
             "values outside the selected method's range are warned, not blocked.",
    )
    strut_cot_max = _seeded_number(
        strut_hi,
        r"Compression strut $\cot\theta_{\max}$",
        0.5,
        5.0,
        2.5,
        0.1,
        "strut_cot_max",
        disabled=not _strut_model,
        help=r"Upper bound for the same physical compression strut. Sector selects "
             "one angle within this range for all live shear, torsion, concrete, "
             "stirrup and longitudinal-reinforcement checks.",
    )
    if _strut_model:
        active_strut_codes = []
        if _links:
            active_strut_codes.append(shear_methods_by_label[_eff_shear_method])
        if _tors:
            active_strut_codes.append(
                shear_codes_by_label[
                    combined_method if combined_on else torsion_method
                ]
            )
        code_cot_min = max(
            code.shear_cot_min_limit for code in active_strut_codes
        )
        code_cot_max = min(
            code.shear_cot_max_limit for code in active_strut_codes
        )
        if _shear_2023 and transverse_ductility_class == "A":
            code_cot_max = min(code_cot_max, 2.0)
        if (
            strut_cot_min < code_cot_min - 1e-9
            or strut_cot_max > code_cot_max + 1e-9
        ):
            sts.caption(
                "Warning: the shared strut bounds fall outside the selected "
                "method's default range "
                f"{code_cot_min:g}..{code_cot_max:g}. The values are allowed, but "
                "the entered values are used in every calculation."
            )
    if "_capacity_steel_pending_material_id" in st.session_state:
        st.session_state["capacity_steel_material_id"] = st.session_state.pop(
            "_capacity_steel_pending_material_id"
        )
    capacity_steel_material_id = _seeded_selectbox(
        sts, "Reference reinforcing material", mild_material_ids,
        mild_material_ids[0], "capacity_steel_material_id",
        disabled=not (shear_on or torsion_on),
        format_func=lambda value: next(
            (mat_catalog.entry_label(item) for item in mild_catalogue["items"]
             if item["id"] == value),
            f"{value} - undefined (select a material)",
        ),
        help=r"Material law supplying $\gamma_s$ and the longitudinal design yield "
             "for shear/torsion member checks. Element-level bending and stress "
             "calculations use each bar's assigned material.",
    )
    legs_x, legs_y = sts.columns(2)
    shear_vx_link_legs = _seeded_number(
        legs_x, r"Effective legs for $V_x$", 1.0, 20.0, 2.0, 1.0,
        "shear_vx_link_legs", disabled=not _links,
        help=r"Number of stirrup legs crossing the $V_x$ shear plane.",
    )
    shear_vy_link_legs = _seeded_number(
        legs_y, r"Effective legs for $V_y$", 1.0, 20.0, 2.0, 1.0,
        "shear_vy_link_legs", disabled=not _links,
        help=r"Number of stirrup legs crossing the $V_y$ shear plane.",
    )
    spacing_x, spacing_y = sts.columns(2)
    shear_vx_transverse_leg_spacing = _seeded_number(
        spacing_x,
        r"Max. $V_x$-leg spacing along $y$ (mm; 0 = screen)",
        0.0,
        100000.0,
        0.0,
        10.0,
        "shear_vx_transverse_leg_spacing",
        disabled=not (_links and transverse_detailing_on),
        help=r"Largest centre-to-centre distance $s_{t,x}$ along $y$ between link "
             r"legs parallel to $V_x$. Zero uses gross web breadth as an upper-"
             "bound screen; enter actual spacing if the screen exceeds the limit.",
    )
    shear_vy_transverse_leg_spacing = _seeded_number(
        spacing_y,
        r"Max. $V_y$-leg spacing along $x$ (mm; 0 = screen)",
        0.0,
        100000.0,
        0.0,
        10.0,
        "shear_vy_transverse_leg_spacing",
        disabled=not (_links and transverse_detailing_on),
        help=r"Largest centre-to-centre distance $s_{t,y}$ along $x$ between link "
             r"legs parallel to $V_y$. Zero uses gross web breadth as an upper-"
             "bound screen; enter actual spacing if the screen exceeds the limit.",
    )
    sts.caption(
        r"$s_t$ is the in-section distance between parallel link legs: along $y$ "
        r"for $V_x$ and along $x$ for $V_y$. Longitudinal stirrup spacing is $s$."
    )
    shear_link_dia = _seeded_number(
        sts, "Stirrup diameter (mm)", 4.0, 40.0, 10.0, 1.0, "shear_link_dia",
        disabled=not _shared_links,
        help=r"Stirrup bar diameter $\phi$; one leg has area $\pi\phi^2/4$.")
    shear_link_s = _seeded_number(
        sts, r"Stirrup spacing $s$ (mm)", 10.0, 2000.0, 150.0, 10.0, "shear_link_s",
        disabled=not _shared_links, help="Longitudinal spacing of the stirrups.")
    shear_fywk = _seeded_number(
        sts, r"Stirrup yield $f_{ywk}$ (MPa)", 100.0, 900.0, 500.0, 10.0, "shear_fywk",
        disabled=not _shared_links,
        help="Characteristic stirrup yield; the design value is divided by the "
             r"selected material's final effective $\gamma_s$. Enter an appropriately "
             r"reduced $f_{ywk}$ where full anchorage is unavailable.")
    if transverse_detailing_on and not _shared_links:
        _manual_warning(
            sts,
            "calculation-warning",
            "Link detailing is selected, but no links are defined for the active "
            "shear/torsion actions.",
        )

    # Pre-flight for the combined check (it needs several things at once): flag what
    # is missing in the reserved slot right under its toggle, not only after Calculate.
    if combined_on:
        ok_mark, no_mark = chr(0x2713), chr(0x2717)   # check / cross (BMP, ASCII src)
        reqs = [
            (mode in ("Plastic", "Both"), "Plastic / Both bending analysis"),
            (check_util, "Check utilisation against applied moment"),
            (shear_on, "Shear check enabled"),
            (torsion_on, "Torsion check enabled"),
            (shear_links, "Shared links / closed torsion stirrups present"),
        ]
        lines = "  \n".join(f"{ok_mark if met else no_mark} {name}"
                            for met, name in reqs)
        if all(met for met, _ in reqs):
            combined_warn.success("Combined M-V-T requirements met:  \n" + lines)
        else:
            _manual_warning(
                combined_warn,
                "calculation-warning",
                "Combined M-V-T needs all of these (it is not evaluated until "
                "then):  \n" + lines,
            )

    # (Section / Material / Loads tabs were created at the top; fill them now.)
    sec.caption("The section is a set of explicit points (the source of truth). "
                "Use the Quick Section builder to generate a parametric shape and "
                "write its points here, or edit the point tables directly.")
    if "pts_init" not in st.session_state:
        # Seed the tables once from the default Quick Section (metres -> mm).
        d_outer, d_holes, d_bars, d_tendons = _default_quick_section()
        d_hole = [(float(p[0]), float(p[1])) for p in d_holes[0]] if d_holes else []
        _reseed_table("corners_base", "ed_corners", _corners_df(_pts_to_mm(
            [(float(p[0]), float(p[1])) for p in d_outer])))
        _reseed_table("hole_base", "ed_hole", _corners_df(_pts_to_mm(d_hole)))
        _reseed_table("bars_base", "ed_bars", _rebar_df(_pts_to_mm(
            [(float(p[0]), float(p[1]), float(p[2])) for p in d_bars]),
            "bar", size_mode=rebar_table.DIAMETER_MODE))
        _reseed_table("tendons_base", "ed_tendons", _rebar_df(_pts_to_mm(
            [(float(p[0]), float(p[1]), float(p[2])) for p in d_tendons]),
            "tendon", size_mode=rebar_table.AREA_MODE))
        st.session_state[_QS_APPLIED_SETTINGS_KEY] = {}
        st.session_state["pts_init"] = True
    # Migrate a session that predates the void table (or the ID-column tables): seed
    # hole_base, and coerce any stored table to the current data-only schema.
    if "hole_base" not in st.session_state:
        old = st.session_state.get("holes_pts") or []
        st.session_state["hole_base"] = _corners_df(old[0] if old else [])
    for base_key, cols, ed_key in (
            ("corners_base", _CORNER_COLS, "ed_corners"),
            ("hole_base", _CORNER_COLS, "ed_hole"),
            ("bars_base", _REBAR_COLS, "ed_bars"),
            ("tendons_base", _REBAR_COLS, "ed_tendons")):
        df = st.session_state.get(base_key)
        if df is None:
            # A loaded or partial project may omit a table (e.g. a non-prestressed
            # project has no tendon table); seed it empty so the always-mounted
            # grid has a base to read.
            kind = _reinforcement_kind(base_key)
            st.session_state[base_key] = (_corners_df([]) if not kind
                                          else rebar_table.empty_table())
            continue
        kind = _reinforcement_kind(base_key)
        if kind:
            canonical = rebar_table.normalise_table(df, kind)
            if list(df.columns) != _REBAR_COLS or not canonical.equals(df):
                _reseed_table(base_key, ed_key, canonical)
            continue
        if list(df.columns) != cols:
            if set(cols).issubset(df.columns):
                _reseed_table(base_key, ed_key, df.reindex(columns=cols))
            else:
                _reseed_table(base_key, ed_key, _corners_df([]))

    if sec.button(
        "Open Quick Section...", key="open_qs", width="stretch",
        help="Open a full-width builder: pick a shape, dimensions and "
             "reinforcement with a live preview, then Apply to fill the "
             "point tables.",
    ):
        _open_analysis_content("quick_section")

    if sec.button("Clear section...", key="clear_pts", width="stretch",
                  disabled=_section_tables_are_empty(),
                  help="Request removal of all concrete, void, bar and tendon "
                       "points. A separate confirmation is required."):
        st.session_state["_clear_section_confirm"] = True

    if sec.open and st.session_state.get("_clear_section_confirm"):
        confirm_slot = sec.empty()
        with confirm_slot.container():
            _manual_warning(
                st,
                "confirmation-required",
                "Clear all section point tables?",
            )
            confirm_col, cancel_col = st.columns(2)
            confirm_clear = confirm_col.button(
                "Confirm clear", key="confirm_clear_pts", type="primary",
                width="stretch",
            )
            cancel_clear = cancel_col.button(
                "Cancel", key="cancel_clear_pts", width="stretch",
            )
        if confirm_clear:
            st.session_state["_clear_section_undo"] = {
                "tables": _section_table_snapshot(),
                "applied_quick_section_present": (
                    _QS_APPLIED_SETTINGS_KEY in st.session_state
                ),
                "applied_quick_section": copy.deepcopy(
                    st.session_state.get(_QS_APPLIED_SETTINGS_KEY)
                ),
            }
            _clear_section_tables()
            # An empty section is explicit source-of-truth geometry. Strip every
            # former builder value from save/autosave until Undo or Apply restores
            # a layout that those values actually describe.
            st.session_state[_QS_APPLIED_SETTINGS_KEY] = {}
            st.session_state.pop("_clear_section_confirm", None)
            confirm_slot.empty()
        elif cancel_clear:
            st.session_state.pop("_clear_section_confirm", None)
            confirm_slot.empty()

    undo_snapshot = st.session_state.get("_clear_section_undo")
    if undo_snapshot is not None and not _section_tables_are_empty():
        # A new point-table edit supersedes the one-step recovery. This prevents
        # Undo from overwriting geometry entered after the clear.
        st.session_state.pop("_clear_section_undo", None)
        undo_snapshot = None
    if undo_snapshot is not None:
        undo_slot = sec.empty()
        if undo_slot.button("Undo clear", key="undo_clear_pts", width="stretch",
                            help="Restore the four point tables removed by the "
                                 "last clear."):
            _reseed_section_tables(undo_snapshot["tables"])
            if undo_snapshot["applied_quick_section_present"]:
                st.session_state[_QS_APPLIED_SETTINGS_KEY] = copy.deepcopy(
                    undo_snapshot["applied_quick_section"]
                )
            else:
                st.session_state.pop(_QS_APPLIED_SETTINGS_KEY, None)
            st.session_state.pop("_clear_section_undo", None)
            undo_slot.empty()

    sec.markdown("**Cross-section points** (the analysis uses these)")
    provenance_notice = st.session_state.pop(_QS_PROVENANCE_NOTICE_KEY, None)
    if provenance_notice:
        sec.success(provenance_notice)
    sec.caption("Concrete corners define the outline; voids are optional inner "
                "rings. Reinforcement IDs remain fixed. Choose Area, Diameter or "
                "Independent; derived cells are shaded. Paste x/y/area or all "
                "editable columns.")
    sec.markdown("_Concrete corners_")
    _table_field_guide(sec, table_fields.CONCRETE_CORNERS_TABLE_KEY)
    outer_mm = _point_editor(sec, "corners_base", "ed_corners", _CORNER_COLS, 1)
    outer = _pts_to_m(outer_mm)
    if len(outer) < 3:
        # No valid outline. Leave it empty (do NOT fall back to the Quick Section,
        # or Clear Section would silently revert to the template) and let the
        # downstream treat the section as blank.
        _manual_warning(
            sec,
            "geometry-invalid",
            "The section has no concrete outline. Add at least 3 corners, or "
            "open the Quick Section builder.",
        )
    sec.markdown("_Concrete voids_")
    sec.caption("Several voids share this table, each separated by a blank row "
                "(each void needs 3 or more corners).")
    _table_field_guide(sec, table_fields.CONCRETE_VOIDS_TABLE_KEY)
    # The buttons act on the grid's current rows (its last reported value) so typing
    # a void and then adding/removing one does not discard the in-progress corners.
    void_now = _current_table("hole_base", "ed_hole", _CORNER_COLS)
    n_voids = len(_void_groups(void_now, _CORNER_COLS))
    vc1, vc2 = sec.columns(2)
    if vc1.button("+ Add void", key="add_void", width="stretch",
                  disabled=n_voids >= _MAX_VOIDS,
                  help=f"Append a blank separator row, so the next corners you enter "
                       f"start a new void (up to {_MAX_VOIDS})."):
        groups = _void_groups(void_now, _CORNER_COLS)
        _reseed_table("hole_base", "ed_hole",
                      _void_table_from_groups(groups, trailing_blank=True))
    if vc2.button("Remove void", key="rem_void", width="stretch",
                  disabled=n_voids == 0, help="Drop the last void from the table."):
        groups = _void_groups(void_now, _CORNER_COLS)
        _reseed_table("hole_base", "ed_hole", _void_table_from_groups(groups[:-1]))
        _prune_applied_quick_section_settings("hole_base")
    holes_mm = _void_editor(sec, "hole_base", "ed_hole", len(outer) + 1)
    holes = [_pts_to_m(ring) for ring in holes_mm]
    sec.markdown("_Reinforcing bars_")
    _table_field_guide(sec, table_fields.BARS_TABLE_KEY)
    _bar_frame, bar_elements, bars_mm, bar_row_issues = _reinforcement_editor(
        sec, "bars_base", "ed_bars",
    )
    bars = _pts_to_m(bars_mm)
    bar_elements = [
        {**item, "x": item["x_mm"] / _MM, "y": item["y_mm"] / _MM}
        for item in bar_elements
    ]
    # Tendons are always definable; they only enter the analysis and the report when
    # at least one is present (a section with no tendons is simply not prestressed).
    sec.markdown("_Tendons_")
    _table_field_guide(sec, table_fields.TENDONS_TABLE_KEY)
    _tendon_frame, tendon_elements, tendons_mm, tendon_row_issues = (
        _reinforcement_editor(
            sec, "tendons_base", "ed_tendons",
        )
    )
    tendons = _pts_to_m(tendons_mm)
    tendon_elements = [
        {**item, "x": item["x_mm"] / _MM, "y": item["y_mm"] / _MM}
        for item in tendon_elements
    ]
    slab_density = _slab_density_reconciliation(
        st.session_state,
        outer,
        holes,
        _bar_frame,
    )
    if (
        slab_density is not None
        and slab_density.get("status") == "UNVERIFIED"
    ):
        (sec.warning if (sls_cw or clear_spacing_on) else sec.info)(
            slab_density["reason"]
        )
        if slab_density.get("can_use_explicit_bars"):
            sec.button(
                "Use current bars as explicit layout",
                key="slab_density_use_explicit",
                on_click=_use_current_bars_as_explicit,
                help=(
                    "Choose this only after replacing the generated slab-density "
                    "analysis rows with the physical bars to be checked."
                ),
            )

    def assigned_material_ids(frame):
        # Include incomplete rows too. Their geometry is not solver-ready yet, but
        # their material assignment is still user input and must prevent deletion.
        if rebar_table.MATERIAL_ID not in frame:
            return []
        return [
            str(value).strip()
            for value in frame[rebar_table.MATERIAL_ID].tolist()
            if str(value).strip()
        ]

    def assigned_fatigue_ids(frame):
        if rebar_table.FATIGUE_DETAIL_ID not in frame:
            return []
        return [
            str(value).strip()
            for value in frame[rebar_table.FATIGUE_DETAIL_ID].tolist()
            if str(value).strip()
        ]

    assigned_mild_ids = assigned_material_ids(_bar_frame)
    assigned_prestress_ids = assigned_material_ids(_tendon_frame)
    assigned_bar_fatigue_ids = assigned_fatigue_ids(_bar_frame)
    assigned_tendon_fatigue_ids = assigned_fatigue_ids(_tendon_frame)
    invalid_bar_materials = mat_catalog.invalid_assignments(
        [item["material_id"] for item in bar_elements], mild_catalogue, "mild"
    )
    invalid_tendon_materials = mat_catalog.invalid_assignments(
        [item["material_id"] for item in tendon_elements],
        prestress_catalogue, "prestress",
    )
    invalid_capacity_materials = (
        mat_catalog.invalid_assignments(
            [capacity_steel_material_id], mild_catalogue, "mild"
        )
        if (shear_on or torsion_on)
        else []
    )
    material_assignment_error = None
    material_assignment_errors = []
    if (
        invalid_bar_materials
        or invalid_tendon_materials
        or invalid_capacity_materials
    ):
        if invalid_bar_materials:
            material_assignment_errors.append(_BAR_MATERIAL_ASSIGNMENT)
        if invalid_tendon_materials:
            material_assignment_errors.append(_TENDON_MATERIAL_ASSIGNMENT)
        if invalid_capacity_materials:
            material_assignment_errors.append(_MEMBER_MATERIAL_ASSIGNMENT)
        material_assignment_error = _MATERIAL_INPUT_BLOCKER
        for assignment_error in material_assignment_errors:
            sec.error(engineer_messages.error_detail(
                assignment_error,
                fallback=_MATERIAL_INPUT_BLOCKER,
                context="material assignment",
            ))
    fatigue_assignment_error = None
    if fatigue_on and fatigue_check_steel:
        invalid_bar_details = fatigue_inputs.invalid_assignments(
            [item["fatigue_detail_id"] for item in bar_elements],
            fatigue_catalogue,
            fatigue_inputs.MILD,
        )
        invalid_tendon_details = fatigue_inputs.invalid_assignments(
            [item["fatigue_detail_id"] for item in tendon_elements],
            fatigue_catalogue,
            fatigue_inputs.PRESTRESS,
        )
        if invalid_bar_details or invalid_tendon_details:
            parts = []
            if invalid_bar_details:
                parts.append("bar detail " + ", ".join(invalid_bar_details))
            if invalid_tendon_details:
                parts.append(
                    "tendon detail " + ", ".join(invalid_tendon_details)
                )
            fatigue_assignment_error = _FATIGUE_ASSIGNMENT_MESSAGE
            assignment_text = engineer_messages.error_detail(
                fatigue_assignment_error,
                fallback=_FATIGUE_DISPLAY_ERROR,
                context="fatigue assignment",
            )
            _manual_warning(
                sec,
                "input-invalid",
                assignment_text
                + " Other requested analyses can still be calculated; fatigue "
                "will be reported as INVALID until every assignment is resolved.",
            )
    label_scale, label_min_gap = _section_input_preview(
        sec_preview,
        outer,
        holes,
        bars,
        tendons,
        bar_elements,
        tendon_elements,
        visible=bool(sec_tab.open),
    )

    # In a purely elastic-bending calculation the design stress-strain laws do not
    # enter the result, so lock their inactive parameters. Independent shear,
    # torsion and combined capacity checks do use characteristic/design strengths
    # and the user's final partial factors even when bending is Elastic-only; keep
    # the material laws editable whenever one of those checks is active.
    capacity_checks_on = (
        shear_on or torsion_on or combined_on or minimum_reinforcement_on
        or fatigue_on
    )
    lock_mats = mode == "Elastic" and not capacity_checks_on
    # fctm also enters both generations of the minimum-reinforcement check.
    lock_elastic = (
        mode == "Plastic"
        and not minimum_reinforcement_on
        and not fatigue_on
    )
    if lock_mats:
        mat_tab.caption(
            "Elastic-only mode locks the stress-strain laws. "
            r"$f_{ck}$ remains editable for $f_{ctm}$, and steel modulus Es for "
            "crack width. Select Plastic or Both to edit the full laws."
        )
    elif mode == "Elastic" and capacity_checks_on:
        mat_tab.caption(
            "An independent capacity or fatigue check is active, so its material "
            "properties remain editable."
        )

    # Reserve the derived-value action above the peer tabs, but mount the tab
    # selector before evaluating the button. A button-triggered early rerun must
    # not make the nested tab widget disappear and revive its first-tab default.
    auto_all_slot = mat_tab.empty()

    material_tab_labels = ["Concrete", "Mild steel", "Prestressing steel"]
    if fatigue_on:
        material_tab_labels.append("Fatigue details")
    selected_material_tab = normalise_stage_selection(
        st.session_state, "_material_tab", material_tab_labels
    )
    material_tab_preference = st.session_state.get("_material_tab_preference")
    if material_tab_preference not in material_tab_labels:
        st.session_state["_material_tab_preference"] = selected_material_tab
    else:
        # A rerun triggered by a sibling control can remount nested tabs with
        # their first browser-side default. The tab callback records genuine tab
        # clicks first, so the retained preference is authoritative here.
        st.session_state["_material_tab"] = material_tab_preference
    material_tabs = stateful_input_tabs(
        mat_tab,
        material_tab_labels,
        key="_material_tab",
        state=st.session_state,
        on_change=_snapshot_material_tab_state,
        width="stretch",
    )
    if any(tab.open for tab in material_tabs):
        st.session_state["_material_tab_preference"] = st.session_state[
            "_material_tab"
        ]
    if auto_all_slot.button(
        "Auto-calc all derived values",
        key="auto_all_btn",
        width="stretch",
        help="Recompute all auto values from the current grade: the concrete "
             "strain limits eps_c2/eps_cu2/n, fctm and Ec. The modular ratios "
             "n_l/n_s follow from Ec, Es, Ep and creep automatically.",
    ):
        st.session_state["_auto_all"] = True
        st.rerun()
    conc_tab, mild_tab, pre_tab = material_tabs[:3]
    fatigue_tab = material_tabs[3] if fatigue_on else None
    conc_inputs, conc_preview = conc_tab.columns([1.1, 0.9], gap="large")
    mild_inputs, mild_preview = mild_tab.columns([1.1, 0.9], gap="large")
    pre_inputs, pre_preview = pre_tab.columns([1.1, 0.9], gap="large")

    (concrete, sls_fctm, conc_Ec, concrete_preset,
     concrete_k_tc, concrete_eta_cc) = concrete_panel(
         conc_inputs, locked=lock_mats, lock_elastic=lock_elastic, heading=False
     )
    _material_input_preview(
        conc_preview,
        "concrete",
        concrete,
        lambda material: viz.concrete_curve_figure(material),
        visible=bool(mat_tab.open and conc_tab.open),
    )
    mild_catalogue, selected_mild_id, selected_steel = _material_catalog_panel(
        mild_inputs, "mild",
        assigned_mild_ids,
        protected_ids=([capacity_steel_material_id]
                       if shear_on or torsion_on else []),
        locked=lock_mats,
    )
    _material_input_preview(
        mild_preview,
        f"steel_{selected_mild_id}",
        selected_steel,
        lambda material, **kwargs: viz.steel_curve_figure(material, **kwargs),
        title=mat_catalog.entry_label(
            mat_catalog.entry_map(mild_catalogue, "mild")[selected_mild_id]
        ),
        visible=bool(mat_tab.open and mild_tab.open),
    )
    # The reinforcement laws are always definable; whether each is used follows from
    # the section (mild steel when bars exist, prestress when tendons exist).
    (prestress_catalogue, selected_prestress_id,
     selected_prestress) = _material_catalog_panel(
        pre_inputs, "prestress",
        assigned_prestress_ids,
        locked=lock_mats,
    )
    _material_input_preview(
        pre_preview,
        f"prestress_{selected_prestress_id}",
        selected_prestress,
        lambda material, **kwargs: viz.prestress_curve_figure(
            material, **kwargs
        ),
        title=mat_catalog.entry_label(
            mat_catalog.entry_map(
                prestress_catalogue, "prestress"
            )[selected_prestress_id]
        ),
        visible=bool(mat_tab.open and pre_tab.open),
    )
    if fatigue_tab is not None:
        fatigue_catalogue = _fatigue_detail_catalog_panel(
            fatigue_tab,
            assigned_bar_fatigue_ids + assigned_tendon_fatigue_ids,
            fatigue_edition,
        )
        for error in fatigue_inputs.catalog_errors(fatigue_catalogue):
            fatigue_tab.error(engineer_messages.error_detail(
                error,
                fallback=_FATIGUE_DISPLAY_ERROR,
                context="fatigue detail catalogue",
            ))

    material_definition_errors = []

    def _material_map(catalogue, kind):
        out = {}
        for item in catalogue["items"]:
            try:
                out[item["id"]] = mat_catalog.build_material(item, kind)
            except Exception as exc:
                detail = engineer_messages.resolve(
                    exc,
                    fallback=_material_definition_message(item, kind),
                    context="material definition",
                )
                family = (
                    "Mild steel" if kind == "mild"
                    else "Prestressing steel"
                )
                material_definition_errors.append(input_issues.InputIssue(
                    "material-definition",
                    detail,
                    input_issues.InputTarget(
                        input_issues.MATERIAL_PARAMETERS,
                        widget_label=f"{family} values",
                        material_family=family,
                        material_id=str(item["id"]),
                    ),
                ))
        return out

    mild_material_map = _material_map(mild_catalogue, "mild")
    prestress_material_map = _material_map(prestress_catalogue, "prestress")
    reference_steel = mild_material_map.get(capacity_steel_material_id)
    bar_materials = [
        mild_material_map.get(item["material_id"])
        for item in bar_elements
    ]
    tendon_materials = [
        prestress_material_map.get(item["material_id"])
        for item in tendon_elements
    ]
    prestress = tendon_materials[0] if tendon_materials else selected_prestress
    material_error = material_assignment_error
    if torsion_gamma_ct_error:
        material_error = _MATERIAL_INPUT_BLOCKER
    if material_definition_errors:
        for definition_error in material_definition_errors:
            mat_tab.error(engineer_messages.error_detail(
                definition_error.message,
                fallback=_MATERIAL_DEFINITION_DISPLAY,
                context="material definition display",
            ))
        material_error = _MATERIAL_INPUT_BLOCKER

    mild_entries_by_id = mat_catalog.entry_map(mild_catalogue, "mild")
    prestress_entries_by_id = mat_catalog.entry_map(
        prestress_catalogue, "prestress"
    )
    used_mild_ids = list(dict.fromkeys(
        [item["material_id"] for item in bar_elements]
        + ([capacity_steel_material_id] if (shear_on or torsion_on) else [])
    ))
    used_prestress_ids = list(dict.fromkeys(
        item["material_id"] for item in tendon_elements
    ))
    used_mild_entries = [mild_entries_by_id[value] for value in used_mild_ids
                         if value in mild_entries_by_id]
    used_prestress_entries = [prestress_entries_by_id[value]
                              for value in used_prestress_ids
                              if value in prestress_entries_by_id]
    mild_preset = (used_mild_entries[0]["preset"] if used_mild_entries
                   else mild_catalogue["items"][0]["preset"])
    prestress_preset = (used_prestress_entries[0]["preset"]
                        if used_prestress_entries
                        else prestress_catalogue["items"][0]["preset"])

    # The elastic solver uses a fixed 200 GPa reference ratio and one multiplier per
    # element. Their product is each assigned material's actual E/Ec ratio.
    ec_mpa = max(conc_Ec, 1e-6) * 1000.0
    ns = STEEL_REFERENCE_MODULUS / ec_mpa
    nl = STEEL_REFERENCE_MODULUS * (1.0 + phi_creep) / ec_mpa
    loads.markdown("**Derived modular ratios**")
    _modular_ratio_readout(
        loads, used_mild_entries, used_prestress_entries,
        mild_material_map, prestress_material_map, ec_mpa, phi_creep,
    )

    geometry_error = None
    section = None
    if len(outer) >= 3:
        try:
            section = section_core.Section.from_polygon(
                corners=outer,
                bars_xy_area_mm2=bars,
                tendons_xy_area_mm2=tendons,
                holes=holes,
            )
        except geometry.GeometryTopologyError as exc:
            issue = next(iter(exc.validation.issues), None)
            authored = _SECTION_TOPOLOGY_MESSAGES.get(
                getattr(issue, "code", None)
            )
            geometry_error = engineer_messages.resolve(
                authored if authored is not None else exc,
                fallback=_SECTION_GEOMETRY_DISPLAY,
                context="section geometry construction",
            )
    # A void must not split the concrete into disconnected pieces (e.g. a slot
    # reaching across the section): such a section has no valid capacity.
    void_error = None
    if section is not None and holes and not geometry.concrete_is_connected(outer, holes):
        void_error = _SECTION_DISCONNECTED
    # Every reinforcing bar and tendon must sit in the concrete: outside the outline
    # or inside a void it carries no force, so the section is ill-defined. Checked
    # only once the outline itself is valid (a void error is the more basic fault).
    steel_error = (
        _REINFORCEMENT_ROW_INPUT
        if bar_row_issues or tendon_row_issues
        else None
    )
    if section is not None and not void_error and steel_error is None:
        steel_pts = list(bars) + list(tendons)
        if steel_pts:
            ok = geometry.points_inside_concrete(steel_pts, outer, holes)
            nb = len(bars)
            bad_bars = [bar_elements[i]["id"] for i in range(nb) if not ok[i]]
            bad_tendons = [tendon_elements[i - nb]["id"]
                           for i in range(nb, len(steel_pts)) if not ok[i]]
            parts = []
            if bad_bars:
                parts.append(f"bar(s) {', '.join(map(str, bad_bars))}")
            if bad_tendons:
                parts.append(f"tendon(s) {', '.join(map(str, bad_tendons))}")
            if parts:
                steel_error = _REINFORCEMENT_OUTSIDE
    if outer:
        xs = [p[0] for p in outer]
        ys = [p[1] for p in outer]
        extent = 0.75 * max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    else:
        extent = 1.0
    # The geometry signature is the point tables themselves (the source of truth),
    # so editing a point marks the results stale; Quick Section inputs do not, as
    # they only prefill on demand.
    def _element_signature(elements):
        keys = ("id", "x_mm", "y_mm", "area_mm2", "diameter_mm", "size_mode",
                "material_id", "fatigue_detail_id")
        return tuple(tuple(item.get(key) for key in keys) for item in elements)

    def _slab_density_signature(density):
        if density is None:
            return ("slab-density", "not-applicable")
        status = density.get("status")
        if status != "VERIFIED":
            return ("slab-density", status)
        metadata_keys = (
            "face", "role", "layer", "cover_mm", "nominal_spacing_mm"
        )
        element_keys = (
            "id", "kind", "x_mm", "y_mm", "area_mm2", "diameter_mm"
        )
        return (
            "slab-density",
            status,
            tuple(
                tuple(item.get(key) for key in metadata_keys)
                for item in density.get("analysis_metadata", ())
            ),
            tuple(
                tuple(item.get(key) for key in element_keys)
                for item in density.get("physical_elements", ())
            ),
        )

    geom_sig = (tuple(outer), tuple(bars), tuple(tendons),
                 tuple(tuple(r) for r in holes),
                 _element_signature(bar_elements),
                 _element_signature(tendon_elements),
                 tuple(bar_row_issues), tuple(tendon_row_issues),
                 _slab_density_signature(slab_density))
    # Table actions live in their canonical frames, while the shared calculation
    # context excludes row values. Exact row signatures then let the case engine
    # reuse unchanged rows when another row is edited.
    _get = lambda keys: tuple(st.session_state.get(k) for k in keys)
    material_sig = (
        mat_catalog.signature(mild_catalogue, "mild"),
        mat_catalog.signature(prestress_catalogue, "prestress"),
        capacity_steel_material_id,
    )
    shared_sig = geom_sig + material_sig + _get(_SHARED_SIG_KEYS)
    plastic_bending_context_sig = (
        shared_sig
        + _get(_PLASTIC_CONTEXT_SIG_KEYS)
        + (_PLASTIC_RESULT_CONTRACT_TOKEN,)
    )
    elastic_case_context_sig = (
        shared_sig
        + _get(_ELASTIC_CONTEXT_SIG_KEYS)
        + (_ELASTIC_RESULT_CONTRACT_TOKEN,)
    )
    capacity_context_sig = (
        _get(_CAPACITY_CONTEXT_SIG_KEYS)
        + (
            (
                "2023 shear gamma_V",
                shear_gamma_v,
            )
            if shear_gamma_v_active
            else ("2023 shear gamma_V inactive",)
        )
        + (_CAPACITY_RESULT_CONTRACT_TOKEN,)
    )
    plastic_case_context_sig = (
        plastic_bending_context_sig + capacity_context_sig
    )
    plastic_table_sig = _case_table_signature(
        case_frames[load_cases.PLASTIC_TABLE_KEY],
        load_cases.PLASTIC_TABLE_KEY,
    )
    elastic_table_sig = _case_table_signature(
        case_frames[load_cases.ELASTIC_TABLE_KEY],
        load_cases.ELASTIC_TABLE_KEY,
    )
    plastic_sig = plastic_case_context_sig + (plastic_table_sig,)
    elastic_sig = elastic_case_context_sig + (elastic_table_sig,)
    fatigue_sig = (
        (
            "fatigue",
            True,
            _FATIGUE_RESULT_CONTRACT_TOKEN,
            geom_sig,
            material_sig,
            fatigue_edition,
            bool(fatigue_check_steel),
            bool(fatigue_check_concrete),
            fatigue_concrete_method,
            float(concrete.fck),
            float(concrete.alpha_cc),
            float(fatigue_gamma_c),
            float(fatigue_gamma_s),
            float(fatigue_gamma_ff),
            float(fatigue_beta_cc_t0),
            float(fatigue_t0_days),
            float(fatigue_concrete_k1),
            float(fatigue_concrete_c),
            float(nl),
            float(ns),
            fatigue_inputs.catalog_signature(fatigue_catalogue),
            fatigue_inputs.basis_signature(fatigue_basis),
            _fatigue_spectrum_signature(fatigue_spectrum),
        )
        if fatigue_on
        else ("fatigue", False)
    )
    sig = plastic_sig + elastic_sig + (fatigue_sig,)
    st.session_state.pop("_auto_all", None)   # one-shot: applied this run only
    # Fill the reserved Save-Load / About slots now the inputs exist, so the
    # project download captures the fully-built section and loads.
    # Project gathering and save widgets are among the most expensive
    # non-calculation parts of an Inputs rerun.  They are independent of the four
    # engineering input stages, so build them only while their tracked tab is open.
    if project.open:
        with save_slot:
            _save_load_panel()
        with about_slot.expander("About", expanded=False):
            st.markdown("### Sector")
            st.caption("Reinforced-concrete and prestressed cross-section analysis.")
            st.markdown(
                "- **Plastic:** M-M capacity and utilisation\n"
                "- **Elastic:** cracked-section stresses and optional crack width\n"
                "- **Fatigue:** grouped spectrum assessment\n"
                "- **Capacity checks:** shear, torsion and combined M-V-T")
            st.caption(
                "Sector is a transparent calculation tool. The selected methods "
                "supply equations, references, defaults and warnings; the engineer "
                "controls the action set and coefficients."
            )
            st.caption("Set inputs, Calculate, review Results Overview, then export.")
            st.divider()
            st.markdown(f"**Sector v{APP_VERSION}**")
            st.caption(f"Author: {APP_AUTHOR}  \nEmail: {APP_EMAIL}")
            st.caption(
                f"Proprietary software; licensed to {APP_LICENSEE} for internal use."
            )
            if st.button(
                "User manual", key="open_manual", width="stretch",
                help="Open the user manual.",
            ):
                _open_manual_dialog()
    input_assembly_token = app_run_probe.start_phase(
        st.session_state, "input_assembly"
    )
    inp = dict(section=section, geometry_error=geometry_error,
                void_error=void_error, steel_error=steel_error,
                material_error=material_error,
                material_assignment_errors=tuple(material_assignment_errors),
                material_definition_errors=tuple(material_definition_errors),
                torsion_gamma_ct_error=torsion_gamma_ct_error,
                fatigue_assignment_error=fatigue_assignment_error,
                concrete=concrete, steel=reference_steel,
                concrete_preset=concrete_preset,
                concrete_material_id=concrete_preset,
                concrete_k_tc=concrete_k_tc,
                concrete_eta_cc=concrete_eta_cc,
                mild_preset=mild_preset,
                prestress_preset=prestress_preset,
                plastic_case={
                    "id": str(pl_case_id).strip(),
                    "type": pl_case_type,
                    "source": str(pl_case_source).strip(),
                },
                elastic_case={
                    "id": str(el_case_id).strip(),
                    "type": el_case_type,
                    "source": str(el_case_source).strip(),
                },
                plastic_cases=case_frames[load_cases.PLASTIC_TABLE_KEY],
                elastic_cases=case_frames[load_cases.ELASTIC_TABLE_KEY],
                bars=bars, outer=outer, holes=holes, tendons=tendons,
                bar_elements=bar_elements, tendon_elements=tendon_elements,
                slab_density=slab_density,
                mild_material_catalog=mild_catalogue,
                prestress_material_catalog=prestress_catalogue,
                fatigue_detail_catalog=fatigue_catalogue,
                fatigue_basis=fatigue_basis,
                fatigue_spectrum_base=fatigue_inputs.normalise_spectrum_table(
                    st.session_state[fatigue_inputs.SPECTRUM_TABLE_KEY]
                ),
                mild_materials=mild_material_map,
                prestress_materials=prestress_material_map,
                bar_materials=bar_materials,
                tendon_materials=tendon_materials,
                capacity_steel_material_id=capacity_steel_material_id,
                prestress=prestress, P_pl=P_pl, Mx_pl=Mx_pl, My_pl=My_pl,
                check_util=check_util,
                interaction=interaction,
                v_min=v_min, v_max=v_max, v_inc=v_inc,
                P_el_l=P_el_l, Mx_el_l=Mx_el_l, My_el_l=My_el_l, nl=nl,
                P_el_s=P_el_s, Mx_el_s=Mx_el_s, My_el_s=My_el_s, ns=ns,
                el_phi=phi_creep, conc_Ec=conc_Ec,
                sls_cw=sls_cw, sls_fctm=sls_fctm, sls_phi=sls_phi,
                sls_bond=sls_bond, sls_k1=sls_k1, sls_dk_na=sls_dk_na,
                sls_tendon_xi=sls_tendon_xi,
                sls_edition=sls_edition, sls_code=sls_code, sls_member=sls_member,
                sls_long_term_permitted_crack_width_mm=(
                    sls_long_term_permitted_crack_width_mm
                ),
                sls_short_term_permitted_crack_width_mm=(
                    sls_short_term_permitted_crack_width_mm
                ),
                sls_long_term_permitted_crack_width_source=(
                    LONG_TERM_PERMITTED_CRACK_WIDTH_SOURCE
                ),
                sls_short_term_permitted_crack_width_source=(
                    SHORT_TERM_PERMITTED_CRACK_WIDTH_SOURCE
                ),
                sls_heightened_on=sls_heightened_on,
                sls_heightened_permitted_crack_width_mm=(
                    sls_heightened_permitted_crack_width_mm
                ),
                sls_heightened_reference_case=(
                    sls_heightened_reference_case
                ),
                sls_heightened_reinforcement_surface=(
                    sls_heightened_reinforcement_surface
                ),
                sls_heightened_effective_tensile_strength_mpa=(
                    sls_heightened_effective_tensile_strength_mpa
                ),
                sls_heightened_fine_effective_tension_area_mm2=(
                    sls_heightened_fine_effective_tension_area_mm2
                ),
                sls_heightened_coarse_effective_tension_area_mm2=(
                    sls_heightened_coarse_effective_tension_area_mm2
                ),
                shear_on=shear_on,
                shear_method=(combined_method if combined_on else shear_method),
                shear_Vx=case_head["shear_Vx"], shear_Vy=case_head["shear_Vy"],
                shear_face_x=(
                    str(case_frames[load_cases.PLASTIC_TABLE_KEY].iloc[0]["vx_face"])
                    if not case_frames[load_cases.PLASTIC_TABLE_KEY].empty
                    else load_cases.FACE_AUTO
                ),
                shear_face_y=(
                    str(case_frames[load_cases.PLASTIC_TABLE_KEY].iloc[0]["vy_face"])
                    if not case_frames[load_cases.PLASTIC_TABLE_KEY].empty
                    else load_cases.FACE_AUTO
                ),
                shear_vx_bw=shear_vx_bw, shear_vy_bw=shear_vy_bw,
                shear_dlower=shear_dlower,
                shear_gamma_v=effective_shear_gamma_v,
                shear_links=shear_links,
                shear_vx_link_legs=shear_vx_link_legs,
                shear_vy_link_legs=shear_vy_link_legs,
                shear_vx_transverse_leg_spacing=(
                    shear_vx_transverse_leg_spacing
                ),
                shear_vy_transverse_leg_spacing=(
                    shear_vy_transverse_leg_spacing
                ),
                shear_link_dia=shear_link_dia, shear_link_s=shear_link_s,
                shear_fywk=shear_fywk,
                strut_cot_min=strut_cot_min,
                strut_cot_max=strut_cot_max,
                torsion_on=torsion_on,
                torsion_method=(combined_method if combined_on else torsion_method),
                torsion_T=torsion_T, torsion_tef=torsion_tef,
                torsion_nu_v=torsion_nu_v,
                torsion_gamma_ct=torsion_gamma_ct,
                torsion_subdivide=torsion_subdivide,
                torsion_subrects=torsion_subrects,
                combined_on=combined_on, combined_method=combined_method,
                combined_mv_independent=combined_mv_independent,
                minimum_reinforcement_on=minimum_reinforcement_on,
                transverse_detailing_on=transverse_detailing_on,
                clear_spacing_on=clear_spacing_on,
                detailing_edition=detailing_edition,
                detailing_member_type=detailing_member_type,
                detailing_cut_direction=detailing_cut_direction,
                modelled_direction_alias=modelled_direction.normalise_alias(
                    modelled_direction_alias
                ),
                detailing_d_upper=detailing_d_upper,
                detailing_include_tendons=detailing_include_tendons,
                transverse_ductility_class=transverse_ductility_class,
                transverse_apply_ductility_reduction=(
                    transverse_apply_ductility_reduction
                ),
                fatigue_on=fatigue_on,
                fatigue_edition=fatigue_edition,
                fatigue_check_steel=fatigue_check_steel,
                fatigue_check_concrete=fatigue_check_concrete,
                fatigue_concrete_method=fatigue_concrete_method,
                fatigue_gamma_c=fatigue_gamma_c,
                fatigue_gamma_s=fatigue_gamma_s,
                fatigue_gamma_ff=fatigue_gamma_ff,
                fatigue_beta_cc_t0=fatigue_beta_cc_t0,
                fatigue_t0_days=fatigue_t0_days,
                fatigue_concrete_k1=fatigue_concrete_k1,
                fatigue_concrete_c=fatigue_concrete_c,
                mode=mode, extent=extent,
                label_scale=label_scale, label_min_gap=label_min_gap,
                signature=sig,
                plastic_sig=plastic_sig, elastic_sig=elastic_sig,
                fatigue_sig=fatigue_sig,
                plastic_case_context_sig=plastic_case_context_sig,
                elastic_case_context_sig=elastic_case_context_sig,
                plastic_bending_context_sig=plastic_bending_context_sig)
    app_run_probe.stop_phase(st.session_state, input_assembly_token)
    return inp


def _commit_input_fragment(inp) -> None:
    """Publish one complete Inputs render as the canonical engineering draft.

    A fragment rerun can be superseded by a later browser event.  Nothing from
    that partial build becomes durable until ``build_inputs`` returns normally;
    then the scalar/table mirrors, full analysis payload and autosave service
    observe the same completed state.
    """

    _snapshot_input_state(inp)
    st.session_state.pop(_PENDING_INPUT_EVENTS_KEY, None)
    st.session_state.pop(_INPUT_ISSUE_FOCUS_KEY, None)
    st.session_state[_INPUT_BUILD_KEY] = False
    st.session_state[_LAST_WORKSPACE_KEY] = "Inputs"
    _measured_autosave()


@st.fragment
def _input_workspace() -> None:
    """Render and commit the selected input pane in one sequential fragment.

    Ordinary input edits and stage switches rerun this boundary without
    reconstructing the top-level workspace or Analysis UI.  If a rapid event
    interrupted the preceding build, restore the last complete draft and replay
    every journaled genuine edit before any widget is remounted.
    """

    app_run_probe.open_fragment_run(st.session_state, "inputs")
    if st.session_state.get(_INPUT_BUILD_KEY, False):
        _restore_input_state(replace=True)
    st.session_state[_INPUT_BUILD_KEY] = True
    focus = st.session_state.get(_INPUT_ISSUE_FOCUS_KEY)
    if isinstance(focus, dict):
        location = str(focus.get("stage") or "Inputs")
        if focus.get("material_family"):
            location += f" / {focus['material_family']}"
        correction = str(focus.get("widget_label") or "the cited input")
        focus_message = engineer_messages.error_detail(
            focus.get("message"),
            fallback=_INPUT_FOCUS_DISPLAY,
            context="input issue focus",
        )
        st.info(
            f"Opened **{location}**. Correction target: **{correction}**.  \n"
            f"{focus_message}"
        )
    pane_token = app_run_probe.start_phase(
        st.session_state, "pane_construction"
    )
    try:
        inp = build_inputs(st)
    finally:
        app_run_probe.stop_phase(st.session_state, pane_token)
    _commit_input_fragment(inp)
    app_run_probe.close_fragment_run(st.session_state)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _sweep(v_min, v_max, v_inc):
    """Use the core inclusive-endpoint/max-increment sweep contract."""

    return plastic_core.plastic_sweep_angles(v_min, v_max, v_inc)


def _props_dict(p):
    """Flatten SectionProperties to a plain dict for the results payload."""
    return dict(area=p.area, cx=p.cx, cy=p.cy, Ix=p.Ix, Iy=p.Iy, Ixy=p.Ixy)


def _plastic_point_result(point, inp):
    """Flatten one accepted plastic state without evaluating a material law."""

    corner_rows = []
    for point_no, state in enumerate(point.concrete_corner_states or (), start=1):
        corner_rows.append(dict(
            point_no=point_no,
            ring=("Outer" if state.ring_index == 0
                  else f"Hole {state.ring_index}"),
            ring_point_no=state.point_index + 1,
            x_mm=state.x * _MM,
            y_mm=state.y * _MM,
            section_strain_permille=state.section_strain * _MM,
            strain_permille=state.material_strain * _MM,
            stress_mpa=state.material_stress,
        ))

    mild_names = {
        item.get("id"): item.get("name")
        for item in (inp.get("mild_material_catalog") or {}).get("items", [])
    }
    prestress_names = {
        item.get("id"): item.get("name")
        for item in (inp.get("prestress_material_catalog") or {}).get("items", [])
    }

    reinforcement_rows = []

    def append_states(states, family, elements, names):
        for state in states or ():
            metadata = (
                elements[state.element_index]
                if state.element_index < len(elements) else {}
            )
            element_no = state.element_index + 1
            element_id = str(metadata.get("id") or f"{family.lower()} {element_no}")
            material_id = metadata.get("material_id")
            strain = state.material_strain
            reinforcement_rows.append(dict(
                element_type=family,
                element_no=element_no,
                element_id=element_id,
                material_id=material_id,
                material_name=names.get(material_id),
                state=("Tension" if strain > 1.0e-12 else
                       "Compression" if strain < -1.0e-12 else "Neutral"),
                x_mm=state.x * _MM,
                y_mm=state.y * _MM,
                area_mm2=state.area * 1.0e6,
                section_strain_permille=state.section_strain * _MM,
                initial_strain_permille=state.initial_strain * _MM,
                strain_permille=strain * _MM,
                stress_mpa=state.material_stress,
                force_kn=-state.force,
                internal_force_kn=state.force,
                internal_mx_knm=state.mx,
                internal_my_knm=state.my,
            ))

    bar_elements = list(inp.get("bar_elements") or [])
    tendon_elements = list(inp.get("tendon_elements") or [])
    append_states(point.bar_states, "Bar", bar_elements, mild_names)
    append_states(point.tendon_states, "Tendon", tendon_elements, prestress_names)

    candidate_rows = []
    selection = point.curvature_selection
    if selection is not None:
        for candidate in selection.candidates:
            if candidate.mode.startswith("bar_") and candidate.element_index is not None:
                metadata = (bar_elements[candidate.element_index]
                            if candidate.element_index < len(bar_elements) else {})
                element_id = str(
                    metadata.get("id") or f"bar {candidate.element_index + 1}"
                )
            elif (candidate.mode.startswith("tendon_")
                  and candidate.element_index is not None):
                metadata = (tendon_elements[candidate.element_index]
                            if candidate.element_index < len(tendon_elements) else {})
                element_id = str(
                    metadata.get("id") or f"tendon {candidate.element_index + 1}"
                )
            else:
                element_id = None
            candidate_rows.append(dict(
                mode=candidate.mode,
                element_index=candidate.element_index,
                element_id=element_id,
                strain_limit=candidate.strain_limit,
                distance_from_na_m=candidate.distance_from_na,
                curvature_per_m=candidate.curvature,
                selected=(
                    candidate.mode == selection.selected_mode
                    and candidate.element_index == selection.selected_element_index
                ),
            ))

    return dict(
        V=point.V,
        Mx=point.Mx,
        My=point.My,
        na_x=point.na_x_intercept,
        na_y=point.na_y_intercept,
        eps_c=-point.eps_concrete,
        eps_s=-point.eps_steel,
        eps_s_comp=-point.eps_steel_comp,
        eps_cable=-point.eps_cable,
        kappa=point.curvature,
        comp_force=point.compression_force,
        lever=point.lever_arm,
        dx=point.dx,
        dy=point.dy,
        converged=point.converged,
        axial_requested=point.axial_requested,
        axial_achieved=point.axial,
        axial_residual=point.axial_residual,
        axial_tolerance=point.axial_tolerance,
        axial_reachable=point.axial_reachable,
        compression_depth=point.compression_depth,
        neutral_axis_offset=point.neutral_axis_offset,
        strain_gradient_x=point.strain_gradient_x,
        strain_gradient_y=point.strain_gradient_y,
        strain_offset=point.strain_offset,
        search_lower_depth=point.search_lower_depth,
        search_upper_depth=point.search_upper_depth,
        search_lower_axial=point.search_lower_axial,
        search_upper_axial=point.search_upper_axial,
        search_iterations=point.search_iterations,
        concrete_force=point.concrete_force,
        concrete_mx=point.concrete_mx,
        concrete_my=point.concrete_my,
        bar_force=point.bar_force,
        bar_mx=point.bar_mx,
        bar_my=point.bar_my,
        tendon_force=point.tendon_force,
        tendon_mx=point.tendon_mx,
        tendon_my=point.tendon_my,
        compression_mx=point.compression_mx,
        compression_my=point.compression_my,
        tension_force=point.tension_force,
        tension_mx=point.tension_mx,
        tension_my=point.tension_my,
        concrete_corner_states=corner_rows,
        reinforcement_states=reinforcement_rows,
        curvature_candidates=candidate_rows,
        curvature_selection=(
            dict(
                mode=selection.selected_mode,
                element_index=selection.selected_element_index,
                curvature_per_m=selection.selected_curvature,
            ) if selection is not None else None
        ),
    )


def _elastic_resultant_result(value):
    """Flatten one named elastic resultant with heterogeneous physical units."""

    return dict(
        n=value.axial_force,
        mx=value.moment_x,
        my=value.moment_y,
    )


def _elastic_state_result(value):
    """Flatten one accepted Ec=1 elastic state for publication."""

    sigma0, gradient_x, gradient_y = value.raw_stress_plane
    equilibrium = value.equilibrium
    return dict(
        raw_stress_plane=dict(
            sigma0_kpa=sigma0,
            gradient_x_kpa_per_m=gradient_x,
            gradient_y_kpa_per_m=gradient_y,
        ),
        iterations=value.iterations,
        converged=value.converged,
        equilibrium=dict(
            matrix=[list(row) for row in equilibrium.equilibrium_matrix],
            target=_elastic_resultant_result(equilibrium.target),
            internal=_elastic_resultant_result(equilibrium.internal),
            residual=_elastic_resultant_result(equilibrium.residual),
            residual_scale=equilibrium.residual_scale,
            normalised_residual=equilibrium.normalised_residual,
            relative_tolerance=equilibrium.relative_tolerance,
        ),
    )


def _area_moments_dict(value):
    """Flatten one authoritative polygon-moment result for publication."""

    return dict(
        area_m2=value.area,
        first_x_m3=value.sx,
        first_y_m3=value.sy,
        second_xx_m4=value.sxx,
        second_yy_m4=value.syy,
        product_xy_m4=value.sxy,
    )


def _section_and_material_results(inp):
    """Prepare shared existing calculations once for human-readable output.

    These are compact final-state breakdowns, not a trace or a second solver.
    Every numerical value comes from an existing family kernel/property and is
    shared by all named action cases in the current run.
    """

    # Use the section's established integration orientation: outer positive,
    # voids negative, independent of the user's vertex-entry direction.
    rings = inp["section"].integration_rings()
    moments = geometry.area_moment_breakdown(rings)
    section_properties = dict(
        rings=[
            dict(
                ring_id=("outer" if index == 0 else f"void {index}"),
                role=("gross outline" if index == 0 else "void deduction"),
                **_area_moments_dict(value),
            )
            for index, value in enumerate(moments.ring_moments)
        ],
        net_concrete=dict(
            **_area_moments_dict(moments.total),
            centroid_x_m=moments.centroid[0],
            centroid_y_m=moments.centroid[1],
            ix_centroid_m4=moments.centroidal_syy,
            iy_centroid_m4=moments.centroidal_sxx,
            ixy_centroid_m4=moments.centroidal_sxy,
        ),
    )

    concrete = inp["concrete"]
    mild_ids = list(dict.fromkeys(
        [item.get("material_id") for item in inp.get("bar_elements", [])]
        + ([inp.get("capacity_steel_material_id")]
           if inp.get("shear_on") or inp.get("torsion_on") else [])
    ))
    mild_ids = [value for value in mild_ids if value]
    mild_laws = inp.get("mild_materials") or {}
    if not mild_ids and (inp.get("bars") or inp.get("shear_on")
                         or inp.get("torsion_on")):
        mild_ids = ["-"]
        mild_laws = {"-": inp["steel"]}
    mild = []
    for material_id in mild_ids:
        material = mild_laws.get(material_id)
        if material is None:
            continue
        mild.append(dict(
            material_id=material_id,
            characteristic_yield_mpa=material.fytk,
            yield_factor=material.gamma_y,
            design_yield_mpa=capacity.design_yield(material),
        ))

    prestress_ids = list(dict.fromkeys(
        item.get("material_id") for item in inp.get("tendon_elements", [])
    ))
    prestress_ids = [value for value in prestress_ids if value]
    prestress_laws = inp.get("prestress_materials") or {}
    if not prestress_ids and inp.get("tendons") and inp.get("prestress") is not None:
        prestress_ids = ["-"]
        prestress_laws = {"-": inp["prestress"]}
    prestress_materials = []
    for material_id in prestress_ids:
        material = prestress_laws.get(material_id)
        if material is None:
            continue
        prestress_materials.append(dict(
            material_id=material_id,
            curve=material.curve,
            rupture_strain=material.rupture_strain,
            characteristic_stress_at_rupture_mpa=(
                material.stress(material.rupture_strain, design=False)
                if material.curve in (1, 2, 3, 4, 5) else None
            ),
        ))
    material_properties = dict(
        concrete=dict(
            variant=("2023" if "2023" in str(inp.get("concrete_preset", ""))
                     else "2005"),
            characteristic_strength_mpa=concrete.fck,
            strength_factor=concrete.alpha_cc,
            partial_factor=concrete.gamma_c,
            eta_cc=inp.get("concrete_eta_cc"),
            k_tc=inp.get("concrete_k_tc"),
            design_strength_mpa=concrete.fcd,
        ),
        mild=mild,
        prestress=prestress_materials,
    )

    prestress = capacity.locked_in_prestress_result(inp)
    tendon_elements = list(inp.get("tendon_elements") or [])
    prestress_rows = []
    for value in prestress.tendons:
        row = dataclasses.asdict(value)
        row["material_id"] = (
            tendon_elements[value.tendon_index].get("material_id")
            if value.tendon_index < len(tendon_elements) else None
        )
        prestress_rows.append(row)
    prestress_initial = dict(
        elements=prestress_rows,
        internal_resultant_origin=dict(
            n_kn=prestress.total_n_kn,
            mx_knm=prestress.total_mx_knm,
            my_knm=prestress.total_my_knm,
        ),
        equivalent_action_origin=dict(
            n_kn=-prestress.total_n_kn,
            mx_knm=prestress.total_mx_knm,
            my_knm=prestress.total_my_knm,
        ),
    )

    descriptors = []
    seen = set()
    for family, elements, materials in (
        ("mild", inp.get("bar_elements", []), inp.get("bar_materials", [])),
        ("prestress", inp.get("tendon_elements", []),
         inp.get("tendon_materials", [])),
    ):
        for element, material in zip(elements, materials):
            material_id = str(element.get("material_id") or "-")
            identity = (family, material_id)
            if identity in seen:
                continue
            seen.add(identity)
            descriptors.append((material_id, family, material.Es))
    if not descriptors:
        if inp.get("bars") and inp.get("steel") is not None:
            descriptors.append(("M1", "mild", inp["steel"].Es))
        if inp.get("tendons") and inp.get("prestress") is not None:
            descriptors.append(("P1", "prestress", inp["prestress"].Es))
    ratios = elastic_core.calculate_modular_ratios(
        float(inp["conc_Ec"]) * 1000.0,
        float(inp.get("el_phi") or 0.0),
        descriptors,
    )
    elastic_shared = dict(
        concrete_modulus_mpa=ratios.concrete_modulus_mpa,
        effective_concrete_modulus_mpa=ratios.effective_concrete_modulus_mpa,
        creep_coefficient=ratios.creep_coefficient,
        materials=[dataclasses.asdict(value) for value in ratios.materials],
    )
    return dict(
        section_properties=section_properties,
        material_properties=material_properties,
        prestress_initial=prestress_initial,
        elastic_shared=elastic_shared,
    )


def _elastic_solver_inputs(inp, shared_results):
    """Prepare existing per-element elastic inputs once for every named case."""

    all_laws = list(inp.get("bar_materials") or
                    [inp["steel"]] * len(inp.get("bars", [])))
    all_laws.extend(inp.get("tendon_materials") or [])
    n_mult = (
        np.asarray(
            [material.Es / STEEL_REFERENCE_MODULUS for material in all_laws],
            dtype=float,
        )
        if all_laws else None
    )
    prestress_rows = shared_results["prestress_initial"]["elements"]
    prestress_stress = None
    if prestress_rows:
        prestress_stress = np.asarray(
            [0.0] * len(inp.get("bars", []))
            + [row["locked_in_stress_mpa"] * 1000.0 for row in prestress_rows],
            dtype=float,
        )
    return n_mult, prestress_stress


def _crack_dict(cw, bar_ids=None, tendon_ids=None):
    """Flatten a CrackWidthResult (or None) for the results payload."""
    if cw is None:
        return None

    bar_ids = list(bar_ids or [])
    tendon_ids = list(tendon_ids or [])
    n_bars = len(bar_ids)

    def retained_record(value):
        """Serialize one family-owned retained record without deriving values."""

        if value is None:
            return None
        row = dataclasses.asdict(value)
        row["record_kind"] = type(value).__name__
        return row

    def element(index):
        if index < n_bars:
            number = index + 1
            element_id = bar_ids[index] if index < len(bar_ids) else f"bar {number}"
            return "Bar", number, element_id
        number = index - n_bars + 1
        tendon_index = index - n_bars
        element_id = (tendon_ids[tendon_index]
                      if tendon_index < len(tendon_ids) else f"tendon {number}")
        return "Tendon", number, element_id

    def candidate(c):
        kind, number, element_id = element(c.bar_index)
        return dict(
            element_type=kind, element_no=number,
            element_id=element_id,
            x_mm=c.x * _MM, y_mm=c.y * _MM, area_mm2=c.area,
            wk=c.wk, sr_max=c.sr_max, esm_ecm=c.esm_ecm,
            sigma_s=c.sigma_s, rho_p_eff=c.rho_p_eff, ac_eff=c.ac_eff,
            hc_ef=c.hc_ef, phi=c.phi, cover=c.cover, coarse=c.coarse,
            edition=c.edition, kw=c.kw, k1_r=c.k1_r, kfl=c.kfl,
            sr_max_geometric=c.sr_max_geometric,
            as_eff=c.as_eff, ap_eff=c.ap_eff,
            ap_eff_weighted=c.ap_eff_weighted, xi1=c.xi1,
            reinforcement_type=c.reinforcement_type, bc_ef=c.bc_ef,
            direct_tension=c.direct_tension, scope=c.scope,
            direction_deg=c.direction_deg,
            equivalent_diameter=c.equivalent_diameter,
            diameter_source=c.diameter_source,
            cover_source=c.cover_source,
            bond_coefficient=c.bond_coefficient,
            modular_ratio=c.modular_ratio,
            mean_strain_operands=retained_record(c.mean_strain_operands),
            spacing_operands=retained_record(c.spacing_operands),
        )

    kind, number, element_id = element(cw.gov_bar)
    governing_candidate = (
        candidate(cw.candidates[0]) if cw.candidates else None
    )
    effective_reinforcement = retained_record(
        cw.effective_reinforcement_2023
    )
    if effective_reinforcement is not None:
        for row in effective_reinforcement.get("elements", []):
            element_kind, element_number, retained_id = element(
                int(row["element_index"])
            )
            row.update(
                element_type=element_kind,
                element_no=element_number,
                element_id=retained_id,
            )
    effective_elements = []
    for retained in cw.effective_reinforcement:
        row = dataclasses.asdict(retained)
        element_kind, element_number, retained_id = element(
            int(row["element_index"])
        )
        row.update(
            element_type=element_kind,
            element_no=element_number,
            element_id=retained_id,
        )
        effective_elements.append(row)
    return dict(
        wk=cw.wk, sr_max=cw.sr_max, esm_ecm=cw.esm_ecm,
        sigma_s=cw.sigma_s, rho_p_eff=cw.rho_p_eff, ac_eff=cw.ac_eff,
        hc_ef=cw.hc_ef, phi=cw.phi, cover=cw.cover,
        gov_bar=cw.gov_bar + 1, element_type=kind, element_no=number,
        element_id=element_id, coarse=cw.coarse,
        edition=cw.edition, kw=cw.kw, k1_r=cw.k1_r, kfl=cw.kfl,
        sr_max_geometric=cw.sr_max_geometric,
        as_eff=cw.as_eff, ap_eff=cw.ap_eff,
        ap_eff_weighted=cw.ap_eff_weighted,
        xi1_min=cw.xi1_min, xi1_max=cw.xi1_max,
        bc_ef=cw.bc_ef, direct_tension=cw.direct_tension,
        scope=cw.scope, direction_deg=cw.direction_deg,
        effective_area_operands=retained_record(cw.effective_area_operands),
        effective_reinforcement_2023=effective_reinforcement,
        effective_reinforcement=effective_elements,
        governing_rule=cw.governing_rule,
        governing_candidate=governing_candidate,
        candidates=[candidate(c) for c in cw.candidates],
    )


def _outline_bbox(outer):
    """Bounding box ``(xmin, ymin, xmax, ymax)`` of the outline, or ``None``.

    Used to clip the drawn neutral-axis segment to the section (viz.na_line_at):
    unclipped it spans +/- extent about the origin-closest point, which overshoots
    badly for a section drawn away from the origin.
    """
    outer = [] if outer is None else list(outer)
    if len(outer) < 3:
        return None
    xs = [p[0] for p in outer]
    ys = [p[1] for p in outer]
    return (min(xs), min(ys), max(xs), max(ys))


def _shear_lever_arm(*args, **kwargs):
    return capacity.shear_lever_arm(*args, **kwargs)


def _shear_face_mrd(*args, **kwargs):
    return capacity.shear_face_mrd(*args, **kwargs)


def _tube_torsion(*args, **kwargs):
    return capacity.tube_torsion(*args, **kwargs)


def _run_single_analysis(
    inp,
    *,
    reuse_plastic=None,
    reuse_elastic=None,
    elastic_solver_inputs=None,
    shared_results=None,
):
    """Run one Plastic/Elastic action pair and return the results payload.

    ``reuse_plastic`` / ``reuse_elastic`` let the caller pass a previously computed
    plastic / elastic sub-result whose inputs are unchanged (its split signature
    matches); that analysis is then skipped and the cached result reused, so a Both
    run that only touched the elastic (or only the plastic) inputs recomputes just
    the affected half.
    """
    out = {}
    if (inp["section"] is None or inp.get("geometry_error")
            or inp.get("void_error")
            or inp.get("steel_error") or inp.get("material_error")):
        return out                          # invalid section -> nothing to run
    if shared_results is None:
        shared_results = _section_and_material_results(inp)
    if elastic_solver_inputs is None:
        elastic_solver_inputs = _elastic_solver_inputs(inp, shared_results)
    if inp["mode"] in ("Plastic", "Both") and reuse_plastic is not None:
        out["plastic"] = reuse_plastic
    elif inp["mode"] in ("Plastic", "Both"):
        _warm_solver()
        sweep_angles = _sweep(inp["v_min"], inp["v_max"], inp["v_inc"])
        vlo, vhi = sweep_angles[0], sweep_angles[-1]
        # A full 360 deg turn returns to the start, so the last angle (v_max) repeats
        # the first (v_min) exactly. Sweep only up to the angle before it -- the
        # envelope closes itself -- so that duplicate point is neither computed nor
        # reported. The closed-envelope flag still reflects the full turn.
        closed = plastic_core.plastic_sweep_is_full_turn(vlo, vhi)
        sweep_hi = sweep_angles[-2] if closed else vhi
        # Prestress enters the analysis only when the section actually has tendons.
        pre = inp["prestress"] if inp["tendons"] else None
        # The user enters N tension-positive; the solver is compression-positive, so
        # negate at the boundary (the engine and its verification are unchanged).
        pts = solve_plastic(inp["section"], inp["concrete"], inp["steel"],
                            -inp["P_pl"], vlo, sweep_hi, inp["v_inc"], prestress=pre,
                            bar_materials=inp.get("bar_materials"),
                            tendon_materials=inp.get("tendon_materials"))
        mx = [p.Mx for p in pts]
        my = [p.My for p in pts]
        # Utilisation is a closed-envelope check (a partial arc has no wrap-around), and
        # only reported when the user asks to check it; otherwise this is a capacity-only
        # run (the applied moments are ignored and locked).
        check_util = inp.get("check_util", True)
        if closed and check_util:
            radial = combined.radial_util_result(
                mx, my, inp["Mx_pl"], inp["My_pl"]
            )
            util = radial.utilisation if radial.valid else None
            util_gov = radial.governing_index if radial.valid else None
            util_demand = radial.demand
            util_resistance = radial.resistance
            util_valid = radial.valid
            util_reason = radial.reason
            util_origin_inside_or_on = radial.origin_inside_or_on
        else:
            util, util_gov = None, None
            util_demand, util_resistance = None, None
            util_valid, util_reason = None, None
            util_origin_inside_or_on = None
        out["plastic"] = dict(
            mx=mx, my=my,
            max_mx=max(mx), max_my=max(my), min_mx=min(mx), min_my=min(my),
            util=util, util_gov=util_gov, closed=closed, check_util=check_util,
            util_demand=util_demand, util_resistance=util_resistance,
            util_valid=util_valid, util_reason=util_reason,
            util_origin_inside_or_on=util_origin_inside_or_on,
            applied=((inp["Mx_pl"], inp["My_pl"]) if check_util else None),
            converged=all(p.converged for p in pts),
            # The adapter publishes the accepted state already evaluated by the
            # plastic family. It performs unit/sign conversion and identity
            # decoration only; no material law or capacity calculation is repeated.
            points=[_plastic_point_result(point, inp) for point in pts],
            effective_depths=capacity.plastic_effective_depths(inp),
        )
        worked_index = (
            util_gov
            if util_gov is not None and 0 <= util_gov < len(pts)
            else max(range(len(pts)), key=lambda index: math.hypot(
                pts[index].Mx, pts[index].My
            ))
        )
        out["plastic"].update(
            worked_point_index=worked_index,
            worked_point_basis=(
                "utilisation direction" if util_gov is not None
                else "peak resultant moment"
            ),
        )
        # Opt-in N-M interaction diagrams, one about each bending axis. For each axis
        # trace the +M branch (NA angle stored as V) and the -M branch (V+180) from
        # pure tension to the squash load, then join them into one closed capacity
        # boundary. About x uses a horizontal neutral axis (V = 90/270, Mx varies);
        # about y a vertical one (V = 0/180, My varies).
        if inp.get("interaction"):
            branch = lambda v: solve_interaction(inp["section"], inp["concrete"],
                                                 inp["steel"], v, prestress=pre,
                                                 bar_materials=inp.get("bar_materials"),
                                                 tendon_materials=inp.get(
                                                     "tendon_materials"))
            loop_x = branch(90.0) + list(reversed(branch(270.0)))
            loop_y = branch(0.0) + list(reversed(branch(180.0)))
            # The solver reports the axial compression-positive; negate it so the
            # diagram and the applied point are both tension-positive (matching N).
            out["plastic"]["interaction"] = dict(
                x=dict(N=[-q.axial for q in loop_x], M=[q.Mx for q in loop_x],
                       applied=(inp["P_pl"], inp["Mx_pl"]),
                       converged=all(q.converged for q in loop_x)),
                y=dict(N=[-q.axial for q in loop_y], M=[q.My for q in loop_y],
                       applied=(inp["P_pl"], inp["My_pl"]),
                       converged=all(q.converged for q in loop_y)),
            )
    if inp["mode"] in ("Elastic", "Both") and reuse_elastic is not None:
        out["elastic"] = reuse_elastic
    elif inp["mode"] in ("Elastic", "Both"):
        # The user enters N tension-positive; the elastic solver takes it
        # compression-positive, so negate it once here and pass the compression form
        # to every elastic call (main solve and the two cracking checks).
        p_el_l, p_el_s = -inp["P_el_l"], -inp["P_el_s"]
        # Tendons are folded into the bar set for the elastic run. Each tendon uses
        # its own modular ratio (Ep/Ec, via the multiplier Ep/Es) and carries the
        # locked-in prestress Ep*IS, applied as a force so the user's N is the
        # external normal force only -- matching the plastic solver.
        sec = inp["section"]
        bar_laws = list(inp.get("bar_materials") or
                        [inp["steel"]] * len(inp["bars"]))
        tendon_laws = list(inp.get("tendon_materials") or [])
        all_laws = bar_laws + tendon_laws
        n_mult, prestress_stress = elastic_solver_inputs
        pre_resultant = None
        if inp["tendons"]:
            sec = section_core.Section.from_polygon(
                corners=inp["outer"],
                bars_xy_area_mm2=list(inp["bars"]) + list(inp["tendons"]),
                holes=inp["holes"],
            )
            internal = shared_results["prestress_initial"][
                "internal_resultant_origin"
            ]
            pre_resultant = (
                internal["n_kn"], internal["mx_knm"], internal["my_knm"]
            )
        r = solve_elastic_combined(sec, p_el_l, inp["Mx_el_l"], inp["My_el_l"],
                                   inp["nl"], p_el_s, inp["Mx_el_s"],
                                   inp["My_el_s"], inp["ns"],
                                   n_mult=n_mult, prestress_stress=prestress_stress)
        mpa = lambda arr: [s / 1000.0 for s in arr]  # kN/m2 -> MPa
        total = mpa(r.bar_stress_total)
        bar_ids = [item["id"] for item in inp.get("bar_elements", [])]
        tendon_ids = [item["id"] for item in inp.get("tendon_elements", [])]
        mild_names = {
            item["id"]: item["name"]
            for item in inp["mild_material_catalog"]["items"]
        }
        prestress_names = {
            item["id"]: item["name"]
            for item in inp["prestress_material_catalog"]["items"]
        }
        elements = sls_core.element_rows(
            inp["bars"], inp["tendons"],
            total=total, long=mpa(r.bar_stress_long),
            dif=mpa(r.bar_stress_dif), rst1=mpa(r.bar_stress_rst1),
            es_mpa=[material.Es for material in bar_laws],
            ep_mpa=([material.Es for material in tendon_laws]
                    if tendon_laws else None),
            bar_ids=bar_ids, tendon_ids=tendon_ids,
            bar_material_ids=[item["material_id"]
                              for item in inp.get("bar_elements", [])],
            tendon_material_ids=[item["material_id"]
                                 for item in inp.get("tendon_elements", [])],
            bar_material_names=[mild_names.get(element["material_id"], "")
                                for element in inp.get("bar_elements", [])],
            tendon_material_names=[
                prestress_names.get(element["material_id"], "")
                for element in inp.get("tendon_elements", [])
            ],
        )
        long_passive = mpa(r.bar_stress_long_passive)
        reduced_long = mpa(r.bar_stress_reduced_long)
        locked_in = mpa(r.bar_stress_locked_in)
        for index, row in enumerate(elements):
            row.update(
                long_passive_mpa=long_passive[index],
                reduced_long_mpa=reduced_long[index],
                locked_in_mpa=locked_in[index],
            )
        corners = sls_core.concrete_corner_rows(
            inp["outer"], inp["holes"],
            stress_plane=(r.short_term.eps0, r.short_term.kx, r.short_term.ky),
            ec_mpa=inp["conc_Ec"] * 1000.0,
        )
        governing_element = (
            max(elements, key=lambda row: row["total_mpa"]) if elements else None
        )
        if governing_element is not None and governing_element["total_mpa"] <= 0.0:
            governing_element = None
        stress_outputs = sls_core.stress_outputs(
            total,
            n_bars=len(inp["bars"]),
            max_concrete_compression=r.max_concrete_compression / 1000.0,
            valid=r.converged,
            bar_ids=bar_ids, tendon_ids=tendon_ids,
        )
        out["elastic"] = dict(
            total=total, long=mpa(r.bar_stress_long), dif=mpa(r.bar_stress_dif),
            rst1=mpa(r.bar_stress_rst1),
            max_conc=r.max_concrete_compression / 1000.0,
            max_conc_xy=tuple(r.short_term.max_concrete_xy),
            # Public point identifiers are one-based everywhere; the engine keeps
            # zero-based arrays internally.
            max_conc_point=int(r.max_concrete_point) + 1,
            na_x=r.na_x_intercept, na_y=r.na_y_intercept,
            max_steel=(governing_element["total_mpa"] if governing_element else 0.0),
            # Compatibility field: global one-based position in the solver's
            # bars-then-tendons array. New presentation uses max_steel_element so
            # a tendon is never labelled as a reinforcing bar.
            max_steel_bar=(int(np.argmax(total)) + 1
                           if governing_element is not None else 0),
            max_steel_type=(governing_element["element_type"]
                            if governing_element else None),
            max_steel_element=(governing_element["element_id"]
                               if governing_element else None),
            prestress=pre_resultant,
            converged=r.converged,
            stress_plane=(r.short_term.eps0, r.short_term.kx, r.short_term.ky),
            accepted_states=dict(
                long_term=_elastic_state_result(r.long),
                instantaneous_combined=_elastic_state_result(r.short_term),
            ),
            superposition=dict(
                long_term_modular_ratio=r.long_term_modular_ratio,
                short_term_modular_ratio=r.short_term_modular_ratio,
                long_term_reduction_factor=r.long_term_reduction_factor,
                prestress_resultant=_elastic_resultant_result(
                    r.prestress_resultant
                ),
                combined_target_before_neutralisation=_elastic_resultant_result(
                    r.combined_target_before_neutralisation
                ),
                neutralising_resultant=_elastic_resultant_result(
                    r.neutralising_resultant
                ),
            ),
            elements=elements,
            concrete_corners=corners,
            stress_outputs=stress_outputs,
        )

        # Extended serviceability checks. Explicit bars take clear cover from the
        # geometry; a verified slab-density layout supplies its physical face cover
        # and entered spacing instead of treating integration points as bar axes.
        # The user-defined long-term
        # state at nl (beta/kt = 0.5/0.4) drives the cracking threshold, the
        # section properties and tension stiffening; the short-term (instantaneous)
        # state -- the total long+short load at ns (beta/kt = 1.0/0.6) -- gives the
        # short-term crack width. Crack width is reported for both loads.
        if inp["sls_phi"] > 0.0:
            phi = inp["sls_phi"]
        else:
            phi = [
                (
                    item["diameter_mm"]
                    if item.get("size_mode")
                    in {
                        rebar_table.DIAMETER_MODE,
                        rebar_table.INDEPENDENT_MODE,
                    }
                    else 0.0
                )
                for item in (inp.get("bar_elements", [])
                             + inp.get("tendon_elements", []))
            ]
        # k1 per bar: the mild reinforcement uses the selected bond value; any
        # prestressing tendons (folded into the bar set after the bars) always
        # use 1.6. Order matches sec.bar_arrays() (bars first, then tendons).
        k1_bars = [inp["sls_k1"]] * len(inp["bars"]) + [1.6] * len(inp["tendons"])
        density = inp.get("slab_density")
        physical_geometry_available = not (
            density is not None and density.get("status") == "UNVERIFIED"
        )
        physical_geometry_reason = (
            density.get("reason")
            if density is not None and not physical_geometry_available
            else None
        )
        crack_cover = None
        crack_spacing = None
        physical_spacing_points = None
        physical_spacing_groups = None
        if density is not None and density.get("status") == "VERIFIED":
            metadata = list(density.get("analysis_metadata") or [])
            if len(metadata) != len(inp["bars"]):
                physical_geometry_available = False
                physical_geometry_reason = _SLAB_DENSITY_GUIDANCE
            else:
                crack_cover = [float(item["cover_mm"]) for item in metadata]
                crack_spacing = [
                    float(item["nominal_spacing_mm"]) for item in metadata
                ]
                physical_spacing_groups = [
                    item.get("spacing_group") for item in metadata
                ]
                if inp["tendons"]:
                    rings = list(sec.integration_rings())
                    tendon_elements = list(inp.get("tendon_elements", []))
                    try:
                        tendon_cover = [
                            _slab_tendon_face_clear_cover_mm(
                                item["y"], item["diameter_mm"], rings[0]
                            )
                            for item in tendon_elements
                        ]
                    except (IndexError, KeyError, TypeError, ValueError, OverflowError):
                        physical_geometry_available = False
                        physical_geometry_reason = _SLAB_TENDON_FACE_GUIDANCE
                        tendon_cover = [0.0] * len(tendon_elements)
                    crack_cover.extend(tendon_cover)
                    crack_spacing.extend(
                        math.nan for _item in tendon_elements
                    )
                    physical_spacing_groups.extend(
                        None for _item in tendon_elements
                    )
                physical_spacing_points = [
                    (
                        float(item["x_mm"]) / _MM,
                        float(item["y_mm"]) / _MM,
                        None,
                        item.get("spacing_group"),
                    )
                    for item in density.get("physical_elements", ())
                ]
                physical_spacing_points.extend(
                    (
                        float(item["x"]),
                        float(item["y"]),
                        len(inp["bars"]) + index,
                    )
                    for index, item in enumerate(
                        inp.get("tendon_elements", [])
                    )
                )
        # Dispatch only through the immutable capability binding. Persisted labels
        # and label substrings never select an engineering route.
        ordinary_binding = design_standards.capability_binding(
            inp["sls_code"],
            design_standards.Capability.ORDINARY_CRACK_WIDTH,
        )
        ordinary_route = ordinary_binding.ordinary_crack_width_route
        if ordinary_route is None:
            raise ValueError("The selected basis has no ordinary crack-width route")
        dk_na = ordinary_route.k3_cover_dependent
        slabs_or_prestressed = (
            inp["sls_member"] == "Slab" or bool(inp["tendons"])
        )
        include_hx = (
            ordinary_route.include_hx_term_for_slabs_or_prestressed
            if slabs_or_prestressed
            else ordinary_route.include_hx_term_for_ordinary_beams
        )
        report_coarse = ordinary_route.report_coarse_system
        crack_basis = design_standards.get_design_basis(inp["sls_code"])
        # Cracking is irreversible and is triggered by the maximum load the section
        # ever sees, so the section is cracked if EITHER the sustained (long-term) or
        # the peak (total) action exceeds the cracking stress. The peak check uses
        # the combined creep state (long @ nl superposed with short @ ns), matching
        # the reported Total/RST1 stresses; a short-term action that counteracts the
        # sustained one can leave the peak uncracked while the long-term already
        # cracked, and vice versa. Report the governing (smallest lambda_cr) of the
        # two.
        # cr_l provides the long-term cracked state and the sustained cracking
        # factor; its own crack width is unused (the crack widths are computed
        # below per system), so the coarse flag here is immaterial.
        cr_l = analyse_cracking(
            sec, p_el_l, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
            fctm=inp["sls_fctm"], Es=[material.Es for material in all_laws],
            beta=0.5, kt=0.4,
            cover=crack_cover, bar_diameter=phi,
            nominal_spacing=crack_spacing,
            physical_spacing_points=physical_spacing_points,
            physical_spacing_groups=physical_spacing_groups,
            k1=k1_bars,
            physical_geometry_available=physical_geometry_available,
            physical_geometry_reason=physical_geometry_reason,
            k3_cover_dependent=dk_na, include_hx_term=include_hx,
            edition=ordinary_route.edition,
            n_mult=n_mult, prestress_stress=prestress_stress)
        sls_converged = (
            r.converged
            and cr_l.uncracked.converged
            and cr_l.cracked_state.converged
        )
        out["elastic"]["converged"] = sls_converged
        if not sls_converged:
            for output in out["elastic"]["stress_outputs"].values():
                output.update(value=None, calculation_state="INVALID")
        crk_t, lam_t, sig_t = combined_cracking(
            sec, p_el_l, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
            p_el_s, inp["Mx_el_s"], inp["My_el_s"], inp["ns"],
            fctm=inp["sls_fctm"], n_mult=n_mult, prestress_stress=prestress_stress)
        # Governing case. Its cracked state (for the reported cracked properties) is
        # the combined creep total state (r.short_term) when the peak strictly
        # governs, or the long-term cracked state when the sustained action governs.
        # Ties (e.g. no short-term load, where the peak reduces to the sustained
        # check) go to the sustained state, so a long-term-only run keeps its nl
        # cracked properties rather than the instantaneous combined state.
        if lam_t < cr_l.lambda_cr:
            cracked, lambda_cr, sigma_ct, gov_state = crk_t, lam_t, sig_t, r.short_term
        else:
            cracked, lambda_cr, sigma_ct = (cr_l.cracked, cr_l.lambda_cr,
                                            cr_l.sigma_ct)
            gov_state = cr_l.cracked_state
        # Reinforcement enters the transformed properties at n*A, or n*(Ep/Es)*A per
        # tendon via n_mult -- the same per-bar modular ratio the elastic and cracking
        # solves use, so the reported section properties are consistent with them.
        props_un = transformed_properties(sec, inp["nl"], cracked=False, n_mult=n_mult)
        props_cr = (transformed_properties(
            sec, inp["nl"], eps0=gov_state.eps0, kx=gov_state.kx, ky=gov_state.ky,
            cracked=True, n_mult=n_mult) if cracked else None)
        out["elastic"].update(
            cracked=cracked, lambda_cr=lambda_cr, sigma_ct=sigma_ct,
            fctm=inp["sls_fctm"], show_cw=inp["sls_cw"],
            props_un=_props_dict(props_un),
            props_cr=(_props_dict(props_cr) if props_cr is not None else None),
            crack=None, crack_short=None,
            crack_basis_key=crack_basis.key.value,
            crack_code=crack_basis.label,
            crack_edition=ordinary_route.edition,
            crack_member=(inp["sls_member"] if report_coarse else None),
        )
        # Crack width is its own opt-in, reported for both load cases once the
        # section has cracked. The short-term state reuses the combined creep solve
        # `r`: its instantaneous neutral axis with the displayed total steel stress
        # (s2 + RST1), so the crack-width sigma_s matches the Total column rather
        # than a raw (long+short)-at-ns solve. Cover follows the physical source
        # selected above.
        crack_evaluations = {}
        if inp["sls_cw"] and cracked:
            # Crack width uses the load-induced steel stress, so strip the locked-in
            # tendon prestress back out of the reported total (mild bars unaffected).
            cw_stress = np.asarray(r.bar_stress_total, dtype=float)
            if prestress_stress is not None:
                cw_stress = cw_stress - prestress_stress
            short_state = dataclasses.replace(r.short_term, bar_stress=cw_stress)

            reinforcement_types = (
                ["mild"] * len(inp["bars"])
                + ["prestress"] * len(inp["tendons"])
            )
            tendon_xi = (
                None
                if not inp["tendons"] or inp.get("sls_tendon_xi", 0.0) <= 0.0
                else [1.0] * len(inp["bars"])
                + [float(inp["sls_tendon_xi"])] * len(inp["tendons"])
            )

            def _cw(state, n, kt, coarse):
                return evaluate_crack_width(
                    sec,
                    state,
                    n,
                    fctm=inp["sls_fctm"],
                    Es=[material.Es for material in all_laws],
                    kt=kt,
                    cover=crack_cover,
                    bar_diameter=phi,
                    nominal_spacing=crack_spacing,
                    physical_spacing_points=physical_spacing_points,
                    physical_spacing_groups=physical_spacing_groups,
                    physical_geometry_available=physical_geometry_available,
                    physical_geometry_reason=physical_geometry_reason,
                    k1=k1_bars,
                    k3_cover_dependent=dk_na,
                    include_hx_term=include_hx,
                    coarse=coarse,
                    edition=ordinary_route.edition,
                    n_mult=n_mult,
                    reinforcement_types=reinforcement_types,
                    bond_ratio_xi=tendon_xi,
                )

            # Long-term crack width is on the cracked section under the user-entered
            # sustained action (kt = 0.4), computed directly from that state so it
            # is reported even when the long-term load alone would not cross the
            # cracking threshold. The short-term is the instantaneous total (kt = 0.6).
            long_evaluation = _cw(
                cr_l.cracked_state, inp["nl"], 0.4, False
            )
            short_evaluation = _cw(short_state, inp["ns"], 0.6, False)
            long_crack = _crack_dict(
                long_evaluation.result, bar_ids, tendon_ids
            )
            short_crack = _crack_dict(
                short_evaluation.result, bar_ids, tendon_ids
            )
            crack_evaluations.update(
                {
                    "Long-term": {
                        "status": long_evaluation.status,
                        "reason": long_evaluation.reason,
                        "result": long_crack,
                    },
                    "Short-term": {
                        "status": short_evaluation.status,
                        "reason": short_evaluation.reason,
                        "result": short_crack,
                    },
                }
            )
            out["elastic"].update(
                crack=long_crack,
                crack_short=short_crack,
            )
            # The DK NA reports the coarse crack system alongside the fine one, for
            # both load cases (four crack widths in total).
            if report_coarse:
                long_coarse_evaluation = _cw(
                    cr_l.cracked_state, inp["nl"], 0.4, True
                )
                short_coarse_evaluation = _cw(
                    short_state, inp["ns"], 0.6, True
                )
                long_coarse_crack = _crack_dict(
                    long_coarse_evaluation.result, bar_ids, tendon_ids
                )
                short_coarse_crack = _crack_dict(
                    short_coarse_evaluation.result, bar_ids, tendon_ids
                )
                crack_evaluations = {
                    "Long-term (fine)": crack_evaluations["Long-term"],
                    "Short-term (fine)": crack_evaluations["Short-term"],
                    "Long-term (coarse)": {
                        "status": long_coarse_evaluation.status,
                        "reason": long_coarse_evaluation.reason,
                        "result": long_coarse_crack,
                    },
                    "Short-term (coarse)": {
                        "status": short_coarse_evaluation.status,
                        "reason": short_coarse_evaluation.reason,
                        "result": short_coarse_crack,
                    },
                }
                out["elastic"].update(
                    crack_coarse=long_coarse_crack,
                    crack_short_coarse=short_coarse_crack,
                )
        eout = out["elastic"]
        if report_coarse:
            long_term_crack_cases = {
                name: crack_evaluations.get(name)
                for name in (
                    "Long-term (fine)",
                    "Long-term (coarse)",
                )
            }
            short_term_crack_cases = {
                name: crack_evaluations.get(name)
                for name in (
                    "Short-term (fine)",
                    "Short-term (coarse)",
                )
            }
        else:
            long_term_crack_cases = {
                name: crack_evaluations.get(name)
                for name in ("Long-term",)
            }
            short_term_crack_cases = {
                name: crack_evaluations.get(name)
                for name in ("Short-term",)
            }
        eout["crack_output"] = sls_core.crack_outputs(
            long_term_crack_cases,
            short_term_crack_cases,
            valid=eout["converged"],
            requested=bool(inp["sls_cw"]),
            long_term_criterion_mm=inp.get(
                LONG_TERM_PERMITTED_CRACK_WIDTH_KEY, 0.0
            ),
            short_term_criterion_mm=inp.get(
                SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY, 0.0
            ),
            long_term_criterion_source=inp.get(
                "sls_long_term_permitted_crack_width_source"
            ),
            short_term_criterion_source=inp.get(
                "sls_short_term_permitted_crack_width_source"
            ),
        )
    if inp.get("minimum_reinforcement_on"):
        if inp.get("detailing_edition") == detailing.EC2_2023:
            _warm_solver()
        out["minimum_reinforcement"] = detailing.minimum_reinforcement(
            inp["section"],
            inp.get("bar_elements") or [],
            inp.get("bar_materials") or [],
            inp["concrete"],
            edition=inp["detailing_edition"],
            fctm_mpa=inp["sls_fctm"],
            n_ed_tension_kn=inp["P_pl"],
            mx_ed_knm=inp["Mx_pl"],
            my_ed_knm=inp["My_pl"],
            member_type=inp.get(
                "detailing_member_type", detailing.MEMBER_BEAM
            ),
            cut_direction=inp.get(
                "detailing_cut_direction", detailing.CUT_TRANSVERSE
            ),
        )
    _run_capacity_checks(inp, out)
    if inp.get("transverse_detailing_on"):
        out["transverse_reinforcement"] = _transverse_detailing_result(inp, out)
    return out


def _run_fatigue_or_invalid(inp):
    """Run fatigue when valid; otherwise return immutable INVALID evidence.

    Fatigue is independent of the requested plastic/elastic/capacity checks.
    Invalid fatigue input therefore cannot suppress otherwise valid results.
    """

    errors = fatigue_analysis.validation_errors(inp)
    return (
        fatigue_analysis.invalid_result(inp, errors)
        if errors
        else fatigue_analysis.run_analysis(inp)
    )


_HEIGHTENED_POSITIVE_INPUTS = (
    (
        "sls_heightened_effective_tensile_strength_mpa",
        "Effective tensile strength",
    ),
    (
        HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY,
        "Heightened permitted crack width",
    ),
    (
        "sls_heightened_fine_effective_tension_area_mm2",
        "Fine-system effective tension area",
    ),
    (
        "sls_heightened_coarse_effective_tension_area_mm2",
        "Coarse-system effective tension area",
    ),
)
_HEIGHTENED_BOOLEAN = EngineerMessage(
    "HEIGHTENED-ENABLED",
    "Choose whether heightened crack control is enabled",
)
_HEIGHTENED_ELASTIC_MODE = EngineerMessage(
    "HEIGHTENED-ELASTIC-MODE",
    "Enable Elastic analysis before checking heightened crack control",
)
_HEIGHTENED_DESIGN_BASIS = EngineerMessage(
    "HEIGHTENED-DESIGN-BASIS",
    "Select the first-generation DK NA:2024 design basis for heightened crack control",
)
_HEIGHTENED_SURFACE = EngineerMessage(
    "HEIGHTENED-SURFACE",
    "Select ribbed or smooth reinforcement for heightened crack control",
)
_HEIGHTENED_POSITIVE_MESSAGES = {
    "sls_heightened_effective_tensile_strength_mpa": EngineerMessage(
        "HEIGHTENED-TENSILE-STRENGTH",
        "Enter a positive finite effective tensile strength",
    ),
    HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY: EngineerMessage(
        "HEIGHTENED-CRACK-LIMIT",
        "Enter a positive finite heightened crack-width limit",
    ),
    "sls_heightened_fine_effective_tension_area_mm2": EngineerMessage(
        "HEIGHTENED-FINE-AREA",
        "Enter a positive finite fine-system effective tension area",
    ),
    "sls_heightened_coarse_effective_tension_area_mm2": EngineerMessage(
        "HEIGHTENED-COARSE-AREA",
        "Enter a positive finite coarse-system effective tension area",
    ),
}
_HEIGHTENED_REFERENCE_REQUIRED = EngineerMessage(
    "HEIGHTENED-REFERENCE-REQUIRED",
    "Enable crack-width calculation for at least one Elastic case",
)
_HEIGHTENED_REFERENCE_SELECT = EngineerMessage(
    "HEIGHTENED-REFERENCE-SELECT",
    "Select one crack-enabled Elastic case as the heightened reference",
)
_HEIGHTENED_REFERENCE_DISPLAY = EngineerMessage(
    "HEIGHTENED-REFERENCE-CASE",
    "Review the Elastic reference case for heightened crack control",
)


def _heightened_crack_control_validation_errors(inp):
    """Validate the separate DK calculation without evaluating its formula."""

    enabled = inp.get("sls_heightened_on", False)
    if type(enabled) is not bool:
        return [_HEIGHTENED_BOOLEAN]
    if not enabled:
        return []

    errors = []
    if inp.get("mode") not in {"Elastic", "Both"}:
        errors.append(_HEIGHTENED_ELASTIC_MODE)
    try:
        design_standards.capability_binding(
            inp.get("sls_code"),
            design_standards.Capability.HEIGHTENED_CRACK_CONTROL,
        )
    except ValueError:
        errors.append(_HEIGHTENED_DESIGN_BASIS)
    if inp.get("sls_heightened_reinforcement_surface") not in {
        "ribbed",
        "smooth",
    }:
        errors.append(_HEIGHTENED_SURFACE)
    for key, _label in _HEIGHTENED_POSITIVE_INPUTS:
        value = inp.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            number = math.nan
        if (
            isinstance(value, bool)
            or type(value).__name__ == "bool_"
            or not math.isfinite(number)
            or number <= 0.0
        ):
            errors.append(_HEIGHTENED_POSITIVE_MESSAGES[key])
    try:
        records = case_analysis.case_records(inp, "elastic")
        names = heightened_adapter.crack_enabled_case_names(records)
    except Exception as exc:
        errors.append(engineer_messages.resolve(
            exc,
            fallback=_HEIGHTENED_REFERENCE_DISPLAY,
            context="heightened crack-control reference case",
        ))
    else:
        selected = inp.get("sls_heightened_reference_case")
        if not names:
            errors.append(_HEIGHTENED_REFERENCE_REQUIRED)
        elif len(names) > 1 and (
            not isinstance(selected, str) or selected not in names
        ):
            errors.append(_HEIGHTENED_REFERENCE_SELECT)
    return errors


def _heightened_crack_control_payload(inp, analysis_result):
    """Bind, derive and evaluate the dual family from retained case evidence."""

    reference_name = heightened_adapter.resolve_reference_case_name(
        case_analysis.case_records(inp, "elastic"),
        inp.get("sls_heightened_reference_case"),
    )
    reference = next(
        (
            entry
            for entry in analysis_result.get("elastic_cases", [])
            if entry.get("name") == reference_name
        ),
        None,
    )
    if not isinstance(reference, dict):
        raise ValueError(
            "The selected heightened reference case has no current calculated result"
        )
    derived = heightened_adapter.derive_heightened_reinforcement(
        reference,
        bar_diameter_override_mm=inp.get("sls_phi", 0.0),
    )
    result = heightened_crack_control_core.calculate_dual_heightened_crack_control(
        basis=inp["sls_code"],
        reinforcement_surface=inp["sls_heightened_reinforcement_surface"],
        bar_diameter_mm=derived.bar_diameter_mm,
        effective_tensile_strength_mpa=inp[
            "sls_heightened_effective_tensile_strength_mpa"
        ],
        reinforcement_modulus_mpa=derived.reinforcement_modulus_mpa,
        permitted_crack_width_mm=inp[HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY],
        fine_effective_tension_area_mm2=inp[
            "sls_heightened_fine_effective_tension_area_mm2"
        ],
        coarse_effective_tension_area_mm2=inp[
            "sls_heightened_coarse_effective_tension_area_mm2"
        ],
        provided_reinforcement_area_mm2=(
            derived.provided_reinforcement_area_mm2
        ),
    )
    branch_payloads = {}
    for branch_name in ("fine", "coarse"):
        branch = getattr(result, branch_name)
        branch_payload = dataclasses.asdict(branch)
        branch_payload.update(
            basis_key=branch.basis_key.value,
            crack_system=branch.crack_system.value,
            reinforcement_surface=branch.reinforcement_surface.value,
            status=branch.status.value,
        )
        branch_payloads[branch_name] = branch_payload
    governing = branch_payloads[result.governing_crack_system.value]
    payload = {
        **governing,
        "fine": branch_payloads["fine"],
        "coarse": branch_payloads["coarse"],
        "governing_crack_system": result.governing_crack_system.value,
        "governing_required_reinforcement_area_mm2": (
            result.governing_required_reinforcement_area_mm2
        ),
        "governing_comparison_ratio": result.governing_comparison_ratio,
        "governing_status": result.governing_status.value,
        "reference_case_id": derived.reference_case_id,
        "ordinary_crack_branch": derived.ordinary_crack_branch,
        "diameter_source": derived.diameter_source,
        "diameter_governing_element_ids": list(
            derived.diameter_governing_element_ids
        ),
        "modulus_governing_material_ids": list(
            derived.modulus_governing_material_ids
        ),
        "contributions": [
            dataclasses.asdict(item) for item in derived.contributions
        ],
    }
    return payload


def _attach_heightened_crack_control(inp, result):
    """Attach exactly one section-level heightened result when requested."""

    if inp.get("sls_heightened_on"):
        result["heightened_crack_control"] = (
            _heightened_crack_control_payload(inp, result)
        )


def _clear_spacing_result(inp):
    """Use nominal slab axes, never density-analysis points, for detailing."""

    density = inp.get("slab_density")
    if density is not None and density.get("status") == "UNVERIFIED":
        return {
            "status": "NOT ASSESSED",
            "edition": inp["detailing_edition"],
            "clause": (
                "11.2(2)"
                if inp["detailing_edition"] == detailing.EC2_2023
                else "8.2(2)"
            ),
            "d_upper_mm": float(inp["detailing_d_upper"]),
            "include_tendons": bool(
                inp.get("detailing_include_tendons", False)
            ),
            "pairs": [],
            "governing": None,
            "reason": density.get("reason") or _SLAB_DENSITY_GUIDANCE,
            "limitations": [
                "Reapply the slab layout or define explicit bars before "
                "assessing clear spacing."
            ],
        }
    elements = list(inp.get("bar_elements") or [])
    if density is not None and density.get("status") == "VERIFIED":
        elements = list(density.get("physical_elements") or [])
    elements.extend(list(inp.get("tendon_elements") or []))
    return detailing.clear_spacing(
        elements,
        d_upper_mm=inp["detailing_d_upper"],
        edition=inp["detailing_edition"],
        include_tendons=inp.get("detailing_include_tendons", False),
    )


def run_analysis(
    inp,
    *,
    reuse_plastic=None,
    reuse_elastic=None,
    reuse_plastic_cases=None,
    reuse_plastic_bending_cases=None,
    reuse_elastic_cases=None,
    reuse_fatigue=None,
):
    """Run every current named action and enabled calculation."""
    sweep_error = case_analysis.plastic_sweep_error(inp)
    if sweep_error is not None:
        raise engineer_messages.EngineerValidationError(sweep_error)
    heightened_errors = _heightened_crack_control_validation_errors(inp)
    if heightened_errors:
        raise engineer_messages.EngineerValidationError(heightened_errors[0])
    if (inp["section"] is None or inp.get("geometry_error")
            or inp.get("void_error")
            or inp.get("steel_error") or inp.get("material_error")):
        return {}
    shared_results = _section_and_material_results(inp)
    elastic_solver_inputs = _elastic_solver_inputs(inp, shared_results)
    if "plastic_cases" not in inp and "elastic_cases" not in inp:
        result = _run_single_analysis(
            inp,
            reuse_plastic=reuse_plastic,
            reuse_elastic=reuse_elastic,
            elastic_solver_inputs=elastic_solver_inputs,
            shared_results=shared_results,
        )
        if inp.get("clear_spacing_on"):
            result["clear_spacing"] = _clear_spacing_result(inp)
        if inp.get("fatigue_on"):
            result["fatigue"] = (
                reuse_fatigue
                if reuse_fatigue is not None
                else _run_fatigue_or_invalid(inp)
            )
        result.update(shared_results)
        _attach_heightened_crack_control(inp, result)
        result["worked_example_selection"] = (
            presentation.worked_example_selection(inp, result)
        )
        return result

    def _runner(case_inp, *, reuse_plastic=None):
        return _run_single_analysis(
            case_inp,
            reuse_plastic=reuse_plastic,
            elastic_solver_inputs=elastic_solver_inputs,
            shared_results=shared_results,
        )

    result = case_analysis.run_case_tables(
        inp,
        _runner,
        reuse_plastic=reuse_plastic_cases,
        reuse_plastic_bending=reuse_plastic_bending_cases,
        reuse_elastic=reuse_elastic_cases,
    )
    if inp.get("clear_spacing_on"):
        result["clear_spacing"] = _clear_spacing_result(inp)
    if inp.get("fatigue_on"):
        result["fatigue"] = (
            reuse_fatigue
            if reuse_fatigue is not None
            else _run_fatigue_or_invalid(inp)
        )
    result.update(shared_results)
    _attach_heightened_crack_control(inp, result)
    result["worked_example_selection"] = (
        presentation.worked_example_selection(inp, result)
    )
    return result


def _run_uniaxial_capacity_checks(inp, out):
    """Shear, torsion and the combined M-V-T checks for ``inp``; mutates ``out``.

    Runs after the independent plastic and elastic analyses. Reads ``inp`` and the
    already-built ``out["plastic"/"shear"/"torsion"]``; writes ``out["shear"]``,
    ``out["torsion"]`` and ``out["combined"]``. One member strut angle serves shear
    AND torsion (EN 1992-1-1 6.3.2(2)), chosen to minimise the governing utilisation
    -- the sizeable strut-angle pass that used to sit inline in run_analysis.
    """
    # Build angle-independent contexts in the headless calculation layer. The
    # Streamlit app retains the shared member-angle scan and presentation only.
    n_prestress = capacity.prestress_axial(inp)
    n_ed_comp = -inp["P_pl"] + n_prestress
    shear_payload, link_ctx = capacity.build_shear_context(
        inp, n_prestress, n_ed_comp
    )
    if shear_payload is not None:
        out["shear"] = shear_payload
    tors_ctx = capacity.build_torsion_context(inp, n_ed_comp)

    # ---- Member strut angle (EN 1992-1-1 6.3.2(2)) ----------------------------
    # One strut angle serves shear AND torsion (the same web struts carry both).
    # It is chosen to MINIMISE THE GOVERNING UTILISATION over every reported check
    # that depends on it: the stirrup checks relax with a flatter strut while the
    # crushing checks and the longitudinal-chord demand (MEd + 0.5*VEd*cot*z
    # [+ Ftd,T*z/2] vs MRd) grow, so the optimum is load-dependent -- unlike the
    # old per-action angle, which maximised each resistance alone and therefore sat
    # at the band edge regardless of VEd/MEd/NEd. The chord enters the objective as
    # the SAME capped utilisation the app reports (6.2.3(7)), so the chosen angle
    # can never fail a reported check that another admissible angle would pass.
    # Only LIVE checks constrain the angle -- valid AND loaded: an invalid tube
    # (util = inf at every angle) or a companion with zero load must not drag the
    # angle of a valid check. With no live checks (capacity-only runs) the legacy
    # resistance-maximising angles are kept.
    if link_ctx is not None or tors_ctx is not None:
        v_ed_s = link_ctx["v_ed"] if link_ctx is not None else 0.0
        t_ed_s = tors_ctx["t_ed"] if tors_ctx is not None else 0.0
        # Validity probes: a broken links result (no stirrup area / degenerate web)
        # or an invalid tube gives infinite utilisations at EVERY angle, which would
        # otherwise tie the scan and pin the angle at the band edge.
        lk_probe = (link_ctx["build"](link_ctx["cot_min"], link_ctx["cot_min"])
                    if link_ctx is not None else None)
        links_valid = bool(
            lk_probe is not None
            and lk_probe["valid"]
            and (lk_probe.get("vrd_s") or 0.0) > 0.0
            and (lk_probe.get("vrd_max") or 0.0) > 0.0
        )
        tors_valid = bool(
            tors_ctx is not None
            and tors_ctx["closed_links_present"]
            and tors_ctx["asw_over_s_t"] > 0.0
            and all(tb["valid"] for tb in tors_ctx["subtubes"])
        )
        shear_live = links_valid and v_ed_s > 0.0
        tors_live = tors_valid and t_ed_s > 0.0

        # Longitudinal-chord parameters: the shear tension face's applied moment and
        # pure-axis capacity (the B1 machinery), available when the plastic
        # utilisation was computed and the links provide a lever arm.
        pl = out.get("plastic")
        chord_faces = []           # shear-axis chord faces (see below)
        chord_off_faces = []       # off-axis chord faces (both), built when torsion is live
        if links_valid and pl is not None and pl.get("util") is not None:
            l_axis, tlow = link_ctx["axis"], link_ctx["tension_low"]
            m_signed = inp["Mx_pl"] if l_axis == "x" else inp["My_pl"]
            off_signed = inp["My_pl"] if l_axis == "x" else inp["Mx_pl"]
            off_max = pl["max_my"] if l_axis == "x" else pl["max_mx"]
            off_min = pl.get("min_my" if l_axis == "x" else "min_mx", -off_max)
            off_cap = off_max if off_signed >= 0.0 else abs(off_min)
            off_util = (abs(off_signed) / off_cap if off_cap > 0.0
                        else (math.inf if off_signed else 0.0))
            _, scx, scy = capacity.gross_area_centroid(
                inp["outer"], inp["holes"]
            )
            s_centroid = scy if l_axis == "x" else scx
            # Shear-axis chord: MRd is CONDITIONAL on the coexisting off-axis moment
            # (the M-M envelope point carrying off_signed) -- the pure-axis capacity
            # overstates what the chord can lean on under biaxial bending. The
            # flexural shear-TENSION face carries the shear shift dFtd; when torsion
            # is live the OPPOSITE (compression) face also carries the torsion
            # longitudinal share (no shear shift, tensile round the whole tube), so
            # it is built too and the GOVERNING face reported (it can govern on a
            # section with asymmetric steel). The tension face keeps the legacy
            # fallback (pure-axis then sweep extremum) so a failed conditional solve
            # still reports; the torsion-only face is only used on an honest solve.
            shear_faces = [(tlow, True)]
            if tors_live:
                shear_faces.append((not tlow, False))
            for f_tlow, gets_shift in shear_faces:
                m_ed_f = combined.chord_applied_moment(m_signed, f_tlow)
                m_rd_f, cond_f = _shear_face_mrd(inp, l_axis, f_tlow, m_off=off_signed)
                if gets_shift:
                    if not cond_f and m_rd_f <= 0.0:
                        max_m = pl["max_mx"] if l_axis == "x" else pl["max_my"]
                        min_m = pl.get("min_mx" if l_axis == "x" else "min_my", -max_m)
                        m_rd_f = max_m if f_tlow else abs(min_m)
                    if not (m_rd_f > 0.0 or cond_f):
                        continue
                    z_f_mm, z_f_src = link_ctx["z_mm"], link_ctx["z_src"]
                else:
                    if not cond_f:
                        continue
                    _, s_cg = shear.tension_reinforcement(inp["bars"], l_axis,
                                                          f_tlow, s_centroid)
                    d_f = shear.effective_depth(inp["outer"], l_axis, f_tlow, s_cg)
                    z_f_mm, z_f_src = _shear_lever_arm(inp, l_axis, f_tlow, d_f)
                    if z_f_mm is None or z_f_mm <= 0.0:
                        continue
                chord_faces.append(
                    dict(m_ed=m_ed_f, m_rd=m_rd_f, z_m=z_f_mm / 1000.0,
                         z_src=z_f_src, axis=l_axis, tension_low=f_tlow,
                         off_util=off_util, m_off=off_signed, conditional=cond_f,
                         gets_shift=gets_shift))
            # Off-axis chord(s): with torsion live, the OTHER axis' tension chords
            # carry their bending tension plus a share of the distributed torsion
            # longitudinal force. The torsion force is tensile round the whole tube
            # perimeter, so it tensions BOTH off-axis faces -- both are built and the
            # governing one reported (on a section with asymmetric steel the face the
            # bending does not tension can still govern under the torsion share).
            # Each face's capacity is conditional on the shear-axis moment, and only
            # the honest conditional capacity is used (a failed solve leaves no
            # defensible MRd, so that face is simply not checked). Single-tube
            # sections only: on a compound section the torsion steel is per sub-tube,
            # so no single tube bounds the off-axis face.
            if (chord_faces and tors_live
                    and not tors_ctx.get("subdivide", False)):
                o_axis = "y" if l_axis == "x" else "x"
                _, ocx, ocy = capacity.gross_area_centroid(
                    inp["outer"], inp["holes"]
                )
                o_centroid = ocy if o_axis == "x" else ocx
                for o_tlow in (True, False):
                    m_ed_o = combined.chord_applied_moment(off_signed, o_tlow)
                    m_rd_o, o_cond = _shear_face_mrd(inp, o_axis, o_tlow,
                                                     m_off=m_signed)
                    if not o_cond:
                        continue
                    # Lever arm about the off axis: the exact face-aligned Plastic
                    # internal lever arm, like the reinforced-shear z.
                    _, o_cg = shear.tension_reinforcement(inp["bars"], o_axis,
                                                          o_tlow, o_centroid)
                    d_o = shear.effective_depth(inp["outer"], o_axis, o_tlow, o_cg)
                    z_o_mm, z_o_src = _shear_lever_arm(inp, o_axis, o_tlow, d_o)
                    if z_o_mm is None or z_o_mm <= 0.0:
                        continue
                    chord_off_faces.append(
                        dict(m_ed=m_ed_o, m_rd=m_rd_o, z_m=z_o_mm / 1000.0,
                             z_src=z_o_src, axis=o_axis, tension_low=o_tlow,
                             m_off=m_signed, conditional=True))

        # The scan band comes from the one physical compression-strut input. A
        # companion that is invalid or carries no load does not join the objective,
        # but shear and torsion no longer have separate ranges to reconcile.
        band = None
        if shear_live and tors_live:
            band = (link_ctx["cot_min"], link_ctx["cot_max"])
        elif shear_live:
            band = (link_ctx["cot_min"], link_ctx["cot_max"])
        elif tors_live:
            band = (tors_ctx["tcot_min"], tors_ctx["tcot_max"])

        @functools.lru_cache(maxsize=4096)
        def _snap(cot):
            """Every strut-angle-dependent resistance at one cot."""
            s = {}
            if link_ctx is not None:
                s["lk"] = link_ctx["build"](cot, cot)
            if tors_ctx is not None:
                tk = dict(tors_ctx["_tk"], cot_min=cot, cot_max=cot)
                s["subs"] = tuple(_tube_torsion(tb, te, **tk)
                                  for tb, te in zip(tors_ctx["subtubes"],
                                                    tors_ctx["ted_parts"]))
            return s

        def _ftd_t_at(cot):
            """Torsion longitudinal force on the web chord (kN) at one cot."""
            if not tors_live:
                return 0.0
            web = _snap(cot)["subs"][0]
            return web["asl_req"] * tors_ctx["fyd_long"] / 1000.0

        links_model_2023 = bool(
            link_ctx is not None and link_ctx.get("model_2023")
        )

        def _ftd_v_at(cot):
            """Additional longitudinal shear force on the tension chord (kN)."""
            factor = 1.0 if links_model_2023 else 0.5
            return factor * v_ed_s * cot

        utils = []
        objective_labels = []

        def _add_angle_objective(label, evaluator):
            objective_labels.append(label)
            utils.append(evaluator)

        if shear_live:
            _add_angle_objective(
                "shear link yielding",
                lambda c: combined.ratio(v_ed_s, _snap(c)["lk"]["vrd_s"]),
            )
            _add_angle_objective(
                "shear strut crushing",
                lambda c: combined.ratio(v_ed_s, _snap(c)["lk"]["vrd_max"]),
            )
        if tors_live:
            for i in range(len(tors_ctx["subtubes"])):
                _add_angle_objective(
                    f"torsion sub-tube {i + 1}",
                    lambda c, i=i: _snap(c)["subs"][i]["util"],
                )
        if links_valid and tors_live and tors_ctx["asw_over_s_t"] > 0.0:
            # The one closed stirrup carries shear AND the web's torsion share (the
            # transverse check); the web struts crush under both (6.29).
            def _shared_stirrup(c):
                sf = (0.0 if v_ed_s <= link_ctx["vrd_c"]
                      else combined.ratio(v_ed_s, _snap(c)["lk"]["vrd_s"]))
                tf = combined.ratio(_snap(c)["subs"][0]["t_ed"],
                                    _snap(c)["subs"][0]["trd_s"])
                return sf + tf

            def _crush_629(c):
                snap = _snap(c)
                return combined.crushing_interaction(
                    snap["subs"][0]["t_ed"], snap["subs"][0]["trd_max"],
                    v_ed_s, snap["lk"]["vrd_max"])
            _add_angle_objective("shared closed stirrup", _shared_stirrup)
            _add_angle_objective("shared shear-torsion strut", _crush_629)
        for _cf in chord_faces:
            # The objective sees exactly the reported chord utilisation. The 2005
            # shear shift is capped per 6.2.3(7); the 2023 NVd force from (8.50) is
            # not capped because Sector does not establish the support/load-specific
            # condition in (8.53).
            if _cf["m_rd"] > 0.0 and (shear_live or tors_live):
                face = "negative" if _cf["tension_low"] else "positive"
                _add_angle_objective(
                    f"{_cf['axis']}-axis {face} longitudinal chord",
                    lambda c, f=_cf: combined.longitudinal_check(
                        f["m_ed"], f["m_rd"],
                        _ftd_v_at(c) if f["gets_shift"] else 0.0,
                        _ftd_t_at(c), f["z_m"],
                        cap_shear_force=not links_model_2023,
                    )["util"],
                )
        for _ocf in chord_off_faces:
            # Each off-axis face depends on the angle only through Ftd,T; both join
            # the objective (m_rd > 0) so the optimiser and the reported governing
            # verdict agree. A zero-capacity face is kept out (util = inf at every
            # angle would tie the scan).
            if _ocf["m_rd"] > 0.0 and tors_live:
                face = "negative" if _ocf["tension_low"] else "positive"
                _add_angle_objective(
                    f"{_ocf['axis']}-axis {face} off-axis chord",
                    lambda c, f=_ocf: combined.longitudinal_check(
                        f["m_ed"], f["m_rd"], 0.0, _ftd_t_at(c), f["z_m"]
                    )["util"],
                )
        cot_star = None
        member_angle_selection = None
        if band is not None and utils:
            angle_result = combined.governing_strut_result(
                utils, band[0], band[1]
            )
            cot_star = angle_result.cot
            member_angle_selection = dataclasses.asdict(angle_result)
            member_angle_selection["objective_labels"] = tuple(objective_labels)
            member_angle_selection["governing_objectives"] = tuple(
                objective_labels[index]
                for index in angle_result.governing_component_indices
            )
        # One label for how the member angle was chosen, reused by every payload:
        #   utilisation -> a live load drove the minimax choice (cot_star found);
        #   resistance  -> no live transverse load, so the capacity result uses its
        #                  resistance-optimum angle (nothing to optimise).
        theta_mode_str = (
            "utilisation" if cot_star is not None else "resistance"
        )

        # ---- torsion payload at the member angle (or the shared band when no load
        # drives the choice) ----
        if tors_ctx is not None:
            t_ed = tors_ctx["t_ed"]
            subdivide = tors_ctx["subdivide"]
            tk = tors_ctx["_tk"]
            # Pin to the member angle only when torsion is a LIVE participant. A dead
            # companion (TEd = 0) does not join the shared-angle objective and remains
            # at its resistance optimum within the same user-entered range.
            if cot_star is not None and tors_live:
                tk = dict(tk, cot_min=cot_star, cot_max=cot_star)
            sub_res = [_tube_torsion(tb, te, **tk)
                       for tb, te in zip(tors_ctx["subtubes"], tors_ctx["ted_parts"])]
            governing_sub = None
            if subdivide:
                for r, c, dims in zip(sub_res, tors_ctx["consts"],
                                      tors_ctx["sub_dims"]):
                    r["stiffness"] = c
                    (r["x_mm"], r["y_mm"],
                     r["b_mm"], r["h_mm"]) = dims
                tube_valid = all(r["tube_valid"] for r in sub_res)
                transverse_resistance_assessed = all(
                    r["transverse_resistance_assessed"] for r in sub_res
                )
                valid = bool(tube_valid and transverse_resistance_assessed)
                trd = sum(r["trd"] for r in sub_res) if valid else None
                asl_req = sum(r["asl_req"] for r in sub_res)
                primary = sub_res[0]
                tube_main = primary["tube"]
                # Governing = the WORST sub-tube (each carries its stiffness share).
                if valid:
                    governing_sub = max(
                        range(len(sub_res)),
                        key=lambda i: sub_res[i]["util"],
                    )
                    util_t = sub_res[governing_sub]["util"]
                else:
                    governing_sub = None
                    util_t = None
            else:
                primary = sub_res[0]
                sub_res = None
                trd, asl_req = primary["trd"], primary["asl_req"]
                tube_main = tors_ctx["tube"]
                tube_valid = primary["tube_valid"]
                transverse_resistance_assessed = primary[
                    "transverse_resistance_assessed"
                ]
                valid = bool(tube_valid and transverse_resistance_assessed)
                util_t = primary["util"] if valid else None
            assessment_reason = (
                None
                if transverse_resistance_assessed
                else primary["assessment_reason"]
            )
            reason = (
                tube_main.get("reason")
                if not tube_valid
                else assessment_reason
            )
            required_by_tube = tuple(
                item["asl_req"] for item in (sub_res or [primary])
            )
            longitudinal_assessment = (
                capacity.torsion_longitudinal_assessment(
                    inp,
                    required_by_tube,
                    resistance_assessed=valid,
                )
            )
            resistance_status = (
                "NOT ASSESSED"
                if not valid or util_t is None
                else "PASS"
                if math.isfinite(util_t) and util_t <= 1.0
                else "FAIL"
            )
            overall_status = capacity.aggregate_assessment_status((
                resistance_status,
                longitudinal_assessment["status"],
            ))
            overall_ok = (
                True
                if overall_status == "PASS"
                else False
                if overall_status == "FAIL"
                else None
            )
            overall_reason = (
                reason
                if not valid
                else capacity.TORSION_RESISTANCE_EXCEEDED
                if resistance_status == "FAIL"
                else longitudinal_assessment["reason"]
            )
            tcode = tors_ctx["tcode"]
            tcot_min, tcot_max = tors_ctx["tcot_min"], tors_ctx["tcot_max"]
            lo_t, hi_t = tcode.shear_cot_min_limit, tcode.shear_cot_max_limit
            torsion_out_of_limits = bool(
                tcot_min < lo_t - 1e-9 or tcot_max > hi_t + 1e-9
            )
            out["torsion"] = dict(
                tube=tube_main, trd_s=primary["trd_s"], trd_max=primary["trd_max"],
                trd=trd, trd_c=primary["trd_c"], cot=primary["cot"],
                theta_deg=primary["theta_deg"], util=util_t, asl_req=asl_req,
                t_ed=t_ed, fcd=tors_ctx["fcd"], fywd=tors_ctx["fywd_t"],
                fyd_long=tors_ctx["fyd_long"], nu=primary["nu"],
                alpha_cw=tors_ctx["alpha_cw"], fctd=tors_ctx["fctd"],
                fctk_005=tors_ctx["fctk_005"],
                gamma_c=tors_ctx["gamma_c"], gamma_ct=tors_ctx["gamma_ct"],
                gamma_s=tors_ctx["gamma_s"],
                nu_v_detailing=tors_ctx["nu_detail_applied"],
                sigma_cp=tors_ctx["sigma_cp"], n_prestress=n_prestress,
                asw_t=tors_ctx["asw_t"], asw_over_s=tors_ctx["asw_over_s_t"],
                dia=inp["shear_link_dia"], s=inp["shear_link_s"], cot_min=tcot_min,
                cot_max=tcot_max, method=inp["torsion_method"],
                governs=primary["governs"], valid=valid,
                tube_valid=tube_valid,
                closed_links_present=tors_ctx["closed_links_present"],
                transverse_resistance_assessed=(
                    transverse_resistance_assessed
                ),
                # Compatibility alias for retained schema-27 result consumers.
                full_resistance_assessed=transverse_resistance_assessed,
                assessment_reason=assessment_reason,
                resistance_status=resistance_status,
                longitudinal_assessment=longitudinal_assessment,
                assessment_status=overall_status,
                assessment_ok=overall_ok,
                overall_reason=overall_reason,
                resistance_selection=primary["resistance_selection"],
                reason=reason, cot_limit_lo=lo_t, cot_limit_hi=hi_t,
                out_of_limits=torsion_out_of_limits,
                subdivided=subdivide, subtubes=sub_res, primary=primary,
                governing_sub=governing_sub,
                compound_detected=tors_ctx["compound_detected"],
                subdivision_requested=tors_ctx["subdivision_requested"],
                subdivision_valid=tors_ctx["subdivision_valid"],
                subdivision_reason=tors_ctx["subdivision_reason"],
                theta_mode=(
                    theta_mode_str
                    if transverse_resistance_assessed and tors_live
                    else (
                        "resistance"
                        if transverse_resistance_assessed
                        else "transparency"
                    )
                ),
                torque_distribution=tors_ctx["torque_distribution"],
                member_angle_selection=member_angle_selection)

        # ---- links payload at the member angle ----
        if link_ctx is not None:
            v_ed = link_ctx["v_ed"]
            # Pin to the member angle only when shear is a LIVE participant. A dead
            # companion (VEd = 0) remains at its resistance optimum within the same
            # user-entered range.
            if cot_star is not None and shear_live:
                lk = link_ctx["build"](cot_star, cot_star)
            else:
                lk = link_ctx["build"](link_ctx["cot_min"], link_ctx["cot_max"])
            util_l = (
                v_ed / lk["vrd"]
                if lk.get("valid") and (lk.get("vrd") or 0.0) > 0.0
                else None
            )
            # Extra longitudinal force from shear: 2005 delta_Ftd = 0.5 VEd cot
            # theta; 2023 NVd = |VEd| cot theta (8.50).
            longitudinal_shear_force = (
                (1.0 if link_ctx.get("model_2023") else 0.5)
                * v_ed * lk["cot"]
                if lk["valid"] else None
            )
            delta_ftd = (
                None if link_ctx.get("model_2023") or not lk["valid"]
                else longitudinal_shear_force
            )
            angle_limits = link_ctx["angle_limits"]
            lo, hi = angle_limits["minimum"], angle_limits["maximum"]
            links_out_of_limits = bool(
                link_ctx["cot_min"] < lo - 1e-9
                or link_ctx["cot_max"] > hi + 1e-9
            )
            # The reported longitudinal-chord check (capped per 6.2.3(7)), on the
            # shear tension face; the torsion term is the web tube's share (zero
            # without torsion). Shown in the Shear view and reused by the combined
            # view, so both present the same numbers.
            lchk = None
            ochk = None
            lchecks = []
            ochecks = []
            off_not_evaluated = None
            if chord_faces and lk["valid"]:
                # The torsion term comes from the BUILT torsion payload (the web
                # tube's Asl at its final angle).
                p_web = out.get("torsion", {}).get("primary")
                ftd_t_star = (p_web["asl_req"] * tors_ctx["fyd_long"] / 1000.0
                              if (p_web is not None and tors_live) else 0.0)
                # Why no off-axis chord check accompanies this one (so the views and
                # report can disclose it rather than silently drop the torsion share
                # on the off-axis face, as the pre-v0.78 warning always did):
                #   subdivided -> a compound section's torsion steel is per sub-tube;
                #   not_solved -> single tube, but at least one chord face that
                #                 carries the torsion share could not be built (its
                #                 conditional solve failed or it has no tension steel).
                # Under torsion the torsion tensions all four faces (both shear faces
                # and both off-axis faces), so ALL four are required; if fewer were
                # built the coverage is incomplete and a partly-checked governing
                # chord must not read as a clean OK -- disclose it.
                if tors_live and tors_ctx.get("subdivide", False):
                    off_not_evaluated = "subdivided"
                elif tors_live and len(chord_faces) + len(chord_off_faces) < 4:
                    off_not_evaluated = "not_solved"
                else:
                    off_not_evaluated = None
                # Report the GOVERNING shear-axis face (highest utilisation at the
                # member angle): the flexural tension face (bending + dFtd + torsion)
                # or, under torsion, the compression face (torsion share only).
                for _cf in chord_faces:
                    fchk = combined.longitudinal_check(
                        _cf["m_ed"], _cf["m_rd"],
                        longitudinal_shear_force if _cf["gets_shift"] else 0.0,
                        ftd_t_star, _cf["z_m"],
                        cap_shear_force=not link_ctx.get("model_2023"))
                    fchk.update(valid=True, role="shear_axis",
                                axis=_cf["axis"],
                                tension_low=_cf["tension_low"],
                                off_util=_cf["off_util"],
                                biaxial=bool(_cf["off_util"] > 0.05),
                                m_off=_cf["m_off"],
                                conditional=_cf["conditional"],
                                has_torsion=tors_live,
                                gets_shift=_cf["gets_shift"],
                                off_not_evaluated=off_not_evaluated,
                                theta_mode=theta_mode_str)
                    lchecks.append(fchk)
                    if lchk is None or fchk["util"] > lchk["util"]:
                        lchk = fchk
                # The off-axis chord: bending tension about the OTHER axis plus its
                # share of the torsion longitudinal force (no shear shift -- the
                # shear acts in the shear plane), against the capacity conditional on
                # the shear-axis moment. Both off-axis faces carry the torsion share;
                # report the GOVERNING (highest utilisation) at the member angle.
                for _ocf in chord_off_faces:
                    fchk = combined.longitudinal_check(
                        _ocf["m_ed"], _ocf["m_rd"], 0.0, ftd_t_star, _ocf["z_m"])
                    fchk.update(valid=True, role="off_axis",
                                axis=_ocf["axis"],
                                tension_low=_ocf["tension_low"],
                                m_off=_ocf["m_off"],
                                conditional=_ocf["conditional"],
                                z_src=_ocf.get("z_src"),
                                theta_mode=theta_mode_str)
                    ochecks.append(fchk)
                    if ochk is None or fchk["util"] > ochk["util"]:
                        ochk = fchk
            required_chords = lchecks + ochecks
            governing_longitudinal = (
                max(required_chords, key=lambda item: item["util"])
                if required_chords else None
            )
            longitudinal_fallback = next(
                (
                    item for item in required_chords
                    if not item.get("conditional", True)
                ),
                None,
            )
            out["shear"].update(
                links=dict(res=lk, util=util_l, asw=link_ctx["asw"],
                           asw_over_s=link_ctx["asw_over_s"],
                           legs=inp["shear_link_legs"], dia=inp["shear_link_dia"],
                           s=inp["shear_link_s"], fywk=inp["shear_fywk"],
                           cot_min=link_ctx["cot_min"], cot_max=link_ctx["cot_max"],
                           delta_ftd=delta_ftd,
                           longitudinal_shear_force=longitudinal_shear_force,
                           longitudinal_shear_symbol=(
                               "NVd" if link_ctx.get("model_2023") else "delta_Ftd"
                           ),
                           longitudinal_shear_clause=(
                               "8.2.3(8), Formula (8.50)"
                               if link_ctx.get("model_2023")
                               else "6.2.3(7), Formula (6.18)"
                           ),
                           cot_limit_lo=lo, cot_limit_hi=hi,
                           angle_limits=angle_limits,
                           model_2023=link_ctx.get("model_2023", False),
                           z_source=link_ctx["z_src"],
                           z_component=link_ctx["z_component"],
                           z_source_angle_deg=link_ctx["z_source_angle_deg"],
                           z_source_case=link_ctx["z_source_case"],
                           z_source_axial_kn=link_ctx["z_source_axial_kn"],
                           assessment_reason=(
                               link_ctx["z_src"]
                               if link_ctx.get("z_mm") is None
                               else lk.get("reason")
                           ),
                           out_of_limits=links_out_of_limits,
                           required=bool(v_ed > link_ctx["vrd_c"]), chord=lchk,
                           chord_off=ochk,
                           chord_candidates=required_chords,
                           governing_longitudinal=governing_longitudinal,
                           longitudinal_fallback=longitudinal_fallback,
                           longitudinal_all_conditional=(
                               bool(required_chords)
                               and longitudinal_fallback is None
                           ),
                           theta_mode=(theta_mode_str if shear_live
                                       else "resistance"),
                           member_angle_selection=member_angle_selection))

        # ---- checks that pair shear and torsion, at the member angle ----
        if tors_ctx is not None:
            t_ed = tors_ctx["t_ed"]
            primary = out["torsion"]["primary"]
            # Minimum-reinforcement screen (EN 1992-1-1 6.3.2(5), Eq 6.31).
            # Applicability is decided here and retained with the operands so no
            # presentation surface can infer a favourable verdict from geometry
            # alone.
            sh_ms = out.get("shear")
            _trdc = primary["trd_c"]
            sh_res = (sh_ms or {}).get("res") or {}
            out["torsion"]["min_reinf"] = dataclasses.asdict(
                combined.minimum_reinforcement_screen_result(
                    t_ed,
                    _trdc,
                    (sh_ms or {}).get("v_ed"),
                    sh_res.get("vrd_c") if sh_res.get("valid") else None,
                    solid_rectangle=(
                        geometry.section_is_approximately_solid_rectangle(
                            inp["outer"], inp.get("holes") or ()
                        )
                    ),
                    subdivided=bool(tors_ctx["subdivide"]),
                    model_2023=bool((sh_ms or {}).get("model_2023")),
                    shear_available=bool(sh_ms is not None and sh_res.get("valid")),
                )
            )
            # Combined shear+torsion concrete crushing (6.29) at the member angle,
            # pairing the shear with the PRIMARY (web) tube's torsion share.
            sh_links = out.get("shear", {}).get("links")
            p_tube, t_ed_p = primary["tube"], primary["t_ed"]
            if sh_links is not None and sh_links["res"]["valid"] and p_tube["valid"]:
                # The member angle when a load drives it; otherwise the
                # least-conservative angle (cot = 1 clamped to the shared band).
                pl_lo, pl_hi = link_ctx["cot_min"], link_ctx["cot_max"]
                cot_c = (
                    cot_star
                    if cot_star is not None
                    else min(max(1.0, pl_lo), pl_hi)
                )
                trdmax_result = torsion.trd_max_result(
                    tors_ctx["fck"], tors_ctx["tcode"], p_tube["Ak"],
                    p_tube["tef"], tors_ctx["alpha_cw"], cot_c,
                    closed_detailing=tors_ctx["nu_detail"],
                    fcd_mpa=tors_ctx["fcd"])
                vlk = link_ctx["build"](cot_c, cot_c)
                inter = combined.crushing_interaction_result(
                    t_ed_p, trdmax_result.trd_max, v_ed_s, vlk["vrd_max"])
                out["torsion"]["interaction"] = dict(
                    valid=True, cot=cot_c,
                    theta_deg=math.degrees(math.atan2(1.0, cot_c)),
                    trd_max=trdmax_result.trd_max,
                    vrd_max=vlk["vrd_max"], t_ed=t_ed_p,
                    v_ed=v_ed_s, value=inter.utilisation,
                    torsion_ratio=inter.torsion_ratio,
                    shear_ratio=inter.shear_ratio,
                    ok=inter.ok,
                    torsion_strut=dataclasses.asdict(trdmax_result))

    capacity.finalize_combined(inp, out)


def _directional_shear_status(inp, shear_out):
    """Acceptance state for one directional shear calculation."""
    if not shear_out or not (shear_out.get("res") or {}).get("valid"):
        return "INVALID"
    if inp.get("shear_links") is True:
        links = shear_out.get("links")
        if links is None or not (links.get("res") or {}).get("valid"):
            return "NOT ASSESSED"
        util = links.get("util")
    else:
        util = shear_out.get("util")
    if util is None or not math.isfinite(float(util)):
        return "INVALID"
    return "PASS" if float(util) <= 1.0 + 1.0e-9 else "FAIL"


def _shear_candidate_assessment(inp, candidate_out):
    """Return the status and shear-only metric for one candidate face."""
    shear_out = candidate_out.get("shear") or {}
    status = _directional_shear_status(inp, shear_out)
    links = shear_out.get("links") or {}
    # VRd,c remains useful context when links are present, but it is no longer the
    # acceptance resistance. Rank faces/components by the same applicable metric
    # used by _directional_shear_status so presentation and verdicts cannot diverge.
    metric = float(
        (
            links.get("util")
            if inp.get("shear_links") is True
            else shear_out.get("util")
        )
        or 0.0
    )
    return status, (math.inf if status == "INVALID" else metric)


def _minimum_reinf_assessment(torsion_out):
    """Return an ordering state for the face-specific Eq. 6.31 screen."""
    if torsion_out is None:
        return "NOT RUN", 0.0
    check = (torsion_out or {}).get("min_reinf") or {}
    if not check.get("applicable"):
        return presentation.minimum_reinforcement_screen_status(check), 0.0
    value = check.get("value")
    if value is None or not math.isfinite(float(value)):
        return "INVALID", math.inf
    return ("PASS" if check.get("ok") else "FAIL"), float(value)


def _candidate_domain_cot(candidate, domain):
    """Strut cot(theta) for one candidate/domain, where the domain has an angle."""
    results = candidate.get("results") or {}
    if domain == "shear":
        return (((results.get("shear") or {}).get("links") or {}).get("res") or {}).get(
            "cot"
        )
    if domain == "vt":
        return ((results.get("torsion") or {}).get("interaction") or {}).get("cot")
    if domain == "combined":
        combined_out = results.get("combined") or {}
        transverse = combined_out.get("transverse") or {}
        if transverse.get("valid") and transverse.get("cot") is not None:
            return transverse.get("cot")
        return (combined_out.get("crushing") or {}).get("cot")
    return None


def _governing_domain(candidate, status, metric, domain):
    """Auditable face/angle/status record for an independently governed domain."""
    return {
        "face": "negative" if candidate["tension_low"] else "positive",
        "cot": _candidate_domain_cot(candidate, domain),
        "status": status,
        "util": metric,
    }


def _torsion_interaction_assessment(torsion_out):
    """Return the result state of one face-specific V+T crushing screen."""
    if torsion_out is None:
        return "NOT RUN", 0.0
    torsion_out = torsion_out or {}
    interaction = torsion_out.get("interaction") or {}
    value = interaction.get("value")
    status = presentation.interaction_assessment_status(interaction)
    metric = float(value or 0.0)
    if not math.isfinite(metric):
        metric = math.inf
    return status, metric


def _combined_direction_assessment(inp, candidate_out):
    """Return the conservative status and utilisation for one V+T screen.

    Reuse the same result rows as the application summary so the directional
    results view and report cannot disagree about an invalid or failed sub-check.
    """
    rows = [
        row for row in presentation.result_summary_rows(inp, candidate_out)
        if row.get("view") == "M-V-T Combined"
    ]
    status = presentation.overall_summary_status(rows)
    utilisations = [
        float(row["util"])
        for row in rows
        if row.get("util") is not None
    ]
    return status, max(utilisations, default=0.0)


def _direction_input(inp, component, tension_low, spec=None):
    """Translate one v7 component/face onto the verified uniaxial v6 contract."""
    spec = spec or capacity.shear_direction_specs(inp)[component]
    translated = dict(inp)
    translated.update(
        shear_axis=spec["axis"],
        shear_tension=bool(tension_low),
        shear_V=spec["v_ed"],
        shear_bw=spec["bw"],
        shear_link_legs=spec["legs"],
    )
    return translated


def _run_capacity_checks(inp, out):
    """Run directional Vx/Vy checks without claiming a biaxial interaction law.

    Each direction is passed independently through the existing verified shear and
    shear-torsion implementation. If both components are present, both directional
    results are retained with no aggregate cross-direction verdict.
    """
    prepared_inp = inp
    directional_contract = (
        "shear_Vx" in prepared_inp
        or "shear_Vy" in prepared_inp
        or "shear_components" in prepared_inp
    )
    if not directional_contract:
        _run_uniaxial_capacity_checks(prepared_inp, out)
        return

    specs = capacity.shear_direction_specs(prepared_inp)
    active = [component for component in ("vx", "vy")
              if prepared_inp.get("shear_on") and specs[component]["v_ed"] > 0.0]
    if not active:
        base = dict(prepared_inp, shear_on=False, combined_on=False)
        _run_uniaxial_capacity_checks(base, out)
        return

    directions = {}
    retained_nm_action_alone = None
    for component in active:
        spec = specs[component]
        face_key = "shear_face_x" if component == "vx" else "shear_face_y"
        faces = capacity.shear_face_candidates(spec["face"], spec["moment"])
        candidates = []
        for tension_low in faces:
            candidate_inp = _direction_input(
                prepared_inp, component, tension_low, spec
            )
            if retained_nm_action_alone is not None:
                candidate_inp["_dkna_nm_action_alone"] = (
                    retained_nm_action_alone
                )
            candidate_out = {
                key: value for key, value in out.items()
                if key in {"plastic", "elastic"}
            }
            _run_uniaxial_capacity_checks(candidate_inp, candidate_out)
            action_alone = (
                (candidate_out.get("combined") or {}).get("action_alone")
                or {}
            )
            if (
                retained_nm_action_alone is None
                and isinstance(action_alone.get("n"), dict)
                and isinstance(action_alone.get("m"), dict)
            ):
                retained_nm_action_alone = {
                    "n": action_alone["n"],
                    "m": action_alone["m"],
                }
            shear_status, shear_metric = _shear_candidate_assessment(
                candidate_inp, candidate_out
            )
            torsion_status, torsion_metric = _torsion_interaction_assessment(
                candidate_out.get("torsion")
            )
            min_reinf_status, min_reinf_metric = _minimum_reinf_assessment(
                candidate_out.get("torsion")
            )
            if candidate_out.get("combined") is not None:
                combined_status, combined_metric = _combined_direction_assessment(
                    candidate_inp, candidate_out
                )
            else:
                combined_status, combined_metric = "NOT RUN", 0.0
            candidates.append({
                "tension_low": bool(tension_low),
                "input": candidate_inp,
                "results": candidate_out,
                "shear_status": shear_status,
                "shear_metric": shear_metric,
                "torsion_status": torsion_status,
                "torsion_metric": torsion_metric,
                "min_reinf_status": min_reinf_status,
                "min_reinf_metric": min_reinf_metric,
                "combined_status": combined_status,
                "combined_metric": combined_metric,
            })
        shear_governing = max(
            candidates,
            key=lambda candidate: capacity.assessment_key(
                candidate["shear_status"], candidate["shear_metric"]
            ),
        )
        torsion_governing = max(
            candidates,
            key=lambda candidate: capacity.assessment_key(
                candidate["torsion_status"], candidate["torsion_metric"]
            ),
        )
        min_reinf_governing = max(
            candidates,
            key=lambda candidate: capacity.assessment_key(
                candidate["min_reinf_status"], candidate["min_reinf_metric"]
            ),
        )
        combined_governing = max(
            candidates,
            key=lambda candidate: capacity.assessment_key(
                candidate["combined_status"], candidate["combined_metric"]
            ),
        )
        shear_out = dict(shear_governing["results"]["shear"])
        shear_status = capacity.aggregate_assessment_status(
            candidate["shear_status"] for candidate in candidates
        )
        torsion_status = capacity.aggregate_assessment_status(
            candidate["torsion_status"] for candidate in candidates
        )
        min_reinf_status = capacity.aggregate_assessment_status(
            candidate["min_reinf_status"] for candidate in candidates
        )
        combined_status = capacity.aggregate_assessment_status(
            candidate["combined_status"] for candidate in candidates
        )
        governing_domains = {
            "shear": _governing_domain(
                shear_governing,
                shear_status,
                shear_governing["shear_metric"],
                "shear",
            )
        }
        if any(
            ((candidate["results"].get("torsion") or {}).get("interaction"))
            is not None
            for candidate in candidates
        ):
            governing_domains["vt"] = _governing_domain(
                torsion_governing,
                torsion_status,
                torsion_governing["torsion_metric"],
                "vt",
            )
        if any(
            ((candidate["results"].get("torsion") or {}).get("min_reinf"))
            is not None
            for candidate in candidates
        ):
            governing_domains["minimum_reinforcement"] = _governing_domain(
                min_reinf_governing,
                min_reinf_status,
                min_reinf_governing["min_reinf_metric"],
                "minimum_reinforcement",
            )
        if any(candidate["results"].get("combined") is not None
               for candidate in candidates):
            governing_domains["combined"] = _governing_domain(
                combined_governing,
                combined_status,
                combined_governing["combined_metric"],
                "combined",
            )
        shear_out.update(
            face_mode=str(inp.get(face_key, "auto")),
            both_faces_evaluated=len(candidates) == 2,
            governing_face=(
                "negative" if shear_governing["tension_low"] else "positive"
            ),
            associated_moment=spec["moment"],
            associated_moment_origin=spec["moment_origin"],
            signed_v_ed=spec["signed_v_ed"],
            status=shear_status,
            governing_domains=governing_domains,
            face_candidates=[{
                "tension_low": candidate["tension_low"],
                "shear_status": candidate["shear_status"],
                "shear_metric": candidate["shear_metric"],
                "torsion_status": candidate["torsion_status"],
                "torsion_metric": candidate["torsion_metric"],
                "min_reinf_status": candidate["min_reinf_status"],
                "min_reinf_metric": candidate["min_reinf_metric"],
                "combined_status": candidate["combined_status"],
                "combined_metric": candidate["combined_metric"],
                "shear": candidate["results"].get("shear"),
                "torsion": candidate["results"].get("torsion"),
                "combined": candidate["results"].get("combined"),
            } for candidate in candidates],
        )
        combined_out = combined_governing["results"].get("combined")
        if combined_out is not None:
            combined_out = dict(
                combined_out,
                component=component,
                governing_face=(
                    "negative" if combined_governing["tension_low"] else "positive"
                ),
                governing_cot=_candidate_domain_cot(
                    combined_governing, "combined"
                ),
            )
        torsion_out = torsion_governing["results"].get("torsion")
        if torsion_out is not None:
            vt_domain = governing_domains.get("vt") or {}
            torsion_out = dict(
                torsion_out,
                directional_interaction_status=capacity.aggregate_assessment_status(
                    candidate["torsion_status"] for candidate in candidates
                ),
                directional_governing_face=vt_domain.get("face"),
                directional_governing_cot=vt_domain.get("cot"),
            )
            selected_min_reinf = (
                (min_reinf_governing["results"].get("torsion") or {}).get(
                    "min_reinf"
                )
            )
            if selected_min_reinf is not None:
                torsion_out["min_reinf"] = dict(
                    selected_min_reinf,
                    directional_status=min_reinf_status,
                    governing_face=(
                        "negative"
                        if min_reinf_governing["tension_low"]
                        else "positive"
                    ),
                )
                torsion_out["directional_min_reinf_status"] = min_reinf_status
                torsion_out["directional_min_reinf_governing_face"] = (
                    "negative"
                    if min_reinf_governing["tension_low"]
                    else "positive"
                )
        directions[component] = {
            "component": component,
            "shear": shear_out,
            "torsion": torsion_out,
            "combined": combined_out,
            "status": shear_out["status"],
            "metric": shear_governing["shear_metric"],
        }

    if len(active) == 1:
        chosen = directions[active[0]]
        out["shear"] = chosen["shear"]
        if chosen["torsion"] is not None:
            out["torsion"] = chosen["torsion"]
        if chosen["combined"] is not None:
            out["combined"] = chosen["combined"]
        return

    out["shear"] = {
        "directions": {
            key: value["shear"] for key, value in directions.items()
        },
        "active_directions": active,
        "biaxial": True,
        "note": (
            "Vx and Vy are calculated independently. Generic cross-direction "
            "interaction is not calculated."
        ),
    }

    # Torsion on its own remains fully assessable.  The directional V+T screens
    # above are retained separately; no Vx+Vy+T interaction is inferred.
    if inp.get("torsion_on"):
        torsion_only_inp = dict(inp, shear_on=False, combined_on=False)
        torsion_only_out = {key: value for key, value in out.items()
                            if key in {"plastic", "elastic"}}
        _run_uniaxial_capacity_checks(torsion_only_inp, torsion_only_out)
        if torsion_only_out.get("torsion") is not None:
            out["torsion"] = dict(
                torsion_only_out["torsion"],
                directional_interactions={
                    key: value["torsion"] for key, value in directions.items()
                },
            )
    if inp.get("combined_on"):
        directional_combined = {
            key: value["combined"] for key, value in directions.items()
        }
        independent_mv = inp.get("combined_mv_independent") is True
        separation_condition = next((
            direction.get("m_v_separation_condition")
            for direction in directional_combined.values()
            if isinstance(direction, dict)
            and direction.get("m_v_independent") is independent_mv
            and isinstance(direction.get("m_v_separation_condition"), dict)
        ), None)
        out["combined"] = dict(
            directions=directional_combined,
            biaxial=True,
            m_v_independent=independent_mv,
            m_v_separation_condition=separation_condition,
            note=(
                "Independent Vx+T and Vy+T calculations are reported. Generic "
                "Vx+Vy+T interaction is not calculated."
            ),
        )


def _direction_detailing_depth(direction):
    """Smallest required-face depth retained in one directional shear result."""
    depths = []
    for candidate in direction.get("face_candidates") or []:
        value = (candidate.get("shear") or {}).get("d")
        if value is not None and math.isfinite(float(value)) and float(value) > 0.0:
            depths.append(float(value))
    value = direction.get("d")
    if value is not None and math.isfinite(float(value)) and float(value) > 0.0:
        depths.append(float(value))
    return min(depths, default=0.0)


def _transverse_detailing_result(inp, out):
    """Translate verified shear/torsion geometry into pure detailing checks."""
    shear_specs = []
    shear_out = out.get("shear") or {}
    if inp.get("shear_on") and shear_out:
        directions = shear_out.get("directions")
        if directions:
            items = list(directions.items())
        else:
            component = str(shear_out.get("component") or (
                "vy" if shear_out.get("axis") == "x" else "vx"
            ))
            items = [(component, shear_out)]
        for component, direction in items:
            links = direction.get("links") or {}
            resistance = direction.get("res") or {}
            resistance_valid = bool(resistance.get("valid"))
            vrd_c = resistance.get("vrd_c")
            v_ed = direction.get("v_ed")
            if (
                resistance_valid
                and vrd_c is not None
                and v_ed is not None
                and math.isfinite(float(vrd_c))
                and math.isfinite(float(v_ed))
            ):
                links_required = float(v_ed) > float(vrd_c) + 1.0e-9
            else:
                links_required = None
            shear_specs.append({
                "component": component,
                "links_present": inp.get("shear_links") is True,
                "links_required": links_required,
                "requirement_clause": (
                    "8.2.2"
                    if bool(direction.get("model_2023"))
                    else "6.2.2"
                ),
                "bw_mm": direction.get("bw", 0.0),
                "d_mm": _direction_detailing_depth(direction),
                "legs": links.get(
                    "legs",
                    inp.get(
                        "shear_vx_link_legs"
                        if component == "vx"
                        else "shear_vy_link_legs",
                        0.0,
                    ),
                ),
                "transverse_leg_spacing_mm": inp.get(
                    "shear_vx_transverse_leg_spacing"
                    if component == "vx"
                    else "shear_vy_transverse_leg_spacing",
                    0.0,
                ),
                "measurement_axis": "y" if component == "vx" else "x",
            })

    torsion_specs = []
    torsion_out = out.get("torsion") or {}
    if inp.get("torsion_on") and torsion_out:
        subresults = torsion_out.get("subtubes") or []
        if subresults:
            for index, subresult in enumerate(subresults, start=1):
                tube = subresult.get("tube") or {}
                torsion_specs.append({
                    "label": f"Tube {index}",
                    "valid": bool(subresult.get("valid") and tube.get("valid")),
                    "reason": tube.get("reason"),
                    "tef_mm": tube.get("tef", 0.0),
                    "uk_mm": float(tube.get("uk", 0.0)) * 1000.0,
                    "minimum_dimension_mm": tube.get(
                        "minimum_dimension_mm", 0.0
                    ),
                })
        else:
            tube = torsion_out.get("tube") or {}
            torsion_specs.append({
                "label": "Tube",
                "valid": bool(torsion_out.get("valid") and tube.get("valid")),
                "reason": torsion_out.get("reason") or tube.get("reason"),
                "tef_mm": tube.get("tef", 0.0),
                "uk_mm": float(tube.get("uk", 0.0)) * 1000.0,
                "minimum_dimension_mm": tube.get(
                    "minimum_dimension_mm", 0.0
                ),
            })

    return detailing.transverse_reinforcement(
        edition=inp["detailing_edition"],
        fck_mpa=inp["concrete"].fck,
        fywk_mpa=inp["shear_fywk"],
        diameter_mm=inp["shear_link_dia"],
        spacing_mm=inp["shear_link_s"],
        shear_directions=shear_specs,
        torsion_tubes=torsion_specs,
        ductility_class=inp.get("transverse_ductility_class", "B"),
        apply_ductility_reduction=inp.get(
            "transverse_apply_ductility_reduction", False
        ),
        member_type=inp.get(
            "detailing_member_type", detailing.MEMBER_BEAM
        ),
    )


# ---------------------------------------------------------------------------
# Input previews and result views. Geometry and material laws stay beside their
# source inputs; the Analysis page therefore contains calculated results only.
# ---------------------------------------------------------------------------

# View order follows the checking workflow: consolidated status first, then the
# plastic, elastic, shear, torsion and combined details.
VIEWS = [view.label for view in manual_ia.RESULT_VIEWS]
_RESULT_VIEWS = tuple(VIEWS)


def _memo_fig(name, sig, build):
    """Return a cached live figure, rebuilding only when its inputs change.

    Streamlit reruns the whole script on every widget change, so the live section
    and material previews would otherwise re-run the ~10-20 ms Plotly figure
    construction each time -- e.g. rebuilding the material curves when the user
    only touched a load. One slot per figure kind is kept in session state, keyed
    by ``sig`` (compared by value); the figure is reused in place rather than
    pickled (unlike ``st.cache_data``), which is safe because the views only read
    it. On a cache miss the cost is just the rebuild that would happen anyway, so
    this never makes the point-editing path (where the geometry changes every
    keystroke) slower.
    """
    cache = st.session_state.setdefault("_fig_cache", {})
    entry = cache.get(name)
    if entry is None or entry[0] != sig:
        entry = cache[name] = (sig, build())
    return entry[1]


def _section_input_preview(box, outer, holes, bars, tendons, bar_elements=None,
                           tendon_elements=None, *, visible):
    """Render the section beside its point tables and return label settings.

    Controls remain mounted with the other inputs. The Plotly payload is emitted
    only while the Section tab is open, which avoids hidden-chart overhead on load
    and material edits.
    """
    box.markdown("**Display**")
    lc1, lc2 = box.columns(2)
    label_scale = _seeded_number(
        lc1, "Label size", 0.5, 3.0,
        st.session_state.get("_workspace_label_scale", 1.0),
        0.1, "label_scale",
        help="Scales corner, bar and tendon number labels.",
    )
    label_min_gap = _seeded_number(
        lc2, "Label spacing", 0.0, 0.5,
        st.session_state.get("_workspace_label_min_gap", 0.04),
        0.01, "label_min_gap",
        help="Hides labels closer together than this fraction of the section size; "
             "0 shows every label.",
    )
    st.session_state["_workspace_label_scale"] = label_scale
    st.session_state["_workspace_label_min_gap"] = label_min_gap

    box.caption(
        f"{len(outer)} corners | {len(holes)} voids | "
        f"{len(bars)} bars | {len(tendons)} tendons"
    )
    if visible:
        preview_token = app_run_probe.start_phase(st.session_state, "preview")
        try:
            bar_xy = [(b[0], b[1], b[2]) for b in bars]
            tendon_xy = [(t[0], t[1], t[2]) for t in tendons]
            bar_records = list(bar_elements or [])
            tendon_records = list(tendon_elements or [])
            bar_ids = [item["id"] for item in bar_records]
            tendon_ids = [item["id"] for item in tendon_records]

            def assignment_hover(records):
                out = []
                for item in records:
                    line = f"material = {item.get('material_id') or '-'}"
                    diameter = item.get("diameter_mm")
                    if diameter is not None:
                        line += f"<br>diameter = {float(diameter):.3g} mm"
                    line += f"<br>size basis = {item.get('size_mode') or '-'}"
                    out.append(line)
                return out

            bar_hover = assignment_hover(bar_records)
            tendon_hover = assignment_hover(tendon_records)
            assignment_sig = tuple(
                (
                    item.get("id"),
                    item.get("material_id"),
                    item.get("diameter_mm"),
                    item.get("size_mode"),
                )
                for item in bar_records + tendon_records
            )
            sig = (
                outer,
                holes,
                bar_xy,
                tendon_xy,
                tuple(bar_ids),
                tuple(tendon_ids),
                assignment_sig,
                label_scale,
                label_min_gap,
            )
            fig = _memo_fig(
                "section",
                sig,
                lambda: viz.section_figure(
                    outer,
                    holes,
                    bar_xy,
                    title="Section preview",
                    tendons=tendon_xy,
                    show_labels=True,
                    label_scale=label_scale,
                    label_min_gap=label_min_gap,
                    height=640,
                    scale=_MM,
                    unit="mm",
                    bar_ids=bar_ids,
                    tendon_ids=tendon_ids,
                    bar_hover=bar_hover,
                    tendon_hover=tendon_hover,
                ),
            )
            box.plotly_chart(fig, width="stretch")
        finally:
            app_run_probe.stop_phase(st.session_state, preview_token)
    return label_scale, label_min_gap


def _material_input_preview(box, cache_name, material, figure_builder, *, visible,
                            title=None):
    """Render one live material law only when its nested input tab is visible."""
    if visible and material is not None:
        preview_token = app_run_probe.start_phase(st.session_state, "preview")
        try:
            signature = (material, title) if title is not None else material
            if title is None:
                build = lambda: figure_builder(material)
            else:
                build = lambda: figure_builder(material, title=title)
            box.plotly_chart(
                _memo_fig(cache_name, signature, build),
                width="stretch",
            )
        finally:
            app_run_probe.stop_phase(st.session_state, preview_token)


def results_overview_view(inp, results, *, stale=False):
    """One-screen result register without a global calculation verdict."""
    all_rows = presentation.multi_case_summary_rows(inp, results, stale=stale)
    selected = presentation.governing_summary_rows(all_rows)
    rows = presentation.governing_result_rows(selected)
    information_rows = presentation.governing_information_rows(selected)
    failure_states = {
        "INVALID",
        "FAIL",
        "EXCEEDS USER-SPECIFIED LIMIT",
        "PROVIDED AREA BELOW CALCULATED REQUIREMENT",
    }
    warning_states = {
        "STALE",
        "REVIEW",
        "CONDITIONAL",
        "NOT ASSESSED",
        "CALCULATED - NO LIMIT COMPARISON",
    }
    success_or_output_states = {
        "PASS",
        "WITHIN USER-SPECIFIED LIMIT",
        "PROVIDED AREA AT LEAST CALCULATED REQUIREMENT",
        "CALCULATED",
    }
    failure_count = sum(row["status"] in failure_states for row in rows)
    warning_count = sum(
        row["status"] in warning_states
        or row["status"] not in (
            failure_states
            | warning_states
            | success_or_output_states
            | presentation.GOVERNING_OVERVIEW_INFORMATION_STATUSES
        )
        for row in rows
    )
    if failure_count:
        st.error(
            "A governing comparison fails or is invalid. Review the "
            "highlighted rows below."
        )
    elif warning_count:
        _manual_warning(
            st,
            "results-review",
            "Some governing results require review. Review the "
            "highlighted rows below."
        )
    elif rows:
        st.success(
            "The governing results are current; every comparison with a "
            "stated criterion is within it."
        )
    else:
        st.info(
            "No applicable calculated result is available. Scope and calculation "
            "states are listed below; no pass conclusion is implied."
        )
    st.caption(
        "Interpret each row independently; an aggregate section status is not "
        "calculated."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Governing result types", len(rows))
    c2.metric("Fail / invalid", failure_count)
    c3.metric("Review / stale", warning_count)
    c4.metric("Scope states", len(information_rows))

    display = []
    for row in rows:
        display.append({
            "Check": row["check"],
            "Governing action": row["case"],
            "Status": row["status"],
            "Result": row["result"],
            "Criterion": row["criterion"],
            "View": row["view"],
        })
    summary = pd.DataFrame(
        display,
        columns=(
            "Check",
            "Governing action",
            "Status",
            "Result",
            "Criterion",
            "View",
        ),
    )
    status_colours = {
        "PASS": "background-color: #E8F5E9; color: #1B5E20; font-weight: 600",
        "FAIL": "background-color: #FDECEC; color: #9B1C1C; font-weight: 600",
        "INVALID": "background-color: #FDECEC; color: #9B1C1C; font-weight: 600",
        "NOT ASSESSED": (
            "background-color: #FFF4D6; color: #7A4E00; font-weight: 600"
        ),
        "CONDITIONAL": (
            "background-color: #FFF4D6; color: #7A4E00; font-weight: 600"
        ),
        "NOT RUN": "background-color: #EEF2F6; color: #374151; font-weight: 600",
        "NOT CALCULATED": (
            "background-color: #EEF2F6; color: #374151; font-weight: 600"
        ),
        "STALE": "background-color: #FFF4D6; color: #7A4E00; font-weight: 600",
        "REVIEW": "background-color: #FFF4D6; color: #7A4E00; font-weight: 600",
        "NOT APPLICABLE": "background-color: #EEF2F6; color: #374151",
        "CALCULATED": "background-color: #E8F0FE; color: #174EA6",
        "NOT REQUESTED": "background-color: #EEF2F6; color: #374151",
        "CALCULATED - NO LIMIT COMPARISON": (
            "background-color: #E8F0FE; color: #174EA6"
        ),
        "WITHIN USER-SPECIFIED LIMIT": (
            "background-color: #E8F0FE; color: #174EA6; font-weight: 600"
        ),
        "EXCEEDS USER-SPECIFIED LIMIT": (
            "background-color: #FFF4D6; color: #7A4E00; font-weight: 600"
        ),
        "PROVIDED AREA AT LEAST CALCULATED REQUIREMENT": (
            "background-color: #E8F0FE; color: #174EA6; font-weight: 600"
        ),
        "PROVIDED AREA BELOW CALCULATED REQUIREMENT": (
            "background-color: #FFF4D6; color: #7A4E00; font-weight: 600"
        ),
    }
    if not summary.empty:
        styled = summary.style.map(
            lambda value: status_colours.get(str(value), ""),
            subset=["Status"],
        )
        st.table(
            styled,
            hide_index=True,
            width="stretch",
            height="content",
        )

    for row in rows:
        if str(row.get("overview_key") or "").startswith(
            "torsion:minimum_reinforcement"
        ):
            st.caption(
                f"{row['check']} - {row['status']}: {row.get('note') or '-'}"
            )

    if information_rows:
        st.markdown("**Scope and calculation state**")
        st.text("\n".join(
            f"{row['check']} | {row['case']} | {row['status']} | {row['result']}"
            for row in information_rows
        ))


def _detailing_status_callout(status, message):
    """Render one concise detailing verdict with the shared status vocabulary."""
    status = str(status or "NOT ASSESSED").upper()
    text = f"{status} - {message}"
    if status == "PASS":
        st.success(text)
    elif status in {"FAIL", "INVALID"}:
        st.error(text)
    elif status == "NOT APPLICABLE":
        st.info(text)
    else:
        _manual_warning(st, "calculation-warning", text)


def detailing_view(inp, results, *, global_results=None):
    """Modelled-direction reinforcement and link-spacing evidence."""
    results = results or {}
    global_results = global_results or results
    minimum = results.get("minimum_reinforcement")
    transverse = results.get("transverse_reinforcement")
    spacing = global_results.get("clear_spacing")

    st.subheader("Detailing")
    min_card, transverse_card, spacing_card = st.columns(3)
    with min_card.container(border=True):
        direction_label = modelled_direction.resolved_markdown_label(
            minimum,
            cut_direction=inp.get("detailing_cut_direction"),
            alias=inp.get(modelled_direction.ALIAS_KEY),
        )
        st.markdown(f"**{direction_label} minimum reinforcement**")
        if not inp.get("minimum_reinforcement_on"):
            st.caption("Not selected for this case.")
        elif minimum is None:
            st.info("Calculate to evaluate this case.")
        else:
            checks = minimum.get("checks") or []
            utilisations = [
                float(check["utilisation"])
                for check in checks
                if check.get("utilisation") is not None
                and math.isfinite(float(check["utilisation"]))
            ]
            result_text = (
                f"governing utilisation {100.0 * max(utilisations):.1f} %"
                if utilisations
                else presentation.result_reason(
                    minimum.get("reason"),
                    "minimum_reinforcement",
                    context="minimum-reinforcement card reason",
                )
            )
            _detailing_status_callout(minimum.get("status"), result_text)
            st.caption(
                f"{minimum.get('member_type', inp.get('detailing_member_type', '-'))}; "
                f"{minimum.get('cut_direction', inp.get('detailing_cut_direction', '-'))} | "
                f"{minimum.get('edition', '-')} | {minimum.get('clause', '-')}"
            )
            nominal_solution = next((
                check.get("nominal_solution")
                for check in checks
                if check.get("nominal_solution")
            ), None)
            if nominal_solution:
                target = nominal_solution.get("governing_target_increment_deg")
                if "governing_target_increment_deg" not in nominal_solution:
                    target = nominal_solution.get("governing_increment_deg")
                achieved = nominal_solution.get("governing_interval_deg")
                retained = nominal_solution.get("accepted_point_count")
                resolution = str(
                    nominal_solution.get("resolution_state") or ""
                ).upper()
                if achieved is not None and retained is not None:
                    outcome = (
                        "assessment resolved"
                        if resolution == "RESOLVED"
                        else "separate assessment required"
                    )
                    st.caption(
                        "Nominal envelope: achieved governing interval "
                        f"{float(achieved):g}°"
                        + (
                            f" for the {float(target):g}° target; "
                            if target is not None
                            else "; "
                        )
                        + f"{int(retained)} angles retained; "
                        + f"{outcome}."
                    )
                    lower = nominal_solution.get("utilisation_lower_bound")
                    upper = nominal_solution.get("utilisation_upper_bound")
                    if lower is not None and upper is not None:
                        convergence = (
                            "all retained angles converged"
                            if nominal_solution.get("all_points_converged")
                            else "one or more retained angles did not converge"
                        )
                        st.caption(
                            "Refinement estimate: utilisation interval "
                            f"{100.0 * float(lower):.4f}–"
                            f"{100.0 * float(upper):.4f} %; {convergence}."
                        )

    with transverse_card.container(border=True):
        st.markdown("**Shear/torsion link detailing**")
        if not inp.get("transverse_detailing_on"):
            st.caption("Not selected for this case.")
        elif transverse is None:
            st.info("Calculate to evaluate this case.")
        else:
            governing = transverse.get("governing") or {}
            transverse_status = str(
                transverse.get("status") or "NOT ASSESSED"
            ).upper()
            incomplete_reason = next((
                presentation.result_reason(
                    check["reason"],
                    "transverse_reinforcement",
                    context="transverse-reinforcement card check reason",
                )
                for check in transverse.get("checks") or []
                if check.get("status") == "NOT ASSESSED"
                and check.get("reason")
            ), None)
            if transverse_status == "NOT ASSESSED" and incomplete_reason:
                result_text = incomplete_reason
            elif governing:
                utilisation = governing.get("utilisation")
                result_text = str(governing.get("scope") or "governing check")
                if utilisation is not None:
                    result_text += f"; {_pct(utilisation)}"
            else:
                result_text = presentation.result_reason(
                    transverse.get("reason"),
                    "transverse_reinforcement",
                    context="transverse-reinforcement card reason",
                )
            _detailing_status_callout(
                transverse_status,
                result_text,
            )
            st.caption(
                f"{transverse.get('member_type', inp.get('detailing_member_type', '-'))} | "
                f"{transverse.get('edition') or '-'}"
            )

    with spacing_card.container(border=True):
        st.markdown("**Clear spacing**")
        if not inp.get("clear_spacing_on"):
            st.caption("Not selected.")
        elif spacing is None:
            st.info("Calculate to evaluate the section.")
        else:
            governing = spacing.get("governing") or {}
            if governing:
                result_text = (
                    f"{governing.get('clear_mm', 0.0):.1f} mm clear; "
                    f"{governing.get('required_mm', 0.0):.1f} mm required"
                )
            else:
                result_text = presentation.result_reason(
                    spacing.get("reason"),
                    "generic",
                    context="clear-spacing card reason",
                )
            _detailing_status_callout(spacing.get("status"), result_text)
            st.caption(
                f"{spacing.get('edition', '-')} | {spacing.get('clause', '-')}"
            )

    highlight_ids = []
    if minimum:
        highlight_ids = sorted({
            str(element_id)
            for check in minimum.get("checks") or []
            for element_id in check.get("bar_ids") or []
        })
    if minimum is not None or spacing is not None:
        st.plotly_chart(
            viz.detailing_geometry_figure(
                inp.get("outer") or [],
                inp.get("holes") or [],
                inp.get("bars") or [],
                inp.get("tendons") or [],
                bar_elements=inp.get("bar_elements") or [],
                tendon_elements=inp.get("tendon_elements") or [],
                highlight_ids=highlight_ids,
                spacing_pair=(spacing or {}).get("governing"),
                tension_zone=(
                    (minimum.get("checks") or [None])[0]
                    if minimum and minimum.get("checks") else None
                ),
                title="Detailing check geometry",
            ),
            width="stretch",
        )

    if minimum is not None:
        st.markdown("**Minimum-reinforcement details**")
        checks = minimum.get("checks") or []
        if checks and presentation.minimum_area_check(minimum, checks[0]):
            rows = [{
                "Axis": (
                    "Mx + My" if check.get("axis") == "xy"
                    else f"M{check.get('axis', '-')}"
                ),
                "Tension face": check.get("face", "-"),
                "As,provided [mm2]": check.get("as_provided_mm2"),
                "As,min [mm2]": check.get("as_min_mm2"),
                "Utilisation [%]": (
                    100.0 * float(check["utilisation"])
                    if check.get("utilisation") is not None else None
                ),
                "bt [mm]": check.get("bt_mm"),
                "d [mm]": check.get("d_mm"),
                "fctm [MPa]": check.get("fctm_mpa"),
                "fyk [MPa]": check.get("fyk_mpa"),
                "Bars": ", ".join(check.get("bar_ids") or []),
                "Status": check.get("status"),
            } for check in checks]
        elif checks and checks[0].get("type") == "pure tension":
            rows = [{
                "Check": "Pure tension",
                "Rcr [kN]": check.get("demand_kn"),
                "Rnom [kN]": check.get("resistance_kn"),
                "Utilisation [%]": (
                    100.0 * float(check["utilisation"])
                    if check.get("utilisation") is not None else None
                ),
                "As,provided [mm2]": check.get("as_provided_mm2"),
                "Bars": ", ".join(check.get("bar_ids") or []),
                "Status": check.get("status"),
            } for check in checks]
        else:
            rows = [{
                "Check": "Bending with axial force",
                "Mcr [kNm]": check.get("m_cr_knm"),
                "MR,nom [kNm]": check.get("mr_nom_knm"),
                "Utilisation [%]": (
                    100.0 * float(check["utilisation"])
                    if check.get("utilisation") is not None else None
                ),
                "Model": check.get("model"),
                "Nnom,tension [kN]": check.get("nominal_axial_resistance_kn"),
                "Axial equilibrium": (
                    "Yes" if check.get("axial_feasible") is True
                    else "No" if check.get("axial_feasible") is False
                    else "-"
                ),
                "As,provided [mm2]": check.get("as_provided_mm2"),
                "Bars": ", ".join(check.get("bar_ids") or []),
                "Status": check.get("status"),
            } for check in checks]
        if rows:
            st.dataframe(
                rows,
                hide_index=True,
                width="stretch",
                column_config={
                    "Utilisation [%]": st.column_config.NumberColumn(format="%.1f"),
                },
            )
            reasons = [
                presentation.result_reason(
                    check["reason"],
                    "minimum_reinforcement",
                    context="minimum-reinforcement detail reason",
                )
                for check in checks if check.get("reason")
            ]
            if reasons:
                st.caption("Outcome: " + "; ".join(dict.fromkeys(reasons)))
        elif minimum.get("reason"):
            st.caption(presentation.result_reason(
                minimum["reason"],
                "minimum_reinforcement",
                context="minimum-reinforcement detail summary reason",
            ))
        if minimum.get("limitations"):
            with st.expander("Minimum-reinforcement method notes"):
                for note in minimum["limitations"]:
                    st.markdown(f"- {note}")

    if spacing is not None:
        st.markdown("**Clear-spacing details**")
        pair_rows = [{
            "Pair": f"{pair.get('first_id', '?')} - {pair.get('second_id', '?')}",
            "Clear [mm]": pair.get("clear_mm"),
            "Required [mm]": pair.get("required_mm"),
            "Margin [mm]": pair.get("margin_mm"),
            "Status": pair.get("status"),
        } for pair in spacing.get("pairs") or []]
        if pair_rows:
            st.dataframe(
                pair_rows,
                hide_index=True,
                width="stretch",
                column_config={
                    "Clear [mm]": st.column_config.NumberColumn(format="%.1f"),
                    "Required [mm]": st.column_config.NumberColumn(format="%.1f"),
                    "Margin [mm]": st.column_config.NumberColumn(format="%+.1f"),
                },
            )
        elif spacing.get("reason"):
            st.caption(presentation.result_reason(
                spacing["reason"],
                "generic",
                context="clear-spacing detail reason",
            ))
        if spacing.get("limitations"):
            with st.expander("Clear-spacing method notes"):
                for note in spacing["limitations"]:
                    st.markdown(f"- {note}")

    if transverse is not None:
        st.markdown("**Shear/torsion link details**")
        check_labels = {
            "minimum_ratio": "Minimum ratio",
            "longitudinal_spacing": "Longitudinal spacing",
            "transverse_leg_spacing": "Transverse leg spacing",
            "torsion_spacing": "Closed-link spacing",
            "required_links": "Required links",
        }
        transverse_rows = []
        for check in transverse.get("checks") or []:
            kind = check.get("kind")
            ratio = kind == "minimum_ratio"
            required_links = kind == "required_links"
            check_label = check_labels.get(kind, kind)
            if kind == "transverse_leg_spacing" and check.get("measurement_axis"):
                check_label += f" (along {check['measurement_axis']})"
            transverse_rows.append({
                "Scope": check.get("scope"),
                "Check": check_label,
                "Provided": None if required_links else check.get("provided"),
                "Limit": None if required_links else check.get("limit"),
                "Unit": (
                    "not defined"
                    if required_links
                    else "-" if ratio else "mm"
                ),
                "Utilisation [%]": (
                    100.0 * float(check["utilisation"])
                    if check.get("utilisation") is not None
                    else None
                ),
                "Status": check.get("status"),
                "Reference": check.get("clause"),
            })
        if transverse_rows:
            st.dataframe(
                transverse_rows,
                hide_index=True,
                width="stretch",
                column_config={
                    "Provided": st.column_config.NumberColumn(format="%.5g"),
                    "Limit": st.column_config.NumberColumn(format="%.5g"),
                    "Utilisation [%]": st.column_config.NumberColumn(
                        format="%.1f"
                    ),
                },
            )
        elif transverse.get("reason"):
            st.caption(presentation.result_reason(
                transverse["reason"],
                "transverse_reinforcement",
                context="transverse-reinforcement detail summary reason",
            ))
        reasons = [
            presentation.result_reason(
                check["reason"],
                "transverse_reinforcement",
                context="transverse-reinforcement detail reason",
            )
            for check in transverse.get("checks") or []
            if check.get("reason")
        ]
        if reasons:
            st.caption("Outcome: " + "; ".join(dict.fromkeys(reasons)))
        if transverse.get("limitations"):
            with st.expander("Shear/torsion link method notes"):
                for note in transverse["limitations"]:
                    st.markdown(f"- {note}")


def _fmt(v):
    """Format a coordinate, showing an infinite neutral-axis intercept as 'inf'."""
    return "inf" if not math.isfinite(v) else f"{v:.3f}"


def _plastic_table(pts, cable, steel_comp=False):
    """Per-angle results table, one row per neutral-axis angle. ``steel_comp`` splits
    the steel-strain column into a tensile and a compression column (only meaningful
    when the mild steel is active in compression)."""
    eps_s_cols = ({f"{_EPS}s,t (%)": [round(pt["eps_s"], 3) for pt in pts],
                   f"{_EPS}s,c (%)": [round(pt["eps_s_comp"], 3) for pt in pts]}
                  if steel_comp else
                  {f"{_EPS}s (%)": [round(pt["eps_s"], 3) for pt in pts]})
    cols = {
        f"NA angle ({_DEG})": [round(pt["V"], 1) for pt in pts],
        "Mx (kNm)": [round(pt["Mx"], 3) for pt in pts],
        "My (kNm)": [round(pt["My"], 3) for pt in pts],
        "NA x (mm)": [_fmt(pt["na_x"] * _MM) for pt in pts],
        "NA y (mm)": [_fmt(pt["na_y"] * _MM) for pt in pts],
        f"{_EPS}c (%)": [round(pt["eps_c"], 3) for pt in pts],
        **eps_s_cols,
        f"{_KAPPA} (1/m)": [round(pt["kappa"], 4) for pt in pts],
        "F_comp (kN)": [round(pt["comp_force"], 3) for pt in pts],
        "Internal lever z (mm)": [round(pt["lever"] * _MM, 3) for pt in pts],
        "z_x (mm)": [round(pt["dx"] * _MM, 3) for pt in pts],
        "z_y (mm)": [round(pt["dy"] * _MM, 3) for pt in pts],
    }
    if cable:
        cols[f"{_EPS}cable (%)"] = [round(pt["eps_cable"], 3) for pt in pts]
    return cols


def _plastic_state_hover(rows):
    """Format retained plastic material states for section-figure hover text."""

    if not rows:
        return None
    out = []
    for row in rows:
        material_id = _html_escape(
            str(row.get("material_id") or "").strip(), quote=True
        )
        material_name = _html_escape(
            str(row.get("material_name") or "").strip(), quote=True
        )
        suffix = f", material {material_id}" if material_id else ""
        if suffix and material_name:
            suffix += f" - {material_name}"
        out.append(
            f"{_SIGMA} = {row['stress_mpa']:.1f} MPa, "
            f"{_EPS} = {row['strain_permille'] / 10.0:.3f} %{suffix}"
        )
    return out


def _elastic_state_hover(rows):
    """Format retained Elastic bar/tendon responses for result-figure hover."""

    if not rows:
        return None
    out = []
    for row in rows:
        material_id = _html_escape(
            str(row.get("material_id") or "").strip(), quote=True
        )
        material_name = _html_escape(
            str(row.get("material_name") or "").strip(), quote=True
        )
        material = ""
        if material_id:
            material = f"<br>material = {material_id}"
            if material_name:
                material += f" - {material_name}"
        out.append(
            f"{_SIGMA}<sub>total</sub> = {row['total_mpa']:.3f} MPa<br>"
            f"{_EPS} = {row['strain_permille']:.4f} {_PERMILLE}{material}"
        )
    return out


def _elastic_corner_hover(rows):
    """Format retained Elastic concrete-corner responses without coordinates."""

    if not rows:
        return None
    return [
        f"{row['ring']} point {row['ring_point_no']}<br>"
        f"{_SIGMA}<sub>c</sub> = {row['stress_mpa']:.3f} MPa<br>"
        f"{_EPS}<sub>c</sub> = {row['strain_permille']:.4f} {_PERMILLE}"
        for row in rows
    ]


def plastic_view(inp, results):
    """Plastic capacity: metrics, the M-M envelope, an inspectable neutral-axis
    state (compression zone + section diagnostics), and the full per-angle table
    matching the handcalc verification."""
    if not results or "plastic" not in results:
        st.info("Run a Plastic or Both analysis, then press Calculate.")
        return
    p = results["plastic"]
    pts = p["points"]
    # Derive the minima from the envelope if absent, so a result payload cached
    # before min_mx/min_my existed (matching inputs -> no recompute) still renders.
    min_mx = p.get("min_mx", min(p["mx"]))
    min_my = p.get("min_my", min(p["my"]))
    assessment = presentation.plastic_action_assessment(p)
    status = assessment["status"]
    verdict = presentation.plastic_assessment_text(assessment)
    if status == "PASS":
        st.success(verdict)
    elif status in {"FAIL", "INVALID"}:
        st.error(verdict)
    else:
        _manual_warning(st, "calculation-warning", verdict)

    st.markdown("#### Applied actions")
    a1, a2, a3 = st.columns(3)
    a1.metric(r"Axial $N_{Ed}$ (tension +)", f"{inp['P_pl']:.3f} kN")
    applied = p.get("applied")
    moment_help = ("Applied moment checked against the closed M-M capacity envelope."
                   if assessment["assessed"] else assessment["detail"].capitalize() + ".")
    a2.metric(r"$M_{x,Ed}$", "-" if applied is None else f"{applied[0]:.3f} kNm",
              help=moment_help)
    a3.metric(r"$M_{y,Ed}$", "-" if applied is None else f"{applied[1]:.3f} kNm",
              help=moment_help)

    st.markdown("#### Directional capacity extrema")
    st.dataframe(
        {
            "Bending axis": ["Mx", "My"],
            "Negative capacity (kNm)": [round(min_mx, 3), round(min_my, 3)],
            "Positive capacity (kNm)": [
                round(p["max_mx"], 3), round(p["max_my"], 3)],
        },
        hide_index=True,
        width="stretch",
    )
    st.plotly_chart(
        viz.interaction_figure(p["mx"], p["my"], applied=p.get("applied"),
                               angles=[pt["V"] for pt in p["points"]],
                               util=assessment.get("util"),
                               closed=p.get("closed", True)),
        width="stretch")

    # Default to the utilisation-governing angle (the state in the applied load's
    # direction) when a utilisation was checked; otherwise show the strongest-about-x
    # state, which is a sensible landmark for a capacity-only run.
    gov_i = p.get("util_gov")
    default_i = (gov_i if gov_i is not None and gov_i < len(pts)
                 else max(range(len(pts)), key=lambda i: pts[i]["Mx"]))
    # The sweep length varies with V.min/V.max/V.inc; clamp a stale selection.
    if st.session_state.get("pl_state", 0) >= len(pts):
        st.session_state["pl_state"] = default_i
    sel = st.selectbox("Neutral-axis state", range(len(pts)), index=default_i,
                       format_func=lambda i: (
                           f"{i + 1}: NA angle = {pts[i]['V']:.0f}{_DEG}"
                       ),
                       key="pl_state",
                       help="Inspect the section state at one swept neutral-axis angle.")
    pt = pts[sel]
    retained_state = presentation.plastic_state_rows(pt)
    hp = retained_state["halfplane"]
    na = viz.na_line_at(hp[0], hp[1], hp[2], inp["extent"],
                        bbox=_outline_bbox(inp["outer"]))
    cL, cR = st.columns([3, 2])
    with cL:
        bar_xy = [(b[0], b[1], b[2]) for b in inp["bars"]]
        tendon_xy = [(t[0], t[1], t[2]) for t in inp["tendons"]]
        # Colour and hover text use the accepted material states retained by the
        # plastic solver. A tendon on the compression side may therefore remain
        # tensile because its locked-in prestrain is already included.
        bar_states = [
            row for row in retained_state["elements"]
            if row.get("element_type") == "Bar"
        ]
        tendon_states = [
            row for row in retained_state["elements"]
            if row.get("element_type") == "Tendon"
        ]
        state_colour = lambda row: (
            viz.BAR_TENSION
            if row.get("strain_permille", 0.0) >= 0.0
            else viz.BAR_COMPRESSION
        )
        bar_colors = [state_colour(row) for row in bar_states]
        tendon_colors = [state_colour(row) for row in tendon_states]
        bar_hover = _plastic_state_hover(bar_states)
        tendon_hover = _plastic_state_hover(tendon_states)
        st.plotly_chart(
            viz.section_figure(inp["outer"], inp["holes"], bar_xy, na_line=na,
                               bar_colors=bar_colors, tendons=tendon_xy,
                               tendon_colors=tendon_colors,
                               zones=viz.compression_zones(inp["outer"], hp),
                               title=f"Section at NA angle = {pt['V']:.0f}{_DEG} "
                                     "(tension + / compression -)",
                               show_labels=False, scale=_MM, unit="mm",
                               bar_hover=bar_hover, tendon_hover=tendon_hover,
                               bar_ids=[item["id"] for item in inp.get("bar_elements", [])],
                               tendon_ids=[item["id"] for item in inp.get("tendon_elements", [])],
                               geometry_hover=False),
            width="stretch")
        st.caption("Blue/plain markers are tension (+); vermillion/x markers are "
                   "compression (-). Bar circles and tendon diamonds identify the "
                   "element type. Hover an element for its ID, design stress and "
                   "strain; complete values are tabulated beside the figure.")
    with cR:
        # Split the bar strain into its tensile and compression extreme only when
        # there are mild bars that are active in compression (a tendon-only section has
        # no mild bar to compress). Also guard on the field being present so a pre-v0.40
        # reused payload (which lacks eps_s_comp) degrades to the single strain.
        active_comp = (any(material.active_in_compression
                           for material in (inp.get("bar_materials")
                                            or [inp["steel"]]))
                       and bool(inp["bars"])
                       and "eps_s_comp" in pt)
        compression_depth_mm = presentation.plastic_compression_depth_mm(pt)
        compression_depth_text = (
            "-"
            if compression_depth_mm is None
            else f"{compression_depth_mm:.3f} mm"
        )
        lines = [
            f"- **Source state**: {presentation.action_set_text(inp, 'plastic', include_source=False)}; "
            f"$N_{{Ed}} = {inp['P_pl']:.3f}$ kN; "
            f"NA angle = {pt['V']:.0f}{_DEG} (sweep point {sel + 1})",
            f"- **$M_x$ / $M_y$**: {pt['Mx']:.3f} / {pt['My']:.3f} kNm",
            f"- **Curvature $\\kappa$**: {pt['kappa']:.4g} 1/m",
            f"- **Compression resultant $F_{{comp}}$**: "
            f"{pt['comp_force']:.3f} kN",
            f"- **Compression-zone depth $c$**: {compression_depth_text}",
            f"- **Internal lever arm $z$**: {pt['lever'] * _MM:.3f} mm",
            f"- **Lever-arm components $z_x$ / $z_y$**: "
            f"{pt['dx'] * _MM:.3f} / {pt['dy'] * _MM:.3f} mm",
            f"- **Concrete strain $\\varepsilon_c$**: {pt['eps_c']:.3f} %",
        ]
        if active_comp:
            lines.append(f"- **Steel strain, tension $\\varepsilon_{{s,t}}$**: "
                         f"{pt['eps_s']:.3f} %")
            lines.append(f"- **Steel strain, compression $\\varepsilon_{{s,c}}$**: "
                         f"{pt['eps_s_comp']:.3f} %")
        else:
            lines.append(f"- **Steel strain $\\varepsilon_s$**: {pt['eps_s']:.3f} %")
        if inp["tendons"]:
            lines.append(f"- **Tendon strain $\\varepsilon_p$**: {pt['eps_cable']:.3f} %")
        lines.append(f"- **NA intercepts**: x {_fmt(pt['na_x'] * _MM)}, "
                     f"y {_fmt(pt['na_y'] * _MM)} mm")
        st.markdown("\n".join(lines))
        st.caption("Strains are tension-positive (compression negative), agreeing "
                   "with N and the stresses -- so a crushing concrete strain reads "
                   "negative.")

    effective_depths = p.get("effective_depths") or ()
    st.markdown("#### Face-specific effective depth")
    if not effective_depths:
        st.caption(
            "This result does not include face-specific effective depth. "
            "Recalculate to show it."
        )
    else:
        st.caption(
            "Each d is measured from the opposite extreme concrete fibre to the "
            "centroid of the listed mild bars. Four face-aligned values show the "
            "available depth for either bending direction, including off-axis states."
        )
        st.dataframe(
            {
                "Bending axis": [row["axis"] for row in effective_depths],
                "Tension face": [
                    viz.tension_face_label(row["tension_low"], row["axis"])
                    for row in effective_depths
                ],
                "d (mm)": [
                    round(row["d_mm"], 3) if row["d_mm"] > 0.0 else None
                    for row in effective_depths
                ],
                "Tension-bar IDs": [
                    ", ".join(str(value) for value in row["asl_bar_ids"])
                    or "none"
                    for row in effective_depths
                ],
                "Asl (mm2)": [
                    round(row["asl_mm2"], 3) for row in effective_depths
                ],
                "Asl centroid": [
                    (
                        f"{row['coordinate']} = "
                        f"{row['asl_cg_m'] * _MM:.3f} mm"
                        if row["asl_cg_m"] is not None
                        else "-"
                    )
                    for row in effective_depths
                ],
                "Calculated arm component": [
                    row["arm_component"] for row in effective_depths
                ],
            },
            hide_index=True,
            width="stretch",
            column_config={
                "d (mm)": st.column_config.NumberColumn(format="%.3f"),
                "Asl (mm2)": st.column_config.NumberColumn(format="%.3f"),
            },
        )

    state_rows = retained_state
    with st.expander("Selected neutral-axis state - calculation details", expanded=False):
        st.caption(
            f"Point-by-point design stress and compatible strain at NA angle = "
            f"{pt['V']:.0f}{_DEG}. Signs are tension positive; reinforcement force "
            "is stress x entered area."
        )
        concrete_rows = state_rows["concrete"]
        if concrete_rows:
            st.markdown("**Concrete corner response**")
            st.dataframe(
                {
                    "Point": [row["point_no"] for row in concrete_rows],
                    "Ring": [row["ring"] for row in concrete_rows],
                    "Ring point": [row["ring_point_no"] for row in concrete_rows],
                    "x (mm)": [round(row["x_mm"], 2) for row in concrete_rows],
                    "y (mm)": [round(row["y_mm"], 2) for row in concrete_rows],
                    f"Strain ({_EPS}, {_PERMILLE})": [
                        round(row["strain_permille"], 5) for row in concrete_rows],
                    f"Design stress ({_SIGMA}c, MPa)": [
                        round(row["stress_mpa"], 3) for row in concrete_rows],
                },
                hide_index=True,
                width="stretch",
                height=min(35 * (len(concrete_rows) + 1) + 3, 420),
            )
        element_rows = state_rows["elements"]
        if element_rows:
            st.markdown("**Reinforcement and tendon response**")
            material_labels = [
                (f"{row.get('material_id')} - {row.get('material_name')}"
                 if row.get("material_name") else row.get("material_id"))
                for row in element_rows
            ]
            st.dataframe(
                {
                    "Element": [row["element_id"] for row in element_rows],
                    "Material": material_labels,
                    "State": [row["state"] for row in element_rows],
                    "x (mm)": [round(row["x_mm"], 2) for row in element_rows],
                    "y (mm)": [round(row["y_mm"], 2) for row in element_rows],
                    "Area (mm2)": [round(row["area_mm2"], 2) for row in element_rows],
                    f"Strain ({_EPS}, {_PERMILLE})": [
                        round(row["strain_permille"], 5) for row in element_rows],
                    f"Design stress ({_SIGMA}, MPa)": [
                        round(row["stress_mpa"], 3) for row in element_rows],
                    "Force (kN)": [round(row["force_kn"], 3) for row in element_rows],
                },
                hide_index=True,
                width="stretch",
                height=min(35 * (len(element_rows) + 1) + 3, 420),
            )

    with st.expander("Full results table (per neutral-axis angle)"):
        # Size the table to all rows so the page scrolls, not the table itself.
        steel_comp = (any(material.active_in_compression
                          for material in (inp.get("bar_materials")
                                           or [inp["steel"]]))
                      and bool(inp["bars"])
                      and bool(pts) and "eps_s_comp" in pts[0])
        st.dataframe(_plastic_table(pts, bool(inp["tendons"]), steel_comp),
                     hide_index=True, width="stretch",
                     height=35 * (len(pts) + 1) + 3)


def interaction_view(inp, results):
    """Axial-moment (N-M) interaction diagrams about both bending axes."""
    if not inp.get("interaction"):
        st.info("Enable 'N-M interaction diagrams' in Analysis settings, "
                "then run a Plastic or Both analysis and press Calculate.")
        return
    if not results or "plastic" not in results or "interaction" not in results["plastic"]:
        st.info("Run a Plastic or Both analysis, then press Calculate.")
        return
    d = results["plastic"]["interaction"]
    dx, dy = d["x"], d["y"]
    if not dx.get("converged", True) or not dy.get("converged", True):
        st.error("INVALID - N-M boundary | One or more points did not converge; "
                 "values are diagnostic only.")
    # The pure-axial extremes (squash load, tension limit) are the same for either
    # bending axis; take them across both boundaries so the metrics are consistent.
    # N is tension-positive, so the squash (compression) load is the minimum and the
    # tension limit the maximum.
    all_N = list(dx["N"]) + list(dy["N"])
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Squash load $N_c$", f"{min(all_N):.3f} kN")
    m2.metric("Tension limit $N_t$", f"{max(all_N):.3f} kN")
    m3.metric("Max $M_x$", f"{max(dx['M']):.3f} kNm")
    m4.metric("Max $M_y$", f"{max(dy['M']):.3f} kNm")
    show_applied = inp.get("check_util")
    cL, cR = st.columns(2)
    with cL:
        st.plotly_chart(viz.interaction_nm_figure(
            dx["N"], dx["M"], axis="x",
            applied=dx.get("applied") if show_applied else None,
            title="N-Mx interaction"), width="stretch")
    with cR:
        st.plotly_chart(viz.interaction_nm_figure(
            dy["N"], dy["M"], axis="y",
            applied=dy.get("applied") if show_applied else None,
            title="N-My interaction"), width="stretch")
    st.caption(
        "Each curve traces capacity from pure tension to squash load. The marked "
        "point is the applied plastic action; points inside the boundary are within "
        "capacity. Hover for $N$ and $M$."
    )
    with st.expander("Numerical N-M boundary (all points)", expanded=False):
        rows = presentation.nm_boundary_rows(d)
        display_rows = [
            {
                "Point": row["Point"],
                "N, Mx boundary (kN)": (
                    None if row["N, Mx boundary (kN)"] is None
                    else round(row["N, Mx boundary (kN)"], 3)),
                "Mx (kNm)": (
                    None if row["Mx (kNm)"] is None
                    else round(row["Mx (kNm)"], 3)),
                "N, My boundary (kN)": (
                    None if row["N, My boundary (kN)"] is None
                    else round(row["N, My boundary (kN)"], 3)),
                "My (kNm)": (
                    None if row["My (kNm)"] is None
                    else round(row["My (kNm)"], 3)),
            }
            for row in rows
        ]
        st.dataframe(
            display_rows,
            hide_index=True,
            width="stretch",
            height=min(35 * (len(display_rows) + 1) + 3, 560),
        )
        st.caption("The point order is the exact plotted boundary order. Separate "
                   "axial-force columns are shown because the Mx and My traces "
                   "may use different numerical points.")


def _calculation_output_metric(box, label, output):
    """Render one output quantity without an acceptance verdict."""
    value = output.get("value")
    unit = output.get("unit") or ""
    value_text = "-" if value is None else f"{value:.3f} {unit}".strip()
    box.metric(label, value_text)
    state = output.get("calculation_state", "NOT CALCULATED")
    governing = output.get("governing")
    note = state if not governing else f"{state}; governing {governing}"
    box.caption(note)


def elastic_view(inp, results, *, global_results=None):
    """Cracked-section elastic stresses: peak concrete, neutral axis, the section
    diagnostic and per-bar stresses, matching the handcalc verification."""
    global_results = results if global_results is None else global_results
    heightened = (global_results or {}).get("heightened_crack_control")
    if not results or "elastic" not in results:
        if heightened:
            _heightened_crack_control_panel(heightened)
        else:
            st.info("Run an Elastic or Both analysis, then press Calculate.")
        return
    e = results["elastic"]
    if not e.get("converged", True):
        st.error("INVALID - Elastic result | The analysis did not converge; values are "
                 "diagnostic only.")

    st.markdown("### Elastic stress outputs")
    checks = e.get("stress_outputs", {})
    enabled = [
        ("Concrete compression", checks.get("concrete", {})),
        ("Reinforcement tension", checks.get("reinforcement", {})),
    ]
    if inp.get("tendons"):
        enabled.append(("Tendon tension", checks.get("prestress", {})))
    metric_cols = st.columns(len(enabled))
    for col, (label, output) in zip(metric_cols, enabled):
        _calculation_output_metric(col, label, output)
    st.caption(
        "Concrete compression and longitudinal reinforcement/tendon tension are "
        "reported for the actual named Elastic action. No stress limit is applied."
    )

    # Modular ratios are derived per assigned material.
    ec_mpa = inp["conc_Ec"] * 1000.0
    ratios = []
    for element, material in zip(inp.get("bar_elements", []),
                                 inp.get("bar_materials", [])):
        ratios.append((element["material_id"], material))
    for element, material in zip(inp.get("tendon_elements", []),
                                 inp.get("tendon_materials", [])):
        ratios.append((element["material_id"], material))
    unique_ratios = {material_id: material for material_id, material in ratios}
    if unique_ratios:
        ratio_txt = "; ".join(
            f"{material_id}: $n_s={material.Es / ec_mpa:.3f}$, "
            f"$n_l={material.Es * (1.0 + inp['el_phi']) / ec_mpa:.3f}$"
            for material_id, material in unique_ratios.items()
        )
        st.caption("Derived modular ratios - " + ratio_txt + ".")

    # The tendon prestress is applied automatically from the initial strain, so N
    # is the external force only; show the equivalent prestress action that was added.
    ps = e.get("prestress")
    if ps is not None:
        # ps[0] is the tendon tension resultant; the prestress precompresses the
        # section, so as an axial action (tension-positive) it is a compression.
        st.caption(f"Equivalent tendon-prestress action: $N={-ps[0]:.3f}$ kN, "
                   f"$M_x$ = {ps[1]:.3f} kNm, $M_y$ = {ps[2]:.3f} kNm "
                   r"(added to the external $N$ and $M$; $N$ is tension-positive).")

    # The neutral axis and the compression/tension zones only make sense when the
    # concrete actually carries compression; a fully tensile case has none.
    has_comp = e["max_conc"] > 0.0
    if has_comp:
        st.caption(f"Neutral-axis intercepts (for concrete stress): "
                   f"x {_fmt(e['na_x'] * _MM)} mm,  y {_fmt(e['na_y'] * _MM)} mm")
    else:
        st.caption("The concrete carries no compression (the section is fully "
                   "cracked in tension); no neutral axis is shown.")

    hp = viz.elastic_halfplane(e["na_x"], e["na_y"], e["max_conc_xy"]) if has_comp else None
    na = (viz.na_line_at(hp[0], hp[1], hp[2], inp["extent"],
                         bbox=_outline_bbox(inp["outer"])) if hp else None)
    zones = viz.compression_zones(inp["outer"], hp) if hp else None
    # Tendons fold into the bar set for the solve, but are drawn as diamonds (bars
    # as circles), each coloured by its stress sign -- consistent with the other
    # views. The stress list runs bars first, then tendons.
    nb = len(inp["bars"])
    bar_xy = [(b[0], b[1], b[2]) for b in inp["bars"]]
    tendon_xy = [(t[0], t[1], t[2]) for t in inp["tendons"]]
    sign = lambda s: viz.BAR_TENSION if s >= 0 else viz.BAR_COMPRESSION
    bar_colors = [sign(s) for s in e["total"][:nb]]
    tendon_colors = [sign(s) for s in e["total"][nb:]]
    element_rows = e.get("elements", [])
    bar_states = [
        row for row in element_rows if row.get("element_type") == "Bar"
    ]
    tendon_states = [
        row for row in element_rows if row.get("element_type") == "Tendon"
    ]
    section_col, strain_col = st.columns([3, 2])
    with section_col:
        st.plotly_chart(
            viz.section_figure(inp["outer"], inp["holes"], bar_xy,
                               bar_colors=bar_colors,
                               tendons=tendon_xy, tendon_colors=tendon_colors,
                               na_line=na, zones=zones, show_labels=False,
                               scale=_MM, unit="mm",
                               title="Elastic state (tension + / compression -)",
                               bar_ids=[item["id"] for item in inp.get("bar_elements", [])],
                               tendon_ids=[item["id"] for item in inp.get("tendon_elements", [])],
                               bar_hover=_elastic_state_hover(bar_states),
                               tendon_hover=_elastic_state_hover(tendon_states),
                               corner_hover=_elastic_corner_hover(
                                   e.get("concrete_corners", [])
                               ),
                               geometry_hover=False),
            width="stretch")
        st.caption("Blue/plain markers are tension (+); vermillion/x markers are "
                   "compression (-). Bar circles and tendon diamonds identify the "
                   "element type. Hover for material, stress and strain; "
                   "geometry remains in the complete table below.")
    with strain_col:
        st.plotly_chart(
            viz.elastic_strain_figure(
                e.get("concrete_corners"), e.get("elements"),
                e.get("stress_plane"), ec_mpa=inp["conc_Ec"] * 1000.0),
            width="stretch")

    # Complete, explicitly typed element evidence: no tendon is called a bar, and
    # geometry/area/strain stay beside every stress component for direct QA.
    st.markdown("**Reinforcement and tendon response (tension +)**")
    if element_rows:
        material_labels = [
            (f"{row.get('material_id')} - {row.get('material_name')}"
             if row.get("material_name") else row.get("material_id"))
            for row in element_rows
        ]
        st.dataframe(
            {
                "Element": [r["element_id"] for r in element_rows],
                "Material": material_labels,
                "x (mm)": [round(r["x_mm"], 2) for r in element_rows],
                "y (mm)": [round(r["y_mm"], 2) for r in element_rows],
                "Area (mm2)": [round(r["area_mm2"], 2) for r in element_rows],
                f"Strain ({_EPS}, {_PERMILLE})": [
                    round(r["strain_permille"], 5) for r in element_rows],
                "Total (MPa)": [round(r["total_mpa"], 3) for r in element_rows],
                "Long (MPa)": [round(r["long_mpa"], 3) for r in element_rows],
                "Dif (MPa)": [round(r["dif_mpa"], 3) for r in element_rows],
                "RST1 (MPa)": [round(r["rst1_mpa"], 3) for r in element_rows],
            },
            hide_index=True, width="stretch",
            height=min(35 * (len(element_rows) + 1) + 3, 560))
    st.caption(
        "**Total** = long + short  \n"
        "**Long** = long-term alone  \n"
        "**Dif** = total - long  \n"
        "**RST1** = instantaneous response with the long-term concrete stresses "
        "neutralised.")

    corner_rows = e.get("concrete_corners", [])
    if corner_rows:
        with st.expander("Concrete corner stress/strain details", expanded=False):
            st.dataframe(
                {
                    "Point": [r["point_no"] for r in corner_rows],
                    "Ring": [r["ring"] for r in corner_rows],
                    "Ring point": [r["ring_point_no"] for r in corner_rows],
                    "x (mm)": [round(r["x_mm"], 2) for r in corner_rows],
                    "y (mm)": [round(r["y_mm"], 2) for r in corner_rows],
                    f"Strain ({_EPS}, {_PERMILLE})": [
                        round(r["strain_permille"], 5) for r in corner_rows],
                    f"Concrete stress ({_SIGMA}c, MPa)": [
                        round(r["stress_mpa"], 3) for r in corner_rows],
                },
                hide_index=True, width="stretch",
                height=min(35 * (len(corner_rows) + 1) + 3, 560))
            st.caption("Cracked concrete carries compression only. Compatible "
                       "tensile strains remain in the plane while concrete tensile "
                       "stress is reported as zero.")

    _elastic_sls_section(inp, e)
    if heightened:
        _heightened_crack_control_panel(heightened)


def _elastic_sls_section(inp, e):
    """Serviceability sub-report inside the elastic view: the cracking threshold
    and transformed section properties (always); crack width is an independent
    opt-in. The cracking decision is on the *total* (long + short) load -- cracking
    is triggered by the peak load the section ever sees and is irreversible -- while
    the crack width is reported for both the user-defined sustained and
    instantaneous action parts."""
    if "cracked" not in e:
        return
    show_cw = e.get("show_cw", False)
    st.divider()
    st.markdown("#### Cracking and crack width")
    if not e.get("converged", True):
        st.error("INVALID - Cracking classification | Elastic solve did not "
                 "converge; values are diagnostic only.")
    elif e["cracked"]:
        governing_text = (
            "fixed prestress already reaches the tensile threshold"
            if inp.get("tendons") and e["lambda_cr"] == 0.0
            else "governing long-term/total action"
        )
        _manual_warning(
            st,
            "calculation-warning",
            f"CRACKED | $\\lambda_{{cr}}$ {e['lambda_cr']:.3f} | "
            + governing_text,
        )
    else:
        lam = "infinite" if math.isinf(e["lambda_cr"]) else f"{e['lambda_cr']:.3f}"
        st.success(f"UNCRACKED | $\\sigma_{{ct}}$ {e['sigma_ct']:.3f} MPa <= "
                   f"$f_{{ctm}}$ {e['fctm']:.3f} MPa | "
                   f"$\\lambda_{{cr}}$ {lam}")

    if inp.get("tendons"):
        threshold_help = (
            "Factor on the external N/M actions to first cracking. Locked-in "
            "prestress remains fixed; prestress alone above fctm gives "
            "lambda_cr = 0. Otherwise lambda_cr < 1 is cracked and "
            "lambda_cr >= 1 is uncracked."
        )
    else:
        threshold_help = (
            r"Proportional load factor to first cracking, "
            r"$f_{ctm}/\sigma_{ct,I}$ ($=M_{cr}/M$ in pure bending), taken as "
            "the governing (smaller) of the long-term and total actions. "
            "lambda_cr < 1 is cracked; lambda_cr >= 1 is uncracked."
        )
    st.metric(r"Cracking factor $\lambda_{cr}$",
              "inf" if math.isinf(e["lambda_cr"]) else f"{e['lambda_cr']:.3f}",
              help=threshold_help)

    pL, pR = st.columns(2)
    with pL:
        st.markdown(r"**Transformed section properties (at $n_l$)**")
        un = e["props_un"]
        cr = e.get("props_cr")
        rows = ["Area A (m2)", "Centroid x (m)", "Centroid y (m)",
                "Ix about x-axis (m4)", "Iy about y-axis (m4)", "Ixy (m4)"]
        keys = ["area", "cx", "cy", "Ix", "Iy", "Ixy"]
        data = {"Property": rows, "Uncracked": [f"{un[k]:.4g}" for k in keys]}
        if cr is not None:
            data["Cracked"] = [f"{cr[k]:.4g}" for k in keys]
        st.dataframe(data, hide_index=True, width="stretch")
        st.caption("Transformed ($n_l$-weighted) properties about the section "
                   "centroid; the cracked column drops the concrete in tension. "
                   "Ix resists Mx (bending about the x-axis).")
    with pR:
        if show_cw:
            _crack_width_panel(e)


def _heightened_crack_control_panel(result):
    """Render both retained Formula 7.100 NA systems and their provenance."""

    st.divider()
    st.markdown("#### DK NA heightened crack control")
    st.caption(
        f"{result.get('formula_identity', 'Formula 7.100 NA')} | Reference case "
        f"{result.get('reference_case_id', '-')}, ordinary crack-width method "
        f"{result.get('ordinary_crack_branch', '-')}."
    )
    required = result.get("governing_required_reinforcement_area_mm2")
    provided = result.get("provided_reinforcement_area_mm2")
    ratio = result.get("governing_comparison_ratio")
    h1, h2, h3 = st.columns(3)
    h1.metric(
        "Calculated required area",
        "-" if required is None else f"{required:.1f} mm2",
    )
    h2.metric(
        "Auto-derived provided area",
        "-" if provided is None else f"{provided:.1f} mm2",
    )
    h3.metric(
        "Required / provided",
        "-" if ratio is None else f"{ratio:.3f}",
    )
    status = str(result.get("governing_status") or "NOT ASSESSED")
    if status == "PROVIDED AREA BELOW CALCULATED REQUIREMENT":
        _manual_warning(st, "calculation-warning", status)
    else:
        st.info(status)
    basis_label = design_standards.get_design_basis(
        result["basis_key"]
    ).label
    systems = [result.get("fine") or {}, result.get("coarse") or {}]
    st.dataframe(
        [
            {
                "System": str(branch.get("crack_system") or "-").title(),
                "Ac,eff (mm2)": branch.get("effective_tension_area_mm2"),
                "As,req (mm2)": branch.get(
                    "required_reinforcement_area_mm2"
                ),
                "As,req / As,prov": branch.get("comparison_ratio"),
                "Status": branch.get("status"),
                "Governing": (
                    branch.get("crack_system")
                    == result.get("governing_crack_system")
                ),
            }
            for branch in systems
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        f"Basis: {basis_label}. Reinforcement surface: "
        f"{result.get('reinforcement_surface')}. Diameter "
        f"{result.get('bar_diameter_mm', 0.0):.3f} mm from "
        f"{result.get('diameter_source', '-')} (governing elements: "
        f"{', '.join(result.get('diameter_governing_element_ids') or ['-'])}); "
        "conservative modulus "
        f"{result.get('reinforcement_modulus_mpa', 0.0):.1f} MPa "
        "(governing materials: "
        f"{', '.join(result.get('modulus_governing_material_ids') or ['-'])})."
    )
    contributions = result.get("contributions") or []
    if contributions:
        with st.expander(
            "Reinforcement source details", expanded=False
        ):
            st.dataframe(
                [
                    {
                        "Element": row.get("element_id"),
                        "Material": row.get("material_id"),
                        "Area (mm2)": row.get("area_mm2"),
                        "Diameter (mm)": row.get("diameter_mm"),
                        "Diameter source": row.get("diameter_source"),
                        "Es (MPa)": row.get("reinforcement_modulus_mpa"),
                    }
                    for row in contributions
                ],
                hide_index=True,
                width="stretch",
            )


def _crack_width_panel(e):
    """Crack width (EC2 7.3.4) for the long-term and short-term load cases, side
    by side. The DK NA reports the fine and the coarse crack system (four columns);
    each bar's clear cover is taken from the geometry and the bar with the largest
    wk governs, reported per load case."""
    cl, cs = e.get("crack"), e.get("crack_short")
    clc, csc = e.get("crack_coarse"), e.get("crack_short_coarse")
    st.markdown(f"**Crack width $w_k$** ({e.get('crack_code', 'EC2 7.3.4')})")
    no_results = cl is None and cs is None and clc is None and csc is None
    outputs = e.get("crack_output", {})
    if not isinstance(outputs, dict):
        outputs = {}
    duration_columns = st.columns(2)
    retained_reasons = []
    for column, duration, label in zip(
        duration_columns,
        ("long_term", "short_term"),
        ("Long-term", "Short-term"),
        strict=True,
    ):
        output = outputs.get(duration, {})
        value = output.get("value")
        case = output.get("case") or "-"
        governing = output.get("governing") or "-"
        state = output.get("calculation_state", "NOT CALCULATED")
        criterion = output.get("criterion_mm")
        criterion_source = output.get("criterion_source")
        ratio = output.get("ratio")
        raw_reason = output.get("reason")
        reason = (
            presentation.result_reason(
                raw_reason,
                "crack",
                context=f"{duration} crack-width result reason",
            )
            if raw_reason
            else ""
        )
        if raw_reason:
            retained_reasons.append(reason)
        column.metric(
            f"{label} calculated crack width",
            "-" if value is None else f"{value:.3f} mm",
        )
        identity = f"branch {case}; longitudinal element {governing}"
        if criterion in (None, 0.0):
            comparison = "User limit: 0 mm; no comparison requested."
        else:
            comparison = (
                f"User limit: {criterion:.3f} mm"
                + (f" ({criterion_source})" if criterion_source else "")
                + (
                    f"; retained wk / limit ratio = {ratio:.3f}."
                    if ratio is not None
                    else "."
                )
            )
        column.caption(f"{state}; {identity}. {comparison}")
        if reason:
            (
                column.warning
                if state == "EXCEEDS USER-SPECIFIED LIMIT"
                else column.info
            )(reason)
    if no_results:
        if not retained_reasons:
            st.info(
                "No crack-width value was returned for this action. Review the "
                "inputs and calculation state."
            )
        return
    quants = ["wk (mm)", "sr,max (mm)", f"{_EPS}sm - {_EPS}cm",
              f"{_SIGMA}s (MPa)", f"{_RHO}p,eff", "hc,ef (m)", "cover c (mm)",
              f"element dia {_PHI} (mm)", "governing element"]
    keys = ["wk", "sr_max", "esm_ecm", "sigma_s", "rho_p_eff", "hc_ef", "cover",
            "phi", "element_id"]
    fmts = ["{:.3f}", "{:.3f}", "{:.3e}", "{:.3f}", "{:.4f}", "{:.3f}", "{:.3f}",
            "{:.3f}", "{}"]

    def column(c):
        if c is None:
            return ["-"] * len(keys)
        return [f.format(c[k]) for k, f in zip(keys, fmts)]

    has_coarse = clc is not None or csc is not None
    if has_coarse:
        # DK NA: fine and coarse crack systems, each for both load cases.
        data = {"Quantity": quants, "Long-term (fine)": column(cl),
                "Short-term (fine)": column(cs), "Long-term (coarse)": column(clc),
                "Short-term (coarse)": column(csc)}
    else:
        data = {"Quantity": quants, "Long-term": column(cl),
                "Short-term": column(cs)}
    st.dataframe(data, hide_index=True, width="stretch")
    st.caption("Governing (largest-$w_k$) element per load case; each element's "
               "clear cover is the distance to the nearest concrete face minus "
               "its radius.")

    cases = ([
        ("Long-term (fine)", cl),
        ("Short-term (fine)", cs),
        ("Long-term (coarse)", clc),
        ("Short-term (coarse)", csc),
    ] if has_coarse else [
        ("Long-term", cl),
        ("Short-term", cs),
    ])
    candidate_rows = []
    for case_name, case_result in cases:
        if not case_result:
            continue
        case_max = float(case_result.get("wk", 0.0))
        for rank, row in enumerate(case_result.get("candidates", []), start=1):
            wk = float(row["wk"])
            candidate_rows.append({
                "Case": case_name,
                "Rank": rank,
                "Status": ("Governing" if rank == 1 else
                           ("Within 10%" if case_max > 0.0 and wk >= 0.9 * case_max
                            else "Candidate")),
                "Element": row["element_id"],
                "x (mm)": round(row["x_mm"], 2),
                "y (mm)": round(row["y_mm"], 2),
                "Area (mm2)": round(row["area_mm2"], 2),
                "Cover (mm)": round(row["cover"], 2),
                f"{_PHI} (mm)": round(row["phi"], 2),
                f"{_SIGMA}s (MPa)": round(row["sigma_s"], 3),
                "Ac,eff (m2)": round(row["ac_eff"], 6),
                f"{_EPS}sm-{_EPS}cm": round(row["esm_ecm"], 7),
                "sr,max (mm)": round(row["sr_max"], 2),
                "wk (mm)": round(wk, 3),
            })
    if candidate_rows:
        with st.expander("All crack-width candidates", expanded=False):
            st.dataframe(candidate_rows, hide_index=True, width="stretch",
                         height=min(35 * (len(candidate_rows) + 1) + 3, 560))
            st.caption("Sorted by crack width within each case. 'Within 10%' marks "
                       "near-governing elements for rapid sensitivity review.")
    member = e.get("crack_member")
    if member:
        st.caption(r"DK NA: cover-dependent $k_3 = 3.4(25/c)^{2/3}$, reported for both "
                   f"the fine and the coarse crack system (7.3.4(1): centroid-matched "
                   f"effective area, $w_k$ halved). Member type = {member} (the "
                   f"(h-x)/3 effective-height term applies to slabs and prestressed "
                   f"members, fine system only).")


_FATIGUE_STATUS_COLOURS = {
    "PASS": "background-color: #E8F5E9; color: #1B5E20; font-weight: 600",
    "FAIL": "background-color: #FDECEC; color: #9B1C1C; font-weight: 600",
    "INVALID": "background-color: #FDECEC; color: #9B1C1C; font-weight: 600",
    "REVIEW": "background-color: #FFF4D6; color: #7A4E00; font-weight: 600",
    "STALE": "background-color: #FFF4D6; color: #7A4E00; font-weight: 600",
    "OK": "background-color: #E8F5E9; color: #1B5E20",
    "BOUNDED": "background-color: #E8F0FE; color: #174EA6",
}


def _fatigue_result_table(rows, *, height=420):
    """Render a compact fatigue table with a consistent status column."""

    frame = pd.DataFrame(rows)
    if frame.empty:
        st.info("No results for this check.")
        return
    if "Status" in frame.columns:
        frame = frame.style.map(
            lambda item: _FATIGUE_STATUS_COLOURS.get(str(item), ""),
            subset=["Status"],
        )
    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        height=min(35 * (len(rows) + 1) + 3, height),
    )


def _fatigue_status_callout(status, text):
    message = f"{status} - {text}"
    if status == "PASS":
        st.success(message)
    elif status in {"FAIL", "INVALID"}:
        st.error(message)
    else:
        _manual_warning(st, "calculation-warning", message)


def _fatigue_map_signature(inp, spectrum):
    outer = inp.get("outer")
    holes = inp.get("holes")
    search = fatigue_presentation.value(spectrum, "concrete_search")
    return (
        tuple(
            tuple(float(coordinate) for coordinate in point)
            for point in ([] if outer is None else outer)
        ),
        tuple(
            tuple(
                tuple(float(coordinate) for coordinate in point)
                for point in ring
            )
            for ring in ([] if holes is None else holes)
        ),
        tuple(
            (
                kind,
                str(record.get("id") or ""),
                float(record.get("x_mm", 0.0)),
                float(record.get("y_mm", 0.0)),
            )
            for kind, records in (
                ("bar", inp.get("bar_elements") or []),
                ("tendon", inp.get("tendon_elements") or []),
            )
            for record in records
        ),
        str(fatigue_presentation.value(spectrum, "spectrum_name", "")),
        tuple(
            (
                str(fatigue_presentation.value(item, "element_id", "")),
                fatigue_presentation.evidence_number(
                    fatigue_presentation.value(item, "utilisation")
                ),
                fatigue_presentation.evidence_number(
                    fatigue_presentation.value(item, "damage_utilisation")
                ),
                fatigue_presentation.evidence_number(
                    fatigue_presentation.value(item, "yield_utilisation")
                ),
            )
            for item in fatigue_presentation.items(spectrum, "reinforcement")
        ),
        tuple(
            (
                fatigue_presentation.value(item, "fibre_index"),
                fatigue_presentation.finite_number(
                    fatigue_presentation.value(item, "x_m")
                ),
                fatigue_presentation.finite_number(
                    fatigue_presentation.value(item, "y_m")
                ),
                fatigue_presentation.evidence_number(
                    fatigue_presentation.value(item, "utilisation")
                ),
                fatigue_presentation.evidence_number(
                    fatigue_presentation.value(item, "damage")
                ),
                fatigue_presentation.evidence_number(
                    fatigue_presentation.value(item, "stress_utilisation")
                ),
                fatigue_presentation.evidence_number(
                    fatigue_presentation.value(
                        item, "equivalent_utilisation"
                    )
                ),
            )
            for item in fatigue_presentation.items(spectrum, "concrete")
        ),
        (
            None
            if search is None
            else (
                bool(fatigue_presentation.value(search, "converged", False)),
                fatigue_presentation.finite_number(
                    fatigue_presentation.value(search, "x_m")
                ),
                fatigue_presentation.finite_number(
                    fatigue_presentation.value(search, "y_m")
                ),
                fatigue_presentation.evidence_number(
                    fatigue_presentation.value(search, "damage")
                ),
                fatigue_presentation.evidence_number(
                    fatigue_presentation.value(search, "upper_damage")
                ),
                fatigue_presentation.evidence_number(
                    fatigue_presentation.value(search, "absolute_gap")
                ),
                fatigue_presentation.evidence_number(
                    fatigue_presentation.value(search, "relative_gap")
                ),
                fatigue_presentation.value(search, "divisions"),
                fatigue_presentation.value(search, "boxes_evaluated"),
                fatigue_presentation.value(search, "points_evaluated"),
            )
        ),
    )


def _fatigue_reinforcement_panel(payload, spectrum):
    rows = fatigue_presentation.reinforcement_rows(spectrum)
    if not rows:
        st.info("Reinforcement fatigue is not included in this calculation.")
        return
    _fatigue_result_table([
        {
            "Element": row["element_id"],
            "Type": row["kind"].capitalize(),
            "Detail": row["detail_id"],
            "Diameter [mm]": row["diameter_mm"],
            "Simplified screen": row["screen_status"],
            f"Screen {_DELTA}{_SIGMA} [MPa]": row["screen_range_mpa"],
            "Screen limit [MPa]": row["screen_threshold_mpa"],
            "Miner D": row["damage"],
            "Yield / proof util. [%]": (
                None if row["yield_utilisation"] is None
                else 100.0 * row["yield_utilisation"]
            ),
            "Governing": row["governing"],
            "Utilisation [%]": (
                None if row["utilisation"] is None
                else 100.0 * row["utilisation"]
            ),
            "Status": row["status"],
        }
        for row in rows
    ])

    options = [row["element_id"] for row in rows]
    preferred = str(
        fatigue_presentation.value(
            spectrum, "governing_reinforcement_id", options[0]
        )
        or options[0]
    )
    if preferred not in options:
        preferred = options[0]
    key = "_fatigue_result_element"
    if st.session_state.get(key) not in options:
        st.session_state[key] = preferred
    selected = st.selectbox(
        "Reinforcement element",
        options,
        key=key,
        help="Select an element for its S-N curve and bin results.",
    )
    result = fatigue_presentation.result_by_element(spectrum, selected)
    properties = fatigue_presentation.reinforcement_property(payload, selected)
    if result is None or properties is None:
        st.error("INVALID - Assigned fatigue properties are unavailable.")
        return

    screen = fatigue_presentation.simplified_reinforcement_screen(result)
    st.markdown("**Simplified stress-range screen**")
    _fatigue_result_table([{
        "Status": screen["status"],
        "Detail class": screen["detail_class"],
        "Range basis": screen["range_basis"].capitalize(),
        f"Governing {_DELTA}{_SIGMA} [MPa]": screen["governing_range_mpa"],
        "Limit [MPa]": screen["threshold_mpa"],
        "Utilisation [%]": (
            None
            if screen["utilisation"] is None
            else 100.0 * screen["utilisation"]
        ),
        "Governing bin": screen["governing_bin"],
        "Total cycles": screen["total_cycles"],
    }], height=120)
    if screen["reason"]:
        st.caption(presentation.result_reason(
            screen["reason"],
            "fatigue",
            context="simplified fatigue-screen reason",
        ))
    if screen["source"]:
        st.caption("Reference: " + screen["source"])
    st.caption(
        "A passing simplified screen makes the detailed stress-range check "
        "unnecessary for this element, but Sector still reports "
        "the S-N/Miner calculation. Yield or proof stress remains independent."
    )

    gamma_s = (payload.get("partial_factors") or {}).get("gamma_s")
    bin_rows = fatigue_presentation.reinforcement_bin_rows(result)
    property_signature = tuple(
        fatigue_presentation.value(properties, field)
        for field in (
            "element_id", "detail_id", "diameter_mm", "n_star", "k1", "k2",
            "delta_sigma_rsk_mpa", "fytk_mpa", "fyck_mpa",
            "bond_ratio_xi", "bond_equivalent_diameter_mm",
        )
    )
    bin_signature = tuple(
        tuple(row.get(name) for name in sorted(row))
        for row in bin_rows
    )
    left, right = st.columns([3, 2])
    with left:
        st.plotly_chart(
            _memo_fig(
                "fatigue_sn",
                (property_signature, float(gamma_s), bin_signature),
                lambda: viz.fatigue_sn_figure(
                    result, properties, gamma_s,
                ),
            ),
            width="stretch",
        )
    with right:
        st.plotly_chart(
            _memo_fig(
                "fatigue_reinforcement_damage",
                (selected, bin_signature),
                lambda: viz.fatigue_damage_figure(result),
            ),
            width="stretch",
        )

    st.markdown("**Assigned S-N and strength data**")
    _fatigue_result_table([{
        "Element": selected,
        "Detail": fatigue_presentation.value(properties, "detail_id", "-"),
        "N*": fatigue_presentation.value(properties, "n_star"),
        "k1": fatigue_presentation.value(properties, "k1"),
        "k2": fatigue_presentation.value(properties, "k2"),
        f"{_DELTA}{_SIGMA}Rsk [MPa]": fatigue_presentation.value(
            properties, "delta_sigma_rsk_mpa"
        ),
        "fyk / proof [MPa]": fatigue_presentation.value(
            properties, "fytk_mpa"
        ),
        "Bond factor": (
            fatigue_presentation.value(properties, "bond_ratio_xi") or "-"
        ),
    }], height=120)
    st.caption(
        f"$\\gamma_{{Ff}}={(payload.get('partial_factors') or {}).get('gamma_ff'):g}$ "
        r"is applied to the cyclic actions; the design S-N curve uses $\gamma_s$."
    )

    st.markdown("**Bin results**")
    _fatigue_result_table([
        {
            "Bin": row["bin"],
            "Cycles": row["cycles"],
            "Status": row["status"],
            "Range state": row["range_state"],
            "Long stress [MPa]": row["stress_long_mpa"],
            "Elastic total [MPa]": row["stress_total_elastic_mpa"],
            "Fatigue total [MPa]": row["stress_total_mpa"],
            "Design total [MPa]": row["stress_total_design_mpa"],
            f"Elastic {_DELTA}{_SIGMA} [MPa]": (
                row["stress_range_elastic_mpa"]
            ),
            f"Fatigue {_DELTA}{_SIGMA} [MPa]": row["stress_range_mpa"],
            f"Design {_DELTA}{_SIGMA} [MPa]": (
                row["design_stress_range_mpa"]
            ),
            f"{_DELTA}{_SIGMA}Rd [MPa]": row["delta_sigma_rd_mpa"],
            "N_R": row["cycles_to_failure"],
            "Miner D": row["damage"],
            "Yield / proof util. [%]": (
                None if row["yield_utilisation"] is None
                else 100.0 * row["yield_utilisation"]
            ),
            "Bond factor": row["bond_adjustment"],
            "Bond method": row["bond_method"],
        }
        for row in bin_rows
    ], height=560)
    st.caption(
        "Elastic total and elastic stress range come directly from the Elastic analysis. "
        "Fatigue values include the reported bond transformation; design values "
        r"also include the action-level $\gamma_{Ff}$ factor."
    )


def _fatigue_concrete_panel(spectrum):
    rows = fatigue_presentation.concrete_rows(spectrum)
    if not rows:
        st.info("Concrete fatigue is not included in this calculation.")
        return
    equivalent_method = any(
        row.get("equivalent_utilisation") is not None for row in rows
    )
    criterion_label = (
        "Equivalent util. [%]" if equivalent_method else "Miner D"
    )
    st.caption(f"Method: {rows[0]['method']}")
    _fatigue_result_table([
        {
            "Fibre": row["fibre_index"],
            "Source": row["source"],
            "x [mm]": row["x_mm"],
            "y [mm]": row["y_mm"],
            criterion_label: (
                100.0 * row["equivalent_utilisation"]
                if equivalent_method
                and row["equivalent_utilisation"] is not None
                else row["damage"]
            ),
            "Stress util. [%]": (
                None if row["stress_utilisation"] is None
                else 100.0 * row["stress_utilisation"]
            ),
            "Governing": row["governing"],
            "Utilisation [%]": (
                None if row["utilisation"] is None
                else 100.0 * row["utilisation"]
            ),
            "Status": row["status"],
        }
        for row in rows
    ], height=520)

    options = [row["fibre_index"] for row in rows]
    preferred = fatigue_presentation.value(
        spectrum, "governing_concrete_fibre", options[0]
    )
    if preferred not in options:
        preferred = options[0]
    key = "_fatigue_result_fibre"
    if st.session_state.get(key) not in options:
        st.session_state[key] = preferred
    selected = st.selectbox(
        "Concrete fibre",
        options,
        key=key,
        format_func=lambda index: next(
            (
                f"C{index} - {row['source']} "
                f"({row['x_mm']:.1f}, {row['y_mm']:.1f}) mm"
                for row in rows if row["fibre_index"] == index
            ),
            f"C{index}",
        ),
        help="Select a fixed fibre for its same-point concrete fatigue results.",
    )
    result = fatigue_presentation.result_by_fibre(spectrum, selected)
    if result is None:
        st.error("INVALID - Selected concrete fibre is unavailable.")
        return
    bin_rows = fatigue_presentation.concrete_bin_rows(result)
    bin_signature = tuple(
        tuple(row.get(name) for name in sorted(row))
        for row in bin_rows
    )
    st.plotly_chart(
        _memo_fig(
            "fatigue_concrete_damage",
            (selected, bin_signature),
            lambda: viz.fatigue_damage_figure(result),
        ),
        width="stretch",
    )

    search = fatigue_presentation.value(spectrum, "concrete_search")
    if search is not None:
        st.markdown("**Bounded governing-fibre search**")
        point_label = (
            "Point util. [%]" if equivalent_method else "Point D"
        )
        upper_label = (
            "Upper util. [%]" if equivalent_method else "Upper bound D"
        )
        point_value = fatigue_presentation.value(search, "damage")
        upper_value = fatigue_presentation.value(search, "upper_damage")
        absolute_gap = fatigue_presentation.value(search, "absolute_gap")
        _fatigue_result_table([{
            "Status": (
                "BOUNDED"
                if fatigue_presentation.value(search, "converged", False)
                else "INVALID"
            ),
            "x [mm]": 1000.0 * fatigue_presentation.value(search, "x_m", 0.0),
            "y [mm]": 1000.0 * fatigue_presentation.value(search, "y_m", 0.0),
            point_label: (
                100.0 * point_value if equivalent_method else point_value
            ),
            upper_label: (
                100.0 * upper_value if equivalent_method else upper_value
            ),
            (
                "Absolute gap [%]" if equivalent_method else "Absolute gap"
            ): (
                100.0 * absolute_gap
                if equivalent_method else absolute_gap
            ),
            "Relative gap [%]": 100.0 * fatigue_presentation.value(
                search, "relative_gap", 0.0
            ),
            "Divisions": fatigue_presentation.value(search, "divisions"),
            "Boxes": fatigue_presentation.value(search, "boxes_evaluated"),
            "Points": fatigue_presentation.value(search, "points_evaluated"),
        }], height=120)

    st.markdown("**Selected-fibre bin results**")
    detail_rows = []
    for row in bin_rows:
        detail = {
            "Bin": row["bin"],
            "Cycles": row["cycles"],
            "Status": row["status"],
            "Long compression [MPa]": row["compression_long_mpa"],
            "Total compression [MPa]": row["compression_total_mpa"],
            "Design min [MPa]": row["compression_min_design_mpa"],
            "Design max [MPa]": row["compression_max_design_mpa"],
            "Stress ratio": row["stress_ratio"],
            "Ecd,min": row["e_cd_min"],
            "Ecd,max": row["e_cd_max"],
        }
        if equivalent_method:
            detail["Equivalent util. [%]"] = (
                100.0 * row["equivalent_utilisation"]
                if row["equivalent_utilisation"] is not None
                else None
            )
        else:
            detail["N_R"] = row["cycles_to_failure"]
            detail["Miner D"] = row["damage"]
        detail["Stress util. [%]"] = (
            None if row["stress_utilisation"] is None
            else 100.0 * row["stress_utilisation"]
        )
        detail_rows.append(detail)
    _fatigue_result_table(detail_rows, height=560)
    if equivalent_method:
        st.caption(
            r"Concrete uses $E_{cd,max}+0.43\sqrt{1-E_{cd,min}/E_{cd,max}}"
            r"\leq1$. Each action pair must be damage-equivalent for $10^6$ "
            "cycles; the Cycles column is not used for this concrete check."
        )


def _fatigue_spectrum_panel(inp, spectrum):
    selected_name = str(
        fatigue_presentation.value(spectrum, "spectrum_name", "")
    )
    records = [
        record
        for record in fatigue_inputs.spectrum_records(
            inp.get(fatigue_inputs.SPECTRUM_TABLE_KEY)
        )
        if record[fatigue_inputs.SPECTRUM] == selected_name
    ]
    st.markdown("**Entered actions (tension-positive N)**")
    _fatigue_result_table([
        {
            "Bin": record[fatigue_inputs.NAME],
            "Description": record[fatigue_inputs.DESCRIPTION],
            "Cycles": record[fatigue_inputs.CYCLES],
            "Nlong,Ed [kN]": record["n_long_ed_kn"],
            "Mx,long,Ed [kNm]": record["mx_long_ed_knm"],
            "My,long,Ed [kNm]": record["my_long_ed_knm"],
            "Nshort,Ed [kN]": record["n_short_ed_kn"],
            "Mx,short,Ed [kNm]": record["mx_short_ed_knm"],
            "My,short,Ed [kNm]": record["my_short_ed_knm"],
        }
        for record in records
    ], height=520)
    st.markdown("**Elastic calculation details**")
    _fatigue_result_table([
        {
            "Bin": row["bin"],
            "Description": row["description"],
            "Cycles": row["cycles"],
            "Status": row["status"],
            "Cyclic action": row["cyclic_action"],
            "gamma_Ff": row["gamma_ff"],
            "Bond method": row["bond_method"],
        }
        for row in fatigue_presentation.spectrum_bin_rows(spectrum)
    ], height=520)


def _fatigue_result_basis_panel(payload):
    basis = payload.get("basis") or {}
    factors = payload.get("partial_factors") or {}
    checks = payload.get("checks") or {}
    parameters = payload.get("concrete_parameters") or {}
    rows = [
        (
            "Design basis",
            payload.get("basis_label") or payload.get("edition") or "-",
        ),
        ("Method scope", payload.get("basis_disclosure") or "-"),
        (
            "Checks",
            ", ".join(
                label
                for key, label in (
                    ("reinforcement", "reinforcement"),
                    ("concrete", "concrete"),
                )
                if checks.get(key)
            ) or "-",
        ),
        ("Method", basis.get("method") or "-"),
        ("Method reference", payload.get("method_reference") or "-"),
        ("gamma_Ff", factors.get("gamma_ff")),
        ("gamma_s", factors.get("gamma_s")),
        ("gamma_c,fat", factors.get("gamma_c")),
        ("t0 [days]", payload.get("t0_days")),
        ("beta_cc(t0)", parameters.get("beta_cc_t0")),
        ("fck [MPa]", parameters.get("fck_mpa")),
        ("Notes", basis.get("notes") or "-"),
    ]
    _fatigue_result_table([
        # A presentation column must have one Arrow-compatible type.  Mixing the
        # textual provenance rows above with numeric factors made Streamlit coerce
        # the frame on every render and emit a full serialization traceback.
        {"Item": label, "Value": str(value)}
        for label, value in rows
        if value is not None
    ], height=760)
    references = payload.get("calculation_references") or {}
    if references:
        st.markdown("**Calculation references**")
        _fatigue_result_table([
            {"Check": key.capitalize(), "Reference": value}
            for key, value in references.items()
        ], height=180)
    capability_bindings = payload.get("capability_bindings") or {}
    if capability_bindings:
        st.markdown("**Calculation methods and scope**")
        _fatigue_result_table([
            {
                "Check": key.capitalize(),
                "Method": str(
                    binding.get("capability") or "-"
                ).replace("_", " ").capitalize(),
                "Reference": binding.get("source") or "-",
                "Scope": binding.get("disclosure") or "-",
            }
            for key, binding in capability_bindings.items()
        ], height=240)
    details = payload.get("fatigue_detail_basis") or ()
    if details:
        st.markdown("**Assigned fatigue details**")
        _fatigue_result_table([
            {
                "ID": item.get("id"),
                "Name": item.get("name"),
                "Type": str(item.get("kind") or "").capitalize(),
                "Preset": item.get("preset"),
                "N*": item.get("n_star"),
                "k1": item.get("k1"),
                "k2": item.get("k2"),
                f"{_DELTA}{_SIGMA}Rsk [MPa]": (
                    item.get("delta_sigma_rsk_mpa")
                ),
                "Source": item.get("source") or "-",
            }
            for item in details
        ], height=420)


def fatigue_view(inp, results, *, stale=False):
    """Grouped fatigue summary with spectrum and component drill-down."""

    if not inp.get("fatigue_on"):
        st.info("Enable Fatigue in Analysis settings, then press Calculate.")
        return
    payload = (results or {}).get("fatigue")
    if payload is None:
        st.info("Press Calculate to assess the grouped spectra.")
        return

    status = fatigue_presentation.overall_status(payload, stale=stale)
    errors = tuple(payload.get("errors") or ())
    if errors:
        _fatigue_status_callout(
            status,
            "Fatigue not assessed; other requested analyses were calculated",
        )
        st.error("Resolve the fatigue input errors, then recalculate fatigue.")
        for error in errors:
            visible_error = engineer_messages.error_detail(
                error,
                fallback=_FATIGUE_DISPLAY_ERROR,
                context="fatigue result error",
            )
            st.markdown(f"- {visible_error}")
        return
    governing_name = str(payload.get("governing_spectrum") or "-")
    utilisation = fatigue_presentation.evidence_number(
        payload.get("utilisation")
    )
    breakdown = fatigue_presentation.criterion_breakdown(payload)
    _fatigue_status_callout(
        status,
        (
            f"{governing_name} | governing utilisation "
            f"{viz.pct(utilisation)}"
            + (f" | {breakdown}" if breakdown else "")
        ),
    )
    warnings = tuple(payload.get("warnings") or ())
    if warnings:
        with st.expander(f"Basis warnings ({len(warnings)})", expanded=True):
            for warning in warnings:
                visible_warning = engineer_messages.error_detail(
                    warning,
                    fallback=_FATIGUE_DISPLAY_WARNING,
                    context="fatigue result warning",
                )
                st.markdown(f"- {visible_warning}")

    summary_rows = fatigue_presentation.spectrum_rows(payload)
    _fatigue_result_table([
        {
            "Spectrum": row["spectrum"],
            "Status": row["status"],
            "Bins": row["bins"],
            "Reinforcement": row["reinforcement_elements"],
            "Concrete fibres": row["concrete_fibres"],
            "Governing": row["governing"],
            "Max Miner D": row["miner_damage"],
            "Max yield / proof util. [%]": (
                None if row["yield_utilisation"] is None
                else 100.0 * row["yield_utilisation"]
            ),
            "Utilisation [%]": (
                None if row["utilisation"] is None
                else 100.0 * row["utilisation"]
            ),
            "Zero-action bins": row["zero_cyclic_bins"],
            "Search upper D": row["search_upper_damage"],
        }
        for row in summary_rows
    ], height=360)
    st.caption(
        "Each spectrum is assessed independently. The governing utilisation is "
        "the maximum applicable Miner, yield/proof or concrete result."
    )

    options = [row["spectrum"] for row in summary_rows]
    if not options:
        st.error("INVALID - No spectrum results were returned.")
        return
    preferred = governing_name if governing_name in options else options[0]
    key = "_fatigue_result_spectrum"
    if st.session_state.get(key) not in options:
        st.session_state[key] = preferred
    selected_name = st.selectbox(
        "Spectrum",
        options,
        key=key,
        help="Select a grouped spectrum for detailed results.",
    )
    spectrum = fatigue_presentation.spectrum_by_name(payload, selected_name)
    if spectrum is None:
        st.error("INVALID - Selected spectrum result is unavailable.")
        return

    row = next(
        item for item in summary_rows if item["spectrum"] == selected_name
    )
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Status", row["status"])
    m2.metric("Governing utilisation", viz.pct(row["utilisation"]))
    m3.metric(
        "Max Miner D",
        fatigue_presentation.compact_number(row["miner_damage"]),
    )
    m4.metric(
        "Max yield / proof utilisation",
        (
            "-"
            if row["yield_utilisation"] is None
            else viz.pct(row["yield_utilisation"])
        ),
    )
    m5.metric("Governing", row["governing"])
    st.plotly_chart(
        _memo_fig(
            "fatigue_utilisation_map",
            _fatigue_map_signature(inp, spectrum),
            lambda: viz.fatigue_utilisation_map_figure(
                inp.get("outer", []),
                inp.get("holes", []),
                inp.get("bar_elements", []),
                inp.get("tendon_elements", []),
                spectrum,
            ),
        ),
        width="stretch",
    )

    detail_options = []
    if fatigue_presentation.items(spectrum, "reinforcement"):
        detail_options.append("Reinforcement")
    if fatigue_presentation.items(spectrum, "concrete"):
        detail_options.append("Concrete")
    detail_options.extend(["Spectrum bins", "Basis"])
    detail_key = "_fatigue_result_detail"
    if st.session_state.get(detail_key) not in detail_options:
        st.session_state[detail_key] = detail_options[0]
    detail = st.segmented_control(
        "Detail",
        detail_options,
        key=detail_key,
        required=True,
    )
    if detail == "Reinforcement":
        _fatigue_reinforcement_panel(payload, spectrum)
    elif detail == "Concrete":
        _fatigue_concrete_panel(spectrum)
    elif detail == "Spectrum bins":
        _fatigue_spectrum_panel(inp, spectrum)
    else:
        _fatigue_result_basis_panel(payload)


def _verdict_metric(box, label, value, ok, *, help=None):
    """Render a genuine demand-versus-resistance equation.

    Method-default-range deviations are reported separately as warnings and
    never suppress or relabel this result.
    """
    box.metric(
        label,
        value,
        delta=("PASS" if ok else "FAIL"),
        delta_color=("normal" if ok else "inverse"),
        help=help,
    )


def _member_material_note(inp):
    """Identify the reinforcing material shared by shear/torsion checks."""
    material_id = inp.get("capacity_steel_material_id") or "-"
    name = next(
        (item.get("name", "") for item in
         (inp.get("mild_material_catalog") or {}).get("items", [])
         if item.get("id") == material_id),
        "",
    )
    label = f"{material_id} - {name}" if name else str(material_id)
    gamma_s = getattr(inp.get("steel"), "gamma_y", None)
    suffix = f"; $\\gamma_s={gamma_s:g}$" if gamma_s is not None else ""
    st.caption(f"Member-check reinforcing material: {label}{suffix}.")


def shear_view(inp, results):
    """Shear resistance without shear reinforcement (VRd,c) and the utilisation.

    Reports the resistance, the derived geometry (effective depth, web width,
    tension reinforcement) and the intermediate quantities of EN 1992-1-1 sec.
    6.2.2(1), then the utilisation VEd/VRd,c.
    """
    if not results or "shear" not in results:
        if not inp.get("shear_requested", inp.get("shear_on")):
            st.info("Enable 'Check shear capacity' in Analysis settings, "
                    "then press Calculate.")
        elif (
            abs(float(inp.get("shear_Vx", 0.0))) <= 0.0
            and abs(float(inp.get("shear_Vy", 0.0))) <= 0.0
        ):
            st.info("Vx,Ed = Vy,Ed = 0; shear is not evaluated for this case.")
        else:
            st.info("Press Calculate to run the shear check.")
        return
    aggregate = results["shear"]
    combined_blocker = presentation.combined_bending_assessment_blocker(results)
    combined_blocked = combined_blocker is not None
    directions = aggregate.get("directions") or {}
    if directions:
        summary = []
        for component in ("vx", "vy"):
            if component not in directions:
                continue
            item = directions[component]
            governing_util = (
                (item.get("links") or {}).get("util")
                if inp.get("shear_links") is True else item.get("util")
            )
            summary.append({
                "Component": "Vx,Ed" if component == "vx" else "Vy,Ed",
                "VEd [kN]": item.get("signed_v_ed", item.get("v_ed")),
                "VRd [kN]": (
                    ((item.get("links") or {}).get("res") or {}).get("vrd")
                    if inp.get("shear_links") is True
                    else (item.get("res") or {}).get("vrd_c")
                ),
                "Utilisation": governing_util,
                "Status": item.get("status"),
                "Tension face": viz.tension_face_label(
                    item.get("tension_low", True), item.get("axis")
                ),
            })
        if aggregate.get("biaxial"):
            st.info(
                "Vx,Ed and Vy,Ed are calculated independently. Generic "
                "cross-direction interaction is not calculated."
            )
            components = inp.get("shear_components") or {}
            st.plotly_chart(
                viz.biaxial_shear_overview_figure(
                    inp.get("outer", []), inp.get("holes", []), inp.get("bars", []),
                    vx_ed=(components.get("vx") or {}).get(
                        "signed_v_ed", inp.get("shear_Vx", 0.0)
                    ),
                    vy_ed=(components.get("vy") or {}).get(
                        "signed_v_ed", inp.get("shear_Vy", 0.0)
                    ),
                    title="Directional shear actions",
                ),
                width="stretch",
            )
        st.dataframe(summary, hide_index=True, width="stretch")
        options = [component for component in ("vx", "vy") if component in directions]
        if len(options) > 1:
            preferred = options[0]
            if preferred not in options:
                preferred = options[0]
            if st.session_state.get("shear_direction_view") not in options:
                st.session_state["shear_direction_view"] = preferred
            selected = st.segmented_control(
                "Directional result",
                options,
                format_func=lambda value: "Vx,Ed" if value == "vx" else "Vy,Ed",
                key="shear_direction_view",
                required=True,
            )
        else:
            selected = options[0]
        sh = directions[selected or options[0]]
    else:
        sh = aggregate
    _member_material_note(inp)
    res = sh["res"]
    component = sh.get("component") or ("vy" if sh["axis"] == "x" else "vx")
    action_label = "Vx,Ed" if component == "vx" else "Vy,Ed"
    action_math = r"$V_{x,Ed}$" if component == "vx" else r"$V_{y,Ed}$"
    util_math = (r"$|V_{x,Ed}|/V_{Rd,c}$" if component == "vx"
                 else r"$|V_{y,Ed}|/V_{Rd,c}$")
    axis_lbl = (r"$V_{y,Ed}$ along y; paired with $M_{x,Ed}$" if component == "vy"
                else r"$V_{x,Ed}$ along x; paired with $M_{y,Ed}$")
    face_lbl = viz.tension_face_label(sh["tension_low"], sh["axis"])
    if not res["valid"]:
        _manual_warning(
            st,
            "calculation-warning",
            r"$V_{Rd,c}$ is zero - there is no tension reinforcement on the "
            "chosen face, or the derived effective depth / web width is zero. "
            r"Add tension bars on that face and check the geometry (or enter $b_w$).",
        )
    util = sh["util"]
    ok = viz.util_ok(util)
    m1, m2, m3 = st.columns(3)
    signed_v_ed = float(sh.get("signed_v_ed", sh["v_ed"]))
    m1.metric(f"Applied {action_math}", f"{signed_v_ed:.3f} kN")
    m2.metric(r"Resistance $V_{Rd,c}$", f"{res['vrd_c']:.3f} kN")
    util_txt = _pct(util)
    m3.metric(f"Utilisation {util_math}", util_txt,
              delta=("OK" if ok else "Over limit"),
              delta_color=("normal" if ok else "inverse"))
    pre_note = (f" plus tendon precompression {sh['n_prestress']:.1f} kN (from the "
                 "prestress initial strain)" if sh.get("n_prestress") else "")
    st.caption(f"{axis_lbl} shear, tension on the {face_lbl} face. Method: "
               f"{sh['method']}. The axial action uses the plastic axial force "
               f"$N={sh['n_ed']:.1f}$ kN (tension-positive){pre_note}.")
    if sh.get("face_mode") == "auto":
        st.caption(
            "Automatic face selection uses the associated moment at the concrete "
            f"centroid: {float(sh.get('associated_moment', 0.0)):.3f} kNm."
        )

    if sh.get("both_faces_evaluated"):
        governing_domains = sh.get("governing_domains") or {}
        domain_labels = {
            "shear": "Shear",
            "vt": "V+T (6.29)",
            "minimum_reinforcement": "Minimum reinf. (6.31)",
            "combined": "Combined",
        }
        candidate_rows = []
        for candidate in sh.get("face_candidates", []):
            candidate_shear = candidate.get("shear") or {}
            candidate_links = candidate_shear.get("links") or {}
            face_token = "negative" if candidate.get("tension_low", True) else "positive"
            governing_here = [
                domain_labels[key]
                for key, domain in governing_domains.items()
                if domain.get("face") == face_token
                and not (key == "combined" and combined_blocked)
            ]
            candidate_rows.append({
                "Face": viz.tension_face_label(
                    candidate.get("tension_low", True), sh["axis"]
                ),
                "VRd,c [kN]": (candidate_shear.get("res") or {}).get("vrd_c"),
                "|VEd|/VRd,c": candidate_shear.get("util"),
                "|VEd|/VRd": candidate_links.get("util"),
                "Shear status": candidate.get("shear_status"),
                "V+T status": candidate.get("torsion_status"),
                "Combined status": (
                    "NOT ASSESSED"
                    if combined_blocked
                    else candidate.get("combined_status")
                ),
                "Governing domains": ", ".join(governing_here),
            })
        st.caption("Associated bending moment is zero; both faces were evaluated.")
        st.dataframe(candidate_rows, hide_index=True, width="stretch")
        if combined_blocked:
            _manual_warning(
                st,
                "calculation-warning",
                "Combined M-V-T is NOT ASSESSED. " + combined_blocker,
            )
        governing_rows = []
        for key in ("shear", "vt", "minimum_reinforcement", "combined"):
            domain = governing_domains.get(key)
            if not domain:
                continue
            if key == "combined" and combined_blocked:
                governing_rows.append({
                    "Check": domain_labels[key],
                    "Governing face": "-",
                    f"cot {_THETA}": None,
                    "Value / utilisation": None,
                    "Status / outcome": "NOT ASSESSED",
                })
                continue
            status = domain.get("status")
            if key == "minimum_reinforcement":
                status = {
                    "PASS": "minimum sufficient",
                    "FAIL": "designed reinforcement required",
                }.get(status, str(status or "NOT ASSESSED").lower())
            governing_rows.append({
                "Check": domain_labels[key],
                "Governing face": viz.directional_face_label(component, domain["face"]),
                f"cot {_THETA}": domain.get("cot"),
                "Value / utilisation": domain.get("util"),
                "Status / outcome": status,
            })
        st.markdown("**Independent governing selections**")
        st.dataframe(governing_rows, hide_index=True, width="stretch")

    geometry_basis = presentation.shear_geometry_basis(inp, sh)
    z_geometry = geometry_basis["z_mm"]
    bw_source = "user input" if sh["bw_user"] else "auto minimum solid width"
    st.plotly_chart(
        viz.shear_geometry_figure(
            inp.get("outer", []), inp.get("holes", []), inp.get("bars", []),
            axis=sh["axis"], tension_low=sh["tension_low"],
            centroid=sh["centroid"], asl_bar_ids=sh.get("asl_bar_ids", []),
            asl_cg_m=sh.get("asl_cg"), asl_mm2=sh["asl"],
            d_mm=sh["d"], z_mm=z_geometry, bw_mm=sh["bw"],
            bw_source=bw_source,
            signed_v_ed=signed_v_ed,
            d_note=geometry_basis["d_note"],
            z_note=geometry_basis["z_note"],
            title=f"{action_label} geometry - {face_lbl} tension",
        ),
        width="stretch",
    )
    st.caption(geometry_basis["statement"])

    bw_note = ("user input" if sh["bw_user"]
               else f"auto = min solid width {sh['bw_auto']:.1f} mm")
    st.markdown("**Derived quantities**")
    if sh.get("model_2023"):
        a_cs_text = (
            f"{res['a_cs']:.1f} mm"
            if res.get("a_cs", 0.0) > 0.0 else "not applicable (VEd = 0)"
        )
        st.dataframe(
            {"Quantity": ["Effective depth d", "Web width bw",
                           "Standard-defined concrete-shear arm z",
                           "Tension reinf. Asl", f"Reinf. ratio {_RHO}l",
                          "Action moment MEd", "Shear span acs",
                          "Axial factor kvp", "Modified depth kvp*d (8.27)",
                           "Aggregate ddg", f"{_TAU}Rd,c", f"{_TAU}Rd,c,min",
                           "Flexural fyd", f"{_GAMMA}V"],
              "Value": [f"{sh['d']:.1f} mm", f"{sh['bw']:.1f} mm ({bw_note})",
                        f"{res['z']:.1f} mm (0.9 d)", f"{sh['asl']:.1f} mm2",
                        f"{res['rho_l']:.4f}", f"{sh['m_ed_2023']:.3f} kNm",
                        a_cs_text, f"{res['k_vp']:.4f} (>= 0.1)",
                        f"{res['d_kvp']:.1f} mm", f"{res['ddg']:.1f} mm",
                        f"{res['tau_rdc']:.3f} MPa", f"{res['tau_min']:.3f} MPa",
                        f"{res['fyd']:.1f} MPa", f"{res['gamma_v']:.2f}"]},
            hide_index=True, width="stretch")
        st.caption(
            r"$k_{vp} = \max[1 + N_{Ed}/|V_{Ed}|\ d/(3a_{cs}),\,0.1]$, "
            r"$a_{cs}=\max(|M_{Ed}/V_{Ed}|,d)$ (8.30-8.31). Formula 8.27 uses "
            r"the selected $\gamma_V$, $d_{dg}=16+D_{lower}\leq40$ mm and "
            "fully anchored tension-face $A_{sl}$. Tendons are parallel to the "
            r"member axis ($\cos\beta=1$)."
        )
    else:
        st.dataframe(
            {"Quantity": ["Effective depth d", "Web width bw", "Tension reinf. Asl",
                          f"Reinf. ratio {_RHO}l", "Size factor k",
                          f"Axial stress {_SIGMA}cp", "Concrete area Ac",
                          "CRd,c", "vmin", "fcd"],
             "Value": [f"{sh['d']:.1f} mm", f"{sh['bw']:.1f} mm ({bw_note})",
                       f"{sh['asl']:.1f} mm2",
                       f"{res['rho_l']:.4f} ({chr(0x2264)} 0.02)",
                       f"{res['k']:.3f} ({chr(0x2264)} 2.0)",
                       f"{res['sigma_cp']:.3f} MPa ({chr(0x2264)} 0.2 fcd)",
                       f"{sh['ac'] * 1e6:.0f} mm2", f"{res['crd_c']:.4f}",
                       f"{res['vmin']:.3f} MPa", f"{res['fcd']:.2f} MPa"]},
            hide_index=True, width="stretch")
        st.caption(
            r"$V_{Rd,c} = \max[\,C_{Rd,c}\,k(100\,\rho_l f_{ck})^{1/3} + k_1\sigma_{cp},"
            r"\ v_{min} + k_1\sigma_{cp}]\,b_w d$, with $k_1 = "
            f"{res['k1']:.2f}$. "
            r"$A_{sl}$ is the tension reinforcement on the chosen face, assumed fully "
            r"anchored ($\geq l_{bd} + d$) beyond the section.")

    # Shear reinforcement (links): the governing check when present.
    links = sh.get("links")
    if links is not None:
        lk = links["res"]
        st.divider()
        st.markdown("**Shear reinforcement (links)**")
        if not lk["valid"]:
            reason = presentation.result_reason(
                links.get("assessment_reason")
                or lk.get("reason")
                or "invalid reinforced-shear input",
                "shear",
                context="reinforced-shear result reason",
            )
            _manual_warning(
                st,
                "calculation-warning",
                "The reinforced-shear check is NOT ASSESSED: " + reason + ".",
            )
            st.caption(
                "Review the reason above; link lever arm, resistance, utilisation "
                "and status are withheld."
            )
            return
        if links["out_of_limits"]:
            limit_ref = (
                (links.get("angle_limits") or {}).get("clause")
                or "EN 1992-1-1 6.7N / DK NA 6.7a NA"
            )
            _manual_warning(
                st,
                "method-applicability",
                f"The strut angle bounds (cot {_THETA} in "
                f"[{links['cot_min']:.2f}, {links['cot_max']:.2f}]) fall outside "
                f"the selected method's default range "
                f"[{links['cot_limit_lo']:.1f}, "
                f"{links['cot_limit_hi']:.1f}] ({limit_ref}). The actual values "
                "are used in the reported calculations.",
            )
        req_txt = (r"links are required ($V_{Ed}>V_{Rd,c}$)" if links["required"]
                   else r"links are not strictly required ($V_{Ed}\leq V_{Rd,c}$); minimum "
                        "reinforcement rules still apply")
        st.caption(f"For this $V_{{Ed}}$, {req_txt}.")
        util_l = links["util"]
        ok_l = viz.util_ok(util_l)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(r"$V_{Rd,s}$", f"{lk['vrd_s']:.3f} kN")
        c2.metric(r"$V_{Rd,max}$", f"{lk['vrd_max']:.3f} kN")
        c3.metric(r"$V_{Rd}=\min$", f"{lk['vrd']:.3f} kN",
                  help=f"governed by {lk['governs']}")
        ul_txt = _pct(util_l)
        _verdict_metric(c4, r"Utilisation $V_{Ed}/V_{Rd}$", ul_txt, ok_l)
        if links.get("model_2023"):
            st.dataframe(
                {
                    "Quantity": [
                        f"Strut angle {_THETA}",
                        f"cot {_THETA} (auto)",
                        f"Permitted cot {_THETA}",
                        "Lever arm z",
                        "Link area/spacing Asw/s",
                        f"Link ratio {_RHO}w",
                        "Design yield fywd",
                        f"Compression factor {_NU}",
                        f"{_TAU}Ed",
                        f"{_TAU}Rd,sy",
                        f"Compression stress {_SIGMA}cd",
                        f"Limit {_NU} fcd",
                        "Additional chord force NVd",
                    ],
                    "Value": [
                        f"{lk['theta_deg']:.1f}{_DEG}",
                        f"{lk['cot']:.3f}",
                        (
                            f"{links['cot_limit_lo']:.2f} to "
                            f"{links['cot_limit_hi']:.2f}; "
                            f"class {(links.get('angle_limits') or {}).get('ductility_class', 'B')}"
                        ),
                        f"{lk['z']:.1f} mm ({links['z_source']})",
                        f"{links['asw']:.1f} mm2 / {links['s']:.0f} mm "
                        f"({links['legs']:.0f} x {chr(0x00F8)}{links['dia']:.0f})",
                        f"{lk['rho_w']:.5f}",
                        f"{lk['fywd']:.1f} MPa",
                        f"{lk['nu']:.3f}",
                        f"{lk['tau_ed']:.3f} MPa",
                        f"{lk['tau_rd_sy']:.3f} MPa",
                        f"{lk['sigma_cd']:.3f} MPa",
                        f"{lk['nu_fcd']:.3f} MPa",
                        f"{links['longitudinal_shear_force']:.1f} kN",
                    ],
                },
                hide_index=True,
                width="stretch",
            )
        else:
            st.dataframe(
                {"Quantity": [f"Strut angle {_THETA}", f"cot {_THETA} (auto)",
                              "Lever arm z", "Link area/spacing Asw/s",
                              "Design yield fywd", f"Strut factor {_NU}1",
                              f"Chord factor {_ALPHA}cw",
                              f"Extra long. tension {_DELTA}Ftd"],
                 "Value": [f"{lk['theta_deg']:.1f}{_DEG}", f"{lk['cot']:.3f}",
                           f"{lk['z']:.1f} mm ({links['z_source']})",
                           f"{links['asw']:.1f} mm2 / {links['s']:.0f} mm "
                           f"({links['legs']:.0f} x {chr(0x00F8)}{links['dia']:.0f})",
                           f"{lk['fywd']:.1f} MPa", f"{lk['nu1']:.3f}",
                           f"{lk['alpha_cw']:.3f}",
                           f"{links['longitudinal_shear_force']:.1f} kN"]},
                hide_index=True, width="stretch")
        if links.get("theta_mode") == "utilisation":
            shared_ref = (
                " (shared with torsion when enabled)"
                if links.get("model_2023")
                else " (shared with torsion when enabled, EN 1992-1-1 6.3.2(2))"
            )
            theta_txt = ("Sector selects one member strut angle " + _THETA
                         + shared_ref + " that minimises the governing utilisation: a "
                         "flatter strut relaxes the stirrups but raises the "
                         "crushing demand and the longitudinal chord tension, so "
                         "the chosen angle depends on the applied actions.")
        else:
            theta_txt = (r"Sector auto-optimises $\theta$ within the bounds to "
                         r"maximise $V_{Rd} = \min(V_{Rd,s}, V_{Rd,max})$.")
        if links.get("model_2023"):
            st.caption(
                r"$\tau_{Rd,sy}=\rho_w f_{ywd}\cot\theta$ (8.42); "
                r"$\sigma_{cd}=\tau_{Ed}(\cot\theta+\tan\theta)"
                r"\leq\nu f_{cd}$ (8.44), with $\nu=0.5$. "
                + theta_txt
                + r" $N_{Vd}=|V_{Ed}|\cot\theta$ (8.50) is added to the "
                "longitudinal tension chord without the support-specific (8.53) "
                "relief."
            )
        else:
            st.caption(
                r"$V_{Rd,s} = (A_{sw}/s)\,z f_{ywd}\cot\theta$ (6.8); "
                r"$V_{Rd,max} = \alpha_{cw} b_w z\,\nu_1 f_{cd}/"
                r"(\cot\theta+\tan\theta)$ (6.9). "
                + theta_txt
                + r" $\Delta F_{td}=0.5V_{Ed}\cot\theta$ is the extra "
                "longitudinal tension the tension chord must also carry."
            )
        # Longitudinal chord under M + V (+ T): the same check the combined view
        # shows, computed at the member strut angle.
        ch = links.get("chord")
        if ch is not None and ch.get("valid"):
            st.markdown("**Longitudinal chord: bending + shear"
                        + (" + torsion" if ch.get("has_torsion") else "")
                        + " tension**")
            face_lbl = viz.tension_face_label(
                ch.get("tension_low", True), ch.get("axis")
            )
            gets_shift = ch.get("gets_shift", True)
            face_desc = (f"the shear tension face ({face_lbl})" if gets_shift else
                         f"the shear COMPRESSION face ({face_lbl}) -- the torsion "
                         "tension governs here, with no shear shift and the bending "
                         "relieving rather than adding")
            g1, g2, g3 = st.columns(3)
            g1.metric(fr"$M_{{Ed}}$ (about {ch['axis']})", f"{ch['m_ed']:.1f} kNm")
            g2.metric(r"$M_{Ed,\mathrm{total}}$", f"{ch['m_total']:.1f} kNm",
                      help="bending + longitudinal shear force (+ torsion) as an equivalent "
                           "moment on the governing chord face")
            coverage = ch.get("off_not_evaluated")
            fallback = presentation.required_chord_fallback(links)
            fell_back = fallback is not None
            if coverage:
                g3.metric(
                    r"$M_{Ed,\mathrm{total}}/M_{Rd}$",
                    _pct(ch["util"]),
                    help=(
                        "NOT ASSESSED: longitudinal chord coverage is incomplete; "
                        "see the warning below."
                    ),
                )
            elif fell_back:
                g3.metric(
                    r"$M_{Ed,\mathrm{total}}/M_{Rd}$",
                    _pct(ch["util"]),
                    help=(
                        "NOT ASSESSED: the displayed capacity is a pure-axis "
                        "substitute; see the warning below."
                        if not ch.get("conditional", True)
                        else "NOT ASSESSED: another required chord face uses a "
                             "pure-axis substitute; see the warning below."
                    ),
                )
            else:
                _verdict_metric(
                    g3,
                    r"$M_{Ed,\mathrm{total}}/M_{Rd}$",
                    _pct(ch["util"]),
                    ch["ok"],
                )
            obj_note = (" This demand is part of the strut-angle objective, so "
                        + _THETA + " backs off the band edge when the chord would "
                        "otherwise govern."
                        if ch.get("theta_mode") == "utilisation" else "")
            shear_term = (
                r"N_{Vd}\,z" if links.get("model_2023")
                else r"\Delta F_{td}\,z"
            )
            st.caption(
                f"Governing chord: {face_desc}. "
                rf"$M_{{Ed,total}}$ includes {shear_term} and half the perimeter "
                r"torsion share: "
                f"{ch['m_ed']:.1f} + {ch['mv']:.1f} + {ch['mt']:.1f} = "
                f"{ch['m_total']:.1f} kNm versus $M_{{Rd}} = "
                f"{ch['m_rd']:.1f}$ kNm "
                + viz.chord_mrd_label(ch["axis"], ch.get("m_off", 0.0),
                                      ch.get("conditional", True))
                + f"; $z = {ch['z']:.3f}$ m." + obj_note
            )
            if ch.get("capped"):
                st.caption(
                    "Shear shift is capped at section MRd under 6.2.3(7); the "
                    "strut-angle objective uses the same capped demand."
                )
            if fell_back:
                fallback_axis = fallback.get("axis", "?")
                fallback_face = (
                    "negative" if fallback.get("tension_low", True)
                    else "positive"
                )
                _manual_warning(
                    st,
                    "calculation-warning",
                    f"The required {fallback_axis}-axis {fallback_face} face uses "
                    "a pure-axis substitute after its conditional solve failed. "
                    "The chord result may be optimistic; use the combined "
                    + chr(0x03A3) + "(SEd/SRd) result.")
            if coverage == "subdivided":
                st.caption("Compound (subdivided) section: the torsion "
                           "longitudinal steel is per sub-tube, so the off-axis "
                           "chord's torsion share is not evaluated here; the "
                           + chr(0x03A3) + "(SEd/SRd) check covers the interaction.")
            elif coverage == "not_solved":
                _manual_warning(
                    st,
                    "calculation-warning",
                    "At least one torsion-carrying chord face could not be solved "
                    "or has no tension steel. The displayed chord may not govern; "
                    "use the " + chr(0x03A3) + "(SEd/SRd) interaction result.")
            elif not fell_back and ch.get("biaxial") and not ch.get("has_torsion"):
                st.caption("The off-axis chord carries only its bending tension "
                           "(no torsion is acting), which the biaxial bending "
                           "utilisation already covers.")
            _render_chord_off(
                links.get("chord_off"),
                assessment_complete=not bool(coverage) and not fell_back,
            )
        st.plotly_chart(viz.truss_figure(lk["theta_deg"], lk["z"], links["legs"],
                                         links["dia"], links["s"]), width="stretch")


def _render_chord_off(och, *, assessment_complete=True):
    """Off-axis chord check block, shared by the Shear and Combined views.

    Rendered when torsion is live on a single-tube section: the chord about the
    OTHER axis carries its bending tension plus its share of the distributed
    torsion longitudinal force (no shear shift -- the shear acts in the shear
    plane), against the capacity conditional on the shear-axis moment.
    """
    if och is None or not och.get("valid"):
        return
    face_lbl = viz.tension_face_label(
        och.get("tension_low", True), och.get("axis")
    )
    st.markdown(fr"**Off-axis chord (about {och['axis']}, governing face): bending "
                r"+ torsion tension**")
    g1, g2, g3 = st.columns(3)
    g1.metric(fr"$M_{{Ed}}$ (about {och['axis']})", f"{och['m_ed']:.1f} kNm")
    g2.metric(r"$M_{Ed,\mathrm{total}}$", f"{och['m_total']:.1f} kNm",
              help="bending + the torsion share as an equivalent moment on "
                   "this chord")
    if assessment_complete:
        _verdict_metric(
            g3,
            r"$M_{Ed,\mathrm{total}}/M_{Rd}$",
            _pct(och["util"]),
            och["ok"],
        )
    else:
        g3.metric(
            r"$M_{Ed,\mathrm{total}}/M_{Rd}$",
            _pct(och["util"]),
            help=(
                "NOT ASSESSED: the complete longitudinal chord assessment is "
                "not available."
            ),
        )
    st.caption(
        f"Governing chord: {face_lbl} face about the {och['axis']}-axis. "
        r"$M_{Ed,total}$ includes bending and half the perimeter torsion share: "
        f"{och['m_ed']:.1f} + {och['mt']:.1f} = {och['m_total']:.1f}$ kNm vs "
        f"$M_{{Rd}} = {och['m_rd']:.1f}$ kNm "
        + viz.chord_mrd_label(och["axis"], och.get("m_off", 0.0), True)
        + f"; $z = {och['z']:.3f}$ m "
        + f"({och.get('z_src') or 'calculated source not retained'}).")
    st.caption("The shear shift acts in the shear plane, while this orthogonal chord "
               "receives the torsion share. The shared steel carries both demands; "
               "the DK NA " + chr(0x03A3)
               + "(SEd/SRd) result governs.")


def torsion_view(inp, results):
    """Torsion resistance from the thin-walled tube (TRd,s / TRd,max / TRd,c), the
    required longitudinal steel, and the combined shear+torsion crushing check."""
    if not results or "torsion" not in results:
        if not inp.get("torsion_requested", inp.get("torsion_on")):
            st.info("Enable 'Check torsion capacity' in Analysis settings, "
                    "then press Calculate.")
        elif abs(float(inp.get("torsion_T", 0.0))) <= 0.0:
            st.info("TEd = 0 for this action set; torsion is not evaluated.")
        else:
            st.info("Press Calculate to run the torsion check.")
        return
    t = results["torsion"]
    _member_material_note(inp)
    tube = t["tube"]
    tube_valid = (
        t.get("tube_valid") is True
        if "tube_valid" in t
        else t.get("valid") is True
    )
    transverse_resistance_assessed = (
        t.get("transverse_resistance_assessed") is True
        if "transverse_resistance_assessed" in t
        else t.get("full_resistance_assessed") is True
        if "full_resistance_assessed" in t
        else t.get("valid") is True
    )
    transverse_resistance_available = bool(
        tube_valid
        and transverse_resistance_assessed
        and (
            t.get("closed_links_present") is True
            if "closed_links_present" in t
            else t.get("valid") is True
        )
        and t.get("valid") is True
    )
    directional_interactions = t.get("directional_interactions") or {}
    if directional_interactions and transverse_resistance_available:
        st.info(
            "Generic Vx,Ed + Vy,Ed + TEd interaction is not calculated. The table "
            "shows independent Vx+T and Vy+T calculations; the torsion result below "
            "is standalone."
        )
        rows = []
        min_reinf_rows = []
        for component in ("vx", "vy"):
            item = directional_interactions.get(component)
            if not item:
                continue
            interaction = item.get("interaction") or {}
            value = interaction.get("value")
            status = item.get("directional_interaction_status") or (
                presentation.interaction_assessment_status(interaction)
            )
            rows.append({
                "Directional screen": "Vx,Ed + TEd" if component == "vx"
                else "Vy,Ed + TEd",
                "TEd/TRd": item.get("util"),
                "6.29 V+T": value,
                "Status": status,
                "Governing face": viz.directional_face_label(
                    component, item.get("directional_governing_face")
                ),
                f"cot {_THETA}": item.get("directional_governing_cot"),
            })
            min_reinf = item.get("min_reinf") or {}
            if min_reinf:
                min_reinf_status = (
                    presentation.minimum_reinforcement_screen_status(min_reinf)
                )
                if min_reinf_status == "PASS":
                    outcome = "minimum sufficient"
                elif min_reinf_status == "FAIL":
                    outcome = "designed reinforcement required"
                else:
                    outcome = min_reinf_status
                min_reinf_rows.append({
                    "Directional 6.31 screen": (
                        "Vx,Ed + TEd" if component == "vx" else "Vy,Ed + TEd"
                    ),
                    "6.31 sum": min_reinf.get("value"),
                    "Status": min_reinf_status,
                    "Outcome": outcome,
                    "Governing face": viz.directional_face_label(
                        component,
                        item.get(
                            "directional_min_reinf_governing_face"
                        ),
                    ),
                    "Scope / guidance": (
                        presentation.minimum_reinforcement_screen_note(min_reinf)
                    ),
                })
        st.dataframe(rows, hide_index=True, width="stretch")
        if min_reinf_rows:
            st.caption(
                "Within its stated scope, Formula (6.31) screens whether minimum "
                "shear-and-torsion reinforcement is sufficient. The complete "
                "resistance checks remain separate."
            )
            st.dataframe(min_reinf_rows, hide_index=True, width="stretch")

    # A biaxial run reports Formula (6.31) per shear direction above. The
    # standalone torsion payload deliberately has no shear companion and must
    # not replace it. Render the retained single-direction scope before any
    # torsion-resistance early return so unavailable links cannot hide it.
    mr = None if directional_interactions else t.get("min_reinf")
    if mr is not None:
        st.divider()
        st.markdown("**Minimum-reinforcement screen (6.3.2(5), Eq 6.31)**")
        if not mr.get("applicable"):
            status = presentation.minimum_reinforcement_screen_status(mr)
            st.caption(
                f"{status}: "
                + presentation.minimum_reinforcement_screen_note(mr)
                + "."
            )
        else:
            val = mr["value"]
            ok_mr = mr["ok"]
            s1, s2, s3 = st.columns(3)
            s1.metric(
                r"$T_{Ed}/T_{Rd,c}$",
                f"{mr['t_ed'] / mr['trd_c'] * 100:.1f} %",
            )
            s2.metric(
                r"$V_{Ed}/V_{Rd,c}$",
                f"{mr['v_ed'] / mr['vrd_c'] * 100:.1f} %",
            )
            s3.metric(r"Sum ($\leq100\%$)", f"{val * 100:.1f} %",
                      delta=("minimum reinf. suffices" if ok_mr
                             else "designed reinf. required"),
                      delta_color=("normal" if ok_mr else "inverse"))
            st.caption("TEd/TRd,c + VEd/VRd,c <= 1 (6.3.2(5), Eq 6.31): if satisfied, "
                       "only minimum shear + torsion reinforcement is required -- no "
                       "designed stirrups for these actions. "
                       + presentation.minimum_reinforcement_screen_note(mr)
                       + ".")
    if tube_valid and not transverse_resistance_assessed:
        raw_reason = (
            t.get("assessment_reason")
            or t.get("reason")
            or "full torsion resistance not assessed"
        )
        if raw_reason == "closed_links_not_present":
            detail = (
                "Current shared links / closed torsion stirrups are not present."
            )
        elif raw_reason == "closed_link_reinforcement_not_positive":
            detail = (
                "Current closed torsion stirrups are selected, but their one-leg "
                "reinforcement per unit length is not positive."
            )
        else:
            detail = presentation.result_reason(
                raw_reason,
                "torsion",
                context="torsion assessment reason",
            ) + "."
        _manual_warning(
            st,
            "calculation-warning",
            "The torsion transverse/strut resistance is NOT ASSESSED. "
            + detail
            + " Select current closed links for the resistance component and "
            "utilisation; the values "
            "below show concrete resistance and reinforcement demand only.",
        )
        m1, m2, m3 = st.columns(3)
        m1.metric(r"Applied $T_{Ed}$", f"{t['t_ed']:.3f} kNm")
        m2.metric(
            r"Concrete cap $T_{Rd,max}$",
            f"{t['trd_max']:.3f} kNm",
            help="Concrete-strut cap; the transverse resistance component requires current closed links.",
        )
        m3.metric(r"Cracking $T_{Rd,c}$", f"{t['trd_c']:.3f} kNm")
        st.caption(
            f"Displayed cap angle: theta = {t['theta_deg']:.1f} deg, "
            f"cot theta = {t['cot']:.3f}. It supports the concrete cap and "
            "Formula 6.28 reinforcement demand; the resistance component requires links."
        )
        if t.get("subdivided"):
            subs = t.get("subtubes") or []
            st.markdown("**Validated sub-tube context**")
            st.dataframe(
                {
                    "Sub-tube": [
                        "web" if i == 0 else f"part {i + 1}"
                        for i in range(len(subs))
                    ],
                    "TEd,i (kNm)": [f"{item['t_ed']:.3f}" for item in subs],
                    "TRd,max cap (kNm)": [
                        f"{item['trd_max']:.3f}" for item in subs
                    ],
                    "TRd,c (kNm)": [
                        f"{item['trd_c']:.3f}" for item in subs
                    ],
                    "Required Asl (mm2)": [
                        f"{item['asl_req']:.0f}" for item in subs
                    ],
                },
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "Geometry and demand remain visible; the component-resistance sum, governing "
                "sub-tube and utilisation require current closed links."
            )
            st.plotly_chart(viz.subtube_figure(subs), width="stretch")
        else:
            st.markdown("**Tube idealisation and informational demand**")
            st.dataframe(
                {
                    "Quantity": [
                        "Gross area A",
                        "Wall thickness tef",
                        "Enclosed area Ak",
                        "Centre-line perimeter uk",
                        "Required longitudinal steel Asl",
                    ],
                    "Value": [
                        f"{tube['A'] * 1e6:.0f} mm2",
                        f"{tube['tef']:.1f} mm",
                        f"{tube['Ak'] * 1e6:.0f} mm2",
                        f"{tube['uk'] * 1e3:.0f} mm",
                        f"{t['asl_req']:.0f} mm2",
                    ],
                },
                hide_index=True,
                width="stretch",
            )
            st.plotly_chart(
                viz.tube_figure(
                    inp["outer"],
                    inp.get("holes"),
                    tube["tef"],
                    ak_m2=tube["Ak"],
                ),
                width="stretch",
            )
        return
    if not t["valid"]:
        if t.get("reason") == "multi-cell (2+ voids)":
            _manual_warning(
                st,
                "calculation-warning",
                "Torsion is not assessed for a multi-cell section: one tube omits "
                "the internal webs and would overstate resistance. EN 1992-1-1 "
                "6.3.2(1) requires separate tubes; use a solid or single-cell outline.",
            )
        elif t.get("reason") == "compound outline requires subdivision":
            _manual_warning(
                st,
                "calculation-warning",
                "Torsion is not assessed for this re-entrant or compound outline "
                "as one tube. Under EN 1992-1-1 6.3.1(3), enable subdivision and "
                "enter rectangles that partition the section.",
            )
        elif str(t.get("reason") or "").startswith("invalid sub-tube partition:"):
            presentation.result_reason(
                t.get("subdivision_reason") or t.get("reason"),
                "torsion",
                context="torsion sub-tube partition reason",
            )
            _manual_warning(
                st,
                "geometry-invalid",
                "Torsion is not assessed because the sub-tubes do not partition "
                "the concrete section. Adjust centres and dimensions "
                "to cover the net area without gaps, overlaps or boundary crossings."
            )
        else:
            _manual_warning(
                st,
                "geometry-invalid",
                "The torsion tube could not be formed from the outline (a "
                "degenerate or too-thin section). Enter a wall thickness tef to "
                "override, or check the geometry.",
            )
        return
    if t["out_of_limits"]:
        _manual_warning(
            st,
            "method-applicability",
            f"The strut bounds (cot {_THETA} in [{t['cot_min']:.2f}, "
            f"{t['cot_max']:.2f}]) fall outside the selected method's default "
            f"range [{t['cot_limit_lo']:.1f}, {t['cot_limit_hi']:.1f}] "
            "(6.7N / 6.7a NA). The actual values are used in the reported "
            "torsion and interaction calculations.",
        )
    util = t["util"]
    util_txt = _pct(util)
    resistance_status = str(t.get("resistance_status") or (
        "PASS" if viz.util_ok(util) else "FAIL"
    ))
    if t.get("subdivided"):
        m1, m2, m3 = st.columns(3)
        m1.metric(r"Applied $T_{Ed}$", f"{t['t_ed']:.3f} kNm")
        m2.metric(r"$\sum T_{Rd,i}$", f"{t['trd']:.3f} kNm",
                  help="Resistance-component sum for reference under 6.3.1(3); "
                       "maximum sub-tube utilisation controls.")
        m3.metric(
            r"Transverse/strut component $\max(T_{Ed,i}/T_{Rd,i})$",
            util_txt,
        )
        m3.caption(resistance_status)
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(r"Applied $T_{Ed}$", f"{t['t_ed']:.3f} kNm")
        m2.metric(r"$T_{Rd}$ component $=\min$", f"{t['trd']:.3f} kNm",
                  help=f"governed by {t['governs']}")
        m3.metric(r"Cracking $T_{Rd,c}$", f"{t['trd_c']:.3f} kNm")
        m4.metric(r"Transverse/strut utilisation $T_{Ed}/T_{Rd}$", util_txt)
        m4.caption(resistance_status)

    overall_status = presentation.torsion_assessment_status(t)
    overall_note = presentation.torsion_assessment_note(t)
    if overall_status != "PASS":
        _manual_warning(
            st,
            "calculation-warning",
            f"Overall torsion assessment: {overall_status}. {overall_note}.",
        )
    longitudinal = t.get("longitudinal_assessment") or {}
    if longitudinal:
        def _area_text(value):
            return "-" if value is None else f"{float(value):.0f} mm2"

        st.markdown("**Longitudinal torsion reinforcement (Formula 6.28)**")
        st.dataframe(
            {
                "Quantity": [
                    "Required longitudinal area",
                    "All modelled passive bars - gross area",
                    "All modelled passive bars - equivalent area at selected fyd",
                    "Longitudinal assessment",
                ],
                "Value": [
                    _area_text(longitudinal.get("required_asl_mm2")),
                    _area_text(longitudinal.get("provided_gross_area_mm2")),
                    _area_text(longitudinal.get("provided_equivalent_area_mm2")),
                    str(longitudinal.get("status") or "NOT ASSESSED"),
                ],
            },
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "The modelled passive-bar total is an upper bound. Sector does not "
            "credit it as usable torsion reinforcement unless reserve beyond "
            "bending, distribution around every torsion-tube side and member "
            "anchorage are established."
        )

    st.caption(
        "Torsional cracking inputs: "
        f"$f_{{ctd}} = f_{{ctk,0.05}}/\\gamma_{{ct}} = "
        f"{t['fctk_005']:.3f}/{t['gamma_ct']:.3f} = "
        f"{t['fctd']:.3f}$ MPa. The actual direct gamma_ct input is used."
    )

    if t.get("subdivided"):
        subs = t["subtubes"]
        c_tot = sum(s["stiffness"] for s in subs) or 1.0
        if t.get("theta_mode") == "utilisation":
            angle_clause = (f"every sub-tube is at the ONE member strut angle "
                            f"(6.3.2(2), cot {_THETA} = {t['cot']:.3f}), shared with "
                            "the shear check and selected to minimise the governing "
                            "utilisation")
        else:
            angle_clause = ("each sub-tube is at its OWN resistance-optimum strut angle "
                            "(no single member angle applies -- see the cot column)")
        st.caption(f"Compound section (6.3.1(3)): the TRd component is "
                   f"{chr(0x03A3)} of the sub-tube resistance components; TEd is "
                   "split by uncracked torsional stiffness "
                   r"$C = \beta\,h\,b^3$ (6.3.1(4)). The first row (web) carries the "
                   f"shear in the combined V+T checks; {angle_clause}. "
                   f"Method: {t['method']}.")
        st.markdown("**Sub-tube resistance components and Formula 6.28 demand**")
        st.dataframe(
            {"Sub-tube": [("web" if i == 0 else f"part {i + 1}")
                          for i in range(len(subs))],
             "centre x, y (mm)": [
                 f"{s['x_mm']:.0f}, {s['y_mm']:.0f}" for s in subs
             ],
             "b x h (mm)": [f"{s['b_mm']:.0f} x {s['h_mm']:.0f}" for s in subs],
             "tef (mm)": [f"{s['tube']['tef']:.1f}" for s in subs],
             "Ak (mm2)": [f"{s['tube']['Ak'] * 1e6:.0f}" for s in subs],
             f"cot {_THETA}": [f"{s['cot']:.3f}" for s in subs],
             "Stiffness": [f"{s['stiffness'] / c_tot * 100:.1f} %" for s in subs],
             "TEd,i (kNm)": [f"{s['t_ed']:.3f}" for s in subs],
             "TRd,i (kNm)": [f"{s['trd']:.3f}" for s in subs],
             "TEd/TRd,i": [_pct(s["util"]) for s in subs],
             "Asl,req,i (mm2)": [f"{s['asl_req']:.0f}" for s in subs],
             "Governs": [s["governs"] for s in subs]},
            hide_index=True, width="stretch")
        g = t.get("governing_sub")
        gov_lbl = (("web" if g == 0 else f"part {g + 1}") if g is not None else "-")
        st.caption(f"Governing sub-tube resistance component: {gov_lbl}; "
                   f"max(TEd,i/TRd,i) = {util_txt}, so every sub-tube resistance "
                   "component must pass.")
        st.caption("Applied torque is distributed by uncracked torsional stiffness. "
                   f"Required longitudinal steel {chr(0x03A3)}Asl = "
                   f"{t['asl_req']:.0f} mm2 is the sum for all sub-tubes. Its "
                   "allocation around every sub-tube and reserve beyond bending "
                   "must be verified. The figure shows the validated partition "
                   "used by the calculation.")
        st.plotly_chart(viz.subtube_figure(subs), width="stretch")
    else:
        theta_note = ("the ONE member strut angle (6.3.2(2)), shared with the shear "
                      "check and selected to minimise the governing utilisation"
                      if t.get("theta_mode") == "utilisation"
                      else "auto-optimised for the torsion resistance")
        st.caption(
            f"$\\theta={t['theta_deg']:.1f}^\\circ$ strut "
            f"($\\cot\\theta={t['cot']:.3f}$, {theta_note}). "
            f"Method: {t['method']}. "
            f"$T_{{Rd,s}}={t['trd_s']:.3f}$ kNm, "
            f"$T_{{Rd,max}}={t['trd_max']:.3f}$ kNm."
        )
        tef_note = ("user input" if tube["tef_user"]
                    else ("auto A/u, capped at the wall" if tube["tef_capped"]
                          else "auto = A/u"))
        st.markdown("**Tube idealisation and torsion quantities**")
        st.dataframe(
            {"Quantity": ["Gross area A", "Outer perimeter u", "Wall thickness tef",
                          "Enclosed area Ak", "Centre-line perimeter uk",
                          f"Strut factor {_NU}", f"Chord factor {_ALPHA}cw",
                          "Concrete tensile factor gamma_ct",
                          "Required long. steel " + chr(0x03A3) + "Asl"],
             "Value": [f"{tube['A'] * 1e6:.0f} mm2", f"{tube['u'] * 1e3:.0f} mm",
                       f"{tube['tef']:.1f} mm ({tef_note})",
                       f"{tube['Ak'] * 1e6:.0f} mm2",
                       f"{tube['uk'] * 1e3:.0f} mm", f"{t['nu']:.3f}",
                       f"{t['alpha_cw']:.3f}", f"{t['gamma_ct']:.3f}",
                       f"{t['asl_req']:.0f} mm2"]},
            hide_index=True, width="stretch")
        st.caption(
            r"$T_{Rd,s}$ follows the torsional wall shear flow (6.27) and "
            r"transverse equilibrium (6.8); $T_{Rd,max}$ follows (6.30). "
            r"Required $\sum A_{sl}=T_{Ed}u_k\cot\theta/(2A_kf_{yd})$ (6.28) "
            "must remain available beyond bending demand and be distributed and "
            "anchored for torsion; "
            r"$T_{Rd,c}$ uses $f_{ctd}$."
        )
        st.plotly_chart(viz.tube_figure(inp["outer"], inp.get("holes"), tube["tef"],
                                        ak_m2=tube["Ak"]), width="stretch")
    if t.get("n_prestress"):
        st.caption(f"{_ALPHA}cw uses {_SIGMA}cp = {t['sigma_cp']:.3f} MPa, which "
                   f"includes the tendon precompression {t['n_prestress']:.1f} kN "
                   "(from the prestress initial strain) as well as the axial N.")
    if t.get("nu_v_detailing"):
        st.caption(f"{_NU} = {_NU}v (raised from {_NU}t) under DK NA Figur 5.100 NA: "
                   "closed stirrups round the periphery + distributed longitudinal "
                   "steel on both faces. This selected detailing condition remains "
                   "subject to the overall longitudinal verification above.")

    inter = t.get("interaction")
    if inter is not None and not inter.get("valid"):
        st.divider()
        st.markdown("**Combined shear + torsion (concrete crushing, 6.29)**")
        _manual_warning(
            st, "calculation-warning", _no_common_angle_msg(inter)
        )
    elif inter is not None:
        st.divider()
        st.markdown("**Combined shear + torsion (concrete crushing, 6.29)**")
        val = inter["value"]
        ok_i = viz.util_ok(val)
        i1, i2, i3 = st.columns(3)
        i1.metric(r"$T_{Ed}/T_{Rd,max}$", f"{(inter['t_ed']/inter['trd_max']*100):.1f} %"
                  if inter["trd_max"] > 0 else "inf")
        i2.metric(r"$V_{Ed}/V_{Rd,max}$", f"{(inter['v_ed']/inter['vrd_max']*100):.1f} %"
                  if inter["vrd_max"] > 0 else "inf")
        val_txt = _pct(val)
        _verdict_metric(
            i3, r"Sum ($\leq100\%$)", val_txt, ok_i,
        )
        st.caption(
            r"$T_{Ed}/T_{Rd,max}+V_{Ed}/V_{Rd,max}\leq1$ (6.29), "
            "uses one shared strut angle "
            f"$\\cot\\theta={inter['cot']:.2f}$ "
            f"($\\theta={inter['theta_deg']:.1f}^\\circ$). Displayed "
            "$T_{Rd,max}$ and $V_{Rd,max}$ correspond to that angle, not their "
            "stand-alone optima."
        )


def _pct(value):
    """Shared util-percent formatter, resolved only for a requested result."""

    return viz.pct(value)


def _no_common_angle_msg(d):
    """Message for a defensive failure of the shared member-angle check."""
    reason = presentation.result_reason(
        d.get("reason") or "no evaluable shared angle",
        "combined",
        context="combined shared-angle reason",
    )
    return (
        "The shared compression-strut check is NOT evaluated: "
        f"{reason}."
    )


def combined_view(inp, results):
    """Combined M-V-T interaction: the concrete-crushing (6.29) and DK NA
    sum(SEd/SRd) checks across the plastic (M), shear (V) and torsion (T) results."""
    if not results or "combined" not in results:
        if not inp.get("combined_requested", inp.get("combined_on")):
            st.info("Enable 'Check combined M-V-T' in Analysis settings "
                    "(with Plastic, the shear check and the torsion check), then "
                    "press Calculate.")
        elif (
            (
                abs(float(inp.get("shear_Vx", 0.0))) <= 0.0
                and abs(float(inp.get("shear_Vy", 0.0))) <= 0.0
            )
            or abs(float(inp.get("torsion_T", 0.0))) <= 0.0
        ):
            shear_zero = (
                abs(float(inp.get("shear_Vx", 0.0))) <= 0.0
                and abs(float(inp.get("shear_Vy", 0.0))) <= 0.0
            )
            torsion_zero = abs(float(inp.get("torsion_T", 0.0))) <= 0.0
            if shear_zero and torsion_zero:
                zero_text = "Vx,Ed = Vy,Ed = TEd = 0"
            elif shear_zero:
                zero_text = "Vx,Ed = Vy,Ed = 0"
            else:
                zero_text = "TEd = 0"
            st.info(
                f"Combined M-V-T is not evaluated because {zero_text} for this case."
            )
        else:
            st.info("Enable Plastic utilisation, shear and torsion, then press "
                    "Calculate to run the combined check.")
        return
    combined_blocker = presentation.combined_bending_assessment_blocker(results)
    if combined_blocker is not None:
        _manual_warning(
            st,
            "calculation-warning",
            "Combined M-V-T is NOT ASSESSED. " + combined_blocker,
        )
        return
    aggregate = results["combined"]
    _member_material_note(inp)
    if aggregate.get("biaxial"):
        st.info(
            "Vx+T and Vy+T are calculated separately. Generic simultaneous "
            "Vx+Vy+T interaction is not calculated."
        )
        directions = aggregate.get("directions") or {}
        rows = []
        for component in ("vx", "vy"):
            item = directions.get(component) or {}
            rows.append({
                "Directional screen": "Vx,Ed + TEd" if component == "vx"
                else "Vy,Ed + TEd",
                "Axial util.": item.get("r_n"),
                "Bending util.": item.get("r_m"),
                "Shear util.": item.get("r_v"),
                "Torsion util.": item.get("r_t"),
                "DK NA sum": item.get("dkna_sum"),
                "Governing face": viz.directional_face_label(
                    component, item.get("governing_face")
                ),
                f"cot {_THETA}": item.get("governing_cot"),
                "DK NA sum status": (
                    presentation.combined_dkna_status(item)
                ),
            })
        st.dataframe(rows, hide_index=True, width="stretch")
        options = [component for component in ("vx", "vy") if directions.get(component)]
        if not options:
            return
        preferred = options[0]
        if st.session_state.get("combined_direction_view") not in options:
            st.session_state["combined_direction_view"] = preferred
        selected = st.segmented_control(
            "Directional combined result",
            options,
            format_func=lambda value: "Vx,Ed + TEd" if value == "vx" else "Vy,Ed + TEd",
            key="combined_direction_view",
            required=True,
        )
        c = directions[selected or options[0]]
    else:
        c = aggregate
    if not c["valid"]:
        missing = []
        if not c.get("have_m"):
            missing.append("plastic bending (M) with a utilisation "
                           "(enable Plastic and 'Check utilisation')")
        if not c.get("have_v"):
            missing.append("a valid shear check (V)")
        if not c.get("have_t"):
            missing.append("a valid torsion check (T)")
        _manual_warning(
            st,
            "calculation-warning",
            "The combined check needs all three actions. Missing: "
            + "; ".join(missing)
            + "."
            + (
                " Reason: " + presentation.result_reason(
                    c["reason"],
                    "combined",
                    context="combined result reason",
                ) + "."
                if c.get("reason")
                else ""
            ),
        )
        return
    st.caption(f"Selected calculation method: {c['method']}.")
    if c.get("governing_face"):
        component = c.get("component") or "vy"
        angle_note = (
            ""
            if c.get("governing_cot") is None
            else f" at cot {_THETA} = {float(c['governing_cot']):.3f}"
        )
        st.caption(
            "Independent directional governing selection: "
            f"{viz.directional_face_label(component, c['governing_face'])}"
            f"{angle_note}."
        )
    if c.get("outside_default_range"):
        _manual_warning(
            st,
            "method-applicability",
            "The selected compression-strut bounds fall outside the selected "
            "method's default range. The actual values are used in every "
            "combined calculation.",
        )
    action_alone = c.get("action_alone") or {}

    def _action_help(key, unit):
        action = action_alone.get(key) or {}
        demand = action.get("demand")
        resistance = action.get("resistance")
        if demand is None or resistance is None:
            return "The matching action-alone resistance is not available."
        return (
            f"SEd = {float(demand):.3f} {unit}; "
            f"SRd = {float(resistance):.3f} {unit}, with the other external "
            "section actions set to zero."
        )

    action_boxes = st.columns(4)
    for box, label, key, unit in zip(
        action_boxes,
        (r"Axial $N$", r"Bending $M$", r"Shear $V$", r"Torsion $T$"),
        ("n", "m", "v", "t"),
        ("kN", "kNm", "kN", "kNm"),
    ):
        box.metric(label, _pct(c.get(f"r_{key}")), help=_action_help(key, unit))
    st.caption(
        "DK NA 6.3.2(6): each ratio uses the resistance to that sectional "
        "action acting alone. N retains its entered tension/compression sign; "
        "the M resistance follows the entered biaxial moment direction."
    )
    st.caption(
        "This is an internal cross-section resistance check. It does not replace "
        "a separate member and detailing assessment under Annex F where that "
        "assessment applies."
    )

    st.divider()
    st.markdown(r"**DK NA 6.3.2(6): $\sum(S_{Ed}/S_{Rd})\leq1$**")
    d1, d2 = st.columns([1, 2])
    torsion_assessment_note = (
        presentation.combined_torsion_assessment_note(c)
    )
    dkna_failed = bool(
        c.get("dkna_valid")
        and presentation.combined_dkna_limit_satisfied(c) is False
    )
    if dkna_failed:
        _verdict_metric(
            d1,
            r"$\sum(S_{Ed}/S_{Rd})$",
            _pct(c.get("dkna_sum")),
            False,
        )
        d2.caption(
            "The DK NA action-alone sum exceeds its numerical limit. This is a "
            "definite combined failure even where another torsion prerequisite "
            "also remains unverified."
        )
        if c.get("m_v_independent"):
            _manual_warning(
                st,
                "calculation-warning",
                presentation.combined_dkna_assumption_note(c),
            )
        if torsion_assessment_note:
            _manual_warning(
                st,
                "calculation-warning",
                torsion_assessment_note,
            )
    elif not c.get("dkna_valid"):
        d1.metric(r"$\sum(S_{Ed}/S_{Rd})$", "-")
        d1.caption("NOT ASSESSED")
        d2.caption(
            "No DK NA verdict is given because one or more matching action-alone "
            "resistances could not be determined."
        )
        _manual_warning(
            st,
            "calculation-warning",
            "The DK NA combined interaction is NOT ASSESSED. Check the section, "
            "materials and complete Plastic bending sweep, then recalculate.",
        )
        if torsion_assessment_note:
            _manual_warning(
                st,
                "calculation-warning",
                torsion_assessment_note,
            )
    elif torsion_assessment_note:
        d1.metric(r"$\sum(S_{Ed}/S_{Rd})$", _pct(c.get("dkna_sum")))
        dkna_component_status = str(
            c.get("dkna_status") or "NOT ASSESSED"
        )
        d1.caption(f"{dkna_component_status} numerical component")
        if c.get("m_v_independent"):
            d2.caption(
                "The separate M/V route is selected as a design assumption. "
                "N + M + T and N + V + T are calculated independently, and "
                "the governing sum is retained as numerical component evidence. "
                "It is not an overall M-V-T verdict while the torsion "
                "longitudinal-reinforcement requirement governs."
            )
            _manual_warning(
                st,
                "calculation-warning",
                presentation.combined_dkna_assumption_note(c),
            )
        else:
            d2.caption(
                "The DK NA action-alone sum is retained as numerical component "
                "evidence. It is not an overall M-V-T verdict while the torsion "
                "longitudinal-reinforcement requirement governs."
            )
        _manual_warning(
            st,
            "calculation-warning",
            torsion_assessment_note,
        )
    elif c["m_v_independent"]:
        dkna_status = presentation.combined_dkna_status(c)
        if dkna_status == "FAIL":
            _verdict_metric(
                d1,
                r"$\sum(S_{Ed}/S_{Rd})$",
                _pct(c["dkna_sum"]),
                False,
            )
        else:
            d1.metric(r"$\sum(S_{Ed}/S_{Rd})$", _pct(c["dkna_sum"]))
            d1.caption(dkna_status)
        d2.caption(
            "The separate M/V route is selected as a design assumption. "
            "N + M + T and N + V + T are calculated independently, and the "
            "governing sum is shown."
        )
        _manual_warning(
            st,
            "calculation-warning",
            presentation.combined_dkna_assumption_note(c),
        )
    else:
        _verdict_metric(
            d1,
            r"$\sum(S_{Ed}/S_{Rd})$",
            _pct(c["dkna_sum"]),
            c["dkna_ok"],
        )
        d2.caption(
            "sum = N + M + V + T, using each action-alone resistance. Select the "
            "separate M/V route only after separately verifying the capacity, "
            "distribution and anchorage of the additional longitudinal "
            "reinforcement required for shear; that result remains CONDITIONAL."
        )

    st.markdown("**Physical resistance components**")
    component_boxes = st.columns(3)
    for box, component in zip(
        component_boxes,
        presentation.combined_physical_components(c),
    ):
        status = component["status"]
        value = _pct(component["util"])
        if status in {"PASS", "FAIL"}:
            _verdict_metric(
                box,
                component["label"],
                value,
                status == "PASS",
                help=component["note"],
            )
        else:
            box.metric(component["label"], value, help=component["note"])
            box.caption(status)
    st.caption(
        "Concrete strut, closed stirrup and longitudinal reinforcement are "
        "independent physical checks; no combined transverse utilisation is shown."
    )

    cr = c.get("crushing")
    if cr is not None and cr.get("valid"):
        st.divider()
        st.markdown(r"**Concrete compression strut (6.29): "
                    r"$T_{Ed}/T_{Rd,max}+V_{Ed}/V_{Rd,max}\leq1$**")
        val = cr["value"]
        ok_c = viz.util_ok(val)
        cc1, cc2 = st.columns([1, 2])
        _verdict_metric(
            cc1, "Sum", _pct(val), ok_c,
        )
        cc2.caption(
            f"At a common strut $\\cot\\theta={cr['cot']:.2f}$ "
            f"($\\theta={cr['theta_deg']:.1f}^\\circ$). "
            f"$T_{{Rd,max}}={cr['trd_max']:.1f}$ kNm, "
            f"$V_{{Rd,max}}={cr['vrd_max']:.1f}$ kN."
        )
        st.plotly_chart(viz.vt_interaction_figure(
            cr["vrd_max"], cr["trd_max"], cr["v_ed"], cr["t_ed"],
            show_verdict=True),
            width="stretch")
    elif cr is not None and not cr.get("valid"):
        _manual_warning(st, "calculation-warning", _no_common_angle_msg(cr))
    else:
        st.caption("The shear+torsion crushing interaction (6.29) needs shear links "
                   "(for VRd,max); enable them in the shear block.")

    tr = c.get("transverse")
    if tr is not None and not tr.get("valid"):
        st.divider()
        st.markdown("**Shared stirrup: shear + torsion transverse steel**")
        _manual_warning(st, "calculation-warning", _no_common_angle_msg(tr))
    elif tr is not None:
        st.divider()
        st.markdown("**Shared stirrup: shear + torsion transverse steel**")
        t1, t2, t3 = st.columns(3)
        t1.metric("Shear share", _pct(tr["shear_fraction"]))
        t2.metric("Torsion share", _pct(tr["torsion_fraction"]))
        _verdict_metric(
            t3,
            "Closed-stirrup utilisation",
            _pct(tr["u_stirrup"]),
            viz.util_ok(tr["u_stirrup"]),
        )
        if tr["shear_credited"]:
            st.caption(
                f"Concrete carries the shear (VEd = {tr['v_ed']:.1f} kN <= "
                f"VRd,c = {tr['vrd_c']:.1f} kN, 6.2.1). Stirrup allocation to "
                "shear is zero, so the closed stirrup serves torsion."
            )
        else:
            st.caption("VEd > VRd,c, so the stirrup carries both: shear and torsion "
                       "demands add on the shared closed stirrup.")
        st.caption(
            f"At the member strut angle $\\cot\\theta={tr['cot']:.2f}$ "
            f"($\\theta={tr['theta_deg']:.1f}^\\circ$), one angle is shared "
            "by every shear and torsion check (6.3.2(2)), selected to minimise "
            "the governing utilisation."
        )

    st.divider()
    st.markdown("**Longitudinal reinforcement: combined M + V + T tension chord**")
    lg = c.get("longitudinal")
    if lg is not None and lg["valid"]:
        ax_lbl = lg["axis"]
        face_lbl = viz.tension_face_label(
            lg.get("tension_low", True), lg.get("axis")
        )
        gets_shift = lg.get("gets_shift", True)
        face_desc = (f"the shear tension face ({face_lbl})" if gets_shift else
                     f"the shear COMPRESSION face ({face_lbl}) -- the torsion "
                     "tension governs there (no shear shift, bending relieves it)")
        biaxial = lg.get("biaxial", False)
        ok_l = lg["ok"]
        coverage = lg.get("off_not_evaluated")
        fallback = presentation.required_chord_fallback(c)
        fell_back = fallback is not None
        g1, g2, g3 = st.columns(3)
        g1.metric(fr"$M_{{Ed}}$ (about {ax_lbl})", f"{lg['m_ed']:.1f} kNm")
        g2.metric(r"$M_{Ed,\mathrm{total}}$", f"{lg['m_total']:.1f} kNm",
                  help="bending + shear shift + torsion, as an equivalent moment "
                       "on the governing chord face")
        if coverage:
            g3.metric(
                r"$M_{Ed,\mathrm{total}}/M_{Rd}$",
                _pct(lg["util"]),
                help=(
                    "NOT ASSESSED: longitudinal chord coverage is incomplete; "
                    "see the warning below."
                ),
            )
        elif fell_back:
            g3.metric(
                r"$M_{Ed,\mathrm{total}}/M_{Rd}$",
                _pct(lg["util"]),
                help=(
                    "NOT ASSESSED: the displayed capacity is a pure-axis "
                    "substitute; see the warning below."
                    if not lg.get("conditional", True)
                    else "NOT ASSESSED: another required chord face uses a "
                         "pure-axis substitute; see the warning below."
                ),
            )
        else:
            _verdict_metric(
                g3,
                r"$M_{Ed,\mathrm{total}}/M_{Rd}$",
                _pct(lg["util"]),
                ok_l,
            )
        st.caption(
            f"Governing chord: {face_desc} about the {ax_lbl}-axis. "
            r"$M_{Ed,total}$ includes bending, shear shift and half the perimeter "
            "torsion share: "
            f"{lg['m_ed']:.1f} + {lg['mv']:.1f} + {lg['mt']:.1f} = {lg['m_total']:.1f}$ "
            f"kNm versus $M_{{Rd}} = {lg['m_rd']:.1f}$ kNm "
            + viz.chord_mrd_label(ax_lbl, lg.get("m_off", 0.0),
                                  lg.get("conditional", True))
            + f"; $z = {lg['z']:.3f}$ m. "
            + viz.chord_angle_note(lg.get("theta_mode"))
        )
        if lg["capped"]:
            st.caption(
                "Shear shift is capped at section MRd under 6.2.3(7), used here "
                "because a cross-section calculation has no member peak moment."
            )
        if fell_back:
            fallback_axis = fallback.get("axis", "?")
            fallback_face = (
                "negative" if fallback.get("tension_low", True)
                else "positive"
            )
            _manual_warning(
                st,
                "calculation-warning",
                f"The required {fallback_axis}-axis {fallback_face} face uses a "
                "pure-axis substitute after its conditional solve failed. The "
                "chord result may be optimistic; use the "
                + chr(0x03A3) + "(SEd/SRd) result above.")
        if coverage == "subdivided":
            st.caption("Compound (subdivided) section: the torsion longitudinal "
                       "steel is per sub-tube, so the off-axis chord's torsion "
                       "share is not evaluated; the " + chr(0x03A3) + "(SEd/SRd) "
                       "sum above covers the interaction.")
        elif coverage == "not_solved":
            _manual_warning(
                st,
                "calculation-warning",
                "At least one torsion-carrying chord face could not be solved or "
                "has no tension steel. The displayed chord may not govern; use "
                "the " + chr(0x03A3) + "(SEd/SRd) interaction result above.")
        elif not fell_back and biaxial and not lg.get("has_torsion"):
            st.caption("The off-axis chord carries only its bending tension (no "
                       "torsion is acting), which the biaxial bending utilisation "
                       "in the " + chr(0x03A3) + "(SEd/SRd) sum already covers.")
        elif not fell_back:
            st.caption("The DK NA " + chr(0x03A3) + "(SEd/SRd) result above uses "
                       "full biaxial bending utilisation and governs the combined "
                       "assessment.")
        _render_chord_off(
            c.get("chord_off"),
            assessment_complete=not bool(coverage) and not fell_back,
        )
    else:
        st.caption(
            f"Additional longitudinal demand: torsion {chr(0x03A3)}Asl = "
            f"{c['asl_torsion']:.0f} mm2 around the perimeter (6.28), and shear "
            f"{_DELTA}Ftd = {c['delta_ftd']:.1f} kN on the tension chord (6.18). "
            "Enable links for the full utilisation check."
        )


_VIEW_ALIASES = {
    "M-V-T Interaction": "M-V-T Combined",
    "Bridge Calculations": "Results Overview",
    "Section": "Results Overview",
    "Material laws": "Results Overview",
    "Stress-Strain diagrams": "Results Overview",
}


def _case_entries_for_view(inp, results, family):
    """Return calculated entries, or current input rows before calculation."""
    entries = (results or {}).get(f"{family}_cases")
    if entries is not None:
        return entries
    return [
        {
            "name": record[load_cases.NAME],
            "description": record[load_cases.DESCRIPTION],
            "actions": record,
            "evaluated": False,
            "results": {},
        }
        for record in case_analysis.case_records(inp, family)
    ]


def _render_selected_case_actions(family, actions, inp=None):
    """Compact, consistently named action evidence for the selected case."""
    if family == "plastic":
        st.dataframe(
            [{
                "N_Ed [kN]": actions.get("n_ed_kn", 0.0),
                "Mx_Ed [kNm]": actions.get("mx_ed_knm", 0.0),
                "My_Ed [kNm]": actions.get("my_ed_knm", 0.0),
                "Vx_Ed [kN]": actions.get("vx_ed_kn", 0.0),
                "Vy_Ed [kN]": actions.get("vy_ed_kn", 0.0),
                "Vx face": actions.get("vx_face", "auto"),
                "Vy face": actions.get("vy_face", "auto"),
                "T_Ed [kNm]": actions.get("t_ed_knm", 0.0),
                "Minimum reinforcement": (
                    "Yes" if actions.get("check_minimum_reinforcement") else ""
                ),
            }],
            hide_index=True,
            width="stretch",
        )
        return
    st.dataframe(
        [
            {
                "Action part": "Long-term",
                "N_Ed [kN]": actions.get("n_long_ed_kn", 0.0),
                "Mx_Ed [kNm]": actions.get("mx_long_ed_knm", 0.0),
                "My_Ed [kNm]": actions.get("my_long_ed_knm", 0.0),
            },
            {
                "Action part": "Short-term",
                "N_Ed [kN]": actions.get("n_short_ed_kn", 0.0),
                "Mx_Ed [kNm]": actions.get("mx_short_ed_knm", 0.0),
                "My_Ed [kNm]": actions.get("my_short_ed_knm", 0.0),
            },
        ],
        hide_index=True,
        width="stretch",
    )
    criteria = []
    for label, key in (
        ("long-term", LONG_TERM_PERMITTED_CRACK_WIDTH_KEY),
        ("short-term", SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY),
    ):
        criterion = (inp or {}).get(key, 0.0)
        criterion_text = (
            "no comparison"
            if criterion is None
            or pd.isna(criterion)
            or float(criterion) == 0.0
            else f"{float(criterion):.3f} mm"
        )
        criteria.append(f"{label} {criterion_text}")
    st.caption(
        "Stresses are reported for this action. Crack width: "
        + (
            "calculated with the selected method"
            if actions.get("calculate_crack_width")
            else "not requested"
        )
        + ". User criteria: " + "; ".join(criteria) + "."
    )


def _selected_case_context(inp, results, family):
    """Render a persistent case picker and return its input/result slice."""
    entries = _case_entries_for_view(inp, results, family)
    if not entries:
        return inp, {}, None
    key = f"_{family}_result_case_index"
    if not isinstance(st.session_state.get(key), int):
        st.session_state[key] = 0
    st.session_state[key] = min(st.session_state[key], len(entries) - 1)

    def label(index):
        entry = entries[index]
        name = entry.get("name") or f"Row {index + 1}"
        description = entry.get("description") or ""
        return f"{name} - {description}" if description else name

    index = st.selectbox(
        "Case",
        range(len(entries)),
        key=key,
        format_func=label,
        persist_state="session",
        help="Select the named case shown in this result view.",
    )
    entry = entries[index]
    actions = entry.get("actions") or {}
    _render_selected_case_actions(family, actions, inp)
    if family == "elastic":
        case_inp = case_analysis.elastic_case_input(inp, actions)
    else:
        case_inp = case_analysis.plastic_case_input(inp, actions)
    return case_inp, entry.get("results") or {}, entry


def _store_completed_analysis(
    inp,
    results,
    engineering_input_sha256,
    project_input_sha256,
    calculation_revision,
):
    """Publish one successful calculation without disturbing prior evidence."""

    st.session_state["results"] = results
    st.session_state["result_sig"] = inp["signature"]
    st.session_state["result_plastic_sig"] = inp["plastic_sig"]
    st.session_state["result_elastic_sig"] = inp["elastic_sig"]
    st.session_state["result_fatigue_sig"] = inp["fatigue_sig"]
    st.session_state["result_plastic_case_context_sig"] = inp[
        "plastic_case_context_sig"
    ]
    st.session_state["result_elastic_case_context_sig"] = inp[
        "elastic_case_context_sig"
    ]
    st.session_state["result_plastic_bending_context_sig"] = inp[
        "plastic_bending_context_sig"
    ]
    if results:
        # Result payloads remain visible after an edit so the engineer can see
        # the last calculated state. Keep the matching inputs with them.
        st.session_state["result_input_snapshot"] = copy.deepcopy(inp)
        st.session_state["calculation_record"] = {
            "performed_at_utc": datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
            "sector_version": APP_VERSION,
            "source_revision": calculation_revision,
            # ``input_sha256`` preserves the project correlation used
            # by existing files. Result reuse is governed by the explicit frozen
            # engineering identity, which excludes report metadata/preferences.
            "input_sha256": project_input_sha256,
            "engineering_input_sha256": engineering_input_sha256,
            "result_sha256": project_io.result_sha256(results),
        }
    else:
        st.session_state.pop("result_input_snapshot", None)
    # Re-default the Plastic view's neutral-axis state to this result's governing
    # angle. The user can still pick another rotation until the next Calculate.
    st.session_state.pop("pl_state", None)


def _calculation_failure_message(error: Exception) -> str:
    """Return the complete engineer-facing calculation failure message."""

    detail = engineer_messages.error_detail(
        error,
        fallback=EngineerMessage(
            "CALCULATION-BLOCKED",
            "Sector could not complete the calculation. Review the inputs and try again",
        ),
        context="calculation",
    )
    return "Calculation blocked: " + detail + "."


@st.fragment
def _analysis_workspace(inp):
    """Render and operate the main analysis workspace independently.

    View switches and result-detail controls do not alter the input tabs. Keeping
    them in a fragment avoids rebuilding every input widget for those interactions.
    An input edit still causes a normal full rerun and invokes this function with a
    freshly built input payload.
    """
    app_run_probe.open_fragment_run(st.session_state, "analysis")
    # No input widget owns these keys on Analysis. Restore the last completed
    # draft on every fragment rerun before autosave, hashing or calculation reads.
    _restore_input_state(replace=True)
    # This must live inside the fragment: Calculate, View and result-detail changes
    # rerun only this function, not the top-level page dispatcher.  Quick Section
    # and the manual do not invoke the fragment, so their exclusion is preserved.
    _measured_autosave()

    # Migrate a renamed view label before either workspace control renders. A keyed
    # selectbox otherwise keeps returning the stale string, which the dispatch no
    # longer recognises.
    current_view = st.session_state.get(
        "view", st.session_state.get("_workspace_view", VIEWS[0])
    )
    current_view = _VIEW_ALIASES.get(current_view, current_view)
    if current_view not in VIEWS:
        current_view = VIEWS[0]
    st.session_state["view"] = current_view

    c_view, c_calc = st.columns([3, 1])
    # Create Calculate before View; the containers preserve their visual order.
    c_calc.markdown("<div style='height:1.7em'></div>", unsafe_allow_html=True)
    calc = c_calc.button(
        "Calculate", type="primary", key="calculate", width="stretch",
        help="Run the selected analysis for the current inputs.",
    )
    case_errors = list(
        case_analysis.validation_errors(inp)
        if "plastic_cases" in inp or "elastic_cases" in inp
        else presentation.required_action_set_errors(inp)
    )
    heightened_errors = _heightened_crack_control_validation_errors(inp)
    section_input_issues = input_issues.section_issues(inp)
    requested_input_issues = (
        *input_issues.case_issues(case_errors),
        *input_issues.heightened_issues(heightened_errors),
    )
    all_input_issues = (*section_input_issues, *requested_input_issues)
    # Retire the former semicolon-joined state if this code hot-reloads into a
    # live 0.93 session. The current validator output is the only authority.
    st.session_state.pop("_case_error", None)
    if calc and all_input_issues:
        st.session_state[_SHOW_INPUT_ISSUES_KEY] = True
        calc = False
    elif not requested_input_issues:
        st.session_state.pop(_SHOW_INPUT_ISSUES_KEY, None)
    if calc:
        # Reuse a previously computed half whose split signature is unchanged, so a
        # Both run that touched only elastic (or only plastic) inputs recomputes just
        # the affected analysis.
        prev = st.session_state.get("results") or {}
        reuse_plastic = (
            prev.get("plastic")
            if st.session_state.get("result_plastic_sig") == inp["plastic_sig"]
            else None
        )
        reuse_elastic = (
            prev.get("elastic")
            if st.session_state.get("result_elastic_sig") == inp["elastic_sig"]
            else None
        )
        reuse_plastic_cases = (
            prev.get("plastic_cases")
            if st.session_state.get("result_plastic_case_context_sig")
            == inp["plastic_case_context_sig"]
            else None
        )
        reuse_elastic_cases = (
            prev.get("elastic_cases")
            if st.session_state.get("result_elastic_case_context_sig")
            == inp["elastic_case_context_sig"]
            else None
        )
        reuse_plastic_bending_cases = (
            prev.get("plastic_cases")
            if st.session_state.get("result_plastic_bending_context_sig")
            == inp["plastic_bending_context_sig"]
            else None
        )
        reuse_fatigue = (
            prev.get("fatigue")
            if st.session_state.get("result_fatigue_sig") == inp["fatigue_sig"]
            else None
        )
        engineering_input_sha256 = _engineering_input_hash(inp)
        project_input_sha256 = _calculation_project_hash(inp)
        calculation_revision = source_revision()
        try:
            completed = run_analysis(
                inp,
                reuse_plastic=reuse_plastic,
                reuse_elastic=reuse_elastic,
                reuse_plastic_cases=reuse_plastic_cases,
                reuse_plastic_bending_cases=reuse_plastic_bending_cases,
                reuse_elastic_cases=reuse_elastic_cases,
                reuse_fatigue=reuse_fatigue,
            )
        except Exception as exc:
            st.session_state["_case_error"] = _calculation_failure_message(exc)
            st.error(st.session_state["_case_error"])
        else:
            _store_completed_analysis(
                inp,
                completed,
                engineering_input_sha256,
                project_input_sha256,
                calculation_revision,
            )

    view = c_view.selectbox(
        "View", VIEWS, key="view",
        help="Calculated result view. Geometry and material-law previews are beside "
             "their inputs; press Calculate to update these results.",
    )
    st.session_state["_workspace_view"] = view

    results = st.session_state.get("results")
    # An invalid section (a void that disconnects the concrete, steel outside the
    # outline) makes run_analysis return {}. Treat that like no result so the badge
    # does not read green "up to date" for a calculation that produced nothing.
    stale = bool(results) and st.session_state.get("result_sig") != inp["signature"]
    if not results:
        c_calc.caption("Not calculated yet")
    elif stale:
        c_calc.caption(":orange[Inputs changed -- recalculate]")
    else:
        c_calc.caption(":green[Results up to date]")
    if stale and view in _RESULT_VIEWS:
        _manual_warning(
            st,
            "results-stale",
            "Inputs changed since the last calculation - press Calculate to update.",
        )
    visible_input_issues = list(section_input_issues)
    if st.session_state.get(_SHOW_INPUT_ISSUES_KEY):
        visible_input_issues.extend(requested_input_issues)
    _render_input_issues(
        tuple(visible_input_issues),
        key_prefix="analysis-input-issue",
    )
    result_snapshot = st.session_state.get("result_input_snapshot")
    if stale and view in _RESULT_VIEWS and result_snapshot is None:
        # Sessions can survive a Streamlit hot reload. A result payload without
        # its matching input snapshot cannot be rendered against edited inputs
        # without creating internally inconsistent evidence. Keep it hidden until
        # a current calculation records the missing snapshot.
        st.error(
            "The displayed calculation cannot be matched to its inputs. Press "
            "Calculate before viewing the results."
        )
        app_run_probe.close_fragment_run(st.session_state)
        return
    if inp.get("fatigue_assignment_error"):
        assignment_text = engineer_messages.error_detail(
            inp["fatigue_assignment_error"],
            fallback=_FATIGUE_DISPLAY_ERROR,
            context="fatigue assignment",
        )
        _manual_warning(
            st,
            "input-invalid",
            assignment_text
            + " Other requested analyses remain available; the fatigue result "
            "will be INVALID until the assignments are resolved.",
        )
    fatigue_errors = tuple(
        ((results or {}).get("fatigue") or {}).get("errors") or ()
    )
    if fatigue_errors and view != "Fatigue Results":
        visible_fatigue_errors = tuple(
            engineer_messages.error_detail(
                error,
                fallback=_FATIGUE_DISPLAY_ERROR,
                context="fatigue result error",
            )
            for error in fatigue_errors
        )
        st.error(
            "Fatigue not assessed: "
            + "; ".join(visible_fatigue_errors)
            + "."
        )

    # A stale result must be rendered wholly against the inputs that produced it.
    # Apply this before selecting a case or deciding which checks were enabled so
    # every result view receives one internally consistent input/result pair.
    result_inp = result_snapshot if stale else inp
    family = (
        "elastic" if view == "Elastic Results"
        else "plastic" if (
            view == "Detailing"
            and (
                result_inp.get("minimum_reinforcement_on")
                or result_inp.get("transverse_detailing_on")
            )
        )
        else "plastic" if view in {
            "Plastic Results", "N-M Interaction", "Shear", "Torsion",
            "M-V-T Combined",
        }
        else None
    )
    view_inp, view_results = result_inp, results
    if family:
        view_inp, view_results, _entry = _selected_case_context(
            result_inp, results, family
        )

    if view == "Results Overview":
        results_overview_view(result_inp, results, stale=stale)
    elif view == "Plastic Results":
        plastic_view(view_inp, view_results)
    elif view == "N-M Interaction":
        interaction_view(view_inp, view_results)
    elif view == "Fatigue Results":
        fatigue_view(result_inp, results, stale=stale)
    elif view == "Detailing":
        detailing_view(view_inp, view_results, global_results=results)
    elif view == "Shear":
        shear_view(view_inp, view_results)
    elif view == "Torsion":
        torsion_view(view_inp, view_results)
    elif view == "M-V-T Combined":
        combined_view(view_inp, view_results)
    else:
        elastic_view(view_inp, view_results, global_results=results)
    app_run_probe.close_fragment_run(st.session_state)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

_v093_state_purged = (
    session_state_migrations.purge_retired_bridge_session_state(
        st.session_state
    )
)
_autosave_startup()        # restore the last autosaved session (BriCoS-style) on launch
_apply_pending_project()   # restore an uploaded project before any widget is built
_normalise_report_profile_session_state()
# Migrate renamed workspace choices even while Inputs is selected; otherwise an old
# widget value can survive indefinitely until the engineer first opens Analysis.
if st.session_state.get("view") in _VIEW_ALIASES:
    st.session_state["view"] = _VIEW_ALIASES[st.session_state["view"]]
manual_open = bool(st.session_state.get("_manual_open"))
quick_section_open = bool(st.session_state.get("_qs_open"))
# Fragment exit buttons cannot modify an already-instantiated navigation widget.
# They queue the destination instead; a full rerun applies it here, before the
# widget is created again.
next_main_page = st.session_state.pop("_next_main_page", None)
if next_main_page in app_run_probe.WORKSPACE_NAMES:
    st.session_state["_main_page"] = next_main_page
# The Quick Section builder remains a full-width Analysis view. The manual is a
# dialog and deliberately leaves the current workspace page mounted behind it.
if quick_section_open:
    st.session_state["_main_page"] = "Analysis"
st.session_state.setdefault("_main_page", "Inputs")
if st.session_state["_main_page"] not in app_run_probe.WORKSPACE_NAMES:
    st.session_state["_main_page"] = "Inputs"
_restore_input_state(
    replace=(
        _v093_state_purged
        or bool(st.session_state.get(_INPUT_BUILD_KEY, False))
        or (
            st.session_state.get("_main_page") == "Inputs"
            and st.session_state.get(_LAST_WORKSPACE_KEY) in {"Analysis", "Report"}
        )
    )
)
_restore_report_state(
    replace=(
        _v093_state_purged
        or bool(st.session_state.get(_REPORT_BUILD_KEY, False))
        or (
            st.session_state.get("_main_page") == "Report"
            and st.session_state.get(_LAST_WORKSPACE_KEY) in {"Inputs", "Analysis"}
        )
    )
)
app_run_probe.stop_phase(st.session_state, _startup_probe)

for _migration_warning in st.session_state.get(
    "_project_migration_warnings", ()
):
    _manual_warning(st, "crack-criterion-missing", _migration_warning)

main_page = st.segmented_control(
    "Workspace",
    list(app_run_probe.WORKSPACE_NAMES),
    key="_main_page",
    on_change=_snapshot_completed_input_state,
    required=True,
    width="stretch",
    label_visibility="collapsed",
)

if main_page == "Inputs":
    st.session_state[_REPORT_BUILD_KEY] = False
    _input_workspace()
elif main_page == "Analysis":
    st.session_state[_REPORT_BUILD_KEY] = False
    reset_input_stage_mounts(st.session_state)
    st.session_state[_LAST_WORKSPACE_KEY] = "Analysis"
    inp = st.session_state.get("_latest_inputs")
    if quick_section_open:
        _quick_section_viewport()
    elif inp is None:
        st.info("Open Inputs once to initialise the section and analysis settings.")
        st.button(
            "Open Inputs", type="primary", key="initialise_inputs",
            on_click=_set_main_page, args=("Inputs",),
        )
    else:
        _analysis_workspace(inp)
else:
    reset_input_stage_mounts(st.session_state)
    _report_workspace(st.session_state.get("_latest_inputs"))

# Keep the current workspace visible behind the manual. The
# dialog is imported and built only while open, so its figures stay off the normal
# rerun path.
if manual_open:
    import manual                          # lazy: keep the manual off the hot path
    manual.render_manual_dialog()
app_run_probe.close_run(st.session_state)
