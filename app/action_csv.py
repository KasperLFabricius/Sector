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
import functools
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
MAX_CASE_ROWS = 5000
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


_UTF16_BOMS = (bytes((0xFF, 0xFE)), bytes((0xFE, 0xFF)))
_SAVE_AS_UTF8 = "Save the file as CSV UTF-8 and import it again."


def decode(data: bytes) -> str:
    """Decode an uploaded file: UTF-8 (with or without BOM), else Windows-1252.

    A UTF-16 file (for example Excel "Unicode text") gives one message.
    """

    if len(data) > MAX_BYTES:
        raise ValueError("The file is too large. Sector reads at most 2 MB.")
    if data.startswith(_UTF16_BOMS) or bytes(1) in data:
        raise ValueError("The file uses UTF-16 or contains null characters. " + _SAVE_AS_UTF8)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise ValueError(_SAVE_AS_UTF8) from exc


_VERSION_MARK_RE = re.compile(r'"?#\s*sector-actions-csv\b', re.IGNORECASE)


def is_versioned(text: str) -> bool:
    """Whether the first nonblank line starts with the CSV version mark."""

    for line in str(text).lstrip(_BOM).splitlines():
        if line.strip():
            return _VERSION_MARK_RE.match(line.strip()) is not None
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
            shown.append(f"The file has {len(messages) - MAX_MESSAGES} more issues.")
        raise ValueError(" ".join(shown))


def _width(cells: list[str], width: int, raw_width: int, line: int,
           messages: list[str]):
    """Return the cells of one row, or ``None`` with a message.

    A spreadsheet pads the heading row and the data rows to one width, so the
    raw width of the heading row (with its blank cells at the end) is the
    limit. A row with more cells (for example an unquoted comma decimal) is
    rejected, so that no value moves to the next column. Cells under a blank
    heading must be blank.
    """

    cells = list(cells)
    if len(cells) > raw_width:
        messages.append(
            f"Line {line} has {len(cells)} cells. The heading row has "
            f"{raw_width}. Put each comma decimal in quotes."
        )
        return None
    if any(cells[width:]):
        messages.append(
            f"Line {line} has a value in a column without a heading."
        )
        return None
    cells = cells[:width]
    if len(cells) != width:
        messages.append(
            f"Line {line} has {len(cells)} cells. The heading row has {width}."
        )
        return None
    return cells


def _records(text: str, delimiter: str) -> list[tuple[int, list[str]]]:
    """Return the records (empty lines left out) with the first physical line of each."""

    reader = csv.reader(io.StringIO(text), delimiter=delimiter, strict=True)
    rows = []
    start = 1
    while True:
        try:
            cells = next(reader)
        except StopIteration:
            return rows
        except csv.Error as exc:
            reason = str(exc)
            if "field larger than field limit" in reason:
                detail = "A cell has more than 131072 characters."
            else:
                detail = ("A quoted cell is not closed correctly. Put each quoted "
                          "value between two quote characters.")
            raise ValueError(f"Line {start}: Sector cannot read this line. {detail}") from exc
        cells = [cell.strip() for cell in cells]
        if cells:
            rows.append((start, cells))
        start = reader.line_num + 1


@functools.lru_cache(maxsize=4)
def _parse_cached(text: str):
    text = str(text).lstrip(_BOM)
    rows = []
    for record in _records(text, _delimiter(text.splitlines())):
        # Keep the units row (the record after the heading row) also when all
        # its cells are blank, for example "," for limit_state and name.
        if any(record[1]) or len(rows) == 2:
            rows.append(record)
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
    raw_width = len(header)
    header = list(header)
    while header and not header[-1]:
        header.pop()
    header = [cell.casefold() for cell in header]
    width = len(header)
    messages: list[str] = []
    if not all(header):
        raise ValueError(f"Line {line}: give each column a heading.")
    if len(header) != len(set(header)):
        raise ValueError(f"Line {line}: use each column heading once.")
    unknown = [cell for cell in header if cell not in COLUMNS]
    if unknown:
        raise ValueError(
            f'Line {line}: the column headings "{", ".join(unknown)}" are not '
            "known. Use the headings of the template."
        )
    for required in (LIMIT_STATE, load_cases.NAME):
        if required not in header:
            raise ValueError(f"Line {line}: add the {required} column.")
    line, units = rows[2]
    units = _width(units, width, raw_width, line, messages)
    _fail(messages)
    for column, unit in zip(header, units):
        if _unit_token(unit) != _unit_token(UNITS[column]):
            expected = (f'"{UNITS[column]}"' if UNITS[column] != "-"
                        else '"-" or blank')
            messages.append(
                f"Line {line} (units row): the unit of {column} must be "
                f'{expected}. The file has "{unit}".'
            )
    _fail(messages)
    if len(rows) - 3 > MAX_CASE_ROWS:
        raise ValueError(
            f"The file has more than {MAX_CASE_ROWS} case rows. Split the file."
        )
    if len(rows) < 4:
        raise ValueError("Add at least one case row after the units row.")
    records = {key: [] for key in load_cases.CASE_TABLE_KEYS}
    lines = {key: [] for key in load_cases.CASE_TABLE_KEYS}
    for line, cells in rows[3:]:
        cells = _width(cells, width, raw_width, line, messages)
        if cells is None:
            continue
        record = dict(zip(header, cells))
        limit_state = record[LIMIT_STATE].upper()
        key = LIMIT_STATE_TABLES.get(limit_state)
        if key is None:
            messages.append(f"Line {line}: {LIMIT_STATE} must be ULS or SLS.")
            continue
        foreign = [
            column for column in header
            if record[column] and _column_table(column) not in {None, key}
        ]
        if foreign:
            messages.append(
                f"Line {line}: leave {', '.join(foreign)} blank in a "
                f"{limit_state} row."
            )
        if not record[load_cases.NAME]:
            messages.append(f"Line {line}: enter a case name.")
        for flag in load_cases.FLAG_COLUMNS[key]:
            if flag in record and record[flag].casefold() not in _FLAG_TOKENS:
                messages.append(f"Line {line}: use true or false in {flag}.")
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
                f'number. The file has "{entered}".'
            )
        for position, row in enumerate(frame.to_dict("records")):
            for column in load_cases.PLASTIC_FACE_COLUMNS:
                if column in row and row[column] not in load_cases.FACE_OPTIONS:
                    messages.append(
                        f"Line {lines[key][position]}: {column} must be auto, "
                        "negative or positive."
                    )
            for column in load_cases.ATTRIBUTE_COLUMNS:
                reason = load_cases.attribute_error(column, row[column])
                if reason is not None:
                    messages.append(
                        f"Line {lines[key][position]}: {column} {reason}."
                    )
        tables[key] = frame
    _fail(messages)
    return tables, {key: tuple(value) for key, value in lines.items()}


