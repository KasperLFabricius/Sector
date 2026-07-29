"""Serialise the full input set to a project file and read it back (Save / Load).

A project file is JSON: the four point tables (concrete corners, voids, bars and
tendons, all in millimetres), Plastic and Elastic load-case tables, an optional
grouped fatigue spectrum, and the remaining material and analysis-setting inputs.
The geometry and action tables are the source of truth. Live numerical results
are recomputed on load; optional compact crack-control, fatigue-conformance, and
bridge-methodology evidence is kept only inside the input-hash-bound
calculation-provenance record.

The functions here are pure (no Streamlit), so the round trip is unit-tested
directly; the app wires the download / upload widgets to them.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone

import pandas as pd

import bridge_inputs
import fatigue_analysis
import fatigue_inputs
import load_cases
import material_catalog
import reinforcement_table as rebar_table
from sector import (
    bridge,
    codes,
    conformance,
    danish_bridge,
    detailing,
    geometry,
    multidirectional,
    sls,
)
from sector import __version__ as sector_version
from sector.build_info import source_revision

FORMAT = "sector-project"
VERSION = 22  # v22: sourced multidirectional crack/shear interaction evidence
DEFAULT_SLS_TENDON_BOND = "Plain round (k1 = 1.6)"
DEFAULT_SLS_TENDON_XI = 0.0
DEFAULT_SLS_CRITERION_MODE = sls.CRITERION_MODE_LEGACY
DEFAULT_SLS_PRESTRESS_CLASS = sls.PRESTRESS_REINFORCED_UNBONDED
DEFAULT_SLS_PROTECTION_CLASS = sls.PROTECTION_NOT_ESTABLISHED
DEFAULT_SLS_EXPOSURE_CLASS = sls.EXPOSURE_NOT_ESTABLISHED
DEFAULT_SLS_BRIDGE_EXPOSURE_CLASS = sls.BRIDGE_EXPOSURE_NOT_ESTABLISHED
DEFAULT_SLS_DK_MEMBER_CLASS = danish_bridge.NOT_ESTABLISHED
DEFAULT_SLS_DECOMPRESSION = sls.DECOMPRESSION_NOT_ESTABLISHED

_UNSUPPORTED_SEPARATE_STRUT_KEYS = frozenset({
    "shear_cot_min",
    "shear_cot_max",
    "torsion_cot_min",
    "torsion_cot_max",
})


def _reject_unsupported_strut_settings(raw_scalars: dict) -> None:
    if _UNSUPPORTED_SEPARATE_STRUT_KEYS.intersection(raw_scalars):
        raise ValueError(
            "unsupported pre-0.91 project: separate shear/torsion strut-angle "
            "settings cannot be loaded; recreate the shared compression-strut "
            "range explicitly"
        )


# The four point-table session-state keys (DataFrames, millimetres).
TABLE_KEYS = ["corners_base", "hole_base", "bars_base", "tendons_base"]
REINFORCEMENT_TABLE_KEYS = {"bars_base": "bar", "tendons_base": "tendon"}
CASE_TABLE_KEYS = list(load_cases.CASE_TABLE_KEYS)
FATIGUE_TABLE_KEYS = [fatigue_inputs.SPECTRUM_TABLE_KEY]
BRIDGE_TABLE_KEYS = list(bridge_inputs.TABLE_KEYS)
PROJECT_TABLE_KEYS = (
    TABLE_KEYS + CASE_TABLE_KEYS + FATIGUE_TABLE_KEYS + BRIDGE_TABLE_KEYS
)
_CASE_PAYLOAD_KEYS = {
    load_cases.PLASTIC_TABLE_KEY: "plastic",
    load_cases.ELASTIC_TABLE_KEY: "elastic",
}
_GEOMETRY_COLUMNS = ("x (mm)", "y (mm)")


def _geometry_points(frame: pd.DataFrame, label: str) -> list[tuple[float, float]]:
    """Read one project geometry frame without silently dropping bad rows."""
    if not all(column in frame.columns for column in _GEOMETRY_COLUMNS):
        raise ValueError(
            f"{label} table must contain columns "
            f"'{_GEOMETRY_COLUMNS[0]}' and '{_GEOMETRY_COLUMNS[1]}'"
        )
    points: list[tuple[float, float]] = []
    for row_number, (_, row) in enumerate(frame.iterrows(), start=1):
        values = [row.get(column) for column in _GEOMETRY_COLUMNS]
        try:
            point = tuple(float(value) / 1000.0 for value in values)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{label} point {row_number} is not numeric"
            ) from exc
        if not all(math.isfinite(value) for value in point):
            raise ValueError(
                f"{label} point {row_number} contains a non-finite coordinate"
            )
        points.append(point)
    return points


def _project_holes(hole_frame: pd.DataFrame | None) -> list[list[tuple[float, float]]]:
    """Read separator-delimited project hole rings in metres."""
    if hole_frame is None or hole_frame.empty:
        return []
    if not all(column in hole_frame.columns for column in _GEOMETRY_COLUMNS):
        raise ValueError(
            "hole table must contain columns "
            f"'{_GEOMETRY_COLUMNS[0]}' and '{_GEOMETRY_COLUMNS[1]}'"
        )

    holes: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for row_number, (_, row) in enumerate(hole_frame.iterrows(), start=1):
        raw = [row.get(column) for column in _GEOMETRY_COLUMNS]
        blank = [pd.isna(value) for value in raw]
        if all(blank):
            if current:
                holes.append(current)
                current = []
            continue
        if any(blank):
            raise ValueError(
                f"hole table row {row_number} is a partial separator/point"
            )
        try:
            point = tuple(float(value) / 1000.0 for value in raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"hole point {row_number} is not numeric") from exc
        if not all(math.isfinite(value) for value in point):
            raise ValueError(
                f"hole point {row_number} contains a non-finite coordinate"
            )
        current.append(point)
    if current:
        holes.append(current)
    return holes


def _project_geometry(tables: dict) -> tuple[list, list[list]] | None:
    """Return project outer/void rings in metres, or ``None`` when intentionally blank."""
    holes = _project_holes(tables.get("hole_base"))
    outer_frame = tables.get("corners_base")
    if outer_frame is None or outer_frame.empty:
        if holes:
            raise ValueError("hole geometry requires a non-empty outer ring")
        return None
    outer = _geometry_points(outer_frame, "outer ring")
    return outer, holes


def _validate_project_geometry(tables: dict) -> None:
    """Apply the same canonical topology gate used by the API, UI, and solvers."""
    rings = _project_geometry(tables)
    if rings is None:
        return
    outer, holes = rings
    try:
        geometry.require_valid_section_topology(outer, holes)
    except geometry.GeometryTopologyError as exc:
        raise ValueError(f"invalid project section geometry: {exc}") from exc

FATIGUE_SCALAR_KEYS = (
    fatigue_inputs.DETAIL_CATALOG_KEY,
    fatigue_inputs.BASIS_KEY,
    "fatigue_on",
    "fatigue_edition",
    "fatigue_check_steel",
    "fatigue_check_concrete",
    "fatigue_concrete_method",
    "fatigue_concrete_miner_basis",
    "fatigue_concrete_miner_source",
    "fatigue_factor_mode",
    "fatigue_factor_approval",
    "fatigue_gamma0",
    "fatigue_gamma3",
    "fatigue_gamma_c",
    "fatigue_gamma_s",
    "fatigue_gamma_ff",
    "fatigue_beta_cc_t0",
    "fatigue_t0_days",
    "fatigue_concrete_k1",
    "fatigue_concrete_c",
    "fatigue_source",
)

BRIDGE_SCALAR_KEYS = (
    "design_methodology",
    "bridge_brittle_method",
    "bridge_expected_box_walls",
    "bridge_minimum_scope",
    "bridge_shear_scope",
    "bridge_exposure",
    "bridge_asset_class",
    "bridge_infrastructure_manager",
    "bridge_manager_source",
    "bridge_project_basis_source",
    "bridge_authority_approval_reference",
    "bridge_traffic_fatigue_applicability",
    "bridge_traffic_fatigue_model",
    "bridge_traffic_fatigue_source",
    "bridge_environment_class",
    "bridge_environment_source",
    "bridge_special_rules",
    "bridge_departure_applicability",
    "bridge_departure_source",
    "bridge_deviations",
    "bridge_control_class",
    "bridge_control_source",
    "bridge_consequence_class",
    "bridge_consequence_source",
    "bridge_high_strength_approval",
    "bridge_high_strength_approval_reference",
    "bridge_execution_conditions_source",
    "bridge_surface_condition",
    "bridge_deicing_applicability",
    "bridge_deicing_source",
    "bridge_cover_category",
    "bridge_nominal_cover_mm",
    "bridge_cover_source",
    "bridge_collision_risk_applicability",
    "bridge_alpha_cc_basis",
    "bridge_alpha_cc_custom_methodology",
    "bridge_alpha_cc_approval_reference",
    "bridge_alpha_ct",
    "bridge_alpha_ct_basis",
    "bridge_alpha_ct_custom_methodology",
    "bridge_alpha_ct_approval_reference",
)

TORSION_FACTOR_SCALAR_KEYS = (
    "torsion_factor_mode",
    "torsion_gamma0",
    "torsion_gamma3",
    "torsion_gamma_ct",
    "torsion_factor_approval",
)

OPTIONAL_FACTOR_VALUE_KEYS = (
    "fatigue_gamma_s",
    "fatigue_gamma_c",
    "torsion_gamma_ct",
)

FACTOR_NUMERIC_SCALAR_KEYS = (
    "fatigue_gamma0",
    "fatigue_gamma3",
    "fatigue_gamma_s",
    "fatigue_gamma_c",
    "torsion_gamma0",
    "torsion_gamma3",
    "torsion_gamma_ct",
)

# Every scalar / string input that makes up a project. Missing keys are skipped on
# save, so an older or partial file still loads what it has.
SCALAR_KEYS = [
    # Quick Section builder settings (durable mirror keys; the builder writes the
    # generated points into the tables, which are saved separately).
    "qsv_shape", "qsv_b_mm", "qsv_h_mm", "qsv_bf_mm", "qsv_hf_mm", "qsv_bw_mm",
    "qsv_hw_mm", "qsv_wall_mm", "qsv_dia_mm", "qsv_ring_n", "qsv_ring_d",
    "qsv_ring_c_mm", "qsv_qs_rebar_mode", "qsv_qs_cover_to_edge",
    "qsv_bot_n", "qsv_bot_d", "qsv_bot_s",
    "qsv_top_n", "qsv_top_d", "qsv_top_s", "qsv_bot_c_mm", "qsv_top_c_mm",
    "qsv_bot_n2", "qsv_top_n2", "qsv_bot_layers", "qsv_top_layers",
    "qsv_layer_s", "qsv_bot_off_d", "qsv_top_off_d", "qsv_tnd_n",
    "qsv_tnd_a", "qsv_tnd_c_mm", "qsv_tnd_layers", "qsv_tnd_layer_s",
    # Concrete.
    "conc_preset", "conc_fck", "conc_gamma_c", "conc_k_tc", "conc_alpha_cc",
    "conc_eps_c2", "conc_eps_cu2", "conc_n", "conc_Ec", "sls_fctm",
    # Stable material catalogues. The former flat material keys below remain in
    # this allow-list only so old project files and API callers can be migrated.
    material_catalog.MILD_CATALOG_KEY,
    material_catalog.PRESTRESS_CATALOG_KEY,
    fatigue_inputs.DETAIL_CATALOG_KEY,
    fatigue_inputs.BASIS_KEY,
    # Mild reinforcement.
    "mild_preset", "mild_active_comp", "mild_fytk", "mild_fyck", "mild_futk",
    "mild_eut", "mild_gamma_y", "mild_gamma_u", "mild_gamma_E", "mild_k",
    "mild_ey0t", "mild_ey0c", "mild_Es",
    # Prestressing steel.
    "pre_preset", "pre_IS", "pre_fytk", "pre_futk", "pre_eut",
    "pre_gamma_y", "pre_gamma_u", "pre_gamma_E", "pre_k", "pre_ey0t", "pre_Es",
    # Loads. The modular ratios n_l/n_s are derived from Ec, Es, Ep and the creep
    # coefficient (el_phi), so they are not persisted -- they follow from the moduli.
    "pl_case_id", "pl_case_type", "pl_case_source",
    "el_case_id", "el_case_type", "el_case_source",
    "pl_P", "pl_Mx", "pl_My", "el_long_P", "el_long_Mx", "el_long_My", "el_phi",
    "el_short_P", "el_short_Mx", "el_short_My",
    # Analysis & result settings.
    "mode", "v_min", "v_max", "v_inc", "pl_check_util",
    "pl_interaction",
    "sls_cw", "sls_phi", "sls_bond", "sls_code", "sls_member",
    "sls_tendon_bond", "sls_tendon_xi",
    "sls_criterion_mode", "sls_prestress_class", "sls_protection_class",
    "sls_exposure_class", "sls_bridge_exposure_class",
    "sls_dk_member_class",
    "sls_exposure_context",
    "sls_check_appearance", "sls_appearance_limit",
    "sls_check_durability", "sls_decompression_applicability",
    "sls_project_characteristic_limit", "sls_project_frequent_limit",
    "sls_project_quasi_permanent_limit",
    "sls_wk_limit", "sls_conc_limit_pct", "sls_steel_limit_pct",
    "sls_pre_limit_pct", "sls_limit_source",
    *multidirectional.CRACK_INPUT_KEYS,
    # Fatigue factor provenance. Presets expose every applied multiplier;
    # overrides remain complete approved final inputs.
    "fatigue_on", "fatigue_edition", "fatigue_check_steel",
    "fatigue_check_concrete", "fatigue_factor_mode",
    "fatigue_factor_approval",
    "fatigue_gamma0", "fatigue_gamma3",
    "fatigue_gamma_c", "fatigue_gamma_s",
    "fatigue_concrete_method",
    "fatigue_concrete_miner_basis", "fatigue_concrete_miner_source",
    "fatigue_gamma_ff", "fatigue_beta_cc_t0", "fatigue_t0_days",
    "fatigue_concrete_k1", "fatigue_concrete_c", "fatigue_source",
    # Whole-calculation methodology and DS/EN 1992-2 base evidence controls.
    *BRIDGE_SCALAR_KEYS,
    # Modelled-direction reinforcement, shear/torsion links and clear spacing.
    "minimum_reinforcement_on", "transverse_detailing_on",
    "clear_spacing_on", "detailing_edition",
    "detailing_member_type", "detailing_cut_direction",
    "detailing_d_upper", "detailing_include_tendons",
    "transverse_ductility_class", "transverse_apply_ductility_reduction",
    # Shear (VRd,c without links, and the variable-strut VRd with links).
    "shear_on", "shear_method", "shear_axis", "shear_tension", "shear_V", "shear_bw",
    "shear_vx_bw", "shear_vy_bw",
    "shear_dlower",
    "shear_links", "shear_link_legs", "shear_vx_link_legs", "shear_vy_link_legs",
    "shear_link_dia", "shear_link_s", "shear_fywk",
    "shear_vx_transverse_leg_spacing", "shear_vy_transverse_leg_spacing",
    *multidirectional.SHEAR_INPUT_KEYS,
    "strut_cot_min", "strut_cot_max",
    # Torsion (thin-walled tube, TRd). The stirrup is the shared shear_link_* one.
    "torsion_on", "torsion_method", "torsion_T", "torsion_tef", "torsion_nu_v",
    "torsion_factor_mode", "torsion_gamma0", "torsion_gamma3",
    "torsion_gamma_ct", "torsion_factor_approval",
    # Sub-tube subdivision for compound / T-sections (6.3.1(3)).
    "torsion_subdivide", "torsion_nsub",
    "torsion_sub_x0", "torsion_sub_y0", "torsion_sub_x1", "torsion_sub_y1",
    "torsion_sub_x2", "torsion_sub_y2", "torsion_sub_x3", "torsion_sub_y3",
    "torsion_sub_b0", "torsion_sub_h0", "torsion_sub_b1", "torsion_sub_h1",
    "torsion_sub_b2", "torsion_sub_h2", "torsion_sub_b3", "torsion_sub_h3",
    # Combined M-V-T interaction.
    "combined_on", "combined_method", "combined_mv_independent",
    "capacity_steel_material_id",
    "label_scale", "label_min_gap",
    # Report metadata.
    "rep_proj_no", "rep_proj_name", "rep_section", "rep_rev", "rep_author",
    "rep_checker", "rep_approver", "rep_comments", "rep_report_content",
]

# A preset prefills its fields only when the selection *changes*; on load we set
# each change-marker to the loaded preset so the saved field values are kept.
PREV_MARKERS = {"conc_prev": "conc_preset", "mild_prev": "mild_preset",
                "pre_prev": "pre_preset"}


def _scalar(value):
    """Coerce a value to a JSON-native scalar (handle numpy / pandas types)."""
    if hasattr(value, "item"):           # numpy / pandas scalar
        return value.item()
    return value


def _validate_factor_scalars(scalars: dict) -> None:
    """Reject non-numeric/Boolean factors at every project-file boundary."""
    for key in FACTOR_NUMERIC_SCALAR_KEYS:
        if key not in scalars:
            continue
        value = scalars[key]
        if value is None and key in OPTIONAL_FACTOR_VALUE_KEYS:
            continue
        try:
            codes.strict_positive_real(value, key)
        except ValueError as exc:
            raise ValueError(f"invalid project material factor: {exc}") from exc


def _validate_crack_numeric_scalars(scalars: dict) -> None:
    """Reject Boolean, non-numeric and non-finite crack inputs at file boundaries."""
    for key in sls.CRACK_NUMERIC_INPUT_KEYS:
        if key not in scalars:
            continue
        value = scalars[key]
        if sls.is_boolean_value(value) or isinstance(value, str):
            raise ValueError(
                f"invalid project crack-control input: {key} must be a real "
                "number, not Boolean/text"
            )
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid project crack-control input: {key} must be a real number"
            ) from exc
        if not math.isfinite(number):
            raise ValueError(
                f"invalid project crack-control input: {key} must be finite"
            )


def _validate_multidirectional_scalars(
    scalars: dict,
    *,
    project_version: int,
) -> None:
    """Validate typed PR-06 fields and reject active current-schema omissions."""

    for key in multidirectional.INTERACTION_BOOLEAN_INPUT_KEYS:
        if key in scalars and not isinstance(scalars[key], bool):
            raise ValueError(
                f"invalid project multidirectional input: {key} must be an "
                "explicit Boolean selection"
            )
    for key in multidirectional.INTERACTION_NUMERIC_INPUT_KEYS:
        if key not in scalars:
            continue
        value = scalars[key]
        if isinstance(value, bool) or isinstance(value, str):
            raise ValueError(
                f"invalid project multidirectional input: {key} must be a "
                "finite real number, not Boolean/text"
            )
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid project multidirectional input: {key} must be a "
                "finite real number"
            ) from exc
        if not math.isfinite(number):
            raise ValueError(
                f"invalid project multidirectional input: {key} must be finite"
            )
    for key in multidirectional.INTERACTION_TEXT_INPUT_KEYS:
        if key in scalars and not isinstance(scalars[key], str):
            raise ValueError(
                f"invalid project multidirectional input: {key} must be text"
            )

    crack_method = scalars.get("crack_interaction_method")
    if (
        crack_method is not None
        and (
            not isinstance(crack_method, str)
            or crack_method not in multidirectional.CRACK_METHODS
        )
    ):
        raise ValueError("unknown crack-interaction methodology")
    shear_method = scalars.get("shear_interaction_method")
    if (
        shear_method is not None
        and (
            not isinstance(shear_method, str)
            or shear_method not in multidirectional.SHEAR_METHODS
        )
    ):
        raise ValueError("unknown shear-interaction methodology")
    depth_route = scalars.get("shear_interaction_depth_route")
    if (
        depth_route is not None
        and depth_route not in multidirectional.DEPTH_ROUTES
    ):
        raise ValueError("unknown biaxial-shear effective-depth route")
    combination = scalars.get("crack_interaction_combination")
    if (
        combination is not None
        and (
            not isinstance(combination, str)
            or combination not in sls.SLS_COMBINATIONS
        )
    ):
        raise ValueError("unknown crack-interaction SLS combination")

    if project_version < VERSION:
        return
    required_by_method = {
        multidirectional.CRACK_METHOD_DK_2004: {
            "crack_interaction_case_id",
            "crack_interaction_criterion_id",
            "crack_interaction_combination",
            "crack_interaction_axis_x",
            "crack_interaction_axis_y",
            "crack_interaction_orthogonal",
            "crack_interaction_plane_stress",
            "crack_interaction_no_discontinuity",
            "crack_interaction_angle_deg",
            "crack_interaction_spacing_x_mm",
            "crack_interaction_spacing_y_mm",
            "crack_interaction_strain_x",
            "crack_interaction_strain_y",
        },
        multidirectional.CRACK_METHOD_EN_2023: {
            "crack_interaction_case_id",
            "crack_interaction_criterion_id",
            "crack_interaction_combination",
            "crack_interaction_axis_x",
            "crack_interaction_axis_y",
            "crack_interaction_orthogonal",
            "crack_interaction_membrane",
            "crack_interaction_no_discontinuity",
            "crack_interaction_angle_deg",
            "crack_interaction_spacing_x_mm",
            "crack_interaction_spacing_y_mm",
            "crack_interaction_strain_x",
            "crack_interaction_strain_y",
            "crack_interaction_transverse_strain",
        },
        multidirectional.CRACK_METHOD_PROJECT: {
            "crack_interaction_case_id",
            "crack_interaction_criterion_id",
            "crack_interaction_combination",
            "crack_interaction_axis_x",
            "crack_interaction_axis_y",
            "crack_interaction_domain_confirmed",
            "crack_interaction_component_x_mm",
            "crack_interaction_component_y_mm",
            "crack_interaction_limit_x_mm",
            "crack_interaction_limit_y_mm",
            "crack_interaction_exponent",
            "crack_interaction_source",
            "crack_interaction_approval",
        },
        multidirectional.SHEAR_METHOD_EN_2023: {
            "shear_interaction_axis_x",
            "shear_interaction_axis_y",
            "shear_interaction_planar_member",
            "shear_interaction_same_control_point",
            "shear_interaction_per_unit_width",
            "shear_interaction_out_of_plane",
            "shear_interaction_depth_route",
            "shear_interaction_resultant_resistance_kn_per_m",
            "shear_interaction_source",
            "shear_interaction_approval",
        },
        multidirectional.SHEAR_METHOD_PROJECT: {
            "shear_interaction_axis_x",
            "shear_interaction_axis_y",
            "shear_interaction_domain_confirmed",
            "shear_interaction_exponent",
            "shear_interaction_source",
            "shear_interaction_approval",
        },
    }
    active_methods = []
    active_method_selections = (
        (
            "crack_interaction_on",
            "crack_interaction_method",
            crack_method,
        ),
        (
            "shear_interaction_on",
            "shear_interaction_method",
            shear_method,
        ),
    )
    for enabled_key, method_key, method in active_method_selections:
        if scalars.get(enabled_key) is not True:
            continue
        if method_key not in scalars or method is None:
            raise ValueError(
                "current project has an active multidirectional method with "
                f"missing required fields: {method_key}"
            )
        active_methods.append(method)
    for method in active_methods:
        required = required_by_method.get(method, set())
        missing = sorted(required - set(scalars))
        if missing:
            raise ValueError(
                "current project has an active multidirectional method with "
                "missing required fields: " + ", ".join(missing)
            )


def _validate_bridge_scalars(scalars: dict) -> None:
    """Reject unknown or falsely numeric bridge-methodology state."""

    methodology = scalars.get("design_methodology")
    if methodology is not None and methodology not in bridge.METHODOLOGIES:
        raise ValueError("unknown design methodology")
    option_fields = {
        "bridge_brittle_method": bridge.BRITTLE_METHODS,
        "bridge_minimum_scope": bridge.MINIMUM_SCOPES,
        "bridge_shear_scope": bridge.SHEAR_SCOPES,
        "bridge_exposure": bridge.BRIDGE_EXPOSURES,
        "sls_bridge_exposure_class": sls.BRIDGE_EXPOSURE_CLASSES,
        "sls_dk_member_class": danish_bridge.MEMBER_CLASSES,
        "bridge_asset_class": danish_bridge.ASSET_CLASSES,
        "bridge_infrastructure_manager": (
            danish_bridge.INFRASTRUCTURE_MANAGERS
        ),
        "bridge_traffic_fatigue_applicability": (
            danish_bridge.FATIGUE_APPLICABILITY
        ),
        "bridge_environment_class": danish_bridge.ENVIRONMENT_CLASSES,
        "bridge_departure_applicability": (
            danish_bridge.APPLICABILITY_OPTIONS
        ),
        "bridge_control_class": danish_bridge.CONTROL_CLASSES,
        "bridge_consequence_class": danish_bridge.CONSEQUENCE_CLASSES,
        "bridge_high_strength_approval": danish_bridge.APPROVAL_STATES,
        "bridge_surface_condition": danish_bridge.SURFACE_CONDITIONS,
        "bridge_deicing_applicability": (
            danish_bridge.APPLICABILITY_OPTIONS
        ),
        "bridge_cover_category": danish_bridge.COVER_CATEGORIES,
        "bridge_collision_risk_applicability": (
            danish_bridge.APPLICABILITY_OPTIONS
        ),
        "bridge_alpha_cc_basis": conformance.BASIS_OPTIONS,
        "bridge_alpha_ct_basis": conformance.BASIS_OPTIONS,
    }
    for key, options in option_fields.items():
        if key in scalars and scalars[key] not in options:
            raise ValueError(f"unknown bridge methodology option: {key}")
    if "bridge_expected_box_walls" in scalars:
        raw = scalars["bridge_expected_box_walls"]
        if conformance.is_boolean(raw) or isinstance(raw, str):
            raise ValueError(
                "bridge_expected_box_walls must be a non-negative integer"
            )
        try:
            number = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "bridge_expected_box_walls must be a non-negative integer"
            ) from exc
        if (
            not math.isfinite(number)
            or number < 0.0
            or not number.is_integer()
        ):
            raise ValueError(
                "bridge_expected_box_walls must be a non-negative integer"
            )
    if "bridge_nominal_cover_mm" in scalars:
        raw = scalars["bridge_nominal_cover_mm"]
        if raw is not None:
            if conformance.is_boolean(raw) or isinstance(raw, str):
                raise ValueError(
                    "bridge_nominal_cover_mm must be a finite non-negative number"
                )
            try:
                number = float(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "bridge_nominal_cover_mm must be a finite non-negative number"
                ) from exc
            if not math.isfinite(number) or number < 0.0:
                raise ValueError(
                    "bridge_nominal_cover_mm must be a finite non-negative number"
                )
    if "bridge_alpha_ct" in scalars:
        try:
            codes.strict_positive_real(
                scalars["bridge_alpha_ct"],
                "bridge_alpha_ct",
            )
        except ValueError as exc:
            raise ValueError(f"invalid Danish bridge coefficient: {exc}") from exc
    typed_text_fields = (
        "bridge_manager_source",
        "bridge_project_basis_source",
        "bridge_authority_approval_reference",
        "bridge_traffic_fatigue_model",
        "bridge_traffic_fatigue_source",
        "bridge_environment_source",
        "bridge_special_rules",
        "bridge_departure_source",
        "bridge_deviations",
        "bridge_control_source",
        "bridge_consequence_source",
        "bridge_high_strength_approval_reference",
        "bridge_execution_conditions_source",
        "bridge_deicing_source",
        "bridge_cover_source",
        "bridge_alpha_cc_custom_methodology",
        "bridge_alpha_cc_approval_reference",
        "bridge_alpha_ct_custom_methodology",
        "bridge_alpha_ct_approval_reference",
    )
    for key in typed_text_fields:
        if key in scalars:
            try:
                conformance.typed_text(scalars[key], key)
            except ValueError as exc:
                raise ValueError(
                    f"invalid Danish bridge provenance: {exc}"
                ) from exc


def _setdefault_danish_bridge_scalars(scalars: dict) -> None:
    """Install blocking, non-inferred defaults for every PR-05 field."""

    defaults = {
        "bridge_asset_class": danish_bridge.NOT_ESTABLISHED,
        "bridge_infrastructure_manager": danish_bridge.NOT_ESTABLISHED,
        "bridge_manager_source": "",
        "bridge_project_basis_source": "",
        "bridge_authority_approval_reference": "",
        "bridge_traffic_fatigue_applicability": (
            danish_bridge.NOT_ESTABLISHED
        ),
        "bridge_traffic_fatigue_model": "",
        "bridge_traffic_fatigue_source": "",
        "bridge_environment_class": danish_bridge.NOT_ESTABLISHED,
        "bridge_environment_source": "",
        "bridge_special_rules": "",
        "bridge_departure_applicability": danish_bridge.NOT_ESTABLISHED,
        "bridge_departure_source": "",
        "bridge_deviations": "",
        "bridge_control_class": danish_bridge.NOT_ESTABLISHED,
        "bridge_control_source": "",
        "bridge_consequence_class": danish_bridge.NOT_ESTABLISHED,
        "bridge_consequence_source": "",
        "bridge_high_strength_approval": danish_bridge.NOT_ESTABLISHED,
        "bridge_high_strength_approval_reference": "",
        "bridge_execution_conditions_source": "",
        "bridge_surface_condition": danish_bridge.NOT_ESTABLISHED,
        "bridge_deicing_applicability": danish_bridge.NOT_ESTABLISHED,
        "bridge_deicing_source": "",
        "bridge_cover_category": danish_bridge.NOT_ESTABLISHED,
        "bridge_nominal_cover_mm": None,
        "bridge_cover_source": "",
        "bridge_collision_risk_applicability": (
            danish_bridge.NOT_ESTABLISHED
        ),
        "bridge_alpha_cc_basis": conformance.STANDARD_BASIS,
        "bridge_alpha_cc_custom_methodology": "",
        "bridge_alpha_cc_approval_reference": "",
        "bridge_alpha_ct": 1.0,
        "bridge_alpha_ct_basis": conformance.STANDARD_BASIS,
        "bridge_alpha_ct_custom_methodology": "",
        "bridge_alpha_ct_approval_reference": "",
        "sls_dk_member_class": DEFAULT_SLS_DK_MEMBER_CLASS,
    }
    for key, value in defaults.items():
        scalars.setdefault(key, value)


def _default_fatigue_miner_basis(scalars: dict) -> str:
    """Return the only unambiguous default for the selected Miner method."""

    method = scalars.get(
        "fatigue_concrete_method",
        fatigue_analysis.CONCRETE_MINER,
    )
    if method == fatigue_analysis.CONCRETE_PROJECT_MINER:
        return fatigue_inputs.MINER_BASIS_PROJECT_SN_RELATION
    if method != fatigue_analysis.CONCRETE_MINER:
        return fatigue_inputs.MINER_BASIS_NOT_ESTABLISHED
    edition = scalars.get("fatigue_edition")
    if (
        edition == fatigue_inputs.EC2_2_2005_AC
        and scalars.get("design_methodology")
        in bridge.BRIDGE_METHODOLOGIES
    ):
        return fatigue_inputs.MINER_BASIS_BRIDGE_STANDARD
    if edition == fatigue_inputs.EC2_2023:
        return fatigue_inputs.MINER_BASIS_2023_STANDARD
    return fatigue_inputs.MINER_BASIS_NOT_ESTABLISHED


def _normalise_fatigue_miner_basis(scalars: dict) -> None:
    """Resolve only method/edition combinations that have one safe basis."""

    expected = _default_fatigue_miner_basis(scalars)
    if (
        expected != fatigue_inputs.MINER_BASIS_NOT_ESTABLISHED
        and scalars.get("fatigue_concrete_miner_basis") in {
            None,
            "",
            fatigue_inputs.MINER_BASIS_NOT_ESTABLISHED,
        }
    ):
        scalars["fatigue_concrete_miner_basis"] = expected


def _validate_fatigue_miner_scalars(
    scalars: dict,
    *,
    allow_missing: bool = False,
) -> None:
    """Reject only malformed or numerically unusable concrete Miner input."""

    relevant = {
        "fatigue_concrete_method",
        "fatigue_concrete_c",
        "fatigue_concrete_miner_basis",
        "fatigue_concrete_miner_source",
    }
    if not relevant.intersection(scalars):
        return
    method = scalars.get(
        "fatigue_concrete_method",
        fatigue_analysis.CONCRETE_MINER,
    )
    if method not in fatigue_analysis.CONCRETE_METHODS:
        raise ValueError("unknown concrete fatigue method")
    if method not in fatigue_analysis.CONCRETE_MINER_METHODS:
        return
    if "fatigue_concrete_c" not in scalars and allow_missing:
        return
    coefficient = scalars.get(
        "fatigue_concrete_c",
        fatigue_inputs.STANDARD_CONCRETE_MINER_C,
    )
    miner_basis = str(
        scalars.get("fatigue_concrete_miner_basis") or ""
    ).strip()
    if (
        allow_missing
        and miner_basis
        == fatigue_inputs.MINER_BASIS_NOT_ESTABLISHED
    ):
        expected = _default_fatigue_miner_basis(scalars)
        if expected != fatigue_inputs.MINER_BASIS_NOT_ESTABLISHED:
            miner_basis = expected
    if allow_missing and not miner_basis:
        return
    errors = fatigue_analysis.concrete_miner_parameter_errors(
        edition=str(scalars.get("fatigue_edition") or "").strip(),
        concrete_method=method,
        miner_basis=miner_basis,
        miner_source=str(
            scalars.get("fatigue_concrete_miner_source") or ""
        ).strip(),
        coefficient_c=coefficient,
        design_methodology=str(
            scalars.get("design_methodology")
            or bridge.COMPONENT_METHODS
        ),
    )
    if errors:
        raise ValueError("invalid concrete fatigue Miner input: " + "; ".join(errors))


def _cell(v):
    """A cell as a finite float, or ``None`` for a blank / non-numeric value.

    The point editors are paste-friendly, so a cell can momentarily hold a stray
    string; serialise that as a blank (the analysis skips it) rather than raising.
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _table_to_obj(df, table_key=None) -> dict:
    """A DataFrame as ``{columns, rows}`` with blanks / stray cells stored as null."""
    kind = REINFORCEMENT_TABLE_KEYS.get(table_key)
    if df is None:
        if not kind:
            return {"columns": [], "rows": []}
        df = rebar_table.empty_table()
    if kind:
        df = rebar_table.normalise_table(df, kind)
    cols = [str(c) for c in df.columns]
    rows = []
    for row in df.itertuples(index=False, name=None):
        values = []
        for column, value in zip(cols, row):
            if kind and column in rebar_table.TEXT_COLUMNS:
                values.append(rebar_table.text_cell(value))
            else:
                values.append(_cell(value))
        rows.append(values)
    return {"columns": cols, "rows": rows}


