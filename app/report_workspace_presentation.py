"""Read-only report coverage, bounded profile presets and guarded PDF preview."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass

from app import report_profiles


@dataclass(frozen=True, slots=True)
class PresentationPreset:
    """A presentation-depth preference, containing no engineering or identity data."""

    profile: str

    def __post_init__(self) -> None:
        if type(self.profile) is not str:
            raise TypeError("preset profile must be an exact profile label")
        report_profiles.resolve_profile(self.profile)


def read_preset(value: Mapping) -> PresentationPreset:
    """Reject extra fields rather than silently copy identity or action data."""
    if not isinstance(value, Mapping) or set(value) != {"profile"}:
        raise ValueError("a presentation preset contains only its profile")
    return PresentationPreset(value["profile"])


def preset_changes(current: str, preset: PresentationPreset) -> tuple[dict, ...]:
    """Show all proposed changes before the UI can apply a preference."""
    current = report_profiles.resolve_profile(current).key
    if not isinstance(preset, PresentationPreset):
        raise TypeError("preset must be a PresentationPreset")
    if current == preset.profile:
        return ()
    return ({"Setting": "Report profile", "Current": current,
             "Proposed": preset.profile},)


def profile_outline(profile: str) -> tuple[dict[str, str], ...]:
    """Describe depth using the unchanged report policy, without filtering content."""
    policy = report_profiles.resolve_profile(profile)
    inputs = {
        "effective": "All inputs applicable to each reported result",
        "used": "All used inputs",
        "canonical": "All calculation inputs",
    }[policy.input_scope]
    results = {
        "governing-only": "Governing results and requested-check outcomes",
        "complete": "Full result tables and requested-check outcomes",
    }[policy.non_governing_scope]
    equations = {
        "interpretive": "Equations needed to interpret the results",
        "used": "Used equations and criteria",
        "used-and-theory": "Used equations, criteria and method theory",
    }[policy.equation_scope]
    substitutions = {
        "none": "Available in Audit",
        "governing": "Governing substitutions",
        "every-retained": "All retained substitutions and calculation sequences",
    }[policy.substitution_scope]
    return tuple({"Content": label, "Coverage": coverage} for label, coverage in (
        ("Project and section", "Document identity and section description"),
        ("Results", results),
        ("Inputs", inputs),
        ("Figures", "All applicable figures"),
        ("Methods", equations),
        ("Substitutions", substitutions),
        ("Assessment", "Applicable statuses, warnings, sources and limitations"),
        ("QA appendix", "Included" if policy.include_qa_appendix else "Available in Audit"),
    ))


def declared_case_rows(assignments) -> tuple[dict[str, str], ...]:
    """Describe declared names without selecting, excluding or calculating cases."""
    return tuple(
        {"Family": family, "Case or spectrum": name}
        for family, name in assignments
        if family in {"Plastic", "Elastic", "Fatigue"}
        and type(name) is str and name.strip()
    )


def pdf_preview_url(
    pdf: object, *, artifact_signature: object, current_signature: object,
    requested_signature: object, pending_inputs: bool,
) -> str | None:
    """Expose only explicitly requested bytes bound to a complete current state.

    The UI must compute current_signature with its original report signature
    function. This helper never generates a document or calculates results.
    """
    if (
        pending_inputs is not False
        or current_signature is None
        or artifact_signature is None
        or requested_signature is None
        or artifact_signature != current_signature
        or requested_signature != current_signature
        or type(pdf) is not bytes
        or not pdf.startswith(b"%PDF-")
    ):
        return None
    return "data:application/pdf;base64," + base64.b64encode(pdf).decode("ascii")
