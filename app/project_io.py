"""Current-schema project persistence for Sector.

Project files contain the geometry, reinforcement, actions, numerical
coefficients and direct method choices needed to reproduce a calculation.
Released Sector 0.94 projects used schema 25. Sector 0.95 used schema 26 to
separate long-term, short-term and heightened permitted crack-width inputs.
Schema 27 persists the user-selected DS/EN 1992-1-1:2023 shear partial factor.
Schemas 25 and 26 have bounded in-memory migrations; schema 24 and future
schemas remain unsupported. Retired component-mapped bridge inputs are
deliberately absent from the schema.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

import fatigue_inputs
import load_cases
import material_catalog
import numpy as np
import pandas as pd
import reinforcement_table as rebar_table

from app import modelled_direction, report_profiles
from app import heightened_crack_adapter
from app.table_field_definitions import (
    decimal_issue_ledger,
)
from sector import __version__ as sector_version
from sector import (
    capacity,
    codes,
    design_standards,
    geometry,
    heightened_crack_control,
)
from sector.build_info import source_revision
from sector.sls_identity import (
    HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY,
    LONG_TERM_PERMITTED_CRACK_WIDTH_KEY,
    SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY,
)

FORMAT = "sector-project"
VERSION = 27
MIGRATABLE_VERSION = 26
LEGACY_MIGRATABLE_VERSION = 25
MIGRATABLE_VERSIONS = (
    LEGACY_MIGRATABLE_VERSION,
    MIGRATABLE_VERSION,
)

LEGACY_SHARED_CRACK_WIDTH_KEY = "sls_permitted_crack_width_mm"

TABLE_KEYS = ["corners_base", "hole_base", "bars_base", "tendons_base"]
REINFORCEMENT_TABLE_KEYS = {"bars_base": "bar", "tendons_base": "tendon"}
CASE_TABLE_KEYS = list(load_cases.CASE_TABLE_KEYS)
FATIGUE_TABLE_KEYS = [fatigue_inputs.SPECTRUM_TABLE_KEY]
PROJECT_TABLE_KEYS = TABLE_KEYS + CASE_TABLE_KEYS + FATIGUE_TABLE_KEYS

FATIGUE_SCALAR_KEYS = (
    fatigue_inputs.DETAIL_CATALOG_KEY,
    fatigue_inputs.BASIS_KEY,
    "fatigue_on",
    "fatigue_edition",
    "fatigue_check_steel",
    "fatigue_check_concrete",
    "fatigue_concrete_method",
    "fatigue_gamma_c",
    "fatigue_gamma_s",
    "fatigue_gamma_ff",
    "fatigue_beta_cc_t0",
    "fatigue_t0_days",
    "fatigue_concrete_k1",
    "fatigue_concrete_c",
)

HEIGHTENED_CRACK_SCALAR_KEYS = (
    "sls_heightened_on",
    "sls_heightened_reference_case",
    "sls_heightened_reinforcement_surface",
    "sls_heightened_effective_tensile_strength_mpa",
    "sls_heightened_fine_effective_tension_area_mm2",
    "sls_heightened_coarse_effective_tension_area_mm2",
    HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY,
)

_HEIGHTENED_POSITIVE_OPERAND_KEYS = (
    "sls_heightened_effective_tensile_strength_mpa",
    "sls_heightened_fine_effective_tension_area_mm2",
    "sls_heightened_coarse_effective_tension_area_mm2",
    HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY,
)

LEGACY_HEIGHTENED_OPERAND_KEYS = {
    "sls_heightened_crack_system",
    "sls_heightened_bar_diameter_mm",
    "sls_heightened_reinforcement_modulus_mpa",
    "sls_heightened_effective_tension_area_mm2",
    "sls_heightened_provided_reinforcement_area_mm2",
}


QUICK_SECTION_SCALAR_KEYS = (
    "qsv_shape", "qsv_b_mm", "qsv_h_mm", "qsv_bf_mm", "qsv_hf_mm",
    "qsv_bw_mm", "qsv_hw_mm", "qsv_wall_mm", "qsv_dia_mm",
    "qsv_t_orientation",
    "qsv_trap_bottom_mm", "qsv_trap_top_mm", "qsv_trap_h_mm",
    "qsv_l_b_mm", "qsv_l_h_mm", "qsv_l_web_mm", "qsv_l_flange_mm",
    "qsv_i_bf_mm", "qsv_i_tf_mm", "qsv_i_bw_mm", "qsv_i_hw_mm",
    "qsv_u_b_mm", "qsv_u_h_mm", "qsv_u_web_mm", "qsv_u_base_mm",
    "qsv_annulus_outer_mm", "qsv_annulus_inner_mm",
    "qsv_ring_n", "qsv_ring_d", "qsv_ring_c_mm", "qsv_qs_rebar_mode",
    "qsv_qs_cover_to_edge", "qsv_bot_n", "qsv_bot_d", "qsv_bot_s",
    "qsv_top_n", "qsv_top_d", "qsv_top_s", "qsv_bot_c_mm",
    "qsv_top_c_mm", "qsv_bot_n2", "qsv_top_n2", "qsv_bot_layers",
    "qsv_top_layers", "qsv_layer_s", "qsv_bot_off_d", "qsv_top_off_d",
    "qsv_tnd_n", "qsv_tnd_a", "qsv_tnd_c_mm", "qsv_tnd_layers",
    "qsv_tnd_layer_s",
)


# Current UI/session inputs only. Deprecated compliance, authority, cover-
# calculator, multidirectional-interaction and SLS-limit fields are absent.
SCALAR_KEYS = [
    # Quick Section settings. The generated point tables remain authoritative.
    *QUICK_SECTION_SCALAR_KEYS,
    # Concrete and material catalogues.
    "conc_preset", "conc_fck", "conc_gamma_c", "conc_k_tc",
    "conc_alpha_cc", "conc_eps_c2", "conc_eps_cu2", "conc_n",
    "conc_Ec", "sls_fctm",
    material_catalog.MILD_CATALOG_KEY,
    material_catalog.PRESTRESS_CATALOG_KEY,
    fatigue_inputs.DETAIL_CATALOG_KEY,
    fatigue_inputs.BASIS_KEY,
    # Live material-panel state.
    "mild_preset", "mild_active_comp", "mild_fytk", "mild_fyck",
    "mild_futk", "mild_eut", "mild_gamma_y", "mild_gamma_u",
    "mild_gamma_E", "mild_k", "mild_ey0t", "mild_ey0c", "mild_Es",
    "pre_preset", "pre_IS", "pre_fytk", "pre_futk", "pre_eut",
    "pre_gamma_y", "pre_gamma_u", "pre_gamma_E", "pre_k",
    "pre_ey0t", "pre_Es",
    # Analysis and numerical method choices.
    "mode", "v_min", "v_max", "v_inc", "pl_check_util",
    "pl_interaction", "el_phi",
    "sls_cw", "sls_phi", "sls_bond", "sls_tendon_xi",
    "sls_code", "sls_member", LONG_TERM_PERMITTED_CRACK_WIDTH_KEY,
    SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY,
    *HEIGHTENED_CRACK_SCALAR_KEYS,
    # Fatigue.
    "fatigue_on", "fatigue_edition", "fatigue_check_steel",
    "fatigue_check_concrete", "fatigue_concrete_method",
    "fatigue_gamma_c", "fatigue_gamma_s", "fatigue_gamma_ff",
    "fatigue_beta_cc_t0", "fatigue_t0_days", "fatigue_concrete_k1",
    "fatigue_concrete_c",
    # Reinforcement detailing.
    "minimum_reinforcement_on", "transverse_detailing_on",
    "clear_spacing_on", "detailing_edition", "detailing_member_type",
    "detailing_cut_direction", "detailing_d_upper",
    "detailing_include_tendons", "transverse_ductility_class",
    "transverse_apply_ductility_reduction",
    # Independent Vx and Vy shear calculations.
    "shear_on", "shear_method", "shear_Vx", "shear_Vy",
    "shear_face_x", "shear_face_y", "shear_vx_bw", "shear_vy_bw",
    "shear_dlower", "shear_gamma_v", "shear_links", "shear_vx_link_legs",
    "shear_vy_link_legs", "shear_link_dia", "shear_link_s",
    "shear_fywk", "shear_vx_transverse_leg_spacing",
    "shear_vy_transverse_leg_spacing", "strut_cot_min",
    "strut_cot_max",
    # Torsion and combined resistance.
    "torsion_on", "torsion_method", "torsion_T", "torsion_tef",
    "torsion_nu_v", "torsion_gamma_ct", "torsion_subdivide",
    "torsion_nsub", "torsion_sub_x0", "torsion_sub_y0",
    "torsion_sub_x1", "torsion_sub_y1", "torsion_sub_x2",
    "torsion_sub_y2", "torsion_sub_x3", "torsion_sub_y3",
    "torsion_sub_b0", "torsion_sub_h0", "torsion_sub_b1",
    "torsion_sub_h1", "torsion_sub_b2", "torsion_sub_h2",
    "torsion_sub_b3", "torsion_sub_h3", "combined_on",
    "combined_method", "combined_mv_independent",
    "capacity_steel_material_id", "label_scale", "label_min_gap",
    # Project/report metadata. No checker/approver sign-off fields.
    "rep_proj_no", "rep_proj_name", "rep_section", "rep_rev",
    "rep_author", "rep_comments",
    # Local application preferences that are meaningful on restore.
    "autosave_on", "autosave_min",
]

# Project-owned presentation choices that must survive save/load without
# becoming calculation inputs or changing the calculation-input hash.
REPORT_PROFILE_KEY = "rep_report_content"
PRESENTATION_SCALAR_KEYS = (modelled_direction.ALIAS_KEY, REPORT_PROFILE_KEY)
_LEGACY_REPORT_PROFILE_LABELS = {
    "Default report": report_profiles.STANDARD_PROFILE.label,
    "Default report + QA appendix": report_profiles.AUDIT_PROFILE.label,
}

PREV_MARKERS = {
    "conc_prev": "conc_preset",
    "mild_prev": "mild_preset",
    "pre_prev": "pre_preset",
}

_GEOMETRY_COLUMNS = ("x (mm)", "y (mm)")
_POSITIVE_FACTOR_KEYS = {
    "conc_gamma_c",
    "mild_gamma_y",
    "mild_gamma_u",
    "mild_gamma_E",
    "pre_gamma_y",
    "pre_gamma_u",
    "pre_gamma_E",
    "fatigue_gamma_c",
    "fatigue_gamma_s",
    "fatigue_gamma_ff",
    "torsion_gamma_ct",
    "shear_gamma_v",
}


def _json_value(value):
    if hasattr(value, "item"):
        return _json_value(value.item())
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_value(item) for item in value]
    return value


def _cell(value):
    if pd.isna(value):
        return None
    return _json_value(value)


def _positive_real(value, label: str) -> float:
    if isinstance(value, bool) or isinstance(value, str):
        raise ValueError(f"{label} must be a positive finite real number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{label} must be a positive finite real number"
        ) from exc
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{label} must be a positive finite real number")
    return number


def _nonnegative_real(value, label: str) -> float:
    """Normalize one non-negative project scalar without Boolean coercion."""
    if isinstance(value, (bool, np.bool_)) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be a non-negative finite real number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"{label} must be a non-negative finite real number"
        ) from exc
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{label} must be a non-negative finite real number")
    return 0.0 if number == 0.0 else number


def _normalise_table(value, key: str) -> pd.DataFrame:
    if key in CASE_TABLE_KEYS:
        return load_cases.normalise_table(value, key)
    if key == fatigue_inputs.SPECTRUM_TABLE_KEY:
        return fatigue_inputs.normalise_spectrum_table(value)
    kind = REINFORCEMENT_TABLE_KEYS.get(key)
    if kind:
        return rebar_table.normalise_table(value, kind)
    if value is None:
        return pd.DataFrame(columns=list(_GEOMETRY_COLUMNS), dtype="float64")
    frame = (
        value.copy(deep=True)
        if isinstance(value, pd.DataFrame)
        else pd.DataFrame(value)
    )
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.astype("float64") if len(frame.columns) else frame


def _validate_canonical_table(frame: pd.DataFrame, key: str) -> None:
    """Reject a canonical table that cannot round-trip without data loss."""

    issues = decimal_issue_ledger(frame.attrs)
    if issues:
        (row, column), entered = min(issues.items())
        raise ValueError(
            f"{key} row {row + 1}: {column} contains malformed decimal "
            f"input {entered!r}"
        )
    if key in CASE_TABLE_KEYS:
        load_cases.table_records(frame, key)
    elif key == fatigue_inputs.SPECTRUM_TABLE_KEY:
        fatigue_inputs.spectrum_records(frame)


def _table_to_obj(value, key: str) -> dict:
    frame = _normalise_table(value, key)
    _validate_canonical_table(frame, key)
    columns = [str(column) for column in frame.columns]
    rows = [
        [_cell(cell) for cell in row]
        for row in frame.itertuples(index=False, name=None)
    ]
    return {
        "columns": columns,
        "rows": rows,
    }


def _obj_to_table(value, key: str) -> pd.DataFrame:
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} is not a table object")
    columns = value.get("columns")
    rows = value.get("rows")
    if (
        not isinstance(columns, list)
        or not all(isinstance(column, str) for column in columns)
        or not isinstance(rows, list)
    ):
        raise ValueError(f"{key} table columns/rows are malformed")
    if (
        key == load_cases.ELASTIC_TABLE_KEY
        and tuple(columns) != load_cases.ELASTIC_COLUMNS
    ):
        raise ValueError(
            f"{key} table columns do not match current schema {VERSION}; "
            "the exact current Elastic action columns are required"
        )
    try:
        frame = pd.DataFrame(rows, columns=columns)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} table rows are not tabular") from exc
    canonical = _normalise_table(frame, key)
    _validate_canonical_table(canonical, key)
    return canonical


def _geometry_points(frame: pd.DataFrame, label: str) -> list[tuple[float, float]]:
    if not all(column in frame.columns for column in _GEOMETRY_COLUMNS):
        raise ValueError(
            f"{label} table must contain {_GEOMETRY_COLUMNS[0]} and "
            f"{_GEOMETRY_COLUMNS[1]}"
        )
    points = []
    for row_number, (_, row) in enumerate(frame.iterrows(), start=1):
        try:
            point = tuple(
                float(row[column]) / 1000.0
                for column in _GEOMETRY_COLUMNS
            )
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


def _project_holes(frame: pd.DataFrame | None) -> list[list[tuple[float, float]]]:
    if frame is None or frame.empty:
        return []
    if not all(column in frame.columns for column in _GEOMETRY_COLUMNS):
        raise ValueError("hole table has invalid columns")
    holes = []
    current = []
    for row_number, (_, row) in enumerate(frame.iterrows(), start=1):
        values = [row[column] for column in _GEOMETRY_COLUMNS]
        blank = [pd.isna(value) for value in values]
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
            point = tuple(float(value) / 1000.0 for value in values)
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


def _validate_geometry(tables: Mapping) -> None:
    outer_frame = tables.get("corners_base")
    holes = _project_holes(tables.get("hole_base"))
    if outer_frame is None or outer_frame.empty:
        if holes:
            raise ValueError("hole geometry requires a non-empty outer ring")
        return
    outer = _geometry_points(outer_frame, "outer ring")
    try:
        geometry.require_valid_section_topology(outer, holes)
    except geometry.GeometryTopologyError as exc:
        raise ValueError(f"invalid project section geometry: {exc}") from exc


def _assigned_catalog_ids(
    tables: Mapping,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return material/fatigue assignments from all reinforcement rows."""

    bars = rebar_table.normalise_table(tables.get("bars_base"), "bar")
    tendons = rebar_table.normalise_table(
        tables.get("tendons_base"), "tendon"
    )

    def values(frame: pd.DataFrame, column: str) -> tuple[str, ...]:
        return tuple(
            text
            for value in frame[column].tolist()
            if (text := rebar_table.text_cell(value))
        )

    return (
        values(bars, rebar_table.MATERIAL_ID),
        values(tendons, rebar_table.MATERIAL_ID),
        values(bars, rebar_table.FATIGUE_DETAIL_ID),
        values(tendons, rebar_table.FATIGUE_DETAIL_ID),
    )