def _obj_to_table(obj, table_key=None) -> pd.DataFrame:
    """Rebuild a canonical DataFrame from ``{columns, rows}``.

    Raises :class:`ValueError` on a malformed table object (not a ``{columns,
    rows}`` mapping) so the caller can report it rather than crash on an
    ``AttributeError``.
    """
    if not isinstance(obj, dict):
        raise ValueError("table entry is not a {columns, rows} object")
    cols = list(obj.get("columns", []))
    rows = obj.get("rows", []) or []
    try:
        df = pd.DataFrame(rows, columns=cols)
    except (ValueError, TypeError) as exc:      # ragged / non-tabular rows
        raise ValueError("table rows are not tabular") from exc
    kind = REINFORCEMENT_TABLE_KEYS.get(table_key)
    if kind:
        return rebar_table.normalise_table(df, kind)
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.astype("float64") if cols else df


def _bridge_tables_from_payload(payload: dict | None) -> dict:
    """Read and validate the dedicated text-preserving bridge table payload."""

    if payload is None:
        return {}
    payload_version = payload.get("version")
    if payload_version not in {1, bridge_inputs.VERSION}:
        raise ValueError("unknown bridge evidence schema version")
    raw_tables = payload.get("tables")
    if not isinstance(raw_tables, dict):
        raise ValueError("bridge tables must be an object")
    output = {}
    errors = []
    for key in bridge_inputs.TABLE_KEYS:
        frame = bridge_inputs.table_from_records(
            raw_tables.get(key, []),
            key,
        )
        output[key] = frame
        errors.extend(bridge_inputs.table_errors(frame, key))
    if errors:
        raise ValueError("invalid bridge evidence: " + "; ".join(errors))
    return output


