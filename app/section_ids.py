"""Stable identities of the section model (project schema 29).

Sector numbers the corners of the concrete section with stable IDs. An outer
corner has the ID ``C<n>``. A void corner has the ID ``V<n>``, and the numbers
are unique over all voids. Reinforcing bars and tendons keep their table IDs
(``R<n>`` and ``P<n>``, see ``reinforcement_table``). An edge has no stored ID:
its identity is the ordered pair of its start and end corner IDs in the ring
order of the table, for example ``C3-C4``.

``normalise_geometry_table`` keeps each valid ID, so a deletion does not
renumber the other IDs. A row without a valid ID gets the next number that the
region has not issued (``next_corner`` or ``next_void_corner``), so a deleted ID
is not used again. The point editors of Sector 0.97.1 do not keep the IDs yet
(PR I1), so an application save numbers the corners in row order.

The section model is a list of regions. Schema 29 accepts one region, ``A1``,
which owns the corner and void tables. The prefix A keeps the region ID apart
from the bar IDs R<n>. A region can record the parameters of
the section template that made its geometry. The point tables stay the
authority for the calculation, and the IDs, the region list and the template
parameters have no engineering effect.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence

import pandas as pd

CORNERS_TABLE_KEY = "corners_base"
VOIDS_TABLE_KEY = "hole_base"
GEOMETRY_TABLE_KEYS = (CORNERS_TABLE_KEY, VOIDS_TABLE_KEY)

ID = "ID"
X = "x (mm)"
Y = "y (mm)"
COORDINATE_COLUMNS = (X, Y)
COLUMNS = (ID, X, Y)

CORNER_PREFIX = "C"
VOID_CORNER_PREFIX = "V"
REGION_PREFIX = "A"
_PREFIXES = {
    CORNERS_TABLE_KEY: CORNER_PREFIX,
    VOIDS_TABLE_KEY: VOID_CORNER_PREFIX,
}

EDGE_SEPARATOR = "-"

REGIONS_KEY = "section_regions"
REGIONS_VERSION = 1
MAX_REGIONS = 1
DEFAULT_REGION_ID = "A1"
# The counters of the issued corner numbers on the region record.
COUNTER_FIELDS = {
    CORNERS_TABLE_KEY: "next_corner",
    VOIDS_TABLE_KEY: "next_void_corner",
}

# Section templates that can record their parameters on a region. These are the
# Quick Section shapes; a later template (for example a parametric box girder)
# adds its kind here.
TEMPLATE_KINDS = (
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
)

# Template and group parameters are flat name-value pairs.
PARAMETER_NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
MAX_PARAMETERS = 64
MAX_PARAMETER_TEXT = 200


def id_pattern(prefix: str) -> re.Pattern:
    """Return the full-match pattern of one stable ID family."""

    return re.compile(rf"{re.escape(prefix)}([1-9][0-9]*)")


def table_prefix(key: str) -> str:
    """Return the ID prefix of one geometry table."""

    try:
        return _PREFIXES[key]
    except KeyError as exc:
        raise ValueError(f"unknown geometry table: {key}") from exc


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
    if isinstance(value, (bool, list, tuple, dict, set)):
        return math.nan
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _blank_coordinates(x, y) -> bool:
    return math.isnan(x) and math.isnan(y)


def empty_geometry_table() -> pd.DataFrame:
    """Return an empty geometry table with the schema-29 columns."""

    return pd.DataFrame({
        ID: pd.Series(dtype="object"),
        X: pd.Series(dtype="float64"),
        Y: pd.Series(dtype="float64"),
    })


def _records(value) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, pd.DataFrame):
        return value.to_dict("records")
    frame = pd.DataFrame(value)
    return frame.to_dict("records")


def normalise_geometry_table(
    value, key: str, next_number: int = 1
) -> pd.DataFrame:
    """Return a geometry table with the ID, x and y columns.

    Coordinates become floats, and a non-numeric cell becomes NaN as before. In
    the void table, a row with two blank coordinates separates two voids and has
    no ID. Each other row keeps its ID when the ID has the prefix of the table
    and is unique. A row without a valid ID gets the next number from
    ``next_number`` (the counter of the region) or above the largest number in
    the table, whichever is higher, in row order. A table without any valid
    ID is numbered from 1 in row order. Valid IDs never change.
    """

    prefix = table_prefix(key)
    pattern = id_pattern(prefix)
    records = _records(value)
    rows = []
    for record in records:
        x = _number(record.get(X))
        y = _number(record.get(Y))
        rows.append([_text(record.get(ID)), x, y])
    separator = [
        key == VOIDS_TABLE_KEY and _blank_coordinates(x, y)
        for _id, x, y in rows
    ]
    numbers = [
        int(match.group(1))
        for (element_id, _x, _y), blank in zip(rows, separator)
        if not blank and (match := pattern.fullmatch(element_id))
    ]
    # A table with no valid ID (an older file, or a live table of 0.97.1)
    # is numbered in row order from 1.
    next_number = (
        max(int(next_number), max(numbers) + 1) if numbers else 1
    )
    used: set[str] = set()
    for row, blank in zip(rows, separator):
        if blank:
            row[0] = ""
            continue
        element_id = row[0]
        if pattern.fullmatch(element_id) and element_id not in used:
            used.add(element_id)
            continue
        while f"{prefix}{next_number}" in used:
            next_number += 1
        row[0] = f"{prefix}{next_number}"
        used.add(row[0])
        next_number += 1
    if not rows:
        return empty_geometry_table()
    frame = pd.DataFrame(rows, columns=list(COLUMNS))
    frame[ID] = frame[ID].astype("object")
    for column in COORDINATE_COLUMNS:
        frame[column] = frame[column].astype("float64")
    return frame


def next_number_after(frame: pd.DataFrame, key: str) -> int:
    """Return the number above the largest ID number of a normalised table."""

    pattern = id_pattern(table_prefix(key))
    numbers = [
        int(match.group(1))
        for element_id in frame[ID].tolist()
        if (match := pattern.fullmatch(str(element_id)))
    ]
    return max(numbers, default=0) + 1


def corner_ids(value, key: str) -> list[str]:
    """Return the IDs of the corner rows of one geometry table, in order."""

    frame = normalise_geometry_table(value, key)
    return [element_id for element_id in frame[ID].tolist() if element_id]


def edge_id(start_id: str, end_id: str) -> str:
    """Return the identity of the edge from one corner to the next corner."""

    for corner in (start_id, end_id):
        if not _corner_prefix(corner):
            raise ValueError(f"{corner!r} is not a corner ID")
    if _corner_prefix(start_id) != _corner_prefix(end_id):
        raise ValueError("an edge connects two corners of the same ring family")
    if start_id == end_id:
        raise ValueError("an edge connects two different corners")
    return f"{start_id}{EDGE_SEPARATOR}{end_id}"


def ring_edge_ids(ids: Sequence[str]) -> list[str]:
    """Return the edge IDs of one closed ring, the last corner to the first."""

    ids = list(ids)
    if len(ids) < 3:
        return []
    return [edge_id(ids[i], ids[(i + 1) % len(ids)]) for i in range(len(ids))]


def parse_edge_id(value: str) -> tuple[str, str]:
    """Return the start and end corner IDs of one edge identity."""

    if type(value) is not str:
        raise ValueError("an edge ID must be text")
    parts = value.split(EDGE_SEPARATOR)
    if len(parts) != 2:
        raise ValueError(f"{value!r} is not an edge ID")
    start_id, end_id = parts
    edge_id(start_id, end_id)
    return start_id, end_id


def _corner_prefix(value) -> str | None:
    if type(value) is not str:
        return None
    for prefix in (CORNER_PREFIX, VOID_CORNER_PREFIX):
        if id_pattern(prefix).fullmatch(value):
            return prefix
    return None


def default_region() -> dict:
    """Return the one region of a schema-29 section."""

    return {
        "id": DEFAULT_REGION_ID,
        "template": None,
        "next_corner": 1,
        "next_void_corner": 1,
    }


def default_regions() -> dict:
    """Return the default region list."""

    return {"version": REGIONS_VERSION, "items": [default_region()]}


def validate_parameters(value, label: str) -> dict:
    """Return one flat parameter mapping, or raise ``ValueError``.

    A name has lowercase ASCII letters, digits and underscores and starts with a
    letter. A value is a Boolean, a finite JSON number or one line of text. A
    JSON integer stays an integer, so a count keeps its type.
    """

    if not isinstance(value, Mapping):
        raise ValueError(f"{label} parameters must be an object")
    if len(value) > MAX_PARAMETERS:
        raise ValueError(f"{label} has more than {MAX_PARAMETERS} parameters")
    parameters = {}
    for name, item in value.items():
        if type(name) is not str or PARAMETER_NAME_RE.fullmatch(name) is None:
            raise ValueError(f"{label} has an invalid parameter name")
        if type(item) is bool:
            parameters[name] = item
        elif type(item) is int:
            parameters[name] = item
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError(f"{label} parameter {name} must be finite")
            parameters[name] = 0.0 if item == 0.0 else item
        elif type(item) is str:
            if (
                len(item) > MAX_PARAMETER_TEXT
                or any(ord(character) < 32 for character in item)
            ):
                raise ValueError(
                    f"{label} parameter {name} must be one line of at most "
                    f"{MAX_PARAMETER_TEXT} characters"
                )
            parameters[name] = item
        else:
            raise ValueError(
                f"{label} parameter {name} must be a number, a Boolean or text"
            )
    return dict(sorted(parameters.items()))


def validate_template(value, label: str):
    """Return ``None`` or one validated template record."""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} template must be an object or null")
    if set(value) != {"kind", "parameters"}:
        raise ValueError(f"{label} template must contain kind and parameters")
    kind = value["kind"]
    if type(kind) is not str or kind not in TEMPLATE_KINDS:
        raise ValueError(f"{label} template kind is not supported")
    return {
        "kind": kind,
        "parameters": validate_parameters(value["parameters"], f"{label} template"),
    }


def validate_regions(value) -> dict:
    """Return the validated region list, or raise ``ValueError``."""

    if not isinstance(value, Mapping):
        raise ValueError(f"{REGIONS_KEY} must be an object")
    if set(value) - {"version", "items"}:
        raise ValueError(f"{REGIONS_KEY} contains unknown fields")
    version = value.get("version", REGIONS_VERSION)
    if type(version) is not int or version != REGIONS_VERSION:
        raise ValueError(f"{REGIONS_KEY} version is not supported")
    items = value.get("items")
    if type(items) is not list:
        raise ValueError(f"{REGIONS_KEY} items must be a list")
    if len(items) != MAX_REGIONS:
        raise ValueError(f"{REGIONS_KEY} must contain exactly one region")
    pattern = id_pattern(REGION_PREFIX)
    regions = []
    for position, item in enumerate(items, start=1):
        label = f"{REGIONS_KEY} item {position}"
        if not isinstance(item, Mapping):
            raise ValueError(f"{label} must be an object")
        if set(item) - {"id", "template", *COUNTER_FIELDS.values()}:
            raise ValueError(f"{label} contains unknown fields")
        region_id = item.get("id")
        if type(region_id) is not str or pattern.fullmatch(region_id) is None:
            raise ValueError(f"{label} id must be A followed by a number")
        if region_id != DEFAULT_REGION_ID:
            raise ValueError(f"{label} id must be {DEFAULT_REGION_ID}")
        region = {
            "id": region_id,
            "template": validate_template(item.get("template"), label),
        }
        for field in COUNTER_FIELDS.values():
            counter = item.get(field, 1)
            if type(counter) is not int or counter < 1:
                raise ValueError(f"{label} {field} must be a positive whole number")
            region[field] = counter
        regions.append(region)
    return {"version": REGIONS_VERSION, "items": regions}
