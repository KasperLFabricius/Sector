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
    "workspace",
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
    action: str


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
    _destination("project", "Project", "Project", "input-stage"),
)


WORKSPACES: Final[tuple[ManualDestination, ...]] = (
    _destination(
        "report-workspace", "Report", "Report workspace", "workspace"
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
        "Open the Inputs stage named in the warning, correct the identified value "
        "or assignment, then press Calculate.",
    ),
    WarningReference(
        "method-applicability",
        "A selected coefficient or method reports an applicability warning.",
        "The selected option has conditions that Sector cannot infer from the "
        "section geometry or action row.",
        "Open Inputs > Analysis settings, confirm the stated project condition "
        "and selected design basis, then calculate again.",
    ),
    WarningReference(
        "geometry-invalid",
        "The section is rejected or no result is produced.",
        "The outer ring, a void, bar, tendon, or material assignment is malformed.",
        "Correct the highlighted geometry under Inputs > Section or the cited "
        "assignment under Inputs > Material parameters, then press Calculate.",
    ),
    WarningReference(
        "loads-invalid",
        "An action row is rejected or its requested result is not produced.",
        "A required action value is missing or invalid, or a row name is empty or "
        "duplicates another row in the same table.",
        "Open Inputs > Loads, correct the named row, value or duplicate name, then "
        "press Calculate.",
    ),
    WarningReference(
        "crack-not-requested",
        "No crack width is calculated for an Elastic row.",
        "Calculate crack width is off for that named row.",
        "Open Inputs > Loads and enable Calculate crack width on that Elastic row "
        "only when crack-width output is required.",
    ),
    WarningReference(
        "crack-criterion-missing",
        "Crack width is calculated but acceptance is not assessed.",
        "The matching long-term or short-term permitted width in Analysis "
        "settings is 0 mm.",
        "Open Inputs > Analysis settings. Enter a positive value for that duration "
        "to compare, or retain 0 mm to state the width without comparison.",
    ),
    WarningReference(
        "results-stale",
        "Analysis results are marked stale after an input edit.",
        "A calculation input changed after the last calculation.",
        "Press Calculate after the final input edit, then return to the named "
        "Analysis view and verify that the stale marker has cleared.",
    ),
    WarningReference(
        "report-stale",
        "A report cannot be downloaded because its input or metadata changed.",
        "The retained PDF no longer matches the current calculation inputs or "
        "Report metadata.",
        "If calculation inputs changed, finish the Inputs edit and press Calculate. "
        "If only metadata changed, keep the current results. Then open Report and "
        "select Generate report before downloading.",
    ),
    WarningReference(
        "results-review",
        "Results Overview shows one or more governing results requiring review.",
        "At least one requested calculation failed, is invalid, is not assessed, "
        "or retains a calculation warning.",
        "Open Analysis > Results Overview, follow the row's View entry to the named "
        "detail view, and read its criterion and warning before changing the cited "
        "Inputs stage. The overview is not a global compliance verdict.",
    ),
    WarningReference(
        "calculation-warning",
        "A requested result is unavailable, outside the selected method bounds, "
        "or requires review.",
        "A required action, geometry component, reinforcement item, convergence "
        "state, or method-domain condition is missing or invalid.",
        "Open the named Analysis detail view, read the exact warning and correct "
        "the cited Inputs stage where appropriate. Retain NOT ASSESSED or INVALID "
        "when the implemented method is outside scope.",
    ),
    WarningReference(
        "confirmation-required",
        "Sector asks for confirmation before clearing section point tables.",
        "The action replaces authored geometry and reinforcement rows.",
        "Return to Inputs > Section. Cancel to retain the rows, or confirm only "
        "after saving any project state that must remain recoverable.",
    ),
    WarningReference(
        "project-file",
        "A project file is rejected during loading.",
        "The selected file is malformed, is not a Sector project, or contains "
        "unsupported project data.",
        "Return to Inputs > Project and select a valid project file for the current "
        "application, or recreate the inputs manually.",
    ),
    WarningReference(
        "report-generation",
        "PDF or HTML manual/report generation is unavailable.",
        "Required retained results or a publication dependency failed closed.",
        "Read the displayed reason. Press Calculate only when stale or missing "
        "results are cited; otherwise correct the named Report input or publication "
        "dependency and retry.",
    ),
)


