"""Typed UI destinations for authored input-validation messages."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app import engineer_messages
from app.manual_information_architecture import INPUT_STAGES as REGISTERED_STAGES
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
    {"Concrete", "Mild steel", "Prestressing steel", "Fatigue details"}
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
class InputTarget:
    """One bounded correction destination in the Inputs workspace."""

    stage: str
    widget_key: str | None = None
    widget_label: str | None = None
    material_family: str | None = None
    material_id: str | None = None

    def __post_init__(self) -> None:
        if self.stage not in INPUT_STAGES:
            raise ValueError(f"unknown input stage: {self.stage!r}")
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
                "Mild steel": "M",
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


def _case_target(message: EngineerMessage) -> InputTarget:
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
    if message.code.startswith("PLASTIC-"):
        return InputTarget(
            LOADS,
            "plastic_cases_editor",
            "Plastic and capacity cases",
        )
    if message.code.startswith("ELASTIC-"):
        return InputTarget(
            LOADS,
            "elastic_cases_editor",
            "Elastic cases",
        )
    return InputTarget(LOADS, widget_label="Plastic and Elastic case tables")


def case_issues(errors: Iterable[object]) -> tuple[InputIssue, ...]:
    """Adapt load-case diagnostics without granting provenance to raw values."""

    issues = []
    for index, value in enumerate(errors, start=1):
        message = _resolved(
            value,
            fallback=_CASE_FALLBACK,
            context="load-case input issue",
        )
        issues.append(InputIssue(
            code=f"case-{index}",
            message=message,
            target=_case_target(message),
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
        family = "Mild steel"
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
    "InputIssue",
    "InputTarget",
    "case_issues",
    "heightened_issues",
    "section_issues",
]
