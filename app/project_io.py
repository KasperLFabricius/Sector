"""Current-schema project persistence for Sector.

Project files contain the geometry, reinforcement, actions, numerical
coefficients and direct method choices needed to reproduce a calculation.
Sector 0.94 projects used schema 25. Sector 0.95 used schema 26 to separate
long-term, short-term and heightened permitted crack-width inputs. Sector 0.96.1
uses schema 27 to persist the user-selected DS/EN 1992-1-1:2023 shear partial
factor.
Schemas 25 and 26 have bounded in-memory migrations; schema 24 and future
schemas remain unsupported. Retired component-mapped bridge inputs are
deliberately absent from the schema.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

import fatigue_inputs
import load_cases
import material_catalog
import numpy as np
import pandas as pd
import reinforcement_table as rebar_table

from app import engineer_messages, modelled_direction, report_profiles
from app import heightened_crack_adapter
from app.table_field_definitions import (
    decimal_issue_ledger,
)
from sector import __version__ as sector_version
from sector import (
    capacity,
    codes,
    design_standards,
    detailing,
    geometry,
    heightened_crack_control,
    material_presets,
    plastic,
    shear,
)
from sector.build_info import source_revision
from sector.engineer_message import EngineerMessage
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


class ProjectInputError(ValueError):
    """A deliberate project-file validation error with optional public copy."""

    def __init__(
        self,
        *args: object,
        engineer_message: EngineerMessage | None = None,
    ) -> None:
        super().__init__(*args)
        if engineer_message is not None and not isinstance(
            engineer_message, EngineerMessage
        ):
            raise TypeError("engineer_message must be an EngineerMessage")
        self.engineer_message = engineer_message


@dataclasses.dataclass(frozen=True, slots=True)
class PreparedProjectUpload:
    """Validated upload text paired with its raw-byte content identity."""

    content_identity: str
    text: str


_PROJECT_READ_FALLBACK = EngineerMessage(
    "PROJECT-READ",
    "the project file could not be read",
)
_PROJECT_UNREADABLE = EngineerMessage(
    "PROJECT-UNREADABLE",
    "the selected file is not a readable Sector project",
)
_PROJECT_INCOMPATIBLE = EngineerMessage(
    "PROJECT-INCOMPATIBLE",
    "the project file contains information that this version of Sector cannot read",
)
_PROJECT_DAMAGED = EngineerMessage(
    "PROJECT-DAMAGED",
    "the project file is incomplete or damaged",
)
_PROJECT_INVALID_INPUT = EngineerMessage(
    "PROJECT-INVALID-INPUT",
    "the project file contains an invalid input value",
)
_PROJECT_SWEEP_RESOLUTION = EngineerMessage(
    "PROJECT-SWEEP-RESOLUTION",
    "increase the neutral-axis sweep maximum increment; the requested sweep is "
    "too fine to calculate reliably",
)
_PROJECT_SWEEP_SPAN = EngineerMessage(
    "PROJECT-SWEEP-SPAN",
    "correct the neutral-axis sweep start and end angles; their separation is "
    "too large to calculate reliably",
)
_PROJECT_CHANGED = EngineerMessage(
    "PROJECT-CHANGED",
    "the project file is damaged or was changed outside Sector",
)
_PROJECT_CALCULATION_DAMAGED = EngineerMessage(
    "PROJECT-CALCULATION-DAMAGED",
    "the recorded calculation is damaged; recalculate before saving the project",
)
_PROJECT_REPORT_UNAVAILABLE = EngineerMessage(
    "PROJECT-REPORT-UNAVAILABLE",
    "the saved report type is not available in this version of Sector",
)
_PROJECT_REPORT_CONFLICT = EngineerMessage(
    "PROJECT-REPORT-CONFLICT",
    "the project file contains conflicting report settings",
)
_PROJECT_DIRECTION = EngineerMessage(
    "PROJECT-DIRECTION",
    "the modelled-direction description must be a single line of at most 60 characters",
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
    "shear_section_form", "shear_vx_web_inclination_deg",
    "shear_vy_web_inclination_deg", "shear_hoop_diameter",
    "shear_vx_fitted_z", "shear_vy_fitted_z", "shear_duct_case",
    "shear_vx_duct_sum", "shear_vy_duct_sum", "shear_vx_duct_largest",
    "shear_vy_duct_largest",
    "shear_dlower", "shear_gamma_v", "shear_links", "shear_vx_link_legs",
    "shear_vy_link_legs", "shear_link_dia", "shear_link_s",
    "shear_fywk", "shear_vx_transverse_leg_spacing",
    "shear_vy_transverse_leg_spacing", "strut_cot_min",
    "strut_cot_max",
    # Torsion and combined resistance.
    "torsion_on", "torsion_method", "torsion_design_basis",
    "torsion_member_scope", "torsion_T", "torsion_tef",
    "torsion_nu_v", "torsion_gamma_ct", "torsion_subdivide",
    "torsion_nsub", "torsion_sub_x0", "torsion_sub_y0",
    "torsion_sub_x1", "torsion_sub_y1", "torsion_sub_x2",
    "torsion_sub_y2", "torsion_sub_x3", "torsion_sub_y3",
    "torsion_sub_b0", "torsion_sub_h0", "torsion_sub_b1",
    "torsion_sub_h1", "torsion_sub_b2", "torsion_sub_h2",
    "torsion_sub_b3", "torsion_sub_h3", "combined_on",
    "combined_method", "combined_mv_independent",
    capacity.TORSION_CASE_AUTHORITIES_KEY,
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

# Every persisted scalar has one explicit JSON type at the project boundary.
# Numeric engineering inputs accept JSON integers or floats and are normalised to
# finite floats. Counts accept an integral JSON number and are normalised to ints.
# No Boolean/string/container truthiness or float-from-text conversion is allowed.
_BOOLEAN_SCALAR_KEYS = frozenset({
    "qsv_qs_cover_to_edge",
    "mild_active_comp",
    "pl_check_util",
    "pl_interaction",
    "sls_cw",
    "sls_heightened_on",
    "fatigue_on",
    "fatigue_check_steel",
    "fatigue_check_concrete",
    "minimum_reinforcement_on",
    "transverse_detailing_on",
    "clear_spacing_on",
    "detailing_include_tendons",
    "transverse_apply_ductility_reduction",
    "shear_on",
    "shear_links",
    "torsion_on",
    "torsion_nu_v",
    "torsion_subdivide",
    "combined_on",
    "combined_mv_independent",
    "autosave_on",
})

_INTEGER_SCALAR_KEYS = frozenset({
    "qsv_ring_n",
    "qsv_bot_n",
    "qsv_top_n",
    "qsv_bot_n2",
    "qsv_top_n2",
    "qsv_bot_layers",
    "qsv_top_layers",
    "qsv_tnd_n",
    "qsv_tnd_layers",
    "torsion_nsub",
    "autosave_min",
})

_TEXT_SCALAR_KEYS = frozenset({
    "qsv_shape",
    "qsv_t_orientation",
    "qsv_qs_rebar_mode",
    "conc_preset",
    "mild_preset",
    "pre_preset",
    "mode",
    "sls_bond",
    "sls_code",
    "sls_member",
    "sls_heightened_reference_case",
    "sls_heightened_reinforcement_surface",
    "fatigue_edition",
    "fatigue_concrete_method",
    "detailing_edition",
    "detailing_member_type",
    "detailing_cut_direction",
    "transverse_ductility_class",
    "shear_method",
    "shear_face_x",
    "shear_face_y",
    "shear_section_form",
    "shear_duct_case",
    "torsion_method",
    "torsion_design_basis",
    "torsion_member_scope",
    "combined_method",
    "capacity_steel_material_id",
    "rep_proj_no",
    "rep_proj_name",
    "rep_section",
    "rep_rev",
    "rep_author",
    "rep_comments",
})

_NESTED_SCALAR_KEYS = frozenset({
    material_catalog.MILD_CATALOG_KEY,
    material_catalog.PRESTRESS_CATALOG_KEY,
    fatigue_inputs.DETAIL_CATALOG_KEY,
    fatigue_inputs.BASIS_KEY,
    capacity.TORSION_CASE_AUTHORITIES_KEY,
})

_EXACT_TEXT_OPTIONS = {
    "qsv_shape": frozenset({
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
    }),
    "qsv_t_orientation": frozenset({"Flange at top", "Flange at bottom"}),
    "qsv_qs_rebar_mode": frozenset({"By number", "By spacing"}),
    "shear_section_form": frozenset(shear.SHEAR_SECTION_FORMS),
    "shear_duct_case": frozenset(shear.SHEAR_DUCT_CASES),
    "torsion_design_basis": frozenset(capacity.TORSION_DESIGN_BASES),
    "torsion_member_scope": frozenset(capacity.TORSION_MEMBER_SCOPES),
    "conc_preset": frozenset(material_presets.CONCRETE_PRESETS),
    "mild_preset": frozenset({
        *material_catalog.presets("mild"),
        material_catalog.CUSTOM_PRESET,
    }),
    "pre_preset": frozenset({
        *material_catalog.presets("prestress"),
        material_catalog.CUSTOM_PRESET,
    }),
    "mode": frozenset({"Plastic", "Elastic", "Both"}),
    "sls_bond": frozenset({
        "Ribbed / high bond (k1 = 0.8)",
        "Plain round (k1 = 1.6)",
    }),
    "sls_member": frozenset({"Beam", "Slab"}),
    "sls_heightened_reinforcement_surface": frozenset({"ribbed", "smooth"}),
    "fatigue_concrete_method": frozenset({
        "Explicit Palmgren-Miner spectrum",
        "User-defined Miner S-N relation",
        "Damage-equivalent stress amplitude",
    }),
    "detailing_edition": frozenset(detailing.EDITIONS),
    "detailing_member_type": frozenset(detailing.MEMBER_TYPES),
    "detailing_cut_direction": frozenset(detailing.CUT_DIRECTIONS),
    "transverse_ductility_class": frozenset({"A", "B", "C"}),
    "shear_face_x": frozenset(load_cases.FACE_OPTIONS),
    "shear_face_y": frozenset(load_cases.FACE_OPTIONS),
}

_TYPED_NONREAL_SCALAR_KEYS = (
    _BOOLEAN_SCALAR_KEYS
    | _INTEGER_SCALAR_KEYS
    | _TEXT_SCALAR_KEYS
    | _NESTED_SCALAR_KEYS
)
_REAL_SCALAR_KEYS = frozenset(SCALAR_KEYS) - _TYPED_NONREAL_SCALAR_KEYS

if len(_TYPED_NONREAL_SCALAR_KEYS) != sum(map(len, (
    _BOOLEAN_SCALAR_KEYS,
    _INTEGER_SCALAR_KEYS,
    _TEXT_SCALAR_KEYS,
    _NESTED_SCALAR_KEYS,
))):  # pragma: no cover - import-time schema authoring guard
    raise RuntimeError("project scalar type groups overlap")


def _invalid_input(message: str) -> ProjectInputError:
    """Return a typed internal diagnostic carrying authored public guidance."""

    return ProjectInputError(
        message,
        engineer_message=_PROJECT_INVALID_INPUT,
    )


def _strict_finite_real(
    value,
    label: str,
    *,
    requirement: str = "must be a finite number",
) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        raise _invalid_input(f"{label} {requirement}")
    number = float(value)
    if not math.isfinite(number):
        raise _invalid_input(f"{label} {requirement}")
    return 0.0 if number == 0.0 else number


def _strict_integer(value, label: str) -> int:
    if type(value) not in {int, float} or isinstance(value, bool):
        raise _invalid_input(f"{label} must be a whole number")
    number = float(value)
    if not math.isfinite(number) or not number.is_integer():
        raise _invalid_input(f"{label} must be a whole number")
    return int(number)


def _strict_text(value, label: str) -> str:
    if type(value) is not str:
        raise _invalid_input(f"{label} must be text")
    return value


def _validate_catalog_envelope(
    value,
    key: str,
    *,
    expected_version: int,
) -> tuple[dict, list[dict]]:
    if not isinstance(value, Mapping):
        raise _invalid_input(f"{key} must be an object")
    catalog = dict(value)
    allowed = {"version", "next_id", "items"}
    unknown = set(catalog) - allowed
    if unknown:
        raise _invalid_input(f"{key} contains unknown fields")
    if "version" in catalog:
        version = _strict_integer(catalog["version"], f"{key} version")
        if version != expected_version:
            raise _invalid_input(f"{key} version is not supported")
        catalog["version"] = version
    if "next_id" in catalog:
        next_id = _strict_integer(catalog["next_id"], f"{key} next_id")
        if next_id < 1:
            raise _invalid_input(f"{key} next_id must be positive")
        catalog["next_id"] = next_id
    items = catalog.get("items")
    if type(items) is not list:
        raise _invalid_input(f"{key} items must be a list")
    if any(not isinstance(item, Mapping) for item in items):
        raise _invalid_input(f"{key} items must contain only objects")
    return catalog, [dict(item) for item in items]


def _validate_material_catalog(value, kind: str, key: str) -> dict:
    catalog, items = _validate_catalog_envelope(
        value,
        key,
        expected_version=material_catalog.VERSION,
    )
    text_fields = {"id", "name", "description", "preset"}
    integer_fields = {"curve"}
    boolean_fields = (
        {"active_in_compression", "active_comp"}
        if kind == "mild"
        else set()
    )
    real_fields = set(material_catalog.fields(kind))
    allowed = text_fields | integer_fields | boolean_fields | real_fields
    validated = []
    for position, item in enumerate(items, start=1):
        label = f"{key} item {position}"
        if set(item) - allowed:
            raise _invalid_input(f"{label} contains unknown fields")
        for field in text_fields.intersection(item):
            item[field] = _strict_text(item[field], f"{label} {field}")
        for field in integer_fields.intersection(item):
            item[field] = _strict_integer(item[field], f"{label} {field}")
        for field in boolean_fields.intersection(item):
            if type(item[field]) is not bool:
                raise _invalid_input(f"{label} {field} must be a Boolean")
        for field in real_fields.intersection(item):
            item[field] = _strict_finite_real(item[field], f"{label} {field}")
        try:
            material_catalog.validate_material_definition(item, kind)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise _invalid_input(f"{label}: {exc}") from exc
        validated.append(item)
    catalog["items"] = validated
    return catalog


def _validate_material_aliases(payload: Mapping) -> None:
    """Validate persisted live-panel aliases against their owning material law.

    Current projects normally carry complete catalogues, while deliberately
    sparse projects may carry only the historical M1/P1 widget aliases. Rebuild
    the same family definition the live panel will own and reject an invalid
    active domain before any project state is applied. When a present catalogue
    no longer contains M1/P1, its old aliases are orphaned and cannot recreate or
    override a material. Inactive curve fields are left out by
    ``validate_material_definition``.
    """

    for kind, prefix, preset_key, alias_id in (
        ("mild", "mild", "mild_preset", "M1"),
        ("prestress", "pre", "pre_preset", "P1"),
    ):
        alias_keys = {
            f"{prefix}_{field}": field
            for field in material_catalog.fields(kind)
        }
        relevant_keys = set(alias_keys) | {preset_key}
        if kind == "mild":
            relevant_keys.add("mild_active_comp")
        if not relevant_keys.intersection(payload):
            continue

        entry = None
        catalog_key = material_catalog.catalog_key(kind)
        catalog_is_present = catalog_key in payload
        catalog = payload.get(catalog_key)
        if isinstance(catalog, Mapping):
            items = catalog.get("items")
            if isinstance(items, list):
                entry = next(
                    (
                        dict(item)
                        for item in items
                        if isinstance(item, Mapping)
                        and item.get("id") == alias_id
                    ),
                    None,
                )
        if entry is None and catalog_is_present:
            continue
        if entry is None:
            selected = payload.get(preset_key)
            available = material_catalog.presets(kind)
            entry = material_catalog.default_entry(
                kind,
                preset=selected if selected in available else None,
            )

        for key, field in alias_keys.items():
            if key in payload:
                entry[field] = payload[key]
        if kind == "mild" and "mild_active_comp" in payload:
            entry["active_in_compression"] = payload["mild_active_comp"]
        try:
            material_catalog.validate_material_definition(entry, kind)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            family = "mild-steel" if kind == "mild" else "prestressing-steel"
            raise _invalid_input(f"invalid {family} material values: {exc}") from exc


def _validate_fatigue_catalog(value, key: str) -> dict:
    catalog, items = _validate_catalog_envelope(
        value,
        key,
        expected_version=fatigue_inputs.VERSION,
    )
    exemplar = fatigue_inputs.default_entry()
    text_fields = {
        field for field, default in exemplar.items() if type(default) is str
    }
    boolean_fields = {
        field for field, default in exemplar.items() if type(default) is bool
    }
    real_fields = set(exemplar) - text_fields - boolean_fields
    allowed = text_fields | boolean_fields | real_fields
    validated = []
    for position, item in enumerate(items, start=1):
        label = f"{key} item {position}"
        if set(item) - allowed:
            raise _invalid_input(f"{label} contains unknown fields")
        for field in text_fields.intersection(item):
            item[field] = _strict_text(item[field], f"{label} {field}")
        for field in boolean_fields.intersection(item):
            if type(item[field]) is not bool:
                raise _invalid_input(f"{label} {field} must be a Boolean")
        for field in real_fields.intersection(item):
            item[field] = _strict_finite_real(item[field], f"{label} {field}")
        validated.append(item)
    catalog["items"] = validated
    return catalog


def _validate_fatigue_basis(value, key: str) -> dict:
    if not isinstance(value, Mapping):
        raise _invalid_input(f"{key} must be an object")
    basis = dict(value)
    if set(basis) - {"method", "notes"}:
        raise _invalid_input(f"{key} contains unknown fields")
    for field in ("method", "notes"):
        if field in basis:
            basis[field] = _strict_text(basis[field], f"{key} {field}")
    return basis


def _validate_torsion_case_authorities(value, key: str) -> dict:
    """Validate the separately persisted Plastic-case authority mapping."""

    if not isinstance(value, Mapping):
        raise _invalid_input(f"{key} must be an object")
    validated = {}
    expected_fields = {
        capacity.TORSION_CASE_DESIGN_BASIS_KEY,
        capacity.TORSION_CASE_MEMBER_SCOPE_KEY,
    }
    for raw_name, raw_entry in value.items():
        name = _strict_text(raw_name, f"{key} case name")
        if not name.strip() or name != name.strip():
            raise _invalid_input(f"{key} contains an invalid case name")
        if not isinstance(raw_entry, Mapping):
            raise _invalid_input(f"{key} {name} must be an object")
        entry = dict(raw_entry)
        if set(entry) != expected_fields:
            raise _invalid_input(
                f"{key} {name} must contain design basis and member scope"
            )
        design_basis = _strict_text(
            entry[capacity.TORSION_CASE_DESIGN_BASIS_KEY],
            f"{key} {name} design basis",
        )
        member_scope = _strict_text(
            entry[capacity.TORSION_CASE_MEMBER_SCOPE_KEY],
            f"{key} {name} member scope",
        )
        if design_basis not in capacity.TORSION_DESIGN_BASES:
            raise _invalid_input(f"{key} {name} design basis is not supported")
        if member_scope not in capacity.TORSION_MEMBER_SCOPES:
            raise _invalid_input(f"{key} {name} member scope is not supported")
        validated[name] = {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: design_basis,
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: member_scope,
        }
    return validated


def _validate_nested_scalar(value, key: str):
    if key == material_catalog.MILD_CATALOG_KEY:
        return _validate_material_catalog(value, "mild", key)
    if key == material_catalog.PRESTRESS_CATALOG_KEY:
        return _validate_material_catalog(value, "prestress", key)
    if key == fatigue_inputs.DETAIL_CATALOG_KEY:
        return _validate_fatigue_catalog(value, key)
    if key == fatigue_inputs.BASIS_KEY:
        return _validate_fatigue_basis(value, key)
    if key == capacity.TORSION_CASE_AUTHORITIES_KEY:
        return _validate_torsion_case_authorities(value, key)
    raise RuntimeError(f"unhandled nested project scalar {key}")


def _validated_scalar_payload(scalars: Mapping) -> dict:
    payload = {}
    for key in SCALAR_KEYS:
        if key not in scalars:
            continue
        value = _json_value(scalars[key])
        # These exact-choice resolvers retain their established unknown-value
        # diagnostics. Reject non-text values at this authored input boundary
        # before handing supported strings to those resolvers.
        if key in {
            "shear_method",
            "torsion_method",
            "combined_method",
            "sls_code",
            "fatigue_edition",
        }:
            payload[key] = _strict_text(value, key)
            continue
        if (
            key == "sls_heightened_reinforcement_surface"
            and scalars.get("sls_heightened_on") is True
        ):
            payload[key] = value
            continue
        if key in _BOOLEAN_SCALAR_KEYS:
            if type(value) is not bool:
                raise _invalid_input(f"{key} must be a Boolean")
        elif key in _INTEGER_SCALAR_KEYS:
            value = _strict_integer(value, key)
        elif key in _TEXT_SCALAR_KEYS:
            value = _strict_text(value, key)
            options = _EXACT_TEXT_OPTIONS.get(key)
            if options is not None and value not in options:
                raise _invalid_input(f"{key} is not a supported selection")
        elif key in _NESTED_SCALAR_KEYS:
            value = _validate_nested_scalar(value, key)
        elif key in _REAL_SCALAR_KEYS:
            requirement = "must be a finite number"
            if key in _POSITIVE_FACTOR_KEYS or key in (
                "sls_heightened_effective_tensile_strength_mpa",
                "sls_heightened_fine_effective_tension_area_mm2",
                "sls_heightened_coarse_effective_tension_area_mm2",
            ):
                requirement = "must be a positive finite real number"
            elif key in (
                LONG_TERM_PERMITTED_CRACK_WIDTH_KEY,
                SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY,
            ):
                requirement = "must be a non-negative finite real number"
            elif key == HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY:
                requirement = (
                    "must be a positive finite real number"
                    if scalars.get("sls_heightened_on") is True
                    else "must be a non-negative finite real number"
                )
            value = _strict_finite_real(
                value,
                key,
                requirement=requirement,
            )
        else:  # pragma: no cover - import-time manifest covers current keys
            raise RuntimeError(f"untyped project scalar {key}")
        payload[key] = value
    return payload


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
    elif key in REINFORCEMENT_TABLE_KEYS:
        issues = rebar_table.row_issues(
            frame, REINFORCEMENT_TABLE_KEYS[key]
        )
        if issues:
            element_id, reason = issues[0]
            raise _invalid_input(
                f"{key} {element_id} has invalid reinforcement {reason}"
            )


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


def _expected_table_columns(key: str) -> tuple[str, ...]:
    if key in TABLE_KEYS[:2]:
        return _GEOMETRY_COLUMNS
    if key in REINFORCEMENT_TABLE_KEYS:
        return tuple(rebar_table.COLUMNS)
    if key in CASE_TABLE_KEYS:
        return tuple(load_cases.TABLE_COLUMNS[key])
    if key == fatigue_inputs.SPECTRUM_TABLE_KEY:
        return tuple(fatigue_inputs.SPECTRUM_COLUMNS)
    raise RuntimeError(f"unhandled project table {key}")


def _table_cell_kinds(
    key: str,
) -> tuple[set[str], set[str], set[str], set[str]]:
    """Return numeric, nullable-numeric, text and Boolean columns."""

    if key == "corners_base":
        return set(_GEOMETRY_COLUMNS), set(), set(), set()
    if key == "hole_base":
        return set(_GEOMETRY_COLUMNS), set(_GEOMETRY_COLUMNS), set(), set()
    if key in REINFORCEMENT_TABLE_KEYS:
        return (
            set(rebar_table.NUMERIC_COLUMNS),
            set(rebar_table.NUMERIC_COLUMNS),
            set(rebar_table.TEXT_COLUMNS),
            set(),
        )
    if key in CASE_TABLE_KEYS:
        return (
            set(load_cases.NUMERIC_COLUMNS[key]),
            # A wholly blank editor row is a supported transport state and is
            # removed by the canonical action-table validation below.
            set(load_cases.NUMERIC_COLUMNS[key]),
            set(load_cases.TEXT_COLUMNS[key]),
            set(load_cases.FLAG_COLUMNS[key]),
        )
    if key == fatigue_inputs.SPECTRUM_TABLE_KEY:
        return (
            set(fatigue_inputs.SPECTRUM_NUMERIC),
            # Same explicit blank-row allowance as the native spectrum editor.
            set(fatigue_inputs.SPECTRUM_NUMERIC),
            set(fatigue_inputs.SPECTRUM_TEXT),
            set(),
        )
    raise RuntimeError(f"unhandled project table {key}")


def _validated_table_rows(value, key: str) -> tuple[list[str], list[list]]:
    if not isinstance(value, Mapping):
        raise _invalid_input(f"{key} must be a table object")
    unknown = set(value) - {"columns", "rows"}
    if unknown:
        raise _invalid_input(f"{key} table contains unknown fields")
    columns = value.get("columns")
    rows = value.get("rows")
    expected = list(_expected_table_columns(key))
    if type(columns) is not list or columns != expected:
        raise _invalid_input(f"{key} table columns do not match the current format")
    if type(rows) is not list:
        raise _invalid_input(f"{key} table rows must be a list")

    numeric, nullable_numeric, text, boolean = _table_cell_kinds(key)
    validated_rows = []
    for row_number, row in enumerate(rows, start=1):
        if type(row) is not list or len(row) != len(columns):
            raise _invalid_input(
                f"{key} row {row_number} does not match the table columns"
            )
        validated = []
        for column, cell in zip(columns, row):
            label = f"{key} row {row_number} {column}"
            if column in numeric:
                if cell is None and column in nullable_numeric:
                    validated.append(None)
                    continue
                if (
                    key in (*CASE_TABLE_KEYS, fatigue_inputs.SPECTRUM_TABLE_KEY)
                    and (
                        type(cell) not in {int, float}
                        or isinstance(cell, bool)
                        or not math.isfinite(float(cell))
                    )
                ):
                    raise _invalid_input(
                        f"{key} row {row_number}: {column} contains malformed "
                        f"decimal input {cell!r}"
                    )
                validated.append(_strict_finite_real(cell, label))
                continue
            if column in boolean:
                if type(cell) is not bool:
                    raise _invalid_input(f"{label} must be a Boolean")
                validated.append(cell)
                continue
            if column in text:
                text_value = _strict_text(cell, label)
                if (
                    column in load_cases.PLASTIC_FACE_COLUMNS
                    and text_value not in load_cases.FACE_OPTIONS
                ):
                    raise _invalid_input(f"{label} is not a supported face")
                if (
                    column == rebar_table.SIZE_MODE
                    and text_value not in rebar_table.SIZE_MODES
                ):
                    raise _invalid_input(f"{label} is not a supported size mode")
                validated.append(text_value)
                continue
            raise RuntimeError(f"untyped project table column {key}.{column}")
        validated_rows.append(validated)
    return columns, validated_rows


def _obj_to_table(value, key: str) -> pd.DataFrame:
    columns, rows = _validated_table_rows(value, key)
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
    payload = _validated_scalar_payload(scalars)
    payload.setdefault(
        "torsion_design_basis",
        capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED,
    )
    payload.setdefault(
        "torsion_member_scope",
        capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED,
    )
    raw_case_authorities = payload.setdefault(
        capacity.TORSION_CASE_AUTHORITIES_KEY,
        {},
    )
    plastic_cases = load_cases.active_table(
        tables.get(load_cases.PLASTIC_TABLE_KEY),
        load_cases.PLASTIC_TABLE_KEY,
    )
    case_names = tuple(
        str(name).strip()
        for name in plastic_cases[load_cases.NAME].tolist()
        if str(name).strip()
    )
    # Project files from before this bounded contract have no per-case mapping.
    # Give every current Plastic row an explicit fail-closed entry, while pruning
    # renamed/deleted/orphaned names so old authority cannot silently reappear.
    payload[capacity.TORSION_CASE_AUTHORITIES_KEY] = {
        name: capacity.torsion_case_authority(raw_case_authorities, name)
        for name in case_names
    }
    try:
        plastic.plastic_sweep_angles(
            payload.get("v_min", 0.0),
            payload.get("v_max", 360.0),
            payload.get("v_inc", 15.0),
        )
    except plastic.PlasticSweepSpanError as exc:
        raise ProjectInputError(
            f"invalid neutral-axis sweep span: {exc}",
            engineer_message=_PROJECT_SWEEP_SPAN,
        ) from exc
    except plastic.PlasticSweepResolutionError as exc:
        raise ProjectInputError(
            f"invalid neutral-axis sweep resolution: {exc}",
            engineer_message=_PROJECT_SWEEP_RESOLUTION,
        ) from exc
    except (TypeError, ValueError, OverflowError) as exc:
        raise _invalid_input(f"invalid neutral-axis sweep: {exc}") from exc
    _validate_material_aliases(payload)
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
        raise ProjectInputError(
            f"unknown persisted report profile {value!r}",
            engineer_message=_PROJECT_REPORT_UNAVAILABLE,
        ) from exc


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


_RECORDED_VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9]+){1,3}")
_RECORDED_REVISION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,127}")
_PROVENANCE_FIELDS = frozenset({
    "sector_version",
    "source_revision",
    "saved_at_utc",
    "input_sha256",
    "results_included",
})
_CALCULATION_FIELDS = frozenset({
    "performed_at_utc",
    "sector_version",
    "source_revision",
    "input_sha256",
    "engineering_input_sha256",
    "result_sha256",
    "matches_saved_inputs",
})


def _valid_recorded_version(value) -> bool:
    return (
        type(value) is str
        and len(value) <= 64
        and _RECORDED_VERSION_RE.fullmatch(value) is not None
    )


def _valid_recorded_revision(value) -> bool:
    return (
        type(value) is str
        and _RECORDED_REVISION_RE.fullmatch(value) is not None
    )


def _parse_recorded_time(value) -> datetime | None:
    if type(value) is not str or not value or len(value) > 64:
        return None
    try:
        recorded = datetime.fromisoformat(value)
    except ValueError:
        return None
    if recorded.tzinfo is None or recorded.utcoffset() is None:
        return None
    return recorded.astimezone(timezone.utc)


def recorded_sector_version_label(value) -> str | None:
    """Return a display-safe recorded product version or no label."""

    return value if _valid_recorded_version(value) else None


def recorded_utc_label(value) -> str | None:
    """Return a display-safe UTC time without echoing an unvalidated value."""

    recorded = _parse_recorded_time(value)
    return recorded.strftime("%Y-%m-%d %H:%M UTC") if recorded else None


def _record_field_error(
    detail: str,
    *,
    engineer_message: EngineerMessage,
) -> ProjectInputError:
    return ProjectInputError(detail, engineer_message=engineer_message)


def _validated_recorded_time(
    value,
    label: str,
    *,
    engineer_message: EngineerMessage,
) -> str:
    recorded = _parse_recorded_time(value)
    if recorded is None:
        raise _record_field_error(
            f"{label} must be a timezone-aware ISO timestamp",
            engineer_message=engineer_message,
        )
    return recorded.isoformat(timespec="seconds")


def _validated_recorded_version(
    value,
    label: str,
    *,
    engineer_message: EngineerMessage,
) -> str:
    if not _valid_recorded_version(value):
        raise _record_field_error(
            f"{label} must be a product version",
            engineer_message=engineer_message,
        )
    return value


def _validated_recorded_revision(
    value,
    label: str,
    *,
    engineer_message: EngineerMessage,
) -> str:
    if not _valid_recorded_revision(value):
        raise _record_field_error(
            f"{label} must be a source revision token",
            engineer_message=engineer_message,
        )
    return value


def _validated_recorded_sha256(
    value,
    label: str,
    *,
    engineer_message: EngineerMessage,
) -> str:
    if not _valid_sha256(value):
        raise _record_field_error(
            f"{label} must be a lowercase SHA-256",
            engineer_message=engineer_message,
        )
    return value


def _validated_provenance_record(value: Mapping) -> dict:
    unknown = set(value) - _PROVENANCE_FIELDS
    if unknown:
        raise _record_field_error(
            "project provenance contains unknown fields",
            engineer_message=_PROJECT_DAMAGED,
        )
    record = {}
    if "sector_version" in value:
        record["sector_version"] = _validated_recorded_version(
            value["sector_version"],
            "project sector_version",
            engineer_message=_PROJECT_DAMAGED,
        )
    if "source_revision" in value:
        record["source_revision"] = _validated_recorded_revision(
            value["source_revision"],
            "project source_revision",
            engineer_message=_PROJECT_DAMAGED,
        )
    if "saved_at_utc" in value:
        record["saved_at_utc"] = _validated_recorded_time(
            value["saved_at_utc"],
            "project saved_at_utc",
            engineer_message=_PROJECT_DAMAGED,
        )
    if "input_sha256" in value:
        record["input_sha256"] = _validated_recorded_sha256(
            value["input_sha256"],
            "project input_sha256",
            engineer_message=_PROJECT_DAMAGED,
        )
    if "results_included" in value:
        if value["results_included"] is not False:
            raise _record_field_error(
                "project results_included must be false",
                engineer_message=_PROJECT_DAMAGED,
            )
        record["results_included"] = False
    return record


def _validated_calculation_record(value: Mapping, actual_input_sha256: str) -> dict:
    unknown = set(value) - _CALCULATION_FIELDS
    if unknown:
        raise _record_field_error(
            "calculation record contains unknown fields",
            engineer_message=_PROJECT_CALCULATION_DAMAGED,
        )
    record = {}
    if "performed_at_utc" in value:
        record["performed_at_utc"] = _validated_recorded_time(
            value["performed_at_utc"],
            "calculation performed_at_utc",
            engineer_message=_PROJECT_CALCULATION_DAMAGED,
        )
    if "sector_version" in value:
        record["sector_version"] = _validated_recorded_version(
            value["sector_version"],
            "calculation sector_version",
            engineer_message=_PROJECT_CALCULATION_DAMAGED,
        )
    if "source_revision" in value:
        record["source_revision"] = _validated_recorded_revision(
            value["source_revision"],
            "calculation source_revision",
            engineer_message=_PROJECT_CALCULATION_DAMAGED,
        )
    for key in ("input_sha256", "engineering_input_sha256", "result_sha256"):
        if key in value:
            record[key] = _validated_recorded_sha256(
                value[key],
                f"calculation {key}",
                engineer_message=_PROJECT_CALCULATION_DAMAGED,
            )
    if (
        "matches_saved_inputs" in value
        and type(value["matches_saved_inputs"]) is not bool
    ):
        raise _record_field_error(
            "calculation matches_saved_inputs must be a Boolean",
            engineer_message=_PROJECT_CALCULATION_DAMAGED,
        )
    record["matches_saved_inputs"] = (
        bool(record.get("input_sha256"))
        and record.get("input_sha256") == actual_input_sha256
    )
    return record


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
    app_version = _validated_recorded_version(
        app_version or sector_version,
        "project sector_version",
        engineer_message=_PROJECT_DAMAGED,
    )
    revision = _validated_recorded_revision(
        revision or source_revision(),
        "project source_revision",
        engineer_message=_PROJECT_DAMAGED,
    )
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
    if calculation is not None:
        if not isinstance(calculation, Mapping):
            raise _record_field_error(
                "calculation record must be an object",
                engineer_message=_PROJECT_CALCULATION_DAMAGED,
            )
        payload["calculation"] = _validated_calculation_record(
            {
                key: _json_value(value)
                for key, value in calculation.items()
                if value not in (None, "")
            },
            digest,
        )
    return json.dumps(payload, indent=2, ensure_ascii=True, allow_nan=False)


class _NonFiniteJsonConstant(ValueError):
    """One non-standard NaN/infinity token encountered during JSON decoding."""


def _reject_nonfinite_json_constant(value: str) -> None:
    raise _NonFiniteJsonConstant(value)


def _decode(text: str) -> dict:
    try:
        data = json.loads(
            text,
            parse_constant=_reject_nonfinite_json_constant,
        )
    except _NonFiniteJsonConstant as exc:
        raise ProjectInputError(
            "project contains a non-finite numeric value",
            engineer_message=_PROJECT_INVALID_INPUT,
        ) from exc
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProjectInputError(
            "not valid JSON",
            engineer_message=_PROJECT_UNREADABLE,
        ) from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ProjectInputError(
            "not a Sector project file",
            engineer_message=_PROJECT_UNREADABLE,
        )
    version = data.get("version")
    if version not in {*MIGRATABLE_VERSIONS, VERSION}:
        raise ProjectInputError(
            f"unsupported Sector project schema {version!r}; "
            f"only current schema {VERSION} and migrations from schemas "
            f"{LEGACY_MIGRATABLE_VERSION} and {MIGRATABLE_VERSION} are supported",
            engineer_message=_PROJECT_INCOMPATIBLE,
        )
    if not isinstance(data.get("tables"), Mapping):
        raise ProjectInputError(
            "malformed tables section",
            engineer_message=_PROJECT_DAMAGED,
        )
    if not isinstance(data.get("scalars"), Mapping):
        raise ProjectInputError(
            "malformed scalars section",
            engineer_message=_PROJECT_DAMAGED,
        )
    if not isinstance(data.get("presentation", {}), Mapping):
        raise ProjectInputError(
            "malformed presentation section",
            engineer_message=_PROJECT_DAMAGED,
        )
    if not isinstance(data.get("provenance"), Mapping):
        raise ProjectInputError(
            "missing project provenance",
            engineer_message=_PROJECT_DAMAGED,
        )
    return data


def engineer_error_message(error: Exception) -> str:
    """Publish authored project guidance and hide every other diagnostic."""

    return engineer_messages.error_detail(
        error,
        fallback=_PROJECT_READ_FALLBACK,
        context="project file",
    )


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
        raise ProjectInputError(
            "project inputs are not canonical JSON",
            engineer_message=_PROJECT_DAMAGED,
        ) from exc
    provenance = _validated_provenance_record(data["provenance"])
    recorded = provenance.get("input_sha256")
    calculation = None
    if "calculation" in data:
        if not isinstance(data["calculation"], Mapping):
            raise _record_field_error(
                "calculation record must be an object",
                engineer_message=_PROJECT_CALCULATION_DAMAGED,
            )
        calculation = _validated_calculation_record(
            data["calculation"],
            actual,
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
            "The older project file's permitted crack width must be positive "
            "when heightened crack control is enabled"
        )
    heightened = shared if heightened_enabled else 0.0
    warnings = (
        (
            "This project file used one permitted crack width for both ordinary "
            "durations. The value was copied to the independent "
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
                "the older heightened crack-control inputs do not identify one "
                "reference case; leave exactly one Elastic case crack-enabled, "
                "then load and review it"
            ) from exc
        migrated["sls_heightened_reference_case"] = reference
    warning = (
        "This older project file used one heightened crack-control system. Its "
        "effective tension area was copied to both the fine and coarse systems; "
        "diameter, reinforcement modulus and provided area now come from the "
        "selected ordinary crack-width case. Review both effective "
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
        raise ProjectInputError(
            "unknown current-schema presentation inputs: "
            + ", ".join(sorted(unknown_presentation)),
            engineer_message=_PROJECT_INCOMPATIBLE,
        )
    try:
        direction = modelled_direction.normalise_alias(
            raw_presentation.get(modelled_direction.ALIAS_KEY)
        )
    except ValueError as exc:
        raise ProjectInputError(
            "invalid modelled-direction description",
            engineer_message=_PROJECT_DIRECTION,
        ) from exc
    scalars[modelled_direction.ALIAS_KEY] = direction
    legacy_report_profile = raw_scalars.get(REPORT_PROFILE_KEY)
    current_report_profile = raw_presentation.get(REPORT_PROFILE_KEY)
    if current_report_profile is None:
        current_report_profile = legacy_report_profile
    elif legacy_report_profile is not None:
        if normalise_report_profile(current_report_profile) != (
            normalise_report_profile(legacy_report_profile)
        ):
            raise ProjectInputError(
                "conflicting report profiles in scalars and presentation",
                engineer_message=_PROJECT_REPORT_CONFLICT,
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
        raise ProjectInputError(
            "project input hash mismatch",
            engineer_message=_PROJECT_CHANGED,
        )
    unknown_tables = set(data["tables"]) - set(PROJECT_TABLE_KEYS)
    missing_tables = set(PROJECT_TABLE_KEYS) - set(data["tables"])
    if unknown_tables:
        raise ProjectInputError(
            "unknown current-schema tables: "
            + ", ".join(sorted(unknown_tables)),
            engineer_message=_PROJECT_INCOMPATIBLE,
        )
    if missing_tables:
        raise ProjectInputError(
            "missing current-schema tables: "
            + ", ".join(sorted(missing_tables)),
            engineer_message=_PROJECT_DAMAGED,
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
                capacity.TORSION_CASE_AUTHORITIES_KEY,
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
            raise ProjectInputError(
                "unknown schema-25 inputs: "
                + ", ".join(sorted(unknown_scalars)),
                engineer_message=_PROJECT_INCOMPATIBLE,
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
        )
        if gamma_v_active:
            migration_warnings = (
                *migration_warnings,
                "This project file used the fixed DS/EN 1992-1-1:2023 shear "
                "partial factor. The calculation now has an "
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
        allowed_schema26_scalars = set(SCALAR_KEYS) - {
            "shear_gamma_v",
            capacity.TORSION_CASE_AUTHORITIES_KEY,
        }
        unknown_scalars = (
            set(raw_scalars)
            - allowed_schema26_scalars
            - {REPORT_PROFILE_KEY}
        )
        if unknown_scalars:
            raise ProjectInputError(
                "unknown schema-26 inputs: "
                + ", ".join(sorted(unknown_scalars)),
                engineer_message=_PROJECT_INCOMPATIBLE,
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
        )
        if gamma_v_active:
            migration_warnings = (
                "This project file used the fixed DS/EN 1992-1-1:2023 shear "
                "partial factor. The calculation now has an "
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
            raise ProjectInputError(
                "unknown current-schema inputs: "
                + ", ".join(sorted(unknown_scalars)),
                engineer_message=_PROJECT_INCOMPATIBLE,
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


def project_upload_identity(content: bytes | bytearray | memoryview) -> str:
    """Return an identity derived exclusively from the uploaded raw bytes."""

    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise TypeError("project upload content must be bytes-like")
    return hashlib.sha256(bytes(content)).hexdigest()


def prepare_project_upload(
    content: bytes | bytearray | memoryview,
) -> PreparedProjectUpload:
    """Decode and fully validate one uploaded project without mutating app state."""

    raw = bytes(content)
    identity = project_upload_identity(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ProjectInputError(
            "project upload is not valid UTF-8",
            engineer_message=_PROJECT_UNREADABLE,
        ) from exc
    parse_project_with_info(text)
    return PreparedProjectUpload(content_identity=identity, text=text)
