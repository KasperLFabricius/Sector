"""Canonical reinforcement-element tables used by the UI and project files.

The section solvers still consume ``(x, y, area)`` tuples.  This module keeps the
richer, stable element record beside those tuples so later material, detailing and
fatigue checks can refer to the same bar or tendon without relying on row position.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping

import pandas as pd


ELEMENT_ID = "ID"
X = "x (mm)"
Y = "y (mm)"
SIZE_MODE = "size mode"
AREA = "area (mm2)"
DIAMETER = "diameter (mm)"
MATERIAL_ID = "material ID"
FATIGUE_DETAIL_ID = "fatigue detail ID"
GROUP_ID = "group ID"
SPACING_GROUP_ID = "spacing group ID"

COLUMNS = [
    ELEMENT_ID,
    X,
    Y,
    SIZE_MODE,
    AREA,
    DIAMETER,
    MATERIAL_ID,
    FATIGUE_DETAIL_ID,
    GROUP_ID,
    SPACING_GROUP_ID,
]
NUMERIC_COLUMNS = {X, Y, AREA, DIAMETER}
TEXT_COLUMNS = set(COLUMNS) - NUMERIC_COLUMNS

AREA_MODE = "Area"
DIAMETER_MODE = "Diameter"
INDEPENDENT_MODE = "Independent"
SIZE_MODES = (AREA_MODE, DIAMETER_MODE, INDEPENDENT_MODE)

KINDS = ("bar", "tendon")


def _kind(kind: str) -> str:
    value = str(kind).strip().lower()
    if value not in KINDS:
        raise ValueError(f"unknown reinforcement kind: {kind}")
    return value


def id_prefix(kind: str) -> str:
    return "R" if _kind(kind) == "bar" else "P"


def default_material_id(kind: str) -> str:
    return "M1" if _kind(kind) == "bar" else "P1"


def equivalent_diameter(area_mm2: float | None) -> float | None:
    """Diameter of one circular element with ``area_mm2``."""
    value = finite_number(area_mm2)
    if value is None or value <= 0.0:
        return None
    return math.sqrt(4.0 * value / math.pi)


def circular_area(diameter_mm: float | None) -> float | None:
    """Area of one circular element with ``diameter_mm``."""
    value = finite_number(diameter_mm)
    if value is None or value <= 0.0:
        return None
    return math.pi * value * value / 4.0


def finite_number(value) -> float | None:
    """A finite float, or ``None`` for a blank/non-numeric cell."""
    if isinstance(value, (list, tuple, dict, set)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def text_cell(value, default: str = "") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        return default
    return str(value).strip()


def empty_table() -> pd.DataFrame:
    """An empty mixed-type table with the canonical column order."""
    return pd.DataFrame({
        column: pd.Series(dtype="float64" if column in NUMERIC_COLUMNS else "object")
        for column in COLUMNS
    })


def _records(value) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, pd.DataFrame):
        return value.to_dict("records")
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _normal_mode(value, default_mode: str) -> str:
    text = text_cell(value)
    for choice in SIZE_MODES:
        if text.casefold() == choice.casefold():
            return choice
    return default_mode


def _id_pattern(kind: str):
    return re.compile(rf"^{id_prefix(kind)}([1-9][0-9]*)$")


def _allocate_id(prefix: str, used: set[str], next_number: int) -> tuple[str, int]:
    while f"{prefix}{next_number}" in used:
        next_number += 1
    value = f"{prefix}{next_number}"
    used.add(value)
    return value, next_number + 1


def normalise_table(value, kind: str, *, default_mode: str = AREA_MODE) -> pd.DataFrame:
    """Return a canonical mixed-type element table.

    Legacy ``x/y/area`` rows migrate to area-authoritative records. Missing or
    duplicate IDs are replaced deterministically; existing valid IDs never change.
    The non-authoritative size value is derived on every normalisation.
    """
    kind = _kind(kind)
    if default_mode not in SIZE_MODES:
        raise ValueError(f"unknown size mode: {default_mode}")
    source = _records(value)
    pattern = _id_pattern(kind)
    prefix = id_prefix(kind)
    raw_ids = [text_cell(row.get(ELEMENT_ID)) for row in source]
    suffixes = [int(match.group(1)) for raw in raw_ids
                if (match := pattern.fullmatch(raw))]
    next_number = max(suffixes, default=0) + 1
    used: set[str] = set()
    rows: list[dict] = []

    for raw in source:
        element_id = text_cell(raw.get(ELEMENT_ID))
        if not pattern.fullmatch(element_id) or element_id in used:
            element_id, next_number = _allocate_id(prefix, used, next_number)
        else:
            used.add(element_id)

        mode = _normal_mode(raw.get(SIZE_MODE), default_mode)
        area = finite_number(raw.get(AREA))
        diameter = finite_number(raw.get(DIAMETER))
        if mode == AREA_MODE:
            diameter = equivalent_diameter(area)
        elif mode == DIAMETER_MODE:
            area = circular_area(diameter)

        rows.append({
            ELEMENT_ID: element_id,
            X: finite_number(raw.get(X)),
            Y: finite_number(raw.get(Y)),
            SIZE_MODE: mode,
            AREA: area,
            DIAMETER: diameter,
            MATERIAL_ID: text_cell(raw.get(MATERIAL_ID), default_material_id(kind))
                         or default_material_id(kind),
            FATIGUE_DETAIL_ID: text_cell(raw.get(FATIGUE_DETAIL_ID)),
            GROUP_ID: text_cell(raw.get(GROUP_ID)),
            SPACING_GROUP_ID: text_cell(raw.get(SPACING_GROUP_ID)),
        })

    if not rows:
        return empty_table()
    frame = pd.DataFrame(rows, columns=COLUMNS)
    for column in NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    for column in TEXT_COLUMNS:
        frame[column] = frame[column].astype("object")
    return frame


def table_from_points(
    points_mm: Iterable[Iterable[float]],
    kind: str,
    *,
    size_mode: str = AREA_MODE,
) -> pd.DataFrame:
    """Build canonical elements from ``(x_mm, y_mm, area_mm2)`` points."""
    rows = []
    for point in points_mm:
        row = {X: point[0], Y: point[1], AREA: point[2], SIZE_MODE: size_mode}
        if size_mode == DIAMETER_MODE:
            row[DIAMETER] = equivalent_diameter(point[2])
        rows.append(row)
    return normalise_table(rows, kind, default_mode=size_mode)


def row_issues(value, kind: str) -> list[tuple[str, str]]:
    """Return ``(element ID, reason)`` for rows not usable by the solvers."""
    frame = normalise_table(value, kind)
    issues: list[tuple[str, str]] = []
    for row in frame.to_dict("records"):
        missing = []
        for column, label in ((X, "x"), (Y, "y"), (AREA, "area"),
                              (DIAMETER, "diameter")):
            number = finite_number(row.get(column))
            if number is None or (column in (AREA, DIAMETER) and number <= 0.0):
                missing.append(label)
        if missing:
            issues.append((str(row[ELEMENT_ID]), ", ".join(missing)))
    return issues


def valid_elements(value, kind: str) -> list[dict]:
    """Canonical, solver-ready element records in current table order."""
    frame = normalise_table(value, kind)
    invalid = {element_id for element_id, _reason in row_issues(frame, kind)}
    out = []
    for row in frame.to_dict("records"):
        if row[ELEMENT_ID] in invalid:
            continue
        out.append({
            "id": str(row[ELEMENT_ID]),
            "kind": _kind(kind),
            "x_mm": float(row[X]),
            "y_mm": float(row[Y]),
            "area_mm2": float(row[AREA]),
            "diameter_mm": float(row[DIAMETER]),
            "size_mode": str(row[SIZE_MODE]),
            "material_id": str(row[MATERIAL_ID]),
            "fatigue_detail_id": str(row[FATIGUE_DETAIL_ID]),
            "group_id": str(row[GROUP_ID]),
            "spacing_group_id": str(row[SPACING_GROUP_ID]),
        })
    return out


def point_grid_specs(
    kind: str,
    material_ids: Iterable[str] | None = None,
    fatigue_detail_ids: Iterable[str] | None = None,
) -> list[dict]:
    """Plain component column metadata for the mixed reinforcement grid."""
    kind = _kind(kind)
    material_options = [str(value).strip() for value in (material_ids or [])
                        if str(value).strip()]
    material_spec = (
        {"field": MATERIAL_ID, "title": "Material ID", "type": "select",
         "options": material_options, "preserve_unknown": True, "width": 108}
        if material_options
        else {"field": MATERIAL_ID, "title": "Material ID", "type": "text",
              "width": 108}
    )
    fatigue_options = [
        str(value).strip()
        for value in (fatigue_detail_ids or [])
        if str(value).strip()
    ]
    fatigue_spec = (
        {
            "field": FATIGUE_DETAIL_ID,
            "title": "Fatigue detail ID",
            "type": "select",
            "options": fatigue_options,
            "preserve_unknown": True,
            "allow_blank": True,
            "width": 128,
        }
        if fatigue_options
        else {
            "field": FATIGUE_DETAIL_ID,
            "title": "Fatigue detail ID",
            "type": "text",
            "width": 128,
        }
    )
    return [
        {"field": ELEMENT_ID, "title": "ID", "type": "id", "width": 64,
         "editable": False, "paste": False},
        {"field": X, "title": "x (mm)", "type": "number", "width": 88},
        {"field": Y, "title": "y (mm)", "type": "number", "width": 88},
        {"field": SIZE_MODE, "title": "Size basis", "type": "select",
         "options": list(SIZE_MODES), "width": 112},
        {"field": AREA, "title": "Area (mm2)", "type": "number", "width": 108,
         "derived_role": "area"},
        {"field": DIAMETER, "title": "Diameter (mm)", "type": "number",
         "width": 124, "derived_role": "diameter"},
        material_spec,
        fatigue_spec,
        {"field": GROUP_ID, "title": "Group ID", "type": "text", "width": 92},
        {"field": SPACING_GROUP_ID, "title": "Lap / bundle ID", "type": "text",
         "width": 128},
    ]


def point_grid_options(
    kind: str,
    material_ids: Iterable[str] | None = None,
    fatigue_detail_ids: Iterable[str] | None = None,
) -> dict:
    """Persistent-ID and size-derivation settings for the frontend."""
    available = [str(value).strip() for value in (material_ids or [])
                 if str(value).strip()]
    return {
        "id_column": ELEMENT_ID,
        "id_prefix": id_prefix(kind),
        "layout": "fitData",
        "default_values": {
            SIZE_MODE: AREA_MODE,
            MATERIAL_ID: (available[0] if available else default_material_id(kind)),
            # The connection/detail class cannot be inferred from geometry.
            # Require an explicit fatigue assignment even when compatible
            # catalogue entries are available.
            FATIGUE_DETAIL_ID: "",
            GROUP_ID: "",
            SPACING_GROUP_ID: "",
        },
        "compact_paste_fields": [X, Y, AREA],
        "derived_size": {
            "mode": SIZE_MODE,
            "area": AREA,
            "diameter": DIAMETER,
            "area_mode": AREA_MODE,
            "diameter_mode": DIAMETER_MODE,
            "independent_mode": INDEPENDENT_MODE,
        },
    }