def _canonical_inputs(tables: dict, scalars: dict) -> dict:
    """Return the JSON-native input payload used by both save and hash checks."""
    has_load_inputs = (
        any(key in tables for key in load_cases.CASE_TABLE_KEYS)
        or any(key in scalars for key in load_cases.LEGACY_SCALAR_KEYS)
    )
    scalar_payload = {
        k: _scalar(scalars[k])
        for k in SCALAR_KEYS
        if (
            k in scalars
            and not (has_load_inputs and k in load_cases.LEGACY_SCALAR_KEYS)
        )
    }
    # Validate active-method completeness before defaults are added. Otherwise
    # a raw/headless omission could be turned into an apparently deliberate
    # empty source, axis, or domain field at the save boundary.
    _validate_multidirectional_scalars(
        scalar_payload,
        project_version=VERSION,
    )
    # Crack-control applicability fields are written even for deliberately
    # partial saves so a reused UI session cannot inherit a previous project's
    # combination route or silently revive the pre-v17 max-of-duration check.
    scalar_payload.setdefault(
        "sls_tendon_bond", DEFAULT_SLS_TENDON_BOND
    )
    scalar_payload.setdefault("sls_tendon_xi", DEFAULT_SLS_TENDON_XI)
    scalar_payload.setdefault(
        "sls_criterion_mode", DEFAULT_SLS_CRITERION_MODE
    )
    scalar_payload.setdefault(
        "sls_prestress_class", DEFAULT_SLS_PRESTRESS_CLASS
    )
    scalar_payload.setdefault(
        "sls_protection_class", DEFAULT_SLS_PROTECTION_CLASS
    )
    scalar_payload.setdefault(
        "sls_exposure_class", DEFAULT_SLS_EXPOSURE_CLASS
    )
    scalar_payload.setdefault(
        "sls_bridge_exposure_class",
        DEFAULT_SLS_BRIDGE_EXPOSURE_CLASS,
    )
    scalar_payload.setdefault("sls_exposure_context", "")
    scalar_payload.setdefault("sls_check_appearance", False)
    scalar_payload.setdefault("sls_appearance_limit", 0.0)
    scalar_payload.setdefault("sls_check_durability", False)
    scalar_payload.setdefault(
        "sls_decompression_applicability", DEFAULT_SLS_DECOMPRESSION
    )
    scalar_payload.setdefault("sls_project_characteristic_limit", 0.0)
    scalar_payload.setdefault("sls_project_frequent_limit", 0.0)
    scalar_payload.setdefault("sls_project_quasi_permanent_limit", 0.0)
    for key, value in {
        **multidirectional.crack_configuration({}),
        **multidirectional.shear_configuration({}),
    }.items():
        scalar_payload.setdefault(key, value)
    # Empty override widgets use ``None`` in Streamlit state. Persist them exactly
    # like absent optional values so a no-edit load/save keeps the canonical input
    # hash stable and never synthesises an approved numeric factor.
    for key in OPTIONAL_FACTOR_VALUE_KEYS:
        if scalar_payload.get(key) is None:
            scalar_payload.pop(key, None)
    _validate_factor_scalars(scalar_payload)
    _validate_crack_numeric_scalars(scalar_payload)
    _validate_multidirectional_scalars(
        scalar_payload,
        project_version=VERSION,
    )
    # These v6 controls were global because one shear component existed. Their
    # values are consumed only by the v7 migration and are not written again.
    for key in ("shear_axis", "shear_tension", "shear_bw", "shear_link_legs"):
        scalar_payload.pop(key, None)
    if (
        scalar_payload.get("fatigue_on")
        or "fatigue_gamma_s" in scalar_payload
        or "fatigue_gamma_c" in scalar_payload
    ):
        scalar_payload.setdefault("fatigue_gamma0", 1.0)
        scalar_payload.setdefault("fatigue_gamma3", 1.0)
        scalar_payload.setdefault("fatigue_factor_approval", "")
        has_numeric_fatigue_factor = (
            "fatigue_gamma_s" in scalar_payload
            or "fatigue_gamma_c" in scalar_payload
        )
        default_fatigue_factor_mode = fatigue_inputs.FACTOR_MODE_PRESET
        if has_numeric_fatigue_factor:
            default_fatigue_factor_mode = (
                fatigue_inputs.FACTOR_MODE_OVERRIDE
                if str(
                    scalar_payload.get("fatigue_factor_approval") or ""
                ).strip()
                else fatigue_inputs.FACTOR_MODE_LEGACY
            )
        scalar_payload.setdefault(
            "fatigue_factor_mode",
            default_fatigue_factor_mode,
        )
        scalar_payload.setdefault(
            "fatigue_concrete_method",
            fatigue_analysis.CONCRETE_MINER,
        )
        if (
            scalar_payload["fatigue_concrete_method"]
            in fatigue_analysis.CONCRETE_MINER_METHODS
        ):
            scalar_payload.setdefault(
                "fatigue_concrete_c",
                fatigue_inputs.STANDARD_CONCRETE_MINER_C,
            )
        scalar_payload.setdefault(
            "fatigue_concrete_miner_basis",
            _default_fatigue_miner_basis(scalar_payload),
        )
        _normalise_fatigue_miner_basis(scalar_payload)
        scalar_payload.setdefault("fatigue_concrete_miner_source", "")
        if (
            scalar_payload["fatigue_concrete_miner_basis"]
            not in fatigue_inputs.MINER_BASES
        ):
            raise ValueError("unknown concrete fatigue Miner applicability")
    if scalar_payload.get("torsion_on"):
        scalar_payload.setdefault(
            "torsion_factor_mode", codes.FACTOR_MODE_PRESET
        )
        scalar_payload.setdefault("torsion_gamma0", 1.0)
        scalar_payload.setdefault("torsion_gamma3", 1.0)
        scalar_payload.setdefault("torsion_factor_approval", "")
    # Current project files write only the catalogue representation. External
    # callers may still supply the former flat material values; migrate them at
    # the save/hash boundary so two equivalent inputs have one canonical form.
    for kind, legacy_keys in (
        ("mild", material_catalog.LEGACY_MILD_KEYS),
        ("prestress", material_catalog.LEGACY_PRESTRESS_KEYS),
    ):
        key = material_catalog.catalog_key(kind)
        if key in scalar_payload:
            scalar_payload[key] = material_catalog.normalise_catalog(
                scalar_payload[key], kind
            )
        elif any(legacy in scalar_payload for legacy in legacy_keys):
            scalar_payload[key] = material_catalog.from_legacy_scalars(
                scalar_payload, kind
            )
        if key in scalar_payload:
            for legacy in legacy_keys:
                scalar_payload.pop(legacy, None)
    if fatigue_inputs.DETAIL_CATALOG_KEY in scalar_payload:
        scalar_payload[fatigue_inputs.DETAIL_CATALOG_KEY] = (
            fatigue_inputs.normalise_catalog(
                scalar_payload[fatigue_inputs.DETAIL_CATALOG_KEY]
            )
        )
    if fatigue_inputs.BASIS_KEY in scalar_payload:
        scalar_payload[fatigue_inputs.BASIS_KEY] = (
            fatigue_inputs.canonical_basis(
                scalar_payload[fatigue_inputs.BASIS_KEY]
            )
        )
    elif scalar_payload.get("fatigue_on"):
        raise ValueError("fatigue basis is required when fatigue is enabled")
    elif "fatigue_source" in scalar_payload:
        basis = fatigue_inputs.default_basis()
        basis["spectrum_source"] = str(
            scalar_payload.get("fatigue_source") or ""
        ).strip()
        scalar_payload[fatigue_inputs.BASIS_KEY] = basis
    if fatigue_inputs.BASIS_KEY in scalar_payload:
        # ``fatigue_source`` was the pre-v10 one-line precursor to the structured
        # basis.  Current files have one canonical provenance representation.
        scalar_payload.pop("fatigue_source", None)
    scalar_payload.setdefault(
        "design_methodology",
        bridge.COMPONENT_METHODS,
    )
    if scalar_payload["design_methodology"] not in bridge.METHODOLOGIES:
        raise ValueError("unknown design methodology")
    scalar_payload.setdefault(
        "bridge_brittle_method",
        bridge.BRITTLE_NOT_ESTABLISHED,
    )
    scalar_payload.setdefault("bridge_expected_box_walls", 0)
    scalar_payload.setdefault(
        "bridge_minimum_scope",
        bridge.MINIMUM_SCOPE_NOT_ESTABLISHED,
    )
    scalar_payload.setdefault(
        "bridge_shear_scope",
        bridge.SHEAR_SCOPE_NOT_ESTABLISHED,
    )
    scalar_payload.setdefault(
        "bridge_exposure",
        bridge.BRIDGE_EXPOSURE_NOT_ESTABLISHED,
    )
    _setdefault_danish_bridge_scalars(scalar_payload)
    _validate_bridge_scalars(scalar_payload)
    _validate_fatigue_miner_scalars(scalar_payload)
    content = {
        "tables": {k: _table_to_obj(tables.get(k), k) for k in TABLE_KEYS},
        "scalars": scalar_payload,
    }
    if has_load_inputs:
        legacy = load_cases.tables_from_legacy_scalars(scalars)
        content["load_cases"] = {
            payload_key: load_cases.table_records(
                tables.get(table_key, legacy[table_key]), table_key
            )
            for table_key, payload_key in _CASE_PAYLOAD_KEYS.items()
        }
    if fatigue_inputs.SPECTRUM_TABLE_KEY in tables:
        content["fatigue"] = {
            "spectrum": fatigue_inputs.spectrum_records(
                tables[fatigue_inputs.SPECTRUM_TABLE_KEY]
            )
        }
    content["bridge"] = {
        "version": bridge_inputs.VERSION,
        "tables": {
            key: bridge_inputs.table_records(tables.get(key), key)
            for key in bridge_inputs.TABLE_KEYS
        },
    }
    return content


