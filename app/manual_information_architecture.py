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
        "numerical-procedures", "Numerical procedures", "Calculation conventions", "reading-path"
    ),
    _destination(
        "portable-startup", "Portable startup", "Start the portable application", "reading-path"
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

# Public navigation labels are separate from the retained stage and anchor
# identities used by saved UI state and existing manual links.
PUBLIC_PAGE_LABELS: Final = MappingProxyType({
    "section": "Section",
    "material-parameters": "Materials",
    "loads": "Actions",
    "analysis-settings": "Analysis settings",
    "results-overview": "Results",
    "report-workspace": "Report",
    "project": "Project and recovery",
    "start-here": "Help and manual",
})


PUBLICATION_REFERENCES: Final[tuple[ManualDestination, ...]] = (
    _destination("status-reference", "Result statuses", "Result status reference", "result-view"),
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
        "method-shear", "Shear resistance", "Shear resistance",
        "method",
    ),
    _destination("method-torsion", "Torsion", "Torsion (thin-walled tube)", "method"),
    _destination(
        "method-combined", "Combined M-V-T", "Combined M-V-T interaction", "method"
    ),
)


WARNINGS: Final[tuple[WarningReference, ...]] = (
    WarningReference(
        "autosave-recovery",
        "Autosave is paused, or it cannot write the recovery file.",
        "Another Sector session changed the recovery file, the file cannot be read, "
        "or the recovery file cannot be written.",
        "Select Download project to keep the current inputs. Read the warning. "
        "For a session conflict, close other sessions and restart Sector. "
        "For a write failure, check folder access. "
        "Keep an unreadable recovery file until you have an intact saved project.",
    ),
    WarningReference(
        "startup-incomplete",
        "Sector.exe stops before the browser opens.",
        "The extracted package is incomplete, a dependency is blocked, or the console reports a startup error.",
        'Read the console message. Extract the full ZIP into a new local folder. Keep _internal beside Sector.exe. If company policy blocks execution, use the approved software process.',
    ),
    WarningReference(
        "elastic-equilibrium",
        "An elastic state has a convergence warning or unavailable neutral axis.",
        "The equilibrium matrix is singular, the iteration limit is reached, or the accepted plane has no finite axis intercept.",
        'Read the convergence status and residuals. Examine geometry, material assignments, moduli and actions. A missing axis intercept can occur with uniform strain or an axis parallel to a coordinate direction. Use the plane coefficients and concrete stress to distinguish these cases.',
    ),
    WarningReference(
        "plastic-equilibrium",
        "A capacity point has an unreachable axial target or a convergence warning.",
        "The entered axial force exceeds the range available at that orientation, or equilibrium fails its acceptance checks.",
        'Examine the axial-force sign, units, reinforcement areas and assigned material limits. Read the residual and reachability status. Keep an unresolved point as diagnostic output. Use accepted points for resistance assessment.',
    ),
    WarningReference(
        "input-invalid",
        'Sector rejects or adjusts an entered value, or that value prevents a requested check.',
        'The value is outside its declared range, conflicts with a different input, or leaves an assignment incomplete.',
        'Open the input page named in the warning. Correct the identified value or assignment. Open Results. Select Calculate.',
    ),
    WarningReference(
        "method-applicability",
        "A selected coefficient or method reports an applicability warning.",
        "The selected option has conditions that Sector cannot infer from the "
        "section geometry or action row.",
        'Open Analysis settings. Make sure that the stated project condition is satisfied. Make sure that the selected design basis is correct. Open Results. Select Calculate.',
    ),
    WarningReference(
        "geometry-invalid",
        'Sector rejects the section or gives no result.',
        "The outer ring, a void, bar, tendon, or material assignment is malformed.",
        'Open Section. Correct the identified geometry. For an assignment error, open Materials. Correct the assignment. Open Results. Select Calculate.',
    ),
    WarningReference(
        "loads-invalid",
        'Sector rejects an action row or gives no requested result for it.',
        'A required action value is missing or invalid, or a row name is empty or duplicates a different action name across the action tables.',
        'Open Actions. Find the row named in the warning. Correct the identified value or name. Use unique action and bin names across all action tables.\n\nOpen Results. Select Calculate. Examine the requested result in Results Overview.',
    ),
    WarningReference(
        "crack-not-requested",
        'Sector calculates no crack width for an Elastic row.',
        "Calculate crack width is off for that named row.",
        'Open Actions. If crack-width output is required, enable Calculate crack width on the named Elastic row.',
    ),
    WarningReference(
        "crack-criterion-missing",
        'Sector calculates crack width without a limit comparison.',
        "The matching long-term or short-term permitted width in Analysis "
        "settings is 0 mm.",
        'Open Analysis settings. For a limit comparison, enter a positive permitted width for the required duration. To calculate the width without comparison, keep 0 mm.',
    ),
    WarningReference(
        "results-stale",
        "Analysis results are marked stale after an input edit.",
        "A calculation input changed after the last calculation.",
        'After the last input edit, open Results. Select Calculate. Open the named result view. Make sure that you cannot see the stale marker.',
    ),
    WarningReference(
        "report-stale",
        "A report cannot be downloaded because its inputs or project details changed.",
        'The existing PDF has different calculation inputs or Report details from the current project.',
        'If calculation inputs changed, complete the input edit. Open Results. Select Calculate. If only report details changed, keep the current results.\n\nOpen Report. Select Generate report. Download the new PDF.',
    ),
    WarningReference(
        "results-review",
        "Results Overview shows one or more governing results requiring review.",
        'One requested calculation failed, is invalid, is not assessed, or has a calculation warning.',
        'Open Results > Results Overview. Select the check row in an Overview table. Select Open selected result. Read its criterion and warning. Correct the identified input page where applicable. Examine the full requested-check register before you accept the calculation.',
    ),
    WarningReference(
        "calculation-warning",
        "A requested result is unavailable, outside the selected method bounds, "
        "or requires review.",
        "A required action, geometry component, reinforcement item, convergence "
        "state, or method-domain condition is missing or invalid.",
        'Open Results and select the named result view. Read the warning. Correct the identified input page where applicable. Keep NOT ASSESSED or INVALID when the method is outside its scope.',
    ),
    WarningReference(
        "confirmation-required",
        "Sector asks for confirmation before clearing section point tables.",
        "The action replaces authored geometry and reinforcement rows.",
        'Return to Section. To keep the rows, select Cancel. Before confirmation, save the project state that you must keep for recovery.',
    ),
    WarningReference(
        "project-file",
        'Sector rejects a project file when you load it.',
        "The selected file is malformed, is not a Sector project, or contains "
        "unsupported project data.",
        'Open Project and recovery. Expand Save / Load. Under Load project, select a project file with no damage that the current version supports. If no applicable file is available, enter the inputs manually.',
    ),
    WarningReference(
        "report-generation",
        "PDF or HTML manual/report generation is unavailable.",
        "Required calculation results or a report component are unavailable.",
        'Read the displayed message. If results are stale or missing, open Results. Select Calculate. If the results are current, correct the identified Report input or missing report component. Try generation again.',
    ),
    WarningReference(
        "report-source-unmatched",
        "A report reference has no matching current case or spectrum.",
        "The reference's exact action name was renamed or removed.",
        'Open Report > Project and action references. Select the unmatched entry. Keep it if the historical context is required. To remove it, clear the two fields. Enter the reference for the current action in its own entry.',
    ),
)


