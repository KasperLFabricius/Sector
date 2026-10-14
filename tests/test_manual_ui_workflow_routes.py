"""Pure navigation and publication contracts for the 0.96.9 UI manual."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app import manual_information_architecture as ia

ROOT = Path(__file__).resolve().parents[1]


def _manual_copy():
    tree = ast.parse((ROOT / "app/manual.py").read_text("utf-8"))
    return "\n".join(
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def test_public_pages_preserve_internal_stage_and_manual_identities():
    assert tuple(ia.PUBLIC_PAGE_LABELS.values()) == (
        "Section", "Materials", "Actions", "Analysis settings", "Results",
        "Report", "Project and recovery", "Help and manual",
    )
    assert tuple(item.label for item in ia.INPUT_STAGES) == (
        "Analysis settings", "Section", "Material parameters", "Loads", "Project",
    )
    assert all(ia.destination(key) for key in ia.PUBLIC_PAGE_LABELS)
    assert ia.heading_anchor("Loads", 1) == "manual-loads"
    assert ia.heading_anchor("Materials", 1) == "manual-material-parameters"
    with pytest.raises(TypeError):
        ia.PUBLIC_PAGE_LABELS["loads"] = "changed"


@pytest.mark.parametrize("workflow", ia.WORKFLOWS, ids=lambda item: item.key)
def test_workflow_routes_use_public_navigation_without_changing_task_identity(workflow):
    assert ia.destination(workflow.destination_key)
    assert ia.warning_reference(workflow.warning_key)
    assert "Inputs >" not in workflow.action
    assert "Open Analysis." not in workflow.action
    if "Select Calculate." in workflow.action:
        assert workflow.action.index("Open Results") < workflow.action.index("Select Calculate.")


@pytest.mark.parametrize("warning", ia.WARNINGS, ids=lambda item: item.key)
def test_warning_corrections_name_current_pages(warning):
    assert "Inputs >" not in warning.correction
    assert "Open Analysis." not in warning.correction
    assert "open Analysis." not in warning.correction
    if "Select Calculate." in warning.correction:
        assert warning.correction.lower().index("open results") < warning.correction.index("Select Calculate.")


def test_action_help_contains_the_verified_conventions_and_paste_requirements():
    copy = _manual_copy()
    for requirement in (
        "+x points right and +y points up", "Negative $N$ means compression",
        "positive $M_x$ compresses the top face", "positive $M_y$ compresses the right face",
        "$V_x$ pairs with $M_y$", "$V_y$ pairs with $M_x$",
        "Current torsion resistance uses $|T|$", "-350 kN sustained and -120 kN instantaneous give -470 kN total",
        "Download paste headings", "required column headings", "Spreadsheet rows",
        "Blank ordinary action cells use zero", "Ambiguous grouped or mixed separators require correction",
    ):
        assert requirement in copy


def test_help_and_case_navigation_remain_explicit_in_manual():
    copy = _manual_copy()
    for requirement in (
        "Each input keeps its field-specific help", "meaning, unit, conditions and limits",
        "case, physical row and field", "case changed after the issue was recorded",
        "selected case, result view and applicable filters", "Help and manual",
    ):
        assert requirement in copy


def test_mvt_manual_keeps_shared_ownership_and_explicit_prerequisites():
    copy = _manual_copy()
    for requirement in (
        "Checks and methods", "Shared reinforcement", "Combined M-V-T",
        "Shared reinforcement has one editing location", "engineering assumptions explicit",
        "Select the applicable member scope for each case",
    ):
        combined = copy + "\n" + "\n".join(item.action for item in ia.WORKFLOWS)
        assert requirement in combined


def test_brand_and_report_coverage_are_documented_for_every_output():
    copy = _manual_copy()
    assert "The Sweco logo identifies the UI, reports and both manual formats" in copy
    assert "Coverage identifies the included checks and case families" in copy
    assert "It retains each applicable status, warning and report component" in copy
    assert "generated PDF preview" in copy


def test_old_workspace_instructions_are_retired_without_renaming_engineering_headings():
    copy = _manual_copy()
    assert "Inputs >" not in copy
    assert "Open **Analysis**" not in copy
    assert "Conventions and sign convention" in copy
    assert "Plastic capacity analysis" in copy
    assert "Cracked-section elastic analysis" in copy


def test_workspace_schematic_matches_exact_publication_identity():
    from app import publication_items as publication

    tree = ast.parse((ROOT / "app/manual.py").read_text("utf-8"))
    figures = [node for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "fig" and node.args
               and isinstance(node.args[0], ast.Name)
               and node.args[0].id == "fig_workspace_overview"]
    assert len(figures) == 1
    spec = publication.MANUAL_FIGURE_SPECS[0]
    assert spec.factory == figures[0].args[0].id
    assert spec.caption == ast.literal_eval(figures[0].args[1])
    assert spec.alternative == ast.literal_eval(figures[0].args[2])


@pytest.mark.parametrize("number,headers", [
    (11, ["Application page", "Manual destination"]),
    (76, ["Symptom", "Likely cause", "Correction"]),
])
def test_navigation_table_has_exact_ordered_publication_contract(number, headers):
    from app import publication_items as publication

    tree = ast.parse((ROOT / "app/manual.py").read_text("utf-8"))
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == "table" and node.args
             and isinstance(node.args[0], ast.List)
             and all(isinstance(item, ast.Constant) for item in node.args[0].elts)
             and ast.literal_eval(node.args[0]) == headers]
    assert len(calls) == 1
    # Evaluate this registry-only expression. No manual import or figure execution.
    rows = eval(compile(ast.Expression(calls[0].args[1]), "table_rows", "eval"),
                {"manual_ia": ia, "__builtins__": {}})
    block = ("table", headers, rows)
    spec = publication.MANUAL_TABLE_SPECS[number - 1]
    assert spec.headers == tuple(headers)
    assert publication._table_content_sha256(block) == publication.MANUAL_TABLE_CONTENT_SHA256[number - 1]
    assert publication._table_content_sha256(("table", headers, list(reversed(rows)))) != publication.MANUAL_TABLE_CONTENT_SHA256[number - 1]
    changed_rows = [list(row) for row in rows]
    changed_rows[0][-1] += " changed"
    assert publication._table_content_sha256(("table", headers, changed_rows)) != publication.MANUAL_TABLE_CONTENT_SHA256[number - 1]


def test_overview_procedures_use_exact_row_selection_control():
    copy = _manual_copy()
    assert "Select a result row in an **Overview** table" in copy
    procedures = "\n".join(w.correction for w in ia.WARNINGS) + "\n" + "\n".join(w.action for w in ia.WORKFLOWS)
    assert "Select the check row in an Overview table" in procedures
    assert "Select a check row in an Overview table" in procedures
    assert "Result details" not in procedures
    assert "Result details" not in copy
