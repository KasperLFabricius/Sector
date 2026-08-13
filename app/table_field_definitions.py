"""Shared, Streamlit-free definitions for Sector's editable input tables.

The registry is the canonical language boundary between table persistence,
validation and presentation.  Editable controls may use plain ``label`` and
``help`` text, while mathematical guides use ``math_symbol`` and ``unit``.  A
field's blank policy is explicit so that an omitted action cannot be confused
with an omitted optional value.
"""

from __future__ import annotations

import math
import re
import struct
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class BlankPolicy(str, Enum):
    """Meaning assigned to an empty editable cell."""

    ZERO = "zero"
    NULL = "null"
    REQUIRED = "required"
    EMPTY_TEXT = "empty_text"
    DEFAULT = "default"


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    """One stable field contract shared by every user-facing surface."""

    key: str
    label: str
    help: str
    math_symbol: str
    unit: str
    definition: str
    sign: str
    blank: BlankPolicy
    source: str
    default: str | float | bool | None = None

    @property
    def required(self) -> bool:
        """Whether a nonblank value is required for an active row."""

        return self.blank is BlankPolicy.REQUIRED


class DecimalParseError(ValueError):
    """Raised when an editable numeric value is ambiguous or non-finite."""


# Keep the marker a finite-width IEEE-754 NaN with a payload different from the
# ordinary NaN emitted for an empty pandas cell.  The attrs ledger supplies the
# human-readable issue; the payload only distinguishes "still malformed" from
# "the engineer cleared this cell" after a numeric editor round trip.
_INVALID_DECIMAL_BITS = 0x7FF8_0000_0053_EC70
INVALID_DECIMAL_CELLS_ATTR = "sector_invalid_decimal_cells_v1"


def _as_float(value: object) -> float:
    """Runtime float protocol used for pandas/numpy scalar compatibility."""

    return float(value)  # type: ignore[arg-type]


def invalid_decimal_sentinel() -> float:
    """Return the internal float sentinel for a malformed nonblank cell."""

    return struct.unpack(">d", struct.pack(">Q", _INVALID_DECIMAL_BITS))[0]


def is_invalid_decimal_sentinel(value: object) -> bool:
    """Whether ``value`` retains Sector's malformed-cell NaN payload."""

    try:
        number = _as_float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isnan(number):
        return False
    bits = struct.unpack(">Q", struct.pack(">d", number))[0]
    return bits == _INVALID_DECIMAL_BITS


def decimal_issue_ledger(
    attrs: Mapping[object, object] | None,
) -> dict[tuple[int, str], str]:
    """Return a sanitized copy of a canonical DataFrame's issue ledger."""

    raw = attrs.get(INVALID_DECIMAL_CELLS_ATTR) if attrs is not None else None
    if not isinstance(raw, Mapping):
        return {}
    ledger: dict[tuple[int, str], str] = {}
    for key, message in raw.items():
        if (
            isinstance(key, tuple)
            and len(key) == 2
            and isinstance(key[0], int)
            and key[0] >= 0
            and isinstance(key[1], str)
            and isinstance(message, str)
            and message
        ):
            ledger[(key[0], key[1])] = message
    return ledger


def set_decimal_issue_ledger(
    attrs: MutableMapping[object, object],
    ledger: Mapping[tuple[int, str], str],
) -> None:
    """Replace the issue ledger without leaving an empty stale attribute."""

    if ledger:
        attrs[INVALID_DECIMAL_CELLS_ATTR] = dict(ledger)
    else:
        attrs.pop(INVALID_DECIMAL_CELLS_ATTR, None)


def decimal_is_blank(value: object) -> bool:
    """Return whether a numeric editor value is an ordinary blank.

    Leading and trailing whitespace alone is blank.  Internal whitespace is not:
    it is rejected by :func:`parse_decimal` as ambiguous grouping.
    """

    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if is_invalid_decimal_sentinel(value):
        return False
    value_type = type(value)
    if value_type.__name__ == "NAType" and value_type.__module__.startswith(
        "pandas"
    ):
        return True
    try:
        return math.isnan(_as_float(value))
    except (TypeError, ValueError, OverflowError):
        return False


_DECIMAL_RE = re.compile(
    r"^[+-]?(?:(?:[0-9]+(?:[.,][0-9]*)?)|(?:[.,][0-9]+))"
    r"(?:[eE][+-]?[0-9]+)?$"
)