def input_sha256(tables: dict, scalars: dict) -> str:
    """Hash the canonical calculation inputs, independent of save timestamps."""
    content = _canonical_inputs(tables, scalars)
    canonical = json.dumps(
        content, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bridge_publication_matches_inputs(record) -> bool:
    """Return whether a safe bridge snapshot proved current-input correlation."""

    if not isinstance(record, dict):
        return False
    validation = record.get("publication_validation")
    return (
        isinstance(validation, dict)
        and validation.get("status") == "ACCEPTED"
    )


_CALCULATION_PROVENANCE_FIELDS = (
    "performed_at_utc",
    "sector_version",
    "source_revision",
    "input_sha256",
    "crack_control",
    "multidirectional_interaction",
    "fatigue_conformance",
    "bridge_methodology",
)


def publication_safe_calculation_record(
    calculation,
    *,
    calculation_inputs,
    input_digest,
    calculation_results=None,
) -> dict | None:
    """Return one canonical, fail-closed calculation-provenance record.

    ``matches_saved_inputs`` is a durable rejection latch.  Once an earlier
    publication boundary rejected evidence, loading or re-saving the sanitized
    record must not infer a match merely because the rejected field is no longer
    present and the input hash still agrees. ``calculation_inputs`` is the one
    canonical input snapshot used to reconstruct methodology, bridge fatigue
    conformance, and Danish crack applicability, so callers cannot supply those
    contexts independently. ``calculation_results`` is accepted only for a live
    session boundary; saved projects do not restore it and therefore cannot
    authenticate assessed interaction conclusions without recalculation.
    """

    if not isinstance(calculation, Mapping):
        return None
    current_inputs = (
        calculation_inputs
        if isinstance(calculation_inputs, Mapping)
        else {}
    )
    design_methodology = current_inputs.get("design_methodology")
    fatigue_context = fatigue_analysis.bridge_publication_context(
        current_inputs
    )
    expected_crack_numerical_method = (
        sls.expected_danish_bridge_crack_numerical_method(
            current_inputs
        )
    )
    publication_matches = True
    if "matches_saved_inputs" in calculation:
        publication_matches = calculation.get("matches_saved_inputs") is True
    record = {
        key: calculation.get(key)
        for key in _CALCULATION_PROVENANCE_FIELDS
        if calculation.get(key) not in (None, "")
    }
    interaction_record_required = bool(
        current_inputs.get("crack_interaction_on") is True
        or current_inputs.get("shear_interaction_on") is True
    )
    if "multidirectional_interaction" in calculation:
        record["multidirectional_interaction"] = (
            multidirectional.publication_safe_interaction_record(
                calculation.get("multidirectional_interaction"),
                current_inputs=current_inputs,
                current_results=(
                    calculation_results
                    if isinstance(calculation_results, Mapping)
                    else None
                ),
            )
        )
        interaction_validation = (
            (record.get("multidirectional_interaction") or {}).get(
                "publication_validation"
            )
        )
        publication_matches = (
            publication_matches
            and isinstance(interaction_validation, Mapping)
            and interaction_validation.get("status") == "ACCEPTED"
        )
        if record["multidirectional_interaction"] is None:
            record.pop("multidirectional_interaction")
            publication_matches = False
    elif interaction_record_required:
        publication_matches = False
    if "crack_control" in calculation:
        raw_crack_control = calculation.get("crack_control")
        unexpected_crack_issues = []
        if expected_crack_numerical_method is None:
            if sls.danish_bridge_crack_route_selected(current_inputs):
                unexpected_crack_issues.append(
                    "Stored Danish bridge crack evidence exists although "
                    "current inputs do not request crack-width calculation."
                )
            elif (
                isinstance(raw_crack_control, Mapping)
                and raw_crack_control.get("numerical_method") is not None
            ):
                unexpected_crack_issues.append(
                    "Stored Danish bridge crack numerical-method evidence is "
                    "not applicable to the current methodology, code, and "
                    "edition."
                )
        record["crack_control"] = sls.publication_safe_crack_control_record(
            raw_crack_control,
            expected_numerical_method=(
                expected_crack_numerical_method
            ),
            additional_validation_issues=unexpected_crack_issues,
        )
        if record["crack_control"] is None:
            record.pop("crack_control")
            publication_matches = False
        elif (
            expected_crack_numerical_method is not None
            or unexpected_crack_issues
        ):
            crack_validation = record["crack_control"].get(
                "publication_validation"
            )
            publication_matches = (
                publication_matches
                and isinstance(crack_validation, Mapping)
                and crack_validation.get("status") == "ACCEPTED"
            )
    if "fatigue_conformance" in calculation:
        record["fatigue_conformance"] = (
            fatigue_analysis.publication_safe_conformance_record(
                calculation.get("fatigue_conformance"),
                design_methodology=design_methodology,
                current_basis=current_inputs.get(fatigue_inputs.BASIS_KEY),
            )
        )
        if record["fatigue_conformance"] is None:
            record.pop("fatigue_conformance")
            publication_matches = False
    if "bridge_methodology" in calculation:
        import bridge_analysis

        record["bridge_methodology"] = bridge.publication_safe_record(
            calculation.get("bridge_methodology"),
            design_methodology=design_methodology,
            fatigue_context=fatigue_context,
            danish_basis_context=bridge_inputs.danish_basis_context(
                current_inputs
            ),
            danish_fck_mpa=bridge_inputs.danish_fck_mpa(current_inputs),
            danish_crack_context=(
                bridge_analysis.danish_crack_publication_context(
                    current_inputs,
                    crack_control_record=record.get("crack_control"),
                )
            ),
        )
        if record["bridge_methodology"] is None:
            record.pop("bridge_methodology")
            publication_matches = False
        else:
            publication_matches = (
                publication_matches
                and _bridge_publication_matches_inputs(
                    record["bridge_methodology"]
                )
            )
    record["matches_saved_inputs"] = (
        bool(record.get("input_sha256"))
        and record.get("input_sha256") == input_digest
        and publication_matches
    )
    return record


def dump_project(tables: dict, scalars: dict, *, calculation=None,
                 app_version=None, revision=None) -> str:
    """Serialise the point tables and scalar inputs to a JSON project string.

    ``tables`` maps the table keys to DataFrames; ``scalars`` maps the input keys
    to their values. Unknown scalar keys are dropped so the file stays canonical.
    """
    _validate_project_geometry(tables)
    content = _canonical_inputs(tables, scalars)
    digest = input_sha256(tables, scalars)
    revision = str(revision or source_revision())
    app_version = str(app_version or sector_version)
    payload = {
        "format": FORMAT,
        "version": VERSION,
        **content,
        "provenance": {
            "sector_version": app_version,
            "source_revision": revision,
            "saved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "input_sha256": digest,
            "results_included": False,
        },
    }
    if calculation:
        publication_inputs = dict(content["scalars"])
        publication_inputs.update(content.get("tables") or {})
        publication_inputs["load_cases"] = (
            content.get("load_cases") or {}
        )
        publication_inputs.update(
            _bridge_tables_from_payload(content.get("bridge"))
        )
        record = publication_safe_calculation_record(
            calculation,
            calculation_inputs=publication_inputs,
            input_digest=digest,
        )
        payload["calculation"] = record
        payload["provenance"]["results_included"] = bool(
            (record.get("crack_control") or {}).get("cases")
            or record.get("multidirectional_interaction")
            or record.get("fatigue_conformance")
            or record.get("bridge_methodology")
        )
    return json.dumps(payload, indent=2)


def project_provenance(text: str) -> dict:
    """Read and verify provenance without changing the parse return contract."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("not valid JSON") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("not a Sector project file")
    raw_scalars = data.get("scalars") or {}
    if not isinstance(raw_scalars, dict):
        raise ValueError("malformed 'tables' or 'scalars' section")
    _reject_unsupported_strut_settings(raw_scalars)
    _validate_factor_scalars(raw_scalars)
    _validate_crack_numeric_scalars(raw_scalars)
    _validate_multidirectional_scalars(
        raw_scalars,
        project_version=int(data.get("version", 1)),
    )
    _validate_bridge_scalars(raw_scalars)
    _validate_fatigue_miner_scalars(raw_scalars, allow_missing=True)
    provenance = data.get("provenance")
    if not isinstance(provenance, dict):
        return {
            "sector_version": None,
            "source_revision": None,
            "saved_at_utc": None,
            "input_sha256": None,
            "input_hash_valid": None,
            "results_included": False,
            "calculation": None,
        }
    raw_tables = data.get("tables") or {}
    raw_load_cases = data.get("load_cases")
    raw_fatigue = data.get("fatigue")
    raw_bridge = data.get("bridge")
    if not isinstance(raw_tables, dict):
        raise ValueError("malformed 'tables' or 'scalars' section")
    if raw_load_cases is not None and not isinstance(raw_load_cases, dict):
        raise ValueError("malformed 'load_cases' section")
    if raw_fatigue is not None and not isinstance(raw_fatigue, dict):
        raise ValueError("malformed 'fatigue' section")
    if raw_bridge is not None and not isinstance(raw_bridge, dict):
        raise ValueError("malformed 'bridge' section")
    bridge_tables = _bridge_tables_from_payload(raw_bridge)
    canonical_inputs = {"tables": raw_tables, "scalars": raw_scalars}
    if raw_load_cases is not None:
        canonical_inputs["load_cases"] = raw_load_cases
    if raw_fatigue is not None:
        canonical_inputs["fatigue"] = raw_fatigue
    if raw_bridge is not None:
        canonical_inputs["bridge"] = raw_bridge
    canonical = json.dumps(
        canonical_inputs,
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    )
    actual = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    recorded = provenance.get("input_sha256")
    calculation = publication_safe_calculation_record(
        data.get("calculation"),
        calculation_inputs={
            **raw_scalars,
            **raw_tables,
            "load_cases": raw_load_cases or {},
            **bridge_tables,
        },
        input_digest=actual,
    )
    return {
        "sector_version": provenance.get("sector_version"),
        "source_revision": provenance.get("source_revision"),
        "saved_at_utc": provenance.get("saved_at_utc"),
        "input_sha256": recorded,
        "input_hash_valid": bool(recorded) and recorded == actual,
        "results_included": bool(
            (
                (calculation or {}).get("crack_control")
                or {}
            ).get("cases")
            or (calculation or {}).get("multidirectional_interaction")
            or (calculation or {}).get("fatigue_conformance")
            or (calculation or {}).get("bridge_methodology")
        ),
        "calculation": calculation,
    }


def parse_project(text: str):
    """Read a project string into ``(tables, scalars)``.

    Raises :class:`ValueError` if the text is not a Sector project file (wrong
    format tag or unparseable JSON), so the caller can show a friendly message.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("not valid JSON") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("not a Sector project file")
    raw_tables = data.get("tables") or {}
    raw_load_cases = data.get("load_cases")
    raw_fatigue = data.get("fatigue")
    raw_bridge = data.get("bridge")
    raw_scalars = data.get("scalars") or {}
    if not isinstance(raw_tables, dict) or not isinstance(raw_scalars, dict):
        raise ValueError("malformed 'tables' or 'scalars' section")
    _reject_unsupported_strut_settings(raw_scalars)
    _validate_factor_scalars(raw_scalars)
    _validate_crack_numeric_scalars(raw_scalars)
    _validate_multidirectional_scalars(
        raw_scalars,
        project_version=int(data.get("version", 1)),
    )
    _validate_bridge_scalars(raw_scalars)
    _validate_fatigue_miner_scalars(raw_scalars, allow_missing=True)
    if raw_load_cases is not None and not isinstance(raw_load_cases, dict):
        raise ValueError("malformed 'load_cases' section")
    if raw_fatigue is not None and not isinstance(raw_fatigue, dict):
        raise ValueError("malformed 'fatigue' section")
    if raw_bridge is not None and not isinstance(raw_bridge, dict):
        raise ValueError("malformed 'bridge' section")
    tables = {
        k: _obj_to_table(raw_tables[k], k)
        for k in TABLE_KEYS if k in raw_tables
    }
    scalars = {k: v for k, v in raw_scalars.items() if k in SCALAR_KEYS}
    interaction_defaults = {
        **multidirectional.crack_configuration({}),
        **multidirectional.shear_configuration({}),
    }
    if data.get("version", 1) < VERSION:
        # Legacy projects have no interaction authority. Migrate to explicit
        # opt-out state without synthesising a source, approval, or domain.
        scalars.update(interaction_defaults)
    else:
        for key, value in interaction_defaults.items():
            scalars.setdefault(key, value)
    if raw_load_cases is not None:
        plastic_records = raw_load_cases.get("plastic", [])
        if data.get("version", 1) < 7:
            plastic_records = load_cases.migrate_legacy_plastic_records(
                plastic_records,
                axis=raw_scalars.get("shear_axis"),
                tension=raw_scalars.get("shear_tension"),
            )
        case_tables = {
            table_key: load_cases.table_from_records(
                (
                    plastic_records
                    if table_key == load_cases.PLASTIC_TABLE_KEY
                    else raw_load_cases.get(payload_key, [])
                ),
                table_key,
            )
            for table_key, payload_key in _CASE_PAYLOAD_KEYS.items()
        }
    if raw_fatigue is not None:
        tables[fatigue_inputs.SPECTRUM_TABLE_KEY] = (
            fatigue_inputs.spectrum_from_records(
                raw_fatigue.get("spectrum", [])
            )
        )
    tables.update(_bridge_tables_from_payload(raw_bridge))
    # Files saved before the explicit EN 1992-1-1:2023 applicability selector have
    # no k_tc field. Migrate those deterministically to the general/other-case value
    # instead of letting an unrelated preset value already in session state leak
    # into the loaded calculation.
    if "2023" in str(scalars.get("conc_preset", "")):
        scalars.setdefault("conc_k_tc", 0.85)
    # The steel moduli are now entered in GPa; files written before that stored them
    # in MPa. A real modulus in GPa is at most a few hundred, so a value of 1000 or
    # more is unambiguously a legacy MPa figure -- rescale it so old projects load
    # correctly. (New files store GPa, well below the threshold, so re-loading them
    # is a no-op.)
    for key in ("mild_Es", "pre_Es"):
        val = scalars.get(key)
        if isinstance(val, (int, float)) and val >= 1000.0:
            scalars[key] = val / 1000.0
    # Migrate either explicit v6 catalogues or the former one-material flat
    # inputs. A deliberately partial project with no material data stays partial;
    # the UI seeds its normal defaults independently.
    for kind, legacy_keys in (
        ("mild", material_catalog.LEGACY_MILD_KEYS),
        ("prestress", material_catalog.LEGACY_PRESTRESS_KEYS),
    ):
        key = material_catalog.catalog_key(kind)
        if key in scalars:
            scalars[key] = material_catalog.normalise_catalog(scalars[key], kind)
        elif any(legacy in raw_scalars for legacy in legacy_keys):
            scalars[key] = material_catalog.from_legacy_scalars(scalars, kind)
        if key in scalars:
            for legacy in legacy_keys:
                scalars.pop(legacy, None)
    if fatigue_inputs.DETAIL_CATALOG_KEY in scalars:
        if not isinstance(
            scalars[fatigue_inputs.DETAIL_CATALOG_KEY], dict
        ):
            raise ValueError(
                "fatigue detail catalogue must be an object with a "
                "non-empty items list"
            )
        scalars[fatigue_inputs.DETAIL_CATALOG_KEY] = (
            fatigue_inputs.normalise_catalog(
                scalars[fatigue_inputs.DETAIL_CATALOG_KEY]
            )
        )
    if fatigue_inputs.BASIS_KEY in scalars:
        if not isinstance(scalars[fatigue_inputs.BASIS_KEY], dict):
            raise ValueError("fatigue basis must be an object")
        normalise_current_basis = (
            fatigue_inputs.canonical_basis
            if data.get("version", 1) >= VERSION
            else fatigue_inputs.normalise_basis
        )
        scalars[fatigue_inputs.BASIS_KEY] = normalise_current_basis(
            scalars[fatigue_inputs.BASIS_KEY]
        )
    elif (
        data.get("version", 1) >= VERSION
        and bool(scalars.get("fatigue_on"))
    ):
        raise ValueError("fatigue basis is required when fatigue is enabled")
    elif (
        bool(scalars.get("fatigue_on"))
        or "fatigue_source" in raw_scalars
        or (
            data.get("version", 1) < 10
            and raw_fatigue is not None
        )
    ):
        # Older fatigue projects contained the numerical spectrum but no explicit
        # authority provenance.  Seed a neutral, visibly incomplete basis; never
        # infer a traffic model or modifiers from the action rows.
        basis = fatigue_inputs.default_basis()
        basis["spectrum_source"] = str(
            raw_scalars.get("fatigue_source") or ""
        ).strip()
        scalars[fatigue_inputs.BASIS_KEY] = basis
    if fatigue_inputs.BASIS_KEY in scalars:
        scalars.pop("fatigue_source", None)
    # Material IDs already existed as traceability fields in v5, although every
    # element still used one global law. Clone that law under each valid referenced
    # ID so old calculations remain runnable and numerically unchanged in v6.
    if data.get("version", 1) < 6:
        for kind, table_key in (("mild", "bars_base"),
                                ("prestress", "tendons_base")):
            key = material_catalog.catalog_key(kind)
            table = tables.get(table_key)
            if (
                key not in scalars
                or table is None
                or rebar_table.MATERIAL_ID not in table
            ):
                continue
            scalars[key] = material_catalog.materialise_legacy_assignments(
                scalars[key], kind,
                [rebar_table.text_cell(value)
                 for value in table[rebar_table.MATERIAL_ID].tolist()],
            )
    if material_catalog.MILD_CATALOG_KEY in scalars:
        available = material_catalog.material_ids(
            scalars[material_catalog.MILD_CATALOG_KEY], "mild"
        )
        if scalars.get("capacity_steel_material_id") not in available:
            scalars["capacity_steel_material_id"] = available[0]
    # v7 replaces the former global direction, face, web-width override and link
    # leg count. Preserve the configured historical direction exactly; the other
    # direction is written explicitly with the app defaults so loading into a
    # reused Streamlit session cannot retain values from the previous project.
    if data.get("version", 1) < 7:
        for direction in ("vx", "vy"):
            scalars.setdefault(f"shear_{direction}_bw", 0.0)
            scalars.setdefault(f"shear_{direction}_link_legs", 2.0)
        component = load_cases.legacy_shear_component(
            raw_scalars.get("shear_axis")
        )
        old_bw = raw_scalars.get("shear_bw")
        if isinstance(old_bw, (int, float)):
            scalars[f"shear_{component}_bw"] = float(old_bw)
        old_legs = raw_scalars.get("shear_link_legs")
        if isinstance(old_legs, (int, float)):
            scalars[f"shear_{component}_link_legs"] = float(old_legs)
    # v8 introduces detailing settings and a per-row minimum-reinforcement flag.
    # Write every new scalar explicitly when loading an older file so a reused
    # Streamlit session cannot leak checks or parameters from the previous project.
    if data.get("version", 1) < 8:
        scalars.setdefault("minimum_reinforcement_on", False)
        scalars.setdefault("clear_spacing_on", False)
        scalars.setdefault("detailing_edition", detailing.EC2_2005_DKNA)
        scalars.setdefault("detailing_d_upper", 16.0)
        scalars.setdefault("detailing_include_tendons", False)
    # v13 adds transverse-link detailing.  Write every new value explicitly so
    # loading an older/partial development file in a reused Streamlit session
    # cannot inherit the previous project's enabled check or geometry.
    if data.get("version", 1) < 13:
        scalars.setdefault("transverse_detailing_on", False)
        scalars.setdefault("shear_vx_transverse_leg_spacing", 0.0)
        scalars.setdefault("shear_vy_transverse_leg_spacing", 0.0)
        scalars.setdefault("transverse_ductility_class", "B")
        scalars.setdefault("transverse_apply_ductility_reduction", False)
    if data.get("version", 1) < 14:
        scalars.setdefault("detailing_member_type", detailing.MEMBER_BEAM)
        scalars.setdefault("detailing_cut_direction", detailing.CUT_TRANSVERSE)
    # v15 separates the torsional tensile factor from the concrete compression
    # factor and records fatigue-factor derivations. Old fatigue numbers are
    # retained but require an explicit engineer decision; they are never silently
    # relabelled as the new edition preset or an approved override.
    if data.get("version", 1) < 15:
        torsion_method = str(
            (
                raw_scalars.get("combined_method")
                if raw_scalars.get("combined_on")
                else raw_scalars.get("torsion_method")
            )
            or codes.EC2_2005_DKNA.label
        )
        torsion_code = {
            code.label: code
            for code in (codes.EC2_2005, codes.EC2_2005_DKNA)
        }.get(torsion_method, codes.EC2_2005_DKNA)
        scalars.setdefault("torsion_factor_mode", codes.FACTOR_MODE_PRESET)
        scalars.setdefault("torsion_gamma0", 1.0)
        scalars.setdefault("torsion_gamma3", 1.0)
        scalars.setdefault(
            "torsion_gamma_ct",
            torsion_code.material_factor_basis()["tension_final"],
        )
        scalars.setdefault("torsion_factor_approval", "")

        scalars.setdefault("fatigue_gamma0", 1.0)
        scalars.setdefault("fatigue_gamma3", 1.0)
        scalars.setdefault("fatigue_factor_approval", "")
        has_legacy_fatigue_factors = any(
            isinstance(raw_scalars.get(key), (int, float))
            for key in ("fatigue_gamma_s", "fatigue_gamma_c")
        )
        scalars.setdefault(
            "fatigue_factor_mode",
            (
                fatigue_inputs.FACTOR_MODE_LEGACY
                if has_legacy_fatigue_factors
                else fatigue_inputs.FACTOR_MODE_PRESET
            ),
        )
    # v16 makes the prestressing bond condition and xi input explicit for the
    # 2023 effective reinforcement ratio.  Default absent keys for every input
    # version, including partial v16 files produced by external callers.  The
    # conservative poor-bond choice and blocking zero xi prevent a reused UI
    # session from silently turning an incomplete mixed-reinforcement check into
    # a calculated result.
    scalars.setdefault("sls_tendon_bond", DEFAULT_SLS_TENDON_BOND)
    scalars.setdefault("sls_tendon_xi", DEFAULT_SLS_TENDON_XI)
    # v17 separates response duration from SLS-combination class and records
    # criterion source/applicability. Older or partial files retain their former
    # numerical limit only as evidence and require an explicit engineer decision.
    if (
        data.get("version", 1) < 17
        or "sls_criterion_mode" not in raw_scalars
    ):
        scalars["sls_criterion_mode"] = DEFAULT_SLS_CRITERION_MODE
    scalars.setdefault(
        "sls_prestress_class", DEFAULT_SLS_PRESTRESS_CLASS
    )
    scalars.setdefault(
        "sls_protection_class", DEFAULT_SLS_PROTECTION_CLASS
    )
    scalars.setdefault("sls_exposure_class", DEFAULT_SLS_EXPOSURE_CLASS)
    scalars.setdefault(
        "sls_bridge_exposure_class",
        DEFAULT_SLS_BRIDGE_EXPOSURE_CLASS,
    )
    scalars.setdefault("sls_exposure_context", "")
    scalars.setdefault("sls_check_appearance", False)
    scalars.setdefault("sls_appearance_limit", 0.0)
    scalars.setdefault("sls_check_durability", False)
    scalars.setdefault(
        "sls_decompression_applicability", DEFAULT_SLS_DECOMPRESSION
    )
    scalars.setdefault("sls_project_characteristic_limit", 0.0)
    scalars.setdefault("sls_project_frequent_limit", 0.0)
    scalars.setdefault("sls_project_quasi_permanent_limit", 0.0)
    # v19 introduces a whole-calculation bridge methodology. Earlier projects
    # remain independent component calculations; they are never silently
    # relabelled as EN 1992-2. A selected current bridge method with absent table
    # rows receives the canonical blocking defaults from the dedicated payload.
    if (
        data.get("version", 1) < 19
        or "design_methodology" not in raw_scalars
    ):
        scalars["design_methodology"] = bridge.COMPONENT_METHODS
    scalars.setdefault(
        "bridge_brittle_method",
        bridge.BRITTLE_NOT_ESTABLISHED,
    )
    scalars.setdefault("bridge_expected_box_walls", 0)
    scalars.setdefault(
        "bridge_minimum_scope",
        bridge.MINIMUM_SCOPE_NOT_ESTABLISHED,
    )
    scalars.setdefault(
        "bridge_shear_scope",
        bridge.SHEAR_SCOPE_NOT_ESTABLISHED,
    )
    scalars.setdefault(
        "bridge_exposure",
        bridge.BRIDGE_EXPOSURE_NOT_ESTABLISHED,
    )
    _setdefault_danish_bridge_scalars(scalars)
    _validate_bridge_scalars(scalars)
    # A current-version file may still be partial or hand-edited. Never let an
    # unknown routing token fall through the Streamlit selectbox to its fresh-
    # project default, because that could silently turn ambiguous legacy evidence
    # into a standard-derived ordinary-reinforced assessment.
    criterion_mode = scalars.get("sls_criterion_mode")
    prestress_class = scalars.get("sls_prestress_class")
    protection_class = scalars.get("sls_protection_class")
    exposure_class = scalars.get("sls_exposure_class")
    edition_2023 = "2023" in str(scalars.get("sls_code") or "")
    # A v17 2023 bonded project cannot distinguish Table 9.2 Protection Level 1
    # from Levels 2/3, and a v17 2023 reinforced/unbonded file has only free
    # exposure text, not a controlled Table 9.2 row. Preserve its numeric evidence
    # but require an explicit current-schema routing decision. The already
    # structured 2004 route does not depend on either new field and remains valid.
    if (
        data.get("version", 1) < 18
        and criterion_mode == sls.CRITERION_MODE_STANDARD
        and edition_2023
    ):
        scalars["sls_criterion_mode"] = DEFAULT_SLS_CRITERION_MODE
        criterion_mode = DEFAULT_SLS_CRITERION_MODE
    if criterion_mode not in sls.CRITERION_MODES:
        scalars["sls_criterion_mode"] = DEFAULT_SLS_CRITERION_MODE
    if prestress_class not in sls.PRESTRESS_CLASSES:
        scalars["sls_prestress_class"] = DEFAULT_SLS_PRESTRESS_CLASS
        if criterion_mode == sls.CRITERION_MODE_STANDARD:
            scalars["sls_criterion_mode"] = DEFAULT_SLS_CRITERION_MODE
    if protection_class not in sls.PROTECTION_CLASSES:
        scalars["sls_protection_class"] = DEFAULT_SLS_PROTECTION_CLASS
        if (
            criterion_mode == sls.CRITERION_MODE_STANDARD
            and edition_2023
            and prestress_class == sls.PRESTRESS_BONDED
        ):
            scalars["sls_criterion_mode"] = DEFAULT_SLS_CRITERION_MODE
    if exposure_class not in sls.EXPOSURE_CLASSES_2023:
        scalars["sls_exposure_class"] = DEFAULT_SLS_EXPOSURE_CLASS
        if (
            criterion_mode == sls.CRITERION_MODE_STANDARD
            and edition_2023
        ):
            scalars["sls_criterion_mode"] = DEFAULT_SLS_CRITERION_MODE
    if (
        scalars.get("sls_decompression_applicability")
        not in sls.DECOMPRESSION_OPTIONS
    ):
        # "Not established" remains blocking for bonded prestress, while the
        # field is immaterial for reinforced/unbonded and project criteria.
        scalars["sls_decompression_applicability"] = DEFAULT_SLS_DECOMPRESSION
    if (
        bool(scalars.get("fatigue_on"))
        or "fatigue_factor_mode" in scalars
        or "fatigue_gamma_s" in scalars
        or "fatigue_gamma_c" in scalars
    ):
        # Early v15 development files predate the dedicated factor-approval
        # field. Never promote the spectrum-method approval to this role.
        scalars.setdefault("fatigue_factor_approval", "")
        scalars.setdefault(
            "fatigue_concrete_method",
            fatigue_analysis.CONCRETE_MINER,
        )
        if (
            scalars["fatigue_concrete_method"]
            in fatigue_analysis.CONCRETE_MINER_METHODS
        ):
            scalars.setdefault(
                "fatigue_concrete_c",
                fatigue_inputs.STANDARD_CONCRETE_MINER_C,
            )
        scalars.setdefault(
            "fatigue_concrete_miner_basis",
            _default_fatigue_miner_basis(scalars),
        )
        _normalise_fatigue_miner_basis(scalars)
        scalars.setdefault("fatigue_concrete_miner_source", "")
        if (
            scalars["fatigue_concrete_miner_basis"]
            not in fatigue_inputs.MINER_BASES
        ):
            raise ValueError("unknown concrete fatigue Miner applicability")
    if (
        "torsion_factor_mode" in scalars
        and scalars["torsion_factor_mode"] not in codes.FACTOR_MODES
    ):
        raise ValueError("unknown torsion material-factor source")
    if (
        "fatigue_factor_mode" in scalars
        and scalars["fatigue_factor_mode"] not in fatigue_inputs.FACTOR_MODES
    ):
        raise ValueError("unknown fatigue material-factor source")
    if (
        "fatigue_concrete_miner_basis" in scalars
        and scalars["fatigue_concrete_miner_basis"]
        not in fatigue_inputs.MINER_BASES
    ):
        raise ValueError("unknown concrete fatigue Miner applicability")
    if (
        raw_scalars.get("fatigue_check_concrete") is True
        or {
            "fatigue_concrete_method",
            "fatigue_concrete_c",
            "fatigue_concrete_miner_basis",
            "fatigue_concrete_miner_source",
        }.intersection(raw_scalars)
    ):
        _validate_fatigue_miner_scalars(scalars)
    # The axial force N is now tension-positive; files written before that (version
    # < 2) stored it compression-positive, so negate their axial values to preserve
    # the physical loads. Moments are unchanged.
    if data.get("version", 1) < 2:
        for key in ("pl_P", "el_long_P", "el_short_P"):
            val = scalars.get(key)
            if isinstance(val, (int, float)):
                scalars[key] = -val
    # Quick Section rebar rework (v0.42): the interleave diameters became numeric
    # (0 = off; previously "none" or a string diameter), and the single cover split
    # into a separate top and bottom cover.
    for key in ("qsv_bot_off_d", "qsv_top_off_d"):
        val = scalars.get(key)
        if isinstance(val, str):
            scalars[key] = 0.0 if val == "none" else float(val)
    old_cover = raw_scalars.get("qsv_cover_mm")      # single cover -> both faces
    if isinstance(old_cover, (int, float)):
        scalars.setdefault("qsv_bot_c_mm", float(old_cover))
        scalars.setdefault("qsv_top_c_mm", float(old_cover))
    # v0.48 merged the separate torsion stirrup (torsion_stirrup_dia/_s, torsion_fywk)
    # into the shared shear_link_* stirrup. Fold a deliberately-configured legacy
    # torsion stirrup into the shared keys, so a project that used torsion keeps its
    # stirrup. Conditions:
    #   * shear links are not active -- both shear_on and shear_links set means the
    #     shear stirrup is the real one and is kept (two stirrups cannot both survive);
    #     shear_links alone can be stale after shear_on was turned off;
    #   * the torsion stirrup was actually customised (differs from the app defaults)
    #     -- so a dormant default torsion stirrup never overwrites a custom shear one,
    #     and the migration also fires when the torsion check was toggled off before
    #     saving (its custom stirrup would otherwise be lost on re-enable).
    _shear_active = bool(raw_scalars.get("shear_on") and raw_scalars.get("shear_links"))
    _legacy_stirrup = (("torsion_stirrup_dia", "shear_link_dia", 10.0),
                       ("torsion_stirrup_s", "shear_link_s", 150.0),
                       ("torsion_fywk", "shear_fywk", 500.0))
    _customised = any(isinstance(raw_scalars.get(old), (int, float))
                      and raw_scalars[old] != dflt
                      for old, _new, dflt in _legacy_stirrup)
    if _customised and not _shear_active:
        for old, new, _dflt in _legacy_stirrup:
            val = raw_scalars.get(old)
            if isinstance(val, (int, float)):
                scalars[new] = float(val)

    if raw_load_cases is None:
        if (
            data.get("version", 1) >= 4
            and not any(
                key in raw_scalars for key in load_cases.LEGACY_SCALAR_KEYS
            )
        ):
            # A partial v4 project may intentionally carry no load data. Preserve
            # that absence so parsing and re-saving cannot invent default cases or
            # change the recorded input hash. The mounted UI supplies its normal
            # widget defaults independently when such a partial file is applied.
            case_tables = {}
        else:
            # Build migrated rows only after every historical scalar migration,
            # especially the pre-v2 axial-force sign conversion above.
            legacy_scalars = dict(scalars)
            if data.get("version", 1) < 7:
                legacy_scalars.setdefault(
                    "shear_tension", load_cases.FACE_NEGATIVE
                )
            case_tables = load_cases.tables_from_legacy_scalars(legacy_scalars)
    tables.update(case_tables)
    _validate_project_geometry(tables)
    return tables, scalars
