"""Presentation destinations layered over the retained workspace authorities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Page:
    key: str
    label: str
    workspace: str
    stage: str | None
    icon: str


PAGES = (
    Page("section", "Section", "Inputs", "Section", "architecture"),
    Page("materials", "Materials", "Inputs", "Material parameters", "layers"),
    Page("actions", "Actions", "Inputs", "Loads", "table_view"),
    Page("settings", "Analysis settings", "Inputs", "Analysis settings", "tune"),
    Page("results", "Results", "Analysis", None, "analytics"),
    Page("report", "Report", "Report", None, "description"),
    Page("project", "Project and recovery", "Inputs", "Project", "folder_open"),
    Page("help", "Help and manual", "Inputs", None, "help"),
)
BY_KEY = {page.key: page for page in PAGES}


def input_page(stage):
    """Map only a registered stage to its public destination."""
    return next((p.key for p in PAGES if p.stage is not None and p.stage == stage), "section")


def legacy_destination(workspace, stage=None):
    if workspace == "Analysis":
        return "results"
    if workspace == "Report":
        return "report"
    return input_page(stage)


def context_status(inputs, state, *, pending, contract_current=True):
    """Read calculation identity without changing inputs or serializing a project."""
    if pending:
        return "Input edit pending", "Complete the current input before calculation."
    if not inputs or not state.get("results"):
        return "Not calculated", "Select Calculate to run the requested analyses."
    if not contract_current:
        return "Recalculation required", "The retained capacity results require an update."
    if state.get("result_sig") != inputs.get("signature"):
        return "Inputs changed", "Displayed results retain their calculated input snapshot."
    return "Results current", "Results match the current completed input."


def take_calculate_request(state, inputs, *, pending, generation):
    """Consume an explicit request once, bound to completed inputs and project."""
    request = state.pop("_workflow_calculate_request", None)
    if not isinstance(request, dict):
        return False
    return bool(
        not pending and inputs
        and request.get("signature") == inputs.get("signature")
        and request.get("generation") == generation
    )
