"""CSV action schema version 1: one file for the Plastic and Elastic cases.

The file form (plan decision 9):

1. Line 1 is the version line ``# sector-actions-csv v1``.
2. Line 2 holds the column headings, line 3 the unit of each column.
3. Each further line is one case. ``limit_state`` sends a ULS row to the
   Plastic table and an SLS row to the Elastic table.

Comma, semicolon and tab delimiters are read. Numeric cells accept the dot or
the comma decimal (comma decimals in a comma-delimited file need quotes). A ULS
row leaves the SLS action columns blank, and an SLS row the ULS columns.

The headings are the keys of the action tables. The case attributes (location
tag, design situation, stage) are in the file, but have no calculation effect.
The import reads all values through ``load_cases.normalise_table``, so the
file gives the same canonical tables as the editors.
"""

from __future__ import annotations

import copy
import csv
import io
import re
from collections.abc import Mapping

import pandas as pd

from app import load_cases
from app.table_field_definitions import field_definition

_BOM = chr(0xFEFF)
VERSION = 1
VERSION_LINE = f"# sector-actions-csv v{VERSION}"
_VERSION_RE = re.compile(r"#\s*sector-actions-csv\s+v(\S*)", re.IGNORECASE)
LIMIT_STATE = "limit_state"
LIMIT_STATE_TABLES = {
    "ULS": load_cases.PLASTIC_TABLE_KEY,
    "SLS": load_cases.ELASTIC_TABLE_KEY,
}
TABLE_LIMIT_STATES = {table: state for state, table in LIMIT_STATE_TABLES.items()}
_CASE_COLUMNS = (load_cases.NAME, load_cases.DESCRIPTION, *load_cases.ATTRIBUTE_COLUMNS)
FAMILY_COLUMNS = {
    key: tuple(
        column for column in load_cases.TABLE_COLUMNS[key]
        if column not in _CASE_COLUMNS
    )
    for key in load_cases.CASE_TABLE_KEYS
}
COLUMNS = (
    LIMIT_STATE,
    *_CASE_COLUMNS,
    *FAMILY_COLUMNS[load_cases.PLASTIC_TABLE_KEY],
    *FAMILY_COLUMNS[load_cases.ELASTIC_TABLE_KEY],
)
MAX_BYTES = 2_000_000
MAX_MESSAGES = 5
_FLAG_TOKENS = {"", "0", "1", "true", "false", "yes", "no", "on", "off"}
NO_VERSION_MESSAGE = (
    f'Line 1 must be the version line "{VERSION_LINE}". To add a block '
    "without this line to one table, use Plastic or Elastic > Paste cases "
    "with preview."
)


def _csv_unit(unit: str) -> str:
    return unit.replace(" ", "")


def _column_table(column: str) -> str | None:
    for key, columns in FAMILY_COLUMNS.items():
        if column in columns:
            return key
    return None


UNITS = {
    LIMIT_STATE: "-",
    **{column: "-" for column in _CASE_COLUMNS},
    **{
        column: _csv_unit(field_definition(_column_table(column), column).unit)
        for column in COLUMNS[1 + len(_CASE_COLUMNS):]
    },
}


def _unit_token(text: str) -> str:
    token = str(text).replace(" ", "").casefold()
    return "-" if token in {"", "-"} else token


def field_reference_rows() -> list[list[str]]:
    """Return one manual row per column: heading, unit, rows and content."""

    rows = []
    for column in COLUMNS:
        if column == LIMIT_STATE:
            used, content = "All", "ULS (Plastic table) or SLS (Elastic table)"
        else:
            table = _column_table(column)
            used = TABLE_LIMIT_STATES[table] if table else "All"
            content = field_definition(
                table or load_cases.PLASTIC_TABLE_KEY, column
            ).label
        rows.append([f"`{column}`", UNITS[column], used, content])
    return rows


def _number_text(value, decimal_comma: bool) -> str:
    text = str(value)
    return text.replace(".", ",") if decimal_comma else text