WORKFLOWS: Final[tuple[Workflow, ...]] = (
    Workflow(
        "section-creation", "Create a section", "A valid concrete section with reinforcement",
        "section", "Member geometry and coordinate convention", "Section preview is valid",
        "geometry-invalid",
        'Open Section. Enter or generate the concrete outline. If the section has voids, enter them. Add the reinforcement geometry. Examine the section preview.',
    ),
    Workflow(
        "materials-reinforcement", "Define materials and reinforcement",
        "Assigned concrete, mild-steel and prestress laws", "material-parameters",
        "Material grades and reinforcement layout", 'Each used material ID resolves',
        "geometry-invalid",
        'Open Materials. Define the required material laws. Open Section. Assign each reinforcement material ID. Make sure that each assigned ID identifies a defined material.',
    ),
    Workflow(
        "action-tables", "Enter actions", "Named Plastic, Elastic and fatigue actions",
        "loads", "Design action sets", "Rows are valid and uniquely named",
        "loads-invalid",
        'Open Actions. Enter the required Plastic/capacity, Elastic and grouped-fatigue rows. Give each action row a unique name. Correct each displayed row error.',
    ),
    Workflow(
        "elastic-crack", "Calculate elastic response and crack width",
        "Calculated stresses, cracking state and optional crack width", "elastic-results",
        "Valid section, materials and Elastic row", 'Calculated results or an assessment-status message',
        "crack-not-requested",
        'Under Analysis settings > General, select Elastic. Open Crack width. Select the crack-width method and enter the required limits. Under Actions, define the Elastic row. Select Calculate crack width when required. Open Results. Select Calculate. Open Elastic Results. Examine the named case.',
    ),
    Workflow(
        "plastic-capacity", "Calculate plastic capacity",
        'Capacity envelope, utilization and selected critical state', "plastic-results",
        "Valid section, materials and Plastic row", "Calculated capacity result",
        "results-stale",
        'Under Analysis settings > General, select Plastic. Enable N-M interaction diagrams when those additional curves are necessary. Under Actions, define the Plastic/capacity row. Open Results. Select Calculate. Open Plastic Results. Examine the named case.',
    ),
    Workflow(
        "fatigue", "Calculate grouped fatigue", "Spectrum and governing element results",
        "fatigue-results", "Valid fatigue spectra and material details",
        'Calculated results or an assessment-status message', "results-stale",
        'Under Analysis settings > Fatigue, enable Fatigue. Select the fatigue edition. Select Reinforcement, Concrete or the two options. Under Materials, define the fatigue details. Under Section, assign each required detail ID. Under Actions, enter the grouped spectra. Open Results. Select Calculate. Open Fatigue Results. Select the spectrum. Examine each status and warning.',
    ),
    Workflow(
        "detailing", 'Examine detailing', "Minimum reinforcement, links and spacing results",
        "detailing", 'Calculated applicable action rows', 'Each requested check has a status and related assessment message',
        "results-stale",
        'Under Analysis settings > Detailing, enable each required detailing check. Complete its link and member inputs. Under Actions, select Check minimum reinforcement on each required Plastic/capacity row. Open Results. Select Calculate. Open Detailing. Examine each requested status.',
    ),
    Workflow(
        "shear-check", "Calculate shear resistance", "Directional shear resistance and governing face",
        "shear", "Valid capacity row and directional shear geometry", 'Each active direction has a result or a message that identifies the assessment condition',
        "calculation-warning",
        'Open Analysis settings > Shear / torsion / M-V-T > Checks and methods. Enable Check shear capacity and select the method. In Shear, select the section form and complete the web and duct inputs. In Shared reinforcement, complete the link inputs. Under Actions, enter the signed shear components. Open Results. Select Calculate. Open Shear. Examine each active direction.',
    ),
    Workflow(
        "torsion-check", "Calculate torsion resistance", "Tube geometry, transverse resistance and longitudinal requirement",
        "torsion", "Applicable member scope, closed links and nonzero torsion action", 'An assessment for transverse reinforcement and an assessment for longitudinal reinforcement',
        "method-applicability",
        'Open Analysis settings > Shear / torsion / M-V-T > Checks and methods. Enable Check torsion capacity and select the design basis. Open Torsion. Select the applicable member scope for each case and complete the tube inputs. In Shared reinforcement, complete the closed-stirrup inputs. Under Actions, enter torsion. Open Results. Select Calculate. Open Torsion. Examine the tube and the two reinforcement assessments.',
    ),
    Workflow(
        "combined-check", "Calculate combined resistance", "Concurrent bending, shear and torsion assessments",
        "combined", 'Valid capacity row, enabled component checks and all necessary shared-link inputs',
        "Governing strut, stirrup and longitudinal component results", "calculation-warning",
        'Open Analysis settings > Shear / torsion / M-V-T > Checks and methods. Enable Check combined M-V-T. Make sure that the linked component methods are correct. In Shared reinforcement, make sure that the common strut-angle range is correct. Open Combined M-V-T and examine its prerequisites and assumptions. Under Actions, enter concurrent actions in one capacity row. Open Results. Select Calculate. Open M-V-T Combined. Examine each component and the overall status.',
    ),
    Workflow(
        "review-results", 'Examine results', 'A full requested-calculation register',
        "results-overview", "Current calculation results", 'Sector shows the warnings and governing rows',
        "results-review",
        'Open Results > Results Overview. Select a check row in an Overview table. Select Open selected result. Examine each warning and each not-assessed state.',
    ),
    Workflow(
        "save-load", "Save or load a project", "A reproducible current project",
        "project", "Current inputs or a supported project file",
        'Calculate again after you load inputs', "project-file",
        'Open Project and recovery. Expand Save / Load. To save the inputs, select Download project. To load inputs, select a saved file under Load project. After loading, examine the restored inputs. Open Results. Select Calculate. Examine the new results in Results Overview.',
    ),
    Workflow(
        "report-profile", "Choose a report profile", "Brief, Standard or Audit publication",
        "report-workspace", "Current inputs and project details",
        "Profile changes presentation depth only", "report-generation",
        'With current results, open Report. Enter the project details. Select Brief, Standard or Audit. Select Generate report. Download the PDF.',
    ),
)


ALL_DESTINATIONS: Final[tuple[ManualDestination, ...]] = (
    *READING_PATHS,
    *PUBLICATION_REFERENCES,
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
    "PUBLIC_PAGE_LABELS",
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