def parse_decimal(
    value: object,
    *,
    blank: BlankPolicy = BlankPolicy.REQUIRED,
    default: float | None = None,
) -> float | None:
    """Parse one strict, unambiguous decimal editor value.

    A dot or comma is accepted as the single decimal separator, including with
    a sign and exponent.  Mixed/repeated separators, grouping whitespace,
    booleans and non-finite values are rejected.  Blank handling is controlled
    by the caller's field definition.
    """

    if decimal_is_blank(value):
        if blank is BlankPolicy.ZERO:
            return 0.0
        if blank is BlankPolicy.NULL:
            return None
        if blank is BlankPolicy.DEFAULT:
            if default is None:
                raise DecimalParseError("a numeric default is required")
            return parse_decimal(default)
        if blank is BlankPolicy.EMPTY_TEXT:
            raise DecimalParseError("empty-text policy is not numeric")
        raise DecimalParseError("a value is required")

    value_type = type(value)
    if isinstance(value, bool) or (
        value_type.__name__ == "bool_"
        and value_type.__module__.startswith("numpy")
    ):
        raise DecimalParseError("booleans are not decimal numbers")

    if isinstance(value, str):
        text = value.strip()
        if not _DECIMAL_RE.fullmatch(text):
            raise DecimalParseError("enter one unambiguous decimal number")
        text = text.replace(",", ".")
        try:
            number = float(text)
        except (TypeError, ValueError, OverflowError) as exc:
            raise DecimalParseError("enter one unambiguous decimal number") from exc
    else:
        try:
            number = _as_float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise DecimalParseError("enter one decimal number") from exc

    if not math.isfinite(number):
        raise DecimalParseError("enter a finite decimal number")
    return number


CONCRETE_CORNERS_TABLE_KEY = "corners_base"
CONCRETE_VOIDS_TABLE_KEY = "hole_base"
BARS_TABLE_KEY = "bars_base"
TENDONS_TABLE_KEY = "tendons_base"
PLASTIC_CASES_TABLE_KEY = "plastic_cases_base"
ELASTIC_CASES_TABLE_KEY = "elastic_cases_base"
FATIGUE_SPECTRUM_TABLE_KEY = "fatigue_spectrum_base"

TABLE_KEYS = (
    CONCRETE_CORNERS_TABLE_KEY,
    CONCRETE_VOIDS_TABLE_KEY,
    BARS_TABLE_KEY,
    TENDONS_TABLE_KEY,
    PLASTIC_CASES_TABLE_KEY,
    ELASTIC_CASES_TABLE_KEY,
    FATIGUE_SPECTRUM_TABLE_KEY,
)

TABLE_TITLES = MappingProxyType(
    {
        CONCRETE_CORNERS_TABLE_KEY: "Concrete corner points",
        CONCRETE_VOIDS_TABLE_KEY: "Concrete void points",
        BARS_TABLE_KEY: "Reinforcing bars",
        TENDONS_TABLE_KEY: "Prestressing tendons",
        PLASTIC_CASES_TABLE_KEY: "Plastic and capacity cases",
        ELASTIC_CASES_TABLE_KEY: "Elastic cases",
        FATIGUE_SPECTRUM_TABLE_KEY: "Grouped fatigue spectrum",
    }
)

_LATEX_UNITS = MappingProxyType(
    {
        "-": "",
        "mm": r"\mathrm{mm}",
        "mm^2": r"\mathrm{mm}^{2}",
        "kN": r"\mathrm{kN}",
        "kN m": r"\mathrm{kN\,m}",
        "cycles": r"\mathrm{cycles}",
    }
)


def latex_unit(unit: str) -> str:
    """Return the supported inline-math unit fragment, failing closed."""

    try:
        return _LATEX_UNITS[unit]
    except KeyError as exc:
        raise ValueError(f"unsupported editable-table unit: {unit}") from exc


def input_rule(definition: FieldDefinition) -> str:
    """Return the concise human wording for one blank/default contract."""

    if definition.blank is BlankPolicy.ZERO:
        return "Blank = 0"
    if definition.blank is BlankPolicy.NULL:
        return "Blank = not provided"
    if definition.blank is BlankPolicy.REQUIRED:
        return "Required"
    if definition.blank is BlankPolicy.EMPTY_TEXT:
        return "Blank = empty text"
    return f"Blank = {definition.default}"


_TABLE_METHOD_DEPENDENCIES = MappingProxyType({
    CONCRETE_CORNERS_TABLE_KEY: "All section calculations and section figures",
    CONCRETE_VOIDS_TABLE_KEY: "All section calculations and section figures",
    BARS_TABLE_KEY: (
        "Plastic, Elastic/crack, fatigue, detailing and resistance checks as used"
    ),
    TENDONS_TABLE_KEY: (
        "Plastic, Elastic/crack, fatigue and resistance checks as used"
    ),
    PLASTIC_CASES_TABLE_KEY: (
        "Plastic capacity, minimum reinforcement, shear, torsion and combined M-V-T"
    ),
    ELASTIC_CASES_TABLE_KEY: "Elastic stresses, cracking and ordinary crack width",
    FATIGUE_SPECTRUM_TABLE_KEY: "Grouped reinforcement and concrete fatigue",
})


