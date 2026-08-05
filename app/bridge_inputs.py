"""Typed tables for the optional independent bridge calculations."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Final, Literal, TypeAlias, cast

import pandas as pd

from sector import bridge


TableKey: TypeAlias = Literal[
    "bridge_brittle_base",
    "bridge_box_walls_base",
    "bridge_minimum_crack_base",
]
BRITTLE_TABLE_KEY: Final[TableKey] = "bridge_brittle_base"
BOX_WALL_TABLE_KEY: Final[TableKey] = "bridge_box_walls_base"
MINIMUM_CRACK_TABLE_KEY: Final[TableKey] = "bridge_minimum_crack_base"
TABLE_KEYS: Final[tuple[TableKey, ...]] = (
    BRITTLE_TABLE_KEY,
    BOX_WALL_TABLE_KEY,
    MINIMUM_CRACK_TABLE_KEY,
)

TABLE_COLUMNS: Final[dict[TableKey, tuple[str, ...]]] = {
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
TEXT_COLUMNS: Final[dict[TableKey, tuple[str, ...]]] = {
    BRITTLE_TABLE_KEY: ("region_id",),
    BOX_WALL_TABLE_KEY: ("wall_id",),
    MINIMUM_CRACK_TABLE_KEY: ("component",),
}
BOOLEAN_COLUMNS: Final[dict[TableKey, tuple[str, ...]]] = {
    BRITTLE_TABLE_KEY: (),
    BOX_WALL_TABLE_KEY: (),
    MINIMUM_CRACK_TABLE_KEY: ("restrained_shrinkage",),
}
NUMERIC_COLUMNS: Final[dict[TableKey, tuple[str, ...]]] = {
    key: tuple(
        column
        for column in columns
        if column not in TEXT_COLUMNS[key]
        and column not in BOOLEAN_COLUMNS[key]
    )
    for key, columns in TABLE_COLUMNS.items()
}


def _key(key: str) -> TableKey:
    if key not in TABLE_KEYS:
        raise bridge.BridgeCalculationError(
            "INVALID_INPUT",
            "bridge_table",
            f"unknown bridge table: {key}",
        )
    return key


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        return ""
    return str(value).strip()


def _number(value: object) -> float:
    if isinstance(value, bool) or isinstance(value, str):
        return math.nan
    try:
        number = float(cast(Any, value))
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _flag(value: object) -> bool:
    return value if isinstance(value, bool) else False


def _missing(value: object) -> bool:
    if value is None or (isinstance(value, str) and not value.strip()):
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _frame(value: object, key: TableKey) -> pd.DataFrame:
    if value is None:
        return empty_table(key)
    try:
        frame = (
            value.copy(deep=True)
            if isinstance(value, pd.DataFrame)
            else pd.DataFrame(value)
        )
    except (TypeError, ValueError) as exc:
        raise bridge.BridgeCalculationError(
            "INVALID_INPUT",
            key,
            f"{key} must be tabular",
        ) from exc
    if bool(frame.columns.duplicated().any()):
        raise bridge.BridgeCalculationError(
            "INVALID_INPUT",
            key,
            f"{key} contains duplicate columns",
        )
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


def normalise_table(value: object, key: str) -> pd.DataFrame:
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
            result[column] = source.map(_flag).astype("bool")
        else:
            result[column] = source.map(_number).astype("float64")
    return result.reset_index(drop=True)


def _raw_blank(record: Mapping[str, object], key: TableKey) -> bool:
    return (
        all(
            _missing(record.get(column))
            for column in (*TEXT_COLUMNS[key], *NUMERIC_COLUMNS[key])
        )
        and all(
            _missing(record.get(column)) or record.get(column) is False
            for column in BOOLEAN_COLUMNS[key]
        )
    )


def records(value: object, key: str) -> list[dict[str, object]]:
    key = _key(key)
    rows: list[dict[str, object]] = []
    raw_frame = _frame(value, key).reset_index(drop=True)
    raw_records = (
        raw_frame.to_dict("records")
        if len(raw_frame.columns)
        else [{} for _ in range(len(raw_frame.index))]
    )
    canonical_records = normalise_table(raw_frame, key).to_dict("records")
    for number, (raw_record, record) in enumerate(
        zip(raw_records, canonical_records, strict=True),
        start=1,
    ):
        if _raw_blank(raw_record, key):
            continue
        for column in NUMERIC_COLUMNS[key]:
            if not math.isfinite(float(record[column])):
                raise bridge.BridgeCalculationError(
                    "INVALID_INPUT",
                    column,
                    f"{key} row {number}: {column} must be finite numeric",
                )
        for column in BOOLEAN_COLUMNS[key]:
            raw_value = raw_record.get(column)
            if not _missing(raw_value) and not isinstance(raw_value, bool):
                raise bridge.BridgeCalculationError(
                    "INVALID_INPUT",
                    column,
                    f"{key} row {number}: {column} must be Boolean",
                )
        if key == MINIMUM_CRACK_TABLE_KEY:
            component = _text(record["component"]).casefold()
            if component not in {"web", "flange"}:
                raise bridge.BridgeCalculationError(
                    "INVALID_INPUT",
                    "component",
                    f"{key} row {number}: component must be Web or Flange",
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


def table_from_records(value: object, key: str) -> pd.DataFrame:
    if value is None:
        return empty_table(key)
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise bridge.BridgeCalculationError(
            "INVALID_INPUT",
            key,
            f"{key} must be a list of row objects",
        )
    return normalise_table(value, key)


def calculate_brittle(
    value: object,
    *,
    standard: bridge.BridgeMethod,
) -> bridge.BrittleMethodResult | None:
    brittle_rows = records(value, BRITTLE_TABLE_KEY)
    if not brittle_rows:
        return None
    return bridge.calculate_brittle_method_b(
        (
            bridge.PrestressBrittleRegion(
                region_id=_text(row["region_id"]),
                m_rep_knm=row["m_rep_knm"],
                z_s_m=row["z_s_m"],
                f_yk_mpa=row["f_yk_mpa"],
                as_provided_mm2=row["as_provided_mm2"],
            )
            for row in brittle_rows
        ),
        selected_standard=standard,
    )


def calculate_box_walls(value: object) -> bridge.BoxWallResult | None:
    wall_rows = records(value, BOX_WALL_TABLE_KEY)
    if not wall_rows:
        return None
    return bridge.calculate_box_walls(
        bridge.BoxWall(
            wall_id=_text(row["wall_id"]),
            cot_theta=row["cot_theta"],
            v_ed_kn=row["v_ed_kn"],
            v_rd_max_kn=row["v_rd_max_kn"],
            t_ed_equivalent_kn=row["t_ed_equivalent_kn"],
            t_rd_max_equivalent_kn=row["t_rd_max_equivalent_kn"],
        )
        for row in wall_rows
    )


def calculate_minimum_crack(
    value: object,
) -> bridge.MinimumCrackResult | None:
    minimum_rows = records(value, MINIMUM_CRACK_TABLE_KEY)
    if not minimum_rows:
        return None
    return bridge.calculate_minimum_crack_reinforcement(
        bridge.MinimumCrackComponent(
            component=_text(row["component"]),
            act_mm2=row["act_mm2"],
            k_c=row["k_c"],
            k=row["k"],
            fct_eff_mpa=row["fct_eff_mpa"],
            sigma_s_mpa=row["sigma_s_mpa"],
            as_provided_mm2=row["as_provided_mm2"],
            restrained_shrinkage=_flag(row["restrained_shrinkage"]),
        )
        for row in minimum_rows
    )