WORKFLOWS: Final[tuple[Workflow, ...]] = (
    Workflow(
        "section-creation", "Create a section", "A valid concrete section with reinforcement",
        "section", "Member geometry and coordinate convention", "Section preview is valid",
        "geometry-invalid",
        "Open Inputs > Section. Enter or generate the concrete outline and voids, "
        "add reinforcement geometry, confirm the preview, then press Calculate.",
    ),
    Workflow(
        "materials-reinforcement", "Define materials and reinforcement",
        "Assigned concrete, mild-steel and prestress laws", "material-parameters",
        "Material grades and reinforcement layout", "Every used material ID resolves",
        "geometry-invalid",
        "Open Inputs > Material parameters and define the required material laws. "
        "Use Inputs > Section to assign each reinforcement material ID, then press "
        "Calculate.",
    ),
    Workflow(
        "action-tables", "Enter actions", "Named Plastic, Elastic and fatigue actions",
        "loads", "Design action sets", "Rows are valid and uniquely named",
        "loads-invalid",
        "Open Inputs > Loads. Enter the uniquely named Plastic/capacity, Elastic "
        "and grouped-fatigue rows required for the task, then press Calculate.",
    ),
    Workflow(
        "elastic-crack", "Calculate elastic response and crack width",
        "Retained stresses, cracking state and optional crack width", "elastic-results",
        "Valid section, materials and Elastic row", "Calculated or bounded not-assessed state",
        "crack-criterion-missing",
        "Select Elastic and the crack-width method and limits under Inputs > "
        "Analysis settings. Define the Elastic row under Inputs > Loads, enable "
        "Calculate crack width when required, press Calculate, then open Analysis > "
        "Elastic Results.",
    ),
    Workflow(
        "plastic-capacity", "Calculate plastic capacity",
        "Capacity envelope, utilisation and selected critical state", "plastic-results",
        "Valid section, materials and Plastic row", "Calculated capacity result",
        "results-stale",
        "Select Plastic under Inputs > Analysis settings. Define the Plastic/capacity "
        "row under Inputs > Loads, press Calculate, then open Analysis > Plastic "
        "Results or Analysis > N-M Interaction.",
    ),
    Workflow(
        "fatigue", "Calculate grouped fatigue", "Spectrum and governing element results",
        "fatigue-results", "Valid fatigue spectra and material details",
        "Calculated or bounded not-assessed state", "results-stale",
        "Enable Fatigue under Inputs > Analysis settings. Define fatigue details "
        "under Inputs > Material parameters, assign them under Inputs > Section, "
        "enter grouped spectra under Inputs > Loads, press Calculate, then open "
        "Analysis > Fatigue Results.",
    ),
    Workflow(
        "detailing", "Review detailing", "Minimum reinforcement, links and spacing results",
        "detailing", "Calculated relevant action rows", "Each requested check has a bounded status",
        "results-stale",
        "Enable each required detailing check under Inputs > Analysis settings, "
        "complete its dependent link or member inputs, press Calculate, then open "
        "Analysis > Detailing.",
    ),
    Workflow(
        "review-results", "Review results", "A complete requested-calculation register",
        "results-overview", "Current calculation results", "Warnings and governing rows are visible",
        "results-review",
        "Press Calculate after the final input edit, then open Analysis > Results "
        "Overview. Follow each governing row's View entry to its named detail view "
        "and review every warning or not-assessed state.",
    ),
    Workflow(
        "save-load", "Save or load a project", "A reproducible current project",
        "project", "Current inputs or a supported project file",
        "Loaded inputs require a fresh calculation", "project-file",
        "Open Inputs > Project. Download the project to save the current inputs, or "
        "select a project file to load it. After loading, review the restored inputs "
        "and press Calculate before using results.",
    ),
    Workflow(
        "report-profile", "Choose a report profile", "Brief, Standard or Audit publication",
        "report-workspace", "Current inputs and project metadata",
        "Profile changes presentation depth only", "report-generation",
        "With current results, open Report, enter the project metadata, choose Brief, "
        "Standard or Audit, then generate and download the PDF.",
    ),
)


ALL_DESTINATIONS: Final[tuple[ManualDestination, ...]] = (
    *READING_PATHS,
    *INPUT_STAGES,
    *WORKSPACES,
    *RESULT_VIEWS,
    *METHODS,
)

DESTINATIONS: Final = MappingProxyType(
    {destination.key: destination for destination in ALL_DESTINATIONS}
)
_HEADING_ANCHORS: Final = MappingProxyType({
    (
        destination.heading,
        2 if destination.kind in {"result-view", "workspace"} else 1,
    ):
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
    "WORKSPACES",
    "ManualDestination",
    "WarningReference",
    "Workflow",
    "destination",
    "heading_anchor",
    "warning_reference",
]