def validation_rule(definition: FieldDefinition) -> str:
    """Return one explicit manual validation rule from the canonical field role."""

    if definition.key == "cycles":
        return "Required finite number greater than zero."
    if definition.key in {"name", "spectrum"}:
        return "Required stable identity; uniqueness is enforced in its table scope."
    if definition.key == "description":
        return "Optional project text."
    if definition.key == "material_id":
        return "Required ID that must resolve to the matching material catalogue."
    if definition.key == "area_mm2":
        return "Required finite area greater than zero."
    if definition.key == "calculate_crack_width":
        return "Boolean request; off means crack width is not requested."
    if definition.unit != "-" or definition.math_symbol != "-":
        return "Finite unambiguous decimal; the field-specific sign rule applies."
    return "Value must satisfy the table-owned type and identity contract."


def method_dependency(table_key: str, definition: FieldDefinition) -> str:
    """Return the calculation families that consume one registered table field."""

    # Validate both identities before returning shared prose.
    if definition not in table_fields(table_key):
        raise ValueError(
            f"field {definition.key!r} does not belong to editable table {table_key!r}"
        )
    return _TABLE_METHOD_DEPENDENCIES[table_key]


def _field(
    key: str,
    label: str,
    help_text: str,
    math_symbol: str,
    unit: str,
    definition: str,
    sign: str,
    blank: BlankPolicy,
    source: str = "User input",
    default: str | float | bool | None = None,
) -> FieldDefinition:
    return FieldDefinition(
        key=key,
        label=label,
        help=help_text,
        math_symbol=math_symbol,
        unit=unit,
        definition=definition,
        sign=sign,
        blank=blank,
        source=source,
        default=default,
    )


_XY_FIELDS = (
    _field(
        "x (mm)", "x coordinate",
        "Point x coordinate from the section origin, in millimetres.",
        "x", "mm", "Horizontal coordinate of the point.",
        "Positive in the section's declared positive x direction.",
        BlankPolicy.REQUIRED,
    ),
    _field(
        "y (mm)", "y coordinate",
        "Point y coordinate from the section origin, in millimetres.",
        "y", "mm", "Vertical coordinate of the point.",
        "Positive in the section's declared positive y direction.",
        BlankPolicy.REQUIRED,
    ),
)


def _reinforcement_fields(kind: str) -> tuple[FieldDefinition, ...]:
    is_bar = kind == "bar"
    prefix = "R" if is_bar else "P"
    material = "M1" if is_bar else "P1"
    noun = "bar" if is_bar else "tendon"
    return (
        _field(
            "ID", f"{noun.capitalize()} ID", f"Stable identifier for this {noun}.",
            "i", "-", "Stable row identity used by calculations and reports.",
            "Identifiers carry no physical sign.", BlankPolicy.DEFAULT,
            "Sector generated",
            f"next {prefix} number above the highest retained suffix",
        ),
        *_XY_FIELDS,
        _field(
            "size mode", "Size input", "Choose whether area or diameter controls the size.",
            "-", "-", "Selects the authoritative size input for the element.",
            "Not applicable.", BlankPolicy.DEFAULT, "User selection", "Area",
        ),
        _field(
            "area (mm2)", "Area",
            f"Cross-sectional area of one {noun}, in square millimetres; "
            "derived from diameter when Diameter controls the size.",
            "A_s" if is_bar else "A_p", "mm^2",
            f"Cross-sectional area of the {noun}.", "Area is positive.",
            BlankPolicy.NULL,
        ),
        _field(
            "diameter (mm)", "Diameter",
            f"Equivalent circular diameter of one {noun}, in millimetres; "
            "derived from area when Area controls the size.",
            "\\phi_s" if is_bar else "\\phi_p", "mm",
            f"Diameter used for the {noun}'s size and detailing checks.",
            "Diameter is positive.", BlankPolicy.NULL,
        ),
        _field(
            "material ID", "Material ID", f"Material-law identifier assigned to this {noun}.",
            "-", "-", "Links the element to its material definition.",
            "Identifiers carry no physical sign.", BlankPolicy.DEFAULT,
            "User assignment", material,
        ),
        _field(
            "fatigue detail ID", "Fatigue detail ID",
            f"Optional fatigue-resistance detail assigned to this {noun}.",
            "-", "-", "Links the element to a fatigue resistance definition.",
            "Identifiers carry no physical sign.", BlankPolicy.EMPTY_TEXT,
            "User assignment",
        ),
    )


