"""Canonical user-defined Plastic and Elastic action tables.

A case name and description are user-controlled. The Elastic table retains the
sustained and instantaneous decomposition required by the combined creep solver.
Stresses are always calculation outputs; crack width is an optional numerical
calculation per Elastic action. No required combinations are inferred.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd

from app.table_field_definitions import (
    DecimalParseError,
    decimal_is_blank,
    decimal_issue_ledger,
    field_definition,
    invalid_decimal_sentinel,
    is_invalid_decimal_sentinel,
    parse_decimal,
    set_decimal_issue_ledger,
)

PLASTIC_TABLE_KEY = "plastic_cases_base"
ELASTIC_TABLE_KEY = "elastic_cases_base"
CASE_TABLE_KEYS = (PLASTIC_TABLE_KEY, ELASTIC_TABLE_KEY)

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
    "check_minimum_reinforcement",
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
    "calculate_crack_width",
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
    PLASTIC_TABLE_KEY: ("check_minimum_reinforcement",),
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


def _issue_text(value) -> str:
    """Short retained source text for one malformed numeric cell."""

    text = str(value).strip()
    return text[:160] or type(value).__name__


def _number(
    value,
    *,
    blank,
    prior_issue: str | None = None,
) -> tuple[float, str | None]:
    """Return a canonical number and optional malformed-source ledger entry."""

    if prior_issue and is_invalid_decimal_sentinel(value):
        return invalid_decimal_sentinel(), prior_issue
    if decimal_is_blank(value):
        try:
            number = parse_decimal(value, blank=blank)
        except DecimalParseError:
            # No load-case numeric field is currently required, but fail closed
            # if a future registry field adopts that policy.
            return math.nan, None
        return float(number), None
    try:
        number = parse_decimal(value, blank=blank)
    except DecimalParseError:
        return invalid_decimal_sentinel(), _issue_text(value)
    if number is None:  # pragma: no cover - no nullable load actions today
        return math.nan, None
    return float(number), None


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
    nonblank values remain invalid so :func:`validation_errors` can reject them
    before calculation.  A canonical frame carries an attrs ledger plus a tagged
    NaN sentinel: repeated validation retains malformed text, while replacing the
    cell with an ordinary editor NaN is a genuine clear and therefore becomes zero.
    """
    key = _kind(key)
    if value is None:
        return empty_table(key)
    canonical_source = bool(
        isinstance(value, pd.DataFrame)
        and value.attrs.get("sector_load_case_table") == key
        and tuple(value.columns) == TABLE_COLUMNS[key]
    )
    try:
        frame = value.copy(deep=True) if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} is not tabular") from exc
    frame = frame.reset_index(drop=True)
    prior_issues = decimal_issue_ledger(frame.attrs) if canonical_source else {}
    issues: dict[tuple[int, str], str] = {}
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
        blank = field_definition(key, column).blank
        values = []
        for position, value_at_position in enumerate(source.tolist()):
            number, issue = _number(
                value_at_position,
                blank=blank,
                prior_issue=prior_issues.get((position, column)),
            )
            values.append(number)
            if issue is not None:
                issues[(position, column)] = issue
        result[column] = pd.Series(values, index=frame.index, dtype="float64")
    for column in FLAG_COLUMNS[key]:
        source = frame[column] if column in frame else pd.Series(False, index=frame.index)
        result[column] = source.map(_flag).astype("bool")
    result = result.loc[:, TABLE_COLUMNS[key]].reset_index(drop=True)
    result.attrs["sector_load_case_table"] = key
    set_decimal_issue_ledger(result.attrs, issues)
    return result


def editor_table(value, key: str) -> pd.DataFrame:
    """Project canonical actions into lossless text-backed editor columns."""

    key = _kind(key)
    frame = normalise_table(value, key)
    display = frame.copy(deep=True)
    issues = decimal_issue_ledger(frame.attrs)
    for column in NUMERIC_COLUMNS[key]:
        values = []
        for position, value_at_position in enumerate(frame[column].tolist()):
            issue = issues.get((position, column))
            if issue is not None:
                values.append(issue)
                continue
            number = float(value_at_position)
            values.append(repr(number) if math.isfinite(number) else "")
        display[column] = pd.Series(
            values, index=display.index, dtype="string"
        )
    return display


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
    positions = [position for position, retained in enumerate(keep) if retained]
    active = frame.loc[keep].reset_index(drop=True)
    old_issues = decimal_issue_ledger(frame.attrs)
    new_issues = {
        (new_position, column): old_issues[(old_position, column)]
        for new_position, old_position in enumerate(positions)
        for column in NUMERIC_COLUMNS[key]
        if (old_position, column) in old_issues
    }
    active.attrs["sector_load_case_table"] = key
    set_decimal_issue_ledger(active.attrs, new_issues)
    return active


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


def default_tables() -> dict[str, pd.DataFrame]:
    """Build the app's initial one-row Plastic and Elastic tables."""
    plastic = normalise_table([{
        NAME: "PL-01",
        DESCRIPTION: "",
        "n_ed_kn": 0.0,
        "mx_ed_knm": 0.0,
        "my_ed_knm": 0.0,
        "vx_ed_kn": 0.0,
        "vy_ed_kn": 0.0,
        "vx_face": FACE_AUTO,
        "vy_face": FACE_AUTO,
        "t_ed_knm": 0.0,
    }], PLASTIC_TABLE_KEY)
    elastic = normalise_table([{
        NAME: "EL-01",
        DESCRIPTION: "",
        "n_long_ed_kn": 0.0,
        "mx_long_ed_knm": 0.0,
        "my_long_ed_knm": 0.0,
        "n_short_ed_kn": 0.0,
        "mx_short_ed_knm": 0.0,
        "my_short_ed_knm": 0.0,
        "calculate_crack_width": False,
    }], ELASTIC_TABLE_KEY)
    return {PLASTIC_TABLE_KEY: plastic, ELASTIC_TABLE_KEY: elastic}


def head_inputs(tables: Mapping | None) -> dict:
    """Map the first row of each table to the single-case calculation adapter."""
    tables = tables or {}
    defaults = default_tables()
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
        # Primary-direction projection for retained single-direction kernels.
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
        "sls_cw": bool(e["calculate_crack_width"]),
    }


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
