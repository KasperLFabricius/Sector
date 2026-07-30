"""Typed tables for the optional independent bridge calculations."""

from __future__ import annotations

import math
from collections.abc import Mapping

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


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        return ""
    return str(value).strip()


def _number(value):
    if isinstance(value, bool) or isinstance(value, str):
        return math.nan
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _flag(value) -> bool:
    return value if isinstance(value, bool) else False


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
    if value is None:
        return empty_table(key)
    frame = value.copy(deep=True) if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
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
            result[column] = source.map(_flag).astype("bool")
        else:
            result[column] = source.map(_number).astype("float64")
    return result.reset_index(drop=True)


def _blank(record: Mapping, key: str) -> bool:
    return (
        all(not _text(record.get(column)) for column in TEXT_COLUMNS[key])
        and all(
            not math.isfinite(_number(record.get(column)))
            for column in NUMERIC_COLUMNS[key]
        )
        and not any(_flag(record.get(column)) for column in BOOLEAN_COLUMNS[key])
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
            if not math.isfinite(float(record[column])):
                raise ValueError(
                    f"{key} row {number}: {column} must be finite numeric"
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