def _action(
    key: str,
    label: str,
    symbol: str,
    unit: str,
    definition: str,
    sign: str,
) -> FieldDefinition:
    return _field(
        key, label, f"{definition} Leave blank to use zero.", symbol, unit,
        definition, sign, BlankPolicy.ZERO, default=0.0,
    )


_CASE_ID_FIELDS = (
    _field(
        "name", "Name", "Required case name, unique across all action tables.",
        "-", "-", "Stable user-facing action-case identity.",
        "Names carry no physical sign.", BlankPolicy.REQUIRED,
    ),
    _field(
        "description", "Description", "Optional project description of the case.",
        "-", "-", "Project-defined action or combination description.",
        "Not applicable.", BlankPolicy.EMPTY_TEXT,
    ),
)

_PLASTIC_FIELDS = (
    *_CASE_ID_FIELDS,
    _action("n_ed_kn", "Axial force", "N_{Ed}", "kN",
            "Design axial force.", "Tension is positive; compression is negative."),
    _action("mx_ed_knm", "Moment about x", "M_{x,Ed}", "kN m",
            "Design moment about the x axis.", "Uses the declared section-axis sign."),
    _action("my_ed_knm", "Moment about y", "M_{y,Ed}", "kN m",
            "Design moment about the y axis.", "Uses the declared section-axis sign."),
    _action("vx_ed_kn", "Shear along x", "V_{x,Ed}", "kN",
            "Signed design shear along x, paired with bending about y.",
            "Uses the declared positive x direction."),
    _action("vy_ed_kn", "Shear along y", "V_{y,Ed}", "kN",
            "Signed design shear along y, paired with bending about x.",
            "Uses the declared positive y direction."),
    _field(
        "vx_face", "Vx face", "Face used for the Vx shear check; Auto derives it from My.",
        "-", "-", "Selects the physical face assessed for shear along x.",
        "Negative is left; positive is right.", BlankPolicy.DEFAULT,
        "User selection", "auto",
    ),
    _field(
        "vy_face", "Vy face", "Face used for the Vy shear check; Auto derives it from Mx.",
        "-", "-", "Selects the physical face assessed for shear along y.",
        "Negative is bottom; positive is top.", BlankPolicy.DEFAULT,
        "User selection", "auto",
    ),
    _action("t_ed_knm", "Torsion", "T_{Ed}", "kN m",
            "Signed design torsion action.", "Uses the declared positive torsion sense."),
    _field(
        "check_minimum_reinforcement", "Minimum reinforcement",
        "Enable the minimum-reinforcement check for this case.", "-", "-",
        "Requests the modelled-direction minimum-reinforcement assessment.",
        "Not applicable.", BlankPolicy.DEFAULT, "User selection", False,
    ),
)

_ELASTIC_FIELDS = (
    *_CASE_ID_FIELDS,
    _action("n_long_ed_kn", "Sustained axial force", "N_{Ed,long}", "kN",
            "Sustained axial-force part.", "Tension is positive; compression is negative."),
    _action("mx_long_ed_knm", "Sustained moment about x", "M_{x,Ed,long}", "kN m",
            "Sustained moment part about x.", "Uses the declared section-axis sign."),
    _action("my_long_ed_knm", "Sustained moment about y", "M_{y,Ed,long}", "kN m",
            "Sustained moment part about y.", "Uses the declared section-axis sign."),
    _action("n_short_ed_kn", "Instantaneous axial force", "N_{Ed,short}", "kN",
            "Instantaneous axial-force part.", "Tension is positive; compression is negative."),
    _action("mx_short_ed_knm", "Instantaneous moment about x", "M_{x,Ed,short}", "kN m",
            "Instantaneous moment part about x.", "Uses the declared section-axis sign."),
    _action("my_short_ed_knm", "Instantaneous moment about y", "M_{y,Ed,short}", "kN m",
            "Instantaneous moment part about y.", "Uses the declared section-axis sign."),
    _field(
        "calculate_crack_width", "Calculate crack width",
        "Run the selected crack-width calculation for this case.", "-", "-",
        "Requests numerical crack-width calculation for the elastic action.",
        "Not applicable.", BlankPolicy.DEFAULT, "User selection", False,
    ),
)