def _canonical_scalars(
    scalars: Mapping,
    tables: Mapping,
    *,
    migrate_gamma_v: bool = False,
) -> dict:
    payload = {
        key: _json_value(scalars[key])
        for key in SCALAR_KEYS
        if key in scalars
    }
    for key in ("shear_links", "torsion_nu_v"):
        if key not in payload:
            payload[key] = False
        elif type(payload[key]) is not bool:
            raise ValueError(f"{key} must be a Boolean")
    effective_shear_method = (
        payload.get("combined_method")
        if payload.get("combined_on") is True
        else payload.get("shear_method")
    )
    gamma_v_active = (
        payload.get("shear_on") is True
        and effective_shear_method == codes.EC2_2023.label
        and payload.get("shear_links") is not True
    )
    if "shear_gamma_v" not in payload:
        if gamma_v_active and not migrate_gamma_v:
            raise ValueError(
                "shear_gamma_v is required when the DS/EN "
                "1992-1-1:2023 shear calculation is enabled"
            )
        payload["shear_gamma_v"] = float(codes.EC2_2023.shear_gamma_v)
    for key in _POSITIVE_FACTOR_KEYS.intersection(payload):
        payload[key] = _positive_real(payload[key], key)
    for key in (
        LONG_TERM_PERMITTED_CRACK_WIDTH_KEY,
        SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY,
    ):
        payload[key] = _nonnegative_real(payload.get(key, 0.0), key)
    mild_ids, prestress_ids, bar_fatigue_ids, tendon_fatigue_ids = (
        _assigned_catalog_ids(tables)
    )
    capacity_material_id = rebar_table.text_cell(
        payload.get("capacity_steel_material_id")
    )
    if (
        capacity_material_id
        and (payload.get("shear_on") or payload.get("torsion_on"))
    ):
        mild_ids = (*mild_ids, capacity_material_id)
    for kind, assigned_ids in (
        ("mild", mild_ids),
        ("prestress", prestress_ids),
    ):
        key = material_catalog.catalog_key(kind)
        if key in payload:
            payload[key] = material_catalog.normalise_catalog(
                payload[key],
                kind,
                reserved_ids=assigned_ids,
            )
            invalid = material_catalog.invalid_assignments(
                assigned_ids, payload[key], kind
            )
            if invalid:
                raise ValueError(
                    f"undefined {kind} material assignment(s): "
                    + ", ".join(invalid)
                )
        elif assigned_ids:
            raise ValueError(f"{key} is required by material assignments")
    if fatigue_inputs.DETAIL_CATALOG_KEY in payload:
        payload[fatigue_inputs.DETAIL_CATALOG_KEY] = (
            fatigue_inputs.normalise_catalog(
                payload[fatigue_inputs.DETAIL_CATALOG_KEY],
                assigned_ids=bar_fatigue_ids + tendon_fatigue_ids,
            )
        )
        invalid_bar = fatigue_inputs.invalid_assignments(
            bar_fatigue_ids,
            payload[fatigue_inputs.DETAIL_CATALOG_KEY],
            fatigue_inputs.MILD,
        )
        invalid_tendon = fatigue_inputs.invalid_assignments(
            tendon_fatigue_ids,
            payload[fatigue_inputs.DETAIL_CATALOG_KEY],
            fatigue_inputs.PRESTRESS,
        )
        if invalid_bar or invalid_tendon:
            raise ValueError(
                "undefined fatigue-detail assignment(s): "
                + ", ".join((*invalid_bar, *invalid_tendon))
            )
    elif bar_fatigue_ids or tendon_fatigue_ids:
        raise ValueError(
            f"{fatigue_inputs.DETAIL_CATALOG_KEY} is required by fatigue "
            "assignments"
        )
    if fatigue_inputs.BASIS_KEY in payload:
        payload[fatigue_inputs.BASIS_KEY] = fatigue_inputs.normalise_basis(
            payload[fatigue_inputs.BASIS_KEY]
        )
    if "fatigue_edition" in payload:
        payload["fatigue_edition"] = (
            design_standards.parse_design_basis_key(
                payload["fatigue_edition"]
            ).value
        )
    if "sls_code" in payload:
        payload["sls_code"] = design_standards.parse_design_basis_key(
            payload["sls_code"]
        ).value

    elastic = load_cases.active_table(
        tables.get(load_cases.ELASTIC_TABLE_KEY),
        load_cases.ELASTIC_TABLE_KEY,
    )
    ordinary_crack_requested = bool(
        not elastic.empty and elastic["calculate_crack_width"].any()
    )
    if ordinary_crack_requested and "sls_code" not in payload:
        raise ValueError(
            "sls_code is required when an Elastic case requests crack width"
        )

    if "sls_heightened_on" in payload and not isinstance(
        payload["sls_heightened_on"], bool
    ):
        raise ValueError("sls_heightened_on must be a Boolean")
    if not payload.get("sls_heightened_on", False):
        payload[HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY] = _nonnegative_real(
            payload.get(HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY, 0.0),
            HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY,
        )
    if payload.get("sls_heightened_on", False):
        if payload.get("mode") not in {"Elastic", "Both"}:
            raise ValueError(
                "heightened crack control requires Elastic analysis to be enabled"
            )
        if "sls_code" not in payload:
            raise ValueError(
                "sls_code is required when heightened crack control is enabled"
            )
        if payload["sls_code"] != (
            design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024.value
        ):
            raise ValueError(
                "heightened crack control requires "
                "ec2_1_1_first_gen_dk_na_2024"
            )

        surface_key = "sls_heightened_reinforcement_surface"
        if surface_key not in payload:
            raise ValueError(
                f"{surface_key} is required when heightened crack control "
                "is enabled"
            )
        try:
            payload[surface_key] = (
                heightened_crack_control.ReinforcementSurface(
                    payload[surface_key]
                ).value
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{surface_key} must be exactly 'ribbed' or 'smooth'"
            ) from exc

        for key in _HEIGHTENED_POSITIVE_OPERAND_KEYS:
            if key not in payload:
                raise ValueError(
                    f"{key} is required when heightened crack control is enabled"
                )
            if isinstance(payload[key], np.bool_):
                raise ValueError(f"{key} must be a positive finite real number")
            if key == HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY:
                try:
                    width = _nonnegative_real(payload[key], key)
                except ValueError as exc:
                    raise ValueError(
                        f"{key} must be a positive finite real number"
                    ) from exc
                if width <= 0.0:
                    raise ValueError(f"{key} must be a positive finite real number")
                payload[key] = width
            else:
                payload[key] = _positive_real(payload[key], key)
        payload["sls_heightened_reference_case"] = (
            heightened_crack_adapter.resolve_reference_case_name(
                elastic.to_dict("records"),
                payload.get("sls_heightened_reference_case"),
            )
        )
    method_resolvers = (
        ("shear_method", capacity.selected_shear_code),
        ("torsion_method", capacity.selected_torsion_code),
        ("combined_method", capacity.selected_combined_code),
    )
    for key, resolver in method_resolvers:
        if key in payload:
            resolver(payload[key])
    if payload.get("torsion_on") and "torsion_gamma_ct" not in payload:
        raise ValueError(
            "torsion_gamma_ct is required when the torsion calculation is enabled"
        )
    return payload


