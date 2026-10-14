"""Typed UI destinations for authored input-validation messages."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app import engineer_messages, load_cases
from app.manual_information_architecture import INPUT_STAGES as REGISTERED_STAGES
from app.table_field_definitions import field_definition
from sector.engineer_message import EngineerMessage

_STAGE_LABELS = {stage.key: stage.label for stage in REGISTERED_STAGES}
ANALYSIS_SETTINGS = _STAGE_LABELS["analysis-settings"]
SECTION = _STAGE_LABELS["section"]
MATERIAL_PARAMETERS = _STAGE_LABELS["material-parameters"]
LOADS = _STAGE_LABELS["loads"]
PROJECT = _STAGE_LABELS["project"]
# Compatibility name for downstream imports; the stage itself is Project-only.
PROJECT_REPORT = PROJECT

INPUT_STAGES = frozenset(
    {
        ANALYSIS_SETTINGS,
        SECTION,
        MATERIAL_PARAMETERS,
        LOADS,
        PROJECT,
    }
)
MATERIAL_FAMILIES = frozenset(
    {"Concrete", "Reinforcing steel", "Prestressing steel", "Fatigue details"}
)

_CASE_FALLBACK = EngineerMessage(
    "ACTION-CASES",
    "Review the Plastic and Elastic case tables before calculating",
)
_HEIGHTENED_FALLBACK = EngineerMessage(
    "HEIGHTENED-INPUT",
    "Review the heightened crack-control inputs before calculating",
)
_SECTION_GEOMETRY_FALLBACK = EngineerMessage(
    "SECTION-GEOMETRY",
    "Review the concrete outline and void geometry",
)
_SECTION_MISSING = EngineerMessage(
    "SECTION-MISSING",
    "Define a section outline with at least three finite coordinate pairs",
)
_SECTION_VOID_FALLBACK = EngineerMessage(
    "SECTION-VOID",
    "Keep every void inside the outline without disconnecting the concrete",
)
_SECTION_REINFORCEMENT_FALLBACK = EngineerMessage(
    "SECTION-REINFORCEMENT",
    "Place every reinforcement element inside the concrete outline and outside voids",
)
_MATERIAL_ASSIGNMENT_FALLBACK = EngineerMessage(
    "MATERIAL-ASSIGNMENT",
    "Select a defined material for every reinforcement and member check",
)
_MATERIAL_DEFINITION_FALLBACK = EngineerMessage(
    "MATERIAL-DEFINITION",
    "Review the selected material values",
)
_TORSION_FACTOR_FALLBACK = EngineerMessage(
    "TORSION-FACTOR",
    "Enter a positive finite concrete tensile factor gamma_ct",
)
_MATERIAL_FALLBACK = EngineerMessage(
    "MATERIAL-INPUT",
    "Review the material definitions and assignments",
)


@dataclass(frozen=True, slots=True)
class CaseLocation:
    """Verified table cell, with identity independent of its display position.

    Unique case names survive row reordering. Ambiguous or absent names use the
    physical editor row only while both table snapshots remain unchanged.
    """

    table_key: str
    field_key: str
    row_position: int
    case_name: str | None
    row_digest: str
    tables_digest: str

    def __post_init__(self) -> None:
        if self.table_key not in load_cases.CASE_TABLE_KEYS:
            raise ValueError("unknown case table")
        if self.field_key not in load_cases.TABLE_COLUMNS[self.table_key]:
            raise ValueError("unknown case field")
        if type(self.row_position) is not int or self.row_position < 0:
            raise ValueError("case row position must be a nonnegative integer")
        if self.case_name is not None and (
            type(self.case_name) is not str or not self.case_name.strip()
        ):
            raise ValueError("case name must be nonblank or absent")
        for value in (self.row_digest, self.tables_digest):
            if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("case location requires snapshot digests")


@dataclass(frozen=True, slots=True)
class InputTarget:
    """One bounded correction destination in the Inputs workspace."""

    stage: str
    widget_key: str | None = None
    widget_label: str | None = None
    material_family: str | None = None
    material_id: str | None = None
    case_location: CaseLocation | None = None

    def __post_init__(self) -> None:
        if self.stage not in INPUT_STAGES:
            raise ValueError(f"unknown input stage: {self.stage!r}")
        if self.case_location is not None:
            if not isinstance(self.case_location, CaseLocation):
                raise TypeError("case location must be typed")
            expected = {
                load_cases.PLASTIC_TABLE_KEY: "plastic_cases_editor",
                load_cases.ELASTIC_TABLE_KEY: "elastic_cases_editor",
            }[self.case_location.table_key]
            if self.stage != LOADS or self.widget_key != expected:
                raise ValueError("case location must match its Actions editor")
        if (
            self.material_family is not None
            and self.material_family not in MATERIAL_FAMILIES
        ):
            raise ValueError(
                f"unknown material family: {self.material_family!r}"
            )
        if (
            self.material_family is not None
            and self.stage != MATERIAL_PARAMETERS
        ):
            raise ValueError(
                "a material-family destination must use Material parameters"
            )
        if self.material_id is not None:
            expected_prefix = {
                "Reinforcing steel": "M",
                "Prestressing steel": "P",
            }.get(self.material_family)
            if expected_prefix is None or not re.fullmatch(
                rf"{expected_prefix}[1-9][0-9]*", self.material_id
            ):
                raise ValueError(
                    "a material-ID destination must match its material family"
                )


@dataclass(frozen=True, slots=True)
class InputIssue:
    """One blocking message and its optional trustworthy correction target."""

    code: str
    message: EngineerMessage
    target: InputTarget | None = None


def _resolved(
    message: object,
    *,
    fallback: EngineerMessage,
    context: str,
) -> EngineerMessage:
    return engineer_messages.resolve(
        message,
        fallback=fallback,
        context=context,
    )


def _case_target(message: EngineerMessage) -> InputTarget | None:
    if message.code == "PLASTIC-SWEEP-BOUNDS":
        return InputTarget(
            ANALYSIS_SETTINGS,
            "v_max",
            "Neutral-axis sweep end angle",
        )
    if message.code == "PLASTIC-SWEEP-SPAN":
        return InputTarget(
            ANALYSIS_SETTINGS,
            widget_label="Neutral-axis sweep start and end angles",
        )
    if message.code in {
        "PLASTIC-SWEEP-INCREMENT",
        "PLASTIC-SWEEP-RESOLUTION",
    }:
        return InputTarget(
            ANALYSIS_SETTINGS,
            "v_inc",
            "Neutral-axis sweep maximum increment",
        )
    if message.code == "PLASTIC-SWEEP-VALUES":
        return InputTarget(
            ANALYSIS_SETTINGS,
            widget_label="Neutral-axis sweep",
        )
    if message.code in _CASE_TABLE_CODES[load_cases.PLASTIC_TABLE_KEY]:
        return InputTarget(
            LOADS,
            "plastic_cases_editor",
            "Plastic and capacity cases",
        )
    if message.code in _CASE_TABLE_CODES[load_cases.ELASTIC_TABLE_KEY]:
        return InputTarget(
            LOADS,
            "elastic_cases_editor",
            "Elastic cases",
        )
    if message.code == "CASE-NAME-UNIQUE":
        return InputTarget(LOADS, widget_label="Plastic and Elastic case tables")
    return None


_CASE_FIELDS = {
    "PLASTIC-CASE-NAME": "name", "ELASTIC-CASE-NAME": "name",
    "CASE-NAME-UNIQUE": "name",
    "PLASTIC-N-ED": "n_ed_kn", "PLASTIC-MX-ED": "mx_ed_knm",
    "PLASTIC-MY-ED": "my_ed_knm", "PLASTIC-VX-ED": "vx_ed_kn",
    "PLASTIC-VY-ED": "vy_ed_kn", "PLASTIC-T-ED": "t_ed_knm",
    "ELASTIC-N-LONG": "n_long_ed_kn",
    "ELASTIC-MX-LONG": "mx_long_ed_knm",
    "ELASTIC-MY-LONG": "my_long_ed_knm",
    "ELASTIC-N-SHORT": "n_short_ed_kn",
    "ELASTIC-MX-SHORT": "mx_short_ed_knm",
    "ELASTIC-MY-SHORT": "my_short_ed_knm",
}
_CASE_TABLE_CODES = {
    load_cases.PLASTIC_TABLE_KEY: {
        code for code in _CASE_FIELDS if code.startswith("PLASTIC-")
    } | {"PLASTIC-CASE-REQUIRED", "PLASTIC-SHEAR-FACE"},
    load_cases.ELASTIC_TABLE_KEY: {
        code for code in _CASE_FIELDS if code.startswith("ELASTIC-")
    } | {"ELASTIC-CASE-REQUIRED"},
}


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), default=str,
    ).encode("ascii")).hexdigest()


def _case_frames(plastic, elastic):
    return {
        key: load_cases.normalise_table(value, key)
        for key, value in zip(load_cases.CASE_TABLE_KEYS, (plastic, elastic))
    }


def _table_digest(frames) -> str:
    return _digest([
        (key, load_cases.editor_table(frame, key).to_dict("records"))
        for key, frame in frames.items()
    ])


def resolve_case_location(
    location: CaseLocation, plastic, elastic,
) -> int | None:
    """Return the current physical editor row, or expire stale/ambiguous focus.

    This helper changes no inputs or selection state. The UI can retain its
    current case selection when the requested destination has expired.
    """
    if not isinstance(location, CaseLocation):
        return None
    frames = _case_frames(plastic, elastic)
    frame = frames[location.table_key]
    if location.case_name is None:
        if _table_digest(frames) != location.tables_digest:
            return None
        position = location.row_position
    else:
        matches = [
            (key, position)
            for key, current in frames.items()
            for position, name in enumerate(current[load_cases.NAME])
            if name.casefold() == location.case_name.casefold()
        ]
        if len(matches) != 1 or matches[0][0] != location.table_key:
            return None
        position = matches[0][1]
    if position >= len(frame):
        return None
    current_row = load_cases.editor_table(frame, location.table_key).iloc[position]
    if _digest(current_row.to_dict()) != location.row_digest:
        return None
    return position


def _exact_case_targets(plastic, elastic):
    """Attach cell ownership to a replay of the unchanged table validator.

    The final equality check fails closed if validation order or ownership ever
    changes. Messages and acceptance criteria remain owned by load_cases.
    """
    frames = _case_frames(plastic, elastic)
    counts = Counter(
        name.casefold() for frame in frames.values()
        for name in frame[load_cases.NAME] if name
    )
    tables_digest = _table_digest(frames)
    expected = load_cases.validation_errors(plastic, elastic)
    targets = []
    seen = set()
    duplicate_message = None
    # Obtain the authored duplicate diagnostic from the validator itself.
    for message in expected:
        if message.code == "CASE-NAME-UNIQUE":
            duplicate_message = message
            break
    for key, frame in frames.items():
        editor_frame = load_cases.editor_table(frame, key)
        for position in range(len(frame)):
            one = frame.iloc[[position]].copy(deep=True)
            if load_cases.active_table(one, key).empty:
                continue
            row = frame.iloc[position].to_dict()
            name = row[load_cases.NAME]
            messages = load_cases.validation_errors(
                one if key == load_cases.PLASTIC_TABLE_KEY else None,
                one if key == load_cases.ELASTIC_TABLE_KEY else None,
            )
            if name:
                if name.casefold() in seen and duplicate_message is not None:
                    messages.insert(0, duplicate_message)
                seen.add(name.casefold())
            invalid_faces = iter(
                field for field in load_cases.PLASTIC_FACE_COLUMNS
                if key == load_cases.PLASTIC_TABLE_KEY
                and row[field] not in load_cases.FACE_OPTIONS
            )
            for message in messages:
                field = _CASE_FIELDS.get(message.code)
                if message.code == "PLASTIC-SHEAR-FACE":
                    field = next(invalid_faces, None)
                if field is None:
                    return ()
                location = CaseLocation(
                    key, field, position,
                    name if name and counts[name.casefold()] == 1 else None,
                    _digest(editor_frame.iloc[position].to_dict()), tables_digest,
                )
                editor = (
                    "plastic_cases_editor" if key == load_cases.PLASTIC_TABLE_KEY
                    else "elastic_cases_editor"
                )
                target = InputTarget(
                    LOADS, editor, field_definition(key, field).label,
                    case_location=location,
                )
                targets.append((message, target))
    if [message for message, _target in targets] != expected:
        return ()
    return tuple(targets)


def case_issues(
    errors: Iterable[object], *, plastic=None, elastic=None,
) -> tuple[InputIssue, ...]:
    """Adapt load-case diagnostics without granting provenance to raw values."""

    errors = tuple(errors)
    has_row_diagnostics = any(
        type(value) is EngineerMessage
        and (value.code in _CASE_FIELDS or value.code == "PLASTIC-SHEAR-FACE")
        for value in errors
    )
    exact = (
        _exact_case_targets(plastic, elastic)
        if has_row_diagnostics and (plastic is not None or elastic is not None)
        else ()
    )
    # Missing-table and sweep diagnostics can precede the row-level errors.
    # Only an exact trusted suffix grants row ownership. No message text parsing.
    exact_start = len(errors) - len(exact)
    use_exact = bool(exact) and exact_start >= 0 and all(
        type(value) is EngineerMessage and value == message
        for value, (message, _target) in zip(errors[exact_start:], exact)
    )
    issues = []
    for index, value in enumerate(errors, start=1):
        message = _resolved(
            value,
            fallback=_CASE_FALLBACK,
            context="load-case input issue",
        )
        target = _case_target(message)
        if use_exact and index - 1 >= exact_start:
            target = exact[index - 1 - exact_start][1]
        issues.append(InputIssue(
            code=f"case-{index}",
            message=message,
            target=target,
        ))
    return tuple(issues)


_HEIGHTENED_TARGETS = {
    "HEIGHTENED-ELASTIC-MODE": (
        InputTarget(
            ANALYSIS_SETTINGS,
            "mode",
            "Analysis mode",
        )
    ),
    "HEIGHTENED-DESIGN-BASIS": (
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_code",
            "Crack-width design basis",
        )
    ),
    "HEIGHTENED-REFERENCE-REQUIRED": (
        InputTarget(
            LOADS,
            "elastic_cases_editor",
            "Elastic cases",
        )
    ),
    "HEIGHTENED-REFERENCE-SELECT": (
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_heightened_reference_case",
            "Reference crack-enabled Elastic case",
        )
    ),
    "HEIGHTENED-ENABLED": (
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_heightened_on",
            "Optional DK NA heightened crack control",
        )
    ),
    "HEIGHTENED-SURFACE": (
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_heightened_reinforcement_surface",
            "Reinforcement surface",
        )
    ),
    "HEIGHTENED-TENSILE-STRENGTH": (
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_heightened_effective_tensile_strength_mpa",
            "Effective tensile strength",
        )
    ),
    "HEIGHTENED-CRACK-LIMIT": (
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_heightened_permitted_crack_width_mm",
            "Heightened permitted crack width",
        )
    ),
    "HEIGHTENED-FINE-AREA": (
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_heightened_fine_effective_tension_area_mm2",
            "Fine-system effective tension area",
        )
    ),
    "HEIGHTENED-COARSE-AREA": (
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_heightened_coarse_effective_tension_area_mm2",
            "Coarse-system effective tension area",
        )
    ),
}


def heightened_issues(errors: Iterable[object]) -> tuple[InputIssue, ...]:
    """Adapt heightened-check messages, failing closed on untyped values."""

    issues = []
    for index, value in enumerate(errors, start=1):
        message = _resolved(
            value,
            fallback=_HEIGHTENED_FALLBACK,
            context="heightened crack-control input issue",
        )
        target = _HEIGHTENED_TARGETS.get(message.code)
        issues.append(InputIssue(f"heightened-{index}", message, target))
    return tuple(issues)


def _material_definition_target(message: EngineerMessage) -> InputTarget | None:
    if message.code.startswith("MILD-"):
        family = "Reinforcing steel"
    elif message.code.startswith("PRESTRESS-"):
        family = "Prestressing steel"
    else:
        return InputTarget(
            MATERIAL_PARAMETERS,
            widget_label="Material values",
        )
    return InputTarget(
        MATERIAL_PARAMETERS,
        widget_label=f"{family} values",
        material_family=family,
    )


def section_issues(inp: Mapping) -> tuple[InputIssue, ...]:
    """Return section/material blockers already diagnosed by input assembly."""

    issues: list[InputIssue] = []
    geometry_error = inp.get("geometry_error")
    if geometry_error:
        message = _resolved(
            geometry_error,
            fallback=_SECTION_GEOMETRY_FALLBACK,
            context="section geometry input issue",
        )
        issues.append(InputIssue(
            "section-geometry",
            message,
            InputTarget(SECTION, widget_label="Section outline and void geometry"),
        ))
    elif inp.get("section") is None:
        issues.append(InputIssue(
            "section-missing",
            _SECTION_MISSING,
            InputTarget(SECTION, "ed_corners", "Section outline"),
        ))

    if inp.get("void_error"):
        issues.append(InputIssue(
            "section-void",
            _resolved(
                inp["void_error"],
                fallback=_SECTION_VOID_FALLBACK,
                context="section void input issue",
            ),
            InputTarget(SECTION, "ed_hole", "Void geometry"),
        ))
    if inp.get("steel_error"):
        message = _resolved(
            inp["steel_error"],
            fallback=_SECTION_REINFORCEMENT_FALLBACK,
            context="section reinforcement input issue",
        )
        issues.append(InputIssue(
            "section-reinforcement",
            message,
            InputTarget(SECTION, widget_label="Reinforcement geometry"),
        ))

    assignment_errors = tuple(inp.get("material_assignment_errors") or ())
    for index, value in enumerate(assignment_errors, start=1):
        message = _resolved(
            value,
            fallback=_MATERIAL_ASSIGNMENT_FALLBACK,
            context="material assignment input issue",
        )
        if message.code == "BAR-MATERIAL-ASSIGNMENT":
            target = InputTarget(SECTION, "ed_bars", "Bar material assignment")
        elif message.code == "TENDON-MATERIAL-ASSIGNMENT":
            target = InputTarget(
                SECTION,
                "ed_tendons",
                "Tendon material assignment",
            )
        elif message.code == "MEMBER-MATERIAL-ASSIGNMENT":
            target = InputTarget(
                ANALYSIS_SETTINGS,
                "capacity_steel_material_id",
                "Member-check material",
            )
        else:
            target = None
        issues.append(InputIssue(f"material-assignment-{index}", message, target))

    for index, value in enumerate(
        tuple(inp.get("material_definition_errors") or ()), start=1
    ):
        if (
            isinstance(value, InputIssue)
            and value.code == "material-definition"
        ):
            issues.append(InputIssue(
                f"material-definition-{index}",
                value.message,
                value.target,
            ))
            continue
        message = _resolved(
            value,
            fallback=_MATERIAL_DEFINITION_FALLBACK,
            context="material definition input issue",
        )
        issues.append(InputIssue(
            f"material-definition-{index}",
            message,
            _material_definition_target(message),
        ))

    if inp.get("torsion_gamma_ct_error"):
        issues.append(InputIssue(
            "torsion-gamma-ct",
            _resolved(
                inp["torsion_gamma_ct_error"],
                fallback=_TORSION_FACTOR_FALLBACK,
                context="torsion concrete tensile factor input issue",
            ),
            InputTarget(
                ANALYSIS_SETTINGS,
                "torsion_gamma_ct",
                "Concrete tensile factor gamma_ct",
            ),
        ))

    # Compatibility fallback for an older/custom input payload that exposes only
    # the combined engine blocker.  Unknown ownership is deliberately rendered
    # without a navigation control rather than guessing a correction location.
    explicit_material_diagnostics = bool(
        assignment_errors
        or inp.get("material_definition_errors")
        or inp.get("torsion_gamma_ct_error")
    )
    if inp.get("material_error") and not explicit_material_diagnostics:
        issues.append(InputIssue(
            "material-unmapped",
            _resolved(
                inp["material_error"],
                fallback=_MATERIAL_FALLBACK,
                context="unmapped material input issue",
            ),
            None,
        ))

    return tuple(issues)


__all__ = [
    "ANALYSIS_SETTINGS",
    "INPUT_STAGES",
    "LOADS",
    "MATERIAL_FAMILIES",
    "MATERIAL_PARAMETERS",
    "PROJECT",
    "PROJECT_REPORT",
    "SECTION",
    "CaseLocation",
    "InputIssue",
    "InputTarget",
    "case_issues",
    "heightened_issues",
    "resolve_case_location",
    "section_issues",
]
