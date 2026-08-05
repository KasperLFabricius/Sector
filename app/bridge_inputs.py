"""Typed tables for the optional independent bridge calculations."""

from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Complex, Real

import pandas as pd

from sector import bridge


BRITTLE_TABLE_KEY = "bridge_brittle_base"
BOX_WALL_TABLE_KEY = "bridge_box_walls_base"
MINIMUM_CRACK_TABLE_KEY = "bridge_minimum_crack_base"
TABLE_KEYS = (
    BRITTLE_TABLE_KEY,
    BOX_WALL_TABLE_KEY,
    MINIMUM_CRACK_TABLE_KEY,
)
_INVALID_CELL_TAG = "__sector_bridge_invalid_cell_v1__"

TABLE_COLUMNS = {
    BRITTLE_TABLE_KEY: (
        "region_id",
        "m_rep_knm",
        "z_s_m",
        "f_yk_mpa",
        "as_provided_mm2",
    ),
    BOX_WALL_TABLE_KEY: (
        "wall_id",
        "cot_theta",
        "v_ed_kn",
        "v_rd_max_kn",
        "t_ed_equivalent_kn",
        "t_rd_max_equivalent_kn",
    ),
    MINIMUM_CRACK_TABLE_KEY: (
        "component",
        "act_mm2",
        "k_c",
        "k",
        "fct_eff_mpa",
        "sigma_s_mpa",
        "as_provided_mm2",
        "restrained_shrinkage",
    ),
}
TEXT_COLUMNS = {
    BRITTLE_TABLE_KEY: ("region_id",),
    BOX_WALL_TABLE_KEY: ("wall_id",),
    MINIMUM_CRACK_TABLE_KEY: ("component",),
}
BOOLEAN_COLUMNS = {
    BRITTLE_TABLE_KEY: (),
    BOX_WALL_TABLE_KEY: (),
    MINIMUM_CRACK_TABLE_KEY: ("restrained_shrinkage",),
}
NUMERIC_COLUMNS = {
    key: tuple(
        column
        for column in columns
        if column not in TEXT_COLUMNS[key]
        and column not in BOOLEAN_COLUMNS[key]
    )
    for key, columns in TABLE_COLUMNS.items()
}


def _key(key: str) -> str:
    if key not in TABLE_KEYS:
        raise ValueError(f"unknown bridge table: {key}")
    return key


def _missing(value) -> bool:
    """Return true only for scalar blank values accepted by the table UI."""
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    if missing is pd.NA:
        return True
    if isinstance(missing, bool):
        return missing
    if getattr(missing, "ndim", 1) != 0:
        return False
    try:
        return bool(missing)
    except (TypeError, ValueError):
        return False


def _encoded_invalid_identity(value):
    if type(value) is not dict or set(value) != {_INVALID_CELL_TAG}:
        return None
    payload = value[_INVALID_CELL_TAG]
    if type(payload) is not dict or set(payload) != {
        "type",
        "representation",
    }:
        return None
    type_name = payload["type"]
    representation = payload["representation"]
    if not isinstance(type_name, str) or not isinstance(representation, str):
        return None
    return type_name, representation


def _encoded_invalid_cell(type_name: str, representation: str) -> dict:
    return {
        _INVALID_CELL_TAG: {
            "type": type_name,
            "representation": representation,
        }
    }


def _invalid_identity(value) -> tuple[str, str]:
    encoded = _encoded_invalid_identity(value)
    if encoded is not None:
        return encoded
    type_name = f"{type(value).__module__}.{type(value).__qualname__}"
    if (
        not isinstance(value, (bool, str))
        and not (isinstance(value, Complex) and not isinstance(value, Real))
    ):
        try:
            number = float(value)
        except (TypeError, ValueError):
            pass
        else:
            if not math.isfinite(number):
                return type_name, (
                    "not_a_number"
                    if math.isnan(number)
                    else (
                        "positive_infinity"
                        if number > 0.0
                        else "negative_infinity"
                    )
                )
    return type_name, repr(value)


def _text(value) -> str:
    if _missing(value):
        return ""
    return str(value).strip()


def _number(value):
    if (
        isinstance(value, (bool, str))
        or _encoded_invalid_identity(value) is not None
        or (isinstance(value, Complex) and not isinstance(value, Real))
    ):
        return math.nan
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _flag(value) -> bool:
    return value if isinstance(value, bool) else False


def _raw_number(value):
    if _missing(value):
        return math.nan
    encoded = _encoded_invalid_identity(value)
    if encoded is not None:
        return _encoded_invalid_cell(*encoded)
    if isinstance(value, (bool, str)):
        return value
    if isinstance(value, Complex) and not isinstance(value, Real):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return number if math.isfinite(number) else value


def _raw_flag(value):
    if _missing(value):
        return False
    encoded = _encoded_invalid_identity(value)
    return _encoded_invalid_cell(*encoded) if encoded is not None else value