def _canonical_inputs(tables: Mapping, scalars: Mapping) -> dict:
    _validate_geometry(tables)
    return {
        "tables": {
            key: _table_to_obj(tables.get(key), key)
            for key in PROJECT_TABLE_KEYS
        },
        "scalars": _canonical_scalars(scalars, tables),
    }


def _canonical_presentation(scalars: Mapping) -> dict:
    return {
        modelled_direction.ALIAS_KEY: modelled_direction.normalise_alias(
            scalars.get(modelled_direction.ALIAS_KEY)
        ),
        REPORT_PROFILE_KEY: normalise_report_profile(
            scalars.get(REPORT_PROFILE_KEY)
        ),
    }


def normalise_report_profile(value=None) -> str:
    """Return one exact current report-profile label.

    Early schema-24 builds persisted two exact labels before Brief, Standard and
    Audit were introduced. Only those two spellings migrate; every other unknown
    or inexact value fails closed instead of silently selecting Standard.
    """

    if isinstance(value, str) and value in _LEGACY_REPORT_PROFILE_LABELS:
        return _LEGACY_REPORT_PROFILE_LABELS[value]
    try:
        return report_profiles.resolve_profile(value).label
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unknown persisted report profile {value!r}") from exc


def _input_digest(content: Mapping) -> str:
    canonical = json.dumps(
        content,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def input_sha256(tables: Mapping, scalars: Mapping) -> str:
    """Hash the complete canonical schema input block for project correlation."""
    return _input_digest(_canonical_inputs(tables, scalars))


def persistence_sha256(tables: Mapping, scalars: Mapping) -> str:
    """Hash everything Sector persists for local project recovery.

    The dedicated presentation block remains outside legacy ``input_sha256``.
    Autosave still needs to notice an alias/profile-only edit, so its
    de-duplication key covers both canonical inputs and presentation. Runtime
    result reuse has its own explicit engineering-input identity.
    """

    return _input_digest({
        "inputs": _canonical_inputs(tables, scalars),
        "presentation": _canonical_presentation(scalars),
    })


def _fingerprint_value(value):
    """Return strict type-tagged data for an exact in-memory payload.

    Calculation results contain immutable dataclasses, NumPy values and pandas
    tables that are intentionally richer than project JSON.  A result identity
    hash must distinguish retained type as well as numerical value: ``True``,
    ``1``, ``1.0``, a list and a tuple therefore have different encodings.
    """

    if value is None:
        return ["none"]
    if value is pd.NA:
        return ["pandas-na"]
    if value is pd.NaT:
        return ["pandas-nat"]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", str(value)]
    if type(value) is float:
        if math.isnan(value):
            encoded = "nan"
        elif math.isinf(value):
            encoded = "+inf" if value > 0.0 else "-inf"
        else:
            encoded = value.hex()
        return ["float", encoded]
    if type(value) is str:
        return ["str", value]
    if type(value) is bytes:
        return ["bytes", value.hex()]
    if isinstance(value, np.generic):
        return ["numpy-scalar", str(value.dtype), _fingerprint_value(value.item())]
    if isinstance(value, np.ndarray):
        return [
            "numpy-array",
            f"{type(value).__module__}.{type(value).__qualname__}",
            str(value.dtype),
            list(value.shape),
            _fingerprint_value(value.tolist()),
        ]
    if isinstance(value, pd.DataFrame):
        return [
            "pandas-dataframe",
            f"{type(value).__module__}.{type(value).__qualname__}",
            _fingerprint_value(value.columns),
            _fingerprint_value(value.index),
            [str(dtype) for dtype in value.dtypes],
            _fingerprint_value(value.to_numpy(dtype=object).tolist()),
        ]
    if isinstance(value, pd.Series):
        return [
            "pandas-series",
            f"{type(value).__module__}.{type(value).__qualname__}",
            _fingerprint_value(value.name),
            str(value.dtype),
            _fingerprint_value(list(value.index)),
            _fingerprint_value(value.tolist()),
        ]
    if isinstance(value, pd.Index):
        return [
            "pandas-index",
            f"{type(value).__module__}.{type(value).__qualname__}",
            str(value.dtype),
            _fingerprint_value(value.name),
            _fingerprint_value(value.tolist()),
        ]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        identity = f"{type(value).__module__}.{type(value).__qualname__}"
        fields = [
            [field.name, _fingerprint_value(getattr(value, field.name))]
            for field in dataclasses.fields(value)
        ]
        return ["dataclass", identity, fields]
    if isinstance(value, Mapping):
        items = []
        for key, item in value.items():
            encoded_key = _fingerprint_value(key)
            encoded_item = _fingerprint_value(item)
            sort_key = json.dumps(
                encoded_key,
                ensure_ascii=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            items.append((sort_key, encoded_key, encoded_item))
        items.sort(key=lambda item: item[0])
        identity = f"{type(value).__module__}.{type(value).__qualname__}"
        return ["mapping", identity, [[key, item] for _, key, item in items]]
    if type(value) is list:
        return ["list", [_fingerprint_value(item) for item in value]]
    if type(value) is tuple:
        return ["tuple", [_fingerprint_value(item) for item in value]]
    if type(value) in {set, frozenset}:
        encoded = [_fingerprint_value(item) for item in value]
        encoded.sort(key=lambda item: json.dumps(
            item,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        ))
        return ["set" if type(value) is set else "frozenset", encoded]
    if isinstance(value, datetime):
        return ["datetime", value.isoformat()]
    raise TypeError(
        "unsupported calculation fingerprint value: "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def result_sha256(result) -> str:
    """Hash an exact retained result/payload with concrete types preserved."""

    canonical = json.dumps(
        _fingerprint_value(result),
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _valid_sha256(value) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def dump_project(
    tables: Mapping,
    scalars: Mapping,
    *,
    calculation=None,
    app_version=None,
    revision=None,
) -> str:
    """Serialize one current-schema project."""
    content = _canonical_inputs(tables, scalars)
    digest = _input_digest(content)
    app_version = str(app_version or sector_version)
    revision = str(revision or source_revision())
    payload = {
        "format": FORMAT,
        "version": VERSION,
        **content,
        "presentation": _canonical_presentation(scalars),
        "provenance": {
            "sector_version": app_version,
            "source_revision": revision,
            "saved_at_utc": datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
            "input_sha256": digest,
            "results_included": False,
        },
    }
    if isinstance(calculation, Mapping):
        record = {
            key: _json_value(calculation.get(key))
            for key in (
                "performed_at_utc",
                "sector_version",
                "source_revision",
                "input_sha256",
                "engineering_input_sha256",
                "result_sha256",
            )
            if calculation.get(key) not in (None, "")
        }
        record["matches_saved_inputs"] = (
            record.get("input_sha256") == digest
        )
        for key in ("engineering_input_sha256", "result_sha256"):
            if key in record and not _valid_sha256(record[key]):
                raise ValueError(
                    f"calculation {key} must be a lowercase SHA-256"
                )
        payload["calculation"] = record
    return json.dumps(payload, indent=2, ensure_ascii=True, allow_nan=False)


def _decode(text: str) -> dict:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("not valid JSON") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("not a Sector project file")
    version = data.get("version")
    if version not in {*MIGRATABLE_VERSIONS, VERSION}:
        raise ValueError(
            f"unsupported Sector project schema {version!r}; "
            f"only current schema {VERSION} and migrations from schemas "
            f"{LEGACY_MIGRATABLE_VERSION} and {MIGRATABLE_VERSION} are supported"
        )
    if not isinstance(data.get("tables"), Mapping):
        raise ValueError("malformed tables section")
    if not isinstance(data.get("scalars"), Mapping):
        raise ValueError("malformed scalars section")
    if not isinstance(data.get("presentation", {}), Mapping):
        raise ValueError("malformed presentation section")
    if not isinstance(data.get("provenance"), Mapping):
        raise ValueError("missing project provenance")
    return data


def project_provenance(text: str) -> dict:
    """Read provenance and verify current inputs/calculation correlation."""
    data = _decode(text)
    content = {
        "tables": data["tables"],
        "scalars": data["scalars"],
    }
    try:
        actual = _input_digest(content)
    except (TypeError, ValueError) as exc:
        raise ValueError("project inputs are not canonical JSON") from exc
    provenance = data["provenance"]
    recorded = provenance.get("input_sha256")
    calculation = (
        dict(data["calculation"])
        if isinstance(data.get("calculation"), Mapping)
        else None
    )
    if calculation is not None:
        calculation["matches_saved_inputs"] = (
            bool(calculation.get("input_sha256"))
            and calculation.get("input_sha256") == actual
        )
    return {
        "schema_version": data["version"],
        "sector_version": provenance.get("sector_version"),
        "source_revision": provenance.get("source_revision"),
        "saved_at_utc": provenance.get("saved_at_utc"),
        "input_sha256": recorded,
        "input_hash_valid": bool(recorded) and recorded == actual,
        "results_included": False,
        "calculation": calculation,
    }


def _migrated_schema25_crack_widths(
    raw_scalars: Mapping,
) -> tuple[dict[str, float], tuple[str, ...], dict]:
    """Split the retired schema-25 shared width without inferring applicability."""

    raw = raw_scalars.get(LEGACY_SHARED_CRACK_WIDTH_KEY)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        shared = 0.0
    else:
        shared = _nonnegative_real(raw, LEGACY_SHARED_CRACK_WIDTH_KEY)
    heightened_enabled = raw_scalars.get("sls_heightened_on") is True
    if heightened_enabled and shared <= 0.0:
        raise ValueError(
            f"{LEGACY_SHARED_CRACK_WIDTH_KEY} must be positive when schema-25 "
            "heightened crack control is enabled"
        )
    heightened = shared if heightened_enabled else 0.0
    warnings = (
        (
            "Schema 25 used one permitted crack width for both ordinary "
            "durations. Sector copied the positive value to the independent "
            "long-term and short-term inputs; review both before recalculating."
        ),
    ) if shared > 0.0 else ()
    migrated = {
        LONG_TERM_PERMITTED_CRACK_WIDTH_KEY: shared,
        SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY: shared,
        HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY: heightened,
    }
    return migrated, warnings, {
        "source_key": LEGACY_SHARED_CRACK_WIDTH_KEY,
        "shared_value_mm": shared,
        "long_term_value_mm": shared,
        "short_term_value_mm": shared,
        "heightened_value_mm": heightened,
        "heightened_preserved": heightened_enabled,
    }


def _migrated_heightened_operands(
    raw_scalars: Mapping,
    elastic: pd.DataFrame,
) -> tuple[dict, tuple[str, ...], bool]:
    """Replace the retired single-system inputs with the dual input contract."""

    old_keys = LEGACY_HEIGHTENED_OPERAND_KEYS.intersection(raw_scalars)
    if not old_keys:
        return dict(raw_scalars), (), False
    new_only = {
        "sls_heightened_reference_case",
        "sls_heightened_fine_effective_tension_area_mm2",
        "sls_heightened_coarse_effective_tension_area_mm2",
    }
    mixed = new_only.intersection(raw_scalars)
    if mixed:
        raise ValueError(
            "heightened crack control mixes retired and current dual-system "
            "inputs: " + ", ".join(sorted(mixed))
        )

    migrated = dict(raw_scalars)
    for key in LEGACY_HEIGHTENED_OPERAND_KEYS:
        migrated.pop(key, None)
    legacy_area = raw_scalars.get(
        "sls_heightened_effective_tension_area_mm2"
    )
    if legacy_area is not None:
        migrated["sls_heightened_fine_effective_tension_area_mm2"] = legacy_area
        migrated["sls_heightened_coarse_effective_tension_area_mm2"] = legacy_area

    if raw_scalars.get("sls_heightened_on") is True:
        try:
            reference = heightened_crack_adapter.resolve_reference_case_name(
                elastic.to_dict("records"), None
            )
        except ValueError as exc:
            raise ValueError(
                "the retired heightened configuration cannot be migrated because "
                "it does not identify one reference case; leave exactly one "
                "Elastic case crack-enabled, then load and explicitly review it"
            ) from exc
        migrated["sls_heightened_reference_case"] = reference
    warning = (
        "The retired single-system heightened inputs were migrated to the dual "
        "fine/coarse workflow. The former effective tension area was copied to "
        "both systems; diameter, reinforcement modulus and provided area now "
        "come from retained ordinary crack evidence. Review both effective "
        "tension areas before recalculating."
    )
    return migrated, (warning,), True


def _apply_presentation(
    data: Mapping,
    raw_scalars: Mapping,
    scalars: dict,
) -> None:
    """Apply project-owned presentation values after input canonicalisation."""

    raw_presentation = data.get("presentation", {})
    unknown_presentation = (
        set(raw_presentation) - set(PRESENTATION_SCALAR_KEYS)
    )
    if unknown_presentation:
        raise ValueError(
            "unknown current-schema presentation inputs: "
            + ", ".join(sorted(unknown_presentation))
        )
    scalars[modelled_direction.ALIAS_KEY] = (
        modelled_direction.normalise_alias(
            raw_presentation.get(modelled_direction.ALIAS_KEY)
        )
    )
    legacy_report_profile = raw_scalars.get(REPORT_PROFILE_KEY)
    current_report_profile = raw_presentation.get(REPORT_PROFILE_KEY)
    if current_report_profile is None:
        current_report_profile = legacy_report_profile
    elif legacy_report_profile is not None:
        if normalise_report_profile(current_report_profile) != (
            normalise_report_profile(legacy_report_profile)
        ):
            raise ValueError(
                "conflicting report profiles in scalars and presentation"
            )
    scalars[REPORT_PROFILE_KEY] = normalise_report_profile(
        current_report_profile
    )


def parse_project_with_info(text: str):
    """Return current inputs plus source-schema migration information.

    ``parse_project`` remains the two-value compatibility API. Callers that need
    to surface a migration warning use this three-value wrapper.
    """

    data = _decode(text)
    provenance = project_provenance(text)
    if not provenance["input_hash_valid"]:
        raise ValueError("project input hash mismatch")
    unknown_tables = set(data["tables"]) - set(PROJECT_TABLE_KEYS)
    missing_tables = set(PROJECT_TABLE_KEYS) - set(data["tables"])
    if unknown_tables:
        raise ValueError(
            "unknown current-schema tables: "
            + ", ".join(sorted(unknown_tables))
        )
    if missing_tables:
        raise ValueError(
            "missing current-schema tables: "
            + ", ".join(sorted(missing_tables))
        )

    source_version = data["version"]
    raw_scalars = data["scalars"]
    migration_warnings: tuple[str, ...] = ()
    migration_provenance = {"source_key": None}
    heightened_contract_migrated = False
    tables = {
        key: _obj_to_table(data["tables"][key], key)
        for key in PROJECT_TABLE_KEYS
    }
    if source_version == LEGACY_MIGRATABLE_VERSION:
        allowed_schema25_scalars = (
            set(SCALAR_KEYS)
            - {
                LONG_TERM_PERMITTED_CRACK_WIDTH_KEY,
                SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY,
                HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY,
                "shear_gamma_v",
            }
            | {LEGACY_SHARED_CRACK_WIDTH_KEY}
            | LEGACY_HEIGHTENED_OPERAND_KEYS
        )
        unknown_scalars = (
            set(raw_scalars)
            - allowed_schema25_scalars
            - {REPORT_PROFILE_KEY}
        )
        if unknown_scalars:
            raise ValueError(
                "unknown schema-25 inputs: "
                + ", ".join(sorted(unknown_scalars))
            )
        migrated_widths, migration_warnings, migration_provenance = (
            _migrated_schema25_crack_widths(raw_scalars)
        )
        (
            migrated_scalars,
            heightened_warnings,
            heightened_contract_migrated,
        ) = _migrated_heightened_operands(
            raw_scalars,
            tables[load_cases.ELASTIC_TABLE_KEY],
        )
        migration_warnings = (*migration_warnings, *heightened_warnings)
        migrated_scalars.pop(LEGACY_SHARED_CRACK_WIDTH_KEY, None)
        migrated_scalars.pop(REPORT_PROFILE_KEY, None)
        migrated_scalars.update(migrated_widths)
        gamma_v_active = (
            migrated_scalars.get("shear_on") is True
            and (
                migrated_scalars.get("combined_method")
                if migrated_scalars.get("combined_on") is True
                else migrated_scalars.get("shear_method")
            ) == codes.EC2_2023.label
            and migrated_scalars.get("shear_links") is not True
        )
        if gamma_v_active:
            migration_warnings = (
                *migration_warnings,
                "Schema 25 used the fixed DS/EN 1992-1-1:2023 shear "
                "partial factor. Sector migrated the calculation to the "
                "explicit gamma_V input at 1.40; review it before "
                "recalculating.",
            )
        migration_provenance["shear_gamma_v"] = {
            "defaulted": True,
            "value": float(codes.EC2_2023.shear_gamma_v),
            "active_2023_shear": gamma_v_active,
        }
        scalars = _canonical_scalars(
            migrated_scalars,
            tables,
            migrate_gamma_v=True,
        )
    elif source_version == MIGRATABLE_VERSION:
        allowed_schema26_scalars = set(SCALAR_KEYS) - {"shear_gamma_v"}
        unknown_scalars = (
            set(raw_scalars)
            - allowed_schema26_scalars
            - {REPORT_PROFILE_KEY}
        )
        if unknown_scalars:
            raise ValueError(
                "unknown schema-26 inputs: "
                + ", ".join(sorted(unknown_scalars))
            )
        migrated_scalars = dict(raw_scalars)
        migrated_scalars.pop(REPORT_PROFILE_KEY, None)
        gamma_v_active = (
            migrated_scalars.get("shear_on") is True
            and (
                migrated_scalars.get("combined_method")
                if migrated_scalars.get("combined_on") is True
                else migrated_scalars.get("shear_method")
            ) == codes.EC2_2023.label
            and migrated_scalars.get("shear_links") is not True
        )
        if gamma_v_active:
            migration_warnings = (
                "Schema 26 used the fixed DS/EN 1992-1-1:2023 shear "
                "partial factor. Sector migrated the calculation to the "
                "explicit gamma_V input at 1.40; review it before "
                "recalculating.",
            )
        migration_provenance["shear_gamma_v"] = {
            "defaulted": True,
            "value": float(codes.EC2_2023.shear_gamma_v),
            "active_2023_shear": gamma_v_active,
        }
        scalars = _canonical_scalars(
            migrated_scalars,
            tables,
            migrate_gamma_v=True,
        )
    else:
        unknown_scalars = (
            set(raw_scalars)
            - set(SCALAR_KEYS)
            - {REPORT_PROFILE_KEY}
        )
        if unknown_scalars:
            raise ValueError(
                "unknown current-schema inputs: "
                + ", ".join(sorted(unknown_scalars))
            )
        scalars = _canonical_scalars(raw_scalars, tables)

    _apply_presentation(data, raw_scalars, scalars)
    _validate_geometry(tables)
    info = {
        "source_schema_version": source_version,
        "target_schema_version": VERSION,
        "migrated": (
            source_version != VERSION or heightened_contract_migrated
        ),
        "migration_warnings": migration_warnings,
        "migration_provenance": migration_provenance,
        "provenance": provenance,
    }
    return tables, scalars, info


def parse_project(text: str):
    """Return ``(tables, scalars)`` with bounded schema compatibility."""

    tables, scalars, _info = parse_project_with_info(text)
    return tables, scalars
