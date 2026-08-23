"""Typed UI destinations for engine-owned input validation messages.

The calculation and project boundaries intentionally continue to return plain
strings.  This module is the narrow application-boundary adapter that gives
those strings a safe Streamlit destination without making the numerical engine
depend on UI state or labels.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.manual_information_architecture import INPUT_STAGES as REGISTERED_STAGES

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
    message: str
    target: InputTarget | None = None


def _issue(code: str, message: object, target: InputTarget | None) -> InputIssue:
    return InputIssue(code=code, message=str(message).strip(), target=target)


def _case_target(message: str) -> InputTarget:
    if message.startswith("Plastic") or "Plastic case" in message:
        return InputTarget(
            LOADS,
            "plastic_cases_editor",
            "Plastic and capacity cases",
        )
    if message.startswith("Elastic") or "Elastic case" in message:
        return InputTarget(
            LOADS,
            "elastic_cases_editor",
            "Elastic cases",
        )
    return InputTarget(LOADS, widget_label="Plastic and Elastic case tables")


def case_issues(errors: Iterable[object]) -> tuple[InputIssue, ...]:
    """Adapt existing load-case validator strings without changing them."""

    return tuple(
        _issue(f"case-{index}", message, _case_target(str(message).strip()))
        for index, message in enumerate(errors, start=1)
        if str(message).strip()
    )


_HEIGHTENED_TARGETS = (
    (
        "Heightened crack control requires Elastic analysis",
        InputTarget(
            ANALYSIS_SETTINGS,
            "mode",
            "Analysis mode",
        ),
    ),
    (
        "Heightened crack control is available only with",
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_code",
            "Crack-width design basis",
        ),
    ),
    (
        "Heightened crack control requires at least one crack-enabled",
        InputTarget(
            LOADS,
            "elastic_cases_editor",
            "Elastic cases",
        ),
    ),
    (
        "Select one crack-enabled Elastic case",
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_heightened_reference_case",
            "Reference crack-enabled Elastic case",
        ),
    ),
    (
        "Heightened crack control must be explicitly",
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_heightened_on",
            "Optional DK NA heightened crack control",
        ),
    ),
    (
        "Heightened reinforcement surface",
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_heightened_reinforcement_surface",
            "Reinforcement surface",
        ),
    ),
    (
        "Effective tensile strength",
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_heightened_effective_tensile_strength_mpa",
            "Effective tensile strength",
        ),
    ),
    (
        "Heightened permitted crack width",
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_heightened_permitted_crack_width_mm",
            "Heightened permitted crack width",
        ),
    ),
    (
        "Fine-system effective tension area",
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_heightened_fine_effective_tension_area_mm2",
            "Fine-system effective tension area",
        ),
    ),
    (
        "Coarse-system effective tension area",
        InputTarget(
            ANALYSIS_SETTINGS,
            "sls_heightened_coarse_effective_tension_area_mm2",
            "Coarse-system effective tension area",
        ),
    ),
)


def heightened_issues(errors: Iterable[object]) -> tuple[InputIssue, ...]:
    """Adapt heightened-check strings, falling back without fake navigation."""

    issues = []
    for index, message in enumerate(errors, start=1):
        text = str(message).strip()
        if not text:
            continue
        target = next(
            (
                candidate
                for prefix, candidate in _HEIGHTENED_TARGETS
                if text.startswith(prefix)
            ),
            None,
        )
        issues.append(_issue(f"heightened-{index}", text, target))
    return tuple(issues)


def _material_definition_target(message: str) -> InputTarget | None:
    material_id = message.split(":", 1)[0].strip().upper()
    if re.fullmatch(r"M[1-9][0-9]*", material_id):
        family = "Mild steel"
    elif re.fullmatch(r"P[1-9][0-9]*", material_id):
        family = "Prestressing steel"
    else:
        return None
    return InputTarget(
        MATERIAL_PARAMETERS,
        widget_label=f"Material {material_id}",
        material_family=family,
        material_id=material_id,
    )


def section_issues(inp: Mapping) -> tuple[InputIssue, ...]:
    """Return section/material blockers already diagnosed by input assembly."""

    issues: list[InputIssue] = []
    geometry_error = inp.get("geometry_error")
    if geometry_error:
        geometry_text = str(geometry_error)
        geometry_is_hole = any(
            token in geometry_text.lower() for token in ("hole", "void")
        )
        issues.append(
            _issue(
                "section-geometry",
                geometry_text,
                InputTarget(
                    SECTION,
                    "ed_hole" if geometry_is_hole else "ed_corners",
                    "Void geometry" if geometry_is_hole else "Section outline",
                ),
            )
        )
    elif inp.get("section") is None:
        issues.append(
            _issue(
                "section-missing",
                "Define a section outline with at least three points",
                InputTarget(SECTION, "ed_corners", "Section outline"),
            )
        )

    if inp.get("void_error"):
        issues.append(
            _issue(
                "section-void",
                inp["void_error"],
                InputTarget(SECTION, "ed_hole", "Void geometry"),
            )
        )
    if inp.get("steel_error"):
        text = str(inp["steel_error"])
        lower = text.lower()
        mentions_bars = "bar" in lower
        mentions_tendons = "tendon" in lower
        widget_key = (
            "ed_bars"
            if mentions_bars and not mentions_tendons
            else "ed_tendons"
            if mentions_tendons and not mentions_bars
            else None
        )
        issues.append(
            _issue(
                "section-reinforcement",
                text,
                InputTarget(SECTION, widget_key, "Reinforcement geometry"),
            )
        )

    assignment_errors = tuple(inp.get("material_assignment_errors") or ())
    for index, message in enumerate(assignment_errors, start=1):
        text = str(message)
        if text.startswith("Bar material"):
            target = InputTarget(SECTION, "ed_bars", "Bar material assignment")
        elif text.startswith("Tendon material"):
            target = InputTarget(
                SECTION,
                "ed_tendons",
                "Tendon material assignment",
            )
        elif text.startswith("Member-check material"):
            target = InputTarget(
                ANALYSIS_SETTINGS,
                "capacity_steel_material_id",
                "Member-check material",
            )
        else:
            target = None
        issues.append(_issue(f"material-assignment-{index}", text, target))

    for index, message in enumerate(
        tuple(inp.get("material_definition_errors") or ()), start=1
    ):
        text = str(message)
        issues.append(
            _issue(
                f"material-definition-{index}",
                f"Invalid material definition: {text}",
                _material_definition_target(text),
            )
        )

    if inp.get("torsion_gamma_ct_error"):
        issues.append(
            _issue(
                "torsion-gamma-ct",
                inp["torsion_gamma_ct_error"],
                InputTarget(
                    ANALYSIS_SETTINGS,
                    "torsion_gamma_ct",
                    "Concrete tensile factor gamma_ct",
                ),
            )
        )

    # Compatibility fallback for an older/custom input payload that exposes only
    # the combined engine blocker.  Unknown ownership is deliberately rendered
    # without a navigation control rather than guessing a correction location.
    explicit_material_diagnostics = bool(
        assignment_errors
        or inp.get("material_definition_errors")
        or inp.get("torsion_gamma_ct_error")
    )
    if inp.get("material_error") and not explicit_material_diagnostics:
        issues.append(_issue("material-unmapped", inp["material_error"], None))

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
