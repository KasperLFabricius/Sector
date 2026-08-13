"""Stable information architecture shared by Sector manual publications.

The registry contains navigation and help identities only.  It deliberately has
no Streamlit, PDF, solver, result, persistence, or project-schema dependency, so
the eager application shell can use the exact same labels and destinations as
the downloadable PDF and accessible HTML manual.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, TypeAlias


DestinationKind: TypeAlias = Literal[
    "reading-path",
    "input-stage",
    "result-view",
    "method",
    "troubleshooting",
]


@dataclass(frozen=True, slots=True)
class ManualDestination:
    key: str
    label: str
    anchor: str
    heading: str
    kind: DestinationKind


@dataclass(frozen=True, slots=True)
class Workflow:
    key: str
    label: str
    outcome: str
    destination_key: str
    prerequisite: str
    expected_state: str
    warning_key: str
    action: str | None = None


@dataclass(frozen=True, slots=True)
class WarningReference:
    key: str
    symptom: str
    cause: str
    correction: str


def _destination(
    key: str,
    label: str,
    heading: str,
    kind: DestinationKind,
) -> ManualDestination:
    return ManualDestination(
        key=key,
        label=label,
        anchor="manual-" + key,
        heading=heading,
        kind=kind,
    )


READING_PATHS: Final[tuple[ManualDestination, ...]] = (
    _destination(
        "start-here", "Start here", "Start here", "reading-path"
    ),
    _destination(
        "quick-calculation", "Quick calculation", "Quick start", "reading-path"
    ),
    _destination(
        "input-reference", "Input reference", "Input reference", "reading-path"
    ),
    _destination(
        "method-reference", "Method reference", "Method reference", "reading-path"
    ),
    _destination(
        "limitations-troubleshooting",
        "Limitations and troubleshooting",
        "Limitations & troubleshooting",
        "troubleshooting",
    ),
)


INPUT_STAGES: Final[tuple[ManualDestination, ...]] = (
    _destination(
        "analysis-settings", "Analysis settings", "Analysis & result settings",
        "input-stage",
    ),
    _destination("section", "Section", "Defining the section", "input-stage"),
    _destination(
        "material-parameters", "Material parameters", "Materials", "input-stage"
    ),
    _destination("loads", "Loads", "Loads", "input-stage"),
    _destination(
        "project-report", "Project & report", "Project & report", "input-stage"
    ),
)


RESULT_VIEWS: Final[tuple[ManualDestination, ...]] = (
    _destination(
        "results-overview", "Results Overview", "Results overview", "result-view"
    ),
    _destination(
        "plastic-results", "Plastic Results", "Plastic results", "result-view"
    ),
    _destination(
        "n-m-interaction", "N-M Interaction", "N-M Interaction results",
        "result-view",
    ),
    _destination(
        "elastic-results", "Elastic Results", "Elastic results", "result-view"
    ),
    _destination(
        "fatigue-results", "Fatigue Results", "Fatigue results", "result-view"
    ),
    _destination("detailing", "Detailing", "Detailing results", "result-view"),
    _destination("shear", "Shear", "Shear results", "result-view"),
    _destination("torsion", "Torsion", "Torsion results", "result-view"),
    _destination(
        "combined", "M-V-T Combined", "M-V-T Combined results", "result-view"
    ),
)


METHODS: Final[tuple[ManualDestination, ...]] = (
    _destination("method-materials", "Material laws", "Material laws", "method"),
    _destination(
        "method-plastic", "Plastic capacity", "Plastic capacity analysis", "method"
    ),
    _destination(
        "method-detailing", "Reinforcement detailing", "Reinforcement detailing",
        "method",
    ),
    _destination(
        "method-elastic", "Cracked-section elastic", "Cracked-section elastic analysis",
        "method",
    ),
    _destination(
        "method-cracking", "Cracking and crack width",
        "Serviceability: cracking and crack width", "method",
    ),
    _destination("method-fatigue", "Grouped fatigue", "Grouped fatigue", "method"),
    _destination(
        "method-shear", "Shear resistance", "Shear resistance without shear reinforcement",
        "method",
    ),
    _destination("method-torsion", "Torsion", "Torsion (thin-walled tube)", "method"),
    _destination(
        "method-combined", "Combined M-V-T", "Combined M-V-T interaction", "method"
    ),
)


WARNINGS: Final[tuple[WarningReference, ...]] = (
    WarningReference(
        "input-invalid",
        "An entered value is rejected, adjusted, or prevents a requested check.",
        "The value is outside its declared range, conflicts with another input, "
        "or leaves an assignment incomplete.",
        "Correct the identified input and recalculate; do not rely on an adjusted "
        "preview value as issued evidence.",
    ),
    WarningReference(
        "method-applicability",
        "A selected coefficient or method reports an applicability warning.",
        "The selected option has conditions that Sector cannot infer from the "
        "section geometry or action row.",
        "Confirm the stated project condition and selected design basis before "
        "using the result.",
    ),
    WarningReference(
        "geometry-invalid",
        "The section is rejected or no result is produced.",
        "The outer ring, a void, bar, tendon, or material assignment is malformed.",
        "Correct the highlighted Section or Material parameters input before calculating.",
    ),
    WarningReference(
        "crack-not-requested",
        "No crack width is calculated for an Elastic row.",
        "Calculate crack width is off for that named row.",
        "Enable the row option only when crack-width output is required.",
    ),
    WarningReference(
        "crack-criterion-missing",
        "Crack width is calculated but acceptance is not assessed.",
        "The optional permitted crack width in Analysis settings is blank.",
        "Enter one positive shared value to compare, or retain the intentional blank state.",
    ),
    WarningReference(
        "results-stale",
        "Results or the report are marked stale after an edit.",
        "A calculation input or presentation setting changed after the last calculation.",
        "Recalculate, then generate the required report profile again.",
    ),
    WarningReference(
        "calculation-warning",
        "A requested result is unavailable, outside the selected method bounds, "
        "or requires review.",
        "A required action, geometry component, reinforcement item, convergence "
        "state, or method-domain condition is missing or invalid.",
        "Read the exact result warning, correct the cited input where appropriate, "
        "and retain NOT ASSESSED or INVALID when the method is outside scope.",
    ),
    WarningReference(
        "confirmation-required",
        "Sector asks for confirmation before clearing section point tables.",
        "The action replaces authored geometry and reinforcement rows.",
        "Cancel to retain the rows, or confirm only after preserving any project "
        "state that must remain recoverable.",
    ),
    WarningReference(
        "project-version",
        "A project file is rejected during loading.",
        "Its schema or product identity is not the exact supported current format.",
        "Open it in the matching Sector release or recreate it in the current schema.",
    ),
    WarningReference(
        "report-generation",
        "PDF or HTML manual/report generation is unavailable.",
        "Required retained results or a publication dependency failed closed.",
        "Review the displayed reason; recalculate stale results and retry without hiding the error.",
    ),
    WarningReference(
        "portable-prerequisites",
        "The portable Windows build does not produce its verified output, or Windows blocks the unsigned application.",
        "The extracted source is incomplete or unauthenticated, exact 64-bit CPython 3.13.0 is unavailable, the build failed, or local SmartScreen/corporate policy blocks unsigned software.",
        "Use the complete official Sector source ZIP from its trusted release channel, compare its published SHA-256, retain the whole extracted source, install exact 64-bit CPython 3.13.0 when building, and double-click BUILD_SECTOR_PORTABLE.bat. Read the final console message and README-PORTABLE.txt; do not bypass organisational security policy.",
    ),
)


WORKFLOWS: Final[tuple[Workflow, ...]] = (
    Workflow(
        "section-creation", "Create a section", "A valid concrete section with reinforcement",
        "section", "Member geometry and coordinate convention", "Section preview is valid",
        "geometry-invalid",
    ),
    Workflow(
        "materials-reinforcement", "Define materials and reinforcement",
        "Assigned concrete, mild-steel and prestress laws", "material-parameters",
        "Material grades and reinforcement layout", "Every used material ID resolves",
        "geometry-invalid",
    ),
    Workflow(
        "action-tables", "Enter actions", "Named Plastic, Elastic and fatigue actions",
        "loads", "Design action sets", "Rows are valid and uniquely named",
        "geometry-invalid",
    ),
    Workflow(
        "elastic-crack", "Calculate elastic response and crack width",
        "Retained stresses, cracking state and optional crack width", "elastic-results",
        "Valid section, materials and Elastic row", "Calculated or bounded not-assessed state",
        "crack-criterion-missing",
    ),
    Workflow(
        "plastic-capacity", "Calculate plastic capacity",
        "Capacity envelope, utilisation and selected critical state", "plastic-results",
        "Valid section, materials and Plastic row", "Calculated capacity result",
        "results-stale",
    ),
    Workflow(
        "fatigue", "Calculate grouped fatigue", "Spectrum and governing element results",
        "fatigue-results", "Valid fatigue spectra and material details",
        "Calculated or bounded not-assessed state", "results-stale",
    ),
    Workflow(
        "detailing", "Review detailing", "Minimum reinforcement, links and spacing results",
        "detailing", "Calculated relevant action rows", "Each requested check has a bounded status",
        "results-stale",
    ),
    Workflow(
        "review-results", "Review results", "A complete requested-calculation register",
        "results-overview", "Current calculation results", "Warnings and governing rows are visible",
        "results-stale",
    ),
    Workflow(
        "save-load", "Save or load a project", "A current-schema reproducible project",
        "project-report", "Current inputs or a compatible project file",
        "Loaded inputs require a fresh calculation", "project-version",
    ),
    Workflow(
        "report-profile", "Choose a report profile", "Brief, Standard or Audit publication",
        "project-report", "Current results and project metadata",
        "Profile changes presentation depth only", "report-generation",
    ),
    Workflow(
        "portable-build", "Use the portable Windows application",
        "Verified unsigned portable release", "limitations-troubleshooting",
        "Complete extracted official Sector source ZIP and exact 64-bit CPython 3.13.0 for the one-time build",
        "The printed output path contains the complete unsigned portable folder, matching ZIP, SHA-256 sidecar and canonical receipt; running Sector.exe from the complete extracted portable folder reaches the local Sector app",
        "portable-prerequisites",
        "From the extracted source root, double-click BUILD_SECTOR_PORTABLE.bat. No separately entered PowerShell command or administrator elevation is required. Distribute or extract the whole generated portable ZIP, never Sector.exe alone.",
    ),
)


ALL_DESTINATIONS: Final[tuple[ManualDestination, ...]] = (
    *READING_PATHS,
    *INPUT_STAGES,
    *RESULT_VIEWS,
    *METHODS,
)

DESTINATIONS: Final = MappingProxyType(
    {destination.key: destination for destination in ALL_DESTINATIONS}
)
_HEADING_ANCHORS: Final = MappingProxyType({
    (destination.heading, 2 if destination.kind == "result-view" else 1):
        destination.anchor
    for destination in ALL_DESTINATIONS
})
WARNING_REFERENCES: Final = MappingProxyType(
    {warning.key: warning for warning in WARNINGS}
)


def destination(key: str) -> ManualDestination:
    """Return one exact destination or fail closed."""

    try:
        return DESTINATIONS[key]
    except KeyError as error:
        raise ValueError(f"unknown manual destination: {key!r}") from error


def heading_anchor(heading: str, level: int) -> str | None:
    """Return the stable shared anchor for a registered authored heading."""

    return _HEADING_ANCHORS.get((heading, level))


def warning_reference(key: str) -> WarningReference:
    """Return one exact troubleshooting entry or fail closed."""

    try:
        return WARNING_REFERENCES[key]
    except KeyError as error:
        raise ValueError(f"unknown manual warning reference: {key!r}") from error


__all__ = [
    "ALL_DESTINATIONS",
    "DESTINATIONS",
    "INPUT_STAGES",
    "METHODS",
    "READING_PATHS",
    "RESULT_VIEWS",
    "WARNING_REFERENCES",
    "WARNINGS",
    "WORKFLOWS",
    "ManualDestination",
    "WarningReference",
    "Workflow",
    "destination",
    "heading_anchor",
    "warning_reference",
]
