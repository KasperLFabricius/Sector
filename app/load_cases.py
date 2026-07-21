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

# Transitional scalar fields used by project versions 1-3 and by the current
# single-case controls while the table UI is introduced in stages.
LEGACY_SCALAR_KEYS = (
    "pl_case_id", "pl_case_type", "pl_case_source",
    "el_case_id", "el_case_type", "el_case_source",
    "pl_P", "pl_Mx", "pl_My", "shear_V", "torsion_T",
    "el_long_P", "el_long_Mx", "el_long_My",
    "el_short_P", "el_short_Mx", "el_short_My", "sls_cw",
)

NAME = "name"
DESCRIPTION = "description"

PLASTIC_COLUMNS = (
    NAME,
    DESCRIPTION,
    "n_ed_kn",
    "mx_ed_knm",
    "my_ed_knm",
    "v_ed_kn",
    "t_ed_knm",
)
PLASTIC_NUMERIC = PLASTIC_COLUMNS[2:]

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


def empty_table(key: str) -> pd.DataFrame:
    """Return an empty table with stable text, numeric and boolean dtypes."""
    key = _kind(key)
    data = {
        NAME: pd.Series(dtype="string"),
        DESCRIPTION: pd.Series(dtype="string"),
    }
    data.update({column: pd.Series(dtype="float64")
                 for column in NUMERIC_COLUMNS[key]})
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

    result = pd.DataFrame(index=frame.index)
    for column in (NAME, DESCRIPTION):
        source = frame[column] if column in frame else pd.Series("", index=frame.index)
        result[column] = source.map(_text).astype("string")
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
        record = {NAME: _text(row[NAME]), DESCRIPTION: _text(row[DESCRIPTION])}
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
    stress_enabled = any(
        _number(scalars.get(key, 0.0)) > 0.0
        for key in (
            "sls_conc_limit_pct",
            "sls_steel_limit_pct",
            "sls_pre_limit_pct",
        )
    )
    plastic = normalise_table([{
        NAME: _text(scalars.get("pl_case_id")) or "PL-01",
        DESCRIPTION: _description(
            scalars.get("pl_case_type"), scalars.get("pl_case_source")
        ),
        "n_ed_kn": _number(scalars.get("pl_P", 0.0)),
        "mx_ed_knm": _number(scalars.get("pl_Mx", 0.0)),
        "my_ed_knm": _number(scalars.get("pl_My", 0.0)),
        "v_ed_kn": _number(scalars.get("shear_V", 0.0)),
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
    """Expose the first row through the former scalar API during migration.

    This compatibility adapter is intentionally one-way: the final table UI uses
    ``description`` directly, while a pre-table panel receives it in its optional
    classification field. No description text is lost.
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
        "shear_V": float(p["v_ed_kn"]),
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
    frame = normalise_table(value, key)
    legacy = tables_from_legacy_scalars(scalars)[key].iloc[0]
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
    return errors