def export_csv(tables: Mapping, *, delimiter: str = ",") -> str:
    """Write the active Plastic and Elastic cases in the CSV v1 form.

    A semicolon delimiter writes decimal commas. The numbers keep their full
    precision (Python ``repr``), so an import gives the same values.
    """

    if delimiter not in {",", ";"}:
        raise ValueError("Use a comma or a semicolon delimiter.")
    decimal_comma = delimiter == ";"
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")
    buffer.write(VERSION_LINE + "\r\n")
    writer.writerow(COLUMNS)
    writer.writerow([UNITS[column] for column in COLUMNS])
    for limit_state, key in LIMIT_STATE_TABLES.items():
        frame = load_cases.editor_table(
            load_cases.active_table(tables.get(key), key), key
        )
        persisted = load_cases.PERSISTED_COLUMNS[key]
        for record in frame.to_dict("records"):
            row = []
            for column in COLUMNS:
                if column == LIMIT_STATE:
                    row.append(limit_state)
                elif column not in persisted:
                    row.append("")
                elif column in load_cases.FLAG_COLUMNS[key]:
                    row.append("true" if bool(record[column]) else "false")
                elif column in load_cases.NUMERIC_COLUMNS[key]:
                    row.append(_number_text(record[column], decimal_comma))
                else:
                    row.append(str(record[column]))
            writer.writerow(row)
    return buffer.getvalue()


def template(*, delimiter: str = ",") -> str:
    """Return the version line, the headings and the units row."""

    return export_csv({key: [] for key in load_cases.CASE_TABLE_KEYS},
                      delimiter=delimiter)