def _frame(value, key: str) -> pd.DataFrame:
    if value is None:
        return empty_table(key)
    try:
        frame = (
            value.copy(deep=True)
            if isinstance(value, pd.DataFrame)
            else pd.DataFrame(value)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be tabular") from exc
    if bool(frame.columns.duplicated().any()):
        raise ValueError(f"{key} contains duplicate columns")
    return frame


def empty_table(key: str) -> pd.DataFrame:
    key = _key(key)
    data = {
        column: pd.Series(dtype=(
            "string"
            if column in TEXT_COLUMNS[key]
            else (
                "bool"
                if column in BOOLEAN_COLUMNS[key]
                else "float64"
            )
        ))
        for column in TABLE_COLUMNS[key]
    }
    return pd.DataFrame(data)


def normalise_table(value, key: str) -> pd.DataFrame:
    key = _key(key)
    frame = _frame(value, key)
    result = pd.DataFrame(index=frame.index)
    for column in TABLE_COLUMNS[key]:
        source = (
            frame[column]
            if column in frame
            else pd.Series(
                False if column in BOOLEAN_COLUMNS[key] else "",
                index=frame.index,
            )
        )
        if column in TEXT_COLUMNS[key]:
            result[column] = source.map(_text).astype("string")
        elif column in BOOLEAN_COLUMNS[key]:
            flags = source.map(_raw_flag)
            if all(type(item) is bool for item in flags.astype(object).tolist()):
                result[column] = flags.astype("bool")
            else:
                result[column] = flags.astype("object")
        else:
            result[column] = source.map(_raw_number)
    return result.loc[:, TABLE_COLUMNS[key]].reset_index(drop=True)


def _blank(record: Mapping, key: str) -> bool:
    return (
        all(not _text(record.get(column)) for column in TEXT_COLUMNS[key])
        and all(
            _missing(record.get(column))
            for column in NUMERIC_COLUMNS[key]
        )
        and all(
            _missing(record.get(column)) or record.get(column) is False
            for column in BOOLEAN_COLUMNS[key]
        )
    )


def records(value, key: str) -> list[dict]:
    key = _key(key)
    rows = []
    for number, record in enumerate(
        normalise_table(value, key).to_dict("records"),
        start=1,
    ):
        if _blank(record, key):
            continue
        for column in NUMERIC_COLUMNS[key]:
            value_number = _number(record[column])
            if not math.isfinite(value_number):
                raise ValueError(
                    f"{key} row {number}: {column} must be finite numeric"
                )
            record[column] = value_number
        for column in BOOLEAN_COLUMNS[key]:
            if type(record[column]) is not bool:
                raise ValueError(
                    f"{key} row {number}: {column} must be Boolean"
                )
        if key == MINIMUM_CRACK_TABLE_KEY:
            component = _text(record["component"]).casefold()
            if component not in {"web", "flange"}:
                raise ValueError(
                    f"{key} row {number}: component must be Web or Flange"
                )
            record["component"] = component
        rows.append({
            column: (
                _text(record[column])
                if column in TEXT_COLUMNS[key]
                else (
                    bool(record[column])
                    if column in BOOLEAN_COLUMNS[key]
                    else float(record[column])
                )
            )
            for column in TABLE_COLUMNS[key]
        })
    return rows


def table_signature(value, key: str) -> tuple:
    """Return stable identity for valid, missing, and retained invalid cells."""
    key = _key(key)
    frame = normalise_table(value, key)
    rows = []
    for record in frame.to_dict("records"):
        row = []
        for column in TABLE_COLUMNS[key]:
            cell = record[column]
            if column in TEXT_COLUMNS[key]:
                row.append(_text(cell))
            elif column in BOOLEAN_COLUMNS[key]:
                row.append(
                    cell
                    if type(cell) is bool
                    else ("<invalid>", *_invalid_identity(cell))
                )
            elif _missing(cell):
                row.append("<invalid>")
            else:
                number = _number(cell)
                row.append(
                    number
                    if math.isfinite(number)
                    else ("<invalid>", *_invalid_identity(cell))
                )
        rows.append(tuple(row))
    return tuple(rows)


def project_cell(value, key: str, column: str):
    """Encode one normalized bridge cell as strict canonical JSON data."""
    key = _key(key)
    if column not in TABLE_COLUMNS[key]:
        raise ValueError(f"unknown {key} column: {column}")
    if column in TEXT_COLUMNS[key]:
        return _text(value)
    if _missing(value):
        return False if column in BOOLEAN_COLUMNS[key] else None
    encoded = _encoded_invalid_identity(value)
    if encoded is not None:
        return _encoded_invalid_cell(*encoded)
    if column in NUMERIC_COLUMNS[key]:
        number = _number(value)
        if math.isfinite(number):
            return number
    elif type(value) is bool:
        return value
    if (
        type(value) in {bool, int, float, str}
        and (type(value) is not float or math.isfinite(value))
    ):
        return value
    return _encoded_invalid_cell(*_invalid_identity(value))


def table_from_records(value, key: str) -> pd.DataFrame:
    if value is None:
        return empty_table(key)
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{key} must be a list of row objects")
    return normalise_table(value, key)


def calculate(tables: Mapping, *, standard: str) -> dict:
    """Calculate every enabled optional bridge table."""
    out = {}
    brittle_rows = records(tables.get(BRITTLE_TABLE_KEY), BRITTLE_TABLE_KEY)
    if brittle_rows:
        out["brittle_method_b"] = bridge.calculate_brittle_method_b(
            (bridge.PrestressBrittleRegion(**row) for row in brittle_rows),
            selected_standard=standard,
        )
    wall_rows = records(tables.get(BOX_WALL_TABLE_KEY), BOX_WALL_TABLE_KEY)
    if wall_rows:
        out["box_walls"] = bridge.calculate_box_walls(
            bridge.BoxWall(**row) for row in wall_rows
        )
    minimum_rows = records(
        tables.get(MINIMUM_CRACK_TABLE_KEY),
        MINIMUM_CRACK_TABLE_KEY,
    )
    if minimum_rows:
        out["minimum_crack_reinforcement"] = (
            bridge.calculate_minimum_crack_reinforcement(
                bridge.MinimumCrackComponent(**row) for row in minimum_rows
            )
        )
    return out
