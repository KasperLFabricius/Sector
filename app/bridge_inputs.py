"""Canonical project tables for the DS/EN 1992-2 base methodology."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import pandas as pd

from sector import bridge


VERSION = 1

COVERAGE_TABLE_KEY = "bridge_coverage_base"
BRITTLE_TABLE_KEY = "bridge_brittle_regions_base"
BOX_WALL_TABLE_KEY = "bridge_box_walls_base"
MINIMUM_TABLE_KEY = "bridge_minimum_components_base"
TABLE_KEYS = (
    COVERAGE_TABLE_KEY,
    BRITTLE_TABLE_KEY,
    BOX_WALL_TABLE_KEY,
    MINIMUM_TABLE_KEY,
)

COVERAGE_COLUMNS = ("check_id", "applicability", "source", "notes")
BRITTLE_COLUMNS = (
    "region_id",
    "m_rep_knm",
    "z_s_m",
    "f_yk_mpa",
    "as_provided_mm2",
)
BOX_WALL_COLUMNS = (
    "wall_id",
    "cot_theta",
    "v_ed_kn",
    "v_rd_max_kn",
    "t_ed_equivalent_kn",
    "t_rd_max_equivalent_kn",
)
MINIMUM_COLUMNS = (
    "component",
    "act_mm2",
    "k_c",
    "k",
    "fct_eff_mpa",
    "sigma_s_mpa",
    "as_provided_mm2",
    "restrained_shrinkage",
)

TABLE_COLUMNS = {
    COVERAGE_TABLE_KEY: COVERAGE_COLUMNS,
    BRITTLE_TABLE_KEY: BRITTLE_COLUMNS,
    BOX_WALL_TABLE_KEY: BOX_WALL_COLUMNS,
    MINIMUM_TABLE_KEY: MINIMUM_COLUMNS,
}

TEXT_COLUMNS = {
    COVERAGE_TABLE_KEY: COVERAGE_COLUMNS,
    BRITTLE_TABLE_KEY: ("region_id",),
    BOX_WALL_TABLE_KEY: ("wall_id",),
    MINIMUM_TABLE_KEY: ("component",),
}

NUMERIC_COLUMNS = {
    COVERAGE_TABLE_KEY: (),
    BRITTLE_TABLE_KEY: BRITTLE_COLUMNS[1:],
    BOX_WALL_TABLE_KEY: BOX_WALL_COLUMNS[1:],
    MINIMUM_TABLE_KEY: MINIMUM_COLUMNS[1:7],
}

BOOLEAN_COLUMNS = {
    COVERAGE_TABLE_KEY: (),
    BRITTLE_TABLE_KEY: (),
    BOX_WALL_TABLE_KEY: (),
    MINIMUM_TABLE_KEY: ("restrained_shrinkage",),
}


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return ""


def _number(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return math.nan
    if isinstance(value, bool) or type(value).__name__ == "bool_":
        return math.nan
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _flag(value):
    if isinstance(value, bool):
        return value
    if type(value).__name__ == "bool_":
        return bool(value)
    if value is None:
        return None
    return None


def default_coverage_records() -> list[dict]:
    return [
        {
            "check_id": check_id,
            "applicability": bridge.NOT_ESTABLISHED,
            "source": "",
            "notes": "",
        }
        for check_id in bridge.APPLICABILITY_CHECK_IDS
    ]


def empty_table(key: str) -> pd.DataFrame:
    if key not in TABLE_KEYS:
        raise ValueError(f"unknown bridge table: {key}")
    if key == COVERAGE_TABLE_KEY:
        return table_from_records(default_coverage_records(), key)
    data = {}
    for column in TABLE_COLUMNS[key]:
        if column in BOOLEAN_COLUMNS[key]:
            data[column] = pd.Series(dtype="bool")
        elif column in NUMERIC_COLUMNS[key]:
            data[column] = pd.Series(dtype="float64")
        else:
            data[column] = pd.Series(dtype="string")
    result = pd.DataFrame(data, columns=TABLE_COLUMNS[key])
    result.attrs["sector_bridge_table"] = key
    return result


def normalise_table(value, key: str) -> pd.DataFrame:
    """Return one canonical bridge table without accepting unknown columns."""

    if key not in TABLE_KEYS:
        raise ValueError(f"unknown bridge table: {key}")
    if value is None:
        return empty_table(key)
    try:
        frame = (
            value.copy(deep=True)
            if isinstance(value, pd.DataFrame)
            else pd.DataFrame(value)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} is not tabular") from exc

    issues = list(frame.attrs.get("sector_bridge_table_issues") or ())
    unknown_columns = [
        str(column)
        for column in frame.columns
        if column not in TABLE_COLUMNS[key]
    ]
    if unknown_columns:
        issues.append(
            f"{key} contains unknown column(s): "
            + ", ".join(unknown_columns)
        )

    result = pd.DataFrame(index=frame.index)
    for column in TABLE_COLUMNS[key]:
        series = (
            frame[column]
            if column in frame
            else pd.Series([None] * len(frame), index=frame.index)
        )
        if column in BOOLEAN_COLUMNS[key]:
            result[column] = [_flag(value) for value in series]
        elif column in NUMERIC_COLUMNS[key]:
            result[column] = [_number(value) for value in series]
        else:
            for row_number, raw in enumerate(series, start=1):
                if raw is None or isinstance(raw, str):
                    continue
                try:
                    blank = bool(pd.isna(raw))
                except (TypeError, ValueError):
                    blank = False
                if not blank:
                    issues.append(
                        f"{key} row {row_number}: {column} must be typed text"
                    )
            result[column] = [_text(value) for value in series]

    if key == COVERAGE_TABLE_KEY:
        by_id: dict[str, dict] = {}
        for row_number, record in enumerate(
            result.to_dict("records"),
            start=1,
        ):
            check_id = _text(record.get("check_id"))
            if not check_id:
                issues.append(
                    f"{key} row {row_number}: check_id is required"
                )
            elif check_id not in bridge.APPLICABILITY_CHECK_IDS:
                issues.append(
                    f"{key} row {row_number}: unknown check_id {check_id!r}"
                )
            elif check_id in by_id:
                issues.append(
                    f"{key}: duplicate check_id {check_id!r}"
                )
            else:
                by_id[check_id] = record
        result = pd.DataFrame(
            [
                by_id.get(check_id, {
                    "check_id": check_id,
                    "applicability": bridge.NOT_ESTABLISHED,
                    "source": "",
                    "notes": "",
                })
                for check_id in bridge.APPLICABILITY_CHECK_IDS
            ],
            columns=COVERAGE_COLUMNS,
        )

    for column in TEXT_COLUMNS[key]:
        result[column] = result[column].astype("string")
    for column in NUMERIC_COLUMNS[key]:
        result[column] = pd.to_numeric(
            result[column],
            errors="coerce",
        ).astype("float64")
    for column in BOOLEAN_COLUMNS[key]:
        # Retain malformed values as object/None so validation can reject them.
        if all(isinstance(value, bool) for value in result[column].tolist()):
            result[column] = result[column].astype("bool")
    result = result.reset_index(drop=True)
    result.attrs["sector_bridge_table"] = key
    result.attrs["sector_bridge_table_issues"] = tuple(dict.fromkeys(issues))
    return result


def table_from_records(records: Sequence[Mapping], key: str) -> pd.DataFrame:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError(f"{key} records must be a list")
    if not all(isinstance(record, Mapping) for record in records):
        raise ValueError(f"{key} records must contain objects")
    return normalise_table([dict(record) for record in records], key)


def table_records(value, key: str) -> list[dict]:
    frame = normalise_table(value, key)
    errors = table_errors(frame, key)
    if errors:
        raise ValueError("; ".join(errors))
    records = []
    for raw in frame.to_dict("records"):
        record = {}
        for column in TABLE_COLUMNS[key]:
            value = raw[column]
            if column in NUMERIC_COLUMNS[key]:
                record[column] = float(value)
            elif column in BOOLEAN_COLUMNS[key]:
                record[column] = bool(value)
            else:
                record[column] = _text(value)
        records.append(record)
    return records


def _blank_numeric_row(record: Mapping, key: str) -> bool:
    return all(
        pd.isna(record.get(column))
        for column in NUMERIC_COLUMNS[key]
    )


def table_errors(value, key: str) -> list[str]:
    """Return save-boundary errors for one bridge evidence table."""

    frame = normalise_table(value, key)
    errors: list[str] = list(
        frame.attrs.get("sector_bridge_table_issues") or ()
    )
    if key == COVERAGE_TABLE_KEY:
        if list(frame["check_id"]) != list(bridge.APPLICABILITY_CHECK_IDS):
            errors.append("bridge coverage rows are incomplete or reordered")
        for row in frame.to_dict("records"):
            check_id = _text(row["check_id"])
            applicability = _text(row["applicability"])
            if applicability not in bridge.APPLICABILITY_OPTIONS:
                errors.append(f"{check_id}: unknown applicability")
        return errors

    seen: set[str] = set()
    id_column = TABLE_COLUMNS[key][0]
    for row_number, row in enumerate(frame.to_dict("records"), start=1):
        row_id = _text(row.get(id_column))
        blank_numeric = _blank_numeric_row(row, key)
        if not row_id and blank_numeric:
            continue
        if not row_id:
            errors.append(f"{key} row {row_number}: {id_column} is required")
        elif row_id.casefold() in seen:
            errors.append(f"{key}: duplicate {id_column} {row_id!r}")
        else:
            seen.add(row_id.casefold())
        for column in NUMERIC_COLUMNS[key]:
            value = row.get(column)
            if pd.isna(value) or not math.isfinite(float(value)):
                errors.append(
                    f"{key} row {row_number}: {column} must be finite"
                )
        cot_theta = row.get("cot_theta")
        if (
            key == BOX_WALL_TABLE_KEY
            and not pd.isna(cot_theta)
            and math.isfinite(float(cot_theta))
            and not (
                bridge.BOX_WALL_COT_THETA_MIN
                <= float(cot_theta)
                <= bridge.BOX_WALL_COT_THETA_MAX
            )
        ):
            errors.append(
                f"{key} row {row_number}: cot_theta must be between "
                f"{bridge.BOX_WALL_COT_THETA_MIN:.1f} and "
                f"{bridge.BOX_WALL_COT_THETA_MAX:.1f}"
            )
        minimum_k = row.get("k")
        if (
            key == MINIMUM_TABLE_KEY
            and not pd.isna(minimum_k)
            and math.isfinite(float(minimum_k))
            and not (
                bridge.MINIMUM_CRACK_K_MIN
                <= float(minimum_k)
                <= bridge.MINIMUM_CRACK_K_MAX
            )
        ):
            errors.append(
                f"{key} row {row_number}: k must be between "
                f"{bridge.MINIMUM_CRACK_K_MIN:.2f} and "
                f"{bridge.MINIMUM_CRACK_K_MAX:.2f}"
            )
        for column in BOOLEAN_COLUMNS[key]:
            if not isinstance(row.get(column), bool):
                errors.append(
                    f"{key} row {row_number}: {column} must be Boolean"
                )
    return errors


def all_table_errors(tables: Mapping) -> list[str]:
    errors = []
    for key in TABLE_KEYS:
        errors.extend(table_errors(tables.get(key), key))
    return errors


def decisions(value) -> tuple[bridge.ApplicabilityDecision, ...]:
    frame = normalise_table(value, COVERAGE_TABLE_KEY)
    return tuple(
        bridge.ApplicabilityDecision(
            check_id=_text(row["check_id"]),
            applicability=_text(row["applicability"]),
            source=_text(row["source"]),
            notes=_text(row["notes"]),
        )
        for row in frame.to_dict("records")
    )


def brittle_regions(value) -> tuple[bridge.PrestressBrittleRegion, ...]:
    frame = normalise_table(value, BRITTLE_TABLE_KEY)
    return tuple(
        bridge.PrestressBrittleRegion(
            region_id=_text(row["region_id"]),
            m_rep_knm=row["m_rep_knm"],
            z_s_m=row["z_s_m"],
            f_yk_mpa=row["f_yk_mpa"],
            as_provided_mm2=row["as_provided_mm2"],
        )
        for row in frame.to_dict("records")
        if _text(row["region_id"]) or not _blank_numeric_row(row, BRITTLE_TABLE_KEY)
    )


def box_walls(value) -> tuple[bridge.BoxWallEvidence, ...]:
    frame = normalise_table(value, BOX_WALL_TABLE_KEY)
    return tuple(
        bridge.BoxWallEvidence(
            wall_id=_text(row["wall_id"]),
            cot_theta=row["cot_theta"],
            v_ed_kn=row["v_ed_kn"],
            v_rd_max_kn=row["v_rd_max_kn"],
            t_ed_equivalent_kn=row["t_ed_equivalent_kn"],
            t_rd_max_equivalent_kn=row["t_rd_max_equivalent_kn"],
        )
        for row in frame.to_dict("records")
        if _text(row["wall_id"]) or not _blank_numeric_row(row, BOX_WALL_TABLE_KEY)
    )


def minimum_components(value) -> tuple[bridge.MinimumCrackComponent, ...]:
    frame = normalise_table(value, MINIMUM_TABLE_KEY)
    return tuple(
        bridge.MinimumCrackComponent(
            component=_text(row["component"]),
            act_mm2=row["act_mm2"],
            k_c=row["k_c"],
            k=row["k"],
            fct_eff_mpa=row["fct_eff_mpa"],
            sigma_s_mpa=row["sigma_s_mpa"],
            as_provided_mm2=row["as_provided_mm2"],
            restrained_shrinkage=row["restrained_shrinkage"],
        )
        for row in frame.to_dict("records")
        if _text(row["component"]) or not _blank_numeric_row(row, MINIMUM_TABLE_KEY)
    )
