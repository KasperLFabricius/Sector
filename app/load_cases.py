"""Canonical load-case tables shared by the UI and project-file migration.

The current application historically stores one Plastic and one Elastic action
set as individual Streamlit scalar keys.  The multi-case workflow uses two
typed tables instead.  This module owns that boundary so project I/O, the UI and
the calculation orchestration do not each invent subtly different column names,
defaults or validation rules.

The table model deliberately describes solver methodologies, not imposed limit
states.  A case name and description are project-defined.  Section forces use a
consistent ``*_Ed`` vocabulary; the Elastic table retains the existing sustained
and instantaneous decomposition needed by the combined creep solver.  Stress and
crack-width acceptance are selected per Elastic case while their numerical limits
remain global inputs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd


PLASTIC_TABLE_KEY = "plastic_cases_base"
ELASTIC_TABLE_KEY = "elastic_cases_base"
CASE_TABLE_KEYS = (PLASTIC_TABLE_KEY, ELASTIC_TABLE_KEY)

# Historical scalar fields used by project versions 1-3. They remain here only
# for lossless migration into the canonical load-case tables.
LEGACY_SCALAR_KEYS = (
    "pl_case_id", "pl_case_type", "pl_case_source",
    "el_case_id", "el_case_type", "el_case_source",
    "pl_P", "pl_Mx", "pl_My", "shear_V", "torsion_T",
    "el_long_P", "el_long_Mx", "el_long_My",
    "el_short_P", "el_short_Mx", "el_short_My", "sls_cw",
)

NAME = "name"
DESCRIPTION = "description"

# The stored values are deliberately coordinate-neutral.  The UI presents the
# matching physical face for each component (Vx: left/right; Vy: bottom/top).
FACE_AUTO = "auto"
FACE_NEGATIVE = "negative"
FACE_POSITIVE = "positive"
FACE_OPTIONS = (FACE_AUTO, FACE_NEGATIVE, FACE_POSITIVE)
PLASTIC_FACE_COLUMNS = ("vx_face", "vy_face")

PLASTIC_COLUMNS = (
    NAME,
    DESCRIPTION,
    "n_ed_kn",
    "mx_ed_knm",
    "my_ed_knm",
    "vx_ed_kn",
    "vy_ed_kn",
    *PLASTIC_FACE_COLUMNS,
    "t_ed_knm",
)
PLASTIC_NUMERIC = (
    "n_ed_kn",
    "mx_ed_knm",
    "my_ed_knm",
    "vx_ed_kn",
    "vy_ed_kn",
    "t_ed_knm",
)

ELASTIC_COLUMNS = (
    NAME,
    DESCRIPTION,
    "n_long_ed_kn",
    "mx_long_ed_knm",
    "my_long_ed_knm",
    "n_short_ed_kn",
    "mx_short_ed_knm",
    "my_short_ed_knm",
    "check_stress",
    "check_crack_width",
)
ELASTIC_NUMERIC = ELASTIC_COLUMNS[2:8]
ELASTIC_FLAGS = ELASTIC_COLUMNS[8:]

TABLE_COLUMNS = {
    PLASTIC_TABLE_KEY: PLASTIC_COLUMNS,
    ELASTIC_TABLE_KEY: ELASTIC_COLUMNS,
}
NUMERIC_COLUMNS = {
    PLASTIC_TABLE_KEY: PLASTIC_NUMERIC,
    ELASTIC_TABLE_KEY: ELASTIC_NUMERIC,
}
FLAG_COLUMNS = {
    PLASTIC_TABLE_KEY: (),
    ELASTIC_TABLE_KEY: ELASTIC_FLAGS,
}
TEXT_COLUMNS = {
    PLASTIC_TABLE_KEY: (NAME, DESCRIPTION, *PLASTIC_FACE_COLUMNS),
    ELASTIC_TABLE_KEY: (NAME, DESCRIPTION),
}


def _kind(key: str) -> str:
    if key not in CASE_TABLE_KEYS:
        raise ValueError(f"unknown load-case table: {key}")
    return key


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _number(value) -> float:
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0.0
    try:
        if pd.isna(value):
            return 0.0
    except (TypeError, ValueError):
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    try:
        return bool(value) if not pd.isna(value) else False
    except (TypeError, ValueError):
        return False


def _face(value) -> str:
    """Return a canonical face token while retaining invalid text for validation."""
    if isinstance(value, bool):
        return FACE_NEGATIVE if value else FACE_POSITIVE
    text = _text(value).casefold()
    if not text or text == FACE_AUTO:
        return FACE_AUTO
    if text in {
        FACE_NEGATIVE, "low", "lower", "bottom", "left",
        "bottom / left face", "negative-coordinate face", "true", "1",
    }:
        return FACE_NEGATIVE
    if text in {
        FACE_POSITIVE, "high", "upper", "top", "right",
        "top / right face", "positive-coordinate face", "false", "0",
    }:
        return FACE_POSITIVE
    return _text(value)


def legacy_shear_component(axis) -> str:
    """Map the former shear-axis selection to ``vx`` or ``vy``.

    The historical internal axis named the bending axis: ``x`` meant vertical
    shear and therefore maps to Vy; ``y`` meant horizontal shear and maps to Vx.
    UI-label variants are accepted because project files persist widget values.
    """
    text = _text(axis).casefold()
    if text == "y" or "horizontal" in text or "about y" in text:
        return "vx"
    return "vy"


def migrate_legacy_plastic_records(records, *, axis=None, tension=None) -> list[dict]:
    """Convert v4-v6 one-direction plastic rows to the directional schema."""
    component = legacy_shear_component(axis)
    face = _face(FACE_NEGATIVE if tension is None else tension)
    migrated = []
    for source in records or []:
        row = dict(source)
        if "vx_ed_kn" not in row and "vy_ed_kn" not in row:
            v_ed = row.pop("v_ed_kn", 0.0)
            row["vx_ed_kn"] = v_ed if component == "vx" else 0.0
            row["vy_ed_kn"] = v_ed if component == "vy" else 0.0
        row.setdefault(
            "vx_face", face if component == "vx" else FACE_AUTO
        )
        row.setdefault(
            "vy_face", face if component == "vy" else FACE_AUTO
        )
        migrated.append(row)
    return migrated


def empty_table(key: str) -> pd.DataFrame:
    """Return an empty table with stable text, numeric and boolean dtypes."""
    key = _kind(key)
    data = {
        NAME: pd.Series(dtype="string"),
        DESCRIPTION: pd.Series(dtype="string"),
    }
    data.update({column: pd.Series(dtype="float64")
                 for column in NUMERIC_COLUMNS[key]})
    for column in TEXT_COLUMNS[key]:
        data.setdefault(column, pd.Series(dtype="string"))
    data.update({column: pd.Series(dtype="bool")
                 for column in FLAG_COLUMNS[key]})
    frame = pd.DataFrame(data, columns=TABLE_COLUMNS[key])
    frame.attrs["sector_load_case_table"] = key
    return frame


def normalise_table(value, key: str) -> pd.DataFrame:
    """Coerce a table-like value to the canonical columns and dtypes.

    Unknown columns are discarded. Blank force cells become zero; invalid
    nonblank values remain NaN so :func:`validation_errors` can reject them before
    calculation. Canonical frames retain NaN sentinels across repeated validation.
    """
    key = _kind(key)
    if value is None:
        return empty_table(key)
    if (
        isinstance(value, pd.DataFrame)
        and value.attrs.get("sector_load_case_table") == key
        and tuple(value.columns) == TABLE_COLUMNS[key]
    ):
        return value.copy(deep=True).reset_index(drop=True)
    try:
        frame = value.copy(deep=True) if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} is not tabular") from exc
    # Programmatic callers may still supply the former one-direction column. A
    # project file uses the axis-aware v7 migration; without that metadata the
    # historical/default vertical direction is the only deterministic mapping.
    if (
        key == PLASTIC_TABLE_KEY
        and "v_ed_kn" in frame
        and "vx_ed_kn" not in frame
        and "vy_ed_kn" not in frame
    ):
        frame["vy_ed_kn"] = frame["v_ed_kn"]

    result = pd.DataFrame(index=frame.index)
    for column in TEXT_COLUMNS[key]:
        default = FACE_AUTO if column in PLASTIC_FACE_COLUMNS else ""
        source = (
            frame[column]
            if column in frame
            else pd.Series(default, index=frame.index)
        )
        mapper = _face if column in PLASTIC_FACE_COLUMNS else _text
        result[column] = source.map(mapper).astype("string")
    for column in NUMERIC_COLUMNS[key]:
        source = frame[column] if column in frame else pd.Series(0.0, index=frame.index)
        result[column] = source.map(_number).astype("float64")
    for column in FLAG_COLUMNS[key]:
        source = frame[column] if column in frame else pd.Series(False, index=frame.index)
        result[column] = source.map(_flag).astype("bool")
    result = result.loc[:, TABLE_COLUMNS[key]].reset_index(drop=True)
    result.attrs["sector_load_case_table"] = key
    return result


def _row_is_blank(row: Mapping, key: str) -> bool:
    def _is_finite_zero(value) -> bool:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(number) and number == 0.0

    return bool(
        not _text(row.get(NAME))
        and not _text(row.get(DESCRIPTION))
        and all(_is_finite_zero(row.get(column))
                for column in NUMERIC_COLUMNS[key])
        and all(_face(row.get(column)) == FACE_AUTO
                for column in PLASTIC_FACE_COLUMNS if column in TABLE_COLUMNS[key])
        and not any(_flag(row.get(column)) for column in FLAG_COLUMNS[key])
    )


def active_table(value, key: str) -> pd.DataFrame:
    """Return canonical nonblank rows, retaining their user-facing order."""
    frame = normalise_table(value, key)
    keep = [not _row_is_blank(row, key) for row in frame.to_dict("records")]
    return frame.loc[keep].reset_index(drop=True)


def table_records(value, key: str) -> list[dict]:
    """Return strict-JSON-safe records for one canonical case table.

    An invalid active force is rejected rather than converted to a JSON blank:
    blanks intentionally reload as zero, so that conversion would silently alter
    the action and invalidate the recorded project-input hash.
    """
    frame = active_table(value, key)
    records = []
    for row_number, row in enumerate(frame.to_dict("records"), start=1):
        record = {
            column: (
                _face(row[column])
                if column in PLASTIC_FACE_COLUMNS else _text(row[column])
            )
            for column in TEXT_COLUMNS[key]
        }
        for column in PLASTIC_FACE_COLUMNS:
            if column in record and record[column] not in FACE_OPTIONS:
                raise ValueError(
                    f"{key} row {row_number}: {column} must be auto, "
                    "negative or positive"
                )
        for column in NUMERIC_COLUMNS[key]:
            try:
                number = float(row[column])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{key} row {row_number}: {column} must be a finite number"
                ) from exc
            if not math.isfinite(number):
                raise ValueError(
                    f"{key} row {row_number}: {column} must be a finite number"
                )
            record[column] = number
        record.update({column: _flag(row[column]) for column in FLAG_COLUMNS[key]})
        records.append(record)
    return records


def table_from_records(records, key: str) -> pd.DataFrame:
    """Read a JSON load-case list into a canonical DataFrame."""
    if records is None:
        return empty_table(key)
    if not isinstance(records, list) or any(not isinstance(row, Mapping) for row in records):
        raise ValueError(f"{key} is not a list of row objects")
    return normalise_table(records, key)


def _description(classification, source) -> str:
    classification = _text(classification)
    source = _text(source)
    if classification and source:
        return f"{classification} | Source: {source}"
    if source:
        return f"Source: {source}"
    return classification


def tables_from_legacy_scalars(scalars: Mapping | None) -> dict[str, pd.DataFrame]:
    """Migrate the former single-action scalar fields to one row per solver."""
    scalars = scalars or {}
    stress_keys = (
        "sls_conc_limit_pct",
        "sls_steel_limit_pct",
        "sls_pre_limit_pct",
    )
    supplied_limits = [scalars[key] for key in stress_keys if key in scalars]
    # Before per-case flags, stress acceptance was always active whenever the
    # applicable global limit was nonzero. Preserve that behaviour for default and
    # historical rows; an explicit set of all-zero legacy limits remains off.
    stress_enabled = (
        True
        if not supplied_limits
        else any(_number(value) > 0.0 for value in supplied_limits)
    )
    shear_component = legacy_shear_component(scalars.get("shear_axis"))
    legacy_v = _number(scalars.get("shear_V", 0.0))
    # A new table defaults to automatic face selection. Project I/O supplies the
    # historical negative-face default explicitly when migrating pre-v7 scalars.
    default_face = FACE_NEGATIVE if "shear_V" in scalars else FACE_AUTO
    legacy_face = _face(scalars.get("shear_tension", default_face))
    plastic = normalise_table([{
        NAME: _text(scalars.get("pl_case_id")) or "PL-01",
        DESCRIPTION: _description(
            scalars.get("pl_case_type"), scalars.get("pl_case_source")
        ),
        "n_ed_kn": _number(scalars.get("pl_P", 0.0)),
        "mx_ed_knm": _number(scalars.get("pl_Mx", 0.0)),
        "my_ed_knm": _number(scalars.get("pl_My", 0.0)),
        "vx_ed_kn": legacy_v if shear_component == "vx" else 0.0,
        "vy_ed_kn": legacy_v if shear_component == "vy" else 0.0,
        "vx_face": legacy_face if shear_component == "vx" else FACE_AUTO,
        "vy_face": legacy_face if shear_component == "vy" else FACE_AUTO,
        "t_ed_knm": _number(scalars.get("torsion_T", 0.0)),
    }], PLASTIC_TABLE_KEY)
    elastic = normalise_table([{
        NAME: _text(scalars.get("el_case_id")) or "EL-01",
        DESCRIPTION: _description(
            scalars.get("el_case_type"), scalars.get("el_case_source")
        ),
        "n_long_ed_kn": _number(scalars.get("el_long_P", 0.0)),
        "mx_long_ed_knm": _number(scalars.get("el_long_Mx", 0.0)),
        "my_long_ed_knm": _number(scalars.get("el_long_My", 0.0)),
        "n_short_ed_kn": _number(scalars.get("el_short_P", 0.0)),
        "mx_short_ed_knm": _number(scalars.get("el_short_Mx", 0.0)),
        "my_short_ed_knm": _number(scalars.get("el_short_My", 0.0)),
        "check_stress": stress_enabled,
        "check_crack_width": _flag(scalars.get("sls_cw", False)),
    }], ELASTIC_TABLE_KEY)
    return {PLASTIC_TABLE_KEY: plastic, ELASTIC_TABLE_KEY: elastic}


def legacy_scalars_from_tables(tables: Mapping | None) -> dict:
    """Expose the first row through the verified single-case compatibility API.

    The table UI remains authoritative. A few older callers still consume the
    first row through scalar names; ``description`` is retained losslessly.
    """
    tables = tables or {}
    defaults = tables_from_legacy_scalars({})
    plastic = active_table(
        tables.get(PLASTIC_TABLE_KEY, defaults[PLASTIC_TABLE_KEY]),
        PLASTIC_TABLE_KEY,
    )
    elastic = active_table(
        tables.get(ELASTIC_TABLE_KEY, defaults[ELASTIC_TABLE_KEY]),
        ELASTIC_TABLE_KEY,
    )
    p = plastic.iloc[0] if not plastic.empty else defaults[PLASTIC_TABLE_KEY].iloc[0]
    e = elastic.iloc[0] if not elastic.empty else defaults[ELASTIC_TABLE_KEY].iloc[0]
    return {
        "pl_case_id": _text(p[NAME]),
        "pl_case_type": _text(p[DESCRIPTION]),
        "pl_case_source": "",
        "pl_P": float(p["n_ed_kn"]),
        "pl_Mx": float(p["mx_ed_knm"]),
        "pl_My": float(p["my_ed_knm"]),
        # Compatibility only: new calculations consume both directional fields.
        # Prefer the historical default Vy when both happen to be populated.
        "shear_V": float(
            p["vy_ed_kn"] if float(p["vy_ed_kn"]) != 0.0 else p["vx_ed_kn"]
        ),
        "shear_Vx": float(p["vx_ed_kn"]),
        "shear_Vy": float(p["vy_ed_kn"]),
        "torsion_T": float(p["t_ed_knm"]),
        "el_case_id": _text(e[NAME]),
        "el_case_type": _text(e[DESCRIPTION]),
        "el_case_source": "",
        "el_long_P": float(e["n_long_ed_kn"]),
        "el_long_Mx": float(e["mx_long_ed_knm"]),
        "el_long_My": float(e["my_long_ed_knm"]),
        "el_short_P": float(e["n_short_ed_kn"]),
        "el_short_Mx": float(e["mx_short_ed_knm"]),
        "el_short_My": float(e["my_short_ed_knm"]),
        "sls_cw": bool(e["check_crack_width"]),
    }


def overlay_legacy_head(value, key: str, scalars: Mapping | None) -> pd.DataFrame:
    """Update only the first migrated row while preserving any later rows."""
    key = _kind(key)
    scalars = scalars or {}
    frame = normalise_table(value, key)
    legacy = tables_from_legacy_scalars(scalars)[key].iloc[0].copy()
    # Migration defaults a genuinely absent historical identifier to PL/EL-01.
    # A mounted text widget is different: if its key is present and the engineer
    # deliberately clears it, preserve the blank so required-name validation can
    # block calculation instead of silently restoring a default.
    name_key = "pl_case_id" if key == PLASTIC_TABLE_KEY else "el_case_id"
    if name_key in scalars:
        legacy[NAME] = _text(scalars.get(name_key))
    if frame.empty:
        return normalise_table([legacy.to_dict()], key)
    for column in TABLE_COLUMNS[key]:
        frame.at[0, column] = legacy[column]
    return normalise_table(frame, key)


def validation_errors(plastic, elastic, *, require_plastic=False,
                      require_elastic=False) -> list[str]:
    """Return deterministic table errors, including global name uniqueness."""
    tables = {
        PLASTIC_TABLE_KEY: active_table(plastic, PLASTIC_TABLE_KEY),
        ELASTIC_TABLE_KEY: active_table(elastic, ELASTIC_TABLE_KEY),
    }
    errors = []
    if require_plastic and tables[PLASTIC_TABLE_KEY].empty:
        errors.append("At least one Plastic case is required")
    if require_elastic and tables[ELASTIC_TABLE_KEY].empty:
        errors.append("At least one Elastic case is required")

    seen = {}
    for key, label in (
        (PLASTIC_TABLE_KEY, "Plastic"),
        (ELASTIC_TABLE_KEY, "Elastic"),
    ):
        for index, row in tables[key].iterrows():
            number = index + 1
            name = _text(row[NAME])
            if not name:
                errors.append(f"{label} row {number}: Name is required")
            else:
                folded = name.casefold()
                if folded in seen:
                    errors.append(
                        f"Case name '{name}' is duplicated; names must be unique "
                        f"across Plastic and Elastic tables"
                    )
                else:
                    seen[folded] = (label, number)
            for column in NUMERIC_COLUMNS[key]:
                if not math.isfinite(float(row[column])):
                    errors.append(
                        f"{label} row {number}: {column} must be a finite number"
                    )
            if key == PLASTIC_TABLE_KEY:
                for column in PLASTIC_FACE_COLUMNS:
                    if _face(row[column]) not in FACE_OPTIONS:
                        errors.append(
                            f"{label} row {number}: {column} must be auto, "
                            "negative or positive"
                        )
    return errors