def _parse(text: str):
    tables, lines = _parse_cached(str(text))
    return {key: frame.copy(deep=True) for key, frame in tables.items()}, lines


def parse(text: str) -> dict[str, pd.DataFrame]:
    """Read a CSV v1 text into the canonical Plastic and Elastic tables.

    Raise ``ValueError`` with the line number when the file form, a CSV quote
    or a value is not valid. No partial result is returned. The last parsed
    texts are kept, so a rerun with the same file does not parse it again.
    """

    return _parse(text)[0]


def _plastic_rows(value) -> dict[str, tuple]:
    key = load_cases.PLASTIC_TABLE_KEY
    frame = load_cases.editor_table(load_cases.active_table(value, key), key)
    return {
        str(record[load_cases.NAME]): tuple(
            str(record[column]) for column in load_cases.TABLE_COLUMNS[key]
        )
        for record in frame.to_dict("records")
    }


def _names(value, key) -> list[str]:
    frame = load_cases.active_table(value, key)
    return [str(name).strip() for name in frame[load_cases.NAME]]


def import_cases(tables: Mapping, authorities, *, text: str, mode: str,
                 reserved_names=()):
    """Return the new case tables, torsion declarations and imported counts.

    ``mode`` "append" adds the imported cases after the current cases. The
    torsion declarations of the imported names are removed, as for a paste.
    ``mode`` "replace" replaces both tables. A declaration stays only for a
    Plastic case with the same name and the same entries in each Plastic
    column (the case attributes are not compared). ``reserved_names`` are
    other names in use, for example the fatigue bins.
    """

    imported, lines = _parse(text)
    current = {
        key: load_cases.normalise_table(tables.get(key), key)
        for key in load_cases.CASE_TABLE_KEYS
    }
    mapping = copy.deepcopy(authorities) if isinstance(authorities, Mapping) else {}
    if mode not in {"append", "replace"}:
        raise ValueError("Select append or replace.")
    used = {str(name).strip().casefold(): "a fatigue bin" for name in reserved_names}
    if mode == "append":
        for key in load_cases.CASE_TABLE_KEYS:
            for name in _names(current[key], key):
                used.setdefault(name.casefold(), "a current case")
    messages = []
    for key in load_cases.CASE_TABLE_KEYS:
        for name, line in zip(_names(imported[key], key), lines[key]):
            folded = name.casefold()
            if folded in used:
                messages.append(
                    f'Line {line}: the case name "{name}" is already used by '
                    f"{used[folded]}. Use a unique name for each case."
                )
            used[folded] = "an earlier line of the file"
    _fail(messages)
    if mode == "replace":
        result = imported
        before = _plastic_rows(current[load_cases.PLASTIC_TABLE_KEY])
        after = _plastic_rows(result[load_cases.PLASTIC_TABLE_KEY])
        mapping = {
            name: value for name, value in mapping.items()
            if name in after and before.get(name) == after[name]
        }
    else:
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
    errors = load_cases.validation_errors(
        result[load_cases.PLASTIC_TABLE_KEY], result[load_cases.ELASTIC_TABLE_KEY]
    )
    if errors:
        raise ValueError(" ".join(f"{error.text}." for error in errors))
    counts = {key: len(imported[key]) for key in load_cases.CASE_TABLE_KEYS}
    return result, mapping, counts, imported