_FATIGUE_FIELDS = (
    _field(
        "spectrum", "Spectrum", "Required spectrum name; equal names accumulate damage.",
        "-", "-", "Identity of the independently accumulated fatigue spectrum.",
        "Names carry no physical sign.", BlankPolicy.REQUIRED,
    ),
    _field(
        "name", "Bin name", "Required bin name, unique across all action tables.",
        "-", "-", "Stable user-facing identity of the spectrum bin.",
        "Names carry no physical sign.", BlankPolicy.REQUIRED,
    ),
    _field(
        "description", "Description", "Optional project description of the bin.",
        "-", "-", "Project-defined spectrum-bin description.",
        "Not applicable.", BlankPolicy.EMPTY_TEXT,
    ),
    _field(
        "cycles", "Cycles", "Required number of cycles represented by this bin.",
        "n_i", "cycles", "Number of repetitions represented by the bin.",
        "Cycles must be greater than zero.", BlankPolicy.REQUIRED,
    ),
    _action("n_long_ed_kn", "Basic axial force", "N_{Ed,long}", "kN",
            "Sustained or basic axial force.", "Tension is positive; compression is negative."),
    _action("mx_long_ed_knm", "Basic moment about x", "M_{x,Ed,long}", "kN m",
            "Sustained or basic moment about x.", "Uses the declared section-axis sign."),
    _action("my_long_ed_knm", "Basic moment about y", "M_{y,Ed,long}", "kN m",
            "Sustained or basic moment about y.", "Uses the declared section-axis sign."),
    _action("n_short_ed_kn", "Cyclic axial increment", "\\Delta N_{Ed}", "kN",
            "Cyclic axial-force increment added to the basic state.",
            "Tension is positive; compression is negative."),
    _action("mx_short_ed_knm", "Cyclic moment increment about x", "\\Delta M_{x,Ed}", "kN m",
            "Cyclic moment increment about x.", "Uses the declared section-axis sign."),
    _action("my_short_ed_knm", "Cyclic moment increment about y", "\\Delta M_{y,Ed}", "kN m",
            "Cyclic moment increment about y.", "Uses the declared section-axis sign."),
)

TABLE_FIELD_DEFINITIONS = MappingProxyType(
    {
        CONCRETE_CORNERS_TABLE_KEY: _XY_FIELDS,
        CONCRETE_VOIDS_TABLE_KEY: _XY_FIELDS,
        BARS_TABLE_KEY: _reinforcement_fields("bar"),
        TENDONS_TABLE_KEY: _reinforcement_fields("tendon"),
        PLASTIC_CASES_TABLE_KEY: _PLASTIC_FIELDS,
        ELASTIC_CASES_TABLE_KEY: _ELASTIC_FIELDS,
        FATIGUE_SPECTRUM_TABLE_KEY: _FATIGUE_FIELDS,
    }
)


def table_fields(table_key: str) -> tuple[FieldDefinition, ...]:
    """Return the ordered field definitions for one editable table."""

    try:
        return TABLE_FIELD_DEFINITIONS[table_key]
    except KeyError as exc:
        raise ValueError(f"unknown editable table: {table_key}") from exc


def field_definition(table_key: str, field_key: str) -> FieldDefinition:
    """Return one field definition, failing closed for an unknown field."""

    for definition in table_fields(table_key):
        if definition.key == field_key:
            return definition
    raise ValueError(f"unknown field {field_key!r} for editable table {table_key!r}")


def field_map(table_key: str) -> Mapping[str, FieldDefinition]:
    """Return an immutable key-to-definition view for one table."""

    return MappingProxyType({item.key: item for item in table_fields(table_key)})


def _validate_registry() -> None:
    if tuple(TABLE_FIELD_DEFINITIONS) != TABLE_KEYS:
        raise RuntimeError("editable-table registry order is not deterministic")
    for table_key, definitions in TABLE_FIELD_DEFINITIONS.items():
        keys = [item.key for item in definitions]
        if len(keys) != len(set(keys)):
            raise RuntimeError(f"duplicate field key in {table_key}")
        for item in definitions:
            for attribute in (
                "key", "label", "help", "math_symbol", "unit", "definition",
                "sign", "source",
            ):
                if not str(getattr(item, attribute)).strip():
                    raise RuntimeError(f"blank {attribute} for {table_key}.{item.key}")
            if "$" in item.label or "\\" in item.label:
                raise RuntimeError(f"editor label is not plain text: {table_key}.{item.key}")
            if "$" in item.help or "\\" in item.help:
                raise RuntimeError(f"editor help is not plain text: {table_key}.{item.key}")
            if item.blank is BlankPolicy.DEFAULT and item.default is None:
                raise RuntimeError(f"missing default for {table_key}.{item.key}")
            latex_unit(item.unit)


_validate_registry()