def decode(data: bytes) -> str:
    """Decode an uploaded file: UTF-8 (with or without BOM), else Windows-1252."""

    if len(data) > MAX_BYTES:
        raise ValueError("The file is too large. Sector reads at most 2 MB.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise ValueError("Save the file as CSV UTF-8 and import it again.") from exc


def is_versioned(text: str) -> bool:
    """Whether the first nonblank line starts with a version mark."""

    for line in str(text).lstrip(_BOM).splitlines():
        if line.strip():
            return line.strip().lstrip('"').startswith("#")
    return False


def _delimiter(lines: list[str]) -> str:
    for line in lines:
        stripped = line.strip().lstrip('"')
        if stripped and not stripped.startswith("#"):
            for candidate in ("\t", ";", ","):
                if candidate in line:
                    return candidate
            return ","
    return ","


def _fail(messages: list[str]) -> None:
    if messages:
        shown = messages[:MAX_MESSAGES]
        if len(messages) > MAX_MESSAGES:
            shown.append(f"{len(messages) - MAX_MESSAGES} more issues")
        raise ValueError("; ".join(shown))


def _width(cells: list[str], width: int, line: int, messages: list[str]):
    cells = list(cells)
    while len(cells) > width and not cells[-1]:
        cells.pop()
    if len(cells) != width:
        messages.append(
            f"Line {line} has {len(cells)} cells. The heading row has {width}."
        )
        return None
    return cells


def parse(text: str) -> dict[str, pd.DataFrame]:
    """Read a CSV v1 text into the canonical Plastic and Elastic tables.

    Raise ``ValueError`` with line numbers when the file form or a value is
    not valid. No partial result is returned.
    """

    text = str(text).lstrip(_BOM)
    delimiter = _delimiter(text.splitlines())
    reader = csv.reader(io.StringIO(text), delimiter=delimiter, strict=True)
    rows = []
    for cells in reader:
        cells = [cell.strip() for cell in cells]
        if any(cells):
            rows.append((reader.line_num, cells))
    if not rows:
        raise ValueError("The file is empty. " + NO_VERSION_MESSAGE)
    first = rows[0][1]
    match = _VERSION_RE.fullmatch(first[0])
    if match is None or any(first[1:]):
        raise ValueError(NO_VERSION_MESSAGE)
    if match.group(1) != str(VERSION):
        raise ValueError(
            f'The file uses CSV action schema "v{match.group(1)}". '
            f"This Sector version reads v{VERSION} only."
        )
    if len(rows) < 3:
        raise ValueError(
            "Add the heading row and the units row after the version line."
        )
    line, header = rows[1]
    while header and not header[-1]:
        header.pop()
    header = [cell.casefold() for cell in header]
    messages: list[str] = []
    if not all(header):
        raise ValueError(f"Line {line}: give each column a heading.")
    if len(header) != len(set(header)):
        raise ValueError(f"Line {line}: use each column heading once.")
    unknown = [cell for cell in header if cell not in COLUMNS]
    if unknown:
        raise ValueError(
            f"Line {line}: unknown column headings {', '.join(unknown)}. "
            "Use the headings of the template."
        )
    for required in (LIMIT_STATE, load_cases.NAME):
        if required not in header:
            raise ValueError(f"Line {line}: add the {required} column.")
    line, units = rows[2]
    units = _width(units, len(header), line, messages)
    _fail(messages)
    for column, unit in zip(header, units):
        if _unit_token(unit) != _unit_token(UNITS[column]):
            messages.append(
                f"Line {line} (units row): use {UNITS[column]} for {column}, "
                f"not {unit!r}"
            )
    _fail(messages)
    if len(rows) < 4:
        raise ValueError("Add at least one case row after the units row.")
    records = {key: [] for key in load_cases.CASE_TABLE_KEYS}
    lines = {key: [] for key in load_cases.CASE_TABLE_KEYS}
    for line, cells in rows[3:]:
        cells = _width(cells, len(header), line, messages)
        if cells is None:
            continue
        record = dict(zip(header, cells))
        limit_state = record[LIMIT_STATE].upper()
        key = LIMIT_STATE_TABLES.get(limit_state)
        if key is None:
            messages.append(f"Line {line}: {LIMIT_STATE} must be ULS or SLS")
            continue
        foreign = [
            column for column in header
            if record[column] and _column_table(column) not in {None, key}
        ]
        if foreign:
            messages.append(
                f"Line {line}: leave {', '.join(foreign)} blank in a "
                f"{limit_state} row"
            )
        if not record[load_cases.NAME]:
            messages.append(f"Line {line}: enter a case name")
        for flag in load_cases.FLAG_COLUMNS[key]:
            if flag in record and record[flag].casefold() not in _FLAG_TOKENS:
                messages.append(f"Line {line}: use true or false in {flag}")
        records[key].append({
            column: record[column] for column in header
            if column in load_cases.PERSISTED_COLUMNS[key]
        })
        lines[key].append(line)
    _fail(messages)
    tables = {}
    for key in load_cases.CASE_TABLE_KEYS:
        frame = load_cases.normalise_table(
            pd.DataFrame(records[key], dtype=object), key
        )
        issues = load_cases.decimal_issue_ledger(frame.attrs)
        for (position, column), entered in sorted(issues.items()):
            messages.append(
                f"Line {lines[key][position]}: {column} must be one decimal "
                f"number, not {entered!r}"
            )
        for position, row in enumerate(frame.to_dict("records")):
            for column in load_cases.PLASTIC_FACE_COLUMNS:
                if column in row and row[column] not in load_cases.FACE_OPTIONS:
                    messages.append(
                        f"Line {lines[key][position]}: {column} must be auto, "
                        "negative or positive"
                    )
            for column in load_cases.ATTRIBUTE_COLUMNS:
                reason = load_cases.attribute_error(column, row[column])
                if reason is not None:
                    messages.append(
                        f"Line {lines[key][position]}: {column} {reason}"
                    )
        tables[key] = frame
    _fail(messages)
    return tables


def _plastic_rows(value) -> dict[str, tuple]:
    key = load_cases.PLASTIC_TABLE_KEY
    frame = load_cases.editor_table(load_cases.active_table(value, key), key)
    return {
        str(record[load_cases.NAME]): tuple(
            str(record[column]) for column in load_cases.TABLE_COLUMNS[key]
        )
        for record in frame.to_dict("records")
    }


def import_cases(tables: Mapping, authorities, *, text: str, mode: str):
    """Return the new case tables, torsion declarations and imported counts.

    ``mode`` "append" adds the imported cases after the current cases. The
    torsion declarations of the imported names are removed, as for a paste.
    ``mode`` "replace" replaces both tables. A declaration stays only for a
    Plastic case with the same name and the same action values.
    """

    imported = parse(text)
    current = {
        key: load_cases.normalise_table(tables.get(key), key)
        for key in load_cases.CASE_TABLE_KEYS
    }
    mapping = copy.deepcopy(authorities) if isinstance(authorities, Mapping) else {}
    if mode == "replace":
        result = imported
        before = _plastic_rows(current[load_cases.PLASTIC_TABLE_KEY])
        after = _plastic_rows(result[load_cases.PLASTIC_TABLE_KEY])
        mapping = {
            name: value for name, value in mapping.items()
            if name in after and before.get(name) == after[name]
        }
    elif mode == "append":
        result = {}
        for key in load_cases.CASE_TABLE_KEYS:
            joined = pd.concat(
                [load_cases.editor_table(current[key], key),
                 load_cases.editor_table(imported[key], key)],
                ignore_index=True,
            )
            result[key] = load_cases.normalise_table(joined, key)
            for name in imported[key][load_cases.NAME]:
                mapping.pop(str(name), None)
    else:
        raise ValueError("Select append or replace.")
    errors = load_cases.validation_errors(
        result[load_cases.PLASTIC_TABLE_KEY], result[load_cases.ELASTIC_TABLE_KEY]
    )
    if errors:
        raise ValueError("; ".join(str(error) for error in errors))
    counts = {key: len(imported[key]) for key in load_cases.CASE_TABLE_KEYS}
    return result, mapping, counts
